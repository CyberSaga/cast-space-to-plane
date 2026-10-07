"""The ``mesh`` object type through stages A / B / C (contract §5.2.3 step 8, §5.2.4, §5.2.5, §5.2.12,
§5.2.13; test table of §5.2.11)."""

from __future__ import annotations

import copy
import json
import pathlib

import numpy as np
import pytest

from castplane import load_scene
from castplane.primitives import build_object, local_mesh, point_inside_solid, prepared_mesh

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "conformance" / "cases"

CUBE_V = [[-.5, -.5, 0.0], [.5, -.5, 0.0], [.5, .5, 0.0], [-.5, .5, 0.0],
          [-.5, -.5, 1.0], [.5, -.5, 1.0], [.5, .5, 1.0], [-.5, .5, 1.0]]
CUBE_F = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
#: contract §5.2.12: the eight vertices followed by the same eight twice; 12 triangles on the duplicates
SPLIT_V = CUBE_V * 3
SPLIT_F = [[8, 11, 10], [8, 10, 9], [12, 13, 14], [12, 14, 15], [16, 17, 21], [16, 21, 20],
           [17, 18, 22], [17, 22, 21], [18, 19, 23], [18, 23, 22], [19, 16, 20], [19, 20, 23]]
OPEN_BOTTOM_F = [[4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]


def analytic_box_scene() -> dict:
    return json.loads((CASES / "analytic_unit_box_point_light_overhead.json").read_text(encoding="utf-8"))


def mesh_box_scene(vertices=None, faces=None, **keys) -> dict:
    """``analytic_unit_box_point_light_overhead`` with the box replaced by an inline mesh ``cube``."""
    scene = analytic_box_scene()
    obj = {"id": "cube", "type": "mesh",
           "data": {"vertices": copy.deepcopy(SPLIT_V if vertices is None else vertices),
                    "faces": copy.deepcopy(SPLIT_F if faces is None else faces)}}
    obj.update(keys)
    scene["objects"] = [obj]
    return scene


# --- step 3: object records -----------------------------------------------------------------------

def test_mesh_record_keys():
    scene = load_scene(mesh_box_scene())
    rec = build_object(scene["objects"][0])
    assert rec["type"] == "mesh" and rec["analytic"] is None and rec["fallback"] is False
    assert rec["prep_warnings"] == [] and rec["smooth_groups"] == [0] * 6 and rec["triangles"].shape == (12, 3)
    assert rec["mesh"]["vertices"].tolist() == CUBE_V and rec["mesh"]["faces"] == CUBE_F
    assert rec["mesh"]["edge_smooth"].tolist() == [False] * 12
    assert rec["point_names"] == [f"cube.v{k}" for k in range(8)]
    assert all(t["smooth"] is False for t in rec["edge_templates"])
    assert local_mesh(scene["objects"][0])["faces"] == CUBE_F
    assert prepared_mesh(scene["objects"][0])["scale_A"] == 1.0


def test_primitive_records_gain_only_the_switch_off_keys():
    rec = build_object(load_scene(analytic_box_scene())["objects"][0])
    assert rec["fallback"] is False and rec["prep_warnings"] == []
    assert rec["mesh"]["edge_smooth"].tolist() == [False] * 12
    assert "triangles" not in rec and "smooth_groups" not in rec
    assert all("smooth" not in t for t in rec["edge_templates"])


def test_mesh_transform_and_scale_are_applied():
    scene = mesh_box_scene(CUBE_V, CUBE_F, scale=2.0,
                           transform={"position": [1.0, 2.0, 0.0], "rotation_deg": [0.0, 0.0, 90.0]})
    rec = build_object(load_scene(scene)["objects"][0])
    ref = build_object(load_scene(dict(analytic_box_scene(), objects=[
        {"id": "cube", "type": "box", "size": [2, 2, 2],
         "transform": {"position": [1.0, 2.0, 0.0], "rotation_deg": [0.0, 0.0, 90.0]}}]))["objects"][0])
    assert np.array_equal(rec["mesh"]["vertices"], ref["mesh"]["vertices"])
    assert np.array_equal(rec["mesh"]["face_normals"], ref["mesh"]["face_normals"])


def test_point_inside_solid_mesh_branch():
    rec = build_object(load_scene(mesh_box_scene(transform={"position": [3.0, 0.0, 0.0]}))["objects"][0])
    assert point_inside_solid(rec, [3.0, 0.0, 0.5], 1e-9)
    assert not point_inside_solid(rec, [0.0, 0.0, 0.5], 1e-9)
    assert not point_inside_solid(rec, [3.0, 0.0, 1.0], 1e-9)          # on the surface within tol
    fb = build_object(load_scene(mesh_box_scene(CUBE_V, OPEN_BOTTOM_F))["objects"][0])
    assert fb["fallback"] is True and [w["code"] for w in fb["prep_warnings"]] == ["MESH_NON_MANIFOLD"]
    assert not point_inside_solid(fb, [0.0, 0.0, 0.5], 1e-9)          # a fallback mesh has no inside


# --- step 4: the pipeline --------------------------------------------------------------------------

import math  # noqa: E402

from castplane import render, shadow_geometry  # noqa: E402
from castplane.output.geometry_json import dumps  # noqa: E402
from castplane.pipeline import compose, project_scene  # noqa: E402
from tests.reference import raster  # noqa: E402


def doc_of(scene, camera=None):
    return render(load_scene(scene), camera=camera)["geometry"]


def strip_mesh_keys(doc):
    for e in doc["edges"]:
        e.pop("smooth", None)
        e.pop("camera_silhouette", None)
    return doc


def warning_set(doc):
    return {(w["code"], tuple(w["ids"])) for w in doc["warnings"]}


def test_acceptance_1_imported_box_equals_the_parametric_box_byte_for_byte():
    ref = doc_of(analytic_box_scene())
    doc = doc_of(mesh_box_scene())
    assert all(e["smooth"] is False for e in doc["edges"]) and len(doc["edges"]) == 12
    # camera silhouette edges are drawn like every feature edge; the key is camera dependent
    assert {(e["from"], e["to"]) for e in doc["edges"] if e["camera_silhouette"]} == \
        {("cube.v0", "cube.v1"), ("cube.v1", "cube.v2"), ("cube.v2", "cube.v6"), ("cube.v6", "cube.v7"),
         ("cube.v4", "cube.v7"), ("cube.v0", "cube.v4")}
    assert dumps(strip_mesh_keys(doc)) == dumps(ref)
    # the hand values of contract §5.2.12
    assert {(e["from"], e["to"]) for e in doc["edges"] if e["silhouette"]} == \
        {("cube.v4", "cube.v5"), ("cube.v4", "cube.v7"), ("cube.v5", "cube.v6"), ("cube.v6", "cube.v7")}
    sh = doc["shadows"][0]
    assert sh["outline"] == [f"cube.v{k}.shadow.lamp" for k in (4, 5, 6, 7)]
    assert [doc["points"][n]["world"] for n in sh["outline"]] == \
        [[-.75, -.75, 0.0], [.75, -.75, 0.0], [.75, .75, 0.0], [-.75, .75, 0.0]]
    con = doc["construction"]
    assert con["light_point"] == pytest.approx([0, 87.93525754212652], abs=1e-9)
    assert con["shadow_vp"] == pytest.approx([0, -15.270708139022979], abs=1e-9)
    images = [doc["points"][n]["image"] for n in sh["outline"]]
    np.testing.assert_allclose(images, [[-35.43926206447239, -21.040388381248047],
                                        [12.57114643641712, -33.69048944708911],
                                        [33.42375900867301, -9.829161370289384],
                                        [-10.541723693318392, 0.17547618657507147]], atol=1e-9)
    assert con["rays"] == [[k, f"cube.v{v}" if k == "L" else f"cube.v{v}.foot"] for v in (4, 5, 6, 7) for k in "LF"]
    assert len(con["checks"]) == 4 and max(c["max_error_mm"] for c in con["checks"]) <= 1e-9
    assert len(doc["form_shadow"][0]["faces"]) == 5 and doc["warnings"] == []


def world_of(doc):
    return {n: tuple(p["world"]) for n, p in doc["points"].items() if "world" in p}


def mapper(doc):
    """``φ``: a name -> its world-keyed form (``<obj>.v<k>`` replaced by the vertex's world triple)."""
    world = world_of(doc)

    def phi(name):
        if isinstance(name, dict):
            return ("dir", tuple(name["direction"]))
        parts = name.split(".")
        if len(parts) >= 2 and parts[1].startswith("v") and parts[1][1:].isdigit():
            base = ".".join(parts[:2])
            return (parts[0], world[base], ".".join(parts[2:]))
        return name
    return phi


def cyclic_key(seq):
    """Rotation-invariant key of a cyclic sequence (and the rotation that achieves it)."""
    seq = list(seq)
    reps = [tuple(seq[k:] + seq[:k]) for k in range(len(seq))]
    best = min(range(len(seq)), key=lambda k: repr(reps[k])) if seq else 0
    return (reps[best] if seq else ()), best


def assert_equal_by_world(a, b, atol=1e-9):
    """The equality criteria of contract §5.2.13 (a)–(h)."""
    pa, pb = mapper(a), mapper(b)
    # (a) vertex sets, (e) points after renaming
    va = {pa(n): p for n, p in a["points"].items()}
    vb = {pb(n): p for n, p in b["points"].items()}
    assert set(va) == set(vb)
    for k, p in va.items():
        q = vb[k]
        assert p.get("world") == q.get("world") and p.get("direction") == q.get("direction")
        assert (p["image"] is None) == (q["image"] is None)
        if p["image"] is not None:
            np.testing.assert_allclose(p["image"], q["image"], atol=atol)
        if "depth" in p:
            assert abs(p["depth"] - q["depth"]) <= atol
    # (b) edges as unordered world pairs with equal flags and segments as unordered pairs
    def edge_map(doc, phi):
        out = {}
        for e in doc["edges"]:
            key = frozenset([phi(e["from"]), phi(e["to"])])
            seg = e["segment"]
            out[key] = (e["silhouette"], e["back"], e.get("smooth", False), None if seg is None else sorted(seg))
        return out
    ea, eb = edge_map(a, pa), edge_map(b, pb)
    assert set(ea) == set(eb)
    for k, (s, bk, sm, seg) in ea.items():
        s2, bk2, sm2, seg2 = eb[k]
        assert (s, bk, sm) == (s2, bk2, sm2) and (seg is None) == (seg2 is None)
        if seg is not None:
            np.testing.assert_allclose(seg, seg2, atol=atol)

    # (c) form_shadow faces as cyclic world sequences, polygons within atol
    def faces_map(doc, phi):
        out = {}
        for f in doc["form_shadow"]:
            for face, poly in zip(f["faces"], f["polygons"]):
                key, rot = cyclic_key([phi(n) for n in face])
                out[key] = poly[rot:] + poly[:rot] if len(poly) == len(face) else poly
        return out
    fa, fb = faces_map(a, pa), faces_map(b, pb)
    assert set(fa) == set(fb)
    for k in fa:
        np.testing.assert_allclose(fa[k], fb[k], atol=atol)
    # (d) shadows: unbounded, loops as cyclic sequences of mapped names, polygons
    assert len(a["shadows"]) == len(b["shadows"])
    for s1, s2 in zip(a["shadows"], b["shadows"]):
        assert s1["unbounded"] == s2["unbounded"]

        def loops_map(s, phi):
            out = {}
            for loop, poly in zip(s["loops"], s["polygons"]):
                key, rot = cyclic_key([phi(n) for n in loop])
                out[key] = poly[rot:] + poly[:rot] if len(poly) == len(loop) else poly
            return out
        la, lb = loops_map(s1, pa), loops_map(s2, pb)
        assert set(la) == set(lb)
        for k in la:
            np.testing.assert_allclose(la[k], lb[k], atol=atol)
    # (f) rays, checks, segments
    ca, cb = a["construction"], b["construction"]
    assert {(k, pa(n)) for k, n in ca["rays"]} == {(k, pb(n)) for k, n in cb["rays"]}
    assert {pa(c["point"]) for c in ca["checks"]} == {pb(c["point"]) for c in cb["checks"]}
    assert all(c["max_error_mm"] <= 1e-9 for c in ca["checks"] + cb["checks"])
    sa = {(s["kind"], pa(s["point"])): s["points"] for s in ca["segments"]}
    sb = {(s["kind"], pb(s["point"])): s["points"] for s in cb["segments"]}
    assert set(sa) == set(sb)
    for k in sa:
        np.testing.assert_allclose(sa[k], sb[k], atol=atol)
    # (g) warnings, (h) horizon / camera
    assert warning_set(a) == warning_set(b)
    assert a["horizon"] == b["horizon"] and a["camera"] == b["camera"]


def test_acceptance_1_inside_out_and_one_flipped_split_box_equal_the_parametric_box():
    """Winding repair followed by the coplanar merge (contract §5.2.3 steps 5-6, §5.2.13)."""
    ref = dumps(doc_of(analytic_box_scene()))
    inside_out = [[f[0]] + f[1:][::-1] for f in SPLIT_F]
    one = [list(f) for f in SPLIT_F]
    one[4] = [one[4][0]] + one[4][1:][::-1]
    for F in (inside_out, one):
        doc = doc_of(mesh_box_scene(SPLIT_V, F))
        assert [w["code"] for w in doc["warnings"]] == ["MESH_WINDING_FIXED"]
        assert len(doc["edges"]) == 12 and len(doc["form_shadow"][0]["faces"]) == 5
        doc["warnings"] = []
        assert dumps(strip_mesh_keys(doc)) == ref


def test_acceptance_1_shuffled_vertex_and_face_order():
    rng = np.random.default_rng(5)
    perm = rng.permutation(len(SPLIT_V))                 # new position of old vertex k is inv[k]
    inv = np.argsort(perm)
    V = [SPLIT_V[int(k)] for k in perm]
    F = [[int(inv[v]) for v in f] for f in SPLIT_F]
    F = [F[int(k)] for k in rng.permutation(len(F))]
    F = [f[r:] + f[:r] for f, r in zip(F, rng.integers(0, 3, size=len(F)).tolist())]
    shuffled = doc_of(mesh_box_scene(V, F))
    ref = doc_of(analytic_box_scene())
    assert shuffled["warnings"] == []
    names = [f"cube.v{k}" for k in range(8)]
    assert [shuffled["points"][n]["world"] for n in names] != [ref["points"][n]["world"] for n in names]
    assert_equal_by_world(ref, shuffled)
    assert_equal_by_world(doc_of(mesh_box_scene()), shuffled)


def open_bottom_doc(**keys):
    return doc_of(mesh_box_scene(CUBE_V, OPEN_BOTTOM_F, **keys))


def shoelace(pts):
    pts = np.asarray(pts, dtype=float)
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def test_acceptance_2_open_bottom_box_fallback():
    doc = open_bottom_doc()
    assert warning_set(doc) == {("MESH_NON_MANIFOLD", ("cube",))}
    sh = doc["shadows"][0]
    assert len(sh["loops"]) == 5 and sh["unbounded"] is False and sh["outline"] == sh["loops"][0]
    pts = doc["points"]
    loops_xy = [[pts[n]["world"][:2] for n in loop] for loop in sh["loops"]]
    assert sh["loops"][0] == [f"cube.v{k}.shadow.lamp" for k in (4, 5, 6, 7)]
    assert loops_xy[0] == [[-.75, -.75], [.75, -.75], [.75, .75], [-.75, .75]]
    assert sh["loops"][1] == [f"cube.v{k}.shadow.lamp" for k in (0, 4, 5, 1)]       # front, reversed
    assert loops_xy[1] == [[-.5, -.5], [-.75, -.75], [.75, -.75], [.5, -.5]]
    assert shoelace(loops_xy[0]) == pytest.approx(2.25)
    assert shoelace(loops_xy[1]) == pytest.approx(0.3125)                          # CCW, sum +0.625
    assert loops_xy[2] == [[.5, -.5], [.75, -.75], [.75, .75], [.5, .5]]
    for xy in loops_xy[1:]:
        assert shoelace(xy) == pytest.approx(0.3125)
        assert all(abs(x) <= 0.75 and abs(y) <= 0.75 for x, y in xy)
    # the union of the drawn loops is the parametric shadow (±0.75 square): raster IoU 1
    xs = ys = np.linspace(-1.0, 1.0, 201) + 0.003
    union = raster.rasterize_polygons(loops_xy, xs, ys)
    square = raster.rasterize_polygons([loops_xy[0]], xs, ys)
    assert raster.iou(union, square) == 1.0
    # edges: 12, silhouette on the 4 top edges only, never smooth
    assert len(doc["edges"]) == 12 and all(e["smooth"] is False for e in doc["edges"])
    assert {(e["from"], e["to"]) for e in doc["edges"] if e["silhouette"]} == \
        {("cube.v4", "cube.v5"), ("cube.v4", "cube.v7"), ("cube.v5", "cube.v6"), ("cube.v6", "cube.v7")}
    assert all(e["segment"] is not None for e in doc["edges"])
    assert doc["form_shadow"][0]["faces"] == [[f"cube.v{k}" for k in f] for f in OPEN_BOTTOM_F[1:]]
    for k in range(8):
        assert f"cube.v{k}.shadow.lamp" in pts and f"cube.v{k}.foot" in pts
    for k in range(4):
        assert pts[f"cube.v{k}.foot"]["world"] == pts[f"cube.v{k}"]["world"]
    con = doc["construction"]
    assert con["rays"] == [] and con["checks"] == [] and con["segments"] == []


def test_fallback_vertex_not_below_light_only_for_vertices_that_reach_a_loop():
    """§2.3 "some silhouette vertex": in the per-face fallback, a vertex of a light-parallel face only
    never reaches a loop and does not warn; a vertex of a shadowed face above the light does."""
    scene = mesh_box_scene([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], [[0, 1, 2, 3]])
    scene["lights"][0]["position"] = [0.5, 0.0, 0.5]          # in the plane of the quad, below its top
    doc = doc_of(scene)
    assert [w["code"] for w in doc["warnings"]] == ["FACE_PARALLEL_TO_LIGHT", "MESH_NON_MANIFOLD"]
    assert doc["shadows"][0]["loops"] == []
    scene = mesh_box_scene(CUBE_V, OPEN_BOTTOM_F)
    scene["lights"][0]["position"] = [0.0, 0.0, 0.5]          # inside the open box, below the top face
    doc = doc_of(scene)
    assert ("VERTEX_NOT_BELOW_LIGHT", ("cube",)) in warning_set(doc)


def test_fallback_buried_open_box_has_one_point_per_crossed_edge():
    doc = open_bottom_doc(transform={"position": [0.0, 0.0, -0.5]})
    assert warning_set(doc) == {("MESH_NON_MANIFOLD", ("cube",)), ("OBJECT_BELOW_RECEIVER", ("cube",))}
    import re
    is_ground = re.compile(r"^cube\.s\d+\.lamp$").match
    ground = sorted(n for n in doc["points"] if is_ground(n))
    assert ground == [f"cube.s{k}.lamp" for k in range(4)]
    worlds = sorted(tuple(doc["points"][n]["world"]) for n in ground)
    assert worlds == [(-.5, -.5, 0.0), (-.5, .5, 0.0), (.5, -.5, 0.0), (.5, .5, 0.0)]
    sh = doc["shadows"][0]
    assert len(sh["loops"]) == 5
    # every side loop holds two crossings (one name per crossed vertical edge, shared by two faces)
    for loop in sh["loops"][1:]:
        assert sum(1 for n in loop if is_ground(n)) == 2
    # the buried vertices v0..v3 get neither a shadow nor a foot (keep = finite & above)
    assert all(f"cube.v{k}.shadow.lamp" not in doc["points"] for k in range(4))
    assert doc["construction"]["rays"] == []


def regular_polygon(n, r=0.5):
    return [[r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n)] for k in range(n)]


