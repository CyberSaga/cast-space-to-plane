# PLAN v3 — implementation order for M9–M10 (spec-v0.2)

Companion to `docs/ARCHITECTURE.md` §5.6–§5.7 (the binding contract for spec-v0.2) and `docs/DECISIONS.md` D71–D79
(D79 added in M10).
Everything here is derived from §5.6–§5.7; where this file and the contract disagree, the contract wins. Base: conformance
set v7 / 60 cases, 18 warning codes, Python reference + TypeScript port at parity (`compare_svg.py` 0 mismatches).

## 1. Order and parallelism

```
main ──► step 1  contract + decisions (this file, §5.6–§5.7, D71–D78; no code)
      │
      ├─► step 2  Python core (worktree): picture_plane validation, resolve_picture_plane, plane_equation,
      │           unproject_to_plane, camera.py hooks, compose key, CLI info; candidates in tests/fixtures/v8_candidates/
      │
      ├─► step 3  TS port + conformance v8 (merges step 2, mirrors its behaviour-change list; ONE merger regenerates v8)
      │
      ├─► step 4  M9 observer view (web only; needs unproject_to_plane from step 3)
      │     │      4a main.ts split (no behaviour change) ──► 4b observer.ts + pane
      │     │
      │     └─► (parallel with 4b) rig.ts + equation.ts pure functions and their tests (no wiring)
      │
      └─► step 5  M10 plane mode: wire rig.ts into the panes (handles, right-pane mapping, sliders, pivot,
                  views, equation field, undo, readouts); orbit.ts stops driving the UI in the same change
```

- **Step 1** is alone: the contract precedes the code (CLAUDE.md).
- **Steps 2 → 3 are sequential** (Python lands first; the port follows in a separate agent that merges the Python branch).
  Only step 3's merger runs `regen_conformance.py` without `--dry-run`.
