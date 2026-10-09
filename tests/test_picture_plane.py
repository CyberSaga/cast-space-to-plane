"""M10 core: the ``picture_plane`` camera form (spec-v0.2 §4.1, §4.3; appendix A.2–A.5).

* equivalence: a ``picture_plane`` camera draws the same picture as the hand-written ``target`` camera
  (every number of the full geometry document within 1e-9; image coordinates in canvas mm);
* translation invariance: the same eye and direction with another plane offset draws the same picture,
  only ``distance`` / ``foot`` / ``offset`` / ``frame_m`` / ``equation`` change;
* input errors carry the exact JSON field path;
* the form never emits ``CAMERA_LOOKING_ALONG_UP`` (a horizontal plane looks straight down);
* ``unproject_to_plane`` round trip (< 1e-9 mm) and the plane-equation strings;
* ``camera.picture_plane`` appears in the document for this form only.
"""

import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

import castplane
from castplane.camera import camera_forward, camera_matrix, divide, project
from castplane.cli import EXIT_OK, main
from castplane.errors import SceneError
from castplane.io import load_expanded_scene
from castplane.output.geometry_json import dumps
from castplane.picture_plane import plane_equation, resolve_picture_plane, unproject_to_plane
from castplane.scene import validate_camera, validate_scene

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "tests" / "fixtures" / "v8_candidates"
CANDIDATE_NAMES = ("camera_picture_plane_vertical", "camera_picture_plane_tilted", "camera_picture_plane_horizontal")
EXAMPLES = ("basic", "construction_demo", "curved_demo", "directional", "three_point", "two_lights", "mesh_demo",
            "wall_and_ground")
DOC_KEYS = {"normal", "offset", "up", "distance", "foot", "frame_m", "equation"}
COMMON = dict(deadline=None, derandomize=True, suppress_health_check=[HealthCheck.too_slow])
TOL_MM = 1e-9


def load_candidate(name):
    with open(CANDIDATES / f"{name}.json", encoding="utf-8") as fh:
        return json.load(fh)


def lens(cam):
    """The lens keys of a camera block (everything except the pose)."""
    return {k: copy.deepcopy(cam[k]) for k in ("focal_length_mm", "frame_mm", "shift_mm", "near_m") if k in cam}


def unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


def expected_rows(position, normal, offset, up=None):
    """Independent derivation of the camera rows (right', up', forward) of a picture_plane camera: forward points from
    the eye to the plane, up' is ``up`` (or world z, +y when the plane is horizontal) projected onto the plane,
    right' = forward x up'.  No roll angle is involved."""
    n = unit(normal)
    off = float(offset) / float(np.linalg.norm(np.asarray(normal, dtype=np.float64)))
    E = np.asarray(position, dtype=np.float64)
    s = float(n @ E) + off
    f = -np.sign(s) * n
    if up is None:
        up = [0.0, 0.0, 1.0] if np.linalg.norm(np.cross(f, [0.0, 0.0, 1.0])) > 1e-9 else [0.0, 1.0, 0.0]
    u = np.asarray(up, dtype=np.float64)
    u = unit(u - (u @ f) * f)
    return np.stack([np.cross(f, u), u, f]), abs(s), f


def hand_target_camera(cam):
    """The hand-written ``target`` camera of a picture_plane block: target on the far side of the plane along the
    independently derived forward, ``roll_deg`` from the angle between the derived up' and the default up."""
    pp = cam["picture_plane"]
    rows, D, f = expected_rows(cam["position"], pp["normal"], pp["offset"], pp.get("up"))
    E = np.asarray(cam["position"], dtype=np.float64)
    target = E + 3.0 * D * f
    world_up = [0.0, 0.0, 1.0] if np.linalg.norm(np.cross(f, [0.0, 0.0, 1.0])) > 1e-9 else [0.0, 1.0, 0.0]
    r0 = unit(np.cross(f, world_up))
    u0 = np.cross(r0, f)
    # camera_matrix: up_r = -sin(rho) r0 + cos(rho) u0
    rho = math.degrees(math.atan2(-float(rows[1] @ r0), float(rows[1] @ u0)))
    out = {"position": list(cam["position"]), "target": [float(v) for v in target], "roll_deg": rho}
    out.update(lens(cam))
    return out


