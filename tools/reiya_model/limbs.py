"""Hands, legs, socks and shoes of the Reiya model (SPEC.md §D.8, §D.9): regions ``hands``, ``legs``, ``socks`` and
``shoes``.

Regions and the objects they fill (SPEC.md §G, module -> regions mapping):

* ``hands`` -> no default object: each part sets ``obj="arm_l"`` (her left, ``+X``) or ``obj="arm_r"``, the object of
  the sleeve of :mod:`reiya_model.cardigan` on that side: the relaxed open hand, palm forward, with five fingers
  held close together and curled at their joints, the thumb beside the index (``skin``; Decision 3) (§D.8);
* ``legs`` -> object ``legs``: the two bare legs from inside the skirt ceiling to inside the socks (``skin``) (§D.9);
* ``socks`` -> no default object: each part sets ``obj="sock_l"`` / ``obj="sock_r"``: per leg the white calf sock
  (bending forward into the shoe at the ankle), its turned-down cuff and the navy star on its outer side (``socks``,
  ``star``) (§D.9);
* ``shoes`` -> no default object: each part sets ``obj="shoe_l"`` / ``obj="shoe_r"``: per foot the brown penny loafer:
  the shoe with its arched sole, the separate block heel, the saddle strap with the penny slot (a shallow recess in
  its top) and the raised moc-toe apron seam (``shoes``) (§D.9).  One compact object per foot: the hidden-line pass
  then tests a sample on one foot only against that foot's shoe and sock.

How the lines come out (SPEC.md §F; castplane draws an edge between different smooth groups always, an edge inside
one group only on the camera silhouette):

* the palm and every finger are separate single-group shells: outlines only, no construction rays; the fingers'
  tubes start inside the palm block, which runs out of the cuff's mouth for about 1.5 cm (the back of the hand), so
  the broad digits part from the hand below the cuff, each bent at its first joint, to their rounded tips;
* the legs are single-group tubes; the sock tube too (its top ends inside the cuff fold);
* the cuff fold is a separate shell: its outer face and its inside slope are one group and its bottom face another,
  so the fold's lower edge always draws and its top rim draws as an outline;
* the star is a decal on one flat facet of the cuff: its front face stands ``star_relief`` proud and its walls are
  undercut (the back outline smaller), so its whole outline draws as a silhouette and costs no rays;
* the shoe has three groups: the sole (its wall and the arched bottom), the upper, and the inside of the foot opening;
  so the sole line (rising from the forefoot to the heel) and the topline always draw.  The block heel is a separate
  single-group shell (its edges draw as its outline).  The toe box is blunt: its top slopes gently down from the
  ball to the tip, where its front drops almost vertically to the sole (SHOE_TOE_INSET).  The saddle strap
  (``shoe_strap_relief`` thick) and the apron piping (a rounded U of APRON_STATIONS stations round the toe, laid on
  the upper as it is drawn, its twisted quads split) are separate single-group bands whose borders float
  ``shoe_decal_float`` over the faceted upper, so both of their borders draw as silhouettes; the penny slot is a strip
  of the strap's top sunk ``penny_slot_depth`` in its own group, so its outline draws (no shell of its own: no shadow
  loop, Decision 14's outline at a fraction of the cost).

Every right-side part is the mirror image of the left one (:meth:`charmodel.meshkit.Mesh.mirror_x`): the figure is
symmetric here (SPEC.md §E).
"""

from __future__ import annotations

import math

import numpy as np

from charmodel import meshkit as mk
from charmodel.meshkit import Part

from .rig import Rig

__all__ = ["REGIONS", "build"]

#: The regions this module builds (``--only limbs`` selects all of them).
REGIONS = ("hands", "legs", "socks", "shoes")

