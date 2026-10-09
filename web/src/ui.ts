/**
 * The page's controls and panels (contract §5.4.10; M10 §5.7.9): element lookup by id, the layer checkboxes, the
 * examples menu, the plane-mode controls (focal / D / roll sliders, equation field, views, readouts), the error panel,
 * the warnings table, the status line and the file save. No application state lives here; `main.ts` owns the state
 * and passes it in.
 */

import { SceneError } from "castplane";
import type { CameraRecord, GeometryDocument, Scene } from "castplane";

import type { DownloadFile } from "./download.js";
import { slider_from_focal } from "./orbit.js";
import type { OverlayMode } from "./overlay.js";
import type { RigState } from "./rig.js";

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
  /** M10 (contract §5.7.9): the D slider, the plane-mode checkboxes, the pivot selector, the views, the equation field,
   * undo, the readouts and the notices. */
  distInput: HTMLInputElement;
  distOut: HTMLOutputElement;
  snap: HTMLInputElement;
  construction: HTMLInputElement;
  lockLevel: HTMLInputElement;
  pivotMode: HTMLSelectElement;
  views: HTMLDivElement;
  equation: HTMLInputElement;
  equationApply: HTMLButtonElement;
  equationError: HTMLSpanElement;
  quickEquations: HTMLSpanElement;
  undo: HTMLButtonElement;
  reset: HTMLButtonElement;
  readouts: HTMLDivElement;
  notices: HTMLDivElement;
  layersBox: HTMLSpanElement;
  view3d: HTMLInputElement;
  hiddenLines: HTMLInputElement;
  hiddenStyle: HTMLSelectElement;
  statusLine: HTMLDivElement;
  errorPanel: HTMLDivElement;
  warningsBody: HTMLTableSectionElement;
  /** M9 (contract §5.6.3): the observer switch, its pane and its controls. */
  panes: HTMLDivElement;
  observerOn: HTMLInputElement;
  observerControls: HTMLSpanElement;
  observerFrame: HTMLButtonElement;
  observerRays: HTMLInputElement;
  observerPane: HTMLElement;
  observerCanvas: HTMLCanvasElement;
  observerLabels: HTMLDivElement;
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
    distInput: $<HTMLInputElement>("dist"),
    distOut: $<HTMLOutputElement>("dist-out"),
    snap: $<HTMLInputElement>("snap"),
    construction: $<HTMLInputElement>("construction"),
    lockLevel: $<HTMLInputElement>("lock-level"),
    pivotMode: $<HTMLSelectElement>("pivot-mode"),
    views: $<HTMLDivElement>("views"),
    equation: $<HTMLInputElement>("equation"),
    equationApply: $<HTMLButtonElement>("equation-apply"),
    equationError: $<HTMLSpanElement>("equation-error"),
    quickEquations: $<HTMLSpanElement>("quick-equations"),
    undo: $<HTMLButtonElement>("undo"),
    reset: $<HTMLButtonElement>("reset"),
    readouts: $<HTMLDivElement>("readouts"),
    notices: $<HTMLDivElement>("notices"),
    layersBox: $<HTMLSpanElement>("layers"),
    view3d: $<HTMLInputElement>("view3d"),
    hiddenLines: $<HTMLInputElement>("hidden-lines"),
    hiddenStyle: $<HTMLSelectElement>("hidden-style"),
    statusLine: $<HTMLDivElement>("status"),
    errorPanel: $<HTMLDivElement>("error"),
    warningsBody: $<HTMLTableElement>("warnings").tBodies[0]!,
    panes: $<HTMLDivElement>("panes"),
    observerOn: $<HTMLInputElement>("observer-on"),
    observerControls: $<HTMLSpanElement>("observer-controls"),
    observerFrame: $<HTMLButtonElement>("observer-frame"),
    observerRays: $<HTMLInputElement>("observer-rays"),
    observerPane: $<HTMLElement>("observer"),
    observerCanvas: $<HTMLCanvasElement>("obs-gl"),
    observerLabels: $<HTMLDivElement>("obs-labels"),
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

// ---------------------------------------------------------------------------- sliders and readouts
export function focal_text(focal_mm: number): string {
  return `${focal_mm.toFixed(1)} mm`;
}

export function dist_text(D: number): string {
  return `${D.toFixed(2)} m`;
}

export function roll_text(roll_deg: number): string {
  return `${roll_deg.toFixed(1)}°`;
}

/** Set the focal, D and roll sliders and their outputs, and the lock checkbox, from the rig (§5.7.8 item 13: undo and
 * reset re-sync them). A slider being dragged keeps its thumb (the clamped value shows in its output). */
export function set_rig_controls(c: Controls, rig: RigState): void {
  const active = document.activeElement;
  if (active !== c.focalInput) c.focalInput.value = String(slider_from_focal(rig.focal));
  c.focalOut.value = focal_text(rig.focal);
  if (active !== c.distInput) c.distInput.value = String(rig.D);
  c.distOut.value = dist_text(rig.D);
  if (active !== c.rollInput) c.rollInput.value = String(rig.roll_deg);
  c.rollOut.value = roll_text(rig.roll_deg);
  c.lockLevel.checked = rig.up === null;
}

/** Replace the children of `box` by one `<div>` per line (only when the text changed). */
export function set_lines(box: HTMLElement, lines: readonly string[]): void {
  const text = lines.join("\n");
  if (box.dataset["text"] === text) return;
  box.dataset["text"] = text;
  box.replaceChildren(...lines.map((l) => {
    const d = document.createElement("div");
    d.textContent = l;
    return d;
  }));
}

/** One button per quick equation (`data-eq` = its text). */
export function fill_quick_equations(box: HTMLElement, texts: readonly string[]): void {
  for (const t of texts) {
    const b = document.createElement("button");
    b.type = "button";
    b.dataset["eq"] = t;
    b.textContent = t.replace("-", "−");
    box.append(b);
  }
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

/** The status line of a rendered frame; `obs_ms` (the observer's per-frame cost, §5.6.3) only while the switch is on.
 * The camera line reads the record of the rendered block (`C`, `forward`) and its form. */
export function status_text(
  sceneName: string, timings: { stage_a_ms: number; core_ms: number; dom_ms: number }, mode: OverlayMode,
  doc: GeometryDocument, scene: Scene, rec: CameraRecord, focal_mm: number, form: string, obs_ms: number | null = null,
): string {
  return `${sceneName}: stage A ${timings.stage_a_ms.toFixed(1)} ms (cached)\n` +
    `core ms ${timings.core_ms.toFixed(1)} · dom ms ${timings.dom_ms.toFixed(1)}` +
    (obs_ms === null ? "" : ` · obs ms ${obs_ms.toFixed(1)}`) + ` · overlay ${mode}\n` +
    `points ${Object.keys(doc.points).length} · edges ${doc.edges.length} · rays ${ray_count(doc)}` +
    (doc.umbra !== undefined ? ` · umbra pieces ${umbra_count(doc)}` : "") + "\n" +
    `lights ${scene.lights.map((l) => l.id).join(", ")} · receivers ${scene.receivers.map((r) => r.id).join(", ")}\n` +
    `camera (${form}) at (${rec.C.map((x) => x.toFixed(2)).join(", ")}) looking (${rec.forward.map((x) => x.toFixed(3)).join(", ")}), ` +
    `f ${focal_mm.toFixed(1)} mm`;
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
