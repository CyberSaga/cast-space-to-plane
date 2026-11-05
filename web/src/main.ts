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
 * with the ring and arrow handles). Stages B + C + SVG (and the stage A of a dragged object pose) run in a Web Worker
 * (`core_worker.ts`, scheduled by `core_client.ts`, contract §5.4.11) when one can be started; without one the page
 * renders synchronously as before (`frame_sync`). The drawing pane (`#stage`) is view-only: no pointer or wheel listener is
 * registered on it, so drags and wheel there do nothing (the page scrolls natively); the board is moved only in the
 * observer pane and with the controls.
 */

import "./style.css";

import * as THREE from "three";

import {
  LAYER_IDS, camera_matrix, compose, curved, dumps, load_scene, load_scene_text, project_scene, shadow_geometry, write_svg,
} from "castplane";
import type { CameraRecord, GeometryDocument, Scene, SceneObject, StageA, Transform, Vec2, Vec3 } from "castplane";

import { art_frame_matrix, pack_art } from "./art_buffers.js";
import type { ArtBuffers } from "./art_buffers.js";
import { CoreClient } from "./core_client.js";
import type { PoseEntries, RenderParams, RenderedReply, RequestInfo } from "./core_client.js";
import { doc_summary_of } from "./doc_summary.js";
import type { DocSummary } from "./doc_summary.js";
import { display_colours, display_colours_text } from "./colours.js";
import {
  GROUP_VALUE_PREFIX, group_members, group_option_label, next_selection, object_groups, object_groups_text, same_selection,
  selection_of_value, selection_text, selection_value,
} from "./groups.js";
import type { Selection } from "./groups.js";
import { EXAMPLES } from "./examples.js";
import { OBJECT_ID_KEY } from "./helpers3d.js";
import { limit_for_file, object_links, object_links_text } from "./links.js";
import { canonical_angle, limit_text, refusal_text } from "./limits.js";
import type { RawLink } from "./links.js";
import { camera_block_text, json_blob, ordered_layers, scene_blob, svg_blob } from "./download.js";
import { QUICK_EQUATIONS } from "./equation.js";
import { attach_file_drop } from "./input.js";
import { focal_from_slider } from "./orbit.js";
import {
  DRAWING_OFFSET_M, derive_board, framing_points, frame_view, handles_of, hit_handles, initial_view, line_art, observer_basis,
  observer_project, rays_from_points, scene_centre, vertex_ray_points,
} from "./observer.js";
import type { HandleHit, RayPoints } from "./observer.js";
import { ObserverPane } from "./observer3d.js";
import type { HandleInput } from "./observer3d.js";
import {
  LIVE_STAGE_A_MS, UnitDrag, clone_pose, clone_transform, euler_zyx_from_matrix, format_angle, object_rings, parse_angle,
  ring_drag_angle, ring_radius, same_pose, set_group_rotation, single_pose,
  snap_angle, translate_pose, world_centre,
} from "./object_rotate.js";
import type { Axis, ObjectRings, UnitPose } from "./object_rotate.js";
import { IMG_MODE_THRESHOLD, Overlay } from "./overlay.js";
import type { OverlayMode } from "./overlay.js";
import { PlaneSession, arrow_drag, object_centres, ring_drag, ring_grab } from "./plane.js";
import { arrowScreenVector, clone, equation, sync } from "./rig.js";
import type { RigState, RingGrab, ViewName } from "./rig.js";
import { build_scene3d, built_in_world, display_matrix, set_object_matrix } from "./scene3d.js";
import { Stage3D, letterbox, set_gl_draw } from "./stage.js";
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
  /** Which document this frame applied: the core worker's `quick` (hidden lines and umbra off) or `final` reply, or a
   * synchronous render on the main thread (`sync`: the fallback, `settle()`, `probe_rig`). */
  phase: "quick" | "final" | "sync";
  /** The stage A that ran for this frame (the worker's for a new pose, or the main thread's live drag step), else null. */
  stage_a_ms: number | null;
  /** Whether this frame's overlay was applied (a drag frame of a large scene may keep the last picture, `apply_reply`). */
  overlay: boolean;
}

interface State {
  scene: Scene | null;
  sceneName: string;
  /** The loaded raw scene's display colours by object id (`colours.ts`; the validated scene drops the key, §2.0). */
  colours: Map<string, number>;
  /** D84: the loaded raw scene's group names by object id (`groups.ts::object_groups`; web-only, like the colours). */
  groups: Map<string, string>;
  /** D85: the loaded raw scene's parse-valid link keys (`parent`, `joint`) by object id (`links.ts::object_links`;
   * web-only, like the groups); the session resolves them once at load (`PlaneSession.links`). */
  links: Map<string, RawLink>;
  A: StageA | null;
  /** The plane-mode session of the loaded scene (M10, §5.7.7): the rig, undo, pivot, readouts. */
  plane: PlaneSession | null;
  /** The checked layer checkboxes: page-level, kept across scene loads (`toggles.ts`). */
  layersChecked: Set<string>;
  /** The resting document of the last synchronous render. With the core worker it is null from the moment a render is
   * posted until a `settle()` (nothing on the main thread reads the worker's documents; hooks that need one settle). */
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
    | { kind: "object"; sel: Exclude<Selection, null>; axis: Axis; pose0: UnitPose; A0: StageA; w: Vec3; r_c: Vec3; u_c: Vec3 } | null;
  /** M10: the last equation error (the field turns red with it), null when none. */
  equation_error: string | null;
  /** M11 (contract §5.8): the scene and stage-A record as loaded (the 3D groups' geometry; 還原此物體), stage A's time
   * at load (the slow-scene rule), the selection (D83: modeless, its rings are drawn whenever it is set; D84 a whole
   * group or one object), and whether the error panel shows a failed stage-A recompute. */
  loaded: { scene: Scene; A: StageA } | null;
  load_stage_a_ms: number;
  rotate: { sel: Selection };
  object_error: boolean;
  /** D83: the left pane's 「板子」 checkbox (page-level, not an undo step, not stored in the scene). */
  board_visible: boolean;
  /** D86: the refusal of the last 套用 beyond a joint limit (the part and the panel line's text), shown in red until a
   * forced panel sync (a successful action, Escape, a drag start, a selection change, a load) or the next 套用; a
   * non-forced sync keeps it, as it keeps the typed field text (review R5). */
  limit_refusal: { id: string; text: string } | null;
}

const state: State = {
  scene: null,
  sceneName: "",
  colours: new Map(),
  groups: new Map(),
  links: new Map(),
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
  rotate: { sel: null },
  object_error: false,
  board_visible: true,
  limit_refusal: null,
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
  // the <img> mode writes the checked layers: a new render (its reply carries the drawing on the frame too); the DOM
  // mode only hides layers with CSS, and the drawing on the frame follows the checkboxes
  if (overlay.mode === "img") request_render();
  else observer_refresh(true);
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
 * (`colours.ts::display_colours`), `groups` its group names (D84, `groups.ts::object_groups`), `links` its link keys
 * (D85, `links.ts::object_links`), read by the caller because the validated scene does not carry them (§2.0). */
function load(name: string, make: () => Scene, colours: Map<string, number>, groups: Map<string, string>,
  links: Map<string, RawLink>): boolean {
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
  drop_pending_overlay();
  resting_dom_ms = Infinity; // the new scene's overlay cost is measured afresh
  state.object_error = false;
  state.scene = scene;
  state.sceneName = name;
  state.colours = colours;
  state.groups = groups;
  state.links = links;
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
    groups: group_members(groups, scene.objects.map((o) => o.id)),
    links,
  });
  // D83: a load clears the object selection (none is preselected, also for a single-object scene); D84 also a group
  state.rotate.sel = null;
  fill_object_select(ui.objectSelect, scene.objects.map((o) => o.id),
    [...state.plane.groups].map(([g, ids]) => ({ value: GROUP_VALUE_PREFIX + g, label: group_option_label(g, ids.length) })));
  state.obs.needs_framing = true;
  // a drag held across the load (keyboard on the examples menu, a drop) belongs to the old scene: drop it
  state.handle = null;
  state.dragging = false;
  set_equation_error(null);
  ui.pivotMode.value = "scene";
  state.rec = null;
  state.full_svg_length = 0;
  state.frames = [];
  state.doc = null;
  last_rays = null;
  observer_set_art(EMPTY_ART);
  if (client !== null) {
    // the worker gets the validated scene (a new gen); the old scene's picture must not stay under the new 3D view
    client.load(scene, pose_entries(scene));
    overlay.clear();
  }
  view.replace_group(() => build_scene3d(scene, A, colours));
  observer?.set_scene(scene, A, colours);
  // the layer, "Hidden lines" and "3D view" checkboxes are page-level (toggles.ts): the scene's output.layers and
  // output.hidden_lines do not reset them; the hidden style still comes from the scene
  hiddenStyle.value = scene.output.hidden_style ?? "dashed";
  sync_controls();
  sync_object_panel(true);
  layout();
  document.title = `${name} — castplane web`;
  request_render();
  if (client !== null) ui.statusLine.textContent = `${name}: rendering…`;
  return true;
}

