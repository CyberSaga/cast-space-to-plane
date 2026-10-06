"""Validation table of contract §2.0: one test per rule, plus defaults and loading."""

import copy
import json
import pathlib

import pytest

from castplane.errors import SceneError
from castplane.scene import LAYER_IDS, load_scene, polygon_is_simple, validate_scene

EXAMPLES = pathlib.Path(__file__).resolve().parents[1] / "examples"


def base_scene():
    with open(EXAMPLES / "basic.json", encoding="utf-8") as fh:
        return json.load(fh)


def mutate(path, value, delete=False):
    """Return the §4 scene with ``path`` (list of keys / indices) set to ``value`` or deleted."""
    scene = base_scene()
    node = scene
    for key in path[:-1]:
        node = node[key]
    if delete:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return scene


def expect_error(scene, field):
    with pytest.raises(SceneError) as info:
        validate_scene(scene)
    assert info.value.field == field, (info.value.field, info.value.message)
    assert field in str(info.value)


# --- top level ---------------------------------------------------------------

def test_valid_example_loads_from_path():
    scene = load_scene(EXAMPLES / "basic.json")
    assert scene["objects"][0]["id"] == "crate"
    assert scene["camera"]["near_m"] == 0.05


def test_version_must_be_0_1():
    expect_error(mutate(["version"], "0.2"), "version")
    expect_error(mutate(["version"], None, delete=True), "version")


def test_units_and_up():
    expect_error(mutate(["units"], "cm"), "units")
    expect_error(mutate(["up"], "y"), "up")
    scene = mutate(["units"], None, delete=True)
    del scene["up"]
    out = validate_scene(scene)
    assert out["units"] == "m" and out["up"] == "z"


def test_unknown_keys_ignored_and_input_not_mutated():
    scene = base_scene()
    scene["comment"] = "ignored"
    scene["objects"][0]["colour"] = "red"
    before = copy.deepcopy(scene)
    out = validate_scene(scene)
    assert "comment" not in out and "colour" not in out["objects"][0]
    assert scene == before


# --- objects -----------------------------------------------------------------

def test_objects_non_empty_list():
    expect_error(mutate(["objects"], []), "objects")
    expect_error(mutate(["objects"], {"id": "x"}), "objects")


def test_object_ids_unique_non_empty_without_dot():
    expect_error(mutate(["objects", 1, "id"], "crate"), "objects[1].id")
    expect_error(mutate(["objects", 0, "id"], ""), "objects[0].id")
    expect_error(mutate(["objects", 0, "id"], "a.b"), "objects[0].id")
    expect_error(mutate(["objects", 0, "id"], 3), "objects[0].id")


def test_object_type():
    expect_error(mutate(["objects", 0, "type"], "torus"), "objects[0].type")
    expect_error(mutate(["objects", 0, "type"], None, delete=True), "objects[0].type")


def test_box_size_three_positive():
    expect_error(mutate(["objects", 0, "size"], [1.0, 0.8]), "objects[0].size")
    expect_error(mutate(["objects", 0, "size"], [1.0, 0.0, 0.6]), "objects[0].size[1]")
    expect_error(mutate(["objects", 0, "size"], [1.0, -1, 0.6]), "objects[0].size[1]")
    expect_error(mutate(["objects", 0, "size"], None, delete=True), "objects[0].size")


def test_radius_height_positive():
    expect_error(mutate(["objects", 1, "radius"], 0), "objects[1].radius")
    expect_error(mutate(["objects", 1, "height"], -2), "objects[1].height")
    expect_error(mutate(["objects", 1, "height"], None, delete=True), "objects[1].height")
    expect_error(mutate(["objects", 1, "radius"], float("nan")), "objects[1].radius")
    scene = mutate(["objects", 1], {"id": "s", "type": "sphere", "radius": 0.5})
    assert validate_scene(scene)["objects"][1]["radius"] == 0.5
    scene = mutate(["objects", 1], {"id": "s", "type": "sphere"})
    expect_error(scene, "objects[1].radius")
    scene = mutate(["objects", 1], {"id": "c", "type": "cone", "radius": 0.5})
    expect_error(scene, "objects[1].height")


