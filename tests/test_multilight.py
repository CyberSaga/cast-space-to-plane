"""Multiple lights (contract §5.3, M6).

This first block holds the unit tests of the assembly helpers of ``castplane.multilight``
(§5.3.2 / §5.3.3 / §5.3.5); the end-to-end acceptance case and the document / SVG tests of
§5.3.10 are appended below it once the pipeline hooks exist."""

import copy
import json
import pathlib

import numpy as np
import pytest

from castplane import multilight as ML
from castplane.pipeline import _light_record, _object_light_data, compose, project_scene, shadow_geometry
from castplane.primitives import build_object
from castplane.scene import load_scene, validate_object

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
GROUND = np.array([0.0, 0.0, 1.0, 0.0])

# the acceptance case of §5.3.10: unit cube, two symmetric point lights
WEST = {"id": "west", "type": "point", "position": [-2.0, 0.0, 2.0]}
EAST = {"id": "east", "type": "point", "position": [2.0, 0.0, 2.0]}
LIGHT_IDS = ["west", "east"]
#: box faces (castplane.primitives): 0 base, 1 top, 2 -y, 3 +x, 4 +y, 5 -x
BASE, TOP, MY, PX, PY, MX = range(6)


def cube():
    return build_object(validate_object({"id": "cube", "type": "box", "size": [1, 1, 1]}, "objects[0]"))


def cube_light_data(obj, lights=(WEST, EAST)):
    tol = 1e-9
    out = {}
    for light in lights:
        lt = _light_record(light, GROUND, tol)
        out[light["id"]], _w = _object_light_data(obj, lt)
    obj["lights"] = out
    return out


def load(name):
    return load_scene(str(EXAMPLES / name))


# --- names (§5.3.2) ----------------------------------------------------------------

def test_is_multi():
    assert not ML.is_multi([WEST])
    assert ML.is_multi([WEST, EAST])
    assert ML.is_multi({"lights": [WEST, EAST, dict(WEST, id="w2")]})
    assert not ML.is_multi({"lights": [WEST]})


@pytest.mark.parametrize("stem, dependent", [
    ("sil.0", True), ("sil.12", True), ("g0.base", True), ("g3.top", True),
    ("c", False), ("apex", False), ("og0.base", False), ("og1.top", False), ("v4", False),
    ("sil", False), ("g0", False), ("g0.basement", False), ("sil.0.lamp", False),
])
def test_light_dependent_stems(stem, dependent):
    assert ML.is_light_dependent_stem(stem) is dependent


def test_curved_stem_name():
    assert ML.curved_stem_name("ball", "sil.0", "lamp", False) == "ball.sil.0"
    assert ML.curved_stem_name("ball", "sil.0", "lamp", True) == "ball.sil.0.lamp"
    assert ML.curved_stem_name("pillar", "g1.top", "sun", True) == "pillar.g1.top.sun"
    assert ML.curved_stem_name("pillar", "g1.base", "sun", False) == "pillar.g1.base"
    for stem in ("c", "apex", "og0.base", "og2.top"):              # shared by all lights
        assert ML.curved_stem_name("cone", stem, "sun", True) == f"cone.{stem}"


@pytest.mark.parametrize("single, multi", [
    ("ball.sil.0", "ball.sil.0.lamp"),
    ("ball.sil.0.shadow.lamp", "ball.sil.0.lamp.shadow.lamp"),            # the light id twice on purpose
    ("ball.sil.3.shadow.lamp.wall", "ball.sil.3.lamp.shadow.lamp.wall"),
    ("ball.sil.0.foot", "ball.sil.0.lamp.foot"),
    ("pillar.g0.base", "pillar.g0.base.lamp"),
    ("pillar.g1.top.shadow.lamp", "pillar.g1.top.lamp.shadow.lamp"),
    ("pillar.g1.top.foot.wall", "pillar.g1.top.lamp.foot.wall"),
    ("ball.c", "ball.c"), ("cone.apex", "cone.apex"), ("pillar.og0.base", "pillar.og0.base"),
    ("cube.v3", "cube.v3"), ("cube.v3.shadow.lamp", "cube.v3.shadow.lamp"), ("cube.v3.foot", "cube.v3.foot"),
    ("cube.s0.lamp", "cube.s0.lamp"), ("wall.b2", "wall.b2"), ("L.lamp", "L.lamp"), ("F.lamp.wall", "F.lamp.wall"),
])
def test_multi_light_name_map(single, multi):
    assert ML.multi_light_name(single, "lamp") == multi


