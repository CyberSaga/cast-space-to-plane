"""Parts -> the 18 castplane mesh objects of the Miki model (fixed order): Miki's character description.

The machinery (rounding, validation, the per-object merge, statistics, budget checks) is character-free and lives
in :mod:`charmodel.assembly`; this module holds Miki's data (:data:`OBJECTS`, :data:`MATERIALS`,
:data:`DISPLAY_MATERIALS`, :data:`REGION_OBJECTS`, :data:`MODULES`, :data:`BUDGET`, :data:`DECIMALS`), the
:class:`~charmodel.assembly.Character` built from it (:data:`CHARACTER`) and thin wrappers with the public
names the CLI and ``tests/test_miki_model.py`` import.

Flow: :func:`build_parts` asks each part module (``head``, ``hair``, ``body``, ``limbs``) for its parts;
a module whose ``build(rig)`` returns ``None`` is replaced by the mannequin parts of its ``REGIONS``.
Every part names a **material** (its colour, :data:`MATERIALS`) and goes into one **object** (``Part.obj``,
default :data:`REGION_OBJECTS` of its region).  Objects are spatially compact groups of parts: castplane's
hidden-line pass tests a sample only against objects whose image rectangle contains it, and its
construction-ray cap (64 feature silhouette vertices, ``MESH_RAYS_CAPPED``) counts per object.
:func:`assemble` rounds every part to :data:`DECIMALS`, validates it (closed outward manifold shells, no
tiny faces, no vertex below the ground), merges the parts per object in :data:`OBJECTS` order (renumbering
smooth groups per part so different parts never share a group id, and keeping each part's face range and
material for the exporters), reorders vertices so castplane's nesting-parity test cannot flip an
overlapping shell (:func:`meshkit.fix_nesting`), validates each object again (duplicate vertices across
parts) and returns an :class:`Assembly` with the castplane object dicts and per-part / per-object
statistics.
"""

from __future__ import annotations

from charmodel import assembly as _asm
from charmodel.assembly import Assembly, AssemblyError

from . import body, hair, head, limbs, mannequin
from .rig import SUN_TOWARDS, Rig

__all__ = ["OBJECTS", "OBJECT_IDS", "MATERIALS", "DISPLAY_MATERIALS", "display_color", "REGION_OBJECTS", "MODULES",
           "ALL_REGIONS", "BUDGET", "DECIMALS", "SUN_TOWARDS", "CHARACTER", "Assembly", "AssemblyError", "build_parts",
           "assemble", "format_stats"]

#: The castplane objects in their fixed order with what each holds.  ``headband`` comes first: the web UI's
#: observer pane draws its sight rays (視線) for every vertex of ``objects[0]``, and the headband's 120
#: vertices show its perspective without hiding the figure (the 324-vertex hair did).  Every object carries
#: ``display_color`` (D81), so the order no longer picks the 3D colours from the index palette.
OBJECTS = (
    ("headband", "band, pink centre ridge"),
    ("hair", "dome H1, bangs H3, stray strand H5"),
    ("head", "head + face skin"),
    ("eyes", "sclera, iris, pupil, highlight"),
    ("scarf", "ribbons, tips"),
    ("sidelocks", "sidelocks H4 x2"),
    ("blouse", "torso / blouse"),
    ("collar", "collar, dickey, collar pink stripe"),
    ("back_hair", "side curtain + back sheet H2"),
    ("arm_l", "her left sleeve with its cuff rim, 2 cuff white stripes, hand + thumb"),
    ("face_marks", "brows, upper-lid bands, lower-lid marks, mouth"),
    ("arm_r", "her right sleeve with its cuff rim, 2 cuff white stripes, hand + thumb"),
    ("legs", "legs x2"),
    ("socks", "socks x2"),
    ("skirt", "skirt, under-skirt block"),
    ("shoes", "shoes x2"),
    ("ring", "scarf ring, its two pink stripes"),
    ("neck", "neck + decollete bib"),
)

#: Materials (sRGB colours for the MTL, GLB and shaded previews), in a fixed order.
MATERIALS = {
    "hair": "#b9c3e6",
    "skin": "#fbe3d6",
    "eye_white": "#ffffff",
    "iris": "#7fb3a8",
    "pupil": "#2f5c57",
    "headband": "#f4dce8",
    "scarf": "#f6c453",
    "socks": "#f2f0f4",
    "uniform": "#e8667a",          # also every pink stripe
    "skirt": "#f5b9c6",
    "collar": "#fafafa",           # also the white cuff stripes, the ring, the dickey
    "face_marks": "#4b3434",
    "shoes": "#6b4a3a",
}

