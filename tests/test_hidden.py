"""Sampled hidden-line removal (contract §5.1.6, §5.1.7, §5.1.11; spec §10 M4 隱藏線).

Hand values of ``wall_and_ground_hidden``, the ``N`` table, the bisection rule, the exact occluders
(against the generic mesh occluder), determinism, culled = unculled, the ``w = 0`` endpoint case and the
document invariants of the run records.  The depth-buffer reference comparison is further down.
"""

from __future__ import annotations

import json
import math
import pathlib

import numpy as np
import pytest

import castplane
from castplane import hidden
from castplane.output.geometry_json import dumps
from tests.test_receivers import fold_curved_cylinder_scene, wall_and_ground_scene

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "conformance" / "cases"


def load_case(name: str) -> dict:
    scene = json.loads((CASES / f"{name}.json").read_text(encoding="utf-8"))
    scene.pop("description", None)
    return scene


def render_hidden(scene: dict, **kw) -> dict:
    return castplane.render(castplane.load_scene(scene), hidden_lines=True, **kw)


def curved_unbounded_scene() -> dict:
    """``hidden_lines_curved_unbounded`` (contract §5.1.11): a sphere and a cylinder taller than the lamp,
    so both ground shadows are unbounded (a hyperbola branch and an open cylinder shadow), switch on."""
    return {
        "version": "0.1", "units": "m", "up": "z",
        "objects": [{"id": "ball", "type": "sphere", "radius": 0.6, "transform": {"position": [1.4, 1.5, 0]}},
                    {"id": "post", "type": "cylinder", "radius": 0.3, "height": 2.0,
                     "transform": {"position": [-1.4, 1.8, 0]}}],
        "lights": [{"id": "lamp", "type": "point", "position": [0, 0.2, 1.0]}],
        "receivers": [{"id": "ground", "type": "plane", "normal": [0, 0, 1], "offset": 0}],
        "camera": {"position": [0.5, -6, 2.2], "target": [0, 2, 0.6], "focal_length_mm": 35, "frame_mm": [36, 24]},
        "output": {"canvas_mm": [360, 240], "hidden_lines": True},
    }


def vp_in_canvas_scene() -> dict:
    """``hidden_lines_vp_in_canvas``: ``degenerate_vertex_above_point_light`` with the switch on."""
    scene = load_case("degenerate_vertex_above_point_light")
    scene.setdefault("output", {})["hidden_lines"] = True
    return scene


# --------------------------------------------------------------------------- constants and the N table
@pytest.mark.parametrize("length, n", [(0.1, 8), (7.3, 8), (8.0, 8), (1023.9, 1024), (4095.9, 4096), (5000.0, 4096),
                                       (10.0, 10)])
def test_sample_count_table(length, n):
    assert hidden.hlr_sample_count(length) == n
    assert int(hidden._sample_counts([length])[0]) == n


def test_constants_and_stated_tolerance():
    assert (hidden.HLR_SPACING_MM, hidden.HLR_MIN_SAMPLES, hidden.HLR_MAX_SAMPLES, hidden.HLR_BISECTIONS,
            hidden.HLR_RAY_EPS) == (1.0, 8, 4096, 6, 1e-5)
    assert hidden.hlr_tol_mm(100.0) == 1.0 / 64.0
    assert hidden.hlr_tol_mm(4096.0) == pytest.approx(0.015625)
    assert hidden.hlr_tol_mm(8192.0) == pytest.approx(8192.0 / 262144.0)


# --------------------------------------------------------------------------- the sampling / bisection rule
def test_classify_curve_single_boundary_within_the_bracket_width():
    for b in (0.3, 0.5 + 1e-7, 0.91):
        vis, runs = hidden.classify_curve(lambda p, b=b: p < b, 0.0, 1.0, 50.0)
        assert vis == "partial"
        assert [r[2] for r in runs] == [True, False]
        assert runs[0][0] == 0.0 and runs[-1][1] == 1.0 and runs[0][1] == runs[1][0]
        assert abs(runs[0][1] - b) <= 1.0 / (64 * 50) / 2 + 1e-15


def test_classify_curve_uniform_and_parameter_range():
    assert hidden.classify_curve(lambda p: p >= 0.0, 0.0, 1.0, 3.0) == ("visible", [])
    assert hidden.classify_curve(lambda p: p < -1.0, 0.0, 1.0, 3.0) == ("hidden", [])
    seen = []
    hidden.classify_curve(lambda p: seen.append(np.array(p)) or np.ones(len(p), dtype=bool), 2.0, 6.0, 10.0)
    assert np.allclose(seen[0], 2.0 + 4.0 * (np.arange(10) + 0.5) / 10)      # midpoints, N = 10


def test_bisection_keeps_lo_half_iff_the_midpoint_state_differs():
    """Two state changes inside one bracket: the rule follows v(m) != v(lo) deterministically (contract
    §5.1.6.4), so the boundary lands in the first change found by that walk, not in the bracket centre."""
    N = 8
    lo0, hi0 = 2.5 / N, 3.5 / N             # samples 2 and 3 (visible, hidden)
    # hidden on [0.33, 0.34] and on [0.40, 1]: the midpoint 0.375 is visible again
    vis, runs = hidden.classify_curve(lambda p: ~(((p >= 0.33) & (p <= 0.34)) | (p >= 0.40)), 0.0, 1.0, 8.0)
    assert vis == "partial"
    b = runs[0][1]
    assert lo0 < b < hi0
    assert abs(b - 0.40) <= (hi0 - lo0) / 64


# --------------------------------------------------------------------------- occluders
def _box_scene_record(kind: str, **shape):
    obj = {"id": "o", "type": kind, "transform": {"position": [0.3, -0.2, 0.1], "rotation_deg": [10, -20, 35]}}
    obj.update(shape)
    scene = castplane.load_scene({"version": "0.1", "units": "m", "up": "z", "objects": [obj],
                                  "lights": [{"id": "l", "type": "point", "position": [0, 0, 5]}],
                                  "receivers": [{"id": "g", "type": "plane", "normal": [0, 0, 1], "offset": 0}],
                                  "camera": {"position": [0, -8, 3], "target": [0, 0, 0.5], "focal_length_mm": 35,
                                             "frame_mm": [36, 24]},
                                  "output": {"canvas_mm": [360, 240]}})
    return castplane.shadow_geometry(scene)["objects"][0]


