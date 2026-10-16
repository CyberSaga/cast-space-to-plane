"""Head, face, eyes, eyebrows and mouth of the Miki model (owner: head agent).

Part contract (see ``assemble.py`` and the toolkit guide): :func:`build` takes the
:class:`~miki_model.rig.Rig` and returns a list of :class:`~miki_model.meshkit.Part` covering **all** of
:data:`REGIONS` (each part's ``region`` names one of them, so ``--only`` can filter).
Objects / materials (``Part(name, material, mesh, region, obj=...)``, see ``assemble.OBJECTS``): head + face ->
head (skin; no ears); sclera, highlight -> eyes (eye_white), iris -> eyes (iris), pupil -> eyes (pupil); brows,
lid bands, lower-lid marks, mouth -> face_marks (face_marks).

How it is built (spec ``miki_spec.md`` §B):

* **Skin head** (§B.1): one closed loft of horizontal sections from the skull top to the chin.  Each section
  is the spec's asymmetric section (front half ``|x/hw|^3 + |(y-c)/(c-yf)|^3 = 1``, back half an ellipse);
  the ring points are spaced by arc length with most of them on the face (the back of the skull is under the
  hair).  Below the nape row the back of a section is the jaw underside, so the head's underside is closed
  and the neck (``body.py``) sinks into it.  The profile table's nose row (a ridge across the face) is
  replaced by its neighbours' mean and the nose is a local bump of the mid columns (§B.4).  The whole head is
  one smooth group: no line is drawn on the face, only silhouettes.
* **Face features** are thin decal slabs conforming to the actual (faceted) head mesh: each point of a
  feature outline is ray-cast onto the head mesh and moved along the smoothed mesh normal, the back face
  ``eye_slab_depth`` under the skin, the front face the layer's relief above it (§B.2 layer stack).  The front
  face is one smooth group and the walls + back another, so the outline (the front rim) is a feature line
  in every view, while the buried back rim never draws.

The helpers :func:`skin_surface` / :func:`face_point` are also used by ``hair.py`` (bangs on the forehead).
"""

from __future__ import annotations

import functools
import math

import numpy as np

from . import meshkit as mk
from .meshkit import Part
from .rig import SUN_TOWARDS, Rig

__all__ = ["REGIONS", "build", "skin_surface", "face_point", "slab", "column_grid", "band_grid",
           "head_section", "HEAD_ROWS", "SUN", "slab_faces", "oriented"]

#: The mannequin regions this module replaces.
REGIONS = ("head", "eyes", "face_marks")

SIDES = (1, -1)                    # her left (+X), her right (-X)

# ---------------------------------------------------------------------------------------------------------
# Tessellation of the skin head (module constants: they choose the mesh, not the shape, so they are not rig
# fields).  Rows are the section heights between the skull-top pole and the chin pole; they are dense on
# the face (silhouette in every view, decals follow the facets) and sparse on the hair-covered skull.
# ---------------------------------------------------------------------------------------------------------
#: Round 2 (F1): the full rings (face + skull back) end at 1.296; below it the :data:`JAW_RINGS` turn the
#: face into the jaw underside and the nape into the neck.
HEAD_ROWS = (1.445, 1.400, 1.380, 1.360, 1.342, 1.333, 1.325, 1.312, 1.304, 1.296)
#: Arc-length fractions of the ring points on the front half-section, from the midline (0) to the side (1).
#: 0.738 splits the jaw-corner column: without it the jaw outline folds behind the cheek facet above the
#: jaw underside and shows a gap in front views from eye height.
FRONT_FRACTIONS = (0.0, 0.025, 0.165, 0.266, 0.349, 0.426, 0.502, 0.584, 0.679, 0.738, 0.797, 0.90, 1.0)
#: Angles (degrees from her left side, through the back) of the ring points on the back half-section.
BACK_ANGLES = (20.0, 90.0, 160.0)
#: Nose bump (§B.4): row -> displacement (forward, m) of the midline column; the neighbouring columns
#: (fraction 0.05, about 6 mm off the midline at the nose) move ``NOSE_SIDE`` times as much.
#: Round 2 (F4): a clear nose point (was 0.0032 / 0.0065 / 0.0018), 6 mm ahead of the brow.
NOSE_BUMP = {1.325: 0.0045, 1.312: 0.0095, 1.304: 0.003}
NOSE_SIDE = 0.10
#: Round 2 (F1 / F2): the lower head.  Every ring below :data:`HEAD_ROWS` is the face's front half-section
#: at ``zf`` (hw / yf from the profile) ending at the jaw rim point ``(hw, c, zf)`` on each side, then its
#: back points: P20 / P160 on the head-neck junction (just inside the neck, ``JUNCTION_INSET``) at the neck
#: angle ``phi`` (degrees from her left side, -90 = the throat, +90 = the nape), and the midline back point
#: P90: on the nape ``(y, z)`` while that is outside the neck, else (None) inside the neck, moving from the
#: back junction up to the throat so the chin pole's fan rises from the chin into the neck.  The jaw rim
#: (``c`` by ``zf``) rises ~28 degrees from the chin toward the ear; the underside between the rim and the
#: neck slopes up into the throat at the front and down into the neck side under the ear; the nape runs
#: down outside the neck to the junction, so no shelf sticks out of the neck.
JAW_RINGS = (
    # zf      c        phi    P20 z   nape (y, z) or None
    (1.286, -0.008, 10.0, 1.268, (0.066, 1.276)),
    (1.279, -0.020, 0.0, 1.265, (0.054, 1.266)),
    (1.272, -0.033, -18.0, 1.265, (0.044, 1.257)),
    (1.2665, -0.041, -36.0, 1.268, None),
    (1.262, -0.049, -52.0, 1.2725, None),
    (1.2595, -0.054, -62.0, 1.2748, None),
    (1.2575, -0.058, -70.0, 1.2759, None),
)
#: P20 lies at the given z on the neck, JUNCTION_INSET inside its surface: about level (1.265) where the
#: rim descends from the jaw angle (so the strips from the rim into the neck do not twist), then rising to
#: the throat.  The inside-the-neck midline points start at JAW_INSIDE_START_Z.
JUNCTION_INSET = 0.003
JAW_INSIDE_START_Z = 1.256
#: The midline back point of the last jaw ring lies inside the neck, JAW_THROAT_DEPTH of the inset neck
#: half-depth behind the neck's centre line towards the throat, JAW_FAN_SAG under the plane through the chin
#: pole and that ring's P20 / P160 (the chin pole's fan is then a flat, slightly convex underside, no keel
#: at the midline); the inside-the-neck midline points of the rings before it run straight from the back
#: junction to it.
JAW_THROAT_DEPTH = 0.30
JAW_FAN_SAG = 0.0005
#: Chin pole (below the last ring), relative to the chin bottom landmark (y, z offsets).
CHIN_POLE_DY = 0.002


