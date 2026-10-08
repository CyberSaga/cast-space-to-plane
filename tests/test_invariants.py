"""The six invariants of spec §7.1 (contract §4) on the examples and random polyhedral and mixed scenes
(mixed scenes contain cylinders, spheres and cones; M2).

| row | invariant                         | tolerance |
| 1   | construction = direct             | 1e-6 mm   |
| 2   | shadows independent of the camera | 1e-9 m    |
| 3   | point light -> directional light  | max(1e-4 m, 2·δ), tenfold shrink 1e6 → 1e7 m (D20) |
| 4   | rigid equivariance (Z rot + XY)   | 1e-6 mm   |
| 5   | homogeneous scale invariance      | 1e-9      |
| 6   | no NaN / Inf                      | -         |
"""

from __future__ import annotations

import copy
import math
import pathlib
import re

import numpy as np
import pytest

import castplane
from castplane.camera import camera_matrix, divide, project
from castplane.conics import conic_entry, circle_record
from castplane.construction import self_check, special_point_image
from castplane.curved import shadow_outline, shadow_polygon_h
from castplane.light import light_vector
from castplane.output.geometry_json import dumps
from castplane.primitives import build_object
from castplane.scene import load_scene, validate_camera
from castplane.shadow import foot, shadow_loop, shadow_matrix
from tests.reference import random_scenes

EXAMPLES = pathlib.Path(__file__).resolve().parents[1] / "examples"
EXAMPLE_NAMES = ("basic.json", "directional.json", "three_point.json", "construction_demo.json", "curved_demo.json")
GROUND = np.array([0.0, 0.0, 1.0, 0.0])
CURVED = ("cylinder", "sphere", "cone")


