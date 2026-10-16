/**
 * The 3D views' per-object colours (contract §5.4.10; the optional `objects[i].display_color`, §5.4 notes) — pure,
 * DOM-free and three-free, unit-tested (`web/test/colours.test.ts`).
 *
 * Every object is drawn with the palette colour of its index unless the raw scene JSON gives it a valid
 * `display_color` (`"#rrggbb"`, six hex digits, either case). The key is display-only: the validators ignore unknown
 * keys (§2.0), so the validated `Scene` drops it and no core output (document, SVG, warnings) depends on it; the UI
 * reads it from the raw JSON where it loads a scene and keeps it in the downloaded scene (`download.ts::scene_blob`).
 */

/** Per-object colours of the 3D views, cycled by object index. */
export const PALETTE: readonly number[] = [0xc9d6e8, 0xe8d3c3, 0xd2e3c8, 0xe6d9ef, 0xf0e2b6, 0xc8e4e4, 0xebc9cf, 0xd9d9d9];

/** The scene-JSON key of an object's display colour. */
export const DISPLAY_COLOR_KEY = "display_color";

const HEX6 = /^#[0-9a-fA-F]{6}$/;

/** `"#rrggbb"` (either case) → `0xrrggbb`; anything else (other lengths, `#rgb`, no `#`, non-strings) → `null`. */
export function parse_display_color(value: unknown): number | null {
  return typeof value === "string" && HEX6.test(value) ? parseInt(value.slice(1), 16) : null;
}

/** `0xrrggbb` → `"#rrggbb"` (lower case), the form the downloaded scene carries. */
export function display_color_text(colour: number): string {
  return "#" + colour.toString(16).padStart(6, "0");
}

/**
 * The valid display colours of a raw (unvalidated) scene, keyed by object id: entries of `raw.objects` that are
 * objects with a string `id` and a valid `display_color`. Anything else (no `objects` array, non-object entries,
 * missing or non-string ids, missing or invalid colours) is skipped silently — it never fails a load. Ids are not
 * checked against the scene: an id the validated scene does not have is never looked up.
 */
export function display_colours(raw: unknown): Map<string, number> {
  const out = new Map<string, number>();
  if (raw === null || typeof raw !== "object") return out;
  const objects = (raw as { objects?: unknown }).objects;
  if (!Array.isArray(objects)) return out;
  for (const o of objects) {
    if (o === null || typeof o !== "object" || Array.isArray(o)) continue;
    const { id, [DISPLAY_COLOR_KEY]: value } = o as Record<string, unknown>;
    const colour = parse_display_color(value);
    if (typeof id === "string" && colour !== null) out.set(id, colour);
  }
  return out;
}

/** `display_colours(JSON.parse(text))`; text that is not JSON gives an empty map (the loader reports the error). */
export function display_colours_text(text: string): Map<string, number> {
  try {
    return display_colours(JSON.parse(text));
  } catch {
    return new Map();
  }
}

/** The colour object `i` (id `id`) is drawn with: its display colour when `colours` has one, else `PALETTE[i % 8]`. */
export function object_colour(id: string, i: number, colours?: ReadonlyMap<string, number>): number {
  return colours?.get(id) ?? PALETTE[i % PALETTE.length]!;
}
