"""Mesh toolkit of the Miki model generator (numpy + stdlib only).

Conventions (castplane mesh rules, ``docs/USAGE.md`` and contract §5.2):

* world frame: right-handed, Z up, metres, ground ``z = 0``; the figure faces ``-Y``, her left is ``+X``;
* a :class:`Mesh` holds ``vertices`` (float64 ``(N, 3)``), ``faces`` (a list of int lists, triangles or
  quads or flat polygons, counter-clockwise seen from outside) and ``groups`` (one smooth-group id per
  face).  castplane draws the edge between two faces of the **same non-zero group** only where it is a
  camera silhouette, and every edge between **different groups** always (a "feature line"); group 0
  falls back to castplane's 30 degree dihedral rule.  So: one group per smooth patch, a group boundary
  wherever a designed line should be drawn;
* every builder returns a **closed, 2-manifold, outward-oriented shell** (each undirected edge in
  exactly two faces, used once in each direction, positive signed volume).  Builders orient their
  result by its signed volume, so the ring / grid order given by the caller does not matter;
* all transforms return new meshes (meshes are treated as values); :meth:`Mesh.mirror_x` and every
  transform with a negative determinant reverse the face winding so the shell stays outward.

Builders: :func:`loft` (rings -> solid; pole / flat / dome caps or periodic), :func:`sweep` (a profile
along a 3D polyline with rotation-minimising frames, twist, taper, pointed tips), :func:`thicken`
(a parametric surface grid -> closed slab with front / back / rim groups), :func:`revolve`,
:func:`ellipsoid`, :func:`superellipsoid`, :func:`torus`; ring and profile helpers
(:func:`ellipse_ring`, :func:`superellipse_ring`, :func:`rounded_rect_ring`, :func:`place_ring`,
:func:`profile_ellipse`, :func:`profile_lens`, :func:`profile_rect`).  :func:`validate` checks a mesh
against the castplane rules; :func:`fix_nesting` reorders vertices so castplane's nesting-parity
orientation test (contract §5.2.3 step 5) never flips a shell; :func:`split_smooth` gives smooth
per-group vertex normals (GLB export, preview shading).
"""

from __future__ import annotations

import math
from dataclasses import KW_ONLY, dataclass, field

import numpy as np

__all__ = [
    "Mesh", "Part", "MeshError", "ValidationReport",
    "merge", "rotation_matrix", "frame_from_z",
    "loft", "sweep", "thicken", "revolve", "ellipsoid", "superellipsoid", "torus", "tube",
    "ellipse_ring", "superellipse_ring", "rounded_rect_ring", "place_ring", "resample_closed", "resample_polyline",
    "profile_ellipse", "profile_lens", "profile_rect",
    "validate", "fix_nesting", "winding_numbers", "split_smooth", "triangulate", "face_normals",
    "feature_silhouette_vertices",
]

#: Default tolerances of :func:`validate` (metres / square metres).
DUPLICATE_TOL = 1e-5
AREA_TOL = 1e-10
Z_TOL = 1e-9


class MeshError(ValueError):
    """A mesh breaks a castplane rule (raised by :func:`validate` in strict mode and by builders)."""


# ---------------------------------------------------------------------------
# Mesh value type
# ---------------------------------------------------------------------------

