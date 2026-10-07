"""Mesh preprocessing (contract §5.2.3 – §5.2.5, test table of §5.2.11): weld, degenerate faces,
orientation / nesting, non-manifold detection and fallback, coplanar merge, edge classification,
``point_inside_mesh``."""

from __future__ import annotations

import math

import numpy as np
import pytest

from castplane import meshprep
from castplane.mesh import box_mesh, mesh_from_faces, prism_mesh, triangulate_faces
from castplane.meshprep import (COPLANAR_TOL_RAD, INSIDE_WINDING, MESH_MAX_RAYS, SMOOTH_ANGLE_DEFAULT, SMOOTH_BAND,
                                WELD_TOLERANCE_DEFAULT, build_adjacency, classify_edges, compact_vertices,
                                drop_degenerate_faces, fallback_mesh, fix_orientation, inherit_edge_smooth,
                                merge_coplanar, point_inside_mesh, preprocess_mesh, signed_volume, triangulate,
                                weld_map, weld_vertices, winding_number)

CUBE_V = [[-.5, -.5, 0.0], [.5, -.5, 0.0], [.5, .5, 0.0], [-.5, .5, 0.0],
          [-.5, -.5, 1.0], [.5, -.5, 1.0], [.5, .5, 1.0], [-.5, .5, 1.0]]
CUBE_F = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
#: the acceptance box of contract §5.2.12: 8 vertices + the same eight twice, 12 triangles on the duplicates
SPLIT_V = CUBE_V * 3
SPLIT_F = [[8, 11, 10], [8, 10, 9], [12, 13, 14], [12, 14, 15], [16, 17, 21], [16, 21, 20],
           [17, 18, 22], [17, 22, 21], [18, 19, 23], [18, 23, 22], [19, 16, 20], [19, 20, 23]]


def prep(vertices, faces, groups=None, scale=1.0, weld=WELD_TOLERANCE_DEFAULT, smooth=SMOOTH_ANGLE_DEFAULT):
    data = {"vertices": vertices, "faces": faces}
    if groups is not None:
        data["smooth_groups"] = groups
    return preprocess_mesh(data, scale, weld, smooth, "m")


def codes(warnings):
    return [w["code"] for w in warnings]


def test_constants():
    assert (COPLANAR_TOL_RAD, WELD_TOLERANCE_DEFAULT, SMOOTH_ANGLE_DEFAULT, MESH_MAX_RAYS, SMOOTH_BAND,
            INSIDE_WINDING) == (1e-3, 1e-6, 30.0, 64, 1e-9, 0.75)


# --- weld (step 2) -----------------------------------------------------------------------------

def test_weld_lowest_input_index_among_representatives_in_neighbouring_cells():
    # tau = 1: r1 (cell -1) and r2 (cell 1) are 1.8 apart (two representatives); v (cell 0) is within
    # tau of both and joins the one with the LOWEST INPUT INDEX, not the nearer one
    r1, r2, v = [-0.9, 0.0, 0.0], [0.9, 0.0, 0.0], [0.05, 0.0, 0.0]
    for fast in (True, False):
        assert weld_map([r1, r2, v], 1.0, fast).tolist() == [0, 1, 0]
        assert weld_map([r2, r1, v], 1.0, fast).tolist() == [0, 1, 0]
    W, faces, index = weld_vertices([r2, r1, v], [[0, 1, 2]], 1.0)
    assert W.tolist() == [r2, r1] and index.tolist() == [0, 1, 0] and faces == [[0, 1, 0]]


def test_weld_keeps_the_representatives_own_coordinates_and_first_appearance_order():
    V = [[1.0, 0, 0], [0.0, 0, 0], [1.0 + 4e-7, 0, 0], [0.0, 0, -5e-7], [2.0, 0, 0]]
    W, faces, index = weld_vertices(V, [[2, 3, 4]], 1e-6)
    assert W.tolist() == [[1.0, 0, 0], [0.0, 0, 0], [2.0, 0, 0]]     # never a mean
    assert index.tolist() == [0, 1, 0, 1, 2] and faces == [[0, 1, 2]]
    # max-norm distance: each coordinate within tau
    assert weld_map([[0, 0, 0], [1e-6, 1e-6, 1e-6]], 1e-6).tolist() == [0, 0]
    assert weld_map([[0, 0, 0], [1e-6, 1.5e-6, 0]], 1e-6).tolist() == [0, 1]


