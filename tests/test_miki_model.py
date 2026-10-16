"""The Hanabishi Miki drawing-reference model (``tools/make_miki_model.py``, ``tools/miki_model/``).

The generator is a dev tool outside the package; these tests import it from ``tools/`` and pin what the
shipped files promise: the generator reproduces ``examples/miki.json`` and ``examples/meshes/miki.{obj,mtl,glb}``
byte for byte (the build is independent of the BLAS kernel and SIMD loops, ``meshkit._below_fan``); every object
is a closed, consistently oriented manifold that castplane takes without mesh preprocessing warnings; the scene
camera renders with ``warnings == []`` and the default layers; the polygon / triangle budget and the 64 feature
silhouette vertices per object hold; ``display_color`` is the web-only colour the core ignores; and the GLB and
OBJ import with ``castplane import``.  Object lists come from ``miki_model.assemble`` (no hard-coded counts).
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


def _without_display_color(raw: dict) -> dict:
    plain = copy.deepcopy(raw)
    for o in plain["objects"]:
        o.pop("display_color", None)
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
        assert list(o) == ["id", "type", "display_color", "data"]      # deterministic key order


def test_display_color_is_ignored_by_the_core(raw, scene, rendered):
    plain = castplane.load_scene(_without_display_color(raw))
    assert all("display_color" not in o for o in scene["objects"])
    out = castplane.render(plain)
    assert out["svg"] == rendered["svg"]
    assert dumps(out["geometry"]) == dumps(rendered["geometry"])


# ---------------------------------------------------------------------------- (f) OBJ / GLB import

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
