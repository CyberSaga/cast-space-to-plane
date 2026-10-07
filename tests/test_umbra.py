"""The umbra scanline kernel of contract §5.3.4 (M6): ``record_pieces`` table of §5.3.10, the
intersection scan, determinism and the geometric properties of the pieces."""

import json
import math

import numpy as np
import pytest

from castplane.umbra import record_pieces, scan_pieces, tolerances, umbra_from_document, umbra_pieces

CANVAS = [360.0, 240.0]
TOL_MM, TOL_AREA = tolerances(CANVAS)


def area(piece) -> float:
    p = np.asarray(piece, dtype=float)
    u, v = p[:, 0], p[:, 1]
    return float(0.5 * np.sum(u * np.roll(v, -1) - np.roll(u, -1) * v))


def total(pieces) -> float:
    return sum(area(p) for p in pieces)


def assert_convex_ccw(piece):
    p = np.asarray(piece, dtype=float)
    assert p.shape[0] in (3, 4)
    assert area(p) > TOL_AREA
    n = p.shape[0]
    scale = max(1.0, float(np.abs(p).max()))
    for k in range(n):
        a, b, c = p[k], p[(k + 1) % n], p[(k + 2) % n]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        assert cross >= -1e-12 * scale * scale, (piece, k, cross)


def assert_canonical_start(piece):
    p = np.asarray(piece, dtype=float)
    vmin = p[:, 1].min()
    cand = np.flatnonzero(p[:, 1] <= vmin + TOL_MM)
    umin = p[cand, 0].min()
    cand = cand[p[cand, 0] <= umin + TOL_MM]
    assert cand[0] == 0, piece


def winding(points: np.ndarray, poly) -> np.ndarray:
    """Winding number of every point about the closed polygon (vectorised crossing count)."""
    P = np.asarray(poly, dtype=float)
    Q = np.roll(P, -1, axis=0)
    x, y = points[:, 0:1], points[:, 1:2]
    up = (P[None, :, 1] <= y) & (Q[None, :, 1] > y)
    down = (P[None, :, 1] > y) & (Q[None, :, 1] <= y)
    side = (Q[None, :, 0] - P[None, :, 0]) * (y - P[None, :, 1]) - (x - P[None, :, 0]) * (Q[None, :, 1] - P[None, :, 1])
    return (np.where(up & (side > 0), 1, 0) - np.where(down & (side < 0), 1, 0)).sum(axis=1)


def nonzero_mask(points, polygons) -> np.ndarray:
    w = np.zeros(points.shape[0], dtype=int)
    for poly in polygons:
        w += winding(points, poly)
    return w != 0


def grid(u0, u1, v0, v1, nu, nv):
    us = u0 + (np.arange(nu) + 0.5) * (u1 - u0) / nu
    vs = v0 + (np.arange(nv) + 0.5) * (v1 - v0) / nv
    U, V = np.meshgrid(us, vs)
    return np.stack([U.ravel(), V.ravel()], axis=1), (u1 - u0) * (v1 - v0) / (nu * nv)


def pieces_mask(points, pieces) -> np.ndarray:
    m = np.zeros(points.shape[0], dtype=int)
    for piece in pieces:
        m += winding(points, piece) != 0
    assert m.max(initial=0) <= 1, "pieces overlap"
    return m == 1


SQUARE = [[0, 0], [1, 0], [1, 1], [0, 1]]


# --- tolerances ----------------------------------------------------------------

def test_tolerances_derive_from_the_canvas():
    tol_mm, tol_area = tolerances([360, 240])
    assert tol_mm == 1e-9 * 540.0
    assert tol_area == 1e-9 * (540.0 * 540.0)
    assert tol_mm < 1e-6                                   # below the conformance tolerance (§5.3.7)
    assert tolerances([100, 400]) == (1e-9 * 600.0, 1e-9 * 360000.0)


# --- record_pieces: the table of §5.3.10 ------------------------------------------

@pytest.mark.parametrize("loop", [SQUARE, SQUARE[::-1]])
def test_square_one_piece_either_orientation(loop):
    pieces, sides = record_pieces([loop], TOL_MM, TOL_AREA)
    assert len(pieces) == 1 and sides.shape == (1, 2)
    assert area(pieces[0]) == 1.0
    assert pieces[0].tolist() == [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


def test_two_overlapping_squares_one_record():
    second = [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5]]
    pieces, _ = record_pieces([SQUARE, second], TOL_MM, TOL_AREA)
    assert len(pieces) == 3
    assert total(pieces) == pytest.approx(1.75, abs=1e-12)


