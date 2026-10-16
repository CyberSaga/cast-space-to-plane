"""Arms, sleeves, cuff stripes, hands, legs, socks and shoes of the Miki model (owner: body agent).

Part contract (see ``assemble.py`` and the toolkit guide): :func:`build` takes the
:class:`~miki_model.rig.Rig` and returns a list of :class:`~miki_model.meshkit.Part` covering **all** of
:data:`REGIONS`.  Objects / materials: each side's sleeve (uniform), its two cuff white stripes (collar), hand
and thumb (skin) -> ``obj="arm_l"`` / ``obj="arm_r"``; legs -> legs (skin); socks -> socks (socks); shoes -> shoes (shoes).

Lines (spec §F): the sleeve is one smooth group and its cuff (5 mm rim turning in to the opening + the
recessed disc) another, so the cuff rim always draws; the cuff stripes are single-group bands floating
0.25 mm above the sleeve, built on the sleeve's own section polygon, so both borders of each stripe draw as
silhouettes and cost no construction rays; hands, thumbs and legs are single groups (outlines only); the
sock top is a flat cap with its own group (the 1.5 mm step draws); each shoe has three groups: the sole
slab, the upper and the opening (the sole line and the topline always draw).
"""

from __future__ import annotations

import math

import numpy as np

from . import meshkit as mk
from .body import pending_rig
from .meshkit import Part
from .rig import Rig

__all__ = ["REGIONS", "build"]

#: The mannequin regions this module replaces.
REGIONS = ("arms", "hands", "legs", "socks", "shoes")

SIDES = (1, -1)

# ---------------------------------------------------------------------------------------------------
# Module constants (numbers the rig does not carry; see the report for the rig changes they suggest)
# ---------------------------------------------------------------------------------------------------
SLEEVE_POINTS = 10                 # sleeve section polygon (the cuff stripes reuse it)
SLEEVE_START = 0.025               # the round sleeve cap is centred this far down the upper arm: centred on
#                                    the joint its 0.048 radius would rise 2 cm above the shoulder and through
#                                    the collar (O5); here its top meets the blouse's shoulder at the acromion
STRIPE_FLOAT = 0.00025             # cuff stripes float this far above the sleeve
LEG_POINTS = 10
SOCK_POINTS = 12
LEG_Z = (0.720, 0.700, 0.500, 0.420, 0.370)          # the leg ends inside the sock
SOCK_Z = (0.025, 0.065, 0.200, 0.320, 0.385)          # from inside the shoe to the sock top
SHOE_OUTLINE_DEG = (0.0, 20.0, 42.0, 68.0, 98.0, 130.0, 158.0, 180.0)   # one side, toe -> heel
#: Sole half-width factor B(u) along the foot (u from the heel back); half-width = B * sin(theta).
SHOE_WIDTH = ((0.0, 0.060), (0.020, 0.056), (0.050, 0.0455), (0.100, 0.0435), (0.155, 0.0455),
              (0.195, 0.054), (0.225, 0.066))
SHOE_OPENING = (0.045, 0.052, 0.041, 0.0345)   # opening centre u, forward / back / lateral semi-axes
SHOE_TOPLINE_FRONT_Z = 0.063       # throat height (back / sides: rig.shoe_topline_z)
SHOE_OPENING_FLOOR = 0.030
STRAP_FLOAT = 0.0009               # the strap's chords cross the faceted upper: float it a little higher
SHOE_STRAP_U = 0.122                # saddle strap centre from the heel back (spec: y ~ -0.07)
SHOE_STRAP_POINTS = 11             # points along each strap border (7 sagged ~1.4 mm under the upper: dashed lines)
#: Hand sections (review r1, T8): the wrist is narrower than the heel of the palm (a ~7 mm step each side
#: within 15 mm) and the mitten tapers toward the fingertips (distances before scaling to hand_length).
HAND_WRIST = (0.0215, 0.0135)      # half-width, half-thickness at the wrist (and inside the sleeve)
HAND_PALM_HEEL = (0.015, 0.0285)   # distance from the wrist, half-width: the heel of the palm
HAND_FINGER_HALF_WIDTH = (0.029, 0.021)   # middle of the fingers, fingertips


