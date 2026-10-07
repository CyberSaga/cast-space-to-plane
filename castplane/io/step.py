"""STEP import: semantics on top of :mod:`castplane.io.part21` (contract §5.5.3–§5.5.7).

A *loader* (spec §8): it runs before ``validate_scene`` through the expansion step of §5.0.2 and
turns a loader-only ``{"type": "step", "path": ...}`` object into ordinary §2.0 objects.  The core
never sees a STEP file.  Standard library + numpy only; OCP (optional extra ``step``) is imported
by :func:`tessellate_step` alone.

    report        = import_step(path, fallback="error", solid=None, obj_id=None, transform=None, field="step")
    objects, notes = expand_step_object(obj, field, base_dir)        # EXPANDERS["step"]

Recognition (§5.5.5) classifies every ``MANIFOLD_SOLID_BREP`` by its face-type signature
(cylinder, sphere, cone, box) with the per-file tolerances of §5.5.4, reading no orientation sign
of the file; every emitted length goes through :func:`to_metres` (a division, never a
multiplication by 0.001) and every rotation through :func:`euler_zyx_deg`.
"""

from __future__ import annotations

import copy
import math
import os
import re

import numpy as np

from ..errors import SceneError, merge_warnings
from ..scene import _id as _scene_id
from ..scene import validate_transform
from ..transform import euler_zyx_matrix
from .part21 import Part21SyntaxError, parse

__all__ = ["StepError", "STEP_WARNING_CODES", "DEFAULT_SCENE_TEMPLATE", "make_step_warning", "to_metres",
           "import_step", "expand_step_object", "recognise_solid", "euler_zyx_deg", "tessellate_step",
           "mesh_object_from_triangles"]


class StepError(SceneError):
    """A STEP import failure (contract §5.5.6): ``field`` is the JSON path of the step object's
    ``path`` (or the ``field`` given to :func:`import_step`), ``entity`` the entity id (``"#15"``)
    the message starts with, or ``None``."""

    def __init__(self, field: str, message: str, entity: str | None = None):
        self.entity = entity
        super().__init__(field, message)


#: The STEP importer notes (contract §5.5.6; the STEP sub-list of ``castplane.io.IMPORT_NOTE_CODES``).
STEP_WARNING_CODES = {
    "STEP_UNIT_ASSUMED_MM": "the file declares no length unit; millimetres assumed",
    "STEP_ANGLE_UNIT_ASSUMED_RAD": "the file declares no plane angle unit; radians assumed",
    "STEP_SOLID_TESSELLATED": "the solid is not a supported primitive; tessellated into a mesh object",
}

#: The ``version`` / ``units`` / ``up`` / ``lights`` / ``receivers`` / ``camera`` / ``output`` blocks of
#: ``examples/basic.json`` (contract §5.5.8; the spec §4 lamp, ground, 35 mm camera, canvas 273 x 182).
DEFAULT_SCENE_TEMPLATE = {
    "version": "0.1",
    "units": "m",
    "up": "z",
    "lights": [{"id": "lamp", "type": "point", "position": [0.0, 3.0, 3.5]}],
    "receivers": [{"id": "ground", "type": "plane", "normal": [0, 0, 1], "offset": 0.0}],
    "camera": {"position": [0.0, 0.0, 1.5], "target": [0.0, 5.0, 1.0], "roll_deg": 0, "focal_length_mm": 35,
               "frame_mm": [36, 24], "shift_mm": [0.0, 0.0], "near_m": 0.05},
    "output": {"canvas_mm": [273, 182],
               "layers": ["horizon", "objects", "form_shadow", "cast_shadow", "construction", "labels"],
               "png_dpi": 300},
}

#: Direction predicates (parallel / perpendicular / equal directions), contract §5.5.4.
TOL_DIR_STEP = 1e-7

_SUPPORTED = "cylinder, sphere, cone, box"
_FIELD = "step"           # placeholder field of the helpers; import_step re-raises with its own field
_NO_SOLID_TYPES = ("BREP_WITH_VOIDS", "FACETED_BREP", "GEOMETRIC_CURVE_SET", "GEOMETRIC_SET", "MAPPED_ITEM",
                   "SHELL_BASED_SURFACE_MODEL", "TESSELLATED_SHELL", "TESSELLATED_SOLID")
_SURFACES = ("PLANE", "CYLINDRICAL_SURFACE", "SPHERICAL_SURFACE", "CONICAL_SURFACE")


def make_step_warning(code: str, ids=(), message: str | None = None) -> dict:
    """An importer note ``{code, ids, message}`` against :data:`STEP_WARNING_CODES` (contract §5.5.6)."""
    if code not in STEP_WARNING_CODES:
        raise ValueError(f"unknown STEP note code {code!r}")
    return {"code": code, "ids": [str(i) for i in ids],
            "message": STEP_WARNING_CODES[code] if message is None else str(message)}


def to_metres(x, unit_divisor):
    """``float(x) / unit_divisor + 0.0`` (contract §5.5.3): the only unit conversion, a division
    (correctly rounded, so integer and dyadic millimetre values give exactly the metre literal).
    Scalars give a ``float``; lists, tuples and arrays give a (nested) list of ``float``."""
    if isinstance(x, np.ndarray):
        x = x.tolist()
    if isinstance(x, (list, tuple)):
        return [to_metres(v, unit_divisor) for v in x]
    return float(x) / float(unit_divisor) + 0.0


# --------------------------------------------------------------------------- small vector helpers
# Plain Python floats (no BLAS, no numpy scalars): every operation is a correctly rounded IEEE
# operation in a fixed order, so recognition and the emitted numbers are platform independent.
def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b) -> tuple:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _sub(a, b) -> tuple:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b) -> tuple:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(s, a) -> tuple:
    return (s * a[0], s * a[1], s * a[2])


def _norm(a) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    if not n > 0.0 or not math.isfinite(n):
        return None
    return (a[0] / n, a[1] / n, a[2] / n)


# --------------------------------------------------------------------------- entity access
def _err(message: str, entity: str | None = None) -> StepError:
    return StepError(_FIELD, message, entity)


