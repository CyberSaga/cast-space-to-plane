"""Proportions, landmarks and pose of the Reiya model: the single source of every number.

The values are the numeric character spec (``SPEC.md`` in this directory, sections A-E; the section of each field is
in its comment).  They were measured on the creator's design sheet (三面図, see SPEC.md "Appendix: measurements") at
one scale of 0.615 mm per pixel.  "Spec" in a comment means SPEC.md, and where a value differs from it the code wins.
Builders read every dimension from a :class:`Rig` and add a new named field (with a comment and the spec section)
instead of a literal.  Units are metres and degrees.  The frame is castplane's world: Z up, soles on ``z = 0``, the
figure stands at the origin facing ``-Y`` and her left is ``+X``.  A ``side`` argument is ``+1`` for her left
(``+X``) and ``-1`` for her right.

Conventions of the fields:

* a point is ``(x, y, z)`` for her **left** side (``x >= 0``); :meth:`Rig.at` mirrors it for a side.  The few
  asymmetric parts (the bangs, the hairline on her right, the cardigan crossover and its button, the irises) say
  so in their comment and are given in true coordinates;
* a 2D face point is ``(x, z)`` on the face, its ``y`` comes from :meth:`Rig.head_surface_y`;
* the spec's tables are tuples of rows (each documented next to the field); rows run top to bottom;
* ``hw`` is a half-width in x, ``yf`` / ``yb`` are the front (most negative y) / back extents at the midline;
* a horizontal **section** ``(hw, yf, yb)`` is the closed curve whose front half is the superellipse with semi-axes
  ``(hw, c - yf)`` and whose back half is the one with ``(hw, yb - c)``, ``c = (yf + yb) / 2`` unless a field gives
  ``c`` (the head); :meth:`Rig.section_point` / :meth:`Rig.section_ring` evaluate it;
* an **azimuth** ``phi`` (degrees) runs round the vertical axis from the front (``-Y``, 0) through her left (``+X``,
  90) to the back (``+Y``, 180): ``x = r sin(phi)``, ``y = c - r cos(phi)``.

**Scale.**  Every length in this rig, in SPEC.md §A-§E and in the builders is at the design sheet's scale (0.615 mm per
pixel; skin height 1.555 m).  Her real height came later, from the user: :attr:`Rig.stated_height` (1.52 m barefoot,
sole of the foot to the skull top).  The assembled model is scaled uniformly about the origin by
:attr:`Rig.figure_scale` ``= stated_height / skin_height`` (``1.52 / 1.555 = 0.97749``; ``assemble.CHARACTER.scale``,
:func:`charmodel.assembly.build_parts`), so the soles stay on ``z = 0`` and every final length is the sheet length times
``figure_scale``; the ``final_*`` properties give the final key heights.  The writers and the previews scale the
scene camera and the preview framing by the same factor.

:meth:`Rig.replace` / :meth:`Rig.from_dict` change fields (unknown keys raise; JSON lists become tuples).
The derived landmarks (``height``, ``chin_z``, ``eye_z`` ...) are properties of the tables, so a table
override moves them too.  Every method is deterministic (scalar arithmetic and explicit 3-term sums, no BLAS reductions,
no branch decided by the last bit of a float).
"""

from __future__ import annotations

import dataclasses
import math
import warnings
from dataclasses import dataclass

import numpy as np

__all__ = ["Rig", "DEFAULT_RIG", "SUN_TOWARDS", "SPEC_ONLY_FIELDS", "MANNEQUIN_ONLY_FIELDS"]

#: Direction towards the scene's sun (normalised by the scene writer).  The single source for the scene light
#: (``export``), the shaded previews and the lit / unlit classification of slab rims and decal walls, which keeps the
#: construction rays per object under castplane's cap of 64.  The viewer's upper left of the 3/4 front-left scene
#: camera (on her left front), elevation 58 deg: the ground shadow (about 1.0 m for her 1.58 m to the tuft tips)
#: recedes to her left-back and stays inside the portrait frame (SPEC.md §E; the Miki value, which met the same frame).
SUN_TOWARDS = (-0.45, -0.55, 1.14)


def _tuplify(value):
    if isinstance(value, (list, tuple)):
        return tuple(_tuplify(v) for v in value)
    return value


def _interp_rows(rows, z, col):
    """Linear interpolation in z of column ``col`` of a top-to-bottom table (clamped at the ends)."""
    zs = [r[0] for r in rows]
    if z >= zs[0]:
        return rows[0][col]
    if z <= zs[-1]:
        return rows[-1][col]
    for a, b in zip(rows, rows[1:]):
        if b[0] <= z <= a[0]:
            t = (a[0] - z) / (a[0] - b[0])
            return a[col] + t * (b[col] - a[col])
    raise ValueError(f"z {z} outside the table")


def _interp_pairs(pairs, u):
    """Linear interpolation in the first column of a table of ``(u, value)`` rows sorted by ``u`` (clamped)."""
    if u <= pairs[0][0]:
        return pairs[0][1]
    if u >= pairs[-1][0]:
        return pairs[-1][1]
    for a, b in zip(pairs, pairs[1:]):
        if a[0] <= u <= b[0]:
            t = (u - a[0]) / (b[0] - a[0])
            return a[1] + t * (b[1] - a[1])
    raise ValueError(f"{u} outside the table")


