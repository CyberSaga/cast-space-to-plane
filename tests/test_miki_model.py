"""The Hanabishi Miki drawing-reference model (``tools/make_miki_model.py``, ``tools/miki_model/``).

The generator is a dev tool outside the package; these tests import it from ``tools/`` and pin what the
shipped files promise: the generator reproduces ``examples/miki.json`` and ``examples/meshes/miki.{obj,mtl,glb}``
byte for byte (the build is independent of the BLAS kernel and SIMD loops, ``meshkit._below_fan``); every object
is a closed, consistently oriented manifold that castplane takes without mesh preprocessing warnings; the scene
camera renders with ``warnings == []`` and the default layers; the polygon / triangle budget and the 64 feature
silhouette vertices per object hold; ``display_color``, ``group`` (D84) and the links ``parent`` / ``joint`` (D85: one
tree rooted at the skirt, each joint on its parent) are web-only keys the core ignores; and the GLB and OBJ import with
``castplane import``.  Object lists come from ``miki_model.assemble`` (no hard-coded counts).
The model is built once per module (~20 s).
"""

from __future__ import annotations

import copy
import json
import pathlib
import re
import sys

import numpy as np
import pytest

import castplane
from castplane import pipeline
from castplane.cli import EXIT_OK, main
from castplane.meshprep import MESH_MAX_RAYS
from castplane.output.geometry_json import dumps

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from miki_model import assemble as asm  # noqa: E402
from miki_model import export  # noqa: E402
from miki_model import meshkit as mk  # noqa: E402
from miki_model.rig import Rig  # noqa: E402

SCENE = ROOT / "examples" / "miki.json"
MESHES = ROOT / "examples" / "meshes"
COLOUR = re.compile(r"#[0-9a-f]{6}")