def test_prism_polygon_rules():
    def prism(poly):
        return mutate(["objects", 1], {"id": "p", "type": "prism", "polygon": poly, "height": 1.0})

    expect_error(prism([[0, 0], [1, 0]]), "objects[1].polygon")
    expect_error(prism([[0, 0], [1, 1], [2, 2]]), "objects[1].polygon")           # collinear
    expect_error(prism([[0, 0], [1, 1], [1, 0], [0, 1]]), "objects[1].polygon")   # bow-tie
    with pytest.raises(SceneError) as info:   # a symmetric bow-tie has zero signed area: the message must not
        validate_scene(prism([[0, 0], [1, 1], [1, 0], [0, 1]]))                   # call it "collinear" only
    assert "self-intersecting" in info.value.message and "collinear" in info.value.message
    with pytest.raises(SceneError) as info:
        validate_scene(prism([[0, 0], [2, 0], [2, 2], [0, 2], [2, 1]]))            # non-zero-area bow-tie
    assert info.value.message == "polygon is self-intersecting"
    expect_error(prism([[0, 0], [1, 0], [1, 0], [0, 1]]), "objects[1].polygon[1]")  # repeated vertex
    expect_error(prism([[0, 0], [1, 0, 0], [0, 1]]), "objects[1].polygon[1]")
    ccw = validate_scene(prism([[0, 0], [1, 0], [0, 1]]))["objects"][1]["polygon"]
    cw = validate_scene(prism([[0, 0], [0, 1], [1, 0]]))["objects"][1]["polygon"]
    assert ccw == [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    assert cw == [[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]  # clockwise input reversed silently
    assert validate_scene(prism([[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]]))  # concave L is fine


def test_prism_simplicity_tolerances_are_dimensionally_consistent():
    """The orientation tolerance is an area (1e-12·extent²), the collinear bounding-box tolerance a length
    (1e-12·extent); mixing them makes the verdict depend on the unit of the polygon (contract §2.0, §2.8)."""
    def prism(poly):
        return mutate(["objects", 1], {"id": "p", "type": "prism", "polygon": poly, "height": 1.0})

    # simple polygon with a 1e-7 m spur beyond v0 on the line of edge v0v1 (extent 500 m): the vertex is
    # 1e-7 m outside the edge's bounding box, far more than the length tolerance 5e-10 m, so it must load
    spur = [[0.0, 0.0], [500.0, 0.0], [500.0, 500.0], [-1e-7, 0.0]]
    assert validate_scene(prism(spur))["objects"][1]["polygon"] == spur
    # a vertex exactly on a non-adjacent edge (T-touch) is a self-intersection at every scale
    touch = [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [2.0, 0.0], [0.0, 4.0]]
    bowtie = [[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0]]
    for k in (1e-3, 1.0, 1e3):
        for poly, simple in ((spur, True), (touch, False), (bowtie, False)):
            scaled = [[k * x, k * y] for x, y in poly]
            extent = max(abs(c) for p in scaled for c in p)
            assert polygon_is_simple(scaled, 1e-12 * extent * extent, 1e-12 * extent) is simple, (k, poly)
            if simple:
                assert validate_scene(prism(scaled))
            else:
                expect_error(prism(scaled), "objects[1].polygon")


def test_transform_rules():
    expect_error(mutate(["objects", 0, "transform", "scale"], [1, 1, 1]), "objects[0].transform.scale")
    expect_error(mutate(["objects", 0, "transform", "position"], [1, 2]), "objects[0].transform.position")
    expect_error(mutate(["objects", 0, "transform", "rotation_deg"], "x"), "objects[0].transform.rotation_deg")
    expect_error(mutate(["objects", 0, "transform"], 5), "objects[0].transform")
    out = validate_scene(mutate(["objects", 0, "transform"], None, delete=True))
    assert out["objects"][0]["transform"] == {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]}
    out = validate_scene(mutate(["objects", 0, "transform"], {"position": [1, 2, 3]}))
    assert out["objects"][0]["transform"]["rotation_deg"] == [0.0, 0.0, 0.0]


# --- lights ------------------------------------------------------------------

def test_lights_exactly_one():
    expect_error(mutate(["lights"], []), "lights")
    scene = base_scene()
    scene["lights"].append({"id": "l2", "type": "point", "position": [0, 0, 1]})
    expect_error(scene, "lights")


def test_light_type_and_params():
    expect_error(mutate(["lights", 0, "type"], "spot"), "lights[0].type")
    expect_error(mutate(["lights", 0, "position"], None, delete=True), "lights[0].position")
    expect_error(mutate(["lights", 0, "id"], None, delete=True), "lights[0].id")
    expect_error(mutate(["lights", 0, "id"], "a.b"), "lights[0].id")   # "." is the point-name separator (§3.1)
    expect_error(mutate(["lights", 0, "id"], ""), "lights[0].id")
    scene = mutate(["lights", 0], {"id": "sun", "type": "directional", "direction": [0, 0, 2]})
    expect_error(scene, "lights[0].direction")
    scene = mutate(["lights", 0], {"id": "sun", "type": "directional"})
    expect_error(scene, "lights[0].direction")
    scene = mutate(["lights", 0], {"id": "sun", "type": "directional", "direction": [0.6, 0.0, 0.8]})
    assert validate_scene(scene)["lights"][0]["direction"] == [0.6, 0.0, 0.8]


# --- receivers ---------------------------------------------------------------

def test_receivers_rules():
    expect_error(mutate(["receivers"], []), "receivers")
    expect_error(mutate(["receivers", 0, "type"], "sphere"), "receivers[0].type")
    expect_error(mutate(["receivers", 0, "normal"], [0, 1, 0]), "receivers[0].normal")
    expect_error(mutate(["receivers", 0, "normal"], [0, 0, 2]), "receivers[0].normal")
    expect_error(mutate(["receivers", 0, "offset"], 0.5), "receivers[0].offset")
    out = validate_scene(mutate(["receivers", 0, "offset"], None, delete=True))
    assert out["receivers"][0]["offset"] == 0.0


# --- camera ------------------------------------------------------------------

def test_camera_pose_forms():
    expect_error(mutate(["camera", "position"], [0, 0]), "camera.position")
    expect_error(mutate(["camera", "target"], None, delete=True), "camera")
    expect_error(mutate(["camera", "yaw_deg"], 10.0), "camera")                  # both forms
    expect_error(mutate(["camera", "target"], [0.0, 0.0, 1.5]), "camera.target")  # == position
    scene = mutate(["camera", "target"], None, delete=True)
    scene["camera"]["yaw_deg"] = 10.0
    expect_error(scene, "camera")                                                # pitch missing
    scene["camera"]["pitch_deg"] = -5.0
    out = validate_scene(scene)
    assert out["camera"]["yaw_deg"] == 10.0 and "target" not in out["camera"]


def test_camera_lens_rules_and_defaults():
    expect_error(mutate(["camera", "focal_length_mm"], 0), "camera.focal_length_mm")
    expect_error(mutate(["camera", "frame_mm"], [36, 0]), "camera.frame_mm[1]")
    expect_error(mutate(["camera", "frame_mm"], None, delete=True), "camera.frame_mm")
    expect_error(mutate(["camera", "near_m"], -0.1), "camera.near_m")
    expect_error(mutate(["camera", "shift_mm"], [1]), "camera.shift_mm")
    expect_error(mutate(["camera", "roll_deg"], "0"), "camera.roll_deg")
    scene = base_scene()
    for key in ("roll_deg", "shift_mm", "near_m"):
        del scene["camera"][key]
    cam = validate_scene(scene)["camera"]
    assert cam["roll_deg"] == 0.0 and cam["shift_mm"] == [0.0, 0.0] and cam["near_m"] == 0.05


# --- output ------------------------------------------------------------------

def test_output_canvas_aspect_and_defaults():
    expect_error(mutate(["output", "canvas_mm"], [257, 182]), "output.canvas_mm")
    expect_error(mutate(["output", "canvas_mm"], [0, 1]), "output.canvas_mm[0]")
    expect_error(mutate(["output", "canvas_mm"], None, delete=True), "output.canvas_mm")
    expect_error(mutate(["output"], None, delete=True), "output")
    expect_error(mutate(["output", "layers"], ["horizon", "shadows"]), "output.layers[1]")
    expect_error(mutate(["output", "layers"], []), "output.layers")                 # empty subset rejected
    expect_error(mutate(["output", "layers"], ["horizon", "horizon"]), "output.layers")
    with pytest.raises(SceneError) as info:   # the spec's own §4 example: the message names both ratios and a fix
        validate_scene(mutate(["output", "canvas_mm"], [257, 182]))
    assert "257/182 = 1.412" in info.value.message and "36/24 = 1.5" in info.value.message
    assert "[273, 182]" in info.value.message
    expect_error(mutate(["output", "png_dpi"], 0), "output.png_dpi")
    scene = base_scene()
    del scene["output"]["layers"]
    del scene["output"]["png_dpi"]
    out = validate_scene(scene)["output"]
    assert out["layers"] == list(LAYER_IDS) and out["png_dpi"] == 300
    out = validate_scene(mutate(["output", "layers"], ["labels", "horizon"]))["output"]
    assert out["layers"] == ["horizon", "labels"]  # table order preserved
    assert validate_scene(mutate(["output", "canvas_mm"], [36, 24]))["output"]["canvas_mm"] == [36.0, 24.0]


def test_invalid_json_file_reports_scene_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SceneError):
        load_scene(path)
