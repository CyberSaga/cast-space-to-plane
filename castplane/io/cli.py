"""The ``castplane import`` subcommand (contract §5.0.2, §5.2.8).

    castplane import FILE [-o OUT.json] [--into SCENE] [--id ID] [-q]
                          [--inline] [--node NAME|INDEX] [--camera NAME] [--light NAME]
                          [--scale S] [--weld TOL] [--smooth-angle DEG] [--up y|z]

The mesh options apply to ``.obj`` / ``.gltf`` / ``.glb`` / ``.stl`` / ``.ply`` (and every other
format trimesh reads); ``--camera`` / ``--light`` need a glTF file, ``--up`` a non-glTF file
(glTF is always Y-up).  The output is the **raw** assembled scene (``json.dumps(sort_keys=True,
indent=1, ensure_ascii=False)``, importer-generated floats canonical): mesh objects reference FILE
by a POSIX path relative to the output file's directory (the current directory for stdout) or
embed ``data`` with ``--inline``.  ``--into SCENE`` appends the imported objects to the raw
``objects`` of SCENE and copies its other blocks verbatim (the file's camera and lights are then
not used); a relative ``path`` of SCENE's own mesh objects is rewritten relative to the output's
directory when that is not SCENE's directory, so the written scene always re-loads.  Imported ids
are de-duplicated (``_2``, ``_3``, ...) against ``ground`` and SCENE's object / receiver ids; an
explicit ``--id`` that collides is a ``SceneError("--id")``.  ``validate_scene`` checks the assembled scene before anything is written.  Importer
notes go to stderr as ``note: CODE [ids]: message`` (suppressed by ``-q``) and into
``meta.import_notes``.  Exit codes as ``castplane.cli``: 0, 1 (unreadable input / unwritable
output), 2 (``SceneError`` incl. the glTF JSON path, usage), 3 (trimesh missing for STL / PLY).
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys

from ..errors import SceneError, merge_warnings
from ..scene import read_json, validate_scene
from . import EXPANDERS, GLTF_EXTENSIONS, _assemble_scene, expand_scene, gltf, load_mesh_file

__all__ = ["add_import_parser", "cmd_import"]

STEP_EXTENSIONS = (".step", ".stp")


def sanitised_stem(path) -> str:
    """Default object id: the file stem with every character outside ``[A-Za-z0-9_-]`` -> ``_``."""
    stem = os.path.splitext(os.path.basename(os.fspath(path)))[0]
    return re.sub(r"[^A-Za-z0-9_-]", "_", stem) or "mesh"


def _node_value(text):
    if text is None:
        return None
    return int(text) if text.isdigit() else text


def add_import_parser(sub) -> None:
    """Register the ``import`` subcommand on an argparse sub-parser collection."""
    p = sub.add_parser("import", help="import a mesh file (OBJ, glTF / GLB, STL, PLY) as a scene")
    p.add_argument("file", metavar="FILE")
    p.add_argument("-o", "--output", metavar="OUT.json", help="write the scene here (default: stdout)")
    p.add_argument("--into", metavar="SCENE", help="append the imported objects to this scene")
    p.add_argument("--id", help="object id (default: the sanitised file stem)")
    p.add_argument("-q", "--quiet", action="store_true", help="print nothing but errors")
    p.add_argument("--inline", action="store_true", help="embed the geometry as data instead of a path")
    p.add_argument("--node", metavar="NAME|INDEX", help="import one glTF node / mesh or OBJ o / g name")
    p.add_argument("--camera", metavar="NAME", help="glTF: use the camera of this node")
    p.add_argument("--light", metavar="NAME", help="glTF: keep only the light of this node")
    p.add_argument("--scale", type=float, metavar="S", help="file units -> metres (e.g. 0.001 for mm)")
    p.add_argument("--weld", type=float, metavar="TOL", help="weld tolerance in metres (default 1e-6)")
    p.add_argument("--smooth-angle", type=float, metavar="DEG", help="smoothing angle (default 30)")
    p.add_argument("--up", choices=("y", "z"), help="up axis of an OBJ / STL / PLY file (default z)")
    p.set_defaults(func=cmd_import)


def _mesh_keys(args) -> dict:
    keys = {}
    if args.scale is not None:
        keys["scale"] = args.scale + 0.0
    if args.weld is not None:
        keys["weld_tolerance"] = args.weld + 0.0
    if args.smooth_angle is not None:
        keys["smooth_angle_deg"] = args.smooth_angle + 0.0
    return keys


def _ref_path(file_path: str, output) -> str:
    """POSIX path of FILE relative to the output file's directory (cwd for stdout)."""
    base = os.path.dirname(os.path.abspath(output)) if output else os.getcwd()
    rel = os.path.relpath(os.path.abspath(file_path), base)
    return rel.replace(os.sep, "/")


