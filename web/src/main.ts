/**
 * The castplane web UI (contract §5.4.10; M10 plane mode §5.7): load a scene JSON (file picker, page-wide drag and
 * drop, bundled examples), show it with three.js, move the board (the picture plane) and overlay the SVG the ported
 * core writes for that camera — re-rendered per animation frame with stage A cached. No server, no network access at
 * runtime.
 *
 * This module owns the page state, loading and the render loop, and wires the others: `plane.ts` (the plane-mode
 * session: the rig of `rig.ts`, undo, pivot, readouts, and the right pane's gestures), `stage.ts` (one three.js view),
 * `input.ts` (file drop), `ui.ts` (controls and panels), `overlay.ts` (the SVG overlay), and, behind the "旁觀視角"
 * switch (M9, contract §5.6), `observer.ts` / `observer3d.ts` (the observer pane with the ring and arrow handles).
 */

import "./style.css";

import * as THREE from "three";

import { LAYER_IDS, compose, dumps, load_scene, load_scene_text, project_scene, shadow_geometry, write_svg } from "castplane";
import type { CameraRecord, GeometryDocument, Scene, StageA, Vec2 } from "castplane";

import { EXAMPLES } from "./examples.js";
import { camera_block_text, json_blob, ordered_layers, scene_blob, svg_blob } from "./download.js";
import { QUICK_EQUATIONS } from "./equation.js";
import { attach_file_drop } from "./input.js";
import { focal_from_slider } from "./orbit.js";
import {
  derive_board, framing_points, frame_view, handles_of, hit_handles, initial_view, line_art, observer_basis, observer_project,
  scene_centre, vertex_rays,
} from "./observer.js";
import type { HandleHit } from "./observer.js";
import { ObserverPane } from "./observer3d.js";
import type { HandleInput } from "./observer3d.js";
import { IMG_MODE_THRESHOLD, Overlay } from "./overlay.js";
import type { OverlayMode } from "./overlay.js";
import { PlaneSession, RightPaneGesture, arrow_drag, object_centres, ring_drag, ring_grab } from "./plane.js";
import { arrowScreenVector, clone, equation, sync } from "./rig.js";
import type { RigState, RingGrab, ViewName } from "./rig.js";
import { build_scene3d } from "./scene3d.js";
import { Stage3D, letterbox } from "./stage.js";
import {
  $, WarningsTable, build_layer_boxes, controls, describe_error, fill_examples, fill_quick_equations, save, set_error_panel,
  set_lines, set_rig_controls, status_text, umbra_count,
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
  /** The plane-mode session of the loaded scene (M10, §5.7.7): the rig, undo, pivot, readouts. */
  plane: PlaneSession | null;
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
  /** M9 observer (contract §5.6): whether a framing is pending, its last cost. */
  obs: { on: boolean; needs_framing: boolean; ms: number | null };
  /** M10: the handle being dragged in the observer pane, with its pointer-down state (§5.7.8 items 1, 4). */
  handle: { kind: "ring"; rig0: RigState; grab: RingGrab } | { kind: "arrow"; rig0: RigState; v: Vec2 } | null;
  /** M10: the last equation error (the field turns red with it), null when none. */
  equation_error: string | null;
}

const state: State = {
  scene: null,
  sceneName: "",
  A: null,
  plane: null,
  layersChecked: new Set(LAYER_IDS),
  doc: null,
  svg: "",
  timings: { stage_a_ms: 0, core_ms: 0, dom_ms: 0, mode: "dom" },
  dragging: false,
  dirty: false,
  full_svg_length: 0,
  frames: [],
  rec: null,
  obs: { on: false, needs_framing: true, ms: null },
  handle: null,
  equation_error: null,
};