def compare_docs(a, b, path=""):
    """Every numeric leaf within 1e-9 (absolute; relative above 1), identical structure and strings.
    ``camera.picture_plane`` (present in ``a`` only) and the warnings' messages are skipped by the callers."""
    if isinstance(a, dict):
        assert isinstance(b, dict) and set(a) == set(b), f"{path}: keys {sorted(set(a) ^ set(b))}"
        for k in a:
            compare_docs(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), f"{path}: length {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            compare_docs(x, y, f"{path}[{i}]")
    elif isinstance(a, bool) or a is None or isinstance(a, str):
        assert a == b, f"{path}: {a!r} vs {b!r}"
    else:
        assert isinstance(b, (int, float)) and not isinstance(b, bool), f"{path}: {a!r} vs {b!r}"
        assert abs(a - b) <= TOL_MM * max(1.0, abs(a), abs(b)), f"{path}: {a!r} vs {b!r}"


def assert_same_picture(doc_pp, doc_t, ignore_codes=()):
    """Equivalence of two documents of the same scene: ``camera.picture_plane`` aside, everything within 1e-9; image
    coordinates (canvas mm, below 1e3 in every scene used here) therefore within 1e-9 mm."""
    a, b = copy.deepcopy(doc_pp), copy.deepcopy(doc_t)
    assert set(a["camera"]["picture_plane"]) == DOC_KEYS
    del a["camera"]["picture_plane"]
    for d in (a, b):
        d["warnings"] = sorted((w["code"], tuple(w["ids"])) for w in d["warnings"] if w["code"] not in ignore_codes)
    compare_docs(a, b)


def pp_from_camera(cam, D=3.0, flip=False):
    """A picture_plane block with the eye, forward and final up of a validated target / yaw-pitch camera: the plane
    ``forward·X = forward·E + D`` (normal +forward, or -forward with the offset negated when ``flip``)."""
    rec = camera_matrix(cam, [36.0, 24.0])
    f = rec["forward"]
    E = np.asarray(cam["position"], dtype=np.float64)
    n, off = f, -(float(f @ E) + D)
    if flip:
        n, off = -n, -off
    out = {"position": list(cam["position"]),
           "picture_plane": {"normal": [float(v) for v in n], "offset": off, "up": [float(v) for v in rec["R"][1]]}}
    out.update(lens(cam))
    return out


# ---------------------------------------------------------------------------------------------------- equivalence

@pytest.mark.parametrize("name", CANDIDATE_NAMES)
def test_candidate_equals_hand_written_target_camera(name):
    scene = castplane.load_scene(load_candidate(name))
    doc_pp = castplane.render(scene)["geometry"]
    doc_t = castplane.render(scene, camera=hand_target_camera(scene["camera"]))["geometry"]
    # the hand-written camera of the horizontal case looks along world up and warns; the picture_plane form does not
    assert_same_picture(doc_pp, doc_t, ignore_codes=("CAMERA_LOOKING_ALONG_UP",))
    assert "CAMERA_LOOKING_ALONG_UP" not in {w["code"] for w in doc_pp["warnings"]}


@pytest.mark.parametrize("name", EXAMPLES)
@pytest.mark.parametrize("flip", [False, True])
def test_examples_equal_their_picture_plane_twin(name, flip):
    scene, _notes = load_expanded_scene(str(ROOT / "examples" / f"{name}.json"))
    doc_t = castplane.render(scene)["geometry"]
    doc_pp = castplane.render(scene, camera=pp_from_camera(scene["camera"], flip=flip))["geometry"]
    assert_same_picture(doc_pp, doc_t)
    pp = doc_pp["camera"]["picture_plane"]
    assert abs(pp["distance"] - 3.0) < 1e-12
    np.testing.assert_allclose(pp["normal"], doc_t["camera"]["P"][2][:3] / np.linalg.norm(doc_t["camera"]["P"][2][:3]),
                               atol=1e-12)


def test_horizontal_candidate_looks_straight_down_without_warning():
    scene = castplane.load_scene(load_candidate("camera_picture_plane_horizontal"))
    rec = camera_matrix(scene["camera"], scene["output"]["canvas_mm"])
    assert rec["warnings"] == []
    np.testing.assert_array_equal(rec["forward"], [0.0, 0.0, -1.0])
    np.testing.assert_allclose(rec["R"][1], [0.0, 1.0, 0.0], atol=0)          # +y fallback, exactly
    doc = castplane.render(scene)["geometry"]
    assert doc["horizon"]["segment"] is None and doc["horizon"]["v_mm"] is None
    assert doc["camera"]["picture_plane"]["equation"] == "z = 3.00"
    # the target form of the same pose keeps its warning
    t = {"position": [0.2, 5.0, 7.0], "target": [0.2, 5.0, 6.0], "focal_length_mm": 24, "frame_mm": [36, 24]}
    assert [w["code"] for w in camera_matrix(validate_camera(t), [36, 24])["warnings"]] == ["CAMERA_LOOKING_ALONG_UP"]


