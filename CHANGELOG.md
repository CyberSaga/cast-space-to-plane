# Changelog

## Unreleased — review fixes

- m8-step#0: STEP `fallback="mesh"` now tessellates the unrecognised solid itself (`TransferOne` of its own Part-21 record, checked against its vertex points) instead of the k-th solid of OCC's assembly-ordered explorer, which meshed the wrong solid in renumbered multi-solid files.
- m8-step#1: Part 21 values nested deeper than 64 levels are a `syntax: nesting too deep` `StepError` (exit 2) instead of a `RecursionError` traceback.
- m8-step#2: Integer literals beyond 2^53 parse as floats (no `int()` 4300-digit `ValueError`, no `OverflowError`), entity ids are capped at 18 digits (`syntax: entity id too long`); oversized numbers end in a `StepError` (exit 2).
- m8-step#3: `import_step(fallback="mesh")` reads the STEP file with OCP once per import instead of once per unrecognised solid (120 solids: 24.5 s → 1.9 s).
- m8-step#4: A non-positive cylindrical / spherical / circle radius (negative conical radius) is a `StepError` naming the entity instead of an emitted object rejected later at `objects[i].radius`.
- m8-step#5: A non-finite coordinate in any `CARTESIAN_POINT` is a `StepError` naming the point instead of making the tolerance infinite and blaming the geometry.
- m8-step second review: `import_step(fallback="mesh")` checks that every reference OCC is about to transfer resolves (no missing entity, no reference to `#0`) and raises a `StepError` at the referring record instead of letting OCC kill the interpreter with a segmentation fault; wrong-typed references remain a documented known limit (docs/STEP.md §9).
- m5-loaders#0: wrongly typed glTF JSON values (node TRS / matrix, children, scene nodes, primitives, camera numbers, `KHR_lights_punctual` blocks, NUL in a buffer uri) are `SceneError`s at their glTF JSON path (exit 2) instead of Python tracebacks; a safety net maps any remaining untyped failure to `SceneError("", "malformed glTF: ...")`.
- m5-loaders#1: glTF `bufferViews[k].byteOffset` / `.byteLength` / `.byteStride` and `accessors[k].byteOffset` must be non-negative integers (no numpy crash, no silent read of a neighbouring view).
- m5-loaders#2: a glTF accessor without `bufferView` is capped at `3 · MESH_MAX_FACES` elements before allocation (no multi-GB allocation from a tiny file).
- m5-loaders#3: external glTF buffers must be relative paths inside the file's directory naming a regular file, and only `byteLength` bytes are read (no reading of arbitrary files, no unbounded read of `/dev/zero`).
- m5-loaders#4: glTF node world matrices are computed iteratively (node chains deeper than the recursion limit load).
- m5-loaders#5: glTF import and expansion traverse a file once (`gltf.gltf_context`): `N` mesh nodes cost `O(N)` instead of `O(N²)`.
- m5-loaders#6: pathologically nested JSON and integers beyond Python's digit limit are `SceneError("", "invalid ... JSON")` for glTF and scene files (also a non-UTF-8 scene file).
- m5-loaders#7: STL / PLY faces read by trimesh are range-checked by the loader (`objects[i].path` error).
- m5-mesh#1: the mesh length scale `scale_A` is the bounding box of the vertices used by a face, so a stray unused vertex no longer loosens the tolerances or makes validation reject a good mesh ("no usable face").
- m5-mesh#2: docs/USAGE.md states the smoothing rule as the contract does (one shared non-zero group: always smooth; no groups: angle test; different groups: feature).
- m5-mesh#0: a mesh object's receiver-contact tolerance is `max(tol, weld_tolerance)`: a concave mesh resting on the ground with float32-scale bottom noise keeps its clean shadow outline (no chord across the notch, no spurious `OBJECT_BELOW_RECEIVER`).
- m5-loaders#2 (second pass): the glTF mesh size guard is a running budget checked before each primitive is transformed, and `import_gltf_parts` has an import budget of 20 · 50000 vertices / triangles, so one zero or real accessor reused by many primitives or nodes is a quick `SceneError(nodes[k].mesh)` instead of a `MemoryError` / OOM kill.
- m5-loaders#0 (second pass): glTF integer literals too large for a float (309–4300 digits) are `SceneError`s at their JSON path instead of an `OverflowError` traceback.
- m5-loaders#3 (second pass): an external glTF buffer reached through a symbolic link that resolves outside the file's directory is rejected (`buffers[k].uri`).
- gltf (second pass): a node transform that overflows or has a zero scale is reported at `nodes[k]` / `nodes[k].scale | .matrix` instead of as non-finite scene values at validation.
