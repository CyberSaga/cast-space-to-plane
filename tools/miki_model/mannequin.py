"""Placeholder (mannequin) parts for every region of the model, at the spec's proportions.

Each region builder takes a :class:`~miki_model.rig.Rig` and returns a list of
:class:`~miki_model.meshkit.Part`; :func:`build` returns the parts of the requested regions.  The shapes are
deliberately simple (lofted sections, slabs, sweeps) but follow the rig's tables and landmarks (the numeric
spec), so a detailed module (``head.py``, ``hair.py``, ``body.py``, ``limbs.py``) can be previewed in context
while the others are still placeholders.  Every part names its material and lands in the object of
``assemble.OBJECTS`` that the real part will use (``obj=`` where the region's default object differs).
Most placeholders use one smooth group per shell, so they draw as silhouettes and cost no construction rays.

Regions (and the module that replaces them): ``head``, ``eyes``, ``face_marks`` (head.py); ``hair``,
``headband`` (hair.py); ``neck``, ``torso``, ``collar``, ``scarf``, ``skirt`` (body.py); ``arms``,
``hands``, ``legs``, ``socks``, ``shoes`` (limbs.py).
"""

from __future__ import annotations

import math

import numpy as np

from . import meshkit as mk
from .meshkit import Part
from .rig import Rig

__all__ = ["REGIONS", "BUILDERS", "build", "section_ring"]

SIDES = (1, -1)                    # her left (+X), her right (-X)


def _side_name(side: int) -> str:
    return "l" if side > 0 else "r"


def _local(mesh: mk.Mesh, origin, z_axis, x_hint=(1.0, 0.0, 0.0)) -> mk.Mesh:
    """Place a mesh built around the origin (local Z = ``z_axis``) at ``origin``."""
    x, y, z = mk.frame_from_z(z_axis, x_hint)
    return mesh.transform(np.stack([x, y, z], axis=1), origin)


def section_ring(hw, yf, yb, n, z, exponent=2.5, back_exponent=None, c=0.0, x0=0.0):
    """Horizontal ring ``(n, 3)`` of a body section (CCW from +Z, first point on +X): the front half
    (``y < c``) is the superellipse with semi-axes ``(hw, c - yf)``, the back half the one with ``(hw, yb - c)``
    (exponent ``back_exponent``, default ``exponent``)."""
    eb = exponent if back_exponent is None else back_exponent
    t = 2.0 * np.pi * np.arange(n) / n
    ct, st = np.cos(t), np.sin(t)
    back = st > 0
    e = np.where(back, eb, exponent)
    x = x0 + hw * np.sign(ct) * np.abs(ct) ** (2.0 / e)
    y = c + np.where(back, yb - c, c - yf) * np.sign(st) * np.abs(st) ** (2.0 / e)
    return np.stack([x, y, np.full(n, z)], axis=1)


def _face_slab(rig: Rig, pts_xz, relief: float, depth: float):
    """Slab conforming to the face: ``pts_xz`` ``(U, V, 2)`` face points; the back face lies ``depth``
    below the skin, the front face ``relief`` above it (one smooth group)."""
    P = np.asarray(pts_xz, dtype=np.float64)
    U, V = P.shape[:2]
    grid = np.zeros((U, V, 3))
    for i in range(U):
        for j in range(V):
            x, z = P[i, j]
            grid[i, j] = rig.head_surface_point(x, z) - depth * rig.head_normal(x, z)
    return mk.thicken(grid, depth + relief, offset="outward", away_from=rig.head_center, groups="single")


def _face_ellipse(rig: Rig, cx, cz, a, b, relief, nu=6, nv=4):
    """Elliptic face slab (centre ``(cx, cz)``, semi-axes ``a`` in x, ``b`` in z) from a square grid mapped
    onto the disc."""
    u = np.linspace(-1.0, 1.0, nu)
    v = np.linspace(-1.0, 1.0, nv)
    pts = np.zeros((nu, nv, 2))
    for i, uu in enumerate(u):
        for j, vv in enumerate(v):
            pts[i, j] = (cx + a * uu * math.sqrt(1.0 - 0.5 * vv * vv), cz + b * vv * math.sqrt(1.0 - 0.5 * uu * uu))
    return _face_slab(rig, pts, relief, rig.eye_slab_depth)


