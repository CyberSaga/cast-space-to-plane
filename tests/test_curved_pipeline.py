"""M2 integration of the curved primitives through the full pipeline (spec §5.6, §7.2 bullet 3, §7.3,
§10 M2; contract §2.6, §2.7, §2.10, §3.1): the §6.2 document, the SVG layers and the ray-cast
reference, on ``examples/curved_demo.json``, the §4 pillar and purpose-built scenes."""

from __future__ import annotations

import json
import math
import pathlib
import re
import xml.dom.minidom

import numpy as np
import pytest

import castplane
import castplane.curved
import castplane.primitives
from castplane.conics import (circle_matrix, conic_point, ellipse_params, embed_circle, ground_conic_map,
                              transform_conic)
from castplane.errors import warning_codes
from castplane.light import light_vector
from castplane.output.geometry_json import dumps
from castplane.output.svg import write_svg
from castplane.scene import load_scene
from castplane.shadow import shadow_matrix
from tests.reference import random_scenes, raster, raycast
from tests.test_degenerate import finite_and_drawable, ground_loops, image_space_reference, rect

EXAMPLES = pathlib.Path(__file__).resolve().parents[1] / "examples"
GROUND = np.array([0.0, 0.0, 1.0, 0.0])
CURVED = ("cylinder", "sphere", "cone")


def scene_with(objects, light, camera, canvas=(360, 240), near=0.05):
    return load_scene({
        "version": "0.1",
        "objects": objects,
        "lights": [light],
        "receivers": [{"id": "ground", "type": "plane", "normal": [0, 0, 1], "offset": 0.0}],
        "camera": dict({"roll_deg": 0, "focal_length_mm": 35, "frame_mm": [36, 24], "near_m": near}, **camera),
        "output": {"canvas_mm": list(canvas)},
    })


FAR_CAMERA = {"position": [4.0, -8.0, 5.0], "target": [0.0, 0.0, 0.5]}


@pytest.fixture(scope="module")
def demo():
    scene = load_scene(EXAMPLES / "curved_demo.json")
    return scene, castplane.render(scene)


def conic_map(doc, scene, entry):
    """``H`` of a §3.1 conic entry rebuilt from the document: ``P E`` (image) or ``P M E`` (shadow)."""
    P = np.array(doc["camera"]["P"])
    c = entry["circle"]
    E = embed_circle(c["centre"], c["e1"], c["e2"])
    if entry["map"] == "shadow":
        M = shadow_matrix(GROUND, light_vector(scene["lights"][0]))
        return P @ M @ E
    return P @ E


def ground_iou(scene, doc, n=500):
    light = scene["lights"][0]
    xs, ys = random_scenes.sample_grid(scene, light, n=n)
    ref = raycast.shadow_mask(scene, light, xs, ys)
    got = raster.rasterize_polygons(ground_loops(doc), xs, ys)
    return raster.iou(got, ref)


# --------------------------------------------------------------------------- §7.2 bullet 3 through render()
@pytest.mark.parametrize("phi_deg", [25.0, 40.0, 55.0, 70.0])
@pytest.mark.parametrize("az_deg", [30.0, 200.0])
def test_sphere_directional_shadow_ellipse_closed_form_through_the_pipeline(phi_deg, az_deg):
    """Sphere centre ``(0, 0, r)``, sun at elevation φ: the shadow ellipse has semi-axes ``r / sin φ``
    (along the sun's ground direction) and ``r``, and its centre is ``r / tan φ`` behind the foot of the
    sphere.  Checked on (a) the world conic rebuilt from the entry's circle and ``M``, (b) the image conic
    of the entry re-mapped to the ground through the document's ``P`` and (c) the named polygon points."""
    r = 0.6
    phi, az = math.radians(phi_deg), math.radians(az_deg)
    d = np.array([math.cos(phi) * math.cos(az), math.cos(phi) * math.sin(az), math.sin(phi)])
    sun = {"id": "sun", "type": "directional", "direction": d.tolist()}
    ball = {"id": "ball", "type": "sphere", "radius": r}
    scene = scene_with([ball], sun, FAR_CAMERA)
    doc = castplane.render(scene)["geometry"]
    assert doc["warnings"] == []
    sh = [s for s in doc["shadows"] if s["object"] == "ball"][0]
    assert not sh["unbounded"] and len(sh["conics"]) == 1
    entry = sh["conics"][0]
    assert entry["map"] == "shadow" and entry["kind"] == "ellipse" and entry["arc"] is None and not entry["sampled"]
    assert entry["ellipses"] and not entry["polylines"] and not entry["arcs"]
    major_expected, minor_expected = r / math.sin(phi), r
    centre_expected = -(r / math.tan(phi)) * np.array([math.cos(az), math.sin(az)])
    # (a) world conic: H_ground = rows x, y, w of M E
    M = shadow_matrix(GROUND, light_vector(sun))
    c = entry["circle"]
    E = embed_circle(c["centre"], c["e1"], c["e2"])
    C_world = transform_conic(circle_matrix(c["radius"]), ground_conic_map(M, E))
    centre, (major, minor), rot = ellipse_params(C_world)
    assert major == pytest.approx(major_expected, rel=1e-9) and minor == pytest.approx(minor_expected, rel=1e-9)
    np.testing.assert_allclose(centre, centre_expected, atol=1e-9)
    assert abs(math.sin(rot - az)) < 1e-9                                    # major axis along the sun azimuth
    # (b) the image conic re-mapped to the ground: C_ground = G^T C_img G with G the ground homography
    P = np.array(doc["camera"]["P"])
    G = P[:, [0, 1, 3]]
    C_img = np.array(entry["conic"])
    centre2, (major2, minor2), _rot2 = ellipse_params(G.T @ C_img @ G)
    assert major2 == pytest.approx(major_expected, rel=1e-6) and minor2 == pytest.approx(minor_expected, rel=1e-6)
    np.testing.assert_allclose(centre2, centre_expected, atol=1e-6)
    # (c) the named polygon points lie on the ground and on that ellipse, and span its axes
    pts = np.array([doc["points"][n]["world"] for n in sh["outline"]])
    assert np.all(np.abs(pts[:, 2]) < 1e-9)
    along = np.array([math.cos(az), math.sin(az)])
    across = np.array([-math.sin(az), math.cos(az)])
    rel = pts[:, :2] - centre_expected
    assert np.max(np.abs(rel @ along)) == pytest.approx(major_expected, rel=2e-3)
    assert np.max(np.abs(rel @ across)) == pytest.approx(minor_expected, rel=2e-3)
    u = (rel @ along) / major_expected
    v = (rel @ across) / minor_expected
    assert np.max(np.abs(u * u + v * v - 1.0)) < 1e-9
    # the silhouette circle quarter points name four of the polygon vertices
    assert {f"ball.sil.{k}.shadow.sun" for k in range(4)} <= set(sh["outline"])
    assert sh["outline"].count("ball.sil.0.shadow.sun") == 1
    assert max(cc["max_error_mm"] for cc in doc["construction"]["checks"]) <= 1e-6


