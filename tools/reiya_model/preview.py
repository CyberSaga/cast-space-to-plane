"""Previews of the Reiya model: shaded colour renders and castplane line renders, plus contact sheets.

The renderers are character-free and live in :mod:`charmodel.preview`; this module holds Reiya's camera presets
(:data:`PRESETS`, :data:`BODY_PRESETS`, :data:`HEAD_PRESETS`, :data:`FRAME_MM`), the framing numbers taken from
her rig (:func:`cameras`) and thin wrappers that pass her materials, sun and mannequin.  Two independent "eyes"
for builders and reviewers:

* :func:`render_shaded` — a numpy z-buffer rasteriser (Pillow only saves the image): part material colours,
  Lambert shading with normals smoothed inside each smooth group, dark outlines from object / smooth
  group / depth / normal discontinuities, an optional ground plane, and **visible back faces painted
  magenta** (an inverted or open shell shows up immediately).  :func:`shaded_views`,
  :func:`write_shaded_previews` render the camera presets and contact sheets.
* :func:`castplane_views` — the real thing: the scene rendered by castplane (stage A once, then stages
  B + C per camera, hidden lines omitted), SVG -> PNG with cairosvg, warnings collected per view.

Camera presets (:data:`PRESETS`, the same names and angles as Miki's): ``front``, ``back``, ``left`` (camera on her
left, +X), ``right`` (on -X), ``three_quarter_left``, ``three_quarter_right``, ``three_quarter_back``, ``top``,
``low_angle`` (looking up at the face) and the head close-ups ``head_front``, ``head_three_quarter``, ``head_side``,
``head_low``.  :func:`camera_for` turns a preset into a castplane camera dict (portrait 24 x 36 mm frame, so it also
fits the scene canvas of ``examples/reiya.json``); both renderers use the same camera.

Inputs: an :class:`~charmodel.assembly.Assembly`, a list of :class:`~charmodel.meshkit.Part`, or a
list of ``(mesh, '#rrggbb', label)`` tuples.
"""

from __future__ import annotations

from charmodel import assembly as _asm
from charmodel import preview as _pv
from charmodel.preview import BACKFACE, BACKGROUND, GROUND, LINE, contact_sheet, side_by_side  # noqa: F401

from . import mannequin
from .assemble import MATERIALS
from .rig import SUN_TOWARDS, Rig

__all__ = ["PRESETS", "BODY_PRESETS", "HEAD_PRESETS", "FRAME_MM", "cameras", "camera_for", "render_shaded",
           "shaded_views", "with_context", "contact_sheet", "side_by_side", "write_shaded_previews", "castplane_views",
           "write_line_previews"]

#: preset -> (azimuth deg (0 = camera in front at -Y, 90 = camera on her left at +X), elevation deg,
#: framing ("body", "upper" or "head"), focal length mm)
PRESETS = {
    "front": (0.0, 3.0, "body", 50.0),
    "back": (180.0, 3.0, "body", 50.0),
    "left": (90.0, 3.0, "body", 50.0),
    "right": (-90.0, 3.0, "body", 50.0),
    "three_quarter_left": (40.0, 8.0, "body", 50.0),
    "three_quarter_right": (-40.0, 8.0, "body", 50.0),
    "three_quarter_back": (140.0, 8.0, "body", 50.0),
    "top": (20.0, 72.0, "body", 50.0),
    "low_angle": (20.0, -22.0, "upper", 50.0),
    "head_front": (0.0, 0.0, "head", 85.0),
    "head_three_quarter": (35.0, 5.0, "head", 85.0),
    "head_side": (-90.0, 0.0, "head", 85.0),          # her right profile (the ground shadow stays in front)
    "head_low": (20.0, -25.0, "head", 85.0),
}
BODY_PRESETS = ("front", "three_quarter_left", "left", "three_quarter_back", "back", "three_quarter_right",
                "right", "top", "low_angle")
HEAD_PRESETS = ("head_front", "head_three_quarter", "head_side", "head_low")

FRAME_MM = (24.0, 36.0)

#: Framing numbers of the head close-ups as fractions of her head height (chin to skull top, ``rig.head_height``,
#: 0.202 at the sheet scale, 0.1975 m final): the target is this far above the chin (the eyes sit low at 0.35, the big
#: bob and the tufts above) ...
HEAD_TARGET_FRACTION = 0.55
#: ... and the framed height is this many head heights (the hair crown at +0.08 and the tuft tips at +0.13 head
#: heights over the skull, the braids' ends below the chin, the bob as wide as the shoulders).
HEAD_FIT_HEADS = 1.65
#: The ``upper`` framing (``low_angle``) starts this far below the high-waist seam (at the sheet scale, like the rig;
#: :func:`cameras` scales both): the bodice, the cropped cardigan and the hands at the crotch level are in the frame.
UPPER_BELOW_SEAM = 0.35


