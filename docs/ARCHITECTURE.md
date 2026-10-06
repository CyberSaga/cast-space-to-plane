# Architecture contract (v1, M0–M3)

This document is the binding contract between the spec (`docs/spec/spec-v0.1.md`,
sections referenced as §N) and the code. Everything here is normative for the
implementation; where the spec leaves a choice open, the choice is recorded here
and must not be re-decided elsewhere. Decisions that override spec wording are marked **[decision]**.

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
tests/
  reference/raycast.py      independent ray-casting reference (shares NO code with castplane except reading scene dicts)
  reference/raster.py       nonzero-winding polygon rasterizer for IoU
  reference/random_scenes.py random scene generator (seeded)
  test_*.py                 unit / invariant / analytic / degenerate / property / raycast tests
  conformance/cases/*.json  inputs ; conformance/expected/*.json outputs (§6.2 format) ; test_conformance.py ; README.md ; CHANGELOG.md
tools/regen_conformance.py  regenerates expected files; requires --reason, appends a versioned entry to CHANGELOG.md
benchmarks/bench.py         §8 performance targets (benchmarks/README.md records the measured status)
examples/*.json             example scenes (the §4 scene is examples/basic.json); examples/README.md
docs/                       spec + this document + user docs: README.md (root), docs/USAGE.md (CLI + API reference),
                            docs/DECISIONS.md (the [decision] list in Traditional Chinese), docs/images/
```

Package name on PyPI/import: `castplane`. CLI entry point: `castplane`.
Python ≥ 3.10. Core runtime dependency: numpy only. Optional extras:
`png` → cairosvg; `dev` → pytest, hypothesis, pillow, cairosvg.

## 2. Conventions (normative)

### 2.0 Validation (`scene.py`) — every rule raises `SceneError(field=<json path>, message)`
| field | rule |
| --- | --- |
| `version` | must be `"0.1"` |
| `units` / `up` | must be `"m"` / `"z"` (defaults if absent) |
| `objects` | non-empty list; ids unique, non-empty strings without `.` |
| `objects[i].type` | one of `box, cylinder, sphere, cone, prism` |
| `objects[i].size` (box) | 3 positive numbers |
| `radius`, `height` | positive numbers (cylinder, cone: both; sphere: radius only) |
| `objects[i].polygon` (prism) | ≥ 3 vertices `[x,y]`, non-collinear, simple (no self-intersection); clockwise input is reversed silently |
| `objects[i].transform` | optional; `position` 3 numbers (default `[0,0,0]`); `rotation_deg` 3 numbers (default `[0,0,0]`); `scale` forbidden |
| `lights` | list of length exactly 1 (v1); ids unique, non-empty strings without `.` (like object ids: `.` is the separator of the §3.1 point-name grammar, `L.<light>`, `<obj>.s<k>.<light>`) |
| `lights[i].type` | `point` (needs `position`, 3 numbers) or `directional` (needs `direction`, 3 numbers, \|d\| = 1 ± 1e-9, points **towards** the light) |
| `receivers` | list of length exactly 1 (v1); `type == "plane"`; `normal` must be `[0,0,1]` and `offset` must be `0` (v1 ground only, §1); \|normal\| = 1 ± 1e-9 |
| `camera` | `position` 3 numbers; exactly one of `target` (3 numbers, ≠ position) or `yaw_deg`+`pitch_deg`; `roll_deg` default 0; `focal_length_mm > 0`; `frame_mm` 2 positive; `shift_mm` default `[0,0]`; `near_m > 0` default 0.05 |
| `output.canvas_mm` | 2 positive numbers; \|canvas_w/canvas_h − frame_w/frame_h\| ≤ 1e-9 |

**[decision]** The spec's own §4 example (`canvas_mm = [257, 182]` with `frame_mm = [36, 24]`) violates the spec's
own aspect rule (1.412 ≠ 1.5) and is rejected. `examples/basic.json` therefore uses `[273, 182]` (3:2, same height);
users who want JIS B5 paper should set `frame_mm` to a matching aspect (e.g. `[36, 25.5]`) or the canvas to 3:2.
| `output.layers` | **non-empty** subset of the six ids of §2.10 (default when absent: all six, in table order); an empty list is rejected (field `output.layers`), exactly as the CLI rejects an empty `--layers` |
| `output.png_dpi` | positive number, default 300 |

Unknown keys are ignored. `load_scene` returns a new plain dict with all defaults filled in.

### 2.1 Coordinates and units
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

### 2.3 Light, plane projection, feet (§5.1–5.3) — use these exact function names
- `light_vector(light) -> L` : point → `(x,y,z,1)`; directional → `(dx,dy,dz,0)`.
- `lit(n_f, p, L) -> bool` : `n_f·(l − w·p) > tol_lit`; the band `|…| ≤ tol_lit` is "parallel" → not lit and
  warning `FACE_PARALLEL_TO_LIGHT` (§5.7 row 6).
- `shadow_matrix(pi, L) -> M` : `M = (πᵀL)·I₄ − L·πᵀ` ; `S = M·P`.
- `foot(pi, X) -> Q` : `Q = (n·n)·X − (n·x + w·d)·(n,0)`; works for `L` too (gives `F`).
- Light side: if `πᵀL ≤ tol` for a point light → `LIGHT_BELOW_RECEIVER`, no shadows for that light (outlines
  and construction rays omitted, `shadows` entries have empty outlines). For a directional light `|n·l| ≤ tol_dir`
  → `DIRECTIONAL_HORIZONTAL` (no shadows, `F` at infinity and `shadow_vp` on the horizon is still reported);
  `n·l < −tol_dir` → `LIGHT_BELOW_RECEIVER`.
- With canonical inputs `w_S = πᵀL·w_P − w_L·πᵀP` (for the ground: `l_z − p_z` for a point light, `l_z` for a
  directional one). `w_S ≤ tol` ⇒ vertex not below the light (§5.7 row 4) → `VERTEX_NOT_BELOW_LIGHT`
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

### 2.5 Shadow outlines of polyhedra (§5.1, §5.7)
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
  (§5.7 row 6) and the ordinary path applies.

### 2.6 Curved primitives (§5.6)
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
- Caps of cylinders / cones are faces for §5.7 row 6: `|n·(l − w·p)| ≤ tol_lit` for the base (normal `−a`) or the
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

### 2.7 Construction (§5.5)
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

### 2.8 Numerics (§5.8)
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

### 2.10 SVG layers (§6.1) — exact ids, order (bottom → top) and default styles (lengths in mm)
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

## 4. Testing contract (§7)
- `tests/test_invariants.py` covers all six §7.1 rows with the stated tolerances, with two recorded exceptions:
  (i) the endpoints of the **clipped construction-ray segments** (rows 1–4) are compared with
  `1e-6 mm × max(1, max |defining image coordinate| in mm)` (`P'`, `S'`, `Q'`, `L'`, `F'`), because the clipped
  endpoint inherits the conditioning of the rectangle clip of a segment defined by points up to a few metres of
  canvas away (measured worst case 2e-6 mm at a 2.2 m scale); every point, edge, polygon, `L'`, `F'` and horizon
  comparison stays at 1e-6 mm; (ii) `tests/test_property.py` compares the (nearly) picture-plane-parallel light
  family (`forward·d` down to 1e-7, `L'` at ~1e9 mm) with a relative 1e-8. Row 4 (rigid equivariance) uses
  the symmetry group of the ground: rotations about +Z and translations in XY applied to objects, light and
  camera (position + target, roll unchanged; a second variant uses the yaw/pitch form with `yaw += angle`).
  Row 5 per §2.1 (positive scalars on inputs; either sign on sign-free outputs). **Limitation**: the scene document
  only carries canonical inputs (finite positions, unit directions, `w = 1`), so row 5 cannot be exercised through
  `render`; it is tested at the helper level (`shadow_matrix`, `foot`, `project`, `self_check`, `conic_entry`,
  `curved.silhouette` / `shadow_outline` with scaled `L`, `π`, `P`, `M`), which is where homogeneous vectors exist.
- `tests/test_analytic.py` covers §7.2 bullets 1, 2 and 4 plus the roll test vector of §2.2 and the box `h/(h−1)`
  case; `tests/test_curved.py` covers the §7.2 sphere-ellipse bullet (closed form `a = r/sin φ`, `b = r`) and the
  §4 pillar/lamp tangent-generator boundaries (`θ_l = −63.43°`, boundaries `−148.30°` and `21.43°`).
- `tests/test_degenerate.py` has at least one test per §5.7 row (six rows) asserting warning codes and finite output.
- `tests/test_raycast.py` (§7.3): seeded random scenes (1–10 primitives, incl. concave prisms and a case with the
  light foot inside a concavity), grid sampling on the ground, IoU ≥ 0.99.
- `tests/test_property.py` (§7.4): hypothesis strategies for scenes/cameras incl. degenerate distributions
  (light behind camera, light direction parallel to the picture plane, vertices above the light).
- `tests/conformance/` (§7.5): `cases/*.json` (spec §4 scenes + a `description` key) and `expected/*.json`
  (`geometry_json.dumps` of `render(...)["geometry"]`), compared by `tests/test_conformance.py`: every image
  coordinate / drawable within 1e-6 mm (absolute), every other number within 1e-9 relative (absolute floor 1e-9),
  every non-number exactly, warning **code sets** equal (and the `(code, ids)` sets). The set (currently v2, see
  `tests/conformance/CHANGELOG.md`; "v1" elsewhere names the M3 deliverable) holds 34 cases: the four §7.2
  analytic cases, every §5.7 row (+ the undefined-`F`/`L'`, light-below-receiver, light-inside-object and cap-at-light-height
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
