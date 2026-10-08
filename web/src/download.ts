/**
 * The downloads of the web UI (contract §5.4.10) — pure, DOM-free, unit-tested (`web/test/orbit.test.ts`).
 *
 * Every function returns the file's name, MIME type and text; `main.ts` wraps the text in a `Blob`. What is
 * downloaded is exactly what is shown: the SVG writer's output for the checked layers, the spec §6.2 document of
 * the current frame, and the loaded scene with the current camera block.
 */

import { LAYER_ORDER, dumps, write_svg } from "castplane";
import type { GeometryDocument, Scene } from "castplane";

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
 * block of `camera_from_orbit`, so the result never carries both camera forms and the Python CLI reproduces the
 * picture (`castplane render x.scene.json -o out`). `hidden_lines` (the UI checkbox) and `hidden_style` (the UI select,
 * phase 2 of §5.4.10), when given, are written as `output.hidden_lines` / `output.hidden_style` for the same reason.
 */
export function scene_blob(scene: Scene, cam: TargetCamera, sceneName: string, hidden_lines?: boolean,
  hidden_style?: "dashed" | "omit"): DownloadFile {
  const output = { ...scene.output };
  if (hidden_lines !== undefined) output.hidden_lines = hidden_lines;
  if (hidden_style !== undefined) output.hidden_style = hidden_style;
  return { filename: `${sceneName}.scene.json`, type: JSON_MIME, text: dumps({ ...scene, camera: cam, output }) + "\n" };
}

/** The text of "Copy camera block": the current block as deterministic JSON. */
export function camera_block_text(cam: TargetCamera): string {
  return dumps(cam) + "\n";
}
