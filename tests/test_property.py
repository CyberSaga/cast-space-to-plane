"""Property tests with hypothesis (spec §7.4; contract §4, M3 gate).

Random scenes and cameras are generated with hypothesis strategies (``st.composite`` /
``st.builds``) and every example is checked against the six invariants of spec §7.1:

| row | invariant                                   | tolerance        |
| 1   | construction self-check (document checks)   | 1e-6 mm          |
| 2   | world shadow points independent of camera   | 1e-9 m           |
| 3   | point light at 1e6 m -> directional light   | 1e-4 m           |
| 4   | rigid equivariance (Z rotations + XY shifts)| 1e-6 mm          |
| 5   | positive homogeneous scaling of the inputs  | 1e-9 (relative)  |
| 6   | no NaN / Inf in the JSON and the SVG        | --               |

Dedicated degenerate distributions (light behind the camera, light direction parallel
to the picture plane, vertices above the light, horizontal sun, camera looking straight
down, roll ±180°, near 1e-6 … 3 m, f 8 … 5000 mm, shift ±20 mm) must only produce
warnings from the closed code table, never exceptions, and keep the invariants that
remain meaningful for them.

Rows 1 and 4 compare image coordinates; for the extreme-camera distributions (near
1e-6 m, f 5000 mm) a point a hair in front of the near plane, and for a light nearly
parallel to the picture plane its ``L'``, have image coordinates of order 1e9 mm whose
last bits move under a rigid motion of the inputs, so those rows use
``1e-6 mm + 1e-9 · |coordinate|`` (the relative projective equality of contract §2.8);
the other distributions keep the absolute 1e-6 mm.

All settings use ``derandomize=True`` (deterministic in CI) and ``deadline=None``; the
example counts are sized so that the whole file runs well under a minute.
"""

from __future__ import annotations

import copy
import math
import re

import numpy as np
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

import castplane
from castplane.camera import camera_matrix, divide, project
from castplane.construction import self_check
from castplane.errors import WARNING_CODES
from castplane.homogeneous import TOL_DIR
from castplane.output.geometry_json import dumps
from castplane.scene import load_scene, validate_camera
from castplane.shadow import foot, shadow_loop, shadow_matrix
from castplane import curved
from tests.reference import random_scenes, raster, raycast

#: Curved primitives (cylinder / sphere / cone, M2) take part in the mixed distributions.
INCLUDE_CURVED = True

GROUND = np.array([0.0, 0.0, 1.0, 0.0])
POLYHEDRAL = ("box", "prism")
ALL_KINDS = ("box", "prism", "cylinder", "sphere", "cone")
needs_curved = pytest.mark.skipif(not INCLUDE_CURVED, reason="curved shadows need M2")
SUPPRESS = [HealthCheck.too_slow, HealthCheck.filter_too_much, HealthCheck.data_too_large,
            HealthCheck.function_scoped_fixture]
COMMON = dict(deadline=None, derandomize=True, suppress_health_check=SUPPRESS)

#: Row 2 tolerance (m), row 3 tolerance (m), rows 1/4 tolerance (mm), row 5 relative tolerance.
TOL_WORLD = 1e-9
TOL_CONVERGE = 1e-4
TOL_IMAGE = 1e-6
TOL_SCALE = 1e-9


# --------------------------------------------------------------------------- strategies
def finite(lo, hi, **kw):
    return st.floats(min_value=lo, max_value=hi, allow_nan=False, allow_infinity=False, **kw)


def rounded(x, nd=4):
    return round(float(x), nd)


@st.composite
def polygons(draw, n_min=3, n_max=8):
    """Simple star-shaped polygon (counter-clockwise), concave with probability ~0.6."""
    n = draw(st.integers(n_min, n_max))
    seed = draw(st.integers(0, 2 ** 31 - 1))
    concave = n >= 5 and draw(st.booleans())
    rng = np.random.default_rng(seed)
    return random_scenes.star_polygon(rng, n, 0.35, draw(finite(0.6, 1.4)), concave)


@st.composite
def primitives(draw, idx: int, kinds=ALL_KINDS, tilt=True, span=3.0):
    """One primitive of a kind from ``kinds`` resting on (or slightly above) the ground."""
    kind = draw(st.sampled_from(kinds))
    obj: dict = {"id": f"o{idx}", "type": kind}
    if kind == "box":
        obj["size"] = [rounded(draw(finite(0.2, 1.8))) for _ in range(3)]
    elif kind in ("cylinder", "cone"):
        obj["radius"] = rounded(draw(finite(0.15, 0.9)))
        obj["height"] = rounded(draw(finite(0.2, 2.2)))
    elif kind == "sphere":
        obj["radius"] = rounded(draw(finite(0.15, 0.9)))
    else:
        obj["polygon"] = draw(polygons())
        obj["height"] = rounded(draw(finite(0.2, 2.2)))
    rz = rounded(draw(finite(0.0, 360.0)))
    if tilt and kind != "sphere" and draw(st.booleans()):
        rx, ry = rounded(draw(finite(-40.0, 40.0))), rounded(draw(finite(-40.0, 40.0)))
    else:
        rx, ry = 0.0, 0.0
    obj["transform"] = {"position": [rounded(draw(finite(-span, span))), rounded(draw(finite(-span, span))), 0.0],
                        "rotation_deg": [rx, ry, rz]}
    random_scenes.lift_to_ground(obj, draw(st.sampled_from([0.0, 0.0, 0.1, 0.3])))
    return obj


@st.composite
def object_lists(draw, kinds=ALL_KINDS, n_min=1, n_max=4, tilt=True):
    n = draw(st.integers(n_min, n_max))
    return [draw(primitives(i, kinds, tilt)) for i in range(n)]


