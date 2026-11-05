---
name: character-model
description: Build a castplane mesh model of a character (anime or illustrated figure) from a character design, reference images and notes, so users can load it as an example scene and rotate it to study perspective. Use when asked to "build a model of the person in this picture", add a figure or character example, or rework the Miki or Reiya generator in tools/miki_model or tools/reiya_model.
---

# Building a character model from a design and reference images

This is the playbook distilled from building `examples/miki.json` (花菱美希) and `examples/reiya.json` (Reiya). The
generators they produced, `tools/miki_model/` and `tools/reiya_model/`, are the worked examples, both on the shared
toolkit `tools/charmodel/` (its `README.md` lists the API and what a character package defines). Miki's `README.md` is
the maintainer guide (the 10 mesh rules, the CLI); Reiya's `README.md` covers what a second character adds (the
stated-height scale, per-side objects, the fan rule). Each `SPEC.md` shows what a character spec looks like. Read the
toolkit README and Miki's guide before starting, and Reiya's guide for the second-character parts. This file covers the
process and the traps; it does not repeat the rules in `tools/miki_model/README.md`.

What "done" means: a deterministic generator under `tools/<name>_model/` writes a scene JSON with inline `mesh`
objects (the web UI cannot read `path`) plus OBJ / MTL / GLB copies. The scene renders with `warnings: []`. Its line
drawing reads like hand-drawn line art (silhouettes plus designed lines, no wireframe noise). It stays interactive in
the web UI, and a test pins the files byte for byte.

## 0. Before any geometry