def _norm(v) -> float:
    """Length of a 3-vector by an explicit sum (no BLAS kernel, so the last bit is the same on every CPU)."""
    v = np.asarray(v, dtype=np.float64)
    return math.sqrt(float(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    return v / _norm(v)


def _rotate(v, axis, deg: float) -> np.ndarray:
    """Rodrigues rotation of the 3-vector ``v`` about the unit ``axis`` by ``deg`` degrees."""
    v = np.asarray(v, dtype=np.float64)
    k = _unit(axis)
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    kv = float(k[0] * v[0] + k[1] * v[1] + k[2] * v[2])
    return v * ca + np.cross(k, v) * sa + k * kv * (1.0 - ca)


@dataclass(frozen=True)
class Rig:
    """Named dimensions (metres, degrees) and derived landmarks of the figure (``SPEC.md``)."""

    # =====================================================================================================
    # A. Overall proportions and landmarks
    # =====================================================================================================
    #: Landmark table (SPEC.md §A): ``(name, z, hw, yf, yb)``; the body column is the outermost surface at that
    #: level (hair, skin or clothing, see SPEC.md §A for each row).  ``height``, ``chin_z``, ``eye_z``,
    #: ``seam_z`` ... are read from here.  Decision 1: skull top 1.590 in her shoes (skin height 1.555 + a
    #: 0.035 block heel), the hair crown 1.606 sets the sheet scale (0.615 mm / px).
    landmarks: tuple = (
        ("ear-tuft tip", 1.614, 0.064, -0.001, 0.028),      # tip x +-0.064, 8 mm over the crown; yf / yb = the
        #                                                     lobe's front / back edge (side view, 3 cm deep)
        ("hair crown", 1.606, 0.0, -0.015, -0.015),         # top of the dome (sheet rows 131-136)
        ("skull top", 1.590, 0.0, -0.012, -0.012),          # skin under 16 mm of hair (Decision 1)
        ("brow", 1.499, 0.074, -0.114, 0.078),              # skin; her right brow 1.496 (inner) .. 1.502 (outer)
        ("bang line", 1.475, 0.115, -0.131, 0.1046),        # fringe tips 1.473-1.479; hw / yb of the hair mass
        ("eye centre", 1.459, 0.068, -0.102, 0.077),        # skin; eye centres x +-0.0395 (sheet +-0.041)
        ("nose tip", 1.4355, 0.058, -0.1125, 0.071),        # yf = the nose bump tip (face plane -0.105)
        ("mouth", 1.416, 0.0495, -0.1025, 0.061),           # closed smile, corners 1.4176, middle 1.4127
        ("chin", 1.388, 0.0, -0.077, -0.040),               # chin bottom; yb = neck front (jaw underside)
        ("neck", 1.375, 0.022, -0.038, 0.018),              # visible 1.366 .. 1.387 between chin and rim
        ("mock-neck rim", 1.364, 0.029, -0.0475, 0.0285),   # lettuce edge (top, waves +-1.5 mm), white top
        ("neck base", 1.338, 0.050, -0.051, 0.032),         # the mock neck flares into the shoulders
        ("shoulder", 1.300, 0.113, -0.083, 0.050),          # shoulder point (white sleeve outer x 0.111-0.113)
        ("neckline", 1.2765, 0.0935, -0.110, 0.053),        # square neckline of the bodice; straps x 0.0555-0.0885
        ("bust", 1.225, 0.0925, -0.1245, 0.050),            # bodice; apex x +-0.045
        ("high-waist seam", 1.108, 0.0724, -0.1103, 0.0376), # bodice's lower edge (narrowest 0.0705 at 1.116)
        ("natural waist", 1.000, 0.0955, -0.1245, 0.048),   # skirt (body under it: body_rows)
        ("hip", 0.860, 0.1257, -0.1490, 0.0760),            # skirt (body hip: body_rows)
        ("crotch", 0.775, 0.1414, -0.1620, 0.0970),         # skirt; Decision 13 (the legs start at leg_top_z)
        ("skirt hem", 0.390, 0.2125, -0.2215, 0.1790),      # flute crests (Decision 9: level; hem_wave at valleys)
        ("calf", 0.340, 0.0985, -0.0388, 0.0412),           # legs: centre x 0.0595, r 0.039
        ("sock-cuff top", 0.255, 0.0967, -0.0360, 0.0420),  # turned-down cuff (leg + cuff_ease); = sock_cuff_z
        ("sock-cuff bottom", 0.202, 0.0880, -0.0310, 0.0370),
        ("ankle", 0.085, 0.0825, -0.0260, 0.0280),          # ankle centre (0.056, 0.000), sock r 0.0265
        ("heel top", 0.034, 0.0830, -0.0120, 0.0350),       # block heel top; hw = heel outer x, y = block range
        ("sole", 0.0, 0.0915, -0.1525, 0.0350),             # shoe outer x / toe / heel back (feet parallel)
    )
    head_depth_y: tuple = (-0.114, 0.078)    # §A head depth (skin) at the brow line: forehead y, back of skull y
    heel_lift: float = 0.035                 # §A / Decision 1: her heel stands this high in the loafers
    #: §A / Decision 1: her height, from the user (2026-10-21, "Her height is 152cm"): barefoot, sole of the foot to the
    #: skull top.  The rig is at the sheet scale (skin height 1.555); the assembled model is scaled by
    #: ``figure_scale = stated_height / skin_height`` about the origin (the soles stay on z = 0).
    stated_height: float = 1.52

    # -- A.1 body (skin) under the clothes: the legs' top, the hips the skirt hangs over, the arms' armpits ------
    #: ``(z, hw, yf, yb)`` of the body surface below the bodice (hidden; Decision 13).  Sections: c = mid.
    body_rows: tuple = (
        (1.108, 0.0660, -0.1030, 0.0310),  # under the seam
        (1.000, 0.0740, -0.0900, 0.0350),  # natural waist (Decision 13)
        (0.900, 0.0950, -0.0820, 0.0560),
        (0.860, 0.1000, -0.0800, 0.0600),  # hip widest (buttocks)
        (0.775, 0.0960, -0.0700, 0.0520),  # crotch level (the two thighs)
    )
    body_exponent: float = 2.4               # §A body / top / bodice sections: superellipse exponent (both halves)

    # -- A.2 the white top's torso (mock-neck top), outer surface ------------------------------------------------
    #: ``(z, hw, yf, yb)`` from the mock neck's flare to inside the bodice (§D.2); the shoulders are the
    #: sheet's slope (cardigan-off view), the white sleeve tube adds the upper arm outside.
    top_rows: tuple = (
        (1.349, 0.0318, -0.0488, 0.0298),  # the mock neck flares into the shoulders, a smooth concave flare (review
        (1.346, 0.0360, -0.0495, 0.0305),  # r2-L11; the sheet's OFF outline: hw 0.031 / 0.0357 / 0.041 at z 1.350 /
        (1.342, 0.0420, -0.0500, 0.0310),  # 1.346 / 1.342) down to the fold where it meets the shoulders (top_fold_z)
        (1.336, 0.0600, -0.0540, 0.0340),
        (1.330, 0.0720, -0.0580, 0.0380),
        (1.322, 0.0870, -0.0640, 0.0430),
        (1.312, 0.0990, -0.0720, 0.0470),
        (1.300, 0.1040, -0.0830, 0.0500),  # shoulder point level (the sleeve tube reaches x 0.113)
        (1.276, 0.0910, -0.1060, 0.0505),  # neckline level: the bodice's top edge lies on this + lift
        (1.258, 0.0900, -0.1140, 0.0490),  # armpit (the arm's sleeve tube passes outside / behind)
        (1.225, 0.0885, -0.1185, 0.0465),  # bust (inside the bodice from 1.270 down)
        (1.190, 0.0815, -0.1155, 0.0425),  # the top's torso ends here, buried in the bodice
    )
    #: Mock neck tube ``(z, hw, yf, yb)`` (§D.2): from the lettuce rim down into the shoulder flare.
    mock_neck_rows: tuple = (
        (1.364, 0.0290, -0.0475, 0.0285),  # rim (the waves ride on this)
        (1.352, 0.0293, -0.0480, 0.0290),
        (1.342, 0.0330, -0.0490, 0.0300),  # guide only, not sampled: below 1.352 the flare is top_rows' (1.349 /
        #                                    1.346 down to the fold at top_fold_z)
    )
    mock_neck_exponent: float = 2.0
    lettuce_waves: int = 20                  # §D.2 wavy (lettuce) rim: waves round the rim (5-6 humps across the
    #                                          front, each 9-10 mm wide, as drawn)
    lettuce_amplitude: float = 0.0015        # z amplitude of the rim waves (+-)
    lettuce_flare: float = 0.0020            # the rim turns out this much
    mock_neck_thickness: float = 0.0025      # wall thickness at the dent's floor (the tube is a closed solid; its
    #                                          inner wall flares up to the rim's top face, lettuce_rim_width wide)
    #: White sleeve tubes of the top (§D.2): radius along the arm, ``(position, radius)``, position 0 = shoulder
    #: joint, 1 = elbow; they end inside the cardigan sleeve at top_sleeve_end.
    top_sleeve_radii: tuple = ((0.0, 0.0235), (0.5, 0.0225), (1.0, 0.0215))
    top_sleeve_end: float = 0.40             # arm position where the white sleeve ends (hidden in the cardigan sleeve)

    # -- A.3 the dress bodice and skirt (jumper, material dress) -------------------------------------------------
    #: Bodice outer surface ``(z, hw, yf, yb)`` (§D.3), square neckline to the high-waist seam.
    bodice_rows: tuple = (
        (1.2765, 0.0935, -0.1100, 0.0530),  # square neckline (front top edge between the straps)
        (1.258, 0.0940, -0.1180, 0.0520),   # the top edge at the sides (armpit)
        (1.225, 0.0925, -0.1245, 0.0500),   # bust
        (1.185, 0.0835, -0.1215, 0.0460),
        (1.147, 0.0760, -0.1145, 0.0410),
        (1.116, 0.0705, -0.1090, 0.0365),   # the narrowest (sheet hw 0.0705 at z 1.116)
        (1.108, 0.0724, -0.1103, 0.0376),   # high-waist seam: the lower edge laps seam_relief over the skirt
    )
    bodice_front_exponent: float = 2.2       # a fuller front (bust) ...
    bodice_back_exponent: float = 2.5        # ... and a flatter back
    bust_apex_x: float = 0.045               # §D.3 bust apex x (guide for the front bulge)
    neckline_z: tuple = (1.2765, 1.258, 1.250)   # §D.3 bodice top edge: front (between straps), sides, back (hidden)
    strap_x: tuple = (0.0555, 0.0885)        # §D.3 strap inner / outer edge x at the front (width 0.033)
    #: Strap centreline over the shoulder (her left; the strap is strap_x wide around it, lying on the top + lift).
    strap_path: tuple = ((0.072, -0.0850, 1.2765), (0.072, -0.0784, 1.2900), (0.072, -0.0627, 1.3100),
                         (0.072, -0.0393, 1.3260), (0.072, -0.0100, 1.3330), (0.072, 0.0188, 1.3260),
                         (0.072, 0.0363, 1.3100), (0.072, 0.0360, 1.2900), (0.072, 0.0287, 1.2700),
                         (0.072, 0.0254, 1.2500))
    #                                          (centre of the strap's thickness on top_rows + lift; front end on the
    #                                          bodice's top edge, back end under the cardigan)
    strap_thickness: float = 0.0025
    strap_lift: float = 0.0012               # strap inner face above the top surface
    bodice_lift: float = 0.0020              # the bodice's inner face above the top (where they overlap)
    seam_relief: float = 0.0010              # §D.3 high-waist seam: the bodice's lower edge laps 1 mm over the skirt
    #                                          (bodice_rows[-1] = skirt at 1.108 + this; the skirt's top tucks under)
    #: Skirt outer surface at the flute crests ``(z, hw, yf, yb)`` (§D.4): A-line, from the seam to the hem.
    skirt_rows: tuple = (
        (1.116, 0.0693, -0.1078, 0.0357),   # top edge, tucked 1.2 mm inside the bodice
        (1.108, 0.0714, -0.1093, 0.0366),   # seam (under the bodice's lower edge)
        (1.100, 0.0730, -0.1110, 0.0375),
        (1.060, 0.0820, -0.1170, 0.0410),
        (1.012, 0.0929, -0.1230, 0.0460),
        (0.950, 0.1064, -0.1341, 0.0523),
        (0.889, 0.1196, -0.1439, 0.0689),
        (0.827, 0.1325, -0.1550, 0.0836),
        (0.766, 0.1439, -0.1642, 0.1002),
        (0.704, 0.1565, -0.1734, 0.1168),
        (0.643, 0.1694, -0.1839, 0.1298),
        (0.581, 0.1827, -0.1956, 0.1451),
        (0.520, 0.1950, -0.2060, 0.1581),
        (0.458, 0.2057, -0.2146, 0.1710),
        (0.434, 0.2097, -0.2183, 0.1759),
        (0.390, 0.2125, -0.2215, 0.1790),   # hem (crest mean): the last 4 cm turn out a little (the flare)
    )
    skirt_exponent: float = 2.1
    skirt_flutes: int = 8                    # §D.4 / Decision 10: soft flutes (godets); a crest at the centre front
    #                                          (the sheet: 6-8 soft lobes, about 3 valleys across the front)
    flute_depth: float = 0.020               # crest-to-valley (radial) at the hem (the sheet's hem steps 7-25 mm;
    #                                          20 mm at most) ...
    flute_top_z: float = 0.860               # ... tapering to 0 here (smooth above; they fade by the hip)
    flute_line_top_z: float = 0.620          # the valleys draw as lines from the hem up to here (§F)
    hem_wave: float = 0.010                  # the hem is this much higher at the valleys than at the crests
    placket_x: float = 0.0165                # §D.3 / §D.4: two placket lines at x +-placket_x (the sheet's ink lines
    #                                          33 mm apart framing the button line), creases from the neckline
    #                                          (neckline_z[0]) down the bodice and the skirt to the hem
    skirt_thickness: float = 0.004           # fabric at the hem rim (inner facing 4 mm inside)
    skirt_ceiling_z: float = 0.720           # one shell: the inner facing rises from the hem to this ceiling
    #: Dress buttons (§D.5, Decision 11): 17 teardrops on the centre front, pointed end up: three on the bodice,
    #: a 6 cm gap across the high-waist seam, then the skirt's evenly spaced from button_skirt_z[0] to [1].
    button_bodice_z: tuple = (1.2360, 1.1900, 1.1380)   # the bodice's buttons, top to bottom (sheet)
    button_skirt_z: tuple = (1.0760, 0.4320)  # top / bottom skirt button centres (0.0495 apart; the bottom one 4.2 cm
    #                                           above the hem)
    button_skirt_count: int = 14
    button_size: tuple = (0.0068, 0.0123)    # width x height (sheet 11 x 20 px)
    button_relief: float = 0.0025            # domed height above the dress surface (2.5 mm: the sheet's side view
    #                                          shows no buttons on the front outline; 3.5 mm drew them as teeth)

    # =====================================================================================================
    # B.1 Skin head, neck
    # =====================================================================================================
    cranium_center: tuple = (0.0, -0.015, 1.492)    # §B.1 guide: centre of the skull (camera framing)
    cranium_radii: tuple = (0.074, 0.098, 0.098)
    #: Skin head profile (§B.1): ``(z, hw, yf, yb)``; yf is the face plane at the midline (the nose bump is
    #: separate, :attr:`nose_tip`); ``yb = None``: the back is the neck there (the jaw underside runs in front).
    #: The face is 4-6 mm wider than the sheet's visible skin from the eyes up (the curtains overlap it), so the
    #: eyes do not wrap round the face (Decision 4).
    head_profile: tuple = (
        (1.590, 0.000, -0.0120, -0.0120),   # skull top
        (1.582, 0.034, -0.0460, 0.0200),
        (1.570, 0.050, -0.0700, 0.0400),
        (1.555, 0.060, -0.0880, 0.0560),
        (1.540, 0.067, -0.1000, 0.0650),
        (1.522, 0.072, -0.1080, 0.0720),
        (1.505, 0.074, -0.1125, 0.0765),    # forehead
        (1.495, 0.074, -0.1140, 0.0780),    # brow line: widest skull, forehead front (sheet -0.1138)
        (1.482, 0.073, -0.1110, 0.0785),
        (1.470, 0.071, -0.1060, 0.0780),    # upper lid
        (1.459, 0.068, -0.1020, 0.0770),    # eyes; the bridge (sheet -0.1021); hw 4 mm over the visible skin
        (1.447, 0.064, -0.1030, 0.0745),    # lower lid (sheet visible skin hw 0.060 at 1.4446)
        (1.436, 0.058, -0.1050, 0.0710),    # nose (bump: nose_tip)
        (1.426, 0.0535, -0.1055, 0.0665),
        (1.416, 0.0495, -0.1025, 0.0610),   # mouth
        (1.410, 0.0455, -0.0985, 0.0560),
        (1.404, 0.0385, -0.0925, 0.0490),   # the jaw narrows fast (V chin)
        (1.400, 0.0310, -0.0880, 0.0440),   # last back row: below it the back is the nape / neck
        (1.396, 0.0235, -0.0845, None),
        (1.392, 0.0145, -0.0810, None),
        (1.389, 0.0075, -0.0785, None),
        (1.388, 0.0000, -0.0770, None),     # chin bottom
    )
    face_front_exponent: float = 3.6         # §B.1 front half: |x/hw|^3.6 + |(y-c)/(c-yf)|^3.6 = 1 (a flat face:
    #                                          the eyes wrap 2.0 cm in depth across their 3.95 cm, Decision 4)
    #: §B.1 widest-point offset c by z ``(z, c)`` (linear between, clamped).
    face_center_offset: tuple = ((1.470, -0.0120), (1.410, -0.0080))
    jaw_underside: tuple = ((-0.0770, 1.3880), (-0.0650, 1.3885), (-0.0520, 1.3895), (-0.0400, 1.3920))  # (y, z)
    nape: tuple = (0.0300, 1.3920)           # §B.1 (y, z): the back of the head curves into the neck here
    nose_tip: tuple = (0.0, -0.1125, 1.4355)  # §B.4 bump 7.5 mm proud of the face plane (sheet 10 mm; Decision 5)
    nose_proud: float = 0.0075
    nose_bridge_z: float = 1.452             # the bump starts here (fades into the bridge)
    nose_half_width: float = 0.0060
    nose_base_z: float = 1.4285              # the bump ends at the upper lip
    #: Face-surface y at the feature points (§B.1), ``(x, z, y)``, from :meth:`head_surface_y`.
    face_surface_points: tuple = (
        (0.0395, 1.459, -0.0982),          # eye centre
        (0.0195, 1.459, -0.1017),          # eye inner corner
        (0.0590, 1.459, -0.0816),          # eye outer corner
        (0.028, 1.4963, -0.1129),          # brow inner
        (0.054, 1.5024, -0.1026),          # brow outer
        (0.0, 1.4150, -0.1018),            # mouth
    )
    neck_half_width: float = 0.022           # §B.1 / §D.1 elliptic neck (sheet 0.0221)
    neck_y: tuple = (-0.038, 0.018)          # front / back y (front: sheet -0.0375; back: Decision)
    neck_z: tuple = (1.330, 1.400)           # from inside the mock neck to inside the head

    # =====================================================================================================
    # B.2 Eyes (objects eye_l / eye_r; slabs conform to the face); heterochromia: her right (-x) red, her left (+x) blue
    # =====================================================================================================
    eye_x: float = 0.0395                    # eye centre x (z = eye_z = 1.459); sheet +-0.041
    eye_inner_x: float = 0.0195              # inner corner (sheet lash line 0.0228)
    eye_outer_x: float = 0.0590              # outer corner (sheet lash end 0.066-0.068: Decision 4 narrows the
    #                                          opening; the lash flick reaches 0.066)
    #: Upper boundary of the opening (the upper lid line) ``(x, z)``, inner -> outer: highest at the inner-middle
    #: (x 0.03-0.04), falling 5.5 mm to the outer corner, drooping ~10 deg outward (tare-me; sheet 9.5-11 deg).
    #: It is the sheet's lash lower edge (both eyes averaged) about 0.5 mm lower, so the band covers the sclera's top.
    eye_lid_line: tuple = ((0.0195, 1.4708), (0.0295, 1.4716), (0.0410, 1.4712), (0.0525, 1.4688),
                           (0.0590, 1.4661))
    #: Lower sclera boundary ``(x, z)``, inner corner -> outer corner (each end 1 mm under the lid line).
    sclera_lower: tuple = ((0.0195, 1.4698), (0.0230, 1.4560), (0.0305, 1.4485), (0.0395, 1.4458),
                           (0.0490, 1.4475), (0.0555, 1.4540), (0.0590, 1.4651))
    iris_center_z: float = 1.4590            # iris ellipse centre (x = eye_x); its top ~3 mm into the lash band
    iris_size: tuple = (0.0250, 0.0300)      # width x height (sheet 0.0258 x >= 0.026 visible)
    pupil_center_z: float = 1.4680           # the dark upper iris (the sheet's pupil is the iris's dark top; its
    #                                          lighter lower half is not modelled: Decision 24): its top (1.474) tucks
    #                                          under the lash band, 2.2 mm under the band's top, so only its lower arc
    #                                          draws, a dark cap under the lash with the big highlight in it
    pupil_size: tuple = (0.0160, 0.0120)
    #: One highlight ``(dx from the eye centre, z, diameter)``; the same on both eyes (light from the upper left).
    #: (Review r4-L3: a 2 mm second highlight at the iris's lower right printed as a black dot, read as a low pupil,
    #: at the scene camera's scale; head.py draws one highlight per entry.)
    highlights: tuple = ((-0.0030, 1.4660, 0.0045),)
    eye_slab_depth: float = 0.0003           # every eye / mark slab's back face sits this far below the skin
    decal_skin_clearance: float = 0.00041    # decal front faces at least this far off the skin (0.40 mm final) ...
    decal_layer_clearance: float = 0.0002    # ... and off the decal below them (stacked layers)
    decal_undercut: float = 0.0022           # decal walls: the back outline is the front one moved in this much
    sclera_relief: float = 0.0006            # front face above the skin, per layer
    iris_relief: float = 0.0010
    pupil_relief: float = 0.0013
    highlight_relief: float = 0.0016
    # -- upper lash band (objects face_marks_l / _r, material lashes): thick, dark, with an outer flick --------
    #: The band's lower edge runs from lash_inner along eye_lid_line to lash_outer (drooping outward with it).
    lash_inner: tuple = (0.0205, 1.4714)     # (x, z) inner end of the band's lower edge
    lash_outer: tuple = (0.0600, 1.4660)     # outer end
    lash_height: tuple = (0.0010, 0.0050, 0.0045)   # z height at the inner end, the middle (x of eye_lid_line's
    #                                                 middle point), the outer end (her right eye on the sheet, which
    #                                                 the fringe does not cover); lash_height_quarters between
    lash_flick_tip: tuple = (0.0665, 1.4640)  # (x, z) tip of the flick at the outer end (out and down)
    lash_flick_width: float = 0.0020
    lash_relief: float = 0.0014              # over the top of sclera and iris

    # =====================================================================================================
    # B.3 Brows, B.4 nose and mouth, blush (objects face_marks_l / _r; nose in the skin mesh)
    # =====================================================================================================
    brow_inner: tuple = (0.028, 1.4963)      # (x, z): the inner end is LOWER (sheet, her right brow)
    brow_mid: tuple = (0.041, 1.5005)
    brow_outer: tuple = (0.054, 1.5024)
    brow_width: tuple = (0.0016, 0.0010)     # inner, outer end (tapering)
    brow_relief: float = 0.0008              # her left brow lies under the fringe (modelled, hidden)
    mouth_corners: tuple = (0.0165, 1.4176)  # (x, z) of her left corner (mirrored); closed smile
    mouth_bottom_z: float = 1.4127           # the middle of the U
    mouth_band: float = 0.0006
    mouth_relief: float = 0.0008
    #: Blush hatch strokes (Decision 6): ``count`` strokes per cheek round ``center`` (her left; mirrored centre,
    #: the same lean on both cheeks as drawn).
    blush_center: tuple = (0.050, 1.4375)
    blush_count: int = 3
    blush_stroke: tuple = (0.0060, 0.0005)   # length, width (0.5 mm: the two long borders merge into one stroke)
    blush_spacing: float = 0.0035
    blush_tilt_deg: float = 70.0             # from horizontal, top leaning towards +x on both cheeks
    blush_relief: float = 0.00072            # 0.704 mm on the final model (figure_scale)

    # =====================================================================================================
    # C. Hair (objects tufts, fringe, bob, hair, braid_l / braid_r, hair_under)
    # =====================================================================================================
    #: Outer silhouette of the hair mass (dome + bob) ``(z, hw, yf, yb)`` from the sheet (front and side views),
    #: crown to the eyes (the bob's rows below); yf below 1.50 is the sheet's fringe front (the model's fringe lies
    #: closer, fringe_gap; Decision 8).  The crown is flat and wide: the top rows' hw fit the front / back views'
    #: drop below their own crown (2.3 / 5.2 / 9.8 / 13.2 / 31.9 mm at x 0.025 / 0.037 / 0.049 / 0.057 / 0.075).
    hair_rows: tuple = (
        (1.606, 0.0000, -0.0150, -0.0150),  # crown
        (1.604, 0.0240, -0.0247, -0.0017),  # (yf / yb on the line from the crown to the next row)
        (1.600, 0.0400, -0.0440, 0.0250),
        (1.592, 0.0590, -0.0710, 0.0410),
        (1.582, 0.0680, -0.0890, 0.0550),   # (front view: the tufts sit here)
        (1.573, 0.0760, -0.1020, 0.0650),
        (1.563, 0.0835, -0.1100, 0.0720),
        (1.548, 0.0900, -0.1185, 0.0805),
        (1.533, 0.0950, -0.1255, 0.0873),
        (1.518, 0.1005, -0.1298, 0.0935),
        (1.504, 0.1058, -0.1322, 0.0984),
        (1.489, 0.1105, -0.1328, 0.1021),
        (1.474, 0.1150, -0.1310, 0.1046),
        (1.459, 0.1203, -0.1298, 0.1052),   # eyes (= bob_rows; the bob keeps widening to hw 0.1235 at z 1.43)
    )
    hair_exponent: tuple = (2.3, 2.2)        # front, back half of a hair section
    hair_thickness: tuple = (0.016, 0.014, 0.026, 0.020)   # §C minimum over the scalp: crown, front hairline,
    #                                                         sides, back (the silhouette gives 0.026-0.050 at the
    #                                                         sides and 0.020-0.028 at the back)
    dome_bottom_z: float = 1.500             # H1 dome: closed by a cap buried in the skull about here
    # -- C.2 fringe (bangs), swept to her left from a parting on her right -------------------------------------
    parting: tuple = (-0.028, 1.569)         # (x, z) TRUE coordinates: the parting / apex of the exposed forehead
    #: Fringe locks in TRUE x (asymmetric): ``(root_x, root_z, tip_x, tip_z, root_width, tip_width)``, her right
    #: -> left: the swept lock SL, then four wide locks A-D with a near-level bottom at the upper lash (the sheet).
    #: Roots lie under the dome along the hairline; a lock keeps its width down to fringe_taper of its length
    #: above the tip and then tapers to its tip (pointed when tip_width is 0, else a blunt end that wide), so the
    #: notches between locks stay <= 10 mm deep; neighbours overlap ~2 mm and alternate +-0.6 mm in depth
    #: (fringe_stagger) so they never coincide.
    fringe_locks: tuple = (
        (-0.026, 1.569, -0.063, 1.4717, 0.012, 0.0),    # SL: the swept lock from the parting along hairline_right
        #                                                 (its inner edge is the hairline), the tip over her right
        #                                                 lash's outer end
        (-0.022, 1.565, -0.009, 1.4717, 0.020, 0.0),    # A: its edge bounds the exposed forehead on the right
        (-0.006, 1.563, 0.003, 1.4705, 0.022, 0.012),   # B: the centre lock between the eyes, a 12 mm blunt tip
        (0.004, 1.560, 0.014, 1.4729, 0.022, 0.0),      # C (C and D lean ~6-14 deg to her left, as the sheet's
        (0.028, 1.554, 0.048, 1.4740, 0.030, 0.0),      # D  strand lines): over her left eye; its lower edge is
        #                                                    fringe_lower_edge
    )
    fringe_taper: float = 0.30               # a lock tapers only over this fraction of its length above the tip
    #: Lower edge of lock D (TRUE x, ``(x, z)``): along the top of her left lash band (about 0.5 mm over it, so no skin
    #: shows between) from its lower-inner corner, just outside lock C's tip, through its tip to its outer end, where
    #: it merges into her left curtain's front edge.  (The audit's (0.050, 1.4775) -> (0.062, 1.481) lay 3-7 mm above
    #: the drooping band.  The corner is at x 0.018, as on the sheet, where the lock rests on the lash from px 1965, x
    #: 0.015: starting the edge at x 0.034 left a 20 mm V of forehead between C and D, against the 10 mm notches.)
    fringe_lower_edge: tuple = ((0.018, 1.4745), (0.034, 1.4752), (0.048, 1.4740), (0.062, 1.4700))
    fringe_thickness: float = 0.004
    fringe_gap: tuple = (0.003, 0.005)       # inner surface off the skin at the root / at the tips (Decision 8;
    #                                          the tips' front surface 4.5-12 mm from the skin: the far eye shows)
    fringe_stagger: float = 0.0006
    #: Hairline on her right (TRUE x): the exposed forehead's outer boundary, parting -> temple; the dome's front
    #: edge follows it (on her left the fringe hides the hairline).
    hairline_right: tuple = ((-0.028, 1.569), (-0.038, 1.545), (-0.047, 1.520), (-0.055, 1.492), (-0.062, 1.470))
    # -- C.3 bob: side curtains + back (one crescent opening to the face) --------------------------------------
    #: ``(z, hw, yb, front_x, front_y, t)``: outer hw / back y of the bob, its front edge (the face opening) and its
    #: thickness (§C.3).  A bell: it keeps widening below the eyes to hw 0.1235 at the nose (z 1.425-1.436) and
    #: then curves in to the tips (no flip).  In profile the front edge sweeps back from the temple (y -0.070 at
    #: z 1.495) to y -0.056 at the eye line and -0.053 at z 1.452 (2.6 cm behind the eye's outer corner, 4.6-4.9 cm
    #: of cheek from the face front: the sheet's side view shows the cheek and the eye) and forward again to the
    #: A-line tips beside the jaw (a '(' sweep).  The edge stands about 1-2 mm off the faceted skin (0.6-0.7 mm at
    #: the temple, z 1.488-1.495) and the skin's outline behind it is moved out under the curtain
    #: (``cheek_bulge``), so in the front views the curtain hides the skin's outline and only the curtain's edge
    #: draws as the cheek line (sheet inner edges 0.060 / 0.052-0.055 / 0.049-0.052 at z 1.445 / 1.430 / 1.415);
    #: the inner surface clears the face's side by >= 3 mm (Decision 8).  The row at z 1.495 keeps the curtain's
    #: top corner off the dome's lower rim (no temple dash).  Below z 1.405 only the back reaches: the last rows
    #: curl the back in under to the nape (sheet side-view back edge 0.090 / 0.065 / 0.058 / 0.049 at z 1.403 /
    #: 1.400 / 1.390 / 1.386); their front edge only matters for the front tips at z 1.399.
    bob_rows: tuple = (
        (1.520, 0.1015, 0.0950, 0.0750, -0.0900, 0.018),  # starts under the dome / fringe at the temple
        (1.495, 0.1085, 0.1010, 0.0715, -0.0700, 0.020),
        (1.474, 0.1150, 0.1046, 0.0716, -0.0635, 0.021),  # (a mesh row: the edge follows the wide temple)
        (1.459, 0.1203, 0.1052, 0.0667, -0.0530, 0.022),  # eyes; the eye's outer corner is at y -0.082; the
        (1.445, 0.1227, 0.1040, 0.0667, -0.0530, 0.022),  # mesh samples the edge between these at z 1.452
        (1.430, 0.1235, 0.1010, 0.0556, -0.0580, 0.021),  # widest (the nose: sheet hw 0.1233 at z 1.422-1.437)
        (1.415, 0.1217, 0.0960, 0.0478, -0.0640, 0.019),
        (1.408, 0.1180, 0.0920, 0.0425, -0.0720, 0.017),  # the side tips start at 1.405 (bob_hem_z)
        (1.403, 0.1140, 0.0900, 0.0430, -0.0715, 0.016),  # back curl (only the back columns reach below)
        (1.398, 0.1080, 0.0640, 0.0400, -0.0710, 0.015),
        (1.385, 0.0900, 0.0500, 0.0400, -0.0710, 0.012),  # at the nape (the back centre ends at 1.378)
    )
    #: Lower edge (tip line) of the bob by azimuth ``(phi, z)``: the A-line front locks reach the jaw, the sides
    #: end at 1.405, the back tucks in to the nape (inverted bell, sheet back view).  Since the finishing pass only
    #: the mannequin reads it (``MANNEQUIN_ONLY_FIELDS``); the detailed bob's lower edge is ``bob_lock_columns``.
    bob_hem_z: tuple = ((38.0, 1.3990), (60.0, 1.4030), (90.0, 1.4050), (135.0, 1.3970), (180.0, 1.3780))
    #: Innermost front tips (her left; mirrored): the curtains' lowest locks curve in under the cheeks (the sheet
    #: draws them on the jaw outline at z ~1.408; the tip sits lower to keep >= 3 mm of skin clearance in 3D,
    #: 6.7 mm here: never above z 1.404).
    bob_front_tip: tuple = (0.039, -0.070, 1.399)
    bob_tips: int = 18                       # pointed layered tips round the hem (both sides and the back); the side
    #                                          tips point down or slightly in (no flare), each point at its lock's
    #                                          lower-inner corner (spec only: the lock table sets the tips)
    bob_tip_depth: float = 0.020             # notch root above the tip at the sides (bob_tip_depth_back at the back;
    #                                          spec only since the finishing pass: the lock table's steps)
    #: H4 lavender under-layer (material hair_inner, Decision 7: mandatory, never on the outer surface): per side a
    #: lining of the curtain's inner face over its lowest bob_under_depth (one lavender line under the curtain: since
    #: the finishing pass a short straight strip with pointed ends on the curtain's long front lock, by the jaw), and
    #: one lavender lock hanging from under the bob behind the jaw whose lower edge is a V down to one point midway
    #: between under_lock_tips, its sides ending at the two tips' x (the sheet's lavender spikes between the jaw and
    #: the braids; one lock, not separate thorns; review r3-T6: three teeth drew a W under the chin from knee height,
    #: and the finishing pass's review: two teeth still drew a zigzag).
    bob_under_depth: float = 0.004
    under_lock_tips: tuple = ((0.0285, -0.0290, 1.392), (0.0395, -0.0235, 1.394))  # her left
    under_lock_width: float = 0.008          # the lock's outer sides flare to this width at the root
    under_lock_root_z: float = 1.410         # roots buried in the head's lower back at this height (guide)
    # -- C.4 ear tufts (object tufts, objects[0]) --------------------------------------------------------------
    #: A rounded fin, no hook: its point is the top-inner corner, the inner edge is straight (leaning ~19 deg
    #: outward going up), the outer contour convex; the lobe axis (base centre -> tip) is near vertical, ~4 deg
    #: inward.  Lobe ~3 cm tall and ~3 cm deep.
    tuft_base_center: tuple = (0.066, 0.012, 1.582)   # on the dome's upper-outer slope (her left; mirrored),
    #                                                     2.5 mm above the dome surface (1.5795 there)
    tuft_tip: tuple = (0.064, 0.006, 1.614)  # 32 mm above the base centre, 8 mm above the hair crown
    tuft_base_size: tuple = (0.030, 0.031)   # along the slope (x-z) x depth (y)
    #: Front-view outline (her left, ``(x, z)``; the sheet's front view moved down 1 mm to the model's crown): the
    #: tip, then the convex outer contour down to its junction with the dome silhouette; the inner edge runs
    #: straight from the tip to tuft_inner_notch (where it meets the dome silhouette), leaning ~19 deg outward
    #: going up (sheet 15-18 deg).
    tuft_front_outline: tuple = ((0.0640, 1.6140), (0.0738, 1.6085), (0.0787, 1.6005), (0.0800, 1.5915),
                                 (0.0780, 1.5810), (0.0755, 1.5736))
    tuft_inner_notch: tuple = (0.0566, 1.5930)
    #: Side-view outline (``(y, z)``) of the plate's section ends A / B, not of the built silhouette: hair.py puts the
    #: cup face 2t·n off A and the back face 2t·n off B (n_y ~ -0.57), which adds ~4 mm in front and behind, so this
    #: is the drawn profile moved inward by that inset (less over the tapered top).  Built: the front edge at
    #: y -0.0015 .. -0.0021 up to 3.5 mm under the top, the round top at y 0.006, the convex back edge out to
    #: y 0.029 and straight down to the base (sunk tuft_base_sink into the dome): 29-31 mm deep (sheet 28-31 mm;
    #: review r5-L2: the uncompensated outline built a 36-37 mm deep, low hump).
    tuft_side_outline: tuple = ((0.0030, 1.5800), (0.0030, 1.6050), (0.0016, 1.6090), (0.0012, 1.6120),
                                (0.0060, 1.6140), (0.0130, 1.6120), (0.0172, 1.6085), (0.0219, 1.6005),
                                (0.0240, 1.5930), (0.0240, 1.5830))
    tuft_thickness: float = 0.007            # shell thickness at the rim
    tuft_cup_depth: float = 0.0035           # the concave (inner) face
    tuft_cup_azimuth_deg: float = 35.0       # the cup opens towards the front, turned this far outward
    tuft_outer_bulge: float = 0.010          # the outer contour's bulge (front view), measured from the tip-junction
    #                                          chord (tuft_front_outline is the contour)
    #: The lighter inner face (material tuft_inner): inset from the cup rim by (outer rim, inner rim), so it sits on
    #: the cup's OUTER half (from the front it spans x ~0.068 to the outer contour; a front sliver from the side;
    #: none from the back).  Along the top the inset blends between the two.
    tuft_inner_inset: tuple = (0.0025, 0.009)
    tuft_inner_relief: float = 0.00063       # 0.616 mm on the final model (figure_scale; rule 5; review r5-L2:
    #                                          0.62 mm would leave the re-laid faceted cup's decal 0.474 mm proud)
    tuft_base_sink: float = 0.004            # the base sinks this far into the dome
    # -- C.5 braids (objects braid_l / braid_r) ------------------------------------------------------------------
    #: Centreline (her left; mirrored): root hidden in the curtain -> out under the side hair behind the jaw ->
    #: the tie (last point).  13 deg out and 25 deg back (the sheet's lobe centres lean 23-27 deg); it comes out
    #: at y +0.008 (sheet side view +0.009) and the tie is at y +0.028 (sheet +0.022 .. +0.031).
    braid_path: tuple = ((0.050, 0.005, 1.420), (0.052, 0.008, 1.398), (0.054, 0.015, 1.384),
                         (0.058, 0.022, 1.370), (0.062, 0.028, 1.356))
    braid_lobes: int = 5                     # three-strand look: lobes alternating side to side (top one tucked)
    braid_width: float = 0.017               # the mannequin's braid tube (the detailed lobes use
    #                                          hair.BRAID_LOBE_HALF_WIDTH)
    braid_thickness: float = 0.012
    braid_lobe_tilt_deg: float = 40.0        # each lobe leans this far, alternately left / right (sheet ~40 deg)
    braid_tie_radius: float = 0.0045         # a 9 mm tie band (sheet ~14 px)
    braid_tie_length: float = 0.0040
    #: End tuft: 3 pointed sub-locks from the tie, kicking outward and back (tips, her left); the upper one is the
    #: longest and ends level with the tie (a crescent brush, its locks sagging between the tie and the tips).
    braid_tuft_tips: tuple = ((0.0919, 0.0448, 1.3530), (0.0849, 0.0518, 1.3398), (0.0790, 0.0382, 1.3407))
    braid_tuft_width: float = 0.010          # at the tie (review r4-L2: 14 mm blades sagging 7 mm read as a claw)
    braid_tuft_thickness: float = 0.010      # round strands (review r5-L1: 6 mm blades read as hooks edge-on)

    # =====================================================================================================
    # D.6 Cardigan (objects cardigan, arm_l, arm_r; material cardigan): cropped, worn wide off the shoulders
    # =====================================================================================================
    #: Inner reference surface of the body panels ``(z, hw, yf, yb)``: the cardigan hangs from the bust and the
    #: shoulder blades (it does not follow the under-bust in), cardigan_thickness outward from here.
    cardigan_rows: tuple = (
        (1.322, 0.0980, -0.0680, 0.0500),
        (1.300, 0.1080, -0.0930, 0.0560),
        (1.258, 0.1040, -0.1240, 0.0600),
        (1.225, 0.1010, -0.1285, 0.0600),   # 4 mm off the bust apex
        (1.185, 0.0990, -0.1285, 0.0580),
        (1.150, 0.0980, -0.1280, 0.0560),
        (1.109, 0.0980, -0.1270, 0.0550),   # the over-lap's button stands at y -0.1465 (sheet -0.142)
        (1.060, 0.0980, -0.1265, 0.0540),
        (0.996, 0.0990, -0.1295, 0.0540),
    )
    cardigan_thickness: float = 0.006
    #: Neckline (top edge, her left half): back centre -> over the shoulder -> down the front edge -> the V
    #: crossing (last point).  At the back it is a straight boat line at 1.313-1.321.
    cardigan_neckline: tuple = ((0.000, 0.0525, 1.313), (0.040, 0.0487, 1.316), (0.073, 0.0363, 1.319),
                                (0.0905, 0.0200, 1.321), (0.099, -0.0200, 1.318), (0.099, -0.0572, 1.296),
                                (0.097, -0.0696, 1.272), (0.080, -0.0996, 1.245), (0.060, -0.1161, 1.221),
                                (0.041, -0.1237, 1.196), (0.022, -0.1273, 1.172), (0.007, -0.1279, 1.150))
    #                                          (points on the inner reference surface: cardigan_surface_y)
    #: Her RIGHT front laps over (women's wrap; the sheet's crossover): TRUE coordinates of the over-lap's front
    #: edge from the crossing to its lower corner ...
    overlap_edge: tuple = ((0.007, -0.1379, 1.150), (0.016, -0.1370, 1.128), (0.020, -0.1361, 1.105),
                           (0.019, -0.1360, 1.085), (0.014, -0.1363, 1.072))
    #                                          (y = the over-lap's inner face: the under-lap's outer - overlap_gap;
    #                                          a guide: cardigan.py reads x and z only)
    #: ... and of the under-lap's (her left front) hidden edge under it.
    underlap_edge: tuple = ((0.007, -0.1279, 1.150), (-0.010, -0.1272, 1.125), (-0.030, -0.1247, 1.100),
                            (-0.030, -0.1244, 1.075))
    overlap_gap: float = 0.0040              # the over-lap lies this far in front of the under-lap (r3-L3: 0.0025
    #                                          put the over-lap bands' undercut edge, band_inner_relief inside its inner
    #                                          face, exactly on the under-lap's hem band top, which hid the over-lap
    #                                          hem band's lower border from x 0 to its corner)
    #: Front hem ``(|x|, z)`` from the centre front to the side seam (both fronts; rounded front corners); the
    #: back hem is level at cardigan_back_hem_z.
    cardigan_front_hem: tuple = ((0.000, 1.072), (0.040, 1.061), (0.081, 1.036), (0.094, 1.012), (0.099, 1.000))
    cardigan_back_hem_z: float = 0.996
    hem_band_height: float = 0.032           # ribbed hem band (back 0.996-1.029)
    front_band_width: float = 0.022          # ribbed front bands along the V edges and the back neckline
    band_thickness: float = 0.0075           # bands are separate shells, 1.5 mm proud of the body panels
    band_ribs: int = 0                       # rib lines on the front / neck bands (Decision 12: none)
    hem_band_ribs: int = 0                   # rib creases round the hem band (Decision 12: none, a plain band whose
    #                                          borders draw; 16 widely spaced creases cut it into boxes that read
    #                                          as a segmented belt, and the sheet's ~32 cost ~110 ms per web frame)
    #: The one round button (TRUE coordinates (x, z)); it sits on the over-lap's front band near its inner border.
    cardigan_button: tuple = (-0.001, 1.109)
    cardigan_button_diameter: float = 0.013
    cardigan_button_relief: float = 0.0035
    # -- D.7 balloon sleeves and long ribbed cuffs ----------------------------------------------------------------
    armhole_center: tuple = (0.104, -0.004, 1.262)    # dropped shoulder seam (her left): centre ...
    armhole_radii: tuple = (0.058, 0.060)    # ... half-axes (y, z) of the seam ellipse ...
    armhole_tilt_deg: float = 12.0           # ... its plane leans out at the bottom by this much
    #: Balloon sleeve radius along the arm ``(position, radius)``: 0 shoulder joint, 1 elbow, 2 wrist (the gather).
    sleeve_radii: tuple = ((0.0, 0.035), (0.5, 0.035), (1.0, 0.038), (1.4, 0.044), (1.75, 0.050), (1.95, 0.046),
                           (2.0, 0.034))
    balloon_drop: float = 0.010              # the bag hangs this far below its gather on the under side
    balloon_offset: tuple = (0.004, 0.020)   # sleeve centre off the arm axis: outward (x), backward (y); the bulk
    #                                          hangs behind the arm (the sheet's side-view drape reaches y +0.105)
    #: Depth / width ratio of the sleeve section ``(position, ratio)``: round at the shoulder, deeper than wide
    #: (front-back) along the forearm (Decision 15).
    sleeve_depth_ratio: tuple = ((0.0, 1.05), (1.0, 1.2), (1.75, 1.35), (2.0, 1.0))
    #: Long ribbed cuff: a cone from the gather, cuff_gather_offset above the wrist, cuff_length along the forearm to
    #: a wide mouth just short of the knuckles, flaring linearly from cuff_radius to cuff_end_radius (the sheet's four
    #: cuffs: dia 56-76 at the gather to 73-86 mm at the mouth); the back of the hand shows for about 1.4 cm below the
    #: mouth before the five digits part (the sheet: about 14 mm).  Finishing pass: the cuff hangs cuff_offset outside
    #: the forearm and its mouth is level (cuff_mouth_level), longer on its outer side, as the sheet draws it (its
    #: outer edge 0.209 -> 0.221 from z 0.87 to 0.84, its inner edge 0.136 -> 0.139).
    cuff_length: float = 0.046
    cuff_gather_offset: float = -0.007       # the gather (the balloon's lower end, the cuff's top) lies this far above
    #                                          the wrist along the forearm (negative: below it)
    cuff_radius: float = 0.032               # at the gather (dia 64 mm) ...
    cuff_end_radius: float = 0.0405          # ... at the mouth (dia 81 mm)
    cuff_ribs: int = 8                       # rib creases round each cuff (Decision 12)
    cuff_opening_radius: float = 0.0360      # the mouth's rim turned in to this opening (finishing pass: unread, the
    #                                          mouth turns straight into its recess cone)

    # =====================================================================================================
    # D.8 Hands (open, relaxed, palm forward, fingers fanned; Decision 3: five fingers)
    # =====================================================================================================
    palm_length: float = 0.068               # wrist -> knuckle line along the palm axis: the cuff's mouth crosses it
    #                                          at 48 mm, so the back of the hand shows for ~2 cm below the mouth
    palm_width: float = 0.050                # fits the cuff (every palm corner inside it >= 3 mm off its wall)
    palm_thickness: float = 0.020
    palm_turn_deg: float = 15.0              # the palm faces forward (-Y), turned this far towards the body
    #: Fingers ``(name, across, along, length, thickness, fan_deg, curl_deg)``: base offset across the palm
    #: (+ towards the thumb = outward), along the palm from the wrist (fraction of palm_length), length,
    #: thickness at the base (tapering to finger_taper), fan angle in the palm plane (+ outward), curl at each
    #: joint (towards the palm).  A relaxed open hand (finishing pass, the user's review: the sheet's splayed, straight
    #: digits read as a mannequin's): the four fingers lie close together (fanned 15 / 10 / 2 / -9 deg about the hand
    #: axis, was 28 / 10 / -24 / -38), each joint curled 16-26 deg (more towards the little finger, as a hanging hand
    #: curls), the thumb shorter and thicker, rooted further back and curled forward, so it reads as a thumb beside
    #: the index (was 46 deg out, straight); still five separate digits (Decision 3).  The middle tip is the lowest
    #: point, where the sheet draws the lowest fingertip (A4).  Every finger tube starts inside the palm block, its
    #: outer edge (|across| + 0.575 thickness) at least 2 mm inside palm_width / 2, so no tube's flat start shows past
    #: the block's side.
    fingers: tuple = (
        ("thumb", 0.014, 0.80, 0.046, 0.0145, 30.0, 18.0),
        ("index", 0.010, 1.00, 0.050, 0.0125, 15.0, 16.0),
        ("middle", 0.000, 1.00, 0.052, 0.0125, 10.0, 18.0),
        ("ring", -0.010, 1.00, 0.042, 0.0118, 2.0, 22.0),
        ("little", -0.016, 0.90, 0.032, 0.0108, -9.0, 26.0),
    )

    # =====================================================================================================
    # D.9 Legs, socks, shoes
    # =====================================================================================================
    leg_top_z: float = 0.730                 # inside the skirt ceiling
    #: Leg radius by z (circular): ``(z, r)`` top to bottom (sheet below the hem; above it a guide).
    leg_radii: tuple = ((0.800, 0.0580), (0.700, 0.0530), (0.600, 0.0480), (0.520, 0.0430), (0.475, 0.0405),
                        (0.420, 0.0405), (0.360, 0.0400), (0.340, 0.0390), (0.290, 0.0360), (0.250, 0.0320),
                        (0.200, 0.0285), (0.150, 0.0265), (0.110, 0.0250), (0.085, 0.0245))
    sock_ease: float = 0.0015                # white socks = leg + 1.5 mm from the shoe up to the cuff
    sock_cuff_z: tuple = (0.202, 0.255)      # turned-down cuff: bottom (a drawn edge), top (the rounded fold)
    sock_cuff_ease: float = 0.0062           # cuff outer radius = leg + this (sheet r 0.0372)
    sock_cuff_thickness: float = 0.004       # the fold
    star_center_z: float = 0.225             # navy star on the outer side of each cuff (material star)
    star_azimuth_deg: float = 65.0           # from the front towards the outer side
    star_radii: tuple = (0.0068, 0.0029)     # outer / inner radius of the 5-point star
    star_relief: float = 0.0008
    shoe_length: float = 0.188               # brown penny loafers (sheet 0.185), along the turned-out foot axis
    shoe_heel_back: tuple = (0.055, 0.035)   # (x, y) of the heel back on the ground, her left
    shoe_toe_out_deg: float = 0.0            # the feet are parallel (the sheet's apron centrelines are vertical)
    shoe_ball_width: float = 0.073
    shoe_heel_width: float = 0.060          # holds the sock (r 0.028 at the topline) with 2 mm walls
    shoe_ball_u: float = 0.70                # the ball (widest) at this fraction of the length from the heel
    shoe_sole: float = 0.0135                # sole slab under the forefoot (its own smooth group; sheet 13.5-15 mm)
    shoe_heel_height: float = 0.034          # block heel height (z 0 .. 0.034)
    shoe_heel_length: float = 0.050          # block heel length from the back (sheet 48 at the ground, 54 at the top)
    shoe_topline_z: tuple = (0.098, 0.090)   # opening rim at the heel back / along the sides
    shoe_toe_height: float = 0.052           # top of the moc toe (sheet 0.051-0.055)
    shoe_vamp_z: float = 0.080               # instep (top of the saddle strap)
    strap_u: float = 0.58                    # saddle strap centre at this fraction of the length from the heel
    shoe_strap_width: float = 0.016
    shoe_strap_relief: float = 0.0028         # the strap stands this proud of the upper (a visible leather band)
    penny_slot: tuple = (0.020, 0.004)       # slot on the strap (length, width): its outline, a shallow recess in
    #                                          the strap's top (Decision 14)
    apron_relief: float = 0.0012             # moc-toe apron seam: a raised U piping round the toe

    # =====================================================================================================
    # E. Pose (relaxed A-pose from the sheet; the joint positions are binding, the angles document them)
    # =====================================================================================================
    #: The arms hang a little behind the torso's mid-depth (y +0.00 .. +0.022): the torso is narrower there, so
    #: the upper arm fits beside it while the front view shows the arm overlapping the torso side, as the sheet
    #: draws it (SPEC.md §E, Decision 16).
    shoulder_joint_pos: tuple = (0.088, 0.000, 1.285)    # §E (upper arm outer edge at x 0.111 on the sheet)
    elbow_pos: tuple = (0.100, 0.022, 1.095)             # at the high-waist seam (sheet ~1.10-1.12)
    wrist_pos: tuple = (0.160, 0.002, 0.885)             # sheet (0.159, 0.886) (finishing pass: was 0.170)
    fingertip_pos: tuple = (0.2091, -0.0100, 0.7843)     # end of the palm axis (wrist -> fingertip_pos is the hand
    #                                                      axis, 26 deg out, 10 deg off the forearm: the palm leaves
    #                                                      through the cuff's mouth, which hangs outside the wrist;
    #                                                      the fingers fan round it)
    arm_abduction_deg: float = 3.6           # upper arm, frontal plane (documentation of the joints above)
    forearm_out_deg: float = 15.9            # forearm out from vertical (sheet ~16); elbow bent ~17 deg
    hand_out_deg: float = 26.0               # palm axis (wrist -> fingertip_pos) out from vertical (sheet wrist ->
    #                                          knuckles 24 deg, knuckles -> middle tip 36 deg)
    hip_joint_pos: tuple = (0.068, -0.004, 0.860)
    knee_pos: tuple = (0.062, -0.003, 0.475)
    ankle_pos: tuple = (0.056, 0.000, 0.085)

    # =====================================================================================================
    # ---- builder fields: head.py / hair.py ----
    # (append-only: only the owner of head.py / hair.py appends fields here)
    # =====================================================================================================
    #: §B.2 stacked decals: every eye layer (and the lash band over them) stands at least this far proud of the decal
    #: under it (the hidden-line rule: an outline less than ~0.5 mm over the surface below is eaten); the reliefs above
    #: (sclera 0.6 / iris 1.0 / pupil 1.3 / highlight 1.6 mm over the skin) become 0.6 / 1.12 / 1.64 / 2.16 mm where the
    #: layers overlap.  0.52 at the sheet scale: 0.508 mm on the final model (figure_scale 0.9775; rule 5's 0.5 mm).
    decal_layer_step: float = 0.00052
    #: §C.1 the dome's hairline on her left (TRUE x, ``(x, z)``, parting height -> temple): hidden under lock D (the
    #: mirror of ``hairline_right``); the dome dives into the skin below it, and the temple hair lies outside it.
    hairline_left: tuple = ((0.028, 1.569), (0.038, 1.545), (0.047, 1.520), (0.055, 1.492), (0.062, 1.470))
    #: §C.3 the notch depth at the back centre (``bob_tip_depth`` at the sides, blended by the hem height): the back
    #: curl rows leave room for only 12 mm there (spec only since the finishing pass: the lock table's steps).
    bob_tip_depth_back: float = 0.012
    #: §B.2 the lash band's height at the x of ``eye_lid_line``'s second and fourth points (between the stations of
    #: ``lash_height``): the band's top is a smooth arc through the five stations (no peak at the middle).
    lash_height_quarters: tuple = (0.0036, 0.0052)
    #: §B.1 / §C.3 the hidden cheek bulge ``(z, b)`` (linear between, 0 outside): the head mesh's side column behind
    #: the bob's front edge (``head.CHEEK_BULGE_COLUMN``, y ~ -0.037) moves out by ``b``, so in the front views the
    #: skin's outline lies behind the curtain (covered by it) and only the curtain's edge draws as the cheek line,
    #: although the edge stands back where the cheek shows in profile.  The curtain covers the bulge from every view.
    cheek_bulge: tuple = ((1.500, 0.0), (1.486, 0.0026), (1.465, 0.0032), (1.440, 0.0032), (1.425, 0.0026),
                          (1.408, 0.0))
    #: §C.3 (finishing pass) the bob's long locks hang from its bell below this height (the lock zone's top row);
    #: the two slits beside the side lock reach up to it (the sheet's front and back views: the outermost strand
    #: stands off the curtain with background between, from about the eye line down).
    bob_slit_top_z: float = 1.452
    #: §C.3 the slits through the bob's side below ``bob_slit_top_z`` (front and back view, |x|): the curtain's front
    #: lock and the back lock end at ``[0]``; the side lock's inner (flat) face is at ``[1]`` (the sheet's gap: front
    #: view x 0.1129-0.1141, back view 0.1116-0.1141 on her left, 0.1135-0.1165 on her right; one symmetric slit).
    bob_slit_x: tuple = (0.1130, 0.1146)
    #: §C.3 the lock zone's columns (her left, mirrored), from the face-window edge round to the back centre:
    #: ``(kind, a, z_bottom, step_side, step_z)``.  ``kind``: ``edge`` (its bottom is ``bob_front_tip``), ``face``
    #: (on the curtain's front face, its bottom at x ``a``), ``facex`` (front face, at ``bob_slit_x[0]``: the front
    #: slit's inner side), ``gap`` (a slit between the neighbours), ``sfront`` / ``sback`` (the side lock's front /
    #: back edge, at ``bob_slit_x[1]``), ``side`` (the side lock, its bottom at azimuth ``a``), ``backx`` (back
    #: contour, at ``bob_slit_x[0]``: the back slit's inner side), ``back`` (back contour, its bottom at x ``a``),
    #: ``centre`` (the nape).  A step (``step_side`` -1: towards the edge, +1: towards the centre) ends the lock on
    #: that side on this column at ``step_z``, above this column's own tip: the locks are layered, each tip at its
    #: inner (face-side or nape-side) end and each lower edge rising outward, as the sheet draws them (front view
    #: tips at |x| 0.069 / 0.092 / the side strand 0.115, notches 0.0687 / 0.0915; back view tips 0.092 / 0.070 /
    #: 0.030, the nape 1.374).
    bob_lock_columns: tuple = (
        ("edge", 0.0, 0.0, 0, 0.0),
        ("face", 0.0580, 1.4035, 0, 0.0),
        ("face", 0.0815, 1.4057, 0, 0.0),
        ("face", 0.0918, 1.4052, -1, 1.4158),
        ("face", 0.1000, 1.4105, 0, 0.0),
        ("facex", 0.0, 1.4370, 0, 0.0),
        ("gap", 0.0, 0.0, 0, 0.0),
        ("sfront", 0.0, 1.4085, 0, 0.0),
        ("side", 84.0, 1.4075, 0, 0.0),
        ("side", 90.0, 1.4070, 0, 0.0),
        ("side", 102.0, 1.4075, 0, 0.0),
        ("sback", 0.0, 1.4085, 0, 0.0),
        ("gap", 0.0, 0.0, 0, 0.0),
        ("backx", 0.0, 1.4370, 0, 0.0),
        ("back", 0.0995, 1.4128, 0, 0.0),
        ("back", 0.0922, 1.4055, 1, 1.4150),
        ("back", 0.0830, 1.4062, 0, 0.0),
        ("back", 0.0600, 1.4005, 0, 0.0),
        ("back", 0.0302, 1.3853, 1, 1.3921),
        ("back", 0.0150, 1.3795, 0, 0.0),
        ("centre", 0.0, 1.3740, 0, 0.0),
    )
    #: §C.3 (leaf pass) the side lock's two lower corners ``(front, back)``: a radius > 0 rounds that corner into the
    #: lower edge with a circular arc (``hair.BOB_SIDE_CORNER_SEGMENTS`` segments; the lock's shoulder), 0 makes it a
    #: point (``bob_side_back_tip``); ``None``: both edges run down the contour as before the leaf pass.  19 mm
    #: (V4 pass; 16 before): the 3/4 views foreshorten the arc's end along the lower edge to 0.57, so its last two
    #: chords stay 1.2 px long only with 9-10 degree steps at this radius; with the first side column at azimuth 84
    #: the arc's end is 14 mm before that column's tip (at 78 the lower edge's 2 mm step in x from the edge strip to
    #: the lock's body, seen from below, folded 15 degrees).
    bob_side_corner_radius: tuple = (0.019, 0.0)
    #: §C.3 (leaf pass) a pointed corner's tip: this far behind (away from the lock; negative: towards it) and this far
    #: below the corner of the edge's and the lower edge's lines; the back edge runs straight down to it from z 1.428,
    #: so the lower edge falls into a point at the lock's back (a leaf seen from the side; from below a designed tip
    #: over 60 degrees).  6 mm towards the lock: the back edge leans down and forward as the sheet's profile strokes
    #: there do, and the lower edge's thin plate is 17.5 mm long (at +6 mm it leaned back, a 29 mm blade from below).
    #: 2 mm below (V4 pass; 2.5 before): with the side lock's middle column raised to z 1.4070 the 3/4 views read the
    #: drop at the next column as a 12 degree turn.
    bob_side_back_tip: tuple = (-0.006, 0.0020)
    #: §C.3 (leaf pass) the lock zone's inserted columns: ``(after, frac, kind, a, z_bottom)`` (kind "back") or
    #: ``(after, frac, "backc", a, z_bottom, phi_top)``, each a column of ``kind`` / ``a`` / ``z_bottom`` as in
    #: ``bob_lock_columns`` (no step), between that table's column ``after`` and the next one.  ``after + frac``
    #: (0 < frac < 1, each used once) is only its stable index: its place in the order and its label (the table's
    #: indices stay as they are, so ``hair.BOB_STRANDS`` / ``BOB_SPLIT_STRAND`` and the lining's stations keep their
    #: meaning); it moves no point.  A "back" column lies on the chord between its two neighbours, blended at the
    #: fraction that puts its tip's x at ``a``, only its lower end moved to ``z_bottom`` (the nape, where the back
    #: curls under).  A "backc" column (V4 pass) lies on the contour itself, like the table's back columns: its
    #: azimuth runs from ``phi_top`` (degrees) at the lock zone's top row to that of x = ``a`` at ``z_bottom`` (the
    #: chord put column 13.66 1.5-3 mm inside the surface, which the 3/4 views see edge-on there: a back-facing
    #: sliver among front-facing facets drew a 5 px fold loop).  Column 13.66 follows the 3/4 views' grazing line
    #: down the back lock beside the slit (x 0.1038 at the top, 0.1055 at its tip; the surface's normal 1.5 degrees
    #: beyond the grazing azimuth, so the strips on both sides of it face the cameras by 2.5-3 degrees), and its
    #: tip is on the leaf curve.  The bottoms sample each lock's lower edge between the existing tips on the sheet's
    #: convex curve (back view): the back lock from its tip (column 15) up to the back slit's end (column 13),
    #: leaving the tip at 28 degrees and meeting the slit's side upright (the sheet: 35 -> 59 -> 81 degrees), the
    #: next lock from the step at column 15 down to column 17 (the sheet: 47 degrees at the notch, flattening
    #: towards its tip).  The heights are fitted so that the lower edge's projected turns stay under 12 degrees in
    #: the 3/4 and low views (columns 14 and 16 moved with them; V4: column 14 at 1.4128 and 14.51 at 1.4092, the
    #: curve's x-z turns 11 degrees each from the slit's end to the tip).
    bob_leaf_columns: tuple = (
        (13, 0.66, "backc", 0.1055, 1.4214, 123.0),
        (14, 0.51, "backc", 0.0960, 1.4092, 129.2),
        (15, 0.48, "back", 0.0878, 1.40925),
        (16, 0.23, "back", 0.0778, 1.4041),
        (16, 0.57, "back", 0.0700, 1.4020),
    )

    # =====================================================================================================
    # ---- builder fields: body.py ----
    # (append-only: only the owner of body.py appends fields here)
    # =====================================================================================================
    # -- D.2 the white mock-neck top -------------------------------------------------------------------------
    mock_neck_inner_depth: float = 0.012     # the mock neck's inner wall runs this far down from the rim to the dent's
    #                                          floor (hidden: the neck passes through it; 4.5-8 mm of gap show)
    top_torso_end_z: float = 1.240           # the top's torso ends here with a cap buried in the bodice (the bodice is
    #                                          a solid: nothing of the top shows below its top edge) ...
    top_bodice_inset: float = 0.003          # ... its rows below the bodice's top edge shrink this much (the A.2 rows
    #                                          there are within 0.5 mm of the bodice's faceted surface)
    top_skip_rows: tuple = (1.330,)          # top_rows the faceted top leaves out (linear between its neighbours there
    #                                          within 1 mm)
    top_sleeve_start: float = -0.15          # the white sleeve tube starts at this arm position (before the shoulder
    #                                          joint, inside the torso) in a point
    # -- D.3 bodice and straps -------------------------------------------------------------------------------
    bodice_ring_z: tuple = (1.225, 1.185, 1.116)   # bodice sections between the top edge and the seam ring (the
    #                                                bodice_rows the faceted solid keeps; 1.258 / 1.147 are linear)
    bodice_tuck: float = 0.006               # the bodice's top ledge runs in from its edge to this far inside the top's
    #                                          surface (level per column; its inner part is hidden in the top)
    strap_tuck_length: float = 0.012         # each strap dives over this length of its path before the bodice's top
    #                                          edge ...
    strap_tuck_offset: float = -0.0022       # ... to this offset of its inner face from the top's surface (its outer
    #                                          face then lies under the bodice's: the neckline line runs across it) ...
    strap_tuck_extension: float = 0.004      # ... and runs on this far into the bodice
    strap_back_x: tuple = (0.042, 0.075)     # strap inner / outer edge x at the back end: from the shoulder top the
    #                                          strap moves in to these (the back is narrower; the sheet's back view
    #                                          shows the navy at x 0.050-0.075 above the cardigan's band)
    # -- D.4 skirt -----------------------------------------------------------------------------------------------
    skirt_ring_z: tuple = (1.116, 0.950, 0.860, 0.700, 0.550, 0.434)   # skirt sections above the hem (the A-line is
    #                                          straight between them within 0.5 mm; the flutes are linear in z)
    #: Flute-valley line stripes (§D.4 / §F: thin single-group ridge shells lying in the valleys from the hem up to
    #: flute_line_top_z; a group boundary cannot end in the middle of a smooth surface): half-width at the hem and at
    #: the top end, float of their borders above the valley walls (0.313 mm on the final model; 0.31 -> 0.32 in review
    #: round 4: the skirt's ridge-fanned triangles bulge between the valley columns, and at 0.31 the borders stood only
    #: 0.288 mm over them, under the sheet-scale model's 0.290; now >= 0.299, Decision 1), ridge height above the
    #: valley.
    valley_stripe: tuple = (0.0006, 0.0001, 0.00032, 0.0010)
    # -- D.5 dress buttons -------------------------------------------------------------------------------------
    button_float: float = 0.0006             # the teardrop's flat back floats this far above the dress surface (its
    #                                          outline draws: >= 0.5 mm proud, rule 5)
    # -- review round 1 ----------------------------------------------------------------------------------------
    top_fold_dip: float = 0.0035             # §D.2 the fold at the mock neck's base dips this much at the centre front
    #                                          and back (cos^2 of the azimuth, level at the sides), sliding down the
    #                                          top's surface: a soft U in the front view (sheet z 1.341 at the ends,
    #                                          1.335 at the centre), not a ruler-straight line
    button_skirt_relief: float = 0.0015      # §D.5 the skirt's 14 teardrops are domed this high (button_relief: the
    #                                          bodice's three): they sit on the skirt's front crest, the side views'
    #                                          outline, where 2.5 mm still drew 14 teeth (>= button_float + 0.5 mm)
    # -- review round 2 ----------------------------------------------------------------------------------------
    top_fold_z: float = 1.342                # §D.2 the fold at the mock neck's base lies on the top_rows row at this z
    #                                          (level at her sides, top_fold_dip lower at the centre front and back);
    #                                          the top_rows above it are the mock neck's flare (its outer wall, no
    #                                          line), dipping with the fold in proportion (body._flare_point)
    # -- review round 4 ----------------------------------------------------------------------------------------
    lettuce_rim_width: float = 0.0010        # §D.2 the lettuce rim's top face is this wide (radially, inward from the
    #                                          lip turned out lettuce_flare): the inner wall flares from
    #                                          mock_neck_thickness at the dent's floor up to it.  Seen edge-on at the
    #                                          sides, the 4.5 mm face's radial edges drew a stack of 3-4 boxes (r4-T1)
    lettuce_side_amplitude: float = 0.75     # §D.2 the rim waves' amplitude at her sides as a fraction of
    #                                          lettuce_amplitude (blended by cos^2 of the azimuth: full at the centre
    #                                          front and back): less zigzag where the front views see the rim edge-on
    # -- v2 finishing pass: triangles freed where the jumper and the cardigan always cover the top --------------
    #: §D.2 the two top rows below the shoulder-point row of top_rows (z, the first item) leave out their points at
    #: azimuths from the second to the third item (round the back, under the cardigan's back panel and in the bodice;
    #: it stops one column short of her right back side, where the top's light silhouette runs down the torso)
    top_back_cut: tuple = (1.300, 108.0, 234.0)
    #: §D.3 the bodice's back under the cardigan's back panel: the section-angle ranges (t, deg; 90 = centre back) of
    #: the columns that the ledge's inner ring, the 1.225 row and the 1.185 row leave out (the top edge, its neckline
    #: line and its rays stay; the 1.225 row keeps her right back side's column, where the bodice's light silhouette
    #: turns down the back)
    bodice_back_cut: tuple = ((30.0, 150.0), (30.0, 135.0), (45.0, 135.0))

    # =====================================================================================================
    # ---- builder fields: cardigan.py / limbs.py ----
    # (append-only: only the owner of cardigan.py / limbs.py appends fields here)
    # =====================================================================================================
    # -- cardigan.py: body panel, bands, button (§D.6) ------------------------------------------------------
    #: Her RIGHT front's V edge below its bend (TRUE ``(x, z)``): it leaves the mirrored neckline at z 1.196 and runs
    #: straight to the crossing at x +0.007 (the sheet: x -0.042 at 1.196, crossing +0.007 at 1.150), so the
    #: over-lap's V crosses the centre line.
    overlap_v_edge: tuple = ((-0.041, 1.196), (-0.017, 1.173), (0.007, 1.150))
    overlap_lift_width: float = 0.045        # the over-lap stands cardigan_thickness + overlap_gap off the reference
    #                                          where the under-lap lies under it and fades to 0 over this x range
    #                                          beyond the under-lap's edge (towards her right side)
    band_float: float = 0.00031              # the bands' inner borders float this far over the panel (they draw as
    #                                          silhouettes: the band's underside is undercut there; 0.30 mm final)
    band_overhang: float = 0.0015            # the bands wrap the panel's edge and stand this far beyond it
    band_inner_relief: float = 0.0010        # ... and this far inside the panel's inner face
    cardigan_button_rim: float = 0.0006      # the button's rim stands this far over the band's top
    # -- cardigan.py: sleeves and cuffs (§D.7) --------------------------------------------------------------
    sleeve_cap_depth: float = 0.012          # the balloon's top closes in a dome this deep over its shoulder ring
    #                                          (under the neck band's end)
    #: The balloon's shoulder ring above its ring at the shoulder joint (in that ring's frame): its centre moved
    #: ``(outward, up)`` from the joint's sleeve centre and its ``(lateral, depth)`` radii.  The cap is one round puff
    #: that continues the shoulder's curve into the sleeve (front outline 0.118 / 0.122 / 0.123 at z 1.310 / 1.305 /
    #: 1.300; the sheet 0.115-0.121 / 0.117-0.123 / 0.118-0.126) and keeps the white sleeve tube's pointed start (in
    #: the torso) 3 mm outside the sleeve (castplane's nesting test needs one tube vertex outside it).
    sleeve_shoulder_ring: tuple = (0.001, 0.016, 0.031, 0.033)
    cuff_tuck: float = 0.010                 # the ribbed cuff starts this far inside the balloon's gather
    cuff_recess: float = 0.015               # the cuff's mouth turns in as a recess cone this deep (the palm passes it)
    #: The balloon sleeve's rings (finishing pass: the sheet's balloon), from the shoulder joint down to the bag's
    #: widest ring (her left): ``(position, lateral radius, depth radius, outward offset, backward offset, level)``.
    #: Each ring is an ellipse round the arm axis point at ``position`` (0 shoulder joint, 1 elbow, 2 wrist;
    #: :meth:`arm_point`) moved outward (x) and backward (y), its plane perpendicular to the sleeve's centre line and
    #: turned ``level`` (0 .. 1) of the way to horizontal.  Fitted to the sheet's balloon (front and back views, both
    #: sides averaged: outer half-width 0.130 at z 1.20, 0.150 at 1.10, 0.174 at 1.00, widest 0.215 at 0.90, rounding
    #: in to 0.209 over the cuff) with the inner side kept where it clears the skirt; the last ring is the bag's widest
    #: and closes in its rounded bottom (sleeve_bag_depth).  It supersedes sleeve_radii / sleeve_depth_ratio /
    #: balloon_offset / balloon_drop for the detailed model (the mannequin still reads the first three).
    sleeve_rings: tuple = (
        (0.000, 0.0320, 0.0340, 0.0030, 0.0000, 0.00),
        (0.600, 0.0348, 0.0389, 0.0015, 0.0120, 0.00),
        (1.250, 0.0415, 0.0518, 0.0067, 0.0200, 0.00),
        (1.680, 0.0440, 0.0581, 0.0082, 0.0180, 0.30),
        (1.970, 0.0451, 0.0505, 0.0124, 0.0080, 0.40),
    )
    sleeve_bag_depth: float = 0.030          # the bag's last (widest) ring closes in a rounded bottom this deep;
    #                                          its pole lies inside the cuff, which comes out of it
    sleeve_bag_converge: float = 0.3         # the bottom's rings move this fraction of the way onto the cuff's axis
    #                                          (towards the pole), so its lower rings hug the cuff all round
    sleeve_gather_ring: int = 2              # the bottom's rings below this one (1 = the first under the widest) are
    #                                          a second smooth group: the boundary, just outside the cuff, draws the
    #                                          gather (the cuff's top) wherever it is seen
    cuff_offset: float = 0.006               # the cuff's axis lies this far outward of the forearm's (the sheet's
    #                                          cuffs hang outside the wrist of its cardigan-off view)
    cuff_mouth_level: float = 1.0            # the cuff's mouth plane is turned this fraction of the way from
    #                                          perpendicular to its axis to level (the sheet draws it level)
    # -- limbs.py: hands (§D.8) ----------------------------------------------------------------------------
    finger_taper: float = 0.80               # §D.8 a finger's tube tapers to this fraction of its base thickness
    palm_end_thickness: float = 0.014        # the palm thins to this at the knuckles (the fingers leave it there)
    # -- limbs.py: legs, socks (§D.9) ------------------------------------------------------------------------
    leg_bottom_z: float = 0.240              # the bare leg ends inside the sock, under the cuff's top
    sock_tube_top_z: float = 0.250           # the sock tube ends inside the turned-down cuff (its top is hidden)
    #: The sock's foot inside the loafer (her left; ``(u, z)`` along the foot from the heel back): it bends forward
    #: from the ankle so the instep fills the shoe's opening up to the throat ...
    sock_foot_path: tuple = ((0.068, 0.055), (0.115, 0.030))
    sock_foot_size: tuple = ((0.042, 0.038), (0.036, 0.022))   # ... (width, thickness) at those stations
    sock_ankle_squeeze: float = 0.003        # the sock tube narrows by this (radius) at the ankle bend, inside the
    #                                          shoe, so it stays clear of the loafer's topline round the heel
    star_depth: float = 0.0003               # the star decal's back face sits this far inside the cuff facet ...
    star_undercut: float = 0.0024            # ... and its back outline is smaller, its inner corners this much (the
    #                                          walls undercut ~65 deg, so the outline stays a silhouette in side views)
    # -- limbs.py: shoes (§D.9, Decision 14) -------------------------------------------------------------------
    shoe_ball_contact_u: float = 0.585       # the forefoot sole touches the ground from here (fraction of the length
    #                                          from the heel back); the arch rises from here back to the block heel
    shoe_heel_sole: float = 0.006            # sole layer over the block heel (the sole line rises to heel + this)
    shoe_heel_slant: float = 0.003           # the block's front face leans: heel length -+ this at the ground / top
    shoe_toe_radius: float = 0.032           # the rounded toe (half ellipse this long at the front of the outline)
    #: Foot opening (topline loop): back u, front u (the throat on the instep), half width (the sock r 0.026 at the
    #: ankle with ~2 mm to spare; the heel's 2 mm walls).
    shoe_opening: tuple = (0.006, 0.088, 0.029)
    shoe_throat_z: float = 0.082             # the topline at the throat (on the instep, under the strap's back edge)
    shoe_opening_floor_z: float = 0.040      # the opening's inner wall drops straight down to a flat floor this high
    #                                          (hidden in the sock)
    shoe_strap_end_z: float = 0.050          # the saddle strap runs down the sides of the upper to about here
    shoe_toe_tip_height: float = 0.045       # the toe box's top slopes from shoe_toe_height at the ball to this at
    #                                          the tip, where its blunt front drops almost straight to the sole (the
    #                                          sheet's side view: a near-vertical front up to z 0.043-0.045 under the
    #                                          apron's lip; r4-L5)
    shoe_decal_float: float = 0.00041        # strap / apron borders float this far over the faceted surface (0.40 mm
    #                                          final)
    #: Moc-toe apron seam: the U of the raised piping on the toe box (her left half, ``(u, v)`` from the strap's front
    #: edge round the toe to the centre line; mirrored in v) and the piping's width.
    apron_path: tuple = ((0.119, 0.025), (0.146, 0.027), (0.165, 0.022), (0.175, 0.012), (0.178, 0.0))
    apron_width: float = 0.0026
    penny_slot_depth: float = 0.00052        # the penny slot is sunk this far into the strap's top (its outline draws;
    #                                          0.508 mm on the final model, rule 5)

    # -----------------------------------------------------------------------------------------------------
    # construction
    def __post_init__(self):
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            if isinstance(v, list):
                object.__setattr__(self, f.name, _tuplify(v))

    def replace(self, **changes) -> "Rig":
        """A copy with some fields changed (unknown names raise ``TypeError``)."""
        return dataclasses.replace(self, **changes)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, values: dict) -> "Rig":
        """Defaults updated by ``values`` (JSON lists become tuples); unknown keys raise ``KeyError``."""
        names = {f.name for f in dataclasses.fields(cls)}
        unknown = sorted(set(values) - names)
        if unknown:
            raise KeyError(f"unknown rig keys: {unknown}")
        unread = sorted(set(values) & SPEC_ONLY_FIELDS)
        if unread:
            warnings.warn(f"rig keys not read by the model builders (spec only): {unread}", stacklevel=2)
        context = sorted(set(values) & MANNEQUIN_ONLY_FIELDS)
        if context:
            warnings.warn(f"rig keys read only by the mannequin (--context parts): {context}", stacklevel=2)
        return cls(**{k: _tuplify(v) for k, v in values.items()})

    @staticmethod
    def at(point, side: int) -> np.ndarray:
        """A her-left point ``(x, y, z)`` (or ``(x, z)``) mirrored to ``side`` (x multiplied by ``side``)."""
        p = np.array(point, dtype=np.float64)
        p[0] *= side
        return p

    # -----------------------------------------------------------------------------------------------------
    # landmarks (from the table)
    def landmark(self, name: str):
        """``(z, hw, yf, yb)`` of a landmark row (SPEC.md §A)."""
        for row in self.landmarks:
            if row[0] == name:
                return row[1:]
        raise KeyError(f"unknown landmark {name!r}; one of {[r[0] for r in self.landmarks]}")

    height = property(lambda self: self.landmark("skull top")[0],
                      doc="sole to skull top standing in her shoes (1.590 at the sheet scale; Decision 1)")
    skin_height = property(lambda self: self.height - self.heel_lift, doc="barefoot height at the sheet scale (1.555)")
    figure_scale = property(lambda self: self.stated_height / self.skin_height,
                            doc="uniform scale of the assembled model: stated_height / skin_height (0.97749)")
    figure_top_z = property(lambda self: self.landmark("ear-tuft tip")[0], doc="highest point (the tuft tips)")
    hair_top_z = property(lambda self: self.landmark("hair crown")[0])
    chin_z = property(lambda self: self.landmark("chin")[0])
    head_height = property(lambda self: self.height - self.chin_z, doc="chin to skull top (0.202)")
    head_unit = property(lambda self: self.hair_top_z - self.chin_z, doc="chin to hair crown (0.218)")
    heads_tall = property(lambda self: self.hair_top_z / self.head_unit,
                          doc="hair crown height / (crown - chin): 7.37 (SPEC.md §A)")
    brow_z = property(lambda self: self.landmark("brow")[0])
    bangs_tip_z = property(lambda self: self.landmark("bang line")[0])
    eye_z = property(lambda self: self.landmark("eye centre")[0])
    nose_z = property(lambda self: self.landmark("nose tip")[0])
    mouth_z = property(lambda self: self.landmark("mouth")[0])
    neck_z_mid = property(lambda self: self.landmark("neck")[0])
    mock_neck_z = property(lambda self: self.landmark("mock-neck rim")[0])
    neck_base_z = property(lambda self: self.landmark("neck base")[0])
    shoulder_z = property(lambda self: self.landmark("shoulder")[0])
    neckline_top_z = property(lambda self: self.landmark("neckline")[0])
    bust_z = property(lambda self: self.landmark("bust")[0])
    seam_z = property(lambda self: self.landmark("high-waist seam")[0], doc="high-waist seam (1.108)")
    waist_z = property(lambda self: self.landmark("natural waist")[0], doc="natural waist (1.000; framing)")
    hip_z = property(lambda self: self.landmark("hip")[0])
    crotch_z = property(lambda self: self.landmark("crotch")[0])
    hem_z = property(lambda self: self.landmark("skirt hem")[0], doc="skirt hem at the flute crests (0.390)")
    calf_z = property(lambda self: self.landmark("calf")[0])
    sock_top_z = property(lambda self: self.sock_cuff_z[1])
    sock_cuff_bottom_z = property(lambda self: self.sock_cuff_z[0])
    ankle_z = property(lambda self: self.landmark("ankle")[0])
    heel_top_z = property(lambda self: self.landmark("heel top")[0])

    # -----------------------------------------------------------------------------------------------------
    # final heights (the assembled model, scaled by figure_scale; docs and tests quote these)
    def final(self, length: float) -> float:
        """A sheet-scale length or height at the final scale (times :attr:`figure_scale`)."""
        return length * self.figure_scale

    final_skin_height = property(lambda self: self.final(self.skin_height),
                                 doc="barefoot, sole to skull top: stated_height (1.520)")
    final_height = property(lambda self: self.final(self.height), doc="skull top standing in her loafers (1.5542)")
    final_hair_top_z = property(lambda self: self.final(self.hair_top_z), doc="hair crown (1.5698)")
    final_figure_top_z = property(lambda self: self.final(self.figure_top_z), doc="ear-tuft tips (1.5777)")
    final_eye_z = property(lambda self: self.final(self.eye_z), doc="eye centres (1.4262)")
    final_chin_z = property(lambda self: self.final(self.chin_z), doc="chin (1.3568)")
    final_head_height = property(lambda self: self.final(self.head_height), doc="chin to skull top (0.1975)")
    final_seam_z = property(lambda self: self.final(self.seam_z), doc="high-waist seam (1.0831)")
    final_hem_z = property(lambda self: self.final(self.hem_z), doc="skirt hem at the flute crests (0.3812)")
    final_heel_lift = property(lambda self: self.final(self.heel_lift), doc="heel lift in the loafers (0.0342)")

    # -----------------------------------------------------------------------------------------------------
    # sections (shared model of every horizontal cross-section)
    @staticmethod
    def section_point(hw: float, yf: float, yb: float, t: float, exponent=2.0, back_exponent=None, c=None,
                      x0: float = 0.0):
        """``(x, y)`` of a section at the ring angle ``t`` (radians, counter-clockwise seen from above, 0 = +X,
        pi/2 = +Y (back), 3 pi/2 = -Y (front)): front half superellipse with semi-axes ``(hw, c - yf)``, back
        half ``(hw, yb - c)``; ``c`` defaults to the midpoint ``(yf + yb) / 2``."""
        cc = 0.5 * (yf + yb) if c is None else c
        ct, st = math.cos(t), math.sin(t)
        back = st > 0.0
        e = (exponent if back_exponent is None else back_exponent) if back else exponent
        x = x0 + hw * math.copysign(abs(ct) ** (2.0 / e), ct)
        y = cc + (yb - cc if back else cc - yf) * math.copysign(abs(st) ** (2.0 / e), st)
        return x, y

    @classmethod
    def section_ring(cls, section, n: int, z: float, exponent=2.0, back_exponent=None, c=None) -> np.ndarray:
        """Horizontal ring ``(n, 3)`` of ``section = (hw, yf, yb)`` at height ``z``, counter-clockwise from +Z,
        first point on +X (as ``mannequin.section_ring`` of the Miki generator)."""
        hw, yf, yb = section
        out = np.zeros((n, 3))
        for i in range(n):
            x, y = cls.section_point(hw, yf, yb, 2.0 * math.pi * i / n, exponent, back_exponent, c)
            out[i] = (x, y, z)
        return out

    @staticmethod
    def section_half_width_at(hw: float, yf: float, yb: float, y: float, exponent=2.0, back_exponent=None,
                              c=None) -> float:
        """Half-width ``x`` of a section at depth ``y`` (0 outside it)."""
        cc = 0.5 * (yf + yb) if c is None else c
        back = y > cc
        semi = (yb - cc) if back else (cc - yf)
        e = (exponent if back_exponent is None else back_exponent) if back else exponent
        if semi <= 0.0:
            return 0.0
        v = abs(y - cc) / semi
        if v >= 1.0:
            return 0.0
        return hw * (1.0 - v ** e) ** (1.0 / e)

    @staticmethod
    def azimuth_point(phi_deg: float, r: float, c: float = 0.0):
        """``(x, y)`` at azimuth ``phi`` (0 front -Y, 90 her left +X, 180 back) and radius ``r`` round ``(0, c)``."""
        p = math.radians(phi_deg)
        return r * math.sin(p), c - r * math.cos(p)

    # -----------------------------------------------------------------------------------------------------
    # head
    @property
    def head_center(self) -> np.ndarray:
        """Centre of the skull (camera framing, "away from the head" directions)."""
        return np.array(self.cranium_center, dtype=np.float64)

    @property
    def head_radii(self) -> np.ndarray:
        return np.array(self.cranium_radii, dtype=np.float64)

    def face_offset(self, z: float) -> float:
        """Widest-point offset ``c`` of the head section at ``z`` (§B.1)."""
        (z1, c1), (z0, c0) = self.face_center_offset
        t = min(1.0, max(0.0, (z - z0) / (z1 - z0)))
        return c0 + t * (c1 - c0)

    def head_section(self, z: float):
        """``(hw, yf, yb, c)`` of the skin head at ``z`` (linear in the profile table; ``yb`` is None below
        the last back row, where the back is the nape / neck)."""
        rows = self.head_profile
        hw = _interp_rows(rows, z, 1)
        yf = _interp_rows(rows, z, 2)
        backs = [r for r in rows if r[3] is not None]
        yb = _interp_rows(backs, z, 3) if z >= backs[-1][0] else None
        return hw, yf, yb, self.face_offset(z)

    def head_surface_y(self, x: float, z: float, front: bool = True) -> float:
        """y of the skin head at ``(x, z)`` from the §B.1 section model (without the nose bump): front half
        ``|x/hw|^e + |(y-c)/(c-yf)|^e = 1`` (e = face_front_exponent), back half the ellipse with semi-axes
        ``(hw, yb - c)``.  For ``|x| >= hw`` the section's side point ``y = c`` is returned."""
        hw, yf, yb, c = self.head_section(z)
        if hw <= 0:
            return yf if front else (c if yb is None else yb)
        u = min(1.0, abs(x) / hw)
        if front:
            e = self.face_front_exponent
            return c - (c - yf) * (1.0 - u ** e) ** (1.0 / e)
        if yb is None:
            raise ValueError(f"no back surface of the head at z {z} (the neck)")
        return c + (yb - c) * math.sqrt(max(0.0, 1.0 - u * u))

    def nose_bump(self, x: float, z: float) -> float:
        """Forward (-y) offset of the nose bump at ``(x, z)``: ``nose_proud`` at the tip, a cosine falloff to 0 at
        ``nose_half_width`` across, at the bridge and at the base (§B.4)."""
        w = self.nose_half_width
        if abs(x) >= w or z >= self.nose_bridge_z or z <= self.nose_base_z:
            return 0.0
        zt = self.nose_tip[2]
        if z >= zt:
            v = (z - zt) / (self.nose_bridge_z - zt)
        else:
            v = (zt - z) / (zt - self.nose_base_z)
        return self.nose_proud * 0.25 * (1.0 + math.cos(math.pi * abs(x) / w)) * (1.0 + math.cos(math.pi * v))

    def face_y(self, x: float, z: float) -> float:
        """Front skin y including the nose bump."""
        return self.head_surface_y(x, z) - self.nose_bump(x, z)

    def head_surface_point(self, x: float, z: float, front: bool = True) -> np.ndarray:
        """Point of the skin head at ``(x, z)`` on the front (``-Y``, without the nose) or back side."""
        return np.array([x, self.head_surface_y(x, z, front), z])

    def head_normal(self, x: float, z: float, d: float = 1e-4) -> np.ndarray:
        """Outward unit normal of the front face surface at ``(x, z)`` (finite differences)."""
        px = self.head_surface_point(x + d, z) - self.head_surface_point(x - d, z)
        pz = self.head_surface_point(x, z + d) - self.head_surface_point(x, z - d)
        n = _unit(np.cross(pz, px))
        return -n if n[1] > 0 else n

    def eye_center(self, side: int) -> np.ndarray:
        """Eye centre on the face surface ``(+-0.0395, -0.098, 1.459)``."""
        return self.head_surface_point(side * self.eye_x, self.eye_z)

    def neck_section(self, z: float):
        """``(hw, yf, yb)`` of the neck (an elliptic cylinder, §D.1)."""
        return self.neck_half_width, self.neck_y[0], self.neck_y[1]

    # -----------------------------------------------------------------------------------------------------
    # hair
    def hair_section(self, z: float):
        """``(hw, yf, yb)`` of the hair mass's outer silhouette (§C, the sheet's), zero width above the crown."""
        if z >= self.hair_rows[0][0]:
            return 0.0, self.hair_rows[0][2], self.hair_rows[0][3]
        return tuple(_interp_rows(self.hair_rows, z, k) for k in (1, 2, 3))

    def hair_surface_y(self, x: float, z: float, front: bool = True) -> float:
        """y of the hair silhouette surface at ``(x, z)`` (front or back half of :meth:`hair_section`)."""
        hw, yf, yb = self.hair_section(z)
        c = 0.5 * (yf + yb)
        if hw <= 0:
            return c
        ef, eb = self.hair_exponent
        u = min(1.0, abs(x) / hw)
        if front:
            return c - (c - yf) * (1.0 - u ** ef) ** (1.0 / ef)
        return c + (yb - c) * (1.0 - u ** eb) ** (1.0 / eb)

    def dome_section(self, z: float):
        """``(hw, yf, yb)`` of the top-hair dome H1 at ``z``: the hair silhouette (alias kept for the toolkit)."""
        return self.hair_section(z)

    def bob_row(self, z: float):
        """``(hw, yb, front_x, front_y, t)`` of the bob at ``z`` (linear in :attr:`bob_rows`, clamped)."""
        return tuple(_interp_rows(self.bob_rows, z, k) for k in range(1, 6))

    def bob_hem(self, phi_deg: float) -> float:
        """z of the bob's lower edge (tip line) at azimuth ``|phi|`` (symmetric)."""
        return _interp_pairs(self.bob_hem_z, abs(phi_deg))

    def tuft_frame(self, side: int):
        """``(base, tip, cup_normal)`` of an ear tuft: base centre, tip and the unit normal of its concave face
        (horizontal, ``tuft_cup_azimuth_deg`` outward from -Y)."""
        base = self.at(self.tuft_base_center, side)
        tip = self.at(self.tuft_tip, side)
        a = math.radians(self.tuft_cup_azimuth_deg)
        return base, tip, np.array([side * math.sin(a), -math.cos(a), 0.0])

    def braid_point(self, side: int, u: float) -> np.ndarray:
        """Point of the braid centreline polyline at parameter ``u`` (0 root .. 1 tie), by arc length."""
        pts = [self.at(p, side) for p in self.braid_path]
        seg = [_norm(b - a) for a, b in zip(pts, pts[1:])]
        s = min(max(u, 0.0), 1.0) * sum(seg)
        for i, L in enumerate(seg):
            if s <= L or i == len(seg) - 1:
                return pts[i] + (pts[i + 1] - pts[i]) * (min(s, L) / L)
            s -= L
        return pts[-1]

    # -----------------------------------------------------------------------------------------------------
    # torso and clothes
    def body_section(self, z: float):
        """``(hw, yf, yb)`` of the hidden body under the skirt (§A.1)."""
        return tuple(_interp_rows(self.body_rows, z, k) for k in (1, 2, 3))

    def top_section(self, z: float):
        """``(hw, yf, yb)`` of the white top's torso (§D.2)."""
        return tuple(_interp_rows(self.top_rows, z, k) for k in (1, 2, 3))

    def mock_neck_section(self, z: float):
        return tuple(_interp_rows(self.mock_neck_rows, z, k) for k in (1, 2, 3))

    def bodice_section(self, z: float):
        """``(hw, yf, yb)`` of the dress bodice's outer surface (§D.3)."""
        return tuple(_interp_rows(self.bodice_rows, z, k) for k in (1, 2, 3))

    def skirt_section(self, z: float):
        """``(hw, yf, yb)`` of the skirt's outer surface at the flute crests (§D.4)."""
        return tuple(_interp_rows(self.skirt_rows, z, k) for k in (1, 2, 3))

    def flute_depth_at(self, z: float) -> float:
        """Crest-to-valley depth of the flutes at ``z`` (0 above ``flute_top_z``, ``flute_depth`` at the hem)."""
        t = (self.flute_top_z - z) / (self.flute_top_z - self.hem_z)
        return self.flute_depth * min(1.0, max(0.0, t))

    def flute_offset(self, z: float, phi_deg: float) -> float:
        """Radial offset of the skirt surface (0 at a crest, ``-flute_depth_at(z)`` at a valley); a crest at the
        centre front (``phi`` 0)."""
        w = 0.5 * (1.0 - math.cos(math.radians(self.skirt_flutes * phi_deg)))
        return -self.flute_depth_at(z) * w

    def skirt_hem_at(self, phi_deg: float) -> float:
        """z of the hem at azimuth ``phi`` (higher by ``hem_wave`` at the valleys)."""
        w = 0.5 * (1.0 - math.cos(math.radians(self.skirt_flutes * phi_deg)))
        return self.hem_z + self.hem_wave * w

    def skirt_point(self, z: float, phi_deg: float, flutes: bool = True) -> np.ndarray:
        """Outer skirt surface point at height ``z`` and azimuth ``phi``: the crest section's point along the ray
        from the section centre at that azimuth (polar, not the superellipse parameter), moved radially by
        :meth:`flute_offset` when ``flutes``."""
        hw, yf, yb = self.skirt_section(z)
        c = 0.5 * (yf + yb)
        e = self.skirt_exponent
        p = math.radians(phi_deg)
        sx, cy = math.sin(p), -math.cos(p)            # direction from the centre
        semi = (yb - c) if cy > 0 else (c - yf)       # front or back half
        if abs(sx) < 1e-15:
            r = semi
        else:
            r = 1.0 / ((abs(sx) / hw) ** e + (abs(cy) / semi) ** e) ** (1.0 / e)
        if flutes:
            r += self.flute_offset(z, phi_deg)
        return np.array([r * sx, c + r * cy, z])

    def skirt_ring(self, z: float, n: int, flutes: bool = True) -> np.ndarray:
        """Ring ``(n, 3)`` of the skirt's outer surface at ``z`` at ``n`` equal azimuth steps (counter-clockwise
        from +Z, first point on +X like :meth:`section_ring`, but spaced by polar angle), with the flutes when
        ``flutes``; ``n`` a multiple of ``2 * skirt_flutes`` puts a vertex on every crest and valley."""
        out = np.zeros((n, 3))
        for i in range(n):
            out[i] = self.skirt_point(z, 360.0 * i / n + 90.0, flutes)   # ring angle 0 (+X) = azimuth 90
        return out

    #: Section kind -> (section method, front exponent, back exponent) for :meth:`ring`.
    _RING_KINDS = {
        "body": ("body_section", "body_exponent", "body_exponent"),
        "top": ("top_section", "body_exponent", "body_exponent"),
        "mock_neck": ("mock_neck_section", "mock_neck_exponent", "mock_neck_exponent"),
        "neck": ("neck_section", None, None),
        "bodice": ("bodice_section", "bodice_front_exponent", "bodice_back_exponent"),
        "skirt": ("skirt_section", "skirt_exponent", "skirt_exponent"),
        "cardigan": ("cardigan_section", "body_exponent", "body_exponent"),
        "cardigan_outer": ("cardigan_outer_section", "body_exponent", "body_exponent"),
    }

    def ring(self, kind: str, z: float, n: int) -> np.ndarray:
        """Ring ``(n, 3)`` of a named section model at ``z`` with its exponents (``kind``: ``body``, ``top``,
        ``mock_neck``, ``neck`` (ellipse), ``bodice``, ``skirt`` (crests, no flutes: :meth:`skirt_ring`),
        ``cardigan``, ``cardigan_outer``, ``hair`` (the hair silhouette))."""
        if kind == "hair":
            ef, eb = self.hair_exponent
            return self.section_ring(self.hair_section(z), n, z, ef, eb)
        meth, ef, eb = self._RING_KINDS[kind]
        sec = getattr(self, meth)(z)
        e_f = 2.0 if ef is None else getattr(self, ef)
        e_b = 2.0 if eb is None else getattr(self, eb)
        return self.section_ring(sec, n, z, e_f, e_b)

    def button_positions(self) -> tuple:
        """z of the dress buttons, top to bottom: the bodice's (:attr:`button_bodice_z`), then the skirt's evenly
        spaced (Decision 11)."""
        z0, z1 = self.button_skirt_z
        n = self.button_skirt_count
        return tuple(self.button_bodice_z) + tuple(z0 + (z1 - z0) * i / (n - 1) for i in range(n))

    def dress_front_y(self, z: float) -> float:
        """y of the dress's centre-front surface at ``z`` (bodice above the seam, skirt crest below)."""
        if z >= self.seam_z:
            return self.bodice_section(z)[1]
        return self.skirt_section(z)[1]

    def cardigan_section(self, z: float):
        """``(hw, yf, yb)`` of the cardigan body panels' inner reference surface (§D.6)."""
        return tuple(_interp_rows(self.cardigan_rows, z, k) for k in (1, 2, 3))

    def cardigan_outer_section(self, z: float):
        """The panels' outer surface: :meth:`cardigan_section` grown by ``cardigan_thickness``."""
        hw, yf, yb = self.cardigan_section(z)
        t = self.cardigan_thickness
        return hw + t, yf - t, yb + t

    def cardigan_surface_y(self, x: float, z: float, front: bool = True) -> float:
        """y of the cardigan's inner reference surface at ``(x, z)`` (front or back half of
        :meth:`cardigan_section`, exponent ``body_exponent``); the panels grow ``cardigan_thickness`` outward."""
        hw, yf, yb = self.cardigan_section(z)
        c = 0.5 * (yf + yb)
        e = self.body_exponent
        f = (1.0 - min(1.0, abs(x) / hw) ** e) ** (1.0 / e)
        return c - (c - yf) * f if front else c + (yb - c) * f

    def cardigan_hem_z(self, x: float, front: bool = True) -> float:
        """z of the cardigan's lower edge at ``x`` on the front (rounded front corners) or the back (level)."""
        if not front:
            return self.cardigan_back_hem_z
        return _interp_pairs(self.cardigan_front_hem, abs(x))

    # -----------------------------------------------------------------------------------------------------
    # legs
    def leg_radius(self, z: float) -> float:
        return _interp_rows(self.leg_radii, z, 1)

    def hip_joint(self, side: int) -> np.ndarray:
        return self.at(self.hip_joint_pos, side)

    def knee(self, side: int) -> np.ndarray:
        return self.at(self.knee_pos, side)

    def ankle(self, side: int) -> np.ndarray:
        return self.at(self.ankle_pos, side)

    def leg_point(self, side: int, z: float) -> np.ndarray:
        """Point of the leg axis (hip -> knee -> ankle polyline) at height ``z``."""
        h, k, a = self.hip_joint(side), self.knee(side), self.ankle(side)
        if z >= k[2]:
            t = (h[2] - z) / (h[2] - k[2])
            return h + t * (k - h)
        t = (k[2] - z) / (k[2] - a[2])
        return k + t * (a - k)

    def sock_radius(self, z: float) -> float:
        """Outer radius of the sock at ``z`` (the cuff above ``sock_cuff_z[0]``)."""
        if self.sock_cuff_z[0] <= z <= self.sock_cuff_z[1]:
            return self.leg_radius(z) + self.sock_cuff_ease
        return self.leg_radius(z) + self.sock_ease

    def foot_dir(self, side: int) -> np.ndarray:
        """Horizontal unit vector heel -> toe (``-Y`` turned out by ``shoe_toe_out_deg``)."""
        t = math.radians(self.shoe_toe_out_deg)
        return np.array([side * math.sin(t), -math.cos(t), 0.0])

    def heel_point(self, side: int) -> np.ndarray:
        """Back of the shoe sole on the ground: ``(+-0.055, 0.035, 0)``."""
        x, y = self.shoe_heel_back
        return np.array([side * x, y, 0.0])

    def toe_point(self, side: int) -> np.ndarray:
        """Front of the shoe sole on the ground (heel point + shoe_length along :meth:`foot_dir`)."""
        return self.heel_point(side) + self.shoe_length * self.foot_dir(side)

    # -----------------------------------------------------------------------------------------------------
    # arms and hands
    def shoulder_joint(self, side: int) -> np.ndarray:
        return self.at(self.shoulder_joint_pos, side)

    def elbow(self, side: int) -> np.ndarray:
        return self.at(self.elbow_pos, side)

    def wrist(self, side: int) -> np.ndarray:
        return self.at(self.wrist_pos, side)

    def fingertip(self, side: int, name: str = "middle") -> np.ndarray:
        """Tip of a finger (straight, before its curl): its base plus its length along its fanned direction."""
        base, d, _ = self.finger_base(side, name)
        return base + self.finger(name)[3] * d

    def upper_arm_dir(self, side: int) -> np.ndarray:
        return _unit(self.elbow(side) - self.shoulder_joint(side))

    def forearm_dir(self, side: int) -> np.ndarray:
        return _unit(self.wrist(side) - self.elbow(side))

    def hand_dir(self, side: int) -> np.ndarray:
        """Unit vector of the palm axis: wrist -> :attr:`fingertip_pos`."""
        return _unit(self.at(self.fingertip_pos, side) - self.wrist(side))

    @property
    def upper_arm_length(self) -> float:
        return _norm(np.subtract(self.elbow_pos, self.shoulder_joint_pos))

    @property
    def forearm_length(self) -> float:
        return _norm(np.subtract(self.wrist_pos, self.elbow_pos))

    @property
    def hand_length(self) -> float:
        """Length of the palm axis (wrist -> :attr:`fingertip_pos`)."""
        return _norm(np.subtract(self.fingertip_pos, self.wrist_pos))

    def arm_point(self, side: int, position: float) -> np.ndarray:
        """Point of the arm axis at ``position``: 0 shoulder joint, 1 elbow, 2 wrist (linear between), beyond 2
        along the forearm direction by ``(position - 2) * forearm_length`` (the cuff)."""
        s, e, w = self.shoulder_joint(side), self.elbow(side), self.wrist(side)
        if position <= 1.0:
            return s + (e - s) * max(position, 0.0)
        if position <= 2.0:
            return e + (w - e) * (position - 1.0)
        return w + self.forearm_dir(side) * ((position - 2.0) * self.forearm_length)

    def sleeve_radius(self, position: float) -> float:
        """Balloon sleeve radius at ``position`` (0 shoulder joint, 1 elbow, 2 wrist; see :attr:`sleeve_radii`)."""
        return _interp_pairs(self.sleeve_radii, position)

    def sleeve_center(self, side: int, position: float) -> np.ndarray:
        """Centre of the balloon sleeve's section at ``position``: the arm axis moved by ``balloon_offset``
        (outward, backward), fading in from the shoulder (0 at position 0, full from 1 to 1.9) and back to the arm
        axis at the gather (position 2)."""
        if position <= 1.0:
            f = max(position, 0.0)
        elif position <= 1.9:
            f = 1.0
        else:
            f = max(0.0, (2.0 - position) / 0.1)
        ox, oy = self.balloon_offset
        return self.arm_point(side, position) + f * np.array([side * ox, oy, 0.0])

    def sleeve_radii_at(self, position: float):
        """``(lateral, depth)`` radii of the balloon sleeve's section at ``position`` (the depth along +-Y)."""
        rr = self.sleeve_radius(position)
        return rr, rr * _interp_pairs(self.sleeve_depth_ratio, position)

    def cuff_start(self, side: int) -> np.ndarray:
        """Centre of the cuff's top (the gather, where the balloon ends): ``cuff_gather_offset`` above the wrist
        along the forearm."""
        return self.wrist(side) - self.cuff_gather_offset * self.forearm_dir(side)

    def cuff_end(self, side: int) -> np.ndarray:
        """Centre of the cuff's mouth: ``cuff_length`` beyond the gather along the forearm (just short of the
        knuckles)."""
        return self.cuff_start(side) + self.cuff_length * self.forearm_dir(side)

    def cuff_radius_at(self, s: float) -> float:
        """Outer radius of the ribbed cuff at the distance ``s`` along the forearm from the gather: the cone's
        linear flare from :attr:`cuff_radius` to :attr:`cuff_end_radius` (clamped at both ends)."""
        u = min(1.0, max(0.0, s / self.cuff_length))
        return self.cuff_radius + u * (self.cuff_end_radius - self.cuff_radius)

    def palm_normal(self, side: int) -> np.ndarray:
        """Unit normal of the palm (facing forward, -Y, turned ``palm_turn_deg`` towards the body)."""
        d = self.hand_dir(1)
        n = np.array([0.0, -1.0, 0.0])
        n = _unit(n - d * float(n[0] * d[0] + n[1] * d[1] + n[2] * d[2]))
        n = _rotate(n, d, self.palm_turn_deg)       # about the hand axis: turns -Y towards -X for her left hand
        n[0] *= side
        return n

    def hand_frame(self, side: int):
        """``(wrist, hand_dir, palm_normal, thumb_dir)``: the hand's axis, the palm normal and the unit vector
        across the palm towards the thumb (outward)."""
        d = self.hand_dir(side)
        n = self.palm_normal(side)
        a = _unit(np.cross(d, n))
        if a[0] * side < 0:                          # the thumb is on the outer side (palm forward)
            a = -a
        return self.wrist(side), d, n, a

    def knuckles(self, side: int) -> np.ndarray:
        """Centre of the knuckle line: ``palm_length`` from the wrist along the hand axis."""
        w, d, _, _ = self.hand_frame(side)
        return w + self.palm_length * d

    def finger(self, name: str):
        """The :attr:`fingers` row of a finger."""
        for row in self.fingers:
            if row[0] == name:
                return row
        raise KeyError(f"unknown finger {name!r}")

    def finger_base(self, side: int, name: str):
        """``(base, direction, palm_normal)`` of a finger: its base on the palm and its (straight) direction,
        fanned in the palm plane by its ``fan_deg`` (positive outward)."""
        w, d, n, a = self.hand_frame(side)
        _, across, along, length, thick, fan, curl = self.finger(name)
        base = w + d * (along * self.palm_length) + a * across
        # rotate the hand axis towards the thumb side by fan_deg about the palm normal
        dirn = _unit(d * math.cos(math.radians(fan)) + a * math.sin(math.radians(fan)))
        return base, dirn, n


#: Rig fields that no builder of the detailed model reads (neither directly nor through a rig method): SPEC.md values
#: kept for reference (the pose angles document the joint positions; the hidden guides ``body_rows`` /
#: ``cranium_radii``; shapes that the builders take from module constants, such as the bob's tips, the braid lobes,
#: the tuft's light face and outer bulge; features the model leaves out, such as the armhole, the band ribs and the
#: shirring lift; since the finishing pass the bob's old tip depths, which its lock table replaced, the balloon's
#: old lip drop, the cuff's old turned-in opening and the white sleeve tube's start: ``body.TOP_SLEEVE_TUBES`` is off,
#: the balloon sleeves always cover the tubes).  A ``--rig`` override of one of them changes nothing;
#: :meth:`Rig.from_dict` warns about it.  (``stated_height`` and ``heel_lift`` are not in it: no builder reads them,
#: but they set :attr:`Rig.figure_scale`, the scale of the whole model, of the scene camera and of the preview
#: framing.)
SPEC_ONLY_FIELDS = frozenset((
    "arm_abduction_deg", "armhole_center", "armhole_radii", "armhole_tilt_deg", "balloon_drop", "band_ribs",
    "bob_tip_depth", "bob_tip_depth_back", "bob_tips", "bodice_lift", "body_rows", "braid_lobes", "bust_apex_x",
    "cranium_radii", "cuff_opening_radius", "decal_layer_clearance", "face_surface_points", "forearm_out_deg",
    "hair_thickness", "hand_out_deg", "head_depth_y", "seam_relief", "shoe_vamp_z", "top_sleeve_start",
    "tuft_inner_inset", "tuft_outer_bulge",
))
#: Rig fields read only by :mod:`mannequin` (the grey ``--context`` placeholder parts, through :meth:`Rig.tuft_frame`,
#: :meth:`Rig.bob_hem`, :meth:`Rig.sleeve_center` and :meth:`Rig.sleeve_radii_at`), not by the detailed model
#: (``hair.py`` builds the tufts from ``tuft_front_outline`` / ``tuft_side_outline``, the braid lobes from its own
#: ``BRAID_LOBE_HALF_WIDTH``, not ``braid_width``, and the bob's lower edge from ``bob_lock_columns``, not
#: ``bob_hem_z``; ``cardigan.py`` builds the balloon from ``sleeve_rings``, not ``sleeve_radii`` /
#: ``sleeve_depth_ratio`` / ``balloon_offset``; the mannequin's top keeps its white sleeve tubes, the model's are off,
#: ``body.TOP_SLEEVE_TUBES``); :meth:`Rig.from_dict` warns about them too.
MANNEQUIN_ONLY_FIELDS = frozenset((
    "balloon_offset", "bob_hem_z", "braid_width", "sleeve_depth_ratio", "sleeve_radii", "top_sleeve_end",
    "top_sleeve_radii", "tuft_base_center", "tuft_base_size", "tuft_cup_azimuth_deg",
))


DEFAULT_RIG = Rig()