def walk_numbers(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_numbers(v)
    elif isinstance(obj, float):
        yield obj


def polyhedral_scene(seed: int, n: int = 3, light_type=None) -> dict:
    rng = np.random.default_rng(seed)
    objects = [random_scenes.random_object(rng, i, "box" if i % 2 else "prism") for i in range(n)]
    light = random_scenes.random_light(rng, objects, light_type)
    return random_scenes.assemble_scene(objects, light, random_scenes.random_camera(rng, objects))


def mixed_scene(seed: int, n: int = 5, light_type=None) -> dict:
    """Random scene with all five primitive kinds (``n >= 5``: one of each first), tilted objects allowed."""
    return random_scenes.make_scene(seed, n, light_type)


def all_scenes():
    out = [load_scene(EXAMPLES / name) for name in EXAMPLE_NAMES]
    rolled = copy.deepcopy(out[3])
    rolled["camera"]["roll_deg"] = 90.0                     # vertical horizon: v_mm is null
    out.append(load_scene(rolled))
    out += [load_scene(polyhedral_scene(seed, 1 + seed % 4)) for seed in range(6)]
    out += [load_scene(polyhedral_scene(100 + seed, 2, "directional")) for seed in range(3)]
    out += [load_scene(mixed_scene(200 + seed, 5 + seed % 2)) for seed in range(3)]            # M2: curved objects
    out += [load_scene(mixed_scene(300 + seed, 5, "directional")) for seed in range(2)]
    return out


def polyhedral_ids(scene) -> set:
    return {o["id"] for o in scene["objects"] if o["type"] not in CURVED}


SCENES = all_scenes()


def geometry(scene, camera=None):
    return castplane.render(scene, camera=camera)["geometry"]


def meet_lines(a, b, c, d):
    """Meet of the lines ``a×b`` and ``c×d`` of homogeneous 2-D points (spec §5.5)."""
    return np.cross(np.cross(a, b), np.cross(c, d))


def homogeneous(point, direction):
    """Homogeneous 3-vector of a finite image point or of a direction (point at infinity)."""
    if point is not None:
        return np.array([point[0], point[1], 1.0])
    return np.array([direction[0], direction[1], 0.0])


# --------------------------------------------------------------------------- row 1
@pytest.mark.parametrize("scene", SCENES)
def test_construction_equals_direct_projection(scene):
    doc = geometry(scene)
    checks = doc["construction"]["checks"]
    assert checks, "every scene here has shadow vertices"
    assert max(c["max_error_mm"] for c in checks) <= 1e-6
    # independent recomputation from the points dict (spec §5.5, §7.1 row 1)
    con = doc["construction"]
    light = scene["lights"][0]["id"]
    Lp = homogeneous(con["light_point"], con["light_point_at_infinity"])
    Fp = homogeneous(con["shadow_vp"], con["shadow_vp_at_infinity"])
    skipped = {w["ids"][0] for w in doc["warnings"] if w["code"] == "CONSTRUCTION_CHECK_SKIPPED"}
    verified = 0
    for kind, name in con["rays"]:
        if kind != "L":
            continue
        P = doc["points"][name]["image"]
        S = doc["points"][f"{name}.shadow.{light}"]["image"]
        Q = doc["points"][f"{name}.foot"]["image"]
        if f"{name}.shadow.{light}" in skipped or P is None or S is None or Q is None:
            continue
        s_check = meet_lines(Lp, np.array(P + [1.0]), Fp, np.array(Q + [1.0]))
        assert abs(s_check[2]) > 1e-12
        np.testing.assert_allclose(s_check[:2] / s_check[2], S, atol=1e-6)
        verified += 1
    assert verified > 0


# --------------------------------------------------------------------------- row 2
@pytest.mark.parametrize("scene", SCENES)
def test_shadows_are_camera_independent(scene):
    doc1 = geometry(scene)
    cam2 = {"position": [-6.0, -4.0, 7.0], "target": [0.0, 3.0, 0.0], "roll_deg": 15.0, "focal_length_mm": 20.0,
            "frame_mm": list(scene["camera"]["frame_mm"]), "shift_mm": [1.0, -2.0], "near_m": 0.1}
    doc2 = geometry(scene, camera=cam2)
    assert doc1["camera"]["P"] != doc2["camera"]["P"]
    # camera outline generator endpoints of curved objects (<obj>.og<k>.*) legitimately move with the camera
    names1 = {n for n in doc1["points"] if ".og" not in n}
    assert names1 == {n for n in doc2["points"] if ".og" not in n}
    for name in names1:
        p = doc1["points"][name]
        if "world" in p:
            np.testing.assert_allclose(p["world"], doc2["points"][name]["world"], atol=1e-9)
        else:
            np.testing.assert_allclose(p["direction"], doc2["points"][name]["direction"], atol=1e-9)
    assert [s["loops"] for s in doc1["shadows"]] == [s["loops"] for s in doc2["shadows"]]
    assert [s["unbounded"] for s in doc1["shadows"]] == [s["unbounded"] for s in doc2["shadows"]]
    assert [f["faces"] for f in doc1["form_shadow"]] == [f["faces"] for f in doc2["form_shadow"]]
    assert [[t["segment"] for t in f["terminator"] if "segment" in t] for f in doc1["form_shadow"]] == \
        [[t["segment"] for t in f["terminator"] if "segment" in t] for f in doc2["form_shadow"]]
    poly = polyhedral_ids(scene)
    assert [e["silhouette"] for e in doc1["edges"] if e["object"] in poly] == \
        [e["silhouette"] for e in doc2["edges"] if e["object"] in poly]
    # the world circles and arcs of the shadow conics are camera free; their image conics are not
    for s1, s2 in zip(doc1["shadows"], doc2["shadows"]):
        assert [(c["circle"], c["arc"]) for c in s1["conics"]] == [(c["circle"], c["arc"]) for c in s2["conics"]]


# --------------------------------------------------------------------------- row 3
#: Spec §7.1 row 3 tolerance (m) and the two distances (m) at which a point light stands in for the sun.
TOL_CONVERGE = 1e-4
FAR, FARTHER = 1e6, 1e7
#: Absolute floor (m) of the tenfold-shrink comparison (rounding of world coordinates of a few metres).
SHRINK_FLOOR = 1e-9


def far_point_light_scene(scene, distance):
    """``scene`` with its directional light replaced by a point light ``distance`` metres along the sun
    direction from the world origin (spec §7.1 row 3; contract §4 (iii), DECISIONS D20)."""
    far = copy.deepcopy(scene)
    d = np.asarray(scene["lights"][0]["direction"], dtype=np.float64)
    far["lights"][0] = {"id": scene["lights"][0]["id"], "type": "point", "position": (distance * d).tolist()}
    return far


def predicted_gap(doc_d, doc_p, name, distance, sin_e):
    """First-order bound (m) on the distance between the directional shadow ``name`` of ``doc_d`` and the
    point-light shadow of the same name in ``doc_p`` (DECISIONS D20).  A source point at height ``h`` whose
    directional shadow lies ``|S_dir|`` from the origin the light recedes from has the point-light shadow
    ``S_dir · D sin e / (D sin e − h)`` (a homothety about the origin, exact), i.e. a gap of
    ``h · |S_dir| / (D sin e − h)``; the construction points of curved objects (tangent generators,
    silhouette-circle quadrant points) also move by themselves at first order in ``1/D``, and the
    directional shadow map stretches that motion by at most ``1 / sin e``."""
    src = name.split(".shadow.")[0]
    h = float(doc_d["points"][src]["world"][2])
    s_dir = np.asarray(doc_d["points"][name]["world"][:2], dtype=np.float64)
    shift = float(np.linalg.norm(np.subtract(doc_p["points"][src]["world"], doc_d["points"][src]["world"])))
    return h * float(np.linalg.norm(s_dir)) / (distance * sin_e - h) + shift / sin_e


def shadow_gap(doc_d, doc_p, name) -> float:
    return float(np.linalg.norm(np.subtract(doc_p["points"][name]["world"], doc_d["points"][name]["world"])))


def assert_shrinks_tenfold(gaps):
    """``gaps[key] = {FAR: gap, FARTHER: gap}``: every gap at 1e7 m is at most a tenth of the one at 1e6 m."""
    for key, g in gaps.items():
        assert g[FARTHER] <= 0.1 * g[FAR] + SHRINK_FLOOR, (key, g)


@pytest.mark.parametrize("seed", [100, 101, 102, 7])
def test_point_light_converges_to_directional_light(seed):
    """Row 3 on polyhedral scenes with the tolerance of contract §4 (iii): every named shadow point is within
    ``max(1e-4 m, 2·δ)`` of the directional one (``δ`` the first-order bound of D20), the gap of a mesh vertex
    is exactly the homothety of D20 (1e-9 m), the loops are identical and the gap shrinks tenfold when the
    light recedes from 1e6 m to 1e7 m."""
    scene = load_scene(polyhedral_scene(seed, 2, "directional"))
    sin_e = float(scene["lights"][0]["direction"][2])
    doc_d = geometry(scene)
    shadow_names = [n for n in doc_d["points"] if ".shadow." in n]
    assert shadow_names
    gaps = {}
    for D in (FAR, FARTHER):
        doc_p = geometry(far_point_light_scene(scene, D))
        assert not any(w["code"] == "VERTEX_NOT_BELOW_LIGHT" for w in doc_p["warnings"])
        assert set(shadow_names) <= set(doc_p["points"])
        assert [s["loops"] for s in doc_d["shadows"]] == [s["loops"] for s in doc_p["shadows"]]
        for name in shadow_names:
            s_d = np.asarray(doc_d["points"][name]["world"], dtype=np.float64)
            s_p = np.asarray(doc_p["points"][name]["world"], dtype=np.float64)
            h = float(doc_d["points"][name.split(".shadow.")[0]]["world"][2])
            exact = np.array([s_d[0], s_d[1], 0.0]) * (h / (D * sin_e - h))
            np.testing.assert_allclose(s_p - s_d, exact, rtol=0.0, atol=1e-9, err_msg=f"{name} at {D:g} m")
            gap = shadow_gap(doc_d, doc_p, name)
            assert gap <= max(TOL_CONVERGE, 2.0 * predicted_gap(doc_d, doc_p, name, D, sin_e)), (name, D, gap)
            gaps.setdefault(name, {})[D] = gap
    assert_shrinks_tenfold(gaps)


def polyline_distance(A, B) -> float:
    """Largest distance from a vertex of the closed polygon ``A`` to the closed polygon ``B`` (2-D)."""
    A, B = np.asarray(A, dtype=np.float64), np.asarray(B, dtype=np.float64)
    P0, P1 = B, np.roll(B, -1, axis=0)
    d = P1 - P0
    dd = np.einsum("ij,ij->i", d, d)
    worst = 0.0
    for a in A:
        t = np.clip(np.einsum("ij,ij->i", a[None, :] - P0, d) / np.where(dd == 0.0, 1.0, dd), 0.0, 1.0)
        q = P0 + t[:, None] * d
        worst = max(worst, float(np.min(np.linalg.norm(q - a[None, :], axis=1))))
    return worst


@pytest.mark.parametrize("seed", [300, 301, 302])
def test_point_light_converges_to_directional_light_for_curved_objects(seed):
    """Row 3 on mixed scenes (contract §4 (iii), D20): the named shadow points (construction points of the
    curved objects included) are within ``max(1e-4 m, 2·δ)`` of the directional ones, the sampled ground
    polygons of the conic shadows coincide within the same bound taken at the object's highest point, and
    both gaps shrink tenfold from 1e6 m to 1e7 m."""
    scene = load_scene(mixed_scene(seed, 5, "directional"))
    sin_e = float(scene["lights"][0]["direction"][2])
    doc_d = geometry(scene)
    shadow_names = [n for n in doc_d["points"] if ".shadow." in n]
    curved = {o["id"] for o in scene["objects"] if o["type"] in CURVED}
    assert any(n.split(".")[0] in curved for n in shadow_names)
    top = {o["id"]: random_scenes.highest_z(o) for o in scene["objects"]}
    gaps = {}
    for D in (FAR, FARTHER):
        doc_p = geometry(far_point_light_scene(scene, D))
        assert not any(w["code"] == "VERTEX_NOT_BELOW_LIGHT" for w in doc_p["warnings"])
        assert set(shadow_names) == {n for n in doc_p["points"] if ".shadow." in n}
        shift = {}                      # per object: largest motion (m) of a construction point itself
        for name in shadow_names:
            gap = shadow_gap(doc_d, doc_p, name)
            assert gap <= max(TOL_CONVERGE, 2.0 * predicted_gap(doc_d, doc_p, name, D, sin_e)), (name, D, gap)
            gaps.setdefault(name, {})[D] = gap
            src = name.split(".shadow.")[0]
            oid = src.split(".")[0]
            motion = float(np.linalg.norm(np.subtract(doc_p["points"][src]["world"], doc_d["points"][src]["world"])))
            shift[oid] = max(shift.get(oid, 0.0), motion)
        for s_d, s_p in zip(doc_d["shadows"], doc_p["shadows"]):
            assert s_d["object"] == s_p["object"] and len(s_d["loops"]) == len(s_p["loops"])
            h = top[s_d["object"]]
            for k, (l_d, l_p) in enumerate(zip(s_d["loops"], s_p["loops"])):
                A = np.array([doc_d["points"][n]["world"][:2] for n in l_d])
                B = np.array([doc_p["points"][n]["world"][:2] for n in l_p])
                bound = h * float(np.max(np.linalg.norm(A, axis=1))) / (D * sin_e - h) + shift.get(s_d["object"], 0.0) / sin_e
                dist = max(polyline_distance(A, B), polyline_distance(B, A))
                assert dist <= max(TOL_CONVERGE, 2.0 * bound), (s_d["object"], k, D, dist, bound)
                gaps.setdefault((s_d["object"], k), {})[D] = dist
    assert_shrinks_tenfold(gaps)


# --------------------------------------------------------------------------- row 4
def rot_z(angle_deg):
    a = math.radians(angle_deg)
    return np.array([[math.cos(a), -math.sin(a), 0.0], [math.sin(a), math.cos(a), 0.0], [0.0, 0.0, 1.0]])


def yaw_pitch_of(camera):
    """Yaw / pitch of a target-form camera (contract §2.2 formula inverted)."""
    f = np.array(camera["target"]) - np.array(camera["position"])
    f = f / np.linalg.norm(f)
    return math.degrees(math.atan2(-f[0], f[1])), math.degrees(math.asin(max(-1.0, min(1.0, f[2]))))


def transform_scene(scene, angle_deg, shift, yaw_form):
    R = rot_z(angle_deg)
    t = np.array([shift[0], shift[1], 0.0])
    out = copy.deepcopy(scene)
    for o in out["objects"]:
        tr = o["transform"]
        tr["position"] = (R @ np.array(tr["position"]) + t).tolist()
        tr["rotation_deg"] = [tr["rotation_deg"][0], tr["rotation_deg"][1], tr["rotation_deg"][2] + angle_deg]
    lt = out["lights"][0]
    if lt["type"] == "point":
        lt["position"] = (R @ np.array(lt["position"]) + t).tolist()
    else:
        d = R @ np.array(lt["direction"])
        lt["direction"] = (d / np.linalg.norm(d)).tolist()
    cam = out["camera"]
    if "target" not in cam:
        cam["target"] = (np.array(cam["position"]) + np.array([
            -math.sin(math.radians(cam["yaw_deg"])) * math.cos(math.radians(cam["pitch_deg"])),
            math.cos(math.radians(cam["yaw_deg"])) * math.cos(math.radians(cam["pitch_deg"])),
            math.sin(math.radians(cam["pitch_deg"]))])).tolist()
        del cam["yaw_deg"], cam["pitch_deg"]
    if yaw_form:
        yaw, pitch = yaw_pitch_of(cam)
        cam["yaw_deg"], cam["pitch_deg"] = yaw + angle_deg, pitch
        cam["position"] = (R @ np.array(cam["position"]) + t).tolist()
        del cam["target"]
    else:
        cam["position"] = (R @ np.array(cam["position"]) + t).tolist()
        cam["target"] = (R @ np.array(cam["target"]) + t).tolist()
    return out


def assert_drawables_equal(entries1, entries2, atol):
    """Conic entries of two documents draw the same curves: same kinds and parameter ranges, sampled
    polylines and arc endpoints within ``atol`` mm, same arc flags, ellipse centres and axes within
    ``atol`` (the rotation of a nearly circular ellipse is numerically arbitrary and is not compared)."""
    assert len(entries1) == len(entries2)
    for c1, c2 in zip(entries1, entries2):
        assert c1["kind"] == c2["kind"] and c1["which"] == c2["which"] and c1["sampled"] == c2["sampled"]
        assert (c1["arc"] is None) == (c2["arc"] is None)
        assert len(c1["polylines"]) == len(c2["polylines"]) and len(c1["arcs"]) == len(c2["arcs"])
        assert len(c1["ellipses"]) == len(c2["ellipses"])
        for p1, p2 in zip(c1["polylines"], c2["polylines"]):
            np.testing.assert_allclose(p1, p2, atol=atol)
        for a1, a2 in zip(c1["arcs"], c2["arcs"]):
            np.testing.assert_allclose([a1["start"], a1["end"]], [a2["start"], a2["end"]], atol=atol)
            assert a1["large_arc"] == a2["large_arc"] and a1["sweep"] == a2["sweep"]
            np.testing.assert_allclose([a1["rx"], a1["ry"]], [a2["rx"], a2["ry"]], atol=atol, rtol=1e-9)
        for e1, e2 in zip(c1["ellipses"], c2["ellipses"]):
            np.testing.assert_allclose(e1["centre"], e2["centre"], atol=atol)
            np.testing.assert_allclose([e1["rx"], e1["ry"]], [e2["rx"], e2["ry"]], atol=atol, rtol=1e-9)


def assert_images_equal(doc1, doc2, atol):
    assert set(doc1["points"]) == set(doc2["points"])
    for name, p in doc1["points"].items():
        q = doc2["points"][name]
        assert (p["image"] is None) == (q["image"] is None), name
        if p["image"] is not None:
            np.testing.assert_allclose(p["image"], q["image"], atol=atol, err_msg=name)
    for e1, e2 in zip(doc1["edges"], doc2["edges"]):
        assert (e1["segment"] is None) == (e2["segment"] is None)
        assert e1["back"] == e2["back"] and e1["silhouette"] == e2["silhouette"]
        if e1["segment"] is not None:
            np.testing.assert_allclose(e1["segment"], e2["segment"], atol=atol)
    for s1, s2 in zip(doc1["shadows"], doc2["shadows"]):
        assert s1["loops"] == s2["loops"] and s1["unbounded"] == s2["unbounded"]
        for p1, p2 in zip(s1["polygons"], s2["polygons"]):
            np.testing.assert_allclose(p1, p2, atol=atol)
    for f1, f2 in zip(doc1["form_shadow"], doc2["form_shadow"]):
        assert f1["faces"] == f2["faces"]
        for p1, p2 in zip(f1["polygons"], f2["polygons"]):
            np.testing.assert_allclose(p1, p2, atol=atol)
        assert_drawables_equal([t for t in f1["terminator"] if "segment" not in t],
                               [t for t in f2["terminator"] if "segment" not in t], atol)
        for t1, t2 in zip(f1["terminator"], f2["terminator"]):
            if "segment" in t1:
                assert t1["segment"] == t2["segment"]
                np.testing.assert_allclose(t1["polylines"], t2["polylines"], atol=atol)
    for s1, s2 in zip(doc1["shadows"], doc2["shadows"]):
        assert_drawables_equal(s1["conics"], s2["conics"], atol)
    for o1, o2 in zip(doc1["outlines"], doc2["outlines"]):
        assert o1["object"] == o2["object"]
        assert [c["back"] for c in o1["conics"]] == [c["back"] for c in o2["conics"]]
        assert_drawables_equal(o1["conics"], o2["conics"], atol)
    c1, c2 = doc1["construction"], doc2["construction"]
    for key in ("light_point", "shadow_vp"):
        assert (c1[key] is None) == (c2[key] is None)
        if c1[key] is not None:
            np.testing.assert_allclose(c1[key], c2[key], atol=atol)
    assert c1["rays"] == c2["rays"]
    assert [s["kind"] for s in c1["segments"]] == [s["kind"] for s in c2["segments"]]
    light = doc1["shadows"][0]["light"] if doc1["shadows"] else None
    for s1, s2 in zip(c1["segments"], c2["segments"]):
        # a ray is a 2-D segment through P', S', Q' and L'/F' then clipped to the canvas rectangle; its clipped
        # endpoint inherits the conditioning of its defining points, so the tolerance scales with their size
        nm = s1["point"]
        defining = [doc1["points"][nm]["image"], doc1["points"][f"{nm}.shadow.{light}"]["image"],
                    doc1["points"][f"{nm}.foot"]["image"], c1["light_point"], c1["shadow_vp"]]
        scale = max(1.0, max(abs(x) for p in defining if p is not None for x in p))
        np.testing.assert_allclose(s1["points"], s2["points"], atol=atol * scale)
    v1, v2 = doc1["horizon"]["v_mm"], doc2["horizon"]["v_mm"]
    assert (v1 is None) == (v2 is None)
    if v1 is not None:
        assert abs(v1 - v2) < atol
    assert [w["code"] for w in doc1["warnings"]] == [w["code"] for w in doc2["warnings"]]


@pytest.mark.parametrize("scene", SCENES)
@pytest.mark.parametrize("yaw_form", [False, True])
def test_rigid_equivariance(scene, yaw_form):
    doc1 = geometry(scene)
    for angle, shift in ((37.0, (2.5, -1.25)), (-120.0, (-4.0, 3.0)), (180.0, (0.0, 0.0))):
        doc2 = geometry(load_scene(transform_scene(scene, angle, shift, yaw_form)))
        assert_images_equal(doc1, doc2, 1e-6)


# --------------------------------------------------------------------------- row 5
def _cam():
    cam = validate_camera({"position": [1.0, -2.0, 1.5], "target": [0.0, 5.0, 0.5], "focal_length_mm": 35,
                           "frame_mm": [36, 24], "shift_mm": [1.0, 0.5]})
    return camera_matrix(cam, [36, 24])


@pytest.mark.parametrize("k_pi, k_L, k_P", [(2.0, 3.0, 0.5), (1e-3, 1e3, 7.0), (5.0, 0.25, 1e2)])
def test_homogeneous_scale_invariance_positive_scalars(k_pi, k_L, k_P):
    """Row 5 with positive scalars on every input (contract §2.1 oriented representatives)."""
    L = light_vector({"type": "point", "position": [1.0, 2.0, 4.0]})
    P = np.array([[0.3, 0.4, 1.0, 1.0], [-1.0, 2.0, 0.5, 1.0], [2.0, -1.0, 3.0, 1.0]])
    cam = _cam()
    for Lv in (L, light_vector({"type": "directional", "direction": [0.6, 0.0, 0.8]})):
        M1 = shadow_matrix(GROUND, Lv)
        M2 = shadow_matrix(k_pi * GROUND, k_L * Lv)
        S1 = P @ M1.T
        S2 = (k_P * P) @ M2.T
        np.testing.assert_allclose(S1[:, :3] / S1[:, 3:4], S2[:, :3] / S2[:, 3:4], rtol=1e-9, atol=1e-9)
        Q1, Q2 = foot(GROUND, P), foot(k_pi * GROUND, k_P * P)
        np.testing.assert_allclose(Q1[:, :3] / Q1[:, 3:4], Q2[:, :3] / Q2[:, 3:4], rtol=1e-9, atol=1e-9)
        F1, F2 = foot(GROUND, Lv), foot(k_pi * GROUND, k_L * Lv)
        np.testing.assert_allclose(F1 / np.max(np.abs(F1)), F2 / np.max(np.abs(F2)), rtol=1e-9, atol=1e-9)
        # light-side predicate keeps its sign under positive scaling (contract §2.3)
        assert (k_pi * GROUND) @ (k_L * Lv) > 0
        # shadow loops: same divided polygon
        loop = np.array([[0.0, 0.0, 2.0, 1.0], [1.0, 0.0, 2.0, 1.0], [1.0, 1.0, 2.0, 1.0], [0.0, 1.0, 2.0, 1.0]])
        sh1 = shadow_loop(loop, M1, GROUND, 1e-9)
        sh2 = shadow_loop(k_P * loop, M2, k_pi * GROUND, 1e-9)
        V1, V2 = sh1["vertices"], sh2["vertices"]
        np.testing.assert_allclose(V1[:, :3] / V1[:, 3:4], V2[:, :3] / V2[:, 3:4], rtol=1e-9, atol=1e-9)
        # image coordinates and the construction self-check are unchanged
        Lp1, Lp2 = project(cam, Lv), project(cam, k_L * Lv)
        err1, sk1 = self_check(Lp1, project(cam, P), project(cam, F1), project(cam, Q1), project(cam, S1), 1e-9)
        err2, sk2 = self_check(Lp2, project(cam, k_P * P), project(cam, F2), project(cam, k_P * Q2),
                               project(cam, S2), 1e-9)
        assert not sk1.any() and not sk2.any()
        assert np.max(err1) < 1e-9 and np.max(err2) < 1e-9


@pytest.mark.parametrize("k_pi, k_L, k_P", [(2.0, 3.0, 0.5), (1e-3, 1e3, 7.0), (5.0, 0.25, 1e2)])
@pytest.mark.parametrize("kind", CURVED)
def test_homogeneous_scale_invariance_curved_objects(k_pi, k_L, k_P, kind):
    """Row 5 for curved objects: the silhouette / shadow outline of contract §2.6 under positively scaled
    ``pi`` and ``L`` (and the matching ``M``) gives the same divided ground polygon and the same conic
    entries; the conic entry of a circle is invariant under any non-zero scaling of its map ``H``."""
    o = {"id": "o", "type": kind, "radius": 0.4, "transform": {"position": [1.0, 2.0, 0.0],
                                                                "rotation_deg": [10.0, -5.0, 30.0]}}
    if kind != "sphere":
        o["height"] = 1.3
    an = build_object(o)["analytic"]
    cam = _cam()
    for Lv in (light_vector({"type": "point", "position": [-1.0, 0.5, 3.0]}),
               light_vector({"type": "directional", "direction": [0.6, 0.0, 0.8]})):
        M1, M2 = shadow_matrix(GROUND, Lv), shadow_matrix(k_pi * GROUND, k_L * Lv)
        # the plane functional (ground clip) and w_S scale with k_pi: so do the length-valued tolerances
        out1 = shadow_outline(an, Lv, M1, GROUND, 1e-9, 1e-9)
        out2 = shadow_outline(an, k_L * Lv, M2, k_pi * GROUND, k_pi * 1e-9, k_pi * 1e-9)
        V1, V2 = shadow_polygon_h(out1)["vertices"], shadow_polygon_h(out2)["vertices"]
        assert V1.shape == V2.shape and V1.shape[0] >= 3
        np.testing.assert_allclose(V1[:, :3] / V1[:, 3:4], V2[:, :3] / V2[:, 3:4], rtol=1e-9, atol=1e-9)
        pieces1 = [p["conic_arc"] for p in out1["pieces"] if "conic_arc" in p]
        pieces2 = [p["conic_arc"] for p in out2["pieces"] if "conic_arc" in p]
        assert len(pieces1) == len(pieces2) >= 1
        for a1, a2 in zip(pieces1, pieces2):
            H1, H2 = cam["P"] @ a1["T"] @ a1["E"], cam["P"] @ a2["T"] @ a2["E"]
            e1 = conic_entry(a1["circle"], H1, (a1["theta0"], a1["theta1"]), "shadow")
            e2 = conic_entry(a2["circle"], H2, (a2["theta0"], a2["theta1"]), "shadow")
            np.testing.assert_allclose(e1["conic"], e2["conic"], rtol=1e-9, atol=1e-9)
            assert e1["kind"] == e2["kind"] and e1["arc"] == pytest.approx(e2["arc"], rel=1e-9)
            for k in (-1.0, 2.0, -1e-3):   # sign-free: the conic matrix up to sign (contract §2.1)
                e3 = conic_entry(a1["circle"], k * H1, (a1["theta0"], a1["theta1"]), "shadow")
                np.testing.assert_allclose(e3["conic"], e1["conic"], rtol=1e-9, atol=1e-9)
                assert e3["kind"] == e1["kind"]
    circle = circle_record([0.3, 0.4, 0.5], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], 0.25)
    E = np.array([[1.0, 0, 0.3], [0, 1.0, 0.4], [0, 0, 0.5], [0, 0, 1.0]])          # the circle's embedding
    base = conic_entry(circle, cam["P"] @ E, None)
    for k in (k_pi, -k_L, 1e-3):
        scaled = conic_entry(circle, k * (cam["P"] @ E), None)
        np.testing.assert_allclose(scaled["conic"], base["conic"], rtol=1e-9, atol=1e-9)
        assert scaled["kind"] == base["kind"] == "ellipse"


