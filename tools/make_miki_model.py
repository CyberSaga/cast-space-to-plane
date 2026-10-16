#!/usr/bin/env python3
"""Build the Hanabishi Miki drawing-reference model and write it for castplane (dev tool).

    python3 tools/make_miki_model.py                       # build -> validate -> write examples/miki.json,
                                                           #   examples/meshes/miki.{obj,mtl,glb}
    python3 tools/make_miki_model.py --check               # + castplane validate / render (warnings must be
                                                           #   []) + statistics table vs the budget
    python3 tools/make_miki_model.py --preview DIR         # + shaded contact sheets and head close-ups
    python3 tools/make_miki_model.py --lines DIR [--lines-views front head_side ...] [--no-hidden]
                                             [--lines-layers objects]
                                                           # + castplane line renders and their contact sheet
    python3 tools/make_miki_model.py --only hair headband --preview DIR [--context]
                                                           # quick iteration on some regions (writes no model
                                                           #   files unless --out-dir is given; --context draws
                                                           #   the other regions as grey mannequin parts)

The generator lives in ``tools/miki_model/`` (geometry numpy-only; previews use Pillow and cairosvg).  The
output is deterministic: running the tool twice gives byte-identical files.  Exit status: 0 on success,
1 when the model is invalid, over budget or the castplane check reports warnings, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from miki_model import assemble as asm  # noqa: E402
from miki_model import export, preview  # noqa: E402
from miki_model.rig import Rig  # noqa: E402


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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out-dir", help="write miki.json here and meshes/miki.{obj,mtl,glb} below it "
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
    args = p.parse_args(argv)

    for v in args.lines_views or []:
        if v not in preview.PRESETS:
            p.error(f"unknown preset {v!r}; one of {list(preview.PRESETS)}")
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
    out_dir = args.out_dir or os.path.join(REPO, "examples")
    files = []
    if write:
        mesh_dir = os.path.join(out_dir, "meshes")
        os.makedirs(mesh_dir, exist_ok=True)
        scene_path = os.path.join(out_dir, "miki.json")
        text = export.write_scene(model, scene_path)
        export.check_scene(text)
        obj, mtl, glb = (os.path.join(mesh_dir, f"miki.{ext}") for ext in ("obj", "mtl", "glb"))
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
            if size > 700 * 1024:
                print(f"scene file {size / 1024:.0f} KiB exceeds 700 KiB")
                status = 1
        else:
            print("castplane check skipped (no model files written)")
    return status


if __name__ == "__main__":
    sys.exit(main())