def prism_data(n, r=0.5, h=1.0):
    ring = regular_polygon(n, r)
    V = [[x, y, 0.0] for x, y in ring] + [[x, y, h] for x, y in ring]
    F = [list(range(n - 1, -1, -1)), list(range(n, 2 * n))]
    F += [[k, (k + 1) % n, n + (k + 1) % n, n + k] for k in range(n)]
    return V, F


def test_mesh_smooth_prism16_draws_two_lateral_edges():
    V, F = prism_data(16)
    doc = doc_of(mesh_box_scene(V, F))
    edges = doc["edges"]
    lateral = [e for e in edges if abs(int(e["from"].split("v")[1]) - int(e["to"].split("v")[1])) == 16]
    caps = [e for e in edges if e not in lateral]
    assert len(lateral) == 16 and len(caps) == 32
    assert all(e["smooth"] for e in lateral) and not any(e["smooth"] for e in caps)
    drawn = [e for e in lateral if e["segment"] is not None]
    assert len(drawn) == 2 and all(e["camera_silhouette"] for e in drawn)
    assert all(e["segment"] is None and e["visibility"] == "visible" for e in lateral if not e["camera_silhouette"])
    assert all(e["segment"] is not None for e in caps)
    # the SVG writer simply skips the null segments
    svg = render(load_scene(mesh_box_scene(V, F)))["svg"]
    body = svg[svg.index('<g id="objects.cube">'):svg.index('<g id="form_shadow"')]
    assert body.count("<line") == len([e for e in edges if e["segment"] is not None]) == 34   # 32 caps + 2


