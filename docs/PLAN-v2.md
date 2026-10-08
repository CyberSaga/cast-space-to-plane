# PLAN v2 — implementation order for M4–M8

Companion to `docs/ARCHITECTURE.md` §5 (the binding v2 contract) and `docs/DECISIONS.md` D21–D69. Everything here is
derived from §5; where this file and §5 disagree, §5 wins.

## 1. Order and parallelism

```
main ──► M7 step 1 (rules.json, --rules-only, v3)  ── merged first, alone
      │
      ├─► worktree M4 ─────────────┐
      │                            ├─► merge M4 → main (full key-additive regeneration = v4, + 9 cases)
      ├─► worktree M5 ─────────────┘        ▲ M5 rebases on v4, merge → v5 (+ 3 cases)
      │                                     │
      ├─► worktree M7 phase 1 (ts/, web/; accepted against v3 on its branch; no castplane/ edits beyond step 1)
      │
      │   after M4 is on main:   worktree M6 (rebased on M4+M5) ──► merge → v6 (+ 4 cases)
      │   after M5 is on main:   worktree M8 ──────────────────────► merge (no case)
      │
      └─► M7 phase 2 (rebase on main at v6; port the M4–M6 geometry; both runners green on v6)
```

- **Wave 1 (parallel worktrees)**: M4 and M5 (and M7 phase 1, which touches only new files after step 1).
- **Wave 2 (parallel)**: M6 (needs M4; rebased on the merged M4 + M5 `main` before its conformance step), M8 (needs M5),
  M7 phase 1 continuing.
- **Wave 3**: M7 phase 2 (needs everything; owns the merge of the port onto the final format).

### Shared files and the merge rule
A file is *shared* when two worktrees of the same wave edit it. Rule: **append-only hunks in disjoint regions**, no
reformatting, no moving of existing code; the second merger rebases and resolves textually. The owning milestone of a
shared function is listed; the other milestone must not restructure it.

