"""Scene JSON loading and validation (spec §4; contract §2.0).

``load_scene(path_or_dict)`` returns a *new* plain dict with every default
filled in, or raises :class:`SceneError` with the JSON field path of the first
rule that fails.  Unknown keys are ignored (contract §2.0).
"""

from __future__ import annotations

import json
import math
import os

from .errors import SceneError

OBJECT_TYPES = ("box", "cylinder", "sphere", "cone", "prism")
LIGHT_TYPES = ("point", "directional")
#: The six SVG layer ids in table order (contract §2.10).
LAYER_IDS = ("horizon", "objects", "form_shadow", "cast_shadow", "construction", "labels")

_UNIT_TOL = 1e-9


# ---------------------------------------------------------------------------
# small checkers
# ---------------------------------------------------------------------------

def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _number(value, field: str, positive: bool = False) -> float:
    if not _is_number(value):
        raise SceneError(field, "must be a finite number")
    if positive and value <= 0:
        raise SceneError(field, "must be > 0")
    return float(value)


def _vector(value, field: str, n: int, positive: bool = False) -> list:
    if not isinstance(value, (list, tuple)) or len(value) != n:
        raise SceneError(field, f"must be a list of {n} numbers")
    return [_number(v, f"{field}[{i}]", positive=positive) for i, v in enumerate(value)]


def _require(d: dict, key: str, field: str):
    if key not in d:
        raise SceneError(f"{field}.{key}" if field else key, "required")
    return d[key]


def _dict(value, field: str) -> dict:
    if not isinstance(value, dict):
        raise SceneError(field, "must be an object")
    return value


def _id(value, field: str, no_dot: bool) -> str:
    if not isinstance(value, str) or value == "":
        raise SceneError(field, "must be a non-empty string")
    if no_dot and "." in value:
        raise SceneError(field, "must not contain '.'")
    return value


def _norm(v) -> float:
    return math.sqrt(sum(float(c) * float(c) for c in v))


# ---------------------------------------------------------------------------
# polygon helpers (prism validation, contract §2.0)
# ---------------------------------------------------------------------------

def polygon_signed_area(poly) -> float:
    """Shoelace signed area; positive for counter-clockwise polygons (contract §2.1)."""
    area = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return 0.5 * area


def _orient(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, p, eps) -> bool:
    return (min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps
            and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps)


def _segments_intersect(a, b, c, d, eps_area: float, eps_len: float) -> bool:
    """Closed-segment intersection test for ``ab`` vs ``cd``.

    ``eps_area`` is the tolerance of the orientation tests (dimension length²),
    ``eps_len`` the tolerance of the bounding-box test used for collinear touches
    (dimension length); the two must not be mixed up (contract §2.0, §2.8).
    """
    o1, o2 = _orient(a, b, c), _orient(a, b, d)
    o3, o4 = _orient(c, d, a), _orient(c, d, b)
    if ((o1 > eps_area and o2 < -eps_area or o1 < -eps_area and o2 > eps_area)
            and (o3 > eps_area and o4 < -eps_area or o3 < -eps_area and o4 > eps_area)):
        return True
    if abs(o1) <= eps_area and _on_segment(a, b, c, eps_len):
        return True
    if abs(o2) <= eps_area and _on_segment(a, b, d, eps_len):
        return True
    if abs(o3) <= eps_area and _on_segment(c, d, a, eps_len):
        return True
    if abs(o4) <= eps_area and _on_segment(c, d, b, eps_len):
        return True
    return False


def polygon_is_simple(poly, eps_area: float, eps_len: float | None = None) -> bool:
    """True when no two non-adjacent edges touch (no self-intersection).

    ``eps_area`` (length²) is used for the orientation tests and ``eps_len``
    (length, default ``sqrt(eps_area)``) for the collinear bounding-box test.
    """
    if eps_len is None:
        eps_len = math.sqrt(eps_area)
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or (j + 1) % n == i or (i + 1) % n == j:
                continue
            c, d = poly[j], poly[(j + 1) % n]
            if _segments_intersect(a, b, c, d, eps_area, eps_len):
                return False
    return True


