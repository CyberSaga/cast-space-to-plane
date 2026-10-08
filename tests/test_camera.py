"""Camera conventions of contract §2.2 and the §7.2 camera case."""

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from castplane.camera import (camera_matrix, clip_polygon_near, clip_polygon_rect_h, clip_segment_near,
                              divide, horizon, nu, project, vanishing_point)
from castplane.errors import SceneError
from castplane.homogeneous import join, meet, normalize_max
from castplane.scene import validate_camera, validate_output


def cam(position=(0.0, 0.0, 1.5), target=(0.0, 5.0, 1.5), roll=0.0, f=35.0, frame=(36.0, 24.0),
        canvas=None, shift=(0.0, 0.0), near=0.05, **extra):
    d = {"position": list(position), "roll_deg": roll, "focal_length_mm": f, "frame_mm": list(frame),
         "shift_mm": list(shift), "near_m": near}
    if target is not None:
        d["target"] = list(target)
    d.update(extra)
    return camera_matrix(validate_camera(d), list(canvas or frame))


def uv(c, X):
    return divide(project(c, np.asarray(X, float)))


def test_det_R_is_minus_one_and_axes():
    c = cam()
    assert abs(np.linalg.det(c["R"]) + 1.0) < 1e-12
    np.testing.assert_allclose(c["R"], [[1, 0, 0], [0, 0, 1], [0, 1, 0]], atol=1e-12)  # right=+x, up=+z, fwd=+y
    np.testing.assert_allclose(c["t"], [0.0, -1.5, 0.0], atol=1e-12)


def test_hand_computed_projection():
    # camera at (0,0,1.5) looking +y, f=35, s=1: point (1, 5, 2.5) -> depth 5, u = 35*1/5, v = 35*1/5
    c = cam()
    np.testing.assert_allclose(uv(c, [1.0, 5.0, 2.5, 1.0]), [7.0, 7.0], atol=1e-12)
    assert abs(project(c, [1.0, 5.0, 2.5, 1.0])[2] - 5.0) < 1e-12
    # shift moves the principal point; canvas scaling s = 2 doubles everything in canvas mm
    c2 = cam(shift=(2.0, -1.0), canvas=(72.0, 48.0))
    np.testing.assert_allclose(uv(c2, [1.0, 5.0, 2.5, 1.0]), [2 * 7.0 + 4.0, 2 * 7.0 - 2.0], atol=1e-12)
    assert c2["u0"] == 4.0 and c2["v0"] == -2.0


def test_roll_test_vector_contract_2_2():
    c = cam(roll=10.0)
    u, v = uv(c, [0.0, 5.0, 2.5, 1.0])
    assert abs(u - 35.0 * math.sin(math.radians(10)) * 0.2) < 1e-9
    assert abs(u - 1.2155) < 1e-4 and u > 0


def test_yaw_pitch_form_matches_target_form():
    yaw, pitch = 30.0, -20.0
    fwd = np.array([-math.sin(math.radians(yaw)) * math.cos(math.radians(pitch)),
                    math.cos(math.radians(yaw)) * math.cos(math.radians(pitch)),
                    math.sin(math.radians(pitch))])
    c1 = cam(target=None, yaw_deg=yaw, pitch_deg=pitch)
    c2 = cam(target=tuple(np.array([0.0, 0.0, 1.5]) + 3.0 * fwd))
    np.testing.assert_allclose(c1["P"], c2["P"], atol=1e-12)
    np.testing.assert_allclose(c1["forward"], fwd, atol=1e-12)
    # positive yaw turns left: forward points towards -x
    assert c1["forward"][0] < 0


def test_level_camera_vertical_edges_stay_vertical_spec_7_2():
    c = cam(target=(2.0, 5.0, 1.5))  # pitch = 0, yawed
    for base in ([1.0, 4.0, 0.0], [-2.0, 7.0, 0.0], [3.0, 3.0, 0.0]):
        top = base[:2] + [2.0]
        a, b = uv(c, base + [1.0]), uv(c, top + [1.0])
        assert abs(a[0] - b[0]) < 1e-9
    assert vanishing_point(c, [0, 0, 1]) is None


def test_pitched_camera_verticals_converge_to_z_vp_below_horizon_spec_7_2():
    c = cam(position=(1.0, -2.0, 4.0), target=(0.5, 5.0, 0.5))  # looking down
    vpz = vanishing_point(c, [0, 0, 1])
    assert vpz is not None
    hz = horizon(c)
    assert hz["v_mm"] is not None
    assert vpz[1] < hz["v_mm"]  # z vanishing point below the horizon when looking down
    vpz_h = np.array([vpz[0], vpz[1], 1.0])
    for base in ([1.0, 4.0, 0.0], [-2.0, 7.0, 0.0], [3.0, 3.0, 0.0]):
        a = project(c, base + [1.0])
        b = project(c, base[:2] + [2.0, 1.0])
        line = normalize_max(join(a, b))
        assert abs(line @ normalize_max(vpz_h)) < 1e-9  # VPz lies on every projected vertical edge


def test_horizon_level_camera_is_v0():
    c = cam()
    hz = horizon(c)
    assert hz["v_mm"] == 0.0
    np.testing.assert_allclose(hz["vanishing_points"]["y"], [0.0, 0.0], atol=1e-12)
    assert hz["vanishing_points"]["x"] is None and hz["vanishing_points"]["z"] is None
    assert hz["segment"] is not None and hz["segment"][0][1] == 0.0 and hz["segment"][1][1] == 0.0
    c_shift = cam(shift=(0.0, 3.0))
    assert abs(horizon(c_shift)["v_mm"] - 3.0) < 1e-12
    # with yaw 45° both x and y vanishing points are finite and on the horizon
    c45 = cam(target=(5.0, 5.0, 1.5))
    hz = horizon(c45)
    for axis in ("x", "y"):
        vp = hz["vanishing_points"][axis]
        assert vp is not None and abs(vp[1] - hz["v_mm"]) < 1e-9
    assert abs(np.array(hz["line"]) @ np.array(hz["vanishing_points"]["x"] + [1.0])) < 1e-9


