# Benchmarks (spec §8)

`bench.py` measures the two spec §8 performance targets on the deterministic M3
benchmark scene built by `tests.reference.random_scenes.make_benchmark_scene`:
100 primitives (prisms on 33/34-gon bases plus a few cylinders, cones and one
sphere; ≈10k mesh edges), one point light, one ground receiver.  Since M7 step 1
(contract §5.4.9, §5.0.9) the scene is a **committed file**,
`scenes/benchmark_100.json`, which `bench.py` loads under its default arguments;
only the variants (`--objects N` ≠ 100, `--no-curved`) are generated.  The
TypeScript benchmark reads the same file, so both measure the same input bytes.

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
python3 benchmarks/bench.py --hidden-lines # M4: + full render with output.hidden_lines on (informational)
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

## The committed scene file (M7 step 1)

```sh
python3 benchmarks/export_scene.py     # rewrites scenes/benchmark_100.json and scenes/benchmark_100.build.json
```

`export_scene.py` writes `make_benchmark_scene()` through `geometry_json.canonical` +
`json.dumps(sort_keys=True, indent=1)` + newline (6748 floats, 4 ints, 213 strings) and records
the build that wrote it in `benchmark_100.build.json` (`{"python": …, "numpy": …}`).  Lock rule
(`tests/test_bench.py::test_benchmark_scene_file_matches_generator`): the file must equal the
generator's output byte for byte when the running NumPy version equals the recorded one (a
NumPy `Generator` bit stream is not frozen across releases, NEP 19); on another NumPy the
committed file and the fresh scene must both load and have the same object count, types and
mesh edge count.  Refresh the file only deliberately (and say so in the commit).

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

## M7 step 1 (2026-10-06): the committed file `scenes/benchmark_100.json`

`python3 benchmarks/bench.py -n 5 --gate full`, three consecutive runs, now reading the committed
file (byte-identical to the generator's scene on this build, so the measured document is the same
as before: 100 primitives, 10726 mesh edges, 9030 drawn edges, 15171 named points). This container
is slower than the one of the M3 table above: the pre-step-1 `bench.py` (generating the scene) on
the same container measured full render 592 ms (695), camera-only 189 ms (195) in one run. The
gate is unchanged (`--gate full`, D17); the camera-only row stays informational until the
TypeScript measurement of §5.4.9.

| path | run 1 | run 2 | run 3 | target | status |
| --- | --- | --- | --- | --- | --- |
| full render | 539 ms (599) | 553 ms (645) | 554 ms (584) | < 1 s | **PASS** (3/3) |
| camera-only re-render | 156 ms (164) | 165 ms (182) | 164 ms (165) | < 100 ms | FAIL (informational, D17) |
| same, cyclic GC disabled | 143 ms (148) | 147 ms (150) | 144 ms (153) | – | informational |
| stage A only | 151 ms | 161 ms | 156 ms | – | – |
| SVG writer only | 54 ms | 56 ms | 62 ms | – | – |
| JSON dumps only | 223 ms | 217 ms | 223 ms | – | – |

## M4 (2026-10-07): switch-off cost and the `--hidden-lines` row

Contract §5.1.6.6 / §5.0.9: the hard gate stays `python3 benchmarks/bench.py --gate full` on the
committed scene with hidden lines **off** (unchanged; it exited 0 in all six runs below). The M4 keys
(`hidden_lines`, `receivers`, `construction.per_receiver`, `runs`, `visibility`, `hidden_polylines`,
`polygon_edges`) are the only switch-off cost. "before M4" is the branch point `fb17986`
(`git archive` of it, run from its own tree); "after M4" is the M4 worktree (`--hidden-lines` adds the
row `full render, hidden lines on`, informational, soft target < 5 s). `python3 benchmarks/bench.py -n 5
--gate full [--hidden-lines] --json`, three consecutive runs each, on the same container (Python
3.13.16, numpy 2.5.3; min over the repetitions, median in brackets):