# --------------------------------------------------------------------------- §4 pillar / lamp
def test_pillar_tangent_generators_through_the_pipeline():
    """Contract §4 analytic case: pillar base (-1.5, 6, 0), r = 0.3 under the lamp (0, 3, 3.5): the
    tangent generators sit at -148.30° and 21.43° (document points ``pillar.g0.base`` / ``pillar.g1.base``)."""
    scene = load_scene(EXAMPLES / "basic.json")
    doc = castplane.render(scene)["geometry"]
    angles = []
    for k in (0, 1):
        base = doc["points"][f"pillar.g{k}.base"]["world"]
        top = doc["points"][f"pillar.g{k}.top"]["world"]
        assert base[2] == pytest.approx(0.0) and top[2] == pytest.approx(2.4)
        assert base[:2] == pytest.approx(top[:2])
        angles.append(math.degrees(math.atan2(base[1] - 6.0, base[0] + 1.5)))
    assert angles[0] == pytest.approx(-148.30, abs=0.01) and angles[1] == pytest.approx(21.43, abs=0.01)
    # the generators are tangent to the pillar as seen from the lamp: u_theta . (l - p) = 0
    for k, ang in enumerate(angles):
        u = np.array([math.cos(math.radians(ang)), math.sin(math.radians(ang)), 0.0])
        for name in (f"pillar.g{k}.base", f"pillar.g{k}.top"):
            p = np.array(doc["points"][name]["world"])
            assert abs(u @ (np.array([0.0, 3.0, 3.5]) - p)) < 1e-9
    # their shadows are the ends of the shadow outline's straight parts, and the base points are their own shadow
    sh = [s for s in doc["shadows"] if s["object"] == "pillar"][0]
    for k in (0, 1):
        np.testing.assert_allclose(doc["points"][f"pillar.g{k}.base.shadow.lamp"]["world"],
                                   doc["points"][f"pillar.g{k}.base"]["world"], atol=1e-12)
        assert f"pillar.g{k}.base.shadow.lamp" in sh["outline"] and f"pillar.g{k}.top.shadow.lamp" in sh["outline"]
    assert [c["which"] for c in sh["conics"]] == ["base", "top"]
    assert all(c["kind"] == "ellipse" and c["map"] == "shadow" and c["arc"] is not None for c in sh["conics"])
    # terminator: the two generators (named) and the two cap arcs, thin line in the form_shadow layer
    fs = [f for f in doc["form_shadow"] if f["object"] == "pillar"][0]
    assert fs["faces"] == [] and fs["polygons"] == []
    segs = [t["segment"] for t in fs["terminator"] if "segment" in t]
    assert sorted(map(tuple, segs)) == [("pillar.g0.top", "pillar.g0.base"), ("pillar.g1.base", "pillar.g1.top")]
    assert [t["which"] for t in fs["terminator"] if "segment" not in t] == ["base", "top"]


