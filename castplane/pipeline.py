"""Three-stage pipeline (spec §3; contract §3).

* Stage A ``shadow_geometry(scene)``: camera independent (objects, meshes,
  bounding box; M1 adds lights, silhouettes and shadow loops).
* Stage B ``project_scene(scene, A, camera=None)``: camera matrices and every
  projected point / clipped segment in homogeneous 2-D form (vectorised).
* Stage C ``compose(scene, B)``: the §6.2 geometry document with the division
  by ``x̃3`` done last and canonical floats.
* ``render(scene, camera=None)`` runs all three and writes the SVG.

M0 scope: object edges (``silhouette`` is a ``False`` placeholder, ``back`` is
computed with the camera as light), points, horizon and vanishing points,
camera block and warnings.  ``shadows``, ``form_shadow`` and ``construction``
are present with empty content so the §6.2 shape is already complete.
"""

from __future__ import annotations

import numpy as np

from .camera import (camera_matrix, clip_segments_near, clip_segments_rect_h, divide,
                     horizon as camera_horizon, nu, project)
from .errors import make_warning, merge_warnings
from .homogeneous import TOL_DIR, scene_scale, to_homogeneous, tolerance
from .output.geometry_json import canonical
from .output.svg import write_svg
from .primitives import build_object
from .scene import validate_camera


def _lit(normals, points, L, tol):
    """``lit(f) <=> n_f · (l - w·p) > tol`` (spec §5.1) for many faces at once.

    TEMPORARY M0 helper: used only to compute the ``back`` flag of edges with the
    camera as the light (contract §2.10).  M1 replaces it with
    ``castplane.light.lit`` (owned by the light/shadow track); do not extend it.
    """
    L = np.asarray(L, dtype=np.float64)
    l, w = L[:3], L[3]
    return np.einsum("ij,ij->i", normals, l[None, :] - w * points) > tol


# ---------------------------------------------------------------------------
# stage A
# ---------------------------------------------------------------------------

