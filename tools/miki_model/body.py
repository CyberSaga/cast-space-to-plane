"""Neck, sailor top, collar, scarf + ring and skirt of the Miki model (owner: body agent).

Part contract (see ``assemble.py`` and ``README.md`` in this directory): :func:`build` takes the
:class:`~miki_model.rig.Rig` and returns a list of :class:`~miki_model.meshkit.Part` covering **all** of
:data:`REGIONS`.  Objects / materials (``Part(name, material, mesh, region, obj=...)``): neck + decollete
bib -> head (skin); torso -> blouse (uniform); collar, dickey -> collar (collar), collar stripe -> collar
(uniform); scarf ribbons, tips -> scarf (scarf); ring -> ``obj="ring"`` (collar), ring stripes ->
``obj="ring"`` (uniform); skirt, under-skirt -> skirt (skirt).

How the lines come out (castplane draws feature edges always and smooth edges only on the camera
silhouette; SPEC.md §F):

* the blouse is one smooth group; its flat hem disc has its own group, so the hem rim always draws;
* the collar top is one group and its walls + underside another: the outer and inner edges always draw,
  the 4 mm underside edge only where it is the outline;
* the colour stripes (collar stripe, ring stripes) are thin single-group bands that **float** 0.25 mm
  above the surface they decorate: both borders then draw as silhouettes from every side (a band sunk into
  the surface would lose the border whose wall faces the camera) and they cost no construction rays;
* the scarf ribbons (lens section), tips, ring, neck, bib and dickey are single groups: outlines only;
* the skirt's 16 knife pleats alternate two smooth groups column by column on the outer surface, the hem
  rim and the inner surface, so the 32 crest / valley creases draw from the blouse hem to the skirt hem
  (and inside the skirt) while the hem itself draws as the outline of the thin fabric edge.
"""

from __future__ import annotations

import math

import numpy as np

from . import meshkit as mk
from .meshkit import Part
from .rig import Rig

__all__ = ["REGIONS", "build", "Torso", "torso_model"]

#: The mannequin regions this module replaces.
REGIONS = ("neck", "torso", "collar", "scarf", "skirt")

SIDES = (1, -1)

# ---------------------------------------------------------------------------------------------------
# Module constants (numbers the rig does not carry; see the report for the rig changes they suggest)
# ---------------------------------------------------------------------------------------------------
#: Convex shoulder slope of the blouse between the neck root (1.215) and the acromion (1.180), as
#: ``(z, hw)``: through the collar's I3 (x 0.042 at z 1.213) and O5 (x 0.118 at z 1.191) (SPEC.md §D.2);
#: yf / yb are interpolated linearly between the rig's 1.215 and 1.180 rows.
TORSO_RING_POINTS = 18                 # points per blouse section
TORSO_SKIP_ROWS = ()                   # rig rows the loft leaves out (linear between their neighbours; v6: none,
#                                        the old 0.990 row is now the lofted 1.000 row under the bust)
TORSO_NECK_INSET = 0.004               # the blouse's top ring sits this far inside the neck
COLLAR_END_WIDTH = 0.004               # each lapel ends at the V tip with this width (the halves don't touch)
COLLAR_LAPEL_Y = -0.03                 # collar columns in front of this are the lapels (feature-line edges)
COLLAR_SHOULDER_ROUNDING = 12         # moving-average half window (samples of 400) rounding the O3-O5 turn
COLLAR_EDGE_THICKNESS = 0.0030        # the 4 mm collar thins to this at its outer / inner edges
COLLAR_BIB_CLEARANCE = 0.0006        # the collar's underside clears the bib's top by this (r3 F4)
BIB_AWAY_Z = 1.15                    # the bib is thickened inward, away from (0, neck centre y, BIB_AWAY_Z)
COLLAR_BIB_PASSES = 8                 # ... raised in up to this many passes
COLLAR_RAISED_MIN_THICKNESS = 0.0012  # ... and the slab there thins to keep its top: at least this thick
NECK_POINTS = 14
RING_POINTS = 8                        # scarf ring (and its stripes) section points
RIBBON_PROFILE_POINTS = 8              # scarf ribbon lens section points
RIBBON_LIFT_PASSES = 6                 # the ribbon stations lift off the faceted blouse in up to this many passes
BIB_COLUMNS = 13
BIB_SINK = 0.002                       # the bib's top row lies this far inside the neck surface
BIB_THICKNESS = 0.0015                 # the bib slab grows this far inward from its laid top face
BIB_MIN_THICKNESS = 0.0005             # ... and thins to no less than this off the faceted blouse
BIB_UNDER_COLLAR = 0.009               # the bib reaches this far under the collar inner edge (6 mm left blouse
#                                        showing between two columns at the lapel after the r1 shoulder change)
SKIRT_FACING_INSET = 0.007             # the facing's top ring inside the pleated surface
SKIRT_TWIST_SPLIT_DEG = 1.0            # pleat quads twisted more than this become two triangles (r4 F5)
BIB_TWIST_SPLIT_DEG = 10.0             # ... and bib quads (r4 merge, shared F6: dashes missing along the collar
#                                        top in the low head views; +42 polygons, no extra triangles)
#: The bloomers block (object skirt, the hips): ``(z, hw, yf, yb)`` rows, exponent rig.torso_exponent, 16 points.
#: v6: narrowed with the A-line skirt (was ((0.950, 0.100, -0.060, 0.055), (0.780, 0.150, -0.075, 0.090),
#: (0.700, 0.157, -0.081, 0.092))): its top ring 4 mm inside the skirt's waist rim (equal half-widths put two
#: vertices within 1e-5 m), the legs' top caps (rig.leg_top_z) inside it, its bottom inside the skirt's ceiling.
UNDERSKIRT = ((0.950, 0.096, -0.060, 0.055), (0.780, 0.111, -0.074, 0.080), (0.700, 0.120, -0.080, 0.088))
#: The neck (review r1, F6 / T6): ``rig.neck_half_width`` is its half-width at the head end; toward the base it
#: widens by this extra half-width ``(z, extra)`` (a 12 % taper with most of it in the last 15 mm: the flare
#: into the trapezius, continued under the blouse).  The depth semi-axis scales with the half-width.
#: Review r4 (F14, the user's notes: a slimmer neck): the flare is 40 % of round 3's (root half-width 0.0262,
#: was 0.028; 0.027 at the bottom inside the blouse, was 0.030).
NECK_FLARE = ((1.180, 0.0020), (1.205, 0.0018), (1.215, 0.0012), (1.228, 0.0005), (1.245, 0.0))
#: The depth semi-axis is ``rig.neck_y``'s half-depth times ``a / (rig.neck_half_width + NECK_DEPTH_FLARE)``:
#: round 3's root flare, so the head end (where head.py's jaw joins the neck) keeps its round-3 section.
NECK_DEPTH_FLARE = 0.0030
NECK_BASE_Z = 1.215                    # ``rig.neck_y`` is the neck's front / back at this height (its root)
NECK_TILT_DEG = 8.0                    # the axis leans forward: the top is in front of the base
NECK_RING_Z = (1.180, 1.215, 1.236, 1.285)   # neck sections (ends inside torso / head; few: hidden-line cost)
NECK_BLOUSE_INSET = 0.003              # the blouse's neck-root row stays this far inside the neck
NECK_FIT = 0.85                        # ... and its ring within this ellipse measure of the neck (~2 mm in)
#: Parts laid on the blouse (collar, bib, scarf ribbons) clear its FACETED loft by at least this (body.faceted_deficit):
#: laid on the analytic Torso alone, the collar's twisted back-flap quads dipped 1.2 mm into the loft along their fan
#: diagonals, the ribbons' inner lens edges 1.3 mm and the bib's back face 0.2 mm (the clearance checks'
#: generic:body.blouse|body.collar, |body.scarf_ribbon_*, generic:body.bib|body.blouse)
FACETED_CLEARANCE = 0.0002
#: A point inside the chest (the collar slab's and its stripe's normals point away from it).
TORSO_CENTRE = (0.0, 0.012, 1.12)
#: v6: the blouse below the bust (rig.blouse_rows from the bust down) is narrowed so that the sleeve, turned inward
#: to the required arms-inward angles (poses.POSES), clears it by at least this below z
#: acceptance.SLEEVE_JOIN_FLOOR_Z (acceptance clear:limbs.sleeve_*^body.blouse/waist, both clipped there; the band
#: above it, up to the zone-exempt shoulder join, is not measured).
SLEEVE_BLOUSE_CLEARANCE = 0.002

