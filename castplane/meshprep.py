"""Mesh preprocessing of the ``mesh`` object type (spec §9 網格匯入; contract §5.2.3 – §5.2.5).

Core module: numpy / stdlib only, no file access, every step deterministic and order-defined
(the TypeScript port reproduces it, contract §5.2.9).  The entry point is

    preprocess_mesh(data, scale, weld_tolerance, smooth_angle_deg) -> (mesh, triangles, fallback,
                                                                       smooth_groups, warnings)

with the steps of contract §5.2.3 in this order: scale -> weld -> degenerate faces -> adjacency /
manifold / orientation -> (triangles) -> coplanar merge -> edge classification.  A mesh that is
not a closed, consistently orientable manifold takes the per-face fallback of §5.2.5
(:func:`fallback_mesh`).

Every tolerance of this module is relative to ``scale_A = max(1, max extent of the bounding box
of scale·vertices)`` (:func:`mesh_scale`).
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np

from .errors import make_warning
from .mesh import _group_faces, face_normals_newell, mesh_from_faces, triangulate_faces

__all__ = [
    "COPLANAR_TOL_RAD",
    "WELD_TOLERANCE_DEFAULT",
    "SMOOTH_ANGLE_DEFAULT",
    "MESH_MAX_RAYS",
    "SMOOTH_BAND",
    "INSIDE_WINDING",
    "mesh_scale",
    "weld_map",
    "weld_vertices",
    "prepare_faces",
    "drop_degenerate_faces",
    "compact_vertices",
    "triangulate",
    "build_adjacency",
    "fix_orientation",
    "signed_volume",
    "winding_number",
    "merge_coplanar",
    "classify_edges",
    "fallback_mesh",
    "inherit_edge_smooth",
    "point_inside_mesh",
    "preprocess_mesh",
]

#: Coplanar-merge angle (contract §5.2.3 step 6).
COPLANAR_TOL_RAD = 1e-3
#: Default weld tolerance in metres, after ``scale`` (contract §5.2.1).
WELD_TOLERANCE_DEFAULT = 1e-6
#: Default smoothing angle in degrees (contract §5.2.1).
SMOOTH_ANGLE_DEFAULT = 30.0
#: Construction rays per (object, light, receiver) (contract §5.2.4).
MESH_MAX_RAYS = 64
#: Dimensionless band of the smooth-edge test (contract §5.2.3 step 7).
SMOOTH_BAND = 1e-9
#: ``|w| > INSIDE_WINDING`` means inside (generalised winding number, contract §5.2.3 step 8).
INSIDE_WINDING = 0.75
#: Newell-norm threshold of a degenerate face, relative to ``scale_A²`` (contract §5.2.3 step 3).
DEGENERATE_REL = 1e-12
#: Zero-volume threshold of a component, relative to ``scale_A³`` (contract §5.2.3 step 5).
VOLUME_REL = 1e-12

_OFFSETS = tuple((dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1))
_INT64_SAFE = float(2 ** 62)


def mesh_scale(V) -> float:
    """``scale_A = max(1, max extent of the axis-aligned bounding box of V)`` (contract §5.2.3 step 1)."""
    V = np.asarray(V, dtype=np.float64).reshape(-1, 3)
    if V.shape[0] == 0:
        return 1.0
    return max(1.0, float(np.max(V.max(axis=0) - V.min(axis=0))))


# ---------------------------------------------------------------------------
# step 2: weld
# ---------------------------------------------------------------------------

def _cell_quotients(V: np.ndarray, tol: float):
    """``x/τ + 0.5`` per coordinate (the cell key is its floor), or ``None`` for exact welding
    (``τ = 0``, or a ``τ`` so small that ``x/τ`` overflows: then no two distinct floats are within
    ``τ`` of each other except near 0, which such a ``τ`` cannot be meant for)."""
    if not tol > 0.0:
        return None
    with np.errstate(over="ignore", invalid="ignore"):
        q = V / tol + 0.5
    if not bool(np.all(np.isfinite(q))):
        return None
    return q


def _weld_reference(V: np.ndarray, tol: float) -> np.ndarray:
    """The reference O(27·n) loop of contract §5.2.3 step 2: representative input index per vertex."""
    n = V.shape[0]
    rep = np.empty(n, dtype=np.int64)
    Vl = V.tolist()
    q = _cell_quotients(V, tol)
    if q is None:  # tau = 0: exact equality of the float triple (-0.0 == 0.0)
        seen: dict = {}
        for i, p in enumerate(Vl):
            rep[i] = seen.setdefault((p[0], p[1], p[2]), i)
        return rep
    ql = q.tolist()
    cells: dict = {}
    for i in range(n):
        cx, cy, cz = (math.floor(c) for c in ql[i])
        x, y, z = Vl[i]
        best = -1
        for dx, dy, dz in _OFFSETS:
            lst = cells.get((cx + dx, cy + dy, cz + dz))
            if not lst:
                continue
            for r in lst:
                if best >= 0 and r >= best:
                    continue
                a, b, c = Vl[r]
                if abs(a - x) <= tol and abs(b - y) <= tol and abs(c - z) <= tol:
                    best = r
        if best < 0:
            cells.setdefault((cx, cy, cz), []).append(i)
            best = i
        rep[i] = best
    return rep


def _rows_view(a: np.ndarray) -> np.ndarray:
    """``(n, 3)`` int64 rows as a 1-D void array (equality / membership only)."""
    a = np.ascontiguousarray(a, dtype=np.int64)
    return a.view(np.dtype((np.void, a.dtype.itemsize * a.shape[1]))).reshape(-1)


def _weld_fast(V: np.ndarray, tol: float) -> np.ndarray:
    """Vectorised weld, result-identical to :func:`_weld_reference` (tested): a vertex whose cell has
    no occupied neighbour cell and whose cell's vertices are all within ``τ`` of the cell's lowest
    input index is merged into that vertex directly; every other vertex goes through the reference
    loop (restricted to those vertices, which never interact with the isolated cells)."""
    n = V.shape[0]
    q = _cell_quotients(V, tol)
    if q is None or n == 0 or float(np.max(np.abs(q))) >= _INT64_SAFE:
        return _weld_reference(V, tol)
    keys = np.floor(q).astype(np.int64)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    n_cells = uniq.shape[0]
    occupied = np.zeros(n_cells, dtype=bool)
    u_view = _rows_view(uniq)
    for off in _OFFSETS:
        if off == (0, 0, 0):
            continue
        occupied |= np.isin(_rows_view(uniq + np.array(off, dtype=np.int64)), u_view)
    first = np.full(n_cells, n, dtype=np.int64)
    np.minimum.at(first, inv, np.arange(n, dtype=np.int64))
    near = np.max(np.abs(V - V[first[inv]]), axis=1) <= tol
    isolated = ~occupied
    isolated[np.unique(inv[~near])] = False
    rep = np.where(isolated[inv], first[inv], -1).astype(np.int64)
    slow = np.nonzero(~isolated[inv])[0]
    if slow.shape[0]:
        rep[slow] = slow[_weld_reference(V[slow], tol)]
    return rep


def weld_map(V, tol: float, fast: bool = True) -> np.ndarray:
    """Representative **input index** of every vertex under the weld rule of contract §5.2.3 step 2
    (``fast`` selects the vectorised path, which is result-identical to the reference loop)."""
    V = np.asarray(V, dtype=np.float64).reshape(-1, 3)
    return _weld_fast(V, float(tol)) if fast else _weld_reference(V, float(tol))


def prepare_faces(faces, index=None) -> list:
    """Faces as lists of Python ints, optionally renumbered through ``index`` (an ``(n,)`` map)."""
    if index is None:
        return [[int(v) for v in f] for f in faces]
    idx = np.asarray(index, dtype=np.int64).reshape(-1).tolist()
    return [[idx[int(v)] for v in f] for f in faces]


def weld_vertices(V, faces, tol: float, fast: bool = True):
    """Weld (contract §5.2.3 step 2) -> ``(W, faces_w, index)``: ``W`` the representatives' own
    coordinates numbered in order of first appearance, ``faces_w`` the faces renumbered, ``index``
    the ``(n,)`` map input vertex -> welded vertex.  Unused representatives are removed later
    (:func:`compact_vertices`, after the degenerate-face step)."""
    V = np.asarray(V, dtype=np.float64).reshape(-1, 3)
    rep = weld_map(V, tol, fast)
    n = V.shape[0]
    reps = np.nonzero(rep == np.arange(n, dtype=np.int64))[0]
    number = np.full(n, -1, dtype=np.int64)
    number[reps] = np.arange(reps.shape[0], dtype=np.int64)
    index = number[rep]
    return V[reps].copy(), prepare_faces(faces, index), index


# ---------------------------------------------------------------------------
# step 3: degenerate faces
# ---------------------------------------------------------------------------

def _newell_vectors(V: np.ndarray, faces: list) -> np.ndarray:
    """Unnormalised Newell normals (``Σ p_i × p_{i+1}``, the formula of ``mesh.face_normals_newell``)."""
    out = np.zeros((len(faces), 3), dtype=np.float64)
    for _length, (idx, arr) in _group_faces(faces).items():
        p = V[arr]
        q = np.roll(p, -1, axis=1)
        n = np.einsum("klj,klm->kjm", p, q)
        out[idx] = np.stack([n[:, 1, 2] - n[:, 2, 1], n[:, 2, 0] - n[:, 0, 2], n[:, 0, 1] - n[:, 1, 0]], axis=1)
    return out


def _collapse(face) -> list:
    """Collapse consecutive duplicate indices cyclically, keeping the first vertex."""
    g = [int(face[0])]
    for v in face[1:]:
        v = int(v)
        if v != g[-1]:
            g.append(v)
    while len(g) > 1 and g[-1] == g[0]:
        g.pop()
    return g


def drop_degenerate_faces(V, faces, scale_A: float):
    """Contract §5.2.3 step 3 -> ``(kept_faces, kept_index)``: consecutive duplicates collapsed
    (cyclically), then faces with ``< 3`` vertices, with vertices that are not pairwise distinct
    (``[a, b, c, b]``) or with Newell norm ``<= 1e-12·scale_A²`` are dropped.  ``kept_index`` lists
    the input index of every kept face."""
    V = np.asarray(V, dtype=np.float64).reshape(-1, 3)
    cand, cand_idx = [], []
    for k, f in enumerate(faces):
        g = _collapse(f)
        if len(g) < 3 or len(set(g)) != len(g):
            continue
        cand.append(g)
        cand_idx.append(k)
    if not cand:
        return [], []
    norms = np.linalg.norm(_newell_vectors(V, cand), axis=1)
    good = (norms > DEGENERATE_REL * float(scale_A) ** 2).tolist()
    return ([f for f, ok in zip(cand, good) if ok], [k for k, ok in zip(cand_idx, good) if ok])


def compact_vertices(V, faces):
    """Remove the vertices used by no face, keeping the order -> ``(V2, faces2, old_index)``."""
    V = np.asarray(V, dtype=np.float64).reshape(-1, 3)
    used = np.zeros(V.shape[0], dtype=bool)
    for f in faces:
        used[f] = True
    old = np.nonzero(used)[0]
    number = np.full(V.shape[0], -1, dtype=np.int64)
    number[old] = np.arange(old.shape[0], dtype=np.int64)
    return V[old].copy(), prepare_faces(faces, number), old


# ---------------------------------------------------------------------------
# step 4: triangles
# ---------------------------------------------------------------------------

def triangulate(faces) -> np.ndarray:
    """Fan triangulation ``(f0, f_k, f_{k+1})`` of every face, face-major order -> ``(t, 3)`` int
    (``mesh.triangulate_faces`` on the padded face table)."""
    faces = list(faces)
    if not faces:
        return np.zeros((0, 3), dtype=np.int64)
    lens = np.array([len(f) for f in faces], dtype=np.int64)
    padded = np.full((len(faces), int(lens.max())), -1, dtype=np.int64)
    for k, f in enumerate(faces):
        padded[k, :len(f)] = f
    return triangulate_faces(padded, lens)


# ---------------------------------------------------------------------------
# step 5: adjacency, manifold test, orientation
# ---------------------------------------------------------------------------

def build_adjacency(faces, n_v: int) -> dict:
    """Undirected edges ``i < j`` (lexicographic) with their incident faces (distinct face indices,
    ascending) and the direction each face traverses them (``+1``: ``i -> j``, ``-1``: ``j -> i``).

    Returns ``{"edges": (m, 2) int, "edge_faces": [[f, ...]], "edge_dirs": [[±1, ...]],
    "face_edges": [[e, ...] ascending], "face_edge_at": [[e of (f[k], f[k+1]) for k]],
    "counts": (m,) int, "manifold": bool, "consistent": bool}``.  Faces are assumed to have pairwise
    distinct vertices (step 3), so a face meets an edge at most once."""
    n_v = max(int(n_v), 1)
    a_list, b_list, f_list = [], [], []
    for fi, f in enumerate(faces):
        L = len(f)
        for k in range(L):
            a_list.append(f[k])
            b_list.append(f[(k + 1) % L])
            f_list.append(fi)
    a = np.array(a_list, dtype=np.int64)
    b = np.array(b_list, dtype=np.int64)
    fidx = np.array(f_list, dtype=np.int64)
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    keys = lo * n_v + hi
    uniq, inv = np.unique(keys, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    edges = np.stack([uniq // n_v, uniq % n_v], axis=1).astype(np.int64)
    dirs = np.where(a < b, 1, -1)
    order = np.lexsort((fidx, inv))
    m = uniq.shape[0]
    counts = np.bincount(inv, minlength=m)
    bounds = np.concatenate([[0], np.cumsum(counts)]).tolist()
    f_sorted = fidx[order].tolist()
    d_sorted = dirs[order].tolist()
    edge_faces = [f_sorted[bounds[e]:bounds[e + 1]] for e in range(m)]
    edge_dirs = [d_sorted[bounds[e]:bounds[e + 1]] for e in range(m)]
    inv_l = inv.tolist()
    face_edge_at, pos = [], 0
    for f in faces:
        face_edge_at.append(inv_l[pos:pos + len(f)])
        pos += len(f)
    face_edges = [sorted(row) for row in face_edge_at]
    manifold = bool(np.all(counts == 2))
    consistent = manifold and all(d[0] != d[1] for d in edge_dirs)
    return {"edges": edges, "edge_faces": edge_faces, "edge_dirs": edge_dirs, "face_edges": face_edges,
            "face_edge_at": face_edge_at, "counts": counts.astype(np.int64), "manifold": manifold,
            "consistent": consistent}


def _flip_face(f) -> list:
    """Reverse a face keeping its start vertex: ``[f0] + f[1:][::-1]``."""
    return [f[0]] + list(f[1:])[::-1]


def fix_orientation(faces, adjacency: dict):
    """Orientation propagation over the face adjacency graph of a manifold mesh (contract §5.2.3
    step 5): BFS per connected component from its lowest-index face, FIFO queue, neighbours in
    ascending edge index; a face is flipped when it traverses the shared edge in the same direction
    as its already-oriented neighbour.  Returns ``(faces_out, flipped (F,) bool, components
    [[face indices ascending]], conflict)``; ``conflict`` (a face reached with contradicting
    requirements, e.g. a Klein-bottle connectivity) means "not manifold"."""
    F = len(faces)
    flip = [False] * F
    comp = [-1] * F
    components = []
    conflict = False
    edge_faces, edge_dirs, face_edges = adjacency["edge_faces"], adjacency["edge_dirs"], adjacency["face_edges"]
    for s in range(F):
        if comp[s] >= 0:
            continue
        c = len(components)
        members = [s]
        comp[s] = c
        queue = deque([s])
        while queue:
            g = queue.popleft()
            for e in face_edges[g]:
                (f0, f1), (d0, d1) = edge_faces[e], edge_dirs[e]
                if f0 == g:
                    h, dh, dg = f1, d1, d0
                else:
                    h, dh, dg = f0, d0, d1
                eff_g = -dg if flip[g] else dg
                need = dh == eff_g          # same direction as the oriented neighbour -> flip h
                if comp[h] < 0:
                    comp[h] = c
                    flip[h] = need
                    members.append(h)
                    queue.append(h)
                elif flip[h] != need:
                    conflict = True
        components.append(sorted(members))
    out = [_flip_face(f) if fl else list(f) for f, fl in zip(faces, flip)]
    return out, np.array(flip, dtype=bool), components, conflict


def signed_volume(V, tris) -> float:
    """``Σ_tri a·(b×c) / 6``, summed sequentially in triangle order (contract §5.2.3 step 5)."""
    tris = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    if tris.shape[0] == 0:
        return 0.0
    V = np.asarray(V, dtype=np.float64).reshape(-1, 3)
    det = np.einsum("ij,ij->i", V[tris[:, 0]], np.cross(V[tris[:, 1]], V[tris[:, 2]]))
    return float(np.cumsum(det)[-1]) / 6.0


def winding_number(V, tris, x) -> float:
    """Generalised winding number of the triangles about ``x``: Van Oosterom–Strackee solid angles
    ``Ω = 2·atan2(a·(b×c), |a||b||c| + (a·b)|c| + (a·c)|b| + (b·c)|a|)`` summed sequentially in
    triangle order, divided by ``4π`` (contract §5.2.3 step 8)."""
    tris = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    if tris.shape[0] == 0:
        return 0.0
    V = np.asarray(V, dtype=np.float64).reshape(-1, 3)
    x = np.asarray(x, dtype=np.float64).reshape(3)
    a, b, c = V[tris[:, 0]] - x, V[tris[:, 1]] - x, V[tris[:, 2]] - x
    la, lb, lc = (np.sqrt(np.einsum("ij,ij->i", v, v)) for v in (a, b, c))
    num = np.einsum("ij,ij->i", a, np.cross(b, c))
    den = (la * lb * lc + np.einsum("ij,ij->i", a, b) * lc + np.einsum("ij,ij->i", a, c) * lb
           + np.einsum("ij,ij->i", b, c) * la)
    omega = 2.0 * np.arctan2(num, den)
    return float(np.cumsum(omega)[-1]) / (4.0 * math.pi)


def _segment_distances(x, A, B) -> np.ndarray:
    d = B - A
    dd = np.einsum("ij,ij->i", d, d)
    t = np.einsum("ij,ij->i", x[None, :] - A, d)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(dd > 0.0, t / np.where(dd > 0.0, dd, 1.0), 0.0)
    t = np.clip(t, 0.0, 1.0)
    p = A + t[:, None] * d
    return np.linalg.norm(x[None, :] - p, axis=1)


def _point_triangle_distances(V, tris, x) -> np.ndarray:
    """Exact Euclidean distance from ``x`` to every (closed) triangle: the distance to the plane
    when the foot lies inside the triangle, else the distance to the nearest edge (degenerate
    triangles reduce to their edges)."""
    A, B, C = V[tris[:, 0]], V[tris[:, 1]], V[tris[:, 2]]
    dist = np.minimum(np.minimum(_segment_distances(x, A, B), _segment_distances(x, B, C)),
                      _segment_distances(x, C, A))
    n = np.cross(B - A, C - A)
    nn = np.einsum("ij,ij->i", n, n)
    ok = nn > 0.0
    if bool(np.any(ok)):
        ap = x[None, :] - A
        s = np.where(ok, np.einsum("ij,ij->i", ap, n) / np.where(ok, nn, 1.0), 0.0)
        foot = x[None, :] - s[:, None] * n
        # barycentric sign test: the foot is inside iff it is on the inner side of all three edges
        e0 = np.einsum("ij,ij->i", np.cross(B - A, foot - A), n)
        e1 = np.einsum("ij,ij->i", np.cross(C - B, foot - B), n)
        e2 = np.einsum("ij,ij->i", np.cross(A - C, foot - C), n)
        inside = ok & (e0 >= 0.0) & (e1 >= 0.0) & (e2 >= 0.0)
        plane = np.abs(s) * np.sqrt(nn)
        dist = np.where(inside, np.minimum(dist, plane), dist)
    return dist


def point_inside_mesh(verts, tris, x, tol: float = 0.0) -> bool:
    """Contract §5.2.3 step 8: ``x`` is inside the closed mesh ``tris`` iff ``|w| > 0.75`` and the
    point–triangle distance to every triangle is ``> tol`` (a point on the surface within ``tol``
    is outside, as ``primitives._point_in_polygon_margin``)."""
    V = np.asarray(verts, dtype=np.float64).reshape(-1, 3)
    tris = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    x = np.asarray(x, dtype=np.float64).reshape(3)
    if tris.shape[0] == 0:
        return False
    if not abs(winding_number(V, tris, x)) > INSIDE_WINDING:
        return False
    return bool(np.min(_point_triangle_distances(V, tris, x)) > tol)


def _orient_components(V, faces, components, scale_A: float):
    """Volume / nesting-parity orientation of contract §5.2.3 step 5 -> ``(faces_out, flipped_any)``."""
    tris_of = [triangulate([faces[f] for f in comp]) for comp in components]
    vols = [signed_volume(V, t) for t in tris_of]
    thr = VOLUME_REL * float(scale_A) ** 3
    solid = [abs(v) > thr for v in vols]
    out = list(faces)
    flipped = False
    for k, comp in enumerate(components):
        if not solid[k]:
            continue
        x_k = V[min(min(faces[f]) for f in comp)]
        depth = sum(1 for c in range(len(components))
                    if c != k and solid[c] and abs(winding_number(V, tris_of[c], x_k)) > INSIDE_WINDING)
        want_positive = depth % 2 == 0
        if (vols[k] > 0.0) != want_positive:
            for f in comp:
                out[f] = _flip_face(out[f])
            flipped = True
    return out, flipped


# ---------------------------------------------------------------------------
# step 6: coplanar merge
# ---------------------------------------------------------------------------

def _boundary_loops(directed: list) -> list:
    """Chain directed edges ``(a, b)`` (given in ascending undirected-edge order) into loops by the
    lowest-index unused outgoing edge (the rule of ``light.silhouette_loops``)."""
    outgoing: dict = {}
    for idx, (a, _b) in enumerate(directed):
        outgoing.setdefault(a, []).append(idx)
    used = [False] * len(directed)
    loops = []
    for start in range(len(directed)):
        if used[start]:
            continue
        loop, cur = [], start
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
                break
            cur = nxt
        loops.append(loop)
    return loops


def merge_coplanar(V, faces, normals, adjacency: dict, cos_tol: float):
    """Seed-ordered region growing of contract §5.2.3 step 6 (manifold meshes) ->
    ``(new_faces, origin)``.

    Faces are taken in index order; an unassigned face ``s`` seeds a region that grows by BFS over
    the face adjacency (FIFO, neighbours in ascending index of the shared edge); a neighbour ``f``
    reached from ``g`` joins iff it is unassigned, ``n_f·n_s >= cos_tol`` and ``n_f·n_g >= cos_tol``.
    A region whose boundary is one simple loop becomes one face, started at the first vertex of the
    seed's cycle on the boundary (else the lowest-index boundary vertex) and walked in the
    boundary's direction; a region with a hole or a pinch is left unmerged.  Output faces follow the
    seed order (an unmerged region contributes its faces in ascending index at its seed's place);
    ``origin[k]`` is the seed of a merged face or the face itself (smoothing group source)."""
    N = np.asarray(normals, dtype=np.float64).reshape(-1, 3).tolist()
    F = len(faces)
    edge_faces, face_edges, face_edge_at = adjacency["edge_faces"], adjacency["face_edges"], adjacency["face_edge_at"]

    def dot(i, j):
        a, b = N[i], N[j]
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    region = [-1] * F
    new_faces, origin = [], []
    for s in range(F):
        if region[s] >= 0:
            continue
        region[s] = s
        members = [s]
        queue = deque([s])
        while queue:
            g = queue.popleft()
            for e in face_edges[g]:
                ef = edge_faces[e]
                h = ef[1] if ef[0] == g else ef[0]
                if region[h] < 0 and dot(h, s) >= cos_tol and dot(h, g) >= cos_tol:
                    region[h] = s
                    members.append(h)
                    queue.append(h)
        if len(members) == 1:
            new_faces.append(list(faces[s]))
            origin.append(s)
            continue
        member_set = set(members)
        directed = []
        for f in members:
            cyc = faces[f]
            L = len(cyc)
            for k in range(L):
                e = face_edge_at[f][k]
                ef = edge_faces[e]
                other = ef[1] if ef[0] == f else ef[0]
                if other not in member_set:
                    directed.append((e, cyc[k], cyc[(k + 1) % L]))
        directed.sort()
        loops = _boundary_loops([(a, b) for _e, a, b in directed])
        simple = len(loops) == 1 and len(loops[0]) == len(directed) and len(set(loops[0])) == len(loops[0])
        if not simple:
            for f in sorted(members):
                new_faces.append(list(faces[f]))
                origin.append(f)
            continue
        loop = loops[0]
        on_boundary = set(loop)
        start = next((v for v in faces[s] if v in on_boundary), min(loop))
        k = loop.index(start)
        new_faces.append(loop[k:] + loop[:k])
        origin.append(s)
    return new_faces, origin


# ---------------------------------------------------------------------------
# step 7: edge classification
# ---------------------------------------------------------------------------

def classify_edges(mesh: dict, smooth_angle_deg: float, smooth_groups) -> np.ndarray:
    """``edge_smooth (m,) bool`` (contract §5.2.3 step 7): ``(g_a == g_b != 0) or (g_a == g_b == 0 and
    n_a·n_b >= cos(smooth_angle_deg) - 1e-9)``."""
    ef = np.asarray(mesh["edge_faces"], dtype=np.int64).reshape(-1, 2)
    if ef.shape[0] == 0:
        return np.zeros(0, dtype=bool)
    n = np.asarray(mesh["face_normals"], dtype=np.float64)
    g = np.asarray(smooth_groups, dtype=np.int64).reshape(-1)
    ga, gb = g[ef[:, 0]], g[ef[:, 1]]
    d = np.einsum("ij,ij->i", n[ef[:, 0]], n[ef[:, 1]])
    c = math.cos(math.radians(float(smooth_angle_deg))) - SMOOTH_BAND
    same = ga == gb
    return (same & (ga != 0)) | (same & (ga == 0) & (d >= c))


# ---------------------------------------------------------------------------
# §5.2.5: non-manifold fallback mesh
# ---------------------------------------------------------------------------

def fallback_mesh(V, faces, vertex_names=None) -> dict:
    """The §2.4-shaped mesh of a non-manifold mesh (contract §5.2.5): ``faces`` as given, ``edges``
    the unique ``i < j`` pairs, ``edge_faces[e] = [f_min, f_max]`` (equal for a boundary edge),
    ``edge_flipped`` accordingly, Newell ``face_normals``, ``edge_smooth`` all False."""
    V = np.asarray(V, dtype=np.float64).reshape(-1, 3)
    faces = [[int(v) for v in f] for f in faces]
    n_v = max(V.shape[0], 1)
    a_l, b_l, f_l = [], [], []
    for fi, f in enumerate(faces):
        L = len(f)
        for k in range(L):
            a_l.append(f[k])
            b_l.append(f[(k + 1) % L])
            f_l.append(fi)
    a = np.array(a_l, dtype=np.int64)
    b = np.array(b_l, dtype=np.int64)
    fidx = np.array(f_l, dtype=np.int64)
    keys = np.minimum(a, b) * n_v + np.maximum(a, b)
    uniq, inv = np.unique(keys, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    m = uniq.shape[0]
    edges = np.stack([uniq // n_v, uniq % n_v], axis=1).astype(np.int64)
    f_min = np.full(m, len(faces), dtype=np.int64)
    f_max = np.full(m, -1, dtype=np.int64)
    np.minimum.at(f_min, inv, fidx)
    np.maximum.at(f_max, inv, fidx)
    rev = a > b                                   # the face traverses the edge as j -> i
    flip_min = np.zeros(m, dtype=bool)
    flip_max = np.zeros(m, dtype=bool)
    at_min = fidx == f_min[inv]
    at_max = fidx == f_max[inv]
    flip_min[inv[at_min]] = rev[at_min]
    flip_max[inv[at_max]] = rev[at_max]
    if vertex_names is None:
        vertex_names = [f"v{i}" for i in range(V.shape[0])]
    return {
        "vertices": V,
        "edges": edges,
        "faces": faces,
        "face_normals": face_normals_newell(V, faces),
        "edge_faces": np.stack([f_min, f_max], axis=1),
        "edge_flipped": np.stack([flip_min, flip_max], axis=1),
        "vertex_names": list(vertex_names),
        "edge_smooth": np.zeros(m, dtype=bool),
    }


def inherit_edge_smooth(loop_mesh: dict, origins, mesh: dict, edge_smooth) -> np.ndarray:
    """``edge_smooth`` of a receiver-clipped mesh (contract §5.2.4): an edge that is part of an
    original edge inherits its flag (a crossing vertex ``("ground", i, j)`` names that edge);
    cut-face edges (both endpoints crossings) and any other new edge are feature (False)."""
    index = {(int(i), int(j)): e for e, (i, j) in enumerate(np.asarray(mesh["edges"]).tolist())}
    flags = np.asarray(edge_smooth, dtype=bool).tolist()
    out = []
    for a, b in np.asarray(loop_mesh["edges"], dtype=np.int64).reshape(-1, 2).tolist():
        oa, ob = origins[a], origins[b]
        key = None
        if isinstance(oa, tuple) and isinstance(ob, tuple):
            key = None
        elif isinstance(oa, tuple) or isinstance(ob, tuple):
            v, cross = (ob, oa) if isinstance(oa, tuple) else (oa, ob)
            i, j = int(cross[1]), int(cross[2])
            if int(v) in (i, j):
                key = (min(i, j), max(i, j))
        else:
            key = (min(int(oa), int(ob)), max(int(oa), int(ob)))
        e = index.get(key) if key is not None else None
        out.append(bool(flags[e]) if e is not None else False)
    return np.array(out, dtype=bool).reshape(-1)


# ---------------------------------------------------------------------------
# the whole pipeline
# ---------------------------------------------------------------------------

def preprocess_mesh(data: dict, scale: float, weld_tolerance: float, smooth_angle_deg: float,
                    object_id: str = ""):
    """Contract §5.2.3 -> ``(mesh, triangles, fallback, smooth_groups, warnings)``.

    ``data`` is the validated ``objects[i].data`` (Z-up, file units); the result is in the object's
    local frame (``scale`` applied, ``transform`` not).  ``mesh`` is the §2.4 dict plus
    ``edge_smooth``; ``triangles`` the fan triangles of the kept (oriented) faces on the welded
    vertices -- the original surface; ``smooth_groups`` one per final face; ``warnings`` the
    ``MESH_*`` warnings with ids ``[object_id]``."""
    V = float(scale) * np.asarray(data["vertices"], dtype=np.float64).reshape(-1, 3)
    groups_in = list(data.get("smooth_groups") or [0] * len(data["faces"]))
    scale_A = mesh_scale(V)
    warnings = []
    W, faces_w, _index = weld_vertices(V, data["faces"], float(weld_tolerance))
    kept, kept_idx = drop_degenerate_faces(W, faces_w, scale_A)
    n_dropped = len(data["faces"]) - len(kept)
    if n_dropped:
        warnings.append(make_warning("MESH_DEGENERATE_FACES", [object_id],
                                     f"{n_dropped} degenerate face(s) dropped"))
    groups = [int(groups_in[k]) for k in kept_idx]
    W, faces, _old = compact_vertices(W, kept)
    names = [f"v{k}" for k in range(W.shape[0])]
    adjacency = build_adjacency(faces, W.shape[0])
    conflict = False
    if adjacency["manifold"]:
        oriented, flipped, components, conflict = fix_orientation(faces, adjacency)
    if not adjacency["manifold"] or conflict:
        counts = adjacency["counts"]
        n1, n3 = int(np.sum(counts == 1)), int(np.sum(counts >= 3))
        msg = (f"mesh is not a closed manifold ({n1} edge(s) with 1 face, {n3} edge(s) with >= 3 faces"
               + ("; inconsistent winding" if conflict else "") + "); per-face shadow fallback")
        warnings.append(make_warning("MESH_NON_MANIFOLD", [object_id], msg))
        mesh = fallback_mesh(W, faces, names)
        return mesh, triangulate(faces), True, groups, warnings
    oriented, flipped_volume = _orient_components(W, oriented, components, scale_A)
    if bool(np.any(flipped)) or flipped_volume:
        warnings.append(make_warning("MESH_WINDING_FIXED", [object_id]))
    triangles = triangulate(oriented)
    normals = face_normals_newell(W, oriented)
    merged, origin = merge_coplanar(W, oriented, normals, adjacency, math.cos(COPLANAR_TOL_RAD))
    merged_groups = [groups[k] for k in origin]
    mesh = mesh_from_faces(W, merged, names)
    mesh["edge_smooth"] = classify_edges(mesh, smooth_angle_deg, merged_groups)
    return mesh, triangles, False, merged_groups, warnings
