# CLAUDE.md — castplane (cast-space-to-plane)

Exact perspective cast-shadow construction drawings for painters. You give it a scene JSON (objects, lights, receivers,
camera). It returns a deterministic geometry document (spec §6.2 JSON) plus a layered SVG/PNG. The output has shadow
outlines, construction rays L′P′ / F′Q′, vanishing points and the horizon.
Python reference implementation (`castplane/`, numpy only) + a TypeScript port (`ts/`) + a three.js web UI (`web/`).
Milestones M0–M8 are all done (spec §10). There is no open roadmap; changes are fixes or versioned extensions.

## Where the truth lives (read before changing behaviour)

Precedence, highest first:
1. `docs/ARCHITECTURE.md` is the **binding contract** (English). §1–§4 cover v1 (M0–M3) and §5 covers v2 (M4–M8, §5.1 M4 …
   §5.5 M8). Each §5.x ends with a `### Implementation notes` block. Behaviour that the contract text did not already
   describe is appended there as a self-contained `[decision, implementation]` paragraph. Append only: never rewrite
   v1 text, amend by reference.
2. `docs/DECISIONS.md` is the plain-language decision log D1–D70, in **Traditional Chinese**. New decisions get the next
   number (D71…) in the same style: 規格 / 問題 / 決定 / 理由.
3. `docs/spec/spec-v0.1.md` is the original spec (Traditional Chinese). The contract overrides it where marked
   **[decision]**.
4. `tests/conformance/README.md` holds the conformance rules. `docs/PLAN-v2.md` is historical (the M4–M8 order and
   shared-file table).

In the contract, "§N" means the contract and "spec §N" means the spec. User docs are in Traditional Chinese:
`README.md`, `docs/USAGE.md`, `docs/STEP.md`, `examples/README.md`, `tests/conformance/README.md` and
`tests/conformance/CHANGELOG.md`. Code comments, docstrings and the contract are in English. Keep each file in its own
language.

## Commands

```sh
pip install -e '.[dev]'                       # python ≥3.10; extras: mesh (trimesh), png (cairosvg), step (cadquery-ocp)
python -m pytest -q                           # ~2000 tests, ~4 min; use -x / a single file while iterating
python -m pytest -q tests/test_conformance.py # the output contract (60 cases)
python3 benchmarks/bench.py --gate full       # CI perf gate: full render < 1 s (camera-only row informational, D17)
python3 tools/regen_conformance.py --reason "CI dry run" --dry-run   # must report 0 changes unless you mean it

npm ci                                         # node ≥20.19 / ≥22.12; workspaces ts/ and web/
npm test                                       # ts (builds first) + web
node --test --test-reporter=tap ts/build/test/conformance.test.js   # TS runner, one test per case
python3 tools/compare_svg.py                   # Python vs TS SVG text, needs the ts build; expect 0 mismatches
node ts/build/bench/camera_only.js --gate both --reps 20            # TS perf gate (camera-only < 70 ms literal)
npm run -w web build                           # static vite build

castplane render examples/basic.json -o out/   # CLI: render | validate | info | stages | import
```

CI is defined in `.github/workflows/ci.yml`:
- Python 3.10 and 3.13: suite, bench `--gate full`, and the dry run (3.13 only).
- TS on node 20 and 22: build, tests, and the TS runner with fail/skip/todo all 0. The TS bench runs on node 22.
- web: tests and build.

**Run on 3.10 before pushing** if you touch syntax or anything perf-sensitive. CI broke twice on things 3.13 hid:
- f-strings with a backslash in the expression are a SyntaxError before 3.12.
- `json.dumps(indent=…)` is pure Python before 3.13, which is why `geometry_json` has a compact-encode + NumPy re-indent
  fast path. It must stay byte-identical to `json.dumps(indent=1, sort_keys=True, ensure_ascii=False, allow_nan=False)`.

