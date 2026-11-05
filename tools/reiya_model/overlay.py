"""Reiya's overlay data: how her design sheet (三面図) is drawn and what the overlay check measures on it.

The check itself is character-free (:mod:`charmodel.overlay`); this module holds Reiya's half of it:

* the sheet's mapping (SPEC.md, "Appendix: measurements on the design sheet"): one scale ``s = 0.000615`` m per
  pixel at the sheet scale, the ground at row 2745, front ``X = (px - 1940) s``, back ``X = -(px - 2839) s``, side
  (よこ, her LEFT profile, image left = her front) ``Y = (px - 3655) s``, ``Z = (2745 - py) s``; the model is built at
  this scale and then scaled by ``rig.figure_scale`` (1.52 / 1.555), so the check divides it by that first and quotes
  offsets in mm on the final 152 cm figure (sheet-scale offset x ``figure_scale``);
* the sheet's colour classes (palette swatches and the shades the sheet paints), the material -> class map;
* the row bands, the class outlines and lower edges, the landmarks, the zoomed crops, the smoothness parts and views,
  the shaded skin probe, the pose / clearance extras and the pass criteria (each with its sentence and its grounds
  below; the overlay section of ``tools/reiya_model/README.md`` and SPEC.md Decision 31 explain them).

Run it with ``python3 tools/make_reiya_model.py --overlay SHEET.png DIR`` (DIR outside the repository: the images
contain the sheet, which never goes into the repository).
"""

from __future__ import annotations

import math

import numpy as np

from charmodel import meshkit as mk
from charmodel.overlay import (Criterion, Landmark, LowerEdge, OverlaySpec, Outline, Probe, SheetSpec, SheetView,
                               mesh_distance)

from .assemble import MATERIALS
from .preview import PRESETS, cameras
from .rig import SUN_TOWARDS, Rig

__all__ = ["SHEET", "SPEC", "SHEET_WRIST", "SHEET_SHOULDER", "extras"]

#: Sheet scale (metres per pixel) and the ground row (SPEC.md appendix).
SCALE = 0.000615
GROUND_ROW = 2745

#: The views: the front (正面), her left profile (よこ, image left = her front, -Y), the back (後ろ) and the
#: cardigan-off front (カーディガンOFF, the model without its cardigan; informational).  Each box holds that figure
#: only; the label boxes hold the view's label and the leader line that touches the figure.
VIEWS = (
    SheetView("front", (1.0, 0.0, 0.0), 1940, (1480, 80, 2400, 2800), "正面",
              label_boxes=((1440, 636, 1736, 728), (2320, 636, 2400, 734))),
    SheetView("left", (0.0, 1.0, 0.0), 3655, (3290, 80, 4000, 2800), "よこ",
              label_boxes=((3180, 636, 3480, 728),)),
    SheetView("back", (-1.0, 0.0, 0.0), 2839, (2400, 80, 3285, 2800), "後ろ",
              label_boxes=((2320, 636, 2628, 734), (3180, 636, 3285, 728))),
    SheetView("front_off", (1.0, 0.0, 0.0), 1044, (600, 80, 1478, 2800), "カーディガンOFF",
              label_boxes=((560, 636, 864, 728), (1440, 636, 1480, 728)), hide_materials=("cardigan",)),
)

_WHITE = ((242, 242, 242), (230, 194, 194), (255, 255, 255), (220, 220, 225), (200, 200, 210), (176, 176, 176))
_SOCK_Z = 0.30          # white below this is the socks, above it the mock-neck top
_EYE_Z = (1.43, 1.50)   # the eye band (iris, sclera)

