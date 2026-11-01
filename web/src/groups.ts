/**
 * D84 groups of parts (contract §5.8 notes) — pure, DOM-free and three-free, unit-tested (`web/test/groups.test.ts`).
 *
 * The optional web-only scene key `objects[i].group` (a non-empty string) names the model an object is a part of. Like
 * `display_color` (`colours.ts`) it is display-only: the validators ignore unknown keys (§2.0), so the validated `Scene`
 * drops it and no core output depends on it; the UI reads it from the raw JSON where it loads a scene and writes it back
 * unchanged in the downloaded scene (`download.ts::scene_blob`). It is unrelated to OBJ `g` groups and to a mesh's
 * `data.smooth_groups`.
 *
 * A **unit** is a group with at least two members present in the scene, or a single object (no group, or a group name
 * used by one object only). The left pane's click cycle ({@link next_selection}) selects a whole unit first, then a part.
 */

/** The scene-JSON key of an object's group name. */
export const GROUP_KEY = "group";

/** The prefix of a group's key in the 物體 dropdown and in the pivot selection: object ids cannot contain `.`
 * (`ts/src/scene.ts::id`), so `group.<name>` never equals an object id. */
export const GROUP_VALUE_PREFIX = "group.";

/** A UTF-16 code unit that is a surrogate without its pair (`String.prototype.isWellFormed` is not in the ES2022 lib). */
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

/** The left pane's selection: nothing, a whole group (≥ 2 members), or one object (a part, or an ungrouped object). */
export type Selection = null | { kind: "group"; group: string } | { kind: "part"; id: string };

/** Whether `s` is encodable as UTF-8: no UTF-16 surrogate without its pair (D84 review: JSON `"\ud800"` parses, but
 * the downloaded scene's `dumps` could not write it). D85 also uses it for `objects[i].parent` (`links.ts`). */
export function is_utf8_text(s: string): boolean {
  return !LONE_SURROGATE.test(s);
}

/** Whether `value` is a valid group name: a string that is not empty or whitespace only (kept verbatim, not trimmed)
 * and is encodable as UTF-8 (D84 review: no lone surrogate such as JSON `"\ud800"`, which the downloaded scene's
 * `dumps` could not write). */
export function is_group_name(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "" && is_utf8_text(value);
}

/**
 * The valid group names of a raw (unvalidated) scene, keyed by object id: entries of `raw.objects` that are objects
 * with a string `id` and a valid `group` ({@link is_group_name}; the string kept verbatim). Anything else (no `objects`
 * array, non-object entries, missing or non-string ids, a missing, non-string, empty or whitespace-only group) is
 * skipped silently: no SceneError, no warning, the object is ungrouped.
 */
export function object_groups(raw: unknown): Map<string, string> {
  const out = new Map<string, string>();
  if (raw === null || typeof raw !== "object") return out;
  const objects = (raw as { objects?: unknown }).objects;
  if (!Array.isArray(objects)) return out;
  for (const o of objects) {
    if (o === null || typeof o !== "object" || Array.isArray(o)) continue;
    const { id, [GROUP_KEY]: value } = o as Record<string, unknown>;
    if (typeof id === "string" && is_group_name(value)) out.set(id, value);
  }
  return out;
}

/** `object_groups(JSON.parse(text))`; text that is not JSON gives an empty map (the loader reports the error). */
export function object_groups_text(text: string): Map<string, string> {
  try {
    return object_groups(JSON.parse(text));
  } catch {
    return new Map();
  }
}

/**
 * The groups with at least two members among the scene's object ids `ids` (scene order), each with its member ids in
 * scene order; groups in the order of their first member. A group name used by one object only is left out (that
 * object behaves as an ungrouped one).
 */