- **Steps 4 → 5 are a sequence** (M10 builds on M9's observer pane). The pure modules of M10 (`rig.ts`, `equation.ts`)
  depend only on the TS port and may be written in parallel with step 4b in their own worktree; they are wired in step 5.
- Each step ends with the gates of §4 and a reviewer pass (`.claude/agents/reviewer.md`) with a different lens than the
  implementer (geometry steps: numeric / determinism lens; web steps: interaction / invariant lens).

### Shared files and the merge rule
A file is *shared* when two worktrees edit it. Rule (as in PLAN-v2): **append-only hunks in disjoint regions**, no
reformatting, no moving of existing code; the owner of each shared function is named and the other step must not
restructure it.

| file | step 2 (Python core) | step 3 (TS port + v8) | step 4 (M9) | step 4' (rig / equation, parallel) | step 5 (M10) |
| --- | --- | --- | --- | --- | --- |
| `castplane/scene.py` | **owns** `validate_camera` (third form, new messages) + new `validate_picture_plane` | — | — | — | — |
| `castplane/camera.py` | **owns** the resolve hook at the top of `camera_forward` / `camera_matrix`, the warning suppression, `picture_plane` in the record | — | — | — | — |
| `castplane/picture_plane.py` (new) | **owns** | — | — | — | — |
| `castplane/pipeline.py` | one conditional key in `compose`'s `camera` block | — | — | — | — |
| `castplane/cli.py` | three lines in `cmd_info` | — | — | — | — |
| `ts/src/scene.ts`, `camera.ts`, `picture_plane.ts` (new), `document.ts` / `pipeline.ts` (compose key), `index.ts` (exports) | — | **owns** (mirror of step 2, same names and operation order) | — | — | — |
| `tests/test_picture_plane.py` (new), `tests/test_scene.py`, `tests/test_camera.py`, `tests/test_cli.py` | **owns** / appended blocks | — | — | — | — |
| `ts/test/picture_plane.test.ts` (new), `ts/test/scene.test.ts` | — | **owns** / appended blocks | — | — | — |
| `tests/fixtures/v8_candidates/` | writes the three candidate scenes | consumes and deletes after regeneration | — | — | — |
| `tests/conformance/cases/`, `expected/`, `CHANGELOG.md`, `README.md` | — (never) | **only writer**: three `--case` regenerations = v8, `### M10 投影平面` rows | — | — | — |
| `tests/test_conformance.py` | — | `test_set_covers_the_required_sources` += a `picture_plane` case | — | — | — |
| `tests/golden/build_fingerprint.json` | — | `python -m tests.build_identity --write` | — | — | — |
| `web/src/main.ts` | — | — | **owns** the split (4a) and the observer wiring (4b) | — | appended wiring; replaces the drawing-pane orbit handlers |
| `web/src/observer.ts` (new) | — | — | **owns** | — | appends ring / arrow geometry and the hit test |
| `web/src/rig.ts`, `web/src/equation.ts` (new) | — | — | — | **owns** | consumes; no restructuring |
| `web/src/orbit.ts`, `web/test/orbit.test.ts` | — | — | unchanged | unchanged | unchanged (stops being used by the UI; tests stay green) |
| `web/src/download.ts` | — | — | — | — | `scene_blob` takes the rig's block (picture_plane form) |
| `web/test/observer.test.ts`, `rig.test.ts`, `equation.test.ts` (new) | — | — | `observer.test.ts` | `rig.test.ts`, `equation.test.ts` | appended rows (§5.7.13 web table) |
| `web/index.html`, `web/src/style.css` | — | — | switch, two-pane layout, < 880 px stacking | — | controls row, sliders, view buttons, equation field |
| `docs/USAGE.md`, `README.md`, `web/README.md` | `camera.picture_plane` scene format, `castplane info` lines, `__all__` names | counts v8 / 63 | §4 web UI: observer view; `obs ms` numbers | — | §4 web UI: plane mode; screenshot `docs/images/web_ui_observer.png` |
| `CLAUDE.md` | — | conformance counts v8 / 63; decision range `(D1–D70)` → `(D1–D78)` | — | — | — |
| `docs/ARCHITECTURE.md` implementation notes | §5.7 notes (append) | §5.7 notes (append) | §5.6 notes (append) | §5.7 notes (append) | §5.7 notes (append) |

Step-only files (no coordination needed): step 2 `castplane/picture_plane.py`, `tests/test_picture_plane.py`,
`tests/fixtures/v8_candidates/*`; step 3 `ts/src/picture_plane.ts`, `ts/test/picture_plane.test.ts`; step 4
`web/src/observer.ts` (+ its DOM / three.js drawing module), `web/test/observer.test.ts`; step 4' `web/src/rig.ts`,
`web/src/equation.ts` and their tests.

## 2. Per-step deliverables and acceptance

### Step 1 — contract (this change)
`docs/ARCHITECTURE.md` §5.6, §5.7 and the appended amendment paragraphs of §2.0, §2.2, §3.1 and the §5.4 implementation
notes; `docs/DECISIONS.md` D71–D78; this file; the spec-v0.1 §9 / §10 rows pointing to spec-v0.2. Acceptance: the diff
of existing contract sections is append-only; `tests/test_contract_wording.py` and the conformance doc test pass.

### Step 2 — Python core (§5.6.1, §5.7.1–§5.7.6)
Steps: 1 `scene.py` third form + `validate_picture_plane` (tests first: every §5.7.1 row with its field path);
2 `picture_plane.py` `resolve_picture_plane`, `plane_equation`, `unproject_to_plane`; 3 `camera.py` hooks and warning
suppression; 4 `pipeline.compose` key; 5 `cli.py` `info` lines; 6 candidate scenes in `tests/fixtures/v8_candidates/`
(vertical `y = 2`, tilted with a given `up`, horizontal `z = 3` polyhedra only), each with its hand-written equivalent
target camera. Acceptance tests: §5.7.13 core table (equivalence < 1e-9 mm, translation invariance, hand values of the
spec-v0.2 §4.1 block, roll reference, no `CAMERA_LOOKING_ALONG_UP`, input errors, validated-block round trip, the equation
table incl. ties), §5.6.8 round trip (hypothesis), `--dry-run` **0 changes** on the 60 v7 cases.

### Step 3 — TS port + conformance v8 (§5.7.0, §5.7.14)
Merge step 2; mirror `scene.ts`, `camera.ts`, `picture_plane.ts` (same names, record shapes, operation order;
`plane_equation` with the exact-tie formatter); the compose key; the TS tests of §5.7.13 / §5.6.8. Then, on the merged
branch: `--dry-run` (0 changes), three `regen_conformance.py --case NAME --reason "..."` runs (one v8 CHANGELOG entry),
`python -m tests.build_identity --write`, README / USAGE / CLAUDE.md counts (v8 / 63) and CLAUDE.md's decision range
(D1–D78). Acceptance: both runners pass
63/63 on the same commit; `compare_svg.py` 0 mismatches (cases and examples); TS camera-only gate unchanged.

### Step 4 — M9 observer view (§5.6)
4a: split `main.ts` (drawing stage, pointer handlers) with no behaviour change; web tests and build green. 4b:
`observer.ts` (board derivation, framing, element geometry), the observer pane (three.js, second camera), the switch and
the two-pane / stacked layout, `obs ms`; `picture_plane` scene cameras handed to `orbit_from_camera` as their resolved
block with the target at the scene centre's depth, and `D` = their `picture_plane` distance (§5.6.2). Acceptance: §5.6.8 / §5.6.9 (switch-off identity of SVG and JSON, < 100 ms per frame on the five examples,
recorded in `web/README.md`).

