"""Internal mesh representation and primitive builders (spec §9 "網格匯入"; contract §2.4).

A mesh is a plain dict::

    vertices     : (n, 3) float64
    edges        : (m, 2) int, each edge once, i < j, lexicographically sorted
    faces        : list of int lists, counter-clockwise seen from outside, planar
    face_normals : (k, 3) outward unit normals
    edge_faces   : (m, 2) int, the two faces adjacent to each edge
    edge_flipped : (m, 2) bool, whether that face traverses the edge as j -> i (derived, optional:
                   lets the silhouette walk orient edges without scanning the face cycles)
    vertex_names : ["v0", "v1", ...]
    edge_smooth  : (m,) bool, added by ``primitives.build_object`` (M5, contract §5.2.3 step 7): the
                   edge is smooth (not drawn unless it is a camera silhouette edge, §5.2.4); all
                   False for the primitives, ``meshprep.classify_edges`` for ``mesh`` objects

Builders produce local coordinates (contract §2.1): box spans
``[-sx/2, sx/2] x [-sy/2, sy/2] x [0, sz]``; cylinder / cone / sphere axis is
+Z with the base (or sphere bottom) at ``z = 0``; prism polygon lies in XY
(counter-clockwise) and is extruded over ``[0, height]``.
"""

from __future__ import annotations

import math

import numpy as np

#: Default angular resolution of the approximate meshes of curved primitives (contract §2.4).
CURVED_SEGMENTS = 32
SPHERE_RINGS = 16


def _group_faces(faces):
    """Group faces by vertex count -> ``{length: (face_indices, (k, length) int array)}``."""
    groups = {}
    for fi, f in enumerate(faces):
        groups.setdefault(len(f), []).append(fi)
    out = {}
    for length, idx in groups.items():
        arr = np.array([faces[i] for i in idx], dtype=np.int64).reshape(len(idx), length)
        out[length] = (np.array(idx, dtype=np.int64), arr)
    return out


def face_normals_newell(vertices, faces):
    """Outward unit normals by Newell's method, vectorised per face length (contract §2.4)."""
    return _face_normals_grouped(vertices, faces, _group_faces(faces))


def _face_normals_grouped(vertices, faces, groups: dict):
    """:func:`face_normals_newell` with the face groups of :func:`_group_faces` already built."""
    verts = np.asarray(vertices, dtype=np.float64)
    normals = np.zeros((len(faces), 3), dtype=np.float64)
    for length, (idx, arr) in groups.items():
        p = verts[arr]                                   # (k, L, 3)
        q = np.roll(p, -1, axis=1)                       # next vertex
        n = np.einsum("klj,klm->kjm", p, q)              # (k, 3, 3) pairwise products
        # Newell: n_x = sum (y_i - y_j)(z_i + z_j) etc. == sum of cross products p_i x p_j
        cross = np.stack([
            n[:, 1, 2] - n[:, 2, 1],
            n[:, 2, 0] - n[:, 0, 2],
            n[:, 0, 1] - n[:, 1, 0],
        ], axis=1)
        norm = np.linalg.norm(cross, axis=1, keepdims=True)
        norm = np.where(norm == 0.0, 1.0, norm)
        normals[idx] = cross / norm
    return normals


