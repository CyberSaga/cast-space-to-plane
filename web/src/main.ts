/**
 * The castplane web UI (contract §5.4.10; M10 plane mode §5.7): load a scene JSON (file picker, page-wide drag and
 * drop, bundled examples), show it with three.js, move the board (the picture plane) and overlay the SVG the ported
 * core writes for that camera — re-rendered per animation frame with stage A cached. No server, no network access at
 * runtime.
 *
 * This module owns the page state, loading and the render loop, and wires the others: `plane.ts` (the plane-mode
 * session: the rig of `rig.ts`, undo, pivot, readouts), `stage.ts` (one three.js view), `input.ts` (file drop),
 * `ui.ts` (controls and panels), `toggles.ts` (the page-level view toggles and their defaults), `overlay.ts` (the SVG
 * overlay), and, behind the "旁觀視角" switch (M9, contract §5.6), `observer.ts` / `observer3d.ts` (the observer pane
 * with the ring and arrow handles). The drawing pane (`#stage`) is view-only: no pointer or wheel listener is
 * registered on it, so drags and wheel there do nothing (the page scrolls natively); the board is moved only in the
 * observer pane and with the controls.
 *
 * M11 (contract §5.8): the observer pane also edits the scene — a press on an object selects it, a drag moves it
 * horizontally (`scene_edit.ts`), the selected object's vertical handle moves it vertically, a library tile adds a
 * preset (`library.ts`), Delete / Backspace or the chip's button delete it, and every edit is one entry of the single
 * history (`plane.ts`). Hit tests, the press classifier and the key rules are `selection.ts`'s. The drawing pane only
 * shows the selection outline in `#sel-overlay`, outside the writer's markup (D79); while 預覽 is on the scene is
 * read-only.
 */

import "./style.css";

import * as THREE from "three";

import { LAYER_IDS, compose, dumps, load_scene, load_scene_text, project_scene, shadow_geometry, validate_scene, write_svg } from "castplane";
import type { CameraRecord, GeometryDocument, Scene, SceneObject, StageA, Vec2, Vec3 } from "castplane";

import { EXAMPLES } from "./examples.js";
import { camera_block_text, json_blob, ordered_layers, scene_blob, svg_blob } from "./download.js";
import { QUICK_EQUATIONS } from "./equation.js";
import { attach_file_drop } from "./input.js";
import { LIB_NARROW_PX, PRESETS, make_object, tile_label } from "./library.js";
import type { Preset } from "./library.js";
import { focal_from_slider } from "./orbit.js";
import {
  derive_board, framing_points, frame_view, handles_of, hit_handles, initial_view, line_art, observer_basis, observer_project,
  scene_centre, vertex_rays,
} from "./observer.js";
import type { HandleHit } from "./observer.js";
import { ObserverPane } from "./observer3d.js";
import type { ObserverSelection, PaneInput } from "./observer3d.js";
import { IMG_MODE_THRESHOLD, Overlay } from "./overlay.js";
import type { OverlayMode } from "./overlay.js";
import { PlaneSession, arrow_drag, object_centres, ring_drag, ring_grab } from "./plane.js";
import type { ActionResult, StepResult } from "./plane.js";
import { arrowScreenVector, clone, equation, sync } from "./rig.js";
import type { RigState, RingGrab, ViewName } from "./rig.js";
import { build_scene3d, object_matrix, set_object_node } from "./scene3d.js";
import {
  NOTICE_KEEP_ONE, PREVIEW_MS, add_with_entry, can_delete, delete_with_entry, display_name, drag_begin, drag_position,
  finish_position, index_of, label_text, move_entry, names_after, next_id, place_object, used_ids, vertical_begin, vertical_handle,
  vertical_z, with_position, world_bbox,
} from "./scene_edit.js";
import type { Box, CameraFrame, DragStart, VerticalStart } from "./scene_edit.js";
import {
  PressTracker, focus_kind, frame_ray, hit_vertical, observer_frame, outline_polylines, press_target, shortcut_action, svg_point,
  wire_segments,
} from "./selection.js";
import type { TargetLike } from "./selection.js";
import { Stage3D, letterbox } from "./stage.js";
import { initial_toggles } from "./toggles.js";
import {
  $, WarningsTable, build_layer_boxes, controls, describe_error, fill_examples, fill_quick_equations, save, set_error_panel,
  set_lines, set_rig_controls, status_text, umbra_count,
} from "./ui.js";

THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

/** The page's view toggles at start (layers, hidden lines, 3D view); scene loads never reset them. */
const TOGGLES = initial_toggles(LAYER_IDS);

interface FrameRecord {
  core_ms: number;
  dom_ms: number;
  /** The observer's own cost (geometry + its render), `null` while 預覽 hides the pane. */
  obs_ms: number | null;
  mode: OverlayMode;
  dragging: boolean;
  svg_bytes: number;
  /** M11 (§5.8.12): an object-drag frame (stage A re-run; `core_ms` includes validate + A), and whether it was drawn as
   * the wireframe preview (no core run). */
  edit: boolean;
  preview: boolean;
}

/** M11: an open press on an object or on the selected object's vertical handle in the observer pane (§5.8.2–§5.8.4). */
interface ObjectPress {
  kind: "object" | "vertical";
  id: string;
  index: number;
  /** The record at pointer-down (restored on a cancel; the move entry's `before`). */
  before: SceneObject;
  tracker: PressTracker;
  /** The selection before the press (a cancel brings it back). */
  prev_selected: string | null;
  /** The observer camera and pane size at pointer-down (the drag maths uses that frame). */
  cam: CameraFrame;
  W: number;
  H: number;
  drag: DragStart | null;
  vert: VerticalStart | null;
  /** The drag has begun (an object: travel ≥ CLICK_PX; the handle: at once). */
  started: boolean;
  /** Wireframe preview for this gesture (§5.8.12), decided once (`null`: after the first drag frame). */
  preview: boolean | null;
  /** Stage A and the vertex offset of the object at pointer-down (the wireframe and the translated vertices). */
  A0: StageA;
  offset: number;
  /** The anchor's world displacement since pointer-down. */
  shift: Vec3;
  /** A vertical drag: the handle's length at pointer-down, kept for the gesture (the handle follows the object by
   * `Δz_b`, §5.8.4, so its tip stays under the pointer). */
  len0: number | null;
}