def _face_band(rig: Rig, xs, zc, half_h, relief):
    """Band on the face along ``xs`` with centre heights ``zc`` and half heights ``half_h`` (arrays)."""
    xs, zc, hh = (np.asarray(a, dtype=np.float64) for a in (xs, zc, half_h))
    pts = np.stack([np.stack([xs, zc - hh], axis=1), np.stack([xs, zc + hh], axis=1)], axis=1)
    return _face_slab(rig, pts, relief, rig.eye_slab_depth)


# ---------------------------------------------------------------------------
# head.py regions
# ---------------------------------------------------------------------------

def _jaw_y(rig: Rig, z: float) -> float:
    ys, zs = zip(*rig.jaw_underside)
    return float(np.interp(z, zs, ys))


def head(rig: Rig):
    rows = [r for r in rig.head_profile if r[1] > 0]
    rings = []
    nz = rig.nose_tip[2]
    for k, (z, hw, yf, yb) in enumerate(rows):
        if z == nz:                                      # the nose is local: a separate bump below
            yf = 0.5 * (rows[k - 1][2] + rows[k + 1][2])
        c = rig.face_offset(z)
        if yb is None:                                   # below the nape: the jaw underside is the back
            yb = _jaw_y(rig, z)
            c = 0.5 * (yf + yb)
        rings.append(section_ring(hw, yf, yb, 24, z, rig.face_front_exponent, 2.0, c))
    top, bottom = rig.head_profile[0], rig.head_profile[-1]
    skin = mk.loft(rings, ("pole", (0.0, top[2], top[0])), ("pole", (0.0, bottom[2] + 0.002, bottom[0])))
    t = rig.nose_tip
    nose = mk.ellipsoid((t[0], t[1] + rig.nose_half_width, t[2] + 0.003),
                        (rig.nose_half_width, rig.nose_half_width, 0.010), 10, 6)
    return [Part("mannequin.head", "skin", skin, "head"), Part("mannequin.nose", "skin", nose, "head")]


def eyes(rig: Rig):
    parts = []
    lo, lid = rig.eye_full_z[0], rig.eye_lid_z
    for side in SIDES:
        s = _side_name(side)
        cx = side * rig.eye_x
        a = 0.5 * (rig.eye_outer_x - rig.eye_inner_x)
        sclera = _face_ellipse(rig, cx, 0.5 * (lo + lid), a, 0.5 * (lid - lo), rig.sclera_relief, 8, 4)
        iw, ih = rig.iris_size
        iris = _face_ellipse(rig, cx, 0.5 * (lo + lid) + 0.0005, 0.5 * iw, 0.5 * (lid - lo) - 0.001,
                             rig.iris_relief, 6, 4)
        pw, ph = rig.pupil_size
        pupil = _face_ellipse(rig, cx, rig.pupil_center_z, 0.5 * pw, 0.5 * ph, rig.pupil_relief, 4, 4)
        hl = _face_ellipse(rig, cx + rig.highlight_dx, rig.highlight_z, 0.5 * rig.highlight_diameter,
                           0.5 * rig.highlight_diameter, rig.highlight_relief, 3, 3)
        parts += [Part(f"mannequin.sclera_{s}", "eye_white", sclera, "eyes"),
                  Part(f"mannequin.iris_{s}", "iris", iris, "eyes"),
                  Part(f"mannequin.pupil_{s}", "pupil", pupil, "eyes"),
                  Part(f"mannequin.highlight_{s}", "eye_white", hl, "eyes")]
    return parts