def _parts(inst) -> list:
    """``[(NAME, args), ...]`` of a simple or complex instance."""
    name, args = inst
    return list(args) if name == "COMPLEX" else [(name, args)]


def _type_name(inst) -> str:
    name, args = inst
    return "+".join(n for n, _ in args) if name == "COMPLEX" else name


def _get(entities: dict, ref, names) -> tuple:
    """The instance ``ref`` (must be one of ``names``) as ``(name, args)``."""
    if not isinstance(ref, str) or ref not in entities:
        raise _err(f"{ref}: referenced entity does not exist" if isinstance(ref, str)
                   else f"syntax: expected an entity reference, found {ref!r}")
    name, args = entities[ref]
    if name not in names:
        raise _err(f"{ref}: expected {' or '.join(names)}, found {_type_name(entities[ref])}", ref)
    return name, args


def _arg(args, k: int, ref: str):
    if not isinstance(args, list) or k >= len(args):
        raise _err(f"{ref}: too few parameters", ref)
    return args[k]


def _num(v, ref: str) -> float:
    if isinstance(v, tuple) and len(v) == 2:     # a typed value, e.g. POSITIVE_LENGTH_MEASURE(300.)
        v = v[1]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(_as_float(v)):
        raise _err(f"{ref}: expected a number, found {v!r}", ref)
    return float(v)


def _as_float(v) -> float:
    """``float(v)``, ``inf`` for an integer beyond the double range (never ``OverflowError``)."""
    try:
        return float(v)
    except OverflowError:
        return math.inf


def _point(entities: dict, ref) -> tuple:
    _, args = _get(entities, ref, ("CARTESIAN_POINT",))
    coords = _arg(args, 1, ref)
    if not isinstance(coords, list) or len(coords) != 3:
        raise _err(f"{ref}: expected a 3D CARTESIAN_POINT", ref)
    return tuple(_num(c, ref) for c in coords)


def _direction(entities: dict, ref) -> tuple:
    _, args = _get(entities, ref, ("DIRECTION",))
    coords = _arg(args, 1, ref)
    if not isinstance(coords, list) or len(coords) != 3:
        raise _err(f"{ref}: expected a 3D DIRECTION", ref)
    d = _unit(tuple(_num(c, ref) for c in coords))
    if d is None:
        raise _err(f"unsupported: degenerate placement {ref} (zero direction)", ref)
    return d


def _placement(entities: dict, ref) -> tuple:
    """``AXIS2_PLACEMENT_3D(name, location, axis | $, ref_direction | $)`` -> ``(o, a, e1, e2)``
    (contract §5.5.4): ``a`` normalised (default ``z``), ``e1`` the projected, normalised
    ``ref_direction`` (default the first of ``x``, ``y`` not parallel to ``a``), ``e2 = a x e1``."""
    _, args = _get(entities, ref, ("AXIS2_PLACEMENT_3D",))
    o = _point(entities, _arg(args, 1, ref))
    axis = _arg(args, 2, ref)
    a = (0.0, 0.0, 1.0) if axis is None else _direction(entities, axis)
    rd = _arg(args, 3, ref) if len(args) > 3 else None
    if rd is None:
        r = next(c for c in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)) if _norm(_cross(c, a)) > TOL_DIR_STEP)
    else:
        r = _direction(entities, rd)
        if _norm(_cross(r, a)) <= TOL_DIR_STEP:
            raise _err(f"unsupported: degenerate placement {ref} (ref_direction parallel to axis)", ref)
    e1 = _unit(_sub(r, _scale(_dot(r, a), a)))
    e2 = _cross(a, e1)
    return o, a, e1, e2


# --------------------------------------------------------------------------- units (§5.5.3)
def _unit_candidates(entities: dict) -> list:
    """The unit entities a ``GLOBAL_UNIT_ASSIGNED_CONTEXT`` names (all entities when none does)."""
    refs = []
    for inst in entities.values():
        for name, args in _parts(inst):
            if name == "GLOBAL_UNIT_ASSIGNED_CONTEXT" and args and isinstance(args[0], list):
                refs.extend(r for r in args[0] if isinstance(r, str) and r in entities)
    if not refs:
        refs = list(entities)
    return sorted(set(refs), key=lambda r: int(r[1:]))


def _si(parts: dict):
    args = parts.get("SI_UNIT")
    if args is None or len(args) < 2:
        return None
    return args[-2], args[-1]


def _length_unit(entities: dict) -> tuple:
    """``(unit, unit_divisor, notes)``: ``("mm", 1000.0)`` or ``("m", 1.0)``; no length unit ->
    mm with ``STEP_UNIT_ASSUMED_MM``; anything else -> ``StepError("unsupported: length unit ...")``."""
    found = {}
    for ref in _unit_candidates(entities):
        parts = dict(_parts(entities[ref]))
        if "LENGTH_UNIT" not in parts:
            continue
        si = _si(parts)
        if "CONVERSION_BASED_UNIT" in parts:
            cb = parts["CONVERSION_BASED_UNIT"]
            label = cb[0] if cb and isinstance(cb[0], str) else "?"
            raise _err(f"unsupported: length unit {ref} '{label}' (conversion based; only mm and m)", ref)
        if si is None or si[1] != ".METRE." or si[0] not in (None, ".MILLI."):
            text = f"SI_UNIT({si[0] or '$'},{si[1]})" if si is not None else _type_name(entities[ref])
            raise _err(f"unsupported: length unit {ref} {text} (only mm and m)", ref)
        found[ref] = ("m", 1.0) if si[0] is None else ("mm", 1000.0)
    if not found:
        return "mm", 1000.0, [make_step_warning("STEP_UNIT_ASSUMED_MM")]
    values = sorted(set(found.values()), key=lambda u: u[1])
    if len(values) > 1:
        raise _err("unsupported: length units with different scales in one file ("
                   + ", ".join(f"{r} {u}" for r, (u, _) in found.items()) + ")")
    return values[0][0], values[0][1], []


def _radian(entities: dict, ref) -> bool:
    if not isinstance(ref, str) or ref not in entities:
        return False
    parts = dict(_parts(entities[ref]))
    return "PLANE_ANGLE_UNIT" in parts and _si(parts) == (None, ".RADIAN.")


