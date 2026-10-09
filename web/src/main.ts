/**
 * The castplane web UI (contract §5.4.10): load a scene JSON (file picker, page-wide drag and drop, bundled
 * examples), show it with three.js, drag the camera, and overlay the SVG the ported core writes for that camera —
 * re-rendered per animation frame with stage A cached. No server, no network access at runtime.
 *
 * This module owns the state, loading and the render loop, and wires the others: `stage.ts` (one three.js view),
 * `input.ts` (pointer / wheel / file-drop gestures), `ui.ts` (controls and panels), `overlay.ts` (the SVG overlay).
 */

import "./style.css";

import * as THREE from "three";

import { LAYER_IDS, compose, dumps, load_scene, load_scene_text, project_scene, shadow_geometry, write_svg } from "castplane";
import type { GeometryDocument, Scene, StageA } from "castplane";

import { EXAMPLES } from "./examples.js";
import { camera_block_text, json_blob, ordered_layers, scene_blob, svg_blob } from "./download.js";
import { attach_drag_input, attach_file_drop } from "./input.js";
import {
  camera_from_orbit, focal_from_slider, orbit_from_camera, pan_orbit, rotate_orbit, set_focal, set_roll, zoom_orbit,
} from "./orbit.js";
import type { OrbitState } from "./orbit.js";
import { IMG_MODE_THRESHOLD, Overlay } from "./overlay.js";
import type { OverlayMode } from "./overlay.js";
import { build_scene3d } from "./scene3d.js";
import { Stage3D, letterbox } from "./stage.js";
import {
  $, WarningsTable, build_layer_boxes, controls, describe_error, fill_examples, focal_text, roll_text, save,
  set_error_panel, set_lens_sliders, status_text, umbra_count,
} from "./ui.js";

THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

interface FrameRecord {
  core_ms: number;
  dom_ms: number;
  mode: OverlayMode;
  dragging: boolean;
  svg_bytes: number;
}

interface State {
  scene: Scene | null;
  sceneName: string;
  A: StageA | null;
  orbit: OrbitState | null;
  layersChecked: Set<string>;
  doc: GeometryDocument | null;
  svg: string;
  timings: { stage_a_ms: number; core_ms: number; dom_ms: number; mode: OverlayMode };
  dragging: boolean;
  dirty: boolean;
  full_svg_length: number;
  frames: FrameRecord[];
}

const state: State = {
  scene: null,
  sceneName: "",
  A: null,
  orbit: null,
  layersChecked: new Set(LAYER_IDS),
  doc: null,
  svg: "",
  timings: { stage_a_ms: 0, core_ms: 0, dom_ms: 0, mode: "dom" },
  dragging: false,
  dirty: false,
  full_svg_length: 0,
  frames: [],
};

const ui = controls();
const { viewport, stage, canvas, examplesSelect, fileInput, focalInput, focalOut, rollInput, rollOut, view3d, hiddenLines, hiddenStyle } = ui;

// ---------------------------------------------------------------------------- three.js and overlay
const view = new Stage3D(canvas);
const overlay = new Overlay(stage);
const warnings = new WarningsTable(ui.warningsBody);

// ---------------------------------------------------------------------------- layer checkboxes
const layerBoxes = build_layer_boxes(ui.layersBox, LAYER_IDS, (id, checked) => {
  if (checked) state.layersChecked.add(id);
  else state.layersChecked.delete(id);
  overlay.set_hidden_layers(state.layersChecked);
  if (overlay.mode === "img") request_render();
});

function show_error(message: string | null): void {
  set_error_panel(ui.errorPanel, message);
}

// ---------------------------------------------------------------------------- loading
function load(name: string, make: () => Scene): boolean {
  let scene: Scene;
  let A: StageA;
  let stage_a_ms: number;
  try {
    scene = make();
    const t0 = performance.now();
    A = shadow_geometry(scene);
    stage_a_ms = performance.now() - t0;
  } catch (e) {
    show_error(describe_error(e)); // the previous scene stays
    return false;
  }
  show_error(null);
  state.scene = scene;
  state.sceneName = name;
  state.A = A;
  state.timings.stage_a_ms = stage_a_ms;
  state.orbit = orbit_from_camera(scene.camera, scene);
  state.full_svg_length = 0;
  state.frames = [];
  view.replace_group(() => build_scene3d(scene, A));
  state.layersChecked = new Set(scene.output.layers);
  for (const [id, box] of layerBoxes) box.checked = state.layersChecked.has(id);
  overlay.set_hidden_layers(state.layersChecked);
  hiddenLines.checked = scene.output.hidden_lines === true;
  hiddenStyle.value = scene.output.hidden_style ?? "dashed";
  hiddenStyle.disabled = !hiddenLines.checked;
  sync_sliders();
  layout();
  document.title = `${name} — castplane web`;
  request_render();
  return true;
}

function load_text(name: string, text: string): boolean {
  const ok = load(name, () => load_scene_text(text));
  if (ok) examplesSelect.value = "";
  return ok;
}