interface State {
  scene: Scene | null;
  sceneName: string;
  A: StageA | null;
  /** The plane-mode session of the loaded scene (M10, §5.7.7): the rig, undo, pivot, readouts. */
  plane: PlaneSession | null;
  /** The checked layer checkboxes: page-level, kept across scene loads (`toggles.ts`). */
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
  /** M11 (§5.8.1): the selected object id (at most one), web state only: never in the scene JSON or a history entry.
   * It is the observer's vertex-ray focus (§5.8.6). */
  selected_id: string | null;
  /** M11 (§5.8.9): display names of the objects the library made (`id → tile name`), never written to the JSON. */
  names: Map<string, string>;
  /** M11: the open object or vertical-handle press (§5.8.2). */
  press: ObjectPress | null;
  /** M11 (§5.8.12): the objects were changed by a drag since the last frame; the next frame re-runs stage A. */
  objects_dirty: boolean;
  /** M11: the scene stage A was last built from (a drag frame the validator rejects falls back to it). */
  scene_A: Scene | null;
  /** M11 (§5.8.12): the cost (ms) of the last drag-mode edit frame of this scene; a test hook can force it. */
  edit_ms: number | null;
  edit_ms_forced: number | null;
  /** M11 (§5.8.7): the library sidebar is open (never stored; collapsed at start, on a load and on entering 預覽). */
  library_open: boolean;
  /** M11 (§5.8.10): a Delete was refused by the keep-one rule; the notice shows until the next edit or selection. */
  keep_one_notice: boolean;
}

const state: State = {
  scene: null,
  sceneName: "",
  A: null,
  plane: null,
  layersChecked: new Set(TOGGLES.layers),
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
  selected_id: null,
  names: new Map(),
  press: null,
  objects_dirty: false,
  scene_A: null,
  edit_ms: null,
  edit_ms_forced: null,
  library_open: false,
  keep_one_notice: false,
};

const ui = controls();
const { viewport, stage, canvas, examplesSelect, fileInput, focalInput, distInput, rollInput, view3d, hiddenLines, hiddenStyle } = ui;

// ---------------------------------------------------------------------------- three.js and overlay
const view = new Stage3D(canvas);
const overlay = new Overlay(stage);
/** M11 (§5.8.2, §5.8.12, §5.8.14): the drawing pane's selection outline and drag wireframe — a sibling of the writer's
 * overlay (interface only, `pointer-events: none`, never in an output). */
const selOverlay = document.createElementNS("http://www.w3.org/2000/svg", "svg");
selOverlay.id = "sel-overlay";
selOverlay.setAttribute("class", "sel-overlay");
selOverlay.setAttribute("preserveAspectRatio", "xMidYMid meet");
selOverlay.setAttribute("aria-hidden", "true");
stage.append(selOverlay);
const warnings = new WarningsTable(ui.warningsBody);
/** The observer pane, created at startup (D80; while 預覽 hides it the layout and outputs are the §5.4.10 page's;
 *  the drawing pane takes no input either way, D79). */
let observer: ObserverPane | null = null;

// ---------------------------------------------------------------------------- layer checkboxes and view toggles
// page-level state (toggles.ts): set once here, kept across scene loads
hiddenLines.checked = TOGGLES.hidden_lines;
hiddenStyle.disabled = !hiddenLines.checked;
view3d.checked = TOGGLES.view3d;
canvas.classList.toggle("hidden", !view3d.checked); // hidden from the first frame; `frame` renders it only when checked
ui.construction.checked = state.layersChecked.has("construction");
overlay.set_hidden_layers(state.layersChecked);
const layerBoxes = build_layer_boxes(ui.layersBox, LAYER_IDS, state.layersChecked, (id, checked) => {
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
  state.press = null; // a press held across the load belongs to the old scene (§5.8.16)
  state.scene = scene;
  state.scene_A = scene;
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
  state.dragging = false;
  state.selected_id = null; // a load clears the selection (§5.8.2) and, with the new session, both history stacks
  state.names = new Map();
  state.objects_dirty = false;
  state.edit_ms = null;
  state.keep_one_notice = false;
  stage.classList.remove("wire");
  set_library(false); // collapsed after every scene load (§5.8.7)
  set_equation_error(null);
  ui.pivotMode.value = "scene";
  state.rec = null;
  state.full_svg_length = 0;
  state.frames = [];
  view.replace_group(() => build_scene3d(scene, A));
  observer?.set_scene(scene, A);
  // the layer, "Hidden lines" and "3D view" checkboxes are page-level (toggles.ts): the scene's output.layers and
  // output.hidden_lines do not reset them; the hidden style still comes from the scene
  hiddenStyle.value = scene.output.hidden_style ?? "dashed";
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
    notes.push(state.obs.on ? "請點一下左窗的物體，把它設為旋轉中心（在那之前旋轉中心不動）" : "按「返回編輯」後點一下左窗的物體，把它設為旋轉中心（在那之前旋轉中心不動）");
  }
  if (!state.obs.on) notes.push(NOTICE_PREVIEW_READ_ONLY);
  if (state.keep_one_notice) notes.push(NOTICE_KEEP_ONE);
  set_lines(ui.notices, notes);
  ui.pivotMode.value = pl.pivot.mode; // an undo or redo of 重設視角 restores the selector (§5.8.5)
  // §5.8.11: undo and redo need an entry and the edit view (preview is read-only, §5.8.14); during a gesture the
  // history commands, 重設視角 and 重新取中心 are inert and their buttons disabled
  const busy = gesture_open();
  ui.undo.disabled = !pl.history.canUndo || !state.obs.on || busy;
  ui.redo.disabled = !pl.history.canRedo || !state.obs.on || busy;
  ui.reset.disabled = busy;
  ui.recenter.disabled = busy;
  sync_chip(busy);
  ui.libTab.hidden = state.library_open || !state.obs.on; // the tab is hidden while the sidebar is open and in 預覽
  for (const t of ui.libGrid.querySelectorAll<HTMLButtonElement>("button.tile")) t.disabled = busy; // add is inert in a gesture
}

/** 預覽 is read-only (§5.8.14): the one-line hint of `#notices`. */
const NOTICE_PREVIEW_READ_ONLY = "預覽中無法編輯物件；按「返回編輯」或 Esc 回到編輯畫面";

const f2 = (x: number): string => {
  const t = x.toFixed(2);
  return t === "-0.00" ? "0.00" : t;
};

/** The selection chip (§5.8.2, §5.8.10): `name（id）`, the anchor `底面 (x, y, z) m` and the delete button; hidden
 * without a selection and while previewing. The keep-one rule disables the button and shows its text. */
function sync_chip(busy: boolean): void {
  const sc = state.scene, id = state.selected_id;
  const obj = sc === null || id === null ? undefined : sc.objects.find((o) => o.id === id);
  ui.chip.hidden = obj === undefined || !state.obs.on;
  if (obj === undefined || sc === null) return;
  const p = obj.transform.position;
  ui.chipName.textContent = label_text(obj.id, state.names);
  ui.chipPos.textContent = `底面 (${f2(p[0])}, ${f2(p[1])}, ${f2(p[2])}) m`;
  const one = !can_delete(sc.objects);
  ui.selDelete.disabled = one || busy;
  ui.chipHint.hidden = !one;
}

