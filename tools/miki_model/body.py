"""Neck, sailor top, collar, scarf + ring and skirt of the Miki model (owner: body agent).

Part contract (see ``assemble.py`` and the toolkit guide): :func:`build` takes the
:class:`~miki_model.rig.Rig` and returns a list of :class:`~miki_model.meshkit.Part` covering **all** of
:data:`REGIONS`.  Objects / materials (``Part(name, material, mesh, region, obj=...)``): neck + decollete
bib -> head (skin); torso -> blouse (uniform); collar, dickey -> collar (collar), collar stripe -> collar
(uniform); scarf ribbons, tips -> scarf (scarf); ring -> ``obj="ring"`` (collar), ring stripes ->
``obj="ring"`` (uniform); skirt, under-skirt -> skirt (skirt).

How the lines come out (castplane draws feature edges always and smooth edges only on the camera
silhouette; spec §F):

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
#: ``(z, hw)``: through the collar's I3 (x 0.042 at z 1.213) and O5 (x 0.118 at z 1.191) (spec §D.2);
#: yf / yb are interpolated linearly between the rig's 1.215 and 1.180 rows.
SHOULDER_HW = ((1.215, 0.031), (1.211, 0.052), (1.202, 0.085), (1.191, 0.118), (1.180, 0.150))
TORSO_RING_POINTS = 24                 # points per blouse section
TORSO_NECK_INSET = 0.004               # the blouse's top ring sits this far inside the neck
COLLAR_END_WIDTH = 0.004               # each lapel ends at the V tip with this width (the halves don't touch)
COLLAR_STRIPE_SMOOTHING = 0            # Laplacian passes on the stripe border rows (shoulder turn)
COLLAR_SMOOTH_ABOVE_Z = 1.10           # ... only where the outer edge is above this (flap top, shoulder)
COLLAR_SHOULDER_ROUNDING = 12          # moving-average half window (samples of 400) rounding the O3-O5 turn
COLLAR_EDGE_THICKNESS = 0.0030        # the 4 mm collar thins to this at its outer / inner edges
STRIPE_FLOAT = 0.00025                 # decal bands float this far above the surface they decorate
NECK_POINTS = 16
BIB_COLUMNS = 13
BIB_LIFT = 0.0015                      # spec 1 mm: the chords between columns sag ~1 mm on the curved chest
DICKEY_LIFT = 0.0019                   # the dickey's back face: above the bib, so its top edge draws
BIB_SINK = 0.002                       # the bib's top row lies this far inside the neck surface
DICKEY_CORNER_X = 0.034                # dickey top corners pushed under the lapels (spec 0.024 lies in the V)
DICKEY_BOTTOM_Z = 1.087                # dickey bottom point under the collar's V tip (spec 1.096)
SKIRT_ROWS_Z = (0.950, 0.900, 0.860, 0.780, 0.450)   # pleated band 0.78 -> 0.45 is straight (one section)
UNDERSKIRT = ((0.950, 0.100, -0.060, 0.055), (0.780, 0.150, -0.075, 0.090), (0.700, 0.157, -0.081, 0.092))


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


def lay_on(torso: Torso, P, gap, margin=0.0006, passes=6):
    """Grid ``P`` ``(U, V, 3)`` laid on the blouse: each point moved onto the surface plus its ``gap``
    ``(U, V)``; then, wherever a quad's centre or an edge midpoint (a chord of the faceted grid) dips closer
    than ``margin`` to the curved surface, the gaps of its corners grow until it clears."""
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
                tests = [(quad, 0.25 * sum(grid[a, b] for a, b in quad))]
                tests += [([quad[k], quad[(k + 1) % 4]], 0.5 * (grid[quad[k]] + grid[quad[(k + 1) % 4]]))
                          for k in range(4)]
                for corners, c in tests:
                    d = margin - sd(c)
                    if d > 0:
                        for a, b in corners:
                            bump[a, b] = max(bump[a, b], d)
        if not np.any(bump > 1e-6):
            break
        G += bump
        grid = base + G[..., None] * nrm
    return grid


def torso_model(rig: Rig) -> Torso:
    """The blouse rows: the rig's rows with the convex shoulder of :data:`SHOULDER_HW` in between."""
    br = list(rig.blouse_rows)
    y0, y1 = rig.neck_y
    # the neck-root row inside the neck's front / back (the rig's yf -0.026 sticks 4 mm out of the neck)
    br[0] = (br[0][0], br[0][1], max(br[0][2], y0 + 0.001), min(br[0][3], y1 - 0.001))
    top, sh = br[0], br[1]
    rows = []
    for z, hw in SHOULDER_HW:
        t = (top[0] - z) / (top[0] - sh[0])
        rows.append((z, hw, top[2] + t * (sh[2] - top[2]), top[3] + t * (sh[3] - top[3])))
    rows += br[2:]
    return Torso(rows, rig.torso_exponent)