- **Rights.** A character from a published work belongs to its rights holders. Before the first commit, ask the
  user whether the model may live in this public repository. If it does, ship a notice like `COPYRIGHT_NOTICE.md` (the
  character is not part of the project's authorized distribution; GPL-3.0 covers castplane only). Link the notice
  from every README that mentions the model. Have the exporter write it into the scene `description`, the OBJ / MTL
  headers and the GLB `asset.copyright`. Reference screenshots never go into the repository. For an original character
  whose owner is not known (Reiya: a design sheet from the user), write a neutral notice ("belongs to her creator; a
  drawing reference made from the creator's design sheet; not part of this project's authorized distribution"), keep it
  in the same places, and ask the user who owns her. `COPYRIGHT_NOTICE.md` has one section per character.
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
  Make an explicit, marked **Decision** for what no source shows (Miki: socks, shoes, skirt length; Reiya: her height
  until the user gave it), and list those decisions in the final report so the user can correct them. A height the
  user states later is binding: apply it as a scale (§1), do not remeasure.

## 1. Spec, then toolkit (can run in parallel)

- **Spec (`SPEC.md`), written before modelling.** Write it in metres:
  - a landmark table (z, half-width, front y, back y for every body level);
  - face proportions as ratios of one face unit;
  - one section per part with binding numbers;
  - a **lines plan** (§F in Miki's spec): which edges must draw as feature lines;
  - a **likeness checklist** (§I, about 20 items), which the review rounds score.

  Later the code wins over the spec. Mark deviations in comments, and list spec fields that nothing reads in
  `rig.SPEC_ONLY_FIELDS`.
- **Toolkit.** Import `tools/charmodel/` (it was extracted from `tools/miki_model/` when Reiya landed: `meshkit`, the
  closed-shell builders, `validate`, `fix_nesting`, `feature_silhouette_vertices` and the fan helpers; `assembly`:
  `Character`, `assemble`, statistics; `export`; `preview`; `cli`). It has no character content, so import it instead of
  forking it, and never put a character's number, colour or text in it. A character package is its own `rig.py`,
  `mannequin.py` and part modules plus thin `assemble.py`, `export.py`, `preview.py` and `tools/make_<name>_model.py`
  copied from `tools/reiya_model/` with the data replaced; the toolkit README says what each must define. A change to
  `charmodel` changes every character: regenerate and test each of them (the extraction's own check was that Miki
  regenerated byte for byte).
- **Stated height.** Measure and build at the design sheet's scale (one scale for every view). When the user states the
  height, give the `Character` a `scale` (Reiya: `assemble.figure_scale`, `rig.stated_height / rig.skin_height`) rather
  than rescaling the rig, the spec and the builders; the writers scale the scene camera and the previews their framing
  by the same factor. Decide it before the docs are written: every quoted height is the final one, and Reiya's README
  had to wait for the scale.
- All numbers live in a frozen `Rig` dataclass. Builders read `rig.*` and contain no literals. A grey mannequin part
  exists for every region, so each module can be previewed in context before the others exist.

## 2. Objects, then parts in parallel

- **Objects come first and are spatially compact.** Group parts into castplane objects by place, not by colour. The
  hidden-line pass tests a sample only against objects whose image rectangle contains it, and the ray cap of 64 is
  per object. Miki has 18 objects, from 58 closed shells; Reiya has 27, from 115 parts. Colour belongs to the part
  (`material`), and the object's `display_color` is its dominant material colour (D81, read only by the web 3D views).
- **Object split and order are a performance tool.** Measure the web still frame against the last model in the same
  container; Reiya's first merge was 5 % slower than Miki's and the objects brought it below. The finishing pass's
  smooth bob (one shell of 1292 triangles) made her slower again, because every line of the face, the head, the dome
  and the braids was tested against it (cost model 21.0 -> 24.6 M ray-triangle tests, Miki 21.7 M); cutting it into
  three shells along its outer back strand lines brought it to 19.3 M. Split a big or wide
  object by side (eyes, face marks, braids, arms, socks, shoes: one per side), because a left sample is then never
  tested against right-side triangles. Do not split where the two parts' shadows overlap: castplane draws the cast
  shadow per object, so such a split adds inner shadow outlines (Reiya's hem band, skirt stripes and hands were
  rejected for it). Order the objects with the outer layers first, top to bottom (cardigan, arms, face, hair, clothes
  under the cardigan, skirt, feet): the pass stops at the first occluder that hides a sample, so the objects that hide
  the most come early.
- **`objects[0]` matters.** The web observer pane draws sight rays to every vertex of the first object. Put a small,
  telling part first (Miki: the headband, 120 vertices; Reiya: the two ear tufts, 152 vertices).
- **Split the builders by file ownership** so that agents run in separate worktrees: head + hair in one, body + limbs
  in the other (Reiya: head + hair, body, cardigan + limbs). Each writes only its own modules; one merger agent merges
  them (a 3-way merge of `rig.py`, which every owner edits), fits the seams (neck / collar, hair / shoulders) and
  regenerates. If the user forbids worktrees or git writes (Reiya's build), give each builder and fixer a private copy
  of the package under the scratchpad (`cp -r` of `tools/<name>_model`, `tools/charmodel` and the CLI script) and have
  it write only there, with trials going to `--out-dir` or `--only`. The merger copies each owner's files back and
  3-way merges `rig.py` with `git merge-file -p`, which writes no git state. Only the merger writes into the
  repository and `examples/`, and nothing is committed.

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

## 3b. Finish criteria and the overlay check (when the character has a design sheet)

Review rounds judge likeness by eye and a finding without a number stays "minor" round after round. Reiya's finishing
pass ran on numbers: `python3 tools/make_reiya_model.py --overlay SHEET.png DIR` (the toolkit's `overlay.py` plus the
character's own `tools/<name>_model/overlay.py`; the method is in `tools/charmodel/README.md`, her criteria are the
`CRITERIA` of her `overlay.py` and the report it writes) renders the front, side and back views orthographically into
the sheet's pixel grid, scaled to the sheet, lays them over it at 50 % and reports each landmark's offset in mm on the
final model, with the smoothness of the shapes that read as "faceted".
- **Every finish criterion closes with a number and a priority** (P1 must pass, P2 should): "the bob's lower edge
  within 6 mm per column on average", "no dihedral over 25 degrees inside one smooth group of the bob", "lit-side face
  R - B at least 15". Set each limit from a measurement of the current model; none under about 1.5 ink widths of the
  sheet (the sheet's own line is part of its silhouette), and never loosen one to pass.
- **Measure what a viewer sees.** The first version measured each part alone and counted a rim buried in the dome; count
  only faces and outline edges that are front-most in the whole model's z-buffer from a review camera.
- **At most three fix rounds**, then stop and report every criterion that still fails with its value (Reiya: 19 of 41
  passed before the pass, 35 after it and 36 after a leaf pass that gave the bob's lock ends leaf-shaped tips; M5 has
  nothing to measure, four P2 rows are open and listed in her README).
- **The sheet and `DIR` stay outside the repository**: the images contain the sheet (the CLI refuses a `DIR` inside it).
  `tests/test_charmodel_overlay.py` checks the method on a synthetic sheet, so the tests need no real one.
- **Smoothness can cost budget.** If the criteria cannot pass inside the cap, report the shortfall with a fresh web
  bench (still frame against the previous character's, alternating, same container) and leave the decision to the user:
  `assemble.BUDGET` is Reiya's 6500 polygons / 10600 triangles, which the user decided to keep on 2026-11-01.

## 4. Integration

- Add a scene file `examples/<name>.json`. The scene needs:
  - a sun from the viewer's upper left;
  - a ground plane;
  - a 3/4 front camera with a portrait frame;
  - `output.layers` set to `["objects", "cast_shadow"]`. castplane does not occlude the form- and cast-shadow
    **fills**, so with `form_shadow` on, back-lit hair shows through the face.
- Vite bundles every `examples/*.json` into the web Example menu. `tests/test_ts_port.py` asserts the number of
  examples (`len(examples) == 10` with Miki and Reiya) and names the character examples, so a new example must update
  that count and the set.
- Write `tests/test_<name>_model.py`, modelled on `tests/test_miki_model.py` (or Reiya's, which also pins the scale:
  soles at `z = 0`, the stated height, the head top, the scaled scene camera). It pins byte-identical regeneration,
  closed manifolds with no mesh fallback, `warnings == []`, the budget and the ray cap, and `display_color`.
- Docs: the generator's README and SPEC (in English), `examples/README.md`, `docs/USAGE.md` and `README.md` (in
  Traditional Chinese), a section in `COPYRIGHT_NOTICE.md`, and a §5.4 implementation note when the model needs a
  contract-visible change. Quote the object and polygon counts, and update them whenever the model changes. Pin the
  quoted numbers in the character's test (Reiya's `DOC_QUOTES` in `tests/test_reiya_model.py`: counts, file sizes, SVG
  length, test count), because nothing else fails when a regeneration leaves a document stale.
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
- **A twisted quad's ridge fan hides its own silhouette edge.** castplane fans each face from its first vertex. On a
  twisted quad of a curved shell the ridge diagonal bulges over the quad's own silhouette edge, and the hidden-line
  pass then drops that piece of outline (for Reiya's skirt and top in 7 of 16 views, 5 to 9 % of the figure's height at
  worst, and again for her sleeves and limbs). Write every loft-built shell through `meshkit.inscribed_fan` (the valley
  diagonal, no polygon cost). Thin bands on a twisting surface take `fan_fold` instead (do not wrap those:
  `inscribed_fan` undoes it), and `split_twisted` is for a quad that stays folded after fanning. Scan for it: compare
  the boundary of the shaded silhouette with the ink of the hidden-line render over 72 azimuths. Do it when a part is
  first written, not after the review.
- **A scale shrinks every relief.** The stated-height scale makes a 0.5 mm decal 0.489 mm, under rule 5. After a scale
  (or a change of it), raise the fields at the floor, divide the floats that are under 0.5 mm by design (silhouette
  borders, tapered ends) by the scale so they keep their verified standoff, and re-measure every decal layer on the
  rounded final meshes.
- **Sheet conventions are not 3D.** A flat design sheet draws hair 2 to 3 cm in front of the face in profile, hems as
  look-down curves and eyes wider than the face wraps. Built literally they float, tilt or wrap in the 3/4 views. Use
  the views that agree, resolve the rest in 3D and record each choice as a Decision.
- **castplane draws no line where two objects meet.** There is no intersection line between objects (Reiya's chin
  against the neck in low views, a sleeve cap under a band), so a line that must show needs a silhouette or a group
  boundary of one shell there; otherwise record it as a known limit rather than trying a keel group (it draws a lens).
- **Web scene download of mesh scenes** once wrote face indices as `26.0`, which the CLI rejected. This is fixed in
  `web/src/download.ts`. Re-check that the CLI renders a downloaded scene with the same SVG as the web UI.
- **Hidden geometry still draws ground-shadow strokes.** A part no camera sees (Reiya's white sleeve tubes under the
  balloon sleeves, the straps' back ends, a bob cut into three objects) draws nothing in the `objects` layer, but its
  shadow on the ground is a fill and an outline per object in `cast_shadow`. Trimming or splitting "invisible" geometry
  changes the shadow drawing, so diff the `cast_shadow` layer in the scene camera as well as the object lines.
- **Performance figures depend on the container.** The still frame measured about 1.4 s in the container where Miki
  was built and about 2.4 s in a later one, with the same code; in the container of Reiya's finishing pass, with the runs
  alternating, Miki took 2.9 to 3.5 s and the finished Reiya 2.7 to 2.9 s, and a parallel job moves a figure by 10 %
  or more.
  Measure the current `examples/miki.json` in the same container, at the same time, as the baseline before you judge a
  new model against the 1.5 s target, and interleave the runs.
- **What users ask afterwards.** The drawing pane is an uncoloured line drawing by design; colour shows only with
  "3D view" ticked or in the observer pane. Turn on Hidden lines with style omit, and keep the eye above the ground.
  Put this in the user-facing docs.

## Model choice for this task

| work | model |
| --- | --- |
| spec from references, likeness critic, part builders, fixers, mergers, integration | `opus` |
| line-art / technical critic, docs, gates and screenshots | `sonnet` |
| count, typo and reference fixes | `haiku` |

Builders and fixers run in worktrees (`isolation: "worktree"`), or in private copies when the user forbids worktrees
(§2). Nothing in `castplane/`, `ts/`, `web/` or `tests/conformance/` changes for a model; if it must, that is a
separate change with its own D-number and review. Remove the worktrees after their branches are merged
(`git worktree remove`, then `git branch -d`).
