/**
 * The page's controls and panels (contract §5.4.10): element lookup by id, the layer checkboxes, the examples
 * menu, the focal / roll sliders' display, the error panel, the warnings table, the status line and the file save.
 * No application state lives here; `main.ts` owns the state and passes it in.
 */

import { SceneError } from "castplane";
import type { GeometryDocument, Scene } from "castplane";

import type { DownloadFile } from "./download.js";
import { slider_from_focal } from "./orbit.js";
import type { OrbitState, TargetCamera } from "./orbit.js";
import type { OverlayMode } from "./overlay.js";

/** The element with id `id` (throws if missing). */
export const $ = <T extends HTMLElement>(id: string): T => {
  const el = document.getElementById(id);
  if (el === null) throw new Error(`missing #${id}`);
  return el as T;
};

/** The elements of `index.html` the UI reads or writes. */
export interface Controls {
  viewport: HTMLElement;
  stage: HTMLDivElement;
  canvas: HTMLCanvasElement;
  examplesSelect: HTMLSelectElement;
  fileInput: HTMLInputElement;
  focalInput: HTMLInputElement;
  focalOut: HTMLOutputElement;
  rollInput: HTMLInputElement;
  rollOut: HTMLOutputElement;
  layersBox: HTMLSpanElement;
  view3d: HTMLInputElement;
  hiddenLines: HTMLInputElement;
  hiddenStyle: HTMLSelectElement;
  statusLine: HTMLDivElement;
  errorPanel: HTMLDivElement;
  warningsBody: HTMLTableSectionElement;
}

export function controls(): Controls {
  return {
    viewport: $<HTMLElement>("viewport"),
    stage: $<HTMLDivElement>("stage"),
    canvas: $<HTMLCanvasElement>("gl"),
    examplesSelect: $<HTMLSelectElement>("examples"),
    fileInput: $<HTMLInputElement>("file"),
    focalInput: $<HTMLInputElement>("focal"),
    focalOut: $<HTMLOutputElement>("focal-out"),
    rollInput: $<HTMLInputElement>("roll"),
    rollOut: $<HTMLOutputElement>("roll-out"),
    layersBox: $<HTMLSpanElement>("layers"),
    view3d: $<HTMLInputElement>("view3d"),
    hiddenLines: $<HTMLInputElement>("hidden-lines"),
    hiddenStyle: $<HTMLSelectElement>("hidden-style"),
    statusLine: $<HTMLDivElement>("status"),
    errorPanel: $<HTMLDivElement>("error"),
    warningsBody: $<HTMLTableElement>("warnings").tBodies[0]!,
  };
}

/** One checked checkbox per layer id in `box` (`data-layer` = id); `on_change(id, checked)` on each toggle. */
export function build_layer_boxes(
  box: HTMLElement, ids: readonly string[], on_change: (id: string, checked: boolean) => void,
): Map<string, HTMLInputElement> {
  const boxes = new Map<string, HTMLInputElement>();
  for (const id of ids) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = true;
    input.dataset["layer"] = id;
    input.addEventListener("change", () => on_change(id, input.checked));
    label.append(input, document.createTextNode(id));
    box.append(label);
    boxes.set(id, input);
  }
  return boxes;
}

/** Append one `<option>` per name to the examples menu. */
export function fill_examples(select: HTMLSelectElement, names: readonly string[]): void {
  for (const name of names) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    select.append(opt);
  }
}

// ---------------------------------------------------------------------------- errors
export function set_error_panel(panel: HTMLElement, message: string | null): void {
  panel.hidden = message === null;
  panel.textContent = message ?? "";
}

export function describe_error(e: unknown): string {
  if (e instanceof SceneError) return `SceneError\nfield: ${e.field === "" ? "(document)" : e.field}\n${e.detail}`;
  return e instanceof Error ? `${e.name}: ${e.message}` : String(e);
}

// ---------------------------------------------------------------------------- sliders
export function focal_text(orbit: OrbitState): string {
  return `${orbit.focal_length_mm.toFixed(1)} mm`;
}

export function roll_text(orbit: OrbitState): string {
  return `${orbit.roll_deg.toFixed(1)}°`;
}

/** Set the focal and roll sliders and their outputs from the orbit state. */
export function set_lens_sliders(c: Controls, orbit: OrbitState): void {
  c.focalInput.value = String(slider_from_focal(orbit.focal_length_mm));
  c.focalOut.value = focal_text(orbit);
  c.rollInput.value = String(orbit.roll_deg);
  c.rollOut.value = roll_text(orbit);
}

// ---------------------------------------------------------------------------- downloads
/** Save `file` through a temporary `<a download>` (the blob URL is revoked a second later). */
export function save(file: DownloadFile): void {
  const url = URL.createObjectURL(new Blob([file.text], { type: file.type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = file.filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------------------------------------------------------------------------- status and warnings
/** Construction rays of every light (`constructions` with N ≥ 2 lights, else `construction`). */
export function ray_count(doc: GeometryDocument): number {
  const blocks = doc.constructions !== undefined ? Object.values(doc.constructions) : [doc.construction];
  return blocks.reduce((n, b) => n + b.rays.length, 0);
}

/** Umbra pieces of the frame (`null` polygons — a drag frame, `umbra = false` — count as none). */
export function umbra_count(doc: GeometryDocument): number {
  return (doc.umbra ?? []).reduce((n, u) => n + (u.polygons?.length ?? 0), 0);
}

/** The status line of a rendered frame. */
export function status_text(
  sceneName: string, timings: { stage_a_ms: number; core_ms: number; dom_ms: number }, mode: OverlayMode,
  doc: GeometryDocument, scene: Scene, cam: TargetCamera,
): string {
  return `${sceneName}: stage A ${timings.stage_a_ms.toFixed(1)} ms (cached)\n` +
    `core ms ${timings.core_ms.toFixed(1)} · dom ms ${timings.dom_ms.toFixed(1)} · overlay ${mode}\n` +
    `points ${Object.keys(doc.points).length} · edges ${doc.edges.length} · rays ${ray_count(doc)}` +
    (doc.umbra !== undefined ? ` · umbra pieces ${umbra_count(doc)}` : "") + "\n" +
    `lights ${scene.lights.map((l) => l.id).join(", ")} · receivers ${scene.receivers.map((r) => r.id).join(", ")}\n` +
    `camera (${cam.position.map((x) => x.toFixed(2)).join(", ")}) → (${cam.target.map((x) => x.toFixed(2)).join(", ")}), ` +
    `f ${cam.focal_length_mm.toFixed(1)} mm, roll ${cam.roll_deg.toFixed(1)}°`;
}

/** The warnings table (`code`, `ids`, `message`); rebuilt only when the warnings change. */
export class WarningsTable {
  private last = "";

  constructor(private readonly body: HTMLTableSectionElement) {}

  update(doc: GeometryDocument): void {
    const key = JSON.stringify(doc.warnings);
    if (key === this.last) return;
    this.last = key;
    this.body.replaceChildren(
      ...doc.warnings.map((w) => {
        const tr = document.createElement("tr");
        for (const text of [w.code, w.ids.join(", "), w.message]) {
          const td = document.createElement("td");
          td.textContent = text;
          tr.append(td);
        }
        return tr;
      }),
    );
    if (doc.warnings.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 3;
      td.textContent = "none";
      tr.append(td);
      this.body.append(tr);
    }
  }
}