def test_ray_cap_64_and_mesh_rays_capped():
    V, F = prism_data(100)
    for smooth in (0.0, 30.0):
        doc = doc_of(mesh_box_scene(V, F, smooth_angle_deg=smooth))
        assert ("MESH_RAYS_CAPPED", ("cube",)) in warning_set(doc)
        sh = doc["shadows"][0]
        assert len(sh["loops"]) == 1 and len(sh["outline"]) == 100
        loop_vertices = [n[:-len(".shadow.lamp")] for n in sh["outline"]]
        selected = set(loop_vertices[:64])
        rays = doc["construction"]["rays"]
        assert {n for k, n in rays if k == "L"} == selected
        # emission order stays ascending vertex index
        idx = [int(n.split(".v")[1]) for k, n in rays if k == "L"]
        assert idx == sorted(idx) and len(idx) == 64
        assert len(doc["construction"]["checks"]) == 64
        assert all(f"{n}.shadow.lamp" in doc["points"] for n in loop_vertices)   # every vertex keeps its points
    V, F = prism_data(32)
    doc = doc_of(mesh_box_scene(V, F))
    assert "MESH_RAYS_CAPPED" not in {w["code"] for w in doc["warnings"]}
    assert len([r for r in doc["construction"]["rays"] if r[0] == "L"]) == 32