#: Colour classes: representative colours (r, g, b), or (r, g, b, z_lo, z_hi) to count only at those heights
#: (sheet-scale metres).  The first colour paints the class.  The ink lines (``line``) take their neighbours' class.
_HAIR_Z = (1.32, 3.0)    # the hair (and the braids) lie above this: the skin's shadow tone is the hair colour
_BODY_Z = (-1.0, 1.36)   # the dress, the cardigan and the buttons lie below this (the cardigan's top at 1.33)
_INK = (78, 53, 43)
CLASSES = {
    "hair": tuple(c + _HAIR_Z for c in ((242, 181, 167), (242, 190, 178), (233, 145, 135), (242, 166, 150),
                                         (226, 150, 140), (210, 140, 150)))
            + ((250, 210, 194, 1.42, 3.0),          # its light tone is the neck's below the nape
               (225, 215, 239, 1.36, 1.46),         # the lavender under the side hair
               (255, 223, 210, 1.55, 1.70),         # the tufts' light inner face
               (255, 230, 212, 1.50, 3.0)),         # the highlight band on the crown
    "skin": ((255, 248, 241), (255, 222, 206), (246, 208, 194), (254, 236, 226), (246, 188, 156), (255, 242, 235),
             (246, 206, 191), (251, 198, 177), (240, 181, 163), (248, 190, 168)),
    "eyes": tuple(c + _EYE_Z for c in ((210, 87, 84), (215, 111, 113), (159, 42, 41), (99, 135, 166),
                                        (43, 72, 92), (196, 227, 230), (42, 57, 68))),
    "white": tuple(c + (_SOCK_Z, 3.0) for c in _WHITE),
    "navy": tuple(c + _BODY_Z for c in ((24, 64, 89), (21, 48, 68), (14, 34, 47), (16, 44, 61), (35, 80, 105),
                                         (30, 60, 80))),
    "cardigan": tuple(c + _BODY_Z for c in ((166, 107, 99), (140, 85, 78), (120, 70, 65), (185, 125, 115))),
    "gold": tuple(c + _BODY_Z for c in ((217, 149, 89), (240, 190, 120), (190, 120, 70))),
    "shoes": tuple(c + (-1.0, 0.13) for c in ((145, 100, 60), (190, 130, 80), (120, 80, 50), (210, 150, 100),
                                               (160, 110, 70))),
    "socks": tuple(c + (-1.0, _SOCK_Z) for c in _WHITE),
    # the ink (#4e352b), and its anti-aliased mixes with the paper, the skin and its shadow tone (they would read as
    # the cardigan)
    "line": ((0, 0, 0), (63, 41, 36), (40, 30, 30), (90, 70, 70), _INK) + tuple(
        tuple(int(round(a * i + (1.0 - a) * c)) for i, c in zip(_INK, light))
        for light in ((249, 249, 249), (255, 248, 241), (240, 181, 163)) for a in (0.75, 0.5)),
}

SHEET = SheetSpec(scale=SCALE, ground_row=GROUND_ROW, views=VIEWS, classes=CLASSES, background_greys=(249, 214),
                  label_greys=(100, 213), line_class="line", line_fill_px=6, ring_px=2,
                  relabel=(("white", "eyes") + _EYE_Z,                # the scleras and the eye highlights
                           ("socks", "skin", 0.258, _SOCK_Z),          # the highlights on the bare calves
                           ("white", "skin", _SOCK_Z, 0.335)))

#: Material -> class.  The lashes, brows, mouth and blush strokes are ink on the sheet: they take their neighbours'
#: class on both images.
MATERIAL_CLASSES = {
    "hair": "hair", "hair_inner": "hair", "tuft_inner": "hair", "skin": "skin", "eye_white": "eyes",
    "iris_red": "eyes", "pupil_red": "eyes", "iris_blue": "eyes", "pupil_blue": "eyes", "lashes": "line",
    "face_marks": "line", "top": "white", "dress": "navy", "buttons": "gold", "cardigan": "cardigan",
    "socks": "socks", "star": "navy", "shoes": "shoes",
}

#: Row bands of the silhouette (sheet-scale metres).  ``face`` is the bob beside the face (the curtains cover the
#: face's edge), ``hem`` the rows of the sheet's curved hem (Decision 9: the model's hem is level at 0.390).
BANDS = (
    ("tufts", 1.575, 1.625), ("hair", 1.47, 1.575), ("face", 1.39, 1.47), ("neck", 1.335, 1.39),
    ("shoulders", 1.20, 1.335), ("sleeves", 0.84, 1.20), ("hands", 0.76, 0.84), ("skirt", 0.43, 0.76),
    ("hem", 0.33, 0.43), ("legs", 0.26, 0.33), ("socks", 0.10, 0.26), ("shoes", 0.0, 0.10),
)

_IOU = ("hair", "skin", "white", "navy", "cardigan", "gold", "shoes", "socks")
#: Per-class IoU per view (the eyes only where they show).
IOU_CLASSES = {"front": _IOU[:2] + ("eyes",) + _IOU[2:], "left": _IOU[:2] + ("eyes",) + _IOU[2:], "back": _IOU,
               "front_off": ("white", "navy", "skin")}

