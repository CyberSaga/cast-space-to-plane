# Architecture contract (v1, M0–M3)

This document is the binding contract between the spec (`docs/spec/spec-v0.1.md`,
sections referenced as §N) and the code. Everything here is normative for the
implementation; where the spec leaves a choice open, the choice is recorded here
and must not be re-decided elsewhere.

## 1. Package layout

```
castplane/                  pure library, depends only on numpy (stdlib otherwise)
  __init__.py               public API re-exports + __version__
  errors.py                 SceneError (input errors; carries `field` path) ; warning codes + make_warning()
  homogeneous.py            4-vector / 3-vector helpers: normalize_max, cross3, meet/join of 2D lines, tolerance
  scene.py                  load_scene / validate_scene (JSON -> validated plain dict), defaults, camera forms
  transform.py              euler_zyx_matrix(rotation_deg), apply_transform
  mesh.py                   internal mesh representation + builders for polyhedral primitives (box, prism)
  primitives.py             build_object(obj_dict) -> Object record (mesh + analytic params for curved types)
  light.py                  light_vector(light) -> L (4,), lit(face_normal, p, L), silhouette_edges, silhouette_loops
  shadow.py                 shadow_matrix(plane, L) -> M (4x4), foot(plane, X), shadow of polyhedra (loops incl. unbounded)
  conics.py                 3x3 conic math: circle_matrix, embed_circle (E 4x3), transform_conic, classify, ellipse_params, sample_conic, arc helpers
  curved.py                 sphere / cylinder / cone: silhouette w.r.t. an arbitrary homogeneous L (light OR camera), terminator, shadow conics
  camera.py                 camera_matrix(cam, canvas) -> {K,R,t,P(3x4),C, forward, near_functional}, project, clip_segment_near, clip_polygon_near, horizon, vanishing_point
  construction.py           L', F', Q' points, construction rays L'P' and F'Q', self-check intersection S'
  pipeline.py               stage A shadow_geometry(scene) ; stage B project_scene(scene, A, camera=None) ; stage C compose(...) ; render(scene)
  output/__init__.py
  output/geometry_json.py   §6.2 JSON geometry document (deterministic, sorted keys, fixed float formatting)
  output/svg.py             §6.1 layered SVG written with stdlib string building (NO svgwrite dependency)
  output/png.py             §6.3 rasterize via cairosvg (optional extra), resvg fallback if present on PATH
  cli.py                    `castplane` CLI (argparse): render / validate / stages
tests/
  reference/raycast.py      independent ray-casting reference (shares NO code with castplane except reading scene dicts)
  reference/raster.py       nonzero-winding polygon rasterizer for IoU
  reference/random_scenes.py random scene generator (seeded)
  test_*.py                 unit / invariant / analytic / degenerate / property / raycast tests
  conformance/cases/*.json  inputs ; conformance/expected/*.json outputs (§6.2 format) ; test_conformance.py ; README.md
benchmarks/bench.py         §8 performance targets
examples/*.json             example scenes (the §4 scene is examples/basic.json)
docs/                       spec + this document + user docs
```

Package name on PyPI/import: `castplane`. CLI entry point: `castplane`.
Python ≥ 3.10. Core runtime dependency: numpy only. Optional extras:
`png` → cairosvg; `dev` → pytest, hypothesis, pillow.

## 2. Conventions (normative)

### 2.1 Coordinates and units
- World: right-handed, Z up, metres. Ground receiver is `z = 0` → π = (0,0,1,0).
- Object anchor = centre of the **base** (bottom face / base circle); an object resting on the
  ground has `position[2] == 0`.
- `rotation_deg = [rx, ry, rz]`: Euler angles applied in **Z–Y–X order**, i.e.
  `R = Rz(rz) · Ry(ry) · Rx(rx)` applied to local coordinates (`world = R·local + position`).
  Local axes before rotation: box `size=[sx,sy,sz]` spans `[-sx/2,sx/2]×[-sy/2,sy/2]×[0,sz]`;
  cylinder/cone/sphere axis = local +Z; sphere centre at local `(0,0,r)`; prism polygon in local XY
  (counter-clockwise when viewed from +Z; if the input is clockwise, reverse it silently), extruded `[0,height]`.