| file | M4 may touch | M5 may touch | M6 may touch (wave 2) | M8 may touch (wave 2) | M7 may touch |
| --- | --- | --- | --- | --- | --- |
| `castplane/scene.py` | append `validate_bounds`, `validate_hidden_output`; one call line each in `validate_receiver` / `validate_output`; `receivers` rules in `validate_scene`; reserved-id check (`hidden`) | `OBJECT_TYPES += ("mesh",)`, `MESH_*` constants, `AXIS_MAP` / `to_z_up`, `validate_mesh_data`, the `mesh` branch of `validate_object` (incl. "expand first" for `path`-only); `read_json` extraction (used by `load_expanded_scene`) | `lights` row of `validate_scene`, `RESERVED_LIGHT_IDS_MULTI` + the multi-light `core` object-id check | `LOADER_TYPES` block **above** the `OBJECT_TYPES` test | — |
| `castplane/errors.py` | append `RECEIVER_UNLIT` (end) | append the 4 `MESH_*` after it | — | — | — |
| `castplane/pipeline.py` | new helpers `_receiver_record`, `_plate_record`, `_shadow_records_for_receiver`; `shadow_geometry` receiver loop; `_project_light` per receiver; `_project_shadows` keyed (light, receiver); `project_scene` stores `B["A"]`; `compose` emits M4 keys and calls `hidden.classify_document`; `render` keywords. Leaves the `build_object` / `_object_light_data` call sites alone | `shadow_geometry` (prep warnings, fallback `clipped = None`), `_object_light_data` fallback branch, `_shadow_record` (`ray_vertices`), new `_fallback_shadow_record`, `_project_polyhedra` (`camera_silhouette`), `_project_shadows` (`ok &= ray_vertices`), `compose` (mesh edge keys) | hooks only: `_project_polyhedra(…, light_ids)`, `project_scene(…, umbra=True)` + `constructions`, `compose` multi-light keys, `multi` to `curved.stage_a_object` | — | — |
| `castplane/curved.py` | `frame` threading, per-receiver `stage_a_object`, `_bounds_clip_pieces`, `_loop_entries` bounds rows | — | `construction_points(…, light_id)`, `stage_a_object(…, multi)`, `_loop_entries` / `_terminator_segment_names` stem names | — | — |
| `castplane/shadow.py` | `receiver_frame`, `bounds_functionals`, `clip_polygon_bounds`, `plate_loop`, `shadow_loop(frame, F)` | — | — | — | — |
| `castplane/primitives.py` | — | `build_object` mesh keys, `local_mesh` mesh branch, `point_inside_solid` mesh branch | — | — | — |
| `castplane/mesh.py` | — | `triangulate_faces`, `edge_smooth` docstring | — | — | — |
| `castplane/output/svg.py` | hidden-run drawing, `hidden_style`, label filter | — | three layer builders branch to `svg_multilight.py` | — | — |
| `castplane/cli.py` | one argument block (`--hidden-lines`, `--no-hidden-lines`, `--hidden-style`); `info` receivers | one import, one `add_import_parser(sub)`, four `load_expanded_scene` call sites (**M5 owns**: it merges first and needs them for `mesh` + `path` scenes; the `import` parser itself lives in `castplane/io/cli.py`) | `info` lights | — (M8 registers `EXPANDERS["step"]` and its options in `io/`, §5.0.2) | — |
| `castplane/io/__init__.py`, `io/cli.py` | — | **M5 owns**: `load_mesh_file`, `SUPPORTED_EXTENSIONS`, `expand_mesh_object`, `EXPANDERS["mesh"]`, `expand_scene`, `load_expanded_scene`, `IMPORT_NOTE_CODES`, the `import` parser with the mesh options | — | adds `EXPANDERS["step"]`, `EXTENSION_LOADERS`, the `STEP_*` notes, the STEP options (`--solid`, `--fallback`) and the extension dispatch | — |
| `castplane/output/geometry_json.py` | — | — | — | — | `allow_nan=False` (step 1) |
| `benchmarks/bench.py` | `--hidden-lines` row, before/after rows | `--scene mesh10k` | `--lights N`, `--no-umbra`, 2 000-edge row | informational rows in README only | default = committed scene file (step 1) |
| `tests/reference/raycast.py` | `first_hit_t` variants, `hit_plate`, `hit_ground` (new functions) | `hit_mesh`, `HITTERS["mesh"]` | — | — | — |
| `tests/reference/random_scenes.py` | — | `make_mesh_scene` | `assemble_scene(objects, lights, camera)`, `make_scene(…, n_lights=1)` | — | — |
| `tests/test_conformance.py` | `runs_rule` (read from `rules.json`) | inline-`data` assertion, `mesh` in coverage | `mm_key_paths` (from `rules.json`), N ≥ 2 / N ≥ 3 coverage | post-expansion sentence in README only | `rules.json` assertion, `case_overrides`, `case_name` argument (step 1) |
| `tests/test_scene.py`, `test_cli.py`, `test_degenerate.py`, `test_bench.py`, `test_svg.py`, `test_raycast.py`, `test_invariants.py` | appended blocks | appended blocks (incl. the `test_cli.py` `documented_commands` regex `(render|validate|info|stages|import)`) | appended blocks | — (all M8 tests live in `tests/test_step.py`) | `test_bench.py` lock test, `test_curved.py` precondition |
| `tests/conformance/README.md`, `CHANGELOG.md` | `### M4 受影面與隱藏線` rows; v4 entry at merge | `### M5 網格` rows; v5 entry | `### M6 多光源` rows; v6 entry | one sentence | rule-2 / rule-3 addenda; v3 entry; v6 "both runners green" line |
| `docs/USAGE.md`, `README.md`, `benchmarks/README.md` | appended rows | appended rows (+ `castplane import` mesh section) | appended rows | appended rows (+ STEP section, `docs/STEP.md`) | USAGE §4, README paragraph, TS bench table |
| `pyproject.toml` | — | extra `mesh` | — | extra `step` (alphabetical) | — |
| `.github/workflows/ci.yml` | — | — | — | — | jobs `ts`, `web`; `tests/test_ts_port.py` in the Python job |