def shadow_geometry(scene: dict) -> dict:
    """Stage A: camera-independent geometry (contract §3).  Never touches ``scene["camera"]``."""
    objects = [build_object(o) for o in scene["objects"]]
    vertices = np.concatenate([o["mesh"]["vertices"] for o in objects], axis=0)
    return {
        "objects": objects,
        "vertices": vertices,
        "bbox": (vertices.min(axis=0), vertices.max(axis=0)),
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# stage B
# ---------------------------------------------------------------------------

def _resolve_camera(scene: dict, camera):
    """Scene camera, or a validated override whose frame aspect matches the scene canvas."""
    if camera is None:
        return scene["camera"]
    cam = validate_camera(camera, "camera")
    canvas, frame = scene["output"]["canvas_mm"], cam["frame_mm"]
    if abs(canvas[0] / canvas[1] - frame[0] / frame[1]) > 1e-9:
        from .errors import SceneError
        raise SceneError("camera.frame_mm", "aspect ratio must equal output.canvas_mm aspect ratio")
    return cam


def _project_object(obj: dict, cam: dict, tol: float) -> dict:
    """Vectorised projection and clipping of one object's vertices and edges (contract §2.2)."""
    mesh = obj["mesh"]
    V4 = to_homogeneous(mesh["vertices"])
    nu_v = nu(cam, V4)
    x_h = project(cam, V4)                                   # (n, 3) homogeneous image points
    behind = nu_v < 0.0
    # back flag: both adjacent faces unlit with the camera as light (contract §2.10)
    faces = mesh["faces"]
    first = np.array([f[0] for f in faces], dtype=np.int64)
    face_lit = _lit(mesh["face_normals"], mesh["vertices"][first], np.append(cam["C"], 1.0), tol)
    ef = mesh["edge_faces"]
    back = ~face_lit[ef[:, 0]] & ~face_lit[ef[:, 1]]
    # drawing pipeline: near clip (4-D) -> P -> homogeneous rectangle clip -> divide (in compose)
    edges = mesh["edges"]
    A, B, keep = clip_segments_near(cam, V4[edges[:, 0]], V4[edges[:, 1]])
    A2, B2 = project(cam, A), project(cam, B)
    A3, B3, keep_rect = clip_segments_rect_h(A2, B2, cam["rect"])
    keep = keep & keep_rect
    return {
        "id": obj["id"],
        "type": obj["type"],
        "point_names": obj["point_names"],
        "world": mesh["vertices"],
        "image_h": x_h,
        "depth": x_h[:, 2],
        "behind": behind,
        "edges": edges,
        "back": back,
        "segments_h": np.stack([A3, B3], axis=1),           # (m, 2, 3) homogeneous endpoints
        "segment_keep": keep,
    }


def project_scene(scene: dict, A: dict, camera=None) -> dict:
    """Stage B: project stage-A geometry with the scene camera or an override (contract §3)."""
    cam_dict = _resolve_camera(scene, camera)
    canvas = scene["output"]["canvas_mm"]
    cam = camera_matrix(cam_dict, canvas)
    scale = scene_scale(A["vertices"], cam["C"])
    tol = tolerance(scale)
    warnings = list(cam["warnings"]) + list(A["warnings"])
    objects = []
    for obj in A["objects"]:
        rec = _project_object(obj, cam, tol)
        if bool(np.any(rec["behind"])):
            warnings.append(make_warning("POINT_BEHIND_CAMERA", [obj["id"]]))
        objects.append(rec)
    return {
        "camera": cam,
        "scene_scale": scale,
        "tol": tol,
        "objects": objects,
        "horizon": camera_horizon(cam, TOL_DIR),
        "shadows": [],
        "form_shadow": [],
        "construction": None,
        "warnings": merge_warnings(warnings),
    }


# ---------------------------------------------------------------------------
# stage C
# ---------------------------------------------------------------------------

def compose(scene: dict, B: dict) -> dict:
    """Stage C: the §6.2 geometry document (contract §3.1), canonical floats, sorted point names."""
    cam = B["camera"]
    points, edges = {}, []
    for rec in B["objects"]:
        # bulk conversion to Python floats (+ 0.0 canonicalises -0.0) keeps this loop cheap (§8 performance)
        uv = (divide(np.where(rec["behind"][:, None], np.array([0.0, 0.0, 1.0]), rec["image_h"])) + 0.0).tolist()
        world = (rec["world"] + 0.0).tolist()
        depth = (rec["depth"] + 0.0).tolist()
        behind = rec["behind"].tolist()
        for k, name in enumerate(rec["point_names"]):
            points[name] = {"world": world[k], "image": None if behind[k] else uv[k], "depth": depth[k]}
        seg_uv = (divide(np.where(rec["segment_keep"][:, None, None], rec["segments_h"],
                                  np.array([0.0, 0.0, 1.0]))) + 0.0).tolist()
        keep = rec["segment_keep"].tolist()
        back = rec["back"].tolist()
        names, oid = rec["point_names"], rec["id"]
        for e, (i, j) in enumerate(rec["edges"].tolist()):
            edges.append({
                "object": oid,
                "from": names[i],
                "to": names[j],
                "silhouette": False,      # placeholder until M1 (light silhouette)
                "back": back[e],
                "visibility": "visible",
                "segment": seg_uv[e] if keep[e] else None,
            })
    hz = B["horizon"]
    construction = B["construction"] or {
        "light_point": None, "light_point_at_infinity": None,
        "shadow_vp": None, "shadow_vp_at_infinity": None,
        "rays": [], "checks": [],
    }
    # points / edges are canonical by construction (bulk + 0.0 above); the small blocks go through canonical()
    doc = canonical({
        "canvas_mm": [float(c) for c in cam["canvas_mm"]],
        "camera": {
            "P": cam["P"].tolist(),
            "C": cam["C"].tolist(),
            "horizon_line": list(hz["line"]),
            "principal_point": [cam["u0"], cam["v0"]],
        },
        "shadows": list(B["shadows"]),
        "form_shadow": list(B["form_shadow"]),
        "construction": construction,
        "horizon": {
            "v_mm": hz["v_mm"],
            "line": list(hz["line"]),
            "segment": hz["segment"],
            "vanishing_points": dict(hz["vanishing_points"]),
        },
        "warnings": list(B["warnings"]),
    })
    doc["points"] = points
    doc["edges"] = edges
    return doc


def render(scene: dict, camera=None) -> dict:
    """Run stages A, B, C and write the SVG with the scene's layer subset (contract §3)."""
    A = shadow_geometry(scene)
    B = project_scene(scene, A, camera=camera)
    doc = compose(scene, B)
    return {"geometry": doc, "svg": write_svg(doc, layers=scene["output"]["layers"])}
