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
    # examples may hold loader-level objects (M5 ``mesh`` with ``path``): expand them first (§5.0.2)
    from castplane.io import load_expanded_scene
    return load_expanded_scene(str(EXAMPLES / name))[0]


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


# =====================================================================================
# End-to-end (contract §5.3.10): the pipeline hooks, the document and the SVG
# =====================================================================================

import re  # noqa: E402

import castplane  # noqa: E402
from castplane.output.geometry_json import dumps  # noqa: E402
from castplane.shadow import receiver_frame  # noqa: E402
from castplane.umbra import tolerances, umbra_from_document, umbra_pieces  # noqa: E402
from tests.reference import random_scenes, raster  # noqa: E402
from tests.test_umbra import EXPECTED, EXPECTED_AREAS, area, assert_convex_ccw, total  # noqa: E402

#: The M6 keys of a multi-light document (contract §5.3.5); none of them exists for ``N = 1``.
M6_KEYS = ("constructions", "umbra", "form_shadow_core")
GROUND_RECEIVER = {"id": "ground", "type": "plane", "normal": [0, 0, 1], "offset": 0.0}
LAYERS = ["horizon", "objects", "form_shadow", "cast_shadow", "construction", "labels"]


def scene_of(objects, lights, camera, canvas=(360, 240), receivers=None, **output):
    out = {"canvas_mm": list(canvas), "layers": list(LAYERS), "png_dpi": 300}
    out.update(output)
    return {"version": "0.1", "units": "m", "up": "z", "objects": copy.deepcopy(objects),
            "lights": copy.deepcopy(lights), "receivers": copy.deepcopy(receivers or [GROUND_RECEIVER]),
            "camera": copy.deepcopy(camera), "output": out}


ACCEPTANCE_CAMERA = {"position": [0, -6, 4], "target": [0, 0, 0], "roll_deg": 0, "focal_length_mm": 35,
                     "frame_mm": [36, 24], "shift_mm": [0, 0], "near_m": 0.05}


def acceptance_scene() -> dict:
    """``multilight_two_point_symmetric_box`` (contract §5.3.10)."""
    return scene_of([{"id": "cube", "type": "box", "size": [1, 1, 1]}], [WEST, EAST], ACCEPTANCE_CAMERA)


SUN = {"id": "sun", "type": "directional", "direction": [0.3, 0.5, 0.812403840463596]}
LAMP = {"id": "lamp", "type": "point", "position": [-2.0, -3.0, 3.0]}


def curved_scene() -> dict:
    """The curved two-light scene of §5.3.10: ``ball`` sphere, ``pillar`` cylinder, ``wedge`` prism; ``lamp``
    point ``(−2, −3, 3)``, ``sun`` directional ``(0.3, 0.5, 0.812403840463596)``."""
    objects = [
        {"id": "ball", "type": "sphere", "radius": 0.5, "transform": {"position": [1.2, 0.9, 0.0]}},
        {"id": "pillar", "type": "cylinder", "radius": 0.3, "height": 1.6, "transform": {"position": [-1.0, 1.0, 0.0]}},
        {"id": "wedge", "type": "prism", "polygon": [[0, 0], [1.2, 0], [0, 0.9]], "height": 0.7,
         "transform": {"position": [0.1, -0.9, 0.0], "rotation_deg": [0, 0, 15]}},
    ]
    camera = {"position": [0.5, -7.0, 3.5], "target": [0.0, 0.3, 0.5], "roll_deg": 0, "focal_length_mm": 35,
              "frame_mm": [36, 24], "shift_mm": [0, 0], "near_m": 0.05}
    return scene_of(objects, [LAMP, SUN], camera)


def three_light_scene(order=(0, 1, 2)) -> dict:
    """The concave prism of ``make_concavity_scene(1)`` with two more point lights (§5.3.10)."""
    scene = random_scenes.make_concavity_scene(1)
    first = scene["lights"][0]
    x, y, z = first["position"]
    lights = [first, {"id": "light_b", "type": "point", "position": [round(x + 1.3, 4), round(y - 0.9, 4), z]},
              {"id": "light_c", "type": "point", "position": [round(x - 0.8, 4), round(y + 1.1, 4), round(z + 0.6, 4)]}]
    scene["lights"] = [lights[k] for k in order]
    return scene


def render(scene, **kw):
    return castplane.render(load_scene(scene), **kw)


def doc_of(scene, **kw):
    return render(scene, **kw)["geometry"]


def js(x) -> str:
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def map_strings(x, fn):
    """Apply ``fn`` to every string value (not dict keys) of a JSON-like structure."""
    if isinstance(x, str):
        return fn(x)
    if isinstance(x, list):
        return [map_strings(v, fn) for v in x]
    if isinstance(x, dict):
        return {k: map_strings(v, fn) for k, v in x.items()}
    return x


def single_light_scene(scene: dict, k: int) -> dict:
    s = copy.deepcopy(scene)
    s["lights"] = [copy.deepcopy(scene["lights"][k])]
    return s


def assert_per_light_bit_identical(scene: dict) -> dict:
    """The bit-identity statement of §5.3.2 for every light: ``shadows[light == k]``, ``constructions[k]``,
    ``form_shadow[light == k]`` and the light's / shared ``points`` equal the single-light document of that
    light after the name map (compared as canonical JSON text, i.e. bit for bit).  Returns the document."""
    multi = doc_of(scene)
    object_ids = {o["id"] for o in scene["objects"]}
    covered = set()
    for k, light in enumerate(scene["lights"]):
        lid = light["id"]
        single = doc_of(single_light_scene(scene, k))
        assert not any(key in single for key in M6_KEYS)

        def mp(name, lid=lid):
            return ML.multi_light_name(name, lid, object_ids)

        mine = [e for e in multi["shadows"] if e["light"] == lid]
        assert js(mine) == js(map_strings(single["shadows"], mp)), lid
        assert js(multi["constructions"][lid]) == js(map_strings(single["construction"], mp)), lid
        form = [{key: v for key, v in e.items() if key != "light"} for e in multi["form_shadow"] if e["light"] == lid]
        assert js(form) == js(map_strings(single["form_shadow"], mp)), lid
        for name, p in single["points"].items():
            assert mp(name) in multi["points"], (lid, name)
            assert js(multi["points"][mp(name)]) == js(p), (lid, name)
            covered.add(mp(name))
    assert covered == set(multi["points"])          # no point that no single-light document has
    assert multi["construction"] == multi["constructions"][scene["lights"][0]["id"]]
    return multi


