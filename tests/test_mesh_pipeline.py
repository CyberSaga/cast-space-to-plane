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