- Homogeneous 4-vectors `X=(x,y,z,w)`; `w=0` = point at infinity (direction). Planes `π=(n,d)` with `n·x + d = 0`.
- Picture (image) plane coordinates `(u,v)` in **mm**, `u` right, `v` up, **origin at the frame centre**.
  The principal point sits at `(u0,v0) = shift_mm · s` where `s = canvas_mm[0]/frame_mm[0]`.
  (Spec §2 says "origin at the principal point" and §5.4 puts `(u0,v0)` inside K; these only agree
  when shift is 0. We follow the K formula literally and draw the principal point marker at `(u0,v0)`.)
- Canvas: picture coordinates are already in canvas mm (frame is scaled by `s` so that the frame
  fills the canvas). SVG mapping: `x_svg = u + W/2`, `y_svg = H/2 − v`, `viewBox="0 0 W H"`,
  `width="Wmm" height="Hmm"`.

### 2.2 Camera (§5.4)
- `forward = normalize(target − position)`; `right = normalize(forward × up_world)` with
  `up_world=(0,0,1)` (if |forward × up| < eps use up_world=(0,1,0) and warn `CAMERA_LOOKING_ALONG_UP`);
  `up = right × forward`; then roll rotates `right`/`up` about `forward` by `roll_deg`
  (positive = counter-clockwise as seen by the viewer, i.e. rotating the picture CCW).
- yaw/pitch/roll form: `yaw_deg` about +Z (0 = looking along +Y, positive turns left/CCW seen from above),
  `pitch_deg` positive = looking up, then `roll_deg` as above. Exactly one of {target, yaw/pitch} must be given.
- Rows of `R` are `(right, up, forward)`; `t = −R·position`. `[R|t]` is 3×4. Depth of a point is the 3rd
  component of `[R|t]·X` (camera-space z, positive in front). `det R = −1` on purpose, so that
  `u` is right, `v` is up and depth is positive forward; nobody may "fix" this.
- `K = [[f·s, 0, u0],[0, f·s, v0],[0,0,1]]` with `f = focal_length_mm`, `s` and `(u0,v0)` from 2.1.
- `P = K·[R|t]` (3×4). `x̃ = P·X`, `(u,v) = (x̃1/x̃3, x̃2/x̃3)`. `x̃3` equals the depth for `w=1` points.
- Near-plane clipping is done **before division** on the 4-D homogeneous input with the linear functional
  `ν(X) = forward·(x − C·w) − near·w ≥ 0` (for `w=1` this is `depth ≥ near`; for `w=0` directions it is
  `forward·d ≥ 0`). Segments and polygons are clipped by linear interpolation of homogeneous coordinates
  (Sutherland–Hodgman for polygons). Division by `x̃3` happens last. Points with `ν<0` and no
  partner are "behind camera" and produce warning `POINT_BEHIND_CAMERA` (per object, deduplicated).
- Horizon: image line of the receiver's line at infinity = join of the images of two independent
  directions in the plane; stored as a 2D homogeneous line `(a,b,c)` normalised by max component and
  as `v_mm` (its `v` at `u=0`) when not vertical. Vanishing points: `P·(d,0)` for `d ∈ {x,y,z}` and for
  each object's local axes are NOT required; JSON lists `x`, `y`, `z` (each `[u,v]` or `null` if at infinity).

### 2.3 Light, plane projection, feet (§5.1–5.3) — use these exact function names
- `light_vector(light) -> L` : point → `(x,y,z,1)`; directional → `(dx,dy,dz,0)` (direction **towards** the light, unit length validated).
- `lit(n_f, p, L) -> bool` : `n_f·(l − w·p) > tol` (equality → not lit; §5.7).
- `shadow_matrix(pi, L) -> M` : `M = (πᵀL)·I₄ − L·πᵀ` ; `S = M·P`.
- `foot(pi, X) -> Q` : `Q = (n·n)·X − (n·x + w·d)·(n,0)`; works for `L` too (gives `F`).
- Shadow w: `w_S ≤ tol` ⇒ vertex not below the light (§5.7 row 4) → warning `VERTEX_NOT_BELOW_LIGHT`,
  and the shadow outline becomes unbounded (see 2.5).

