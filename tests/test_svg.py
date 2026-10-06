"""Smoke tests: pipeline -> §6.2 JSON + §6.1 SVG (contract §2.10, §3.1), PNG and CLI."""

import copy
import json
import math
import pathlib
import re
import warnings
import xml.dom.minidom

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import castplane
from castplane.cli import main
from castplane.errors import WARNING_CODES
from castplane.output.geometry_json import dumps
from castplane.output.svg import LAYER_ORDER, write_svg
from castplane.scene import load_scene

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


@pytest.fixture(scope="module")
def basic():
    scene = load_scene(EXAMPLES / "basic.json")
    return scene, castplane.render(scene)


def test_render_basic_has_six_layers_in_order_and_finite_json(basic):
    scene, result = basic
    doc, svg = result["geometry"], result["svg"]
    ids = re.findall(r'<g id="([a-z_]+)"', svg)
    assert [i for i in ids if i in LAYER_ORDER] == list(LAYER_ORDER)
    text = dumps(doc)
    assert "NaN" not in text and "Infinity" not in text
    assert not re.search(r"-0\.0(?![0-9])", text)  # no negative zero
    assert all(math.isfinite(x) for x in walk_numbers(doc))
    assert set(doc) == {"canvas_mm", "camera", "points", "edges", "shadows", "form_shadow", "construction",
                        "horizon", "warnings"}
    assert doc["shadows"] == [] and doc["form_shadow"] == []
    assert doc["construction"]["light_point"] is None and doc["construction"]["rays"] == []
    assert doc["warnings"] == []
    assert doc["canvas_mm"] == [273.0, 182.0]
    assert len(doc["camera"]["P"]) == 3 and len(doc["camera"]["P"][0]) == 4
    assert doc["horizon"]["v_mm"] == pytest.approx(35 * 273 / 36 * 0.1, rel=1e-9)  # f·s·tan(pitch)


def test_json_is_deterministic_and_sorted(basic):
    scene, _ = basic
    a = dumps(castplane.render(scene)["geometry"])
    b = dumps(castplane.render(scene)["geometry"])
    assert a == b
    parsed = json.loads(a)
    assert list(parsed) == sorted(parsed)
    assert a.startswith("{\n \"camera\"")  # indent=1, sort_keys


def test_points_and_edges_shape(basic):
    scene, result = basic
    doc = result["geometry"]
    p = doc["points"]["crate.v0"]
    assert set(p) == {"world", "image", "depth"} and len(p["image"]) == 2
    e = doc["edges"][0]
    assert e["object"] == "crate" and e["from"] == "crate.v0" and e["silhouette"] is False
    assert e["visibility"] == "visible" and e["segment"] is not None
    # back flag with camera as light: the crate's bottom-face-only edges are back, top edges are front
    back = {(e["from"], e["to"]) for e in doc["edges"] if e["object"] == "crate" and e["back"]}
    assert any(a.endswith(".v0") or a.endswith(".v1") for a, _ in back)
    assert all(not (a.endswith(".v4") and b.endswith(".v5")) for a, b in back)
    assert sum(1 for e in doc["edges"] if e["object"] == "crate") == 12
    assert sum(1 for e in doc["edges"] if e["object"] == "crate" and e["back"]) == 3  # 3 hidden edges of a box


def test_svg_mapping_and_styles(basic):
    scene, result = basic
    svg = result["svg"]
    assert 'width="273mm" height="182mm"' in svg and 'viewBox="0 0 273 182"' in svg
    assert '<circle cx="136.5" cy="91" r="0.6"' in svg  # principal point at (W/2, H/2)
    assert 'stroke-dasharray="1.2 0.8"' in svg and 'stroke="#111" stroke-width="0.3"' in svg
    assert '<g id="cast_shadow" fill="#000" fill-opacity="0.3"' in svg
    assert '<g id="form_shadow" fill="#335"' in svg
    assert ">VPy<" in svg and ">v0<" in svg and ">crate<" in svg
    assert '<g id="construction" stroke-width="0.15" fill="none"/>' in svg  # empty layer still emitted