def test_multi_light_name_map_with_object_ids():
    # a light called "g0" and a receiver called "base": F.g0.base is the light foot, not a stem
    assert ML.multi_light_name("F.g0.base", "g0", object_ids={"pillar"}) == "F.g0.base"
    assert ML.multi_light_name("pillar.g0.base", "g0", object_ids={"pillar"}) == "pillar.g0.base.g0"


# --- edges (§5.3.3) and the acceptance silhouette table (§5.3.10) ---------------------------

def test_silhouette_lights_acceptance_cube():
    obj = cube()
    data = cube_light_data(obj)
    assert int(data["west"]["edge_silhouette"].sum()) == 6        # "west has exactly six silhouette edges"
    sil, lists = ML.silhouette_lights([data[k]["edge_silhouette"] for k in LIGHT_IDS], LIGHT_IDS,
                                     len(obj["edge_templates"]))
    by_edge = {(t["from"].split(".")[1], t["to"].split(".")[1]): (bool(s), l)
               for t, s, l in zip(obj["edge_templates"], sil.tolist(), lists)}
    expected = {
        ("v4", "v5"): ["west", "east"], ("v6", "v7"): ["west", "east"],        # top edges y = ±0.5
        ("v0", "v3"): ["west"], ("v0", "v4"): ["west"], ("v3", "v7"): ["west"], ("v5", "v6"): ["west"],
        ("v1", "v2"): ["east"], ("v1", "v5"): ["east"], ("v2", "v6"): ["east"], ("v4", "v7"): ["east"],
        ("v0", "v1"): [], ("v2", "v3"): [],                                    # the other two base edges
    }
    assert {k: v[1] for k, v in by_edge.items()} == expected
    assert sum(v[0] for v in by_edge.values()) == 10
    assert all(v[0] == bool(v[1]) for v in by_edge.values())


def test_silhouette_lights_single_light_is_the_v1_flag_and_missing_records():
    obj = cube()
    data = cube_light_data(obj, (WEST,))
    sil, lists = ML.silhouette_lights([data["west"]["edge_silhouette"]], ["west"], len(obj["edge_templates"]))
    assert sil.tolist() == data["west"]["edge_silhouette"].tolist()
    assert lists == [["west"] if s else [] for s in sil.tolist()]
    sil, lists = ML.silhouette_lights([None, None], LIGHT_IDS, n_edges=3)
    assert sil.tolist() == [False] * 3 and lists == [[], [], []]
    # review fix: every record missing still gives one flag per edge, never a zero-length array
    n = len(obj["edge_templates"])
    sil, lists = ML.silhouette_lights([None, None], LIGHT_IDS, n)
    assert sil.shape == (n,) and not sil.any() and lists == [[]] * n
    with pytest.raises(TypeError):
        ML.silhouette_lights([None, None], LIGHT_IDS)                 # n_edges is required
    with pytest.raises(ValueError):
        ML.silhouette_lights([data["west"]["edge_silhouette"]], ["west"], n + 1)


def test_plate_silhouette_lights():
    assert ML.plate_silhouette_lights({"west": True, "east": False}, LIGHT_IDS) == ["west"]
    assert ML.plate_silhouette_lights({"west": True, "east": True}, ["east", "west"]) == ["east", "west"]
    assert ML.plate_silhouette_lights({}, LIGHT_IDS) == []


# --- form shadow and core (§5.3.1, §5.3.3) ------------------------------------------------

def test_unlit_union_and_core_acceptance_cube():
    obj = cube()
    data = cube_light_data(obj)
    union, masks, core = ML.unlit_union([data[k]["lit"] for k in LIGHT_IDS])
    assert union.tolist() == [BASE, MY, PX, PY, MX]
    assert union[masks[0]].tolist() == [BASE, MY, PX, PY]          # west: +x, -y, +y, base
    assert union[masks[1]].tolist() == [BASE, MY, PY, MX]          # east: -x, -y, +y, base
    assert union[core].tolist() == [BASE, MY, PY]                  # the ±y faces and the base


def test_form_table_single_light_equals_the_v1_arrays():
    obj = cube()
    data = cube_light_data(obj, (WEST,))
    t = ML.form_table(obj, ["west"])
    assert np.array_equal(t["form_idx"], data["west"]["form_idx"])
    assert np.array_equal(t["form_lens"], data["west"]["form_lens"])
    assert t["form_faces"] == data["west"]["form_faces"]
    assert t["masks"][0].all() and t["core"].all()


