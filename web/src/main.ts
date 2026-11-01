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
 */

import "./style.css";

import * as THREE from "three";

import { LAYER_IDS, compose, curved, dumps, load_scene, load_scene_text, project_scene, shadow_geometry, write_svg } from "castplane";
import type { CameraRecord, GeometryDocument, Scene, SceneObject, StageA, Transform, Vec2, Vec3 } from "castplane";

import { display_colours, display_colours_text } from "./colours.js";
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
import {
  LIVE_STAGE_A_MS, ObjectDrag, clone_transform, format_angle, ground_transform, object_rings, parse_angle, ring_drag_angle,
  ring_radius, same_transform, set_rotation, snap_angle, world_centre,
} from "./object_rotate.js";
import type { Axis, ObjectRings } from "./object_rotate.js";
import { IMG_MODE_THRESHOLD, Overlay } from "./overlay.js";
import type { OverlayMode } from "./overlay.js";
import { PlaneSession, arrow_drag, object_centres, ring_drag, ring_grab } from "./plane.js";
import { arrowScreenVector, clone, equation, sync } from "./rig.js";
import type { RigState, RingGrab, ViewName } from "./rig.js";
import { build_scene3d, built_in_world, display_matrix, set_object_matrix } from "./scene3d.js";
import { Stage3D, letterbox } from "./stage.js";
import { initial_toggles } from "./toggles.js";
import {
  $, WarningsTable, build_layer_boxes, controls, describe_error, fill_examples, fill_object_select, fill_quick_equations,
  object_centre_text, save, set_error_panel, set_lines, set_rig_controls, status_text, umbra_count,
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
}

interface State {
  scene: Scene | null;
  sceneName: string;
  /** The loaded raw scene's display colours by object id (`colours.ts`; the validated scene drops the key, §2.0). */
  colours: Map<string, number>;
  A: StageA | null;
  /** The plane-mode session of the loaded scene (M10, §5.7.7): the rig, undo, pivot, readouts. */
  plane: PlaneSession | null;
  /** The checked layer checkboxes: page-level, kept across scene loads (`toggles.ts`). */
  layersChecked: Set<string>;
  doc: GeometryDocument | null;
  svg: string;
  /** `stage_a_ms`: the last stage A (the load's, or M11 an object rotation's); `stage_a_runs`: stage A runs since the
   * load (1 at load). */
  timings: { stage_a_ms: number; stage_a_runs: number; core_ms: number; dom_ms: number; mode: OverlayMode };
  dragging: boolean;
  dirty: boolean;
  full_svg_length: number;
  frames: FrameRecord[];
  /** The camera record of the last frame (the observer reads it, §5.6.2). */
  rec: CameraRecord | null;
  /** M9 observer (contract §5.6): whether a framing is pending, its last cost. */
  obs: { on: boolean; needs_framing: boolean; ms: number | null };
  /** M10: the handle being dragged in the observer pane, with its pointer-down state (§5.7.8 items 1, 4). */
  handle: { kind: "ring"; rig0: RigState; grab: RingGrab } | { kind: "arrow"; rig0: RigState; v: Vec2 }
    | { kind: "object"; id: string; axis: Axis; t0: Transform; A0: StageA; w: Vec3; r_c: Vec3; u_c: Vec3 } | null;
  /** M10: the last equation error (the field turns red with it), null when none. */
  equation_error: string | null;
  /** M11 (contract §5.8): the scene and stage-A record as loaded (the 3D groups' geometry; 還原此物體), stage A's time
   * at load (the slow-scene rule), the rotate mode and the selected object, and whether the error panel shows a failed
   * stage-A recompute. */
  loaded: { scene: Scene; A: StageA } | null;
  load_stage_a_ms: number;
  rotate: { on: boolean; id: string | null };
  object_error: boolean;
}

const state: State = {
  scene: null,
  sceneName: "",
  colours: new Map(),
  A: null,
  plane: null,
  layersChecked: new Set(TOGGLES.layers),
  doc: null,
  svg: "",
  timings: { stage_a_ms: 0, stage_a_runs: 0, core_ms: 0, dom_ms: 0, mode: "dom" },
  dragging: false,
  dirty: false,
  full_svg_length: 0,
  frames: [],
  rec: null,
  obs: { on: false, needs_framing: true, ms: null },
  handle: null,
  equation_error: null,
  loaded: null,
  load_stage_a_ms: 0,
  rotate: { on: false, id: null },
  object_error: false,
};

