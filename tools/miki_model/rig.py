"""Proportions, landmarks and pose of the Miki model: the single source of every number.

The values are the numeric character spec (``miki_spec.md``, sections A-E; the section of each field is in
its comment).  Builders read every dimension from a :class:`Rig` and add a new named field (with a comment
and the spec section) instead of a literal.  Units are metres and degrees.  The frame is castplane's world:
Z up, soles on ``z = 0``, the figure stands at the origin facing ``-Y`` and her left is ``+X``.  A ``side``
argument is ``+1`` for her left (``+X``) and ``-1`` for her right.

Conventions of the fields:

* a point is ``(x, y, z)`` for her **left** side (``x >= 0``); :meth:`Rig.at` mirrors it for a side;
* a 2D face point is ``(x, z)`` on the face, its ``y`` comes from :meth:`Rig.head_surface_y`;
* the spec's tables are tuples of rows (each documented next to the field); rows run top to bottom;
* ``hw`` is a half-width in x, ``yf`` / ``yb`` are the front (most negative y) / back extents at the midline.

:meth:`Rig.replace` / :meth:`Rig.from_dict` change fields (unknown keys raise; JSON lists become tuples).
The derived landmarks (``height``, ``chin_z``, ``eye_z`` ...) are properties of the tables, so a table
override moves them too.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

import numpy as np

__all__ = ["Rig", "DEFAULT_RIG"]


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


@dataclass(frozen=True)
class Rig:
    """Named dimensions (metres, degrees) and derived landmarks of the figure (spec ``miki_spec.md``)."""

    # =====================================================================================================
    # A. Overall proportions and landmarks
    # =====================================================================================================
    #: Landmark table (spec §A): ``(name, z, hw, yf, yb)``; the body column is the body surface, or the
    #: clothing surface where she is clothed (see the spec for the surface of each row).  ``height``,
    #: ``chin_z``, ``eye_z``, ``waist_z`` ... are read from here.
    landmarks: tuple = (
        ("hair top", 1.528, 0.0, 0.010, 0.010),            # hair crown (hair 18 mm thick)
        ("skull top", 1.510, 0.0, 0.012, 0.012),           # skin under the hair (official height 151 cm)
        ("headband front", 1.465, 0.094, -0.092, 0.132),   # band centreline on the midline; hw / yb of the hair
        ("bang cut", 1.432, 0.072, -0.0975, 0.137),        # flat cut; hw of the bangs (hair mass 0.098)
        ("brow line", 1.374, 0.081, -0.089, 0.113),        # skin; brows 1.366 inner ... 1.381 outer
        ("eye centre", 1.342, 0.076, -0.085, 0.107),       # skin; eye centres at x = +-0.040
        ("nose tip", 1.312, 0.071, -0.093, 0.093),
        ("mouth", 1.286, 0.058, -0.083, 0.074),
        ("chin", 1.255, 0.012, -0.064, -0.022),            # chin pad; yb = neck front (jaw underside rises to it)
        ("neck base", 1.195, 0.031, -0.022, 0.046),        # neck; collar inner edge at 1.205-1.212
        ("shoulder line", 1.180, 0.160, -0.055, 0.079),    # sleeve cap / collar flap; acromion x 0.150
        ("armpit", 1.065, 0.130, -0.104, 0.089),           # the sleeve leaves the torso side here
        ("bust", 1.040, 0.132, -0.110, 0.089),             # blouse; apex at x +-0.050
        ("waist", 0.940, 0.122, -0.098, 0.076),            # blouse (body under it: body_waist)
        ("blouse hem", 0.900, 0.130, -0.100, 0.080),       # loose hem, slight flare
        ("hip widest", 0.780, 0.165, -0.102, 0.112),       # skirt (body: body_hip); pleats open below here
        ("crotch", 0.690, 0.180, -0.120, 0.130),           # skirt
        ("skirt hem", 0.450, 0.215, -0.158, 0.168),        # pleat crests
        ("knee", 0.420, 0.123, -0.048, 0.048),             # legs: centre x 0.077, r 0.046
        ("sock top", 0.385, 0.1245, -0.049, 0.049),        # sock = leg + 1.5 mm
        ("ankle", 0.065, 0.106, -0.019, 0.039),            # ankle centre (0.077, 0.010), r 0.029
        ("sole", 0.0, 0.130, -0.175, 0.050),               # shoe outer / toe / heel; feet turned out 8 deg
    )
    head_depth_y: tuple = (-0.091, 0.115)    # §A head depth (skin) at z 1.40: forehead y, back of skull y
    hair_half_width_temples: float = 0.100   # §A hair mass hw at the temples
    #: Superellipse exponent of the torso / blouse / hip cross-sections (§A): the front half has semi-axes
    #: ``(hw, -yf)``, the back half ``(hw, yb)``, widest at ``y = 0``.
    torso_exponent: float = 2.5
    #: Blouse (top) rows for the loft, top to bottom (§A landmark table + intermediate rows; §D.1):
    #: ``(z, hw, yf, yb)``; interpolate linearly in z.  1.180 uses the acromion hw 0.150 and the blouse back
    #: 0.075 (the landmark row's 0.160 / 0.079 are the sleeve cap and the collar flap); at the armpit and the
    #: bust the blouse back is 0.085 (the landmark rows' 0.089 include the 4 mm collar flap; the collar point
    #: O1 = 0.085 at z 1.030 and §C.6's "blouse back 0.086 at z 1.10" agree).  The blouse is loose: from the
    #: bust down it drapes straight.
    blouse_rows: tuple = (
        (1.215, 0.031, -0.026, 0.050),     # neck root
        (1.180, 0.150, -0.055, 0.075),     # shoulder line (acromion)
        (1.130, 0.150, -0.085, 0.086),
        (1.065, 0.130, -0.104, 0.085),     # armpit
        (1.040, 0.132, -0.110, 0.085),     # bust
        (0.990, 0.128, -0.106, 0.080),
        (0.940, 0.122, -0.098, 0.076),     # waist (blouse)
        (0.900, 0.130, -0.100, 0.080),     # hem
    )
    bust_apex_x: float = 0.050               # §A/§D.1 bust apex at x +-0.050 (y -0.110)
    body_waist: tuple = (0.940, 0.105, -0.065, 0.060)   # §A body under the blouse at the waist (z, hw, yf, yb)
    body_hip: tuple = (0.780, 0.150, -0.075, 0.090)     # §A body under the skirt at the hip (z, hw, yf, yb)

    # =====================================================================================================
    # B.1 Skin head, neck
    # =====================================================================================================
    cranium_center: tuple = (0.0, 0.012, 1.405)   # §B.1 cranium ellipsoid (guide above z 1.40)
    cranium_radii: tuple = (0.083, 0.103, 0.105)
    #: Skin head profile (§B.1): ``(z, hw, yf, yb)`` at the midline, top to bottom.  ``yb = None``: the back
    #: is the neck there (the jaw underside :attr:`jaw_underside` runs in front of it).
    head_profile: tuple = (
        (1.510, 0.000, 0.012, 0.012),      # top
        (1.500, 0.035, -0.032, 0.056),
        (1.480, 0.057, -0.057, 0.081),
        (1.460, 0.069, -0.073, 0.097),     # under the headband
        (1.440, 0.077, -0.083, 0.107),
        (1.420, 0.082, -0.089, 0.113),     # forehead
        (1.400, 0.083, -0.091, 0.115),     # widest skull, forehead front
        (1.380, 0.082, -0.090, 0.114),     # brow ridge (very soft)
        (1.360, 0.079, -0.087, 0.111),
        (1.342, 0.076, -0.085, 0.107),     # eyes; the bridge between them
        (1.325, 0.074, -0.088, 0.100),     # cheeks fullest (just below the eyes)
        (1.312, 0.071, -0.093, 0.093),     # nose tip (the bump is local, width +-0.006)
        (1.300, 0.066, -0.085, 0.085),     # under the nose
        (1.286, 0.058, -0.083, 0.074),     # mouth
        (1.272, 0.046, -0.078, 0.060),     # jaw narrows fast; back = nape into the neck
        (1.262, 0.030, -0.073, None),
        (1.257, 0.016, -0.068, None),      # small rounded chin
        (1.255, 0.000, -0.064, None),      # chin bottom
    )
    face_front_exponent: float = 3.0         # §B.1 front half of a head section: |x/hw|^3 + |(y-c)/(c-yf)|^3 = 1
    face_center_offset: float = 0.012        # §B.1 widest-point offset c: this for z >= 1.40, 0 for z <= 1.33,
    face_center_offset_z: tuple = (1.33, 1.40)   # linear in between
    jaw_underside: tuple = ((-0.064, 1.255), (-0.050, 1.258), (-0.038, 1.263), (-0.026, 1.272))  # §B.1 (y, z)
    nape: tuple = (0.050, 1.27)              # §B.1 (y, z): the back of the head curves into the nape below 1.30
    #: Face-surface y at the feature points (§B.1), ``(x, z, y)``: place features on the surface with these.
    face_surface_points: tuple = (
        (0.040, 1.342, -0.0805),           # eye centre
        (0.019, 1.342, -0.0845),           # eye inner corner
        (0.061, 1.342, -0.066),            # eye outer corner
        (0.020, 1.366, -0.0874),           # brow inner
        (0.058, 1.381, -0.0767),           # brow outer
        (0.0, 1.286, -0.083),              # mouth
        (0.0, 1.432, -0.0854), (0.04, 1.432, -0.081), (0.06, 1.432, -0.068), (0.07, 1.432, -0.054),  # bang cut
    )
    neck_half_width: float = 0.031          # §B.1 elliptic cylinder
    neck_y: tuple = (-0.022, 0.046)          # front / back y (centre 0.012)
    neck_z: tuple = (1.180, 1.285)           # from inside the torso to inside the head
    bib_bottom_z: float = 1.165              # §B.1 décolleté bib fills the collar V down to here (neck shell)
    bib_lift: float = 0.001                  # bib above the blouse surface
    ear_center: tuple = (0.078, 0.010, 1.335)   # §B.1 ears are NOT modelled; the hair must cover this zone
    ear_height: float = 0.040

    # =====================================================================================================
    # B.2 Eyes (object eyes; slabs conform to the face)
    # =====================================================================================================
    eye_x: float = 0.040                     # eye centre x (z = eye_z = 1.342, surface y -0.0805)
    eye_inner_x: float = 0.019               # inner corner (chord width 0.042, inner-corner gap 0.038)
    eye_outer_x: float = 0.061
    eye_full_z: tuple = (1.323, 1.363)       # full eye height 0.040 if the lid were up
    eye_lid_z: float = 1.351                 # visible opening: lower lid 1.323 up to this flat upper-lid line
    eye_lid_rise: float = 0.001              # the lid line rises this much from inner to outer end (~1.5 deg)
    iris_size: tuple = (0.026, 0.031)        # ellipse width x height
    iris_center_z: float = 1.3375            # its top 2.5 mm is hidden under the lid band
    pupil_size: tuple = (0.012, 0.016)
    pupil_center_z: float = 1.337
    highlight_diameter: float = 0.005
    highlight_dx: float = -0.008             # highlight x = eye centre x + this on BOTH eyes (towards -x)
    highlight_z: float = 1.3445
    #: Lower sclera boundary (x, z), inner corner -> outer corner; the upper boundary is the lid line.
    sclera_lower: tuple = ((0.019, 1.3435), (0.028, 1.327), (0.040, 1.323), (0.052, 1.326), (0.061, 1.3455))
    eye_slab_depth: float = 0.0003           # every eye / mark slab's back face sits this far below the skin
    sclera_relief: float = 0.0006            # front face above the skin, per layer
    iris_relief: float = 0.0010
    pupil_relief: float = 0.0013
    highlight_relief: float = 0.0016
    lid_band_relief: float = 0.0018          # face_marks; overlaps the top of sclera and iris
    lower_lid_relief: float = 0.0010         # face_marks
    lid_band_inner: tuple = (0.018, 1.3495)  # upper-lid band (x, z) ends; thick, flat, dark
    lid_band_outer: tuple = (0.062, 1.3515)
    lid_band_height: tuple = (0.002, 0.0035)  # z height at the inner end, in the middle
    lid_flick_length: float = 0.007          # downward lash flick at the outer end
    lid_flick_width: float = 0.002
    lid_flick_angle_deg: float = 60.0        # below horizontal, pointing down and outward
    lid_flick_tip: tuple = (0.064, 1.343)    # (x, z)
    lower_lid_width: float = 0.001           # lower-lid mark: band along the outer 60 % of the lower sclera edge
    lower_lid_offset: float = 0.0004         # outside the sclera edge
    lower_lid_x: tuple = (0.036, 0.058)

    # =====================================================================================================
    # B.3 Brows, B.4 nose and mouth (object face_marks; nose in the skin mesh)
    # =====================================================================================================
    brow_inner: tuple = (0.020, 1.366)       # (x, z); y -0.0874; 15 mm above the lid line
    brow_mid: tuple = (0.039, 1.375)         # 1.5 mm of upward arch
    brow_outer: tuple = (0.058, 1.381)       # y -0.0767; tilt about 22 deg rising outward
    brow_tilt_deg: float = 22.0
    brow_width: tuple = (0.0018, 0.0010)     # inner, outer end (tapering)
    brow_relief: float = 0.0008
    nose_tip: tuple = (0.0, -0.093, 1.312)   # 5 mm proud of the cheek plane; no nostrils, no mark
    nose_proud: float = 0.005
    nose_bridge_z: float = 1.330
    nose_half_width: float = 0.006           # the bump is local
    mouth_width: float = 0.014               # small omega cat mouth, centre (0, mouth_z), y mouth_y
    mouth_y: float = -0.083
    mouth_arc_sag: float = 0.0012            # two arcs, each mouth_width / 2 wide
    mouth_cusp_z: float = 1.2868
    mouth_corner_z: float = 1.2875
    mouth_band: float = 0.0012
    mouth_relief: float = 0.0008

    # =====================================================================================================
    # C. Hair (objects hair, sidelocks, back_hair; headband)
    # =====================================================================================================
    hair_thickness: tuple = (0.018, 0.017, 0.0165, 0.022)   # §C over the scalp: crown, front under the band,
    #                                                         sides above the ears, back of the skull
    dome_center: tuple = (0.0, 0.012, 1.405)    # §C/§C.5 H1: offset ellipsoid
    dome_radii: tuple = (0.0995, 0.1195, 0.123)  # x, y towards the front, z
    dome_back_radius: float = 0.125             # y towards the back
    dome_bottom_z: float = 1.43                 # closed by a flat cap buried inside the skull
    hairline_z: float = 1.440                   # §C hidden under the bangs, 8 mm above the cut
    # -- C.1 headband ------------------------------------------------------------------------------------
    band_tilt_deg: float = 12.0                 # plane through the front point, descending toward the back:
    band_plane_y0: float = -0.0905              #   z = headband_front_z - tan(tilt) * (y - band_plane_y0)
    #: Centreline on the hair surface + 1.5 mm, ``(x, y, z)`` from the midline to the buried end (mirror -x).
    band_centreline: tuple = (
        (0.000, -0.0918, 1.4652), (0.0155, -0.0905, 1.4650), (0.0331, -0.0850, 1.4638),
        (0.0503, -0.0750, 1.4617), (0.0618, -0.0650, 1.4596), (0.0705, -0.0550, 1.4575),
        (0.0773, -0.0450, 1.4553), (0.0827, -0.0350, 1.4532), (0.0869, -0.0250, 1.4511),
        (0.0901, -0.0150, 1.4490), (0.0915, -0.0050, 1.4469),
    )
    band_width: float = 0.008                   # across the band, along the surface
    band_thickness: float = 0.003
    band_embed: float = 0.0005                  # inner face 0.5 mm into the hair
    band_visible_x: float = 0.087               # visible span; from y ~ band_tuck_y back it is under H2
    band_tuck_y: float = -0.028
    band_end_bury: float = 0.004                # capped ends buried >= 4 mm inside H2
    band_ridge_width: float = 0.002             # pink centre ridge (material uniform), whole visible span
    band_ridge_height: float = 0.0006
    # -- C.2 bangs (H3) -----------------------------------------------------------------------------------
    bangs_half_width: float = 0.072             # follows the forehead curve (arc in top view)
    bangs_top_z: tuple = (1.4615, 1.452)        # band's lower edge at the middle / at x +-0.072
    bangs_top_extension: float = 0.005          # the slab continues this far up under the band into H1
    bangs_skin_gap: float = 0.001               # inner surface off the forehead (at the cut)
    bangs_thickness: float = 0.011              # even down to the cut
    bangs_outer_y: tuple = (-0.089, -0.0975)    # outer surface at the midline: top, cut (leans ~16 deg forward)
    bangs_curl: tuple = (0.004, 0.002)          # the bottom 4 mm curl 2 mm toward the forehead
    bangs_strips: int = 6                       # front split into 6 strips (5 strand lines, 3-4 deg creases)
    # -- C.3 sidelocks (H4) ---------------------------------------------------------------------------------
    sidelock_width: float = 0.026               # stated ribbon width (the edge table spans 0.031-0.040)
    sidelock_thickness: float = 0.009
    #: Edge positions (centre of the thickness) for her left: ``(z, x_in, y_in, x_out, y_out)``; the last row
    #: is the straight horizontal cut.
    sidelock_rows: tuple = (
        (1.445, 0.072, -0.060, 0.098, -0.030),   # root, merged into H1/H2
        (1.400, 0.072, -0.068, 0.098, -0.036),   # covers the forehead corner / temple
        (1.370, 0.072, -0.066, 0.098, -0.034),
        (1.342, 0.072, -0.052, 0.098, -0.026),   # 3.3 mm off the skin at the eye level
        (1.310, 0.072, -0.046, 0.098, -0.022),
        (1.270, 0.073, -0.044, 0.099, -0.022),   # beside the jaw
        (1.220, 0.073, -0.054, 0.099, -0.034),   # starts to come forward over the shoulder
        (1.180, 0.074, -0.068, 0.100, -0.052),   # >= 12 mm in front of the collar / shoulder
        (1.145, 0.074, -0.086, 0.101, -0.072),   # lies on the collar lapel
        (1.120, 0.074, -0.092, 0.101, -0.078),   # straight horizontal cut
    )
    sidelock_crease_x: float = 0.086            # one shallow strand crease on the front face, from z 1.43
    sidelock_crease_top_z: float = 1.43
    # -- C.4 stray strand (H5): exactly one, on her LEFT (+x) -------------------------------------------------
    strand_points: tuple = (
        (0.022, -0.086, 1.474),    # P0 root on H1, just above/behind the band
        (0.030, -0.093, 1.463),    # P1 arches over the band
        (0.040, -0.096, 1.432),    # P2 crosses the bangs, passing their cut
        (0.052, -0.086, 1.400),    # P3 diagonally outward over the forehead
        (0.063, -0.074, 1.368),    # P4 crosses the outer end of the brow
        (0.071, -0.060, 1.335),    # P5 8 mm outside the eye's outer corner, in front of the sidelock
        (0.074, -0.062, 1.305),    # P6 tip, on the sidelock's front face
    )
    strand_width: float = 0.004                 # 4-6 sided section, Catmull-Rom through the points
    strand_thickness: float = 0.002
    strand_taper_length: float = 0.030          # tapers to a point over the last 30 mm (length ~0.19)
    # -- C.6 side curtain + back sheet (H2) --------------------------------------------------------------------
    #: Crescent rows for z >= 1.215: ``(z, cy, ax, outer back y, t, y_end)``: outer contour = ellipse centre
    #: ``(0, cy)``, semi-axes ``ax`` and ``outer back y - cy``; inner = outer offset by ``t``; blunt end faces
    #: at the curtain's front edge ``y_end``.
    curtain_rows: tuple = (
        (1.450, 0.012, 0.0985, 0.136, 0.020, -0.034),   # starts under H1, behind the sidelock root
        (1.400, 0.012, 0.1000, 0.137, 0.020, -0.034),   # covers the ear zone
        (1.340, 0.012, 0.1020, 0.133, 0.022, -0.028),
        (1.290, 0.012, 0.1035, 0.128, 0.024, -0.022),
        (1.250, 0.020, 0.1060, 0.125, 0.026, 0.010),    # behind the jaw; neck shows between curtain and sidelock
        (1.215, 0.040, 0.1100, 0.123, 0.028, 0.060),    # goes behind the shoulders
    )
    #: Back sheet rows for z <= 1.18: ``(z, hw, midline inner y, midline outer y, thickness)``; blunt lateral
    #: faces at +-hw; the inner surface is the blouse / collar back + back_sheet_gap where that is closer.
    back_sheet_rows: tuple = (
        (1.180, 0.122, 0.090, 0.121, 0.020),
        (1.100, 0.130, 0.099, 0.119, 0.020),
        (1.000, 0.137, 0.099, 0.118, 0.019),
        (0.920, 0.143, 0.099, 0.117, 0.018),
        (0.860, 0.150, 0.100, 0.116, 0.016),            # end of the flat part
    )
    back_sheet_gap: float = 0.008
    hair_clumps: int = 7                        # shallow pointed clumps across the width, blunt lower faces
    clump_notch_z: float = 0.860
    clump_tip_z: float = 0.830
    clump_tip_x: tuple = (-0.129, -0.086, -0.043, 0.0, 0.043, 0.086, 0.129)
    hair_grooves: int = 4                       # V-grooves between clumps 2/3, 3/4, 4/5, 5/6
    groove_depth: float = 0.002
    groove_top_z: float = 1.30

    # =====================================================================================================
    # D.1-D.3 Blouse, sailor collar, scarf + ring
    # =====================================================================================================
    collar_thickness: float = 0.004             # §D.2 grows outward from the underside points
    collar_gap: float = 0.001                   # on the blouse (lapels lift over the scarf: in the points)
    #: Outer edge O1..O9 on the collar underside, her left half (§D.2).
    collar_outer: tuple = (
        (0.000, 0.085, 1.030),     # O1 back flap, bottom centre
        (0.105, 0.061, 1.030),     # O2 back flap bottom corner (square)
        (0.105, 0.070, 1.120),     # O3 flap side, going up
        (0.110, 0.045, 1.188),     # O4 turning forward over the shoulder
        (0.118, 0.000, 1.192),     # O5 on top of the shoulder
        (0.116, -0.058, 1.170),    # O6 front of the shoulder (lapel lifted 10 mm over the scarf)
        (0.082, -0.084, 1.136),    # O7 lift 9 mm
        (0.040, -0.097, 1.110),    # O8 lift 6 mm
        (0.000, -0.099, 1.090),    # O9 V tip (lift 1 mm; collar front surface -0.103)
    )
    #: Inner edge / neckline I1..I7 (§D.2); I7 = O9.
    collar_inner: tuple = (
        (0.000, 0.052, 1.212), (0.034, 0.045, 1.210), (0.042, 0.012, 1.213), (0.038, -0.043, 1.195),
        (0.030, -0.063, 1.168), (0.015, -0.087, 1.128), (0.000, -0.099, 1.090),
    )
    collar_stripe_width: float = 0.008          # one pink stripe (material uniform), raised band
    collar_stripe_inset: float = 0.010          # its outer border inside the outer edge
    collar_stripe_relief: float = 0.0008
    dickey_thickness: float = 0.0015            # white V filler (material collar), 1 mm above the blouse
    dickey_corners: tuple = ((0.024, -0.066, 1.165), (0.0, -0.0985, 1.096))  # mid-thickness (mirror the first)
    #: Scarf ribbon path S0..S5 (§D.3), centre of the thickness, her left; S0 hidden under the collar.
    scarf_path: tuple = (
        (0.120, -0.052, 1.176), (0.110, -0.064, 1.150), (0.080, -0.085, 1.120),
        (0.044, -0.098, 1.098), (0.012, -0.104, 1.080), (0.006, -0.110, 1.070),
    )
    scarf_width: tuple = (0.045, 0.018)         # lens section width at S0, at S4 (in the chest surface)
    scarf_thickness: tuple = (0.010, 0.006)     # at S0, at S4
    ring_center: tuple = (0.0, -0.112, 1.072)   # rounded box (material collar), top at z 1.084
    ring_size: tuple = (0.036, 0.016, 0.024)    # x, y (from -0.104 to -0.120), z
    ring_corner_radius: float = 0.005
    ring_stripe_z: tuple = (1.068, 1.076)       # two pink stripes (material uniform), centre z
    ring_stripe_height: float = 0.003
    ring_stripe_relief: float = 0.0006
    scarf_tip_thickness: float = 0.004          # flat blades 1-2 mm off the blouse front
    scarf_tip_root: tuple = (0.008, -0.116, 1.064)   # tip B (her left, in front); tip A: scarf_tip_root_right
    scarf_tip_root_right: tuple = (-0.008, -0.113, 1.064)   # tip A (her right, behind)
    scarf_tip_root_width: float = 0.018
    scarf_tip_angle_deg: float = 15.0           # from vertical, outward
    scarf_tip_length: float = 0.090
    scarf_tip_max_width: tuple = (0.034, 0.7)   # widest, at this fraction of the length
    scarf_tip_cut_deg: float = 45.0             # oblique end cut, the point on the outer side
    scarf_tip_point: tuple = (0.031, -0.116, 0.977)   # tip B point; tip A (-0.031, -0.113, 0.977)
    scarf_tip_front_offset: float = 0.003       # tip B lies 3 mm in front of tip A where they overlap

    # =====================================================================================================
    # D.4 Sleeves, cuffs, hands
    # =====================================================================================================
    #: Sleeve radius along the arm: ``(position, radius)`` with position 0 = shoulder joint, 0.5 = mid upper
    #: arm, 1 = elbow, 1.5 = mid forearm, 2 = wrist.
    sleeve_radii: tuple = ((0.0, 0.048), (0.5, 0.045), (1.0, 0.043), (1.5, 0.044), (2.0, 0.044))
    cuff_past_wrist: float = 0.010              # cuff edge beyond the wrist joint toward the hand
    cuff_rim: float = 0.005                     # the tube closes with a rim turning in to the opening
    cuff_opening_radius: float = 0.030
    cuff_recess: float = 0.010                  # recessed disc this far inside
    cuff_stripes: tuple = ((0.012, 0.020), (0.028, 0.036))   # white stripes (object cuffs, material collar),
    cuff_stripe_relief: float = 0.0008                       # distances from the cuff edge
    hand_length: float = 0.140                  # wrist to middle fingertip; one closed mitten (material skin)
    palm_length: float = 0.075
    palm_width: float = 0.066
    palm_thickness: float = 0.024
    finger_length: float = 0.065
    finger_tip_thickness: float = 0.016
    finger_curl_deg: tuple = (20.0, 15.0)       # at the knuckles, at the middle joints
    thumb_length: float = 0.050                 # lobe from the index side of the palm base, lying forward
    thumb_thickness: float = 0.018
    wrist_in_sleeve: float = 0.015
    palm_turn_back_deg: float = 20.0            # palm faces the thigh (medial), turned back; thumb in front

    # =====================================================================================================
    # D.5 Skirt and under-skirt (object skirt, material skirt)
    # =====================================================================================================
    #: Outer surface at the pleat crests: ``(z, hw, yf, yb)``; superellipse exponent skirt_exponent.
    skirt_rows: tuple = (
        (0.950, 0.108, -0.068, 0.062),     # waist rim (hidden under the blouse)
        (0.900, 0.122, -0.088, 0.075),     # inside the blouse hem
        (0.860, 0.138, -0.093, 0.086),
        (0.780, 0.165, -0.102, 0.112),     # pleats open below here
        (0.690, 0.180, -0.120, 0.130),
        (0.550, 0.200, -0.142, 0.152),
        (0.450, 0.215, -0.158, 0.168),     # hem, 3 cm above the knee centre
    )
    skirt_exponent: float = 2.2
    skirt_thickness: float = 0.003              # thick tube, open bottom
    skirt_pleats: int = 16                      # knife pleats, all clockwise from above, 22.5 deg each
    pleat_depth: float = 0.010                  # valley radially inside the crest at the hem
    pleat_top_z: float = 0.780                  # depth tapers to 0 here; smooth yoke above
    underskirt_z: tuple = (0.700, 0.950)        # bloomers block with the body hip shape (body_hip)

    # =====================================================================================================
    # D.6 Legs, socks, shoes
    # =====================================================================================================
    leg_top_z: float = 0.720                    # inside the under-skirt block
    #: Leg radius by z (circular): ``(z, r)`` top to bottom.
    leg_radii: tuple = ((0.700, 0.072), (0.600, 0.064), (0.500, 0.054), (0.420, 0.046), (0.320, 0.050),
                        (0.200, 0.040), (0.100, 0.030), (0.065, 0.029))
    sock_ease: float = 0.0015                   # sock = leg + 1.5 mm, top rim a 1.5 mm step (white knee socks)
    shoe_length: float = 0.225                  # dark brown penny loafers, along the (turned-out) foot axis
    shoe_heel_y: float = 0.050                  # heel at y +0.050, toe at y -0.175
    shoe_toe_y: float = -0.175
    shoe_ball_width: float = 0.084
    shoe_heel_width: float = 0.062
    shoe_heel_x: float = 0.082                  # heel centres at x +-0.082
    shoe_toe_out_deg: float = 8.0
    shoe_sole: float = 0.012                    # sole slab, its own smooth group
    shoe_heel_height: float = 0.025             # heel block at the back
    shoe_instep: float = 0.075
    shoe_topline_z: float = 0.055               # opening rim around the ankle
    strap_width: float = 0.012                  # saddle strap across the instep at y ~ strap_y, 1 mm proud
    strap_y: float = -0.07
    strap_relief: float = 0.001

    # =====================================================================================================
    # E. Pose (relaxed A-pose; the joint positions are binding, the angles document them)
    # =====================================================================================================
    shoulder_joint_pos: tuple = (0.140, 0.005, 1.155)
    acromion: tuple = (0.150, 0.005, 1.180)
    elbow_pos: tuple = (0.224, -0.012, 0.925)
    wrist_pos: tuple = (0.292, -0.080, 0.738)
    fingertip_pos: tuple = (0.339, -0.102, 0.608)   # middle fingertip
    arm_abduction_deg: float = 20.0             # upper arm (0.245 long) in the frontal plane
    arm_flexion_deg: float = 4.0                # upper arm flexed forward
    elbow_bend_deg: float = 15.0                # forearm (0.210 long) bent forward
    wrist_extension_deg: float = 10.0           # hand extended back relative to the forearm
    hip_joint_pos: tuple = (0.078, 0.005, 0.780)
    knee_pos: tuple = (0.077, 0.000, 0.420)
    ankle_pos: tuple = (0.077, 0.010, 0.065)

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
        """``(z, hw, yf, yb)`` of a landmark row (spec §A)."""
        for row in self.landmarks:
            if row[0] == name:
                return row[1:]
        raise KeyError(f"unknown landmark {name!r}; one of {[r[0] for r in self.landmarks]}")

    height = property(lambda self: self.landmark("skull top")[0], doc="sole to skull top (1.510)")
    hair_top_z = property(lambda self: self.landmark("hair top")[0])
    chin_z = property(lambda self: self.landmark("chin")[0])
    head_height = property(lambda self: self.height - self.chin_z, doc="chin to skull top (0.255)")
    heads_tall = property(lambda self: self.height / self.head_height)
    headband_front_z = property(lambda self: self.landmark("headband front")[0])
    bangs_cut_z = property(lambda self: self.landmark("bang cut")[0])
    brow_z = property(lambda self: self.landmark("brow line")[0])
    eye_z = property(lambda self: self.landmark("eye centre")[0])
    nose_z = property(lambda self: self.landmark("nose tip")[0])
    mouth_z = property(lambda self: self.landmark("mouth")[0])
    neck_base_z = property(lambda self: self.landmark("neck base")[0])
    shoulder_z = property(lambda self: self.landmark("shoulder line")[0])
    armpit_z = property(lambda self: self.landmark("armpit")[0])
    bust_z = property(lambda self: self.landmark("bust")[0])
    waist_z = property(lambda self: self.landmark("waist")[0])
    blouse_hem_z = property(lambda self: self.landmark("blouse hem")[0])
    hip_z = property(lambda self: self.landmark("hip widest")[0])
    crotch_z = property(lambda self: self.landmark("crotch")[0])
    skirt_hem_z = property(lambda self: self.landmark("skirt hem")[0])
    knee_z = property(lambda self: self.landmark("knee")[0])
    sock_top_z = property(lambda self: self.landmark("sock top")[0])
    ankle_z = property(lambda self: self.landmark("ankle")[0])
    skirt_waist_z = property(lambda self: self.skirt_rows[0][0])

    # -----------------------------------------------------------------------------------------------------
    # head
    @property
    def head_center(self) -> np.ndarray:
        """Centre of the cranium ellipsoid (camera framing, "away from the head" directions)."""
        return np.array(self.cranium_center, dtype=np.float64)

    @property
    def head_radii(self) -> np.ndarray:
        return np.array(self.cranium_radii, dtype=np.float64)

    def face_offset(self, z: float) -> float:
        """Widest-point offset ``c`` of the head section at ``z`` (§B.1)."""
        z0, z1 = self.face_center_offset_z
        t = min(1.0, max(0.0, (z - z0) / (z1 - z0)))
        return self.face_center_offset * t

    def head_section(self, z: float):
        """``(hw, yf, yb, c)`` of the skin head at ``z`` (linear in the profile table; ``yb`` is None below
        the nape row, where the back is the neck)."""
        rows = self.head_profile
        hw = _interp_rows(rows, z, 1)
        yf = _interp_rows(rows, z, 2)
        backs = [r for r in rows if r[3] is not None]
        yb = _interp_rows(backs, z, 3) if z >= backs[-1][0] else None
        return hw, yf, yb, self.face_offset(z)

    def head_surface_y(self, x: float, z: float, front: bool = True) -> float:
        """y of the skin head at ``(x, z)`` from the §B.1 section model: front half the superellipse
        ``|x/hw|^3 + |(y-c)/(c-yf)|^3 = 1``, back half the ellipse with semi-axes ``(hw, yb - c)``.  For
        ``|x| >= hw`` the section's side point ``y = c`` is returned."""
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

    def head_surface_point(self, x: float, z: float, front: bool = True) -> np.ndarray:
        """Point of the skin head at ``(x, z)`` on the front (``-Y``) or back side."""
        return np.array([x, self.head_surface_y(x, z, front), z])

    def head_normal(self, x: float, z: float, d: float = 1e-4) -> np.ndarray:
        """Outward unit normal of the front face surface at ``(x, z)`` (finite differences)."""
        px = self.head_surface_point(x + d, z) - self.head_surface_point(x - d, z)
        pz = self.head_surface_point(x, z + d) - self.head_surface_point(x, z - d)
        n = np.cross(pz, px)
        n = n / np.linalg.norm(n)
        return -n if n[1] > 0 else n

    def eye_center(self, side: int) -> np.ndarray:
        """Eye centre on the face surface ``(+-0.040, -0.0805, 1.342)``."""
        return self.head_surface_point(side * self.eye_x, self.eye_z)

    def dome_section(self, z: float):
        """``(hw, yf, yb)`` of the top-hair ellipsoid H1 at ``z`` (zero width outside it)."""
        c, (ax, ayf, az) = self.dome_center, self.dome_radii
        q = 1.0 - ((z - c[2]) / az) ** 2
        s = math.sqrt(q) if q > 0 else 0.0
        return ax * s, c[1] - ayf * s, c[1] + self.dome_back_radius * s

    # -----------------------------------------------------------------------------------------------------
    # torso
    def blouse_section(self, z: float):
        """``(hw, yf, yb)`` of the blouse at ``z`` (linear in :attr:`blouse_rows`)."""
        return tuple(_interp_rows(self.blouse_rows, z, k) for k in (1, 2, 3))

    def skirt_section(self, z: float):
        """``(hw, yf, yb)`` of the skirt's outer surface at the pleat crests at ``z``."""
        return tuple(_interp_rows(self.skirt_rows, z, k) for k in (1, 2, 3))

    def leg_radius(self, z: float) -> float:
        rows = self.leg_radii
        return _interp_rows(rows, z, 1)

    # -----------------------------------------------------------------------------------------------------
    # arms
    def shoulder_joint(self, side: int) -> np.ndarray:
        return self.at(self.shoulder_joint_pos, side)

    def elbow(self, side: int) -> np.ndarray:
        return self.at(self.elbow_pos, side)

    def wrist(self, side: int) -> np.ndarray:
        return self.at(self.wrist_pos, side)

    def fingertip(self, side: int) -> np.ndarray:
        return self.at(self.fingertip_pos, side)

    def upper_arm_dir(self, side: int) -> np.ndarray:
        d = self.elbow(side) - self.shoulder_joint(side)
        return d / np.linalg.norm(d)

    def forearm_dir(self, side: int) -> np.ndarray:
        d = self.wrist(side) - self.elbow(side)
        return d / np.linalg.norm(d)

    def hand_dir(self, side: int) -> np.ndarray:
        d = self.fingertip(side) - self.wrist(side)
        return d / np.linalg.norm(d)

    @property
    def upper_arm_length(self) -> float:
        return float(np.linalg.norm(np.subtract(self.elbow_pos, self.shoulder_joint_pos)))

    @property
    def forearm_length(self) -> float:
        return float(np.linalg.norm(np.subtract(self.wrist_pos, self.elbow_pos)))

    def cuff_edge(self, side: int) -> np.ndarray:
        """Centre of the sleeve's cuff edge: ``cuff_past_wrist`` beyond the wrist along the forearm."""
        return self.wrist(side) + self.cuff_past_wrist * self.forearm_dir(side)

    def sleeve_radius(self, position: float) -> float:
        """Sleeve radius at ``position`` (0 shoulder joint, 1 elbow, 2 wrist; see :attr:`sleeve_radii`)."""
        p, r = zip(*self.sleeve_radii)
        return float(np.interp(position, p, r))

    # -----------------------------------------------------------------------------------------------------
    # legs
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

    def foot_dir(self, side: int) -> np.ndarray:
        """Horizontal unit vector heel -> toe (``-Y`` turned out by ``shoe_toe_out_deg``)."""
        t = math.radians(self.shoe_toe_out_deg)
        return np.array([side * math.sin(t), -math.cos(t), 0.0])

    def heel_point(self, side: int) -> np.ndarray:
        """Back of the shoe sole on the ground: ``(+-shoe_heel_x, shoe_heel_y, 0)``."""
        return np.array([side * self.shoe_heel_x, self.shoe_heel_y, 0.0])


DEFAULT_RIG = Rig()
