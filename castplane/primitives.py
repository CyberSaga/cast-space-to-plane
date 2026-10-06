"""Object records: mesh in world coordinates + analytic parameters (spec §4, §5.6; contract §2.4).

``build_object(obj)`` turns one validated ``objects[i]`` dict into::

    {
      "id": str, "type": str,
      "mesh": mesh dict in WORLD coordinates (contract §2.4),
      "point_names": ["<id>.v0", ...]      names of the mesh vertices (§3.1),
      "analytic": None | {kind, base, axis, e1, e2, radius, height, centre},
      "bbox": (min_xyz, max_xyz),
      "face_first": (k,) int      first vertex of every face (the ``lit`` representative point),
      "faces_padded": (k, Lmax) int   faces as a -1 padded table, "face_lens": (k,) int,
      "face_point_names": [[names of the face's vertices], ...],
      "edge_templates": [{object, from, to, silhouette: False, back: False, visibility: "visible",
                          segment: None}, ...]   one §3.1 edge record per mesh edge, camera / light free,
      "world_lists": [[x, y, z], ...]   the vertices as canonical Python lists (the ``world`` of the §3.1
                                        point records; shared by reference with every document),
    }

The ``face_*`` tables are derived from the mesh once here so that stage B can
project every polyhedral object of a scene in a few batched numpy calls (spec §8);
stage C copies the ``edge_templates`` and fills in the three camera / light dependent
keys (``silhouette``, ``back``, ``segment``) instead of building every record from scratch.

Curved primitives (cylinder, sphere, cone) carry an approximate 32-segment
mesh ONLY for bounding boxes / scene scale and the M5-shaped representation;
their shadows and outlines are computed analytically from ``analytic`` by the
curved-primitive track (contract §2.4/§2.6).
"""

from __future__ import annotations

import numpy as np

from .mesh import (box_mesh, cone_mesh, cylinder_mesh, mesh_bbox, prism_mesh,
                   sphere_mesh, transform_mesh)
from .transform import transform_frame

CURVED_TYPES = ("cylinder", "sphere", "cone")


def local_mesh(obj: dict) -> dict:
    """Mesh of a validated object in its local frame (contract §2.1)."""
    typ = obj["type"]
    if typ == "box":
        return box_mesh(obj["size"])
    if typ == "prism":
        return prism_mesh(obj["polygon"], obj["height"])
    if typ == "cylinder":
        return cylinder_mesh(obj["radius"], obj["height"])
    if typ == "cone":
        return cone_mesh(obj["radius"], obj["height"])
    if typ == "sphere":
        return sphere_mesh(obj["radius"])
    raise ValueError(f"unknown object type {typ!r}")


def analytic_record(obj: dict, R, position):
    """``{kind, base, axis, e1, e2, radius, height, centre}`` in world coords for curved types (contract §2.4).

    ``(e1, e2, axis)`` is the rotated local frame; ``base`` is the world
    position of the local origin (base-circle centre); ``centre`` is the sphere
    centre (``base + r·axis``) or the mid-height point of cylinder / cone.
    For a sphere ``height`` is ``None``.
    """
    typ = obj["type"]
    if typ not in CURVED_TYPES:
        return None
    R = np.asarray(R, dtype=np.float64)
    base = np.asarray(position, dtype=np.float64)
    e1, e2, axis = R[:, 0].copy(), R[:, 1].copy(), R[:, 2].copy()
    radius = float(obj["radius"])
    if typ == "sphere":
        height = None
        centre = base + radius * axis
    else:
        height = float(obj["height"])
        centre = base + 0.5 * height * axis
    return {
        "kind": typ,
        "base": base,
        "axis": axis,
        "e1": e1,
        "e2": e2,
        "radius": radius,
        "height": height,
        "centre": centre,
    }


def face_tables(mesh: dict) -> dict:
    """``{face_first, faces_padded, face_lens}`` of a mesh (see the module docstring)."""
    faces = mesh["faces"]
    lens = np.array([len(f) for f in faces], dtype=np.int64).reshape(-1)
    width = int(lens.max()) if lens.shape[0] else 0
    padded = np.full((lens.shape[0], width), -1, dtype=np.int64)
    for k, f in enumerate(faces):
        padded[k, :len(f)] = f
    first = padded[:, 0].copy() if width else np.zeros(0, dtype=np.int64)
    return {"face_first": first, "faces_padded": padded, "face_lens": lens}


def build_object(obj: dict) -> dict:
    """Build the object record of a validated ``objects[i]`` dict with the world transform applied."""
    R, position = transform_frame(obj.get("transform"))
    mesh = transform_mesh(local_mesh(obj), R, position)
    names = [f"{obj['id']}.{n}" for n in mesh["vertex_names"]]
    rec = {
        "id": obj["id"],
        "type": obj["type"],
        "mesh": mesh,
        "point_names": names,
        "analytic": analytic_record(obj, R, position),
        "bbox": mesh_bbox(mesh),
    }
    rec.update(face_tables(mesh))
    rec["face_point_names"] = [[names[int(v)] for v in f] for f in mesh["faces"]]
    rec["world_lists"] = (mesh["vertices"] + 0.0).tolist()
    rec["edge_templates"] = [{"object": obj["id"], "from": names[i], "to": names[j], "silhouette": False,
                              "back": False, "visibility": "visible", "segment": None}
                             for i, j in mesh["edges"].tolist()]
    return rec
