"""Tests for castplane.conics (spec §5.6, §7.2; contract §2.6)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from castplane.conics import (adjugate3, arc_svg_flags, centred_conic, circle_embedding, circle_frame,
                              circle_matrix, circle_point, circle_record, classify, condition_number,
                              conic_entry, conic_point, ellipse_arc_params, ellipse_params,
                              embed_circle, functional_coeffs, ground_conic_map, is_sampled,
                              normalize_conic, sample_arc, sample_count, sub_arcs_where_nonnegative,
                              transform_conic)
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



# --------------------------------------------------------------------------- translation-invariant classification (contract §2.6)
def test_far_small_circle_is_a_healthy_ellipse():
    """Contract §2.6: a 0.3 m circle 50 m from the origin must classify as a healthy ellipse."""
    for dist in (0.0, 50.0, 500.0, 5000.0):
        H = affine(1.0, 1.0, 0.0, dist, 0.3 * dist)
        C = transform_conic(circle_matrix(0.3), H)
        assert classify(C) == "ellipse"
        assert condition_number(C) < 1e8
        assert not is_sampled(C)
        Cc, centre = centred_conic(C)
        assert np.allclose(centre, [dist, 0.3 * dist], atol=1e-6 * max(1.0, dist))
        assert np.allclose(Cc[:2, 2], 0.0, atol=1e-9)        # centred: no linear terms
        assert np.allclose(Cc, np.diag([1.0, 1.0, -0.09]), atol=1e-6)
        params = ellipse_params(C)
        assert params[1][0] == pytest.approx(0.3, rel=1e-6) and params[1][1] == pytest.approx(0.3, rel=1e-6)


@pytest.mark.parametrize("seed", range(12))
def test_classification_is_translation_invariant(seed):
    rng = np.random.default_rng(seed)
    C = circle_matrix(float(rng.uniform(0.2, 2.0)))
    # an ellipse, a hyperbola and a parabola, each translated by a large offset
    H_ell = affine(*rng.uniform(0.5, 3.0, size=2), rng.uniform(0, math.pi), 0.0, 0.0)
    H_hyp = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 1.0, 0.5 * math.sqrt(-C[2, 2])]])
    H_par = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 1.0, math.sqrt(-C[2, 2])]])
    for H, expected in ((H_ell, "ellipse"), (H_hyp, "hyperbola"), (H_par, "parabola")):
        Cp = transform_conic(C, H)
        assert classify(Cp) == expected
        # a parabola has no centre: its degeneracy / conditioning are judged at its vertex,
        # so it is translation invariant like the ellipse and the hyperbola (contract §2.6)
        for scale in (1.0, 1e3, 1e5):
            tx, ty = rng.uniform(-1, 1, size=2) * scale
            T = np.array([[1.0, 0, -tx], [0, 1.0, -ty], [0, 0, 1.0]])   # x^T (T^T C T) x: conic moved by (tx, ty)
            Ct = T.T @ Cp @ T
            assert classify(Ct) == expected, (expected, scale)
            assert not is_sampled(Ct), (expected, scale)
            assert condition_number(Ct) == pytest.approx(condition_number(Cp), rel=1e-3)


def test_parabola_is_translated_to_its_vertex():
    """Contract §2.6 [decision] (translation-invariant classification) for parabolas: the
    vertex of ``y = x^2 / (2p)`` moved by ``(tx, ty)`` is ``(tx, ty)``, the vertex-centred
    conic has no constant term and no linear term along the tangent, and the verdict
    (kind, sampled, cond) does not depend on the distance from the origin."""
    p = 0.7
    C0 = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -p], [0.0, -p, 0.0]])      # x^2 - 2 p y = 0
    Cc0, v0 = centred_conic(C0)
    assert np.allclose(v0, 0.0)
    for tx, ty in ((0.0, 0.0), (3.0, -2.0), (1e3, 0.5e3), (-1e4, 1e4)):
        R = rot2(0.3 * tx / (abs(tx) + 1.0))
        T = np.eye(3)
        T[:2, :2] = R.T                                   # x_local = R^T (x - t)
        T[:2, 2] = -(R.T @ np.array([tx, ty]))
        Ct = T.T @ C0 @ T
        Cc, vertex = centred_conic(Ct)
        assert np.allclose(vertex, [tx, ty], atol=1e-6 * max(1.0, abs(tx), abs(ty)))
        assert abs(Cc[2, 2]) < 1e-6                       # the vertex lies on the conic
        assert classify(Ct) == "parabola"
        assert not is_sampled(Ct)
        assert condition_number(Ct) == pytest.approx(condition_number(C0), rel=1e-6)
        # the vertex-centred conic is the rotated C_c0 up to the max-normalisation scale
        sv, sv0 = np.linalg.svd(Cc, compute_uv=False), np.linalg.svd(Cc0, compute_uv=False)
        assert np.allclose(sv / sv[0], sv0 / sv0[0], rtol=1e-6)
    # the image-space case of the review: a parabola whose vertex is a metre (1e3 mm) off-canvas
    C = transform_conic(circle_matrix(1.0), np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 1.0, 1.0]]))
    T = np.array([[1.0, 0, -1e3], [0, 1.0, 0], [0, 0, 1.0]])
    far = T.T @ C @ T
    assert classify(far) == "parabola" and not is_sampled(far) and condition_number(far) < 10.0
    # a parabola without a linear term along its axis is a pair of parallel lines: degenerate
    assert classify(np.diag([1.0, 0.0, -1.0])) == "degenerate"
    assert centred_conic(np.diag([1.0, 0.0, -1.0]))[1] is None
    assert classify(np.diag([1.0, 0.0, 0.0])) == "degenerate"              # a double line


def test_classify_degenerate_cases_and_zero_block():
    # two lines x^2 - y^2 = 0: det 0 -> degenerate even though the 2x2 block is fine
    assert classify(np.diag([1.0, -1.0, 0.0])) == "degenerate"
    # a single line (zero 2x2 block)
    assert classify(np.array([[0, 0, 1.0], [0, 0, 1.0], [1.0, 1.0, 0]])) == "degenerate"
    assert condition_number(np.zeros((3, 3))) == math.inf
    assert is_sampled(np.diag([1.0, -1.0, 0.0]))
    # a non-degenerate but ill-conditioned (tiny) ellipse is sampled; a very elongated one
    # (|det| <= 1e-12 after max-normalisation) is degenerate -- sampled either way
    C = transform_conic(circle_matrix(3e-5), affine(1.0, 1.0, 0.0, 5.0, 5.0))
    assert classify(C) == "ellipse" and condition_number(C) > 1e8 and is_sampled(C)
    C = transform_conic(circle_matrix(1.0), affine(1.0, 1e-5, 0.0, 0.0, 0.0))
    assert classify(C) == "degenerate" and is_sampled(C)


# --------------------------------------------------------------------------- circle helpers / output helpers
def test_circle_frame_record_embedding_and_point():
    e1, e2 = circle_frame([0.0, 0.0, 1.0])              # fallback n x x
    assert np.allclose(e1, [0, 1, 0]) and np.allclose(e2, [-1, 0, 0])
    e1, e2 = circle_frame([1.0, 1.0, 0.0])
    n = np.array([1.0, 1.0, 0.0]) / math.sqrt(2)
    assert np.allclose(e1, np.cross(n, [0, 0, 1.0]) / np.linalg.norm(np.cross(n, [0, 0, 1.0])))
    assert np.allclose(e2, np.cross(n, e1))
    assert np.allclose(np.cross(e1, e2), n)              # right-handed: theta increasing is CCW about n
    circ = circle_record([1, 2, 3], e1, e2, 0.5)
    E = circle_embedding(circ)
    assert np.allclose(E, embed_circle([1, 2, 3], e1, e2))
    P = circle_point(circ, 0.3)
    assert P.shape == (4,) and P[3] == 1.0
    assert np.allclose(P[:3], circ["centre"] + 0.5 * (math.cos(0.3) * e1 + math.sin(0.3) * e2))
    assert circle_point(circ, np.array([0.0, 1.0])).shape == (2, 4)


def test_sample_count_rule():
    assert sample_count(0.0, 2 * math.pi) == 64
    assert sample_count(0.0, math.pi) == 32
    assert sample_count(1.0, 1.0 + math.pi / 2) == 16
    assert sample_count(0.0, 0.01) == 8
    assert sample_count(2 * math.pi, 0.0) == 64                     # direction does not matter
    assert sample_count(0.0, math.pi, per_circle=256) == 128


def test_conic_entry_shape_and_canonical_floats():
    circ = circle_record([0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], 1.0)
    H = affine(2.0, 1.0, 0.3, 1.0, -1.0)
    entry = conic_entry(circ, H, arc=(2.0, 0.5), map="shadow")
    assert set(entry) == {"conic", "kind", "arc", "circle", "map", "sampled", "cond"}
    assert entry["kind"] == "ellipse" and entry["map"] == "shadow" and not entry["sampled"]
    assert entry["arc"] == {"theta0": 0.5, "theta1": 2.0}        # CCW range, theta1 > theta0
    assert max(max(row) for row in entry["conic"]) == 1.0
    assert entry["circle"]["radius"] == 1.0 and entry["circle"]["e1"] == [1.0, 0.0, 0.0]
    assert conic_entry(circ, H)["arc"] is None
    assert conic_entry(circ, H, arc={"theta0": 0.1, "theta1": 0.4})["arc"] == {"theta0": 0.1, "theta1": 0.4}
    import json
    json.dumps(entry)                                              # JSON serialisable
    singular = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 0, 0]])
    bad = conic_entry(circ, singular)
    assert bad["kind"] == "degenerate" and bad["sampled"] and bad["cond"] == math.inf


def test_ellipse_arc_params_matches_direct_points():
    H = affine(2.0, 1.0, 0.4, 1.0, -1.0)
    res = ellipse_arc_params(H, 1.0, 0.2, 2.5)
    assert res is not None
    centre, axes, rot = ellipse_params(transform_conic(circle_matrix(1.0), H))
    assert np.allclose(res["centre"], centre) and res["axes"] == pytest.approx(axes) and res["rotation"] == pytest.approx(rot)
    p0 = conic_point(H, 0.2, 1.0)
    p1 = conic_point(H, 2.5, 1.0)
    assert np.allclose(res["start"], p0[:2] / p0[2]) and np.allclose(res["end"], p1[:2] / p1[2])
    assert res["large_arc"] == 0 and res["sweep"] == 1                 # 2.3 rad < pi, orientation preserving
    assert ellipse_arc_params(H, 1.0, 2.5, 0.2)["sweep"] == 0
    assert ellipse_arc_params(H, 1.0, 0.2, 4.0)["large_arc"] == 1
    # a point behind the camera (x3 <= 0) -> None; a hyperbola -> None
    H_behind = H.copy()
    H_behind[2] = [0.0, 0.0, -1.0]
    assert ellipse_arc_params(H_behind, 1.0, 0.0, 1.0) is None
    H_hyp = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 1.0, 0.5]])
    assert ellipse_arc_params(H_hyp, 1.0, 0.0, 1.0) is None


def _noisy_circle(p, q, r):
    return np.array([[p, q, 0.0], [q, r, 0.0], [0.0, 0.0, 1.0]])


@pytest.mark.parametrize("p, q, r", [
    (-0.0032653061224489806, 1.27e-20, -0.0032653061224489793),    # numpy/BLAS values of the on-axis sphere (M7 review)
    (-0.0032653061224489793, -1.27e-20, -0.0032653061224489806),
    (-0.0032653061224489800, 0.0, -0.0032653061224489800),          # exact tie (the port's fixed-order sums)
])
def test_ellipse_params_circle_within_rounding_has_rotation_zero(p, q, r):
    """A circle whose matrix carries ulp noise has no defined axis direction; the rotation is fixed at 0 instead of
    being chosen by the exact tests ``p >= r`` / ``s1 >= s2`` from the noise (M7 review, §5.4 implementation notes)."""
    centre, (major, minor), rot = ellipse_params(_noisy_circle(p, q, r))
    assert rot == 0.0
    assert major >= minor and major == pytest.approx(17.5, rel=1e-12) and minor == pytest.approx(17.5, rel=1e-12)


def test_ellipse_params_near_circle_above_the_band_keeps_its_rotation():
    centre, (major, minor), rot = ellipse_params(_noisy_circle(-(1.0 + 2e-6), 0.0, -1.0))
    assert rot == pytest.approx(math.pi / 2, abs=1e-12) and major > minor        # the major axis lies along y


def test_sphere_centred_on_the_camera_axis_outline_ellipse_has_rotation_zero():
    import castplane
    from castplane.scene import load_scene
    scene = load_scene({
        "version": "0.1", "units": "m", "up": "z",
        "objects": [{"id": "s0", "type": "sphere", "radius": 0.5, "transform": {"position": [0, 0, 0]}}],
        "lights": [{"id": "lamp", "type": "point", "position": [0, 0, 4]}],
        "receivers": [{"id": "ground", "type": "plane", "normal": [0, 0, 1], "offset": 0}],
        "camera": {"position": [4, -8, 5], "target": [0, 0, 0.5], "focal_length_mm": 35, "frame_mm": [36, 24]},
        "output": {"canvas_mm": [360, 240]}})
    ell = castplane.render(scene)["geometry"]["outlines"][0]["conics"][0]["ellipses"][0]
    assert ell["rotation_deg"] == 0.0 and ell["rx"] == pytest.approx(ell["ry"], rel=1e-12)