def test_rays_only_for_feature_silhouette_vertices():
    # a UV sphere mesh (32 x 16, dihedral angles < 30 deg): every edge is smooth, so no silhouette vertex
    # is an endpoint of a feature silhouette edge -> no rays / checks / segments, but every silhouette
    # vertex keeps its .shadow / .foot points
    from castplane.mesh import sphere_mesh
    sm = sphere_mesh(0.5)
    scene = mesh_box_scene(sm["vertices"].tolist(), sm["faces"])
    doc = doc_of(scene)
    assert all(e["smooth"] for e in doc["edges"])
    sil = {n for e in doc["edges"] if e["silhouette"] for n in (e["from"], e["to"])}
    assert len(sil) > 20
    assert doc["construction"]["rays"] == [] and doc["construction"]["checks"] == []
    assert all(f"{n}.shadow.lamp" in doc["points"] and f"{n}.foot" in doc["points"] for n in sil)
    # with smooth_angle_deg = 0 every edge is a feature edge: every silhouette vertex gets its rays
    doc0 = doc_of(mesh_box_scene(sm["vertices"].tolist(), sm["faces"], smooth_angle_deg=0.0))
    assert {n for k, n in doc0["construction"]["rays"] if k == "L"} == sil
    # only the camera silhouette edges of the smooth sphere are drawn
    drawn = [e for e in doc["edges"] if e["segment"] is not None]
    assert drawn and all(e["camera_silhouette"] for e in drawn)