def test_aspect_ratio_error():
    camera = validate_camera({"position": [0, 0, 1.5], "target": [0, 5, 1.5], "focal_length_mm": 35,
                              "frame_mm": [36, 24]})
    with pytest.raises(SceneError) as info:
        validate_output({"canvas_mm": [257, 182]}, camera["frame_mm"])
    assert info.value.field == "output.canvas_mm"
    assert validate_output({"canvas_mm": [273, 182]}, camera["frame_mm"])["canvas_mm"] == [273.0, 182.0]


def test_near_functional_and_segment_clipping():
    c = cam()
    A = np.array([0.0, 3.0, 1.5, 1.0])   # depth 3, in front
    B = np.array([0.0, -1.0, 1.5, 1.0])  # depth -1, behind
    assert abs(nu(c, A) - (3.0 - 0.05)) < 1e-12
    assert abs(nu(c, B) - (-1.0 - 0.05)) < 1e-12
    out = clip_segment_near(c, A, B)
    assert out is not None
    A2, B2 = out
    np.testing.assert_allclose(A2, A)
    assert abs(nu(c, B2)) < 1e-12
    assert abs(B2[1] / B2[3] - 0.05) < 1e-12          # crossing lies on the near plane y = 0.05
    assert abs(project(c, B2)[2] / B2[3] - 0.05) < 1e-12
    assert clip_segment_near(c, B, B + np.array([0, -1, 0, 0])) is None
    assert clip_segment_near(c, A, A + np.array([1, 0, 0, 0])) is not None
    # directions: a direction pointing forward is kept, one pointing backward is clipped away
    assert nu(c, [0.0, 1.0, 0.0, 0.0]) > 0 and nu(c, [0.0, -1.0, 0.0, 0.0]) < 0
    poly = clip_polygon_near(c, [[0, 3, 0, 1], [1, 3, 0, 1], [1, -3, 0, 1], [0, -3, 0, 1]])
    assert poly.shape == (4, 4) and np.all(nu(c, poly) >= -1e-12)


def test_rect_clip_with_direction_vertex_has_no_nan_or_inf():
    c = cam()
    rect = c["rect"]
    poly = np.array([[0.0, 0.0, 1.0], [10.0, 0.0, 1.0], [1.0, 1.0, 0.0]])  # last vertex at infinity
    out = clip_polygon_rect_h(poly, rect)
    assert out.shape[0] >= 3
    assert np.all(np.isfinite(out))
    assert np.all(out[:, 2] > 0)
    pts = divide(out)
    assert np.all(np.isfinite(pts))
    assert np.all(pts[:, 0] <= rect[1] + 1e-9) and np.all(pts[:, 1] <= rect[3] + 1e-9)
    # a direction vertex alone is outside any bounded rectangle
    assert clip_polygon_rect_h(np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]]), rect).shape[0] == 0
    # meet/join sanity: the clipped edge towards infinity has the direction (1, 1)
    m = meet(join([0.0, 0.0, 1.0], [1.0, 1.0, 0.0]), [1.0, 0.0, -rect[1]])
    np.testing.assert_allclose(divide(m), [rect[1], rect[1]], atol=1e-9)


def test_camera_looking_along_up_warns_but_works():
    c = cam(position=(0, 0, 5), target=(0, 0, 0))
    assert [w["code"] for w in c["warnings"]] == ["CAMERA_LOOKING_ALONG_UP"]
    assert np.all(np.isfinite(c["P"]))
    hz = horizon(c)
    assert hz["v_mm"] is None and hz["segment"] is None  # horizon is the line at infinity


@settings(max_examples=150, deadline=None)
@given(
    pos=st.tuples(*[st.floats(-50, 50) for _ in range(3)]),
    tgt=st.tuples(*[st.floats(-50, 50) for _ in range(3)]),
    roll=st.floats(-180, 180),
    f=st.floats(1, 500),
    shift=st.tuples(st.floats(-20, 20), st.floats(-20, 20)),
    pitch=st.floats(-90, 90),
    yaw=st.floats(-360, 360),
)
def test_any_camera_parameters_do_not_raise(pos, tgt, roll, f, shift, pitch, yaw):
    base = {"position": list(pos), "roll_deg": roll, "focal_length_mm": f, "frame_mm": [36, 24],
            "shift_mm": list(shift), "near_m": 0.05}
    if np.linalg.norm(np.subtract(tgt, pos)) > 1e-6:
        c = camera_matrix(validate_camera(dict(base, target=list(tgt))), [36, 24])
        assert np.all(np.isfinite(c["P"])) and abs(abs(np.linalg.det(c["R"])) - 1.0) < 1e-9
        horizon(c)
    c = camera_matrix(validate_camera(dict(base, yaw_deg=yaw, pitch_deg=pitch)), [36, 24])
    assert np.all(np.isfinite(c["P"]))
    hz = horizon(c)
    assert all(np.all(np.isfinite(v)) for v in hz["vanishing_points"].values() if v is not None)
    assert hz["v_mm"] is None or math.isfinite(hz["v_mm"])
