"""Writers of the Reiya model: castplane scene JSON (inline mesh data), Wavefront OBJ + MTL, glTF 2.0 GLB.

The writers are character-free and live in :mod:`charmodel.export`; this module holds Reiya's texts (the scene
:data:`SCENE_SETTINGS` and :data:`DESCRIPTION`, the OBJ / MTL header lines, the GLB generator and copyright
strings, all carrying the rights :data:`NOTICE`; :func:`scene_description` quotes her heights from the rig) and thin
wrappers with the public names the CLI and ``tests/test_reiya_model.py`` use.  Every writer is deterministic (fixed
object order, rounded coordinates, no timestamps): running the generator twice gives byte-identical files.  Geometry
comes from an :class:`~charmodel.assembly.Assembly`: the castplane objects (:data:`~reiya_model.assemble.OBJECTS`,
spatially compact groups of parts) and the material of every part (:data:`~reiya_model.assemble.MATERIALS`).

* :func:`scene_text` / :func:`write_scene`: the scene of :func:`scene_settings` (a sun, the ground receiver, the
  3/4 front portrait camera, scaled with the model by ``rig.figure_scale``) and :func:`scene_description`, both of
  the assembly's rig, with one ``mesh`` object per castplane object and inline ``data``, each with
  ``display_color`` (lower-case ``"#rrggbb"`` of its dominant material,
  :func:`~reiya_model.assemble.display_color`; read only by the web UI's 3D views, ignored by the core); the
  structure is indented, every ``data`` block is compact on one line.  :func:`check_scene` loads it with
  ``castplane.load_scene`` (lazy import).
* :func:`write_obj`: ``mtllib``, one ``o <object>`` per object and a ``usemtl <material>`` per part block
  (castplane's OBJ reader ignores ``usemtl``), ``s`` per smooth group (group ids made unique across objects;
  vertices ordered so that the whole file is also safe as a single castplane mesh).  The MTL has every
  material.
* :func:`write_glb`: one node + mesh per object (named by the object id) with one primitive per material
  (that material's faces, its own compact vertex set), POSITION / NORMAL (smoothed within a smooth group,
  vertices split at group boundaries) / indices; the materials array is :data:`MATERIALS` in order.
  castplane ``(x, y, z)`` is written as glTF ``(x, z, -y)`` (glTF is Y-up; castplane's importer maps back
  exactly and concatenates a mesh's primitives into one object).
"""

from __future__ import annotations

from charmodel import export as _ex
from charmodel.export import check_scene, srgb_to_linear

from .assemble import CHARACTER, OBJECTS
from .rig import Rig

__all__ = ["SCENE_SETTINGS", "SHEET_CAMERA", "scene_settings", "DESCRIPTION", "scene_description", "NOTICE",
           "OBJ_HEADER", "MTL_HEADER", "GLB_GENERATOR", "GLB_COPYRIGHT", "scene_dict", "scene_text", "write_scene",
           "check_scene", "obj_text", "mtl_text", "write_obj", "glb_bytes", "write_glb", "srgb_to_linear"]

#: The rights notice of the character (BRIEF §6; the second section of COPYRIGHT_NOTICE.md), written into the scene
#: description and the OBJ / MTL headers.
NOTICE = (
    "Reiya and her design belong to her creator; this model is a drawing reference made from the creator's design "
    "sheet; the character is not part of this project's authorized distribution (the GPL-3.0 licence covers the "
    "castplane software only; see COPYRIGHT_NOTICE.md)."
)

_RIG = Rig()