const ui = controls();
const { viewport, stage, canvas, examplesSelect, fileInput, focalInput, distInput, rollInput, view3d, hiddenLines, hiddenStyle } = ui;

// ---------------------------------------------------------------------------- three.js and overlay
const view = new Stage3D(canvas);
const overlay = new Overlay(stage);
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
/** Load a scene: `make` validates it; `colours` are the display colours of the same raw data
 * (`colours.ts::display_colours`), read by the caller because the validated scene does not carry them (§2.0). */
function load(name: string, make: () => Scene, colours: Map<string, number>): boolean {
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
  // M11: an object drag held across the load belongs to the old scene (forgotten, nothing restored)
  obj_drag.abandon();
  state.object_error = false;
  state.scene = scene;
  state.sceneName = name;
  state.colours = colours;
  state.A = A;
  state.loaded = { scene, A };
  state.load_stage_a_ms = stage_a_ms;
  state.timings.stage_a_ms = stage_a_ms;
  state.timings.stage_a_runs = 1;
  // §5.7.7: the rig of the load rule (scene-centre pivot); the scene camera itself is rendered until the first change.
  // M11 (§5.8.3): the objects' load-time poses give the local pivots and the 還原此物體 targets
  const records = new Map(A.objects.map((o) => [o.id, o]));
  state.plane = new PlaneSession({
    camera: scene.camera, canvas_mm: scene.output.canvas_mm, centre: scene_centre(A), object_centres: object_centres(A.objects),
    vertices: A.vertices,
    object_poses: scene.objects.map((o) => ({ id: o.id, transform: o.transform, vertices: records.get(o.id)?.mesh.vertices ?? [] })),
  });
  // M11: the object selection (the only object is preselected); the rotate mode is page-level and kept
  state.rotate.id = scene.objects.length === 1 ? scene.objects[0]!.id : null;
  fill_object_select(ui.objectSelect, scene.objects.map((o) => o.id));
  state.obs.needs_framing = true;
  // a drag held across the load (keyboard on the examples menu, a drop) belongs to the old scene: drop it
  state.handle = null;
  state.dragging = false;
  set_equation_error(null);
  ui.pivotMode.value = "scene";
  state.rec = null;
  state.full_svg_length = 0;
  state.frames = [];
  view.replace_group(() => build_scene3d(scene, A, colours));
  observer?.set_scene(scene, A, colours);
  // the layer, "Hidden lines" and "3D view" checkboxes are page-level (toggles.ts): the scene's output.layers and
  // output.hidden_lines do not reset them; the hidden style still comes from the scene
  hiddenStyle.value = scene.output.hidden_style ?? "dashed";
  sync_controls();
  sync_object_panel();
  layout();
  document.title = `${name} — castplane web`;
  request_render();
  return true;
}

