"""Tests for castplane.light and castplane.shadow (spec §5.1–5.3, §5.7, §7.2; contract §2.3/§2.5).

Test meshes are built by hand here following contract §2.4 (this track must not import
castplane.mesh).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from castplane.light import (face_lit_flags, is_parallel, light_vector, lit, lit_state,
                             silhouette_edges, silhouette_loops)
from castplane.shadow import (clip_loop_to_plane, clip_mesh_to_plane, foot, shadow_loop, shadow_matrix,
                              shadow_w)

GROUND = np.array([0.0, 0.0, 1.0, 0.0])
TOL = 1e-9


# --------------------------------------------------------------------------- mesh helpers (§2.4)
def mesh_from_faces(vertices, faces, prefix="m"):
    """Build the contract §2.4 mesh dict from vertices and CCW-from-outside faces."""
    V = np.asarray(vertices, dtype=np.float64)
    edge_set = {}
    for fi, f in enumerate(faces):
        n = len(f)
        for k in range(n):
            a, b = int(f[k]), int(f[(k + 1) % n])
            key = (min(a, b), max(a, b))
            edge_set.setdefault(key, []).append(fi)
    keys = sorted(edge_set)
    edges = np.array(keys, dtype=np.int64).reshape(-1, 2)
    edge_faces = np.array([edge_set[k] for k in keys], dtype=np.int64).reshape(-1, 2)
    normals = []
    for f in faces:  # Newell's method
        n = np.zeros(3)
        for k in range(len(f)):
            p, q = V[f[k]], V[f[(k + 1) % len(f)]]
            n += np.cross(p, q)
        normals.append(n / np.linalg.norm(n))
    return {
        "vertices": V,
        "edges": edges,
        "faces": [list(map(int, f)) for f in faces],
        "face_normals": np.array(normals),
        "edge_faces": edge_faces,
        "vertex_names": ["%s.v%d" % (prefix, k) for k in range(len(V))],
    }


def prism_mesh(polygon, height, position=(0.0, 0.0, 0.0)):
    """Contract §2.1 prism: CCW polygon in local XY extruded over [0, height]."""
    poly = np.asarray(polygon, dtype=np.float64)
    n = len(poly)
    bottom = np.c_[poly, np.zeros(n)]
    top = np.c_[poly, np.full(n, float(height))]
    V = np.vstack([bottom, top]) + np.asarray(position, dtype=np.float64)
    faces = [list(range(n - 1, -1, -1)), list(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, n + j, n + i])
    return mesh_from_faces(V, faces)


def box_mesh(size=(1.0, 1.0, 1.0), position=(0.0, 0.0, 0.0)):
    """Contract §2.1 box: [-sx/2, sx/2] x [-sy/2, sy/2] x [0, sz]; 8 vertices, 12 edges, 6 faces."""
    sx, sy, sz = size
    poly = [[-sx / 2, -sy / 2], [sx / 2, -sy / 2], [sx / 2, sy / 2], [-sx / 2, sy / 2]]
    return prism_mesh(poly, sz, position)


def signed_area(xy):
    P = np.asarray(xy, dtype=np.float64)
    x, y = P[:, 0], P[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def truncate(vertices4, far=1e4):
    """Replace direction vertices by finite points at distance ``far`` (ground x, y)."""
    out = []
    for v in vertices4:
        if v[3] == 0.0:
            d = v[:2] / np.linalg.norm(v[:2])
            out.append(d * far)
        else:
            out.append(v[:2] / v[3])
    return np.array(out)


def point_in_polygon(poly, p):
    wn = 0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        left = (x1 - x0) * (p[1] - y0) - (p[0] - x0) * (y1 - y0)
        if y0 <= p[1] < y1 and left > 0:
            wn += 1
        elif y1 <= p[1] < y0 and left < 0:
            wn -= 1
    return wn != 0


def box_shadow(size, light, position=(0, 0, 0)):
    mesh = box_mesh(size, position)
    L = light_vector(light)
    tol = TOL if light["type"] == "point" else 1e-9
    lit_flags, _ = face_lit_flags(mesh, L, tol)
    loops = silhouette_loops(mesh, lit_flags)
    M = shadow_matrix(GROUND, L)
    out = []
    for loop in loops:
        P4 = np.c_[mesh["vertices"][loop], np.ones(len(loop))]
        out.append(shadow_loop(P4, M, GROUND, tol))
    return mesh, loops, out


# --------------------------------------------------------------------------- mesh sanity
def test_unit_box_mesh_matches_contract_2_4():
    m = box_mesh()
    assert m["vertices"].shape == (8, 3)
    assert m["edges"].shape == (12, 2)
    assert len(m["faces"]) == 6
    assert m["edge_faces"].shape == (12, 2)
    assert np.all(m["edges"][:, 0] < m["edges"][:, 1])
    # outward normals: each face normal points away from the box centre
    centre = np.array([0.0, 0.0, 0.5])
    for f, n in zip(m["faces"], m["face_normals"]):
        p = m["vertices"][f].mean(axis=0)
        assert np.dot(n, p - centre) > 0


# --------------------------------------------------------------------------- light vectors / lit
def test_light_vector_forms():
    assert np.allclose(light_vector({"type": "point", "position": [1, 2, 3]}), [1, 2, 3, 1])
    d = [0.0, 0.6, 0.8]
    assert np.allclose(light_vector({"type": "directional", "direction": d}), d + [0.0])
    with pytest.raises(ValueError):
        light_vector({"type": "spot"})


def test_lit_point_and_directional_same_formula():
    n = np.array([0.0, 0.0, 1.0])
    p = np.array([0.3, 0.2, 1.0])
    assert lit(n, p, light_vector({"type": "point", "position": [0, 0, 3]}))
    assert not lit(n, p, light_vector({"type": "point", "position": [0, 0, 0.5]}))
    assert lit(n, p, light_vector({"type": "directional", "direction": [0, 0, 1]}))
    assert not lit(n, p, light_vector({"type": "directional", "direction": [0, 0, -1]}))


def test_parallel_band_counts_as_unlit():
    n = np.array([1.0, 0.0, 0.0])
    p = np.array([0.5, 0.0, 0.0])
    L = light_vector({"type": "directional", "direction": [0, 0, 1]})
    assert is_parallel(n, p, L, 1e-9)
    assert lit_state(n, p, L, 1e-9) == (False, True)
    # inside the band: the tiny positive value is still "parallel", not lit
    L2 = light_vector({"type": "point", "position": [0.5 + 1e-12, 0, 5]})
    assert lit_state(n, p, L2, 1e-9) == (False, True)
    assert lit_state(n, p, light_vector({"type": "point", "position": [2, 0, 5]}), 1e-9) == (True, False)


def test_face_lit_flags_vertical_sun_on_box():
    m = box_mesh()
    L = light_vector({"type": "directional", "direction": [0, 0, 1]})
    lit_flags, parallel = face_lit_flags(m, L, 1e-9)
    assert lit_flags.tolist() == [False, True, False, False, False, False]
    assert parallel.tolist() == [False, False, True, True, True, True]


# --------------------------------------------------------------------------- silhouettes
def test_silhouette_edges_of_box_under_overhead_point_light():
    m = box_mesh()
    L = light_vector({"type": "point", "position": [0, 0, 3]})
    lit_flags, parallel = face_lit_flags(m, L, TOL)
    assert not parallel.any()
    assert lit_flags.tolist() == [False, True, False, False, False, False]
    sil = silhouette_edges(m, lit_flags)
    top_edges = {(4, 5), (5, 6), (6, 7), (4, 7)}
    assert {tuple(m["edges"][e]) for e in sil} == top_edges
    loops = silhouette_loops(m, lit_flags)
    assert len(loops) == 1 and sorted(loops[0]) == [4, 5, 6, 7]


def test_silhouette_loops_closed_and_cover_all_silhouette_edges():
    m = box_mesh((1, 2, 1.5))
    L = light_vector({"type": "point", "position": [3, -2, 4]})
    lit_flags, _ = face_lit_flags(m, L, TOL)
    sil = silhouette_edges(m, lit_flags)
    loops = silhouette_loops(m, lit_flags)
    used = []
    for loop in loops:
        assert len(loop) >= 3
        for k in range(len(loop)):
            a, b = loop[k], loop[(k + 1) % len(loop)]
            used.append((min(a, b), max(a, b)))
    assert sorted(used) == sorted(tuple(m["edges"][e]) for e in sil)
    assert len(used) == 6  # hexagonal silhouette of a box lit from a generic direction


@pytest.mark.parametrize("light_pos", [(0, 0, 3), (2, 1, 3), (-3, 2, 2.5), (0.2, -4, 6)])
def test_box_shadow_polygon_is_ccw_in_ground_xy(light_pos):
    """Contract §2.5 orientation claim: lit face on the left seen from the light ->
    counter-clockwise ground polygon."""
    _, loops, shadows = box_shadow((1, 1, 1), {"type": "point", "position": list(light_pos)})
    assert len(shadows) == 1
    sh = shadows[0]
    assert not sh["unbounded"]
    xy = sh["vertices"][:, :2] / sh["vertices"][:, 3:4]
    assert signed_area(xy) > 0


def test_prism_shadow_polygon_is_ccw_under_directional_light():
    poly = [[-1, -1], [1, -1], [1, 0], [0.5, 0], [0.5, 1], [-1, 1]]  # concave L shape
    mesh = prism_mesh(poly, 1.2)
    L = light_vector({"type": "directional", "direction": [0.3, -0.4, math.sqrt(1 - 0.25)]})
    lit_flags, _ = face_lit_flags(mesh, L, 1e-9)
    M = shadow_matrix(GROUND, L)
    total = 0.0
    for loop in silhouette_loops(mesh, lit_flags):
        P4 = np.c_[mesh["vertices"][loop], np.ones(len(loop))]
        sh = shadow_loop(P4, M, GROUND, 1e-9)
        xy = sh["vertices"][:, :2] / sh["vertices"][:, 3:4]
        assert signed_area(xy) > 0
        total += signed_area(xy)
    assert total > 0


# --------------------------------------------------------------------------- shadow matrix / foot
def test_shadow_matrix_properties():
    for light in ({"type": "point", "position": [1, 2, 5]},
                  {"type": "directional", "direction": [0.6, 0, 0.8]}):
        L = light_vector(light)
        M = shadow_matrix(GROUND, L)
        assert np.allclose(GROUND @ M, 0)            # images lie in the plane
        assert np.allclose(M @ L, 0)                 # the light itself maps to zero
        X = np.array([0.3, -0.7, 0.0, 1.0])          # a ground point is its own shadow
        S = M @ X
        assert np.allclose(S / S[3], X)
        assert shadow_w(GROUND, L, X) == pytest.approx(S[3])


def test_foot_formula_5_3():
    X = np.array([1.0, 2.0, 3.0, 1.0])
    Q = foot(GROUND, X)
    assert np.allclose(Q / Q[3], [1, 2, 0, 1])
    F = foot(GROUND, light_vector({"type": "directional", "direction": [0.6, 0, 0.8]}))
    assert F[3] == 0 and np.allclose(F[:3], [0.6, 0, 0])
    # batch form and a general plane
    pi = np.array([0.0, 0.6, 0.8, -1.0])
    Xs = np.array([[1, 2, 3, 1], [0, 0, 0, 1], [2, 2, 2, 2]], dtype=float)
    Qs = foot(pi, Xs)
    assert np.allclose(Qs @ pi, 0)
    for X, Q in zip(Xs, Qs):
        d = Q[:3] / Q[3] - X[:3] / X[3]
        assert np.allclose(np.cross(d, pi[:3]), 0)


def test_shadow_w_matches_contract_2_3():
    P = np.array([0.5, 0.5, 1.0, 1.0])
    assert shadow_w(GROUND, light_vector({"type": "point", "position": [0, 0, 3]}), P) == pytest.approx(2.0)
    assert shadow_w(GROUND, light_vector({"type": "directional", "direction": [0, 0.6, 0.8]}), P) == pytest.approx(0.8)
    assert shadow_w(GROUND, light_vector({"type": "point", "position": [0, 0, 1]}), P) == pytest.approx(0.0)


# --------------------------------------------------------------------------- §7.2 analytic cases
@pytest.mark.parametrize("h", [1.5, 2.0, 5.0, 100.0])
def test_unit_box_point_light_overhead_scales_base_by_h_over_h_minus_1(h):
    _, _, shadows = box_shadow((1, 1, 1), {"type": "point", "position": [0, 0, h]})
    sh = shadows[0]
    xy = sh["vertices"][:, :2] / sh["vertices"][:, 3:4]
    s = h / (h - 1.0)
    expected = {(round(x * s, 9), round(y * s, 9)) for x in (-0.5, 0.5) for y in (-0.5, 0.5)}
    got = {(round(x, 9), round(y, 9)) for x, y in xy}
    assert got == expected
    assert [type(src) for src in sh["sources"]] == [int] * 4


@pytest.mark.parametrize("elev_deg, factor", [(45.0, 1.0), (30.0, math.sqrt(3.0))])
def test_sun_elevation_shadow_length(elev_deg, factor):
    e = math.radians(elev_deg)
    light = {"type": "directional", "direction": [-math.cos(e), 0.0, math.sin(e)]}  # light at -x
    height = 1.3
    _, _, shadows = box_shadow((1, 1, height), light)
    sh = shadows[0]
    xy = sh["vertices"][:, :2] / sh["vertices"][:, 3:4]
    assert xy[:, 0].max() == pytest.approx(0.5 + height * factor)
    assert xy[:, 0].min() == pytest.approx(-0.5)
    assert signed_area(xy) == pytest.approx(1.0 + height * factor)


def test_box_taller_than_point_light_is_unbounded_with_correct_directions():
    light = {"type": "point", "position": [3.0, 0.0, 1.5]}
    mesh, loops, shadows = box_shadow((1, 1, 2), light)
    assert len(shadows) == 1
    sh = shadows[0]
    assert sh["unbounded"]
    V = sh["vertices"]
    L = light_vector(light)
    M = shadow_matrix(GROUND, L)
    dirs = [k for k, v in enumerate(V) if v[3] == 0.0]
    assert len(dirs) >= 2
    # outgoing / incoming direction vertices vs the limit of S(t)/w(t) along the source edge
    for k, src in enumerate(sh["sources"]):
        if isinstance(src, tuple) and src[0] == "dir":
            i, j = src[1], src[2]
            Pa = np.r_[mesh["vertices"][loops[0][i]], 1.0]
            Pb = np.r_[mesh["vertices"][loops[0][j]], 1.0]
            wa, wb = (M @ Pa)[3], (M @ Pb)[3]
            t_star = wa / (wa - wb)
            # approach the crossing from the finite side
            t = t_star - 1e-7 if wa > 0 else t_star + 1e-7
            S = M @ ((1 - t) * Pa + t * Pb)
            p = S[:2] / S[3]
            d = p / np.linalg.norm(p)
            assert np.linalg.norm(p) > 1e5
            assert np.allclose(d, V[k][:2] / np.linalg.norm(V[k][:2]), atol=1e-6)
    # the shadow region lies behind the box, away from the light (-x direction)
    poly = truncate(V)
    assert signed_area(poly) > 0
    assert point_in_polygon(poly, (-50.0, 0.0))
    assert not point_in_polygon(poly, (50.0, 0.0))
    # the truncated finite part: base vertices on the lit (+x) side are their own shadow
    finite = [v[:2] / v[3] for v in V if v[3] != 0.0]
    assert any(np.allclose(f, (0.5, -0.5)) for f in finite)
    assert any(np.allclose(f, (0.5, 0.5)) for f in finite)


def test_arc_at_infinity_subedges_are_below_90_degrees():
    light = {"type": "point", "position": [3.0, 0.0, 1.5]}
    _, _, shadows = box_shadow((1, 1, 2), light)
    V = shadows[0]["vertices"]
    n = len(V)
    for k in range(n):
        a, b = V[k], V[(k + 1) % n]
        if a[3] == 0.0 and b[3] == 0.0:
            ang = math.degrees(math.acos(np.clip(np.dot(a[:2], b[:2]) /
                                                 (np.linalg.norm(a[:2]) * np.linalg.norm(b[:2])), -1, 1)))
            assert ang < 90.0


def test_u_prism_with_light_inside_notch_sweeps_the_large_arc():
    """Contract review case: the at-infinity arc must sweep ~335 degrees CCW, not 28."""
    poly = [[-2, -2], [2, -2], [2, 2], [0.5, 2], [0.5, -1], [-0.5, -1], [-0.5, 2], [-2, 2]]
    assert signed_area(poly) > 0
    mesh = prism_mesh(poly, 3.0)
    light = {"type": "point", "position": [0.0, 0.0, 1.5]}
    L = light_vector(light)
    lit_flags, _ = face_lit_flags(mesh, L, TOL)
    assert int(lit_flags.sum()) == 3  # the three notch walls
    loops = silhouette_loops(mesh, lit_flags)
    assert len(loops) == 1
    M = shadow_matrix(GROUND, L)
    P4 = np.c_[mesh["vertices"][loops[0]], np.ones(len(loops[0]))]
    sh = shadow_loop(P4, M, GROUND, TOL)
    assert sh["unbounded"]
    V = sh["vertices"]
    dir_idx = [k for k, v in enumerate(V) if v[3] == 0.0]
    d_out = V[dir_idx[0]]
    d_in = V[dir_idx[-1]]
    sweep = (math.atan2(d_in[1], d_in[0]) - math.atan2(d_out[1], d_out[0])) % (2 * math.pi)
    assert math.degrees(sweep) > 300.0
    assert len(dir_idx) >= 6  # ceil(332 / 60) = 6 steps -> 7 direction vertices
    poly_t = truncate(V)
    far = 5e3
    for deg in (0.0, 180.0, 270.0):
        p = (far * math.cos(math.radians(deg)), far * math.sin(math.radians(deg)))
        assert point_in_polygon(poly_t, p), deg
    p = (far * math.cos(math.radians(90.0)), far * math.sin(math.radians(90.0)))
    assert not point_in_polygon(poly_t, p)
    assert signed_area(poly_t) > 0


def test_loop_entirely_above_light_yields_no_shadow():
    mesh = box_mesh((1, 1, 1), position=(0, 0, 5))
    light = {"type": "point", "position": [3, 0, 1.0]}
    L = light_vector(light)
    M = shadow_matrix(GROUND, L)
    loop = [4, 5, 6, 7]
    P4 = np.c_[mesh["vertices"][loop], np.ones(4)]
    sh = shadow_loop(P4, M, GROUND, TOL)
    assert sh["vertices"].shape == (0, 4)
    assert not sh["unbounded"]
    assert sh["sources"] == []


# --------------------------------------------------------------------------- ground clip (§2.3)
def test_ground_clip_drops_below_ground_part():
    loop = np.array([[0, 0, -1, 1], [1, 0, -1, 1], [1, 0, 1, 1], [0, 0, 1, 1]], dtype=float)
    clipped, sources, below = clip_loop_to_plane(loop, GROUND, TOL)
    assert below
    assert clipped.shape == (4, 4)
    assert np.allclose(clipped[:, 2] >= -TOL, True)
    assert sources == [("ground", 1, 2), 2, 3, ("ground", 3, 0)]
    assert np.allclose(clipped[0], [1, 0, 0, 1]) and np.allclose(clipped[3], [0, 0, 0, 1])
    same, src2, below2 = clip_loop_to_plane(loop[2:], GROUND, TOL)
    assert not below2 and src2 == [0, 1] and np.allclose(same, loop[2:])


def test_ground_clip_on_plane_vertex_is_not_duplicated():
    """Reviewer finding: a kept vertex inside the band |pi^T X| <= tol is its own
    crossing; the clip must not insert a second copy (zero-length edge, two point names)."""
    loop = np.array([[0, 0, 0, 1], [1, 0, -1, 1], [1, 0, 1, 1], [0, 0, 1, 1]], dtype=float)
    clipped, sources, below = clip_loop_to_plane(loop, GROUND, TOL)
    assert below
    assert sources == [0, ("ground", 1, 2), 2, 3]
    assert np.allclose(clipped, [[0, 0, 0, 1], [1, 0, 0, 1], [1, 0, 1, 1], [0, 0, 1, 1]])
    for a, b in zip(clipped, np.roll(clipped, -1, axis=0)):
        assert np.linalg.norm(a - b) > 1e-6
    # the same with the on-plane vertex slightly inside the band and as the *second* endpoint
    loop2 = np.array([[0, 0, 1, 1], [0, 0, 5e-10, 1], [1, 0, -1, 1], [1, 0, 1, 1]], dtype=float)
    clipped2, sources2, _ = clip_loop_to_plane(loop2, GROUND, TOL)
    assert sources2 == [0, 1, ("ground", 2, 3), 3]
    loop3 = np.array([[0, 0, 1, 1], [1, 0, 1, 1], [1, 0, -1, 1], [0, 0, -5e-10, 1]], dtype=float)
    clipped3, sources3, _ = clip_loop_to_plane(loop3, GROUND, TOL)
    assert sources3 == [0, 1, ("ground", 1, 2), 3]


def test_shadow_loop_separate_clip_tolerance():
    """Reviewer finding: the ground clip is a length predicate (tol = 1e-9 * scene_scale)
    while w_S for a directional light uses tol_dir = 1e-9; ``tol_clip`` separates them."""
    L = light_vector({"type": "directional", "direction": [0.0, 0.0, 1.0]})
    M = shadow_matrix(GROUND, L)
    depth = -5e-7
    loop = np.array([[0, 0, depth, 1], [1, 0, depth, 1], [1, 1, 1, 1], [0, 1, 1, 1]], dtype=float)
    # tol_clip larger than |depth|: the vertices are "on" the ground and nothing is cut
    sh = shadow_loop(loop, M, GROUND, tol=1e-9, tol_clip=1e-6)
    assert not sh["below_ground"] and sh["sources"] == [0, 1, 2, 3]
    # default: tol_clip = tol -> the two vertices are below and get clipped
    sh = shadow_loop(loop, M, GROUND, tol=1e-9)
    assert sh["below_ground"]
    assert sum(isinstance(x, tuple) and x[0] == "ground" for x in sh["sources"]) == 2
    # tol_clip never influences the w_S predicate
    sh = shadow_loop(loop, M, GROUND, tol=1e-9, tol_clip=10.0)
    assert not sh["unbounded"] and not sh["below_ground"]


def test_shadow_loop_through_the_light_is_finite():
    """Reviewer finding (spec §5.8 / §7.1 row 6): a raw loop with a vertex exactly at the
    point light (M L = 0) must not raise and must not produce NaN."""
    L = np.array([0.5, 0.5, 1.0, 1.0])
    M = shadow_matrix(GROUND, L)
    loop = np.array([[0, 0, 0, 1], [1, 0, 0, 1], [0.5, 0.5, 1, 1], [0, 1, 0, 1]], dtype=float)
    with np.errstate(all="raise"):
        sh = shadow_loop(loop, M, GROUND, TOL)
    V = sh["vertices"]
    assert np.all(np.isfinite(V))
    assert sh["unbounded"]
    dirs = V[V[:, 3] == 0.0]
    assert len(dirs) >= 2
    assert np.allclose(np.linalg.norm(dirs[:, :3], axis=1), 1.0)
    assert sh["vertices"][0].tolist() == [0.0, 0.0, 0.0, 1.0]
    # same loop, light at a different vertex position (incoming edge first / last)
    for loop2 in (np.roll(loop, 1, axis=0), np.roll(loop, -1, axis=0)):
        with np.errstate(all="raise"):
            sh2 = shadow_loop(loop2, M, GROUND, TOL)
        assert np.all(np.isfinite(sh2["vertices"]))


def test_shadow_loop_half_buried_box_is_clipped_at_the_ground():
    """Contract §2.3: the silhouette *loop* is clipped to z >= 0, so the crossings (which
    are their own shadows) replace the buried vertices and the cut is the straight chord
    between the crossings.  The crossings here are base corners of the upper half, so
    every vertex of the clipped shadow is a vertex of the upper-half box's shadow; the
    chord skips the one cut-face corner that is not on the silhouette loop."""
    light = {"type": "point", "position": [2.0, 1.0, 6.0]}
    full = box_shadow((1, 1, 1), light, position=(0, 0, -0.5))
    sh = full[2][0]
    assert sh["below_ground"]
    assert sum(isinstance(s, tuple) and s[0] == "ground" for s in sh["sources"]) == 2
    for v, src in zip(sh["vertices"], sh["sources"]):
        if isinstance(src, tuple):
            assert v[2] == pytest.approx(0.0)
    ref = box_shadow((1, 1, 0.5), light)[2][0]
    a = {tuple(np.round(v[:2] / v[3], 9)) for v in sh["vertices"]}
    b = {tuple(np.round(v[:2] / v[3], 9)) for v in ref["vertices"]}
    assert a < b and len(b) - len(a) == 1
    assert signed_area(sh["vertices"][:, :2] / sh["vertices"][:, 3:4]) > 0


# --------------------------------------------------------------------------- end-to-end vs. reference
def test_box_shadow_matches_raycast_reference():
    from tests.reference.raster import iou, rasterize_polygons
    from tests.reference.raycast import shadow_mask

    size = (1.0, 0.8, 0.6)
    light = {"id": "lamp", "type": "point", "position": [1.0, 3.0, 3.5]}
    scene = {"objects": [{"id": "crate", "type": "box", "size": list(size),
                          "transform": {"position": [0, 0, 0], "rotation_deg": [0, 0, 0]}}]}
    _, _, shadows = box_shadow(size, light)
    loops2d = [sh["vertices"][:, :2] / sh["vertices"][:, 3:4] for sh in shadows]
    xs = np.linspace(-3, 3, 400)
    ys = np.linspace(-4, 2, 400)
    assert iou(rasterize_polygons(loops2d, xs, ys), shadow_mask(scene, light, xs, ys)) >= 0.99


# --------------------------------------------------------------------------- random polyhedra vs. reference (§7.3)
def _placed_mesh(obj):
    """Hand-built box/prism mesh placed with the object's transform (test-only helper)."""
    from tests.reference.raycast import object_frame

    if obj["type"] == "box":
        sx, sy, sz = obj["size"]
        poly = [[-sx / 2, -sy / 2], [sx / 2, -sy / 2], [sx / 2, sy / 2], [-sx / 2, sy / 2]]
        h = sz
    else:
        poly, h = obj["polygon"], obj["height"]
    m = prism_mesh(poly, h)
    R, pos = object_frame(obj)
    return mesh_from_faces(m["vertices"] @ R.T + pos, m["faces"], obj["id"])