@st.composite
def point_lights(draw, objects, above=True):
    """Point light above every object (``above``) or anywhere above the ground but outside the objects."""
    top = max(random_scenes.highest_z(o) for o in objects)
    if above:
        z = draw(finite(top + 0.3, top + 8.0))
        xy = [draw(finite(-8.0, 8.0)), draw(finite(-8.0, 8.0))]
    else:
        z = draw(finite(0.3, max(0.31, 0.9 * top)))
        xy = [draw(finite(-7.0, 7.0)), draw(finite(-7.0, 7.0))]
        # constructive instead of assume(): pushed horizontally out of every bounding sphere
        xy = random_scenes.push_clear([xy[0], xy[1], z], objects, 0.25)[:2]
        assert random_scenes.clear_of_objects(np.array([xy[0], xy[1], z]), objects, 0.25 - 1e-6)
    return {"id": "lamp", "type": "point", "position": [rounded(xy[0]), rounded(xy[1]), rounded(z)]}


@st.composite
def directional_lights(draw, el_min=20.0, el_max=85.0):
    az = draw(finite(0.0, 2.0 * math.pi))
    el = math.radians(draw(finite(el_min, el_max)))
    return {"id": "sun", "type": "directional", "direction": random_scenes.unit_direction(az, el)}


def lights(objects):
    return st.one_of(point_lights(objects), directional_lights())


@st.composite
def cameras(draw, objects, yaw_form=False, f_range=(18.0, 200.0), near_range=(0.01, 0.5),
            roll_range=(-30.0, 30.0), shift_range=(-5.0, 5.0), dist_range=(3.0, 15.0), el_range=(2.0, 60.0)):
    """Camera orbiting the scene centre; target form by default, yaw/pitch form on request."""
    pts = np.vstack([random_scenes.world_extreme_points(o) for o in objects])
    centre = 0.5 * (pts.min(axis=0) + pts.max(axis=0))
    az = draw(finite(0.0, 2.0 * math.pi))
    el = math.radians(draw(finite(*el_range)))
    dist = draw(finite(*dist_range))
    pos = centre + dist * np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
    pos[2] = max(float(pos[2]), 0.2)
    target = centre + np.array([draw(finite(-0.5, 0.5)) for _ in range(3)])
    cam = {
        "position": [rounded(v) for v in pos],
        "roll_deg": rounded(draw(finite(*roll_range))),
        "focal_length_mm": rounded(draw(finite(*f_range)), 3),
        "frame_mm": [36.0, 24.0],
        "shift_mm": [rounded(draw(finite(*shift_range))), rounded(draw(finite(*shift_range)))],
        "near_m": draw(finite(*near_range)),
    }
    if yaw_form:
        f = target - pos
        f = f / np.linalg.norm(f)
        cam["yaw_deg"] = rounded(math.degrees(math.atan2(-f[0], f[1])))
        cam["pitch_deg"] = rounded(math.degrees(math.asin(max(-1.0, min(1.0, f[2])))))
    else:
        cam["target"] = [rounded(v) for v in target]
    return cam


@st.composite
def scenes(draw, kinds=ALL_KINDS, light=None, camera=None, n_max=4):
    """A complete spec §4 scene; ``light`` / ``camera`` are callables ``objects -> strategy``
    (``camera`` may also take the drawn light)."""
    objects = draw(object_lists(kinds, 1, n_max))
    lt = draw(lights(objects) if light is None else light(objects))
    if camera is None:
        cam = draw(cameras(objects, yaw_form=draw(st.booleans())))
    else:
        cam = draw(camera(objects, lt))
    return random_scenes.assemble_scene(objects, lt, cam)


# ----- dedicated degenerate distributions (spec §7.4)
@st.composite
def light_behind_camera(draw, objects, cam):
    """Point light with negative camera depth, above every object (spec §5.7 row 1)."""
    fwd, right, up = random_scenes.camera_frame(target_form(cam))
    pos = np.asarray(cam["position"], dtype=np.float64)
    top = max(random_scenes.highest_z(o) for o in objects)
    lpos = pos - draw(finite(0.3, 5.0)) * fwd + draw(finite(-3.0, 3.0)) * right
    lpos[2] = max(float(lpos[2]) + draw(finite(0.3, 3.0)), top + 0.3)
    return {"id": "lamp", "type": "point", "position": [rounded(v) for v in lpos]}


#: Minimum ``d_z`` of a light (nearly) parallel to the picture plane: elevation > 17 deg keeps the
#: 1e6 m convergence of row 3 within 1e-4 m.
PARALLEL_MIN_Z = 0.3


@st.composite
def light_parallel_to_picture_plane(draw, cam, exact: bool):
    """Directional light perpendicular to the camera forward vector -- exactly (``psi = 0``,
    ``LIGHT_POINT_AT_INFINITY``) or tilted out of the picture plane by ``psi`` in
    ``±1e-7 … ±4e-3`` rad (``L'`` finite but ~1e9 mm away) -- above the horizon (spec §5.7
    row 2).  The elevation is constructed, not filtered: ``d = cos(phi) right + sin(phi) up``
    with ``sin(phi) = d_z / up_z`` for a drawn ``d_z`` (``right`` is horizontal, ``up_z > 0``)."""
    fwd, right, up = random_scenes.camera_frame(target_form(cam))
    up_z = float(up[2])
    psi = 0.0 if exact else draw(st.sampled_from([1e-7, -1e-7, 1e-4, -1e-3, 1e-3, -4e-3]))
    z_min = PARALLEL_MIN_Z + 0.01
    assume(up_z > z_min + 1e-3)        # a camera looking down more steeply than ~72 deg (rare)
    dz = draw(finite(z_min, up_z - 1e-3))
    phi = math.asin(min(1.0, dz / up_z))
    if draw(st.booleans()):
        phi = math.pi - phi
    d = math.cos(psi) * (math.cos(phi) * right + math.sin(phi) * up) + math.sin(psi) * fwd
    d = d / np.linalg.norm(d)
    assert d[2] > PARALLEL_MIN_Z, d
    return {"id": "sun", "type": "directional", "direction": [float(v) for v in d]}


