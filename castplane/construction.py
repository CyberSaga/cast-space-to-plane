"""Construction points, rays and the self-check (spec §5.5, §5.7; contract §2.7).

Everything here is 2-D image geometry on homogeneous 3-vectors ``(x̃1, x̃2, x̃3)``
or on already divided ``(u, v)`` canvas-mm points.  The 3-D inputs (``L``, ``F``,
``P``, ``S``, ``Q``) are projected by :func:`castplane.camera.project`; the
drawing rules of contract §2.7 are:

* ``L' = P·L`` and ``F' = P·F`` are **never near-clipped or nulled**: they are
  divided whenever ``|x̃3| > tol``; otherwise the point is at infinity and only
  its direction ``normalize_max((x̃1, x̃2))`` is reported.
* Construction rays are **2-D segments**: ``L'P'`` is the segment covering
  ``L'``, ``P'`` and ``S'`` (all three are collinear, spec §5.5); when ``L'`` is
  at infinity it is the segment ``P'→S'`` extended by 20 % beyond both ends.
  ``F'Q'`` is built the same way from ``F'``, ``Q'``, ``S'``; the vertical is
  ``P'Q'``.  All of them go through the homogeneous rectangle clip (contract
  §2.2 step 3) before the division.
* Self-check ``S'_check = (L'×P') × (F'×Q')`` against ``S'`` (spec §5.5), both
  max-normalised, compared in ``(u, v)``; skipped when a line is the zero vector,
  when the two lines are parallel / coincident, or when ``S'`` (or the meet) is
  at infinity.
"""

from __future__ import annotations

import numpy as np

from .camera import clip_segments_rect_h, divide, project
from .homogeneous import TOL_DIR, normalize_max, row_max_abs

#: Extension factor of the ``P'→S'`` segment when the far point is at infinity (contract §2.7).
RAY_EXTENSION = 0.2
#: Relative threshold under which a 2-D line / meet counts as the zero vector (contract §2.7 / §2.8).
LINE_ZERO_REL = 1e-9
#: Lines whose max-normalised meet is smaller than this are treated as parallel / coincident for the
#: self-check (contract §2.7): the intersection of two lines at an angle θ amplifies rounding by 1/sin θ,
#: so below ≈ 1e-6 the 1e-6 mm comparison is meaningless and the check is skipped instead.
LINE_PARALLEL_REL = 1e-6


def special_point_image(cam: dict, X, tol: float) -> dict:
    """Image of ``L`` or ``F`` by plain division (contract §2.7).

    Returns ``{"h", "point", "at_infinity", "behind", "undefined"}``.

    ``point`` is ``[u, v]`` when ``|x̃3| > tol`` (also when ``x̃3 < 0``: the
    anti-light point of spec §5.7 row 1), else ``None`` and ``at_infinity`` is
    ``normalize_max((x̃1, x̃2))``.  When the whole image vector is the zero
    vector up to rounding (``max|x̃| ≤ 1e-9 · max|P| · max|X|``: the foot of a
    directional light along the receiver normal, ``X = 0``, or a point light at
    the camera centre, ``P·X = 0``) the point is ``undefined``: ``point`` and
    ``at_infinity`` are both ``None``.  ``behind`` is ``x̃3 < -tol``.
    """
    X = np.asarray(X, dtype=np.float64).reshape(4)
    x = project(cam, X)
    scale = float(np.max(np.abs(cam["P"]))) * float(np.max(np.abs(X)))
    if float(np.max(np.abs(x))) <= LINE_ZERO_REL * scale:
        return {"h": x, "point": None, "at_infinity": None, "behind": False, "undefined": True}
    x3 = float(x[2])
    if abs(x3) > tol:
        return {"h": x, "point": [float(x[0] / x3) + 0.0, float(x[1] / x3) + 0.0], "at_infinity": None,
                "behind": x3 < -tol, "undefined": False}
    d = normalize_max(x[:2])
    return {"h": x, "point": None, "at_infinity": [float(d[0]) + 0.0, float(d[1]) + 0.0], "behind": False,
            "undefined": False}