def _polyhedra_scene(seed, n):
    from tests.reference import random_scenes
    rng = np.random.default_rng(seed)
    objects = [random_scenes.random_object(rng, i, "box" if i % 2 else "prism") for i in range(n)]
    light = random_scenes.random_light(rng, objects)
    return random_scenes.assemble_scene(objects, light, random_scenes.random_camera(rng, objects))


@pytest.mark.parametrize("seed", range(10))
def test_random_polyhedra_shadows_match_raycast_reference(seed):
    from tests.reference import random_scenes
    from tests.reference.raster import iou, rasterize_polygons
    from tests.reference.raycast import shadow_mask

    scene = random_scenes.make_concavity_scene(seed) if seed % 3 == 0 else _polyhedra_scene(seed, 1 + seed % 5)
    light = scene["lights"][0]
    L = light_vector(light)
    M = shadow_matrix(GROUND, L)
    tol = 1e-9 if light["type"] == "directional" else TOL * 10
    loops2d = []
    for obj in scene["objects"]:
        mesh = _placed_mesh(obj)
        lit_flags, _ = face_lit_flags(mesh, L, tol)
        for loop in silhouette_loops(mesh, lit_flags):
            P4 = np.c_[mesh["vertices"][loop], np.ones(len(loop))]
            sh = shadow_loop(P4, M, GROUND, tol)
            assert not sh["unbounded"]
            V = sh["vertices"]
            if len(V):
                loops2d.append(V[:, :2] / V[:, 3:4])
    xs, ys = random_scenes.sample_grid(scene, light, n=400)
    ref = shadow_mask(scene, light, xs, ys)
    got = rasterize_polygons(loops2d, xs, ys)
    assert iou(got, ref) >= 0.99