# ---------------------------------------------------------------------------------------------------------------
# Resolutions and shape factors (every dimension comes from the rig)
# ---------------------------------------------------------------------------------------------------------------
PALM_POINTS = 8                    # palm section (rounded rectangle)
PALM_RECT_EXPONENT = 3.0
PALM_STATIONS = (0.45, 0.92)       # the palm block's start (inside the cuff, behind its recess) and end (just short
#                                    of the knuckle line), as fractions of palm_length from the wrist
PALM_WIDTH_END = 0.88              # palm width at its end (the knuckles), a fraction of palm_width: the block's
#                                    corners stay inside the thumb's and the little finger's roots (no step in the
#                                    hand's outline where they leave it)
FINGER_POINTS = 6                  # finger section (hexagon; two vertices on the width axis = on the outline)
FINGER_SEGMENT = 0.50              # the first phalanx (to the first joint's ring), a fraction of the finger length;
#                                    the rest bends there and again before the tip by the finger's curl (towards the
#                                    palm), so the relaxed curl shows as a bent finger
#: The rounded tip, as deep as half the section's smaller axis: one ring at this fraction of the depth past the
#: second joint with this fraction of the tip's size, then the apex.
FINGER_TIP_RING = (0.5, 0.87)
FINGER_FLAT = (1.15, 0.90)         # section width / thickness factors (a finger is a little wider than thick)
FINGER_START = 0.010               # each finger tube starts this far back inside the palm
LEG_POINTS = 8                     # legs, sock tube and cuff fold share this count (and phase) round the leg
LEG_Z = (0.400, 0.340, 0.290)      # leg rings between leg_top_z and leg_bottom_z (below the hem: the calf)
SHOE_HEEL_U = (0.5,)               # outline points round the heel, fractions of the heel radius from the back
SHOE_TOE_U = (0.45, 0.80)          # outline points round the toe, fractions of the toe radius from its start
SHOE_TOE_NARROW = 0.95             # half width where the toe starts rounding, fraction of the ball's
#: The upper's middle ring: each sole-edge point moves this far (fractions u, v, z) towards its topline point.
SHOE_UPPER_MID = (0.08, 0.15, 0.55)
#: The toe box in front of the ball: its top edge (the upper's middle ring) slopes from shoe_toe_height at the ball
#: down to shoe_toe_tip_height at the tip (quadratic in the distance past the ball), and its inset towards the topline
#: changes by this much (a fraction of the way to its topline point, also quadratic; added to SHOE_UPPER_MID[0]):
#: negative brings the edge forward over the sole's toe, so the front drops almost vertically to the sole (a blunt moc
#: toe, review r4-L5: 0.12 made a 2 cm sloping wedge, a doorstop in profile).
SHOE_TOE_INSET = -0.04
SHOE_HEEL_INSET = 0.0006           # the block heel's footprint lies this far inside the sole outline
SHOE_HEEL_INTO = 0.003             # ... and its top this far inside the shoe (no shared vertices)
STRAP_SIDE_STATIONS = 1            # stations of the saddle strap between each of its ends and its middle step,
STRAP_SLOT_STEP = 1.3              # ... which holds the penny slot and is this many slot lengths long
STRAP_BEVEL = 0.25                 # the strap's raised top is inset this fraction of its width at each border
APRON_STATIONS = 11                # stations along the apron's U (a rounded U round the toe)
APRON_HEIGHT = 0.7                 # the piping's ridge height, fraction of apron_relief over its float
APRON_SPLIT_DEG = 1.0              # the piping's quads twisted more than this (where it crosses from the vamp's
#                                    steep sides onto the flat toe box) are split into their two fan triangles
#                                    (meshkit.split_twisted), so castplane's facing and occlusion agree
PROBE = 0.05                       # rays that find a surface start this far outside it

SIDES = (1, -1)


def _s(side: int) -> str:
    return "l" if side > 0 else "r"


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    return v / math.sqrt(float(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))


def _dot(a, b) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def _mirror(mesh: mk.Mesh, side: int) -> mk.Mesh:
    return mesh if side > 0 else mesh.mirror_x()


def _mirror_fan(mesh: mk.Mesh, side: int) -> mk.Mesh:
    """:func:`_mirror` with every quad on its valley fan diagonal (:func:`charmodel.meshkit.inscribed_fan`): a ridge
    diagonal near the outline bulges over the quad's own silhouette edge in projection, and the hidden-line pass then
    drops a piece of the limb's outline (review round 3, r3-T1)."""
    return mk.inscribed_fan(_mirror(mesh, side))


# ---------------------------------------------------------------------------------------------------------------
# hands (§D.8): palm block + five fanned finger tubes
# ---------------------------------------------------------------------------------------------------------------

def _palm(rig: Rig) -> mk.Mesh:
    """The palm: a rounded slab along the hand axis, palm_width across (towards the thumb) and palm_thickness along
    the palm normal, narrowing / thinning to its end at the knuckles (PALM_WIDTH_END, palm_end_thickness); it starts
    inside the cuff, behind the cuff's recess (PALM_STATIONS), so its start is never seen."""
    w, d, n, _a = rig.hand_frame(1)
    pl, W, T = rig.palm_length, rig.palm_width, rig.palm_thickness
    s0, s1 = PALM_STATIONS
    path = np.array([w + s0 * pl * d, w + s1 * pl * d])
    widths = np.array([W, PALM_WIDTH_END * W])
    thick = np.array([T, rig.palm_end_thickness])
    return mk.sweep(path, width=widths, thickness=thick, profile=mk.profile_rect(PALM_POINTS, PALM_RECT_EXPONENT),
                    normals=np.tile(n, (2, 1)), start="flat", end="flat", cap_groups=(1, 1))