def _import_parts(args):
    """``(parts, notes)`` of FILE (contract §5.2.8)."""
    path = args.file
    ext = os.path.splitext(path)[1].lower()
    if ext in STEP_EXTENSIONS:
        raise SceneError("FILE", "STEP import is not available in this version (castplane import accepts "
                                 "OBJ, glTF / GLB, STL and PLY files)")
    if not os.path.isfile(path):
        raise FileNotFoundError(2, f"cannot read {path}", path)
    ref = _ref_path(path, args.output)
    keys = _mesh_keys(args)
    node = _node_value(args.node)
    if ext in GLTF_EXTENSIONS:
        if args.up is not None:
            raise SceneError("--up", "glTF files are always Y-up; omit --up")
        parts, notes = gltf.import_gltf_parts(path, ref=ref, inline=args.inline, node=node, camera=args.camera,
                                              light=args.light, mesh_keys=keys)
        if args.id is not None:
            if len(parts["objects"]) != 1:
                raise SceneError("--id", f"the file yields {len(parts['objects'])} objects; --id needs exactly one "
                                         "(select one with --node)")
            old = parts["objects"][0]["id"]
            parts["objects"][0]["id"] = args.id
            if old in parts["raw"]:
                parts["raw"][args.id] = parts["raw"].pop(old)
        return parts, notes
    for opt, value in (("--camera", args.camera), ("--light", args.light)):
        if value is not None:
            raise SceneError(opt, f"{opt} needs a glTF / GLB file")
    raw = load_mesh_file(path, node)
    oid = args.id if args.id is not None else sanitised_stem(path)
    o = {"id": oid, "type": "mesh"}
    if args.inline:
        o["data"] = raw
    else:
        o["path"] = ref
        if node is not None:
            o["node"] = node
    if args.up is not None:
        o["up"] = args.up
    o.update(keys)
    return {"objects": [o], "lights": None, "camera": None, "canvas_mm": None, "raw": {oid: raw}}, []


def _check_object(o: dict, raw: dict) -> dict:
    """The imported object as validation sees it (geometry filled in)."""
    if o.get("type") == "mesh" and "data" not in o:
        o = dict(o, data=raw[o["id"]])
    return o


def _dedupe(objects: list, raw: dict, taken: set) -> None:
    for o in objects:
        base, n, oid = o["id"], 2, o["id"]
        while oid in taken:
            oid, n = f"{base}_{n}", n + 1
        if oid != base and base in raw:
            raw[oid] = raw.pop(base)
        o["id"] = oid
        taken.add(oid)


def _ids(blocks) -> set:
    return {b["id"] for b in blocks if isinstance(b, dict) and isinstance(b.get("id"), str)} \
        if isinstance(blocks, list) else set()


def _rebase_paths(objects: list, scene_dir: str, output) -> list:
    """SCENE's raw objects with every relative loader ``path`` (an object whose type has an
    expander) rewritten relative to the output file's directory (cwd for stdout), so that the
    written scene re-loads from where it is written; every other key stays verbatim."""
    base = os.path.dirname(os.path.abspath(output)) if output else os.getcwd()
    if os.path.normcase(os.path.abspath(base)) == os.path.normcase(os.path.abspath(scene_dir)):
        return copy.deepcopy(objects)          # written next to SCENE: the paths stay verbatim
    out = []
    for o in objects:
        o = copy.deepcopy(o)
        path = o.get("path") if isinstance(o, dict) else None
        if isinstance(o, dict) and o.get("type") in EXPANDERS and isinstance(path, str) and path \
                and not os.path.isabs(path):
            full = os.path.normpath(os.path.join(scene_dir, path))
            try:
                o["path"] = os.path.relpath(full, base).replace(os.sep, "/")
            except ValueError:                 # another drive (Windows): no relative path exists
                o["path"] = full.replace(os.sep, "/")
        out.append(o)
    return out


def cmd_import(args) -> int:
    """``castplane import``: assemble, check and write the scene (contract §5.0.2, §5.2.8)."""
    parts, notes = _import_parts(args)
    raw = parts["raw"]
    base_scene = None
    taken = {"ground"}                         # the receiver id (kept free with --into too, §5.0.1)
    if args.into:
        base_scene = read_json(args.into)
        if not isinstance(base_scene, dict):
            raise SceneError("--into", "the scene must be a JSON object")
        taken |= _ids(base_scene.get("objects")) | _ids(base_scene.get("receivers"))
    if args.id is not None and args.id in taken:
        raise SceneError("--id", f"{args.id!r} is already an object or receiver id of the scene")
    _dedupe(parts["objects"], raw, set(taken))
    if base_scene is not None:
        scene_dir = os.path.dirname(os.path.abspath(args.into))
        expanded, into_notes = expand_scene(base_scene, scene_dir)
        scene = copy.deepcopy(base_scene)
        scene["objects"] = _rebase_paths(list(scene.get("objects", [])), scene_dir, args.output) + parts["objects"]
        check = copy.deepcopy(expanded)
        check["objects"] = list(check.get("objects", [])) + [_check_object(o, raw) for o in parts["objects"]]
        notes = merge_warnings(notes, into_notes)
        meta = scene.get("meta")
        scene["meta"] = dict(meta) if isinstance(meta, dict) else {}
        scene["meta"]["import_notes"] = notes
    else:
        scene, notes = _assemble_scene(parts, notes)
        check = dict(scene, objects=[_check_object(o, raw) for o in scene["objects"]])
    validate_scene(check)                      # a check only: the raw assembled scene is written
    text = json.dumps(scene, sort_keys=True, indent=1, ensure_ascii=False) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        if not args.quiet:
            print(args.output)
    else:
        sys.stdout.write(text)
    if not args.quiet:
        for n in notes:
            print(f"note: {n['code']} {n['ids']}: {n['message']}", file=sys.stderr)
    return 0