def _angle_unit(entities: dict) -> tuple:
    """``(angle_factor, notes)``: radians per file angle unit (contract §5.5.3)."""
    found = {}
    for ref in _unit_candidates(entities):
        parts = dict(_parts(entities[ref]))
        if "PLANE_ANGLE_UNIT" not in parts:
            continue
        si = _si(parts)
        if "CONVERSION_BASED_UNIT" in parts:
            cb = parts["CONVERSION_BASED_UNIT"]
            m = cb[1] if len(cb) > 1 else None
            inst = entities.get(m) if isinstance(m, str) else None
            if inst is None or inst[0] != "PLANE_ANGLE_MEASURE_WITH_UNIT" or len(inst[1]) < 2 \
                    or not _radian(entities, inst[1][1]):
                raise _err(f"unsupported: plane angle unit {ref} (conversion must be a "
                           f"PLANE_ANGLE_MEASURE_WITH_UNIT in radians)", ref)
            found[ref] = _num(inst[1][0], m)
        elif si == (None, ".RADIAN."):
            found[ref] = 1.0
        else:
            raise _err(f"unsupported: plane angle unit {ref} {_type_name(entities[ref])}", ref)
    if not found:
        return 1.0, [make_step_warning("STEP_ANGLE_UNIT_ASSUMED_RAD")]
    values = sorted(set(found.values()))
    if len(values) > 1:
        raise _err("unsupported: plane angle units with different scales in one file")
    return values[0], []


def _tolerance(entities: dict, unit: str) -> float:
    """``tol`` in file units (contract §5.5.4): ``1e-6 · max(1 mm, extent) `` expressed in file units."""
    k = 1000.0 if unit == "m" else 1.0
    extent = 0.0
    for ref, (name, args) in entities.items():
        if name == "CARTESIAN_POINT" and len(args) > 1 and isinstance(args[1], list):
            for c in args[1]:
                if isinstance(c, (int, float)) and not isinstance(c, bool):
                    v = _as_float(c)
                    if not math.isfinite(v):     # review fix: an inf here made tol = inf
                        raise _err(f"{ref}: non-finite coordinate {c!r}", ref)
                    extent = max(extent, abs(v))
    extent_mm = max(1.0, k * extent)
    return 1e-6 * extent_mm / k


# --------------------------------------------------------------------------- topology (§5.5.4)
def _solid_ids(entities: dict) -> list:
    """Every ``MANIFOLD_SOLID_BREP`` in ascending numeric entity id."""
    ids = [r for r, (name, _) in entities.items() if name == "MANIFOLD_SOLID_BREP"]
    if not ids:
        counts = {}
        for inst in entities.values():
            for name, _ in _parts(inst):
                if name in _NO_SOLID_TYPES:
                    counts[name] = counts.get(name, 0) + 1
        found = ", ".join(f"{n} ×{c}" for n, c in sorted(counts.items())) or "nothing"
        raise _err(f"unsupported: no MANIFOLD_SOLID_BREP solid (found: {found})")
    return sorted(ids, key=lambda r: int(r[1:]))


def _check_assembly(entities: dict, tol: float) -> None:
    """Identity-only assemblies (contract §5.5.4): every ``ITEM_DEFINED_TRANSFORMATION`` maps equal
    placements; any ``MAPPED_ITEM`` is unsupported."""
    for ref in sorted(entities, key=lambda r: int(r[1:])):
        name, args = entities[ref]
        if name == "MAPPED_ITEM":
            raise _err(f"unsupported: MAPPED_ITEM {ref} (single placement only)", ref)
        if name != "ITEM_DEFINED_TRANSFORMATION":
            continue
        o1, a1, x1, _ = _placement(entities, _arg(args, 2, ref))
        o2, a2, x2, _ = _placement(entities, _arg(args, 3, ref))
        if (_norm(_sub(o1, o2)) > tol or _norm(_sub(a1, a2)) > TOL_DIR_STEP
                or _norm(_sub(x1, x2)) > TOL_DIR_STEP):
            raise _err(f"unsupported: assembly transformation {ref} is not the identity (single placement only)", ref)


class _Reject(Exception):
    """A rule-specific reason why a solid is not the primitive its face signature selected."""


def _vertex(entities: dict, ref) -> tuple:
    _, args = _get(entities, ref, ("VERTEX_POINT",))
    return _point(entities, _arg(args, 1, ref))


def _edge(entities: dict, ref, rec: dict) -> None:
    """One ``ORIENTED_EDGE`` / ``EDGE_CURVE``: its vertex points and ``CIRCLE`` radius into ``rec``."""
    name, args = _get(entities, ref, ("ORIENTED_EDGE", "EDGE_CURVE"))
    if name == "ORIENTED_EDGE":
        ref = _arg(args, 3, ref)
        name, args = _get(entities, ref, ("EDGE_CURVE", "ORIENTED_EDGE"))
        if name != "EDGE_CURVE":
            raise _Reject(f"{ref}: nested ORIENTED_EDGE")
    rec["vertices"].append(_vertex(entities, _arg(args, 1, ref)))
    rec["vertices"].append(_vertex(entities, _arg(args, 2, ref)))
    geom = _arg(args, 3, ref)
    if not isinstance(geom, str) or geom not in entities:
        raise _err(f"{ref}: edge geometry {geom!r} does not exist", ref)
    gname, gargs = entities[geom]
    if gname in ("SURFACE_CURVE", "SEAM_CURVE"):
        geom = _arg(gargs, 1, geom)
        if not isinstance(geom, str) or geom not in entities:
            raise _err(f"{ref}: edge geometry {geom!r} does not exist", ref)
        gname, gargs = entities[geom]
    if gname == "CIRCLE":
        radius = _num(_arg(gargs, 2, geom), geom)
        if not radius > 0.0:                     # ISO 10303-42 positive_length_measure (review fix)
            raise _err(f"{geom}: CIRCLE radius must be > 0, found {radius!r}", geom)
        rec["circles"].append(radius)