@pytest.mark.parametrize("kind, shape", [
    ("box", {"size": [1.2, 0.7, 0.9]}),
    ("prism", {"polygon": [[-1, -1], [1, -1], [1, 1], [0.5, 1], [0.5, -0.5], [-0.5, -0.5], [-0.5, 1], [-1, 1]],
               "height": 0.8}),
])
def test_exact_occluders_agree_with_the_generic_mesh_occluder(kind, shape):
    rec = _box_scene_record(kind, **shape)
    exact = hidden.occluder(rec)
    generic = hidden._mesh_occluder(rec)
    assert exact["kind"] == kind and generic["kind"] == "mesh"
    rng = np.random.default_rng(7)
    O = rng.uniform(-3, 3, size=(4000, 3))
    target = rec["frame"][1] + rng.uniform(-0.8, 0.8, size=(4000, 3)) + [0.0, 0.0, 0.4]
    D = (target - O) * rng.uniform(0.2, 2.0, size=(4000, 1))
    t1 = hidden.first_hit(exact, O, D, 1e-9)
    t2 = hidden.first_hit(generic, O, D, 1e-9)
    assert np.array_equal(np.isinf(t1), np.isinf(t2))
    fin = np.isfinite(t1)
    assert fin.sum() > 500
    assert np.max(np.abs(t1[fin] - t2[fin])) < 1e-9
    # the generic occluder built from triangles (M5 records carry ``triangles``) gives the same answer
    mesh = rec["mesh"]
    tris = []
    for f in mesh["faces"]:
        tris.extend([f[0], f[i], f[i + 1]] for i in range(1, len(f) - 1))
    if kind == "box":     # convex faces: the fan triangulation is exact
        t3 = hidden.first_hit(hidden._mesh_occluder(dict(rec, triangles=np.array(tris))), O, D, 1e-9)
        assert np.array_equal(np.isinf(t1), np.isinf(t3)) and np.max(np.abs(t1[fin] - t3[fin])) < 1e-9


def test_unknown_kind_uses_the_generic_occluder_and_never_raises():
    rec = _box_scene_record("box", size=[1, 1, 1])
    weird = dict(rec, type="teapot", shape={})
    occ = hidden.occluder(weird)
    assert occ["kind"] == "mesh"
    t = hidden.first_hit(occ, np.zeros((1, 3)) + [0, -5, 0.5], np.array([[0.3, 5, 0.1]]))
    assert np.isfinite(t[0])
    assert hidden.occluder({"id": "x", "type": "teapot"})["kind"] == "mesh"           # no mesh at all
    assert hidden.first_hit(hidden.occluder({"id": "x", "type": "teapot"}), [0, 0, 0], np.ones((2, 3)))[0] == math.inf


def test_curved_occluders_first_hit_closed_form():
    sc = {"version": "0.1", "units": "m", "up": "z",
          "objects": [{"id": "s", "type": "sphere", "radius": 1.0, "transform": {"position": [0, 0, 0]}},
                      {"id": "c", "type": "cylinder", "radius": 0.5, "height": 2.0, "transform": {"position": [5, 0, 0]}},
                      {"id": "k", "type": "cone", "radius": 1.0, "height": 2.0, "transform": {"position": [-5, 0, 0]}}],
          "lights": [{"id": "l", "type": "point", "position": [0, 0, 9]}],
          "receivers": [{"id": "g", "type": "plane", "normal": [0, 0, 1], "offset": 0}],
          "camera": {"position": [0, -9, 3], "target": [0, 0, 0.5], "focal_length_mm": 35, "frame_mm": [36, 24]},
          "output": {"canvas_mm": [360, 240]}}
    A = castplane.shadow_geometry(castplane.load_scene(sc))
    sphere, cyl, cone = (hidden.occluder(o) for o in A["objects"])
    O = np.array([[0, -5, 1.0]])
    assert hidden.first_hit(sphere, O, np.array([[0, 1, 0]]))[0] == pytest.approx(4.0)        # centre (0,0,1)
    assert hidden.first_hit(cyl, np.array([[5, -5, 1.0]]), np.array([[0, 1, 0]]))[0] == pytest.approx(4.5)
    assert hidden.first_hit(cyl, np.array([[5, 0, 5.0]]), np.array([[0, 0, -1]]))[0] == pytest.approx(3.0)   # top disc
    assert hidden.first_hit(cone, np.array([[-5, -5, 1.0]]), np.array([[0, 1, 0]]))[0] == pytest.approx(4.5)
    assert hidden.first_hit(cone, np.array([[-5, 0, -3.0]]), np.array([[0, 0, 1]]))[0] == pytest.approx(3.0)  # base
    assert hidden.first_hit(cone, np.array([[-5, -5, 2.5]]), np.array([[0, 1, 0]]))[0] == math.inf          # above apex
    # inside the sphere: the exit crossing
    assert hidden.first_hit(sphere, np.array([[0, 0, 1.0]]), np.array([[1, 0, 0]]))[0] == pytest.approx(1.0)


def test_occlusion_predicate_cases():
    """A front-face point is not occluded by its own object, a back-edge point is, a point in the notch of a
    concave prism is not, a camera inside a solid sees nothing (contract §5.1.6.3)."""
    rec = _box_scene_record("box", size=[1, 1, 1])
    occ = hidden.occluder(rec)
    R, pos = rec["frame"]
    V = rec["mesh"]["vertices"]
    C = pos + R @ np.array([0.0, -6.0, 3.0])               # in front of the local -y face, above
    front = 0.5 * (V[0] + V[1])                             # bottom edge of the front face (-y)
    back = 0.5 * (V[2] + V[3])                              # bottom edge of the back face (+y)
    assert not hidden.occluded([occ], C, front[None, :])[0]
    assert hidden.occluded([occ], C, back[None, :])[0]
    centre = pos + R @ np.array([0.0, 0.0, 0.5])
    beyond = np.array([centre + 2.0 * (P - centre) for P in (front, back, V[5])])
    assert hidden.occluded([occ], centre, beyond).all()                       # the exit crossing comes first
    assert not hidden.occluded([occ], centre, np.array([front, back, V[5]])).any()   # its own surface: t = 1
    u = _box_scene_record("prism", polygon=[[-1, -1], [1, -1], [1, 1], [0.5, 1], [0.5, -0.5], [-0.5, -0.5],
                                            [-0.5, 1], [-1, 1]], height=0.8)
    occ_u = hidden.occluder(u)
    R, pos = u["frame"]
    notch = pos + R @ np.array([0.0, 0.2, 0.0])                 # notch floor
    cam_above = pos + R @ np.array([0.0, 0.25, 6.0])            # straight above the notch
    assert not hidden.occluded([occ_u], cam_above, notch[None, :])[0]
    cam_side = pos + R @ np.array([4.0, 0.2, 0.3])              # through the right arm
    assert hidden.occluded([occ_u], cam_side, notch[None, :])[0]


def test_plate_and_ground_occluders():
    A = castplane.shadow_geometry(castplane.load_scene(wall_and_ground_scene()))
    occs = hidden.scene_occluders(A)
    assert [o["kind"] for o in occs] == ["box", "ground", "plate"]
    plate, ground = occs[2], occs[1]
    C = np.array([0.0, -1.0, 1.6])
    assert hidden.occluded([plate], C, np.array([[0.0, 7.0, 0.5]]))[0]          # behind the wall
    assert not hidden.occluded([plate], C, np.array([[0.0, 7.0, 4.0]]))[0]      # seen above the wall
    assert not hidden.occluded([plate], C, np.array([[0.0, 6.0, 1.0]]))[0]      # on the wall itself
    assert hidden.occluded([ground], C, np.array([[0.0, 3.0, -0.2]]))[0]        # below the ground
    assert not hidden.occluded([ground], C, np.array([[0.0, 3.0, 0.0]]))[0]     # on the ground
    no_ground = hidden.scene_occluders(dict(A, receivers=[dict(A["receivers"][1], index=0)]))
    assert [o["kind"] for o in no_ground] == ["box", "plate"]