def test_square_with_reversed_inner_square_is_a_hole():
    hole = [[0.25, 0.25], [0.25, 0.75], [0.75, 0.75], [0.75, 0.25]]
    pieces, _ = record_pieces([SQUARE, hole], TOL_MM, TOL_AREA)
    assert len(pieces) == 4
    assert total(pieces) == pytest.approx(0.75, abs=1e-12)


def test_bow_tie_nonzero_area():
    pieces, _ = record_pieces([[[0, 0], [2, 2], [2, 0], [0, 2]]], TOL_MM, TOL_AREA)
    assert total(pieces) == pytest.approx(2.0, abs=1e-12)
    for p in pieces:
        assert_convex_ccw(p)


C_LOOP = [(3, 3), (0, 3), (0, 0), (4, 0), (7, 0), (7, 1), (3, 1), (1, 1), (5, 0.96), (5, 1.96), (7, 1.96), (7, 2.96)]


def test_c_shaped_sweep_loop_four_pieces():
    pieces, _ = record_pieces([C_LOOP], TOL_MM, TOL_AREA)
    assert len(pieces) == 4
    assert pieces[0].tolist() == [[0.0, 0.0], [7.0, 0.0], [7.0, 1.0], [0.0, 1.0]]
    assert pieces[1].tolist() == [[0.0, 1.0], [5.0, 1.0], [5.0, 1.96], [0.0, 1.96]]
    assert pieces[2].tolist() == [[0.0, 1.96], [7.0, 1.96], [7.0, 2.96], [0.0, 2.96]]
    assert pieces[3].tolist() == [[0.0, 2.96], [7.0, 2.96], [3.0, 3.0], [0.0, 3.0]]     # the top trapezoid
    assert total(pieces) == pytest.approx(19.0, abs=1e-12)
    pts, cell = grid(0, 7, 0, 3, 700, 300)
    raster = nonzero_mask(pts, [C_LOOP]).sum() * cell
    assert abs(raster - 19.0) <= 0.005 * 19.0


def _boundary_v_distance(vertex, loop) -> float:
    """Smallest ``|Δv|`` from ``vertex`` to a point of the closed loop with the same ``u``."""
    u, v = vertex
    P = np.asarray(loop, dtype=float)
    best = math.inf
    for k in range(P.shape[0]):
        (u0, v0), (u1, v1) = P[k], P[(k + 1) % P.shape[0]]
        if u0 == u1:
            if u == u0:
                best = min(best, max(0.0, min(v0, v1) - v, v - max(v0, v1)))
        elif min(u0, u1) <= u <= max(u0, u1):
            best = min(best, abs(v0 + (u - u0) * (v1 - v0) / (u1 - u0) - v))
    return best


@pytest.mark.parametrize("loop", [
    [(-250, 0), (250, 1.5 * TOL_MM), (250, 100), (-250, 100)],                                   # sliver
    [(-250, 0), (0, 0), (250, 0.7 * TOL_MM), (250, 1.2 * TOL_MM), (250, 100), (-250, 100)],       # merged vertex
])
def test_sliver_and_merged_vertex_cases(loop):
    pieces, _ = record_pieces([loop], TOL_MM, TOL_AREA)
    assert pieces
    assert abs(total(pieces) - abs(area(loop))) <= TOL_AREA
    u_lo, u_hi = min(p[0] for p in loop), max(p[0] for p in loop)
    for piece in pieces:
        assert_convex_ccw(piece)
        assert_canonical_start(piece)
        assert piece[:, 0].min() >= u_lo and piece[:, 0].max() <= u_hi
        for vertex in piece:
            assert _boundary_v_distance(vertex, loop) <= TOL_MM * (1 + 1e-9)


