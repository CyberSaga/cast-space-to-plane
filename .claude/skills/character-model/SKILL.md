---
name: character-model
description: Build a castplane mesh model of a character (anime or illustrated figure) from a character design, reference images and notes, so users can load it as an example scene and rotate it to study perspective. Use when asked to "build a model of the person in this picture", add a figure or character example, or rework the Miki generator in tools/miki_model.
---

# Building a character model from a design and reference images

This is the playbook distilled from building `examples/miki.json` (花菱美希). The generator it produced,
`tools/miki_model/`, is the worked example; its `README.md` is the maintainer guide (API, the 10 mesh rules, CLI) and
its `SPEC.md` shows what a character spec looks like. Read both before starting. This file covers the process and
the traps; it does not repeat the rules in `tools/miki_model/README.md`.

What "done" means: a deterministic generator under `tools/<name>_model/` writes a scene JSON with inline `mesh`
objects (the web UI cannot read `path`) plus OBJ / MTL / GLB copies. The scene renders with `warnings: []`. Its line
drawing reads like hand-drawn line art (silhouettes plus designed lines, no wireframe noise). It stays interactive in
the web UI, and a test pins the files byte for byte.

## 0. Before any geometry

- **Rights.** A character from a published work belongs to its rights holders. Before the first commit, ask the
  user whether the model may live in this public repository. If it does, ship a notice like `COPYRIGHT_NOTICE.md` (the
  character is not part of the project's authorized distribution; GPL-3.0 covers castplane only). Link the notice
  from every README that mentions the model. Have the exporter write it into the scene `description`, the OBJ / MTL
  headers and the GLB `asset.copyright`. Reference screenshots never go into the repository.
- **Reference pack (scratchpad, never committed).** Copy the images to `$S/refs/`. Extract the pages and embedded
  images of a PDF with the Read tool (`pages=`); `pdfimages` / `pdftoppm` work too if installed. Then write
  `$S/BRIEF.md` for the agents:
  1. the request, quoted;
  2. a table of each reference image and what it shows (view angle, which features it settles);
  3. the user's own findings (their notes are binding: in Miki's case, how the headband sits, the bangs block, the
     scarf ring, the face proportions);
  4. the deliverable file tree;
  5. frame, scale and pose (Z up, metres, soles on z = 0, facing −Y, her left = +x, relaxed A-pose);
  6. the hard constraints (below);
  7. the scene settings;
  8. the check commands.
  Every agent prompt starts with "read BRIEF.md first".
- **Facts the images cannot give.** Look up the official height and similar data and cite the source in the spec.
  Make an explicit, marked **Decision** for what no source shows (Miki: socks, shoes, skirt length), and list those
  decisions in the final report so the user can correct them.

## 1. Spec, then toolkit (can run in parallel)