@pytest.mark.parametrize("k", [-1.0, -3.0, 2.0, -1e-3])
def test_homogeneous_scale_invariance_sign_free_outputs(k):
    """Row 5 with scalars of either sign on sign-free outputs: image coordinates of finite points,
    divided ground points, lines and their meets (contract §2.1)."""
    cam = _cam()
    X = np.array([[0.3, 0.4, 1.0, 1.0], [-1.0, 2.0, 0.5, 1.0]])
    np.testing.assert_allclose(divide(project(cam, X)), divide(project(cam, k * X)), rtol=1e-9)
    L = light_vector({"type": "point", "position": [1.0, 2.0, 4.0]})
    lp = special_point_image(cam, L, 1e-9)
    lp_k = special_point_image(cam, k * L, 1e-9)
    np.testing.assert_allclose(lp["point"], lp_k["point"], rtol=1e-9)
    M = shadow_matrix(GROUND, L)
    S = X @ M.T
    S_k = (k * X) @ (k * M).T
    np.testing.assert_allclose(S[:, :3] / S[:, 3:4], S_k[:, :3] / S_k[:, 3:4], rtol=1e-9)
    F, Q = foot(GROUND, L), foot(GROUND, X)
    err, sk = self_check(k * project(cam, L), project(cam, X), project(cam, F), k * project(cam, Q),
                         k * project(cam, S), 1e-9)
    assert not sk.any() and np.max(err) < 1e-9
    # a scaled camera matrix gives the same image coordinates
    cam_k = dict(cam, P=k * cam["P"])
    np.testing.assert_allclose(divide(project(cam_k, X)), divide(project(cam, X)), rtol=1e-9)