def scene_description(rig: Rig | None = None) -> str:
    """The scene ``description`` for ``rig`` (default: the default rig, :data:`DESCRIPTION`): her height (barefoot,
    ``rig.stated_height``), her height in her loafers (``rig.final_height``) and her heads (``rig.heads_tall``) come
    from the rig, so a ``--rig`` override of ``stated_height`` is quoted as it is built; the rest is fixed text."""
    rig = Rig() if rig is None else rig
    return (
        f"Reiya (レイヤ) as a drawing reference: an anime girl {rig.stated_height:.2f} m tall (barefoot, sole to "
        f"skull top; {rig.final_height:.2f} m in her loafers, {rig.heads_tall:.1f} heads to the hair crown) with a "
        "salmon-pink bob, two ear-shaped hair tufts on top and two thin braids, a white mock-neck top under a navy "
        "jumper dress with a long fluted A-line skirt, a cropped rust-brown cardigan worn off the shoulders with "
        "balloon sleeves, white socks and brown penny loafers; in a "
        "relaxed A-pose, standing at the origin on the ground (z = 0) and facing -Y (her left hand on +X). "
        f"{len(OBJECTS)} mesh objects, each a spatially compact group of parts (" + ", ".join(o for o, _ in OBJECTS)
        + ") so hidden-line removal stays fast; each object's display_color (its dominant material) colours it in "
        "the web UI's 3D views and is ignored by the drawing; per-part colours are the materials in "
        "examples/meshes/reiya.obj/.mtl/.glb. "
        "Smooth groups turn the designed lines (fringe locks, bob tips, the tufts' inner-ear lines, neckline, waist "
        "seam, hems, cuffs, shoe outlines) into feature edges and leave the rest to silhouettes. In the web UI "
        "choose it from the Example menu, orbit the board around her (the front button looks along +y at her face) "
        "and untick the 'labels' layer: every mesh vertex is labelled. "
        "The observer pane's sight rays (on by default) "
        "are drawn for every vertex of the first object, the two ear tufts, to show their perspective; untick them "
        "to see the whole figure. "
        "The default layers are the line drawing and the ground shadow (objects, cast_shadow); tick 'form_shadow' "
        "in the web UI for the shading fills (they are not hidden-line occluded, so back-lit hair shows through). "
        "The cast shadow is drawn per object (a translucent fill and outline for each), so where objects overlap "
        "(the head, hair, bob, tufts and face parts; the cardigan over the dress; the arms over the skirt) the fills "
        "stack darker and inner outlines show; trace its outer silhouette. It is also not occluded by her legs and "
        "shoes. "
        "CLI: 'castplane render examples/reiya.json -o out'. This scene JSON is the renderable form; the OBJ / GLB "
        "files are for other 3D software (a castplane import of them carries MESH_* warnings and renders slowly). "
        "Generated by tools/make_reiya_model.py. "
        "Rights notice: " + NOTICE
    )


#: The scene description of the default rig (:func:`scene_description`); the writers use the description of the
#: assembly's rig.
DESCRIPTION = scene_description(_RIG)

#: The scene camera as it was framed on the sheet-scale model (rig and SPEC.md lengths): 3/4 front-left at 27 deg
#: from the front, the lens at 1.40 (standing eye level, a little under her eyes at 1.459), 65 mm: the figure (soles
#: to the tuft tips) fills 75 % of the frame height; the target sits 0.33 to the right of her axis (along the image's
#: right) so her ground shadow, which falls to her left-back (about 1.0 m), stays in the frame with about 3 mm (of 24)
#: to spare on both sides and 4.5 mm at the top and bottom.  :func:`scene_settings` scales its position and target by
#: ``rig.figure_scale`` about the origin, as the model is scaled, so the picture stays the same: at the default rig the
#: lens is at 1.3685 m and her eyes at 1.426 m.
SHEET_CAMERA = {"position": [1.8, -3.53, 1.4], "target": [0.3, 0.15, 0.8], "roll_deg": 0, "focal_length_mm": 65,
                "frame_mm": [24, 36], "shift_mm": [0.0, 0.0], "near_m": 0.05}

#: Decimals of the scaled scene camera's position and target (0.1 mm).
CAMERA_DECIMALS = 4