# --------------------------------------------------------------------------- drawn 4-D geometry
def test_drawn_segment_4d_reproduces_the_drawn_endpoints():
    scene = castplane.load_scene(load_case("degenerate_point_behind_camera"))
    A = castplane.shadow_geometry(scene)
    B = castplane.project_scene(scene, A)
    doc = castplane.compose(scene, B)
    cam = B["camera"]
    checked = clipped = 0
    for e in doc["edges"]:
        X = [np.array(doc["points"][n]["world"] + [1.0]) for n in (e["from"], e["to"])]
        res = hidden.drawn_segment_4d(cam, X[0], X[1])
        assert (res is None) == (e["segment"] is None)
        if res is None:
            continue
        for Y, uv in zip(res, e["segment"]):
            x = cam["P"] @ Y
            assert np.allclose(x[:2] / x[2], uv, atol=1e-9)
        checked += 1
        clipped += not (np.allclose(res[0] / res[0][3], X[0]) and np.allclose(res[1] / res[1][3], X[1]))
    assert checked >= 5 and clipped >= 1


def test_clip_polygon_4d_matches_the_drawn_polygons_and_marks_clip_edges():
    for name in ("degenerate_vertex_above_point_light", "example_directional", "random_seed3_3objects",
                 "degenerate_point_behind_camera", "camera_roll_and_shift"):
        scene = castplane.load_scene(load_case(name))
        A = castplane.shadow_geometry(scene)
        B = castplane.project_scene(scene, A)
        doc = castplane.compose(scene, B)
        for sh, a_sh in zip(doc["shadows"], A["shadows"]):
            for poly, loop in zip(sh["polygons"], a_sh["loops"]):
                pts, ids = hidden.clip_polygon_4d(B["camera"], loop["vertices"])
                assert len(pts) == len(poly), name
                if len(poly):
                    x = pts @ B["camera"]["P"].T
                    assert np.allclose(x[:, :2] / x[:, 2:3], poly, atol=1e-6)
                    assert all(i is None or 0 <= i < len(loop["vertices"]) for i in ids)
    # the w = 0 case: two direction vertices (the drawn horizon segment) and one clip edge
    scene = castplane.load_scene(load_case("degenerate_vertex_above_point_light"))
    A = castplane.shadow_geometry(scene)
    B = castplane.project_scene(scene, A)
    pts, ids = hidden.clip_polygon_4d(B["camera"], A["shadows"][0]["loops"][0]["vertices"])
    assert int(np.sum(pts[:, 3] == 0.0)) == 2 and ids.count(None) == 1


# --------------------------------------------------------------------------- wall_and_ground_hidden (§5.1.11)
def _edge(doc, a, b):
    found = [e for e in doc["edges"] if {e["from"], e["to"]} == {a, b}]
    assert len(found) == 1
    return found[0]


def test_wall_and_ground_hidden_hand_values():
    doc = render_hidden(wall_and_ground_scene())["geometry"]
    assert doc["hidden_lines"] is True
    base = _edge(doc, "wall.b0", "wall.b1")
    assert base["visibility"] == "partial"
    runs = base["runs"]
    assert [r["visible"] for r in runs] == [True, False, True]
    ell = math.dist(*base["segment"])
    assert ell == pytest.approx(223.1516, abs=1e-4)
    bounds = [(0.0, 23 / 60), (23 / 60, 37 / 60), (37 / 60, 1.0)]
    for r, (s0, s1) in zip(runs, bounds):
        assert r["s"][0] == pytest.approx(s0, abs=1e-3) and r["s"][1] == pytest.approx(s1, abs=1e-3)
        assert r["t"] == pytest.approx(r["s"], abs=1e-12)            # picture-plane parallel: s = t
    assert runs[0]["mm"][0] == 0.0 and runs[-1]["mm"][1] == pytest.approx(223.1516, abs=1e-4)
    assert runs[0]["mm"][1] == pytest.approx(85.5415, abs=0.05)
    assert runs[1]["mm"][1] == pytest.approx(137.6102, abs=0.05)
    for a, b in zip(runs, runs[1:]):
        assert a["s"][1] == b["s"][0] and a["mm"][1] == b["mm"][0]
    # the ground shadow edge (0.75, 5, 0) -> (0.75, 6.5, 0): hidden by the plate beyond y = 6
    sh = next(s for s in doc["shadows"] if s["receiver"] == "ground" and s["object"] == "crate")
    poly, recs = sh["polygons"][0], sh["polygon_edges"][0]
    assert len(recs) == len(poly)
    k = next(i for i in range(len(poly))
             if abs(poly[i][0] - 32.405452361298636) < 1e-6 and abs(poly[(i + 1) % len(poly)][0] - 26.078616180680637) < 1e-6)
    rec = recs[k]
    assert rec["visibility"] == "partial" and [r["visible"] for r in rec["runs"]] == [True, False]
    s_b, t_b = rec["runs"][0]["s"][1], rec["runs"][0]["t"][1]
    assert s_b == pytest.approx(0.713073, abs=1e-3)
    assert t_b == pytest.approx(2 / 3, abs=1e-3)
    a, b = np.array(poly[k]), np.array(poly[(k + 1) % len(poly)])
    assert np.allclose(a + s_b * (b - a), [27.8939534, -29.5611244], atol=0.05)
    # the crate: five hidden back edges, seven visible front edges; the wall top edge is visible
    hidden_edges = {("crate.v0", "crate.v3"), ("crate.v1", "crate.v2"), ("crate.v2", "crate.v3"),
                    ("crate.v2", "crate.v6"), ("crate.v3", "crate.v7")}
    for e in doc["edges"]:
        if e["object"] != "crate":
            continue
        expected = "hidden" if (e["from"], e["to"]) in hidden_edges else "visible"
        assert e["visibility"] == expected, (e["from"], e["to"])
        assert e["runs"] == []
    assert sum(e["visibility"] == "hidden" for e in doc["edges"] if e["object"] == "crate") == 5
    assert sum(e["visibility"] == "visible" for e in doc["edges"] if e["object"] == "crate") == 7
    assert _edge(doc, "wall.b2", "wall.b3")["visibility"] == "visible"


def test_switch_off_documents_carry_the_switch_off_values():
    doc = castplane.render(castplane.load_scene(wall_and_ground_scene()))["geometry"]
    assert doc["hidden_lines"] is False
    assert all(e["visibility"] == "visible" and e["runs"] == [] for e in doc["edges"])
    assert all(s["polygon_edges"] == [] for s in doc["shadows"])


# --------------------------------------------------------------------------- determinism, culling, purity
DETERMINISM_SCENES = {
    "wall_and_ground_hidden": wall_and_ground_scene,
    "fold_curved_cylinder": fold_curved_cylinder_scene,
    "hidden_lines_curved_unbounded": curved_unbounded_scene,
    "hidden_lines_vp_in_canvas": vp_in_canvas_scene,
}


@pytest.mark.parametrize("name", sorted(DETERMINISM_SCENES))
def test_render_twice_with_hidden_lines_is_byte_identical(name):
    make = DETERMINISM_SCENES[name]
    r1, r2 = render_hidden(make()), render_hidden(make())
    assert dumps(r1["geometry"]) == dumps(r2["geometry"])
    assert r1["svg"] == r2["svg"]


@pytest.mark.parametrize("name", ["wall_and_ground_hidden", "fold_curved_cylinder", "hidden_lines_curved_unbounded",
                                  "example_construction_demo", "random_seed0_3objects"])