def _side_name(side: int) -> str:
    return "l" if side > 0 else "r"


def _unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


def _sweep_loft(path, width, thickness, profile, normals, cap_start, cap_end, cap_groups=None, groups=1):
    """:func:`meshkit.sweep`'s rings (its frames) closed with any :func:`meshkit.loft` caps (e.g. a dome
    with one ring instead of the sweep's two)."""
    _m, (P, T, N, B) = mk.sweep(path, width=width, thickness=thickness, profile=profile, normals=normals,
                                return_frames=True)
    W = np.asarray(width, dtype=np.float64)
    TH = np.asarray(thickness, dtype=np.float64)
    prof = np.asarray(profile, dtype=np.float64)
    rings = [P[i] + prof[:, :1] * (0.5 * W[i]) * B[i] + prof[:, 1:2] * (0.5 * TH[i]) * N[i] for i in range(len(P))]
    return mk.loft(rings, cap_start, cap_end, groups=groups, cap_groups=cap_groups)


# ---------------------------------------------------------------------------------------------------
# sleeves + cuff stripes
# ---------------------------------------------------------------------------------------------------

def _sleeve(rig: Rig, side: int):
    J, E, C = rig.shoulder_joint(side), rig.elbow(side), rig.cuff_edge(side)
    d1, d2 = rig.upper_arm_dir(side), rig.forearm_dir(side)
    Lu = rig.upper_arm_length
    Lf = rig.forearm_length
    stations = [(J + SLEEVE_START * d1, SLEEVE_START / Lu),
                (E - 0.035 * d1, 1.0 - 0.035 / Lu), (E + 0.0 * d1, 1.0), (E + 0.035 * d2, 1.0 + 0.035 / Lf),
                (C - 0.045 * d2, 2.0), (C, 2.0)]
    # round the elbow: pull the elbow station toward the inside of the bend
    P = np.array([p for p, _ in stations])
    P[2] = 0.5 * P[2] + 0.25 * (P[1] + P[3])
    pos = np.array([q for _, q in stations])
    rad = np.array([rig.sleeve_radius(q) for q in pos])
    _m, (Pp, T, N, B) = mk.sweep(P, width=2 * rad, profile=mk.profile_ellipse(SLEEVE_POINTS), start="round",
                                 end="flat", return_frames=True)
    t = 2.0 * np.pi * np.arange(SLEEVE_POINTS) / SLEEVE_POINTS
    ct, st = np.cos(t)[:, None], np.sin(t)[:, None]
    rings = [Pp[i] + rad[i] * (ct * B[i] + st * N[i]) for i in range(len(Pp))]
    Bc, Nc = B[-1], N[-1]
    r_open = rig.cuff_opening_radius
    rings.append(C + r_open * (ct * Bc + st * Nc))                                  # the rim turning in
    rings.append(C - rig.cuff_recess * d2 + r_open * (ct * Bc + st * Nc))           # opening to the disc
    groups = [1] * (len(Pp) - 1) + [2, 2]
    sleeve = mk.loft(rings, ("dome", rad[0], 1), "flat", groups=groups, cap_groups=(None, 2))
    stripes = []
    R = rad[-1] + STRIPE_FLOAT
    for d0, d1_ in rig.cuff_stripes:
        lo, hi = (C - d * d2 + R * (ct * Bc + st * Nc) for d in (d0, d1_))
        stripes.append(mk.ridge_band(lo, hi, ct * Bc + st * Nc, rig.cuff_stripe_relief))
    return sleeve, stripes


# ---------------------------------------------------------------------------------------------------
# hands (mitten + thumb lobe)
# ---------------------------------------------------------------------------------------------------