# --------------------------------------------------------------------------- curved_demo.json
def test_curved_demo_document_and_svg(demo):
    scene, result = demo
    doc, svg = result["geometry"], result["svg"]
    assert doc["warnings"] == []
    assert [o["id"] for o in scene["objects"]] == ["drum", "ball", "cone"]
    assert [s["object"] for s in doc["shadows"]] == ["drum", "ball", "cone"]
    assert all(not s["unbounded"] and s["conics"] and s["polygons"] for s in doc["shadows"])
    assert [o["object"] for o in doc["outlines"]] == ["drum", "ball", "cone"]
    # objects layer: cylinder = 2 generators + 4 cap arcs (the camera at z = 1.6 is above the 1.5 m top, so
    # only the far base arc is back); sphere = 1 outline circle; cone = 2 generators + 2 base arcs
    drum = doc["outlines"][0]["conics"]
    assert [(c["which"], c["back"]) for c in drum] == [("base", False), ("base", True), ("top", False), ("top", False)]
    assert all(c["kind"] == "ellipse" and c["map"] == "image" and c["arcs"] for c in drum)
    ball = doc["outlines"][1]["conics"]
    assert len(ball) == 1 and ball[0]["which"] == "silhouette" and ball[0]["ellipses"] and not ball[0]["back"]
    cone = doc["outlines"][2]["conics"]
    assert [(c["which"], c["back"]) for c in cone] == [("base", False), ("base", True)]
    gens = {o["object"]: [(g["from"], g["to"]) for g in o["generators"]] for o in doc["outlines"]}
    assert gens["drum"] == [("drum.og0.base", "drum.og0.top"), ("drum.og1.base", "drum.og1.top")]
    assert gens["ball"] == []
    assert gens["cone"] == [("cone.og0.base", "cone.og0.top"), ("cone.og1.base", "cone.og1.top")]
    np.testing.assert_allclose(doc["points"]["cone.og0.top"]["world"], doc["points"]["cone.apex"]["world"])
    assert all(not g["back"] and g["segment"] is not None for o in doc["outlines"] for g in o["generators"])
    assert not any(e["object"] in CURVED for e in doc["edges"])        # edges[] is camera independent
    # terminators
    fs = {f["object"]: f["terminator"] for f in doc["form_shadow"]}
    assert set(fs) == {"drum", "ball", "cone"}
    assert len(fs["ball"]) == 1 and fs["ball"][0]["arc"] is None and fs["ball"][0]["ellipses"]
    assert sorted(tuple(t["segment"]) for t in fs["cone"] if "segment" in t) == [("cone.apex", "cone.g0.base"),
                                                                                    ("cone.g1.base", "cone.apex")]
    for t in fs["drum"] + fs["cone"]:
        if "segment" in t:
            assert t["polylines"] and len(t["polylines"][0]) == 2
            for name in t["segment"]:
                assert doc["points"][name]["image"] is not None
    # construction points and their shadows / feet
    con = doc["construction"]
    expected = {"drum.g0.base", "drum.g0.top", "drum.g1.base", "drum.g1.top", "ball.c", "ball.sil.0", "ball.sil.1",
                "ball.sil.2", "ball.sil.3", "cone.g0.base", "cone.g1.base", "cone.apex"}
    assert {r[1] for r in con["rays"] if r[0] == "L"} == expected
    M = shadow_matrix(GROUND, light_vector(scene["lights"][0]))
    for name in expected:
        P = np.array(doc["points"][name]["world"] + [1.0])
        S = M @ P
        np.testing.assert_allclose(doc["points"][f"{name}.shadow.lamp"]["world"], S[:3] / S[3], atol=1e-9)
        np.testing.assert_allclose(doc["points"][f"{name}.foot"]["world"], [P[0], P[1], 0.0], atol=1e-12)
    # the sphere construction points: centre and the four silhouette-circle points at distance r_s from it
    c = np.array(doc["points"]["ball.c"]["world"])
    assert c == pytest.approx([0.5, 5.0, 0.55])
    sil = np.array([doc["points"][f"ball.sil.{k}"]["world"] for k in range(4)])
    L = np.array(scene["lights"][0]["position"])
    for p in sil:
        assert abs((p - c) @ (L - p)) < 1e-9                       # on the tangent cone: (p - c) ⊥ (l - p)
        assert np.linalg.norm(p - c) == pytest.approx(0.55, rel=1e-9)
    # SVG: layers, dashed back arcs, conic outlines without fill, labels
    xml.dom.minidom.parseString(svg)
    assert '<g id="objects.drum.back"' in svg and '<g id="objects.cone.back"' in svg
    assert 'objects.ball.back' not in svg
    back = re.search(r'<g id="objects.drum.back"[^>]*>(.*?)</g>', svg, re.S).group(1)
    assert back.count("<path") == 1 and "A " in back
    assert re.search(r'<g id="cast_shadow.lamp.drum.conics" fill="none">', svg)
    assert re.search(r'<g id="form_shadow.ball.terminator"[^>]*stroke="#335"', svg)
    for label in ("g0.base", "g1.top", "sil.0", "sil.3", "apex", "c"):
        assert f">{label}<" in svg
    assert ">og0.base<" not in svg and not re.search(r">s\d+<", svg)
    for oid in ("drum", "ball", "cone"):
        assert f">{oid}<" in svg
    assert '<ellipse' in svg


def test_every_curved_construction_point_passes_the_self_check(demo):
    scene, result = demo
    doc = result["geometry"]
    con = doc["construction"]
    skipped = {w["ids"][0] for w in doc["warnings"] if w["code"] == "CONSTRUCTION_CHECK_SKIPPED"}
    assert not skipped
    checked = {c["point"]: c["max_error_mm"] for c in con["checks"]}
    for kind, name in con["rays"]:
        if kind != "L":
            continue
        key = f"{name}.shadow.lamp"
        assert key in checked and checked[key] <= 1e-6, key
    assert len(checked) == 12
    # independent recomputation: (L' x P') x (F' x Q') = S'
    Lp = np.array(con["light_point"] + [1.0])
    Fp = np.array(con["shadow_vp"] + [1.0])
    for kind, name in con["rays"]:
        if kind != "L":
            continue
        P = np.array(doc["points"][name]["image"] + [1.0])
        Q = np.array(doc["points"][f"{name}.foot"]["image"] + [1.0])
        S = doc["points"][f"{name}.shadow.lamp"]["image"]
        meet = np.cross(np.cross(Lp, P), np.cross(Fp, Q))
        np.testing.assert_allclose(meet[:2] / meet[2], S, atol=1e-6)


def test_curved_demo_cast_shadows_match_the_raycast_reference(demo):
    scene, result = demo
    assert ground_iou(scene, result["geometry"]) >= 0.99


@pytest.mark.parametrize("seed, n", [(11, 5), (12, 6), (13, 3), (14, 5), (15, 2)])
def test_seeded_mixed_scenes_match_the_raycast_reference(seed, n):
    """§7.3 for mixed scenes (all five kinds, tilted objects): the named ground polygons of the document
    (sampled conic arcs plus generator shadows) agree with the ray caster."""
    raw = random_scenes.make_scene(seed, n)
    if n >= 5:
        assert {o["type"] for o in raw["objects"]} >= set(CURVED)
    scene = load_scene(raw)
    doc = castplane.render(scene)["geometry"]
    assert all(not s["unbounded"] for s in doc["shadows"])
    assert ground_iou(raw, doc, n=500) >= 0.99
    finite_and_drawable(doc)