def face_marks(rig: Rig):
    parts = []
    for side in SIDES:
        s = _side_name(side)
        # upper-lid band along the lid line
        (x0, z0), (x1, z1) = rig.lid_band_inner, rig.lid_band_outer
        k = np.linspace(0.0, 1.0, 6)
        hh = 0.5 * np.interp(k, [0.0, 0.5, 1.0], [rig.lid_band_height[0], rig.lid_band_height[1],
                                                   rig.lid_band_height[1]])
        lid = _face_band(rig, side * (x0 + k * (x1 - x0)), z0 + k * (z1 - z0), hh, rig.lid_band_relief)
        # brow through inner, middle, outer
        bx = np.array([rig.brow_inner[0], rig.brow_mid[0], rig.brow_outer[0]])
        bz = np.array([rig.brow_inner[1], rig.brow_mid[1], rig.brow_outer[1]])
        xs = np.linspace(bx[0], bx[-1], 5)
        brow = _face_band(rig, side * xs, np.interp(xs, bx, bz),
                          0.5 * np.interp(xs, [bx[0], bx[-1]], list(rig.brow_width)), rig.brow_relief)
        parts += [Part(f"mannequin.lid_{s}", "face_marks", lid, "face_marks"),
                  Part(f"mannequin.brow_{s}", "face_marks", brow, "face_marks")]
    # omega mouth: two sagging arcs between the corners and the middle cusp
    hw = 0.5 * rig.mouth_width
    xs = np.linspace(-hw, hw, 9)
    base = rig.mouth_cusp_z + (rig.mouth_corner_z - rig.mouth_cusp_z) * np.abs(xs) / hw
    zc = base - rig.mouth_arc_sag * np.sin(np.pi * np.abs(xs) / hw)
    mouth = _face_band(rig, xs, zc, np.full(9, 0.5 * rig.mouth_band), rig.mouth_relief)
    parts.append(Part("mannequin.mouth", "face_marks", mouth, "face_marks"))
    return parts


# ---------------------------------------------------------------------------
# hair.py regions
# ---------------------------------------------------------------------------

def _dome_point(rig: Rig, p):
    """Point of the H1 ellipsoid on the ray from its centre through ``p``, and the outward normal there."""
    c = np.array(rig.dome_center, dtype=np.float64)
    ax, ayf, az = rig.dome_radii
    d = np.asarray(p, dtype=np.float64) - c
    r = np.array([ax, ayf if d[1] < 0 else rig.dome_back_radius, az])
    q = c + d / math.sqrt(float(np.sum((d / r) ** 2)))
    n = (q - c) / r ** 2
    return q, n / np.linalg.norm(n)


