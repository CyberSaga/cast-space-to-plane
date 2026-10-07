/**
 * The castplane web UI (contract §5.4.10): load a scene JSON (file picker, page-wide drag and drop, bundled
 * examples), show it with three.js, drag the camera, and overlay the SVG the ported core writes for that camera —
 * re-rendered per animation frame with stage A cached. No server, no network access at runtime.
 */

import "./style.css";

import * as THREE from "three";

import { LAYER_IDS, SceneError, compose, dumps, load_scene, load_scene_text, project_scene, shadow_geometry, write_svg } from "castplane";
import type { GeometryDocument, Scene, StageA } from "castplane";

import { EXAMPLES } from "./examples.js";
import { camera_block_text, json_blob, ordered_layers, scene_blob, svg_blob } from "./download.js";
import type { DownloadFile } from "./download.js";
import {
  camera_from_orbit, focal_from_slider, orbit_from_camera, pan_orbit, rotate_orbit, set_focal, set_roll, slider_from_focal,
  zoom_orbit,
} from "./orbit.js";
import type { OrbitState } from "./orbit.js";
import { IMG_MODE_THRESHOLD, Overlay } from "./overlay.js";
import type { OverlayMode } from "./overlay.js";
import { build_scene3d, dispose_scene3d } from "./scene3d.js";
import { apply_camera_block } from "./threeCamera.js";

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

const $ = <T extends HTMLElement>(id: string): T => {
  const el = document.getElementById(id);
  if (el === null) throw new Error(`missing #${id}`);
  return el as T;
};

const viewport = $<HTMLElement>("viewport");
const stage = $<HTMLDivElement>("stage");
const canvas = $<HTMLCanvasElement>("gl");
const examplesSelect = $<HTMLSelectElement>("examples");
const fileInput = $<HTMLInputElement>("file");
const focalInput = $<HTMLInputElement>("focal");
const focalOut = $<HTMLOutputElement>("focal-out");
const rollInput = $<HTMLInputElement>("roll");
const rollOut = $<HTMLOutputElement>("roll-out");
const layersBox = $<HTMLSpanElement>("layers");
const view3d = $<HTMLInputElement>("view3d");
const statusLine = $<HTMLDivElement>("status");
const errorPanel = $<HTMLDivElement>("error");
const warningsBody = $<HTMLTableElement>("warnings").tBodies[0]!;

// ---------------------------------------------------------------------------- three.js
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.shadowMap.enabled = false; // normative (§5.4.0): shadows come only from the ported core
renderer.setPixelRatio(window.devicePixelRatio || 1);
const scene3 = new THREE.Scene();
scene3.background = new THREE.Color(0xffffff);
const camera3 = new THREE.PerspectiveCamera();
let group3: THREE.Group | null = null;

const overlay = new Overlay(stage);

// ---------------------------------------------------------------------------- layer checkboxes
const layerBoxes = new Map<string, HTMLInputElement>();
for (const id of LAYER_IDS) {
  const label = document.createElement("label");
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = true;
  box.dataset["layer"] = id;
  box.addEventListener("change", () => {
    if (box.checked) state.layersChecked.add(id);
    else state.layersChecked.delete(id);
    overlay.set_hidden_layers(state.layersChecked);
    if (overlay.mode === "img") request_render();
  });
  label.append(box, document.createTextNode(id));
  layersBox.append(label);
  layerBoxes.set(id, box);
}

// ---------------------------------------------------------------------------- errors
function show_error(message: string | null): void {
  errorPanel.hidden = message === null;
  errorPanel.textContent = message ?? "";
}

