"""Placeholder (mannequin) parts for every region of the model.

Each region builder takes a :class:`~miki_model.rig.Rig` and returns a list of
:class:`~miki_model.meshkit.Part`; :func:`build` returns the parts of the requested regions.  The shapes
are deliberately simple (ellipsoids, tubes, slabs) but sit at the rig's landmarks, so a detailed module
(``head.py``, ``hair.py``, ``body.py``, ``limbs.py``) can be previewed in context while the others are
still placeholders.  The figure stands on ``z = 0`` facing ``-Y``.

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

__all__ = ["REGIONS", "BUILDERS", "build"]

SIDES = (1, -1)                    # her left (+X), her right (-X)


def _side_name(side: int) -> str:
    return "l" if side > 0 else "r"


def _local(mesh: mk.Mesh, origin, z_axis, x_hint=(1.0, 0.0, 0.0)) -> mk.Mesh:
    """Place a mesh built around the origin (local Z = ``z_axis``) at ``origin``."""
    x, y, z = mk.frame_from_z(z_axis, x_hint)
    return mesh.transform(np.stack([x, y, z], axis=1), origin)


def _ellipsoid_surface(c, radii, d):
    """Point where the ray from ``c`` along unit ``d`` meets the ellipsoid ``radii`` about ``c``."""
    d = np.asarray(d, dtype=np.float64)
    t = 1.0 / math.sqrt(float(np.sum((d / radii) ** 2)))
    return c + d * t


def _head_normal(rig: Rig, p):
    c, r = rig.head_center, rig.head_radii
    n = (p - c) / r ** 2
    return n / np.linalg.norm(n)


# ---------------------------------------------------------------------------
# head.py regions
# ---------------------------------------------------------------------------

def head(rig: Rig):
    parts = [Part("mannequin.head", "skin", mk.ellipsoid(rig.head_center, rig.head_radii, 24, 14), "head")]
    c = rig.head_center
    for side in SIDES:
        ear = mk.ellipsoid((0.0, 0.0, 0.0), (0.007, 0.014, 0.5 * rig.ear_size), 10, 6)
        pos = (side * (0.5 * rig.head_width - 0.004), c[1] + 0.006, rig.chin_z + rig.ear_height_ratio * rig.head_height)
        parts.append(Part(f"mannequin.ear_{_side_name(side)}", "skin", ear.translate(pos), "head"))
    return parts


def _face_disc(rig: Rig, x, z, half_w, half_h, relief, lift, n=16):
    p = rig.head_surface_point(x, z)
    nrm = _head_normal(rig, p)
    disc = mk.superellipsoid((0.0, 0.0, 0.0), (half_w, half_h, relief), n, 4, 2.0, 2.0)
    return _local(disc, p + nrm * lift, nrm, x_hint=(1.0, 0.0, 0.0))


def eyes(rig: Rig):
    parts = []
    for side in SIDES:
        x = side * 0.5 * rig.eye_spacing
        white = _face_disc(rig, x, rig.eye_z, 0.5 * rig.eye_width, 0.5 * rig.eye_height, rig.eye_relief, 0.0)
        iris = _face_disc(rig, x, rig.eye_z - 0.002, 0.30 * rig.eye_width, 0.38 * rig.eye_height,
                          rig.eye_relief, 0.6 * rig.eye_relief, 12)
        parts.append(Part(f"mannequin.eye_{_side_name(side)}", "eyes", white, "eyes"))
        parts.append(Part(f"mannequin.iris_{_side_name(side)}", "eyes", iris, "eyes"))
    return parts


def face_marks(rig: Rig):
    parts = []
    z = rig.eye_z + 0.5 * rig.eye_height + rig.brow_gap
    for side in SIDES:
        xs = side * (0.5 * rig.eye_spacing + np.linspace(-0.6, 0.6, 5) * rig.eye_width)
        pts = np.array([rig.head_surface_point(x, z + 0.004 * (1 - (k - 2) ** 2 / 4.0)) for k, x in enumerate(xs)])
        nrm = np.array([_head_normal(rig, p) for p in pts])
        brow = mk.sweep(pts + nrm * 0.0008, width=0.0045, thickness=0.0024, profile=mk.profile_lens(6),
                        normals=nrm, start="pointed", end="pointed")
        parts.append(Part(f"mannequin.brow_{_side_name(side)}", "face_marks", brow, "face_marks"))
    mouth = _face_disc(rig, 0.0, rig.mouth_z, 0.5 * rig.mouth_width, 0.0025, 0.0015, 0.0003, 10)
    parts.append(Part("mannequin.mouth", "face_marks", mouth, "face_marks"))
    return parts


# ---------------------------------------------------------------------------
# hair.py regions
# ---------------------------------------------------------------------------

def hair(rig: Rig):
    c, r = rig.head_center, rig.head_radii
    v = rig.hair_volume
    cap = mk.ellipsoid(c + np.array([0.0, 0.016, 0.010]), r + np.array([v, v * 0.6, v * 0.2]), 24, 12)
    parts = [Part("mannequin.hair_cap", "hair", cap, "hair")]
    # bangs: slab over the forehead, from inside the cap down to the cut line
    rb = r + np.array([0.006, 0.006, 0.006])
    az = np.radians(np.linspace(-52.0, 52.0, 9))
    zs = np.linspace(c[2] + 0.62 * r[2], rig.bangs_cut_z, 5)
    grid = np.zeros((len(az), len(zs), 3))
    for i, a in enumerate(az):
        for j, z in enumerate(zs):
            el = math.asin(max(-1.0, min(1.0, (z - c[2]) / rb[2])))
            d = np.array([math.sin(a) * math.cos(el), -math.cos(a) * math.cos(el), math.sin(el)])
            grid[i, j] = c + d * rb
    bangs = mk.thicken(grid, rig.bangs_thickness, offset="outward", away_from=c,
                       groups={"front": 1, "back": 1, "rim": {"v0": 1, "v1": 2, "u0": 1, "u1": 1}})   # cut edge drawn
    parts.append(Part("mannequin.bangs", "hair", bangs, "hair"))
    # back hair: slab hanging behind the back, wrapping slightly around
    us = np.linspace(-1.0, 1.0, 9)
    zs = np.linspace(c[2] + 0.2 * r[2], rig.hair_back_end_z, 10)
    grid = np.zeros((len(us), len(zs), 3))
    for j, z in enumerate(zs):
        t = (c[2] - z) / (c[2] - rig.hair_back_end_z)             # 0 at the head, 1 at the ends
        half = (0.75 * r[0] + v) * (1 - t) + rig.hair_back_half_width * t
        yb = c[1] + (r[1] + v + 0.004) * (1 - t) ** 0.5 * (1 - t) + (rig.chest_half_depth + 0.050) * min(1.0, 2.5 * t)
        yb = max(yb, c[1] + 0.03) if t < 0.2 else yb
        for i, u in enumerate(us):
            grid[i, j] = (u * half, yb - 0.05 * u * u * (0.6 + 0.4 * t), z)
    back = mk.thicken(grid, lambda a, b: rig.hair_back_thickness * (1.0 - 0.6 * b) * (1.0 - 0.5 * (2 * a - 1) ** 2),
                      away_from=(0.0, -1.0, c[2]), groups="single")
    parts.append(Part("mannequin.back_hair", "hair", back, "hair"))
    # sidelocks
    for side in SIDES:
        pts = np.array([[side * (r[0] - 0.006), c[1] - 0.020, c[2] + 0.020],
                        [side * (r[0] + 0.004), c[1] - 0.040, rig.eye_z - 0.010],
                        [side * (r[0] - 0.004), c[1] - 0.045, rig.chin_z + 0.010],
                        [side * (r[0] - 0.010), c[1] - 0.040, rig.sidelock_end_z]])
        path = mk.resample_polyline(pts, 10)
        nrm = np.tile([side * 1.0, 0.0, 0.0], (len(path), 1))
        lock = mk.sweep(path, width=rig.sidelock_width, thickness=rig.sidelock_thickness,
                        profile=mk.profile_lens(8), normals=nrm, start="round", end="flat")
        parts.append(Part(f"mannequin.sidelock_{_side_name(side)}", "hair", lock, "hair"))
    # the single stray strand beside her right temple
    pts = np.array([[-0.040, c[1] - r[1] + 0.012, c[2] + 0.55 * r[2]],
                    [-0.058, c[1] - r[1] + 0.000, c[2] + 0.20 * r[2]],
                    [-0.062, c[1] - r[1] + 0.010, rig.eye_z - 0.020]])
    path = mk.resample_polyline(pts, 8)
    strand = mk.sweep(path, width=lambda s: rig.strand_width * (1.0 - 0.8 * s), thickness=0.0025,
                      profile=mk.profile_lens(6), start="round", end="pointed")
    parts.append(Part("mannequin.strand", "hair", strand, "hair"))
    return parts


def headband(rig: Rig):
    c = rig.head_center
    r = rig.head_radii + np.array([rig.hair_volume, rig.hair_volume * 0.6, rig.hair_volume * 0.2]) \
        + rig.headband_lift
    c_cap = c + np.array([0.0, 0.016, 0.010])
    b = math.radians(rig.headband_angle_deg)
    e = np.array([0.0, math.cos(b), math.sin(b)])         # band plane normal
    alphas = np.radians(np.linspace(-84.0, 84.0, 25))
    grid = np.zeros((len(alphas), 2, 3))
    for i, a in enumerate(alphas):
        d = np.array([math.sin(a), -math.cos(a) * math.sin(b), math.cos(a) * math.cos(b)])
        p = _ellipsoid_surface(c_cap, r, d)
        grid[i, 0] = p - e * 0.5 * rig.headband_width
        grid[i, 1] = p + e * 0.5 * rig.headband_width
    band = mk.thicken(grid, rig.headband_thickness, offset="outward", away_from=c, groups="single")
    return [Part("mannequin.headband", "headband", band, "headband")]


# ---------------------------------------------------------------------------
# body.py regions
# ---------------------------------------------------------------------------

def neck(rig: Rig):
    rings = [mk.ellipse_ring(rig.neck_radius, rig.neck_radius * 0.95, 12, (0.0, rig.neck_y, z))
             for z in (rig.shoulder_z - 0.050, rig.chin_z + 0.045)]
    return [Part("mannequin.neck", "skin", mk.loft(rings, "flat", "flat"), "neck")]


def _torso_sections(rig: Rig, ease: float):
    """``(z, half width, half depth)`` from the hem to the neckline."""
    e = ease
    return [(rig.top_hem_z, rig.waist_half_width + 0.015 + e, rig.waist_half_depth + 0.008 + e),
            (rig.waist_z, rig.waist_half_width + e, rig.waist_half_depth + e),
            (rig.chest_z, rig.chest_half_width + e, rig.chest_half_depth + e),
            (rig.shoulder_z - 0.035, rig.shoulder_half_width - 0.010 + e, rig.chest_half_depth - 0.012 + e),
            (rig.shoulder_z, rig.shoulder_half_width - 0.040, rig.chest_half_depth - 0.030),
            (rig.shoulder_z + 0.012, rig.neck_radius + 0.022, rig.neck_radius + 0.018)]


def torso(rig: Rig):
    rings = [mk.superellipse_ring(w, d, 20, rig.torso_exponent, (0.0, 0.0, z)) for z, w, d in
             _torso_sections(rig, rig.top_ease)]
    return [Part("mannequin.top", "uniform", mk.loft(rings, "pole", "pole"), "torso")]


def collar(rig: Rig):
    # band around the neckline sitting on the shoulders
    n = 24
    t = 2.0 * np.pi * np.arange(n) / n
    inner, outer = rig.neck_radius + 0.020, rig.shoulder_half_width - 0.030
    grid = np.zeros((n, 2, 3))
    for i, a in enumerate(t):
        grid[i, 0] = (inner * 1.05 * math.cos(a), inner * math.sin(a), rig.shoulder_z + 0.016)
        grid[i, 1] = (outer * math.cos(a), (rig.chest_half_depth - 0.010) * math.sin(a), rig.shoulder_z - 0.022)
    band = mk.thicken(grid, rig.collar_thickness, periodic_u=True, offset="outward", away_from=(0.0, 0.0, 0.9),
                      groups="single")
    # square flap on the back
    xs = np.linspace(-rig.collar_flap_half_width, rig.collar_flap_half_width, 5)
    zs = np.linspace(rig.shoulder_z - 0.010, rig.collar_back_flap_z, 5)
    grid = np.zeros((len(xs), len(zs), 3))
    for i, x in enumerate(xs):
        for j, z in enumerate(zs):
            k = (rig.shoulder_z - z) / (rig.shoulder_z - rig.collar_back_flap_z)
            y = rig.chest_half_depth + rig.top_ease + 0.004 - 0.020 * (1 - k) ** 2 - 0.25 * (x / 0.3) ** 2
            grid[i, j] = (x, y, z)
    flap = mk.thicken(grid, rig.collar_thickness, offset="outward", away_from=(0.0, 0.0, rig.chest_z),
                      groups="single")
    return [Part("mannequin.collar", "collar", band, "collar"), Part("mannequin.collar_flap", "collar", flap, "collar")]


def scarf(rig: Rig):
    y0 = -(rig.chest_half_depth + rig.top_ease) - 0.010
    parts = []
    for side in SIDES:
        pts = np.array([[side * 0.004, y0 + 0.004, rig.collar_v_z + 0.010],
                        [side * 0.012, y0 - 0.004, rig.collar_v_z - 0.030],
                        [side * 0.030, y0 - 0.004, rig.scarf_tip_z + 0.020],
                        [side * 0.036, y0 - 0.002, rig.scarf_tip_z]])
        path = mk.resample_polyline(pts, 8)
        nrm = np.tile([0.0, -1.0, 0.0], (len(path), 1))
        tip = mk.sweep(path, width=lambda s: rig.scarf_width * (1.0 - 0.6 * s), thickness=0.005,
                       profile=mk.profile_lens(8, 0.4), normals=nrm, start="flat", end="pointed")
        parts.append(Part(f"mannequin.scarf_tip_{_side_name(side)}", "scarf", tip, "scarf"))
    ring = mk.torus((0.0, y0, rig.collar_v_z - 0.010), rig.scarf_ring_radius + 0.012, 0.003, 16, 6,
                    normal=(0.0, 0.0, 1.0), minor_z=0.006)
    parts.append(Part("mannequin.scarf_ring", "collar", ring, "scarf"))
    return parts


def skirt(rig: Rig):
    p = rig.skirt_pleats
    m = 2 * p
    rings = []
    zs = np.linspace(rig.skirt_top_z, rig.skirt_hem_z, 5)
    for j, z in enumerate(zs):
        t = j / (len(zs) - 1)
        hw = (rig.waist_half_width + 0.010) * (1 - t) + rig.skirt_hem_half_width * t
        hd = (rig.waist_half_depth + 0.010) * (1 - t) + rig.skirt_hem_half_depth * t
        depth = 0.01 + 0.05 * t
        a = 2.0 * np.pi * np.arange(m) / m
        k = 1.0 - depth * (np.arange(m) % 2)
        rings.append(np.stack([hw * k * np.cos(a), hd * k * np.sin(a), np.full(m, z)], axis=1))
    rings = rings[::-1]                                   # hem first
    # one group: the pleats and the hem draw as silhouettes (pleat creases as feature lines would cross the
    # light terminator many times and exceed castplane's 64 ray vertices of the uniform object)
    mesh = mk.loft(rings, "pole", "pole", groups=1)        # star-shaped rings: fan caps
    return [Part("mannequin.skirt", "uniform", mesh, "skirt")]


# ---------------------------------------------------------------------------
# limbs.py regions
# ---------------------------------------------------------------------------

def _arm_path(rig: Rig, side: int, n: int = 10):
    s, e, w = rig.shoulder_joint(side), rig.elbow(side), rig.wrist(side)
    a = mk.resample_polyline(np.array([s + np.array([-side * 0.03, 0.0, 0.01]), s, e]), n // 2 + 1)
    b = mk.resample_polyline(np.array([e, w + rig.sleeve_end_past_wrist * rig.forearm_dir(side)]), n // 2 + 1)
    return np.concatenate([a, b[1:]])


def arms(rig: Rig):
    parts = []
    for side in SIDES:
        path = _arm_path(rig, side)
        seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
        s = np.concatenate([[0.0], np.cumsum(seg)]) / seg.sum()
        rad = np.interp(s, [0.0, 0.5, 1.0], [rig.upper_arm_radius, rig.elbow_radius, rig.wrist_radius]) \
            + rig.sleeve_ease
        sleeve = mk.sweep(path, width=2 * rad, n_profile=12, start="round", end="flat")
        parts.append(Part(f"mannequin.sleeve_{_side_name(side)}", "uniform", sleeve, "arms"))
        d = rig.forearm_dir(side)
        w = rig.wrist(side)
        for k, back in enumerate((0.022, 0.040)):
            ctr = w - d * back
            band = mk.torus(ctr, rig.wrist_radius + rig.sleeve_ease + 0.002, 0.0028, 14, 6, normal=d, minor_z=0.004)
            parts.append(Part(f"mannequin.cuff_{_side_name(side)}{k}", "collar", band, "arms"))
    return parts


def hands(rig: Rig):
    parts = []
    for side in SIDES:
        d = rig.forearm_dir(side)
        ctr = rig.wrist(side) + d * (0.45 * rig.hand_length)
        hand = mk.superellipsoid((0.0, 0.0, 0.0), (0.5 * rig.hand_thickness, 0.5 * rig.hand_width,
                                                   0.5 * rig.hand_length), 12, 8, 2.4, 2.2)
        parts.append(Part(f"mannequin.hand_{_side_name(side)}", "skin",
                          _local(hand, ctr, d, x_hint=(side * 1.0, 0.0, 0.0)), "hands"))
    return parts


def _leg_path(rig: Rig, side: int, n: int = 12):
    h, k, a = rig.hip_joint(side), rig.knee(side), rig.ankle(side)
    top = h + np.array([0.0, 0.0, 0.035])
    return mk.resample_polyline(np.array([top, k, a]), n)


def _leg_radius(rig: Rig, s):
    return np.interp(s, [0.0, 0.48, 0.52, 0.7, 1.0],
                     [rig.thigh_radius, rig.knee_radius, rig.knee_radius, rig.calf_radius, rig.ankle_radius])


def legs(rig: Rig):
    parts = []
    for side in SIDES:
        path = _leg_path(rig, side)
        s = np.linspace(0.0, 1.0, len(path))
        leg = mk.sweep(path, width=2 * _leg_radius(rig, s), n_profile=12, start="round", end="round",
                       up=(0.0, -1.0, 0.0))
        parts.append(Part(f"mannequin.leg_{_side_name(side)}", "skin", leg, "legs"))
    return parts


def socks(rig: Rig):
    parts = []
    for side in SIDES:
        path = _leg_path(rig, side, 60)
        seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
        s_all = np.concatenate([[0.0], np.cumsum(seg)]) / seg.sum()
        z = np.linspace(rig.sock_top_z, rig.ankle_z - 0.005, 6)
        rev = path[::-1]                                   # z increasing
        pts = np.stack([np.interp(z, rev[:, 2], rev[:, k]) for k in range(3)], axis=1)
        s = np.interp(z, rev[:, 2], s_all[::-1])
        sock = mk.sweep(pts, width=2 * (_leg_radius(rig, s) + rig.sock_ease), n_profile=12, start="flat",
                        end="flat", up=(0.0, -1.0, 0.0))
        parts.append(Part(f"mannequin.sock_{_side_name(side)}", "socks", sock, "socks"))
    return parts


def shoes(rig: Rig):
    parts = []
    for side in SIDES:
        d = rig.foot_dir(side)
        a = rig.ankle(side)
        ctr = np.array([a[0], a[1], 0.0]) + d * (0.5 * rig.foot_length - rig.heel_back)
        L, W = rig.foot_length, rig.foot_width
        rings = []
        for z, k in ((0.0, 1.0), (rig.shoe_sole, 1.02), (0.6 * rig.shoe_height, 0.95), (rig.shoe_height, 0.55)):
            ring = mk.rounded_rect_ring(W * k, L * k, 0.45 * W * k, 20)
            if z == rig.shoe_height:
                ring[:, 1] += 0.5 * L - rig.heel_back - 0.30 * L * 0.5     # opening over the ankle
            ring[:, 2] = z
            rings.append(ring)
        shoe = mk.loft(rings, "flat", "flat", groups=[1, 2, 2])
        # local frame: +Y of the ring = towards the heel; rotate so -Y points along the foot direction
        ang = math.degrees(math.atan2(d[0], -d[1]))
        shoe = shoe.rotate("z", ang).translate(ctr)
        parts.append(Part(f"mannequin.shoe_{_side_name(side)}", "shoes", shoe, "shoes"))
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
