"""Head and face of the Reiya model (SPEC.md §B): regions ``head``, ``eyes`` and ``face_marks``.

Regions and the objects they fill (SPEC.md §G, module -> regions mapping):

* ``head`` -> object ``head``: one closed skin shell for the skull and the face (front exponent 3.6, the V chin, the
  jaw rings turning under into the neck) with the nose bump in the mesh (§B.1); no ears (Decision 22);
* ``eyes`` -> objects ``eye_l`` / ``eye_r``: per eye a stack of thin slabs conforming to the face: sclera, iris (her
  right eye red ``iris_red``, her left eye blue ``iris_blue``), pupil (``pupil_red`` / ``pupil_blue``) and the
  highlights of ``rig.highlights`` (§B.2);
* ``face_marks`` -> objects ``face_marks_l`` / ``face_marks_r`` by side (the mouth in ``face_marks_l``): the two upper
  lash bands with their outer flicks (``lashes``), the brows, the closed-smile mouth and the six blush strokes
  (``face_marks``) (§B.2-§B.4).

How it is built (the bare section numbers are SPEC.md's):

* **Skin head** (§B.1): one loft of horizontal rings from a pole at the skull top to a pole under the chin.  Each ring
  is the §B.1 section at its height (front half the 3.6 superellipse round ``c``, back half an ellipse), with the
  ring points at fixed superellipse parameters (:data:`FRONT_FRACTIONS` of the arc length at the eye line), so
  consecutive rings correspond and no quad twists.  Above :data:`BACK_FULL_Z` (inside the bob and the dome from every
  view) a ring keeps only :data:`BACK_ANGLES_HIDDEN` behind its side points; a strip of triangles joins it to the
  rings below (:func:`_loft_rings`).  The rows are the profile's plus the nose rows; the nose bump
  (``rig.nose_bump``) moves the midline column and its neighbours forward.  Below the last back row (z 1.400) the
  back points run down the nape (``rig.nape``) into the neck, and the lowest rings rise towards the neck along
  ``rig.jaw_underside``: the face's sides turn under through several rings into a narrow keel under the chin (no flat
  shelf).  Behind the bob's front edge the side column :data:`CHEEK_BULGE_COLUMN` moves out by ``rig.cheek_bulge``
  (hidden under the curtain from every view), so in the front views the skin's outline lies behind the curtain and
  the cheek line is the curtain's edge alone.  The whole head is one smooth group: no line on the face, only
  silhouettes (§F).
* **Face features** are thin decals, one smooth group each (no construction ray): the big eye layers (sclera, iris,
  pupil) are slabs whose walls are undercut, so the front rim is a camera silhouette from the whole front half space;
  the narrow marks (lash bands, brows, mouth, blush strokes) are ridge decals (a triangular section: both borders on
  the face, a ridge :data:`RIDGE_RISE` over them, the bottom faces looking into the face, so both borders draw from
  every usual view); the highlights are low domes.  Each point of a feature outline lies on the smooth §B.1 surface
  (``rig.head_surface_y``) moved out by the layer's relief, then pushed out (along y only, so the outline keeps its
  front-view shape) until every vertex, edge midpoint and quad-diagonal midpoint clears the faceted skin by
  ``rig.decal_skin_clearance`` and every decal already placed under it by ``rig.decal_layer_step`` (the stacked eye
  layers stand >= 0.5 mm proud of the layer below).

:func:`skin_surface` (the head mesh with a ray caster) and :func:`face_point` are also used by ``hair.py``.
"""

from __future__ import annotations

import functools
import math

import numpy as np

from charmodel import meshkit as mk
from charmodel.meshkit import Part

from .rig import Rig

__all__ = ["REGIONS", "build", "skin_surface", "SkinSurface", "face_point", "smooth_face", "slab", "slab_faces",
           "oriented", "head_rows", "SIDES"]

#: The regions this module builds (``--only head`` selects all of them).
REGIONS = ("head", "eyes", "face_marks")

SIDES = (1, -1)                    # her left (+X), her right (-X)

# ---------------------------------------------------------------------------------------------------------------------
# Tessellation of the skin head (module constants: they choose the mesh, not the shape).  The rings are the §B.1
# profile rows plus the nose rows (1.441, 1.4355 the tip, 1.4285 the base); the skull above the forehead is under the
# hair, so it keeps only two rings.
# ---------------------------------------------------------------------------------------------------------------------
SKULL_ROWS = (1.570, 1.540)
#: Face rows from the forehead to the last full (back) row; the nose bump peaks on 1.4355 and ends on 1.4285.
FACE_ROWS = (1.505, 1.495, 1.482, 1.470, 1.459, 1.447, 1.441, 1.4355, 1.4285, 1.426, 1.416, 1.410, 1.404, 1.400)
#: Jaw rows below the last back row: their back points run down the nape into the neck.
JAW_ROWS = (1.396, 1.392, 1.389)
#: Arc-length fractions of the front ring points on the quarter section at the eye line, from the midline (0) to the
#: side point (1); the same superellipse parameters are used on every ring.  0.028 is the nose's side column (x ~4 mm).
FRONT_FRACTIONS = (0.0, 0.028, 0.085, 0.16, 0.24, 0.32, 0.40, 0.50, 0.64, 0.81, 1.0)
#: Angles (degrees from her left side, through the back) of the back ring points.
BACK_ANGLES = (25.0, 90.0, 155.0)
#: Above this height the back of the skull is always inside the bob and the dome: its rings keep only the
#: BACK_ANGLES_HIDDEN points behind the side points (a strip of triangles joins the two kinds of ring).  Below it the
#: back of the jaw and the nape show from below.
BACK_FULL_Z = 1.462
BACK_ANGLES_HIDDEN = (90.0,)
#: Below the nape the midline back point lies inside the neck: this fraction of the neck's back half-depth behind the
#: neck's centre line.
NECK_INSIDE = 0.4
#: The jaw rows rise towards the neck along rig.jaw_underside by this fraction of its rise (the lowest ring fully).
JAW_LIFT = {1.396: 0.0, 1.392: 0.5, 1.389: 1.0}
#: Skin quads whose two fan triangles differ by more than this become two triangles (meshkit.split_twisted).
SKIN_TWIST_SPLIT_DEG = 10.0