def test_weld_tau_zero_is_exact_equality():
    V = [[0.0, 0, 0], [-0.0, 0, 0], [1e-300, 0, 0], [0.0, 0, 0]]
    for fast in (True, False):
        assert weld_map(V, 0.0, fast).tolist() == [0, 0, 2, 0]


def test_weld_split_vertex_box_reproduces_the_parametric_vertices():
    W, faces, index = weld_vertices(SPLIT_V, SPLIT_F, 1e-6)
    assert W.tolist() == CUBE_V and index.tolist() == list(range(8)) * 3
    assert faces[0] == [0, 3, 2] and faces[-1] == [3, 4, 7]


@pytest.mark.parametrize("seed", range(6))
def test_weld_fast_path_is_result_identical_to_the_reference_loop(seed):
    rng = np.random.default_rng(seed)
    tau = [1e-6, 1e-3, 0.05, 0.0, 0.3, 1e-6][seed]
    centres = rng.uniform(-2, 2, size=(60, 3))
    # clusters of near-duplicates (some straddling cell borders), isolated points, exact copies
    pts = [centres[int(rng.integers(60))] + rng.uniform(-1.2, 1.2, size=3) * tau for _ in range(600)]
    pts += list(centres)
    pts += [pts[int(rng.integers(len(pts)))] for _ in range(100)]
    # points placed exactly on cell borders and at distance exactly tau
    pts += [np.array([0.5, 0.5, 0.5]) * tau, np.array([1.5, 0.5, 0.5]) * tau, np.array([-0.5, 0.5, 0.5]) * tau]
    V = np.array(pts)[rng.permutation(len(pts))]
    ref = weld_map(V, tau, fast=False)
    fast = weld_map(V, tau, fast=True)
    assert np.array_equal(ref, fast)
    a = weld_vertices(V, [[0, 1, 2]], tau, fast=False)
    b = weld_vertices(V, [[0, 1, 2]], tau, fast=True)
    assert np.array_equal(a[0], b[0]) and a[1] == b[1] and np.array_equal(a[2], b[2])


def test_weld_fast_path_dense_grid_and_rounding_borders():
    # a dense grid at spacing tau: every cell has occupied neighbours (all vertices take the loop)
    g = np.arange(6) * 1e-3
    V = np.array([[x, y, z] for x in g for y in g for z in g])
    assert np.array_equal(weld_map(V, 1e-3, fast=True), weld_map(V, 1e-3, fast=False))
    # same cell but more than tau apart after rounding of x / tau: handled by the loop
    tau = 0.1
    V = np.array([[0.04999999999999999, 0, 0], [-0.04999999999999999 - 0.1 + 1e-17, 0, 0], [0.0, 0, 0]])
    assert np.array_equal(weld_map(V, tau, fast=True), weld_map(V, tau, fast=False))


# --- degenerate faces (step 3) -------------------------------------------------------------------

def test_degenerate_faces_rules():
    V = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [2, 0, 0], [1e-7, 0, 0]], dtype=float)
    faces = [[0, 1, 2, 1],        # not pairwise distinct: dropped (would fool the manifold count)
             [0, 0, 1, 2],        # collapsed to [0, 1, 2]
             [0, 1, 2, 0],        # cyclic duplicate collapsed, start vertex kept: [0, 1, 2]
             [0, 1, 4],           # collinear: zero Newell normal
             [1, 1, 1],           # collapses to one vertex
             [0, 1],              # fewer than 3 vertices
             [0, 5, 3],           # Newell norm 1e-7 > 1e-12 * scale_A^2: kept
             [0, 2, 3]]
    kept, idx = drop_degenerate_faces(V, faces, 1.0)
    assert kept == [[0, 1, 2], [0, 1, 2], [0, 5, 3], [0, 2, 3]] and idx == [1, 2, 6, 7]
    kept, idx = drop_degenerate_faces(V, faces, 1e3)        # threshold 1e-12 * 1e6 = 1e-6 > 1e-7
    assert idx == [1, 2, 7]


def test_degenerate_faces_warning_and_compaction():
    V = CUBE_V + [[5.0, 5.0, 5.0]]
    mesh, tris, fallback, groups, warnings = prep(V, CUBE_F + [[0, 1, 0], [8, 8, 8]])
    assert codes(warnings) == ["MESH_DEGENERATE_FACES"] and "2 degenerate" in warnings[0]["message"]
    assert warnings[0]["ids"] == ["m"] and not fallback
    assert mesh["vertices"].tolist() == CUBE_V                 # the unused vertex 8 is removed
    V2, f2, old = compact_vertices(np.array([[0, 0, 0], [9, 9, 9], [1, 0, 0], [0, 1, 0]], float), [[3, 2, 0]])
    assert V2.tolist() == [[0, 0, 0], [1, 0, 0], [0, 1, 0]] and f2 == [[2, 1, 0]] and old.tolist() == [0, 2, 3]