def test_form_table_light_inside_and_missing_record():
    obj = cube()
    inside = {"id": "bulb", "type": "point", "position": [0.0, 0.0, 0.5]}
    data = cube_light_data(obj, (WEST, inside))
    assert data["bulb"]["light_inside"]
    t = ML.form_table(obj, ["west", "bulb"])
    assert len(t["form_faces"]) == 6                                # the light inside makes every face unlit
    assert t["masks"][1].all()
    assert [obj["face_point_names"][k] for k in range(6) if k in (BASE, MY, PX, PY)] == \
        [f for f, c in zip(t["form_faces"], t["core"].tolist()) if c]
    t = ML.form_table(obj, ["west", "nobody"])                      # no record: lit by it, no core
    assert not t["core"].any() and not t["masks"][1].any()


def test_split_form_shares_the_drawables():
    faces = [["a"], ["b"], ["c"]]
    polygons = [[[0.0, 0.0]], [[1.0, 1.0]], [[2.0, 2.0]]]
    by_light, core = ML.split_form(faces, polygons, [np.array([True, False, True]), np.array([True, True, False])],
                                   np.array([True, False, False]), LIGHT_IDS)
    assert by_light["west"] == ([["a"], ["c"]], [[[0.0, 0.0]], [[2.0, 2.0]]])
    assert by_light["east"] == ([["a"], ["b"]], [[[0.0, 0.0]], [[1.0, 1.0]]])
    assert core == ([["a"]], [[[0.0, 0.0]]])
    assert by_light["west"][1][0] is polygons[0] and core[1][0] is polygons[0]


def test_plate_form_lights():
    tw = [1e-9, 1e-9]
    assert ML.plate_form_lights([1.0, -1.0], tw, -2.0, 1e-9) == ([True, False], False)
    assert ML.plate_form_lights([1.0, 1.0], tw, -2.0, 1e-9) == ([True, True], True)
    assert ML.plate_form_lights([1.0, 1.0], tw, 2.0, 1e-9) == ([False, False], False)
    assert ML.plate_form_lights([0.0, 1.0], tw, -2.0, 1e-9) == ([False, True], True)   # parallel: unlit, no entry
    assert ML.plate_form_lights([1.0, 1.0], tw, 0.0, 1e-9) == ([False, False], False)  # camera in the plane


def test_assemble_form_shadow_light_major():
    items = [
        {"object": "cube", "by_light": {"west": {"faces": [["f1"]], "polygons": [[[0.0, 0.0]]], "terminator": []},
                                        "east": {"faces": [], "polygons": [], "terminator": []}},
         "core": {"faces": [["f1"]], "polygons": [[[0.0, 0.0]]]}},
        {"object": "ball", "by_light": {"west": {"faces": [], "polygons": [], "terminator": [{"t": 1}]},
                                        "east": {"faces": [], "polygons": [], "terminator": [{"t": 2}]}},
         "core": None},
        {"object": "wall", "by_light": {"east": {"faces": [["wall.b0"]], "polygons": [], "terminator": []}},
         "core": {"faces": [], "polygons": []}},
    ]
    form, core = ML.assemble_form_shadow(items, LIGHT_IDS)
    assert [(e["light"], e["object"]) for e in form] == [("west", "cube"), ("west", "ball"), ("east", "ball"),
                                                          ("east", "wall")]
    assert form[1]["terminator"] == [{"t": 1}] and form[2]["terminator"] == [{"t": 2}]
    assert set(form[0]) == {"light", "object", "faces", "polygons", "terminator"}
    assert core == [{"object": "cube", "faces": [["f1"]], "polygons": [[[0.0, 0.0]]]}]


# --- construction per light (§5.3.3, §5.3.5) -----------------------------------------------

@pytest.mark.parametrize("example", ["basic.json", "curved_demo.json", "wall_and_ground.json", "directional.json"])
def test_construction_block_single_light_equals_the_pipeline_block(example):
    scene = load(example)
    A = shadow_geometry(scene)
    B = project_scene(scene, A)
    default = scene["receivers"][0]["id"]
    blocks = ML.construction_blocks(B["lights"], B["receiver_lights"], B["shadows"], default)
    assert list(blocks) == [lt["id"] for lt in scene["lights"]]
    assert blocks[scene["lights"][0]["id"]] == B["construction"]
    doc = compose(scene, B)
    assert json.dumps(ML.construction_doc(blocks[scene["lights"][0]["id"]]), sort_keys=True) == \
        json.dumps(doc["construction"], sort_keys=True)


def _light_b(lid, lp, vp):
    return {"id": lid, "light_point": {"point": lp, "at_infinity": None},
            "shadow_vp": {"point": vp, "at_infinity": None}}