Milestone-only files (no coordination needed): M4 `castplane/hidden.py`, `tests/reference/zbuffer.py`, `tests/test_receivers.py`,
`tests/test_hidden.py`; M5 `castplane/meshprep.py`, `castplane/io/obj.py`, `io/gltf.py`, `io/trimesh_adapter.py`,
`tests/test_meshprep.py`, `tests/test_mesh_pipeline.py`, `tests/test_loaders.py`, `tests/fixtures/meshes/*`; M6
`castplane/umbra.py`, `castplane/multilight.py`, `castplane/output/svg_multilight.py`, `tests/test_umbra.py`,
`tests/test_multilight.py`, `tests/golden/example_basic.svg`; M8 `castplane/io/part21.py`, `io/step.py`,
`tools/make_step_fixtures.py`, `tests/fixtures/step/*`, `tests/test_step.py`, `docs/STEP.md`; M7 `ts/`, `web/`, root
`package.json` / `package-lock.json`, `tests/conformance/rules.json`, `benchmarks/export_scene.py`, `benchmarks/scenes/*`,
`tests/test_ts_port.py`, `tools/compare_svg.py`.

## 2. Per-milestone steps, acceptance tests, conformance cases, benchmark rows

### M7 step 1 (first, alone; §5.4.0, §5.4.8)
Steps: `tests/conformance/rules.json` (v3 content of §5.4.8) + `compare_documents(expected, actual, case_name=None)` reading
`case_overrides`; `tools/regen_conformance.py --rules-only`; the v3 CHANGELOG entry; `tests/test_curved.py::test_stage_b_objects_equals_per_object_loop`;
`geometry_json.py` `allow_nan=False` + test; `benchmarks/export_scene.py` → `benchmarks/scenes/benchmark_100.json` +
`.build.json`; `bench.py` reads the committed file by default; `tests/test_bench.py` lock test; `tests/test_ts_port.py`
(skipping TS checks while `ts/` is absent). Acceptance: Python suite green, `--dry-run` zero drift, CHANGELOG has v3,
no expected file changed.

### M4 (wave 1; §5.1)
Steps (each keeps the suite green): 1 `errors.py` + `scene.py` rows + golden SVG hashes of the 34 cases; A-track 2–5
(`shadow.py` frame / bounds clip / anchor rule, `pipeline.py` receiver helpers, `curved.py` frame threading, stage B/C +
`render` keywords + labels); H-track 6–9 (`hidden.py`, `svg.py` hidden groups, `cli.py` flags, `raycast.py` / `zbuffer.py`
references); closing 10 (`--strip-new-keys`, M4 cases with `--case` in the worktree, bench rows, docs). The A- and H-tracks
touch disjoint files except `compose` → `classify_document` and `render(hidden_style)`.
Acceptance tests: `wall_and_ground` hand values (§5.1.11: `F.lamp.wall = (0,6,3)`, wall quadrilateral `(0.75,6,0)…(−0.75,6,0)`,
fold `(±3/4,6,0)` both ways within 1e-9 m, images `wall.b0' = (−111.5758137, −29.5611244)` …, `L' = (0, 162.8814554)`,
warnings `[]`); `wall_and_ground_hidden` (runs `[0, 23/60]`, `[23/60, 37/60]`, `[37/60, 1]` on `wall.b0→b1`, `mm`
boundaries `85.5415` / `137.6102` of `223.1516`; ground-shadow edge boundary `s = 0.713073`; crate 5 hidden / 7 visible
edges); z-buffer reference ≥ 99 % decided agreement (100 % on box / prism edges), boundaries ±0.15 mm ≥ 98 %; bounds-clip
unit tests (270° U-prism and half-plane → full plate, area 15, 4 vertices); `RECEIVER_UNLIT` four predicates; frame
equivalence (wall rotated to ground, 1e-9 m); byte-identical SVG for all 34 v2 scenes with the switch off; render twice
with the switch on → identical bytes; culled = unculled on 5 scenes; `N` table `0.1, 7.3, 8.0, 1023.9, 4095.9, 5000 mm → 8,
8, 8, 1024, 4096, 4096`, `10.0 → 10`; spec §7.1 rows 1–6 on `wall_and_ground` and `fold_curved_cylinder`; raycast IoU ≥ 0.99
on plates. Conformance: v4 at merge (all 34 key-additive, `--strip-new-keys` zero mismatches) + `wall_and_ground`,
`wall_and_ground_hidden`, `receiver_unlit_wall`, `receiver_directional_wall`, `fold_curved_cylinder`,
`bounded_default_receiver`, `hidden_lines_curved_unbounded`, `hidden_lines_vp_in_canvas`, `concave_prism_on_plate`;
`rules.json` += `runs_rule`, `hidden_polylines`, `interval`, the `per_receiver` mm path. Benchmark rows: `--hidden-lines`
(soft < 5 s); switch-off full render and JSON size before / after M4; `--gate full` unchanged.

