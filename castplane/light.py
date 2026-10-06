"""Light vectors, lit tests and silhouette extraction (spec §5.1, contract §2.3 / §2.5).

All functions are pure and operate on the plain mesh dict of contract §2.4::

    vertices     (n,3) float64 world coordinates
    edges        (m,2) int, each edge once, i<j
    faces        list of int lists, CCW seen from outside, planar
    face_normals (k,3) outward unit normals
    edge_faces   (m,2) int, the two faces adjacent to each edge

Only numpy is used.  Tolerances are passed in by the caller (contract §2.8:
``tol = 1e-9 * scene_scale`` for point lights, ``tol_dir = 1e-9`` for directional
lights); every predicate is strict (``> tol``) and the band ``|.| <= tol`` counts as
the degenerate ("parallel", not lit) side.
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "light_vector",
    "lit",
    "is_parallel",
    "lit_state",
    "face_lit_flags",
    "silhouette_edges",
    "silhouette_loops",
]


def light_vector(light: dict) -> np.ndarray:
    """Homogeneous light vector ``L`` (spec §5.1, contract §2.3).

    Point light ``{"type": "point", "position": [x, y, z]}`` -> ``(x, y, z, 1)``;
    directional light ``{"type": "directional", "direction": [dx, dy, dz]}`` with the
    direction pointing *towards* the light -> ``(dx, dy, dz, 0)``.
    """
    kind = light.get("type")
    if kind == "point":
        pos = np.asarray(light["position"], dtype=np.float64).reshape(3)
        return np.array([pos[0], pos[1], pos[2], 1.0], dtype=np.float64)
    if kind == "directional":
        d = np.asarray(light["direction"], dtype=np.float64).reshape(3)
        return np.array([d[0], d[1], d[2], 0.0], dtype=np.float64)
    raise ValueError("light.type must be 'point' or 'directional', got %r" % (kind,))


def _lit_value(n_f: np.ndarray, p: np.ndarray, L: np.ndarray) -> float:
    """The signed quantity ``n_f . (l - w p)`` of spec §5.1."""
    n_f = np.asarray(n_f, dtype=np.float64).reshape(3)
    p = np.asarray(p, dtype=np.float64).reshape(3)
    L = np.asarray(L, dtype=np.float64).reshape(4)
    return float(n_f[0] * (L[0] - L[3] * p[0])
                 + n_f[1] * (L[1] - L[3] * p[1])
                 + n_f[2] * (L[2] - L[3] * p[2]))


def lit(n_f, p, L, tol: float = 0.0) -> bool:
    """Spec §5.1: ``lit(f) <=> n_f . (l - w p) > tol`` for a face with outward normal
    ``n_f`` containing the point ``p``; ``L = (l, w)`` is the homogeneous light vector.

    The band ``|n_f . (l - w p)| <= tol`` is "parallel" and counts as not lit
    (contract §2.3, spec §5.7 row 6); see :func:`is_parallel`.
    """
    return _lit_value(n_f, p, L) > tol


def is_parallel(n_f, p, L, tol: float = 0.0) -> bool:
    """True when the face is parallel to the light within tolerance
    (``|n_f . (l - w p)| <= tol``, spec §5.7 row 6 -> warning ``FACE_PARALLEL_TO_LIGHT``)."""
    return abs(_lit_value(n_f, p, L)) <= tol


def lit_state(n_f, p, L, tol: float = 0.0) -> tuple[bool, bool]:
    """``(lit, parallel)`` for one face (spec §5.1 / §5.7 row 6); ``parallel`` implies ``not lit``."""
    v = _lit_value(n_f, p, L)
    return (v > tol, abs(v) <= tol)


def face_lit_flags(mesh: dict, L, tol: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised :func:`lit_state` over all faces of a mesh (spec §5.1).

    The representative point ``p`` of each face is its first vertex (any point of a
    planar face gives the same value).  Returns ``(lit_flags, parallel_flags)``, two
    ``(k,)`` bool arrays; ``parallel_flags`` is the per-face evidence for the
    ``FACE_PARALLEL_TO_LIGHT`` warning.
    """
    L = np.asarray(L, dtype=np.float64).reshape(4)
    normals = np.asarray(mesh["face_normals"], dtype=np.float64)
    vertices = np.asarray(mesh["vertices"], dtype=np.float64)
    faces = mesh["faces"]
    k = len(faces)
    if k == 0:
        return np.zeros(0, dtype=bool), np.zeros(0, dtype=bool)
    first = np.array([int(f[0]) for f in faces], dtype=np.int64)
    p = vertices[first]                                   # (k,3)
    # n_f . (l - w p), spec §5.1, fixed-shape einsum (contract §2.8 determinism)
    values = np.einsum("ij,ij->i", normals, L[None, :3] - L[3] * p)
    return values > tol, np.abs(values) <= tol