def test_bow_tie_guard_per_end_clamp():
    """A crossing merged into a slab boundary (within tol_mm of the vertex event v = 0) must not
    produce a bow-tie piece: the per-end clamp keeps every piece convex and CCW."""
    def on_flat(v):                     # the nearly horizontal line through (50 + 2.5 tol, tol/2), du/dv = -1e5
        return (50.0 + 2.5 * TOL_MM - 1e5 * (v - TOL_MM / 2), v)
    # a bow-tie loop whose two crossing edges are (0,-10) -> (100,10) and the nearly horizontal edge;
    # they cross at v ~ tol/2, so the crossing event is dropped next to the vertex event v = 0 of
    # the second loop, and in the slab [0, 5e-4] the two edges bounding the inside interval swap
    # order between the slab's ends
    bow = [(0.0, -10.0), (100.0, 10.0), on_flat(5e-4), on_flat(-5e-4)]
    square = [(200.0, 0.0), (201.0, 0.0), (201.0, 1.0), (200.0, 1.0)]          # the vertex at v = 0
    for loops in ([bow, square], [square, bow], [bow[::-1], square]):
        pieces, _ = record_pieces(loops, TOL_MM, TOL_AREA)
        assert pieces
        for piece in pieces:
            assert_convex_ccw(piece)
            assert_canonical_start(piece)
        # the clamped piece of the slab [0, 5e-4]: bottom from the steep edge (u = 50) to the flat one
        clamped = [p for p in pieces if p[0, 1] == 0.0 and p[0, 0] == 50.0]
        assert len(clamped) == 1 and clamped[0].shape[0] == 4
        assert clamped[0][1, 0] == pytest.approx(on_flat(0.0)[0], abs=1e-12)
        pts, cell = grid(-1, 201, -10, 10, 808, 400)
        assert abs(pieces_mask(pts, pieces).sum() - nonzero_mask(pts, loops).sum()) * cell <= 0.01 * total(pieces)
    # the configuration without the bow-tie: the crossing edges bound different pieces
    steep = [(0.0, -10.0), (100.0, 10.0), (-100.0, 10.0)]
    flat = [on_flat(-5e-4), on_flat(5e-4), (-50.0, -20.0), (200.0, 0.0)]
    for piece in record_pieces([steep, flat], TOL_MM, TOL_AREA)[0]:
        assert_convex_ccw(piece)


def test_degenerate_inputs_give_no_pieces():
    assert record_pieces([], TOL_MM, TOL_AREA)[0] == []
    assert record_pieces([[[0, 0], [1, 1]]], TOL_MM, TOL_AREA)[0] == []                 # < 3 vertices: ignored
    assert record_pieces([[[0, 0], [1, 0], [2, 0]]], TOL_MM, TOL_AREA)[0] == []         # zero area
    assert record_pieces([[[0, 0], [1, 1], [2, 2], [1, 1]]], TOL_MM, TOL_AREA)[0] == []
    pieces, sides = record_pieces([[[0, 0], [1, 0], [1, 1e-9]]], TOL_MM, TOL_AREA)    # area <= tol_area: dropped
    assert pieces == [] and sides.shape == (0, 2)


def test_determinism_same_bytes():
    rng = np.random.default_rng(7)
    loops = [rng.random((12, 2)) * 50 for _ in range(3)]
    runs = [json.dumps([p.tolist() for p in record_pieces(loops, TOL_MM, TOL_AREA)[0]]) for _ in range(2)]
    assert runs[0] == runs[1]
    per_light = [[[loops[0]], [loops[1]]], [[loops[2]]]]
    assert json.dumps(umbra_pieces(per_light, CANVAS)) == json.dumps(umbra_pieces(per_light, CANVAS))


def test_emitted_floats_are_canonical():
    pieces = umbra_pieces([[[[[-1, -1], [1, -1], [1, 1], [-1, 1]]]], [[[[0, 0], [2, 0], [2, 2], [0, 2]]]]], CANVAS)
    for piece in pieces:
        for u, v in piece:
            assert type(u) is float and type(v) is float
            assert math.copysign(1.0, u) == 1.0 or u != 0.0
            assert math.copysign(1.0, v) == 1.0 or v != 0.0


# --- the intersection scan -----------------------------------------------------------

def test_umbra_pieces_two_lights_hand_polygons():
    shifted = [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5]]
    pieces = umbra_pieces([[[SQUARE]], [[shifted]]], CANVAS)
    assert pieces == [[[0.5, 0.5], [1.0, 0.5], [1.0, 1.0], [0.5, 1.0]]]
    assert area(pieces[0]) == 0.25
    disjoint = [[2.5, 0.5], [3.5, 0.5], [3.5, 1.5], [2.5, 1.5]]
    assert umbra_pieces([[[SQUARE]], [[disjoint]]], CANVAS) == []
    assert umbra_pieces([[[SQUARE]]], CANVAS) == []                     # fewer than two active lights
    assert umbra_pieces([], CANVAS) == []
    assert umbra_pieces([[[SQUARE]], []], CANVAS) == []                 # an active light without records