function load_text(name: string, text: string): boolean {
  const ok = load(name, () => load_scene_text(text), display_colours_text(text), object_groups_text(text), object_links_text(text));
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
  if (ex !== undefined) load(ex.name, () => load_scene(ex.data), display_colours(ex.data), object_groups(ex.data), object_links(ex.data));
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
    notes.push(pivot_hint());
  }
  set_lines(ui.notices, notes);
  // M11 review: 復原 is off while any drag is held (an undo mid-gesture would race the gesture's own step)
  ui.undo.disabled = !pl.undo.canUndo || state.dragging || state.handle !== null;
}

/** The hint for an object pivot not yet picked (D83: modeless, the click on an object picks the pivot and selects it). */
function pivot_hint(): string {
  return state.obs.on ? "請點一下左窗的物體，把它設為旋轉中心（目前暫用場景中心）" : "按「返回編輯」後點一下左窗的物體，把它設為旋轉中心（目前暫用場景中心）";
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
  // M11 review: ignored during any held drag (board or object): an undo mid-gesture would race the gesture's own step
  if (pl === null || state.dragging || state.handle !== null) return;
  const r = pl.undo_step();
  if (r.object !== undefined || r.objects !== undefined) {
    // M11 (§5.8.3): an object step is peeked, stage A recomputed, and popped only on success (else the history is kept);
    // D84: a group step restores every member and the group frame in one stage A
    const pose: UnitPose = r.object !== undefined ? single_pose(r.object.id, r.object.transform)
      : { transforms: r.objects!.transforms, group: r.objects!.group };
    if (apply_pose(pose)) pl.pop_object_step();
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
  viewDirty = true;
  request_observer_render();
});

/** Download SVG / JSON: the texts of `download.ts` for the resting document of the current camera (the core worker
 * renders it when its last document is not that one; a reply of an older scene generation is dropped). */