class Mesh:
    """Polygon mesh: ``vertices`` float64 ``(N, 3)``, ``faces`` list of int lists (CCW from outside),
    ``groups`` list of int (smooth group per face; 0 = castplane's dihedral-angle rule).

    Every method returns a new mesh; the arrays of ``self`` are never modified."""

    __slots__ = ("vertices", "faces", "groups")

    def __init__(self, vertices=None, faces=None, groups=None):
        v = np.zeros((0, 3)) if vertices is None else np.asarray(vertices, dtype=np.float64)
        self.vertices = np.array(v, dtype=np.float64).reshape(-1, 3)
        self.faces = [] if faces is None else [[int(i) for i in f] for f in faces]
        if groups is None:
            groups = 0
        if isinstance(groups, (int, np.integer)):
            groups = [int(groups)] * len(self.faces)
        self.groups = [int(g) for g in groups]
        if len(self.groups) != len(self.faces):
            raise MeshError(f"{len(self.groups)} groups for {len(self.faces)} faces")

    # -- counts --------------------------------------------------------------
    @property
    def n_vertices(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def n_faces(self) -> int:
        return len(self.faces)

    @property
    def n_triangles(self) -> int:
        """Triangles after castplane's fan triangulation (``len(face) - 2`` per face)."""
        return sum(len(f) - 2 for f in self.faces)

    def bbox(self):
        """``(min (3,), max (3,))`` of the vertices."""
        return self.vertices.min(axis=0), self.vertices.max(axis=0)

    def __repr__(self) -> str:
        return f"Mesh({self.n_vertices} vertices, {self.n_faces} faces, groups {sorted(set(self.groups))})"

    # -- copies and transforms -------------------------------------------------
    def copy(self) -> "Mesh":
        return Mesh(self.vertices.copy(), self.faces, self.groups)

    def transform(self, matrix, offset=(0.0, 0.0, 0.0)) -> "Mesh":
        """``v -> matrix @ v + offset``; the winding is reversed when ``det(matrix) < 0``."""
        M = np.asarray(matrix, dtype=np.float64).reshape(3, 3)
        V = self.vertices @ M.T + np.asarray(offset, dtype=np.float64)
        faces = self.faces
        if np.linalg.det(M) < 0:
            faces = [[f[0]] + f[1:][::-1] for f in faces]
        return Mesh(V, faces, self.groups)

    def translate(self, offset) -> "Mesh":
        return Mesh(self.vertices + np.asarray(offset, dtype=np.float64), self.faces, self.groups)

    def rotate(self, axis, angle_deg: float, origin=(0.0, 0.0, 0.0)) -> "Mesh":
        """Rotate by ``angle_deg`` (right hand) about ``axis`` (``'x'``/``'y'``/``'z'`` or a vector)
        through ``origin``."""
        R = rotation_matrix(axis, angle_deg)
        o = np.asarray(origin, dtype=np.float64)
        return Mesh((self.vertices - o) @ R.T + o, self.faces, self.groups)

    def scale(self, s, origin=(0.0, 0.0, 0.0)) -> "Mesh":
        """Scale by a scalar or a per-axis ``(sx, sy, sz)`` about ``origin`` (a negative product mirrors
        and reverses the winding)."""
        s = np.broadcast_to(np.asarray(s, dtype=np.float64), (3,))
        o = np.asarray(origin, dtype=np.float64)
        return self.transform(np.diag(s), o - s * o)

    def mirror_x(self) -> "Mesh":
        """Mirror ``x -> -x`` (her right <-> left); the winding is reversed so the shell stays outward."""
        V = self.vertices * np.array([-1.0, 1.0, 1.0])
        return Mesh(V, [[f[0]] + f[1:][::-1] for f in self.faces], self.groups)

    def flipped(self) -> "Mesh":
        """Reverse every face (inside out)."""
        return Mesh(self.vertices, [[f[0]] + f[1:][::-1] for f in self.faces], self.groups)

    def with_groups(self, groups) -> "Mesh":
        """Replace the groups: an int (all faces), a list (per face) or a dict ``old -> new``."""
        if isinstance(groups, dict):
            groups = [groups.get(g, g) for g in self.groups]
        return Mesh(self.vertices, self.faces, groups)

    def rounded(self, decimals: int = 5) -> "Mesh":
        """Coordinates rounded to ``decimals`` (``-0.0`` normalised to ``0.0``)."""
        return Mesh(np.round(self.vertices, decimals) + 0.0, self.faces, self.groups)

    def merge(self, *others: "Mesh") -> "Mesh":
        """This mesh followed by ``others`` (vertex indices offset; groups kept as they are)."""
        return merge(self, *others)

    def triangles(self):
        """Fan triangulation at each face's first vertex (castplane's rule): ``(tris (T, 3) int,
        tri_face (T,) int)``."""
        return triangulate(self.faces)


@dataclass
class Part:
    """One named piece of the model.

    * ``name``: unique in the whole model (prefix it with the module, e.g. ``hair.sidelock_l``);
    * ``material``: its colour, a key of ``assemble.MATERIALS`` (``hair``, ``skin``, ``iris``, ...);
    * ``mesh``: closed shells;
    * ``region``: the region it belongs to (``--only`` filters by it; empty = every region of the module
      that built it);
    * ``obj`` (keyword only): the castplane object it goes into, one of ``assemble.OBJECT_IDS``; empty =
      ``assemble.REGION_OBJECTS[region]`` (so most parts need not set it; the ring, the neck, the
      sidelocks, the back hair and the cuff stripes do)."""

    name: str
    material: str
    mesh: Mesh
    region: str = ""
    _: KW_ONLY
    obj: str = ""


def merge(*meshes: Mesh) -> Mesh:
    """Concatenate meshes (vertex indices offset, groups unchanged)."""
    if len(meshes) == 1 and isinstance(meshes[0], (list, tuple)):
        meshes = tuple(meshes[0])
    verts, faces, groups, base = [], [], [], 0
    for m in meshes:
        verts.append(m.vertices)
        faces.extend([[i + base for i in f] for f in m.faces])
        groups.extend(m.groups)
        base += m.n_vertices
    V = np.concatenate(verts, axis=0) if verts else np.zeros((0, 3))
    return Mesh(V, faces, groups)


def rotation_matrix(axis, angle_deg: float) -> np.ndarray:
    """Right-handed rotation matrix about ``axis`` (``'x'``, ``'y'``, ``'z'`` or a 3-vector)."""
    if isinstance(axis, str):
        axis = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}[axis]
    a = np.asarray(axis, dtype=np.float64)
    a = a / np.linalg.norm(a)
    t = math.radians(angle_deg)
    c, s = math.cos(t), math.sin(t)
    x, y, z = a
    return np.array([[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                     [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                     [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]])


def frame_from_z(z_axis, x_hint=(1.0, 0.0, 0.0)):
    """Orthonormal ``(x, y, z)`` with ``z`` along ``z_axis`` and ``x`` as close to ``x_hint`` as possible."""
    z = np.asarray(z_axis, dtype=np.float64)
    z = z / np.linalg.norm(z)
    x = np.asarray(x_hint, dtype=np.float64)
    x = x - z * np.dot(x, z)
    if np.linalg.norm(x) < 1e-9:
        x = np.array([0.0, 1.0, 0.0]) - z * z[1]
        if np.linalg.norm(x) < 1e-9:
            x = np.array([0.0, 0.0, 1.0]) - z * z[2]
    x = x / np.linalg.norm(x)
    return x, np.cross(z, x), z


# ---------------------------------------------------------------------------
# Rings and profiles
# ---------------------------------------------------------------------------

def _spow(x, p):
    return np.sign(x) * np.abs(x) ** p


def resample_closed(points, n: int, start=None) -> np.ndarray:
    """``n`` points at equal arc length along the closed polyline ``points`` (2D or 3D), starting at the
    polyline point nearest ``start`` (default: the first point), keeping the direction."""
    P = np.asarray(points, dtype=np.float64)
    if start is not None:
        k = int(np.argmin(np.linalg.norm(P - np.asarray(start, dtype=np.float64), axis=1)))
        P = np.roll(P, -k, axis=0)
    Q = np.concatenate([P, P[:1]], axis=0)
    seg = np.linalg.norm(np.diff(Q, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.arange(n) * (s[-1] / n)
    return np.stack([np.interp(t, s, Q[:, k]) for k in range(Q.shape[1])], axis=1)


def resample_polyline(points, n: int) -> np.ndarray:
    """``n`` points at equal arc length along the open polyline ``points`` (both ends kept)."""
    P = np.asarray(points, dtype=np.float64)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0.0, s[-1], n)
    return np.stack([np.interp(t, s, P[:, k]) for k in range(P.shape[1])], axis=1)


def place_ring(points2d, origin=(0.0, 0.0, 0.0), x_axis=(1.0, 0.0, 0.0), y_axis=(0.0, 1.0, 0.0)) -> np.ndarray:
    """Map 2D ring points ``(M, 2)`` into the 3D plane ``origin + u·x_axis + v·y_axis``."""
    P = np.asarray(points2d, dtype=np.float64)
    return (np.asarray(origin, dtype=np.float64) + P[:, :1] * np.asarray(x_axis, dtype=np.float64)
            + P[:, 1:2] * np.asarray(y_axis, dtype=np.float64))


def ellipse_ring(a: float, b: float, n: int, center=(0.0, 0.0, 0.0), phase_deg: float = 0.0) -> np.ndarray:
    """Horizontal ellipse ring ``(n, 3)`` (semi-axes ``a`` along X, ``b`` along Y) at ``center``,
    counter-clockwise seen from +Z, first point at angle ``phase_deg`` from +X."""
    t = np.radians(phase_deg) + 2.0 * np.pi * np.arange(n) / n
    c = np.asarray(center, dtype=np.float64)
    return np.stack([c[0] + a * np.cos(t), c[1] + b * np.sin(t), np.full(n, c[2])], axis=1)


def superellipse_ring(a: float, b: float, n: int, exponent: float = 2.5, center=(0.0, 0.0, 0.0),
                      uniform: bool = True) -> np.ndarray:
    """Horizontal superellipse ``|x/a|^p + |y/b|^p = 1`` ring ``(n, 3)`` at ``center`` (CCW from +Z,
    first point on +X).  ``exponent`` 2 = ellipse, 3–4 = rounded box.  ``uniform`` resamples at equal arc
    length (better quads); otherwise points are equal in parameter angle."""
    m = 8 * n if uniform else n
    t = 2.0 * np.pi * np.arange(m) / m
    P = np.stack([a * _spow(np.cos(t), 2.0 / exponent), b * _spow(np.sin(t), 2.0 / exponent)], axis=1)
    if uniform:
        P = resample_closed(P, n)
    c = np.asarray(center, dtype=np.float64)
    return np.stack([c[0] + P[:, 0], c[1] + P[:, 1], np.full(n, c[2])], axis=1)


def rounded_rect_ring(width: float, depth: float, radius: float, n: int, center=(0.0, 0.0, 0.0)) -> np.ndarray:
    """Horizontal rounded rectangle (``width`` along X, ``depth`` along Y, corner ``radius``) resampled to
    ``n`` points at equal arc length, CCW from +Z, first point on +X."""
    r = min(radius, 0.5 * width - 1e-9, 0.5 * depth - 1e-9)
    hx, hy = 0.5 * width - r, 0.5 * depth - r
    pts = []
    for q, (sx, sy) in enumerate(((1, 1), (-1, 1), (-1, -1), (1, -1))):
        a = np.radians(90.0 * q) + np.linspace(0.0, np.pi / 2, 16)
        pts.append(np.stack([sx * hx + r * np.cos(a), sy * hy + r * np.sin(a)], axis=1))
    P = np.concatenate(pts, axis=0)
    P = resample_closed(np.concatenate([[[0.5 * width, 0.0]], P[P[:, 1] >= 0], P[P[:, 1] < 0]]), n)
    c = np.asarray(center, dtype=np.float64)
    return np.stack([c[0] + P[:, 0], c[1] + P[:, 1], np.full(n, c[2])], axis=1)


def profile_ellipse(m: int = 8, phase_deg: float = 0.0) -> np.ndarray:
    """Unit ellipse profile ``(m, 2)`` (half extents 1), CCW, first point on +x."""
    t = np.radians(phase_deg) + 2.0 * np.pi * np.arange(m) / m
    return np.stack([np.cos(t), np.sin(t)], axis=1)


def profile_lens(m: int = 8, fullness: float = 0.6) -> np.ndarray:
    """Unit lens / almond profile ``(m, 2)`` (sharp-ish at ``x = ±1``, half thickness 1 at ``x = 0``): a
    flat hair strand or ribbon section.  ``fullness`` in (0, 1]: 1 = ellipse, small = sharper edges."""
    t = 2.0 * np.pi * np.arange(m) / m
    return np.stack([np.cos(t), _spow(np.sin(t), fullness)], axis=1)


def profile_rect(m: int = 8, exponent: float = 4.0) -> np.ndarray:
    """Unit rounded-rectangle profile ``(m, 2)`` (a superellipse; ``m`` multiple of 4 recommended)."""
    t = 2.0 * np.pi * (np.arange(m) + 0.5) / m
    return np.stack([_spow(np.cos(t), 2.0 / exponent), _spow(np.sin(t), 2.0 / exponent)], axis=1)


# ---------------------------------------------------------------------------
# Orientation helpers
# ---------------------------------------------------------------------------

def triangulate(faces):
    """Fan triangulation ``(f0, fk, fk+1)`` of each face: ``(tris (T, 3) int, tri_face (T,) int)``."""
    tris, owner = [], []
    for k, f in enumerate(faces):
        for j in range(1, len(f) - 1):
            tris.append((f[0], f[j], f[j + 1]))
            owner.append(k)
    return (np.array(tris, dtype=np.int64).reshape(-1, 3), np.array(owner, dtype=np.int64))


def _best_fan_start(P) -> int:
    """Start vertex of the fan triangulation of polygon ``P`` (k, 3) that maximises the smallest triangle
    area (avoids zero-area slivers from collinear ring points, which a float32 writer would turn into
    degenerate triangles)."""
    k = P.shape[0]
    best, best_area = 0, -1.0
    for s in range(k):
        Q = np.roll(P, -s, axis=0)
        a = np.linalg.norm(np.cross(Q[1:-1] - Q[0], Q[2:] - Q[0]), axis=1).min()
        if a > best_area * (1.0 + 1e-9):
            best, best_area = s, a
    return best


def face_normals(mesh: Mesh):
    """Newell normals of the faces: ``(unit normals (F, 3), areas (F,))``."""
    V = mesh.vertices
    n = np.zeros((mesh.n_faces, 3))
    for k, f in enumerate(mesh.faces):
        P = V[f]
        Q = np.roll(P, -1, axis=0)
        n[k] = 0.5 * np.cross(P, Q).sum(axis=0)
    area = np.linalg.norm(n, axis=1)
    return n / np.where(area > 0, area, 1.0)[:, None], area


def _signed_volume(V, faces) -> float:
    tris, _ = triangulate(faces)
    if not len(tris):
        return 0.0
    a, b, c = V[tris[:, 0]], V[tris[:, 1]], V[tris[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def _outward(mesh: Mesh) -> Mesh:
    """Flip the whole mesh when its signed volume is negative."""
    return mesh.flipped() if _signed_volume(mesh.vertices, mesh.faces) < 0 else mesh


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _group_table(groups, n_sections: int, m: int) -> np.ndarray:
    """Normalise a ``groups`` argument (int / per-section sequence / ``(sections, M)`` array)."""
    g = np.asarray(groups, dtype=np.int64)
    if g.ndim == 0:
        return np.full((n_sections, m), int(g))
    if g.ndim == 1:
        if g.shape[0] != n_sections:
            raise MeshError(f"groups has {g.shape[0]} entries for {n_sections} sections")
        return np.repeat(g[:, None], m, axis=1)
    if g.shape != (n_sections, m):
        raise MeshError(f"groups has shape {g.shape}, expected {(n_sections, m)}")
    return g.copy()


def _parse_cap(cap):
    if isinstance(cap, str):
        return cap, None, None
    kind = cap[0]
    return kind, (cap[1] if len(cap) > 1 else None), (cap[2] if len(cap) > 2 else None)


def _dome_rings(ring, inner, depth, n_rings):
    """Rings closing ``ring`` into a rounded end that bulges away from ``inner`` (the neighbouring ring)
    by ``depth``; returns ``(rings, apex)``."""
    c = ring.mean(axis=0)
    axis = c - inner.mean(axis=0)
    axis = axis / np.linalg.norm(axis)
    rings = []
    for k in range(1, n_rings + 1):
        th = 0.5 * np.pi * k / (n_rings + 1)
        rings.append(c + (ring - c) * math.cos(th) + axis * depth * math.sin(th))
    return rings, c + axis * depth


def loft(rings, cap_start="pole", cap_end="pole", periodic_v: bool = False, groups=1, cap_groups=None) -> Mesh:
    """Solid through ``rings`` (a list of ``(M, 3)`` arrays with equal ``M``, consecutive rings
    corresponding point by point; each ring a simple closed loop).

    ``cap_start`` / ``cap_end``:

    * ``'pole'`` — triangle fan to the ring centroid, or ``('pole', apex_xyz)`` to a given apex;
    * ``'flat'`` — one polygon face (the ring should be planar);
    * ``('dome', depth)`` or ``('dome', depth, n_rings)`` — a rounded end bulging ``depth`` beyond the ring
      (default 2 extra rings) closed by a pole.

    ``periodic_v=True`` joins the last ring back to the first (a ring-shaped solid, e.g. a torus); the
    caps are then ignored.  ``groups``: an int, one int per section (``len(rings) - 1`` sections, or
    ``len(rings)`` when periodic) or a ``(sections, M)`` array (one group per quad: column-wise groups
    make lengthwise feature lines, e.g. skirt pleats).  A group change between sections is a feature line
    around the solid.  ``cap_groups = (start, end)``: default for pole / dome caps is the neighbouring
    quad's group (smooth into the tip), for flat caps a new group (``max + 1``, ``max + 2``) so the cap rim
    draws."""
    R = [np.asarray(r, dtype=np.float64).reshape(-1, 3) for r in rings]
    m = R[0].shape[0]
    if m < 3 or any(r.shape[0] != m for r in R):
        raise MeshError("loft: rings need equal point counts >= 3")
    if len(R) < (1 if periodic_v else 2):
        raise MeshError("loft: need at least two rings")
    n_sec = len(R) if periodic_v else len(R) - 1
    G = _group_table(groups, n_sec, m)
    kind_s, arg_s, arg2_s = _parse_cap(cap_start)
    kind_e, arg_e, arg2_e = _parse_cap(cap_end)
    gmax = int(G.max())
    cg = list(cap_groups) if cap_groups is not None else [None, None]
    start_rows, end_rows = [], []
    if not periodic_v:
        if kind_s == "dome":
            start_rows, apex_s = _dome_rings(R[0], R[1], float(arg_s), int(arg2_s or 2))
            start_rows = start_rows[::-1]
            kind_s, arg_s = "pole", apex_s
        if kind_e == "dome":
            end_rows, apex_e = _dome_rings(R[-1], R[-2], float(arg_e), int(arg2_e or 2))
            kind_e, arg_e = "pole", apex_e
    all_rings = list(start_rows) + R + list(end_rows)
    V = np.concatenate(all_rings, axis=0)
    ns, nr = len(start_rows), len(all_rings)
    faces, fgroups = [], []

    def idx(r, j):
        return (r % nr) * m + (j % m)

    for r in range(nr if periodic_v else nr - 1):
        body = ns <= r < ns + n_sec
        for j in range(m):
            faces.append([idx(r, j), idx(r, j + 1), idx(r + 1, j + 1), idx(r + 1, j)])
            if body:
                fgroups.append(int(G[r - ns, j]))
            elif r < ns:
                fgroups.append(int(cg[0]) if cg[0] is not None else int(G[0, j]))
            else:
                fgroups.append(int(cg[1]) if cg[1] is not None else int(G[-1, j]))
    verts = [V]
    if not periodic_v:
        nv = V.shape[0]
        for end, kind, arg in (("start", kind_s, arg_s), ("end", kind_e, arg_e)):
            r = 0 if end == "start" else nr - 1
            row = G[0] if end == "start" else G[-1]
            gi = 0 if end == "start" else 1
            if kind == "pole":
                apex = all_rings[r].mean(axis=0) if arg is None else np.asarray(arg, dtype=np.float64)
                verts.append(apex[None, :])
                for j in range(m):
                    if end == "start":
                        faces.append([nv, idx(r, j + 1), idx(r, j)])
                    else:
                        faces.append([nv, idx(r, j), idx(r, j + 1)])
                    fgroups.append(int(cg[gi]) if cg[gi] is not None else int(row[j]))
                nv += 1
            elif kind == "flat":
                ring = [idx(r, j) for j in range(m)]
                faces.append(ring[::-1] if end == "start" else ring)
                fgroups.append(int(cg[gi]) if cg[gi] is not None else gmax + 1 + gi)
            else:
                raise MeshError(f"loft: unknown cap {kind!r}")
    return _outward(Mesh(np.concatenate(verts, axis=0), faces, fgroups))


def _param(value, s):
    """Evaluate a float / array / callable(s) parameter at the arc-length parameters ``s``."""
    if callable(value):
        return np.array([float(value(x)) for x in s])
    a = np.asarray(value, dtype=np.float64)
    return np.full(len(s), float(a)) if a.ndim == 0 else a


def _rmf(points, tangents, n0):
    """Rotation-minimising normals along a polyline (double reflection, Wang et al. 2008)."""
    N = [n0]
    for i in range(len(points) - 1):
        v1 = points[i + 1] - points[i]
        c1 = float(np.dot(v1, v1))
        if c1 < 1e-30:
            N.append(N[-1])
            continue
        rL = N[-1] - (2.0 / c1) * np.dot(v1, N[-1]) * v1
        tL = tangents[i] - (2.0 / c1) * np.dot(v1, tangents[i]) * v1
        v2 = tangents[i + 1] - tL
        c2 = float(np.dot(v2, v2))
        n = rL - (2.0 / c2) * np.dot(v2, rL) * v2 if c2 > 1e-30 else rL
        n = n - tangents[i + 1] * np.dot(n, tangents[i + 1])
        N.append(n / np.linalg.norm(n))
    return np.array(N)


def sweep(path, width=0.01, thickness=None, profile=None, n_profile: int = 8, normals=None, up=None,
          twist_deg=0.0, start="flat", end="flat", groups=1, cap_groups=None, return_frames: bool = False):
    """Sweep a 2D profile along the 3D polyline ``path`` ``(P, 3)``.

    Local frame per path point: tangent ``t``, *thickness* direction ``n`` and *width* direction
    ``b = t × n``; profile point ``(px, py)`` goes to ``c + px·width/2·b + py·thickness/2·n``.  ``n``
    follows rotation-minimising frames from ``up`` (projected onto the plane normal to the first
    tangent; default world Z, or Y when the path starts vertical), or is given per point by ``normals``
    ``(P, 3)`` (each projected onto the plane normal to the tangent) — e.g. "away from the head centre"
    for a flat strand that lies on the hair.  ``twist_deg``: total twist (linear) or callable(s) -> degrees.

    ``width`` / ``thickness`` (default ``thickness = width``): float, ``(P,)`` array or callable(s) with
    ``s`` the normalised arc length in [0, 1].  ``profile``: ``(M, 2)`` unit profile (see
    :func:`profile_ellipse`, :func:`profile_lens`, :func:`profile_rect`), a callable(s) -> ``(M, 2)``,
    or None for an ellipse with ``n_profile`` points.

    ``start`` / ``end``: ``'flat'`` (flat cap), ``'round'`` (dome of depth ``min(w, th)/2``),
    ``'pointed'`` (the last path point becomes the apex of a triangle fan: hair-strand and scarf tips; the
    ring at that point is not built, so give the path a short last segment for a sharp tip).
    ``groups`` / ``cap_groups`` as in :func:`loft` (sections between consecutive built rings)."""
    P = np.asarray(path, dtype=np.float64).reshape(-1, 3)
    if P.shape[0] < 2:
        raise MeshError("sweep: path needs >= 2 points")
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    if np.any(seg < 1e-9):
        raise MeshError("sweep: path has repeated points")
    s = np.concatenate([[0.0], np.cumsum(seg)])
    s = s / s[-1]
    T = np.zeros_like(P)
    T[1:-1] = P[2:] - P[:-2]
    T[0], T[-1] = P[1] - P[0], P[-1] - P[-2]
    T = T / np.linalg.norm(T, axis=1)[:, None]
    if normals is not None:
        Nn = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
        Nn = Nn - T * np.einsum("ij,ij->i", Nn, T)[:, None]
        N = Nn / np.linalg.norm(Nn, axis=1)[:, None]
    else:
        u = np.array([0.0, 0.0, 1.0]) if up is None else np.asarray(up, dtype=np.float64)
        if abs(np.dot(u / np.linalg.norm(u), T[0])) > 0.99:
            u = np.array([0.0, 1.0, 0.0])
        n0 = u - T[0] * np.dot(u, T[0])
        N = _rmf(P, T, n0 / np.linalg.norm(n0))
    B = np.cross(T, N)
    if callable(twist_deg) or np.ndim(twist_deg) == 1:
        tw = np.radians(_param(twist_deg, s))
    else:
        tw = np.radians(float(twist_deg) * s)
    if np.any(tw != 0):
        c, si = np.cos(tw)[:, None], np.sin(tw)[:, None]
        N, B = c * N - si * B, si * N + c * B
    W = _param(width, s)
    TH = W if thickness is None else _param(thickness, s)
    rings = []
    for i in range(P.shape[0]):
        prof = profile(s[i]) if callable(profile) else (profile_ellipse(n_profile) if profile is None else profile)
        prof = np.asarray(prof, dtype=np.float64)
        rings.append(P[i] + prof[:, :1] * (0.5 * W[i]) * B[i] + prof[:, 1:2] * (0.5 * TH[i]) * N[i])
    caps = []
    for which, kind in (("start", start), ("end", end)):
        i = 0 if which == "start" else -1
        if kind == "pointed":
            caps.append(("pole", P[i]))
        elif kind == "round":
            caps.append(("dome", 0.5 * min(W[i], TH[i])))
        elif kind == "flat":
            caps.append("flat")
        else:
            raise MeshError(f"sweep: unknown tip {kind!r}")
    if start == "pointed":
        rings = rings[1:]
    if end == "pointed":
        rings = rings[:-1]
    mesh = loft(rings, caps[0], caps[1], groups=groups, cap_groups=cap_groups)
    if return_frames:
        return mesh, (P, T, N, B)
    return mesh


def tube(path, radius, n: int = 8, start="round", end="round", group: int = 1, **kw) -> Mesh:
    """Round tube of ``radius`` (float / array / callable(s)) along ``path`` (a :func:`sweep` shortcut)."""
    r = radius
    diam = (lambda x: 2.0 * float(r(x))) if callable(r) else 2.0 * np.asarray(r, dtype=np.float64)
    return sweep(path, width=diam, profile=profile_ellipse(n), start=start, end=end, groups=group, **kw)


def _grid_normals(G, periodic_u: bool):
    if periodic_u:
        du = np.roll(G, -1, axis=0) - np.roll(G, 1, axis=0)
    else:
        du = np.gradient(G, axis=0)
    dv = np.gradient(G, axis=1)
    n = np.cross(du, dv)
    ln = np.linalg.norm(n, axis=2)
    if np.any(ln < 1e-15):
        raise MeshError("thicken: degenerate grid (zero-area normal)")
    return n / ln[..., None]


def thicken(grid, thickness, periodic_u: bool = False, offset: str = "centre", flip: bool = False,
            groups=None, away_from=None, return_sides: bool = False) -> Mesh:
    """Closed slab from a parametric surface ``grid`` ``(U, V, 3)`` (``U, V >= 2``).

    The *front* side is the ``du × dv`` side of the grid (``u`` = first axis); ``flip=True`` swaps it, and
    ``away_from=(x, y, z)`` chooses it automatically so that the front faces away from that point (e.g.
    the head centre for hair: ``offset='outward'`` then grows the slab away from the head).
    ``thickness``: float, ``(U, V)`` array or callable(u, v) on the unit square (``u = i/(U-1)``, or
    ``i/U`` when periodic), > 0 everywhere.  ``offset``: ``'centre'`` (grid in the middle), ``'outward'``
    (grid is the back face; slab grows to the front) or ``'inward'`` (grid is the front face).
    ``periodic_u=True`` joins row ``U-1`` back to row 0 (a ring-shaped slab: headband, collar band).

    ``groups``: dict with ``front`` (int or ``(U', V-1)`` array, ``U' = U-1`` or ``U``), ``back`` (int)
    and ``rim`` (int, or a dict with keys ``v0``, ``v1``, ``u0``, ``u1`` per border); default
    ``{front: 1, back: 2, rim: 3}``: the slab borders are feature lines on both sides.  ``groups="single"``
    puts the whole slab in one group: its borders then draw only as camera silhouettes — which the border
    of a thin closed slab nearly always is — and they cost no construction rays.  Every feature border
    that lies on the light terminator (e.g. a rim facing away from the sun next to a lit front) counts
    towards castplane's 64 ray vertices per object (:func:`feature_silhouette_vertices`), so give a rim
    its own group only where the line matters (e.g. ``rim={"v0": 1, "v1": 2, "u0": 1, "u1": 1}`` with
    ``front = back = 1`` for a bang cut edge).
    ``return_sides`` also returns ``{"front": F, "back": B}`` (the two ``(U, V, 3)`` vertex grids)."""
    G = np.asarray(grid, dtype=np.float64)
    U, V = G.shape[0], G.shape[1]
    if U < 2 or V < 2:
        raise MeshError("thicken: grid needs U, V >= 2")
    nrm = _grid_normals(G, periodic_u)
    if away_from is not None:
        d = G - np.asarray(away_from, dtype=np.float64)
        flip = bool(np.einsum("uvi,uvi->", nrm, d) < 0) != bool(flip)
    if flip:
        nrm = -nrm
    uu = np.arange(U) / (U if periodic_u else U - 1)
    vv = np.arange(V) / (V - 1)
    if callable(thickness):
        Ug, Vg = np.meshgrid(uu, vv, indexing="ij")
        th = np.vectorize(lambda a, b: float(thickness(a, b)))(Ug, Vg)
    else:
        th = np.broadcast_to(np.asarray(thickness, dtype=np.float64), (U, V))
    if np.any(th <= 0):
        raise MeshError("thicken: thickness must be > 0 everywhere")
    a, b = {"centre": (0.5, 0.5), "outward": (1.0, 0.0), "inward": (0.0, 1.0)}[offset]
    F = G + nrm * (a * th)[..., None]
    Bk = G - nrm * (b * th)[..., None]
    g = {"front": 1, "back": 2, "rim": 3}
    if groups == "single":
        g = {"front": 1, "back": 1, "rim": 1}
    elif groups:
        g.update(groups)
    rim = g["rim"] if isinstance(g["rim"], dict) else {k: g["rim"] for k in ("v0", "v1", "u0", "u1")}
    nu = U if periodic_u else U - 1
    front = g["front"]
    front = np.full((nu, V - 1), int(front)) if np.ndim(front) == 0 else np.asarray(front, dtype=np.int64)
    if front.shape != (nu, V - 1):
        raise MeshError(f"thicken: front groups shape {front.shape}, expected {(nu, V - 1)}")

    def f(u, v):
        return (u % U) * V + v

    def bk(u, v):
        return U * V + (u % U) * V + v

    faces, fg = [], []
    for u in range(nu):
        for v in range(V - 1):
            faces.append([f(u, v), f(u + 1, v), f(u + 1, v + 1), f(u, v + 1)])
            fg.append(int(front[u, v]))
            faces.append([bk(u, v), bk(u, v + 1), bk(u + 1, v + 1), bk(u + 1, v)])
            fg.append(int(g["back"]))
        faces.append([f(u + 1, 0), f(u, 0), bk(u, 0), bk(u + 1, 0)])
        fg.append(int(rim.get("v0", 3)))
        faces.append([f(u, V - 1), f(u + 1, V - 1), bk(u + 1, V - 1), bk(u, V - 1)])
        fg.append(int(rim.get("v1", 3)))
    if not periodic_u:
        for v in range(V - 1):
            faces.append([f(0, v), f(0, v + 1), bk(0, v + 1), bk(0, v)])
            fg.append(int(rim.get("u0", 3)))
            faces.append([f(U - 1, v + 1), f(U - 1, v), bk(U - 1, v), bk(U - 1, v + 1)])
            fg.append(int(rim.get("u1", 3)))
    mesh = _outward(Mesh(np.concatenate([F.reshape(-1, 3), Bk.reshape(-1, 3)]), faces, fg))
    if return_sides:
        return mesh, {"front": F, "back": Bk}
    return mesh


def revolve(profile, n: int = 24, groups=1, cap_groups=None, closed: bool = False, center=(0.0, 0.0, 0.0),
            phase_deg: float = 0.0) -> Mesh:
    """Surface of revolution about the vertical axis through ``center``.  ``profile`` ``(K, 2)`` of
    ``(r, z)`` from bottom to top; an end point with ``r == 0`` becomes a pole, an end with ``r > 0`` a
    flat cap.  ``closed=True`` treats the profile as a closed loop (all ``r > 0``; e.g. a rectangle gives
    a band / washer, a circle a torus).  ``groups`` per profile segment as in :func:`loft`."""
    Pr = np.asarray(profile, dtype=np.float64).reshape(-1, 2)
    c = np.asarray(center, dtype=np.float64)
    t = np.radians(phase_deg) + 2.0 * np.pi * np.arange(n) / n
    cs, sn = np.cos(t), np.sin(t)

    def ring(r, z):
        return np.stack([c[0] + r * cs, c[1] + r * sn, np.full(n, c[2] + z)], axis=1)

    if closed:
        if np.any(Pr[:, 0] <= 0):
            raise MeshError("revolve: a closed profile needs r > 0")
        return loft([ring(r, z) for r, z in Pr], periodic_v=True, groups=groups)
    lo, hi = 0, len(Pr)
    cap_s, cap_e = "flat", "flat"
    if Pr[0, 0] <= 1e-12:
        cap_s, lo = ("pole", c + np.array([0.0, 0.0, Pr[0, 1]])), 1
    if Pr[-1, 0] <= 1e-12:
        cap_e, hi = ("pole", c + np.array([0.0, 0.0, Pr[-1, 1]])), len(Pr) - 1
    if np.any(Pr[lo:hi, 0] <= 1e-12):
        raise MeshError("revolve: only the end points may lie on the axis")
    g = np.asarray(groups, dtype=np.int64)
    cg = list(cap_groups) if cap_groups is not None else [None, None]
    if g.ndim == 1:                       # one group per profile segment
        if len(g) != len(Pr) - 1:
            raise MeshError(f"revolve: {len(g)} groups for {len(Pr) - 1} profile segments")
        if lo == 1 and cg[0] is None:
            cg[0] = int(g[0])
        if hi == len(Pr) - 1 and cg[1] is None:
            cg[1] = int(g[-1])
        g = g[lo:hi - 1]
    return loft([ring(r, z) for r, z in Pr[lo:hi]], cap_s, cap_e, groups=g, cap_groups=cg)


def superellipsoid(center, radii, nu: int = 24, nv: int = 12, e_ring: float = 2.0, e_vert: float = 2.0,
                   group: int = 1, z_squash=None) -> Mesh:
    """Superellipsoid with semi-axes ``radii`` at ``center``: ``e_ring`` is the exponent of the horizontal
    sections (2 = ellipse, larger = boxier), ``e_vert`` of the vertical profile.  ``nu`` points per ring,
    ``nv`` latitude bands (poles at top and bottom).  ``z_squash(z_unit) -> factor`` optionally scales
    each ring (e.g. to make an egg)."""
    c = np.asarray(center, dtype=np.float64)
    rx, ry, rz = radii
    rings = []
    for j in range(nv - 1, 0, -1):
        th = np.pi * j / nv                         # bottom (j = nv-1) to top (j = 1)
        zr = float(_spow(np.cos(th), 2.0 / e_vert))
        rr = float(np.abs(np.sin(th)) ** (2.0 / e_vert))
        k = 1.0 if z_squash is None else float(z_squash(zr))
        ring = superellipse_ring(rx * rr * k, ry * rr * k, nu, e_ring, uniform=False)
        ring[:, 2] = rz * zr
        rings.append(ring + c)
    return loft(rings, ("pole", c - [0.0, 0.0, rz]), ("pole", c + [0.0, 0.0, rz]), groups=group)


def ellipsoid(center, radii, nu: int = 24, nv: int = 12, group: int = 1) -> Mesh:
    """Ellipsoid with semi-axes ``radii`` at ``center`` (``nu`` points per ring, ``nv`` bands)."""
    return superellipsoid(center, radii, nu, nv, 2.0, 2.0, group)


def torus(center, major: float, minor, nu: int = 24, nv: int = 8, normal=(0.0, 0.0, 1.0), group: int = 1,
          minor_z=None) -> Mesh:
    """Torus around ``normal`` through ``center``: ``major`` radius, ``minor`` tube radius (``minor_z`` a
    different half height along ``normal`` for an elliptic tube section, e.g. a flat band)."""
    mz = minor if minor_z is None else minor_z
    t = 2.0 * np.pi * np.arange(nv) / nv
    prof = np.stack([major + minor * np.cos(t), mz * np.sin(t)], axis=1)
    m = revolve(prof, nu, closed=True, groups=group)
    x, y, z = frame_from_z(normal)
    return m.transform(np.stack([x, y, z], axis=1), center)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    """Result of :func:`validate`.  ``errors`` lists every broken rule (empty = valid)."""

    name: str
    n_vertices: int = 0
    n_faces: int = 0
    n_triangles: int = 0
    n_shells: int = 0
    bbox: tuple = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    z_min: float = 0.0
    shells: list = field(default_factory=list)
    tiny_faces: list = field(default_factory=list)
    folded_faces: list = field(default_factory=list)
    duplicate_pairs: list = field(default_factory=list)
    unused_vertices: int = 0
    nested_shells: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        head = (f"{self.name}: {self.n_shells} shell(s), {self.n_vertices} vertices, {self.n_faces} faces, "
                f"{self.n_triangles} triangles, z_min {self.z_min:.6f}")
        if self.ok:
            return head + ", OK"
        return head + "\n  " + "\n  ".join(self.errors)


def _shell_labels(n_vertices: int, faces) -> tuple:
    """Connected components (through shared vertices): ``(vertex_label (N,), face_label (F,), n)``;
    labels are numbered by first appearance in face order (unused vertices get -1)."""
    parent = list(range(n_vertices))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for f in faces:
        r0 = find(f[0])
        for i in f[1:]:
            ri = find(i)
            if ri != r0:
                if ri < r0:
                    r0, ri = ri, r0
                parent[ri] = r0
    labels, vl = {}, np.full(n_vertices, -1, dtype=np.int64)
    fl = np.zeros(len(faces), dtype=np.int64)
    for k, f in enumerate(faces):
        r = find(f[0])
        if r not in labels:
            labels[r] = len(labels)
        fl[k] = labels[r]
    used = np.zeros(n_vertices, dtype=bool)
    for f in faces:
        used[f] = True
    for v in np.nonzero(used)[0]:
        vl[v] = labels[find(int(v))]
    return vl, fl, len(labels)


def winding_numbers(points, V, tris, chunk: int = 4096) -> np.ndarray:
    """Generalised winding numbers ``(P,)`` of ``points`` w.r.t. the triangles ``tris`` over ``V``
    (Van Oosterom–Strackee solid angles / 4π; ±1 inside a closed shell, 0 outside)."""
    X = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    out = np.zeros(X.shape[0])
    if not len(tris):
        return out
    A, B, C = V[tris[:, 0]], V[tris[:, 1]], V[tris[:, 2]]
    step = max(1, 2_000_000 // max(1, len(tris)))
    for k0 in range(0, X.shape[0], step):
        x = X[k0:k0 + step, None, :]
        a, b, c = A[None] - x, B[None] - x, C[None] - x
        la, lb, lc = (np.linalg.norm(a, axis=2), np.linalg.norm(b, axis=2), np.linalg.norm(c, axis=2))
        det = np.einsum("pti,pti->pt", a, np.cross(b, c))
        den = (la * lb * lc + np.einsum("pti,pti->pt", a, b) * lc + np.einsum("pti,pti->pt", b, c) * la
               + np.einsum("pti,pti->pt", c, a) * lb)
        out[k0:k0 + x.shape[0]] = (2.0 * np.arctan2(det, den)).sum(axis=1) / (4.0 * np.pi)
    return out


def validate(mesh: Mesh, name: str = "mesh", strict: bool = False, dup_tol: float = DUPLICATE_TOL,
             area_tol: float = AREA_TOL, z_tol: float = Z_TOL, check_nesting: bool = True,
             check_ground: bool = True) -> ValidationReport:
    """Check ``mesh`` against the castplane mesh rules (contract §5.2.3).

    Per shell (connected through shared vertices): every undirected edge in exactly two faces, used once
    in each direction (manifold, consistent winding), positive signed volume (outward).  Whole mesh:
    faces with ``>= 3`` distinct vertices and area ``> area_tol``, no folded face (a fan triangle whose
    normal opposes the face normal), no two vertices closer than ``dup_tol`` (castplane welds per
    object), no unused vertex, ``z_min >= -z_tol`` (``check_ground``), and (``check_nesting``) no shell
    whose lowest-index vertex lies inside another shell (castplane would require that shell inward and
    flip it: use :func:`fix_nesting`).  ``strict`` raises :class:`MeshError` with the summary."""
    V = mesh.vertices
    rep = ValidationReport(name=name, n_vertices=mesh.n_vertices, n_faces=mesh.n_faces,
                           n_triangles=mesh.n_triangles)
    if mesh.n_faces == 0 or mesh.n_vertices == 0:
        rep.errors.append("empty mesh")
        if strict:
            raise MeshError(rep.summary())
        return rep
    if not np.all(np.isfinite(V)):
        rep.errors.append("non-finite vertex coordinates")
    lo, hi = V.min(axis=0), V.max(axis=0)
    rep.bbox = (tuple(float(x) for x in lo), tuple(float(x) for x in hi))
    rep.z_min = float(lo[2])
    for k, f in enumerate(mesh.faces):
        if len(f) < 3 or len(set(f)) != len(f) or min(f) < 0 or max(f) >= mesh.n_vertices:
            rep.errors.append(f"face {k} has repeated or invalid vertex indices {f}")
    if rep.errors:
        if strict:
            raise MeshError(rep.summary())
        return rep
    vl, fl, ns = _shell_labels(mesh.n_vertices, mesh.faces)
    rep.n_shells = ns
    rep.unused_vertices = int(np.sum(vl < 0))
    if rep.unused_vertices:
        rep.errors.append(f"{rep.unused_vertices} unused vertices")
    # edges
    a = np.concatenate([np.asarray(f) for f in mesh.faces])
    b = np.concatenate([np.roll(np.asarray(f), -1) for f in mesh.faces])
    ef = np.repeat(np.arange(mesh.n_faces), [len(f) for f in mesh.faces])
    n = np.int64(mesh.n_vertices)
    dkey = a * n + b
    ukey = np.minimum(a, b) * n + np.maximum(a, b)
    uk, uinv, ucount = np.unique(ukey, return_inverse=True, return_counts=True)
    dk, dcount = np.unique(dkey, return_counts=True)
    dup_dir = set(dk[dcount > 1].tolist())
    bad_edge = np.zeros(len(uk), dtype=bool)
    shell_bad = {}
    for e in np.nonzero(ucount != 2)[0]:
        bad_edge[e] = True
    for k in np.nonzero(np.isin(dkey, list(dup_dir)))[0] if dup_dir else []:
        bad_edge[uinv[k]] = True
    tris, owner = triangulate(mesh.faces)
    A_, B_, C_ = V[tris[:, 0]], V[tris[:, 1]], V[tris[:, 2]]
    vol_t = np.einsum("ij,ij->i", A_, np.cross(B_, C_)) / 6.0
    vol = np.bincount(fl[owner], weights=vol_t, minlength=ns)
    for e in np.nonzero(bad_edge)[0]:
        k = int(np.nonzero(uinv == e)[0][0])
        s = int(fl[ef[k]])
        d = shell_bad.setdefault(s, {"boundary": 0, "overused": 0, "inconsistent": 0})
        if ucount[e] == 1:
            d["boundary"] += 1
        elif ucount[e] > 2:
            d["overused"] += 1
        else:
            d["inconsistent"] += 1
    for s in range(ns):
        faces_s = int(np.sum(fl == s))
        bad = shell_bad.get(s, {"boundary": 0, "overused": 0, "inconsistent": 0})
        manifold = not any(bad.values())
        info = {"index": s, "faces": faces_s, "vertices": int(np.sum(vl == s)), "volume": float(vol[s]),
                "manifold": manifold, **bad, "outward": bool(vol[s] > 0)}
        rep.shells.append(info)
        if not manifold:
            rep.errors.append(f"shell {s} ({faces_s} faces) not a closed consistent manifold: "
                              f"{bad['boundary']} boundary, {bad['overused']} over-used, "
                              f"{bad['inconsistent']} inconsistently wound edges")
        elif not vol[s] > 0:
            rep.errors.append(f"shell {s} ({faces_s} faces) is inside out (signed volume {vol[s]:.3e})")
    # faces
    nrm, area = face_normals(mesh)
    rep.tiny_faces = [int(k) for k in np.nonzero(area <= area_tol)[0]]
    if rep.tiny_faces:
        rep.errors.append(f"{len(rep.tiny_faces)} faces with area <= {area_tol:g} m^2 (first: {rep.tiny_faces[:5]})")
    tn = np.cross(B_ - A_, C_ - A_)
    # a fan triangle opposing the face normal by more than 0.1 % of the face's area (near-collinear slivers of
    # flat caps after rounding are harmless; a bow-tie quad or a fan over a reflex vertex is not)
    fold = np.einsum("ij,ij->i", tn, nrm[owner]) < -2e-3 * area[owner]
    rep.folded_faces = sorted(set(int(k) for k in owner[fold]) - set(rep.tiny_faces))
    if rep.folded_faces:
        rep.errors.append(f"{len(rep.folded_faces)} folded (bow-tie / reflex fan) faces "
                          f"(first: {rep.folded_faces[:5]})")
    # duplicates (cell hashing)
    cell = np.floor(V / dup_tol).astype(np.int64)
    buckets = {}
    for i, c in enumerate(map(tuple, cell)):
        buckets.setdefault(c, []).append(i)
    pairs = []
    for c, members in buckets.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    other = buckets.get((c[0] + dx, c[1] + dy, c[2] + dz))
                    if not other:
                        continue
                    for i in members:
                        for j in other:
                            if i < j and np.max(np.abs(V[i] - V[j])) < dup_tol:
                                pairs.append((i, j))
    rep.duplicate_pairs = sorted(set(pairs))
    if rep.duplicate_pairs:
        rep.errors.append(f"{len(rep.duplicate_pairs)} vertex pairs closer than {dup_tol:g} m "
                          f"(first: {rep.duplicate_pairs[:3]})")
    if check_ground and rep.z_min < -z_tol:
        rep.errors.append(f"vertices below the ground: z_min = {rep.z_min:.6g}")
    if check_nesting and ns > 1 and not rep.errors:
        rep.nested_shells = _nested_first_vertices(V, tris, fl[owner], vl, ns)
        for s, c, w in rep.nested_shells:
            rep.errors.append(f"shell {s}: its first vertex lies inside shell {c} (winding {w:.2f}); "
                              "castplane would flip it (use meshkit.fix_nesting)")
    if strict and rep.errors:
        raise MeshError(rep.summary())
    return rep


def _shell_tris(tris, tri_shell, ns):
    return [tris[tri_shell == s] for s in range(ns)]


def _nested_first_vertices(V, tris, tri_shell, vl, ns, thresh: float = 0.25):
    """``[(shell, other shell, winding)]`` for shells whose lowest-index vertex is inside another."""
    first = [int(np.nonzero(vl == s)[0][0]) for s in range(ns)]
    per = _shell_tris(tris, tri_shell, ns)
    bmin = np.array([V[np.unique(t)].min(axis=0) for t in per])
    bmax = np.array([V[np.unique(t)].max(axis=0) for t in per])
    out = []
    for s in range(ns):
        x = V[first[s]]
        for c in range(ns):
            if c == s or np.any(x < bmin[c]) or np.any(x > bmax[c]):
                continue
            w = float(winding_numbers(x, V, per[c])[0])
            if abs(w) > thresh:
                out.append((s, c, w))
    return out


def fix_nesting(mesh: Mesh, thresh: float = 0.25, strict: bool = True) -> Mesh:
    """Reorder vertices so that the lowest-index vertex of every shell lies outside all other shells.

    castplane orients each connected component by nesting parity, evaluated at the component's
    lowest-index vertex (contract §5.2.3 step 5): when that vertex is inside another shell of the same
    object (two overlapping shells, e.g. the neck pushed into the head), the shell would be flipped
    inward and ``MESH_WINDING_FIXED`` reported.  For each such shell the first (lowest-index) vertex that
    is outside every other shell is swapped with the shell's first vertex.  A shell with no vertex
    outside the others (completely buried in another) raises :class:`MeshError`, or is left as it is
    when ``strict`` is false."""
    V = mesh.vertices
    vl, fl, ns = _shell_labels(mesh.n_vertices, mesh.faces)
    if ns < 2:
        return mesh
    tris, owner = triangulate(mesh.faces)
    tri_shell = fl[owner]
    nested = _nested_first_vertices(V, tris, tri_shell, vl, ns, thresh)
    if not nested:
        return mesh
    per = _shell_tris(tris, tri_shell, ns)
    perm = np.arange(mesh.n_vertices)
    for s in sorted(set(n[0] for n in nested)):
        verts = np.nonzero(vl == s)[0]
        worst = np.zeros(len(verts))
        for c in range(ns):
            if c != s:
                worst = np.maximum(worst, np.abs(winding_numbers(V[verts], V, per[c])))
        ok = np.nonzero(worst < thresh)[0]
        if not len(ok):
            if not strict:
                continue
            raise MeshError(f"fix_nesting: shell {s} lies completely inside other shells")
        i0, i1 = int(verts[0]), int(verts[ok[0]])
        perm[i0], perm[i1] = i1, i0          # new vertex i0 is old i1 and vice versa
    inv = np.empty_like(perm)
    inv[perm] = np.arange(len(perm))
    faces = [[int(inv[i]) for i in f] for f in mesh.faces]
    return Mesh(V[perm], faces, mesh.groups)


# ---------------------------------------------------------------------------
# Smooth normals
# ---------------------------------------------------------------------------

def split_smooth(mesh: Mesh):
    """Vertices split at smooth-group boundaries with smoothed normals.

    Returns ``(positions (K, 3), normals (K, 3), tris (T, 3), tri_face (T,), corner_vertex (K,))``: a
    vertex shared by faces of one non-zero group gets one normal (area-weighted mean of those faces'
    Newell normals); a vertex on a group boundary is duplicated once per group; group-0 faces are flat
    (one copy per face).  ``corner_vertex`` maps each output vertex to the input vertex.  Polygons with more
    than four corners are fanned from the corner that maximises the smallest triangle (no slivers)."""
    nrm, area = face_normals(mesh)
    cv, ck = [], []
    for k, (f, g) in enumerate(zip(mesh.faces, mesh.groups)):
        key = g if g > 0 else -1 - k
        cv.extend(f)
        ck.extend([key] * len(f))
    cv = np.asarray(cv, dtype=np.int64)
    ck = np.asarray(ck, dtype=np.int64)
    cface = np.repeat(np.arange(mesh.n_faces), [len(f) for f in mesh.faces])
    keys = np.stack([cv, ck], axis=1)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    acc = np.zeros((len(uniq), 3))
    np.add.at(acc, inv, nrm[cface] * area[cface][:, None])
    ln = np.linalg.norm(acc, axis=1)
    normals = acc / np.where(ln > 0, ln, 1.0)[:, None]
    tris, tri_face = [], []
    pos = 0
    for k, f in enumerate(mesh.faces):
        c = inv[pos:pos + len(f)]
        if len(f) > 4:
            c = np.roll(c, -_best_fan_start(mesh.vertices[f]))
        for j in range(1, len(f) - 1):
            tris.append((c[0], c[j], c[j + 1]))
            tri_face.append(k)
        pos += len(f)
    return (mesh.vertices[uniq[:, 0]], normals, np.array(tris, dtype=np.int64).reshape(-1, 3),
            np.array(tri_face, dtype=np.int64), uniq[:, 0])


# ---------------------------------------------------------------------------
# castplane construction-ray budget
# ---------------------------------------------------------------------------

#: castplane draws construction rays for at most this many feature silhouette vertices per mesh object
#: and light; more raise the ``MESH_RAYS_CAPPED`` warning (contract §5.2.4).
MAX_FEATURE_SILHOUETTE_VERTICES = 64


def feature_silhouette_vertices(mesh: Mesh, light_dir, smooth_angle_deg: float = 30.0) -> np.ndarray:
    """Vertices on **feature** edges of the light silhouette (castplane's ray candidates, contract §5.2.4).

    ``light_dir`` points towards a directional light.  An edge is on the light silhouette when exactly
    one of its two faces is lit (``n·L > 0``); it is a feature edge when its faces have different smooth
    groups (or group 0 with a dihedral above ``smooth_angle_deg``).  castplane emits a warning
    (``MESH_RAYS_CAPPED``) when an object has more than :data:`MAX_FEATURE_SILHOUETTE_VERTICES` of them,
    so keep group boundaries off the shading terminator: a group boundary between a lit and an unlit
    region (a slab rim with its own group, a flat cap facing away from the light, the hem cap of a skirt)
    contributes all of its vertices on the lit side.  Returns the sorted vertex indices (ignores
    castplane's coplanar merge and ground clipping, so it is a close estimate)."""
    L = np.asarray(light_dir, dtype=np.float64)
    L = L / np.linalg.norm(L)
    nrm, _ = face_normals(mesh)
    lit = nrm @ L > 1e-9
    edges = {}
    for k, f in enumerate(mesh.faces):
        for a, b in zip(f, f[1:] + f[:1]):
            edges.setdefault((min(a, b), max(a, b)), []).append(k)
    cos_s = math.cos(math.radians(smooth_angle_deg))
    out = set()
    for (a, b), fs in edges.items():
        if len(fs) != 2:
            continue
        f0, f1 = fs
        if lit[f0] == lit[f1]:
            continue
        g0, g1 = mesh.groups[f0], mesh.groups[f1]
        smooth = (g0 == g1 != 0) or (g0 == g1 == 0 and float(nrm[f0] @ nrm[f1]) >= cos_s - 1e-9)
        if not smooth:
            out.update((a, b))
    return np.array(sorted(out), dtype=np.int64)


# --- additions by body ---------------------------------------------------------------------------------
# Helpers added by the body / limbs builder (body.py, limbs.py).  Appended only; nothing above is changed.

def catmull_rom(points, n: int, alpha: float = 0.5) -> np.ndarray:
    """``n`` points at equal arc length on the open centripetal Catmull-Rom spline through ``points``
    (both end points kept; the end tangents mirror the neighbouring segment)."""
    P = np.asarray(points, dtype=np.float64)
    if P.shape[0] < 3:
        return resample_polyline(P, n)
    Q = np.concatenate([2 * P[:1] - P[1:2], P, 2 * P[-1:] - P[-2:-1]], axis=0)
    dense = []
    for i in range(1, Q.shape[0] - 2):
        p0, p1, p2, p3 = Q[i - 1], Q[i], Q[i + 1], Q[i + 2]
        t0 = 0.0
        t1 = t0 + max(float(np.linalg.norm(p1 - p0)), 1e-12) ** alpha
        t2 = t1 + max(float(np.linalg.norm(p2 - p1)), 1e-12) ** alpha
        t3 = t2 + max(float(np.linalg.norm(p3 - p2)), 1e-12) ** alpha
        for t in np.linspace(t1, t2, 24, endpoint=False):
            a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
            a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
            a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
            b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
            b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
            dense.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    dense.append(P[-1])
    return resample_polyline(np.array(dense), n)


def polyline_at(points, fractions) -> np.ndarray:
    """Points at the given arc-length fractions (0..1) of the open polyline ``points``."""
    P = np.asarray(points, dtype=np.float64)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)]) / seg.sum()
    f = np.asarray(fractions, dtype=np.float64)
    return np.stack([np.interp(f, s, P[:, k]) for k in range(P.shape[1])], axis=1)


def strip_plate(side_a, side_b, normal, thickness: float, offset: str = "centre", tip: bool = True,
                group: int = 1) -> Mesh:
    """Closed plate between two polylines ``side_a`` / ``side_b`` ``(n, 3)`` running from the plate's
    root to its far end; with ``tip=True`` their last points coincide (a pointed or obliquely cut end:
    the last face is a triangle and the tip is one edge across the thickness).  ``normal`` (3,) or
    ``(n, 3)`` is the thickness direction per station; ``offset`` as in :func:`thicken`.  Every face has
    ``group`` (the outline draws as a silhouette).  Faces are quads and triangles."""
    A = np.asarray(side_a, dtype=np.float64)
    B = np.asarray(side_b, dtype=np.float64)
    n = A.shape[0]
    N = np.array(np.broadcast_to(np.asarray(normal, dtype=np.float64), (n, 3)))
    N /= np.linalg.norm(N, axis=1)[:, None]
    a, b = {"centre": (0.5, 0.5), "outward": (1.0, 0.0), "inward": (0.0, 1.0)}[offset]
    m = n - 1 if tip else n
    top = np.concatenate([A + a * thickness * N, B[:m] + a * thickness * N[:m]])
    bot = np.concatenate([A - b * thickness * N, B[:m] - b * thickness * N[:m]])
    V = np.concatenate([top, bot])
    nt = top.shape[0]

    def ia(i, k=0):
        return k * nt + i

    def ib(i, k=0):
        return k * nt + (n + i if i < m else n - 1)

    faces = []
    for i in range(n - 1):
        last = tip and i == n - 2
        if last:
            faces.append([ia(i), ia(i + 1), ib(i)])
            faces.append([ia(i, 1), ib(i, 1), ia(i + 1, 1)])
            faces.append([ib(i), ia(i + 1), ia(i + 1, 1), ib(i, 1)])
        else:
            faces.append([ia(i), ia(i + 1), ib(i + 1), ib(i)])
            faces.append([ia(i, 1), ib(i, 1), ib(i + 1, 1), ia(i + 1, 1)])
            faces.append([ib(i), ib(i + 1), ib(i + 1, 1), ib(i, 1)])
        faces.append([ia(i), ia(i, 1), ia(i + 1, 1), ia(i + 1)])
    faces.append([ia(0), ib(0), ib(0, 1), ia(0, 1)])
    if not tip:
        faces.append([ia(n - 1), ia(n - 1, 1), ib(n - 1, 1), ib(n - 1)])
    return _outward(Mesh(V, faces, group))


def ridge_band(border_a, border_b, normals, height: float, periodic: bool = True, group: int = 1) -> Mesh:
    """Thin decal band with a flat triangular section (3 faces per station step): the two borders
    ``(U, 3)`` lie on (or just above) the decorated surface and the ridge rises ``height`` along
    ``normals`` ``(U, 3)`` midway between them.  Seen from almost any side both borders are camera
    silhouettes (the bottom face looks away), and the ridge edge is not, so one group draws the stripe's
    two border lines.  ``periodic`` closes the band around (a ring); otherwise the ends get triangles."""
    A = np.asarray(border_a, dtype=np.float64)
    B = np.asarray(border_b, dtype=np.float64)
    Nn = np.asarray(normals, dtype=np.float64)
    Nn = Nn / np.linalg.norm(Nn, axis=1)[:, None]
    U = A.shape[0]
    R = 0.5 * (A + B) + height * Nn
    V = np.concatenate([A, R, B])
    faces = []
    steps = U if periodic else U - 1
    for j in range(steps):
        k = (j + 1) % U
        faces.append([j, k, U + k, U + j])
        faces.append([U + j, U + k, 2 * U + k, 2 * U + j])
        faces.append([2 * U + j, 2 * U + k, k, j])
    if not periodic:
        faces.append([0, U, 2 * U])
        faces.append([U - 1, 3 * U - 1, 2 * U - 1])
    return _outward(Mesh(V, faces, group))


# --- additions by headhair r1 ---

#: Relative height below which a quad counts as planar in :func:`_below_fan` (see there).
PLANAR_REL = 1e-9


def _below_fan(a, b, c, d) -> bool:
    """True iff quad corner ``d`` lies below the plane of triangle ``(a, b, c)`` (seen from outside), so the
    fan diagonal ``a``-``c`` is the quad's ridge.  A (near-)planar quad, ``|n . (d - a)| <= PLANAR_REL |n| |d - a|``,
    is not below: its sign there is rounding noise that the BLAS kernel picks (a Haswell and an AVX-512 build
    rotate different faces), and either diagonal gives the same surface, so keeping the given order makes the
    generated files the same on every build."""
    n = np.cross(b - a, c - a)
    w = d - a
    h = float(n @ w)
    return h < 0.0 and abs(h) > PLANAR_REL * float(np.linalg.norm(n)) * float(np.linalg.norm(w))


def inscribed_fan(mesh: Mesh) -> Mesh:
    """``mesh`` with every quad's vertex order rotated so that castplane's fan diagonal (first to third
    vertex) is the quad's *valley* diagonal (the fold bends inward, seen from outside).  On a convex surface
    the ridge diagonal bulges out beyond the quad's own edges, so near a silhouette it can cover the
    silhouette edge in projection and castplane's hidden-line pass drops a piece of the outline; with the
    valley diagonal every facet stays inside its edges.  It also makes mirrored halves triangulate as
    mirror images (symmetric outlines).  Topology, groups and vertices are unchanged."""
    V = mesh.vertices
    faces = []
    for f in mesh.faces:
        f = list(f)
        if len(f) == 4:
            if _below_fan(*(V[i] for i in f)):    # d below triangle (a, b, c): a-c is the ridge diagonal
                f = f[1:] + f[:1]
        faces.append(f)
    return Mesh(V.copy(), faces, mesh.groups)


# --- additions by body r2 ---

def fan_fold(mesh: Mesh, ridge) -> Mesh:
    """``mesh`` with each quad's vertex order rotated so that castplane's fan diagonal (first to third
    vertex) is the quad's *ridge* diagonal (the fold bulges outward, seen from outside) where ``ridge[k]`` is
    true and its *valley* diagonal elsewhere (as :func:`inscribed_fan`).  A thin closed band laid on a
    twisting surface (a decal stripe) can otherwise intersect itself: the twisted bottom quad's fan bulges up
    through the top faces and shows its back.  Bottom faces folded inward (valley) and top faces folded
    outward (ridge) keep the two sides apart.  Topology, groups and vertices are unchanged."""
    V = mesh.vertices
    faces = []
    for k, f in enumerate(mesh.faces):
        f = list(f)
        if len(f) == 4:
            is_ridge = _below_fan(*(V[i] for i in f))   # d below triangle (a, b, c): a-c is the ridge diagonal
            if is_ridge != bool(ridge[k]):
                f = f[1:] + f[:1]
        faces.append(f)
    return Mesh(V.copy(), faces, mesh.groups)


def surface_clearance(mesh: Mesh, points, directions) -> np.ndarray:
    """Signed height of each point ``(P, 3)`` above the (fan-triangulated) surface ``mesh``, measured along
    the line through it with unit ``directions`` ``(P, 3)`` (its "up"): the hit nearest to the point wins;
    positive when the surface lies below (``-direction``), negative when the point is under the surface;
    ``nan`` when the line misses the mesh."""
    P = np.asarray(points, dtype=np.float64)
    D = np.asarray(directions, dtype=np.float64)
    tris, _ = triangulate(mesh.faces)
    a, b, c = (mesh.vertices[tris[:, k]] for k in range(3))
    e1, e2 = b - a, c - a                                         # (T, 3)
    out = np.full(len(P), np.nan)
    for i in range(len(P)):
        d = -D[i]
        h = np.cross(d, e2)
        det = np.einsum("ij,ij->i", e1, h)
        ok = np.abs(det) > 1e-14
        f = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        s = P[i] - a
        u = f * np.einsum("ij,ij->i", s, h)
        q = np.cross(s, e1)
        v = f * (q @ d)
        t = f * np.einsum("ij,ij->i", e2, q)
        hit = ok & (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0)
        if hit.any():
            th = t[hit]
            out[i] = float(th[np.argmin(np.abs(th))])
    return out


def lift_band_borders(mesh: Mesh, border_a, border_b, up, clearance: float, samples: int = 7,
                      passes: int = 12) -> np.ndarray:
    """Per-station lift ``(U,)`` along ``up`` ``(U, 3)`` that keeps both straight-chord borders of a decal band
    (``border_a`` / ``border_b`` ``(U, 3)``, stations in order) at least ``clearance`` above ``mesh`` at every
    one of ``samples`` points per chord: a coarse band's chords sag through a curved, faceted surface, which
    hides pieces of its border lines (dashed outlines).  Lifts only grow; deterministic."""
    A = np.asarray(border_a, dtype=np.float64)
    B = np.asarray(border_b, dtype=np.float64)
    N = np.asarray(up, dtype=np.float64)
    N = N / np.linalg.norm(N, axis=1)[:, None]
    U = len(A)
    lift = np.zeros(U)
    ss = np.linspace(0.0, 1.0, samples)
    for _ in range(passes):
        bump = np.zeros(U)
        for X in (A, B):
            Q = X + lift[:, None] * N
            pts, dirs, owners = [], [], []
            for j in range(U - 1):
                for s in ss:
                    pts.append(Q[j] + s * (Q[j + 1] - Q[j]))
                    d = (1.0 - s) * N[j] + s * N[j + 1]
                    dirs.append(d / np.linalg.norm(d))
                    owners.append(j)
            h = surface_clearance(mesh, np.array(pts), np.array(dirs))
            for j, hv in zip(owners, h):
                if np.isfinite(hv) and hv < clearance:
                    bump[j] = max(bump[j], clearance - hv)
                    bump[j + 1] = max(bump[j + 1], clearance - hv)
        if not np.any(bump > 1e-7):
            break
        lift += bump
    return lift


# --- additions by headhair r3 ---

def split_twisted(mesh: Mesh, max_deg: float, only=None) -> Mesh:
    """``mesh`` with every quad whose two fan triangles ``(f0, f1, f2)`` / ``(f0, f2, f3)`` differ in normal by
    more than ``max_deg`` degrees replaced by those two triangles (same group, same diagonal).  castplane
    decides a polygon's facing by its Newell normal but tests occlusion against its fan triangles: on a twisted
    quad near the outline one triangle can face the camera while the polygon does not (or the reverse), so the
    outline is drawn along an edge that the quad's own other triangle hides, and a piece of it is missing.  As
    two triangles the facing and the occluders agree.  The triangles (and the shape) are unchanged; each split
    quad adds one polygon.  ``only`` (one bool per face) limits the split to those faces."""
    V = mesh.vertices
    cos_max = math.cos(math.radians(max_deg))
    faces, groups = [], []
    for k, (f, g) in enumerate(zip(mesh.faces, mesh.groups)):
        f = list(f)
        if len(f) == 4 and (only is None or only[k]):
            a, b, c, d = (V[i] for i in f)
            n1 = np.cross(b - a, c - a)
            n2 = np.cross(c - a, d - a)
            l1, l2 = float(np.linalg.norm(n1)), float(np.linalg.norm(n2))
            if l1 > 0.0 and l2 > 0.0 and float(n1 @ n2) / (l1 * l2) < cos_max:
                faces += [[f[0], f[1], f[2]], [f[0], f[2], f[3]]]
                groups += [g, g]
                continue
        faces.append(f)
        groups.append(g)
    return Mesh(V.copy(), faces, groups)


# --- additions by model-checks M1: exact distances and robust triangle-triangle intersection ---------------------
#
# Used by ``checks.py`` (the clearance / poke-through report).  Everything is numpy, chunked to bound memory, and
# deterministic: candidate pairs come out in lexicographic (triangle of A, triangle of B) order and every reduction
# is a fixed-shape expression, so the same input gives the same output on every run.

#: Kinds returned by :func:`triangle_intersections`.
TT_NONE, TT_CROSSING, TT_CONTACT, TT_COINCIDENT = 0, 1, 2, 3
TT_KINDS = {TT_NONE: "none", TT_CROSSING: "crossing", TT_CONTACT: "contact", TT_COINCIDENT: "coincident"}


def _dot(a, b):
    return np.einsum("...i,...i->...", a, b)


def closest_point_on_triangle(P, A, B, C) -> np.ndarray:
    """Closest point of triangle ``(A, B, C)`` to ``P``, elementwise over broadcastable ``(..., 3)`` arrays
    (Ericson, *Real-Time Collision Detection* 5.1.5: Voronoi regions of the vertices, edges and face).  A
    degenerate triangle (a repeated vertex, collinear vertices: ``|ab x ac|^2 <= 1e-24 |ab|^2 |ac|^2``, where the
    region tests are not valid) returns the nearest of the closest points of its three edges instead."""
    P, A, B, C = np.broadcast_arrays(*(np.asarray(x, dtype=np.float64) for x in (P, A, B, C)))
    out = _closest_point_on_triangle_regions(P, A, B, C)
    ab, ac = B - A, C - A
    cr = np.cross(ab, ac)
    degen = _dot(cr, cr) <= 1e-24 * _dot(ab, ab) * _dot(ac, ac)
    if np.any(degen):
        best, bd = None, None
        for X, Y in ((A, B), (B, C), (C, A)):
            q = _closest_point_on_segment(P, X, Y)
            d = _dot(q - P, q - P)
            if best is None:
                best, bd = q, d
            else:
                better = d < bd
                best, bd = np.where(better[..., None], q, best), np.where(better, d, bd)
        out = np.where(degen[..., None], best, out)
    return out


def _closest_point_on_segment(P, X, Y) -> np.ndarray:
    """Closest point of segment ``X``-``Y`` to ``P`` (elementwise; a zero-length segment is its point)."""
    d = Y - X
    dd = _dot(d, d)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(dd > 0, _dot(P - X, d) / np.where(dd > 0, dd, 1.0), 0.0)
    return X + np.clip(t, 0.0, 1.0)[..., None] * d


def _closest_point_on_triangle_regions(P, A, B, C) -> np.ndarray:
    """The Voronoi-region evaluation of :func:`closest_point_on_triangle` (valid for non-degenerate triangles)."""
    ab, ac, ap = B - A, C - A, P - A
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    bp = P - B
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    cp = P - C
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    with np.errstate(divide="ignore", invalid="ignore"):
        den = va + vb + vc
        v_f = np.where(den != 0, vb / np.where(den != 0, den, 1.0), 0.0)
        w_f = np.where(den != 0, vc / np.where(den != 0, den, 1.0), 0.0)
        out = A + v_f[..., None] * ab + w_f[..., None] * ac                       # face region (default)
        # edge BC
        t_bc = (d4 - d3) / np.where((d4 - d3) + (d5 - d6) != 0, (d4 - d3) + (d5 - d6), 1.0)
        m = (va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0)
        out = np.where(m[..., None], B + t_bc[..., None] * (C - B), out)
        # edge AC
        t_ac = d2 / np.where(d2 - d6 != 0, d2 - d6, 1.0)
        m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        out = np.where(m[..., None], A + t_ac[..., None] * ac, out)
        # edge AB
        t_ab = d1 / np.where(d1 - d3 != 0, d1 - d3, 1.0)
        m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        out = np.where(m[..., None], A + t_ab[..., None] * ab, out)
    # vertex regions (checked last, so they win over the edge tests on their boundaries)
    out = np.where(((d6 >= 0) & (d5 <= d6))[..., None], C, out)
    out = np.where(((d3 >= 0) & (d4 <= d3))[..., None], B, out)
    out = np.where(((d1 <= 0) & (d2 <= 0))[..., None], A, out)
    return out


def point_triangle_distance(points, V, tris, chunk: int = 1_000_000):
    """Exact Euclidean distance from each point ``(P, 3)`` to the triangle set ``tris`` ``(T, 3)`` over ``V``:
    ``(distance (P,), nearest triangle (P,), nearest point (P, 3))``; ties go to the lowest triangle index.
    Chunked so that at most ``chunk`` point-triangle pairs are in memory.  With no triangles the distance is
    ``inf`` and the triangle ``-1``."""
    X = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    tris = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    n = X.shape[0]
    dist = np.full(n, np.inf)
    near = np.full(n, -1, dtype=np.int64)
    foot = np.full((n, 3), np.nan)
    if not len(tris) or not n:
        return dist, near, foot
    A, B, C = V[tris[:, 0]], V[tris[:, 1]], V[tris[:, 2]]
    step = max(1, chunk // len(tris))
    for k0 in range(0, n, step):
        x = X[k0:k0 + step, None, :]
        q = closest_point_on_triangle(x, A[None], B[None], C[None])                # (p, T, 3)
        d2 = _dot(q - x, q - x)
        j = np.argmin(d2, axis=1)
        r = np.arange(len(j))
        dist[k0:k0 + len(j)] = np.sqrt(d2[r, j])
        near[k0:k0 + len(j)] = j
        foot[k0:k0 + len(j)] = q[r, j]
    return dist, near, foot


def closest_points_segments(P0, P1, Q0, Q1):
    """Closest points ``(on P0-P1, on Q0-Q1)`` of two segments, elementwise over ``(..., 3)`` arrays (Ericson
    5.1.9, with the degenerate cases of zero-length segments)."""
    P0, P1, Q0, Q1 = np.broadcast_arrays(*(np.asarray(x, dtype=np.float64) for x in (P0, P1, Q0, Q1)))
    d1, d2, r = P1 - P0, Q1 - Q0, P0 - Q0
    a, e, f = _dot(d1, d1), _dot(d2, d2), _dot(d2, r)
    c, b = _dot(d1, r), _dot(d1, d2)
    tiny = 1e-30
    den = a * e - b * b
    with np.errstate(divide="ignore", invalid="ignore"):
        s = np.where(den > tiny * np.maximum(a * e, tiny), np.clip((b * f - c * e) / np.where(den != 0, den, 1.0),
                                                                    0.0, 1.0), 0.0)
        s = np.where(a <= tiny, 0.0, s)
        t = np.where(e > tiny, (b * s + f) / np.where(e > tiny, e, 1.0), 0.0)
        # clamp t, then recompute s for the clamped t
        s_lo = np.where(a > tiny, np.clip(-c / np.where(a > tiny, a, 1.0), 0.0, 1.0), 0.0)
        s_hi = np.where(a > tiny, np.clip((b - c) / np.where(a > tiny, a, 1.0), 0.0, 1.0), 0.0)
        s = np.where(t < 0.0, s_lo, np.where(t > 1.0, s_hi, s))
        t = np.clip(t, 0.0, 1.0)
        s = np.where((a <= tiny) & (e > tiny), 0.0, s)
        t = np.where((a <= tiny) & (e > tiny), np.clip(f / np.where(e > tiny, e, 1.0), 0.0, 1.0), t)
        t = np.where((e <= tiny) & (a > tiny), 0.0, t)
        s = np.where((e <= tiny) & (a > tiny), np.clip(-c / np.where(a > tiny, a, 1.0), 0.0, 1.0), s)
    return P0 + s[..., None] * d1, Q0 + t[..., None] * d2


def triangle_pair_distance(TA, TB):
    """Exact distance between paired triangles ``TA[k]`` / ``TB[k]`` (``(K, 3, 3)`` each) when they do not
    intersect (0 or a rounding-sized value when they do; use :func:`triangle_intersections` for that):
    ``(distance (K,), point on A (K, 3), point on B (K, 3))``.  The minimum of the 6 vertex-to-triangle and 9
    edge-to-edge distances, in that fixed order (ties: the first)."""
    TA = np.asarray(TA, dtype=np.float64).reshape(-1, 3, 3)
    TB = np.asarray(TB, dtype=np.float64).reshape(-1, 3, 3)
    cand_a, cand_b = [], []
    for i in range(3):                                   # A's vertices to B
        cand_a.append(TA[:, i])
        cand_b.append(closest_point_on_triangle(TA[:, i], TB[:, 0], TB[:, 1], TB[:, 2]))
    for i in range(3):                                   # B's vertices to A
        cand_a.append(closest_point_on_triangle(TB[:, i], TA[:, 0], TA[:, 1], TA[:, 2]))
        cand_b.append(TB[:, i])
    for i in range(3):
        for j in range(3):
            pa, pb = closest_points_segments(TA[:, i], TA[:, (i + 1) % 3], TB[:, j], TB[:, (j + 1) % 3])
            cand_a.append(pa)
            cand_b.append(pb)
    PA, PB = np.stack(cand_a, axis=1), np.stack(cand_b, axis=1)          # (K, 15, 3)
    d = np.sqrt(_dot(PA - PB, PA - PB))
    j = np.argmin(d, axis=1)
    r = np.arange(len(j))
    return d[r, j], PA[r, j], PB[r, j]


def triangle_bbox_pairs(VA, tris_a, VB, tris_b, pad: float = 0.0, chunk: int = 2_000_000):
    """Candidate triangle pairs ``(ia (K,), ib (K,))`` whose bounding boxes, each grown by ``pad``, overlap; in
    lexicographic ``(ia, ib)`` order.  Chunked over A's triangles."""
    ta = np.asarray(tris_a, dtype=np.int64).reshape(-1, 3)
    tb = np.asarray(tris_b, dtype=np.int64).reshape(-1, 3)
    if not len(ta) or not len(tb):
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    PA, PB = VA[ta], VB[tb]
    alo, ahi = PA.min(axis=1) - pad, PA.max(axis=1) + pad
    blo, bhi = PB.min(axis=1), PB.max(axis=1)
    out_a, out_b = [], []
    step = max(1, chunk // len(tb))
    for k0 in range(0, len(ta), step):
        lo, hi = alo[k0:k0 + step, None, :], ahi[k0:k0 + step, None, :]
        hit = np.all((lo <= bhi[None]) & (hi >= blo[None]), axis=2)
        i, j = np.nonzero(hit)
        out_a.append(i + k0)
        out_b.append(j)
    return np.concatenate(out_a), np.concatenate(out_b)


def _plane_distances(T, R):
    """Signed distances ``(K, 3)`` of the vertices of ``T`` to the planes of ``R`` (unit ``R`` normals, right
    hand ``(r1 - r0) x (r2 - r0)``), and those unit normals ``(K, 3)``."""
    n = np.cross(R[:, 1] - R[:, 0], R[:, 2] - R[:, 0])
    ln = np.linalg.norm(n, axis=1)
    n = n / np.where(ln > 0, ln, 1.0)[:, None]
    return _dot(T - R[:, None, 0], n[:, None, :]), n


def _plane_cut(T, d):
    """The two end points ``(K, 2, 3)`` of the zero set of the signed distances ``d`` ``(K, 3)`` on triangles ``T``
    that straddle their plane (one ``d > 0`` and one ``d < 0``): the edge points where ``d`` changes sign and any
    vertex with ``d == 0``.  The two candidates farthest apart are kept."""
    pts = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        di, dj = d[:, i], d[:, j]
        cross = (di * dj) < 0
        t = np.where(cross, di / np.where(cross, di - dj, 1.0), np.nan)
        pts.append(T[:, i] + t[:, None] * (T[:, j] - T[:, i]))
    for i in range(3):
        pts.append(np.where((d[:, i] == 0)[:, None], T[:, i], np.nan))
    P = np.stack(pts, axis=1)                                                   # (K, 6, 3), nan = absent
    ok = np.all(np.isfinite(P), axis=2)
    Q = np.where(ok[..., None], P, 0.0)
    D = np.linalg.norm(Q[:, :, None, :] - Q[:, None, :, :], axis=3)
    D = np.where(ok[:, :, None] & ok[:, None, :], D, -1.0)
    flat = np.argmax(D.reshape(len(T), -1), axis=1)
    i0, i1 = flat // 6, flat % 6
    r = np.arange(len(T))
    return np.stack([Q[r, i0], Q[r, i1]], axis=1)


def _clip_convex_2d(poly, clip):
    """Sutherland-Hodgman: convex polygon ``poly`` ``(n, 2)`` clipped by the convex CCW polygon ``clip``."""
    out = [tuple(p) for p in poly]
    m = len(clip)
    for k in range(m):
        a, b = clip[k], clip[(k + 1) % m]
        ex, ey = b[0] - a[0], b[1] - a[1]

        def side(p):
            return ex * (p[1] - a[1]) - ey * (p[0] - a[0])

        src, out = out, []
        if not src:
            break
        for i in range(len(src)):
            p, q = src[i], src[(i + 1) % len(src)]
            sp, sq = side(p), side(q)
            if sp >= 0:
                out.append(p)
            if (sp >= 0) != (sq >= 0):
                t = sp / (sp - sq)
                out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return np.array(out, dtype=np.float64).reshape(-1, 2)


def _polygon_area_2d(P) -> float:
    if len(P) < 3:
        return 0.0
    x, y = P[:, 0], P[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _coplanar_overlap(ta, tb, ref):
    """Overlap polygon ``(n, 3)`` of two (near-)coplanar triangles ``ta``, ``tb`` ``(3, 3)``, both projected onto
    the plane of ``ref`` (``ta`` or ``tb``), and its area."""
    o = ref[0]
    n = np.cross(ref[1] - ref[0], ref[2] - ref[0])
    n = n / np.linalg.norm(n)
    u = ref[1] - ref[0]
    u = u / np.linalg.norm(u)
    w = np.cross(n, u)

    def to2(T):
        P = np.stack([_dot(T - o, u), _dot(T - o, w)], axis=1)
        return P if _polygon_area_2d(P) >= 0 else P[::-1]

    poly = _clip_convex_2d(to2(ta), to2(tb))
    area = abs(_polygon_area_2d(poly))
    return o + poly[:, :1] * u + poly[:, 1:2] * w, area


def _edge_crossings(VX, tx, ix, X, dX, Y, nY, eps: float) -> list:
    """Crossings of a surface X through triangle Y along an edge of X (the edge-crossing pass of
    :func:`triangle_intersections`): for each contact pair ``k`` (X triangle ``tx[ix[k]]`` with vertices ``X[k]``
    and plane distances ``dX[k]`` to triangle ``Y[k]`` of unit normal ``nY[k]``), an edge of the X triangle with
    both ends within ``eps`` of Y's plane, whose two triangles' opposite vertices lie beyond ``+eps`` and ``-eps``
    of it, and which runs through the interior of Y's triangle (clipped to the triangle shrunk by ``eps`` in its
    plane, a positive length is left) is a crossing.  Returns ``[(k, segment start, segment end)]`` with the edge
    clipped to Y's (unshrunk) triangle.  An edge on a mesh boundary (one triangle; e.g. a face subset) is never
    one.  An X edge lying along a Y edge (both surfaces creased on the same line) is left a contact: there the
    sign test alone cannot tell crossing from touching (a known limit)."""
    out = []
    flat = np.abs(dX) <= eps
    cand = [(k, i) for k in range(len(X)) for i in range(3) if flat[k, i] and flat[k, (i + 1) % 3]]
    if not cand:
        return out
    for k, i in cand:
        t = tx[ix[k]]
        u, v, w = int(t[i]), int(t[(i + 1) % 3]), int(t[(i + 2) % 3])
        d1 = float(dX[k, (i + 2) % 3])
        on_edge = np.nonzero(np.sum((tx == u) | (tx == v), axis=1) == 2)[0]
        if len(on_edge) != 2:
            continue
        other = tx[on_edge[0]] if int(on_edge[1]) == int(ix[k]) else tx[on_edge[1]]
        w2 = [int(q) for q in other if int(q) not in (u, v)]
        if len(w2) != 1 or w2[0] == w:
            continue
        d2 = float(_dot(VX[w2[0]] - Y[k, 0], nY[k]))
        if not ((d1 > eps and d2 < -eps) or (d1 < -eps and d2 > eps)):
            continue
        P, Q = VX[u], VX[v]
        lo, hi = 0.0, 1.0
        lo_s, hi_s = 0.0, 1.0                                                  # clipped to the shrunk triangle
        for j in range(3):
            a, b, c = Y[k, j], Y[k, (j + 1) % 3], Y[k, (j + 2) % 3]
            m = np.cross(nY[k], b - a)
            lm = float(np.linalg.norm(m))
            if lm == 0.0:
                lo = hi = lo_s = hi_s = None
                break
            m = m / lm
            if float(_dot(c - a, m)) < 0:
                m = -m
            sp, sq = float(_dot(P - a, m)), float(_dot(Q - a, m))
            for off, which in ((0.0, "full"), (eps, "shrunk")):
                l0, l1 = (lo, hi) if which == "full" else (lo_s, hi_s)
                if sp == sq:
                    if sp < off:
                        l0, l1 = 1.0, 0.0
                else:
                    t0 = (off - sp) / (sq - sp)
                    if sq > sp:
                        l0 = max(l0, t0)
                    else:
                        l1 = min(l1, t0)
                if which == "full":
                    lo, hi = l0, l1
                else:
                    lo_s, hi_s = l0, l1
        if lo is None or hi_s <= lo_s:
            continue
        out.append((k, P + lo * (Q - P), P + hi * (Q - P)))
    return out


def triangle_intersections(VA, tris_a, VB, tris_b, eps: float, pairs=None) -> dict:
    """Classify every candidate triangle pair of two triangle sets under the tolerance ``eps`` (metres).

    ``pairs`` is ``(ia, ib)`` (default: :func:`triangle_bbox_pairs` with ``pad = eps``).  From the signed
    distances of each triangle's vertices to the other triangle's plane:

    * **coincident** (:data:`TT_COINCIDENT`): all three vertices of one triangle lie within ``eps`` of the other's
      plane and the two overlap in that plane by more than ``eps**2`` in area; the overlap polygon is returned;
    * **crossing** (:data:`TT_CROSSING`): both triangles have a vertex above ``+eps`` and one below ``-eps``, and
      their cuts along the planes' intersection line overlap (any positive length: a short segment is still a
      crossing); the segment is returned;
    * **contact** (:data:`TT_CONTACT`): any other pair whose exact distance is ``<= eps`` (touching at a vertex or
      an edge, or coplanar within ``eps`` with no area to speak of); the nearest point pair is returned;
    * **crossing along an edge** (also :data:`TT_CROSSING`; the edge-crossing pass over the contact pairs, both
      directions, :func:`_edge_crossings`): an edge of one triangle lies within ``eps`` of the other's plane, inside
      it, and the two triangles on that edge leave on opposite sides beyond ``eps`` -- the surface crosses along its
      own edge (a ring row exactly on the other part's plane), which no single triangle pair shows.  Both triangles
      on the edge are marked, each with the edge clipped to the other triangle as its segment.  It needs the edge's
      second triangle in the same triangle set, so on a face subset a boundary edge is never one;
    * none (dropped): everything else.

    Returns ``{"ia", "ib", "kind", "seg" (K, 2, 3), "polys" (list of (n, 3) or None), "near_band" (K,) bool,
    "n_candidates", "n_near_band"}`` for the classified (not-none) pairs, in candidate order.  ``seg`` holds the
    crossing segment, the coincident polygon's bbox diagonal or the contact point twice.  ``near_band`` marks a pair
    with a vertex-to-plane distance in ``[eps / 10, 10 eps]`` (its kind may depend on ``eps``);
    ``n_near_band`` counts them over all candidates."""
    ta = np.asarray(tris_a, dtype=np.int64).reshape(-1, 3)
    tb = np.asarray(tris_b, dtype=np.int64).reshape(-1, 3)
    if pairs is None:
        pairs = triangle_bbox_pairs(VA, ta, VB, tb, pad=eps)
    ia, ib = (np.asarray(p, dtype=np.int64) for p in pairs)
    empty = {"ia": ia[:0], "ib": ib[:0], "kind": np.zeros(0, dtype=np.int64), "seg": np.zeros((0, 2, 3)),
             "polys": [], "near_band": np.zeros(0, dtype=bool), "n_candidates": int(len(ia)), "n_near_band": 0}
    if not len(ia):
        return empty
    A, B = VA[ta[ia]], VB[tb[ib]]                                                   # (K, 3, 3)
    dA, nB = _plane_distances(A, B)
    dB, nA = _plane_distances(B, A)
    absd = np.concatenate([np.abs(dA), np.abs(dB)], axis=1)
    near_band = np.any((absd >= eps / 10.0) & (absd <= 10.0 * eps), axis=1)
    copA = np.all(np.abs(dA) <= eps, axis=1)
    copB = np.all(np.abs(dB) <= eps, axis=1)
    sepA = np.all(dA > eps, axis=1) | np.all(dA < -eps, axis=1)
    sepB = np.all(dB > eps, axis=1) | np.all(dB < -eps, axis=1)
    strA = np.any(dA > eps, axis=1) & np.any(dA < -eps, axis=1)
    strB = np.any(dB > eps, axis=1) & np.any(dB < -eps, axis=1)
    kind = np.zeros(len(ia), dtype=np.int64)
    seg = np.zeros((len(ia), 2, 3))
    polys = [None] * len(ia)
    # coplanar within eps: coincident or (thin) contact
    cop = np.nonzero((copA | copB) & ~(sepA | sepB))[0]
    for k in cop:
        ref = B[k] if copA[k] else A[k]
        poly, area = _coplanar_overlap(A[k], B[k], ref)
        if area > eps * eps:
            kind[k] = TT_COINCIDENT
            polys[k] = poly
            seg[k] = (poly.min(axis=0), poly.max(axis=0))
    # crossing: both straddle beyond eps and the cuts overlap along the line
    cr = np.nonzero(strA & strB & ~(copA | copB))[0]
    if len(cr):
        L = np.cross(nA[cr], nB[cr])
        L = L / np.linalg.norm(L, axis=1)[:, None]
        SA = _plane_cut(A[cr], dA[cr])
        SB = _plane_cut(B[cr], dB[cr])
        tA, tB = _dot(SA, L[:, None, :]), _dot(SB, L[:, None, :])                  # (n, 2)
        oA = np.argsort(tA, axis=1, kind="stable")
        r = np.arange(len(cr))
        tA0, tA1 = tA[r, oA[:, 0]], tA[r, oA[:, 1]]
        PA0, PA1 = SA[r, oA[:, 0]], SA[r, oA[:, 1]]
        lo = np.maximum(tA0, np.minimum(tB[:, 0], tB[:, 1]))
        hi = np.minimum(tA1, np.maximum(tB[:, 0], tB[:, 1]))
        ok = hi > lo
        span = np.where(tA1 > tA0, tA1 - tA0, 1.0)
        s0, s1 = (lo - tA0) / span, (hi - tA0) / span
        kind[cr[ok]] = TT_CROSSING
        seg[cr[ok], 0] = (PA0 + s0[:, None] * (PA1 - PA0))[ok]
        seg[cr[ok], 1] = (PA0 + s1[:, None] * (PA1 - PA0))[ok]
    # contact: whatever is left and not separated, if the exact distance is within eps
    rest = np.nonzero((kind == TT_NONE) & ~(sepA | sepB))[0]
    if len(rest):
        d, pa, pb = triangle_pair_distance(A[rest], B[rest])
        hit = d <= eps
        kind[rest[hit]] = TT_CONTACT
        seg[rest[hit], 0] = pa[hit]
        seg[rest[hit], 1] = pb[hit]
    # crossing along a mesh edge: every triangle pair there is a contact (each triangle has one vertex off the
    # other's plane, on one side only), but the two triangles on the edge leave on opposite sides
    ct = np.nonzero(kind == TT_CONTACT)[0]
    if len(ct):
        for k, s0, s1 in _edge_crossings(VA, ta, ia[ct], A[ct], dA[ct], B[ct], nB[ct], eps) + \
                _edge_crossings(VB, tb, ib[ct], B[ct], dB[ct], A[ct], nA[ct], eps):
            kind[ct[k]] = TT_CROSSING
            seg[ct[k]] = (s0, s1)
    keep = np.nonzero(kind != TT_NONE)[0]
    return {"ia": ia[keep], "ib": ib[keep], "kind": kind[keep], "seg": seg[keep],
            "polys": [polys[k] for k in keep], "near_band": near_band[keep], "n_candidates": int(len(ia)),
            "n_near_band": int(np.sum(near_band))}