def test_write_svg_layer_subset_and_errors(basic):
    scene, result = basic
    doc = result["geometry"]
    svg = write_svg(doc, layers=["labels", "objects"])
    ids = re.findall(r'<g id="([a-z_]+)"', svg)
    assert [i for i in ids if i in LAYER_ORDER] == ["objects", "labels"]
    assert "horizon" not in ids
    with pytest.raises(ValueError):
        write_svg(doc, layers=["objects", "shadows"])
    svg_sub = castplane.render(dict(scene, output=dict(scene["output"], layers=["horizon"])))["svg"]
    assert re.findall(r'<g id="([a-z_]+)"', svg_sub) == ["horizon"]


def test_points_behind_camera_are_null_and_edges_clipped():
    scene = load_scene(EXAMPLES / "basic.json")
    scene = copy.deepcopy(scene)
    scene["camera"]["position"] = [2.0, 4.0, 0.3]  # inside the crate
    scene["camera"]["target"] = [2.0, 9.0, 0.3]
    doc = castplane.render(scene)["geometry"]
    assert any(w["code"] == "POINT_BEHIND_CAMERA" and w["ids"] == ["crate"] for w in doc["warnings"])
    behind = [n for n, p in doc["points"].items() if p["image"] is None]
    assert behind and all(doc["points"][n]["depth"] < 0.05 for n in behind)
    crate_edges = [e for e in doc["edges"] if e["object"] == "crate"]
    assert any(e["segment"] is None for e in crate_edges)           # fully behind: dropped
    crossing = [e for e in crate_edges if e["segment"] is not None
                and (doc["points"][e["from"]]["image"] is None) != (doc["points"][e["to"]]["image"] is None)]
    assert crossing  # edges crossing the near plane are clipped, not dropped
    assert all(math.isfinite(x) for x in walk_numbers(doc))
    svg = castplane.render(scene)["svg"]
    assert "nan" not in svg.lower() and "inf" not in svg.lower().replace("infinity", "")


def _rect(doc):
    """Extended canvas rectangle ``(u_min, u_max, v_min, v_max)`` of contract §2.2 step 3 (25 % margin)."""
    W, H = doc["canvas_mm"]
    return (-0.75 * W, 0.75 * W, -0.75 * H, 0.75 * H)


def _inside(p, rect, slack=1e-9):
    return rect[0] - slack <= p[0] <= rect[1] + slack and rect[2] - slack <= p[1] <= rect[3] + slack


def test_segment_endpoints_equal_point_images(basic):
    """Drawing-pipeline invariant (contract §2.2): a fully visible edge inside the extended canvas is drawn
    exactly between the images of its vertices (``segment[0]`` <-> ``from``, ``segment[1]`` <-> ``to``)."""
    scene, result = basic
    doc = result["geometry"]
    rect = _rect(doc)
    checked = 0
    for e in doc["edges"]:
        a, b = doc["points"][e["from"]]["image"], doc["points"][e["to"]]["image"]
        assert a is not None and b is not None and e["segment"] is not None  # basic.json: all in front
        if _inside(a, rect) and _inside(b, rect):
            np.testing.assert_allclose(e["segment"], [a, b], atol=1e-12)
            checked += 1
    assert checked == len(doc["edges"]) == 12 + 32 * 3  # box + 32-gon cylinder, all inside the canvas