@pytest.mark.parametrize("kind, light_type, seed", [(k, lt, s) for k in CURVED for lt in ("point", "directional")
                                                    for s in (5, 6)])
def test_single_curved_object_through_render_matches_raycast(kind, light_type, seed):
    rng = np.random.default_rng(seed)
    o = random_scenes.random_object(rng, 0, kind, allow_tilt=True)
    light = random_scenes.random_light(rng, [o], light_type)
    raw = random_scenes.assemble_scene([o], light, random_scenes.random_camera(rng, [o]))
    doc = castplane.render(load_scene(raw))["geometry"]
    sh = doc["shadows"][0]
    assert sh["conics"] and not sh["unbounded"]
    assert ground_iou(raw, doc, n=400) >= 0.99
    # the drawn polygon of a bounded shadow is the image of its named points when fully visible
    W, H = doc["canvas_mm"]
    imgs = [doc["points"][n]["image"] for n in sh["outline"]]
    if all(i is not None and abs(i[0]) <= 0.75 * W and abs(i[1]) <= 0.75 * H for i in imgs):
        np.testing.assert_allclose(sh["polygons"][0], imgs, atol=1e-9)


# --------------------------------------------------------------------------- unbounded curved shadow
def test_unbounded_sphere_shadow_is_finite_and_covers_the_far_direction():
    """Sphere top above the point light: ``VERTEX_NOT_BELOW_LIGHT``, direction entries, a finite drawn
    polygon (near clip + rectangle clip) agreeing with the ray caster in image space."""
    ball = {"id": "ball", "type": "sphere", "radius": 1.0, "transform": {"position": [0.0, 5.0, 0.0]}}
    lamp = {"id": "lamp", "type": "point", "position": [-2.5, 5.0, 1.5]}
    scene = scene_with([ball], lamp, {"position": [0.0, -3.0, 2.5], "target": [0.5, 5.0, 0.5]})
    doc = castplane.render(scene)["geometry"]
    assert [w["ids"] for w in doc["warnings"] if w["code"] == "VERTEX_NOT_BELOW_LIGHT"] == [["ball"]]
    sh = doc["shadows"][0]
    assert sh["unbounded"] is True
    dirs = [e["direction"] for e in sh["outline"] if isinstance(e, dict)]
    assert len(dirs) >= 2 and all(abs(np.linalg.norm(d) - 1.0) < 1e-12 and d[2] == 0.0 for d in dirs)
    assert all(d[0] > 0.5 for d in dirs)                                   # away from the light: +x
    # the conic of the kept arc is drawn as a sampled polyline when its image is not an ellipse, never
    # as a chord across w = 0; every drawn point lies inside the extended canvas
    u0, u1, v0, v1 = rect(doc)
    for poly in sh["polygons"]:
        for u, v in poly:
            assert u0 <= u <= u1 and v0 <= v <= v1
    for c in sh["conics"]:
        assert c["arc"] is not None
        for pl in c["polylines"]:
            for u, v in pl:
                assert u0 <= u <= u1 and v0 <= v <= v1
        for a in c["arcs"]:
            for u, v in (a["start"], a["end"]):
                assert u0 <= u <= u1 and v0 <= v <= v1
    iou, outside, horizon_ok = image_space_reference(scene, doc)
    assert iou >= 0.99 and outside == 0 and horizon_ok
    # the centre is below the light (shadow exists) but the top silhouette point is not
    assert "ball.c.shadow.lamp" in doc["points"]
    finite_and_drawable(doc)


def test_unbounded_cylinder_and_cone_shadows_in_image_space():
    for obj in ({"id": "t", "type": "cylinder", "radius": 0.5, "height": 3.0, "transform": {"position": [0.0, 5.0, 0.0]}},
                {"id": "t", "type": "cone", "radius": 0.7, "height": 3.0, "transform": {"position": [0.0, 5.0, 0.0]}}):
        lamp = {"id": "lamp", "type": "point", "position": [-2.5, 4.0, 1.8]}
        scene = scene_with([obj], lamp, {"position": [1.0, -4.0, 3.0], "target": [0.0, 5.0, 1.0]})
        doc = castplane.render(scene)["geometry"]
        assert "VERTEX_NOT_BELOW_LIGHT" in warning_codes(doc["warnings"])
        assert doc["shadows"][0]["unbounded"]
        iou, outside, horizon_ok = image_space_reference(scene, doc)
        assert iou >= 0.99 and outside == 0 and horizon_ok, obj["type"]
        finite_and_drawable(doc)


# --------------------------------------------------------------------------- circle partly behind the camera
def back_project_to_circle(doc, uv, circle):
    """World point of the viewing ray through the image point ``uv`` (canvas mm) on the plane of
    ``circle`` and its depth ``x3`` (contract §2.2), rebuilt from the document's ``P`` and ``C``."""
    P = np.array(doc["camera"]["P"])
    C = np.array(doc["camera"]["C"])
    d = np.linalg.solve(P[:, :3], np.array([uv[0], uv[1], 1.0]))     # ray direction (R^T K^-1 x)
    n = np.cross(circle["e1"], circle["e2"])
    lam = float(n @ (np.array(circle["centre"]) - C)) / float(n @ d)
    X = C + lam * d
    return X, float(P[2] @ np.append(X, 1.0))


def circle_param(X, circle):
    rel = np.asarray(X) - np.array(circle["centre"])
    return math.atan2(float(rel @ circle["e2"]), float(rel @ circle["e1"])) % (2 * math.pi)


