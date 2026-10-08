"""Unit tests of castplane.construction (spec §5.5, §5.7; contract §2.7)."""

from __future__ import annotations

import numpy as np
import pytest

from castplane.camera import camera_matrix, divide, project
from castplane.construction import (clip_segments_uv, coincidence_check, covering_segments, extended_segments,
                                    self_check, special_point_image)
from castplane.light import light_vector
from castplane.scene import validate_camera
from castplane.shadow import foot, shadow_matrix

GROUND = np.array([0.0, 0.0, 1.0, 0.0])


def cam(position=(0.0, 0.0, 1.5), target=(0.0, 5.0, 1.5), f=35.0):
    c = validate_camera({"position": list(position), "target": list(target), "focal_length_mm": f,
                         "frame_mm": [36, 24]})
    return camera_matrix(c, [36, 24])


def test_special_point_image_finite_behind_and_at_infinity():
    c = cam()
    lp = special_point_image(c, [1.0, 5.0, 2.5, 1.0], 1e-9)
    assert lp["point"] == pytest.approx([7.0, 7.0]) and lp["at_infinity"] is None and not lp["behind"]
    lp = special_point_image(c, [1.0, -5.0, 2.5, 1.0], 1e-9)            # behind the camera: anti point
    assert lp["behind"] and lp["point"] == pytest.approx([-7.0, -7.0])
    lp = special_point_image(c, [0.6, 0.0, 0.8, 0.0], 1e-9)              # direction ⊥ forward: at infinity
    assert lp["point"] is None and lp["at_infinity"] == pytest.approx([0.75, 1.0])
    lp = special_point_image(c, [0.0, 0.0, 0.0, 0.0], 1e-9)              # zero vector (foot of a vertical sun)
    assert lp["point"] is None and lp["at_infinity"] is None and lp["undefined"]
    lp = special_point_image(c, [0.0, 1.0, 0.0, 0.0], 1e-9)              # direction along forward: VPy
    assert lp["point"] == pytest.approx([0.0, 0.0])


def test_covering_and_extended_segments():
    A = np.array([0.0, 0.0])
    B = np.array([[1.0, 1.0], [3.0, 3.0], [2.0, 2.0]])
    C = np.array([[2.0, 2.0], [1.0, 1.0], [2.0, 2.0]])
    seg = covering_segments(A, B, C)

    def ends(seg_row):  # the segment as an orientation-free pair of endpoints
        return sorted((round(float(x), 9), round(float(y), 9)) for x, y in seg_row)

    assert ends(seg[0]) == [(0.0, 0.0), (2.0, 2.0)]
    assert ends(seg[1]) == [(0.0, 0.0), (3.0, 3.0)]
    assert ends(seg[2]) == [(0.0, 0.0), (2.0, 2.0)]          # B == C: direction taken from A
    # A in the middle: the segment runs between the two outer points
    seg = covering_segments(np.array([1.5, 1.5]), np.array([[1.0, 1.0]]), np.array([[2.0, 2.0]]))
    assert ends(seg[0]) == [(1.0, 1.0), (2.0, 2.0)]
    ext = extended_segments(np.array([[0.0, 0.0]]), np.array([[10.0, 0.0]]))
    np.testing.assert_allclose(ext[0], [[-2.0, 0.0], [12.0, 0.0]])


def test_clip_segments_uv_clips_to_rect_and_drops_zero_length():
    rect = (-10.0, 10.0, -5.0, 5.0)
    seg = np.array([[[0.0, 0.0], [100.0, 0.0]],        # leaves the rectangle to the right
                    [[1.0, 1.0], [1.0, 1.0]],          # zero length
                    [[-50.0, 20.0], [-40.0, 20.0]],    # entirely outside
                    [[-1.0, -1.0], [1.0, 1.0]]])       # inside
    out, keep = clip_segments_uv(seg, rect)
    assert keep.tolist() == [True, False, False, True]
    np.testing.assert_allclose(out[0], [[0.0, 0.0], [10.0, 0.0]])
    np.testing.assert_allclose(out[3], [[-1.0, -1.0], [1.0, 1.0]])
    out, keep = clip_segments_uv(np.zeros((0, 2, 2)), rect)
    assert out.shape == (0, 2, 2) and keep.shape == (0,)


def _points(c, L, P):
    M = shadow_matrix(GROUND, L)
    S = P @ M.T
    S = S / S[:, 3:4]
    Q = foot(GROUND, P)
    F = foot(GROUND, L)
    return project(c, L), project(c, P), project(c, F), project(c, Q), project(c, S)