def _hand(rig: Rig, side: int):
    W = rig.wrist(side)
    a0 = rig.hand_dir(side)
    tb = math.radians(rig.palm_turn_back_deg)
    p = np.array([-side * math.cos(tb), math.sin(tb), 0.0])        # palm normal: medial, turned back
    p = _unit(p - a0 * np.dot(p, a0))
    w = np.cross(a0, p)
    if w[1] > 0:                                                    # the thumb / index side is in front
        w = -w
    # centreline in the (a, p) plane: palm straight, fingers curled toward the palm
    c1, c2 = (math.radians(x) for x in rig.finger_curl_deg)
    pl, fl = rig.palm_length, rig.finger_length
    pts2 = [(-rig.wrist_in_sleeve, 0.0), (0.0, 0.0), (HAND_PALM_HEEL[0], 0.0), (0.035, 0.0), (pl, 0.0)]
    i_wrist, i_palm = 1, 4
    ang = c1
    x, y = pl, 0.0
    for seg, dang in ((0.5 * fl, c1), (0.5 * fl, c2)):
        x += seg * math.cos(ang)
        y += seg * math.sin(ang)
        pts2.append((x, y))
        ang += dang
    pts2 = np.array(pts2)
    tip = pts2[-1]
    rot = -math.atan2(tip[1], tip[0])
    k = rig.hand_length / float(np.hypot(*tip))
    cr, sr = math.cos(rot), math.sin(rot)
    pts2 = np.stack([cr * pts2[:, 0] - sr * pts2[:, 1], sr * pts2[:, 0] + cr * pts2[:, 1]], axis=1) * k
    path = np.array([W + q[0] * a0 + q[1] * p for q in pts2])
    # section half sizes (width along w, thickness along p) per station
    ww, wt = HAND_WRIST
    half_w = np.array([ww, ww, HAND_PALM_HEEL[1], 0.031, 0.5 * rig.palm_width + 0.001, *HAND_FINGER_HALF_WIDTH])
    half_t = np.array([wt, wt, 0.0125, 0.5 * rig.palm_thickness, 0.0105, 0.0090, 0.5 * rig.finger_tip_thickness])
    # thickness direction along the curl
    tang = np.gradient(path, axis=0)
    nrm = np.array([np.cross(w, t) for t in tang])
    nrm = np.array([n if np.dot(n, p) > 0 else -n for n in nrm])
    hand = _sweep_loft(path, 2 * half_w, 2 * half_t, mk.profile_rect(8, 2.6), nrm, "flat",
                       ("dome", 0.5 * rig.finger_tip_thickness, 1), cap_groups=(1, None))
    # thumb: a lobe from the index side of the palm base, lying forward along the index finger and
    # slightly toward the palm (the palm direction is the rotated centreline, not the chord)
    a_palm = _unit(path[i_palm] - path[i_wrist])
    base = path[i_wrist] + 0.010 * a_palm + 0.019 * w + 0.002 * p
    d_a = _unit(0.95 * a_palm + 0.25 * w + 0.10 * p)
    d_b = _unit(0.97 * a_palm + 0.02 * w + 0.20 * p)
    q1 = base + 0.024 * d_a
    q2 = q1 + 0.5 * (rig.thumb_length - 0.024) * d_b
    q3 = q1 + (rig.thumb_length - 0.024) * d_b
    tp = np.array([base, q1, q2, q3])
    th = rig.thumb_thickness
    thumb = _sweep_loft(tp, np.array([0.022, 0.020, 0.017, 0.014]), np.array([th, th, 0.9 * th, 0.8 * th]),
                        mk.profile_ellipse(6), np.tile(p, (4, 1)), "flat", ("dome", 0.006, 1), cap_groups=(1, None))
    return hand, thumb


# ---------------------------------------------------------------------------------------------------
# legs, socks
# ---------------------------------------------------------------------------------------------------

def _leg_tube(rig: Rig, side: int, zs, ease: float, n: int):
    path = np.array([rig.leg_point(side, z) for z in zs])
    rad = np.array([rig.leg_radius(z) for z in zs]) + ease
    return mk.sweep(path, width=2 * rad, profile=mk.profile_ellipse(n), up=(0.0, -1.0, 0.0), start="flat",
                    end="flat", cap_groups=(1, 1 if ease == 0 else None))