/** Whether a gesture is open (a ring or arrow drag; the condition that already refuses 預覽, §5.8.11). */
function gesture_open(): boolean {
  return state.dragging || state.handle !== null || (state.plane?.in_gesture ?? false);
}

/** After a session action: re-frame the observer when asked (never during a drag), then render. */
function after_action(r: ActionResult): void {
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
    ev.stopPropagation(); // the field's Esc cancels the typed text only; it does not also leave 預覽
    set_equation_error(null);
    ui.equation.blur();
  }
});
// leaving the field discards the typed text, and with it the text's error
ui.equation.addEventListener("blur", () => {
  set_equation_error(null);
  sync_controls();
});
/** Undo or redo (§5.8.11): not while previewing (§5.8.14) or during a gesture. A board or reset entry re-frames the
 * observer; an object entry replaces the objects (stage A re-run, the session's geometry refreshed, `P` untouched, no
 * re-framing) and the selection follows the object it acted on (§5.8.2). */
function history_step(dir: "undo" | "redo"): void {
  const pl = state.plane;
  if (pl === null || state.scene === null || !state.obs.on || gesture_open()) return;
  drop_pending_press();
  const r: StepResult = dir === "undo" ? pl.undo_step(state.scene.objects) : pl.redo_step(state.scene.objects);
  state.keep_one_notice = false;
  if (r.objects !== null && !apply_objects(r.objects)) {
    pl.history.clear(); // the restored scene failed validation: a bug guard, as a LIFO violation
  } else if (r.object_entry !== undefined && r.dir !== undefined) {
    state.names = names_after(state.names, r.object_entry, r.dir); // the display name follows the record (§5.8.9)
  }
  if (r.select !== undefined) set_selection(r.select);
  after_action(r);
}

/**
 * Replace the page's objects after an edit (§5.8.0): the loaded scene with the new `objects` array (records shared by
 * reference) is checked by the port's `validate_scene`, stage A is re-run and the session gets the new geometry
 * (`set_geometry`: `P`, the history and `scene_block` are kept, §5.8.5); the three.js groups are rebuilt. The observer
 * is not re-framed (§5.8.6). A selected id that no longer exists is cleared. Returns false (the previous scene stays,
 * the reason in the error panel) when the edited scene is rejected.
 */
function apply_objects(objects: readonly SceneObject[]): boolean {
  const pl = state.plane, sc = state.scene;
  if (pl === null || sc === null) return false;
  const scene: Scene = { ...sc, objects: [...objects] };
  let A: StageA;
  const t0 = performance.now();
  try {
    validate_scene(scene);
    A = shadow_geometry(scene);
  } catch (e) {
    show_error(describe_error(e));
    return false;
  }
  state.timings.stage_a_ms = performance.now() - t0;
  state.scene = scene;
  state.scene_A = scene;
  state.A = A;
  state.objects_dirty = false;
  pl.set_geometry(scene_centre(A), object_centres(A.objects), A.vertices);
  if (state.selected_id !== null && !scene.objects.some((o) => o.id === state.selected_id)) state.selected_id = null;
  view.replace_group(() => build_scene3d(scene, A));
  observer?.set_scene(scene, A);
  request_render();
  return true;
}

/** Re-run stage A for the objects a drag changed (§5.8.12; the three.js nodes were already moved): the port's
 * `validate_scene`, `shadow_geometry` and the session's `set_geometry`. A rejected edit falls back to the last scene
 * stage A was built from. Returns the cost in ms. */
function rebuild_stage_a(): number {
  const pl = state.plane, sc = state.scene;
  state.objects_dirty = false;
  if (pl === null || sc === null) return 0;
  const t0 = performance.now();
  let A: StageA;
  try {
    validate_scene(sc);
    A = shadow_geometry(sc);
  } catch (e) {
    show_error(describe_error(e));
    if (state.scene_A !== null) state.scene = state.scene_A;
    return performance.now() - t0;
  }
  state.scene_A = sc;
  state.A = A;
  pl.set_geometry(scene_centre(A), object_centres(A.objects), A.vertices);
  return performance.now() - t0;
}

/** Select an object (or clear with `null`): web state only, not a history step (§5.8.2); the observer's vertex rays
 * follow it without a core frame (§5.8.6). */
function set_selection(id: string | null): void {
  const next = id !== null && state.scene !== null && state.scene.objects.some((o) => o.id === id) ? id : null;
  if (next === state.selected_id) return;
  state.selected_id = next;
  state.keep_one_notice = false;
  observer_refresh(true);
  draw_sel_overlay();
  sync_controls();
}

// ---------------------------------------------------------------------------- M11 editing: add, delete (§5.8.7–§5.8.10)
/** Whether the scene can be edited now: the edit view (預覽 is read-only, §5.8.14) and no gesture open (§5.8.11). */
function can_edit(): boolean {
  return state.plane !== null && state.scene !== null && state.A !== null && state.obs.on && !gesture_open();
}

/** Add a preset (§5.8.8): the target, the avoidance, the snap; appended with the id of §5.8.9, selected, one add
 * entry; the pivot and the observer framing are untouched; a narrow screen closes the sidebar. */
function add_preset(preset: Preset): void {
  const pl = state.plane, sc = state.scene, A = state.A;
  if (pl === null || sc === null || A === null || !can_edit()) return;
  drop_pending_press();
  const id = next_id(preset.prefix, used_ids(sc));
  const d = sync(pl.rig);
  const at = place_object(make_object(preset, id, [0, 0, 0]), { E: d.E, f: pl.rig.f, P: pl.rig.P, r0: d.r0,
    existing: A.objects.map((o) => o.bbox), snap: ui.snap.checked });
  const res = add_with_entry(sc.objects, make_object(preset, id, at.position), preset.name, state.names);
  if (!apply_objects(res.objects)) return;
  state.names = res.names;
  pl.history.push(res.entry);
  set_selection(id);
  if (window.innerWidth < LIB_NARROW_PX) set_library(false);
  sync_controls();
}

/** Delete the selection (§5.8.10): refused by the keep-one rule (a refused key press shows the notice), otherwise
 * removed with one delete entry; the selection is cleared and `P` is untouched. */
function delete_selected(by_key: boolean): void {
  const pl = state.plane, sc = state.scene, id = state.selected_id;
  if (pl === null || sc === null || id === null || !can_edit()) return;
  drop_pending_press();
  const res = delete_with_entry(sc.objects, index_of(sc.objects, id), state.names);
  if (res === null) {
    if (by_key) {
      state.keep_one_notice = true;
      sync_controls();
    }
    return;
  }
  if (!apply_objects(res.objects)) return;
  state.names = res.names;
  pl.history.push(res.entry);
  set_selection(null);
  sync_controls();
}