def test_render_twice_is_bit_identical():
    for scene in (mesh_box_scene(), mesh_box_scene(CUBE_V, OPEN_BOTTOM_F), mesh_box_scene(*prism_data(16))):
        a, b = render(load_scene(scene)), render(load_scene(copy.deepcopy(scene)))
        assert dumps(a["geometry"]) == dumps(b["geometry"]) and a["svg"] == b["svg"]


def test_stage_a_is_camera_independent_with_meshes():
    for scene in (mesh_box_scene(), mesh_box_scene(CUBE_V, OPEN_BOTTOM_F), mesh_box_scene(*prism_data(16))):
        s = load_scene(scene)
        A1 = shadow_geometry(s)
        s2 = copy.deepcopy(s)
        s2["camera"] = None                                 # stage A never touches the camera
        A2 = shadow_geometry(s2)
        assert dumps(A1) == dumps(A2)
        cam2 = {"position": [-6.0, -4.0, 7.0], "target": [0.0, 3.0, 0.0], "roll_deg": 15.0,
                "focal_length_mm": 20.0, "frame_mm": [36, 24], "shift_mm": [1.0, -2.0], "near_m": 0.1}
        d1 = compose(s, project_scene(s, A1))
        d2 = compose(s, project_scene(s, A1, camera=cam2))
        assert [(e["from"], e["to"], e["silhouette"], e["smooth"]) for e in d1["edges"]] == \
            [(e["from"], e["to"], e["silhouette"], e["smooth"]) for e in d2["edges"]]
        assert {n: p.get("world") for n, p in d1["points"].items()} == {n: p.get("world") for n, p in d2["points"].items()}
        assert [x["loops"] for x in d1["shadows"]] == [x["loops"] for x in d2["shadows"]]
        assert [f["faces"] for f in d1["form_shadow"]] == [f["faces"] for f in d2["form_shadow"]]
        assert d1["construction"]["rays"] == d2["construction"]["rays"]