@pytest.mark.parametrize("normal", [[0, 0, 1], [0, 0, -1], [0, 0, 2.5]])
@pytest.mark.parametrize("above", [True, False])
def test_horizontal_planes_never_warn(normal, above):
    E = [1.0, 2.0, 5.0 if above else -1.0]
    cam = validate_camera({"position": E, "picture_plane": {"normal": normal, "offset": -2.0 * normal[2]},
                           "focal_length_mm": 20, "frame_mm": [36, 24]})
    rec = camera_matrix(cam, [36, 24])
    assert rec["warnings"] == []
    np.testing.assert_array_equal(rec["forward"], [0.0, 0.0, -1.0 if above else 1.0])
    assert rec["picture_plane"]["equation"] == "z = 2.00"
    assert rec["picture_plane"]["distance"] == 3.0


def test_resolve_returns_the_target_form():
    cam = validate_camera({"position": [0.37, -2.0, 0.9], "picture_plane": {"normal": [0, 1, 0], "offset": -2.0},
                           "focal_length_mm": 20, "frame_mm": [36, 24], "near_m": 0.05})
    tcam, roll, info = resolve_picture_plane(cam)
    assert "picture_plane" not in tcam and tcam["target"] == [0.37, -1.0, 0.9] and roll == 0.0
    assert {k: tcam[k] for k in ("position", "focal_length_mm", "frame_mm", "shift_mm", "near_m")} == {
        "position": [0.37, -2.0, 0.9], "focal_length_mm": 20.0, "frame_mm": [36.0, 24.0], "shift_mm": [0.0, 0.0],
        "near_m": 0.05}
    assert info == {"normal": [0.0, 1.0, 0.0], "offset": -2.0, "distance": 4.0, "foot": [0.37, 2.0, 0.9]}
    np.testing.assert_array_equal(camera_forward(cam), [0.0, 1.0, 0.0])
    rec = camera_matrix(cam, [36, 24])
    assert rec["picture_plane"] == {"normal": [0.0, 1.0, 0.0], "offset": -2.0, "up": [0.0, 0.0, 1.0],
                                    "distance": 4.0, "foot": [0.37, 2.0, 0.9], "frame_m": [7.2, 4.8],
                                    "equation": "y = 2.00"}


def test_normal_sign_and_scale_do_not_matter():
    base = {"position": [0.5, -1.0, 2.0], "focal_length_mm": 28, "frame_mm": [36, 24]}
    recs = []
    for n, off in (([1, 2, -0.5], 3.0), ([-1, -2, 0.5], -3.0), ([10, 20, -5], 30.0)):
        cam = validate_camera(dict(base, picture_plane={"normal": n, "offset": off, "up": [0.2, 0.0, 1.0]}))
        recs.append(camera_matrix(cam, [36, 24]))
    for r in recs[1:]:
        np.testing.assert_allclose(r["P"], recs[0]["P"], rtol=0, atol=1e-12)
        assert r["picture_plane"]["equation"] == recs[0]["picture_plane"]["equation"]
        assert abs(r["picture_plane"]["distance"] - recs[0]["picture_plane"]["distance"]) < 1e-12


def test_translation_invariance_only_plane_keys_change():
    scene = castplane.load_scene(load_candidate("camera_picture_plane_tilted"))
    cam = copy.deepcopy(load_candidate("camera_picture_plane_tilted")["camera"])
    docs = []
    for off in (1.4, 3.0, 9.5, -0.5):     # all with the plane in front of the eye along the same f
        c = copy.deepcopy(cam)
        c["picture_plane"]["offset"] = off
        docs.append(castplane.render(scene, camera=c)["geometry"])
    ref = docs[0]
    for d in docs[1:]:
        a, b = copy.deepcopy(d), copy.deepcopy(ref)
        pa, pb = a["camera"].pop("picture_plane"), b["camera"].pop("picture_plane")
        assert dumps(a) == dumps(b)                       # identical picture, bit for bit
        assert pa["normal"] == pb["normal"] and pa["up"] == pb["up"]
        for k in ("distance", "foot", "offset", "frame_m", "equation"):
            assert pa[k] != pb[k], k
        ratio = pa["distance"] / pb["distance"]
        np.testing.assert_allclose(np.asarray(pa["frame_m"]) / np.asarray(pb["frame_m"]), [ratio, ratio], rtol=1e-12)