const ui = controls();
const { viewport, stage, canvas, examplesSelect, fileInput, focalInput, distInput, rollInput, view3d, hiddenLines, hiddenStyle } = ui;

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
  if (id === "construction") ui.construction.checked = checked; // "作圖線" mirrors the construction layer
  if (overlay.mode === "img") request_render();
  observer_refresh(true); // the drawing on the frame follows the layer checkboxes
});
ui.construction.addEventListener("change", () => {
  const box = layerBoxes.get("construction");
  if (box === undefined || box.checked === ui.construction.checked) return;
  box.checked = ui.construction.checked;
  box.dispatchEvent(new Event("change"));
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
  // §5.7.7: the rig of the load rule (scene-centre pivot); the scene camera itself is rendered until the first change
  state.plane = new PlaneSession({
    camera: scene.camera, canvas_mm: scene.output.canvas_mm, centre: scene_centre(A), object_centres: object_centres(A.objects),
    vertices: A.vertices,
  });
  state.obs.needs_framing = true;
  // a drag held across the load (keyboard on the examples menu, a drop) belongs to the old scene: drop it
  state.handle = null;
  gesture.reset();
  state.dragging = false;
  set_equation_error(null);
  ui.pivotMode.value = "scene";
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
  ui.construction.checked = state.layersChecked.has("construction");
  sync_controls();
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

// ---------------------------------------------------------------------------- plane-mode controls (§5.7.8, §5.7.9)
/** Re-sync the sliders, the lock checkbox, the equation field (unless focused), the readouts, the notices and undo. */
function sync_controls(): void {
  const pl = state.plane;
  if (pl === null) return;
  set_rig_controls(ui, pl.rig);
  if (document.activeElement !== ui.equation) ui.equation.value = equation(pl.rig);
  set_lines(ui.readouts, pl.readout_lines());
  const notes = pl.notices();
  if (pl.pivot.mode === "object" && pl.pivot.object_id === null) {
    notes.push(state.obs.on ? "請點一下左窗的物體，把它設為旋轉中心（目前暫用場景中心）" : "打開旁觀視角後點一下左窗的物體，把它設為旋轉中心（目前暫用場景中心）");
  }
  set_lines(ui.notices, notes);
  ui.undo.disabled = !pl.undo.canUndo;
}

/** After a session action: re-frame the observer when asked (never during a drag), then render. */
function after_action(r: { changed: boolean; framing: boolean }): void {
  if (r.framing) state.obs.needs_framing = true;
  sync_controls();
  request_render();
}

function set_equation_error(message: string | null): void {
  state.equation_error = message;
  ui.equation.classList.toggle("bad", message !== null);
  ui.equation.setAttribute("aria-invalid", message !== null ? "true" : "false");
  ui.equationError.textContent = message ?? "";
}

/** Apply an equation text (the field, or a quick button's own text). */
function apply_equation(text: string): boolean {
  const pl = state.plane;
  if (pl === null) return false;
  const { error, result } = pl.apply_equation(text);
  set_equation_error(error);
  if (error === null) after_action(result);
  return error === null;
}

focalInput.addEventListener("input", () => {
  if (state.plane?.set_focal(focal_from_slider(Number(focalInput.value)))) after_action({ changed: true, framing: false });
});
distInput.addEventListener("input", () => {
  if (state.plane?.set_D(Number(distInput.value))) after_action({ changed: true, framing: false });
});
rollInput.addEventListener("input", () => {
  if (state.plane?.set_roll(Number(rollInput.value))) after_action({ changed: true, framing: false });
});
// at the end of a slider drag the thumb goes to the clamped value (the focused slider is not re-synced while it moves)
for (const el of [focalInput, distInput, rollInput]) {
  el.addEventListener("change", () => {
    if (state.plane !== null) set_rig_controls(ui, state.plane.rig, true);
  });
}
ui.lockLevel.addEventListener("change", () => {
  if (state.plane !== null) after_action(state.plane.set_lock_level(ui.lockLevel.checked));
});
ui.pivotMode.addEventListener("change", () => {
  if (state.plane !== null) after_action(state.plane.set_pivot_mode(ui.pivotMode.value === "object" ? "object" : "scene"));
});
for (const b of ui.views.querySelectorAll<HTMLButtonElement>("button[data-view]")) {
  b.addEventListener("click", () => {
    if (state.plane !== null) after_action(state.plane.view(b.dataset["view"] as ViewName));
  });
}
fill_quick_equations(ui.quickEquations, QUICK_EQUATIONS);
for (const b of ui.quickEquations.querySelectorAll<HTMLButtonElement>("button[data-eq]")) {
  b.addEventListener("click", () => apply_equation(b.dataset["eq"]!));
}
// 「套用」 must not take the focus first: the field's blur would re-sync it to the current plane before the click
ui.equationApply.addEventListener("mousedown", (ev) => ev.preventDefault());
ui.equationApply.addEventListener("click", () => {
  if (apply_equation(ui.equation.value)) ui.equation.blur();
});
ui.equation.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") {
    ev.preventDefault();
    if (apply_equation(ui.equation.value)) ui.equation.blur();
  } else if (ev.key === "Escape") {
    set_equation_error(null);
    ui.equation.blur();
  }
});
// leaving the field discards the typed text, and with it the text's error
ui.equation.addEventListener("blur", () => {
  set_equation_error(null);
  sync_controls();
});
ui.undo.addEventListener("click", () => {
  if (state.plane !== null) after_action(state.plane.undo_step());
});
ui.reset.addEventListener("click", () => {
  if (state.plane === null) return;
  const r = state.plane.reset();
  ui.pivotMode.value = "scene";
  set_equation_error(null);
  if (observer !== null) observer.view = { ...initial_view(), target: observer.view.target, dist: observer.view.dist };
  after_action({ ...r, framing: true });
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
  if (state.scene !== null && state.plane !== null) save(scene_blob(state.scene, state.plane.block(), state.sceneName, hiddenLines.checked, hidden_style()));
});
$<HTMLButtonElement>("copy-camera").addEventListener("click", () => {
  if (state.scene === null || state.plane === null) return;
  const text = camera_block_text(state.plane.block());
  navigator.clipboard.writeText(text).then(
    () => show_error(null),
    (e) => show_error(`clipboard unavailable (${describe_error(e)}); camera block:\n${text}`),
  );
});

