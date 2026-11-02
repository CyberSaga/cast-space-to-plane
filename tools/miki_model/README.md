# tools/miki_model: maintainer guide

> **Copyright notice:** Hanabishi Miki (*Hayate the Combat Butler*) belongs to her rights holders. This model is an unofficial fan-made drawing reference, and the character and her model are **not included in this project's authorized distribution and dissemination** (the GPL-3.0 licence covers the castplane software only). See [`COPYRIGHT_NOTICE.md`](../../COPYRIGHT_NOTICE.md).

This package generates the 花菱美希 (Hanabishi Miki) drawing-reference model: `examples/miki.json` (the castplane
scene, 18 inline `mesh` objects) and `examples/meshes/miki.{obj,mtl,glb}` (the same model for other 3D software). It is
a development tool outside the castplane core. The geometry modules import numpy and the standard library only;
the previews also use Pillow and cairosvg (both in the `dev` extra). The four generated files are never edited by
hand: change the generator and regenerate. `tests/test_miki_model.py` compares them byte for byte.

The user-facing description of the scene is in `examples/README.md`, the command line in `docs/USAGE.md` (section 5),
and the contract note in `docs/ARCHITECTURE.md` (§5.4 implementation notes). The character spec is
[`SPEC.md`](SPEC.md): it was written before modelling and the model was then refined in review rounds, so where
it and `rig.py` or a builder disagree, the code wins. Comments in the code cite it as `SPEC.md §X`; a bare "spec §N"
elsewhere in the repository means `docs/spec/spec-v0.1.md`.

## Layout

| file | what it holds |
| --- | --- |
| `../make_miki_model.py` | the CLI: build, validate, write the four files, optional previews and checks |
| `rig.py` | `Rig`, a frozen dataclass: every proportion, landmark and pose number, with the SPEC.md section in its comment; `SUN_TOWARDS` |
| `meshkit.py` | `Mesh`, `Part`, the closed-shell builders, `validate`, `fix_nesting`, `feature_silhouette_vertices` |
| `mannequin.py` | simple placeholder parts for every region (what `--context` draws in grey) |
| `head.py`, `hair.py`, `body.py`, `limbs.py` | the detailed parts; each has `REGIONS` and `build(rig)` |
| `assemble.py` | parts to castplane objects (`OBJECTS`, `MATERIALS`, `assemble`, statistics, `BUDGET`) |
| `export.py` | the scene JSON (`SCENE_SETTINGS`, `DESCRIPTION`), the OBJ + MTL and the GLB writers |
| `preview.py` | shaded colour renders, castplane line renders, contact sheets, the camera presets |
| `checks.py`, `acceptance.py` | the clearance and proportion checks and the acceptance profile they evaluate (see "Checks") |

Regions per module: `head.py` has `head`, `eyes`, `face_marks`; `hair.py` has `hair`, `headband`; `body.py` has
`neck`, `torso`, `collar`, `scarf`, `skirt`; `limbs.py` has `arms`, `hands`, `legs`, `socks`, `shoes`. A module whose
`build(rig)` returns `None` is replaced by `mannequin.py` for its regions (all four are written now).

## The part, object and material model

A **part** is one named piece: `Part(name, material, mesh, region="", *, obj="")` (`meshkit.Part`).
- `name` is unique in the whole model and carries the module as a prefix (`hair.sidelock_l`).
- `material` is the part's **colour**, a key of `assemble.MATERIALS` (13 of them: `hair`, `skin`, `eye_white`,
  `iris`, `pupil`, `headband`, `scarf`, `socks`, `uniform`, `skirt`, `collar`, `face_marks`, `shoes`). The pink stripes
  use `uniform` and the white cuff stripes, ring and dickey use `collar`. Colours are used by the OBJ / MTL / GLB
  and by the shaded previews.
- `obj` is the castplane **object** the part is merged into, one of `assemble.OBJECT_IDS`. Left empty it is
  `assemble.REGION_OBJECTS[region]`; set it where that default is wrong or missing (sidelocks, back hair, the ring,
  both arms).
- `region` is one of the module's `REGIONS`; `--only` filters by it. A part without a region must set `obj`.