### M5 (wave 1; §5.2)
Steps: 1 `errors.py` / `scene.py` (`mesh` rows, usable-face guard, `up` map); 2 `meshprep.py` + `mesh.triangulate_faces` +
`tests/test_meshprep.py`; 3 `primitives.py`; 4 `pipeline.py` (the functions listed in the table above); 5 `castplane/io/`
(`__init__`, `obj`, `gltf`, `trimesh_adapter`, `cli` with the mesh options, `expand_scene`, `load_expanded_scene`,
`IMPORT_NOTE_CODES`) + `pyproject` extra `mesh`; 6 `cli.py`: the one import line, the `add_import_parser(sub)` call and
the four `load_expanded_scene` call sites (M5 owns these; M8 keeps them and adds nothing to `cli.py`); 7 `raycast.py`
`hit_mesh`, `random_scenes.make_mesh_scene`; 8 tests, fixtures, conformance cases (`--case`, after rebasing on v4), docs,
bench `--scene mesh10k`. Steps 2 and 5 are parallel with each other.
Acceptance tests: acceptance 1 (imported split-vertex box == `analytic_unit_box_point_light_overhead` byte-equal after
deleting `smooth` / `camera_silhouette`; shuffled variant by the §5.2.13 rule; end-to-end `box_split.obj` and its `up: "y"`
variant through `load_expanded_scene`); acceptance 2 (open-bottom box: `MESH_NON_MANIFOLD`, 5 loops, front loop
`(−.5,−.5),(−.75,−.75),(.75,−.75),(.5,−.5)` area 0.3125, union = ±0.75 square, IoU 1.0, no rays); buried fallback (4
`s<k>` points); `mesh_smooth_prism16` (2 lateral edges drawn, all cap edges feature); ray cap 64 + `MESH_RAYS_CAPPED`;
weld / degenerate / orientation / merge / classify tables of §5.2.11; `point_inside_mesh`; loaders (OBJ, glTF `.gltf` +
`.bin` + data-URI, GLB, strided accessors, mirrored node, exact Y-up → Z-up `(1,0,2) → (1,−2,0)`); `castplane import` on the
fixture glTF (`focal_length_mm = 38.79273772518993`, both lights kept, `IMPORT_SPOT_AS_POINT`, `node: "Cube"` / `node: 3`,
re-loads); exit codes; determinism; stage A camera independence; spec §7.1 rows 1, 2, 4; raycast IoU on `make_mesh_scene`.
Conformance: v5 = `mesh_box_welded_triangulated`, `mesh_open_bottom_box_fallback`, `mesh_smooth_prism16` (inline `data`;
no existing file changes; `--dry-run` zero drift). Benchmark rows: features-off delta; `--scene mesh10k` stage A and full.