Note (D80, after M10): the "switch" in this step became the default-on observer pane with a 預覽 toggle that hides it; "switch-off identity" reads as the preview. See contract §5.6 implementation notes and DECISIONS D80.

### Step 4' — rig and equation pure functions (§5.7.7, §5.7.8; parallel with 4b)
`rig.ts`: state, derived quantities, `camera_of_rig`, load rule, ring (both modes), right-pane orbit, snap, arrow,
wheel / pinch, pan, roll, D, pivot, views, undo stack helpers; `equation.ts`: the grammar of §5.7.8 item 12. Acceptance:
the web rows of §5.7.13 that need no DOM (all of them except the hit-test and gesture-settling rows, which step 5 adds).

### Step 5 — M10 plane mode (§5.7.9–§5.7.11)
Wire the ring and arrow into the observer pane and its hit test; the right-pane mapping (left drag, wheel, pan, pinch);
the focal / D / roll sliders; pivot selector and object picking; lock-horizontal; six views; equation field with quick
buttons; undo / reset; readouts and notices; "Download scene" / "Copy camera block" in `picture_plane` form; `orbit.ts`
no longer drives the UI (tests unchanged). Acceptance: every row of §5.7.13; §5.7.15.

## 3. Conformance versions at a glance
| v | by | expected changed | cases added | rules.json |
| --- | --- | --- | --- | --- |
| v8 | step 3 merger (Python + TS on one commit) | 0 | 3 (`camera_picture_plane_vertical`, `camera_picture_plane_tilted`, `camera_picture_plane_horizontal`) | unchanged |

Capacity: `expected/` is 2 706 181 bytes at v7 (limit 3 MiB = 3 145 728 bytes; 439 547 bytes left); three minimal
camera cases (≈ 25–55 KB each) fit.

