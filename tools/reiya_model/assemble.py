"""Parts -> the castplane mesh objects of the Reiya model (fixed order): Reiya's character description.

The machinery (rounding, validation, the per-object merge, statistics, budget checks) is character-free and lives
in :mod:`charmodel.assembly`; this module holds Reiya's data (:data:`OBJECTS`, :data:`MATERIALS`,
:data:`DISPLAY_MATERIALS`, :data:`REGION_OBJECTS`, :data:`MODULES`, :data:`BUDGET`, :data:`DECIMALS`), the
:class:`~charmodel.assembly.Character` built from it (:data:`CHARACTER`) and thin wrappers with the public
names the CLI (``tools/make_reiya_model.py``) and the tests import.

Flow: :func:`build_parts` asks each part module (``head``, ``hair``, ``body``, ``cardigan``, ``limbs``) for its
parts; a module whose ``build(rig)`` returns ``None`` is replaced by the mannequin parts of its ``REGIONS``.
Every part names a **material** (its colour, :data:`MATERIALS`) and goes into one **object** (``Part.obj``,
default :data:`REGION_OBJECTS` of its region).  Objects are spatially compact groups of parts (SPEC.md §G):
castplane's hidden-line pass tests a sample only against objects whose image rectangle contains it, and its
construction-ray cap (64 feature silhouette vertices, ``MESH_RAYS_CAPPED``) counts per object.
:func:`assemble` rounds every part to :data:`DECIMALS`, validates it (closed outward manifold shells, no
tiny faces, no vertex below the ground), merges the parts per object in :data:`OBJECTS` order (renumbering
smooth groups per part so different parts never share a group id, and keeping each part's face range and
material for the exporters), reorders vertices so castplane's nesting-parity test cannot flip an
overlapping shell (:func:`charmodel.meshkit.fix_nesting`), validates each object again (duplicate vertices
across parts) and returns an :class:`Assembly` with the castplane object dicts and per-part / per-object
statistics.  The builders work at the design sheet's scale; :func:`build_parts` scales every part by
:func:`figure_scale` (``rig.figure_scale``, 0.97749: her stated 1.52 m) before the rounding.
"""

from __future__ import annotations

from charmodel import assembly as _asm
from charmodel.assembly import Assembly, AssemblyError

from . import body, cardigan, hair, head, limbs, mannequin
from .rig import SUN_TOWARDS, Rig

__all__ = ["OBJECTS", "OBJECT_IDS", "MATERIALS", "DISPLAY_MATERIALS", "display_color", "REGION_OBJECTS", "MODULES",
           "ALL_REGIONS", "BUDGET", "DECIMALS", "SUN_TOWARDS", "CHARACTER", "Assembly", "AssemblyError", "build_parts",
           "assemble", "format_stats", "figure_scale"]

#: The castplane objects in their fixed order (SPEC.md §G) with what each holds.  ``tufts`` comes first: the web
#: UI's observer pane draws its sight rays (視線) for every vertex of ``objects[0]``, and the two ear tufts (about
#: 150 vertices, the first thing people recognise) show their perspective without hiding the figure.  After it the
#: order is outer layers first, top to bottom (the cardigan and the arms, the face, the hair and head, the clothes
#: under the cardigan, the skirt, the feet): castplane's hidden-line pass tests a sample against the occluders in
#: this order and stops at the first that hides it, so the objects that hide the most lines come early.  The
#: objects are small and compact (the fringe, the bob and its lavender under-layer are objects of their own, the bob
#: cut into three shells along its outer back strand lines; each eye, each side's face marks, each braid, arm, shoe
#: and sock is an object per side): a sample is tested only against the objects whose image rectangle contains it, so
#: splitting a large object where its parts lie apart saves most of the web still frame's hidden-line time.  Every
#: object carries ``display_color`` (D81), so the order does not pick the 3D colours.
OBJECTS = (
    ("tufts", "the two ear tufts H5 with their lighter inner-face decals"),
    ("cardigan", "back + 2 fronts, front / neck bands, plain hem band"),
    ("arm_l", "her left balloon sleeve with its ribbed cuff, hand + 5 fingers"),
    ("arm_r", "her right balloon sleeve with its ribbed cuff, hand + 5 fingers"),
    ("face_marks_l", "her left lash band with its flick, brow and 3 blush strokes, and the mouth"),
    ("face_marks_r", "her right lash band with its flick, brow and 3 blush strokes"),
    ("eye_l", "her left eye: sclera, blue iris, pupil, highlight"),
    ("eye_r", "her right eye: sclera, red iris, pupil, highlight"),
    ("fringe", "fringe H2: swept lock SL, locks A-C, lock D as two plates"),
    ("neck", "neck"),
    ("bob_l", "the bob H3's left side: her left curtain, side lock and back locks out to the outer back strand"),
    ("bob_r", "the bob H3's right side: her right curtain, side lock and back locks out to the outer back strand"),
    ("bob", "the bob H3's back between the two outer back strands, down to the nape"),
    ("hair", "dome H1"),
    ("head", "skin head with the nose bump"),
    ("braid_l", "her left braid H6: 5 pointed lobes, tie, 3-lock end tuft"),
    ("braid_r", "her right braid H6: 5 pointed lobes, tie, 3-lock end tuft"),
    ("hair_under", "the lavender under-layer H4: a lining strip inside each curtain's lower edge (ending in front of "
                   "the braid root), one 2-tooth under-lock per side"),
    ("top", "mock neck with the lettuce rim, its flare and the fold at its base, shoulders / upper chest"),
    ("bodice", "bodice (square-neckline rim, high-waist seam edge, placket creases), 2 straps"),
    ("buttons", "17 teardrop dress buttons, the cardigan's round button"),
    ("skirt", "fluted A-line skirt (placket creases), hem rim, inner facing, ceiling, 8 flute-valley line stripes"),
    ("shoe_l", "her left penny loafer (sole, block heel, upper, saddle strap with the penny slot, apron seam)"),
    ("shoe_r", "her right penny loafer"),
    ("sock_l", "her left sock, its cuff fold and star"),
    ("sock_r", "her right sock, its cuff fold and star"),
    ("legs", "legs x2"),
)

