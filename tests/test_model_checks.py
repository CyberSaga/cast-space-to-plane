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

import dataclasses
import json
import math
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


def _segment_distance(p, a, b):
    d = b - a
    t = 0.0 if not d @ d else float(np.clip((p - a) @ d / (d @ d), 0.0, 1.0))
    return float(np.linalg.norm(a + t * d - p))


def test_point_triangle_distance_degenerate_triangles():
    """A repeated vertex or collinear vertices: the distance is the nearest edge's, never vertex A's (review)."""
    cases = [([[-1.2, -1.0, 1.6], [-1.2, -1.0, 1.6], [-1.06, -2.19, 1.53]], [-1.7, -1.7, 2.2]),
             ([[1.0, 1.6, 0.0], [1.0, 1.6, 0.0], [1.34, 3.47, -2.04]], [1.3, 1.7, -0.6]),
             ([[-0.1, 0.7, -0.1], [0.56, 0.15, 0.56], [-1.24, 1.65, -1.24]], [0.0, 1.1, -1.4]),
             ([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [3.0, 0.0, 0.0]], [2.0, 1.0, 0.0]),
             ([[0.5, 0.5, 0.5], [0.5, 0.5, 0.5], [0.5, 0.5, 0.5]], [1.5, 0.5, 0.5])]
    for T, p in cases:
        T, p = np.asarray(T, float), np.asarray(p, float)
        true = min(_segment_distance(p, T[i], T[(i + 1) % 3]) for i in range(3))
        d, _, q = mk.point_triangle_distance(p, T, [[0, 1, 2]])
        assert abs(d[0] - true) < 1e-12, (T, p, d[0], true)
        assert abs(np.linalg.norm(q[0] - p) - true) < 1e-12


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


# ---------------------------------------------------------------------------------------------------------------
# detector fixtures (synthetic parts, synthetic profiles)
# ---------------------------------------------------------------------------------------------------------------

from miki_model import acceptance as ac  # noqa: E402
from miki_model import checks  # noqa: E402


def _box(lo, hi) -> mk.Mesh:
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    ring = lambda z: np.array([[x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z]])  # noqa: E731
    return mk.loft([ring(z0), ring(z1)], "flat", "flat")


def _rod(x, y, z0, z1, r=0.005, n=12) -> mk.Mesh:
    return mk.loft([mk.ellipse_ring(r, r, n, (x, y, z)) for z in (z0, z1)], "flat", "flat")


def _parts(**meshes):
    return [mk.Part(name, "skin", m, obj="x") for name, m in meshes.items()]


def _req(report, name):
    return next(e for e in report["requirements"] if e["name"] == name)


def _generic(report, a, b):
    return _req(report, f"generic:{a}|{b}")


def test_crossing_that_vertex_samples_miss_fails():
    """Two thin slabs crossing like a '+': no vertex of either lies inside the other, the curve is found."""
    parts = _parts(a=_box((-0.1, -0.002, -0.002), (0.1, 0.002, 0.002)),
                   b=_box((-0.002, -0.1, -0.001), (0.002, 0.1, 0.001)))
    rep = checks.run(parts, profile=[])
    g = _generic(rep, "a", "b")
    assert g["verdict"] == checks.FAIL
    assert g["measured"]["vertices_inside"] == 0 and g["measured"]["crossings"] > 0
    assert rep["summary"]["required_pass"] is False


def test_shell_wholly_inside_another_fails():
    parts = _parts(big=_box((-0.05, -0.05, -0.05), (0.05, 0.05, 0.05)),
                   small=_box((-0.01, -0.01, -0.01), (0.01, 0.01, 0.01)))
    rep = checks.run(parts, profile=[])
    g = _generic(rep, "big", "small")
    assert g["verdict"] == checks.FAIL and g["measured"]["crossings"] == 0
    assert any(f["what"] == "shell wholly inside the other part" and f["part"] == "small" for f in g["findings"])