def ground_homography(doc: dict, receiver: dict | None = None) -> np.ndarray:
    """``H_r = P·E_r`` (contract §5.3.1): ``E_r = [e1 e2 o_r; 0 0 1]``; ``(e1, e2)`` the receiver frame of
    §5.1.2 (the ground: ``H = P[:, (0, 1, 3)]``).  Returns ``(H, E)``."""
    P = np.asarray(doc["camera"]["P"], dtype=float)
    if receiver is None or receiver.get("bounds") is None:
        E = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 0, 0], [0, 0, 1.0]])
    else:
        n = np.asarray(receiver["plane"][:3], dtype=float)
        e1, e2 = receiver_frame(n)
        o = -float(receiver["plane"][3]) * n
        E = np.zeros((4, 3))
        E[:3, 0], E[:3, 1], E[:3, 2], E[3, 2] = e1, e2, o, 1.0
    return P @ E, E


def map_back(doc: dict, pieces, receiver=None) -> list:
    """The pieces mapped to the receiver plane by ``H_r⁻¹`` (world points ``(k, 3)``) and in plane
    coordinates ``(k, 2)``."""
    H, E = ground_homography(doc, receiver)
    Hi = np.linalg.inv(H)
    out = []
    for piece in pieces:
        p = np.asarray(piece, dtype=float)
        X = np.hstack([p, np.ones((p.shape[0], 1))]) @ Hi.T
        uv = X[:, :2] / X[:, 2:3]
        world = (np.hstack([uv, np.ones((uv.shape[0], 1))]) @ E.T)
        out.append((world[:, :3] / world[:, 3:4], uv))
    return out


def shoelace(p) -> float:
    p = np.asarray(p, dtype=float)
    return float(0.5 * np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]))


def convex_clip(subject, clip):
    """Sutherland–Hodgman of a convex CCW ``subject`` against a convex CCW ``clip`` (test helper)."""
    out = [np.asarray(v, dtype=float) for v in subject]
    C = [np.asarray(v, dtype=float) for v in clip]
    for i in range(len(C)):
        a, b = C[i], C[(i + 1) % len(C)]
        inp, out = out, []
        if not inp:
            break

        def side(p, a=a, b=b):
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        for j in range(len(inp)):
            p, q = inp[j], inp[(j + 1) % len(inp)]
            sp, sq = side(p), side(q)
            if sp >= 0:
                out.append(p)
            if (sp >= 0) != (sq >= 0):
                out.append(p + (q - p) * (sp / (sp - sq)))
    return out


def union_corners(polys, tol=1e-9, angle_tol=1e-6) -> list:
    """The corner vertices of the union of disjoint convex CCW polygons: a candidate vertex is a corner iff
    the total interior angle of the union there (sum over the pieces: their angle at a vertex, ``π`` on the
    relative interior of an edge, ``2π`` strictly inside) is not ``π`` or ``2π`` (within ``angle_tol``);
    candidates closer than ``tol`` are one vertex."""
    polys = [np.asarray(p, dtype=float) for p in polys]
    cands = []
    for p in polys:
        for v in p:
            if not any(np.max(np.abs(v - c)) <= tol for c in cands):
                cands.append(v)
    corners = []
    for c in cands:
        total_angle = 0.0
        for p in polys:
            n = p.shape[0]
            d = np.max(np.abs(p - c), axis=1)
            k = int(np.argmin(d))
            if d[k] <= tol:
                a, b = p[(k - 1) % n] - c, p[(k + 1) % n] - c
                total_angle += math.acos(max(-1.0, min(1.0, float(a @ b) / (np.linalg.norm(a) * np.linalg.norm(b)))))
                continue
            inside, on_edge = True, False
            for j in range(n):
                a, b = p[j], p[(j + 1) % n]
                cr = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
                if abs(cr) <= tol * max(1.0, float(np.linalg.norm(b - a))):
                    t = float((c - a) @ (b - a)) / float((b - a) @ (b - a))
                    if 0.0 < t < 1.0:
                        on_edge = True
                    else:
                        inside = False
                elif cr < 0:
                    inside = False
            if on_edge and inside:
                total_angle += math.pi
            elif inside:
                total_angle += 2 * math.pi
        if abs(total_angle - math.pi) > angle_tol and abs(total_angle - 2 * math.pi) > angle_tol:
            corners.append(c)
    return corners


import math  # noqa: E402


# --- the acceptance case (§5.3.10) ------------------------------------------------------

def test_acceptance_document():
    doc = assert_per_light_bit_identical(acceptance_scene())
    assert doc["warnings"] == []
    assert [(s["light"], s["object"]) for s in doc["shadows"]] == [("west", "cube"), ("east", "cube")]
    west = doc["shadows"][0]["polygons"]
    assert len(west) == 1
    np.testing.assert_allclose(west[0], [list(p) for p in _umbra_west()], rtol=0, atol=1e-6)
    assert sorted(doc["constructions"]) == ["east", "west"]
    (entry,) = doc["umbra"]
    assert entry["receiver"] == "ground" and entry["lights"] == ["west", "east"]
    pieces = entry["polygons"]
    assert len(pieces) == 3
    for piece, expected, a in zip(pieces, EXPECTED, EXPECTED_AREAS):
        np.testing.assert_allclose(piece, expected, rtol=0, atol=1e-6)
        assert area(piece) == pytest.approx(a, rel=1e-9)
        assert_convex_ccw(piece)
    assert abs(pieces[2][2][0]) < 1e-13
    assert total(pieces) == pytest.approx(1538.7327412965, rel=1e-6)