An **object** is what castplane sees: a spatially compact group of parts. The groups are small on purpose, because
castplane's hidden-line pass tests a sample only against objects whose image rectangle contains it, and the cap of
64 construction rays (below) is counted per object. The order is fixed (`assemble.OBJECTS`), and **the headband is
first**: the web UI's observer pane draws its sight rays for every vertex of `objects[0]`, and the headband's 120
vertices show its perspective without hiding the figure. Each object also carries a `display_color` (the colour of
its dominant material, `assemble.DISPLAY_MATERIALS`), which only the web UI's 3D views read; the core ignores it.
Every object has `"group": "miki"` (`export.GROUP`, D84), so a click in the web UI selects the whole figure and a
second click the part.

**Linked parts (D85).** Each object also carries the web-only keys `parent` (the id of the object it hangs from;
left out on the root) and `joint` (the point it turns about, `[x, y, z]` in the object's local frame), which the
core ignores. In the web UI a rotation of a part carries its descendants about its joint, so the hair stays on the
head and the socks and shoes on the legs. `assemble.PARENTS` holds the tree (in `OBJECTS` order, exactly one
`None`) and `assemble.part_links(rig)` the joints, read from the rig (`hip_joint`, `knee`, `ankle`,
`shoulder_joint`, `waist_z`, `neck_y` / `neck_z`, `collar_outer`, `ring_center`, `cranium_center`) and rounded to
`DECIMALS`; `export.scene_dict` writes them after `group` (key order `id, type, display_color, group, parent,
joint, data`). The meshes are world coordinates with identity transforms, so a local joint is the world point.
Authoring rules, which the web UI enforces by ignoring a bad link silently:
- a parent must be another object of the same group, and the links must form a tree (a cycle drops every link on
  it); a `joint` without a `parent` is the root's own pivot (the skirt's hip centre);
- put a joint inside its parent's bounding box, where the two pieces meet (shoulder, neck, hip, knee, ankle); a
  piece that only sits on its parent (hair, headband, eyes, face decals) turns about the parent's centre (the
  skull); the tests allow a joint up to 0.12 m outside the part's own box;
- left and right limbs that share one object (`legs`, `socks`, `shoes`) take a midline joint and move together;
  give each side its own object to bend one leg.

| object | parent | joint | | object | parent | joint |
| --- | --- | --- | --- | --- | --- | --- |
| `skirt` | (root) | hip centre | | `hair`, `headband`, `sidelocks`, `back_hair`, `eyes`, `face_marks` | `head` | `cranium_center` |
| `blouse` | `skirt` | `(0, 0, waist_z)` | | `collar` | `blouse` | neck root |
| `legs` | `skirt` | hip centre | | `scarf` | `blouse` | `collar_outer[-1]` (the V tip) |
| `socks` | `legs` | knee centre | | `ring` | `scarf` | `ring_center` |
| `shoes` | `socks` | ankle centre | | `arm_l`, `arm_r` | `blouse` | `shoulder_joint(+1)`, `(-1)` |
| `neck` | `blouse` | neck root `(0, mean(neck_y), neck_z[0])` | | `head` | `neck` | `(0, mean(neck_y), neck_z[1])` |

| # | object | holds |
| --- | --- | --- |
| 0 | `headband` | band, pink centre ridge |
| 1 | `hair` | dome H1, bangs H3, stray strand H5 |
| 2 | `head` | head and face skin |
| 3 | `eyes` | sclera, iris, pupil, highlight (per eye) |
| 4 | `scarf` | ribbons, tips |
| 5 | `sidelocks` | sidelocks H4 (a pair) |
| 6 | `blouse` | the torso / blouse |
| 7 | `collar` | collar, dickey, collar pink stripe |
| 8 | `back_hair` | side curtain and back sheet H2 |
| 9 | `arm_l` | her left sleeve, its 2 cuff white stripes, hand and thumb |
| 10 | `face_marks` | brows, upper-lid bands, lower-lid marks, mouth, nose mark |
| 11 | `arm_r` | the same for her right arm |
| 12 | `legs` | the two legs |
| 13 | `socks` | the two socks |
| 14 | `skirt` | skirt, under-skirt block |
| 15 | `shoes` | the two shoes with their straps |
| 16 | `ring` | scarf ring, its 2 pink stripes |
| 17 | `neck` | neck and décolleté bib |

Currently 58 parts (58 closed shells), 4225 vertices, 4514 polygons and 8242 triangles. To add, split or reorder
objects, change `OBJECTS` and keep `DISPLAY_MATERIALS` and `PARENTS` in the same order (asserts check it), give a
new object its joint in `part_links`, then update the object lists that `export.DESCRIPTION`, `examples/README.md`
and the §5.4 note quote.

