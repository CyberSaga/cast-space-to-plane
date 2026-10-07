"""Loaders, scene expansion and ``castplane import`` (contract §5.0.2, §5.2.2, §5.2.8, §5.2.11;
Python only).  Fixtures: ``tests/fixtures/meshes/`` (written by ``tools/make_mesh_fixtures.py``)."""

from __future__ import annotations

import base64
import copy
import json
import math
import os
import pathlib
import struct
import subprocess
import sys

import numpy as np
import pytest

from castplane import load_scene, render, validate_scene
from castplane import io as cio
from castplane.cli import EXIT_INPUT, EXIT_IO, EXIT_MISSING_DEPENDENCY, EXIT_OK, main
from castplane.errors import SceneError
from castplane.io import (EXPANDERS, IMPORT_NOTE_CODES, SUPPORTED_EXTENSIONS, expand_mesh_object, expand_scene,
                          load_expanded_scene, load_mesh_file)
from castplane.io import gltf as G
from castplane.io import obj as O

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "meshes"
EXAMPLES = ROOT / "examples"

CUBE_V = [[-.5, -.5, 0.0], [.5, -.5, 0.0], [.5, .5, 0.0], [-.5, .5, 0.0],
          [-.5, -.5, 1.0], [.5, -.5, 1.0], [.5, .5, 1.0], [-.5, .5, 1.0]]
SPLIT_V = CUBE_V * 3
SPLIT_F = [[8, 11, 10], [8, 10, 9], [12, 13, 14], [12, 14, 15], [16, 17, 21], [16, 21, 20],
           [17, 18, 22], [17, 22, 21], [18, 19, 23], [18, 23, 22], [19, 16, 20], [19, 20, 23]]
#: contract §5.2.11: the fixture camera has yfov = 0.6 rad -> focal_length_mm = 12 / tan(0.3)
FOCAL_IMPORT = 38.79273772518993


def basic_scene() -> dict:
    return json.loads((EXAMPLES / "basic.json").read_text(encoding="utf-8"))


def mesh_scene(path, **keys) -> dict:
    """``analytic_unit_box_point_light_overhead`` with its box replaced by a ``mesh`` + ``path`` object."""
    scene = json.loads((ROOT / "tests" / "conformance" / "cases" / "analytic_unit_box_point_light_overhead.json")
                       .read_text(encoding="utf-8"))
    scene["objects"] = [dict({"id": "m", "type": "mesh", "path": str(path)}, **keys)]
    return scene


# --------------------------------------------------------------------------- glTF building helpers
def gltf_doc(meshes_positions, nodes, *, indices=None, extra=None, mode=4):
    """A glTF dict with one data-URI buffer; ``meshes_positions[m]`` are glTF-axis float32 positions."""
    blob, views, accessors, meshes = bytearray(), [], [], []
    for m, P in enumerate(meshes_positions):
        P = np.asarray(P, dtype="<f4")
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": P.nbytes})
        blob += P.tobytes()
        accessors.append({"bufferView": len(views) - 1, "componentType": 5126, "count": len(P), "type": "VEC3"})
        prim = {"attributes": {"POSITION": len(accessors) - 1}, "mode": mode}
        if indices is not None:
            I = np.asarray(indices[m], dtype="<u2").reshape(-1)
            while len(blob) % 4:
                blob.append(0)
            views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": I.nbytes})
            blob += I.tobytes()
            accessors.append({"bufferView": len(views) - 1, "componentType": 5123, "count": len(I), "type": "SCALAR"})
            prim["indices"] = len(accessors) - 1
        while len(blob) % 4:
            blob.append(0)
        meshes.append({"name": f"mesh{m}", "primitives": [prim]})
    doc = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(blob), "uri": "data:application/octet-stream;base64,"
                                                     + base64.b64encode(bytes(blob)).decode()}],
           "bufferViews": views, "accessors": accessors, "meshes": meshes, "nodes": nodes}
    doc.update(extra or {})
    return doc


def write_gltf(tmp_path, doc, name="t.gltf") -> str:
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return str(p)


TRI = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
BOX_GLTF = [[v[0], v[2], -v[1] + 0.0] for v in SPLIT_V]       # A^T of the split box


# --------------------------------------------------------------------------- OBJ
def test_obj_box_split_fixture_is_the_contract_box():
    raw = load_mesh_file(FIX / "box_split.obj")
    assert raw == {"vertices": SPLIT_V, "faces": SPLIT_F, "smooth_groups": [0] * 12}
    y = load_mesh_file(FIX / "box_split_y.obj")
    assert y["faces"] == SPLIT_F and y["vertices"] == [[v[0], v[2], -v[1] + 0.0] for v in SPLIT_V]