def test_culled_equals_unculled(name):
    make = DETERMINISM_SCENES.get(name) or (lambda: load_case(name))
    scene = castplane.load_scene(make())
    A = castplane.shadow_geometry(scene)
    B = castplane.project_scene(scene, A)
    culled = hidden.classify_document(castplane.compose(scene, B, hidden_lines=False), A, B, cull=True)
    plain = hidden.classify_document(castplane.compose(scene, B, hidden_lines=False), A, B, cull=False)
    assert dumps(culled) == dumps(plain)
    assert any(e["visibility"] != "visible" for e in culled["edges"]) or any(
        r["visibility"] != "visible" for s in culled["shadows"] for pe in s["polygon_edges"] for r in pe)


def test_image_bounds_cull_data():
    scene = castplane.load_scene(wall_and_ground_scene())
    A = castplane.shadow_geometry(scene)
    B = castplane.project_scene(scene, A)
    occs = hidden.scene_occluders(A)
    b = [hidden.image_bounds(o, B["camera"]) for o in occs]
    assert b[1] is None                                    # the unbounded ground is never culled
    u0, u1, v0, v1, dmin = b[0]
    assert u0 < u1 and v0 < v1 and dmin > 0
    near = castplane.load_scene(load_case("degenerate_point_behind_camera"))
    A2 = castplane.shadow_geometry(near)
    B2 = castplane.project_scene(near, A2)
    assert hidden.image_bounds(hidden.scene_occluders(A2)[0], B2["camera"]) is None   # a hull point behind


def test_classification_never_mutates_stage_a_or_b():
    scene = castplane.load_scene(fold_curved_cylinder_scene())
    A = castplane.shadow_geometry(scene)
    B = castplane.project_scene(scene, A)
    before_a = dumps(A)
    before_b = dumps({k: v for k, v in B.items() if k != "A"})
    doc = castplane.compose(scene, B, hidden_lines=True)
    assert dumps(A) == before_a
    assert dumps({k: v for k, v in B.items() if k != "A"}) == before_b
    # the documents of the same B with the switch off are unaffected (fresh lists everywhere)
    off = castplane.compose(scene, B, hidden_lines=False)
    assert all(e["visibility"] == "visible" and e["runs"] == [] for e in off["edges"])
    assert any(e["visibility"] != "visible" for e in doc["edges"])


# --------------------------------------------------------------------------- run-record invariants (§5.1.7)
def _check_straight(item, where):
    vis, runs = item["visibility"], item["runs"]
    assert vis in ("visible", "hidden", "partial"), where
    assert (len(runs) > 0) == (vis == "partial"), where
    if runs:
        assert runs[0]["s"][0] == 0.0 and runs[-1]["s"][1] == 1.0, where
        assert runs[0]["t"][0] == 0.0 and runs[-1]["t"][1] == 1.0, where
        for a, b in zip(runs, runs[1:]):
            assert a["s"][1] == b["s"][0] and a["visible"] != b["visible"], where
            assert a["mm"][1] == b["mm"][0], where
        for r in runs:
            assert r["s"][0] < r["s"][1] and r["mm"][0] <= r["mm"][1], where
            assert set(r) == {"s", "t", "mm", "visible"}, where


def _check_conic(c, where):
    vis, runs = c["visibility"], c["runs"]
    assert (len(runs) > 0) == (vis == "partial"), where
    if vis == "visible":
        assert c["hidden_polylines"] == [], where
    else:
        assert c["ellipses"] == [] and c["hidden_polylines"], where
    if runs:
        by = {}
        for r in runs:
            assert isinstance(r["interval"], int) and set(r) == {"interval", "theta", "mm", "visible"}, where
            by.setdefault(r["interval"], []).append(r)
        assert sorted(by) == list(range(len(c["visible"]))), where
        for k, rr in by.items():
            lo, hi = c["visible"][k]
            assert rr[0]["mm"][0] == 0.0 and rr[0]["theta"][0] == lo and rr[-1]["theta"][1] == hi, where
            for a, b in zip(rr, rr[1:]):
                assert a["mm"][1] == b["mm"][0] and a["visible"] != b["visible"], where


def check_document(doc: dict, label: str) -> int:
    n = 0
    for e in doc["edges"]:
        _check_straight(e, (label, e["from"], e["to"]))
        n += 1
    for o in doc["outlines"]:
        for g in o["generators"]:
            _check_straight(g, (label, g["from"]))
        for c in o["conics"]:
            _check_conic(c, (label, o["object"], c["which"]))
    for f in doc["form_shadow"]:
        for t in f["terminator"]:
            if "segment" in t:
                _check_straight(t, (label, t["segment"]))
            else:
                _check_conic(t, (label, f["object"]))
    for s in doc["shadows"]:
        assert len(s["polygon_edges"]) == len(s["polygons"]), label
        for poly, recs in zip(s["polygons"], s["polygon_edges"]):
            assert len(recs) == (len(poly) if len(poly) >= 3 else 0), label
            for r in recs:
                _check_straight(r, (label, s["object"]))
        for c in s["conics"]:
            _check_conic(c, (label, s["object"], c["which"]))
    return n


@pytest.mark.parametrize("name", sorted(p.stem for p in CASES.glob("*.json")))
def test_run_records_on_every_conformance_case(name):
    r = render_hidden(load_case(name))
    check_document(r["geometry"], name)
    json.loads(dumps(r["geometry"]))           # finite, serialisable (allow_nan=False)


@pytest.mark.parametrize("name", ["hidden_lines_curved_unbounded", "hidden_lines_vp_in_canvas"])
def test_named_m4_hidden_scenes_render_finite(name):
    r = render_hidden(DETERMINISM_SCENES[name]())
    doc = r["geometry"]
    check_document(doc, name)
    text = dumps(doc)
    assert "NaN" not in text and "Infinity" not in text
    if name == "hidden_lines_curved_unbounded":
        assert all(s["unbounded"] for s in doc["shadows"])
        assert any(c["visibility"] == "partial" for s in doc["shadows"] for c in s["conics"])
    else:
        # the w = 0 endpoint: the shadow edge running to the vanishing point is a subject (not all visible)
        recs = doc["shadows"][0]["polygon_edges"][0]
        assert any(r["visibility"] != "visible" for r in recs)


# --------------------------------------------------------------------------- SVG (contract §5.1.8, §5.0.6)
import xml.etree.ElementTree as ET

from castplane.output import svg as svg_mod

SVG_NS = "{http://www.w3.org/2000/svg}"


def _tree(svg_text: str):
    return ET.fromstring(svg_text)


def _group(root, gid):
    found = [g for g in root.iter(f"{SVG_NS}g") if g.get("id") == gid]
    assert len(found) == 1, gid
    return found[0]


def _child_ids(g):
    return [c.get("id") for c in g if c.tag == f"{SVG_NS}g"]


def _drawn(g):
    return [c for c in g.iter() if c.tag in (f"{SVG_NS}line", f"{SVG_NS}polyline", f"{SVG_NS}path",
                                             f"{SVG_NS}ellipse", f"{SVG_NS}polygon")]