def _face_records(entities: dict, solid_ref: str, angle_factor: float) -> list:
    """The faces of a solid in ascending face entity id: ``{"id", "surface", "o", "a", "e1", "e2",
    "radius", "semi", "vertices", "circles"}`` (geometry keys only for the four supported surfaces)."""
    _, sargs = _get(entities, solid_ref, ("MANIFOLD_SOLID_BREP",))
    shell = _arg(sargs, 1, solid_ref)
    _, shargs = _get(entities, shell, ("CLOSED_SHELL",))
    faces = _arg(shargs, 1, shell)
    if not isinstance(faces, list) or not faces:
        raise _err(f"{shell}: empty CLOSED_SHELL", shell)
    out = []
    for fref in sorted(set(faces), key=lambda r: int(r[1:]) if isinstance(r, str) and r[1:].isdigit() else -1):
        _, fargs = _get(entities, fref, ("ADVANCED_FACE", "FACE_SURFACE"))
        geom = _arg(fargs, 2, fref)
        if not isinstance(geom, str) or geom not in entities:
            raise _err(f"{fref}: face geometry {geom!r} does not exist", fref)
        surface = _type_name(entities[geom])
        rec = {"id": fref, "surface": surface, "vertices": [], "circles": [], "loops_ok": True}
        if surface in _SURFACES:
            gargs = entities[geom][1]
            rec["o"], rec["a"], rec["e1"], rec["e2"] = _placement(entities, _arg(gargs, 1, geom))
            if surface != "PLANE":
                rec["radius"] = _num(_arg(gargs, 2, geom), geom)
                # ISO 10303-42: cylindrical / spherical radius > 0, conical radius >= 0 (review fix)
                if rec["radius"] < 0.0 or (rec["radius"] == 0.0 and surface != "CONICAL_SURFACE"):
                    raise _err(f"{geom}: {surface} radius must be {'≥' if surface == 'CONICAL_SURFACE' else '>'} 0, "
                               f"found {rec['radius']!r}", geom)
            if surface == "CONICAL_SURFACE":
                rec["semi"] = _num(_arg(gargs, 3, geom), geom) * angle_factor
        bounds = _arg(fargs, 1, fref)
        for bref in bounds if isinstance(bounds, list) else []:
            _, bargs = _get(entities, bref, ("FACE_BOUND", "FACE_OUTER_BOUND"))
            loop = _arg(bargs, 1, bref)
            lname, largs = _get(entities, loop, ("EDGE_LOOP", "VERTEX_LOOP", "POLY_LOOP"))
            if lname == "VERTEX_LOOP":
                rec["vertices"].append(_vertex(entities, _arg(largs, 1, loop)))
            elif lname == "EDGE_LOOP":
                try:
                    for eref in _arg(largs, 1, loop) or []:
                        _edge(entities, eref, rec)
                except _Reject:
                    rec["loops_ok"] = False
            else:
                rec["loops_ok"] = False
        out.append(rec)
    return out


def _counts(faces: list) -> dict:
    counts = {}
    for f in faces:
        counts[f["surface"]] = counts.get(f["surface"], 0) + 1
    return dict(sorted(counts.items()))


# --------------------------------------------------------------------------- recognisers (§5.5.5)
def _parallel(a, b) -> bool:
    return _norm(_cross(a, b)) <= TOL_DIR_STEP


def _frame_rotation(e1, e2, a) -> list:
    """``euler_zyx_deg`` of the frame with columns ``e1``, ``e2``, ``a``."""
    return euler_zyx_deg([[e1[0], e2[0], a[0]], [e1[1], e2[1], a[1]], [e1[2], e2[2], a[2]]])


def _recognise_cylinder(faces: list, ud: float, tol: float) -> dict:
    cyl = [f for f in faces if f["surface"] == "CYLINDRICAL_SURFACE"]
    planes = [f for f in faces if f["surface"] == "PLANE"]
    c = cyl[0]
    o, a, e1, r = c["o"], c["a"], c["e1"], c["radius"]
    for f in cyl[1:]:
        if abs(f["radius"] - r) > tol:
            raise _Reject("cylindrical faces with different radii")
        if not _parallel(f["a"], a) or _norm(_cross(_sub(f["o"], o), a)) > tol:
            raise _Reject("cylindrical faces on different axes")
    if len(planes) != 2:
        raise _Reject(f"{len(planes)} planar face(s), a cylinder has 2")
    if not all(_parallel(p["a"], a) for p in planes):
        raise _Reject("a cap plane is not perpendicular to the axis")
    t = [_dot(_sub(p["o"], o), a) for p in planes]
    h = max(t) - min(t)
    if h <= tol:
        raise _Reject("zero height")
    ax, az = a[0], a[2]
    flip = (az < -TOL_DIR_STEP
            or (abs(az) <= TOL_DIR_STEP and ax < -TOL_DIR_STEP)
            or (abs(az) <= TOL_DIR_STEP and abs(ax) <= TOL_DIR_STEP and a[1] < 0))
    if flip:
        a = (-a[0], -a[1], -a[2])
        t = [-v for v in t]
    e2 = _cross(a, e1)
    base = _add(o, _scale(min(t), a))
    return {"type": "cylinder", "radius": to_metres(r, ud), "height": to_metres(h, ud),
            "transform": {"position": to_metres(base, ud), "rotation_deg": _frame_rotation(e1, e2, a)}}


def _recognise_sphere(faces: list, ud: float, tol: float) -> dict:
    c, r = faces[0]["o"], faces[0]["radius"]
    for f in faces[1:]:
        if _norm(_sub(f["o"], c)) > tol or abs(f["radius"] - r) > tol:
            raise _Reject("spherical faces of different spheres")
    position = (c[0] - r * 0.0, c[1] - r * 0.0, c[2] - r * 1.0)
    return {"type": "sphere", "radius": to_metres(r, ud),
            "transform": {"position": to_metres(position, ud), "rotation_deg": [0.0, 0.0, 0.0]}}