def covering_segments(A, B, C):
    """Segments covering three collinear 2-D points per row (contract §2.7 rays with a finite far point).

    ``A`` is ``(2,)`` or ``(n, 2)`` (``L'`` / ``F'``), ``B`` and ``C`` are
    ``(n, 2)`` (``P'`` and ``S'``, or ``Q'`` and ``S'``).  The segment runs
    from the lowest to the highest of the three points along the line direction
    (``C − B``, falling back to ``A − B`` when ``B == C``).  Returns ``(n, 2, 2)``.
    """
    B = np.asarray(B, dtype=np.float64).reshape(-1, 2)
    C = np.asarray(C, dtype=np.float64).reshape(-1, 2)
    A = np.broadcast_to(np.asarray(A, dtype=np.float64).reshape(-1, 2), B.shape)
    d = C - B
    alt = A - B
    use_alt = row_max_abs(d) <= 1e-12 * np.maximum(1.0, row_max_abs(B))
    d = np.where(use_alt[:, None], alt, d)
    norm = np.sqrt(np.einsum("ij,ij->i", d, d))
    norm = np.where(norm == 0.0, 1.0, norm)
    d = d / norm[:, None]
    tA = np.einsum("ij,ij->i", A - B, d)
    tB = np.zeros(B.shape[0])
    tC = np.einsum("ij,ij->i", C - B, d)
    # the lowest / highest of the three parameters (fixed-size expressions, contract §2.8 determinism)
    lo = np.minimum(np.minimum(tA, tB), tC)
    hi = np.maximum(np.maximum(tA, tB), tC)
    out = np.empty((B.shape[0], 2, 2), dtype=np.float64)
    out[:, 0, :] = B + lo[:, None] * d
    out[:, 1, :] = B + hi[:, None] * d
    return out


def extended_segments(B, C, frac: float = RAY_EXTENSION):
    """``B→C`` extended by ``frac`` beyond both ends per row (contract §2.7, far point at infinity)."""
    B = np.asarray(B, dtype=np.float64).reshape(-1, 2)
    C = np.asarray(C, dtype=np.float64).reshape(-1, 2)
    d = C - B
    return np.stack([B - frac * d, C + frac * d], axis=1)


def clip_segments_uv(segments, rect):
    """Homogeneous rectangle clip (contract §2.2 step 3+4) of ``(n, 2, 2)`` mm segments -> ``(clipped, keep)``.

    Zero-length segments (both ends coincide) are not kept: they are not segments.
    """
    seg = np.asarray(segments, dtype=np.float64).reshape(-1, 2, 2)
    if seg.shape[0] == 0:
        return seg, np.zeros(0, dtype=bool)
    A = np.ones((seg.shape[0], 3))
    A[:, :2] = seg[:, 0, :]
    B = np.ones((seg.shape[0], 3))
    B[:, :2] = seg[:, 1, :]
    A2, B2, keep = clip_segments_rect_h(A, B, rect)
    out = np.empty((seg.shape[0], 2, 2), dtype=np.float64)
    out[:, 0, :] = divide(A2)
    out[:, 1, :] = divide(B2)
    out = np.where(keep[:, None, None], out, 0.0)
    length = row_max_abs(out[:, 1, :] - out[:, 0, :])
    keep = keep & (length > 1e-9)
    return out, keep


