"""Loader layer of castplane (contract §5.0.2, §5.2.2, §5.2.8): file loaders, scene expansion and
the importer notes.  Python only; nothing here is used by ``validate_scene`` or the stages A/B/C.

    raw            = castplane.io.load_mesh_file(path, node=None)          # {vertices, faces, smooth_groups}
    scene, notes   = castplane.io.expand_scene(scene, base_dir=None)       # mesh + path -> mesh + data
    scene, notes   = castplane.io.load_expanded_scene(path_or_dict, base_dir=None)   # read_json + expand + validate

``expand_scene`` replaces every object whose ``type`` is a key of :data:`EXPANDERS` by the objects
its expander returns (in list position); a ``mesh`` object with ``path`` and no ``data`` gets its
``data`` from the file (``path`` kept as written).  Relative paths are joined to ``base_dir`` (the
scene file's directory, else the current working directory).  Loader errors become
``SceneError("objects[i].path", ...)`` (a failed ``node`` selection ``objects[i].node``); a missing
optional dependency is an ``ImportError``; an unreadable file an ``OSError`` whose message names
the field.  Importer notes ``{code, ids, message}`` come from the closed list
:data:`IMPORT_NOTE_CODES` and are never document warnings.
"""

from __future__ import annotations

import contextvars
import copy
import os

import numpy as np

from ..errors import SceneError, merge_warnings
from ..scene import read_json, to_z_up, validate_scene
from . import gltf, obj, step, trimesh_adapter

__all__ = ["EXPANDERS", "IMPORT_NOTE_CODES", "SUPPORTED_EXTENSIONS", "load_mesh_file", "expand_mesh_object",
           "expand_scene", "load_expanded_scene"]
__all__ += ["EXTENSION_LOADERS"]                # M8 (contract §5.5.0)

#: The documented mesh file extensions (contract §5.2.8): ``.obj`` -> :mod:`castplane.io.obj`,
#: ``.gltf`` / ``.glb`` -> :mod:`castplane.io.gltf`, ``.stl`` / ``.ply`` -> trimesh (optional extra
#: ``mesh``).  Any other extension is also handed to trimesh.
SUPPORTED_EXTENSIONS = (".obj", ".gltf", ".glb", ".stl", ".ply")
GLTF_EXTENSIONS = (".gltf", ".glb")

#: The closed list of importer notes (contract §5.0.2), code -> default message.  M8 appends the
#: ``STEP_*`` codes.  Notes are never merged into a document's ``warnings``.
IMPORT_NOTE_CODES = {
    "IMPORT_SPOT_AS_POINT": "spot light imported as a point light at its position",
    "IMPORT_CAMERA_DROPPED": "the file holds more cameras than the scene uses",
    "IMPORT_NO_CAMERA_DEFAULT": "the file holds no camera; the bounding-box default camera is used",
    "IMPORT_NO_LIGHT_DEFAULT": "the file holds no light; the default directional light is used",
}
# --- M8: the STEP importer notes (contract §5.5.6; ``step.STEP_WARNING_CODES`` is this sub-list) ---
IMPORT_NOTE_CODES.update(step.STEP_WARNING_CODES)

#: The default directional light of an import without a light (contract §5.2.8).
DEFAULT_LIGHT_DIRECTION = [-0.5, -0.5, 0.7071067811865476]
DEFAULT_LIGHT_ID = "sun"

_CACHE: contextvars.ContextVar = contextvars.ContextVar("castplane_io_cache", default=None)


def _note(code: str, ids=(), message: str | None = None) -> dict:
    """An importer note (contract §5.0.2), like ``errors.make_warning`` against :data:`IMPORT_NOTE_CODES`."""
    if code not in IMPORT_NOTE_CODES:
        raise ValueError(f"unknown importer note code {code!r}")
    return {"code": code, "ids": [str(i) for i in ids],
            "message": IMPORT_NOTE_CODES[code] if message is None else str(message)}


def _parse_file(path: str):
    """The parsed form of a mesh file (cached per absolute path within one ``expand_scene`` call)."""
    cache = _CACHE.get()
    key = os.path.abspath(path)
    if cache is not None and key in cache:
        return cache[key]
    ext = os.path.splitext(path)[1].lower()
    if ext == ".obj":
        parsed = ("obj", obj.read_obj(path))
    elif ext in GLTF_EXTENSIONS:
        parsed = ("gltf", gltf.read_gltf(path))
    elif ext in EXTENSION_LOADERS:             # M8: .step / .stp -> tessellate_step (§5.5.7), no recognition
        try:
            parsed = ("tessellated", _raw_from_triangles(EXTENSION_LOADERS[ext](path)))
        except step.StepError as exc:          # the loader message without the standalone "step" field
            raise SceneError("", exc.message) from None
    else:
        # trimesh files take no node selection, so the parsed form is the raw mesh itself
        parsed = ("trimesh", trimesh_adapter.load_trimesh(path, None))
    if cache is not None:
        cache[key] = parsed
    return parsed