#: Review r4 (F1): narrow, sloping shoulders (the close-up and 3/4 profile frames, the user's drawing and notes): the
#: rig's blouse_rows[1:3], blouse_shoulder_hw, shoulder_joint_pos, sleeve_radii and collar_outer O4 - O6 hold
#: the round-4 values (round 3 rose only ~12 deg from the neck to a square sleeve-cap corner 0.358 wide).


def _side_name(side: int) -> str:
    return "l" if side > 0 else "r"


def _grid_normals(G, away_from):
    """Unit normals ``(U, V, 3)`` of a surface grid, oriented away from ``away_from``."""
    du = np.gradient(G, axis=0)
    dv = np.gradient(G, axis=1)
    n = np.cross(du, dv)
    n /= np.linalg.norm(n, axis=2)[..., None]
    if np.einsum("uvi,uvi->", n, G - np.asarray(away_from, dtype=np.float64)) < 0:
        n = -n
    return n


def _interp(rows, z, col):
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


# ---------------------------------------------------------------------------------------------------
# The blouse surface as an implicit function (used by the loft and to lay the collar, bib, dickey and
# scarf onto it)
# ---------------------------------------------------------------------------------------------------

class Torso:
    """Blouse surface: horizontal sections ``|x/hw|^e + |y/b|^e = 1`` (``b = -yf`` in front, ``yb`` behind),
    rows linear in z.  :meth:`onto` lays points on the surface plus a gap."""

    def __init__(self, rows, exponent):
        self.rows = tuple(rows)
        self.e = float(exponent)

    def section(self, z):
        hw, yf, yb = (_interp(self.rows, z, k) for k in (1, 2, 3))
        over = z - self.rows[0][0]
        if over > 0:                                  # closed just above the top row (not a cylinder)
            k = max(0.02, 1.0 - over / 0.008)
            hw, yf, yb = hw * k, yf * k, yb * k
        return hw, yf, yb

    def f(self, p):
        hw, yf, yb = self.section(p[2])
        b = yb if p[1] > 0 else -yf
        return (abs(p[0]) / hw) ** self.e + (abs(p[1]) / b) ** self.e

    def grad(self, p, h=1e-6):
        return np.array([(self.f(p + h * e) - self.f(p - h * e)) / (2 * h) for e in np.eye(3)])

    def normal(self, p):
        g = self.grad(np.asarray(p, dtype=np.float64))
        return g / np.linalg.norm(g)

    def onto(self, p, gap=0.0):
        """``p`` moved onto the surface (Newton steps along the gradient) and then ``gap`` out along the
        normal."""
        q = np.array(p, dtype=np.float64)
        for _ in range(40):
            g = self.grad(q)
            r = self.f(q) - 1.0
            q = q - r / float(g @ g) * g
            if abs(r) < 1e-10:
                break
        return q + gap * self.normal(q)

    #: skeleton the surface is cast from (spine + shoulder line): a ray from its closest point through a
    #: point never runs along the surface, unlike the gradient of the piecewise-linear rows
    SKELETON = (((0.0, 0.008, 0.80), (0.0, 0.008, 1.14)), ((-0.11, 0.008, 1.15), (0.11, 0.008, 1.15)))

    def cast(self, p):
        """``(surface point, unit ray direction)``: the surface hit by the ray from the closest skeleton
        point through ``p`` (bisection on the section measure)."""
        p = np.asarray(p, dtype=np.float64)
        best = None
        for a, b in self.SKELETON:
            a, b = np.asarray(a), np.asarray(b)
            t = float(np.clip(np.dot(p - a, b - a) / np.dot(b - a, b - a), 0.0, 1.0))
            c = a + t * (b - a)
            dist = float(np.linalg.norm(p - c))
            if best is None or dist < best[0] - 1e-12:
                best = (dist, c)
        c = best[1]
        d = p - c
        d /= np.linalg.norm(d)
        lo, hi = 0.0, 0.4
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if self.f(c + mid * d) < 1.0:
                lo = mid
            else:
                hi = mid
        return c + 0.5 * (lo + hi) * d, d

    def ring(self, z, n, inset=0.0):
        """Section ring ``(n, 3)`` (CCW from +Z, first point on +X), shrunk by ``inset``."""
        hw, yf, yb = self.section(z)
        t = 2.0 * np.pi * np.arange(n) / n
        ct, st = np.cos(t), np.sin(t)
        x = (hw - inset) * np.sign(ct) * np.abs(ct) ** (2.0 / self.e)
        y = np.where(st > 0, yb - inset, -yf - inset) * np.sign(st) * np.abs(st) ** (2.0 / self.e)
        return np.stack([x, y, np.full(n, z)], axis=1)


def _surface_heights(T, points, directions, reach: float = 0.02, chunk: int = 64):
    """:func:`meshkit.surface_clearance` on the triangles ``T`` ``(K, 3, 3)`` (the same rule: signed height of each
    point along its unit direction above the triangles, the hit nearest to the point wins, ``nan`` on a miss) for
    the hits within ``reach`` of the points (a farther one may read ``nan``), vectorised over chunks of points
    against the triangles near each chunk (the laid-on parts run it every pass)."""
    T = np.asarray(T, dtype=np.float64)
    P = np.asarray(points, dtype=np.float64)
    D = np.asarray(directions, dtype=np.float64)
    lo, hi = T.min(axis=1), T.max(axis=1)
    out = np.full(len(P), np.nan)
    for k0 in range(0, len(P), chunk):
        X = P[k0:k0 + chunk]
        near = np.nonzero(np.all((lo <= X.max(axis=0) + reach) & (hi >= X.min(axis=0) - reach), axis=1))[0]
        if not len(near):
            continue
        a, b, c = T[near, 0], T[near, 1], T[near, 2]
        e1, e2 = b - a, c - a
        d = -D[k0:k0 + chunk, None, :]                                   # (p, 1, 3)
        h = np.cross(d, e2[None])                                        # (p, T, 3)
        det = np.einsum("tj,ptj->pt", e1, h)
        ok = np.abs(det) > 1e-14
        f = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        sv = X[:, None, :] - a[None]
        u = f * np.einsum("ptj,ptj->pt", sv, h)
        q = np.cross(sv, e1[None])
        v = f * np.einsum("ptj,ptj->pt", q, np.broadcast_to(d, q.shape))
        t = f * np.einsum("tj,ptj->pt", e2, q)
        hit = ok & (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0)
        at = np.where(hit, np.abs(t), np.inf)
        j = np.argmin(at, axis=1)
        r = np.arange(len(j))
        out[k0:k0 + len(j)] = np.where(np.isfinite(at[r, j]), t[r, j], np.nan)
    return out