# --------------------------------------------------------------------------- unbounded shadows vs. reference
def _low_light_scene(seed):
    """Tall (possibly tilted) boxes and concave prisms with a point light at z in
    [0.2, 1.2] outside every object's bounding box: most silhouette loops are unbounded."""
    from tests.reference import random_scenes
    rng = np.random.default_rng(seed)
    n = int(rng.integers(1, 4))
    objects = []
    for i in range(n):
        o = random_scenes.random_object(rng, i, "box" if i % 2 else "prism")
        if o["type"] == "box":
            o["size"][2] = round(o["size"][2] * 2.5, 4)
        else:
            o["height"] = round(o["height"] * 2.0, 4)
        min_z = float(np.min(random_scenes.world_extreme_points(o)[:, 2]))
        o["transform"]["position"][2] = round(o["transform"]["position"][2] - min_z, 6)
        objects.append(o)
    while True:
        pos = np.array([rng.uniform(-7, 7), rng.uniform(-7, 7), rng.uniform(0.2, 1.2)])
        inside = False
        for o in objects:
            pts = random_scenes.world_extreme_points(o)
            if np.all(pos >= pts.min(axis=0) - 0.2) and np.all(pos <= pts.max(axis=0) + 0.2):
                inside = True
        if not inside:
            break
    light = {"id": "light", "type": "point", "position": [round(float(v), 4) for v in pos]}
    return random_scenes.assemble_scene(objects, light, random_scenes.random_camera(rng, objects))