### 2.4 Mesh representation (also the M5 future mesh format)
```
vertices : (n,3) float64 world coords
edges    : (m,2) int  vertex indices, each edge once, i<j
faces    : list of int lists (CCW seen from outside), planar
face_normals : (k,3) outward unit normals
edge_faces : (m,2) int  the two faces adjacent to each edge (closed manifold ⇒ always 2)
vertex_names : ["v0", "v1", ...]   (names are "<object id>.v<k>")
```
Builders: `box_mesh(size)`, `prism_mesh(polygon, height)`; cylinder/cone/sphere also produce a mesh
(caps as n-gons / lateral quads, sphere as UV-sphere) ONLY for the ray-cast-independent extras like
bounding boxes and the M5-shaped representation; their shadows and outlines are computed analytically
(§5.6), never from that mesh. Curved objects carry `analytic = {kind, centre/base, axis, radius, height, ...}` in world coords.

### 2.5 Shadow outlines of polyhedra (§5.1, §5.7)
- Silhouette edges: edges whose two adjacent faces have different `lit`. `silhouette_loops` walks
  them into closed loops oriented with the **lit face on the left** when seen from the light.
- Each loop → list of homogeneous shadow points `S_i = M·P_i`. Edges whose both endpoints have
  `w_S ≤ tol` are dropped. An edge from `w>0` to `w≤0` is replaced by a **direction** vertex
  `(D,0)` where `D` is the spatial part of the point on the edge where `w` crosses 0 (sign chosen so
  the direction points away from the finite end). Consecutive direction vertices are kept as-is
  (they define the "edge at infinity"). The result is an oriented homogeneous polygon in the ground
  plane; `unbounded=true` when it contains any `w=0` vertex.
- For drawing, that homogeneous polygon goes through: camera near clipping (2.2) → division →
  2D clipping against the **extended canvas rectangle** (canvas grown by 25 % on each side).
  Bounded outlines are only near-clipped (no 2D clipping needed; SVG handles overflow).
- Fill rule for cast shadows is `nonzero` (needed for concave prisms).

### 2.6 Curved primitives (§5.6)
- Circle in its own plane: `C = diag(1,1,−ρ²)` in local coordinates `(x,y,1)`; embedding
  `E = [e1 e2 c ; 0 0 1]` (4×3) with `e1,e2` an orthonormal basis of the plane and `c` the centre.
- Any 3×3 projective map `H` of the circle gives conic `C' = H⁻ᵀ C H⁻¹`. Ground shadow conic uses
  `H = P·M·E`; image of a circle (outline / terminator / end caps) uses `H = P·E`. Conic matrices are
  normalised by their max-|entry| (made +1) before output.
- The **same** silhouette routine serves the light and the camera: `curved.silhouette(obj, L)` with `L`
  the light vector OR the camera position `(C,1)`. Camera outline = that silhouette; terminator = the
  light silhouette (drawn in the image, not on the ground); cast shadow = the light silhouette mapped by `M`.
- Sphere: silhouette circle centre `c + (r²/|v|²)·v`, radius `r·√(1 − r²/|v|²)`, normal `v/|v|`
  with `v = l − c` (point) ; directional: great circle, normal `l`. Light inside the sphere (`|v| ≤ r`) →
  warning `LIGHT_INSIDE_OBJECT`, no shadow.