def test_self_check_agrees_for_point_and_directional_lights():
    c = cam(position=(1.0, -3.0, 2.0), target=(0.0, 5.0, 0.5))
    P = np.array([[0.3, 4.0, 1.0, 1.0], [-1.0, 6.0, 0.5, 1.0], [2.0, 3.0, 1.5, 1.0]])
    for L in (light_vector({"type": "point", "position": [1.0, 2.0, 4.0]}),
              light_vector({"type": "directional", "direction": [0.6, 0.0, 0.8]})):
        Lp, Pp, Fp, Qp, Sp = _points(c, L, P)
        err, skipped = self_check(Lp, Pp, Fp, Qp, Sp, 1e-9)
        assert not skipped.any()
        assert np.max(err) < 1e-9
        # a wrong S' (shifted by 1 mm in u) is detected
        wrong = Sp + np.array([1.0, 0.0, 0.0]) * Sp[:, 2:3]
        err, skipped = self_check(Lp, Pp, Fp, Qp, wrong, 1e-9)
        assert not skipped.any() and np.min(err) > 0.999 and np.max(err) < 1.001


def test_self_check_skip_rules():
    c = cam()
    L = light_vector({"type": "point", "position": [0.0, 3.0, 3.5]})
    P = np.array([[0.5, 4.0, 1.0, 1.0]])
    Lp, Pp, Fp, Qp, Sp = _points(c, L, P)
    # P' = L' projectively -> zero line -> skipped
    err, skipped = self_check(Lp, Lp[None, :] * 2.0, Fp, Qp, Sp, 1e-9)
    assert skipped.tolist() == [True] and err.tolist() == [0.0]
    # Q' = F' -> skipped
    err, skipped = self_check(Lp, Pp, Fp, Fp[None, :], Sp, 1e-9)
    assert skipped.tolist() == [True]
    # coincident lines (Q' on the line L'P') -> skipped
    err, skipped = self_check(Lp, Pp, Lp, Pp, Sp, 1e-9)
    assert skipped.tolist() == [True]
    # S' at infinity -> skipped
    err, skipped = self_check(Lp, Pp, Fp, Qp, np.array([[1.0, 1.0, 0.0]]), 1e-9)
    assert skipped.tolist() == [True]
    # two distinct parallel lines u = -1 (L'P') and u = -2 (F'Q'): the meet is at infinity -> skipped
    Lp2, Pp2 = np.array([-1.0, 0.0, 1.0]), np.array([[-1.0, -1.0, 1.0]])
    Fp2, Qp2 = np.array([-2.0, 0.0, 1.0]), np.array([[-2.0, -1.0, 1.0]])
    err, skipped = self_check(Lp2, Pp2, Fp2, Qp2, Sp, 1e-9)
    assert skipped.tolist() == [True] and np.all(np.isfinite(err))
    assert self_check(Lp, np.zeros((0, 3)), Fp, np.zeros((0, 3)), np.zeros((0, 3)), 1e-9)[0].shape == (0,)


def test_self_check_matches_hand_intersection():
    c = cam(position=(1.0, -3.0, 2.0), target=(0.0, 5.0, 0.5))
    L = light_vector({"type": "point", "position": [1.0, 2.0, 4.0]})
    P = np.array([[0.3, 4.0, 1.0, 1.0]])
    Lp, Pp, Fp, Qp, Sp = _points(c, L, P)
    meet = np.cross(np.cross(Lp, Pp[0]), np.cross(Fp, Qp[0]))
    np.testing.assert_allclose(divide(meet), divide(Sp[0]), atol=1e-9)


def test_special_point_image_light_at_the_camera_centre_is_undefined_not_a_noise_direction():
    c = cam(position=(1.0, -3.0, 2.0), target=(0.0, 5.0, 0.5))
    x = project(c, np.array([1.0, -3.0, 2.0, 1.0]))
    assert np.max(np.abs(x)) < 1e-9                                      # P·(C, 1) = 0 up to rounding
    lp = special_point_image(c, [1.0, -3.0, 2.0, 1.0], 1e-9)
    assert lp["point"] is None and lp["at_infinity"] is None and lp["undefined"] and not lp["behind"]
    # a light slightly away from the centre is a regular (finite or at-infinity) point
    lp = special_point_image(c, [1.0, -3.0, 2.001, 1.0], 1e-9)
    assert not lp["undefined"] and (lp["point"] is not None or lp["at_infinity"] is not None)


def test_coincidence_check_measures_the_image_distance_and_skips_points_at_infinity():
    S = np.array([[2.0, 4.0, 2.0], [1.0, 1.0, 1.0], [3.0, 3.0, 0.0]])
    R = np.array([[1.0, 2.0, 1.0], [1.5, 1.0, 1.0], [1.0, 1.0, 1.0]])
    err, skipped = coincidence_check(S, R, 1e-9)
    assert skipped.tolist() == [False, False, True]
    np.testing.assert_allclose(err, [0.0, 0.5, 0.0])
    assert coincidence_check(np.zeros((0, 3)), np.zeros((0, 3)), 1e-9)[0].shape == (0,)
