/**
 * Multi-light assembly helpers (port of `castplane/multilight.py`; contract §5.3.2, §5.3.3, §5.3.5; M6, M7 phase 2
 * §5.4.14).
 *
 * A scene is multi-light iff it has at least two lights (`is_multi`). Every light is evaluated with the v1 / M4 formulas
 * exactly as if it were alone; this module holds the small, pure pieces that turn those per-light results into the
 * multi-light parts of stages B and C, so that the pipeline only needs hooks:
 *
 * - names: `curved_stem_name` (light-dependent curved base names get the light id as their last segment, §5.3.2) and
 *   `multi_light_name` (the single-light → multi-light name map of the bit-identity statement);
 * - edges: `silhouette_lights` (`edges[].silhouette` as the OR over lights and the additive `edges[].silhouette_lights`)
 *   and `plate_silhouette_lights` (a receiver's bounds edges);
 * - form shadow: `unlit_union` / `form_table` (the faces unlit by at least one light, projected once), `split_form`
 *   (per-light lists and the core sharing the same drawables), `plate_form_lights` (plates as one-face polyhedra),
 *   `assemble_form_shadow` (`form_shadow[]` light-major with `light`, and `form_shadow_core[]`);
 * - construction: `construction_block` (§5.4.14 (c): one M4 construction block per light, incl. `per_receiver`;
 *   `construction` stays the alias of the first light), `construction_blocks` and `construction_doc` (the document
 *   block);
 * - umbra: `active_lights` and `umbra_entries` (one `umbra[]` entry per receiver from the stage-B drawables, through
 *   `umbra.ts`).
 *
 * Port notes: Python tuples are arrays and dicts keyed by light id are `Map`s in scene order; the reference's
 * `form_table` returns the padded numpy tables, the port the face vertex-index lists (`form_idx`, contract §5.4.2: the
 * padded tables are not ported); `construction_block` keeps the §5.4.14 (c) argument order `(light, shadows,
 * receiver_lights, default_id)` of phase 1 (the reference's is `(light, receiver_lights, shadows, default_id)`).
 */

import { canonical } from "./output/geometry_json.js";
import type { ConstructionStageB, LightStageB, ShadowStageB } from "./pipeline.js";
import { umbra_pieces } from "./umbra.js";
import type { UV } from "./umbra.js";

/** The light-dependent curved stems (`sil.<k>`, `g<k>.base`, `g<k>.top`, contract §5.3.2), anchored at the start. */
const LIGHT_STEM_PREFIX = /^(?:sil\.[0-9]+|g[0-9]+\.(?:base|top))(?=\.|$)/;

/** A scene (or its `lights` list) is multi-light iff it has at least two lights (§5.3). */
export function is_multi(lights: readonly unknown[] | { lights?: readonly unknown[] }): boolean {
  const list = Array.isArray(lights) ? lights : ((lights as { lights?: readonly unknown[] }).lights ?? []);
  return list.length >= 2;
}

/** `sil.<k>`, `g<k>.base` and `g<k>.top` depend on the light; `c`, `apex`, `og<k>.base|top` and the polyhedral `v<k>`
 * do not (contract §5.3.2). */
export function is_light_dependent_stem(stem: string): boolean {
  const m = LIGHT_STEM_PREFIX.exec(stem);
  return m !== null && m[0].length === stem.length;
}

/** The base name of a curved construction point (contract §5.3.2, §5.0.4): `<obj>.<stem>`, plus `.<light>` iff `multi`
 * and the stem is light dependent. Shadow and foot names are composed from it by appending `.shadow.<light>[.<r>]` /
 * `.foot[.<r>]`. */
export function curved_stem_name(obj_id: string, stem: string, light_id: string | null, multi: boolean): string {
  const base = `${obj_id}.${stem}`;
  if (multi && is_light_dependent_stem(stem)) return `${base}.${light_id as string}`;
  return base;
}