def in_intervals(theta, intervals):
    return any((theta - lo) % (2 * math.pi) <= (hi - lo) + 1e-9 for lo, hi in intervals)


def test_circle_crossing_the_near_plane_draws_only_the_visible_arc():
    """A short, wide cylinder with the camera 0.3 m above its top cap, looking across it: both cap
    circles cross the near plane and their visible parts run right across the canvas.  Every drawn
    point back-projects onto the circle with depth >= near, every drawn polyline segment follows the
    circle (no chord across the canvas: the mid-points of the drawn segments are on the circle too),
    and the parameter range behind the near plane is never drawn."""
    cyl = {"id": "cyl", "type": "cylinder", "radius": 1.2, "height": 0.2, "transform": {"position": [0.0, 0.0, 0.0]}}
    lamp = {"id": "lamp", "type": "point", "position": [1.0, 2.0, 3.0]}
    scene = scene_with([cyl], lamp, {"position": [0.0, -0.4, 0.5], "target": [0.0, 5.0, 0.1], "focal_length_mm": 18},
                       near=0.05)
    A = castplane.shadow_geometry(scene)
    B = castplane.project_scene(scene, A)
    doc = castplane.compose(scene, B)
    assert [w["ids"] for w in doc["warnings"] if w["code"] == "POINT_BEHIND_CAMERA"] == [["cyl"]]
    rec = B["objects"][0]
    assert rec["analytic"] and not rec["camera_inside"]
    near = scene["camera"]["near_m"]
    entries = doc["outlines"][0]["conics"]
    assert len(entries) == 2 and {e["which"] for e in entries} == {"base", "top"}
    W, H = doc["canvas_mm"]
    u0, u1, v0, v1 = rect(doc)
    drawn_wide = 0
    for a, entry in zip(rec["outline_arcs"], entries):
        assert a["near_cut"] and not a["whole_circle"] and entry["kind"] == "hyperbola"
        assert not entry["ellipses"] and not entry["arcs"] and entry["polylines"]
        front = a["front"]
        assert len(front) == 1 and 0.0 < front[0][1] - front[0][0] < 2 * math.pi
        circle = entry["circle"]
        r = circle["radius"]
        # the near-clipped arc ends sit exactly at depth == near
        E = embed_circle(circle["centre"], circle["e1"], circle["e2"])
        P = np.array(doc["camera"]["P"])
        for th in front[0]:
            X = conic_point(E, th, r)
            assert float(P[2] @ X) / X[3] == pytest.approx(near, abs=1e-9)
        for pl in entry["polylines"]:
            pts = np.array(pl)
            assert np.all(pts[:, 0] >= u0) and np.all(pts[:, 0] <= u1) and np.all(pts[:, 1] >= v0) and np.all(pts[:, 1] <= v1)
            if pts[:, 0].max() - pts[:, 0].min() > W:
                drawn_wide += 1
            for uv in pts:
                X, depth = back_project_to_circle(doc, uv, circle)
                assert depth >= near - 1e-9
                assert np.linalg.norm(X - circle["centre"]) == pytest.approx(r, abs=1e-6)
                assert in_intervals(circle_param(X, circle), front)
            for p, q in zip(pts[:-1], pts[1:]):           # no chord: the segment mid-points hug the circle
                X, depth = back_project_to_circle(doc, 0.5 * (p + q), circle)
                assert depth >= near - 1e-9
                assert abs(np.linalg.norm(X - circle["centre"]) - r) < 0.01 * r
        # nothing of the behind-the-camera range (the complement of ``front``) is drawn
        lo, hi = front[0]
        behind = [[hi, lo + 2 * math.pi]]
        for pl in entry["polylines"]:
            for uv in pl:
                X, _depth = back_project_to_circle(doc, uv, circle)
                th = circle_param(X, circle)
                assert not ((th - behind[0][0]) % (2 * math.pi) < behind[0][1] - behind[0][0] - 1e-9)
    assert drawn_wide == 2                                   # both visible arcs span the whole canvas width
    # the cap on the far side of the (camera-unlit) lateral surface is the back arc
    back = {e["which"]: e["back"] for e in entries}
    assert back == {"base": True, "top": False}
    svg = finite_and_drawable(doc)
    assert "<ellipse" not in svg
    for coords in re.findall(r'<polyline points="([^"]*)"', svg):
        for pair in coords.split():
            x, y = (float(v) for v in pair.split(","))
            assert -0.25 * W - 1e-3 <= x <= 1.25 * W + 1e-3 and -0.25 * H - 1e-3 <= y <= 1.25 * H + 1e-3


def test_whole_ellipse_is_drawn_only_when_some_of_it_is_inside_the_extended_canvas():
    """A sphere wholly in front of the near plane but far outside the extended canvas: the entry
    has ``visible == []`` and no drawable (no ``<ellipse>`` outside the picture); moved half-way
    into the margin it is drawn as a whole ``<ellipse>`` with a non-empty ``visible``."""
    lamp = {"id": "lamp", "type": "point", "position": [1.0, 2.0, 3.0]}
    cam = {"position": [0.0, -2.0, 2.0], "target": [0.0, 5.0, 0.3], "focal_length_mm": 50}
    ball = {"id": "ball", "type": "sphere", "radius": 0.5, "transform": {"position": [6.0, 5.0, 0.0]}}
    doc = castplane.render(scene_with([ball], lamp, cam))["geometry"]
    entry = doc["outlines"][0]["conics"][0]
    assert entry["kind"] == "ellipse" and entry["visible"] == []
    assert entry["ellipses"] == [] and entry["arcs"] == [] and entry["polylines"] == []
    assert "<ellipse" not in write_svg(doc)
    ball["transform"]["position"] = [3.3, 5.0, 0.0]
    doc = castplane.render(scene_with([ball], lamp, cam))["geometry"]
    entry = doc["outlines"][0]["conics"][0]
    u0, u1, _v0, _v1 = rect(doc)
    assert entry["visible"] and len(entry["ellipses"]) == 1
    ell = entry["ellipses"][0]
    assert ell["centre"][0] + ell["rx"] > u1 > ell["centre"][0] - ell["rx"]   # straddles the margin edge
    assert "<ellipse" in write_svg(doc)


