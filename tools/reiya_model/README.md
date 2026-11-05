# tools/reiya_model: maintainer guide

> **Rights notice:** Reiya and her design belong to her creator; this model is a drawing reference made from the creator's design sheet; the character is not part of this project's authorized distribution (the GPL-3.0 licence covers the castplane software only). See [`COPYRIGHT_NOTICE.md`](../../COPYRIGHT_NOTICE.md).

This package generates the Reiya (レイヤ) drawing-reference model: `examples/reiya.json` (the castplane scene, 27 inline
`mesh` objects) and `examples/meshes/reiya.{obj,mtl,glb}` (the same model for other 3D software). She is an anime girl
152 cm tall (barefoot) with a salmon-pink bob, two ear-shaped hair tufts, two braids, a navy jumper dress with a long
fluted skirt, a cropped cardigan with balloon sleeves, white socks and penny loafers. The package is a development tool
outside the castplane core. It holds Reiya's character content (rig, part builders, mannequin, objects, materials,
texts, camera presets, and the data of her overlay check); the character-free machinery (mesh builders, assembly,
writers, previews, the overlay check, the command line) lives in the shared toolkit
[`tools/charmodel/`](../charmodel/README.md), which Miki's package uses too. The geometry modules import numpy and the
standard library only; the previews also use Pillow and cairosvg (both in the `dev` extra). The four generated files
are never edited by hand: change the generator and regenerate. `tests/test_reiya_model.py` compares them byte for byte.

After five review rounds the user reviewed the model (2026-10-31) and the package went through a **finishing pass**: a
warm skin colour, a smooth bob with layered tapered locks, fuller balloon sleeves with gathered cuffs, relaxed hands
and arms, and a numeric finish check that lays the model over her design sheet (the overlay check, below). The sections
that follow describe the model as finished; "Open after the finishing pass" at the end lists what still fails.

This package is the second character built on the toolkit. [`tools/miki_model/README.md`](../miki_model/README.md) is
the first guide: the 10 mesh rules, the building blocks (`meshkit`), the full list of CLI options and the process in
`.claude/skills/character-model/SKILL.md` apply here unchanged, and this file does not repeat them. It covers what is
different about Reiya.

The user-facing description of the scene is in `examples/README.md`, the command line in `docs/USAGE.md` (section 5.3),
and the contract note is the bullet "`examples/reiya.json` is the tenth example" in the §5.4 implementation notes of
`docs/ARCHITECTURE.md`. The character spec is
[`SPEC.md`](SPEC.md): it was written before modelling from the creator's design sheet and then refined in review
rounds, so where it and `rig.py` or a builder disagree, the code wins. Comments in the code cite it as `SPEC.md §X`; a
bare "spec §N" elsewhere in the repository means `docs/spec/spec-v0.1.md`. The design sheet and the other reference
images are not in the repository.

## Layout

| file | what it holds |
| --- | --- |
| `../make_reiya_model.py` | the CLI: Reiya's `charmodel.cli.Tool` (name, title, rig, the three modules below) handed to `charmodel.cli.main` (build, validate, write the four files, optional previews and checks) |
| `../charmodel/` | the shared toolkit: `meshkit.py` (closed-shell builders, `validate`, `fix_nesting`, the fan-diagonal helpers), `assembly.py` (`Character`, `assemble`, statistics), `export.py` (the writers), `preview.py`, `overlay.py` (the overlay check and the smoothness metrics), `cli.py` |
| `rig.py` | `Rig`, a frozen dataclass: every proportion, landmark and pose number, with the SPEC.md section in its comment; `SUN_TOWARDS`; `stated_height`, `figure_scale` and the `final_*` heights |
| `mannequin.py` | simple placeholder parts for every region (what `--context` draws in grey) |
| `head.py`, `hair.py`, `body.py`, `cardigan.py`, `limbs.py` | the detailed parts; each has `REGIONS` and `build(rig)` |
| `assemble.py` | Reiya's objects and materials (`OBJECTS`, `MATERIALS`, `DISPLAY_MATERIALS`, `REGION_OBJECTS`, `MODULES`, `BUDGET`), her `charmodel.assembly.Character` (`CHARACTER`, with `scale=figure_scale`) and wrappers (`assemble`, `build_parts`, `format_stats`, `display_color`, `figure_scale`) over `charmodel.assembly` |
| `export.py` | Reiya's texts (`SCENE_SETTINGS`, `DESCRIPTION`, `NOTICE`, the OBJ / MTL headers, the GLB generator and copyright), the scene camera (`SHEET_CAMERA`, `scene_settings(rig)`) and wrappers over the writers of `charmodel.export` |
| `preview.py` | Reiya's camera presets (`PRESETS`, `cameras(rig)`) and wrappers over the shaded renders, castplane line renders and contact sheets of `charmodel.preview` |
| `overlay.py` | Reiya's half of the overlay check: how her design sheet is drawn (view mapping, colour classes), the row bands, outlines, lower edges, landmarks, the smoothness parts and views, and the 41 pass criteria (`SPEC`, `CRITERIA`) |
| `SPEC.md` | the character spec: landmark tables, one section per part, the lines plan (§F), the objects plan (§G), the likeness checklist (§I), the self-consistency checks and the numbered Decisions |

Unlike `miki_model`, this package has no `meshkit.py`: the part modules import the toolkit directly
(`from charmodel import meshkit as mk`). A change to `tools/charmodel/` changes every character it touches, so
regenerate and test both Miki and Reiya after one.

Regions per module: `head.py` has `head`, `eyes`, `face_marks`; `hair.py` has `hair`, `tufts`, `braids`; `body.py` has
`neck`, `top`, `dress`, `buttons`; `cardigan.py` has `cardigan`, `sleeves`; `limbs.py` has `hands`, `legs`, `socks`,
`shoes`. A module whose `build(rig)` returns `None` is replaced by `mannequin.py` for its regions (all five are written
now). The all-mannequin model is itself a valid model, so any one module can be previewed in context while the others
are placeholders.

## The part, object and material model

