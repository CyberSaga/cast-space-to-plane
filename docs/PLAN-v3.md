# PLAN v3 — implementation order for M9–M10 (spec-v0.2)

Companion to `docs/ARCHITECTURE.md` §5.6–§5.7 (the binding contract for spec-v0.2) and `docs/DECISIONS.md` D71–D78.
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