# ---------------------------------------------------------------------------------------------------
# neck + bib (object head, skin)
# ---------------------------------------------------------------------------------------------------

def _neck(rig: Rig):
    y0, y1 = rig.neck_y
    cy, b = 0.5 * (y0 + y1), 0.5 * (y1 - y0)
    rings = [mk.ellipse_ring(rig.neck_half_width, b, NECK_POINTS, (0.0, cy, z)) for z in rig.neck_z]
    return mk.loft(rings, "flat", "flat", cap_groups=(1, 1))


def _neck_point(rig: Rig, phi, z, sink=0.0):
    y0, y1 = rig.neck_y
    cy, b = 0.5 * (y0 + y1), 0.5 * (y1 - y0)
    a = rig.neck_half_width
    return np.array([(a - sink) * math.cos(phi), cy + (b - sink) * math.sin(phi), z])


def _bib(rig: Rig, torso: Torso, inner_edge):
    """Skin sheet filling the collar's V opening: columns around the front half of the neck, each from
    inside the neck out to under the collar's inner edge (or under the dickey's top edge at the front),
    lying ``bib_lift`` above the blouse."""
    cy = 0.5 * sum(rig.neck_y)
    ie = np.asarray(inner_edge)                       # her left inner edge I3 ... I7 (dense), on the blouse
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
        out = e + 0.006 * np.array([math.cos(phi), math.sin(phi), -0.6])   # 6 mm under the collar
        if out[2] < bottom:
            out = out + (bottom - out[2]) / (e[2] + 0.02 - out[2]) * (e + np.array([0, 0, 0.02]) - out)
            out[2] = bottom
        # the top row lies on the blouse inside the neck (no fin standing out of the neck surface)
        # the top row: inside the neck at the height where the blouse meets the neck, so the bib leaves
        # the neck flush with the blouse (no fin standing out of the neck surface)
        inner = _neck_point(rig, phi, torso.rows[0][0] + BIB_LIFT, BIB_SINK)
        rows.append([inner] + [inner + t * (out - inner) for t in (0.15, 0.4, 0.7, 1.0)])
    P = np.array(rows)
    grid = np.concatenate([P[:, :1], lay_on(torso, P[:, 1:], BIB_LIFT, margin=0.0008)], axis=1)
    return mk.thicken(grid, 0.0015, offset="inward", away_from=(0.0, cy, 1.15), groups="single")


# ---------------------------------------------------------------------------------------------------
# blouse (object blouse, uniform)
# ---------------------------------------------------------------------------------------------------

def _blouse(rig: Rig, torso: Torso):
    n = TORSO_RING_POINTS
    y0, y1 = rig.neck_y
    top_z = rig.neck_base_z + 0.027
    neck_ring = mk.ellipse_ring(rig.neck_half_width - TORSO_NECK_INSET, 0.5 * (y1 - y0) - TORSO_NECK_INSET, n,
                                (0.0, 0.5 * (y0 + y1), top_z))
    rings = [neck_ring] + [torso.ring(r[0], n) for r in torso.rows]
    groups = [1] * (len(rings) - 1)
    apex = (0.0, 0.5 * (y0 + y1), top_z + 0.004)
    return mk.loft(rings, ("pole", apex), "flat", groups=groups)       # flat hem disc: its own group