def _recognise_cone(faces: list, ud: float, tol: float) -> dict:
    cones = [f for f in faces if f["surface"] == "CONICAL_SURFACE"]
    planes = [f for f in faces if f["surface"] == "PLANE"]
    c = cones[0]
    o, a_s, e1, radius_s, semi = c["o"], c["a"], c["e1"], c["radius"], c["semi"]
    if not 0.0 < abs(semi) < math.pi / 2 - TOL_DIR_STEP:
        raise _Reject("semi-angle out of range")

    def apex(f):
        return _sub(f["o"], _scale(f["radius"] / math.tan(f["semi"]), f["a"]))

    for f in cones[1:]:
        if not _parallel(f["a"], a_s) or abs(f["semi"] - semi) > TOL_DIR_STEP \
                or _norm(_sub(apex(f), apex(c))) > tol:
            raise _Reject("conical faces of different cones")
    if len(planes) != 1:
        raise _Reject(f"{len(planes)} planar faces (a frustum is not a cone)" if len(planes) == 2
                      else f"{len(planes)} planar face(s), a cone has 1")
    cap = planes[0]
    if not _parallel(cap["a"], a_s):
        raise _Reject("the base plane is not perpendicular to the axis")
    p_cap = cap["o"]
    far = [v for f in cones for v in f["vertices"] if abs(_dot(_sub(v, p_cap), a_s)) > tol]
    if not far:
        raise _Reject("cone without an apex vertex")
    V = far[0]
    if any(_norm(_sub(v, V)) > tol for v in far[1:]):
        raise _Reject("cone without a single apex vertex")
    s = _dot(_sub(V, p_cap), a_s)
    a = a_s if s > 0 else (-a_s[0], -a_s[1], -a_s[2])
    h = _dot(_sub(V, p_cap), a)
    b = _sub(V, _scale(h, a))
    e2 = _cross(a, e1)
    if not cap["circles"]:
        raise _Reject("the base face has no CIRCLE edge")
    r = cap["circles"][0]
    if any(abs(x - r) > tol for x in cap["circles"][1:]):
        raise _Reject("base circles of different radii")
    if abs(r - abs(radius_s + _dot(_sub(b, o), a_s) * math.tan(semi))) > tol or not h > tol:
        raise _Reject("inconsistent cone")
    if abs(radius_s + _dot(_sub(V, o), a_s) * math.tan(semi)) > tol:
        raise _Reject("inconsistent cone (the surface radius does not vanish at the apex vertex)")
    return {"type": "cone", "radius": to_metres(r, ud), "height": to_metres(h, ud),
            "transform": {"position": to_metres(b, ud), "rotation_deg": _frame_rotation(e1, e2, a)}}


def _canon(n, order) -> tuple:
    for k in order:
        if abs(n[k]) > TOL_DIR_STEP:
            return n if n[k] > 0 else (-n[0], -n[1], -n[2])
    return n


def _recognise_box(faces: list, ud: float, tol: float) -> dict:
    groups = []                                  # [[face, ...]] in ascending lowest face id
    for f in faces:
        for g in groups:
            if _parallel(g[0]["a"], f["a"]):
                g.append(f)
                break
        else:
            groups.append([f])
    if len(groups) != 3 or any(len(g) != 2 for g in groups):
        raise _Reject("the planes are not three pairs of parallel faces")
    dirs = [g[0]["a"] for g in groups]
    for g, n in zip(groups, dirs):
        if abs(_dot(_sub(g[1]["o"], g[0]["o"]), n)) <= tol:
            raise _Reject("two parallel faces in one plane")
    if any(abs(_dot(dirs[i], dirs[j])) > TOL_DIR_STEP for i, j in ((0, 1), (0, 2), (1, 2))):
        raise _Reject("the face directions are not mutually perpendicular")
    verts = []
    for f in faces:
        for v in f["vertices"]:
            if all(_norm(_sub(v, w)) > tol for w in verts):
                verts.append(v)
    if len(verts) != 8:
        raise _Reject(f"{len(verts)} distinct vertices, a box has 8")

    def pick(cands, k):
        best = max(abs(dirs[i][k]) for i in cands)
        return next(i for i in cands if abs(dirs[i][k]) >= best - TOL_DIR_STEP)

    iz = pick([0, 1, 2], 2)
    z = _canon(dirs[iz], (2, 0, 1))
    ix = pick([i for i in (0, 1, 2) if i != iz], 0)
    x = _canon(dirs[ix], (0, 1, 2))
    x = _unit(_sub(x, _scale(_dot(x, z), z)))
    y = _cross(z, x)
    local = [(_dot(v, x), _dot(v, y), _dot(v, z)) for v in verts]
    lo = [min(p[k] for p in local) for k in range(3)]
    hi = [max(p[k] for p in local) for k in range(3)]
    size = [hi[k] - lo[k] for k in range(3)]
    if any(s <= tol for s in size):
        raise _Reject("zero size")
    mx, my, mz = (hi[0] + lo[0]) / 2.0, (hi[1] + lo[1]) / 2.0, lo[2]
    position = (x[0] * mx + y[0] * my + z[0] * mz, x[1] * mx + y[1] * my + z[1] * mz,
                x[2] * mx + y[2] * my + z[2] * mz)
    return {"type": "box", "size": to_metres(size, ud),
            "transform": {"position": to_metres(position, ud), "rotation_deg": _frame_rotation(x, y, z)}}


def _recognise(entities: dict, solid_ref: str, unit_divisor: float, angle_factor: float, tol: float) -> tuple:
    """``(object | None, face counts, reason | None)``."""
    faces = _face_records(entities, solid_ref, angle_factor)
    counts = _counts(faces)
    kinds = set(counts)
    if not all(f["loops_ok"] for f in faces):
        return None, counts, "unsupported face loop"
    if kinds <= {"CYLINDRICAL_SURFACE", "PLANE"} and counts.get("CYLINDRICAL_SURFACE", 0) >= 1:
        rule = _recognise_cylinder
    elif kinds == {"SPHERICAL_SURFACE"}:
        rule = _recognise_sphere
    elif kinds <= {"CONICAL_SURFACE", "PLANE"} and counts.get("CONICAL_SURFACE", 0) >= 1:
        rule = _recognise_cone
    elif kinds == {"PLANE"} and counts["PLANE"] == 6:
        rule = _recognise_box
    else:
        return None, counts, None
    try:
        return rule(faces, float(unit_divisor), float(tol)), counts, None
    except _Reject as exc:
        return None, counts, f"{rule.__name__[len('_recognise_'):]}: {exc}"


