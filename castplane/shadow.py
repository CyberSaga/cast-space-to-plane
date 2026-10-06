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

from .homogeneous import to_homogeneous
from .mesh import mesh_from_faces

__all__ = [
    "shadow_matrix",
    "foot",
    "shadow_w",
    "clip_loop_to_plane",
    "clip_mesh_to_plane",
    "shadow_loop",
    "ARC_STEP_DEG",
    "receiver_frame",
    "bounds_functionals",
    "clip_polygon_bounds",
    "plate_loop",
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


def clip_mesh_to_plane(mesh: dict, pi, tol: float = 0.0) -> tuple[dict, list]:
    """Contract §2.3 ground clip of a whole closed mesh: the part of the solid on the side
    ``pi^T X >= 0`` as a new closed mesh (contract §2.4 dict), so that its silhouette loops
    are those of "the part above the ground", cut face included.

    Every face polygon is clipped with :func:`clip_loop_to_plane` (crossing points are shared
    through the crossed edge); the open boundary left by the dropped parts (directed edges
    that occur in a single clipped face) is chained into cap faces oriented with their
    outward normal ``-n`` (the cap is the bottom of the kept part).  Returns
    ``(clipped_mesh, origins)`` where ``origins[k]`` is the original vertex index (int) of
    the ``k``-th clipped vertex or ``("ground", i, j)`` for the crossing of the original
    edge ``i-j`` (``i < j``), which lies on the plane and is its own shadow and foot.
    Raises ``ValueError`` when the clipped surface is not a closed manifold (a degenerate
    contact with the plane); callers fall back to clipping the silhouette loops only.
    """
    pi = np.asarray(pi, dtype=np.float64).reshape(4)
    V = np.asarray(mesh["vertices"], dtype=np.float64).reshape(-1, 3)
    V4 = to_homogeneous(V)
    f = V4 @ pi
    kept = f >= -tol
    new_vertices: list = []
    origins: list = []
    index_of = {}
    for k in range(V.shape[0]):
        if kept[k]:
            index_of[k] = len(new_vertices)
            new_vertices.append(V[k])
            origins.append(k)
    crossing: dict = {}
    faces_out: list = []
    for face in mesh["faces"]:
        face = [int(v) for v in face]
        P, src, _below = clip_loop_to_plane(V4[face], pi, tol, sources=face)
        if P.shape[0] < 3:
            continue
        poly = []
        for row, s in zip(P, src):
            if isinstance(s, tuple):
                i, j = int(s[1]), int(s[2])
                key = (min(i, j), max(i, j))
                if key not in crossing:
                    crossing[key] = len(new_vertices)
                    new_vertices.append(row[:3] / row[3])
                    origins.append(("ground", key[0], key[1]))
                poly.append(crossing[key])
            else:
                poly.append(index_of[int(s)])
        faces_out.append(poly)
    # cap faces: the reversed boundary edges chained into loops (lowest-index unused outgoing edge)
    directed = set()
    for poly in faces_out:
        for a in range(len(poly)):
            directed.add((poly[a], poly[(a + 1) % len(poly)]))
    boundary = sorted((q, p) for (p, q) in directed if (q, p) not in directed)
    outgoing: dict = {}
    for idx, (a, _b) in enumerate(boundary):
        outgoing.setdefault(a, []).append(idx)
    used = [False] * len(boundary)
    cap_loops = []
    for start in range(len(boundary)):
        if used[start]:
            continue
        loop = []
        cur = start
        while True:
            used[cur] = True
            a, b = boundary[cur]
            loop.append(a)
            nxt = None
            for cand in outgoing.get(b, []):
                if not used[cand]:
                    nxt = cand
                    break
            if nxt is None:
                break
            cur = nxt
        if len(loop) >= 3:
            cap_loops.append(loop)
    vertices = np.array(new_vertices, dtype=np.float64).reshape(-1, 3)
    faces_out.extend(_cap_faces(cap_loops, vertices, pi[:3]))
    if not faces_out:  # the whole solid is below the plane: nothing is left to cast a shadow
        empty = {"vertices": np.zeros((0, 3)), "edges": np.zeros((0, 2), dtype=np.int64), "faces": [],
                 "face_normals": np.zeros((0, 3)), "edge_faces": np.zeros((0, 2), dtype=np.int64),
                 "vertex_names": []}
        return empty, []
    names = [f"v{o}" if isinstance(o, int) else f"x{o[1]}_{o[2]}" for o in origins]
    clipped = mesh_from_faces(vertices, faces_out, names)
    return clipped, origins


def _plane_basis(n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Orthonormal ``(e1, e2)`` spanning the plane with normal ``n`` (``e1 × e2`` along ``n``)."""
    n = n / np.linalg.norm(n)
    helper = np.array([0.0, 0.0, 1.0]) if abs(n[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    e1 = np.cross(helper, n)
    e1 = e1 / np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    return e1, e2


def _signed_area(uv: np.ndarray) -> float:
    """Shoelace area of a closed 2-D loop (positive when counter-clockwise)."""
    x, y = uv[:, 0], uv[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _point_in_loop(p: np.ndarray, uv: np.ndarray) -> bool:
    """Even-odd point-in-polygon test of ``p`` against the closed 2-D loop ``uv``."""
    inside = False
    k = uv.shape[0]
    for i in range(k):
        x0, y0 = uv[i]
        x1, y1 = uv[(i + 1) % k]
        if (y0 > p[1]) != (y1 > p[1]):
            xint = x0 + (p[1] - y0) * (x1 - x0) / (y1 - y0)
            if p[0] < xint:
                inside = not inside
    return inside


def _cap_faces(cap_loops: list, vertices: np.ndarray, n: np.ndarray) -> list:
    """Turn the chained boundary loops of the ground clip into cap faces (contract §2.3 / §2.4).

    The cut of a solid by the plane is a set of regions, each possibly with
    holes (a tilted concave prism whose notch dips below the ground).  A loop
    running counter-clockwise about ``-n`` is an outer boundary; one running the
    other way is a hole, and it is bridged into the outer loop that contains it
    (keyhole polygon: the bridge edge is traversed twice and cancels out), so
    that every cap is ONE face with outward normal ``-n`` and the hole edges
    keep the cap, not a spurious upward face, as their second face.
    """
    if not cap_loops:
        return []
    e1, e2 = _plane_basis(np.asarray(n, dtype=np.float64))
    uv_of = [np.stack([vertices[loop] @ e1, vertices[loop] @ e2], axis=1) for loop in cap_loops]
    areas = [_signed_area(uv) for uv in uv_of]
    # the cap's outward normal is -n: an outer loop is clockwise in the (e1, e2) frame of n
    outer = [k for k, a in enumerate(areas) if a < 0.0]
    holes = [k for k, a in enumerate(areas) if a >= 0.0]
    polys = {k: list(cap_loops[k]) for k in outer}
    orphan = []
    for h in holes:
        p = uv_of[h][0]
        containing = [k for k in outer if _point_in_loop(p, uv_of[k])]
        if not containing:
            orphan.append(list(cap_loops[h]))
            continue
        k = min(containing, key=lambda idx: abs(areas[idx]))
        # bridge between the closest (outer vertex, hole vertex) pair
        d = uv_of[k][:, None, :] - uv_of[h][None, :, :]
        i, j = np.unravel_index(int(np.argmin(np.einsum("ijk,ijk->ij", d, d))), d.shape[:2])
        hole = list(cap_loops[h])
        rotated = hole[j:] + hole[:j]
        poly = polys[k]
        pos = poly.index(cap_loops[k][i])
        polys[k] = poly[:pos + 1] + rotated + [rotated[0], cap_loops[k][i]] + poly[pos + 1:]
    return [polys[k] for k in outer] + orphan


def _direction_vertex(S_a: np.ndarray, w_a: float, S_b: np.ndarray, w_b: float,
                      fallback_from: np.ndarray | None, last_resort: np.ndarray | None = None) -> np.ndarray:
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
            # contract §5.1.2: the last resort is (e1, 0) of the receiver frame ((1, 0, 0, 0) on the ground)
            return np.array([1.0, 0.0, 0.0, 0.0]) if last_resort is None else np.array(last_resort, dtype=np.float64)
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


def shadow_loop(points4, M, pi, tol: float = 0.0, tol_clip: float | None = None, frame=None, F=None) -> dict:
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

    M4 (contract §5.1.2): ``frame = (e1, e2)`` (:func:`receiver_frame`) is given for every receiver
    other than the unbounded ground; the arc at infinity is then swept counter-clockwise about ``n`` in
    ``(e1, e2)`` coordinates and the last-resort direction is ``(e1, 0)``.  ``F`` is the light foot on
    the receiver (used by the "edge through the light" fallback; recovered from ``M`` when ``None`` and
    the receiver is the ground).  ``frame is None`` runs the literal v2 code (byte identity on the ground).
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
    if frame is None:
        F = _light_foot_from_matrix(M, pi)  # only used when an edge passes through the light
        last_resort = None
    else:
        e1, e2 = (np.asarray(e, dtype=np.float64).reshape(3) for e in frame)
        if F is not None:
            F = np.asarray(F, dtype=np.float64).reshape(4)
            F = F / F[3] if abs(float(F[3])) > 1e-300 else None
        last_resort = np.array([e1[0], e1[1], e1[2], 0.0])

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
                verts.append(_direction_vertex(S[a], wa, S[b], wb, F, last_resort))
                sources.append(("dir", src[a], src[b]))
                kinds.append("out")
        else:
            if finite[b]:
                verts.append(_direction_vertex(S[a], wa, S[b], wb, F, last_resort))
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
            if frame is None:   # the ground: literal v2 expressions (contract §5.1.2 [decision])
                th0 = math.atan2(d_out[1], d_out[0])
                th1 = math.atan2(d_in[1], d_in[0])
            else:               # counter-clockwise about n in the receiver frame (e1, e2)
                th0 = math.atan2(float(d_out[:3] @ e2), float(d_out[:3] @ e1))
                th1 = math.atan2(float(d_in[:3] @ e2), float(d_in[:3] @ e1))
            delta = (th1 - th0) % (2.0 * math.pi)
            if not math.isfinite(delta) or delta <= 1e-12:
                delta = 2.0 * math.pi
            steps = max(1, int(math.ceil(delta / math.radians(ARC_STEP_DEG) - 1e-12)))
            for s in range(1, steps):
                th = th0 + delta * s / steps
                if frame is None:
                    out_verts.append(np.array([math.cos(th), math.sin(th), 0.0, 0.0]))
                else:
                    v = math.cos(th) * e1 + math.sin(th) * e2
                    out_verts.append(np.array([v[0], v[1], v[2], 0.0]))
                out_sources.append(("arc", s - 1))
    vertices = np.array(out_verts, dtype=np.float64).reshape(-1, 4)
    return {"vertices": vertices, "unbounded": unbounded, "sources": out_sources,
            "below_ground": below}


# ---------------------------------------------------------------------------
# M4: bounded receivers (contract §5.1.2, §5.1.3)
# ---------------------------------------------------------------------------

def receiver_frame(n) -> tuple[np.ndarray, np.ndarray]:
    """Contract §5.1.2: ``(e1, e2)`` with ``e1 × e2 = n``: ``e1 = normalize(z × n)``, ``e2 = n × e1``;
    when ``|z × n| <= 1e-9``: ``e1 = (1, 0, 0)``, ``e2 = n × e1``.  For the ground this is ``(x, y)``.
    "Counter-clockwise about ``n``" means counter-clockwise in these coordinates."""
    n = np.asarray(n, dtype=np.float64).reshape(3)
    c = np.array([-n[1], n[0], 0.0])                      # z × n
    norm = float(np.linalg.norm(c))
    e1 = np.array([1.0, 0.0, 0.0]) if norm <= 1e-9 else c / norm
    e2 = np.cross(n, e1)
    return e1, e2


def bounds_functionals(bounds, n) -> np.ndarray:
    """Contract §5.1.2: ``Psi (k, 4)``, row ``k`` is ``psi_k = (m_k, -m_k · b_k)`` with the unit inward
    normal ``m_k = n × (b_{k+1} - b_k) / |b_{k+1} - b_k|`` of the counter-clockwise (about ``n``) bounds
    polygon, so that ``psi_k · X`` is the signed distance to edge ``k`` times ``w`` for a finite ``X`` and
    ``m_k · d`` for a direction ``(d, 0)``.  A point of the plane is inside iff ``psi_k · X >= 0`` for all ``k``."""
    B = np.asarray(bounds, dtype=np.float64).reshape(-1, 3)
    n = np.asarray(n, dtype=np.float64).reshape(3)
    E = np.roll(B, -1, axis=0) - B
    m = np.cross(n[None, :], E)
    m = m / np.linalg.norm(E, axis=1)[:, None]
    return np.concatenate([m, -np.einsum("ij,ij->i", m, B)[:, None]], axis=1)


def _merge_equal_neighbours(P: list, src: list) -> tuple[list, list]:
    """Merge consecutive (cyclic) projectively equal vertices, keeping the first (contract §5.1.3.3 rule 5)."""
    if len(P) < 2:
        return P, src
    N = [v / float(np.max(np.abs(v))) if float(np.max(np.abs(v))) > 0.0 else v for v in P]
    keep_p, keep_s, keep_n = [P[0]], [src[0]], [N[0]]
    for v, s, nv in zip(P[1:], src[1:], N[1:]):
        if float(np.max(np.abs(nv - keep_n[-1]))) <= 1e-9:
            continue
        keep_p.append(v)
        keep_s.append(s)
        keep_n.append(nv)
    while len(keep_p) >= 2 and float(np.max(np.abs(keep_n[-1] - keep_n[0]))) <= 1e-9:
        keep_p.pop()
        keep_s.pop()
        keep_n.pop()
    return keep_p, keep_s


def clip_polygon_bounds(points4, sources, psi, bounds, tol: float) -> tuple[np.ndarray, list]:
    """Contract §5.1.3.3: Sutherland–Hodgman of an oriented homogeneous shadow polygon (direction
    vertices ``w = 0`` and arcs at infinity included) against ``psi_k · X >= 0`` in row order.

    1. band: a vertex is kept iff ``f_i >= -tol·|w_i|`` (strict ``>= 0`` for directions); a kept vertex
       inside its band is its own crossing (no crossing is inserted next to it);
    2. crossings ``(f_a B - f_b A) / (f_a - f_b)`` get the source ``("bounds", k, src_a, src_b)``; a
       zero-vector interpolation (antipodal directions) is dropped;
    3. anchor rule: two consecutive output directions on the clip line (``|psi_k · D| <= 1e-9 max|D|``)
       that are antipodal get the edge's start vertex ``(b_k, 1)`` inserted between them, source
       ``("bounds", k, "anchor")``;
    4. fewer than three vertices after any row: empty;
    5. after the last row: projectively equal neighbours are merged (keeping the first), vertices with
       ``w <= 0`` dropped, and a sliver (``|area| <= tol · perimeter``) is empty.

    Returns ``(points4' (m, 4), sources')``; ``m == 0`` when the polygon misses the plate."""
    P = [np.asarray(v, dtype=np.float64).reshape(4) for v in np.asarray(points4, dtype=np.float64).reshape(-1, 4)]
    src = list(sources)
    Psi = np.asarray(psi, dtype=np.float64).reshape(-1, 4)
    B = np.asarray(bounds, dtype=np.float64).reshape(-1, 3)
    empty = (np.zeros((0, 4), dtype=np.float64), [])
    if len(P) < 3:
        return empty
    scale = max(float(np.max(np.abs(np.array(P)))), 0.0)
    for k in range(Psi.shape[0]):
        if len(P) < 3:
            return empty
        row = Psi[k]
        f = [float(row @ X) for X in P]
        w = [abs(float(X[3])) for X in P]
        keep = [fi >= -tol * wi if wi != 0.0 else fi >= 0.0 for fi, wi in zip(f, w)]
        band = [abs(fi) <= tol * wi for fi, wi in zip(f, w)]
        n = len(P)
        out, out_src = [], []
        if all(keep):
            out, out_src = list(P), list(src)
        else:
            for a in range(n):
                b = (a + 1) % n
                if keep[a]:
                    out.append(P[a])
                    out_src.append(src[a])
                if keep[a] != keep[b]:
                    if (keep[a] and band[a]) or (keep[b] and band[b]):
                        continue
                    fa, fb = f[a], f[b]
                    X = (fa * P[b] - fb * P[a]) / (fa - fb)
                    if not float(np.max(np.abs(X))) > 1e-12 * max(scale, float(np.max(np.abs(P[a]))),
                                                                   float(np.max(np.abs(P[b])))):
                        continue                         # antipodal directions: no projective point
                    out.append(X)
                    out_src.append(("bounds", k, src[a], src[b]))
        # anchor rule (exactness for arcs at infinity spanning >= 180 degrees)
        if len(out) >= 2:
            anchored, anchored_src = [], []
            m = len(out)
            for a in range(m):
                anchored.append(out[a])
                anchored_src.append(out_src[a])
                Da, Db = out[a], out[(a + 1) % m]
                if Da[3] == 0.0 and Db[3] == 0.0 and m >= 2:
                    on_a = abs(float(row @ Da)) <= 1e-9 * float(np.max(np.abs(Da)))
                    on_b = abs(float(row @ Db)) <= 1e-9 * float(np.max(np.abs(Db)))
                    if on_a and on_b and float(Da[:3] @ Db[:3]) < 0.0:
                        anchored.append(np.array([B[k, 0], B[k, 1], B[k, 2], 1.0]))
                        anchored_src.append(("bounds", k, "anchor"))
            out, out_src = anchored, anchored_src
        P, src = out, out_src
        if len(P) < 3:
            return empty
    P, src = _merge_equal_neighbours(P, src)
    kept = [(v, s) for v, s in zip(P, src) if float(v[3]) > 0.0]
    if len(kept) < 3:
        return empty
    V = np.array([v for v, _s in kept], dtype=np.float64)
    X = V[:, :3] / V[:, 3:4]
    Xn = np.roll(X, -1, axis=0)
    area = 0.5 * float(np.linalg.norm(np.sum(np.cross(X, Xn), axis=0)))
    perimeter = float(np.sum(np.linalg.norm(Xn - X, axis=1)))
    if area <= tol * perimeter:
        return empty
    return V, [s for _v, s in kept]


def plate_loop(bounds, pi, L, tol: float):
    """Contract §5.1.3.2: the silhouette loop of a bounded receiver used as a caster (an opaque plate):
    its whole boundary, in the stored counter-clockwise order when the light is on the positive side of
    its plane (``pi^T L > tol``), reversed when it is on the negative side (``< -tol``); ``None`` when the
    plate is edge-on to the light (``|pi^T L| <= tol``: it casts nothing).  Returns ``(loop4 (k, 4),
    vertex_ids)`` with ``vertex_ids[i]`` the index ``k`` of ``b<k>``."""
    B = np.asarray(bounds, dtype=np.float64).reshape(-1, 3)
    piL = float(np.asarray(pi, dtype=np.float64).reshape(4) @ np.asarray(L, dtype=np.float64).reshape(4))
    if abs(piL) <= tol:
        return None
    ids = list(range(B.shape[0]))
    if piL < 0.0:
        ids = ids[::-1]
    return to_homogeneous(B[ids]), ids