def _side_name(side: int) -> str:
    return "l" if side > 0 else "r"


# ---------------------------------------------------------------------------------------------------------
# skin head
# ---------------------------------------------------------------------------------------------------------

def _interp_rows(rows, z, col):
    zs = [r[0] for r in rows]
    if z >= zs[0]:
        return rows[0][col]
    if z <= zs[-1]:
        return rows[-1][col]
    for a, b in zip(rows, rows[1:]):
        if b[0] <= z <= a[0]:
            t = (a[0] - z) / (a[0] - b[0])
            return a[col] + t * (b[col] - a[col])
    raise ValueError(z)


def _base_profile(rig: Rig):
    """The §B.1 profile with the nose row's front replaced by its neighbours' mean (the nose is a bump)."""
    rows = list(rig.head_profile)
    nz = rig.nose_tip[2]
    for k, (z, hw, yf, yb) in enumerate(rows):
        if abs(z - nz) < 1e-9 and 0 < k < len(rows) - 1:
            rows[k] = (z, hw, 0.5 * (rows[k - 1][2] + rows[k + 1][2]), yb)
    return tuple(rows)


def _jaw_y(rig: Rig, z: float) -> float:
    ys, zs = zip(*rig.jaw_underside)
    return float(np.interp(z, zs, ys))


def head_section(rig: Rig, z: float):
    """``(hw, yf, yb, c)`` of the skin head section at ``z`` without the nose ridge; below the nape row the
    back ``yb`` is the jaw underside and ``c`` the middle of the section."""
    rows = _base_profile(rig)
    hw = _interp_rows(rows, z, 1)
    yf = _interp_rows(rows, z, 2)
    backs = [r for r in rows if r[3] is not None]
    if z >= backs[-1][0]:
        return hw, yf, _interp_rows(backs, z, 3), rig.face_offset(z)
    yb = _jaw_y(rig, z)
    return hw, yf, yb, 0.5 * (yf + yb)


def _front_angles(rig: Rig) -> np.ndarray:
    """Superellipse parameter angles (from the midline, pi/2, to the side, 0) of the front ring points: the
    :data:`FRONT_FRACTIONS` of arc length on the section at the eye line.  Every ring uses the same angles,
    so the points of consecutive rings correspond (no twisted quads where the section changes shape)."""
    hw, yf, _yb, c = head_section(rig, rig.eye_z)
    e = rig.face_front_exponent
    t = np.linspace(0.5 * np.pi, 0.0, 2000)
    x = hw * np.cos(t) ** (2.0 / e)
    y = c - (c - yf) * np.sin(t) ** (2.0 / e)
    s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    return np.interp(np.asarray(FRONT_FRACTIONS) * s[-1], s, t)


def _front_quadrant(hw, yf, c, e, angles):
    """Points ``(x >= 0, y)`` of the front superellipse quadrant at the parameter ``angles``."""
    t = np.asarray(angles, dtype=np.float64)
    return hw * np.cos(t) ** (2.0 / e), c - (c - yf) * np.sin(t) ** (2.0 / e)


def _junction_point(rig: Rig, phi_deg: float, z: float, depth: float = 1.0) -> np.ndarray:
    """Point at height ``z`` and neck angle ``phi_deg`` (her left side 0, throat -90, nape +90),
    ``JUNCTION_INSET`` inside the neck (``depth < 1``: further in, a fraction of the inset ellipse)."""
    from .body import _neck_section                          # the neck is body.py's (object neck)
    p = math.radians(phi_deg)
    a, cy, b = _neck_section(rig, z)
    return np.array([depth * (a - JUNCTION_INSET) * math.cos(p),
                     cy + depth * (b - JUNCTION_INSET) * math.sin(p), z])


def _chin_apex(rig: Rig) -> np.ndarray:
    chin = rig.head_profile[-1]
    return np.array([0.0, chin[2] + CHIN_POLE_DY, chin[0]])


def _jaw_back(rig: Rig, k: int):
    """``(P20, P90)`` (her left; P160 mirrors P20) of the ``k``-th :data:`JAW_RINGS` row."""
    from .body import _neck_section
    _zf, _c, phi, pz, nape = JAW_RINGS[k]
    p20 = _junction_point(rig, phi, pz)
    if nape is not None:
        return p20, np.array([0.0, nape[0], nape[1]])
    # the last ring's midline point: under the plane of the chin fan, inside the neck
    last = _junction_point(rig, JAW_RINGS[-1][2], JAW_RINGS[-1][3])
    apex = _chin_apex(rig)
    a, cy, b = _neck_section(rig, last[2])
    y_end = cy - JAW_THROAT_DEPTH * (b - JUNCTION_INSET)
    t = (y_end - apex[1]) / (last[1] - apex[1])
    end = np.array([0.0, y_end, apex[2] + t * (last[2] - apex[2]) - JAW_FAN_SAG])
    inside = [j for j, r in enumerate(JAW_RINGS) if r[4] is None]
    start = _junction_point(rig, 90.0, JAW_INSIDE_START_Z)
    u = inside.index(k) / max(1, len(inside) - 1)
    return p20, (1.0 - u) * start + u * end