#: The four triangles of a grid quad's two fans (castplane draws one; ``fan_fold`` decides which).
QUAD_FANS = ((0, 1, 2), (0, 2, 3), (0, 1, 3), (1, 2, 3))


def _grid_quads(U: int, V: int, periodic_v: bool = False) -> np.ndarray:
    """``(Q, 4)`` flat corner indices of the quads of a ``(U, V)`` grid (``u`` major)."""
    return np.array([[j * V + i, (j + 1) * V + i, (j + 1) * V + (i + 1) % V, j * V + (i + 1) % V]
                     for j in range(U - 1) for i in range(V if periodic_v else V - 1)])


def _lower_fans(Gf, quads, up) -> np.ndarray:
    """``(Q, 2, 3)``: per quad the fan whose diagonal midpoint lies lower along the mean ``up`` of its corners -- the
    fan ``fan_fold`` gives a slab's valley-folded top and its ridge-folded underside."""
    D = np.asarray(up, dtype=np.float64)[quads].sum(axis=1)
    P = Gf[quads]
    low02 = np.einsum("qi,qi->q", 0.5 * (P[:, 0] + P[:, 2]) - 0.5 * (P[:, 1] + P[:, 3]), D) <= 0.0
    local = np.where(low02[:, None, None], np.array(QUAD_FANS[:2])[None], np.array(QUAD_FANS[2:])[None])
    return np.take_along_axis(np.repeat(quads[:, None, :], 2, axis=1), local, axis=2)