def load_mesh_file(path, node=None) -> dict:
    """Load a mesh file into the common raw form ``{"vertices": [[x, y, z]...], "faces": [[int...]...],
    "smooth_groups": [int...]}`` (contract §5.2.8): glTF / GLB already Z-up (axis map applied, node
    transforms baked), OBJ / STL / PLY in file axes; file units.  Dispatch by lower-cased extension:
    ``.obj``, ``.gltf`` / ``.glb``, :data:`EXTENSION_LOADERS` (``.step`` / ``.stp``: OCP tessellation in
    metres, M8), anything else through trimesh.  ``node`` selects a glTF node /
    mesh or an OBJ ``o`` / ``g`` name (string, or integer index)."""
    path = os.fspath(path)
    ext = os.path.splitext(path)[1].lower()
    if node is not None and ext != ".obj" and ext not in GLTF_EXTENSIONS:
        raise SceneError("node", "node selection needs an OBJ or glTF file")
    kind, parsed = _parse_file(path)
    if kind == "obj":
        return obj.load_obj(path, node, parsed=parsed)
    if kind == "gltf":
        return gltf.load_gltf(path, node, parsed=parsed)
    return copy.deepcopy(parsed)


def expand_mesh_object(o: dict, field: str, base_dir) -> tuple:
    """``EXPANDERS["mesh"]`` (contract §5.0.2): a ``mesh`` object with ``path`` and no ``data`` is
    returned with ``data`` loaded from the file (``path`` kept as written); any other object is
    returned unchanged.  Returns ``([object], notes)``."""
    out = copy.deepcopy(o)
    if not isinstance(o, dict) or "data" in o or not isinstance(o.get("path"), str) or o["path"] == "":
        return [out], []
    path = o["path"]
    ext = os.path.splitext(path)[1].lower()
    if "up" in o and ext in GLTF_EXTENSIONS:
        raise SceneError(f"{field}.up", "glTF files are always Y-up; omit up")
    node = o.get("node")
    if node is not None and (isinstance(node, bool) or not isinstance(node, (str, int))
                             or (isinstance(node, int) and node < 0)):
        raise SceneError(f"{field}.node", "must be a string or a non-negative integer")
    full = path if os.path.isabs(path) else os.path.join(os.getcwd() if base_dir is None else os.fspath(base_dir), path)
    try:
        raw = load_mesh_file(full, node)
    except SceneError as exc:
        if exc.field == "node":
            raise SceneError(f"{field}.node", exc.message) from None
        raise SceneError(f"{field}.path", f"{exc.field}: {exc.message}" if exc.field else exc.message) from None
    except OSError as exc:
        raise type(exc)(exc.errno, f"{field}.path: {exc.strerror or exc}", exc.filename) from None
    out["data"] = raw
    return [out], []


#: Object type -> expander ``(obj, field, base_dir) -> (objects, notes)`` (contract §5.0.2; M8 adds ``step``).
EXPANDERS = {"mesh": expand_mesh_object}

# --- M8: STEP (contract §5.5.0, §5.5.7) -----------------------------------------------------------
EXPANDERS["step"] = step.expand_step_object

#: Lower-cased file extension -> loader ``(path) -> {"vertices" (m), "faces", ...}`` used by
#: :func:`load_mesh_file` (hence by a ``mesh`` object with ``path``) before the M5 dispatch:
#: a ``.step`` / ``.stp`` mesh file is tessellated directly with OCP (optional extra ``step``),
#: with **no** analytic recognition (``type: "step"`` is the only analytic path).
EXTENSION_LOADERS = {".step": step.tessellate_step, ".stp": step.tessellate_step}


def _raw_from_triangles(tri: dict) -> dict:
    """The raw mesh form ``{vertices, faces, smooth_groups}`` of a tessellation (the ``data`` of
    ``step.mesh_object_from_triangles``)."""
    return step.mesh_object_from_triangles("mesh", tri, None)["data"]