A minimal part module:

```python
from . import meshkit as mk
from .meshkit import Part
from .rig import Rig

REGIONS = ("hair", "headband")

def build(rig: Rig):
    bangs = mk.thicken(grid, rig.bangs_thickness, offset="outward", away_from=rig.head_center,
                       groups={"front": 1, "back": 1, "rim": {"v0": 1, "v1": 2, "u0": 1, "u1": 1}})
    return [Part("hair.bangs", "hair", bangs, "hair"),
            Part("hair.sidelock_l", "hair", lock_l, "hair", obj="sidelocks")]
```

When `build` returns a list it replaces **all** of the module's regions, so return every region. `assemble` then rounds
every part to `DECIMALS` (5, i.e. 0.01 mm), validates it, merges the parts per object (keeping each part's face range
and material for the exporters), renumbers smooth groups per part so local ids 1, 2, 3 ... never collide, and
reorders vertices against castplane's nesting-parity flip (`meshkit.fix_nesting`).

### Building blocks (`meshkit`)

Meshes are values: `Mesh(vertices, faces, groups)` with faces counter-clockwise seen from outside and one smooth-group
id per face. Every method returns a new mesh: `translate`, `rotate(axis, deg, origin)`, `scale`, `transform`,
`mirror_x` (flips the winding for you), `flipped`, `with_groups`, `rounded`, `merge`; `n_faces`, `n_triangles`,
`bbox()` and `triangles()` read it. Her left is `+x`: build the left side and mirror.

Every builder returns **one closed, 2-manifold, outward-oriented shell** (oriented by signed volume, so the ring or
grid order you pass does not matter):

| builder | for |
| --- | --- |
| `loft(rings, cap_start, cap_end, periodic_v, groups, cap_groups)` | anything with cross-sections; caps are `'pole'`, `('pole', apex)`, `'flat'`, `('dome', depth[, n])` |
| `sweep(path, width, thickness, profile, normals, up, twist_deg, start, end, groups, cap_groups)` | strands, locks, tips; ends are `'flat'`, `'round'`, `'pointed'` |
| `tube(path, radius, n)` | a round sweep |
| `thicken(grid, thickness, periodic_u, offset, away_from, groups)` | slabs on a surface: bangs, hair sheets, collar, headband, face decals |
| `revolve(profile, n, groups, closed)` | bodies of revolution; `closed=True` with a rectangle profile makes a band |
| `ellipsoid`, `superellipsoid`, `torus` | blobs |
| `strip_plate`, `ridge_band` | plates with a pointed end, thin raised decal bands |

Ring and profile helpers: `ellipse_ring`, `superellipse_ring`, `rounded_rect_ring`, `place_ring`, `profile_ellipse`,
`profile_lens`, `profile_rect`, `resample_polyline`, `resample_closed`. Read the docstrings for the group arguments:
`loft(groups=...)` takes an int, one value per section or a `(sections, M)` array, and `thicken(groups=...)` takes
`{"front", "back", "rim"}` or `"single"`.

## Changing proportions (`rig.py`)

Every number the builders use is a field of `Rig`. Read dimensions from `rig` and add a new dimension as a new named
field with a comment (and the SPEC.md section), not as a literal in a builder. Points are `(x, y, z)` for her left;
`rig.at(p, side)` mirrors them (`side = +1` left, `-1` right). The §A landmark table (`rig.landmarks`) drives the
derived heights (`rig.height`, `chin_z`, `eye_z`, `waist_z`, ...), so editing a row moves them. Surface models such as
`rig.head_surface_y(x, z)`, `rig.head_normal(x, z)`, `rig.blouse_section(z)` and `rig.skirt_section(z)` are what
decals and clothes sit on.

Two ways to change a value:
- edit the default in `rig.py` and regenerate (the way to change the shipped model);
- try it without touching the code: `python3 tools/make_miki_model.py --only head --preview /tmp/p --rig mine.json`,
  where the file is a JSON object of `Rig` fields (`Rig.from_dict`: unknown keys raise, lists become tuples). In
  Python, `Rig().replace(...)` does the same.

Some fields are inert: `rig.SPEC_ONLY_FIELDS` are SPEC.md values that no builder reads (the shapes come from module
constants such as `hair.BACK_GROOVE_DEPTH` or from `limbs.py`), and `rig.MANNEQUIN_ONLY_FIELDS` are read only by the
grey `--context` parts. `Rig.from_dict` warns when you override one. A change of proportions can break the rules
below (a decal sunk into the skin, a count over a cap), so run `--check` after it.

