# Benchmarks (spec §8)

`bench.py` measures the two spec §8 performance targets on the deterministic M3
benchmark scene built by `tests.reference.random_scenes.make_benchmark_scene`:
100 primitives (prisms on 33/34-gon bases plus a few cylinders, cones and one
sphere; ≈10k mesh edges), one point light, one ground receiver.

| path | what is timed | target |
| --- | --- | --- |
| full render | `shadow_geometry` + `project_scene` + `compose` + `write_svg` + `geometry_json.dumps` | < 1 s |
| camera-only re-render | `project_scene` + `compose` + `write_svg` with a cached stage A | < 100 ms |

The benchmark is **not** part of the default `pytest` suite (it would dominate its
run time and depends on the machine).  Run it from the repository root:

```sh
python3 benchmarks/bench.py                # 5 repetitions, min / median, PASS / FAIL
python3 benchmarks/bench.py -n 20          # more repetitions
python3 benchmarks/bench.py --profile      # cProfile hot spots of both paths
python3 benchmarks/bench.py --json         # machine-readable measurements
python3 benchmarks/bench.py --no-curved    # prisms only
```

The exit status is 0 when both targets pass and 1 otherwise, so the script can be
used as a CI gate (`python3 benchmarks/bench.py || exit 1`).  Timings are the
minimum over the repetitions (the least noisy estimate of the cost of the code
itself); the median is printed alongside.  Stage A alone, the SVG writer alone and
the JSON serialisation alone are reported for orientation.

Determinism of the scene: `make_benchmark_scene` is seeded, so every run measures
exactly the same input; `tests/test_reference.py` checks that the scene stays the
same and carries ≈10k edges.

## Current status (M3, 2026-10-06)

Measured with `python3 benchmarks/bench.py -n 3` on the CI container (Python 3.13,
numpy; timings are the minimum over the repetitions, the median in brackets):

| path | measured | target | status |
| --- | --- | --- | --- |
| full render | 913 ms (1039 ms) | < 1 s | marginal: the minimum passes, the median does not, so the exit status flips between runs |
| camera-only re-render | 528 ms (548 ms) | < 100 ms | **FAIL** (≈5× over) |
| stage A only | 114 ms (132 ms) | – | – |
| SVG writer only | 105 ms (140 ms) | – | – |
| JSON dumps only | 341 ms (410 ms) | – | – |

The §8 targets are therefore **not met** yet.  The script itself is correct (min of the
repetitions against the target, exit status 1); the hot spots are in `castplane/pipeline.py`
and `castplane/output/` (per-object Python loops in `project_scene`, the recursive
`canonical()` in `compose`, per-coordinate string formatting in the SVG writer), not in the
benchmark harness.  Until they are vectorised the benchmark must not be used as a blocking
CI gate; treat a PASS of the full-render row as noise-dependent.