- Cylinder (base `b`, axis `a`, radius `r`, height `h`): light projected onto the base plane along the axis:
  `l_p = l − ((l − w·b)·a)·a` (for `w=0`, `l_p = l − (l·a)a` is a direction). Lit angular interval of the
  lateral surface: centred on `θ_l = atan2(l_p·e2, l_p·e1)` with half-width `α = acos(r/d)` for a point
  light (`d = |l_p − b|`; `d ≤ r` ⇒ nothing lit), `α = π/2` for directional (`|l_p| = 0` ⇒ nothing lit).
  Generators at `θ_l ± α` are both the terminator and the silhouette ("tangent generators").
  Caps: top normal `+a`, base normal `−a`, each tested with `lit`. Silhouette arcs: parts of the cap
  circles where cap-lit ≠ lateral-lit. Loop = base arc + generator + top arc + generator (or just a full
  circle when the lateral surface is wholly lit/unlit).
- Cone (base `b`, apex `v = b + h·a`): lateral normal along the generator at angle θ is
  `n_θ ∝ h·u_θ + r·a`; `n_θ·g = 0` so `lit` is constant along each generator and
  `lit(θ) ⇔ h·(q_⊥·u_θ) + r·(q·a) > 0`, `q = l − w·v`. Lit interval centred on `θ_l` with
  `α = acos(−r·(q·a)/(h·|q_⊥|))` (clamped; all lit / all unlit when out of range). This is the
  "tangent from the apex" condition of §5.6. Loop = base arc + generator + apex + generator.
- Output of curved outlines: `conics` entries `{conic: 3x3, kind: "ellipse|parabola|hyperbola|degenerate",
  arc: {theta0, theta1} | null, H: 3x3}` ; `arc` is the circle-parameter range (radians, CCW in the
  circle's `(e1,e2)` frame, `theta1 > theta0`); `null` = full conic. Sampling (64 segments per full
  circle, scaled by arc length) happens only in `output/`.
- Ellipses are written as `<ellipse>` (full) or `<path d="M … A rx ry rot large sweep x y">` (arc);
  parabola/hyperbola/degenerate are sampled polylines (`CONIC_SAMPLED` warning for degenerate only).

### 2.7 Construction (§5.5)
- `L' = P·L`, `F' = P·F`, `P'_i = P·P_i`, `Q'_i = P·Q_i`, `S'_i = P·S_i` all as 2D homogeneous 3-vectors.
- Self-check: `S'_check = (L'×P') × (F'×Q')`; must agree with `S'` within 1e-6 mm after normalisation
  (skipped — with a note in the JSON `checks` — when `P'`, `L'` coincide or any point is at infinity in a way
  that makes the lines undefined).
- Rays drawn in the `construction` layer: the 2D segment through `L'`, `P'`, `S'` (covering all three; if
  `L'` is at infinity the segment is `P'→S'` extended by 20 % beyond both ends) and likewise `F'`, `Q'`, `S'`;
  both clipped to the extended canvas rectangle. Also the vertical `P'Q'` ("頂點垂線").
  Only silhouette vertices get construction rays (§5.1 "只有光輪廓邊的頂點需要投影"); for curved objects:
  sphere → centre + silhouette-circle extreme points; cylinder/cone → generator endpoints and apex.
- Light behind the viewer (depth of L < 0): `L'` is still finite ("反光點"); warning `LIGHT_BEHIND_CAMERA`.
  `L'` at infinity (`x̃3 == 0`): rays are parallel; warning `LIGHT_POINT_AT_INFINITY`.

### 2.8 Numerics (§5.8)
- float64 everywhere; `tol = 1e-9 · scene_scale` where `scene_scale` = max(1, largest extent of the
  bounding box of all object vertices, light position and camera position).
- `normalize_max(v)` divides a homogeneous vector by its max-|component| (sign preserved) — use it before
  any comparison; never divide by `w` before clipping.
- All predicates are `> tol` / `< −tol`; the band in between counts as the "not lit / degenerate" side.
- Degenerate situations never raise. They append `{"code": <CODE>, "ids": [...], "message": str}` to
  `warnings` (sorted by code then ids for determinism). Input errors raise `SceneError(field=...)`.