@st.composite
def horizontal_sun(draw):
    """Directional light at elevation 0 (or within ±1e-3°, both signs): spec §5.7 row 3."""
    az = draw(finite(0.0, 2.0 * math.pi))
    el = math.radians(draw(st.sampled_from([0.0, 0.0, 1e-3, -1e-3, 1e-12, -1e-12])))
    return {"id": "sun", "type": "directional", "direction": random_scenes.unit_direction(az, el)}


@st.composite
def camera_straight_down(draw, objects):
    pts = np.vstack([random_scenes.world_extreme_points(o) for o in objects])
    centre = 0.5 * (pts.min(axis=0) + pts.max(axis=0))
    h = draw(finite(3.0, 20.0))
    x, y = draw(finite(-3.0, 3.0)), draw(finite(-3.0, 3.0))
    cam = {"position": [rounded(centre[0] + x), rounded(centre[1] + y), rounded(h)],
           "target": [rounded(centre[0] + x), rounded(centre[1] + y), 0.0],
           "roll_deg": rounded(draw(finite(-180.0, 180.0))), "focal_length_mm": rounded(draw(finite(14.0, 85.0)), 3),
           "frame_mm": [36.0, 24.0], "shift_mm": [0.0, 0.0], "near_m": 0.05}
    if draw(st.booleans()):
        del cam["target"]
        cam["yaw_deg"], cam["pitch_deg"] = rounded(draw(finite(-180.0, 180.0))), -90.0
    return cam


def extreme_cameras(objects, lt=None):
    """roll ±180°, near 1e-6 … 3 m, f 8 … 5000 mm, shift ±20 mm (spec §7.4 degenerate camera ranges)."""
    return cameras(objects, f_range=(8.0, 5000.0), near_range=(1e-6, 3.0), roll_range=(-180.0, 180.0),
                   shift_range=(-20.0, 20.0), dist_range=(1.0, 15.0), el_range=(0.0, 85.0))


def target_form(cam: dict) -> dict:
    """Target-form copy of a camera dict (yaw/pitch cameras get a target 1 m ahead)."""
    if "target" in cam:
        return cam
    yaw, pitch = math.radians(cam["yaw_deg"]), math.radians(cam["pitch_deg"])
    fwd = np.array([-math.sin(yaw) * math.cos(pitch), math.cos(yaw) * math.cos(pitch), math.sin(pitch)])
    out = dict(cam)
    out["target"] = (np.asarray(cam["position"], dtype=np.float64) + fwd).tolist()
    del out["yaw_deg"], out["pitch_deg"]
    return out