def hair(rig: Rig):
    c = np.array(rig.dome_center, dtype=np.float64)
    ax, ayf, az = rig.dome_radii
    # H1 dome: the ellipsoid from the crown down to dome_bottom_z; below the band its front retreats
    # inside the forehead (the bangs and the band cover it there)
    z_band = rig.bangs_top_z[0]
    rings = []
    for phi in np.radians(np.linspace(78.0, 0.0, 8)):
        z = max(rig.dome_bottom_z, c[2] + az * math.sin(phi))
        hw, yf, yb = rig.dome_section(z)
        k = min(1.0, max(0.0, (z_band - z) / (z_band - rig.hairline_z)))
        yf = (1.0 - k) * yf + k * (rig.head_section(z)[1] + 0.004)
        rings.append(section_ring(hw, yf, yb, 24, z, 2.0, 2.0, c[1]))
        if z <= rig.dome_bottom_z:
            break
    dome = mk.loft(rings, ("pole", (0.0, c[1], c[2] + az)), "flat", cap_groups=(1, 1))
    parts = [Part("mannequin.hair_dome", "hair", dome, "hair")]
    # H3 bangs: a slab from under the band down to the flat cut; inner surface off the forehead
    xs = np.linspace(-rig.bangs_half_width, rig.bangs_half_width, 13)
    cut = rig.bangs_cut_z
    top_mid, top_end = rig.bangs_top_z
    grid = np.zeros((len(xs), 5, 3))
    gap_top = (rig.bangs_outer_y[0] + rig.bangs_thickness) - rig.head_section(top_mid)[1]
    for i, x in enumerate(xs):
        zt = top_mid - (top_mid - top_end) * (x / rig.bangs_half_width) ** 2 + rig.bangs_top_extension
        for j, z in enumerate(np.linspace(zt, cut, 5)):
            g = rig.bangs_skin_gap + max(0.0, (z - cut) / (top_mid - cut)) * (gap_top - rig.bangs_skin_gap)
            grid[i, j] = rig.head_surface_point(x, z) + g * rig.head_normal(x, z)
    bangs = mk.thicken(grid, rig.bangs_thickness, offset="outward", away_from=rig.head_center,
                       groups={"front": 1, "back": 1, "rim": {"v0": 1, "v1": 2, "u0": 1, "u1": 1}})  # cut drawn
    parts.append(Part("mannequin.bangs", "hair", bangs, "hair"))
    # H5 the single stray strand, on her left
    pts = mk.resample_polyline(np.array(rig.strand_points), 12)
    strand = mk.sweep(pts, width=lambda s: rig.strand_width * min(1.0, 1.4 * (1.0 - s) + 0.05),
                      thickness=rig.strand_thickness, profile=mk.profile_lens(6), normals=pts - c,
                      start="round", end="pointed")
    parts.append(Part("mannequin.strand", "hair", strand, "hair"))
    # H4 sidelocks (object sidelocks): ribbons between the tabulated inner and outer edges
    for side in SIDES:
        rows = np.array(rig.sidelock_rows)
        inner = np.stack([side * rows[:, 1], rows[:, 2], rows[:, 0]], axis=1)
        outer = np.stack([side * rows[:, 3], rows[:, 4], rows[:, 0]], axis=1)
        path = 0.5 * (inner + outer)
        d = outer - inner
        width = np.linalg.norm(d, axis=1)
        nrm = np.stack([d[:, 1], -d[:, 0], np.zeros(len(d))], axis=1) * side    # forward / outward
        lock = mk.sweep(path, width=width, thickness=rig.sidelock_thickness, profile=mk.profile_lens(8, 0.5),
                        normals=nrm, start="round", end="flat", cap_groups=(1, 1))
        parts.append(Part(f"mannequin.sidelock_{_side_name(side)}", "hair", lock, "hair", obj="sidelocks"))
    # H2 side curtain + back sheet (object back_hair): one slab through the crescent / plate mid-surfaces
    k = 15
    cols = []
    for z, cy, axc, yb_o, t, y_end in rig.curtain_rows:
        a, b = axc - 0.5 * t, (yb_o - cy) - 0.5 * t
        s0 = max(-1.0, min(1.0, (y_end - cy) / b))
        phi = np.linspace(math.asin(s0), math.pi - math.asin(s0), k)
        cols.append((np.stack([a * np.cos(phi), cy + b * np.sin(phi), np.full(k, z)], axis=1), t))
    for z, hw, y_in, y_out, t in rig.back_sheet_rows:
        x = np.linspace(hw, -hw, k)
        y = 0.5 * (y_in + y_out) - 0.025 * (x / hw) ** 2
        cols.append((np.stack([x, y, np.full(k, z)], axis=1), t))
    grid = np.stack([p for p, _ in cols], axis=1)                       # (U = k across, V = rows down)
    th = np.tile(np.array([t for _, t in cols]), (k, 1))
    sheet = mk.thicken(grid, th, offset="centre", away_from=(0.0, 0.0, 1.2), groups="single")
    parts.append(Part("mannequin.back_hair", "hair", sheet, "hair", obj="back_hair"))
    return parts


