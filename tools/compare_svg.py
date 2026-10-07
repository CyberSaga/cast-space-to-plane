#!/usr/bin/env python3
"""Compare the SVG text of the Python reference and of the TypeScript port (dev tool, contract §5.4.6).

    python3 tools/compare_svg.py [scene.json ...]        # default: every tests/conformance/cases/*.json

Every scene is rendered with ``castplane.render`` and with the built port (``node ts/scripts/render.mjs``, so
``npm run -w ts build`` must have run) and the two SVG strings are compared line by line.  The writers are
specified to emit the same text for the same document (contract §5.4.6); the documents of the two
implementations differ by a few ulps, so a number that sits within rounding of a four-decimal boundary may
legitimately round differently, and that is the only tolerated difference: a differing line is a boundary
difference when its non-numeric text is identical, every differing number differs by exactly one unit of the
fourth decimal, and the reference's unrounded value of that number (the Python SVG written once more with
every number at 17 decimals, same line structure) lies within ``BOUNDARY_TOL`` = 1e-12 mm of a four-decimal
rounding half-way (exact decimal arithmetic).  Such lines are listed for review; any other difference -- a
genuine 1e-4 drift included -- is a mismatch.

This is not a CI gate (the CI gates are the JSON conformance set and the structural SVG tests of
``ts/test/svg.test.ts``).  A scene the port cannot render (``render.mjs`` writes ``<name>.error``: a SceneError, or
a phase-2 part of the port that has not landed yet) is reported as a ``TS render failed`` row and counted
separately; the other scenes are still compared.  Exit status: 0 when the outputs are identical or differ only at
rounding boundaries, 1 on any other difference or a failed TS render, 2 when node or the built port is unavailable.
"""

from __future__ import annotations

import argparse
import decimal
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import castplane  # noqa: E402
import castplane.output.svg as _svg  # noqa: E402
from castplane.scene import load_scene  # noqa: E402

RENDER = ROOT / "ts" / "scripts" / "render.mjs"
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
#: Distance (mm) from a four-decimal rounding half-way within which two implementations may round apart (§5.4.6).
BOUNDARY_TOL = decimal.Decimal("1e-12")


def split_numbers(line: str) -> tuple[list[str], list[float]]:
    """Non-numeric text pieces and the numbers of an SVG line."""
    return NUMBER.split(line), [float(m) for m in NUMBER.findall(line)]


def _hp(x) -> str:
    return f"{float(x) + 0.0:.17f}"


def unrounded_svg(scene) -> str:
    """The Python SVG of ``scene`` with every number written at 17 decimals (exact decimal expansion of the
    double to 1e-17) instead of the four of ``_f``: the same elements and lines, so line ``i`` carries the
    unrounded values of line ``i`` of the real SVG (the writer's structure never depends on the number text)."""
    saved = _svg._f, _svg._fmt_bytes
    _svg._f = _hp
    _svg._fmt_bytes = lambda values: np.array([_hp(v).encode("ascii") for v in np.asarray(values, dtype=np.float64).ravel()],
                                              dtype="S")
    try:
        return castplane.render(scene)["svg"]
    finally:
        _svg._f, _svg._fmt_bytes = saved


def near_boundary(x: float) -> bool:
    """``x`` lies within ``BOUNDARY_TOL`` of a four-decimal rounding half-way (exact arithmetic)."""
    d = decimal.Decimal(x) * 10000
    frac = d - d.to_integral_value(rounding=decimal.ROUND_FLOOR)
    return abs(frac - decimal.Decimal("0.5")) <= BOUNDARY_TOL * 10000


def boundary_difference(a: str, b: str, exact: str | None) -> bool:
    """True when two lines differ only by numbers one unit of the fourth decimal apart whose unrounded reference
    value (the same number of ``exact``, the line at 17 decimals) sits within ``BOUNDARY_TOL`` of a half-way."""
    ta, na = split_numbers(a)
    tb, nb = split_numbers(b)
    if ta != tb or len(na) != len(nb) or exact is None:
        return False
    _te, ne = split_numbers(exact)
    if len(ne) != len(na):
        return False
    return all(x == y or (abs(abs(x - y) - 1e-4) <= 1e-9 and near_boundary(e)) for x, y, e in zip(na, nb, ne))