# --- triangles (step 4) --------------------------------------------------------------------------

def test_triangles_are_fans_at_the_first_vertex():
    assert triangulate([[0, 1, 2, 3, 4], [5, 6, 7]]).tolist() == [[0, 1, 2], [0, 2, 3], [0, 3, 4], [5, 6, 7]]
    assert triangulate_faces(np.array([[0, 1, 2, 3], [4, 5, 6, -1]]), np.array([4, 3])).tolist() == \
        [[0, 1, 2], [0, 2, 3], [4, 5, 6]]
    mesh, tris, *_ = prep(CUBE_V, CUBE_F)
    assert tris.tolist()[:2] == [[0, 3, 2], [0, 2, 1]] and tris.shape == (12, 3)


# --- adjacency / manifold / orientation (step 5) ---------------------------------------------------

def test_manifold_box_unchanged_and_equal_to_the_parametric_box():
    for V, F in ((CUBE_V, CUBE_F), (SPLIT_V, SPLIT_F)):
        mesh, tris, fallback, groups, warnings = prep(V, F)
        ref = box_mesh([1, 1, 1])
        assert warnings == [] and not fallback and groups == [0] * 6
        assert mesh["faces"] == ref["faces"] == CUBE_F
        for key in ("vertices", "edges", "face_normals", "edge_faces", "edge_flipped"):
            assert np.array_equal(mesh[key], ref[key]), key
        assert mesh["edge_smooth"].tolist() == [False] * 12


def test_propagation_fixes_one_flipped_face():
    F = [list(f) for f in CUBE_F]
    F[4] = [F[4][0]] + F[4][1:][::-1]
    adj = build_adjacency(F, 8)
    assert adj["manifold"] and not adj["consistent"]
    out, flipped, comps, conflict = fix_orientation(F, adj)
    assert not conflict and flipped.tolist() == [False] * 4 + [True, False] and comps == [list(range(6))]
    assert out == CUBE_F
    mesh, tris, fallback, groups, warnings = prep(CUBE_V, F)
    assert codes(warnings) == ["MESH_WINDING_FIXED"] and mesh["faces"] == CUBE_F and not fallback


def test_inside_out_box_is_flipped_by_signed_volume():
    F = [[f[0]] + f[1:][::-1] for f in CUBE_F]
    assert build_adjacency(F, 8)["consistent"]
    assert signed_volume(np.array(CUBE_V), triangulate(F)) == pytest.approx(-1.0)
    mesh, tris, fallback, groups, warnings = prep(CUBE_V, F)
    assert codes(warnings) == ["MESH_WINDING_FIXED"] and mesh["faces"] == CUBE_F
    assert signed_volume(mesh["vertices"], tris) == pytest.approx(1.0)      # triangles follow the fix
    assert point_inside_mesh(mesh["vertices"], tris, [0, 0, 0.5], 1e-9)


def hollow_box(inner_outward=False):
    outer = box_mesh([2, 2, 2])
    inner = box_mesh([1, 1, 1])
    V = outer["vertices"].tolist() + [[x, y, z + 0.5] for x, y, z in inner["vertices"].tolist()]
    if inner_outward:
        F_in = [[v + 8 for v in f] for f in inner["faces"]]
    else:
        F_in = [[f[0] + 8] + [v + 8 for v in f[1:]][::-1] for f in inner["faces"]]
    return V, [list(f) for f in outer["faces"]] + F_in


def test_hollow_box_keeps_the_inverted_cavity_shell():
    V, F = hollow_box()
    mesh, tris, fallback, groups, warnings = prep(V, F)
    assert warnings == [] and not fallback and mesh["faces"] == F
    assert not point_inside_mesh(mesh["vertices"], tris, [0, 0, 1.0], 1e-9)     # the light in the cavity
    assert point_inside_mesh(mesh["vertices"], tris, [0.75, 0.75, 1.0], 1e-9)   # inside the wall
    assert winding_number(mesh["vertices"], tris, [0, 0, 1.0]) == pytest.approx(0.0, abs=1e-12)
    # a cavity shell authored outward is flipped inward (nesting depth 1 -> odd -> inward)
    V, F_out = hollow_box(inner_outward=True)
    mesh, tris, fallback, groups, warnings = prep(V, F_out)
    assert codes(warnings) == ["MESH_WINDING_FIXED"] and mesh["faces"] == F
    assert not point_inside_mesh(mesh["vertices"], tris, [0, 0, 1.0], 1e-9)