@pytest.mark.parametrize("name", sorted(DETERMINISM_SCENES))
def test_hidden_groups_come_first_in_their_layers_with_the_stated_style(name):
    r = render_hidden(DETERMINISM_SCENES[name]())
    root = _tree(r["svg"])
    ids = [g.get("id") for g in root.iter(f"{SVG_NS}g")]
    assert len(ids) == len(set(ids))                                     # every id unique
    for layer, colour in (("objects", "#111"), ("form_shadow", "#335"), ("cast_shadow", "#000")):
        lg = _group(root, layer)
        assert _child_ids(lg)[0] == f"{layer}.hidden"
        hg = _group(root, f"{layer}.hidden")
        assert hg.get("stroke") == colour and hg.get("stroke-width") == "0.15"
        assert hg.get("stroke-dasharray") == "0.5 0.5" and hg.get("fill") == "none"
        for sub in _child_ids(hg):
            assert sub.startswith(f"{layer}.hidden.")
    doc = r["geometry"]
    # cast-shadow fill paths are not stroked; their outline runs are, in the .outline groups
    cs = _group(root, "cast_shadow")
    paths = [p for g in cs if g.get("id", "").startswith("cast_shadow.") and g.get("id") != "cast_shadow.hidden"
             for p in g if p.tag == f"{SVG_NS}path"]
    assert paths and all(p.get("stroke") == "none" for p in paths)
    first = doc["receivers"][0]["id"]
    for sh in doc["shadows"]:
        if not any(len(p) >= 3 for p in sh["polygons"]):
            continue
        if all(r_["visibility"] == "hidden" for pe in sh["polygon_edges"] for r_ in pe):
            continue
        gid = svg_mod._shadow_subgroup_id(sh, first, "outline")
        g = _group(root, gid)
        assert g.get("stroke") == "#000" and g.get("stroke-width") == "0.25"


def test_wall_base_edge_is_split_at_the_run_boundaries():
    r = render_hidden(wall_and_ground_scene())
    doc, root = r["geometry"], _tree(r["svg"])
    base = _edge(doc, "wall.b0", "wall.b1")
    (ua, va), (ub, vb) = base["segment"]
    W, H = doc["canvas_mm"]
    hidden_lines = list(_group(root, "objects.hidden.wall"))
    assert len(hidden_lines) == 1
    s0, s1 = base["runs"][1]["s"]
    x1 = float(hidden_lines[0].get("x1"))
    x2 = float(hidden_lines[0].get("x2"))
    assert x1 == pytest.approx(ua + s0 * (ub - ua) + W / 2, abs=1e-4)
    assert x2 == pytest.approx(ua + s1 * (ub - ua) + W / 2, abs=1e-4)
    front = _group(root, "objects.wall.front")
    ys = [round(float(l.get("y1")), 3) for l in front if l.tag == f"{SVG_NS}line"]
    assert ys.count(round(H / 2 - va, 3)) >= 2                         # the two visible pieces of the base edge
    # the crate's five hidden edges are in objects.hidden.crate, its seven visible ones in .front
    assert len(list(_group(root, "objects.hidden.crate"))) == 5
    assert len([c for c in _group(root, "objects.crate.front")]) == 7
    assert "objects.crate.back" not in [g.get("id") for g in root.iter(f"{SVG_NS}g")]


@pytest.mark.parametrize("name", sorted(DETERMINISM_SCENES))
def test_omit_style_keeps_the_ids_and_draws_nothing_hidden(name):
    scene = castplane.load_scene(DETERMINISM_SCENES[name]())
    dashed = castplane.render(scene, hidden_lines=True)
    omit = castplane.render(scene, hidden_lines=True, hidden_style="omit")
    assert dumps(dashed["geometry"]) == dumps(omit["geometry"])
    rd, ro = _tree(dashed["svg"]), _tree(omit["svg"])
    assert [g.get("id") for g in rd.iter(f"{SVG_NS}g")] == [g.get("id") for g in ro.iter(f"{SVG_NS}g")]
    drew_hidden = False
    for layer in ("objects", "form_shadow", "cast_shadow"):
        assert _drawn(_group(ro, f"{layer}.hidden")) == []
        drew_hidden = drew_hidden or bool(_drawn(_group(rd, f"{layer}.hidden")))
    assert drew_hidden
    # outside the hidden groups the two SVGs are identical
    for layer in ("objects", "form_shadow", "cast_shadow"):
        for gid in _child_ids(_group(rd, layer))[1:]:
            assert ET.tostring(_group(rd, gid)) == ET.tostring(_group(ro, gid))
    # the scene's own output.hidden_style is the default of render
    scene_omit = castplane.load_scene(dict(DETERMINISM_SCENES[name](), output=dict(
        DETERMINISM_SCENES[name]().get("output", {}), hidden_style="omit")))
    assert castplane.render(scene_omit, hidden_lines=True)["svg"] == omit["svg"]


def test_hidden_groups_exist_only_when_the_switch_is_on():
    scene = castplane.load_scene(wall_and_ground_scene())
    off = castplane.render(scene)["svg"]
    assert ".hidden" not in off and ".outline" not in off and '<path d="M' in off and 'Z" stroke="none"/>' not in off
    on = castplane.render(scene, hidden_lines=True)["svg"]
    assert 'id="objects.hidden"' in on and 'id="cast_shadow.lamp.crate.wall.outline"' in on
    # a hidden-lines document written with a layer subset keeps the subset and the fixed order
    doc = castplane.render(scene, hidden_lines=True)["geometry"]
    sub = svg_mod.write_svg(doc, layers=["cast_shadow", "objects"])
    root = _tree(sub)
    assert [g.get("id") for g in root if g.tag == f"{SVG_NS}g"] == ["objects", "cast_shadow"]
    with pytest.raises(ValueError):
        svg_mod.write_svg(doc, hidden_style="dotted")


def test_partly_hidden_conics_become_arcs_and_hidden_polylines():
    r = render_hidden(curved_unbounded_scene())
    doc, root = r["geometry"], _tree(r["svg"])
    post = next(o for o in doc["outlines"] if o["object"] == "post")
    assert any(c["visibility"] == "hidden" and c["hidden_polylines"] and not c["arcs"] for c in post["conics"])
    sh = next(s for s in doc["shadows"] if s["object"] == "post")
    c = sh["conics"][0]
    assert c["visibility"] == "partial" and c["ellipses"] == []
    assert len(c["arcs"]) + len(c["polylines"]) == sum(1 for r_ in c["runs"] if r_["visible"])
    assert len(c["hidden_polylines"]) == sum(1 for r_ in c["runs"] if not r_["visible"])
    # the arcs keep the run's theta range
    vis_runs = [r_ for r_ in c["runs"] if r_["visible"]]
    for arc in c["arcs"]:
        assert any(arc["theta"] == r_["theta"] for r_ in vis_runs)
    hidden_cs = _group(root, "cast_shadow.hidden.lamp")
    assert any(e.tag == f"{SVG_NS}polyline" for e in hidden_cs)


# --------------------------------------------------------------------------- depth-buffer reference (§5.1.11)
# For every run of every subject drawable: samples every 0.5 mm along the run (0.3 mm kept clear of each end)
# against the three-valued depth buffer of tests/reference/zbuffer.py, and every run boundary against the
# point-wise ray cast 0.15 mm before and after it.  World points of the samples are recovered by the
# reference itself (back-projection of the image point onto the drawable's 3-D line, its receiver plane, or
# the exact circle / its exact shadow), never through castplane.
from tests.reference import random_scenes
from tests.reference import zbuffer as zb