// ---------------------------------------------------------------------------- right-pane input (§5.7.8 items 2, 5, 6)
const gesture = new RightPaneGesture();
stage.addEventListener("contextmenu", (ev) => ev.preventDefault());
stage.addEventListener("pointerdown", (ev) => {
  const pl = state.plane;
  if (pl === null || state.handle !== null) return;
  const r = gesture.down({ id: ev.pointerId, x: ev.clientX, y: ev.clientY, button: ev.button, shift: ev.shiftKey, type: ev.pointerType }, pl.rig);
  if (r === "ignored") return;
  stage.setPointerCapture(ev.pointerId);
  ev.preventDefault();
  if (r === "start") {
    pl.begin();
    state.dragging = true;
  }
});
stage.addEventListener("pointermove", (ev) => {
  const pl = state.plane, sc = state.scene;
  if (pl === null || sc === null || gesture.active === null) return;
  const next = gesture.move({ id: ev.pointerId, x: ev.clientX, y: ev.clientY },
    { H_px: stage.clientHeight || 1, frame_h: sc.camera.frame_mm[1], snap: ui.snap.checked && !ev.altKey });
  if (next !== null && pl.drag(next)) request_render(); // the controls follow in the frame
});
const right_end = (ev: PointerEvent): void => {
  if (!gesture.up(ev.pointerId)) return;
  state.plane?.end();
  state.dragging = false;
  sync_controls();
  request_render(); // the resting frame (DOM overlay, hidden lines, umbra)
};
stage.addEventListener("pointerup", right_end);
stage.addEventListener("pointercancel", right_end);
stage.addEventListener("wheel", (ev) => {
  const pl = state.plane;
  if (pl === null) return;
  ev.preventDefault();
  if (pl.wheel(ev.deltaY, performance.now())) request_render();
}, { passive: false });