def _validate_polygon(value, field: str) -> list:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        raise SceneError(field, "must be a list of at least 3 [x, y] vertices")
    poly = [_vector(p, f"{field}[{i}]", 2) for i, p in enumerate(value)]
    extent = max(max(abs(c) for p in poly for c in p), 1e-300)
    eps_len = 1e-12 * extent
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if math.hypot(b[0] - a[0], b[1] - a[1]) <= eps_len:
            raise SceneError(f"{field}[{i}]", "consecutive vertices coincide")
    area = polygon_signed_area(poly)
    if abs(area) <= 1e-12 * extent * extent:
        raise SceneError(field, "zero area: vertices are collinear or the polygon is self-intersecting")
    if not polygon_is_simple(poly, 1e-12 * extent * extent, eps_len):
        raise SceneError(field, "polygon is self-intersecting")
    if area < 0:  # clockwise input is reversed silently (contract §2.0)
        poly = poly[::-1]
    return poly


# ---------------------------------------------------------------------------
# block validators
# ---------------------------------------------------------------------------

def validate_transform(value, field: str) -> dict:
    """``transform`` block (contract §2.0): optional, ``scale`` forbidden."""
    if value is None:
        return {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]}
    t = _dict(value, field)
    if "scale" in t:
        raise SceneError(f"{field}.scale", "scale is not supported; use the size parameters")
    out = {
        "position": _vector(t.get("position", [0.0, 0.0, 0.0]), f"{field}.position", 3),
        "rotation_deg": _vector(t.get("rotation_deg", [0.0, 0.0, 0.0]), f"{field}.rotation_deg", 3),
    }
    return out


def validate_object(value, field: str) -> dict:
    """One ``objects[i]`` entry (contract §2.0)."""
    o = _dict(value, field)
    out = {"id": _id(_require(o, "id", field), f"{field}.id", no_dot=True)}
    typ = _require(o, "type", field)
    if typ not in OBJECT_TYPES:
        raise SceneError(f"{field}.type", f"must be one of {', '.join(OBJECT_TYPES)}")
    out["type"] = typ
    if typ == "box":
        out["size"] = _vector(_require(o, "size", field), f"{field}.size", 3, positive=True)
    elif typ in ("cylinder", "cone"):
        out["radius"] = _number(_require(o, "radius", field), f"{field}.radius", positive=True)
        out["height"] = _number(_require(o, "height", field), f"{field}.height", positive=True)
    elif typ == "sphere":
        out["radius"] = _number(_require(o, "radius", field), f"{field}.radius", positive=True)
    elif typ == "prism":
        out["polygon"] = _validate_polygon(_require(o, "polygon", field), f"{field}.polygon")
        out["height"] = _number(_require(o, "height", field), f"{field}.height", positive=True)
    out["transform"] = validate_transform(o.get("transform"), f"{field}.transform")
    return out


def validate_light(value, field: str) -> dict:
    """One ``lights[i]`` entry (contract §2.0)."""
    lt = _dict(value, field)
    out = {"id": _id(_require(lt, "id", field), f"{field}.id", no_dot=True)}
    typ = _require(lt, "type", field)
    if typ not in LIGHT_TYPES:
        raise SceneError(f"{field}.type", f"must be one of {', '.join(LIGHT_TYPES)}")
    out["type"] = typ
    if typ == "point":
        out["position"] = _vector(_require(lt, "position", field), f"{field}.position", 3)
    else:
        d = _vector(_require(lt, "direction", field), f"{field}.direction", 3)
        if abs(_norm(d) - 1.0) > _UNIT_TOL:
            raise SceneError(f"{field}.direction", "must be a unit vector (|d| = 1 within 1e-9)")
        out["direction"] = d
    return out