| path | before M4: run 1 | run 2 | run 3 | after M4: run 1 | run 2 | run 3 | target |
| --- | --- | --- | --- | --- | --- | --- | --- |
| full render (switch off) | 343 ms (365) | 355 ms (358) | 337 ms (372) | 365 ms (386) | 295 ms (342) | 362 ms (368) | < 1 s, **PASS** 6/6 |
| camera-only re-render | 108 ms (114) | 115 ms (129) | 86 ms (88) | 108 ms (111) | 109 ms (111) | 111 ms (127) | < 100 ms (informational, D17) |
| same, cyclic GC disabled | 89 ms | 93 ms | 75 ms | 91 ms | 91 ms | 87 ms | – |
| stage A only | 83 ms | 65 ms | 84 ms | 78 ms | 80 ms | 84 ms | – |
| SVG writer only | 33 ms | 27 ms | 34 ms | 32 ms | 36 ms | 43 ms | – |
| JSON dumps only | 129 ms | 100 ms | 142 ms | 109 ms | 132 ms | 139 ms | – |
| full render, hidden lines on | – | – | – | 958 ms (1076) | 1126 ms (1208) | 932 ms (1219) | soft < 5 s (informational): pass 3/3 |

| size (switch off) | before M4 | after M4 | change |
| --- | --- | --- | --- |
| JSON bytes | 10 484 284 | 10 628 057 | +143 773 (+1.4 %): the added keys with their switch-off values |
| SVG bytes | 1 960 727 | 1 960 727 | 0 (the SVG is byte-identical with the switch off, §5.1.8) |
| JSON bytes, hidden lines on | – | 12 027 699 | +13.2 % over switch-off (runs, `polygon_edges`, `hidden_polylines`) |
| SVG bytes, hidden lines on | – | 2 430 336 | +24.0 % (hidden sub-groups, split visible runs) |

The switch-off rows before and after M4 lie within the container's run-to-run noise (±15 %); the
document has the same 9030 drawn edges and 15171 named points. With hidden lines on the full render
takes ≈ 1 s, a fifth of the soft target: every edge, generator, conic interval and shadow-polygon
edge is sampled at 1 mm (≥ 8 samples) against the exact occluders of the 100 primitives, with the
image-bounds cull of §5.1.6.4.

## M5 part 1 (2026-10-07): features-off delta of the mesh pipeline

`python3 benchmarks/bench.py -n 5 --gate full` on the committed `scenes/benchmark_100.json` (no `mesh`
object, so this measures what the M5 hooks cost a scene that does not use them), three interleaved
runs on the same container: "before" is the tree at `fb17986` (the branch point of `wt/m5`), "after"
is `wt/m5` with steps 1–4 and 7. The document is byte-identical (same sizes, `warnings []`). Minimum
over the repetitions, the median in brackets.

| path | before run 1 | before run 2 | before run 3 | after run 1 | after run 2 | after run 3 |
| --- | --- | --- | --- | --- | --- | --- |
| full render | 507 ms (561) | 516 ms (531) | 531 ms (549) | 513 ms (565) | 535 ms (549) | 545 ms (573) |
| camera-only re-render | 149 ms (152) | 150 ms (184) | 154 ms (166) | 148 ms (153) | 149 ms (150) | 151 ms (154) |
| stage A only | 145 ms | 152 ms | 147 ms | 144 ms | 143 ms | 146 ms |
| SVG writer only | 52 ms | 52 ms | 53 ms | 50 ms | 50 ms | 51 ms |
| JSON dumps only | 215 ms | 210 ms | 207 ms | 215 ms | 203 ms | 206 ms |

The deltas (full render +1 to +4 %, the other rows −2 to +1 %) are inside the container's run-to-run
drift; the full-render gate passes 6/6. The `--scene mesh10k` rows (stage A including the weld, and
the full render) come with PLAN-v2 M5 step 8 (part 2), which adds the scene to `bench.py`.
