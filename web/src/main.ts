/**
 * The castplane web UI (contract §5.4.10): load a scene JSON (file picker, page-wide drag and drop, bundled
 * examples), show it with three.js, drag the camera, and overlay the SVG the ported core writes for that camera —
 * re-rendered per animation frame with stage A cached. No server, no network access at runtime.
 *
 * This module owns the state, loading and the render loop, and wires the others: `stage.ts` (one three.js view),
 * `input.ts` (pointer / wheel / file-drop gestures), `ui.ts` (controls and panels), `overlay.ts` (the SVG overlay),
 * and, behind the "旁觀視角" switch (M9, contract §5.6), `observer.ts` / `observer3d.ts` (the read-only observer pane).
 */

import "./style.css";

import * as THREE from "three";

import { LAYER_IDS, compose, dumps, load_scene, load_scene_text, project_scene, shadow_geometry, write_svg } from "castplane";
import type { CameraRecord, GeometryDocument, Scene, StageA, Vec3 } from "castplane";

import { EXAMPLES } from "./examples.js";
import { camera_block_text, json_blob, ordered_layers, scene_blob, svg_blob } from "./download.js";
import { attach_drag_input, attach_file_drop } from "./input.js";
import {
  camera_from_orbit, focal_from_slider, orbit_from_camera, pan_orbit, rotate_orbit, set_focal, set_roll, zoom_orbit,
} from "./orbit.js";
import type { OrbitState } from "./orbit.js";
import {
  derive_board, frame_camera_block, frame_view, framing_points, line_art, observer_D, observer_project, orbit_camera,
  scene_centre, vertex_rays,
} from "./observer.js";
import { ObserverPane } from "./observer3d.js";
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
  /** The observer's own cost (geometry + its render), `null` while the switch is off. */
  obs_ms: number | null;
  mode: OverlayMode;
  dragging: boolean;
  svg_bytes: number;
}

interface State {
  scene: Scene | null;
  sceneName: string;
  A: StageA | null;
  orbit: OrbitState | null;
  /** Whether the drawing camera was edited since the load or "Reset camera" (see {@link drawing_block}). */
  camera_edited: boolean;
  layersChecked: Set<string>;
  doc: GeometryDocument | null;
  svg: string;
  timings: { stage_a_ms: number; core_ms: number; dom_ms: number; mode: OverlayMode };
  dragging: boolean;
  dirty: boolean;
  full_svg_length: number;
  frames: FrameRecord[];
  /** The camera record of the last frame (the observer reads it, §5.6.2). */
  rec: CameraRecord | null;
  /** M9 observer (contract §5.6): `D` and the scene centre per loaded scene, whether a framing is pending. */
  obs: { on: boolean; D: number; centre: Vec3; needs_framing: boolean; ms: number | null };
}

const state: State = {
  scene: null,
  sceneName: "",
  A: null,
  orbit: null,
  camera_edited: false,
  layersChecked: new Set(LAYER_IDS),
  doc: null,
  svg: "",
  timings: { stage_a_ms: 0, core_ms: 0, dom_ms: 0, mode: "dom" },
  dragging: false,
  dirty: false,
  full_svg_length: 0,
  frames: [],
  rec: null,
  obs: { on: false, D: 4, centre: [0, 0, 0], needs_framing: true, ms: null },
};

const ui = controls();
const { viewport, stage, canvas, examplesSelect, fileInput, focalInput, focalOut, rollInput, rollOut, view3d, hiddenLines, hiddenStyle } = ui;

/** The block the core renders and the downloads write: an unedited `picture_plane` scene camera as it is, else the M7
 * orbit's target-form block (`frame_camera_block`, §5.6 implementation notes). */
function drawing_block(scene: Scene, orbit: OrbitState): ReturnType<typeof camera_from_orbit> | Scene["camera"] {
  return frame_camera_block(scene.camera, camera_from_orbit(orbit, scene.camera), state.camera_edited);
}

// ---------------------------------------------------------------------------- three.js and overlay
const view = new Stage3D(canvas);
const overlay = new Overlay(stage);
const warnings = new WarningsTable(ui.warningsBody);
/** The observer pane, created on the first switch-on (with the switch off the page is the §5.4.10 page). */
let observer: ObserverPane | null = null;