def mesh_from_faces(vertices, faces, vertex_names=None) -> dict:
    """Build the full mesh dict from vertices and CCW faces (contract §2.4).

    Edges are extracted with ``numpy.unique`` (sorted ``i < j`` pairs); every
    edge must be shared by exactly two faces (closed manifold) or ``ValueError``
    is raised.
    """
    verts = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
    faces = [list(map(int, f)) for f in faces]
    n_v = int(verts.shape[0])
    groups = _group_faces(faces)
    pair_list, owner_list, flip_list = [], [], []
    for length, (idx, arr) in groups.items():
        nxt = np.roll(arr, -1, axis=1)
        flipped = arr > nxt                              # the face traverses this edge as j -> i
        pairs = np.stack([arr, nxt], axis=2).reshape(-1, 2)
        pairs.sort(axis=1)
        pair_list.append(pairs)
        owner_list.append(np.repeat(idx, length))
        flip_list.append(flipped.reshape(-1))
    pairs = np.concatenate(pair_list, axis=0)
    owners = np.concatenate(owner_list, axis=0)
    flips = np.concatenate(flip_list, axis=0)
    # one integer key per sorted pair (i < j < n_v): a 1-D unique is much faster than the row-wise one
    # and yields the same lexicographic edge order
    keys = pairs[:, 0].astype(np.int64) * max(n_v, 1) + pairs[:, 1].astype(np.int64)
    uniq, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
    inverse = inverse.reshape(-1)
    if np.any(counts != 2):
        raise ValueError("mesh is not a closed manifold: every edge must have exactly two faces")
    edges = np.stack([uniq // max(n_v, 1), uniq % max(n_v, 1)], axis=1)
    order = np.lexsort((owners, inverse))
    edge_faces = owners[order].reshape(-1, 2)
    edge_flipped = flips[order].reshape(-1, 2)
    if vertex_names is None:
        vertex_names = [f"v{i}" for i in range(verts.shape[0])]
    return {
        "vertices": verts,
        "edges": edges.astype(np.int64),
        "faces": faces,
        "face_normals": _face_normals_grouped(verts, faces, groups),
        "edge_faces": edge_faces.astype(np.int64),
        "edge_flipped": edge_flipped,
        "vertex_names": list(vertex_names),
    }


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------

def box_mesh(size) -> dict:
    """Axis-aligned box ``[-sx/2, sx/2] x [-sy/2, sy/2] x [0, sz]`` (contract §2.1/§2.4).

    Vertex order: v0..v3 bottom ring counter-clockwise from ``(-,-)``, v4..v7 top.
    """
    sx, sy, sz = (float(v) for v in size)
    hx, hy = sx / 2.0, sy / 2.0
    ring = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
    verts = [(x, y, 0.0) for x, y in ring] + [(x, y, sz) for x, y in ring]
    faces = [
        [0, 3, 2, 1],  # bottom (-z)
        [4, 5, 6, 7],  # top (+z)
        [0, 1, 5, 4],  # front (-y)
        [1, 2, 6, 5],  # right (+x)
        [2, 3, 7, 6],  # back (+y)
        [3, 0, 4, 7],  # left (-x)
    ]
    return mesh_from_faces(verts, faces)


def _extrude(ring, height):
    """Extrude a CCW planar ring at ``z = 0`` to ``z = height``: bottom, top and side quads."""
    n = len(ring)
    verts = [(x, y, 0.0) for x, y in ring] + [(x, y, float(height)) for x, y in ring]
    faces = [list(range(n - 1, -1, -1)), list(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, n + j, n + i])
    return verts, faces


def prism_mesh(polygon, height) -> dict:
    """Right prism over a simple CCW polygon in local XY, extruded over ``[0, height]`` (contract §2.4)."""
    ring = [(float(x), float(y)) for x, y in polygon]
    verts, faces = _extrude(ring, height)
    return mesh_from_faces(verts, faces)


def _circle_ring(radius, segments):
    return [(radius * math.cos(2.0 * math.pi * i / segments), radius * math.sin(2.0 * math.pi * i / segments))
            for i in range(segments)]


def cylinder_mesh(radius, height, segments: int = CURVED_SEGMENTS) -> dict:
    """Approximate cylinder: n-gon caps and lateral quads (contract §2.4; bounding boxes only)."""
    verts, faces = _extrude(_circle_ring(float(radius), segments), height)
    return mesh_from_faces(verts, faces)


def cone_mesh(radius, height, segments: int = CURVED_SEGMENTS) -> dict:
    """Approximate cone: n-gon base, apex at ``(0, 0, height)``, lateral triangles (contract §2.4)."""
    ring = _circle_ring(float(radius), segments)
    n = segments
    verts = [(x, y, 0.0) for x, y in ring] + [(0.0, 0.0, float(height))]
    faces = [list(range(n - 1, -1, -1))]
    for i in range(n):
        faces.append([i, (i + 1) % n, n])
    return mesh_from_faces(verts, faces)


def sphere_mesh(radius, segments: int = CURVED_SEGMENTS, rings: int = SPHERE_RINGS) -> dict:
    """Approximate UV-sphere with centre ``(0, 0, r)`` (bottom on the ground; contract §2.1/§2.4)."""
    r = float(radius)
    verts = [(0.0, 0.0, 2.0 * r)]  # top pole
    for j in range(1, rings):
        phi = math.pi * j / rings
        z = r + r * math.cos(phi)
        rr = r * math.sin(phi)
        verts.extend((rr * math.cos(2.0 * math.pi * i / segments), rr * math.sin(2.0 * math.pi * i / segments), z)
                     for i in range(segments))
    verts.append((0.0, 0.0, 0.0))  # bottom pole
    bottom = len(verts) - 1

    def ring_index(j, i):
        return 1 + (j - 1) * segments + (i % segments)

    faces = []
    for i in range(segments):  # top fan
        faces.append([ring_index(1, i), ring_index(1, i + 1), 0])
    for j in range(1, rings - 1):  # bands: upper ring j, lower ring j+1
        for i in range(segments):
            faces.append([ring_index(j + 1, i), ring_index(j + 1, i + 1), ring_index(j, i + 1), ring_index(j, i)])
    for i in range(segments):  # bottom fan
        faces.append([ring_index(rings - 1, i + 1), ring_index(rings - 1, i), bottom])
    return mesh_from_faces(verts, faces)


# ---------------------------------------------------------------------------
# utilities
# ---------------------------------------------------------------------------

def transform_mesh(mesh: dict, R, position) -> dict:
    """Return a new mesh with ``vertices = R·v + position`` and rotated normals (contract §2.1)."""
    R = np.asarray(R, dtype=np.float64)
    position = np.asarray(position, dtype=np.float64)
    out = dict(mesh)
    out["vertices"] = mesh["vertices"] @ R.T + position[None, :]
    out["face_normals"] = mesh["face_normals"] @ R.T
    return out


def mesh_bbox(mesh: dict):
    """``(min_xyz, max_xyz)`` of the vertices."""
    v = mesh["vertices"]
    return v.min(axis=0), v.max(axis=0)


def euler_characteristic(mesh: dict) -> int:
    """``V - E + F`` (2 for a closed genus-0 surface)."""
    return int(mesh["vertices"].shape[0] - mesh["edges"].shape[0] + len(mesh["faces"]))


def triangulate_faces(faces_padded, face_lens) -> np.ndarray:
    """Fan triangulation ``(f0, f_k, f_{k+1})`` of every face of a ``-1``-padded face table
    (contract §5.2.3 step 4): vectorised, columns ``(0, k, k+1)`` masked by ``face_lens``; returns a
    ``(t, 3)`` int array in face-major order (the triangles of face 0 first, ``k`` ascending)."""
    P = np.asarray(faces_padded, dtype=np.int64)
    lens = np.asarray(face_lens, dtype=np.int64).reshape(-1)
    if P.ndim != 2 or P.shape[0] == 0 or P.shape[1] < 3:
        return np.zeros((0, 3), dtype=np.int64)
    width = P.shape[1]
    first = np.broadcast_to(P[:, :1], (P.shape[0], width - 2))
    tri = np.stack([first, P[:, 1:width - 1], P[:, 2:width]], axis=2)       # (F, W-2, 3)
    mask = np.arange(2, width, dtype=np.int64)[None, :] < lens[:, None]     # triangle (0, k, k+1): k+1 < len
    return np.ascontiguousarray(tri[mask]).reshape(-1, 3)