def validate_receiver(value, field: str) -> dict:
    """One ``receivers[i]`` entry (contract §2.0 as amended by §5.1.1): any plane ``n·x + d = 0`` with
    ``|n| = 1``, optional convex ``bounds`` (:func:`validate_bounds`).  The rules that need the
    receiver's index or the other blocks (unbounded only at index 0 and only for the ground, bounds
    above the ground, disjoint ids) are checked by :func:`validate_scene`."""
    r = _dict(value, field)
    out = {"id": _id(_require(r, "id", field), f"{field}.id", no_dot=True)}
    typ = _require(r, "type", field)
    if typ != "plane":
        raise SceneError(f"{field}.type", "must be 'plane'")
    out["type"] = "plane"
    n = _vector(_require(r, "normal", field), f"{field}.normal", 3)
    if abs(_norm(n) - 1.0) > _UNIT_TOL:
        raise SceneError(f"{field}.normal", "must be a unit vector (|n| = 1 within 1e-9)")
    offset = _number(r.get("offset", 0.0), f"{field}.offset")
    out["bounds"] = None if r.get("bounds") is None else validate_bounds(r["bounds"], n, offset, f"{field}.bounds")
    if out["bounds"] is None and _is_ground(n, offset):
        n, offset = [0.0, 0.0, 1.0], 0.0      # the unbounded ground keeps the literal v1 plane
    out["normal"] = n
    out["offset"] = offset
    return out


def validate_camera(value, field: str = "camera") -> dict:
    """``camera`` block (contract §2.0): target form or yaw/pitch form, exactly one."""
    c = _dict(value, field)
    out = {"position": _vector(_require(c, "position", field), f"{field}.position", 3)}
    has_target = "target" in c
    has_yp = "yaw_deg" in c or "pitch_deg" in c
    if has_target and has_yp:
        raise SceneError(field, "give either target or yaw_deg + pitch_deg, not both")
    if has_target:
        t = _vector(c["target"], f"{field}.target", 3)
        if _norm([t[i] - out["position"][i] for i in range(3)]) <= 1e-12:
            raise SceneError(f"{field}.target", "must differ from position")
        out["target"] = t
    elif has_yp:
        if "yaw_deg" not in c or "pitch_deg" not in c:
            raise SceneError(field, "yaw_deg and pitch_deg must be given together")
        out["yaw_deg"] = _number(c["yaw_deg"], f"{field}.yaw_deg")
        out["pitch_deg"] = _number(c["pitch_deg"], f"{field}.pitch_deg")
    else:
        raise SceneError(field, "needs target or yaw_deg + pitch_deg")
    out["roll_deg"] = _number(c.get("roll_deg", 0.0), f"{field}.roll_deg")
    out["focal_length_mm"] = _number(_require(c, "focal_length_mm", field), f"{field}.focal_length_mm", positive=True)
    out["frame_mm"] = _vector(_require(c, "frame_mm", field), f"{field}.frame_mm", 2, positive=True)
    out["shift_mm"] = _vector(c.get("shift_mm", [0.0, 0.0]), f"{field}.shift_mm", 2)
    out["near_m"] = _number(c.get("near_m", 0.05), f"{field}.near_m", positive=True)
    return out


