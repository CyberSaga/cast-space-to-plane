/**
 * D85 linked parts (contract §5.8 notes) — pure, DOM-free and three-free, unit-tested (`web/test/links.test.ts`).
 *
 * Optional web-only scene keys on an object of a grouped model (D84):
 * - `objects[i].parent`: the id of another part of the same ≥ 2 group; rotating the parent carries this part.
 * - `objects[i].joint`: a point `[x, y, z]` in the object's **local** frame (the frame of its mesh vertices / its
 *   primitive before `transform`); the part turns about its world image `j_w = R·joint + p` instead of its local
 *   bounding-box centre (D82). It rides with the object, so the downloaded scene needs no conversion.
 * - D86 `objects[i].joint_limit`: `{axis, min_deg?, max_deg?}` bounds the part's rotation relative to its parent about
 *   `axis` (the parent's local frame); resolved only for a part with a resolved parent (`limits.ts` has the maths).
 *
 * Like `group` (`groups.ts`) they are ignored by the core validators (§2.0) and written back verbatim by the scene
 * download (`download.ts::scene_blob`). Nothing else is stored: the forest (parents, children, subtrees) is resolved
 * once at load (`PlaneSession`) from the scene's ids and groups; a malformed or unusable key is ignored silently (no
 * SceneError, no warning) and the scene behaves as D84.
 */

import type { Vec3 } from "castplane";

import { is_utf8_text } from "./groups.js";
import type { Limit } from "./limits.js";

/** The scene-JSON key of an object's parent id. */
export const PARENT_KEY = "parent";
/** The scene-JSON key of an object's joint (a local point). */
export const JOINT_KEY = "joint";
/** D86: the scene-JSON key of a part's joint limit. */
export const LIMIT_KEY = "joint_limit";

/** D86: a parse-valid `joint_limit` as written (the axis in the parent's local frame, the bounds in degrees; at least
 * one bound present). */
export interface JointLimit {
  axis: Vec3;
  min_deg?: number;
  max_deg?: number;
}

/** An object's parse-valid link keys (each absent when missing or malformed). */
export interface RawLink {
  parent?: string;
  joint?: Vec3;
  /** D86. */
  joint_limit?: JointLimit;
}

/** The resolved links of a scene (load-time only): per child its parent, per parent its children in scene order (only
 * ids with at least one child have an entry), and per object its parse-valid joint (independent of `parent` and of
 * grouping: a root's own joint, or an ungrouped object's). D86: per part with a resolved parent its limit. */
export interface LinkForest {
  parent: Map<string, string>;
  children: Map<string, string[]>;
  joints: Map<string, Vec3>;
  limits: Map<string, Limit>;
}

/** A parse-valid `parent`: a non-empty string encodable as UTF-8 (no lone surrogate, `groups.ts::is_utf8_text`), kept
 * verbatim (not trimmed: it must equal an object id to resolve). */
export function parse_parent(v: unknown): string | null {
  return typeof v === "string" && v !== "" && is_utf8_text(v) ? v : null;
}

/** A parse-valid `joint`: an array of exactly three finite numbers, stored as `[x + 0, y + 0, z + 0]` (no `-0`). */
export function parse_joint(v: unknown): Vec3 | null {
  if (!Array.isArray(v) || v.length !== 3 || !v.every((x) => typeof x === "number" && Number.isFinite(x))) return null;
  return [(v[0] as number) + 0, (v[1] as number) + 0, (v[2] as number) + 0];
}

const bound_ok = (b: unknown): boolean => b === undefined || (typeof b === "number" && Number.isFinite(b) && b >= -180 && b <= 180);

/**
 * D86: a parse-valid `joint_limit`: a non-null, non-array object whose `axis` is an array of exactly three finite numbers
 * with `0 < hypot(x, y, z) < ∞`, whose `min_deg` / `max_deg`, each when present (not `undefined`), is a finite number in
 * `[−180, 180]`, with at least one of them present and `min_deg ≤ max_deg` when both are. Stored with `+ 0` (no `-0`);
 * other properties are dropped. Anything else is null (the key is absent: no SceneError, no warning).
 */
export function parse_joint_limit(v: unknown): JointLimit | null {
  if (v === null || typeof v !== "object" || Array.isArray(v)) return null;
  const { axis, min_deg, max_deg } = v as Record<string, unknown>;
  const ax = parse_joint(axis);
  if (ax === null) return null;
  const n = Math.hypot(ax[0], ax[1], ax[2]);
  if (!(n > 0 && n < Infinity)) return null;
  if (!bound_ok(min_deg) || !bound_ok(max_deg) || (min_deg === undefined && max_deg === undefined)) return null;
  if (min_deg !== undefined && max_deg !== undefined && (min_deg as number) > (max_deg as number)) return null;
  const out: JointLimit = { axis: ax };
  if (min_deg !== undefined) out.min_deg = (min_deg as number) + 0;
  if (max_deg !== undefined) out.max_deg = (max_deg as number) + 0;
  return out;
}

/** D86: the value *Download scene* writes for a parsed limit: `{axis, min_deg?, max_deg?}` (copies). */
export function limit_for_file(l: JointLimit): JointLimit {
  const out: JointLimit = { axis: [l.axis[0], l.axis[1], l.axis[2]] };
  if (l.min_deg !== undefined) out.min_deg = l.min_deg;
  if (l.max_deg !== undefined) out.max_deg = l.max_deg;
  return out;
}

