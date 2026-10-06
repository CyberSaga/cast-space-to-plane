# castplane (TypeScript port of the core)

The TypeScript port of the castplane core (contract `docs/ARCHITECTURE.md` §5.4): scene validation, the three-stage
pipeline (stage A camera independent, stage B projection, stage C the spec §6.2 geometry document), the deterministic
JSON writer and the spec §6.1 SVG writer. Python (`castplane/`) is the reference implementation; the port is accepted
against the conformance set `tests/conformance/` (34/34 cases at set v3). Zero runtime dependencies; the core under
`src/` compiles with `types: []` and `lib: ["ES2022"]`, so it runs unchanged in node and in the browser.

## Build and test

```sh
npm ci                      # at the repository root (npm workspace)
npm run -w ts build         # tsc -p tsconfig.json && tsc -p tsconfig.test.json  ->  ts/build/
npm run -w ts test          # build + node --test build/test/*.test.js
node ts/scripts/render.mjs examples/basic.json out/   # dev helper: out/basic.svg + out/basic.json
python3 tools/compare_svg.py                          # dev tool: SVG text of both implementations, case by case
```

Test suites (`test/`, `node:test`): `conformance` (the 34 cases with the rules of `tests/conformance/rules.json`,
read from the repository, plus the comparator self-tests), `geometry_json` (writer parity on every expected file,
`py_repr`, `cmp_code_points`, `INT_KEYS`), `svg` (`fmt` table and exact-rounding identity, layer structure),
`determinism` (byte-identical re-renders, camera-free blocks for two cameras, stage A camera independence, frozen `A`),
`analytic` (the spec §7.2 hand values), `camera`, `degenerate` (spec §5.7 rows), `scene` (validation rows),
`numerics` (`pymod`, `pyimod`, `py_round`, Jacobi condition numbers, the `%` and neutrality grep rules), `errors`
(`WARNING_CODES` equals `castplane/errors.py`), `mesh_shadow`.

## API

```ts
import { load_scene, shadow_geometry, project_scene, compose, write_svg, dumps, render } from "castplane";

const scene = load_scene(json);              // validated, defaults filled (throws SceneError {field, detail})
const A     = shadow_geometry(scene);         // stage A: never touches scene.camera; reuse it for every camera
const B     = project_scene(scene, A, camera); // stage B: optional camera override (a spec §4 camera block)
const doc   = compose(scene, B);              // stage C: the spec §6.2 document (read-only data)
const svg   = write_svg(doc, layers);         // layered SVG string
const text  = dumps(doc);                     // deterministic JSON (Python json.dumps(sort_keys, indent=1) byte format)
const out   = render(scene, camera);          // {geometry: doc, svg}
```

Function names are the Python names (snake_case); see `docs/USAGE.md` §4 and contract §5.4.2 for the module map.