function download(kind: "svg" | "json"): void {
  const pl = state.plane;
  if (client !== null) {
    if (state.scene === null || pl === null) return;
    client.download({ kind, layers: ordered_layers(state.layersChecked), hidden_style: hidden_style(), hidden: hiddenLines.checked,
      umbra: true, block: pl.block(), scene_name: state.sceneName });
    return;
  }
  if (state.doc === null) return;
  save(kind === "svg" ? svg_blob(state.doc, state.layersChecked, state.sceneName, hidden_style()) : json_blob(state.doc, state.sceneName));
}
$<HTMLButtonElement>("dl-svg").addEventListener("click", () => download("svg"));
$<HTMLButtonElement>("dl-json").addEventListener("click", () => download("json"));
$<HTMLButtonElement>("dl-scene").addEventListener("click", () => {
  // the loaded scene's display colours, groups (D84) and links (D85) go back into the file (the core ignores them, §2.0)
  if (state.scene !== null && state.plane !== null) {
    save(scene_blob(state.scene, state.plane.block(), state.sceneName, hiddenLines.checked, hidden_style(), state.colours, state.groups,
      state.links));
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
    // D83 (modeless): the selected object's rings > the board's arrow tip > its ring; the board's handles are null
    // while 「板子」 is unchecked, the rings null without a selection
    return hit_handles(o.basis, o.W, o.H, p, touch, observer.last_handles, observer.last_object_rings);
  },
  begin: (hit) => {
    const pl = state.plane, o = obs_frame();
    if (pl === null || o === null || observer === null) return;
    if (hit.kind === "object_ring") {
      const rings = observer.last_object_rings;
      const X = rings?.rings[hit.axis][hit.index];
      const sel = rings === null ? null : selection_of_value(rings.id);
      if (rings === null || X === undefined || sel === null) return;
      start_unit_drag(sel, hit.axis, { w: [X[0] - rings.centre[0], X[1] - rings.centre[1], X[2] - rings.centre[2]],
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
    drag_rendered = false;
    sync_controls(); // 復原 off while the drag is held
    request_observer_render(); // nothing changed yet: the active handle is drawn thicker
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
    request_after_drag();
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
    request_after_drag();
  },
  click: (p) => {
    const pl = state.plane;
    if (pl === null || observer === null) return;
    click_object(observer.pick_object(p));
  },
};

// ---------------------------------------------------------------------------- M11 single-object rotation (§5.8), D84 groups
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

/** D84: the groups of the loaded scene with at least two members (member ids in scene order). */
const scene_groups = (): ReadonlyMap<string, readonly string[]> => state.plane?.groups ?? new Map<string, readonly string[]>();

/** The selected object as a part (null without a selection or with a whole group selected). */
const selected_part = (): string | null => state.rotate.sel?.kind === "part" ? state.rotate.sel.id : null;

/** Whether `sel` names something of the loaded scene (an object id, or a group with ≥ 2 members). */
function valid_selection(sel: Selection): boolean {
  if (sel === null) return true;
  return sel.kind === "part" ? object_in(state.scene, sel.id) !== undefined : scene_groups().has(sel.group);
}

/**
 * D84: the current pose of a unit: a part's (or ungrouped object's) transform, or every member's transform with the
 * group's frame (`G`, `c`). D85: a part with descendants gives its subtree (the part first, then its descendants in
 * preorder; `group: null`; `PlaneSession.part_pose`), a part without them its own transform as in D84. Null when
 * unknown.
 */
function unit_pose(sel: Selection, tr: (id: string) => Transform | null = current_transform,
  pending: UnitPose | null = null): UnitPose | null {
  if (sel === null) return null;
  if (sel.kind === "part") return state.plane?.part_pose(sel.id, tr) ?? null;
  const ids = scene_groups().get(sel.group);
  const frame = pending?.group != null && pending.group.name === sel.group ? pending.group : state.plane?.group_frame(sel.group) ?? null;
  if (ids === undefined || frame === null) return null;
  const transforms = new Map<string, Transform>();
  for (const id of ids) {
    const t = tr(id);
    if (t === null) return null;
    transforms.set(id, t);
  }
  return { transforms, group: frame };
}

/** D84: the load-time pose of a unit (還原此物體): the load transforms and, for a group, `G = I` and `c = c0`. D85: for a
 * part, the target of `PlaneSession.part_restore_pose` (G3): its load pose relative to its parent's current pose (a
 * root part or a lone object: its load transform exactly, as D84), its descendants carried; the current pose itself
 * when that is no action (the 1e-9 rule of a part with a parent), so 還原此物體 is disabled exactly then. */
function initial_pose(sel: Selection, tr: (id: string) => Transform | null = current_transform,
  pending: UnitPose | null = null): UnitPose | null {
  const pl = state.plane;
  if (sel?.kind === "part") return pl?.part_restore_pose(sel.id, tr) ?? null;
  const pose = unit_pose(sel, tr, pending);
  if (pose === null || pl === null) return null;
  const transforms = new Map<string, Transform>();
  for (const id of pose.transforms.keys()) {
    const t = pl.initial_transform(id);
    if (t === null) return null;
    transforms.set(id, t);
  }
  const group = pose.group === null ? null : pl.initial_group_frame(pose.group.name);
  return pose.group !== null && group === null ? null : { transforms, group };
}

/** The angles the fields show for a unit: a part's `rotation_deg`, a group's `G` decomposed (D84, display only). */
function unit_angles(pose: UnitPose | null): readonly number[] | null {
  if (pose === null) return null;
  if (pose.group !== null) return euler_zyx_from_matrix(pose.group.G);
  return [...pose.transforms.values()][0]?.rotation_deg ?? null;
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

/** Both three.js groups: every object of `pose` at its transform. */
function set_pose_3d(pose: UnitPose): void {
  for (const [id, t] of pose.transforms) set_object_pose_3d(id, t);
}

/** Both three.js groups: every object at its pose in `state.scene` (after a group was rebuilt from the loaded scene). */
function sync_object_poses_3d(): void {
  for (const o of state.scene?.objects ?? []) set_object_pose_3d(o.id, o.transform);
}

/**
 * Give the objects of `pose` their transforms (contract §5.8.2; D84 one or more objects and a group frame): (1) a copy
 * of the scene with the new `transform`s (the old one is not mutated, stage A's lists are shared by reference); (2)
 * stage A on it; (3) `state.scene`, `state.A`, the timings, `plane.update_scene` and the group frame; (4) the 3D
 * matrices of both groups; (5) a frame (unless `request` is false: called from the frame itself). `record: "step"` adds
 * one undo step (a discrete action: an object step for one object without a frame, else a group step with every
 * member and the frame). `live: false` moves only the 3D proxy. On a stage-A exception nothing is committed, the 3D
 * matrices return to the committed pose and the error panel says 「核心重算失敗，請回報」. Returns whether the pose was
 * committed.
 */
function apply_pose(pose: UnitPose, record: { kind: "none" | "step" } = { kind: "none" }, live = true, request = true): boolean {
  const scene = state.scene, pl = state.plane;
  if (scene === null || pl === null || pose.transforms.size === 0) return false;
  const before = new Map<string, Transform>();
  for (const id of pose.transforms.keys()) {
    const t = current_transform(id);
    if (t === null) return false;
    before.set(id, t);
  }
  const frame_before = pose.group === null ? null : pl.group_frame(pose.group.name);
  if (!live) {
    set_pose_3d(pose);
    if (request) request_render();
    return true;
  }
  const scene1: Scene = { ...scene, objects: scene.objects.map((o) => {
    const t = pose.transforms.get(o.id);
    return t === undefined ? o : { ...o, transform: clone_transform(t) };
  }) };
  let A1: StageA, ms: number;
  try {
    const t0 = performance.now();
    A1 = shadow_geometry(scene1);
    ms = performance.now() - t0;
  } catch (e) {
    state.object_error = true;
    show_error(`${NOTICE_CORE_FAILED}\n${describe_error(e)}`);
    for (const [id, t] of before) set_object_pose_3d(id, t);
    if (request) request_render();
    return false;
  }
  if (state.object_error) {
    state.object_error = false;
    show_error(null);
  }
  state.scene = scene1;
  publish_pose(); // the worker's scene follows (nothing is posted when it already holds this pose: a drag's last candidate)
  state.A = A1;
  state.timings.stage_a_ms = ms;
  state.timings.stage_a_runs += 1;
  pl.update_scene(A1.objects, A1);
  if (pose.group !== null) pl.set_group_frame(pose.group);
  set_pose_3d(pose);
  if (record.kind === "step") {
    if (pose.group === null && pose.transforms.size === 1) {
      const [id, t] = [...pose.transforms][0]!;
      pl.record_object(id, before.get(id)!, t);
    } else pl.record_objects(before, frame_before, pose.transforms, pose.group);
  }
  sync_object_panel();
  if (request) request_render();
  return true;
}

/** The object-drag state machine (§5.8.2; D84 on a unit pose) with this page's effects. */
const obj_drag = new UnitDrag<Scene, StageA>({
  // from `frame()` (no extra frame request) and from `end()` (the caller requests the resting frame)
  apply: (pose) => apply_pose(pose, { kind: "none" }, true, false),
  // D86 review R8: a slow scene runs no stage A during a drag, so the joint-limit line follows the candidate here. With
  // the core worker every drag is a proxy drag: the panel (fields, c_w readout, limit line) reads the candidate, and the
  // candidate goes to the worker with the next render request (`render_params`), which runs its stage A
  proxy: (pose) => {
    set_pose_3d(pose);
    if (client !== null) sync_object_panel(false, pose);
    else if (selected_part() !== null) render_object_limit(pose);
  },
  restore: (pose0, scene0, A0) => {
    state.scene = scene0;
    publish_pose();
    state.A = A0;
    state.plane?.update_scene(A0.objects, A0);
    if (pose0.group !== null) state.plane?.set_group_frame(pose0.group);
    set_pose_3d(pose0);
    sync_object_panel();
  },
});

/** Pointer-down of a drag of unit `sel` about world axis `axis` (a ring, or the `rotate_object` / `rotate_group`
 * hooks); false when it cannot start (no scene, unknown unit, a gesture already running). D85: a part with a joint or
 * descendants turns its whole subtree about one world point, `PlaneSession.part_pivot` at the pointer-down pose (its
 * world joint, else its `c_w`); any other part keeps the M11 per-object path (no pivot passed). One object opens an
 * object step, several (a group, or a part's subtree) an `objects` step (`group: null` for a subtree). */
function start_unit_drag(sel: Exclude<Selection, null>, axis: Axis, grab: { w: Vec3; r_c: Vec3; u_c: Vec3 }): boolean {
  const pl = state.plane, scene = state.scene, A = state.A, pose0 = unit_pose(sel);
  if (pl === null || scene === null || A === null || pose0 === null || state.dragging || state.handle !== null) return false;
  const c_locals = new Map<string, Vec3>();
  if (pose0.group === null) {
    for (const id of pose0.transforms.keys()) {
      const c = pl.local_centres.get(id);
      if (c === undefined) return false;
      c_locals.set(id, c);
    }
  }
  const t_sel = sel.kind === "part" ? pose0.transforms.get(sel.id) : undefined;
  const pivot = sel.kind !== "part" || t_sel === undefined ? null : pl.part_pivot(sel.id, t_sel);
  // D86: a part with a joint limit gets the closed-form clamp of the drag angle (null: the D85 path bit for bit)
  const clamp = sel.kind !== "part" || t_sel === undefined ? null : pl.part_drag_clamp(sel.id, axis, t_sel, current_transform);
  object_seq += 1;
  // with the core worker the drag only moves the proxies on the main thread (`live: false`); the worker runs the
  // candidate's stage A and the release commits it synchronously (§5.8.2)
  obj_drag.begin(pose0, scene, A, object_seq, { live: client === null && !slow_scene(), axis, c_locals, pivot, clamp });
  // D85: the step's kind follows the number of objects (as `apply_pose`'s record): `end_object` refuses an `objects`
  // step, so a subtree opened as one object would record nothing
  if (pose0.group === null && pose0.transforms.size === 1) {
    const [id, t0] = [...pose0.transforms][0]!;
    pl.begin_object(id, t0);
  } else pl.begin_objects(pose0.transforms, pose0.group);
  state.handle = { kind: "object", sel, axis, pose0: clone_pose(pose0), A0: A, ...grab };
  state.dragging = true;
  drag_rendered = false;
  // M11 review: a drag drops any typed angle and the field's focus, so the fields follow the pose while it turns
  blur_object_field();
  sync_object_panel(true);
  sync_controls(); // 復原 off while the drag is held
  request_observer_render(); // nothing changed yet: the active ring is drawn thicker
  return true;
}

/** Release of an object drag: the last candidate committed synchronously (§5.8.2), one undo step when it changed. */
function finish_object_drag(): void {
  const res = obj_drag.end();
  state.handle = null;
  state.dragging = false;
  if (res !== null && res.ok && res.changed) {
    if (res.pose.group === null && res.pose.transforms.size === 1) state.plane?.end_object([...res.pose.transforms.values()][0]!);
    else state.plane?.end_objects(res.pose.transforms, res.pose.group);
  } else state.plane?.cancel_object();
  sync_controls();
  sync_object_panel();
  if (res !== null && res.ok && res.changed) request_render();
  else request_after_drag();
}

/** A second finger: the object drag is abandoned and the pointer-down state restored (§5.8.2), no step. */
function cancel_object_drag(): void {
  obj_drag.cancel();
  state.plane?.cancel_object();
  state.handle = null;
  state.dragging = false;
  sync_controls();
  sync_object_panel();
  request_after_drag();
}

/** A discrete action on a unit (numeric apply, 還原此物體, 落地): one undo step when the pose changed. */
function unit_action(after: UnitPose): boolean {
  if (state.dragging || state.handle !== null) return false;
  const pl = state.plane;
  if (pl === null) return false;
  const before: UnitPose = { transforms: new Map(), group: after.group === null ? null : pl.group_frame(after.group.name) };
  for (const id of after.transforms.keys()) {
    const t = current_transform(id);
    if (t === null) return false;
    before.transforms.set(id, t);
  }
  blur_object_field();
  const ok = same_pose(before, after) || apply_pose(after, { kind: "step" });
  // M11 review: a successful action resets every field to the pose (typed entries applied or superseded)
  if (ok) sync_object_panel(true);
  sync_controls();
  return ok;
}

/** The numeric fields' pose for object `id` (spec-v0.3 §2.3): exact Euler angles `r`, the pivot fixed. D85
 * (`PlaneSession.part_numeric_pose`): a part with a joint or descendants gets `r` about its pivot and its subtree the
 * same rotation (`object_rotate.ts::set_part_rotation`; `r` equal to its angles is no action, G4); any other object
 * the M11 `set_rotation` about its `c_w`. D86: a target whose joint-limit angle is outside the range is refused, never
 * clamped (no stage A, no step; `state.limit_refusal` names the angle and the bound, and for the selected part the
 * limit line and the three fields turn red); a target inside, a bound included, is applied verbatim. A 套用 that
 * changes nothing is no action and is not checked. */
function apply_object_rotation(id: string, r: readonly number[]): boolean {
  if (!r.every((x) => Number.isFinite(x))) return false;
  const pl = state.plane;
  const after = pl?.part_numeric_pose(id, r, current_transform) ?? null;
  if (pl === null || after === null || state.dragging || state.handle !== null) return false;
  const chk = pl.part_limit_check(id, after, current_transform), now = pl.part_pose(id, current_transform);
  if (chk !== null && !chk.inside && (now === null || !same_pose(now, after))) {
    state.limit_refusal = { id, text: refusal_text(pl.limit(id)!, chk.phi, pl.parent_of(id)!) };
    render_object_limit();
    return false;
  }
  return unit_action(after);
}

/** D84: the numeric fields' pose for group `name`: its rotation relative to the load becomes `euler_zyx_matrix(r)`,
 * every member turned about `c` (`object_rotate.ts::set_group_rotation`). */
function apply_group_rotation(name: string, r: readonly number[]): boolean {
  const pose = unit_pose({ kind: "group", group: name });
  if (pose === null || !r.every((x) => Number.isFinite(x))) return false;
  return unit_action(set_group_rotation(pose, r));
}

/** 「套用」 / Enter in a field: a non-finite field turns red and nothing changes; an unedited field keeps the exact
 * current angle (the field shows it rounded to 0.1°). */
function apply_object_fields(): boolean {
  const sel = state.rotate.sel, cur = unit_angles(unit_pose(sel));
  if (sel === null || cur === null) return false;
  // D86: every 套用 re-decides; the previous refusal goes (a refused entry sets it again)
  if (state.limit_refusal !== null) {
    state.limit_refusal = null;
    render_object_limit();
  }
  const vals = ui.objectFields.map((el, i) => el.value === el.dataset["shown"] ? cur[i]! : parse_angle(el.value));
  let ok = true;
  ui.objectFields.forEach((el, i) => {
    const bad = vals[i] === null;
    el.classList.toggle("bad", bad);
    el.setAttribute("aria-invalid", bad ? "true" : "false");
    if (bad) ok = false;
  });
  if (!ok) return false;
  // D84 review: 套用 with no field edited is not an action (no undo step, no ulp drift of a group's members); the loop
  // above has already cleared any stale red state
  if (ui.objectFields.every((el) => !field_edited(el))) return true;
  return sel.kind === "group" ? apply_group_rotation(sel.group, vals as number[]) : apply_object_rotation(sel.id, vals as number[]);
}

/** 落地 (spec-v0.3 §3.3; only with an unbounded `receivers[0]`): translate along its normal so that the unit's minimum
 * signed distance to it is 0 (the exact surface of a curved primitive, else the stage-A vertices). D84: a group moves
 * as one, by the minimum over all its members, and its `c` with it. D85: a root part with descendants moves its
 * subtree as one; the button is hidden for a part with a parent (`sync_object_panel`) and the function refuses it too. */
function ground_unit(sel: Selection): boolean {
  // D85 review: the function enforces the rule the panel shows, so a script click on the hidden button moves nothing
  if (sel?.kind === "part" && state.plane?.parent_of(sel.id) !== null) return false;
  const scene = state.scene, A = state.A, pose = unit_pose(sel);
  const r0 = scene?.receivers[0];
  if (pose === null || A === null || r0 === undefined || r0.bounds !== null) return false;
  const n = r0.normal, pi = [n[0], n[1], n[2], r0.offset];
  let dmin = Infinity;
  for (const id of pose.transforms.keys()) {
    const rec = A.objects.find((o) => o.id === id);
    if (rec === undefined) return false;
    if (rec.analytic !== null) dmin = Math.min(dmin, curved.plane_min(rec.analytic, pi));
    else for (const v of rec.mesh.vertices) dmin = Math.min(dmin, n[0] * v[0] + n[1] * v[1] + n[2] * v[2] + r0.offset);
  }
  if (!Number.isFinite(dmin) || dmin === 0) return false;
  return unit_action(translate_pose(pose, [-dmin * n[0], -dmin * n[1], -dmin * n[2]]));
}

/** 還原此物體: the unit back to its load pose (D84: a group's every member, `G = I`, `c = c0`; a part only itself; D85
 * a part back to its load pose relative to its parent, its subtree carried, `initial_pose`). */
function restore_unit(sel: Selection): boolean {
  const init = initial_pose(sel);
  return init !== null && unit_action(init);
}

/**
 * Select what to rotate (the dropdown, a click in the left pane, the hooks); null clears the selection. D84: a whole
 * group or one object (a part).
 */
function select(sel: Selection): void {
  if (!valid_selection(sel)) return;
  if (state.dragging || state.handle !== null) return;
  // D83 review: re-selecting the selection (a second click on an ungrouped object, e.g. to re-pick the pivot) is not a
  // selection change, so typed angle text survives it (the M11 review rule); only a real change rewrites every field
  const changed = !same_selection(sel, state.rotate.sel);
  state.rotate.sel = sel;
  sync_object_panel(changed);
  request_observer_render(); // the rings: the picture does not depend on the selection
}

/** Select object `id` as a part (M11 / D83: also a grouped object; `click_object` runs the D84 click cycle). */
function select_object(id: string | null): void {
  select(id === null ? null : { kind: "part", id });
}

/**
 * A left-pane click on object `id` (null: blank space). D84 click cycle (`groups.ts::next_selection`): an object of a
 * group with ≥ 2 members selects the whole group first, the clicked part on the next click, the whole group again on
 * the next, …; another part of the same group moves the focus to it; an ungrouped object is selected as in D83. Blank
 * space clears the selection (the pivot is kept). With 旋轉中心 = 點選物體 the click also sets the pivot to the newly
 * selected unit's centre (a group's `c`, a part's stage-A bbox centre; no undo step, §5.7.8 item 10).
 */
function click_object(id: string | null): void {
  const pl = state.plane;
  if (pl === null || state.dragging || state.handle !== null) return;
  if (id === null || object_in(state.scene, id) === undefined) {
    select(null);
    return;
  }
  const next = next_selection(state.rotate.sel, id, state.groups, scene_groups());
  if (pl.pivot.mode === "object" && next !== null) {
    // a pivot pick moves the board's pivot, not the camera: a core render only if the block changed after all
    const block0 = JSON.stringify(pl.block());
    const r = next.kind === "group" ? pl.pick_group(next.group) : pl.pick_object(next.id);
    if (JSON.stringify(pl.block()) !== block0) after_action(r);
    else {
      if (r.framing) state.obs.needs_framing = true;
      sync_controls();
    }
  }
  select(next);
}

/** The selected unit's three rings (null without a selection; D83: drawn whenever something is selected). D84: a
 * group's rings are centred on its `c`, radius from its load-time world bounding box (larger than a part's). D85: a
 * part's rings are centred on its pivot (`PlaneSession.pivot_local`: its world joint, else its `c_w`), radius from
 * its own local bounding box as before. */
function object_rings_now(): ObjectRings | null {
  const sel = state.rotate.sel, pl = state.plane;
  if (sel === null || pl === null) return null;
  if (sel.kind === "group") {
    const f = pl.group_frame(sel.group), l = pl.group_loads.get(sel.group);
    return f === null || l === undefined ? null : object_rings(selection_value(sel), f.c, ring_radius(l.half_diagonal));
  }
  const id = sel.id, t = current_transform(id);
  const c = pl.pivot_local(id), hd = pl.local_half_diagonals.get(id);
  if (t === null || c === null || hd === undefined) return null;
  return object_rings(id, world_centre(t, c), ring_radius(hd));
}

/** The pivot's label name in the observer: an object id, or 「<name>（整組）」 for a group (D84). */
function pivot_label(key: string | null): string | null {
  return key !== null && key.startsWith(GROUP_VALUE_PREFIX) ? `${key.slice(GROUP_VALUE_PREFIX.length)}（整組）` : key;
}

/** Whether angle field `el` holds typed text (its text differs from the one the panel last wrote). */
const field_edited = (el: HTMLInputElement): boolean => el.value !== (el.dataset["shown"] ?? "");

/** Take the focus off an angle field (a drag or a discrete object action), so the field shows the pose afterwards. */
function blur_object_field(): void {
  const a = document.activeElement;
  if (a instanceof HTMLInputElement && ui.objectFields.includes(a)) a.blur();
}

/**
 * The panel's 物體 section from the state: dropdown, selection line, fields, buttons, pivot readout, slow-scene hint.
 * M11 review: the three angle fields are one entry, so a field with typed text (`field_edited`) keeps its text and red
 * state until 「套用」 / Enter applies it; `force` rewrites every field from the pose (a successful object action,
 * Escape, a drag start, a selection change, a scene load). Focus alone never protects a field: an unedited focused
 * field follows the pose. D84: for a whole group the fields show its rotation relative to the load and the readout its
 * pivot `c`. D85: a part's line counts the parts it carries, the readout names its pivot (「關節 j_w」 for a joint, else
 * 「中心 c_w」), and 落地 is hidden for a part with a parent.
 */
function sync_object_panel(force = false, pending: UnitPose | null = null): void {
  // the core worker's proxy drag: the candidate's transforms first (the ids it holds), the committed scene for the rest
  const tr = (id: string): Transform | null => {
    const t = pending?.transforms.get(id);
    return t !== undefined ? clone_transform(t) : current_transform(id);
  };
  const scene = state.scene, pl = state.plane, sel = state.rotate.sel, pose = unit_pose(sel, tr, pending), angles = unit_angles(pose);
  if (force) state.limit_refusal = null;
  const value = selection_value(sel);
  if (ui.objectSelect.value !== value) ui.objectSelect.value = value;
  const carried = sel?.kind === "part" && pl !== null ? pl.subtree(sel.id).length - 1 : 0;
  ui.objectSelected.textContent = selection_text(sel, state.groups, scene_groups(), carried);
  ui.objectFields.forEach((el, i) => {
    el.disabled = angles === null;
    if (!force && angles !== null && field_edited(el)) return;
    const text = angles === null ? "" : format_angle(angles[i]!);
    el.value = text;
    el.dataset["shown"] = text;
    el.classList.remove("bad");
    el.setAttribute("aria-invalid", "false");
  });
  ui.objectApply.disabled = pose === null;
  const init = initial_pose(sel, tr, pending);
  ui.objectRestore.disabled = pose === null || init === null || same_pose(pose, init);
  // D85: a translation cannot keep a part's joint on its unmoved parent, so 落地 is offered for a group, a lone object
  // and a root part only
  ui.objectGround.hidden = scene === null || scene.receivers[0]?.bounds !== null
    || (sel?.kind === "part" && pl !== null && pl.parent_of(sel.id) !== null);
  ui.objectGround.disabled = pose === null;
  let centre: Vec3 | null = null, joint = false;
  if (pose?.group != null) centre = pose.group.c;
  else if (sel?.kind === "part") {
    const t = tr(sel.id), c = pl?.pivot_local(sel.id) ?? null;
    centre = t === null || c === null ? null : world_centre(t, c);
    joint = centre !== null && pl?.joint(sel.id) != null;
  }
  ui.objectCentre.textContent = object_centre_text(centre, joint);
  render_object_limit(pending);
  // the slow-scene rule is the synchronous path's: with the core worker every drag runs its stage A off the main thread
  ui.objectNotice.textContent = scene !== null && slow_scene() && client === null ? NOTICE_SLOW_SCENE : "";
}

/**
 * D86: the panel's joint-limit line for the selected part: while a refusal of a 套用 on it stands
 * (`state.limit_refusal`), its text in red with the three fields red too; else 「關節限制：繞 <parent> 的 (x, y, z) 軸
 * <range>，目前 <φ>°」 (`limits.ts::limit_text`) of the part against its parent at their current transforms, or, on a slow
 * scene during a drag, with the transforms of the pending candidate `pending` taken first (review R8: the part, or its
 * parent when the part is carried in the dragged subtree). Empty for anything but a part with a resolved limit.
 */
function render_object_limit(pending: UnitPose | null = null): void {
  const pl = state.plane, id = selected_part();
  const cur = (k: string): Transform | null => {
    const t = pending?.transforms.get(k);
    return t !== undefined ? clone_transform(t) : current_transform(k);
  };
  const lim = id === null || pl === null ? null : pl.limit(id), par = id === null || pl === null ? null : pl.parent_of(id);
  let text = "", bad = false;
  if (pl !== null && id !== null && lim !== null && par !== null) {
    const ref = state.limit_refusal;
    if (ref !== null && ref.id === id) {
      text = ref.text;
      bad = true;
    } else {
      const t = cur(id), a = t === null ? null : pl.part_limit_at(id, t, cur);
      if (a !== null) text = limit_text(lim, a.phi, par);
    }
  }
  ui.objectLimit.textContent = text;
  ui.objectLimit.classList.toggle("bad", bad);
  if (bad) {
    for (const el of ui.objectFields) {
      el.classList.add("bad");
      el.setAttribute("aria-invalid", "true");
    }
  }
}

ui.objectSelect.addEventListener("change", () => select(selection_of_value(ui.objectSelect.value)));
// 「套用」 does not take the focus: a red field keeps its caret for the correction
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
      ev.stopPropagation(); // the fields' Esc discards the typed angles only; it does not also leave 預覽
      sync_object_panel(true);
      el.blur();
    }
  });
  // M11 review: leaving a field keeps its typed text (the three fields are one entry, applied together)
}
ui.objectRestore.addEventListener("click", () => restore_unit(state.rotate.sel));
ui.objectGround.addEventListener("click", () => ground_unit(state.rotate.sel));

// ---------------------------------------------------------------------------- layout (letterboxed to canvas_mm)
function layout(): void {
  const aspect = state.scene ? state.scene.output.canvas_mm[0] / state.scene.output.canvas_mm[1] : 3 / 2;
  const [w, h] = letterbox(viewport, stage, aspect);
  view.set_size(w, h);
  if (state.obs.on && observer !== null) observer.set_size(ui.observerPane.clientWidth, ui.observerPane.clientHeight);
}
/** The observer needs a redraw without a core render (`request_observer_render`). */
let obsDirty = false;
/** The drawing pane's three.js view needs a redraw without a core render (a resize, the 3D-view checkbox). */
let viewDirty = false;
// a resize changes no document (the overlay scales with its viewBox): only the two three.js views are redrawn
const resize = new ResizeObserver(() => {
  layout();
  viewDirty = true;
  request_observer_render();
});
resize.observe(viewport);
resize.observe(ui.observerPane);

// ---------------------------------------------------------------------------- observer (M9, contract §5.6)

/** The drawing on the frame of no document (a load, before its first render). */
const EMPTY_ART: ArtBuffers = { lines: [], fills: [] };

/** The drawing the observer shows (canvas mm, `art_buffers.ts`): the last applied document's, kept here so that a pane
 * created later (`set_observer`) starts with it. */
let last_art: ArtBuffers = EMPTY_ART;

/** Hand the observer a new drawing on the frame (`ObserverPane.set_art`). */
function observer_set_art(art: ArtBuffers): void {
  last_art = art;
  observer?.set_art(art);
}

/** The world points of the vertex rays of the last applied document (`observer.ts::vertex_ray_points`). */
let last_rays: RayPoints | null = null;

/**
 * Update the observer from the current state and draw it (§5.6.2, §5.6.5): the board of the rig on the record of the
 * current block (`camera_matrix`, so the board and the drawing's placement move at once with the camera; the drawing's
 * content is the last document's), the handles, the selected unit's rings, the vertex rays of the last document's
 * points, and the drawing's frame matrix; frame it when a framing is pending and no drag is running (§5.6.4). Returns
 * the observer's own cost in ms.
 */
function update_observer(): number {
  const pl = state.plane, scene = state.scene;
  if (observer === null || scene === null || pl === null) return 0;
  const t0 = performance.now();
  const rig = pl.rig, d = sync(rig);
  let rec: CameraRecord;
  try {
    rec = camera_matrix(pl.block() as Parameters<typeof camera_matrix>[0], scene.output.canvas_mm);
  } catch {
    return 0; // a block the core refuses: its render reports the error; the observer keeps its last frame
  }
  // M10: the board of the rig (§5.6.5): pivot P, R = g + D, D of the rig; the frame from the current record
  const board = derive_board(rec, { target: rig.P, distance: d.R }, rig.D);
  const rays = ui.observerRays.checked && last_rays !== null ? rays_from_points(last_rays, scene, board, rec.near) : null;
  const shown = state.board_visible;
  if (state.obs.needs_framing && !state.dragging) {
    observer.view = frame_view(observer.view, framing_points(board, scene, pl.scene.centre), observer.aspect);
    state.obs.needs_framing = false;
  }
  // D83: the board's handles and the selected object's rings are drawn together (modeless); 「板子」 unchecked hides the
  // board group and its labels and passes no board handles (not hit-tested, not hover-highlighted)
  const hd = state.handle;
  observer.update({ board, rays, board_visible: shown, handles: shown ? handles_of(rig, scene.camera.frame_mm) : null,
    pivot_id: pl.pivot.mode === "object" ? pivot_label(pl.pivot.object_id) : null,
    active: hd?.kind === "ring" || hd?.kind === "arrow" ? hd.kind : null,
    object_rings: object_rings_now(), active_axis: hd?.kind === "object" ? hd.axis : null,
    art_matrix: art_frame_matrix(rec, rig.D - DRAWING_OFFSET_M) });
  observer.render();
  return performance.now() - t0;
}

/** The drawing on the frame of the checked layers: re-packed from the main thread's document when it has one, else
 * asked of the core worker (an `art` request); then the observer is redrawn. */
function observer_refresh(rebuild: boolean): void {
  if (rebuild) {
    if (state.doc !== null && state.rec !== null) observer_set_art(pack_art(line_art(state.doc, state.rec, 1, state.layersChecked)));
    else client?.request_art([...state.layersChecked]);
  }
  request_observer_render();
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
    observer.set_art(last_art); // the last document's drawing (a pane created after a render)
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
  request_observer_render();
});
ui.observerRays.addEventListener("change", () => request_observer_render());