# --------------------------------------------------------------------------- row 6
def degenerate_scenes():
    base = load_scene(EXAMPLES / "construction_demo.json")
    out = []
    s = copy.deepcopy(base)
    s["lights"][0]["position"] = [0.0, -6.0, 4.0]                   # light behind the camera
    out.append(s)
    s = copy.deepcopy(base)
    s["lights"][0] = {"id": "sun", "type": "directional", "direction": [0.0, 0.0, 1.0]}   # vertical sun
    out.append(s)
    s = copy.deepcopy(base)
    s["lights"][0] = {"id": "sun", "type": "directional", "direction": [1.0, 0.0, 0.0]}   # horizontal sun
    out.append(s)
    s = copy.deepcopy(base)
    s["lights"][0] = {"id": "sun", "type": "directional", "direction": [0.0, 0.0, -1.0]}  # below the ground
    out.append(s)
    s = copy.deepcopy(base)
    s["lights"][0]["position"] = [0.0, 4.0, 1.0]                     # lower than the block: unbounded
    out.append(s)
    s = copy.deepcopy(base)
    s["lights"][0]["position"] = [0.0, 4.0, -1.0]                    # below the receiver
    out.append(s)
    s = copy.deepcopy(base)
    s["lights"][0]["position"] = [1.2, 5.0, 0.8]                     # exactly at a crate top vertex height
    out.append(s)
    s = copy.deepcopy(base)
    s["camera"]["position"] = [1.2, 5.0, 0.4]                        # camera inside the crate
    s["camera"]["target"] = [1.2, 9.0, 0.4]
    out.append(s)
    s = copy.deepcopy(base)
    s["objects"][0]["transform"]["position"][2] = -0.4               # half-buried crate
    out.append(s)
    s = copy.deepcopy(base)
    s["camera"]["position"] = [0.0, 3.0, 12.0]                       # looking straight down
    s["camera"]["target"] = [0.0, 3.0, 0.0]
    out.append(s)
    s = copy.deepcopy(base)
    s["lights"][0] = {"id": "sun", "type": "directional", "direction": [0.6, 0.0, 0.8]}  # L' at infinity
    s["camera"]["position"] = [0.0, -2.0, 1.6]
    s["camera"]["target"] = [0.0, 5.0, 1.6]
    out.append(s)
    return out