def scene_settings(rig: Rig | None = None) -> dict:
    """The scene blocks for ``rig`` (default: the default rig): :data:`SHEET_CAMERA` with its position and target
    times ``rig.figure_scale``, rounded to :data:`CAMERA_DECIMALS` (scalar products, the same bits on every CPU).
    Version 0.1, metres, Z up; one directional light ``sun`` from the viewer's upper left
    (:data:`~reiya_model.rig.SUN_TOWARDS`; the writer fills in the direction); the receiver ``ground`` (the plane
    z = 0); the camera; the output layers ``objects`` and ``cast_shadow`` with hidden lines omitted
    (``examples/README.md`` describes the scene).  The objects are inserted between ``up`` and ``lights``."""
    rig = Rig() if rig is None else rig
    f = rig.figure_scale
    camera = dict(SHEET_CAMERA)
    for key in ("position", "target"):
        camera[key] = [round(float(v) * f, CAMERA_DECIMALS) + 0.0 for v in SHEET_CAMERA[key]]
    return {
        "version": "0.1",
        "units": "m",
        "up": "z",
        "lights": [{"id": "sun", "type": "directional", "direction": None}],
        "receivers": [{"id": "ground", "type": "plane", "normal": [0, 0, 1], "offset": 0}],
        "camera": camera,
        "output": {"canvas_mm": [182, 273], "layers": ["objects", "cast_shadow"], "hidden_lines": True,
                   "hidden_style": "omit", "png_dpi": 200},
    }


#: The scene blocks of the default rig (:func:`scene_settings`); the writers use the blocks of the assembly's rig.
SCENE_SETTINGS = scene_settings(_RIG)

#: Header lines of examples/meshes/reiya.obj and reiya.mtl.
OBJ_HEADER = ("# Reiya drawing-reference model (castplane frame: Z up, metres, facing -Y)",
              "# generated by tools/make_reiya_model.py",
              "# COPYRIGHT: " + NOTICE)
MTL_HEADER = ("# Reiya model materials (tools/make_reiya_model.py)",
              "# COPYRIGHT: " + NOTICE)

#: ``asset.generator`` and ``asset.copyright`` of examples/meshes/reiya.glb.
GLB_GENERATOR = "tools/reiya_model (castplane)"
GLB_COPYRIGHT = ("Reiya and her design belong to her creator; drawing reference made from the creator's design sheet, "
                 "not part of this project's authorized distribution (GPL-3.0 covers the castplane software only; "
                 "COPYRIGHT_NOTICE.md)")


def _description(assembly, description: str | None) -> str:
    return scene_description(assembly.rig) if description is None else description


def scene_dict(assembly, description: str | None = None) -> dict:
    """The castplane scene as a dict (objects in the fixed order, inline data; the camera and, unless
    ``description`` is given, the :func:`scene_description` of the assembly's rig)."""
    return _ex.scene_dict(CHARACTER, assembly, scene_settings(assembly.rig), _description(assembly, description))


def scene_text(assembly, description: str | None = None) -> str:
    """Scene JSON text: indented structure, one compact line per ``data`` block, trailing newline."""
    return _ex.scene_text(CHARACTER, assembly, scene_settings(assembly.rig), _description(assembly, description))


def write_scene(assembly, path, description: str | None = None) -> str:
    return _ex.write_scene(CHARACTER, assembly, path, scene_settings(assembly.rig),
                           _description(assembly, description))


def mtl_text(assembly=None) -> str:
    """MTL text with every material of :data:`MATERIALS` (``Kd`` in sRGB, as most OBJ readers expect)."""
    return _ex.mtl_text(CHARACTER, MTL_HEADER)


def obj_text(assembly, mtl_name: str = "reiya.mtl") -> str:
    """OBJ text: the objects in order (``o``), a ``usemtl`` per part block, global vertex numbering, ``s``
    ids unique across objects.  The vertex order is fixed with :func:`charmodel.meshkit.fix_nesting` over the whole
    model, so a single-object import of the file (``castplane import reiya.obj``) gets no orientation flip
    either."""
    return _ex.obj_text(assembly, mtl_name, OBJ_HEADER)


def write_obj(assembly, obj_path, mtl_path) -> None:
    _ex.write_obj(CHARACTER, assembly, obj_path, mtl_path, OBJ_HEADER, MTL_HEADER)


def glb_bytes(assembly, generator: str = GLB_GENERATOR) -> bytes:
    """The model as a binary glTF 2.0 file: one node / mesh per object, one primitive per material."""
    return _ex.glb_bytes(CHARACTER, assembly, generator, GLB_COPYRIGHT)


def write_glb(assembly, path) -> None:
    _ex.write_glb(CHARACTER, assembly, path, GLB_GENERATOR, GLB_COPYRIGHT)
