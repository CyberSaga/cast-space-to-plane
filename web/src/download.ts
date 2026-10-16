/**
 * The downloads of the web UI (contract §5.4.10) — pure, DOM-free, unit-tested (`web/test/orbit.test.ts`).
 *
 * Every function returns the file's name, MIME type and text; `main.ts` wraps the text in a `Blob`. What is
 * downloaded is exactly what is shown: the SVG writer's output for the checked layers, the spec §6.2 document of
 * the current frame, and the loaded scene with the current camera block.
 */

import { LAYER_ORDER, dumps, write_svg } from "castplane";
import type { Camera, GeometryDocument, Scene, SceneObject } from "castplane";

import { DISPLAY_COLOR_KEY, display_color_text } from "./colours.js";
import type { TargetCamera } from "./orbit.js";

export interface DownloadFile {
  filename: string;
  type: string;
  text: string;
}

export const SVG_MIME = "image/svg+xml";
export const JSON_MIME = "application/json";

/** The checked layers in §2.10 order (unknown ids dropped). */
export function ordered_layers(checked: Iterable<string>): string[] {
  const set = new Set(checked);
  return LAYER_ORDER.filter((id) => set.has(id));
}

/** `write_svg(doc, layers, hidden_style)` with the checked layers in §2.10 order → `<sceneName>.svg` (`hidden_style`: the
 * UI's "Hidden style" select, initialised from the scene's `output.hidden_style`; used only by a document with hidden
 * lines on, §5.1.8). */
export function svg_blob(doc: GeometryDocument, layers: Iterable<string>, sceneName: string, hidden_style = "dashed"): DownloadFile {
  return { filename: `${sceneName}.svg`, type: SVG_MIME, text: write_svg(doc, ordered_layers(layers), hidden_style) };
}

/** `dumps(doc) + "\n"` (the spec §6.2 document) → `<sceneName>.json`. */
export function json_blob(doc: GeometryDocument, sceneName: string): DownloadFile {
  return { filename: `${sceneName}.json`, type: JSON_MIME, text: dumps(doc) + "\n" };
}

/**
 * `dumps({...scene, camera: cam}) + "\n"` → `<sceneName>.scene.json`: the loaded scene with the explicit target-form
 * block of `camera_from_orbit` (or, in M9, an unedited `picture_plane` scene camera as it is, §5.6 notes), so the result never carries both camera forms and the Python CLI reproduces the
 * picture (`castplane render x.scene.json -o out`). `hidden_lines` (the UI checkbox) and `hidden_style` (the UI select,
 * phase 2 of §5.4.10), when given, are written as `output.hidden_lines` / `output.hidden_style` for the same reason.
 * `colours` (the loaded raw scene's display colours by object id, `colours.ts::display_colours`): each object of the
 * scene that has one gets it back as `display_color: "#rrggbb"` (lower case), so the file reloads with the same 3D
 * colours; the core ignores the key (§2.0), so the CLI's output is that of the file without it.
 * A `mesh` object (§5.2.1) is written so that the Python validator accepts it (`mesh_object_for_file`): `data.faces`,
 * `data.smooth_groups` and an integer `node` as JSON integers, and `path` / `node` left out when null. A scene without
 * mesh objects is `dumps({...scene, objects, camera, output}) + "\n"`, as before.
 */
export function scene_blob(scene: Scene, cam: TargetCamera | Camera, sceneName: string, hidden_lines?: boolean,
  hidden_style?: "dashed" | "omit", colours?: ReadonlyMap<string, number>): DownloadFile {
  const output = { ...scene.output };
  if (hidden_lines !== undefined) output.hidden_lines = hidden_lines;
  if (hidden_style !== undefined) output.hidden_style = hidden_style;
  const ints = new IntSlots();
  const objects = scene.objects.map((o) => {
    const colour = colours?.get(o.id);
    const obj = o.type === "mesh" ? mesh_object_for_file(o, ints) : o;
    return colour === undefined ? obj : { ...obj, [DISPLAY_COLOR_KEY]: display_color_text(colour) };
  });
  return { filename: `${sceneName}.scene.json`, type: JSON_MIME, text: ints.fill(dumps({ ...scene, objects, camera: cam, output })) + "\n" };
}

/**
 * Integer values spliced into a `dumps` text. `dumps` writes every number as a Python float (`26.0`) except under
 * `INT_KEYS`, but the Python validator wants `int` mesh indices (`castplane.scene._is_index`): `slot(v)` stands for `v`
 * (an integer or a nested list of integers) as a placeholder string, and `fill(text)` replaces each placeholder with `v`
 * in `json.dumps(indent=1)` layout at the placeholder's depth (the indentation of its line).
 */
class IntSlots {
  private readonly values: unknown[] = [];
  // U+0000 is written as the escape `\u0000` by `dumps`; the counter makes each placeholder unique
  private readonly tag = "\u0000castplane-int:";

  slot(v: unknown): string {
    this.values.push(v);
    return `${this.tag}${this.values.length - 1}`;
  }

  fill(text: string): string {
    if (this.values.length === 0) return text;
    let n = 0;
    const out = text.replace(/"\\u0000castplane-int:(\d+)"/g, (_m, k: string, at: number) => {
      const line = text.lastIndexOf("\n", at) + 1;
      let depth = 0;
      while (text[line + depth] === " ") depth++;
      n++;
      return int_json(this.values[Number(k)], depth);
    });
    // a scene string equal to a placeholder would be replaced too: refuse rather than write a different scene
    if (n !== this.values.length) throw new Error("scene text holds a reserved placeholder string");
    return out;
  }
}

/** `json.dumps(v, indent=1)` of an integer or a nested list of integers whose first line sits at `depth`. */
function int_json(v: unknown, depth: number): string {
  if (typeof v === "number") {
    if (!Number.isSafeInteger(v)) throw new Error(`not an integer: ${v}`);
    return String(v + 0);
  }
  if (!Array.isArray(v)) throw new Error(`not an integer list: ${typeof v}`);
  if (v.length === 0) return "[]";
  const inner = "\n" + " ".repeat(depth + 1);
  return "[" + inner + v.map((x) => int_json(x, depth + 1)).join("," + inner) + "\n" + " ".repeat(depth) + "]";
}

/** A validated `mesh` object as the scene file writes it (contract §5.2.1): `data.faces`, `data.smooth_groups` and an
 * integer `node` through `ints` (JSON integers), and the loader keys `path` / `node` dropped when null (the validators
 * read a missing key as null). */
function mesh_object_for_file(o: SceneObject, ints: IntSlots): Record<string, unknown> {
  const out: Record<string, unknown> = { ...o };
  if (o.path == null) delete out.path;
  if (o.node == null) delete out.node;
  else if (typeof o.node === "number") out.node = ints.slot(o.node);
  if (o.data !== undefined) {
    out.data = { ...o.data, faces: ints.slot(o.data.faces), smooth_groups: ints.slot(o.data.smooth_groups) };
  }
  return out;
}

/** The text of "Copy camera block": the current block as deterministic JSON. */
export function camera_block_text(cam: TargetCamera | Camera): string {
  return dumps(cam) + "\n";
}