def test_near_contact_inside_the_tolerance_passes():
    """A sphere's pole touching a box top: 0.5 um into it (below the contact tolerance) and 0.5 eps above it."""
    for dz in (-0.5e-6, 0.5 * EPS):
        sphere = mk.ellipsoid((0.0, 0.0, 0.05 + dz), (0.05, 0.05, 0.05), nu=12, nv=12)
        parts = _parts(box=_box((-0.1, -0.1, -0.02), (0.1, 0.1, 0.0)), ball=sphere)
        rep = checks.run(parts, profile=[])
        g = _generic(rep, "box", "ball")
        assert g["verdict"] == checks.PASS, (dz, g)
        assert g["measured"]["crossings"] == 0 and g["measured"]["vertices_inside"] == 0
        if dz < 0:
            assert g["measured"]["contacts"] > 0                      # recorded with its location, not hidden
            assert any(f["what"] == "contact" for f in g["findings"])


def _rod_join(zone, rim=None, depth=0.0, name="join:rod~box"):
    return ac.Join(name, "rod", "box", zone, rim, depth, "fixture", "a rod sunk into a box through its top")


TOP = 0.05


def test_join_inside_its_zone_passes_and_a_leak_fails():
    box = _box((-0.05, -0.05, -0.05), (0.05, 0.05, TOP))
    zone = ac.Zone(z=(TOP, TOP), note="the box's top face")
    rim = ac.Select(min_sides=ac.CAP_SIDES, vz=(-1.0, 0.0), note="the rod's bottom cap")
    ok = checks.run(_parts(box=box, rod=_rod(0.0, 0.0, 0.0, 0.1)), profile=[_rod_join(zone, rim, 0.02)])
    assert _req(ok, "join:rod~box")["verdict"] == checks.PASS
    assert not any(e["kind"] == "generic" and set(e["parts"]) == {"rod", "box"} for e in ok["requirements"])
    # the same rod near the box's side: its curve also runs down the side wall, outside the zone
    leak = checks.run(_parts(box=box, rod=_rod(0.048, 0.0, 0.0, 0.1)), profile=[_rod_join(zone)])
    j = _req(leak, "join:rod~box")
    assert j["verdict"] == checks.FAIL and j["measured"]["outside_zone"] > 0
    assert any("outside the zone" in f["what"] and f["xyz"][2] < TOP - 1e-3 for f in j["findings"])


def _cut_prism():
    """A decal-like prism (front triangle at y = -1 mm facing -y, back at y = +2 mm) and a host box whose front
    plane cuts the prism's front face along x = 5 mm, from one front edge to the other."""
    F = np.array([[-0.01, -0.001, -0.01], [0.01, -0.001, -0.01], [0.0, -0.001, 0.01]])
    m = mk.loft([F, F + [0.0, 0.003, 0.0]], "flat", "flat")
    if not mk.validate(m, "p", check_ground=False).ok:
        m = mk.loft([F[::-1], F[::-1] + [0.0, 0.003, 0.0]], "flat", "flat")

    def yp(x):
        return -0.4 * (x - 0.005) - 0.001

    xs, zs, yb = (-0.05, 0.05), (-0.05, 0.05), 0.06
    HV = np.array([[xs[0], yp(xs[0]), zs[0]], [xs[1], yp(xs[1]), zs[0]], [xs[1], yp(xs[1]), zs[1]],
                   [xs[0], yp(xs[0]), zs[1]], [xs[0], yb, zs[0]], [xs[1], yb, zs[0]], [xs[1], yb, zs[1]],
                   [xs[0], yb, zs[1]]])
    hf = [[0, 1, 2], [0, 2, 3], [4, 7, 6], [4, 6, 5], [0, 4, 5, 1], [1, 5, 6, 2], [2, 6, 7, 3], [3, 7, 4, 0]]
    if mk.face_normals(mk.Mesh(HV, hf, 1))[0][0][1] > 0:
        hf = [f[::-1] for f in hf]
    return m, mk.Mesh(HV, hf, 1)