/**
 * The parse-valid link keys of a raw (unvalidated) scene, keyed by object id, with the skip rules of
 * `groups.ts::object_groups`: entries of `raw.objects` that are objects with a string `id`; an entry `id → RawLink`
 * exists iff at least one of the keys is parse-valid ({@link parse_parent}, {@link parse_joint}, D86
 * {@link parse_joint_limit}), and a malformed key is simply absent from it. Anything else is skipped silently.
 */
export function object_links(raw: unknown): Map<string, RawLink> {
  const out = new Map<string, RawLink>();
  if (raw === null || typeof raw !== "object") return out;
  const objects = (raw as { objects?: unknown }).objects;
  if (!Array.isArray(objects)) return out;
  for (const o of objects) {
    if (o === null || typeof o !== "object" || Array.isArray(o)) continue;
    const { id, [PARENT_KEY]: pv, [JOINT_KEY]: jv, [LIMIT_KEY]: lv } = o as Record<string, unknown>;
    if (typeof id !== "string") continue;
    const parent = parse_parent(pv), joint = parse_joint(jv), limit = parse_joint_limit(lv);
    if (parent === null && joint === null && limit === null) continue;
    const link: RawLink = {};
    if (parent !== null) link.parent = parent;
    if (joint !== null) link.joint = joint;
    if (limit !== null) link.joint_limit = limit;
    out.set(id, link);
  }
  return out;
}

/** `object_links(JSON.parse(text))`; text that is not JSON gives an empty map (the loader reports the error). */
export function object_links_text(text: string): Map<string, RawLink> {
  try {
    return object_links(JSON.parse(text));
  } catch {
    return new Map();
  }
}

/**
 * Resolve the parse-valid links `raw` against the scene's object ids `ids` (scene order) and `group_of` (an id's ≥ 2
 * group, null when ungrouped or alone in its group):
 * 1. `c → par` is a candidate iff `par !== c`, `par ∈ ids` and `group_of(c) !== null && group_of(c) === group_of(par)`
 *    (G2: links only inside one rotation unit); else there is no link.
 * 2. Cycles: every node has at most one parent, so each component holds at most one cycle. A three-colour walk from
 *    every node drops the parent link of **every node on a cycle** (trees hanging off it keep theirs): no tiebreak, so
 *    the result does not depend on the scene order; O(n).
 * 3. `children` in scene order; `joints` every parse-valid joint of an id in `ids`, whatever its parent or group.
 * 4. D86 `limits`: the parse-valid `joint_limit` of every id with a parent after steps 1–2 (a root part, a lone object
 *    or a dropped link has none), with the unit axis and ±180 for an absent bound; a range covering the whole circle
 *    (`min_deg −180` and `max_deg 180`) is no limit.
 */
export function resolve_links(raw: ReadonlyMap<string, RawLink>, ids: readonly string[],
  group_of: (id: string) => string | null): LinkForest {
  const in_scene = new Set(ids);
  const cand = new Map<string, string>();
  for (const c of ids) {
    const par = raw.get(c)?.parent;
    if (par === undefined || par === c || !in_scene.has(par)) continue;
    const g = group_of(c);
    if (g !== null && g === group_of(par)) cand.set(c, par);
  }
  // 1 = on the current walk (grey), 2 = done (black)
  const colour = new Map<string, 1 | 2>();
  const on_cycle = new Set<string>();
  for (const start of ids) {
    if (colour.has(start)) continue;
    const path: string[] = [];
    let x: string | undefined = start;
    while (x !== undefined && !colour.has(x)) {
      colour.set(x, 1);
      path.push(x);
      x = cand.get(x);
    }
    if (x !== undefined && colour.get(x) === 1) for (const y of path.slice(path.indexOf(x))) on_cycle.add(y);
    for (const y of path) colour.set(y, 2);
  }
  const parent = new Map<string, string>();
  const lists = new Map<string, string[]>();
  for (const c of ids) {
    const par = cand.get(c);
    if (par === undefined || on_cycle.has(c)) continue;
    parent.set(c, par);
    const list = lists.get(par);
    if (list === undefined) lists.set(par, [c]);
    else list.push(c);
  }
  const children = new Map<string, string[]>();
  for (const id of ids) {
    const list = lists.get(id);
    if (list !== undefined) children.set(id, list);
  }
  const joints = new Map<string, Vec3>();
  for (const id of ids) {
    const j = raw.get(id)?.joint;
    if (j !== undefined) joints.set(id, [j[0], j[1], j[2]]);
  }
  const limits = new Map<string, Limit>();
  for (const id of ids) {
    const l = raw.get(id)?.joint_limit;
    if (l === undefined || !parent.has(id)) continue;
    const min = l.min_deg ?? -180, max = l.max_deg ?? 180;
    if (min <= -180 && max >= 180) continue;
    const n = Math.hypot(l.axis[0], l.axis[1], l.axis[2]);
    limits.set(id, { axis: [l.axis[0], l.axis[1], l.axis[2]], a: [l.axis[0] / n + 0, l.axis[1] / n + 0, l.axis[2] / n + 0], min, max,
      min_written: l.min_deg !== undefined, max_written: l.max_deg !== undefined });
  }
  return { parent, children, joints, limits };
}

/** The ids a rotation of part `id` moves: preorder, **`id` first** (the numeric fields show the first entry's angles),
 * then each child's subtree, siblings in scene order. `[id]` for a leaf or an id without links. */
export function subtree(forest: LinkForest, id: string): string[] {
  const out: string[] = [];
  const stack = [id];
  while (stack.length > 0) {
    const x = stack.pop()!;
    out.push(x);
    const kids = forest.children.get(x);
    if (kids !== undefined) for (let k = kids.length - 1; k >= 0; k--) stack.push(kids[k]!);
  }
  return out;
}