_LR = ("left", "right")
OUTLINES = (
    Outline("hair", "front", "figure", 1.41, 1.575, _LR),
    Outline("tuft_r", "front", "hair", 1.575, 1.625, ("left",), h_range=(-0.12, -0.02)),
    Outline("tuft_l", "front", "hair", 1.575, 1.625, ("right",), h_range=(0.02, 0.12)),
    Outline("sleeve", "front", "cardigan", 0.90, 1.20, _LR),
    Outline("sleeve_inner", "front", "cardigan", 0.90, 0.99, _LR, inner=True),
    Outline("cuff", "front", "cardigan", 0.84, 0.90, _LR),
    Outline("skirt", "front", "navy", 0.43, 0.84, _LR),
    Outline("hair", "back", "figure", 1.41, 1.575, _LR),
    Outline("tuft_l", "back", "hair", 1.575, 1.625, ("left",), h_range=(-0.12, -0.02)),
    Outline("tuft_r", "back", "hair", 1.575, 1.625, ("right",), h_range=(0.02, 0.12)),
    Outline("sleeve", "back", "cardigan", 0.90, 1.20, _LR),
    Outline("sleeve_inner", "back", "cardigan", 0.90, 0.99, _LR, inner=True),
    Outline("cuff", "back", "cardigan", 0.84, 0.90, _LR),
    Outline("skirt", "back", "navy", 0.43, 0.84, _LR),
    Outline("hair_back", "left", "figure", 1.40, 1.575, ("right",)),
    Outline("hair_front", "left", "figure", 1.47, 1.575, ("left",)),
    Outline("skirt_front", "left", "navy", 0.43, 1.00, ("left",)),
    Outline("skirt_back", "left", "navy", 0.43, 0.80, ("right",)),
    Outline("cardigan_front", "left", "cardigan", 1.08, 1.25, ("left",)),
    Outline("cardigan_back", "left", "cardigan", 0.95, 1.32, ("right",)),
    Outline("top", "front_off", "white", 1.25, 1.37, _LR),
    Outline("bodice", "front_off", "navy", 1.11, 1.26, _LR),
)

_SIDE_TIPS = ((-0.125, -0.085), (0.085, 0.125))      # outside the braids, inside the bell
LOWER_EDGES = (
    LowerEdge("bob_tips", "front", "hair", _SIDE_TIPS, 1.37, 1.47),
    LowerEdge("fringe", "front", "hair", ((-0.015, 0.055),), 1.44, 1.52),
    LowerEdge("hem", "front", "navy", ((-0.22, 0.22),), 0.30, 0.45),
    LowerEdge("bob_tips", "back", "hair", _SIDE_TIPS, 1.37, 1.47),
    LowerEdge("bob_nape", "back", "hair", ((-0.035, 0.035),), 1.36, 1.47),
    LowerEdge("hem", "back", "navy", ((-0.22, 0.22),), 0.30, 0.45),
    LowerEdge("bob_side", "left", "hair", ((-0.10, -0.012), (0.035, 0.11)), 1.37, 1.47),
    LowerEdge("hem", "left", "navy", ((-0.23, 0.19),), 0.30, 0.45),
)


def _pair(name, view, kind, cls, h_range, z_range, axes, sides=("r", "l"), min_run=0.0):
    """A landmark per side: ``h_range`` is the image-left one; the other is mirrored (``sides`` names the image-left
    side first: her right in the front view, her left in the back view)."""
    lo, hi = h_range
    mirror = {"left": "right", "right": "left"}.get(kind, kind)
    return (Landmark(f"{name}_{sides[0]}", view, kind, cls, (lo, hi), z_range, axes, min_run),
            Landmark(f"{name}_{sides[1]}", view, mirror, cls, (-hi, -lo), z_range, axes, min_run))