@pytest.fixture(scope="module")
def model():
    """The model built from the default rig (strict: invalid parts raise)."""
    return asm.assemble(Rig())


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads(SCENE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def scene(raw) -> dict:
    return castplane.load_scene(copy.deepcopy(raw))


@pytest.fixture(scope="module")
def stage_a(scene) -> dict:
    return pipeline.shadow_geometry(scene)


@pytest.fixture(scope="module")
def rendered(scene) -> dict:
    return castplane.render(scene)


WEB_KEYS = ("display_color", "group", "parent", "joint")   # read only by the web UI; the core ignores them

#: D85: the 19 joints (object-local = world: identity transforms), from rig.py (design table; 5 decimals).
JOINTS = {
    "skirt": (0.0, 0.005, 0.78), "blouse": (0.0, 0.0, 0.94), "legs": (0.0, 0.005, 0.78), "socks": (0.0, 0.0, 0.42),
    "shoes": (0.0, 0.01, 0.065), "neck": (0.0, 0.013, 1.18), "head": (0.0, 0.013, 1.285),
    "hair": (0.0, 0.012, 1.405), "headband": (0.0, 0.012, 1.405), "sidelocks": (0.0, 0.012, 1.405),
    "back_hair": (0.0, 0.012, 1.405), "eyes": (0.0, 0.012, 1.405), "face_marks": (0.0, 0.012, 1.405),
    "collar": (0.0, 0.013, 1.18), "scarf": (0.0, -0.099, 1.09), "ring": (0.0, -0.1125, 1.07),
    "arm_l": (0.126, 0.005, 1.137), "arm_r": (-0.126, 0.005, 1.137), "sock_tops": (0.0, 0.0, 0.42),
}


def _without_display_color(raw: dict) -> dict:
    """``raw`` without the web-only object keys (:data:`WEB_KEYS`)."""
    plain = copy.deepcopy(raw)
    for o in plain["objects"]:
        for k in WEB_KEYS:
            o.pop(k, None)
    return plain


# ---------------------------------------------------------------------------- (a) reproducible files

def test_build_reproduces_the_scene_json_byte_for_byte(model):
    assert model.ok
    assert export.scene_text(model).encode("utf-8") == SCENE.read_bytes()


def test_build_reproduces_the_obj_mtl_and_glb_byte_for_byte(model):
    assert export.obj_text(model, "miki.mtl").encode("utf-8") == (MESHES / "miki.obj").read_bytes()
    assert export.mtl_text(model).encode("utf-8") == (MESHES / "miki.mtl").read_bytes()
    assert export.glb_bytes(model) == (MESHES / "miki.glb").read_bytes()


def test_scene_objects_are_the_generator_objects_in_order(raw, model):
    assert [o["id"] for o in raw["objects"]] == list(asm.OBJECT_IDS) == list(model.meshes)
    assert all(o["type"] == "mesh" and set(o["data"]) == {"vertices", "faces", "smooth_groups"} for o in raw["objects"])


# ---------------------------------------------------------------------------- (b) closed manifolds, no warnings

def test_every_object_is_a_closed_consistently_oriented_manifold(raw):
    for o in raw["objects"]:
        d = o["data"]
        n_v = len(d["vertices"])
        directed = [(f[i], f[(i + 1) % len(f)]) for f in d["faces"] for i in range(len(f))]
        assert all(0 <= a < n_v for a, _ in directed), o["id"]
        assert len(set(directed)) == len(directed), f"{o['id']}: a directed edge is used twice (bad orientation)"
        assert all((b, a) in set(directed) for a, b in directed), f"{o['id']}: an edge has no opposite (open)"
        used = {a for a, _ in directed}
        assert used == set(range(n_v)), f"{o['id']}: unreferenced vertices"
        rep = mk.validate(mk.Mesh(d["vertices"], d["faces"], d["smooth_groups"]), o["id"])
        assert rep.ok, rep.summary()


def test_castplane_takes_every_object_without_mesh_preprocessing(stage_a):
    assert [o["id"] for o in stage_a["objects"]] == list(asm.OBJECT_IDS)
    for o in stage_a["objects"]:
        assert o["type"] == "mesh"
        assert o["fallback"] is False, o["id"]
        assert o["prep_warnings"] == [], (o["id"], o["prep_warnings"])


def test_stage_a_has_no_warnings(stage_a):
    assert stage_a["warnings"] == []


# ---------------------------------------------------------------------------- (c) scene camera render

def test_scene_camera_render_has_no_warnings(rendered):
    assert rendered["geometry"]["warnings"] == []


def test_default_layers_are_objects_and_cast_shadow(raw, scene, rendered):
    assert raw["output"]["layers"] == ["objects", "cast_shadow"]
    assert scene["output"]["layers"] == ["objects", "cast_shadow"]
    assert re.findall(r'<g id="([a-z_]+)"', rendered["svg"]) == ["objects", "cast_shadow"]


# ---------------------------------------------------------------------------- (d) budget and rays

def test_polygon_and_triangle_budget(raw, model):
    polygons = sum(len(o["data"]["faces"]) for o in raw["objects"])
    triangles = sum(len(f) - 2 for o in raw["objects"] for f in o["data"]["faces"])
    assert (polygons, triangles) == (model.stats["total"]["polygons"], model.stats["total"]["triangles"])
    assert polygons <= asm.BUDGET["polygons"]
    assert triangles <= asm.BUDGET["triangles"]
    assert model.stats["within_budget"]


def test_at_most_64_feature_silhouette_vertices_per_object(model, stage_a):
    # the generator's count (feature silhouette vertices towards the sun) and castplane's ray selection
    assert model.stats["rays_ok"] and model.stats["rays_over"] == []
    assert all(o["ray_vertices"] <= MESH_MAX_RAYS for o in model.stats["objects"])
    rays = {rec["object"]: int(np.count_nonzero(rec["ray_vertices"])) for rec in stage_a["shadows"]}
    assert set(rays) == set(asm.OBJECT_IDS)
    assert max(rays.values()) <= MESH_MAX_RAYS


# ---------------------------------------------------------------------------- (e) display_color

def test_every_object_has_its_display_color(raw):
    assert set(asm.DISPLAY_MATERIALS) == set(asm.OBJECT_IDS)
    for o in raw["objects"]:
        colour = o["display_color"]
        assert COLOUR.fullmatch(colour), (o["id"], colour)
        assert colour == asm.display_color(o["id"]) == asm.MATERIALS[asm.DISPLAY_MATERIALS[o["id"]]]
        # deterministic key order; the root (skirt) has no parent key
        parent = ["parent"] if asm.PARENTS[o["id"]] is not None else []
        assert list(o) == ["id", "type", "display_color", "group", *parent, "joint", "data"]


def test_every_object_is_a_part_of_the_miki_group(raw):
    # D84: one group with all 19 objects, so a click in the web UI selects the whole figure, a second click the part
    assert [o["group"] for o in raw["objects"]] == [export.GROUP] * len(asm.OBJECT_IDS)
    assert export.GROUP == "miki"


def test_display_color_group_and_links_are_ignored_by_the_core(raw, scene, rendered):
    plain = castplane.load_scene(_without_display_color(raw))
    assert all(k not in o for o in scene["objects"] for k in WEB_KEYS)
    out = castplane.render(plain)
    assert out["svg"] == rendered["svg"]
    assert dumps(out["geometry"]) == dumps(rendered["geometry"])


# ---------------------------------------------------------------------------- (f) linked parts (D85)

def test_parents_form_one_tree_rooted_at_the_skirt():
    assert tuple(asm.PARENTS) == asm.OBJECT_IDS
    assert [oid for oid, p in asm.PARENTS.items() if p is None] == ["skirt"]
    depth = {}
    for oid in asm.OBJECT_IDS:
        node, seen = oid, []
        while asm.PARENTS[node] is not None:         # every id reaches the root without a cycle
            assert node not in seen, f"cycle through {oid}"
            seen.append(node)
            node = asm.PARENTS[node]
        assert node == "skirt", oid
        depth[oid] = len(seen)
    assert max(depth.values()) == 4                   # skirt -> blouse -> neck -> head -> hair: 5 levels
    children = {oid: [c for c, p in asm.PARENTS.items() if p == oid] for oid in asm.OBJECT_IDS}
    assert children["head"] == ["headband", "hair", "eyes", "sidelocks", "back_hair", "face_marks"]
    assert children["blouse"] == ["scarf", "collar", "arm_l", "arm_r", "neck"]
    assert children["skirt"] == ["blouse", "legs"]
    assert (children["legs"], children["socks"], children["scarf"], children["neck"]) \
        == (["socks", "sock_tops"], ["shoes"], ["ring"], ["head"])


def test_the_file_links_are_the_rig_joints(raw):
    links = asm.part_links(Rig())
    assert list(links) == list(asm.OBJECT_IDS)
    assert {oid: joint for oid, (_p, joint) in links.items()} == JOINTS
    for o in raw["objects"]:
        parent, joint = links[o["id"]]
        assert o.get("parent") == parent, o["id"]
        assert ("parent" in o) == (parent is not None), o["id"]
        assert o["joint"] == list(joint) == list(JOINTS[o["id"]]), o["id"]
        assert all(type(x) is float for x in o["joint"]), o["id"]
        assert o["group"] == export.GROUP                # a link counts only inside one group (D85 §1)


def _bbox_distance(p, vertices) -> float:
    v = np.asarray(vertices, dtype=np.float64)
    lo, hi = v.min(axis=0), v.max(axis=0)
    return float(np.linalg.norm(np.maximum(0.0, np.maximum(lo - p, p - hi))))


def test_each_joint_is_on_its_parent_and_near_its_part(raw):
    # inside the parent's bounding box (inclusive); within 0.12 m of the part's own box: the face decals, the
    # headband and the limb tops turn about the skull / hip / knee, which lie outside their own boxes
    verts = {o["id"]: o["data"]["vertices"] for o in raw["objects"]}
    for o in raw["objects"]:
        j = np.array(o["joint"], dtype=np.float64)
        if "parent" in o:
            assert _bbox_distance(j, verts[o["parent"]]) <= 1e-9, (o["id"], o["parent"])
        assert _bbox_distance(j, verts[o["id"]]) <= 0.12, o["id"]


# ---------------------------------------------------------------------------- (g) OBJ / GLB import

def test_glb_imports_into_the_same_objects(tmp_path, raw):
    out = tmp_path / "miki_glb.json"
    assert main(["import", str(MESHES / "miki.glb"), "--inline", "-o", str(out), "--quiet"]) == EXIT_OK
    imported = json.loads(out.read_text(encoding="utf-8"))
    assert [o["id"] for o in imported["objects"]] == list(asm.OBJECT_IDS)
    castplane.load_scene(imported)
    for got, want in zip(imported["objects"], raw["objects"]):
        g, w = got["data"], want["data"]
        # triangles: castplane's fan triangulation of the scene's faces; positions: the scene's (float32)
        assert len(g["faces"]) == sum(len(f) - 2 for f in w["faces"]), got["id"]
        assert {tuple(round(x, 5) + 0.0 for x in v) for v in g["vertices"]} \
            == {tuple(float(x) + 0.0 for x in v) for v in w["vertices"]}, got["id"]


def test_obj_imports_and_validates(tmp_path, raw):
    out = tmp_path / "miki_obj.json"
    assert main(["import", str(MESHES / "miki.obj"), "--inline", "-o", str(out), "--quiet"]) == EXIT_OK
    imported = json.loads(out.read_text(encoding="utf-8"))
    assert [o["id"] for o in imported["objects"]] == ["miki"]
    validated = castplane.load_scene(imported)
    assert len(validated["objects"]) == 1
    data = imported["objects"][0]["data"]
    assert len(data["faces"]) == sum(len(o["data"]["faces"]) for o in raw["objects"])
    assert len(data["vertices"]) == sum(len(o["data"]["vertices"]) for o in raw["objects"])