/** D83: the left pane's 「板子」 checkbox. Left pane only: the drawing pane, the outputs, the camera, undo and framing
 * are unchanged; not an undo step, not stored in the scene. A change while a board-handle drag is held is ignored
 * (the checkbox goes back), so the held board never disappears under the pointer; an object-ring drag allows it. */
function set_board_visible(on: boolean): void {
  const hd = state.handle;
  if (hd?.kind === "ring" || hd?.kind === "arrow") {
    ui.observerBoard.checked = state.board_visible;
    return;
  }
  ui.observerBoard.checked = on;
  if (on === state.board_visible) return;
  state.board_visible = on;
  ui.observerPane.classList.remove("on-handle"); // the hover state is re-computed on the next mouse move
  request_observer_render();
}
ui.observerBoard.checked = state.board_visible;
ui.observerBoard.addEventListener("change", () => set_board_visible(ui.observerBoard.checked));

// ---------------------------------------------------------------------------- core worker (§5.4.11)
/** The core worker's client, or null: the synchronous fallback (no `Worker`, or the worker failed). */
let client: CoreClient | null = null;
let core_worker: Worker | null = null;

/** Every object's transform of `scene`, the ids of `pending` (a drag candidate) taken from it. */
function pose_entries(scene: Scene, pending: UnitPose | null = null): PoseEntries {
  return scene.objects.map((o) => [o.id, clone_transform(pending?.transforms.get(o.id) ?? o.transform)]);
}

