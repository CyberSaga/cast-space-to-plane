# Changelog

## Unreleased — review fixes

- m6-umbra#0: umbra kernel bridges zero-width intervals between coincident edges (§5.3.4 step 5), so per-face fallback meshes no longer yield one umbra piece per face fragment (672-face shell under two lights: 5 584 → 27 pieces); conformance bytes unchanged.
- m6-umbra#1: SVG labels parse point names from the right against the known light/receiver ids, so a light called `shadow` or `foot` keeps its `L.`/`F.`/curved-stem labels.
- m4-hidden#0: the SVG construction layer emits the per-receiver F′_r markers and rays in `receivers[]` order, so `write_svg` of a JSON round-tripped document is byte-identical to `write_svg` of the in-memory one.
- determinism-perf#1: contract §5.0.3 / §5.4.7 no longer list `conics[].conic` / `.kind` as camera-free (the image conic depends on `P`); they are listed as camera-dependent.
- m4-hidden#2: the M4 depth-buffer guard note counts 29 scenes (was 28).
- docs-contract#5: README, USAGE and contract §5.0.6 / §5.1.8 document the `cast_shadow.<light>.<object>.<r>.outline` / `.conics` ids of records on non-default receivers.
- docs-contract#6: contract §5.0.1 names both reserved-id messages (`reserved id`, `reserved id in a multi-light scene`), matching the loader.
- determinism-perf#2: `benchmarks/bench.py` prints `no target` instead of a single-light PASS/FAIL verdict on the full / camera-only / hidden-lines rows of the target-free `--lights 2|3` and `--scene mesh10k` variants.
- m4-hidden#1: `benchmarks/README.md` records the informational mesh10k hidden-lines row (≈ 5.8 s, no target; brute-force occluder test permitted by §5.1.6.2); no code change.
- review (second pass), m4-hidden#1 note: `benchmarks/README.md` no longer claims an AABB cull cannot help the mesh10k hidden-lines row; it records `_MT_BLOCK = 1 << 17` (byte-identical, 5.93 s → 4.29 s, 468 → 120 MB peak RSS) and a mesh-AABB-clipped triangle cull as result-identical, unimplemented options.
- review (second pass), determinism-perf#1 follow-up: contract §5.0.3 / §5.4.7 restrict the camera-free `conics[].{arc, circle, map, which}` claim to objects without `POINT_BEHIND_CAMERA` (a near-cut camera changes the entry list and `arc`, §2.6).
- review (second pass), determinism-perf#2 follow-up: `tests/test_bench.py` covers the `--scene mesh10k` target-free rows.
- review (second pass), m6-umbra#0 follow-up: `benchmarks/README.md` and contract §5.3 record that the bridged kernel still costs O(events × active edges) on per-face fallback meshes under N ≥ 2 (2752 faces: 0.81 s) and that `umbra=False` is the escape hatch for 10k+ faces.
