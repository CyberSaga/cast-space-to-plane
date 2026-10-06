"""M1 pipeline integration (spec §6, §10; contract §3): examples, JSON round trip, determinism, SVG layers
and the ray-cast IoU of the §6.2 shadow loops for polyhedral scenes."""

from __future__ import annotations

import copy
import json
import math
import pathlib
import re
import xml.dom.minidom

import numpy as np
import pytest

import castplane
from castplane.output.geometry_json import dumps
from castplane.output.svg import write_svg
from castplane.scene import load_scene
from tests.reference import random_scenes, raster, raycast

EXAMPLES = pathlib.Path(__file__).resolve().parents[1] / "examples"


def walk_numbers(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_numbers(v)
    elif isinstance(obj, float):
        yield obj


def polyhedral_scene(seed: int, n: int, light_type=None) -> dict:
    """Random scene restricted to box / prism objects (curved objects are M2)."""
    rng = np.random.default_rng(seed)
    objects = [random_scenes.random_object(rng, i, "box" if i % 2 else "prism") for i in range(n)]
    light = random_scenes.random_light(rng, objects, light_type)
    return random_scenes.assemble_scene(objects, light, random_scenes.random_camera(rng, objects))


def ground_loops(doc: dict):
    """World ``(x, y)`` polygons of every bounded §6.2 shadow loop (names resolved through ``points``)."""
    loops = []
    for sh in doc["shadows"]:
        for loop in sh["loops"]:
            if any(not isinstance(e, str) for e in loop):
                continue  # unbounded loop: direction entries
            pts = [doc["points"][name]["world"][:2] for name in loop]
            if len(pts) >= 3:
                loops.append(np.array(pts))
    return loops


@pytest.fixture(scope="module")
def basic():
    scene = load_scene(EXAMPLES / "basic.json")
    return scene, castplane.render(scene)


@pytest.fixture(scope="module")
def directional():
    scene = load_scene(EXAMPLES / "directional.json")
    return scene, castplane.render(scene)


def test_basic_example_shadows_construction_and_svg_subgroup(basic):
    scene, result = basic
    doc, svg = result["geometry"], result["svg"]
    assert '<g id="cast_shadow.lamp"' in svg
    assert re.search(r'<g id="cast_shadow"[^>]*fill-rule="nonzero"', svg)
    crate = [s for s in doc["shadows"] if s["object"] == "crate"]
    assert len(crate) == 1 and crate[0]["light"] == "lamp" and crate[0]["receiver"] == "ground"
    assert crate[0]["unbounded"] is False and crate[0]["conics"] == []
    assert crate[0]["outline"] == crate[0]["loops"][0] and len(crate[0]["outline"]) == 6
    assert all(name in doc["points"] for name in crate[0]["outline"])
    assert all(abs(doc["points"][n]["world"][2]) < 1e-12 for n in crate[0]["outline"])  # on the ground
    # the pillar (cylinder) keeps the M0 behaviour in M1: edges only, no shadow entry
    assert not any(s["object"] == "pillar" for s in doc["shadows"])
    con = doc["construction"]
    assert con["light_point"] is not None and con["shadow_vp"] is not None
    assert con["light_point_at_infinity"] is None and con["shadow_vp_at_infinity"] is None
    # L' lies above the horizon (light above eye height), F' below it (foot on the ground)
    assert con["light_point"][1] > doc["horizon"]["v_mm"] > con["shadow_vp"][1]
    assert con["rays"] and all(r[0] in ("L", "F") for r in con["rays"])
    assert {r[1] for r in con["rays"] if r[0] == "L"} == {"crate.v0", "crate.v3", "crate.v4", "crate.v5",
                                                           "crate.v6", "crate.v7"}
    assert all(r[1].endswith(".foot") for r in con["rays"] if r[0] == "F")
    assert con["checks"] and max(c["max_error_mm"] for c in con["checks"]) < 1e-6
    assert any(e["silhouette"] for e in doc["edges"] if e["object"] == "crate")
    assert sum(e["silhouette"] for e in doc["edges"] if e["object"] == "crate") == 6
    # construction markers and ray groups are present in the SVG
    assert ">L′<" in svg and ">F′<" in svg and '<circle' in svg and 'r="1"' in svg
    for kind in ("LP", "FQ", "PQ"):
        assert f'<g id="construction.{kind}"' in svg
    assert '<g id="form_shadow.crate"' in svg and "<polygon" in svg
    assert "L.lamp" in doc["points"] and "F.lamp" in doc["points"]
    assert doc["points"]["L.lamp"]["world"] == [0.0, 3.0, 3.5] and doc["points"]["F.lamp"]["world"] == [0.0, 3.0, 0.0]
    assert doc["warnings"] == []
    xml.dom.minidom.parseString(svg)


def test_directional_example(directional):
    scene, result = directional
    doc, svg = result["geometry"], result["svg"]
    assert '<g id="cast_shadow.sun"' in svg
    con = doc["construction"]
    # the sun is a direction: L' is its vanishing point, F' lies on the horizon
    assert doc["points"]["L.sun"]["at_infinity"] is True and doc["points"]["F.sun"]["at_infinity"] is True
    assert con["shadow_vp"] is not None
    hz = doc["horizon"]["line"]
    assert abs(hz[0] * con["shadow_vp"][0] + hz[1] * con["shadow_vp"][1] + hz[2]) < 1e-6
    # the sun direction has a negative y component: it is behind the viewer, so L' is the anti-solar point
    # below the horizon (spec §2 "反光點"; no LIGHT_BEHIND_CAMERA warning for a direction, contract §2.9)
    assert con["light_point"] is not None and con["light_point"][1] < doc["horizon"]["v_mm"]
    assert not any(w["code"] == "LIGHT_BEHIND_CAMERA" for w in doc["warnings"])
    for s in doc["shadows"]:
        assert s["light"] == "sun" and s["object"] in ("post", "crate")
        assert s["unbounded"] is False and s["polygons"] and len(s["polygons"][0]) >= 3
    assert len(doc["form_shadow"]) == 2
    assert con["checks"] and max(c["max_error_mm"] for c in con["checks"]) < 1e-6
    assert all(math.isfinite(x) for x in walk_numbers(doc))


def test_json_round_trip_and_determinism(basic):
    scene, result = basic
    text = dumps(result["geometry"])
    parsed = json.loads(text)
    assert dumps(parsed) == text
    assert parsed == result["geometry"]
    again = castplane.render(scene)
    assert dumps(again["geometry"]) == text          # byte-identical JSON
    assert again["svg"] == result["svg"]              # byte-identical SVG
    assert "NaN" not in text and "Infinity" not in text and not re.search(r"-0\.0(?![0-9])", text)
    for name, p in parsed["points"].items():
        if p.get("at_infinity"):
            assert set(p) == {"direction", "at_infinity", "image"}
        else:
            assert set(p) == {"world", "image", "depth"}


def test_construction_demo_example_renders_like_a_construction_drawing():
    scene = load_scene(EXAMPLES / "construction_demo.json")
    result = castplane.render(scene)
    doc, svg = result["geometry"], result["svg"]
    assert doc["warnings"] == []
    W, H = doc["canvas_mm"]
    con = doc["construction"]
    for p in (con["light_point"], con["shadow_vp"]):
        assert abs(p[0]) < W / 2 and abs(p[1]) < H / 2          # both markers on the canvas
    assert {s["object"] for s in doc["shadows"]} == {"crate", "block", "wedge"}
    assert all(not s["unbounded"] for s in doc["shadows"])
    assert len(con["segments"]) >= 3 * 10
    assert svg.count("<line") > 60
    assert ">L′<" in svg and ">F′<" in svg


def test_stage_b_caching_and_camera_independence_of_stage_a(basic):
    scene, _ = basic
    A = castplane.shadow_geometry(scene)
    assert "camera" not in A
    override = dict(scene["camera"], position=[3.0, -2.0, 2.5], target=[0.0, 5.0, 0.5])
    d1 = castplane.compose(scene, castplane.project_scene(scene, A))
    d2 = castplane.compose(scene, castplane.project_scene(scene, A, camera=override))
    for name in d1["points"]:
        if "world" in d1["points"][name]:
            assert d1["points"][name]["world"] == d2["points"][name]["world"]
    assert d1["shadows"][0]["outline"] == d2["shadows"][0]["outline"]
    assert d1["construction"]["light_point"] != d2["construction"]["light_point"]


@pytest.mark.parametrize("seed, n", [(1, 2), (2, 3), (3, 4), (5, 2)])
def test_shadow_loops_match_raycast_reference(seed, n):
    """§7.3 for M1: rasterise the §6.2 loops (world coordinates of the named points) vs the ray caster."""
    scene = polyhedral_scene(seed, n)
    doc = castplane.render(load_scene(scene))["geometry"]
    light = scene["lights"][0]
    assert all(not s["unbounded"] for s in doc["shadows"])
    xs, ys = random_scenes.sample_grid(scene, light, n=400)
    ref = raycast.shadow_mask(scene, light, xs, ys)
    got = raster.rasterize_polygons(ground_loops(doc), xs, ys)
    assert raster.iou(got, ref) >= 0.99


def test_box_plus_prism_scene_iou():
    scene = random_scenes.assemble_scene(
        [{"id": "crate", "type": "box", "size": [1.0, 0.8, 0.6],
          "transform": {"position": [0.5, 0.0, 0.0], "rotation_deg": [0, 0, 30]}},
         {"id": "u", "type": "prism", "polygon": random_scenes.u_polygon(2.0, 0.6, 1.5), "height": 1.0,
          "transform": {"position": [-2.0, 1.0, 0.0], "rotation_deg": [0, 0, 15]}}],
        {"id": "lamp", "type": "point", "position": [1.5, -3.0, 3.0]},
        {"position": [4.0, -6.0, 3.0], "target": [0.0, 0.0, 0.5], "roll_deg": 0.0, "focal_length_mm": 30.0,
         "frame_mm": [36.0, 24.0], "shift_mm": [0.0, 0.0], "near_m": 0.05})
    doc = castplane.render(load_scene(scene))["geometry"]
    light = scene["lights"][0]
    xs, ys = random_scenes.sample_grid(scene, light, n=500)
    ref = raycast.shadow_mask(scene, light, xs, ys)
    got = raster.rasterize_polygons(ground_loops(doc), xs, ys)
    assert raster.iou(got, ref) >= 0.99
    assert any(s["object"] == "u" and len(s["loops"]) >= 1 for s in doc["shadows"])


def test_svg_layer_subset_only_draws_requested_layers(basic):
    scene, result = basic
    doc = result["geometry"]
    svg = write_svg(doc, layers=["cast_shadow"])
    assert re.findall(r'<g id="([a-z_]+)"', svg) == ["cast_shadow"]
    assert '<g id="cast_shadow.lamp"' in svg
    svg = write_svg(doc, layers=["construction"])
    assert "L′" in svg and 'stroke="#d33"' in svg and 'stroke="#36c"' in svg and 'stroke="#3a3"' in svg


def test_drawn_shadow_polygon_matches_point_images(basic):
    """A bounded, fully visible shadow polygon is drawn exactly through the images of its named points."""
    scene, result = basic
    doc = result["geometry"]
    sh = [s for s in doc["shadows"] if s["object"] == "crate"][0]
    expected = [doc["points"][n]["image"] for n in sh["outline"]]
    np.testing.assert_allclose(sh["polygons"][0], expected, atol=1e-9)


def test_cli_render_writes_construction_layers(tmp_path):
    from castplane.cli import main
    assert main(["render", str(EXAMPLES / "construction_demo.json"), "-o", str(tmp_path)]) == 0
    svg = (tmp_path / "construction_demo.svg").read_text(encoding="utf-8")
    assert '<g id="construction.LP"' in svg
    doc = json.loads((tmp_path / "construction_demo.json").read_text(encoding="utf-8"))
    assert doc["construction"]["rays"]