# ---------------------------------------------------------------------------------------------------- input errors

def scene_with_camera(camera):
    s = load_candidate("camera_picture_plane_vertical")
    s["camera"] = camera
    return s


def pp_cam(**pp):
    block = {"normal": [0, 1, 0], "offset": -2.0}
    block.update(pp)
    return {"position": [0.0, -2.0, 1.0], "picture_plane": block, "focal_length_mm": 20, "frame_mm": [36, 24]}


@pytest.mark.parametrize("mutate, field", [
    (lambda c: c["picture_plane"].update(offset=2.0), "camera.picture_plane.offset"),            # plane through E
    (lambda c: c["picture_plane"].update(offset=2.0 + 5e-10), "camera.picture_plane.offset"),
    (lambda c: c["picture_plane"].update(normal=[0, 4, 0], offset=8.0), "camera.picture_plane.offset"),
    (lambda c: c["picture_plane"].update(up=[0, 1, 0]), "camera.picture_plane.up"),             # up parallel to n
    (lambda c: c["picture_plane"].update(up=[0, -3, 1e-10]), "camera.picture_plane.up"),
    (lambda c: c["picture_plane"].update(up=[0, 0, 0]), "camera.picture_plane.up"),
    (lambda c: c["picture_plane"].update(up=[0, 1]), "camera.picture_plane.up"),
    (lambda c: c["picture_plane"].update(up=[0, float("inf"), 1]), "camera.picture_plane.up[1]"),
    (lambda c: c["picture_plane"].update(normal=[0, 0, 0]), "camera.picture_plane.normal"),      # zero normal
    (lambda c: c["picture_plane"].update(normal=[0, 1e-13, 0]), "camera.picture_plane.normal"),
    (lambda c: c["picture_plane"].update(normal=[0, float("nan"), 0]), "camera.picture_plane.normal[1]"),
    (lambda c: c["picture_plane"].update(normal="y"), "camera.picture_plane.normal"),
    (lambda c: c["picture_plane"].update(offset="2"), "camera.picture_plane.offset"),
    (lambda c: c["picture_plane"].update(offset=float("inf")), "camera.picture_plane.offset"),
    (lambda c: c["picture_plane"].pop("normal"), "camera.picture_plane.normal"),
    (lambda c: c["picture_plane"].pop("offset"), "camera.picture_plane.offset"),
    (lambda c: c.update(picture_plane=[0, 1, 0, -2]), "camera.picture_plane"),
    (lambda c: c.update(target=[0, 5, 1]), "camera"),                                           # with target
    (lambda c: c.update(yaw_deg=0.0, pitch_deg=0.0), "camera"),                                 # with yaw/pitch
    (lambda c: c.update(yaw_deg=0.0), "camera"),
    (lambda c: c.update(pitch_deg=0.0), "camera"),
    (lambda c: c.update(roll_deg=10.0), "camera.roll_deg"),                                     # roll is in up
    (lambda c: c.update(roll_deg=0), "camera.roll_deg"),
    (lambda c: c.pop("position"), "camera.position"),
])
def test_input_errors_name_the_field(mutate, field):
    cam = pp_cam()
    mutate(cam)
    with pytest.raises(SceneError) as exc:
        validate_scene(scene_with_camera(cam))
    assert exc.value.field == field, str(exc.value)
    scene = castplane.load_scene(load_candidate("camera_picture_plane_vertical"))
    with pytest.raises(SceneError) as exc:                  # the same rule for a camera override (stage B)
        castplane.render(scene, camera=cam)
    assert exc.value.field == field


