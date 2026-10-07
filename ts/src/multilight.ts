/**
 * Multi-light assembly helpers (port of `castplane/multilight.py`; contract §5.3.2, §5.3.3, §5.3.5; M6).
 *
 * A scene is multi-light iff it has at least two lights (`is_multi`). Phase 2 part 1 ports the naming helpers that
 * the single-light receiver code already calls (`curved_stem_name` with `multi = false` is the identity on the v1 /
 * M4 names); the multi-light assembly (silhouette lights, form shadow split, construction blocks, umbra entries)
 * follows with the M6 part of §5.4.14.
 */

/** The light-dependent curved stems (`sil.<k>`, `g<k>.base`, `g<k>.top`, contract §5.3.2). */
const LIGHT_STEM = /^(?:sil\.[0-9]+|g[0-9]+\.(?:base|top))$/;

/** A scene (or its `lights` list) is multi-light iff it has at least two lights (§5.3). */
export function is_multi(lights: readonly unknown[] | { lights: readonly unknown[] }): boolean {
  const list = Array.isArray(lights) ? lights : (lights as { lights: readonly unknown[] }).lights;
  return list.length >= 2;
}

/** `sil.<k>`, `g<k>.base` and `g<k>.top` depend on the light; `c`, `apex`, `og<k>.base|top` and the polyhedral
 * `v<k>` do not (contract §5.3.2). */
export function is_light_dependent_stem(stem: string): boolean {
  return LIGHT_STEM.test(stem);
}

/** The base name of a curved construction point (contract §5.3.2, §5.0.4): `<obj>.<stem>`, plus `.<light>` iff
 * `multi` and the stem is light dependent. */
export function curved_stem_name(obj_id: string, stem: string, light_id: string | null, multi: boolean): string {
  const base = `${obj_id}.${stem}`;
  if (multi && is_light_dependent_stem(stem)) return `${base}.${light_id as string}`;
  return base;
}