def test_rect_clipped_segment_ends_on_rect_boundary_and_on_the_edge_line():
    """An edge with one image outside the extended canvas keeps the inside endpoint exactly and replaces the
    other by the crossing with the rectangle boundary (homogeneous clip, contract §2.2 step 3)."""
    scene = copy.deepcopy(load_scene(EXAMPLES / "basic.json"))
    scene["camera"]["focal_length_mm"] = 80.0  # longer lens: many vertices leave the extended canvas
    doc = castplane.render(scene)["geometry"]
    rect = _rect(doc)
    partial = 0
    for e in doc["edges"]:
        a, b = doc["points"][e["from"]]["image"], doc["points"][e["to"]]["image"]
        assert a is not None and b is not None
        ia, ib = _inside(a, rect), _inside(b, rect)
        if ia and ib:
            np.testing.assert_allclose(e["segment"], [a, b], atol=1e-12)
        elif not ia and not ib:
            if e["segment"] is not None:  # crosses the canvas: both ends on the boundary, on the edge line
                for q in map(np.array, e["segment"]):
                    assert _inside(q, rect, 1e-9)
                    a_, b_ = np.array(a), np.array(b)
                    d = b_ - a_
                    np.testing.assert_allclose(a_ + float((q - a_) @ d / (d @ d)) * d, q, atol=1e-9)
        else:
            assert e["segment"] is not None
            partial += 1
            kept, clipped = (0, 1) if ia else (1, 0)
            np.testing.assert_allclose(e["segment"][kept], a if ia else b, atol=1e-12)
            q = np.array(e["segment"][clipped])
            assert _inside(q, rect, 1e-9)
            assert min(abs(q[0] - rect[0]), abs(q[0] - rect[1]), abs(q[1] - rect[2]), abs(q[1] - rect[3])) < 1e-9
            # q lies on the line through a and b, between them
            a_, b_ = np.array(a), np.array(b)
            d = b_ - a_
            t = float((q - a_) @ d / (d @ d))
            assert -1e-9 <= t <= 1 + 1e-9
            np.testing.assert_allclose(a_ + t * d, q, atol=1e-9)
    assert partial > 0
    # both ends outside but crossing the canvas: kept, both ends on the boundary (also with a direction end)
    from castplane.camera import clip_segments_rect_h, divide
    A = np.array([[-1000.0, -50.0, 1.0], [-1000.0, 0.0, 2.0]])
    B = np.array([[1000.0, 50.0, 1.0], [1.0, 0.0, 0.0]])
    a2, b2, keep = clip_segments_rect_h(A, B, rect)
    assert keep.all()
    np.testing.assert_allclose(divide(a2), [[rect[0], -10.2375], [rect[0], 0.0]], atol=1e-9)
    np.testing.assert_allclose(divide(b2), [[rect[1], 10.2375], [rect[1], 0.0]], atol=1e-9)


def test_near_clipped_endpoint_lies_exactly_on_the_near_plane():
    """Near clipping (contract §2.2 step 1) is exact: the clipped endpoint of an edge crossing the near plane
    is the image of the 4-D crossing point, whose depth equals ``near_m``; the visible endpoint keeps its image."""
    scene = copy.deepcopy(load_scene(EXAMPLES / "basic.json"))
    scene["objects"][0]["transform"]["rotation_deg"] = [0, 0, 0]   # crate spans y in [3.6, 4.4]
    scene["camera"]["position"] = [2.0, 3.0, 0.3]
    scene["camera"]["target"] = [2.0, 9.0, 0.3]
    scene["camera"]["near_m"] = 1.0                                   # near plane at y = 4.0, inside the crate
    A = castplane.shadow_geometry(scene)
    B = castplane.project_scene(scene, A)
    doc = castplane.compose(scene, B)
    P = np.array(doc["camera"]["P"])
    near = scene["camera"]["near_m"]
    rect = _rect(doc)
    crate = [k for k, o in enumerate(B["objects"]) if o["id"] == "crate"][0]
    rec = B["objects"][crate]
    crossing = 0
    for idx, e in enumerate(x for x in doc["edges"] if x["object"] == "crate"):
        pa, pb = doc["points"][e["from"]], doc["points"][e["to"]]
        if (pa["image"] is None) == (pb["image"] is None):
            continue
        crossing += 1
        assert e["segment"] is not None
        vis, hid = (0, 1) if pa["image"] is not None else (1, 0)
        X = [np.array(pa["world"] + [1.0]), np.array(pb["world"] + [1.0])]
        # ν(X) = x̃3 − near·w with x̃3 = P[2]·X (contract §2.2)
        nu = [float(P[2] @ X[0]) - near, float(P[2] @ X[1]) - near]
        assert nu[vis] > 0 > nu[hid]
        t = nu[0] / (nu[0] - nu[1])
        Xc = X[0] + t * (X[1] - X[0])
        xc = P @ Xc
        assert abs(xc[2] - near) < 1e-12                     # crossing point sits on the near plane
        img_c = [xc[0] / xc[2], xc[1] / xc[2]]
        img_v = pa["image"] if vis == 0 else pb["image"]
        assert _inside(img_c, rect) and _inside(img_v, rect)  # chosen so the rectangle clip is a no-op
        np.testing.assert_allclose(e["segment"][vis], img_v, atol=1e-12)
        np.testing.assert_allclose(e["segment"][hid], img_c, atol=1e-12)
        # stage B: the clipped homogeneous endpoint has x̃3 == near and the kept one the vertex's depth
        seg_h = rec["segments_h"][idx]
        assert rec["segment_keep"][idx]
        assert abs(seg_h[hid][2] - near) < 1e-12
        assert abs(seg_h[vis][2] - (pa if vis == 0 else pb)["depth"]) < 1e-12
    assert crossing == 4  # the four crate edges running along y cross the near plane