ZB_STEP_MM = 0.5
ZB_END_MM = 0.3
ZB_BOUNDARY_MM = 0.15


def _straight_runs(item: dict, length: float) -> list:
    """``[(m0, m1, visible)]`` of a straight drawable (one run for a non-partial one)."""
    if item["visibility"] == "partial":
        return [(r["mm"][0], r["mm"][1], r["visible"]) for r in item["runs"]]
    return [(0.0, length, item["visibility"] == "visible")]


def _circle_point(circle: dict, theta) -> np.ndarray:
    theta = np.asarray(theta, dtype=np.float64).reshape(-1)
    c, e1, e2 = (np.asarray(circle[k], dtype=np.float64) for k in ("centre", "e1", "e2"))
    r = float(circle["radius"])
    return c[None, :] + r * (np.cos(theta)[:, None] * e1[None, :] + np.sin(theta)[:, None] * e2[None, :])


def _shadow_of(P: np.ndarray, light: dict, plane) -> np.ndarray:
    """Exact cast shadow on the plane ``n·x + d = 0`` of the world points ``P`` (central / parallel projection)."""
    n, d = np.asarray(plane[:3], dtype=np.float64), float(plane[3])
    if light["type"] == "point":
        L = np.asarray(light["position"], dtype=np.float64)
        lam = -(L @ n + d) / ((P - L[None, :]) @ n)
        return L[None, :] + lam[:, None] * (P - L[None, :])
    D = np.asarray(light["direction"], dtype=np.float64)
    mu = -(P @ n + d) / float(D @ n)
    return P + mu[:, None] * D[None, :]


class _Collector:
    """Buffer samples and boundary probes of one document, then evaluate them in bulk."""

    def __init__(self, scene: dict):
        self.scene = scene
        self.cm = zb.camera_model(scene)
        self.samples = []         # (uv (n,2), X (n,3), visible bool, tag)
        self.bounds = []          # (X_before (3,), X_after (3,), vis_before, vis_after, tag)

    # straight drawables: image segment a -> b, world_of(uv) back-projection
    def straight(self, seg, item: dict, world_of, tag: str) -> None:
        a, b = np.asarray(seg[0], dtype=np.float64), np.asarray(seg[1], dtype=np.float64)
        du, dv = float(b[0] - a[0]), float(b[1] - a[1])
        length = math.sqrt(du * du + dv * dv)
        if length <= 2 * ZB_END_MM:
            return
        runs = _straight_runs(item, length)

        def uv_at(m):
            s = np.asarray(m, dtype=np.float64).reshape(-1) / length
            return a[None, :] + s[:, None] * (b - a)[None, :]

        for m0, m1, vis in runs:
            m = np.arange(m0 + ZB_END_MM, m1 - ZB_END_MM + 1e-12, ZB_STEP_MM)
            if m.shape[0]:
                uv = uv_at(m)
                self.samples.append((uv, world_of(uv), bool(vis), tag))
        for (_a0, m_b, v0), (_b0, _b1, v1) in zip(runs, runs[1:]):
            mm = np.clip([m_b - ZB_BOUNDARY_MM, m_b + ZB_BOUNDARY_MM], 0.0, length)
            X = world_of(uv_at(mm))
            self.bounds.append((X[0], X[1], bool(v0), bool(v1), tag))

    # conic drawables: the exact curve X(theta) (circle point, or its shadow on the receiver)
    def conic(self, entry: dict, world_of_theta, tag: str) -> None:
        if not entry.get("visible"):
            return
        by_interval = {}
        for r in entry["runs"]:
            by_interval.setdefault(r["interval"], []).append((r["theta"][0], r["theta"][1], r["visible"]))
        for k, (lo, hi) in enumerate(entry["visible"]):
            runs = by_interval.get(k) or [(lo, hi, entry["visibility"] == "visible")]
            coarse = np.linspace(lo, hi, 257)
            uvc, _ = zb.project(self.cm, world_of_theta(coarse))
            approx = float(np.sum(np.hypot(*np.diff(uvc, axis=0).T)))
            n = int(min(200000, max(256, math.ceil(approx / 0.02))))
            th = np.linspace(lo, hi, n + 1)
            uv, _ = zb.project(self.cm, world_of_theta(th))
            cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(uv, axis=0).T))])
            ends = [(float(np.interp(t0, th, cum)), float(np.interp(t1, th, cum)), vis) for t0, t1, vis in runs]
            for m0, m1, vis in ends:
                m = np.arange(m0 + ZB_END_MM, m1 - ZB_END_MM + 1e-12, ZB_STEP_MM)
                if m.shape[0]:
                    X = world_of_theta(np.interp(m, cum, th))
                    uvs, _ = zb.project(self.cm, X)
                    self.samples.append((uvs, X, bool(vis), tag))
            for (_a0, m_b, v0), (_b0, _b1, v1) in zip(ends, ends[1:]):
                mm = np.clip([m_b - ZB_BOUNDARY_MM, m_b + ZB_BOUNDARY_MM], 0.0, cum[-1])
                X = world_of_theta(np.interp(mm, cum, th))
                self.bounds.append((X[0], X[1], bool(v0), bool(v1), tag))

    def evaluate(self, guard: bool = True) -> dict:
        """Per tag: ``[decided, agreeing, decided hidden]`` sample counts; ``boundaries: [total, agreeing]``."""
        out = {"boundaries": [0, 0]}
        if self.samples:
            Z = zb.DepthBuffer(self.scene)
            uv = np.concatenate([s[0] for s in self.samples])
            X = np.concatenate([s[1] for s in self.samples])
            vis = np.concatenate([np.full(s[0].shape[0], s[2]) for s in self.samples])
            tags = np.concatenate([np.full(s[0].shape[0], s[3], dtype=object) for s in self.samples])
            ok = np.all(np.isfinite(X), axis=1)
            _uv, depth = zb.project(self.cm, X[ok])
            decided, hid = zb.hidden_states(Z, uv[ok], depth, guard)
            agree = decided & (hid != vis[ok])
            for tag in sorted(set(tags.tolist())):
                sel = tags[ok] == tag
                out[tag] = [int(np.sum(decided[sel])), int(np.sum(agree[sel])), int(np.sum(hid[sel]))]
        if self.bounds:
            Xa = np.array([b[0] for b in self.bounds])
            Xb = np.array([b[1] for b in self.bounds])
            occ = zb.occluded_points(self.scene, np.concatenate([Xa, Xb]))
            n = len(self.bounds)
            va = np.array([b[2] for b in self.bounds])
            vb = np.array([b[3] for b in self.bounds])
            good = (~occ[:n] == va) & (~occ[n:] == vb)
            out["boundaries"] = [n, int(np.sum(good))]
        return out


