"""Placeholder (mannequin) parts for every region of the Reiya model, at SPEC.md's proportions.

Each region builder takes a :class:`~reiya_model.rig.Rig` and returns a list of :class:`charmodel.meshkit.Part`;
:func:`build` returns the parts of the requested regions.  The shapes are deliberately simple (lofted sections, slabs,
sweeps) but follow the rig's surface models and landmarks (the numeric character spec, SPEC.md), so a detailed
module (``head.py``, ``hair.py``, ``body.py``, ``cardigan.py``, ``limbs.py``) can be previewed in context
(``--only ... --context``) while the others are still placeholders, and the whole mannequin is a valid model of
its own (``--check`` passes with castplane ``warnings: []``).  Every part names its material and lands in the object
of ``assemble.OBJECTS`` that the real part will use (``obj=`` where the region's default object differs: the fringe,
the bob, the skirt, the cardigan's button, and by side the eyes, the face marks, the braids, the sleeves, the hands,
the socks and the shoes; the white sleeve tubes stay in ``top``, see :func:`top`).
The placeholders use one smooth group per shell wherever a line is not needed, so they draw as silhouettes and cost no
construction rays.

Regions (and the module that replaces them): ``head``, ``eyes`` (``eye_l`` / ``eye_r``), ``face_marks``
(``face_marks_l`` / ``face_marks_r``) (head.py); ``hair`` (with the fringe, object ``fringe``, and the bob, object
``bob``), ``tufts``, ``braids`` (``braid_l`` / ``braid_r``) (hair.py); ``neck``, ``top`` (the real sleeve tubes in
``arm_l`` / ``arm_r``), ``dress`` (with the skirt, object ``skirt``), ``buttons`` (body.py); ``cardigan`` (its
button in ``buttons``), ``sleeves`` (objects ``arm_l`` / ``arm_r``) (cardigan.py); ``hands`` (objects ``arm_l`` /
``arm_r``), ``legs``, ``socks`` (``sock_l`` / ``sock_r``), ``shoes`` (``shoe_l`` / ``shoe_r``) (limbs.py).

Every dimension comes from the rig; the module constants below are only resolutions (ring / grid counts) and the
few shape factors of the stand-ins, named.
"""

from __future__ import annotations

import math

import numpy as np

from charmodel import meshkit as mk
from charmodel.meshkit import Part

from .rig import Rig

__all__ = ["REGIONS", "BUILDERS", "build"]

SIDES = (1, -1)                    # her left (+X), her right (-X)

# -- resolutions of the stand-ins ------------------------------------------------------------------------------
HEAD_RING = 24                     # points per head / torso / bodice ring
HAIR_RING = 24                     # points per dome ring
SKIRT_RING = 32                    # a multiple of 2 * skirt_flutes: a vertex on every flute crest and valley
LIMB_RING = 12                     # legs, socks, sleeves
SHOE_RING = 20
#: Rows of the skirt's outer surface (a subset of ``rig.skirt_rows``: the A-line is nearly straight) and of its
#: inner facing between the hem and the ceiling.
SKIRT_OUTER_Z = (1.116, 1.060, 0.950, 0.827, 0.704, 0.581, 0.458)
SKIRT_INNER_Z = (0.520,)
BOB_COLUMNS = 25                   # bob grid: columns from her left front edge round the back to her right front edge
BOB_ROWS = 6
CARDIGAN_COLUMNS = 32              # cardigan grid: equal azimuth steps round the body (periodic)
CARDIGAN_ROWS = 6
SLEEVE_POSITIONS = (0.0, 0.5, 1.0, 1.4, 1.75, 1.95, 2.0)   # arm positions of the balloon sleeve's rings
LEG_Z = (0.700, 0.600, 0.520, 0.475, 0.420, 0.340, 0.250, 0.200, 0.150)  # leg rings between the top and the ankle
SOCK_Z = (0.190, 0.150, 0.110, 0.085, 0.050)                # sock rings between the cuff and the sole of the sock

# -- shape factors of the stand-ins (not spec values) -----------------------------------------------------------
DOME_TUCK = 0.006                  # the dome's lower rings shrink this much to tuck under the bob ...
DOME_TUCK_Z = 1.533                # ... starting at this hair row
FRINGE_TOP_Z = 1.540               # the fringe slab starts inside the dome here
FRINGE_X = (-0.024, 0.060)         # the fringe slab's x range (TRUE x; the forehead shows on her right)
BOB_WRAP_DEG = 40.0                # the bob's inner surface turns in to the front edge over this azimuth range
BOB_TOP_TAPER = 0.3                # the bob's top row has this fraction of its thickness (its top edge under the dome)
TUFT_ROOT_DEPTH = 0.020            # the tuft's root ring sits this far below its base centre (inside the dome)
SOCK_BOTTOM_Z = 0.030              # the sock starts inside the shoe
SOCK_TOP_GAP = 0.005               # the sock tube ends this far under the cuff top (inside the cuff)
CUFF_DOME = 0.004                  # the sock cuff's rounded top
SHOE_TOP_LENGTH = 0.55             # the shoe's top ring (topline) spans this fraction of the length from the heel
SLEEVE_CUFF_TUCK = 0.008           # the ribbed cuff starts this far inside the balloon's gather
STRAP_TUCK = 0.005                 # the strap starts this far inside the bodice