def recognise_solid(entities, solid_ref, unit_divisor, angle_factor, tol):
    """The §2.0 object dict (without ``id``) of one ``MANIFOLD_SOLID_BREP`` if it is a cylinder,
    sphere, cone or box by the exact rules of contract §5.5.5, else ``None``.  Lengths in metres
    through :func:`to_metres`; ``tol`` in file units (§5.5.4)."""
    return _recognise(entities, solid_ref, unit_divisor, angle_factor, tol)[0]


# --------------------------------------------------------------------------- rotations
def euler_zyx_deg(R) -> list:
    """``[rx, ry, rz]`` in degrees with ``R = Rz·Ry·Rx`` (contract §5.5.5; the inverse of
    ``transform.euler_zyx_matrix``): entries canonicalised with ``+ 0.0`` first, the ``cos ry >= 0``
    branch, gimbal lock (``hypot(R00, R10) <= 1e-12``) -> ``rz = 0``; angles in ``(-180, 180]``."""
    M = np.asarray(R, dtype=np.float64)
    r = [[float(M[i, j]) + 0.0 for j in range(3)] for i in range(3)]
    cy = math.hypot(r[0][0], r[1][0])
    ry = math.atan2(-r[2][0], cy)
    if cy > 1e-12:
        rz = math.atan2(r[1][0], r[0][0])
        rx = math.atan2(r[2][1], r[2][2])
    else:
        sy = -r[2][0]
        rz = 0.0
        rx = math.atan2(sy * r[0][1] + 0.0, r[1][1])     # + 0.0: sy = -1 must not make a -0.0
    return [math.degrees(rx) + 0.0, math.degrees(ry) + 0.0, math.degrees(rz) + 0.0]


def _compose_transform(obj: dict, transform: dict) -> dict:
    """``R = R_user · R_step``, ``position = R_user · p_step + p_user`` (contract §5.5.1)."""
    t = obj["transform"]
    Ru = euler_zyx_matrix(transform["rotation_deg"])
    Rs = euler_zyx_matrix(t["rotation_deg"])
    R = Ru @ Rs
    p = Ru @ np.asarray(t["position"], dtype=np.float64) + np.asarray(transform["position"], dtype=np.float64)
    out = copy.deepcopy(obj)
    out["transform"] = {"position": [float(v) + 0.0 for v in p], "rotation_deg": euler_zyx_deg(R)}
    return out