def headband(rig: Rig):
    cl = np.array(rig.band_centreline)
    full = np.concatenate([cl[:0:-1] * [-1.0, 1.0, 1.0], cl])          # -x end ... midline ... +x end
    on = np.array([_dome_point(rig, p)[0] for p in full])
    nrm = np.array([_dome_point(rig, p)[1] for p in full])
    tang = np.gradient(on, axis=0)
    across = np.cross(tang, nrm)
    across /= np.linalg.norm(across, axis=1)[:, None]
    hw = 0.5 * rig.band_width
    base = on - rig.band_embed * nrm
    grid = np.stack([base - hw * across, base + hw * across], axis=1)
    band = mk.thicken(grid, rig.band_thickness, offset="outward", away_from=rig.head_center, groups="single")
    parts = [Part("mannequin.headband", "headband", band, "headband")]
    vis = np.abs(full[:, 0]) <= rig.band_visible_x
    top = (base + (rig.band_thickness - 0.0003) * nrm)[vis]
    a = across[vis]
    rw = 0.5 * rig.band_ridge_width
    ridge = mk.thicken(np.stack([top - rw * a, top + rw * a], axis=1), rig.band_ridge_height + 0.0003,
                       offset="outward", away_from=rig.head_center, groups="single")
    parts.append(Part("mannequin.headband_ridge", "uniform", ridge, "headband"))
    return parts


# ---------------------------------------------------------------------------
# body.py regions
# ---------------------------------------------------------------------------

def neck(rig: Rig):
    y0, y1 = rig.neck_y
    rings = [mk.ellipse_ring(rig.neck_half_width, 0.5 * (y1 - y0), 14, (0.0, 0.5 * (y0 + y1), z)) for z in rig.neck_z]
    return [Part("mannequin.neck", "skin", mk.loft(rings, "flat", "flat", cap_groups=(1, 1)), "neck")]


def torso(rig: Rig):
    rows = list(rig.blouse_rows)
    z0, hw0, yf0, yb0 = rows[0]
    y0, y1 = rig.neck_y
    rows[0] = (z0, rig.neck_half_width - 0.005, y0 + 0.004, y1 - 0.004)    # neckline inside the neck
    rings = [section_ring(hw, yf, yb, 24, z, rig.torso_exponent) for z, hw, yf, yb in rows]
    top = mk.loft(rings, ("pole", (0.0, 0.5 * (y0 + y1), z0 + 0.008)), "flat", cap_groups=(1, 1))
    return [Part("mannequin.blouse", "uniform", top, "torso")]


def _inside_blouse(rig: Rig, p) -> float:
    """Superellipse measure of ``p`` in the blouse section at its height (< 1 = inside)."""
    hw, yf, yb = rig.blouse_section(p[2])
    b = yb if p[1] > 0 else -yf
    e = rig.torso_exponent
    return (abs(p[0]) / hw) ** e + (abs(p[1]) / b) ** e


def _onto_blouse(rig: Rig, p, gap):
    """``p`` moved out of the blouse to ``gap`` above its surface along the gradient of the section
    measure (Newton steps onto the surface); unchanged when it is already outside."""
    def f(q):
        return _inside_blouse(rig, q) - 1.0

    q = np.array(p, dtype=np.float64)
    if f(q) >= 0.0:
        return q
    h = 1e-5
    for _ in range(30):
        g = np.array([(f(q + h * e) - f(q - h * e)) / (2 * h) for e in np.eye(3)])
        q = q - f(q) / float(g @ g) * g
        if abs(f(q)) < 1e-9:
            break
    g = np.array([(f(q + h * e) - f(q - h * e)) / (2 * h) for e in np.eye(3)])
    return q + gap * g / np.linalg.norm(g)


def _piece(points, fractions):
    """Points at the given arc-length fractions of the polyline ``points``."""
    P = np.asarray(points, dtype=np.float64)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)]) / seg.sum()
    return np.stack([np.interp(fractions, s, P[:, k]) for k in range(3)], axis=1)