def cameras(rig: Rig | None = None) -> _pv.Cameras:
    """The presets with the framing numbers of ``rig`` at the final scale (the rig's sheet-scale heights times
    ``rig.figure_scale``, as the assembled model is scaled): ``upper`` frames from :data:`UPPER_BELOW_SEAM` below the
    high-waist seam to the top, ``head`` looks at :data:`HEAD_TARGET_FRACTION` of the head height above the chin (on
    the cranium's y) and fits :data:`HEAD_FIT_HEADS` head heights.  The default bounding box (no model given) reaches
    the skull top in her loafers + 3 cm, above the tuft tips."""
    rig = Rig() if rig is None else rig
    f = rig.figure_scale
    head_z = rig.chin_z + HEAD_TARGET_FRACTION * rig.head_height
    return _pv.Cameras(PRESETS, height=rig.height * f, upper_bottom_z=(rig.seam_z - UPPER_BELOW_SEAM) * f,
                       head_target=(0.0, float(rig.head_center[1]) * f, head_z * f),
                       head_fit=HEAD_FIT_HEADS * rig.head_height * f, frame_mm=FRAME_MM)


def camera_for(preset, rig: Rig | None = None, bbox=None) -> dict:
    """castplane camera dict for a preset name (or an ``(azimuth, elevation, framing, focal)`` tuple):
    the camera looks at the framing target from a distance that fits the framed height into the
    36 mm frame height.  ``bbox`` = ``(min, max)`` of the model (default: her standing figure)."""
    return cameras(rig).camera(preset, bbox)


def render_shaded(model, camera: dict, size=(600, 900), supersample: int = 2, ground: bool = True,
                  lines: bool = True, light=None):
    """Shaded colour render of ``model`` (see module docstring) from a castplane camera dict; returns a
    Pillow ``Image`` of ``size`` (width, height).  ``light`` (towards the light) defaults to the scene sun."""
    return _pv.render_shaded(model, camera, materials=MATERIALS, light=SUN_TOWARDS if light is None else light,
                             size=size, supersample=supersample, ground=ground, lines=lines)


class _ScaledMannequin:
    """The mannequin with its parts scaled by ``rig.figure_scale``, as :func:`charmodel.assembly.build_parts` scales
    the model's (the ``--context`` parts must stand where the model's parts would)."""

    REGIONS = mannequin.REGIONS

    @staticmethod
    def build(rig: Rig, regions=None) -> list:
        return _asm.scale_parts(mannequin.build(rig, regions), rig.figure_scale)


def with_context(model, rig: Rig | None = None, colour: str = _pv.CONTEXT_COLOUR):
    """Drawables of ``model`` plus the mannequin parts of every region it does not contain (an
    :class:`Assembly` built with ``only=...``), drawn in a neutral grey: preview one region in context.  The
    mannequin parts are scaled by ``rig.figure_scale`` like the model's."""
    return _pv.with_context(model, Rig() if rig is None else rig, materials=MATERIALS, mannequin=_ScaledMannequin,
                            colour=colour)


def shaded_views(model, presets=BODY_PRESETS, rig: Rig | None = None, size=(400, 600), **kw) -> dict:
    """``{preset: Image}`` of :func:`render_shaded` for each preset."""
    light = kw.pop("light", None)
    return _pv.shaded_views(model, cameras(rig), presets, materials=MATERIALS,
                            light=SUN_TOWARDS if light is None else light, size=size, **kw)


def write_shaded_previews(model, out_dir, rig: Rig | None = None, body=BODY_PRESETS, head=HEAD_PRESETS,
                          size=(400, 600), head_size=(400, 600), singles: bool = True) -> list:
    """Shaded contact sheets ``shaded_body.png`` (``body`` presets) and ``shaded_head.png`` (``head``
    presets) in ``out_dir`` plus one ``shaded_<preset>.png`` per view (``singles``).  Returns the paths."""
    return _pv.write_shaded_previews(model, out_dir, cameras(rig), body, head, materials=MATERIALS, light=SUN_TOWARDS,
                                     size=size, head_size=head_size, singles=singles)


def castplane_views(scene, presets=BODY_PRESETS + HEAD_PRESETS, rig: Rig | None = None, hidden: bool = True,
                    px: int = 600, jobs: int | None = None, layers=None) -> dict:
    """Render ``scene`` (a scene JSON path or a raw scene dict, e.g. ``export.scene_dict``) with castplane for each
    preset camera.  Returns ``{preset: {"svg": str, "png": bytes, "warnings": [str], "camera": dict}}``.
    Stage A runs once; stages B + C run per camera (``jobs`` worker processes, default up to 4).
    ``layers``: SVG layers to draw (default: the scene's; ``["objects"]`` gives the bare line drawing
    without the translucent form / cast shadow fills)."""
    return _pv.castplane_views(scene, cameras(rig), presets, hidden, px, jobs, layers)


def write_line_previews(scene, out_dir, presets=BODY_PRESETS + HEAD_PRESETS, rig: Rig | None = None,
                        hidden: bool = True, px: int = 600, jobs: int | None = None, layers=None) -> dict:
    """:func:`castplane_views` written to ``out_dir``: ``lines_<preset>.svg`` / ``.png`` per view, the
    contact sheet ``lines_sheet.png`` and ``lines_warnings.txt``.  Returns ``{preset: warnings}``."""
    return _pv.write_line_previews(scene, out_dir, cameras(rig), presets, hidden, px, jobs, layers)
