"""Arcs at infinity of a shadow loop with several excursions to infinity (contract §2.5 as amended by the
§5.1 implementation note "arc pairing"; D70; review findings m4-geometry#0 and determinism-perf#0).

A silhouette loop whose plane through the light parallel to the receiver cuts it four or more times
(a concave caster with the light between its arms: an arch, a U-prism lying on its side, a U-prism on the
ground with a wall beyond its opening) has two or more outgoing / incoming direction pairs.  The arcs at
infinity are fixed by the **angular** order of the crossings about ``n`` -- parenthesis matching of the
loop's own crossings, which for a simple loop pairs every outgoing direction with the angularly next
incoming one -- not by the loop order; the chains are re-linked through those arcs and every cycle is one
output loop.  The tests here are reference-free where they can be (an analytic plate shadow, synthetic
crossing patterns) and use the ray caster on whole scenes.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

import castplane
from castplane.homogeneous import to_homogeneous
from castplane.scene import load_scene
from castplane.shadow import _arc_components, shadow_loop, shadow_matrix
from tests.reference import raster, raycast
from tests.test_raycast import multi_component_records, render_and_compare
from tests.test_receivers import plate_masks, shadow_of

#: The scenes were v7 candidates (tests/fixtures/v7_candidates/) and are conformance cases since v7.
FIXTURES = Path(__file__).parent / "conformance" / "cases"
#: candidate file name -> v7 conformance case file
CASE_FILE = {"arch_ground.json": "arc_pairing_arch_ground.json", "u_wall.json": "arc_pairing_u_wall.json",
             "u_notch_wall.json": "arc_pairing_u_notch_wall.json", "u_on_side.json": "arc_pairing_u_on_side.json",
             "u_closed_arm_wall.json": "arc_pairing_u_closed_arm_wall.json",
             "spiral_upright.json": "arc_base_level_spiral_upright.json",
             "spiral_tilted.json": "arc_base_level_spiral_tilted.json",
             "spiral_floor.json": "arc_base_level_spiral_floor.json"}
GROUND = np.array([0.0, 0.0, 1.0, 0.0])
TWO_PI = 2.0 * math.pi
#: An arch-shaped plate outline in the vertical plane ``y = 1`` as ``(x, z)`` pairs, counter-clockwise as
#: seen from the light side (``y < 1``): legs at ``|x| in [0.5, 1]`` up to ``z = 2``, the opening between
#: them up to the lintel at ``z = 1.5``.  (A U with its mouth *up* would not do: its loop order agrees
#: with the angular order, like ``concave_prism_on_plate``; the mouth must face the light plane's cut.)
U_XZ = [(-1.0, 0.0), (-0.5, 0.0), (-0.5, 1.5), (0.5, 1.5), (0.5, 0.0), (1.0, 0.0), (1.0, 2.0), (-1.0, 2.0)]
LIGHT = np.array([0.0, -2.0, 1.0])   # in front of the opening, below the lintel: the light plane cuts both legs


def fixture(name: str) -> dict:
    return load_scene(json.loads((FIXTURES / CASE_FILE[name]).read_text(encoding="utf-8")))


def rot_z(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def u_plate(T=(0.0, 0.0, 0.0), rz: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """``(loop4, light4)`` of the U plate and its light, rotated about ``z`` by ``rz`` and translated by ``T``."""
    R, T = rot_z(rz), np.asarray(T, dtype=np.float64)
    pts = np.array([[x, 1.0, z] for x, z in U_XZ]) @ R.T + T
    L = R @ LIGHT + T
    return to_homogeneous(pts), np.array([L[0], L[1], L[2], 1.0])


def direction_rows(component: dict) -> list:
    """``[(kind, angle)]`` of the component's ``("dir", ...)`` rows: ``"out"`` when the previous row is a
    finite vertex, else ``"in"`` (an incoming direction follows the arc)."""
    V, src = component["vertices"], component["sources"]
    rows = []
    for k, s in enumerate(src):
        if isinstance(s, tuple) and s[0] == "dir":
            prev = src[k - 1]
            kind = "out" if not (isinstance(prev, tuple) and prev[0] in ("dir", "arc")) else "in"
            rows.append((kind, math.atan2(V[k, 1], V[k, 0])))
    return rows


def ground_polygons(components: list, centre, far: float) -> list:
    out = []
    for comp in components:
        poly = []
        for v in comp["vertices"]:
            if v[3] == 0.0:
                n = math.hypot(v[0], v[1])
                poly.append([centre[0] + far * v[0] / n, centre[1] + far * v[1] / n])
            else:
                poly.append([v[0] / v[3], v[1] / v[3]])
        out.append(np.asarray(poly))
    return out


def analytic_plate_mask(xs, ys) -> np.ndarray:
    """Ground points whose segment to the light crosses the plane ``y = 1`` inside the U outline."""
    X, Y = np.meshgrid(xs, ys)
    beyond = Y > 1.0
    t = np.where(beyond, (1.0 - LIGHT[1]) / np.where(beyond, Y - LIGHT[1], 1.0), 0.0)
    px = LIGHT[0] + t * (X - LIGHT[0])
    pz = LIGHT[2] + t * (0.0 - LIGHT[2])
    inside = raycast.point_in_polygon(px.ravel(), pz.ravel(), U_XZ).reshape(X.shape)
    return inside & beyond


# --------------------------------------------------------------------------- shadow_loop on a 4-crossing loop
def test_four_crossing_loop_splits_into_two_angularly_paired_loops():
    """The U plate in front of the lamp: the loop crosses the light plane at the four arm edges; the
    result has two components, each with one outgoing and one incoming direction, every outgoing direction
    paired with the angularly next incoming one (not the loop-order next one), and the nonzero union of
    the components equals the analytic plate shadow."""
    loop4, L4 = u_plate()
    sh = shadow_loop(loop4, shadow_matrix(GROUND, L4), GROUND, 1e-9)
    comps = sh["loops"]
    assert len(comps) == 2 and sh["unbounded"]
    assert sh["vertices"] is comps[0]["vertices"] and sh["sources"] is comps[0]["sources"]
    rows = [direction_rows(c) for c in comps]
    assert all(sorted(k for k, _a in r) == ["in", "out"] for r in rows)
    ins = [a for r in rows for k, a in r if k == "in"]
    for r in rows:
        th_out = next(a for k, a in r if k == "out")
        th_in = next(a for k, a in r if k == "in")
        gaps = sorted((a - th_out) % TWO_PI for a in ins)
        assert abs((th_in - th_out) % TWO_PI - gaps[0]) <= 1e-12, "the arc must end at the angularly next incoming direction"
        assert (th_in - th_out) % TWO_PI < math.pi, "each arm's sweep is less than a half turn"
    total = sum((next(a for k, a in r if k == "in") - next(a for k, a in r if k == "out")) % TWO_PI for r in rows)
    assert total < math.pi, "the two arcs together cover less than the half circle (the loop-order pairing covered it all)"
    # reference-free check of the fill: nonzero union of the components against the analytic plate shadow
    xs, ys = np.linspace(-14.0, 14.0, 561), np.linspace(-3.0, 40.0, 861)
    got = raster.rasterize_polygons(ground_polygons(comps, (0.0, 18.5), 1e7), xs, ys)
    ref = analytic_plate_mask(xs, ys)
    assert ref.any() and raster.iou(got, ref) >= 0.99


def test_single_pair_loops_keep_one_component_identical_to_the_top_level_arrays():
    """A loop with at most one excursion (the lamp above the plate: none; the lamp at the lintel's
    height, where only the two outer edges cut the light plane: one) has exactly one component holding
    the same arrays; the empty result has one empty one."""
    loop4, _L4 = u_plate()
    for lz in (2.5, 1.75):
        L4 = np.array([0.0, -2.0, lz, 1.0])
        sh = shadow_loop(loop4, shadow_matrix(GROUND, L4), GROUND, 1e-9)
        assert len(sh["loops"]) == 1
        assert sh["loops"][0]["vertices"] is sh["vertices"] and sh["loops"][0]["sources"] is sh["sources"]
        assert sh["loops"][0]["unbounded"] == sh["unbounded"] == (lz < 2.0)
    # every vertex above the light: nothing
    sh = shadow_loop(loop4, shadow_matrix(GROUND, np.array([0.0, -2.0, -0.5, 1.0])), GROUND, 1e-9)
    assert sh["vertices"].shape == (0, 4) and len(sh["loops"]) == 1 and sh["loops"][0]["vertices"].shape == (0, 4)


@pytest.mark.parametrize("T, rz", [((0.0, 6.0, 0.0), 0.0), ((0.0, -6.0, 0.0), 0.0), ((20.0, 0.0, 0.0), 0.0),
                                   ((0.0, 0.0, 0.0), 37.0), ((5.0, -3.0, 0.0), 123.0), ((-7.0, 11.0, 0.0), 250.0)])
def test_arc_pairing_is_translation_and_rotation_invariant(T, rz):
    """The pairing depends only on the directions of the crossings (no origin enters): the same plate and
    lamp moved rigidly give the same components -- finite vertices mapped, every direction and arc sample
    turned by ``rz`` -- so the fix cannot be origin dependent (the S[:3]-azimuth proposal was)."""
    loop0, L0 = u_plate()
    base = shadow_loop(loop0, shadow_matrix(GROUND, L0), GROUND, 1e-9)["loops"]
    loop4, L4 = u_plate(T, rz)
    moved = shadow_loop(loop4, shadow_matrix(GROUND, L4), GROUND, 1e-9)["loops"]
    assert len(moved) == len(base) == 2
    R, Tv = rot_z(rz), np.asarray(T, dtype=np.float64)
    for a, b in zip(base, moved):
        assert a["sources"] == b["sources"]
        Va, Vb = a["vertices"], b["vertices"]
        assert Va.shape == Vb.shape
        for va, vb in zip(Va, Vb):
            if va[3] == 0.0:
                assert vb[3] == 0.0
                da, db = va[:3] / np.linalg.norm(va[:3]), vb[:3] / np.linalg.norm(vb[:3])
                assert np.allclose(R @ da, db, atol=1e-9)
            else:
                assert np.allclose(R @ (va[:3] / va[3]) + Tv, vb[:3] / vb[3], atol=1e-7)


# --------------------------------------------------------------------------- the matching itself (synthetic crossings)
def _synthetic(pattern):
    """``verts / sources / kinds`` of a loop ``F0, out, in, F1, out, in, F2`` with the given direction angles
    (degrees) in loop order: ``pattern = [out_0, in_after_out_0, out_1, in_after_out_1]``."""
    def d(deg):
        return np.array([math.cos(math.radians(deg)), math.sin(math.radians(deg)), 0.0, 0.0])
    verts = [np.array([0.0, 0.0, 0.0, 1.0]), d(pattern[0]), d(pattern[1]), np.array([1.0, 0.0, 0.0, 1.0]),
             d(pattern[2]), d(pattern[3]), np.array([2.0, 0.0, 0.0, 1.0])]
    sources = ["F0", ("dir", 0, 1), ("dir", 1, 2), "F1", ("dir", 3, 4), ("dir", 4, 5), "F2"]
    kinds = ["finite", "out", "in", "finite", "out", "in", "finite"]
    return verts, sources, kinds


def test_interleaved_crossings_are_repaired_into_two_simple_loops():
    """The wall case of finding m4-geometry#0 (crossings out -54.5°, in -125.5°, out 149°, in 31° in loop
    order): the angular pairing gives out(-54.5) -> in(31) and out(149) -> in(234.5), 85.5° each, as two
    loops; the loop-order pairing swept 289° + 242°."""
    verts, sources, kinds = _synthetic([-54.5, -125.5, 149.0, 31.0])
    comps = _arc_components(verts, sources, kinds, [1, 4], None)
    assert len(comps) == 2
    assert comps[0]["sources"] == ["F0", ("dir", 0, 1), ("arc", 0), ("dir", 4, 5), "F2"]
    assert comps[1]["sources"] == [("dir", 1, 2), "F1", ("dir", 3, 4), ("arc", 0)]
    mid0 = math.degrees(math.atan2(comps[0]["vertices"][2, 1], comps[0]["vertices"][2, 0]))
    mid1 = math.degrees(math.atan2(comps[1]["vertices"][3, 1], comps[1]["vertices"][3, 0]))
    assert abs(mid0 - (-54.5 + 42.75)) <= 1e-9
    assert abs((mid1 - (149.0 + 42.75) + 180.0) % 360.0 - 180.0) <= 1e-9


def test_loop_order_pairing_is_reproduced_when_it_is_the_angular_one():
    """Crossings out 10°, in 100°, out 200°, in 300°: the angular pairing is the loop-order one, so the
    single output loop is the v1 polygon (vertex order kept, arcs after each outgoing direction)."""
    verts, sources, kinds = _synthetic([10.0, 100.0, 200.0, 300.0])
    comps = _arc_components(verts, sources, kinds, [1, 4], None)
    assert len(comps) == 1
    assert comps[0]["sources"] == ["F0", ("dir", 0, 1), ("arc", 0), ("dir", 1, 2), "F1", ("dir", 3, 4), ("arc", 0),
                                   ("dir", 4, 5), "F2"]


def test_nested_crossings_match_like_parentheses():
    """Crossings out 10°, in 40°, out 20°, in 30° in loop order (a loop that is not simple on the sphere):
    parenthesis matching pairs the outer crossings (10° -> 40°) and the inner ones (20° -> 30°), which is
    the loop-order pairing here, so the v1 polygon comes out unchanged (one loop, sweeps 30° and 10°, the
    inner interval at winding two under the nonzero rule); a naive "angularly next incoming direction"
    rule would have paired 10° -> 30° and 20° -> 40° instead."""
    verts, sources, kinds = _synthetic([10.0, 40.0, 20.0, 30.0])
    comps = _arc_components(verts, sources, kinds, [1, 4], None)
    assert len(comps) == 1
    assert comps[0]["sources"] == ["F0", ("dir", 0, 1), ("dir", 1, 2), "F1", ("dir", 3, 4), ("dir", 4, 5), "F2"]
    rows = direction_rows(comps[0])
    assert [k for k, _a in rows] == ["out", "in", "out", "in"]
    assert [round(math.degrees(a), 9) for _k, a in rows] == [10.0, 40.0, 20.0, 30.0]


def test_coincident_out_and_in_crossings_sweep_the_full_circle():
    """An outgoing and an incoming direction at the same angle (the loop touches infinity) keep the v1 rule
    ``delta = 2 pi`` (contract §2.5 "when they coincide"), also with a second pair in the loop: the
    crossings out 10°, in 10°, out 100°, in 200° give the full circle (five inserted samples) for the
    touching pair and a 100° arc (one sample) for the other, re-linked into one loop."""
    verts, sources, kinds = _synthetic([10.0, 10.0, 100.0, 200.0])
    comps = _arc_components(verts, sources, kinds, [1, 4], None)
    assert len(comps) == 1
    arcs = [s for s in comps[0]["sources"] if isinstance(s, tuple) and s[0] == "arc"]
    assert len(arcs) == 5 + 1
    assert comps[0]["sources"][:8] == ["F0", ("dir", 0, 1)] + [("arc", k) for k in range(5)] + [("dir", 1, 2)]


# --------------------------------------------------------------------------- whole scenes
def test_arch_on_the_ground_has_two_ground_loops_matching_the_raycast():
    """Fixture ``arch_ground``: lamp below the lintel; two unbounded loops (the legs), IoU >= 0.99 with the
    ray caster on the §7.3 harness; the loop-order pairing covered the whole plane (IoU 0.075)."""
    scene = fixture("arch_ground.json")
    A = castplane.shadow_geometry(scene)
    assert [len(r["loops"]) for r in A["shadows"]] == [2]
    assert multi_component_records(A)
    out = render_and_compare(scene, per_object=False)
    assert out["iou"] >= 0.99


def test_u_prism_on_its_side_matches_the_raycast_on_the_ground():
    """Fixture ``u_on_side`` (finding m4-geometry#0 scene B): the v2 ground path with two excursions."""
    scene = fixture("u_on_side.json")
    assert multi_component_records(castplane.shadow_geometry(scene))
    out = render_and_compare(scene, per_object=False)
    assert out["iou"] >= 0.99


def test_u_prism_with_a_wall_beyond_the_opening_shadows_only_the_arms():
    """Fixture ``u_notch_wall`` (finding m4-geometry#0 scene A): lamp in the notch below the arm tops, wall
    beyond the opening: two wall loops, about 46 % of the plate, IoU >= 0.99 with the ray caster; the
    whole plate was reported before."""
    scene = fixture("u_notch_wall.json")
    doc = castplane.render(scene)["geometry"]
    sh = shadow_of(doc, "wall", "u")
    assert len(sh["loops"]) == 2 and all(len(loop) >= 3 for loop in sh["loops"])
    mask_doc, mask_ref = plate_masks(scene, doc, "wall")
    assert 0.2 <= float(mask_doc.mean()) <= 0.8, "the shadow must be a proper part of the plate"
    assert raster.iou(mask_doc, mask_ref) >= 0.99


def test_u_prism_straddling_the_light_plane_casts_nothing_on_the_wall():
    """Fixture ``u_wall`` (finding determinism-perf#0): the U-prism straddles the plane through the lamp
    parallel to the wall; the light plane cuts it four times, the two re-paired arcs sweep 6° each and
    both components miss the plate, so the wall record has no loops -- as the ray caster says (0 shadowed
    wall points); the loop-order pairing swept 354° and filled the 15 m² plate."""
    scene = fixture("u_wall.json")
    doc = castplane.render(scene)["geometry"]
    sh = shadow_of(doc, "wall", "u")
    assert sh["loops"] == [] and sh["polygons"] == [] and not sh["unbounded"]
    mask_doc, mask_ref = plate_masks(scene, doc, "wall")
    assert not mask_ref.any() and not mask_doc.any()
    # the ground shadow of the same prism is bounded (lamp above it) and unchanged in kind
    assert not shadow_of(doc, "ground", "u")["unbounded"]