def _bend(d, n, deg: float) -> np.ndarray:
    """``d`` turned by ``deg`` towards ``n`` (the palm side: a finger's curl)."""
    m = _unit(n - d * _dot(n, d))
    a = math.radians(deg)
    return _unit(d * math.cos(a) + m * math.sin(a))


def _finger(rig: Rig, name: str) -> mk.Mesh:
    """One digit: a hexagonal tube from inside the palm to the first joint's ring (FINGER_SEGMENT of its length), on
    to a smaller ring just past the second joint and a rounded tip (the apex).  Both joints bend by the finger's curl
    towards the palm, and the tip ends at the finger's length along the curled chain, so the finger reads as bent at
    its first joint (a relaxed hand), at the triangles of a straight tube with a round tip.  It tapers linearly to
    finger_taper of its base thickness at the second joint."""
    base, d, n = rig.finger_base(1, name)
    _, _across, _along, length, thick, _fan, curl = rig.finger(name)
    fw, ft = FINGER_FLAT
    r_tip = 0.5 * thick * rig.finger_taper
    tip = min(fw, ft) * r_tip                                   # the round tip's depth
    a_ring, k_ring = FINGER_TIP_RING
    s1 = FINGER_SEGMENT
    s2 = 1.0 - s1 - tip / length
    joint = base + s1 * length * d
    cur = _bend(d, n, curl)
    p = joint + s2 * length * cur                               # the second joint
    cur = _bend(cur, n, curl)
    r_joint = 0.5 * thick + (r_tip - 0.5 * thick) * s1 / (s1 + s2)
    pts = [base - FINGER_START * d, joint, p + a_ring * tip * cur, p + tip * cur]
    rad = np.array([0.5 * thick, r_joint, k_ring * r_tip, r_tip])
    return mk.sweep(np.array(pts), width=2.0 * fw * rad, thickness=2.0 * ft * rad,
                    profile=mk.profile_ellipse(FINGER_POINTS), normals=np.tile(n, (len(pts), 1)), start="flat",
                    end="pointed", cap_groups=(1, None))


def _hand_parts(rig: Rig):
    palm = _palm(rig)
    fingers = mk.merge([_finger(rig, row[0]) for row in rig.fingers])
    parts = []
    for side in SIDES:
        obj = f"arm_{_s(side)}"
        parts.append(Part(f"limbs.palm_{_s(side)}", "skin", _mirror_fan(palm, side), "hands", obj=obj))
        parts.append(Part(f"limbs.fingers_{_s(side)}", "skin", _mirror_fan(fingers, side), "hands", obj=obj))
    return parts


# ---------------------------------------------------------------------------------------------------------------
# legs and socks (§D.9)
# ---------------------------------------------------------------------------------------------------------------

def _leg(rig: Rig) -> mk.Mesh:
    zs = (rig.leg_top_z,) + LEG_Z + (rig.leg_bottom_z,)
    path = np.array([rig.leg_point(1, z) for z in zs])
    rad = np.array([rig.leg_radius(z) for z in zs])
    return mk.sweep(path, width=2.0 * rad, profile=mk.profile_ellipse(LEG_POINTS),
                    normals=np.tile([0.0, -1.0, 0.0], (len(zs), 1)), start="flat", end="flat", cap_groups=(1, 1))


def _foot_point(rig: Rig, u: float, z: float) -> np.ndarray:
    """Point ``u`` along the left foot from the heel back, at height ``z``."""
    return rig.heel_point(1) + u * rig.foot_dir(1) + np.array([0.0, 0.0, z])


def _sock(rig: Rig) -> mk.Mesh:
    """The sock tube: the leg + sock_ease from inside the cuff down to the ankle, where it bends forward along the foot
    into the shoe (the instep fills the shoe's opening up to the throat)."""
    zs = (rig.sock_tube_top_z,)
    path = [rig.leg_point(1, z) for z in zs] + [rig.ankle(1)]
    wid = [2.0 * (rig.leg_radius(z) + rig.sock_ease) for z in zs]
    wid.append(2.0 * (rig.leg_radius(rig.ankle_z) + rig.sock_ease - rig.sock_ankle_squeeze))
    thk = list(wid)
    front, up = np.array([0.0, -1.0, 0.0]), np.array([0.0, 0.0, 1.0])
    nrm = [front] * len(zs) + [_unit(front + up)]
    for (u, z), (fw, ft) in zip(rig.sock_foot_path, rig.sock_foot_size):
        path.append(_foot_point(rig, u, z))
        wid.append(fw)
        thk.append(ft)
        nrm.append(up)
    return mk.sweep(np.array(path), width=np.array(wid), thickness=np.array(thk),
                    profile=mk.profile_ellipse(LEG_POINTS), normals=np.array(nrm), start="flat", end="flat",
                    cap_groups=(1, 1))