def _unbounded_shadows(scene):
    light = scene["lights"][0]
    L = light_vector(light)
    M = shadow_matrix(GROUND, L)
    out = []
    for obj in scene["objects"]:
        mesh = _placed_mesh(obj)
        lit_flags, _ = face_lit_flags(mesh, L, TOL)
        for loop in silhouette_loops(mesh, lit_flags):
            P4 = np.c_[mesh["vertices"][loop], np.ones(len(loop))]
            sh = shadow_loop(P4, M, GROUND, TOL)
            if len(sh["vertices"]):
                out.append(sh)
    return out


@pytest.mark.parametrize("seed", range(12))
def test_unbounded_random_polyhedra_shadows_are_ccw_and_match_raycast(seed):
    """Reviewer test gap: unbounded loops (incl. several excursions to infinity) and
    tilted meshes must still be CCW and agree with the raycast reference on a window."""
    from tests.reference.raster import iou, rasterize_polygons
    from tests.reference.raycast import shadow_mask

    scene = _low_light_scene(seed)
    shadows = _unbounded_shadows(scene)
    assert any(sh["unbounded"] for sh in shadows)
    loops2d = []
    for sh in shadows:
        V = sh["vertices"]
        assert np.all(np.isfinite(V))
        poly = truncate(V, 1e5)
        assert signed_area(poly) > 0
        loops2d.append(poly)
    xs = np.linspace(-6, 6, 400)
    ys = np.linspace(-6, 6, 400)
    assert iou(rasterize_polygons(loops2d, xs, ys), shadow_mask(scene, scene["lights"][0], xs, ys)) >= 0.99