Chromium for Playwright is at `/opt/pw-browsers/chromium`. Never run `playwright install`.

## Architecture in one screen

Pipeline (`castplane/pipeline.py`), stages A → B → C:
- **A** `shadow_geometry(scene)`: world-space shadows, terminators and receivers. **Camera-independent** (spec §7.1
  row 2). `scene_scale_A` excludes the camera and the lights.
- **B** `project_scene(scene, A, camera=None)`: projection, clipping, construction rays and umbra.
- **C** `compose(scene, B, hidden_lines)`: the §6.2 document. `render(scene)` runs A + B + C and writes SVG.
- A camera-only re-render reuses the cached A. Documents share A's camera-free lists **by reference**, so treat
  documents as read-only and `copy.deepcopy` before mutating (docs/USAGE.md "文件是唯讀資料").

The core modules are listed in `docs/ARCHITECTURE.md §1`:
- geometry: `homogeneous`, `light`, `shadow`, `conics`, `curved`, `camera`, `construction`
- M4 hidden lines: `hidden`
- M5 mesh: `meshprep`
- M6 multi-light: `umbra`, `multilight`
- output: `output/geometry_json`, `output/svg`, `output/svg_multilight`, `output/png`

Loaders live **outside the core** in `castplane/io/`: OBJ, glTF, trimesh, Part 21 / STEP, and `castplane import`.
`expand_scene` turns `path`/`step` objects into inline `mesh` data before validation. The core and the TS port never
see a file path.

## Hard invariants (tests enforce them; don't break them)

- **Core depends on numpy only.** Optional deps are confined to loaders and PNG.
- **Bit-deterministic JSON per build.** Floats are canonicalised `x + 0.0` (never `-0.0`) and keys are sorted. Avoid
  reductions over variable-length axes whose order could vary; use fixed-shape expressions or `einsum`.
- **Degenerate geometry warns, never raises.** Warnings use the closed list of **18** codes (`castplane/errors.py`;
  contract §2.9 + §5.0.5), deduped and sorted by (code, ids). Adding a code is a contract change.
  Input errors raise `SceneError(field=<json path>, ...)`, and the CLI exits with code 2.
- **Oriented projective geometry** (D3): finite points have w = +1. The receiver plane has the light on its positive
  side. `normalize_max` keeps the sign. Predicates are `> tol` / `< -tol` with `tol = 1e-9·scene_scale`; the band in
  between counts as degenerate.
- **Construction rays are always 2-D segments** (D4) and are self-checked only where drawn (D18).
- New document fields must be derivable by pure geometry from the scene JSON.
- Function names follow the spec symbols. The TS port keeps the same snake_case names and record shapes (D49).
  It uses `Map` for id indexes (D59).

## Conformance set: the output contract

`tests/conformance/` holds `cases/*.json`, `expected/*.json` and `rules.json`. It is currently **v7 with 60 cases**.
- **Never hand-edit `expected/`.** Regenerate only with
  `tools/regen_conformance.py --case NAME --reason "..."`. That appends `## v<N>` to `tests/conformance/CHANGELOG.md`.
  A full regeneration (no `--case`) is for intentional behaviour changes, with the reason naming every changed case.
- Comparator changes go to `rules.json` and then `--rules-only --reason`. The comparator can never be silently loosened.
- The workflow is: add the case first, generate, review the diff, then change code. Before any geometry change, run
  `--dry-run` and expect 0 changes. A change that does alter bytes is a versioned bump, and the TS port must follow in
  the same change.
- Cases are post-expansion scenes, so mesh cases use inline `data`. Keep cases small: all expected files must stay
  < 3 MiB, and they are at ~2.7 MB now.