def collect_document(scene: dict, doc: dict) -> _Collector:
    """Every subject drawable of a hidden-lines document (contract §5.1.6.1) into a :class:`_Collector`.
    Tags: ``"poly_edge"`` (edges[] of boxes / prisms, the 100 % set) and ``"other"``."""
    col = _Collector(scene)
    cm = col.cm
    pts = doc["points"]
    kinds = {o["id"]: o["type"] for o in scene["objects"]}
    planes = {r["id"]: r["plane"] for r in doc["receivers"]}
    lights = {lt["id"]: lt for lt in scene["lights"]}

    def line_world(a_name, b_name):
        A, B = pts[a_name]["world"], pts[b_name]["world"]
        return lambda uv: zb.on_line(cm, uv, A, B)

    for e in doc["edges"]:
        if e["segment"] is None:
            continue
        tag = "poly_edge" if kinds.get(e["object"]) in ("box", "prism") else "other"
        col.straight(e["segment"], e, line_world(e["from"], e["to"]), tag)
    for o in doc["outlines"]:
        for g in o["generators"]:
            if g["segment"] is not None:
                col.straight(g["segment"], g, line_world(g["from"], g["to"]), "other")
        for c in o["conics"]:
            col.conic(c, lambda th, c=c: _circle_point(c["circle"], th), "other")
    for f in doc["form_shadow"]:
        for t in f["terminator"]:
            if "segment" in t:
                if t["polylines"]:
                    col.straight(t["polylines"][0], t, line_world(*t["segment"]), "other")
            else:
                col.conic(t, lambda th, t=t: _circle_point(t["circle"], th), "other")
    # shadow polygon edges: subjects are the edges on an original outline edge (clip edges and drawn horizon
    # segments are not subjects, §5.1.6.4); the provenance comes from the 4-D clip of the stage-A loop
    A = castplane.shadow_geometry(scene)
    cam = castplane.project_scene(scene, A)["camera"]
    for sh, a_sh in zip(doc["shadows"], A["shadows"]):
        plane = planes[sh["receiver"]]
        world_of = lambda uv, plane=plane: zb.on_plane(cm, uv, plane[:3], plane[3])
        for poly, recs, loop in zip(sh["polygons"], sh["polygon_edges"], a_sh["loops"]):
            if len(poly) < 3:
                continue
            p4, ids = hidden.clip_polygon_4d(cam, loop["vertices"])
            if len(p4) != len(poly):
                continue
            n = len(poly)
            for k in range(n):
                if ids[k] is None or (p4[k, 3] == 0.0 and p4[(k + 1) % n, 3] == 0.0):
                    continue
                col.straight([poly[k], poly[(k + 1) % n]], recs[k], world_of, "other")
        for c in sh["conics"]:
            light = lights[sh["light"]]
            col.conic(c, lambda th, c=c, light=light, plane=plane: _shadow_of(_circle_point(c["circle"], th),
                                                                                light, plane), "other")
    return col


def zbuffer_random_scene(seed: int) -> dict:
    """A seeded random scene for the depth-buffer comparison: ``1 + seed % 6`` objects and ``seed % 3`` plates
    (a wall behind the objects as seen from the camera, then a low free-standing panel in front of them)."""
    n_obj, n_plates = 1 + seed % 6, seed % 3
    scene = random_scenes.make_scene(5000 + seed, n_obj)
    pts = np.vstack([random_scenes.world_extreme_points(o) for o in scene["objects"]])
    centre = 0.5 * (pts.min(axis=0) + pts.max(axis=0))
    C = np.asarray(scene["camera"]["position"], dtype=np.float64)
    view = np.array([centre[0] - C[0], centre[1] - C[1], 0.0])
    view /= np.linalg.norm(view)
    side = np.array([-view[1], view[0], 0.0])
    rel = pts[:, :2] - centre[None, :2]
    depth_ext = float(np.max(rel @ view[:2]))
    width = float(np.max(np.abs(rel @ side[:2]))) + 2.0
    dist = float(np.linalg.norm((centre - C)[:2]))
    rng = np.random.default_rng(seed)

    def plate(rid, at, half, height):
        n = -view
        d = -float(n @ at)
        b = [at - half * side, at + half * side, at + half * side + [0, 0, height], at - half * side + [0, 0, height]]
        return {"id": rid, "type": "plane", "normal": [float(v) + 0.0 for v in n], "offset": d,
                "bounds": [[float(v) + 0.0 for v in p] for p in b]}

    if n_plates >= 1:
        at = np.array([centre[0], centre[1], 0.0]) + (depth_ext + float(rng.uniform(0.3, 1.0))) * view
        scene["receivers"].append(plate("wall", at, width, float(rng.uniform(2.0, 3.5))))
    if n_plates >= 2:
        at = np.array([centre[0], centre[1], 0.0]) - min(0.45 * dist, float(rng.uniform(1.0, 2.5))) * view
        at = at + float(rng.uniform(-1.0, 1.0)) * side
        scene["receivers"].append(plate("panel", at, float(rng.uniform(0.6, 1.5)), float(rng.uniform(0.4, 1.2))))
    scene["output"]["hidden_lines"] = True
    return scene


def m4_hidden_scenes() -> dict:
    """The M4 conformance scenes of contract §5.1.11 (built as in ``tests/test_receivers.py``), switch on."""
    from tests.test_receivers import _concave_prism_scene

    def unlit():
        sc = wall_and_ground_scene()
        sc["lights"] = [{"id": "lamp", "type": "point", "position": [0, 8, 3]}]
        return sc

    def directional():
        sc = wall_and_ground_scene()
        d = np.array([0.3, -0.5, 0.8]) / math.sqrt(0.98)
        sc["lights"] = [{"id": "sun", "type": "directional", "direction": d.tolist()}]
        sc["camera"] = {"position": [0, -1, 1.6], "target": [0, 6, 1.6], "focal_length_mm": 35, "frame_mm": [36, 24]}
        return sc

    def bounded_default():
        sc = wall_and_ground_scene()
        sc["receivers"] = [{"id": "floor", "type": "plane", "normal": [0, 0, 1], "offset": 0,
                            "bounds": [[-2, 2, 0], [2, 2, 0], [2, 5.5, 0], [-2, 5.5, 0]]}]
        return sc

    def concave():
        u = [[-1, -1], [1, -1], [1, 1], [0.5, 1], [0.5, -0.5], [-0.5, -0.5], [-0.5, 1], [-1, 1]]
        return _concave_prism_scene([[-3, -4.5, 0], [3, -4.5, 0], [3, -2, 0], [-3, -2, 0]], [0, 0, 0], u,
                                    [0, 0.2, 0.7])

    makers = {"wall_and_ground_hidden": wall_and_ground_scene, "receiver_unlit_wall": unlit,
              "receiver_directional_wall": directional, "fold_curved_cylinder": fold_curved_cylinder_scene,
              "bounded_default_receiver": bounded_default, "hidden_lines_curved_unbounded": curved_unbounded_scene,
              "hidden_lines_vp_in_canvas": vp_in_canvas_scene, "concave_prism_on_plate": concave}
    out = {}
    for name, make in makers.items():
        sc = make()
        sc.setdefault("output", {})["hidden_lines"] = True
        out[name] = sc
    return out


ZBUFFER_SCENES = dict(m4_hidden_scenes(), **{f"random_{s}": zbuffer_random_scene(s) for s in range(20)})


def _zbuffer_result(name: str) -> dict:
    scene = castplane.load_scene(ZBUFFER_SCENES[name])
    doc = castplane.render(scene, hidden_lines=True)["geometry"]
    return collect_document(scene, doc).evaluate()


