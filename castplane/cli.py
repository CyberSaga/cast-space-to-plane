"""``castplane`` command line (contract §1, §5.0.2): render / validate / stages / info / import.

    castplane render   scene.json -o OUTDIR [--camera cam.json] [--formats svg,json,png]
                                            [--layers a,b] [--dpi N] [--quiet]
                                            [--hidden-lines | --no-hidden-lines] [--hidden-style dashed|omit]
    castplane validate scene.json [--quiet]
    castplane stages   scene.json [--camera cam.json] [-o stages.json] [--quiet]
    castplane info     scene.json [--camera cam.json]
    castplane import   FILE [-o OUT.json] [--into SCENE] [--id ID] [-q] [mesh options]  (castplane.io.cli)

``render`` writes ``<scene stem>.svg`` / ``.json`` / ``.png`` into ``OUTDIR`` for the
requested formats (default ``svg,json``; PNG only on request, through the optional
``cairosvg`` extra or the ``resvg`` CLI).  ``--camera`` takes a JSON file holding either
a bare ``camera`` block (spec §4 form) or a whole scene whose ``camera`` is used;
``--layers`` restricts the SVG to a subset of the six layer ids.  ``stages`` dumps the
stage A / stage B intermediates (contract §3) as one canonical JSON object
``{"A": ..., "B": ...}`` (stdout unless ``-o`` is given).  ``info`` prints the horizon,
the vanishing points, the construction points, the receivers (``lit`` / ``casts`` per light) and the
warning table.  ``--hidden-lines`` / ``--no-hidden-lines`` / ``--hidden-style`` override the scene's
``output.hidden_lines`` / ``hidden_style`` for ``render`` (contract §5.1.6.6; the scene is not rewritten).
``render`` / ``validate`` / ``stages`` / ``info`` load the scene with ``castplane.io.load_expanded_scene``
(``mesh`` objects with a ``path`` are read relative to the scene file) and print the importer
notes to stderr as ``note: <CODE> [ids]: message``.

Exit codes:

* ``0`` success;
* ``1`` file / output error (unreadable scene, unwritable output directory);
* ``2`` invalid input: a :class:`SceneError` (the message names the JSON field path, e.g.
  ``error: objects[1].size[2]: must be > 0``), an unknown ``--formats`` / ``--layers`` entry,
  or a command-line usage error (argparse's own convention);
* ``3`` a missing optional dependency (PNG requested without ``cairosvg`` / ``resvg``, an STL /
  PLY mesh without ``trimesh``).

Warnings of the rendered document go to stderr as ``warning: <CODE> [ids]: message``
(suppressed by ``--quiet``); errors always go to stderr.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .errors import SceneError
from .io import load_expanded_scene
from .io.cli import add_import_parser
from .output.geometry_json import dumps
from .output.png import write_png
from .output.svg import HIDDEN_STYLES, LAYER_ORDER, write_svg
from .pipeline import compose, project_scene, shadow_geometry
from .scene import load_camera

FORMATS = ("svg", "json", "png")

EXIT_OK = 0
EXIT_IO = 1
EXIT_INPUT = 2
EXIT_MISSING_DEPENDENCY = 3


def _split(value, allowed, what: str):
    """Comma-separated subset of ``allowed`` (order preserved, duplicates dropped) or ``None``."""
    if value is None:
        return None
    items = []
    for it in (v.strip() for v in value.split(",")):
        if not it:
            continue
        if it not in allowed:
            raise SceneError(f"--{what}", f"unknown {what[:-1]} {it!r}; choose from {', '.join(allowed)}")
        if it not in items:
            items.append(it)
    if not items:
        raise SceneError(f"--{what}", f"needs at least one of {', '.join(allowed)}")
    return items


def _run(scene_path, camera_path, hidden_lines=None, quiet=False):
    scene, notes = load_expanded_scene(scene_path)
    _print_notes(notes, quiet)
    camera = load_camera(camera_path) if camera_path else None
    A = shadow_geometry(scene)
    B = project_scene(scene, A, camera=camera)
    return scene, compose(scene, B, hidden_lines=hidden_lines)


def _print_notes(notes: list, quiet: bool) -> None:
    """Importer notes of the scene expansion (contract §5.0.2): stderr, ``note:`` prefix."""
    if quiet:
        return
    for n in notes:
        print(f"note: {n['code']} {n['ids']}: {n['message']}", file=sys.stderr)


def _print_warnings(doc: dict, quiet: bool) -> None:
    if quiet:
        return
    for w in doc["warnings"]:
        print(f"warning: {w['code']} {w['ids']}: {w['message']}", file=sys.stderr)


def cmd_render(args) -> int:
    formats = _split(args.formats, FORMATS, "formats") or ["svg", "json"]
    layers = _split(args.layers, LAYER_ORDER, "layers")
    scene, doc = _run(args.scene, args.camera, hidden_lines=args.hidden_lines, quiet=args.quiet)
    if layers is None:
        layers = scene["output"]["layers"]
    dpi = scene["output"]["png_dpi"] if args.dpi is None else args.dpi
    if dpi <= 0:
        raise SceneError("--dpi", "must be > 0")
    os.makedirs(args.outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.scene))[0]
    hidden_style = scene["output"].get("hidden_style", "dashed") if args.hidden_style is None else args.hidden_style
    svg = write_svg(doc, layers=layers, hidden_style=hidden_style)
    outputs = []
    if "svg" in formats:
        outputs.append((stem + ".svg", svg.encode("utf-8")))
    if "json" in formats:
        outputs.append((stem + ".json", (dumps(doc) + "\n").encode("utf-8")))
    if "png" in formats:
        try:
            png = write_png(svg, dpi=dpi)
        except ImportError as exc:
            print(f"error: PNG output is unavailable: {exc}", file=sys.stderr)
            return EXIT_MISSING_DEPENDENCY
        outputs.append((stem + ".png", png))
    for name, data in outputs:
        path = os.path.join(args.outdir, name)
        with open(path, "wb") as fh:
            fh.write(data)
        if not args.quiet:
            print(path)
    _print_warnings(doc, args.quiet)
    return EXIT_OK


def cmd_validate(args) -> int:
    scene, notes = load_expanded_scene(args.scene)
    _print_notes(notes, args.quiet)
    if not args.quiet:
        print(f"ok: {len(scene['objects'])} object(s), {len(scene['lights'])} light(s), "
              f"{len(scene['receivers'])} receiver(s)")
    return EXIT_OK


def cmd_stages(args) -> int:
    scene, notes = load_expanded_scene(args.scene)
    _print_notes(notes, args.quiet)
    camera = load_camera(args.camera) if args.camera else None
    A = shadow_geometry(scene)
    B = project_scene(scene, A, camera=camera)
    text = dumps({"A": A, "B": _stage_b_without_a(B)}) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        if not args.quiet:
            print(args.output)
    else:
        sys.stdout.write(text)
    return EXIT_OK


def _fmt_point(p) -> str:
    if p is None:
        return "none"
    return f"({p[0]:.4f}, {p[1]:.4f})"


def warning_table(warnings: list) -> str:
    """Fixed-width ``code | ids | message`` table of a document's warnings (``info`` output)."""
    if not warnings:
        return "warnings: none"
    rows = [(w["code"], ", ".join(w["ids"]) or "-", w["message"]) for w in warnings]
    w0 = max(len("code"), max(len(r[0]) for r in rows))
    w1 = max(len("ids"), max(len(r[1]) for r in rows))
    lines = [f"warnings: {len(rows)}", f"  {'code':<{w0}}  {'ids':<{w1}}  message",
             f"  {'-' * w0}  {'-' * w1}  {'-' * 7}"]
    lines.extend(f"  {c:<{w0}}  {i:<{w1}}  {m}" for c, i, m in rows)
    return "\n".join(lines)