def _leg(rig: Rig, side: int):
    return _leg_tube(rig, side, LEG_Z, 0.0, LEG_POINTS)


def _sock(rig: Rig, side: int):
    # path from the bottom (inside the shoe) up to the sock top; the top cap gets its own group
    zs = SOCK_Z
    path = np.array([rig.leg_point(side, z) for z in zs])
    rad = np.array([rig.leg_radius(z) for z in zs]) + rig.sock_ease
    return mk.sweep(path, width=2 * rad, profile=mk.profile_ellipse(SOCK_POINTS), up=(0.0, -1.0, 0.0),
                    start="flat", end="flat", cap_groups=(1, None))


# ---------------------------------------------------------------------------------------------------
# shoes (penny loafers)
# ---------------------------------------------------------------------------------------------------

def _shoe(rig: Rig, side: int):
    L = rig.shoe_length
    n = 2 * len(SHOE_OUTLINE_DEG) - 2
    uc, a = 0.5 * L, 0.5 * L
    # outline angles, denser at the toe and the heel (a round toe, not a 12-gon point); 0 = toe
    half = np.radians(SHOE_OUTLINE_DEG)
    th = np.concatenate([half, 2.0 * np.pi - half[1:-1][::-1]])
    u = uc + a * np.cos(th)
    Bu = np.interp(u, [q[0] for q in SHOE_WIDTH], [q[1] for q in SHOE_WIDTH])
    v = Bu * np.sin(th)
    sole = rig.shoe_sole + (rig.shoe_heel_height - rig.shoe_sole) * np.clip((0.085 - u) / 0.035, 0.0, 1.0)
    uo, af, ab, al = SHOE_OPENING
    # topline loop: the point of the opening ellipse in the direction of each outline point
    phi = np.arctan2(v / al, np.where(u >= uo, (u - uo) / af, (u - uo) / ab))
    tu = uo + np.where(np.cos(phi) >= 0, af, ab) * np.cos(phi)
    tv = al * np.sin(phi)
    front = np.clip(np.cos(phi), 0.0, 1.0) ** 2
    tz = rig.shoe_topline_z + (SHOE_TOPLINE_FRONT_Z - rig.shoe_topline_z) * front
    rings = [np.stack([u, v, np.zeros(n)], axis=1), np.stack([u, v, sole], axis=1)]
    # the upper: from the sole line up and in to the topline (walls rise steeply, the vamp curves over)
    for t in (0.35, 0.7, 1.0):
        g = t ** 1.6
        h = math.sin(0.5 * math.pi * t) ** 0.7
        rings.append(np.stack([u + g * (tu - u), v + g * (tv - v), sole + h * (tz - sole)], axis=1))
    # inside the opening: the rim rolls in and down to a floor (the sock passes through it)
    d = np.stack([tu - uo, tv], axis=1)
    q = np.array([uo, 0.0]) + d * (1.0 - 0.003 / np.linalg.norm(d, axis=1))[:, None]
    rings.append(np.stack([q[:, 0], q[:, 1], tz - 0.006], axis=1))
    groups = [1, 2, 2, 2, 3]
    shoe = mk.loft(rings, "flat", ("pole", (uo, 0.0, SHOE_OPENING_FLOOR)), groups=groups, cap_groups=(1, 3))
    # saddle strap: a ridge band over the upper between two plane sections u = strap_u -+ width / 2
    upper = np.array([g == 2 for g in shoe.groups])
    su = SHOE_STRAP_U
    hw = 0.5 * rig.strap_width
    secs = [_plane_section(shoe, upper, su + k * hw) for k in (-1.0, 1.0)]
    m = SHOE_STRAP_POINTS
    A_, B_ = (mk.resample_polyline(sec, m) for sec in secs)
    mid = 0.5 * (A_ + B_)
    tang = np.gradient(mid, axis=0)
    nrm = np.cross(tang, np.array([1.0, 0.0, 0.0]))
    out = mid - np.array([su, 0.0, 0.0])
    nrm *= np.sign(np.einsum("ij,ij->i", nrm, out))[:, None]
    nrm /= np.linalg.norm(nrm, axis=1)[:, None]
    strap = mk.ridge_band(A_ + STRAP_FLOAT * nrm, B_ + STRAP_FLOAT * nrm, nrm, rig.strap_relief, periodic=False)
    # place: local (u, v, z) -> world; the axis passes under the ankle centre at u = rig.shoe_ankle_u
    f = rig.foot_dir(side)
    perp = np.array([-f[1], f[0], 0.0])                    # det [f, perp, z] = +1 (the shoe is symmetric in v)
    A = rig.ankle(side)
    origin = np.array([A[0], A[1], 0.0]) - rig.shoe_ankle_u * f
    M = np.stack([f, perp, np.array([0.0, 0.0, 1.0])], axis=1)
    return shoe.transform(M, origin), strap.transform(M, origin)