def _landmarks():
    out = []
    for view, sides in (("front", ("r", "l")), ("back", ("l", "r"))):
        out += [Landmark("crown", view, "top", "hair", (-0.02, 0.02), (1.5, 1.7), "z")]
        out += _pair("tuft_tip", view, "top", "hair", (-0.10, -0.03), (1.57, 1.7), "hz", sides)
        out += _pair("bob_widest", view, "left", "hair", (-0.2, -0.05), (1.40, 1.47), "h", sides)
        out += _pair("bob_tip", view, "bottom", "hair", (-0.135, -0.085), (1.37, 1.47), "hz", sides)
        out += _pair("shoulder", view, "left", "figure", (-0.2, 0.0), (1.295, 1.31), "h", sides)
        out += _pair("sleeve_widest", view, "left", "cardigan", (-0.3, -0.1), (0.86, 1.0), "hz", sides)
        out += _pair("cuff", view, "bottom", "cardigan", (-0.3, -0.1), (0.75, 0.95), "hz", sides, 0.025)
        out += _pair("hand_tip", view, "bottom", "skin", (-0.3, -0.12), (0.70, 0.88), "hz", sides)
        out += _pair("hand_out", view, "left", "skin", (-0.3, -0.12), (0.70, 0.88), "h", sides)
        out += _pair("hem_width", view, "left", "navy", (-0.3, -0.1), (0.40, 0.45), "h", sides)
        out += _pair("hem_side", view, "bottom", "navy", (-0.215, -0.17), (0.30, 0.45), "z", sides)
        out += _pair("sock_cuff", view, "top", "socks", (-0.12, 0.0), (0.15, 0.30), "z", sides)
        out += [Landmark("sole", view, "bottom", "shoes", (-0.15, 0.15), (-0.02, 0.10), "z")]
    out += [Landmark("bang_line", "front", "bottom", "hair", (-0.01, 0.01), (1.44, 1.52), "z"),
            Landmark("mock_neck_rim", "front", "top", "white", (-0.015, 0.015), (1.30, 1.375), "z"),
            Landmark("cardigan_hem", "front", "bottom", "cardigan", (-0.02, 0.02), (0.95, 1.15), "z"),
            Landmark("nape", "back", "bottom", "hair", (-0.02, 0.02), (1.36, 1.45), "z"),
            Landmark("cardigan_neckline", "back", "top", "cardigan", (-0.02, 0.02), (1.2, 1.4), "z"),
            Landmark("cardigan_hem", "back", "bottom", "cardigan", (-0.02, 0.02), (0.9, 1.1), "z")]
    out += [Landmark("tuft_top", "left", "top", "hair", (-0.03, 0.05), (1.55, 1.7), "hz"),
            Landmark("hair_front", "left", "left", "hair", (-0.2, 0.0), (1.48, 1.53), "h"),
            Landmark("hair_back", "left", "right", "hair", (0.0, 0.2), (1.40, 1.50), "h"),
            Landmark("bob_front_tip", "left", "bottom", "hair", (-0.13, -0.085), (1.37, 1.47), "hz"),
            Landmark("nape", "left", "bottom", "hair", (0.04, 0.12), (1.36, 1.45), "hz"),
            Landmark("chin", "left", "bottom", "skin", (-0.095, -0.06), (1.36, 1.43), "hz"),
            Landmark("nose", "left", "left", "skin", (-0.2, -0.05), (1.42, 1.45), "h"),
            Landmark("cardigan_front", "left", "left", "cardigan", (-0.25, 0.0), (1.08, 1.16), "h"),
            Landmark("cardigan_back", "left", "right", "cardigan", (0.0, 0.25), (0.90, 1.35), "h"),
            Landmark("skirt_front_hem", "left", "left", "navy", (-0.3, 0.0), (0.42, 0.46), "h"),
            Landmark("skirt_back_hem", "left", "right", "navy", (0.0, 0.3), (0.42, 0.46), "h"),
            Landmark("sock_cuff", "left", "top", "socks", (-0.1, 0.1), (0.15, 0.30), "z"),
            Landmark("toe", "left", "left", "shoes", (-0.3, 0.0), (0.0, 0.1), "h"),
            Landmark("heel", "left", "right", "shoes", (0.0, 0.2), (0.0, 0.1), "h"),
            Landmark("sole", "left", "bottom", "shoes", (-0.2, 0.1), (-0.02, 0.10), "z")]
    return tuple(out)


LANDMARKS = _landmarks()

#: Zoomed crops ``(view, name, (h_lo, h_hi, z_lo, z_hi), magnification)``.
ZOOMS = (
    ("front", "head", (-0.17, 0.17, 1.32, 1.63), 3), ("front", "sleeve_r", (-0.28, -0.04, 0.74, 1.34), 2),
    ("front", "sleeve_l", (0.04, 0.28, 0.74, 1.34), 2), ("front", "skirt", (-0.26, 0.26, 0.30, 1.10), 1),
    ("back", "head", (-0.17, 0.17, 1.32, 1.63), 3), ("back", "sleeve_l", (-0.28, -0.04, 0.74, 1.34), 2),
    ("back", "sleeve_r", (0.04, 0.28, 0.74, 1.34), 2), ("back", "skirt", (-0.26, 0.26, 0.30, 1.10), 1),
    ("left", "head", (-0.16, 0.14, 1.32, 1.63), 3), ("left", "cardigan", (-0.20, 0.16, 0.85, 1.40), 2),
    ("left", "skirt", (-0.26, 0.22, 0.30, 1.10), 1),
)

#: The bob's lower edge (its layered tips and their notches, 12-20 mm deep over the tip line at 1.378-1.41) lies
#: below this height (sheet scale); the bell above it.
BOB_TIP_ZONE_Z = 1.43