# --------------------------------------------------------------------------- partly buried curved objects (§2.3, §7.3)
BURIED = [
    ("tilted cone, base centre on the ground",
     {"id": "o", "type": "cone", "radius": 0.5, "height": 1.5, "transform": {"position": [0, 0, 0], "rotation_deg": [40, 0, 0]}},
     {"id": "lamp", "type": "point", "position": [2.0, 2.0, 3.0]}),
    ("sphere buried to half its radius",
     {"id": "o", "type": "sphere", "radius": 0.6, "transform": {"position": [0, 0, -0.3]}},
     {"id": "lamp", "type": "point", "position": [2.0, 2.0, 3.0]}),
    ("cylinder tilted 60 deg",
     {"id": "o", "type": "cylinder", "radius": 0.5, "height": 1.5, "transform": {"position": [0, 0, 0], "rotation_deg": [60, 0, 0]}},
     {"id": "lamp", "type": "point", "position": [2.0, 2.0, 3.0]}),
    ("horizontal log half buried",
     {"id": "o", "type": "cylinder", "radius": 0.5, "height": 2.0, "transform": {"position": [-1.0, 0.3, 0.2], "rotation_deg": [90, 0, 30]}},
     {"id": "lamp", "type": "point", "position": [1.5, -2.0, 2.0]}),
    ("cone standing on its apex below the ground",
     {"id": "o", "type": "cone", "radius": 0.7, "height": 1.2, "transform": {"position": [0, 0, 0.9], "rotation_deg": [175, 0, 0]}},
     {"id": "sun", "type": "directional", "direction": [0.3, -0.5, 0.812403840463596]}),
    ("sphere buried past its centre, steep sun",
     {"id": "o", "type": "sphere", "radius": 0.8, "transform": {"position": [0, 0, -1.3]}},
     {"id": "sun", "type": "directional", "direction": [0.2, 0.3, 0.9327379053088815]}),
    ("steep cone with a hyperbolic ground section",
     {"id": "o", "type": "cone", "radius": 0.5, "height": 1.5, "transform": {"position": [0, 0, 0.2], "rotation_deg": [80, 0, 20]}},
     {"id": "lamp", "type": "point", "position": [-2.0, 1.5, 2.5]}),
]


@pytest.mark.parametrize("name, o, light", BURIED, ids=[b[0] for b in BURIED])
def test_partly_buried_curved_object_shadow_matches_the_raycast_reference(name, o, light):
    """Contract §2.3: the drawn shadow of a partly buried object is that of the part above the
    ground, whose cut face adds the lit boundary of the ground cross-section to the outline
    (``curved._ground_chain``); the ray caster (spec §7.3) is the reference, IoU >= 0.99."""
    scene = scene_with([o], light, FAR_CAMERA)
    doc = castplane.render(scene)["geometry"]
    assert [w["ids"] for w in doc["warnings"] if w["code"] == "OBJECT_BELOW_RECEIVER"] == [["o"]]
    sh = doc["shadows"][0]
    assert not sh["unbounded"]
    assert ground_iou(scene, doc, n=500) >= 0.99, name
    # the ground points of the chain are their own shadow: all on the receiver, named <obj>.s<k>.<light>
    ground_names = [n for n in sh["outline"] if isinstance(n, str) and n.split(".")[1].startswith("s")]
    assert ground_names and all(abs(doc["points"][n]["world"][2]) < 1e-8 for n in ground_names)
    finite_and_drawable(doc)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_random_buried_curved_objects_match_the_raycast_reference(seed):
    """Random kinds, rotations and burial depths under point and directional lights."""
    rng = np.random.default_rng(seed)
    for i in range(12):
        kind = CURVED[i % 3]
        r = float(rng.uniform(0.3, 1.0))
        o = {"id": "o", "type": kind, "radius": r, "transform": {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]}}
        if kind != "sphere":
            o["height"] = float(rng.uniform(0.3, 2.5))
            o["transform"]["rotation_deg"] = [float(v) for v in rng.uniform(-180, 180, 3)]
        an = castplane.primitives.build_object(o)["analytic"]
        zmin = castplane.curved.plane_min(an, GROUND)
        size = 2 * r if kind == "sphere" else max(2 * r, o["height"])
        o["transform"]["position"][2] = -zmin - float(rng.uniform(0.05, 0.9)) * size
        top = o["transform"]["position"][2] - zmin + size                  # at or above the highest point
        if rng.uniform() < 0.7:
            light = {"id": "l", "type": "point",
                     "position": [float(rng.uniform(-4, 4)), float(rng.uniform(-4, 4)), float(top + rng.uniform(0.3, 3.0))]}
        else:
            phi, az = math.radians(rng.uniform(20, 85)), math.radians(rng.uniform(0, 360))
            light = {"id": "l", "type": "directional",
                     "direction": [math.cos(phi) * math.cos(az), math.cos(phi) * math.sin(az), math.sin(phi)]}
        scene = scene_with([o], light, FAR_CAMERA)
        doc = castplane.render(scene)["geometry"]
        assert "OBJECT_BELOW_RECEIVER" in warning_codes(doc["warnings"])
        if doc["shadows"][0]["unbounded"]:
            iou, outside, horizon_ok = image_space_reference(scene, doc)
            assert iou >= 0.985 and outside == 0 and horizon_ok, (seed, i, o, light)
        else:
            assert ground_iou(scene, doc, n=400) >= 0.99, (seed, i, o, light)
        finite_and_drawable(doc)


