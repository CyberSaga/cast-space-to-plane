"""Object records: mesh in world coordinates + analytic parameters (spec §4, §5.6; contract §2.4).

``build_object(obj)`` turns one validated ``objects[i]`` dict into::

    {
      "id": str, "type": str,
      "mesh": mesh dict in WORLD coordinates (contract §2.4),
      "point_names": ["<id>.v0", ...]      names of the mesh vertices (§3.1),
      "analytic": None | {kind, base, axis, e1, e2, radius, height, centre},
      "bbox": (min_xyz, max_xyz),
    }

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


def build_object(obj: dict) -> dict:
    """Build the object record of a validated ``objects[i]`` dict with the world transform applied."""
    R, position = transform_frame(obj.get("transform"))
    mesh = transform_mesh(local_mesh(obj), R, position)
    names = [f"{obj['id']}.{n}" for n in mesh["vertex_names"]]
    return {
        "id": obj["id"],
        "type": obj["type"],
        "mesh": mesh,
        "point_names": names,
        "analytic": analytic_record(obj, R, position),
        "bbox": mesh_bbox(mesh),
    }