- **Spec (`SPEC.md`), written before modelling.** Write it in metres:
  - a landmark table (z, half-width, front y, back y for every body level);
  - face proportions as ratios of one face unit;
  - one section per part with binding numbers;
  - a **lines plan** (§F in Miki's spec): which edges must draw as feature lines;
  - a **likeness checklist** (§I, about 20 items), which the review rounds score.

  Later the code wins over the spec. Mark deviations in comments, and list spec fields that nothing reads in
  `rig.SPEC_ONLY_FIELDS`.
- **Toolkit.** Reuse `tools/miki_model/meshkit.py` (closed-shell builders, `validate`, `fix_nesting`,
  `feature_silhouette_vertices`). It has no character content, so import it instead of forking it. Copy and adapt
  `rig.py`, `assemble.py`, `export.py`, `preview.py` and `mannequin.py`. Before a second character lands, extract the
  shared modules into one package in a separate refactor. The check for that refactor is that both models regenerate
  byte for byte.
- All numbers live in a frozen `Rig` dataclass. Builders read `rig.*` and contain no literals. A grey mannequin part
  exists for every region, so each module can be previewed in context before the others exist.

## 2. Objects, then parts in parallel

- **Objects come first and are spatially compact.** Group parts into castplane objects by place, not by colour. The
  hidden-line pass tests a sample only against objects whose image rectangle contains it, and the ray cap of 64 is
  per object. Miki has 18 objects, from 58 closed shells. Colour belongs to the part (`material`), and the object's
  `display_color` is its dominant material colour (D81, read only by the web 3D views).
- **`objects[0]` matters.** The web observer pane draws sight rays to every vertex of the first object. Put a small,
  telling part first (Miki: the headband, 120 vertices).
- **Split the builders by file ownership** so that two agents run in separate worktrees: head + hair in one, body +
  limbs in the other. Each writes only its own modules; one merger agent merges both, fits the seams (neck / collar,
  hair / shoulders) and regenerates.

## 3. Review rounds until the majors are gone

Each round has two critics in parallel, both read-only:
- a **likeness and appeal critic** (`opus`): side-by-side sheets of each reference against a camera matched to its
  angle, shaded and line versions; the spec's checklist item by item with measured numbers; anime appeal;
- a **line-art and technical critic** (`sonnet`):
  - `--check`;
  - 16 line renders (12 azimuths, high, low, 2 head close-ups), each with `warnings: []`;
  - stray or missing lines, decals eaten by hidden-line removal, poke-through and gaps;
  - `node tools/web_frame_bench.mjs`;
  - determinism and the Python 3.10 bytes;
  - `castplane import` of the GLB and OBJ.

The round then runs the fixers (one per owner, in worktrees) and a merger. Findings are structured. Each has severity,
owner, part, view, observed, expected, and a fix concrete enough to implement ("raise the bang cut from 1.425 to
1.432").

- Severity has to be honest. blocker / major is only what a person drawing from the model would notice in the
  `[objects, cast_shadow]` line drawing or the shaded views; everything else is minor. Pass the earlier rounds'
  results to each round (`$S/review/rN_result.json`), so that deliberate rejections are not reported again. Make
  the later rounds explicit **verification** rounds that look for regressions the previous fixes caused.
- Miki needed four rounds (major findings 11 → 6 → 6 → 1). Stop when no blocker or major remains. Carry the remaining
  minors into the final report as known limits.
- Critics often may not write files. Ask for the full report in the structured result as a fallback.

## 4. Integration

- Add a scene file `examples/<name>.json`. The scene needs:
  - a sun from the viewer's upper left;
  - a ground plane;
  - a 3/4 front camera with a portrait frame;
  - `output.layers` set to `["objects", "cast_shadow"]`. castplane does not occlude the form- and cast-shadow
    **fills**, so with `form_shadow` on, back-lit hair shows through the face.
- Vite bundles every `examples/*.json` into the web Example menu. `tests/test_ts_port.py` asserts the number of
  examples (`len(examples) == 9`), so a new example must update that count.
- Write `tests/test_<name>_model.py`, modelled on `tests/test_miki_model.py`. It pins byte-identical regeneration,
  closed manifolds with no mesh fallback, `warnings == []`, the budget and the ray cap, and `display_color`.
- Docs: the generator's README and SPEC (in English), `examples/README.md`, `docs/USAGE.md` and `README.md` (in
  Traditional Chinese), and a §5.4 implementation note when the model needs a contract-visible change. Quote the
  object and polygon counts, and update them whenever the model changes.
- Take a web UI screenshot with Playwright (Chromium at `/opt/pw-browsers/chromium`; launch with
  `--use-angle=swiftshader`). Untick `labels`, because every mesh vertex gets one.
- Finish with an adversarial review by `.claude/agents/reviewer.md` (that agent defaults to `fable`; override the
  model only if the user restricted the models), then the gates in CLAUDE.md "Verify before you push".

## Traps that cost a round last time

- **Coplanar merge eats group boundaries.** Faces within 1e-3 rad merge whatever their groups. A colour stripe on a
  flat band needs a crease of at least 1°, or must be a separate shell floating about 0.5 mm above the surface.
- **Decals under 0.5 mm proud vanish** under hidden-line removal. So do lid bands, brows, the mouth and stripes.
- **The light silhouette costs rays.** Flat caps facing away from the sun, slab rims with their own group, and pleat
  creases each put feature-silhouette vertices on the ray budget. Prefer `thicken(groups="single")`, and split a
  crowded object rather than deleting designed lines.
- **Jaw and neck.** A flat shelf under the jaw reads as a box in low views and draws a stray line across the face. Use
  several jaw rings that turn under into the neck. Check `head_low` and `low_angle` early.
- **Hair seams.** Where two hair shells cross (dome / curtain), the outline jogs and zigzags. Tuck one inside the
  other, and split twisted quads.
- **BLAS-dependent bytes.** Any branch on the last bits of a float reduction makes the generator differ across CPUs.
  Use relative tolerances (`meshkit._below_fan`, `PLANAR_REL`). Check with `OPENBLAS_CORETYPE=Haswell` and with
  Python 3.10 / numpy 2.2.
- **Web scene download of mesh scenes** once wrote face indices as `26.0`, which the CLI rejected. This is fixed in
  `web/src/download.ts`. Re-check that the CLI renders a downloaded scene with the same SVG as the web UI.
- **Performance figures depend on the container.** The still frame measured about 1.4 s in the container where Miki
  was built and about 2.4 s in a later one, with the same code. Measure the current `examples/miki.json` in the same
  container as the baseline before you judge a new model against the 1.5 s target.
- **What users ask afterwards.** The drawing pane is an uncoloured line drawing by design; colour shows only with
  "3D view" ticked or in the observer pane. Turn on Hidden lines with style omit, and keep the eye above the ground.
  Put this in the user-facing docs.

## Model choice for this task

| work | model |
| --- | --- |
| spec from references, likeness critic, part builders, fixers, mergers, integration | `opus` |
| line-art / technical critic, docs, gates and screenshots | `sonnet` |
| count, typo and reference fixes | `haiku` |

Builders and fixers run in worktrees (`isolation: "worktree"`). Nothing in `castplane/`, `ts/`, `web/` or
`tests/conformance/` changes for a model; if it must, that is a separate change with its own D-number and review.
Remove the worktrees after their branches are merged (`git worktree remove`, then `git branch -d`).

Models live only on the model branch `claude/admiring-bohr-egi4ik`, which is never merged into main (CLAUDE.md,
"Character models live on their own branch"). Merge `origin/main` into it before starting a model. A system change
the model needs lands on main first, on its own branch off main without model files; then merge main into the model
branch.