def test_join_zone_tests_the_whole_segment_not_its_ends():
    """The host cuts across the decal's FRONT face from one front edge to the other; the zone allows only the
    non-front faces.  Both end points lie on edges shared with the walls (inside the zone), the 10 mm between
    them do not: FAIL (review finding: the zone test used the end points only)."""
    decal, host = _cut_prism()
    assert mk.validate(decal, "decal", check_ground=False).ok and mk.validate(host, "host", check_ground=False).ok
    not_front = ac.Select(facing=((0.0, -1.0, 0.0), 0.7), invert=True, note="not the front face")
    join = ac.Join("join:decal~skin", "decal", "skin", ac.Zone(faces=("a", not_front)), None, 0.0, "fixture", "d")
    j = _req(checks.run(_parts(decal=decal, skin=host), profile=[join]), "join:decal~skin")
    assert j["verdict"] == checks.FAIL and j["measured"]["outside_zone"] >= 1, j["measured"]
    leak = [f for f in j["findings"] if "outside the zone" in f["what"]]
    assert leak and abs(leak[0]["xyz"][0] - 0.005) < 1e-6 and -0.0099 < leak[0]["xyz"][2] < -1e-4
    # the same cut through a union zone (any_of) that also leaves the front out
    union = dataclasses.replace(join, zone=ac.Zone(any_of=(ac.Zone(faces=("a", not_front)), ac.Zone(z=(0.5, 0.6)))))
    assert _req(checks.run(_parts(decal=decal, skin=host), profile=[union]), "join:decal~skin")["verdict"] == \
        checks.FAIL
    # allowing the front face too: PASS
    every = dataclasses.replace(join, zone=ac.Zone(faces=("a", ac.ALL)))
    assert _req(checks.run(_parts(decal=decal, skin=host), profile=[every]), "join:decal~skin")["verdict"] == \
        checks.PASS


def test_join_zone_selecting_no_faces_is_indeterminate():
    box = _box((-0.05, -0.05, -0.05), (0.05, 0.05, TOP))
    zone = ac.Zone(faces=("b", ac.Select(groups=(99,), note="no such group")))
    j = _req(checks.run(_parts(box=box, rod=_rod(0.0, 0.0, 0.0, 0.1)), profile=[_rod_join(zone)]), "join:rod~box")
    assert j["verdict"] == checks.INDETERMINATE and "selects no faces" in j["verdict_reason"]


def test_join_whose_buried_rim_surfaces_fails():
    box = _box((-0.05, -0.05, -0.05), (0.05, 0.05, TOP))
    zone = ac.Zone(z=(TOP, TOP))
    rim = ac.Select(min_sides=ac.CAP_SIDES, vz=(-1.0, TOP + 0.01), note="the rod's bottom cap")
    for z0, verdict in ((0.0, checks.PASS), (TOP - 0.005, checks.FAIL), (TOP + 0.002, checks.FAIL)):
        rep = checks.run(_parts(box=box, rod=_rod(0.0, 0.0, z0, 0.1)), profile=[_rod_join(zone, rim, 0.02)])
        j = _req(rep, "join:rod~box")
        assert j["verdict"] == verdict, (z0, j)
        if verdict == checks.FAIL:
            assert any(f["what"] == "rim vertex not buried by the required depth" for f in j["findings"])


def test_positive_gap_below_the_minimum_fails():
    lo = _box((-0.02, -0.02, -0.02), (0.02, 0.02, 0.0))
    for gap, verdict in ((0.0005, checks.FAIL), (0.002, checks.PASS)):
        hi = _box((-0.01, -0.01, gap), (0.01, 0.01, 0.01))
        req = ac.Clear("clear:hi^lo", "hi", "lo", ac.ALL, ac.ALL, 0.001, ac.INF, "fixture", "a 1 mm gap")
        for metric in ("points", "euclid"):
            rep = checks.run(_parts(lo=lo, hi=hi), profile=[dataclasses.replace(req, metric=metric)])
            c = _req(rep, "clear:hi^lo")
            assert c["verdict"] == verdict, (gap, metric, c)
            if "min" in c["measured"]:
                assert abs(c["measured"]["min"] - gap) < 1e-9
            else:                                                     # nothing within the screening pad
                assert metric == "euclid" and c["measured"]["min_gap_above"] < gap