def collar(rig: Rig):
    O, I = np.array(rig.collar_outer), np.array(rig.collar_inner)
    # left half from the back centre to just before the V tip, in three corresponding pieces: flap bottom
    # O1-O2 / I1-I2, flap side and shoulder O2-O5 / I2-I3, lapel O5-O9 / I3-I7
    f1, f2, f3 = np.linspace(0.0, 1.0, 5), np.linspace(0.0, 1.0, 9)[1:], np.linspace(0.0, 0.93, 7)[1:]
    outer = np.concatenate([_piece(O[:2], f1), _piece(O[1:5], f2), _piece(O[4:], f3)])
    inner = np.concatenate([_piece(I[:2], f1), _piece(I[1:3], f2), _piece(I[2:], f3)])
    mirror = np.array([-1.0, 1.0, 1.0])
    outer = np.concatenate([(outer[:0:-1] * mirror), outer])            # right V end ... back ... left V end
    inner = np.concatenate([(inner[:0:-1] * mirror), inner])
    rows = 5
    grid = np.zeros((len(outer), rows, 3))
    for j, t in enumerate(np.linspace(0.0, 1.0, rows)):
        for i in range(len(outer)):
            grid[i, j] = _onto_blouse(rig, (1.0 - t) * inner[i] + t * outer[i], 3 * rig.collar_gap)
    col = mk.thicken(grid, rig.collar_thickness, offset="outward", away_from=(0.0, 0.0, 1.10), groups="single")
    return [Part("mannequin.collar", "collar", col, "collar")]


def scarf(rig: Rig):
    parts = []
    S = np.array(rig.scarf_path)
    s = np.linspace(0.0, 1.0, len(S))
    w = np.interp(s, [0.0, 0.8, 1.0], [rig.scarf_width[0], rig.scarf_width[1], rig.scarf_width[1]])
    t = np.interp(s, [0.0, 0.8, 1.0], [rig.scarf_thickness[0], rig.scarf_thickness[1], rig.scarf_thickness[1]])
    for side in SIDES:
        path = S * [side, 1.0, 1.0]
        nrm = np.stack([2.0 * path[:, 0], -np.ones(len(path)), np.full(len(path), 0.35)], axis=1)
        ribbon = mk.sweep(path, width=w, thickness=t, profile=mk.profile_lens(8, 0.5), normals=nrm,
                          start="flat", end="flat", cap_groups=(1, 1))
        parts.append(Part(f"mannequin.scarf_ribbon_{_side_name(side)}", "scarf", ribbon, "scarf"))
    for side, root, point in ((1, rig.scarf_tip_root, rig.scarf_tip_point),
                              (-1, rig.scarf_tip_root_right, (-rig.scarf_tip_point[0], rig.scarf_tip_root_right[1],
                                                              rig.scarf_tip_point[2]))):
        root, point = np.array(root), np.array(point)
        f = np.array([0.0, 0.35, 0.7, 0.9, 1.0])
        path = root + f[:, None] * (point - root)
        wmax, at = rig.scarf_tip_max_width
        width = np.interp(f, [0.0, at, 0.9, 1.0], [rig.scarf_tip_root_width, wmax, 0.6 * wmax, 0.0])
        tip = mk.sweep(path, width=np.maximum(width, 1e-3), thickness=rig.scarf_tip_thickness,
                       profile=mk.profile_lens(8, 0.4), normals=np.tile([0.0, -1.0, 0.0], (len(path), 1)),
                       start="flat", end="pointed", cap_groups=(1, 1))
        parts.append(Part(f"mannequin.scarf_tip_{_side_name(side)}", "scarf", tip, "scarf"))
    # the ring (object ring): rounded box with two pink stripes
    c = np.array(rig.ring_center)
    w, d, h = rig.ring_size
    r = rig.ring_corner_radius
    rings = [mk.rounded_rect_ring(w, d, r, 16, (c[0], c[1], c[2] + dz)) for dz in (-(0.5 * h - r), 0.5 * h - r)]
    box = mk.loft(rings, ("dome", r, 2), ("dome", r, 2))
    parts.append(Part("mannequin.ring", "collar", box, "scarf", obj="ring"))
    e = 0.0004
    for k, zc in enumerate(rig.ring_stripe_z):
        hh = 0.5 * rig.ring_stripe_height
        grid = np.stack([mk.rounded_rect_ring(w - 2 * e, d - 2 * e, r - e, 16, (c[0], c[1], zc + dz))
                         for dz in (-hh, hh)], axis=1)
        band = mk.thicken(grid, rig.ring_stripe_relief + e, periodic_u=True, offset="outward",
                          away_from=c, groups="single")
        parts.append(Part(f"mannequin.ring_stripe{k}", "uniform", band, "scarf", obj="ring"))
    return parts