/** The name map of the bit-identity statement (contract §5.3.2): a point name of the single-light document of light
 * `light_id` → its name in the multi-light document (`sil.<k>` → `sil.<k>.<light>`, `g<k>.base|top` →
 * `g<k>.base|top.<light>`, applied right after the object id; every other name is unchanged). With `object_ids` only
 * names whose first part is one of them are mapped (so `F.<light>.<r>` is never read as a curved stem). */
export function multi_light_name(name: string, light_id: string, object_ids: Iterable<string> | null = null): string {
  const i = name.indexOf(".");
  if (i < 0) return name;
  const head = name.slice(0, i), rest = name.slice(i + 1);
  if (object_ids !== null && !new Set(object_ids).has(head)) return name;
  const m = LIGHT_STEM_PREFIX.exec(rest);
  if (m === null) return name;
  const end = m[0].length;
  return `${head}.${rest.slice(0, end)}.${light_id}${rest.slice(end)}`;
}

// ---------------------------------------------------------------------------
// edges (contract §5.3.3)
// ---------------------------------------------------------------------------

/**
 * `edges[].silhouette` and `edges[].silhouette_lights` of one polyhedral object. `edge_flags[k]` is the
 * `edge_silhouette` list of light `light_ids[k]` or `null` when the object has no record for that light (no silhouette
 * edge). Returns `[silhouette, lists]`: the OR over lights and, per edge, the ids of the lights for which it is a
 * silhouette edge (scene order, `[]` allowed). `n_edges` is required (an object with no record for any light still gets
 * one `false` per edge); a flag list of another length is a caller error (`Error`, the reference's `ValueError`).
 */
export function silhouette_lights(edge_flags: readonly (readonly boolean[] | null | undefined)[], light_ids: readonly string[],
  n_edges: number): [boolean[], string[][]] {
  const n = Math.trunc(n_edges);
  edge_flags.forEach((a, k) => {
    if (a !== null && a !== undefined && a.length !== n) throw new Error(`edge_flags[${k}] has ${a.length} flags, expected ${n}`);
  });
  const silhouette: boolean[] = [];
  const lists: string[][] = [];
  for (let e = 0; e < n; e++) {
    const ids: string[] = [];
    light_ids.forEach((lid, k) => {
      const a = edge_flags[k];
      if (a !== null && a !== undefined && a[e] === true) ids.push(lid);
    });
    silhouette.push(ids.length > 0);
    lists.push(ids);
  }
  return [silhouette, lists];
}

/** `silhouette_lights` of a bounded receiver's bounds edges: the lights for which the plate casts
 * (`receivers[r].casts[k]`), scene order (contract §5.3.3). */
export function plate_silhouette_lights(casts: ReadonlyMap<string, boolean> | Readonly<Record<string, boolean>>,
  light_ids: readonly string[]): string[] {
  const get = (lid: string): boolean => (casts instanceof Map ? casts.get(lid)
    : Object.prototype.hasOwnProperty.call(casts, lid) ? (casts as Record<string, boolean>)[lid] : false) === true;
  return light_ids.filter(get);
}

// ---------------------------------------------------------------------------
// form shadow and core (contract §5.3.1, §5.3.3, §5.3.5)
// ---------------------------------------------------------------------------

/**
 * Faces unlit by at least one light (contract §5.3.3). `lit_by_light[k]` is the face lit-flag list of light `k`
 * ("parallel" already counts as unlit, a light inside the solid already makes every face unlit) or `null` for a light
 * without a record (all faces lit by it). Returns `[union, masks, core]`: the face indices of the union in face-index
 * order, per light a mask over `union` (that light's unlit faces) and the mask over `union` of the **core** faces
 * (unlit by every light). For `N = 1` the union is the v1 unlit set.
 */