@pytest.mark.parametrize("seed, n_dir", [(6, 4), (8, 6)])
def test_loops_with_several_excursions_to_infinity(seed, n_dir):
    """Loops that leave to infinity more than once (>= 4 direction vertices from edges):
    every outgoing direction is followed by an incoming one and the result is CCW."""
    shadows = _unbounded_shadows(_low_light_scene(seed))
    counts = [sum(isinstance(s, tuple) and s[0] == "dir" for s in sh["sources"]) for sh in shadows]
    assert max(counts) == n_dir
    sh = shadows[counts.index(n_dir)]
    kinds = [s[0] if isinstance(s, tuple) else "finite" for s in sh["sources"]]
    V = sh["vertices"]
    n = len(V)
    for k in range(n):
        if kinds[k] == "dir" and V[k][3] == 0.0 and kinds[(k + 1) % n] in ("arc", "dir"):
            # outgoing: the following vertex is at infinity too
            assert V[(k + 1) % n][3] == 0.0
    assert signed_area(truncate(V, 1e5)) > 0


# --------------------------------------------------------------------------- ground clip of the solid (contract §2.3)
def _rotated(mesh, rx_deg, ry_deg, dz):
    """Tilt a mesh (Z-Y-X order: here Ry·Rx) and shift it by ``dz``; normals are rotated too."""
    rx, ry = math.radians(rx_deg), math.radians(ry_deg)
    Rx = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]])
    Ry = np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]])
    R = Ry @ Rx
    out = dict(mesh)
    out["vertices"] = mesh["vertices"] @ R.T + np.array([0.0, 0.0, dz])
    out["face_normals"] = mesh["face_normals"] @ R.T
    return out