def test_error_messages():
    with pytest.raises(SceneError, match="exactly one of target, yaw_deg \\+ pitch_deg or picture_plane"):
        validate_camera(dict(pp_cam(), target=[0, 5, 1]))
    with pytest.raises(SceneError, match="needs target, yaw_deg \\+ pitch_deg or picture_plane"):
        validate_camera({"position": [0, 0, 1], "focal_length_mm": 20, "frame_mm": [36, 24]})
    with pytest.raises(SceneError, match="roll is carried by picture_plane.up"):
        validate_camera(dict(pp_cam(), roll_deg=5))
    with pytest.raises(SceneError, match="passes through camera.position"):
        validate_camera(pp_cam(offset=2.0))
    with pytest.raises(SceneError, match="parallel to picture_plane.normal"):
        validate_camera(pp_cam(up=[0, 2, 0]))
    with pytest.raises(SceneError, match="nonzero"):
        validate_camera(pp_cam(normal=[0, 0, 0]))
    # the existing target / yaw-pitch message is unchanged
    with pytest.raises(SceneError, match="give either target or yaw_deg \\+ pitch_deg, not both"):
        validate_camera({"position": [0, 0, 1], "target": [0, 1, 1], "yaw_deg": 0, "pitch_deg": 0,
                         "focal_length_mm": 20, "frame_mm": [36, 24]})


def test_plane_just_off_the_eye_is_accepted():
    cam = validate_camera(pp_cam(offset=2.0 + 2e-9))
    assert cam["picture_plane"]["offset"] == 2.0 + 2e-9
    rec = camera_matrix(cam, [36, 24])
    np.testing.assert_array_equal(rec["forward"], [0.0, -1.0, 0.0])        # s > 0: f = -n
    assert rec["warnings"] == []


def test_validated_block_is_normalised_and_revalidates():
    cam = validate_camera({"position": [1, 2, 3], "picture_plane": {"normal": [0, 3, 4], "offset": 10, "up": [0, 0, 2]},
                           "focal_length_mm": 20, "frame_mm": [36, 24]})
    assert cam["picture_plane"] == {"normal": [0.0, 0.6, 0.8], "offset": 2.0, "up": [0.0, 0.0, 2.0]}
    assert "roll_deg" not in cam and "target" not in cam and "yaw_deg" not in cam
    assert validate_camera(copy.deepcopy(cam)) == cam
    no_up = validate_camera({"position": [1, 2, 3], "picture_plane": {"normal": [0, 1, 0], "offset": 1},
                             "focal_length_mm": 20, "frame_mm": [36, 24]})
    assert "up" not in no_up["picture_plane"]


# ---------------------------------------------------------------------------------------------------- document

def test_document_keys_only_for_the_picture_plane_form():
    for name in ("basic", "directional"):
        scene, _ = load_expanded_scene(str(ROOT / "examples" / f"{name}.json"))
        doc = castplane.render(scene)["geometry"]
        assert set(doc["camera"]) == {"P", "C", "horizon_line", "principal_point"}
    scene = castplane.load_scene(load_candidate("camera_picture_plane_tilted"))
    doc = castplane.render(scene)["geometry"]
    assert set(doc["camera"]) == {"P", "C", "horizon_line", "principal_point", "picture_plane"}
    pp = doc["camera"]["picture_plane"]
    assert set(pp) == DOC_KEYS
    f, u, Q = (np.asarray(pp[k]) for k in ("normal", "up", "foot"))
    C = np.asarray(doc["camera"]["C"])
    assert abs(np.linalg.norm(f) - 1) < 1e-15 and abs(np.linalg.norm(u) - 1) < 1e-15 and abs(f @ u) < 1e-15
    np.testing.assert_allclose(C + pp["distance"] * f, Q, atol=1e-12)        # Q = E + D f
    assert abs(f @ Q + pp["offset"]) < 1e-12                                   # Q on the plane f·X + offset = 0
    assert f @ C + pp["offset"] < 0                                            # the eye on the negative side
    np.testing.assert_allclose(pp["frame_m"], [36 * pp["distance"] / 28, 24 * pp["distance"] / 28], rtol=1e-15)
    assert pp["equation"] == "0.322x + 0.919y - 0.230z = 1.286"
    # up is the frame up: the given up projected onto the plane
    rows, D, _ = expected_rows([-2.9, -1.2, 3.0], [-0.35, -1.0, 0.25], 1.4, [0.15, 0.0, 1.0])
    np.testing.assert_allclose(u, rows[1], atol=1e-15)
    assert abs(D - pp["distance"]) < 1e-15
    # the document is JSON-native, canonical and deterministic
    text = dumps(doc)
    assert text == dumps(castplane.render(castplane.load_scene(load_candidate("camera_picture_plane_tilted")))["geometry"])
    assert "-0.0" not in json.dumps(pp)


