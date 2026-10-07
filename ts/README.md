# castplane (TypeScript port of the core)

The TypeScript port of the castplane core (contract `docs/ARCHITECTURE.md` §5.4): scene validation, the three-stage
pipeline (stage A camera independent, stage B projection, stage C the spec §6.2 geometry document), the deterministic
JSON writer and the spec §6.1 SVG writer, at the full M4–M6 document format of contract §5.0.3: bounded receivers
with folds and per-receiver records, sampled hidden-line removal (`src/hidden.ts`), mesh objects with the
preprocessing pipeline and its fallback (`src/meshprep.ts`), and several lights with per-light shadows, the umbra and
the multi-light SVG groups (`src/umbra.ts`, `src/multilight.ts`). Python (`castplane/`) is the reference
implementation; the port is accepted against the conformance set `tests/conformance/`: phase 1 34/34 cases at set
v3; phase 2 (M7 step 11, contract §5.4.0 / §5.4.14) 50 of 50 cases at set v6; after the final-review merge (the
angular arc pairing at infinity and its base level, the mesh contact tolerance, `scale_A` from the used vertices, the
umbra's zero-width bridging, the right-to-left point-name parse; §5.4 note "Final review fixes ported") **60 of 60
cases at set v7**, both runners green, recorded in the v6 and v7 entries of `tests/conformance/CHANGELOG.md`. The runner `test/conformance.test.ts` is final: one `node:test` test
per case, no todo list (the five phase-2 parts shrank one, part 5 removed it). The SVG of every case and of every
example (the M4–M6 ones `wall_and_ground`, `mesh_demo` and `two_lights` included) is byte-identical to the Python
writer (`tests/test_ts_port.py`, `tools/compare_svg.py`). The core reads expanded scenes only: a `mesh` object carries its
geometry inline (`data`); `objects[i].path` alone is the "must be expanded first" `SceneError` (expand with
`castplane.io.expand_scene` or `castplane import --inline`). Zero runtime dependencies; the core under
`src/` compiles with `types: []` and `lib: ["ES2022"]`, so it runs unchanged in node and in the browser.

## Build and test

```sh
npm ci                      # at the repository root (npm workspace)
npm run -w ts build         # tsc -p tsconfig.json && tsc -p tsconfig.test.json  ->  ts/build/
npm run -w ts test          # build + node --test build/test/*.test.js
node ts/scripts/render.mjs examples/basic.json out/   # dev helper: out/basic.svg + out/basic.json
python3 tools/compare_svg.py                          # dev tool: SVG text of both implementations, case by case
node ts/build/bench/camera_only.js --gate both --reps 20   # spec §8 benchmark (benchmarks/README.md, TS table)
```

Test suites (`test/`, `node:test`): `conformance` (every case with the rules of `tests/conformance/rules.json`,
read from the repository, plus the comparator self-tests), `geometry_json` (writer parity on every expected file,
`py_repr`, `cmp_code_points`, `INT_KEYS`), `svg` (`fmt` table and exact-rounding identity, layer structure),
`determinism` (byte-identical re-renders, camera-free blocks for two cameras, stage A camera independence, frozen `A`),
`analytic` (the spec §7.2 hand values), `camera`, `degenerate` (spec §5.7 rows), `scene` (validation rows),
`numerics` (`pymod`, `pyimod`, `py_round`, Jacobi condition numbers, the `%` and neutrality grep rules), `errors`
(`WARNING_CODES` equals `castplane/errors.py`), `mesh_shadow`, `receivers` (bounded receivers, the bounds clip and
the `wall_and_ground` hand values of contract §5.1.11), `hidden` (sampled hidden-line removal: occluders, the
sampling / bisection rule, the drawn 4-D geometry, the `wall_and_ground_hidden` hand values, run-record invariants on
every case with the switch on, the hidden-run SVG groups), `meshprep` (the `tests/test_meshprep.py` table: weld,
degenerate faces, orientation and nesting parity, the non-manifold fallback mesh, the coplanar merge, edge
classification, `point_inside_mesh`), `mesh_pipeline` (acceptance 1 and 2 of contract §5.2.12, smooth edges, the
64-ray cap, meshes on bounded receivers), `umbra` (the `tests/test_umbra.py` table of the scanline kernel, the
acceptance pieces from the hand drawables, every expected `umbra[]` recomputed bit for bit), `multilight` (the
`multilight.ts` helpers, the hand values of `multilight_two_point_symmetric_box`, the per-light bit identity, the
multi-light SVG groups and opacities, `umbra = false`, hidden lines with two lights), `arc_pairing` (the
`tests/test_arc_pairing.py` / `test_arc_base_level.py` contract: arcs at infinity paired by the angular order of the
crossings, one component per cycle, bit identity with the v1 loop-order code, `light_plane_level` against a
brute-force ray count, `arc_level` and `turns`, the arch / U-wall / spiral scenes of set v7). `test/fixtures/mesh_demo.expanded.json` is the Python expansion of
`examples/mesh_demo.json` that the determinism tests read (kept current by `tests/test_ts_port.py`).

## API

```ts
import { load_scene, shadow_geometry, project_scene, compose, write_svg, dumps, render } from "castplane";

const scene = load_scene(json);              // validated, defaults filled (throws SceneError {field, detail})
const A     = shadow_geometry(scene);         // stage A: never touches scene.camera; reuse it for every camera
const B     = project_scene(scene, A, camera); // stage B: optional camera override (a spec §4 camera block)
const doc   = compose(scene, B, hidden_lines); // stage C: the spec §6.2 document (read-only data); hidden_lines
                                              // (null = scene.output.hidden_lines) runs hidden.classify_document
const svg   = write_svg(doc, layers, hidden_style); // layered SVG string; hidden_style "dashed" | "omit"
const text  = dumps(doc);                     // deterministic JSON (Python json.dumps(sort_keys, indent=1) byte format)
const out   = render(scene, camera, hidden_lines, hidden_style); // {geometry: doc, svg}
```

Function names are the Python names (snake_case); see contract §5.4.2 for the module map and `docs/USAGE.md` §4 for the user guide (API, benchmark, web UI).