def test_zero_volume_component_keeps_its_orientation():
    # a closed zero-volume sheet (two coincident-vertex triangles back to back) next to a box
    V = CUBE_V + [[3, 0, 0], [4, 0, 0], [3, 1, 0]]
    F = CUBE_F + [[8, 9, 10], [8, 10, 9]]
    adj = build_adjacency(F, 11)
    assert adj["manifold"]
    mesh, tris, fallback, groups, warnings = prep(V, F)
    assert warnings == [] and not fallback


def mobius(n=8):
    V, F = [], []
    for k in range(n):
        t = 2 * math.pi * k / n
        for s in (-0.3, 0.3):
            r = 1 + s * math.cos(t / 2)
            V.append([r * math.cos(t), r * math.sin(t), s * math.sin(t / 2)])
    for k in range(n):
        a, b = 2 * k, 2 * k + 1
        if k < n - 1:
            c, d = 2 * k + 2, 2 * k + 3
        else:
            c, d = 1, 0                       # the half twist
        F.append([a, c, d, b])
    return V, F


def klein(N=6, M=4):
    """Closed, every edge on exactly two faces, not orientable (twisted identification)."""
    def vid(i, j):
        if i == N:
            i, j = 0, (M - j) % M
        return i * M + (j % M)
    V = []
    for i in range(N):
        u = 2 * math.pi * i / N
        for j in range(M):
            w = 2 * math.pi * j / M
            r = 2 + math.cos(w)
            V.append([r * math.cos(u), r * math.sin(u), math.sin(w) + 0.1 * i])
    F = [[vid(i, j), vid(i + 1, j), vid(i + 1, j + 1), vid(i, j + 1)] for i in range(N) for j in range(M)]
    return V, F


def test_mobius_strip_is_not_manifold():
    V, F = mobius()
    mesh, tris, fallback, groups, warnings = prep(V, F)
    assert fallback and codes(warnings) == ["MESH_NON_MANIFOLD"]
    assert "inconsistent winding" not in warnings[0]["message"] and "with 1 face" in warnings[0]["message"]


def test_klein_bottle_connectivity_is_inconsistent_winding():
    V, F = klein()
    adj = build_adjacency(F, len(V))
    assert adj["manifold"]
    _out, _flipped, _comps, conflict = fix_orientation(F, adj)
    assert conflict
    mesh, tris, fallback, groups, warnings = prep(V, F)
    assert fallback and codes(warnings) == ["MESH_NON_MANIFOLD"]
    assert "inconsistent winding" in warnings[0]["message"]