# ---------------------------------------------------------------------------------------------------
# sailor collar, stripe, dickey (object collar)
# ---------------------------------------------------------------------------------------------------

def _collar_edges(rig: Rig, n1=2, n2=5, n3=7):
    """Corresponding outer / inner edge points of her left half, back centre -> V tip: ``(outer, inner,
    lift)`` with the lapel lift (spec §D.2) per column."""
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
    # lapel lift at the outer edge: 0 at O5, then the spec's 10 / 9 / 6 mm at O6 / O7 / O8, 0 at the tip
    lift = np.zeros(len(outer))
    lift_pts = np.array([O[4], O[5], O[6], O[7], O[8]])
    lift_val = np.array([0.0, 0.010, 0.009, 0.006, 0.0])
    s_pts = np.array([np.argmin(np.linalg.norm(lap_o - p, axis=1)) for p in lift_pts], dtype=float)
    k0 = n1 + n2 + 1
    for j in range(k0, len(outer)):
        s = float(np.argmin(np.linalg.norm(lap_o - outer[j], axis=1)))
        lift[j] = float(np.interp(s, s_pts, lift_val))
    return outer, inn, lift


def _collar(rig: Rig, torso: Torso):
    """The collar slab (underside on the blouse + gap, 4 mm thick, thinner at the edges), the floating pink
    stripe band, and the left inner edge (for the bib)."""
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
    vfrac = (0.0, None, None, 0.5, 0.8, 1.0)
    Q1, Q2 = np.zeros((U, 3)), np.zeros((U, 3))
    for j in range(U):
        w = float(np.linalg.norm(inner[j] - outer[j]))
        reach = s_in * float(np.linalg.norm(off[j]))
        k = min(1.0, 0.62 * w / reach)
        Q1[j] = outer[j] + k * s_out * off[j]
        Q2[j] = outer[j] + k * s_in * off[j]
    # where the outline turns toward the neck over the shoulder (O3 - O5) its radius is below the 18 mm
    # offset and the offset rows fold: smooth them along the collar (the square O2 corners stay fixed)
    corner = np.array(rig.collar_outer[1])
    corners = [j for j in range(U) if np.linalg.norm(np.abs(outer[j]) - np.abs(corner)) < 1e-6]
    fixed = {0, U - 1} | {j + d for j in corners for d in (-1, 0, 1)}
    fixed |= {j for j in range(U) if outer[j][2] < COLLAR_SMOOTH_ABOVE_Z}
    for Q in (Q1, Q2):
        for _ in range(COLLAR_STRIPE_SMOOTHING):
            S = Q.copy()
            for j in range(1, U - 1):
                if j not in fixed:
                    S[j] = 0.5 * Q[j] + 0.25 * (Q[j - 1] + Q[j + 1])
            Q[:] = S
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
    grid = lay_on(torso, P, G)

    def thick(u, v):
        edge = min(v, 1.0 - v) * 5.0
        return COLLAR_EDGE_THICKNESS + (rig.collar_thickness - COLLAR_EDGE_THICKNESS) * min(1.0, edge)

    col, sides = mk.thicken(grid, thick, offset="outward", away_from=(0.0, 0.012, 1.12),
                            groups={"front": 1, "back": 2, "rim": 2}, return_sides=True)
    top = sides["front"]
    nrm = _grid_normals(top, (0.0, 0.012, 1.12))[:, 1:3]
    base = top[:, 1:3] + STRIPE_FLOAT * nrm
    stripe = mk.ridge_band(base[:, 0], base[:, 1], 0.5 * (nrm[:, 0] + nrm[:, 1]), rig.collar_stripe_relief,
                           periodic=False)
    left_inner = np.array([torso.onto(p, 0.0) for p in _collar_edges(rig)[1]])
    return col, stripe, left_inner