### M6 (wave 2, after M4 on main; §5.3)
Steps: 1 `scene.py` `lights` row + reserved ids; 2 `umbra.py` + `tests/test_umbra.py`; 3 `multilight.py`; 4 `curved.py`
names; 5 `pipeline.py` hooks; 6 `output/svg_multilight.py` + three `if`s in `svg.py`; 7 `cli.py` `info`, USAGE; 8 tests
(`test_multilight.py`, `test_raycast.py` `n_lights`, `test_invariants.py`, `test_degenerate.py`, `test_svg.py` + golden file,
`test_cli.py`, `test_scene.py`, `test_conformance.py`); 9 conformance cases (`--case`, after rebasing on v5); 10 bench
`--lights N`, `--no-umbra`, 2 000-edge row, re-measured N = 1; 11 docs. Steps 2 + 3 and 4 + 6 are parallel.
Acceptance tests: `multilight_two_point_symmetric_box` (per-light bit identity; umbra 3 pieces index-wise within 1e-6 mm,
areas `132.85761502560047`, `1315.4880281807557`, `90.38709809014404`, total `1538.7327412965`; mapped back area 7/6;
`silhouette_lights`; `form_shadow_core` = ±y faces + base; SVG opacities `0.15` / `0.09`, one umbra path with 3 subpaths);
curved two-light scene (name map, grammar round trip); `umbra_from_document` bit for bit; three lights IoU ≥ 0.995 and
permutation invariance; inactive second light; identical lights; light inside box; camera on / below ground;
`umbra=False` → `null`; validation; single-light documents carry no M6 key; the `record_pieces` table (square, overlapping
squares 1.75, hole 0.75, bow-tie 2.0, C-loop 4 pieces 19.0, sliver and merged-vertex cases, bow-tie guard); rigid
equivariance; raycast AND over lights IoU ≥ 0.99; SVG N = 1 `<g id>` list equals the single-light list and matches
`tests/golden/example_basic.svg`; a two-light `wall_and_ground` (per-receiver umbra). Conformance: v6 =
`multilight_two_point_symmetric_box`, `multilight_point_and_directional_curved`, `multilight_three_lights_concave_prism`,
`multilight_second_light_inactive`; `rules.json` += the `constructions` mm paths. Benchmark rows: `--lights 2|3` full,
camera-only with / without umbra, umbra alone; `record_pieces` 2 000-edge loop; re-measured N = 1 (`--gate full` PASS).

