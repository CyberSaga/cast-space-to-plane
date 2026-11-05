"""Cardigan of the Reiya model (SPEC.md §D.6, §D.7): regions ``cardigan`` and ``sleeves``.

Regions and the objects they fill (SPEC.md §G, module -> regions mapping):

* ``cardigan`` -> object ``cardigan``: the cropped rust-brown knit cardigan (``cardigan``) worn off the shoulders: the
  body panel (back and both fronts in one piece) with the deep V and the crossover (her right front over her left),
  the ribbed front band that runs up both front edges, round the back's boat neckline and over the shoulders, the
  plain hem band, and its one round gold button (``buttons``; it sets ``obj="buttons"``: it lies on the centre line
  with the dress buttons) (§D.6);
* ``sleeves`` -> no default object: each part sets ``obj="arm_l"`` (her left, ``+X``) or ``obj="arm_r"``: the balloon
  sleeve from the dropped shoulder and its long ribbed cuff (§D.7).  The hands of :mod:`reiya_model.limbs` (and the
  white sleeve tubes of :mod:`reiya_model.body`, when ``body.TOP_SLEEVE_TUBES`` builds them) share these two
  objects, so each arm is one compact object.

The body panel is one slab (``cardigan_thickness`` outward from the reference surface ``rig.cardigan_section``) over a
grid whose columns run round the body from her left front's (the under-lap's) hidden edge, round her left side, the
back and her right side, to her right front's (the over-lap's) edge, which crosses the centre line: the panel wraps a
little more than 360 degrees and the over-lap stands ``cardigan_thickness + overlap_gap`` off the reference where the
under-lap lies under it.  Its rows run from the top edge (the neckline: the V edges, the shoulders, the back's boat
line) to the hem (the rounded front corners, the level back).  The grid is a Coons patch in (azimuth, z) between the
four edges.

How the lines come out (SPEC.md §F):

* the panel is one smooth group: it draws only as its outline, and its edges are covered by the bands;
* the bands are separate shells with a triangular section that wraps the panel's edge: a sloping top from the inner
  border (floating ``band_float`` over the panel) to ``band_thickness - cardigan_thickness`` proud at the garment
  edge, a flat edge face, and an undercut face back under the inner border.  So each band's inner border is a
  camera silhouette from every view that sees its top (no construction rays), and the garment edge draws as the band's
  edge (the edge face's twisted quads are split into their triangles, so the outline stays unbroken where that face
  turns edge-on and the line moves from its top edge to its bottom edge);
* the hem band is one smooth group (``hem_band_ribs`` 0, Decision 12): only its borders draw, like the other bands
  (with ``hem_band_ribs`` > 0 its columns alternate two groups and the rib creases draw across it);
* the button is a single-group dome on the over-lap's band (its outline draws);
* the balloon sleeve is a smooth bag (SLEEVE_POINTS round, rings at equal steps of the normal's angle, a rounded
  cap and a rounded bottom), so its outline and shading show no flat panels; it is one smooth group (outline only)
  down to a ring of its rounded bottom just outside the cuff (rig.sleeve_gather_ring), below which it is a second
  group: that ring draws the gather, the cuff's top, from every view that sees it (the rounded bottom faces the
  camera down to the cuff, so no silhouette would draw it); the cuff's cone alternates two groups in pairs of
  columns (8 rib creases), and its mouth (the recess turning in) is a third group, so the cuff's lower rim always
  draws.  The cuff starts inside the bag's rounded bottom, which rounds in over it.
"""

from __future__ import annotations

import math

import numpy as np

from charmodel import meshkit as mk
from charmodel.meshkit import Part

from .rig import Rig

__all__ = ["REGIONS", "build"]

#: The regions this module builds (``--only cardigan`` selects both).
REGIONS = ("cardigan", "sleeves")