@pytest.mark.parametrize("name", CANDIDATE_NAMES)
def test_candidates_render_deterministically(name):
    a = castplane.render(castplane.load_scene(load_candidate(name)))
    b = castplane.render(castplane.load_scene(load_candidate(name)))
    assert dumps(a["geometry"]) == dumps(b["geometry"]) and a["svg"] == b["svg"]


def test_candidate_documents():
    want = {
        "camera_picture_plane_vertical": ("y = 2.00", 4.0, [7.2, 4.8]),
        "camera_picture_plane_horizontal": ("z = 3.00", 4.0, [6.0, 4.0]),
    }
    for name, (eq, D, frame) in want.items():
        doc = castplane.render(castplane.load_scene(load_candidate(name)))["geometry"]
        pp = doc["camera"]["picture_plane"]
        assert pp["equation"] == eq and pp["distance"] == D
        np.testing.assert_allclose(pp["frame_m"], frame, rtol=1e-15)
        assert doc["warnings"] == [] or "CAMERA_LOOKING_ALONG_UP" not in {w["code"] for w in doc["warnings"]}


# ---------------------------------------------------------------------------------------------------- plane equation

S2 = math.sqrt(0.5)


@pytest.mark.parametrize("normal, offset, text", [
    ([0, 1, 0], -2.0, "y = 2.00"),
    ([0, -1, 0], 2.0, "y = 2.00"),
    ([0, -2, 0], 4.0, "y = 2.00"),
    ([1, 0, 0], 1.0, "x = -1.00"),
    ([-1, 0, 0], 1.0, "x = 1.00"),
    ([0, 0, -1], 3.0, "z = 3.00"),
    ([0, 0, 1], -3.0, "z = 3.00"),
    ([0, 0, 1], 0.0, "z = 0.00"),
    ([0, 0, -1], 0.0, "z = 0.00"),            # -0.0 constant
    ([0, 0, 1], 0.001, "z = 0.00"),           # -0.001 rounds to -0.00 -> 0.00
    ([0, 0, -1], -0.004, "z = 0.00"),
    ([0, 0, 1], -0.006, "z = 0.01"),
    ([1, 0, 0], -1.005, "x = 1.00"),          # 1.005 is 1.00499999... in binary: Python's exact rounding
    ([S2, S2, 0], -1.2, "0.707x + 0.707y = 1.200"),
    ([-S2, -S2, 0], 1.2, "0.707x + 0.707y = 1.200"),       # first nonzero coefficient made positive
    ([1, 1, 0], -1.2 * math.sqrt(2), "0.707x + 0.707y = 1.200"),   # unnormalised
    ([S2, S2, 0], 1.2, "0.707x + 0.707y = -1.200"),
    ([S2, -S2, 0], 0.0, "0.707x - 0.707y = 0.000"),
    ([-S2, S2, 0], 0.0, "0.707x - 0.707y = 0.000"),         # flipped: the constant -0.0 prints as 0.000
    ([S2, -S2, 0], 1e-4, "0.707x - 0.707y = 0.000"),        # -0.0001 -> -0.000 -> 0.000
    ([0, -0.6, 0.8], 2.0, "0.600y - 0.800z = 2.000"),
    ([1e-4, 0.6, -0.8], 0.0, "0.600y - 0.800z = 0.000"),    # |x| < 5e-4 dropped, x is the first nonzero (> 0)
    ([-1e-4, 0.6, -0.8], 0.0, "-0.600y + 0.800z = 0.000"),  # x first nonzero and negative: all flipped
    ([1e-10, -0.6, 0.8], 0.0, "0.600y - 0.800z = 0.000"),   # |x| <= 1e-9 is not "nonzero": y is flipped
    ([0.3, 0.4, -math.sqrt(0.75)], -5.0, "0.300x + 0.400y - 0.866z = 5.000"),
    ([0.0, 1.0, 1e-4], -2.0, "1.000y = 2.000"),             # not an axis (|n_y| - 1 > 1e-9), x and z dropped
])
def test_plane_equation(normal, offset, text):
    assert plane_equation(normal, offset) == text


# ---------------------------------------------------------------------------------------------------- unproject

