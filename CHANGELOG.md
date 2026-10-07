## Unreleased — review fixes

- m8-step#0: STEP `fallback="mesh"` now tessellates the unrecognised solid itself (`TransferOne` of its own Part-21 record, checked against its vertex points) instead of the k-th solid of OCC's assembly-ordered explorer, which meshed the wrong solid in renumbered multi-solid files.
- m8-step#1: Part 21 values nested deeper than 64 levels are a `syntax: nesting too deep` `StepError` (exit 2) instead of a `RecursionError` traceback.
- m8-step#2: Integer literals beyond 2^53 parse as floats (no `int()` 4300-digit `ValueError`, no `OverflowError`), entity ids are capped at 18 digits (`syntax: entity id too long`); oversized numbers end in a `StepError` (exit 2).
- m8-step#3: `import_step(fallback="mesh")` reads the STEP file with OCP once per import instead of once per unrecognised solid (120 solids: 24.5 s → 1.9 s).
- m8-step#4: A non-positive cylindrical / spherical / circle radius (negative conical radius) is a `StepError` naming the entity instead of an emitted object rejected later at `objects[i].radius`.
- m8-step#5: A non-finite coordinate in any `CARTESIAN_POINT` is a `StepError` naming the point instead of making the tolerance infinite and blaming the geometry.