export function unlit_union(lit_by_light: readonly (readonly boolean[] | null | undefined)[]): [number[], boolean[][], boolean[]] {
  const first = lit_by_light.find((a) => a !== null && a !== undefined);
  const n = first === undefined || first === null ? 0 : first.length;
  const unlit = lit_by_light.map((a) => Array.from({ length: n }, (_x, f) => a !== null && a !== undefined && a[f] !== true));
  const union: number[] = [];
  for (let f = 0; f < n; f++) if (unlit.some((row) => row[f])) union.push(f);
  const masks = unlit.map((row) => union.map((f) => row[f] as boolean));
  const core = lit_by_light.length > 0 ? union.map((f) => unlit.every((row) => row[f])) : [];
  return [union, masks, core];
}

/** The input `form_table` reads of one polyhedral stage-A object. */
export interface FormTableObject {
  lights: ReadonlyMap<string, { lit: readonly boolean[] }>;
  mesh: { faces: readonly (readonly number[])[] };
  face_point_names: readonly (readonly string[])[];
}

/** The faces unlit by at least one light of one polyhedral stage-A object (the multi-light replacement of the
 * per-light `form_idx` / `form_faces`; for `N = 1` exactly those lists): `{form_idx, form_faces, masks, core}`. */
export function form_table(obj: FormTableObject, light_ids: readonly string[]): {
  form_idx: number[][]; form_faces: string[][]; masks: boolean[][]; core: boolean[];
} {
  const lit = light_ids.map((lid) => obj.lights.get(lid)?.lit ?? null);
  const [union, masks, core] = unlit_union(lit);
  return {
    form_idx: union.map((f) => [...(obj.mesh.faces[f] as readonly number[])]),
    form_faces: union.map((f) => obj.face_point_names[f] as string[]),
    masks,
    core,
  };
}

/** Per-light lists and the core of one object from the projected union (contract §5.3.3): `by_light.get(lid) =
 * [faces, polygons]` (that light's unlit faces, face-index order) and `core = [faces, polygons]` (faces unlit by all
 * lights). The lists reference the same drawable objects as `faces` / `polygons` (projected once). */
export function split_form<F, Q>(faces: readonly F[], polygons: readonly Q[], masks: readonly (readonly boolean[])[],
  core: readonly boolean[], light_ids: readonly string[]): [Map<string, [F[], Q[]]>, [F[], Q[]]] {
  const pick = (mask: readonly boolean[]): [F[], Q[]] => {
    const idx: number[] = [];
    mask.forEach((b, i) => {
      if (b) idx.push(i);
    });
    return [idx.map((i) => faces[i] as F), idx.map((i) => polygons[i] as Q)];
  };
  const by_light = new Map<string, [F[], Q[]]>();
  light_ids.forEach((lid, k) => {
    if (k < masks.length) by_light.set(lid, pick(masks[k] as readonly boolean[]));
  });
  return [by_light, pick(core)];
}

/** Plates as one-face polyhedra (contract §5.1.8, §5.3.3): `light_sides[k] = π_rᵀL_k` and `tol_ws[k]` its tolerance
 * (stage A), `cam_side = n_r·(C − b_0)` (stage B). Returns `[flags, core]`: `flags[k]` is the single-light rule of light
 * `k` (the camera faces the side of the plate unlit by that light, both signs strictly beyond their tolerances), `core`
 * is true iff the camera side is decided and **no** light is strictly on the camera's side ("parallel" counts as
 * unlit). */
export function plate_form_lights(light_sides: readonly number[], tol_ws: readonly number[], cam_side: number,
  tol: number): [boolean[], boolean] {
  if (!(Math.abs(cam_side) > tol)) return [light_sides.map(() => false), false];
  const cam_pos = cam_side > 0.0;
  const flags: boolean[] = [];
  let lit_any = false;
  const n = Math.min(light_sides.length, tol_ws.length);
  for (let k = 0; k < n; k++) {
    const side = light_sides[k] as number, tw = tol_ws[k] as number;
    const decided = Math.abs(side) > tw;
    flags.push(decided && (side > 0.0) !== cam_pos);
    lit_any = lit_any || (decided && (side > 0.0) === cam_pos);
  }
  return [flags, !lit_any && flags.length > 0];
}