def mesh_invariant_scenes():
    """Mesh scenes for the spec §7.1 rows: the split-vertex box rotated and moved, a 16-gon prism mesh
    and a concave L-shaped extrusion, under a point and a directional light."""
    V, F = prism_data(16)
    L_poly = [[0, 0], [1.2, 0], [1.2, 0.4], [0.4, 0.4], [0.4, 1.0], [0, 1.0]]
    LV = [[x, y, 0.0] for x, y in L_poly] + [[x, y, 0.8] for x, y in L_poly]
    n = len(L_poly)
    LF = [list(range(n - 1, -1, -1)), list(range(n, 2 * n))] + [[k, (k + 1) % n, n + (k + 1) % n, n + k] for k in range(n)]
    scenes = []
    for light in ({"id": "lamp", "type": "point", "position": [1.5, -2.0, 4.0]},
                  {"id": "sun", "type": "directional", "direction": [-0.4, -0.5, 0.7681145747868608]}):
        sc = mesh_box_scene()
        sc["objects"][0]["transform"] = {"position": [0.3, -0.2, 0.0], "rotation_deg": [0.0, 0.0, 25.0]}
        sc["objects"].append({"id": "prism", "type": "mesh", "data": {"vertices": V, "faces": F},
                              "transform": {"position": [-1.5, 1.0, 0.0], "rotation_deg": [0, 0, 10]}})
        sc["objects"].append({"id": "ell", "type": "mesh", "data": {"vertices": LV, "faces": LF},
                              "transform": {"position": [1.5, 1.2, 0.0], "rotation_deg": [0, 0, -30]}})
        sc["lights"] = [light]
        scenes.append(load_scene(sc))
    return scenes


@pytest.mark.parametrize("k", [0, 1])
def test_spec_7_1_row_1_construction_equals_direct_projection(k):
    from tests.test_invariants import test_construction_equals_direct_projection
    test_construction_equals_direct_projection(mesh_invariant_scenes()[k])


@pytest.mark.parametrize("k", [0, 1])
def test_spec_7_1_row_2_shadows_are_camera_independent(k):
    from tests.test_invariants import test_shadows_are_camera_independent
    test_shadows_are_camera_independent(mesh_invariant_scenes()[k])


@pytest.mark.parametrize("k", [0, 1])
@pytest.mark.parametrize("yaw_form", [False, True])
def test_spec_7_1_row_4_rigid_equivariance(k, yaw_form):
    from tests.test_invariants import test_rigid_equivariance
    test_rigid_equivariance(mesh_invariant_scenes()[k], yaw_form)


# --- step 7: the ray-cast reference on meshes --------------------------------------------------------

from tests.reference import random_scenes, raycast  # noqa: E402


def raycast_iou(scene, doc, lo=(-1.5, -1.5), hi=(1.5, 1.5), n=301):
    # the grid is offset by a non-round amount so that no sample lies exactly on a shadow edge
    # (the rasteriser's half-open edge rule and the ray caster's inclusive bounds differ there)
    xs, ys = random_scenes.grid(np.array(lo) + 0.0037, np.array(hi) + 0.0037, n)
    loops = raster.doc_ground_loops(doc, np.zeros(2), 1e9)
    got = raster.rasterize_polygons(loops, xs, ys)
    ref = raycast.shadow_mask(scene, scene["lights"][0], xs, ys)
    assert ref.any()
    return raster.iou(got, ref)


def test_acceptance_2_ray_cast_iou_is_one():
    scene = mesh_box_scene(CUBE_V, OPEN_BOTTOM_F)
    doc = doc_of(scene)
    # a ground ray under the box enters through the open bottom and hits the top face
    assert raycast_iou(scene, doc) == 1.0
    assert raycast_iou(load_scene(scene), doc) == 1.0


def test_buried_fallback_ray_cast_iou():
    scene = mesh_box_scene(CUBE_V, OPEN_BOTTOM_F, transform={"position": [0.0, 0.0, -0.5]})
    assert raycast_iou(scene, doc_of(scene)) >= 0.99


def test_hit_mesh_applies_scale_and_the_raw_up_axis():
    y_up = [[x, z, -y] for x, y, z in CUBE_V]
    o = np.array([[0.0, 0.0, -1.0], [3.0, 0.0, -1.0], [0.0, 0.0, 2.0]])
    d = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]])
    obj = {"type": "mesh", "data": {"vertices": y_up, "faces": CUBE_F}, "up": "y", "scale": 2.0}
    assert raycast.hit_mesh(obj, o, d, np.inf).tolist() == [True, False, False]
    assert raycast.HITTERS["mesh"] is raycast.hit_mesh
    tri = raycast.mesh_triangles(obj)
    assert tri.shape == (12, 3, 3) and float(tri[:, :, 2].max()) == 2.0


@pytest.mark.parametrize("seed", [0, 1, 2, 5, 8, 9])
def test_ray_cast_iou_on_seeded_mesh_scenes(seed):
    from tests.test_raycast import render_and_compare
    scene = random_scenes.make_mesh_scene(seed)
    out = render_and_compare(scene)                     # union and per object, IoU >= 0.99
    assert out["iou"] >= 0.99 and all(v >= 0.99 for v in out["per_object"].values())