A **part** is one named piece: `Part(name, material, mesh, region="", *, obj="")` (`charmodel.meshkit.Part`).
- `name` is unique in the whole model and carries the module as a prefix (`hair.bob`, `limbs.shoe_l`).
- `material` is the part's **colour**, a key of `assemble.MATERIALS` (18 of them): `hair`, `hair_inner` (the lavender
  under-layer), `tuft_inner`, `skin`, `eye_white`, `iris_red`, `pupil_red`, `iris_blue`, `pupil_blue`, `lashes`,
  `face_marks`, `top`, `dress`, `buttons`, `cardigan`, `socks`, `star`, `shoes`. Her right eye is red and her left eye
  blue (heterochromia), which is why the iris and pupil materials come in pairs. The colours are sampled on the design
  sheet (SPEC.md §H) and are used by the OBJ / MTL / GLB and the shaded previews.
- `obj` is the castplane **object** the part is merged into, one of `assemble.OBJECT_IDS`. Left empty it is
  `assemble.REGION_OBJECTS[region]`. Seven of Reiya's regions have **no default** (`None`: `eyes`, `face_marks`,
  `braids`, `sleeves`, `hands`, `socks`, `shoes`) because their objects are per side, so every part of them sets `obj`
  (`eye_l`, `braid_r`, `shoe_l` ...). Other parts override a default: the fringe sets `obj="fringe"`, the bob
  `obj="bob"` (the three shells of the bob are `bob_l`, `bob` and `bob_r`, see below), the lavender under-layer
  `obj="hair_under"`, the skirt `obj="skirt"` (default of `dress`: `bodice`), the white sleeve tubes of `top` would go
  to `arm_l` / `arm_r` (off since the finishing pass: `body.TOP_SLEEVE_TUBES`), and the cardigan's round button goes
  to `buttons`.
- `region` is one of the module's `REGIONS`; `--only` filters by it. A part without a region must set `obj`.