def _ring_points(rig: Rig, hw, yf, c, z, back) -> np.ndarray:
    """Ring CCW seen from +Z starting at her left side point ``(hw, c)``: the side point, the three
    ``back`` points (left -> back -> right, ``(3, 3)``), the right side point, the front half-section."""
    fx, fy = _front_quadrant(hw, yf, c, rig.face_front_exponent, _front_angles(rig))
    pts = [(hw, c, z)]
    pts += [tuple(p) for p in back]
    pts.append((-hw, c, z))
    for k in range(len(FRONT_FRACTIONS) - 2, 0, -1):          # right front: side -> midline
        pts.append((-fx[k], fy[k], z))
    pts.append((0.0, fy[0], z))
    for k in range(1, len(FRONT_FRACTIONS) - 1):              # left front: midline -> side
        pts.append((fx[k], fy[k], z))
    return np.array(pts, dtype=np.float64)


def _jaw_ring(rig: Rig, k: int) -> np.ndarray:
    """The ``k``-th :data:`JAW_RINGS` ring (round 2, F1)."""
    zf, c = JAW_RINGS[k][:2]
    rows = _base_profile(rig)
    hw, yf = _interp_rows(rows, zf, 1), _interp_rows(rows, zf, 2)
    p20, p90 = _jaw_back(rig, k)
    p160 = p20 * np.array([-1.0, 1.0, 1.0])
    return _ring_points(rig, hw, yf, c, zf, [p20, p90, p160])


def _head_ring(rig: Rig, z: float) -> np.ndarray:
    """Ring at height ``z``: CCW seen from +Z, starting at her left side point."""
    hw, yf, yb, c = head_section(rig, z)
    back = [(hw * math.cos(a), c + (yb - c) * math.sin(a), z) for a in np.radians(BACK_ANGLES)]
    P = _ring_points(rig, hw, yf, c, z, back)
    pts = P
    # the nose bump (local, on the mid columns)
    d = NOSE_BUMP.get(round(z, 4), 0.0)
    if d:
        mid = len(pts) - len(FRONT_FRACTIONS) + 1             # index of the midline point
        P[mid, 1] -= d
        P[mid - 1, 1] -= NOSE_SIDE * d
        P[mid + 1, 1] -= NOSE_SIDE * d
    return P


def _head_mesh(rig: Rig) -> mk.Mesh:
    """The skin head: sections from :data:`HEAD_ROWS` [0] (under the bangs, inside the hair: the skull above
    it is never visible, so a flat cap in the head's smooth group closes it) down to the chin pole."""
    rings = [_head_ring(rig, z) for z in HEAD_ROWS] + [_jaw_ring(rig, k) for k in range(len(JAW_RINGS))]
    apex_chin = tuple(_chin_apex(rig))
    # Round 1 (F5) / round 2 (F1): the jaw underside is its own smooth group: the side columns (jaw rim ->
    # P20) from the last full ring down, the back columns once they are inside the neck, and the chin pole's
    # fan.  Its border is the jaw rim from under the ear to the chin (PDF p.18's jaw line: on the outline
    # from the front and from above, so the outline stays one stroke at head-lowered angles, and the jaw line
    # from below); its other borders lie inside the neck, or under the ear behind the silhouette of the
    # surface that turns from the jaw angle into the neck.  The nape stays in the skull's group (no line
    # around the neck).
    G = np.ones((len(rings) - 1, len(rings[0])), dtype=int)
    n0 = len(HEAD_ROWS)                                       # section n0 - 1 + k ends at jaw ring k
    nb = len(BACK_ANGLES)
    for k in range(len(JAW_RINGS)):
        s = n0 - 1 + k
        G[s, 0] = G[s, nb] = 2
        if k and JAW_RINGS[k - 1][4] is None:                 # both rings' back points inside the neck
            G[s, 1:nb] = 2
    return mk.inscribed_fan(mk.loft(rings, "flat", ("pole", apex_chin), groups=G, cap_groups=(1, None)))