// ---------------------------------------------------------------------------- layer checkboxes
const layerBoxes = build_layer_boxes(ui.layersBox, LAYER_IDS, (id, checked) => {
  if (checked) state.layersChecked.add(id);
  else state.layersChecked.delete(id);
  overlay.set_hidden_layers(state.layersChecked);
  if (overlay.mode === "img") request_render();
  observer_refresh(true); // the drawing on the frame follows the layer checkboxes
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
  // §5.6.2: a picture_plane camera reaches the M7 orbit as its target form with the pivot at the scene centre's depth
  state.obs.centre = scene_centre(A);
  state.obs.D = observer_D(scene.camera, scene.output.canvas_mm);
  state.obs.needs_framing = true;
  state.orbit = orbit_from_camera(orbit_camera(scene.camera, state.obs.centre), scene);
  state.camera_edited = false;
  state.rec = null;
  state.full_svg_length = 0;
  state.frames = [];
  view.replace_group(() => build_scene3d(scene, A));
  observer?.set_scene(scene, A);
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
  state.camera_edited = true;
  focalOut.value = focal_text(state.orbit);
  request_render();
});
rollInput.addEventListener("input", () => {
  if (state.orbit === null) return;
  state.orbit = set_roll(state.orbit, Number(rollInput.value));
  state.camera_edited = true;
  rollOut.value = roll_text(state.orbit);
  request_render();
});
$<HTMLButtonElement>("reset").addEventListener("click", () => {
  if (state.scene === null) return;
  state.orbit = orbit_from_camera(orbit_camera(state.scene.camera, state.obs.centre), state.scene);
  state.camera_edited = false;
  state.obs.needs_framing = true;
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
  if (state.scene !== null && state.orbit !== null) save(scene_blob(state.scene, drawing_block(state.scene, state.orbit), state.sceneName, hiddenLines.checked, hidden_style()));
});
$<HTMLButtonElement>("copy-camera").addEventListener("click", () => {
  if (state.scene === null || state.orbit === null) return;
  const text = camera_block_text(drawing_block(state.scene, state.orbit));
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
    state.camera_edited = true;
    request_render();
  },
  end: () => {
    state.dragging = false;
    request_render(); // the resting frame (DOM overlay)
  },
  wheel: (deltaY) => {
    if (state.orbit === null) return;
    state.orbit = zoom_orbit(state.orbit, deltaY);
    state.camera_edited = true;
    request_render();
  },
});

// ---------------------------------------------------------------------------- layout (letterboxed to canvas_mm)
function layout(): void {
  const aspect = state.scene ? state.scene.output.canvas_mm[0] / state.scene.output.canvas_mm[1] : 3 / 2;
  const [w, h] = letterbox(viewport, stage, aspect);
  view.set_size(w, h);
  if (state.obs.on && observer !== null) observer.set_size(ui.observerPane.clientWidth, ui.observerPane.clientHeight);
}
const resize = new ResizeObserver(() => {
  layout();
  request_render();
});
resize.observe(viewport);
resize.observe(ui.observerPane);

// ---------------------------------------------------------------------------- observer (M9, contract §5.6)
const OBSERVER_KEY = "castplane.observer";

/** Update the observer from the drawing camera's record and document (§5.6.2, §5.6.5): board, drawing on the frame
 * (checked layers), vertex rays; frame it when a framing is pending and no drag is running (§5.6.4); then draw it.
 * Returns the observer's own cost in ms. Reads `rec` and `doc` only. */
function update_observer(rec: CameraRecord, doc: GeometryDocument): number {
  if (observer === null || state.scene === null || state.orbit === null) return 0;
  const t0 = performance.now();
  const board = derive_board(rec, state.orbit, state.obs.D);
  const art = line_art(doc, rec, state.obs.D, state.layersChecked);
  const rays = ui.observerRays.checked ? vertex_rays(doc, state.scene, board, rec.near) : null;
  if (state.obs.needs_framing && !state.dragging) {
    observer.view = frame_view(observer.view, framing_points(board, state.scene, state.obs.centre), observer.aspect);
    state.obs.needs_framing = false;
  }
  observer.update({ board, art, rays });
  observer.render();
  return performance.now() - t0;
}

/** Re-draw the observer without a core frame: `rebuild` re-derives its geometry from the last frame (layer or ray
 * checkboxes), else only its camera changed. */
function observer_refresh(rebuild: boolean): void {
  if (!state.obs.on || observer === null) return;
  if (rebuild && state.rec !== null && state.doc !== null) update_observer(state.rec, state.doc);
  else observer.render();
}

let obsRafPending = false;
function request_observer_render(): void {
  if (obsRafPending) return;
  obsRafPending = true;
  requestAnimationFrame(() => {
    obsRafPending = false;
    observer_refresh(false);
  });
}