def validate_output(value, frame_mm, field: str = "output") -> dict:
    """``output`` block (contract §2.0): canvas aspect must equal the frame aspect."""
    o = _dict(value, field)
    canvas = _vector(_require(o, "canvas_mm", field), f"{field}.canvas_mm", 2, positive=True)
    if abs(canvas[0] / canvas[1] - frame_mm[0] / frame_mm[1]) > 1e-9:
        ratio = frame_mm[0] / frame_mm[1]
        raise SceneError(f"{field}.canvas_mm",
                         f"aspect ratio {canvas[0]:g}/{canvas[1]:g} = {canvas[0] / canvas[1]:.4g} must equal "
                         f"camera.frame_mm aspect ratio {frame_mm[0]:g}/{frame_mm[1]:g} = {ratio:.4g} "
                         f"(e.g. canvas_mm [{canvas[1] * ratio:g}, {canvas[1]:g}] or frame_mm "
                         f"[{frame_mm[0]:g}, {frame_mm[0] * canvas[1] / canvas[0]:g}])")
    layers = o.get("layers", list(LAYER_IDS))
    if not isinstance(layers, (list, tuple)):
        raise SceneError(f"{field}.layers", "must be a list of layer ids")
    if not layers:
        raise SceneError(f"{field}.layers", "must not be empty (omit the key to get all six layers)")
    for i, name in enumerate(layers):
        if name not in LAYER_IDS:
            raise SceneError(f"{field}.layers[{i}]", f"must be one of {', '.join(LAYER_IDS)}")
    if len(set(layers)) != len(layers):
        raise SceneError(f"{field}.layers", "layer ids must be unique")
    out = {
        "canvas_mm": canvas,
        "layers": [name for name in LAYER_IDS if name in layers],
        "png_dpi": _number(o.get("png_dpi", 300), f"{field}.png_dpi", positive=True),
    }
    out.update(validate_hidden_output(o, field))
    return out


def validate_scene(scene) -> dict:
    """Validate a scene dict against the table of contract §2.0; returns a new dict with defaults."""
    s = _dict(scene, "scene")
    version = _require(s, "version", "")
    if version != "0.1":
        raise SceneError("version", "must be '0.1'")
    units = s.get("units", "m")
    if units != "m":
        raise SceneError("units", "must be 'm'")
    up = s.get("up", "z")
    if up != "z":
        raise SceneError("up", "must be 'z'")

    objects = _require(s, "objects", "")
    if not isinstance(objects, list) or len(objects) == 0:
        raise SceneError("objects", "must be a non-empty list")
    out_objects, seen = [], set()
    for i, o in enumerate(objects):
        vo = validate_object(o, f"objects[{i}]")
        if vo["id"] in seen:
            raise SceneError(f"objects[{i}].id", f"duplicate object id {vo['id']!r}")
        seen.add(vo["id"])
        out_objects.append(vo)

    lights = _require(s, "lights", "")
    if not isinstance(lights, list) or len(lights) == 0:
        raise SceneError("lights", "must be a non-empty list")
    out_lights, seen = [], set()
    for i, lt in enumerate(lights):
        vl = validate_light(lt, f"lights[{i}]")
        if vl["id"] in seen:
            raise SceneError(f"lights[{i}].id", f"duplicate light id {vl['id']!r}")
        seen.add(vl["id"])
        out_lights.append(vl)
    validate_lights_in_scene(out_lights, out_objects)

    receivers = _require(s, "receivers", "")
    if not isinstance(receivers, list) or len(receivers) == 0:
        raise SceneError("receivers", "must be a non-empty list")
    out_receivers = [validate_receiver(r, f"receivers[{i}]") for i, r in enumerate(receivers)]
    validate_receivers_in_scene(out_receivers, out_objects, out_lights)

    camera = validate_camera(_require(s, "camera", ""), "camera")
    output = validate_output(_require(s, "output", ""), camera["frame_mm"], "output")

    return {
        "version": "0.1",
        "units": "m",
        "up": "z",
        "objects": out_objects,
        "lights": out_lights,
        "receivers": out_receivers,
        "camera": camera,
        "output": output,
    }


