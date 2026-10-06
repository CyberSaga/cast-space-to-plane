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