# --------------------------------------------------------------------------- CONIC_SAMPLED
def test_conic_sampled_only_for_an_edge_on_circle(demo):
    _scene, result = demo
    assert "CONIC_SAMPLED" not in warning_codes(result["geometry"]["warnings"])
    cyl = {"id": "cyl", "type": "cylinder", "radius": 0.4, "height": 1.5, "transform": {"position": [0.0, 5.0, 0.0]}}
    lamp = {"id": "lamp", "type": "point", "position": [-2.0, 2.0, 3.5]}
    # a level camera at exactly the top cap's height sees that circle edge-on: H = P E is singular
    scene = scene_with([cyl], lamp, {"position": [0.0, 0.0, 1.5], "target": [0.0, 5.0, 1.5]})
    doc = castplane.render(scene)["geometry"]
    assert [w["ids"] for w in doc["warnings"] if w["code"] == "CONIC_SAMPLED"] == [["cyl"]]
    top = [c for c in doc["outlines"][0]["conics"] if c["which"] == "top"]
    assert top and all(c["sampled"] and c["kind"] == "degenerate" for c in top)
    assert all(c["polylines"] and not c["arcs"] and not c["ellipses"] for c in top)
    for c in top:  # the edge-on circle draws as a straight segment at v = 0 (eye height)
        for pl in c["polylines"]:
            assert all(abs(v) < 1e-9 for _u, v in pl)
    base = [c for c in doc["outlines"][0]["conics"] if c["which"] == "base"]
    assert all(not c["sampled"] and c["kind"] == "ellipse" for c in base)
    finite_and_drawable(doc)


# --------------------------------------------------------------------------- determinism, caching, JSON shape
def test_curved_render_is_deterministic_and_camera_free_in_stage_a(demo):
    scene, result = demo
    text = dumps(result["geometry"])
    again = castplane.render(scene)
    assert dumps(again["geometry"]) == text and again["svg"] == result["svg"]
    assert "NaN" not in text and "Infinity" not in text and not re.search(r"-0\.0(?![0-9])", text)
    parsed = json.loads(text)
    assert parsed == result["geometry"]
    A = castplane.shadow_geometry(scene)
    assert "camera" not in A
    override = dict(scene["camera"], position=[4.0, -3.0, 3.0], target=[0.0, 6.0, 0.5])
    d2 = castplane.compose(scene, castplane.project_scene(scene, A, camera=override))
    d1 = result["geometry"]
    assert [s["loops"] for s in d1["shadows"]] == [s["loops"] for s in d2["shadows"]]
    for name, p in d1["points"].items():
        if ".og" in name:
            continue
        assert d2["points"][name].get("world") == p.get("world"), name
    for c1, c2 in zip(d1["shadows"][0]["conics"], d2["shadows"][0]["conics"]):
        assert c1["circle"] == c2["circle"] and c1["arc"] == c2["arc"]       # world data is camera free
        assert c1["conic"] != c2["conic"]                                     # the image conic is not


def test_conic_entries_have_the_contract_shape(demo):
    _scene, result = demo
    doc = result["geometry"]
    entries = [c for s in doc["shadows"] for c in s["conics"]] + [c for o in doc["outlines"] for c in o["conics"]]
    entries += [t for f in doc["form_shadow"] for t in f["terminator"] if "segment" not in t]
    assert entries
    for c in entries:
        assert {"conic", "kind", "arc", "circle", "map"} <= set(c)
        C = np.array(c["conic"])
        assert C.shape == (3, 3) and np.allclose(C, C.T) and np.max(C) == 1.0
        assert c["kind"] in ("ellipse", "parabola", "hyperbola", "degenerate")
        assert c["map"] in ("image", "shadow")
        assert set(c["circle"]) == {"centre", "e1", "e2", "radius"}
        if c["arc"] is not None:
            assert c["arc"]["theta1"] > c["arc"]["theta0"]
        # the image points of the circle at the drawn parameters satisfy the normalised conic equation
        H = conic_map(doc, _scene, c)
        for lo, hi in c["visible"]:
            for th in np.linspace(lo, hi, 7):
                x = conic_point(H, th, c["circle"]["radius"])
                assert abs(x @ C @ x) <= 1e-9 * float(x @ x)


def test_loop_entry_names_are_canonical(demo):
    scene, result = demo
    doc = result["geometry"]
    for sh in doc["shadows"]:
        oid = sh["object"]
        ground = [n for n in sh["outline"] if isinstance(n, str) and re.fullmatch(rf"{oid}\.s\d+\.lamp", n)]
        assert ground == [f"{oid}.s{k}.lamp" for k in range(len(ground))]       # numbered in loop order
        assert all(abs(doc["points"][n]["world"][2]) < 1e-12 for n in ground)
        for n in ground:
            assert f"{n}.foot" not in doc["points"]                                # ground points: no rays
        named = [n for n in sh["outline"] if isinstance(n, str) and ".shadow." in n]
        assert len(named) == len(set(named))
    drum = [s for s in doc["shadows"] if s["object"] == "drum"][0]["outline"]
    assert {f"drum.g{k}.{e}.shadow.lamp" for k in (0, 1) for e in ("base", "top")} <= set(drum)
    cone = [s for s in doc["shadows"] if s["object"] == "cone"][0]["outline"]
    assert "cone.apex.shadow.lamp" in cone and "cone.g0.base.shadow.lamp" in cone