@pytest.mark.parametrize("scene", degenerate_scenes() + SCENES)
def test_no_nan_or_inf(scene):
    result = castplane.render(scene)
    doc, svg = result["geometry"], result["svg"]
    assert all(math.isfinite(x) for x in walk_numbers(doc))
    text = dumps(doc)
    assert "NaN" not in text and "Infinity" not in text and not re.search(r"-0\.0(?![0-9])", text)
    low = svg.lower().replace("infinity", "")
    assert "nan" not in low and "inf" not in low


# --------------------------------------------------------------------------- M6: row 2 for the umbra (contract §5.3.10)
def _umbra_ground(doc):
    from tests.test_multilight import map_back
    return [uv for _w, uv in map_back(doc, doc["umbra"][0]["polygons"])]


@pytest.mark.parametrize("which", ["acceptance", "three_lights"])
def test_umbra_ground_image_is_camera_independent(which):
    """Two cameras that both see the whole umbra: the ground images (``H⁻¹``) of the umbra pieces have equal
    union area within 1e-9 (relative) and the same vertex set -- the corner vertices of the union, since the
    slab decomposition itself is made in the image -- within 1e-9 m on the acceptance scene.  On the
    three-light scene the snapping of §5.3.4 step 1 (≤ tol_mm along the image ``v`` axis, a camera-dependent
    direction) moves vertices by ~1e-7 m on the ground and kinks short edges, so its corners are compared
    by their turning angle > 1e-3 at 1e-6 m (implementation note of §5.3)."""
    from tests.test_multilight import acceptance_scene, shoelace, three_light_scene, union_corners
    scene = load_scene(acceptance_scene() if which == "acceptance" else three_light_scene())
    cam2 = dict(scene["camera"])
    if which == "acceptance":
        cam2.update(position=[2.0, -5.0, 5.5], target=[0.2, 0.1, 0.0], roll_deg=7.0, focal_length_mm=30.0)
    else:
        cam2.update(position=[-7.0, -6.0, 8.0], target=[0.5, 0.5, 0.0], roll_deg=-10.0, focal_length_mm=24.0)
    doc1, doc2 = geometry(scene), geometry(scene, camera=cam2)
    assert doc1["camera"]["P"] != doc2["camera"]["P"]
    g1, g2 = _umbra_ground(doc1), _umbra_ground(doc2)
    assert g1 and g2
    a1, a2 = sum(shoelace(p) for p in g1), sum(shoelace(p) for p in g2)
    assert a2 == pytest.approx(a1, rel=1e-9)
    tol, angle_tol = (1e-9, 1e-6) if which == "acceptance" else (1e-6, 1e-3)
    c1, c2 = union_corners(g1, tol, angle_tol), union_corners(g2, tol, angle_tol)
    assert len(c1) == len(c2) >= 3
    for c in c1:
        assert min(float(np.max(np.abs(c - d))) for d in c2) <= tol, c