def _cuff_frame(rig: Rig):
    """``(axis centre (x, y), phase deg, star angle deg)`` of her left sock's cuff fold: the polygon (LEG_POINTS sides)
    is turned so that one facet's centre faces the star's azimuth (``star_azimuth_deg`` from the front towards her
    outer side)."""
    c0, c1 = rig.sock_cuff_z
    ctr = rig.leg_point(1, 0.5 * (c0 + c1))
    star = math.degrees(math.atan2(-math.cos(math.radians(rig.star_azimuth_deg)),
                                   math.sin(math.radians(rig.star_azimuth_deg))))   # angle from +X (counter-clockwise)
    phase = star - 180.0 / LEG_POINTS
    return ctr, phase, star


def _cuff(rig: Rig) -> mk.Mesh:
    """The turned-down cuff: a closed fold (the outer face up to the rim and the inside slope back down one group, the
    bottom face another, so its lower edge always draws), its outer radius the leg + sock_cuff_ease,
    sock_cuff_thickness thick at the bottom."""
    c0, c1 = rig.sock_cuff_z
    ctr, phase, _ = _cuff_frame(rig)
    r0 = rig.leg_radius(c0) + rig.sock_cuff_ease
    r1 = rig.leg_radius(c1) + rig.sock_cuff_ease
    prof = [(r0, c0), (r1, c1), (r0 - rig.sock_cuff_thickness, c0)]
    prof = np.array([(r, z - ctr[2]) for r, z in prof])
    return mk.revolve(prof, LEG_POINTS, groups=[1, 1, 2], closed=True, center=ctr, phase_deg=phase)


def _star(rig: Rig) -> mk.Mesh:
    """The navy 5-point star on the cuff facet that faces ``star_azimuth_deg``: front face star_relief proud (5 kites
    round the centre), back face star_depth inside the facet, undercut walls."""
    c0, c1 = rig.sock_cuff_z
    ctr, phase, star = _cuff_frame(rig)
    r0 = rig.leg_radius(c0) + rig.sock_cuff_ease
    r1 = rig.leg_radius(c1) + rig.sock_cuff_ease
    zt, rt = c1, r1                                             # the outer face runs from (r0, c0) to (r1, c1)
    a0, a1 = math.radians(phase), math.radians(phase + 360.0 / LEG_POINTS)
    A = np.array([ctr[0] + r0 * math.cos(a0), ctr[1] + r0 * math.sin(a0), c0])
    B = np.array([ctr[0] + r0 * math.cos(a1), ctr[1] + r0 * math.sin(a1), c0])
    D = np.array([ctr[0] + rt * math.cos(a0), ctr[1] + rt * math.sin(a0), zt])
    C = np.array([ctr[0] + rt * math.cos(a1), ctr[1] + rt * math.sin(a1), zt])
    e1 = _unit(B - A)
    nf = _unit(np.cross(B - A, D - A))
    if _dot(nf, [math.cos(math.radians(star)), math.sin(math.radians(star)), 0.0]) < 0.0:
        nf = -nf
    e2 = _unit(np.cross(nf, e1))
    if e2[2] < 0.0:
        e2 = -e2
    lo, hi = 0.5 * (A + B), 0.5 * (D + C)
    centre = lo + (hi - lo) * ((rig.star_center_z - lo[2]) / (hi[2] - lo[2]))
    ro, ri = rig.star_radii
    u = rig.star_undercut
    loop, back = [], []
    for k in range(5):
        for r, extra in ((ro, 0.0), (ri, 36.0)):
            t = math.radians(90.0 + 72.0 * k + extra)
            dirn = e1 * math.cos(t) + e2 * math.sin(t)
            loop.append(centre + rig.star_relief * nf + r * dirn)
            back.append(centre - rig.star_depth * nf + r * (1.0 - u / ri) * dirn)
    V = [centre + rig.star_relief * nf] + loop + [centre - rig.star_depth * nf] + back
    nb = 1 + len(loop)
    faces = []
    m = len(loop)
    for k in range(5):
        o, i_prev, i_next = 2 * k, (2 * k - 1) % m, 2 * k + 1
        faces.append([0, 1 + i_prev, 1 + o, 1 + i_next])
        faces.append([nb, nb + 1 + i_next, nb + 1 + o, nb + 1 + i_prev])
    for j in range(m):
        k = (j + 1) % m
        faces.append([1 + k, 1 + j, nb + 1 + j, nb + 1 + k])
    return mk._outward(mk.Mesh(np.array(V), faces, 1))