def coincidence_check(Sp, Rp, tol: float):
    """Degenerate form of the spec §5.5 self-check when one construction line is undefined.

    For a point light at the camera centre ``L``, ``P`` and ``S`` are collinear
    with the eye, so ``S' = P'``; for a directional light along the receiver
    normal ``S = Q`` (``M·P = foot(π, P)``), so ``S' = Q'``.  ``Sp`` and ``Rp``
    are ``(n, 3)`` homogeneous image points; returns ``(max_error_mm (n,),
    skipped (n,) bool)`` with rows skipped when either point is at infinity
    (``|x̃3| ≤ tol``).
    """
    Sp = np.asarray(Sp, dtype=np.float64).reshape(-1, 3)
    Rp = np.asarray(Rp, dtype=np.float64).reshape(-1, 3)
    n = Sp.shape[0]
    if n == 0:
        return np.zeros(0), np.zeros(0, dtype=bool)
    skipped = (np.abs(Sp[:, 2]) <= tol) | (np.abs(Rp[:, 2]) <= tol)
    one = np.array([0.0, 0.0, 1.0])
    safe_S = np.where(skipped[:, None], one, Sp)
    safe_R = np.where(skipped[:, None], one, Rp)
    err = row_max_abs(divide(safe_S) - divide(safe_R))
    return np.where(skipped, 0.0, err), skipped


def _relative_zero(v, scale):
    """Rows of ``v`` whose max-|component| is ≤ ``LINE_ZERO_REL · scale``."""
    return row_max_abs(v) <= LINE_ZERO_REL * scale


def self_check(Lp, Pp, Fp, Qp, Sp, tol: float):
    """Spec §5.5 self-check ``S'_check = (L'×P') × (F'×Q')`` vs ``S'`` (contract §2.7), vectorised.

    ``Lp``, ``Fp`` are ``(3,)``; ``Pp``, ``Qp``, ``Sp`` are ``(n, 3)`` homogeneous
    image points.  Returns ``(max_error_mm (n,), skipped (n,) bool)``; the error of
    a skipped row is ``0``.  Skip rules: a zero line (``P' = L'`` or ``Q' = F'``
    projectively), (nearly) parallel / coincident lines (max-normalised meet ≤ 1e-6, where
    the intersection amplifies rounding by more than 1e6), ``S'`` at infinity
    (``|x̃3| ≤ tol``) or the meet itself at infinity (two distinct parallel
    lines).  The comparison is ``max(|Δu|, |Δv|)`` after max-normalising both.
    """
    Pp = np.asarray(Pp, dtype=np.float64).reshape(-1, 3)
    Qp = np.asarray(Qp, dtype=np.float64).reshape(-1, 3)
    Sp = np.asarray(Sp, dtype=np.float64).reshape(-1, 3)
    n = Pp.shape[0]
    if n == 0:
        return np.zeros(0), np.zeros(0, dtype=bool)
    Lp = np.asarray(Lp, dtype=np.float64).reshape(3)
    Fp = np.asarray(Fp, dtype=np.float64).reshape(3)
    l1 = np.cross(np.broadcast_to(Lp, (n, 3)), Pp)
    l2 = np.cross(np.broadcast_to(Fp, (n, 3)), Qp)
    scale1 = float(np.max(np.abs(Lp))) * row_max_abs(Pp)
    scale2 = float(np.max(np.abs(Fp))) * row_max_abs(Qp)
    skipped = _relative_zero(l1, scale1) | _relative_zero(l2, scale2)
    l1n = normalize_max(l1)
    l2n = normalize_max(l2)
    meet = np.cross(l1n, l2n)
    skipped |= row_max_abs(meet) <= LINE_PARALLEL_REL                    # parallel or coincident lines (ill-conditioned)
    skipped |= np.abs(Sp[:, 2]) <= tol                                   # S' at infinity
    meet_n = normalize_max(meet)
    skipped |= np.abs(meet_n[:, 2]) <= TOL_DIR                           # meet at infinity (parallel lines)
    safe_meet = np.where(skipped[:, None], np.array([0.0, 0.0, 1.0]), meet_n)
    safe_S = np.where(skipped[:, None], np.array([0.0, 0.0, 1.0]), normalize_max(Sp))
    err = row_max_abs(divide(safe_meet) - divide(safe_S))
    err = np.where(skipped, 0.0, err)
    return err, skipped