def load_scene(path_or_dict) -> dict:
    """Load a scene from a JSON file path or a dict and validate it (contract §3)."""
    if isinstance(path_or_dict, (str, os.PathLike)):
        with open(path_or_dict, "r", encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except json.JSONDecodeError as exc:
                raise SceneError("", f"invalid JSON: {exc}") from exc
    else:
        data = path_or_dict
    return validate_scene(data)


def load_camera(path_or_dict) -> dict:
    """Load a camera override (a file holding either a ``camera`` block or a scene with one)."""
    if isinstance(path_or_dict, (str, os.PathLike)):
        with open(path_or_dict, "r", encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except json.JSONDecodeError as exc:
                raise SceneError("", f"invalid JSON: {exc}") from exc
    else:
        data = path_or_dict
    if isinstance(data, dict) and "camera" in data and "position" not in data:
        data = data["camera"]
    return validate_camera(data, "camera")


# ---------------------------------------------------------------------------
# M4 (contract §5.1.1, §5.0.1): bounded receivers, hidden-line output switches, reserved ids
# ---------------------------------------------------------------------------

#: Ids that no object, receiver or light may take (the ``*.hidden`` SVG sub-groups, contract §5.0.1).
RESERVED_IDS = ("hidden",)
#: ``output.hidden_style`` values (contract §5.1.8).
HIDDEN_STYLES = ("dashed", "omit")


def _is_ground(n, offset) -> bool:
    """The plane is the ground ``z = 0`` (``normal == [0, 0, 1]`` and ``offset == 0`` within 1e-9)."""
    return (all(abs(float(n[i]) - (0.0, 0.0, 1.0)[i]) <= _UNIT_TOL for i in range(3))
            and abs(float(offset)) <= _UNIT_TOL)


def validate_bounds(value, normal, offset, field: str) -> list:
    """``receivers[i].bounds`` (contract §5.1.1): >= 3 world points on the plane ``n·x + d = 0``
    forming a simple strictly convex polygon; a clockwise list (about ``n``) is reversed silently,
    so the stored order is counter-clockwise about ``n`` seen from the positive side."""
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        raise SceneError(field, "must be a list of at least 3 [x, y, z] vertices")
    pts = [_vector(p, f"{field}[{k}]", 3) for k, p in enumerate(value)]
    n = [float(c) for c in normal]
    d = float(offset)
    ext = max(1.0, max(abs(c) for p in pts for c in p))
    m = len(pts)
    for k, p in enumerate(pts):                                       # (1) coplanar
        if abs(n[0] * p[0] + n[1] * p[1] + n[2] * p[2] + d) > 1e-9 * ext:
            raise SceneError(f"{field}[{k}]", "must lie in the receiver plane (|n·b + offset| <= 1e-9 · extent)")
    edges = [[pts[(k + 1) % m][j] - pts[k][j] for j in range(3)] for k in range(m)]
    lengths = [_norm(e) for e in edges]
    for k in range(m):                                                # (2) consecutive vertices distinct
        if not lengths[k] > 1e-12 * ext:
            raise SceneError(f"{field}[{k}]", "consecutive vertices coincide")
    cross, dot = [], []
    for k in range(m):
        a, b = edges[k], edges[(k + 1) % m]
        c = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
        cross.append(c[0] * n[0] + c[1] * n[1] + c[2] * n[2])
        dot.append(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])
    message = "must be a simple strictly convex polygon"
    sigma = 1.0 if cross[0] > 0.0 else -1.0
    for k in range(m):                                                # (3) strictly convex
        if sigma * cross[k] <= 1e-9 * lengths[k] * lengths[(k + 1) % m]:
            raise SceneError(field, message)
    turning = sum(math.atan2(sigma * cross[k], dot[k]) for k in range(m))
    if abs(turning - 2.0 * math.pi) > 1e-9 * m:                        # (4) simple (no star polygon)
        raise SceneError(field, message)
    if sigma < 0.0:                                                   # (5) clockwise -> reversed silently
        pts = pts[::-1]
    return pts


def validate_hidden_output(o: dict, field: str = "output") -> dict:
    """``output.hidden_lines`` (boolean, default false) and ``output.hidden_style`` (``"dashed"``
    default, or ``"omit"``) of contract §5.1.1 / §5.0.1."""
    hidden = o.get("hidden_lines", False)
    if not isinstance(hidden, bool):
        raise SceneError(f"{field}.hidden_lines", "must be a boolean")
    style = o.get("hidden_style", "dashed")
    if style not in HIDDEN_STYLES:
        raise SceneError(f"{field}.hidden_style", f"must be one of {', '.join(HIDDEN_STYLES)}")
    return {"hidden_lines": hidden, "hidden_style": style}


def validate_receivers_in_scene(receivers: list, objects: list, lights: list) -> None:
    """The scene-level receiver rules of contract §5.1.1 / §5.0.1: ids unique, not reserved and
    disjoint from object and light ids; a receiver without ``bounds`` only at index 0 and only for
    the ground plane; with an unbounded ground every bounds vertex is above it (``b_z >= -1e-9·ext``).
    Also the reserved-id rule for object and light ids (``hidden``)."""
    for kind, items in (("objects", objects), ("lights", lights), ("receivers", receivers)):
        for i, item in enumerate(items):
            if item["id"] in RESERVED_IDS:
                raise SceneError(f"{kind}[{i}].id", "reserved id")
    object_ids = {o["id"] for o in objects}
    light_ids = {lt["id"] for lt in lights}
    seen = set()
    for i, r in enumerate(receivers):
        rid = r["id"]
        if rid in seen:
            raise SceneError(f"receivers[{i}].id", f"duplicate receiver id {rid!r}")
        seen.add(rid)
        if rid in object_ids:
            raise SceneError(f"receivers[{i}].id", f"receiver id {rid!r} is also an object id")
        if rid in light_ids:
            raise SceneError(f"receivers[{i}].id", f"receiver id {rid!r} is also a light id")
        if r["bounds"] is None and not (i == 0 and _is_ground(r["normal"], r["offset"])):
            raise SceneError(f"receivers[{i}].bounds", "required unless the receiver is the ground plane at receivers[0]")
    if receivers[0]["bounds"] is None:
        for i, r in enumerate(receivers):
            if r["bounds"] is None:
                continue
            ext = max(1.0, max(abs(c) for p in r["bounds"] for c in p))
            for k, p in enumerate(r["bounds"]):
                if p[2] < -1e-9 * ext:
                    raise SceneError(f"receivers[{i}].bounds[{k}]", "below the ground receiver")


# ---------------------------------------------------------------------------
# M6 (contract §5.3.0, §5.0.1): any number of lights, multi-light reserved ids
# ---------------------------------------------------------------------------

#: Light ids rejected in a multi-light scene (``len(lights) >= 2``): the ids of the
#: ``cast_shadow.umbra`` / ``form_shadow.core`` SVG sub-groups (contract §5.3.0, §5.3.6).
RESERVED_LIGHT_IDS_MULTI = ("umbra", "core")
#: Object ids rejected in a multi-light scene (``form_shadow.core`` names the core group alone, §5.0.1).
RESERVED_OBJECT_IDS_MULTI = ("core",)


def validate_lights_in_scene(lights: list, objects: list) -> None:
    """The multi-light id rules of contract §5.3.0 / §5.0.1: with at least two lights the light ids
    ``umbra`` / ``core`` and the object id ``core`` are reserved (a single-light scene keeps them
    valid).  ``hidden`` (always reserved) and receiver ∩ light = ∅ are checked by
    :func:`validate_receivers_in_scene`."""
    if len(lights) < 2:
        return
    for i, lt in enumerate(lights):
        if lt["id"] in RESERVED_LIGHT_IDS_MULTI:
            raise SceneError(f"lights[{i}].id", "reserved id in a multi-light scene")
    for i, o in enumerate(objects):
        if o["id"] in RESERVED_OBJECT_IDS_MULTI:
            raise SceneError(f"objects[{i}].id", "reserved id in a multi-light scene")
