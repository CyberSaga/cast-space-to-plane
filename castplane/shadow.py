"""Plane projection of shadows (spec §5.2, §5.3, §5.7; contract §2.3, §2.5).

Everything here works on oriented homogeneous 4-vectors ``X = (x, y, z, w)`` with the
canonical forms of contract §2.1: finite points ``w = +1``, point light ``(l, 1)``,
directional light ``(l, 0)`` with ``l`` towards the light, receiver plane
``pi = (n, d)`` with the light on its positive side (``pi^T L > 0``).

Only numpy is used.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = [
    "shadow_matrix",
    "foot",
    "shadow_w",
    "clip_loop_to_plane",
    "shadow_loop",
    "ARC_STEP_DEG",
]

# contract §2.5: at-infinity sub-edges must span < 90 degrees; use ceil(delta / 60 deg) steps.
ARC_STEP_DEG = 60.0


def shadow_matrix(pi, L) -> np.ndarray:
    """Spec §5.2: ``M = (pi^T L) I_4 - L pi^T`` so that ``S = M P`` is the shadow of ``P``
    on the plane ``pi`` cast by the light ``L`` (point or directional alike).

    ``pi^T M = 0`` (every image lies on the plane) and ``M L = 0``.
    """
    pi = np.asarray(pi, dtype=np.float64).reshape(4)
    L = np.asarray(L, dtype=np.float64).reshape(4)
    piL = float(pi @ L)
    return piL * np.eye(4) - np.outer(L, pi)


def foot(pi, X) -> np.ndarray:
    """Spec §5.3: foot of ``X`` on the plane ``pi = (n, d)`` along the plane normal,
    ``Q = (n . n) X - (n . x + w d) (n, 0)``.  Works for the light vector too (``F``);
    a directional light gives a point at infinity (``w = 0``).
    """
    pi = np.asarray(pi, dtype=np.float64).reshape(4)
    X = np.asarray(X, dtype=np.float64)
    n = pi[:3]
    d = pi[3]
    nn = float(n @ n)
    n0 = np.array([n[0], n[1], n[2], 0.0], dtype=np.float64)
    if X.ndim == 1:
        X = X.reshape(4)
        s = float(n @ X[:3] + X[3] * d)
        return nn * X - s * n0
    s = X[:, :3] @ n + X[:, 3] * d
    return nn * X - s[:, None] * n0[None, :]


def shadow_w(pi, L, P) -> np.ndarray | float:
    """Contract §2.3: the ``w`` component of ``M P``,
    ``w_S = (pi^T L) w_P - w_L (pi^T P)`` (for the ground: ``l_z - p_z`` for a point
    light, ``l_z`` for a directional one).  ``w_S <= tol`` means the vertex is not below
    the light (spec §5.7 row 4).  ``P`` may be ``(4,)`` or ``(n, 4)``.
    """
    pi = np.asarray(pi, dtype=np.float64).reshape(4)
    L = np.asarray(L, dtype=np.float64).reshape(4)
    P = np.asarray(P, dtype=np.float64)
    piL = float(pi @ L)
    if P.ndim == 1:
        return piL * float(P[3]) - float(L[3]) * float(pi @ P)
    return piL * P[:, 3] - L[3] * (P @ pi)


def _normalize_max(v: np.ndarray) -> np.ndarray:
    """Divide by the max-|component| (sign preserved), contract §2.8; zero stays zero."""
    m = float(np.max(np.abs(v)))
    if m == 0.0:
        return v
    return v / m


def clip_loop_to_plane(points4, pi, tol: float = 0.0, sources=None):
    """Contract §2.3 ground clip: Sutherland–Hodgman clip of a closed homogeneous loop
    to the half-space ``pi^T X >= 0`` with linear interpolation of homogeneous
    coordinates.  Vertices with ``pi^T X < -tol`` are "below" and dropped; crossings are
    inserted on the plane itself (they are their own shadows).

    Returns ``(clipped (k,4), sources, any_below)`` where ``sources`` lists, per kept
    vertex, the original index (int) or ``("ground", i, j)`` for the crossing of the
    edge ``i -> j``.  A kept vertex inside the band ``|pi^T X| <= tol`` is its own
    crossing, so no extra (duplicate) vertex is inserted next to it.
    """
    P = np.asarray(points4, dtype=np.float64).reshape(-1, 4)
    pi = np.asarray(pi, dtype=np.float64).reshape(4)
    n = P.shape[0]
    if sources is None:
        sources = list(range(n))
    if n == 0:
        return P.copy(), [], False
    f = P @ pi
    keep = f >= -tol
    any_below = bool(np.any(~keep))
    if not any_below:
        return P.copy(), list(sources), False
    out_pts: list[np.ndarray] = []
    out_src: list = []
    for a in range(n):
        b = (a + 1) % n
        if keep[a]:
            out_pts.append(P[a])
            out_src.append(sources[a])
        if keep[a] != keep[b]:
            fa, fb = float(f[a]), float(f[b])
            # a kept endpoint inside the band |pi^T X| <= tol already lies on the plane
            # and is its own crossing: inserting it again would give a zero-length edge
            if (keep[a] and abs(fa) <= tol) or (keep[b] and abs(fb) <= tol):
                continue
            # crossing of edge a -> b with pi^T X = 0 (linear in t)
            t = fa / (fa - fb) if fa != fb else 0.0
            t = min(1.0, max(0.0, t))
            X = (1.0 - t) * P[a] + t * P[b]
            out_pts.append(X)
            out_src.append(("ground", sources[a], sources[b]))
    if not out_pts:
        return np.zeros((0, 4), dtype=np.float64), [], True
    return np.array(out_pts, dtype=np.float64), out_src, True


def _direction_vertex(S_a: np.ndarray, w_a: float, S_b: np.ndarray, w_b: float,
                      fallback_from: np.ndarray | None) -> np.ndarray:
    """Contract §2.5: ``D = (1 - t*) S_a + t* S_b`` with ``t* = w_a / (w_a - w_b)`` so
    that ``w_D = 0``; with canonical inputs ``+D`` is the outgoing (resp. incoming)
    direction of the shadow ray.  The result is scaled to unit length in the plane."""
    t = w_a / (w_a - w_b)
    D = (1.0 - t) * S_a + t * S_b
    D = D.copy()
    D[3] = 0.0
    norm = float(np.linalg.norm(D[:3]))
    if not (norm > 1e-300 and math.isfinite(norm)):
        # the edge passes through the light itself (M L = 0): the whole edge shadows
        # onto one ground point; use the shadow ray from the light foot through the
        # finite endpoint (S_a for the outgoing case, S_b for the incoming one).
        norm = 0.0
        if fallback_from is not None:
            S_f, w_f = (S_a, w_a) if w_a > 0.0 else (S_b, w_b)
            if w_f > 0.0:
                d = S_f[:3] / w_f - fallback_from[:3]
                D = np.array([d[0], d[1], d[2], 0.0], dtype=np.float64)
                norm = float(np.linalg.norm(D[:3]))
        if not (norm > 1e-300 and math.isfinite(norm)):
            return np.array([1.0, 0.0, 0.0, 0.0])
    return D / norm


def _light_foot_from_matrix(M: np.ndarray, pi: np.ndarray) -> np.ndarray | None:
    """Recover the finite light foot ``F = foot(pi, L)`` from ``M`` (fallback only).

    For the ground (``d = 0``): ``M e_w = (pi^T L) e_w`` gives ``pi^T L`` and
    ``M (n,0) = (pi^T L)(n,0) - (n.n) L`` gives ``L``.
    """
    n = pi[:3]
    nn = float(n @ n)
    if nn <= 0.0 or pi[3] != 0.0:
        return None
    n0 = np.array([n[0], n[1], n[2], 0.0])
    piL = float(M[3, 3])
    L = (piL * n0 - M @ n0) / nn
    F = foot(pi, L)
    if abs(F[3]) <= 1e-300:
        return None
    return F / F[3]


def shadow_loop(points4, M, pi, tol: float = 0.0, tol_clip: float | None = None) -> dict:
    """Shadow polygon of one silhouette loop (spec §5.2 / §5.7 row 4, contract §2.5).

    ``points4`` is the ``(n, 4)`` loop in order (lit face on the left as seen from the
    light), ``M`` the shadow matrix and ``pi`` the receiver.  ``tol`` is the ``w_S``
    tolerance (contract §2.8: ``tol = 1e-9 * scene_scale`` for a point light,
    ``tol_dir = 1e-9`` for a directional one); ``tol_clip`` is the length-valued
    tolerance of the ground clip (``1e-9 * scene_scale`` for both light types) and
    defaults to ``tol``.  Steps:

    1. ground clip to ``pi^T X >= 0`` (contract §2.3) with ``tol_clip``;
    2. ``S_i = M P_i``; edges with both ``w_S <= tol`` are dropped; an edge from
       ``w_a > tol`` to ``w_b <= tol`` becomes the outgoing direction vertex ``D`` and the
       reverse edge the incoming one (``t* = w_a / (w_a - w_b)``);
    3. between an outgoing and the next incoming direction the arc of directions swept
       counter-clockwise in ground ``(x, y)`` (``delta in (0, 2 pi]``) is subdivided
       into ``ceil(delta / 60 deg)`` equal steps so that every at-infinity sub-edge spans
       less than 90 degrees.

    Returns ``{"vertices": (k, 4) homogeneous ground polygon (direction vertices have
    w = 0 exactly), "unbounded": bool, "sources": per-vertex provenance (int index of the
    input vertex, ("ground", i, j) for a ground-clip crossing, ("dir", i, j) for the
    direction of edge i -> j, ("arc", k) for the k-th inserted sweep vertex),
    "below_ground": bool (some input vertex was below the receiver)}``.
    A loop with all vertices at ``w <= tol`` yields an empty polygon.
    """
    M = np.asarray(M, dtype=np.float64).reshape(4, 4)
    pi = np.asarray(pi, dtype=np.float64).reshape(4)
    if tol_clip is None:
        tol_clip = tol
    P, src, below = clip_loop_to_plane(points4, pi, tol_clip)
    n = P.shape[0]
    empty = {"vertices": np.zeros((0, 4), dtype=np.float64), "unbounded": False,
             "sources": [], "below_ground": below}
    if n == 0:
        return empty
    S = P @ M.T                                      # S_i = M P_i, spec §5.2
    w = S[:, 3]
    finite = w > tol
    if not np.any(finite):
        return empty
    F = _light_foot_from_matrix(M, pi)  # only used when an edge passes through the light

    # rotate so that we start at a finite vertex
    start = int(np.argmax(finite))
    order = [(start + k) % n for k in range(n)]
    verts: list[np.ndarray] = []
    sources: list = []
    kinds: list[str] = []      # "finite" | "out" | "in"
    for idx in range(n):
        a = order[idx]
        b = order[(idx + 1) % n]
        wa, wb = float(w[a]), float(w[b])
        if finite[a]:
            verts.append(S[a])
            sources.append(src[a])
            kinds.append("finite")
            if not finite[b]:
                verts.append(_direction_vertex(S[a], wa, S[b], wb, F))
                sources.append(("dir", src[a], src[b]))
                kinds.append("out")
        else:
            if finite[b]:
                verts.append(_direction_vertex(S[a], wa, S[b], wb, F))
                sources.append(("dir", src[a], src[b]))
                kinds.append("in")
            # both not finite: edge dropped

    # insert the arcs at infinity between each outgoing and the following incoming direction
    out_verts: list[np.ndarray] = []
    out_sources: list = []
    m = len(verts)
    unbounded = False
    for k in range(m):
        out_verts.append(verts[k])
        out_sources.append(sources[k])
        if kinds[k] == "out":
            unbounded = True
            nxt = (k + 1) % m
            assert kinds[nxt] == "in", "an outgoing direction must be followed by an incoming one"
            d_out = verts[k]
            d_in = verts[nxt]
            th0 = math.atan2(d_out[1], d_out[0])
            th1 = math.atan2(d_in[1], d_in[0])
            delta = (th1 - th0) % (2.0 * math.pi)
            if not math.isfinite(delta) or delta <= 1e-12:
                delta = 2.0 * math.pi
            steps = max(1, int(math.ceil(delta / math.radians(ARC_STEP_DEG) - 1e-12)))
            for s in range(1, steps):
                th = th0 + delta * s / steps
                out_verts.append(np.array([math.cos(th), math.sin(th), 0.0, 0.0]))
                out_sources.append(("arc", s - 1))
    vertices = np.array(out_verts, dtype=np.float64).reshape(-1, 4)
    return {"vertices": vertices, "unbounded": unbounded, "sources": out_sources,
            "below_ground": below}