def test_make_mesh_scene_families():
    kinds = set()
    fallback = 0
    for seed in range(12):
        scene = random_scenes.make_mesh_scene(seed)
        assert scene == random_scenes.make_mesh_scene(seed)          # deterministic
        validated = load_scene(scene)
        kinds.update(o["type"] for o in validated["objects"])
        recs = [build_object(o) for o in validated["objects"]]
        fallback += sum(r["fallback"] for r in recs)
        for raw, rec in zip(scene["objects"], recs):
            assert len(raw["data"]["vertices"]) > rec["mesh"]["vertices"].shape[0] or rec["fallback"]
    assert kinds == {"mesh"} and fallback > 0


def test_make_scene_is_byte_identical_for_the_frozen_seeds():
    """Adding the M5 mesh helpers to ``random_scenes`` must not change any scene of the frozen RNG
    draw order (the conformance cases and other test modules rely on them)."""
    import hashlib

    def h(obj):
        return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]
    got = [h(random_scenes.make_scene(seed)) for seed in (0, 1, 3, 9, 14, 23, 38, 101)]
    got += [h(random_scenes.make_scene(7, 5, "point")), h(random_scenes.make_benchmark_scene())]
    assert got == ['47a20ab723d05faf', '075436f29bcbff67', 'a5f2bc22b03e1134', '545a2aafc0cdddb1',
                   'abc0e0dff1ecc701', '5fa14e7a0a68466b', '3ca6efb78725a29b', '0a16a469ce154800',
                   'f7f4155414737479', 'dbce76c756497f29']


# --- every polyhedral conformance scene, its objects rewritten as meshes ------------------------------

def _polyhedral_case_names():
    names = []
    for path in sorted(CASES.glob("*.json")):
        scene = json.loads(path.read_text(encoding="utf-8"))
        if all(o["type"] in ("box", "prism") for o in scene["objects"]):
            names.append(path.stem)
    return names


@pytest.mark.parametrize("name", _polyhedral_case_names())
def test_polyhedral_cases_rewritten_as_meshes_are_unchanged(name):
    """A box / prism written as a ``mesh`` with the parametric vertices and faces renders the same
    document (after deleting the two mesh edge keys and the kind named in the LIGHT_INSIDE_OBJECT
    message; ``smooth_angle_deg = 0`` so that every edge is drawn as for a primitive): the ground-clipped loop mesh, the feature-vertex ray selection and the inside test of
    the mesh path agree with the primitive path on buried, concave, degenerate and random scenes."""
    from castplane.mesh import box_mesh, prism_mesh
    raw = json.loads((CASES / f"{name}.json").read_text(encoding="utf-8"))
    ref = render(load_scene(raw))["geometry"]
    scene = copy.deepcopy(raw)
    validated = load_scene(raw)["objects"]
    for k, o in enumerate(validated):
        local = box_mesh(o["size"]) if o["type"] == "box" else prism_mesh(o["polygon"], o["height"])
        # smooth_angle_deg 0: every edge a feature edge (a prism's nearly coplanar sides would otherwise
        # be smooth edges, drawn only as camera silhouettes, which is the mesh rule and not the primitive's)
        scene["objects"][k] = {"id": o["id"], "type": "mesh", "transform": o["transform"], "smooth_angle_deg": 0,
                               "data": {"vertices": local["vertices"].tolist(), "faces": local["faces"]}}
    doc = strip_mesh_keys(render(load_scene(scene))["geometry"])
    for w in doc["warnings"] + ref["warnings"]:
        if w["code"] == "LIGHT_INSIDE_OBJECT":
            w["message"] = "inside"
    assert dumps(doc) == dumps(ref)


def test_buried_mesh_rays_reuse_the_shadow_record_silhouette(monkeypatch):
    """A receiver-clipped (buried) mesh evaluates ``face_lit_flags`` on the clipped mesh exactly as often
    as the parametric box does: the §5.2.4 ray selection reuses the silhouette mask of the shadow record
    instead of recomputing it, and still selects the same rays."""
    from castplane import pipeline

    def counted(scene):
        calls = []
        real = pipeline.face_lit_flags
        monkeypatch.setattr(pipeline, "face_lit_flags", lambda *a, **k: calls.append(1) or real(*a, **k))
        doc = doc_of(scene)
        monkeypatch.setattr(pipeline, "face_lit_flags", real)
        return len(calls), doc

    box = analytic_box_scene()
    box["objects"][0]["transform"] = {"position": [0.0, 0.0, -0.5]}
    n_box, ref = counted(box)
    n_mesh, doc = counted(mesh_box_scene(transform={"position": [0.0, 0.0, -0.5]}))
    assert n_box >= 1 and n_mesh == n_box
    assert ("OBJECT_BELOW_RECEIVER", ("cube",)) in warning_set(doc)
    assert doc["construction"]["rays"] == ref["construction"]["rays"] != []
    assert dumps(strip_mesh_keys(doc)) == dumps(ref)


# --- step 8: acceptance 1 end-to-end through the loaders (contract §5.2.11) ------------------------

@pytest.mark.parametrize("name, keys", [("box_split.obj", {}), ("box_split_y.obj", {"up": "y"}), ("box.gltf", {}),
                                        ("box.glb", {})])