def _distance_deficit(Gf, quads, VB, tris_b, height: float, fans=None) -> np.ndarray:
    """Per grid vertex (flat ``Gf``): how far ``height`` exceeds the exact distance from the fan triangles of the
    quads it is a corner of (``fans`` ``(Q, k, 3)``, default both fans of each quad) to the triangles ``tris_b`` over
    ``VB`` (a crossing pair counts as 0: the pair distance of two triangles that pierce each other is not 0); 0 where
    they are farther apart."""
    fans = quads[:, QUAD_FANS] if fans is None else np.asarray(fans)
    per = fans.shape[1]
    fans = fans.reshape(-1, 3)
    need = np.zeros(len(Gf))
    ia, ib = mk.triangle_bbox_pairs(Gf, fans, VB, tris_b, pad=height)
    if len(ia):
        d, _pa, _pb = mk.triangle_pair_distance(Gf[fans[ia]], VB[tris_b[ib]])
        cut = mk.triangle_intersections(Gf, fans, VB, tris_b, 1e-9, pairs=(ia, ib))
        crossing = set(zip(cut["ia"].tolist(), cut["ib"].tolist()))
        d = np.where([(a, b) in crossing for a, b in zip(ia.tolist(), ib.tolist())], 0.0, d)
        np.maximum.at(need, quads[ia // per].reshape(-1), np.repeat(np.maximum(height - d, 0.0), 4))
    return need


def faceted_deficit(mesh: mk.Mesh, grid, up, height, periodic_v: bool = False):
    """Per grid vertex ``(U, V)``: how much it must rise along ``up`` ``(U, V, 3)`` so that the quads of ``grid``
    ``(U, V, 3)`` lie at least ``height`` above ``mesh`` -- the FACETED surface (the blouse loft as built), measured
    along ``up`` as :func:`meshkit.surface_clearance` does.  Every quad is sampled at its corners, edge midpoints,
    both diagonal midpoints and the centroids of the four triangles of its two possible fans (a twisted quad's fan
    diagonal dips well below its corner mean, and ``fan_fold`` may pick either); a sample's deficit goes to the
    corners it is made of.  Every one of those four triangles of each quad must also be ``height`` from the mesh's
    triangles by the exact distance (a ridge of the faceted mesh can cross a fan diagonal between the samples; the
    samples along ``up`` catch a quad sunk deeper than ``height``); a quad's distance deficit goes to its four
    corners.  ``periodic_v`` closes the grid in ``v`` (a swept section)."""
    G = np.asarray(grid, dtype=np.float64)
    U, V = G.shape[:2]
    Gf = G.reshape(-1, 3)
    Df = np.asarray(up, dtype=np.float64).reshape(-1, 3)
    W, rows, cols, quads = _quad_samples(U, V, periodic_v)
    pts = np.einsum("sv,vi->si", W, Gf)                 # fixed-order sums (no BLAS kernel in the vertices)
    dirs = np.einsum("sv,vi->si", W, Df)
    dirs /= np.linalg.norm(dirs, axis=1)[:, None]
    tris, _ = mk.triangulate(mesh.faces)
    h = _surface_heights(mesh.vertices[tris], pts, dirs)
    deficit = np.where(np.isfinite(h), height - np.nan_to_num(h), 0.0)
    need = np.zeros(U * V)
    np.maximum.at(need, cols, np.maximum(deficit[rows], 0.0))
    # and by the exact distance: a ridge of the faceted mesh may cross a fan diagonal of the grid between the samples
    need = np.maximum(need, _distance_deficit(Gf, quads, mesh.vertices, tris, height))
    return need.reshape(U, V)


def _quad_samples(U: int, V: int, periodic_v: bool):
    """The samples of :func:`faceted_deficit` on a ``(U, V)`` grid: ``(W, rows, cols, quads)``, ``W``
    ``(S, U * V)`` the sample weights (each sample the mean of the corners it is made of), ``(rows, cols)`` the
    sample -> corner pairs and ``quads`` ``(Q, 4)`` the flat corner indices of each quad."""
    quads = _grid_quads(U, V, periodic_v)
    sets = []
    for quad in quads.tolist():
        sets += [[q] for q in quad]
        sets += [[quad[k], quad[(k + 1) % 4]] for k in range(4)]
        sets += [[quad[0], quad[2]], [quad[1], quad[3]]]
        sets += [[quad[k] for k in tri] for tri in QUAD_FANS]
    sets = [list(k) for k in dict.fromkeys(tuple(sorted(own)) for own in sets)]   # each sample once, in order
    W = np.zeros((len(sets), U * V))
    rows, cols = [], []
    for k, own in enumerate(sets):
        W[k, own] = 1.0 / len(own)
        rows += [k] * len(own)
        cols += own
    return W, np.array(rows), np.array(cols), quads


def lay_on(torso: Torso, P, gap, margin=0.0006, passes=6, mesh: mk.Mesh | None = None, return_gap: bool = False):
    """Grid ``P`` ``(U, V, 3)`` laid on the blouse: each point moved onto the surface plus its ``gap``
    ``(U, V)``; then, wherever a quad's centre or an edge midpoint (a chord of the faceted grid) dips closer
    than ``margin`` to the curved surface, the gaps of its corners grow until it clears.  With ``mesh`` (the
    blouse loft as built) the grid also clears that faceted surface by FACETED_CLEARANCE (:func:`faceted_deficit`).
    ``return_gap`` also returns the grown gaps ``(U, V)`` (a caller that raises the grid further adds to these: a
    rise below what the margin passes already added would otherwise be absorbed)."""
    P = np.asarray(P, dtype=np.float64)
    U, V = P.shape[:2]
    G = np.array(np.broadcast_to(np.asarray(gap, dtype=np.float64), (U, V)))
    hits = [[torso.cast(P[j, i]) for i in range(V)] for j in range(U)]
    base = np.array([[h[0] for h in row] for row in hits])
    nrm = np.array([[h[1] for h in row] for row in hits])

    def sd(q):
        g = torso.grad(q)
        return (torso.f(q) - 1.0) / float(np.linalg.norm(g))

    grid = base + G[..., None] * nrm
    for _ in range(passes):
        bump = np.zeros((U, V))
        for j in range(U - 1):
            for i in range(V - 1):
                quad = [(j, i), (j + 1, i), (j + 1, i + 1), (j, i + 1)]
                centre = 0.25 * sum(grid[a, b] for a, b in quad)
                tests = [(quad, centre)]
                tests += [([quad[k], quad[(k + 1) % 4]], 0.5 * (grid[quad[k]] + grid[quad[(k + 1) % 4]]))
                          for k in range(4)]
                # the quarter points (centre -> corner): on a strongly curved patch (the shoulder turn
                # under the bib) the surface can rise between the centre and the edge midpoints
                tests += [(quad, 0.5 * (centre + grid[c])) for c in quad]
                for corners, c in tests:
                    d = margin - sd(c)
                    if d > 0:
                        for a, b in corners:
                            bump[a, b] = max(bump[a, b], d)
        if mesh is not None:
            bump = np.maximum(bump, faceted_deficit(mesh, grid, nrm, FACETED_CLEARANCE))
        if not np.any(bump > 1e-6):
            break
        G += bump
        grid = base + G[..., None] * nrm
    return (grid, G) if return_gap else grid


def torso_model(rig: Rig) -> Torso:
    """The blouse rows: the rig's rows with the convex shoulder of ``rig.blouse_shoulder_hw`` in between."""
    br = list(rig.blouse_rows)
    # the neck-root row inside the neck (half-width, front and back NECK_BLOUSE_INSET inside)
    a, cy, b = _neck_section(rig, br[0][0])
    k = NECK_BLOUSE_INSET
    br[0] = (br[0][0], min(br[0][1], a - k), max(br[0][2], cy - b + k), min(br[0][3], cy + b - k))
    # the blouse section is a superellipse about y = 0, the neck an ellipse about cy: narrow the row until
    # its whole ring lies inside the neck (ellipse measure <= NECK_FIT)
    for _ in range(40):
        R = Torso([br[0]], rig.torso_exponent).ring(br[0][0], 72)
        if float(np.max((R[:, 0] / a) ** 2 + ((R[:, 1] - cy) / b) ** 2)) <= NECK_FIT:
            break
        br[0] = (br[0][0], br[0][1] - 0.0005, br[0][2], br[0][3])
    rows = []
    for z, hw in rig.blouse_shoulder_hw:            # yf / yb linear in z through the table's rows
        if z >= br[0][0] - 1e-9:
            hw = min(hw, br[0][1])
        rows.append((z, hw, _interp(br, z, 2), _interp(br, z, 3)))
    last = rig.blouse_shoulder_hw[-1][0]
    rows += [r for r in br[2:] if r[0] not in TORSO_SKIP_ROWS and r[0] < last - 1e-9]
    return Torso(rows, rig.torso_exponent)


# ---------------------------------------------------------------------------------------------------
# neck + bib (object head, skin)
# ---------------------------------------------------------------------------------------------------

def _neck_section(rig: Rig, z):
    """``(half-width, centre y, depth semi-axis)`` of the elliptic neck section at ``z``: tapered toward the
    head (:data:`NECK_FLARE`), its axis leaning forward by :data:`NECK_TILT_DEG` about ``NECK_BASE_Z``."""
    y0, y1 = rig.neck_y
    zs, extra = zip(*NECK_FLARE)
    base = rig.neck_half_width + NECK_DEPTH_FLARE
    a = rig.neck_half_width + float(np.interp(z, zs, extra))
    b = 0.5 * (y1 - y0) * a / base
    cy = 0.5 * (y0 + y1) - math.tan(math.radians(NECK_TILT_DEG)) * (z - NECK_BASE_Z)
    return a, cy, b


def _neck(rig: Rig):
    z0, z1 = rig.neck_z
    zs = [z for z in NECK_RING_Z if z0 - 1e-9 <= z <= z1 + 1e-9]
    zs = sorted(set([z0] + zs + [z1]))
    rings = []
    for z in zs:
        a, cy, b = _neck_section(rig, z)
        rings.append(mk.ellipse_ring(a, b, NECK_POINTS, (0.0, cy, z)))
    return mk.loft(rings, "flat", "flat", cap_groups=(1, 1))


def _neck_point(rig: Rig, phi, z, sink=0.0):
    a, cy, b = _neck_section(rig, z)
    return np.array([(a - sink) * math.cos(phi), cy + (b - sink) * math.sin(phi), z])


def _bib(rig: Rig, torso: Torso, inner_edge, blouse: mk.Mesh):
    """Skin sheet filling the collar's V opening: columns around the front half of the neck, each from
    inside the neck out to under the collar's inner edge (or under the dickey's top edge at the front),
    lying ``bib_lift`` above the blouse (its back face FACETED_CLEARANCE above the ``blouse`` loft)."""
    cy = _neck_section(rig, torso.rows[0][0])[1]
    ie = np.asarray(inner_edge)                     # her left inner edge I3 ... I7 (dense), on the blouse
    az = np.arctan2(ie[:, 1] - cy, ie[:, 0])
    phis = np.radians(np.linspace(8.0, -188.0, BIB_COLUMNS))
    rows = []
    bottom = rig.bib_bottom_z - 0.007                 # under the dickey's top edge
    for phi in phis:
        side = 1.0 if math.cos(phi) >= 0 else -1.0
        a = math.atan2(math.sin(phi), side * math.cos(phi))   # mirrored to her left
        order = np.argsort(az)                        # the inner edge interpolated by azimuth
        e = np.array([np.interp(a, az[order], ie[order, c]) for c in range(3)])
        e[0] *= side
        out = e + BIB_UNDER_COLLAR * np.array([math.cos(phi), math.sin(phi), -0.6])   # under the collar
        if out[2] < bottom:
            out = out + (bottom - out[2]) / (e[2] + 0.02 - out[2]) * (e + np.array([0, 0, 0.02]) - out)
            out[2] = bottom
        # the top row lies on the blouse inside the neck (no fin standing out of the neck surface)
        # the top row: inside the neck at the height where the blouse meets the neck, so the bib leaves
        # the neck flush with the blouse (no fin standing out of the neck surface)
        inner = _neck_point(rig, phi, torso.rows[0][0] + rig.bib_lift, BIB_SINK)
        rows.append([inner] + [inner + t * (out - inner) for t in (0.15, 0.4, 0.7, 1.0)])
    P = np.array(rows)
    grid = np.concatenate([P[:, :1], lay_on(torso, P[:, 1:], rig.bib_lift, margin=0.0013)], axis=1)
    # the top stays where the analytic lay put it (under the collar and the dickey); where the back face would
    # come closer than FACETED_CLEARANCE to the faceted blouse (its top row inside the neck, BIB_SINK + the
    # thickness deeper than NECK_BLOUSE_INSET; the laid rows, whose back face lies on the analytic surface) the
    # slab thins (acceptance generic:body.bib|body.blouse)
    away = (0.0, cy, BIB_AWAY_Z)
    out = _grid_normals(grid, away)
    need = faceted_deficit(blouse, grid, out, BIB_THICKNESS + FACETED_CLEARANCE)
    return mk.thicken(grid, np.maximum(BIB_MIN_THICKNESS, BIB_THICKNESS - need), offset="inward", away_from=away,
                      groups="single")


# ---------------------------------------------------------------------------------------------------
# blouse (object blouse, uniform)
# ---------------------------------------------------------------------------------------------------

def _blouse(rig: Rig, torso: Torso):
    n = TORSO_RING_POINTS
    top_z = rig.neck_base_z + 0.027
    a, cy, b = _neck_section(rig, top_z)
    neck_ring = mk.ellipse_ring(a - TORSO_NECK_INSET, b - TORSO_NECK_INSET, n, (0.0, cy, top_z))
    rings = [neck_ring] + [torso.ring(r[0], n) for r in torso.rows]
    groups = [1] * (len(rings) - 1)
    apex = (0.0, cy, top_z + 0.004)
    return mk.loft(rings, ("pole", apex), "flat", groups=groups)       # flat hem disc: its own group


# ---------------------------------------------------------------------------------------------------
# sailor collar, stripe, dickey (object collar)
# ---------------------------------------------------------------------------------------------------

def _collar_edges(rig: Rig, n1=2, n2=5, n3=6):
    """Corresponding outer / inner edge points of her left half, back centre -> V tip: ``(outer, inner,
    lift)`` with the lapel lift (SPEC.md §D.2) per column."""
    O, I = np.array(rig.collar_outer), np.array(rig.collar_inner)
    side = mk.catmull_rom(O[1:], 400)                 # O2 ... O9, smooth (the O2 corner stays square)
    # round the turn over the shoulder (O3 - O5): its radius must exceed the stripe's 18 mm offset
    k3 = int(np.argmin(np.linalg.norm(side - O[2], axis=1)))
    k5 = int(np.argmin(np.linalg.norm(side - O[4], axis=1)))
    w = COLLAR_SHOULDER_ROUNDING
    for _ in range(40):
        sm = side.copy()
        for k in range(k3, k5 + 1):
            sm[k] = side[max(k - w, 0):k + w + 1].mean(axis=0)
        side = sm
    inner = mk.catmull_rom(I, 400)                    # I1 ... I7
    k5 = int(np.argmin(np.linalg.norm(side - O[4], axis=1)))
    i2 = int(np.argmin(np.linalg.norm(inner - I[1], axis=1)))
    i3 = int(np.argmin(np.linalg.norm(inner - I[2], axis=1)))
    # the V-tip end: where the lapel is COLLAR_END_WIDTH wide
    lap_o, lap_i = side[k5:], inner[i3:]
    fs = np.linspace(0.0, 1.0, 400)
    po, pi = mk.polyline_at(lap_o, fs), mk.polyline_at(lap_i, fs)
    w = np.linalg.norm(po - pi, axis=1)
    f_end = float(fs[np.nonzero(w > COLLAR_END_WIDTH)[0][-1]])
    g = np.linspace(0.0, 1.0, n3 + 1)
    g = f_end * (1.0 - (1.0 - g) ** 1.25)             # a little denser toward the V tip
    outer = np.concatenate([mk.polyline_at(O[:2], np.linspace(0.0, 1.0, n1 + 1)),
                            mk.polyline_at(side[:k5 + 1], np.linspace(0.0, 1.0, n2 + 1))[1:],
                            mk.polyline_at(lap_o, g)[1:]])
    inn = np.concatenate([mk.polyline_at(inner[:i2 + 1], np.linspace(0.0, 1.0, n1 + 1)),
                          mk.polyline_at(inner[i2:i3 + 1], np.linspace(0.0, 1.0, n2 + 1))[1:],
                          mk.polyline_at(lap_i, g)[1:]])
    # lapel lift at the outer edge: 0 at O5, then SPEC.md's 10 / 9 / 6 mm at O6 / O7 / O8, 0 at the tip
    lift = np.zeros(len(outer))
    lift_pts = np.array([O[4], O[5], O[6], O[7], O[8]])
    lift_val = np.array([0.0, 0.010, 0.009, 0.006, 0.0])
    s_pts = np.array([np.argmin(np.linalg.norm(lap_o - p, axis=1)) for p in lift_pts], dtype=float)
    k0 = n1 + n2 + 1
    for j in range(k0, len(outer)):
        s = float(np.argmin(np.linalg.norm(lap_o - outer[j], axis=1)))
        lift[j] = float(np.interp(s, s_pts, lift_val))
    return outer, inn, lift


def _fold_band(band: mk.Mesh) -> mk.Mesh:
    """A :func:`meshkit.ridge_band` with its two top quads per step folded on their ridge diagonal and its
    bottom quad on the valley diagonal (review r2, F4): where the collar top twists along a long step (the
    back flap's side edge, 34 mm per step, and the shoulder turn) the bottom quad's fan otherwise bulged up
    through the 0.8 mm ridge and its back face showed (magenta) at the flap's lower side corner.

    Review r4: the bottom quad now folds on its ridge diagonal too (bulging down, toward the collar top it
    floats over; its fan triangles stay >= 0.22 mm above the collar).  On the r4 shoulder's steeper, more
    twisted turn the valley-folded bottom bulged up through the top faces at the front of the shoulder and
    showed its back (magenta) in the low head views (up to 17 px per view); all-ridge shows none in 40 head
    views and 7 flap / shoulder views."""
    return mk.fan_fold(band, [True] * band.n_faces)


def _collar(rig: Rig, torso: Torso, under: mk.Mesh | None = None, blouse: mk.Mesh | None = None):
    """The collar slab (underside on the blouse + gap, 4 mm thick, thinner at the edges), the floating pink
    stripe band, and the left inner edge (for the bib).  ``under``: the bib, which the underside clears;
    ``blouse``: the loft as built, which the underside clears by FACETED_CLEARANCE."""
    outer, inner, lift = _collar_edges(rig)
    mirror = np.array([-1.0, 1.0, 1.0])
    outer = np.concatenate([outer[:0:-1] * mirror, outer])
    inner = np.concatenate([inner[:0:-1] * mirror, inner])
    lift = np.concatenate([lift[:0:-1], lift])
    U = len(outer)
    s_out, s_in = rig.collar_stripe_inset, rig.collar_stripe_inset + rig.collar_stripe_width
    # in-surface inward offset of the outer edge, mitred at corners (the O2 corner stays square)
    off = np.zeros((U, 3))
    for j in range(U):
        nrm = torso.normal(outer[j])
        segs = []
        for a, b in ((j - 1, j), (j, j + 1)):
            if 0 <= a and b < U:
                t = outer[b] - outer[a]
                t /= np.linalg.norm(t)
                m = np.cross(nrm, t)
                if np.dot(m, inner[j] - outer[j]) < 0:
                    m = -m
                segs.append(m / np.linalg.norm(m))
        bis = segs[0] + segs[-1]
        bis /= np.linalg.norm(bis)
        off[j] = bis / max(0.5, float(np.dot(bis, segs[0])))
    vfrac = (0.0, None, None, 0.4, 0.72, 1.0)
    Q1, Q2 = np.zeros((U, 3)), np.zeros((U, 3))
    for j in range(U):
        w = float(np.linalg.norm(inner[j] - outer[j]))
        reach = s_in * float(np.linalg.norm(off[j]))
        k = min(1.0, 0.62 * w / reach)
        Q1[j] = outer[j] + k * s_out * off[j]
        Q2[j] = outer[j] + k * s_in * off[j]
    P = np.zeros((U, len(vfrac), 3))
    G = np.zeros((U, len(vfrac)))
    for j in range(U):
        q1, q2 = Q1[j], Q2[j]
        pts = [outer[j], q1, q2]
        for t in vfrac[3:]:
            pts.append(q2 + t * (inner[j] - q2))
        for i, p in enumerate(pts):
            v = i / (len(pts) - 1.0)
            P[j, i] = p
            G[j, i] = rig.collar_gap + lift[j] * (1.0 - v) ** 1.3
    grid0 = lay_on(torso, P, G)                         # on the analytic Torso: the collar's top stays here
    grid, G = lay_on(torso, P, G, mesh=blouse, return_gap=True)

    def thick(u, v):
        edge = min(v, 1.0 - v) * 5.0
        return COLLAR_EDGE_THICKNESS + (rig.collar_thickness - COLLAR_EDGE_THICKNESS) * min(1.0, edge)

    T = np.array([[thick(j / (U - 1.0), i / (len(vfrac) - 1.0)) for i in range(len(vfrac))] for j in range(U)])
    if under is not None:                               # review r3 (F4): the underside clears the bib
        away = (0.0, _neck_section(rig, torso.rows[0][0])[1], BIB_AWAY_Z)
        for _ in range(COLLAR_BIB_PASSES):
            rise = _inner_edge_raise(grid, under, away)
            if not np.any(rise > 1e-6):
                break
            grid, G = lay_on(torso, P, G + rise, mesh=blouse, return_gap=True)
    # the top stays where the analytic lay put it: the underside raised off the faceted blouse and the bib thins
    # the slab (no taller walls; the collar's look, its stripe and the hair fitted over it unchanged), down to
    # COLLAR_RAISED_MIN_THICKNESS, where the top rises with it
    slab_groups = {"front": 1, "back": 2, "rim": {"v0": 3, "v1": 4, "u0": 5, "u1": 5}}
    _col0, sides0 = mk.thicken(grid0, T, offset="outward", away_from=TORSO_CENTRE, groups=slab_groups,
                               return_sides=True)
    n0 = (sides0["front"] - grid0) / T[..., None]
    left = np.einsum("uvi,uvi->uv", sides0["front"] - grid, n0)
    top = np.where((left < COLLAR_RAISED_MIN_THICKNESS)[..., None], grid + COLLAR_RAISED_MIN_THICKNESS * n0,
                   sides0["front"])
    # ... and between the vertices too: on the twisted back-flap quads the top's (valley) and the underside's
    # (ridge) fan diagonals of a thinned slab crossed (its back showed, magenta, in the back views)
    quads = _grid_quads(U, len(vfrac))
    up0 = n0.reshape(-1, 3)
    under_fans = _lower_fans(grid.reshape(-1, 3), quads, up0).reshape(-1, 3)
    for _ in range(COLLAR_BIB_PASSES):
        need = _distance_deficit(top.reshape(-1, 3), quads, grid.reshape(-1, 3), under_fans,
                                 COLLAR_RAISED_MIN_THICKNESS, _lower_fans(top.reshape(-1, 3), quads, up0))
        need = need.reshape(top.shape[:2])
        if not np.any(need > 1e-6):
            break
        top = top + need[..., None] * n0
    col = mk.thicken(grid, T, offset="outward", away_from=TORSO_CENTRE, groups=slab_groups)   # vertices: top, bottom
    col = mk.Mesh(np.concatenate([top.reshape(-1, 3), grid.reshape(-1, 3)]), col.faces, col.groups)
    # groups: on the lapels (the dickey, the bib and the scarf lie under their edges, so the underside
    # silhouette would be hidden) the walls + underside are a second group and both edges always draw;
    # around the back and the shoulders the whole collar is one group: its edges draw once, as outlines
    lapel = np.array([outer[j][1] < COLLAR_LAPEL_Y for j in range(U)])
    face_col = []
    for u in range(U - 1):
        face_col += [u, u] * (len(vfrac) - 1) + [u, u]
    face_col += [0, U - 2] * (len(vfrac) - 1)
    groups = []
    for g, u in zip(col.groups, face_col):
        on_lapel = lapel[u] and lapel[u + 1]
        groups.append(1 if (g == 1 or not on_lapel) else 2)
    # review r2 (F5): the top quads' fan diagonals were ridges; seen from the side their facets bulged over
    # the inner edge's silhouette at the nape and chopped it into dashes.  Top faces fold on the valley
    # diagonal (every facet inside its edges), the underside on the ridge (away from the top: no crossing)
    col = mk.fan_fold(col, [g == 2 for g in col.groups]).with_groups(groups)
    nrm =_grid_normals(top, TORSO_CENTRE)[:, 1:3]
    base = top[:, 1:3] + rig.stripe_float * nrm
    stripe = _fold_band(mk.ridge_band(base[:, 0], base[:, 1], 0.5 * (nrm[:, 0] + nrm[:, 1]),
                                      rig.collar_stripe_relief, periodic=False))
    left_inner = np.array([torso.onto(p, 0.0) for p in _collar_edges(rig)[1]])
    return col, stripe, left_inner


def _inner_edge_raise(grid, under: mk.Mesh, away):
    """Per collar underside vertex ``(U, V)`` (``grid``, the laid underside), how much more it must rise so that
    every underside quad clears the top of ``under`` (the bib: its faces whose normal points away from ``away``)
    by COLLAR_BIB_CLEARANCE, by the exact triangle-triangle distance (both fans of each quad; a quad's deficit
    goes to its four corners).  Review r3 (F4): the bib reaches 9 mm under the collar and its chords are lifted
    1.3 - 3 mm off the blouse there, while the collar's inner edge chords (up to 36 mm long beside the neck) sag to
    1.2 mm: the bib cut through the inner wall, hid the wall's lower edge (the outline beside the neck) in the
    front views and chopped the lapel's inner edge into dashes.  Measured over the whole underside (not only the
    inner-edge chords, probed vertically: the strip beside the inner edge still touched the bib where its top
    is steep next to the neck; acceptance clear:body.collar^body.bib)."""
    U, V = grid.shape[:2]
    nb, _ = mk.face_normals(under)
    cb = np.array([under.vertices[f].mean(axis=0) for f in under.faces])
    top = np.einsum("fi,fi->f", nb, cb - np.asarray(away, dtype=np.float64)) > 0.0
    tb, owner = mk.triangulate(under.faces)
    need = _distance_deficit(grid.reshape(-1, 3), _grid_quads(U, V), under.vertices, tb[top[owner]],
                             COLLAR_BIB_CLEARANCE)
    return need.reshape(U, V)


def _dickey(rig: Rig, torso: Torso):
    """White V filler (1.5 mm), 1.1 mm above the blouse, its top edge horizontal at bib_bottom_z, its
    corners and point tucked under the lapels."""
    zt, zb = rig.bib_bottom_z, rig.dickey_corners[1][2]
    zs = np.linspace(zt, zb, 5)
    cols = []
    for u in np.linspace(-1.0, 1.0, 5):
        col = []
        for z in zs:
            t = (zt - z) / (zt - zb)
            half = rig.dickey_corners[0][0] * (1.0 - t) + 0.003 * t
            hw, yf, yb = torso.section(z)
            p = np.array([u * half, yf, z])
            col.append(torso.onto(p, rig.dickey_lift))
        cols.append(col)
    grid = np.array(cols)
    return mk.thicken(grid, rig.dickey_thickness, offset="outward", away_from=(0.0, 0.0, 1.13), groups="single")


# ---------------------------------------------------------------------------------------------------
# scarf ribbons, ring + stripes, tips
# ---------------------------------------------------------------------------------------------------

def _ribbon(rig: Rig, torso: Torso, side: int, blouse: mk.Mesh):
    """A scarf ribbon: a lens section swept along ``rig.scarf_path`` (SPEC.md §D.3) from under the lapel into the
    ring, its stations lifted where the section comes closer than FACETED_CLEARANCE to the ``blouse`` loft."""
    S = np.array(rig.scarf_path) * [side, 1.0, 1.0]
    n = len(S)
    s = np.linspace(0.0, 1.0, n)
    w = np.interp(s, [0.0, 0.8, 1.0], [rig.scarf_width[0], rig.scarf_width[1], rig.scarf_width[1]])
    w[0] = rig.scarf_start_width                        # review r3 (F7): stays under the lapel
    w[-2:] = rig.scarf_ring_width                       # S4, S5: gathered into the ring
    th = np.interp(s, [0.0, 0.8, 1.0], [rig.scarf_thickness[0], rig.scarf_thickness[1], rig.scarf_thickness[1]])
    th[0] = rig.scarf_start_thickness
    for k, dz in enumerate(rig.scarf_tuck_z):            # S0, S1 lowered under the lifted lapel
        S[k, 2] += dz
    P = S.copy()
    for k in range(n - 1):                           # S5 stays inside the ring
        P[k] = torso.onto(S[k], 0.001 + 0.5 * th[k])
    m = 9
    path = mk.catmull_rom(P, m)
    ss = np.linspace(0.0, 1.0, m)
    W = np.interp(ss, s, w)
    TH = np.interp(ss, s, th)
    nrm = np.array([torso.normal(p) for p in path])
    M = RIBBON_PROFILE_POINTS
    rib = mk.sweep(path, width=W, thickness=TH, profile=mk.profile_lens(M, 0.55), normals=nrm, start="flat",
                   end="flat", cap_groups=(1, 1))
    # laid on the analytic Torso, the lens's lower edge dipped 1.3 mm into the faceted loft over the front of the
    # shoulder: lift the section there along the station normal, per lateral position (profile points k and M - k
    # together, so the section keeps its thickness and its other edge stays).  The stations up to S1 (tucked under
    # the lapel, scarf_tuck_z: lifted, the ribbon's edge came out through the lapel's top) and S5 (inside the ring)
    # stay, so the end caps stay flat.
    rings = rib.vertices.reshape(m, M, 3)               # flat caps: the vertices are the sections
    up = np.repeat(nrm[:, None, :], M, axis=1)
    lateral = np.minimum(np.arange(M), M - np.arange(M))
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)]) / seg.sum()
    tucked = arc <= arc[int(np.argmin(np.linalg.norm(path - P[len(rig.scarf_tuck_z) - 1], axis=1)))] + 1e-9
    for _ in range(RIBBON_LIFT_PASSES):
        need = faceted_deficit(blouse, rings, up, FACETED_CLEARANCE, periodic_v=True)
        col = np.zeros((m, M // 2 + 1))
        for k in range(M):
            col[:, lateral[k]] = np.maximum(col[:, lateral[k]], need[:, k])
        lift = col[:, lateral]
        lift[tucked] = 0.0
        lift[-1] = 0.0
        if not np.any(lift > 1e-6):
            break
        rings = rings + lift[..., None] * up
    return mk.Mesh(rings.reshape(-1, 3), rib.faces, rib.groups)


def _ring(rig: Rig):
    # r2 F11 (the high-angle frame / the user's drawing): a prominent band about as wide as the scarf there and taller
    # than it is wide, with two clearly separate 4 mm stripes (rig.ring_size / ring_stripe_*)
    c = np.array(rig.ring_center)
    w, d, h = rig.ring_size
    r = rig.ring_corner_radius
    n = RING_POINTS
    zs = (c[2] - (0.5 * h - r), c[2] + (0.5 * h - r))
    rings = [mk.rounded_rect_ring(w, d, r, n, (c[0], c[1], z)) for z in zs]
    box = mk.loft(rings, ("dome", r, 1), ("dome", r, 1))
    # the stripe stations: the ring's own polygon vertices, each moved stripe_float out along the rounded
    # rectangle's normal there (a separately resampled, larger rounded rectangle put its corner stations 0.32 mm
    # off the ring's corner chords; acceptance clear:body.ring_stripe*^body.ring)
    ring_xy = mk.rounded_rect_ring(w, d, r, n)[:, :2]
    hx, hy = 0.5 * w - r, 0.5 * d - r
    # from the nearest point of the inner rectangle (the arc centres): axis-aligned on a flat, radial on an arc
    out_xy = ring_xy - np.stack([np.clip(ring_xy[:, 0], -hx, hx), np.clip(ring_xy[:, 1], -hy, hy)], axis=1)
    out_xy /= np.linalg.norm(out_xy, axis=1)[:, None]
    stripes = []
    for zc in rig.ring_stripe_z:
        hh = 0.5 * rig.ring_stripe_height
        g = rig.stripe_float
        lo, hi = (np.column_stack([c[0] + ring_xy[:, 0] + g * out_xy[:, 0], c[1] + ring_xy[:, 1] + g * out_xy[:, 1],
                                   np.full(n, zc + dz)]) for dz in (-hh, hh))
        out = 0.5 * (lo + hi) - np.array([c[0], c[1], zc])
        out[:, 2] = 0.0
        stripes.append(mk.ridge_band(lo, hi, out, rig.ring_stripe_relief))
    return box, stripes


def _tip(rig: Rig, torso: Torso, side: int):
    """A flat 4 mm blade below the ring: root inside the ring, ``scarf_tip_angle_deg`` outward (toward
    ``scarf_tip_point``), widest ``scarf_tip_max_width`` (a broad fan), a 45 deg oblique cut with the point on
    the outer side (SPEC.md §D.3)."""
    if side > 0:
        root, point, front = np.array(rig.scarf_tip_root), np.array(rig.scarf_tip_point), rig.scarf_tip_front_offset
    else:
        root = np.array(rig.scarf_tip_root_right)
        point = np.array([-rig.scarf_tip_point[0], rig.scarf_tip_root_right[1], rig.scarf_tip_point[2]])
        front = 0.0
    L = rig.scarf_tip_length
    a = point - root
    a[1] = 0.0
    a /= np.linalg.norm(a)                            # along the blade (in the frontal plane)
    o = np.array([-a[2], 0.0, a[0]]) * side           # across, toward the outer side
    if o[0] * side < 0:
        o = -o
    wmax, at = rig.scarf_tip_max_width
    w0 = rig.scarf_tip_root_width
    # 2D outline (s along, t across; t > 0 = outer side)
    cut_s = at * L                                    # the inner edge ends at the widest station
    inner = [(0.0, -0.5 * w0), (0.35 * L, -0.5 * (w0 + 0.75 * (wmax - w0))), (cut_s, -0.5 * wmax)]
    tip = (L, 0.004)
    outer = [(0.0, 0.5 * w0), (0.35 * L, 0.5 * (w0 + 0.75 * (wmax - w0))), (cut_s, 0.5 * wmax),
             (0.5 * (cut_s + L), 0.6 * 0.5 * wmax)]
    # the oblique cut: inner corner -> tip at 45 deg, sampled; the outer edge to the tip
    cut = [(cut_s + f * (L - cut_s), -0.5 * wmax + f * (tip[1] + 0.5 * wmax)) for f in (0.5,)]
    A = inner + cut + [tip]
    B = outer + [tip]
    n = max(len(A), len(B))
    A2 = mk.resample_polyline(np.array(A), n) if len(A) != n else np.array(A)
    B2 = mk.resample_polyline(np.array(B), n) if len(B) != n else np.array(B)

    o_root = np.array([o[0], 0.0, 0.0])               # the root edge is level: both root corners at root z

    def place(st):
        # the root (s = 0) edge is level, so the whole root cap sits in the ring's ~3 mm bottom-cap window
        # (above the dome, below its side wall; acceptance join:body.scarf_tip_*~body.ring)
        p = root + st[0] * a + st[1] * (o_root if st[0] == 0.0 else o)
        hw, yf, yb = torso.section(p[2])
        q = torso.onto(np.array([p[0], yf, p[2]]), 0.0)
        y_surface = q[1] - 0.0015 - 0.5 * rig.scarf_tip_thickness - front
        k = min(1.0, st[0] / 0.03)
        p[1] = (1.0 - k) * min(root[1], y_surface) + k * y_surface
        return p

    PA = np.array([place(p) for p in A2])
    PB = np.array([place(p) for p in B2])
    PB[-1] = PA[-1]
    return mk.strip_plate(PA, PB, (0.0, -1.0, 0.0), rig.scarf_tip_thickness, offset="centre", tip=True)


# ---------------------------------------------------------------------------------------------------
# skirt + under-skirt (object skirt, material skirt)
# ---------------------------------------------------------------------------------------------------

def _skirt(rig: Rig):
    """Pleated skirt shell (SPEC.md §D.5): smooth from the waist (0.95) down to pleat_top_z, below it 16 knife
    pleats (crest / valley sawtooth, depth 0 at pleat_top_z -> pleat_depth at the hem), a 3 mm
    hem rim and a short inner facing that rises to ``rig.skirt_ceiling_z``, where a ceiling closes the shell level
    with the under-skirt's bottom (from below the legs and the under-skirt still show).  Groups: the two
    faces of each pleat 1 / 2 from the waist to the hem (the pressed pleat lines run up to the blouse
    hem; above pleat_top_z they lie on the smooth surface), the hidden waist cap 3, hem rim + facing +
    ceiling 4; so the 32 crest / valley creases and the hem always draw, and nothing inside adds lines."""
    n = rig.skirt_pleats
    span = 2.0 * np.pi / n
    ang = np.concatenate([[k * span, (k + 0.8) * span] for k in range(n)])
    M = 2 * n
    e = rig.skirt_exponent
    ct, st = np.cos(ang), np.sin(ang)

    def offset(P, inset):
        nx = np.roll(P, -1, axis=0) - np.roll(P, 1, axis=0)
        nv = np.stack([nx[:, 1], -nx[:, 0]], axis=1)
        nv /= np.linalg.norm(nv, axis=1)[:, None]
        return P - inset * nv

    def ring(z, inset):
        hw, yf, yb = rig.skirt_section(z)
        depth = rig.pleat_depth * min(1.0, max(0.0, (rig.pleat_top_z - z) / (rig.pleat_top_z - rig.skirt_hem_z)))
        x = hw * np.sign(ct) * np.abs(ct) ** (2.0 / e)
        y = np.where(st > 0, yb, -yf) * np.sign(st) * np.abs(st) ** (2.0 / e)
        rad = np.hypot(x, y)
        k = 1.0 - depth * (np.arange(M) % 2) / rad
        P = np.stack([x * k, y * k], axis=1)
        if inset:
            nx = np.roll(P, -1, axis=0) - np.roll(P, 1, axis=0)
            nv = np.stack([nx[:, 1], -nx[:, 0]], axis=1)
            nv /= np.linalg.norm(nv, axis=1)[:, None]
            P = P - inset * nv
        return np.column_stack([P, np.full(M, z)])

    zw, zp, zh = rig.skirt_waist_z, rig.pleat_top_z, rig.skirt_hem_z
    # the facing's top ring: on the straight pleated section of the mesh (not the curved rows) + inset
    t = (zp - rig.skirt_ceiling_z) / (zp - zh)
    mid = (1.0 - t) * ring(zp, 0.0) + t * ring(zh, 0.0)
    # (7 mm in: the twisted pleat quads' fan triangles dip up to ~3 mm inside the bilinear surface)
    ceil_ring = np.column_stack([offset(mid[:, :2], SKIRT_FACING_INSET), np.full(M, rig.skirt_ceiling_z)])
    rings = [ring(zw, 0.0), ring(zp, 0.0), ring(zh, 0.0), ring(zh, rig.skirt_thickness), ceil_ring]
    V = np.concatenate(rings + [np.array([[0.0, 0.0, zw + 0.002], [0.0, 0.005, rig.skirt_ceiling_z + 0.004]])])
    top, ceil = 5 * M, 5 * M + 1

    def v(r, j):
        return r * M + j % M

    faces, groups = [], []
    for j in range(M):
        ab = 1 + (j % 2)
        faces.append([top, v(0, j + 1), v(0, j)])                                   # waist cap (hidden)
        faces.append([v(0, j), v(0, j + 1), v(1, j + 1), v(1, j)])                  # yoke
        faces.append([v(1, j), v(1, j + 1), v(2, j + 1), v(2, j)])                  # pleat face
        faces.append([v(2, j), v(2, j + 1), v(3, j + 1), v(3, j)])                  # hem rim
        faces.append([v(3, j), v(3, j + 1), v(4, j + 1), v(4, j)])                  # inner facing
        faces.append([ceil, v(4, j), v(4, j + 1)])                                  # ceiling
        groups += [1, ab, ab, 4, 4, 4]           # waist cap: group 1 (half its rim is a hidden feature)
    skirt = mk._outward(mk.Mesh(V, faces, groups))
    # review r4 (F5): the pleat faces twist (depth 0 at pleat_top_z, pleat_depth at the hem); castplane
    # decides a polygon's facing by its Newell normal but occludes with its fan triangles, so near the
    # skirt's side outline a crease lost ~10 mm or drew dotted.  Split those quads into their two fan
    # triangles (same diagonal, same shape; +32 polygons).
    return mk.split_twisted(skirt, SKIRT_TWIST_SPLIT_DEG, only=[k % 6 == 2 for k in range(len(faces))])


def _underskirt(rig: Rig):
    out = []
    k = 16
    for z, hw, yf, yb in UNDERSKIRT:
        t = 2.0 * np.pi * np.arange(k) / k
        ct, st = np.cos(t), np.sin(t)
        x = hw * np.sign(ct) * np.abs(ct) ** (2.0 / rig.torso_exponent)
        y = np.where(st > 0, yb, -yf) * np.sign(st) * np.abs(st) ** (2.0 / rig.torso_exponent)
        out.append(np.stack([x, y, np.full(k, z)], axis=1))
    return mk.loft(out, "flat", "flat", cap_groups=(1, 1))


# ---------------------------------------------------------------------------------------------------

def build(rig: Rig):
    """Parts of :data:`REGIONS` for ``rig``."""
    torso = torso_model(rig)
    parts = []
    blouse = _blouse(rig, torso)
    bib = _bib(rig, torso, np.array([torso.onto(p, 0.0) for p in _collar_edges(rig)[1]]), blouse)
    col, stripe, left_inner = _collar(rig, torso, under=bib, blouse=blouse)
    parts.append(Part("body.neck", "skin", _neck(rig), "neck"))
    parts.append(Part("body.bib", "skin", mk.split_twisted(bib, BIB_TWIST_SPLIT_DEG), "neck"))
    parts.append(Part("body.blouse", "uniform", blouse, "torso"))
    parts.append(Part("body.collar", "collar", col, "collar"))
    parts.append(Part("body.collar_stripe", "uniform", stripe, "collar"))
    parts.append(Part("body.dickey", "collar", _dickey(rig, torso), "collar"))
    for side in SIDES:
        parts.append(Part(f"body.scarf_ribbon_{_side_name(side)}", "scarf", _ribbon(rig, torso, side, blouse),
                          "scarf"))
    for side in (-1, 1):                              # tip A (her right, behind) first, then tip B
        parts.append(Part(f"body.scarf_tip_{_side_name(side)}", "scarf", _tip(rig, torso, side), "scarf"))
    box, stripes = _ring(rig)
    parts.append(Part("body.ring", "collar", box, "scarf", obj="ring"))
    for k, s in enumerate(stripes):
        parts.append(Part(f"body.ring_stripe{k}", "uniform", s, "scarf", obj="ring"))
    parts.append(Part("body.skirt", "skirt", _skirt(rig), "skirt"))
    parts.append(Part("body.underskirt", "skirt", _underskirt(rig), "skirt"))
    return parts
