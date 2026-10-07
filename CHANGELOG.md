# Changelog

## Unreleased — review fixes

- m6-umbra#0: umbra kernel bridges zero-width intervals between coincident edges (§5.3.4 step 5), so per-face fallback meshes no longer yield one umbra piece per face fragment (672-face shell under two lights: 5 584 → 27 pieces); conformance bytes unchanged.
- m6-umbra#1: SVG labels parse point names from the right against the known light/receiver ids, so a light called `shadow` or `foot` keeps its `L.`/`F.`/curved-stem labels.
- m4-hidden#0: the SVG construction layer emits the per-receiver F′_r markers and rays in `receivers[]` order, so `write_svg` of a JSON round-tripped document is byte-identical to `write_svg` of the in-memory one.
- determinism-perf#1: contract §5.0.3 / §5.4.7 no longer list `conics[].conic` / `.kind` as camera-free (the image conic depends on `P`); they are listed as camera-dependent.
- m4-hidden#2: the M4 depth-buffer guard note counts 29 scenes (was 28).
- docs-contract#5: README, USAGE and contract §5.0.6 / §5.1.8 document the `cast_shadow.<light>.<object>.<r>.outline` / `.conics` ids of records on non-default receivers.
- docs-contract#6: contract §5.0.1 names both reserved-id messages (`reserved id`, `reserved id in a multi-light scene`), matching the loader.