def test_acceptance_1_end_to_end_through_load_expanded_scene(name, keys):
    """``mesh`` + ``path`` (relative to the scene file) -> ``castplane.io.load_expanded_scene`` -> the
    parametric box document, byte for byte after deleting the two mesh-only edge keys."""
    from castplane.io import load_expanded_scene

    scene = analytic_box_scene()
    scene["objects"] = [dict({"id": "cube", "type": "mesh", "path": f"../../fixtures/meshes/{name}"}, **keys)]
    loaded, notes = load_expanded_scene(scene, base_dir=CASES)
    assert notes == [] and loaded["objects"][0]["data"]["faces"] == SPLIT_F
    assert loaded["objects"][0]["path"] == f"../../fixtures/meshes/{name}" and loaded["objects"][0]["up"] == "z"
    doc = render(loaded)["geometry"]
    assert dumps(strip_mesh_keys(doc)) == dumps(doc_of(analytic_box_scene()))


# --- M4/M5 merge: meshes on bounded receivers (contract §5.2.5, §5.2.7, §5.2.11) -------------------

def wall_mesh_scene(faces, vertices=None, floor=False) -> dict:
    """``tests.test_receivers.wall_and_ground_scene`` (the §5.1.11 hand-computed case) with the crate
    replaced by an inline mesh of the same unit box; ``floor`` swaps the unbounded ground for the
    bounded floor tile ``[-2, 2] x [2, 5.5]`` of ``test_raycast_iou_on_plates`` (bounded default receiver)."""
    from tests.test_receivers import wall_and_ground_scene

    scene = wall_and_ground_scene()
    scene["objects"] = [{"id": "crate", "type": "mesh",
                         "data": {"vertices": copy.deepcopy(CUBE_V if vertices is None else vertices),
                                  "faces": copy.deepcopy(faces)},
                         "transform": {"position": [0, 4.5, 0]}}]
    if floor:
        scene["receivers"] = [{"id": "floor", "type": "plane", "normal": [0, 0, 1], "offset": 0,
                               "bounds": [[-2, 2, 0], [2, 2, 0], [2, 5.5, 0], [-2, 5.5, 0]]},
                              scene["receivers"][1]]
    return scene


@pytest.mark.parametrize("floor", [False, True], ids=["ground+wall", "floor+wall"])
def test_fallback_mesh_on_a_bounded_receiver(floor):
    """§5.2.5 / §5.2.7: a non-manifold mesh is never cut by any receiver plane (``clipped[r] = None``); on a
    bounded receiver every face loop is shadowed with ``M_r`` and cut by the bounds; the union of the
    loops agrees with the ray cast on the plate (IoU >= 0.99); no rays / checks for the fallback object."""
    from tests.test_receivers import plate_masks

    scene = load_scene(wall_mesh_scene(OPEN_BOTTOM_F, floor=floor))
    A = shadow_geometry(scene)
    (obj,) = A["objects"]
    assert obj["fallback"] is True and obj["ground_mesh"] is None
    assert obj["clipped"] and all(c is None for c in obj["clipped"].values())
    doc = render(scene)["geometry"]
    assert warning_set(doc) == {("MESH_NON_MANIFOLD", ("crate",))}
    pts = doc["points"]
    rids = ("floor", "wall") if floor else ("wall",)
    for rid in rids:
        (sh,) = [s for s in doc["shadows"] if s["receiver"] == rid and s["object"] == "crate"]
        assert sh["loops"] and sh["unbounded"] is False and sh["outline"] == sh["loops"][0]
        sfx = "" if rid == scene["receivers"][0]["id"] else f".{rid}"
        rcv = next(r for r in scene["receivers"] if r["id"] == rid)
        B = np.asarray(rcv["bounds"], dtype=float)
        for loop in sh["loops"]:
            assert len(loop) >= 3
            for name in loop:
                assert name.startswith("crate.") and name.endswith(f".lamp{sfx}"), name
                X = np.asarray(pts[name]["world"], dtype=float)
                assert abs(float(np.dot(rcv["normal"], X)) + rcv["offset"]) <= 1e-9
                assert np.all(X >= B.min(axis=0) - 1e-9) and np.all(X <= B.max(axis=0) + 1e-9), (name, X)
        mask_doc, mask_ref = plate_masks(scene, doc, rid)
        assert mask_ref.any() and raster.iou(mask_doc, mask_ref) >= 0.99, (rid, raster.iou(mask_doc, mask_ref))
    con = doc["construction"]
    rays = con["rays"] + [r for pr in con["per_receiver"].values() for r in pr["rays"]]
    checks = con["checks"] + [c for pr in con["per_receiver"].values() for c in pr["checks"]]
    assert not any("crate" in json.dumps(r) for r in rays + checks)
    assert dumps(render(scene)["geometry"]) == dumps(doc)                  # deterministic


@pytest.mark.parametrize("floor", [False, True], ids=["ground+wall", "floor+wall"])
def test_manifold_mesh_on_bounded_receivers_equals_the_parametric_crate(floor):
    """Acceptance 1 on the M4 receivers: the split / triangulated mesh crate renders the parametric crate's
    document byte for byte (after deleting the two mesh-only edge keys), including the per-receiver rays
    selected through ``ray_vertices`` on the receiver-clipped loop mesh."""
    from tests.test_receivers import wall_and_ground_scene

    ref_scene = wall_and_ground_scene()
    mesh_scene = wall_mesh_scene(SPLIT_F, SPLIT_V, floor=floor)
    ref_scene["receivers"] = mesh_scene["receivers"]
    ref = doc_of(ref_scene)
    doc = doc_of(mesh_scene)
    assert ref["construction"]["per_receiver"]["wall"]["rays"]
    assert dumps(strip_mesh_keys(doc)) == dumps(ref)