# ---------------------------------------------------------------------------------------------------------------
# Resolutions and shape factors (every dimension comes from the rig)
# ---------------------------------------------------------------------------------------------------------------
#: Bottom azimuths (deg) of the panel's columns whose tops are her left neckline's points, from the crossing side
#: (neckline point 10, x 0.022) to the back (point 1, x 0.040); her right side mirrors them.  The tops sit exactly
#: on the neckline's points, so the band follows the neckline; the bottoms are spread evenly round the hem.
CARD_BOTTOM_DEG = (12.0, 24.0, 36.0, 48.0, 60.0, 72.0, 90.0, 108.0, 125.0, 150.0)
#: ... and of the columns under the over-lap's V edge below its bend (``rig.overlap_v_edge`` without the crossing).
CARD_OVERLAP_BOTTOM_DEG = (336.0, 349.0)
#: Rows of the panel grid: the top edge, just past the front band (ROW_MARGIN beyond its width, across the edge),
#: just above the hem band, the hem.
ROW_MARGIN = 0.003
ROW_MAX_FRACTION = 0.42            # a short column keeps both band rows within this fraction of its length
ROW_SAMPLES = 41                   # samples along a column to measure distances on it
HEM_SIDE_BLEND_DEG = 20.0          # the hem steps from the fronts' side level to the back's over this azimuth range
HEM_STATION_STEP = 0.019           # the hem band's stations lie about this far apart along the hem (equal arc length),
#                                    so the band follows the rounded front corners and the curve round the body
EDGE_BLEND_COLUMNS = (1.0, 0.5)    # weight of the over-lap edge's own curve in the last column and the next (Coons)
UNDERLAP_CUT = 0.008               # the panel's first column cuts this far off the under-lap's hidden corner (the
#                                    hidden edge then belongs to the top row: no straight-angle corner in the grid)
#: Bottom azimuths (deg) of the columns whose tops are the under-lap's hidden edge points (from its corner side up
#: to the crossing).
CARD_UNDERLAP_BOTTOM_DEG = (-8.0, -1.0, 6.0)
#: Points round the balloon sleeve: every ring is an ellipse sampled at equal steps of its outward normal's angle
#: (22.5 deg), so neighbouring facets meet at about 22.5 deg all round, the deep sides included (equal steps of the
#: ellipse's parameter crowd the turn at the ends of its long axis).
SLEEVE_POINTS = 15
SLEEVE_CAP_RINGS = 4              # rings of the balloon's top dome (over the shoulder ring), at equal normal steps
SLEEVE_BAG_RINGS = 5              # rings of the bag's rounded bottom (under its widest ring), at equal normal steps
SLEEVE_SPLIT_DEG = 0.25           # the sleeve's quads twisted more than this (the long bands between rings of
#                                   different shapes, up to ~1.2 deg) are split into their two fan triangles
#                                   (meshkit.split_twisted): seen edge-on, a quad's Newell facing and one of its
#                                   triangles disagreed, and the quad's own triangle hid the outline (a 3-4 cm gap at
#                                   az 15 / 40 in the 72-azimuth scan)
CUFF_POINTS = 16                   # a multiple of 4: the 8 rib creases come from groups alternating in pairs
BUTTON_POINTS = 8
BUTTON_BACK = (0.8, 0.5)           # the button's back ring: radius fraction, height as a fraction of the band's relief
BUTTON_SHOULDER = (0.7, 0.6)       # the dome's shoulder ring: radius fraction, height fraction rim -> apex
PROBE = 0.05                       # rays that find a surface start this far outside it
BAND_TOP_SAMPLES = 5               # samples per side of each band strip checked against the panel ...
BAND_TOP_PASSES = 8                # ... in up to this many lifting passes
BAND_KINK_MARGIN = 0.0005         # ... and the band's edge clears a kink of the panel's edge by this
BAND_EDGE_KEEP = 0.002             # ... from the inner border to this far inside the panel's edge
BAND_MIN_STEP = 0.014              # the front band skips panel edge nodes closer than this to the previous station
#                                    (a short step at a corner would fold the band's mitred inner border)
BAND_EDGE_SPLIT_DEG = 1.0          # a band's edge-face quads twisted more than this are split into their two fan
#                                    triangles (meshkit.split_twisted): where the edge face turns edge-on along the
#                                    band, the outline moves from its top edge to its bottom edge inside one quad

SIDES = (1, -1)


def _s(side: int) -> str:
    return "l" if side > 0 else "r"


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    return v / math.sqrt(float(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))


