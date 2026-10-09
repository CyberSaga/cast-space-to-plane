# castplane (cast-space-to-plane)

castplane takes a scene JSON (objects, lights, receivers, camera) and returns two things:
- an exact perspective cast-shadow construction as a deterministic geometry document (spec §6.2 JSON);
- a layered SVG of the same drawing.

It is built as three pieces:
- `castplane/` is the Python reference implementation. It depends on numpy only.
- `ts/` is a TypeScript port of the core that must produce the same output.
- `web/` is a three.js UI on top of the port.

The pipeline runs three stages, A → B → C, in `castplane/pipeline.py`:
- **A** `shadow_geometry(scene)` works in world space and is camera-independent.
- **B** `project_scene(scene, A, camera)` projects and clips.
- **C** `compose(...)` builds the document.

A camera change re-runs only B and C.

## Commands

```sh
pip install -e '.[dev]'                        # Python >= 3.10
python -m pytest -q -x tests/test_<area>.py    # iterate on one file; the full suite is ~2000 tests / ~4 min
python -m pytest -q                            # full suite
python3 tools/regen_conformance.py --reason "check" --dry-run   # conformance drift; expect "0 changes"
python3 benchmarks/bench.py --gate full        # perf gate (full render < 1 s)

npm ci && npm test                             # TS port + web (node >= 20.19); builds ts first
node --test --test-reporter=tap ts/build/test/conformance.test.js   # TS conformance runner
python3 tools/compare_svg.py                   # Python vs TS SVG text; must report 0 mismatches (needs ts build)
node ts/build/bench/camera_only.js --gate both --reps 20            # TS perf gate
npm run -w web build

castplane render examples/basic.json -o out    # CLI: render | validate | info | stages | import
```

## Verify before you push

CI runs Python 3.10 and 3.13, node 20 and 22, and the web build (`.github/workflows/ci.yml`). Pick the checks that
match what you changed:
- **Python change:** full suite, dry run, and `bench.py --gate full`.
- **Syntax or perf-sensitive Python:** also run on **Python 3.10**. 3.13 hides two traps:
  - a backslash inside an f-string expression is a SyntaxError before 3.12;
  - `json.dumps(indent=...)` is slow pure Python before 3.13.
- **Anything that changes output:** also `npm test`, the TS conformance runner and `compare_svg.py`.
- **Web UI:** `npm run -w web build`. Playwright's Chromium is at `/opt/pw-browsers/chromium`. Never run
  `playwright install`.

## Where the rules live

- `docs/ARCHITECTURE.md` is the **binding contract**: §1–§4 cover v1 and §5.1–§5.5 cover M4–M8.
  - Read the section for the code you touch before changing behaviour.
  - New behaviour goes in as an appended `[decision, implementation]` paragraph at the end of that section's
    `### Implementation notes`.
  - Never rewrite existing contract text; amend it by reference.
- `docs/DECISIONS.md` (D1–D78) explains each decision in plain language. A real new decision gets the next D-number,
  written in the same 規格 / 問題 / 決定 / 理由 style.
- `docs/spec/spec-v0.1.md` is the original spec. The contract overrides it where marked **[decision]**.
- In the contract, "§N" means the contract and "spec §N" means the spec.
- **Languages:**
  - Code, docstrings and the contract are in English.
  - `README.md`, `docs/USAGE.md`, `docs/STEP.md`, `docs/DECISIONS.md` and `tests/conformance/*.md` are in Traditional
    Chinese.
  - Keep each file in its own language.

## Hard constraints

- **The core imports numpy only.** Optional libraries (trimesh, OCP, cairosvg) belong in `castplane/io/` loaders or PNG
  output. `castplane/io/expand_scene` inlines meshes before validation. The core and the TS port never read file paths.
- **JSON output is bit-deterministic per build.**
  - Emit floats as `x + 0.0` (no `-0.0`), with sorted keys.
  - Never reduce over variable-length axes whose order can vary; use fixed-shape expressions or `einsum`.
  - `output/geometry_json.dumps` must stay byte-identical to
    `json.dumps(indent=1, sort_keys=True, ensure_ascii=False, allow_nan=False)`.
- **Degenerate geometry warns and never raises.** Warnings come from the closed list of 18 codes in
  `castplane/errors.py`, and adding a code is a contract change. Bad input raises `SceneError(field=<json path>)`, and
  the CLI then exits with code 2.
- **Oriented projective geometry** (D3).
  - Finite points have w = +1, and the light is on the positive side of every receiver plane.
  - `normalize_max` keeps the sign.
  - Predicates are `> tol` / `< -tol`, and the band in between is the degenerate side.
- **Stage A must not depend on the camera.** Documents share A's lists by reference, so treat them as read-only and
  `copy.deepcopy` before mutating.
- **Name things after the spec's symbols.** The TS port uses the same snake_case names and record shapes, with `Map`
  for id indexes.
- **Keep `tests/reference/` (the ray caster and z-buffer) independent of `castplane`.** It shares no code with it. It
  is the ground truth for shadow regions (IoU ≥ 0.99).

## Conformance set (`tests/conformance/`, the output contract, v8 / 63 cases)

- **Never edit `expected/` by hand.**
  - New case: `python3 tools/regen_conformance.py --case NAME --reason "..."`.
  - Intentional behaviour change: the same command without `--case`, with a reason naming every changed case.
  - Either way the tool appends a versioned entry to `tests/conformance/CHANGELOG.md`.
- **Comparator constants live in `rules.json`.** After changing it, record it with `--rules-only --reason "..."`. Never
  loosen it to make a test pass.