function load_file(file: File): void {
  const looks_json = /\.json$/i.test(file.name) || file.type === "application/json";
  if (!looks_json) {
    show_error(`${file.name}: not a JSON file`);
    return;
  }
  file.text().then(
    (text) => load_text(file.name.replace(/\.json$/i, ""), text),
    (e) => show_error(`${file.name}: ${describe_error(e)}`),
  );
}

fill_examples(examplesSelect, EXAMPLES.map((e) => e.name));
examplesSelect.addEventListener("change", () => {
  const ex = EXAMPLES.find((e) => e.name === examplesSelect.value);
  if (ex !== undefined) load(ex.name, () => load_scene(ex.data));
});
fileInput.addEventListener("change", () => {
  const f = fileInput.files?.[0];
  if (f !== undefined) load_file(f);
  fileInput.value = "";
});
attach_file_drop(viewport, load_file);

// ---------------------------------------------------------------------------- sliders and buttons
function sync_sliders(): void {
  if (state.orbit === null) return;
  set_lens_sliders(ui, state.orbit);
}

focalInput.addEventListener("input", () => {
  if (state.orbit === null) return;
  state.orbit = set_focal(state.orbit, focal_from_slider(Number(focalInput.value)));
  focalOut.value = focal_text(state.orbit);
  request_render();
});
rollInput.addEventListener("input", () => {
  if (state.orbit === null) return;
  state.orbit = set_roll(state.orbit, Number(rollInput.value));
  rollOut.value = roll_text(state.orbit);
  request_render();
});
$<HTMLButtonElement>("reset").addEventListener("click", () => {
  if (state.scene === null) return;
  state.orbit = orbit_from_camera(state.scene.camera, state.scene);
  sync_sliders();
  request_render();
});
// phase 2 of §5.4.10: the hidden-line switch, passed as `hidden_lines` to `compose`, and the hidden style, passed as
// `hidden_style` to `write_svg` ("dashed" | "omit", §5.1.8); both initialised from the scene's `output`
hiddenLines.addEventListener("change", () => {
  hiddenStyle.disabled = !hiddenLines.checked;
  request_render();
});
hiddenStyle.addEventListener("change", () => request_render());

/** The selected hidden style (`write_svg`'s third argument). */
function hidden_style(): "dashed" | "omit" {
  return hiddenStyle.value === "omit" ? "omit" : "dashed";
}
view3d.addEventListener("change", () => {
  canvas.classList.toggle("hidden", !view3d.checked);
  request_render();
});

$<HTMLButtonElement>("dl-svg").addEventListener("click", () => {
  if (state.doc !== null) save(svg_blob(state.doc, state.layersChecked, state.sceneName, hidden_style()));
});
$<HTMLButtonElement>("dl-json").addEventListener("click", () => {
  if (state.doc !== null) save(json_blob(state.doc, state.sceneName));
});
$<HTMLButtonElement>("dl-scene").addEventListener("click", () => {
  if (state.scene !== null && state.orbit !== null) save(scene_blob(state.scene, camera_from_orbit(state.orbit, state.scene.camera), state.sceneName, hiddenLines.checked, hidden_style()));
});
$<HTMLButtonElement>("copy-camera").addEventListener("click", () => {
  if (state.scene === null || state.orbit === null) return;
  const text = camera_block_text(camera_from_orbit(state.orbit, state.scene.camera));
  navigator.clipboard.writeText(text).then(
    () => show_error(null),
    (e) => show_error(`clipboard unavailable (${describe_error(e)}); camera block:\n${text}`),
  );
});

// ---------------------------------------------------------------------------- pointer input (state only)
attach_drag_input(stage, {
  ready: () => state.orbit !== null && state.scene !== null,
  start: () => {
    state.dragging = true;
  },
  drag: (dx, dy, pan, H_px) => {
    if (state.orbit === null || state.scene === null) return;
    state.orbit = pan
      ? pan_orbit(state.orbit, dx, dy, H_px, state.scene.camera, state.scene.output.canvas_mm)
      : rotate_orbit(state.orbit, dx, dy, H_px);
    request_render();
  },
  end: () => {
    state.dragging = false;
    request_render(); // the resting frame (DOM overlay)
  },
  wheel: (deltaY) => {
    if (state.orbit === null) return;
    state.orbit = zoom_orbit(state.orbit, deltaY);
    request_render();
  },
});

// ---------------------------------------------------------------------------- layout (letterboxed to canvas_mm)
function layout(): void {
  const aspect = state.scene ? state.scene.output.canvas_mm[0] / state.scene.output.canvas_mm[1] : 3 / 2;
  const [w, h] = letterbox(viewport, stage, aspect);
  view.set_size(w, h);
}
new ResizeObserver(() => {
  layout();
  request_render();
}).observe(viewport);

// ---------------------------------------------------------------------------- render loop
let rafPending = false;