/** After every assignment of `state.scene` outside `load`: the worker's scene follows (a `pose` message only when the
 * transforms differ from the last posted ones). */
function publish_pose(): void {
  if (client !== null && state.scene !== null) client.publish_pose(pose_entries(state.scene));
}

/** What the status line needs of a render besides its reply. */
interface StatusMeta {
  focal_mm: number;
  form: string;
}

/** The render the core worker should run now (read when the request is posted: the latest camera / pose wins). */
function render_params(): RenderParams | null {
  const pl = state.plane, scene = state.scene;
  if (pl === null || scene === null) return null;
  const dragging = state.dragging;
  // §5.4.11: during a drag of a large scene the <img> overlay with the checked layers; hidden lines and umbra off
  const img = dragging && state.full_svg_length > IMG_MODE_THRESHOLD;
  const block = pl.block();
  const meta: StatusMeta = { focal_mm: block.focal_length_mm, form: pl.scene_block ? "scene camera" : "picture_plane" };
  return { block, hidden: hiddenLines.checked && !dragging, umbra: !dragging, layers: img ? ordered_layers(state.layersChecked) : null,
    quick_layers: ordered_layers(state.layersChecked), img_threshold: IMG_MODE_THRESHOLD, hidden_style: hidden_style(),
    two_phase: !dragging, art_layers: [...state.layersChecked], dragging, img,
    // an object drag's pending candidate goes with the render (the worker runs its stage A)
    transforms: pose_entries(scene, obj_drag.pending), meta };
}