#: Display material of each object (its dominant material): ``display_color(oid)`` is that material's colour,
#: written as the object's optional ``display_color`` key in examples/miki.json.  The web UI's 3D views draw
#: the object in it (instead of the index palette); castplane's core ignores the key (contract §2.0).
DISPLAY_MATERIALS = {
    "headband": "headband", "hair": "hair", "head": "skin", "eyes": "iris", "scarf": "scarf",
    "sidelocks": "hair", "blouse": "uniform", "collar": "collar", "back_hair": "hair", "arm_l": "uniform",
    "face_marks": "face_marks", "arm_r": "uniform", "legs": "skin", "socks": "socks", "skirt": "skirt",
    "shoes": "shoes", "ring": "collar", "neck": "skin",
}

#: Default object of a part by its region (``Part.obj`` overrides it: e.g. ``hair`` parts that are
#: sidelocks go to ``sidelocks``, the back hair to ``back_hair``, the scarf ring to ``ring``).  ``None``:
#: the region has no default and every part must set ``obj`` (``arms`` / ``hands`` go to ``arm_l`` or
#: ``arm_r`` by side: one compact object per arm keeps the hidden-line pass from testing hand-to-hand
#: image rectangles).  The neck and the bib are their own compact object (review round 1, appended so the
#: other indices keep their palette colours): the head's image rectangle then ends at the chin and the
#: blouse's triangles are not tested by the collar / neck samples twice.
REGION_OBJECTS = {
    "head": "head", "eyes": "eyes", "face_marks": "face_marks",
    "hair": "hair", "headband": "headband",
    "neck": "neck", "torso": "blouse", "collar": "collar", "scarf": "scarf", "skirt": "skirt",
    "arms": None, "hands": None, "legs": "legs", "socks": "socks", "shoes": "shoes",
}

#: Part modules in assembly order (each defines ``REGIONS`` and ``build(rig)``).
MODULES = (head, hair, body, limbs)

#: Web-UI budget (SPEC.md §G): polygons = faces as written, triangles = castplane's fan triangulation.
BUDGET = {"polygons": 6000, "triangles": 10000}

#: Coordinates are rounded to this many decimals (0.01 mm) before validation and writing.
DECIMALS = 5

#: Miki's character description for :mod:`charmodel` (its constructor checks that the mannequin regions, the
#: module ``REGIONS``, :data:`REGION_OBJECTS`, :data:`DISPLAY_MATERIALS` and :data:`MATERIALS` agree).
CHARACTER = _asm.Character(
    name="miki", objects=OBJECTS, materials=MATERIALS, display_materials=DISPLAY_MATERIALS,
    region_objects=REGION_OBJECTS, modules=MODULES, mannequin=mannequin, rig_factory=Rig, sun_towards=SUN_TOWARDS,
    budget=BUDGET, decimals=DECIMALS)

OBJECT_IDS = CHARACTER.object_ids
ALL_REGIONS = CHARACTER.all_regions


def display_color(oid: str) -> str:
    """Lower-case ``"#rrggbb"`` display colour of object ``oid`` (:data:`DISPLAY_MATERIALS`)."""
    return CHARACTER.display_color(oid)


def build_parts(rig: Rig, only=None):
    """``(parts, sources)``: the parts of every region (or of the regions in ``only``) with ``obj``
    resolved, and which module built each region.  ``only`` may also name a module (``head``, ``hair``,
    ``body``, ``limbs``)."""
    return _asm.build_parts(CHARACTER, rig, only)


def assemble(rig: Rig | None = None, only=None, strict: bool = True) -> Assembly:
    """Build, round, validate and merge the model.  ``strict`` raises :class:`AssemblyError` listing every
    invalid part / object; otherwise the reports are kept on the result (``Assembly.ok``)."""
    return _asm.assemble(CHARACTER, rig, only, strict)


def format_stats(stats: dict, parts: bool = True) -> str:
    """Plain-text table of :func:`assemble` statistics (per part, per object, total vs budget)."""
    return _asm.format_stats(stats, OBJECT_IDS, parts)
