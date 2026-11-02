"""The Miki model's clearance / poke-through checks (``tools/miki_model/checks.py``, milestone 1).

Three layers:

* the exact geometry primitives in ``meshkit`` (point-triangle and triangle-triangle distance, the robust
  triangle-triangle intersection with its crossing / contact / coincident classification);
* the detector fixtures of the plan (synthetic meshes with known answers, including the degenerate-intersection
  policy: coplanar overlap, touching within eps, a crossing shorter than eps, a tolerance-sensitive verdict and a
  crossing the segment classifier cannot see);
* the checks run on the real Miki model (built once per module, as in ``test_miki_model.py``): every required
  requirement's verdict is reported, and two mutations (the collar 3 mm into the blouse, a hair root 2 mm out of
  the dome) turn their requirements to FAIL.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from miki_model import meshkit as mk  # noqa: E402

EPS = 0.5 * np.sqrt(3.0) * 1e-5          # the policy's eps for 5 decimals


def _tri_samples(T, n=60):
    """Dense barycentric samples of triangle ``T`` (3, 3)."""
    s = np.linspace(0.0, 1.0, n)
    u, v = np.meshgrid(s, s, indexing="ij")
    m = (u + v) <= 1.0
    u, v = u[m], v[m]
    return T[0] + u[:, None] * (T[1] - T[0]) + v[:, None] * (T[2] - T[0])


# ---------------------------------------------------------------------------------------------------------------
# meshkit primitives
# ---------------------------------------------------------------------------------------------------------------

def test_point_triangle_distance_matches_dense_sampling():
    rng = np.random.default_rng(7)
    V = rng.normal(size=(30, 3))
    tris = np.arange(30).reshape(10, 3)
    P = rng.normal(size=(40, 3)) * 2.0
    d, j, q = mk.point_triangle_distance(P, V, tris, chunk=37)       # tiny chunk: exercises the chunking
    for i, p in enumerate(P):
        best = min(np.min(np.linalg.norm(_tri_samples(V[t]) - p, axis=1)) for t in tris)
        assert d[i] <= best + 1e-12                                   # exact never exceeds a sampled distance
        assert d[i] >= best - 0.05                                    # and the samples come close
        assert np.isclose(np.linalg.norm(q[i] - p), d[i])
        # the foot lies on the reported triangle
        dd, _, _ = mk.point_triangle_distance(q[i], V, tris[j[i]:j[i] + 1])
        assert dd[0] < 1e-12


def test_point_triangle_distance_regions():
    V = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0]])
    tris = [[0, 1, 2]]
    P = np.array([[0.2, 0.2, 3.0],      # face
                  [-1.0, -1.0, 0.0],    # vertex A
                  [2.0, -0.5, 0.0],     # vertex B
                  [0.5, -1.0, 0.0],     # edge AB
                  [1.0, 1.0, 0.0],      # edge BC
                  [-1.0, 0.5, 0.0]])    # edge AC
    d, _, q = mk.point_triangle_distance(P, V, tris)
    np.testing.assert_allclose(d, [3.0, np.sqrt(2.0), np.sqrt(1.25), 1.0, np.sqrt(0.5), 1.0])
    np.testing.assert_allclose(q[4], [0.5, 0.5, 0.0])


def test_triangle_pair_distance_matches_sampling():
    rng = np.random.default_rng(3)
    for _ in range(20):
        A = rng.normal(size=(3, 3))
        B = rng.normal(size=(3, 3)) + rng.normal(size=3) * 3.0
        d, pa, pb = mk.triangle_pair_distance(A[None], B[None])
        r = mk.triangle_intersections(A, [[0, 1, 2]], B, [[0, 1, 2]], 1e-9)
        if len(r["kind"]) and r["kind"][0] == mk.TT_CROSSING:
            continue                                                 # crossing: the distance is 0 by definition
        SA, SB = _tri_samples(A, 30), _tri_samples(B, 30)
        best = np.min(np.linalg.norm(SA[:, None] - SB[None], axis=2))
        assert d[0] <= best + 1e-12 and d[0] >= best - 0.2
        assert np.isclose(np.linalg.norm(pa[0] - pb[0]), d[0])


def _kinds(TA, TB, eps=EPS):
    VA, VB = np.asarray(TA, float).reshape(-1, 3), np.asarray(TB, float).reshape(-1, 3)
    r = mk.triangle_intersections(VA, np.arange(len(VA)).reshape(-1, 3), VB, np.arange(len(VB)).reshape(-1, 3), eps)
    return [mk.TT_KINDS[int(k)] for k in r["kind"]], r


def test_triangle_intersection_crossing_segment():
    k, r = _kinds([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0.2, 0.2, -0.5], [0.3, 0.2, 0.5], [0.2, 0.5, 0.5]])
    assert k == ["crossing"]
    seg = sorted(map(tuple, np.round(r["seg"][0], 12)))
    np.testing.assert_allclose(seg, [(0.2, 0.35, 0.0), (0.25, 0.2, 0.0)])


def test_triangle_intersection_separated_and_touching():
    T = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
    assert _kinds(T, [[0.2, 0.2, 0.01], [0.3, 0.2, 0.5], [0.2, 0.5, 0.5]])[0] == []
    # vertex on face within eps (above and below the plane by a fraction of eps): contact, not crossing
    for dz in (0.0, 0.5 * EPS, -0.5 * EPS):
        assert _kinds(T, [[0.2, 0.2, dz], [0.3, 0.2, 0.5], [0.2, 0.5, 0.5]])[0] == ["contact"]
    # edge on face within eps
    assert _kinds(T, [[0.1, 0.1, -0.3 * EPS], [0.5, 0.1, 0.4 * EPS], [0.3, 0.2, 0.5]])[0] == ["contact"]
    # an edge-on-edge touch of two perpendicular triangles
    assert _kinds(T, [[0.5, -0.5, 0.0], [0.5, 0.5, 0.0], [0.5, 0.0, -1.0]])[0] in (["contact"], ["crossing"])


def test_triangle_intersection_short_crossing_is_a_crossing():
    """A poke whose segment is far shorter than eps is still a crossing (never dropped by length)."""
    T = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
    h = 3.0 * EPS
    # a tall thin B whose tip pokes 3 eps through A's interior: its cut is a sliver shorter than eps
    B = [[0.3, 0.3, -h], [0.299, 0.301, 1.0], [0.301, 0.299, 1.0]]
    k, r = _kinds(T, B)
    assert k == ["crossing"]
    length = np.linalg.norm(r["seg"][0, 1] - r["seg"][0, 0])
    assert 0 < length < EPS


def test_triangle_intersection_coincident():
    T = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
    k, r = _kinds(T, [[0.1, 0.1, 0.2 * EPS], [0.8, 0.1, -0.3 * EPS], [0.1, 0.8, 0.0]])
    assert k == ["coincident"]
    assert r["polys"][0].shape[0] >= 3
    # coplanar, touching only along an edge: no area, so contact
    k, _ = _kinds(T, [[0.5, 0.5, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0]])
    assert k == ["contact"]


def test_triangle_bbox_pairs_order_and_pad():
    V = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0], [1.05, 0, 0], [2, 0, 0], [1.05, 1, 0]])
    ia, ib = mk.triangle_bbox_pairs(V, [[0, 1, 2], [0, 1, 2]], V, [[3, 4, 5]], pad=0.0)
    assert len(ia) == 0
    ia, ib = mk.triangle_bbox_pairs(V, [[0, 1, 2], [0, 1, 2]], V, [[3, 4, 5]], pad=0.1)
    assert ia.tolist() == [0, 1] and ib.tolist() == [0, 0]
