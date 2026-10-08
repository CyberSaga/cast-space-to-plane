"""Mesh builders and topology (contract §2.4)."""

import numpy as np
import pytest

from castplane.mesh import (box_mesh, cone_mesh, cylinder_mesh, euler_characteristic, mesh_from_faces,
                            prism_mesh, sphere_mesh)
from castplane.primitives import build_object

L_SHAPE = [[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]]

ALL = {
    "box": lambda: box_mesh([1.0, 0.8, 0.6]),
    "prism": lambda: prism_mesh(L_SHAPE, 1.0),
    "cylinder": lambda: cylinder_mesh(0.3, 2.4),
    "cone": lambda: cone_mesh(0.5, 1.0),
    "sphere": lambda: sphere_mesh(0.5),
}


def face_centroid(mesh, f):
    return mesh["vertices"][f].mean(axis=0)


@pytest.mark.parametrize("name", sorted(ALL))
def test_topology_is_closed_manifold(name):
    m = ALL[name]()
    V, E, F = m["vertices"].shape[0], m["edges"].shape[0], len(m["faces"])
    assert euler_characteristic(m) == 2, (V, E, F)
    edges = m["edges"]
    assert np.all(edges[:, 0] < edges[:, 1])
    assert len({tuple(e) for e in edges.tolist()}) == E
    assert np.all(np.diff(edges[:, 0]) >= 0)  # lexicographically sorted
    assert m["edge_faces"].shape == (E, 2)
    assert m["face_normals"].shape == (F, 3)
    np.testing.assert_allclose(np.linalg.norm(m["face_normals"], axis=1), 1.0, atol=1e-12)
    assert m["vertex_names"] == [f"v{i}" for i in range(V)]
    # each edge appears in both of its faces as consecutive vertices
    for (i, j), (fa, fb) in zip(edges.tolist(), m["edge_faces"].tolist()):
        assert fa != fb
        for f in (fa, fb):
            face = m["faces"][f]
            ring = {tuple(sorted((face[k], face[(k + 1) % len(face)]))) for k in range(len(face))}
            assert (i, j) in ring
    # each face is planar
    for f, n in zip(m["faces"], m["face_normals"]):
        pts = m["vertices"][f]
        assert np.max(np.abs((pts - pts[0]) @ n)) < 1e-12


@pytest.mark.parametrize("name", ["box", "cylinder", "cone", "sphere"])
def test_normals_outward_convex(name):
    m = ALL[name]()
    centre = (m["vertices"].min(axis=0) + m["vertices"].max(axis=0)) / 2.0
    for f, n in zip(m["faces"], m["face_normals"]):
        assert n @ (face_centroid(m, f) - centre) > 0


def test_prism_normals_outward_concave():
    m = prism_mesh(L_SHAPE, 1.0)
    n = len(L_SHAPE)
    np.testing.assert_allclose(m["face_normals"][0], [0, 0, -1], atol=1e-12)
    np.testing.assert_allclose(m["face_normals"][1], [0, 0, 1], atol=1e-12)
    for i in range(n):
        a, b = np.array(L_SHAPE[i], float), np.array(L_SHAPE[(i + 1) % n], float)
        e = b - a
        expected = np.array([e[1], -e[0], 0.0]) / np.linalg.norm(e)
        np.testing.assert_allclose(m["face_normals"][2 + i], expected, atol=1e-12)


def test_local_extents(name=None):
    b = box_mesh([1.0, 0.8, 0.6])
    np.testing.assert_allclose(b["vertices"].min(axis=0), [-0.5, -0.4, 0.0])
    np.testing.assert_allclose(b["vertices"].max(axis=0), [0.5, 0.4, 0.6])
    s = sphere_mesh(0.5)
    np.testing.assert_allclose(s["vertices"].min(axis=0)[2], 0.0, atol=1e-12)
    np.testing.assert_allclose(s["vertices"].max(axis=0)[2], 1.0, atol=1e-12)
    assert s["vertices"].shape[0] == 2 + 32 * 15  # UV-sphere, 32 segments, 16 rings (15 vertex rings)
    c = cone_mesh(0.5, 1.0)
    assert c["vertices"].shape[0] == 33 and len(c["faces"]) == 33
    cy = cylinder_mesh(0.3, 2.4)
    assert cy["vertices"].shape[0] == 64 and len(cy["faces"]) == 34


def test_mesh_from_faces_rejects_open_mesh():
    with pytest.raises(ValueError):
        mesh_from_faces([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]])


def test_build_object_applies_world_transform_and_names():
    obj = {"id": "crate", "type": "box", "size": [1.0, 0.8, 0.6],
           "transform": {"position": [2.0, 4.0, 0.0], "rotation_deg": [0.0, 0.0, 30.0]}}
    rec = build_object(obj)
    m = rec["mesh"]
    c, s = np.cos(np.radians(30)), np.sin(np.radians(30))
    # v2 is local (+0.5, +0.4, 0)
    np.testing.assert_allclose(m["vertices"][2], [2.0 + 0.5 * c - 0.4 * s, 4.0 + 0.5 * s + 0.4 * c, 0.0], atol=1e-12)
    np.testing.assert_allclose(m["face_normals"][3], [c, s, 0.0], atol=1e-12)  # +x face rotated
    assert rec["point_names"][:2] == ["crate.v0", "crate.v1"]
    assert rec["analytic"] is None
    # contract §2.4: the derived tables are a required part of the record (the batched stage B reads them)
    for key in ("face_first", "faces_padded", "face_lens", "face_point_names", "edge_templates", "world_lists",
                "frame", "shape"):
        assert key in rec, key
    assert len(rec["edge_templates"]) == m["edges"].shape[0] and len(rec["world_lists"]) == m["vertices"].shape[0]
    assert rec["shape"] is obj and np.allclose(rec["frame"][1], [2.0, 4.0, 0.0])
    lo, hi = rec["bbox"]
    assert lo[2] == 0.0 and abs(hi[2] - 0.6) < 1e-12


def test_build_object_curved_analytic_record():
    obj = {"id": "pillar", "type": "cylinder", "radius": 0.3, "height": 2.4,
           "transform": {"position": [-1.5, 6.0, 0.0], "rotation_deg": [90.0, 0.0, 0.0]}}
    rec = build_object(obj)
    a = rec["analytic"]
    assert a["kind"] == "cylinder" and a["radius"] == 0.3 and a["height"] == 2.4
    np.testing.assert_allclose(a["base"], [-1.5, 6.0, 0.0])
    np.testing.assert_allclose(a["axis"], [0.0, -1.0, 0.0], atol=1e-12)  # local +Z rotated about X by 90°
    np.testing.assert_allclose(a["e1"], [1.0, 0.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(a["e2"], [0.0, 0.0, 1.0], atol=1e-12)
    np.testing.assert_allclose(a["centre"], [-1.5, 4.8, 0.0], atol=1e-12)
    sph = build_object({"id": "b", "type": "sphere", "radius": 0.5,
                        "transform": {"position": [1.0, 1.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]}})
    np.testing.assert_allclose(sph["analytic"]["centre"], [1.0, 1.0, 0.5])
    assert sph["analytic"]["height"] is None