function describe_error(e: unknown): string {
  if (e instanceof SceneError) return `SceneError\nfield: ${e.field === "" ? "(document)" : e.field}\n${e.detail}`;
  return e instanceof Error ? `${e.name}: ${e.message}` : String(e);
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
  if (group3 !== null) {
    scene3.remove(group3);
    dispose_scene3d(group3);
  }
  group3 = build_scene3d(scene, A);
  scene3.add(group3);
  state.layersChecked = new Set(scene.output.layers);
  for (const [id, box] of layerBoxes) box.checked = state.layersChecked.has(id);
  overlay.set_hidden_layers(state.layersChecked);
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

for (const ex of EXAMPLES) {
  const opt = document.createElement("option");
  opt.value = ex.name;
  opt.textContent = ex.name;
  examplesSelect.append(opt);
}
examplesSelect.addEventListener("change", () => {
  const ex = EXAMPLES.find((e) => e.name === examplesSelect.value);
  if (ex !== undefined) load(ex.name, () => load_scene(ex.data));
});
fileInput.addEventListener("change", () => {
  const f = fileInput.files?.[0];
  if (f !== undefined) load_file(f);
  fileInput.value = "";
});
window.addEventListener("dragover", (ev) => {
  ev.preventDefault();
  viewport.classList.add("dragover");
});
window.addEventListener("dragleave", (ev) => {
  if (ev.relatedTarget === null) viewport.classList.remove("dragover");
});
window.addEventListener("drop", (ev) => {
  ev.preventDefault();
  viewport.classList.remove("dragover");
  const f = ev.dataTransfer?.files?.[0];
  if (f !== undefined) load_file(f);
});

// ---------------------------------------------------------------------------- sliders and buttons
function sync_sliders(): void {
  if (state.orbit === null) return;
  focalInput.value = String(slider_from_focal(state.orbit.focal_length_mm));
  focalOut.value = `${state.orbit.focal_length_mm.toFixed(1)} mm`;
  rollInput.value = String(state.orbit.roll_deg);
  rollOut.value = `${state.orbit.roll_deg.toFixed(1)}°`;
}

focalInput.addEventListener("input", () => {
  if (state.orbit === null) return;
  state.orbit = set_focal(state.orbit, focal_from_slider(Number(focalInput.value)));
  focalOut.value = `${state.orbit.focal_length_mm.toFixed(1)} mm`;
  request_render();
});
rollInput.addEventListener("input", () => {
  if (state.orbit === null) return;
  state.orbit = set_roll(state.orbit, Number(rollInput.value));
  rollOut.value = `${state.orbit.roll_deg.toFixed(1)}°`;
  request_render();
});
$<HTMLButtonElement>("reset").addEventListener("click", () => {
  if (state.scene === null) return;
  state.orbit = orbit_from_camera(state.scene.camera, state.scene);
  sync_sliders();
  request_render();
});
view3d.addEventListener("change", () => {
  canvas.classList.toggle("hidden", !view3d.checked);
  request_render();
});

function save(file: DownloadFile): void {
  const url = URL.createObjectURL(new Blob([file.text], { type: file.type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = file.filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$<HTMLButtonElement>("dl-svg").addEventListener("click", () => {
  if (state.doc !== null) save(svg_blob(state.doc, state.layersChecked, state.sceneName));
});
$<HTMLButtonElement>("dl-json").addEventListener("click", () => {
  if (state.doc !== null) save(json_blob(state.doc, state.sceneName));
});
$<HTMLButtonElement>("dl-scene").addEventListener("click", () => {
  if (state.scene !== null && state.orbit !== null) save(scene_blob(state.scene, camera_from_orbit(state.orbit, state.scene.camera), state.sceneName));
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
let pointer: { id: number; x: number; y: number; pan: boolean } | null = null;

stage.addEventListener("contextmenu", (ev) => ev.preventDefault());
stage.addEventListener("pointerdown", (ev) => {
  if (state.orbit === null || pointer !== null) return;
  pointer = { id: ev.pointerId, x: ev.clientX, y: ev.clientY, pan: ev.button === 2 || ev.shiftKey };
  stage.setPointerCapture(ev.pointerId);
  state.dragging = true;
  ev.preventDefault();
});
stage.addEventListener("pointermove", (ev) => {
  if (pointer === null || ev.pointerId !== pointer.id || state.orbit === null || state.scene === null) return;
  const dx = ev.clientX - pointer.x, dy = ev.clientY - pointer.y;
  pointer.x = ev.clientX;
  pointer.y = ev.clientY;
  if (dx === 0 && dy === 0) return;
  const H_px = stage.clientHeight || 1;
  state.orbit = pointer.pan
    ? pan_orbit(state.orbit, dx, dy, H_px, state.scene.camera, state.scene.output.canvas_mm)
    : rotate_orbit(state.orbit, dx, dy, H_px);
  request_render();
});
function end_drag(ev: PointerEvent): void {
  if (pointer === null || ev.pointerId !== pointer.id) return;
  pointer = null;
  state.dragging = false;
  request_render(); // the resting frame (DOM overlay)
}
stage.addEventListener("pointerup", end_drag);
stage.addEventListener("pointercancel", end_drag);
stage.addEventListener("wheel", (ev) => {
  if (state.orbit === null) return;
  ev.preventDefault();
  state.orbit = zoom_orbit(state.orbit, ev.deltaY);
  request_render();
}, { passive: false });

// ---------------------------------------------------------------------------- layout (letterboxed to canvas_mm)
function layout(): void {
  const aspect = state.scene ? state.scene.output.canvas_mm[0] / state.scene.output.canvas_mm[1] : 3 / 2;
  const W = viewport.clientWidth - 16, H = viewport.clientHeight - 16;
  let w = W, h = W / aspect;
  if (h > H) {
    h = H;
    w = H * aspect;
  }
  w = Math.max(1, Math.floor(w));
  h = Math.max(1, Math.floor(w / aspect));
  stage.style.width = `${w}px`;
  stage.style.height = `${h}px`;
  renderer.setSize(w, h, false);
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
    doc = compose(scene, B);
    // all six layers with CSS visibility (DOM mode); the checked subset in <img> mode
    svg = write_svg(doc, img_mode ? ordered_layers(state.layersChecked) : LAYER_IDS);
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
  if (view3d.checked) {
    apply_camera_block(camera3, cam, scene.output.canvas_mm, state.A.scene_scale);
    renderer.render(scene3, camera3);
  }
  update_warnings(doc);
  state.timings.core_ms = t1 - t0;
  state.timings.dom_ms = t2 - t1;
  state.timings.mode = overlay.mode;
  state.frames.push({ core_ms: t1 - t0, dom_ms: t2 - t1, mode: overlay.mode, dragging: state.dragging, svg_bytes: svg.length });
  if (state.frames.length > 500) state.frames.shift();
  statusLine.textContent =
    `${state.sceneName}: stage A ${state.timings.stage_a_ms.toFixed(1)} ms (cached)\n` +
    `core ms ${state.timings.core_ms.toFixed(1)} · dom ms ${state.timings.dom_ms.toFixed(1)} · overlay ${overlay.mode}\n` +
    `points ${Object.keys(doc.points).length} · edges ${doc.edges.length} · rays ${doc.construction.rays.length}\n` +
    `camera (${cam.position.map((x) => x.toFixed(2)).join(", ")}) → (${cam.target.map((x) => x.toFixed(2)).join(", ")}), ` +
    `f ${cam.focal_length_mm.toFixed(1)} mm, roll ${cam.roll_deg.toFixed(1)}°`;
}

let lastWarnings = "";
function update_warnings(doc: GeometryDocument): void {
  const key = JSON.stringify(doc.warnings);
  if (key === lastWarnings) return;
  lastWarnings = key;
  warningsBody.replaceChildren(
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
    warningsBody.append(tr);
  }
}

// ---------------------------------------------------------------------------- start
/** Read-only hooks for the smoke test and for measuring `core ms` / `dom ms` (web/README.md). */
(window as unknown as { castplane_web: unknown }).castplane_web = {
  examples: EXAMPLES.map((e) => e.name),
  load_example: (name: string) => {
    const ex = EXAMPLES.find((e) => e.name === name);
    if (ex === undefined) throw new Error(`unknown example ${name}`);
    examplesSelect.value = name;
    load(name, () => load_scene(ex.data));
  },
  load_text,
  get frames() { return state.frames.slice(); },
  get timings() { return { ...state.timings }; },
  get camera() { return state.orbit && state.scene ? camera_from_orbit(state.orbit, state.scene.camera) : null; },
  get svg_length() { return state.svg.length; },
  /** The scene camera's SVG / JSON through the bundled core (`project_scene(scene, A)` with no override). */
  reference_render: () => {
    if (state.scene === null || state.A === null) return null;
    const doc = compose(state.scene, project_scene(state.scene, state.A));
    return { svg: write_svg(doc, state.scene.output.layers), json: dumps(doc) };
  },
};

layout();
const first = EXAMPLES.find((e) => e.name === "basic") ?? EXAMPLES[0];
if (first !== undefined) {
  examplesSelect.value = first.name;
  load(first.name, () => load_scene(first.data));
}
