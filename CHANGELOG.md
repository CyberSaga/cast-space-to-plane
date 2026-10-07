# Changelog

## Unreleased — review fixes

- m5-loaders#0: wrongly typed glTF JSON values (node TRS / matrix, children, scene nodes, primitives, camera numbers, `KHR_lights_punctual` blocks, NUL in a buffer uri) are `SceneError`s at their glTF JSON path (exit 2) instead of Python tracebacks; a safety net maps any remaining untyped failure to `SceneError("", "malformed glTF: ...")`.
- m5-loaders#1: glTF `bufferViews[k].byteOffset` / `.byteLength` / `.byteStride` and `accessors[k].byteOffset` must be non-negative integers (no numpy crash, no silent read of a neighbouring view).
- m5-loaders#2: a glTF accessor without `bufferView` is capped at `3 · MESH_MAX_FACES` elements before allocation (no multi-GB allocation from a tiny file).
- m5-loaders#3: external glTF buffers must be relative paths inside the file's directory naming a regular file, and only `byteLength` bytes are read (no reading of arbitrary files, no unbounded read of `/dev/zero`).
- m5-loaders#4: glTF node world matrices are computed iteratively (node chains deeper than the recursion limit load).
- m5-loaders#5: glTF import and expansion traverse a file once (`gltf.gltf_context`): `N` mesh nodes cost `O(N)` instead of `O(N²)`.
- m5-loaders#6: pathologically nested JSON and integers beyond Python's digit limit are `SceneError("", "invalid ... JSON")` for glTF and scene files (also a non-UTF-8 scene file).
- m5-loaders#7: STL / PLY faces read by trimesh are range-checked by the loader (`objects[i].path` error).