def test_obj_features_negative_indices_groups_smoothing_polygons_continuation():
    raw = load_mesh_file(FIX / "features.obj")
    assert raw["faces"][:6] == [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    assert raw["faces"][6:] == [[8, 10, 9], [8, 11, 10], [9, 10, 11], [8, 9, 11]]   # relative indices after 'o marker'
    assert raw["smooth_groups"] == [0, 1, 2, 2, 2, 2, 0, 0, 0, 0]
    assert raw["vertices"][0] == [-0.5, -0.5, 0.0]                                   # the 4th component is ignored
    parsed = O.read_obj(FIX / "features.obj")
    assert parsed["names"] == ["crate", "bottom", "top", "sides", "walls", "marker", "tetra"]
    walls = load_mesh_file(FIX / "features.obj", "walls")                            # a second name on the g line
    assert walls["faces"] == [[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]] and len(walls["vertices"]) == 8
    assert load_mesh_file(FIX / "features.obj", 0)["faces"] == raw["faces"][:6]      # 'o crate'
    tetra = load_mesh_file(FIX / "features.obj", 6)                                 # 7th distinct name
    assert tetra == load_mesh_file(FIX / "features.obj", "marker")
    assert tetra["vertices"] == [[2.0, 0.0, 0.0], [3.0, 0.0, 0.0], [2.5, 1.0, 0.0], [2.5, 0.5, 1.0]]
    assert tetra["faces"] == [[0, 2, 1], [0, 3, 2], [1, 2, 3], [0, 1, 3]]
    assert load_mesh_file(FIX / "features.obj", "top") == {"vertices": CUBE_V[4:], "faces": [[0, 1, 2, 3]],
                                                           "smooth_groups": [1]}


@pytest.mark.parametrize("text, msg", [
    ("v 0 0 x\n", "non-numeric"),
    ("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 4\n", "out of range"),
    ("v 0 0 0\nv 1 0 0\nf 1 2\n", "at least 3"),
    ("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 0 1 2\n", "index 0"),
    ("v 0 0 0\nv 1 0 0\nv 0 1 0\nf -4 -1 -2\n", "out of range"),
    ("v 0 0 0\nv 1 0 0\nv 0 1 0\nf a 1 2\n", "not an integer"),
    ("v 0 0 nan\n", "finite"),
])
def test_obj_errors(text, msg):
    with pytest.raises(SceneError) as info:
        O.select_obj(O.parse_obj(text))
    assert msg in info.value.message and info.value.field.startswith("line ")


def test_obj_selection_errors():
    parsed = O.parse_obj("o a\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\ng empty\n")
    with pytest.raises(SceneError) as info:
        O.select_obj(parsed, "nope")
    assert info.value.field == "node"
    with pytest.raises(SceneError) as info:
        O.select_obj(parsed, 5)
    assert info.value.field == "node"
    with pytest.raises(SceneError) as info:
        O.select_obj(parsed, "empty")                                                # a name without faces
    assert "no face" in info.value.message
    with pytest.raises(SceneError):
        O.select_obj(O.parse_obj("v 0 0 0\n"))


def test_obj_ignores_unknown_keywords_and_comments():
    raw = O.select_obj(O.parse_obj("# c\nmtllib x.mtl\nusemtl m\nfoo bar\nv 0 0 0 # trailing\nv 1 0 0\nv 0 1 0\n"
                                   "vt 0 0\nvn 0 0 1\nl 1 2\np 1\ns 3\nf 1/1/1 2//1 3/1\n"))
    assert raw == {"vertices": TRI, "faces": [[0, 1, 2]], "smooth_groups": [3]}


# --------------------------------------------------------------------------- glTF / GLB
@pytest.mark.parametrize("name", ["box.gltf", "box_datauri.gltf", "box.glb"])
def test_gltf_box_fixtures_are_the_contract_box_exactly(name):
    """External .bin, data URI and GLB give the same Z-up split box (exact Y-up -> Z-up map)."""
    assert load_mesh_file(FIX / name) == {"vertices": SPLIT_V, "faces": SPLIT_F, "smooth_groups": [0] * 12}


def test_gltf_exact_axis_map():
    """contract §5.2.11: glTF (1, 0, 2) -> castplane (1, -2, 0), with no trig noise."""
    doc = gltf_doc([[[1.0, 0.0, 2.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0]]], [{"mesh": 0}])
    raw = G.gltf_raw(doc, _buffers(doc))
    assert raw["vertices"][0] == [1.0, -2.0, 0.0]
    assert raw["vertices"][2] == [0.0, 0.0, 1.0]
    assert all(math.copysign(1.0, c) == 1.0 for v in raw["vertices"] for c in v if c == 0.0)   # no -0.0


def _buffers(doc):
    return [base64.b64decode(b["uri"].split(",", 1)[1]) for b in doc["buffers"]]


def test_gltf_strided_accessors_index_types_and_modes():
    load = lambda n: load_mesh_file(FIX / "primitives.gltf", n)  # noqa: E731
    quad = lambda y: [[0.0, y, 0.0], [1.0, y, 0.0], [0.0, y + 1.0, 0.0], [1.0, y + 1.0, 0.0]]  # noqa: E731
    assert load("Strided") == {"vertices": quad(0.0), "faces": [[0, 1, 3], [0, 3, 2]], "smooth_groups": [0, 0]}
    assert load("U8") == {"vertices": quad(2.0), "faces": [[0, 1, 3], [0, 3, 2]], "smooth_groups": [0, 0]}
    soup = load("Soup")                                                              # non-indexed: consecutive triples
    assert soup["faces"] == [[0, 1, 2], [3, 4, 5]] and len(soup["vertices"]) == 6
    strip = load("Strip")                                                            # odd triangles swapped
    assert strip["faces"] == [[0, 1, 2], [1, 3, 2]]
    assert strip["vertices"] == [[0.0, 6.0, 0.0], [0.0, 7.0, 0.0], [1.0, 6.0, 0.0], [1.0, 7.0, 0.0]]
    fan = load("Fan")                                                                # the line primitive is skipped
    assert fan["faces"] == [[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 5]] and len(fan["vertices"]) == 6
    doc, buffers = G.read_gltf(FIX / "primitives.gltf")
    acc = G.read_accessor(doc, buffers, 1)                                           # the interleaved NORMAL
    assert acc.tolist() == [[0.0, 1.0, 0.0]] * 4
    whole = load_mesh_file(FIX / "primitives.gltf")
    assert len(whole["faces"]) == 2 + 2 + 2 + 2 + 4


def test_gltf_mirrored_nested_trs_and_column_major_matrix():
    raw = load_mesh_file(FIX / "mirrored.gltf")
    h = math.sqrt(0.5)
    x, y, z, w = 0.0, h, 0.0, h
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    P = np.array(TRI) + [0.0, 1.0, 0.0]                         # leaf matrix: translation (0, 1, 0)
    P = P * [-1.0, 1.0, 1.0] + [2.0, 0.0, 0.0]                  # Mirror: T(2, 0, 0) · S(-1, 1, 1)
    P = P @ R.T                                                 # Root: 90 degrees about +Y
    expected = np.stack([P[:, 0], -P[:, 2], P[:, 1]], axis=1)
    np.testing.assert_allclose(raw["vertices"], expected, atol=1e-15)
    assert raw["faces"] == [[2, 1, 0]]                          # det < 0: faces reversed


def test_gltf_traversal_order_defines_the_first_node_with_a_name(tmp_path):
    nodes = [{"name": "A", "children": [2]}, {"name": "dup", "mesh": 0, "translation": [5.0, 0.0, 0.0]},
             {"name": "dup", "mesh": 0}]
    doc = gltf_doc([TRI], nodes, extra={"scenes": [{"nodes": [0, 1]}], "scene": 0})
    assert G.traversal_order(doc) == [0, 2, 1]
    raw = G.gltf_raw(doc, _buffers(doc), "dup")                 # node 2 (child of A) comes first
    assert raw["vertices"][1] == [1.0, 0.0, 0.0]
    assert G.gltf_raw(doc, _buffers(doc), 1)["vertices"][0] == [5.0, 0.0, 0.0]
    assert G.gltf_raw(doc, _buffers(doc), "mesh0")["vertices"][0] == [0.0, 0.0, 0.0]   # mesh name: first node using it
    assert G.gltf_raw(doc, _buffers(doc), "A")["vertices"][1] == [1.0, 0.0, 0.0]     # subtree of A
    with pytest.raises(SceneError) as info:
        G.gltf_raw(doc, _buffers(doc), "zzz")
    assert info.value.field == "node"
    with pytest.raises(SceneError) as info:
        G.gltf_raw(doc, _buffers(doc), 9)
    assert info.value.field == "node"
    del doc["scenes"], doc["scene"]                              # no scenes: every root in index order
    assert G.traversal_order(doc) == [0, 2, 1]


def _bad(doc, path_field, tmp_path, fn=None):
    p = write_gltf(tmp_path, doc)
    with pytest.raises(SceneError) as info:
        (fn or load_mesh_file)(p)
    assert info.value.field == path_field, (info.value.field, info.value.message)
    return info.value


def test_gltf_errors_carry_the_gltf_json_path(tmp_path):
    base = gltf_doc([TRI], [{"mesh": 0}])
    d = copy.deepcopy(base)
    d["accessors"][0]["sparse"] = {"count": 1}
    _bad(d, "accessors[0].sparse", tmp_path)
    d = copy.deepcopy(base)
    d["accessors"][0]["componentType"] = 5123
    _bad(d, "accessors[0].componentType", tmp_path)
    d = copy.deepcopy(base)
    d["meshes"][0]["primitives"][0]["targets"] = [{"POSITION": 0}]
    _bad(d, "meshes[0].primitives[0].targets", tmp_path)
    d = copy.deepcopy(base)
    d["meshes"][0]["primitives"][0]["mode"] = 7
    _bad(d, "meshes[0].primitives[0].mode", tmp_path)
    d = copy.deepcopy(base)
    d["nodes"][0]["skin"] = 0
    _bad(d, "nodes[0].skin", tmp_path)
    d = copy.deepcopy(base)
    d["asset"]["version"] = "1.0"
    _bad(d, "asset.version", tmp_path)
    d = copy.deepcopy(base)
    d["buffers"][0]["uri"] = "data:application/octet-stream,abc"
    _bad(d, "buffers[0].uri", tmp_path)
    d = copy.deepcopy(base)
    d["extensionsRequired"] = ["KHR_draco_mesh_compression"]
    _bad(d, "extensionsRequired[0]", tmp_path)
    d = copy.deepcopy(base)
    d["accessors"][0]["count"] = 4
    _bad(d, "accessors[0].count", tmp_path)
    d = copy.deepcopy(base)
    d["meshes"][0]["primitives"][0]["mode"] = 1                  # only lines: no triangle
    assert "no triangle" in _bad(d, "meshes", tmp_path).message


def test_glb_container_errors(tmp_path):
    p = tmp_path / "x.glb"
    good = (FIX / "box.glb").read_bytes()
    p.write_bytes(good[:4] + struct.pack("<I", 1) + good[8:])
    with pytest.raises(SceneError, match="version 1"):
        load_mesh_file(p)
    p.write_bytes(good[:16])
    with pytest.raises(SceneError):
        load_mesh_file(p)
    js = json.dumps({"asset": {"version": "2.0"}}).encode()
    bad_first = struct.pack("<4sII", b"glTF", 2, 20 + len(js)) + struct.pack("<II", len(js), 0x004E4942) + js
    p.write_bytes(bad_first)
    with pytest.raises(SceneError, match="first GLB chunk"):
        load_mesh_file(p)


def test_gltf_external_buffer_missing_is_an_os_error(tmp_path):
    doc = json.loads((FIX / "box.gltf").read_text())
    p = write_gltf(tmp_path, doc, "box.gltf")                    # box.bin is not next to it
    with pytest.raises(OSError):
        load_mesh_file(p)


# --------------------------------------------------------------------------- trimesh (STL / PLY)
@pytest.mark.parametrize("name", ["box.stl", "box.ply"])
def test_trimesh_formats_keep_the_stored_order_and_render(name):
    pytest.importorskip("trimesh")
    raw = load_mesh_file(FIX / name)
    assert len(raw["faces"]) == 12 and raw["smooth_groups"] == [0] * 12
    assert len(raw["vertices"]) == (36 if name.endswith(".stl") else 8)              # process=False: no merge
    assert sorted(map(tuple, raw["vertices"])) == sorted(map(tuple, CUBE_V * (3 if name.endswith(".stl") else 1))) \
        or {tuple(v) for v in raw["vertices"]} == {tuple(v) for v in CUBE_V}
    scene, notes = load_expanded_scene(mesh_scene(FIX / name))
    doc = render(scene)["geometry"]
    assert doc["warnings"] == [] and notes == [] and len(doc["edges"]) == 12


def test_missing_trimesh_is_an_import_error_and_exit_3(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "trimesh", None)
    with pytest.raises(ImportError, match=r"castplane\[mesh\]"):
        load_mesh_file(FIX / "box.stl")
    assert main(["import", str(FIX / "box.stl"), "-o", str(tmp_path / "s.json")]) == EXIT_MISSING_DEPENDENCY
    assert "castplane[mesh]" in capsys.readouterr().err
    assert not (tmp_path / "s.json").exists()


def test_trimesh_rejects_a_node_selection():
    pytest.importorskip("trimesh")
    with pytest.raises(SceneError) as info:
        load_mesh_file(FIX / "box.stl", "x")
    assert info.value.field == "node"


def test_supported_extensions_and_registry():
    assert SUPPORTED_EXTENSIONS == (".obj", ".gltf", ".glb", ".stl", ".ply")
    assert EXPANDERS["mesh"] is expand_mesh_object
    assert set(IMPORT_NOTE_CODES) >= {"IMPORT_SPOT_AS_POINT", "IMPORT_CAMERA_DROPPED", "IMPORT_NO_CAMERA_DEFAULT",
                                      "IMPORT_NO_LIGHT_DEFAULT"}
    assert "IMPORT_LIGHT_DROPPED" not in IMPORT_NOTE_CODES                          # retired (§5.0.2)


# --------------------------------------------------------------------------- expansion
def test_validate_scene_on_a_path_only_mesh_names_expand_scene():
    with pytest.raises(SceneError) as info:
        load_scene(mesh_scene("box_split.obj"))
    assert info.value.field == "objects[0].path" and "expand_scene" in info.value.message


def test_expand_scene_fills_data_keeps_path_and_is_idempotent():
    scene = mesh_scene("box_split.obj")
    out, notes = expand_scene(scene, FIX)
    assert notes == [] and out["objects"][0]["path"] == "box_split.obj"
    assert out["objects"][0]["data"]["faces"] == SPLIT_F
    assert scene["objects"][0].get("data") is None                                   # the input is not mutated
    again, _ = expand_scene(out, "/nonexistent")
    assert again == out and again is not out
    assert list(out) == list(scene)                                                  # key order kept
    assert out["lights"] == scene["lights"] and out["lights"] is not scene["lights"]


def test_expand_scene_resolves_a_relative_path_of_a_dict_against_the_cwd(monkeypatch):
    monkeypatch.chdir(FIX)
    scene, notes = load_expanded_scene(mesh_scene("box_split.obj"))
    assert scene["objects"][0]["data"]["vertices"] == SPLIT_V and scene["objects"][0]["path"] == "box_split.obj"


def test_load_expanded_scene_resolves_against_the_scene_file_directory(tmp_path):
    scene = mesh_scene(os.path.relpath(FIX / "box_split.obj", tmp_path))
    p = tmp_path / "s.json"
    p.write_text(json.dumps(scene), encoding="utf-8")
    loaded, notes = load_expanded_scene(str(p))
    assert loaded["objects"][0]["data"]["faces"] == SPLIT_F and notes == []
    absolute, _ = load_expanded_scene(mesh_scene(str(FIX / "box_split.obj")))       # absolute paths as given
    assert absolute["objects"][0]["data"] == loaded["objects"][0]["data"]


def test_expand_scene_passes_other_inputs_through():
    assert expand_scene([1, 2]) == ([1, 2], [])
    s = {"objects": "x", "version": "0.1"}
    assert expand_scene(s) == (s, [])
    prim = basic_scene()
    out, _ = expand_scene(prim)
    assert out == prim


def test_expansion_errors_carry_the_object_field(tmp_path):
    with pytest.raises(SceneError) as info:
        expand_scene(mesh_scene("box.gltf", up="y"), FIX)
    assert info.value.field == "objects[0].up" and "Y-up" in info.value.message
    with pytest.raises(SceneError) as info:
        expand_scene(mesh_scene("features.obj", node="nope"), FIX)
    assert info.value.field == "objects[0].node"
    with pytest.raises(SceneError) as info:
        expand_scene(mesh_scene("box.gltf", node=True), FIX)
    assert info.value.field == "objects[0].node"
    (tmp_path / "bad.obj").write_text("v 0 0 q\n")
    with pytest.raises(SceneError) as info:
        expand_scene(mesh_scene("bad.obj"), tmp_path)
    assert info.value.field == "objects[0].path" and info.value.message.startswith("line 1: ")
    with pytest.raises(OSError) as info:
        expand_scene(mesh_scene("missing.obj"), tmp_path)
    assert "objects[0].path" in str(info.value)


def test_expand_scene_parses_each_file_once_per_call(monkeypatch):
    calls = []
    real = O.read_obj
    monkeypatch.setattr(O, "read_obj", lambda p: calls.append(p) or real(p))
    scene = mesh_scene("features.obj", node="crate")
    scene["objects"].append({"id": "t", "type": "mesh", "path": "features.obj", "node": "tetra"})
    out, _ = expand_scene(scene, FIX)
    assert len(calls) == 1 and len(out["objects"][1]["data"]["faces"]) == 4
    expand_scene(scene, FIX)
    assert len(calls) == 2                                                           # no cache across calls


def test_expand_scene_reads_each_trimesh_file_once_per_call(monkeypatch):
    calls = []
    real = cio.trimesh_adapter.load_trimesh
    monkeypatch.setattr(cio.trimesh_adapter, "load_trimesh", lambda p, n=None: calls.append(p) or real(p, n))
    pytest.importorskip("trimesh")
    scene = {"objects": [{"id": f"m{i}", "type": "mesh", "path": "box.stl"} for i in range(3)]}
    out, _ = expand_scene(scene, FIX)
    assert len(calls) == 1 and out["objects"][0]["data"] == out["objects"][2]["data"]
    out["objects"][0]["data"]["faces"].clear()                                       # copies, not one shared dict
    assert out["objects"][1]["data"]["faces"]
    expand_scene(scene, FIX)
    assert len(calls) == 2


def test_obj_with_a_utf8_bom_keeps_its_first_vertex(tmp_path):
    p = tmp_path / "bom.obj"
    p.write_bytes(b"\xef\xbb\xbfv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    assert load_mesh_file(p) == {"vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                                 "faces": [[0, 1, 2]], "smooth_groups": [0]}


def test_load_obj_and_load_gltf_match_load_mesh_file():
    assert O.load_obj(FIX / "features.obj", "crate") == load_mesh_file(FIX / "features.obj", "crate")
    parsed = O.read_obj(FIX / "box_split.obj")
    assert O.load_obj("unused.obj", parsed=parsed) == load_mesh_file(FIX / "box_split.obj")
    assert G.load_gltf(FIX / "box.glb") == load_mesh_file(FIX / "box.glb")
    parsed = G.read_gltf(FIX / "box.gltf")
    assert G.load_gltf("unused.gltf", parsed=parsed) == load_mesh_file(FIX / "box.gltf")


def test_castplane_io_is_reachable_after_a_plain_import():
    code = "import castplane; print(castplane.io.load_expanded_scene is not None)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=True)
    assert out.stdout.strip() == "True"


def test_up_y_obj_expands_to_the_z_up_box():
    a, _ = load_expanded_scene(mesh_scene(FIX / "box_split.obj"))
    b, _ = load_expanded_scene(mesh_scene(FIX / "box_split_y.obj", up="y"))
    assert a["objects"][0]["data"] == b["objects"][0]["data"]


# --------------------------------------------------------------------------- import (glTF mapping)
def fixture_import(**kw):
    return G.import_gltf_scene(FIX / "import_scene.gltf", ref="import_scene.gltf", **kw)


def expected_camera():
    a = -0.2                                            # the fixture camera is pitched down by 0.2 rad about +X
    forward = np.array([0.0, math.cos(a), math.sin(a)])  # A·(R·(0, 0, -1)) with R = Rx(-0.2)
    position = np.array([0.0, -8.0, 2.0])
    return position, position + forward


def test_import_fixture_scene_exact():
    scene, notes = fixture_import()
    position, target = expected_camera()
    cam = scene["camera"]
    assert cam["position"] == [0.0, -8.0, 2.0] and cam["frame_mm"] == [36.0, 24.0] and cam["near_m"] == 0.1
    assert cam["focal_length_mm"] == FOCAL_IMPORT == 12.0 / math.tan(0.3)
    np.testing.assert_allclose(cam["target"], target, atol=1e-15)
    assert abs(cam["roll_deg"]) < 1e-12
    assert scene["output"] == {"canvas_mm": [360.0, 240.0]}
    assert scene["lights"] == [{"id": "Lamp", "type": "point", "position": [2.0, -1.0, 4.0]},
                               {"id": "Spot", "type": "point", "position": [-2.0, 0.0, 3.0]}]
    assert notes == [{"code": "IMPORT_SPOT_AS_POINT", "ids": ["Spot"],
                      "message": "spot light imported as a point light at its position"}]
    assert scene["meta"] == {"import_notes": notes}
    objs = scene["objects"]
    assert objs[0] == {"id": "node3", "type": "mesh", "path": "import_scene.gltf", "node": 3}
    assert objs[1] == {"id": "Cube", "type": "mesh", "path": "import_scene.gltf", "node": "Cube"}
    pillar = objs[2]
    assert {k: pillar[k] for k in ("id", "type", "radius", "height")} == \
        {"id": "Pillar", "type": "cylinder", "radius": 0.3, "height": 1.5}
    assert pillar["transform"]["position"] == [0.0, 3.0, 0.0]
    np.testing.assert_allclose(pillar["transform"]["rotation_deg"], [0.0, 0.0, 30.0], atol=1e-12)
    assert scene["receivers"] == [{"id": "ground", "type": "plane", "normal": [0.0, 0.0, 1.0], "offset": 0.0}]
    assert (scene["version"], scene["units"], scene["up"]) == ("0.1", "m", "z")


def test_import_fixture_meshes_reload_through_their_node_references():
    scene, _ = fixture_import()
    expanded, _ = expand_scene(scene, FIX)
    cube = expanded["objects"][1]["data"]
    assert cube["faces"] == SPLIT_F and cube["vertices"] == [[x + 1.0, y, z] for x, y, z in SPLIT_V]
    assert expanded["objects"][0]["data"] == load_mesh_file(FIX / "import_scene.gltf", 3)


def test_import_fixture_reloads_with_both_lights_or_one_light():
    scene, _ = fixture_import()
    expanded, _ = expand_scene(scene, FIX)
    # M6 lifted the v1 "exactly one light" row: both imported lights re-load and render
    assert [lt["id"] for lt in validate_scene(expanded)["lights"]] == ["Lamp", "Spot"]
    two = render(validate_scene(expanded))["geometry"]
    assert {(o["light"], o["object"]) for o in two["shadows"]} == \
        {(lt, ob) for lt in ("Lamp", "Spot") for ob in ("node3", "Cube", "Pillar")}
    assert [(u["receiver"], u["lights"]) for u in two["umbra"]] == [("ground", ["Lamp", "Spot"])]
    assert two["umbra"][0]["polygons"] and two["warnings"] == []
    one, notes = fixture_import(light="Lamp")
    assert [lt["id"] for lt in one["lights"]] == ["Lamp"] and notes == []
    doc = render(validate_scene(expand_scene(one, FIX)[0]))["geometry"]
    assert {o["object"] for o in doc["shadows"]} == {"node3", "Cube", "Pillar"}
    assert all(e["smooth"] is False for e in doc["edges"] if e["object"] == "Cube")


def test_import_inline_embeds_the_node_data():
    scene, _ = fixture_import(inline=True, light="Lamp")
    assert "path" not in scene["objects"][1] and "node" not in scene["objects"][1]
    assert scene["objects"][1]["data"] == load_mesh_file(FIX / "import_scene.gltf", "Cube")
    validate_scene(scene)


def test_import_node_and_camera_selection_and_mesh_keys():
    scene, _ = fixture_import(node="Cube", light="Lamp", mesh_keys={"weld_tolerance": 1e-5})
    assert scene["objects"] == [{"id": "Cube", "type": "mesh", "path": "import_scene.gltf", "node": "Cube",
                                 "weld_tolerance": 1e-5}]
    with pytest.raises(SceneError) as info:
        fixture_import(camera="nope")
    assert info.value.field == "--camera"
    with pytest.raises(SceneError) as info:
        fixture_import(light="nope")
    assert info.value.field == "--light"


def test_import_ids_reserved_light_ids_cameras_and_defaults(tmp_path):
    h = math.sqrt(0.5)
    nodes = [{"name": "a.b", "mesh": 0}, {"name": "a.b", "mesh": 0, "translation": [2.0, 0.0, 0.0]},
             {"mesh": 0, "translation": [4.0, 0.0, 0.0], "children": [3]},
             {"name": "nested", "mesh": 0, "translation": [0.0, 1.0, 0.0]},
             {"name": "umbra", "translation": [0.0, 5.0, 0.0], "extensions": {"KHR_lights_punctual": {"light": 0}}},
             {"name": "hidden", "rotation": [-h, 0.0, 0.0, h], "extensions": {"KHR_lights_punctual": {"light": 1}}},
             {"name": "camA", "camera": 0, "translation": [0.0, 1.0, 9.0]},
             {"name": "camB", "camera": 0, "translation": [0.0, 1.0, 7.0]}]
    extra = {"cameras": [{"type": "perspective", "perspective": {"yfov": 0.8, "znear": 0.2}}],
             "extensions": {"KHR_lights_punctual": {"lights": [{"type": "point"}, {"type": "directional"}]}}}
    p = write_gltf(tmp_path, gltf_doc([TRI], nodes, extra=extra))
    scene, notes = G.import_gltf_scene(p, ref="t.gltf")
    assert [o["id"] for o in scene["objects"]] == ["a_b", "a_b_2", "node2"]
    assert [o["node"] for o in scene["objects"]] == [0, 1, 2]       # duplicate / empty names -> indices
    nested = expand_scene(scene, tmp_path)[0]["objects"][2]["data"]   # node 2's subtree includes node 3
    assert len(nested["faces"]) == 2
    assert [lt["id"] for lt in scene["lights"]] == ["umbra_light", "hidden_light"]
    nodes_r = [{"name": "hidden", "mesh": 0}, {"name": "core", "mesh": 0, "translation": [2.0, 0.0, 0.0]}] + nodes[4:6]
    reserved, _ = G.import_gltf_scene(write_gltf(tmp_path, gltf_doc([TRI], nodes_r, extra=extra), "r.gltf"))
    assert [o["id"] for o in reserved["objects"]] == ["hidden_object", "core_object"]     # reserved ids (§5.0.1)
    one, _ = G.import_gltf_scene(write_gltf(tmp_path, gltf_doc([TRI], nodes_r, extra=extra), "r.gltf"), light="umbra")
    assert [o["id"] for o in one["objects"]] == ["hidden_object", "core"] and one["lights"][0]["id"] == "umbra"
    assert scene["lights"][1]["type"] == "directional"                 # shines along local -Z, turned to -Y
    np.testing.assert_allclose(scene["lights"][1]["direction"], [0.0, 0.0, 1.0], atol=1e-15)
    assert scene["camera"]["position"] == [0.0, -9.0, 1.0]
    assert scene["camera"]["focal_length_mm"] == 12.0 / math.tan(0.4) and scene["camera"]["frame_mm"] == [36.0, 24.0]
    assert [n["code"] for n in notes] == ["IMPORT_CAMERA_DROPPED"] and notes[0]["ids"] == ["camB"]
    picked, notes = G.import_gltf_scene(p, ref="t.gltf", camera="camB")
    assert picked["camera"]["position"] == [0.0, -7.0, 1.0] and notes[0]["ids"] == ["camA"]
    bare = write_gltf(tmp_path, gltf_doc([TRI], [{"name": "tri", "mesh": 0}]), "bare.gltf")
    scene, notes = G.import_gltf_scene(bare)
    assert [n["code"] for n in notes] == ["IMPORT_NO_CAMERA_DEFAULT", "IMPORT_NO_LIGHT_DEFAULT"]
    assert scene["lights"] == [{"id": "sun", "type": "directional", "direction": [-0.5, -0.5, 0.7071067811865476]}]
    # bbox of the triangle (0..1, -0..0, 0..1) -> e = 1
    assert scene["camera"] == {"position": [0.5, -2.0, 0.7], "target": [0.5, 0.0, 0.5], "focal_length_mm": 35.0,
                               "frame_mm": [36.0, 24.0]}
    assert scene["output"] == {"canvas_mm": [360.0, 240.0]}


def test_import_camera_roll_aspect_and_looking_down(tmp_path):
    s, c = math.sin(0.1), math.cos(0.1)
    nodes = [{"name": "tri", "mesh": 0},
             {"name": "cam", "camera": 0, "translation": [0.0, 1.0, 5.0], "rotation": [0.0, 0.0, s, c]}]
    extra = {"cameras": [{"type": "perspective", "perspective": {"yfov": 0.5, "aspectRatio": 2.0, "znear": 0.1}}]}
    scene, _ = G.import_gltf_scene(write_gltf(tmp_path, gltf_doc([TRI], nodes, extra=extra)))
    assert scene["camera"]["roll_deg"] == pytest.approx(math.degrees(0.2), abs=1e-12)
    assert scene["camera"]["frame_mm"] == [48.0, 24.0] and scene["output"]["canvas_mm"] == [480.0, 240.0]
    # castplane renders the imported roll the glTF way: the camera's up vector maps to the image +v axis
    from castplane.camera import camera_matrix
    cam = camera_matrix(validate_scene(dict(scene, objects=[{"id": "t", "type": "box", "size": [1, 1, 1]}]))["camera"],
                        scene["output"]["canvas_mm"])
    np.testing.assert_allclose(cam["R"][1], [-math.sin(0.2), 0.0, math.cos(0.2)], atol=1e-12)
    h = math.sqrt(0.5)
    nodes[1] = {"name": "cam", "camera": 0, "translation": [0.0, 5.0, 0.0], "rotation": [-h, 0.0, 0.0, h]}
    scene, _ = G.import_gltf_scene(write_gltf(tmp_path, gltf_doc([TRI], nodes, extra=extra), "down.gltf"))
    np.testing.assert_allclose(np.subtract(scene["camera"]["target"], scene["camera"]["position"]), [0, 0, -1], atol=1e-15)
    cam = camera_matrix(validate_scene(dict(scene, objects=[{"id": "t", "type": "box", "size": [1, 1, 1]}]))["camera"],
                        scene["output"]["canvas_mm"])
    np.testing.assert_allclose(cam["R"][1], [0.0, 1.0, 0.0], atol=1e-12)        # glTF up (0, 0, -1) -> castplane +y
    extra["cameras"][0] = {"type": "orthographic", "orthographic": {}}
    with pytest.raises(SceneError) as info:
        G.import_gltf_scene(write_gltf(tmp_path, gltf_doc([TRI], nodes, extra=extra), "ortho.gltf"))
    assert info.value.field == "cameras[0].type"


def test_import_extras_primitive_scale_and_errors(tmp_path):
    params = {"castplane": {"type": "box", "size": [1.0, 2.0, 0.5]}}
    nodes = [{"name": "crate", "scale": [2.0, 2.0, 2.0], "translation": [1.0, 0.0, -2.0], "extras": params,
              "mesh": 0}]
    scene, _ = G.import_gltf_scene(write_gltf(tmp_path, gltf_doc([TRI], nodes)))
    assert scene["objects"] == [{"id": "crate", "type": "box", "size": [2.0, 4.0, 1.0],
                                 "transform": {"position": [1.0, 2.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]}}]
    # the mesh attached to a primitive node is ignored by the loader
    with pytest.raises(SceneError):
        load_mesh_file(write_gltf(tmp_path, gltf_doc([TRI], nodes), "p.gltf"))
    nodes[0]["scale"] = [1.0, 2.0, 1.0]
    with pytest.raises(SceneError) as info:
        G.import_gltf_scene(write_gltf(tmp_path, gltf_doc([TRI], nodes)))
    assert info.value.field == "nodes[0].scale"
    nodes[0]["scale"] = [-1.0, 1.0, 1.0]
    with pytest.raises(SceneError) as info:
        G.import_gltf_scene(write_gltf(tmp_path, gltf_doc([TRI], nodes)))
    assert info.value.field == "nodes[0].scale" and "mirrored" in info.value.message
    del nodes[0]["scale"]
    nodes[0]["matrix"] = [-1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
    with pytest.raises(SceneError) as info:
        G.import_gltf_scene(write_gltf(tmp_path, gltf_doc([TRI], nodes)))
    assert info.value.field == "nodes[0].matrix"
    # invalid extras parameters are reported at their glTF JSON path, with and without a camera in the file
    for scale in (None, [2.0, 2.0, 2.0]):
        bad = [{"name": "b", "extras": {"castplane": {"type": "box", "size": [1.0, -1.0, 1.0]}}}, {"mesh": 0}]
        if scale:
            bad[0]["scale"] = scale
        for cam in (False, True):
            extra = {"cameras": [{"type": "perspective", "perspective": {"yfov": 0.6}}]} if cam else None
            nodes_b = bad + ([{"camera": 0, "translation": [0.0, 1.0, 8.0]}] if cam else [])
            with pytest.raises(SceneError) as info:
                G.import_gltf_scene(write_gltf(tmp_path, gltf_doc([TRI], nodes_b, extra=extra), "bad.gltf"))
            assert info.value.field == "nodes[0].extras.castplane.size[1]"
    bad = [{"name": "b", "scale": [2.5, 2.5, 2.5], "extras": {"castplane": {"type": "box", "size": ["a", 1, 1]}}}]
    with pytest.raises(SceneError) as info:
        G.import_gltf_scene(write_gltf(tmp_path, gltf_doc([TRI], bad + [{"mesh": 0}]), "bad.gltf"))
    assert info.value.field == "nodes[0].extras.castplane.size[0]"
    # a tilted cylinder: Z up = node local +Y, rotation via euler_zyx(A·R·A^T)
    s, c = math.sin(math.radians(10.0)), math.cos(math.radians(10.0))
    nodes = [{"name": "p", "rotation": [s, 0.0, 0.0, c], "extras": {"castplane": {"type": "cylinder", "radius": 0.2,
                                                                                     "height": 1.0}}}]
    scene, _ = G.import_gltf_scene(write_gltf(tmp_path, gltf_doc([TRI], nodes + [{"mesh": 0}])))
    np.testing.assert_allclose(scene["objects"][0]["transform"]["rotation_deg"], [20.0, 0.0, 0.0], atol=1e-12)


def test_euler_zyx_round_trip_and_gimbal():
    from castplane.transform import euler_zyx_matrix
    for angles in ([10.0, 20.0, 30.0], [-40.0, 5.0, 170.0], [0.0, 0.0, 0.0]):
        got = [math.degrees(a) for a in G.euler_zyx(euler_zyx_matrix(angles))]
        np.testing.assert_allclose(got, angles, atol=1e-12)
    got = [math.degrees(a) for a in G.euler_zyx(euler_zyx_matrix([0.0, 90.0, 25.0]))]
    assert got[0] == 0.0 and got[1] == pytest.approx(90.0) and got[2] == pytest.approx(25.0)


# --------------------------------------------------------------------------- CLI
def run_import(tmp_path, *argv, out="scene.json"):
    target = tmp_path / out
    code = main(["import", *[str(a) for a in argv], "-o", str(target)])
    return code, (json.loads(target.read_text(encoding="utf-8")) if target.exists() else None)


def test_cli_import_obj_writes_a_relative_reference_that_reloads(tmp_path, capsys):
    code, scene = run_import(tmp_path, FIX / "box_split.obj")
    assert code == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out.strip() == str(tmp_path / "scene.json")
    assert "note: IMPORT_NO_CAMERA_DEFAULT []" in captured.err and "note: IMPORT_NO_LIGHT_DEFAULT []" in captured.err
    assert scene["objects"] == [{"id": "box_split", "type": "mesh",
                                 "path": os.path.relpath(FIX / "box_split.obj", tmp_path).replace(os.sep, "/")}]
    assert [n["code"] for n in scene["meta"]["import_notes"]] == ["IMPORT_NO_CAMERA_DEFAULT", "IMPORT_NO_LIGHT_DEFAULT"]
    assert main(["validate", str(tmp_path / "scene.json")]) == EXIT_OK
    assert main(["render", str(tmp_path / "scene.json"), "-o", str(tmp_path / "out"), "-q"]) == EXIT_OK
    doc = json.loads((tmp_path / "out" / "scene.json").read_text())
    assert doc["warnings"] == [] and len(doc["edges"]) == 12
    text = (tmp_path / "scene.json").read_text(encoding="utf-8")
    assert text == json.dumps(scene, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def test_cli_import_is_deterministic_and_quiet(tmp_path, capsys):
    run_import(tmp_path, FIX / "import_scene.gltf", "--light", "Lamp", "-q", out="a.json")
    run_import(tmp_path, FIX / "import_scene.gltf", "--light", "Lamp", "-q", out="b.json")
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()
    assert capsys.readouterr() == ("", "")


def test_cli_import_gltf_with_two_lights(tmp_path, capsys):
    code, scene = run_import(tmp_path, FIX / "import_scene.gltf")
    err = capsys.readouterr().err
    # M6 lifted the one-light rule: the two-light import is written and renders with both lights
    assert code == EXIT_OK and [lt["id"] for lt in scene["lights"]] == ["Lamp", "Spot"]
    assert "note: IMPORT_SPOT_AS_POINT ['Spot']" in err
    assert main(["render", str(tmp_path / "scene.json"), "-o", str(tmp_path / "two"), "-q"]) == EXIT_OK
    svg = next((tmp_path / "two").glob("*.svg")).read_text(encoding="utf-8")
    assert all(f'id="{g}"' in svg for g in ("cast_shadow.Lamp", "cast_shadow.Spot", "cast_shadow.umbra"))
    code, scene = run_import(tmp_path, FIX / "import_scene.gltf", "--light", "Spot", out="spot.json")
    assert code == EXIT_OK and scene["lights"] == [{"id": "Spot", "type": "point", "position": [-2.0, 0.0, 3.0]}]
    assert "note: IMPORT_SPOT_AS_POINT ['Spot']" in capsys.readouterr().err
    assert scene["objects"][1]["node"] == "Cube" and scene["objects"][0]["node"] == 3
    assert main(["validate", str(tmp_path / "spot.json"), "-q"]) == EXIT_OK


def test_cli_import_mesh_options(tmp_path):
    code, scene = run_import(tmp_path, FIX / "box_split_y.obj", "--inline", "--up", "y", "--id", "crate",
                             "--scale", "2", "--weld", "1e-5", "--smooth-angle", "45")
    assert code == EXIT_OK
    (o,) = scene["objects"]
    assert o["id"] == "crate" and o["up"] == "y" and o["scale"] == 2.0 and o["weld_tolerance"] == 1e-5
    assert o["smooth_angle_deg"] == 45.0 and o["data"] == load_mesh_file(FIX / "box_split_y.obj") and "path" not in o
    # the default camera sees the Z-up, scaled box: bbox x/y in [-1, 1], z in [0, 2] -> e = 2
    assert scene["camera"]["target"] == [0.0, 0.0, 1.0] and scene["camera"]["position"] == [0.0, -5.0, 1.4]
    validate_scene(scene)
    code, scene = run_import(tmp_path, FIX / "features.obj", "--node", "6", out="n.json")
    assert code == EXIT_OK and scene["objects"][0]["node"] == 6 and scene["objects"][0]["id"] == "features"
    code, scene = run_import(tmp_path, FIX / "features.obj", "--node", "walls", out="w.json")
    assert code == EXIT_OK and scene["objects"][0]["node"] == "walls"


def test_cli_import_into_appends_and_copies_blocks_verbatim(tmp_path, capsys):
    into = EXAMPLES / "basic.json"
    # an explicit --id that is already an object id of SCENE is refused (never silently renamed)
    code, scene = run_import(tmp_path, FIX / "box_split.obj", "--into", into, "--id", "crate")
    assert code == EXIT_INPUT and scene is None and "error: --id:" in capsys.readouterr().err
    (tmp_path / "crate.obj").write_bytes((FIX / "box_split.obj").read_bytes())
    code, scene = run_import(tmp_path, tmp_path / "crate.obj", "--into", into)
    assert code == EXIT_OK
    raw = json.loads(into.read_text(encoding="utf-8"))
    for key in ("version", "units", "up", "lights", "receivers", "camera", "output"):
        assert scene[key] == raw[key]
    assert scene["camera"]["focal_length_mm"] == 35 and isinstance(scene["camera"]["focal_length_mm"], int)
    assert scene["objects"][:2] == raw["objects"]
    assert scene["objects"][2]["id"] == "crate_2"                     # deduplicated against the existing ids
    assert scene["meta"] == {"import_notes": []}
    assert main(["validate", str(tmp_path / "scene.json"), "-q"]) == EXIT_OK


def test_cli_import_into_elsewhere_rebases_scene_mesh_paths(tmp_path):
    into = EXAMPLES / "mesh_demo.json"
    raw = json.loads(into.read_text(encoding="utf-8"))
    (tmp_path / "sub").mkdir()
    code, scene = run_import(tmp_path, FIX / "box.glb", "--into", into, "-q", out="sub/x.json")
    assert code == EXIT_OK
    for mine, theirs in zip(scene["objects"], raw["objects"]):
        if theirs.get("type") == "mesh" and "path" in theirs:
            assert mine["path"] == os.path.relpath(EXAMPLES / theirs["path"], tmp_path / "sub").replace(os.sep, "/")
            assert {k: v for k, v in mine.items() if k != "path"} == {k: v for k, v in theirs.items() if k != "path"}
        else:
            assert mine == theirs
    assert main(["validate", str(tmp_path / "sub" / "x.json"), "-q"]) == EXIT_OK
    # written next to SCENE, the paths stay verbatim
    out = tmp_path / "copy"
    out.mkdir()
    (out / "scene.json").write_text(into.read_text(encoding="utf-8"), encoding="utf-8")
    (out / "meshes").mkdir()
    (out / "meshes" / "house.obj").write_bytes((EXAMPLES / "meshes" / "house.obj").read_bytes())
    assert main(["import", str(FIX / "box.glb"), "--into", str(out / "scene.json"), "-o", str(out / "y.json"),
                 "-q"]) == EXIT_OK
    written = json.loads((out / "y.json").read_text(encoding="utf-8"))
    assert written["objects"][:len(raw["objects"])] == raw["objects"]
    assert main(["validate", str(out / "y.json"), "-q"]) == EXIT_OK


def test_cli_import_ids_avoid_the_ground_receiver(tmp_path, capsys):
    (tmp_path / "ground.obj").write_bytes((FIX / "box_split.obj").read_bytes())
    code, scene = run_import(tmp_path, tmp_path / "ground.obj", "-q")
    assert code == EXIT_OK and [o["id"] for o in scene["objects"]] == ["ground_2"]
    assert [r["id"] for r in scene["receivers"]] == ["ground"]
    code, scene = run_import(tmp_path, FIX / "box_split.obj", "--id", "ground", out="g.json")
    assert code == EXIT_INPUT and scene is None and "error: --id:" in capsys.readouterr().err


def test_cli_import_stdout_without_output(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(FIX)
    assert main(["import", "box_split.obj", "-q"]) == EXIT_OK
    out = capsys.readouterr().out
    assert json.loads(out)["objects"][0]["path"] == "box_split.obj"


def test_cli_import_exit_codes(tmp_path, capsys):
    assert main(["import", str(tmp_path / "missing.obj"), "-o", str(tmp_path / "s.json")]) == EXIT_IO
    assert main(["import", str(FIX / "box_split.obj"), "-o", str(tmp_path / "no" / "dir" / "s.json")]) == EXIT_IO
    assert main(["import", str(FIX / "box.gltf"), "--up", "y", "-o", str(tmp_path / "s.json")]) == EXIT_INPUT
    assert "error: --up:" in capsys.readouterr().err
    assert main(["import", str(FIX / "box_split.obj"), "--camera", "c", "-o", str(tmp_path / "s.json")]) == EXIT_INPUT
    assert main(["import", str(FIX / "import_scene.gltf"), "--id", "x", "-o", str(tmp_path / "s.json")]) == EXIT_INPUT
    bad = write_gltf(tmp_path, dict(gltf_doc([TRI], [{"mesh": 0, "skin": 0}])), "skin.gltf")
    assert main(["import", bad, "-o", str(tmp_path / "s.json")]) == EXIT_INPUT
    assert "error: nodes[0].skin:" in capsys.readouterr().err
    (tmp_path / "part.step").write_text("ISO-10303-21;\n")
    assert main(["import", str(tmp_path / "part.step"), "-o", str(tmp_path / "s.json")]) == EXIT_INPUT
    # a glTF without any triangle (points / lines only; no camera) is a SceneError, not a traceback
    lines = write_gltf(tmp_path, gltf_doc([TRI], [{"mesh": 0, "name": "m"}], mode=1), "lines.gltf")
    capsys.readouterr()
    assert main(["import", lines, "-o", str(tmp_path / "s.json")]) == EXIT_INPUT
    assert "error: meshes: the file holds no triangle" in capsys.readouterr().err
    with pytest.raises(SceneError) as info:
        G.import_gltf_scene(lines)
    assert info.value.field == "meshes"
    with pytest.raises(SystemExit) as info:
        main(["import", str(FIX / "box_split.obj"), "--up", "x"])
    assert info.value.code == 2
    assert not (tmp_path / "s.json").exists()


def test_cli_render_validate_info_stages_load_mesh_paths_relative_to_the_scene(tmp_path, capsys):
    scene = mesh_scene(os.path.relpath(FIX / "box_split.obj", tmp_path))
    p = tmp_path / "m.json"
    p.write_text(json.dumps(scene), encoding="utf-8")
    assert main(["validate", str(p)]) == EXIT_OK
    assert "ok: 1 object(s)" in capsys.readouterr().out
    assert main(["info", str(p)]) == EXIT_OK
    assert main(["stages", str(p), "-o", str(tmp_path / "st.json"), "-q"]) == EXIT_OK
    assert main(["render", str(p), "-o", str(tmp_path / "out"), "-q"]) == EXIT_OK
    capsys.readouterr()
    scene["objects"][0]["path"] = "nope.obj"
    p.write_text(json.dumps(scene), encoding="utf-8")
    assert main(["validate", str(p)]) == EXIT_IO
    scene["objects"][0]["path"] = os.path.relpath(FIX / "features.obj", tmp_path)
    scene["objects"][0]["node"] = "zzz"
    p.write_text(json.dumps(scene), encoding="utf-8")
    assert main(["validate", str(p)]) == EXIT_INPUT
    assert "error: objects[0].node:" in capsys.readouterr().err


def test_cli_entry_point_runs_import(tmp_path):
    out = tmp_path / "s.json"
    proc = subprocess.run([sys.executable, "-m", "castplane.cli", "import", str(FIX / "box.glb"), "-o", str(out), "-q"],
                          cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(out.read_text())["objects"][0]["node"] == "Box"


def test_fixture_generator_is_in_sync():
    proc = subprocess.run([sys.executable, str(ROOT / "tools" / "make_mesh_fixtures.py"), "--check"], cwd=ROOT,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_notes_never_enter_document_warnings(tmp_path):
    scene, notes = G.import_gltf_scene(FIX / "import_scene.gltf", light="Spot")
    assert notes
    doc = render(validate_scene(expand_scene(scene, FIX)[0]))["geometry"]
    assert not {w["code"] for w in doc["warnings"]} & set(IMPORT_NOTE_CODES)
    assert cio._note("IMPORT_SPOT_AS_POINT", ["x"])["ids"] == ["x"]
    with pytest.raises(ValueError):
        cio._note("MESH_NON_MANIFOLD")


# --------------------------------------------------------------------------- review fixes (loaders group)
def _tri_doc(**extra):
    """One float VEC3 triangle (+ uint16 indices) in a data-URI buffer: the base of the mutations."""
    return gltf_doc([TRI], [{"mesh": 0, "name": "n0"}], indices=[[0, 1, 2]], extra=extra)


def _cam_light_doc():
    """``_tri_doc`` plus a perspective camera node and a point light node."""
    d = _tri_doc()
    d["nodes"] += [{"camera": 0, "translation": [0.0, 1.0, 5.0]},
                   {"extensions": {"KHR_lights_punctual": {"light": 0}}, "translation": [0.0, 3.0, 0.0]}]
    d["cameras"] = [{"type": "perspective", "perspective": {"yfov": 0.6, "aspectRatio": 1.5, "znear": 0.1}}]
    d["extensions"] = {"KHR_lights_punctual": {"lights": [{"type": "point"}]}}
    return d


def _set(path, value):
    """A mutation ``doc[path...] = value`` (a list of keys / indices)."""
    def f(d):
        target = d
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return f


# m5-loaders#0: wrongly typed JSON values are SceneErrors at their glTF JSON path, never tracebacks
@pytest.mark.parametrize("mutate, field", [
    (_set(["nodes", 0, "children"], 1), "nodes[0].children"),
    (_set(["nodes", 0, "children"], None), "nodes[0].children"),
    (_set(["nodes", 0, "matrix"], ["a"] * 16), "nodes[0].matrix"),
    (_set(["nodes", 0, "matrix"], [float("nan")] + [0.0] * 15), "nodes[0].matrix"),
    (_set(["nodes", 0, "translation"], [1.0, 2.0]), "nodes[0].translation"),
    (_set(["nodes", 0, "translation"], "abc"), "nodes[0].translation"),
    (_set(["nodes", 0, "rotation"], [0.0, 0.0, 1.0]), "nodes[0].rotation"),
    (_set(["nodes", 0, "rotation"], [0.0, 0.0, 0.0, 1.0, 0.0]), "nodes[0].rotation"),
    (_set(["nodes", 0, "rotation"], [[0.0], 0.0, 0.0, 1.0]), "nodes[0].rotation"),
    (_set(["nodes", 0, "rotation"], None), "nodes[0].rotation"),
    (_set(["nodes", 0, "scale"], [1.0, 1.0]), "nodes[0].scale"),
    (_set(["nodes", 0, "scale"], "s"), "nodes[0].scale"),
    (_set(["scenes"], [{"nodes": 0}]), "scenes[0].nodes"),
    (_set(["meshes", 0, "primitives"], 3), "meshes[0].primitives"),
    (_set(["meshes", 0, "primitives"], None), "meshes[0].primitives"),
    (_set(["meshes", 0, "primitives", 0, "mode"], 4.5), "meshes[0].primitives[0].mode"),
    (_set(["accessors", 0, "componentType"], [5126]), "accessors[0].componentType"),
    (_set(["buffers", 0, "uri"], "a\0b.bin"), "buffers[0].uri"),
])
def test_gltf_wrongly_typed_values_are_scene_errors(tmp_path, mutate, field):
    d = _tri_doc()
    mutate(d)
    _bad(d, field, tmp_path)
    _bad(d, field, tmp_path, G.import_gltf_scene)


@pytest.mark.parametrize("mutate, field", [
    (_set(["cameras", 0, "perspective", "yfov"], "x"), "cameras[0].perspective.yfov"),
    (_set(["cameras", 0, "perspective", "yfov"], None), "cameras[0].perspective.yfov"),
    (_set(["cameras", 0, "perspective", "yfov"], [0.6]), "cameras[0].perspective.yfov"),
    (_set(["cameras", 0, "perspective", "aspectRatio"], "x"), "cameras[0].perspective.aspectRatio"),
    (_set(["cameras", 0, "perspective", "aspectRatio"], None), "cameras[0].perspective.aspectRatio"),
    (_set(["cameras", 0, "perspective", "znear"], "x"), "cameras[0].perspective.znear"),
    (_set(["extensions"], []), "extensions"),
    (_set(["extensions", "KHR_lights_punctual"], []), "extensions.KHR_lights_punctual"),
    (_set(["extensions", "KHR_lights_punctual", "lights"], {"0": {"type": "point"}}),
     "extensions.KHR_lights_punctual.lights"),
    (_set(["extensions", "KHR_lights_punctual", "lights"], [3]), "extensions.KHR_lights_punctual.lights[0]"),
    (_set(["nodes", 2, "extensions", "KHR_lights_punctual", "light"], True),
     "nodes[2].extensions.KHR_lights_punctual.light"),
])
def test_gltf_wrongly_typed_camera_and_light_values_are_scene_errors(tmp_path, mutate, field):
    d = _cam_light_doc()
    G.import_gltf_scene(write_gltf(tmp_path, d))                  # the unmutated document imports
    mutate(d)
    _bad(d, field, tmp_path, G.import_gltf_scene)


def test_gltf_read_accessor_rejects_unhashable_type_values():
    d = _tri_doc()
    for key, value in (("type", ["VEC3"]), ("componentType", [5126]), ("componentType", 5126.0)):
        bad = copy.deepcopy(d)
        bad["accessors"][0][key] = value
        with pytest.raises(SceneError) as info:
            G.read_accessor(bad, _buffers(bad), 0)
        assert info.value.field == f"accessors[0].{key}"


def test_gltf_malformed_values_exit_2_through_the_cli(tmp_path, capsys):
    d = _tri_doc()
    d["nodes"][0]["rotation"] = [0.0, 0.0, 1.0]
    p = write_gltf(tmp_path, d, "rot.gltf")
    assert main(["import", p, "-q", "-o", str(tmp_path / "s.json")]) == EXIT_INPUT
    assert "error: nodes[0].rotation:" in capsys.readouterr().err
    scene = mesh_scene(p)                                         # the same file behind a scene's mesh path
    (tmp_path / "scene.json").write_text(json.dumps(scene), encoding="utf-8")
    assert main(["validate", str(tmp_path / "scene.json")]) == EXIT_INPUT
    assert "objects[0].path: nodes[0].rotation:" in capsys.readouterr().err


def test_gltf_safety_net_turns_untyped_failures_into_scene_errors(monkeypatch):
    """Any TypeError / ValueError / ... a per-field check misses still leaves as SceneError("")."""
    doc = _tri_doc()
    monkeypatch.setattr(G, "_local_matrix", lambda node, k: (_ for _ in ()).throw(TypeError("boom")))
    with pytest.raises(SceneError) as info:
        G.gltf_raw(doc, _buffers(doc))
    assert info.value.field == "" and "malformed glTF: TypeError: boom" in info.value.message


# m5-loaders#1: bufferView / accessor byteOffset, byteStride and byteLength are non-negative integers
@pytest.mark.parametrize("mutate, field", [
    (_set(["bufferViews", 1, "byteOffset"], -36), "bufferViews[1].byteOffset"),
    (_set(["bufferViews", 0, "byteOffset"], "0"), "bufferViews[0].byteOffset"),
    (_set(["bufferViews", 0, "byteOffset"], 0.5), "bufferViews[0].byteOffset"),
    (_set(["bufferViews", 0, "byteLength"], -1), "bufferViews[0].byteLength"),
    (_set(["bufferViews", 0, "byteStride"], "12"), "bufferViews[0].byteStride"),
    (_set(["bufferViews", 0, "byteStride"], 12.5), "bufferViews[0].byteStride"),
    (_set(["bufferViews", 0, "byteStride"], -12), "bufferViews[0].byteStride"),
    (_set(["bufferViews", 0, "buffer"], True), "bufferViews[0].buffer"),
    (_set(["accessors", 0, "byteOffset"], "0"), "accessors[0].byteOffset"),
    (_set(["accessors", 0, "byteOffset"], -12), "accessors[0].byteOffset"),
    # a negative accessor offset that stays inside the buffer used to read the neighbouring view
    (_set(["accessors", 1, "byteOffset"], -36), "accessors[1].byteOffset"),
])
def test_gltf_accessor_offsets_and_strides_are_checked(tmp_path, mutate, field):
    d = _tri_doc()
    mutate(d)
    _bad(d, field, tmp_path)


# m5-loaders#2: an accessor without bufferView (all zeros) is capped before any allocation
@pytest.mark.parametrize("acc, count", [(0, 10 ** 12), (0, 10 ** 30), (1, 10 ** 12), (0, G.MAX_ZERO_ACCESSOR_COUNT + 1)])
def test_gltf_zero_accessor_count_is_capped(tmp_path, acc, count):
    d = _tri_doc()
    del d["accessors"][acc]["bufferView"]
    d["accessors"][acc]["count"] = count
    err = _bad(d, f"accessors[{acc}].count", tmp_path)
    assert "without a bufferView" in err.message


def test_gltf_small_zero_accessor_still_reads_as_zeros():
    """contract §5.2.8 implementation note (8): an accessor without bufferView is zeros."""
    d = _tri_doc()
    del d["accessors"][0]["bufferView"]
    a = G.read_accessor(d, _buffers(d), 0)
    assert a.shape == (3, 3) and not a.any()
    d["accessors"][0]["count"] = G.MAX_ZERO_ACCESSOR_COUNT
    assert G.read_accessor(d, _buffers(d), 0).shape == (G.MAX_ZERO_ACCESSOR_COUNT, 3)


# m5-loaders#3: external buffers stay inside the glTF's directory and are read up to byteLength only
def _external(tmp_path, uri, length=36 + 6 + 2):
    d = _tri_doc()
    blob = _buffers(d)[0]
    sub = tmp_path / "sub"
    sub.mkdir(exist_ok=True)
    (sub / "tri.bin").write_bytes(blob + b"\xff" * 1000)          # longer than byteLength
    (tmp_path / "secret.bin").write_bytes(blob)
    d["buffers"] = [{"byteLength": length, "uri": uri}]
    return d, sub


@pytest.mark.parametrize("uri", ["../secret.bin", "%2e%2e/secret.bin", "sub/../../secret.bin", "/etc/hostname",
                                 "file:///etc/hostname", "http://example.com/x.bin", ".", "", "/dev/zero"])
def test_gltf_external_buffer_must_stay_inside_the_directory(tmp_path, uri):
    d, sub = _external(tmp_path, uri)
    p = write_gltf(sub, d)
    with pytest.raises(SceneError) as info:
        load_mesh_file(p)
    assert info.value.field == "buffers[0].uri", (info.value.field, info.value.message)


def test_gltf_external_buffer_is_read_up_to_byte_length(tmp_path):
    d, sub = _external(tmp_path, "tri.bin")
    p = write_gltf(sub, d)
    doc, buffers = G.read_gltf(p)
    assert len(buffers[0]) == 44                                  # the declared byteLength, not the 1044 file bytes
    assert load_mesh_file(p)["faces"] == [[0, 1, 2]]
    d["buffers"][0]["uri"] = "./sub%20dir/tri.bin"                # percent-decoded, still inside
    (sub / "sub dir").mkdir()
    (sub / "sub dir" / "tri.bin").write_bytes(_buffers(_tri_doc())[0])
    assert load_mesh_file(write_gltf(sub, d))["faces"] == [[0, 1, 2]]
    d["buffers"][0]["byteLength"] = 2000                          # longer than the file
    _bad(d, "buffers[0].byteLength", sub)


# m5-loaders#4: deep node chains need no recursion
def test_gltf_deep_node_chain_loads(tmp_path):
    n = 3000                                                      # node k has child k - 1; mesh on node 0
    nodes = [{"mesh": 0, "translation": [1.0, 0.0, 0.0]}] + \
            [{"children": [k - 1], "translation": [1.0, 0.0, 0.0]} for k in range(1, n)]
    d = gltf_doc([TRI], nodes, extra={"scenes": [{"nodes": [n - 1]}]})
    raw = load_mesh_file(write_gltf(tmp_path, d))
    assert raw["vertices"][0] == [float(n), 0.0, 0.0]
    d["nodes"][0]["children"] = [n - 1]                           # close the chain into a cycle
    del d["scenes"]
    _bad(d, "nodes[0].children", tmp_path)


# m5-loaders#5: importing / expanding N mesh nodes traverses the file once
def test_gltf_import_and_expand_traverse_the_file_once(tmp_path, monkeypatch):
    n = 40
    nodes = [{"mesh": 0, "name": f"m{k}" if k % 2 else "", "translation": [2.0 * k, 0.0, 0.0]} for k in range(n)]
    p = write_gltf(tmp_path, gltf_doc([TRI], nodes), "wide.gltf")
    calls = []
    real = G.node_world_matrices
    monkeypatch.setattr(G, "node_world_matrices", lambda doc: calls.append(1) or real(doc))
    parts, _ = G.import_gltf_parts(p, ref="wide.gltf")
    assert len(calls) == 1 and len(parts["objects"]) == n
    assert [o["node"] for o in parts["objects"][:3]] == [0, "m1", 2]
    scene = mesh_scene(p)
    scene["objects"] = parts["objects"]
    calls.clear()
    out, _ = expand_scene(scene, tmp_path)
    assert len(calls) == 1
    assert [o["data"] for o in out["objects"]] == [parts["raw"][o["id"]] for o in parts["objects"]]
    assert out["objects"][5]["data"]["vertices"][0] == [10.0, 0.0, 0.0]


def test_gltf_import_skips_meshes_below_an_emitted_mesh_through_any_node(tmp_path):
    """A mesh node under an emitted mesh node is part of that object's subtree, also when an
    ``extras.castplane`` primitive node or a plain node sits in between (imported once)."""
    nodes = [{"mesh": 0, "name": "top", "children": [1]},
             {"name": "prim", "extras": {"castplane": {"type": "box", "size": [1, 1, 1]}}, "children": [2]},
             {"name": "mid", "children": [3]},
             {"mesh": 0, "name": "deep"},
             {"mesh": 0, "name": "other"}]
    parts, _ = G.import_gltf_parts(write_gltf(tmp_path, gltf_doc([TRI], nodes)))
    assert [o["id"] for o in parts["objects"]] == ["top", "prim", "other"]
    assert len(parts["raw"]["top"]["faces"]) == 2                 # top + deep


# m5-loaders#6: pathological JSON is a SceneError("") for glTF files and scene files alike
@pytest.mark.parametrize("text", ['{"asset": {"version": "2.0"}, "x": ' + "[" * 200000 + "]" * 200000 + "}",
                                  '{"asset": {"version": "2.0"}, "x": 1' + "0" * 5000 + "}"])
def test_pathological_json_is_a_scene_error(tmp_path, capsys, text):
    p = tmp_path / "x.gltf"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(SceneError) as info:
        load_mesh_file(p)
    assert info.value.field == "" and "invalid glTF JSON" in info.value.message
    s = tmp_path / "scene.json"
    s.write_text(text, encoding="utf-8")
    with pytest.raises(SceneError) as info:
        load_expanded_scene(str(s))
    assert info.value.field == "" and "invalid JSON" in info.value.message
    assert main(["validate", str(s)]) == EXIT_INPUT
    assert main(["import", str(p), "-q", "-o", str(tmp_path / "o.json")]) == EXIT_INPUT


def test_scene_file_that_is_not_utf8_is_a_scene_error(tmp_path):
    s = tmp_path / "scene.json"
    s.write_bytes(b'{"version": "0.1", "x": "\xff"}')
    with pytest.raises(SceneError, match="invalid JSON"):
        load_scene(str(s))


# m5-loaders#7: trimesh-read faces are range-checked by the loader (field objects[i].path)
@pytest.mark.parametrize("bad", [99, -1])
def test_trimesh_face_index_out_of_range_is_a_loader_error(tmp_path, bad):
    pytest.importorskip("trimesh")
    p = tmp_path / "bad.ply"
    p.write_text("ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\n"
                 "element face 1\nproperty list uchar int vertex_indices\nend_header\n"
                 f"0 0 0\n1 0 0\n0 1 0\n3 0 1 {bad}\n", encoding="utf-8")
    with pytest.raises(SceneError, match=f"face index {bad} is out of range"):
        load_mesh_file(p)
    with pytest.raises(SceneError) as info:
        expand_scene(mesh_scene(p))
    assert info.value.field == "objects[0].path"