def _umbra_west():
    from tests.test_umbra import WEST as W
    return W


def test_acceptance_umbra_mapped_back_to_the_ground():
    doc = doc_of(acceptance_scene())
    back = map_back(doc, doc["umbra"][0]["polygons"])
    ground = [uv for _w, uv in back]
    assert sum(shoelace(p) for p in ground) == pytest.approx(7.0 / 6.0, abs=1e-9)
    for i in range(len(ground)):                     # pairwise disjoint interiors
        for j in range(i + 1, len(ground)):
            inter = convex_clip(ground[i], ground[j])
            assert len(inter) < 3 or abs(shoelace(inter)) <= 1e-12
    verts = np.vstack(ground)
    hexagon = [(0.5, 0.5), (-0.5, 0.5), (-0.5, -0.5), (0.5, -0.5), (0.0, 2 / 3), (0.0, -2 / 3)]
    for v in hexagon:
        assert np.min(np.max(np.abs(verts - np.array(v)), axis=1)) <= 1e-9, v
    assert all(np.allclose(w[:, 2], 0.0, atol=1e-12) for w, _uv in back)


FACE_NAMES = cube()["face_point_names"]


def test_acceptance_form_shadow_core_and_edges():
    doc = doc_of(acceptance_scene())
    faces = {lid: [e["faces"] for e in doc["form_shadow"] if e["light"] == lid] for lid in LIGHT_IDS}
    assert [e["light"] for e in doc["form_shadow"]] == ["west", "east"]
    assert faces["west"] == [[FACE_NAMES[k] for k in (BASE, MY, PX, PY)]]          # +x, −y, +y, base
    assert faces["east"] == [[FACE_NAMES[k] for k in (BASE, MY, PY, MX)]]          # −x, −y, +y, base
    (core,) = doc["form_shadow_core"]
    assert core["object"] == "cube" and core["faces"] == [FACE_NAMES[k] for k in (BASE, MY, PY)]
    assert len(core["polygons"]) == 3
    by_edge = {(e["from"].split(".")[1], e["to"].split(".")[1]): e for e in doc["edges"]}
    assert sum(e["silhouette"] for e in doc["edges"]) == 10
    assert by_edge[("v4", "v5")]["silhouette_lights"] == ["west", "east"]
    assert by_edge[("v6", "v7")]["silhouette_lights"] == ["west", "east"]
    assert by_edge[("v5", "v6")]["silhouette_lights"] == ["west"]                 # top edge x = +0.5
    assert by_edge[("v4", "v7")]["silhouette_lights"] == ["east"]                 # top edge x = −0.5
    assert by_edge[("v0", "v1")]["silhouette_lights"] == [] and by_edge[("v2", "v3")]["silhouette_lights"] == []
    assert all(e["silhouette"] == bool(e["silhouette_lights"]) for e in doc["edges"])


def g_ids(svg: str) -> list:
    return re.findall(r'<g id="([^"]*)"', svg)


def g_tag(svg: str, gid: str) -> str:
    m = re.search(r'<g id="%s"[^>]*>' % re.escape(gid), svg)
    assert m, gid
    return m.group(0)


def g_body(svg: str, gid: str) -> str:
    """The text of the group ``gid`` (its children); ``""`` for an empty ``<g …/>``."""
    tag = g_tag(svg, gid)
    if tag.endswith("/>"):
        return ""
    start = svg.index(tag) + len(tag)
    depth, pos = 1, start
    for m in re.finditer(r"<g[ >]|</g>", svg[start:]):
        depth += 1 if m.group(0) != "</g>" else -1
        if depth == 0:
            return svg[start:start + m.start()]
    raise AssertionError(gid)


def test_acceptance_svg():
    svg = render(acceptance_scene())["svg"]
    ids = g_ids(svg)
    for gid in ("cast_shadow.east", "cast_shadow.west"):
        assert 'fill-opacity="0.15"' in g_tag(svg, gid)
    for gid in ("form_shadow.east", "form_shadow.west"):
        assert 'fill-opacity="0.09"' in g_tag(svg, gid)
    assert g_tag(svg, "cast_shadow.umbra") == '<g id="cast_shadow.umbra" fill="#000" fill-opacity="0.3" stroke="none">'
    paths = re.findall(r"<path d=\"([^\"]*)\"", g_body(svg, "cast_shadow.umbra"))
    assert len(paths) == 1 and paths[0].count("M ") == 3 and paths[0].count("Z") == 3
    assert g_tag(svg, "form_shadow.core") == '<g id="form_shadow.core">'
    assert g_body(svg, "form_shadow.core").count("<polygon") == 3
    assert g_body(svg, "form_shadow.west").count("<polygon") == 1           # the +x face only
    assert g_body(svg, "form_shadow.east").count("<polygon") == 1           # the −x face only
    for lid in ("east", "west"):
        assert f"construction.{lid}" in ids
        for kind in ("LP", "FQ", "PQ"):
            assert f"construction.{lid}.{kind}" in ids
    assert "construction.LP" not in ids
    # §5.0.6 order inside the layers: light groups by code point, then core / umbra on top
    order = [i for i in ids if i.startswith(("form_shadow.", "cast_shadow.")) and i.count(".") == 1]
    assert order == ["form_shadow.east", "form_shadow.west", "form_shadow.core",
                     "cast_shadow.east", "cast_shadow.west", "cast_shadow.umbra"]