#: Materials (sRGB colours for the MTL, GLB and shaded previews; SPEC.md §H, sampled on the design sheet), in a fixed
#: order.
MATERIALS = {
    "hair": "#f2b5a7",             # palette swatch 1 (hair pink)
    "hair_inner": "#e1d7ef",       # lavender under the side hair (the under-layer H4)
    "tuft_inner": "#ffdfd2",       # the ear tufts' inner faces
    "skin": "#fad8cd",             # rosy warm mid-tone (Decision 33; #fae3d8 before, Decision 30)
    "eye_white": "#ffffff",        # sclera and highlights
    "iris_red": "#d25754",         # her right iris (middle tone)
    "pupil_red": "#9f2a29",        # its dark top
    "iris_blue": "#6387a6",        # her left iris (palette swatch 6, steel blue)
    "pupil_blue": "#2a3944",       # its dark top
    "lashes": "#3f2924",           # upper lash bands
    "face_marks": "#8d5946",       # brows, mouth, blush strokes
    "top": "#f2f2f2",              # white mock-neck top
    "dress": "#184059",            # palette swatch 5 (dress navy)
    "buttons": "#d99559",          # palette swatch 3 (button gold): the dress buttons and the cardigan button
    "cardigan": "#a66b63",         # palette swatch 2 (cardigan brown)
    "socks": "#f2f2f2",
    "star": "#173449",             # the navy sock star
    "shoes": "#91643c",            # palette swatch 4 (loafer brown)
}

#: Display material of each object (its dominant material, SPEC.md §H): ``display_color(oid)`` is that material's
#: colour, written as the object's optional ``display_color`` key in examples/reiya.json.  The web UI's 3D views draw
#: the object in it (instead of the index palette); castplane's core ignores the key (contract §2.0).
DISPLAY_MATERIALS = {
    "tufts": "hair", "cardigan": "cardigan", "arm_l": "cardigan", "arm_r": "cardigan", "face_marks_l": "lashes",
    "face_marks_r": "lashes", "eye_l": "eye_white", "eye_r": "eye_white", "fringe": "hair", "neck": "skin",
    "bob_l": "hair", "bob_r": "hair", "bob": "hair", "hair": "hair", "head": "skin", "braid_l": "hair",
    "braid_r": "hair", "hair_under": "hair_inner",
    "top": "top", "bodice": "dress", "buttons": "buttons", "skirt": "dress", "shoe_l": "shoes", "shoe_r": "shoes",
    "sock_l": "socks", "sock_r": "socks", "legs": "skin",
}

#: Default object of a part by its region (``Part.obj`` overrides it; SPEC.md §G): of the ``hair`` region the fringe
#: sets ``obj="fringe"``, the bob's three shells ``obj="bob_l"`` / ``"bob"`` (the back) / ``"bob_r"`` and the lavender
#: under-layer ``obj="hair_under"``; the skirt of the ``dress`` region sets ``obj="skirt"``; the white sleeve tubes of
#: ``top`` (off by default) go to their arm, the cardigan's button to ``buttons``.  ``None``: the region has no default
#: and every part must set ``obj`` (``sleeves`` and ``hands`` go to ``arm_l`` or ``arm_r``, ``socks`` to ``sock_l`` /
#: ``sock_r``, ``shoes`` to ``shoe_l`` / ``shoe_r``, ``eyes`` to ``eye_l`` / ``eye_r``, ``face_marks`` to
#: ``face_marks_l`` (with the mouth) / ``face_marks_r`` and ``braids`` to ``braid_l`` / ``braid_r`` by side: one compact
#: object per side keeps the hidden-line pass from testing one side's lines against the other side, and the two sides'
#: ground shadows do not overlap, so the shadow draws the same).
REGION_OBJECTS = {
    "head": "head", "eyes": None, "face_marks": None,
    "hair": "hair", "tufts": "tufts", "braids": None,
    "neck": "neck", "top": "top", "dress": "bodice", "buttons": "buttons",
    "cardigan": "cardigan", "sleeves": None,
    "hands": None, "legs": "legs", "socks": None, "shoes": None,
}