## Previewing

```sh
python3 tools/make_miki_model.py --only hair headband --context --preview /tmp/p     # your regions in colour, the rest grey
python3 tools/make_miki_model.py --only hair --lines /tmp/l --lines-views head_front head_side --lines-layers objects
python3 tools/make_miki_model.py --check --preview /tmp/p --lines /tmp/l              # the full model, checked
```

| option | what it does |
| --- | --- |
| `--out-dir DIR` | write `miki.json` and `meshes/miki.{obj,mtl,glb}` there (default: the repository's `examples/`) |
| `--only REGION...` | build only some regions or modules (`head`, `hair`, `body`, `limbs` or any region name); writes no model files unless `--out-dir` is also given |
| `--context` | with `--only`: draw the other regions as grey mannequin parts in the shaded previews |
| `--preview DIR` | shaded renders (a numpy z-buffer; each part in its material colour; visible back faces are **magenta**, which means an inverted or open shell): `shaded_body.png`, `shaded_head.png` and `shaded_<preset>.png` |
| `--lines DIR` | the real castplane line drawing per view: `lines_<preset>.svg` / `.png`, `lines_sheet.png` and `lines_warnings.txt` (the sheet caption says `[warnings]` for a view that has any) |
| `--lines-views PRESET...` | presets for `--lines` (default: all) |
| `--lines-layers LAYER...` | SVG layers for `--lines` (`objects` = lines only, no shadow fills) |
| `--no-hidden` | `--lines` without hidden-line removal (faster) |
| `--check` | castplane validate and render of the scene camera (warnings must be `[]`) and the statistics table |
| `--no-strict` | keep going after an invalid part, so you can still look at the previews |
| `--rig FILE.json` | rig overrides |

Presets (`preview.PRESETS`): body `front`, `back`, `left` (camera on her left, `+x`), `right`,
`three_quarter_left`, `three_quarter_right`, `three_quarter_back`, `top`, `low_angle`; head `head_front`,
`head_three_quarter`, `head_side` (her right profile), `head_low`. From Python, `preview.camera_for(preset, rig)`
gives the castplane camera dict, `preview.render_shaded(parts, camera, size)` returns an image, and
`preview.castplane_views(scene, presets)` renders the line drawing; `assemble.assemble(rig, only=..., strict=False)`
and `assemble.format_stats(model.stats)` give the statistics table. Exit status of the CLI: 0 on success, 1 when the
model is invalid, over a budget or the castplane check reports warnings, 2 on a usage error.

## Rules a part must obey

These are castplane's mesh rules (contract §5.2) and what the generator adds on top. `--check` and
`tests/test_miki_model.py` enforce them; `meshkit.validate(mesh, name, strict=True)` checks one part.

1. **Closed 2-manifold outward shells.** Each undirected edge is in exactly two faces and used once in each
   direction, and the signed volume is positive. Use the builders and do not assemble shells from open pieces.
   Also: no face of area <= 1e-10 m², no folded (bow-tie) face, no unused vertex.
2. **No vertex below z = 0.** Soles exactly on z = 0 are fine (contact tolerance `max(tol, weld_tolerance)`); a
   vertex below raises `OBJECT_BELOW_RECEIVER`.
3. **Smooth groups make the drawn lines.** castplane draws an edge between two faces of the same non-zero group
   only where it is a camera silhouette, an edge between different groups always (a feature line), and for group 0
   an edge wherever the dihedral angle is above 30°. So give each smooth patch its own group and put a group
   boundary exactly where a line should be drawn (the bang cut, headband edges, collar edges, hems, shoe outlines,
   eye outlines); never leave a tessellation edge inside a patch as a feature. SPEC.md §F is the lines plan.
4. **Coplanar faces merge whatever their groups.** castplane merges adjacent faces within 1e-3 rad (0.057°) of
   coplanar before drawing, so a group boundary between flat faces disappears. Give the surface a real crease of at
   least 1°, or make a colour stripe a separate thin raised shell.
5. **Decals stand >= 0.5 mm proud.** A hidden-line sample is hidden when an occluder is hit before the sample
   (ray parameter `t < 1 - 1e-5`, about 0.04 mm at 4 m), so a decal (eye layers, brows, mouth, stripes) must stand at
   least 0.5 mm proud of the surface it sits on, or its outline is eaten by the surface. Their bottoms may sink into
   the surface below. The `*_relief` fields of `Rig` are 0.6 to 1.6 mm, and `head.py` keeps a clearance floor
   (`decal_skin_clearance`, `decal_layer_clearance`) against the faceted skin between vertices. Colour stripes are
   separate bands that float `stripe_float` above the surface, so both borders draw as silhouettes.
6. **No near-duplicate vertices across the shells of one object.** castplane welds vertices closer than
   `weld_tolerance` (1e-6 m) per object, across shells too, and two shells that share or nearly share a vertex
   would fuse into a non-manifold mesh (`MESH_NON_MANIFOLD`, a per-face fallback, bad shadows). `validate` rejects
   two vertices closer than 1e-5 m within an object. Coordinates are rounded to 0.01 mm, so keep vertex spacing
   >= 0.05 mm; tips are the risky spots. Overlapping shells are fine (`fix_nesting` handles the vertex order), but a
   shell completely buried inside another shell of the same object is an error: delete it.
7. **At most 64 feature silhouette vertices per object.** castplane draws construction rays for the vertices of
   feature edges that lie on the light silhouette (between a lit and an unlit face) and warns `MESH_RAYS_CAPPED`
   above 64 per object. The light is `rig.SUN_TOWARDS`. The usual offenders are slab rims with their own group, flat
   caps that face away from the sun, pleat creases and a hem cap with its own group. Check a part with
   `len(mk.feature_silhouette_vertices(part.mesh, SUN_TOWARDS))`; `--check` prints a `rays` column per part and per
   object and fails when an object is over (`OVER`). If an object is too crowded, split it into another compact
   object instead of deleting designed lines. Prefer `thicken(groups="single")` slabs, whose borders draw only as
   silhouettes and cost no rays, and give a rim its own group only where the line must show.
8. **Budget.** At most 6000 polygons and 10000 triangles in total (`assemble.BUDGET`, polygons = faces as written,
   triangles = castplane's fan triangulation; now 4514 and 8242) and a scene file of at most 700 KiB (190 KiB now).
   Hidden-line time grows with the number of drawn edge samples times the number of triangles, and shrinks when
   objects are compact. `node tools/web_frame_bench.mjs examples/miki.json 5` times the web path (the figures
   depend on the machine, so compare against a baseline measured on the same machine).
   The web port's resting frame (with hidden lines) takes about 1.4 s against a 1.5 s target,
   and the Python CLI renders the scene in about 4 s, so spend polygons where the silhouette needs them and not on
   flat areas. Every mesh vertex also gets a label in the `labels` layer, which is why the web UI asks users to
   untick it.
9. **Deterministic.** Running the generator twice must give byte-identical files: no randomness, no set iteration
   order, no wall-clock values, coordinates rounded to `DECIMALS`. Do not let the last bit of a floating-point
   reduction decide a branch: a Haswell and an AVX-512 BLAS kernel round differently, so `meshkit._below_fan`
   (which picks each quad's fan diagonal) treats near-planar quads with a relative tolerance `PLANAR_REL`. Use
   tolerances or fixed-shape expressions in the same way.
10. **Python 3.10 syntax** (CI runs 3.10 and 3.13): no `type` statements, no PEP 695 generics, no backslash inside an
    f-string expression.

An OBJ or GLB imported with `castplane import` does not meet rules 3 and 7 (a GLB has no smooth groups and an OBJ
imports as one object), so it renders with `MESH_*` warnings; only `examples/miki.json` has to render with
`warnings: []`.

## Checks (clearance and proportions)

`checks.py` turns the questions a review round used to answer by eye (does a part poke through another, is a gap too
small, do the proportions match the tables they were lofted from) into requirements that end PASS, FAIL or
INDETERMINATE. It only reads the model: it builds it with `assemble.assemble` and checks the rounded, exported
geometry of the pre-merge parts (`Assembly.parts`, `assemble.DECIMALS`), never the 18 merged objects and never the
builders' float output. It writes no model file, so `make_miki_model.py --check` stays byte-identical.

```sh
python -m tools.miki_model.checks                        # the gate: exit 0 only if every required check passes
python -m tools.miki_model.checks --report-only          # print everything, always exit 0 (use while modelling)
python -m tools.miki_model.checks --out report.json      # also write the JSON report
```

The review round runs the gate. While modelling, use `--report-only`. The report goes only where `--out` says (the
default is the printed summary); it has sorted keys and is deterministic.

### Verdicts and the exit code

- **PASS**: the requirement was measured and holds.
- **FAIL**: it was measured and does not hold. A FAIL is never widened to pass (see "Adding a requirement").
- **INDETERMINATE**: there is no trustworthy verdict, and it never counts as a pass. The reason is in the report:
  a missing measurement, invalid geometry, a pose that was not tested, a join whose parts never meet where the
  builder says they do, or `tolerance-sensitive` (below).
- A join or clearance that is allowed to have no contact and has none is reported as `NOT_EXERCISED`: it does not
  block the gate and is not counted as a PASS.

Exit status: 0 when every `required` requirement is PASS (or not exercised), 1 otherwise. An `advisory` requirement
is printed and never changes the exit status. `--report-only` always exits 0.

### The three pair relations

Burial is this model's construction idiom (the neck ends inside the torso and the head, the bib inside the neck,
the leg inside the sock, the sidelock roots inside the dome, every decal's back under the skin, the scarf tips' root
rim inside the ring, and the hair tucks: each sidelock over the bangs' outermost strip and end
(`join:hair.bangs~hair.sidelock_{l,r}`, a leak onto the next strip fails) and into the side curtain's front edge
(`join:hair.sidelock_{l,r}~hair.back`, from `hair.CURTAIN_FRONT_Y` back by `hair.CURTAIN_END_THICKNESS`)), so a
generic "no part may intersect another" gate would fail on day one. Every pair of parts, across objects and inside one
object (`collar` merges the collar, the dickey and the stripe), therefore falls under exactly one relation:

- **join**: part A is buried in part B on purpose. The requirement names the buried part, the host, the zone where
  the A/B intersection curve may lie (a z or y range, faces of either part, "inside" or "near" a part) and the depth
  from the builder constant. Every segment of the curve, and every edge of a coincident patch, must lie wholly inside
  the zone (dilated by eps), the buried rim must stay under the host's surface by at least the depth, and no shell
  of either part may lie wholly inside the other without being the declared burial. A segment outside the zone, or
  a rim that surfaces, is a FAIL.
- **clear**: faces of A must clear faces of B by `[min, max]` (collar underside against the bib, straps, decal
  fronts against the skin, the colour stripes). A contact or a coincident patch is a gap of 0, below the minimum.
  A finite maximum is enforced only where a builder places a part a stated distance off its host.
- **everything else** (the generic relation, one requirement per remaining pair): any triangle-triangle crossing,
  coincident patch or containment is a FAIL. A contact within eps is not a penetration; it is counted and located.

### Degenerate intersections

An intersection is not always a clean segment, so each candidate triangle pair is classified by the signed
distances of its vertices to the other triangle's plane, against `eps = max(weld tolerance, sqrt(3)/2 * 10^-DECIMALS)`
(8.7 micrometres, the rounding error of the exported grid):

- **crossing**: the pair yields a segment, however short, so a narrow poke is never dropped by length;
- **contact**: the triangles touch at a vertex or edge within eps (no penetration; a gap of 0 for a `clear`);
- **coincident**: they lie in one plane and overlap by more than eps squared in area (a z-fight, an unstable hidden
  line); it FAILs under the generic relation and `clear`, and passes a join only when the patch is inside the zone.

A verdict must not depend on eps: every join and generic requirement is evaluated at eps/10, eps and 10 eps, and
when the three differ it is INDETERMINATE (`tolerance-sensitive`) with the near-band triangle pairs listed.
Containment (a winding test per shell, both directions) and the buried-rim depth run independently of the segment
classifier, and a FAIL from either stands. Bounding boxes only order and screen the work; a pair the profile names
is always tested.

### The report

The JSON report records the profile and geometry versions, each requirement's measured and required values with
units, the part, the face or vertex indices and the full XYZ of each finding (the worst first, at most 12), the
relation that applied, a table of every intersecting part pair, and a width table every 5 mm for the free-form
parts (hair, skirt), which is diagnostic only: it becomes a gate once a written rule exists. The printed summary
gives the counts per kind, the passes that rely on the facet-bulge allowance, the zones that are exempt or
approximate, and every requirement that is not PASS.

### Accepted as they stand

The close round (profile v3) left every required requirement PASS. These results were reviewed and signed off as
they are, not fixed:
- Five joins pass only through the facet-bulge allowance (the summary lists them with the nominal and the effective
  depth): `body.bib~body.neck`, `body.blouse~body.neck`, `hair.headband~hair.dome` and `hair.sidelock_{l,r}~hair.dome`.
  The rim is the stated depth under the analytic host; the faceted host bulges less far out between its vertices.
- The sidelock root depth is `hair.SIDELOCK_ROOT_INSET` x cos(section normal, dome normal): the builder insets the
  root row's edges along the horizontal section normal, so the perpendicular depth is the smaller cosine of the two
  edges at their own section points (`hair._sidelock_root_edges`, the inner edge turned
  `hair.SIDELOCK_ROOT_INNER_TURN`).
- `limbs.sleeve_{l,r}~body.blouse` and `limbs.thumb_{l,r}~limbs.hand_{l,r}` are zone-exempt: the builders state no
  zone for those burials (the blouse cuts the sleeve over its round cap and down the armpit; the thumb is a lobe
  off the palm base), so the intersection curve is not tested, only containment and the rim (the thumb's base cap).
- The advisory `clear:limbs.strap_{l,r}^limbs.shoe_{l,r}/surface` stays FAIL: its exact-distance metric covers every
  strap face, including the strap's end faces, which physically meet the shoe. The gated rule is the builder's
  border-chord clearance (`clear:limbs.strap_{l,r}^limbs.shoe_{l,r}`), which passes.
- `pose:rest-only` stays INDETERMINATE (advisory) until the named poses are tested (milestone 2).

### Adding a requirement

Requirements live in `acceptance.py` (`Join`, `Clear`, `Proportion`, `Pose`; `profile()` returns them in a fixed
order, and `PROFILE_VERSION` is bumped when one is added, removed or changed).
- Take the numbers from `rig.py` and the builder modules' constants by import (`NECK_BLOUSE_INSET`, `BIB_SINK`,
  `SIDELOCK_ROOT_INSET`, `rig.band_embed`, `COLLAR_BIB_CLEARANCE`, ...), never by copying a value. SPEC.md is not
  the reference: where the code departed from it, the code wins.
- Fill in `constant` (where the number comes from) and `reason` (why it exists). Select faces geometrically with
  `Select`, since a `Part` has no named face groups.
- Calibrating a number to the model as it stands is allowed only when the reason says "accepted in round N" with the
  round cited. Any other miss is reported as FAIL and is fixed in the generator, not in the profile.
- A new join is also how a pair stops being judged by the generic relation: declare it, with its zone and depth,
  rather than excusing the FAIL.

`tests/test_model_checks.py` holds the detector fixtures (synthetic meshes: a crossing that vertex samples miss, a
shell wholly inside another, a contact inside the tolerance, a join that leaks past its zone, a join whose rim
surfaces, a positive gap below the minimum, a pose that was not tested) and pins Miki's verdict set.

## How the files are checked

```sh
python3 tools/make_miki_model.py --check                      # rewrites examples/ and checks the rules above
python -m pytest -q -o addopts="" tests/test_miki_model.py    # about half a minute; builds the model once per run
```

`tests/test_miki_model.py` pins what the shipped files promise:
- the generator reproduces `miki.json` and `meshes/miki.{obj,mtl,glb}` byte for byte, on every build;
- the scene objects are `assemble.OBJECT_IDS` in order, and every object is a closed, consistently oriented
  manifold that castplane takes without mesh preprocessing (no fallback, no `prep_warnings`);
- stage A and the scene-camera render have `warnings == []`, with the default layers `objects` and `cast_shadow`;
- the polygon / triangle budget holds and no object has more than 64 construction rays (by the generator's count
  and by castplane's);
- `display_color` is on every object, equals the dominant material colour, and does not change the core's output;
- `parent` / `joint` (D85) form one tree rooted at the skirt, equal `part_links(Rig())`, put every joint inside its
  parent's bounding box and within 0.12 m of its part's, and do not change the core's output;
- the GLB and the OBJ import with `castplane import` into the same objects.

Object lists come from `miki_model.assemble`, so the tests need no edit when an object changes.

After a change to the generator: run `--check` (it rewrites the four files), run the tests above, and update the
counts and object lists that `examples/README.md`, `docs/USAGE.md`, `README.md` and the §5.4 note quote (objects,
shells, vertices, polygons, triangles). Then commit the generator change together with the regenerated files.
