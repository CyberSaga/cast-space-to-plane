#!/usr/bin/env python3
"""Export the spec §8 benchmark scene as a committed scene file (contract §5.4.9, §5.0.9).

    python3 benchmarks/export_scene.py

writes

* ``benchmarks/scenes/benchmark_100.json`` -- ``tests.reference.random_scenes.make_benchmark_scene()``
  (100 primitives, ≈10.7k mesh edges, one point light, one receiver) as a spec §4 scene file:
  ``castplane.output.geometry_json.canonical`` + ``json.dumps(sort_keys=True, indent=1)`` + newline;
* ``benchmarks/scenes/benchmark_100.build.json`` -- ``{"python": …, "numpy": …}``, the build that
  wrote it.

``benchmarks/bench.py`` (default arguments) and the TypeScript benchmark read this file, so both
measure the same input bytes on every build.  The scene comes from a seeded NumPy ``Generator``,
whose bit stream is not frozen across NumPy releases (NEP 19); hence the lock rule of
``tests/test_bench.py::test_benchmark_scene_file_matches_generator``: byte equality with the
generator only when the running NumPy version equals the recorded one, otherwise the same object
count, types and mesh edge count.  Re-run this script only to refresh the file deliberately.
"""

from __future__ import annotations

import json
import pathlib
import platform
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy  # noqa: E402

from castplane.output.geometry_json import canonical  # noqa: E402
from tests.reference import random_scenes  # noqa: E402

SCENES = ROOT / "benchmarks" / "scenes"
SCENE_FILE = SCENES / "benchmark_100.json"
BUILD_FILE = SCENES / "benchmark_100.build.json"


def scene_text(scene: dict | None = None) -> str:
    """The exact text of ``benchmark_100.json`` for ``scene`` (default: the generator's scene)."""
    if scene is None:
        scene = random_scenes.make_benchmark_scene()
    return json.dumps(canonical(scene), sort_keys=True, indent=1) + "\n"


def build_text() -> str:
    """The exact text of ``benchmark_100.build.json`` for the running build."""
    return json.dumps({"python": platform.python_version(), "numpy": numpy.__version__}, sort_keys=True, indent=1) + "\n"


def main(argv=None) -> int:
    SCENES.mkdir(parents=True, exist_ok=True)
    SCENE_FILE.write_text(scene_text(), encoding="utf-8")
    BUILD_FILE.write_text(build_text(), encoding="utf-8")
    print(f"wrote {SCENE_FILE.relative_to(ROOT)} and {BUILD_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