/** The status line after a frame (`pending`: the resting frame's final document is still being computed). */
function show_status(summary: DocSummary, rec: CameraRecord, meta: StatusMeta, obs_ms: number | null, pending: boolean): void {
  if (state.scene === null) return;
  ui.statusLine.textContent = status_text(state.sceneName, state.timings, overlay.mode, summary, state.scene, rec, meta.focal_mm, meta.form,
    obs_ms, pending);
}

/**
 * The drawing pane's overlay during a drag is throttled by its own cost: a new SVG costs the main thread its parse,
 * layout and paint (an `<img>` SVG document is laid out on the main thread like the DOM overlay), which for a large
 * scene exceeds a frame many times over, while the worker replies at its own pace. The last resting DOM update's
 * `innerHTML` time (`dom_ms`) scales with the SVG's element count, so a drag frame's overlay is applied only when
 * `OVERLAY_DRAG_INTERVAL_K · dom_ms` has passed since the last one (`basic`: ≈ 0.5 ms → an interval under one frame,
 * so no throttling and every reply; `two_lights`: ≈ 1–2 ms → at most every other frame; a 10 k-element scene: ≈ 30–90
 * ms of `innerHTML`, whose `<img>` paint costs about three times that → every 0.5–1.5 s, so the main thread spends
 * under a fifth of the drag on it). A skipped reply is
 * applied when the interval has passed unless a newer one came first (`pending_overlay`), so a pointer held still
 * never leaves a stale picture. The observer's drawing on the frame, the warnings and the status follow every reply;
 * the resting frame always applies.
 */
export const OVERLAY_DRAG_INTERVAL_K = 16;
/** No throttling at all when the interval would be shorter than one animation frame (ms): the examples get every reply. */
export const OVERLAY_DRAG_MIN_INTERVAL_MS = 17;
/** When the overlay was last applied, and the resting DOM overlay's `innerHTML` time (ms): the smallest measured since
 * the load (the first resting frame after a load is cold and overstates it; `Infinity` until one was measured, which
 * means no throttling). */
let overlay_applied_at = -Infinity, resting_dom_ms = Infinity;
/** A drag reply whose overlay was skipped: applied when the interval has passed (a trailing apply, so the drawing pane
 * never keeps a stale picture while the pointer is held still), unless a newer reply applies first. */
let pending_overlay: { svg: string; img: boolean; timer: number } | null = null;

function drop_pending_overlay(): void {
  if (pending_overlay === null) return;
  clearTimeout(pending_overlay.timer);
  pending_overlay = null;
}

/** The drag-frame overlay interval now (0: no throttling). */
function overlay_interval(): number {
  const ms = OVERLAY_DRAG_INTERVAL_K * resting_dom_ms;
  return !Number.isFinite(ms) || ms < OVERLAY_DRAG_MIN_INTERVAL_MS ? 0 : ms;
}

/** Show `svg` in the drawing pane (`<img>` or DOM), now. */
function apply_overlay(svg: string, img: boolean): void {
  drop_pending_overlay();
  if (img) overlay.set_img(svg);
  else overlay.set_svg(svg);
  overlay_applied_at = performance.now();
}

/** Apply a render reply of the core worker: the overlay (the `<img>` for a drag request of a large scene, or a resting
 * `quick` document too long for the DOM; else the DOM overlay; a drag frame's overlay is throttled, above), the
 * warnings, the timings, the drawing on the frame, the observer, the frame record and the status line. */
function apply_reply(r: RenderedReply, info: RequestInfo): void {
  if (state.scene === null || state.plane === null) return;
  const img = info.img || (r.phase === "quick" && r.img);
  const t1 = performance.now();
  const wait = info.dragging ? overlay_interval() - (t1 - overlay_applied_at) : 0;
  const skip_overlay = wait > 0;
  try {
    if (skip_overlay) {
      // the drawing pane keeps its last picture until the interval has passed, then shows this reply (or a newer one)
      drop_pending_overlay();
      const svg = r.svg;
      pending_overlay = { svg, img, timer: window.setTimeout(() => {
        pending_overlay = null;
        try {
          apply_overlay(svg, img);
        } catch (e) {
          show_error(describe_error(e));
        }
      }, Math.ceil(wait)) };
    } else apply_overlay(r.svg, img);
  } catch (e) {
    show_error(describe_error(e));
    return;
  }
  const t2 = performance.now();
  if (!img && !skip_overlay) state.full_svg_length = r.svg.length;
  if (!img && !info.dragging) resting_dom_ms = Math.min(resting_dom_ms, t2 - t1); // a resting DOM frame's cost
  state.svg = r.svg;
  state.rec = r.rec;
  last_rays = r.ray_points;
  warnings.update_list(r.warnings);
  if (r.stage_a_ran && r.stage_a_ms !== null) {
    state.timings.stage_a_ms = r.stage_a_ms;
    state.timings.stage_a_runs += 1;
  }
  state.timings.core_ms = r.core_ms;
  state.timings.dom_ms = t2 - t1;
  state.timings.mode = overlay.mode;
  observer_set_art(r.art);
  const obs_ms = state.obs.on && observer !== null ? update_observer() : null;
  state.obs.ms = obs_ms;
  state.frames.push({ core_ms: r.core_ms, dom_ms: t2 - t1, obs_ms, mode: overlay.mode, dragging: info.dragging, svg_bytes: r.svg.length,
    phase: r.phase, stage_a_ms: r.stage_a_ran ? r.stage_a_ms : null, overlay: !skip_overlay });
  if (state.frames.length > 500) state.frames.shift();
  const pending = client !== null && client.final_pending && !client.dirty;
  show_status(r.summary, r.rec, info.meta as StatusMeta, obs_ms, pending);
}

/** The worker cannot be used (it failed to start or threw outside a request): the synchronous path from now on. */
function worker_failed(message: string): void {
  if (client === null) return;
  client = null;
  core_worker?.terminate();
  core_worker = null;
  show_error(`core worker unavailable, rendering on the main thread (${message})`);
  state.doc = null;
  request_render();
}

