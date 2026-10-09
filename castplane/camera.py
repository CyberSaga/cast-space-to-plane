"""Rectilinear perspective camera (spec §5.4, §5.7; contract §2.2).

Conventions (contract §2.2, normative):

* ``forward = normalize(target - position)``; ``right = normalize(forward x up_world)``;
  ``up = right x forward``; roll turns ``(right, up)`` about ``forward``.
* Rows of ``R`` are ``(right', up', forward)`` so ``det R = -1`` on purpose:
  ``u`` right, ``v`` up, depth positive in front.  Nobody may "fix" this.
* ``K = [[f·s, 0, u0], [0, f·s, v0], [0, 0, 1]]`` with ``s = canvas_w / frame_w``
  and ``(u0, v0) = shift_mm · s`` (canvas mm, origin at the frame centre).
* ``P = K·[R|t]``, ``x̃ = P·X``, ``(u, v) = (x̃1/x̃3, x̃2/x̃3)`` divided LAST.
* Near functional ``ν(X) = forward·(x - C·w) - near·w = x̃3 - near·w``.
"""

from __future__ import annotations

import math

import numpy as np

from .errors import make_warning
from .homogeneous import (TOL_DIR, clip_polygon_halfspace, clip_polygons_halfspace, clip_segment_halfspace,
                          clip_segments_halfspace, join, normalize_max)

UP_WORLD = np.array([0.0, 0.0, 1.0])
FALLBACK_UP = np.array([0.0, 1.0, 0.0])
#: The extended canvas rectangle grows the canvas by this fraction on each side (contract §2.2 step 3).
RECT_GROW = 0.25


def _unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


def _default_basis(forward):
    """``(right, up, along_up)`` before roll (contract §2.2): ``right = normalize(forward x up_world)``, ``up =
    right x forward`` with ``up_world`` = world z, or +y when ``|forward x z| <= 1e-9`` (``along_up`` true)."""
    up_world = UP_WORLD
    along_up = bool(np.linalg.norm(np.cross(forward, up_world)) <= 1e-9)
    if along_up:
        up_world = FALLBACK_UP
    right = _unit(np.cross(forward, up_world))
    return right, np.cross(right, forward), along_up


def camera_forward(cam: dict):
    """``forward`` of a validated camera dict: target form, yaw/pitch form or (M10) ``picture_plane`` form, which
    is resolved to its target form first (``castplane.picture_plane.resolve_picture_plane``; contract §2.2)."""
    if "picture_plane" in cam:   # forward is f itself (spec-v0.2 §4.1), bit for bit the document's normal
        from .picture_plane import resolve_picture_plane
        return np.asarray(resolve_picture_plane(cam)[2]["normal"], dtype=np.float64)
    if "target" in cam:
        return _unit(np.asarray(cam["target"], dtype=np.float64) - np.asarray(cam["position"], dtype=np.float64))
    yaw, pitch = math.radians(cam["yaw_deg"]), math.radians(cam["pitch_deg"])
    return np.array([-math.sin(yaw) * math.cos(pitch), math.cos(yaw) * math.cos(pitch), math.sin(pitch)])


def camera_matrix(cam: dict, canvas) -> dict:
    """Camera record ``{K, R, t, P, C, forward, near, s, u0, v0, canvas_mm, frame_mm, rect, warnings}`` (§5.4, contract §2.2).

    ``cam`` is a validated camera block (contract §2.0; a ``picture_plane`` block is resolved first and its
    record gains ``picture_plane``, the document block of ``picture_plane_document``), ``canvas`` is
    ``output.canvas_mm``.  ``rect`` is the extended canvas rectangle
    ``(u_min, u_max, v_min, v_max)`` used by the homogeneous rectangle clip.
    """
    warnings = []
    pp_info = None
    roll_deg = cam.get("roll_deg", 0.0)
    if "picture_plane" in cam:
        # M10 (spec-v0.2 §4.1): resolve to the target form; the explicit frame up never warns
        from .picture_plane import resolve_picture_plane
        cam, roll_deg, pp_info = resolve_picture_plane(cam)
    C = np.asarray(cam["position"], dtype=np.float64)
    # picture_plane: forward is f bit for bit (the |f x z| <= 1e-9 fallback is decided on f, R[2] = document normal)
    forward = camera_forward(cam) if pp_info is None else np.asarray(pp_info["normal"], dtype=np.float64)
    right, up, along_up = _default_basis(forward)
    if along_up and pp_info is None:
        warnings.append(make_warning("CAMERA_LOOKING_ALONG_UP", []))
    rho = math.radians(roll_deg)
    right_r = math.cos(rho) * right + math.sin(rho) * up
    up_r = -math.sin(rho) * right + math.cos(rho) * up
    R = np.stack([right_r, up_r, forward], axis=0)
    t = -R @ C

    canvas = [float(canvas[0]), float(canvas[1])]
    frame = [float(cam["frame_mm"][0]), float(cam["frame_mm"][1])]
    s = canvas[0] / frame[0]
    f = float(cam["focal_length_mm"])
    shift = cam.get("shift_mm", [0.0, 0.0])
    u0, v0 = float(shift[0]) * s, float(shift[1]) * s
    K = np.array([[f * s, 0.0, u0], [0.0, f * s, v0], [0.0, 0.0, 1.0]])
    Rt = np.concatenate([R, t[:, None]], axis=1)
    P = K @ Rt
    W, H = canvas
    rect = (-(0.5 + RECT_GROW) * W, (0.5 + RECT_GROW) * W, -(0.5 + RECT_GROW) * H, (0.5 + RECT_GROW) * H)
    rec = {
        "K": K, "R": R, "t": t, "Rt": Rt, "P": P, "C": C, "forward": forward,
        "near": float(cam.get("near_m", 0.05)), "s": s, "u0": u0, "v0": v0,
        "canvas_mm": canvas, "frame_mm": frame, "rect": rect, "warnings": warnings,
    }
    if pp_info is not None:
        from .picture_plane import picture_plane_document
        rec["picture_plane"] = picture_plane_document(pp_info, rec, f)
    return rec