def _side_name(side: int) -> str:
    return "l" if side > 0 else "r"


def _smoothstep(e0: float, e1: float, x):
    t = np.clip((np.asarray(x, dtype=np.float64) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _norm3(v) -> float:
    """Length of a 3-vector by an explicit sum (no BLAS kernel)."""
    return math.sqrt(float(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))


def _unit3(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    return v / _norm3(v)


def _dot3(a, b) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def _rows_norm(A) -> np.ndarray:
    """Row lengths of an ``(N, 3)`` array by explicit sums."""
    A = np.asarray(A, dtype=np.float64)
    return np.sqrt(A[:, 0] * A[:, 0] + A[:, 1] * A[:, 1] + A[:, 2] * A[:, 2])


# ---------------------------------------------------------------------------------------------------------------------
# skin head
# ---------------------------------------------------------------------------------------------------------------------

def head_rows():
    """All ring heights of the skin head, top to bottom."""
    return SKULL_ROWS + FACE_ROWS + JAW_ROWS


def _front_params(rig: Rig) -> np.ndarray:
    """Superellipse parameters ``t`` (pi/2 = the midline, 0 = the side point) of the front ring points: the
    :data:`FRONT_FRACTIONS` of arc length on the quarter section at the eye line."""
    hw, yf, _yb, c = rig.head_section(rig.eye_z)
    e = rig.face_front_exponent
    t = np.linspace(0.5 * np.pi, 0.0, 4001)
    x = hw * np.cos(t) ** (2.0 / e)
    y = c - (c - yf) * np.sin(t) ** (2.0 / e)
    s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    return np.interp(np.asarray(FRONT_FRACTIONS) * s[-1], s, t)


def _jaw_z(rig: Rig, y: float) -> float:
    ys = [p[0] for p in rig.jaw_underside]
    zs = [p[1] for p in rig.jaw_underside]
    return float(np.interp(y, ys, zs))


def _back_y(rig: Rig, z: float):
    """Back y of the ring at ``z`` and whether it is the skull's (False below the nape: the neck)."""
    hw, yf, yb, c = rig.head_section(z)
    if yb is not None:
        return yb
    last = [r for r in rig.head_profile if r[3] is not None][-1]
    ny, nz = rig.nape
    if z >= nz:
        t = (last[0] - z) / (last[0] - nz)
        return last[3] + t * (ny - last[3])
    _hw, yf_n, yb_n = rig.neck_section(z)
    cn = 0.5 * (yf_n + yb_n)
    return cn + NECK_INSIDE * (yb_n - cn)


def _back_angles(z: float):
    return BACK_ANGLES if z <= BACK_FULL_Z else BACK_ANGLES_HIDDEN


def _ring(rig: Rig, z: float, params) -> np.ndarray:
    """Head ring at ``z``: CCW seen from +Z starting at her left side point: the side point, the back points (left ->
    back -> right), the right side point, the front half from her right to her left."""
    hw, yf, _yb, c = rig.head_section(z)
    yb = _back_y(rig, z)
    e = rig.face_front_exponent
    fx = hw * np.cos(params) ** (2.0 / e)
    fy = c - (c - yf) * np.sin(params) ** (2.0 / e)
    pts = [(hw, c, z)]
    for a in np.radians(_back_angles(z)):
        pts.append((hw * math.cos(a), c + (yb - c) * math.sin(a), z))
    pts.append((-hw, c, z))
    n = len(params)
    for k in range(n - 2, 0, -1):                     # her right front: side -> midline
        pts.append((-fx[k], fy[k], z))
    pts.append((0.0, fy[0], z))
    for k in range(1, n - 1):                          # her left front: midline -> side
        pts.append((fx[k], fy[k], z))
    P = np.array(pts, dtype=np.float64)
    nb = len(_back_angles(z))
    front = list(range(nb + 2, len(P)))
    for i in front:                                    # the nose bump (local, in the mesh only)
        P[i, 1] -= rig.nose_bump(float(P[i, 0]), z)
    b = _cheek_bulge(rig, z)
    if b > 0.0:                                        # the hidden cheek bulge (under the curtain)
        for i in (nb + 2, len(P) - 1):                 # her right, her left CHEEK_BULGE_COLUMN
            P[i, 0] += math.copysign(b, float(P[i, 0]))
    lift = JAW_LIFT.get(round(z, 4), 0.0)
    if lift:
        z0 = rig.jaw_underside[0][1]
        for i in [0, nb + 1] + front:
            P[i, 2] += lift * max(0.0, _jaw_z(rig, float(P[i, 1])) - z0)
    return P


#: The front ring column that the hidden cheek bulge moves out (the last before the side point: FRONT_FRACTIONS 0.81,
#: y ~ -0.037, behind the bob's front edge on every row it covers).
CHEEK_BULGE_COLUMN = len(FRONT_FRACTIONS) - 2


def _cheek_bulge(rig: Rig, z: float) -> float:
    """Outward move of :data:`CHEEK_BULGE_COLUMN` at ``z`` (``rig.cheek_bulge``, 0 outside its range)."""
    zs = [p[0] for p in rig.cheek_bulge]
    bs = [p[1] for p in rig.cheek_bulge]
    if z >= max(zs) or z <= min(zs):
        return 0.0
    order = np.argsort(zs)
    return float(np.interp(z, np.asarray(zs)[order], np.asarray(bs)[order]))


def _head_mesh(rig: Rig) -> mk.Mesh:
    params = _front_params(rig)
    rings = [_ring(rig, z, params) for z in head_rows()]
    top = rig.head_profile[0]
    ys = [p[0] for p in rig.jaw_underside]
    zs = [p[1] for p in rig.jaw_underside]
    # chin pole: on the jaw underside between the chin and the neck (the fan is the keel's flat bottom)
    yp = 0.5 * (ys[0] + ys[-1])
    apex_chin = (0.0, yp, float(np.interp(yp, ys, zs)) - CHIN_POLE_SAG)
    return mk.inscribed_fan(_loft_rings(rings, [_back_angles(z) for z in head_rows()], (0.0, top[2], top[0]),
                                        apex_chin))


def _loft_rings(rings, backs, apex_top, apex_bottom) -> mk.Mesh:
    """Closed shell through the head rings (``meshkit.loft``'s windings) whose back parts may differ in point count:
    there the strip between two rings is a zip of triangles by the back points' angles (0 her left side .. 180 her
    right side), elsewhere quads point by point."""
    V, starts = [], []
    for r in rings:
        starts.append(len(V))
        V.extend([np.asarray(p, dtype=np.float64) for p in r])
    faces = []
    for k in range(len(rings) - 1):
        A, B = starts[k], starts[k + 1]
        na, nb = len(backs[k]), len(backs[k + 1])
        ma, mb = len(rings[k]), len(rings[k + 1])
        # back: side L (0), backs, side R (n + 1)
        pa = [0.0] + list(backs[k]) + [180.0]
        pb = [0.0] + list(backs[k + 1]) + [180.0]
        i = j = 0
        while i < na + 1 or j < nb + 1:
            if i < na + 1 and j < nb + 1 and abs(pa[i + 1] - pb[j + 1]) < 1e-9:
                faces.append([A + i, A + i + 1, B + j + 1, B + j])
                i += 1
                j += 1
            elif j == nb + 1 or (i < na + 1 and pa[i + 1] < pb[j + 1]):
                faces.append([A + i, A + i + 1, B + j])
                i += 1
            else:
                faces.append([A + i, B + j + 1, B + j])
                j += 1
        # front: side R -> front points -> side L (index 0, wrapping)
        fa = list(range(na + 1, ma)) + [0]
        fb = list(range(nb + 1, mb)) + [0]
        for q in range(len(fa) - 1):
            faces.append([A + fa[q], A + fa[q + 1], B + fb[q + 1], B + fb[q]])
    top = len(V)
    V.append(np.asarray(apex_top, dtype=np.float64))
    m = len(rings[0])
    for j in range(m):
        faces.append([top, starts[0] + (j + 1) % m, starts[0] + j])
    bot = len(V)
    V.append(np.asarray(apex_bottom, dtype=np.float64))
    m = len(rings[-1])
    for j in range(m):
        faces.append([bot, starts[-1] + j, starts[-1] + (j + 1) % m])
    return oriented(mk.Mesh(np.array(V), faces, 1))


#: The chin pole sits this far under the jaw-underside line (a slightly convex keel bottom, no fold).
CHIN_POLE_SAG = 0.0005


class SkinSurface:
    """A mesh with ray casting along +Y (front-most hit over the faces looking towards -Y) and smoothed normals."""

    def __init__(self, mesh: mk.Mesh, front_only: bool = True):
        self.mesh = mesh
        V = mesh.vertices
        tris, _owner = mesh.triangles()
        a, b, c = V[tris[:, 0]], V[tris[:, 1]], V[tris[:, 2]]
        tn = np.cross(b - a, c - a)
        vn = np.zeros_like(V)
        for k in range(3):
            np.add.at(vn, tris[:, k], tn)
        self.vn = vn / _rows_norm(vn)[:, None]
        keep = tn[:, 1] < -1e-14 if front_only else np.ones(len(tris), dtype=bool)
        self.tris = tris[keep]
        self.A, self.B, self.C = a[keep], b[keep], c[keep]

    def y(self, x: float, z: float):
        """y of the front-most mesh point at ``(x, z)``, or None off the mesh."""
        h = self._hit(x, z)
        return None if h is None else h[0][1]

    def _hit(self, x: float, z: float):
        A, B, C = self.A, self.B, self.C
        v0x, v0z = B[:, 0] - A[:, 0], B[:, 2] - A[:, 2]
        v1x, v1z = C[:, 0] - A[:, 0], C[:, 2] - A[:, 2]
        v2x, v2z = x - A[:, 0], z - A[:, 2]
        den = v0x * v1z - v1x * v0z
        ok = np.abs(den) > 1e-16
        den = np.where(ok, den, 1.0)
        l1 = (v2x * v1z - v1x * v2z) / den
        l2 = (v0x * v2z - v2x * v0z) / den
        l0 = 1.0 - l1 - l2
        eps = -1e-9
        inside = ok & (l0 >= eps) & (l1 >= eps) & (l2 >= eps)
        if not inside.any():
            return None
        idx = np.nonzero(inside)[0]
        y = l0[idx] * A[idx, 1] + l1[idx] * B[idx, 1] + l2[idx] * C[idx, 1]
        j = int(np.argmin(y))
        k = idx[j]
        t = self.tris[k]
        n = l0[k] * self.vn[t[0]] + l1[k] * self.vn[t[1]] + l2[k] * self.vn[t[2]]
        return np.array([x, float(y[j]), z]), n / _norm3(n)

    def hit(self, x: float, z: float):
        """``(point, unit normal)`` of the front-most mesh point at ``(x, z)`` (raises off the mesh)."""
        h = self._hit(x, z)
        if h is None:
            raise mk.MeshError(f"face point ({x:.4f}, {z:.4f}) is off the mesh")
        return h


@functools.lru_cache(maxsize=4)
def skin_surface(rig: Rig) -> SkinSurface:
    """The skin head mesh of ``rig`` with its ray caster (cached per rig)."""
    return SkinSurface(_head_mesh(rig))


def face_point(rig: Rig, x: float, z: float, offset: float = 0.0) -> np.ndarray:
    """Point of the head mesh at ``(x, z)`` (front side), moved ``offset`` along the smoothed normal."""
    p, n = skin_surface(rig).hit(x, z)
    return p + offset * n


def smooth_face(rig: Rig, x: float, z: float, d: float = 2e-4):
    """``(point, unit outward normal)`` of the smooth §B.1 face surface (without the nose) at ``(x, z)``."""
    p = rig.head_surface_point(x, z)
    px = rig.head_surface_point(x + d, z) - rig.head_surface_point(x - d, z)
    pz = rig.head_surface_point(x, z + d) - rig.head_surface_point(x, z - d)
    n = _unit3(np.cross(pz, px))
    return p, (-n if n[1] > 0 else n)


# ---------------------------------------------------------------------------------------------------------------------
# slabs and decals
# ---------------------------------------------------------------------------------------------------------------------

def slab_faces(U: int, V: int):
    """Faces of a slab between a front and a back ``(U, V)`` grid (front vertices first, then back) and the kind of
    each face: ``("front"|"back", u, v)``, or a rim ``("v0"|"v1", u)`` / ``("u0"|"u1", v)``."""
    def f(u, v):
        return u * V + v

    def bk(u, v):
        return U * V + u * V + v

    faces, kinds = [], []
    for u in range(U - 1):
        for v in range(V - 1):
            faces.append([f(u, v), f(u + 1, v), f(u + 1, v + 1), f(u, v + 1)])
            kinds.append(("front", u, v))
            faces.append([bk(u, v), bk(u, v + 1), bk(u + 1, v + 1), bk(u + 1, v)])
            kinds.append(("back", u, v))
        faces.append([f(u + 1, 0), f(u, 0), bk(u, 0), bk(u + 1, 0)])
        kinds.append(("v0", u))
        faces.append([f(u, V - 1), f(u + 1, V - 1), bk(u + 1, V - 1), bk(u, V - 1)])
        kinds.append(("v1", u))
    for v in range(V - 1):
        faces.append([f(0, v), f(0, v + 1), bk(0, v + 1), bk(0, v)])
        kinds.append(("u0", v))
        faces.append([f(U - 1, v + 1), f(U - 1, v), bk(U - 1, v), bk(U - 1, v + 1)])
        kinds.append(("u1", v))
    return faces, kinds


def oriented(m: mk.Mesh) -> mk.Mesh:
    """``m`` flipped when its signed volume is negative."""
    tris, _ = m.triangles()
    Vx = m.vertices
    a, b, c = Vx[tris[:, 0]], Vx[tris[:, 1]], Vx[tris[:, 2]]
    cr = np.cross(b, c)
    vol = float(np.sum(a[:, 0] * cr[:, 0] + a[:, 1] * cr[:, 1] + a[:, 2] * cr[:, 2]))
    return m.flipped() if vol < 0 else m


def slab(front, back, groups=(1, 1, 1, 1, 1, 1)) -> mk.Mesh:
    """Closed slab between two ``(U, V, 3)`` vertex grids: ``groups = (front, back, v0, v1, u0, u1)``, each an int, a
    ``(U-1, V-1)`` table (front / back) or one int per rim face.  Oriented outward by its signed volume."""
    F = np.asarray(front, dtype=np.float64)
    Bk = np.asarray(back, dtype=np.float64)
    U, V = F.shape[0], F.shape[1]
    faces, kinds = slab_faces(U, V)
    g = dict(zip(("front", "back", "v0", "v1", "u0", "u1"), groups))
    fg = []
    for k in kinds:
        val = g[k[0]]
        if np.ndim(val) == 0:
            fg.append(int(val))
        elif np.ndim(val) == 2:
            fg.append(int(val[k[1]][k[2]]))
        else:
            fg.append(int(val[k[1]]))
    return oriented(mk.Mesh(np.concatenate([F.reshape(-1, 3), Bk.reshape(-1, 3)]), faces, fg))


class DecalStack:
    """Front surfaces of the decals placed so far (plus the skin), for :func:`_decal`'s clearance pass."""

    def __init__(self, rig: Rig):
        self.skin = skin_surface(rig)
        self.clear_skin = rig.decal_skin_clearance
        self.step = rig.decal_layer_step
        self.layers = []

    def add(self, F):
        U, V = F.shape[:2]
        faces = [[u * V + v, (u + 1) * V + v, (u + 1) * V + v + 1, u * V + v + 1]
                 for u in range(U - 1) for v in range(V - 1)]
        m = mk.Mesh(F.reshape(-1, 3), faces, 1)
        self.layers.append(SkinSurface(m, front_only=False))

    def required_front_y(self, x: float, z: float) -> float:
        req = self.skin.y(x, z) - self.clear_skin
        for s in self.layers:
            y = s.y(x, z)
            if y is not None:
                req = min(req, y - self.step)
        return req

    def top_y(self, x: float, z: float) -> float:
        """y of the front-most surface (skin or a placed decal) at ``(x, z)``."""
        top = self.skin.y(x, z)
        for s in self.layers:
            y = s.y(x, z)
            if y is not None:
                top = min(top, y)
        return top


def _samples(G):
    """Sample points of a ``(U, V, 2)`` grid with the vertices they depend on: vertices, edge midpoints and the
    midpoints of both quad diagonals."""
    U, V = G.shape[:2]
    out = [(G[i, j], ((i, j),)) for i in range(U) for j in range(V)]
    for i in range(U):
        for j in range(V):
            for a, b in (((i, j), (i + 1, j)), ((i, j), (i, j + 1)), ((i, j), (i + 1, j + 1)),
                         ((i + 1, j), (i, j + 1))):
                if a[0] < U and b[0] < U and b[1] < V and a[1] < V:
                    out.append((0.5 * (G[a] + G[b]), (a, b)))
    return out


def _clear(F, N, G, required, sign: float, rounds: int = 8, columns: bool = False):
    """Move vertices of ``F`` along y (their ``(x, z)`` stay on the face points, so the requirements are evaluated
    where the vertices are and a band never folds over itself where the face turns sideways) until every sample's
    (chord) y is on the right side of ``required(x, z)``: ``sign = +1`` keeps ``y <= required`` (in front), ``-1``
    keeps ``y >= required``.  A two-row grid (a band), or any grid with ``columns``, moves whole columns, so its narrow
    quads never twist.  ``N`` is unused (kept for the call shape)."""
    V = F.shape[1]
    samples = []
    for xz, idx in _samples(G):
        moved_idx = idx
        if V == 2 or columns:
            moved_idx = tuple(sorted({(i, j) for i, _ in idx for j in range(V)}))
        samples.append((idx, moved_idx, required(float(xz[0]), float(xz[1]))))
    for _ in range(rounds):
        moved = False
        for idx, moved_idx, req in samples:
            y = sum(F[k][1] for k in idx) / len(idx)
            d = sign * (y - req)
            if d > 1e-8:
                for k in moved_idx:
                    F[k][1] -= sign * (d + 2e-6)
                moved = True
        if not moved:
            return


def _decal(rig: Rig, grid_xz, relief, stack: DecalStack, depth: float | None = None,
           shrink=("centroid", 0.5), add: bool = True) -> mk.Mesh:
    """Face decal slab from ``(U, V, 2)`` face points ``(x, z)``: the front ``relief`` (per column or a scalar) above
    the smooth face and clear of the skin and of the decals already in ``stack``, the back ``depth`` behind the
    front-most surface under it.  One smooth group; the walls are undercut (the back outline is the front one moved
    ``rig.decal_undercut`` towards the centroid, ``("centroid", k)``, or scaled towards each column's middle,
    ``("across", k)``), so the front rim is a silhouette from the whole front half space."""
    depth = rig.eye_slab_depth if depth is None else depth
    G = np.asarray(grid_xz, dtype=np.float64)
    U, V = G.shape[:2]
    rel = np.broadcast_to(np.asarray(relief, dtype=np.float64), (U,))
    surf = skin_surface(rig)
    F = np.zeros((U, V, 3))
    N = np.zeros((U, V, 3))
    for i in range(U):
        for j in range(V):
            p, n = smooth_face(rig, float(G[i, j, 0]), float(G[i, j, 1]))
            F[i, j] = p - np.array([0.0, rel[i] / max(0.3, -n[1]), 0.0])
            N[i, j] = n
    _clear(F, N, G, stack.required_front_y, +1.0)
    mode, k = shrink
    if mode == "centroid":
        c = G.reshape(-1, 2).mean(axis=0)
        d = G - c
        r = np.sqrt(d[..., 0] * d[..., 0] + d[..., 1] * d[..., 1])[..., None]
        kk = np.maximum(k, 1.0 - rig.decal_undercut / np.maximum(r, 1e-9))
        GB = c + kk * d
    else:
        mid = G.mean(axis=1, keepdims=True)
        e = G[:, -1] - G[:, 0]
        half = 0.5 * np.sqrt(e[:, 0] * e[:, 0] + e[:, 1] * e[:, 1])
        kk = np.maximum(k, np.minimum(1.0, 0.0001 / np.maximum(half, 1e-9)))
        GB = mid + kk[:, None, None] * (G - mid)
    B = np.zeros((U, V, 3))
    NB = np.zeros((U, V, 3))
    for i in range(U):
        for j in range(V):
            x, z = float(GB[i, j, 0]), float(GB[i, j, 1])
            p, n = surf.hit(x, z)
            B[i, j] = (x, stack.top_y(x, z) + depth / max(0.3, -n[1]), z)
            NB[i, j] = n
    _clear(B, NB, GB, lambda x, z: stack.top_y(x, z) + depth, -1.0)
    if add:
        stack.add(F)
    return slab(F, B, (1, 1, 1, 1, 1, 1))


#: The ridge of a ridge decal / the apex of a dome decal stands this far over its borders: the top faces slope some
#: degrees, so both borders stay camera silhouettes from nearly the whole front half space while the bottom faces look
#: into the face (the band's outline draws from every usual view; a slab's undercut wall cannot lean enough on a band
#: 1-2 mm wide).
RIDGE_RISE = 0.0005


def _front_points(rig: Rig, G, relief):
    """Points ``(U, V, 3)`` and unit normals of the face points ``G`` ``(U, V, 2)`` on the smooth face, moved out by
    ``relief`` ``(U, V)`` along the normal."""
    U, V = G.shape[:2]
    F = np.zeros((U, V, 3))
    N = np.zeros((U, V, 3))
    for i in range(U):
        for j in range(V):
            p, n = smooth_face(rig, float(G[i, j, 0]), float(G[i, j, 1]))
            F[i, j] = p - np.array([0.0, relief[i, j] / max(0.3, -n[1]), 0.0])     # the relief along the normal,
            N[i, j] = n                                                             # moved along y
    return F, N


def _ridge_decal(rig: Rig, side_a, side_b, relief, stack: DecalStack, add: bool = False,
                 columns: bool = False) -> mk.Mesh:
    """Thin mark between the two border polylines ``side_a`` / ``side_b`` ``(U, 2)`` (face points): a triangular
    section whose borders stand ``relief`` (per station or a scalar) over the face, clear of the skin and of the
    decals in ``stack`` (``rig.decal_layer_step``), and whose ridge midway rises :data:`RIDGE_RISE` more; the bottom
    face (the chord from border to border) looks into the face.  One smooth group: both borders draw as silhouettes
    and cost no construction ray.  The ends are triangles.  With ``columns`` the clearance pass moves each station's
    section as a whole (a band lifted over a layer under part of it, as the lash band over the pupil, never folds)."""
    A = np.asarray(side_a, dtype=np.float64)
    B = np.asarray(side_b, dtype=np.float64)
    U = len(A)
    rel = np.broadcast_to(np.asarray(relief, dtype=np.float64), (U,))
    G = np.stack([A, 0.5 * (A + B), B], axis=1)
    R = np.stack([rel, rel + RIDGE_RISE, rel], axis=1)
    F, N = _front_points(rig, G, R)
    _clear(F, N, G, stack.required_front_y, +1.0, columns=columns)
    Pa, Pb = F[:, 0], F[:, 2]
    # the ridge stays RIDGE_RISE over the chord between the (cleared) borders, so the section never inverts
    mid = 0.5 * (Pa + Pb)
    Pr = mid.copy()
    Pr[:, 1] = np.minimum(F[:, 1, 1], mid[:, 1] - RIDGE_RISE)
    V = np.concatenate([Pa, Pr, Pb])
    faces, top = [], []
    for j in range(U - 1):
        k = j + 1
        faces += [[j, k, U + k, U + j], [U + j, U + k, 2 * U + k, 2 * U + j], [2 * U + j, 2 * U + k, k, j]]
        top += [True, True, False]
    faces += [[0, U, 2 * U], [U - 1, 3 * U - 1, 2 * U - 1]]
    top += [False, False]
    # orient outward by the signed volume (a narrow stroke's top faces slope steeply, so the first top face's normal
    # is no reliable guide), then fold the top quads outward and the bottom quads inward (meshkit.fan_fold): a thin
    # band's fan diagonals must not cross through each other
    if _signed_volume(V, faces) < 0.0:
        faces = [[f[0]] + f[1:][::-1] for f in faces]
    if add:
        stack.add(F)
    return mk.fan_fold(mk.Mesh(V, faces, 1), top)


def _signed_volume(V, faces) -> float:
    """Six times the signed volume of the closed polygon mesh ``(V, faces)`` (each face fanned from its first vertex;
    explicit sums, no BLAS kernel)."""
    vol = 0.0
    for f in faces:
        a = V[f[0]]
        for j in range(1, len(f) - 1):
            b, c = V[f[j]], V[f[j + 1]]
            vol += _dot3(a, np.cross(b, c))
    return vol


def _dome_decal(rig: Rig, ring_xz, relief: float, stack: DecalStack, depth: float, add: bool = False) -> mk.Mesh:
    """Small round mark (a highlight): the border ring ``(n, 2)`` stands ``relief`` over the face and clear of the
    decals in ``stack``, a top apex over its centre :data:`RIDGE_RISE` higher, a bottom apex ``depth`` behind the
    front-most surface under the centre: a flat double cone whose border is a silhouette from every front view."""
    P = np.asarray(ring_xz, dtype=np.float64)
    n = len(P)
    c = P.mean(axis=0)
    G = np.concatenate([P, c[None]])[:, None, :]
    R = np.full((n + 1, 1), float(relief))
    R[-1, 0] += RIDGE_RISE
    F, N = _front_points(rig, G, R)
    _clear(F, N, G, stack.required_front_y, +1.0)
    top = F[-1, 0]
    ring = F[:n, 0]
    _p, nn = skin_surface(rig).hit(float(c[0]), float(c[1]))
    bottom = np.array([c[0], stack.top_y(float(c[0]), float(c[1])) + depth / max(0.3, -nn[1]), c[1]])
    V = np.concatenate([ring, top[None], bottom[None]])
    faces = []
    for j in range(n):
        k = (j + 1) % n
        faces.append([n, j, k])
        faces.append([n + 1, k, j])
    if add:
        stack.add(F)
    return oriented(mk.Mesh(V, faces, 1))


def _smooth_curve(points, x):
    """Smooth curve (cubic Hermite with finite-difference tangents) through ``points`` ``[(x, z)]`` (x ascending),
    evaluated at ``x``; clamped linear outside."""
    P = np.asarray(points, dtype=np.float64)
    xs, zs = P[:, 0], P[:, 1]
    m = np.zeros_like(zs)
    m[1:-1] = (zs[2:] - zs[:-2]) / (xs[2:] - xs[:-2])
    m[0] = (zs[1] - zs[0]) / (xs[1] - xs[0])
    m[-1] = (zs[-1] - zs[-2]) / (xs[-1] - xs[-2])
    x = np.atleast_1d(np.asarray(x, dtype=np.float64))
    out = np.zeros_like(x)
    for k, xv in enumerate(x):
        i = int(np.clip(np.searchsorted(xs, xv) - 1, 0, len(xs) - 2))
        h = xs[i + 1] - xs[i]
        t = (xv - xs[i]) / h
        if t < 0.0 or t > 1.0:                         # outside: the end tangent
            out[k] = zs[i] + m[i] * (xv - xs[i]) if t < 0.0 else zs[i + 1] + m[i + 1] * (xv - xs[i + 1])
            continue
        h00, h10 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t
        h01, h11 = -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
        out[k] = h00 * zs[i] + h10 * h * m[i] + h01 * zs[i + 1] + h11 * h * m[i + 1]
    return out


def column_grid(lo, hi, rows: int) -> np.ndarray:
    """``(U, rows, 2)`` face points ``(x, z)``: column ``i`` runs from ``lo[i]`` to ``hi[i]``."""
    lo, hi = np.asarray(lo, dtype=np.float64), np.asarray(hi, dtype=np.float64)
    t = np.linspace(0.0, 1.0, rows)
    return lo[:, None, :] + t[None, :, None] * (hi - lo)[:, None, :]


def band_grid(centre, half_width) -> np.ndarray:
    """``(U, 2, 2)`` face points of a band round the polyline ``centre`` ``(U, 2)`` with mitred perpendicular offsets
    of ``half_width`` ``(U,)``."""
    P = np.asarray(centre, dtype=np.float64)
    w = np.broadcast_to(np.asarray(half_width, dtype=np.float64), (len(P),))
    d = np.diff(P, axis=0)
    d /= np.sqrt(d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1])[:, None]
    nseg = np.stack([d[:, 1], -d[:, 0]], axis=1)
    n = np.zeros_like(P)
    n[0], n[-1] = nseg[0], nseg[-1]
    for i in range(1, len(P) - 1):
        m = nseg[i - 1] + nseg[i]
        m /= math.sqrt(float(m[0] * m[0] + m[1] * m[1]))
        n[i] = m / max(0.3, float(m[0] * nseg[i][0] + m[1] * nseg[i][1]))
    return np.stack([P + w[:, None] * n, P - w[:, None] * n], axis=1)


def _ellipse_columns(cx, cz, a, b, n, lo_clip=None, hi_clip=None, eps=0.10):
    """Columns of an ellipse (centre ``(cx, cz)``, semi-axes ``a``, ``b``) at equal parameter angle, clipped to
    ``lo_clip(x) <= z <= hi_clip(x)``; returns ``(lo (n, 2), hi (n, 2))``."""
    th = np.linspace(math.pi - eps, eps, n)
    x = cx + a * np.cos(th)
    h = b * np.sin(th)
    zl, zh = cz - h, cz + h
    if lo_clip is not None:
        zl = np.maximum(zl, lo_clip(x))
    if hi_clip is not None:
        zh = np.minimum(zh, hi_clip(x))
    if np.any(zh - zl < 2e-4):
        raise mk.MeshError("ellipse columns clipped away")
    return np.stack([x, zl], axis=1), np.stack([x, zh], axis=1)


# ---------------------------------------------------------------------------------------------------------------------
# eyes (§B.2)
# ---------------------------------------------------------------------------------------------------------------------
#: Columns / rows of the eye decal grids (tessellation).
SCLERA_COLS, SCLERA_ROWS = 8, 2
IRIS_COLS = 10
PUPIL_COLS = 7
HIGHLIGHT_COLS = (10, 8)           # border points per rig.highlights entry (the default rig has one, the large
#                                    highlight; a --rig override may add a second, smaller one)
#: Layer back faces reach this far behind the front-most surface under them (sclera: rig.eye_slab_depth); each stacked
#: layer a little deeper, so the back faces never share a vertex (castplane welds coincident vertices of an object).
STACK_DEPTH = 0.0003
LAYER_DEPTH_STEP = 0.00006
#: The iris stays this far inside the lower sclera boundary and this far under the lash band's top.
IRIS_LOW_MARGIN = 0.0004
IRIS_TOP_MARGIN = 0.0008


def _lid_z(rig: Rig, x):
    """The upper lid line (the sclera's top, the lash band's lower edge) at ``|x|``."""
    return _smooth_curve(rig.eye_lid_line, np.abs(np.asarray(x, dtype=np.float64)))


def _sclera_lo(rig: Rig, x):
    return _smooth_curve(rig.sclera_lower, np.abs(np.asarray(x, dtype=np.float64)))


def _lash_lower(rig: Rig, x):
    """Lower edge of the lash band at ``|x|``: from ``lash_inner`` along the lid line to ``lash_outer``."""
    (x0, z0), (x1, z1) = rig.lash_inner, rig.lash_outer
    pts = [(x0, z0)] + [p for p in rig.eye_lid_line if x0 < p[0] < x1] + [(x1, z1)]
    return _smooth_curve(pts, np.abs(np.asarray(x, dtype=np.float64)))


def _lash_height(rig: Rig, x):
    """Height of the lash band at ``|x|``: a smooth curve through ``lash_height`` (the inner end, the lid line's
    middle point, the outer end) and ``lash_height_quarters`` (the lid line's second and fourth points), so the band's
    top is an arc, not a roof peaked at the middle."""
    (x0, _), (x1, _) = rig.lash_inner, rig.lash_outer
    h0, hm, h1 = rig.lash_height
    q0, q1 = rig.lash_height_quarters
    lid = rig.eye_lid_line
    pts = [(x0, h0), (lid[1][0], q0), (lid[2][0], hm), (lid[3][0], q1), (x1, h1)]
    return _smooth_curve(pts, np.abs(np.asarray(x, dtype=np.float64)))


def _lash_top(rig: Rig, x):
    return _lash_lower(rig, x) + _lash_height(rig, x)


def _eye_parts(rig: Rig, side: int, stack: DecalStack):
    s = _side_name(side)
    colour = "blue" if side > 0 else "red"            # heterochromia: her left (+x) blue, her right (-x) red
    cx = side * rig.eye_x
    xi, xo = rig.eye_inner_x, rig.eye_outer_x
    xs = np.linspace(xi, xo, SCLERA_COLS)
    lo = np.stack([side * xs, _sclera_lo(rig, xs)], axis=1)
    # the sclera's top tucks under the lash band where the band covers it (its corners stay on the lid line)
    (lx0, _), (lx1, _) = rig.lash_inner, rig.lash_outer
    cover = np.clip(np.minimum(xs - lx0, lx1 - xs) / 0.003, 0.0, 1.0) * (0.5 * _lash_height(rig, xs))
    hi = np.stack([side * xs, _lid_z(rig, xs) + cover], axis=1)
    sclera = _decal(rig, column_grid(lo, hi, SCLERA_ROWS), rig.sclera_relief, stack)
    iw, ih = rig.iris_size
    lo_i, hi_i = _ellipse_columns(cx, rig.iris_center_z, 0.5 * iw, 0.5 * ih, IRIS_COLS,
                                  lo_clip=lambda x: _sclera_lo(rig, x) + IRIS_LOW_MARGIN,
                                  hi_clip=lambda x: _lash_top(rig, x) - IRIS_TOP_MARGIN)
    iris = _decal(rig, column_grid(lo_i, hi_i, 2), rig.iris_relief, stack, STACK_DEPTH)
    pw, ph = rig.pupil_size
    lo_p, hi_p = _ellipse_columns(cx, rig.pupil_center_z, 0.5 * pw, 0.5 * ph, PUPIL_COLS)
    pupil = _decal(rig, column_grid(lo_p, hi_p, 2), rig.pupil_relief, stack, STACK_DEPTH + LAYER_DEPTH_STEP)
    obj = f"eye_{s}"                                  # one compact object per eye (SPEC.md §G)
    parts = [Part(f"head.sclera_{s}", "eye_white", sclera, "eyes", obj=obj),
             Part(f"head.iris_{s}", f"iris_{colour}", iris, "eyes", obj=obj),
             Part(f"head.pupil_{s}", f"pupil_{colour}", pupil, "eyes", obj=obj)]
    for k, ((dx, hz, dia), cols) in enumerate(zip(rig.highlights, HIGHLIGHT_COLS)):
        r = 0.5 * dia
        # the same side on both eyes (light from the upper left): dx is not mirrored
        a = np.linspace(0.0, 2.0 * math.pi, cols, endpoint=False)
        ring = np.stack([cx + dx + r * np.cos(a), hz + r * np.sin(a)], axis=1)
        hl = _dome_decal(rig, ring, rig.highlight_relief, stack, STACK_DEPTH + (2 + k) * LAYER_DEPTH_STEP)
        parts.append(Part(f"head.highlight{k + 1}_{s}", "eye_white", hl, "eyes", obj=obj))
    return parts


# ---------------------------------------------------------------------------------------------------------------------
# face marks (§B.2 lash bands, §B.3 brows, §B.4 mouth and blush)
# ---------------------------------------------------------------------------------------------------------------------
LASH_COLS = 7                      # main band columns (the flick adds LASH_FLICK_COLS)
LASH_FLICK_COLS = 2
BROW_COLS = 4
MOUTH_COLS = 7
#: The lash band and the brows thin to this relief over their outer RELIEF_TAPER_FRACTION (where the face turns away),
#: so they do not jut out of the face's outline in 3/4 and profile views (0.40 mm on the final model).
RELIEF_TAPER_END = 0.00041
RELIEF_TAPER_FRACTION = 0.3


def _tapered_relief(xs, relief: float, fraction: float = RELIEF_TAPER_FRACTION,
                    end: float = RELIEF_TAPER_END) -> np.ndarray:
    """Per-column relief along ``xs`` (inner end first): ``relief`` up to the last ``fraction``, then down to
    ``end``."""
    xs = np.abs(np.asarray(xs, dtype=np.float64))
    s = (xs - xs[0]) / (xs[-1] - xs[0])
    t = np.clip((s - (1.0 - fraction)) / fraction, 0.0, 1.0)
    return relief + t * (min(relief, end) - relief)


def _lash_band(rig: Rig, side: int, stack: DecalStack) -> mk.Mesh:
    """Upper lash band (a ridge decal): its lower border runs from ``lash_inner`` along the lid line to
    ``lash_outer``, its upper border ``lash_height`` higher; then the flick runs on from the band's outer end down and
    out to ``lash_flick_tip``, ``lash_flick_width`` tall and tapering to a blunt point.  Over the sclera and the iris it
    stands ``rig.decal_layer_step`` over them (the stack); its relief tapers at both ends (:data:`LASH_INNER_RELIEF`
    over the inner :data:`LASH_INNER_TAPER` of its length, where the flat face is level with the bridge, and
    :data:`RELIEF_TAPER_END` over the outer :data:`RELIEF_TAPER_FRACTION`, where the face turns away)."""
    (x0, _), (x1, z1) = rig.lash_inner, rig.lash_outer
    xs = np.linspace(x0, x1, LASH_COLS)
    lo = _lash_lower(rig, xs)
    hi = lo + _lash_height(rig, xs)
    tx, tz = rig.lash_flick_tip
    w = rig.lash_flick_width
    fx = np.linspace(x1, tx, LASH_FLICK_COLS + 2)[1:]
    t = (fx - x1) / (tx - x1)
    centre = (z1 + 0.5 * w) + t * (tz - (z1 + 0.5 * w))
    half = 0.5 * w * (1.0 - t) + FLICK_TIP_HALF * t
    X = np.concatenate([xs, fx])
    LO = np.concatenate([lo, centre - half])
    HI = np.concatenate([hi, centre + half])
    rel = _tapered_relief(X, rig.lash_relief)
    s = (X - X[0]) / (X[-1] - X[0])
    k = np.clip(s / LASH_INNER_TAPER, 0.0, 1.0)
    rel = LASH_INNER_RELIEF + k * (rel - LASH_INNER_RELIEF)
    return _ridge_decal(rig, np.stack([side * X, LO], axis=1), np.stack([side * X, HI], axis=1), rel, stack,
                        columns=True)


#: Half height of the flick at its tip (a blunt 0.3 mm point: no sliver faces).
FLICK_TIP_HALF = 0.00015
#: The lash band's relief at its inner end (on the skin beside the sclera's inner corner) and the fraction of its
#: length over which it rises to ``rig.lash_relief``: the flat face is level with the nose bridge there, so a full
#: relief would jut out of the profile.
LASH_INNER_RELIEF = 0.0006
LASH_INNER_TAPER = 0.2


def _brow(rig: Rig, side: int, stack: DecalStack) -> mk.Mesh:
    pts = np.array([rig.brow_inner, rig.brow_mid, rig.brow_outer])
    xs = np.linspace(pts[0, 0], pts[-1, 0], BROW_COLS)
    zs = _smooth_curve(pts, xs)
    t = (xs - xs[0]) / (xs[-1] - xs[0])
    w0, w1 = rig.brow_width
    half = 0.5 * (w0 + (w1 - w0) * t)
    half[0] *= 0.75                                   # slightly rounded stroke ends
    half[-1] *= 0.6
    g = band_grid(np.stack([xs, zs], axis=1), half)
    g[..., 0] *= side
    return _ridge_decal(rig, g[:, 0], g[:, 1], _tapered_relief(xs, rig.brow_relief), stack)


def _mouth(rig: Rig, stack: DecalStack) -> mk.Mesh:
    """The closed smile: a U from the corners to the middle (a cosine sag), vertical columns ``mouth_band`` tall."""
    cx, cz = rig.mouth_corners
    xs = np.linspace(-cx, cx, MOUTH_COLS)
    u = np.abs(xs) / cx
    zc = rig.mouth_bottom_z + (cz - rig.mouth_bottom_z) * (1.0 - np.cos(0.5 * np.pi * u))
    half = np.full(len(xs), 0.5 * rig.mouth_band)
    half[0] *= 0.6
    half[-1] *= 0.6
    return _ridge_decal(rig, np.stack([xs, zc - half], axis=1), np.stack([xs, zc + half], axis=1), rig.mouth_relief,
                        stack)


def _blush(rig: Rig, side: int, stack: DecalStack):
    """``blush_count`` short hatch strokes round the cheek centre, ``blush_spacing`` apart along x, each tilted
    ``blush_tilt_deg`` from horizontal (the top towards +x on both cheeks, as drawn)."""
    L, W = rig.blush_stroke
    a = math.radians(rig.blush_tilt_deg)
    d = np.array([math.cos(a), math.sin(a)])          # along the stroke (up, leaning to +x)
    nrm = np.array([-d[1], d[0]])
    cx, cz = rig.blush_center
    out = []
    n = rig.blush_count
    for k in range(n):
        c = np.array([side * cx + (k - 0.5 * (n - 1)) * rig.blush_spacing, cz])
        P = np.array([c - 0.5 * L * d, c + 0.5 * L * d])
        out.append(_ridge_decal(rig, P - 0.5 * W * nrm, P + 0.5 * W * nrm, rig.blush_relief, stack))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------------------------------------------------

def build(rig: Rig):
    """The parts of :data:`REGIONS`: the skin head, per eye the sclera / iris / pupil / highlights, and the face
    marks (lash bands, brows, mouth, blush strokes)."""
    skin = mk.split_twisted(skin_surface(rig).mesh, SKIN_TWIST_SPLIT_DEG)
    parts = [Part("head.skin", "skin", skin, "head")]
    marks = []
    for side in SIDES:
        s = _side_name(side)
        stack = DecalStack(rig)                       # the eye layers of this side, in order (then the lash band)
        parts += _eye_parts(rig, side, stack)
        obj = f"face_marks_{s}"                       # one compact object per side; the mouth joins her left
        marks.append(Part(f"head.lash_{s}", "lashes", _lash_band(rig, side, stack), "face_marks", obj=obj))
        skin_only = DecalStack(rig)
        marks.append(Part(f"head.brow_{s}", "face_marks", _brow(rig, side, skin_only), "face_marks", obj=obj))
        for k, m in enumerate(_blush(rig, side, skin_only)):
            marks.append(Part(f"head.blush{k + 1}_{s}", "face_marks", m, "face_marks", obj=obj))
    marks.append(Part("head.mouth", "face_marks", _mouth(rig, DecalStack(rig)), "face_marks", obj="face_marks_l"))
    return parts + marks