def test_required_pose_not_tested_is_indeterminate():
    pose = ac.Pose("pose:arms-raised", "arms raised", "fixture", "posed clearance", level="required")
    rep = checks.run(_parts(a=_box((0, 0, 0), (0.01, 0.01, 0.01))), profile=[pose])
    p = _req(rep, "pose:arms-raised")
    assert p["verdict"] == checks.INDETERMINATE and "not tested" in p["verdict_reason"]
    assert rep["summary"]["required_pass"] is False                 # INDETERMINATE never passes
    advisory = dataclasses.replace(pose, level="advisory")
    assert checks.run(_parts(a=_box((0, 0, 0), (0.01, 0.01, 0.01))), profile=[advisory])["summary"]["required_pass"]


# -- degenerate-intersection policy ----------------------------------------------------------------------------

def test_coplanar_overlap_is_coincident():
    """Two boxes sharing a face plane, overlapping in it: 'coincident' -- FAIL under everything else, PASS under a
    join only when the overlap polygon lies inside the zone."""
    a = _box((-0.02, -0.02, -0.02), (0.02, 0.02, 0.0))
    b = _box((0.0, -0.01, 0.0), (0.04, 0.01, 0.02))
    rep = checks.run(_parts(a=a, b=b), profile=[])
    g = _generic(rep, "a", "b")
    assert g["verdict"] == checks.FAIL and g["measured"]["coincident"] > 0 and g["measured"]["crossings"] == 0
    assert rep["summary"]["coincident"] > 0
    inside = ac.Join("join:b~a", "b", "a", ac.Zone(z=(0.0, 0.0)), None, 0.0, "fixture", "b stands on a")
    assert _req(checks.run(_parts(a=a, b=b), profile=[inside]), "join:b~a")["verdict"] == checks.PASS
    outside = dataclasses.replace(inside, zone=ac.Zone(z=(0.001, 0.002)))
    j = _req(checks.run(_parts(a=a, b=b), profile=[outside]), "join:b~a")
    assert j["verdict"] == checks.FAIL and any("coincident" in f["what"] for f in j["findings"])


def test_edge_and_vertex_on_face_within_eps_is_contact_not_penetration():
    """A box standing on its edge and an octahedron standing on its vertex, each 0.5 um into a slab."""
    slab = _box((-0.1, -0.1, -0.01), (0.1, 0.1, 0.0))
    s = 0.01 / math.sqrt(2.0)
    edge = mk.Mesh(_box((-0.02, -s, -s), (0.02, s, s)).rotate("x", 45.0).vertices + [0, 0, 0.01 - 0.5e-6],
                   _box((-0.02, -s, -s), (0.02, s, s)).faces, 1)
    octa = mk.ellipsoid((0.0, 0.0, 0.0), (0.01, 0.01, 0.01), nu=4, nv=3)
    vertex = octa.translate((0.05, 0.05, 0.01 - 0.5e-6))
    rep = checks.run(_parts(slab=slab, edge=edge, vertex=vertex), profile=[])
    for other in ("edge", "vertex"):
        g = _generic(rep, "slab", other)
        assert g["verdict"] == checks.PASS, (other, g)
        assert g["measured"]["contacts"] > 0 and g["measured"]["crossings"] == 0


def test_mesh_crossing_shorter_than_eps_is_a_crossing():
    """A needle poking 20 eps through a face: its cut is far shorter than eps, and it still counts."""
    h = 20.0 * EPS
    w = 1e-4
    sq = lambda z, k: np.array([[-k, -k, z], [k, -k, z], [k, k, z], [-k, k, z]])  # noqa: E731
    needle = mk.loft([sq(0.05, w), sq(0.01, w * 0.8)], "flat", ("pole", (0.0, 0.0, -h)))
    rep = checks.run(_parts(slab=_box((-0.1, -0.1, -0.01), (0.1, 0.1, 0.0)), needle=needle), profile=[])
    g = _generic(rep, "slab", "needle")
    assert g["verdict"] == checks.FAIL and g["measured"]["crossings"] > 0
    chk = checks.Checker({p.name: checks.PartGeom(p.name, p.obj, p.mesh) for p in _parts(
        slab=_box((-0.1, -0.1, -0.01), (0.1, 0.1, 0.0)), needle=needle)})
    r = chk.classify(chk.pair("slab", "needle"), chk.eps)
    seg = r["seg"][r["kind"] == mk.TT_CROSSING]
    assert np.max(np.linalg.norm(seg[:, 1] - seg[:, 0], axis=1)) < EPS