def _euler(mesh):
    return mesh["vertices"].shape[0] - mesh["edges"].shape[0] + len(mesh["faces"])


def test_clip_mesh_to_plane_tilted_box_gets_one_cap_with_outward_normal_minus_n():
    box = _rotated(prism_mesh([[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]], 1.0), 25.0, -15.0, -0.3)
    clipped, origins = clip_mesh_to_plane(box, GROUND, TOL)
    assert _euler(clipped) == 2 and clipped["edge_faces"].shape[1] == 2
    assert np.all(clipped["vertices"][:, 2] >= -TOL)
    crossings = [k for k, o in enumerate(origins) if isinstance(o, tuple)]
    assert crossings and all(abs(clipped["vertices"][k, 2]) <= 1e-12 for k in crossings)
    caps = [i for i, f in enumerate(clipped["faces"]) if all(isinstance(origins[v], tuple) for v in f)]
    assert len(caps) == 1
    np.testing.assert_allclose(clipped["face_normals"][caps[0]], [0.0, 0.0, -1.0], atol=1e-12)
    # original faces keep their normals; the kept original vertices keep their coordinates
    for k, o in enumerate(origins):
        if isinstance(o, int):
            np.testing.assert_allclose(clipped["vertices"][k], box["vertices"][o])
        else:
            i, j = o[1], o[2]
            a, b = box["vertices"][i], box["vertices"][j]
            t = a[2] / (a[2] - b[2])
            np.testing.assert_allclose(clipped["vertices"][k], a + t * (b - a), atol=1e-12)