export function group_members(groups: ReadonlyMap<string, string>, ids: readonly string[]): Map<string, string[]> {
  const all = new Map<string, string[]>();
  for (const id of ids) {
    const g = groups.get(id);
    if (g === undefined) continue;
    const list = all.get(g);
    if (list === undefined) all.set(g, [id]);
    else list.push(id);
  }
  return new Map([...all].filter(([, list]) => list.length >= 2));
}

/** The ≥ 2 group of object `id` (null when it is ungrouped or the only object of its group). */
export function group_of(id: string, groups: ReadonlyMap<string, string>, members: ReadonlyMap<string, readonly string[]>): string | null {
  const g = groups.get(id);
  return g !== undefined && members.has(g) ? g : null;
}

/**
 * The click cycle (D84) for a left-pane click on object `clicked`:
 * - not in a ≥ 2 group: `{part, clicked}` (as D83);
 * - in group G: nothing selected or a selection outside G → `{group G}`; `{group G}` → `{part clicked}`; `{part p}` with
 *   `p` in G: `p === clicked` → `{group G}`, else `{part clicked}` (the focus moves to the other part of the same model).
 * A click on blank space is not handled here (it clears the selection).
 */
export function next_selection(current: Selection, clicked: string, groups: ReadonlyMap<string, string>,
  members: ReadonlyMap<string, readonly string[]>): Selection {
  const G = group_of(clicked, groups, members);
  if (G === null) return { kind: "part", id: clicked };
  if (current === null) return { kind: "group", group: G };
  if (current.kind === "group") return current.group === G ? { kind: "part", id: clicked } : { kind: "group", group: G };
  if (group_of(current.id, groups, members) !== G) return { kind: "group", group: G };
  return current.id === clicked ? { kind: "group", group: G } : { kind: "part", id: clicked };
}

/** Exact equality of two selections. */
export function same_selection(a: Selection, b: Selection): boolean {
  if (a === null || b === null) return a === b;
  if (a.kind === "group") return b.kind === "group" && a.group === b.group;
  return b.kind === "part" && a.id === b.id;
}

/** The key of a selection in the 物體 dropdown and the pivot selection: `""`, the object id, or `group.<name>`. */
export function selection_value(sel: Selection): string {
  return sel === null ? "" : sel.kind === "part" ? sel.id : GROUP_VALUE_PREFIX + sel.group;
}

/** The selection of a dropdown value ({@link selection_value}'s inverse): `""` → null, `group.<name>` → the group,
 * anything else → that object as a part. */
export function selection_of_value(value: string): Selection {
  if (value === "") return null;
  if (value.startsWith(GROUP_VALUE_PREFIX)) return { kind: "group", group: value.slice(GROUP_VALUE_PREFIX.length) };
  return { kind: "part", id: value };
}

/** The dropdown label of a group: 「<name>（整組，<n> 個部件）」. */
export function group_option_label(name: string, n: number): string {
  return `${name}（整組，${n} 個部件）`;
}

/** The panel's line naming the selection: 「已選：<name>（整組）」, 「已選：<id>（<group> 的部件）」, 「已選：<id>」, or `""`.
 * D85: `carried` (the number of descendants a part's rotation carries, `subtree(P).length − 1`) > 0 on a part of a
 * group gives 「已選：<id>（<group> 的部件，帶動 <carried> 個部件）」; 0 (the default) gives the D84 strings. Links exist
 * only inside a ≥ 2 group (`links.ts::resolve_links`), so `carried` is ignored for a whole group or an ungrouped object. */
export function selection_text(sel: Selection, groups: ReadonlyMap<string, string>,
  members: ReadonlyMap<string, readonly string[]>, carried = 0): string {
  if (sel === null) return "";
  if (sel.kind === "group") return `已選：${sel.group}（整組）`;
  const G = group_of(sel.id, groups, members);
  if (G === null) return `已選：${sel.id}`;
  return carried > 0 ? `已選：${sel.id}（${G} 的部件，帶動 ${carried} 個部件）` : `已選：${sel.id}（${G} 的部件）`;
}
