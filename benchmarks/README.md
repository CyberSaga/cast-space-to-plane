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
run time and depends on the machine); `tests/test_bench.py` only checks that the
script runs, that its gate logic is right and that the batched kernels of the
performance pass equal the scalar ones.  Run it from the repository root:

```sh
python3 benchmarks/bench.py                # 5 repetitions, min / median, PASS / FAIL per target
python3 benchmarks/bench.py -n 20          # more repetitions
python3 benchmarks/bench.py --gate full    # exit status from the full-render target only
python3 benchmarks/bench.py --profile      # cProfile hot spots of both paths
python3 benchmarks/bench.py --json         # machine-readable measurements (incl. "gate" and "pass")
python3 benchmarks/bench.py --no-curved    # prisms only
```

Timings are the minimum over the repetitions (the least noisy estimate of the cost
of the code itself); the median is printed alongside.  Stage A alone, the SVG writer
alone and the JSON serialisation alone are reported for orientation, and the
camera-only path is timed a second time with the cyclic garbage collector disabled
(`same, cyclic GC disabled`), which shows the collector's share -- the library itself
never touches the collector.

## Exit status and the `--gate` option

`--gate` decides which targets the exit status reflects:

| `--gate` | exit 0 when | use |
| --- | --- | --- |
| `both` (default) | both targets pass | the spec-literal check (§8 names both numbers); still exits 1 so the camera-only miss is never hidden |
| `full` | the full-render target passes; the camera-only row is informational | **the v1 CI gate** (ARCHITECTURE §4 last bullet [decision] / DECISIONS D17: the camera-only target is deferred to M7) |
| `none` | always | measurements only |

The CI gate for v1 is therefore `python3 benchmarks/bench.py --gate full || exit 1`;
`--gate both` is the spec-literal check that will become the gate again once the
camera-only target is met (M7).  The text and the JSON output always name the gate
that produced the status, so a PASS is never ambiguous.

Determinism of the scene: `make_benchmark_scene` is seeded, so every run measures
exactly the same input; `tests/test_reference.py` checks that the scene stays the
same and carries ≈10k edges.

## Current status (M3, 2026-10-06, after the second §8 performance pass)

Measured with `python3 benchmarks/bench.py -n 5`, three consecutive runs on the CI container
(Python 3.13.16, numpy 2.5; the minimum over the repetitions, the median in brackets; the
container's timings drift by about ±15 % between runs and an independent re-run on another
container measured 10–40 % slower than the numbers below):

| path | run 1 | run 2 | run 3 | target | status |
| --- | --- | --- | --- | --- | --- |
| full render | 362 ms (386) | 345 ms (417) | 355 ms (384) | < 1 s | **PASS** (3/3; before the passes: 995 ms) |
| camera-only re-render | 109 ms (119) | 112 ms (120) | 113 ms (119) | < 100 ms | **FAIL** (3/3; before: 493 ms, after the first pass 137–150 ms) |
| same, cyclic GC disabled | 87 ms (91) | 94 ms (95) | 92 ms (94) | – | informational |
| stage A only | 85 ms | 83 ms | 83 ms | – | before: 100 ms |
| SVG writer only | 34 ms | 33 ms | 34 ms | – | before: 109 ms, after the first pass 46–63 ms |
| JSON dumps only | 135 ms | 135 ms | 135 ms | – | before: 260 ms |

The full-render target is met with a wide margin.  The camera-only target is **not met**:
the path takes ≈ 110 ms with the default collector (≈ 90 ms without it) against the 100 ms
target, i.e. the target is missed by ≈ 10 %, and by more on a slower machine.  `docs/ARCHITECTURE.md` §4 now records the [decision] (D17 in `docs/DECISIONS.md`): the
camera-only row stays a target, CI uses `python3 benchmarks/bench.py --gate full`, and closing the
gap is deferred to the M7 interactive-UI work; the default `--gate both` still exits 1 so that the
miss is never hidden.

What the second pass changed (output byte-identical on 61 reference scenes -- the 34 conformance
cases, the 5 examples, two benchmark scenes and 20 generated unbounded / light-behind-camera /
near-camera / concave scenes -- each through two cameras, JSON and SVG): the SVG writer assembles whole `<line/>` / `<polygon/>` / `<path/>` elements
as numpy byte-string arrays (one `tobytes` per group instead of one Python statement per
number; `np.char` only, so NumPy 1.24+ works), stage A caches the camera-free parts of the
document (padded unlit-face tables per light, §3.1 edge record templates, the world
coordinates of every named point as canonical Python lists -- shared by reference with the
documents, see the `castplane.pipeline` docstring), the construction rays / self-checks of a
light are built as flat lists once and sliced per record, polygon drawables are converted
from the surviving vertices only, and the short-row reductions of the ray helpers are
fixed-size expressions.

What is left is the Python floor of the §6.2 document itself on this scene: the camera-only
path creates ≈ 15k point records, 9k edge records and 12.8k ray records (≈ 150k Python
containers, every one a camera-dependent `{...}` / `[u, v]` of the contract's document shape)
and formats ≈ 128k SVG coordinates; the per-element cost (`ndarray.tolist`, one dict literal
per record, ≈ 55 ms in total) plus the ≈ 35 ms numpy work of stages B / C and the ≈ 20 ms
of the cyclic collector (33 generation-0 and 3 generation-1 collections per re-render on
the ≈ 150k new containers, plus one full collection every few re-renders) add up to the
≈ 110 ms measured.  Closing the remaining gap needs either a leaner document (fewer Python
containers per point / edge / ray -- a change of the §6.2 shape or of its Python
representation, e.g. tuples, which the contract's "lists" wording and the existing tests
rule out for v1) or a compiled path, both outside the v1 "numpy only" constraint.  An
interactive host that keeps a stage A cached can recover most of the collector's share
with `gc.freeze()` on the cache and a higher `gc.set_threshold`; the library does not do
this for it.