### 2.9 Warning codes (closed list for v1)
```
CAMERA_LOOKING_ALONG_UP     LIGHT_BEHIND_CAMERA      LIGHT_POINT_AT_INFINITY
DIRECTIONAL_HORIZONTAL      LIGHT_BELOW_RECEIVER     VERTEX_NOT_BELOW_LIGHT
POINT_BEHIND_CAMERA         FACE_PARALLEL_TO_LIGHT   LIGHT_INSIDE_OBJECT
CONIC_SAMPLED               SHADOW_VP_AT_INFINITY    CONSTRUCTION_CHECK_SKIPPED
OBJECT_BELOW_RECEIVER
```

## 3. Public API (pure functions on JSON-serialisable data + numpy)
```python
scene = castplane.load_scene(path_or_dict)                 # validated dict (raises SceneError)
A      = castplane.shadow_geometry(scene)                  # stage A: camera independent
B      = castplane.project_scene(scene, A, camera=None)    # stage B: camera may be overridden
doc    = castplane.compose(scene, B)                       # stage C: §6.2 geometry dict (+ svg via output)
svg    = castplane.output.svg.write_svg(doc, layers=None)  # str
png    = castplane.output.png.write_png(svg, dpi)          # bytes, optional extra
result = castplane.render(scene, camera=None)              # {"geometry": doc, "svg": str}
```
`A`, `B` are plain dicts of numpy arrays/lists and may be cached; `shadow_geometry` must not touch the camera.

### 3.1 §6.2 geometry document (keys, deterministic)
```
canvas_mm, camera {P: 3x4, C: [x,y,z], horizon_line: [a,b,c]}, points {name: {world: [x,y,z] | direction [dx,dy,dz] + at_infinity:true,
image: [u,v] | null, depth: float | null}}, edges [{object, from, to, silhouette(bool, w.r.t. light), back(bool, w.r.t. camera), visibility:"visible"}],
shadows [{light, receiver, object, outline:[point names | {"direction":[..]}], conics:[...], unbounded, loops:[[...]] }],
form_shadow [{object, faces:[[point names]], terminator:[conics/segments]}],
construction {light_point:[u,v]|null, light_point_at_infinity:[a,b]|null, shadow_vp:[u,v]|null, shadow_vp_at_infinity:[a,b]|null,
rays:[["L", name], ["F", name]], checks:[{point, max_error_mm}]},
horizon {v_mm: float|null, line:[a,b,c], vanishing_points:{x:[u,v]|null, y:..., z:...}},
warnings [{code, ids, message}]
```
Point names: `"<obj>.v<k>"`, `"<obj>.v<k>.shadow.<light>"`, `"<obj>.v<k>.foot"`, `"L.<light>"`, `"F.<light>"`,
curved: `"<obj>.c"` (centre), `"<obj>.g0.base"`, `"<obj>.g0.top"`, `"<obj>.g1.*"`, `"<obj>.apex"`,
`"<obj>.sil.<k>"` for sphere silhouette extreme points (k = 0..3). Floats are written with
`repr`-style shortest round-trip formatting; keys sorted; `json.dumps(..., sort_keys=True, indent=1)`.

## 4. Testing contract (§7)
- `tests/test_invariants.py` covers all six §7.1 rows with the stated tolerances.
- `tests/test_analytic.py` covers all four §7.2 bullets.
- `tests/test_degenerate.py` has at least one test per §5.7 row (six rows) asserting warning codes and finite output.
- `tests/test_raycast.py` (§7.3): seeded random scenes, grid sampling on the ground, IoU ≥ 0.99.
- `tests/test_property.py` (§7.4): hypothesis strategies for scenes/cameras incl. degenerate distributions.
- `tests/conformance/` (§7.5): cases + expected, 1e-6 mm, warning code sets equal; `tools/regen_conformance.py` to regenerate with a mandatory `--reason` recorded in `tests/conformance/CHANGELOG.md`.
- `benchmarks/bench.py`: 100 primitives / ~10k edges < 1 s full render; camera-only re-render < 100 ms.