def _leg_parts(rig: Rig):
    leg, sock, cuff, star = _leg(rig), _sock(rig), _cuff(rig), _star(rig)
    parts = []
    for side in SIDES:
        parts.append(Part(f"limbs.leg_{_s(side)}", "skin", _mirror_fan(leg, side), "legs"))
    for side in SIDES:
        obj = f"sock_{_s(side)}"
        parts.append(Part(f"limbs.sock_{_s(side)}", "socks", _mirror_fan(sock, side), "socks", obj=obj))
        parts.append(Part(f"limbs.sock_cuff_{_s(side)}", "socks", _mirror_fan(cuff, side), "socks", obj=obj))
        parts.append(Part(f"limbs.sock_star_{_s(side)}", "star", _mirror(star, side), "socks", obj=obj))
    return parts


# ---------------------------------------------------------------------------------------------------------------
# shoes (§D.9, Decision 14): built in the shoe's own frame (x = u along the foot from the heel back, y = v across,
# z up) for her left foot, then placed on the heel point and mirrored for her right
# ---------------------------------------------------------------------------------------------------------------

def _shoe_half_width(rig: Rig, u: float) -> float:
    """Half width of the sole outline at ``u``: a round heel, straight sides widening to the ball, a rounded toe."""
    L = rig.shoe_length
    hr = 0.5 * rig.shoe_heel_width
    hb = 0.5 * rig.shoe_ball_width
    ub = rig.shoe_ball_u * L
    tr = rig.shoe_toe_radius
    ht = SHOE_TOE_NARROW * hb
    if u <= hr:
        return math.sqrt(max(0.0, hr * hr - (hr - u) ** 2))
    if u <= ub:
        return hr + (hb - hr) * (u - hr) / (ub - hr)
    if u <= L - tr:
        return hb + (ht - hb) * (u - ub) / (L - tr - ub)
    q = (u - (L - tr)) / tr
    return ht * math.sqrt(max(0.0, 1.0 - q * q))


def _shoe_outline_u(rig: Rig):
    """The outline stations along one side (heel -> toe): round the heel, the block heel's front, the ball contact,
    the ball, round the toe."""
    L = rig.shoe_length
    hr = 0.5 * rig.shoe_heel_width
    tr = rig.shoe_toe_radius
    heel = [f * hr for f in SHOE_HEEL_U]
    toe = [L - tr + f * tr for f in SHOE_TOE_U]
    return heel + [rig.shoe_heel_length, rig.shoe_ball_contact_u * L, rig.shoe_ball_u * L] + toe


def _sole_z(rig: Rig, u: float):
    """``(bottom, top)`` of the sole at ``u``: on the block heel at the back, the arch rising from the ball contact
    to the heel, flat on the ground under the forefoot."""
    uh, uc = rig.shoe_heel_length, rig.shoe_ball_contact_u * rig.shoe_length
    hh, ht = rig.shoe_heel_height, rig.shoe_heel_height + rig.shoe_heel_sole
    if u <= uh:
        return hh, ht
    if u >= uc:
        return 0.0, rig.shoe_sole
    t = (uc - u) / (uc - uh)
    return hh * t, rig.shoe_sole + (ht - rig.shoe_sole) * t


def _topline(rig: Rig, u: float, v: float):
    """The topline (foot-opening loop) point in the direction of the outline point ``(u, v)`` seen from the
    opening's centre, with its height: the heel back, the sides, the throat on the instep."""
    ob, of, oh = rig.shoe_opening
    uo, au = 0.5 * (ob + of), 0.5 * (of - ob)
    phi = math.atan2(v / oh, (u - uo) / au)
    cp, sp = math.cos(phi), math.sin(phi)
    zb, zs = rig.shoe_topline_z
    z = zs + (zb - zs) * max(0.0, -cp) ** 2 + (rig.shoe_throat_z - zs) * max(0.0, cp) ** 2
    return np.array([uo + au * cp, oh * sp, z])