def _rod_rows(x, y, zs, r=0.005, n=12) -> mk.Mesh:
    return mk.loft([mk.ellipse_ring(r, r, n, (x, y, z)) for z in zs], "flat", "flat")


def test_crossing_along_a_mesh_edge_is_a_crossing():
    """A ring row exactly on the other part's plane: each triangle pair there is a contact (one far vertex, one
    side), yet the surface crosses along the row's edges.  The edge-crossing pass finds it (review finding)."""
    slab = _box((-0.05, -0.05, 0.0), (0.05, 0.05, 0.002))
    for zs in ((-0.01, 0.012), (-0.01, 0.0, 0.002, 0.012)):            # control; ring rows on both slab faces
        rep = checks.run(_parts(slab=slab, rod=_rod_rows(0.0, 0.0, zs)), profile=[])
        g = _generic(rep, "slab", "rod")
        assert g["verdict"] == checks.FAIL and g["measured"]["crossings"] > 0, (zs, g["measured"])
    # a join: the rod sunk through the box's top also leaves through its bottom face (outside the zone),
    # with a ring row exactly on the bottom plane, and 5 um above it (no longer tolerance-sensitive)
    box = _box((-0.05, -0.05, -0.05), (0.05, 0.05, 0.05))
    join = ac.Join("join:rod~box", "rod", "box", ac.Zone(z=(0.05, 0.05)), None, 0.0, "fixture", "through the top")
    for zs in ((-0.1, 0.1), (-0.1, -0.05, 0.1), (-0.1, -0.05 + 5e-6, 0.1)):
        j = _req(checks.run(_parts(box=box, rod=_rod_rows(0.0, 0.0, zs)), profile=[join]), "join:rod~box")
        assert j["verdict"] == checks.FAIL and j["measured"]["outside_zone"] > 0, (zs, j["measured"])
    # the segment is the edge clipped to the triangle it crosses
    X = np.array([[0.2, 0.2, 0.0], [0.6, 0.2, 0.0], [0.4, 0.5, 0.3], [0.4, -0.1, -0.3]])
    T = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    r = mk.triangle_intersections(X, [[0, 1, 2], [1, 0, 3]], T, [[0, 1, 2]], EPS)
    assert [mk.TT_KINDS[int(q)] for q in r["kind"]] == ["crossing", "crossing"]
    np.testing.assert_allclose(sorted(map(tuple, r["seg"][0])), [(0.2, 0.2, 0.0), (0.6, 0.2, 0.0)])
    # the same two triangles on the same side of the plane only touch it: contact
    X2 = X.copy()
    X2[3, 2] = 0.3
    r = mk.triangle_intersections(X2, [[0, 1, 2], [1, 0, 3]], T, [[0, 1, 2]], EPS)
    assert [mk.TT_KINDS[int(q)] for q in r["kind"]] == ["contact", "contact"]


def test_verdict_that_flips_with_eps_is_tolerance_sensitive():
    """A sphere pole 3 eps into a box: a crossing at eps / 10 and eps, a contact at 10 eps -> INDETERMINATE."""
    sphere = mk.ellipsoid((0.0, 0.0, 0.05 - 3.0 * EPS), (0.05, 0.05, 0.05), nu=12, nv=12)
    rep = checks.run(_parts(box=_box((-0.1, -0.1, -0.02), (0.1, 0.1, 0.0)), ball=sphere), profile=[])
    g = _generic(rep, "box", "ball")
    assert g["verdict"] == checks.INDETERMINATE and g["verdict_reason"].startswith("tolerance-sensitive")
    assert g["tolerance_sensitive"] and all("xyz" in f and "face" in f for f in g["tolerance_sensitive"])
    assert rep["summary"]["tolerance_sensitive"] == 1 and rep["summary"]["required_pass"] is False