def test_clip_mesh_to_plane_bridges_a_hole_into_the_cap():
    """A tilted U prism whose notch dips below the ground: the ground cross-section is an annulus and
    must become ONE cap face (keyhole polygon), never a spurious upward-facing hole face."""
    u = [[-1, -1], [1, -1], [1, 1], [0.3, 1], [0.3, -0.5], [-0.3, -0.5], [-0.3, 1], [-1, 1]]
    mesh = _rotated(prism_mesh(u, 1.0), 15.0, 10.0, -0.2)
    clipped, origins = clip_mesh_to_plane(mesh, GROUND, TOL)
    # the bridge is one edge shared by the cap with itself: V - E + F = 2 - 2 (one hole)
    assert _euler(clipped) == 0 and clipped["edge_faces"].shape[1] == 2
    caps = [i for i, f in enumerate(clipped["faces"]) if all(isinstance(origins[v], tuple) for v in f)]
    assert len(caps) == 1
    cap = clipped["faces"][caps[0]]
    assert len(cap) > len(set(cap))                                     # the bridge vertices appear twice
    bridge = [k for k, e in enumerate(clipped["edges"].tolist()) if clipped["edge_faces"][k].tolist() == [caps[0]] * 2]
    assert len(bridge) == 1
    assert clipped["face_normals"][caps[0]][2] < 0.0                    # outward normal -n
    # a face normal pointing up at z = 0 would be a hole drawn as a face
    for i, f in enumerate(clipped["faces"]):
        if np.all(np.abs(clipped["vertices"][f][:, 2]) <= 1e-9):
            assert clipped["face_normals"][i][2] < 0.0
    # the silhouette of the clipped solid under a light above is a closed walk with the cut-face edges in it
    L = light_vector({"type": "point", "position": [1.5, -1.0, 6.0]})
    lit_flags, _ = face_lit_flags(clipped, L, TOL)
    assert not lit_flags[caps[0]]
    loops = silhouette_loops(clipped, lit_flags)
    assert loops and any(isinstance(origins[v], tuple) for loop in loops for v in loop)