def _shoe_body(rig: Rig):
    """The loafer without its heel block and decals, in the shoe frame: rings from the sole's bottom outline (on the
    block heel, the arch, the forefoot on the ground) to the sole line, the upper's middle (in front of the ball the
    moc toe box's top edge, sloping gently down to the tip, its front almost vertical: a blunt toe, SHOE_TOE_INSET),
    the topline loop and the opening's straight inner wall down to its flat floor.  Groups: sole 1, upper 2,
    opening 3."""
    L = rig.shoe_length
    side_u = _shoe_outline_u(rig)
    pts = [(L, 0.0)] + [(u, _shoe_half_width(rig, u)) for u in reversed(side_u)] + [(0.0, 0.0)] + \
          [(u, -_shoe_half_width(rig, u)) for u in side_u]
    ku, kv, kz = SHOE_UPPER_MID
    ub = rig.shoe_ball_u * L
    r0, r1, r2, r3, r4 = [], [], [], [], []
    for u, v in pts:
        zb, zt = _sole_z(rig, u)
        top = _topline(rig, u, v)
        r0.append((u, v, zb))
        r1.append((u, v, zt))
        if u <= ub:
            z2, k = zt + kz * (top[2] - zt), ku
        else:                                                   # the moc toe box's top edge in front of the ball
            q = ((u - ub) / (L - ub)) ** 2
            z2 = rig.shoe_toe_height - q * (rig.shoe_toe_height - rig.shoe_toe_tip_height)
            k = ku + q * SHOE_TOE_INSET
        r2.append((u + k * (top[0] - u), v + kv * (top[1] - v), z2))
        r3.append(tuple(top))
        r4.append((top[0], top[1], rig.shoe_opening_floor_z))
    body = mk.loft([np.array(r) for r in (r0, r1, r2, r3, r4)], "flat", "flat", groups=[1, 2, 2, 3], cap_groups=(1, 3))
    # the flat bottom is not planar (the arch): split it along the heel's front and the ball contact into three planar
    # convex polygons (the heel's top, the arch slope, the forefoot on the ground)
    m = len(pts)
    cap = [k for k, f in enumerate(body.faces) if len(f) == m and body.groups[k] == 1]
    if len(cap) != 1:
        raise mk.MeshError("shoe: bottom cap not found")
    face = body.faces[cap[0]]
    n_side = len(side_u)
    uh_k = n_side - side_u.index(rig.shoe_heel_length)           # index in pts of the +v heel-front point ...
    uc_k = n_side - side_u.index(rig.shoe_ball_contact_u * L)     # ... and of the +v ball-contact point
    mirror = {k: m - k for k in range(1, m)}                      # +v point k <-> -v point m - k (heel back: n_side+1)
    pos = {vi: i for i, vi in enumerate(face)}

    def sub(ks):
        """The cap's vertices of the pts indices ``ks`` (a closed loop) in the cap's own cyclic order."""
        idx = sorted((pos[k] for k in ks))
        return [face[i] for i in idx]

    heel = [k for k in range(uh_k + 1, m - uh_k)]                 # u < heel front on both sides (round the back)
    heel = [uh_k] + heel + [mirror[uh_k]]
    arch = [uc_k, uh_k, mirror[uh_k], mirror[uc_k]]
    fore = list(range(0, uc_k + 1)) + list(range(mirror[uc_k], m))
    new_faces = [sub(heel), sub(arch), sub(fore)]
    faces = body.faces[:cap[0]] + new_faces + body.faces[cap[0] + 1:]
    groups = body.groups[:cap[0]] + [1, 1, 1] + body.groups[cap[0] + 1:]
    return mk.Mesh(body.vertices, faces, groups)


def _heel_block(rig: Rig) -> mk.Mesh:
    """The block heel: a single-group prism under the back of the shoe, its front face leaning forward."""
    uh, sl = rig.shoe_heel_length, rig.shoe_heel_slant
    hr = 0.5 * rig.shoe_heel_width
    rings = []
    for z, uf in ((0.0, uh - sl), (rig.shoe_heel_height + SHOE_HEEL_INTO,
                                   uh + sl * (rig.shoe_heel_height + SHOE_HEEL_INTO) / rig.shoe_heel_height)):
        us = [f * hr for f in SHOE_HEEL_U]
        ring = [(uf, _shoe_half_width(rig, uh) - SHOE_HEEL_INSET)]
        ring += [(u, _shoe_half_width(rig, u) - SHOE_HEEL_INSET) for u in reversed(us)]
        ring += [(SHOE_HEEL_INSET, 0.0)]
        ring += [(u, -(_shoe_half_width(rig, u) - SHOE_HEEL_INSET)) for u in us]
        ring += [(uf, -(_shoe_half_width(rig, uh) - SHOE_HEEL_INSET))]
        rings.append(np.array([(u, v, z) for u, v in ring]))
    return mk.loft(rings, "flat", "flat", groups=1, cap_groups=(1, 1))


def _plane_section(mesh: mk.Mesh, mask, u0: float) -> np.ndarray:
    """Polyline where the plane ``x = u0`` cuts the faces ``mask`` of ``mesh`` (an open surface patch), ordered by
    increasing y (from one border of the patch to the other)."""
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
    start = min(ends, key=lambda key: (pts[key][1], key))
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