# --------------------------------------------------------------------------- helpers
def walk_numbers(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_numbers(v)
    elif isinstance(obj, float):
        yield obj


def render(scene, camera=None):
    return castplane.render(load_scene(scene), camera=camera)


def codes(doc):
    return {w["code"] for w in doc["warnings"]}


def assert_warnings_only(result):
    """Row 6 plus the §7.4 "warnings, never exceptions" rule: finite output, known codes, valid SVG."""
    doc, svg = result["geometry"], result["svg"]
    assert all(math.isfinite(x) for x in walk_numbers(doc))
    text = dumps(doc)
    assert "NaN" not in text and "Infinity" not in text and not re.search(r"-0\.0(?![0-9])", text)
    low = svg.lower().replace("infinity", "")
    assert "nan" not in low and "inf" not in low
    assert svg.startswith('<?xml version="1.0"') and svg.rstrip().endswith("</svg>")
    for w in doc["warnings"]:
        assert w["code"] in WARNING_CODES and isinstance(w["ids"], list) and isinstance(w["message"], str)


def assert_construction_check(doc, rel=0.0):
    """Row 1: every non-skipped self-check of the document is within 1e-6 mm (plus ``rel`` times the
    size of the shadow point's image for the extreme-camera distributions)."""
    light = doc["shadows"][0]["light"] if doc["shadows"] else None
    for c in doc["construction"]["checks"]:
        img = doc["points"][c["point"]]["image"]
        scale = max(abs(v) for v in img) if img is not None else 1.0
        assert c["max_error_mm"] <= TOL_IMAGE + rel * scale, (c, light)


#: Contract §3.1 / §2.7 point names that are camera independent: mesh vertices, shadows, feet, ground
#: crossings, the light and its foot, and the light-silhouette construction points of curved objects.
#: (Camera-outline points of curved objects legitimately move with the camera and are not matched.)
CAMERA_INDEPENDENT = re.compile(
    r"(^[LF]\.[^.]+$)|(\.v\d+$)|(\.shadow\.[^.]+$)|(\.foot$)|(\.s\d+\.[^.]+$)|(\.c$)|(\.sil\.\d+$)"
    r"|(\.g[01]\.(base|top)$)|(\.apex$)")


def assert_camera_independent(scene, doc):
    """Row 2: the world shadow points, loops and silhouettes do not change with the camera.

    Two renders are compared with ``doc``: a *different scene dict* whose camera, canvas and
    near plane are replaced (so a stage A that reads ``scene["camera"]`` -- forbidden by
    contract §2.8 / §3 -- would change its tolerances and be caught), and the
    ``render(camera=...)`` override of contract §3.
    """
    other = {"position": [-7.0, -5.0, 6.0], "target": [0.0, 2.0, 0.0], "roll_deg": 7.0, "focal_length_mm": 24.0,
             "frame_mm": [36.0, 24.0], "shift_mm": [1.0, -1.0], "near_m": 0.1}
    scene2 = copy.deepcopy(scene)
    scene2["camera"] = dict(other, position=[40.0, -60.0, 25.0], near_m=2.0)
    scene2["output"]["canvas_mm"] = [180.0, 120.0]
    doc2 = render(scene2)["geometry"]
    doc3 = render(scene, camera=other)["geometry"]
    names = {n for n in doc["points"] if CAMERA_INDEPENDENT.search(n)}
    loop_names = {e for s in doc["shadows"] for loop in s["loops"] for e in loop if isinstance(e, str)}
    assert loop_names <= names, loop_names - names
    for other_doc in (doc2, doc3):
        assert names == {n for n in other_doc["points"] if CAMERA_INDEPENDENT.search(n)}
        for name in names:
            p = doc["points"][name]
            key = "world" if "world" in p else "direction"
            np.testing.assert_allclose(p[key], other_doc["points"][name][key], rtol=0.0, atol=TOL_WORLD,
                                       err_msg=name)
        assert [s["loops"] for s in doc["shadows"]] == [s["loops"] for s in other_doc["shadows"]]
        assert [s["unbounded"] for s in doc["shadows"]] == [s["unbounded"] for s in other_doc["shadows"]]
        assert [e["silhouette"] for e in doc["edges"]] == [e["silhouette"] for e in other_doc["edges"]]


def assert_point_light_converges(scene, doc):
    """Row 3: the point light at 1e6 m along the sun direction reproduces the directional shadow."""
    lt = scene["lights"][0]
    if lt["type"] != "directional":
        return
    far = copy.deepcopy(scene)
    d = np.asarray(lt["direction"], dtype=np.float64)
    far["lights"][0] = {"id": lt["id"], "type": "point", "position": (1e6 * d).tolist()}
    doc_p = render(far)["geometry"]
    assert "VERTEX_NOT_BELOW_LIGHT" not in codes(doc_p)
    names_d = {n for n in doc["points"] if ".shadow." in n}
    names_p = {n for n in doc_p["points"] if ".shadow." in n}
    # a face exactly parallel to the sun (n·l = 0) may be lit by the far point light (n·(l − p) ≠ 0): the
    # silhouettes may then differ by edge-on faces whose shadows have no area; compare the common points
    parallel = "FACE_PARALLEL_TO_LIGHT" in codes(doc) | codes(doc_p)
    curved = any(o["type"] in ("cylinder", "sphere", "cone") for o in scene["objects"])
    if not parallel:
        assert names_d == names_p
    if not parallel and not curved:
        assert [s["loops"] for s in doc["shadows"]] == [s["loops"] for s in doc_p["shadows"]]
    for name in names_d & names_p:
        np.testing.assert_allclose(doc["points"][name]["world"], doc_p["points"][name]["world"],
                                   rtol=0.0, atol=TOL_CONVERGE, err_msg=name)
    if curved or parallel:
        # arc samples of curved shadows are named by index and their count may differ by one between
        # the two lights: compare the shadow regions themselves (nonzero rule, union over objects)
        pts = np.vstack([random_scenes.world_extreme_points(o) for o in scene["objects"]])[:, :2]
        lo, hi = pts.min(axis=0) - 6.0, pts.max(axis=0) + 6.0
        centre, far = 0.5 * (lo + hi), 1e6 * float(np.max(hi - lo))
        xs, ys = random_scenes.grid(lo, hi, 400)
        a = raster.rasterize_polygons(raster.doc_ground_loops(doc, centre, far), xs, ys)
        b = raster.rasterize_polygons(raster.doc_ground_loops(doc_p, centre, far), xs, ys)
        assert raster.iou(a, b) >= 0.99


def rot_z(angle_deg):
    a = math.radians(angle_deg)
    return np.array([[math.cos(a), -math.sin(a), 0.0], [math.sin(a), math.cos(a), 0.0], [0.0, 0.0, 1.0]])


def transform_scene(scene, angle_deg, shift):
    """Rotate about +Z by ``angle_deg`` and translate by ``shift`` in XY: objects, light and camera
    (target form: position + target; yaw/pitch form: ``yaw += angle``; roll unchanged)."""
    R = rot_z(angle_deg)
    t = np.array([shift[0], shift[1], 0.0])
    out = copy.deepcopy(scene)
    for o in out["objects"]:
        tr = o["transform"]
        tr["position"] = (R @ np.asarray(tr["position"], dtype=np.float64) + t).tolist()
        tr["rotation_deg"] = [tr["rotation_deg"][0], tr["rotation_deg"][1], tr["rotation_deg"][2] + angle_deg]
    lt = out["lights"][0]
    if lt["type"] == "point":
        lt["position"] = (R @ np.asarray(lt["position"], dtype=np.float64) + t).tolist()
    else:
        d = R @ np.asarray(lt["direction"], dtype=np.float64)
        lt["direction"] = (d / np.linalg.norm(d)).tolist()
    cam = out["camera"]
    cam["position"] = (R @ np.asarray(cam["position"], dtype=np.float64) + t).tolist()
    if "target" in cam:
        cam["target"] = (R @ np.asarray(cam["target"], dtype=np.float64) + t).tolist()
    else:
        cam["yaw_deg"] = cam["yaw_deg"] + angle_deg
    return out


def fallback_frame_objects(scene) -> set:
    """Ids of curved objects whose named construction points depend on a frame that is fixed in
    world coordinates: a sphere with the light along the vertical axis through its centre uses the
    contract §2.6 fallback ``e1 = n × x``; a cylinder / cone with the light on its axis
    (``q_⊥ = 0``) has no ``θ_l`` and the tangent generators are a convention.  Those *named*
    points are not equivariant under a rotation of the scene (the drawn curves are), so rows 1 / 4
    skip the names of these objects."""
    out = set()
    lt = scene["lights"][0]
    for o in scene["objects"]:
        if o["type"] not in ("sphere", "cylinder", "cone"):
            continue
        R, pos = raycast.object_frame(o)
        a = R @ np.array([0.0, 0.0, 1.0])
        if o["type"] == "sphere":
            c = pos + float(o["radius"]) * a
            v = np.asarray(lt["position"], dtype=np.float64) - c if lt["type"] == "point" \
                else np.asarray(lt["direction"], dtype=np.float64)
            n = v / max(float(np.linalg.norm(v)), 1e-300)
            if np.linalg.norm(np.cross(n, [0.0, 0.0, 1.0])) <= 1e-7:
                out.add(o["id"])
        else:
            q = np.asarray(lt["position"], dtype=np.float64) - pos if lt["type"] == "point" \
                else np.asarray(lt["direction"], dtype=np.float64)
            q_perp = q - float(q @ a) * a
            if np.linalg.norm(q_perp) <= 1e-7 * max(1.0, float(np.linalg.norm(q))):
                out.add(o["id"])
    return out


def skipped_name(name: str, skip: set) -> bool:
    return any(name.startswith(f"{oid}.") for oid in skip)


def loops_equal(loops1, loops2, R=None) -> bool:
    """§6.2 loop lists are equal up to the ground rotation ``R`` (2x2) of their direction entries."""
    if len(loops1) != len(loops2):
        return False
    for l1, l2 in zip(loops1, loops2):
        if len(l1) != len(l2):
            return False
        for e1, e2 in zip(l1, l2):
            if isinstance(e1, str) or isinstance(e2, str):
                if e1 != e2:
                    return False
                continue
            d1 = np.asarray(e1["direction"], dtype=np.float64)[:2]
            d2 = np.asarray(e2["direction"], dtype=np.float64)[:2]
            if R is not None:
                d1 = R @ d1
            if np.max(np.abs(d1 - d2)) > 1e-9:
                return False
    return True


def assert_images_equal(doc1, doc2, atol, rel=0.0, skip=frozenset(), R=None):
    """Image-space equality of two documents (rows 1 / 4): points, edge segments, shadow polygons,
    form-shadow polygons, construction points and the horizon.  ``skip`` holds the ids of
    :func:`fallback_frame_objects`; ``R`` is the ground rotation applied to ``doc2`` (direction
    entries of unbounded loops are world vectors and rotate with the scene)."""
    def close(a, b, msg=""):
        a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
        tol = atol + rel * np.maximum(np.abs(a), np.abs(b))
        assert np.all(np.abs(a - b) <= tol), f"{msg}: {a} vs {b}"

    assert set(doc1["points"]) == set(doc2["points"])
    for name, p in doc1["points"].items():
        if skipped_name(name, skip):
            continue
        q = doc2["points"][name]
        assert (p["image"] is None) == (q["image"] is None), name
        if p["image"] is not None:
            close(p["image"], q["image"], name)
    assert len(doc1["edges"]) == len(doc2["edges"])
    for e1, e2 in zip(doc1["edges"], doc2["edges"]):
        assert (e1["segment"] is None) == (e2["segment"] is None)
        assert e1["back"] == e2["back"] and e1["silhouette"] == e2["silhouette"]
        if e1["segment"] is not None:
            close(e1["segment"], e2["segment"], f"edge {e1['from']}-{e1['to']}")
    for s1, s2 in zip(doc1["shadows"], doc2["shadows"]):
        assert loops_equal(s1["loops"], s2["loops"], R) and s1["unbounded"] == s2["unbounded"]
        assert len(s1["polygons"]) == len(s2["polygons"])
        for p1, p2 in zip(s1["polygons"], s2["polygons"]):
            assert len(p1) == len(p2)
            close(p1, p2, f"shadow polygon {s1['object']}")
    for f1, f2 in zip(doc1["form_shadow"], doc2["form_shadow"]):
        assert f1["faces"] == f2["faces"]
        for p1, p2 in zip(f1["polygons"], f2["polygons"]):
            assert len(p1) == len(p2)
            close(p1, p2, f"form shadow {f1['object']}")
    c1, c2 = doc1["construction"], doc2["construction"]
    for key in ("light_point", "shadow_vp"):
        assert (c1[key] is None) == (c2[key] is None), key
        if c1[key] is not None:
            close(c1[key], c2[key], key)
    assert c1["rays"] == c2["rays"]
    for ch1, ch2 in zip(c1["checks"], c2["checks"]):
        assert ch1["point"] == ch2["point"]
    v1, v2 = doc1["horizon"]["v_mm"], doc2["horizon"]["v_mm"]
    assert (v1 is None) == (v2 is None)
    if v1 is not None:
        close([v1], [v2], "horizon")
    assert [w["code"] for w in doc1["warnings"]] == [w["code"] for w in doc2["warnings"]]


def assert_rigid_equivariant(scene, doc, rel=0.0):
    """Row 4: the image output is unchanged when objects, light and camera move together."""
    skip = fallback_frame_objects(scene)
    for angle, shift in ((41.0, (1.5, -2.25)), (-137.0, (-3.0, 4.0))):
        doc2 = render(transform_scene(scene, angle, shift))["geometry"]
        assert_images_equal(doc, doc2, TOL_IMAGE, rel, skip, rot_z(angle)[:2, :2])


def assert_homogeneous_rows_close(V1, V2, msg=""):
    """Two homogeneous ``(n, 4)`` polygons describe the same points: finite rows after division,
    direction rows after max-normalisation (relative 1e-9)."""
    assert V1.shape == V2.shape, msg
    fin1, fin2 = V1[:, 3] != 0.0, V2[:, 3] != 0.0
    assert np.array_equal(fin1, fin2), msg
    if fin1.any():
        np.testing.assert_allclose(V1[fin1, :3] / V1[fin1, 3:4], V2[fin1, :3] / V2[fin1, 3:4],
                                   rtol=TOL_SCALE, atol=TOL_SCALE, err_msg=msg)
    if (~fin1).any():
        n1 = V1[~fin1, :3] / np.max(np.abs(V1[~fin1, :3]), axis=1, keepdims=True)
        n2 = V2[~fin1, :3] / np.max(np.abs(V2[~fin1, :3]), axis=1, keepdims=True)
        np.testing.assert_allclose(n1, n2, rtol=TOL_SCALE, atol=TOL_SCALE, err_msg=msg)


def assert_curved_positive_scaling(A, k_pi, k_L):
    """Row 5 for the curved primitives (contract §2.6): the light silhouette, the named
    construction points and the homogeneous ground shadow polygon of ``curved`` are unchanged
    under ``L -> k_L L``, ``π -> k_pi π`` (and hence ``M -> k_pi k_L M``).  The object itself has
    no homogeneous input to scale (its analytic record is Euclidean), and the public scene API
    takes only Euclidean inputs, so a document-level row 5 is not expressible; the rendered
    curved shadows are covered by ``tests/test_curved.py`` / ``tests/test_curved_pipeline.py``."""
    lt = A["lights"][0]
    L = lt["L"]
    M1, M2 = shadow_matrix(GROUND, L), shadow_matrix(k_pi * GROUND, k_L * L)
    tol_L = lt["tol_lit"]
    for obj in A["objects"]:
        an = obj["analytic"]
        if an is None:
            continue
        oid = obj["id"]
        sil1, sil2 = curved.silhouette(an, L, tol_L), curved.silhouette(an, k_L * L, tol_L)
        assert sil1["light_inside"] == sil2["light_inside"] and sil1["cap_lit"] == sil2["cap_lit"], oid
        assert len(sil1["loop"]) == len(sil2["loop"]) and len(sil1["generators"]) == len(sil2["generators"]), oid
        for g1, g2 in zip(sil1["generators"], sil2["generators"]):
            np.testing.assert_allclose(g1["base"], g2["base"], rtol=TOL_SCALE, atol=TOL_SCALE, err_msg=oid)
            np.testing.assert_allclose(g1["top"], g2["top"], rtol=TOL_SCALE, atol=TOL_SCALE, err_msg=oid)
        for a1, a2 in zip(sil1["arcs"], sil2["arcs"]):
            assert a1["which"] == a2["which"], oid
            np.testing.assert_allclose([a1["theta0"], a1["theta1"]], [a2["theta0"], a2["theta1"]],
                                       rtol=TOL_SCALE, atol=TOL_SCALE, err_msg=oid)
            np.testing.assert_allclose(a1["circle"]["centre"], a2["circle"]["centre"],
                                       rtol=TOL_SCALE, atol=TOL_SCALE, err_msg=oid)
        if sil1["circle"] is not None:
            for key in ("centre", "radius", "normal"):
                np.testing.assert_allclose(sil1["circle"][key], sil2["circle"][key],
                                           rtol=TOL_SCALE, atol=TOL_SCALE, err_msg=oid)
        pts1 = curved.construction_points(an, L, tol_L, oid)
        pts2 = curved.construction_points(an, k_L * L, tol_L, oid)
        assert list(pts1) == list(pts2), oid
        for name in pts1:
            assert_homogeneous_rows_close(pts1[name].reshape(1, 4), pts2[name].reshape(1, 4), name)
        # the clip levels are length-valued predicates on π^T X and w_S = M[3]·X, which scale with
        # k_pi (contract §2.8): the scaled call gets the scaled tolerances so that the predicates agree
        out1 = curved.shadow_outline(an, L, M1, GROUND, A["tol"], TOL_DIR)
        out2 = curved.shadow_outline(an, k_L * L, M2, k_pi * GROUND, k_pi * A["tol"], k_pi * TOL_DIR)
        assert out1["empty"] == out2["empty"] and out1["unbounded"] == out2["unbounded"], oid
        if out1["empty"]:
            continue
        kinds1 = [next(k for k in p if k in ("segment", "conic_arc", "direction")) for p in out1["pieces"]]
        kinds2 = [next(k for k in p if k in ("segment", "conic_arc", "direction")) for p in out2["pieces"]]
        assert kinds1 == kinds2, oid
        for p1, p2 in zip(out1["pieces"], out2["pieces"]):
            if "conic_arc" in p1:
                np.testing.assert_allclose([p1["conic_arc"]["theta0"], p1["conic_arc"]["theta1"]],
                                           [p2["conic_arc"]["theta0"], p2["conic_arc"]["theta1"]],
                                           rtol=TOL_SCALE, atol=TOL_SCALE, err_msg=oid)
        poly1, poly2 = curved.shadow_polygon_h(out1), curved.shadow_polygon_h(out2)
        assert poly1["unbounded"] == poly2["unbounded"], oid
        assert_homogeneous_rows_close(poly1["vertices"], poly2["vertices"], oid)


def assert_positive_scaling(scene, doc, k_pi=3.0, k_L=0.25, k_P=7.0):
    """Row 5 (contract §2.1): positive scalars on π, L and the vertices leave the divided shadow
    points, feet, loops, images and the self-check unchanged (relative 1e-9).  Polyhedral
    objects are checked through the ``shadow`` / ``camera`` / ``construction`` helpers on their
    mesh vertices, curved objects through :func:`assert_curved_positive_scaling`."""
    validated = load_scene(scene)
    A = castplane.shadow_geometry(validated)
    lt = A["lights"][0]
    L = lt["L"]
    if lt["pi_L"] <= 0.0:
        return  # no shadows for a light on the back side of the receiver (contract §2.3)
    assert_curved_positive_scaling(A, k_pi, k_L)
    P = np.vstack([np.c_[o["mesh"]["vertices"][:6], np.ones(min(6, o["mesh"]["vertices"].shape[0]))]
                   for o in A["objects"]])
    M1, M2 = shadow_matrix(GROUND, L), shadow_matrix(k_pi * GROUND, k_L * L)
    S1, S2 = P @ M1.T, (k_P * P) @ M2.T
    finite = (S1[:, 3] > 1e-9) & (S2[:, 3] > 1e-9)
    if finite.any():
        np.testing.assert_allclose(S1[finite, :3] / S1[finite, 3:4], S2[finite, :3] / S2[finite, 3:4],
                                   rtol=TOL_SCALE, atol=TOL_SCALE)
    Q1, Q2 = foot(GROUND, P), foot(k_pi * GROUND, k_P * P)
    np.testing.assert_allclose(Q1[:, :3] / Q1[:, 3:4], Q2[:, :3] / Q2[:, 3:4], rtol=TOL_SCALE, atol=TOL_SCALE)
    F1, F2 = foot(GROUND, L), foot(k_pi * GROUND, k_L * L)
    if np.max(np.abs(F1)) > 0.0:
        np.testing.assert_allclose(F1 / np.max(np.abs(F1)), F2 / np.max(np.abs(F2)), rtol=TOL_SCALE, atol=TOL_SCALE)
    assert (k_pi * GROUND) @ (k_L * L) > 0
    cam = camera_matrix(validate_camera(scene["camera"]), scene["output"]["canvas_mm"])
    x1, x2 = project(cam, P), project(cam, k_P * P)
    front = np.abs(x1[:, 2]) > 1e-9
    if front.any():
        np.testing.assert_allclose(divide(x1[front]), divide(x2[front]), rtol=TOL_SCALE, atol=TOL_SCALE)
    loop = P[:4] if P.shape[0] >= 4 else P
    sh1 = shadow_loop(loop, M1, GROUND, 1e-9)
    sh2 = shadow_loop(k_P * loop, M2, k_pi * GROUND, 1e-9)
    V1, V2 = sh1["vertices"], sh2["vertices"]
    assert V1.shape == V2.shape and sh1["unbounded"] == sh2["unbounded"]
    fin = V1[:, 3] != 0.0
    if fin.any():
        np.testing.assert_allclose(V1[fin, :3] / V1[fin, 3:4], V2[fin, :3] / V2[fin, 3:4], rtol=TOL_SCALE, atol=TOL_SCALE)
    if (~fin).any():
        n1 = V1[~fin, :3] / np.max(np.abs(V1[~fin, :3]), axis=1, keepdims=True)
        n2 = V2[~fin, :3] / np.max(np.abs(V2[~fin, :3]), axis=1, keepdims=True)
        np.testing.assert_allclose(n1, n2, rtol=TOL_SCALE, atol=TOL_SCALE)
    if finite.any() and front.any() and lt["type"] == "point":
        keep = finite & front
        err1, sk1 = self_check(project(cam, L), x1[keep], project(cam, F1), project(cam, Q1[keep]),
                               project(cam, S1[keep]), 1e-9)
        err2, sk2 = self_check(project(cam, k_L * L), x2[keep], project(cam, F2), project(cam, k_P * Q2[keep]),
                               project(cam, S2[keep]), 1e-9)
        assert np.array_equal(sk1, sk2)
        # the self-check errors are differences of image coordinates: for a shadow point far away
        # (small w_S) or an extreme camera they carry the relative 1e-9 of contract §2.8
        uv = np.abs(np.concatenate([divide(x1[keep]), divide(project(cam, S1[keep])), divide(project(cam, Q1[keep]))], axis=1))
        tol_err = 1e-6 + TOL_SCALE * np.max(uv, axis=1)
        assert np.all(np.abs(err1 - err2) <= tol_err), (err1, err2, tol_err)


def check_all_invariants(scene, rel=0.0, rows=(1, 2, 3, 4, 5, 6)):
    result = render(scene)
    doc = result["geometry"]
    if 6 in rows:
        assert_warnings_only(result)
    if 1 in rows:
        assert_construction_check(doc, rel)
    if 2 in rows:
        assert_camera_independent(scene, doc)
    if 3 in rows:
        assert_point_light_converges(scene, doc)
    if 4 in rows:
        assert_rigid_equivariant(scene, doc, rel)
    if 5 in rows:
        assert_positive_scaling(scene, doc)
    return doc


# --------------------------------------------------------------------------- main distribution
@settings(max_examples=40, **COMMON)
@given(scene=scenes(kinds=POLYHEDRAL))
def test_polyhedral_scenes_satisfy_all_invariants(scene):
    """Spec §7.1 rows 1–6 on random polyhedral scenes with random cameras (both camera forms)."""
    doc = check_all_invariants(scene)
    assert doc["shadows"]


@needs_curved
@settings(max_examples=25, **COMMON)
@given(scene=scenes(kinds=ALL_KINDS))
def test_mixed_scenes_satisfy_all_invariants(scene):
    """Spec §7.1 rows 1–6 on scenes with all five primitive types."""
    check_all_invariants(scene)


@settings(max_examples=25, **COMMON)
@given(scene=scenes(kinds=POLYHEDRAL, light=lambda objs: directional_lights(20.0, 85.0)))
def test_directional_light_scenes_converge_from_point_lights(scene):
    """Row 3 focus: every example has a directional light (point light at 1e6 m within 1e-4 m)."""
    doc = check_all_invariants(scene)
    assert doc["points"][f"L.{scene['lights'][0]['id']}"]["at_infinity"] is True


# --------------------------------------------------------------------------- degenerate distributions
@settings(max_examples=25, **COMMON)
@given(scene=scenes(kinds=POLYHEDRAL, camera=lambda objs, lt: cameras(objs, yaw_form=False)).flatmap(
    lambda s: light_behind_camera(s["objects"], s["camera"]).map(
        lambda lt: dict(s, lights=[lt]))))
def test_light_behind_camera_only_warns(scene):
    """Spec §5.7 row 1: finite anti-light point below the horizon, everything else intact."""
    doc = check_all_invariants(scene)
    assert "LIGHT_BEHIND_CAMERA" in codes(doc)
    con = doc["construction"]
    assert con["light_point"] is not None
    assert doc["points"]["L.lamp"]["depth"] < 0


def parallel_light_scenes(exact: bool):
    return scenes(kinds=POLYHEDRAL, camera=lambda objs, lt: cameras(objs, yaw_form=False)).flatmap(
        lambda s: light_parallel_to_picture_plane(s["camera"], exact).map(lambda lt: dict(s, lights=[lt])))


@settings(max_examples=12, **COMMON)
@given(scene=parallel_light_scenes(exact=True))
def test_light_exactly_parallel_to_picture_plane_only_warns(scene):
    """Spec §5.7 row 2, exact case: ``L'`` at infinity (``LIGHT_POINT_AT_INFINITY``), the
    construction rays are parallel to ``light_point_at_infinity``."""
    doc = check_all_invariants(scene, rel=1e-8)
    assert "LIGHT_POINT_AT_INFINITY" in codes(doc)
    con = doc["construction"]
    assert con["light_point"] is None and con["light_point_at_infinity"] is not None
    assert doc["points"]["L.sun"]["image"] is None


@settings(max_examples=25, **COMMON)
@given(scene=parallel_light_scenes(exact=False))
def test_light_nearly_parallel_to_picture_plane_only_warns(scene):
    """Spec §5.7 row 2, nearly parallel: ``forward · d`` down to 1e-7 puts ``L'`` at ~1e9 mm with
    a conditioning of ``1e-16 / |forward · d|`` ~ 1e-9 on its coordinates, hence a relative 1e-8."""
    doc = check_all_invariants(scene, rel=1e-8)
    con = doc["construction"]
    assert "LIGHT_POINT_AT_INFINITY" not in codes(doc)
    assert con["light_point"] is not None and con["light_point_at_infinity"] is None


@settings(max_examples=25, **COMMON)
@given(scene=scenes(kinds=POLYHEDRAL, light=lambda objs: point_lights(objs, above=False)))
def test_vertices_above_the_light_only_warn(scene):
    """Spec §5.7 row 4: unbounded outlines (direction entries) with ``VERTEX_NOT_BELOW_LIGHT``."""
    doc = check_all_invariants(scene)
    light = scene["lights"][0]["position"]
    if max(random_scenes.highest_z(o) for o in scene["objects"]) > light[2]:
        assert "VERTEX_NOT_BELOW_LIGHT" in codes(doc)
        assert any(s["unbounded"] for s in doc["shadows"])
    for s in doc["shadows"]:
        assert s["unbounded"] == any(not isinstance(e, str) for loop in s["loops"] for e in loop)


@settings(max_examples=20, **COMMON)
@given(scene=scenes(kinds=POLYHEDRAL, light=lambda objs: horizontal_sun()))
def test_horizontal_sun_only_warns(scene):
    """Spec §5.7 row 3: no shadows, ``DIRECTIONAL_HORIZONTAL`` (or ``LIGHT_BELOW_RECEIVER`` for a
    sun a hair below the horizon); the drawing is otherwise complete."""
    doc = check_all_invariants(scene, rows=(1, 2, 4, 5, 6))
    dz = scene["lights"][0]["direction"][2]
    if abs(dz) <= 1e-9:
        assert "DIRECTIONAL_HORIZONTAL" in codes(doc)
        assert all(not s["loops"] for s in doc["shadows"])
    elif dz < 0:
        assert "LIGHT_BELOW_RECEIVER" in codes(doc)
    assert doc["edges"] and doc["horizon"]["line"]


@settings(max_examples=20, **COMMON)
@given(scene=scenes(kinds=POLYHEDRAL, camera=lambda objs, lt: camera_straight_down(objs)))
def test_camera_looking_straight_down_only_warns(scene):
    """Contract §2.2: forward parallel to world up uses the fallback up vector and warns."""
    doc = check_all_invariants(scene, rows=(1, 2, 3, 5, 6))
    assert "CAMERA_LOOKING_ALONG_UP" in codes(doc)
    # the ground's line at infinity images to the line at infinity (0, 0, 1): no horizon segment,
    # no v_mm, no x / y vanishing points
    hz = doc["horizon"]
    assert hz["v_mm"] is None and hz["segment"] is None
    assert hz["vanishing_points"]["x"] is None and hz["vanishing_points"]["y"] is None
    assert abs(hz["line"][0]) <= 1e-9 and abs(hz["line"][1]) <= 1e-9 and hz["line"][2] == 1.0
    # looking straight down: the vanishing point of z is the principal point (or absent when roll is odd)
    vp = hz["vanishing_points"]["z"]
    if vp is not None:
        np.testing.assert_allclose(vp, doc["camera"]["principal_point"], rtol=0.0, atol=1e-6)


@settings(max_examples=30, **COMMON)
@given(scene=scenes(kinds=POLYHEDRAL, camera=extreme_cameras))
def test_extreme_camera_parameters_only_warn(scene):
    """roll ±180°, near 1e-6 … 3 m, f 8 … 5000 mm, shift ±20 mm: no exceptions, finite output; the
    image-space rows use the relative tolerance of the module docstring."""
    check_all_invariants(scene, rel=1e-9)


@needs_curved
@settings(max_examples=20, **COMMON)
@given(scene=scenes(kinds=ALL_KINDS, camera=extreme_cameras, light=lambda objs: point_lights(objs, above=False)))
def test_everything_degenerate_at_once_only_warns(scene):
    """All primitive types, light below some tops, extreme camera: warnings only (rows 2, 5, 6)."""
    doc = check_all_invariants(scene, rel=1e-9, rows=(2, 5, 6))
    assert codes(doc) <= set(WARNING_CODES)


# --------------------------------------------------------------------------- strategies themselves
@settings(max_examples=30, **COMMON)
@given(scene=scenes(kinds=ALL_KINDS if INCLUDE_CURVED else POLYHEDRAL))
def test_generated_scenes_are_valid_and_above_the_ground(scene):
    """Every generated scene validates and no object dips below the receiver (no OBJECT_BELOW_RECEIVER)."""
    validated = load_scene(scene)
    assert validated["version"] == "0.1"
    for o in scene["objects"]:
        assert random_scenes.lowest_z(o) >= 0.0
    doc = castplane.render(validated)["geometry"]
    assert "OBJECT_BELOW_RECEIVER" not in codes(doc)