# --- the curved two-light scene (§5.3.10) --------------------------------------------------

def test_curved_two_lights_bit_identical_and_names():
    doc = assert_per_light_bit_identical(curved_scene())
    names = set(doc["points"])
    assert {"ball.sil.0.lamp", "ball.sil.0.sun", "ball.c"} <= names
    assert "ball.sil.0.lamp.shadow.lamp" in names and "ball.sil.0" not in names
    assert any(n.startswith("pillar.g0.base.lamp") for n in names)
    assert any(n.startswith("pillar.g0.base.sun") for n in names)
    assert not any(re.fullmatch(r"pillar\.g\d\.(base|top)(\.shadow\.\w+|\.foot)?", n) for n in names)
    # one form_shadow entry per (light, curved object) holding that light's terminator
    curved_entries = [(e["light"], e["object"]) for e in doc["form_shadow"] if e["object"] in ("ball", "pillar")]
    assert curved_entries == [("lamp", "ball"), ("lamp", "pillar"), ("sun", "ball"), ("sun", "pillar")]
    for e in doc["form_shadow"]:
        for t in e["terminator"]:
            if "segment" in t:
                assert all(n.endswith("." + e["light"]) for n in t["segment"]), t["segment"]
    for lid in ("lamp", "sun"):
        for kind, name in doc["constructions"][lid]["rays"]:
            if name.startswith(("ball.", "pillar.")) and name.split(".")[1] not in ("c", "apex"):
                assert f".{lid}" in name and (kind == "L" or name.endswith(".foot")), name
    assert {c["object"] for c in doc["form_shadow_core"]} <= {"wedge"}


def parse_name(name: str, light_ids, receiver_ids, object_ids, multi: bool) -> str:
    """Parse a point name from the right against the known light and receiver ids (contract §5.0.4) and
    rebuild it: ``<obj>.<stem>[.<light>][.shadow.<light> | .foot][.<r>]``, ``<obj>.s<k>.<light>[.<r>]``,
    ``L.<light>``, ``F.<light>[.<r>]``, ``<r>.b<k>``."""
    parts = name.split(".")
    if parts[0] in ("L", "F") and parts[0] not in object_ids:
        assert parts[1] in light_ids and len(parts) <= (2 if parts[0] == "L" else 3), name
        if len(parts) == 3:
            assert parts[2] in receiver_ids[1:], name
        return name
    r = None
    if len(parts) > 2 and parts[-1] in receiver_ids[1:]:
        r = parts.pop()
    if len(parts) >= 3 and parts[-2] == "shadow" and parts[-1] in light_ids:
        tail, light, base = "shadow", parts[-1], parts[:-2]
    elif parts[-1] == "foot":
        tail, light, base = "foot", None, parts[:-1]
    elif len(parts) == 3 and re.fullmatch(r"s\d+", parts[1]) and parts[2] in light_ids:
        assert parts[0] in object_ids or parts[0] in receiver_ids, name
        return name
    else:
        tail, light, base = None, None, parts
        assert r is None, name
    obj, stem = base[0], base[1:]
    assert obj in object_ids or obj in receiver_ids, name
    if multi and len(stem) >= 2 and stem[-1] in light_ids and ML.is_light_dependent_stem(".".join(stem[:-1])):
        assert light is None or light == stem[-1], name            # the light id twice on purpose
        stem = stem[:-1] + [stem[-1]]
    else:
        assert not ML.is_light_dependent_stem(".".join(stem)) or not multi, name
    out = ".".join([obj] + stem)
    if tail == "shadow":
        out += f".shadow.{light}"
    elif tail == "foot":
        out += ".foot"
    if r is not None:
        out += f".{r}"
    return out


def test_point_name_grammar_round_trip():
    for scene, multi in ((curved_scene(), True), (single_light_scene(curved_scene(), 0), False)):
        doc = doc_of(scene)
        lights = {lt["id"] for lt in scene["lights"]}
        rids = [r["id"] for r in scene["receivers"]]
        oids = {o["id"] for o in scene["objects"]}
        for name in doc["points"]:
            assert parse_name(name, lights, rids, oids, multi) == name


# --- umbra reproducible from the document (§5.3.5 (c)) -----------------------------------------

@pytest.mark.parametrize("make", [acceptance_scene, curved_scene, three_light_scene])
def test_umbra_reproducible_from_document(make):
    doc = doc_of(make())
    again = umbra_from_document(json.loads(dumps(doc)))
    assert js(again) == js(doc["umbra"])


# --- three lights (§5.3.10) ---------------------------------------------------------------

def _image_masks(doc, pts):
    from tests.test_umbra import nonzero_mask, pieces_mask
    expect = np.ones(pts.shape[0], dtype=bool)
    rid = doc["umbra"][0]["receiver"]
    for lid in doc["umbra"][0]["lights"]:
        lit = np.zeros(pts.shape[0], dtype=bool)
        for sh in doc["shadows"]:
            if sh["light"] == lid and sh["receiver"] == rid and sh["polygons"]:
                lit |= nonzero_mask(pts, sh["polygons"])
        expect &= lit
    return expect, pieces_mask(pts, doc["umbra"][0]["polygons"])


def test_three_lights_union_equals_the_raster_and():
    doc = doc_of(three_light_scene())
    assert len(doc["umbra"][0]["lights"]) == 3
    pieces = doc["umbra"][0]["polygons"]
    assert pieces
    allp = np.vstack([np.asarray(p) for p in pieces])
    lo, hi = allp.min(axis=0) - 2.0, allp.max(axis=0) + 2.0
    from tests.test_umbra import grid as uv_grid
    pts, _cell = uv_grid(lo[0], hi[0], lo[1], hi[1], 800, 600)
    expect, got = _image_masks(doc, pts)
    assert (got & expect).sum() / (got | expect).sum() >= 0.995
    for piece in pieces:
        assert_convex_ccw(piece)