#: Smoothness: the parts (merged per label, with height zones; a label is a report key, so it has no dot) and the
#: review views (the 3/4 views at +-35 deg and the low view).
SMOOTH_PARTS = (
    ("hair_bob", ("hair.bob", "hair.bob_l", "hair.bob_back", "hair.bob_r"),
     (("bell", BOB_TIP_ZONE_Z, 9.0), ("tips", -1.0, BOB_TIP_ZONE_Z))),
    ("hair_dome", ("hair.dome",)),
    ("hair_fringe", ("hair.lock_sl", "hair.lock_a", "hair.lock_b", "hair.lock_c", "hair.lock_d1", "hair.lock_d2")),
    ("hair_lining", ("hair.lining_l", "hair.lining_r")),
    ("hair_under_locks", ("hair.under_locks_l", "hair.under_locks_r")),
    ("cardigan_sleeve_l", ("cardigan.sleeve_l",)),
    ("cardigan_sleeve_r", ("cardigan.sleeve_r",)),
    ("cardigan_panel", ("cardigan.panel",)),
    ("body_skirt", ("body.skirt",)),
)
SMOOTH_VIEWS = (
    ("three_quarter_left", (35.0, 8.0, "body", 50.0)),
    ("three_quarter_right", (-35.0, 8.0, "body", 50.0)),
    ("low_angle", PRESETS["low_angle"]),
)
#: The faces a dihedral may count are the faces a viewer sees: visible in the whole model from one of the smoothness
#: views or one of the 13 preview presets (each a z-buffer of every part; correction of 2026-10-31: a face buried in
#: the dome or always behind other locks is never shaded, so its dihedral does not count).
VISIBILITY_VIEWS = tuple((f"preset_{k}", v) for k, v in PRESETS.items())

#: The lit side of her face (her right cheek, below the blush strokes, beside the mouth) in the head close-up.
PROBES = (Probe("skin_lit_face", PRESETS["head_front"], (-0.030, -0.095, 1.425), window=7),)

#: The sheet's arm: the wrist (the white sleeve's end, cardigan-off view, SPEC.md appendix) and the shoulder joint the
#: rig places under the sheet's shoulder point (x 0.111 outer edge).  The shoulder-to-wrist angle out from vertical
#: in the front plane is 10.1 deg.
SHEET_WRIST = (0.159, 0.886)
SHEET_SHOULDER = (0.088, 1.285)


def _angle_out(top, bottom) -> float:
    """Degrees out from vertical of the segment ``top -> bottom`` in the front (x, z) plane."""
    return math.degrees(math.atan2(abs(bottom[0] - top[0]), top[1] - bottom[1]))


def extras(model, rig: Rig) -> dict:
    """The pose and clearance numbers the overlay cannot see: the arm angles (rig joints), the finger curl per joint
    (``rig.fingers``) and the smallest distance between each arm (sleeve, cuff, hand) and the skirt on the final
    model (mm)."""
    sh, el, wr = np.asarray(rig.shoulder_joint_pos), np.asarray(rig.elbow_pos), np.asarray(rig.wrist_pos)
    up, fo = el - sh, wr - el
    bend = math.degrees(math.acos(float(np.clip(up @ fo / (np.linalg.norm(up) * np.linalg.norm(fo)), -1.0, 1.0))))
    flex = math.degrees(math.atan2(-fo[1], -fo[2]) - math.atan2(-up[1], -up[2]))
    sheet_angle = _angle_out(SHEET_SHOULDER, SHEET_WRIST)
    model_angle = _angle_out((sh[0], sh[2]), (wr[0], wr[2]))
    by = {p.name: p for p in model.parts}
    skirt = [by[n].mesh for n in by if n == "body.skirt" or n.startswith("body.skirt_valley")]
    clear = {}
    if skirt:
        sk = mk.merge(*skirt)
        for s in ("l", "r"):
            arm = [by[n].mesh for n in (f"cardigan.sleeve_{s}", f"cardigan.cuff_{s}", f"limbs.palm_{s}",
                                        f"limbs.fingers_{s}") if n in by]
            if arm:
                clear[s] = round(mesh_distance(mk.merge(*arm), sk) * 1000.0, 2)
    return {
        "arm": {"shoulder_to_wrist_deg": round(model_angle, 2), "sheet_shoulder_to_wrist_deg": round(sheet_angle, 2),
                "excess_deg": round(model_angle - sheet_angle, 2), "elbow_bend_deg": round(bend, 2),
                "elbow_flexion_deg": round(flex, 2), "wrist_x_vs_sheet_mm": round((wr[0] - SHEET_WRIST[0])
                                                                                  * rig.figure_scale * 1000.0, 2)},
        "fingers": {row[0]: row[6] for row in rig.fingers},
        "sleeve_skirt_clearance_mm": clear,
    }


def _views(path, views=("front", "back")):
    return tuple(f"views.{v}.{path}" for v in views)