def test_open_box_takes_the_fallback_mesh():
    F = [[4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    mesh, tris, fallback, groups, warnings = prep(CUBE_V, F)
    assert fallback and codes(warnings) == ["MESH_NON_MANIFOLD"]
    assert "4 edge(s) with 1 face" in warnings[0]["message"]
    assert mesh["faces"] == F and mesh["edge_smooth"].tolist() == [False] * 12
    edges = mesh["edges"].tolist()
    ef = dict(zip(map(tuple, edges), mesh["edge_faces"].tolist()))
    assert ef[(0, 1)] == [1, 1] and ef[(4, 5)] == [0, 1] and ef[(0, 4)] == [1, 4]
    fl = dict(zip(map(tuple, edges), mesh["edge_flipped"].tolist()))
    assert fl[(4, 5)] == [False, True] and fl[(0, 4)] == [True, False]
    assert np.allclose(mesh["face_normals"][0], [0, 0, 1]) and tris.shape == (10, 3)
    ref = fallback_mesh(np.array(CUBE_V), F, ["v%d" % k for k in range(8)])
    assert ref["edges"].tolist() == edges


# --- coplanar merge (step 6) ---------------------------------------------------------------------

def test_triangulated_box_merges_into_the_six_parametric_quads():
    W, faces, _ = weld_vertices(SPLIT_V, SPLIT_F, 1e-6)
    adj = build_adjacency(faces, 8)
    normals = meshprep.face_normals_newell(W, faces)
    merged, origin = merge_coplanar(W, faces, normals, adj, math.cos(COPLANAR_TOL_RAD))
    assert merged == CUBE_F and origin == [0, 2, 4, 6, 8, 10]
    # seed start vertices 0, 4, 0, 1, 2, 3 (the seeds' first vertices, all on their region boundary)
    assert [f[0] for f in merged] == [0, 4, 0, 1, 2, 3]


def test_reoriented_split_box_merges_into_the_six_parametric_quads():
    """The merge must read the edges of the oriented faces, not of the input faces."""
    inside_out = [[f[0]] + f[1:][::-1] for f in SPLIT_F]
    one = [list(f) for f in SPLIT_F]
    one[4] = [one[4][0]] + one[4][1:][::-1]
    for F in (inside_out, one):
        mesh, tris, fallback, groups, warnings = prep(SPLIT_V, F)
        assert codes(warnings) == ["MESH_WINDING_FIXED"] and not fallback
        assert mesh["faces"] == CUBE_F and mesh["edge_smooth"].tolist() == [False] * 12
        assert signed_volume(mesh["vertices"], tris) == pytest.approx(1.0)


def fan_prism(n=16, r=1.0, h=2.0):
    """A 16-gon prism whose caps are centre fans: vertices bottom ring 0..n-1, top ring n..2n-1,
    bottom centre 2n, top centre 2n+1; faces: bottom fan, top fan, side quads."""
    ring = [[r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n)] for k in range(n)]
    V = [[x, y, 0.0] for x, y in ring] + [[x, y, h] for x, y in ring] + [[0.0, 0.0, 0.0], [0.0, 0.0, h]]
    cb, ct = 2 * n, 2 * n + 1
    F = [[cb, (k + 1) % n, k] for k in range(n)]
    F += [[ct, n + k, n + (k + 1) % n] for k in range(n)]
    F += [[k, (k + 1) % n, n + (k + 1) % n, n + k] for k in range(n)]
    return V, F


def test_centre_fan_cap_starts_at_the_first_boundary_vertex_of_the_seed_and_keeps_the_centre():
    V, F = fan_prism()
    mesh, tris, fallback, groups, warnings = prep(V, F)
    assert warnings == [] and not fallback
    assert len(mesh["faces"]) == 2 + 16
    # bottom seed [32, 1, 0]: its first vertex (the centre) is interior, the start is vertex 1
    assert mesh["faces"][0] == [1, 0] + list(range(15, 1, -1))
    assert mesh["faces"][1] == list(range(16, 32))           # top seed [33, 16, 17]: start 16
    assert mesh["vertices"].shape[0] == 34                    # centre vertices kept ...
    used = set(np.asarray(mesh["edges"]).ravel().tolist())
    assert 32 not in used and 33 not in used                  # ... without edges
    assert tris.shape == (16 + 16 + 32, 3) and 32 in tris.ravel().tolist()
    # 16 lateral edges are smooth (22.5 deg < 30 deg), all cap edges feature
    smooth = dict(zip(map(tuple, mesh["edges"].tolist()), mesh["edge_smooth"].tolist()))
    assert all(smooth[(k, k + 16)] for k in range(16))
    assert sum(smooth.values()) == 16


def boss_box():
    """A 4x4x1 box with a 1x1x1 boss on top: the top face is a square ring of 8 triangles (a region
    with a hole), the boss top is a quad, everything closed."""
    o = [[-2, -2, 1], [2, -2, 1], [2, 2, 1], [-2, 2, 1]]
    i = [[-.5, -.5, 1], [.5, -.5, 1], [.5, .5, 1], [-.5, .5, 1]]
    it = [[x, y, 2] for x, y, _ in i]
    ob = [[x, y, 0] for x, y, _ in o]
    V = [list(map(float, p)) for p in o + i + it + ob]      # o 0..3, i 4..7, it 8..11, ob 12..15
    ring = []
    for k in range(4):
        a, b = k, (k + 1) % 4
        ring += [[a, b, 4 + b], [a, 4 + b, 4 + a]]
    F = ring                                                 # faces 0..7: the ring (8 triangles)
    F += [[8, 9, 10, 11]]                                    # boss top
    F += [[4 + k, 4 + (k + 1) % 4, 8 + (k + 1) % 4, 8 + k] for k in range(4)]     # boss walls
    F += [[12, 15, 14, 13]]                                  # bottom
    F += [[12 + k, 12 + (k + 1) % 4, (k + 1) % 4, k] for k in range(4)]           # outer walls
    return V, F


def test_square_ring_region_with_a_hole_is_left_unmerged():
    V, F = boss_box()
    mesh, tris, fallback, groups, warnings = prep(V, F)
    assert warnings == [] and not fallback
    assert mesh["faces"][:8] == F[:8] and len(mesh["faces"]) == len(F)
    # the ring's interior edges are coplanar, hence smooth (also at smooth_angle_deg = 0, SMOOTH_BAND)
    for smooth_deg in (30.0, 0.0):
        mesh, *_ = prep(V, F, smooth=smooth_deg)
        smooth = dict(zip(map(tuple, mesh["edges"].tolist()), mesh["edge_smooth"].tolist()))
        interior = [(min(a, b), max(a, b)) for a, b in [(0, 5), (1, 5), (1, 6), (2, 6), (2, 7), (3, 7), (3, 4), (0, 4)]]
        assert all(smooth[e] for e in interior)
        assert sum(smooth.values()) == 8


def test_bent_strip_regions_on_merge_coplanar():
    n, theta = 20, 1.5e-4
    V = np.array([[0.5 * k, float(k % 2), 0.0] for k in range(n + 2)])
    F = [[k, k + 1, k + 2] if k % 2 == 0 else [k + 1, k, k + 2] for k in range(n)]
    normals = np.array([[math.sin(k * theta), 0.0, math.cos(k * theta)] for k in range(n)])
    adj = build_adjacency(F, n + 2)
    merged, origin = merge_coplanar(V, F, normals, adj, math.cos(COPLANAR_TOL_RAD))
    assert origin == [0, 7, 14] and len(merged) == 3
    assert sorted(merged[0]) == list(range(0, 9)) and sorted(merged[1]) == list(range(7, 16))
    assert sorted(merged[2]) == list(range(14, 22))
    assert merged[0][0] == 0 and merged[1][0] == 8 and merged[2][0] == 14     # first seed vertex on the boundary


def test_merged_faces_take_the_seed_smoothing_group():
    groups = [5, 5, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4]
    mesh, tris, fallback, out_groups, warnings = prep(SPLIT_V, SPLIT_F, groups=groups)
    assert out_groups == [5, 0, 1, 2, 3, 4]


# --- edge classification (step 7) ----------------------------------------------------------------

def test_classify_edges_with_and_without_smoothing_groups():
    ref = prism_mesh([[math.cos(2 * math.pi * k / 16), math.sin(2 * math.pi * k / 16)] for k in range(16)], 2.0)
    lateral = np.array([(i + 16 == j) for i, j in ref["edges"].tolist()])
    # no groups: the 30 deg angle rule (22.5 deg lateral -> smooth, 90 deg cap edges -> feature)
    smooth = classify_edges(ref, 30.0, [0] * 18)
    assert np.array_equal(smooth, lateral)
    assert not np.any(classify_edges(ref, 20.0, [0] * 18))
    assert np.array_equal(classify_edges(ref, 90.0, [0] * 18), np.ones(48, dtype=bool))   # 90 deg within the band
    # groups: same non-zero group -> smooth whatever the angle; group vs no group -> feature
    g = [0, 0] + [1] * 16
    assert np.array_equal(classify_edges(ref, 0.0, g), lateral)
    g = [7, 7] + [7] * 16
    assert np.all(classify_edges(ref, 0.0, g))
    # different non-zero groups -> feature even for small dihedral angles
    g = [0, 0] + [1, 2] * 8
    assert not np.any(classify_edges(ref, 30.0, g))
    g = [0, 0] + [1] * 8 + [0] * 8                     # group 1 vs group 0 -> feature
    s = classify_edges(ref, 30.0, g)
    assert s.sum() == 7 + 7                            # 7 edges inside each half (group 1 / group 0)


def test_inherit_edge_smooth_on_a_clipped_mesh():
    from castplane.shadow import clip_mesh_to_plane
    V, F = fan_prism()
    mesh, *_ = prep(V, F)
    m = dict(mesh)
    m["vertices"] = mesh["vertices"] - np.array([0, 0, 1.0])          # half buried
    clipped, origins = clip_mesh_to_plane(m, np.array([0, 0, 1.0, 0]), 1e-9)
    flags = inherit_edge_smooth(clipped, origins, mesh, mesh["edge_smooth"])
    for (a, b), s in zip(clipped["edges"].tolist(), flags.tolist()):
        oa, ob = origins[a], origins[b]
        if isinstance(oa, tuple) and isinstance(ob, tuple):
            assert not s                                    # cut-face edge: feature
        elif isinstance(oa, tuple) or isinstance(ob, tuple):
            cross, v = (oa, ob) if isinstance(oa, tuple) else (ob, oa)
            if cross[1] + 16 == cross[2] and v in cross[1:]:
                assert s                                    # part of a smooth lateral edge
        else:
            k = mesh["edges"].tolist().index([min(oa, ob), max(oa, ob)])
            assert s == bool(mesh["edge_smooth"][k])
    assert flags.sum() == 16


# --- point_inside_mesh (step 8) ------------------------------------------------------------------

def test_point_inside_mesh():
    mesh, tris, *_ = prep(CUBE_V, CUBE_F)
    V = mesh["vertices"]
    assert point_inside_mesh(V, tris, [0, 0, 0.5], 1e-9)
    assert winding_number(V, tris, [0, 0, 0.5]) == pytest.approx(1.0)
    assert not point_inside_mesh(V, tris, [0, 0, 1.5], 1e-9)
    assert not point_inside_mesh(V, tris, [2, 0.1, 0.5], 1e-9)
    # on a face within tol: outside (as _point_in_polygon_margin); just beyond tol: inside
    assert winding_number(V, tris, [0, 0, 1.0]) == pytest.approx(0.5)
    assert not point_inside_mesh(V, tris, [0, 0, 1.0 - 0.5e-9], 1e-9)
    assert not point_inside_mesh(V, tris, [0.5 - 1e-10, 0.2, 0.3], 1e-9)
    assert point_inside_mesh(V, tris, [0, 0, 1.0 - 2e-9], 1e-9)
    # the |w| > 0.75 rule: one missing face (w = 5/6) is still inside, two missing faces (w = 2/3) not
    t5 = triangulate(CUBE_F[:5])
    t4 = triangulate(CUBE_F[:4])
    assert winding_number(V, t5, [0, 0, 0.5]) == pytest.approx(5 / 6)
    assert point_inside_mesh(V, t5, [0, 0, 0.5], 1e-9)
    assert not point_inside_mesh(V, t4, [0, 0, 0.5], 1e-9)
    # orientation-free: an inside-out surface gives w = -1, still inside
    inv = triangulate([[f[0]] + f[1:][::-1] for f in CUBE_F])
    assert winding_number(V, inv, [0, 0, 0.5]) == pytest.approx(-1.0)
    assert point_inside_mesh(V, inv, [0, 0, 0.5], 1e-9)


def test_preprocess_without_a_usable_face_raises_a_clear_error():
    # unreachable on a validated scene (the usable-face check of validate_mesh_data); direct calls only
    for scale, weld in ((1.0, 10.0), (1e-7, WELD_TOLERANCE_DEFAULT)):
        with pytest.raises(ValueError, match="no usable face"):
            prep(CUBE_V, CUBE_F, scale=scale, weld=weld)


def test_preprocess_is_deterministic_and_does_not_mutate_its_input():
    V, F = fan_prism()
    data = {"vertices": [list(v) for v in V], "faces": [list(f) for f in F]}
    a = preprocess_mesh(data, 1.0, 1e-6, 30.0, "m")
    b = preprocess_mesh(data, 1.0, 1e-6, 30.0, "m")
    assert data == {"vertices": V, "faces": F}
    for key in ("vertices", "edges", "face_normals", "edge_faces", "edge_smooth"):
        assert np.array_equal(a[0][key], b[0][key])
    assert np.array_equal(a[1], b[1]) and a[2:] == b[2:]


def test_scale_is_applied_before_the_weld():
    mm = [[1000 * c for c in v] for v in CUBE_V]
    mesh, *_ = prep(mm, CUBE_F, scale=0.001)
    assert np.allclose(mesh["vertices"], CUBE_V, rtol=0, atol=1e-15)
    near = [list(v) for v in CUBE_V] + [[-.5 + 5e-7, -.5, 0.0]]
    mesh, _t, _fb, _g, warnings = prep(near, [[8, 3, 2, 1]] + CUBE_F[1:])
    assert mesh["faces"][0] == [0, 3, 2, 1] and warnings == []
    assert mesh_from_faces(mesh["vertices"], mesh["faces"])["edges"].shape == (12, 2)


def test_preprocess_mesh_return_scale_and_prepared_mesh_reuse_it(monkeypatch):
    """``preprocess_mesh(..., return_scale=True)`` appends the ``scale_A`` its steps used; the 5-tuple
    form is unchanged, and :func:`castplane.primitives.prepared_mesh` takes the value from there
    instead of converting the vertices a second time."""
    from castplane import primitives
    data = {"vertices": [[3 * c for c in v] for v in SPLIT_V], "faces": SPLIT_F}
    five = meshprep.preprocess_mesh(data, 2.0, 1e-6, 30.0, "m")
    six = meshprep.preprocess_mesh(data, 2.0, 1e-6, 30.0, "m", return_scale=True)
    assert len(five) == 5 and len(six) == 6 and six[5] == 6.0
    assert six[0]["faces"] == five[0]["faces"] and six[1].tolist() == five[1].tolist()
    calls = []
    real = meshprep.mesh_scale
    monkeypatch.setattr(meshprep, "mesh_scale", lambda V: calls.append(1) or real(V))
    rec = primitives.prepared_mesh({"id": "m", "type": "mesh", "data": data, "scale": 2.0})
    assert rec["scale_A"] == 6.0 and len(calls) == 1


def test_has_usable_face_is_the_validation_guard():
    assert meshprep.has_usable_face(CUBE_V, CUBE_F, 1.0, 1e-6)
    # every face collapses under a weld tolerance larger than the box
    assert not meshprep.has_usable_face(CUBE_V, CUBE_F, 1.0, 10.0)
    # a single sliver whose Newell norm is below 1e-12 * scale_A^2
    assert not meshprep.has_usable_face([[0, 0, 0], [1, 0, 0], [2, 1e-14, 0]], [[0, 1, 2]], 1.0, 0.0)
    import inspect
    from castplane import scene
    src = inspect.getsource(scene)
    assert "import numpy" not in src and "np." not in src          # one import style: scene.py stays numpy-free


def test_usage_states_the_smoothing_group_rule_of_classify_edges():
    """m5-mesh#2: inside one non-zero smoothing group every edge is smooth whatever the dihedral angle
    (contract §5.2.3 step 7, D36); docs/USAGE.md must say so instead of "angle below AND same group"."""
    import pathlib

    from castplane.mesh import cylinder_mesh

    cyl = cylinder_mesh(1.0, 1.0, 16)
    data = {"vertices": cyl["vertices"].tolist(), "faces": cyl["faces"], "smooth_groups": [1] * len(cyl["faces"])}
    mesh = preprocess_mesh(data, 1.0, 1e-6, 30.0, "m")[0]
    assert bool(mesh["edge_smooth"].all())                     # incl. the 90-degree cap rims
    data["smooth_groups"] = [0] * len(cyl["faces"])
    assert int(preprocess_mesh(data, 1.0, 1e-6, 30.0, "m")[0]["edge_smooth"].sum()) == 16
    usage = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "USAGE.md").read_text(encoding="utf-8")
    row = next(line for line in usage.splitlines() if line.startswith("| `smooth_angle_deg` |"))
    assert "（且平滑群組相同）" not in row
    assert "同一個非零平滑群組的邊一律平滑" in row and "兩面都無群組時" in row


