# Architecture contract (v1 M0–M3 in §1–§4; v2 extensions M4–M8 in §5)

This document is the binding contract between the spec (`docs/spec/spec-v0.1.md`,
sections referenced as §N) and the code. Everything here is normative for the
implementation; where the spec leaves a choice open, the choice is recorded here
and must not be re-decided elsewhere. Decisions that override spec wording are marked **[decision]**.
§1–§4 are the v1 (M0–M3) contract as delivered; §5 holds the v2 extensions (M4–M8) and amends §1–§4 where it says so
(each amended paragraph carries a one-line pointer).

## 1. Package layout

```
castplane/                  pure library, depends only on numpy (stdlib otherwise)
  __init__.py               public API re-exports + __version__
  errors.py                 SceneError (input errors; carries `field` path); warning codes + make_warning()
  homogeneous.py            4-vector / 3-vector helpers: normalize_max, cross3, meet/join of 2D lines, clip helpers, tolerance
  scene.py                  load_scene / validate_scene (JSON -> validated plain dict), defaults, camera forms
  transform.py              euler_zyx_matrix(rotation_deg), apply_transform
  mesh.py                   internal mesh representation + builders for polyhedral primitives (box, prism)
  primitives.py             build_object(obj_dict) -> Object record (mesh + analytic params for curved types)
  light.py                  light_vector(light) -> L (4,), lit(face_normal, p, L), silhouette_edges, silhouette_loops
  shadow.py                 shadow_matrix(plane, L) -> M (4x4), foot(plane, X), shadow loops of polyhedra (incl. unbounded)
  conics.py                 3x3 conic math: circle_matrix, embed_circle (E 4x3), transform_conic (adjugate based), classify, ellipse_params, sample, arcs
  curved.py                 sphere / cylinder / cone: silhouette w.r.t. an arbitrary homogeneous L (light OR camera), terminator, shadow conics
  camera.py                 camera_matrix(cam, canvas) -> {K,R,t,P(3x4),C, forward, near}, project, nu (near functional), clip_segment_near, clip_polygon_near, clip_polygon_rect_h, horizon, vanishing_point
  construction.py           L', F', Q' points, construction rays L'P' and F'Q', self-check intersection S'
  pipeline.py               stage A shadow_geometry(scene) ; stage B project_scene(scene, A, camera=None) ; stage C compose(...) ; render(scene)
  output/__init__.py
  output/geometry_json.py   §6.2 JSON geometry document (deterministic, sorted keys, canonical floats)
  output/svg.py             §6.1 layered SVG written with stdlib string building (NO svgwrite dependency)
  output/png.py             §6.3 rasterize via cairosvg (optional extra), resvg CLI fallback if present on PATH
  cli.py                    `castplane` CLI (argparse): render / validate / stages / info; exit codes 0 ok, 1 I/O,
                            2 invalid input (SceneError with field path / usage), 3 missing optional dependency (PNG)
  hidden.py                 (M4, §5.1.6) sampled hidden-line removal: exact occluders, first_hit, drawn_segment_4d, classify_document
  meshprep.py               (M5, §5.2.3) mesh preprocessing: weld, degenerate faces, adjacency / orientation, coplanar merge, edge classes, fallback mesh
  umbra.py                  (M6, §5.3.4) scanline umbra kernel: tolerances, scan_pieces, record_pieces, umbra_pieces, umbra_from_document
  multilight.py             (M6, §5.3.2–§5.3.3) multi-light assembly helpers (constructions per light, form-shadow core, silhouette_lights)
  output/svg_multilight.py  (M6, §5.3.6) per-light / umbra / core sub-group builders used by output/svg.py
  io/__init__.py            (M5 + M8, §5.0.2) loader registry: EXPANDERS, EXTENSION_LOADERS, expand_scene, load_expanded_scene, load_mesh_file, IMPORT_NOTE_CODES
  io/obj.py io/gltf.py io/trimesh_adapter.py   (M5, §5.2.8) mesh file loaders (trimesh = optional extra `mesh`)
  io/part21.py io/step.py   (M8, §5.5.2–§5.5.7) ISO 10303-21 parser and STEP recognisers; tessellate_step needs the optional extra `step`
  io/cli.py                 (M5 + M8, §5.0.2) the one `castplane import` subcommand (mesh and STEP options)
ts/                         (M7, §5.4) the TypeScript core (ts/src, zero dependencies), node:test suites, ts/bench/camera_only.ts
web/                        (M7, §5.4.10) the vite + three.js web UI (static build)
package.json, package-lock.json   (M7) root npm workspace for ts/ and web/
tests/
  reference/raycast.py      independent ray-casting reference (shares NO code with castplane except reading scene dicts)
  reference/raster.py       nonzero-winding polygon rasterizer for IoU
  reference/random_scenes.py random scene generator (seeded)
  reference/zbuffer.py      (M4, §5.1.11) three-valued per-pixel depth-buffer reference for hidden lines (shares no code with castplane)
  fixtures/meshes/*, fixtures/step/*   (M5, M8) loader fixtures; tests/golden/example_basic.svg (M6)
  test_*.py                 unit / invariant / analytic / degenerate / property / raycast tests
  conformance/cases/*.json  inputs ; conformance/expected/*.json outputs (§6.2 format) ; test_conformance.py ; README.md ; CHANGELOG.md
  conformance/rules.json    (M7, §5.0.8) the comparator constants shared by the Python and TypeScript runners
  test_ts_port.py           (M7) Python-side checks of the files shared with the TypeScript port
tools/regen_conformance.py  regenerates expected files; requires --reason, appends a versioned entry to CHANGELOG.md
                            (+ `--rules-only`, `--strip-new-keys`, §5.0.8); tools/compare_svg.py (M7 dev tool); tools/make_step_fixtures.py (M8, needs OCP)
benchmarks/bench.py         §8 performance targets (benchmarks/README.md records the measured status)
benchmarks/scenes/benchmark_100.json   (M7, §5.4.9) the §8 benchmark scene as a committed scene file (bench.py reads it by default); benchmarks/export_scene.py writes it
examples/*.json             example scenes (the §4 scene is examples/basic.json); examples/README.md
docs/                       spec + this document + user docs: README.md (root), docs/USAGE.md (CLI + API reference),
                            docs/DECISIONS.md (the [decision] list in Traditional Chinese), docs/images/
                            docs/PLAN-v2.md (M4–M8 implementation order), docs/STEP.md (M8 feasibility report)
```

Package name on PyPI/import: `castplane`. CLI entry point: `castplane`.
Python ≥ 3.10. Core runtime dependency: numpy only. Optional extras:
`png` → cairosvg; `dev` → pytest, hypothesis, pillow, cairosvg. v2 (§5): `mesh` → trimesh (M5, STL / PLY only);
`step` → cadquery-ocp (M8, tessellation fallback and fixture generator only). The TypeScript core (`ts/`) has no runtime dependency.

## 2. Conventions (normative)

### 2.0 Validation (`scene.py`) — every rule raises `SceneError(field=<json path>, message)`
*Amended by §5.0.1 (unified v2 rows: `mesh` / `step` object types, `receivers` ≥ 1, `lights` ≥ 1, `output.hidden_lines` / `hidden_style`, reserved ids, loader expansion before validation).*
| field | rule |
| --- | --- |
| `version` | must be `"0.1"` |
| `units` / `up` | must be `"m"` / `"z"` (defaults if absent) |
| `objects` | non-empty list; ids unique, non-empty strings without `.` |
| `objects[i].type` | one of `box, cylinder, sphere, cone, prism` (amended by §5.0.1: + `mesh`; `step` is loader-only) |
| `objects[i].size` (box) | 3 positive numbers |
| `radius`, `height` | positive numbers (cylinder, cone: both; sphere: radius only) |
| `objects[i].polygon` (prism) | ≥ 3 vertices `[x,y]`, non-collinear, simple (no self-intersection); clockwise input is reversed silently |
| `objects[i].transform` | optional; `position` 3 numbers (default `[0,0,0]`); `rotation_deg` 3 numbers (default `[0,0,0]`); `scale` forbidden |
| `lights` | list of length exactly 1 (v1; amended by §5.3.0: non-empty list of any length); ids unique, non-empty strings without `.` (like object ids: `.` is the separator of the §3.1 point-name grammar, `L.<light>`, `<obj>.s<k>.<light>`) |
| `lights[i].type` | `point` (needs `position`, 3 numbers) or `directional` (needs `direction`, 3 numbers, \|d\| = 1 ± 1e-9, points **towards** the light) |
| `receivers` | list of length exactly 1 (v1); `type == "plane"`; `normal` must be `[0,0,1]` and `offset` must be `0` (v1 ground only, §1); \|normal\| = 1 ± 1e-9 (amended by §5.1.1: non-empty list, any plane, optional convex `bounds`) |
| `camera` | `position` 3 numbers; exactly one of `target` (3 numbers, ≠ position) or `yaw_deg`+`pitch_deg`; `roll_deg` default 0; `focal_length_mm > 0`; `frame_mm` 2 positive; `shift_mm` default `[0,0]`; `near_m > 0` default 0.05 |
| `output.canvas_mm` | 2 positive numbers; \|canvas_w/canvas_h − frame_w/frame_h\| ≤ 1e-9 |

**[decision]** The spec's own §4 example (`canvas_mm = [257, 182]` with `frame_mm = [36, 24]`) violates the spec's
own aspect rule (1.412 ≠ 1.5) and is rejected. `examples/basic.json` therefore uses `[273, 182]` (3:2, same height);
users who want JIS B5 paper should set `frame_mm` to a matching aspect (e.g. `[36, 25.5]`) or the canvas to 3:2.
| `output.layers` | **non-empty** subset of the six ids of §2.10 (default when absent: all six, in table order); an empty list is rejected (field `output.layers`), exactly as the CLI rejects an empty `--layers` |
| `output.png_dpi` | positive number, default 300 |

Unknown keys are ignored. `load_scene` returns a new plain dict with all defaults filled in.

### 2.1 Coordinates and units
*Amended by §5.1.2 (receivers are any plane `π = (n, d)` with bounds; the ground stays the only unbounded receiver).*
- World: right-handed, Z up, metres. Ground receiver is `z = 0` → π = (0,0,1,0) (the only v1 receiver).
- Object anchor = centre of the **base** (bottom face / base circle); an object resting on the
  ground has `position[2] == 0`.
- `rotation_deg = [rx, ry, rz]`: Euler angles applied in **Z–Y–X order**, i.e.
  `R = Rz(rz) · Ry(ry) · Rx(rx)` applied to local coordinates (`world = R·local + position`), each `R*` a
  right-handed rotation about that axis.
  Local axes before rotation: box `size=[sx,sy,sz]` spans `[-sx/2,sx/2]×[-sy/2,sy/2]×[0,sz]`;
  cylinder/cone/sphere axis = local +Z; sphere centre at local `(0,0,r)`; prism polygon in local XY
  (counter-clockwise when viewed from +Z), extruded `[0,height]`.
- Homogeneous 4-vectors `X=(x,y,z,w)`; `w=0` = point at infinity (direction). Planes `π=(n,d)` with `n·x + d = 0`.
- **Oriented projective geometry [decision]**: all homogeneous vectors are oriented. Canonical forms are:
  finite points `w=+1`; directions `(d,0)` pointing the way the ray travels; point light `(l,1)`; directional
  light `(l,0)` with `l` towards the light; receiver π with the light on its positive side (`πᵀL > 0`,
  guaranteed by validation + §2.3). `normalize_max` preserves sign. Every sign predicate below assumes
  canonical representatives. Spec §7.1 row 5 (scale invariance) is therefore tested with **positive**
  scalars on all inputs, plus with scalars of either sign on sign-free outputs (image coordinates of finite
  points, conic matrices up to sign).
- Picture (image) plane coordinates `(u,v)` in **canvas mm**, `u` right, `v` up, **origin at the frame centre**.
  The frame is scaled by `s = canvas_mm[0]/frame_mm[0]` so that it fills the canvas; frame-mm = canvas-mm / s.
  The principal point sits at `(u0,v0) = shift_mm · s`; positive `shift_mm[1]` moves the principal point up.
  **[decision]** Spec §2 "原點在主點" and §5.4's K with `(u0,v0)` agree only when shift is 0; we follow the K
  formula literally, draw the principal point marker at `(u0,v0)`, and all `image` coordinates in
  JSON/SVG/tests (and all mm tolerances) are canvas-mm.
- SVG mapping: `x_svg = u + W/2`, `y_svg = H/2 − v`, `viewBox="0 0 W H"`, `width="Wmm" height="Hmm"`.

### 2.2 Camera (§5.4)
- `forward = normalize(target − position)`; `right = normalize(forward × up_world)` with
  `up_world=(0,0,1)` (if |forward × up_world| ≤ 1e-9 use up_world=(0,1,0) and warn `CAMERA_LOOKING_ALONG_UP`);
  `up = right × forward`.
- Roll (ρ = `roll_deg`): `right' = cos ρ · right + sin ρ · up`, `up' = −sin ρ · right + cos ρ · up`.
  Positive roll turns the camera counter-clockwise about `forward` as seen from behind the camera, so the
  rendered picture content appears rotated **clockwise**. Test vector: camera (0,0,1.5)→(0,5,1.5), f=35,
  frame=canvas=(36,24), roll=+10°: world point (0,5,2.5) projects to `u = +35·sin10°·0.2 = 1.2155 mm` (u > 0).
- yaw/pitch form: `forward = (−sin yaw · cos pitch, cos yaw · cos pitch, sin pitch)` (yaw 0 = +Y, positive
  yaw turns left/CCW seen from above; positive pitch looks up), then the same right/up construction and roll.
- Rows of `R` are `(right', up', forward)`; `t = −R·position`. `[R|t]` is 3×4. Depth of a point is the 3rd
  component of `[R|t]·X` (camera-space z, positive in front). `det R = −1` on purpose, so that
  `u` is right, `v` is up and depth is positive forward; nobody may "fix" this.
- `K = [[f·s, 0, u0],[0, f·s, v0],[0,0,1]]` with `f = focal_length_mm`, `s` and `(u0,v0)` from 2.1.
- `P = K·[R|t]` (3×4). `x̃ = P·X`, `(u,v) = (x̃1/x̃3, x̃2/x̃3)`. `x̃3` equals the depth for `w=1` points.
- Near functional on 4-vectors: `ν(X) = forward·(x − C·w) − near·w` (`= x̃3 − near·w`). For `w=1` this is
  `depth ≥ near`; for directions it is `forward·d ≥ 0`.
- **Drawing pipeline for every drawn segment/polygon [decision]**:
  1. near-clip in 4-D homogeneous world coordinates against `ν(X) ≥ 0` (linear interpolation of
     homogeneous coordinates; Sutherland–Hodgman for polygons; segments by the same rule);
  2. multiply by `P` → 2-D homogeneous 3-vectors;
  3. clip against the **extended canvas rectangle** (canvas grown by 25 % on each side) in 2-D homogeneous
     coordinates with the four functionals `u_max·x̃3 − x̃1 ≥ 0`, `x̃1 − u_min·x̃3 ≥ 0`,
     `v_max·x̃3 − x̃2 ≥ 0`, `x̃2 − v_min·x̃3 ≥ 0` (a bounded rectangle contains no point at infinity, so every
     surviving vertex has `x̃3 > 0`);
  4. divide by `x̃3` last.
  Step 3 is mandatory for anything that may contain direction vertices (unbounded shadows, horizon,
  construction rays); for bounded object edges and bounded shadows it may be skipped (SVG overflows harmlessly)
  but must not break if applied.
- Individual points with `ν(X) < 0` are "behind camera": their JSON `image` is `null` and `depth` is given; the
  per-object warning `POINT_BEHIND_CAMERA` is emitted once per object (ids `[object]`). Exceptions: `L` and `F`
  (see §2.7) and vanishing points are never nulled; they are computed by plain division whenever `|x̃3| > tol`.
- Horizon: image line of the receiver's line at infinity = join of the images of two independent
  directions in the plane (`P·(1,0,0,0)` and `P·(0,1,0,0)`); stored as a 2-D homogeneous line `(a,b,c)`
  normalised by max component and as `v_mm` (its `v` at `u=0`, `null` if the line is vertical or at infinity).
  Vanishing points: `P·(d,0)` for `d ∈ {x,y,z}`; JSON gives `[u,v]` or `null` when `|x̃3| ≤ tol`. The horizon
  segment drawn in SVG is the line clipped to the extended canvas rectangle (step 3 above).

### 2.3 Light, plane projection, feet (spec §5.1–5.3) — use these exact function names
*Amended by §5.1.2–§5.1.3 (per-(light, receiver) light side, `RECEIVER_UNLIT`, silent clip and bounds clip for bounded receivers, plates as casters) and §5.2.5 (per-face fallback for non-manifold meshes).*
- `light_vector(light) -> L` : point → `(x,y,z,1)`; directional → `(dx,dy,dz,0)`.
- `lit(n_f, p, L) -> bool` : `n_f·(l − w·p) > tol_lit`; the band `|…| ≤ tol_lit` is "parallel" → not lit and
  warning `FACE_PARALLEL_TO_LIGHT` (spec §5.7 row 6).
- `shadow_matrix(pi, L) -> M` : `M = (πᵀL)·I₄ − L·πᵀ` ; `S = M·P`.
- `foot(pi, X) -> Q` : `Q = (n·n)·X − (n·x + w·d)·(n,0)`; works for `L` too (gives `F`).
- Light side: if `πᵀL ≤ tol` for a point light → `LIGHT_BELOW_RECEIVER`, no shadows for that light (outlines
  and construction rays omitted, `shadows` entries have empty outlines). For a directional light `|n·l| ≤ tol_dir`
  → `DIRECTIONAL_HORIZONTAL` (no shadows, `F` at infinity and `shadow_vp` on the horizon is still reported);
  `n·l < −tol_dir` → `LIGHT_BELOW_RECEIVER`.
- With canonical inputs `w_S = πᵀL·w_P − w_L·πᵀP` (for the ground: `l_z − p_z` for a point light, `l_z` for a
  directional one). `w_S ≤ tol` ⇒ vertex not below the light (spec §5.7 row 4) → `VERTEX_NOT_BELOW_LIGHT`
  (ids `[object]`), and the shadow outline becomes unbounded (§2.5).
- Vertices with `πᵀP < −tol` (below the ground) → `OBJECT_BELOW_RECEIVER` (ids `[object]`). Before shadowing,
  the object's **mesh is cut by the receiver plane** (`shadow.clip_mesh_to_plane`; the cut face becomes part of the
  solid and its lit-side edges become silhouette edges), so the drawn shadow is exactly that of the part above the
  ground. Ground-crossing vertices are named `<obj>.s<k>.<light>` in order of first appearance; they are their own
  shadow and foot and get no construction ray. Clipping the loop edge-by-edge to `πᵀX ≥ 0` is only the fallback when
  the cut surface is not a closed manifold.
- **Buried curved objects [decision]** (`curved._ground_chain`): the `OBJECT_BELOW_RECEIVER` predicate is evaluated on
  the exact surface (`curved.plane_min`: lowest point of the sphere / rim circles / apex), never on the approximate mesh.
  The part of the silhouette loop below the receiver is removed exactly like the Sutherland–Hodgman clip above, and each
  removed part is replaced by the **lit boundary of the object's ground cross-section** between the exit and the entry
  crossing (the counter-clockwise boundary path of the convex cross-section, i.e. the part adjacent to the lit lateral
  surface), **not** by a straight chord: the cut face is unlit, so its lit-side boundary is a silhouette edge and the
  drawn shadow is exactly that of the part above the ground (footprint included, §7.3). The chain is emitted as ground
  `segment` pieces (`which == "ground"`) between sampled points of the cross-section curve (64 per full turn of the
  base-circle parameter), so it is a polyline in `loops` / `polygons` and does **not** appear in `shadows[].conics`.
  The straight chord remains the fallback when the cross-section is degenerate (no area) or when no cross-section point
  is on the lit side (a lit cap chord, which the chord reproduces exactly).

### 2.4 Mesh representation (also the M5 future mesh format)
*Amended by §5.2.3 (the `mesh` object type: `edge_smooth`, `triangles`, `fallback` on the record) and §5.1.2 (`obj["clipped"][receiver]`).*
```
vertices : (n,3) float64 world coords
edges    : (m,2) int  vertex indices, each edge once, i<j
faces    : list of int lists (CCW seen from outside), planar
face_normals : (k,3) outward unit normals
edge_faces : (m,2) int  the two faces adjacent to each edge (closed manifold ⇒ always 2)
vertex_names : ["v0", "v1", ...]   (names are "<object id>.v<k>")
edge_flipped : (m,2) bool  DERIVED, optional: whether each edge runs against the orientation of its two faces
```
Derived tables that `build_object` adds to the object record and that the batched stage B / C read directly
(they are a **required** part of the stage-A object record, not optional caches; only `edge_flipped` and the
`S_lists` / `Q_lists` / `G_lists` / `G_world` caches of a shadow record are optional and rebuilt when absent):
`face_first`, `faces_padded`, `face_lens`, `face_point_names` (padded face index tables, `primitives.face_tables`),
`edge_templates` and `world_lists` (camera-free §3.1 record templates built once by stage A and shared by reference
with every document composed from it), plus per light `form_idx` / `form_lens` / `form_faces` (the unlit faces).
The record also keeps `frame = (R, position)` and `shape` (the validated `objects[i]` dict) for the exact
point-in-solid test of §2.5 (`primitives.point_inside_solid`).
Builders: `box_mesh(size)`, `prism_mesh(polygon, height)`; cylinder/cone/sphere also produce a mesh
(caps as n-gons / lateral quads, sphere as UV-sphere, 32 segments) ONLY for bounding boxes / scene scale and
the M5-shaped representation; their shadows and outlines are computed analytically (§5.6), never from that mesh.
Curved objects carry `analytic = {kind, base (b), axis (a), e1, e2, radius, height, centre}` in world coords,
where `(e1, e2, a)` is the rotated local frame.

### 2.5 Shadow outlines of polyhedra (spec §5.1, §5.7)
*Amended by §5.1.2 ("counter-clockwise in ground `(x, y)`" reads "counter-clockwise about `n`" in the receiver frame; the ground keeps the literal v2 code) and §5.1.3.3 (bounds clip, anchor rule).*
- Silhouette edges: edges whose two adjacent faces have different `lit`. `silhouette_loops` walks
  them into closed loops oriented with the **lit face on the left** when seen from the light; under `M` such a
  loop maps to a polygon that is **counter-clockwise in ground `(x,y)`** (verified), and the shadow region is
  on its left.
- Each loop → list of homogeneous shadow points `S_i = M·P_i` (after the ground clip of §2.3). Edges whose
  both endpoints have `w_S ≤ tol` are dropped. An edge from `S_a` (`w_a > tol`) to `S_b` (`w_b ≤ tol`) is
  replaced by the **direction vertex** `D = (1−t*)·S_a + t*·S_b` with `t* = w_a/(w_a − w_b)` (so `w_D = 0`);
  with canonical inputs `+D` is automatically the outgoing direction of the shadow ray
  (`S(t)/w(t) → +∞·D` as `t → t*⁻`). The reverse edge (`w_a ≤ tol`, `w_b > tol`) gives the incoming direction
  the same way.
- **Arc at infinity [decision]**: between an outgoing direction `D_out` and the next incoming direction `D_in`
  the region spans the arc of directions swept **counter-clockwise (in ground `(x,y)`) from `D_out` to `D_in`**,
  `Δθ ∈ (0, 2π]` (`Δθ = 2π` when they coincide). Because homogeneous interpolation of a `(D1,0)→(D2,0)` edge only
  covers the shorter arc, intermediate direction vertices are inserted so that every at-infinity sub-edge spans
  `< 90°` (use `ceil(Δθ / 60°)` equal steps). A loop with all vertices at `w ≤ tol` yields no shadow.
- The result is an oriented homogeneous polygon in the ground plane; `unbounded=true` when it contains any
  `w=0` vertex. It goes through the full drawing pipeline of §2.2 (near clip → `P` → homogeneous rectangle
  clip → divide). Bounded outlines may skip the rectangle clip.
- Fill rule for cast shadows is `nonzero` (needed for concave prisms, whose silhouette can be several loops).
- A **point light strictly inside a polyhedron** (box / prism; `primitives.point_inside_solid`: the light mapped into
  the object's local frame lies inside the §2.1 local extents by more than `tol`, exact also for concave prisms and
  rotated objects) lights nothing: every face counts as unlit (all faces go to `form_shadow`, no
  `FACE_PARALLEL_TO_LIGHT`), there are no silhouette edges, the shadow record is empty (`outline`, `loops`,
  `polygons` empty, `unbounded=false`) and no construction points / rays exist; the warning is
  `LIGHT_INSIDE_OBJECT` (ids `[object]`) with a message naming the kind, the same code as for the curved kinds
  of §2.6. A point light exactly on the surface (within `tol`) is outside: the touching face is "parallel"
  (spec §5.7 row 6) and the ordinary path applies.

### 2.6 Curved primitives (spec §5.6)
*Amended by §5.1.4 (per-receiver curved records, closed-form bounds clip of conic pieces) and §5.1.6.5 (sampling site (c): the stage-C conic polyline is reused for hidden-line runs).*
- Circle in its own plane: `C = diag(1,1,−ρ²)` in local coordinates `(x,y,1)`; embedding
  `E = [e1 e2 c ; 0 0 1]` (4×3) with `e1,e2` an orthonormal basis of the plane and `c` the centre.
  Circle frame for silhouette circles (sphere): `e1 = normalize(n × z)`, `e2 = n × e1`; when `|n × z| ≤ 1e-9`
  (light along world z) the fallback is `n × e1_obj`, then `n × e2_obj`, the sphere's **rotated local axes**
  (`conics.circle_frame(n, fallback=(e1, e2))`), so that the sampled outline rotates with the scene (§7.1 row 4);
  for an unrotated sphere this is exactly `n × x`. Cap circles of cylinders/cones use the object's rotated local `(e1, e2)`.
- Any 3×3 projective map `H` of the circle gives conic `C' = adj(H)ᵀ · C · adj(H)` (adjugate, so singular `H`
  does not raise; classify as `degenerate` and emit `CONIC_SAMPLED`). Ground shadow conic uses `H = P·M·E`;
  image of a circle (outline / terminator / end caps) uses `H = P·E`. Conic matrices are normalised by their
  max-|entry| (made +1) before output. Classification must be translation-invariant **[decision]**: let `A` be the
  upper-left 2×2 block normalised by its own max-|entry|; `kind` = ellipse / hyperbola by the sign of `det A`,
  parabola when `|det A| ≤ 1e-12`. Degeneracy and conditioning are judged on the conic translated to its centre
  (`C_c = Tᵀ C T`, `T = [[I, centre],[0,1]]`, centre = `−A⁻¹·(C[0:2,2])` when `A` is invertible; a parabola is
  translated to its vertex instead) and then max-normalised: `|det C_c| ≤ 1e-12` → degenerate; condition number of `C_c`
  `> 1e8` → `CONIC_SAMPLED` (§11.3). A 0.3 m circle 50 m from the origin must classify as a healthy ellipse.
- The **same** silhouette routine serves the light and the camera: `curved.silhouette(obj, L)` with `L`
  the light vector OR the camera position `(C,1)`. Camera outline = that silhouette; terminator = the
  light silhouette (drawn in the image, not on the ground); cast shadow = the light silhouette mapped by `M`.
- Sphere: silhouette circle centre `c + (r²/|v|²)·v`, radius `r·√(1 − r²/|v|²)`, normal `v/|v|`
  with `v = l − c` (point); directional: great circle through `c`, normal `l`. Light inside the sphere (`|v| ≤ r`) →
  warning `LIGHT_INSIDE_OBJECT`, no shadow. A point light inside a cylinder / cone (lateral surface wholly unlit and
  no lit cap) gives the same code with a message naming the kind ("inside the cylinder" / "inside the cone").
- Caps of cylinders / cones are faces for spec §5.7 row 6: `|n·(l − w·p)| ≤ tol_lit` for the base (normal `−a`) or the
  top (normal `+a`, cylinder only) cap → `FACE_PARALLEL_TO_LIGHT` (ids `[object]`), the cap counts as unlit
  (`curved._cap_parallel`).
- Cylinder (base `b`, axis `a`, radius `r`, height `h`, frame `e1,e2`): `q = l − w·b`, `q_⊥ = q − (q·a)·a`,
  `θ_l = atan2(q_⊥·e2, q_⊥·e1)`, `d = |q_⊥|`. Lit angular interval of the lateral surface is centred on `θ_l`
  with half-width `α = acos(r/d)` for a point light (`d ≤ r + tol` ⇒ nothing lit), `α = π/2` for a directional
  light (`d ≤ tol` ⇒ nothing lit). The test `u_θ·(l − w·p) > 0` is independent of the position along the
  generator because `u_θ ⊥ a` (verified). Generators at `θ_l ± α` are both the terminator and the silhouette
  ("tangent generators"). Caps: top normal `+a`, base normal `−a`, each tested with `lit` at its centre.
  Silhouette arcs: parts of the cap circles where cap-lit ≠ lateral-lit. Loop = base arc + generator + top arc +
  generator (or a full cap circle when the lateral surface is wholly lit/unlit, or nothing).
- Cone (base `b`, apex `v = b + h·a`): lateral normal along the generator at angle θ is
  `n_θ ∝ h·u_θ + r·a`; `n_θ·g = 0` so `lit` is constant along each generator and
  `lit(θ) ⇔ h·(q_⊥·u_θ) + r·(q·a) > 0`, `q = l − w·v`, `q_⊥ = q − (q·a)·a` (note `(l − w·v)_⊥ = (l − w·b)_⊥`, so
  `θ_l` is the same as for the cylinder). Lit interval centred on `θ_l` with `α = acos(−r·(q·a)/(h·|q_⊥|))`
  (argument `< −1` ⇒ all lit, `> 1` ⇒ all unlit). If `|q_⊥| ≤ tol`: all generators lit iff `r·(q·a) > tol`,
  else none. This is the "tangent from the apex" condition of §5.6 (tangents from the central projection of `L`
  through the apex onto the base plane, `l_a = v − (h/(q·a))·q`; the formula already covers the `q·a > 0`
  complement case). Loop = base arc + generator + apex + generator.
- Output of curved outlines: `conics` entries (full field list in §3.1)
  `{conic: 3x3, kind, arc: {theta0, theta1} | null, circle: {centre, e1, e2, radius}, map: "shadow"|"image", sampled,
  which, visible, polylines, arcs, ellipses}` (+ `back` in `outlines[]`);
  `arc` is the circle-parameter range (radians, CCW in the circle's `(e1,e2)` frame, `theta1 > theta0`);
  `null` = full conic. The 4-D parametrisation `X(θ) = T·E·(ρ cos θ, ρ sin θ, 1)` (`T = M` for shadows, `I` for
  image circles) is kept so that:
  * **near clipping of conics**: `ν(X(θ)) = A cos θ + B sin θ + C` is closed form; a `<ellipse>` is emitted only
    when `C − √(A²+B²) ≥ 0` (whole circle in front) and `kind == ellipse`; otherwise the visible sub-arc(s)
    `[θa, θb]` are solved in closed form, `arc` is restricted to them, and only those are drawn;
  * **unbounded curved shadows**: `w_S(θ)` is likewise `A' cos θ + B' sin θ + C'`; arcs with `w_S ≤ tol` are dropped,
    direction vertices are inserted at the exact `w_S = 0` crossings with the §2.5 rule, and the arc samples + the
    generator/segment shadows are joined into one oriented homogeneous polygon that goes through the full
    drawing pipeline; `unbounded=true`. A hyperbola/parabola polyline must never cross `w = 0`.
  * Sampling (64 segments per full circle, proportionally fewer for arcs, minimum 8; the count is
    `max(8, round(64·|θ1 − θ0| / 2π))` — **rounded to the nearest integer, not `ceil`**, so that an arc at an exact
    fraction of the circle keeps its count under the rounding noise of §7.1 rows 3–4; `conics.sample_count`) is used
    in two places and nowhere else: (a) the conic **drawables** (`polylines` / `arcs` / `ellipses` of §3.1) are sampled
    only at the output stage (stage C / `output/`); the exact conics and their 4-D parametrisation are never sampled in
    stage A/B — near clipping, canvas clipping and the `w_S = 0` crossings are solved in closed form on them; (b) the
    **filled shadow polygon** of a curved object (`shadows[].polygons[0]`, `curved.shadow_polygon_h`) and the lit
    boundary of the **ground cross-section** of a partly buried curved object (`curved._ground_section`, §2.3) are
    sampled with the same rule in stage A (64 per full circle, minimum 8), because they are part of the
    camera-independent outline (its finite vertices are the named ground points `<obj>.s<k>.<light>` with world
    coordinates in the document); the exact boundary is kept beside them in `shadows[].conics` (`map == "shadow"`).
- Ellipses are written as `<ellipse>` (full) or `<path d="M … A rx ry rot large sweep x y">` (arc, flags decided
  by checking the arc's midpoint); parabola/hyperbola/degenerate are sampled polylines.

### 2.7 Construction (spec §5.5)
*Amended by §5.1.5 (per-receiver `F'_r`, rays and checks in `construction.per_receiver`), §5.2.4 (mesh rays capped at 64 feature silhouette vertices) and §5.3.3 (`constructions` per light).*
- `L' = P·L`, `F' = P·F`, `P'_i = P·P_i`, `Q'_i = P·Q_i`, `S'_i = P·S_i` all as 2-D homogeneous 3-vectors.
- Undefined special points **[decision]**: a directional light along the receiver normal makes `F = 0`; then the `F.<light>`
  point is omitted, `shadow_vp` and `shadow_vp_at_infinity` are both `null`, no `SHADOW_VP_AT_INFINITY` warning, no `F'Q'`
  rays, and the self-check uses `S' = Q'`. A point light at the camera centre makes `L' = 0` (tested as
  `max|x̃| ≤ 1e-9·max|P|·max|L|`); then `light_point` and `light_point_at_infinity` are both `null`, no warning, no `L'P'`
  rays, and the self-check uses `S' = P'`.
- `L` and `F` are **never near-clipped or nulled**: `light_point`/`shadow_vp` are computed by plain division whenever
  `|x̃3| > tol`; `x̃3 < 0` for a finite `L` → `LIGHT_BEHIND_CAMERA` (反光點, finite, below the horizon); `|x̃3| ≤ tol`
  → `light_point_at_infinity = normalize_max((x̃1, x̃2))` and `LIGHT_POINT_AT_INFINITY`; likewise
  `shadow_vp_at_infinity` + `SHADOW_VP_AT_INFINITY` for `F`.
- **[decision]** `LIGHT_BEHIND_CAMERA` is emitted for a **finite** `L` only. Spec §5.7 row 1 ("光源在觀者後方", `x̃3 < 0`)
  does not say "point light", but for a directional light `L' = P·(d, 0)` is the ordinary image of a direction: it is
  finite whenever `d` is not parallel to the picture plane, `x̃3 = forward·d < 0` only says that the sun is in the
  hemisphere behind the camera, and the drawing rule below (the 2-D segment covering `L'`, `P'`, `S'`) is the same
  in both hemispheres; `light_point` itself (below the horizon) tells the painter. Nothing is degenerate, so no
  warning (same reasoning as the undefined special points above); `examples/directional.json` is this case.
- Self-check: `S'_check = (L'×P') × (F'×Q')`; compared with `S'` after `normalize_max` of both; must agree within
  1e-6 mm in `(u,v)`. Skipped with `CONSTRUCTION_CHECK_SKIPPED` (ids `[point name]`) when either line is the zero
  vector (`P' = L'` or `Q' = F'` projectively), when the two lines are (nearly) parallel or coincident
  (`max|l1 × l2| ≤ 1e-6` after `normalize_max` of both lines — the intersection amplifies rounding by `1/sin θ`,
  so below that the 1e-6 mm comparison is meaningless), or when `S'` is at infinity (`|x̃3| ≤ tol`).
  **[decision]** Checks are produced exactly for the vertices whose construction rays are drawn (`ν(P)`, `ν(S)`,
  `ν(Q) ≥ 0`, see below): a shadow point behind the near plane has no meaningful mm image (its depth may be
  arbitrarily close to 0), is not drawn, and gets neither a check nor a `CONSTRUCTION_CHECK_SKIPPED` warning.
- **Rays drawn [decision]**: construction rays are 2-D segments, never near-clipped 3-D segments. For a silhouette
  vertex with `ν(P) ≥ 0`, `ν(S) ≥ 0` and `ν(Q) ≥ 0` the ray `L'P'` is the 2-D segment covering `L'`, `P'`, `S'`
  (when `L'` is at infinity: the segment `P'→S'` extended by 20 % beyond both ends), likewise `F'Q'` covers
  `F'`, `Q'`, `S'`; both go through step 3+4 of the drawing pipeline (homogeneous rectangle clip). Also the
  vertical `P'Q'` ("頂點垂線"). Vertices with any of `P`, `S`, `Q` behind the camera get no ray (counted under
  `POINT_BEHIND_CAMERA`). When `L` is behind the camera the image of the 3-D segment `LP` is the complement of
  the 2-D segment `L'P'`, while `S'` provably lies on the 2-D line `L'P'` (between `L'` and `P'`); the 2-D rule is
  what a painter draws and overrides the wording of spec §5.7 row 1.
- Only silhouette vertices get construction rays (§5.1); for curved objects: sphere → centre `<obj>.c` and
  silhouette-circle points `<obj>.sil.0..3 = centre ± r_s·e1, ± r_s·e2` (frame of §2.6); cylinder → generator
  endpoints `<obj>.g0.base/top`, `<obj>.g1.base/top` (ordered `θ_l − α`, `θ_l + α`); cone → `<obj>.g0.base`,
  `<obj>.g1.base`, `<obj>.apex`. The sphere centre's shadow is a construction aid, not the centre of the shadow ellipse.
- **Camera outline points**: the tangent generators of the camera silhouette of a cylinder / cone end in the named
  points `<obj>.og<k>.base` / `<obj>.og<k>.top` (`k ∈ {0, 1}`; a cone's `.top` is its apex). They exist only for the
  current camera (a flat cone seen from above has none), so they are **camera dependent**: they are `points` entries
  and the segments are `outlines[].generators` (drawn in the objects layer), never `edges[]` entries (whose list is
  camera independent); they get no construction rays, no shadow / foot points and no labels.

### 2.8 Numerics (spec §5.8)
*Amended by §5.1.10 (HLR constants), §5.3.7 (`tol_mm` / `tol_area` in canvas mm) and §5.4.4 (the JavaScript port's numerics).*
- float64 everywhere. Stage A uses `scene_scale_A = max(1, extent of the bounding box of all object mesh vertices)`
  (camera-free, so world shadows stay camera-independent per §7.1 row 2); stage B/C use
  `scene_scale = max(scene_scale_A, extent including the camera position)`. Light positions are excluded from both so
  that the 10⁶ m convergence test keeps tolerances sane.
  `tol = 1e-9 · scene_scale` for length-valued predicates (`ν`, `w_S` and `lit` with point lights, ground clip);
  `tol_dir = 1e-9` for dimensionless ones (`lit`/`w_S` with directional lights, direction tests); projective
  equality of 2-D points/lines uses a relative 1e-9 after `normalize_max`. The two places where the tests compare
  with a looser tolerance than the spec's 1e-6 mm / 1e-9 are recorded in §4 (clipped ray endpoints, nearly
  picture-plane-parallel lights).
- `normalize_max(v)` divides a homogeneous vector by its max-|component| (sign preserved); never divide by `w`
  before clipping.
- All predicates are `> tol` / `< −tol`; the band in between counts as the degenerate side.
- Degenerate situations never raise. They append `{"code": <CODE>, "ids": [...], "message": str}` to
  `warnings` (deduplicated, sorted by code then ids). Input errors raise `SceneError(field=...)`.
- Determinism: every emitted float is canonicalised with `x + 0.0` (no `−0.0`); stage A/B use fixed-size
  expressions / `einsum` with fixed operand shapes, never reductions over variable-length axes whose order could
  vary; a test renders the same scene twice in-process and compares the JSON bytes.

### 2.9 Warning codes (closed list for v1): code → predicate → ids → effect
*Amended by §5.0.5: the list grows to 18 (`RECEIVER_UNLIT`, four `MESH_*` codes) and the ground-only scope of four codes is recorded there.*
| code | predicate | ids | effect |
| --- | --- | --- | --- |
| `CAMERA_LOOKING_ALONG_UP` | \|forward × up_world\| ≤ 1e-9 | `[]` | fallback up (0,1,0) |
| `LIGHT_BEHIND_CAMERA` | finite `L` only (§2.7 [decision]), `x̃3(L') < −tol` | `[light]` | `L'` finite (反光點) |
| `LIGHT_POINT_AT_INFINITY` | \|x̃3(L')\| ≤ tol | `[light]` | `light_point` null, `light_point_at_infinity` set, rays parallel |
| `SHADOW_VP_AT_INFINITY` | \|x̃3(F')\| ≤ tol | `[light]` | `shadow_vp` null, `shadow_vp_at_infinity` set |
| `DIRECTIONAL_HORIZONTAL` | directional, \|n·l\| ≤ tol_dir | `[light]` | no shadows / rays |
| `LIGHT_BELOW_RECEIVER` | point `πᵀL ≤ tol`, or directional `n·l < −tol_dir` | `[light]` | no shadows / rays |
| `VERTEX_NOT_BELOW_LIGHT` | some silhouette vertex `w_S ≤ tol` | `[object]` | unbounded outline (§2.5/2.6) |
| `OBJECT_BELOW_RECEIVER` | some vertex `πᵀP < −tol` | `[object]` | loop clipped to the ground (§2.3) |
| `POINT_BEHIND_CAMERA` | some drawn point of the object (vertex, shadow, foot, ground point, curved point, part of a drawn circle) `ν < 0` | `[object]` (never `[light]`: `L` / `F` are not nulled) | image null / segment clipped / ray omitted |
| `FACE_PARALLEL_TO_LIGHT` | some face (incl. a cylinder / cone cap) \|n_f·(l − w·p)\| ≤ tol | `[object]` | face unlit |
| `LIGHT_INSIDE_OBJECT` | point light: sphere \|l − c\| ≤ r; cylinder / cone with nothing lit; box / prism with the light strictly inside the solid (§2.5, `primitives.point_inside_solid`) | `[object]` | no shadow / terminator / construction points for that object (a polyhedron keeps all its faces, unlit, in `form_shadow`); message names the kind |
| `CONIC_SAMPLED` | some conic of the object degenerate or cond > 1e8 | `[object]` | polyline instead of ellipse / arc |
| `CONSTRUCTION_CHECK_SKIPPED` | §2.7 skip conditions | `[point name]` | check entry absent |

### 2.10 SVG layers (spec §6.1) — exact ids, order (bottom → top) and default styles (lengths in mm)
*Amended by §5.0.6 (sub-group order with the M4 `*.hidden` groups and the M6 per-light / `umbra` / `core` groups) and §5.0.4 (labels).*
| order | `<g id>` | content | default style |
| --- | --- | --- | --- |
| 1 | `horizon` | horizon segment; vanishing points x/y/z (when finite); principal point | `stroke="#999" stroke-width="0.15"`; points `r="0.6"` filled `#999`, name text 2.5 mm |
| 2 | `objects` | all edges; curved: outline generators + cap conics | `stroke="#111" stroke-width="0.3"`; back edges `stroke-dasharray="1.2 0.8" stroke-width="0.2"` |
| 3 | `form_shadow` | unlit faces as polygons; curved: terminator conics/generators | `fill="#335" fill-opacity="0.18" stroke="none"`; terminator `stroke="#335" stroke-width="0.2"` |
| 4 | `cast_shadow` | one sub-group `<g id="cast_shadow.<light id>">` per light; outlines as paths (`fill-rule="nonzero"`) | `fill="#000" fill-opacity="0.3" stroke="#000" stroke-width="0.25"` |
| 5 | `construction` | `L'` (marker: circle r=1 + "L′"), `F'` (marker: diamond + "F′"), rays `L'P'` (`stroke="#d33"`), `F'Q'` (`stroke="#36c"`), verticals `P'Q'` (`stroke="#3a3"`) | `stroke-width="0.15"` |
| 6 | `labels` | vertex ids (`v0`…), point names, object ids at the object's top vertex | `font-size="2.2"` `fill="#444"` font-family `sans-serif` |
`write_svg(doc, layers)` emits only the requested subset, preserving this order; a layer without content is still
written as an empty `<g>`. Sub-groups: `objects.<id>` with `objects.<id>.front` / `.back`, `form_shadow.<id>` with
`form_shadow.<id>.terminator`, `cast_shadow.<light>` with `cast_shadow.<light>.<object>.conics` (stroke-only exact
conic outline on top of the filled polygon), `construction.LP` / `.FQ` / `.PQ`. The writer draws the document's
drawables (`edges[].segment`, `shadows[].polygons`, `form_shadow[].polygons`, `outlines[].generators[].segment`, the
`polylines` / `arcs` / `ellipses` of conic entries, `construction.segments`, `horizon.segment`), all already in canvas mm.
Back edge: both adjacent faces have `lit(n_f, p, (C,1)) == False` (camera as light). Cap-circle arcs of curved objects
are split at the camera outline generators; the arc on the far side is back. Labels: vertex ids (`v<k>`) and curved
construction points (`c`, `sil.<k>`, `g<k>.base/.top`, `apex`), `L.<light>` / `F.<light>`, and the object id at its
highest labelled point; shadows, feet, ground points (`s<k>`) and camera outline points (`og<k>`) get no label.
PNG (§6.3): transparent background, size = `round(canvas_mm · dpi / 25.4)` px.

## 3. Public API (pure functions on JSON-serialisable data + numpy)
*Amended by §5.0.7 (keywords `hidden_lines`, `hidden_style`, `umbra`; `castplane.io.load_expanded_scene`; new modules).*
```python
scene = castplane.load_scene(path_or_dict)                 # validated dict (raises SceneError)
A      = castplane.shadow_geometry(scene)                  # stage A: camera independent
B      = castplane.project_scene(scene, A, camera=None)    # stage B: camera may be overridden (dict in §4 form)
doc    = castplane.compose(scene, B)                       # stage C: §6.2 geometry dict
svg    = castplane.output.svg.write_svg(doc, layers=None)  # str
png    = castplane.output.png.write_png(svg, dpi)          # bytes, optional extra
result = castplane.render(scene, camera=None)              # {"geometry": doc, "svg": str}
```
`A`, `B` are plain dicts of numpy arrays/lists and may be cached; `shadow_geometry` must not touch the camera.
Stage A content: per object the mesh, lit flags, silhouette loops, homogeneous shadow loops (with direction
vertices), feet `Q`, curved silhouette/terminator circles and shadow parametrisations, `F`, `L`, warnings.
Stage B content: the camera matrices and every projected point/segment/polygon in homogeneous 2-D form plus
the near-clipped drawables; stage C turns B into the §6.2 document (with division and canonical floats).
Also public: `castplane.scene.load_camera(path_or_dict)` (a camera block or a scene holding one; used by the CLI
`--camera`), `castplane.output.geometry_json.dumps(doc)` / `write_geometry_json(doc, path)` (the deterministic
serialisation of §3.1), `castplane.errors.warning_codes(warnings)`; the full list is in `docs/USAGE.md`.

### 3.1 §6.2 geometry document (keys, deterministic)
*Amended by §5.0.3 (the full v2 key listing), §5.0.4 (point-name grammar) and §5.4.5 (`allow_nan=False`, `INT_KEYS`).*
```
canvas_mm, camera {P: 3x4, C: [x,y,z], horizon_line: [a,b,c], principal_point: [u0,v0]},
points {name: {world: [x,y,z], image: [u,v] | null, depth: float}   -- finite points
        name: {direction: [dx,dy,dz], at_infinity: true, image: [u,v] | null}},
edges [{object, from, to, silhouette: bool (w.r.t. light), back: bool (w.r.t. camera), visibility: "visible",
        segment: [[u,v],[u,v]] | null}],                             -- polyhedral objects only (camera independent list)
shadows [{light, receiver, object, outline: [point name | {"direction": [dx,dy,dz]}], loops: [[...]], conics: [...],
          unbounded: bool, polygons: [[[u,v], ...], ...]}],
form_shadow [{object, faces: [[point names]], polygons: [[[u,v], ...], ...],
              terminator: [{conic entry} | {"segment": [name, name], "polylines": [[[u,v],[u,v]]] | []}]}],
outlines [{object, generators: [{from, to, back: false, segment: [[u,v],[u,v]] | null}], conics: [{conic entry + back}]}],
construction {light_point: [u,v] | null, light_point_at_infinity: [a,b] | null, shadow_vp: [u,v] | null,
              shadow_vp_at_infinity: [a,b] | null, rays: [["L", name], ["F", name]], checks: [{point, max_error_mm}],
              segments: [{kind: "LP"|"FQ"|"PQ", point: name, points: [[u,v],[u,v]]}]},
horizon {v_mm: float | null, line: [a,b,c], segment: [[u,v],[u,v]] | null, vanishing_points: {x: [u,v] | null, y: ..., z: ...}},
warnings [{code, ids, message}]
```
`outline` is the first loop (for compatibility with the spec example), `loops` has all loops. Everything named
`segment`, `segments[].points`, `polygons`, `polylines`, `arcs`, `ellipses` is a **drawable**: canvas mm after the
full drawing pipeline of §2.2 (near clip, `P`, extended-rectangle clip, division); `null` / empty when nothing is in
front of the near plane or inside the extended canvas. The SVG writer draws drawables only.

Conic entry (`shadows[].conics`, `outlines[].conics`, `form_shadow[].terminator`):
```
{conic: 3x3 (max-normalised, +1 max entry), kind: "ellipse"|"parabola"|"hyperbola"|"degenerate",
 arc: {theta0, theta1} | null (null = the whole circle), circle: {centre, e1, e2, radius} (world, the 4-D parametrisation),
 map: "shadow"|"image", sampled: bool (CONIC_SAMPLED predicate), which: "base"|"top"|"silhouette",
 visible: [[a, b], ...] (circle-parameter intervals in front of the near plane AND inside the extended canvas; empty = nothing drawn),
 polylines: [[[u,v], ...], ...] (sampled, for parabola / hyperbola / degenerate / sampled conics),
 arcs: [{start, end, rx, ry, rotation_deg, large_arc, sweep, theta: [a, b]}] (SVG A parameters, sweep in the v-up frame),
 ellipses: [{centre, rx, ry, rotation_deg}] (only for a whole circle in front of the near plane, healthy ellipse, partly visible),
 back: bool (outlines[] only; dashed when true)}
```
The `cond` of `conics.conic_entry` is dropped from the document. The drawn shadow polygon of a curved object
(`shadows[].polygons[0]`) is the sampled outline of `curved.shadow_polygon_h` (64 samples per full circle, rule above);
the exact boundary is in `conics` with `map == "shadow"`.

Point names: `"<obj>.v<k>"`, `"<obj>.v<k>.shadow.<light>"`, `"<obj>.v<k>.foot"`, `"L.<light>"`, `"F.<light>"`
(direction points with `at_infinity: true` for a directional light; `F.<light>` absent when `F` is undefined, §2.7),
`"<obj>.s<k>.<light>"` ground-crossing / ground-polyline points (§2.3: their own shadow and foot, no ray), curved
construction names per §2.7 with the same `.shadow.<light>` / `.foot` suffixes (a curved shadow-polygon vertex that is
the uncut shadow of a construction point is named by it, e.g. `<obj>.g1.base.shadow.<light>`, `<obj>.sil.k.shadow.<light>`
at the quarter points of an unclipped sphere circle; every other finite vertex is a ground point), and the camera
outline points `"<obj>.og<k>.base/.top"`. Floats are written with `repr`-style shortest round-trip formatting after
`+ 0.0`; `json.dumps(doc, sort_keys=True, indent=1, ensure_ascii=False)`.

## 4. Testing contract (spec §7)
*Amended by §5.0.8 (conformance set versions v3–v6, `rules.json`) and §5.0.9 (benchmark rows); per-milestone test contracts in §5.1.11, §5.2.11, §5.3.10, §5.4.13, §5.5.10.*
- `tests/test_invariants.py` covers all six §7.1 rows with the stated tolerances, with three recorded exceptions:
  (i) the endpoints of the **clipped construction-ray segments** (rows 1–4) are compared with
  `1e-6 mm × max(1, max |defining image coordinate| in mm)` (`P'`, `S'`, `Q'`, `L'`, `F'`), because the clipped
  endpoint inherits the conditioning of the rectangle clip of a segment defined by points up to a few metres of
  canvas away (measured worst case 2e-6 mm at a 2.2 m scale); every point, edge, polygon, `L'`, `F'` and horizon
  comparison stays at 1e-6 mm; (ii) `tests/test_property.py` compares the (nearly) picture-plane-parallel light
  family (`forward·d` down to 1e-7, `L'` at ~1e9 mm) with a relative 1e-8; (iii) row 3 (point light at 10⁶ m
  along the sun direction from the world origin) is compared with `max(1e-4 m, 2·δ)` instead of a flat 1e-4 m,
  where `δ = h·|S_dir| / (D·sin e − h) + |X_pt − X_dir| / sin e` is the exact gap of the homothety
  `S_pt = S_dir · D sin e / (D sin e − h)` (vertex height `h`, sun elevation `e`, `|S_dir|` the distance of the
  directional shadow from the origin; the second term is the first-order motion of a curved object's own
  construction point, zero for mesh vertices), the mesh-vertex gap must equal that homothety within 1e-9 m and
  every gap must shrink tenfold at 10⁷ m, because the spec's 1e-4 m is not universally true in the tested
  domain (a 2.95 m vertex under a 20° sun gives 1.001e-4 m while the library matches the closed form to 1e-15 m;
  D20). Row 4 (rigid equivariance) uses
  the symmetry group of the ground: rotations about +Z and translations in XY applied to objects, light and
  camera (position + target, roll unchanged; a second variant uses the yaw/pitch form with `yaw += angle`).
  Row 5 per §2.1 (positive scalars on inputs; either sign on sign-free outputs). **Limitation**: the scene document
  only carries canonical inputs (finite positions, unit directions, `w = 1`), so row 5 cannot be exercised through
  `render`; it is tested at the helper level (`shadow_matrix`, `foot`, `project`, `self_check`, `conic_entry`,
  `curved.silhouette` / `shadow_outline` with scaled `L`, `π`, `P`, `M`), which is where homogeneous vectors exist.
- `tests/test_analytic.py` covers §7.2 bullets 1, 2 and 4 plus the roll test vector of §2.2 and the box `h/(h−1)`
  case; `tests/test_curved.py` covers the §7.2 sphere-ellipse bullet (closed form `a = r/sin φ`, `b = r`) and the
  §4 pillar/lamp tangent-generator boundaries (`θ_l = −63.43°`, boundaries `−148.30°` and `21.43°`).
- `tests/test_degenerate.py` has at least one test per spec §5.7 row (six rows) asserting warning codes and finite output.
- `tests/test_raycast.py` (§7.3): seeded random scenes (1–10 primitives, incl. concave prisms and a case with the
  light foot inside a concavity), grid sampling on the ground, IoU ≥ 0.99.
- `tests/test_property.py` (§7.4): hypothesis strategies for scenes/cameras incl. degenerate distributions
  (light behind camera, light direction parallel to the picture plane, vertices above the light).
- `tests/conformance/` (§7.5): `cases/*.json` (spec §4 scenes + a `description` key) and `expected/*.json`
  (`geometry_json.dumps` of `render(...)["geometry"]`), compared by `tests/test_conformance.py`: every image
  coordinate / drawable within 1e-6 mm (absolute), every other number within 1e-9 relative (absolute floor 1e-9),
  every non-number exactly, warning **code sets** equal (and the `(code, ids)` sets). The set (currently v2, see
  `tests/conformance/CHANGELOG.md`; "v1" elsewhere names the M3 deliverable) holds 34 cases: the four §7.2
  analytic cases, every spec §5.7 row (+ the undefined-`F`/`L'`, light-below-receiver, light-inside-object and cap-at-light-height
  corner cases), the five example scenes, the concavity case, two partly buried objects, roll + shift and yaw/pitch
  cameras and six random §7.3 scenes that pass the ray-cast gate. Expected files are regenerated only with
  `tools/regen_conformance.py --reason "..."` (optionally `--case NAME`), which appends `## v<N> — <date>` to
  `tests/conformance/CHANGELOG.md` (with the Python / NumPy build that produced the files); the set is versioned
  by `N`. Rules in `tests/conformance/README.md`. Expected files are **bit-exact only for the recorded
  interpreter / NumPy build** (another libm rounds the last bits differently, ≈ 1e-12 on a few leaves); the
  determinism requirement of §2.8 is per build, so `test_regen_tool_exit_codes_match_its_docstring` requires
  zero drift of `--dry-run` only on the recorded NumPy version and otherwise only that every drifted case still
  passes the §7.5 tolerances.
- `tests/test_cli.py`: render / validate / info / stages, `--camera` (camera-only JSON and scene file), `--layers`,
  `--formats`, `--quiet`, the warning table and the exit codes (2 for a `SceneError` with the field path).
- `benchmarks/bench.py`: 100 primitives / ~10k edges < 1 s full render incl. SVG; camera-only re-render < 100 ms.
  **[decision]** Spec §8 calls these numbers 目標值 (targets). After two vectorisation passes the full render measures
  ≈ 0.35–0.45 s (PASS) and the camera-only re-render ≈ 110–130 ms with the default cyclic GC (≈ 90 ms with it
  disabled) on the 4-CPU CI container; the remaining cost is the Python-object floor of the §6.2 document (≈ 15k point
  dicts, 9k edge dicts, 12.8k ray dicts) plus ≈ 128k SVG coordinates, which numpy-only code cannot remove without
  changing the document's Python representation. For v1 the camera-only row is therefore recorded as a target
  that is missed by ≈ 10–30 % on this container, `benchmarks/README.md` carries the measured numbers, the CI gate
  is `python3 benchmarks/bench.py --gate full`, and closing the gap (a leaner record shape or a compiled
  formatting path) is deferred to the M7 interactive-UI work, which is where the 100 ms budget matters.

## 5. v2 extensions (M4–M8)

This section is the binding v2 contract for the five extensions of spec §9 / §10: **M4** bounded receivers, folds and
sampled hidden-line removal (§5.1), **M5** mesh import (§5.2), **M6** multiple lights (§5.3), **M7** the TypeScript
port and the web UI (§5.4), **M8** STEP import (§5.5). Everything in §1–§4 stays in force; where a rule of §2–§4 is
changed, the change is written here with a **[decision]** marker and the affected §2 paragraph carries a one-line
pointer ("amended by §5.x"). Decisions that resolve a conflict between two of the five designs are additionally
marked **[decision, synthesis]**; they are the only places where the designs' text was altered. The plain-language
log is `docs/DECISIONS.md` D21–D69 (M4 D21–D29, M5 D30–D41, M6 D42–D48, M7 D49–D60, M8 D61–D66, synthesis D67–D69); the
implementation order is `docs/PLAN-v2.md`.

Conventions of this section:
- **Numbering.** The designs were written as "§5" (M4), "§6" (M5), "M6.x" (M6), "§8" (M7) and "§9" (M8). They are
  §5.1–§5.5 here and every internal cross-reference has been renumbered (`§5.3.3` of the M4 design is §5.1.3.3,
  `M6.4` is §5.3.4, `§8.14` of the M7 design is §5.4.14, and so on). A reference to the spec is always written
  "spec §N"; an unprefixed "§N" is this contract.
- **Carried-over constraints** (every one of them applies to every subsection): the core depends on numpy only
  (loaders may use optional extras); pure functions on JSON-serialisable data; bit-identical JSON per build
  (`x + 0.0` canonical floats, sorted keys); degenerate situations warn with the closed code list of §2.9 as extended
  by §5.0.5 and never raise; input errors raise `SceneError` with a JSON field path; stage A is camera independent;
  the §2.2 drawing pipeline applies to every drawable; the existing conformance cases keep passing unless §5.0.8
  records why a regeneration is needed; the spec §8 targets hold with the new features switched off and the cost with
  them on is measured (§5.0.9); function names follow the spec symbols; every new document field is derivable by pure
  geometry from the scene JSON (anything that needs a file loader is a loader of §5.0.2, outside the core, and is
  flagged there).
- **Merge order** (spec §10: M6 ← M4, M8 ← M5; the TypeScript port in parallel): M7 step 1 (comparator file,
  §5.0.8) → M4 → M5 → M6 → M8 → M7 phase 2. The shared-file rules of each milestone (§5.1.12, §5.2.7, §5.3.9,
  §5.4.0, §5.5.0) assume exactly this order.

### 5.0 Common changes

#### 5.0.1 Scene JSON (`scene.py`) — the unified §2.0 table additions
All rows are additive: every v2 scene validates unchanged. Field paths are as written; `load_scene` fills the defaults.

| field | rule | milestone |
| --- | --- | --- |
| `objects[i].type` | one of `box, cylinder, sphere, cone, prism, mesh` (`OBJECT_TYPES`); the loader-only type `step` (`LOADER_TYPES = ("step",)`) is rejected by `validate_object` **before** the `OBJECT_TYPES` test with `SceneError(f"{field}.type", "loader object type 'step' must be expanded first (castplane.io.expand_scene or 'castplane import')")`; unknown types keep the "must be one of …" message | M5, M8 |
| `objects[i]` (`mesh`) | `data` (inline geometry, §5.2.1) is **required by validation**; `path` / `node` / `up` / `scale` / `weld_tolerance` / `smooth_angle_deg` as §5.2.1. **[decision, synthesis]** A `mesh` object written with `path` and no `data` is a loader-level object exactly like `step`: `validate_object` raises `SceneError(f"{field}.path", "mesh file must be expanded first (castplane.io.expand_scene or 'castplane import')")`; `castplane.io.expand_scene` (§5.0.2) reads the file and fills `data`, keeping `path` as written (informational). In the scene as written at least one of `path` / `data` is present (neither → `SceneError(f"{field}.data", "required")` from `validate_object`); an object carrying **both** is taken as already expanded (`data` is used, `path` is informational) — there is no "both given" error, which is what keeps `expand_scene` idempotent. The usable-face guard and the `up: "y"` axis map of §5.2.1 run in `validate_object` on `data` (numpy only, no file) | M5, M8 |
| `objects[i].id` / `receivers[i].id` / `lights[i].id` | **[decision, synthesis] reserved ids**: `hidden` is never a valid object, receiver or light id (it is the id of the `objects.hidden` / `form_shadow.hidden` / `cast_shadow.hidden` sub-groups of §5.1.8); in a **multi-light** scene (`len(lights) ≥ 2`) `umbra` and `core` are rejected as light ids (M6, §5.3.0) **and** `core` also as an object id (kept symmetric with the light-id rule so that the prefix `form_shadow.core` names the core group alone; `form_shadow.<light>.<obj>` itself cannot collide with it because a light id is never `core`). Message `"reserved id"` for `hidden` (any id kind) and for the object id `core`; `"reserved id in a multi-light scene"` for the light ids `umbra` / `core` (§5.3.0; one string per row, M6 implementation note; final review docs-contract#6); field the id's own path. Receiver ids are disjoint from object ids (M4) **and from light ids** (§5.0.4: the point-name grammar is parsed from the right against the known light ids and receiver ids) | M4, M6 |
| `receivers` | non-empty list; ids unique, non-empty, no `.`; §5.1.1 rows (`normal` any unit vector, `offset` any number, `bounds` as there, unbounded only at index 0 and only for the ground) | M4 |
| `lights` | non-empty list of any length; ids unique, non-empty, no `.`; §5.3.0 | M6 |
| `output.hidden_lines` | boolean, default `false` | M4 |
| `output.hidden_style` | `"dashed"` (default) or `"omit"` | M4 |
| whole scene | `scene.read_json(path) -> dict` is extracted from `load_scene` (behaviour unchanged: `JSONDecodeError` → `SceneError("", "invalid JSON: …")`) and reused by `castplane.io.load_expanded_scene` | M5 (needed by `load_expanded_scene`, which M5 owns; the M8 design wrote it) |

`castplane.load_scene(path_or_dict)` stays **pure** (no file access besides the scene file itself; signature unchanged;
M5's `base_dir` keyword is **not** added — [decision, synthesis], see §5.0.2). `validate_scene(scene)` keeps its signature.

#### 5.0.2 Loader layering: `castplane/io/` (M5 + M8 unified) **[decision, synthesis]**
The M5 design placed its loaders in `castplane/loaders/` and called them from `validate_scene`; the M8 design placed
its parser in `castplane/io/` and ran an expansion step *before* validation. One layering is adopted for both:
- **Package** `castplane/io/` (the name M8 chose; M5's module names are kept): `__init__.py` (registry and expansion),
  `obj.py`, `gltf.py`, `trimesh_adapter.py` (M5, §5.2.8), `part21.py`, `step.py` (M8, §5.5.2–§5.5.7), `cli.py` (the one
  `import` subcommand, §5.0.2 below). `castplane/meshprep.py` (M5's preprocessing pipeline), `castplane/hidden.py`
  (M4), `castplane/umbra.py` and `castplane/multilight.py` (M6) are **core** modules (numpy only, no file access).
  Inside `castplane`, `import io` is the absolute stdlib import (PEP 328); no shadowing.
- **Expansion before validation.** `castplane.io.expand_scene(scene, base_dir=None) -> (scene_out, notes)` returns a
  new dict in which every object that is a key of `EXPANDERS` is replaced, in its list position, by the objects its
  expander returns: `EXPANDERS = {"step": expand_step_object, "mesh": expand_mesh_object}`, where `expand_mesh_object`
  acts only on a `mesh` object carrying `path` and no `data` (it loads the file through `load_mesh_file(abs_path, node)`,
  §5.2.8, or — when the extension is `.step` / `.stp` — through `EXTENSION_LOADERS[".step"] = tessellate_step`, §5.5.7,
  and returns the same object with `data` filled and `path` kept); every other element is deep-copied unchanged, a
  non-list `objects` or a non-dict scene is passed through so that `validate_scene` reports the proper field path.
  `base_dir` = the directory of the scene file when the scene came from a file, else the current working directory
  unless given; a relative `path` is joined to it. Loader errors are re-raised as `SceneError(field="objects[i].path",
  message=<loader message>)`; a missing optional dependency propagates as `ImportError` (CLI exit 3); an unreadable
  file is an `OSError` (CLI exit 1). Within one call a parsed file is cached by absolute path (no observable effect).
  `expand_scene` is idempotent on an expanded scene.
- `castplane.io.load_expanded_scene(path_or_dict, base_dir=None) -> (scene, notes)` = `scene.read_json` (for a path)
  → `expand_scene` → `validate_scene`. It is what the CLI (`render`, `validate`, `stages`, `info`, `import --into`) uses;
  it does not shadow `castplane.load_scene` (different name, different return type on purpose). API users with
  file-referencing scenes call it; the stages A/B/C and `render` only ever see expanded scenes. Consequently the
  TypeScript port (§5.4) consumes expanded scenes and needs no loader; conformance cases are post-expansion scenes
  (`type: step` and `mesh` + `path` never appear in `cases/`; `test_conformance.py` asserts it).
- **Importer notes** (one mechanism for M5 and M8): a note is `{code, ids, message}` from the closed list
  `castplane.io.IMPORT_NOTE_CODES` = M5's `IMPORT_SPOT_AS_POINT`, `IMPORT_CAMERA_DROPPED`, `IMPORT_NO_CAMERA_DEFAULT`,
  `IMPORT_NO_LIGHT_DEFAULT` + M8's `STEP_UNIT_ASSUMED_MM`, `STEP_ANGLE_UNIT_ASSUMED_RAD`, `STEP_SOLID_TESSELLATED`
  (M8's `STEP_WARNING_CODES` is this sub-list; `make_step_warning` builds a note). `IMPORT_LIGHT_DROPPED` of the M5
  design is **retired** because M6 is in this contract: the importer emits every light (§5.2.8). Notes are returned by
  `expand_scene` / `load_expanded_scene`, written by `castplane import` under `meta.import_notes`, printed by the CLI to
  stderr as `note: CODE [ids]: message`, and are **never** merged into a document's `warnings` (§2.9 is closed).
- **One `castplane import` subcommand** (`castplane/io/cli.py`: `add_import_parser(sub)`, `cmd_import(args)`;
  `castplane/cli.py` changes by one import line, one `add_import_parser(sub)` call and the four scene-loading call
  sites switching to `load_expanded_scene` — all three edits are made by **M5**, which merges first and needs them for
  `mesh` + `path` scenes; M8 adds nothing to `castplane/cli.py`, it only registers `EXPANDERS["step"]`,
  `EXTENSION_LOADERS` and its options in `io/`). Syntax:
  `castplane import FILE [-o OUT.json] [--into SCENE] [--id ID] [-q]` plus, by extension, the mesh options of §5.2.8
  (`--inline`, `--node NAME|INDEX`, `--camera NAME`, `--light NAME`, `--scale S`, `--weld TOL`, `--smooth-angle DEG`,
  `--up y|z`) for `.obj` / `.gltf` / `.glb` / `.stl` / `.ply`, and the STEP options of §5.5.8 (`--solid K`,
  `--fallback error|mesh`) for `.step` / `.stp`; an option of the other family is a usage error (exit 2). Common rules:
  the object id defaults to the sanitised file stem (`[^A-Za-z0-9_-]` → `_`); `--into SCENE` is loaded with
  `load_expanded_scene(SCENE)` and its raw blocks (`version`, `units`, `up`, `lights`, `receivers`, `camera`, `output`
  and unknown keys) are copied verbatim, the imported objects appended to its raw `objects`; without `--into`, the
  camera and lights come from the file when the format carries them (glTF, §5.2.8), otherwise from the M5 defaults
  (bbox camera + default directional light, with notes `IMPORT_NO_CAMERA_DEFAULT` / `IMPORT_NO_LIGHT_DEFAULT`) and
  the receiver is always the ground **[decision, synthesis]**: the M8 design's `DEFAULT_SCENE_TEMPLATE` (the
  `examples/basic.json` blocks) is kept as the API constant `castplane.io.step.DEFAULT_SCENE_TEMPLATE` for the M8
  tests, and the M8 CLI test that compares the written light / camera blocks with `examples/basic.json` runs with
  `--into examples/basic.json`. The output is the **raw** assembled scene, `json.dumps(scene, sort_keys=True,
  indent=1, ensure_ascii=False) + "\n"`, numbers generated by the importer canonicalised with `+ 0.0`, blocks copied
  from `--into` untouched; `validate_scene` runs on the assembled scene as a check only (a failure is reported with its
  field path, exit 2). Exit codes as §1: 0; 1 unreadable input / unwritable output; 2 `SceneError` (incl. `StepError`),
  usage; 3 missing optional dependency (`trimesh`, `cadquery-ocp`).

#### 5.0.3 The §3.1 document — full updated key listing (amends §3.1)
The v1 shape is a strict subset: a single-light scene with the unbounded ground, no `mesh` object and `hidden_lines`
off produces the v1 document plus the switch-off values of the M4 keys (`hidden_lines: false`, `receivers` with one
entry, `construction.per_receiver: {}`, empty `runs` / `hidden_polylines` / `polygon_edges`, every `visibility`
`"visible"`). Keys marked **(N ≥ 2)** exist iff the scene has at least two lights (§5.3.5); keys marked **(mesh)** exist
only on `edges[]` entries of `mesh` objects (§5.2.4). Every other key is always present.

```
hidden_lines bool                                               -- the effective switch (scene value or render override)
canvas_mm, camera {P: 3x4, C: [x,y,z], horizon_line: [a,b,c], principal_point: [u0,v0]}
receivers [{id, plane: [nx,ny,nz,d], bounds: [[x,y,z], ...] | null,
            lit: {<light>: bool}, casts: {<light>: bool}}]      -- scene order; receivers[0] is the default receiver
points    {name: {world: [x,y,z], image: [u,v] | null, depth: float}         -- finite points
           name: {direction: [dx,dy,dz], at_infinity: true, image: [u,v] | null}}
edges     [{object, from, to, silhouette: bool (OR over lights), back: bool,
            visibility: "visible" | "hidden" | "partial", runs: [run ...], segment: [[u,v],[u,v]] | null,
            silhouette_lights: [light ids, scene order]         (N ≥ 2)
            smooth: bool, camera_silhouette: bool}]             (mesh)
                                                                -- entries of objects and of receiver bounds edges
                                                                -- (object == <receiver id>, from/to "<r>.b<k>", back false)
shadows   [{light, receiver, object (caster: object id or receiver id), outline, loops, conics: [conic entry ...],
            unbounded: bool, polygons: [[[u,v], ...], ...],
            polygon_edges: [[run record ...], ...]}]            -- parallel to polygons when hidden lines are on, [] when off
                                                                -- order: receiver (scene) → light (scene) → caster
                                                                -- (objects in scene order, then the other bounded receivers)
form_shadow [{object, faces: [[point names]], polygons, terminator: [conic entry | {segment: [name, name],
              polylines, visibility, runs}], light}]            -- light (N ≥ 2): one entry per (light, object), light-major;
                                                                -- plates (object == <receiver id>) included (§5.1.8)
form_shadow_core [{object, faces, polygons}]                     (N ≥ 2)
outlines  [{object, generators: [{from, to, back: false, segment, visibility, runs}], conics: [conic entry + back]}]
construction {light_point, light_point_at_infinity, shadow_vp, shadow_vp_at_infinity,
              rays: [["L", name], ["F", name]], checks: [{point, max_error_mm}],
              segments: [{kind: "LP"|"FQ"|"PQ", point, points}],
              per_receiver: {<r>: {shadow_vp, shadow_vp_at_infinity, rays, checks, segments}}}  -- r ≠ receivers[0]
constructions {<light>: <construction block, same shape incl. per_receiver>}   (N ≥ 2); construction == constructions[lights[0].id]
umbra     [{receiver, lights: [active light ids, scene order], polygons: [[[u,v], ...], ...] | null}]   (N ≥ 2)
horizon   {v_mm, line, segment, vanishing_points: {x, y, z}}   -- the ground's line at infinity (eye level) always
warnings  [{code, ids, message}]
conic entry {conic, kind, arc, circle: {centre, e1, e2, radius}, map, sampled, which, visible, polylines, arcs, ellipses,
             visibility, runs: [{interval: k, theta: [a, b], mm: [m0, m1], visible: bool}], hidden_polylines: [[[u,v], ...], ...],
             back (outlines[] only)}
run record  {visibility: "visible" | "hidden" | "partial", runs: [{s: [s0, s1], t: [t0, t1], mm: [m0, m1], visible: bool}, ...]}
```
Rules carried from the milestones: `runs` is non-empty only for `"partial"` (§5.1.7); a drawable with `segment: null`
(incl. a smooth non-silhouette mesh edge, §5.2.4) keeps `"visible"`, `runs: []`; `shadows[].conics` of a bounded receiver
carry `map: "shadow"` with `T = M_r`; `form_shadow[].faces` of a per-light entry list every face unlit by that light,
core faces included; `umbra[].polygons` is `[]` when fewer than two lights are active on that receiver and `null`
only when `project_scene(..., umbra=False)` was used. Serialisation unchanged (§3.1: `sort_keys`, `indent=1`,
`repr` floats after `+ 0.0`, and — M7 — `allow_nan=False`). Integer-valued leaves are exactly the keys
`INT_KEYS = {"large_arc", "sweep", "interval"}` (§5.4.5; `interval` is M4's) **[decision, synthesis]**.

**Camera-free parts** (byte-identical for two cameras; amends the M7 list of §5.4.7 for the final format):
`hidden_lines`, `receivers[]`, `points[*].world / direction / at_infinity` for every name except the camera outline points
`/\.og\d+\.(base|top)$/`, `edges[].{object, from, to, silhouette, silhouette_lights, smooth}`,
`shadows[].{light, receiver, object, outline, loops, unbounded}` and `conics[].{arc, circle, map, which}`,
`form_shadow[].{object, faces, light}` and `form_shadow_core[].{object, faces}` of **object** entries (a plate's entries exist
iff the camera faces its unlit side, §5.1.8, so their *presence* is camera-dependent; their `faces` are not), `outlines[].object`,
`construction.rays` / `per_receiver[*].rays` / `constructions[*].rays`, `umbra[].{receiver, lights}`, the camera-independent
warning codes. Camera-dependent: everything drawn (`image`, `depth`, `segment`, `polygons`, `polylines`, `arcs`,
`ellipses`, `visible`, `hidden_polylines`), `back`, `camera_silhouette`, every `visibility` / `runs` / `polygon_edges`,
`conics[].{conic, kind, sampled}` (the **image** conic `adj(H)ᵀ·C·adj(H)` with `H = P·M·E` for shadows, `P·E` for outlines,
§2.6, so its class can change with the camera; final review determinism-perf#1),
`umbra[].polygons`, the rest of `construction*`, `horizon`, `camera`, `outlines[].generators`, the `og` points.

#### 5.0.4 Point-name grammar (unified; amends §3.1)
A name is `.`-separated; ids contain no `.`; it is parsed **from the right** against the known receiver ids and light ids:
```
<obj>.v<k>                                  vertex                   <r>.b<k>                      receiver bounds vertex
<obj>.s<k>.<light>[.<r>]                    ground / bounds-clip point on receiver r (default receiver: no suffix);
                                            <obj> is the caster id: an object id or, for a plate caster, a receiver id <r'>
<base>.shadow.<light>[.<r>]                 shadow of <base> on receiver r (<base> = <obj>.v<k>, <r'>.b<k>, or a curved stem)
<base>.foot[.<r>]                           foot of <base> on receiver r
<obj>.c  <obj>.apex  <obj>.og<k>.base|top   light-independent curved stems
<obj>.sil.<k>  <obj>.g<k>.base|top          light-dependent curved stems in a single-light document
<obj>.sil.<k>.<light>  <obj>.g<k>.base|top.<light>     the same stems in a multi-light document (§5.3.2)
L.<light>   F.<light>[.<r>]                 light point, light foot per receiver (F.<light> absent when undefined, §2.7)
```
The trailing receiver suffix exists only for receivers other than `receivers[0]` (M4); the light suffix on curved stems
only when `N ≥ 2` (M6); the light id of a multi-light curved shadow therefore appears twice on purpose
(`<obj>.sil.0.<light>.shadow.<light>[.<r>]`). Receiver ids are disjoint from object ids and light ids (§5.0.1), so the
parse is unambiguous. **Labels (SVG)**: a name is unlabelled iff, parsed from the right as above, it is a shadow point
`<base>.shadow.<light>[.<r>]` or a foot `<base>.foot[.<r>]` (equivalently: a part **after the first** (the object /
receiver id) equals `shadow` or `foot` as a marker, never as a light id — a light called `shadow` / `foot` keeps its
`L.`/`F.` and stem labels, §5.3.11; final review m6-umbra#1), or its head (the part after the id) is `s<k>` / `og<k>`
(so an object called `foot` keeps its labels, as in v2); `L.<light>` and `F.<light>[.<r>]` are labelled through the L/F branch and never set an object's top
label; `<r>.b<k>` is labelled `b<k>` with the receiver id bold at its highest vertex; a light-dependent curved stem is
labelled with its `rest` (`sil.0.lamp`).

#### 5.0.5 Warning codes — the closed list of §2.9 grows from 13 to **18**
Appended to `WARNING_CODES` in this order (M4, then M5; M6, M7 and M8 add none):
| code | predicate | ids | effect |
| --- | --- | --- | --- |
| `RECEIVER_UNLIT` | bounded receiver `r`: point light `π_rᵀL ≤ tol`, or directional `\|n_r·l\| ≤ tol_dir`, or `n_r·l < −tol_dir`, or the ground emits `LIGHT_BELOW_RECEIVER` for that light (§5.1.9) | `[light, receiver]` | `r` receives nothing from that light (empty records); `r` still occludes; it casts unless the ground is unlit |
| `MESH_NON_MANIFOLD` | some edge has ≠ 2 distinct faces, or inconsistent winding that propagation cannot fix (§5.2.6) | `[object]` | per-face fallback §5.2.5; no rays / checks / inside test |
| `MESH_WINDING_FIXED` | propagation flipped faces, or a component's signed volume had the wrong sign for its nesting depth | `[object]` | faces reoriented |
| `MESH_DEGENERATE_FACES` | faces dropped in §5.2.3 step 3 | `[object]` | those faces ignored |
| `MESH_RAYS_CAPPED` | more than 64 feature silhouette vertices for one (object, light) | `[object]` | rays / checks for the first 64 (loop order) only |
Changed scope of existing codes (M4, §5.1.9): `LIGHT_BELOW_RECEIVER`, `DIRECTIONAL_HORIZONTAL`, `VERTEX_NOT_BELOW_LIGHT`,
`OBJECT_BELOW_RECEIVER` apply to the **unbounded** receiver only; `SHADOW_VP_AT_INFINITY` ids are `[light]` for the default
receiver and `[light, receiver]` otherwise; `POINT_BEHIND_CAMERA` ids may be a receiver id; `CONSTRUCTION_CHECK_SKIPPED` ids
carry suffixed names; `LIGHT_INSIDE_OBJECT` may say "inside the mesh" (M5). Multi-light (M6): `[object]` warnings are
deduplicated across lights, `[light]` warnings are per light, messages may name the light. The importer notes of §5.0.2
are a separate closed list and are not warnings.

#### 5.0.6 SVG sub-group rules (amends §2.10)
Layer order and default styles of §2.10 are unchanged. Inside a layer the sub-groups are written in this order
(bottom → top); a group marked *iff* exists only under its condition, otherwise nothing is written for it:
| layer | sub-groups in order |
| --- | --- |
| `objects` | `objects.hidden` (*iff* `doc.hidden_lines`; sub-groups `objects.hidden.<id>`, §5.1.8), then `objects.<id>` / `.front` / `.back` for every object **and every bounded receiver** (its bounds edges), document order |
| `form_shadow` | `form_shadow.hidden` (*iff* hidden lines; `form_shadow.hidden.<id>`); then, for `N = 1`: `form_shadow.<id>` / `.terminator`; for `N ≥ 2`: per light `form_shadow.<light>` (`fill-opacity = 0.18 / N_act`) holding `form_shadow.<light>.<obj>` (that light's unlit faces **minus the core faces**) and `.terminator`, then `form_shadow.core` holding `form_shadow.core.<obj>` (§5.3.6). Plates (`<obj>` = receiver id) are ordinary entries |
| `cast_shadow` | `cast_shadow.hidden` (*iff* hidden lines; `cast_shadow.hidden.<light>`); then per light `cast_shadow.<light>` (`fill-opacity = 0.3 / N_act` *iff* `N ≥ 2`) with `cast_shadow.<light>.<object>.conics` and, *iff* hidden lines, `cast_shadow.<light>.<object>.outline` (§5.1.8: the paths then carry `stroke="none"`) for a record on `receivers[0]` (and every record of a v2 document), `cast_shadow.<light>.<object>.<r>.conics` / `cast_shadow.<light>.<object>.<r>.outline` for a record on any other receiver `r` (M4 implementation note "object casting on several receivers"; final review docs-contract#5); then `cast_shadow.umbra` (*iff* `N ≥ 2`; `fill="#000" fill-opacity="0.3" stroke="none"`, one `<path>` per `umbra[]` entry with non-empty polygons) |
| `construction` | for `N = 1`: `construction.LP` / `.FQ` / `.PQ` (markers `L'`, `F'` and — M4 — every receiver's `F'_r` marker and its rays in the same three groups; **[decision, synthesis]** no per-receiver sub-group; the receivers' markers and rays follow `receivers[]` document order, never the key order of `per_receiver`, which the canonical JSON sorts — final review m4-hidden#0); for `N ≥ 2`: per light `construction.<light>` holding that light's markers and `construction.<light>.LP` / `.FQ` / `.PQ` |
| `horizon`, `labels` | unchanged (labels per §5.0.4) |
Light sub-groups are ordered by light id in code-point order (as `cast_shadow.<light>` already is); hidden-run style
`stroke-width="0.15" stroke-dasharray="0.5 0.5" fill="none"` with the layer's stroke colour; `hidden_style == "omit"`
writes the hidden groups empty. `write_svg(doc, layers=None, hidden_style="dashed")`. With `hidden_lines == false` and
`N = 1` the SVG of every v2 scene is byte-identical to the v2 writer's output (golden hashes, §5.1.11, §5.3.10).

#### 5.0.7 Public API (amends §3; all keywords default to the v1 behaviour)
```python
scene  = castplane.load_scene(path_or_dict)                        # pure; expanded scenes only (§5.0.2)
scene, notes = castplane.io.load_expanded_scene(path_or_dict, base_dir=None)   # read_json + expand_scene + validate_scene
A      = castplane.shadow_geometry(scene)                          # stage A: per receiver × light × caster, camera free
B      = castplane.project_scene(scene, A, camera=None, umbra=True)             # M6: umbra=False leaves umbra[].polygons null
doc    = castplane.compose(scene, B, hidden_lines=None)            # M4: None = scene.output.hidden_lines; then hidden.classify_document
svg    = castplane.output.svg.write_svg(doc, layers=None, hidden_style="dashed")
result = castplane.render(scene, camera=None, hidden_lines=None, hidden_style=None, umbra=True)
```
`B["A"] = A` (stage C reaches the camera-free occluder geometry through it); `project_scene` and `compose` never mutate
`A` (M7 test). New public modules: `castplane.hidden` (§5.1.6), `castplane.meshprep` (§5.2.3), `castplane.umbra` and
`castplane.multilight` (§5.3.9), `castplane.io.*` (§5.0.2, §5.2.8, §5.5.6), `castplane.output.svg_multilight` (§5.3.6).
CLI: `render` / `validate` / `stages` / `info` load through `load_expanded_scene` and print importer notes; `render`
gains `--hidden-lines` / `--no-hidden-lines` / `--hidden-style dashed|omit` (passed to `render`, the scene is not
rewritten); `info` lists receivers (`lit` / `casts`) and every light (`active`); `import` as §5.0.2.

#### 5.0.8 Conformance set versioning plan (amends §4) **[decision, synthesis]**
The five designs each claimed "the next version"; the sequence is fixed by the merge order and every entry is written
by `tools/regen_conformance.py` (`--case`, `--reason`, and the new `--rules-only` / `--strip-new-keys` modes):
| version | milestone / step | expected files | cases added | why |
| --- | --- | --- | --- | --- |
| v3 | M7 step 1 (merged **first**, before any worktree regenerates) | none change | — | comparator amendment: `tests/conformance/rules.json` becomes the single source of the comparator constants (§5.4.8) and gains `case_overrides` for the four `direction` leaves of `degenerate_cylinder_cap_at_light_height` (abs 1e-6; §5.4.4 (1)); `--rules-only --reason` entry |
| v4 | M4 merge | **all 34 change, key-additively** (new keys with their switch-off values; no number, name, order, boolean or warning changes — verified by `--strip-new-keys` before the run; §5.1.11) | 9 M4 cases (§5.1.11) | `receivers`, `hidden_lines`, `runs` etc. are unconditional keys |
| v5 | M5 merge (after rebasing on v4) | none change | 3 mesh cases, inline `data` (§5.2.11) | `--case` only |
| v6 | M6 merge (after rebasing on v5) | none change | 4 multi-light cases (§5.3.10) | `--case` only; multi-light keys are conditional |
| — | M8 | none change | none | the importer runs before the scene → document contract (§5.5.10) |
| v6 | M7 phase 2 | none change | — | both runners green on `main` at v6, recorded in the v6 entry (§5.4.0) |
Rules: (1) a worktree may run the tool as often as it needs for its own `--case` additions; at merge its local CHANGELOG
entries are collapsed into the one milestone entry whose number `regen_conformance.py::next_version` assigns on `main`;
(2) the full-set regeneration (v4) happens exactly once, on `main` at the M4 merge, never inside a worktree; (3)
`rules.json` changes go through `--rules-only` (M4 adds the `runs` rule and `hidden_polylines`, M6 adds the
`constructions` path — see below — in their own milestone entries, so the TS runner and the Python runner read one
file). The final `tests/conformance/rules.json` after M6:
```json
{"image_tol_mm": 1e-6, "rel_tol": 1e-9,
 "mm_keys": ["image", "segment", "polygons", "polylines", "hidden_polylines", "light_point", "shadow_vp", "v_mm",
             "vanishing_points", "principal_point", "canvas_mm", "max_error_mm"],
 "drawable_containers": ["arcs", "ellipses"],
 "arc_non_mm": ["rotation_deg", "theta", "large_arc", "sweep"],
 "mm_key_paths": [["construction", "segments", "*", "points"], ["construction", "per_receiver", "*", "segments", "*", "points"],
                  ["constructions", "*", "segments", "*", "points"], ["constructions", "*", "per_receiver", "*", "segments", "*", "points"]],
 "runs_rule": {"mm_abs": 0.05, "param_abs": 1e-3, "param_keys": ["s", "t", "theta"], "exact_keys": ["visible", "interval"]},
 "int_keys": ["large_arc", "sweep", "interval"],
 "max_reported": 25,
 "case_overrides": {"degenerate_cylinder_cap_at_light_height": [
     {"paths": [["shadows", "*", "loops", "*", "*", "direction"], ["shadows", "*", "outline", "*", "direction"]],
      "abs_tol": 1e-6,
      "reason": "direction vertices at a tangent w_S = 0 crossing (curved._zero_shift, acos near |c| = 1): sqrt-type amplification, measured 1.5e-9 absolute per ulp of M or L"}]}}
```
`runs_rule` applies to every number inside any `runs` list entry (edges, generators, terminator segments, conic entries,
`polygon_edges`): `mm` within 0.05 mm absolute, `s` / `t` / `theta` within 1e-3 absolute, `visible` / `interval` and the
run count exact (M4, §5.1.11; it overrides `arc_non_mm` for `theta` inside runs). `receivers[].plane` / `bounds`,
`umbra[].polygons` (an mm key already) and every other new number fall under the existing rules. `int_keys` is the
same list as the writer's `INT_KEYS` (§5.0.3; `tests/test_ts_port.py` asserts both). `test_set_covers_the_required_sources`
requires after v6: every object kind incl. `mesh`, `RECEIVER_UNLIT`, a bounded receiver, an anchor-rule case, a `w = 0`
HLR endpoint case, a case with `N ≥ 2` and one with `N ≥ 3`. `tests/conformance/README.md` gets one `### M4 受影面與隱藏線`,
`### M5 網格`, `### M6 多光源` heading each (rows appended in merge order), the rule "cases are post-expansion scenes and
mesh cases use inline `data`", the rule-2 addendum (`--rules-only`) and the rule-3 addendum naming
`ts/test/conformance.test.ts`, `rules.json` and `case_overrides`.

#### 5.0.9 Performance (amends §4; `benchmarks/README.md` records every row)
The hard CI gate stays `python3 benchmarks/bench.py --gate full` on the single-light, single-receiver, hidden-lines-off
M3 benchmark scene, which `bench.py` now **loads from the committed file** `benchmarks/scenes/benchmark_100.json`
(M7, §5.4.9) under its default arguments and generates only for the variants. The core paths with the new features off
are unchanged by design; each milestone records its switch-off delta. Informational rows (no gate): M4 `--hidden-lines`
(soft target < 5 s) and the switch-off full render + JSON size before / after M4; M5 features-off delta and
`--scene mesh10k` (stage A alone incl. the weld, and full render); M6 re-measured `N = 1`, `--lights 2|3` (full, camera-only
with and without `--no-umbra`, umbra alone) and `record_pieces` on a 2 000-edge loop; M8 fixture import time and the
200-solid file; M7 the TypeScript table (`node ts/build/bench/camera_only.js --gate both --reps 20`, CI gate literal by
the §5.4.9 margin rule). The TS bench and `bench.py` measure the same bytes (`benchmark_100.json`).

#### 5.0.10 Resolved cross-milestone conflicts (index)
Each item is written in full at the place named; this index exists so that no resolution is missed.
| # | conflict | resolution |
| --- | --- | --- |
| C1 | section / decision numbering of the five designs | §5.1–§5.5, D21–D66 (header of §5) |
| C2 | every design claimed the "next" conformance version | §5.0.8 sequence v3 (M7 rules) → v4 (M4) → v5 (M5) → v6 (M6) |
| C3 | `shadows[]` order: M4 receiver → light → caster vs M6 object-major / light-minor | receiver → light → caster (§5.0.3, §5.3.2) |
| C4 | M4 `construction.per_receiver` vs M6 `constructions{<light>}` | `constructions[<light>]` carries the M4 block incl. `per_receiver`; `construction` is the alias (§5.0.3, §5.3.5) |
| C5 | M5 loaders inside `validate_scene` vs M8 expansion before validation | expansion before validation for both; `castplane.load_scene` pure (§5.0.1, §5.0.2) |
| C6 | `castplane/loaders/` (M5) vs `castplane/io/` (M8); two `import` subcommands | one package `castplane/io/`, one subcommand, one notes list (§5.0.2) |
| C7 | M8 `fallback: "mesh"` "rejected until M5" | enabled: the M5 inline `data` keys are in this contract; M8 is implemented after M5 (§5.5.1, §5.5.7) |
| C8 | M4 HLR occluder from `obj["mesh"]` faces vs M5 `rec["triangles"]` | generic occluder uses `rec["triangles"]` when present, faces otherwise (§5.1.6.2, §5.2.7) |
| C9 | id collisions with sub-group ids (`hidden`, `umbra`, `core`) and the right-anchored name parse | reserved ids and receiver ∩ light = ∅ (§5.0.1, §5.0.4) |
| C10 | M6 "single-light document = v1 byte for byte" after M4's unconditional keys | = the v4 document shape; multi-light keys stay conditional (§5.3.5) |
| C11 | umbra per receiver with M4's bounded receivers; "active" per receiver | `umbra[].lights` = lights with `receivers[r].lit`; homography `H_r = P·E_r` (§5.3.1, §5.3.4) |
| C12 | plates (M4) under M6's per-light form shadow / core | plates are one-face polyhedra for §5.3.3 (§5.1.8, §5.3.3) |
| C13 | M5 fallback meshes on bounded receivers | per-face loops go through the bounds clip; `obj["clipped"][r] = None` (§5.2.5) |
| C14 | comparator rules spread over three Python edits | all in `rules.json` after v3; `INT_KEYS` += `interval` (§5.0.8) |
| C15 | API signatures of M4 (`hidden_lines`, `hidden_style`) and M6 (`umbra`) | merged signatures (§5.0.7) |
| C16 | M5 importer "first light only" vs M6 any number of lights | every KHR light emitted; `IMPORT_LIGHT_DROPPED` retired (§5.2.8) |
| C17 | M7 phase 2 scope (which M4–M6 geometry) | enumerated in §5.4.14 and `docs/PLAN-v2.md` |
| C18 | `bench.py` reading a committed scene (M7) vs the M5 / M6 variants | default = committed file; `--scene`, `--lights`, `--hidden-lines` generate (§5.0.9) |
| C19 | SVG sub-group order with hidden groups (M4) and per-light groups (M6) | §5.0.6 |
| C20 | M4 per-receiver construction rays in the SVG | same `LP` / `FQ` / `PQ` groups, no receiver sub-group (§5.0.6) |

### 5.1 M4 — bounded receivers, folds, sampled hidden lines (spec §9 rows 多受影面 / 隱藏線消除, spec §10 M4)

Everything in §1–§4 stays in force. This section adds to it; where it changes a §2–§3 rule the change is marked
**[decision]**. Guiding constraints (unchanged): core = numpy only; stage A never touches the camera; every drawable goes
through the §2.2 pipeline; degeneracies warn (closed code list, extended here by exactly one code) and never raise; input
errors raise `SceneError` with a field path; bit-identical JSON per build; every new document field is pure geometry of
the scene JSON (TS-reproducible; no file loader anywhere in M4).

#### 5.1.0 Verdict on the two "fast" compromises
1. *Clip the ground shadow to the half-space of the other receivers' planes instead of to their plates*: **rejected**. It
   deletes real shadow beside a small plate and is not what the light does. The fold is obtained without any
   cross-receiver clip (§5.1.3.4).
2. *Image-space sampling of hidden lines with a fixed sample rule and a fixed number of bisections*: **accepted** (spec
   §11.1 取樣法先行) because it is deterministic (sample positions are a pure function of the drawn drawable, §5.1.6.4),
   lives entirely in stage C (stage A stays camera independent) and is pure geometry. Rejected variants: adapting the
   sample count to a time budget, a seed or the hardware (breaks bit-determinism); storing HLR data in stage A (camera
   dependence); reading mesh files (M5 territory); using the approximate 32-gon mesh of curved primitives as occluder
   (their own outlines would be self-hidden): occluders are exact (§5.1.6.2) and the generic closed-mesh occluder is used
   only for kinds without an exact test.

#### 5.1.1 Validation (`scene.py`) — new and changed rows of the §2.0 table
| field | rule |
| --- | --- |
| `receivers` | **non-empty** list (was: exactly 1); ids unique, non-empty strings **without `.`** (was: `.` allowed) and **disjoint from object ids** (receiver vertex names `<r>.b<k>` share the point-name namespace; a clash raises on `receivers[i].id`) and — §5.0.1 — disjoint from light ids and never `hidden` |
| `receivers[i].type` | `"plane"` |
| `receivers[i].normal` | 3 numbers, \|n\| = 1 ± 1e-9, **any direction** (was: `[0,0,1]`) |
| `receivers[i].offset` | number, default `0`, any value (plane `n·x + d = 0`) |
| `receivers[i].bounds` | optional. **Absent ⇒ unbounded**, allowed only when `i == 0` and the plane is the ground (`normal == [0,0,1]` ± 1e-9 and `offset == 0` ± 1e-9); otherwise `SceneError(field="receivers[i].bounds", "required unless the receiver is the ground plane at receivers[0]")`. Present ⇒ list of ≥ 3 world points `[x, y, z]` (`validate_bounds(value, normal, offset, field)`); with `ext = max(1, max|coordinate| over the list)`, `e_k = b_{k+1} − b_k` (indices cyclic), `c_k = (e_k × e_{k+1})·n`: (1) coplanar, `\|n·b_k + d\| ≤ 1e-9·ext` (field `receivers[i].bounds[k]`); (2) consecutive vertices distinct, `\|e_k\| > 1e-12·ext` (field `receivers[i].bounds[k]`, "consecutive vertices coincide"); (3) **strictly convex**: all `c_k` have one sign `σ` and `\|c_k\| > 1e-9·\|e_k\|·\|e_{k+1}\|` (the sine of every turning angle exceeds 1e-9 — dimensionless; this floor is what guarantees §5.1.3.3's "no direction survives the bounds clip" in floating point; field `receivers[i].bounds`, "must be a simple strictly convex polygon"); (4) **simple**: `Σ_k atan2(σ·c_k, e_k·e_{k+1}) = 2π` within `1e-9·len(bounds)` (a star polygon such as a pentagram passes (3) with turning sum 4π and is rejected here; same field and message); (5) `σ < 0` (clockwise about `n`) ⇒ the list is **reversed silently** (same rule as the prism polygon), so the stored order is counter-clockwise about `n` seen from the positive side; (6) when `receivers[0]` is unbounded every vertex satisfies `b_z ≥ −1e-9·ext` (field `receivers[i].bounds[k]`, "below the ground receiver") |
| `output.hidden_lines` | boolean, default **`false`** (§5.1.6.6); `validate_hidden_output` |
| `output.hidden_style` | `"dashed"` (default) or `"omit"` (§5.1.8) |

Convexity is required, not a general polygon clipper **[decision]**: homogeneous Sutherland–Hodgman against the edge
functionals of a convex polygon is exact for bounded *and unbounded* homogeneous shadow polygons once the **anchor rule**
of §5.1.3.3 is applied (a plain homogeneous clip is *not* exact when the arc at infinity spans ≥ 180°, see there); a
general clipper needs bounded input and would re-introduce the order-dependent robustness problems the contract avoids.
A concave receiver is composed from several convex receivers (coplanar pieces do not shadow each other, §5.1.3.2).
`load_scene` fills `bounds: null` for the unbounded receiver.

#### 5.1.2 Receivers (contract §2.1 / §2.3 generalised)
- `receiver_plane(r) -> π = (n, d)` as given (|n| = 1). The receiving face is the **positive side** of `π` (where `n`
  points). Validation never reorients `π` **[decision]**: the user's normal names the face that receives shadows and the
  orientation of `bounds`.
- `receiver_frame(n) -> (e1, e2)` with `e1 × e2 = n`: `e1 = normalize(z × n)`, `e2 = n × e1`; when `|z × n| ≤ 1e-9`:
  `e1 = (1, 0, 0)`, `e2 = n × e1`. For the ground this is `(x, y)`. Every existing "counter-clockwise in ground `(x, y)`"
  rule (§2.5 loop orientation, the arc at infinity, the ground chain of §2.3) now reads **"counter-clockwise about `n`"**
  in `(e1, e2)` coordinates: `θ = atan2(d·e2, d·e1)`, arc vertices `cos θ·e1 + sin θ·e2`, section ordering by
  `((p − c)·e1, (p − c)·e2)`. **[decision] The ground keeps the literal v2 expressions**: whenever the receiver is the
  unbounded ground (`frame is None` in every signature below) `shadow_loop`, `curved.shadow_polygon_h`,
  `curved._ground_section`, `curved._ground_chain` and `curved._ground_ring` evaluate `atan2(d[1], d[0])`,
  `(cos θ, sin θ, 0, 0)`, `p[:2]` exactly as today (a 3-term dot product can flip the sign of a zero and with it `atan2`
  by 2π; IEEE arithmetic does not promise bit identity, so the v2 byte-identity is kept by not touching the ground
  path). `shadow._plane_basis` is **not** replaced (nothing needs it). The byte-identity test of §5.1.11 on all 34 v2
  cases is the gate for this claim.
- The ground-specific sites that **must** take the frame for non-ground receivers (enumerated so that none is missed):
  `shadow.shadow_loop` (arc insertion), `shadow._direction_vertex` (last-resort fallback becomes `(e1, 0)`, not
  `(1,0,0,0)`), `shadow._light_foot_from_matrix` (returns `None` for `d ≠ 0`: replaced by passing the light foot `F_r`
  explicitly, `shadow_loop(points4, M, pi, tol, tol_clip=None, frame=None, F=None)`), `curved._ground_section` (sphere
  branch `centre[:2]`, the final `P[:, :2]` centre / size), `curved._ground_chain` (`e[:2]`, `n_[:2]`, the `atan2`
  angles), `curved._ground_ring` (`arctan2` ordering), `curved.shadow_polygon_h` (`atan2(D[1], D[0])` and
  `(cos t, sin t, 0, 0)`), `curved._direction_from` (fallback). A unit test rotates a cylinder-on-a-wall scene so that
  the wall becomes the ground and requires identical polygons (1e-9 m).
- `bounds_functionals(bounds, n) -> Ψ (k, 4)`: row `k` is `ψ_k = (m_k, −m_k·b_k)` with
  **`m_k = n × (b_{k+1} − b_k) / |b_{k+1} − b_k|`** (unit inward normal within the plane for the stored CCW order), so
  that `ψ_k·X = (signed distance to edge k)·w` for a finite `X` and `m_k·d` (dimensionless) for a direction `(d, 0)` —
  the tolerances `tol` / `tol_dir` of §2.8 apply with their proper dimensions. A homogeneous point of the plane is inside
  iff `ψ_k·X ≥ 0` for all `k`; a direction is "inside" iff `m_k·d ≥ 0` for all `k` (for a bounded convex polygon the
  inward normals span the plane positively, so **no** non-zero direction is inside).
- **Default receiver [decision]**: `receivers[0]`. It owns the short point names of §3.1 (`<obj>.v<k>.shadow.<light>`,
  `<obj>.v<k>.foot`, `<obj>.s<k>.<light>`, `F.<light>`) and the flat `construction` keys. Every other receiver `r` appends
  `.<r>` to those names: `<obj>.v<k>.shadow.<light>.<r>`, `<obj>.v<k>.foot.<r>`, `<obj>.s<k>.<light>.<r>`, `F.<light>.<r>`;
  curved construction names likewise (`<obj>.g1.base.shadow.<light>.<r>`). Receiver ids contain no `.`, so the grammar
  of §5.0.4 is unambiguous: a trailing token after `shadow.<light>` or after `foot` is a receiver id.
- **Light side per (light, receiver)**: `πᵀL` with the §2.3 predicates. For the **unbounded** receiver the v1 codes stay
  (`LIGHT_BELOW_RECEIVER`, `DIRECTIONAL_HORIZONTAL`, ids `[light]`). For a **bounded** receiver the three cases (point
  light `π_rᵀL ≤ tol`; directional `|n_r·l| ≤ tol_dir`; directional `n_r·l < −tol_dir`) emit **`RECEIVER_UNLIT`** (ids
  `[light, receiver]`, message naming the case) and the receiver receives nothing from that light: its shadow records
  exist and are empty (as `LIGHT_BELOW_RECEIVER` does today). **The unbounded ground is opaque to light [decision]**: when
  the ground emits `LIGHT_BELOW_RECEIVER` for a light (point light below `z = 0`, or directional `l_z < −tol_dir`), every
  bounded receiver emits `RECEIVER_UNLIT` for that light (message "light below the ground") and no plate casts;
  `DIRECTIONAL_HORIZONTAL` on the ground does **not** propagate (a horizontal sun lights walls). In the
  directional-parallel case `F.<light>.<r>` (a direction point) and `per_receiver[r].shadow_vp(_at_infinity)` are still
  reported, exactly as `DIRECTIONAL_HORIZONTAL` reports `F` for the ground. A receiver is **one-sided for receiving** and
  never auto-flipped **[decision]** (§5.1.9 records this as the one deliberate informational code; the sign-reversal
  alternative is an open question). `receivers[].lit[<light>]` in the document records the outcome.
- **Receivers as occluders / casters [decision]**: a bounded receiver is an opaque plate. It casts a shadow on every
  *other* receiver (§5.1.3.2) whatever side the light is on (`|π_{r'}ᵀL| > tol`; when `|π_{r'}ᵀL| ≤ tol` the plate is
  edge-on and casts nothing; `casts[<light>]` records this), and it is an occluder for the hidden-line test (§5.1.6.2).
  The unbounded ground is an opaque plane: it hides everything on the far side of it from the camera (§5.1.6.2), blocks
  light from below (above) and, because validation keeps bounds above it, never casts.
- `F_r = foot(π_r, L)`, `M_r = shadow_matrix(π_r, L)`, `Q_r = foot(π_r, P)`: the §2.3 formulas with `π_r`, unchanged.
  `F_r` undefined (directional light along `n_r`) follows §2.7 per receiver (`F.<light>.<r>` omitted, `shadow_vp` null
  in `per_receiver`, self-check `S' = Q'_r`).
- Scene scale: bounds vertices are part of the stage-A bounding box (§2.8) — they are scene geometry; the ground has
  none, so v2 scales are unchanged. `tol` below is the stage-A `1e-9·scene_scale_A`.
- Per-(object, receiver) clipped meshes: `obj["clipped"][<receiver id>] = clip_mesh_to_plane(mesh, π_r, tol) | None`
  (None when no vertex is behind `π_r`), computed once per (object, receiver), not per light; `obj["ground_mesh"]` is the
  alias of `obj["clipped"][receivers[0].id]`. (M5 fallback meshes: `None` for every receiver, §5.2.5.)

#### 5.1.3 Shadow records per (light, receiver, caster)
**5.1.3.1 Casters and order.** For each receiver `r` (scene order), for each light (scene order), the casters are the
objects in scene order and then the bounded receivers `r' ≠ r` in scene order. `shadows[]` is emitted in this order, so
the v2 prefix (ground, objects) is unchanged (and, **[decision, synthesis]**, this order also governs multi-light
documents; the M6 design's "object-major, light-minor" wording is superseded, §5.3.2). A record is `{light, receiver,
object: <caster id>, outline, loops, conics, unbounded, polygons, polygon_edges}` (`polygon_edges` is new, §5.1.7). A
caster that is a receiver is recognised by its id being a receiver id (namespaces are disjoint, §5.1.1); no extra key.

**5.1.3.2 The caster's part in front of the receiver.** Before shadowing onto `r` the caster is cut to the half-space
`π_rᵀX ≥ 0` with `obj["clipped"][r]` (objects; fallback `clip_loop_to_plane` as in §2.3) or
`clip_loop_to_plane(bounds, π_r, tol)` (plates). Justification: the light is on the positive side, so a point behind `π_r`
whose ray meets the plate meets it *before* the point and is itself in the plate's shadow; the part behind contributes
no true shadow on `r`. For the unbounded ground this is exactly the §2.3 clip with its `OBJECT_BELOW_RECEIVER` warning
and `s<k>` points. For a **bounded** receiver the clip is **silent** (`OBJECT_BELOW_RECEIVER` is not emitted; being
behind a wall is normal) and the crossings are named `<obj>.s<k>.<light>.<r>` (own shadow and foot, no ray). A caster
wholly behind `π_r` yields an empty record. **Coplanar casters [decision]**: a caster plate whose vertices all satisfy
`|π_rᵀb_k| ≤ tol` (coplanar with `r`, e.g. two coplanar pieces of a composed receiver, a tile lying on the ground, a
two-sided wall given as two coincident plates with normals `±n`) casts nothing on `r` (same status as edge-on; `casts`
stays as computed against the light — the exclusion is per receiver pair, no warning). Without this rule the shadow of
the caster on `r` would be `r' ∩ r` itself, or a zero-area sliver whose vertex count depends on 1e-17 rounding. Plate
loop orientation: the plate's silhouette is its whole boundary; with the light on the positive side the loop is the
stored CCW order (lit face on the left seen from the light, §2.5), with the light on the negative side it is the
reversed order. Plate vertices are named `<r'>.b<k>`; their shadows / feet follow the object grammar
(`<r'>.b<k>.shadow.<light>[.<r>]`, `<r'>.b<k>.foot[.<r>]`) and get construction rays like vertices.

**5.1.3.3 Bounds clip.** `clip_polygon_bounds(points4, sources, psi, bounds, tol) -> (points4', sources')`:
Sutherland–Hodgman of the oriented homogeneous shadow polygon of §2.5/§2.6 (direction vertices and at-infinity arcs
included, built with the receiver frame) against `ψ_k·X ≥ 0` in row order, with the §2.2 interpolation
`(f_a·B − f_b·A)/(f_a − f_b)`, provenance like every other clip of the contract, and these rules:
1. **Band [decision]**: with `f_i = ψ_k·X_i`, a vertex is kept iff `f_i ≥ −tol·|w_i|` — a signed-distance band of `tol`
   for finite vertices (any `w > 0`, no division) and **strict `≥ 0` for directions** (`w = 0` exactly by construction,
   §2.5). A kept vertex inside its band (`|f_i| ≤ tol·|w_i|`) is its own crossing: no crossing is inserted next to it
   (the `clip_loop_to_plane` rule), so a shadow vertex lying exactly on a plate edge (a fold point, a cut-face vertex on
   `z = 0` of a crate straddling the wall) keeps its name and no duplicate `s<k>` point appears (Python and the TS port
   must agree on list lengths and names).
2. Crossings get the source `("bounds", k, src_a, src_b)`; interpolations that give the zero vector (antipodal
   directions) are dropped as in `clip_polygon_halfspace`.
3. **Anchor rule [decision]** (exactness for arcs at infinity spanning ≥ 180°: concave prisms with the light in the
   notch, M5 meshes, a half-plane shadow with directions parallel to a plate edge — verified counter-examples where the
   plain clip returns *empty* for a fully shadowed plate): after the step for row `k`, whenever two consecutive output
   vertices `D_a`, `D_b` are both directions on the clip line (`w = 0`, `|ψ_k·D| ≤ 1e-9·max|D|`) and antipodal
   (`d_a·d_b < 0`), the finite anchor `(b_k, 1)` (the clip edge's own start vertex, which lies on that line) is inserted
   between them with source `("bounds", k, "anchor")`: the path `D_a → b_k → D_b` is the whole clip line traversed with
   the half-plane on its left (for the exit direction `d_a = n × m_k` and entry `d_b = −d_a` this is exactly the
   orientation Sutherland–Hodgman requires), so the later rows generate the plate corners. For a convex caster the
   recession cone is < 180°, no antipodal pair occurs and the rule is never triggered.
4. "Fewer than three vertices ⇒ empty, stop" after any row, as `clip_polygon_rect_h`.
5. After the last row: consecutive projectively equal vertices (max-abs difference ≤ 1e-9 after `normalize_max`) are
   merged keeping the first (the anchor may coincide with a later corner crossing); any vertex with `w ≤ 0` is dropped
   (cannot occur under §5.1.1 rule 3; no warning); a result whose `(e1, e2)` area satisfies `|area| ≤ tol·perimeter` (a
   sliver of width ≤ tol) is empty.
A bounded convex polygon contains no point at infinity, so every surviving vertex has `w > 0`: **for a bounded receiver
`unbounded` is always `false`** and `VERTEX_NOT_BELOW_LIGHT` is **not emitted** (the direction vertices are an
intermediate that the bounds remove; a vertex farther from a wall than the lamp is ordinary) **[decision]**. The
crossings and anchors are named `<obj>.s<k>.<light>.<r>` in order of first appearance, continuing the series of
§5.1.3.2 (one `s` counter per (caster, light, receiver)); they lie on `r`, are their own shadow and foot and get no ray;
`_loop_entries` (pipeline and curved) name `("bounds", …)` rows as ground points of the receiver. The named shadow points
`<obj>.v<k>.shadow.<light>.<r>` of finite silhouette vertices are emitted even when they fall outside the bounds (they
are genuine points of the plane, a painter extends the plate to them); construction rays and self-checks are produced
only for vertices whose `S_r` satisfies `ψ_k·S_r ≥ −tol·w_S` for all `k` (inside the plate) **[decision]**. Empty result
after the clip (shadow misses the plate) is normal: no warning, empty `polygons`.

**5.1.3.4 Fold (轉折影) [decision].** No shadow is ever clipped or subtracted by another receiver. The fold at the
intersection line of two receivers arises by itself: for a silhouette vertex `P`, `M_rP` lies on `π_{r'}` iff the ray
`L→P` meets the line `π_r ∩ π_{r'}` iff `M_{r'}P` is the same point; hence the bounds-clip crossings of the wall polygon
(its bottom edge for a wall standing on the ground) coincide, point for point, with the crossings of the ground
polygon's edges with the wall's base line. The ground polygon continues behind the plate: where the ray from `L` through
the ground point crosses the plate, that point lies inside the plate's own ground shadow (the union of per-caster shadows
under `nonzero` is the correct dark region, exactly as overlapping shadows of two objects are today) and is hidden from
the camera by the plate when hidden lines are on; where the ray clears the plate (a tall object behind a low wall) the
continuation is **genuine shadow** and is correctly drawn. In both cases the per-caster *outline* may run through the
interior of another caster's region; merging outlines is the M6 疊影規則 (M6 draws per-light regions and the umbra and
does not merge outlines either, §5.3.1; left open). Spec §9 "交線處自然轉折" is satisfied by construction; the acceptance
test (§5.1.11) checks the two crossing sets agree to 1e-9 m and match the hand computation.

#### 5.1.4 Curved objects per receiver (§2.6 generalised)
`curved.stage_a_object(obj, lights, receiver, tol, warnings)` is called once per receiver with `π_r`, its frame and `Ψ`;
results live in `obj["curved"][<receiver id>][<light id>]`. `shadow_outline` / `_ground_section` / `_ground_chain` /
`_ground_ring` / `shadow_polygon_h` / `plane_min` take `frame=(e1, e2) | None` and use the receiver-frame coordinates at
every site enumerated in §5.1.2 (ground: literal v2 code). Bounds clipping of conic pieces is **closed form in stage A**:
each `ψ_k` gives `ψ_k·X(θ) = A cos θ + B sin θ + C` (`conics.functional_coeffs(ψ_k, T·E, ρ)` with `T = M_r`) and the
surviving sub-arcs are `sub_arcs_where_nonnegative(A, B, C, θ0, θ1, tol)`; a piece may split into several pieces, each
with its own `arc`, exactly like the `w_S` clip. Segment pieces and the sampled polygon (`shadow_polygon_h`, built in the
receiver frame) go through `clip_polygon_bounds` (anchor rule included: a buried cylinder's unbounded shadow can span
≥ 180°). The cut points are named `<obj>.s<k>.<light>.<r>`. For bounded receivers the curved `VERTEX_NOT_BELOW_LIGHT` /
`OBJECT_BELOW_RECEIVER` warnings are dropped (§5.1.3.2–§5.1.3.3); `LIGHT_INSIDE_OBJECT`, `FACE_PARALLEL_TO_LIGHT`,
`CONIC_SAMPLED` are receiver independent and emitted once. (M6: the signature gains `multi=False`, §5.3.2.)

#### 5.1.5 Construction per receiver (§2.7 generalised)
`L'` is shared. Per receiver `r`: `F'_r = P·F_r` (plain division, never nulled); `|x̃3(F'_r)| ≤ tol` ⇒
`SHADOW_VP_AT_INFINITY` with ids `[light]` for the default receiver (v2 `(code, ids)` sets unchanged) and
**`[light, receiver]` for every other receiver** (degeneracies warn; the ids grammar is not per light — `RECEIVER_UNLIT`
already carries a receiver id), the at-infinity form going to `construction.per_receiver[r].shadow_vp_at_infinity`. Rays
`L'P'` covering `L'`, `P'`, `S'_r`; `F'_rQ'_r` covering `F'_r`, `Q'_r`, `S'_r`; the perpendicular `P'Q'_r` (kind `"PQ"`,
along `n_r`); self-check `S'_check = (L'×P') × (F'_r×Q'_r)` against `S'_r` with the §2.7 skip rules. Rays and checks
exist only for vertices with `ν(P), ν(S_r), ν(Q_r) ≥ 0` and `S_r` inside the bounds (§5.1.3.3). The default receiver's
rays / checks / segments stay in the flat `construction.rays / checks / segments`; every other receiver's go to
`construction.per_receiver[<r>]` (§5.1.7; in a multi-light document inside `constructions[<light>]`, §5.3.5).

#### 5.1.6 Sampled hidden-line removal (隱藏線消除)
**5.1.6.1 Subjects** (the drawables that get `visibility` / `runs`): `edges[]` (object edges and receiver bounds edges,
incl. back edges — `back` stays the face-based flag, `visibility` the sampled one), `outlines[].generators[]`,
`outlines[].conics[]` (cap arcs, sphere circle), `form_shadow[].terminator[]` (conics and generator segments),
`shadows[].conics[]` and the drawn edges of `shadows[].polygons` (`polygon_edges`) that lie on an original outline edge
(§5.1.6.4: edges created by the near clip or the rectangle clip, and edges whose both endpoints are directions — drawn
horizon segments — are clipping artefacts, **not subjects**: `"visible"`, `runs: []`). **Overlays, never hidden**:
`construction.*` (and `constructions.*`), `horizon`, vanishing points, `L'`, `F'`, labels. **Regions, not subject**: the
fills of `shadows[].polygons`, `form_shadow[].polygons`, `form_shadow_core` and `umbra[].polygons` (lines only; spec §9
names edges and shadow outlines).

**5.1.6.2 Occluders** (`castplane/hidden.py`, exact, camera-free input from `A`): `occluder(obj_or_receiver) -> dict`
dispatches on `type`: box (slab test in the local frame), prism (every side quad as ray–plane + point-in-quad, caps with
point-in-polygon — valid for concave prisms), cylinder / cone (lateral quadric with the height range + discs), sphere
(quadric) — the same mathematics as `tests/reference/raycast.py`, re-implemented in the core (the reference shares no
code); **any other kind** (the M5 `mesh` kind, and any future kind) uses the generic closed-mesh occluder: ray–plane per
face + point-in-polygon in the face plane, built — **[decision, synthesis]** — from `rec["triangles"]` on the welded
vertices when the record carries that key (every M5 mesh record, manifold or fallback: the original triangulated surface,
never the merged polygons, §5.2.7) and otherwise from `obj["mesh"]` (contract §2.4 guarantees `vertices`, `faces`,
`face_normals` for every kind). **Nothing raises**; M5 needs no change in `hidden.py` (a BVH is an optional
result-identical optimisation). Every bounded receiver is an opaque convex plate (ray–plane `t_p`, then `ψ_k·(X_p, 1) ≥ 0`
for all `k`); the unbounded ground is an opaque plane (crossing at `t = C_z/(C_z − X_z)` when `C_z` and `X_z` have
different signs). No ground receiver ⇒ no ground occluder. Interface: `first_hit(occ, O (n,3), D (n,3), eps) ->
t_first (n,)`: the smallest boundary-crossing parameter `t > eps` of the rays `O + t·D` (`inf` when none) — identical to
the reference hitters with `T_EPS = eps`.

**5.1.6.3 Predicate.** A world point `X` (finite) is `occluded(X)` iff for some occluder
`first_hit(occ, C, X − C, ε_t) < 1 − ε_t`, `ε_t = HLR_RAY_EPS = 1e-5` (relative to the ray length) **[decision]** (a
classification band for a sampled method, deliberately coarser than spec §5.8's `1e-9 · scene scale`, which stays the
tolerance of every geometric predicate; D26). This is the "some
boundary crossing in the open interval `(ε_t, 1 − ε_t)`" rule: a point on the front surface of its own object (first
crossing `t = 1` up to rounding, e.g. a tangent generator, a sphere silhouette point where the quadratic has a double
root) is **not** occluded, a point on a back edge (first crossing `< 1 − ε_t`) is, a point in the notch of a concave
prism reached without crossing an arm is not, a camera inside a solid sees nothing (the exit crossing is `< 1 − ε_t`).
No object is excluded from occluding its own drawables.

**5.1.6.4 Sampling and bisection (deterministic).** Constants: `HLR_SPACING_MM = 1.0`, `HLR_MIN_SAMPLES = 8`,
`HLR_MAX_SAMPLES = 4096`, `HLR_BISECTIONS = 6`, `HLR_RAY_EPS = 1e-5`. Each subject is a curve parametrised by a
parameter `p ∈ [p0, p1]` with an image length `ℓ` (mm):
* **Straight drawables**: `p = s ∈ [0, 1]`, the image fraction along the drawn segment `a → b`;
  `ℓ = sqrt(du² + dv²)` (written exactly so; not `hypot`/`norm`). The 3-D test point is `X(t)/w` with the 4-D
  parameter `t(s) = s·ã₃ / ((1 − s)·b̃₃ + s·ã₃)` and `X(t) = (1 − t)A + tB`, where `A, B` are the **4-D endpoints of
  the drawn segment**, recomputed by `hidden.drawn_segment_4d(cam, A4, B4)` from the stage-A world endpoints: near clip
  (`ν ≥ 0`) then the four rectangle functionals **evaluated on `P·X`** (`rect_row · (P·X)`, the same floats as the 2-D
  clip, hence the same interpolation parameters); `ã = P·A`, `b̃ = P·B` equal the drawn endpoints up to one rounding of
  `P·X` (≈ 1e-12 mm, irrelevant at the HLR tolerance; the drawn `segment` itself stays the v2 value). An endpoint may be
  a direction (`w = 0`, a vanishing point inside the extended canvas): `b̃₃ = forward·d > 0` and `w(t) = (1 − t)·w_A > 0`
  at every sample because midpoints have `t < 1`; implementations and the TS port must handle `w = 0` endpoints. For
  `shadows[].polygons` the 4-D polygon of §2.5 goes through the near clip and the 4-D rectangle clip with provenance
  (`hidden.clip_polygon_4d`): every output vertex carries the index of the original edge its *outgoing* drawn edge lies
  on, or `None` for an edge created by a clip (a crossing-out vertex starts a clip edge; a crossing-in vertex continues
  the original edge); the drawn polygon's edge `j` is a subject iff its id is not `None` and not both endpoints are
  directions. When the 4-D path's vertex count differs from the drawn polygon's (possible only in the zero-vector
  filter's rounding band), the polygon's edges are all `"visible"`, `runs: []`.
* **Conics**: `p = m ∈ [0, ℓ_k]`, the cumulative length (mm) along the §2.6 polyline of **visible interval `k`**
  (`conics.sample_count` samples; the `visible` list itself is unchanged by the switch); `θ(m)` is piecewise linear on
  that polyline, `X(θ) = T·E·(ρ cos θ, ρ sin θ, 1)` (`T = M_r` for shadow conics, `I` for image conics; `w > 0` on every
  drawn interval). Each visible interval is classified separately. Parametrising by length makes samples uniform in mm
  (a hyperbola branch's polyline steps are very non-uniform in θ).
* `N = min(HLR_MAX_SAMPLES, max(HLR_MIN_SAMPLES, ceil(ℓ / HLR_SPACING_MM − 1e-9)))` samples at
  `p_i = p0 + (p1 − p0)·(i + ½)/N`, `i = 0..N−1` (midpoints: endpoints are shared vertices and ambiguous);
  `hlr_sample_count(length_mm)`. State `v_i = not occluded(X(p_i))`. All equal ⇒ `visibility` is `"visible"` /
  `"hidden"`, `runs = []`. Otherwise for every `i` with `v_i ≠ v_{i+1}` bisect `[lo, hi] = [p_i, p_{i+1}]` exactly 6
  times: evaluate the midpoint `m`; **if `v(m) ≠ v(lo)` keep `[lo, m]`, else keep `[m, hi]`** (one evaluation per step,
  deterministic even when the state crosses several times inside the bracket); the boundary is the midpoint of the final
  bracket (width `(p1 − p0)/(64N)`). **Stated tolerance** `HLR_TOL_MM(ℓ) = max(1/64, ℓ/262144) mm`, i.e. ≤ 0.016 mm for
  `ℓ ≤ 4096 mm` (the extended diagonal of an A0 canvas is ≈ 2.2 m). `visibility = "partial"`, `runs` = the consecutive
  runs from `p0` to `p1` with the state of their samples; the state of the first / last sample extends to the endpoints.
* Image-space culling by each occluder's projected bounding rectangle and depth range (`image_bounds(occ, cam)`) is
  permitted and must not change any result: it is computed from the occluder's extremal points (vertices; sphere /
  cylinder / cone extremal points) and returns "no cull" whenever any extremal point has `ν ≤ 0`. A test compares culled
  and unculled runs on 5 scenes.

**5.1.6.5 Where it runs [decision].** Stage C: `compose(scene, B, hidden_lines=None)` builds the document as in v2 and
then, when the switch is on, calls `hidden.classify_document(doc, A, B)` (`A` reached through `B["A"]`, camera-free
occluder geometry; `cam = B["camera"]`), which fills `visibility` / `runs` / `polygon_edges` / conic `runs` +
`hidden_polylines` and restricts conic `arcs` / `ellipses` / `polylines` to the visible runs. It writes nothing into `A`
or `B`; every list it assigns is a **fresh** object (the `edge_templates` of §2.4 are shared by reference and carry
`runs: []` — HLR never `extend`s them). §2.6's sampling rule gains a third site **(c)**: the §2.6 polyline of a conic
drawable (sampled once in `_arc_drawables`) is reused as the HLR parametrisation and `hidden_polylines` are cut from it —
all in stage C, nothing in stage A/B. Occluders are light independent, so a multi-light document (§5.3) classifies every
light's shadow records with the same occluder set.

**5.1.6.6 Switch and defaults [decision].** `output.hidden_lines` default `false`: spec §9 says v1 marks everything
visible and M4 *fills the field by sampling*, not that the filling is on by default; spec §8's targets are stated for the
off configuration (單光源單受影面) and remain the CI gate; the painter's overlay workflow frequently wants every line; and
off keeps every v2 scene's SVG byte-identical. API: `render(scene, camera=None, hidden_lines=None, hidden_style=None)`
(`None` = the scene's `output` values; §5.0.7 adds M6's `umbra=True`); the CLI gets `--hidden-lines` /
`--no-hidden-lines` and `--hidden-style dashed|omit` and passes them to `render` (it does not rewrite the scene). The
document carries the effective switch as top-level `hidden_lines: bool`. With the switch off every `visibility` is
`"visible"`, every `runs` / `hidden_polylines` is `[]`, `polygon_edges` is `[]` (meaning "all visible") and no occluder
is built. **Cost**: `benchmarks/bench.py --hidden-lines` times the spec §8 scene with the switch on (informational, soft
target < 5 s on the CI container) and the table also records the switch-off full render and JSON size **before and
after** M4 (the added keys are the only cost); the hard gate stays `--gate full` with the switch off.

#### 5.1.7 Document format (§3.1 amendment; the full listing is §5.0.3)
```
hidden_lines bool                                                     -- the effective switch
receivers [{id, plane: [nx, ny, nz, d], bounds: [[x,y,z], ...] | null,
            lit: {<light>: bool}, casts: {<light>: bool}}]             -- scene order; receivers[0] = default
points    + "<r>.b<k>" {world, image|null, depth}; the ".<receiver>" suffixed names of §5.1.2
edges     + entries with object == <receiver id> (from/to "<r>.b<k>", silhouette = casts[<light>] (OR over lights),
            back: false); every entry gains runs: [...]
shadows   [... + polygon_edges: [[run record per drawn polygon edge], ...]]   -- parallel to polygons when on, [] when off
outlines  [{object, generators: [{from, to, back, segment, visibility, runs}], conics: [conic entry]}]
form_shadow[].terminator: conic entries | {segment, polylines, visibility, runs}
construction + per_receiver: {<r>: {shadow_vp, shadow_vp_at_infinity, rays, checks, segments}}  -- r ≠ receivers[0]
conic entry + visibility, runs: [{interval: k, theta: [a, b], mm: [m0, m1], visible: bool}],
              hidden_polylines: [[[u,v],...], ...]
run record (straight): {visibility: "visible"|"hidden"|"partial",
                        runs: [{s: [s0, s1], t: [t0, t1], mm: [m0, m1], visible: bool}, ...]}
```
Rules: `runs` is non-empty **only** for `"partial"`; straight runs are ordered, contiguous from 0 to 1, alternating
`visible`, `mm` measured along the drawn segment from its start; conic runs are grouped by `interval` (the index into
`visible`, in order; an **integer**, listed in `INT_KEYS`), contiguous from 0 to the polyline length of that interval and
alternating within it, `theta` obtained from `mm` by the piecewise-linear map of §5.1.6.4; a drawable with
`segment: null` / empty `visible` keeps `"visible"`, `runs: []`. With hidden lines on, a conic entry's `arcs` /
`ellipses` / `polylines` cover its **visible** runs only (a partly hidden full circle becomes `arcs`, never `ellipses`;
sampled polylines are cut at the boundary points, not resampled) and `hidden_polylines` holds the hidden runs cut from
the same polyline; off, they are as in v2 and `hidden_polylines: []`. `shadows[].conics` of a bounded receiver carry
`map: "shadow"` with `T = M_r`. Point names: `<r>.b<k>` are labelled (`b<k>`, receiver id bold at the highest one); **any
name with a part equal to `shadow` or `foot` is unlabelled** (the receiver suffix may follow `foot`; `svg._is_labelled` /
`_layer_labels` prefilter with `".foot" in name`); `L.<light>` and `F.<light>[.<r>]` go through the L/F branch regardless
of the rest and never set an object's top label. The horizon and `camera.horizon_line` remain the ground's line at
infinity (eye level) whether or not a ground receiver exists. `stages` (CLI) serialises `A["receivers"]` /
`per_receiver` with `geometry_json.dumps` (frames and `Ψ` as lists).

#### 5.1.8 SVG (§2.10 amendment; the unified sub-group order is §5.0.6)
- Receiver bounds edges are drawn in `objects` as `objects.<r>` / `objects.<r>.front` (they are `edges[]`). Plate shadows
  are paths in `cast_shadow.<light>` like object shadows. A plate's unlit camera-facing face is a `form_shadow` entry
  `{object: <r>, faces: [[<r>.b<k> ...]], polygons, terminator: []}` iff `sign(πᵀL) ≠ sign(n·(C − b₀))` with both
  strictly beyond `tol` (the camera sees the face the light does not reach; the light-side sign is stage A, the camera-side
  sign and hence the entry's existence are decided in stage B like `back`, so §5.0.3 lists plate entries as camera
  dependent); under M6 the entry is per light and a
  plate whose camera-facing face is unlit by every light gets a `form_shadow_core` entry (a plate is a one-face
  polyhedron for §5.3.3) **[decision, synthesis]**.
- With `hidden_lines == false` the SVG is **byte-identical to v2** for every v2 scene (golden hashes).
- With it `true`: a visible run is drawn in the drawable's normal group (edges: `.front` / `.back` by the `back` flag;
  conics: normal drawables), split at the run boundaries (`segment[0] + s·(segment[1] − segment[0])`); hidden runs go to
  one sub-group per layer written **first** in the layer, `objects.hidden` (sub-groups `objects.hidden.<id>`),
  `form_shadow.hidden` (`form_shadow.hidden.<id>`), `cast_shadow.hidden` (`cast_shadow.hidden.<light>`), style
  `stroke-width="0.15" stroke-dasharray="0.5 0.5" fill="none"` with the layer's stroke colour (`#111`, `#335`, `#000`).
  `hidden_style == "omit"` writes those groups empty (ids kept, nothing drawn) — true hidden-line removal. Cast-shadow
  paths are then written `stroke="none"` and their outline runs stroked in `cast_shadow.<light>.<object>.outline`
  (`cast_shadow.<light>.<object>.<r>.outline` for a record on a receiver `r` other than `receivers[0]`, like the
  `.conics` groups — M4 implementation note "ids with several receivers", final review docs-contract#5;
  `stroke="#000" stroke-width="0.25"`); the fill is unchanged (regions are not subject, §5.1.6.1).
  `write_svg(doc, layers=None, hidden_style="dashed")`; the hidden groups exist iff `doc["hidden_lines"]` is true.

#### 5.1.9 Warning codes (§2.9 amendment: the closed list grows by one; the table is in §5.0.5)
`RECEIVER_UNLIT` (ids `[light, receiver]`) is the **one deliberate informational code** of the list **[decision]**: a wall
lit from behind is not degenerate (only the band cases are), but an inverted normal is the most likely user error and
`receivers[].lit` alone is easy to miss. Changed scope of existing codes: `LIGHT_BELOW_RECEIVER`, `DIRECTIONAL_HORIZONTAL`,
`VERTEX_NOT_BELOW_LIGHT`, `OBJECT_BELOW_RECEIVER` apply to the **unbounded** receiver only; `POINT_BEHIND_CAMERA` ids may
be a receiver id (its `b<k>` / shadow / foot points); `CONSTRUCTION_CHECK_SKIPPED` ids carry the suffixed names;
`SHADOW_VP_AT_INFINITY` ids are `[light]` for the default receiver and `[light, receiver]` otherwise. No code for "shadow
misses the plate", "object behind a plate", "edge-on plate", "coplanar caster" or any HLR situation: none is degenerate.
`RECEIVER_UNLIT` is appended at the **end** of `WARNING_CODES` (M5 appends after it).

#### 5.1.10 Numerics, determinism, portability
`tol` / `tol_dir` as §2.8 (bounds vertices in the stage-A bbox). All clips are the §2.2 interpolation; all predicates
`> tol` / `< −tol` (bounds clip: the band of §5.1.3.3). HLR constants are fixed by this contract; sample counts derive
from drawn lengths with the stated `ceil`; bisection is a fixed 6 steps with the stated half selection; all occluder
tests are closed form; no reductions over variable-length axes beyond `min` / `any` of hit masks (order independent).
Everything is derivable from the scene JSON by a TypeScript port (the §2.2 camera, the per-kind ray tests, the generic
mesh occluder, the constants above); no document field needs a loader.

#### 5.1.11 Testing contract (§4 amendment)
- **Conformance set** (the version sequence is §5.0.8: M4's full regeneration is **v4**, run once on `main` at the M4
  merge; `tools/regen_conformance.py --reason …`): the 34 v2 cases are regenerated **key-additively** — the new keys
  `hidden_lines`, `receivers`, `construction.per_receiver`, `edges[].runs`, generator / terminator `visibility` + `runs`,
  conic `visibility` / `runs` / `hidden_polylines`, `shadows[].polygon_edges` are added with their switch-off values and
  **no existing number, name, string, boolean or warning changes**. The regen tool gains `--strip-new-keys` (dry run:
  render, delete exactly those keys, compare with the committed expected files by the spec §7.5 comparator — must
  report zero mismatches) and the v4 changelog entry records that this check passed. **The full-set regeneration is run
  once, on the merged branch** (never inside the M4 or M5 worktree; each worktree adds only its own cases with
  `--case`). New cases: `wall_and_ground` (below; switch off), `wall_and_ground_hidden` (same, switch on),
  `receiver_unlit_wall` (light behind the wall → `RECEIVER_UNLIT`), `receiver_directional_wall` (directional light,
  `F.sun.wall` at infinity, `SHADOW_VP_AT_INFINITY` ids `[sun, wall]`), `fold_curved_cylinder` (cylinder shadow folding
  onto a wall: conic bounds clip), `bounded_default_receiver` (no ground; `receivers[0]` is a plate),
  `hidden_lines_curved_unbounded` (sphere + cylinder, an unbounded ground shadow, switch on), `hidden_lines_vp_in_canvas`
  (`degenerate_vertex_above_point_light` with the switch on: a polygon vertex on the horizon inside the extended canvas,
  `w = 0` endpoint), `concave_prism_on_plate` (U-prism with the lamp in the notch on a bounded floor plate: the anchor
  rule; expected polygon = the whole plate). Comparator additions (`tests/conformance/rules.json`, §5.0.8): inside any
  `runs` entry, `mm` within **0.05 mm** absolute, `s` / `t` / `theta` within 1e-3 absolute, `visible`, `interval` and
  the run count exact; `hidden_polylines` under the 1e-6 mm image rule; `receivers[].plane` / `bounds` under 1e-9 rel.
- **Hand-computed acceptance case `wall_and_ground`** (spec §10 M4): ground `receivers[0]`; wall `{id: "wall",
  normal: [0,−1,0], offset: 6, bounds: [[−3,6,0],[3,6,0],[3,6,2.5],[−3,6,2.5]]}`; `crate` box size `[1,1,1]` at
  `(0, 4.5, 0)`; point light `lamp` at `(0, 2, 3)`; camera `(0, −1, 1.6) → (0, 6, 0.8)`, `f = 35`, frame `36×24`,
  canvas `273×182`. Expected (exact): `F.lamp = (0,2,0)`, `F.lamp.wall = (0,6,3)`; lit faces of the crate are front (−y)
  and top, silhouette loop `v0 v1 v5 v6 v7 v4`; ground shadow: `crate.v5.shadow.lamp = (0.75, 5, 0)`, `v6 → (0.75, 6.5, 0)`,
  `v7 → (−0.75, 6.5, 0)`, `v4 → (−0.75, 5, 0)`, `v0`, `v1` their own `(∓0.5, 4, 0)`; wall shadow points
  `crate.v6.shadow.lamp.wall = (2/3, 6, 1/3)`, `v7 → (−2/3, 6, 1/3)`, `v5 → (1, 6, −1)`, `v4 → (−1, 6, −1)`,
  `v0 → (−1, 6, −3)`, `v1 → (1, 6, −3)`; the wall polygon after the bounds clip is the quadrilateral `(0.75, 6, 0)`
  (`crate.s0.lamp.wall`), `(2/3, 6, 1/3)`, `(−2/3, 6, 1/3)`, `(−0.75, 6, 0)` (`crate.s1.lamp.wall`); the **fold** points
  `(±3/4, 6, 0)` equal the crossings of the ground loop edges `(0.75,5)→(0.75,6.5)` and `(−0.75,6.5)→(−0.75,5)` with
  `y = 6` (test: 1e-9 m both ways and against the literals); the wall's own ground shadow has vertices `(±3, 6, 0)`
  (`wall.b0/b1.shadow.lamp`, band-kept, no `OBJECT_BELOW_RECEIVER`), `(18, 26, 0)`, `(−18, 26, 0)`. Images (1e-6 mm,
  verified): `wall.b0' = (−111.5758137, −29.5611244)`, `b1' = (111.5758137, −29.5611244)`,
  `b2' = (116.1978441, 65.4196009)`, `b3' = (−116.1978441, 65.4196009)`, fold `(±27.8939534, −29.5611244)`, wall tops
  `(±24.9268280, −17.3359326)`, `L' = (0, 162.8814554)`, `F'_wall = (0, 85.3679337)`, `F'_ground = (0, −104.8324357)`;
  warnings `[]`. **Hidden-line part** (`wall_and_ground_hidden`): the wall base edge `wall.b0 → wall.b1` is `"partial"`
  with one hidden run `x ∈ (−0.7, 0.7)` (the rays through the crate's front face `y = 4` at `t = 5/7` satisfy
  `|x|·5/7 ≤ 0.5`): the edge is picture-plane parallel so `s = t = (x + 3)/6` exactly, runs `s ∈ [0, 23/60]` visible,
  `[23/60, 37/60]` hidden, `[37/60, 1]` visible, `mm` boundaries `85.5415` and `137.6102` of `ℓ = 223.1516` (tolerance
  0.05 mm); the ground shadow edge `(0.75,5,0)→(0.75,6.5,0)` is hidden by the plate beyond `y = 6`, boundary at image
  fraction `s = 0.713073` (`t = 2/3` in 4-D; within 1e-3), whose image is the fold point `(27.8939534, −29.5611244)`; the
  crate's camera-facing faces are top and front, so its **five** back edges `v0–v3, v1–v2, v2–v3, v2–v6, v3–v7` are
  `"hidden"` (the two bottom side edges by the front face at `z ≈ 0.145`) and its **seven** front edges
  `v0–v1, v0–v4, v1–v5, v4–v5, v4–v7, v5–v6, v6–v7` (`v6–v7` is the top-back edge) are `"visible"`; the wall top edge is
  `"visible"`.
- **Reference depth comparison** (`tests/reference/zbuffer.py`, shares no code with castplane; re-implements §2.2 from
  the spec like `raycast.py` does the placement): a per-pixel ray-cast depth buffer over the extended canvas at
  `0.1 mm/px` (nearest `t` over objects via `first_hit_t` versions of the raycast hitters, plates, the ground), depth =
  camera-space `x̃₃` for both the buffer and the sample. The reference is **three-valued**: `hidden_at(Z, (u, v), depth)`
  returns `True` when `Z[px] < depth·(1 − 0.02)`, `False` when `Z[px] > depth·(1 + 0.02)`, and **`None` (undecided)**
  inside the band (a grazing occluder such as the crate's front face at `t_in = 5/(y+1) > 0.98` over the first 1.68 mm of
  edge `v1–v2` is in that band). `tests/test_hidden.py` checks, for every run of every subject drawable of the M4 cases
  and of 20 seeded random scenes with 1–6 objects and 0–2 plates: samples every 0.5 mm along the run excluding 0.3 mm at
  each end agree with the buffer for ≥ 99 % of the **decided** samples per document and for **100 % of the decided
  samples on `edges[]` of boxes / prisms** (no silhouette ambiguity there); every run boundary agrees with the point-wise
  raycast reference at ±0.15 mm along the drawable (≥ 98 % of boundaries). The 2 % depth band and the 0.3 mm end margin
  are the documented limits of the reference (silhouette pixels, grazing occluders).
- **Invariants**: spec §7.1 rows 1–6 re-run on `wall_and_ground` and `fold_curved_cylinder` (row 2: all receivers' shadow
  points camera independent; row 4: rigid motions of the ground's symmetry group applied to bounds too); frame
  equivalence: a cylinder / sphere on a wall with the lamp below the top, compared with the scene rotated so that the
  wall becomes the ground (polygons equal within 1e-9 m); `test_degenerate.py` gains `RECEIVER_UNLIT` (four predicates
  incl. the light below the ground), a plate edge-on to the light, a plate seen edge-on by the camera, a light exactly
  in a plate's plane, a crate straddling the wall plane (silent clip, `s<k>` names, no duplicate at `z = 0`), a coplanar
  caster (casts nothing), the directional light along the wall normal (`F.sun.wall` absent); `test_raycast.py` (spec
  §7.3) extends the IoU gate to bounded receivers: the mask on receiver `r` is the union of per-caster masks rasterised
  in `(e1, e2)` and compared with `raycast.occluded` from receiver samples, plates added as hitters (IoU ≥ 0.99);
  bounds-clip unit tests: the 270° U-prism polygon and the half-plane polygon on the `[−3,3]×[0,2.5]` plate both return
  the full plate (area 15, four vertices after merging), a bounded square, a < 180° wedge, a polygon wholly outside
  (empty), a direction nearly parallel to an edge (removed); determinism: render twice with hidden lines on, byte-equal
  JSON and SVG; `test_cli.py`: the new flags; `test_bench.py`: the `--hidden-lines` row and the before/after switch-off
  rows exist. The full M4 test plan (validation rows, receiver / fold tests, `test_hidden.py` unit tests incl. the `N`
  table `ℓ = 0.1, 7.3, 8.0, 1023.9, 4095.9, 5000 mm → 8, 8, 8, 1024, 4096, 4096` and `ℓ = 10.0 → 10`, the `w = 0`
  endpoint case, SVG structure, labels) is binding as written in `docs/PLAN-v2.md` §M4.

#### 5.1.12 Shared files with M5 (parallel worktrees)
Both milestones touch `scene.py`, `errors.py`, `cli.py`, `pipeline.py`, `tests/reference/raycast.py`,
`tests/test_scene.py`, `test_cli.py`, `test_degenerate.py`, `test_conformance.py`, the conformance set, `docs/*`,
`benchmarks/*`. M4 confines its edits in them to **appended blocks**: `validate_bounds` / `validate_hidden_output`
appended to `scene.py` and called from one new line each in `validate_receiver` / `validate_output`; `RECEIVER_UNLIT`
appended at the end of `WARNING_CODES`; CLI arguments in one block; in `pipeline.py` the `_object_light_data` /
`build_object` call sites (M5's hook points) stay untouched and the receiver loop lives in new helpers
(`_receiver_record`, `_plate_record`, `_shadow_records_for_receiver`); `raycast.py` gains `first_hit_t` variants and
`hit_plate` / `hit_ground` as new functions. `hidden.py`, `zbuffer.py` are M4-only. The v4 regeneration happens once on
the merged branch (M5's `mesh` kind works with M4's `hidden.occluder` fallback without edits). The file lists per
worktree and the merge rule are in `docs/PLAN-v2.md`.

### Implementation notes
- **[decision, implementation] (M4 A-track) Own-crossing band of a direction in the bounds clip.** In
  `shadow.clip_polygon_bounds` a kept direction vertex (`ψ_k·D >= 0`, strict as §5.1.3.3 rule 1 says) is its own
  crossing when `|ψ_k·D| <= 1e-9·max|D|` — the anchor rule's "on the clip line" test of rule 3 — instead of only when
  `ψ_k·D == 0`. A direction exactly parallel to a plate edge evaluates to ~1e-16 after rounding (`sin π`, a
  `_direction_vertex` interpolation); with the literal band the crossing inserted next to it is a finite point at
  ~1e16 m that defeats the anchor rule (the 270° wedge unit test returned the empty set instead of the plate). List
  lengths and names only change in that rounding band; the TypeScript port must use the same test.
- **[decision, implementation] (M4) Pre-v4 expected files inside the worktree.** Until the one v4 regeneration on the
  merged branch (§5.0.8 rule 2), `tests/test_conformance.py::test_render_matches_expected` compares a case whose
  expected file has no `hidden_lines` key after `tools/regen_conformance.py::strip_new_keys` (which also fails when a
  stripped key does not carry its switch-off value), and `test_regen_tool_exit_codes_match_its_docstring` accepts
  `--dry-run` drift of such cases only when they pass after stripping. Both bridges are inert once the expected files
  carry the M4 keys. `tests/test_receivers.py` additionally requires, on the recorded NumPy build, the stripped JSON to
  be **byte-identical** to the expected file and the SVG to match `tests/golden/v2_svg_sha256.json` (the v2 writer's
  output hashed before M4) for all 34 v2 cases.
- **[decision, implementation] (M4) Frame equivalence for the sphere.** The sphere's silhouette-circle frame is
  `e1 = normalize(n × z)` with the world `z` (§2.6), which a rotation that moves `z` (wall → floor) does not carry
  along: the 64 polygon samples start at another point of the same exact curve. The frame-equivalence test of §5.1.11
  therefore compares the box and cylinder polygons vertex by vertex (names identical, 1e-9 m) and the sphere polygons as
  curves (every vertex within the 64-gon sagitta of the other polygon, areas within 1e-3 relative).
- **[decision, implementation] (M4) Small choices the contract leaves open.** `stage_a_object(obj, lights, receiver,
  tol, warnings)` takes the stage-A receiver record (`{id, pi, bounded, frame, bounds, psi, suffix}`); its per-receiver
  data is `obj["curved"][r][light]` with the polygon already bounds-clipped and the closed-form clipped arcs in
  `conic_pieces` (`sub_arcs_where_nonnegative(..., tol)` with the stage-A `tol` on `ψ_k·X`). On a bounded receiver a
  loop whose bounds clip is empty is dropped from `loops` (the ground keeps the v2 behaviour). A plate lit from its
  negative side traverses `ids[::-1]` (`b<k-1> … b0`). A plate caster on the unbounded ground emits
  `VERTEX_NOT_BELOW_LIGHT` with its receiver id like an object. `construction.per_receiver` lists every receiver
  other than `receivers[0]`, lit or not (its `F'_r` is reported as `F` is for an unlit ground). With `N = 1` the plate's
  `form_shadow` entry uses `lights[0]`. `edges[].runs` is set in `compose` (a fresh `[]` per edge; `primitives.py`
  and its `edge_templates` belong to M5). The `F'_r` marker is labelled `F′<receiver id>`. `RECEIVER_UNLIT` messages
  name the case ("light below the ground", "point light is behind …", "directional light is parallel …",
  "directional light is behind …"). `castplane stages` writes `B` without its `A` reference. Until the H-track lands,
  `compose` calls `hidden.classify_document` only when `castplane.hidden` can be imported.
- **[decision, implementation] (M4) `objects` sub-group order.** §5.0.6 says the `objects.<id>` groups (objects and
  bounded receivers) follow document order, but the v2 writer orders them by id (`sorted`), and five v2 cases
  (`concave_prism_light_foot_in_notch`, `example_construction_demo`, `example_curved_demo`, `example_directional`,
  `example_three_point`) have object ids out of sorted order: following the wording would break the byte-identity gate
  of §5.0.6 / §5.1.8. The writer keeps the v2 rule (sorted by id; a receiver's group sorts with the objects), which is
  what the golden hashes require. `form_shadow` entries keep document order (objects, then plates), as in v2.
- **[decision, implementation] (M4 review) `cast_shadow.<light>.<object>.conics` ids with several receivers.** §5.0.6 /
  §2.10 name the sub-group by (light, object) only, but M4 has one shadow record per (light, receiver, object): a curved
  object casting conics on two receivers (`fold_curved_cylinder`) wrote two `<g>` with the same id, which XML forbids.
  The record on `receivers[0]` (and every record of a v2 document, which has no `receivers` block) keeps the v2 id
  `cast_shadow.<light>.<object>.conics` (golden hashes unchanged); a record on any other receiver `r` writes
  `cast_shadow.<light>.<object>.<r>.conics`. The H-track `cast_shadow.<light>.<object>.outline` groups use the same
  rule (`svg._shadow_subgroup_id(record, receivers[0] id, "outline")`); the TypeScript port must follow it.
- **[decision, implementation] (M4 review) Geometry of the `concave_prism_on_plate` case (step 10).** "Expected
  polygon = the whole plate" holds when the plate lies beyond the closed arm of the U with the lamp in the notch below
  the arms' tops (U `[[−1,−1],[1,−1],[1,1],[0.5,1],[0.5,−0.5],[−0.5,−0.5],[−0.5,1],[−1,1]]`, height 1, at the origin;
  lamp `(0, 0.2, 0.7)`; plate `[−3,3]×[−4.5,−2]`: area 15 = the plate, the anchor rule fires). It does **not** hold for a
  plate under the prism: the notch floor under the lamp and the wedge through the opening are lit (U ±1.5 with the same
  notch at `(0,4,0)`, lamp `(0, 4.5, 0.5)`, plate `[−3,3]×[1,7]`: area 36 − 2 − 2.625 = 31.375). The conformance case
  uses the first geometry; both agree with `raycast.occluded_on_receiver` at IoU ≥ 0.99
  (`test_concave_prism_on_plate_geometries_against_the_raycast`).
- **[decision, implementation] (M4 H-track) Silhouette guard of the depth-buffer reference.** The bare three-valued
  rule of §5.1.11 misjudges a sample that lies within a pixel of an occluder's silhouette **behind** it: the ray through
  the pixel centre (up to 0.07 mm from the sample) passes beside the occluder and sees the background (`Z > depth·1.02`,
  "visible") while the sample's own ray grazes the occluder (`first_hit < 1 − ε_t`, correctly hidden). Light terminators
  near the camera silhouette produce whole runs of such samples (the terminator generator of a cylinder lit from nearly
  the camera's side; a sphere's light-silhouette circle just behind its rim). The same happens on a **face seen
  edge-on**: in the contract's own case `hidden_lines_vp_in_canvas` the camera (`z = 3`) lies exactly in the plane of
  the tower's top face, so the pixel-centre rays beside the hidden top edges see `Z = inf` through the zero-width face.
  Measured with `guard=False` over the 29 depth-buffer scenes of `tests/test_hidden.py` (77,529 decided samples, 273
  disagreements): the bare rule fails the ≥ 99 % gate on `hidden_lines_vp_in_canvas` (543 / 618 = 87.9 %),
  `hidden_lines_curved_unbounded` (973 / 984 = 98.9 %), `random_1` (98.7 %) and `random_3` (97.9 %), and it fails the
  **100 % rule on box / prism `edges[]`** ("no silhouette ambiguity there") on `hidden_lines_vp_in_canvas` (467 / 535;
  all 68 box-edge disagreements of the set are there). Every one of the 273 disagreeing samples is confirmed
  castplane-correct by the point-wise ray cast (`zbuffer.occluded_points`). `zbuffer.hidden_states` therefore
  leaves a sample **undecided** also when some pixel of the 3 × 3 neighbourhood of its pixel lies on the other side of
  the sample's depth than the centre pixel (centre "hidden" and a neighbour `Z ≥ depth`, or centre "visible" and a
  neighbour `Z ≤ depth`): a depth edge then passes within 1.5 px of the sample — the "silhouette pixels" the contract
  names as a limit of the reference. The band rule itself is unchanged (`guard=False` gives it). The 100 % box / prism
  rule of §5.1.11 is therefore stated, and tested, on the **guarded** decided set (9,631 of the 14,424 box / prism
  samples stay decided). With the guard every
  M4 scene and the 20 random scenes of `tests/test_hidden.py` agree at 100 % of the decided samples (≥ 99 % required),
  both states are decided in quantity, and a document with every state flipped fails
  (`test_depth_buffer_comparison_is_not_vacuous`). Test-side choices the contract leaves open: the world point of a
  sample is recovered by the reference (the image point back-projected onto the drawable's 3-D line, onto its receiver
  plane for `polygon_edges`, the exact circle point / its exact shadow at the run's `theta` for conics, sampled by image
  length along the exact curve); which `polygon_edges` are subjects comes from `hidden.clip_polygon_4d`'s provenance;
  the random scenes are `random_scenes.make_scene(5000 + seed, 1 + seed % 6)` with `seed % 3` plates (a wall behind the
  objects as seen from the camera, then a low panel in front of them).
- **[decision, implementation] (M4 review) The 4-D clip decides on the drawn 3-vectors.** `hidden.clip_polygon_4d` and
  `hidden.drawn_segments_4d` read §5.1.6.4's "evaluated on `P·X` (the same floats as the 2-D clip)" literally: after
  the near clip (4-D, as in stage B) they compute `x̃ = P·X` once and run the four rectangle steps on the carried
  3-vectors with the stage-B formulas (`(fa·x̃b − fb·x̃a)/(fa − fb)`, the zero-row filter on the 3-vectors with the 2-D
  scale), interpolating the 4-D points with the same `(fa, fb)`. The first implementation re-projected the
  interpolated 4-D point before each functional; from the second functional on its values differed from the drawn
  polygon's in the last bits, and a vertex on a clip line (a shadow edge through the extended-canvas corner:
  `wall_and_ground_hidden` seen from `(0, 4.5, 0.5)` towards `(0, 6, 0.5)`, the fourth functional −2.6e-14 drawn vs
  +6.5e-14 re-projected) gave 6 vertices against 4 drawn, so `classify_document`'s count check wrote four occluded
  edges `visible`. Every in/out decision is now bit-identical to the drawn polygon's; the count check stays as a
  defensive guard (no raise) that can only fire if `project` gave different bits for the same row in the stage-B
  batch, which no test scene does (`test_clip_polygon_4d_vertex_count_equals_the_drawn_polygon` on all cases). The
  TypeScript port must carry the 3-vectors the same way.
- **[decision, implementation] (M4 review) Conic polylines are recomputed, not handed over.** §5.1.6.5 (c) says the
  §2.6 polyline is "sampled once in `_arc_drawables`" and reused; `_arc_drawables` samples only the arcs it draws as
  polylines (a healthy ellipse arc is an SVG `A`), so `hidden._conic_subject` recomputes the polyline of every visible
  interval with the same call (`sample_arc(H, ρ, lo, hi, sample_count(lo, hi))` and the same division), which gives
  the identical floats; the parametrisation and the `hidden_polylines` are cut from that table.
- **[decision, implementation] (M4 review) `cli.py` lines outside the PLAN's M4 block.** Besides the argument block and
  the `info` receivers, M4 changed `_run` (a `hidden_lines` parameter passed to `compose`; the `def` line and the
  `return` line, next to the `scene = load_scene(scene_path)` line M5 turns into `load_expanded_scene`), the module
  docstring usage block, one import line (`HIDDEN_STYLES`) and `cmd_stages` (`_stage_b_without_a`, B written without
  its `A` reference). The merge of M4 after M5 resolves the `_run` hunk by keeping both changes
  (`load_expanded_scene` and the `hidden_lines` parameter).
- **[decision, implementation] (M4 step 10) The nine cases: choices the contract leaves open.** The scenes are the
  test-suite builders (`tests/test_receivers.py::wall_and_ground_scene` / `fold_curved_cylinder_scene`,
  `tests/test_hidden.py::m4_hidden_scenes` / `curved_unbounded_scene` / `vp_in_canvas_scene`), so the conformance
  files and the unit / depth-buffer tests check the same geometry. The switch is on exactly where §5.1.11 says so
  (`wall_and_ground_hidden`, `hidden_lines_curved_unbounded`, `hidden_lines_vp_in_canvas`) and off in the other six
  (`fold_curved_cylinder` included: its conic bounds clip is the subject; conic runs are covered by
  `hidden_lines_curved_unbounded`). `receiver_unlit_wall` puts the lamp at `(0, 8, 3)`; besides `RECEIVER_UNLIT
  [lamp, wall]` it carries `POINT_BEHIND_CAMERA [wall]` (the wall's top corners shadow onto the ground at
  `(±18, −4, 0)`, behind the camera at `y = −1`) — kept on purpose: it is the §5.1.9 case "ids may be a receiver id".
  `receiver_directional_wall` uses the sun `(0.3, −0.5, 0.8)/√0.98` and a level camera (`target z = 1.6`), so the
  in-wall direction `F.sun.wall ∝ (0.3, 0, 0.8)` is perpendicular to the view direction and its image is at infinity.
  `concave_prism_on_plate` is the "beyond the closed arm" geometry of the note above.
- **[decision, implementation] (M4 step 10) Worktree changelog entries and the rules record at the merge.** In the
  worktree `rules.json` was changed through `--rules-only` (§5.0.8 rule 3; local entry `v4`) and the nine cases were
  added with one `--case` call (local entry `v5`); both entries say they are worktree-local. At the merge they are
  collapsed into the one v4 milestone entry together with the full key-additive regeneration (rule 1), **and that
  collapsed entry must keep the `- rules (tests/conformance/rules.json at v4):` snapshot block** (or the merge runs
  `--rules-only` on `main` before the regeneration): `tests/test_conformance.py::test_rules_json_is_versioned_in_the_changelog`
  reads the last rules snapshot of the changelog and requires it to equal `rules.json`. `--strip-new-keys` compares a
  case whose expected file already carries the M4 keys (`"hidden_lines":` present — the nine M4 cases, and every file
  after v4) unstripped, so the pre-v4 check runs on the whole set (`43 of 43 case(s) with zero mismatches`) instead of
  failing on the nine new files; the 34 v2 files are stripped as §5.1.11 says (34 of 34 byte-identical after
  stripping on the recorded build).
- **[decision, implementation] (M4 step 10) `bench.py --hidden-lines` adds one row and keeps the committed scene.**
  §5.0.9 / C18 / §5.4.9 list `--hidden-lines` among the variants that "generate"; §5.1.6.6 says the option "times the
  spec §8 scene with the switch on" and that the table also records the switch-off rows. `--hidden-lines` therefore
  loads the same scene as the default run (the committed `benchmark_100.json`, with `output.hidden_lines` set to true
  in memory — on the recorded NumPy build this is byte-identical to the generated scene, and on any other build it is
  still the one spec §8 scene the other rows measure) and **adds** the informational row `full render, hidden lines
  on` (`hidden_lines_full_render_s: {min, median, target: 5.0, soft_pass}`, `hidden_lines_svg_bytes`,
  `hidden_lines_json_bytes` in `--json`); every other row, `pass` and the exit status stay the switch-off measurement,
  so `--gate full` is unchanged with or without the option.
- **[decision, implementation] (final review, m4-hidden#0) Receiver order of the construction layer.** `_layer_construction`
  iterated `construction.per_receiver` in dict order: scene order in memory, code-point order after the canonical JSON
  round trip (`sort_keys`), so `write_svg(json.loads(dumps(doc)))` differed from `write_svg(doc)` (the `F′wall` /
  `F′panel` markers and rays swapped) whenever two bounded receivers were not in code-point order — the writer must be a
  pure function of the document's content (§3, §5.4.6). The F′_r markers and rays are now emitted in `receivers[]`
  document order (ids missing from `receivers[]`, not produced by the pipeline, last in code-point order); the
  multi-light path passes `receivers` to the per-light sub-document. The in-memory order was already scene order, so no
  golden or expected SVG changes. §5.0.6 states the order. Test:
  `tests/test_receivers.py::test_construction_layer_is_independent_of_per_receiver_key_order`.

### 5.2 M5 — mesh import (spec §9 rows 網格匯入 / 匯入格式, spec §10 M5, spec §11.3)

Everything in §2–§4 stays in force. This section adds the object type `mesh`, the preprocessing pipeline, the per-face
fallback, four warning codes (`MESH_*`, appended to the §2.9 table after `RECEIVER_UNLIT`; the total is 18, §5.0.5), two
document keys (mesh edges only), the loaders and the `castplane import` command (unified with M8 in §5.0.2).

Layering rule **[decision]** (as amended by §5.0.2 **[decision, synthesis]**): file loaders live in `castplane/io/` and
are used **only** by `castplane.io.expand_scene` / `load_expanded_scene` / the CLI, never by `validate_scene`. After
expansion a `mesh` object always carries its geometry inline (`data`, §5.2.1), so `validate_scene`, stages A/B/C and
the preprocessing pipeline (§5.2.3) are pure functions of the scene dict and need no file or optional dependency; the
TypeScript port reproduces every mesh document from the scene JSON alone (§5.2.9).

#### 5.2.1 Scene JSON: object type `mesh` (§2.0 validation table additions)
| field | rule |
| --- | --- |
| `objects[i].type` | now one of `box, cylinder, sphere, cone, prism, mesh` |
| `objects[i].path` (mesh) | non-empty string. At least one of `path` / `data` must be present (neither → `SceneError(objects[i].data)`); both together mean "already expanded" (§5.0.1). Resolved against `base_dir` by `expand_scene` (§5.0.2); the file is loaded by `io.load_mesh_file(abs_path, node)` **during expansion** and every loader error (missing / unreadable file, parse error, unsupported feature, empty selection) is re-raised as `SceneError(field="objects[i].path", message=<loader message>)`. A missing optional dependency (trimesh) propagates as `ImportError` (CLI exit 3). After expansion the object holds **both** the original `path` string (as written, informational) and the loaded `data`; `validate_object` requires `data` and raises `SceneError(objects[i].path, "mesh file must be expanded first …")` when only `path` is present **[decision, synthesis]**. Within one `expand_scene` call a parsed file is cached by absolute path (Python-only implementation note; no observable effect) |
| `objects[i].node` (mesh, optional) | string **or** non-negative integer. glTF: a string selects the **first node in depth-first traversal order** (§5.2.8) whose `name` equals it (its subtree), else the first mesh with that name; an integer selects `nodes[k]` (its subtree). OBJ: a string selects an `o` / `g` name; an integer selects the k-th **distinct** `o` / `g` name in order of first appearance. Not found → `SceneError(objects[i].node)`. Ignored (kept) for `data` |
| `objects[i].data.vertices` | list of ≥ 3 `[x, y, z]` finite numbers (field `objects[i].data.vertices[k]`) |
| `objects[i].data.faces` | list of ≥ 1 int lists, each ≥ 3 entries, every index in `[0, n_v)` (field `objects[i].data.faces[k]`) |
| `objects[i].data.smooth_groups` (optional) | list of non-negative ints, length = `len(faces)`; `0` = no group (OBJ `s off`). Default: all `0` |
| `objects[i].up` (optional) | `"z"` (default) or `"y"`. `"y"` converts `data` (whatever its source: inline, OBJ, STL, PLY) in `validate_object` with the **exact axis map** `A`: `(x, y, z) ↦ (x, −z, y)` (`AXIS_MAP = [[1,0,0],[0,0,−1],[0,1,0]]`, integer entries, implemented by component swapping and sign change, **never** by `cos`/`sin`: `Rx(90°)` via trig leaves 1.2e−16 noise and breaks the exact box equality of §5.2.13), so `data` is always Z-up afterwards (`up` is rewritten to `"z"` in the validated form). glTF / GLB files are Y-up by definition and are **always** converted by the loader; giving `up` together with a glTF / GLB `path` is a contradiction → `SceneError(objects[i].up, "glTF files are always Y-up; omit up")` (raised by `expand_scene`) |
| `objects[i].scale` (optional) | number `> 0`, default `1`; multiplies the local vertices (file units → metres; glTF is already metres). It is applied **before** `weld_tolerance`, so files in millimetres need `scale: 0.001` (`--scale 0.001`), otherwise the 1e−6 m default weld is 1e−9 file units and seams stay open (USAGE.md says this) |
| `objects[i].weld_tolerance` (optional) | number `≥ 0`, default `1e-6` (metres, after `scale`) |
| `objects[i].smooth_angle_deg` (optional) | number in `[0, 180]`, default `30` |
| size guard | after loading: `len(faces) ≤ MESH_MAX_FACES = 50000` and `len(vertices) ≤ MESH_MAX_VERTICES = 50000`, else `SceneError(objects[i].data.faces | .data.vertices)` (`objects[i].path` for file sources). Constants in `scene.py` |
| usable-face guard **[decision]** | validation runs `meshprep.weld_vertices` + `meshprep.drop_degenerate_faces` (§5.2.3 steps 1–3, numpy only, O(V + F)) on `scale · vertices` and raises `SceneError(objects[i].data.faces, "no usable face")` (`objects[i].path` for file sources) when no face survives. The validated `data` stays the **raw** (unwelded) data; the check only guarantees "validated ⇒ renders": `shadow_geometry` never raises on a validated scene and `castplane validate` / `render` agree |
| `objects[i].transform` | as §2.0 (`scale` key still forbidden; use `objects[i].scale`) |

Unknown keys are still ignored (`castplane import` writes a `meta` block, §5.2.8). Validated form of a mesh object:
`{id, type: "mesh", path: str | None, node: str | int | None, data: {vertices: [[x,y,z]...] floats (Z-up, file units,
node transform baked), faces: [[int...]...], smooth_groups: [int...]}, up: "z", scale, weld_tolerance, smooth_angle_deg,
transform}`.

#### 5.2.2 Path resolution
Done by `castplane.io.expand_scene(scene, base_dir=None)` / `load_expanded_scene(path_or_dict, base_dir=None)` (§5.0.2):
for a file path, `base_dir` defaults to `os.path.dirname(os.path.abspath(path))`; a relative `objects[i].path` is joined
to `base_dir`; with a dict input and no `base_dir` the current working directory is used (M8's rule) **[decision,
synthesis]** — the M5 design's "relative path needs base_dir" error is withdrawn in favour of one rule for both loaders.
Absolute paths are used as given. `load_camera` is unchanged. The expanded scene never contains an absolute path (it
keeps the string as written), so expanded scenes stay machine-independent.

#### 5.2.3 Preprocessing pipeline (`castplane/meshprep.py`, core, portable) — `preprocess_mesh(data, scale, weld_tolerance, smooth_angle_deg) -> (mesh, triangles, fallback, smooth_groups, warnings)`
All steps are deterministic, order-defined, numpy/stdlib only; floats are float64 (float32 file data is widened exactly).
**[decision]** The step order is weld → degenerate → triangles → adjacency / manifold / orientation → coplanar merge →
dihedral classification; spec §9 lists merge → dihedral → manifold, but the merge needs consistent outward orientation
(the merged polygon's winding is taken from its faces) and the manifold test must see the unmerged faces, so the manifold
/ orientation step comes first.
1. **Scale**: `V = scale · data.vertices`. `scale_A = max(1, max extent of the bounding box of V)` is the length scale of
   every tolerance in this section.
2. **Weld** (`weld_vertices(V, faces, tol)`): cell key per vertex `c = (floor(x/τ + 0.5), floor(y/τ + 0.5), floor(z/τ + 0.5))`
   (for `τ = 0`: exact equality of the float triple). Vertices are visited in input order; vertex `i` is merged into the
   representative with the **lowest input index among all representatives registered in the 27 cells `c + δ`,
   `δ ∈ {−1,0,1}³`, whose max-norm distance to `v_i` is `≤ τ`** (the order in which the 27 cells are inspected is
   irrelevant; several neighbouring cells may each hold a representative within `τ`); if none, `i` becomes a
   representative registered in cell `c`. The welded position is the **representative's own coordinates** (never a mean),
   so welding a split-vertex box reproduces the parametric vertices exactly. Representatives are numbered in order of first
   appearance; vertex names are `<obj>.v<k>` in that order. Representatives used by no kept face (step 3) are removed,
   keeping the order. Cost: the reference form is an O(27·n) dict-lookup loop (≈ 1 s in CPython at the 50 000 cap); a
   vectorised fast path (e.g. `np.unique` on the **integer** cell keys with the lowest input index per cell, plus the
   27-cell loop only for vertices whose cell has an occupied neighbour) is allowed **only if proven result-identical**
   (same representatives, same first-appearance numbering) by `tests/test_meshprep.py` against the reference loop.
3. **Degenerate faces** (`drop_degenerate_faces(V, faces, scale_A)`): consecutive duplicate indices are collapsed
   (cyclically); then a face is dropped when it has `< 3` vertices, when its vertices are **not pairwise distinct** (e.g.
   `[a,b,c,b]`: it would contribute the same undirected edge twice from one face and fool the manifold count), or when its
   Newell normal norm is `≤ 1e-12 · scale_A²` → warning `MESH_DEGENERATE_FACES` (ids `[object]`, message gives the count).
   Zero kept faces cannot happen on a validated scene (§5.2.1 usable-face guard); `build_object` asserts it.
4. **Triangles**: `triangles = fan triangulation` of every kept face at its first vertex (`(f0, f_k, f_{k+1})`), `(t,3)`
   int over the welded vertices (`mesh.triangulate_faces(faces_padded, face_lens)`: vectorised, columns `(0, k, k+1)`
   masked by `face_lens`); kept on **mesh** object records only (`rec["triangles"]`) as the **original surface** for the
   inside test, the M4 ray tests (§5.1.6.2) and the ray-cast reference (§5.2.7). Primitives do not get the key in M5
   (features-off cost, §5.2.7); M4's `hidden.occluder` has exact per-kind tests for them and needs no triangles.
5. **Adjacency / manifold / orientation** (`build_adjacency`, `fix_orientation`): directed edges from the face cycles;
   undirected edges `i<j` sorted lexicographically with their incident face lists, where incident faces are counted as
   **distinct face indices**. *Manifold* ⇔ every undirected edge has exactly 2 incident faces. *Consistent* ⇔ the two
   faces traverse it in opposite directions. If manifold but not consistent: orientation propagation over the face
   adjacency graph (BFS per connected component from its lowest-index face, FIFO queue, neighbours in ascending edge
   index; a face is flipped by `[f0] + f[1:][::-1]` (same start vertex) when it traverses the shared edge in the same
   direction as its already-oriented neighbour); a conflict (a face reached twice with contradicting requirements, e.g. a
   Klein-bottle connectivity) → not manifold. Then per connected component the **signed volume** `Σ_tri (a·(b×c))/6`
   (sequential sum over the component's triangles in index order) is computed and the component is temporarily oriented
   outward (`volume > 0`); components with `|volume| ≤ 1e-12·scale_A³` (closed zero-volume sheets) keep their orientation
   and take no part in nesting. **Nesting parity [decision]**: for every component `k` the depth `d_k` = number of *other*
   components `c` with `|w_c(x_k)| > 0.75`, `x_k` the lowest-index vertex of `k` and `w_c` the generalised winding number
   of component `c` (step 8 formula, evaluated on `c`'s triangles alone; `|w|` does not depend on `c`'s orientation). The
   required orientation of `k` is outward (`volume > 0`) for even `d_k` and inward (`volume < 0`) for odd `d_k` (a cavity
   shell of a hollow solid keeps its inward normals, so a light inside the cavity has `w = 0` and is "outside"). A
   component whose **original** signed volume has the wrong sign is flipped as a whole. Any flip (propagation or volume)
   → `MESH_WINDING_FIXED` (ids `[object]`). Not manifold → `fallback = True` (§5.2.5), warning `MESH_NON_MANIFOLD` (ids
   `[object]`, message: number of edges with 1 / ≥ 3 faces and whether winding was inconsistent — the message **says
   "inconsistent winding"** when propagation hit a conflict). Closedness is implied by the manifold rule (boundary edges
   have one face).
6. **Coplanar merge** (`merge_coplanar(V, faces, normals, adjacency, cos_tol)`, manifold meshes only) **[decision]**:
   seed-ordered **region growing** (not union-find, whose result depends on the edge processing order): faces are taken in
   index order; an unassigned face `s` seeds a region; the region grows by BFS over face adjacency (FIFO queue; the
   neighbours of a face are visited in ascending index of the shared undirected edge); a neighbour `f` reached from `g`
   joins iff it is unassigned, `n_f·n_s ≥ c` **and** `n_f·n_g ≥ c`, `c = cos(COPLANAR_TOL_RAD)`, `COPLANAR_TOL_RAD = 1e-3`
   (the seed test blocks drift along gently curved strips; a face outside the seed's tolerance later seeds its own
   region). The region boundary = the region's directed edges whose other face is outside the region, chained into loops
   by the lowest-index unused outgoing edge (as `silhouette_loops`). A region whose boundary is not **one simple loop**
   (several loops → hole; a vertex visited twice → pinch) is left **entirely unmerged** (its interior edges are smooth by
   step 7, so nothing is drawn). A merged region becomes one face: its cycle is the boundary loop **started at the first
   vertex of the seed's cycle that lies on the boundary**, walked in the boundary's own direction (which is the seed's
   winding, since orientation is consistent); if no vertex of the seed is on the boundary (a fully interior seed, e.g. the
   centre triangle of a fan-triangulated cap is never the seed because the seed is the lowest index, but a centre-fan cap
   seeded by `[centre, r0, r1]` has its first vertex `centre` interior) the start is the **lowest-index boundary vertex**.
   Merged faces are ordered by seed index; the normal of a merged face is the Newell normal of its polygon;
   `smooth_groups` of a merged face = the seed's group. Vertices used by no face after the merge (e.g. a cap's centre
   vertex) are **kept**: they stay in `vertices` with their names and `points` entries and remain indexed by `triangles`;
   they simply have no edges (and therefore no shadow / foot points, since they are never silhouette vertices). The result
   goes through `mesh.mesh_from_faces` (the §2.4 dict); merged polygons may be concave (every consumer already copes:
   `lit` uses normal + first vertex, form-shadow polygons use nonzero fill).
7. **Edge classification** (`classify_edges(mesh, smooth_angle_deg, smooth_groups)`): `edge_smooth (m,) bool` on the
   merged mesh, with `g_a`, `g_b` the smoothing groups of the two faces **[decision]**:
   `smooth ⇔ (g_a == g_b ≠ 0) ∨ (g_a == g_b == 0 ∧ n_a·n_b ≥ cos(smooth_angle_deg) − 1e-9)`.
   Different non-zero groups, and group vs no-group, are **feature** edges whatever the dihedral angle (a modeller assigns
   different `s` groups precisely to force a hard edge); within group 0 the angle rule decides, with the dimensionless
   band `1e-9` (§2.8: no equality predicate), so coplanar-but-unmerged interiors (hole / pinch regions,
   `n_a·n_b = 1 ± ulp`) are reliably smooth even at `smooth_angle_deg = 0`, which otherwise means "every non-coplanar edge
   is a feature edge". Primitive meshes get `edge_smooth = all False`.
8. **Record**: `build_object` adds `mesh["edge_smooth"]`, `triangles`, `fallback`, `smooth_groups` (per final face),
   `prep_warnings` and the usual §2.4 tables. `point_inside_solid` for a manifold mesh uses the generalised winding number
   of `triangles` (`meshprep.point_inside_mesh(verts, tris, x, tol)`: Van Oosterom–Strackee solid angles summed
   sequentially in triangle order; **inside ⇔ `|w| > 0.75` and the point–triangle distance to every triangle is `> tol`**;
   `w` is 0 or ±1 off the surface, 0.5 on it, so 0.75 is a safe midpoint and the distance clause mirrors
   `_point_in_polygon_margin`: a light on the surface within `tol` is outside, §2.5), with `LIGHT_INSIDE_OBJECT` message
   "point light is inside the mesh"; fallback meshes never report it (no inside).
Constants: `COPLANAR_TOL_RAD = 1e-3`, `WELD_TOLERANCE_DEFAULT = 1e-6`, `SMOOTH_ANGLE_DEFAULT = 30.0`, `MESH_MAX_RAYS = 64`,
`SMOOTH_BAND = 1e-9`, `INSIDE_WINDING = 0.75`. Scene scale (§2.8) includes mesh vertices like any object.

#### 5.2.4 Drawing rules for mesh edges
- Light silhouette (§2.5): unchanged — `lit` flips; smoothness is irrelevant.
- **Camera silhouette edge [decision]**: an edge whose two faces differ in `lit(n_f, p, (C,1))` (the existing stage-B
  `face_lit`). Objects layer draws an edge iff `not smooth or camera_silhouette`. A smooth, non-silhouette edge has
  `segment: null` (not a drawable; the SVG writer needs no change); `back` is computed as before (a camera silhouette edge
  is never back). Feature edges are drawn as before. **M4 cross-rule**: `edges[].visibility` is left at the template value
  (`"visible"`) for every edge with `segment: null`; the M4 sampler only classifies drawn segments (§5.1.7 states the
  same, so neither worktree guesses).
- `edges[]` entries of **mesh objects only** carry two extra keys: `"smooth": bool` (camera independent, from stage A)
  and `"camera_silhouette": bool` (stage B). Absent keys (primitive edges) mean `false`; the primitives' expected files
  are therefore unchanged by M5.
- Construction rays **[decision]**: for a mesh object the rays / self-checks (§2.7) are produced for silhouette vertices
  that are endpoints of at least one **feature** silhouette edge. The candidate set is evaluated **inside `_shadow_record`
  on the loop mesh actually used** (the object's mesh, or the receiver-clipped mesh of §2.3 / §5.1.3.2): an edge of the
  clipped mesh inherits `edge_smooth` from the original edge it is a part of (a crossing vertex `("ground", i, j)` names
  that edge); cut-face edges (both endpoints crossings) are feature; crossing vertices are never candidates (they have no
  rays, §2.3). **Selection** is in silhouette-loop order (loops in order, vertices in loop order, first occurrence of an
  original vertex), the first `MESH_MAX_RAYS = 64` per (object, light, receiver); truncation → `MESH_RAYS_CAPPED` (ids
  `[object]`). **Emission** keeps the existing order (`rays` / `checks` / `segments` follow `vertex_ids`, ascending
  original index): the record carries `ray_vertices (len(vertex_ids),) bool` aligned with `vertex_ids`, which
  `_project_shadows` ANDs into `ok` (`ok = keep & ν(P) ≥ 0 & ν(S) ≥ 0 & ν(Q) ≥ 0 & ray_vertices`; primitives: all True).
  All silhouette vertices keep their `.shadow.<light>` / `.foot` points (the outline names them). A box mesh (all feature)
  gets exactly the parametric box's rays in the parametric order. Labels: unchanged rule (switch the layer off for large
  meshes).

#### 5.2.5 Non-manifold fallback (per-face shadows)
Used when step 5 fails. The object record keeps a §2.4-shaped mesh built by `meshprep.fallback_mesh`: `faces` = the kept
faces as given (after weld / degenerate removal, no merge, no orientation fix), `edges` = unique `i<j` pairs,
`edge_faces[e] = [f_min, f_max]` (lowest / highest index face containing the edge; equal for a boundary edge),
`edge_flipped` accordingly, `face_normals` by Newell on the face as given, `edge_smooth = all False`. Stage A
(`shadow_geometry`) **[decision]**:
- `obj["ground_mesh"] = None` always, and — **[decision, synthesis]** — `obj["clipped"][r] = None` for every receiver `r`
  of §5.1.2 (`clip_mesh_to_plane` is **never** called: it chains the open rim of a non-manifold mesh into cap faces and
  would turn an open box into a closed solid, verified); `OBJECT_BELOW_RECEIVER` is still emitted from the vertex test
  (unbounded ground only, §5.1.9). `rec["prep_warnings"]` are merged into the stage-A warnings for every object.
- `_object_light_data`: lit flags per face as usual (`FACE_PARALLEL_TO_LIGHT` applies); **no** inside test
  (`light_inside = False`); `edge_silhouette[e] = lit[f_min] != lit[f_max]` (approximate, documented); `loops = []`
  (`silhouette_loops` is not called on the `[f_min, f_max]` adjacency); `form_faces` = the unlit faces; `back` (stage B)
  = both `f_min`, `f_max` camera-unlit.
- `_fallback_shadow_record(obj, ol, lt, pi, tol, receiver_id)` replaces `_shadow_record`: `vertex_ids` = **every vertex
  used by a kept face**, ascending; `keep = finite & above` as in §2.3; `.shadow.<light>` **and `.foot`** points exist for
  every kept vertex (feet are camera-free and cheap, and keeping one foot per vertex keeps `compose`'s bulk zip of
  `foot_names` / `keep` aligned — the "no feet" variant would need a `foot_keep` mask through `_project_shadows` and
  `compose`); `ray_vertices = all False`, so there are **no rays, checks or `segments`** for a fallback object
  (`MESH_RAYS_CAPPED` never fires). Shadow: for **every** face (lit or not; parallel faces excluded) take its cycle, reverse
  it with `[f0] + f[1:][::-1]` when the face is unlit (so the lit side is on the left, §2.5), and run
  `shadow.shadow_loop(face4, M, π, tol_w, tol)` — receiver clip, `w_S` direction vertices and arcs included (with the
  receiver frame of §5.1.2 for a non-ground receiver) and then, for a bounded receiver, `clip_polygon_bounds` of §5.1.3.3
  per loop **[decision, synthesis]**. A loop is dropped when it has `< 3` vertices or when it is **bounded** and its
  receiver-plane area satisfies `|area| ≤ tol·scale_A` (the area test is **not** applied to unbounded loops, whose
  homogeneous rows have no finite area). Each surviving face gives one entry of `shadows[].loops` in face order (names
  `<obj>.v<k>.shadow.<light>[.<r>]`, inline directions as §3.1); crossings are named `<obj>.s<k>.<light>[.<r>]` in order of
  first appearance **keyed by the undirected original edge `(min(face[i], face[j]), max(...))`** (`shadow_loop`'s
  `("ground", i, j)` gives loop positions `i, j`), so a crossing on an edge shared by two faces is one point with one name;
  `outline` = the first loop; `polygons` = one drawable per loop, written as **one `<path>` with nonzero fill** (already
  the §2.10 writer's behaviour) so the drawn region is the union; `unbounded` = any loop unbounded (always `false` on a
  bounded receiver). `VERTEX_NOT_BELOW_LIGHT` as usual (unbounded ground only).
- Receiver-plane faces: a face lying **in** the receiver plane shadows itself (its loop is its own footprint); the
  ray-cast reference ignores hits at `t ≤ 1e-9` and does not see such a face (§5.2.7). Acceptance tests avoid this by
  opening the box at the bottom.

#### 5.2.6 Warning codes added to §2.9 (+4 codes; the rows are in §5.0.5)
`MESH_NON_MANIFOLD`, `MESH_WINDING_FIXED`, `MESH_DEGENERATE_FACES`, `MESH_RAYS_CAPPED`, all with ids `[object]`, appended
to `WARNING_CODES` after `RECEIVER_UNLIT`.

#### 5.2.7 Interaction with other milestones, performance, shared-file inventory
- M4 hidden lines: the occluder of a mesh object is `rec["triangles"]` on the welded vertices (the original surface),
  never the merged polygons (§5.1.6.2). M5 adds the key to mesh records only and exposes `mesh.triangulate_faces` so M4
  can give primitives the same key when it needs it (M4 owns that `build_object` edit; M4 does not need it).
- M4 bounded receivers: the fallback runs `shadow_loop` + the bounds clip per face per receiver (§5.2.5); the manifold
  path is receiver-generic through `obj["clipped"][r]`.
- M4 visibility: see the cross-rule in §5.2.4 (`segment: null` edges keep `"visible"`).
- M6 lights: all per-light data is keyed by light id already; the fallback is evaluated per light.
- Ray-cast reference (`tests/reference/raycast.py`): `hit_mesh(obj, o, d, tmax)` = Möller–Trumbore on the fan triangles
  of the **raw** `data.faces` (scale, `up` already applied by validation, and `transform` applied in the reference's own
  code; `HITTERS["mesh"]`); "segment meets any face" is exactly the fallback's union semantics and the manifold case
  alike. Known gap: a face in the receiver plane (`t = 0`) is invisible to the reference (`T_EPS` rule) but is shadow for
  castplane; tests keep mesh faces off the receiver plane or lift the object.
- Performance (spec §8): the M3 benchmark is unchanged and remains the CI gate (`--gate full`). With meshes switched off
  the only new work on the benchmark path is one boolean comparison per edge in `_project_polyhedra`
  (`camera_silhouette`) and the all-False `edge_smooth` arrays; the measured delta is recorded in `benchmarks/README.md`.
  `benchmarks/bench.py --scene mesh10k` renders a 10 000-triangle welded mesh (stage A alone and the full render) and the
  README records the numbers (no gate in M5); the weld's O(27·n) cost (step 2) is part of that measurement.
- `castplane stages` output: every object record now shows `fallback`, `prep_warnings`, `mesh.edge_smooth`; mesh records
  also `triangles` and `smooth_groups` (USAGE.md lists them; `test_cli` only checks ids).
- **Shared-file inventory** (for the M4 / M5 / M6 parallel worktrees; merge order M4 → M5 → M6): `castplane/pipeline.py`
  (`shadow_geometry` loop, `_object_light_data`, `_shadow_record` + new `_fallback_shadow_record`, `_project_polyhedra`,
  `_project_shadows`, `compose`), `castplane/scene.py` (`validate_object` / `validate_scene` vs M4 receiver rows and M8's
  `LOADER_TYPES` block), `castplane/errors.py` (append-only, safe), `castplane/primitives.py` (`build_object`,
  `point_inside_solid`, `local_mesh`), `castplane/cli.py` (the `import` hook, shared with M8 through `castplane/io/cli.py`),
  `benchmarks/bench.py` (`--scene`), `tests/test_conformance.py` (inline-data rule), `tests/conformance/README.md` +
  `CHANGELOG.md`, `tests/reference/raycast.py` (`HITTERS` + `hit_mesh`), `tests/reference/random_scenes.py`
  (`make_mesh_scene`), `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/USAGE.md`, `pyproject.toml`. M5-only:
  `castplane/meshprep.py`, `castplane/io/obj.py`, `io/gltf.py`, `io/trimesh_adapter.py` (the registry `io/__init__.py` and
  `io/cli.py` are shared with M8, §5.0.2), `tests/test_meshprep.py`, `tests/test_mesh_pipeline.py`, `tests/test_loaders.py`,
  `tests/fixtures/meshes/*`.

#### 5.2.8 Loaders (`castplane/io/`, Python only) and `castplane import`
Common raw form returned by every loader (`io.load_mesh_file(path, node=None) -> raw`, dispatch by lower-cased extension
over `SUPPORTED_EXTENSIONS`): `{"vertices": [[x,y,z]...], "faces": [[int...]...], "smooth_groups": [int...]}` (Z-up for
glTF after the axis map, file axes otherwise; file units). `.obj` → `io.obj`, `.gltf` / `.glb` → `io.gltf`, `.step` /
`.stp` → `io.step.tessellate_step` (§5.5.7, via `EXTENSION_LOADERS`), anything else → `io.trimesh_adapter`
(`trimesh.load(path, force="mesh", process=False)`, faces / vertices taken as stored; `ImportError("install
castplane[mesh]")` when trimesh is missing; optional extra `mesh = ["trimesh>=4"]`).
- **OBJ** (`parse_obj(text) -> raw + groups`): `v x y z` (extra components ignored), `f` with `v`, `v/vt`, `v//vn`,
  `v/vt/vn`, negative (relative) indices, polygons ≥ 3; `o NAME` / `g NAME` (a face belongs to the current `o` and the
  current `g`; `node` matches either; integer `node` = k-th distinct name in order of first appearance); `s N` / `s off` /
  `s 0`; `\` line continuation; `#`, `vt`, `vn`, `l`, `p`, `mtllib`, `usemtl` and unknown keywords ignored. Errors (→
  `SceneError(objects[i].path)`): non-numeric coordinate, index out of range, face with < 3 vertices, no face after
  selection.
- **glTF 2.0 / GLB** (`read_gltf(path) -> (json, buffers)`): GLB container (magic `glTF`, version 2, JSON chunk, optional
  BIN chunk), `.gltf` with `data:` URIs (base64) and external `.bin` relative to the file. Accessors with `byteStride`,
  `byteOffset`, normalised = false; POSITION componentType 5126 only, indices 5121 / 5123 / 5125; sparse accessors, other
  component types, morph targets, skins → error. Primitive modes: 4 used; 5 / 6 expanded to triangles (strip:
  `(i, i+1, i+2)` with odd `i` swapped; fan: `(0, i, i+1)`); 0–3 skipped; others error. Non-indexed primitives use
  consecutive triples. **Numerics (normative for both loader implementations)**: `matrix` is **column-major** (16 floats;
  `np.array(m).reshape(4,4).T`); `rotation` is a unit quaternion `[x, y, z, w]`; `local = T·R·S`; `world = parent_world ·
  local`; world matrices by depth-first traversal of `scenes[scene].nodes` (default scene 0; all root nodes in index order
  when `scenes` is absent), children in array order — this traversal order defines "first node with that name". Vertices
  are transformed by the node world matrix (full affine; faces reversed when `det < 0`), then **axis-mapped** with the
  exact `A` of §5.2.1: `(x, y, z)_glTF ↦ (x, −z, y)` (glTF +Y up → castplane +Z up, right-handed preserved);
  `Aᵀ: (x, y, z) ↦ (x, z, −y)`. No smoothing groups.
- `castplane import FILE -o scene.json [--inline] [--node NAME|INDEX] [--camera NAME] [--light NAME] [--scale S] [--weld TOL]
  [--smooth-angle DEG] [--up y|z]` (the common options `--into`, `--id`, `-q` and the output rules are in §5.0.2): writes
  a spec §4 scene (`json.dumps(sort_keys=True, indent=1, ensure_ascii=False)`, canonical floats for importer-generated
  numbers); exit codes as §1 (2 for import errors, which are `SceneError`s whose `field` is the glTF JSON path, e.g.
  `nodes[3].scale`). Mesh objects reference `FILE` by a POSIX relative path from the output file's directory, or embed
  `data` with `--inline`. OBJ / STL / PLY: one mesh object (id = sanitised file stem, no `node`), default camera and light
  (below). glTF mapping tables:
  | glTF | scene JSON |
  | --- | --- |
  | mesh node (no extras) | `{"type": "mesh", "path": FILE, "node": <name or index>}`: the **name** when it is non-empty and unique among all nodes of the file, else the node **index** (so the importer's own output always re-loads); world transform baked by the loader; `transform` omitted |
  | node `extras.castplane = {"type": box|cylinder|sphere|cone|prism, ...params}` | that object verbatim (params in castplane local conventions, metres, Z up = node local +Y, anchor at the base centre); `transform.position = A·t_world`, `rotation_deg = euler_zyx(A·R_world·Aᵀ)` with `R_world` the normalised rotation part; **uniform positive** node scale `s` (`s > 0`, all three equal within 1e-9 relative) multiplies `size` / `radius` / `height` / `polygon`; non-uniform or non-positive scale → `SceneError(nodes[k].scale)`; a mirrored world matrix (`det < 0`) → `SceneError(nodes[k].matrix` or `.scale`, "mirrored node cannot carry a primitive")`; a mesh attached to such a node is ignored |
  | camera `perspective {yfov, aspectRatio, znear}` | `frame_mm = [24·a, 24]` (`a = aspectRatio`, default `1.5`), `focal_length_mm = 12 / tan(yfov/2)`, `near_m = znear`, `canvas_mm = [240·a, 240]`, `position = A·t`, `target = position + A·(R·(0,0,−1))`, `roll_deg = atan2(−up·right₀, up·up₀)` with `up = A·(R·(0,1,0))`, `R` the normalised rotation columns of the world matrix, and `(right₀, up₀)` castplane's unrolled frame of §2.2 (fallback up when looking along z) |
  | camera `orthographic` | `SceneError(cameras[k].type)` |
  | `KHR_lights_punctual` `point` | `{"type": "point", "position": A·t}` |
  | `directional` | `{"type": "directional", "direction": normalize(A·(R·(0,0,+1)))}` (glTF lights shine along local −Z; castplane points towards the light; `R` normalised columns) |
  | `spot` | point light at its position, note `IMPORT_SPOT_AS_POINT` |
  | several cameras / lights | cameras: the first in traversal order (or `--camera` by node name); others dropped with the note `IMPORT_CAMERA_DROPPED`. Lights: **[decision, synthesis]** **every** light is emitted in traversal order (M6 lifts the length-1 rule in this contract); `--light NAME` restricts the output to that one light; `IMPORT_LIGHT_DROPPED` is retired; when the output holds ≥ 2 lights an id that would be `umbra` or `core` (or any id `hidden`) is suffixed `_light` (§5.0.1) |
  | no camera | `target = bbox centre`, `position = (c_x, y_min − 2·e, z_min + 0.7·e)` with `e = max(1, bbox extent)`, `f = 35`, `frame [36, 24]`, `canvas [360, 240]`; note `IMPORT_NO_CAMERA_DEFAULT` |
  | no light | directional `[-0.5, -0.5, 0.7071067811865476]`; note `IMPORT_NO_LIGHT_DEFAULT` |
  | ids | node name with `.` → `_`, empty → `node<k>` / `light<k>`; duplicates suffixed `_2`, `_3`, … |
  Euler decomposition `euler_zyx(R)` (`R = Rz·Ry·Rx`): `ry = atan2(−R[2,0], hypot(R[0,0], R[1,0]))`, `rx = atan2(R[2,1], R[2,2])`,
  `rz = atan2(R[1,0], R[0,0])`; if `hypot(R[0,0], R[1,0]) ≤ 1e-12`: `rx = 0`, `rz = atan2(−R[0,1], R[1,1])`. (M8's
  `euler_zyx_deg` of §5.5.5 is the same decomposition in degrees with the `+ 0.0` canonicalisation; the glTF importer
  may call it.) Import notes are **not** §2.9 warnings: they are printed to stderr as `note: CODE [ids]: message` and
  written under `meta.import_notes` of the scene (`meta` is an unknown key for validation; §5.0.2). Receiver: the ground
  `{"id": "ground", ...}` always.

#### 5.2.9 TypeScript port scope and conformance rules
- `meshprep` (§5.2.3), the fallback (§5.2.5) and the edge rules (§5.2.4) are **core** and are ported (M7 phase 2,
  §5.4.14). Loaders and the importer are not (spec §9 M7 row), exactly like the PNG rasteriser.
- Conformance cases **must** use inline `data` (never `path`); `test_conformance.py` asserts this. No `requires` key is
  introduced. Loader tests are Python-only (`tests/test_loaders.py`, fixtures under `tests/fixtures/meshes/`).
- Existing expected files are unchanged by M5 (mesh-only keys, no new keys on primitive edges, no changed numerics).
- **Versioning with M4 [decision]** (sequence in §5.0.8): M4 regenerates the whole set (v4); M5 is merged **after** M4,
  rebases, and adds its three cases with `--case` only (v5). The README source table gets its rows under a
  milestone-labelled heading (`### M5 網格`) so the textual merge is clean; the "v2 / 34 cases" wording in §4 and the
  README is updated to the actual version / count at each merge.

#### 5.2.10 Fast compromises — accepted / rejected
Accepted: triangles-only glTF (strips / fans expanded, no NURBS / morph / skin); trimesh used purely as a reader of raw
vertices and faces (`process=False`); fan triangulation of OBJ polygons for the ray tests (concave OBJ polygons are a
documented limitation, ear-clipping may replace the fan in M4 without changing the document); the ray cap of 64; the
nesting test by one winding-number evaluation per component (a component whose lowest vertex lies exactly on another
shell is the only ambiguous input; documented).
Rejected: any trimesh processing (`merge_vertices`, `fix_normals`, `process=True`) for the pipeline — version-dependent
ordering breaks bit-determinism and the TS port could not reproduce it; welding to mean positions (breaks the exact box
equality and makes names order-dependent); classifying smooth edges against the camera in stage A (breaks camera
independence of stage A); storing drawn/hidden decisions in stage A; dropping the coplanar merge (changes `form_shadow`
faces and the acceptance equality); `np.unique` on float rows for welding (its row order differs from first-appearance
order); union-find coplanar merge (edge-order dependent partition, §5.2.3 step 6); trig-based axis conversion (§5.2.1);
raising "no usable face" from stage A (validated scenes must render, §5.2.1); reading files inside `validate_scene`
(§5.0.2).

#### 5.2.11 Test contract additions (§4)
- `tests/test_meshprep.py`: weld (27-cell rule incl. two representatives in different neighbouring cells both within `τ`
  → lowest input index wins; `τ = 0`; first-appearance order; fast path result-identical), degenerate faces (incl.
  `[a,b,c,b]`), propagation fix on a box with one flipped face (`MESH_WINDING_FIXED`), inside-out box (signed volume),
  hollow box (outer + inverted inner shell: **no** flip, no warning; light in the cavity is outside), Möbius strip (open)
  and a closed Klein-bottle connectivity (message says "inconsistent winding") → `MESH_NON_MANIFOLD`, open box →
  fallback, coplanar merge of a triangulated box (6 quads, start vertices as §5.2.3 step 6), a centre-fan 16-gon cap
  (start at the first boundary vertex of the seed; centre vertex kept, edge-less), square-ring region (8 triangles, hole)
  left unmerged, strip of 20 triangles bent `1.5e-4` rad per step (regions `{0..6}, {7..13}, {14..19}` on
  `merge_coplanar` directly), smooth / feature classification with and without smoothing groups (different groups →
  feature), `point_inside_mesh` (centre True, outside False, on-face within `tol` False, `|w| > 0.75` rule).
- `tests/test_mesh_pipeline.py`: **acceptance 1** — imported box equals parametric box (§5.2.12, inline data, shuffled
  variant, and end-to-end through `path` with `tests/fixtures/meshes/box_split.obj` plus its `up: "y"` variant, loaded
  with `load_expanded_scene`); **acceptance 2** — open-**bottom** box → `MESH_NON_MANIFOLD`, 5 loops, union = parametric
  shadow (raster IoU and ray-cast IoU ≥ 0.99, exact vertex check); smooth lateral edges of a 16-gon prism are not drawn
  unless camera silhouettes; ray cap; determinism (render twice, bytes equal); stage A camera independence with meshes;
  spec §7.1 rows 1, 2, 4 on a mesh scene; ray-cast IoU on seeded mesh scenes (`make_mesh_scene`); a fallback mesh on a
  bounded receiver (per-face bounds clip, union IoU ≥ 0.99 on the plate).
- `tests/test_loaders.py` (Python only): OBJ fixtures (negative indices, groups, `s`, polygons, continuation), GLB and
  `.gltf` + `.bin` + data-URI fixtures (strided accessors, non-indexed, nested TRS with negative determinant, exact
  Y-up → Z-up), trimesh skipped when absent; `castplane import` on a fixture glTF with a camera, two lights (one spot),
  one extras cylinder, one named mesh and one unnamed mesh (→ `node: <index>`) → exact expected scene JSON that
  re-loads with **both lights** (`IMPORT_SPOT_AS_POINT` note; `--light NAME` keeps one); import notes; exit codes; `up`
  with a glTF path → `SceneError(objects[0].up)`; a dict scene with a relative `path` resolved against the cwd by
  `expand_scene`; `validate_scene` on a `mesh` with `path` only → `SceneError(objects[0].path)` naming `expand_scene`.
- Conformance: three cases added with `--case` after the M4 rebase (v5; nothing regenerated by M5):
  `mesh_box_welded_triangulated`, `mesh_open_bottom_box_fallback`, `mesh_smooth_prism16`; CHANGELOG entry with
  `--reason "add M5 mesh cases (inline data)"`. README gets the `### M5 網格` rows and the rule "mesh cases use inline
  `data`". The full M5 test plan (weld / orientation / merge / classify tables, the acceptance expectations below, CLI
  and benchmark checks) is binding as written in `docs/PLAN-v2.md` §M5.

#### 5.2.12 Acceptance case (hand-computable, spec §10 M5)
Scene = `analytic_unit_box_point_light_overhead` (unit cube at the origin, lamp `(0,0,3)`, camera `(4,−8,5)→(0,0,0.5)`,
f 35, frame 36×24, canvas 360×240) with the object replaced by id `cube`, type `mesh`, inline `data`: vertices `0..7` =
`(−.5,−.5,0),(.5,−.5,0),(.5,.5,0),(−.5,.5,0),(−.5,−.5,1),(.5,−.5,1),(.5,.5,1),(−.5,.5,1)` followed by `8..23` = the same
eight twice (split vertices); faces (12 triangles referencing only the duplicates) `[8,11,10],[8,10,9]` (bottom),
`[12,13,14],[12,14,15]` (top), `[16,17,21],[16,21,20]` (front), `[17,18,22],[17,22,21]` (right), `[18,19,23],[18,23,22]`
(back), `[19,16,20],[19,20,23]` (left). Welding maps `8..23 → 0..7`, order `v0..v7` as the parametric box; the merge gives
the six quads `[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]` in this order (seed start vertices `0,4,0,1,2,3`
are all on their region boundary). Expected: silhouette edges `v4v5, v4v7, v5v6, v6v7` (`silhouette: true`), all 12 edges
`smooth: false`; shadow outline `[v4,v5,v6,v7].shadow.lamp` with world `(−.75,−.75,0),(.75,−.75,0),(.75,.75,0),(−.75,.75,0)`
(base × h/(h−1) = 1.5), feet `(±.5,±.5,0)`, `L' = (0, 87.93525754212652)`, `F' = (0, −15.270708139022979)`, shadow images
`(−35.43926206447239, −21.040388381248047)`, `(12.57114643641712, −33.69048944708911)`,
`(33.42375900867301, −9.829161370289384)`, `(−10.541723693318392, 0.17547618657507147)`; rays `[L v4],[F v4.foot],[L v5],…,[F v7.foot]`
(8, ascending index), 4 checks (`max_error_mm ≤ 1e-9`), `form_shadow` faces bottom + four sides (5), warnings `[]`. The
expected file equals `analytic_unit_box_point_light_overhead` **exactly** except for the two added keys on the 12 edges
(re-verified on the recorded build; both files carry the M4 keys after v4). The pytest acceptance test additionally renders
a *shuffled* vertex order (names differ) and compares with the renaming rule of §5.2.13.

**Acceptance 2 (open-bottom box, fallback)**: same scene, `data` = the 8 vertices above, faces
`[[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]` (top + four sides; bottom edges are boundary edges with
`f_min == f_max`). Expected: warnings `{("MESH_NON_MANIFOLD", ["cube"])}`; 5 loops in face order: top
`[v4,v5,v6,v7].shadow` at `(±.75, ±.75, 0)` (area 2.25); front (unlit, reversed `[0,4,5,1]`)
`(−.5,−.5),(−.75,−.75),(.75,−.75),(.5,−.5)` (CCW, shoelace sum `+0.625`, area `0.3125`); right `(.5,−.5),(.75,−.75),
(.75,.75),(.5,.5)`, back and left by symmetry (each area 0.3125, all inside the top's square) → union = the ±0.75 square,
raster IoU = 1, ray-cast IoU = 1 (`hit_mesh`: a ground ray enters through the open bottom and hits the top face);
`outline` = the top loop; `edges` 12 with `silhouette: true` on the 4 top edges only, `smooth: false` everywhere;
`form_shadow` = the 4 sides; `.shadow` and `.foot` points for all 8 vertices (feet of `v0..v3` are themselves); no rays,
checks, segments; `FACE_PARALLEL_TO_LIGHT` absent (`n·(l − p) = −0.5` on every side).

#### 5.2.13 Equality criteria "imported box = parametric box" (test rule)
With `φ: name ↦ world triple` for `<obj>.v<k>` points: (a) sets of world vertices equal (exact); (b) edges as sets of
unordered world pairs with equal `silhouette` / `back` flags and `segment` endpoints equal as unordered pairs within
1e-9 mm; (c) `form_shadow` faces as sets of **cyclic** world sequences (rotation-invariant), polygons within 1e-9 mm;
(d) shadows: `unbounded` equal, loops as cyclic sequences of mapped names / ground points, polygons within 1e-9 mm;
(e) `points` after renaming: `world` exact, `image` / `depth` within 1e-9; (f) rays as sets of mapped names, checks
`max_error_mm ≤ 1e-9` for the same mapped points, segments per mapped (kind, point) within 1e-9 mm; (g) warning
`(code, ids)` sets equal; (h) horizon / camera blocks exact.

### Implementation notes
- **[decision, implementation] (M5) `triangles` follow the orientation fix.** §5.2.3 lists the fan triangulation as step 4
  and the orientation fix as step 5; the record's `triangles` are the fans of the kept faces **after** propagation and the
  volume / nesting flips (the same triangle set; a flipped face `[f0] + f[1:][::-1]` contributes its fans reversed), so the
  generalised winding number of `point_inside_mesh` sees a consistently oriented surface (with the raw orientation a light
  at the centre of a unit box with one flipped face has `w = 2/3 < 0.75` and would be "outside"). A fallback mesh keeps
  the fans of its kept faces as given. Rays (M4, the ray-cast reference) are orientation-free.
- **[decision, implementation] (M5) Unmerged regions and open edges in `merge_coplanar`.** A region left unmerged (hole or
  pinch) contributes its member faces **in ascending face index at its seed's position** of the seed-ordered output;
  `merge_coplanar` returns `(new_faces, origin)` with `origin[k]` the seed of a merged face or the face itself (the source
  of its smoothing group). An edge with a single face (only possible in a direct call, e.g. the bent-strip test of
  §5.2.11) is a region-boundary edge.
- **[decision, implementation] (M5) Weld details.** Cell keys are `floor(x/τ + 0.5)` of the float quotient; when some `x/τ`
  is not finite (a `τ` far below every float spacing) the weld is the exact `τ = 0` rule. The fast path computes the cell
  occupancy on per-axis compressed cell indices (distinct indices renumbered with gaps capped at 2, so `|Δ| ≤ 1` is kept)
  combined into one int64, merges a vertex directly only when its cell has no occupied neighbour **and** every vertex of
  the cell is within `τ` of the cell's lowest input index (the float quotient may put two vertices more than `τ` apart into
  one cell), and runs the reference loop on all other vertices; `tests/test_meshprep.py` proves it result-identical. The
  degenerate-face collapse keeps the face's first vertex (`[a, b, c, a] → [a, b, c]`).
- **[decision, implementation] (M5) Fallback area test.** "`|area| ≤ tol·scale_A`" uses the stage-A `tol` and the mesh's own
  `scale_A` of §5.2.3 step 1 (stored on the record as `mesh_scale_A`); the receiver-plane area of a bounded loop is
  `½·n̂·Σ X_i × X_{i+1}` of its finite vertices (the shoelace area for the ground).
- **[decision, implementation] (M5, pre-M4 worktree) Receivers.** M5 was built before M4 was merged: the fallback's
  "`obj["clipped"][r] = None` for every receiver" is `obj["ground_mesh"] = None` here (M4 makes `ground_mesh` the alias of
  `clipped[receivers[0].id]` and extends the rule to every receiver); the per-face `clip_polygon_bounds` of a bounded
  receiver and the "fallback mesh on a bounded receiver" test of §5.2.11 need M4's `shadow.clip_polygon_bounds` and are
  added at the M4 / M5 merge. The four `MESH_*` codes sit at the end of `WARNING_CODES` in the M5 branch; the merge keeps
  the §5.0.5 order (after `RECEIVER_UNLIT`). `MESH_RAYS_CAPPED` is evaluated per shadow record, i.e. per (object, light,
  receiver) as §5.2.4 states (§5.0.5's "(object, light)" is the single-receiver reading).
- **[decision, implementation] (M5) API details.** `preprocess_mesh(data, scale, weld_tolerance, smooth_angle_deg,
  object_id="")` takes the object id of its `MESH_*` warnings as an extra keyword (the positional signature is the
  contract's). Every object record carries `fallback` / `prep_warnings` / `mesh["edge_smooth"]` (primitives: `False`, `[]`,
  all False); mesh records add `triangles`, `smooth_groups` and `mesh_scale_A`, and their edge templates carry the
  camera-free `smooth` key. Stage-A shadow records carry `ray_vertices` (a record without it, e.g. an inactive light's empty
  record, draws every row). Validation rejects booleans and floats as face indices / smoothing groups. Until the three v5
  mesh cases are added, `test_set_covers_the_required_sources` requires every kind except `mesh` (a tripwire that fails as
  soon as a mesh case exists).
- **[decision, implementation] (M5) Vertex field paths.** A vertex that is not a list of 3 numbers is reported at
  `objects[i].data.vertices[k]` as the §5.2.1 row says; a non-finite or non-numeric component is reported one level
  deeper, at `objects[i].data.vertices[k][c]`, the `_vector` convention every other vector of §2.0 already follows
  (`transform.position[c]`, ...).
- **[decision, implementation] (M5) Fallback `VERTEX_NOT_BELOW_LIGHT`.** In the per-face fallback of §5.2.5 the "some
  silhouette vertex `w_S ≤ tol`" test of §2.3 reads "some vertex of a face that is **not parallel** to the light" (exactly
  the vertices that can enter a per-face loop; faces with `parallel` are skipped). A vertex used only by light-parallel
  faces never reaches a loop and does not raise the warning. `vertex_ids` / `keep` are unchanged (every kept-face vertex).
- **[decision, implementation] (M5) Coplanar merge after a winding fix.** The merge of step 6 reads each face's edges by
  position, so when step 5 flipped any face it runs on `build_adjacency` of the **oriented** faces (the undirected edge set
  and its numbering are unchanged by flips; only `face_edge_at` / `edge_dirs` differ). A direct `preprocess_mesh` call
  whose faces are all degenerate raises `ValueError("no usable face ...")` (unreachable on a validated scene).
- **[decision, implementation] (M5) Shared helpers.** `preprocess_mesh(..., return_scale=False)`: with `return_scale=True`
  the contract's 5-tuple gains a sixth item, the step-1 `scale_A`, which `primitives.prepared_mesh` stores as
  `mesh_scale_A` instead of recomputing it. The §5.2.1 usable-face guard is `meshprep.has_usable_face(vertices, faces,
  scale, weld_tolerance)` (steps 2–3 on `scale · vertices`), so `scene.py` keeps no numpy import. The §5.2.4 ray
  selection reuses the edge-silhouette mask the shadow record already computed (receiver-clipped or not).
- **[decision, implementation] (M5 part 2) Unreadable mesh files are `OSError`s.** §5.2.1 lists a missing / unreadable
  file among the loader errors re-raised as `SceneError(objects[i].path)`, §5.0.2 (the later, unified rule shared with
  M8) says an unreadable file is an `OSError` (CLI exit 1). §5.0.2 is followed: `expand_mesh_object` re-raises the
  `OSError` of the same class with the message `objects[i].path: <reason>`, so the field is still named; parse errors,
  unsupported features and empty selections are `SceneError(objects[i].path, "<loader field>: <message>")` (OBJ loader
  fields are `line N`, glTF loader fields the glTF JSON path), a failed `node` selection `SceneError(objects[i].node)`.
- **[decision, implementation] (M5 part 2) Two-light glTF imports before M6.** This branch predates M6, so
  `validate_scene` still applies the v1 "exactly one light" row: `castplane import` of a file with ≥ 2 lights emits
  every light as §5.2.8 says, but its validation check fails with `lights` (exit 2, nothing written) until M6 is merged;
  `--light NAME` imports one light. The re-load tests branch on `validate_scene` accepting two lights (they assert
  the `lights` failure before M6 and the two re-loaded lights after it), so they need no edit at the M6 merge.
  **Obsolete since M6 (updated at the M8 merge):** M6 lifted the one-light row, so `castplane import` of the fixture
  `import_scene.gltf` writes both lights (`Lamp`, `Spot` as a point light, note `IMPORT_SPOT_AS_POINT`, exit 0) and
  `castplane render` of the result draws `cast_shadow.Lamp`, `cast_shadow.Spot` and `cast_shadow.umbra` (one umbra
  entry on `ground` with lights `[Lamp, Spot]`, `warnings []`). The branch and its pre-M6 assertions were removed:
  `test_import_fixture_reloads_with_both_lights_or_one_light` and `test_cli_import_gltf_with_two_lights` now assert
  the two-light re-load and render unconditionally.
- **[decision, implementation] (M5 part 2) glTF importer details.** (1) A node selection is a subtree (§5.2.1), so a
  mesh node whose ancestor is already emitted as a mesh object is not emitted again (only the topmost mesh node of a
  branch becomes an object; its object then holds the descendants' meshes) — otherwise the geometry would be imported
  twice. A mesh node whose primitives are all points / lines is skipped. (2) A string `node` that matches no node name
  but a mesh name selects the first node (traversal order) instantiating that mesh, that node alone. (3) `--node`
  emits one mesh object for that selection (the given value; all digits = index); `--id` renames the object only when
  the import yields exactly one object (else a usage `SceneError("--id")`). (4) Ids: empty names → `node<k>` /
  `light<k>` with `k` the **node** index; `sun` is the id of the default light; object ids are de-duplicated against
  the receiver id `ground` (and, with `--into`, against the scene's object and receiver ids; `castplane import`
  applies this to every format, OBJ / STL / PLY included, and an explicit `--id` that collides is a usage
  `SceneError("--id")` instead of being renamed); the reserved ids of §5.0.1 are applied
  to objects as well (`hidden` → `hidden_object`, `core` → `core_object` when the output has ≥ 2 lights). (5) The
  uniform scale `s` of an `extras.castplane` node is the mean column norm of its world matrix, taken as exactly 1 when
  `|s − 1| ≤ 1e-12`, so an unscaled node keeps its parameters verbatim (a rotation's column norms are 1 ± 1 ulp).
  (6) `meta.import_notes` is always written (an empty list when there is no note); with `--into` an existing `meta`
  object is copied and gets the `import_notes` key. (7) `IMPORT_NOTE_CODES` is a dict code → default message (the
  shape of `errors.WARNING_CODES`); M8 adds its `STEP_*` codes to it. (8) Reading: an accessor without `bufferView` is
  zeros (glTF §3.6.2.1); `extensionsRequired` naming Draco, meshopt or mesh quantization is an error, other required
  extensions (materials, textures) are ignored; strips use the glTF rule `(i, i+2, i+1)` for odd `i` (the same cyclic
  triangle as "swapped"). The API adds `gltf.import_gltf_parts` (the pieces before the defaults, used by `--into`) next
  to `import_gltf_scene`.
- **[decision, implementation] (M5 part 2) `castplane import` details.** The validation check runs on the assembled
  scene with the imported meshes' `data` filled in and, with `--into`, the SCENE's own objects expanded relative to the
  SCENE's directory; the written raw scene copies the SCENE's objects verbatim except that, when the output's
  directory (the current directory for stdout) is not the SCENE's directory, a relative `path` of a SCENE object whose
  type has an expander (`mesh`; M8: `step`) is rewritten as the POSIX path of the same file relative to the output's
  directory, so that the written scene re-loads from where it is written (the check above resolves exactly these
  files). A glTF that yields no object (only points / lines, or no mesh node) is `SceneError("meshes", "the file holds
  no triangle")`, the message of the loader. `extras.castplane` parameters are validated as written, before the node
  scale, with the field prefix `nodes[k].extras.castplane` (so a bad size reads `nodes[0].extras.castplane.size[1]`).
  OBJ files are read as `utf-8-sig` (a leading byte-order mark is skipped). Within one `expand_scene` call a
  trimesh-read file (STL / PLY) is read once like OBJ / glTF files (it takes no `node`, so its raw mesh is cached and
  deep-copied per object). `castplane/__init__.py` imports `io` so that `castplane.io` is reachable after a plain
  `import castplane` (§5.0.7); `io` is not in `castplane.__all__` (a star import would shadow the stdlib `io`). An OBJ selection (`node`) drops the unused
  vertices (file order kept); a `.step` / `.stp` FILE is a usage `SceneError` until M8 registers its loader. Conformance:
  the three mesh cases were generated on this pre-M4 branch with `--case`, so their CHANGELOG entry is numbered v4
  here and carries a note that it becomes the M5 v5 entry at the merge (§5.0.8 rule 1).
- **[decision, implementation] (M5 part 2) `tests/test_property.py`.** `test_vertices_above_the_light_only_warn`
  asserted "some vertex below and some above the light ⇒ an unbounded outline" over the whole scene; hypothesis (which
  mines constants from the imported modules, so the new `castplane/io` modules changed its draws) generated two
  separate boxes, one wholly below and one wholly above the light, for which no outline is unbounded. The predicate is
  now evaluated per object (one object straddling the light height), which is what the spec §5.7 row 4 statement means.
- **[decision, implementation] (M4 / M5 merge) What the rebase onto v4 completed.** This supersedes the "pre-M4
  worktree" note above. (1) `pipeline._clip_object` returns `None` for a fallback mesh, so `obj["clipped"][r] = None` for
  every receiver `r` (and `ground_mesh = None`, its alias for `receivers[0]`), on both the unbounded-ground path and the
  bounded-default path; `clip_mesh_to_plane` is never called on a fallback mesh. (2) On a bounded receiver
  `_bounded_object_record` hands a fallback object to `_fallback_shadow_record(obj, ol, lt, rcv["pi"], tol, rid,
  rcv=rcv)`: every non-parallel face loop is shadowed with the receiver frame (`shadow_loop(..., frame, F)`) and cut by
  `clip_polygon_bounds`, then the `< 3` vertices / `|area| ≤ tol·scale_A` drop rule of §5.2.5 is applied to the clipped
  loop; names carry the receiver suffix (`<obj>.v<k>.shadow.<light>.<r>`, `.foot.<r>`); receiver-plane crossings keep the
  undirected-edge key of §5.2.5, and every bounds-clip row (crossing or anchor) is a crossing point of its own
  `<obj>.s<k>.<light>.<r>`, exactly as `_loop_entries` names them for the manifold path; `VERTEX_NOT_BELOW_LIGHT` is not
  emitted (unbounded ground only, §5.1.9) and the record carries M4's `ray_keep` (irrelevant: `ray_vertices` is all
  False). `rcv=None` is the unchanged v2 ground path. (3) The manifold mesh path on a bounded receiver
  (`_bounded_object_record` → `_caster_record`) gets the §5.2.4 `ray_vertices` from `_mesh_ray_vertices` on the loop
  mesh actually used (receiver-clipped or not) and `MESH_RAYS_CAPPED` per (object, light, receiver); `_project_shadows`
  ANDs both masks (`ok &= ray_keep`, then `ok &= ray_vertices`). (4) `shadow_geometry` merges `prep_warnings` before
  the bounded-default branch, so the `MESH_*` warnings are emitted on every receiver configuration. (5) The four
  `MESH_*` codes now follow `RECEIVER_UNLIT` (the §5.0.5 order); the CLI `_run` keeps both changes
  (`load_expanded_scene` + notes, and the `hidden_lines` parameter). (6) Tests: `tests/test_mesh_pipeline.py` adds the
  §5.2.11 "fallback mesh on a bounded receiver" test (the §5.1.11 wall scene and a bounded-floor variant with the crate
  as an open-bottom box: all `clipped` entries `None`, every loop vertex on the plate inside its bounds, ray-cast IoU ≥
  0.99 on each plate — measured 1.0 — and no rays / checks for the crate) and the manifold split-box crate on the same
  two receiver configurations, byte-identical to the parametric crate after deleting the two mesh keys. With hidden
  lines **on**, the mesh crate's runs may differ from the parametric crate's by one bisection step (measured
  `s = 0.66245` vs `0.66255` on one edge of the bounded-floor variant): the occluder of a mesh is its triangle fan
  (§5.2.7), the box's is the exact box, and a sample grazing a box edge can fall on either side of the `1 − eps` test;
  this is inside the conformance runs rule (1e-3 in `s`) and is not asserted byte-for-byte. (7) Conformance: the three
  mesh cases were regenerated on the merged branch (they now carry the M4 keys) and the CHANGELOG entry is the one M5
  milestone entry **v5** (0 existing files changed, 3 added; 43 v4 cases with zero drift), §5.0.8 rule 1.

### 5.3 M6 — multiple lights (amendment to §2.0, §2.3, §2.5–2.10, §3, §3.1, §4)

This section extends the contract to `lights` of any length `N ≥ 1`. Everything of §2–§4 stays in force; the rules
below add to it. The guiding rule is spec §9 (「之後只加功能、不改介面」): **a scene with one light produces exactly the
single-light document of §5.0.3 (the v4 shape: v1 plus the M4 keys) and the single-light SVG, byte for byte**
(**[decision, synthesis]**: the M6 design's "v1 document" reads "the M4-merged document" everywhere below, since M4 adds
unconditional keys and merges first). A document is **multi-light** iff `len(scene.lights) ≥ 2` (`N` below always means
`len(scene.lights)`, inactive lights included; `N_act` means the number of *active* lights, §5.3.1). Every M6 addition to
the document and to the SVG appears **only** in multi-light documents; the existing conformance expected files are
unchanged by M6. Spec §10 lists M4 as M6's dependency: M6 is integrated **after** M4 and M5 (§5.3.9 names the shared files
and the merge order).

#### 5.3.0 Validation (`scene.py`) — replaces the `lights` row of §2.0
| field | rule |
| --- | --- |
| `lights` | **non-empty list** (M6 lifts the v1 length-1 rule; field `lights` when empty or not a list); ids unique (field `lights[i].id`, message names the duplicate), non-empty strings without `.`; **[decision]** in a **multi-light scene only** (`len(lights) ≥ 2`) the ids `umbra` and `core` are rejected (`SceneError(field="lights[i].id", "reserved id in a multi-light scene")`): they are the ids of the `cast_shadow.umbra` / `form_shadow.core` sub-groups of §5.3.6, which exist only in multi-light SVGs, so a v1 scene whose single light is called `umbra` stays valid (§5.0.1 adds: `core` is also rejected as an **object** id in a multi-light scene, `hidden` always, and light ids are disjoint from receiver ids). No upper bound on `N` (spec §9 reserves "an array"; every per-light cost is linear in `N`; the umbra cost is informational, §5.3.9) |
| `lights[i].type` | unchanged (`point` / `directional`, same checks) |
`RESERVED_LIGHT_IDS_MULTI = ("umbra", "core")`. Order of the validated `lights` list = input order ("scene order"); it is
the order of the lights inside the per-receiver `shadows[]` / `form_shadow[]` entries and of `umbra[].lights`. Everything
else in §2.0 is unchanged (the M4 `receivers` row is edited in the same table by M4; the two rows do not interact).

#### 5.3.1 Definitions and the lemma that makes the umbra a drawable
- Per light `k` and receiver `r` (`L_k`, `M_{k,r} = shadow_matrix(π_r, L_k)`, `F_{k,r} = foot(π_r, L_k)`; a light is
  **active on `r`** iff `receivers[r].lit[k]` is true, i.e. for the unbounded ground iff it is not the id of a
  `LIGHT_BELOW_RECEIVER` / `DIRECTIONAL_HORIZONTAL` warning and for a bounded receiver iff no `RECEIVER_UNLIT` names
  `[k, r]` — **[decision, synthesis]**, the per-receiver form of M6's "active") the **drawn cast-shadow region** of `r` is
  `W_k = ∪_casters shadow(caster, L_k)` (the nonzero-filled union of all `shadows[]` loops of light `k` on that receiver,
  §2.5; casters include the other plates, §5.1.3.1). `lit`, silhouettes, terminators, `w_S`, receiver clip, construction
  points, `L'_k`, `F'_{k,r}`, rays and self-checks are evaluated **per light with the v1 / M4 formulas**, each light
  exactly as if it were alone (§2.3–§2.7, §5.1 with `L = L_k`).
- **Umbra (本影) as emitted [decision]**: `umbra[].polygons` is the intersection of the **drawn** regions `W_k` of the
  lights listed in `umbra[].lights` (the lights active on that receiver, in scene order), **computed only when
  `N_act(r) ≥ 2`**; otherwise it is `[]` by decision: with one active light the whole of its region is trivially unlit by
  every active light and is already drawn by its own sub-group, and with no active light the physical umbra (the whole
  receiver) is intentionally not emitted. The definition is about the drawn regions, not about physics: an inactive light
  lights no point of the receiver's upper side and is left out of the intersection (identity element); a point light
  inside an object (`LIGHT_INSIDE_OBJECT`) is **not** left out, and its `W_k` is the drawn region (the other objects'
  shadows), so the emitted umbra is a **subset** of the physical umbra in that case (physically such a light lights
  nothing). This is the v1 convention for that warning (the light's other shadows are kept) carried through, so the umbra
  never disagrees with what the sub-groups draw (§5.3.8, D43).
- **Penumbra (半影)** = `(∪_k W_k) \ U` when `N_act ≥ 2`: in shadow of at least one but not all active lights. It is
  **not materialised [decision]** (spec §9 「半影區分」 is met in the picture by the per-light sub-groups and the umbra
  path on top, and in the document by derivability): the per-light sub-groups draw `W_k` at reduced opacity and the umbra on top (§5.3.6), so the
  penumbra is what remains visible of the per-light groups; a consumer derives penumbra polygons as `W_k` minus the umbra
  pieces (nothing in the document needs polygon subtraction).
- **Form-shadow core** = the faces of a polyhedral object (a bounded receiver counts as a one-face polyhedron, §5.1.8)
  unlit by **every** light (`lit_k(f) == False` for all `k`, "parallel" counting as unlit, a light inside the solid making
  every face unlit; inactive lights included, because their lit flags are computed by the v1 rule). A face unlit by some
  but not all lights is drawn at reduced opacity in those lights' sub-groups only (§5.3.3, §5.3.6). Curved objects have
  no core entry (their unlit surface regions are not polygons).
- **Lemma (projective invariance) [decision]**: let `φ` be the central projection of the receiver plane to the image
  (`x̃ = P·X`), `H⁺` the part of the plane in front of the near plane (`ν ≥ 0`; `near > 0`, so `H⁺` excludes the camera's
  principal plane `x̃3 = 0`). `φ` is injective on `H⁺`, hence `φ(A ∩ B) = φ(A) ∩ φ(B)` for `A, B ⊂ H⁺`, and for the
  extended rectangle `R` of §2.2 step 3 `R ∩ ∩_k φ(W_k ∩ H⁺) = φ((∩_k W_k) ∩ H⁺) ∩ R`. Segments map to segments, so the
  per-light **drawables** `shadows[].polygons` (the §2.2 pipeline on each loop) are exactly the polygons `φ(loop ∩ H⁺) ∩ R`
  (Sutherland–Hodgman of a non-convex loop may add zero-width bridge edges along the clip lines, which carry no nonzero
  winding). Therefore **the image-space intersection of the per-light drawn regions is the exact image of the world
  umbra** restricted to `H⁺` and `R` (which contains the canvas), computed from the drawables alone — no world-space
  polygon booleans, no points at infinity (every drawable vertex is finite). The umbra is a **camera-dependent drawable of
  stage B/C** (like construction rays): no world coordinates, no named points; every per-light shadow record stays camera
  independent (spec §7.1 row 2 unaffected; stage A never touches the camera). The world umbra's image on receiver `r` is
  recovered exactly by the inverse homography `H_r⁻¹`, `H_r = P·E_r` with `E_r = [e1 e2 o_r; 0 0 1]` (4×3), `(e1, e2)` the
  receiver frame of §5.1.2 and `o_r = −d·n` a point of the plane (for the ground this is `H = P[:, (0, 1, 3)]`), which is
  how the tests check it **[decision, synthesis]**. The lemma holds per receiver plane, and because every `shadows[]`
  record lies on exactly one receiver (a folded shadow is two records, §5.1.3), the umbra composes with M4 without change.
- The umbra of a curved object's shadow is the umbra of its **sampled** drawable polygon (`shadows[].polygons[0]`, §2.6
  (b)); the exact conic boundary stays in `shadows[].conics` and is drawn stroke only. The umbra boundary carries the
  §2.6 sampling error and the `tol_mm` of §5.3.4 and nothing else **[decision]** (no conic–conic intersections).

#### 5.3.2 Stage A per light (`pipeline.shadow_geometry`, `curved.stage_a_object`)
- `A["lights"]` holds one `_light_record` per light in scene order (each with its `per_receiver` data, §5.1.2);
  `A["shadows"]` holds one record per (receiver, light, caster) in the order of §5.1.3.1 — receiver (scene order), then
  light (scene order), then caster — **[decision, synthesis]** (the M6 design's "object-major, light-minor" loop is
  superseded; for one receiver and one light every order coincides), each carrying `light`, `receiver`, `object`;
  `obj["lights"][lid]` and `obj["curved"][rid][lid]` are keyed by light id as today. Inactive lights and lights inside an
  object produce the v1 empty record. Ground points `<obj>.s<k>.<light>[.<r>]` are counted per (light, receiver) as today.
- **Row independence [decision, tested]**: every number of a light's stage-A and stage-B data is computed by the v1
  kernels on that light's own rows; `scene_scale_A`, `tol`, the receiver clips and the mesh cut are light independent, and
  the batched kernels (`project`, `nu`, `clip_segments_*`, `_project_polygons`, `self_check`) are row independent by
  contract. **Bit-identity statement (what is compared)**: for every light `k` of a multi-light scene, (1) the `shadows[]`
  entries with `light == k`, (2) `constructions[k]` (incl. `per_receiver`), (3) `form_shadow[]` entries with `light == k`
  (`faces`, `polygons`, `terminator`) and (4) the `points` entries whose name contains `.<k>` as a segment or is a shared
  name (`<obj>.v<j>`, `<obj>.v<j>.foot[.<r>]`, `<obj>.c`, `<obj>.apex`, `<obj>.og<j>.*`, `<r>.b<j>`, `L.<k>`,
  `F.<k>[.<r>]`) equal, bit for bit, the corresponding parts of the single-light document of that light after the name map
  of the next bullet. Keys that legitimately differ are `edges[].silhouette` (OR), `edges[].silhouette_lights`,
  `receivers[].lit / casts` (more keys), `construction` (first light only), `warnings[].message`, the other lights'
  `points`. `project` is a BLAS matmul (`X @ P.T`): row stability across batch sizes is **not guaranteed by any BLAS**;
  the test `tests/test_multilight.py::test_per_light_records_bit_identical` is the witness (it holds on the recorded
  build), and if it ever fails on a build, `camera.project` / `camera.nu` switch to `np.einsum("ij,kj->ik", X, P)` (fixed
  per-element 4-term sums), which the TypeScript port implements as plain 4-term sums anyway.
- **Curved construction point names [decision, grammar preserving]**: the silhouette points of a curved object depend on
  the light (`sil.<k>`, `g<k>.base`, `g<k>.top`); the centre and apex do not. In a multi-light document the
  light-dependent **base** names carry the light id as their last segment: `<obj>.sil.<k>.<light>`,
  `<obj>.g<k>.base.<light>`, `<obj>.g<k>.top.<light>`. The §3.1 composition rule is **unchanged**: shadow =
  `<base>.shadow.<light>[.<r>]` (= `<obj>.sil.<k>.<light>.shadow.<light>`, the light id appears twice on purpose), foot =
  `<base>.foot[.<r>]` (= `<obj>.sil.<k>.<light>.foot`, unique because the base is). `<obj>.c`, `<obj>.apex`, `<obj>.v<k>`,
  `<obj>.v<k>.foot`, `<obj>.og<k>.*` keep their v1 names and are shared by all lights (the `points` dict merges
  bit-identical entries; a `<obj>.v<k>.foot` entry exists iff the vertex is a silhouette vertex of some light). The name map
  of the bit-identity statement is therefore one substitution applied to every name: `sil.<k>` → `sil.<k>.<light>`,
  `g<k>.base|top` → `g<k>.base|top.<light>`. Implementation rule: `curved.construction_points(analytic, L, tol, obj_id,
  light_id=None)` appends `.<light_id>` to the light-dependent stems when given; `stage_a_object(obj, lights, receiver,
  tol, warnings, multi=False)` passes it iff `multi`; the five sites that compose names by string arithmetic —
  `stage_a_object` (`shadow_names`, `foot_names`), `curved._loop_entries` (`keep_names` lookup, `end_name`, `sil` quarter
  points), `curved._terminator_segment_names`, `pipeline._project_shadows` (`rays` `F` entries) and the SVG label filter —
  take the **base** names from the record's `vertex_names` / `obj["curved"][rid][lid]["points"]` keys (via
  `multilight.curved_stem_name(obj_id, stem, light_id, multi)`) and append only `.shadow.<light>[.<r>]` / `.foot[.<r>]`;
  `rec["foot_names"]` is the source of the `rays` `F` entries. The label rules of §5.0.4 stay as they are; `sil.0.west` is
  labelled with its `rest`. In a single-light document nothing changes.
- Warnings: all codes of §2.9 / §5.0.5 keep their predicates and **ids**; per-object codes are deduplicated across lights
  (`merge_warnings`); the message of an `[object]` warning names the light that first triggered it (messages are not
  compared). **No new warning code**.

#### 5.3.3 Stage B per light (`pipeline.project_scene`, `_project_polyhedra`, `_project_shadows`, `curved.stage_b_objects`)
- `B["lights"]` = one `_project_light` record per light (`LIGHT_BEHIND_CAMERA`, `LIGHT_POINT_AT_INFINITY`,
  `SHADOW_VP_AT_INFINITY` per light and — M4 — per receiver, ids `[light]` / `[light, receiver]`). `_project_shadows`
  already groups records by light for rays and self-checks; the per-record `rays` / `segments` / `checks` are assembled
  per light into `B["constructions"][lid] = {light_point, light_point_at_infinity, shadow_vp, shadow_vp_at_infinity, rays,
  checks, segments, per_receiver}` (lists concatenated over that light's records in `shadows[]` order; the default
  receiver's in the flat keys, every other receiver's in `per_receiver[<r>]` as §5.1.5; v1 concatenated over all records,
  which for `N = 1` is the same) and `B["construction"] = B["constructions"][lights[0].id]` (same object).
  `CONSTRUCTION_CHECK_SKIPPED` ids are point names, which carry the light.
- `_project_polyhedra(objs, cam, tol, light_ids)` takes the list of light ids: `edges[].silhouette` is **true iff the edge
  is a silhouette edge of at least one light** (OR; unchanged for `N = 1`; for a receiver bounds edge: `casts[k]` of some
  light), and in multi-light documents the additive key `edges[].silhouette_lights` lists the ids of the lights for which
  it is one (scene order, `[]` allowed) **[decision]**, computed from `obj["lights"][lid]["edge_silhouette"]` where the OR
  is formed (the per-light silhouette is not recoverable from `shadows[].loops` in general: clipped loops contain `s<k>`
  points and cut-face edges, unbounded loops contain direction entries). Unlit faces: the set of faces unlit by **at least
  one** light is projected **once** (for `N = 1` exactly the v1 set, same batched kernel, same floats); the per-light lists
  `form_by_light[lid] = (faces, polygons)` and `form_core = (faces, polygons)` (faces unlit by all lights, face-index
  order) reference the same drawable objects. Plates (§5.1.8) follow the same rule with their single face.
- Curved objects: `curved.stage_b_objects` keeps `terminator` and `shadow_arcs` keyed by light; stage C emits one
  `form_shadow[]` entry per (light, curved object) holding that light's terminator when `N ≥ 2` (v1 merged all lights'
  terminators into one entry, the same thing for `N = 1`).
- `project_scene(scene, A, camera=None, umbra=True)`: the umbra of §5.3.4 is computed in stage B from the stage-B
  drawables when `N ≥ 2`; `umbra=False` (never the default; an interactive caller's choice, M7) leaves `umbra[].polygons`
  as `null` ("not computed", distinct from `[]`) and changes nothing else. Conformance always computes.
- `POINT_BEHIND_CAMERA` stays per object (emitted once).

#### 5.3.4 Umbra computation (`castplane/umbra.py`, stage B; numpy only; deterministic; one scanline kernel)
Input: for a receiver, for every light **active on it** in scene order, the list of its records' drawables
`shadows[].polygons` (lists of `[u, v]` canvas-mm vertices, exactly the numbers written in the document), one sub-list
per record (caster). The umbra is a **pure function of `shadows[].polygons`, `umbra[].lights` and `canvas_mm`**, so a
port recomputes it from the JSON alone (tested). With fewer than two active lights the result is `[]`. Tolerances
(`umbra.tolerances(canvas_mm)`): `D = 1.5 · max(canvas_w, canvas_h)` (the extent of the extended rectangle),
`tol_mm = 1e-9 · D`, `tol_area = 1e-9 · D²`.

**Kernel** `scan_pieces(polygons, groups, lines, n_groups, tol_mm, tol_area) -> (pieces, sides)` — a nonzero scanline
decomposition with one winding counter per group, used twice (per record with one group, then once per receiver with
one group per active light). `polygons[i]` is an `(n_i, 2)` array, `groups[i]` its group, `lines[i]` an `(n_i,)` int
array of **line ids** of its edges (edge `e` runs from vertex `e` to vertex `(e + 1) mod n_i`); polygons with fewer than
three vertices are ignored. **[decision]** The kernel replaces ear clipping (fails the nonzero rule on self-intersecting
shadow loops of concave prisms), the pairwise convex clip and the per-light union pass of earlier drafts (measured at
61 226 raw trapezoids per light on the benchmark scene and ≈150 000 pieces after a union pass).
1. **Vertex events and snapping**: all vertex `v` values sorted ascending (`np.sort`); greedy merge: the first value is
   kept, each following value is kept iff it exceeds the last kept value by more than `tol_mm`; every vertex's `v` is
   **replaced by the kept value it merged into** (so no vertex lies strictly inside a slab, and nearly horizontal edges
   become exactly horizontal). `u` is never changed.
2. **Edge table** in input order (polygon order, then edge order): `(u0, v0, u1, v1, dir, group, line)` with `dir = +1`
   if `v1 > v0` else `−1`; edges with `v0 == v1` (after snapping) are discarded. The **edge index** is the position in
   this table.
3. **Crossing events**: candidate pairs `i < j` are the pairs whose `v`-ranges and `u`-ranges overlap (closed comparisons,
   `≤`), enumerated by a sweep on the `v`-sorted edge table and listed in lexicographic `(i, j)` order, **excluding
   consecutive edges of the same polygon** (they only reproduce their shared vertex up to rounding). For a pair:
   `r = (u1_i − u0_i, v1_i − v0_i)`, `s = (u1_j − u0_j, v1_j − v0_j)`, `den = r_u·s_v − r_v·s_u` (pairs with `den == 0` are
   skipped), `qp = (u0_j − u0_i, v0_j − v0_i)`, `t = (qp_u·s_v − qp_v·s_u)/den`, `s = (qp_u·r_v − qp_v·r_u)/den`; a crossing
   iff `0 ≤ t ≤ 1` and `0 ≤ s ≤ 1` (no tolerance); its event is `v_x = v0_i + t·(v1_i − v0_i)` (edge `i`'s
   parametrisation, `i < j`; a port must use this formula). Crossing events within `tol_mm` of a kept vertex event (on
   either side) are dropped; the remaining ones are sorted and greedily merged with `tol_mm`; the **event list** is the
   sorted union of the vertex events and the merged crossing events (vertex events are never dropped).
4. **Slabs**: consecutive events `[a, b]`, `y_m = (a + b)/2`; an edge is active iff `(v0 − y_m)·(v1 − y_m) < 0`;
   `x(y) = u0 + (y − v0)·((u1 − u0)/(v1 − v0))` with exactly that association and the **exact-endpoint rule** `x(v0) = u0`,
   `x(v1) = u1` (tested by `y == v0` / `y == v1`), so that a drawable vertex that bounds a slab is emitted bit-exactly and a
   second scan over emitted pieces reproduces their vertices; active edges are ordered by `(x(y_m), edge index)`
   (`np.lexsort`); for every group `g`, `w_g(k)` = Σ `dir` over the first `k + 1` ordered edges of group `g`; interval `k`
   (between ordered edges `k` and `k + 1`) is **inside** iff `w_g(k) ≠ 0` for every group.
5. **Runs and clamp**: a maximal run of consecutive inside intervals `[k0, k1]` gives one raw piece bounded by edge `k0`
   on the left and edge `k1 + 1` on the right (intermediate edges are interior to the filled region). **Zero-width
   bridging** (M6 review, implementation note below): a valid interval `k` with `x_{k+1}(y_m) − x_k(y_m) ≤ tol_mm`
   (coincident edges, e.g. an edge shared by two loops of one record) does not end a run — a run is a maximal sequence of
   inside-or-zero-width intervals that holds at least one inside interval, trimmed to its first and last inside
   interval (`k0`, `k1`); with `x^l`, `x^r`
   the two edges' abscissae: `x_a^lo = min(x^l(a), x^r(a))`, `x_a^hi = max(…)`, likewise at `b` (the per-end clamp absorbs
   a crossing that was merged into a slab boundary, which would otherwise give a bow-tie; the clamped lobe has height
   `≤ tol_mm` and area `≤ ½·tol_mm·D = tol_area/2`); the raw piece is dropped iff `x_a^hi − x_a^lo ≤ tol_mm` **and**
   `x_b^hi − x_b^lo ≤ tol_mm`. Raw pieces are ordered by (slab, `k0`).
6. **Run-merge across slabs**: a raw piece of slab `s + 1` whose ordered key `(line of the left edge, line of the right
   edge)` equals the key of the raw piece that last extended a merged piece in slab `s` extends that merged piece
   (replacing its top); otherwise it starts a new merged piece. Two straight lines that do not cross inside the band bound
   a convex region, and a crossing changes the ordered key, so merged pieces are convex. Merged pieces are ordered by
   their first raw piece.
7. **Output**: a merged piece with bottom `(x_lo, x_hi, a)` and top `(x_lo', x_hi', b)` has the vertices `(x_lo, a)`, then
   `(x_hi, a)` iff `x_hi − x_lo > tol_mm`, then `(x_hi', b)`, then `(x_lo', b)` iff `x_hi' − x_lo' > tol_mm`
   (counter-clockwise in the `v`-up frame; a collapsed end makes a triangle); pieces with fewer than three vertices or
   shoelace area `≤ tol_area` are dropped; each piece is rotated to its **canonical start**: among the vertices with
   `v ≤ v_min + tol_mm` the one with the smallest `u` (ties within `tol_mm` in `u`: the lowest index).
   `sides[p] = (line_left, line_right)` of piece `p`.
`record_pieces(polygons, tol_mm, tol_area)` = `scan_pieces` of one record's loops with a single group and line ids =
running edge index over the record's loops (every raw interval has winding `±1` per loop; holes are reversed loops).
`umbra_pieces(per_light, canvas_mm)`: for each active light `k` (scene order) and each of its records `r` (`shadows[]`
order) the pieces of `record_pieces` become input polygons of **one intersection scan** with group `k` and line ids
`base_{k,r} + side` (`base` = running total of the records' edge counts, so ids are globally unique; a piece's upward
edge gets its right line, its downward edge its left line, horizontal edges `−1`); `n_groups` = the number of active
lights. All record pieces are counter-clockwise (winding `+1`), so within one light the counters add and can never cancel
(the per-record nonzero rule is preserved: a reversed loop of one record cannot cancel another record), and an interval
is inside iff every light's counter is nonzero. Output = the pieces (canonical floats).
**Properties**: every piece is convex (a trapezoid or triangle bounded by two input edges and two event lines), CCW, has
`≥ 3` vertices and area `> tol_area`; the pieces have **pairwise disjoint interiors** (one slab decomposition) and their
union equals `φ(U ∩ H⁺) ∩ R` **exactly for the snapped input** (vertices moved by `≤ tol_mm` in `v`), up to the clamped
lobes of step 5 and the dropped pieces of step 7; as a set the result does not depend on the light order (only the output
order and the line ids do, both fixed by scene order). Degenerate cameras: a camera on the receiver plane makes every
drawable degenerate (zero area) → no pieces, no exception; a camera below the receiver reverses the orientation of the
drawables, which the nonzero rule absorbs (tested). Cost per scan: `O((E + X)·log E)` for `E` edges and `X` crossings
(the sweep enumerates candidate pairs by `v`-overlap; the slab loop is processed in chunks of slabs with only the edges
whose `v`-range overlaps the chunk, and the sort is over active (slab, edge) entries only; no boolean table exceeds
8 MB). Measured prototype (§5.3.9): benchmark scene with two lights: 3 637 record pieces per light, 3 514 umbra pieces,
IoU 1.0 against the raster AND; the three-light concave case: 25 pieces.

#### 5.3.5 Document format — amendments to §3.1 (multi-light documents only; `N = 1` is byte-identical to the single-light shape; the full listing is §5.0.3)
```
constructions {<light id>: {light_point, light_point_at_infinity, shadow_vp, shadow_vp_at_infinity,
                            rays, checks, segments, per_receiver}}   -- one M4 construction block per light
construction  (unchanged shape) = constructions[lights[0].id]   -- legacy alias, identical content
umbra [{receiver, lights: [light ids active on that receiver, scene order], polygons: [[[u,v], ...], ...] | null}]
                                                               -- one entry per receiver; polygons = the §5.3.4 pieces,
                                                               -- [] when N_act(r) < 2, null only when project_scene(umbra=False)
form_shadow [{light, object, faces, polygons, terminator}]     -- one entry per (light, object | plate) with unlit faces or a
                                                               -- terminator; light-major (scene order), then object order
form_shadow_core [{object, faces, polygons}]                   -- polyhedral objects and plates with ≥ 1 face unlit by all lights,
                                                               -- object order; faces in face-index order
edges[].silhouette                                             -- OR over lights (§5.3.3)
edges[].silhouette_lights                                      -- [light ids, scene order] for which the edge is a silhouette edge
points                                                         -- light-dependent curved base names of §5.3.2
shadows[]                                                      -- unchanged entries, receiver → light → caster order (§5.1.3.1)
```
Keys `constructions`, `umbra`, `form_shadow_core`, `form_shadow[].light` and `edges[].silhouette_lights` exist **iff
`N ≥ 2`** **[decision]** (a single-light document is the §5.0.3 single-light document; a multi-light document is that plus
exactly these elements). **Normative invariants for the port**: (a) the `shadows[]` records of `receivers[0]` whose
`object` is the first caster list every light in scene order (so scene order is recoverable from `shadows[]`); (b) a light
is active on receiver `r` iff `receivers[r].lit[k]`, and `umbra[].lights` is exactly that list in scene order — the
**primary** source for a consumer; (c) `umbra[].polygons == umbra_pieces([[sh.polygons for sh in shadows if sh.receiver ==
e.receiver and sh.light == k] for k in e.lights], canvas_mm)` bit for bit. All numbers in `umbra[].polygons`,
`constructions.*.segments[].points`, `light_point`, `shadow_vp`, `max_error_mm` are canvas mm (conformance tolerance
1e-6 mm); `rules.json` lists `constructions.*.segments[].points` and `constructions.*.per_receiver.*.segments[].points`
under `mm_key_paths` (§5.0.8; `polygons` is already an mm key). Serialisation unchanged (`sort_keys`, so `constructions` is
written by key order and `form_shadow[]` in list order). If a later synthesis regenerates the whole set, the multi-light
keys **stay conditional**: spec §9 forbids changing the v1 shape and the conditional rule costs one flag in a port.

#### 5.3.6 SVG — amendments to §2.10 (multi-light documents only; the writer detects a multi-light document by the `constructions` key; `N_act = max(1, number of distinct ids in the union of all umbra[].lights)`; light sub-groups are ordered by light id in code-point order, as `cast_shadow.<light>` already is; object sub-groups keep document order; the unified sub-group order incl. the M4 hidden groups is §5.0.6)
| layer | multi-light structure (bottom → top inside the layer) | style |
| --- | --- | --- |
| `form_shadow` | per light `<g id="form_shadow.<light>" fill-opacity="<0.18/N_act>">` holding `form_shadow.<light>.<obj>` with the polygons of that light's entry **except the faces listed in `form_shadow_core`** (writer rule; the document keeps them in the per-light entry) and `form_shadow.<light>.<obj>.terminator` (that light's terminator, v1 terminator style); then `<g id="form_shadow.core">` (no attributes: inherits the layer's `fill-opacity="0.18"`) holding `form_shadow.core.<obj>` (the `form_shadow_core` polygons) | per-light opacity `_f(0.18 / N_act)`; composite: a core face `0.18` (the v1 tone), a face unlit by `m` of the lights `1 − (1 − 0.18/N_act)^m` (`0.09` for `m = 1`, `N_act = 2`) |
| `cast_shadow` | per light `<g id="cast_shadow.<light>" fill-opacity="<0.3/N_act>">` with the v1 / M4 content (`<path>` per record, `fill-rule` inherited, `cast_shadow.<light>.<obj>.conics` stroke only, `.outline` when hidden lines are on, strokes at full opacity); then `<g id="cast_shadow.umbra" fill="#000" fill-opacity="0.3" stroke="none">` with **one `<path>` per `umbra[]` entry** whose `polygons` is a non-empty list, its subpaths being all pieces (`M … Z` each, CCW; one path, so no rasteriser seams between adjacent pieces; no stroke: every umbra boundary edge is already stroked by a per-light outline). Entries with `[]` or `null` produce nothing (the group is still written) | per-light `_f(0.3 / N_act)`; umbra `0.3` on top. Composite for `N_act = 2`: umbra `1 − 0.85²·0.7 = 0.49425`, penumbra of one object `0.15`, two overlapping objects of the same light `0.2775` (the v1 overlap behaviour at half tone; `fill-opacity` is inherited per element — a group `opacity` was rejected because it would also fade the outlines and break v1 parity); with one active light of two the per-light group is at `0.3` and the umbra path is empty, i.e. the v1 picture |
| `construction` | per light `<g id="construction.<light>">` holding that light's `L′` / `F′` markers (incl. every receiver's `F′_r`; unchanged shapes and colours) and `construction.<light>.LP` / `.FQ` / `.PQ` (unchanged ray colours) | unchanged; the group lets a painter toggle one light |
| `labels` | rules of §5.0.4 (`.shadow` / `.foot` parts are not labelled; heads `s<k>` / `og<k>` are not); light-dependent curved base names are labelled with their `rest` (`sil.0.lampA`) | unchanged |
| `horizon`, `objects` | unchanged | unchanged |
For `N = 1` the writer emits the single-light structure exactly (no `fill-opacity` overrides, no `umbra`, `core` or
per-light construction groups). `write_svg(doc, layers=None, hidden_style="dashed")` signature as §5.0.7; `--layers`
selects whole layers only.

#### 5.3.7 Numerics and determinism (adds to §2.8)
- `tol_mm` / `tol_area` of §5.3.4 are the only new tolerances **[decision]**; they derive from `canvas_mm` (document data),
  not from spec §5.8's scene scale, because the umbra lives in canvas mm (D44); `tol_mm` (5.4e-7 mm for a 360 × 240 canvas) is below the 1e-6 mm
  conformance tolerance.
- All umbra predicates are `>` / `≤` against those tolerances or exact equality of snapped values; sorting keys are
  `(value, index)` pairs; input order is scene order (lights), `shadows[]` order (records), loop and edge order; crossing
  pairs are lexicographic. Every emitted float goes through `+ 0.0`. The computation uses fixed-shape expressions and
  order-defined prefix sums only. Any float `%` introduced here follows the `pymod` rule of §5.4.4 (4) in the port.
- **Build stability**: piece count, canonical start and vertex **sets** are build independent whenever no predicate of
  §5.3.4 is within rounding of its threshold; snapping and the exact-endpoint rule make the coincidences that are normal
  in a scene (ground-contact vertices shared by all lights' loops, vertices on other lights' edges) exact rather than
  ulp-dependent, so the acceptance case has no such predicate. Vertex positions may drift by the usual ≈1e-12 mm between
  libms (§4), which the comparator tolerates.
- **Rigid equivariance (spec §7.1 row 4)**: holds for the piece **unions** (receiver images equal in area within 1e-9
  relative and symmetric difference ≤ tol_area · pieces) on every scene, and for piece vertices with the §4 (i) scaled
  tolerance `1e-6 mm × max(1, |defining image coordinate|)` because a crossing vertex inherits the conditioning `1/sin θ`
  of the two edges (the acceptance scene is benign and passes at 1e-6 mm).
- Opacity strings are `_f(0.3 / N_act)` / `_f(0.18 / N_act)` (4 decimals, trailing zeros stripped): `0.15`, `0.09`,
  `0.1`, `0.06`, `0.075`, `0.045`.

#### 5.3.8 Warnings — no change to §2.9 / §5.0.5
No new code; predicates and ids unchanged; `[object]` warnings deduplicate across lights; `[light]` warnings are per
light; messages may name the light. Not degenerate (no warning): two lights at the same position (umbra = that shadow),
all lights inactive (`umbra[].lights == []`, `polygons == []`), a light inside an object for one light only (its empty
record; the umbra is computed from the drawn regions and is a subset of the physical umbra, §5.3.1 [decision]), fewer than
two active lights (`polygons == []`).

#### 5.3.9 API, CLI, performance, shared files (adds to §3, §4)
- Public API unchanged except the keyword: `render`, `shadow_geometry`, `project_scene` (new keyword `umbra=True`),
  `compose`, `write_svg` (§5.0.7). New public helpers in `castplane.umbra`: `tolerances(canvas_mm) -> (tol_mm, tol_area)`,
  `scan_pieces(polygons, groups, lines, n_groups, tol_mm, tol_area) -> (pieces, sides)`,
  `record_pieces(polygons, tol_mm, tol_area) -> (pieces, sides)`, `umbra_pieces(per_light, canvas_mm) -> list`,
  `umbra_from_document(doc) -> list` (recomputes every `umbra[]` entry from `shadows[]`, `umbra[].lights` and
  `canvas_mm`; returns `[]` for a document without the key; must reproduce `doc["umbra"]` bit for bit; the port's
  reference). The multi-light assembly lives in `castplane/multilight.py` (§5.3.2/§5.3.3 helpers) so that the diff in the
  files shared with M4 and M5 is a handful of hooks.
- CLI: `castplane info` lists every light (id, type, position / direction, active per receiver); nothing else changes.
- Performance (spec §8): the gate `benchmarks/bench.py --gate full` keeps the single-light benchmark scene and targets
  (the `N = 1` code path is unchanged; the spec §8 numbers are re-measured and recorded). New informational rows
  `--lights 2` and `--lights 3` (the benchmark light mirrored about the scene centre in `x`, then in `y`): full render
  and camera-only re-render with and without the umbra (`--no-umbra`, i.e. `umbra=False`), and the umbra alone. Measured
  with the design prototype on the CI container (two lights): 3 637 record pieces per light, 3 514 umbra pieces, 2.3 s of
  which ≈ 0.3 s is the numpy core (the rest is per-piece Python in the prototype; the implementation vectorises every
  per-piece step and records its own numbers). No target is set for `N ≥ 2` (spec §8 names one light); the M7 UI skips
  the umbra during drags via `umbra=False`. A further informational row times `record_pieces` on a 2 000-edge loop (the
  M5 mesh case).
- **Shared files and merge order** (spec §10: M6 ← M4; here M6 follows M5 as well, §5.0.8): M6 edits `pipeline.py`
  (`_project_polyhedra` signature, `project_scene`, `compose`: hooks only), `scene.py` (`lights` row), `output/svg.py`
  (three layer builders branch to `svg_multilight.py`), `curved.py` (name composition), `cli.py`,
  `tests/reference/random_scenes.py` (`assemble_scene(objects, lights, camera)` accepting a list;
  `make_scene(seed, n_objects, n_lights=1)` byte-identical for the frozen seeds), `tests/test_conformance.py`,
  `tests/conformance/README.md` and `CHANGELOG.md`, `benchmarks/`, `docs/`. M6 is rebased on the merged M4 + M5 branch
  before its conformance step, so the set gets a single next version (v6, `regen_conformance.py::next_version`).

#### 5.3.10 Test contract (adds to §4)
- **Acceptance case (spec §10 M6), hand computable** — `tests/conformance/cases/multilight_two_point_symmetric_box.json`:
  `cube` = box `size [1, 1, 1]` at the origin (spans `[−0.5, 0.5]² × [0, 1]`); lights `west` = point `(−2, 0, 2)`,
  `east` = point `(2, 0, 2)`; receiver `ground`; camera `position (0, −6, 4)`, `target (0, 0, 0)`, `roll 0`, `f = 35`,
  `frame [36, 24]`, `shift [0, 0]`, `near 0.05`; `canvas [360, 240]` (`s = 10`).
  Hand values: shadow of a top vertex under `west`: `t = l_z/(l_z − p_z) = 2`, `S = 2P − L`; the lit faces of `west` are
  the `−x` face and the top (the `±y` faces have `n·(l − p) = −0.5 < 0`), so its shadow loop is the CCW hexagon
  `(−0.5, 0.5), (−0.5, −0.5), (1, −1), (3, −1), (3, 1), (1, 1)` (area 6.25); `east` is its mirror in `x`. Umbra = hexagon ∩
  mirrored hexagon = the hexagon `(±0.5, ±0.5), (0, ±2/3)` (lower boundary `y = −0.5 − (0.5 − |x|)/3`), ground area
  **7/6**. Camera: `forward = (0, 6, −4)/√52`, `right = (1, 0, 0)`, `up = (0, 4, 6)/√52`,
  `P = [[350, 0, 0, 0], [0, 1400/√52, 2100/√52, 0], [0, 6/√52, −4/√52, √52]]`; a ground point maps to
  `u = 175√52·x/(3y + 26)`, `v = 700·y/(3y + 26)`. Expected document (multi-light): `shadows` = 2 records (`west`, `east`),
  each bit-identical to the single-light document of that light; `constructions` has keys `east`, `west`;
  `umbra = [{receiver: "ground", lights: ["west", "east"], polygons: 3 pieces}]`, the pieces (CCW, canonical start,
  compared index-wise within 1e-6 mm), in this order:
  1. triangle `(0, −19.444444444444443), (25.753937681885635, −14.285714285714285), (−25.753937681885635, −14.285714285714285)`
     (= `(0, −2/3)`, `(±0.5, −0.5)`; `v = −175/9`, `−100/7`), area `132.85761502560047` mm²;
  2. quadrilateral `(−25.753937681885635, −14.285714285714285), (25.753937681885635, −14.285714285714285),
     (22.944417207498113, 12.727272727272727), (−22.944417207498113, 12.727272727272727)` (= `(±0.5, ±0.5)`;
     `v = 140/11` for `y = 0.5`), area `1315.4880281807557` mm²;
  3. triangle `(−22.944417207498113, 12.727272727272727), (22.944417207498113, 12.727272727272727), (0, 16.666666666666664)`
     (= `(±0.5, 0.5)`, `(0, 2/3)`; `v = 50/3`; the apex `u` is `0` within 1e-13), area `90.38709809014404` mm²;
  total image area `1538.7327412965` mm² (1e-6 relative); mapped back by `H⁻¹` the pieces are disjoint, their area sum is
  `7/6` within 1e-9 and every vertex of the ground hexagon is a piece vertex within 1e-9 m. The `west` drawable is
  `(−22.944417207498113, 12.727272727272727), (−25.753937681885635, −14.285714285714285), (54.86708462662592,
  −30.43478260869565), (164.60125387987776, −30.43478260869565), (130.54582204266168, 24.137931034482758),
  (43.51527401422056, 24.137931034482758)`; `warnings == []`; `form_shadow` has two entries (`west`: faces `+x`, `−y`,
  `+y`, base; `east`: `−x`, `−y`, `+y`, base); `form_shadow_core = [{cube: the ±y faces and the base}]`;
  `edges[].silhouette` true for exactly the 4 top edges, the 4 verticals and the two `x = ±0.5` base edges (10 edges);
  `silhouette_lights` = `["west", "east"]` for the two top edges `y = ±0.5` (`v4–v5`, `v6–v7`: top lit, `±y` faces unlit
  under both lights), `["west"]` for the `x = −0.5` base edge, its two verticals **and the top edge `x = +0.5`** (`v5–v6`:
  the `+x` face is unlit by `west` only; the top edge `x = −0.5` is not a `west` silhouette edge because top and `−x` are
  both lit by it), `["east"]` for the mirrored four (`x = +0.5` base edge, its verticals, top edge `x = −0.5` `v4–v7`),
  `[]` for the other two base edges (verified on the v2 library: `west` has exactly six silhouette edges).
- `tests/test_multilight.py` (new): the acceptance case above (document, SVG groups `cast_shadow.east/west/umbra` with
  `fill-opacity="0.15"` on the per-light groups, one umbra `<path>` with 3 `M … Z` subpaths, `construction.west` /
  `.east`, `form_shadow.west` / `.east` with `fill-opacity="0.09"` holding only the `+x` / `−x` face, `form_shadow.core`
  holding the three core faces); `test_per_light_records_bit_identical` on this scene and on the curved two-light scene
  (`ball` sphere, `pillar` cylinder, `wedge` prism; `lamp` point `(−2, −3, 3)`, `sun` directional
  `(0.3, 0.5, 0.812403840463596)`) with the §5.3.2 name map, including `form_shadow[light == k]`; a grammar round-trip of
  every `points` key of that scene (`<obj>.<stem>[.<light>][.shadow.<light> | .foot][.<r>]` parsed from the right against
  the light and receiver ids); `test_umbra_reproducible_from_document` (`umbra_from_document(json.loads(dumps(doc))) ==
  doc["umbra"]` bit for bit, two and three lights); three lights (concave prism of `make_concavity_scene(1)` with two more
  point lights: the union of the pieces equals the raster AND of the three per-light masks, IoU ≥ 0.995 on an 800 × 600
  grid, and permuting the light list permutes `umbra[].lights` but leaves the piece set and the union area unchanged
  within 1e-9); inactive second light (`z < 0`: `LIGHT_BELOW_RECEIVER`, `umbra[0].lights == [first]`, `polygons == []`,
  the single active group at `fill-opacity="0.3"`, empty umbra path); two identical lights (umbra image area = shadow
  image area within 1e-9 relative); light inside a box for one of two lights (empty record for it, other light's shadows
  present, `LIGHT_INSIDE_OBJECT` once, umbra = drawn-region intersection, asserted in words as the chosen convention);
  camera on the ground and below the ground (finite, no exception; below ground: IoU ≥ 0.99 against the ray cast);
  `project_scene(umbra=False)` → `polygons == null`, everything else identical; validation (two lights accepted; duplicate
  id → `lights[1].id`; `umbra` / `core` rejected only when `N ≥ 2` and accepted for `N = 1`; empty list rejected);
  single-light documents carry none of the M6 keys; a two-light scene with a bounded wall (`wall_and_ground` + the mirrored
  lamp): one `umbra[]` entry per receiver, `umbra[1].lights` restricted to the lights with `receivers[1].lit`, pieces mapped
  back by `H_wall⁻¹` lie in the plate.
- `tests/test_umbra.py` (new): `record_pieces` on a square (1 piece, area 1, either orientation), two overlapping unit
  squares offset `(0.5, 0.5)` as one record (3 pieces, area 1.75), a square with a reversed inner square `[0.25, 0.75]²`
  (hole, 4 pieces, area 0.75), the bow-tie `(0,0),(2,2),(2,0),(0,2)` (self-intersecting, nonzero area 2.0), the C-shaped
  sweep loop `(3,3),(0,3),(0,0),(4,0),(7,0),(7,1),(3,1),(1,1),(5,0.96),(5,1.96),(7,1.96),(7,2.96)` (**4** pieces
  `[0,7]×[0,1]`, `[0,5]×[1,1.96]`, `[0,7]×[1.96,2.96]`, and the top trapezoid, area 19.0; raster within 0.5 %); the
  sliver case (quad `(−250,0),(250,1.5·tol_mm),(250,100),(−250,100)`: area within `tol_area` of the true area, every piece
  vertex within `tol_mm` in `v` of the input boundary, no piece wider than the input's `u`-extent) and the merged-vertex
  case (`(−250,0),(0,0),(250,0.7·tol_mm),(250,1.2·tol_mm),(250,100),(−250,100)`: same assertions); the bow-tie guard (edge
  `(0,−10)→(100,10)`, a nearly horizontal edge through `(50 + 2.5·tol_mm, tol_mm/2)` with `du/dv = −1e5`, a vertex at
  `v = 0`: every piece convex and CCW); determinism (two runs, same bytes); the spec §7.1 row 4 equivariance of the
  acceptance pieces (index-wise, 1e-6 mm) and of the three-light pieces (union area / scaled tolerance); `umbra_pieces`
  with two groups on hand polygons (two overlapping squares as two lights → 1 piece of area 0.25; disjoint → `[]`).
- `tests/test_raycast.py`: `random_scenes.make_scene(seed, n_objects, n_lights)` gains `n_lights ∈ {2, 3}` for ≥ 6 seeds;
  the reference mask "occluded from every light" (`raycast.occluded` ANDed over lights) is compared with the union of the
  umbra pieces mapped to the ground by `H⁻¹` (grid samples inside `R` and in front of the near plane), IoU ≥ 0.99; each
  light's own mask is compared with its drawables as in v1.
- `tests/test_invariants.py` row 2 (camera independence): the ground images of the umbra pieces of two cameras that both
  see the whole umbra have equal union area within 1e-9 (relative) and the same vertex set within 1e-9 m.
- `tests/test_degenerate.py`: directional light along the normal (`F` undefined) as the second light
  (`constructions[that].shadow_vp == null`, `rays` without `F`); both lights inactive (`umbra[0].lights == []`).
- Conformance set **v6** = the v5 set + four added cases (`tools/regen_conformance.py --case … --reason "M6: multi-light
  cases"`; no existing expected file changes): `multilight_two_point_symmetric_box` (above),
  `multilight_point_and_directional_curved` (the curved scene above: per-light curved names, terminators per light, umbra of
  sampled polygons, core), `multilight_three_lights_concave_prism` (`N = 3`, self-intersecting and overlapping self-shadow
  loops), `multilight_second_light_inactive` (`LIGHT_BELOW_RECEIVER` on the second light, empty umbra polygons).
  `test_set_covers_the_required_sources` additionally requires a case with `N ≥ 2` and one with `N ≥ 3`. `README.md` of
  the set gains the `constructions` / `umbra` classification rows and the "multi-light documents only" note;
  `is_image_path(("constructions", "east", "segments", 0, "points", 0, 1))` is true (through `rules.json`).
- `tests/test_svg.py`: group ids / order / opacities for `N_act = 2` and `3` (`_f(0.3/3) == "0.1"`, `_f(0.18/3) == "0.06"`);
  the umbra path has one `M … Z` subpath per piece; core faces absent from the per-light groups; for `N = 1` the exact list
  of `<g id>` values equals the single-light list, no `fill-opacity` / `opacity` attribute on any `cast_shadow.*` /
  `form_shadow.*` sub-group, no `umbra` / `core` / `construction.<light>` group, and the SVG of `example_basic` equals the
  golden file `tests/golden/example_basic.svg` generated on the M5-merged base (not a literal in the test).
- `tests/test_bench.py` / `tests/test_cli.py`: `--lights 2|3` runs and reports the umbra share; `castplane info` lists
  both lights; `render` of a two-light scene writes the sub-groups.

#### 5.3.11 Compromises considered
Accepted (exact up to `tol_mm`, deterministic, portable): snapping vertex `v` to merged events and the exact-endpoint rule
(makes coincidences exact instead of ulp-dependent); the per-end clamp (bounded `tol_area/2` lobes); coalescing inside
intervals, bridging zero-width intervals and merging runs by line id (a partition whose size follows the region's runs
per slab, not the slab grid and not the input edge set — the slab events of every input vertex still split it: an
`n × n` grid of unit squares in one record gives `n` pieces); one
intersection scan with a counter per light instead of a fold of pairwise clips (disjoint pieces, light-order independent
set, no pair matrix); reusing the sampled curved drawables; not materialising penumbra polygons (derivable); `[]` for fewer
than two active lights (the picture is the v1 one); projecting the union of unlit faces once; keeping the `construction`
alias; `N_act` as the opacity divisor; core faces drawn once. **Rejected**: an umbra by rasterisation / marching squares
or by SVG blend modes (not exact, not in the document, renderer dependent); ear clipping with "repair" of
self-intersections (fails the nonzero rule); a world-space umbra in stage A (camera-dependent clip rectangle or
oriented-projective booleans for unbounded shadows); the pairwise convex clip fold and the per-light union pass
(measured: 61 226 raw trapezoids per light on the benchmark scene, ≈150 000 pieces and 16 s after a union pass, a 21 GB
pair matrix); the uniform fold emitting one active light's region as pieces (duplicates the only shadow in the document;
the SVG would draw nothing new); reserving `shadow` / `foot` as light ids (v1 allows them; names are parsed from the right
against the known light ids); a group `opacity` on the per-light sub-groups (fades outlines); any polygon-boolean
dependency (shapely, pyclipper); `float32` or GPU paths.

### Implementation notes
- **[decision, implementation] (M6 step 1) The v1 length-1 test.** `tests/test_scene.py::test_lights_exactly_one`
  asserted the v1 rule that §5.3.0 lifts; it is replaced by `test_lights_non_empty_list` (empty / non-list rejected, two
  lights accepted). The multi-light id rules live in `scene.validate_lights_in_scene(lights, objects)` (called from the
  `lights` row of `validate_scene`); the light ids `umbra` / `core` use §5.3.0's message `"reserved id in a multi-light
  scene"`, the object id `core` uses §5.0.1's message `"reserved id"` (one string per row of §5.0.1 / §5.3.0).
- **[decision, implementation] (M6 step 2) Literal readings of §5.3.4 that a port must share.** (1) `tol_area` is
  evaluated as `1e-9 * (D * D)`. (2) "Consecutive edges of the same polygon" (excluded from the crossing pairs) are
  edges whose indices **in the input polygon** differ by 1 modulo `n_i`, decided before the horizontal edges are
  discarded (two edges separated by a discarded horizontal edge are not consecutive). (3) The line ids of
  `record_pieces` and the `base_{k,r}` of `umbra_pieces` count **every** input polygon's `n_i` edges, also of polygons
  with fewer than three vertices (only uniqueness matters for the run merge; the count is fixed so that the line ids are
  reproducible). (4) Step 6 with two raw pieces of one slab carrying the same `(line_left, line_right)` key (not expected:
  a line bounds at most one piece per slab) pairs them in order: the `m`-th of slab `s + 1` extends the merged piece of
  the `m`-th of slab `s`. (5) Crossing-pair enumeration lists every `v`-overlapping pair once from the edge with the
  smaller `(v_min, index)`; the `(i, j)` written into the formula is `(min, max)` of the two table indices; the order in
  which pairs are visited does not affect the result (the events are sorted). (6) `umbra_from_document` always computes
  the polygons, also for an entry written with `umbra=False` (`null`); on a computed document it equals `doc["umbra"]`.
- **[decision, implementation] (M6 step 2) The cost bound of §5.3.4 is not a worst-case bound.** A slab
  decomposition emits one (slab, active edge) entry per active edge per slab, so its cost is `Θ(Σ_slabs active edges)`,
  which is `O((E + X)·E)` in the worst case, not `O((E + X)·log E)`: a 2 000-edge **random** self-intersecting loop
  (4.6·10⁵ merged crossing events) produces 64 221 pieces in ≈ 100 s, while a 2 000-edge simple loop (the M5 mesh case of §5.3.9)
  takes ≈ 0.14 s and the acceptance and benchmark-like inputs are far below that. The kernel is implemented as written
  (vectorised, the slab loop chunked to ≤ 2¹⁸ entries, candidate pairs to ≤ 2¹⁹), and the bound is read as the cost for
  inputs whose slabs hold few active edges (shadow drawables), which is what the benchmark rows measure.
- **[decision, implementation] (M6 step 3) Plates in the core.** `multilight.plate_form_lights`: the per-light flag of a
  plate is the single-light rule of §5.1.8 (both signs strictly beyond their tolerances, so a light parallel to the plate
  gives no per-light entry, exactly the single-light document of that light); the plate is a **core** face iff the camera
  side is decided (`|n·(C − b0)| > tol`) and no light is strictly on the camera's side ("parallel counts as unlit",
  §5.3.1). An object or plate without a record for some light counts as lit by it (no core), as `_project_polyhedra`
  treats a missing record (no unlit face, no silhouette edge). `multilight.multi_light_name` takes an optional
  `object_ids` so that `F.<light>.<r>` is never read as a curved stem whatever the ids are.
- **[decision, implementation] (M6 review fixes) Vectorised piece output, required `n_edges`, USAGE numbering.**
  Step 7 of §5.3.4 (rotation to the canonical start) and the per-piece line ids of `umbra_pieces` are computed on one
  padded `(P, 4)` table per scan (index arithmetic `(rank(start) + j) mod nv`; the record pieces enter the intersection
  scan as one concatenated vertex table), as §5.3.9 asks; the output is bit-identical to the per-piece loop it replaces
  (pieces, sides and `umbra_pieces` JSON compared on random, self-intersecting and benchmark inputs), and
  `tests/test_umbra.py::test_chunk_sizes_are_invisible_in_the_output` pins that `_CHUNK_ENTRIES` / `_CHUNK_PAIRS` never
  change the output. Measured (informational, §5.3.9): the 100-record benchmark drawables against their mirror image
  0.44 s → 0.30 s. `multilight.silhouette_lights(edge_flags, light_ids, n_edges)` takes `n_edges` as a required argument
  (an object without a record for any light still gets one `False` per edge; a flag array of another length raises
  `ValueError`, a caller error, not a scene degeneracy). The USAGE sections of `umbra` / `multilight` are numbered §2.20 /
  §2.21 because M5 owns §2.18 / §2.19.
- **[decision, implementation] (M6 steps 4–5) Where the hooks sit.** `curved.stage_a_object(..., multi)` stores the flag
  as `obj["curved"][<r>][<light>]["multi"]` so that stage B composes the terminator segment names
  (`_terminator_segment_names(oid, t, sil, light_id, multi)`) with the same base names. `_project_polyhedra` also accepts
  a single light id (the v1 call form). The plates' per-light form shadow and core of §5.1.8 / §5.3.3 are computed by
  `pipeline._plate_multi` right after `_plate_record` (whose single-light `form_shadow` is left as it is and not used
  for `N ≥ 2`); the face is projected once. The `rays` `F` entries are taken from the records' `foot_names` (§5.3.2),
  the same strings as before for every single-light record. **One hunk outside the M6 column of the PLAN table**:
  `hidden._curved_pairs` (M4's file) pairs the terminator entries per `(object, light)` when the document is
  multi-light; without it only the first light's entry of a curved object got its `visibility` / `runs` and the
  other lights' entries kept the switch-off values (`tests/test_multilight.py::test_curved_two_lights_with_hidden_lines_bit_identical`
  fails on the M4 code). Single-light documents take the unchanged path.
- **[decision, implementation] (M6 step 6) SVG details §5.3.6 leaves open.** The branch to `svg_multilight` sits in the
  three layer builders **and** in the two hidden-line builders of `form_shadow` / `cast_shadow` (five one-line `if`s,
  all on the `constructions` key). `form_shadow.<light>` and `construction.<light>` are written for every key of
  `constructions` (an empty `<g …/>` when that light has nothing), `cast_shadow.<light>` exactly as in the
  single-light writer (one per light with `shadows[]` records) with the opacity attribute added; `form_shadow.core`
  and `cast_shadow.umbra` are always written in a multi-light SVG (empty when there is nothing). With hidden lines on,
  the `form_shadow.hidden` sub-groups are merged per object (`form_shadow.hidden.<obj>`, first appearance) so that ids
  stay unique when several lights' terminators of one object have hidden runs. A per-light entry whose `polygons` is
  not parallel to its `faces` (a plate whose face is clipped away) is drawn whole unless every face is a core face.
  The `L′` / `F′` marker texts are unchanged for every light (§5.3.6 "unchanged shapes and colours"; the light is told
  by the enclosing `construction.<light>` group).
- **[decision, implementation] (M6 step 8) "As a set the result does not depend on the light order" holds for the
  region, not for the partition.** With coincident edges of different lights (the ground-contact edges every light's
  loop shares, normal in a scene) step 4 orders them by edge index, i.e. by light order, so the edge that closes a run
  (step 5) is the later light's; when the coincident edges part in the next slab, the run merge of step 6 continues or
  restarts depending on which line bounded the run. Measured on the three-light concave case of §5.3.10: 19 pieces in
  scene order, 16 after permuting the lights; the union area agrees within 1e-9 (relative) and the corner vertices of the
  union within 1e-9 mm. The tests therefore read "the piece set" as the region (union area + union corner set); the
  kernel is unchanged (a port reproduces the pieces of the scene order bit for bit, which is what conformance compares).
- **[decision, implementation] (M6 step 8) Row 2 for the umbra: "the same vertex set" is the corner set of the union.**
  The slab decomposition is made in the image, so two cameras give different pieces whose extra vertices lie on the
  union's edges; the test compares the vertices where the union's interior angle is neither `π` nor `2π`. On the
  acceptance scene they agree within 1e-9 m (and the union areas within 1e-9). On the three-light scene the snapping of
  §5.3.4 step 1 (≤ `tol_mm` along the image `v` axis, a camera-dependent direction) moves vertices by ~1e-7 m on the
  ground and kinks very short edges, so its corners are compared at a turning angle > 1e-3 within 1e-6 m (the union
  areas still agree within 1e-9). Spec §7.1 row 2 itself is about the camera-free shadow records, which are untouched.
- **[decision, implementation] (M6 step 8) Test fixtures.** §5.3.10 names the curved two-light scene by its objects and
  lights only; the positions and camera are fixed in `tests/test_multilight.py::curved_scene` (the conformance case
  `multilight_point_and_directional_curved` should reuse them). `tests/golden/example_basic.svg` was generated on the
  M4-merged base of the worktree; its sha256 equals the v2 golden hash of `example_basic`, which the M5 branch keeps, so
  it is the M5-merged base's SVG as well (`.gitignore` gains `!tests/golden/*.svg`). The §5.3.10 `test_umbra.py` rows
  that need the pipeline (equivariance of the acceptance pieces, three-light union area) live in
  `tests/test_multilight.py::test_rigid_equivariance_of_the_umbra`. `castplane info` prints `lights: N` and one line per
  light `<id> (<type>): position|direction (x, y, z); active: <r>=yes|no, …` in place of the v1 `light:` line.
- **[decision, implementation] (M6 review fixes) §5.3.7 build stability and piece-vertex equivariance hold for the
  region, not for the partition, when edges of different lights coincide.** The three-light concave scene of §5.3.10
  (casters standing on the receiver) has cross-light vertex pairs with `0 < |Δ| < 1e-9 mm` (the shadows of the
  ground-contact vertices under different `M_k`) and collinear overlapping ground-contact edges, so the step-4 order
  `(x(y_m), edge index)` and the crossing predicates are within rounding of their thresholds although snapping is
  applied; `u` is never snapped (snapping it within `tol_mm` does not help: measured 21 → 15 / 21 / 23 / 19). Under the
  rigid motions (37°, (2.5, −1.25)), (−120°, (−4, 3)), (180°, 0), (90°, (1, 1)) the per-light drawables move by
  ≤ 1.8e-13 mm but the piece count goes 19 → 16 / 20 / 24 / 20, while the union area agrees within 1e-15 (relative)
  and the corner set of the union (18 corners) within 9e-14 mm. The tests therefore check the three-light rigid row as
  union area + union corner set at the §4 (i) scaled tolerance (`test_rigid_equivariance_of_the_umbra`); the
  acceptance scene keeps the index-wise piece comparison at 1e-6 mm. The kernel is unchanged. Consequence for the
  conformance case `multilight_three_lights_concave_prism` (M6 part 3): an index-wise comparison of its
  `umbra[].polygons` at 1e-6 mm is fragile across libm / BLAS builds and in the TS runner, so either its `umbra`
  polygons are compared as a region (a `case_overrides` entry) or the case uses casters that do not stand on the
  receiver.
- **[decision, implementation] (M6 part 3, step 9) The v6 cases.** (1) The worktree reached v5 by **merging** the M4 + M5
  branch into `wt/m6` (PLAN says "rebase"; the history of parts 1–2 is kept, the conflicts were adjacent append-only
  hunks resolved with the M5 hunk first). (2) `multilight_three_lights_concave_prism` is the U-prism and box of
  `make_concavity_scene(1)` with the two extra point lights of `tests/test_multilight.py::three_light_scene`, **both
  casters lifted 0.2 m** (`transform.position[2] = 0.2`): standing on the ground the case has cross-light vertex pairs
  within rounding and collinear ground-contact edges (the notes above), so its piece partition is build dependent and an
  index-wise comparison at 1e-6 mm would be fragile in another build or the TS runner; lifted, `light_b`'s and
  `light_c`'s loops are still self-intersecting, the three regions overlap (18 pieces), and four rigid motions of the
  whole scene reproduce the pieces index-wise within 2e-13 mm (`tests/test_conformance.py::test_three_light_case_pieces_are_stable_under_rigid_motions`).
  No `case_overrides` entry was needed (the comparator has no region rule, and adding one would be a comparator
  amendment that the TS runner must port). The test-suite scene `three_light_scene()` keeps the casters on the ground
  (its tests compare regions). (3) `multilight_second_light_inactive` puts `under` at `(0.8, −1.3, −1.5)`: the position
  `(1, 0.5, −2)` of `test_inactive_second_light` lies in the plane of the cube's `+y` face and adds
  `FACE_PARALLEL_TO_LIGHT`, which the case should not be about. (4) The curved case reuses `curved_scene()` verbatim;
  its 131 umbra pieces are stable under the same rigid motions (≤ 5e-13 mm). (5) The two worktree-local CHANGELOG
  entries (`--rules-only` for the two `constructions` paths, then `--case` for the four cases) are numbered v6 / v7 in
  the worktree and collapse into the one v6 milestone entry at the M6 merge (§5.0.8 rule 1). The Python runner's
  `_MM_KEY_PATHS` literal gains the same two paths, so the `rules.json` equality test keeps cross-checking it.
- **[decision, implementation] (final review, m6-umbra#0) Zero-width bridging in step 5 of §5.3.4.** Two loops of one
  record that share an edge traverse it in opposite directions; ordered by `(x(y_m), edge index)` the winding passes
  through 0 on the zero-width interval between the two coincident edges whenever the `−1` edge comes first, which ended
  the run, and the run merge of step 6 (keyed on line ids) cannot rejoin the pieces. The partition then had the
  complexity of the input edge set: an `n × n` grid of unit squares gave `n²` pieces, and an M5 per-face fallback mesh
  (`MESH_NON_MANIFOLD`, all face loops in one record) under two lights gave 5 584 umbra pieces for 672 faces (one region
  with 29 boundary vertices; 47 697 pieces and +36 MB of JSON at 2 752 faces). Step 5 now bridges such intervals (a valid
  interval with `x_{k+1}(y_m) − x_k(y_m) ≤ tol_mm` belongs to a run when the run holds an inside interval; the run is
  trimmed to its first and last inside interval). Measured: grid → `n` pieces (one per row), 672 faces → 27 umbra
  pieces, 2 752 faces → 55. The filled set grows only by the bridged gaps: two non-crossing edges `≤ tol_mm` apart at
  `y_m` are `≤ 2·tol_mm` apart on the whole slab, so each bridged sliver has area `≤ 2·tol_mm·D = 2·tol_area` (zero for
  genuinely shared edges) — the same order as the step-5 clamp lobes. The four v6 conformance cases' `umbra[].polygons`
  and the benchmark piece counts (3 637 / 3 652 record pieces, 3 514 umbra pieces with `--lights 2`) are bit-identical,
  so no expected file changes. The TypeScript port of the kernel (M7 phase 2) must mirror the rule; it agrees with the
  Python kernel on every conformance case either way. Tests: `tests/test_umbra.py::test_shared_edges_do_not_split_the_partition`,
  `test_triangle_soup_square_is_one_piece`, `test_separate_regions_are_not_bridged`.
- **[decision, implementation] (final review, m6-umbra#1) Labels of a light called `shadow` / `foot`.** The labels layer
  applied the §5.0.4 part test to the whole name ("any part after the first equals `shadow` / `foot`"), so a light id
  `shadow` or `foot` — valid by §5.0.1 / §5.3.11 — silently lost its `L.<light>`, `F.<light>[.<r>]` and
  `<obj>.sil.<k>.<light>` labels. `svg._is_shadow_or_foot_name(name, lights, receivers, multi)` now parses the name from
  the right against the document's light ids (keys of `constructions`, `shadows[].light`, `receivers[].lit`, the
  `L.` / `F.` names) and receiver ids: after an optional trailing receiver id the name ends in `.foot` or in
  `.shadow.<light>`; `L.<light>`, `F.<light>[.<r>]` and, in a multi-light document, the stems `<obj>.sil.<k>.<light>` /
  `<obj>.g<k>.base|top.<light>` are never shadow / foot names. For every document whose light ids are not `shadow` /
  `foot` the decision equals the old part test (checked on all 50 conformance cases and the examples, hidden lines on
  and off: 8 312 names, 0 differences), so no golden or expected file changes. The §5.0.4 label sentence is amended
  accordingly; the TS writer (§5.4.6) must use the same parse. Test:
  `tests/test_multilight.py::test_light_ids_shadow_and_foot_keep_their_labels`.
- **[decision, implementation] (final review, determinism-perf#2 / m4-hidden#1) Benchmark rows without a target.**
  `benchmarks/bench.py` printed the single-light spec §8 verdicts (`target < 1000 ms FAIL`, `< 100 ms FAIL`, `soft target
  < 5000 ms miss`) on the `--lights 2|3` and `--scene mesh10k` rows, to which §5.0.9 / §5.3.9 / §5.2.7 attach no target.
  Those rows now print `no target (spec §8: the benchmark scene, one light)`; the `--json` output and the exit status
  (`--gate`) are unchanged. The mesh10k hidden-lines row (≈ 5.8 s on the container, brute-force Möller–Trumbore in
  `hidden._first_mesh`, which §5.1.6.2 permits) is recorded in `benchmarks/README.md` as informational; no BVH is added.
  Tests: `tests/test_bench.py::test_bench_target_free_variants_print_no_target`,
  `test_bench_readme_records_the_mesh10k_hidden_lines_row`.

### 5.4 M7 — TypeScript port of the core and the three.js web UI (spec §9 row "TypeScript 移植", spec §10 M7)

Everything in §1–§4 (and §5.0–§5.3, §5.5 where they describe geometry) stays normative for the Python reference
implementation and, where it describes geometry, for the port. This section adds the rules of the second implementation.
Python remains the **reference implementation** (spec §9, `tests/conformance/README.md` rule 3); the port has no authority
over the conformance set.

#### 5.4.0 Scope, non-goals, hard rules and merge sequencing
- Ported: scene validation (§2.0, §5.0.1), transforms (§2.1), camera (§2.2), light / plane projection / feet (§2.3,
  §5.1.2), meshes and primitives (§2.4), polyhedral shadows (§2.5, §5.1.3), curved primitives (§2.6, §5.1.4),
  construction (§2.7, §5.1.5), numerics (§2.8), warnings (§2.9, §5.0.5), the spec §6.1 SVG writer (§2.10, §5.0.6), the
  three-stage pipeline and public API (§3, §5.0.7), the spec §6.2 document and its deterministic serialisation (§3.1,
  §5.0.3), plus the conformance runner (spec §7.5) and the spec §8 benchmark on the TS side; in phase 2 also the M4–M6
  core geometry (§5.4.14).
- **Not ported [decision]**: spec §6.3 PNG (`output/png.py`), the CLI (`cli.py`, incl. `stages` and `import`),
  `tools/regen_conformance.py`, the ray-cast reference, the z-buffer reference and the hypothesis property tests
  (Python-only verification layers), and every file loader (`castplane/io/*`: by §5.0.2 the port consumes expanded scenes;
  the conformance set contains no file references). The web UI reads scene JSON only; the PNG of a web session is the
  browser's own export of the SVG, not a deliverable.
- Hard rules carried over: the TS core has **zero runtime dependencies**; every exported function is a pure function on
  JSON-serialisable data (plain objects / arrays of `number`); stage A never reads `scene.camera`; determinism is
  bit-identical per build (same JSON and SVG strings for the same input in the same process and across processes of the
  same node build); degenerate situations warn with the **unchanged closed code list of §5.0.5** (M7 adds no code; a camera
  inside an object is not a code, exactly as in `curved.camera_outline`) and never throw; input errors throw `SceneError`
  with the same JSON field path strings as Python; the §2.2 drawing pipeline applies to every drawable.
- Shadows in the web UI come **only** from the ported core (`renderer.shadowMap.enabled = false` is normative; no three.js
  light casts or receives shadows; no three.js geometry is used for any geometric output).
- **Merge sequencing with the parallel M4–M6 worktrees [decision]** (spec §10 line "M3 閘門後擴充與移植並行"). M7 is
  delivered in two phases, each with its own acceptance:
  - *Phase 1 (branch `claude/m7-ts-port`)*: the port is accepted against the conformance set as it stands on the M7
    branch base (**v3** after the §5.4.8 comparator amendment, which M7 step 1 merges to `main` first; 34 cases, 13
    warning codes, the v1 §3.1 document), by the tests of §5.4.13 and the benchmark of §5.4.9.
  - *Phase 2 (the merge into `main`, owned by M7, implementation step 11)*: (i) `tests/conformance/rules.json`,
    `INT_KEYS` (§5.4.5) and `WARNING_CODES` (§5.4.2) are updated from the merged Python files; (ii) the M4–M6 geometry
    named by the merged §5.0.3 (visibility runs, bounded receivers / folds, umbra entries, multi-light `constructions`,
    the mesh kind) is ported through the extension points of §5.4.14; (iii) both runners are green on the merged
    conformance set at its then-current version (v6, §5.0.8). Acceptance of phase 2: "both runners green on `main` at set
    v6" recorded in `tests/conformance/CHANGELOG.md`'s v6 entry. Until phase 2 lands, `ts/test/conformance.test.ts` runs
    on the M7 branch only.
  - *Files M7 shares with M4–M6* (every other M7 file is new): `tests/test_conformance.py` (M7: `rules.json` assertion +
    `case_overrides`; M4: the `runs` rule; M6: `mm_key_paths`), `tests/test_bench.py` (M7: one lock test),
    `benchmarks/bench.py` (M7: load the committed scene file), `castplane/output/geometry_json.py` (M7: `allow_nan=False`),
    `tests/test_curved.py` (M7: one precondition test), `.github/workflows/ci.yml` (M7: jobs `ts`, `web`; the Python job
    gains `tests/test_ts_port.py`), `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/USAGE.md`, `README.md`,
    `benchmarks/README.md`, `tests/conformance/README.md`, `tests/conformance/CHANGELOG.md`. New files: `ts/`, `web/`, root
    `package.json` / `package-lock.json`, `tests/conformance/rules.json`, `benchmarks/export_scene.py`, `benchmarks/scenes/`,
    `tests/test_ts_port.py`, `tools/compare_svg.py`, `tools/regen_conformance.py --rules-only` (mode added to the existing
    tool).

#### 5.4.1 Repository layout (normative)
```
package.json                root npm workspace: {"private": true, "workspaces": ["ts", "web"],
                            "engines": {"node": "^20.19.0 || >=22.12.0"}}; scripts build / test / bench delegate to the workspaces
package-lock.json           committed; CI installs with `npm ci`
.gitignore                  + node_modules/, ts/build/, web/dist/, web/build/
ts/                         the core package
  package.json              {"name": "castplane", "version": "0.1.0" (== castplane.__version__), "private": true (M7 does not publish),
                             "type": "module", "exports": {".": {"types": "./build/src/index.d.ts", "default": "./build/src/index.js"}},
                             "engines": {"node": ">=20.19.0"}, "dependencies": {} (none, ever),
                             "devDependencies": {"typescript": "6.0.2", "@types/node": "<exact 22.x pin, no ^>"}, scripts below}
  tsconfig.json             the CORE config — {"compilerOptions": {"strict": true, "target": "ES2022", "lib": ["ES2022"], "module": "NodeNext",
                             "moduleResolution": "NodeNext", "declaration": true, "sourceMap": true, "rootDir": ".", "outDir": "build",
                             "isolatedModules": true, "verbatimModuleSyntax": true, "noImplicitOverride": true,
                             "noFallthroughCasesInSwitch": true, "types": []}, "include": ["src"]}
                            `types: []` + `lib: ["ES2022"]` is what PROVES src/ is browser- and node-neutral: a `node:` import,
                            `process`, `Buffer` or `performance` under src/ fails to compile (verified with tsc 6.0.2: TS2591 / TS2304)
  tsconfig.test.json        {"extends": "./tsconfig.json", "compilerOptions": {"types": ["node"]}, "include": ["src", "test", "bench"]}
                            (same rootDir / outDir, so build/src is emitted once more, identically; test and bench may use node:fs,
                            node:path, node:test, process.argv, performance.now, import.meta.url)
  src/                      §5.4.2 modules (no fs / path / Buffer / process / performance / import.meta anywhere under src/)
  test/*.test.ts            node:test suites (§5.4.8, §5.4.13); run as `node --test build/test/`
  test/helpers.ts           node-only helpers: repo_root() from import.meta.url, read_json(path), write_geometry_json(doc, path)
                            (= dumps(doc) + "\n"), camera_override(base, position, target, roll_deg) (§5.4.7)
  bench/camera_only.ts      the spec §8 benchmark on the TS side (§5.4.9)
  scripts/render.mjs        dev helper: `node ts/scripts/render.mjs scene.json outdir` writes <name>.svg / .json (not a product surface)
  README.md                 build / test / API summary (points to docs/USAGE.md §4)
web/                        the vite + three.js UI, imports the core as the workspace package "castplane"
  package.json              {"name": "castplane-web", "private": true, "type": "module",
                             "dependencies": {"three": "0.186.1", "castplane": "0.1.0"},
                             "devDependencies": {"vite": "8.3.3", "typescript": "6.0.2", "@types/three": "0.186.0", "@types/node": "<same exact pin>"}}
  vite.config.ts            {base: './', build: {target: 'es2022', sourcemap: true}} — static output, no server
  tsconfig.json             strict, "module": "ESNext", "moduleResolution": "bundler", "lib": ["ES2022", "DOM"], "noEmit": true
  tsconfig.test.json        compiles src/orbit.ts + src/download.ts + test/ to build/ with module NodeNext, types ["node"], for `node --test`
  index.html, src/*.ts      §5.4.10
  test/orbit.test.ts        §5.4.13
benchmarks/scenes/benchmark_100.json        the spec §8 benchmark scene exported as a spec §4 scene file (§5.4.9)
benchmarks/scenes/benchmark_100.build.json  {"python": "...", "numpy": "..."} — the build that wrote it (§5.4.9 lock rule)
benchmarks/export_scene.py                  writes both (`python3 benchmarks/export_scene.py`)
tests/conformance/rules.json                the comparator constants shared by both runners (§5.4.8, final content in §5.0.8)
tests/test_ts_port.py                       Python-side checks of the shared files (§5.4.13)
tools/compare_svg.py                        dev tool (§5.4.6)
.github/workflows/ci.yml                    + jobs `ts` and `web` (§5.4.12)
docs/USAGE.md §4 "TypeScript API and web UI" (new section AFTER the existing §3 警告代碼), README.md "Web UI / TypeScript" paragraph, ts/README.md, web/README.md
```
Scripts (exact): `ts`: `"build": "tsc -p tsconfig.json && tsc -p tsconfig.test.json"`, `"test": "npm run build && node --test build/test/"`,
`"bench": "npm run build && node build/bench/camera_only.js --gate both"`; `web`: `"dev": "vite"`, `"build": "tsc -p tsconfig.json && vite build"`,
`"preview": "vite preview"`, `"test": "tsc -p tsconfig.test.json && node --test build/test/"`. Root: `"build"`, `"test"`, `"bench"` run
the workspace scripts in the order ts → web. `ts/package.json` must carry `"type": "module"` (without it NodeNext emits CommonJS
and `import.meta` fails with TS1470).

**[decision] Pins and tool choices.** Versions are exact pins (no `^` anywhere, `@types/node` included): `typescript 6.0.2`
(the last TypeScript release on the JavaScript compiler; it is the toolchain preinstalled in the CI container; TypeScript 7.x,
the Go-based compiler released 2026-07, drops several compiler options and is not yet exercised by this repository —
upgrading is a one-line change once CI runs on it), `vite 8.3.3`, `three 0.186.1`, `@types/three 0.186.0`. Node ≥ 20.19
(vite 8's floor; `node --test` with directory arguments exists since 20). **Test runner = `node:test`**, not vitest: the core
has no dependencies, `node --test` runs the exact `tsc` output that ships (no esbuild transform between the tested code and
the built package, so a transform cannot change float semantics or module order), it needs no configuration, supports
`--test-name-pattern`, `--test-reporter` and timing, and keeps the dev-dependency set at `typescript` + `@types/node`. Vitest
would add ≈100 packages and a second compiler for no capability the suite needs (no DOM tests: the web tests cover pure
modules only). **Build = `tsc`** (declarations + source maps, ESM with `.js` import specifiers so that the same output runs
under node and under vite without a bundling step for the core).

#### 5.4.2 Module mapping (same names, same record shapes)
**[decision] Names.** Exported TS function names are the **Python names, snake_case, unchanged** wherever a Python function
of that name exists (`shadow_matrix`, `light_vector`, `lit`, `foot`, `project`, `silhouette_edges`, `shadow_geometry`,
`project_scene`, `compose`, `render`, `load_scene`, `write_svg`, `dumps`, `row_max_abs`, `shadow_w`, …): spec §8 ties the
names to the spec §5 symbols, and identical names make the two implementations greppable side by side. Python functions
that exist only in a batched (plural) form are ported **under the same plural name with list-in / list-out semantics**
(`covering_segments(A: Vec2[], B: Vec2[], C: Vec2[]): [Vec2, Vec2][]`, `extended_segments`, `clip_segments_uv`,
`clip_segments_rect_h`, `clip_segments_near`), computed row by row. Names that exist only in the port are listed in the
"port-only" column so that grep parity is explicit. Types are PascalCase (`Scene`, `Mesh`, `ObjectRecord`, `StageA`,
`StageB`, `GeometryDocument`, `Warning`). Module-private helpers keep the Python name without the leading underscore.

| Python | TS | exported names (identical to Python) | port-only names | notes |
| --- | --- | --- | --- | --- |
| `errors.py` | `src/errors.ts` | `SceneError`, `WARNING_CODES`, `make_warning`, `merge_warnings`, `warning_codes` | — | `SceneError extends Error`: `field` (JSON path), `detail` (bare message), `message` = `"<field>: <detail>"` (= Python `str(e)`). 13 codes in phase 1, 18 after phase 2 (§5.0.5) |
| `homogeneous.py` | `src/homogeneous.ts` | `TOL_DIR`, `ZERO_REL`, `row_max_abs` (of one vector), `normalize_max`, `cross3`, `join`, `meet`, `to_homogeneous`, `scene_scale`, `tolerance`, `clip_segment_halfspace`, `clip_polygon_halfspace` | — | scalar forms only (§5.4.4 (6)); the batched `clip_segments_halfspace` / `clip_polygons_halfspace` are not ported |
| `scene.py` | `src/scene.ts` | `OBJECT_TYPES`, `LIGHT_TYPES`, `LAYER_IDS`, `polygon_signed_area`, `polygon_is_simple`, `validate_transform`, `validate_object`, `validate_light`, `validate_receiver`, `validate_camera`, `validate_output`, `validate_scene`, `load_scene`, `load_camera` (+ phase 2: `validate_bounds`, `validate_hidden_output`, `validate_mesh_data`, `LOADER_TYPES`) | `load_scene_text` | `load_scene(data: unknown)` takes parsed JSON (no paths: no fs in the core); `load_scene_text(text)` (core, browser-safe) wraps `JSON.parse` and throws `SceneError("", "invalid JSON: <message>")` like Python's file path form |
| `transform.py` | `src/transform.ts` | `rotation_x/y/z`, `euler_zyx_matrix`, `transform_frame`, `apply_transform`, `apply_rotation` | — | |
| `mesh.py` | `src/mesh.ts` | `CURVED_SEGMENTS`, `SPHERE_RINGS`, `face_normals_newell`, `mesh_from_faces`, `box_mesh`, `prism_mesh`, `cylinder_mesh`, `cone_mesh`, `sphere_mesh`, `transform_mesh`, `mesh_bbox`, `euler_characteristic` (+ phase 2: `triangulate_faces`) | — | `Mesh` = §2.4 dict with `edge_flipped` always present (+ `edge_smooth` after phase 2) |
| `primitives.py` | `src/primitives.ts` | `CURVED_TYPES`, `local_mesh`, `analytic_record`, `face_tables`, `build_object`, `point_inside_solid` | — | **[decision]** the padded tables `faces_padded` / `face_lens` are a numpy batching device and are **not** ported; `face_tables` returns `{face_first, face_point_names}`; `edge_templates` and `world_lists` are ported (shared by reference with every document, §3) |
| `light.py` | `src/light.ts` | `light_vector`, `lit`, `is_parallel`, `lit_state`, `face_lit_flags`, `silhouette_edges`, `silhouette_loops` | — | `face_lit_flags` returns `{lit: boolean[], parallel: boolean[]}` |
| `shadow.py` | `src/shadow.ts` | `ARC_STEP_DEG`, `shadow_matrix`, `foot`, `shadow_w` (one point → `number`), `clip_loop_to_plane`, `clip_mesh_to_plane`, `shadow_loop` (+ phase 2: `receiver_frame`, `bounds_functionals`, `clip_polygon_bounds`, `plate_loop`) | — | `sources` entries are tagged objects `{kind: "vertex", index}` / `{kind: "ground", i, j}` / `{kind: "dir", i, j}` / `{kind: "arc", k}` / `{kind: "bounds", k, a, b}` / `{kind: "bounds", k, anchor: true}` (TS has no tuples-as-tags) |
| `conics.py` | `src/conics.ts` | every name of `conics.__all__` | `jacobi_eigenvalues_3` | condition number via `jacobi_eigenvalues_3` (§5.4.4 (5)); `cond` is still dropped from the document |
| `curved.py` | `src/curved.ts` | every name of `curved.__all__` | — | `stage_b_objects(objs, recs, cam, tol, warnings)` loops `stage_b_object`; the equality of the Python batch with that loop is a **tested precondition** of M7 (§5.4.4 (6), `tests/test_curved.py::test_stage_b_objects_equals_per_object_loop`), not a docstring claim |
| `camera.py` | `src/camera.ts` | `UP_WORLD`, `FALLBACK_UP`, `RECT_GROW`, `camera_forward`, `camera_matrix`, `project`, `divide`, `nu`, `depth`, `clip_segment_near`, `clip_segments_near`, `clip_polygon_near`, `rect_functionals`, `clip_polygon_rect_h`, `clip_segments_rect_h`, `clip_line_rect`, `vanishing_point`, `horizon` | — | `project_polygons` (batched) not ported |
| `construction.py` | `src/construction.ts` | `RAY_EXTENSION`, `LINE_ZERO_REL`, `LINE_PARALLEL_REL`, `special_point_image`, `covering_segments`, `extended_segments`, `clip_segments_uv`, `coincidence_check`, `self_check` | — | list-in / list-out, row by row |
| `pipeline.py` | `src/pipeline.ts` | `shadow_geometry`, `project_scene`, `compose`, `render` | `construction_block` (§5.4.14 (c)) | §5.4.7 |
| `hidden.py`, `meshprep.py`, `umbra.py`, `multilight.py` | `src/hidden.ts`, `src/meshprep.ts`, `src/umbra.ts`, `src/multilight.ts` | every public name of §5.1.6, §5.2.3, §5.3.4, §5.3.9 | — | phase 2 (§5.4.14) |
| `output/geometry_json.py` | `src/output/geometry_json.ts` | `canonical`, `dumps` | `py_repr`, `INT_KEYS`, `cmp_code_points` | §5.4.5; `write_geometry_json` lives in `ts/test/helpers.ts` (node-only; nothing under src/ touches fs) |
| `output/svg.py` (+ `svg_multilight.py`) | `src/output/svg.ts` | `LAYER_ORDER`, `STYLE`, `write_svg` | `fmt` (= Python `_f`) | §5.4.6 |
| `output/png.py`, `cli.py`, `io/*` | — | — | — | not ported |
| `__init__.py` | `src/index.ts` | re-exports of §3 / §5.0.7 + `__version__ = "0.1.0"` | — | |
| — | `src/types.ts` | — | `Vec2`, `Vec3`, `Vec4`, `Mat3`, `Mat34`, `Mat4`, `Mat43` | |
| — | `src/document.ts` | — | `GeometryDocument` and the entry types of §3.1 | phase 1: the v1 shape; phase 2: the final §5.0.3 shape (§5.4.14) |
| — | `src/pyfloat.ts` | — | `pymod`, `pyimod`, `py_round`, `cmp_code_points` | §5.4.4 (4) |

**Array conventions [decision].** Vectors are tuples: `Vec3 = [number, number, number]`, `Vec4`, `Vec2`. Matrices are
row-major nested tuples/arrays identical to their document encoding: `Mat3 = [Vec3, Vec3, Vec3]`, `Mat34 = [Vec4, Vec4, Vec4]`
(`P`), `Mat4` (`M`), `Mat43 = [Vec3, Vec3, Vec3, Vec3]` (`E`). Point lists are `Vec3[]` / `Vec4[]`; mesh tables are
`vertices: Vec3[]`, `edges: [number, number][]`, `faces: number[][]`, `face_normals: Vec3[]`, `edge_faces: [number, number][]`,
`edge_flipped: [boolean, boolean][]`, `vertex_names: string[]`. **`Float64Array` is permitted in exactly one place**:
private scratch buffers of stage B in `pipeline.ts` for the per-scene vertex projection (`image_h`, `nu`), and only if
`bench/camera_only.ts` shows a ≥ 10 % gain on the camera-only path (recorded in `benchmarks/README.md`); such a buffer never
reaches stage A, stage C or the document. No `Float32Array`, no `Math.fround`, no WebGL compute anywhere in `ts/src`. Every
table keyed by an object / light / receiver / point id is a `Map<string, …>` (never a plain object: JS reorders
integer-like keys such as `"1"` and would break insertion order); the document's `points` block is a plain object because
the writer sorts its keys anyway and point names always contain a `.`.

#### 5.4.3 Validation (§2.0 / §5.0.1) in the port
No new rows. `load_scene` reproduces every row of the §2.0 table (and, in phase 2, of §5.0.1) with the **same field path
strings** (`objects[1].size`, `camera.frame_mm`, `output.layers[2]`, …); messages are informative only. Predicates: a JSON
number is `typeof x === "number" && Number.isFinite(x)` (booleans are not numbers, exactly like Python's `_is_number`);
lists are `Array.isArray`; objects are non-null non-array objects. Unknown keys are ignored. `load_scene` returns a **new**
object with every default filled. `validate_camera` rejects a block carrying both `target` and `yaw_deg` / `pitch_deg`
with `SceneError("camera", "give either target or yaw_deg + pitch_deg, not both")`, exactly as `castplane/scene.py` does —
which is why every camera block the port or the UI *constructs* (§5.4.7, §5.4.10) is built from the lens fields explicitly,
never by spreading a scene camera. Additional rows that exist only in the port:
| field | rule |
| --- | --- |
| `""` (whole input) | `load_scene_text`: text that is not valid JSON → `SceneError("", "invalid JSON: <JSON.parse message>")`; a non-object root → `SceneError("scene", "must be an object")` (Python `_dict(scene, "scene")`) |
| `camera` (override) | `project_scene(scene, A, camera)`: `validate_camera(camera, "camera")` then the aspect rule → `SceneError("camera.frame_mm", …)` as in `pipeline._resolve_camera` |
| `objects[i].path` / `type: step` | the "must be expanded first" errors of §5.0.1 (the port has no expander) |

#### 5.4.4 Numerics of the port (§2.8 applied to JavaScript)
1. **binary64 everywhere.** JS `number` is IEEE-754 double; V8 performs no FMA contraction (the language forbids it).
   numpy / BLAS may use FMA or a different summation order, so the two implementations differ by ulps, never by more;
   the conformance tolerances (1e-6 mm absolute on image values, 1e-9 relative elsewhere) absorb this **except where the
   geometry itself amplifies an ulp**, which the probe below locates. **Evidence (recorded, M7 design, replaces the earlier
   result-scaling probe, which was projectively trivial):** every kernel *input* was perturbed entry-wise with a
   sign-alternating `1 ± 2^-52` (so that no homogeneous scale cancels) and all 34 v2 cases were run through
   `tests/test_conformance.py::compare_documents`: perturbing `P` (3×4), the world vertices and the clip helpers' outputs
   passes **34/34**; perturbing the entries of `M = shadow_matrix(π, L)` or of `L = light_vector(light)` passes **33/34**
   and fails exactly **one case on exactly four leaves**: `degenerate_cylinder_cap_at_light_height`,
   `shadows[0].loops[0][30].direction[1]`, `[31].direction[1]` and the same two entries of `shadows[0].outline` (expected
   `0.5052007436053615`, got `0.5052007451335294`: 3.0e-9 relative, 1.5e-9 absolute). The amplifier is
   `curved._zero_shift` (`acos(c0) − acos(c1)` with `|c| → 1`): the top rim of that cylinder is tangent to the light
   height, so the `w_S = 0` crossing of `A cos θ + B sin θ + C` is a double root and its parameter moves like
   √(input perturbation) (1e-16 → 1e-8). This is the geometry of the case, not a bug, and the case exists precisely to sit
   on that boundary (`FACE_PARALLEL_TO_LIGHT` needs `|n·(l − p)| ≤ tol`), so rule 7 below (move the case) does not apply;
   the **comparator** is amended for exactly those leaves instead (§5.4.8 `case_overrides`, conformance set v3, recorded
   now rather than after a failure). Every other leaf of every case has ≥ 3× margin against a one-ulp input change in this
   probe. The M4–M6 implementers re-run the probe on their new cases before freezing them (§5.4.14 (f)).
2. **Fixed-order expressions.** Every dot product / matrix product is written out as a left-to-right sum in index order,
   mirroring the Python scalar code: `project`: `x̃_i = P[i][0]·x + P[i][1]·y + P[i][2]·z + P[i][3]·w`;
   `nu(X) = (X0·f0 + X1·f1 + X2·f2) − offset·X3` with `offset = (f0·C0 + f1·C1 + f2·C2) + near` (as `camera.nu`); `lit`:
   `n0·(l0 − w·p0) + n1·(l1 − w·p1) + n2·(l2 − w·p2)` (as `light._lit_value`); `shadow_w = piL·w_P − w_L·(π·P)`; `foot` as
   written in §2.3; `shadow_matrix` entries `piL·δ_ij − L_i·π_j`; `K·[R|t]` with the 3-term sum in `k` order; `cross3` as
   `(a1·b2 − a2·b1, a2·b0 − a0·b2, a0·b1 − a1·b0)` (numpy's own formula); `|v|` = `Math.sqrt(x·x + y·y + z·z)`;
   `math.hypot` → `Math.hypot`; `math.radians(d)` → `d * (Math.PI / 180)`, `math.degrees(r)` → `r * (180 / Math.PI)` (the
   same constant doubles CPython uses); `atan2`, `acos`, `cos`, `sin` → `Math.*` (fdlibm-derived in V8, glibc in CPython:
   ≤ 1 ulp apart, covered by rule 1). The §2.2 near / rectangle clips use the Python interpolation formula verbatim:
   `X = (fa·B − fb·A) / (fa − fb)` (never `A + t·(B − A)`).
3. **Variable-length reductions and sorts** (the only places where Python sums or orders over an axis of variable length)
   and their port: Newell normals (`mesh._face_normals_grouped`: `einsum("klj,klm->kjm")`, sequential over the face's
   vertices) → accumulate `n[j][m] += p[l][j]·q[l][m]` for `l = 0..L−1` in cycle order, then
   `cross = (n12 − n21, n20 − n02, n01 − n10)`, normalised; `scene.polygon_signed_area` → the same sequential loop;
   `shadow._signed_area` (`np.sum`, pairwise) → sequential sum in vertex order (a sign test only);
   `curved._ground_section` centre (`mean(axis=0)`) → sequential sum divided by `n` (an ordering aid only); maxima /
   minima (`row_max_abs`, bbox, `scene_scale`) are order-free; `np.unique` / `lexsort` / `argsort(kind="stable")` on
   **integer** keys → numeric sorts on those keys with the index as tie-break. **Float sort keys exist in two places**
   (`curved._ground_section`: `keys = pymod(atan2(rel_y, rel_x) − phi_e, 2π)`; `curved._ground_ring`:
   `atan2(rel_y, rel_x)`), both `argsort(kind="stable")` on libm-dependent angles: ported as
   `indices.sort((a, b) => keys[a] − keys[b] || a − b)` with the key computed by the same expression; two cross-section
   samples within rounding of the same angle could be ordered differently by the two libms and fall under rule 7 (a case,
   not the predicate, is moved). Phase 2 adds the order-defined reductions of §5.1.10, §5.2.3 (sequential signed volume
   and winding sums) and §5.3.7 (prefix sums, `(value, index)` sorts), all ported as written there.
4. **Python semantics that JS lacks** (`src/pyfloat.ts`): (a) `pymod(a, m)` reproduces CPython `float_rem` exactly
   (`r = a % m` — JS `%` is C `fmod` — `if (r !== 0 && (r < 0) !== (m < 0)) r += m; else if (r === 0) r = m < 0 ? -0 : 0`);
   it replaces every **float** `%` of the Python code, which are exactly (phase 1): `conics.py` `ellipse_params` (`% π`,
   line 330) and `arc_svg_flags` (`% 2π`, 461–462), `curved.py` 687 (`_theta_lit`), 845 and 853 (`_ground_section`, scalar
   and per-sample), 1067 (`shadow_polygon_h`), `shadow.py` 415 (`shadow_loop`); every float `%` that M4–M6 add is listed
   in the same comment block at phase 2. (b) `pyimod(a, n) = ((a % n) + n) % n` reproduces Python's non-negative
   **integer** modulo and is mandatory for every integer `%` whose left operand may be negative: `curved.py` 1256
   `pieces[(i − 1) % n]` (`i = 0` → Python `pieces[-1]`, JS `undefined`) and 1264 `_SIL_INDEX[qi % 4]` (`qi < 0` for
   negative `θ`); the `(i + 1) % n`, `(start + k) % n`, `k % n` forms with non-negative left operands stay as `%`.
   Enforcement: `ts/test/numerics.test.ts` greps `ts/src` and fails on any `%` outside `pyfloat.ts` whose left operand is
   not of the form `(<ident> + <non-negative literal>)`, `<ident>` known non-negative by name (`k`, `s`, `idx`, `start + k`)
   or a bare index expression listed in an allow-list comment `// pyimod-free: <reason>`. (c) `py_round(x)` =
   round-half-to-even (`f = Math.floor(x); d = x − f; d < 0.5 → f; d > 0.5 → f + 1; else f % 2 === 0 ? f : f + 1`) replaces
   `int(round(q))` (`curved.py` 1262); `math.floor(x + 0.5)` (`conics.sample_count`) and `int(math.ceil(x − 1e-12))`
   (`shadow.shadow_loop` step count) are ported literally as `Math.floor(x + 0.5)` and `Math.ceil(x − 1e-12)` (likewise
   M4's `ceil(ℓ / HLR_SPACING_MM − 1e-9)`). (d) `sorted()` of strings → `cmp_code_points` (code-point order, as Python
   compares `str`); `sorted()` of `(code, ids)` tuples → compare `code`, then `ids` element-wise by code points, a shorter
   prefix first.
5. **3×3 linear algebra** (`conics.ts`): determinants in closed cofactor form `a(ei − fh) − b(di − fg) + c(dh − eg)`; the
   condition number of the centred conic (`classify_and_condition`, `condition_number`; Python uses
   `np.linalg.svd(Cc, compute_uv=False)`) is `max|λ| / min|λ|` of the symmetric matrix from `jacobi_eigenvalues_3(C_c)`
   (cyclic Jacobi rotations; **stop when the off-diagonal Frobenius norm is exactly 0, or did not decrease during the last
   sweep, or after 64 sweeps** — deterministic and independent of denormal handling; `Infinity` when `min|λ| = 0`) — the
   singular values of a symmetric matrix are `|λ|`, the threshold `COND_MAX = 1e8` is coarse, and the routine is
   dependency-free.
6. **Scalar-path rule [decision].** The port implements the **scalar semantics** of each record (`pipeline._project_polygon`,
   `_project_shadow`, `_project_light`, `curved.stage_b_object`, `clip_polygon_halfspace`, `clip_segment_halfspace`): the
   batched Python kernels (`project_polygons`, `clip_polygons_halfspace`, `_project_polyhedra`, `_project_shadows`,
   `stage_b_objects`) are performance devices whose outputs must equal the scalar paths **byte for byte**. For
   `project_polygons` and `_project_polyhedra` the Python docstrings and `tests/test_bench.py` already assert this; for
   `stage_b_objects` no such test existed, so M7 adds `tests/test_curved.py::test_stage_b_objects_equals_per_object_loop`
   (for all 34 cases: `dumps(compose(scene, B_batched)) == dumps(compose(scene, B_looped))`, the loop being `stage_b_object`
   per curved object) **as a precondition of the port**; if it fails, the Python batch is fixed first (and the set
   regenerated with `--reason` if that changes an expected file). The same rule binds the vectorised fast paths that M4–M6
   permit (weld fast path, umbra chunking, HLR culling): each has its result-identity test.
7. **Predicates without a tolerance band** (`fa >= 0.0` in the near / rectangle clips, `x3 <= 0` in `ellipse_arc_params`,
   `== 0.0` tests) are kept verbatim. A conformance case whose input places a value within rounding of such an exact
   boundary is ill-posed for a two-implementation contract: if a TS/Python mismatch is traced to one, the **case** is moved
   off the boundary on the Python side (`tools/regen_conformance.py --reason`), never the predicate (README rule 3) — unless
   the boundary is the case's purpose (rule 1's cylinder-cap case), in which case the comparator is amended for the
   affected leaves through `rules.json` and a versioned CHANGELOG entry (§5.4.8).
8. **Determinism.** No `Date`, `Math.random`, `performance.now` inside `ts/src`; `Map` / `Set` iteration is insertion
   order; `Array.prototype.sort` is stable (ES2019) and is always called with an explicit comparator; `Object.keys` is never
   used to order id-keyed data. A test renders every example twice from fresh objects and compares the `dumps` and
   `write_svg` strings byte for byte, and renders with two cameras and compares the camera-free blocks of §5.0.3 byte for
   byte.

#### 5.4.5 Canonical JSON writer (`dumps`, §3.1) — exact reproduction of `json.dumps(canonical(doc), sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False)` **[decision]**
Python repr and JS `Number#toString` produce the same shortest round-trip digit strings; they differ only in notation
thresholds (`1e-07` vs `1e-7`, `1e+16` vs `10000000000000000`, `1.0` vs `1`). The comparator is numeric, so this matters only
for the byte-identical determinism rule of §2.8 and for the parity test below; the port implements Python's rules rather
than relying on `JSON.stringify`.
- **Layout**: object → `{`, newline, members on their own lines indented by `depth` spaces (one per level), `"key": value`,
  separated by `,` + newline, closing bracket on its own line at the parent's indent; arrays likewise, one element per
  line; empty object `{}`, empty array `[]`; `true` / `false` / `null`. `dumps` returns no trailing newline;
  `write_geometry_json` (test helper) and the expected files add `"\n"`.
- **Keys** sorted by `cmp_code_points` (Unicode code points, not UTF-16 units).
- **Strings** via `JSON.stringify(s)` (identical to Python with `ensure_ascii=False` for every well-formed string: `\"`,
  `\\`, `\n`, `\r`, `\t`, `\b`, `\f`, other code points < 0x20 as lowercase `\u00xx`, everything else raw); a string with a
  lone surrogate makes `dumps` throw (Python could not encode it as UTF-8 either).
- **Integers [decision]**: JS has one number type, so the writer carries the closed list `INT_KEYS` — phase 1
  `{"large_arc", "sweep"}` (the only integer-valued leaves of the v2 expected set: 74 occurrences each, verified; Python
  writes them as `int`), after phase 2 `{"large_arc", "sweep", "interval"}` (§5.0.3; `interval` is M4's run index): a
  number under one of these keys is written as `String(Math.trunc(x))`; every other number is a float. Any new integer
  field must be added to `INT_KEYS`, to `rules.json`'s `int_keys` and to the Python side consistently (a Python `int` under
  any other key is a contract violation; `tests/test_ts_port.py` scans the expected files for integer leaves and asserts
  they are all under `INT_KEYS`).
- **Floats** `py_repr(x)`: `x` must be finite (else throw: spec §7.1 row 6 forbids NaN / Inf); `x = x + 0` (maps `-0` to `0`);
  take `s = Math.abs(x).toExponential()` (ES: without an argument it yields the shortest round-trip significand), parse
  the digit string `d1d2…dn` (no dot) and the exponent `e`; `decpt = e + 1` (so that `|x| = 0.d1…dn × 10^decpt`); CPython
  `format_float_short` rule for repr: **exponential iff `decpt <= -4 || decpt > 16`**: `d1` + (`n > 1` ? `"." + d2…dn` :
  `""`) + `"e"` + (`e < 0` ? `"-"` : `"+"`) + `|e|` zero-padded to at least 2 digits; otherwise fixed: `decpt <= 0` →
  `"0." + "0".repeat(-decpt) + digits`; `decpt >= n` → `digits + "0".repeat(decpt - n) + ".0"`; else
  `digits.slice(0, decpt) + "." + digits.slice(decpt)`; prefix `"-"` when `x < 0`. Hand-computable table (both
  implementations, re-verified): `1 → "1.0"`, `0.5 → "0.5"`, `0.0001 → "0.0001"`, `0.00001 → "1e-05"`, `1.5e-7 → "1.5e-07"`,
  `1e15 → "1000000000000000.0"`, `1e16 → "1e+16"`, `123456789012345680 → "1.2345678901234568e+17"`,
  `2.842170943040401e-14 → "2.842170943040401e-14"`, `-35.43926206447239 → "-35.43926206447239"`, `-0 → "0.0"`,
  `1e300 → "1e+300"`.
- `canonical(obj)` deep-copies, applies `x + 0` to every number and throws on non-finite numbers.
- **Non-finite numbers, both sides [decision]**: a NaN / Infinity in a document is a contract violation (spec §7.1 row 6)
  and is unreachable through `render`; so that the two implementations fail the same way when it is reached, the Python
  writer passes `allow_nan=False` (`_REFERENCE_KW` and the C-encoder configuration of `castplane/output/geometry_json.py`),
  making `dumps` raise `ValueError` where the TS `dumps` throws `Error`; neither writes the token `NaN`. The CLI lets that
  `ValueError` propagate (it is a bug report, no new exit code).
- **Parity test (normative)**: for **every** file of `tests/conformance/expected/`, `dumps(JSON.parse(text)) + "\n" === text`
  (the Python set has the same test against its own writer). This exercises exponents, integers, nesting, key order and
  empty containers on 1.2 MB of real documents.

#### 5.4.6 SVG writer parity (§2.10 / §5.0.6)
`write_svg(doc, layers?, hidden_style?)` emits the **same text** as `castplane.output.svg.write_svg` for the same document:
same header lines, the six `<g id>` layers in table order with the §2.10 default styles, empty layers as `<g id="x" attrs/>`,
the sub-groups of §5.0.6, the same element strings (`<line x1=… y1=… x2=… y2=…/>`, `<polygon points="x,y x,y …"/>`,
`<path d="M x y L x y … Z M …"/>`, `<polyline points=…/>`, `<ellipse cx cy rx ry [transform=rotate(…)]/>`, arc
`<path d="M … A rx ry rot large sweep x y"/>` with the sweep flipped and the rotation negated for the y-down frame,
`<circle>`, `<text>` with `escape` of `& < >` and `&quot;` in ids), labels and the object-id label at the highest labelled
point, `"\n"` joins and a trailing `"\n"`. Number format `fmt(x)` = Python `_f`: four decimals, trailing zeros and a
trailing `.` stripped, `"-0"` → `"0"`. **[decision] Rounding ties**: Python's `:.4f` is round-half-even on the exact binary
value while JS `toFixed(4)` rounds exact ties up; an exact tie at the fourth decimal exists iff `x·32` is an odd integer
(`x = j/32`, `j` odd; any double ≥ 2^53 is even, so `|j| < 2^53` and `j = x·32` is exact). `fmt` therefore does: `x = x + 0`;
if `|x| ≥ 1e21`: `s = BigInt(x) + ".0000"` (all such doubles are integers; `toFixed` would switch to exponent notation while
Python prints the digits); else if `Number.isInteger(x·32) && Math.abs(x·32) % 2 === 1`: **exact integer arithmetic** —
`j = BigInt(Math.abs(x·32))`, `n2 = j·625n` (= `|x|·10^4·2`, exact), `f = n2 / 2n` (floor), `m = (f % 2n === 0n) ? f : f + 1n`
(half-even), `s = (x < 0 ? "-" : "") + (m / 10000n) + "." + String(m % 10000n).padStart(4, "0")`; else `s = x.toFixed(4)`;
then strip. (The earlier `y = x·1e4` formulation was exact only for `|x| < 2^54/20000 ≈ 9.0e11` while odd `x·32` exists
up to `|x| < 2^48`; the BigInt form has no such bound.) Hand-computable: `fmt(0.03125) = "0.0312"` (`j = 1`, `n2 = 625`,
`f = 312` even), `fmt(0.09375) = "0.0938"` (`j = 3`, `f = 937` odd → 938), `fmt(-0.03125) = "-0.0312"`, `fmt(-0.00004) = "0"`,
`fmt(12.5) = "12.5"`, `fmt(1e-5) = "0"`, `fmt(123.45678) = "123.4568"`, `fmt(1e21) = "1000000000000000000000"`. The bulk
formatter of the Python writer (`_fmt_bytes`) is a performance device that is proven identical to `_f`; the port may add
its own table-driven formatter only under the same identity proof (a test over 10^5 values including every tie class).
Cross-implementation SVG equality is checked by `tools/compare_svg.py` (dev tool: renders the conformance cases with both
and diffs the text; numbers within 1e-12 of a four-decimal rounding boundary are the only tolerated difference) and is
**not** a CI gate; the CI gates are the JSON conformance set and the structural SVG tests of §5.4.13.

#### 5.4.7 Pipeline, stage-A cache and the camera-only path (§3 / §5.0.7, spec §8)
```ts
const scene = load_scene(json);                       // validated, defaults filled (throws SceneError); expanded scenes only
const A     = shadow_geometry(scene);                  // stage A: never touches scene.camera
const B     = project_scene(scene, A, camera?, umbra?); // stage B: optional camera override (spec §4 camera block)
const doc   = compose(scene, B, hidden_lines?);        // stage C: spec §6.2 document, canonical floats
const svg   = write_svg(doc, layers?, hidden_style?);  // string
const text  = dumps(doc);                              // deterministic JSON
const out   = render(scene, camera?, hidden_lines?, hidden_style?, umbra?);   // {geometry: doc, svg}
```
- `A` is the camera-independent cache: object records (mesh, `face_first`, `face_point_names`, `edge_templates`,
  `world_lists`, per light the lit flags / silhouette / `form_faces` as name lists, `clipped` per receiver, curved
  `obj.curved[rid][lid] = {silhouette, terminator, points, outline, polygon}`), receiver records (§5.1.2), light records
  (`L`, and per receiver `M`, `F`, `F_defined`, `active`, tolerances), shadow records (`keep`, `P_world`, `S_world`,
  `Q_world`, `w_S`, names, `ground_points`, `loops` with entries, `S_lists` / `Q_lists` / `G_lists`), `scene_scale`, `tol`,
  `warnings`. **`project_scene` and `compose` never mutate `A`** (a test deep-freezes `A` and runs B + C twice); the
  camera-free lists of the document are shared by reference with `A`, so a document is read-only data, exactly as in
  Python.
- **Camera-free parts of a document [decision, exact list]**: the list of §5.0.3 (for phase 1, its v1 subset: `points[name]
  .world / .direction / .at_infinity` for every name **except the camera outline points** `/\.og\d+\.(base|top)$/` — §2.7:
  they exist only for the current camera and their world coordinates move with it — verified on `examples/curved_demo.json`:
  6 of 8 `og` points differ between the scene camera and the test camera, every other point is identical — and the two key
  sets agree after removing those names; `edges[].{object, from, to, silhouette}`; `shadows[].{light, receiver, object,
  outline, loops, unbounded}` and every `conics[].{arc, circle, map, which}` (not `conic` / `kind` / `sampled`: the image
  conic depends on `P`, §2.6, §5.0.3); `form_shadow[].{object, faces}`
  and the terminator entries' `segment` names; `outlines[].object`; `construction.rays`; `warnings` restricted to the codes
  that are not camera predicates — `CAMERA_LOOKING_ALONG_UP`, `LIGHT_BEHIND_CAMERA`, `LIGHT_POINT_AT_INFINITY`,
  `SHADOW_VP_AT_INFINITY`, `POINT_BEHIND_CAMERA`, `CONSTRUCTION_CHECK_SKIPPED` are camera-dependent).
- **Camera overrides are built explicitly [decision]**: `ts/test/helpers.ts: camera_override(base, position, target,
  roll_deg) = {position, target, roll_deg, focal_length_mm: base.focal_length_mm, frame_mm: base.frame_mm, shift_mm:
  base.shift_mm, near_m: base.near_m}` — never `{...base, position, target}`, which for a yaw/pitch scene
  (`examples/directional.json`, case `camera_yaw_pitch_form`) would carry `yaw_deg` + `target` and be rejected by
  `validate_camera` (§5.4.3). The bench (§5.4.9) and the UI (§5.4.10) use the same construction.
- The camera-only path is `project_scene(scene, A, cam) → compose → write_svg`; its cost on the benchmark scene is the spec
  §8 target "只換相機重算 < 100 ms" and is measured and, under the margin rule of §5.4.9, gated on the TS side: the JS object
  floor that D17 records for Python (≈150k containers) is estimated at ≈10–20 ms in V8 and the SVG formatting of ≈128k
  numbers at ≈20–30 ms, leaving ≈35 ms of numeric work — **estimates, to be replaced by the step-7 measurement**; nothing in
  the path allocates typed arrays beyond the §5.4.2 allowance, and nothing caches stage-B results across cameras (there is
  exactly one cache, stage A).

#### 5.4.8 Conformance runner (`ts/test/conformance.test.ts`, spec §7.5, README rule 3)
- Locates the repository root from `import.meta.url` (`ts/build/test/` → `../../..`) and reads `tests/conformance/cases/*.json`,
  `tests/conformance/expected/*.json` and `tests/conformance/rules.json` **directly from the repository**; no copy of the set
  exists under `ts/`, and the port never writes expected files.
- Per case: `load_scene(JSON.parse(caseText))` → `render(scene)` → `actual = JSON.parse(dumps(result.geometry))` (round trip
  through the writer, as `tests/test_conformance.py::render_case` does) → `compare_documents(expected, actual, caseName)`
  must return `[]`; failures print the case name and up to `max_reported` mismatch paths in the Python format
  (`points.crate.v0.image[0]: expected …, got … (tolerance 1e-06 mm)`).
- `compare_documents` is the literal port of `tests/test_conformance.py` (`_walk`, `is_image_path`, `_numbers_match`, the
  warning code set and `(code, ids)` set rules; integers and floats are both numbers; booleans, strings, nulls, list lengths
  and key sets exact), extended on **both** sides by the per-case override lookup below and, from v4 on, by the `runs_rule`
  of §5.0.8.
- **[decision] Single source of the comparator constants**: `tests/conformance/rules.json`. Its v3 content is
  ```json
  {"image_tol_mm": 1e-6, "rel_tol": 1e-9,
   "mm_keys": ["image", "segment", "polygons", "polylines", "light_point", "shadow_vp", "v_mm", "vanishing_points", "principal_point", "canvas_mm", "max_error_mm"],
   "drawable_containers": ["arcs", "ellipses"],
   "arc_non_mm": ["rotation_deg", "theta", "large_arc", "sweep"],
   "mm_key_paths": [["construction", "segments", "*", "points"]],
   "int_keys": ["large_arc", "sweep"],
   "max_reported": 25,
   "case_overrides": {
     "degenerate_cylinder_cap_at_light_height": [
       {"paths": [["shadows", "*", "loops", "*", "*", "direction"], ["shadows", "*", "outline", "*", "direction"]],
        "abs_tol": 1e-6,
        "reason": "direction vertices at a tangent w_S = 0 crossing (curved._zero_shift, acos near |c| = 1): sqrt-type amplification, measured 1.5e-9 absolute per ulp of M or L"}]}}
  ```
  and its final (v6) content is in §5.0.8. `drawable_containers` is the container rule that `is_image_path` hard-codes
  today (`("arcs", "ellipses")`), lifted into the file so that an M4–M6 drawable container is added once. A `case_overrides`
  entry applies an absolute tolerance `abs_tol` to every number whose path matches one of `paths` (`*` matches one list
  index or key) in that case only, instead of the default rule; it never relaxes non-number comparisons, key sets or
  warnings. `tests/test_conformance.py` keeps its constants, asserts they equal the file, and reads `case_overrides` from it
  (its only new behaviour in v3: 4 leaves of one case go from 1e-9 relative to 1e-6 absolute; the directions are
  max-normalised so `|d_i| ≤ 1`, and 1e-6 keeps six decimals pinned, a ≥ 600× margin on the measured sensitivity while
  still a comparison, not a waiver — README rule 4 already judges degenerate cases by codes and finiteness).
- **Versioning of comparator changes [decision]**: any change to `rules.json` is a change of the conformance contract and
  is recorded like a regeneration: `tools/regen_conformance.py --rules-only --reason "..."` appends `## v<N>` to
  `CHANGELOG.md` with "comparator amendment, no expected file changed" plus the rules diff, bumping the set version without
  touching `expected/`. The `case_overrides` entry above is **conformance set v3** (CHANGELOG: "v3 — comparator amendment
  for degenerate_cylinder_cap_at_light_height direction vertices (M7 design probe, contract §5.4.4 (1)); no expected file
  changed"), applied in implementation step 1 and merged to `main` before the M4 regeneration (§5.0.8). There is **no**
  pre-authorised loosening of `construction.segments[].points` (the earlier §4 (i)-style exception is withdrawn: spec §7.5
  and README fix those at 1e-6 mm, the probe found no need, and if a ray-endpoint mismatch ever appears it is handled by
  the drift rule below).
- Also asserted: `cases/` and `expected/` correspond one to one and are non-empty; every case loads; the §5.4.5 parity test.
- **Drift rule (README rule 3, restated for CI)**: both runners must pass on the same commit. A TS failure is a TS bug
  unless a contract review shows the Python output violates the spec / contract, in which case Python is fixed and the
  set regenerated with `--reason` (the CHANGELOG entry names the TS finding); or, when the mismatch is an ulp-amplifying
  boundary that is the case's purpose, a `case_overrides` entry is added through `--rules-only` with the measured
  sensitivity in its `reason`. Either route is a versioned CHANGELOG entry; nothing is changed silently.

#### 5.4.9 Benchmark (`ts/bench/camera_only.ts`, spec §8, D17 closure)
- Scene: `benchmarks/scenes/benchmark_100.json`, written by `benchmarks/export_scene.py` from
  `tests.reference.random_scenes.make_benchmark_scene()` through `castplane.output.geometry_json.canonical` +
  `json.dumps(sort_keys=True, indent=1)` + newline (the generator's leaves are plain Python floats / ints / strings,
  verified: 6748 floats, 4 ints, 213 strings), together with `benchmark_100.build.json` = `{"python": …, "numpy": …}`.
  **Lock rule [decision]** (`tests/test_bench.py::test_benchmark_scene_file_matches_generator`): byte equality with the
  generator is required only when the running NumPy version equals the recorded one (the `Generator` bit stream is not
  frozen across NumPy releases by NEP 19), otherwise the test requires that the committed file and the freshly generated
  scene both load and have the same object count, types and mesh edge count (the spec §8 size), exactly as
  `test_regen_tool_exit_codes_match_its_docstring` treats drift. `benchmarks/bench.py` **loads the committed file** when run
  with its default arguments (100 objects, curved) and generates only for `--objects` / `--no-curved` / `--scene` /
  `--lights` / `--hidden-lines` variants (§5.0.9), so the two benchmarks measure the same input bytes on every build;
  `tests/test_reference.py` keeps checking the edge count (≈10.7k).
- Protocol (mirrors `benchmarks/bench.py`): `load_scene`; `other_camera = camera_override(scene.camera, [6, -28, 12],
  [0, 0, 0.5], 3)` (§5.4.7; same lens fields as the Python `dict(scene["camera"], position=…, target=…, roll_deg=3.0)` on
  this target-form scene); warm-up: 3 full renders (JIT); then `reps` (default 20) timings with `performance.now()` of:
  full render (`shadow_geometry + project_scene + compose + write_svg(scene.output.layers) + dumps`), camera-only
  (`project_scene(scene, A, other_camera) + compose + write_svg`), stage A alone, `write_svg` alone, `dumps` alone; reports
  min and median. **`--json` prints the same record as `bench.py` with the same field names**: `objects`, `mesh_edges`,
  `document_edges`, `points`, `svg_bytes`, `json_bytes`, `warnings` (sorted codes), `reps`, `full_render_s: {min, median,
  target}`, `camera_only_s: {min, median, target}`, `stage_a_s`, `svg_s`, `json_s` (`{min, median}`), `pass: {full_render,
  camera_only}`, `gate`, plus `engine: {node, v8}` (TS only; `camera_only_no_gc_s` is Python only). `--gate
  both|full|camera|none` (default `both`); exit 1 when a gated target fails (min over reps).
- **Targets and the CI gate [decision]**: the spec §8 targets are full render < 1 s and camera-only < 100 ms, both
  measured by the TS bench. The *acceptance command* of spec §10 M7 is `node ts/build/bench/camera_only.js --gate both
  --reps 20` exiting 0 on the CI container, recorded with its numbers in `benchmarks/README.md` ("TypeScript port" table:
  node version, three runs, min / median per row). The *CI gate* is decided by that measurement with a margin against
  shared-runner noise (the Python rows drift ±15 % between runs and 10–40 % across containers): if the camera-only minimum
  over 20 reps is **< 70 ms** (≥ 1.4× margin) on the GitHub runner, `ci.yml` gates `--gate both` and D17's deferral is
  closed; otherwise `ci.yml` gates `--gate full`, the camera-only row stays recorded exactly as D17 records it for Python,
  and the number is reviewed at the M7 gate. The gate literal in `ci.yml` is set once at step 7 and changed only with a
  new recorded measurement; it is never loosened to absorb a regression.
- The Python gate stays `--gate full` (D17).

#### 5.4.10 Web UI (`web/`, spec §10 M7 "three.js 場景顯示、相機拖曳、SVG 下載")
Modules (all TypeScript, strict; only `orbit.ts` and `download.ts` are DOM-free and unit-tested):
- `src/main.ts` — state `{scene, sceneName, A, orbit, layersChecked, doc, svg, timings, dragging}`; wires the modules;
  `THREE.Object3D.DEFAULT_UP.set(0, 0, 1)` at startup.
- `src/examples.ts` — `import.meta.glob('../../examples/*.json', {eager: true, import: 'default'})` fills the examples
  `<select>` at build time (the five files: basic, construction_demo, curved_demo, directional, three_point; no copying,
  no fetch, no server). Loading: file `<input type="file" accept=".json">`, page-wide drag-and-drop (`dragover` / `drop`),
  the examples menu. A dropped non-JSON file shows "not a JSON file". On load: `load_scene_text` (a `SceneError` shows
  `field` + `detail` in the error panel; the previous scene stays) → `A = shadow_geometry(scene)` (timed, shown) →
  `orbit = orbit_from_camera(scene.camera, scene)` → `scene3d.build` → layer checkboxes initialised from
  `scene.output.layers` → first render.
- `src/scene3d.ts` — `build_scene3d(scene): THREE.Group`: box → `BoxGeometry(sx, sy, sz)` translated `(0, 0, sz/2)`;
  cylinder → `CylinderGeometry(r, r, h, 64)` rotated `+π/2` about X (three's cylinder axis is +Y) and translated
  `(0, 0, h/2)`; cone → `ConeGeometry(r, h, 64)` likewise; sphere → `SphereGeometry(r, 48, 24)` translated `(0, 0, r)`;
  prism → `ExtrudeGeometry(new Shape(polygon), {depth: h, bevelEnabled: false})`; mesh (phase 2) → `BufferGeometry` from
  the record's `triangles`. Each mesh: `matrixAutoUpdate = false`, `matrix` set column-wise from the core's
  `transform_frame(obj.transform)` (`R`, `position`), so three.js never interprets Euler angles (its `'ZYX'` order would
  agree, but the core's `R` is the single source). Materials: `MeshLambertMaterial` with a per-object colour,
  `castShadow = receiveShadow = false`. Lights as **helpers only**: a point light → a small emissive sphere at `position` +
  a `THREE.PointLight` for shading; a directional light → an `ArrowHelper` at the scene centre along `+direction` + a
  `THREE.DirectionalLight`; plus `AmbientLight`. Receivers → a `PlaneGeometry` of 4× the scene extent at `z = 0` with a
  `GridHelper` (rotated to the XY plane) for the unbounded ground and a `PlaneGeometry` of each bounded receiver's
  `bounds` (phase 2). `renderer.shadowMap.enabled = false` (normative, §5.4.0).
- `src/threeCamera.ts` — `apply_camera_block(cam3: THREE.PerspectiveCamera, block, canvas_mm, scene_scale)`: calls the
  core's `camera_matrix(block, canvas_mm)` and sets `cam3.matrixAutoUpdate = false`, `cam3.matrix` with columns `right'`,
  `up'`, `−forward` (three cameras look down local −Z; `det(right', up', −forward) = +1`) and translation `C`, copies it
  to `matrixWorld`, `matrixWorldInverse = inverse`; the projection is built directly: with `W, H = frame_mm`,
  `f = focal_length_mm`, `(u0, v0) = shift_mm` (frame mm) and `near = near_m`: `left = near·(−W/2 − u0)/f`,
  `right = near·(W/2 − u0)/f`, `top = near·(H/2 − v0)/f`, `bottom = near·(−H/2 − v0)/f`, `far = max(100, 20·scene_scale)`;
  `projectionMatrix.makePerspective(left, right, top, bottom, near, far)`, `projectionMatrixInverse` = its inverse.
  `lookAt`, `updateProjectionMatrix`, `fov`, `aspect` and `filmOffset` are never used: the WebGL view and the SVG overlay
  are two renderings of one castplane camera.
- `src/orbit.ts` (pure) — `OrbitState = {target: Vec3, distance, yaw_deg, pitch_deg, roll_deg, focal_length_mm}`.
  `orbit_from_camera(cam, scene)`: target form → `target = cam.target`, `distance = |target − position|`; yaw/pitch form →
  `forward` from §2.2, `distance = −position_z / forward_z` when `forward_z < −1e-9` (the point where the view axis meets
  the ground), else `5`, `target = position + distance·forward`; in both forms `pitch_deg = degrees(asin(f_z))`,
  `yaw_deg = degrees(atan2(−f_x, f_y))` (the inverse of §2.2's yaw/pitch formula), `roll_deg`, `focal_length_mm` copied.
  **`camera_from_orbit(state, base)` builds the block explicitly in target form from the lens fields**: `{position:
  target − distance·forward(yaw, pitch), target, roll_deg, focal_length_mm, frame_mm: base.frame_mm, shift_mm:
  base.shift_mm, near_m: base.near_m}` — never `{...base, …}` (a yaw/pitch `base` would make `validate_camera` reject the
  result on every frame, §5.4.3); `frame_mm` is fixed by the scene (its aspect is tied to `canvas_mm`), `shift_mm` and
  `near_m` are not editable in M7. Input mapping (per pointer event, state only): left drag `yaw_deg −= dx·(180 / H_px)`,
  `pitch_deg += dy·(180 / H_px)` clamped to `[−89.5, 89.5]` (keeps `CAMERA_LOOKING_ALONG_UP` out of reach; dragging right
  orbits the camera to the right like OrbitControls); right drag or Shift + drag pans `target += (−dx·k)·right' +
  (dy·k)·up'` with `k = distance·(frame_mm[1] / f) / H_px` (metres per pixel at the target depth) and `right'`, `up'` from
  `camera_matrix`; wheel `distance *= exp(0.001·deltaY)` clamped to `[0.05, 1e4]`; a roll slider `[−180, 180]`; a
  focal-length slider, logarithmic `[8, 400] mm`; a "Reset camera" button restores `orbit_from_camera(scene.camera)`.
  Hand-computable (the camera of `analytic_unit_box_point_light_overhead`, `position (4, −8, 5)`, `target (0, 0, 0.5)`;
  **not** the spec §4 camera, which is `(0,0,1.5) → (0,5,1.0)`): `distance = √100.25 = 10.012492197250394`,
  `forward = (−0.39950093555113786, 0.7990018711022757, −0.44943855249503006)` (= the third row of the `P` of that case),
  `yaw_deg = degrees(atan2(0.3995…, 0.7990…)) = degrees(atan(0.5)) = 26.56505117707799`,
  `pitch_deg = degrees(asin(−0.44943855249503006)) = −26.7076677665586` (tolerance 1e-9°); `camera_from_orbit` returns
  `position = (0,0,0.5) − 10.0124…·forward = (4, −8, 5)` within 1e-9 and a block that `validate_camera` accepts.
- Render loop — `request_render()` marks the state dirty and schedules **one** `requestAnimationFrame` callback; the
  callback (if dirty): `cam = camera_from_orbit(orbit, scene.camera)` → `B = project_scene(scene, A, cam, umbra)` (`umbra =
  !state.dragging` in multi-light scenes, §5.3.3) → `doc = compose(scene, B)` → `svg = write_svg(doc, LAYER_IDS)` (all six
  layers; visibility is CSS) → overlay update → `apply_camera_block` + `renderer.render` → warnings panel → timings
  (`core ms` = B + C + SVG, `dom ms` = overlay update). Pointer events only mutate state ("latest camera wins"); at most one
  core render per frame; the main thread is used (a Web Worker is permitted by §5.4.11 but not required).
- `src/overlay.ts` — an `<svg>` element laid exactly over the WebGL canvas (same CSS box, `viewBox="0 0 W H"` in canvas
  mm, `preserveAspectRatio="xMidYMid meet"`, `pointer-events: none`); `set_svg(text)` replaces its children with the
  content between the core's `<svg …>` and `</svg>` (`innerHTML` of the inner markup; the core's header is not inserted
  twice). **DOM budget [decision]**: the per-frame `innerHTML` of the full SVG is the UI's unbounded cost (the benchmark
  scene's SVG is 1.96 MB / ≈ 30k elements and will not lay out in 100 ms in any browser), so the UI distinguishes the
  *resting frame* (DOM overlay, always) from *frames during a drag* (`state.dragging`): during a drag the overlay **may**
  instead display the writer's unchanged SVG text through `<img src="blob:…">` (`URL.createObjectURL(new Blob([svg],
  {type: "image/svg+xml"}))`, revoked on the next frame) — still the writer's output, no document change — and the DOM
  overlay is restored on pointer-up; the implementer picks the mode per frame by `svg.length` (threshold recorded in
  `web/README.md`). `dom ms` is shown in the status line and recorded for the five example scenes and for
  `benchmark_100.json` (§5.4.13). The viewport element keeps the `canvas_mm` aspect (letterboxed), so the overlay and the
  WebGL image coincide pixel for pixel (a visual self-check of the port: object edges drawn by the core lie on the
  three.js silhouettes). Layer toggles: six checkboxes (initialised from `scene.output.layers`) set classes `hide-<layer>`
  on the overlay; CSS `.hide-labels #labels {display: none}` etc. (ids are the §2.10 layer ids; in `<img>` mode the layer
  subset is written by `write_svg(doc, checked)` instead); a "3D view" checkbox hides the WebGL canvas; phase 2 adds a
  "hidden lines" checkbox (passed as `hidden_lines` to `compose`).
- `src/download.ts` (pure) — `svg_blob(doc, layers)` → `write_svg(doc, layers)` with the **checked** layers in §2.10 order
  (`"<sceneName>.svg"`, `image/svg+xml`); `json_blob(doc)` → `dumps(doc) + "\n"` (`"<sceneName>.json"`, the spec §6.2
  document); `scene_blob(scene, cam)` → `dumps({...scene, camera: cam})` + `"\n"` where `cam` is the explicit target-form
  block of `camera_from_orbit` (so the result never carries both forms; `"<sceneName>.scene.json"`: the loaded scene with
  the current camera block, so the Python CLI reproduces the picture: `castplane render x.scene.json -o out`). Buttons:
  "Download SVG", "Download JSON", "Download scene (current camera)", "Copy camera block" (clipboard).
- Warnings panel — a table of `doc.warnings` (`code`, `ids`, `message`) refreshed per frame; the error panel shows
  `SceneError.field` / `.detail` and loader errors. A status line shows `core ms`, `dom ms`, points / edges / rays counts.
- No server: `vite build` emits static files under `web/dist` (`base: './'`), openable from any static host; `vite preview`
  / `vite` for local use. No network access at runtime (examples are bundled).

#### 5.4.11 "Fast" compromises — what is and is not acceptable **[decision]**
D17 named two candidate shortcuts for the camera-only budget; both are decided here, with the UI-level shortcuts after them.
| shortcut | verdict | reason |
| --- | --- | --- |
| (D17-a) a leaner document shape (flat / typed-array records instead of the §3.1 nested lists) | **not acceptable** for the document; acceptable only as private stage-B scratch under the §5.4.2 `Float64Array` rule | §3.1 is the conformance format and the download; the TS portability rule means the document is the same JSON in both implementations |
| (D17-b) a compiled / table-driven number formatter for the SVG | **acceptable** iff provably identical to `fmt` (§5.4.6 identity test incl. tie classes) | the Python writer already does this (`_fmt_bytes` ≡ `_f`) |
| coalescing pointer events into one render per animation frame, latest camera wins | **acceptable and required** | changes no result |
| running B + C + SVG in a Web Worker | acceptable (pure functions, no shared state), optional | the gate is measured in-thread |
| showing the writer's unchanged SVG text through `<img src=blob:>` instead of a live DOM overlay **during a drag**, DOM overlay at rest | **acceptable**, optional (§5.4.10) | the displayed picture is still the writer's output for the contract document of that frame; only the browser's rendering path changes |
| skipping the umbra (`umbra=False`) and hidden lines during a drag | **acceptable** (§5.3.3, §5.1.6.6: both are documented switches whose off state is a contract document) | the resting frame recomputes them |
| a "drag preview" with fewer samples, no self-checks, no labels, or a sparser document | **not acceptable** | every rendered document must be the contract document; layer visibility is CSS (or the writer's `layers` subset); "what you see is what you download" |
| caching stage-B results across cameras (e.g. reusing projections when only `f` changes) | **not acceptable** in M7 | the only cache is stage A (§5.4.7); no measured need |
| drawing the overlay from the document with DOM / Canvas calls instead of the SVG writer's text | **not acceptable** | the displayed picture must be the writer's output |
| taking `P` from the three.js camera, or feeding three.js from a camera other than the core's `camera_matrix` | **not acceptable** | the core is the single source of the camera; three.js only displays |
| `Float32Array`, `Math.fround`, GPU computation in the core | **not acceptable** | §2.8 float64 |
| three.js shadow maps, even as a preview | **not acceptable** | spec §9 |
| bit-determinism (same bytes per build), camera independence of stage A, TS portability of every document field | **invariant** — any shortcut that touches one of them is rejected regardless of speed | §5.4.0 |

#### 5.4.12 CI additions (`.github/workflows/ci.yml`)
```yaml
  ts:
    runs-on: ubuntu-latest
    strategy: {fail-fast: false, matrix: {node: ["20", "22"]}}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: {node-version: "${{ matrix.node }}", cache: npm}
      - run: npm ci
      - run: npm run -w ts build                # tsc -p tsconfig.json && tsc -p tsconfig.test.json
      - run: npm run -w ts test                 # node --test build/test/ (conformance, parity, determinism, unit)
      - if: matrix.node == '22'
        run: node ts/build/bench/camera_only.js --gate <both|full, set at step 7 by the §5.4.9 margin rule> --reps 20
      - if: matrix.node == '22'
        run: npm run -w web test && npm run -w web build                   # orbit tests, type check, vite build
```
The Python `test` job additionally runs `tests/test_ts_port.py` (no node needed). `package-lock.json` is committed; `npm ci`
is the only install step. The benchmark step uses the minimum over 20 repetitions after 3 warm-ups; with `--gate both` in
place a failure is a regression to investigate (re-running a visibly throttled job is allowed; changing the gate literal
requires a new recorded measurement in `benchmarks/README.md`, §5.4.9).

#### 5.4.13 Test contract of the port (`ts/test/`, `web/test/`, `tests/test_ts_port.py`, Python preconditions)
- `conformance.test.ts` (§5.4.8): 34/34 cases at set v3 (phase 1), the full set at v6 (phase 2); `rules.json` loaded incl.
  `drawable_containers`, `runs_rule`, `int_keys` and `case_overrides`; the comparator self-tests ported from
  `test_comparator_detects_drift_of_each_kind` and `test_image_path_classification`, plus one asserting that the override
  applies only to the named case and paths (the same leaf in another case still uses 1e-9 relative).
- `geometry_json.test.ts` (§5.4.5): the parity test over all expected files; the `py_repr` table of §5.4.5;
  `cmp_code_points` (e.g. `"a.v10" < "a.v2"`, `"Z" < "a"`); `INT_KEYS`; `-0` canonicalisation; non-finite throws.
- `svg.test.ts` (§5.4.6): `fmt` table incl. ties and negatives; structure of `write_svg(doc)` for `example_basic` and
  `example_curved_demo` (six groups in order, sub-group ids, one element per drawable, empty layer as `<g …/>`, header and
  trailing newline, the layer subset behaviour and the `ValueError`-equivalent `Error` for unknown layer ids).
- `determinism.test.ts` (§5.4.4 (8), §5.4.7): every `examples/*.json` rendered twice from fresh objects → identical `dumps`
  and `write_svg` strings; rendered with the scene camera and with `camera_override(scene.camera, [6, -28, 12], [0, 0, 0.5],
  3)` → the camera-free blocks listed in §5.4.7 / §5.0.3 are byte-identical (`points` compared after removing names matching
  `/\.og\d+\.(base|top)$/`, and the key sets agree after that removal); `shadow_geometry` called on a scene whose `camera`
  property is a `Proxy` whose `get` throws → no throw; `A` deep-frozen → `project_scene` + `compose` run twice without
  throwing. This test must pass on `examples/directional.json` (yaw/pitch form) — it is the regression test for the
  explicit-override rule.
- `camera.test.ts`: the §2.2 roll vector — camera `(0,0,1.5) → (0,5,1.5)`, `f = 35`, frame = canvas = `(36, 24)`, roll
  `+10°`: world `(0, 5, 2.5)` projects to `u = 35·sin 10°·0.2 = 1.2155372436685123 mm` (`|Δ| ≤ 1e-9`, `u > 0`); `det R = −1`;
  the yaw/pitch form equals the target form for the camera of `analytic_unit_box_point_light_overhead` within 1e-12 in `P`.
- `analytic.test.ts` — the **hand-computable acceptance case of spec §10 (M7 row: "一致性測試集 100% 通過")**, run through
  the port alone and checked against hand values, independently of the expected file: case
  `analytic_unit_box_point_light_overhead` (cube `size [1,1,1]` at the origin, lamp `(0, 0, 3)`, camera
  `(4, −8, 5) → (0, 0, 0.5)`, `f = 35`, frame `36×24`, canvas `360×240`): the top vertices `v4..v7 = (∓0.5, ∓0.5, 1)` have
  shadows `base × h/(h−1) = × 1.5`: `points["cube.v4.shadow.lamp"].world = [−0.75, −0.75, 0]`, `v5 → [0.75, −0.75, 0]`,
  `v6 → [0.75, 0.75, 0]`, `v7 → [−0.75, 0.75, 0]` (`|Δ| ≤ 1e-12`), `shadows[0].outline = ["cube.v4.shadow.lamp",
  "cube.v5.shadow.lamp", "cube.v6.shadow.lamp", "cube.v7.shadow.lamp"]` (counter-clockwise in ground `(x, y)`),
  `unbounded = false`, `warnings = []`, `F.lamp.world = [0, 0, 0]`; the vertical plane through the camera and its target
  contains the z axis (`x = −y/2`), so `construction.light_point[0] = 0` and `shadow_vp[0] = 0` (`|Δ| ≤ 1e-9 mm`), and the
  depth of `L` is `forward·(L − C) = (−4)(−0.3995009…) + 8·(0.7990018…) + (−2)(−0.4494385…) = 1.5980037422045514 +
  6.392014968818206 + 0.8988771049900601 = 8.888895816012818` (`|Δ| ≤ 1e-9`); the published values
  `light_point = [0, 87.93525754212652]`, `shadow_vp = [0, −15.270708139022979]`, `horizon.v_mm = 176.09035322810843` must
  match within 1e-6 mm; every `construction.checks[].max_error_mm ≤ 1e-9`; 12 edges, 18 points. Second hand case:
  `analytic_sun_45deg_box` — the shadow of each top vertex is displaced horizontally by exactly the vertex height
  (`|S − Q| = h` within 1e-12 m; measured Python residual 4.5e-16 m). Phase 2 adds the hand cases of §5.1.11
  (`wall_and_ground`), §5.2.12 (mesh box) and §5.3.10 (two symmetric lights) through the port.
- `numerics.test.ts`: `pymod` table (`pymod(-1e-17, 2π) = 2π`, `pymod(7, 2π) = 0.7168146928204138`, `pymod(-0.5, π) = π − 0.5 =
  2.641592653589793`, `pymod(0, -1) = -0`); `pyimod(-1, 5) = 4`, `pyimod(-7, 4) = 1`, `pyimod(3, 4) = 3`; `py_round(0.5) = 0`,
  `py_round(1.5) = 2`, `py_round(2.5) = 2`, `py_round(-0.5) = -0` (Python `round` gives `0`; the sign is irrelevant since the
  result indexes a list); the **`%` grep rule** of §5.4.4 (4b) over `ts/src`; the **neutrality grep**: no file under `ts/src`
  contains `node:`, `process.`, `Buffer`, `require(`, `import.meta`, `performance.` (the compile with `types: []` enforces
  most of this; the grep makes the rule visible); `jacobi_eigenvalues_3(diag(1, 1e-9, 1))` → cond `1e9 > COND_MAX`;
  `classify` of the §2.6 "0.3 m circle 50 m away" conic = `ellipse`, not sampled; `sample_count(0, π) = 32`,
  `sample_count(0, 0.1) = 8`, `sample_count(0, 2π) = 64`.
- `scene.test.ts`: every §2.0 row with its field path (e.g. `objects[0].polygon` self-intersecting, `output.canvas_mm` aspect
  with the spec's own `[257, 182]` example rejected, `lights` length ≠ 1 in phase 1 / `lights` empty in phase 2, `camera`
  both forms given → `SceneError("camera", …)`, empty `output.layers`); defaults filled; clockwise prism reversed.
- `degenerate.test.ts`: one scene per spec §5.7 row asserting the warning code set and finite output (ported from
  `tests/test_degenerate.py`'s smallest scenes), plus `LIGHT_INSIDE_OBJECT` (sphere, box) and the undefined `F` / `L'` cases.
- `errors.test.ts`: `WARNING_CODES` of `ts/src/errors.ts` equals the literal of `castplane/errors.py` (read from the
  repository at test time).
- `web/test/orbit.test.ts`: the §5.4.10 hand example (incl. `pitch_deg = −26.7076677665586`); round trip
  `camera_from_orbit(orbit_from_camera(cam))` for **both camera forms** — `examples/basic.json` (target form),
  `examples/directional.json` and the case `camera_yaw_pitch_form` (yaw/pitch form) — within 1e-9 m in `position` and with
  `validate_camera` accepting every produced block; pitch clamp ±89.5°; pan / zoom bounds; `download.ts` names
  (`<name>.svg`, `<name>.json`, `<name>.scene.json`) and MIME types, and `scene_blob` output re-validating through
  `load_scene_text`.
- `tests/test_ts_port.py` (Python): `ts/package.json` version == `castplane.__version__` == `ts/src/index.ts`'s `__version__`;
  `tests/conformance/rules.json` equals the constants of `tests/test_conformance.py` (incl. `drawable_containers`); every
  integer-valued leaf of every expected file sits under a key of `INT_KEYS` (read from `ts/src/output/geometry_json.ts` by a
  regex on the `INT_KEYS` literal) and `INT_KEYS == rules.json["int_keys"]`; no file under `ts/src/` contains `node:`,
  `process.`, `Buffer`, `require(`, `import.meta`; `benchmarks/scenes/benchmark_100.json` lock rule (in `tests/test_bench.py`,
  §5.4.9).
- **Python preconditions added by M7** (shared files): `tests/test_curved.py::test_stage_b_objects_equals_per_object_loop`
  (§5.4.4 (6)); `tests/test_conformance.py::test_rules_json_matches_constants` and `::test_case_override_scope`;
  `geometry_json` `allow_nan=False` test (`dumps({"x": float("nan")})` raises `ValueError`).
- **Acceptance of "相機拖曳即時更新" (spec §10 M7)**: (a) `node ts/build/bench/camera_only.js --gate both --reps 20` exits 0 on
  the CI container (camera-only min < 100 ms, full < 1 s, 20 reps after 3 warm-ups), recorded in `benchmarks/README.md` with
  the §5.4.9 CI-gate decision; (b) the UI acceptance scenes are the **five `examples/*.json`**: for each, `core ms` and
  `dom ms` of a drag frame are recorded in `web/README.md` (expected: a few ms each; their SVGs are a few hundred elements),
  and for `benchmark_100.json` the same two numbers plus the overlay mode used during drag; the status line shows the same
  measurement live.

#### 5.4.14 Document format and extension points (the M4–M6 format the port carries in phase 2)
The port is written against the document format of §5.0.3 (§3.1 as amended by M4–M6), ported in phase 2 (§5.4.0); this
section fixes what is format-independent and names the phase-2 scope. The phase-1 `GeometryDocument` type (`src/document.ts`)
is the literal transcription of §3.1; the phase-2 type is that of §5.0.3. Extension points the implementer must keep open
**[decision]**: (a) `shadows[]` entries are keyed by the triple `{light, receiver, object}` and `compose` iterates
receivers → lights → casters (§5.1.3.1), so per-receiver shadow lists and umbra drawables are additional keys on the same
entries or sibling blocks, never a reshaping of the existing ones; (b) `edges[].visibility` is a template field copied from
`edge_templates` and overwritten per camera, so the run list (`runs: [...]`) is filled by `hidden.classify_document` in
stage C without touching stage A; (c) `construction` is produced by one function `construction_block(lightRecord,
shadowRecords)` so that the per-light map `constructions` of §5.3.5 is a loop around it and `construction` its first entry;
(d) every new drawable key is added to `rules.json` (`mm_keys`, `drawable_containers` or `mm_key_paths`) and every new
integer field to `INT_KEYS` / `int_keys` — the final lists are in §5.0.8; (e) new warning codes are added to `WARNING_CODES`
in both implementations in the same commit (`errors.test.ts` asserts the two lists are equal by reading
`castplane/errors.py`'s literal); (f) a new case that sits on an ulp-amplifying boundary by design gets its
`case_overrides` entry in the same CHANGELOG version that adds the case. **Phase-2 scope [decision, synthesis]** (the
modules of §5.0.7 that are core geometry): `src/hidden.ts` (§5.1.6: occluders, `first_hit`, sampling / bisection,
`drawn_segment_4d`, `clip_polygon_4d`, `classify_document`), the receiver generalisation of `shadow.ts` / `curved.ts` /
`pipeline.ts` (§5.1.2–§5.1.5: `receiver_frame`, `bounds_functionals`, `clip_polygon_bounds` with the anchor rule, per-receiver
records and `per_receiver` construction), `src/meshprep.ts` (§5.2.3 incl. the fallback of §5.2.5 and the `mesh` kind in
`primitives.ts` / `scene.ts`), `src/umbra.ts` and `src/multilight.ts` (§5.3.2–§5.3.4), the multi-light SVG builders (§5.3.6)
and the hidden-run SVG groups (§5.1.8). Nothing an M4–M6 case needs lies beyond scene JSON: M5 cases embed `data` inline
(§5.2.9), M8 adds no case (§5.5.10), so the port implements **no loader**.

### Implementation notes
- **[decision, implementation] (M7 step 1) Path patterns are prefixes.** A `case_overrides` path (and, as before, an
  `mm_key_paths` entry) matches a number when the pattern matches the **first `len(pattern)` entries** of the number's
  path (`*` = any one list index or key): the v3 patterns end at the container key `direction` while the numbers sit one
  level deeper (`shadows[0].loops[0][30].direction[1]`), so whole-path equality would match nothing. This is the rule
  `is_image_path` already applied to `["construction", "segments", "*", "points"]`; the TS runner implements the same
  prefix rule (`tests/test_conformance.py::path_has_prefix`).
- **[decision, implementation] (M7 step 1) What `--rules-only` diffs against.** Each `--rules-only` entry records the
  complete rules (one canonical JSON line under `- rules (tests/conformance/rules.json at v<N>):`) next to the diff, and
  the diff of the next entry is taken against the last recorded rules (the first entry says "rules.json created"); git
  is not consulted. An unchanged `rules.json` is refused (exit 1) and `--rules-only --case` is a usage error (exit 2).
  `tests/test_conformance.py::test_rules_json_is_versioned_in_the_changelog` requires the last recorded rules to equal
  `rules.json`, so a comparator change without a changelog entry fails the suite. A rules-only entry renders nothing and
  therefore records no `- build:` line; `recorded_numpy_version()` takes the build of the last entry that has one.

### 5.5 M8 — STEP import (spec §9 row "STEP", spec §10 M8) — a loader, outside the core

Everything in this section is a **loader** in the sense of spec §8 ("載入 … 為可選附加套件"): it runs *before*
`validate_scene` (through the expansion step of §5.0.2), it turns a loader-only object into ordinary §2.0 objects, and the
core (`scene.py` and everything after it) never sees a STEP file, a `path`, or OpenCascade. Consequences that hold by
construction: stage A stays camera independent (§2.8); the §3.1 document is still derivable from the (expanded) scene JSON
by pure geometry; the TypeScript port (§5.4) does **not** port this section — it consumes expanded scenes; the spec §8
performance targets are unaffected because no core module changes behaviour. Design validated on a throwaway prototype
against files written by Open CASCADE 8.0 (cadquery-ocp 8.0.1.1.0): the cylinder fixture expands to a scene that renders
**byte-identically** to `tests/conformance/expected/example_basic.json`; see §5.5.10. Spec §10 lists M5 as M8's
prerequisite: the analytic path (§5.5.2–§5.5.6) does not depend on M5, the tessellation fallback (§5.5.7) does; because M8
is implemented after M5 (`docs/PLAN-v2.md`) the fallback is **enabled** in this contract **[decision, synthesis]** (the M8
design's "rejected until M5" clause and the "prototype complete, mesh fallback pending M5" wording are superseded; the
README M8 row reads "原型完成（Part-21 解析器、四種基元、`castplane import`）；網格退路經 M5 內嵌網格型別").

#### 5.5.0 Package layout additions (the shared `castplane/io/` package is §5.0.2)
```
castplane/io/__init__.py      registry EXPANDERS = {"step": expand_step_object, "mesh": expand_mesh_object};
                              EXTENSION_LOADERS = {".step": tessellate_step, ".stp": tessellate_step} (+ M5's load_mesh_file dispatch);
                              expand_scene(scene, base_dir=None) -> (scene, notes); load_expanded_scene(path_or_dict, base_dir=None) -> (scene, notes)
castplane/io/part21.py        ISO 10303-21 syntax only (stdlib): tokenize(text) -> list[(kind, text)], parse(text) -> {"header", "entities"}
castplane/io/step.py          semantics: StepError, STEP_WARNING_CODES, make_step_warning, DEFAULT_SCENE_TEMPLATE, import_step, expand_step_object,
                              recognise_solid, euler_zyx_deg, to_metres, tessellate_step (optional OCP), mesh_object_from_triangles (adapter to §5.2.1)
castplane/io/cli.py           the one `import` subcommand (§5.0.2): add_import_parser(sub), cmd_import(args); the STEP options live here
tools/make_step_fixtures.py   writes tests/fixtures/step/*.step with OCP (committed output; deterministic header + product names, §5.5.9)
tests/fixtures/step/          cylinder, cylinder_down, cylinder_tilted, sphere, cone, box, frustum (negative), two_solids (multi) .step + README.md
tests/test_step.py            §5.5.10 (every M8 test, including the CLI tests; nothing M8-specific goes into tests/test_cli.py — the `import` regex is M5's, §5.5.8)
docs/STEP.md                  feasibility report (Traditional Chinese; structure in §5.5.12)
```
Core runtime dependency stays numpy only (`part21.py` is stdlib only; `step.py` uses numpy for 3-vectors). New optional
extra in `pyproject.toml`: `step = ["cadquery-ocp>=7.7"]`, on its own line in alphabetical order among the extras (`dev`,
`mesh`, `png`, `step`), used **only** by `tessellate_step` and by `tools/make_step_fixtures.py`. `dev` does not include it
(67 MB wheel, 158 MB installed); OCP tests use `pytest.importorskip("OCP")`. **Public surface [decision]**:
`castplane/io/__init__.py`, `step.py`, `part21.py` and `io/cli.py` each define an explicit `__all__` limited to the §5.5.6
API (`__init__`: `EXPANDERS`, `EXTENSION_LOADERS`, `IMPORT_NOTE_CODES`, `expand_scene`, `load_expanded_scene`,
`load_mesh_file`, `SUPPORTED_EXTENSIONS`; `step`: `StepError`, `STEP_WARNING_CODES`, `DEFAULT_SCENE_TEMPLATE`,
`make_step_warning`, `to_metres`, `import_step`, `expand_step_object`, `recognise_solid`, `euler_zyx_deg`, `tessellate_step`,
`mesh_object_from_triangles`; `part21`: `parse`, `tokenize`, `Part21SyntaxError`; `io.cli`: `add_import_parser`,
`cmd_import`); every helper of §5.5.3–§5.5.5 (`_length_unit`, `_angle_unit`, `_placement`, `_solid_ids`, `_check_assembly`,
`_face_records`, `_recognise_cylinder/_sphere/_cone/_box`, `_compose_transform`) is underscore-prefixed, so
`tests/test_cli.py::test_usage_lists_every_public_function` needs exactly the `__all__` names in `docs/USAGE.md`.

#### 5.5.1 Loader-only object type `step` — validation rows (raised as `SceneError(field, message)` by `expand_step_object`, before the file is opened unless stated)
| field | rule |
| --- | --- |
| `objects[i].type == "step"` | **[decision]** loader-only. `scene.LOADER_TYPES = ("step",)` — **only** `step`; the `mesh` type is a core type in its inline form and a `mesh` carrying `path` without `data` is rejected by its own row (§5.0.1). `scene.validate_object` gets a separate two-line block `if typ in LOADER_TYPES: raise SceneError(f"{field}.type", f"loader object type '{typ}' must be expanded first (castplane.io.expand_scene or 'castplane import')")` placed **before** the existing `if typ not in OBJECT_TYPES` test (so M5's hunk to `OBJECT_TYPES` merges cleanly); the generic "must be one of …" message is kept for unknown types |
| `objects[i].id` | as §2.0 (non-empty string, no `.`); the expanded ids derive from it (§5.5.6) |
| `objects[i].path` | required, non-empty string; resolved against `base_dir` when relative (§5.0.2); an unreadable file raises the `OSError` (CLI exit 1, like an unreadable scene file) |
| `objects[i].solid` | optional; must be an `int` (bools and floats rejected with the `scene._is_number`-style check: `SceneError(objects[i].solid, "must be an integer ≥ 0")`), `≥ 0`, and after the file is parsed `< N` (number of solids counted per §5.5.4) else `SceneError(objects[i].solid, "file has N solid(s)")`; selects one solid |
| `objects[i].fallback` | optional; `"error"` (default) or `"mesh"`; anything else → `SceneError(objects[i].fallback, "must be 'error' or 'mesh'")`. With `"mesh"` an unrecognised solid becomes a `mesh` object through `mesh_object_from_triangles` (§5.5.7) with the note `STEP_SOLID_TESSELLATED`; a missing OCP is then an `ImportError` (exit 3) **[decision, synthesis]** |
| `objects[i].transform` | optional; validated with `scene.validate_transform` (so `scale` is rejected, field `objects[i].transform.scale`); composed with the placement read from the file: `R = R_user · R_step`, `position = R_user · p_step + p_user` (§5.5.5) |
Unknown keys are ignored (§2.0). After expansion the scene contains only §2.0 types; `validate_scene` then applies every
§2.0 rule, including id uniqueness (a clash between an expanded id and another object is reported at the later
`objects[j].id`).

`expand_scene(scene, base_dir=None) -> (scene_out, notes)` behaves as §5.0.2: a new dict; every object whose `type` is a key
of `EXPANDERS` is replaced **in place of its list position** by the objects its expander returns (list order preserved, so
object order in the document is the scene order); every other element — including non-dict entries — is deep-copied
unchanged, and a non-list `objects` (or a non-dict scene) is passed through untouched so that `validate_scene` reports the
proper field path instead of `expand_scene` raising `TypeError`. `notes` is the merged (`errors.merge_warnings`) list of
importer notes (§5.5.6) and is **never** merged into a document's `warnings` **[decision]** (§2.9 is a closed list; importer
notes are about the file, not the geometry). `expand_scene` is idempotent on an already expanded scene.
`load_expanded_scene(path_or_dict, base_dir=None) -> (scene, notes)` reads the JSON with `scene.read_json` (§5.0.1), sets
`base_dir = dirname(path)` when a path is given (else `os.getcwd()` unless `base_dir` is passed), calls `expand_scene` and
then `scene.validate_scene`; it does **not** shadow `castplane.load_scene` (different name, different return type on
purpose).

#### 5.5.2 Part 21 subset (`castplane/io/part21.py`)
- Input: the file read as text, `encoding="utf-8", errors="replace"` (Part 21 is ASCII; non-ASCII can only occur inside
  strings, which the geometry never uses).
- Tokens, in this precedence, as alternatives of **one** regular expression with named groups (`re.X | re.S`), so that
  comments and whitespace are consumed as tokens and a `/*` inside a quoted string is never stripped by a pre-pass:
  `skip = \s+ | /\*.*?\*/` (first; dropped) ; `ref = #\d+` ; `str = '(?:[^']|'')*'` (the `''` escape is unescaped;
  `\X2\…\X0\` sequences are kept verbatim) ; `enum = \.[A-Z0-9_]+\.` ; `real = [+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][+-]?\d+)?` ;
  `name = [A-Z_][A-Z0-9_-]*` (the `-` is needed for `ISO-10303-21` / `END-ISO-10303-21`) ; `punct = [(),;=*$]`. A number
  token containing `.`, `E` or `e` is converted with Python `float()` (correctly rounded, hence deterministic across
  platforms; `-0.` → `-0.0`, which every emitted coordinate later canonicalises with `+ 0.0`), otherwise with `int()`.
  Anything else (e.g. a user-defined entity `!NAME`, a binary `"…"` literal) → `Part21SyntaxError(offset, message)` (a
  `ValueError`), wrapped by `step.py` into `StepError(field, "syntax: … at offset N")`.
- Grammar accepted: `ISO-10303-21; HEADER; <entity>* ENDSEC; DATA; (<id> = <instance> ;)* ENDSEC; END-ISO-10303-21;` where
  `<instance>` is `NAME ( args )` or a **complex entity** `( NAME ( args ) NAME ( args ) … )`. `args` is a comma-separated
  list of values; a value is a ref, string, enum, number, `$` (→ `None`), `*` (→ `None`), a nested list `( … )` (→ Python
  list) or a **typed value** `NAME ( value )` (→ tuple `(NAME, value)`, e.g. `LENGTH_MEASURE(1.E-07)`). Multiple `DATA`
  sections are concatenated; a duplicate instance id → syntax error; a truncated file → syntax error naming the offset of
  the end of input.
- Result: `{"header": {NAME: args, …}, "entities": {"#15": ("MANIFOLD_SOLID_BREP", args), "#114": ("COMPLEX",
  [("LENGTH_UNIT", []), ("NAMED_UNIT", [None]), ("SI_UNIT", [".MILLI.", ".METRE."])]), …}}`. Entity ids keep their `#` string
  form; numeric order is `int(id[1:])`. `parse` does no semantic checks and never needs OCP. Measured on the prototype: the
  cylinder fixture (5.7 KB, 118 entities) parses in ≈ 2 ms.

#### 5.5.3 Units (`step.py`) — one conversion function
- **Length**: the complex entity that holds both `LENGTH_UNIT` and `SI_UNIT(prefix, name)`: `name == .METRE.` and `prefix`
  `None` → `unit = "m"`, `unit_divisor = 1.0`; `prefix == .MILLI.` → `unit = "mm"`, `unit_divisor = 1000.0`. **[decision] The
  only conversion is `to_metres(x, unit_divisor) = float(x) / unit_divisor + 0.0` — a division, never a multiplication by
  `0.001`**, and §5.5.5 uses `to_metres` for every emitted length (there is no "factor"; the first design's `r·f` notation
  and `unit_factor` report key are withdrawn). Why: the IEEE quotient is correctly rounded, so for every millimetre value
  `x` that is **exactly representable as a double** (integers up to 2⁵³, dyadic fractions such as `0.5`, `0.25`) `x / 1000.0`
  is the correctly rounded value of the rational `x/1000`, i.e. exactly the double of the metre literal
  (`300./1000. == 0.3`, `2400./1000. == 2.4`, `-1500./1000. == -1.5`, `0.5/1000. == 0.0005`); multiplication is not
  (`9*0.001 = 0.009000000000000001`, `1001*0.001 = 1.0010000000000001`; 2676 integers in `[−10000, 10000]` differ). The
  guarantee does **not** extend to non-representable decimals: `2.1/1000.0 != 0.0021` (24 % of the tenths in `(0, 10000)`
  miss), so only integer / dyadic mm values are promised bit-exact; everything else is within 1 ulp. Any other prefix, a
  `CONVERSION_BASED_UNIT` used as length unit (inch, foot, …), or two length units with different divisors in one file →
  `StepError(field, "unsupported: length unit …")`. No length unit declared → `unit_divisor = 1000.0` and note
  `STEP_UNIT_ASSUMED_MM` (STEP's conventional default is mm). All coordinates, radii, heights and sizes of §5.5.5 go through
  `to_metres` **after** recognition (recognition works in file units with the tolerances of §5.5.4).
- **Plane angle** (only `CONICAL_SURFACE.semi_angle` uses it, and only in a consistency check): `PLANE_ANGLE_UNIT` +
  `SI_UNIT($, .RADIAN.)` → `angle_factor = 1.0`; `CONVERSION_BASED_UNIT(name, #m)` with `#m =
  PLANE_ANGLE_MEASURE_WITH_UNIT(PLANE_ANGLE_MEASURE(f), #radian_unit)` → `angle_factor = f` (covers `'DEGREE'`,
  f = 0.0174532925199433); none → `1.0` plus note `STEP_ANGLE_UNIT_ASSUMED_RAD`; anything else → `StepError("unsupported:
  plane angle unit …")`.

#### 5.5.4 Topology walk, tolerances
- **Solids**: every `MANIFOLD_SOLID_BREP(name, outer)` in the entity table, in ascending numeric entity id. Nothing else is a
  solid; `BREP_WITH_VOIDS`, `FACETED_BREP`, `SHELL_BASED_SURFACE_MODEL`, `GEOMETRIC_CURVE_SET` etc. are ignored and reported
  in the error when the file has **no** `MANIFOLD_SOLID_BREP`: `StepError(field, "unsupported: no MANIFOLD_SOLID_BREP solid
  (found: FACETED_BREP ×1, …)")`.
- **Assemblies [decision]**: OpenCascade writes *every* multi-solid compound as an assembly
  (`NEXT_ASSEMBLY_USAGE_OCCURRENCE` + `CONTEXT_DEPENDENT_SHAPE_REPRESENTATION` + `ITEM_DEFINED_TRANSFORMATION(name, desc,
  #placement_parent, #placement_child)`; verified: `#142 = ITEM_DEFINED_TRANSFORMATION('', '', #11, #15)` with both
  placements the identity), so assemblies are not rejected outright: each `ITEM_DEFINED_TRANSFORMATION` must map **equal**
  placements (locations within `tol` of §5.5.4, `axis` and `ref_direction` within `tol_dir_step` after normalisation) — the
  identity — and then solid coordinates are taken as absolute. A non-identity transformation or any `MAPPED_ITEM` →
  `StepError(field, "unsupported: assembly transformation #142 is not the identity (single placement only)")`. (Composing a
  chain of placements is out of scope, spec brief §4; it is listed in `docs/STEP.md` as the first follow-up.)
- **Faces**: `CLOSED_SHELL(name, cfs_faces)` → each `ADVANCED_FACE` / `FACE_SURFACE(name, bounds, face_geometry,
  same_sense)`. Bounds: `FACE_BOUND` / `FACE_OUTER_BOUND(name, loop, orientation)`; a loop is `EDGE_LOOP(name,
  oriented_edges)` or `VERTEX_LOOP(name, vertex)` (OCC writes a whole sphere as one face with one vertex loop).
  `ORIENTED_EDGE(name, *, *, edge_element, orientation)` → `EDGE_CURVE(name, start, end, edge_geometry, same_sense)`;
  `start`/`end` are `VERTEX_POINT(name, CARTESIAN_POINT)`; `edge_geometry` is `CIRCLE(name, AXIS2_PLACEMENT_3D, radius)`,
  `LINE(name, CARTESIAN_POINT, VECTOR)`, or `SURFACE_CURVE` / `SEAM_CURVE(name, curve_3d, …)` whose `curve_3d` is read
  instead (OCC writes both for every cap circle / seam). Any other curve type is ignored by the recognisers (they only read
  `CIRCLE` radii). `face_geometry` is one of `PLANE(name, placement)`, `CYLINDRICAL_SURFACE(name, placement, radius)`,
  `SPHERICAL_SURFACE(name, placement, radius)`, `CONICAL_SURFACE(name, placement, radius, semi_angle)`; a solid with any
  other surface (`TOROIDAL_SURFACE`, `B_SPLINE_SURFACE_WITH_KNOTS`, `SURFACE_OF_REVOLUTION`, `SURFACE_OF_LINEAR_EXTRUSION`,
  …) is **unsupported** and the error names it. **Sign-free reading [decision]**: `same_sense`, loop orientations **and the
  sign of a `PLANE` axis** are never read — OCC writes the *same* axis direction for the two opposite faces of a box
  (verified: `#17` and `#137` both `(0.866025403784, 0.5, 0.)`, differing only in `same_sense` `.F.`/`.T.`), so no
  recogniser may depend on it; the recognisers use `|n × a|`, `|n_i × n_j|` and position differences only. The four
  recognisers never need face orientation (a closed solid with the required face signature is the primitive; outward
  normals are implied), which removes the most error-prone part of a B-rep reader.
- **Placement**: `AXIS2_PLACEMENT_3D(name, location, axis | $, ref_direction | $)` → `(o, a, e1, e2)` with `a =
  normalize(axis)` (default `(0,0,1)`), `e1 = normalize(ref − (ref·a)·a)` (default `ref`: the first of `(1,0,0)`, `(0,1,0)`
  with `|ref × a| > tol_dir_step`), `e2 = a × e1`; `|ref × a| ≤ tol_dir_step` for an explicit `ref_direction` →
  `StepError("… degenerate placement #26")`. `(e1, e2, a)` is therefore exactly orthonormal by construction even though STEP
  writers emit only 12–15 significant digits (OCC: 12 for directions, up to 14–15 for coordinates, e.g. `743.46242505348`).
- **Tolerances [decision]**: computed **once per file, in millimetres**, so that a metre file and a millimetre file of the
  same part get the same physical tolerance: `k = 1000.0 if unit == "m" else 1.0` (file units per mm are `1/k`),
  `extent_mm = max(1.0, k · max |coordinate| over every CARTESIAN_POINT of the file)`, `tol = 1e-6 · extent_mm / k` (in file
  units; = 1e-6·extent_mm for a mm file, 1e-9·extent_mm for a metre file), `tol_dir_step = 1e-7` for direction predicates
  (parallel / perpendicular / equal directions). The same `tol` serves the assembly identity check (file level) and every
  recogniser. Rationale: these judge *classification*, not geometry; OCC writes 12 significant digits for directions
  (relative 1e-12), other exporters ≥ 9, so 1e-7 accepts every real exporter while 1e-6·extent (6 µm on a 6 m part) still
  rejects anything that is not the primitive. The geometry itself comes from exact file numbers (radii, vertex points) and
  re-orthonormalised frames, so recognition tolerance never leaks into the emitted scene.

#### 5.5.5 Recognisers (`recognise_solid(entities, solid_ref, unit_divisor, angle_factor, tol) -> object dict | None`) — exact rules
The face-type multiset of the solid selects the rule; every comparison uses §5.5.4 tolerances. Every emitted number is a
Python `float` built as `to_metres(x, unit_divisor)` (lengths) or `float(x) + 0.0` (angles); never a numpy scalar; nothing is
snapped to zero (an angle of `−3e-16°` stays as it is: the expansion is a pure function of the file bytes, and snapping
would be a hidden tolerance).

1. **cylinder** — face types ⊆ {`CYLINDRICAL_SURFACE`, `PLANE`}, ≥ 1 cylindrical face(s) (OCC writes one with a seam; other
   systems split it), all with the same radius (`|Δr| ≤ tol`) and the same axis line (axes parallel within `tol_dir_step`,
   `|(o_j − o_1) × a| ≤ tol`); exactly 2 planar faces whose axes are parallel to the cylinder axis (`|n × a| ≤ tol_dir_step`,
   sign ignored); no other faces. `(o, a, e1, e2)` from the cylindrical face with the lowest entity id, `r` its radius. Cap
   axial positions `t_k = (p_k − o)·a` (`p_k` the plane's location); `h = t_max − t_min`, `h ≤ tol` → unsupported ("zero
   height"). **Up canonicalisation [decision]**: flip `a ← −a`, `e2 ← a × e1`, `t ← −t` when `a_z < −tol_dir_step`, or when
   `|a_z| ≤ tol_dir_step` and `a_x < −tol_dir_step`, or when `|a_z|, |a_x| ≤ tol_dir_step` and `a_y < 0` **strictly**
   (intentionally the only sign test without a tolerance band: at that point `a = ±ŷ` up to 1e-7 and either sign is a
   valid, deterministic choice). A cylinder is symmetric under this flip; the rule makes an imported pillar's `base` its
   bottom, matching the §2.1 anchor convention, and the frame `[e1 e2 a]` stays right-handed. `e1` is the file's
   `ref_direction` (projected), **not** canonicalised: the `buried_cylinder_tilted` acceptance (§5.5.10) proves it
   round-trips into `conics[].circle.e1`; an OCC cylinder written with axis `−z` therefore expands to `rotation_deg
   [0, 0, 180]` (its `ref_direction` is `(−1, 0, −0)`), which is the same solid with the cap-circle parameter shifted by π
   (verified: only `circle.e1/e2` and `theta` leaves of the document differ; every named point and polygon is equal).
   `base = o + t_min·a`. Object: `{"type": "cylinder", "radius": to_metres(r), "height": to_metres(h), "transform":
   {"position": to_metres(base), "rotation_deg": euler_zyx_deg([e1 e2 a])}}`.
2. **sphere** — every face `SPHERICAL_SURFACE` (≥ 1; loops may be `VERTEX_LOOP`s), all with the same centre
   (`|c_j − c_1| ≤ tol`) and radius. A closed solid made only of pieces of one sphere is the whole sphere, so no loop check
   is needed. **Identity frame [decision]** (changed after review): a sphere has no intrinsic frame and the §2.6
   light-along-z fallback of an inline sphere uses the rotated local axes, so the expansion uses the **identity** frame
   regardless of the file's placement: `position = c − r·ẑ` (anchor at the bottom, §2.1), `rotation_deg = [0.0, 0.0, 0.0]`.
   (The first design kept the file frame, which would have anchored a sphere written with axis `−z` at its top.) Object:
   `{"type": "sphere", "radius": to_metres(r), "transform": {"position": to_metres(c − r·ẑ), "rotation_deg": [0.0, 0.0, 0.0]}}`.
3. **cone** — face types ⊆ {`CONICAL_SURFACE`, `PLANE`}, ≥ 1 conical face(s) with pairwise parallel axes, equal
   `semi_angle` (`|Δ| ≤ tol_dir_step`, after the §5.5.3 angle factor) and equal apex points `o_j − (radius_j /
   tan(semi_j))·a_j` (within `tol`); exactly **one** planar face with `|n × a| ≤ tol_dir_step` (a frustum has two planes
   and is unsupported — our `cone` type has no frustum). `(o, a_s, e1, e2)`, `radius_s`, `semi` from the conical face with
   the lowest entity id; `0 < |semi| < π/2 − tol_dir_step` else unsupported. **Apex from topology [decision]**: among the
   vertex points of the conical faces, those with `|(v − p_cap)·a_s| > tol` must all coincide within `tol` → apex `V` (none
   → unsupported "cone without an apex vertex"). Reason: the semi-angle is written with 12 digits (`0.321750554397`), so
   `radius / tan(semi)` reproduces a 1200 mm apex only to 1.4e-9 mm (OCC's own reader has the same error:
   `gp_Cone.Apex()` of the fixture is `(0, 0, 1.43e-9)`), whereas the vertex point is written exactly
   (`(-2.E+03, 5.E+03, 1.2E+03)`); with the vertex the cone fixture expands bit-exactly. `a = a_s · sign((V − p_cap)·a_s)`
   (the file's axis may point either way: OCC writes `(−0., −0., −1.)` for the fixture), `h = (V − p_cap)·a`, `b = V − h·a`,
   `e2 = a × e1` (re-derived so the frame stays right-handed when `a` was flipped). `r` = the radius of the `CIRCLE` edge(s)
   of the planar face's loop (all equal within `tol`; no `CIRCLE` edge → unsupported). Consistency:
   `| r − | radius_s + ((b − o)·a_s)·tan(semi) | | ≤ tol` and `h > tol`, else unsupported ("inconsistent cone"). Object:
   `{"type": "cone", "radius": to_metres(r), "height": to_metres(h), "transform": {"position": to_metres(b), "rotation_deg":
   euler_zyx_deg([e1 e2 a])}}`.
4. **box** (sign-free, rewritten after review) — exactly 6 `PLANE` faces. Group the faces, in ascending entity id, by their
   axis direction **up to sign** (`|n_i × n_j| ≤ tol_dir_step`); there must be exactly 3 groups of exactly 2 faces; within a
   group the two locations must differ along the direction (`|(p_2 − p_1)·n| > tol`); the 3 group directions must be
   mutually perpendicular (`|n_i·n_j| ≤ tol_dir_step`); the distinct vertex points of all faces (deduplicated within `tol`)
   must number exactly 8. (Closedness of the shell then forces a cuboid; no further geometric check is needed.)
   `canon(n, order)` makes positive the first component in `order` whose magnitude exceeds `tol_dir_step`. `z` = the group
   direction with the largest `|n·ẑ|` (ties within `tol_dir_step` → the group containing the lowest face entity id),
   `canon(·, (z, x, y))`; `x` = of the remaining two, the one with the largest `|n·x̂|` (same tie rule), `canon(·, (x, y, z))`,
   then `x ← normalize(x − (x·z)·z)`; `y = z × x`; `R = [x y z]`. `local = V · R` (8×3), `size = max − min` per column (each
   `> tol`), `position = R · (mid_x, mid_y, min_z)` (centre of the bottom face, §2.1). Object: `{"type": "box", "size":
   to_metres(size), "transform": {"position": to_metres(position), "rotation_deg": euler_zyx_deg(R)}}`. Verified on the
   committed fixture construction (OCC 8.0): `size = [1.00000000000002, 0.8000000000003888, 0.6]`,
   `position = [2.0000000000000004, 4.0, 0.0]`, `rotation_deg = [0.0, 0.0, 30.000000000012566]`; an axis-aligned OCC box
   yields `rotation_deg = [0, 0, 0]` and `size = [dx, dy, dz]` exactly.
5. Otherwise → `None`; `import_step` then raises `StepError(field, "#15: unsupported solid: faces {CONICAL_SURFACE: 1,
   PLANE: 2} (supported: cylinder, sphere, cone, box)")` (the face counts are printed sorted by surface name) — unless
   `fallback == "mesh"`, in which case the solid is tessellated (§5.5.7).

**Euler extraction [decision]** `euler_zyx_deg(R) -> [rx, ry, rz]` (degrees, the inverse of `transform.euler_zyx_matrix`,
`R = Rz·Ry·Rx`, so `R[2,0] = −sin ry`, `R[2,1] = cos ry·sin rx`, `R[2,2] = cos ry·cos rx`, `R[0,0] = cos rz·cos ry`,
`R[1,0] = sin rz·cos ry`). **First** every one of the nine entries is canonicalised with `float(·) + 0.0` (OCC writes `-0.`
literally — `DIRECTION('',(1.,0.,-0.))`, `(-0.,-0.,-1.)` — and `e2 = a × e1` / the up-flip manufacture further signed
zeros; `atan2(−0.0, −1)` would return −π). Then `cy = hypot(R[0,0], R[1,0])`; `ry = atan2(−R[2,0], cy)` (the `cos ry ≥ 0`
branch, `ry ∈ [−90°, 90°]`); if `cy > 1e-12`: `rz = atan2(R[1,0], R[0,0])`, `rx = atan2(R[2,1], R[2,2])`; else (gimbal lock,
`sy = −R[2,0] = ±1`): `rz = 0`, `rx = atan2(sy·R[0,1], R[1,1])`. Angles are `math.degrees(·) + 0.0`, in `(−180°, 180°]`
(with the canonicalisation `atan2(+0.0, −1) = +π`, so exactly `180.0`, never `−180.0`; verified on
`[[-1,-0.,0],[-0.,-1,0],[0,0,1]]` → `[0.0, 0.0, 180.0]`). Round trip: `euler_zyx_matrix(euler_zyx_deg(R))` reproduces `R` to
≈ 1e-16; the libm last-bit dependence of `atan2` makes the expanded scene of a *rotated* solid deterministic **per build**
(the same rule as the conformance expected files, §4; e.g. `Rz(30°)` round-trips to `29.999999999999996`), while unrotated
solids expand bit-exactly on every platform. (The M5 glTF importer's `euler_zyx` of §5.2.8 is the same decomposition;
one implementation serves both.)

#### 5.5.6 Importer API, report, ids, notes, errors
```python
castplane.io.step.import_step(path, *, fallback="error", solid=None, obj_id=None, transform=None, field="step") -> report
report = {"path": str, "schema": str | None,            # first FILE_SCHEMA entry, e.g. 'AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'
          "unit": "mm" | "m", "unit_divisor": 1000.0 | 1.0, "angle_factor": float, "tol": float (file units, §5.5.4),
          "solids": [{"entity": "#15", "kind": "cylinder"|"sphere"|"cone"|"box"|"mesh", "faces": {"CYLINDRICAL_SURFACE": 1, "PLANE": 2},
                      "object": {...}}],                 # entity-id order ("mesh" = the §5.5.7 fallback)
          "objects": [...],                              # the solids' objects in the same order (what expand_step_object returns)
          "notes": [{"code", "ids", "message"}]}         # merged with errors.merge_warnings
castplane.io.step.expand_step_object(obj, field, base_dir) -> (objects, notes)      # the EXPANDERS["step"] entry
castplane.io.step.to_metres(x, unit_divisor) -> float                                # x / unit_divisor + 0.0 (scalars, lists and arrays → list of float)
castplane.io.step.make_step_warning(code, ids=(), message=None) -> dict              # like errors.make_warning, against STEP_WARNING_CODES (a note)
castplane.io.expand_scene(scene, base_dir=None) -> (scene, notes)
castplane.io.load_expanded_scene(path_or_dict, base_dir=None) -> (scene, notes)      # expand_scene + scene.validate_scene (the CLI's loader)
castplane.io.step.recognise_solid(entities, solid_ref, unit_divisor, angle_factor, tol) -> dict | None
castplane.io.step.euler_zyx_deg(R) -> [rx, ry, rz]
castplane.io.step.tessellate_step(path, *, deflection_mm=None) -> {"vertices": [[x,y,z]...] (m), "faces": [[i,j,k]...], "cascade_unit": "MM"|"M"}  # OCP
castplane.io.step.mesh_object_from_triangles(obj_id, tri, transform) -> dict          # adapter to the §5.2.1 inline mesh object
castplane.io.part21.parse(text) -> {"header": {...}, "entities": {...}} ; tokenize(text) -> list[(kind, text)]
castplane.io.cli.add_import_parser(sub) ; cmd_import(args) -> int
```
- **Ids [decision]**: when the file holds one solid, or `solid` selects one, the object id is `obj_id` (the scene object's
  `id`; CLI `--id`, default: the file stem with every character outside `[A-Za-z0-9_-]` replaced by `_`); with `n > 1`
  solids and no `solid`, the ids are `<id>_<k>`, `k = 0 … n−1` in entity-id order (no `.`, so the §5.0.4 point-name grammar
  is safe). STEP product names are never used as ids (OCC writes `'Open CASCADE STEP translator 8.0 5'`).
- **Importer notes** (`step.STEP_WARNING_CODES`, the STEP sub-list of `castplane.io.IMPORT_NOTE_CODES`, §5.0.2; same
  `{code, ids, message}` shape, `ids` = `[entity id]` or `[]`), built with `make_step_warning` because
  `errors.make_warning` raises `ValueError` for codes outside `errors.WARNING_CODES`: `STEP_UNIT_ASSUMED_MM` (no length
  unit declared), `STEP_ANGLE_UNIT_ASSUMED_RAD` (no plane-angle unit declared), `STEP_SOLID_TESSELLATED` (ids `["#15"]`; the
  §5.5.7 fallback). `errors.merge_warnings` is applied to note lists only; they are returned by the importer and printed
  by the CLI as `note: …`; they never enter `doc["warnings"]`.
- **Errors**: `class StepError(SceneError)` with the extra attribute `entity` (`"#15"` or `None`); `field` is the JSON path
  of the step object's `path` (`objects[2].path`) when expanding a scene and the string given as `field` (default `"step"`)
  for a standalone `import_step`; `message` starts with the entity id when one applies (`"#15: unsupported solid: …"`) or
  with `syntax:` / `unsupported:` otherwise. Every failure of §5.5.2–§5.5.5 is a `StepError` (CLI exit 2); only a missing
  OCP in §5.5.7 is an `ImportError` (exit 3); file access errors are `OSError` (exit 1).

#### 5.5.7 Tessellation (optional extra `step`; the fallback produces the M5 inline `mesh` object)
`tessellate_step(path, deflection_mm=None)` uses, literally (attribute names verified on cadquery-ocp 8.0.1.1.0; they also
exist in 7.7): `reader = STEPControl_Reader()`; `reader.ReadFile(path) == IFSelect_RetDone` (else `StepError("unsupported:
OCP cannot read …")`); `reader.TransferRoots()`; `shape = reader.OneShape()`; `cascade_unit =
Interface_Static.CVal_s("xstep.cascade.unit")` read **after** the reader has been constructed (it is `''` before any reader
exists and `'MM'` by default afterwards; OCC converts the file into this unit on read; `"MM"` → `÷ 1000.0`, `"M"` → `÷ 1.0`,
anything else → `StepError`); bounding box `Bnd_Box` via `BRepBndLib.Add_s(shape, box)` and `box.CornerMin()` /
`box.CornerMax()` (OCP 8 no longer unpacks `Get()`); **[decision]** `deflection_mm = max(0.01, 1e-3 · diagonal of the
bounding box in cascade units)`; `BRepMesh_IncrementalMesh(shape, deflection_mm, False, 0.3, False)` (`isInParallel =
False`: results were identical with `True` on the fixtures, but `False` removes the only threading in the path);
`TopExp_Explorer(shape, TopAbs_FACE)`; per face `face = TopoDS.Face(explorer.Current())` (**not** `TopoDS.Face_s`, which
does not exist), `tri = BRep_Tool.Triangulation_s(face, loc)` (`getattr(BRep_Tool, "Triangulation_s",
BRep_Tool.Triangulation)`), nodes `tri.Node(i)` (1-based) transformed by `loc.Transformation()`, triangles
`tri.Triangle(i).Get()` (1-based) re-based to the running vertex offset, winding reversed when `face.Orientation() ==
TopAbs_REVERSED`; node blocks are concatenated **without welding** (OCC triangulates each face separately; measured with the
rule above on OCC 8.0: cylinder 170 nodes / 164 triangles, frustum 400 / 598, box 24 / 12, sphere 1447 / 2836 — the first
design's "310 nodes / 304 triangles" was measured with a different deflection and is withdrawn). Welding, edge building and
manifold checking are M5's preprocessing pipeline (§5.2.3). **Fallback wiring [decision, synthesis]**: with
`fallback="mesh"` an unrecognised solid becomes `mesh_object_from_triangles(obj_id, tri, transform)` = `{"id": obj_id,
"type": "mesh", "data": {"vertices": <metres, unwelded>, "faces": <0-based triangles, outward winding>, "smooth_groups":
[0] * len(faces)}, "transform": transform}` (the §5.2.1 inline form; `weld_tolerance`, `smooth_angle_deg`, `scale` take the
M5 defaults, so M5's weld at 1e-6 m closes the per-face seams) with the note `STEP_SOLID_TESSELLATED` (ids `["#15"]`).
Determinism of tessellated objects: per OCP build (the same status as PNG per cairosvg); such objects never appear in
conformance cases. A `mesh` object whose `path` ends in `.step` / `.stp` (case-insensitive) is tessellated directly through
`EXTENSION_LOADERS[".step"] = tessellate_step` by `expand_mesh_object` (§5.0.2) — **no** analytic recognition; `type: "step"`
is the only way to get the analytic path. Missing OCP → `ImportError("the tessellation fallback needs cadquery-ocp: pip
install 'castplane[step]'")` (exit 3).

#### 5.5.8 CLI (the common syntax and output rules are §5.0.2)
```
castplane import FILE.step [-o OUT.json] [--into SCENE] [--id ID] [--solid K] [--fallback error|mesh] [-q]
```
The subcommand lives in `castplane/io/cli.py` (`add_import_parser(sub)`, `cmd_import(args)`, shared with M5's mesh
options); `castplane/cli.py` changes by one import line, one `add_import_parser(sub)` call in `build_parser`, and the four
scene-loading call sites (`_run`, `cmd_validate`, `cmd_stages`, `cmd_info`) switching from `load_scene(path)` to
`load_expanded_scene(path)` and printing the importer notes with `_print_warnings`-style lines (`note:` prefix) — these
`castplane/cli.py` edits are **M5's** (it merges first, §5.0.2); M8 touches `castplane/cli.py` not at all; `StepError`
is a `SceneError`, so the existing exit-code mapping applies. `cmd_import` reads `FILE` with `import_step`, assembles a
complete scene — `--into SCENE` is itself loaded with `load_expanded_scene(SCENE)` (so `step` objects already in it are
expanded relative to `dirname(SCENE)`), its **raw** blocks `version`, `units`, `up`, `lights`, `receivers`, `camera`,
`output` and any unknown keys (e.g. `description`) are copied verbatim from the raw file and the imported objects are
**appended** to its raw `objects` (expanded in place); without `--into` the §5.0.2 defaults apply (a STEP file carries no
camera or light, so the M5 bbox camera and default light are used with their notes; the constant
`step.DEFAULT_SCENE_TEMPLATE` — exactly the `version`/`units`/`up`/`lights`/`receivers`/`camera`/`output` blocks of
`examples/basic.json`, i.e. the spec §4 lamp, ground, 35 mm camera, canvas `[273, 182]` — remains the API constant the M8
tests render into) **[decision, synthesis]** — runs `validate_scene` on the assembled scene **as a check only** (so the
result is guaranteed renderable; a validation failure is reported with its field path, exit 2) and writes the **raw
assembled scene** (not the validated dict with defaults filled, which would turn `[0, 0, 30]` into `[0.0, 0.0, 30.0]` and
drop unknown keys) as `json.dumps(scene, indent=1, sort_keys=True, ensure_ascii=False) + "\n"` to `OUT.json` (or stdout
without `-o`). Importer notes go to stderr as `note: <CODE> [ids]: message` (suppressed by `-q`); the written path is
printed like `render` does. Exit codes as §1: 0; 1 unreadable STEP / scene, unwritable output; 2 `StepError`, `SceneError`,
usage; 3 `--fallback mesh` without OCP. `render`, `validate`, `stages`, `info` therefore accept scene files holding
`{"type": "step", "path": "parts/pillar.step"}` objects (paths relative to the scene file); their importer notes are printed
with the document warnings (never written into the JSON output); `validate` counts objects after expansion.
`tests/test_cli.py::documented_commands` extends its regex to `(render|validate|info|stages|import)` so the documented
`castplane import tests/fixtures/step/cylinder.step …` lines are parsed and the fixture path is checked to exist (the regex extension is made by M5, which merges first and
documents `castplane import` for meshes; M8 adds nothing to `tests/test_cli.py`).

#### 5.5.9 Fixtures (`tests/fixtures/step/`) and generator (`tools/make_step_fixtures.py`)
The generator needs OCP (`pip install cadquery-ocp`), writes with `STEPControl_Writer` after
`Interface_Static.SetCVal_s("write.step.schema", "AP214")`, **always writes the whole set in the table order below within one
process** (`--out DIR`; `--check` regenerates into a temporary directory in the same way and compares bytes), then rewrites
the file so that regeneration is byte-reproducible for a given OCC build: `FILE_NAME` time stamp → `'2026-10-06T00:00:00'`,
author `('castplane')`, organisation `('cast-space-to-plane')`; **every `PRODUCT` name and id** `'Open CASCADE STEP translator
8.0 <counter>'` (a per-process transfer counter: `8.0 1` … `8.0 6`, and `8.0 7`, `8.0 7.1`, `8.0 7.2` inside `two_solids`) →
`'castplane <fixture>'` for the root and `'castplane <fixture>.<k>'` for the k-th child (same text in both the name and the id
field); everything else is left as OCC wrote it. `tests/fixtures/step/README.md` records the OCP / OCC version ("Open
CASCADE STEP processor 8.0", cadquery-ocp 8.0.1.1.0), the parameters below, and the observation that OCC writes directions
with 12 significant digits and coordinates with up to 14–15 (e.g. `743.46242505348`, `2.775557561563E-17`). Outputs are
committed; `tests/test_step.py` checks the set is < 100 KB (measured: 2–17 KB each). Parameters are in **mm** integers so
that the expanded values are exact (§5.5.3):
| fixture | OCP construction | expands to (m) |
| --- | --- | --- |
| `cylinder.step` | `BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(-1500, 6000, 0), gp_Dir(0,0,1)), 300, 2400)` | the spec §4 `pillar`: `cylinder r 0.3 h 2.4 at (-1.5, 6, 0)`, `rotation_deg [0,0,0]` |
| `cylinder_down.step` | `MakeCylinder(gp_Ax2(gp_Pnt(-1500, 6000, 2400), gp_Dir(0,0,-1)), 300, 2400)` (built from the **top** point so that the solid occupies `z ∈ [0, 2400]`; OCC writes `ref_direction (-1., 0., -0.)`) | the same solid as `pillar` with the frame turned by 180°: `r 0.3 h 2.4 at (-1.5, 6, 0)`, `rotation_deg [0, 0, 180]` exactly (verified) |
| `cylinder_tilted.step` | `MakeCylinder(gp_Ax2(gp_Pnt(0, 5000, -400), gp_Dir(*R[:,2]), gp_Dir(*R[:,0])), 500, 1600)`, `R = Rz(20°)·Rx(30°)` | the `buried_cylinder_tilted` drum: `r 0.5 h 1.6 at (0, 5, -0.4)`, `rotation_deg ≈ [30, 0, 20]` |
| `sphere.step` | `BRepPrimAPI_MakeSphere(gp_Pnt(1000, 2000, 500), 500)` | `sphere r 0.5 at (1, 2, 0)`, `rotation_deg [0,0,0]` |
| `cone.step` | `BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(-2000, 5000, 0), gp_Dir(0,0,1)), 400, 0, 1200)` | `cone r 0.4 h 1.2 at (-2, 5, 0)` |
| `box.step` | `BRepPrimAPI_MakeBox(gp_Pnt(-500, -400, 0), 1000, 800, 600)` then `BRepBuilderAPI_Transform` with `T(2000, 4000, 0) · Rz(30°)` | the spec §4 `crate`: `box [1, 0.8, 0.6] at (2, 4, 0)`, `rotation_deg ≈ [0, 0, 30]` |
| `frustum.step` (negative) | `MakeCone(gp_Ax2(origin, +z), 400, 200, 1200)` | `StepError` "#15: unsupported solid: faces {CONICAL_SURFACE: 1, PLANE: 2}"; with `fallback: "mesh"` a `mesh` object (§5.5.7) |
| `two_solids.step` (multi) | compound of the cylinder and the sphere above (OCC writes it as an identity assembly) | ids `<id>_0` (cylinder, entity #37), `<id>_1` (sphere, #154) |

#### 5.5.10 Testing contract (`tests/test_step.py`; spec §10 M8 acceptance)
- **Acceptance case (hand-computable)**: expanding `{"id": "pillar", "type": "step", "path": "cylinder.step"}` must give
  **exactly** (`==` on the dict) `{"id": "pillar", "type": "cylinder", "radius": 0.3, "height": 2.4, "transform": {"position":
  [-1.5, 6.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]}}`; the scene `examples/basic.json` with its `pillar` replaced by that
  step object must render (through `castplane.io.load_expanded_scene` + `render`) to a document whose `geometry_json.dumps`
  is **byte-equal** to the in-process render of the inline `examples/basic.json`, and it must pass
  `tests.test_conformance.compare_documents` against `expected/example_basic.json` (byte-equal on the recorded NumPy build;
  the prototype measured byte equality). The hand numbers of the pillar (closed form, no castplane code): with
  `b = (−1.5, 6, 0)`, `l = (0, 3, 3.5)`, `r = 0.3`, `h = 2.4`: `q_⊥ = (1.5, −3, 0)`, `d = √11.25 = 3.3541019662496847`,
  `θ_l = atan2(−3, 1.5) = −63.43494882292201°`, `α = acos(0.3/d) = 84.86845205068873°`, generators at `θ_l − α =
  −148.30340087361074°` and `θ_l + α = 21.43350322776672°`; `pillar.g0.base = (−1.7552526894158411, 5.8423736552920795, 0)`,
  `pillar.g1.base = (−1.220747310584159, 6.10962634470792, 0)` (each its own shadow); with `S = l + (P − l)·l_z/(l_z − P_z) =
  l + (P − l)·35/11`: `pillar.g0.top.shadow.lamp = (−5.584894920868585, 12.043916175929343, 0)`,
  `pillar.g1.top.shadow.lamp = (−3.884195988222324, 12.894265642252474, 0)`; the test asserts these `world` values within
  1e-9 m on the document rendered from the STEP scene (the expected file carries the same digits; both reviews recomputed
  them independently).
- **Unit arithmetic** (inline Part-21 text, no fixture): a cylinder with `radius 9.`, `height 1001.`, location `(0.5, 0, 0)`
  in a mm file expands to exactly `radius == 0.009`, `height == 1.001`, `position[0] == 0.0005` (all fail under
  multiplication by 0.001); the same values in a `SI_UNIT($, .METRE.)` file expand unchanged with `unit == "m"`.
- `sphere.step`, `cone.step`: exact dict equality with `{"type": "sphere", "radius": 0.5, "transform": {"position": [1.0, 2.0,
  0.0], "rotation_deg": [0.0, 0.0, 0.0]}}` and `{"type": "cone", "radius": 0.4, "height": 1.2, "transform": {"position": [-2.0,
  5.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]}}` (the apex-from-vertex rule makes the height exact); rendering each in the
  `DEFAULT_SCENE_TEMPLATE` must be byte-equal to rendering the inline object. The sphere text-edited to axis `(0,0,-1)`
  expands to the **same** dict (identity frame).
- `box.step`: `size` within 1e-9 of `[1.0, 0.8, 0.6]`, `position` within 1e-9 of `[2.0, 4.0, 0.0]`, `rotation_deg` within
  1e-9° of `[0, 0, 30]` (prototype on OCC 8.0: `[1.00000000000002, 0.8000000000003888, 0.6]`, `[2.0000000000000004, 4.0, 0.0]`,
  `30.000000000012566`); `examples/basic.json` with `crate` from STEP passes `compare_documents` against
  `expected/example_basic.json` (measured max image deviation ≈ 3e-11 mm; spec §7.5 tolerance 1e-6 mm).
- `cylinder_down.step`: `rotation_deg == [0.0, 0.0, 180.0]` and `position == [-1.5, 6.0, 0.0]` exactly, `radius 0.3`, `height
  2.4`; the document rendered from `examples/basic.json` with the pillar from this file has every named `points[*].world`
  within 1e-9 m and every `shadows[].polygons` / `edges[].segment` / `construction.segments` within 1e-6 mm of the inline
  render, and the only leaves allowed to differ are `conics[].circle.e1`, `circle.e2`, `arc.theta0/theta1` and
  `arcs[].theta` (not dict equality). The **bit-equal** canonicalisation case edits **only** the `CYLINDRICAL_SURFACE`
  placement's axis `DIRECTION` of `cylinder.step` (entity `#34` in the OCC file) to `(0.,0.,-1.)`, leaving `ref_direction
  (1.,0.,-0.)` and both `PLANE` placements untouched: result `==` the `cylinder.step` dict.
- `cylinder_tilted.step`: `rotation_deg` within 1e-9° of `[30, 0, 20]`, `position` exact `[0.0, 5.0, -0.4]`, `height` within
  1e-9 of 1.6; `cases/buried_cylinder_tilted.json` with its drum from STEP passes `compare_documents` against
  `expected/buried_cylinder_tilted.json` (prototype: 0 differences) — this also proves `e1` (`ref_direction`) round-trips,
  which the `conics[].circle.e1` / `arc.theta*` fields require.
- `frustum.step`: `StepError` with `entity == "#15"`, message containing `unsupported solid` and `CONICAL_SURFACE: 1,
  PLANE: 2`; `fallback="mesh"` with OCP present (`importorskip("OCP")`): the expansion yields one `mesh` object whose `data`
  passes `validate_scene` and renders (M5 pipeline: `MESH_*` warnings allowed), with the note `STEP_SOLID_TESSELLATED`;
  without OCP `fallback="mesh"` raises `ImportError` naming `castplane[step]` (CLI exit 3); `tessellate_step(frustum)` returns
  a result with every triangle index in `[0, len(vertices))`, `len(faces) ≥ 100`, every face contributing ≥ 1 triangle (3
  faces), `cascade_unit == "MM"`, and the cylinder fixture ≥ 100 vertices (structural assertions only; the exact counts
  170 / 164 and 400 / 598 are recorded in `docs/STEP.md`, not asserted).
- `two_solids.step`: ids `part_0`, `part_1` (file stem `two_solids` → `--id part` given), kinds cylinder / sphere, `part_0`
  equal to the `cylinder.step` object, `solid=1` → single object `part` (sphere), `solid=2` → `SceneError(field="objects[0].solid")`,
  `solid=True` / `solid=1.0` → `SceneError(objects[0].solid)`; the identity `ITEM_DEFINED_TRANSFORMATION`s are accepted.
- Inline-string cases (no fixture): minimal valid file without a unit context → `STEP_UNIT_ASSUMED_MM`;
  `CONVERSION_BASED_UNIT('INCH', …)` and `SI_UNIT(.CENTI., .METRE.)` as length unit → `StepError` "unsupported: length unit";
  a non-identity `ITEM_DEFINED_TRANSFORMATION` (child placement translated by (1,0,0)) → `StepError` "not the identity";
  `MAPPED_ITEM` → `StepError`; truncated file / `!USER_ENTITY` / duplicate `#5` / unterminated string → `StepError` starting
  with `syntax:` and naming an offset; a `/* comment */` between tokens is skipped while `'/*'` inside a string is kept;
  `DEGREE` angle unit on a cone whose `semi_angle = 18.434948822922` → same object as the radian file; part21 round trips
  of `'it''s'` → `it's`, `$`, `*`, `LENGTH_MEASURE(1.E-07)` → `("LENGTH_MEASURE", 1e-07)`, `-0.` → `-0.0`, the complex unit
  entity, multi-line records; metre-file tolerance: a 2 m cylinder written in metres with a cap plane tilted by `2e-9` rad
  is still recognised (tol 2e-9 m = 2e-6 mm·extent) while `2e-6` rad is rejected, mirroring the mm file.
- Recogniser negatives built by editing the cylinder fixture text: a third planar face (keyway) → unsupported; cap plane
  tilted (`DIRECTION (0.001, 0, 1)`) → unsupported; two cylindrical faces with different radii → unsupported; sphere split
  into two hemispherical faces → sphere; `TOROIDAL_SURFACE` → unsupported naming it; no `MANIFOLD_SOLID_BREP` → "no
  MANIFOLD_SOLID_BREP solid (found: …)"; box with 6 planes whose two `+x` faces are written with opposite axis signs
  (text-edited) → the same box (sign-free rule); box with 5 planes + 1 cylinder → unsupported.
- `euler_zyx_deg`: for 200 seeded random `rotation_deg` triples with `ry ∈ (−89°, 89°)`,
  `euler_zyx_matrix(euler_zyx_deg(euler_zyx_matrix(a)))` equals `euler_zyx_matrix(a)` within 1e-12; gimbal-lock inputs
  (`ry = ±90°`) reproduce the matrix within 1e-12 with `rz == 0`; exact ±180° frames with `−0.0` entries
  (`[[-1,-0.,0],[-0.,-1,0],[0,0,1]]` and its `+0.0` twin) both give `[0.0, 0.0, 180.0]`; every output lies in `(−180, 180]`.
- Validation: `validate_scene` on a scene holding a `step` object → `SceneError(field="objects[0].type")` with the §5.5.1
  message; `transform.scale` → `objects[0].transform.scale`; `fallback: "x"` → `objects[0].fallback`; `path` missing →
  `objects[0].path`; unreadable path → `OSError`; a user `transform` composes: step cylinder + `rotation_deg [0,0,90]`,
  `position [1,0,0]` renders within 1e-9 m on world points of the inline cylinder at `R = Rz(90)`, `p = Rz(90)·(−1.5, 6, 0) +
  (1, 0, 0) = (−5, −1.5, 0)` (`Rz(90)` has a `6e-17` entry, so not byte-equal); `expand_scene` passes a non-list `objects`
  through and `validate_scene` then reports `objects`.
- Determinism: `expand_scene` twice → equal `json.dumps`; `castplane import` run twice → identical output bytes.
- CLI (in `tests/test_step.py`): `import cylinder.step -o s.json` → exit 0, `validate s.json` ok, object id = sanitised file
  stem; `import cylinder.step --into examples/basic.json --id post` appends (and keeps the raw `[0, 0, 30]` of the crate and
  unknown keys) and its light / camera blocks are byte-equal to `examples/basic.json`'s; `--into` a scene that itself holds
  a `step` object expands it; stdout mode; `--solid 1` on `two_solids.step`; `-q`; `frustum.step` → exit 2 with `error: step:
  #15: unsupported solid …`; `--fallback mesh` → exit 3 without OCP, exit 0 with it; a mesh option (`--weld`) on a `.step`
  file → exit 2 (usage); missing file → exit 1; `render` on a scene file containing a relative `step` path writes the same
  `basic.json` bytes as rendering `examples/basic.json`; `info` lists the expanded types.
- Performance (spec §8): the core is untouched, so `benchmarks/bench.py --gate full` is unchanged;
  `test_step_import_is_not_slow` requires the **minimum of 3 timed runs** of `import_step` on each fixture to be < 500 ms (a
  flakiness-safe bound; the measured ≈ 2–3 ms per fixture and the informational row "STEP import, 200 cylinders /
  1.25 MB: 0.63 s (prototype; not gated)" go to `benchmarks/README.md`).
- **Conformance set**: unchanged (no case, no expected file; §5.0.8). `tests/conformance/README.md` gets one sentence:
  cases never contain loader-only objects (`step`, `mesh` with `path`); they are post-expansion scenes.

#### 5.5.11 Shortcuts considered **[decision]**
Acceptable (pure, deterministic per build, loader-level): (a) classification by face-type signature plus the closed-solid
argument instead of validating every edge loop, and ignoring every orientation sign in the file; (b) the Euler round trip
`R → rotation_deg → R` (≈ 1e-16, acceptance tolerance 1e-9); (c) OCP tessellation for unrecognised solids, as an
expansion-time loader producing inline data (wired through M5's `mesh` object); (d) assuming mm when no unit is declared,
with a note; (e) accepting identity-only assemblies; (f) canonicalising the sphere to the identity frame and the cylinder
axis to "up" while keeping the file's `ref_direction`.
Not acceptable: (g) resolving `path` inside stage A or at render time (the document would no longer be derivable from the
scene JSON, breaking the M7 portability rule, and the output would depend on the file system and on the OCP build); (h)
OCP / `BRepAdaptor_Surface` as the *primary* parser (hard dependency on a 67 MB wheel the core must not have,
OCC-version-dependent numerics — its apex reconstruction is 1.4e-9 mm off where the Part-21 vertex is exact); (i) a
`rotation_matrix` / `frame` key on scene objects to avoid Euler extraction (new §2.0 row, TS-port change, and it would let
non-orthonormal frames into the core); (j) keeping file units (mm) in the scene (`units` must be `"m"`); (k) importer notes
in `doc["warnings"]` (closed §2.9 list); (l) snapping near-zero angles or sizes (hidden tolerance in a pure function); (m)
multiplying by `0.001` anywhere.

#### 5.5.12 `docs/STEP.md` — required structure (Traditional Chinese)
1 目的與結論（建議先寫）；2 STEP 對解析曲面的表達（AP203 / AP214 / AP242 共用的幾何實體、Part 21 語法、以 OCC 實際輸出為例的實體圖：
`MANIFOLD_SOLID_BREP → CLOSED_SHELL → ADVANCED_FACE → {PLANE, CYLINDRICAL_SURFACE, SPHERICAL_SURFACE, CONICAL_SURFACE} +
AXIS2_PLACEMENT_3D`、`EDGE_LOOP → ORIENTED_EDGE → EDGE_CURVE → {CIRCLE, LINE, SEAM_CURVE}`、`VERTEX_LOOP`、單位 complex entity、
方向 12 位／座標最多 14–15 位有效數字的觀察、**方塊對面共用同一法線方向只靠 `same_sense` 區分**的觀察）；3 路線 (a) OCP / pythonOCC
（`STEPControl_Reader` → `TransferRoots` → `OneShape` → `TopExp_Explorer(TopAbs_FACE)` → `BRepAdaptor_Surface.GetType()` →
`gp_Cylinder / gp_Sphere / gp_Cone / gp_Pln`；安裝現實：pythonocc-core 只有 conda，cadquery-ocp 可 pip，wheel 67 MB、安裝後 158 MB、
LGPL-2.1；確定性只到 OCC 版本；頂點重建誤差 1.4e-9 mm；OCP 8 的 API 名稱差異 `TopoDS.Face`、`Bnd_Box.CornerMin/Max`）；4 路線 (b)
無相依 Part-21 子集解析器（§5.5.2–§5.5.5 的規則、量測：夾具 ≈ 2–3 ms、200 個實體 1.25 MB 0.63 s、約 700 行）；5 建議與工作量（b 為原型：
解析器 1 天、辨識器 1.5 天、CLI 與展開 0.5 天、夾具與測試 1 天、文件 0.5 天；a 僅作網格退路與夾具產生器：0.5 天）；6 範圍外與錯誤／備註清單
（B-spline、環面、掃掠面、截頭圓錐、組件變換、mm/m 以外單位、`BREP_WITH_VOIDS`；`StepError` 與三個備註碼）；7 與 M5 的介面與相依（規格 §10
列 M5 為 M8 前置：網格退路經 M5 的內嵌 `data` 網格物件；`type: step` 走解析辨識；`type: mesh` + `.step` 直接走網格退路；`EXPANDERS` /
`EXTENSION_LOADERS` 登錄表；網格化實測數字 170/164、400/598）；8 驗收案例（§5.5.10 的圓柱位元相同、手算數字）；9 風險（exporter 精度、
分割面、單位宣告缺失、OCC 版本漂移、PRODUCT 名稱的程序計數器）。

### Implementation notes
- **[decision, implementation] (M8 part 1) Re-measured on the committed fixtures (cadquery-ocp 8.0.1.1.0, OCC 8.0).**
  Confirmed exactly as quoted above: cylinder fixture 118 entities / 5 684 bytes, its `CYLINDRICAL_SURFACE` axis is `#34`;
  `two_solids` solids `#37` / `#154` and `#142 = ITEM_DEFINED_TRANSFORMATION('','',#11,#15)` (identity); box faces `#17` /
  `#137` both `(0.866025403784, 0.5, 0.)`; box expansion `size = [1.00000000000002, 0.8000000000003888, 0.6]`,
  `position = [2.0000000000000004, 4.0, 0.0]`, `rotation_deg = [0.0, 0.0, 30.000000000012566]`; cone semi-angle
  `0.321750554397`, axis `(-0., -0., -1.)`; `cylinder_down` `ref_direction (-1., 0., -0.)` → `[0.0, 0.0, 180.0]`;
  tessellation 170 / 164 (cylinder), 400 / 598 (frustum), 24 / 12 (box), 1447 / 2836 (sphere). Sizes 2–17 KB, set 56 KB.
  **Corrected**: (a) §5.5.9's PRODUCT counters are `8.0 1` … `8.0 7` for the seven single-solid fixtures written before
  `two_solids`, and `8.0 8`, `8.0 8.1`, `8.0 8.2` inside it (not `1 … 6`, `7`, `7.1`, `7.2`; the normalisation is a
  regular expression over any counter, so the output is the same); (b) the "`2.775557561563E-17`" example is a
  **direction** component (`cylinder_tilted`, 13 significant digits), not a coordinate; directions carry 12–13
  significant digits, coordinates up to 14 (`743.46242505348`); (c) `cylinder_tilted` expands to `height
  1.600000000000126`, `rotation_deg [30.000000000017515, 1.3772205761362216e-15, 20.000000000016044]` (within the 1e-9
  of §5.5.10), `position [0.0, 5.0, -0.4]` exactly.
- **[decision, implementation] (M8 part 1) §5.5.10 metre-tolerance case.** For a 2 m part `extent_mm = 2000`, so
  `tol = 1e-6 · 2000 / 1000 = 2e-6 m` (= 2e-3 mm in the mm file), not "2e-9 m". A tilted cap plane is judged by the
  unit-free direction predicate (`|n × a| ≤ tol_dir_step = 1e-7`), so a 2e-9 rad tilt is accepted and 2e-6 rad rejected in
  both the metre and the millimetre file; the test additionally exercises `tol` itself with a second cylindrical face
  whose radius differs by 1e-6 m (accepted) / 1e-5 m (rejected), in both units.
- **[decision, implementation] (M8 part 1) Which unit entities count (§5.5.3).** The length / plane-angle units read are
  those listed by a `GLOBAL_UNIT_ASSIGNED_CONTEXT` (every entity when no context lists any). Needed because a `DEGREE`
  file necessarily also holds the radian `SI_UNIT` referenced by its `PLANE_ANGLE_MEASURE_WITH_UNIT`; scanning every
  entity would see two plane-angle units with different factors. The conversion measure must reference a radian unit,
  else `StepError("unsupported: plane angle unit …")`.
- **[decision, implementation] (M8 part 1) Messages.** A rule-specific reason is appended to the §5.5.5 message after
  `; ` (`#15: unsupported solid: faces {CONICAL_SURFACE: 1, PLANE: 2} (supported: cylinder, sphere, cone, box); cone:
  2 planar faces (a frustum is not a cone)`), so the contract text stays a prefix. Degenerate placements read
  `unsupported: degenerate placement #32 (ref_direction parallel to axis)` with `entity = "#32"`; a dangling or
  mistyped reference is `#n: expected DIRECTION, found …`. An `ITEM_DEFINED_TRANSFORMATION` is the identity when the
  locations agree within `tol` and both the normalised axes and the projected `ref_direction`s within `tol_dir_step`.
  In a standalone `import_step(field=F)` a bad `solid` / `fallback` / `transform` is reported at `F` with a trailing
  `.path` replaced by `.solid` / `.fallback` / `.transform` (`objects[i].solid` when expanding; `step.solid` for the
  default `field="step"`). A `POLY_LOOP` or a nested `ORIENTED_EDGE` makes the solid unrecognised (so `fallback="mesh"`
  still applies) instead of raising.
- **[decision, implementation] (M8 part 1, review fix) Cone semi-angle check.** When the conical surface's placement lies
  in the base plane (OCC always writes it so), `(b − o)·a_s = 0` and the §5.5.5 consistency test reduces to
  `r = radius_s`, so it cannot see a wrong semi-angle, and (because of its inner `| … |`) not a surface axis pointing at
  the apex either. **Added** after it: the surface radius must vanish at the apex vertex,
  `| radius_s + ((V − o)·a_s)·tan(semi) | ≤ tol`, else unsupported ("inconsistent cone (the surface radius does not
  vanish at the apex vertex)"). ISO 10303-42 puts the apex at `o − (radius_s / tan(semi))·a_s`, so this holds for every
  valid file whatever the placement (OCC's 12-digit semi-angle leaves a residual of ≈ 4.8e-10 mm on `cone.step`, whose `tol` is 5e-3 mm).
  A degree value read as radians (`18.43…` rad) is still rejected earlier by the range check
  (`0 < |semi| < π/2 − tol_dir_step`).
- **[decision, implementation] (M8 part 1) Mesh fallback in multi-solid files.** `fallback="mesh"` on an unrecognised
  solid `k` of a file with several solids tessellates only the `k`-th `TopAbs_SOLID` of the shape (explorer order;
  verified equal to the entity order on `two_solids`: 170 / 164 and 1447 / 2836, identical to the single fixtures), with
  the deflection rule applied to that solid's bounding box; a single-solid file is tessellated whole, exactly as
  `tessellate_step`. Recognised solids never import OCP.
- **[decision, implementation] (M8 part 1) Gimbal-lock branch.** §5.5.5 says the M5 `gltf.euler_zyx` is "the same
  decomposition"; it is, except at gimbal lock, where `gltf.euler_zyx` sets `rx = 0` (and `rz = atan2(−R01, R11)`) while
  `euler_zyx_deg` sets `rz = 0` (and `rx = atan2(sy·R01, R11)`). Both reproduce `R`; `gltf.py` (M5's file) is unchanged.
  The product is canonicalised too, `atan2(sy·R01 + 0.0, R11)`: with `sy = −1` and `R01 = +0.0` the product is `−0.0`
  and `atan2(−0.0, −1) = −π` would give `−180.0` (review fix; e.g. a cylinder along world `+x` with `ref_direction
  (0, 0, 1)` is `[180.0, -90.0, 0.0]`).
- **[decision, implementation] (M8 part 1, review fix) Mesh fallback `transform` (§5.5.7).** `import_step` passes the
  caller's **raw** `transform` block (deep-copied; validated but not normalised, so `{"position": [1, 0, 0]}` stays
  integer and gains no `rotation_deg`), as §5.5.8 requires for the written scene; the key is **omitted** when
  `transform` is `None` (`validate_scene` would reject `"transform": null`).
- **[decision, implementation] (M8 part 1, review fix) `cylinder_down` render leaves (§5.5.10).** Measured with every
  numeric leaf compared at 1e-9: exactly 64 leaves differ (the count PLAN-v2 quotes), all in conic dicts of `outlines[]`,
  `shadows[]` **and `form_shadow[].terminator[]`**: `circle.e1`, `circle.e2` (negated), `arc.theta0/theta1`,
  `arcs[].theta` **and `visible[][]`** (each shifted by π mod 2π, the same intervals in the flipped parameterisation).
  The allowed list of §5.5.10 is read with `visible` added and as applying to every conic dict, not only those under a
  `conics` key; every point, polygon, segment and edge agrees within 1e-9.
- **[decision, implementation] (M8 part 1) Vector arithmetic.** `step.py` does its 3-vector arithmetic in plain Python
  floats in a fixed order (`_dot`, `_cross`, …; numpy only for `to_metres` of arrays, `euler_zyx_deg` input and the
  user-transform composition), so recognition and the emitted numbers do not depend on a BLAS build.
- **[decision, implementation] (M8 part 2) Registry and the `.step` mesh path (§5.0.2, §5.5.0, §5.5.7).**
  `EXPANDERS["step"]`, `EXTENSION_LOADERS` and `IMPORT_NOTE_CODES.update(step.STEP_WARNING_CODES)` are appended
  hunks of `castplane/io/__init__.py`; `EXTENSION_LOADERS` is consulted by M5's `load_mesh_file` (its per-call
  parse cache) **before** the trimesh fallback, so `expand_mesh_object` needs no change and
  `load_mesh_file("part.step")` returns the same raw form `{vertices (m), faces, smooth_groups: [0]*n}` as
  `mesh_object_from_triangles(...)["data"]`. A `mesh` object with a `.step` path gets **no** importer note
  (`STEP_SOLID_TESSELLATED` belongs to the `type: "step"` fallback, whose ids are entity ids); a `StepError` of
  `tessellate_step` is re-raised by `_parse_file` without its standalone `step` field, so M5's re-raise gives
  `SceneError(objects[i].path, "unsupported: …")`, the bare loader message of §5.0.2 (review fix);
  `node` on a `.step` mesh is M5's `objects[i].node` error. `scene.LOADER_TYPES` sits directly above
  `validate_object` (its test is the first statement after the `type` lookup, before the `OBJECT_TYPES` test).
- **[decision, implementation] (M8 part 2) `castplane import` of a STEP file (§5.5.8).** The written objects are
  the expanded primitives (an unrecognised solid with `--fallback mesh`: the inline `mesh`), never a `step`
  reference; the importer notes go into `meta.import_notes` like every import (§5.0.2; §5.5.8 does not repeat it).
  A missing FILE is checked (exit 1) before the extension dispatch. The mixed-family usage error is a
  `SceneError` at the option (`error: --weld: --weld is a mesh option; FILE is a STEP file …`, exit 2), the same
  mechanism M5 uses for `--up` on glTF; `--solid` is `type=int` (a non-integer is an argparse usage error, exit 2;
  a negative or too large K is `SceneError("step.solid", …)`). **Added**: with `--into SCENE`, the ids that
  SCENE's own `step` objects expand to (`part_0`, …) are reserved like SCENE's raw ids, so an imported object is
  de-duplicated against them (`part_0_2`) instead of failing validation at `objects[j].id`; an explicit `--id`
  equal to one of them is the usual `SceneError("--id")`. To get those ids before `_dedupe`, M5's line
  `expanded, into_notes = expand_scene(base_scene, scene_dir)` was **moved** from the `if base_scene is not None:`
  block into the `if args.into:` block of `cmd_import` (same call, same arguments; the one relocation of existing
  M5 code in M8).
- **[decision, implementation] (M8 part 2) "every face contributes ≥ 1 triangle" (§5.5.10).** Tested without a
  per-face API: the node blocks are unwelded, so each face's triangulation is its own connected component; the
  frustum's triangles form exactly 3 components and OCP's face explorer finds 3 faces. `tessellate_step` keeps the
  contract's return keys.
- **[decision, implementation] (M8 part 2) Extras order and the test environments.** `step` is placed after `png`
  in `pyproject.toml`; the existing `dev` line stays last (PLAN rule: no moving of existing lines), so the extras
  read `mesh`, `png`, `step`, `dev`. The container's system Python has cadquery-ocp 8.0.1.1.0, so the OCP tests
  run in the full suite; the absent path was run with a `ModuleNotFoundError` stub for `OCP` first on
  `PYTHONPATH` (`tests/test_step.py`, `test_cli.py`, `test_loaders.py`: 186 passed, the 6 OCP tests skipped; CLI
  `--fallback mesh` exit 3). The scratch OCP venv has no pytest, so it was not used.
- **[decision, implementation] (M8 part 2) Measurements.** Fixture `import_step` 0.45–4.1 ms (min of 5; table in
  `benchmarks/README.md`); a 200-cylinder OCC assembly (`tools/make_step_fixtures.py --bench-solids 200`, 1 238 126 bytes, 24 220 entities) 0.31–0.40 s (min of 3,
  three runs), not the prototype's 0.63 s; Part 21 parsing is ≈ 85 % of the time. `part21.py` is 202 lines and
  `step.py` 842 (the §5.5.12 "≈ 700 lines" estimate is exceeded by the error paths and the fallback).
- **[decision, implementation] (M8 part 2, review fixes) Tessellation guards and `--id` collisions (§5.5.7,
  §5.2.8 (4)).** OCC's `ReadFile` returns `IFSelect_RetDone` for a file it cannot transfer (a syntactically broken
  file, an empty `DATA` section); `TransferRoots()` then returns 0 and `OneShape()` is null, and `CornerMin()` of the
  void box would raise OCP's `Standard_ConstructionError`. `_tessellate` therefore also raises `StepError("unsupported:
  OCP cannot read … (no transferable shape)")` when no root transfers or the shape is null, and `StepError("unsupported:
  OCP finds no geometry in …")` for a void bounding box (exit 2 at `objects[i].path` / `step`, never a traceback).
  OCC's console printer is left as is (it writes `**** ERR StepFile …` to stdout only for such broken files).
  `castplane import --id ID` on a multi-solid STEP file checks every derived `<ID>_<k>` against the taken ids and
  raises `SceneError("--id")` on a clash instead of renaming it (§5.2.8 (4): an explicit `--id` is never renamed).
  With `--into SCENE`, a present non-list `objects` is `SceneError("objects", "must be a non-empty list")` (the
  `validate_scene` message) before the import is assembled, not `objects[0]`.