def assert_same_corners(a, b, atol):
    ca, cb = union_corners(a), union_corners(b)
    assert len(ca) == len(cb)
    for c in ca:
        assert min(float(np.max(np.abs(c - d))) for d in cb) <= atol, c


def test_three_lights_permutation_invariance():
    """Permuting the lights permutes ``umbra[].lights`` and leaves the umbra region unchanged: the union
    area within 1e-9 and the corner set of the union within 1e-9 mm.  The partition into pieces may differ
    (implementation note of §5.3: coincident edges of different lights, e.g. the shared ground-contact
    edges, are ordered by edge index, which follows the light order)."""
    base = doc_of(three_light_scene())
    a = base["umbra"][0]["polygons"]
    for order in ((2, 0, 1), (1, 2, 0), (0, 2, 1)):
        scene = three_light_scene(order)
        doc = doc_of(scene)
        assert doc["umbra"][0]["lights"] == [lt["id"] for lt in scene["lights"]]
        b = doc["umbra"][0]["polygons"]
        assert total(b) == pytest.approx(total(a), rel=1e-9)
        assert_same_corners(a, b, 1e-9)
        for piece in b:
            assert_convex_ccw(piece)


# --- degenerate and corner cases (§5.3.8, §5.3.10) -------------------------------------------

def test_inactive_second_light():
    below = {"id": "under", "type": "point", "position": [1.0, 0.5, -2.0]}
    scene = scene_of([{"id": "cube", "type": "box", "size": [1, 1, 1]}], [WEST, below], ACCEPTANCE_CAMERA)
    r = render(scene)
    doc, svg = r["geometry"], r["svg"]
    assert {(w["code"], tuple(w["ids"])) for w in doc["warnings"]} >= {("LIGHT_BELOW_RECEIVER", ("under",))}
    assert doc["umbra"] == [{"receiver": "ground", "lights": ["west"], "polygons": []}]
    assert doc["receivers"][0]["lit"] == {"west": True, "under": False}
    assert 'fill-opacity="0.3"' in g_tag(svg, "cast_shadow.west")
    assert re.search(r'<g id="cast_shadow.umbra"[^>]*/>', svg)                   # written, empty
    assert 'fill-opacity="0.18"' in g_tag(svg, "form_shadow.west")


def test_two_identical_lights():
    twin = dict(WEST, id="twin")
    scene = scene_of([{"id": "cube", "type": "box", "size": [1, 1, 1]}], [WEST, twin], ACCEPTANCE_CAMERA)
    doc = doc_of(scene)
    assert doc["warnings"] == []
    shadow_area = total(ML._umbra.record_pieces(doc["shadows"][0]["polygons"], *tolerances(doc["canvas_mm"]))[0])
    assert total(doc["umbra"][0]["polygons"]) == pytest.approx(shadow_area, rel=1e-9)


def test_light_inside_a_box_for_one_of_two_lights():
    """Convention (§5.3.1 [decision]): a point light inside an object is not left out of the umbra; its
    drawn region W_k is the other objects' shadows, so the emitted umbra is the intersection of the drawn
    regions, a subset of the physical umbra."""
    bulb = {"id": "bulb", "type": "point", "position": [0.0, 0.0, 0.5]}
    objects = [{"id": "cube", "type": "box", "size": [1, 1, 1]},
               {"id": "low", "type": "box", "size": [0.6, 0.6, 0.3], "transform": {"position": [2.0, 0.0, 0.0]}}]
    camera = dict(ACCEPTANCE_CAMERA, position=[1.0, -7.0, 4.0], target=[1.5, 0.0, 0.0])
    scene = scene_of(objects, [WEST, bulb], camera)
    doc = doc_of(scene)
    inside = [w for w in doc["warnings"] if w["code"] == "LIGHT_INSIDE_OBJECT"]
    assert [w["ids"] for w in inside] == [["cube"]]
    rec = {(s["light"], s["object"]): s for s in doc["shadows"]}
    assert rec[("bulb", "cube")]["polygons"] == [] and rec[("bulb", "cube")]["loops"] == []
    assert rec[("bulb", "low")]["polygons"] and rec[("west", "cube")]["polygons"]
    assert doc["umbra"][0]["lights"] == ["west", "bulb"]
    pieces = doc["umbra"][0]["polygons"]
    drawn = [[s["polygons"] for s in doc["shadows"] if s["light"] == lid] for lid in ("west", "bulb")]
    assert js(pieces) == js(umbra_pieces(drawn, doc["canvas_mm"]))
    assert pieces and total(pieces) <= total(ML._umbra.record_pieces(rec[("bulb", "low")]["polygons"],
                                                                     *tolerances(doc["canvas_mm"]))[0]) + 1e-9


def test_camera_on_and_below_the_ground():
    on = dict(ACCEPTANCE_CAMERA, position=[0.0, -6.0, 0.0], target=[0.0, 0.0, 0.5])
    doc = doc_of(scene_of([{"id": "cube", "type": "box", "size": [1, 1, 1]}], [WEST, EAST], on))
    dumps(doc)                                                              # finite (allow_nan=False)
    assert doc["umbra"][0]["polygons"] == []                               # every drawable degenerate
    below = dict(ACCEPTANCE_CAMERA, position=[0.3, -6.0, -2.0], target=[0.0, 0.0, 0.0])
    scene = scene_of([{"id": "cube", "type": "box", "size": [1, 1, 1]}], [WEST, EAST], below)
    doc = doc_of(scene)
    dumps(doc)
    assert doc["umbra"][0]["polygons"]
    assert umbra_raycast_iou(load_scene(scene), doc) >= 0.99