def _clip_z(P: np.ndarray, z0: float) -> np.ndarray:
    """The part of the polyline ``P`` above ``z0`` (one connected run over the top), ends interpolated on z0."""
    above = P[:, 2] >= z0
    idx = np.nonzero(above)[0]
    i0, i1 = int(idx[0]), int(idx[-1])
    out = list(P[i0:i1 + 1])
    if i0 > 0:
        a, b = P[i0 - 1], P[i0]
        out.insert(0, a + (b - a) * ((z0 - a[2]) / (b[2] - a[2])))
    if i1 < len(P) - 1:
        a, b = P[i1], P[i1 + 1]
        out.append(a + (b - a) * ((z0 - a[2]) / (b[2] - a[2])))
    return np.array(out)


def _up_normals(P: np.ndarray, across) -> np.ndarray:
    """Unit normals of a band's centre line ``P`` that lies on the upper: perpendicular to the line and to the
    across-direction ``across``, pointing up / out (away from the shoe's inside)."""
    tang = np.gradient(P, axis=0)
    out = []
    for i, t in enumerate(tang):
        nv = _unit(np.cross(t, across))
        c = P[i] - np.array([P[i, 0], 0.0, 0.0])
        if _dot(nv, c) < 0.0:
            nv = -nv
        out.append(nv)
    return np.array(out)


def _flat_band(A, B, N, height: float, bevel: float, slot=None) -> mk.Mesh:
    """Decal band between the borders ``A`` and ``B`` (``(U, 3)``) with a flat raised top ``height`` above them
    along ``N``, inset ``bevel`` (a fraction of the width) at each border; group 1, so both borders (with the bottom
    face looking away) draw as silhouettes.  4 faces per station step plus the two end faces.  ``slot = (j, length,
    width, depth)`` sinks a ``length`` x ``width`` rectangle in the middle of step ``j``'s top by ``depth`` (group 2,
    so its outline draws; four sloping strips join it to the top's border)."""
    A, B, N = (np.asarray(x, dtype=np.float64) for x in (A, B, N))
    Ai = A + bevel * (B - A) + height * N
    Bi = B + bevel * (A - B) + height * N
    U = len(A)
    V = [A, Ai, Bi, B]
    faces, groups = [], []
    for j in range(U - 1):
        k = j + 1
        top = [U + j, U + k, 2 * U + k, 2 * U + j]
        faces += [[j, k, U + k, U + j], [2 * U + j, 2 * U + k, 3 * U + k, 3 * U + j], [3 * U + j, 3 * U + k, k, j]]
        groups += [1, 1, 1]
        if slot is None or slot[0] != j:
            faces.append(top)
            groups.append(1)
            continue
        _, length, width, depth = slot
        a, b, c, d = Ai[j], Ai[k], Bi[k], Bi[j]
        s0 = 0.5 - 0.5 * length / (0.5 * (np.linalg.norm(b - a) + np.linalg.norm(c - d)))
        w0 = 0.5 - 0.5 * width / (0.5 * (np.linalg.norm(d - a) + np.linalg.norm(c - b)))
        nq = _unit(N[j] + N[k])
        R = [(1.0 - w) * ((1.0 - s) * a + s * b) + w * ((1.0 - s) * d + s * c) - depth * nq
             for s, w in ((s0, w0), (1.0 - s0, w0), (1.0 - s0, 1.0 - w0), (s0, 1.0 - w0))]
        r = 4 * U + sum(len(x) for x in V[4:])
        V.append(np.array(R))
        for q in range(4):
            faces.append([top[q], top[(q + 1) % 4], r + (q + 1) % 4, r + q])
            groups.append(1)
        faces.append([r, r + 1, r + 2, r + 3])
        groups.append(2)
    faces += [[0, U, 2 * U, 3 * U], [U - 1, 4 * U - 1, 3 * U - 1, 2 * U - 1]]
    groups += [1, 1]
    return mk._outward(mk.Mesh(np.concatenate(V), faces, groups))


def _surface_z(mesh: mk.Mesh, u: float, v: float) -> float:
    """z of the topmost surface of ``mesh`` over ``(u, v)`` (a ray from above)."""
    top = float(mesh.vertices[:, 2].max()) + PROBE
    h = mk.surface_clearance(mesh, np.array([[u, v, top]]), np.array([[0.0, 0.0, 1.0]]))[0]
    if not np.isfinite(h):
        raise mk.MeshError(f"shoe: no surface over ({u}, {v})")
    return top - float(h)


def _strap_stations(P, step: float) -> np.ndarray:
    """Stations along the strap's section polyline ``P`` (one end, over the instep, the other end): its ends, a middle
    step ``step`` long centred on the polyline's middle (the instep's top), STRAP_SIDE_STATIONS evenly between."""
    P = np.asarray(P, dtype=np.float64)
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    m0, m1 = 0.5 * (s[-1] - step), 0.5 * (s[-1] + step)
    n = STRAP_SIDE_STATIONS + 1
    t = [m0 * i / n for i in range(n + 1)] + [m1 + (s[-1] - m1) * i / n for i in range(n + 1)]
    return np.stack([np.interp(t, s, P[:, k]) for k in range(3)], axis=1)


