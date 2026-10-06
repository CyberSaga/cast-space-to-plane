#!/usr/bin/env python3
"""Spec §8 performance benchmark (contract §4): the M3 benchmark scene through the full pipeline.

Targets (spec §8, measured on the deterministic benchmark scene of
:func:`tests.reference.random_scenes.make_benchmark_scene`: 100 primitives, ≈10k mesh
edges, one point light, one receiver):

* **full render** ``shadow_geometry + project_scene + compose + write_svg + geometry_json.dumps``
  in < 1 s;
* **camera-only re-render** ``project_scene + compose + write_svg`` with the cached stage A
  in < 100 ms (the interactive budget of spec §3 / §9).

Usage::

    python3 benchmarks/bench.py [-n REPS] [--objects N] [--no-curved] [--gate both|full|none]
                                [--profile] [--json]

The script prints min / median of each timing over ``REPS`` repetitions and PASS / FAIL
against the targets.  The exit status follows ``--gate``: ``both`` (the default, the
contract as written) is 0 only when both targets pass, ``full`` gates on the full-render
target alone (the camera-only row is then informational), ``none`` always exits 0.  The
camera-only path is also timed with the cyclic garbage collector disabled, as an
informational row that shows the collector's share (the library never touches the
collector).  With ``--profile`` the slowest functions of each path are listed
(``cProfile``).  It is not part of the default test suite (see ``benchmarks/README.md``).
"""

from __future__ import annotations

import argparse
import cProfile
import gc
import io
import json
import pathlib
import pstats
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import castplane  # noqa: E402
from castplane.output import geometry_json  # noqa: E402
from castplane.output.svg import write_svg  # noqa: E402
from tests.reference import random_scenes  # noqa: E402

TARGET_FULL_S = 1.0
TARGET_CAMERA_S = 0.1
GATES = ("both", "full", "none")


def exit_status(ok_full: bool, ok_cam: bool, gate: str = "both") -> int:
    """Exit status of the script: ``both`` needs both targets, ``full`` only the full-render
    target (the camera-only row is informational), ``none`` never fails."""
    if gate == "both":
        return 0 if (ok_full and ok_cam) else 1
    if gate == "full":
        return 0 if ok_full else 1
    if gate == "none":
        return 0
    raise ValueError(f"unknown gate {gate!r} (one of {', '.join(GATES)})")


def full_render(scene: dict) -> tuple[dict, str, str]:
    """Stages A, B, C, the SVG and the JSON text (spec §8 "含 SVG 輸出")."""
    A = castplane.shadow_geometry(scene)
    B = castplane.project_scene(scene, A)
    doc = castplane.compose(scene, B)
    svg = write_svg(doc, layers=scene["output"]["layers"])
    text = geometry_json.dumps(doc)
    return doc, svg, text


def camera_render(scene: dict, A: dict, camera: dict) -> str:
    """Stages B and C plus the SVG with a cached stage A (spec §8 "只換相機重算")."""
    B = castplane.project_scene(scene, A, camera=camera)
    doc = castplane.compose(scene, B)
    return write_svg(doc, layers=scene["output"]["layers"])


def timeit(fn, reps: int) -> list[float]:
    out = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        out.append(time.perf_counter() - t0)
    return out


def timeit_no_gc(fn, reps: int) -> list[float]:
    """:func:`timeit` with the cyclic garbage collector disabled during the calls (and a full
    collection before each one, so that no deferred work leaks into the timing)."""
    out = []
    enabled = gc.isenabled()
    try:
        for _ in range(reps):
            gc.collect()
            gc.disable()
            t0 = time.perf_counter()
            fn()
            out.append(time.perf_counter() - t0)
            gc.enable()
    finally:
        if enabled:
            gc.enable()
    return out