// ---------------------------------------------------------------------------- observer handles (§5.7.8 items 1, 4, 10; §5.7.9)
/** The observer pane's size and basis for the hit test and the drag mappings (the projection of `observer3d`). */
function obs_frame(): { W: number; H: number; basis: ReturnType<typeof observer_basis> } | null {
  if (observer === null) return null;
  const [W, H] = observer.size;
  return { W, H, basis: observer_basis(observer.view) };
}

const handle_input: HandleInput = {
  hit: (p, touch): HandleHit => {
    const o = obs_frame(), h = observer?.last_handles ?? null;
    if (o === null || h === null || state.plane === null || state.dragging) return null;
    return hit_handles(o.basis, o.W, o.H, p, touch, h);
  },
  begin: (hit) => {
    const pl = state.plane, o = obs_frame(), h = observer?.last_handles ?? null;
    if (pl === null || o === null || h === null || observer === null) return;
    const rig0 = clone(pl.rig);
    if (hit.kind === "ring") {
      state.handle = { kind: "ring", rig0, grab: ring_grab(h.ring[hit.index]!, rig0.P, o.basis.r, o.basis.u) };
    } else {
      const view = observer.view;
      state.handle = { kind: "arrow", rig0, v: arrowScreenVector(rig0, (X) => observer_project(view, o.W, o.H, X)) };
    }
    pl.begin();
    state.dragging = true;
    request_render();
  },
  move: (dx, dy, alt) => {
    const pl = state.plane, hd = state.handle;
    if (pl === null || hd === null) return;
    const snap = ui.snap.checked && !alt;
    const next = hd.kind === "ring" ? ring_drag(hd.rig0, hd.grab, dx, dy, snap) : arrow_drag(hd.rig0, hd.v, dx, dy, snap);
    if (pl.drag(next)) request_render();
  },
  end: () => {
    state.plane?.end();
    state.handle = null;
    state.dragging = false;
    sync_controls();
    request_render();
  },
  cancel: () => {
    state.plane?.cancel();
    state.handle = null;
    state.dragging = false;
    sync_controls();
    request_render();
  },
  click: (p) => {
    const pl = state.plane;
    if (pl === null || observer === null || pl.pivot.mode !== "object") return;
    const id = observer.pick_object(p);
    if (id !== null) after_action(pl.pick_object(id));
  },
};

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
  const pl = state.plane;
  if (observer === null || state.scene === null || pl === null) return 0;
  const t0 = performance.now();
  const rig = pl.rig, d = sync(rig);
  // M10: the board of the rig (§5.6.5): pivot P, R = g + D, D of the rig; the frame from the rendered record
  const board = derive_board(rec, { target: rig.P, distance: d.R }, rig.D);
  const art = line_art(doc, rec, rig.D, state.layersChecked);
  const rays = ui.observerRays.checked ? vertex_rays(doc, state.scene, board, rec.near) : null;
  if (state.obs.needs_framing && !state.dragging) {
    observer.view = frame_view(observer.view, framing_points(board, state.scene, pl.scene.centre), observer.aspect);
    state.obs.needs_framing = false;
  }
  observer.update({ board, art, rays, handles: handles_of(rig, state.scene.camera.frame_mm),
    pivot_id: pl.pivot.mode === "object" ? pl.pivot.object_id : null, active: state.handle?.kind ?? null });
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
    observer.attach_input(ui.observerPane, request_observer_render, handle_input);
    if (state.scene !== null && state.A !== null) observer.set_scene(state.scene, state.A);
  }
  layout();
  sync_controls();
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
  const pl = state.plane;
  if (!state.dirty || state.scene === null || state.A === null || pl === null) return;
  state.dirty = false;
  const scene = state.scene;
  const block = pl.block(); // what the core renders: the scene camera until the first change, then the rig's (§5.7.7)
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
  sync_controls(); // sliders, equation, readouts (the picture delta is measured here, once per frame), notices, undo
  const form = pl.scene_block ? "scene camera" : "picture_plane";
  ui.statusLine.textContent = status_text(state.sceneName, state.timings, overlay.mode, doc, scene, rec, block.focal_length_mm, form, obs_ms);
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
  get camera() { return state.plane === null ? null : state.plane.block(); },
  /** M10: the rig and what is derived from it (read-only), the pivot selection, the undo depth, the readouts. */
  get rig() {
    const pl = state.plane;
    if (pl === null) return null;
    const d = sync(pl.rig);
    return { ...clone(pl.rig), E: d.E, Q: d.Q, R: d.R, c: d.c, r: d.r, u: d.u, equation: equation(pl.rig),
      scene_block: pl.scene_block, pivot: { ...pl.pivot }, undo: pl.undo.size, delta: pl.delta,
      readouts: pl.readout_lines(), notices: pl.notices() };
  },
  /** M10: the observer-pane px of the handles, the eye and the pivot (`null` entries behind the observer). */
  get handles_px() {
    const o = obs_frame(), h = observer?.last_handles ?? null, b = observer?.last_board ?? null;
    if (o === null || h === null || b === null || observer === null) return null;
    const pr = (X: readonly number[]) => observer_project(observer!.view, o.W, o.H, X);
    return { tip: pr(h.tip), Q: pr(h.Q), ring: h.ring.map(pr), E: pr(b.E), P: pr(b.P), size: [o.W, o.H] };
  },
  /** M10: the observer-pane px of each object's pivot (its stage-A bounding-box centre). */
  get objects_px() {
    const o = obs_frame(), pl = state.plane;
    if (o === null || pl === null || observer === null) return null;
    const view = observer.view;
    return Object.fromEntries([...pl.scene.object_centres].map(([id, c]) => [id, observer_project(view, o.W, o.H, c)]));
  },
  /** M10 random-frame check (§5.7.13 last row): put `rig` (a full state; its `P` is kept as given) into the session as a
   * one-move drag would (cancelled afterwards), render one frame synchronously, and report whether every number handed
   * to drawing calls is finite: the camera block, the camera record, the observer's board, drawing, rays and handles,
   * and the SVG text. */
  probe_rig: (rig: RigState) => {
    const pl = state.plane;
    if (pl === null) return null;
    pl.begin(); // a one-move gesture, cancelled after the checks: no undo step, the state comes back
    pl.drag(clone(rig));
    state.dirty = true;
    frame();
    const finite = (x: unknown): boolean => typeof x === "number" ? Number.isFinite(x)
      : Array.isArray(x) ? x.every(finite) : x !== null && typeof x === "object" ? Object.values(x).every(finite) : true;
    const bad: string[] = [];
    if (!finite(pl.block())) bad.push("camera block");
    if (state.rec === null || !finite({ P: state.rec.P, C: state.rec.C, R: state.rec.R })) bad.push("camera record");
    if (/NaN|Infinity/.test(state.svg)) bad.push("svg");
    if (observer !== null && state.obs.on) {
      if (!finite(observer.last_board)) bad.push("board");
      if (!finite(observer.last_handles)) bad.push("handles");
      if (!finite(observer.view)) bad.push("observer view");
    }
    pl.cancel();
    state.dirty = true;
    return bad;
  },
  /** M10: the observer's handle hit test at pane px `(x, y)` (mouse radius). */
  hit_at: (x: number, y: number) => handle_input.hit([x, y], false),
  /** M10: the equation field's state. */
  get equation_field() { return { value: ui.equation.value, error: state.equation_error, bad: ui.equation.classList.contains("bad") }; },
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
    return { on: state.obs.on, D: state.plane?.rig.D ?? null, view: observer.view, labels: observer.label_texts, names,
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
