"""Homogeneous-coordinate helpers (spec §2, §5.8; contract §2.1, §2.8).

All vectors are *oriented* homogeneous vectors (contract §2.1): finite points
``(x, y, z, 1)``, directions ``(d, 0)``; 2-D image points ``(x1, x2, x3)``.
Nothing here divides by ``w``: normalisation is by the max-|component| only.
"""

from __future__ import annotations

import numpy as np

#: Dimensionless tolerance for direction / sign tests (contract §2.8).
TOL_DIR = 1e-9


def normalize_max(v):
    """Divide a homogeneous vector by its max-|component|, preserving sign (§5.8, contract §2.8).

    Works on a single vector or on an ``(..., k)`` array (row-wise).  The zero
    vector is returned unchanged.
    """
    v = np.asarray(v, dtype=np.float64)
    m = np.max(np.abs(v), axis=-1, keepdims=True)
    safe = np.where(m == 0.0, 1.0, m)
    return v / safe


def cross3(a, b):
    """3-vector cross product; the join of two 2-D points / meet of two 2-D lines (§5.5)."""
    return np.cross(np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64))


#: Join of two homogeneous 2-D points is the line through them (§5.5).
join = cross3
#: Meet of two homogeneous 2-D lines is their intersection point (§5.5).
meet = cross3


def to_homogeneous(points, w=1.0):
    """Append a ``w`` column to an ``(n, 3)`` array -> ``(n, 4)`` (contract §2.1)."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    return np.concatenate([pts, np.full((pts.shape[0], 1), float(w))], axis=1)


def scene_scale(vertices, camera_position=None) -> float:
    """``max(1, extent of the bounding box of all vertices and the camera position)`` (contract §2.8).

    Light positions are intentionally excluded.  ``extent`` is the largest side
    of the axis-aligned bounding box.
    """
    pts = [np.asarray(vertices, dtype=np.float64).reshape(-1, 3)]
    if camera_position is not None:
        pts.append(np.asarray(camera_position, dtype=np.float64).reshape(1, 3))
    allp = np.concatenate(pts, axis=0)
    if allp.shape[0] == 0:
        return 1.0
    extent = float(np.max(allp.max(axis=0) - allp.min(axis=0)))
    return max(1.0, extent)


def tolerance(scale: float) -> float:
    """Length-valued tolerance ``tol = 1e-9 * scene_scale`` (§5.8, contract §2.8)."""
    return 1e-9 * float(scale)


#: Relative threshold under which an interpolated homogeneous vector counts as the zero vector.
ZERO_REL = 1e-12


def _nonzero_rows(pts, scale):
    """Mask of rows that are not (numerically) the zero vector, relative to ``scale``."""
    return np.max(np.abs(pts), axis=-1) > ZERO_REL * scale


def clip_segments_halfspace(a, b, fa, fb):
    """Clip many homogeneous segments against one linear functional ``f >= 0`` (contract §2.2 step 1/3).

    ``a, b`` are ``(m, k)`` endpoint arrays, ``fa, fb`` their functional values.
    Returns ``(a2, b2, keep)``: clipped endpoints (rows where ``keep`` is False
    are meaningless) and the boolean keep mask.  The crossing point is the
    linear interpolation ``(fa*b - fb*a) / (fa - fb)`` of the homogeneous
    coordinates, which satisfies ``f == 0`` and never divides by ``w``.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    fa = np.asarray(fa, dtype=np.float64)
    fb = np.asarray(fb, dtype=np.float64)
    a_in = fa >= 0.0
    b_in = fb >= 0.0
    keep = a_in | b_in
    cross = a_in != b_in
    denom = np.where(cross, fa - fb, 1.0)
    x = (fa[:, None] * b - fb[:, None] * a) / denom[:, None]
    a2 = np.where((~a_in & cross)[:, None], x, a)
    b2 = np.where((~b_in & cross)[:, None], x, b)
    # the interpolation of two antipodal directions is the zero vector (no projective point): drop it
    scale = np.maximum(np.max(np.abs(a), axis=-1), np.max(np.abs(b), axis=-1))
    keep &= _nonzero_rows(a2, scale) & _nonzero_rows(b2, scale)
    return a2, b2, keep


def clip_segment_halfspace(a, b, fa, fb):
    """Scalar version of :func:`clip_segments_halfspace`; returns ``(a2, b2)`` or ``None``."""
    a2, b2, keep = clip_segments_halfspace(
        np.asarray(a, dtype=np.float64)[None, :],
        np.asarray(b, dtype=np.float64)[None, :],
        np.array([fa], dtype=np.float64),
        np.array([fb], dtype=np.float64),
    )
    if not keep[0]:
        return None
    return a2[0], b2[0]


def clip_polygon_halfspace(points, values):
    """Sutherland-Hodgman step of a homogeneous polygon against ``f >= 0`` (§5.4, contract §2.2).

    ``points`` is ``(n, k)``, ``values`` the functional at each vertex.  Returns
    an ``(n', k)`` array (possibly empty).  Interpolation is linear in the
    homogeneous coordinates, so direction vertices (``w == 0``) are handled
    without any division by ``w``.
    """
    pts = np.asarray(points, dtype=np.float64)
    vals = np.asarray(values, dtype=np.float64)
    n = pts.shape[0]
    if n == 0:
        return pts.reshape(0, pts.shape[1] if pts.ndim == 2 else 0)
    if np.all(vals >= 0.0):
        return pts.copy()
    if np.all(vals < 0.0):
        return np.zeros((0, pts.shape[1]))
    out = []
    for i in range(n):
        j = (i + 1) % n
        a, b = pts[i], pts[j]
        fa, fb = vals[i], vals[j]
        a_in, b_in = fa >= 0.0, fb >= 0.0
        if a_in:
            out.append(a)
        if a_in != b_in:
            out.append((fa * b - fb * a) / (fa - fb))
    out = np.array(out, dtype=np.float64).reshape(-1, pts.shape[1])
    # interpolating two antipodal directions gives the zero vector (no projective point): drop it
    return out[_nonzero_rows(out, float(np.max(np.abs(pts))))]