function set_observer(on: boolean): void {
  state.obs.on = on;
  ui.observerOn.checked = on;
  try {
    localStorage.setItem(OBSERVER_KEY, on ? "1" : "0");
  } catch {
    // storage unavailable: the switch still works for this page
  }
  ui.observerPane.hidden = !on;
  ui.observerControls.hidden = !on;
  ui.panes.classList.toggle("observer-on", on);
  if (on && observer === null) {
    observer = new ObserverPane(ui.observerCanvas, ui.observerLabels);
    observer.attach_input(ui.observerPane, request_observer_render);
    if (state.scene !== null && state.A !== null) observer.set_scene(state.scene, state.A);
  }
  layout();
  request_render(); // the resting frame: the observer is built from it (and the drawing pane re-letterboxed)
}

ui.observerOn.addEventListener("change", () => set_observer(ui.observerOn.checked));
ui.observerFrame.addEventListener("click", () => {
  state.obs.needs_framing = true;
  observer_refresh(true);
});
ui.observerRays.addEventListener("change", () => observer_refresh(true));

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
  const cam = camera_from_orbit(state.orbit, scene.camera); // the M7 orbit's block (status line)
  const block = frame_camera_block(scene.camera, cam, state.camera_edited); // what the core renders
  const img_mode = state.dragging && state.full_svg_length > IMG_MODE_THRESHOLD;
  let doc: GeometryDocument, svg: string, rec: CameraRecord;
  const t0 = performance.now();
  try {
    const B = project_scene(scene, state.A, block, !state.dragging);
    rec = B.camera;
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
  state.rec = rec;
  if (view3d.checked) view.render(block, scene.output.canvas_mm, state.A.scene_scale);
  warnings.update(doc);
  const obs_ms = state.obs.on ? update_observer(rec, doc) : null;
  state.obs.ms = obs_ms;
  state.timings.core_ms = t1 - t0;
  state.timings.dom_ms = t2 - t1;
  state.timings.mode = overlay.mode;
  state.frames.push({ core_ms: t1 - t0, dom_ms: t2 - t1, obs_ms, mode: overlay.mode, dragging: state.dragging, svg_bytes: svg.length });
  if (state.frames.length > 500) state.frames.shift();
  ui.statusLine.textContent = status_text(state.sceneName, state.timings, overlay.mode, doc, scene, cam, obs_ms);
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
  get camera() { return state.orbit && state.scene ? drawing_block(state.scene, state.orbit) : null; },
  get svg_length() { return state.svg.length; },
  /** The writer's SVG text of the last frame (the overlay's source). */
  get svg() { return state.svg; },
  /** The texts "Download SVG" / "Download JSON" would save now. */
  download_texts: () => state.doc === null ? null : {
    svg: svg_blob(state.doc, state.layersChecked, state.sceneName, hidden_style()).text,
    json: json_blob(state.doc, state.sceneName).text,
  },
  /** M9: switch the observer on / off as the "旁觀視角" checkbox does. */
  set_observer: (on: boolean) => {
    ui.observerOn.checked = on;
    ui.observerOn.dispatchEvent(new Event("change"));
  },
  /** M9: the observer's state (`null` before it was first switched on). */
  get observer() {
    if (observer === null) return null;
    const names = observer.names;
    const count = (prefix: string) => names.filter((n) => n.startsWith(prefix)).length;
    const [W, H] = observer.size, b = observer.last_board;
    /** The frame corners and the eye in observer-pane px (`null` behind the observer). */
    const px = b === null ? null : { corners: b.corners.map((c) => observer_project(observer!.view, W, H, c)),
      E: observer_project(observer.view, W, H, b.E) };
    return { on: state.obs.on, D: state.obs.D, view: observer.view, labels: observer.label_texts, names,
      art_objects: count("art"), ms: state.obs.ms, size: [W, H], px };
  },
  /** M9: the "旁觀視角取景" button. */
  frame_observer: () => ui.observerFrame.click(),
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

let stored_on = false;
try {
  stored_on = localStorage.getItem(OBSERVER_KEY) === "1";
} catch {
  stored_on = false;
}
if (stored_on) set_observer(true);
layout();
const first = EXAMPLES.find((e) => e.name === "basic") ?? EXAMPLES[0];
if (first !== undefined) {
  examplesSelect.value = first.name;
  load(first.name, () => load_scene(first.data));
}