function start_worker(): void {
  if (typeof Worker === "undefined") return;
  try {
    const w = new Worker(new URL("./core_worker.ts", import.meta.url), { type: "module" });
    const c = new CoreClient((m, transfer) => w.postMessage(m, transfer ?? []), {
      rendered: apply_reply,
      art: (m) => {
        observer_set_art(m.art);
        last_rays = m.ray_points;
        request_observer_render();
      },
      downloaded: (m) => save({ filename: m.filename, type: m.mime, text: m.text }),
      error: (m) => show_error(m.message),
    }, render_params);
    w.onmessage = (ev: MessageEvent) => {
      if (client === c) c.on_message(ev.data);
    };
    w.onerror = (ev: ErrorEvent) => {
      ev.preventDefault();
      worker_failed(ev.message || "worker error");
    };
    w.onmessageerror = () => worker_failed("message error");
    core_worker = w;
    client = c;
  } catch (e) {
    client = null;
    core_worker = null;
    console.warn("castplane: no core worker, rendering on the main thread", e);
  }
}

// ---------------------------------------------------------------------------- render loop
let rafPending = false;
/** Whether a core render was requested during the current drag (its release then needs the resting frame). */
let drag_rendered = false;

/** Mark the state dirty and schedule one animation frame (pointer events coalesce: the latest camera wins). */
function request_render(): void {
  state.dirty = true;
  schedule_frame();
}

/** Mark only the observer dirty (selection, rings, rays, board checkbox, framing, the observer camera): the next
 * frame redraws it from the current state without a core render. */
function request_observer_render(): void {
  obsDirty = true;
  schedule_frame();
}

/** The end of a drag: the resting frame when the drag rendered anything, else only the observer (handles thinner). */
function request_after_drag(): void {
  if (drag_rendered || state.dirty) request_render();
  else request_observer_render();
  drag_rendered = false;
}

function schedule_frame(): void {
  if (!rafPending) {
    rafPending = true;
    requestAnimationFrame(frame);
  }
}

/** One animation frame. Without the core worker: today's synchronous frame (`frame_sync`). With it: the drag step of a
 * held object drag (the proxies and the panel), a render request with the current camera / pose (sent now, or after the
 * one in flight), the drawing pane's three.js view, the controls and the observer, all at frame rate; the overlay and
 * the drawing on the frame follow when the reply arrives (`apply_reply`). */
function frame(): void {
  rafPending = false;
  const core = state.dirty, obs = obsDirty;
  obsDirty = false;
  const pl = state.plane;
  if (state.scene === null || state.A === null || pl === null) return;
  if (core) {
    state.dirty = false;
    if (client === null) {
      frame_sync(true);
      return;
    }
    obj_drag.frame(); // `live: false` with the worker: the 3D proxies and the panel follow the candidate
    if (state.scene === null || state.A === null) return;
    if (state.dragging) drag_rendered = true;
    state.doc = null;
    client.request();
    sync_controls(); // sliders, equation, readouts (the picture delta is measured here, once per frame), notices, undo
  } else if (!obs && !viewDirty) return;
  if ((core || viewDirty) && view3d.checked) view.render(pl.block(), state.scene.output.canvas_mm, state.A.scene_scale);
  viewDirty = false;
  if (state.obs.on && observer !== null) state.obs.ms = update_observer();
}

/**
 * The synchronous frame on the main thread (§5.4.10 render loop): `drag_step` runs the pending object pose of the
 * current gesture first (at most one stage A per frame; the 3D proxy only for a slow scene), then stages B and C, the
 * SVG, the overlay, the warnings, the observer and the status line. The fallback's frame, `settle()` and `probe_rig`.
 * Returns whether it rendered.
 */
function frame_sync(drag_step = false): boolean {
  const pl = state.plane;
  if (state.scene === null || state.A === null || pl === null) return false;
  const ran_a = drag_step ? obj_drag.frame() : false;
  if (state.scene === null || state.A === null) return false;
  if (state.dragging) drag_rendered = true;
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
    return false;
  }
  const t1 = performance.now();
  apply_overlay(svg, img_mode);
  const t2 = performance.now();
  if (!img_mode) {
    state.full_svg_length = svg.length;
    if (!state.dragging) resting_dom_ms = Math.min(resting_dom_ms, t2 - t1);
  }
  state.doc = doc;
  state.svg = svg;
  state.rec = rec;
  if (view3d.checked) view.render(block, scene.output.canvas_mm, state.A.scene_scale);
  warnings.update(doc);
  const summary = doc_summary_of(doc);
  // the drawing on the frame and the ray points of this document (counted in the observer's cost, as before)
  const t3 = performance.now();
  observer_set_art(pack_art(line_art(doc, rec, 1, state.layersChecked)));
  last_rays = vertex_ray_points(doc, scene);
  const pack_ms = performance.now() - t3;
  const obs_ms = state.obs.on && observer !== null ? pack_ms + update_observer() : null;
  state.obs.ms = obs_ms;
  state.timings.core_ms = t1 - t0;
  state.timings.dom_ms = t2 - t1;
  state.timings.mode = overlay.mode;
  state.frames.push({ core_ms: t1 - t0, dom_ms: t2 - t1, obs_ms, mode: overlay.mode, dragging: state.dragging, svg_bytes: svg.length,
    phase: "sync", stage_a_ms: ran_a ? state.timings.stage_a_ms : null, overlay: true });
  if (state.frames.length > 500) state.frames.shift();
  sync_controls(); // sliders, equation, readouts (the picture delta is measured here, once per frame), notices, undo
  show_status(summary, rec, { focal_mm: block.focal_length_mm, form: pl.scene_block ? "scene camera" : "picture_plane" }, obs_ms, false);
  return true;
}

/**
 * Hooks that read a document synchronously (`svg`, `svg_length`, `download_texts`, `doc_summary`): with the core worker,
 * when a render is in flight or wanted, or the main thread holds no document, render the resting frame synchronously
 * now (`frame_sync`) and ignore the replies of every request posted before. Returns whether it rendered. Without the
 * worker every frame is synchronous and nothing is done.
 */
function settle(): boolean {
  if (client === null) return false;
  if (!client.in_flight && !client.dirty && !client.final_pending && !state.dirty && state.doc !== null) return false;
  client.settle();
  state.dirty = false;
  return frame_sync();
}

// ---------------------------------------------------------------------------- start
/** Hooks for the smoke test and for measuring `core ms` / `dom ms` (web/README.md); `load_example`, `load_text` and
 * `set_hidden` act as the UI controls would, the rest is read-only. With the core worker, the hooks that read a document
 * (`svg`, `svg_length`, `download_texts`, `doc_summary`) call `settle()` first; `frames` and `timings` do not. */
