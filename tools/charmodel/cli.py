"""The command line of a character model generator (``tools/make_<name>_model.py``), character-free.

A character's script builds a :class:`Tool` from its package and calls :func:`main`::

    TOOL = cli.Tool(name="<name>", title="<Full Name>", rig=Rig, assemble=assemble, export=export,
                    preview=preview, repo=REPO)
    sys.exit(cli.main(TOOL))

Options: ``--out-dir``, ``--preview``, ``--lines``, ``--lines-views``, ``--no-hidden``, ``--lines-layers``,
``--only``, ``--context``, ``--check``, ``--no-strict``, ``--rig`` (``tools/miki_model/README.md`` describes
them) and ``--overlay SHEET DIR`` (the overlay check against the design sheet, :mod:`charmodel.overlay`; only for a
character with overlay data, ``Tool.overlay``).  Exit status: 0 on success, 1 when the model is invalid, over budget,
the scene file is over ``Tool.max_scene_kib``, the castplane check reports warnings or an overlay pass criterion
fails, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

__all__ = ["Tool", "main", "castplane_check"]


@dataclass(frozen=True)
class Tool:
    """What the CLI needs from a character package.

    * ``name``: the file stem: ``<out>/<name>.json`` and ``<out>/meshes/<name>.{obj,mtl,glb}``;
    * ``title``: the character's name in the help text;
    * ``rig``: the ``Rig`` class (``rig()`` is the default rig, ``rig.from_dict(dict)`` applies ``--rig``);
    * ``assemble``: a module with ``assemble(rig, only=, strict=)``, ``AssemblyError``, ``ALL_REGIONS`` and
      ``format_stats(stats)``;
    * ``export``: a module with ``write_scene(model, path) -> text``, ``check_scene(text)``,
      ``write_obj(model, obj_path, mtl_path)``, ``write_glb(model, path)`` and ``scene_dict(model)``;
    * ``preview``: a module with ``PRESETS``, ``with_context(model, rig)``,
      ``write_shaded_previews(model, out_dir, rig)`` and
      ``write_line_previews(scene, out_dir, presets, rig, hidden=, layers=)``;
    * ``repo``: the repository root; the default output directory is ``<repo>/examples``;
    * ``description``: the ``--help`` description (default: built from ``title``);
    * ``max_scene_kib``: ``--check`` fails above this scene file size;
    * ``overlay``: a module with ``SPEC`` (a :class:`charmodel.overlay.OverlaySpec`), or ``None``: ``--overlay`` is
      then a usage error."""

    name: str
    title: str
    rig: Any
    assemble: Any
    export: Any
    preview: Any
    repo: str
    description: str = ""
    max_scene_kib: int = 700
    overlay: Any = None


def _show(path: str) -> str:
    rel = os.path.relpath(path)
    return path if rel.startswith("..") else rel


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def castplane_check(scene_path: str) -> list:
    """castplane validate + render of the scene camera; returns the warnings (strings)."""
    import castplane
    from castplane.io import load_expanded_scene

    scene, _notes = load_expanded_scene(scene_path)
    out = castplane.render(scene)
    return [f"{w['code']} {w['ids']}" for w in out["geometry"]["warnings"]]


def _parser(tool: Tool) -> argparse.ArgumentParser:
    asm, preview, name = tool.assemble, tool.preview, tool.name
    description = (tool.description
                   or f"Build the {tool.title} drawing-reference model and write it for castplane (dev tool).")
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--out-dir", help=f"write {name}.json here and meshes/{name}.{{obj,mtl,glb}} below it "
                                     "(default: the repository's examples/)")
    p.add_argument("--preview", metavar="DIR", help="write shaded contact sheets and head close-ups to DIR")
    p.add_argument("--lines", metavar="DIR", help="write castplane line renders to DIR")
    p.add_argument("--lines-views", nargs="+", metavar="PRESET", default=None,
                   help=f"presets for --lines (default: all): {', '.join(preview.PRESETS)}")
    p.add_argument("--no-hidden", action="store_true", help="--lines without hidden-line removal (faster)")
    p.add_argument("--lines-layers", nargs="+", metavar="LAYER", default=None,
                   help="SVG layers for --lines (default: the scene's; 'objects' = lines only, no shadow fills)")
    p.add_argument("--only", nargs="+", metavar="REGION",
                   help=f"build only these regions or modules: {', '.join(asm.ALL_REGIONS)}")
    p.add_argument("--context", action="store_true",
                   help="with --only: show the other regions as grey mannequin parts in the shaded previews")
    p.add_argument("--check", action="store_true",
                   help="castplane validate + render (warnings must be []) and the statistics table")
    p.add_argument("--no-strict", action="store_true", help="keep going (previews only) when a part is invalid")
    p.add_argument("--rig", metavar="JSON", help="rig overrides (a JSON object of Rig fields)")
    p.add_argument("--overlay", nargs=2, metavar=("SHEET", "DIR"),
                   help="overlay check: render the front / side / back views orthographically into the design sheet "
                        "SHEET's pixel grid and write the overlays, the differences and report.md / report.json to "
                        "DIR (outside the repository: the images contain the sheet)")
    return p


def main(tool: Tool, argv=None) -> int:
    """Run the CLI for ``tool`` (``argv`` default: ``sys.argv[1:]``); returns the exit status."""
    asm, export, preview, Rig = tool.assemble, tool.export, tool.preview, tool.rig
    p = _parser(tool)
    args = p.parse_args(argv)

    for v in args.lines_views or []:
        if v not in preview.PRESETS:
            p.error(f"unknown preset {v!r}; one of {list(preview.PRESETS)}")
    if args.overlay:
        if tool.overlay is None:
            p.error(f"--overlay: {tool.title} has no overlay data (tools/{tool.name}_model/overlay.py)")
        sheet_path, overlay_dir = args.overlay
        repo, odir = os.path.realpath(tool.repo), os.path.realpath(overlay_dir)
        if odir == repo or odir.startswith(repo + os.sep):
            p.error(f"--overlay: {overlay_dir} lies inside the repository; the overlay images contain the design "
                    "sheet, which stays outside it")
        if not os.path.isfile(sheet_path):
            p.error(f"--overlay: no sheet image {sheet_path}")
    rig = Rig()
    if args.rig:
        with open(args.rig, encoding="utf-8") as fh:
            rig = Rig.from_dict(json.load(fh))

    t0 = time.time()
    try:
        model = asm.assemble(rig, only=args.only, strict=not args.no_strict)
    except asm.AssemblyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    status = 0
    if not model.ok:
        for r in model.reports.values():
            if not r.ok:
                print("invalid: " + r.summary(), file=sys.stderr)
        status = 1
    print(f"built {len(model.parts)} parts in {len(model.meshes)} objects in {time.time() - t0:.1f} s "
          f"(sources: {', '.join(sorted(set(model.sources.values())))})")

    write = model.ok and (args.only is None or args.out_dir is not None)
    out_dir = args.out_dir or os.path.join(tool.repo, "examples")
    files = []
    if write:
        mesh_dir = os.path.join(out_dir, "meshes")
        os.makedirs(mesh_dir, exist_ok=True)
        scene_path = os.path.join(out_dir, f"{tool.name}.json")
        text = export.write_scene(model, scene_path)
        export.check_scene(text)
        obj, mtl, glb = (os.path.join(mesh_dir, f"{tool.name}.{ext}") for ext in ("obj", "mtl", "glb"))
        export.write_obj(model, obj, mtl)
        export.write_glb(model, glb)
        files = [scene_path, obj, mtl, glb]
        for f in files:
            print(f"wrote {_show(f)}  {os.path.getsize(f) / 1024:.1f} KiB  sha256 {_sha(f)}")
    elif args.only is not None:
        print("--only without --out-dir: no model files written")

    if args.preview:
        t = time.time()
        shown = preview.with_context(model, rig) if (args.context and args.only) else model
        paths = preview.write_shaded_previews(shown, args.preview, rig)
        print(f"shaded previews: {len([x for x in paths if 'shaded_body' in x or 'shaded_head.png' in x])} sheets "
              f"+ {len(paths) - 2} views in {args.preview} ({time.time() - t:.1f} s)")

    if args.lines:
        t = time.time()
        scene = export.scene_dict(model)
        views = tuple(args.lines_views) if args.lines_views else tuple(preview.PRESETS)
        report = preview.write_line_previews(scene, args.lines, views, rig, hidden=not args.no_hidden,
                                             layers=args.lines_layers)
        noisy = {k: v for k, v in report.items() if v}
        print(f"castplane line renders: {len(report)} views in {args.lines} ({time.time() - t:.1f} s); "
              f"views with warnings: {noisy if noisy else 'none'}")

    if args.overlay:
        from . import overlay as _overlay

        t = time.time()
        report = _overlay.run_overlay(model, rig, tool.overlay.SPEC, args.overlay[0], args.overlay[1], repo=tool.repo,
                                      title=f"{tool.title}: overlay check")
        crit = report["criteria"]
        print(f"overlay check: {len(report['views'])} views in {args.overlay[1]} ({time.time() - t:.1f} s); "
              f"criteria: {_overlay.criteria_summary(crit)}")
        if any(c["pass"] is False for c in crit):
            status = 1

    if args.check:
        print()
        print(asm.format_stats(model.stats))
        if not model.stats["within_budget"] or not model.stats["rays_ok"]:
            status = 1
        if files:
            warnings = castplane_check(files[0])
            print(f"castplane validate: ok; render of the scene camera: warnings {warnings}")
            if warnings:
                status = 1
            for f in files:
                print(f"  {_show(f):34s} {os.path.getsize(f) / 1024:8.1f} KiB")
            size = os.path.getsize(files[0])
            if size > tool.max_scene_kib * 1024:
                print(f"scene file {size / 1024:.0f} KiB exceeds {tool.max_scene_kib} KiB")
                status = 1
        else:
            print("castplane check skipped (no model files written)")
    return status