# --------------------------------------------------------------------------- importer (§5.5.6)
def _sanitise(stem: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", stem) or "step"


def _base_field(field: str) -> str:
    return field[: -len(".path")] if field.endswith(".path") else field


def _check_solid(solid, field: str):
    if solid is None:
        return None
    if isinstance(solid, bool) or not isinstance(solid, int) or solid < 0:
        raise SceneError(field, "must be an integer ≥ 0")
    return solid


def _check_fallback(fallback, field: str) -> str:
    if fallback not in ("error", "mesh"):
        raise SceneError(field, "must be 'error' or 'mesh'")
    return fallback


def _read_text(path) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def import_step(path, *, fallback="error", solid=None, obj_id=None, transform=None, field="step") -> dict:
    """Read a STEP file and recognise its solids (contract §5.5.6).  Returns the report
    ``{"path", "schema", "unit", "unit_divisor", "angle_factor", "tol", "solids", "objects", "notes"}``.
    Every failure of the file is a :class:`StepError` (field ``field``); a bad ``solid`` /
    ``fallback`` / ``transform`` is a ``SceneError`` at the sibling field; an unreadable file an
    ``OSError``; ``fallback="mesh"`` without OCP an ``ImportError``."""
    base = _base_field(field)
    solid = _check_solid(solid, f"{base}.solid")
    fallback = _check_fallback(fallback, f"{base}.fallback")
    user_t = None if transform is None else validate_transform(transform, f"{base}.transform")
    path_s = os.fspath(path)
    if obj_id is None:
        obj_id = _sanitise(os.path.splitext(os.path.basename(path_s))[0])
    text = _read_text(path_s)
    try:
        try:
            doc = parse(text)
        except Part21SyntaxError as exc:
            raise _err(f"syntax: {exc.message} at offset {exc.offset}") from None
        except RecursionError:                   # belt and braces: part21 caps the nesting depth
            raise _err("syntax: nesting too deep") from None
        entities = doc["entities"]
        schema = doc["header"].get("FILE_SCHEMA")
        schema = schema[0][0] if (isinstance(schema, list) and schema and isinstance(schema[0], list)
                                  and schema[0] and isinstance(schema[0][0], str)) else None
        unit, ud, notes = _length_unit(entities)
        angle_factor, angle_notes = _angle_unit(entities)
        notes = notes + angle_notes
        tol = _tolerance(entities, unit)
        solid_ids = _solid_ids(entities)
        _check_assembly(entities, tol)
        if solid is not None and solid >= len(solid_ids):
            raise SceneError(f"{base}.solid", f"file has {len(solid_ids)} solid(s)")
        selected = list(enumerate(solid_ids)) if solid is None else [(solid, solid_ids[solid])]
        single = len(selected) == 1
        solids, objects = [], []
        ocp_file, records, known = None, None, None
        for k, ref in selected:
            oid = obj_id if single else f"{obj_id}_{k}"
            rec, counts, reason = _recognise(entities, ref, ud, angle_factor, tol)
            if rec is None:
                if fallback != "mesh":
                    faces = ", ".join(f"{n}: {c}" for n, c in counts.items())
                    msg = f"{ref}: unsupported solid: faces {{{faces}}} (supported: {_SUPPORTED})"
                    raise _err(msg + (f"; {reason}" if reason else ""), ref)
                if known is None:                # OCC must only see resolvable references (second review)
                    known = _ocp_entity_ids(entities)
                _check_references(entities, known, None if len(solid_ids) == 1 else ref)
                if ocp_file is None:             # read by OCP once per import (review fix)
                    ocp_file = _OcpFile(path_s)
                if len(solid_ids) == 1:
                    shape = ocp_file.whole()
                else:
                    if records is None:
                        records = {r: i for i, r in enumerate(entities, 1)}
                    scale = ocp_file.divisor / ud
                    shape = ocp_file.solid(ref, records[ref], len(entities), _solid_vertices(entities, ref),
                                           scale, max(tol * scale, 1e-9))
                tri = ocp_file.mesh(shape)
                obj = mesh_object_from_triangles(oid, tri, transform)
                notes.append(make_step_warning("STEP_SOLID_TESSELLATED", [ref]))
                kind = "mesh"
            else:
                obj = {"id": oid, **rec}
                if user_t is not None:
                    obj = _compose_transform(obj, user_t)
                kind = obj["type"]
            solids.append({"entity": ref, "kind": kind, "faces": counts, "object": obj})
            objects.append(copy.deepcopy(obj))
    except StepError as exc:
        if exc.field == _FIELD and field != _FIELD:
            raise StepError(field, exc.message, exc.entity) from None
        raise
    return {"path": path_s, "schema": schema, "unit": unit, "unit_divisor": ud, "angle_factor": angle_factor,
            "tol": tol, "solids": solids, "objects": objects, "notes": merge_warnings(notes)}


def expand_step_object(obj, field, base_dir) -> tuple:
    """``EXPANDERS["step"]`` (contract §5.5.1): validate the loader-only ``step`` object, resolve
    ``path`` against ``base_dir`` (the current working directory when ``None``) and return
    ``(objects, notes)`` of :func:`import_step`."""
    if not isinstance(obj, dict):
        raise SceneError(field, "must be an object")
    if "id" not in obj:
        raise SceneError(f"{field}.id", "required")
    oid = _scene_id(obj["id"], f"{field}.id", no_dot=True)
    if "path" not in obj:
        raise SceneError(f"{field}.path", "required")
    path = obj["path"]
    if not isinstance(path, str) or path == "":
        raise SceneError(f"{field}.path", "must be a non-empty string")
    solid = _check_solid(obj.get("solid"), f"{field}.solid")
    fallback = _check_fallback(obj.get("fallback", "error"), f"{field}.fallback")
    transform = obj.get("transform")
    if transform is not None:
        validate_transform(transform, f"{field}.transform")
    full = path if os.path.isabs(path) else os.path.join(os.getcwd() if base_dir is None else os.fspath(base_dir),
                                                         path)
    try:
        report = import_step(full, fallback=fallback, solid=solid, obj_id=oid, transform=transform,
                             field=f"{field}.path")
    except OSError as exc:
        if exc.errno is None:
            raise
        raise type(exc)(exc.errno, f"{field}.path: {exc.strerror or exc}", exc.filename) from None
    return report["objects"], report["notes"]


# --------------------------------------------------------------------------- tessellation (§5.5.7)
_OCP_MISSING = "the tessellation fallback needs cadquery-ocp: pip install 'castplane[step]'"


def _ocp():
    """The OCP names the tessellation uses (``ImportError`` naming ``castplane[step]`` without it)."""
    try:
        from OCP.Bnd import Bnd_Box
        from OCP.BRep import BRep_Tool
        from OCP.BRepBndLib import BRepBndLib
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.Interface import Interface_Static
        from OCP.STEPControl import STEPControl_Reader
        from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID, TopAbs_VERTEX
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopoDS import TopoDS
    except ImportError:
        raise ImportError(_OCP_MISSING) from None
    return dict(locals())


class _OcpFile:
    """One STEP file read by OCP **once** (review fix: the mesh fallback used to re-read and
    re-transfer the whole file for every unrecognised solid, quadratic in the number of solids).

    ``whole()`` is the ``TransferRoots`` / ``OneShape`` shape of :func:`tessellate_step`;
    ``solid(ref, record)`` transfers the one ``MANIFOLD_SOLID_BREP`` at Part-21 record number
    ``record`` (1-based file position, which is how OCC numbers its model) with ``TransferOne``
    (review fix: OCC's ``TopAbs_SOLID`` explorer order follows the assembly structure, not the
    entity ids, so a positional index picked another solid)."""

    def __init__(self, path):
        self.ocp = _ocp()
        self.path = os.fspath(path)
        self.reader = self.ocp["STEPControl_Reader"]()
        if self.reader.ReadFile(self.path) != self.ocp["IFSelect_RetDone"]:
            raise _err(f"unsupported: OCP cannot read {self.path}")
        self.cascade_unit = self.ocp["Interface_Static"].CVal_s("xstep.cascade.unit")
        self.divisor = {"MM": 1000.0, "M": 1.0}.get(self.cascade_unit)
        if self.divisor is None:
            raise _err(f"unsupported: OCP cascade unit {self.cascade_unit!r}")

    def whole(self):
        n_roots = self.reader.TransferRoots()
        shape = self.reader.OneShape()
        if n_roots == 0 or shape.IsNull():     # OCC returns RetDone for a file it cannot transfer (review fix)
            raise _err(f"unsupported: OCP cannot read {self.path} (no transferable shape)")
        return shape

    def solid(self, ref: str, record: int, n_records: int, vertices: list, scale: float, tol: float):
        """The OCC solid of ``ref``; ``vertices`` (file units, times ``scale`` = cascade units) must
        each lie within ``tol`` (cascade units) of a vertex of it, else ``StepError``."""
        model = self.reader.Model()
        if model.NbEntities() != n_records or \
                model.Value(record).DynamicType().Name() != "StepShape_ManifoldSolidBrep":
            raise _err(f"{ref}: unsupported: OCP numbers the records of {self.path} differently", ref)
        self.reader.ClearShapes()
        if not self.reader.TransferOne(record) or self.reader.NbShapes() != 1 or self.reader.Shape(1).IsNull():
            raise _err(f"{ref}: unsupported: OCP cannot transfer the solid", ref)
        shape = self.reader.Shape(1)
        o = self.ocp
        have = []
        explorer = o["TopExp_Explorer"](shape, o["TopAbs_VERTEX"])
        while explorer.More():
            p = o["BRep_Tool"].Pnt_s(o["TopoDS"].Vertex(explorer.Current()))
            have.append((p.X(), p.Y(), p.Z()))
            explorer.Next()
        cell = 2.0 * tol                       # a cheap guard against a record mismatch (grid lookup)
        grid = {}
        for q in have:
            grid.setdefault(tuple(math.floor(c / cell) for c in q), []).append(q)
        for v in vertices:
            w = _scale(scale, v)
            i, j, k = (math.floor(c / cell) for c in w)
            if not any(_norm(_sub(w, q)) <= tol
                       for di in (-1, 0, 1) for dj in (-1, 0, 1) for dk in (-1, 0, 1)
                       for q in grid.get((i + di, j + dj, k + dk), ())):
                raise _err(f"{ref}: unsupported: the OCP solid does not match the file's vertex {list(v)}", ref)
        return shape

    def mesh(self, shape, deflection_mm=None) -> dict:
        """``BRepMesh_IncrementalMesh`` of ``shape`` -> the :func:`tessellate_step` dict (§5.5.7)."""
        o = self.ocp
        if deflection_mm is None:
            box = o["Bnd_Box"]()
            o["BRepBndLib"].Add_s(shape, box)
            if box.IsVoid():                   # CornerMin() of a void box raises Standard_ConstructionError
                raise _err(f"unsupported: OCP finds no geometry in {self.path}")
            lo, hi = box.CornerMin(), box.CornerMax()
            diagonal = math.sqrt((hi.X() - lo.X()) ** 2 + (hi.Y() - lo.Y()) ** 2 + (hi.Z() - lo.Z()) ** 2)
            deflection_mm = max(0.01, 1e-3 * diagonal)
        o["BRepMesh_IncrementalMesh"](shape, float(deflection_mm), False, 0.3, False)
        brep_tool = o["BRep_Tool"]
        triangulation = getattr(brep_tool, "Triangulation_s", None) or brep_tool.Triangulation
        divisor = self.divisor
        vertices, faces = [], []
        explorer = o["TopExp_Explorer"](shape, o["TopAbs_FACE"])
        while explorer.More():
            face = o["TopoDS"].Face(explorer.Current())
            loc = o["TopLoc_Location"]()
            tri = triangulation(face, loc)
            if tri is not None:
                trsf = loc.Transformation()
                offset = len(vertices)
                for i in range(1, tri.NbNodes() + 1):
                    p = tri.Node(i).Transformed(trsf)
                    vertices.append([p.X() / divisor + 0.0, p.Y() / divisor + 0.0, p.Z() / divisor + 0.0])
                reversed_ = face.Orientation() == o["TopAbs_REVERSED"]
                for i in range(1, tri.NbTriangles() + 1):
                    n1, n2, n3 = tri.Triangle(i).Get()
                    f = [offset + n1 - 1, offset + n2 - 1, offset + n3 - 1]
                    faces.append([f[0], f[2], f[1]] if reversed_ else f)
            explorer.Next()
        return {"vertices": vertices, "faces": faces, "cascade_unit": self.cascade_unit}


def _ocp_entity_ids(entities: dict) -> set:
    """The numeric entity ids OCC can resolve (``#091`` and ``#91`` are the same id to OCC; ``#0``
    is none: OCC reads id 0 as "no entity", so a reference to it is unresolved)."""
    return {n for n in (int(r[1:]) for r in entities) if n != 0}


_REF_RE = re.compile(r"#\d+")


def _check_references(entities: dict, known: set, root: str | None = None) -> None:
    """Every reference of the records OCC is about to transfer resolves (the whole file for
    ``TransferRoots``, the records reachable from ``root`` for ``TransferOne``), else a
    ``StepError`` at the referring record (second review: a dangling reference inside the solid
    made the OCC transfer crash the interpreter with a segmentation fault)."""

    def refs(x):
        if isinstance(x, str):
            if _REF_RE.fullmatch(x):
                yield x
        elif isinstance(x, (list, tuple)):
            for y in x:
                yield from refs(y)

    def check(r):
        out = []
        for _, args in _parts(entities[r]):
            for t in refs(args):
                n = int(t[1:])
                if n not in known:
                    why = "OCP numbers entities from #1" if n == 0 else "does not exist"
                    raise _err(f"{r}: unsupported: reference {t} ({why})", r)
                if t in entities:
                    out.append(t)
        return out

    if root is None:
        for r in sorted(entities, key=lambda r: int(r[1:])):
            check(r)
        return
    seen, stack = set(), [root]
    while stack:
        r = stack.pop()
        if r not in seen:
            seen.add(r)
            stack.extend(check(r))


def _solid_vertices(entities: dict, solid_ref: str) -> list:
    """Every ``VERTEX_POINT`` reachable from ``solid_ref`` (file units, deduplicated, in walk order)."""
    seen, stack, points = set(), [solid_ref], []

    def refs(x):
        if isinstance(x, str):
            if x in entities:
                yield x
        elif isinstance(x, (list, tuple)):
            for y in x:
                yield from refs(y)

    while stack:
        r = stack.pop()
        if r in seen:
            continue
        seen.add(r)
        for name, args in _parts(entities[r]):
            if name == "VERTEX_POINT":
                points.append(_vertex(entities, r))
            else:
                stack.extend(refs(args))
    return points


def _tessellate(path, deflection_mm=None) -> dict:
    """:func:`tessellate_step` of the whole shape of the file."""
    ocp_file = _OcpFile(path)
    return ocp_file.mesh(ocp_file.whole(), deflection_mm)


def tessellate_step(path, *, deflection_mm=None) -> dict:
    """Tessellate a STEP file with OCP (contract §5.5.7): ``{"vertices": [[x, y, z]...]`` (metres,
    per-face node blocks, unwelded), ``"faces": [[i, j, k]...]`` (0-based, outward winding),
    ``"cascade_unit": "MM" | "M"}``.  ``ImportError`` without cadquery-ocp."""
    return _tessellate(path, deflection_mm)


def mesh_object_from_triangles(obj_id, tri, transform) -> dict:
    """The §5.2.1 inline ``mesh`` object of a tessellation (contract §5.5.7); ``transform`` is
    omitted when ``None``."""
    out = {"id": obj_id, "type": "mesh",
           "data": {"vertices": [[float(c) + 0.0 for c in v] for v in tri["vertices"]],
                    "faces": [[int(i) for i in f] for f in tri["faces"]],
                    "smooth_groups": [0] * len(tri["faces"])}}
    if transform is not None:
        out["transform"] = copy.deepcopy(transform)
    return out