# --------------------------------------------------------------------------- SVG arcs: flags verified
def svg_arc_centre(x1, y1, x2, y2, rx, ry, phi_deg, large, sweep):
    """SVG implementation notes F.6.5: endpoint -> centre parameterisation; returns
    ``(cx, cy, theta1, delta)`` in SVG (y-down) coordinates."""
    phi = math.radians(phi_deg)
    c, s = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p, y1p = c * dx + s * dy, -s * dx + c * dy
    lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if lam > 1.0:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) * (1.0 if large != sweep else -1.0)
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    cx = c * cxp - s * cyp + (x1 + x2) / 2.0
    cy = s * cxp + c * cyp + (y1 + y2) / 2.0

    def angle(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a
    theta1 = angle(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi
    return cx, cy, rx, ry, theta1, delta


ARC_RE = re.compile(r'<path d="M ([-\d.]+) ([-\d.]+) A ([-\d.]+) ([-\d.]+) ([-\d.]+) ([01]) ([01]) ([-\d.]+) ([-\d.]+)"')


@pytest.mark.parametrize("example", ["curved_demo.json", "basic.json", "directional.json"])
def test_svg_elliptical_arcs_sweep_through_the_sampled_curve(example):
    """Every ``<path … A …>`` of the SVG is the arc of the right ellipse in the right direction: the circle
    point at the parameter midpoint of the drawable lands on the SVG arc (its eccentric angle lies inside the
    swept range), the arc endpoints are the images of the parameter endpoints and the arc never covers the
    sampled points of the complementary parameter range.  ``<ellipse>`` elements pass through sampled
    points of the whole circle."""
    scene = load_scene(EXAMPLES / example)
    doc = castplane.render(scene)["geometry"]
    svg = write_svg(doc)
    W, H = doc["canvas_mm"]

    def to_svg(uv):
        return uv[0] + W / 2.0, H / 2.0 - uv[1]

    def fmt(x):
        s = f"{x + 0.0:.4f}".rstrip("0").rstrip(".")
        return "0" if s in ("-0", "") else s

    paths = {}
    for m in ARC_RE.finditer(svg):
        vals = m.groups()
        paths[(vals[0], vals[1], vals[7], vals[8])] = [float(v) for v in vals[:5]] + [int(vals[5]), int(vals[6])] + \
            [float(vals[7]), float(vals[8])]
    entries = [c for s in doc["shadows"] for c in s["conics"]] + [c for o in doc["outlines"] for c in o["conics"]]
    entries += [t for f in doc["form_shadow"] for t in f["terminator"] if "segment" not in t]
    verified = 0
    for entry in entries:
        Hm = conic_map(doc, scene, entry)
        rho = entry["circle"]["radius"]
        for arc in entry["arcs"]:
            sx, sy = to_svg(arc["start"])
            ex, ey = to_svg(arc["end"])
            key = (fmt(sx), fmt(sy), fmt(ex), fmt(ey))
            assert key in paths, key
            x1, y1, rx, ry, rot, large, sweep, x2, y2 = paths[key]
            cx, cy, rx2, ry2, th1, delta = svg_arc_centre(x1, y1, x2, y2, rx, ry, rot, large, sweep)
            assert abs(delta) > 1e-9
            lo, hi = arc["theta"]
            pts = conic_point(Hm, np.array([lo, 0.5 * (lo + hi), hi]), rho)
            uv = pts[:, :2] / pts[:, 2:3]
            np.testing.assert_allclose(to_svg(uv[0]), (x1, y1), atol=2e-4)
            np.testing.assert_allclose(to_svg(uv[2]), (x2, y2), atol=2e-4)
            phi = math.radians(rot)

            def param(p):
                dx, dy = p[0] - cx, p[1] - cy
                xp = math.cos(phi) * dx + math.sin(phi) * dy
                yp = -math.sin(phi) * dx + math.cos(phi) * dy
                return math.atan2(yp / ry2, xp / rx2)

            def inside(p):
                t = (param(p) - th1) / delta
                t = t % (2 * math.pi / abs(delta))
                return t <= 1.0 + 1e-6
            mid = to_svg(uv[1])
            assert inside(mid), (example, entry["which"], entry["map"])
            # the point at the opposite parameter (complementary arc) must not be on the drawn arc, unless the
            # arc covers (nearly) the whole circle
            if hi - lo < 2 * math.pi - 0.2:
                opp = conic_point(Hm, 0.5 * (lo + hi) + math.pi, rho)
                if opp[2] > 0:
                    assert not inside(to_svg(opp[:2] / opp[2]))
            verified += 1
        for ell in entry["ellipses"]:
            cx, cy = to_svg(ell["centre"])
            phi = -math.radians(ell["rotation_deg"])
            for th in np.linspace(0.0, 2 * math.pi, 13):
                x = conic_point(Hm, th, rho)
                px, py = to_svg(x[:2] / x[2])
                dx, dy = px - cx, py - cy
                xp = math.cos(phi) * dx + math.sin(phi) * dy
                yp = -math.sin(phi) * dx + math.cos(phi) * dy
                assert abs((xp / ell["rx"]) ** 2 + (yp / ell["ry"]) ** 2 - 1.0) < 1e-6
            verified += 1
    assert verified > 0


def test_cli_renders_the_curved_example(tmp_path):
    from castplane.cli import main
    assert main(["render", str(EXAMPLES / "curved_demo.json"), "-o", str(tmp_path), "--formats", "svg,json"]) == 0
    doc = json.loads((tmp_path / "curved_demo.json").read_text(encoding="utf-8"))
    assert doc["outlines"] and all(s["conics"] for s in doc["shadows"])
    svg = (tmp_path / "curved_demo.svg").read_text(encoding="utf-8")
    assert "<ellipse" in svg and " A " in svg