def project(cam: dict, X):
    """``x̃ = P·X`` for one 4-vector or an ``(n, 4)`` array -> 2-D homogeneous 3-vectors (§5.4)."""
    X = np.asarray(X, dtype=np.float64)
    return X @ cam["P"].T


def divide(x):
    """``(u, v) = (x̃1/x̃3, x̃2/x̃3)``; the last step of the drawing pipeline (contract §2.2 step 4)."""
    x = np.asarray(x, dtype=np.float64)
    return x[..., :2] / x[..., 2:3]


def nu(cam: dict, X):
    """Near functional ``ν(X) = forward·(x - C·w) - near·w`` on 4-vectors (contract §2.2)."""
    X = np.asarray(X, dtype=np.float64)
    fwd = cam["forward"]
    offset = float(fwd @ cam["C"]) + cam["near"]
    return X[..., :3] @ fwd - offset * X[..., 3]


def depth(cam: dict, X):
    """Camera-space depth: 3rd component of ``[R|t]·X`` (contract §2.2)."""
    X = np.asarray(X, dtype=np.float64)
    return X @ cam["Rt"][2]


def clip_segment_near(cam: dict, A, B):
    """Near-clip one homogeneous world segment against ``ν ≥ 0`` (contract §2.2 step 1).

    Returns ``(A', B')`` (4-vectors) or ``None`` when the whole segment is behind.
    """
    return clip_segment_halfspace(A, B, float(nu(cam, A)), float(nu(cam, B)))


def clip_segments_near(cam: dict, A, B):
    """Vectorised :func:`clip_segment_near` on ``(m, 4)`` arrays -> ``(A', B', keep)``."""
    return clip_segments_halfspace(A, B, nu(cam, A), nu(cam, B))