def test_object_id_with_xml_special_characters_gives_well_formed_svg():
    """Ids may contain any character except '.' (contract §2.0); attribute values must be quote-escaped."""
    raw = json.loads((EXAMPLES / "basic.json").read_text(encoding="utf-8"))
    raw["objects"][0]["id"] = 'cr"ate<&>'
    raw["lights"][0]["id"] = 'la"mp'
    result = castplane.render(load_scene(raw))
    svg = result["svg"]
    dom = xml.dom.minidom.parseString(svg)  # raises on malformed XML
    ids = {g.getAttribute("id") for g in dom.getElementsByTagName("g")}
    assert 'objects.cr"ate<&>' in ids and 'objects.cr"ate<&>.front' in ids
    assert '<g id="objects.cr&quot;ate&lt;&amp;&gt;"' in svg
    assert any(e["object"] == 'cr"ate<&>' for e in result["geometry"]["edges"])


SCENE_FOR_FUZZ = load_scene(EXAMPLES / "basic.json")
_special = st.sampled_from


@settings(max_examples=120, deadline=None)
@given(
    pos=st.tuples(st.floats(-6, 6), st.floats(-2, 10), st.floats(-1, 6)),   # includes inside the crate / pillar
    pitch=st.one_of(_special([-90.0, 90.0, -89.999, 89.999, 0.0]), st.floats(-90, 90)),
    yaw=st.floats(-360, 360),
    roll=st.one_of(_special([-180.0, 180.0, 90.0]), st.floats(-180, 180)),
    f=st.one_of(_special([8.0, 35.0, 200.0, 5000.0]), st.floats(1, 5000)),
    near=st.one_of(_special([1e-6, 0.05, 3.0]), st.floats(1e-6, 3)),
    shift=st.tuples(st.floats(-20, 20), st.floats(-20, 20)),
    target_form=st.booleans(),
)
def test_any_camera_renders_finite_json_and_svg_without_warnings_or_errors(pos, pitch, yaw, roll, f, near,
                                                                          shift, target_form):
    """M0 acceptance (spec §10): any camera parameters never raise, through the full pipeline
    (stage A -> B -> C -> SVG) under numpy warnings-as-errors, with finite output only."""
    cam = {"position": list(pos), "roll_deg": roll, "focal_length_mm": f, "frame_mm": [36, 24],
           "shift_mm": list(shift), "near_m": near}
    if target_form:
        fwd = [-math.sin(math.radians(yaw)) * math.cos(math.radians(pitch)),
               math.cos(math.radians(yaw)) * math.cos(math.radians(pitch)), math.sin(math.radians(pitch))]
        cam["target"] = [p + 3.0 * d for p, d in zip(pos, fwd)]
    else:
        cam["yaw_deg"], cam["pitch_deg"] = yaw, pitch
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = castplane.render(SCENE_FOR_FUZZ, camera=cam)
    doc, svg = result["geometry"], result["svg"]
    assert all(math.isfinite(x) for x in walk_numbers(doc))
    for p in doc["points"].values():
        assert p["image"] is None or (len(p["image"]) == 2 and all(math.isfinite(x) for x in p["image"]))
    for e in doc["edges"]:
        assert e["segment"] is None or np.asarray(e["segment"], dtype=float).shape == (2, 2)
    assert {w["code"] for w in doc["warnings"]} <= set(WARNING_CODES)
    assert all(isinstance(w["ids"], list) and all(isinstance(i, str) for i in w["ids"]) for w in doc["warnings"])
    low = svg.lower().replace("infinity", "")
    assert "nan" not in low and "inf" not in low
    text = dumps(doc)
    assert "NaN" not in text and "Infinity" not in text
    xml.dom.minidom.parseString(svg)


