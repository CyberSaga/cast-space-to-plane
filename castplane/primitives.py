"""Object records: mesh in world coordinates + analytic parameters (spec §4, §5.6; contract §2.4).

``build_object(obj)`` turns one validated ``objects[i]`` dict into::

    {
      "id": str, "type": str,
      "mesh": mesh dict in WORLD coordinates (contract §2.4),
      "point_names": ["<id>.v0", ...]      names of the mesh vertices (§3.1),
      "analytic": None | {kind, base, axis, e1, e2, radius, height, centre},
      "bbox": (min_xyz, max_xyz),
      "frame": (R, position)        the world transform (contract §2.1) and
      "shape": the validated ``objects[i]`` dict, for :func:`point_inside_solid`,
      "face_first": (k,) int      first vertex of every face (the ``lit`` representative point),
      "faces_padded": (k, Lmax) int   faces as a -1 padded table, "face_lens": (k,) int,
      "face_point_names": [[names of the face's vertices], ...],
      "edge_templates": [{object, from, to, silhouette: False, back: False, visibility: "visible",
                          segment: None}, ...]   one §3.1 edge record per mesh edge, camera / light free,
      "world_lists": [[x, y, z], ...]   the vertices as canonical Python lists (the ``world`` of the §3.1
                                        point records; shared by reference with every document),
    }

The ``face_*`` tables, ``edge_templates`` and ``world_lists`` are derived from the
mesh once here and are a required part of the record: the batched stage B reads
them directly to project every polyhedral object of a scene in a few numpy calls
(spec §8; contract §2.4);
stage C copies the ``edge_templates`` and fills in the three camera / light dependent
keys (``silhouette``, ``back``, ``segment``) instead of building every record from scratch.

``mesh`` objects (M5, contract §5.2) carry the preprocessed mesh of :func:`prepared_mesh`
(welded, oriented, coplanar-merged; or the per-face fallback mesh) plus ``triangles``,
``fallback``, ``smooth_groups``, ``prep_warnings`` and ``mesh["edge_smooth"]``.

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
    if typ == "mesh":
        return prepared_mesh(obj)["mesh"]
    raise ValueError(f"unknown object type {typ!r}")


def prepared_mesh(obj: dict) -> dict:
    """The preprocessed local mesh of a validated ``mesh`` object (contract §5.2.3):
    ``{mesh, triangles, fallback, smooth_groups, warnings, scale_A}`` from
    :func:`castplane.meshprep.preprocess_mesh` (``scale`` applied, ``transform`` not)."""
    from .meshprep import preprocess_mesh
    mesh, triangles, fallback, groups, warnings, scale_A = preprocess_mesh(
        obj["data"], obj.get("scale", 1.0), obj.get("weld_tolerance", 1e-6), obj.get("smooth_angle_deg", 30.0),
        obj["id"], return_scale=True)
    return {"mesh": mesh, "triangles": triangles, "fallback": fallback, "smooth_groups": groups,
            "warnings": warnings, "scale_A": scale_A}


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
    prep = prepared_mesh(obj) if obj["type"] == "mesh" else None
    mesh = transform_mesh(local_mesh(obj) if prep is None else prep["mesh"], R, position)
    names = [f"{obj['id']}.{n}" for n in mesh["vertex_names"]]
    rec = {
        "id": obj["id"],
        "type": obj["type"],
        "mesh": mesh,
        "point_names": names,
        "analytic": analytic_record(obj, R, position),
        "bbox": mesh_bbox(mesh),
        "frame": (R, position),
        "shape": obj,
    }
    rec.update(face_tables(mesh))
    rec["face_point_names"] = [[names[int(v)] for v in f] for f in mesh["faces"]]
    rec["world_lists"] = (mesh["vertices"] + 0.0).tolist()
    rec["edge_templates"] = [{"object": obj["id"], "from": names[i], "to": names[j], "silhouette": False,
                              "back": False, "visibility": "visible", "segment": None}
                             for i, j in mesh["edges"].tolist()]
    # M5 (contract §5.2.3 step 8): every record carries ``fallback`` / ``prep_warnings`` and
    # ``mesh["edge_smooth"]`` (all False for the primitives); mesh records also ``triangles`` (the
    # original surface on the welded vertices), ``smooth_groups`` (per final face) and the mesh
    # length scale ``mesh_scale_A``; their edge templates carry the camera-free ``smooth`` key
    rec["fallback"] = False
    rec["prep_warnings"] = []
    if prep is None:
        mesh["edge_smooth"] = np.zeros(mesh["edges"].shape[0], dtype=bool)
    else:
        assert mesh["faces"], "a validated mesh object keeps at least one face (usable-face guard)"
        rec["triangles"] = prep["triangles"]
        rec["fallback"] = bool(prep["fallback"])
        rec["smooth_groups"] = list(prep["smooth_groups"])
        rec["prep_warnings"] = list(prep["warnings"])
        rec["mesh_scale_A"] = prep["scale_A"]
        for t, smooth in zip(rec["edge_templates"], mesh["edge_smooth"].tolist()):
            t["smooth"] = smooth
    return rec


def _point_in_polygon_margin(x: float, y: float, poly, margin: float) -> bool:
    """Even-odd point-in-polygon test of ``(x, y)`` against the simple polygon ``poly`` (list of
    ``[x, y]``), requiring the point to be farther than ``margin`` from every edge."""
    inside = False
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        # distance from the point to the closed edge segment
        t = ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy)
        t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
        if float(np.hypot(x - (x0 + t * dx), y - (y0 + t * dy))) <= margin:
            return False
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * dx / dy:
            inside = not inside
    return inside


def point_inside_solid(rec: dict, x, tol: float = 0.0) -> bool:
    """True when the world point ``x`` lies strictly inside a polyhedral object (box or prism) by
    more than ``tol`` (contract §2.5 / §2.9 ``LIGHT_INSIDE_OBJECT``); always False for curved
    objects, whose own test lives in :mod:`castplane.curved`.  The test is exact: the point is
    mapped into the object's local frame and compared with the local extents of §2.1."""
    if rec["analytic"] is not None:
        return False
    if rec["type"] == "mesh":
        # contract §5.2.3 step 8: generalised winding number of the original surface; a fallback
        # (non-manifold) mesh has no inside
        if rec.get("fallback"):
            return False
        from .meshprep import point_inside_mesh
        return point_inside_mesh(rec["mesh"]["vertices"], rec["triangles"], x, tol)
    R, position = rec["frame"]
    local = np.asarray(R, dtype=np.float64).T @ (np.asarray(x, dtype=np.float64) - position)
    shape = rec["shape"]
    if rec["type"] == "box":
        sx, sy, sz = shape["size"]
        return bool(abs(local[0]) < sx / 2 - tol and abs(local[1]) < sy / 2 - tol
                    and tol < local[2] < sz - tol)
    if rec["type"] == "prism":
        if not tol < local[2] < shape["height"] - tol:
            return False
        return _point_in_polygon_margin(float(local[0]), float(local[1]), shape["polygon"], tol)
    return False