def test_crossing_hidden_from_the_classifier_is_caught_by_containment_and_depth(monkeypatch):
    """With the segment classifier blinded, a penetrating box still FAILs (containment) and a surfacing rim
    still FAILs (depth): the volume cross-check is independent."""
    def blind(VA, ta, VB, tb, eps, pairs=None):
        z = np.zeros(0, dtype=np.int64)
        return {"ia": z, "ib": z, "kind": z, "seg": np.zeros((0, 2, 3)), "polys": [],
                "near_band": np.zeros(0, dtype=bool), "n_candidates": 0, "n_near_band": 0}

    monkeypatch.setattr(checks.mk, "triangle_intersections", blind)
    parts = _parts(a=_box((-0.02, -0.02, -0.02), (0.02, 0.02, 0.0)), b=_box((0.01, 0.01, -0.005), (0.04, 0.04, 0.02)))
    g = _generic(checks.run(parts, profile=[]), "a", "b")
    assert g["measured"]["crossings"] == 0 and g["measured"]["vertices_inside"] > 0 and g["verdict"] == checks.FAIL
    box = _box((-0.05, -0.05, -0.05), (0.05, 0.05, TOP))
    rim = ac.Select(min_sides=ac.CAP_SIDES, vz=(-1.0, TOP))
    rep = checks.run(_parts(box=box, rod=_rod(0.0, 0.0, TOP - 0.005, 0.1)),
                     profile=[_rod_join(ac.Zone(z=(TOP, TOP)), rim, 0.02)])
    j = _req(rep, "join:rod~box")
    assert j["measured"]["intersection_segments"] == 0 and j["verdict"] == checks.FAIL


def test_report_is_deterministic_json():
    parts = _parts(a=_box((-0.1, -0.002, -0.002), (0.1, 0.002, 0.002)),
                   b=_box((-0.002, -0.1, -0.001), (0.002, 0.1, 0.001)))
    t1, t2 = checks.dumps(checks.run(parts, profile=[])), checks.dumps(checks.run(parts, profile=[]))
    assert t1 == t2
    assert json.loads(t1)["geometry"]["eps"] == pytest.approx(EPS)


# ---------------------------------------------------------------------------------------------------------------
# the checks on Miki (built once per module) and the two mutations
# ---------------------------------------------------------------------------------------------------------------

from miki_model import assemble as asm  # noqa: E402
from miki_model import body, hair  # noqa: E402
from miki_model.rig import Rig  # noqa: E402


@pytest.fixture(scope="module")
def miki():
    return asm.assemble(Rig())


@pytest.fixture(scope="module")
def miki_report(miki):
    return checks.run(miki.parts, reports=miki.reports)


def _mutated(parts, name, fn):
    out = []
    for p in parts:
        if p.name == name:
            V = fn(p.mesh.vertices.copy())
            p = dataclasses.replace(p, mesh=mk.Mesh(np.round(V, asm.DECIMALS) + 0.0, p.mesh.faces, p.mesh.groups))
        out.append(p)
    return out


def test_miki_every_requirement_has_a_verdict(miki_report):
    rep = miki_report
    assert rep["profile"] == {"name": ac.PROFILE_NAME, "version": ac.PROFILE_VERSION,
                              "requirements": len(ac.profile())}
    verdicts = {e["verdict"] for e in rep["requirements"]}
    assert verdicts <= {checks.PASS, checks.FAIL, checks.INDETERMINATE}
    for e in rep["requirements"]:
        assert e["kind"] in ("join", "clear", "generic", "proportion", "pose")
        if e["verdict"] == checks.INDETERMINATE:
            assert e.get("verdict_reason"), e["name"]               # it says what is missing
    names = {e["name"] for e in rep["requirements"]}
    assert {r.name for r in ac.profile()} <= names                  # every profile requirement was evaluated
    assert rep["summary"]["required_pass"] == all(e["verdict"] == checks.PASS for e in rep["requirements"]
                                                  if e["level"] == "required")