def profile(fn, limit: int = 15) -> str:
    pr = cProfile.Profile()
    pr.enable()
    fn()
    pr.disable()
    buf = io.StringIO()
    pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(limit)
    return buf.getvalue()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-n", "--reps", type=int, default=5, help="repetitions per timing (default 5)")
    ap.add_argument("--objects", type=int, default=100, help="number of primitives (default 100)")
    ap.add_argument("--no-curved", action="store_true", help="prisms only (no cylinder / cone / sphere)")
    ap.add_argument("--gate", choices=GATES, default="both",
                    help="which targets decide the exit status (default both; full: camera-only row informational)")
    ap.add_argument("--profile", action="store_true", help="print cProfile hot spots of both paths")
    ap.add_argument("--json", action="store_true", help="print the measurements as JSON instead of text")
    args = ap.parse_args(argv)

    raw = random_scenes.make_benchmark_scene(args.objects, include_curved=not args.no_curved)
    scene = castplane.load_scene(raw)
    n_edges = random_scenes.count_edges(raw)
    other_camera = dict(scene["camera"], position=[6.0, -28.0, 12.0], target=[0.0, 0.0, 0.5], roll_deg=3.0)

    # warm-up (imports, numpy kernels) and the cached stage A for the camera-only path
    doc, svg, text = full_render(scene)
    A = castplane.shadow_geometry(scene)

    t_full = timeit(lambda: full_render(scene), args.reps)
    t_cam = timeit(lambda: camera_render(scene, A, other_camera), args.reps)
    t_cam_nogc = timeit_no_gc(lambda: camera_render(scene, A, other_camera), args.reps)
    t_stage_a = timeit(lambda: castplane.shadow_geometry(scene), args.reps)
    t_svg = timeit(lambda: write_svg(doc, layers=scene["output"]["layers"]), args.reps)
    t_json = timeit(lambda: geometry_json.dumps(doc), args.reps)

    result = {
        "objects": len(scene["objects"]),
        "mesh_edges": n_edges,
        "document_edges": len(doc["edges"]),
        "points": len(doc["points"]),
        "svg_bytes": len(svg),
        "json_bytes": len(text),
        "warnings": sorted({w["code"] for w in doc["warnings"]}),
        "reps": args.reps,
        "full_render_s": {"min": min(t_full), "median": statistics.median(t_full), "target": TARGET_FULL_S},
        "camera_only_s": {"min": min(t_cam), "median": statistics.median(t_cam), "target": TARGET_CAMERA_S},
        "camera_only_no_gc_s": {"min": min(t_cam_nogc), "median": statistics.median(t_cam_nogc)},
        "stage_a_s": {"min": min(t_stage_a), "median": statistics.median(t_stage_a)},
        "svg_s": {"min": min(t_svg), "median": statistics.median(t_svg)},
        "json_s": {"min": min(t_json), "median": statistics.median(t_json)},
    }
    ok_full = result["full_render_s"]["min"] < TARGET_FULL_S
    ok_cam = result["camera_only_s"]["min"] < TARGET_CAMERA_S
    result["pass"] = {"full_render": ok_full, "camera_only": ok_cam}
    result["gate"] = args.gate
    status = exit_status(ok_full, ok_cam, args.gate)

    if args.json:
        print(json.dumps(result, indent=1, sort_keys=True))
    else:
        print(f"benchmark scene: {result['objects']} primitives, {n_edges} mesh edges "
              f"({result['document_edges']} drawn edges, {result['points']} named points), "
              f"SVG {len(svg) / 1024:.0f} kB, JSON {len(text) / 1024:.0f} kB, warnings {result['warnings']}")
        print(f"repetitions: {args.reps}")

        def row(name, t, target=None):
            line = f"  {name:<34} min {min(t) * 1e3:8.1f} ms   median {statistics.median(t) * 1e3:8.1f} ms"
            if target is not None:
                line += f"   target < {target * 1e3:6.0f} ms   {'PASS' if min(t) < target else 'FAIL'}"
            print(line)

        row("full render (A+B+C+SVG+JSON)", t_full, TARGET_FULL_S)
        row("camera-only re-render (B+C+SVG)", t_cam, TARGET_CAMERA_S)
        row("  same, cyclic GC disabled", t_cam_nogc)
        row("  stage A only", t_stage_a)
        row("  SVG writer only", t_svg)
        row("  JSON dumps only", t_json)
        print(f"RESULT: {'PASS' if status == 0 else 'FAIL'} (gate: {args.gate})")

    if args.profile:
        print("\n=== cProfile: full render ===")
        print(profile(lambda: full_render(scene)))
        print("=== cProfile: camera-only re-render ===")
        print(profile(lambda: camera_render(scene, A, other_camera)))
    return status


if __name__ == "__main__":
    sys.exit(main())