#: Part modules in assembly order (each defines ``REGIONS`` and ``build(rig)``).
MODULES = (head, hair, body, cardigan, limbs)

#: Web-UI budget, the limits ``--check`` enforces: polygons = faces as written, triangles = castplane's fan
#: triangulation; the third limit, at most 64 feature silhouette vertices per object (castplane's ray cap,
#: ``MESH_RAYS_CAPPED``), is ``charmodel.meshkit.MAX_FEATURE_SILHOUETTE_VERTICES`` and stays a hard rule.  Until the
#: finishing pass the limits were Miki's 6000 / 10000; what counts is that the web still frame is no slower than
#: Miki's (SPEC.md §G, Decision 32).
#: Decided by the user on 2026-11-01 ("keep the raised cap and the split, add leaf-shaped tips"): the finishing
#: pass's raise stays.  The finishing pass (2026-10-31) had 6216 polygons / 10396 triangles under 6500 / 10500 (the
#: head and hair +644 triangles for the smooth bob, the balloon sleeves +188, the body -308 with the options B and F,
#: the bob's three-shell cut +56), with its web still frame no slower than Miki's (cost model 19.3 M ray-triangle
#: tests against Miki's 21.7 M; the alternating web bench in SPEC.md Decision 32).  The leaf-shaped lock ends (SPEC.md
#: §C.3) add +148 polygons / +196 triangles: 6364 / 10592, so the triangles limit is the smallest multiple of 100
#: that fits, 10600; the polygons stay 6500.
BUDGET = {"polygons": 6500, "triangles": 10600}

#: Coordinates are rounded to this many decimals (0.01 mm) before validation and writing.
DECIMALS = 5


def figure_scale(rig: Rig) -> float:
    """The uniform scale of the assembled model: ``rig.figure_scale`` (her stated height 1.52 m over the sheet's skin
    height 1.555 m; SPEC.md Decision 1).  The builders work at the sheet scale; :func:`charmodel.assembly.build_parts`
    scales every part (the mannequin's too) about the origin before the rounding, so a ``--rig`` override of
    ``stated_height`` rescales the model."""
    return rig.figure_scale


#: Reiya's character description for :mod:`charmodel` (its constructor checks that the mannequin regions, the module
#: ``REGIONS``, :data:`REGION_OBJECTS`, :data:`DISPLAY_MATERIALS` and :data:`MATERIALS` agree).  ``scale`` is
#: :func:`figure_scale`: the parts are built at the design sheet's scale and scaled to her stated height.
CHARACTER = _asm.Character(
    name="reiya", objects=OBJECTS, materials=MATERIALS, display_materials=DISPLAY_MATERIALS,
    region_objects=REGION_OBJECTS, modules=MODULES, mannequin=mannequin, rig_factory=Rig, sun_towards=SUN_TOWARDS,
    budget=BUDGET, decimals=DECIMALS, scale=figure_scale)

OBJECT_IDS = CHARACTER.object_ids
ALL_REGIONS = CHARACTER.all_regions


def display_color(oid: str) -> str:
    """Lower-case ``"#rrggbb"`` display colour of object ``oid`` (:data:`DISPLAY_MATERIALS`)."""
    return CHARACTER.display_color(oid)


def build_parts(rig: Rig, only=None):
    """``(parts, sources)``: the parts of every region (or of the regions in ``only``) with ``obj``
    resolved, and which module built each region.  ``only`` may also name a module (``head``, ``hair``,
    ``body``, ``cardigan``, ``limbs``)."""
    return _asm.build_parts(CHARACTER, rig, only)


def assemble(rig: Rig | None = None, only=None, strict: bool = True) -> Assembly:
    """Build, round, validate and merge the model.  ``strict`` raises :class:`AssemblyError` listing every
    invalid part / object; otherwise the reports are kept on the result (``Assembly.ok``)."""
    return _asm.assemble(CHARACTER, rig, only, strict)


def format_stats(stats: dict, parts: bool = True) -> str:
    """Plain-text table of :func:`assemble` statistics (per part, per object, total vs budget)."""
    return _asm.format_stats(stats, OBJECT_IDS, parts)