// ---------------------------------------------------------------------------- M11 library sidebar (§5.8.7)
/** Open or close the library. Closing returns the focus to the tab when it was inside the sidebar; opening moves it to
 * the first tile. Not while previewing (the tab is hidden and the sidebar inert). */
function set_library(open: boolean): void {
  if (open && !state.obs.on) return;
  const had_focus = ui.lib.contains(document.activeElement);
  state.library_open = open;
  ui.lib.classList.toggle("open", open);
  ui.lib.inert = !open;
  ui.libTab.setAttribute("aria-expanded", open ? "true" : "false");
  ui.libTab.hidden = open || !state.obs.on;
  if (open) ui.libGrid.querySelector<HTMLButtonElement>("button.tile")?.focus({ preventScroll: true });
  else if (had_focus) (state.obs.on ? ui.libTab : ui.preview).focus({ preventScroll: true });
}

for (const preset of PRESETS) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "tile";
  b.setAttribute("aria-label", tile_label(preset));
  b.title = tile_label(preset);
  const thumb = document.createElement("span");
  thumb.className = "thumb";
  thumb.innerHTML = preset.thumbnail; // a static string of library.ts (no script, currentColor)
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = preset.name;
  b.append(thumb, name);
  b.addEventListener("click", () => add_preset(preset));
  ui.libGrid.append(b);
}
ui.libTab.addEventListener("click", () => set_library(true));
ui.libClose.addEventListener("click", () => set_library(false));
// below the narrow breakpoint a pointer-down outside the sidebar and the tab closes it and is consumed (§5.8.7, Q34):
// it starts no gesture and changes no selection; the click that follows it is swallowed too
let swallow_click_until = 0;
document.addEventListener("pointerdown", (ev) => {
  if (!state.library_open || window.innerWidth >= LIB_NARROW_PX) return;
  const t = ev.target instanceof Node ? ev.target : null;
  if (t !== null && (ui.lib.contains(t) || ui.libTab.contains(t))) return;
  ev.preventDefault();
  ev.stopImmediatePropagation();
  swallow_click_until = performance.now() + 800;
  set_library(false);
}, { capture: true });
document.addEventListener("click", (ev) => {
  if (performance.now() > swallow_click_until) return;
  swallow_click_until = 0;
  ev.preventDefault();
  ev.stopImmediatePropagation();
}, { capture: true });
ui.selDelete.addEventListener("click", () => delete_selected(false));

ui.undo.addEventListener("click", () => history_step("undo"));
ui.redo.addEventListener("click", () => history_step("redo"));
// 重設視角 (§5.8.5): board, pivot (the current scene centre) and observer camera; objects and the selection are kept
ui.reset.addEventListener("click", () => {
  if (state.plane === null || gesture_open()) return;
  const r = state.plane.reset();
  set_equation_error(null);
  if (observer !== null) observer.view = { ...initial_view(), target: observer.view.target, dist: observer.view.dist };
  after_action({ ...r, framing: true });
});
// 重新取中心 (§5.8.5): re-take P for the current mode; not an undo step
ui.recenter.addEventListener("click", () => {
  if (state.plane !== null && !gesture_open()) after_action(state.plane.recenter(state.selected_id));
});

// phase 2 of §5.4.10: the hidden-line switch, passed as `hidden_lines` to `compose` (page-level, on at start), and the
// hidden style, passed as `hidden_style` to `write_svg` ("dashed" | "omit", §5.1.8; set from the scene's `output` on load)
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

// ---------------------------------------------------------------------------- observer handles (§5.7.8 items 1, 4, 10; §5.7.9)
/** The observer pane's size and basis for the hit test and the drag mappings (the projection of `observer3d`). */
function obs_frame(): { W: number; H: number; basis: ReturnType<typeof observer_basis> } | null {
  if (observer === null) return null;
  const [W, H] = observer.size;
  return { W, H, basis: observer_basis(observer.view) };
}

/** The ring / arrow hit at pane px `p` (null while a drag is held). */
function hit_board_handles(p: Vec2, touch: boolean): HandleHit {
  const o = obs_frame(), h = observer?.last_handles ?? null;
  if (o === null || h === null || state.plane === null || state.dragging) return null;
  return hit_handles(o.basis, o.W, o.H, p, touch, h);
}

/** The stage-A world mesh of every `mesh` object (the exact hit test of the others needs none). */
function world_meshes(): (StageA["objects"][number]["mesh"] | null)[] {
  return (state.A?.objects ?? []).map((o) => (o.type === "mesh" ? o.mesh : null));
}

/** What a press at pane px `p` grabs (§5.8.2): arrow tip > ring > the selected object's vertical handle > object
 * (exact ray hits, `selection.ts`) > blank. */
function pane_target(p: Vec2, touch: boolean): ReturnType<typeof press_target> | null {
  const sc = state.scene, o = obs_frame();
  if (observer === null || sc === null || o === null || state.plane === null) return null;
  return press_target({ view: observer.view, W: o.W, H: o.H, p, touch, handles: observer.last_handles, selected: state.selected_id,
    vertical_tip: observer.vertical_tip, objects: sc.objects, meshes: world_meshes() });
}

/** Pointer-down on the ring or the arrow (§5.7.8 items 1, 4): opens a board gesture. */
function begin_handle(hit: NonNullable<HandleHit>): void {
  const pl = state.plane, o = obs_frame(), h = observer?.last_handles ?? null;
  if (pl === null || o === null || h === null || observer === null) return;
  const rig0 = clone(pl.rig);
  if (hit.kind === "ring") {
    state.handle = { kind: "ring", rig0, grab: ring_grab(h.ring[hit.index]!, rig0.P, o.basis.r, o.basis.u) };
  } else {
    const v = observer.view;
    state.handle = { kind: "arrow", rig0, v: arrowScreenVector(rig0, (X) => observer_project(v, o.W, o.H, X)) };
  }
  pl.begin();
  state.dragging = true;
  sync_controls();
  request_render();
}

function end_handle(cancel: boolean): void {
  if (cancel) state.plane?.cancel();
  else state.plane?.end();
  state.handle = null;
  state.dragging = false;
  sync_controls();
  request_render();
}

/** The vertex offset of object `index` in stage A's vertex list (objects' vertices come first, in order). */
function vertex_offset(A: StageA, index: number): number {
  let n = 0;
  for (let k = 0; k < index; k++) n += A.objects[k]!.mesh.vertices.length;
  return n;
}