### M8 (wave 2, after M5 on main; §5.5)
Steps: 1 `io/part21.py`; 2 `io/step.py`; 3 `io/__init__.py` registry entries (`EXPANDERS["step"]`, `EXTENSION_LOADERS`,
`STEP_*` notes); 4 `scene.py` (`LOADER_TYPES` block only; `read_json` is M5's); 5 `io/cli.py` STEP options + extension
dispatch (`castplane/cli.py` is already wired by M5); 6 `pyproject` extra `step`, `tools/make_step_fixtures.py`,
fixtures; 7 `tests/test_step.py`; 8 docs (`docs/STEP.md`, USAGE, README row, benchmarks README rows). Steps 1–3, 6–8 are
new files; 4–5 are the shared hunks (`scene.py` and `io/cli.py` / `io/__init__.py`).
Acceptance tests: `cylinder.step` → exact pillar dict and a `basic.json` render **byte-equal** to the inline render, passing
`compare_documents` against `expected/example_basic.json`; hand numbers (`pillar.g0.base = (−1.7552526894158411,
5.8423736552920795, 0)`, `pillar.g0.top.shadow.lamp = (−5.584894920868585, 12.043916175929343, 0)` …); unit arithmetic
(9 mm → 0.009, 1001 mm → 1.001, 0.5 mm → 0.0005; metre file unchanged); `sphere.step`, `cone.step` exact; `box.step`
within 1e-9 and `compare_documents` on `example_basic`; `cylinder_down.step` `[0,0,180]` and the 64 allowed differing
leaves; `cylinder_tilted.step` against `expected/buried_cylinder_tilted.json`; `frustum.step` error / `fallback: "mesh"` →
a `mesh` object that validates and renders (OCP present) / `ImportError` (absent); `two_solids.step` ids and `solid`
selection; inline Part-21 cases (units, assembly, syntax, comments, DEGREE, round trips, metre tolerance); recogniser
negatives; `euler_zyx_deg` round trips and `[0,0,180]`; validation / composition / idempotence; CLI cases incl. `--into`
block equality and the mixed-option usage error; `import_step` min-of-3 < 500 ms. Conformance: unchanged. Benchmark
rows: fixture import ≈ 2–3 ms; 200-solid file (informational).

### M7 phase 1 (wave 1–2, own branch; §5.4) and phase 2 (wave 3)
Phase 1 steps 2–10 of §5.4 (core foundation → mesh / light / shadow → camera / construction → conics / curved → pipeline /
SVG → bench + CI gate decision → web UI → docs → CI on node 20 / 22). Acceptance: 34/34 at v3; writer parity on every
expected file; `fmt` / `py_repr` / `pymod` tables; determinism and camera-free blocks (incl. `directional.json`); the
`analytic_unit_box_point_light_overhead` hand values (`light_point = [0, 87.93525754212652]`, depth `8.888895816012818`);
`analytic_sun_45deg_box`; roll vector `1.2155372436685123 mm`; orbit round trips for both camera forms (`pitch_deg =
−26.7076677665586`); `node ts/build/bench/camera_only.js --gate both --reps 20` exits 0 on CI (camera-only min < 100 ms,
full < 1 s) and the CI gate literal set by the 70 ms margin rule; `web` build and orbit tests; `core ms` / `dom ms`
recorded for the five examples and `benchmark_100.json`.
Phase 2 (step 11): rebase on `main` at v6; port `hidden.ts`, the receiver generalisation, `meshprep.ts` (+ fallback,
`mesh` kind), `umbra.ts` / `multilight.ts`, the hidden-run and multi-light SVG groups; `document.ts` → the §5.0.3 shape;
`INT_KEYS` += `interval`; `WARNING_CODES` → 18; `rules.json` as §5.0.8; run the hand cases of `wall_and_ground`, the mesh
box and the symmetric two-light box through the port; both runners green on v6, recorded in the v6 CHANGELOG entry.
Benchmark rows: the TS table (three runs, min / median) in `benchmarks/README.md`.

## 3. Conformance versions at a glance
| v | by | expected changed | cases added | rules.json |
| --- | --- | --- | --- | --- |
| v3 | M7 step 1 | 0 | 0 | created (`case_overrides`, `drawable_containers`, `int_keys`) |
| v4 | M4 merge | 34 (key-additive) | 9 | `runs_rule`, `hidden_polylines`, `interval`, `per_receiver` path |
| v5 | M5 merge | 0 | 3 | — |
| v6 | M6 merge | 0 | 4 | `constructions` paths |
| v6 | M7 phase 2 | 0 | 0 | — (both runners green) |

## 4. Benchmark rows to add (`benchmarks/README.md`)
| row | milestone | gate |
| --- | --- | --- |
| full render / camera-only on `benchmark_100.json` (committed file) | M7 step 1 | `--gate full` (Python, unchanged) |
| switch-off full render + JSON bytes before / after M4; `--hidden-lines` full render | M4 | none (soft < 5 s) |
| features-off delta; `--scene mesh10k` stage A (incl. weld) and full | M5 | none |
| re-measured N = 1; `--lights 2`, `--lights 3`: full, camera-only ± umbra, umbra alone; `record_pieces` 2 000 edges | M6 | none |
| fixture `import_step` (min of 3); 200-solid 1.25 MB file | M8 | test bound < 500 ms |
| TypeScript: full, camera-only, stage A, SVG, JSON (node 22, three runs) | M7 | `--gate both` iff camera-only min < 70 ms, else `--gate full` |