def _plane_section(mesh, mask, u0):
    """Ordered polyline where the plane ``x = u0`` cuts the faces ``mask`` of ``mesh`` (an open surface
    patch): from one border of the patch to the other, ordered by increasing y."""
    V = mesh.vertices
    pts, links = {}, {}
    for k, f in enumerate(mesh.faces):
        if not mask[k]:
            continue
        for j in range(1, len(f) - 1):
            tri = (f[0], f[j], f[j + 1])
            cut = []
            for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                da, db = V[a, 0] - u0, V[b, 0] - u0
                if (da < 0) != (db < 0):
                    key = (min(a, b), max(a, b))
                    if key not in pts:
                        t = da / (da - db)
                        pts[key] = V[a] + t * (V[b] - V[a])
                    cut.append(key)
            if len(cut) == 2:
                links.setdefault(cut[0], []).append(cut[1])
                links.setdefault(cut[1], []).append(cut[0])
    ends = sorted(k for k, v in links.items() if len(v) == 1)
    start = min(ends, key=lambda key: pts[key][1])
    chain, prev, cur = [start], None, start
    while True:
        nxt = [x for x in links[cur] if x != prev]
        if not nxt:
            break
        prev, cur = cur, nxt[0]
        chain.append(cur)
    P = np.array([pts[key] for key in chain])
    keep = np.concatenate([[True], np.linalg.norm(np.diff(P, axis=0), axis=1) > 1e-6])
    return P[keep]


# ---------------------------------------------------------------------------------------------------

def build(rig: Rig):
    """Parts of :data:`REGIONS` for ``rig``."""
    rig = pending_rig(rig)                 # the r1 shoulder / sleeve changes (body.PENDING_RIG)
    parts = []
    for side in SIDES:
        s = _side_name(side)
        sleeve, stripes = _sleeve(rig, side)
        parts.append(Part(f"limbs.sleeve_{s}", "uniform", sleeve, "arms", obj=f"arm_{s}"))
        for k, band in enumerate(stripes):
            parts.append(Part(f"limbs.cuff_stripe_{s}{k}", "collar", band, "arms", obj=f"arm_{s}"))
    for side in SIDES:
        s = _side_name(side)
        hand, thumb = _hand(rig, side)
        parts.append(Part(f"limbs.hand_{s}", "skin", hand, "hands", obj=f"arm_{s}"))
        parts.append(Part(f"limbs.thumb_{s}", "skin", thumb, "hands", obj=f"arm_{s}"))
    for side in SIDES:
        parts.append(Part(f"limbs.leg_{_side_name(side)}", "skin", _leg(rig, side), "legs"))
    for side in SIDES:
        parts.append(Part(f"limbs.sock_{_side_name(side)}", "socks", _sock(rig, side), "socks"))
    for side in SIDES:
        shoe, strap = _shoe(rig, side)
        parts.append(Part(f"limbs.shoe_{_side_name(side)}", "shoes", shoe, "shoes"))
        parts.append(Part(f"limbs.strap_{_side_name(side)}", "shoes", strap, "shoes"))
    return parts