def clip_polygon_near(cam: dict, points):
    """Sutherland-Hodgman near clip of a homogeneous world polygon ``(n, 4)`` (contract §2.2 step 1)."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 4)
    return clip_polygon_halfspace(pts, nu(cam, pts))


def rect_functionals(rect):
    """The four functionals of the homogeneous rectangle clip as rows ``(a, b, c)`` with ``a x̃1 + b x̃2 + c x̃3 ≥ 0``."""
    u_min, u_max, v_min, v_max = (float(r) for r in rect)
    return np.array([
        [-1.0, 0.0, u_max],   # u_max·x3 - x1 ≥ 0
        [1.0, 0.0, -u_min],   # x1 - u_min·x3 ≥ 0
        [0.0, -1.0, v_max],   # v_max·x3 - x2 ≥ 0
        [0.0, 1.0, -v_min],   # x2 - v_min·x3 ≥ 0
    ])


def clip_polygon_rect_h(points, rect):
    """Clip a 2-D homogeneous polygon ``(n, 3)`` to the rectangle in homogeneous coordinates (contract §2.2 step 3).

    Direction vertices (``x̃3 == 0``) are handled by linear interpolation; since
    a bounded rectangle contains no point at infinity, every surviving vertex has
    ``x̃3 > 0`` and can be divided safely.  A polygon left with fewer than three
    vertices after **any** of the four functionals is dropped (empty result) -- the
    remaining functionals are not applied to it; :func:`project_polygons` does the same.
    """
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    for row in rect_functionals(rect):
        if pts.shape[0] < 3:
            break
        pts = clip_polygon_halfspace(pts, pts @ row)
    if pts.shape[0] < 3:
        return np.zeros((0, 3))
    return pts


def project_polygons(cam: dict, pts, lens):
    """Batched drawing pipeline of contract §2.2 for padded homogeneous world polygons (spec §8).

    ``pts`` is ``(N, L, 4)`` with ``lens[i]`` valid leading rows per polygon and zero
    padding.  Every polygon goes through near clip -> ``P`` -> homogeneous rectangle clip
    -> divide exactly like ``pipeline._project_polygon``: a polygon with fewer than three
    vertices after the near clip or after any one of the four rectangle functionals is
    empty from then on (``clip_polygon_rect_h`` stops clipping such a polygon and returns
    empty, so the two paths agree).  Returns ``(uv (N, W, 2) canvas mm, lens)``; padded rows
    of ``uv`` are ``0``.
    """
    pts = np.asarray(pts, dtype=np.float64)
    lens = np.where(np.asarray(lens, dtype=np.int64) < 3, 0, np.asarray(lens, dtype=np.int64))
    N = pts.shape[0]
    if N == 0:
        return np.zeros((0, 0, 2)), lens
    # the functionals are evaluated on the flattened (rows, k) array so that the very same
    # 2-D kernels as in the per-polygon path produce bit-identical values
    vals = nu(cam, pts.reshape(-1, 4)).reshape(N, -1)
    pts, lens = clip_polygons_halfspace(pts, lens, vals)                  # 1. near clip (4-D)
    lens = np.where(lens < 3, 0, lens)
    X = project(cam, pts.reshape(-1, 4)).reshape(N, -1, 3)                 # 2. P
    for row in rect_functionals(cam["rect"]):                              # 3. rectangle clip
        vals = (X.reshape(-1, 3) @ row).reshape(N, -1)
        X, lens = clip_polygons_halfspace(X, lens, vals)
        lens = np.where(lens < 3, 0, lens)
    valid = np.arange(X.shape[1])[None, :] < lens[:, None]
    X = np.where(valid[:, :, None], X, np.array([0.0, 0.0, 1.0]))
    return divide(X), lens                                                 # 4. divide last


def clip_segments_rect_h(A, B, rect):
    """Vectorised homogeneous rectangle clip of 2-D segments ``(m, 3)`` -> ``(A', B', keep)``."""
    A = np.asarray(A, dtype=np.float64)
    B = np.asarray(B, dtype=np.float64)
    keep = np.ones(A.shape[0], dtype=bool)
    for row in rect_functionals(rect):
        A, B, k = clip_segments_halfspace(A, B, A @ row, B @ row)
        keep &= k
    return A, B, keep


def clip_line_rect(line, rect):
    """Clip the 2-D line ``a·u + b·v + c = 0`` to the rectangle; ``[[u, v], [u, v]]`` or ``None`` (contract §2.2).

    Used for the horizon segment.  The line at infinity (``a = b = 0``) yields ``None``.
    """
    a, b, c = (float(v) for v in normalize_max(line))
    n2 = a * a + b * b
    if n2 <= 1e-18:
        return None
    p0 = np.array([-c * a / n2, -c * b / n2])
    d = np.array([-b, a])
    u_min, u_max, v_min, v_max = rect
    t0, t1 = -math.inf, math.inf
    for p, q in ((-d[0], p0[0] - u_min), (d[0], u_max - p0[0]), (-d[1], p0[1] - v_min), (d[1], v_max - p0[1])):
        if abs(p) <= 1e-15:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
    if t0 >= t1:
        return None
    pa, pb = p0 + t0 * d, p0 + t1 * d
    return [[float(pa[0]), float(pa[1])], [float(pb[0]), float(pb[1])]]


def vanishing_point(cam: dict, d, tol: float = TOL_DIR):
    """Image ``[u, v]`` of the direction ``(d, 0)`` or ``None`` when ``|x̃3| ≤ tol`` (§5.5, contract §2.2)."""
    d = np.asarray(d, dtype=np.float64)
    x = project(cam, np.array([d[0], d[1], d[2], 0.0]))
    if abs(x[2]) <= tol:
        return None
    return [float(x[0] / x[2]), float(x[1] / x[2])]


def horizon(cam: dict, tol: float = TOL_DIR) -> dict:
    """Horizon of the ground: join of the images of ``(1,0,0,0)`` and ``(0,1,0,0)`` (§5.5, contract §2.2).

    Returns ``{"line": [a, b, c], "v_mm": float | None, "segment": [[u, v], [u, v]] | None,
    "vanishing_points": {"x", "y", "z"}}``; ``v_mm`` is the line's ``v`` at
    ``u = 0`` (``None`` for a vertical line or the line at infinity).
    """
    vx = project(cam, np.array([1.0, 0.0, 0.0, 0.0]))
    vy = project(cam, np.array([0.0, 1.0, 0.0, 0.0]))
    line = normalize_max(join(vx, vy))
    a, b, c = (float(v) for v in line)
    v_mm = None if abs(b) <= tol else -c / b
    return {
        "line": [a, b, c],
        "v_mm": v_mm,
        "segment": clip_line_rect(line, cam["rect"]),
        "vanishing_points": {
            "x": vanishing_point(cam, [1.0, 0.0, 0.0], tol),
            "y": vanishing_point(cam, [0.0, 1.0, 0.0], tol),
            "z": vanishing_point(cam, [0.0, 0.0, 1.0], tol),
        },
    }