/** One `form_shadow[]` entry of a multi-light document. */
export interface FormLightEntry {
  light: string;
  object: string;
  faces: unknown[];
  polygons: unknown[];
  terminator: unknown[];
}

/** One `form_shadow_core[]` entry. */
export interface FormCoreEntry {
  object: string;
  faces: unknown[];
  polygons: unknown[];
}

/** An item of `assemble_form_shadow`: one object (or plate) in document order. */
export interface FormItem {
  object: string;
  by_light: ReadonlyMap<string, { faces?: readonly unknown[]; polygons?: readonly unknown[]; terminator?: readonly unknown[] }>;
  core: { faces: readonly unknown[]; polygons: readonly unknown[] } | null;
}

/** `form_shadow[]` and `form_shadow_core[]` of a multi-light document (contract §5.3.5): one entry
 * `{light, object, faces, polygons, terminator}` per (light, object) with unlit faces or a terminator, light-major
 * (scene order) then object order; one core entry `{object, faces, polygons}` per object with at least one core face. */
export function assemble_form_shadow(items: readonly FormItem[], light_ids: readonly string[]): [FormLightEntry[], FormCoreEntry[]] {
  const form: FormLightEntry[] = [];
  for (const lid of light_ids) {
    for (const it of items) {
      const e = it.by_light.get(lid);
      if (e === undefined || !((e.faces ?? []).length > 0 || (e.terminator ?? []).length > 0)) continue;
      form.push({
        light: lid, object: it.object, faces: [...(e.faces ?? [])], polygons: [...(e.polygons ?? [])], terminator: [...(e.terminator ?? [])],
      });
    }
  }
  const core: FormCoreEntry[] = [];
  for (const it of items) {
    const c = it.core;
    if (c !== null && c.faces.length > 0) core.push({ object: it.object, faces: [...c.faces], polygons: [...c.polygons] });
  }
  return [form, core];
}

// ---------------------------------------------------------------------------
// construction per light (contract §5.3.3, §5.3.5, §5.4.14 (c))
// ---------------------------------------------------------------------------

/**
 * One light's construction block (contract §2.7, §5.1.5, §5.3.3, §5.4.14 (c)): `light` is the stage-B record of the
 * default receiver, `receiver_lights.get(<r>)` the stage-B records of every other receiver (one per light, scene order),
 * `shadows` the stage-B records. The flat `rays` / `checks` / `segments` concatenate that light's records on the default
 * receiver in `shadows[]` order; `per_receiver[<r>]` those on receiver `r`. For one light this is the v1 / M4
 * `construction` block; the per-light `constructions` map of §5.3.5 is `construction_blocks`, a loop around it.
 */
export function construction_block(light: LightStageB, shadows: readonly ShadowStageB[],
  receiver_lights: ReadonlyMap<string, readonly LightStageB[]> = new Map(), default_id: string | null = null): ConstructionStageB {
  const lid = light.id;
  const own = shadows.filter((s) => (default_id === null || s.receiver === default_id) && s.light === lid);
  const block: ConstructionStageB = {
    light_point: light.light_point.point,
    light_point_at_infinity: light.light_point.at_infinity,
    shadow_vp: light.shadow_vp.point,
    shadow_vp_at_infinity: light.shadow_vp.at_infinity,
    rays: own.flatMap((s) => s.rays),
    checks: own.flatMap((s) => s.checks),
    segments: own.flatMap((s) => s.segments),
    per_receiver: new Map(),
  };
  for (const [rid, recs] of receiver_lights) {
    const lt_r = recs.find((r) => r.id === lid);
    if (lt_r === undefined) continue;
    const own_r = shadows.filter((s) => s.receiver === rid && s.light === lid);
    block.per_receiver.set(rid, {
      shadow_vp: lt_r.shadow_vp.point,
      shadow_vp_at_infinity: lt_r.shadow_vp.at_infinity,
      rays: own_r.flatMap((s) => s.rays),
      checks: own_r.flatMap((s) => s.checks),
      segments: own_r.flatMap((s) => s.segments),
    });
  }
  return block;
}

