"""The six invariants of spec §7.1 (contract §4) on the examples and random polyhedral scenes.

| row | invariant                         | tolerance |
| 1   | construction = direct             | 1e-6 mm   |
| 2   | shadows independent of the camera | 1e-9 m    |
| 3   | point light -> directional light  | 1e-4 m    |
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
from castplane.construction import self_check, special_point_image
from castplane.light import light_vector
from castplane.output.geometry_json import dumps
from castplane.scene import load_scene, validate_camera
from castplane.shadow import foot, shadow_loop, shadow_matrix
from tests.reference import random_scenes

EXAMPLES = pathlib.Path(__file__).resolve().parents[1] / "examples"
EXAMPLE_NAMES = ("basic.json", "directional.json", "three_point.json", "construction_demo.json")
GROUND = np.array([0.0, 0.0, 1.0, 0.0])


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


def all_scenes():
    out = [load_scene(EXAMPLES / name) for name in EXAMPLE_NAMES]
    rolled = copy.deepcopy(out[-1])
    rolled["camera"]["roll_deg"] = 90.0                     # vertical horizon: v_mm is null
    out.append(load_scene(rolled))
    out += [load_scene(polyhedral_scene(seed, 1 + seed % 4)) for seed in range(6)]
    out += [load_scene(polyhedral_scene(100 + seed, 2, "directional")) for seed in range(3)]
    return out


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
    assert set(doc1["points"]) == set(doc2["points"])
    for name, p in doc1["points"].items():
        if "world" in p:
            np.testing.assert_allclose(p["world"], doc2["points"][name]["world"], atol=1e-9)
        else:
            np.testing.assert_allclose(p["direction"], doc2["points"][name]["direction"], atol=1e-9)
    assert [s["loops"] for s in doc1["shadows"]] == [s["loops"] for s in doc2["shadows"]]
    assert [s["unbounded"] for s in doc1["shadows"]] == [s["unbounded"] for s in doc2["shadows"]]
    assert [f["faces"] for f in doc1["form_shadow"]] == [f["faces"] for f in doc2["form_shadow"]]
    assert [e["silhouette"] for e in doc1["edges"]] == [e["silhouette"] for e in doc2["edges"]]


# --------------------------------------------------------------------------- row 3
@pytest.mark.parametrize("seed", [100, 101, 102, 7])
def test_point_light_converges_to_directional_light(seed):
    scene = load_scene(polyhedral_scene(seed, 2, "directional"))
    far = copy.deepcopy(scene)
    d = np.array(scene["lights"][0]["direction"])
    far["lights"][0] = {"id": scene["lights"][0]["id"], "type": "point", "position": (1e6 * d).tolist()}
    doc_d, doc_p = geometry(scene), geometry(far)
    assert not any(w["code"] == "VERTEX_NOT_BELOW_LIGHT" for w in doc_p["warnings"])
    shadow_names = [n for n in doc_d["points"] if ".shadow." in n]
    assert shadow_names and set(shadow_names) <= set(doc_p["points"])
    for name in shadow_names:
        np.testing.assert_allclose(doc_d["points"][name]["world"], doc_p["points"][name]["world"], atol=1e-4)
    assert [s["loops"] for s in doc_d["shadows"]] == [s["loops"] for s in doc_p["shadows"]]


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
