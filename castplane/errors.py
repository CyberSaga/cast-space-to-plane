"""Input errors and structured warnings (spec §5.8, §8; contract §2.8, §2.9).

``SceneError`` is raised for malformed input and carries the JSON field path
(contract §2.0).  Geometric degeneracies never raise: they are reported as
warning dicts ``{"code", "ids", "message"}`` built with :func:`make_warning`
from the closed code table of contract §2.9.
"""

from __future__ import annotations


class SceneError(ValueError):
    """Malformed scene input.  ``field`` is the JSON path (e.g. ``objects[1].size``)."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


#: Closed list of warning codes (contract §2.9, extended by §5.0.5).  ``code -> default message``.
WARNING_CODES = {
    "CAMERA_LOOKING_ALONG_UP": "camera forward is parallel to world up; using (0,1,0) as up",
    "LIGHT_BEHIND_CAMERA": "finite light is behind the camera; L' is the anti-light point",
    "LIGHT_POINT_AT_INFINITY": "light point L' is at infinity; construction rays are parallel",
    "SHADOW_VP_AT_INFINITY": "shadow vanishing point F' is at infinity",
    "DIRECTIONAL_HORIZONTAL": "directional light is parallel to the receiver; no shadows",
    "LIGHT_BELOW_RECEIVER": "light is on the back side of the receiver; no shadows",
    "VERTEX_NOT_BELOW_LIGHT": "a silhouette vertex is not below the light; shadow outline is unbounded",
    "OBJECT_BELOW_RECEIVER": "object has vertices below the receiver; silhouette clipped to the ground",
    "POINT_BEHIND_CAMERA": "some drawn point is behind the near plane; image is null or clipped",
    "FACE_PARALLEL_TO_LIGHT": "a face is parallel to the light direction; treated as unlit",
    "LIGHT_INSIDE_OBJECT": "point light is inside the sphere; no shadow or terminator",
    "CONIC_SAMPLED": "conic is degenerate or ill-conditioned; emitted as a sampled polyline",
    "CONSTRUCTION_CHECK_SKIPPED": "construction self-check skipped for a degenerate point",
    # M4 (contract §5.0.5 / §5.1.9): appended at the end; M5 appends its codes after this one
    "RECEIVER_UNLIT": "bounded receiver is not lit by this light (light behind or in its plane); it receives no shadow",
    # M5 (contract §5.2.6 / §5.0.5): appended after M4's RECEIVER_UNLIT in the merged list
    "MESH_NON_MANIFOLD": "mesh is not a closed consistently oriented manifold; per-face shadow fallback",
    "MESH_WINDING_FIXED": "mesh faces were reoriented (winding propagation or signed volume)",
    "MESH_DEGENERATE_FACES": "degenerate mesh faces were dropped",
    "MESH_RAYS_CAPPED": "more than 64 feature silhouette vertices; construction rays for the first 64 only",
}


def make_warning(code: str, ids=(), message: str | None = None) -> dict:
    """Build a warning dict ``{"code", "ids", "message"}`` (contract §2.8/§2.9).

    ``code`` must belong to :data:`WARNING_CODES`; ``ids`` are the related
    object / light / point ids (strings).
    """
    if code not in WARNING_CODES:
        raise ValueError(f"unknown warning code {code!r}")
    return {
        "code": code,
        "ids": [str(i) for i in ids],
        "message": WARNING_CODES[code] if message is None else str(message),
    }


def merge_warnings(*lists) -> list:
    """Concatenate warning lists, deduplicate on (code, ids) and sort by code then ids (contract §2.8)."""
    seen = {}
    for lst in lists:
        for w in lst or ():
            key = (w["code"], tuple(w["ids"]))
            if key not in seen:
                seen[key] = {"code": w["code"], "ids": list(w["ids"]), "message": w["message"]}
    return [seen[k] for k in sorted(seen)]


def warning_codes(warnings) -> set:
    """Set of codes present in a warning list (used by tests and the CLI)."""
    return {w["code"] for w in warnings}
