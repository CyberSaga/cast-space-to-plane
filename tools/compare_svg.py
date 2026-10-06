#!/usr/bin/env python3
"""Compare the SVG text of the Python reference and of the TypeScript port (dev tool, contract §5.4.6).

    python3 tools/compare_svg.py [scene.json ...]        # default: every tests/conformance/cases/*.json

Every scene is rendered with ``castplane.render`` and with the built port (``node ts/scripts/render.mjs``, so
``npm run -w ts build`` must have run) and the two SVG strings are compared line by line.  The writers are
specified to emit the same text for the same document (contract §5.4.6); the documents of the two
implementations differ by a few ulps, so a number that sits within rounding of a four-decimal boundary may
legitimately round differently.  The tool sees only the written text, not the unrounded values, so it
tolerates a differing line only when its non-numeric text is identical and every differing number differs by
exactly one unit of the fourth decimal; such lines are listed as boundary differences for review.  Any other
difference is a mismatch.

This is not a CI gate (the CI gates are the JSON conformance set and the structural SVG tests of
``ts/test/svg.test.ts``).  Exit status: 0 when the outputs are identical or differ only at rounding
boundaries, 1 on any other difference, 2 when node or the built port is unavailable.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import castplane  # noqa: E402
from castplane.scene import load_scene  # noqa: E402

RENDER = ROOT / "ts" / "scripts" / "render.mjs"
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def split_numbers(line: str) -> tuple[list[str], list[float]]:
    """Non-numeric text pieces and the numbers of an SVG line."""
    return NUMBER.split(line), [float(m) for m in NUMBER.findall(line)]


def boundary_difference(a: str, b: str) -> bool:
    """True when two lines differ only by numbers one unit of the fourth decimal apart."""
    ta, na = split_numbers(a)
    tb, nb = split_numbers(b)
    if ta != tb or len(na) != len(nb):
        return False
    return all(x == y or abs(abs(x - y) - 1e-4) <= 1e-9 for x, y in zip(na, nb))


def compare(name: str, py: str, ts: str) -> tuple[list[str], list[str]]:
    """``(boundary differences, mismatches)`` of two SVG texts."""
    if py == ts:
        return [], []
    a, b = py.split("\n"), ts.split("\n")
    if len(a) != len(b):
        return [], [f"{name}: {len(a)} lines (Python) vs {len(b)} lines (TypeScript)"]
    boundary, mismatch = [], []
    for i, (x, y) in enumerate(zip(a, b)):
        if x == y:
            continue
        (boundary if boundary_difference(x, y) else mismatch).append(f"{name}:{i + 1}:\n  py: {x[:200]}\n  ts: {y[:200]}")
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
    with tempfile.TemporaryDirectory() as tmp:
        run = subprocess.run([node, str(RENDER), *map(str, scenes), tmp], capture_output=True, text=True, check=False)
        if run.returncode != 0:
            print(run.stderr, file=sys.stderr)
            return 2
        boundary, mismatch = [], []
        for path in scenes:
            py = castplane.render(load_scene(path))["svg"]
            ts = (pathlib.Path(tmp) / f"{path.stem}.svg").read_text(encoding="utf-8")
            b, m = compare(path.stem, py, ts)
            boundary += b
            mismatch += m
    for line in boundary:
        print(f"boundary difference (tolerated) {line}")
    for line in mismatch:
        print(f"MISMATCH {line}")
    print(f"{len(scenes)} scene(s): {len(boundary)} boundary difference(s), {len(mismatch)} mismatch(es)")
    return 1 if mismatch else 0


if __name__ == "__main__":
    sys.exit(main())