_3V = "smoothness.{}.outline.*"
#: The finishing pass's criteria (each one's sentence and grounds are in it; the overlay section of
#: ``tools/reiya_model/README.md`` and SPEC.md Decision 31 explain them; P1 = must pass, P2 = should pass).  The
#: overlay's own precision: the sheet's ink line is 3-4 px (about 2 mm) and part of its silhouette, one sheet pixel
#: is 0.60 mm on the final model, and the views are near-orthographic, not exact.
#: Exempt by Decision: the profile's front hair edge and fringe (8), the hem's curve (9), the eye wrap (4), the side
#: view's sleeve drape (15); the sheet's left-right asymmetry (27) is cancelled by the half-width errors.
CRITERIA = (
    # hair
    Criterion("H1", "P1 the bob's outer outline (crown to tips, z 1.41-1.575) within 4 mm of the sheet's at every row, "
              "front and back", _views("outlines.hair.left.max") + _views("outlines.hair.right.max"), "<=", 4.0,
              "baseline 3.6 / 3.0 mm: the bob's volume already matches; keep it while smoothing"),
    Criterion("H2", "P1 per side, the lowest bob tip (|x| 0.085-0.125, outside the braids) within 3 mm of the sheet's "
              "in height, front and back", tuple(f"views.{v}.landmarks.bob_tip_{s}.dz_mm" for v in ("front", "back")
                                                 for s in ("l", "r")), "abs<=", 3.0,
              "baseline 4.2-5.4 mm (the model's tips hang lower)"),
    Criterion("H3", "P1 the bob's lower edge at the sides (|x| 0.085-0.125) per column: mean offset <= 6 mm, front and "
              "back", _views("lower_edges.bob_tips.mean"), "<=", 6.0, "baseline 10.1 / 11.0 mm"),
    Criterion("H4", "P1 ... and 95 % of those columns within 15 mm (tapered locks where the sheet draws them, no "
              "regular sawtooth)", _views("lower_edges.bob_tips.p95"), "<=", 15.0, "baseline 32.5 / 40.5 mm"),
    Criterion("H5", "P2 the nape (the back's lowest hair at the centre) within 4 mm of the sheet's in height",
              ("views.back.landmarks.nape.dz_mm",), "abs<=", 4.0, "baseline 7.2 mm (the model's centre is higher)"),
    Criterion("H6", "P2 the back hem at the centre (|x| < 0.035) per column: mean offset <= 5 mm",
              ("views.back.lower_edges.bob_nape.mean",), "<=", 5.0, "baseline 6.3 mm"),
    Criterion("H7", "P1 the ear tufts' tips within 3 mm of the sheet's, front and back",
              tuple(f"views.{v}.landmarks.tuft_tip_{s}.d_mm" for v in ("front", "back") for s in ("l", "r")),
              "<=", 3.0, "baseline 0.7-2.4 mm"),
    Criterion("H8", "P1 the ear tufts' outer outline within 5 mm at every row, front and back",
              _views("outlines.tuft_l.*.max") + _views("outlines.tuft_r.*.max"), "<=", 5.0,
              "baseline 2.4-4.8 mm"),
    Criterion("H9", "P1 the fringe's centre lock B: its tip (the bang line) within 2 mm in height",
              ("views.front.landmarks.bang_line.dz_mm",), "abs<=", 2.0, "baseline 0.0 mm"),
    Criterion("H10", "P1 the fringe's lower edge per column: mean offset <= 3 mm",
              ("views.front.lower_edges.fringe.mean",), "<=", 3.0, "baseline 2.6 mm"),
    Criterion("H11", "P2 hair IoU >= 0.80 front", ("views.front.iou.hair",), ">=", 0.80,
              "baseline 0.786 (the tips; the sheet's strand lines and highlights are filled up to 1500 px)"),
    Criterion("H12", "P2 hair IoU >= 0.90 back", ("views.back.iou.hair",), ">=", 0.90, "baseline 0.909"),
    Criterion("H13", "P2 hair IoU >= 0.75 in profile (Decision 8: the fringe and the bob's front edge lie closer to "
              "the face than drawn)", ("views.left.iou.hair",), ">=", 0.75, "baseline 0.774"),
    Criterion("H14", "P1 in profile, the bob's back outline within 5 mm in 95 % of its rows (its front edge is exempt, "
              "Decision 8)", ("views.left.outlines.hair_back.right.p95",), "<=", 5.0, "baseline 4.1 mm"),
    # sleeves
    Criterion("S1", "P1 the sleeve balloon's outer outline (z 0.90-1.20): half-width error <= 6 mm at every row, front "
              "and back", _views("outlines.sleeve.width.max"), "<=", 6.0,
              "baseline 9.9 / 10.2 mm; the half-width cancels the sheet's 15 mm left-right difference (Decision 27)"),
    Criterion("S2", "P1 the balloon rounds in over the cuff: the cuff's outer outline (z 0.84-0.90) half-width error "
              "<= 8 mm in 95 % of the rows, front and back", _views("outlines.cuff.width.p95"), "<=", 8.0,
              "baseline 32.8 / 12.6 mm (the model's sleeve runs straight out to the cuff's end)"),
    Criterion("S3", "P1 each balloon is widest within 15 mm of the sheet's height (z 0.89-0.905), front and back",
              tuple(f"views.{v}.landmarks.sleeve_widest_{s}.dz_mm" for v in ("front", "back") for s in ("l", "r")),
              "abs<=", 15.0, "baseline 27-43 mm: the model's widest point is at the cuff's top (z 0.86, the window's "
              "bottom)"),
    Criterion("S4", "P2 the sleeve's inner edge beside the skirt (z 0.90-0.99): mean offset <= 8 mm per side, front "
              "and back", _views("outlines.sleeve_inner.left_inner.mean") + _views(
                  "outlines.sleeve_inner.right_inner.mean"), "<=", 8.0, "baseline 0.3-3.8 mm, back right 20.2 mm"),
    # skirt and figure
    Criterion("K1", "P1 the skirt's flare within 5 mm at every row (front, back z 0.43-0.84; profile front 0.43-1.00, "
              "back 0.43-0.80; the hem's curve is exempt, Decision 9)",
              _views("outlines.skirt.left.max") + _views("outlines.skirt.right.max")
              + ("views.left.outlines.skirt_front.left.max", "views.left.outlines.skirt_back.right.max"), "<=", 5.0,
              "baseline 3.0-4.2 mm"),
    Criterion("F1", "P1 figure IoU >= 0.92 front and back", _views("iou.figure"), ">=", 0.92, "baseline 0.933 / 0.930"),
    Criterion("F2", "P1 figure IoU >= 0.90 in profile", ("views.left.iou.figure",), ">=", 0.90, "baseline 0.919"),
    Criterion("F3", "P1 the legs' silhouette within 3 mm at every row, front and back", _views("silhouette.legs.max"),
              "<=", 3.0, "baseline 1.2 mm"),
    Criterion("F4", "P1 the shoes' silhouette within 10 mm at every row, front and back",
              _views("silhouette.shoes.max"), "<=", 10.0, "baseline 6.0 / 9.0 mm"),
    Criterion("F5", "P2 the shoulders' half-width error <= 8 mm in 95 % of the rows (z 1.20-1.335), front and back",
              _views("silhouette.shoulders.width.p95"), "<=", 8.0, "baseline 6.1 / 6.6 mm"),
    # pose and hands
    Criterion("A1", "P1 the arms no further out than the sheet's: shoulder-to-wrist angle within the sheet's "
              "10.1 deg -2 / +0.5 deg (front plane)", ("extras.arm.excess_deg",), "between", (-2.0, 0.5),
              "baseline +1.5 deg (the wrist 10.8 mm further out, Decision 16)"),
    Criterion("A2", "P1 the fingers curled 10-30 deg at each joint", ("extras.fingers.*",), "between", (10.0, 30.0),
              "baseline 6 / 8 / 8 / 10 / 12 deg (thumb to little finger)"),
    Criterion("A3", "P1 a small elbow bend: 10-25 deg between the upper arm and the forearm",
              ("extras.arm.elbow_bend_deg",), "between", (10.0, 25.0), "baseline 18.9 deg"),
    Criterion("A4", "P1 the hands stay where the sheet draws them: the lowest fingertip within 8 mm (dh and dz) per "
              "side, front and back", tuple(f"views.{v}.landmarks.hand_tip_{s}.{a}" for v in ("front", "back")
                                            for s in ("l", "r") for a in ("dh_mm", "dz_mm")), "abs<=", 8.0,
              "baseline <= 4.2 mm"),
    Criterion("A5", "P1 the sleeves clear the skirt by >= 8 mm", ("extras.sleeve_skirt_clearance_mm.*",), ">=", 8.0,
              "baseline 10.0 mm"),
    Criterion("C1", "P1 the skin reads warm: lit-side face R - B >= 15 in the shaded head close-up",
              ("probes.skin_lit_face.r_minus_b",), ">=", 15, "baseline 21 (after the #fae3d8 skin), 27 with #fad8cd"),
    # smoothness
    Criterion("M1", "P1 the bob's bell (above z 1.43) has no outline turn > 20 deg in three_quarter_left / right and "
              "low_angle (tips over 60 deg excluded)", (_3V.format("hair_bob") + ".zones.bell.max",), "<=", 20.0,
              "baseline 12.1 / 12.1 / 16.5 deg (v1, the bob alone: 16.9 / 48.1 / 54.1: its top rim, buried in the "
              "dome)"),
    Criterion("M2", "P1 the bob's outline: 95 % of its turns <= 15 deg in each of the three views",
              (_3V.format("hair_bob") + ".p95",), "<=", 15.0,
              "baseline 28.4 / 28.4 / 54.5 deg: the sawtooth tips' notches seen obliquely (v1 28.0 / 29.3 / 54.1)"),
    Criterion("M3", "P1 the bob's bell: the largest dihedral inside one smooth group <= 25 deg (strand grooves are "
              "group boundaries, excluded; folds over 60 deg excluded)",
              ("smoothness.hair_bob.dihedral.zones.bell.max",), "<=", 25.0, "baseline 38.3 deg (v1 42.9)"),
    Criterion("M4", "P1 the bob's bell: 95 % of its dihedrals inside one smooth group <= 12 deg",
              ("smoothness.hair_bob.dihedral.zones.bell.p95",), "<=", 12.0, "baseline 23.9 deg (v1 24.0)"),
    Criterion("M5", "P1 the lavender lining adds no kink: its outline turns <= 25 deg in the three views (its ends, "
              "tips over 60 deg, excluded)", (_3V.format("hair_lining") + ".max",), "<=", 25.0,
              "baseline - / - / 31.1 deg: hidden in the 3/4 views, a kink seen from below (v1 40.4 / 40.4 / 40.1)"),
    Criterion("M6", "P1 the sleeves: outline turns <= 30 deg in the three views",
              (_3V.format("cardigan_sleeve_l") + ".max", _3V.format("cardigan_sleeve_r") + ".max"), "<=", 30.0,
              "baseline 24.2-50.6 deg (v1 37-53)"),
    Criterion("M7", "P1 the sleeves: 95 % of the outline turns <= 20 deg in the three views",
              (_3V.format("cardigan_sleeve_l") + ".p95", _3V.format("cardigan_sleeve_r") + ".p95"), "<=", 20.0,
              "baseline 23.6-45.0 deg (v1 25.7-37.4; fewer, visible vertices)"),
    Criterion("M8", "P1 the sleeves: 95 % of the dihedrals inside one smooth group <= 25 deg",
              ("smoothness.cardigan_sleeve_l.dihedral.p95", "smoothness.cardigan_sleeve_r.dihedral.p95"), "<=", 25.0,
              "baseline 43.2 deg (v1 42.3)"),
    Criterion("M9", "P1 the sleeves: the largest dihedral inside one smooth group <= 40 deg",
              ("smoothness.cardigan_sleeve_l.dihedral.max", "smoothness.cardigan_sleeve_r.dihedral.max"), "<=", 40.0,
              "baseline 47.9 deg (v1 53.0)"),
    Criterion("M10", "P2 the dome (the crown): outline turns <= 30 deg in the three views",
              (_3V.format("hair_dome") + ".max",), "<=", 30.0,
              "baseline 32.5 / 32.5 / 17.0 deg (v1 42.7 / 42.7 / 36.2)"),
    Criterion("M11", "P2 the dome: 95 % of the dihedrals inside one smooth group <= 25 deg",
              ("smoothness.hair_dome.dihedral.p95",), "<=", 25.0, "baseline 33.8 deg (v1 37.7)"),
)