def silhouette_edges(mesh: dict, lit_flags) -> np.ndarray:
    """Indices of the light silhouette edges (spec §5.1 "光輪廓邊"): edges whose two
    adjacent faces have different ``lit`` values.  Returns a sorted int array."""
    lit_flags = np.asarray(lit_flags, dtype=bool)
    edge_faces = np.asarray(mesh["edge_faces"], dtype=np.int64)
    if edge_faces.size == 0:
        return np.zeros(0, dtype=np.int64)
    different = lit_flags[edge_faces[:, 0]] != lit_flags[edge_faces[:, 1]]
    return np.nonzero(different)[0].astype(np.int64)


def _directed_silhouette_edges(mesh: dict, lit_flags: np.ndarray) -> list[tuple[int, int]]:
    """Each silhouette edge directed as it appears in the cycle of its *lit* face.

    Faces are CCW seen from outside, so walking a directed edge of the lit face's
    cycle keeps that face on the left when viewed from its outside, i.e. from the
    light's side (contract §2.5).
    """
    edges = np.asarray(mesh["edges"], dtype=np.int64)
    edge_faces = np.asarray(mesh["edge_faces"], dtype=np.int64)
    faces = mesh["faces"]
    out: list[tuple[int, int]] = []
    for e in silhouette_edges(mesh, lit_flags):
        f0, f1 = int(edge_faces[e, 0]), int(edge_faces[e, 1])
        lit_face = f0 if lit_flags[f0] else f1
        cycle = [int(v) for v in faces[lit_face]]
        i, j = int(edges[e, 0]), int(edges[e, 1])
        n = len(cycle)
        directed = None
        for k in range(n):
            a, b = cycle[k], cycle[(k + 1) % n]
            if a == i and b == j:
                directed = (i, j)
                break
            if a == j and b == i:
                directed = (j, i)
                break
        if directed is None:  # inconsistent mesh; keep the stored order
            directed = (i, j)
        out.append(directed)
    return out


def silhouette_loops(mesh: dict, lit_flags) -> list[list[int]]:
    """Walk the silhouette edges into closed vertex-index loops (contract §2.5).

    Every loop is oriented with the **lit face on the left as seen from the light**;
    under the shadow matrix such a loop maps to a polygon that is counter-clockwise in
    ground ``(x, y)`` (verified numerically in ``tests/test_light_shadow.py``).
    Each loop is a list of vertex indices without the closing repeat.  Vertices where
    several silhouette edges meet are resolved by always taking the lowest-index unused
    outgoing edge, which is deterministic and correct for the nonzero fill rule.
    """
    lit_flags = np.asarray(lit_flags, dtype=bool)
    directed = _directed_silhouette_edges(mesh, lit_flags)
    if not directed:
        return []
    outgoing: dict[int, list[int]] = {}
    for idx, (a, _b) in enumerate(directed):
        outgoing.setdefault(a, []).append(idx)
    used = [False] * len(directed)
    loops: list[list[int]] = []
    for start in range(len(directed)):
        if used[start]:
            continue
        loop: list[int] = []
        cur = start
        while True:
            used[cur] = True
            a, b = directed[cur]
            loop.append(a)
            nxt = None
            for cand in outgoing.get(b, []):
                if not used[cand]:
                    nxt = cand
                    break
            if nxt is None:
                break  # loop closed (b == loop[0]) or the mesh is not closed
            cur = nxt
        loops.append(loop)
    return loops