def expand_scene(scene, base_dir=None) -> tuple:
    """Return ``(scene_out, notes)``: a new scene dict in which every object whose type is a key of
    :data:`EXPANDERS` is replaced, in its list position, by the objects its expander returns; every
    other element is deep-copied unchanged.  A non-dict scene or a non-list ``objects`` is passed
    through (``validate_scene`` reports the proper field).  Idempotent on an expanded scene."""
    if not isinstance(scene, dict) or not isinstance(scene.get("objects"), list):
        return copy.deepcopy(scene), []
    token = _CACHE.set({})
    try:
        objects, notes = [], []
        for i, o in enumerate(scene["objects"]):
            typ = o.get("type") if isinstance(o, dict) else None
            expander = EXPANDERS.get(typ) if isinstance(typ, str) else None
            if expander is None:
                objects.append(copy.deepcopy(o))
                continue
            got, got_notes = expander(o, f"objects[{i}]", base_dir)
            objects.extend(got)
            notes.extend(got_notes)
    finally:
        _CACHE.reset(token)
    out = {key: (objects if key == "objects" else copy.deepcopy(value)) for key, value in scene.items()}
    return out, merge_warnings(notes)


def load_expanded_scene(path_or_dict, base_dir=None) -> tuple:
    """``scene.read_json`` (for a path) -> :func:`expand_scene` -> ``validate_scene``; returns
    ``(validated scene, notes)``.  ``base_dir`` defaults to the scene file's directory (a dict:
    the current working directory)."""
    if isinstance(path_or_dict, (str, os.PathLike)):
        raw = read_json(path_or_dict)
        if base_dir is None:
            base_dir = os.path.dirname(os.path.abspath(os.fspath(path_or_dict)))
    else:
        raw = path_or_dict
    scene, notes = expand_scene(raw, base_dir)
    return validate_scene(scene), notes


# --------------------------------------------------------------------------- importer defaults (§5.2.8)
def _world_points(o: dict, raw: dict | None):
    """World points of one imported object for the default camera's bounding box."""
    if o.get("type") == "mesh":
        V = raw["vertices"]
        if o.get("up") == "y":
            V = to_z_up(V)
        return np.asarray(V, dtype=np.float64) * float(o.get("scale", 1.0))
    from ..primitives import build_object
    from ..scene import validate_object

    return build_object(validate_object(o, "object"))["mesh"]["vertices"]


def _default_camera(objects: list, raw: dict) -> tuple:
    """The bounding-box camera of contract §5.2.8: ``target`` = bbox centre, ``position = (c_x,
    y_min - 2e, z_min + 0.7e)`` with ``e = max(1, largest bbox side)``, f 35, frame 36 x 24, canvas
    360 x 240."""
    pts = np.concatenate([np.asarray(_world_points(o, raw.get(o["id"])), dtype=np.float64).reshape(-1, 3)
                          for o in objects], axis=0)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    c = (lo + hi) / 2.0
    e = max(1.0, float((hi - lo).max()))
    camera = {"position": [float(c[0]) + 0.0, float(lo[1] - 2.0 * e) + 0.0, float(lo[2] + 0.7 * e) + 0.0],
              "target": [float(v) + 0.0 for v in c], "focal_length_mm": 35.0, "frame_mm": [36.0, 24.0]}
    return camera, [360.0, 240.0]


def _assemble_scene(parts: dict, notes: list) -> tuple:
    """A complete raw scene from importer pieces (no ``--into``): the file's camera / lights or the
    defaults with their notes, the ground receiver, ``meta.import_notes``."""
    notes = list(notes)
    camera, canvas = parts.get("camera"), parts.get("canvas_mm")
    if camera is None:
        camera, canvas = _default_camera(parts["objects"], parts.get("raw", {}))
        notes.append(_note("IMPORT_NO_CAMERA_DEFAULT"))
    lights = parts.get("lights")
    if not lights:
        lights = [{"id": DEFAULT_LIGHT_ID, "type": "directional", "direction": list(DEFAULT_LIGHT_DIRECTION)}]
        notes.append(_note("IMPORT_NO_LIGHT_DEFAULT"))
    notes = merge_warnings(notes)
    scene = {
        "version": "0.1",
        "units": "m",
        "up": "z",
        "objects": parts["objects"],
        "lights": lights,
        "receivers": [{"id": "ground", "type": "plane", "normal": [0.0, 0.0, 1.0], "offset": 0.0}],
        "camera": camera,
        "output": {"canvas_mm": canvas},
        "meta": {"import_notes": notes},
    }
    return scene, notes