- **Bit-exactness holds only on the recorded build.** `tests/build_identity.py::exact_build()` requires the recorded
  NumPy version **and** the kernel fingerprint in `tests/golden/build_fingerprint.json`. OpenBLAS DYNAMIC_ARCH and the
  ufunc SIMD dispatch change last digits across CPUs with the same wheel. Elsewhere, tests fall back to spec §7.5
  tolerances (1e-6 mm image, 1e-9 relative). When regenerating the set, also run `python -m tests.build_identity --write`.
  To reproduce a CI-runner-only diff: `OPENBLAS_CORETYPE=Haswell python -m pytest ...`.
- Don't put new cases on the documented ulp-amplifying boundaries (README rule 3, "已知的跨實作邊界").

## TypeScript port parity

Python is the reference.
- Every Python behaviour change that affects output must be mirrored in `ts/src/<same module>.ts`, using the same
  algorithm, operation order and tie-breaking (contract §5.4.4).
- Port the pinning tests too.
- Both runners must pass every case on the same commit, `compare_svg.py` must report 0 mismatches, and
  `tests/test_ts_port.py` must be green.
- The TS JSON writer reproduces Python `repr` floats (`ts/src/pyfloat.ts`) and the `INT_KEYS` list.
- The SVG writer is byte-identical, with round-half-even at 4 decimals (D53).
- When TS disagrees, assume TS is wrong first. If Python violates the contract, fix Python and bump the conformance set.

## Geometry hot spots (where bugs were)

- **Arcs at infinity** (`shadow.shadow_loop`, D7 → D70). An unbounded shadow loop crosses the light plane 2p times.
  - p ≤ 1 keeps the v1 code verbatim.
  - p ≥ 2 pairs crossings by angular parenthesis matching (outgoing = "(", incoming = ")"; ties incoming first; start
    at the minimum cumulative level) and emits one loop per cycle under `loops`.
  - The base level is pinned by `light_plane_level` / `arc_level` and applied via `turns=c` on the first unbounded loop.
  - It is translation and rotation invariant by construction. Never use origin-dependent azimuths.
  - Tests: `tests/test_arc_pairing.py`, `tests/test_arc_base_level.py`, `test_raycast.py` multi-crossing family.
- **Bounded receivers / anchor rule** (contract §5.1.3.3), **mesh contact tolerance** `max(tol, weld_tolerance)`, and
  `meshprep` `scale_A` over face-referenced vertices only.
- **Umbra** (`umbra.py`, one scanline kernel): step 5 bridges gaps narrower than `tol_mm`. Python and TS piece counts can
  differ when casters stand on the receiver (regions agree; contract §5.3 notes).
- The ray-cast reference (`tests/reference/`) shares **no code** with `castplane`. Keep it independent; IoU ≥ 0.99 is
  the §7.3 gate.

## Known open limits (documented, deliberately not fixed)

- A closed-ring imported mesh (genus ≥ 1) with the lamp in its hole at mid-height draws the complement of its shadow.
  This is a strict xfail.
- STEP files with wrong-type references can crash OCC under `fallback="mesh"`.
- `scene._number` raises `OverflowError` on huge ints instead of a `SceneError`.
- `expand_scene` has no total budget across mesh objects.
- Python camera-only re-render is ~120 ms, missing the 100 ms target under D17. The TS port meets it at ~65 ms.
- Deferred, each needing a versioned conformance bump:
  - `covering_segments` ill-conditioning, which changes 9/60 expected files
  - circle axis direction
  - object-id label anchor
  - two-light umbra piece-count rule for grounded casters

## Working conventions

- Each behaviour fix ships with a test that fails before it, plus:
  - a `[decision, implementation]` note in the relevant `### Implementation notes` block;
  - a `CHANGELOG.md` line;
  - a D-entry if it is a real decision.
- Keep README / USAGE counts in sync: case count, set version, warning-code count, test count.
- Merges keep history: merge commits, no rebase or force-push of shared branches. Don't put model names in commits or
  code beyond the required trailer.
- Benchmarks: record new measurements in `benchmarks/README.md`. Gate literals change only with a new recorded
  measurement, never loosened to absorb a regression.