def umbra_raycast_iou(scene: dict, doc: dict, n: int = 400, entry: int = 0) -> float:
    """IoU of the umbra pieces of ``umbra[entry]`` (the ground) mapped back by ``H⁻¹`` against the ray-cast
    reference "occluded from every active light" (``raycast.occluded`` ANDed over ``umbra[].lights``), on
    ground grid samples inside the extended rectangle ``R`` and in front of the near plane (contract §5.3.10)."""
    from castplane.camera import camera_matrix, nu
    from tests.reference import raycast
    e = doc["umbra"][entry]
    lights = [lt for lt in scene["lights"] if lt["id"] in e["lights"]]
    cam = camera_matrix(scene["camera"], scene["output"]["canvas_mm"])
    back = [uv for _w, uv in map_back(doc, e["polygons"])]
    objs = np.vstack([random_scenes.world_extreme_points(o) for o in scene["objects"]])[:, :2]
    pts = np.vstack(back + [objs]) if back else objs
    lo, hi = pts.min(axis=0) - 1.0, pts.max(axis=0) + 1.0

    def masks(lo, hi, n):
        xs, ys = random_scenes.grid(lo, hi, n)
        X, Y = np.meshgrid(xs, ys)
        O = np.stack([X.ravel(), Y.ravel(), np.zeros(X.size)], axis=1)
        O4 = np.hstack([O, np.ones((O.shape[0], 1))])
        x = O4 @ cam["P"].T
        with np.errstate(divide="ignore", invalid="ignore"):
            u, v = x[:, 0] / x[:, 2], x[:, 1] / x[:, 2]
        u0, u1, v0, v1 = cam["rect"]
        valid = (nu(cam, O4) >= 0.0) & (u >= u0) & (u <= u1) & (v >= v0) & (v <= v1)
        ref = valid.copy()
        for lt in lights:
            ref &= raycast.occluded(scene, lt, O)
        got = raster.rasterize_polygons(back, xs, ys).ravel() & valid if back else np.zeros_like(valid)
        return ref.reshape(len(ys), len(xs)), got.reshape(len(ys), len(xs)), xs, ys

    ref, got, xs, ys = masks(lo, hi, 160)
    sel = ref | got
    if sel.any():                                       # zoom on the umbra (and anything the reference sees)
        iy, ix = np.nonzero(sel)
        hx, hy = xs[1] - xs[0], ys[1] - ys[0]
        lo = np.array([xs[ix.min()] - 2 * hx, ys[iy.min()] - 2 * hy])
        hi = np.array([xs[ix.max()] + 2 * hx, ys[iy.max()] + 2 * hy])
        ref, got, xs, ys = masks(lo, hi, n)
    return raster.iou(ref, got)


def test_umbra_false_leaves_polygons_null():
    for make in (acceptance_scene, curved_scene):
        on, off = doc_of(make()), doc_of(make(), umbra=False)
        assert all(e["polygons"] is None for e in off["umbra"])
        assert [e["lights"] for e in off["umbra"]] == [e["lights"] for e in on["umbra"]]
        on.pop("umbra"), off.pop("umbra")
        assert js(on) == js(off)
    scene = load_scene(acceptance_scene())
    A = shadow_geometry(scene)
    B = project_scene(scene, A, umbra=False)
    assert B["umbra"][0]["polygons"] is None


@pytest.mark.parametrize("example", sorted(p.name for p in EXAMPLES.glob("*.json")))
def test_single_light_documents_carry_no_m6_key(example):
    scene = load(example)
    if len(scene["lights"]) != 1:
        pytest.skip("multi-light example")
    doc = castplane.render(scene)["geometry"]
    assert not any(k in doc for k in M6_KEYS)
    assert not any("light" in e for e in doc["form_shadow"])
    assert not any("silhouette_lights" in e for e in doc["edges"])
    assert "fill-opacity" not in "".join(g_tag(castplane.render(scene)["svg"], g) for g in
                                         g_ids(castplane.render(scene)["svg"]) if g.startswith(("cast_shadow.",
                                                                                                "form_shadow.")))


def test_umbra_light_id_in_a_single_light_scene_renders_the_single_light_document():
    scene = scene_of([{"id": "core", "type": "box", "size": [1, 1, 1]}], [dict(WEST, id="umbra")], ACCEPTANCE_CAMERA)
    doc = doc_of(scene)
    assert not any(k in doc for k in M6_KEYS)
    assert {s["light"] for s in doc["shadows"]} == {"umbra"}


# --- a two-light wall_and_ground: umbra per receiver (§5.3.10) -----------------------------------

def wall_two_lights() -> dict:
    scene = json.loads((EXAMPLES / "wall_and_ground.json").read_text())
    lamp = scene["lights"][0]
    scene["lights"].append({"id": "lamp2", "type": "point", "position": [-lamp["position"][0] - 1.2,
                                                                        lamp["position"][1], lamp["position"][2]]})
    return scene


def test_wall_and_ground_two_lights_umbra_per_receiver():
    scene = wall_two_lights()
    doc = assert_per_light_bit_identical(scene)
    assert [e["receiver"] for e in doc["umbra"]] == ["ground", "wall"]
    for e, rcv in zip(doc["umbra"], doc["receivers"]):
        assert e["lights"] == [lid for lid in ("lamp", "lamp2") if rcv["lit"][lid]]
    wall = doc["receivers"][1]
    pieces = doc["umbra"][1]["polygons"]
    assert pieces, "the two lamps' wall shadows overlap"
    B = np.asarray(wall["bounds"], dtype=float)
    lo, hi = B.min(axis=0) - 1e-9, B.max(axis=0) + 1e-9
    for world, _uv in map_back(doc, pieces, wall):
        assert np.all(world >= lo) and np.all(world <= hi)
        assert np.allclose(world @ np.asarray(wall["plane"][:3]) + wall["plane"][3], 0.0, atol=1e-9)
    assert js(umbra_from_document(json.loads(dumps(doc)))) == js(doc["umbra"])
    svg = render(scene)["svg"]                              # hidden lines on: the hidden groups come first
    ids = g_ids(svg)
    assert ids.index("cast_shadow.hidden") < ids.index("cast_shadow.lamp") < ids.index("cast_shadow.umbra")
    assert ids.index("form_shadow.hidden") < ids.index("form_shadow.lamp") < ids.index("form_shadow.core")
    assert len(re.findall(r"<path", g_body(svg, "cast_shadow.umbra"))) == sum(1 for e in doc["umbra"] if e["polygons"])