function load_text(name: string, text: string): boolean {
  const ok = load(name, () => load_scene_text(text), display_colours_text(text));
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
  if (ex !== undefined) load(ex.name, () => load_scene(ex.data), display_colours(ex.data));
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
    notes.push(state.obs.on ? "請點一下左窗的物體，把它設為旋轉中心（目前暫用場景中心）" : "按「返回編輯」後點一下左窗的物體，把它設為旋轉中心（目前暫用場景中心）");
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
ui.undo.addEventListener("click", () => {
  const pl = state.plane;
  if (pl === null || state.handle?.kind === "object") return; // an object step mid-drag would race the gesture's commit
  const r = pl.undo_step();
  if (r.object !== undefined) {
    // M11 (§5.8.3): an object step is peeked, stage A recomputed, and popped only on success (else the history is kept)
    if (apply_object_transform(r.object.id, r.object.transform)) pl.pop_object_step();
    sync_controls();
    sync_object_panel();
    request_render();
    return;
  }
  after_action(r);
});
ui.reset.addEventListener("click", () => {
  if (state.plane === null) return;
  const r = state.plane.reset();
  ui.pivotMode.value = "scene";
  set_equation_error(null);
  if (observer !== null) observer.view = { ...initial_view(), target: observer.view.target, dist: observer.view.dist };
  after_action({ ...r, framing: true });
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
  // the loaded scene's display colours go back into the file (the core ignores them, §2.0)
  if (state.scene !== null && state.plane !== null) {
    save(scene_blob(state.scene, state.plane.block(), state.sceneName, hiddenLines.checked, hidden_style(), state.colours));
  }
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

const handle_input: HandleInput = {
  hit: (p, touch): HandleHit => {
    const o = obs_frame();
    if (o === null || observer === null || state.plane === null || state.dragging) return null;
    // M11 (§5.8.4): in rotate mode only the object rings are handles (the board's are hidden and disabled)
    if (state.rotate.on) {
      const rings = observer.last_object_rings;
      return rings === null ? null : hit_handles(o.basis, o.W, o.H, p, touch, null, rings);
    }
    const h = observer.last_handles;
    return h === null ? null : hit_handles(o.basis, o.W, o.H, p, touch, h);
  },
  begin: (hit) => {
    const pl = state.plane, o = obs_frame();
    if (pl === null || o === null || observer === null) return;
    if (hit.kind === "object_ring") {
      const rings = observer.last_object_rings;
      const X = rings?.rings[hit.axis][hit.index];
      if (rings === null || X === undefined) return;
      start_object_drag(rings.id, hit.axis, { w: [X[0] - rings.centre[0], X[1] - rings.centre[1], X[2] - rings.centre[2]],
        r_c: o.basis.r, u_c: o.basis.u });
      return;
    }
    const h = observer.last_handles;
    if (h === null) return;
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
    if (hd.kind === "object") {
      // §5.8.4: the ring rule of §5.7.8 item 1 from the pointer-down grab and the total displacement; only the pending
      // candidate is stored here, stage A runs at the start of the next frame (or at release)
      obj_drag.move(snap_angle(ring_drag_angle(hd.axis, hd.w, hd.r_c, hd.u_c, dx, dy), snap));
      request_render();
      return;
    }
    const next = hd.kind === "ring" ? ring_drag(hd.rig0, hd.grab, dx, dy, snap) : arrow_drag(hd.rig0, hd.v, dx, dy, snap);
    if (pl.drag(next)) request_render();
  },
  end: () => {
    if (state.handle?.kind === "object") {
      finish_object_drag();
      return;
    }
    state.plane?.end();
    state.handle = null;
    state.dragging = false;
    sync_controls();
    request_render();
  },
  cancel: () => {
    if (state.handle?.kind === "object") {
      cancel_object_drag();
      return;
    }
    state.plane?.cancel();
    state.handle = null;
    state.dragging = false;
    sync_controls();
    request_render();
  },
  click: (p) => {
    const pl = state.plane;
    if (pl === null || observer === null) return;
    if (state.rotate.on) {
      // §5.8.4: in rotate mode a click selects the object to rotate; the pivot's 「點選物體」 is suspended
      const id = observer.pick_object(p);
      if (id !== null) select_object(id);
      return;
    }
    if (pl.pivot.mode !== "object") return;
    const id = observer.pick_object(p);
    if (id !== null) after_action(pl.pick_object(id));
  },
};

// ---------------------------------------------------------------------------- M11 single-object rotation (§5.8)
/** The error panel's text when stage A throws on a rotated scene (a core bug, never a normal path; §5.8.2). */
const NOTICE_CORE_FAILED = "核心重算失敗，請回報";
/** The panel's hint for a scene whose stage A is too slow for a live drag (§5.8.2). */
const NOTICE_SLOW_SCENE = "此場景拖動放開後更新";
/** The sequence number of the last object gesture (§5.8.2: a stale number applies nothing). */
let object_seq = 0;

const object_in = (scene: Scene | null, id: string): SceneObject | undefined => scene?.objects.find((o) => o.id === id);

/** The current transform of object `id` (a copy; null when unknown). */
function current_transform(id: string | null): Transform | null {
  const o = id === null ? undefined : object_in(state.scene, id);
  return o === undefined ? null : clone_transform(o.transform);
}

/** Whether the scene is too slow at load for a live stage A during a drag (§5.8.2). */
const slow_scene = (): boolean => state.load_stage_a_ms > LIVE_STAGE_A_MS;

/** Both three.js groups (drawing pane and observer): draw object `id` at pose `t` (§5.8.2 step 4). */
function set_object_pose_3d(id: string, t: Transform): void {
  const L = state.loaded, obj0 = L === null ? undefined : object_in(L.scene, id);
  if (L === null || obj0 === undefined) return;
  const M = display_matrix({ ...obj0, transform: t }, obj0, built_in_world(obj0, L.A));
  set_object_matrix(view.group, id, M);
  set_object_matrix(observer?.stage.group ?? null, id, M);
}

/** Both three.js groups: every object at its pose in `state.scene` (after a group was rebuilt from the loaded scene). */
function sync_object_poses_3d(): void {
  for (const o of state.scene?.objects ?? []) set_object_pose_3d(o.id, o.transform);
}

/**
 * Give object `id` the pose `t` (contract §5.8.2): (1) a copy of the scene with the new `transform` (the old one is not
 * mutated, stage A's lists are shared by reference); (2) stage A on it; (3) `state.scene`, `state.A`, the timings and
 * `plane.update_scene`; (4) the 3D matrices of both groups; (5) a frame (unless `request` is false: called from the
 * frame itself). `record: "step"` adds one undo step (a discrete action). `live: false` moves only the 3D proxy. On a
 * stage-A exception nothing is committed, the 3D matrices return to the committed pose and the error panel says
 * 「核心重算失敗，請回報」. Returns whether the pose was committed.
 */
function apply_object_transform(id: string, t: Transform, record: { kind: "none" | "step" } = { kind: "none" }, live = true,
  request = true): boolean {
  const scene = state.scene, pl = state.plane, before = current_transform(id);
  if (scene === null || pl === null || before === null) return false;
  if (!live) {
    set_object_pose_3d(id, t);
    if (request) request_render();
    return true;
  }
  const scene1: Scene = { ...scene, objects: scene.objects.map((o) => o.id === id ? { ...o, transform: clone_transform(t) } : o) };
  let A1: StageA, ms: number;
  try {
    const t0 = performance.now();
    A1 = shadow_geometry(scene1);
    ms = performance.now() - t0;
  } catch (e) {
    state.object_error = true;
    show_error(`${NOTICE_CORE_FAILED}\n${describe_error(e)}`);
    set_object_pose_3d(id, before);
    if (request) request_render();
    return false;
  }
  if (state.object_error) {
    state.object_error = false;
    show_error(null);
  }
  state.scene = scene1;
  state.A = A1;
  state.timings.stage_a_ms = ms;
  state.timings.stage_a_runs += 1;
  pl.update_scene(A1.objects, A1);
  set_object_pose_3d(id, t);
  if (record.kind === "step") pl.record_object(id, before, t);
  sync_object_panel();
  if (request) request_render();
  return true;
}

/** The object-drag state machine (§5.8.2) with this page's effects. */
const obj_drag = new ObjectDrag<Scene, StageA>({
  // from `frame()` (no extra frame request) and from `end()` (the caller requests the resting frame)
  apply: (id, t) => apply_object_transform(id, t, { kind: "none" }, true, false),
  proxy: (id, t) => set_object_pose_3d(id, t),
  restore: (id, t0, scene0, A0) => {
    state.scene = scene0;
    state.A = A0;
    state.plane?.update_scene(A0.objects, A0);
    set_object_pose_3d(id, t0);
    sync_object_panel();
  },
});

/** Pointer-down of an object drag about world axis `axis` (a ring, or the `rotate_object` hook); false when it cannot
 * start (no scene, unknown id, a gesture already running). */
function start_object_drag(id: string, axis: Axis, grab: { w: Vec3; r_c: Vec3; u_c: Vec3 }): boolean {
  const pl = state.plane, scene = state.scene, A = state.A, t0 = current_transform(id), c = pl?.local_centres.get(id);
  if (pl === null || scene === null || A === null || t0 === null || c === undefined || state.dragging || state.handle !== null) return false;
  object_seq += 1;
  obj_drag.begin(id, t0, scene, A, object_seq, { live: !slow_scene(), axis, c_local: c });
  pl.begin_object(id, t0);
  state.handle = { kind: "object", id, axis, t0, A0: A, ...grab };
  state.dragging = true;
  request_render();
  return true;
}

/** Release of an object drag: the last candidate committed synchronously (§5.8.2), one undo step when it changed. */
function finish_object_drag(): void {
  const res = obj_drag.end();
  state.handle = null;
  state.dragging = false;
  if (res !== null && res.ok && res.changed) state.plane?.end_object(res.t);
  else state.plane?.cancel_object();
  sync_controls();
  sync_object_panel();
  request_render();
}

/** A second finger: the object drag is abandoned and the pointer-down state restored (§5.8.2), no step. */
function cancel_object_drag(): void {
  obj_drag.cancel();
  state.plane?.cancel_object();
  state.handle = null;
  state.dragging = false;
  sync_controls();
  sync_object_panel();
  request_render();
}

/** A discrete object action (numeric apply, 還原此物體, 落地): one undo step when the pose changed. */
function object_action(id: string, t: Transform): boolean {
  if (state.dragging || state.handle !== null) return false;
  const before = current_transform(id);
  if (before === null) return false;
  if (same_transform(before, t)) return true;
  const ok = apply_object_transform(id, t, { kind: "step" });
  sync_controls();
  return ok;
}

/** The numeric fields' pose for object `id` (spec-v0.3 §2.3): exact Euler angles `r`, the pivot fixed. */
function apply_object_rotation(id: string, r: readonly number[]): boolean {
  const t = current_transform(id), c = state.plane?.local_centres.get(id);
  if (t === null || c === undefined || !r.every((x) => Number.isFinite(x))) return false;
  return object_action(id, set_rotation(t, c, r));
}

/** 「套用」 / Enter in a field: a non-finite field turns red and nothing changes; an unedited field keeps the exact
 * current angle (the field shows it rounded to 0.1°). */
function apply_object_fields(): boolean {
  const id = state.rotate.id, t = current_transform(id);
  if (id === null || t === null) return false;
  const vals = ui.objectFields.map((el, i) => el.value === el.dataset["shown"] ? t.rotation_deg[i]! : parse_angle(el.value));
  let ok = true;
  ui.objectFields.forEach((el, i) => {
    const bad = vals[i] === null;
    el.classList.toggle("bad", bad);
    el.setAttribute("aria-invalid", bad ? "true" : "false");
    if (bad) ok = false;
  });
  if (!ok) return false;
  return apply_object_rotation(id, vals as number[]);
}

/** 落地 (spec-v0.3 §3.3; only with an unbounded `receivers[0]`): translate along its normal so that the object's minimum
 * signed distance to it is 0 (the exact surface of a curved primitive, else the stage-A vertices). */
function ground_object(id: string): boolean {
  const scene = state.scene, A = state.A, t = current_transform(id);
  const r0 = scene?.receivers[0], rec = A?.objects.find((o) => o.id === id);
  if (t === null || r0 === undefined || r0.bounds !== null || rec === undefined) return false;
  const n = r0.normal, pi = [n[0], n[1], n[2], r0.offset];
  let dmin = Infinity;
  if (rec.analytic !== null) dmin = curved.plane_min(rec.analytic, pi);
  else for (const v of rec.mesh.vertices) dmin = Math.min(dmin, n[0] * v[0] + n[1] * v[1] + n[2] * v[2] + r0.offset);
  if (!Number.isFinite(dmin) || dmin === 0) return false;
  return object_action(id, ground_transform(t, dmin, n));
}

/** Select the object to rotate (the dropdown, a click in rotate mode, the hook); null clears the selection. */
function select_object(id: string | null): void {
  if (id !== null && object_in(state.scene, id) === undefined) return;
  if (state.dragging || state.handle !== null) return;
  state.rotate.id = id;
  sync_object_panel();
  request_render();
}

/** The 轉動物體 toggle (§5.8.4): not an undo step, not stored. Ignored during a gesture. */
function set_rotate_mode(on: boolean): void {
  if (on === state.rotate.on || state.dragging || state.handle !== null) return;
  state.rotate.on = on;
  sync_object_panel();
  request_render();
}

/** The selected object's three rings in rotate mode (null without a selection). */
function object_rings_now(): ObjectRings | null {
  const id = state.rotate.id, pl = state.plane, t = current_transform(id);
  const c = id === null ? undefined : pl?.local_centres.get(id), hd = id === null ? undefined : pl?.local_half_diagonals.get(id);
  if (id === null || t === null || c === undefined || hd === undefined) return null;
  return object_rings(id, world_centre(t, c), ring_radius(hd));
}

/** The panel's 物體 section from the state: dropdown, fields (unless focused), buttons, pivot readout, slow-scene hint. */
function sync_object_panel(): void {
  const scene = state.scene, pl = state.plane, id = state.rotate.id, t = current_transform(id);
  ui.rotateMode.setAttribute("aria-pressed", state.rotate.on ? "true" : "false");
  if (ui.objectSelect.value !== (id ?? "")) ui.objectSelect.value = id ?? "";
  ui.objectFields.forEach((el, i) => {
    el.disabled = t === null;
    if (document.activeElement === el) return;
    const text = t === null ? "" : format_angle(t.rotation_deg[i]!);
    el.value = text;
    el.dataset["shown"] = text;
    el.classList.remove("bad");
    el.setAttribute("aria-invalid", "false");
  });
  ui.objectApply.disabled = t === null;
  const init = id === null ? null : pl?.initial_transform(id) ?? null;
  ui.objectRestore.disabled = t === null || init === null || same_transform(t, init);
  ui.objectGround.hidden = scene === null || scene.receivers[0]?.bounds !== null;
  ui.objectGround.disabled = t === null;
  const c = id === null ? undefined : pl?.local_centres.get(id);
  ui.objectCentre.textContent = object_centre_text(t === null || c === undefined ? null : world_centre(t, c));
  ui.objectNotice.textContent = scene !== null && slow_scene() ? NOTICE_SLOW_SCENE : "";
}

ui.rotateMode.addEventListener("click", () => set_rotate_mode(!state.rotate.on));
ui.objectSelect.addEventListener("change", () => select_object(ui.objectSelect.value === "" ? null : ui.objectSelect.value));
// 「套用」 must not take the focus first: the field's blur would re-sync it to the current pose before the click
ui.objectApply.addEventListener("mousedown", (ev) => ev.preventDefault());
ui.objectApply.addEventListener("click", () => {
  if (apply_object_fields()) (document.activeElement as HTMLElement | null)?.blur();
});
for (const el of ui.objectFields) {
  el.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      if (apply_object_fields()) el.blur();
    } else if (ev.key === "Escape") {
      ev.stopPropagation(); // the field's Esc discards the typed text only; it does not also leave 預覽
      el.blur();
    }
  });
  // leaving a field discards its typed text (and its red state)
  el.addEventListener("blur", () => sync_object_panel());
}
ui.objectRestore.addEventListener("click", () => {
  const id = state.rotate.id, t = id === null ? null : state.plane?.initial_transform(id) ?? null;
  if (id !== null && t !== null) object_action(id, t);
});
ui.objectGround.addEventListener("click", () => {
  if (state.rotate.id !== null) ground_object(state.rotate.id);
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
  // M11 (§5.8.4): in rotate mode the board's handles are hidden (null) and the selected object's rings drawn
  const hd = state.handle, rot = state.rotate.on;
  observer.update({ board, art, rays, handles: rot ? null : handles_of(rig, state.scene.camera.frame_mm),
    pivot_id: pl.pivot.mode === "object" ? pl.pivot.object_id : null,
    active: hd?.kind === "ring" || hd?.kind === "arrow" ? hd.kind : null,
    object_rings: rot ? object_rings_now() : null, active_axis: hd?.kind === "object" ? hd.axis : null });
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
  if (on && observer === null) {
    observer = new ObserverPane(ui.observerCanvas, ui.observerLabels);
    observer.attach_input(ui.observerPane, request_observer_render, handle_input);
    // the group is built from the loaded scene (M11: a mesh's geometry is the loaded world one), then posed
    if (state.loaded !== null) {
      observer.set_scene(state.loaded.scene, state.loaded.A, state.colours);
      sync_object_poses_3d();
    }
  }
  layout();
  sync_controls();
  request_render(); // the resting frame: the observer is built from it (and the drawing pane re-letterboxed)
}

/** "預覽" (D80): the drawing pane alone; pressed again ("返回編輯") or Esc returns to the edit view. */
function set_preview(preview: boolean): void {
  // a held drag (observer handle or orbit) keeps the pane: hiding it mid-gesture would move the board unseen
  if (preview === !state.obs.on || state.dragging || state.handle !== null) return;
  set_observer(!preview);
}
ui.preview.addEventListener("click", () => set_preview(state.obs.on));
window.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && !state.obs.on) set_preview(false);
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
  // M11 (§5.8.2): the pending object pose of the current gesture first (at most one stage A per frame; the 3D proxy
  // only for a slow scene); then stages B and C on the result
  obj_drag.frame();
  if (state.scene === null || state.A === null) return;
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
    return load(name, () => load_scene(ex.data), display_colours(ex.data)); // false: the error panel shows why, the previous scene stays
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
  /** M11 (contract §5.8.4): object `id`'s current transform (a copy; null when unknown). */
  object_transform: (id: string) => current_transform(id),
  /** M11: object `id`'s stage-A world vertices (`world_lists` of its record; null when unknown). */
  object_vertices: (id: string) => {
    const rec = state.A?.objects.find((o) => o.id === id);
    return rec === undefined ? null : rec.world_lists.map((v) => [v[0], v[1], v[2]]);
  },
  /** M11: object `id`'s pivot `c_w` (the centre of its local bounding box in world coordinates). */
  object_centre: (id: string) => {
    const t = current_transform(id), c = state.plane?.local_centres.get(id);
    return t === null || c === undefined ? null : world_centre(t, c);
  },
  /** M11: rotate object `id` about world axis `axis` (0 x, 1 y, 2 z) by `deg` as one drag would (begin, one move,
   * release; no snapping): one undo step when the pose changed. Returns the new transform, or null when it cannot run. */
  rotate_object: (id: string, axis: Axis, deg: number) => {
    if (!start_object_drag(id, axis, { w: [1, 0, 0], r_c: [1, 0, 0], u_c: [0, 0, 1] })) return null;
    obj_drag.move(deg);
    finish_object_drag();
    return current_transform(id);
  },
  /** M11: the numeric fields' action for object `id` (exact Euler angles, the pivot fixed): one undo step. */
  set_object_rotation: (id: string, r: [number, number, number]) => apply_object_rotation(id, r),
  /** M11: select the object to rotate (the dropdown / a click in rotate mode); null clears it. */
  select_object: (id: string | null) => select_object(id),
  /** M11: switch the 轉動物體 mode as its toggle would. */
  set_rotate_mode: (on: boolean) => set_rotate_mode(on),
  /** M11: the rotate mode, the selection, the slow-scene flag and the panel's state. */
  get rotate() {
    return { on: state.rotate.on, id: state.rotate.id, slow: slow_scene(), pressed: ui.rotateMode.getAttribute("aria-pressed"),
      fields: ui.objectFields.map((el) => ({ value: el.value, bad: el.classList.contains("bad") })),
      ground_shown: !ui.objectGround.hidden, centre: ui.objectCentre.textContent, notice: ui.objectNotice.textContent };
  },
  /** M11: the observer-pane px of the selected object's rings (per axis; `null` entries behind the observer), or null. */
  get object_rings_px() {
    const o = obs_frame(), r = observer?.last_object_rings ?? null;
    if (o === null || r === null || observer === null) return null;
    const pr = (X: readonly number[]) => observer_project(observer!.view, o.W, o.H, X);
    return { id: r.id, centre: pr(r.centre), rings: r.rings.map((ring) => ring.map(pr)), size: [o.W, o.H] };
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
  load(first.name, () => load_scene(first.data), display_colours(first.data));
}