## 4. Gates (run at the end of every step; CLAUDE.md "Verify before you push")
```sh
python -m pytest -q                                              # full suite (Python 3.13)
/root/.local/bin/python3.10 -m pytest -q                         # 3.10 check (syntax, json indent path)
python3 tools/regen_conformance.py --reason "check" --dry-run   # expect "0 changes" (after v8: on 63 cases)
python3 benchmarks/bench.py --gate full                          # full render < 1 s
npm ci && npm test                                               # TS port + web
node --test --test-reporter=tap ts/build/test/conformance.test.js
python3 tools/compare_svg.py                                     # 0 mismatches
node ts/build/bench/camera_only.js --gate both --reps 20         # TS perf gate
npm run -w web build
```
Steps 4, 4' and 5 change no core output, so for them the Python gates are a no-change check; `npm test` and the web build
are the deciding gates, plus the recorded `obs ms` / acceptance numbers in `web/README.md`. Benchmark gate limits are
never loosened; a camera-only regression from the resolve hook (constant time) is a bug.

## 5. Amendment after step 5 (D79, spec-v0.2 §2.1, §5.9)
Step 5's "right-pane mapping (left drag, wheel, pan, pinch)" and the right-pane parts of step 3's `rig.ts` list were
superseded by D79: the drawing pane is read-only (no input, native scroll, context menu kept), the board is moved only
in the observer pane and with the toolbar, the pan comes from the load rule alone, and the toolbar toggles start at
fixed page-level defaults (horizon, objects, form_shadow, cast_shadow, labels, Hidden lines checked; construction and
3D view unchecked). The contract text is amended by reference in the §5.4 and §5.7 implementation notes; no core
output, conformance case or gate limit changes. The step texts above are kept as the historical plan.

## M11 — 場景編輯

Companion to `docs/spec/spec-v0.3.md` (scene editing: drag objects in 3D, a collapsed-by-default object library, select +
Delete) and to the §5.8 M11 section of `docs/ARCHITECTURE.md` that the contract step adds. `docs/demo/scene_edit_demo.html`
is behaviour reference only; where it differs from the spec, the spec wins (its curved primitives are polygon
approximations and its shadows are vertex convex hulls, neither of which is the spec). Where this file and the contract
disagree, the contract wins. Base: `main` at `20bd2ce` plus the spec commit (conformance set v8 / 63 cases, 18 warning
codes, D1–D80, TS tests 465, web tests 101).

**Core, TS port and conformance set are untouched.** M11 is a web-only change on the scene JSON: stages A, B and C,
`ts/src/*`, `castplane/*` and `tests/conformance/` do not change, and there is no v9.
`regen_conformance.py --dry-run` must stay "0 changes" and `compare_svg.py` "0 mismatches" at every step; nothing in this
milestone ever runs `regen_conformance.py` without `--dry-run`.

### Scope
- **Select and drag.** One selected object at most. A click selects; a drag on an object selects and moves it along the
  horizontal plane at the grabbed point's height (both panes). The left pane also has a vertical handle (z_b only). The
  grazing-angle fallback is decided at pointer-down.
- **Object library.** A sidebar that is collapsed on every load and overlays both panes (the canvases are never pushed
  or resized): 64 px thumbnail plus one line of name per tile, eight presets in a data table (方塊, 木箱, 高柱, 圓柱, 球,
  圓錐, 三角柱, 六角柱), `prefix_n` ids, placement at the camera's line of sight on the ground with avoidance.
- **Delete.** Delete or Backspace on a selection, or the delete button on the selection chip. A scene keeps at least one
  object (the core requires a non-empty `objects`).
- **Undo and redo.** Object add, delete and drag join the single undo stack (50 steps); new 重做 button; Ctrl/⌘+Z and
  Ctrl/⌘+Shift+Z with the focus rule of spec-v0.3 §6.
- **Pivot.** The rotation pivot P is the point taken at the moment it is set; adding, dragging and deleting objects never
  moves it; a new 重新取中心 button re-takes it. 點選物體 is decided by selection, and only a click (not a drag) sets the
  pivot.
- **Revisions of M10** (spec-v0.3 §0, five places): the pivot rule above; the vertex-ray focus object is the selection
  (else `objects[0]`); undo covers object edits and gains redo; 重設 becomes 重設視角 (board, pivot and observer camera
  only; objects are not restored); observer framing uses the eight corners of the scene bounding box.