@pytest.mark.parametrize("far", [1e6, 1e7, 1e12])
def test_an_unused_far_vertex_does_not_widen_scale_a(far):
    """m5-mesh#1: ``scale_A`` is the bbox of the vertices used by a face; a stray vertex (dropped by
    the weld's compaction, absent from the record bbox) must not make validation reject a unit box
    ("no usable face") nor loosen the tolerances."""
    import copy
    import json
    import pathlib

    from castplane import load_scene, render

    stray = CUBE_V + [[far, 0.0, 0.0]]
    out = preprocess_mesh({"vertices": stray, "faces": CUBE_F}, 1.0, 1e-6, 30.0, "m", return_scale=True)
    assert out[5] == 1.0 and out[4] == []
    assert meshprep.has_usable_face(stray, CUBE_F, 1.0, 1e-6)
    base = json.loads((pathlib.Path(__file__).resolve().parents[1] / "tests" / "conformance" / "cases"
                       / "analytic_unit_box_point_light_overhead.json").read_text(encoding="utf-8"))
    docs = []
    for verts in (CUBE_V, stray):
        sc = copy.deepcopy(base)
        sc["objects"] = [{"id": "m", "type": "mesh", "data": {"vertices": verts, "faces": CUBE_F}}]
        docs.append(render(load_scene(sc))["geometry"])
    assert docs[0] == docs[1]