def test_reversed_loop_of_one_record_does_not_cancel_another_record():
    """Record pieces are all CCW, so within one light the counters add: a clockwise record (a
    camera below the receiver reverses every drawable) still counts as shadow."""
    big = [[0, 0], [4, 0], [4, 4], [0, 4]]
    other = [[1, 1], [1, 3], [3, 3], [3, 1]]                            # clockwise, a separate record
    pieces = umbra_pieces([[[big], [other]], [[big]]], CANVAS)
    assert total(pieces) == pytest.approx(16.0, abs=1e-12)
    pieces = umbra_pieces([[[big[::-1]]], [[other]]], CANVAS)
    assert total(pieces) == pytest.approx(4.0, abs=1e-12)


# the acceptance drawables of §5.3.10 (multilight_two_point_symmetric_box): `west` as written in the
# contract, `east` its mirror in u (the scene is symmetric about the camera's vertical plane)
WEST = [(-22.944417207498113, 12.727272727272727), (-25.753937681885635, -14.285714285714285),
        (54.86708462662592, -30.43478260869565), (164.60125387987776, -30.43478260869565),
        (130.54582204266168, 24.137931034482758), (43.51527401422056, 24.137931034482758)]
EAST = [(-u, v) for u, v in WEST][::-1]
EXPECTED = [
    [(0.0, -19.444444444444443), (25.753937681885635, -14.285714285714285), (-25.753937681885635, -14.285714285714285)],
    [(-25.753937681885635, -14.285714285714285), (25.753937681885635, -14.285714285714285),
     (22.944417207498113, 12.727272727272727), (-22.944417207498113, 12.727272727272727)],
    [(-22.944417207498113, 12.727272727272727), (22.944417207498113, 12.727272727272727), (0.0, 16.666666666666664)],
]
EXPECTED_AREAS = [132.85761502560047, 1315.4880281807557, 90.38709809014404]


@pytest.mark.parametrize("order", [("west", "east"), ("east", "west")])
def test_acceptance_pieces_from_the_hand_drawables(order):
    drawn = {"west": [[WEST]], "east": [[EAST]]}
    pieces = umbra_pieces([drawn[k] for k in order], CANVAS)
    assert len(pieces) == 3
    for piece, expected, a in zip(pieces, EXPECTED, EXPECTED_AREAS):
        assert np.allclose(piece, expected, rtol=0.0, atol=1e-6)
        assert area(piece) == pytest.approx(a, rel=1e-12)
    assert abs(pieces[2][2][0]) < 1e-13
    assert total(pieces) == pytest.approx(1538.7327412965, rel=1e-6)


def _random_star(rng, centre, n, r0, r1):
    th = np.sort(rng.random(n)) * 2 * np.pi
    r = r0 + (r1 - r0) * rng.random(n)
    return np.stack([centre[0] + r * np.cos(th), centre[1] + r * np.sin(th)], axis=1)


@pytest.mark.parametrize("seed", range(6))
def test_random_umbra_matches_the_raster_and(seed):
    """Union of the pieces = AND over the lights of the per-light nonzero union of its records;
    pieces convex, CCW, pairwise disjoint; the piece set does not depend on the light order."""
    rng = np.random.default_rng(seed)
    n_lights = 2 + seed % 2
    per_light = []
    for _ in range(n_lights):
        records = []
        for _ in range(1 + int(rng.integers(3))):
            loops = [_random_star(rng, rng.random(2) * 40 - 20, 9, 5, 25)]
            if rng.random() < 0.5:
                loops.append(rng.random((6, 2)) * 40 - 20)                  # self-intersecting loop
            records.append([lp.tolist() for lp in loops])
        per_light.append(records)
    pieces = umbra_pieces(per_light, CANVAS)
    for piece in pieces:
        assert_convex_ccw(piece)
        assert_canonical_start(piece)
    pts, cell = grid(-50, 50, -50, 50, 250, 250)
    expect = np.ones(pts.shape[0], dtype=bool)
    for records in per_light:
        lit = np.zeros(pts.shape[0], dtype=bool)
        for rec in records:
            lit |= nonzero_mask(pts, rec)
        expect &= lit
    got = pieces_mask(pts, pieces)
    union = (got | expect).sum()
    assert union == 0 or (got & expect).sum() / union >= 0.995
    assert abs(got.sum() - expect.sum()) * cell <= 0.03 * max(total(pieces), 1.0)
    permuted = umbra_pieces(per_light[::-1], CANVAS)
    assert total(permuted) == pytest.approx(total(pieces), rel=1e-9, abs=1e-9)
    assert pieces_mask(pts, permuted).tolist() == got.tolist()


