# castplane (TypeScript port of the core)

The TypeScript port of the castplane core (contract `docs/ARCHITECTURE.md` §5.4): scene validation, the three-stage
pipeline (stage A camera independent, stage B projection, stage C the spec §6.2 geometry document), the deterministic
JSON writer and the spec §6.1 SVG writer. Python (`castplane/`) is the reference implementation; the port is accepted
against the conformance set `tests/conformance/` (phase 1: 34/34 cases at set v3; phase 2, in progress at set v6:
46 of 50 cases incl. the three hidden-line cases (`src/hidden.ts`, part 2) and the three mesh cases
(`src/meshprep.ts`, part 3); the four multi-light cases are listed as `todo` in `test/conformance.test.ts` until
their part lands, contract §5.4.0 / §5.4.14). The core reads expanded scenes only: a `mesh` object carries its
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
64-ray cap, meshes on bounded receivers). `test/fixtures/mesh_demo.expanded.json` is the Python expansion of
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