def cmd_info(args) -> int:
    scene, doc = _run(args.scene, args.camera)
    hz, con = doc["horizon"], doc["construction"]
    print(f"scene: {args.scene}")
    print(f"objects: {len(scene['objects'])} ({', '.join(o['id'] + ':' + o['type'] for o in scene['objects'])})")
    lt = scene["lights"][0]
    print(f"light: {lt['id']} ({lt['type']})")
    print(f"canvas_mm: {doc['canvas_mm']}")
    print(f"principal point: {_fmt_point(doc['camera']['principal_point'])}")
    v_mm = hz["v_mm"]
    print("horizon v_mm: " + ("none" if v_mm is None else f"{v_mm:.4f}"))
    for axis in ("x", "y", "z"):
        vp = hz["vanishing_points"][axis]
        # contract §2.2: null when the axis is parallel to the picture plane (its lines stay parallel)
        print(f"vanishing point {axis}: " + ("at infinity (axis parallel to the picture plane)" if vp is None
                                             else _fmt_point(vp)))
    lp = con["light_point"]
    if lp is None and con["light_point_at_infinity"] is not None:
        print(f"light point L': at infinity, direction {_fmt_point(con['light_point_at_infinity'])}")
    else:
        print(f"light point L': {_fmt_point(lp)}")
    fp = con["shadow_vp"]
    if fp is None and con["shadow_vp_at_infinity"] is not None:
        print(f"shadow vanishing point F': at infinity, direction {_fmt_point(con['shadow_vp_at_infinity'])}")
    else:
        print(f"shadow vanishing point F': {_fmt_point(fp)}")
    print(f"points: {len(doc['points'])}, edges: {len(doc['edges'])}, shadows: {len(doc['shadows'])}, "
          f"rays: {len(con['rays'])}, checks: {len(con['checks'])}")
    if con["checks"]:
        print(f"construction self-check max error: {max(c['max_error_mm'] for c in con['checks']):.3e} mm")
    _print_receivers(doc)
    print(warning_table(doc["warnings"]))
    return EXIT_OK