- **Decisions.** D79 and D80 already exist, so the new decisions are **D81–D86**: D81 selection unified with the 點選物體
  pivot; D82 the pivot is the value taken when set; D83 horizontal drag, vertical handle and grazing-angle fallback; D84
  library presets, placement and id rule; D85 keep at least one object; D86 object edits join the single undo stack.
  spec-v0.3 Appendix A's D79–D84 is renumbered; the spec text itself is not edited.
- **Conflicts with D79 / D80.** Right-pane object drag is a new input to the drawing pane (D79 made blank-area gestures
  inert, and they stay inert); a second finger cancels an object drag that has moved < 5 px in either pane (zero
  steps), and the observer pinch exists only in the left pane; editing keeps working in preview
  (D80) except the vertical handle, which lives in the observer pane. These positions are pending the user's
  confirmation (`.claude/scratch/v3_m11_questions.md`); the contract and D81–D86 record whatever is confirmed.

Out of scope (spec-v0.3 §1): rotating or scaling objects, a numeric inspector, dragging from the library onto the
drawing, editing lights or receivers, importing meshes from the library, collisions, and concave prisms in the library
(the core already supports them).

### Files
| file | state | owner |
| --- | --- | --- |
| `web/src/scene_edit.ts` | **new**; pure functions, no DOM: add / delete (with the original index) / move, snap, id generation, placement and avoidance, grazing-angle fallback, applying an undo entry to an `objects` array | step M11-b |
| `web/src/library.ts` | **new**; the preset table (name, type, parameters as 1e-4 literals, id prefix, thumbnail SVG) | step M11-b |
| `web/src/selection.ts` | **new**; hit testing and selection state shared by both panes | step M11-b |
| `web/test/scene_edit.test.ts`, `library.test.ts`, `selection.test.ts` | **new** | step M11-b |
| `web/src/rig.ts` | shared with M10: undo stack entry union and redo | M11-a (the stack API), M11-b consumes |
| `web/src/observer.ts` | shared with M10: `framing_points` (bbox corners), `vertex_rays` (focus id) | M11-a |
| `web/src/plane.ts` | shared with M10: updatable `SessionScene`, pivot as value, selection, reset target, redo | M11-a, extended in M11-c |
| `web/src/main.ts` | shared with M10: sidebar, selection chip, shortcuts, `scene_dirty` throttling, preview | M11-a (revisions only), then M11-c, then M11-d, one writer at a time |
| `web/src/observer3d.ts`, `helpers3d.ts`, `scene3d.ts`, `stage.ts` | shared with M9 / M10: hit at pointer-down, vertical handle, per-object node updates | M11-c |
| `web/src/ui.ts`, `web/index.html`, `web/src/style.css` | shared: 重做, 重新取中心, 重設視角, library tab and sidebar, selection chip | M11-a (labels, buttons), M11-c (library, chip) |
| `web/test/plane.test.ts`, `rig.test.ts`, `observer.test.ts`, `web/scripts/smoke.mjs` | shared: existing M10 tests updated, new rows appended | see the merge order |
| `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` | new §5.8 M11 (English, `[decision]` marks, Implementation notes); amendments to §5.6 / §5.7 as appended `[decision, implementation]` paragraphs (never rewrite existing text); D81–D86 | the contract step, before M11-a |
| `docs/USAGE.md`, `README.md`, `web/README.md`, `CLAUDE.md` | web UI section (drag, library, delete, shortcuts, 重設視角); decision range `(D1–D80)` → `(D1–D86)` | last step |

Nothing under `castplane/`, `ts/` or `tests/conformance/` is edited. The shared-file rule of §1 applies: one writer per
shared file at any time, append-only hunks elsewhere, the owner of each shared function named in the prompt.

### Merge order
1. **Contract and decisions (no code).** `docs/ARCHITECTURE.md` §5.8 and the amendment paragraphs, `docs/DECISIONS.md`
   D81–D86, and the answers to the open points. This precedes every code step.