def test_unproject_principal_point_is_the_foot_and_corners_span_frame_m():
    scene = castplane.load_scene(load_candidate("camera_picture_plane_tilted"))
    rec = camera_matrix(scene["camera"], scene["output"]["canvas_mm"])
    pp = rec["picture_plane"]
    D = pp["distance"]
    Q = unproject_to_plane(rec, [rec["u0"], rec["v0"]], D)
    assert Q.shape == (3,)
    np.testing.assert_allclose(Q, pp["foot"], atol=1e-14)
    W, H = rec["canvas_mm"]
    corners = unproject_to_plane(rec, [[-W / 2, -H / 2], [W / 2, -H / 2], [W / 2, H / 2]], D)
    assert corners.shape == (3, 3)
    np.testing.assert_allclose(np.linalg.norm(corners[1] - corners[0]), pp["frame_m"][0], rtol=1e-14)
    np.testing.assert_allclose(np.linalg.norm(corners[2] - corners[1]), pp["frame_m"][1], rtol=1e-14)
    np.testing.assert_allclose((corners[1] - corners[0]) / pp["frame_m"][0], rec["R"][0], atol=1e-14)
    np.testing.assert_allclose((corners[2] - corners[1]) / pp["frame_m"][1], pp["up"], atol=1e-14)


def test_unproject_round_trip_with_shift():
    cam = validate_camera({"position": [0.3, -4.0, 2.2], "picture_plane": {"normal": [0.2, 1, -0.3], "offset": 1.0,
                                                                           "up": [0.1, 0.2, 1.0]},
                           "focal_length_mm": 50, "frame_mm": [36, 24], "shift_mm": [2.0, -1.5]})
    rec = camera_matrix(cam, [273, 182])
    D = rec["picture_plane"]["distance"]
    rng = np.random.default_rng(7)
    uv = rng.uniform([-180, -120], [180, 120], size=(200, 2))
    X = unproject_to_plane(rec, uv, D)
    back = divide(project(rec, np.concatenate([X, np.ones((len(X), 1))], axis=1)))
    assert np.max(np.abs(back - uv)) < TOL_MM
    f, off = np.asarray(rec["picture_plane"]["normal"]), rec["picture_plane"]["offset"]
    assert np.max(np.abs(X @ f + off)) < 1e-12


# ---------------------------------------------------------------------------------------------------- properties

coord = st.floats(-20.0, 20.0, allow_nan=False)
direction = st.tuples(st.floats(-1.0, 1.0), st.floats(-1.0, 1.0), st.floats(-1.0, 1.0))


@st.composite
def pp_cameras(draw):
    E = [draw(coord), draw(coord), draw(coord)]
    axis = draw(st.sampled_from([None, 0, 1, 2]))
    if axis is None:
        n = list(draw(direction))
        assume(np.linalg.norm(n) > 0.1)
        # keep the default up well-conditioned when no up is given (|f x z| > 1e-3)
        assume(np.linalg.norm(np.cross(unit(n), [0, 0, 1])) > 1e-3)
    else:
        n = [0.0, 0.0, 0.0]
        n[axis] = draw(st.sampled_from([-1.0, 1.0, 2.5]))
    scale = draw(st.sampled_from([1.0, 0.25, 7.0]))
    n = [v * scale for v in n]
    D = draw(st.floats(0.05, 30.0))
    side = draw(st.sampled_from([-1.0, 1.0]))
    nn = float(np.linalg.norm(n))
    offset = (-(unit(n) @ np.asarray(E)) + side * D) * nn
    block = {"normal": n, "offset": float(offset)}
    up = draw(st.one_of(st.none(), direction))
    if up is not None:
        assume(np.linalg.norm(up) > 0.1 and np.linalg.norm(np.cross(unit(up), unit(n))) > 1e-3)
        block["up"] = list(up)
    focal = draw(st.sampled_from([12.0, 20.0, 35.0, 80.0]))
    shift = draw(st.sampled_from([[0.0, 0.0], [3.0, -2.0]]))
    return {"position": E, "picture_plane": block, "focal_length_mm": focal, "frame_mm": [36.0, 24.0],
            "shift_mm": shift}