def _dot(a, b) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def _smoothstep(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


# ---------------------------------------------------------------------------------------------------------------
# the reference surface (rig.cardigan_section) by azimuth
# ---------------------------------------------------------------------------------------------------------------

def _ref(rig: Rig, phi: float, z: float):
    """``(point, horizontal outward unit normal)`` of the cardigan's reference surface at azimuth ``phi`` (deg, 0
    front, 90 her left, any turn) and height ``z``: the section's point on the ray from its centre."""
    hw, yf, yb = rig.cardigan_section(z)
    c = 0.5 * (yf + yb)
    e = rig.body_exponent
    p = math.radians(phi)
    sx, cy = math.sin(p), -math.cos(p)
    semi = (yb - c) if cy > 0.0 else (c - yf)
    ax, ay = abs(sx) / hw, abs(cy) / semi
    r = 1.0 / (ax ** e + ay ** e) ** (1.0 / e)
    X, Y = r * sx, r * cy
    gx = math.copysign(abs(X / hw) ** (e - 1.0) / hw, X) if X != 0.0 else 0.0
    gy = math.copysign(abs(Y / semi) ** (e - 1.0) / semi, Y) if Y != 0.0 else 0.0
    g = math.hypot(gx, gy)
    return np.array([X, c + Y, z]), np.array([gx / g, gy / g, 0.0])


def _phi_of(rig: Rig, x: float, z: float, back: bool = False) -> float:
    """Azimuth (deg, -180..180) of the reference surface's point at TRUE ``x`` and height ``z`` on the front (or
    back) half."""
    hw, yf, yb = rig.cardigan_section(z)
    c = 0.5 * (yf + yb)
    y = rig.cardigan_surface_y(x, z, not back)
    return math.degrees(math.atan2(x, c - y))


def _lift(rig: Rig, x: float) -> float:
    """How far the over-lap (her right front) stands off the reference at TRUE ``x``: cardigan_thickness +
    overlap_gap where the under-lap lies under it, fading to 0 over overlap_lift_width towards her right side."""
    xu = min(p[0] for p in rig.underlap_edge)
    w = _smoothstep((x - (xu - rig.overlap_lift_width)) / rig.overlap_lift_width)
    return w * (rig.cardigan_thickness + rig.overlap_gap)


def _hem_z(rig: Rig, phi: float) -> float:
    """z of the panel's lower edge at the unwrapped azimuth ``phi`` (< 180: the under-lap's side, > 180: the
    over-lap's): the fronts' rounded corners (``cardigan_front_hem`` by |x|; the under-lap rising to its hidden
    corner past the centre, the over-lap level to its lower corner), stepping to the back's level at the sides."""
    a = phi % 360.0
    blend = HEM_SIDE_BLEND_DEG
    zs, zb = rig.cardigan_front_hem[-1][1], rig.cardigan_back_hem_z
    if 90.0 <= a <= 270.0:
        t = min(1.0, min(a - 90.0, 270.0 - a) / blend)
        return zs + t * (zb - zs)
    xu, zu = rig.underlap_edge[-1][0], rig.underlap_edge[-1][2]
    z0 = rig.cardigan_hem_z(0.0)
    z = z0
    for _ in range(8):
        x = float(_ref(rig, phi, z)[0][0])
        if phi < 180.0:                                         # the under-lap (her left front)
            z = rig.cardigan_hem_z(x) if x >= 0.0 else z0 + (zu - z0) * min(1.0, x / xu)
        else:                                                   # the over-lap (her right front)
            z = rig.cardigan_hem_z(x) if x <= 0.0 else z0
    return z


# ---------------------------------------------------------------------------------------------------------------
# the body panel
# ---------------------------------------------------------------------------------------------------------------

def _edges(rig: Rig):
    """The panel's edges in (unwrapped azimuth, z): ``(tops, bottoms, R)``.  ``tops`` are the top nodes of the columns:
    the under-lap's hidden front edge from just above its corner up to the crossing (it continues her left V edge,
    so it belongs to the top row), her left V, the shoulder, the back's boat line, her right shoulder and V; the
    first column is a short end edge cut UNDERLAP_CUT off the under-lap's hidden corner.  ``bottoms`` are their
    bottom azimuths on the hem; ``R`` is the over-lap's front edge (the last column) from the crossing down to its
    lower corner."""
    ux, _uy, uz = rig.underlap_edge[-1]
    tops = [(_phi_of(rig, ux, uz + UNDERLAP_CUT), uz + UNDERLAP_CUT)]
    zc = _hem_z(rig, _phi_of(rig, ux + UNDERLAP_CUT, uz))
    bots = [_phi_of(rig, ux + UNDERLAP_CUT, zc)]
    under = [(_phi_of(rig, x, z), z) for x, _y, z in reversed(rig.underlap_edge[:-1])]
    if len(under) != len(CARD_UNDERLAP_BOTTOM_DEG):
        raise mk.MeshError("cardigan: CARD_UNDERLAP_BOTTOM_DEG must give one bottom per under-lap edge point")
    tops += under
    bots += list(CARD_UNDERLAP_BOTTOM_DEG)
    left = []
    for x, y, z in rig.cardigan_neckline:
        hw, yf, yb = rig.cardigan_section(z)
        left.append((math.degrees(math.atan2(x, 0.5 * (yf + yb) - y)), z))
    # left[0] back centre ... left[-1] the crossing (already the under-lap edge's last top)
    inner = list(reversed(left[1:-1]))                         # crossing side -> back, without both ends
    if len(inner) != len(CARD_BOTTOM_DEG):
        raise mk.MeshError("cardigan: CARD_BOTTOM_DEG must give one bottom per neckline point")
    bend_z = rig.overlap_v_edge[0][1]
    tops += inner
    bots += list(CARD_BOTTOM_DEG)
    tops.append((180.0, left[0][1]))
    bots.append(180.0)
    for (p, z), b in zip(reversed(inner), reversed(CARD_BOTTOM_DEG)):
        if z > bend_z + 1e-9:
            tops.append((360.0 - p, z))
            bots.append(360.0 - b)
    ov = [(_phi_of(rig, x, z) % 360.0, z) for x, z in rig.overlap_v_edge[:-1]]
    if len(ov) != len(CARD_OVERLAP_BOTTOM_DEG):
        raise mk.MeshError("cardigan: CARD_OVERLAP_BOTTOM_DEG must give one bottom per over-lap V point")
    tops += ov
    bots += list(CARD_OVERLAP_BOTTOM_DEG)
    R = [(_phi_of(rig, x, z) + 360.0, z) for x, _y, z in rig.overlap_edge]
    return tops, bots, R


def _polyline_param(P, rmean: float = 0.1):
    """Cumulative arc length fractions of a (azimuth deg, z) polyline (azimuth converted at ``rmean``)."""
    P = np.asarray(P, dtype=np.float64)
    d = np.hypot(np.radians(np.diff(P[:, 0])) * rmean, np.diff(P[:, 1]))
    s = np.concatenate([[0.0], np.cumsum(d)])
    return s / s[-1]


def _at(P, s, v: float) -> np.ndarray:
    P = np.asarray(P, dtype=np.float64)
    return np.array([np.interp(v, s, P[:, 0]), np.interp(v, s, P[:, 1])])


def _panel_grid(rig: Rig):
    """``(grid (U, V, 3) on the reference surface (+ the over-lap's lift), over-lap flags (U,))``: a Coons patch in
    (azimuth, z) between the top nodes, the hem and the over-lap's curved front edge R (the last column).  Each
    column's second row lies just beyond the front band's inner border and its second-to-last row just above the
    hem band's top border (measured across the edge), so each band lies over one flat strip of facets."""
    tops, bots, R = _edges(rig)
    sR = _polyline_param(R)
    T = [np.array(t) for t in tops] + [np.array(R[0])]
    B = [np.array((b, _hem_z(rig, b))) for b in bots] + [np.array(R[-1])]
    U = len(T)
    wr = [0.0] * U
    for k, w in enumerate(EDGE_BLEND_COLUMNS):
        wr[U - 1 - k] = w
    R0, R1 = np.array(R[0]), np.array(R[-1])
    over = np.array([float(T[k][0]) > 180.0 for k in range(U)])

    def point(k, v):
        q = (1.0 - v) * T[k] + v * B[k]
        q = q + wr[k] * (_at(R, sR, v) - ((1.0 - v) * R0 + v * R1))
        p, n = _ref(rig, float(q[0]), float(q[1]))
        if over[k] and float(q[0]) > 270.0:     # her right FRONT only: the lift (by x) must not bulge the back's
            p = p + _lift(rig, float(p[0])) * n  # right half next to the centre back (r3-T2; 0 at 270 anyway)
        return p

    vs = np.linspace(0.0, 1.0, ROW_SAMPLES)
    cols = [np.array([point(k, v) for v in vs]) for k in range(U)]
    top3 = [c[0] for c in cols]
    bot3 = [c[-1] for c in cols]

    def sin_between(a, b):
        return float(np.linalg.norm(np.cross(a, b))) / float(np.linalg.norm(a) * np.linalg.norm(b))

    G = np.zeros((U, 4, 3))
    for k in range(U):
        c = cols[k]
        seg = np.linalg.norm(np.diff(c, axis=0), axis=1)
        sl = np.concatenate([[0.0], np.cumsum(seg)])
        length = float(sl[-1])
        kp, kn = max(k - 1, 0), min(k + 1, U - 1)
        st = sin_between(c[1] - c[0], top3[kn] - top3[kp])
        sb = sin_between(c[-2] - c[-1], bot3[kn] - bot3[kp])
        dt = min((rig.front_band_width + ROW_MARGIN) / max(st, 0.2), ROW_MAX_FRACTION * length)
        db = min((rig.hem_band_height + ROW_MARGIN) / max(sb, 0.2), ROW_MAX_FRACTION * length)
        dist = (0.0, dt, length - db, length)
        for j, d in enumerate(dist):
            G[k, j] = point(k, float(np.interp(d, sl, vs)))
    return G, over


def _panel(rig: Rig):
    """The body panel slab and its two faces' grids ``(mesh, inner grid, outer grid)``."""
    G, _over = _panel_grid(rig)
    centre = (0.0, 0.5 * (rig.cardigan_rows[-1][2] + rig.cardigan_rows[-1][3]), rig.seam_z)
    mesh, sides = mk.thicken(G, rig.cardigan_thickness, offset="outward", away_from=centre, groups="single",
                             return_sides=True)
    return mesh, sides["back"], sides["front"]


def _patch(G, k0: int, k1: int) -> mk.Mesh:
    """The open quad surface of the grid ``G`` (U, V, 3) between its columns ``k0`` and ``k1`` (for ray casts)."""
    sub = G[k0:k1 + 1]
    U, V = sub.shape[:2]
    faces = [[u * V + v, (u + 1) * V + v, (u + 1) * V + v + 1, u * V + v + 1]
             for u in range(U - 1) for v in range(V - 1)]
    return mk.Mesh(sub.reshape(-1, 3), faces, 1)


# ---------------------------------------------------------------------------------------------------------------
# bands
# ---------------------------------------------------------------------------------------------------------------

def _resample_pair(P_in, P_out, n: int):
    """``n`` stations at equal arc length along the polyline ``P_in`` with the matching points of ``P_out`` (the same
    fractions of each segment), and each station's (fractional) index on the polyline."""
    P_in, P_out = np.asarray(P_in), np.asarray(P_out)
    seg = np.linalg.norm(np.diff(P_in, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0.0, s[-1], n)
    A = np.stack([np.interp(t, s, P_in[:, k]) for k in range(3)], axis=1)
    B = np.stack([np.interp(t, s, P_out[:, k]) for k in range(3)], axis=1)
    return A, B, np.interp(t, s, np.arange(len(P_in), dtype=np.float64))


def _band(rig: Rig, patches, side, E_in, E_out, width: float, into_sign: float, groups, nodes=None, station_idx=None,
          end_dir=None):
    """A band along the panel edge ``E_in`` (reference side) / ``E_out`` (outer side), ``(U, 3)`` stations in order:
    a triangular section with its inner border ``width`` into the panel (floating band_float over it), its top
    rising to the band's relief at the edge, the edge face band_overhang beyond the panel's edge and its inside
    band_inner_relief inside the panel's inner face.  ``into_sign`` picks the side of the path the panel lies on;
    ``patches`` are the outer faces of the under-lap's and the over-lap's halves of the panel and ``side[i]`` (0 / 1)
    says which one station ``i`` lies on (the bands under the over-lap are laid on the under-lap, not on it).
    ``nodes`` (the panel's edge polyline, reference and outer side) and ``station_idx`` (each station's fractional
    index on it): where a node of the panel's edge lies between two stations and beyond their chord (a kink of the
    edge), the band's edge stands that much further out at both stations, so the panel's rim never pokes out.
    ``end_dir``: the last station's section runs along this direction (made perpendicular to ``N``, mitred so the band
    keeps its width), so the band's end lies along a garment edge that meets the path at a slant."""
    E_in, E_out = np.asarray(E_in, dtype=np.float64), np.asarray(E_out, dtype=np.float64)
    U = len(E_in)
    t_th = rig.cardigan_thickness
    h = rig.band_thickness - t_th
    f = rig.band_float
    N = np.array([_unit(E_out[i] - E_in[i]) for i in range(U)])
    seg = [_unit(E_out[i + 1] - E_out[i]) for i in range(U - 1)]
    S = []
    for i in range(U):
        a = seg[i - 1] if i > 0 else seg[0]
        b = seg[i] if i < U - 1 else seg[-1]
        si = _unit(np.cross(a + b, N[i])) * into_sign
        sa = _unit(np.cross(a, N[i])) * into_sign
        S.append(si / max(0.5, _dot(si, sa)))                   # mitred at a corner: the border keeps its width
    if end_dir is not None:
        si = _unit(S[-1])
        e = np.asarray(end_dir, dtype=np.float64)
        e = _unit(e - N[-1] * _dot(e, N[-1]))
        S[-1] = e / max(0.5, _dot(e, si))
    S = np.array(S)
    A0 = E_out + width * S
    # project the inner border onto the panel's outer face (the ray from just outside it along -N)
    side = np.asarray(side)
    hgt = np.full(U, np.nan)
    for k in (0, 1):
        idx = np.nonzero(side == k)[0]
        if len(idx):
            hgt[idx] = mk.surface_clearance(patches[k], (A0 + 2.0 * h * N)[idx], N[idx])
    A = np.array([A0[i] + (2.0 * h - (hgt[i] if np.isfinite(hgt[i]) else 2.0 * h) + f) * N[i] for i in range(U)])
    over = np.full(U, rig.band_overhang)
    if nodes is not None:
        n_in, n_out = (np.asarray(x, dtype=np.float64) for x in nodes)
        for i in range(U - 1):
            lo, hi = station_idx[i], station_idx[i + 1]
            for k in range(int(math.floor(lo)) + 1, int(math.ceil(hi))):
                if not lo < k < hi:
                    continue
                t = (k - lo) / (hi - lo)
                for P, Q0, Q1 in ((n_in[k], E_in[i], E_in[i + 1]), (n_out[k], E_out[i], E_out[i + 1])):
                    q = Q0 + t * (Q1 - Q0)
                    sd = _unit((1.0 - t) * S[i] + t * S[i + 1])
                    d = -_dot(P - q, sd)                         # how far the node lies beyond the chord
                    if d > 0.0:
                        extra = rig.band_overhang + d + BAND_KINK_MARGIN
                        over[i], over[i + 1] = max(over[i], extra), max(over[i + 1], extra)
    C = E_out + h * N - over[:, None] * S
    reach = (width - BAND_EDGE_KEEP) / (width + rig.band_overhang)
    lift = _lift_band_top(patches, side, A, A + reach * (C - A), N, f)
    A = A + lift[:, None] * N
    C = C + lift[:, None] * N
    E = E_in - rig.band_inner_relief * N - over[:, None] * S
    rings = [np.array([A[i], C[i], E[i]]) for i in range(U)]
    g = np.asarray(groups)
    caps = (int(g.ravel()[0]), int(g.ravel()[-1])) if g.ndim else (int(g), int(g))
    return mk.loft(rings, "flat", "flat", groups=groups, cap_groups=caps)


def _lift_band_top(patches, side, A, C, N, clearance: float) -> np.ndarray:
    """Per-station lift ``(U,)`` along ``N`` that keeps the band's whole top at least ``clearance`` over the faceted
    panel (``patches[side[i]]``): each strip between the inner border ``A`` and ``C`` (the top just inside the panel's
    edge) of two consecutive stations is checked on the
    triangles of both of its diagonals (castplane may fan it either way), at BAND_TOP_SAMPLES points per side.  Where
    the panel bends between two stations (the over-lap's lift ramp, the body's curve) a flat strip would otherwise
    dip into it and the panel would show through the band."""
    A, C, N = (np.asarray(x, dtype=np.float64) for x in (A, C, N))
    U = len(A)
    lift = np.zeros(U)
    m = BAND_TOP_SAMPLES - 1
    side = np.asarray(side)
    bary = [(i / m, j / m) for i in range(m + 1) for j in range(m + 1 - i)]
    for _ in range(BAND_TOP_PASSES):
        pts, dirs, owners = [], [], []
        Al, Cl = A + lift[:, None] * N, C + lift[:, None] * N
        for i in range(U - 1):
            q = (Al[i], Al[i + 1], Cl[i + 1], Cl[i])
            nq = (N[i], N[i + 1], N[i + 1], N[i])
            for t in ((0, 1, 2), (0, 2, 3), (0, 1, 3), (1, 2, 3)):
                for u, v in bary:
                    w = (1.0 - u - v, u, v)
                    pts.append(sum(w[k] * q[t[k]] for k in range(3)))
                    dirs.append(_unit(sum(w[k] * nq[t[k]] for k in range(3))))
                    owners.append(i)
        pts, dirs, owners = np.array(pts), np.array(dirs), np.array(owners)
        hgt = np.full(len(pts), np.nan)
        for k in (0, 1):
            idx = np.nonzero(side[owners] == k)[0]
            if len(idx):
                hgt[idx] = mk.surface_clearance(patches[k], pts[idx], dirs[idx])
        bump = np.zeros(U)
        for i, hv in zip(owners, hgt):
            if np.isfinite(hv) and hv < clearance:
                bump[i] = max(bump[i], clearance - hv)
                bump[i + 1] = max(bump[i + 1], clearance - hv)
        if not np.any(bump > 1e-7):
            break
        lift += bump
    return lift


def _split_edge_faces(band: mk.Mesh) -> mk.Mesh:
    """``band`` (a :func:`_band` loft: per station step its top, edge and undercut quads, then the two end caps) with
    its twisted edge-face quads split into their fan triangles (BAND_EDGE_SPLIT_DEG).  Where the edge face turns
    edge-on to the camera (along the V and round the hem in 3/4 views) castplane takes a twisted quad's facing from
    its Newell normal but hides lines with its triangles, so the outline that moves from the band's top edge to its
    bottom edge inside the quad loses a piece; as two triangles the diagonal carries the outline across."""
    steps = (len(band.faces) - 2) // 3
    only = [k < 3 * steps and k % 3 == 1 for k in range(len(band.faces))]
    return mk.split_twisted(band, BAND_EDGE_SPLIT_DEG, only=only)


def _clip_from(P_in, P_out, z_stop: float):
    """The part of an end edge (stations ``P_in`` / ``P_out`` from the crossing down) above ``z_stop``, with the cut
    point interpolated."""
    P_in, P_out = np.asarray(P_in), np.asarray(P_out)
    keep_in, keep_out = [P_in[0]], [P_out[0]]
    for i in range(1, len(P_in)):
        if P_in[i, 2] > z_stop:
            keep_in.append(P_in[i])
            keep_out.append(P_out[i])
            continue
        a, b = P_in[i - 1], P_in[i]
        t = (a[2] - z_stop) / (a[2] - b[2])
        keep_in.append(a + t * (b - a))
        keep_out.append(P_out[i - 1] + t * (P_out[i] - P_out[i - 1]))
        break
    return np.array(keep_in), np.array(keep_out)


def _front_band(rig: Rig, patches, kb: int, Gi, Go):
    """The front band along the panel's top row and its last column: up the under-lap's hidden edge (from the panel's
    cut corner), up her left V, over the shoulders and along the back's boat neckline, down her right V and the
    over-lap's edge to the hem band's top."""
    zr = float(Gi[-1, -1, 2]) + rig.hem_band_height
    ri, ro = _clip_from(Gi[-1], Go[-1], zr)
    E_in = np.concatenate([Gi[:-1, 0], ri])
    E_out = np.concatenate([Go[:-1, 0], ro])
    U = len(Gi)
    col = list(range(U - 1)) + [U - 1] * len(ri)
    keep = [0]
    for i in range(1, len(E_in)):
        if np.linalg.norm(E_in[i] - E_in[keep[-1]]) >= BAND_MIN_STEP or i == len(E_in) - 1:
            if i == len(E_in) - 1 and np.linalg.norm(E_in[i] - E_in[keep[-1]]) < BAND_MIN_STEP:
                keep[-1] = i
            else:
                keep.append(i)
    E_in, E_out = E_in[keep], E_out[keep]
    side = [1 if col[i] > kb else 0 for i in keep]
    return _band(rig, patches, side, E_in, E_out, rig.front_band_width, 1.0, 1)


def _hem_band(rig: Rig, patches, kb: int, Gi, Go):
    """The hem band round the lower edge, corner to corner, with stations about HEM_STATION_STEP apart along the hem
    (a smooth band that follows the rounded front corners).  With ``hem_band_ribs`` 0 (the default, Decision 12) it is
    one smooth group: a plain band whose two borders draw, like the front and neck bands.  With ``hem_band_ribs`` > 0
    the stations are grouped into hem_band_ribs + 1 columns of alternating groups, so the ribs draw as creases across
    the band (every crease adds drawn edges to every web frame: the sheet's ~32 cost ~110 ms more per still frame,
    and 16 widely spaced creases cut the band into boxes).  Its end at the over-lap's lower corner runs up along the
    over-lap's front edge (which leans out above the corner), so it meets the front band's end there: no strip of the
    panel's edge shows between the two bands under the button (r3-L3)."""
    hem = Gi[:, -1]
    arc = float(np.sum(np.linalg.norm(np.diff(hem, axis=0), axis=1)))
    n = int(math.ceil(round(arc / HEM_STATION_STEP, 6))) + 1
    if rig.hem_band_ribs > 0:
        per = max(1, int(round((n - 1) / (rig.hem_band_ribs + 1))))
        n = per * (rig.hem_band_ribs + 1) + 1
        groups = [1 + (k // per) % 2 for k in range(n - 1)]
    else:
        groups = [1] * (n - 1)
    E_in, E_out, col = _resample_pair(Gi[:, -1], Go[:, -1], n)
    side = [1 if c > kb else 0 for c in col]
    return _band(rig, patches, side, E_in, E_out, rig.hem_band_height, -1.0, groups, nodes=(Gi[:, -1], Go[:, -1]),
                 station_idx=col, end_dir=Gi[-1, -2] - Gi[-1, -1])


def _button(rig: Rig, panel: mk.Mesh) -> mk.Mesh:
    """The round gold button on the over-lap's band: a back ring sunk in the band, a rim ring over the band's top,
    a shoulder ring and the apex ``cardigan_button_relief`` over the band (one group)."""
    bx, bz = rig.cardigan_button
    phi = _phi_of(rig, bx, bz) + 360.0
    p, n = _ref(rig, phi, bz)
    p = p + _lift(rig, float(p[0])) * n
    hgt = mk.surface_clearance(panel, (p + PROBE * n)[None, :], n[None, :])[0]
    s = p + PROBE * n - float(hgt) * n                          # on the panel's outer face
    h = rig.band_thickness - rig.cardigan_thickness
    R = 0.5 * rig.cardigan_button_diameter
    up = np.array([0.0, 0.0, 1.0])
    e2 = _unit(up - n * _dot(up, n))
    e1 = _unit(np.cross(e2, n))
    rb, hbk = BUTTON_BACK
    rs, hs = BUTTON_SHOULDER
    rim = h + rig.cardigan_button_rim
    apex = h + rig.cardigan_button_relief
    rings = []
    for r, z in ((rb * R, hbk * h), (R, rim), (rs * R, rim + hs * (apex - rim))):
        th = [2.0 * math.pi * j / BUTTON_POINTS for j in range(BUTTON_POINTS)]
        rings.append(np.array([s + z * n + r * (math.cos(a) * e1 + math.sin(a) * e2) for a in th]))
    return mk.loft(rings, "flat", ("pole", s + apex * n), groups=1, cap_groups=(1, 1))


# ---------------------------------------------------------------------------------------------------------------
# sleeves (§D.7), built for her left arm and mirrored
# ---------------------------------------------------------------------------------------------------------------

def _frame(T):
    """``(lateral, depth)`` unit axes of a ring perpendicular to ``T``: depth along +Y (back), lateral = T x depth."""
    T = _unit(T)
    Y = np.array([0.0, 1.0, 0.0])
    N = _unit(Y - T * _dot(Y, T))
    return _unit(np.cross(T, N)), N


def _ellipse_ring(c, b, nv, lat: float, dep: float) -> np.ndarray:
    """An elliptical ring round ``c`` with the semi-axes ``lat`` along ``b`` and ``dep`` along ``nv``, its
    SLEEVE_POINTS points at equal steps of the outward normal's angle (point 0 on ``+b``)."""
    pts = []
    for j in range(SLEEVE_POINTS):
        a = 2.0 * math.pi * j / SLEEVE_POINTS
        ca, sa = math.cos(a), math.sin(a)
        q = math.sqrt(lat * lat * ca * ca + dep * dep * sa * sa)
        pts.append(c + (lat * lat * ca / q) * b + (dep * dep * sa / q) * nv)
    return np.array(pts)


def _cuff_axis(rig: Rig):
    """``(gather centre, axis, lateral, depth)`` of her left cuff: the forearm's direction, moved ``cuff_offset``
    outward of the arm (along the ring's lateral axis) from rig.cuff_start."""
    d = rig.forearm_dir(1)
    b, nv = _frame(d)
    return rig.cuff_start(1) + rig.cuff_offset * b, d, b, nv


def _dome(ring, centre, axis, depth: float, n_rings: int, radius: float, shift=None) -> list:
    """``n_rings`` rings closing ``ring`` (round ``centre``) into a rounded end that bulges ``depth`` along the unit
    ``axis``: the profile is an ellipse quadrant (``radius`` x ``depth``) sampled at equal steps of its normal's angle,
    so the end turns as gently at its rim as at its pole (equal steps of the ellipse's parameter crowd a flat dome's
    turn at its rim).  Ordered from the rim to the pole; the pole itself is ``centre + shift + depth * axis``.
    ``shift``: the rings' centres move by this much towards the pole (in proportion to the sine of the profile
    parameter), so a bag's bottom rounds onto an axis that is not its own (the cuff's)."""
    out = []
    t_pole = 0.5 * math.pi
    for k in range(1, n_rings + 1):
        psi = 0.5 * math.pi * k / (n_rings + 1)                 # the profile's normal angle
        t = math.atan((depth / radius) * math.tan(psi))         # ... as the profile ellipse's parameter
        c = centre if shift is None else centre + shift * (math.sin(t) / math.sin(t_pole))
        out.append(c + (ring - centre) * math.cos(t) + axis * (depth * math.sin(t)))
    return out


def _balloon(rig: Rig) -> mk.Mesh:
    """The balloon sleeve: the shoulder ring (rig.sleeve_shoulder_ring: above the first ring, in its frame) closed by
    a low dome (sleeve_cap_depth, SLEEVE_CAP_RINGS rings) under the end of the neck band, so the cap is one round puff
    that continues the shoulder's curve into the sleeve; then the rings of rig.sleeve_rings (each an ellipse round the
    arm axis point of its position, moved outward and back, its plane perpendicular to the sleeve's centre line
    turned towards level by its ``level``): the sleeve widens to the bag, whose last ring (the widest) closes in a
    rounded bottom (sleeve_bag_depth, SLEEVE_BAG_RINGS rings) that rounds in under the bag, its rings converging
    onto the cuff's axis (sleeve_bag_converge), so they hug the cuff all round; the cuff comes out of it (its pole
    lies inside the cuff).  The bottom's rings below rig.sleeve_gather_ring are a second smooth group: the boundary,
    4-22 mm outside the cuff, draws the gather.  Both ends are domes at equal steps of the profile's normal angle
    (_dome)."""
    side = 1
    rows = rig.sleeve_rings
    C = [rig.arm_point(side, p) + np.array([side * out, back, 0.0]) for p, _lat, _dep, out, back, _lv in rows]
    rings, frames = [], []
    for k, (p, lat, dep, out, back, level) in enumerate(rows):
        T = C[min(k + 1, len(C) - 1)] - C[max(k - 1, 0)]
        n = _unit((1.0 - level) * _unit(T) + level * np.array([0.0, 0.0, -1.0]))
        b, nv = _frame(n)
        frames.append((b, nv, n))
        rings.append(_ellipse_ring(C[k], b, nv, lat, dep))
    out, up, lat, dep = rig.sleeve_shoulder_ring
    cs = C[0] + np.array([side * out, 0.0, up])
    shoulder = _ellipse_ring(cs, frames[0][0], frames[0][1], lat, dep)
    top_axis = _unit(cs - C[0])
    h = rig.sleeve_cap_depth
    cap = _dome(shoulder, cs, top_axis, h, SLEEVE_CAP_RINGS, 0.5 * (lat + dep))[::-1]   # the loft starts at the pole
    lat_b, dep_b = rows[-1][1], rows[-1][2]
    n_b = frames[-1][2]
    D = rig.sleeve_bag_depth
    g, d, _b, _nv = _cuff_axis(rig)
    q = g + _dot(C[-1] - g, d) * d                              # the cuff's axis at the bag ring's centre
    shift = rig.sleeve_bag_converge * ((q - C[-1]) - _dot(q - C[-1], n_b) * n_b)
    bottom = _dome(rings[-1], C[-1], n_b, D, SLEEVE_BAG_RINGS, 0.5 * (lat_b + dep_b), shift)
    nb = len(cap) + 1 + len(rings) - 1                          # the sections down to the bag ring
    groups = [1] * (nb + rig.sleeve_gather_ring) + [2] * (SLEEVE_BAG_RINGS - rig.sleeve_gather_ring)
    return mk.loft(cap + [shoulder] + rings + bottom, ("pole", cs + h * top_axis),
                   ("pole", C[-1] + shift + D * n_b), groups=groups, cap_groups=(1, 2))


def _cuff(rig: Rig) -> mk.Mesh:
    """The long ribbed cuff: a cone from inside the gather to the mouth (cuff_radius -> cuff_end_radius) round the
    cuff's axis (_cuff_axis), its mouth turning in as a shallow recess (a cone cuff_recess deep, the palm passes
    through it); the mouth's plane is turned cuff_mouth_level of the way from perpendicular to the axis to level (the
    sheet draws the mouth level: the cuff is longer on its outer side).  The cone's columns alternate two groups in
    pairs (cuff_ribs creases), the recess is a third group (the mouth's rim always draws).  The top (hidden in the
    balloon's bag) closes in a pole whose triangles take their column's group, so its rim adds no feature edges
    (only the rib creases run on across it)."""
    g, d, b, nv = _cuff_axis(rig)
    zup = np.array([0.0, 0.0, 1.0])
    up = _unit(zup - d * _dot(zup, d))                           # the ring plane's uphill direction
    tilt = math.acos(min(1.0, max(-1.0, -float(d[2]))))           # the axis' angle from straight down
    tan_l = math.tan(rig.cuff_mouth_level * tilt)
    th = [2.0 * math.pi * (j + 0.5) / CUFF_POINTS for j in range(CUFF_POINTS)]
    L = rig.cuff_length

    def ring(s, r, level):
        pts = []
        for a in th:
            e = math.cos(a) * b + math.sin(a) * nv
            pts.append(g + (s + (r * tan_l * _dot(e, up) if level else 0.0)) * d + r * e)
        return np.array(pts)

    rings = [ring(-rig.cuff_tuck, rig.cuff_radius_at(0.0), False), ring(L, rig.cuff_end_radius, True)]
    per = CUFF_POINTS // rig.cuff_ribs                           # columns per rib group
    groups = [1 + (j // per) % 2 for j in range(CUFF_POINTS)]
    return mk.loft(rings, "pole", ("pole", g + (L - rig.cuff_recess) * d), groups=np.array([groups]),
                   cap_groups=(None, 3))


# ---------------------------------------------------------------------------------------------------------------

def build(rig: Rig):
    """The parts of :data:`REGIONS`: the cardigan's panel, bands and button (object ``cardigan``) and per arm the
    balloon sleeve and its cuff (``arm_l`` / ``arm_r``).  The panel's and the bands' quads take their valley fan
    diagonal (:func:`charmodel.meshkit.inscribed_fan`) once the bands and the button have been laid on them: a ridge
    diagonal near the outline bulges over the outline edge in projection and the hidden-line pass drops pieces of the
    cardigan's outline in 3/4 views; a valley diagonal only lowers a faceted surface, so the bands and the button keep
    their clearance.  (Splitting the quads still twisted after that, meshkit.split_twisted, was tried: its diagonals
    draw as stray camera-silhouette strokes on the back and the sleeves' sides.)"""
    panel, Gi, Go = _panel(rig)
    kb = int(np.argmin(np.abs(Gi[:, 0, 0]) + 10.0 * (Gi[:, 0, 1] < 0.0)))   # the back centre column
    patches = (_patch(Go, 0, kb), _patch(Go, kb, len(Go) - 1))
    front_band = _front_band(rig, patches, kb, Gi, Go)
    hem_band = _hem_band(rig, patches, kb, Gi, Go)
    button = _button(rig, panel)
    parts = [Part("cardigan.panel", "cardigan", mk.inscribed_fan(panel), "cardigan"),
             Part("cardigan.front_band", "cardigan", _split_edge_faces(mk.inscribed_fan(front_band)), "cardigan"),
             Part("cardigan.hem_band", "cardigan", _split_edge_faces(mk.inscribed_fan(hem_band)), "cardigan"),
             Part("cardigan.button", "buttons", button, "cardigan", obj="buttons")]
    balloon, cuff = _balloon(rig), _cuff(rig)
    for side in SIDES:
        obj = f"arm_{_s(side)}"
        sleeve = mk.split_twisted(mk.inscribed_fan(balloon if side > 0 else balloon.mirror_x()), SLEEVE_SPLIT_DEG)
        parts.append(Part(f"cardigan.sleeve_{_s(side)}", "cardigan", sleeve, "sleeves", obj=obj))
        cuff_s = mk.inscribed_fan(cuff if side > 0 else cuff.mirror_x())   # its level mouth twists the cone's quads
        parts.append(Part(f"cardigan.cuff_{_s(side)}", "cardigan", cuff_s, "sleeves", obj=obj))
    return parts