(window as unknown as { castplane_web: unknown }).castplane_web = {
  examples: EXAMPLES.map((e) => e.name),
  load_example: (name: string) => {
    const ex = EXAMPLES.find((e) => e.name === name);
    if (ex === undefined) throw new Error(`unknown example ${name}`);
    examplesSelect.value = name;
    // false: the error panel shows why, the previous scene stays
    return load(name, () => load_scene(ex.data), display_colours(ex.data), object_groups(ex.data), object_links(ex.data));
  },
  load_text,
  /** Measurement aid: with `false` the two three.js views skip their WebGL draw calls (`stage.ts::set_gl_draw`), so a
   * run on a software renderer measures the page's JavaScript only. */
  set_gl: (on: boolean) => set_gl_draw(on),
  /** With the core worker: render the resting frame synchronously when a render is pending (or the main thread holds
   * no document), so the overlay, the warnings, the status and the document hooks are the current camera's; true when
   * it rendered. Without the worker: false (every frame is synchronous). */
  settle: () => settle(),
  /** Whether stages B + C + SVG run in the core worker (false: the synchronous fallback). */
  get worker() { return client !== null; },
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
    client?.settle(); // the synchronous frame below supersedes any pending reply
    frame_sync();
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
  /** D83: the object a click at pane px `(x, y)` would select (the observer's ray pick), or null (blank space). */
  pick_at: (x: number, y: number) => observer?.pick_object([x, y]) ?? null,
  /** M10: the equation field's state. */
  get equation_field() { return { value: ui.equation.value, error: state.equation_error, bad: ui.equation.classList.contains("bad") }; },
  get svg_length() {
    settle();
    return state.svg.length;
  },
  /** The writer's SVG text of the last frame (the overlay's source). */
  get svg() {
    settle();
    return state.svg;
  },
  /** The texts "Download SVG" / "Download JSON" would save now. */
  download_texts: () => {
    settle();
    return state.doc === null ? null : {
      svg: svg_blob(state.doc, state.layersChecked, state.sceneName, hidden_style()).text,
      json: json_blob(state.doc, state.sceneName).text,
    };
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
      art_objects: count("art"), ms: state.obs.ms, size: [W, H], px, board_shown: observer.board_shown,
      labels_shown: [...ui.observerLabels.querySelectorAll<HTMLElement>(".obs-label")].filter((e) => !e.hidden).length };
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
    settle();
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
  /** M11 (contract §5.8.4): object `id`'s current transform (a copy; null when unknown). With the core worker an object
   * drag is a proxy drag (the scene is committed at release), so while one is held the shown pose is the candidate's:
   * that transform for the ids it holds (as the live drag of the synchronous path would have committed it). */
  object_transform: (id: string) => {
    const t = client !== null && state.handle?.kind === "object" ? obj_drag.pending?.transforms.get(id) : undefined;
    return t !== undefined ? clone_transform(t) : current_transform(id);
  },
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
   * release; no snapping): one undo step when the pose changed. Returns the new transform, or null when it cannot run.
   * D85: the ring drag's path, so a part with a joint or descendants turns its subtree about its pivot. */
  rotate_object: (id: string, axis: Axis, deg: number) => {
    if (!start_unit_drag({ kind: "part", id }, axis, { w: [1, 0, 0], r_c: [1, 0, 0], u_c: [0, 0, 1] })) return null;
    obj_drag.move(deg);
    finish_object_drag();
    return current_transform(id);
  },
  /** D84: rotate group `name` (≥ 2 members) about world axis `axis` by `deg` as one ring drag would (every member about
   * the group's `c`; no snapping): one undo step when anything changed. Returns the members' transforms by id and the
   * group's display Euler, or null when it cannot run. */
  rotate_group: (name: string, axis: Axis, deg: number) => {
    if (!start_unit_drag({ kind: "group", group: name }, axis, { w: [1, 0, 0], r_c: [1, 0, 0], u_c: [0, 0, 1] })) return null;
    obj_drag.move(deg);
    finish_object_drag();
    const pose = unit_pose({ kind: "group", group: name });
    return pose === null ? null : { transforms: Object.fromEntries(pose.transforms), rotation: unit_angles(pose) };
  },
  /** D84: the numeric fields' action for group `name` (its rotation relative to the load, exact Euler): one undo step. */
  set_group_rotation: (name: string, r: [number, number, number]) => apply_group_rotation(name, r),
  /** D84: group `name`'s rotation relative to the load as the fields show it (`[rx, ry, rz]`, full doubles), or null. */
  group_rotation: (name: string) => unit_angles(unit_pose({ kind: "group", group: name })),
  /** D84: group `name`'s pivot `c` (world), or null. */
  group_centre: (name: string) => state.plane?.group_frame(name)?.c ?? null,
  /** D84: the loaded scene's groups: `groups` (id → name, every valid key) and `units` (≥ 2 members, ids in order). */
  object_groups: () => ({ groups: Object.fromEntries(state.groups),
    units: Object.fromEntries([...scene_groups()].map(([g, ids]) => [g, [...ids]])) }),
  /** D85: the loaded scene's links: `links` (id → its parse-valid `parent` / `joint` keys, as read and as Download scene
   * writes them back), and the forest resolved at load: `parent` (child → parent) and `children` (id → its children
   * in scene order; only ids with children). */
  object_links: () => {
    const f = state.plane?.links;
    return {
      links: Object.fromEntries([...state.links].map(([id, l]) => [id, {
        ...(l.parent !== undefined ? { parent: l.parent } : {}), ...(l.joint !== undefined ? { joint: [...l.joint] } : {}) }])),
      parent: Object.fromEntries(f?.parent ?? []),
      children: Object.fromEntries([...(f?.children ?? [])].map(([id, ks]) => [id, [...ks]])),
    };
  },
  /** D85: object `id`'s world joint `j_w` (its local joint through its current transform), or null when it has none
   * or is unknown. */
  object_joint: (id: string) => {
    const t = current_transform(id), j = state.plane?.joint(id) ?? null;
    return t === null || j === null ? null : world_centre(t, j);
  },
  /** D85: the parts a rotation of part `id` carries (its descendants in preorder, siblings in scene order; `[]` for a
   * leaf), or null for an unknown id. */
  descendants: (id: string) => {
    const pl = state.plane;
    return pl === null || object_in(state.scene, id) === undefined ? null : pl.subtree(id).slice(1);
  },
  /** D85: object `id`'s 3D matrices (column-major, 16 numbers) in the drawing pane's and the observer's three.js groups
   * (`null` for a group not built), or null for an unknown id. */
  object_matrices: (id: string) => {
    if (object_in(state.scene, id) === undefined) return null;
    const of = (g: THREE.Group | null): number[] | null => {
      const c = g?.children.find((x) => x.userData[OBJECT_ID_KEY] === id);
      return c === undefined ? null : [...c.matrix.elements];
    };
    return { view: of(view.group), observer: of(observer?.stage.group ?? null) };
  },
  /** D85: the observer-pane px of world point `X` (`null` behind the observer or without the pane). */
  world_px: (X: readonly number[]) => {
    const o = obs_frame();
    return o === null || observer === null ? null : observer_project(observer.view, o.W, o.H, X);
  },
  /** D84: a left-pane click on object `id` (null: blank space), the click cycle as a real click runs it. */
  click_object: (id: string | null) => click_object(id),
  /** D84: the selection: a whole group with its members, a part with its group (null when ungrouped), or null. */
  selection: () => {
    const sel = state.rotate.sel;
    if (sel === null) return null;
    if (sel.kind === "group") return { kind: "group", group: sel.group, members: [...(scene_groups().get(sel.group) ?? [])] };
    const g = state.groups.get(sel.id);
    return { kind: "part", id: sel.id, group: g !== undefined && scene_groups().has(g) ? g : null };
  },
  /** D84: select group `name` as a whole (the dropdown's group entry). */
  select_group: (name: string) => select({ kind: "group", group: name }),
  /** M11: the numeric fields' action for object `id` (exact Euler angles, the pivot fixed): one undo step. D85: the
   * 套用 path, so a part with a joint or descendants carries its subtree. */
  set_object_rotation: (id: string, r: [number, number, number]) => apply_object_rotation(id, r),
  /** M11: select the object to rotate (the dropdown / a click in the left pane); null clears it. */
  select_object: (id: string | null) => select_object(id),
  /** D83: set the left pane's 「板子」 checkbox as a user would (fires its change handler); returns the resulting state. */
  set_board_visible: (on: boolean) => {
    if (ui.observerBoard.checked !== on) {
      ui.observerBoard.checked = on;
      ui.observerBoard.dispatchEvent(new Event("change"));
    }
    return state.board_visible;
  },
  /** D83: whether the observer's board is shown (the 「板子」 checkbox). */
  board_visible: () => state.board_visible,
  /** M11 / D83: the selection, the slow-scene flag and the panel's state (no mode: the rotation is modeless). */
  get rotate() {
    return { id: selected_part(), selection: selection_value(state.rotate.sel), selected_text: ui.objectSelected.textContent, slow: slow_scene(),
      fields: ui.objectFields.map((el) => ({ value: el.value, bad: el.classList.contains("bad") })),
      ground_shown: !ui.objectGround.hidden, centre: ui.objectCentre.textContent, notice: ui.objectNotice.textContent,
      limit: ui.objectLimit.textContent, limit_bad: ui.objectLimit.classList.contains("bad") };
  },
  /** D86: part `id`'s resolved joint limit and its current angle (`angle_deg` with the `+180 ≡ −180` identification of
   * `limits.ts::canonical_angle`, `state`, whether it is `inside`, the parent's id); null without a resolved limit or for
   * an unknown id. `min_deg` / `max_deg` are the resolved bounds (±180 for an absent one). */
  joint_limit: (id: string) => {
    const pl = state.plane, lim = pl?.limit(id) ?? null, a = pl?.part_limit_angle(id, current_transform) ?? null;
    if (pl == null || lim === null || a === null) return null;
    return { axis: [...lim.axis], min_deg: lim.min, max_deg: lim.max, min_written: lim.min_written, max_written: lim.max_written,
      angle_deg: canonical_angle(a.phi, lim), state: a.state, inside: a.inside, parent: pl.parent_of(id) };
  },
  /** D86: the loaded scene's parse-valid `joint_limit` keys by object id, as read and as Download scene writes them back
   * (also the ones the resolution ignores). */
  object_limits: () => Object.fromEntries([...state.links].filter(([, l]) => l.joint_limit !== undefined)
    .map(([id, l]) => [id, limit_for_file(l.joint_limit!)])),
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

// §5.4.11: stages B + C + SVG in a Web Worker when one can be started (else the synchronous path)
start_worker();
// D80: the page always opens in the edit view (observer pane shown); the old "castplane.observer" storage key is ignored
set_preview(TOGGLES.preview);
layout();
const first = EXAMPLES.find((e) => e.name === "basic") ?? EXAMPLES[0];
if (first !== undefined) {
  examplesSelect.value = first.name;
  load(first.name, () => load_scene(first.data), display_colours(first.data), object_groups(first.data), object_links(first.data));
}