def test_clip_mesh_to_plane_whole_solid_below_gives_an_empty_mesh():
    box = prism_mesh([[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]], 1.0, position=(0.0, 0.0, -2.0))
    clipped, origins = clip_mesh_to_plane(box, GROUND, TOL)
    assert clipped["vertices"].shape == (0, 3) and clipped["faces"] == [] and origins == []
    lit_flags, _ = face_lit_flags(clipped, light_vector({"type": "point", "position": [0.0, 0.0, 3.0]}), TOL)
    assert silhouette_loops(clipped, lit_flags) == []


def test_clip_mesh_to_plane_keeps_a_vertex_on_the_plane_without_duplicates():
    # bottom edge v0-v1 exactly on the ground, the opposite bottom edge below (rotation about x)
    a = math.radians(30.0)
    box = prism_mesh([[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]], 1.0)
    R = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    V = box["vertices"] @ R.T
    V[:, 2] -= V[2, 2]                   # v2 (and v3) exactly at z = 0, v0 / v1 below, the top above
    box = dict(box, vertices=V, face_normals=box["face_normals"] @ R.T)
    assert abs(V[2, 2]) <= 1e-15 and abs(V[3, 2]) <= 1e-15 and V[0, 2] < 0 and V[1, 2] < 0 and V[4, 2] > 0
    clipped, origins = clip_mesh_to_plane(box, GROUND, TOL)
    assert _euler(clipped) == 2
    assert origins.count(2) == 1 and origins.count(3) == 1 and 0 not in origins and 1 not in origins
    # the on-plane vertices are their own crossings: only the two vertical edges from v0 / v1 cross
    assert sorted(o for o in origins if isinstance(o, tuple)) == [("ground", 0, 4), ("ground", 1, 5)]
    caps = [i for i, f in enumerate(clipped["faces"]) if np.all(np.abs(clipped["vertices"][f][:, 2]) <= 1e-12)]
    assert len(caps) == 1 and len(clipped["faces"][caps[0]]) == 4