def scene_points(rec, k=40, seed=0):
    """Points in front of the camera (depth 0.5–40 m, inside a 60° cone)."""
    rng = np.random.default_rng(seed)
    depth = rng.uniform(0.5, 40.0, k)
    lateral = rng.uniform(-0.5, 0.5, (k, 2)) * depth[:, None]
    R, C = rec["R"], rec["C"]
    X = C + depth[:, None] * R[2] + lateral[:, :1] * R[0] + lateral[:, 1:] * R[1]
    return np.concatenate([X, np.ones((k, 1))], axis=1)


@settings(max_examples=200, **COMMON)
@given(pp_cameras())
def test_property_equivalence_with_the_independent_rows(c):
    cam = validate_camera(c)
    rec = camera_matrix(cam, [360.0, 240.0])
    assert rec["warnings"] == []
    rows, D, f = expected_rows(c["position"], c["picture_plane"]["normal"], c["picture_plane"]["offset"],
                               c["picture_plane"].get("up"))
    np.testing.assert_allclose(rec["R"], rows, atol=1e-12)
    assert abs(rec["picture_plane"]["distance"] - D) <= 1e-12 * max(1.0, D)
    # the same picture as the hand-written target camera (forward far along f, roll from the derived up)
    t = camera_matrix(validate_camera(hand_target_camera(c)), [360.0, 240.0])
    X = scene_points(rec)
    a = divide(project(rec, X))
    b = divide(project(t, X))
    assert np.max(np.abs(a - b)) < TOL_MM
    # translation invariance: another plane along the same f, same picture bit for bit
    c2 = copy.deepcopy(c)
    nn = float(np.linalg.norm(c["picture_plane"]["normal"]))
    s = float(unit(c["picture_plane"]["normal"]) @ np.asarray(c["position"])) + c["picture_plane"]["offset"] / nn
    c2["picture_plane"]["offset"] = c["picture_plane"]["offset"] + 0.5 * s * nn     # |s| x 1.5, same side
    rec2 = camera_matrix(validate_camera(c2), [360.0, 240.0])
    np.testing.assert_array_equal(rec2["P"], rec["P"])
    assert rec2["picture_plane"]["normal"] == rec["picture_plane"]["normal"]


@settings(max_examples=200, **COMMON)
@given(pp_cameras(), st.lists(st.tuples(st.floats(-1.0, 1.0), st.floats(-1.0, 1.0)), min_size=1, max_size=8))
def test_property_unproject_round_trip(c, uvs):
    cam = validate_camera(c)
    rec = camera_matrix(cam, [360.0, 240.0])
    pp = rec["picture_plane"]
    uv = np.asarray(uvs) * np.array([270.0, 180.0])        # up to 1.5 canvas half-widths
    X = unproject_to_plane(rec, uv, pp["distance"])
    back = divide(project(rec, np.concatenate([X, np.ones((len(X), 1))], axis=1)))
    assert np.max(np.abs(back - uv)) < TOL_MM
    scale = max(1.0, float(np.max(np.abs(X))))
    assert np.max(np.abs(X @ np.asarray(pp["normal"]) + pp["offset"])) < 1e-12 * scale
    assert pp["equation"] == plane_equation(pp["normal"], pp["offset"])


# ---------------------------------------------------------------------------------------------------- CLI info

def test_info_prints_the_picture_plane(tmp_path, capsys):
    path = CANDIDATES / "camera_picture_plane_vertical.json"
    assert main(["info", str(path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "picture plane: y = 2.00" in out
    assert "eye to picture plane D: 4.0000 m" in out
    assert "frame on the picture plane: 7.2000 x 4.8000 m" in out
    assert main(["info", str(ROOT / "examples" / "basic.json")]) == EXIT_OK
    assert "picture plane:" not in capsys.readouterr().out
    # a picture_plane camera override
    cam = tmp_path / "cam.json"
    cam.write_text(json.dumps({"position": [0, -1, 1.5], "picture_plane": {"normal": [1, 1, 0], "offset": -2.0},
                               "focal_length_mm": 35, "frame_mm": [36, 24]}), encoding="utf-8")
    assert main(["info", str(ROOT / "examples" / "basic.json"), "--camera", str(cam)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "picture plane: 0.707x + 0.707y = 1.414" in out


def test_cli_render_reports_picture_plane_errors(tmp_path, capsys):
    s = load_candidate("camera_picture_plane_vertical")
    s["camera"]["roll_deg"] = 5
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(s), encoding="utf-8")
    assert main(["validate", str(p)]) == 2
    assert "camera.roll_deg" in capsys.readouterr().err