/** Pointer-down on an object (§5.8.2, §5.8.3) or on the selected object's vertical handle (§5.8.4). An object becomes
 * selected at once (the previous selection is kept for a cancel); its drag starts after CLICK_PX of travel. */
function begin_press(kind: "object" | "vertical", id: string, p: Vec2, point: Vec3 | null): void {
  const sc = state.scene, A = state.A, o = obs_frame();
  if (sc === null || A === null || o === null || observer === null) return;
  const index = index_of(sc.objects, id);
  const before = sc.objects[index];
  if (before === undefined) return;
  const cam = observer_frame(observer.view, o.H);
  const ray0 = frame_ray(cam, o.W, o.H, p);
  const prev = state.selected_id;
  let drag: DragStart | null = null, vert: VerticalStart | null = null, len0: number | null = null;
  if (kind === "object") {
    drag = drag_begin(before.transform.position, point!, ray0, cam);
  } else {
    const box = world_bbox(before, A.objects[index]);
    vert = vertical_begin(before.transform.position, box, ray0);
    if (vert === null) return; // s₀ does not exist: the press does nothing (§5.8.4)
    len0 = vertical_handle(box, cam).len;
  }
  state.press = { kind, id, index, before, tracker: new PressTracker(kind === "object" ? "object" : "handle", p[0], p[1]),
    prev_selected: prev, cam, W: o.W, H: o.H, drag, vert, started: false, preview: null, A0: A, offset: vertex_offset(A, index),
    shift: [0, 0, 0], len0 };
  if (kind === "object") set_selection(id);
  else start_drag(state.press);
}

/** The press becomes a drag (§5.8.2): the gesture opens (the history commands are inert), the picture-delta
 * measurement starts (§5.8.12) and the wireframe preview is decided from the last drag-mode frame's cost. */
function start_drag(pr: ObjectPress): void {
  pr.started = true;
  state.dragging = true;
  state.plane?.begin_measure();
  const c = state.edit_ms_forced ?? state.edit_ms;
  pr.preview = c === null ? null : c > PREVIEW_MS;
  sync_controls();
}

/** A move of the open press: the object's new anchor from the pointer (horizontal drag, or the vertical handle). */
function press_move(p: Vec2, alt: boolean): void {
  const pr = state.press;
  if (pr === null) return;
  pr.tracker.move(p[0], p[1]);
  if (!pr.started) {
    if (!pr.tracker.dragging) return; // the 5 px dead zone: nothing moves before it (§5.8.2)
    start_drag(pr);
  }
  const snap = ui.snap.checked && !alt; // Alt pauses snapping, read per event
  const ray = frame_ray(pr.cam, pr.W, pr.H, p);
  let pos: Vec3 | null = null;
  if (pr.drag !== null) {
    const xy = drag_position(pr.drag, ray, pr.tracker.dx, pr.tracker.dy);
    if (xy !== null) pos = finish_position(xy, pr.before.transform.position, snap);
  } else if (pr.vert !== null) {
    pos = vertical_z(pr.vert, ray, snap);
  }
  if (pos !== null) set_press_position(pr, pos);
}

/** Put the pressed object at `pos` (a new record; the pressed one itself when `pos` is the pressed position): the
 * three.js nodes move at once, stage A waits for the next frame (one recompute per frame, §5.8.12). */
function set_press_position(pr: ObjectPress, pos: Vec3): void {
  const sc = state.scene;
  if (sc === null) return;
  const cur = sc.objects[pr.index]!.transform.position, p0 = pr.before.transform.position;
  if (cur[0] === pos[0] && cur[1] === pos[1] && cur[2] === pos[2]) return;
  const same = p0[0] === pos[0] && p0[1] === pos[1] && p0[2] === pos[2];
  const rec = same ? pr.before : with_position(pr.before, pos);
  const objects = sc.objects.slice();
  objects[pr.index] = rec;
  state.scene = { ...sc, objects };
  pr.shift = [pos[0] - p0[0], pos[1] - p0[1], pos[2] - p0[2]];
  const m = rec.type === "mesh" ? new THREE.Matrix4().makeTranslation(pr.shift[0], pr.shift[1], pr.shift[2]) : object_matrix(rec);
  set_object_node(view.group, rec.id, m);
  set_object_node(observer?.stage.group ?? null, rec.id, m);
  if (pr.preview !== true) state.objects_dirty = true;
  request_render();
}

/** Release of the open press: a click keeps the selection (and takes `P` in 點選物體); a drag records one move entry
 * when the position changed and runs one complete recompute (§5.8.11, §5.8.12). */
function press_up(): void {
  const pr = state.press, pl = state.plane, sc = state.scene;
  state.press = null;
  if (pr === null || pl === null || sc === null) return;
  if (!pr.started) {
    // a click (§5.8.2): the selection stays; in 點選物體 the pivot is taken from the object's current box centre
    if (pl.pivot.mode === "object") after_action(pl.pick_object(pr.id));
    else sync_controls();
    return;
  }
  state.dragging = false;
  stage.classList.remove("wire");
  const after = sc.objects[pr.index]!;
  const e = move_entry(pr.index, pr.before, after);
  const objects = sc.objects.slice();
  if (e === null) objects[pr.index] = pr.before; // no movement: the pressed record itself, no entry
  if (apply_objects(objects)) {
    if (e !== null) pl.history.push(e);
  } else {
    objects[pr.index] = pr.before;
    apply_objects(objects);
  }
  sync_controls();
}

/** Cancel the open press (a second finger before CLICK_PX, `pointercancel`, entering 預覽): the pressed record and
 * the previous selection come back; nothing is recorded (§5.8.2, §5.8.16). */
function press_cancel(): void {
  const pr = state.press, sc = state.scene;
  state.press = null;
  if (pr === null || sc === null) return;
  if (pr.started) {
    state.dragging = false;
    stage.classList.remove("wire");
    const objects = sc.objects.slice();
    objects[pr.index] = pr.before;
    apply_objects(objects);
  }
  if (pr.kind === "object") set_selection(pr.prev_selected);
  sync_controls();
}

/** A command (add, delete, undo, redo) while an object press has not yet become a drag ends that press as it is (the
 * selection it made stays; its release does nothing). */
function drop_pending_press(): void {
  if (state.press !== null && !state.press.started) state.press = null;
}