# --- rigid equivariance (spec §7.1 row 4, §5.3.7) -------------------------------------------------

def rigid(scene: dict, angle_deg: float, shift) -> dict:
    a = math.radians(angle_deg)
    R = np.array([[math.cos(a), -math.sin(a), 0.0], [math.sin(a), math.cos(a), 0.0], [0.0, 0.0, 1.0]])
    t = np.array([shift[0], shift[1], 0.0])
    out = copy.deepcopy(scene)
    for o in out["objects"]:
        tr = o.setdefault("transform", {})
        tr["position"] = (R @ np.array(tr.get("position", [0.0, 0.0, 0.0]), dtype=float) + t).tolist()
        rot = tr.get("rotation_deg", [0.0, 0.0, 0.0])
        tr["rotation_deg"] = [rot[0], rot[1], rot[2] + angle_deg]
    for lt in out["lights"]:
        if lt["type"] == "point":
            lt["position"] = (R @ np.array(lt["position"], dtype=float) + t).tolist()
        else:
            d = R @ np.array(lt["direction"], dtype=float)
            lt["direction"] = (d / np.linalg.norm(d)).tolist()
    cam = out["camera"]
    cam["position"] = (R @ np.array(cam["position"], dtype=float) + t).tolist()
    cam["target"] = (R @ np.array(cam["target"], dtype=float) + t).tolist()
    return out


@pytest.mark.parametrize("angle, shift", [(37.0, (2.5, -1.25)), (-120.0, (-4.0, 3.0)), (180.0, (0.0, 0.0))])
def test_rigid_equivariance_of_the_umbra(angle, shift):
    a = doc_of(acceptance_scene())["umbra"][0]["polygons"]
    b = doc_of(rigid(acceptance_scene(), angle, shift))["umbra"][0]["polygons"]
    assert len(a) == len(b)
    for p, q in zip(a, b):
        np.testing.assert_allclose(p, q, rtol=0, atol=1e-6)
    a3 = doc_of(three_light_scene())["umbra"][0]["polygons"]
    b3 = doc_of(rigid(three_light_scene(), angle, shift))["umbra"][0]["polygons"]
    assert total(b3) == pytest.approx(total(a3), rel=1e-9)
    # The region, not the partition (implementation note of §5.3.7): the three-light scene has collinear
    # ground-contact edges and cross-light vertex pairs within rounding of each other, so the piece count
    # changes under a rigid motion (19 -> 16 / 20 / 24); the corner set of the union is equivariant with
    # the §4 (i) scaled tolerance.
    scale = max(1.0, max(abs(float(x)) for piece in a3 for v in piece for x in v))
    assert_same_corners(a3, b3, 1e-6 * scale)
    for piece in b3:
        assert_convex_ccw(piece)


def test_curved_two_lights_with_hidden_lines_bit_identical():
    """Hidden lines on (M4): every light's terminator entries are classified exactly as in its single-light
    document (``hidden._curved_pairs`` pairs them per (light, object) in a multi-light document)."""
    scene = curved_scene()
    scene["output"]["hidden_lines"] = True
    doc = assert_per_light_bit_identical(scene)
    assert doc["hidden_lines"] is True
    vis = [t["visibility"] for e in doc["form_shadow"] for t in e["terminator"] if "segment" in t]
    assert vis and set(vis) != {"visible"}             # some terminator segment is (partly) hidden
    svg = render(scene)["svg"]
    assert g_ids(svg).index("form_shadow.hidden") < g_ids(svg).index("form_shadow.lamp")


# --- named witnesses of the contract (§5.3.2, §5.3.10) ----------------------------------------------

@pytest.mark.parametrize("make", [acceptance_scene, curved_scene, wall_two_lights])
def test_per_light_records_bit_identical(make):
    """The §5.3.2 witness (BLAS row stability of ``camera.project`` / ``camera.nu`` with ``N >= 2`` lights):
    every light's records, construction block, form-shadow entries and points equal its single-light
    document after the name map, bit for bit."""
    assert_per_light_bit_identical(make())


# --- a bounded receiver under two lights: plate form shadow and core (§5.3.3) -----------------------

def plate_two_lights(lamp2_position) -> dict:
    """``wall_and_ground`` seen from behind the wall (``+y`` side), hidden lines off, with a second lamp."""
    scene = json.loads((EXAMPLES / "wall_and_ground.json").read_text())
    scene["camera"]["position"], scene["camera"]["target"] = [2.0, 12.0, 4.0], [0.0, 6.0, 1.0]
    scene["output"]["hidden_lines"] = False
    scene["lights"].append({"id": "lamp2", "type": "point", "position": list(lamp2_position)})
    return scene