def _s(side: int) -> str:
    return "l" if side > 0 else "r"


def _smoothstep(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def _polar_point(section, z: float, phi_deg: float, exponent: float, back_exponent=None) -> np.ndarray:
    """Point of the section ``(hw, yf, yb)`` (superellipse, centre at the mid depth) on the ray from its centre at
    azimuth ``phi`` (0 front -Y, 90 her left +X, 180 back), at height ``z``."""
    hw, yf, yb = section
    c = 0.5 * (yf + yb)
    p = math.radians(phi_deg)
    sx, cy = math.sin(p), -math.cos(p)
    back = cy > 0.0
    semi = (yb - c) if back else (c - yf)
    e = (exponent if back_exponent is None else back_exponent) if back else exponent
    if abs(sx) < 1e-12:
        r = semi
    elif abs(cy) < 1e-12:
        r = hw
    else:
        r = 1.0 / ((abs(sx) / hw) ** e + (abs(cy) / semi) ** e) ** (1.0 / e)
    return np.array([r * sx, c + r * cy, z])


def _azimuth(x: float, y: float, c: float) -> float:
    """Azimuth (degrees, 0 front, 90 her left) of ``(x, y)`` seen from ``(0, c)``."""
    return math.degrees(math.atan2(x, c - y))


def _face_slab(rig: Rig, pts_xz, relief: float, depth: float) -> mk.Mesh:
    """Slab conforming to the face: ``pts_xz`` ``(U, V, 2)`` face points; the back face lies ``depth`` below the skin,
    the front face ``relief`` above it (one smooth group)."""
    P = np.asarray(pts_xz, dtype=np.float64)
    U, V = P.shape[:2]
    grid = np.zeros((U, V, 3))
    for i in range(U):
        for j in range(V):
            x, z = float(P[i, j, 0]), float(P[i, j, 1])
            grid[i, j] = rig.head_surface_point(x, z) - depth * rig.head_normal(x, z)
    return mk.thicken(grid, depth + relief, offset="outward", away_from=rig.head_center, groups="single")


def _face_ellipse(rig: Rig, cx: float, cz: float, a: float, b: float, relief: float, nu: int = 6,
                  nv: int = 4) -> mk.Mesh:
    """Elliptic face slab (centre ``(cx, cz)``, semi-axes ``a`` in x, ``b`` in z) from a square grid mapped onto the
    disc."""
    u = np.linspace(-1.0, 1.0, nu)
    v = np.linspace(-1.0, 1.0, nv)
    pts = np.zeros((nu, nv, 2))
    for i, uu in enumerate(u):
        for j, vv in enumerate(v):
            pts[i, j] = (cx + a * uu * math.sqrt(1.0 - 0.5 * vv * vv), cz + b * vv * math.sqrt(1.0 - 0.5 * uu * uu))
    return _face_slab(rig, pts, relief, rig.eye_slab_depth)


def _face_band(rig: Rig, xs, zc, half_h, relief: float) -> mk.Mesh:
    """Band on the face along ``xs`` with centre heights ``zc`` and half heights ``half_h`` (arrays)."""
    xs, zc, hh = (np.asarray(a, dtype=np.float64) for a in (xs, zc, half_h))
    pts = np.stack([np.stack([xs, zc - hh], axis=1), np.stack([xs, zc + hh], axis=1)], axis=1)
    return _face_slab(rig, pts, relief, rig.eye_slab_depth)


def _circle_loft(centres, radii, n: int, cap_start, cap_end) -> mk.Mesh:
    """Solid through horizontal circles (one smooth group, caps in the same group)."""
    rings = [mk.ellipse_ring(float(r), float(r), n, c) for c, r in zip(centres, radii)]
    return mk.loft(rings, cap_start, cap_end, groups=1, cap_groups=(1, 1))


# ---------------------------------------------------------------------------
# head.py regions
# ---------------------------------------------------------------------------

def _jaw_y(rig: Rig, z: float) -> float:
    ys, zs = zip(*rig.jaw_underside)
    return float(np.interp(z, zs, ys))


def head(rig: Rig):
    """The skin head lofted through ``rig.head_profile`` (the jaw underside as the back below the nape) and the nose
    bump as a small half-buried ellipsoid."""
    rings = []
    for z, hw, yf, yb in rig.head_profile:
        if hw <= 0.0:
            continue
        c = rig.face_offset(z)
        if yb is None:                                   # below the nape: the jaw underside is the back
            yb = _jaw_y(rig, z)
            c = 0.5 * (yf + yb)
        rings.append(rig.section_ring((hw, yf, yb), HEAD_RING, z, rig.face_front_exponent, 2.0, c))
    top, bottom = rig.head_profile[0], rig.head_profile[-1]
    skin = mk.loft(rings[::-1], ("pole", (0.0, bottom[2] + 0.002, bottom[0])), ("pole", (0.0, top[2], top[0])))
    tx, _ty, tz = rig.nose_tip
    nose = mk.ellipsoid((tx, rig.head_surface_y(tx, tz), tz),
                        (rig.nose_half_width, rig.nose_proud, 0.5 * (rig.nose_bridge_z - rig.nose_base_z)), 10, 6)
    return [Part("mannequin.head", "skin", skin, "head"), Part("mannequin.nose", "skin", nose, "head")]


def eyes(rig: Rig):
    """Per eye: sclera over the opening, iris (clipped to the opening's height), pupil, the larger highlight."""
    parts = []
    lo = min(z for _, z in rig.sclera_lower)
    hi = max(z for _, z in rig.eye_lid_line)
    a = 0.5 * (rig.eye_outer_x - rig.eye_inner_x)
    b = 0.5 * (hi - lo)
    zc = 0.5 * (lo + hi)
    for side in SIDES:
        s = _s(side)
        colour = "blue" if side > 0 else "red"           # heterochromia: her left (+x) blue, her right red
        cx = side * rig.eye_x
        sclera = _face_ellipse(rig, cx, zc, a, b, rig.sclera_relief, 8, 4)
        iw, ih = rig.iris_size
        ib = min(0.5 * ih, b - 0.001)
        iz = min(max(rig.iris_center_z, lo + ib + 0.0005), hi - ib - 0.0005)
        iris = _face_ellipse(rig, cx, iz, 0.5 * iw, ib, rig.iris_relief, 6, 4)
        pw, ph = rig.pupil_size
        pupil = _face_ellipse(rig, cx, rig.pupil_center_z, 0.5 * pw, 0.5 * ph, rig.pupil_relief, 4, 4)
        dx, hz, hd = rig.highlights[0]
        hl = _face_ellipse(rig, cx + dx, hz, 0.5 * hd, 0.5 * hd, rig.highlight_relief, 3, 3)
        parts += [Part(f"mannequin.sclera_{s}", "eye_white", sclera, "eyes", obj=f"eye_{s}"),
                  Part(f"mannequin.iris_{s}", f"iris_{colour}", iris, "eyes", obj=f"eye_{s}"),
                  Part(f"mannequin.pupil_{s}", f"pupil_{colour}", pupil, "eyes", obj=f"eye_{s}"),
                  Part(f"mannequin.highlight_{s}", "eye_white", hl, "eyes", obj=f"eye_{s}")]
    return parts


def face_marks(rig: Rig):
    """Upper lash bands (the lower edge along the lid line) and brows (both sides) and the closed-smile mouth."""
    parts = []
    (x0, z0), (x1, z1) = rig.lash_inner, rig.lash_outer
    lid = [(x, z) for x, z in rig.eye_lid_line if x0 < x < x1]
    edge_x = np.array([x0] + [x for x, _ in lid] + [x1])
    edge_z = np.array([z0] + [z for _, z in lid] + [z1])
    for side in SIDES:
        s = _s(side)
        k = np.linspace(0.0, 1.0, 6)
        xs = x0 + k * (x1 - x0)
        h = np.interp(k, [0.0, 0.5, 1.0], list(rig.lash_height))
        lower = np.interp(xs, edge_x, edge_z)
        lash = _face_band(rig, side * xs, lower + 0.5 * h, 0.5 * h, rig.lash_relief)
        bx = np.array([rig.brow_inner[0], rig.brow_mid[0], rig.brow_outer[0]])
        bz = np.array([rig.brow_inner[1], rig.brow_mid[1], rig.brow_outer[1]])
        xs = np.linspace(bx[0], bx[-1], 5)
        brow = _face_band(rig, side * xs, np.interp(xs, bx, bz),
                          0.5 * np.interp(xs, [bx[0], bx[-1]], list(rig.brow_width)), rig.brow_relief)
        parts += [Part(f"mannequin.lash_{s}", "lashes", lash, "face_marks", obj=f"face_marks_{s}"),
                  Part(f"mannequin.brow_{s}", "face_marks", brow, "face_marks", obj=f"face_marks_{s}")]
    cxm, czm = rig.mouth_corners
    xs = np.linspace(-cxm, cxm, 9)
    zc = rig.mouth_bottom_z + (czm - rig.mouth_bottom_z) * (xs / cxm) ** 2
    mouth = _face_band(rig, xs, zc, np.full(9, 0.5 * rig.mouth_band), rig.mouth_relief)
    parts.append(Part("mannequin.mouth", "face_marks", mouth, "face_marks", obj="face_marks_l"))
    return parts


# ---------------------------------------------------------------------------
# hair.py regions
# ---------------------------------------------------------------------------

def _fringe_tip_z(rig: Rig, x: float) -> float:
    tips = sorted((lk[2], lk[3]) for lk in rig.fringe_locks)
    return float(np.interp(x, [t[0] for t in tips], [t[1] for t in tips]))


def _bob_frame(rig: Rig, z: float, f: float):
    """``(row, azimuth, edge azimuth)`` of the bob at height ``z`` and fraction ``f`` of the way from the front edge
    (0) to the back centre (1) on her left: ``row = (hw, yb, front_x, front_y, t, yf)`` (``yf`` of the hair
    section, clamped at the widest row), the azimuth round the section centre."""
    hw, yb, fx, fy, t = rig.bob_row(z)
    yf = rig.hair_section(max(z, rig.hair_rows[-1][0]))[1]
    pe = _azimuth(fx, fy, 0.5 * (yf + yb))
    return (hw, yb, fx, fy, t, yf), pe + f * (180.0 - pe), pe


def hair(rig: Rig):
    """The dome (the hair silhouette from the crown down to ``dome_bottom_z``, its lower rings tucked under the bob
    and its front retreating to the fringe), a fringe slab off the forehead, and the bob (object ``bob``): a crescent
    slab from the temple to the tip line, its inner surface turning in to the front edge beside the face."""
    # dome
    ft = rig.fringe_thickness + rig.fringe_gap[0]
    zs = [r[0] for r in rig.hair_rows if rig.dome_bottom_z < r[0] < rig.hair_rows[0][0]] + [rig.dome_bottom_z]
    ef, eb = rig.hair_exponent
    rings = []
    for z in zs:
        hw, yf, yb = rig.hair_section(z)
        k = _smoothstep((DOME_TUCK_Z - z) / (DOME_TUCK_Z - rig.dome_bottom_z))
        hw, yb = hw - k * DOME_TUCK, yb - k * DOME_TUCK
        yf = (1.0 - k) * yf + k * (rig.head_surface_y(0.0, z) - ft + DOME_TUCK)
        rings.append(rig.section_ring((hw, yf, yb), HAIR_RING, z, ef, eb))
    crown = rig.hair_rows[0]
    dome = mk.loft(rings, ("pole", (0.0, crown[2], crown[0])), "flat", cap_groups=(1, 1))
    parts = [Part("mannequin.hair_dome", "hair", dome, "hair")]
    # fringe: a slab from inside the dome down to the lock tips, off the forehead by fringe_gap
    xs = np.linspace(FRINGE_X[0], FRINGE_X[1], 9)
    nv = 4
    grid = np.zeros((len(xs), nv, 3))
    for i, x in enumerate(xs):
        tip = _fringe_tip_z(rig, float(x))
        for j in range(nv):
            t = j / (nv - 1)
            z = FRINGE_TOP_Z + t * (tip - FRINGE_TOP_Z)
            gap = rig.fringe_gap[0] + t * (rig.fringe_gap[1] - rig.fringe_gap[0])
            grid[i, j] = rig.head_surface_point(float(x), z) + gap * rig.head_normal(float(x), z)
    fringe = mk.thicken(grid, rig.fringe_thickness, offset="outward", away_from=rig.head_center, groups="single")
    parts.append(Part("mannequin.fringe", "hair", fringe, "hair", obj="fringe"))
    # bob (object bob): grid of the crescent's inner surface, grown outward by its thickness
    z_top = rig.bob_rows[0][0]
    U, V = BOB_COLUMNS, BOB_ROWS
    grid = np.zeros((U, V, 3))
    thick = np.zeros((U, V))
    for i in range(U):
        s = i / (U - 1)                                  # 0: her left front edge, 0.5: back centre, 1: her right
        side = 1 if s <= 0.5 else -1
        f = 2.0 * s if side > 0 else 2.0 * (1.0 - s)     # 0 at the front edge, 1 at the back centre
        z_hem = rig.bob_hem(_bob_frame(rig, z_top, f)[1])   # the column's tip-line height (its top azimuth)
        for j in range(V):
            z = z_top + (j / (V - 1)) * (z_hem - z_top)
            (hw, yb, fx, fy, t, yf), phi, pe = _bob_frame(rig, z, f)
            inner = _polar_point((hw - t, yf + t, yb - t), z, phi, ef, eb)
            w = _smoothstep(1.0 - (phi - pe) / BOB_WRAP_DEG)
            p = (1.0 - w) * inner + w * np.array([fx, fy, z])
            p[0] *= side
            grid[i, j] = p
            thick[i, j] = t * (BOB_TOP_TAPER if j == 0 else 1.0)
    bob = mk.thicken(grid, thick, offset="outward", away_from=rig.head_center, groups="single")
    parts.append(Part("mannequin.bob", "hair", bob, "hair", obj="bob"))
    return parts


def tufts(rig: Rig):
    """Two ear-tuft nubs: a lens plate (``tuft_base_size`` wide, ``tuft_thickness`` thick along the cup normal) from
    a root buried in the dome straight to the tip (no hook)."""
    parts = []
    W = rig.tuft_base_size[0]
    us = (-TUFT_ROOT_DEPTH, 0.0, 0.30, 0.60, 0.85, 1.0)
    widths = (W, W, 0.97 * W, 0.80 * W, 0.50 * W, 0.2 * W)
    for side in SIDES:
        base, tip, cup = rig.tuft_frame(side)
        axis = tip - base
        length = math.sqrt(float(axis[0] * axis[0] + axis[1] * axis[1] + axis[2] * axis[2]))
        path = []
        for u in us:
            uu = u / length if u < 0.0 else u
            path.append(base + uu * axis)
        nub = mk.sweep(np.array(path), width=np.array(widths), thickness=rig.tuft_thickness,
                       profile=mk.profile_lens(10, 0.8), normals=np.tile(cup, (len(path), 1)), start="flat",
                       end="pointed", cap_groups=(1, 1))
        parts.append(Part(f"mannequin.tuft_{_s(side)}", "hair", nub, "tufts"))
    return parts


def braids(rig: Rig):
    """Two braid tubes along ``braid_path`` (root hidden in the curtain to the tie), ending in one pointed lock at
    the mean of the end-tuft tips."""
    parts = []
    tips = np.array(rig.braid_tuft_tips)
    tuft_tip = tips.mean(axis=0)
    n = len(rig.braid_path)
    widths = [rig.braid_width] * (n - 1) + [2.0 * rig.braid_tie_radius, rig.braid_tuft_width]
    thicks = [rig.braid_thickness] * (n - 1) + [2.0 * rig.braid_tie_radius, rig.braid_tuft_thickness]
    for side in SIDES:
        path = np.array([rig.at(p, side) for p in rig.braid_path] + [rig.at(tuft_tip, side)])
        nrm = np.tile([float(side), 0.0, 0.0], (len(path), 1))
        tube = mk.sweep(path, width=np.array(widths), thickness=np.array(thicks), profile=mk.profile_ellipse(8),
                        normals=nrm, start="round", end="pointed")
        parts.append(Part(f"mannequin.braid_{_s(side)}", "hair", tube, "braids", obj=f"braid_{_s(side)}"))
    return parts


# ---------------------------------------------------------------------------
# body.py regions
# ---------------------------------------------------------------------------

def neck(rig: Rig):
    hw, yf, yb = rig.neck_section(rig.neck_z_mid)
    rings = [mk.ellipse_ring(hw, 0.5 * (yb - yf), 14, (0.0, 0.5 * (yf + yb), z)) for z in rig.neck_z]
    return [Part("mannequin.neck", "skin", mk.loft(rings, "flat", "flat", cap_groups=(1, 1)), "neck")]


def top(rig: Rig):
    """The mock neck and the top's torso as one loft (its rim drawn), and the two white sleeve tubes."""
    zs = [r[0] for r in rig.mock_neck_rows[:-1]]
    rings = [rig.ring("mock_neck", z, HEAD_RING) for z in zs]
    rings += [rig.ring("top", r[0], HEAD_RING) for r in rig.top_rows]
    torso = mk.loft(rings, "flat", "flat", groups=1, cap_groups=(2, 1))     # the rim draws; the buried end does not
    parts = [Part("mannequin.top", "top", torso, "top")]
    pos = (0.0, 0.5 * rig.top_sleeve_end, rig.top_sleeve_end)
    radii = [float(np.interp(p, [q for q, _ in rig.top_sleeve_radii], [r for _, r in rig.top_sleeve_radii]))
             for p in pos]
    for side in SIDES:
        path = np.array([rig.arm_point(side, p) for p in pos])
        tube = mk.sweep(path, width=2.0 * np.array(radii), profile=mk.profile_ellipse(10), start="round", end="flat",
                        cap_groups=(1, 1))
        # object top, not the real tube's arm_l / arm_r: this stand-in lies wholly inside the stand-in balloon, and an
        # object may not hold a shell buried in another (the real tube starts inside the torso, outside the balloon)
        parts.append(Part(f"mannequin.top_sleeve_{_s(side)}", "top", tube, "top"))
    return parts


def _skirt_ring(rig: Rig, z, inset: float = 0.0) -> np.ndarray:
    """Skirt ring at ``z`` (a float, or ``None`` for the hem: each point at ``skirt_hem_at`` of its azimuth), moved
    ``inset`` towards the section centre."""
    out = np.zeros((SKIRT_RING, 3))
    for i in range(SKIRT_RING):
        phi = 360.0 * i / SKIRT_RING + 90.0                 # ring angle 0 (+X) = azimuth 90, as rig.skirt_ring
        zz = rig.skirt_hem_at(phi) if z is None else z
        p = rig.skirt_point(zz, phi)
        if inset:
            _hw, yf, yb = rig.skirt_section(zz)
            c = np.array([0.0, 0.5 * (yf + yb), zz])
            d = p - c
            r = math.sqrt(float(d[0] * d[0] + d[1] * d[1]))
            p = c + d * (1.0 - inset / r)
        out[i] = p
    return out


def dress(rig: Rig):
    """The bodice (its neckline rim drawn), the two straps (object ``bodice``) and the skirt (object ``skirt``): the
    fluted outer surface, the hem rim and an inner facing up to the ceiling, one smooth group."""
    rings = [rig.ring("bodice", r[0], HEAD_RING) for r in rig.bodice_rows]
    bodice = mk.loft(rings, "flat", "flat", groups=1, cap_groups=(2, 1))
    parts = [Part("mannequin.bodice", "dress", bodice, "dress")]
    w = rig.strap_x[1] - rig.strap_x[0]
    for side in SIDES:
        path = np.array([rig.at(p, side) for p in rig.strap_path])
        d = path[1] - path[0]
        path = np.concatenate([[path[0] - STRAP_TUCK * d / math.sqrt(float(d @ d))], path])
        ref = np.array([path[0][0], 0.5 * (rig.strap_path[0][1] + rig.strap_path[-1][1]), rig.neckline_top_z])
        tube = mk.sweep(path, width=w, thickness=rig.strap_thickness, profile=mk.profile_rect(8, 4.0),
                        normals=path - ref, start="flat", end="flat", cap_groups=(1, 1))
        parts.append(Part(f"mannequin.strap_{_s(side)}", "dress", tube, "dress"))
    t = rig.skirt_thickness
    rings = [_skirt_ring(rig, z) for z in SKIRT_OUTER_Z] + [_skirt_ring(rig, None), _skirt_ring(rig, None, t)]
    rings += [_skirt_ring(rig, z, t) for z in SKIRT_INNER_Z] + [_skirt_ring(rig, rig.skirt_ceiling_z, t)]
    skirt = mk.loft(rings, "flat", "flat", groups=1, cap_groups=(1, 1))
    parts.append(Part("mannequin.skirt", "dress", skirt, "dress", obj="skirt"))
    return parts


def buttons(rig: Rig):
    """The dress buttons: small ellipsoids half sunk into the centre front."""
    bw, bh = rig.button_size
    parts = []
    for k, z in enumerate(rig.button_positions()):
        m = mk.ellipsoid((0.0, rig.dress_front_y(z), z), (0.5 * bw, rig.button_relief, 0.5 * bh), 6, 3)
        parts.append(Part(f"mannequin.button{k:02d}", "buttons", m, "buttons"))
    return parts


# ---------------------------------------------------------------------------
# cardigan.py regions
# ---------------------------------------------------------------------------

def _cardigan_tables(rig: Rig):
    """``(neckline, hem)``: ``[(azimuth, z)]`` of the top edge and the lower edge on her left half, by azimuth."""
    top = []
    for x, y, z in rig.cardigan_neckline:
        hw, yf, yb = rig.cardigan_section(z)
        top.append((_azimuth(x, y, 0.5 * (yf + yb)), z))
    hem = []
    for x, z in rig.cardigan_front_hem:
        hw, yf, yb = rig.cardigan_section(z)
        y = rig.cardigan_surface_y(x, z, True)
        hem.append((_azimuth(x, y, 0.5 * (yf + yb)) if x < hw else 90.0, z))
    hem.append((180.0, rig.cardigan_back_hem_z))
    return sorted(top), sorted(hem)


def cardigan(rig: Rig):
    """The cardigan as one ring-shaped slab on its reference surface, from the neckline (the back boat line, the
    dropped shoulders, the deep V closing at the crossing) down to the hem, grown outward by its thickness; the
    crossover is not modelled.  Its button sits on the centre front."""
    top_t, hem_t = _cardigan_tables(rig)
    U, V = CARDIGAN_COLUMNS, CARDIGAN_ROWS
    grid = np.zeros((U, V, 3))
    for i in range(U):
        phi = 360.0 * i / U
        a = phi if phi <= 180.0 else 360.0 - phi              # mirrored azimuth on her left
        z0 = float(np.interp(a, [p for p, _ in top_t], [z for _, z in top_t]))
        z1 = float(np.interp(a, [p for p, _ in hem_t], [z for _, z in hem_t]))
        for j in range(V):
            z = z0 + (j / (V - 1)) * (z1 - z0)
            grid[i, j] = _polar_point(rig.cardigan_section(z), z, phi, rig.body_exponent)
    centre = (0.0, 0.5 * (rig.cardigan_rows[0][2] + rig.cardigan_rows[0][3]), rig.seam_z)
    panels = mk.thicken(grid, rig.cardigan_thickness, periodic_u=True, offset="outward", away_from=centre,
                        groups="single")
    parts = [Part("mannequin.cardigan", "cardigan", panels, "cardigan")]
    bx, bz = rig.cardigan_button
    hw, yf, yb = rig.cardigan_outer_section(bz)
    front = _polar_point((hw, yf, yb), bz, _azimuth(bx, yf, 0.5 * (yf + yb)), rig.body_exponent)
    r = 0.5 * rig.cardigan_button_diameter
    button = mk.ellipsoid((bx, float(front[1]), bz), (r, rig.cardigan_button_relief, r), 8, 4)
    parts.append(Part("mannequin.cardigan_button", "buttons", button, "cardigan", obj="buttons"))
    return parts


def sleeves(rig: Rig):
    """Per arm (object ``arm_l`` / ``arm_r``): the balloon sleeve swept through ``sleeve_center`` with its lateral
    and depth radii, and the long cuff cone from inside the gather to its mouth past the knuckles, flaring from
    ``cuff_radius`` to ``cuff_end_radius`` (its lower rim drawn)."""
    parts = []
    pos = SLEEVE_POSITIONS
    widths = np.array([2.0 * rig.sleeve_radii_at(p)[0] for p in pos])
    depths = np.array([2.0 * rig.sleeve_radii_at(p)[1] for p in pos])
    for side in SIDES:
        obj = f"arm_{_s(side)}"
        path = np.array([rig.sleeve_center(side, p) for p in pos])
        nrm = np.tile([0.0, 1.0, 0.0], (len(path), 1))
        balloon = mk.sweep(path, width=widths, thickness=depths, profile=mk.profile_ellipse(LIMB_RING), normals=nrm,
                           start="round", end="flat", cap_groups=(1, 1))
        parts.append(Part(f"mannequin.sleeve_{_s(side)}", "cardigan", balloon, "sleeves", obj=obj))
        d = rig.forearm_dir(side)
        a, b = rig.cuff_start(side) - SLEEVE_CUFF_TUCK * d, rig.cuff_end(side)
        cpath = np.array([a, 0.5 * (a + b), b])
        cw = 2.0 * np.array([rig.cuff_radius_at(u) for u in (0.0, 0.5 * rig.cuff_length, rig.cuff_length)])
        cuff = mk.sweep(cpath, width=cw, profile=mk.profile_ellipse(LIMB_RING), start="flat", end="flat",
                        cap_groups=(1, None))
        parts.append(Part(f"mannequin.cuff_{_s(side)}", "cardigan", cuff, "sleeves", obj=obj))
    return parts


# ---------------------------------------------------------------------------
# limbs.py regions
# ---------------------------------------------------------------------------

def hands(rig: Rig):
    """Per arm: a hand paddle (palm width, palm thickness along the palm normal) from the wrist along the cuff to its
    mouth and on to the middle fingertip."""
    parts = []
    for side in SIDES:
        w, _d, n, _a = rig.hand_frame(side)
        ce = rig.cuff_end(side)
        tip = rig.fingertip(side)
        path = np.array([w, ce, 0.5 * (ce + tip), tip])
        W, T = rig.palm_width, rig.palm_thickness
        paddle = mk.sweep(path, width=np.array([0.85 * W, 0.95 * W, W, 0.75 * W]),
                          thickness=np.array([0.9 * T, T, 0.8 * T, 0.5 * T]), profile=mk.profile_rect(12, 3.0),
                          normals=np.tile(n, (len(path), 1)), start="flat", end="round", cap_groups=(1, 1))
        parts.append(Part(f"mannequin.hand_{_s(side)}", "skin", paddle, "hands", obj=f"arm_{_s(side)}"))
    return parts


def legs(rig: Rig):
    parts = []
    zs = (rig.leg_top_z,) + LEG_Z + (rig.ankle_z,)
    for side in SIDES:
        centres = [rig.leg_point(side, z) for z in zs]
        radii = [rig.leg_radius(z) for z in zs]
        leg = _circle_loft(centres, radii, LIMB_RING, ("dome", 0.5 * radii[0]), ("dome", 0.5 * radii[-1]))
        parts.append(Part(f"mannequin.leg_{_s(side)}", "skin", leg, "legs"))
    return parts


def socks(rig: Rig):
    """Per leg: the sock tube from inside the shoe to inside the cuff and the turned-down cuff (its lower edge drawn
    as a silhouette, its top rounded)."""
    parts = []
    c0, c1 = rig.sock_cuff_z
    for side in SIDES:
        zs = (c1 - SOCK_TOP_GAP,) + SOCK_Z + (SOCK_BOTTOM_Z,)
        sock = _circle_loft([rig.leg_point(side, z) for z in zs], [rig.leg_radius(z) + rig.sock_ease for z in zs],
                            LIMB_RING, "flat", "flat")
        parts.append(Part(f"mannequin.sock_{_s(side)}", "socks", sock, "socks", obj=f"sock_{_s(side)}"))
        zs = (c0, c1 - CUFF_DOME)
        cuff = _circle_loft([rig.leg_point(side, z) for z in zs], [rig.leg_radius(z) + rig.sock_cuff_ease for z in zs],
                            LIMB_RING, "flat", ("dome", CUFF_DOME))
        parts.append(Part(f"mannequin.sock_cuff_{_s(side)}", "socks", cuff, "socks", obj=f"sock_{_s(side)}"))
    return parts


def shoes(rig: Rig):
    """Per foot: a loafer block lofted from the sole outline (narrowing to the heel) up to a topline ring round the
    heel half; the sole line and the topline rim draw."""
    parts = []
    L = rig.shoe_length
    for side in SIDES:
        d = rig.foot_dir(side)
        ctr = rig.heel_point(side) + d * (0.5 * L)
        rings = []
        for z, k in ((0.0, 1.0), (rig.shoe_sole, 1.0), (rig.shoe_toe_height, 0.95)):
            ring = mk.rounded_rect_ring(rig.shoe_ball_width * k, L * k, 0.45 * rig.shoe_ball_width * k, SHOE_RING)
            yb = (0.5 - rig.shoe_ball_u) * L                # ball line (local -Y = toe, +Y = heel)
            heel = np.clip((ring[:, 1] - yb) / (0.5 * L - yb), 0.0, 1.0)
            ring[:, 0] *= 1.0 - heel * (1.0 - rig.shoe_heel_width / rig.shoe_ball_width)
            ring[:, 2] = z
            rings.append(ring)
        tl = SHOE_TOP_LENGTH * L
        ring = mk.rounded_rect_ring(rig.shoe_heel_width, tl, 0.45 * rig.shoe_heel_width, SHOE_RING,
                                    (0.0, 0.5 * L - 0.5 * tl, 0.0))
        ring[:, 2] = rig.shoe_topline_z[1]
        rings.append(ring)
        shoe = mk.loft(rings, "flat", "flat", groups=[1, 2, 2], cap_groups=(1, None))   # sole line + topline drawn
        ang = math.degrees(math.atan2(d[0], -d[1]))
        parts.append(Part(f"mannequin.shoe_{_s(side)}", "shoes", shoe.rotate("z", ang).translate(ctr), "shoes",
                          obj=f"shoe_{_s(side)}"))
    return parts


#: region -> builder, in a fixed order (the module order of ``assemble.MODULES``)
BUILDERS = {
    "head": head, "eyes": eyes, "face_marks": face_marks,
    "hair": hair, "tufts": tufts, "braids": braids,
    "neck": neck, "top": top, "dress": dress, "buttons": buttons,
    "cardigan": cardigan, "sleeves": sleeves,
    "hands": hands, "legs": legs, "socks": socks, "shoes": shoes,
}
REGIONS = tuple(BUILDERS)


def build(rig: Rig, regions=None) -> list:
    """Mannequin parts of ``regions`` (default: all), in :data:`REGIONS` order."""
    wanted = REGIONS if regions is None else tuple(r for r in REGIONS if r in set(regions))
    parts = []
    for name in wanted:
        parts.extend(BUILDERS[name](rig))
    return parts