def skirt(rig: Rig):
    n = rig.skirt_pleats
    span = 2.0 * np.pi / n
    ang = np.concatenate([[k * span, (k + 0.8) * span] for k in range(n)])     # crest, valley (knife pleats)
    rings = []
    for z, hw, yf, yb in rig.skirt_rows:
        depth = rig.pleat_depth * min(1.0, max(0.0, (rig.pleat_top_z - z) / (rig.pleat_top_z - rig.skirt_hem_z)))
        ct, st = np.cos(ang), np.sin(ang)
        e = rig.skirt_exponent
        x = hw * np.sign(ct) * np.abs(ct) ** (2.0 / e)
        y = np.where(st > 0, yb, -yf) * np.sign(st) * np.abs(st) ** (2.0 / e)
        rad = np.hypot(x, y)
        k = 1.0 - depth * (np.arange(2 * n) % 2) / rad
        rings.append(np.stack([x * k, y * k, np.full(2 * n, z)], axis=1))
    # one group: pleats and hem draw as silhouettes (pleat creases as feature lines cost many rays)
    return [Part("mannequin.skirt", "skirt", mk.loft(rings, "pole", "pole", groups=1), "skirt")]


# ---------------------------------------------------------------------------
# limbs.py regions
# ---------------------------------------------------------------------------

def arms(rig: Rig):
    parts = []
    for side in SIDES:
        s, e, c = rig.shoulder_joint(side), rig.elbow(side), rig.cuff_edge(side)
        # the round sleeve cap starts 3 cm down the arm: centred on the joint, its 0.048 radius would reach
        # z 1.203 and poke through the collar on the shoulder top (O5)
        start = 0.03 / rig.upper_arm_length
        a = mk.resample_polyline(np.array([s + start * (e - s), e]), 5)
        b = mk.resample_polyline(np.array([e, c]), 5)
        path = np.concatenate([a, b[1:]])
        pos = np.concatenate([np.linspace(start, 1.0, 5), 1.0 + np.linspace(0.0, 1.0, 5)[1:] * (
            np.linalg.norm(c - e) / np.linalg.norm(rig.wrist(side) - e))])
        rad = np.array([rig.sleeve_radius(p) for p in pos])
        sleeve = mk.sweep(path, width=2 * rad, n_profile=12, start="round", end="flat")   # cuff rim drawn
        parts.append(Part(f"mannequin.sleeve_{_side_name(side)}", "uniform", sleeve, "arms"))
        d = rig.forearm_dir(side)
        R = rig.sleeve_radius(2.0)
        for k, (d0, d1) in enumerate(rig.cuff_stripes):
            band = mk.revolve([(R - 0.002, 0.0), (R + rig.cuff_stripe_relief, 0.0),
                               (R + rig.cuff_stripe_relief, d1 - d0), (R - 0.002, d1 - d0)], 16, closed=True,
                              groups=[1, 1, 1, 1])
            parts.append(Part(f"mannequin.cuff_{_side_name(side)}{k}", "collar", _local(band, c - d1 * d, d),
                              "arms", obj="cuffs"))
    return parts


