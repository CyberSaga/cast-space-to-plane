"""Tests for castplane.conics (spec §5.6, §7.2; contract §2.6)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from castplane.conics import (adjugate3, arc_svg_flags, circle_matrix, classify, condition_number,
                              conic_point, ellipse_params, embed_circle, functional_coeffs,
                              ground_conic_map, normalize_conic, sample_arc,
                              sub_arcs_where_nonnegative, transform_conic)
from castplane.light import light_vector
from castplane.shadow import shadow_matrix

GROUND = np.array([0.0, 0.0, 1.0, 0.0])


def rot2(a):
    return np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])


def affine(a, b, alpha, tx, ty):
    H = np.eye(3)
    H[:2, :2] = rot2(alpha) @ np.diag([a, b])
    H[:2, 2] = [tx, ty]
    return H


# --------------------------------------------------------------------------- basics
def test_circle_matrix_and_embedding():
    C = circle_matrix(2.0)
    assert np.allclose(C, np.diag([1, 1, -4]))
    E = embed_circle([1, 2, 3], [1, 0, 0], [0, 1, 0])
    assert E.shape == (4, 3)
    X = E @ np.array([2.0, 0.0, 1.0])
    assert np.allclose(X, [3, 2, 3, 1])
    # points of the circle satisfy x^T C x = 0 and lie on the embedded circle
    for th in np.linspace(0, 2 * math.pi, 7):
        x = np.array([2 * math.cos(th), 2 * math.sin(th), 1.0])
        assert abs(x @ C @ x) < 1e-12
        P = conic_point(E, th, 2.0)
        assert np.linalg.norm(P[:3] - [1, 2, 3]) == pytest.approx(2.0)


def test_adjugate_matches_det_times_inverse():
    rng = np.random.default_rng(1)
    for _ in range(20):
        H = rng.normal(size=(3, 3))
        assert np.allclose(adjugate3(H), np.linalg.det(H) * np.linalg.inv(H))
    singular = np.array([[1, 2, 3], [2, 4, 6], [0, 1, 1]], dtype=float)
    assert np.allclose(adjugate3(singular) @ singular, 0)


def test_transform_conic_preserves_incidence():
    rng = np.random.default_rng(2)
    C = circle_matrix(1.5)
    for _ in range(10):
        H = rng.normal(size=(3, 3))
        Cp = transform_conic(C, H)
        assert np.allclose(Cp, Cp.T)
        for th in rng.uniform(0, 2 * math.pi, 5):
            y = conic_point(H, th, 1.5)
            assert abs(y @ Cp @ y) < 1e-9 * np.abs(Cp).max() * (y @ y)


def test_normalize_conic_max_entry_is_plus_one():
    C = np.array([[-2.0, 0.5, 0.0], [0.5, 1.0, 0.0], [0.0, 0.0, 1.0]])
    N = normalize_conic(C)
    assert np.abs(N).max() == 1.0
    assert N[0, 0] == 1.0  # the max-|entry| was -2 and is made +1
    assert np.allclose(N, C / -2.0)
    assert np.allclose(normalize_conic(np.zeros((3, 3))), 0)


# --------------------------------------------------------------------------- ellipse via affine map
@pytest.mark.parametrize("a,b,alpha,tx,ty", [(2.0, 1.0, 0.0, 0.0, 0.0), (0.5, 3.0, 0.7, 1.0, -2.0),
                                              (1.0, 1.0, 1.2, 3.0, 4.0), (4.0, 2.5, 2.9, -1.0, 0.5)])
def test_circle_under_affine_map_is_ellipse_with_expected_axes(a, b, alpha, tx, ty):
    rho = 1.3
    H = affine(a, b, alpha, tx, ty)
    Cp = transform_conic(circle_matrix(rho), H)
    assert classify(Cp) == "ellipse"
    centre, (major, minor), rot = ellipse_params(Cp)
    assert np.allclose(centre, [tx, ty])
    assert major == pytest.approx(max(a, b) * rho)
    assert minor == pytest.approx(min(a, b) * rho)
    if abs(a - b) > 1e-9:
        expected = alpha if a > b else alpha + math.pi / 2
        assert (rot - expected) % math.pi == pytest.approx(0.0, abs=1e-9) or \
               (rot - expected) % math.pi == pytest.approx(math.pi, abs=1e-9)
    # the points of the ellipse at the axis ends lie on the conic
    for sgn in (1, -1):
        for ang, s in ((rot, major), (rot + math.pi / 2, minor)):
            p = np.r_[centre + sgn * s * np.array([math.cos(ang), math.sin(ang)]), 1.0]
            assert abs(p @ Cp @ p) < 1e-9 * np.abs(Cp).max() * (p @ p)


def test_ellipse_params_invariant_under_conic_sign():
    H = affine(2.0, 1.0, 0.3, 1.0, 1.0)
    Cp = transform_conic(circle_matrix(1.0), H)
    p1 = ellipse_params(Cp)
    p2 = ellipse_params(-Cp)
    assert np.allclose(p1[0], p2[0]) and p1[1] == pytest.approx(p2[1]) and p1[2] == pytest.approx(p2[2])


# --------------------------------------------------------------------------- §7.2 sphere
@pytest.mark.parametrize("phi_deg", [20.0, 45.0, 70.0])
@pytest.mark.parametrize("azimuth_deg", [0.0, 37.0, 200.0])
def test_sphere_shadow_ellipse_closed_form(phi_deg, azimuth_deg):
    """Spec §7.2: sphere centre (0,0,r), directional light at elevation phi -> ground shadow
    ellipse with semi-minor r, semi-major r / sin phi, centre offset r / tan phi opposite
    to the light."""
    r = 0.8
    phi = math.radians(phi_deg)
    az = math.radians(azimuth_deg)
    l = np.array([math.cos(phi) * math.cos(az), math.cos(phi) * math.sin(az), math.sin(phi)])
    L = light_vector({"type": "directional", "direction": l.tolist()})
    # contract §2.6 sphere: directional light -> great circle through c with normal l
    n = l / np.linalg.norm(l)
    e1 = np.cross(n, [0, 0, 1.0])
    e1 = e1 / np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    c = np.array([0.0, 0.0, r])
    E = embed_circle(c, e1, e2)
    M = shadow_matrix(GROUND, L)
    H = ground_conic_map(M, E)
    Cp = transform_conic(circle_matrix(r), H)
    assert classify(Cp) == "ellipse"
    centre, (major, minor), rot = ellipse_params(Cp)
    assert minor == pytest.approx(r)
    assert major == pytest.approx(r / math.sin(phi))
    offset = r / math.tan(phi)
    expected_centre = -offset * np.array([math.cos(az), math.sin(az)])
    assert np.allclose(centre, expected_centre)
    assert math.cos(rot - az) ** 2 == pytest.approx(1.0)  # major axis along the light azimuth
    # cross-check against direct shadow points of the silhouette circle
    for th in np.linspace(0, 2 * math.pi, 9):
        S = conic_point(M @ E, th, r)
        p = np.array([S[0] / S[3], S[1] / S[3], 1.0])
        assert abs(p @ Cp @ p) < 1e-9 * np.abs(Cp).max() * (p @ p)


# --------------------------------------------------------------------------- classification
def test_parabola_hyperbola_degenerate_classification():
    C = circle_matrix(1.0)

    def H_for(c):  # w' = y + c : the line y = -c is sent to infinity
        return np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 1.0, c]])

    assert classify(transform_conic(C, H_for(2.0))) == "ellipse"
    assert classify(transform_conic(C, H_for(1.0))) == "parabola"
    assert classify(transform_conic(C, H_for(0.5))) == "hyperbola"
    singular = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 0, 0]])
    Cd = transform_conic(C, singular)  # must not raise
    assert np.all(np.isfinite(Cd))
    assert classify(Cd) == "degenerate"
    assert ellipse_params(Cd) is None
    assert ellipse_params(transform_conic(C, H_for(0.5))) is None
    assert condition_number(Cd) == math.inf
    assert condition_number(transform_conic(C, H_for(2.0))) < 1e8


# --------------------------------------------------------------------------- sampling
def test_sample_arc_endpoints_and_count():
    H = affine(2.0, 1.0, 0.0, 0.0, 0.0)
    pts = sample_arc(H, 1.0, 0.0, math.pi / 2, 8)
    assert pts.shape == (9, 3)
    assert np.allclose(pts[0], [2, 0, 1])
    assert np.allclose(pts[-1], [0, 1, 1])
    four = conic_point(H, np.array([0.0, math.pi]), 1.0)
    assert four.shape == (2, 3)


def test_functional_coeffs_match_direct_evaluation():
    rng = np.random.default_rng(5)
    E = embed_circle([1, 2, 0.5], [1, 0, 0], [0, 1, 0])
    f = rng.normal(size=4)
    A, B, C = functional_coeffs(f, E, 0.7)
    for th in rng.uniform(0, 2 * math.pi, 10):
        assert f @ conic_point(E, th, 0.7) == pytest.approx(A * math.cos(th) + B * math.sin(th) + C)


# --------------------------------------------------------------------------- sub-arcs
def _brute(A, B, C, th0, th1, n=20001):
    th = np.linspace(th0, th1, n)
    return th, (A * np.cos(th) + B * np.sin(th) + C) >= 0


def _member(intervals, th):
    # a seam-merged interval [a, b] with b > theta1 covers th via th + 2 pi
    return any(a - 1e-9 <= t <= b + 1e-9 for a, b in intervals for t in (th, th + 2 * math.pi))


@pytest.mark.parametrize("seed", range(40))
def test_sub_arcs_against_brute_force(seed):
    rng = np.random.default_rng(seed)
    A, B = rng.normal(size=2)
    C = rng.normal() * 1.5
    full_turn = seed % 2 == 0
    th0 = rng.uniform(-2 * math.pi, 2 * math.pi) if not full_turn else 0.0
    th1 = th0 + (rng.uniform(0.1, 2 * math.pi) if not full_turn else 2 * math.pi)
    intervals = sub_arcs_where_nonnegative(A, B, C, th0, th1)
    for a, b in intervals:
        assert th0 <= a < b
        assert b <= th1 + (2 * math.pi if full_turn else 0.0) and b - a <= 2 * math.pi
    if full_turn:
        assert len(intervals) <= 1  # one sinusoid: one region per turn, never split at the seam
    for (a, b), (c, d) in zip(intervals, intervals[1:]):
        assert b < c
    th, ok = _brute(A, B, C, th0, th1)
    for t, o in zip(th, ok):
        val = A * math.cos(t) + B * math.sin(t) + C
        if abs(val) < 1e-6:
            continue  # exactly on a boundary: either answer is acceptable
        assert _member(intervals, t) == bool(o), (A, B, C, t)


def test_sub_arcs_special_cases():
    assert sub_arcs_where_nonnegative(0, 0, 1) == [[0.0, 2 * math.pi]]
    assert sub_arcs_where_nonnegative(0, 0, -1) == []
    assert sub_arcs_where_nonnegative(1, 0, 2) == [[0.0, 2 * math.pi]]
    assert sub_arcs_where_nonnegative(1, 0, -2) == []
    # cos theta >= 0 on the full turn straddles the seam: ONE interval [3pi/2, 5pi/2]
    iv = sub_arcs_where_nonnegative(1, 0, 0)
    assert len(iv) == 1
    assert iv[0] == pytest.approx([3 * math.pi / 2, 5 * math.pi / 2])
    # a region that does not straddle the seam stays inside [0, 2 pi]
    iv = sub_arcs_where_nonnegative(-1, 0, 0)
    assert len(iv) == 1 and iv[0] == pytest.approx([math.pi / 2, 3 * math.pi / 2])
    # the band |value| <= tol is DROPPED (contract §2.8, same convention as shadow_loop)
    assert sub_arcs_where_nonnegative(1, 0, -1 - 1e-12, tol=1e-9) == []
    assert sub_arcs_where_nonnegative(1, 0, -1 + 1e-12, tol=1e-9) == []
    assert sub_arcs_where_nonnegative(1, 0, 1 + 1e-6, tol=1e-9) == [[0.0, 2 * math.pi]]
    assert sub_arcs_where_nonnegative(1, 0, 1 + 1e-12, tol=1e-9) != [[0.0, 2 * math.pi]]
    assert sub_arcs_where_nonnegative(0, 0, 5e-10, tol=1e-9) == []
    # an arc range that is not the full circle
    iv = sub_arcs_where_nonnegative(1, 0, 0, -math.pi / 4, math.pi / 4)
    assert len(iv) == 1 and iv[0] == pytest.approx([-math.pi / 4, math.pi / 4])
    # a sub-range of the circle is never seam-merged
    iv = sub_arcs_where_nonnegative(1, 0, 0, 0.0, 1.5 * math.pi)
    assert len(iv) == 1 and iv[0] == pytest.approx([0.0, math.pi / 2])


def test_sub_arcs_endpoints_never_on_the_wrong_side_of_tol():
    """Reviewer case: a tilted cap circle crossing the light height.  Every endpoint of
    the kept arcs must have w_S >= tol, never -tol."""
    s = math.sqrt(0.5)
    E = embed_circle([0, 0, 1], [1, 0, 0], [0, s, s])
    L = light_vector({"type": "point", "position": [5, 5, 1]})
    M = shadow_matrix(GROUND, L)
    tol = 1e-9
    intervals = sub_arcs_where_nonnegative(*functional_coeffs(M[3], E, 1.0), tol=tol)
    assert len(intervals) == 1  # no sliver at the seam where w_S(0) == 0
    for a, b in intervals:
        assert b - a > 1e-9
        for th in (a, b):
            assert conic_point(M @ E, th)[3] >= tol * (1 - 1e-6)
        mid = 0.5 * (a + b)
        assert conic_point(M @ E, mid)[3] > tol


def test_sub_arcs_drops_slivers_and_wrap_interval_is_consistent():
    # tangent from below: the single touching point is not an arc
    assert sub_arcs_where_nonnegative(1, 0, -1) == []
    assert sub_arcs_where_nonnegative(1, 0, -1 + 1e-30) == []
    # the wrap interval covers exactly the points where the function is positive
    iv = sub_arcs_where_nonnegative(1, 0, 0.5)
    assert len(iv) == 1
    a, b = iv[0]
    assert a == pytest.approx(4 * math.pi / 3) and b == pytest.approx(8 * math.pi / 3)
    for th in np.linspace(0, 2 * math.pi, 1001):
        inside = a <= th <= b or a <= th + 2 * math.pi <= b
        val = math.cos(th) + 0.5
        if abs(val) > 1e-6:
            assert inside == (val > 0)


# --------------------------------------------------------------------------- svg flags
@pytest.mark.parametrize("th0,th1", [(0.0, 1.0), (0.0, 4.0), (1.0, 0.2), (1.0, -3.0), (0.3, 0.3 + 2 * math.pi - 1e-3)])
def test_arc_svg_flags_from_midpoint(th0, th1):
    H = affine(2.0, 1.0, 0.4, 1.0, -1.0)
    Cp = transform_conic(circle_matrix(1.0), H)
    centre, axes, rot = ellipse_params(Cp)

    def pt(th):
        p = conic_point(H, th, 1.0)
        return p[:2] / p[2]

    large, sweep = arc_svg_flags(centre, axes, rot, pt(th0), pt(0.5 * (th0 + th1)), pt(th1))
    span = abs(th1 - th0)
    assert large == (1 if span > math.pi else 0)
    assert sweep == (1 if th1 > th0 else 0)  # the map is orientation preserving