def compare(name: str, py: str, ts: str, exact: str | None = None) -> tuple[list[str], list[str]]:
    """``(boundary differences, mismatches)`` of two SVG texts; ``exact`` is :func:`unrounded_svg` of the scene
    (without it no difference is tolerated)."""
    if py == ts:
        return [], []
    a, b = py.split("\n"), ts.split("\n")
    if len(a) != len(b):
        return [], [f"{name}: {len(a)} lines (Python) vs {len(b)} lines (TypeScript)"]
    e = exact.split("\n") if exact is not None else None
    if e is not None and len(e) != len(a):
        e = None
    boundary, mismatch = [], []
    for i, (x, y) in enumerate(zip(a, b)):
        if x == y:
            continue
        ok = boundary_difference(x, y, e[i] if e is not None else None)
        (boundary if ok else mismatch).append(f"{name}:{i + 1}:\n  py: {x[:200]}\n  ts: {y[:200]}")
    return boundary, mismatch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("scenes", nargs="*", type=pathlib.Path, help="scene files (default: the conformance cases)")
    args = parser.parse_args(argv)
    scenes = args.scenes or sorted((ROOT / "tests" / "conformance" / "cases").glob("*.json"))
    node = shutil.which("node")
    if node is None or not (ROOT / "ts" / "build" / "src" / "pipeline.js").exists():
        print("node and a built port (npm run -w ts build) are required", file=sys.stderr)
        return 2
    # render.mjs names its outputs by the file stem: scenes sharing a stem (tests/conformance/cases/wall_and_ground.json
    # and examples/wall_and_ground.json) go to separate output directories, one node run per directory
    # batches hold positions into scenes, so the output-directory map does not depend on object identity
    batches: list[list[int]] = []
    for i, path in enumerate(scenes):
        for batch in batches:
            if all(scenes[j].stem != path.stem for j in batch):
                batch.append(i)
                break
        else:
            batches.append([i])
    with tempfile.TemporaryDirectory() as tmp:
        outdir: list[pathlib.Path] = [pathlib.Path(tmp)] * len(scenes)
        stderr = []
        for k, batch in enumerate(batches):
            out = pathlib.Path(tmp) / str(k)
            run = subprocess.run([node, str(RENDER), *(str(scenes[j]) for j in batch), str(out)], capture_output=True, text=True, check=False)
            if run.returncode not in (0, 1):
                print(run.stderr, file=sys.stderr)
                return 2
            stderr.append(run.stderr)
            for j in batch:
                outdir[j] = out
        boundary, mismatch, failed = [], [], []
        for i, path in enumerate(scenes):
            error = outdir[i] / f"{path.stem}.error"
            if error.exists():
                failed.append(f"{path.stem}: {error.read_text(encoding='utf-8').strip()}")
                continue
            svg_file = outdir[i] / f"{path.stem}.svg"
            if not svg_file.exists():
                print("".join(stderr), file=sys.stderr)
                return 2
            scene = load_scene(path)
            py = castplane.render(scene)["svg"]
            ts = svg_file.read_text(encoding="utf-8")
            b, m = compare(path.stem, py, ts, unrounded_svg(scene) if py != ts else None)
            boundary += b
            mismatch += m
    for line in boundary:
        print(f"boundary difference (tolerated) {line}")
    for line in mismatch:
        print(f"MISMATCH {line}")
    for line in failed:
        print(f"TS render failed {line}")
    print(f"{len(scenes)} scene(s): {len(boundary)} boundary difference(s), {len(mismatch)} mismatch(es), "
          f"{len(failed)} TS render failure(s)")
    return 1 if mismatch or failed else 0


if __name__ == "__main__":
    sys.exit(main())