def test_scan_pieces_groups_and_sides():
    """``scan_pieces`` directly: an interval is inside iff every group's counter is nonzero;
    ``sides`` are the line ids of the bounding edges."""
    a = np.array(SQUARE, dtype=float)
    b = a + 0.5
    pieces, sides = scan_pieces([a, b], [0, 0], [np.arange(4), np.arange(4, 8)], 1, TOL_MM, TOL_AREA)
    assert total(pieces) == pytest.approx(1.75)
    pieces, sides = scan_pieces([a, b], [0, 1], [np.arange(4), np.arange(4, 8)], 2, TOL_MM, TOL_AREA)
    assert [p.tolist() for p in pieces] == [[[0.5, 0.5], [1.0, 0.5], [1.0, 1.0], [0.5, 1.0]]]
    assert sides.tolist() == [[7, 1]]                     # left: b's edge (0.5,1.5)->(0.5,0.5); right: a's (1,0)->(1,1)


def test_umbra_from_document():
    doc = {"canvas_mm": CANVAS,
           "shadows": [{"light": "west", "receiver": "ground", "object": "cube", "polygons": [[list(p) for p in WEST]]},
                       {"light": "east", "receiver": "ground", "object": "cube", "polygons": [[list(p) for p in EAST]]},
                       {"light": "east", "receiver": "wall", "object": "cube", "polygons": []}],
           "umbra": [{"receiver": "ground", "lights": ["west", "east"], "polygons": None},
                     {"receiver": "wall", "lights": ["east"], "polygons": []}]}
    out = umbra_from_document(json.loads(json.dumps(doc)))
    assert [e["receiver"] for e in out] == ["ground", "wall"]
    assert out[0]["lights"] == ["west", "east"] and out[1]["polygons"] == []
    assert out[0]["polygons"] == umbra_pieces([[[[list(p) for p in WEST]]], [[[list(p) for p in EAST]]]], CANVAS)
    assert len(out[0]["polygons"]) == 3
    assert umbra_from_document({"shadows": []}) == []


def test_record_pieces_on_a_2000_edge_loop():
    """The M5 mesh case of §5.3.9 (informational timing in the benchmark): a simple 2 000-edge loop
    decomposes into convex pieces whose area equals the loop's shoelace area up to dropped slivers."""
    rng = np.random.default_rng(3)
    loop = _random_star(rng, (0.0, 0.0), 2000, 50.0, 70.0)
    pieces, sides = record_pieces([loop], TOL_MM, TOL_AREA)
    assert sides.shape == (len(pieces), 2)
    # exact up to the pieces of area <= tol_area that step 7 drops (here thin slabs at the extremes)
    assert abs(total(pieces) - abs(area(loop))) <= 10 * TOL_AREA
    for piece in pieces[::97]:
        assert_convex_ccw(piece)


# --- review fix: the chunk boundaries of the kernel never change the output -----------------

def _chunk_inputs():
    rng = np.random.default_rng(11)
    per_light = []
    for _ in range(3):
        records = []
        for _ in range(3):
            loops = [_random_star(rng, rng.random(2) * 40 - 20, 9, 5, 25).tolist(),
                     (rng.random((6, 2)) * 40 - 20).tolist()]             # one self-intersecting loop
            records.append(loops)
        per_light.append(records)
    th = np.linspace(0.0, 2 * np.pi, 41)[:-1]
    r = 30 + 20 * np.cos(7 * th)
    loop = np.stack([r * np.cos(3 * th), r * np.sin(2 * th)], axis=1)     # 40 edges, many crossings
    return per_light, loop


def _chunk_outputs(per_light, loop):
    pieces, sides = record_pieces([loop], TOL_MM, TOL_AREA)
    return (json.dumps(umbra_pieces(per_light, CANVAS)), json.dumps(umbra_pieces(per_light[:2], CANVAS)),
            json.dumps([p.tolist() for p in pieces]), sides.tolist())


@pytest.mark.parametrize("entries,pairs", [(1, 1), (2, 3), (7, 5), (64, 17), (1000, 1000)])
def test_chunk_sizes_are_invisible_in_the_output(monkeypatch, entries, pairs):
    """``_CHUNK_ENTRIES`` / ``_CHUNK_PAIRS`` only bound the size of the temporaries of the slab and
    crossing-pair loops; every chunking gives byte-identical pieces and sides."""
    import castplane.umbra as U
    per_light, loop = _chunk_inputs()
    default = _chunk_outputs(per_light, loop)
    assert len(json.loads(default[0])) > 0 and len(default[3]) > 0
    monkeypatch.setattr(U, "_CHUNK_ENTRIES", entries)
    monkeypatch.setattr(U, "_CHUNK_PAIRS", pairs)
    assert _chunk_outputs(per_light, loop) == default