def _dickey(rig: Rig, torso: Torso):
    """White V filler (1.5 mm), 1.1 mm above the blouse, its top edge horizontal at bib_bottom_z, its
    corners and point tucked under the lapels."""
    zt, zb = rig.bib_bottom_z, DICKEY_BOTTOM_Z
    zs = np.linspace(zt, zb, 5)
    cols = []
    for u in np.linspace(-1.0, 1.0, 5):
        col = []
        for z in zs:
            t = (zt - z) / (zt - zb)
            half = DICKEY_CORNER_X * (1.0 - t) + 0.003 * t
            hw, yf, yb = torso.section(z)
            p = np.array([u * half, yf, z])
            col.append(torso.onto(p, DICKEY_LIFT))
        cols.append(col)
    grid = np.array(cols)
    return mk.thicken(grid, rig.dickey_thickness, offset="outward", away_from=(0.0, 0.0, 1.13), groups="single")


# ---------------------------------------------------------------------------------------------------
# scarf ribbons, ring + stripes, tips
# ---------------------------------------------------------------------------------------------------

def _ribbon(rig: Rig, torso: Torso, side: int):
    S = np.array(rig.scarf_path) * [side, 1.0, 1.0]
    n = len(S)
    s = np.linspace(0.0, 1.0, n)
    w = np.interp(s, [0.0, 0.8, 1.0], [rig.scarf_width[0], rig.scarf_width[1], rig.scarf_width[1]])
    th = np.interp(s, [0.0, 0.8, 1.0], [rig.scarf_thickness[0], rig.scarf_thickness[1], rig.scarf_thickness[1]])
    P = S.copy()
    for k in range(n - 1):                           # S5 stays inside the ring
        P[k] = torso.onto(S[k], 0.001 + 0.5 * th[k])
    m = 9
    path = mk.catmull_rom(P, m)
    ss = np.linspace(0.0, 1.0, m)
    W = np.interp(ss, s, w)
    TH = np.interp(ss, s, th)
    nrm = np.array([torso.normal(p) for p in path])
    return mk.sweep(path, width=W, thickness=TH, profile=mk.profile_lens(8, 0.55), normals=nrm,
                    start="flat", end="flat", cap_groups=(1, 1))


def _ring(rig: Rig):
    c = np.array(rig.ring_center)
    w, d, h = rig.ring_size
    r = rig.ring_corner_radius
    n = 12
    zs = (c[2] - (0.5 * h - r), c[2] + (0.5 * h - r))
    rings = [mk.rounded_rect_ring(w, d, r, n, (c[0], c[1], z)) for z in zs]
    box = mk.loft(rings, ("dome", r, 1), ("dome", r, 1))
    stripes = []
    for zc in rig.ring_stripe_z:
        hh = 0.5 * rig.ring_stripe_height
        g = STRIPE_FLOAT
        lo, hi = (mk.rounded_rect_ring(w + 2 * g, d + 2 * g, r + g, n, (c[0], c[1], zc + dz)) for dz in (-hh, hh))
        out = 0.5 * (lo + hi) - np.array([c[0], c[1], zc])
        out[:, 2] = 0.0
        stripes.append(mk.ridge_band(lo, hi, out, rig.ring_stripe_relief))
    return box, stripes