def test_camera_override_and_stage_caching():
    scene = load_scene(EXAMPLES / "basic.json")
    A = castplane.shadow_geometry(scene)
    B1 = castplane.project_scene(scene, A)
    override = dict(scene["camera"], position=[0.0, 0.0, 3.0], target=[0.0, 5.0, 0.0])
    B2 = castplane.project_scene(scene, A, camera=override)
    d1, d2 = castplane.compose(scene, B1), castplane.compose(scene, B2)
    assert d1["points"]["crate.v0"]["world"] == d2["points"]["crate.v0"]["world"]
    assert d1["points"]["crate.v0"]["image"] != d2["points"]["crate.v0"]["image"]
    assert d2["horizon"]["v_mm"] > d1["horizon"]["v_mm"]
    with pytest.raises(castplane.SceneError):
        castplane.project_scene(scene, A, camera=dict(override, frame_mm=[36, 36]))


def test_three_point_and_directional_examples_render():
    for name in ("three_point.json", "directional.json"):
        doc = castplane.render(load_scene(EXAMPLES / name))["geometry"]
        assert all(math.isfinite(x) for x in walk_numbers(doc))
    doc = castplane.render(load_scene(EXAMPLES / "three_point.json"))["geometry"]
    vpz = doc["horizon"]["vanishing_points"]["z"]
    assert vpz is not None and vpz[1] < doc["horizon"]["v_mm"]


def test_png_output(basic):
    scene, result = basic
    pytest.importorskip("cairosvg")
    from castplane.output.png import png_size, write_png
    png = write_png(result["svg"], dpi=50)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert png_size(result["svg"], 300) == (3224, 2150)


def test_cli_render_validate_stages_info_and_error_exit_code(tmp_path, capsys):
    assert main(["validate", str(EXAMPLES / "basic.json")]) == 0
    assert main(["info", str(EXAMPLES / "basic.json")]) == 0
    out = capsys.readouterr().out
    assert "horizon v_mm" in out and "vanishing point z" in out
    assert main(["render", str(EXAMPLES / "basic.json"), "-o", str(tmp_path), "--formats", "svg,json",
                 "--layers", "objects,horizon"]) == 0
    assert (tmp_path / "basic.svg").exists() and (tmp_path / "basic.json").exists()
    assert not (tmp_path / "basic.png").exists()
    svg = (tmp_path / "basic.svg").read_text(encoding="utf-8")
    assert re.findall(r'<g id="([a-z_]+)"', svg) == ["horizon", "objects"]
    cam = tmp_path / "cam.json"
    cam.write_text(json.dumps({"position": [0, 0, 3], "target": [0, 5, 0], "focal_length_mm": 50,
                               "frame_mm": [36, 24]}), encoding="utf-8")
    assert main(["render", str(EXAMPLES / "basic.json"), "-o", str(tmp_path), "--camera", str(cam)]) == 0
    stages = tmp_path / "stages.json"
    assert main(["stages", str(EXAMPLES / "basic.json"), "--camera", str(cam), "-o", str(stages)]) == 0
    st_doc = json.loads(stages.read_text(encoding="utf-8"))
    assert set(st_doc) == {"A", "B"}
    assert [o["id"] for o in st_doc["A"]["objects"]] == ["crate", "pillar"]
    assert len(st_doc["B"]["camera"]["P"]) == 3 and "segments_h" in st_doc["B"]["objects"][0]
    capsys.readouterr()
    assert main(["stages", str(EXAMPLES / "basic.json")]) == 0
    assert json.loads(capsys.readouterr().out)["B"]["scene_scale"] >= 1.0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(dict(json.loads((EXAMPLES / "basic.json").read_text()), lights=[])), encoding="utf-8")
    assert main(["validate", str(bad)]) == 2
    err = capsys.readouterr().err
    assert "error: lights:" in err
