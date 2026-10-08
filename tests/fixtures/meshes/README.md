# M5 mesh loader fixtures

Written by `python3 tools/make_mesh_fixtures.py` (byte-deterministic; `--check` compares, and
`tests/test_loaders.py::test_fixture_generator_is_in_sync` runs it). Used by `tests/test_loaders.py`,
`tests/test_mesh_pipeline.py` and the `castplane import` examples of `docs/USAGE.md`. Contract §5.2.8, §5.2.11.

| file | content |
| --- | --- |
| `box_split.obj` | the split-vertex unit box of contract §5.2.12 (24 vertices, 12 triangles on the duplicates), Z-up |
| `box_split_y.obj` | the same box in Y-up axes (`A^T: (x, y, z) -> (x, z, -y)`); load with `up: "y"` |
| `features.obj` | OBJ features: 4-component `v`, `v/vt`, `v//vn`, `v/vt/vn`, negative indices, `o` / `g` (two names on one line), `s off` / `s N`, quads, `\` continuation, comments, ignored `vt` / `vn` / `l` / `p` / `mtllib` / `usemtl` |
| `box.gltf` + `box.bin` | the split box in glTF axes, external buffer, `uint16` indices |
| `box_datauri.gltf` | the same with a base64 `data:` URI |
| `box.glb` | the same as a GLB container (JSON + BIN chunks) |
| `primitives.gltf` | nodes `Strided` (interleaved POSITION / NORMAL, `byteStride` 24, a padded view offset, `uint32` indices), `U8` (`uint8` indices), `Soup` (non-indexed), `Strip` (mode 5), `Fan` (mode 6 plus a skipped line primitive) |
| `mirrored.gltf` | nested TRS: a root rotated 90° about +Y, a mirroring child (scale −1 on x, `det < 0` → faces reversed), a column-major `matrix` leaf |
| `import_scene.gltf` | the `castplane import` fixture: camera `yfov = 0.6` (→ `focal_length_mm = 12 / tan(0.3) = 38.79273772518993`), aspect 1.5; `KHR_lights_punctual` point light `Lamp` and spot light `Spot`; an unnamed mesh node (node 3, a wedge), the named mesh node `Cube`, an `extras.castplane` cylinder `Pillar` rotated 30° about the glTF +Y axis |
| `box.stl`, `box.ply` | the unit box as ASCII STL (36 corners) and ASCII PLY (8 vertices, 12 triangles), read through the optional trimesh |