def test_miki_every_intersecting_pair_is_accounted_for(miki_report):
    """The pair table: every pair with an intersection or a contained vertex is under a declared join or a
    generic requirement (which then FAILs)."""
    for p in miki_report["pairs"]:
        assert p["requirements"], p
        if p["crossings"] or p["coincident"] or p["a_vertices_inside_b"] or p["b_vertices_inside_a"]:
            kinds = {n.split(":")[0] for n in p["requirements"]}
            assert "join" in kinds or "FAIL" in p["verdicts"] or "INDETERMINATE" in p["verdicts"], p
    assert miki_report["summary"]["intersecting_pairs"] >= 80


def test_miki_named_pairs_are_tested_even_without_a_contact(miki_report):
    """A pair the profile names is always evaluated (the bbox screen only orders the generic work)."""
    clear = [e for e in miki_report["requirements"] if e["kind"] == "clear"]
    assert any(e["name"] == "clear:limbs.strap_l^limbs.shoe_l" for e in clear)
    assert all(e["verdict"] in (checks.PASS, checks.FAIL, checks.INDETERMINATE) for e in clear)


def test_miki_proportions_match_the_lofting_tables(miki_report):
    for name in ("proportion:head.skin", "proportion:body.blouse"):
        e = _req(miki_report, name)
        assert e["verdict"] == checks.PASS, e["findings"]
        rows = e["measured"]["rows"]
        assert all({"half_width_left", "half_width_right", "front_y", "back_y"} <= set(r) for r in rows)


def test_miki_report_is_deterministic(miki):
    only = {"hair.sidelock_l"}
    a = checks.dumps(checks.run(miki.parts, reports=miki.reports, only=only))
    b = checks.dumps(checks.run(miki.parts, reports=miki.reports, only=only))
    assert a == b


def test_mutation_collar_3mm_into_the_blouse_fails(miki, miki_report):
    """Shifting the collar 3 mm toward the chest turns its lapel-tuck requirements from PASS to FAIL and deepens
    the collar's poke-through into the blouse."""
    names = ("join:body.dickey~body.collar", "join:body.scarf_ribbon_l~body.collar",
             "join:body.scarf_ribbon_r~body.collar")
    for n in names:
        assert _req(miki_report, n)["verdict"] == checks.PASS, n
    c = np.asarray(body.TORSO_CENTRE)

    def inward(V):
        d = V - c
        return V - 0.003 * d / np.linalg.norm(d, axis=1)[:, None]

    rep = checks.run(_mutated(miki.parts, "body.collar", inward), reports=miki.reports, only={"body.collar"})
    for n in names:
        assert _req(rep, n)["verdict"] == checks.FAIL, n
    before = _generic(miki_report, "body.blouse", "body.collar")["measured"]
    after = _generic(rep, "body.blouse", "body.collar")
    assert after["verdict"] == checks.FAIL
    assert after["measured"]["crossings"] > 2 * before["crossings"]
    assert after["measured"]["vertices_inside"] > 2 * before["vertices_inside"]


def test_mutation_hair_root_2mm_out_of_the_dome_fails(miki, miki_report):
    """Pushing the sidelock's buried root row 2 mm out along the dome normal fails the dome-hair join."""
    name = "join:hair.sidelock_l~hair.dome"
    assert _req(miki_report, name)["verdict"] == checks.PASS
    rig = Rig()

    def out(V):
        V = V.copy()
        for i in np.nonzero(V[:, 2] >= hair.SIDELOCK_ROOT_Z - 1e-9)[0]:
            V[i] = V[i] + 0.002 * hair._ellipsoid_normal(rig, V[i])
        return V

    rep = checks.run(_mutated(miki.parts, "hair.sidelock_l", out), reports=miki.reports, only={"hair.sidelock_l"})
    j = _req(rep, name)
    assert j["verdict"] == checks.FAIL
    assert any(f["what"] == "rim vertex not buried by the required depth" for f in j["findings"])