Two objects get parts from more than one module: `arm_l` / `arm_r` (the sleeve and cuff from `cardigan.py`, the hand
from `limbs.py`, and the white tube from `body.py` when `body.TOP_SLEEVE_TUBES` builds it) and `buttons` (the dress
buttons from `body.py`, the cardigan's button from `cardigan.py`). A part module that returns a list replaces **all**
of its regions, so return every region; the rounding, validation, per-object merge, smooth-group renumbering and
`fix_nesting` are `charmodel.assembly.assemble`, driven by the `Character` in `assemble.py`.

An **object** is what castplane sees: a spatially compact group of parts. Each carries a `display_color` (the colour of
its dominant material, `assemble.DISPLAY_MATERIALS`), which only the web UI's 3D views read. The order is fixed
(`assemble.OBJECTS`) and was chosen for two reasons:
- **`tufts` is first.** The web UI's observer pane draws its sight rays for every vertex of `objects[0]`; the two ear
  tufts (about 150 vertices, the first thing people recognise) show their perspective without hiding the figure.
- **Outer layers first, top to bottom** (the cardigan and the arms, the face, the hair, the clothes under the cardigan,
  the skirt, the feet). The hidden-line pass tests a sample against the occluders in this order and stops at the first
  one that hides it, so the objects that hide the most lines come early.

| # | object | holds |
| --- | --- | --- |
| 0 | `tufts` | the two ear tufts H5 with their lighter inner-face decals |
| 1 | `cardigan` | back + 2 fronts, front / neck bands, plain hem band |
| 2 | `arm_l` | her left balloon sleeve (rounded bottom, gathered at the cuff) with its ribbed cuff, hand + 5 fingers |
| 3 | `arm_r` | her right balloon sleeve with its ribbed cuff, hand + 5 fingers |
| 4 | `face_marks_l` | her left lash band with its flick, brow and 3 blush strokes, and the mouth |
| 5 | `face_marks_r` | her right lash band with its flick, brow and 3 blush strokes |
| 6 | `eye_l` | her left eye: sclera, blue iris, pupil, highlight |
| 7 | `eye_r` | her right eye: sclera, red iris, pupil, highlight |
| 8 | `fringe` | fringe H2: swept lock SL, locks A-C, lock D as two plates |
| 9 | `neck` | neck |
| 10 | `bob_l` | the bob H3's left side: her left curtain, side lock and back locks out to the outer back strand |
| 11 | `bob_r` | the bob H3's right side |
| 12 | `bob` | the bob H3's back between the two outer back strands, down to the nape |
| 13 | `hair` | dome H1 |
| 14 | `head` | skin head with the nose bump |
| 15 | `braid_l` | her left braid H6: 5 pointed lobes, tie, 3-lock end tuft |
| 16 | `braid_r` | her right braid H6: 5 pointed lobes, tie, 3-lock end tuft |
| 17 | `hair_under` | the lavender under-layer H4: a short lining strip on each curtain's front lock, one V-shaped under-lock per side |
| 18 | `top` | mock neck with the lettuce rim, its flare and the fold at its base, shoulders / upper chest |
| 19 | `bodice` | bodice (square-neckline rim, high-waist seam edge, placket creases), 2 straps |
| 20 | `buttons` | 17 teardrop dress buttons, the cardigan's round button |
| 21 | `skirt` | fluted A-line skirt (placket creases), hem rim, inner facing, ceiling, 8 flute-valley line stripes |
| 22 | `shoe_l` | her left penny loafer (sole, block heel, upper, saddle strap with the penny slot, apron seam) |
| 23 | `shoe_r` | her right penny loafer |
| 24 | `sock_l` | her left sock, its cuff fold and star |
| 25 | `sock_r` | her right sock, its cuff fold and star |
| 26 | `legs` | legs x2 |

Currently 115 parts (123 closed shells: each hand's five fingers are one part), 5530 vertices, 6354 polygons and 10576
triangles. SPEC.md §G has the per-object polygon and ray counts (the largest ray count is `top`'s 51 of 64). To add,
split or reorder objects, change `OBJECTS` and keep `DISPLAY_MATERIALS` in the same order (the `Character` constructor
checks it), then update the object lists that `export.DESCRIPTION`, `examples/README.md` and SPEC.md §G quote.

Splitting objects by side is what keeps the hidden-line cost down, and it has a limit. The eyes, face marks, braids,
arms, socks and shoes are one object per side: a sample is tested only against objects whose image rectangle contains
it, and one object per side stops the left side's lines being tested against the right side's triangles. The two
sides' ground shadows do not overlap, so the cast shadow draws the same lines. **Do not split where the shadows do
overlap:** castplane draws the cast shadow per object (a fill and an outline each), so a split at an overlap adds inner
outlines to the shadow. The hem band, the skirt's valley stripes and the hands were tried as objects of their own for
the speed and rejected for that reason (review round 1).

**The bob is the one deliberate exception** (finishing pass, merge; SPEC.md Decision 32). The smooth bob is one shell of
1292 triangles, and as one object it was tested by every line of the face, the head, the dome and the braids: the web
still frame's cost model went from 21.0 to 24.6 M ray-triangle tests, and no split with non-overlapping shadows was
available. `hair.BOB_SPLIT_STRAND = 15` therefore cuts the shell along its outer back strand line on each side into
three closed shells, the objects `bob_l`, `bob` (the back and the nape) and `bob_r`. Each cut runs from the bell's top
(inside the dome) down the strand line to its notch and is closed by a cap inside the hair. The shells share no vertex
and no face: the back shell's own copies of the cut's vertices are tucked 0.107 mm past the cut into the side shell and
as far into the hair (`hair.BOB_CUT_TUCK`), so its cap lies inside the side shell, the side shell's cap inside it, and
the strand line is drawn once, where it was. It cost +28 polygons and +56 triangles, brought the cost model to 19.3 M
(Miki's is 21.7 M) and left the bob with 25 / 29 / 36 rays instead of 58 (after the leaf-shaped lock ends 25 / 28 / 37
instead of 57; since the V4 pass 22 / 28 / 34 instead of 51). The drawing effect: the scene camera's and the 3/4 views'
object lines are pixel-identical; the cut's inner edge draws as one new line on the bob's underside behind the side lock
seen from below (`low_angle`, `head_low`), and a few strokes appear inside the head's dense ground shadow (castplane
casts one shadow per object). This departs from the rule above; the user kept it on 2026-11-01 ("keep the raised cap and
the split"). **To undo it**, set `BOB_SPLIT_STRAND = None` (the bob is then one part in one object `bob`; an object
without parts is left out of the scene, and `overlay.SMOOTH_PARTS` already lists the unsplit part), remove `bob_l` and
`bob_r` from `assemble.OBJECTS` and `DISPLAY_MATERIALS` (the tests and the docs compare the scene with `OBJECT_IDS`),
regenerate, update the object lists and counts (6326 polygons / 10520 triangles, 25 objects; the one bob 51 rays) and
measure the web still frame against Miki's again: expect it to be slower. Because the shells share no vertex, an
imported OBJ (one object for the whole model, whose vertices castplane welds at 1e-6 m across shells) stays a closed
manifold; with coinciding caps it reported `MESH_NON_MANIFOLD` (44 edges with three or more faces).

## Changing proportions (`rig.py`)

Every number the builders use is a field of `Rig`. Read dimensions from `rig` and add a new dimension as a new named
field with a comment (and the SPEC.md section), not as a literal in a builder. Points are `(x, y, z)` for her left;
`rig.at(p, side)` mirrors them (`side = +1` left, `-1` right). The landmark table (`rig.landmarks`, SPEC.md §A) drives
the derived heights (`rig.height`, `chin_z`, `eye_z`, `seam_z`, `hem_z` ...), so editing a row moves them. The tables
of rows (`head_profile`, `hair_rows`, `bob_rows`, `top_rows`, `bodice_rows`, `skirt_rows`, `cardigan_rows` ...) are read
by the surface models that decals and clothes sit on: `rig.head_surface_y(x, z)`, `rig.head_normal(x, z)`,
`rig.hair_surface_y`, `rig.top_section(z)`, `rig.skirt_point(z, phi)`, `rig.cardigan_surface_y`, and so on, built on
`Rig.section_point` / `Rig.section_ring` (the superellipse section model of SPEC.md §A).

Two ways to change a value:
- edit the default in `rig.py` and regenerate (the way to change the shipped model);
- try it without touching the code: `python3 tools/make_reiya_model.py --only hair --preview /tmp/p --rig mine.json`,
  where the file is a JSON object of `Rig` fields (`Rig.from_dict`: unknown keys raise, lists become tuples). In
  Python, `Rig().replace(...)` does the same.

Some fields are inert: `rig.SPEC_ONLY_FIELDS` are SPEC.md values that no builder reads (pose angles that document the
joints, the hidden guides `body_rows` and `cranium_radii`, shapes that come from module constants), and
`rig.MANNEQUIN_ONLY_FIELDS` are read only by the grey `--context` parts. `Rig.from_dict` warns when you override one.
The two sets are exact: a trace of the fields the builders read (run once when they were last updated) found no other
unread field. A change of
proportions can break the rules below (a decal sunk into the skin, a count over a cap), so run `--check` after it.

### Her height: the sheet scale and the stated height

The rig, SPEC.md §A-§E and every builder are at the **design sheet's scale**: one scale for all views, 0.615 mm per
pixel, which gives a skin height of 1.555 m. Her real height came later, from the user: **1.52 m barefoot** (sole of
the foot to the skull top), `rig.stated_height`. The model is scaled to it:
- `rig.figure_scale = stated_height / skin_height = 1.52 / 1.555 = 0.97749`. `assemble.CHARACTER` is built with
  `scale=figure_scale` (the optional `Character.scale` of the toolkit), so `charmodel.assembly.build_parts` multiplies
  every part's vertices, the mannequin's too, by it about the origin and before the rounding. The soles stay on
  `z = 0`, and the bytes stay deterministic (an elementwise product).
- The scene camera is `export.SHEET_CAMERA` (framed on the sheet-scale model) with its position and target scaled by
  the same factor (`export.scene_settings(rig)`), so the drawing is the same picture as on the sheet-scale model. The
  preview framing (`preview.cameras(rig)`) is scaled likewise.
- `rig.final(length)` and the ten `final_*` properties (`final_skin_height`, `final_height`, `final_hair_top_z`,
  `final_figure_top_z`, `final_eye_z`, `final_chin_z`, `final_head_height`, `final_seam_z`, `final_hem_z`,
  `final_heel_lift`) give a sheet-scale length at the final scale. Docs, the scene description and the tests quote the
  final figures.

The final key heights: skull top in her loafers 1.554 m, hair crown 1.570 m, ear-tuft tips 1.578 m (the highest point),
eyes 1.426 m, 7.37 heads tall to the hair crown (a ratio the scale keeps). To change her height, set `stated_height`
(in `rig.py`, or `{"stated_height": 1.60}` in a `--rig` file): the scale, the camera and the framing follow. At
`stated_height = skin_height` the scale is 1 and the model is the sheet-scale model.

A relief, a float or a gap shrinks with the model, so a decal's standoff must be re-checked on the **final** model
(rule 5 below). To change `heel_lift` is also to change the scale (it is part of `skin_height`).

## The finishing pass (2026-10-31)

The user's review of the five-round model named four things that made her look unfinished and borrowed two methods from
mesh-avatar-studio (the overlay check and explicit pass criteria, below). The finishing pass answered with these
changes, each described in SPEC.md (section in brackets) and recorded as a Decision (30, 31, 32):

- **Warm skin** (Decision 30): `assemble.MATERIALS["skin"]` became `#fae3d8`, the warm mid-tone between the sheet's
  flat `#fff8f1` and its cel shadow `#f6cebf`. As a 3D albedo the sheet's near-white shaded to a neutral grey on the
  lit side of her face (RGB 143, 139, 136); with `#fae3d8` R - B there was 21 (criterion C1, at least 15). Miki's skin
  is `#fbe3d6`. A one-line change. **Rosier since the V4 pass** (2026-11-01, the user's "skin still looks a bit dull,
  please give her a natural rosy glow"; Decision 33): `#fad8cd`, the hue 4.7 degrees towards pink with more saturation
  and the same value, the largest warm step of five candidates that still keeps the face apart from the salmon hair
  and the lit side as light; C1 is 27. Only the colour changed (the three skin objects' `display_color`, the MTL's Kd,
  the GLB's baseColorFactor); no blush decal or vertex colour (Decision 6).
- **A smooth bob** (SPEC.md §C.3). The bell above z 1.452 has 13 contour columns per side (it had 5) at even turning
  of the section's tangent, about 9 degrees per column, and its rows are read through a monotone cubic. Below it the
  **lock zone** is traced from the sheet: layered, tapered locks (each tip at the lock's inner end, a step ending a
  lock on its neighbour's column), 18 mm rows, a lock thinning to 20 % of the bob's thickness and curling in 1 mm at
  its edge, two slits per side from the tips up to z 1.452 (the sheet's standing-off outer strand), and two strand
  lines per side down the back, drawn as group boundaries. The lavender lining is one short strip behind each
  curtain's front lock (it ran round the curtain's inside and drew a kink from below), and each under-lock is one V.
  The dome's three lowest rings take the bob's own columns (`hair.DOME_SEAM_MATCH`), so the two shells meet in a
  straight level seam instead of crossing back and forth. The sawtooth lower edge of the 20 mm teeth is gone:
  the lower edge at the sides is 5.2 mm off the sheet per column on average (was 10-11), 10.8 mm at the 95th
  percentile (was 32-40).
- **The bob in three shells** (`hair.BOB_SPLIT_STRAND`, above): the price of the smooth bob in hidden-line time.
- **Balloon sleeves and gathered cuffs** (§D.7). Five elliptic rings along the arm, fitted ring by ring to the sheet's
  balloon (widest 0.215 at z 0.90, rounding in over the cuff), 15 points per ring, so neighbouring facets meet at about
  24 degrees; the rounded bottom, 30 mm deep, converges onto the cuff and its second smooth group draws the **gather**,
  the cuff's top. The cuff is a ribbed cone with a level mouth and a recess cone. A sleeve went from 141 polygons /
  278 triangles to 285 / 450. The white sleeve tubes of the top are off (`body.TOP_SLEEVE_TUBES`).
- **Relaxed hands and pose** (§D.8, §E). The four fingers lie together and curl 16 to 26 degrees at each joint (the
  little finger most; 6-12 before), the thumb is shorter and curled forward, the palm turns forward. The wrist moved
  in from x 0.170 to the sheet's 0.160 (shoulder-to-wrist angle 0.1 degrees over the sheet's 10.1), and the elbow bends
  17 degrees. The sleeves still clear the skirt by 10.95 mm: the bag's shape gives the room, not a wrist moved out.
- **Where the triangles went.** The body gave 308 triangles (the hidden backs of the top and the bodice, the white
  tubes, the straps' hidden back ends, a coarser floor of the mock neck's dent: `body.TOP_SLEEVE_TUBES`,
  `STRAP_HIDDEN_BACK_STATIONS`, `TOP_FLOOR_POINTS_PER_WAVE`; nothing visible changes in the scene camera), the head
  and hair took 700, the cardigan and limbs 188: 6216 polygons / 10396 triangles in all, from 5540 / 9816. The leaf
  pass (the leaf-shaped lock ends, below) added +148 polygons / +196 triangles to the bob (6364 / 10592), and the V4
  pass took -10 / -16 from its side shells: 6354 / 10576 now.

**The budget is decided.** The model is over the old 6000 polygons / 10000 triangles. The finishing pass raised
`assemble.BUDGET` provisionally to 6500 / 10500; on 2026-11-01 the user decided "keep the raised cap and the split, add
leaf-shaped tips", and with the leaf-shaped lock ends (+196 triangles) the limits are **6500 polygons / 10600
triangles**, the smallest multiple of 100 that fits (SPEC.md Decision 32; the 64 construction rays per object and the
scene's 700 KiB stay hard limits). After the V4 pass (2026-11-01; Miki first in each of four alternating rounds on an
idle container, medians of the per-round medians) Reiya's still frame took 2783 ms against Miki's 3060 ms (9.0 % faster,
faster in 4 of 4 rounds), her drag frame 101 ms against 71 ms (the 120 ms target holds on the median; single rounds
reached 108 ms, and 124 ms in a supplementary round) and stage A 267 ms against 197 ms. The container is noisy: Miki's
unchanged file moved +6 % (still frame) and +17 % (stage A) against the leaf pass's rounds, and the file before the V4
pass, run alternately with the new one, gave the same drag frame (94.6 against 96.9 ms, medians of three). The figures
below are the finishing pass's. What counts is the web still frame against Miki's, measured in the same container, the
scenes alternating (`node tools/web_frame_bench.mjs <scene> 5`, 6 rounds per session, medians of the per-run medians).
The numbers below are container-dependent and are given for the comparison only:

| model | still frame, session 2 | still frame, session 3 | against Miki, per round |
| --- | --- | --- | --- |
| Miki | 3396 ms (3283-3554) | 2938 ms (2777-3268) | |
| Reiya before the pass | 3172 ms (3054-3383) | | |
| the merged pass, before the body options and the bob cut | 3590 ms (3501-3861) | | +6.7 %, slower in 6 of 6 |
| the final model | 2937 ms (2736-3168) | 2778 ms (2472-3064) | -14.0 % and -7.7 %, faster in 11 of 12 |

Drag frame medians of the final model 106 and 114 ms in the merger's two sessions (84-138 ms per run; Miki 78-91 ms).
A later, shorter check (the documentation sync: three runs of Reiya alternating with two of Miki, other jobs running)
gave the same picture, Reiya's still frame 2.75-2.83 s against Miki's 3.07-3.20 s, stage A 0.24-0.30 s against
0.21-0.24 s, but her drag frame 97, 98 and 123 ms against Miki's 65 and 76 ms: the 120 ms target of
`tools/web_frame_bench.mjs` is met by the median of most runs and is not met with room to spare. The deterministic cost
model of the still frame's hidden-line pass (ray-triangle tests in the scene camera): Miki 21.65 M, Reiya before the
pass 20.98 M, the final model 19.26 M. The figures of an earlier container (Miki 1.4 s) are not comparable.

## Previewing

The command line is `charmodel.cli`, the same as Miki's: every option, the exit statuses and the preset names are those
in the table of [`tools/miki_model/README.md`](../miki_model/README.md#previewing), with Reiya's regions for `--only`
(`head`, `eyes`, `face_marks`, `hair`, `tufts`, `braids`, `neck`, `top`, `dress`, `buttons`, `cardigan`, `sleeves`,
`hands`, `legs`, `socks`, `shoes`, or a module name: `head`, `hair`, `body`, `cardigan`, `limbs`).

```sh
python3 tools/make_reiya_model.py --only hair tufts braids --context --preview /tmp/p   # these regions in colour
python3 tools/make_reiya_model.py --only hair --lines /tmp/l --lines-views head_front head_side --lines-layers objects
python3 tools/make_reiya_model.py --check --preview /tmp/p --lines /tmp/l               # the full model, checked
python3 tools/make_reiya_model.py --check --out-dir /tmp/out                            # leaves examples/ alone
```

- `--out-dir DIR` writes `reiya.json` and `meshes/reiya.{obj,mtl,glb}` there (default: the repository's `examples/`).
  Use it for every trial; only a deliberate regeneration should write `examples/`.
- `--overlay SHEET.png DIR` is the overlay check against her design sheet (next section).
- Presets (`preview.PRESETS`, the same names and angles as Miki's): body `front`, `back`, `left` (camera on her left,
  `+x`), `right`, `three_quarter_left`, `three_quarter_right`, `three_quarter_back`, `top`, `low_angle`; head
  `head_front`, `head_three_quarter`, `head_side` (her right profile), `head_low`.
- From Python: `preview.camera_for(preset, rig)`, `preview.render_shaded(parts, camera, size)`,
  `preview.castplane_views(scene, presets)`, `assemble.assemble(rig, only=..., strict=False)` and
  `assemble.format_stats(model.stats)`. The statistics table widens its object column to the longest object id (Reiya's
  `face_marks_l` is longer than 10 characters).
- The framing follows the rig and the scale: `upper` starts 0.35 m (sheet scale) below the high-waist seam, `head`
  looks 0.55 head heights above the chin and fits 1.65 head heights (`preview.HEAD_TARGET_FRACTION`,
  `HEAD_FIT_HEADS`, `UPPER_BELOW_SEAM`). `--context` scales the grey mannequin parts like the model's, so they stand
  where the real parts would.

The scene camera stands 27° off the front of her, seen from the origin, on her left (`+x`); its view direction is 22°
off the front axis. It is at `[1.7595, -3.4505, 1.3685]` looking at `[0.2932, 0.1466, 0.782]` with 65 mm and a
24 × 36 mm portrait frame. The sun comes from the viewer's upper left (`SUN_TOWARDS = (-0.45, -0.55, 1.14)`, 58° high).
Her ground shadow (about 1.0 m long) falls to her left-back and stays inside the portrait frame.

## The overlay check and the finish criteria

`python3 tools/make_reiya_model.py --out-dir OUT --overlay SHEET.png DIR` lays the model over her design sheet (三面図) and
measures the differences, the check mesh-avatar-studio runs with a very long lens. The code is character-free and lives
in `tools/charmodel/overlay.py` (the method is in the
[toolkit README](../charmodel/README.md#the-overlay-check-overlaypy)); this package holds her data in
[`overlay.py`](overlay.py). **The design sheet is not in the repository**: pass its path
from outside, and `DIR` must lie outside the repository too (the overlay images contain the sheet; the command refuses
a `DIR` inside it). Add `--out-dir OUT` to keep `examples/` untouched. The run takes about 45 s.

- The model is rendered orthographically (a very long lens) into the sheet's pixel grid for her front (正面), left
  profile (よこ), back (後ろ) and the cardigan-off front (informational), with the mapping of the SPEC.md appendix
  (one scale, 0.000615 m per pixel; the model divided by `rig.figure_scale` first). Offsets are quoted in **mm on the
  final 152 cm figure**: one sheet pixel is 0.601 mm. `DIR` gets `overlay_<view>.png` (the sheet at 50 %, the model
  over it at 50 %, outlines in green and magenta) with zoomed crops, `diff_<view>.png` (red: sheet only, blue: model
  only) and **`report.md` + `report.json`** with every number and, first, the criteria table.
- **The criteria are data** (`overlay.CRITERIA`, a tuple of `charmodel.overlay.Criterion`: an id, the sentence that
  opens with its priority, the report values it reads, the reduction and the limit, and a note with the baseline it
  was set from). **P1 must pass, P2 should.** 41 of them: H1-H14 the hair against the sheet (the
  bob's outline within 4 mm, its lowest tip per side within 3 mm, the lower edge at the sides within 6 mm on average and
  15 mm at the 95th percentile, the nape, the tufts, the fringe, hair IoU), S1-S4 the sleeves (the balloon's half-width
  within 6 mm, the cuff, where the balloon is widest, the inner edge beside the skirt), K1 the skirt's flare within 5
  mm, F1-F5 the figure (IoU, legs, shoes, shoulders), A1-A5 the pose (the arm no further out than the sheet's, the
  fingers curled 10-30 degrees, the elbow bend 10-25 degrees, the hands where the sheet draws them, the sleeves at
  least 8 mm from the skirt), C1 the skin (lit-side R - B at least 15) and M1-M11 the smoothness of the bob, the lining,
  the sleeves and the dome. No overlay limit is under 3 mm, because the sheet's own ink line is 3-4 pixels (about 2 mm)
  and part of its silhouette and its views are near-orthographic, not exact.
- **Smoothness** counts what the whole model shows: the largest and the 95th-percentile dihedral angle between adjacent
  faces inside one smooth group (strand grooves and designed lines are group boundaries, folds over 60 degrees are
  designed rims and tips) and the turns of a part's outline in the 3/4 views at +-35 degrees and in `low_angle`, only
  for faces visible from one of 16 review cameras and outline edges where the part is the front-most surface of the
  full model's z-buffer. Turns over 60 degrees are tips (designed points, reported apart); a chain that doubles back
  on itself (over 170 degrees: a thin wall seen edge-on, two outline edges one pixel apart) is a fold, an artefact of
  the projection that counts as neither. An early version measured each part alone and counted the bob's top rim, always
  buried in the dome; the correction changed what is measured, no limit.
- **Exempt by Decision, reported but never a criterion:** the hair's depth in profile (Decision 8), the level hem
  against the sheet's curved one (9), the eye wrap (4), the profile's sleeve drape (15) and the cardigan-off view.
- **Rule:** at most three fix rounds against the criteria; after the third, stop and report every criterion that still
  fails with its value. Never loosen a limit to pass it. The exit status is 1 while a criterion fails; one that has
  nothing to measure (M5, the lining, which lies behind its lock in all three views) is reported as n/a and does not
  fail, and neither the command's count nor `report.md`'s ("36 of 41 pass") includes it. The same holds for a
  criterion whose measurement is partly missing (a landmark not found): it is n/a, never a pass on the rest, and the
  report names the missing keys.

**Result of the finishing pass** (the baseline model passed 19 of 41): 35 pass, M5 is n/a and 5 fail. **After the leaf
pass** (2026-11-01, the leaf-shaped lock ends): 36 pass, M5 is n/a and 4 fail, all P2; every P1 passes, M2 at 13.75
degrees. **After the V4 pass** (2026-11-01, the back slit's fold loop removed, the rosier skin): the same 36 pass and
the same 4 fail; M2 at 11.83 degrees (11.3 / 11.8 / 11.8 in the three views), M3 19.72, M4 11.84, C1 27. They are
listed in "Open after the finishing pass" below.

`tests/test_charmodel_overlay.py` (14 tests: 13 functions, one parametrised) checks the method on a synthetic sheet made from the model's own render (no
real sheet is needed): offsets 0 for the model against itself, a sheet shifted by k pixels reports k pixels in mm, the
smoothness metrics on spheres (a hidden face does not count; a sphere cut in two with the rims 0.1 mm apart has the
outline of the whole one), the criteria evaluator and the command line's refusals.

## Rules a part must obey

The ten rules of [`tools/miki_model/README.md`](../miki_model/README.md#rules-a-part-must-obey) hold for every part and
object (closed outward shells, nothing below `z = 0`, smooth groups make the lines, coplanar faces merge, decals at
least 0.5 mm proud, no near-duplicate vertices, at most 64 feature silhouette vertices per object, the budget,
determinism, Python 3.10 syntax). `--check` and `tests/test_reiya_model.py` enforce them. What this model adds:

1. **Fan every twisted quad (`meshkit.inscribed_fan`).** castplane triangulates a face from its first vertex. On a
   curved surface a quad's *ridge* diagonal bulges over the quad's own silhouette edge, and the hidden-line pass then
   hides a piece of the outline (the edge is covered by a triangle of its own face). Reiya's loft-built shells
   (skirt, top, bodice, cardigan, sleeves, palms, fingers, legs, socks, shoes) twist, so each is written through
   `mk.inscribed_fan`, which rotates each quad so its fan diagonal is the *valley* diagonal. It costs no polygon. Its
   absence showed up as outline dropouts in 7 of 16 views (review r1-T1) and again for the sleeves and limbs (r3-T1:
   gaps of 9 to 18 mm), so use it on a new part by default. A thin band that lies on a twisting surface (a decal stripe,
   a strap) uses `mk.fan_fold` instead (valley on the outer faces, ridge on the inner ones, so its two faces never
   cross); do not wrap those in `inscribed_fan`, which would undo it. `mk.split_twisted` costs polygons and is for a
   quad that stays folded after fanning. Check with an outline scan: compare the boundary of the shaded silhouette
   with the ink of the hidden-line render over many azimuths (72 in review round 3).
2. **Decal floors after the scale (rule 5).** The builders work at the sheet scale and the model is 2.25 % smaller, so a
   0.5 mm relief ends up 0.489 mm. The fields at or just over 0.5 mm were raised (`decal_layer_step`,
   `penny_slot_depth` 0.52 mm, i.e. 0.508 mm final), and the floors and floats that are under 0.5 mm by design
   (silhouette borders, tapered ends) were divided by the scale so they keep their verified values on the final model
   (`decal_skin_clearance`, `head.RELIEF_TAPER_END`, `shoe_decal_float`, `band_float`, `valley_stripe[2]`).
   When you touch a relief, a float or `stated_height`, measure the minimum standoff of the decal layers on the
   rounded **final** meshes (SPEC.md Decision 1 and the self-consistency section list the measured minimums).
3. **Object compactness and order** are part of the design, not tuning (above): per-side objects where the shadows do
   not overlap, outer layers first, `tufts` first. The hidden-line cost of the model against Miki's is the gate:
   a new part that grows a big occluder (the cardigan, the bob, the skirt, the top, the head) needs a measurement. The
   bob is the one exception to "split only where the shadows do not overlap" (above).
4. **Do not copy the sheet's 2D conventions into 3D.** The sheet draws the fringe and the front tips 2 to 3 cm in front
   of the face in profile and the hem as a curve (its look-down convention). Built as drawn, the hair floats in front of
   the face in 3/4 views and the hem is uneven. The model keeps the sheet's silhouette where the views agree and records
   each such choice as a Decision (SPEC.md Decisions 8 and 9: the hair hugs the face, the hem is level).
5. **Reasons for the lines are SPEC.md §F.** Each designed line is a group boundary or a separate floating shell; a
   colour border (the tuft's inner face, the straps, the buttons, the cardigan's bands, the sock star, the lavender
   lining) is a separate shell. Add a part by adding its row there.
6. **Hidden geometry still draws ground-shadow strokes.** A part that no camera sees (the white sleeve tubes under the
   balloon sleeves, the straps' back ends under the cardigan, the back of the skull) draws no line in the `objects`
   layer, but its shadow on the ground is a fill and an outline in `cast_shadow`, per object. Trimming or splitting
   "invisible" geometry therefore changes the shadow drawing: taking the tubes off lost a loop of strokes in each arm's
   shadow, and the bob's cut added strokes inside the head's dense shadow, while the objects layer stayed identical.
   Compare the `cast_shadow` layer in the scene camera (and `--lines-layers objects` for the other layer) before and
   after, not only the object lines.

## How the files are checked

```sh
python3 tools/make_reiya_model.py --check                      # rewrites examples/ and checks the rules above
python -m pytest -q -o addopts="" tests/test_reiya_model.py    # about 30 s; builds the model once per run
python3 tools/compare_svg.py examples/reiya.json               # Python vs the TypeScript port: 0 mismatches
```

`tests/test_reiya_model.py` (25 tests, modelled on `tests/test_miki_model.py`) pins what the shipped files promise:
- the generator reproduces `reiya.json` and `meshes/reiya.{obj,mtl,glb}` byte for byte, on every build;
- the scene objects are `assemble.OBJECT_IDS` in order, and every object is a closed, consistently oriented manifold
  that castplane takes without mesh preprocessing (no fallback, no `prep_warnings`);
- no two triangles of a bob object that share an edge lie back to back (normals opposite within 2 degrees; before the
  V4 pass ten edges at the two slits' tops were 180-degree slivers);
- stage A and the scene-camera render have `warnings == []`, with the default layers `objects` and `cast_shadow`;
- the polygon / triangle budget holds and no object has more than 64 construction rays (by the generator's count and by
  castplane's);
- `display_color` is on every object, equals the dominant material colour (by face area), and does not change the
  core's output;
- the GLB and the OBJ import with `castplane import`;
- the stats table's object column lines up with long ids;
- Reiya's own promises: the soles stand on `z = 0`; `rig.stated_height` is 1.52 and sets `rig.figure_scale`; the skin
  head's top is the final skull top (`rig.final_height`) within 0.1 mm; the scene camera is the sheet camera scaled and
  rounded; and a `stated_height` override rescales (at the sheet's own height the scale is 1);
- the numbers the documents quote are the built ones (`DOC_QUOTES` in the test lists which document quotes which of
  the parts, shells, vertices, polygons, triangles, triangles left, maximum ray count, four file sizes, KiB of the
  scene file and SVG characters), and so is the number of tests quoted for this file (final review FR-2: a
  regeneration that changes a number fails there until the documents follow).

Object lists and counts come from `reiya_model.assemble`, so the tests need no edit when an object changes; only a
document that starts or stops quoting a number needs a `DOC_QUOTES` edit.
`tests/test_ts_port.py` renders every example (now ten) with the TypeScript port and compares it with Python.

Gates after a change to the generator:
- `--check` (it rewrites the four files) and the tests above, and `tests/test_charmodel_overlay.py` (it uses her
  overlay data); then the overlay check, if the change touches her shape (the criteria above);
- the same files from Python 3.10 with numpy 2.2 and with `OPENBLAS_CORETYPE=Haswell`: the bytes must be identical (the
  generator keeps its branches off the last bit of a float reduction, rule 9);
- `castplane render examples/reiya.json -o out`: `warnings: []`, about 5 to 7 s in the container of the last run (Miki's
  takes the same);
- `node tools/web_frame_bench.mjs examples/miki.json 5` and `... examples/reiya.json 5`, alternately, three times each,
  in the same container (the figures of the finishing pass are in "The finishing pass" above: Reiya's still frame
  2.7 to 2.9 s, Miki's 2.9 to 3.5 s, in the finishing pass's container; the 1.4 s of Miki's README is from an earlier
  container). The figures move with the container and its load, so only the comparison counts: Reiya's still frame
  must be no slower than Miki's, and the drag frame must stay under the 120 ms target of `tools/web_frame_bench.mjs`.

Then update the counts and object lists that `examples/README.md`, `docs/USAGE.md`, `README.md`, `web/README.md`,
`CHANGELOG.md`, `docs/ARCHITECTURE.md` §5.4, the Reiya line of `.claude/skills/character-model/SKILL.md` and SPEC.md §G
quote (objects, parts, shells, vertices, polygons, triangles, file sizes, SVG characters). `tests/test_reiya_model.py`
fails on a stale count or size (`test_docs_quote_the_counts_of_the_built_model` names the document and the number), but
not on the object lists, so check those by hand. Commit the generator change together with the regenerated files.

The budget is 6500 polygons and 10600 triangles (now 6354 and 10576; the limits were 6000 and 10000 until the finishing
pass and 6500 / 10500 until the user's decision of 2026-11-01, see above) and a scene file of at most 700 KiB (255.7 KiB
now); the room left is small (24 triangles), so spend polygons where a silhouette needs them.

## Known limits

`SPEC.md` Decision 29 lists what stays open after the review rounds (each is a minor finding, recorded so that later
rounds do not rediscover it). They are:
- the cardigan's back boat band reads as a rectangular shelf behind the shoulder in side and 3/4-back views (filling the
  balloon's back pokes it through the panel's back, and a boxier panel back folds the faceted panel: a fix needs more
  panel columns at the back corners), and the front hem corners drop steeply and read as a hook in 3/4 and low views;
- the far ear tuft is seen edge-on as a post from the scene camera and the in-light cameras (bowing its section would
  widen the front view's straight inner edge, the defining feature);
- the fringe locks' roots step out of the dome in shaded views (it needs an extra station and per-lock root heights);
- there is no chin line in low views (castplane draws no line between objects, and a keel group draws a lens), from
  knee height the lavender under-locks float under the chin, and from below the bob's own back edges still draw single
  lines behind the neck;
- a double stroke at the far temple and a dashed jaw outline in `head_three_quarter`, and a shaded bite at the curtain's
  top-front corner;
- the sleeve cap's boundary under the front band's outer edge is not inked in elevated side-front close-ups.

(The row of straight teeth along the bob's lower edge, an item of the earlier list, is resolved by the finishing pass.)

### Open after the finishing pass

Of the 41 overlay criteria 36 pass, M5 is n/a and these 4 fail, all P2 (the values of the last run, `report.md`); M2,
the one P1 that failed after the finishing pass, passes since the leaf pass:
- **M2 (P1), resolved in the leaf pass:** seen obliquely, each layered lock end with straight edges projected to a
  corner of 20-58 degrees (95 % of the bob's visible outline turns were 45 degrees). The lock ends are now leaf-shaped
  (SPEC.md §C.3 "Leaf-shaped lock ends"): inserted lock columns (`rig.bob_leaf_columns`, stable positions between the
  table's columns, whose indices stay) put the back locks' lower edges on the sheet's convex curves, the back step
  lock's tip closes to one vertex (`hair.BOB_CLOSED_TIPS`), the side lock's front corner is an arc and its back corner
  a point. 95 % of the turns were then at most 13.8 degrees; +196 triangles. **The V4 pass** (2026-11-01, the user's
  "remove the fold sliver and widen the M2 margin") removed the leaf pass's last fold loop, a 5 px back-facing sliver
  at the back slit's end in both 3/4 views, and widened the margin: 95 % of the turns are at most 11.3 / 11.8 / 11.8
  degrees (the largest 13.7). The two columns beside the back slit (13.66, 14.51) are now of the kind `"backc"`
  (`(after, frac, "backc", a, z_bottom, phi_top)`): they lie on the contour itself, where the 3/4 cameras graze the
  lock, instead of on the chord between their neighbours, and do not curl in at the tip (`hair.BOB_LEAF_NO_CURL`).
  The strip joining the bell to the lock zone zips by the shorter diagonal (`hair._zip_param`; the old rule put a fan
  triangle's apex outside its base: M3 23.6 -> 19.7 degrees), the side lock's front arc has explicit angle steps
  (`hair.BOB_SIDE_CORNER_STEPS`, 19 mm) and the front slit's V closes on one vertex; -16 triangles.
- **H11 (P2), front hair IoU 0.7961 against 0.80:** the sheet's fringe and the interior of its strand lines.
- **S4 (P2), 23.5 mm against 8:** the sleeve's inner edge beside the skirt in the back view, on her right. The sheet
  draws its two sleeves 22 mm apart (SPEC.md Decision 27), and the model is symmetric.
- **M10 and M11 (P2), 32.5 and 33.6 degrees against 30 and 25:** the dome's facets at its crown. `hair.DOME_SMOOTH =
  True` passes both, for +161 polygons / +358 triangles, which does not fit 10600 (the model has 24 triangles left);
  it needs a larger budget, so it is off.
- **The bob's three-shell cut** (`hair.BOB_SPLIT_STRAND = 15`) departs from the rule that a split must not overlap the
  shadows, and its inner edge draws a new line from below (see above). It is what keeps the web still frame faster than
  Miki's; the user kept it on 2026-11-01. `BOB_SPLIT_STRAND = None` undoes it (see above for what else to change).
- **The budget** 6500 / 10600 (`assemble.BUDGET`) is the user's decision of 2026-11-01 (SPEC.md Decision 32); the web
  figures behind it are container-dependent: the finishing pass's were measured before the leaf pass's +196 triangles,
  and the re-measurement after the leaf pass and the V4 pass is above. The 64 construction rays per
  object (at most 51 now, `top`) and 700 KiB stay hard limits.

Not in Decision 29 but in SPEC.md's self-consistency section ("Decals on the final model"): a few decal layers measure
under the 0.5 mm of rule 5 on the final model, by the nearest-distance or facet metric. The lowest are the highlights'
0.381 mm where a highlight's border passes over the pupil's chord facets (`head.DecalStack` measures the layer below
on its own grid and not on the triangles that are written), the blush strokes' 0.478 mm, the tuft inner faces' 0.483 mm
and the penny slot's step at 0.413 to 0.507 mm; the section gives every layer's measured minimum.

An OBJ or GLB imported with `castplane import` does not meet rules 3 and 7 of the Miki guide (a GLB has no smooth groups
and an OBJ imports as one object), so it renders with `MESH_*` warnings and slowly (the GLB: 14 objects over the ray
cap; the OBJ, one object: over the cap and `MESH_WINDING_FIXED`); only `examples/reiya.json` has to render with
`warnings: []`. The pane draws the line drawing without colour by design (colour shows with "3D view" ticked or in the
observer pane), and the `labels` layer labels every mesh vertex, which is why the docs tell users to untick it.