/** The observer pane's input (§5.7.9, §5.8.2): hit priority, handles, object and vertical drags, blank clicks. */
const pane_input: PaneInput = {
  down: (p, touch) => {
    if (state.dragging || state.press !== null || !state.obs.on) return false;
    const t = pane_target(p, touch);
    if (t === null) return false;
    switch (t.kind) {
      case "arrow":
        begin_handle({ kind: "arrow" });
        return true;
      case "ring":
        begin_handle({ kind: "ring", index: t.index });
        return true;
      case "handle":
        begin_press("vertical", t.id, p, null);
        return true;
      case "object":
        begin_press("object", t.hit.id, p, t.hit.point);
        return true;
      default:
        return false;
    }
  },
  move: (p, dx, dy, alt) => {
    const pl = state.plane, hd = state.handle;
    if (pl !== null && hd !== null) {
      const snap = ui.snap.checked && !alt;
      const next = hd.kind === "ring" ? ring_drag(hd.rig0, hd.grab, dx, dy, snap) : arrow_drag(hd.rig0, hd.v, dx, dy, snap);
      if (pl.drag(next)) request_render();
      return;
    }
    press_move(p, alt);
  },
  up: () => {
    if (state.handle !== null) end_handle(false);
    else press_up();
  },
  cancel: () => {
    if (state.handle !== null) end_handle(true);
    else press_cancel();
  },
  // a second finger (§5.8.2, Q18): a handle drag (ring, arrow, vertical) is cancelled; an object press that has not
  // moved CLICK_PX is cancelled (no entry, the old selection back); a running object drag ignores it
  second: () => {
    if (state.handle !== null) {
      end_handle(true);
      return "cancel";
    }
    const pr = state.press;
    if (pr === null) return "cancel";
    if (pr.tracker.second_pointer() === "ignore") return "ignore";
    press_cancel();
    return "cancel";
  },
  // a click on blank space in the observer pane (§5.8.2): the selection is cleared; P is not changed
  click: () => set_selection(null),
  hover: (p) => {
    if (hit_board_handles(p, false) !== null) return true;
    const o = obs_frame(), tip = observer?.vertical_tip ?? null;
    return o !== null && tip !== null && state.selected_id !== null && hit_vertical(o.basis, o.W, o.H, p, false, tip);
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
  const rays = ui.observerRays.checked ? vertex_rays(doc, state.scene, board, rec.near, state.selected_id) : null;
  if (state.obs.needs_framing && !state.dragging && state.A !== null) {
    // §5.8.6: framed on the eight corners of the current stage-A box (object edits do not ask for a framing)
    observer.view = frame_view(observer.view, framing_points(board, state.scene, state.A.bbox), observer.aspect);
    state.obs.needs_framing = false;
  }
  const pivot_id = pl.pivot.mode === "object" ? pl.pivot.object_id : null;
  observer.update({ board, art, rays, handles: handles_of(rig, state.scene.camera.frame_mm),
    pivot_id: pivot_id === null ? null : display_name(pivot_id, state.names), active: state.handle?.kind ?? null });
  observer.set_selection(observer_selection());
  observer.render();
  return performance.now() - t0;
}

/** The world box of object `index` now (§5.8.1): stage A's record, or, during a wireframe-preview drag, the pressed
 * frame's record translated by the drag (stage A is not re-run then). */
function current_box(index: number): Box | null {
  const sc = state.scene, A = state.A, pr = state.press;
  const obj = sc?.objects[index];
  if (obj === undefined || A === null) return null;
  if (pr !== null && pr.started && pr.preview === true && pr.index === index) {
    const b = pr.A0.objects[index]!.bbox, d = pr.shift;
    return [[b[0][0] + d[0], b[0][1] + d[1], b[0][2] + d[2]], [b[1][0] + d[0], b[1][1] + d[1], b[1][2] + d[2]]];
  }
  const rec = A.objects[index];
  return world_bbox(obj, rec !== undefined && rec.id === obj.id ? rec : null);
}

/** The observer's selection (outline, vertical handle, label `name（id）`), or null. */
function observer_selection(): ObserverSelection | null {
  const sc = state.scene, id = state.selected_id;
  if (sc === null || id === null) return null;
  const box = current_box(index_of(sc.objects, id));
  const pr = state.press;
  const len = pr !== null && pr.started && pr.kind === "vertical" && pr.id === id ? pr.len0 : null;
  return box === null ? null : { id, box, label: label_text(id, state.names), len };
}

/** The drawing pane's interface layer `#sel-overlay` (§5.8.2, §5.8.12, §5.8.14): the selected object's document
 * drawables in the accent colour, or, during a wireframe-preview drag, every object's edges (the dragged one
 * translated) through the current camera record. Never part of the writer's markup or of an output. */
function draw_sel_overlay(): void {
  const doc = state.doc, rec = state.rec, sc = state.scene, pr = state.press;
  if (doc === null || sc === null) {
    selOverlay.replaceChildren();
    return;
  }
  const cv = doc.canvas_mm;
  const vb = `0 0 ${cv[0]} ${cv[1]}`;
  if (selOverlay.getAttribute("viewBox") !== vb) selOverlay.setAttribute("viewBox", vb);
  const path = (lines: readonly (readonly (readonly number[])[])[]): string =>
    lines.map((pl) => pl.map((q, i) => { const [x, y] = svg_point(q, cv); return `${i === 0 ? "M" : "L"}${x.toFixed(3)} ${y.toFixed(3)}`; }).join("")).join("");
  let html = "";
  const wire = pr !== null && pr.started && pr.preview === true && rec !== null;
  if (wire) {
    const meshes = pr.A0.objects.map((o) => o.mesh);
    const others = wire_segments(meshes.map((m, k) => (k === pr.index ? { vertices: [], edges: [] } : m)), [], rec);
    const moved = wire_segments([meshes[pr.index]!], [pr.shift], rec);
    html += `<path class="wire" d="${path(others)}"/><path class="sel" d="${path(moved)}"/>`;
  } else if (state.selected_id !== null) {
    html += `<path class="sel" d="${path(outline_polylines(doc, state.selected_id))}"/>`;
  }
  stage.classList.toggle("wire", wire);
  selOverlay.innerHTML = html;
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

/** Show or hide the observer pane (D80: shown at page start; hidden only while "預覽" is pressed, which is the M9
 * switch-off state: the drawing pane takes the full width and the outputs are unchanged). */
function set_observer(on: boolean): void {
  state.obs.on = on;
  ui.preview.setAttribute("aria-pressed", on ? "false" : "true");
  ui.preview.textContent = on ? "預覽" : "返回編輯";
  ui.preview.title = on ? "只看作圖畫面（Esc 返回）" : "回到旁觀視角";
  ui.observerPane.hidden = !on;
  ui.observerControls.hidden = !on;
  ui.panes.classList.toggle("observer-on", on);
  if (!on) set_library(false); // an open sidebar collapses on entering 預覽 (§5.8.14)
  if (on && observer === null) {
    observer = new ObserverPane(ui.observerCanvas, ui.observerLabels);
    observer.attach_input(ui.observerPane, request_observer_render, pane_input);
    if (state.scene !== null && state.A !== null) observer.set_scene(state.scene, state.A);
  }
  layout();
  sync_controls();
  request_render(); // the resting frame: the observer is built from it (and the drawing pane re-letterboxed)
}

/** "預覽" (D80): the drawing pane alone; pressed again ("返回編輯") or Esc returns to the edit view. */
function set_preview(preview: boolean): void {
  // a held drag (observer handle or orbit) keeps the pane: hiding it mid-gesture would move the board unseen
  if (preview === !state.obs.on || state.dragging || state.handle !== null) return;
  if (preview && state.press !== null) press_cancel(); // a pending press is cancelled (§5.8.14)
  set_observer(!preview);
}
ui.preview.addEventListener("click", () => set_preview(state.obs.on));

/** The `keydown` target as the key rules read it (§5.8.10). */
function key_target(t: EventTarget | null): TargetLike | null {
  if (!(t instanceof HTMLElement)) return null;
  return { tag: t.tagName, type: t instanceof HTMLInputElement ? t.type : null, editable: t.isContentEditable };
}

// Esc, Delete / Backspace, the history shortcuts and the library toggle (§5.8.10, §5.8.11): one keydown at window;
// the equation field's own Esc stops the event first. preventDefault only when a shortcut acts.
window.addEventListener("keydown", (ev) => {
  const focus = focus_kind(key_target(ev.target), ev.target === ui.equation);
  const act = shortcut_action(ev, { has_selection: state.selected_id !== null, previewing: !state.obs.on, focus,
    gesture_open: gesture_open() });
  if (act === null) return;
  ev.preventDefault();
  if (act === "leave_preview") set_preview(false);
  else if (act === "clear_selection") set_selection(null);
  else if (act === "delete") delete_selected(true);
  else if (act === "toggle_library") set_library(!state.library_open);
  else history_step(act);
});
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
  const pr = state.press;
  if (pr !== null && pr.started && pr.preview === true) {
    preview_frame(pr, pl);
    return;
  }
  // an object drag changed the objects: one stage-A recompute per frame, the latest position wins (§5.8.12)
  const edit = state.objects_dirty;
  const a_ms = edit ? rebuild_stage_a() : 0;
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
  if (!img_mode) state.full_svg_length = svg.length;
  state.doc = doc;
  state.svg = svg;
  state.rec = rec;
  draw_sel_overlay(); // the selection outline is part of the overlay update (`dom ms`)
  const t3 = performance.now();
  if (view3d.checked) view.render(block, scene.output.canvas_mm, state.A.scene_scale);
  warnings.update(doc);
  const obs_ms = state.obs.on ? update_observer(rec, doc) : null;
  state.obs.ms = obs_ms;
  const core_ms = a_ms + (t1 - t0);
  if (edit && state.dragging) {
    // §5.8.12: the cost of a drag-mode edit frame (validate + A + B + C + SVG); the first one of a gesture with no
    // earlier measurement decides its preview mode
    state.edit_ms = core_ms;
    if (pr !== null && pr.started && pr.preview === null) pr.preview = (state.edit_ms_forced ?? core_ms) > PREVIEW_MS;
  }
  state.timings.core_ms = core_ms;
  state.timings.dom_ms = t3 - t1;
  state.timings.mode = overlay.mode;
  state.frames.push({ core_ms, dom_ms: t3 - t1, obs_ms, mode: overlay.mode, dragging: state.dragging, svg_bytes: svg.length,
    edit, preview: false });
  if (state.frames.length > 500) state.frames.shift();
  sync_controls(); // sliders, equation, readouts (the picture delta is measured here, once per frame), notices, undo
  const form = pl.scene_block ? "scene camera" : "picture_plane";
  ui.statusLine.textContent = status_text(state.sceneName, state.timings, overlay.mode, doc, scene, rec, block.focal_length_mm, form, obs_ms);
}

/** A wireframe-preview frame of an object drag (§5.8.12): no stage A, B, C or SVG; `#sel-overlay` shows the objects'
 * edges (the dragged one translated), the writer's overlay is hidden, `state.doc` / `state.svg` and the downloads keep
 * the last complete frame; the picture-delta readout follows the translated vertices (Q30). */
function preview_frame(pr: ObjectPress, pl: PlaneSession): void {
  const t0 = performance.now();
  const A0 = pr.A0, n = A0.objects[pr.index]!.mesh.vertices.length, d = pr.shift;
  const V = A0.vertices.map((v, i) => (i >= pr.offset && i < pr.offset + n ? [v[0] + d[0], v[1] + d[1], v[2] + d[2]] as Vec3 : v));
  pl.set_geometry(scene_centre(A0), object_centres(A0.objects), V);
  draw_sel_overlay();
  const t1 = performance.now();
  const obs_ms = state.obs.on && state.rec !== null && state.doc !== null ? update_observer(state.rec, state.doc) : null;
  state.obs.ms = obs_ms;
  state.frames.push({ core_ms: 0, dom_ms: t1 - t0, obs_ms, mode: overlay.mode, dragging: true, svg_bytes: state.svg.length,
    edit: true, preview: true });
  if (state.frames.length > 500) state.frames.shift();
  sync_controls();
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
      scene_block: pl.scene_block, pivot: { ...pl.pivot }, undo: pl.history.size, redo: pl.history.redo_size, delta: pl.delta,
      readouts: pl.readout_lines(), notices: pl.notices() };
  },
  /** M10: the observer-pane px of the handles, the eye and the pivot (`null` entries behind the observer). */
  get handles_px() {
    const o = obs_frame(), h = observer?.last_handles ?? null, b = observer?.last_board ?? null;
    if (o === null || h === null || b === null || observer === null) return null;
    const pr = (X: readonly number[]) => observer_project(observer!.view, o.W, o.H, X);
    return { tip: pr(h.tip), Q: pr(h.Q), ring: h.ring.map(pr), E: pr(b.E), P: pr(b.P), size: [o.W, o.H] };
  },
  /** M11: the selected object id (§5.8.1), null when none. */
  get selected() { return state.selected_id; },
  /** M11: the current stage-A box and object ids (the scene geometry after edits). */
  get scene_geometry() {
    return state.A === null || state.scene === null ? null
      : { bbox: state.A.bbox.map((p) => [...p]), ids: state.scene.objects.map((o) => o.id) };
  },
  /** M11 test hook (§5.8.3): what the release of an object drag does — move the object `id` to `position` and record
   * one `move` entry (nothing when the position is unchanged, while previewing or during a gesture). Returns whether it
   * moved. The smoke script drags with the pointer; this hook remains for scripted moves. */
  move_object: (id: string, position: [number, number, number]) => {
    const pl = state.plane, sc = state.scene;
    if (pl === null || sc === null || !state.obs.on || gesture_open()) return false;
    const index = sc.objects.findIndex((o) => o.id === id);
    const before = sc.objects[index];
    if (before === undefined) return false;
    const p0 = before.transform.position;
    if (p0[0] === position[0] && p0[1] === position[1] && p0[2] === position[2]) return false;
    const after: SceneObject = { ...before, transform: { ...before.transform, position: [position[0], position[1], position[2]] } };
    if (!apply_objects(sc.objects.map((o, i) => (i === index ? after : o)))) return false;
    pl.history.push({ kind: "move", index, id, before, after });
    set_selection(id);
    sync_controls();
    return true;
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
  /** The observer pane's hit test at pane px `(x, y)` (mouse radius; M11 priority, §5.8.2): `{kind: "arrow"}`,
   * `{kind: "ring", index}`, `{kind: "handle", id}` (the vertical handle), `{kind: "object", id}`, or null (blank). */
  hit_at: (x: number, y: number) => {
    if (state.dragging) return null;
    const t = pane_target([x, y], false);
    if (t === null || t.kind === "blank") return null;
    return t.kind === "object" ? { kind: "object", id: t.hit.id } : t;
  },
  /** M11: a pane px of the observer pane where a press (a mouse, or touch with its larger radius) grabs object `id`
   * (null when none is found). */
  object_px: (id: string, touch = false) => {
    const o = obs_frame(), pl = state.plane;
    const c = pl?.scene.object_centres.get(id);
    if (o === null || observer === null || c === undefined) return null;
    const q = observer_project(observer.view, o.W, o.H, c);
    if (q === null) return null;
    for (let r = 0; r <= 60; r += 4) {
      for (let k = 0; k < (r === 0 ? 1 : 12); k++) {
        const p: Vec2 = [q[0] + r * Math.cos((k * Math.PI) / 6), q[1] + r * Math.sin((k * Math.PI) / 6)];
        if (!(p[0] >= 2 && p[0] <= o.W - 2 && p[1] >= 2 && p[1] <= o.H - 2)) continue;
        const t = pane_target(p, touch);
        if (t !== null && t.kind === "object" && t.hit.id === id) return p;
      }
    }
    return null;
  },
  /** M11: the world point a press at observer-pane px `(x, y)` grabs on an object (null: not an object). */
  hit_point: (x: number, y: number) => {
    const t = pane_target([x, y], false);
    return t !== null && t.kind === "object" ? { id: t.hit.id, point: t.hit.point } : null;
  },
  /** M11: the observer-pane px of a world point (null behind the observer). */
  project_observer: (X: [number, number, number]) => {
    const o = obs_frame();
    return o === null || observer === null ? null : observer_project(observer.view, o.W, o.H, X);
  },
  /** M11: the world tip of the selected object's vertical handle as drawn (null without one). */
  get vertical_tip() { return observer?.vertical_tip ?? null; },
  /** M11: the observer-pane px of the selected object's vertical-handle tip (null without one). */
  get vertical_px() {
    const o = obs_frame(), tip = observer?.vertical_tip ?? null;
    return o === null || tip === null || observer === null ? null : observer_project(observer.view, o.W, o.H, tip);
  },
  /** M11: the drawing-pane px (relative to `#stage`) of object `id`'s box centre through the last camera record. */
  stage_object_px: (id: string) => {
    const c = state.plane?.scene.object_centres.get(id), rec = state.rec, doc = state.doc;
    if (c === undefined || rec === null || doc === null) return null;
    const P = rec.P, w = P[2][0] * c[0] + P[2][1] * c[1] + P[2][2] * c[2] + P[2][3];
    const u = (P[0][0] * c[0] + P[0][1] * c[1] + P[0][2] * c[2] + P[0][3]) / w;
    const v = (P[1][0] * c[0] + P[1][1] * c[1] + P[1][2] * c[2] + P[1][3]) / w;
    const [x, y] = svg_point([u, v], doc.canvas_mm);
    const b = stage.getBoundingClientRect(), k = Math.min(b.width / doc.canvas_mm[0], b.height / doc.canvas_mm[1]);
    return [b.width / 2 + (x - doc.canvas_mm[0] / 2) * k, b.height / 2 + (y - doc.canvas_mm[1] / 2) * k];
  },
  /** M11: the page's objects (ids and anchors), the display names, the library and the chip (read-only). */
  get objects() { return state.scene === null ? [] : state.scene.objects.map((o) => ({ id: o.id, type: o.type, position: [...o.transform.position] })); },
  get scene_objects_json() { return state.scene === null ? null : JSON.stringify(state.scene.objects); },
  get names() { return Object.fromEntries(state.names); },
  get library() {
    return { open: state.library_open, inert: ui.lib.inert, tab_hidden: ui.libTab.hidden, expanded: ui.libTab.getAttribute("aria-expanded"),
      tiles: ui.libGrid.querySelectorAll("button.tile").length };
  },
  get chip() {
    return { hidden: ui.chip.hidden, name: ui.chipName.textContent, pos: ui.chipPos.textContent, delete_disabled: ui.selDelete.disabled,
      hint_hidden: ui.chipHint.hidden };
  },
  /** M11: `#sel-overlay`'s markup (the selection outline / the drag wireframe) and the observer's selection group. */
  get sel_overlay() { return selOverlay.innerHTML; },
  get selection_names() { return observer?.selection_names ?? []; },
  get press() { const pr = state.press; return pr === null ? null : { kind: pr.kind, id: pr.id, started: pr.started, preview: pr.preview }; },
  /** M11 test hook (§5.8.17 "performance"): force the cost that decides the wireframe preview (null: measured). */
  force_edit_ms: (ms: number | null) => { state.edit_ms_forced = ms; },
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
  /** D80: press / release "預覽" (the observer pane hidden / shown) as a user would. */
  set_preview: (preview: boolean) => {
    if (preview === state.obs.on) ui.preview.click();
  },
  /** M9: show / hide the observer pane (`set_preview(!on)`). */
  set_observer: (on: boolean) => {
    if (on !== state.obs.on) ui.preview.click();
  },
  /** M9: the observer's state (`null` only before startup creates it). */
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
  /** M9: the "整體顯示" button. */
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

// D80: the page always opens in the edit view (observer pane shown); the old "castplane.observer" storage key is ignored
set_preview(TOGGLES.preview);
layout();
const first = EXAMPLES.find((e) => e.name === "basic") ?? EXAMPLES[0];
if (first !== undefined) {
  examplesSelect.value = first.name;
  load(first.name, () => load_scene(first.data));
}