def _print_receivers(doc: dict) -> None:
    """``info``: one line per receiver (contract §5.0.7): bounded / unbounded, plane, ``lit`` and ``casts``
    per light (M4)."""
    receivers = doc.get("receivers", [])
    print(f"receivers: {len(receivers)}")
    for k, r in enumerate(receivers):
        kind = "unbounded" if r["bounds"] is None else f"bounded, {len(r['bounds'])} vertices"
        plane = ", ".join(f"{v:g}" for v in r["plane"])
        lit = ", ".join(f"{lid}={'yes' if v else 'no'}" for lid, v in r["lit"].items()) or "-"
        casts = ", ".join(f"{lid}={'yes' if v else 'no'}" for lid, v in r["casts"].items()) or "-"
        default = " (default)" if k == 0 else ""
        print(f"  {r['id']}{default}: {kind}, plane [{plane}]; lit: {lit}; casts: {casts}")


def _stage_b_without_a(B: dict) -> dict:
    """``stages``: ``B["A"]`` is the stage A itself (contract §5.0.7), so B is written without it (A once)."""
    return {k: v for k, v in B.items() if k != "A"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="castplane", description="Perspective shadow construction drawing.")
    parser.add_argument("--version", action="version", version=f"castplane {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    quiet = argparse.ArgumentParser(add_help=False)
    quiet.add_argument("-q", "--quiet", action="store_true", help="print nothing but errors")
    camera = argparse.ArgumentParser(add_help=False)
    camera.add_argument("--camera", metavar="JSON",
                        help="camera override: a JSON file holding a camera block or a scene with one")

    p = sub.add_parser("render", parents=[quiet, camera], help="render a scene to SVG / JSON / PNG")
    p.add_argument("scene")
    p.add_argument("-o", "--outdir", required=True, help="output directory (created if missing)")
    p.add_argument("--formats", metavar="LIST", help="comma-separated subset of svg,json,png (default svg,json)")
    p.add_argument("--layers", metavar="LIST",
                   help="comma-separated subset of the six layer ids (default: the scene's output.layers)")
    p.add_argument("--dpi", type=float, help="PNG resolution (default: the scene's output.png_dpi)")
    # M4 (contract §5.1.6.6 / §5.0.7): hidden-line switches, passed to the renderer (the scene is not rewritten)
    hl = p.add_mutually_exclusive_group()
    hl.add_argument("--hidden-lines", dest="hidden_lines", action="store_true", default=None,
                    help="classify hidden lines by sampling (default: the scene's output.hidden_lines)")
    hl.add_argument("--no-hidden-lines", dest="hidden_lines", action="store_false", default=None,
                    help="draw every line as visible")
    p.add_argument("--hidden-style", choices=HIDDEN_STYLES, default=None,
                   help="dashed: hidden runs dashed in the *.hidden groups; omit: those groups empty "
                        "(default: the scene's output.hidden_style)")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("validate", parents=[quiet], help="validate a scene file")
    p.add_argument("scene")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("stages", parents=[quiet, camera], help="dump the stage A / B intermediates as canonical JSON")
    p.add_argument("scene")
    p.add_argument("-o", "--output", help="write to this file instead of stdout")
    p.set_defaults(func=cmd_stages)

    p = sub.add_parser("info", parents=[camera], help="print horizon, vanishing points, L', F' and the warning table")
    p.add_argument("scene")
    p.set_defaults(func=cmd_info)

    add_import_parser(sub)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SceneError as exc:
        print(f"error: {exc.field}: {exc.message}" if exc.field else f"error: {exc.message}", file=sys.stderr)
        return EXIT_INPUT
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_IO
    except ImportError as exc:
        print(f"error: missing optional dependency: {exc}", file=sys.stderr)
        return EXIT_MISSING_DEPENDENCY


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
