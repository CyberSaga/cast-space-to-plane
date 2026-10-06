"""``castplane`` command line (contract §1): render / validate / stages (+ info).

    castplane render scene.json -o OUTDIR [--camera cam.json] [--formats svg,json,png] [--layers a,b]
    castplane validate scene.json
    castplane stages scene.json [--camera cam.json] [-o stages.json]
    castplane info scene.json [--camera cam.json]

``stages`` dumps the stage A / stage B intermediates (contract §3) as one
canonical JSON object ``{"A": ..., "B": ...}`` (stdout unless ``-o`` is given).

Exit code 2 on a :class:`SceneError` (the message names the field path).
"""

from __future__ import annotations

import argparse
import os
import sys

from .errors import SceneError
from .output.geometry_json import dumps
from .output.png import write_png
from .output.svg import LAYER_ORDER, write_svg
from .pipeline import compose, project_scene, shadow_geometry
from .scene import load_camera, load_scene

FORMATS = ("svg", "json", "png")


def _split(value, allowed, what: str):
    if value is None:
        return None
    items = [v.strip() for v in value.split(",") if v.strip()]
    for it in items:
        if it not in allowed:
            raise SceneError(what, f"unknown {what} {it!r}; choose from {', '.join(allowed)}")
    return items


def _run(scene_path, camera_path):
    scene = load_scene(scene_path)
    camera = load_camera(camera_path) if camera_path else None
    A = shadow_geometry(scene)
    B = project_scene(scene, A, camera=camera)
    return scene, compose(scene, B)


def cmd_render(args) -> int:
    formats = _split(args.formats, FORMATS, "format") or ["svg", "json"]
    layers = _split(args.layers, LAYER_ORDER, "layer")
    scene, doc = _run(args.scene, args.camera)
    if layers is None:
        layers = scene["output"]["layers"]
    os.makedirs(args.outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.scene))[0]
    svg = write_svg(doc, layers=layers)
    written = []
    if "svg" in formats:
        path = os.path.join(args.outdir, stem + ".svg")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg)
        written.append(path)
    if "json" in formats:
        path = os.path.join(args.outdir, stem + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(dumps(doc))
            fh.write("\n")
        written.append(path)
    if "png" in formats:
        path = os.path.join(args.outdir, stem + ".png")
        with open(path, "wb") as fh:
            fh.write(write_png(svg, dpi=scene["output"]["png_dpi"]))
        written.append(path)
    for path in written:
        print(path)
    for w in doc["warnings"]:
        print(f"warning: {w['code']} {w['ids']}: {w['message']}", file=sys.stderr)
    return 0


def cmd_validate(args) -> int:
    scene = load_scene(args.scene)
    print(f"ok: {len(scene['objects'])} object(s), {len(scene['lights'])} light(s), "
          f"{len(scene['receivers'])} receiver(s)")
    return 0


def cmd_stages(args) -> int:
    scene = load_scene(args.scene)
    camera = load_camera(args.camera) if args.camera else None
    A = shadow_geometry(scene)
    B = project_scene(scene, A, camera=camera)
    text = dumps({"A": A, "B": B}) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(args.output)
    else:
        sys.stdout.write(text)
    return 0


def cmd_info(args) -> int:
    _, doc = _run(args.scene, args.camera)
    hz = doc["horizon"]
    print(f"canvas_mm: {doc['canvas_mm']}")
    print(f"horizon v_mm: {hz['v_mm']}")
    for axis in ("x", "y", "z"):
        print(f"vanishing point {axis}: {hz['vanishing_points'][axis]}")
    print(f"points: {len(doc['points'])}, edges: {len(doc['edges'])}")
    if doc["warnings"]:
        print("warnings:")
        for w in doc["warnings"]:
            print(f"  {w['code']} {w['ids']}: {w['message']}")
    else:
        print("warnings: none")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="castplane", description="Perspective shadow construction drawing.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("render", help="render a scene to SVG / JSON / PNG")
    p.add_argument("scene")
    p.add_argument("-o", "--outdir", required=True)
    p.add_argument("--camera", help="camera override JSON (a camera block or a scene file)")
    p.add_argument("--formats", help="comma-separated subset of svg,json,png (default svg,json)")
    p.add_argument("--layers", help="comma-separated subset of the six layer ids")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("validate", help="validate a scene file")
    p.add_argument("scene")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("stages", help="dump the stage A / B intermediates as canonical JSON")
    p.add_argument("scene")
    p.add_argument("--camera", help="camera override JSON (a camera block or a scene file)")
    p.add_argument("-o", "--output", help="write to this file instead of stdout")
    p.set_defaults(func=cmd_stages)

    p = sub.add_parser("info", help="print horizon, vanishing points and warnings")
    p.add_argument("scene")
    p.add_argument("--camera")
    p.set_defaults(func=cmd_info)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SceneError as exc:
        print(f"error: {exc.field}: {exc.message}" if exc.field else f"error: {exc.message}", file=sys.stderr)
        return 2
    except (OSError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
