"""Base level of the arcs at infinity (second-pass review of the arc-pairing fix; §5.1 implementation note
"Base level of the arcs at infinity").

The arcs of ``shadow.shadow_loop`` fix the winding number of the directions at infinity only up to a
constant: a ``p = 1`` loop sweeps ``(theta_in - theta_out) mod 2 pi`` and the ``p >= 2`` parenthesis matching
starts at the minimal running level, both assuming that some direction of the light plane is free.  A lit
patch that wraps around the light within the light plane (a spiral prism with the lamp inside at
mid-height) has no free direction; the pipeline now pins the level with one ray of the light plane
(``shadow.light_plane_level``) and gives the difference to the first arc (``shadow_loop(..., turns=c)``).

Also here: a ``p >= 2`` loop whose angular pairing is the loop-order pairing is emitted bit for bit as the
v1 loop-order code (the sweep is the literal ``(theta_in - theta_out) mod 2 pi`` of the raw angles).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

import castplane
import castplane.pipeline as pipeline
from castplane import shadow as shadow_module
from castplane.homogeneous import to_homogeneous
from castplane.scene import load_scene
from castplane.shadow import (_arc_angle, _sweep_arc, arc_level, light_plane_level, shadow_loop, shadow_matrix)
from tests.reference import raster, raycast, random_scenes
from tests.test_raycast import compare, multi_component_records
from tests.test_receivers import plate_masks

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


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / CASE_FILE[name]).read_text(encoding="utf-8"))


def big_window_fractions(scene: dict, half: float = 20.0, n: int = 240) -> tuple[float, float, float]:
    """``(ray-cast fraction, document fraction, IoU)`` of the ground square ``[-half, half]^2``."""
    v = load_scene(scene)
    doc = castplane.render(v)["geometry"]
    lo, hi = np.array([-half, -half]), np.array([half, half])
    xs, ys = random_scenes.grid(lo, hi, n)
    ref = raycast.shadow_mask(v, v["lights"][0], xs, ys)
    got = raster.rasterize_polygons(raster.doc_ground_loops(doc, 0.5 * (lo + hi), 3e7), xs, ys)
    return float(ref.mean()), float(got.mean()), raster.iou(got, ref)


# --------------------------------------------------------------------------- whole scenes
def test_upright_spiral_with_the_lamp_inside_is_shadowed_almost_everywhere():
    """Fixture ``spiral_upright``: a 1.3-turn spiral prism on the ground, lamp inside at mid-height; every
    horizontal ray from the lamp hits the solid (once or twice), so the ground is in shadow except a small
    patch around the spiral's core.  One ``p = 1`` loop whose arc must sweep 1.3 turns; ``(theta_in -
    theta_out) mod 2 pi`` gave 108° (IoU 0.26 with the ray cast, also before the arc-pairing fix)."""
    scene = fixture("spiral_upright.json")
    A = castplane.shadow_geometry(load_scene(scene))
    (rec,) = [r for r in A["shadows"] if r["receiver"] == "ground"]
    assert len(rec["loops"]) == 1 and rec["unbounded"]
    arcs = sum(1 for s in rec["loops"][0]["sources"] if isinstance(s, tuple) and s[0] == "arc")
    assert arcs > 6, "the arc must sweep more than one full turn"
    doc = castplane.render(load_scene(scene))["geometry"]
    assert compare(scene, doc)["iou"] >= 0.99
    ref, got, iou = big_window_fractions(scene)
    assert ref > 0.95 and abs(got - ref) < 0.01 and iou >= 0.99


def test_tilted_spiral_with_two_excursions_matches_the_raycast():
    """Fixture ``spiral_tilted`` (the reviewer's ``mk_spiral_case 30 15 0.4``): the spiral tilted 15° about
    ``x``; the lit run's top edge dips through the light plane, ``p = 2``, two components whose matched arcs
    sweep 8° and 36° while every direction of the light plane hits the solid; the minimal-level start drew
    12 % of the equator (IoU 0.03-0.07).  The base level adds one full turn to the first arc."""
    scene = fixture("spiral_tilted.json")
    v = load_scene(scene)
    A = castplane.shadow_geometry(v)
    assert multi_component_records(A)
    doc = castplane.render(v)["geometry"]
    assert compare(scene, doc)["iou"] >= 0.99
    ref, got, iou = big_window_fractions(scene)
    assert ref > 0.95 and iou >= 0.99


def test_spiral_on_a_raised_floor_plate_matches_the_raycast():
    """Fixture ``spiral_floor``: the upright spiral and a bounded horizontal plate at ``z = 0.25`` (the solid
    cut to the plate's positive side, the receiver frame path of ``_caster_record``, then the bounds
    clip of an arc sweeping more than one turn): 97 % of the plate is in shadow (IoU 0.27 before)."""
    v = load_scene(fixture("spiral_floor.json"))
    doc = castplane.render(v)["geometry"]
    mask_doc, mask_ref = plate_masks(v, doc, "floor")
    assert float(mask_ref.mean()) > 0.9
    assert raster.iou(mask_doc, mask_ref) >= 0.99


@pytest.mark.parametrize("phi,tilt,frac", [(30, 15.0, 0.4), (30, 20.0, 0.5), (60, 15.0, 0.4), (60, 20.0, 0.5),
                                           (210, 15.0, 0.6), (210, 20.0, 0.5), (240, 15.0, 0.6)])
def test_the_reviewers_failing_spiral_configurations_match_the_raycast(phi, tilt, frac):
    """The seven ``p >= 2`` spiral configurations of the review scan (``attack_spiral3``) that drew a small
    wedge instead of (almost) the whole plane."""
    scene = spiral_scene(phi, tilt, frac)
    ref, got, iou = big_window_fractions(scene, n=160)
    assert iou >= 0.98, (ref, got, iou)


def spiral_polygon(turns=1.3, phi=0.0, r0=0.6, r1=2.0, width=0.35, n=28) -> list:
    a = np.linspace(0, 2 * math.pi * turns, n) + math.radians(phi)
    rad = r0 + (r1 - r0) * (a - a[0]) / (a[-1] - a[0])
    outer = [[(rr + width) * math.cos(t), (rr + width) * math.sin(t)] for rr, t in zip(rad, a)]
    inner = [[rr * math.cos(t), rr * math.sin(t)] for rr, t in zip(rad[::-1], a[::-1])]
    return [[round(float(x), 5), round(float(y), 5)] for x, y in outer + inner]


def spiral_scene(phi: float, tilt: float, frac: float) -> dict:
    """The review scan's scene: spiral pre-rotated by ``phi``, tilted about ``x``, resting on the ground, lamp
    on the axis at ``frac`` of the (tilted) height."""
    obj = {"id": "c", "type": "prism", "polygon": spiral_polygon(phi=phi), "height": 1.0,
           "transform": {"position": [0.0, 0.0, 0.0], "rotation_deg": [tilt, 0.0, 0.0]}}
    pts = random_scenes.world_extreme_points(obj)
    obj["transform"]["position"][2] = round(float(-pts[:, 2].min()) + 0.01, 4)
    zc = float(obj["transform"]["position"][2])
    L = [0.0, 0.0, round(zc + frac * math.cos(math.radians(tilt)), 4)]
    return random_scenes.assemble_scene([obj], {"id": "lamp", "type": "point", "position": L},
                                        random_scenes.random_camera(np.random.default_rng(1), [obj]))


def test_ordinary_unbounded_scenes_need_no_correction(monkeypatch):
    """Every unbounded record of the ordinary scenes (box, arch, U on its side) already has the right level:
    ``shadow_loop`` is never re-run with ``turns != 0`` (byte identity of the conformance cases)."""
    calls = []
    real = shadow_module.shadow_loop

    def spy(*args, **kw):
        calls.append(kw.get("turns", 0))
        return real(*args, **kw)

    monkeypatch.setattr(pipeline, "shadow_loop", spy)
    for name in ("arch_ground.json", "u_on_side.json", "u_notch_wall.json", "u_wall.json"):
        castplane.render(load_scene(fixture(name)))
    box = {"version": "0.1", "units": "m", "up": "z",
           "objects": [{"id": "b", "type": "box", "size": [1.0, 1.0, 2.0]}],
           "lights": [{"id": "lamp", "type": "point", "position": [2.0, 0.5, 1.0]}],
           "receivers": [{"id": "ground", "type": "plane", "normal": [0, 0, 1], "offset": 0}],
           "camera": {"position": [4.0, -8.0, 3.0], "target": [0.0, 0.0, 0.5], "roll_deg": 0.0,
                      "focal_length_mm": 35, "frame_mm": [36, 24], "shift_mm": [0.0, 0.0], "near_m": 0.05},
           "output": {"canvas_mm": [360, 240]}}
    castplane.render(load_scene(box))
    assert calls and all(t == 0 for t in calls)


# --------------------------------------------------------------------------- the pieces
def test_light_plane_level_counts_the_lit_faces_crossed_by_the_reference_ray():
    """``light_plane_level`` against an independent brute-force ray / polygon count on the upright spiral
    (lit faces of the object's mesh, ray from the lamp in the direction ``theta_ref``)."""
    v = load_scene(fixture("spiral_upright.json"))
    A = castplane.shadow_geometry(v)
    obj = A["objects"][0]
    mesh = next(o for o in pipeline_objects(v) if o["id"] == "c")["mesh"]
    lit = np.asarray(obj["lights"]["lamp"]["lit"], dtype=bool)
    L = np.array(v["lights"][0]["position"] + [1.0])
    theta, count = light_plane_level(mesh, lit, L, GROUND, 1e-9)
    u = np.array([math.cos(theta), math.sin(theta), 0.0])
    assert count == brute_force_hits(mesh, lit, L[:3], u) >= 1
    # every direction of the light plane hits the spiral: the level is never zero
    for deg in range(0, 360, 7):
        d = np.array([math.cos(math.radians(deg)), math.sin(math.radians(deg)), 0.0])
        assert brute_force_hits(mesh, lit, L[:3], d) >= 1


def pipeline_objects(v: dict) -> list:
    from castplane.primitives import build_object
    return [build_object(o) for o in v["objects"]]


def brute_force_hits(mesh: dict, lit, l, u) -> int:
    """Number of lit faces (planar polygons) hit by the ray ``l + t u``, ``t > 0`` (crossing-number test in
    the face plane)."""
    V = np.asarray(mesh["vertices"], dtype=np.float64)
    hits = 0
    for f, face in enumerate(mesh["faces"]):
        if not lit[f]:
            continue
        P = V[list(face)]
        n = np.asarray(mesh["face_normals"][f], dtype=np.float64)
        den = float(n @ u)
        if abs(den) < 1e-15:
            continue
        t = float(n @ (P[0] - l)) / den
        if t <= 0.0:
            continue
        X = l + t * u
        drop = int(np.argmax(np.abs(n)))
        keep = [k for k in range(3) if k != drop]
        q, poly = X[keep], P[:, keep]
        inside = False
        for a in range(len(poly)):
            p0, p1 = poly[a], poly[(a + 1) % len(poly)]
            if (p0[1] > q[1]) != (p1[1] > q[1]):
                xc = p0[0] + (q[1] - p0[1]) * (p1[0] - p0[0]) / (p1[1] - p0[1])
                if xc > q[0]:
                    inside = not inside
        hits += int(inside)
    return hits


def test_arc_level_counts_signed_turns():
    assert arc_level([(0.0, math.radians(90.0))], math.radians(45.0)) == 1
    assert arc_level([(0.0, math.radians(90.0))], math.radians(135.0)) == 0
    assert arc_level([(0.0, math.radians(90.0) + TWO_PI)], math.radians(45.0)) == 2
    assert arc_level([(0.0, math.radians(90.0) + TWO_PI)], math.radians(135.0)) == 1
    assert arc_level([(0.0, math.radians(90.0) - TWO_PI)], math.radians(135.0)) == -1
    assert arc_level([(0.0, math.radians(90.0) - TWO_PI)], math.radians(45.0)) == 0
    assert arc_level([(0.0, TWO_PI), (math.radians(10.0), math.radians(20.0))], math.radians(15.0)) == 2


def u_plate_loop():
    """The U plate of ``test_arc_pairing`` (a ``p = 2`` loop on the ground) with its shadow matrix."""
    from tests.test_arc_pairing import u_plate
    loop4, L = u_plate()
    return loop4, shadow_matrix(GROUND, L)


def test_turns_zero_is_the_default_and_turns_adds_full_turns_to_the_first_arc():
    loop4, M = u_plate_loop()
    base = shadow_loop(loop4, M, GROUND, 1e-9)
    same = shadow_loop(loop4, M, GROUND, 1e-9, turns=0)
    for a, b in zip(base["loops"], same["loops"]):
        assert np.array_equal(a["vertices"], b["vertices"]) and a["sources"] == b["sources"]
    plus = shadow_loop(loop4, M, GROUND, 1e-9, turns=1)
    assert len(plus["loops"]) == len(base["loops"])
    a0, a1 = base["loops"][0]["arcs"][0], plus["loops"][0]["arcs"][0]
    assert a1[0] == a0[0] and a1[1] == a0[1] + TWO_PI
    n_arc = lambda c: sum(1 for s in c["sources"] if isinstance(s, tuple) and s[0] == "arc")  # noqa: E731
    assert n_arc(plus["loops"][0]) == n_arc(base["loops"][0]) + 6
    for deg in (3.0, 97.0, 181.0, 275.0):
        th = math.radians(deg)
        lv = lambda r: sum(arc_level(c["arcs"], th) for c in r["loops"])  # noqa: E731
        assert lv(plus) == lv(base) + 1
    minus = shadow_loop(loop4, M, GROUND, 1e-9, turns=-1)
    assert minus["loops"][0]["arcs"][0][1] == a0[1] - TWO_PI < 0.0


def test_negative_sweep_is_sampled_clockwise():
    verts, src = [], []
    _sweep_arc(0.0, -math.radians(150.0), None, verts, src)
    angles = [round(math.degrees(math.atan2(v[1], v[0])), 9) for v in verts]
    assert angles == [-50.0, -100.0] and src == [("arc", 0), ("arc", 1)]


# --------------------------------------------------------------------------- bit identity (finding 2)
def v1_loop_order(verts, sources, kinds, outs, e12, turns=0):
    """The literal v1/v2 loop-order arc code (each ``out`` swept to the loop-order next ``in``)."""
    out_verts, out_sources = [], []
    m = len(verts)
    for k in range(m):
        out_verts.append(verts[k])
        out_sources.append(sources[k])
        if kinds[k] == "out":
            th0 = _arc_angle(verts[k], e12)
            th1 = _arc_angle(verts[(k + 1) % m], e12)
            delta = (th1 - th0) % (2.0 * math.pi)
            if not math.isfinite(delta) or delta <= 1e-12:
                delta = 2.0 * math.pi
            _sweep_arc(th0, delta, e12, out_verts, out_sources)
    return [{"vertices": np.array(out_verts, dtype=np.float64).reshape(-1, 4), "unbounded": True,
             "sources": out_sources, "arcs": []}]


def test_loop_order_pairing_with_two_excursions_is_bit_identical_to_the_v1_code(monkeypatch):
    """Fixture ``u_closed_arm_wall``: U-prism on the ground, lamp in the notch, wall beyond the **closed**
    arm: the wall loop has two excursions (out -54.5°, in 31°, out 149°, in -125.5°) whose angular pairing
    is the loop-order one.  Its components must equal the v1 loop-order polygon bit for bit; the sweep
    ``(a_in + wrap) - a_out`` on mod-2pi-reduced angles differed by an ulp in the anchor points."""
    v = load_scene(fixture("u_closed_arm_wall.json"))
    calls = []
    real = shadow_module.shadow_loop

    def spy(points4, M, pi, tol=0.0, tol_clip=None, frame=None, F=None, turns=0):
        out = real(points4, M, pi, tol, tol_clip=tol_clip, frame=frame, F=F, **({"turns": turns} if turns else {}))
        calls.append(((points4, M, pi, tol, tol_clip, frame, F), out))
        return out

    monkeypatch.setattr(pipeline, "shadow_loop", spy)
    castplane.shadow_geometry(v)
    monkeypatch.undo()
    p2 = [(args, out) for args, out in calls
          if sum(1 for s in out["sources"] if isinstance(s, tuple) and s[0] == "dir") >= 4]
    assert p2, "the wall loop must have two excursions to infinity"
    for args, out in p2:
        assert len(out["loops"]) == 1
        monkeypatch.setattr(shadow_module, "_arc_components", v1_loop_order)
        points4, M, pi, tol, tol_clip, frame, F = args
        ref = shadow_module.shadow_loop(points4, M, pi, tol, tol_clip=tol_clip, frame=frame, F=F)
        monkeypatch.undo()
        assert out["loops"][0]["sources"] == ref["loops"][0]["sources"]
        assert np.array_equal(out["loops"][0]["vertices"], ref["loops"][0]["vertices"])


# --------------------------------------------------------------------------- known limit
RING_OBJ = """v -2 -2 0\nv 2 -2 0\nv 2 2 0\nv -2 2 0\nv -1 -1 0\nv 1 -1 0\nv 1 1 0\nv -1 1 0
v -2 -2 1\nv 2 -2 1\nv 2 2 1\nv -2 2 1\nv -1 -1 1\nv 1 -1 1\nv 1 1 1\nv -1 1 1
f 1 2 10 9\nf 6 5 13 14\nf 9 10 14 13\nf 2 1 5 6
f 2 3 11 10\nf 7 6 14 15\nf 10 11 15 14\nf 3 2 6 7
f 3 4 12 11\nf 8 7 15 16\nf 11 12 16 15\nf 4 3 7 8
f 4 1 9 12\nf 5 8 16 13\nf 12 9 13 16\nf 1 4 8 5
"""


@pytest.mark.xfail(strict=True, reason="known limit (§5.1 implementation note 'Base level of the arcs at "
                                       "infinity'): a lit patch that wraps the light with every silhouette "
                                       "loop bounded has no arc to carry the base level")
def test_closed_ring_mesh_with_the_lamp_in_the_hole_is_a_known_limit(tmp_path):
    """A closed square ring (genus 1, imported mesh only) with the lamp in its hole at mid-height: the top
    silhouette loop lies entirely above the light (no shadow), the bottom one is bounded, so no arc exists
    and the drawn region is the complement of the true shadow."""
    from castplane.io import expand_scene
    (tmp_path / "ring.obj").write_text(RING_OBJ, encoding="utf-8")
    scene = {"version": "0.1", "units": "m", "up": "z",
             "objects": [{"id": "r", "type": "mesh", "path": "ring.obj"}],
             "lights": [{"id": "lamp", "type": "point", "position": [0.1, 0.05, 0.5]}],
             "receivers": [{"id": "ground", "type": "plane", "normal": [0, 0, 1], "offset": 0}],
             "camera": {"position": [4.0, -11.0, 6.0], "target": [0.0, 0.0, 0.5], "roll_deg": 0.0,
                        "focal_length_mm": 28, "frame_mm": [36, 24], "shift_mm": [0.0, 0.0], "near_m": 0.05},
             "output": {"canvas_mm": [360, 240]}}
    expanded, _notes = expand_scene(scene, base_dir=tmp_path)
    ref, got, iou = big_window_fractions(expanded, n=120)
    assert iou >= 0.99