/** `B.constructions`: `{<light id>: construction_block(...)}` in scene order (a `Map`); the caller sets
 * `B.construction = B.constructions.get(lights[0].id)` (the same object). */
export function construction_blocks(lights: readonly LightStageB[], receiver_lights: ReadonlyMap<string, readonly LightStageB[]>,
  shadows: readonly ShadowStageB[], default_id: string | null): Map<string, ConstructionStageB> {
  return new Map(lights.map((lt) => [lt.id, construction_block(lt, shadows, receiver_lights, default_id)] as const));
}

/** The document form of one construction block (contract §3.1, §5.1.7): the small keys through `canonical`, the lists
 * (`rays`, `checks`, `segments`, already canonical) copied shallowly; `per_receiver` in the block's (receiver scene)
 * order. */
export function construction_doc(block: ConstructionStageB): Record<string, unknown> {
  const out: Record<string, unknown> = canonical({
    light_point: block.light_point,
    light_point_at_infinity: block.light_point_at_infinity,
    shadow_vp: block.shadow_vp,
    shadow_vp_at_infinity: block.shadow_vp_at_infinity,
  });
  out["rays"] = [...block.rays];
  out["checks"] = [...block.checks];
  out["segments"] = [...block.segments];
  const per: Record<string, unknown> = {};
  for (const [rid, blk] of block.per_receiver) {
    per[rid] = {
      ...canonical({ shadow_vp: blk.shadow_vp, shadow_vp_at_infinity: blk.shadow_vp_at_infinity }),
      rays: [...blk.rays],
      checks: [...blk.checks],
      segments: [...blk.segments],
    };
  }
  out["per_receiver"] = per;
  return out;
}

// ---------------------------------------------------------------------------
// umbra (contract §5.3.1, §5.3.4)
// ---------------------------------------------------------------------------

/** The lights active on a receiver (`receivers[r].lit[k]` true), scene order: `umbra[].lights`. */
export function active_lights(receiver: { lit?: Readonly<Record<string, boolean>> }, light_ids: readonly string[]): string[] {
  const lit = receiver.lit ?? {};
  return light_ids.filter((lid) => Object.prototype.hasOwnProperty.call(lit, lid) && lit[lid] === true);
}

/** One `umbra[]` entry (contract §5.3.5). */
export interface UmbraStageEntry {
  receiver: string;
  lights: string[];
  polygons: UV[][] | null;
}

/** `umbra[]`: one entry `{receiver, lights, polygons}` per receiver (scene order) from the document `receivers[]`
 * entries (`lit`) and the stage-B / document `shadows[]` drawables (contract §5.3.4, §5.3.5 (c)). `polygons` is
 * `umbra_pieces` of the active lights' records (`[]` when fewer than two are active) or `null` when `compute` is false
 * (`project_scene(..., umbra = false)`). */
export function umbra_entries(receivers: readonly { id: string; lit?: Readonly<Record<string, boolean>> }[],
  shadows: readonly { receiver: string; light: string; polygons: readonly (readonly (readonly number[])[])[] }[],
  light_ids: readonly string[], canvas_mm: readonly number[], compute = true): UmbraStageEntry[] {
  return receivers.map((rcv) => {
    const rid = rcv.id;
    const active = active_lights(rcv, light_ids);
    let polygons: UV[][] | null = null;
    if (compute) {
      const per_light = active.map((lid) => shadows.filter((s) => s.receiver === rid && s.light === lid).map((s) => s.polygons));
      polygons = umbra_pieces(per_light, canvas_mm);
    }
    return { receiver: rid, lights: active, polygons };
  });
}