def _tip(rig: Rig, torso: Torso, side: int):
    """A flat 4 mm blade below the ring: root inside the ring, 15 deg outward, widest 0.034 at 70 %,
    a 45 deg oblique cut with the point on the outer side (spec §D.3)."""
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

    def place(st):
        p = root + st[0] * a + st[1] * o
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
    """Thin pleated tube: 16 knife pleats (crest / valley sawtooth, depth 0 at pleat_top_z -> pleat_depth
    at the hem), the inner surface skirt_thickness inside, open bottom.  The two faces of each pleat
    alternate groups 1 / 2 on the outer surface, the rims and the inner surface, so every crease draws."""
    n = rig.skirt_pleats
    span = 2.0 * np.pi / n
    ang = np.concatenate([[k * span, (k + 0.8) * span] for k in range(n)])
    M = 2 * n
    e = rig.skirt_exponent
    outer, inner = [], []
    for z in SKIRT_ROWS_Z:
        hw, yf, yb = rig.skirt_section(z)
        depth = rig.pleat_depth * min(1.0, max(0.0, (rig.pleat_top_z - z) / (rig.pleat_top_z - rig.skirt_hem_z)))
        ct, st = np.cos(ang), np.sin(ang)
        x = hw * np.sign(ct) * np.abs(ct) ** (2.0 / e)
        y = np.where(st > 0, yb, -yf) * np.sign(st) * np.abs(st) ** (2.0 / e)
        rad = np.hypot(x, y)
        k = 1.0 - depth * (np.arange(M) % 2) / rad
        P = np.stack([x * k, y * k], axis=1)
        # 2D vertex normals of the sawtooth (outward) for the inner surface
        nx = np.roll(P, -1, axis=0) - np.roll(P, 1, axis=0)
        nv = np.stack([nx[:, 1], -nx[:, 0]], axis=1)
        nv /= np.linalg.norm(nv, axis=1)[:, None]
        Q = P - rig.skirt_thickness * nv
        outer.append(np.column_stack([P, np.full(M, z)]))
        inner.append(np.column_stack([Q, np.full(M, z)]))
    R = len(SKIRT_ROWS_Z)
    V = np.concatenate(outer + inner)

    def o(r, j):
        return r * M + j % M

    def i_(r, j):
        return R * M + r * M + j % M

    faces, groups = [], []
    for j in range(M):
        g = 1 + (j % 2)
        for r in range(R - 1):
            faces.append([o(r, j), o(r + 1, j), o(r + 1, j + 1), o(r, j + 1)])
            faces.append([i_(r, j), i_(r, j + 1), i_(r + 1, j + 1), i_(r + 1, j)])
            groups += [g, g]
        faces.append([o(0, j), o(0, j + 1), i_(0, j + 1), i_(0, j)])                 # waist rim
        faces.append([o(R - 1, j), i_(R - 1, j), i_(R - 1, j + 1), o(R - 1, j + 1)])  # hem rim
        groups += [g, g]
    return mk._outward(mk.Mesh(V, faces, groups))


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
    col, stripe, left_inner = _collar(rig, torso)
    parts.append(Part("body.neck", "skin", _neck(rig), "neck"))
    parts.append(Part("body.bib", "skin", _bib(rig, torso, left_inner), "neck"))
    parts.append(Part("body.blouse", "uniform", _blouse(rig, torso), "torso"))
    parts.append(Part("body.collar", "collar", col, "collar"))
    parts.append(Part("body.collar_stripe", "uniform", stripe, "collar"))
    parts.append(Part("body.dickey", "collar", _dickey(rig, torso), "collar"))
    for side in SIDES:
        parts.append(Part(f"body.scarf_ribbon_{_side_name(side)}", "scarf", _ribbon(rig, torso, side), "scarf"))
    for side in (-1, 1):                              # tip A (her right, behind) first, then tip B
        parts.append(Part(f"body.scarf_tip_{_side_name(side)}", "scarf", _tip(rig, torso, side), "scarf"))
    box, stripes = _ring(rig)
    parts.append(Part("body.ring", "collar", box, "scarf", obj="ring"))
    for k, s in enumerate(stripes):
        parts.append(Part(f"body.ring_stripe{k}", "uniform", s, "scarf", obj="ring"))
    parts.append(Part("body.skirt", "skirt", _skirt(rig), "skirt"))
    parts.append(Part("body.underskirt", "skirt", _underskirt(rig), "skirt"))
    return parts