2. **M11-a — the five spec-v0.3 §0 revisions applied to M10 code, as a separate commit, before any editing feature.**
   Behaviour of an unedited scene must not change except where listed. Contents:
   - `SessionScene` becomes updatable (`set_geometry`) without rebuilding `PlaneSession`; the pivot is the value taken
     when set; `set_pivot_mode("object")` no longer re-derives P; selection state; 重新取中心.
   - `vertex_rays(…, focus_id?)`; `framing_points(board, scene, bbox)` with the eight corners.
   - Undo stack entry union and a redo stack; 重做 button; reset takes the current centre and is labelled 重設視角
     (`index.html:22`, `index.html:92`, `web/README.md`, `docs/USAGE.md`).
   - Existing M10 tests updated in the same commit: `plane.test.ts` "discrete actions", "undo keeps the current pivot;
     reset restores…", "switching the pivot mode without a pick…"; `observer.test.ts` "framing: centroid target…" (the
     point count and the ground point) and "framing is aspect-aware…" (the signature); `rig.test.ts` "undo details" and
     "undo and reset" where the stack API changes; `smoke.mjs` reset and object-pivot rows (message texts, 重設視角).
   - Gates: `npm test`, `npm run -w web build`, the dry run (0 changes), `compare_svg.py` (0 mismatches).
3. **M11-b — the pure modules** (can run in parallel worktrees, disjoint files): `scene_edit.ts` + test, `library.ts` +
   test (every tile passes the core `validate_scene` in the port; ids; CCW polygons), `selection.ts` + test. No wiring,
   no shared files.
4. **M11-c — UI wiring.** Library sidebar and tiles, selection (both panes, hit order, click vs drag), horizontal drag
   in both panes, the vertical handle, the selection chip and delete, undo / redo of object entries, shortcuts and
   the Esc order, the right-pane object listener under the amended D79 note. One writer for `main.ts` and
   `observer3d.ts`.
5. **M11-d — throttling and preview.** `scene_dirty` (at most one recompute per animation frame), per-object node
   updates during a drag, the drag-mode cost measured at pointer-down, the web-side wireframe preview that never reaches
   `state.doc`, `state.svg` or the downloads, the "畫面變動" readout during an object drag; the 10-object drag row in the
   smoke test (recorded in `web/README.md`, not gated, as in M10).
6. **Docs and counts.** `README.md`, `docs/USAGE.md`, `web/README.md`, `CLAUDE.md` (decision range and web test counts).

Each step ends with the gates below and a reviewer pass (`.claude/agents/reviewer.md`) with a different lens from the
implementer (web steps: interaction / invariant lens; for M11-b the pure functions get a numeric lens).

### Gates
```sh
python3 tools/regen_conformance.py --reason "check" --dry-run   # expect "0 changes" (63 cases, set v8)
python3 tools/compare_svg.py                                     # 0 mismatches (needs the ts build)
npm ci && npm test                                               # TS port + web, builds ts first
node --test --test-reporter=tap ts/build/test/conformance.test.js
npm run -w web build
```
Python and TS gate outputs are a no-change check for M11 (`pytest -q`, `benchmarks/bench.py --gate full`,
`node ts/build/bench/camera_only.js --gate both --reps 20` should be unchanged); `npm test` and the web build are the
deciding gates, plus the smoke test in `/opt/pw-browsers/chromium` (never run `playwright install`). The M11 acceptance
rows are the web rows of spec-v0.3 §10.1: horizontal drag (grab point stays under the pointer to < 1e-6 m, z_b fixed,
grid snap, Alt), grazing-angle fallback, vertical handle, pivot does not follow, library (every tile valid), delete,
undo (the output after undoing a delete is byte-identical), selection, overlay identity (SVG and JSON with and without a
selection are byte-identical), two fingers (both panes), random stress (200 steps, all drawing values finite), and the
10-object drag time (< 33 ms recorded). The conformance row is "0 changes" / "0 mismatches". Benchmark gate limits are
never loosened.