def hands(rig: Rig):
    parts = []
    for side in SIDES:
        d = rig.hand_dir(side)
        start = rig.wrist(side) - rig.wrist_in_sleeve * d
        length = rig.hand_length + rig.wrist_in_sleeve
        a = math.radians(rig.palm_turn_back_deg)
        palm_normal = (-side * math.cos(a), math.sin(a), 0.0)          # medial, turned toward the back
        hand = mk.superellipsoid((0.0, 0.0, 0.0), (0.5 * rig.palm_thickness, 0.5 * rig.palm_width, 0.5 * length),
                                 12, 8, 2.4, 2.2)
        parts.append(Part(f"mannequin.hand_{_side_name(side)}", "skin",
                          _local(hand, start + 0.5 * length * d, d, x_hint=palm_normal), "hands"))
    return parts


_LEG_Z = (0.70, 0.60, 0.50, 0.42, 0.32, 0.20, 0.10)


def legs(rig: Rig):
    parts = []
    for side in SIDES:
        zs = [rig.leg_top_z] + list(_LEG_Z) + [rig.ankle_z]
        path = np.array([rig.leg_point(side, z) for z in zs])
        rad = np.array([rig.leg_radius(z) for z in zs])
        leg = mk.sweep(path, width=2 * rad, n_profile=12, start="round", end="round", up=(0.0, -1.0, 0.0))
        parts.append(Part(f"mannequin.leg_{_side_name(side)}", "skin", leg, "legs"))
    return parts


def socks(rig: Rig):
    parts = []
    for side in SIDES:
        zs = [0.030, rig.ankle_z, 0.10, 0.20, 0.32, rig.sock_top_z]
        path = np.array([rig.leg_point(side, z) for z in zs])
        rad = np.array([rig.leg_radius(z) for z in zs]) + rig.sock_ease
        sock = mk.sweep(path, width=2 * rad, n_profile=12, start="flat", end="flat", up=(0.0, -1.0, 0.0),
                        cap_groups=(1, None))                         # the sock-top rim draws
        parts.append(Part(f"mannequin.sock_{_side_name(side)}", "socks", sock, "socks"))
    return parts


def shoes(rig: Rig):
    parts = []
    L = rig.shoe_length
    for side in SIDES:
        d = rig.foot_dir(side)
        ctr = rig.heel_point(side) + d * (0.5 * L)
        rings = []
        for z, k, back in ((0.0, 1.0, 0.0), (rig.shoe_sole, 1.0, 0.0), (0.035, 0.95, 0.0),
                           (rig.shoe_topline_z + 0.010, 0.55, 0.30)):
            ring = mk.rounded_rect_ring(rig.shoe_ball_width * k, L * k, 0.45 * rig.shoe_ball_width * k, 20)
            yb = -0.15 * L                                              # ball line (local -Y = toe)
            heel = np.clip((ring[:, 1] - yb) / (0.5 * L - yb), 0.0, 1.0)
            ring[:, 0] *= 1.0 - heel * (1.0 - rig.shoe_heel_width / rig.shoe_ball_width)
            ring[:, 1] += back * 0.5 * L
            ring[:, 2] = z
            rings.append(ring)
        shoe = mk.loft(rings, "flat", "flat", groups=[1, 2, 2])           # sole line drawn
        ang = math.degrees(math.atan2(d[0], -d[1]))
        parts.append(Part(f"mannequin.shoe_{_side_name(side)}", "shoes", shoe.rotate("z", ang).translate(ctr), "shoes"))
    return parts


#: region -> builder, in a fixed order
BUILDERS = {
    "head": head, "eyes": eyes, "face_marks": face_marks,
    "hair": hair, "headband": headband,
    "neck": neck, "torso": torso, "collar": collar, "scarf": scarf, "skirt": skirt,
    "arms": arms, "hands": hands, "legs": legs, "socks": socks, "shoes": shoes,
}
REGIONS = tuple(BUILDERS)


def build(rig: Rig, regions=None) -> list:
    """Mannequin parts of ``regions`` (default: all), in :data:`REGIONS` order."""
    wanted = REGIONS if regions is None else tuple(r for r in REGIONS if r in set(regions))
    parts = []
    for name in wanted:
        parts.extend(BUILDERS[name](rig))
    return parts