def test_construction_blocks_split_by_light_and_receiver():
    shadows = [
        {"receiver": "ground", "light": "west", "rays": [["L", "a.v0"]], "checks": [{"point": "x", "max_error_mm": 0.0}],
         "segments": [{"kind": "LP", "point": "a.v0", "points": [[0.0, 0.0], [1.0, 1.0]]}]},
        {"receiver": "ground", "light": "west", "rays": [["L", "b.v0"]], "checks": [], "segments": []},
        {"receiver": "ground", "light": "east", "rays": [["L", "a.v1"]], "checks": [], "segments": []},
        {"receiver": "wall", "light": "west", "rays": [["F", "a.v0.foot.wall"]], "checks": [], "segments": []},
        {"receiver": "wall", "light": "east", "rays": [["F", "a.v1.foot.wall"]], "checks": [], "segments": []},
    ]
    lights = [_light_b("west", [1.0, 2.0], [3.0, 4.0]), _light_b("east", [-1.0, 2.0], None)]
    receiver_lights = {"wall": [_light_b("west", None, [5.0, 6.0]), _light_b("east", None, [7.0, 8.0])]}
    blocks = ML.construction_blocks(lights, receiver_lights, shadows, "ground")
    assert list(blocks) == ["west", "east"]
    w, e = blocks["west"], blocks["east"]
    assert w["light_point"] == [1.0, 2.0] and w["shadow_vp"] == [3.0, 4.0] and e["shadow_vp"] is None
    assert w["rays"] == [["L", "a.v0"], ["L", "b.v0"]] and e["rays"] == [["L", "a.v1"]]
    assert len(w["checks"]) == 1 and e["checks"] == [] and len(w["segments"]) == 1
    assert w["per_receiver"]["wall"]["shadow_vp"] == [5.0, 6.0]
    assert e["per_receiver"]["wall"]["shadow_vp"] == [7.0, 8.0]
    assert w["per_receiver"]["wall"]["rays"] == [["F", "a.v0.foot.wall"]]
    assert e["per_receiver"]["wall"]["rays"] == [["F", "a.v1.foot.wall"]]
    doc = ML.construction_doc(w)
    assert set(doc) == {"light_point", "light_point_at_infinity", "shadow_vp", "shadow_vp_at_infinity", "rays",
                        "checks", "segments", "per_receiver"}
    assert set(doc["per_receiver"]["wall"]) == {"shadow_vp", "shadow_vp_at_infinity", "rays", "checks", "segments"}


# --- umbra entries (§5.3.4, §5.3.5) -------------------------------------------------------

def test_umbra_entries_per_receiver():
    from tests.test_umbra import EAST as EAST_UV, WEST as WEST_UV
    receivers = [{"id": "ground", "lit": {"west": True, "east": True}},
                 {"id": "wall", "lit": {"west": False, "east": True}}]
    shadows = [{"receiver": "ground", "light": "west", "polygons": [[list(p) for p in WEST_UV]]},
               {"receiver": "ground", "light": "east", "polygons": [[list(p) for p in EAST_UV]]},
               {"receiver": "wall", "light": "east", "polygons": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]]}]
    out = ML.umbra_entries(receivers, shadows, LIGHT_IDS, [360, 240])
    assert [e["receiver"] for e in out] == ["ground", "wall"]
    assert out[0]["lights"] == ["west", "east"] and len(out[0]["polygons"]) == 3
    assert out[1] == {"receiver": "wall", "lights": ["east"], "polygons": []}
    off = ML.umbra_entries(receivers, shadows, LIGHT_IDS, [360, 240], compute=False)
    assert [e["polygons"] for e in off] == [None, None]
    assert [e["lights"] for e in off] == [["west", "east"], ["east"]]
    none_lit = ML.umbra_entries([{"id": "ground", "lit": {"west": False, "east": False}}], shadows, LIGHT_IDS,
                                [360, 240])
    assert none_lit == [{"receiver": "ground", "lights": [], "polygons": []}]
    doc = {"canvas_mm": [360.0, 240.0], "shadows": copy.deepcopy(shadows), "umbra": out}
    from castplane.umbra import umbra_from_document
    assert umbra_from_document(json.loads(json.dumps(doc))) == out


def test_stage_a_shadow_order_is_receiver_light_caster_with_two_casters():
    """Review check (§5.3.2, §5.1.3.1): ``A["shadows"]`` is ordered receiver → light (scene order)
    → caster, not object-major, also with two casters and two lights."""
    scene = json.loads((ROOT / "examples" / "basic.json").read_text())
    second = copy.deepcopy(scene["lights"][0])
    second["id"] = "second"
    second["position"][0] *= -1
    scene["lights"].append(second)
    casters = [o["id"] for o in scene["objects"]]
    assert len(casters) >= 2
    A = shadow_geometry(load_scene(scene))
    keys = [(r["receiver"], r["light"], r["object"]) for r in A["shadows"]]
    assert keys == [("ground", lid, oid) for lid in ("lamp", "second") for oid in casters]