class SkinSurface:
    """The head mesh with ray casting along +Y (front-most hit) and smoothed normals, for decals."""

    def __init__(self, mesh: mk.Mesh):
        self.mesh = mesh
        V = mesh.vertices
        tris, owner = mesh.triangles()
        fn, _ = mk.face_normals(mesh)
        a, b, c = V[tris[:, 0]], V[tris[:, 1]], V[tris[:, 2]]
        tn = np.cross(b - a, c - a)
        # area-weighted vertex normals (one smooth group)
        vn = np.zeros_like(V)
        for k in range(3):
            np.add.at(vn, tris[:, k], tn)
        self.vn = vn / np.linalg.norm(vn, axis=1)[:, None]
        front = tn[:, 1] < -1e-12                              # faces looking towards -Y
        self.tris = tris[front]
        self.A, self.B, self.C = a[front], b[front], c[front]

    def y(self, x: float, z: float):
        """y of the front-most mesh point at ``(x, z)``, or None off the mesh."""
        try:
            return float(self.hit(x, z)[0][1])
        except mk.MeshError:
            return None

    def hit(self, x: float, z: float):
        """``(point, unit normal)`` of the front-most mesh point at ``(x, z)`` (ray along +Y)."""
        A, B, C = self.A, self.B, self.C
        # barycentric coordinates in the xz projection
        v0 = B[:, [0, 2]] - A[:, [0, 2]]
        v1 = C[:, [0, 2]] - A[:, [0, 2]]
        v2 = np.array([x, z]) - A[:, [0, 2]]
        den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
        ok = np.abs(den) > 1e-16
        den = np.where(ok, den, 1.0)
        l1 = (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / den
        l2 = (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / den
        l0 = 1.0 - l1 - l2
        eps = -1e-9
        inside = ok & (l0 >= eps) & (l1 >= eps) & (l2 >= eps)
        if not inside.any():
            raise mk.MeshError(f"face point ({x:.4f}, {z:.4f}) is off the head mesh")
        idx = np.nonzero(inside)[0]
        y = l0[idx] * A[idx, 1] + l1[idx] * B[idx, 1] + l2[idx] * C[idx, 1]
        j = int(np.argmin(y))
        k = idx[j]
        t = self.tris[k]
        w = np.array([l0[k], l1[k], l2[k]])
        n = w @ self.vn[t]
        return np.array([x, float(y[j]), z]), n / np.linalg.norm(n)


@functools.lru_cache(maxsize=4)
def skin_surface(rig: Rig) -> SkinSurface:
    """The skin head mesh of ``rig`` with its ray caster (cached per rig)."""
    return SkinSurface(_head_mesh(rig))


def face_point(rig: Rig, x: float, z: float, offset: float = 0.0) -> np.ndarray:
    """Point of the head mesh at ``(x, z)`` (front side), moved ``offset`` along the smoothed normal."""
    p, n = skin_surface(rig).hit(x, z)
    return p + offset * n


def _face_y(rig: Rig, x: float, z: float) -> float:
    """y of the smooth §B.1 face surface (the section model without the nose ridge) at ``(x, z)``."""
    hw, yf, _yb, c = head_section(rig, z)
    u = min(1.0, abs(x) / hw)
    e = rig.face_front_exponent
    return c - (c - yf) * (1.0 - u ** e) ** (1.0 / e)


def smooth_face(rig: Rig, x: float, z: float, d: float = 2e-4):
    """``(point, unit outward normal)`` of the smooth face surface at ``(x, z)``.  The head mesh is its
    piecewise-flat inscription (rows on the profile, chords across), so a decal built on this surface is
    never under the mesh and stacked decals keep their spec reliefs instead of chord-dependent lifts."""
    p = np.array([x, _face_y(rig, x, z), z])
    px = np.array([2 * d, _face_y(rig, x + d, z) - _face_y(rig, x - d, z), 0.0])
    pz = np.array([0.0, _face_y(rig, x, z + d) - _face_y(rig, x, z - d), 2 * d])
    n = np.cross(pz, px)
    n /= np.linalg.norm(n)
    return p, (-n if n[1] > 0 else n)


# ---------------------------------------------------------------------------------------------------------
# slabs and decals
# ---------------------------------------------------------------------------------------------------------

def slab_faces(U: int, V: int):
    """Faces of a slab between a front and a back ``(U, V)`` grid (front vertices first, then back) and the
    kind of each face: ``("front"|"back", u, v)``, or a rim ``("v0"|"v1", u)`` / ``("u0"|"u1", v)``."""
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
    vol = float(np.einsum("ij,ij->i", Vx[tris[:, 0]], np.cross(Vx[tris[:, 1]], Vx[tris[:, 2]])).sum())
    return m.flipped() if vol < 0 else m


def slab(front, back, groups=(1, 2, 2, 2, 2, 2)) -> mk.Mesh:
    """Closed slab between two ``(U, V, 3)`` vertex grids (same topology as :func:`meshkit.thicken`):
    ``groups = (front, back, v0, v1, u0, u1)``, each rim entry an int or one int per rim face (``U - 1`` for
    ``v0`` / ``v1``, ``V - 1`` for ``u0`` / ``u1``).  The result is oriented outward by its signed volume."""
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
        elif np.ndim(val) == 2:                               # (U-1, V-1) table for the front / back
            fg.append(int(val[k[1]][k[2]]))
        else:
            fg.append(int(val[k[1]]))
    return oriented(mk.Mesh(np.concatenate([F.reshape(-1, 3), Bk.reshape(-1, 3)]), faces, fg))


def classify_rims(F, B, sun=None):
    """Rim groups and undercut vertices of the slab between ``F`` (front) and ``B`` (back) grids.

    castplane counts the vertices of feature edges between a lit and an unlit face (at most 64 per object)
    and draws an edge between two faces of one smooth group only where it is a camera silhouette.  So a rim
    face whose lit state differs from the front face it borders shares the front's group (1; its front rim is
    smooth) and should be undercut (leaning in under the front, so that rim is a silhouette from the front
    half space); a rim face with the same lit state as its front face gets group 2 (a feature line between
    two faces of equal lit state) like the back face.  Returns ``(groups, undercut)``: ``groups`` the four
    rim tables ``[v0 (U-1), v1 (U-1), u0 (V-1), u1 (V-1)]`` for :func:`slab` (front 1, back 2), ``undercut``
    a list of ``((u, v), (u_in, v_in))``: boundary vertices whose rims are all group 1 and their inward
    neighbour (move the back vertex towards it)."""
    F = np.asarray(F, dtype=np.float64)
    B = np.asarray(B, dtype=np.float64)
    L = SUN if sun is None else np.asarray(sun, dtype=np.float64) / np.linalg.norm(sun)
    U, V = F.shape[:2]
    faces, kinds = slab_faces(U, V)
    probe = oriented(mk.Mesh(np.concatenate([F.reshape(-1, 3), B.reshape(-1, 3)]), faces, 1))
    fn, _ = mk.face_normals(probe)
    lit = {k: bool(fn[i] @ L > 0.0) for i, k in enumerate(kinds)}
    front_of = {"v0": lambda i: ("front", i, 0), "v1": lambda i: ("front", i, V - 2),
                "u0": lambda i: ("front", 0, i), "u1": lambda i: ("front", U - 2, i)}
    group = {}
    for k in kinds:
        if k[0] in front_of:
            group[k] = 1 if lit[k] != lit[front_of[k[0]](k[1])] else 2
    adj = {}                                                  # boundary vertex -> adjacent rim faces
    for u in range(U - 1):
        for which, v in (("v0", 0), ("v1", V - 1)):
            for uu in (u, u + 1):
                adj.setdefault((uu, v), []).append((which, u))
    for v in range(V - 1):
        for which, u in (("u0", 0), ("u1", U - 1)):
            for vv in (v, v + 1):
                adj.setdefault((u, vv), []).append((which, v))
    undercut = []
    for (u, v), rims in sorted(adj.items()):
        if all(group[r] == 1 for r in rims):
            uu = u + (1 if u == 0 else -1 if u == U - 1 else 0)
            vv = v + (1 if v == 0 else -1 if v == V - 1 else 0)
            undercut.append(((u, v), (uu, vv)))
    tables = [[group[(which, i)] for i in range(count)]
              for which, count in (("v0", U - 1), ("v1", U - 1), ("u0", V - 1), ("u1", V - 1))]
    return tables, undercut


def column_grid(lo, hi, rows: int, crease_z: float | None = None) -> np.ndarray:
    """``(U, rows, 2)`` face points ``(x, z)``: column ``i`` runs from ``lo[i]`` to ``hi[i]``.  With
    ``crease_z`` and 3 rows, the middle row lies on that height (kept 15 % inside each column): the face
    profile has a concave crease there (the eye line of §B.1), which a flat decal must follow."""
    lo, hi = np.asarray(lo, dtype=np.float64), np.asarray(hi, dtype=np.float64)
    t = np.tile(np.linspace(0.0, 1.0, rows), (lo.shape[0], 1))
    if crease_z is not None and rows == 3:
        f = (crease_z - lo[:, 1]) / (hi[:, 1] - lo[:, 1])
        t[:, 1] = np.clip(f, 0.15, 0.85)
    return lo[:, None, :] + t[:, :, None] * (hi - lo)[:, None, :]


def band_grid(centre, half_width) -> np.ndarray:
    """``(U, 2, 2)`` face points of a band around the polyline ``centre`` ``(U, 2)`` (x, z) with mitred
    perpendicular offsets of ``half_width`` ``(U,)`` (row 0 on the right of the direction of travel)."""
    P = np.asarray(centre, dtype=np.float64)
    w = np.broadcast_to(np.asarray(half_width, dtype=np.float64), (len(P),))
    d = np.diff(P, axis=0)
    d /= np.linalg.norm(d, axis=1)[:, None]
    nseg = np.stack([d[:, 1], -d[:, 0]], axis=1)              # right-hand normal of each segment
    n = np.zeros_like(P)
    n[0], n[-1] = nseg[0], nseg[-1]
    for i in range(1, len(P) - 1):
        m = nseg[i - 1] + nseg[i]
        m /= np.linalg.norm(m)
        n[i] = m / max(0.3, float(m @ nseg[i]))
    return np.stack([P + w[:, None] * n, P - w[:, None] * n], axis=1)


#: Unit direction towards the scene's sun (:data:`rig.SUN_TOWARDS`), for the slab rim / decal wall
#: classification (also used by ``hair.py``).
SUN = np.asarray(SUN_TOWARDS, dtype=np.float64) / np.linalg.norm(SUN_TOWARDS)
#: Undercut of the decal walls: the back outline is the front outline moved ``rig.decal_undercut`` towards the
#: decal's centroid (eye layers; at most down to DECAL_SHRINK of its size: lean 60-75 degrees with the low stacked
#: walls) or scaled by BAND_SHRINK towards each column's middle (bands: brows, lids, mouth).
DECAL_SHRINK = 0.5
BAND_SHRINK = 0.15


# Clearances (m, along y) kept at every vertex, edge midpoint and quad diagonal midpoint of a decal
# (:func:`_clear`): its front above the skin and above every decal already placed under it, its back under
# the skin.  The decals are flat chords over a faceted, partly concave face (the eye line is a shallow valley
# in the §B.1 profile), so without this a layer could dip under the one below it between its vertices.  The
# front clearances are ``rig.decal_skin_clearance`` and ``rig.decal_layer_clearance``.


class DecalStack:
    """Front surfaces of the decals placed so far (plus the skin), for :func:`_decal`'s clearance pass."""

    def __init__(self, rig: Rig):
        self.skin = skin_surface(rig)
        self.clear_skin = rig.decal_skin_clearance
        self.clear_layer = rig.decal_layer_clearance
        self.layers = []

    def add(self, F):
        """Add the front grid ``F`` ``(U, V, 3)`` of a decal as a layer."""
        U, V = F.shape[:2]
        faces = [[u * V + v, (u + 1) * V + v, (u + 1) * V + v + 1, u * V + v + 1]
                 for u in range(U - 1) for v in range(V - 1)]
        m = mk.Mesh(F.reshape(-1, 3), faces, 1)
        fn, _ = mk.face_normals(m)
        if np.sum(fn[:, 1]) > 0:
            m = m.flipped()
        self.layers.append(SkinSurface(m))

    def required_front_y(self, x: float, z: float) -> float:
        req = self.skin.y(x, z) - self.clear_skin
        for s in self.layers:
            y = s.y(x, z)
            if y is not None:
                req = min(req, y - self.clear_layer)
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
    """Sample points of a ``(U, V, 2)`` grid with the vertices they depend on: the vertices, the edge
    midpoints and the quad diagonal midpoints (the fan diagonal ``(u, v)-(u+1, v+1)``)."""
    U, V = G.shape[:2]
    out = [(G[i, j], ((i, j),)) for i in range(U) for j in range(V)]
    for i in range(U):
        for j in range(V):
            for a, b in (((i, j), (i + 1, j)), ((i, j), (i, j + 1)), ((i, j), (i + 1, j + 1))):
                if b[0] < U and b[1] < V:
                    out.append((0.5 * (G[a] + G[b]), (a, b)))
    return out


def _clear(F, N, G, required, sign: float, rounds: int = 6):
    """Move vertices of ``F`` along their normals ``N`` until every sample's (chord) y is on the right side
    of ``required(x, z)``: ``sign = +1`` keeps ``y <= required`` (in front), ``-1`` keeps ``y >= required``.
    A two-row grid (a band) moves whole columns, so its narrow quads never twist."""
    V = F.shape[1]
    samples = []
    for xz, idx in _samples(G):
        moved_idx = idx
        if V == 2:
            moved_idx = tuple(sorted({(i, j) for i, _ in idx for j in range(V)}))
        samples.append((xz, idx, moved_idx, required(*xz)))
    for _ in range(rounds):
        moved = False
        for xz, idx, moved_idx, req in samples:
            y = sum(F[k][1] for k in idx) / len(idx)
            d = sign * (y - req)
            if d > 1e-8:
                for k in moved_idx:
                    n = N[k]
                    F[k] = F[k] + sign * (d + 1e-6) * max(0.2, -n[1]) * n     # y gap d = normal gap d n_y
                moved = True
        if not moved:
            return


def _decal(rig: Rig, grid_xz, relief: float, depth: float | None = None, stack: DecalStack | None = None,
           shrink=("centroid", DECAL_SHRINK)) -> mk.Mesh:
    """Face decal slab from ``(U, V, 2)`` face points ``(x, z)``: the front ``relief`` above the head mesh
    (and clear of the decals already in ``stack``), the back ``depth`` behind the front-most surface under
    it (the skin, or the decal it lies on).

    The decal is one smooth group, so it costs no construction ray and draws no hidden feature edges (each
    drawn edge costs castplane hidden-line samples); its outline must therefore be a camera silhouette in
    every usual view.  So every wall is undercut: the back outline is the front outline shrunk (``shrink =
    ("centroid", k)`` towards the decal's centroid, ``("across", k)`` towards each column's middle for bands)
    and the walls lean in under the front face; with the low walls of the stacked layers the lean is 50-85
    degrees, so the front rim is a silhouette from nearly the whole front half space."""
    depth = rig.eye_slab_depth if depth is None else depth
    G = np.asarray(grid_xz, dtype=np.float64)
    U, V = G.shape[:2]
    rel = np.broadcast_to(np.asarray(relief, dtype=np.float64), (U,))     # per column (tapered marks)
    surf = skin_surface(rig)
    stack = DecalStack(rig) if stack is None else stack
    F = np.zeros((U, V, 3))
    N = np.zeros((U, V, 3))
    for i in range(U):
        for j in range(V):
            p, n = smooth_face(rig, *G[i, j])
            F[i, j] = p + rel[i] * n
            N[i, j] = n
    _clear(F, N, G, stack.required_front_y, +1.0)
    mode, k = shrink
    if mode == "centroid":
        c = G.reshape(-1, 2).mean(axis=0)
        r = np.linalg.norm(G - c, axis=2, keepdims=True)
        kk = np.maximum(k, 1.0 - rig.decal_undercut / np.maximum(r, 1e-9))     # move in by decal_undercut
        GB = c + kk * (G - c)
    else:                                                     # keep the back >= 0.2 mm wide (tips)
        mid = G.mean(axis=1, keepdims=True)
        half = 0.5 * np.linalg.norm(G[:, -1] - G[:, 0], axis=1)
        kk = np.maximum(k, np.minimum(1.0, 0.0001 / np.maximum(half, 1e-9)))
        GB = mid + kk[:, None, None] * (G - mid)
    B = np.zeros((U, V, 3))
    NB = np.zeros((U, V, 3))
    for i in range(U):
        for j in range(V):
            p, n = surf.hit(*GB[i, j])
            target = stack.top_y(*GB[i, j]) + depth              # behind the front-most surface
            B[i, j] = p - (target - p[1]) / max(0.3, -n[1]) * n
            NB[i, j] = n
    _clear(B, NB, GB, lambda x, z: stack.top_y(x, z) + depth, -1.0)
    stack.add(F)
    return slab(F, B, (1, 1, 1, 1, 1, 1))


# ---------------------------------------------------------------------------------------------------------
# eyes (§B.2)
# ---------------------------------------------------------------------------------------------------------
#: Columns / rows of the eye decal grids (tessellation, not shape).
#: Round 1 (F10): 10 segments on the sclera's lower curve, 20 / 14 / 8 outline segments on iris / pupil /
#: highlight (the outline of a column grid has 2 (cols - 1) + 2 segments; the review asked for 12 / 24 /
#: 16 / 10, which costs ~0.1 s of the TS still frame for a difference hardly visible at drawing scale).
#: Round 2 (F8): 14 segments on the sclera's lower curve; 22 / 16 / 8 outline segments on iris / pupil /
#: highlight, whose grids have two rows (no crease row, see _eye_parts): the triangles they save pay for the
#: finer outlines in castplane's hidden-line time.
SCLERA_COLS, SCLERA_ROWS = 15, 3
IRIS_COLS, IRIS_ROWS = 11, 2
PUPIL_COLS, PUPIL_ROWS = 8, 2
HIGHLIGHT_COLS = 4
#: The sclera / iris tops stay this far under the lid band's upper edge (hidden under it).
LID_COVER = 0.0006
#: Stacked eye layers sink a little deeper each (sclera, iris, pupil, highlight), so their back faces never
#: share a vertex (castplane welds coincident vertices of one object).
LAYER_DEPTH_STEP = 0.00006
#: The stacked eye layers (iris, pupil, highlight) reach this far behind the layer they lie on (low walls:
#: steep undercuts); the sclera, lids, brows and mouth go eye_slab_depth under the skin.
STACK_DEPTH = 0.0003


def _smooth_curve(points, x):
    """Monotone-in-x smooth curve (Catmull-Rom in x) through ``points`` ``[(x, z)]`` evaluated at ``x``."""
    P = np.asarray(points, dtype=np.float64)
    xs, zs = P[:, 0], P[:, 1]
    # finite-difference tangents (Catmull-Rom on a non-uniform grid), cubic Hermite per interval
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
        h00, h10 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t
        h01, h11 = -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
        out[k] = h00 * zs[i] + h10 * h * m[i] + h01 * zs[i + 1] + h11 * h * m[i + 1]
    return out


def _lid_z(rig: Rig, x):
    """The upper-lid line (sclera top) at ``|x|``: z 1.351 at the eye centre, rising ``eye_lid_rise`` from
    the inner to the outer corner."""
    x = np.abs(np.asarray(x, dtype=np.float64))
    w = rig.eye_outer_x - rig.eye_inner_x
    return rig.eye_lid_z + rig.eye_lid_rise * (x - rig.eye_x) / w


def _sclera_lo(rig: Rig, x):
    return _smooth_curve(rig.sclera_lower, np.abs(np.asarray(x, dtype=np.float64)))


def _lid_band_centre(rig: Rig, x):
    (x0, z0), (x1, z1) = rig.lid_band_inner, rig.lid_band_outer
    return z0 + (np.abs(x) - x0) * (z1 - z0) / (x1 - x0)


def _lid_band_half(rig: Rig, x):
    h0, h1 = rig.lid_band_height
    x0, x1 = rig.lid_band_inner[0], rig.lid_band_outer[0]
    return 0.5 * np.interp(np.abs(x), [x0, rig.eye_x, x1], [h0, h1, h1])


def _ellipse_columns(cx, cz, a, b, n, lo_clip=None, hi_clip=None, eps=0.10):
    """Columns of an ellipse (centre ``(cx, cz)``, semi-axes ``a``, ``b``) at equal parameter angle, clipped
    to ``lo_clip(x) <= z <= hi_clip(x)``; returns ``(lo (n, 2), hi (n, 2))``."""
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


def _eye_parts(rig: Rig, side: int, stack: DecalStack):
    s = _side_name(side)
    cx = side * rig.eye_x
    xi, xo = rig.eye_inner_x, rig.eye_outer_x
    # sclera: inner side, lower curve, outer side; the top under the lid band
    xs = side * np.linspace(xi, xo, SCLERA_COLS)
    lo = np.stack([xs, _sclera_lo(rig, xs)], axis=1)
    top = np.minimum(_lid_z(rig, xs), _lid_band_centre(rig, xs) + _lid_band_half(rig, xs) - LID_COVER)
    hi = np.stack([xs, top], axis=1)
    d0 = rig.eye_slab_depth
    sclera = _decal(rig, column_grid(lo, hi, SCLERA_ROWS, rig.eye_z), rig.sclera_relief, d0, stack)
    # iris: ellipse clipped by the sclera (lower lid) and the lid line
    iw, ih = rig.iris_size
    lo_i, hi_i = _ellipse_columns(cx, rig.iris_center_z, 0.5 * iw, 0.5 * ih, IRIS_COLS,
                                  lo_clip=lambda x: _sclera_lo(rig, x) + 0.0004,
                                  hi_clip=lambda x: _lid_z(rig, x) - 0.0002)
    # round 2 (F9): the iris and pupil grids have no crease row: forcing the eye-line crease into the short
    # end columns of an ellipse twisted their front quads (visible back faces)
    iris = _decal(rig, column_grid(lo_i, hi_i, IRIS_ROWS), rig.iris_relief, STACK_DEPTH, stack)
    pw, ph = rig.pupil_size
    lo_p, hi_p = _ellipse_columns(cx, rig.pupil_center_z, 0.5 * pw, 0.5 * ph, PUPIL_COLS)
    pupil = _decal(rig, column_grid(lo_p, hi_p, PUPIL_ROWS), rig.pupil_relief, STACK_DEPTH + LAYER_DEPTH_STEP, stack)
    r = 0.5 * rig.highlight_diameter
    lo_h, hi_h = _ellipse_columns(cx + rig.highlight_dx, rig.highlight_z, r, r, HIGHLIGHT_COLS, eps=0.25)
    highlight = _decal(rig, column_grid(lo_h, hi_h, 2), rig.highlight_relief, STACK_DEPTH + 2 * LAYER_DEPTH_STEP,
                        stack)
    return [Part(f"head.sclera_{s}", "eye_white", sclera, "eyes"),
            Part(f"head.iris_{s}", "iris", iris, "eyes"),
            Part(f"head.pupil_{s}", "pupil", pupil, "eyes"),
            Part(f"head.highlight_{s}", "eye_white", highlight, "eyes")]


# ---------------------------------------------------------------------------------------------------------
# face marks (§B.2 lids, §B.3 brows, §B.4 mouth)
# ---------------------------------------------------------------------------------------------------------
LID_COLS = 7                       # main band columns (the flick adds its own)
FLICK_BEND_RADIUS = 0.0022         # the lid band turns down into the flick on this radius (no fold)
BROW_COLS = 5
LOWER_LID_COLS = 5
MOUTH_COLS = 7


#: Round 1 (F17): the brow and the lid band thin to this relief over the outer RELIEF_TAPER_FRACTION of their
#: length (where the face turns away), so they stay inside the profile outline.
RELIEF_TAPER_END = 0.0004
RELIEF_TAPER_FRACTION = 0.25
#: Round 2 (F4): the lid band (with its flick) thins over its outer 45 %, so it no longer juts out of the profile
#: like a visor.
LID_TAPER_FRACTION = 0.45


def _tapered_relief(centre_xz, relief: float, fraction: float = RELIEF_TAPER_FRACTION) -> np.ndarray:
    """Per-column relief along the polyline ``centre_xz`` (inner end first): ``relief`` up to the last
    :data:`RELIEF_TAPER_FRACTION` of its length, then linear down to :data:`RELIEF_TAPER_END`."""
    P = np.asarray(centre_xz, dtype=np.float64)
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    s /= s[-1]
    t = np.clip((s - (1.0 - fraction)) / fraction, 0.0, 1.0)
    return relief + t * (min(relief, RELIEF_TAPER_END) - relief)


def _line_intersection(p, d, q, e):
    """Intersection of the 2D lines ``p + s d`` and ``q + t e``."""
    M = np.array([[d[0], -e[0]], [d[1], -e[1]]])
    s, _t = np.linalg.solve(M, np.asarray(q) - np.asarray(p))
    return np.asarray(p) + s * np.asarray(d)


def _lid_band(rig: Rig, side: int, stack: DecalStack) -> mk.Mesh:
    """Upper-lid band along the lid line, turning down at the outer end into the lash flick (a fillet arc of
    radius ``FLICK_BEND_RADIUS`` between the band line and the flick line through the flick tip)."""
    (x0, z0), (x1, z1) = rig.lid_band_inner, rig.lid_band_outer
    tip = np.array(rig.lid_flick_tip)
    ang = math.radians(rig.lid_flick_angle_deg)
    d2 = np.array([math.cos(ang), -math.sin(ang)])           # flick direction (down and outward)
    d1 = np.array([x1 - x0, z1 - z0])
    d1 /= np.linalg.norm(d1)                                  # band direction (inner -> outer)
    n1 = np.array([d1[1], -d1[0]])                            # right-hand normals (below the travel)
    n2 = np.array([d2[1], -d2[0]])
    R = FLICK_BEND_RADIUS
    centre = _line_intersection(np.array([x0, z0]) + R * n1, d1, tip + R * n2, d2)
    t1, t2 = centre - R * n1, centre - R * n2
    a0 = math.atan2(-n1[1], -n1[0])
    a1 = math.atan2(-n2[1], -n2[0])
    if a1 > a0:
        a1 -= 2 * math.pi
    k_arc = 3
    arc = [centre + R * np.array([math.cos(a), math.sin(a)]) for a in np.linspace(a0, a1, k_arc + 1)[1:]]
    main_x = np.linspace(x0, t1[0], LID_COLS)
    main = np.stack([main_x, z0 + (main_x - x0) * d1[1] / d1[0]], axis=1)
    tail = [t2 + t * (tip - t2) for t in (0.55, 1.0)]
    centre_line = np.concatenate([main, np.array(arc), np.array(tail)])
    hw_main = _lid_band_half(rig, main_x)
    hw_arc = np.linspace(hw_main[-1], 0.5 * rig.lid_flick_width, k_arc + 1)[1:]
    hw_tail = 0.5 * rig.lid_flick_width * np.array([0.65, 0.20])
    half = np.concatenate([hw_main, hw_arc, hw_tail])
    g = band_grid(centre_line, half)
    g[..., 0] *= side
    return _decal(rig, g, _tapered_relief(centre_line, rig.lid_band_relief, LID_TAPER_FRACTION),
                  rig.eye_slab_depth + 0.5 * LAYER_DEPTH_STEP, stack, shrink=("across", BAND_SHRINK))


def _brow(rig: Rig, side: int) -> mk.Mesh:
    pts = np.array([rig.brow_inner, rig.brow_mid, rig.brow_outer])
    xs = np.linspace(pts[0, 0], pts[-1, 0], BROW_COLS)
    zs = _smooth_curve(pts, xs)
    t = (xs - xs[0]) / (xs[-1] - xs[0])
    w0, w1 = rig.brow_width
    half = 0.5 * (w0 + (w1 - w0) * t)
    half[0] *= 0.75                                           # slightly rounded stroke ends
    half[-1] *= 0.6
    centre = np.stack([xs, zs], axis=1)
    g = band_grid(centre, half)
    g[..., 0] *= side
    return _decal(rig, g, _tapered_relief(centre, rig.brow_relief), shrink=("across", BAND_SHRINK))


def _lower_lid(rig: Rig, side: int, stack: DecalStack) -> mk.Mesh:
    xa, xb = rig.lower_lid_x
    xs = np.linspace(xa, xb, LOWER_LID_COLS)
    zc = _sclera_lo(rig, xs) - rig.lower_lid_offset - 0.5 * rig.lower_lid_width
    half = np.full(len(xs), 0.5 * rig.lower_lid_width)
    half[0] *= 0.5
    half[-1] *= 0.7
    g = band_grid(np.stack([xs, zc], axis=1), half)
    g[..., 0] *= side
    del stack                                                 # beside the sclera, not on it: own stack (skin)
    return _decal(rig, g, rig.lower_lid_relief, rig.eye_slab_depth + 1.5 * LAYER_DEPTH_STEP,
                  shrink=("across", BAND_SHRINK))


def _mouth(rig: Rig) -> mk.Mesh:
    hw = 0.5 * rig.mouth_width
    xs = np.linspace(-hw, hw, MOUTH_COLS)
    u = np.abs(xs) / hw
    base = rig.mouth_cusp_z + (rig.mouth_corner_z - rig.mouth_cusp_z) * u
    zc = base - rig.mouth_arc_sag * np.sin(np.pi * u)
    half = np.full(len(xs), 0.5 * rig.mouth_band)
    half[0] *= 0.6
    half[-1] *= 0.6
    # vertical columns (the omega cusp would fold perpendicular offsets)
    lo = np.stack([xs, zc - half], axis=1)
    hi = np.stack([xs, zc + half], axis=1)
    return _decal(rig, column_grid(lo, hi, 2), rig.mouth_relief, shrink=("across", BAND_SHRINK))


# ---------------------------------------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------------------------------------

def build(rig: Rig):
    """Parts of :data:`REGIONS` for ``rig``."""
    parts = [Part("head.skin", "skin", skin_surface(rig).mesh, "head")]
    marks = []
    for side in SIDES:
        s = _side_name(side)
        stack = DecalStack(rig)                               # the eye layers of this side, in order
        parts += _eye_parts(rig, side, stack)
        marks += [Part(f"head.lid_{s}", "face_marks", _lid_band(rig, side, stack), "face_marks"),
                  Part(f"head.lower_lid_{s}", "face_marks", _lower_lid(rig, side, stack), "face_marks"),
                  Part(f"head.brow_{s}", "face_marks", _brow(rig, side), "face_marks")]
    parts += marks
    parts.append(Part("head.mouth", "face_marks", _mouth(rig), "face_marks"))
    return parts