/** Mark the state dirty and schedule one animation frame (pointer events coalesce: the latest camera wins). */
function request_render(): void {
  state.dirty = true;
  if (!rafPending) {
    rafPending = true;
    requestAnimationFrame(frame);
  }
}

function frame(): void {
  rafPending = false;
  if (!state.dirty || state.scene === null || state.A === null || state.orbit === null) return;
  state.dirty = false;
  const scene = state.scene;
  const cam = camera_from_orbit(state.orbit, scene.camera);
  const img_mode = state.dragging && state.full_svg_length > IMG_MODE_THRESHOLD;
  let doc: GeometryDocument, svg: string;
  const t0 = performance.now();
  try {
    const B = project_scene(scene, state.A, cam, !state.dragging);
    // hidden lines are skipped during a drag (§5.4.11: a documented switch whose off state is a contract document);
    // the resting frame recomputes them
    doc = compose(scene, B, hiddenLines.checked && !state.dragging);
    // all six layers with CSS visibility (DOM mode); the checked subset in <img> mode
    svg = write_svg(doc, img_mode ? ordered_layers(state.layersChecked) : LAYER_IDS, hidden_style());
  } catch (e) {
    show_error(describe_error(e));
    return;
  }
  const t1 = performance.now();
  if (img_mode) overlay.set_img(svg);
  else overlay.set_svg(svg);
  const t2 = performance.now();
  if (!img_mode) state.full_svg_length = svg.length;
  state.doc = doc;
  state.svg = svg;
  if (view3d.checked) view.render(cam, scene.output.canvas_mm, state.A.scene_scale);
  warnings.update(doc);
  state.timings.core_ms = t1 - t0;
  state.timings.dom_ms = t2 - t1;
  state.timings.mode = overlay.mode;
  state.frames.push({ core_ms: t1 - t0, dom_ms: t2 - t1, mode: overlay.mode, dragging: state.dragging, svg_bytes: svg.length });
  if (state.frames.length > 500) state.frames.shift();
  ui.statusLine.textContent = status_text(state.sceneName, state.timings, overlay.mode, doc, scene, cam);
}

// ---------------------------------------------------------------------------- start
/** Hooks for the smoke test and for measuring `core ms` / `dom ms` (web/README.md); `load_example`, `load_text` and
 * `set_hidden` act as the UI controls would, the rest is read-only. */
(window as unknown as { castplane_web: unknown }).castplane_web = {
  examples: EXAMPLES.map((e) => e.name),
  load_example: (name: string) => {
    const ex = EXAMPLES.find((e) => e.name === name);
    if (ex === undefined) throw new Error(`unknown example ${name}`);
    examplesSelect.value = name;
    return load(name, () => load_scene(ex.data)); // false: the error panel shows why, the previous scene stays
  },
  load_text,
  get frames() { return state.frames.slice(); },
  get timings() { return { ...state.timings }; },
  get camera() { return state.orbit && state.scene ? camera_from_orbit(state.orbit, state.scene.camera) : null; },
  get svg_length() { return state.svg.length; },
  /** The UI's hidden-line state: the checkbox and the style select. */
  get hidden() { return { lines: hiddenLines.checked, style: hidden_style() }; },
  /** Set the hidden-line checkbox and style as a user would (fires their change handlers). */
  set_hidden: (lines: boolean, style?: "dashed" | "omit") => {
    hiddenLines.checked = lines;
    hiddenLines.dispatchEvent(new Event("change"));
    if (style !== undefined) {
      hiddenStyle.value = style;
      hiddenStyle.dispatchEvent(new Event("change"));
    }
  },
  /** The names of the 3D view's objects (`<object id>`, `light:<id>`, `receiver:<id>`, `outline:<id>`, `grid:<id>`). */
  get scene3d_names() { const g = view.group; return g === null ? [] : g.children.map((c) => c.name).filter((n) => n !== ""); },
  get doc_summary() {
    const d = state.doc;
    if (d === null) return null;
    return {
      hidden_lines: d.hidden_lines,
      hidden_edge_runs: d.edges.reduce((n, e) => n + e.runs.filter((r) => !r.visible).length, 0),
      receivers: d.receivers.map((r) => r.id),
      constructions: d.constructions === undefined ? [] : Object.keys(d.constructions),
      umbra_pieces: umbra_count(d),
    };
  },
  /** The scene camera's SVG / JSON through the bundled core (`project_scene(scene, A)` with no override). */
  reference_render: () => {
    if (state.scene === null || state.A === null) return null;
    const doc = compose(state.scene, project_scene(state.scene, state.A));
    return { name: state.sceneName, svg: write_svg(doc, state.scene.output.layers, state.scene.output.hidden_style ?? "dashed"),
      json: dumps(doc) };
  },
};

layout();
const first = EXAMPLES.find((e) => e.name === "basic") ?? EXAMPLES[0];
if (first !== undefined) {
  examplesSelect.value = first.name;
  load(first.name, () => load_scene(first.data));
}