def _strap(rig: Rig, body: mk.Mesh) -> mk.Mesh:
    """The saddle strap across the instep (between the plane sections of the upper at strap_u -+ half its width, from
    shoe_strap_end_z on one side over the top to the other) with the penny slot sunk in its top at the centre (its
    length along the strap, i.e. across the foot)."""
    L = rig.shoe_length
    us = rig.strap_u * L
    hw = 0.5 * rig.shoe_strap_width
    sl, sw = rig.penny_slot
    upper = [g == 2 for g in body.groups]
    A, B = (_strap_stations(_clip_z(_plane_section(body, upper, us + k * hw), rig.shoe_strap_end_z),
                            STRAP_SLOT_STEP * sl) for k in (-1.0, 1.0))
    N = _up_normals(0.5 * (A + B), np.array([1.0, 0.0, 0.0]))
    f = rig.shoe_decal_float
    lift = f + mk.lift_band_borders(body, A + f * N, B + f * N, N, f)
    A, B = A + lift[:, None] * N, B + lift[:, None] * N
    return _flat_band(A, B, N, rig.shoe_strap_relief, STRAP_BEVEL,
                      slot=(STRAP_SIDE_STATIONS + 1, sl, sw, rig.penny_slot_depth))


def _apron(rig: Rig, body: mk.Mesh) -> mk.Mesh:
    """The moc-toe apron seam: a raised piping (a ridge band) along the U round the toe box, laid on the upper as it
    is drawn (its valley fan diagonals, :func:`_mirror_fan`), its twisted quads split (APRON_SPLIT_DEG)."""
    body = mk.inscribed_fan(body)
    half = np.array(rig.apron_path)
    full = np.concatenate([half, half[-2::-1] * np.array([1.0, -1.0])])
    P2 = mk.resample_polyline(full, APRON_STATIONS)
    P = np.array([(u, v, _surface_z(body, u, v)) for u, v in P2])
    tang = np.gradient(P, axis=0)
    N = []
    for i in range(len(P)):
        # the surface normal from the neighbouring heights (finite differences across and along)
        e = 0.002
        u, v = P2[i]
        zx = (_surface_z(body, u + e, v) - _surface_z(body, u - e, v)) / (2 * e)
        zy = (_surface_z(body, u, v + e) - _surface_z(body, u, v - e)) / (2 * e)
        N.append(_unit([-zx, -zy, 1.0]))
    N = np.array(N)
    side = np.array([_unit(np.cross(N[i], tang[i])) for i in range(len(P))])
    hw = 0.5 * rig.apron_width
    f = rig.shoe_decal_float
    A, B = P + hw * side + f * N, P - hw * side + f * N
    lift = mk.lift_band_borders(body, A, B, N, f)
    A, B = A + lift[:, None] * N, B + lift[:, None] * N
    band = mk.fan_fold(mk.ridge_band(A, B, N, APRON_HEIGHT * rig.apron_relief, periodic=False),
                       [True] * (3 * (len(P) - 1) + 2))
    return mk.split_twisted(band, APRON_SPLIT_DEG)


def _shoe_parts(rig: Rig):
    body = _shoe_body(rig)
    heel = _heel_block(rig)
    strap = _strap(rig, body)
    apron = _apron(rig, body)
    f = rig.foot_dir(1)
    perp = np.array([-f[1], f[0], 0.0])
    if np.linalg.det(np.stack([f, perp, [0.0, 0.0, 1.0]], axis=1)) < 0:
        perp = -perp
    M = np.stack([f, perp, np.array([0.0, 0.0, 1.0])], axis=1)
    origin = rig.heel_point(1)
    meshes = {"shoe": body, "heel": heel, "strap": strap, "apron": apron}
    placed = {k: m.transform(M, origin) for k, m in meshes.items()}
    parts = []
    for side in SIDES:
        for key in ("shoe", "heel", "strap", "apron"):
            # the strap and the apron keep their fan_fold diagonals (inscribed_fan would undo the ridge top)
            mesh = _mirror_fan(placed[key], side) if key in ("shoe", "heel") else _mirror(placed[key], side)
            parts.append(Part(f"limbs.{key}_{_s(side)}", "shoes", mesh, "shoes", obj=f"shoe_{_s(side)}"))
    return parts


# ---------------------------------------------------------------------------------------------------------------

def build(rig: Rig):
    """The parts of :data:`REGIONS` (hands into ``arm_l`` / ``arm_r``, legs, socks, shoes)."""
    return _hand_parts(rig) + _leg_parts(rig) + _shoe_parts(rig)