def test_plate_per_light_entries_and_core():
    wall_edges = lambda doc: [e for e in doc["edges"] if e["object"] == "wall"]   # noqa: E731
    # lamp2 behind the wall (on the camera side): the wall is unlit for lamp only, no core.
    scene = plate_two_lights([1.0, 9.0, 3.0])
    doc = assert_per_light_bit_identical(scene)
    assert ("RECEIVER_UNLIT", ["lamp2", "wall"]) in [(w["code"], w["ids"]) for w in doc["warnings"]]
    assert [e["light"] for e in doc["form_shadow"] if e["object"] == "wall"] == ["lamp"]
    assert "wall" not in [c["object"] for c in doc["form_shadow_core"]]
    assert {tuple(e["silhouette_lights"]) for e in wall_edges(doc)} == {("lamp", "lamp2")}
    ids = g_ids(render(scene)["svg"])
    assert "form_shadow.lamp.wall" in ids and "form_shadow.core.wall" not in ids
    # lamp2 in front of the wall too: the face the camera sees is unlit by both lamps -> per-light entries
    # for both and the plate in form_shadow_core, drawn in form_shadow.core only.
    scene = plate_two_lights([-1.5, 2.5, 3.0])
    doc = assert_per_light_bit_identical(scene)
    entries = [e for e in doc["form_shadow"] if e["object"] == "wall"]
    assert [e["light"] for e in entries] == ["lamp", "lamp2"]
    assert all(e["faces"] == [["wall.b0", "wall.b1", "wall.b2", "wall.b3"]] and e["terminator"] == []
               for e in entries)
    core = {c["object"]: c for c in doc["form_shadow_core"]}
    assert core["wall"]["faces"] == [["wall.b0", "wall.b1", "wall.b2", "wall.b3"]]
    assert js(core["wall"]["polygons"]) == js(entries[0]["polygons"]) == js(entries[1]["polygons"])
    ids = g_ids(render(scene)["svg"])
    assert "form_shadow.core.wall" in ids
    assert "form_shadow.lamp.wall" not in ids and "form_shadow.lamp2.wall" not in ids


def test_two_lights_example_matches_its_readme():
    """examples/README.md describes examples/two_lights.json (M6 part 3): two point lights whose L' and F' lie
    on the canvas, an umbra on the ground, the crate's three faces unlit by both lights in the core, no warning."""
    r = castplane.render(load("two_lights.json"))
    doc, svg = r["geometry"], r["svg"]
    assert doc["warnings"] == [] and sorted(doc["constructions"]) == ["left", "right"]
    w, h = doc["canvas_mm"]
    for c in doc["constructions"].values():
        for key in ("light_point", "shadow_vp"):
            u, v = c[key]
            assert abs(u) < w / 2 and abs(v) < h / 2, key
    (entry,) = doc["umbra"]
    assert entry["lights"] == ["left", "right"] and len(entry["polygons"]) == 118
    assert [(c["object"], len(c["faces"])) for c in doc["form_shadow_core"]] == [("crate", 3)]
    assert "ball.sil.0.left" in doc["points"] and "pillar.g0.base.right" in doc["points"]
    assert 'fill-opacity="0.15"' in g_tag(svg, "cast_shadow.left")
    assert 'fill-opacity="0.09"' in g_tag(svg, "form_shadow.left")
    assert g_body(svg, "cast_shadow.umbra").count("<path") == 1


@pytest.mark.parametrize("case", ["mesh_smooth_prism16", "mesh_open_bottom_box_fallback"])
def test_mesh_scenes_with_two_lights_bit_identical(case):
    """M5 x M6 (after the v5 merge): a mesh object (smooth edges, and the non-manifold per-face fallback) under two
    lights keeps every light's records bit-identical to its single-light document, and the umbra is reproducible."""
    raw = json.loads((ROOT / "tests" / "conformance" / "cases" / f"{case}.json").read_text(encoding="utf-8"))
    first = raw["lights"][0]
    x, y, z = first["position"]
    raw["lights"].append(dict(first, id="second", position=[x + 1.0, y - 0.5, z]))
    doc = assert_per_light_bit_identical(raw)
    assert doc["umbra"][0]["lights"] == [first["id"], "second"] and doc["umbra"][0]["polygons"]
    assert umbra_from_document(json.loads(js(doc))) == doc["umbra"]


# --- review fix m6-umbra#1: light ids `shadow` / `foot` keep their labels (names parsed from the right) ----

def _label_texts(scene) -> list:
    from castplane.output.svg import write_svg
    doc = castplane.render(load_scene(scene))["geometry"]
    return sorted(re.findall(r">([^<]*)</text>", write_svg(doc, layers=["labels"])))


def _wall_two_lights():
    s = json.loads((pathlib.Path(__file__).resolve().parents[1] / "examples" / "wall_and_ground.json").read_text())
    extra = copy.deepcopy(s["lights"][0])
    extra["id"] = "second"
    extra["position"] = [p + d for p, d in zip(extra["position"], (0.7, -0.4, 0.3))]
    s["lights"].append(extra)
    return s


@pytest.mark.parametrize("make", ["curved", "basic", "wall", "wall2"])
@pytest.mark.parametrize("reserved", ["shadow", "foot"])
def test_light_ids_shadow_and_foot_keep_their_labels(make, reserved):
    """§5.0.4 / §5.3.11: `shadow` and `foot` are valid light ids and names are parsed from the right against
    the known light ids, so renaming a light from `lampA` to `shadow` / `foot` renames its labels
    (`sil.0.<light>`, `L.<light>`, `F.<light>[.<r>]`) and drops none."""
    root = pathlib.Path(__file__).resolve().parents[1] / "examples"
    base = {"curved": curved_scene, "basic": lambda: json.loads((root / "basic.json").read_text()),
            "wall": lambda: json.loads((root / "wall_and_ground.json").read_text()), "wall2": _wall_two_lights}[make]

    def labels(lid):
        s = base()
        s["lights"][0]["id"] = lid
        return _label_texts(s)

    plain = labels("lampA")
    assert any("lampA" in t for t in plain)
    assert labels(reserved) == sorted(t.replace("lampA", reserved) for t in plain)