@pytest.mark.parametrize("name", sorted(ZBUFFER_SCENES))
def test_runs_agree_with_the_depth_buffer_reference(name):
    """Contract §5.1.11: samples every 0.5 mm along every run (0.3 mm clear of the ends) agree with the
    three-valued depth buffer for >= 99 % of the decided samples of the document and for 100 % of the decided
    samples on edges[] of boxes / prisms; every run boundary agrees with the point-wise ray cast 0.15 mm
    before and after it for >= 98 % of the boundaries."""
    res = _zbuffer_result(name)
    decided = sum(v[0] for k, v in res.items() if k != "boundaries")
    agree = sum(v[1] for k, v in res.items() if k != "boundaries")
    assert decided > 50, (name, res)
    assert agree >= 0.99 * decided, (name, res)
    if "poly_edge" in res:
        assert res["poly_edge"][1] == res["poly_edge"][0], (name, res)
    total, good = res["boundaries"]
    assert good >= 0.98 * total, (name, res)


def test_depth_buffer_comparison_is_not_vacuous():
    """The comparison decides both states, sees run boundaries, and rejects a wrong classification: with every
    state flipped the agreement collapses (wall_and_ground_hidden and two random scenes with plates)."""
    totals = {"hidden": 0, "visible": 0, "boundaries": 0}
    for name in ("wall_and_ground_hidden", "random_5", "random_11"):
        scene = castplane.load_scene(ZBUFFER_SCENES[name])
        doc = castplane.render(scene, hidden_lines=True)["geometry"]
        res = collect_document(scene, doc).evaluate()
        for k, v in res.items():
            if k != "boundaries":
                totals["hidden"] += v[2]
                totals["visible"] += v[0] - v[2]
        totals["boundaries"] += res["boundaries"][0]
        flipped = json.loads(dumps(doc))
        for item in [e for e in flipped["edges"]] + [r for s in flipped["shadows"] for pe in s["polygon_edges"]
                                                       for r in pe]:
            item["visibility"] = {"visible": "hidden", "hidden": "visible"}.get(item["visibility"], "partial")
            for r in item["runs"]:
                r["visible"] = not r["visible"]
        bad = collect_document(scene, flipped).evaluate()
        decided = sum(v[0] for k, v in bad.items() if k != "boundaries")
        agree = sum(v[1] for k, v in bad.items() if k != "boundaries")
        assert agree < 0.9 * decided, (name, bad)
    assert totals["hidden"] > 500 and totals["visible"] > 500 and totals["boundaries"] > 50, totals


def test_zbuffer_camera_reproduces_the_document_images():
    """The reference camera (re-implemented from the spec) gives the document's images and depths."""
    for name in ("camera_roll_and_shift", "camera_yaw_pitch_form", "example_three_point"):
        scene = castplane.load_scene(load_case(name))
        doc = castplane.render(scene)["geometry"]
        cm = zb.camera_model(scene)
        n = 0
        for pt in doc["points"].values():
            if "world" in pt and pt.get("image") is not None:
                uv, z = zb.project(cm, [pt["world"]])
                assert np.allclose(uv[0], pt["image"], atol=1e-9) and z[0] == pytest.approx(pt["depth"], rel=1e-12)
                n += 1
        assert n >= 8, name
    scene = castplane.load_scene(wall_and_ground_scene())
    cm = zb.camera_model(scene)
    assert cm["rect"] == (-0.75 * 273, 0.75 * 273, -0.75 * 182, 0.75 * 182)
    assert zb.grid_shape(cm) == (2730, 4095)


def test_zbuffer_three_valued_rule_and_lazy_buffer():
    scene = castplane.load_scene(wall_and_ground_scene())
    Z = zb.DepthBuffer(scene)
    cm = Z.cam
    window = (1500, 1504, 1800, 1806)
    full = Z.full(window)
    IY, IX = np.meshgrid(np.arange(1500, 1504), np.arange(1800, 1806), indexing="ij")
    assert np.array_equal(Z[IY.ravel(), IX.ravel()].reshape(full.shape), full)
    # the middle of the back bottom edge v2-v3 of the crate (y = 5, z = 0) is behind the front face
    X = np.array([[0.0, 5.0, 0.0]])
    uv, depth = zb.project(cm, X)
    assert zb.hidden_at(Z, uv[0], depth[0]) is True
    assert zb.occluded_points(scene, X)[0]
    # a point on the visible front face: undecided (inside the band), not occluded point-wise
    Y = np.array([[0.1, 4.0, 0.5]])
    uv, depth = zb.project(cm, Y)
    assert zb.hidden_at(Z, uv[0], depth[0]) is None
    assert not zb.occluded_points(scene, Y)[0]
    # a point in front of everything along its ray: visible
    W = np.array([[2.0, 3.0, 2.0]])
    uv, depth = zb.project(cm, W)
    assert zb.hidden_at(Z, uv[0], depth[0]) is False


@pytest.mark.parametrize("kind, shape", [
    ("box", {"size": [1.2, 0.7, 0.9]}),
    ("prism", {"polygon": [[-1, -1], [1, -1], [1, 1], [0.5, 1], [0.5, -0.5], [-0.5, -0.5], [-0.5, 1], [-1, 1]],
               "height": 0.8}),
    ("cylinder", {"radius": 0.6, "height": 1.1}),
    ("cone", {"radius": 0.7, "height": 1.3}),
    ("sphere", {"radius": 0.6}),
])
def test_reference_first_hit_t_equals_the_core_occluders(kind, shape):
    """``raycast.first_hit_t`` (the reference) and ``hidden.first_hit`` (the core, re-implemented) give the
    same first crossing on random rays, incl. rays starting inside the solid."""
    from tests.reference import raycast
    obj = {"id": "o", "type": kind, "transform": {"position": [0.3, -0.2, 0.1],
                                                    "rotation_deg": [0, 0, 35] if kind == "sphere" else [10, -20, 35]}}
    obj.update(shape)
    sc = {"version": "0.1", "units": "m", "up": "z", "objects": [obj],
          "lights": [{"id": "l", "type": "point", "position": [0, 0, 5]}],
          "receivers": [{"id": "g", "type": "plane", "normal": [0, 0, 1], "offset": 0}],
          "camera": {"position": [0, -8, 3], "target": [0, 0, 0.5], "focal_length_mm": 35, "frame_mm": [36, 24]},
          "output": {"canvas_mm": [360, 240]}}
    scene = castplane.load_scene(sc)
    occ = hidden.occluder(castplane.shadow_geometry(scene)["objects"][0])
    rng = np.random.default_rng(11)
    O = rng.uniform(-3, 3, size=(5000, 3))
    O[:500] = [0.3, -0.2, 0.5] + rng.uniform(-0.1, 0.1, size=(500, 3))            # inside
    target = np.array([0.3, -0.2, 0.5]) + rng.uniform(-0.9, 0.9, size=(5000, 3))
    D = target - O
    o, d = raycast.to_local(scene["objects"][0], O, D)
    t_ref = raycast.FIRST_HIT_T[kind](scene["objects"][0], o, d, 1e-9)
    t_core = hidden.first_hit(occ, O, D, 1e-9)
    fin = np.isfinite(t_ref) & np.isfinite(t_core)
    assert fin.sum() > 1500
    assert np.mean(np.isfinite(t_ref) == np.isfinite(t_core)) > 0.999
    assert np.max(np.abs(t_ref[fin] - t_core[fin])) < 1e-7