- **Order of work:** add the case first, then generate, review the diff, and only then change the code.
- **Changes that alter expected bytes** must update the TS port in the same change, and both runners must pass on the
  same commit.
- **Cases are post-expansion scenes.** Mesh cases use inline `data`. All expected files together must stay < 3 MiB;
  they are at ~2.7 MB now.
- **Bit-exact checks run only on the recorded build:** NumPy version plus the kernel fingerprint in
  `tests/golden/build_fingerprint.json` (`tests/build_identity.py`). Other CPUs differ in the last digits, and tests
  fall back to the 1e-6 mm / 1e-9 tolerances.
  - After regenerating, also run `python -m tests.build_identity --write`.
  - To reproduce a CI-only diff locally: `OPENBLAS_CORETYPE=Haswell python -m pytest ...`.
- **Don't place new cases on the ulp-amplifying boundaries** listed in rule 3 of `tests/conformance/README.md`.

## TypeScript port

Python is the reference.
- **Mirror every output-affecting Python change** in `ts/src/<same module>.ts`, using the same algorithm, operation
  order and tie-breaking. Port the tests that pin it.
- **The JSON writer reproduces Python `repr` floats** (`ts/src/pyfloat.ts`). **The SVG writer must match Python's byte
  for byte**, with round-half-even at 4 decimals.
- **When the two disagree, suspect TS first.** If Python breaks the contract, fix Python and bump the conformance set.

## Gotchas

- **Unbounded shadow loops** (`shadow.shadow_loop`, D70): pair arcs at infinity only by direction (angular bracket
  matching), never by azimuths measured from an origin; those flip to the complement under translation. Tests:
  `tests/test_arc_pairing.py` and `tests/test_arc_base_level.py`.
- **Mesh tolerances:** mesh contact with a receiver uses `max(tol, weld_tolerance)`, and `meshprep`'s `scale_A` counts
  only face-referenced vertices.
- **Umbra piece counts can differ between Python and TS** when casters stand on the receiver; the regions agree. Don't
  build a test case on that.
- **Known limits and deferred fixes** are recorded in the contract's implementation notes. Each deferred fix changes
  expected files, so it needs a versioned conformance bump.
  - Python's camera-only re-render (~120 ms) misses the 100 ms target, which D17 accepts.
  - Benchmark gate limits change only with a newly recorded measurement in `benchmarks/README.md`; never loosen them to
    absorb a regression.

## Subagents: splitting work for performance and cost

Do the work yourself when it touches one or two files or one known symbol. Delegate when a task splits into parts that
can run in parallel, or when a search would otherwise flood your context.

**Pick the model by the kind of work, not by the task's importance:**

| Model | Use it for |
| --- | --- |
| `fable` | geometry design (anything in `shadow`, `curved`, `umbra`, `hidden`), adversarial review of geometry, root-causing a numeric discrepancy |
| `opus` | implementation, fixes, TS porting, merges and conflict resolution |
| `sonnet` | docs and contract-note edits, mechanical refactors, running and reporting the gates, re-verifying a simple finding |
| `haiku` | text-only fixes with known facts (counts, section references, typos) |

**Pipeline per change:** implementer, then reviewer, then fixer (only if there are findings), then merger.
- The reviewer is `.claude/agents/reviewer.md`. It is read-only and must give a reproducing command for each finding.
- Run one review pass. Add independent verifiers only for blocker or major findings, one per finding. Batch the minors
  into one `sonnet` pass. Don't fan out a verifier per minor finding.
- Give the reviewer a different lens than the implementer; a second review of the same kind adds little.

**Sharing work without collisions:**
- Give each parallel agent its own git worktree and branch (`isolation: "worktree"`). Never push the worktree branches;
  the merger brings them into the working branch with merge commits.
- Split by file ownership. Two agents may touch the same file only with append-only hunks in different places:
  implementation notes, `CHANGELOG.md`, README rows. Name the owner of each shared function in the prompt.
- **One writer for the conformance set.** Worker agents never run `regen_conformance.py` without `--dry-run`, and they
  don't touch `tests/conformance/`. They put candidate scenes under `tests/fixtures/<version>_candidates/`. The merger
  makes one versioned regeneration on the merged branch.
- Python changes land first. The TS port follows in a separate agent that merges the Python branch and mirrors the
  report's list of behaviour changes.

**Prompts and hand-offs:**
- Make every prompt self-contained:
  - the current state (branch, HEAD, test counts, set version);
  - the contract sections to read;
  - the exact gate commands;
  - "do not end your turn while a command is still running".
- Make prompts state-aware: tell the agent to check `git log` and `git status` first, so a re-run resumes instead of
  redoing work.
- Pass large inputs (findings lists, review reports) as files in the scratchpad, not pasted into the prompt.
- Ask for a structured report: one line per item (fixed or rejected, with the reason), files changed, test counts,
  conformance cases whose bytes changed, and commits.
- **A subagent's report is a claim, not proof.** Re-run the gates yourself before merging or pushing, and read the diff.

## Guard rails in `.claude/`

- `settings.json` pre-approves the read-only and test commands. It deliberately leaves out `regen_conformance.py`
  without `--dry-run`, and any push.
- `hooks/protect_expected.sh` denies Edit and Write on `tests/conformance/expected/`.

## Change checklist

Each behaviour fix ships with all of the following:
- a test that fails before the fix;
- the implementation-notes paragraph;
- one line in `CHANGELOG.md`;
- updated counts in README and USAGE (cases, set version, warning codes) when they change.

Merges keep history: no rebase or force-push of shared branches.

When Claude gets something wrong here twice, add the rule to this file.