SPEC = OverlaySpec(
    sheet=SHEET, figure_scale=lambda rig: rig.figure_scale, material_classes=MATERIAL_CLASSES, bands=BANDS,
    iou_classes=IOU_CLASSES, outlines=OUTLINES, lower_edges=LOWER_EDGES, landmarks=LANDMARKS, zooms=ZOOMS,
    smooth_parts=SMOOTH_PARTS, smooth_views=SMOOTH_VIEWS, cameras=cameras, materials=MATERIALS, light=SUN_TOWARDS,
    probes=PROBES, extras=extras, criteria=CRITERIA, tip_deg=60.0, min_seg_px=1.0, ref_px=1200,
    visible_only=True, visibility_views=VISIBILITY_VIEWS, visibility_ss=2.0,
    outline_classes=("hair",), max_hole_px=1500,
    notes=("Reiya vs her design sheet (三面図); views front (正面), left (よこ, her left profile: image left = her "
           "front), back (後ろ) and the cardigan-off front (カーディガンOFF, the model without its cardigan: "
           "informational, the model has no upper arms under the sleeves)",
           "the sheet's ink lines (~3-4 px, about 2 mm) are part of its silhouette; the views are near-orthographic, "
           "not exact (the lower body is drawn as if from slightly above: the hem and the shoes curve, Decision 9)"))
