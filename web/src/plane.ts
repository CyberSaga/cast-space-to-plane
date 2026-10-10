/**
 * Plane mode's session (M10; spec-v0.2 §4.2, §5; contract §5.7.7–§5.7.10, revised by M11 §5.8.5 and §5.8.11) — pure,
 * DOM-free and unit-tested (`web/test/plane.test.ts`). It owns the rig of the loaded scene, the history (one undo
 * stack of board, reset and object entries, with a redo stack), the pivot selection, the "unedited scene camera" flag
 * and the picture-delta readout, and maps the observer pane's handle drags (ring, arrow) and the controls onto the rig
 * operations of `rig.ts` (which it never re-implements). The pivot `P` is a stored value taken when it is set (D82):
 * the session's scene geometry (centre, object centres, vertices) is refreshed after every edit by
 * {@link PlaneSession.set_geometry} for future takes only. The drawing pane is view-only: no gesture there reaches
 * the session. `main.ts` wires the DOM to it.
 */

import type { SceneObject, Vec2, Vec3 } from "castplane";

import {
  UNDO_MAX, arrowDrag, bboxCentre, clone, deltaText, equation, frameMetres, fromCamera, measureRef, orbitRing, pictureDelta,
  readouts, sameBoard, sameState, setD, setFocal, setLockLevel, setPivot, setRoll, sixView, toCameraBlock,
} from "./rig.js";
import type { AnyCamera, PicturePlaneCamera, RigState, RingGrab, ViewName } from "./rig.js";
import { EquationError, applyEquation } from "./equation.js";

/** The pivot selection (§5.7.7, §5.8.5): the selector's mode and the object `P` was last taken from (`null`: none, or
 * that object was deleted). Recorded only by a reset entry (§5.8.11). */
export interface PivotSelection {
  mode: "scene" | "object";
  object_id: string | null;
}

/** Notices of the readout area (not document warnings, §5.7.10). */
export const NOTICE_R_CLAMPED = "相機與場景中心的距離超出範圍，已調整";
export const NOTICE_D_CLAMPED = "眼睛到板子的距離 D 超出滑桿範圍（0.5–12 m），已調整";
export const NOTICE_EYE_BELOW_GROUND = "眼睛在地面下方";

/** What the session needs of a loaded scene. `centre`, `object_centres` and `vertices` follow the edited scene
 * ({@link PlaneSession.set_geometry}); `camera` and `canvas_mm` are the loaded scene's. */
export interface SessionScene {
  /** The validated scene camera (any of the three forms). */
  camera: AnyCamera;
  canvas_mm: readonly number[];
  /** The scene centre (stage A's `bbox` centre). */
  centre: Vec3;
  /** Per object id: the centre of its stage-A bounding box (the object pivot). */
  object_centres: ReadonlyMap<string, Vec3>;
  /** Every stage-A vertex (the picture-delta readout). */
  vertices: readonly Vec3[];
}

/** What changed after a session action: `framing` asks for an observer re-framing (§5.6.4: views, equation, reset,
 * undo, pivot changes). */
export interface ActionResult {
  changed: boolean;
  framing: boolean;
}

// ------------------------------------------------------------------------------------------------ history (§5.8.11)

/** A board step (§5.7.8 item 13): undo assigns `before`, redo `after`, both keeping the current `P`. */
export interface BoardEntry {
  kind: "board";
  before: RigState;
  after: RigState;
}

/** 重設視角 (§5.8.5): undo restores `before` (its `P` included) and `pivot_before`, redo `after` and `pivot_after`. The
 * `scene_block` flags around the reset come with them (an unclamped reset renders the scene camera again). */
export interface ResetEntry {
  kind: "reset";
  before: RigState;
  after: RigState;
  pivot_before: PivotSelection;
  pivot_after: PivotSelection;
  block_before: boolean;
  block_after: boolean;
}

/** Adding an object (§5.8.7): `index` = `objects.length` at the time; `name` the display name (library objects). */
export interface AddEntry {
  kind: "add";
  index: number;
  obj: SceneObject;
  name: string | null;
}

/** Deleting an object (§5.8.10): the record and its original index (undo re-inserts the same record there). */
export interface DeleteEntry {
  kind: "delete";
  index: number;
  obj: SceneObject;
  name: string | null;
}

/** Moving an object (§5.8.3, §5.8.4), settled at release: the records before and after. */
export interface MoveEntry {
  kind: "move";
  index: number;
  id: string;
  before: SceneObject;
  after: SceneObject;
}

export type ObjectEntry = AddEntry | DeleteEntry | MoveEntry;
export type HistoryEntry = BoardEntry | ResetEntry | ObjectEntry;

/** The result of applying an object entry: the new `objects` array and the object to select (`null`: clear). */
export interface ObjectStep {
  objects: SceneObject[];
  select: string | null;
}

/**
 * Apply an object entry to `objects` in the direction `dir` (§5.8.11), returning a new array (records are shared by
 * reference, never rebuilt) and the selection that follows the entry (§5.8.2), or `null` when `objects` is not the
 * array the entry expects (the LIFO check: for an undo, the array right after the entry's own action; for a redo, the
 * array right before it). A `null` is a bug; the caller clears both stacks and leaves the scene as it is.
 */
export function apply_object_entry(objects: readonly SceneObject[], e: ObjectEntry, dir: "undo" | "redo"): ObjectStep | null {
  const ok_index = (i: number, n: number): boolean => Number.isInteger(i) && i >= 0 && i <= n;
  const insert = (rec: SceneObject): SceneObject[] => [...objects.slice(0, e.index), rec, ...objects.slice(e.index)];
  const remove = (): SceneObject[] => [...objects.slice(0, e.index), ...objects.slice(e.index + 1)];
  const replace = (rec: SceneObject): SceneObject[] => objects.map((o, i) => (i === e.index ? rec : o));
  switch (e.kind) {
    case "add":
      if (dir === "undo") {
        if (!ok_index(e.index, objects.length - 1) || objects[e.index]!.id !== e.obj.id) return null;
        return { objects: remove(), select: null };
      }
      if (!ok_index(e.index, objects.length)) return null;
      return { objects: insert(e.obj), select: e.obj.id };
    case "delete":
      if (dir === "undo") {
        if (!ok_index(e.index, objects.length)) return null;
        return { objects: insert(e.obj), select: e.obj.id };
      }
      if (!ok_index(e.index, objects.length - 1) || objects[e.index] !== e.obj) return null;
      return { objects: remove(), select: null };
    case "move": {
      const [expect, next] = dir === "undo" ? [e.after, e.before] : [e.before, e.after];
      if (!ok_index(e.index, objects.length - 1) || objects[e.index] !== expect) return null;
      return { objects: replace(next), select: e.id };
    }
  }
}

/**
 * The history (§5.8.11; D86): one undo stack of at most {@link UNDO_MAX} entries (the oldest dropped when a 51st is
 * pushed) and a redo stack. Undoing moves the top entry onto the redo stack and redoing moves it back, so the two
 * together never exceed the cap; every pushed entry clears the redo stack. Selection is never recorded.
 */
export class History {
  private readonly undos: HistoryEntry[] = [];
  private readonly redos: HistoryEntry[] = [];

  constructor(readonly max = UNDO_MAX) {}

  /** The undo depth. */
  get size(): number {
    return this.undos.length;
  }

  get redo_size(): number {
    return this.redos.length;
  }

  get canUndo(): boolean {
    return this.undos.length > 0;
  }

  get canRedo(): boolean {
    return this.redos.length > 0;
  }

  /** Record a new entry: the redo stack is cleared. */
  push(e: HistoryEntry): void {
    this.undos.push(e);
    if (this.undos.length > this.max) this.undos.shift();
    this.redos.length = 0;
  }

  /** The entry to undo (moved onto the redo stack), or `null` when empty. */
  take_undo(): HistoryEntry | null {
    const e = this.undos.pop();
    if (e === undefined) return null;
    this.redos.push(e);
    return e;
  }

  /** The entry to redo (moved back onto the undo stack), or `null` when empty. */
  take_redo(): HistoryEntry | null {
    const e = this.redos.pop();
    if (e === undefined) return null;
    this.undos.push(e);
    return e;
  }

  /** An actual change that is not itself an undo or redo (§5.8.11 "Redo is cleared"). */
  clear_redo(): void {
    this.redos.length = 0;
  }

  /** A load, or the LIFO bug guard. */
  clear(): void {
    this.undos.length = 0;
    this.redos.length = 0;
  }
}

/** What an undo or redo did: for an object entry `objects` is the new array and `select` the selection that follows
 * it (§5.8.2); for a board or reset entry `objects` is `null` and the selection is kept (`select` undefined). */
export interface StepResult extends ActionResult {
  entry: HistoryEntry["kind"] | null;
  objects: SceneObject[] | null;
  select?: string | null;
}

const NOTHING: ActionResult = { changed: false, framing: false };
const NO_STEP: StepResult = { changed: false, framing: false, entry: null, objects: null };

const same_pivot = (p: PivotSelection, q: PivotSelection): boolean => p.mode === q.mode && p.object_id === q.object_id;

/**
 * The plane-mode session of one loaded scene. Every rig change goes through it: handle drags in the observer pane
 * (`begin` / `drag` / `end`), the sliders, views, the equation, lock-horizontal, pivot, 重新取中心, undo, redo and
 * 重設視角. While {@link scene_block} is true (since the load or an unclamped reset, until the first rig change) the
 * core renders the scene camera itself, so the document, its warnings and the downloads are the CLI's; the rig's
 * `picture_plane` block has the same picture (§5.7.7 load rule, no clamp), and every change switches to it. An object
 * edit never rebuilds the session: {@link set_geometry} refreshes the scene geometry and leaves `P` where it is.
 */
export class PlaneSession {
  rig: RigState;
  readonly history = new History();
  pivot: PivotSelection = { mode: "scene", object_id: null };
  /** Whether the frame renders the scene camera as it is (unedited since the load or reset, no load clamp). */
  scene_block: boolean;
  /** The load rule's notices (clamps), re-evaluated at a load and at a reset only (§5.8.5). */
  load_notices: string[];
  private scene_: SessionScene;
  private delta_: number | null = null;
  /** Whether {@link delta} must be re-measured (computed lazily: at most once per rendered frame, not per pointer event). */
  private delta_stale = false;
  private ref0: (Vec2 | null)[] | null = null;
  private gesture0: { rig: RigState; scene_block: boolean; delta: number | null } | null = null;

  constructor(scene: SessionScene) {
    this.scene_ = scene;
    const res = fromCamera(scene.camera, scene.centre);
    this.rig = res.rig;
    this.scene_block = !(res.clampedD || res.clampedR);
    this.load_notices = load_notices(res);
  }

  /** The loaded scene's camera and canvas with the current (edited) geometry. */
  get scene(): SessionScene {
    return this.scene_;
  }

  /** Whether a handle gesture is open: undo, redo, 重設視角 and 重新取中心 are inert then (§5.8.11). */
  get in_gesture(): boolean {
    return this.gesture0 !== null;
  }

  /**
   * The geometry of the edited scene after a stage-A recompute (§5.8.5): the session, its rig, its history and
   * {@link scene_block} are kept, and `rig.P` is not touched (future takes read the new values). The picture-delta
   * measurement goes on when the vertex list keeps its length (an object drag), else it ends and keeps its last value.
   * A pivot object that no longer exists loses its name (`object_id = null`; the selector keeps its mode).
   */
  set_geometry(centre: readonly number[], object_centres: ReadonlyMap<string, Vec3>, vertices: readonly Vec3[]): void {
    const same_count = vertices.length === this.scene_.vertices.length;
    this.scene_ = { ...this.scene_, centre: [centre[0]!, centre[1]!, centre[2]!], object_centres, vertices };
    if (!same_count) this.ref0 = null;
    else if (this.ref0 !== null) this.delta_stale = true;
    if (this.pivot.object_id !== null && !object_centres.has(this.pivot.object_id)) this.pivot = { ...this.pivot, object_id: null };
  }

  /** The picture-delta readout ("這次拖動右窗畫面變動", frame mm): the largest image displacement of the stage-A
   * vertices since the start of the current or last gesture; null before any. */
  get delta(): number | null {
    if (this.delta_stale && this.ref0 !== null) this.delta_ = pictureDelta(this.ref0, this.measure());
    this.delta_stale = false;
    return this.delta_;
  }

  private set delta(v: number | null) {
    this.delta_ = v;
    this.delta_stale = false;
  }

  /** The `picture_plane` block of the rig (`camera_of_rig`, §5.7.7). */
  rig_block(): PicturePlaneCamera {
    return toCameraBlock(this.rig, this.scene_.camera);
  }

  /** The block the core renders and the downloads write: the scene camera while {@link scene_block}, else the rig's. */
  block(): AnyCamera {
    return this.scene_block ? this.scene_.camera : this.rig_block();
  }

  /** Image of every stage-A vertex in frame mm through the rig (null behind the eye). */
  measure(rig: RigState = this.rig): (Vec2 | null)[] {
    return measureRef(rig, this.scene_.camera, this.scene_.canvas_mm, this.scene_.vertices);
  }

  /** Replace the rig; any change leaves the scene camera's block. Returns whether the state changed. */
  private assign(next: RigState): boolean {
    const changed = !sameState(this.rig, next) || !same3(this.rig.P, next.P);
    this.rig = next;
    if (changed) this.scene_block = false;
    if (changed && this.ref0 !== null) this.delta_stale = true;
    return changed;
  }

  /** {@link assign} for a user change that is not recorded (a slider, lock off, a pivot take): clears the redo stack
   * when something changed (§5.8.11). */
  private assign_unrecorded(next: RigState): boolean {
    const changed = this.assign(next);
    if (changed) this.history.clear_redo();
    return changed;
  }

  // ---------------------------------------------------------------------------------------------- gestures

  /** Pointer-down of a handle drag (ring, arrow): opens one undo step and the delta. */
  begin(): void {
    this.gesture0 = { rig: clone(this.rig), scene_block: this.scene_block, delta: this.delta };
    this.ref0 = this.measure();
    this.delta = 0;
  }

  /** Abandon the current gesture (a second finger on a handle drag): the pointer-down state comes back, no step. */
  cancel(): void {
    const g = this.gesture0;
    this.gesture0 = null;
    if (g === null) return;
    this.rig = g.rig;
    this.scene_block = g.scene_block;
    this.delta = g.delta;
    this.ref0 = null;
  }

  /** A move of the current gesture: the new state computed from the pointer-down state by the caller. Ignored
   * outside a gesture (a move of a gesture begun on another session, e.g. one held across a scene load). */
  drag(next: RigState): boolean {
    if (this.gesture0 === null) return false;
    return this.assign(next);
  }

  /** Release: one board entry when the board `(f, g, up, a, b)` changed (§5.7.8 item 13). */
  end(): boolean {
    const g = this.gesture0;
    this.gesture0 = null;
    if (g === null || sameBoard(g.rig, this.rig)) return false;
    this.history.push({ kind: "board", before: g.rig, after: clone(this.rig) });
    return true;
  }

  // ---------------------------------------------------------------------------------------------- discrete actions

  private discrete(next: RigState, framing: boolean): ActionResult {
    const before = this.rig;
    if (!sameState(before, next)) this.history.push({ kind: "board", before: clone(before), after: clone(next) });
    this.ref0 = null;
    const changed = this.assign(next);
    return { changed, framing: framing && changed };
  }

  /** One-click view (§5.7.8 item 11): one undo step, re-frames the observer. */
  view(name: ViewName): ActionResult {
    return this.discrete(sixView(this.rig, name), true);
  }

  /** Apply an equation (§5.7.8 item 12): the error message (the plane is kept) or null. One undo step. */
  apply_equation(text: string): { error: string | null; result: ActionResult } {
    let next: RigState;
    try {
      next = applyEquation(this.rig, text);
    } catch (e) {
      if (e instanceof EquationError) return { error: e.message, result: { changed: false, framing: false } };
      throw e;
    }
    return { error: null, result: this.discrete(next, true) };
  }

  /** Lock-horizontal (§5.7.7): switching it on is one undo step, switching it off is not (nothing visible changes). */
  set_lock_level(level: boolean): ActionResult {
    const next = setLockLevel(this.rig, level);
    if (level && this.rig.up !== null) return this.discrete(next, false);
    return { changed: this.assign_unrecorded(next), framing: false };
  }

  /** Focal length slider (mm): not an undo step. */
  set_focal(focal: number): boolean {
    return this.assign_unrecorded(setFocal(this.rig, focal));
  }

  /** `D` slider (m): clamped so that `R ∈ [0.8, 40]`; not an undo step. */
  set_D(D: number): boolean {
    return this.assign_unrecorded(setD(this.rig, D));
  }

  /** Roll slider (degrees about the line of sight; the eye does not move): not an undo step. */
  set_roll(roll_deg: number): boolean {
    return this.assign_unrecorded(setRoll(this.rig, roll_deg));
  }

  // ---------------------------------------------------------------------------------------------- pivot (§5.8.5)

  /** Set the pivot selection; a change of it clears the redo stack (§5.8.11). */
  private set_pivot(next: PivotSelection): void {
    if (!same_pivot(this.pivot, next)) this.history.clear_redo();
    this.pivot = next;
  }

  /** The pivot selector (§5.8.5): 場景中心 takes the **current** scene centre; 點選物體 keeps `P` until an object is
   * clicked (the label drops the name). Not an undo step; only a pivot that actually moves clears the pan and re-frames
   * the observer. */
  set_pivot_mode(mode: PivotSelection["mode"]): ActionResult {
    if (mode === "scene") {
      this.set_pivot({ mode: "scene", object_id: null });
      return this.move_pivot(this.scene_.centre, false);
    }
    if (this.pivot.mode !== "object") this.set_pivot({ mode: "object", object_id: null });
    return NOTHING;
  }

  /** A click on an object in 點選物體 mode: `P` becomes its current box centre and the eye moves onto its axis (pan
   * cleared), also when it already is the pivot object (an explicit pick re-centres it, spec-v0.2 §7.1). */
  pick_object(id: string): ActionResult {
    const c = this.scene_.object_centres.get(id);
    if (this.pivot.mode !== "object" || c === undefined) return NOTHING;
    this.set_pivot({ mode: "object", object_id: id });
    return this.move_pivot(c, true);
  }

  /** 重新取中心 (§5.8.5): re-take `P` for the current mode — the current scene centre in 場景中心; in 點選物體 the
   * selected object's current box centre (it becomes the pivot object), else the scene centre. Not an undo step; the pan
   * is cleared only when `P` moves. Inert during a gesture. */
  recenter(selected: string | null): ActionResult {
    if (this.gesture0 !== null) return NOTHING;
    if (this.pivot.mode === "scene") return this.move_pivot(this.scene_.centre, false);
    const c = selected === null ? undefined : this.scene_.object_centres.get(selected);
    this.set_pivot({ mode: "object", object_id: c === undefined ? null : selected });
    return this.move_pivot(c ?? this.scene_.centre, false);
  }

  /** Move the pivot to `P` (pan cleared). With the same `P`, only a `recentre` (an explicit pick) clears the pan. */
  private move_pivot(P: readonly number[], recentre: boolean): ActionResult {
    if (same3(P, this.rig.P) && (!recentre || (this.rig.a === 0 && this.rig.b === 0))) return NOTHING;
    this.ref0 = null;
    const changed = this.assign_unrecorded(setPivot(this.rig, P));
    return { changed, framing: changed };
  }

  // ---------------------------------------------------------------------------------------------- undo, redo, reset

  /** Undo (§5.8.11): a board entry restores its `before` (the current `P` kept) and re-frames the observer; a reset
   * entry restores the board, `P` and the pivot selection; an object entry returns the new `objects` (pass the current
   * ones) and the selection that follows it, touching neither `P` nor `scene_block` nor the framing. Inert during a
   * gesture. */
  undo_step(objects: readonly SceneObject[] = []): StepResult {
    return this.step("undo", objects);
  }

  /** Redo (§5.8.11): the reverse of {@link undo_step}. */
  redo_step(objects: readonly SceneObject[] = []): StepResult {
    return this.step("redo", objects);
  }

  private step(dir: "undo" | "redo", objects: readonly SceneObject[]): StepResult {
    if (this.gesture0 !== null) return NO_STEP;
    const e = dir === "undo" ? this.history.take_undo() : this.history.take_redo();
    if (e === null) return NO_STEP;
    this.ref0 = null; // the measurement ends (its last value is kept)
    if (e.kind === "board") {
      const target = dir === "undo" ? e.before : e.after;
      const changed = this.assign({ ...clone(target), P: [...this.rig.P] as Vec3 });
      return { changed, framing: true, entry: e.kind, objects: null };
    }
    if (e.kind === "reset") {
      const [rig, pivot, block] = dir === "undo" ? [e.before, e.pivot_before, e.block_before] : [e.after, e.pivot_after, e.block_after];
      this.rig = clone(rig);
      this.pivot = { ...pivot };
      this.scene_block = block;
      if (dir === "redo") this.delta = null;
      return { changed: true, framing: true, entry: e.kind, objects: null };
    }
    const r = apply_object_entry(objects, e, dir);
    if (r === null) {
      this.history.clear(); // LIFO violated: a bug; both stacks cleared, the scene left as it is
      return NO_STEP;
    }
    return { changed: true, framing: false, entry: e.kind, objects: r.objects, select: r.select };
  }

  /** 重設視角 (§5.8.5): the §5.7.7 load rule applied to the scene camera at the **current** scene centre (clamps and
   * their notices re-evaluated, the scene camera's block again when unclamped), the scene-centre pivot. One reset entry
   * when the rig, `P` or the pivot selection changed; objects and the selection are not touched. The caller also resets
   * the observer's direction and frames it. Inert during a gesture. */
  reset(): ActionResult {
    if (this.gesture0 !== null) return NOTHING;
    const res = fromCamera(this.scene_.camera, this.scene_.centre);
    const before = clone(this.rig), pivot_before = { ...this.pivot }, block_before = this.scene_block;
    const pivot_after: PivotSelection = { mode: "scene", object_id: null };
    const block_after = !(res.clampedD || res.clampedR);
    const changed = !sameState(before, res.rig) || !same3(before.P, res.rig.P) || !same_pivot(pivot_before, pivot_after);
    if (changed) {
      this.history.push({ kind: "reset", before, after: clone(res.rig), pivot_before, pivot_after, block_before, block_after });
    }
    this.load_notices = load_notices(res);
    this.rig = res.rig;
    this.pivot = pivot_after;
    this.scene_block = block_after;
    this.ref0 = null;
    this.delta = null;
    return { changed, framing: true };
  }

  // ---------------------------------------------------------------------------------------------- readouts

  /** The notices shown under the panes: the load clamps and "眼睛在地面下方" (§5.7.10). */
  notices(): string[] {
    const out = [...this.load_notices];
    if (readouts(this.rig, this.scene_.camera.frame_mm).eye_below_ground) out.push(NOTICE_EYE_BELOW_GROUND);
    return out;
  }

  /** The readout lines of spec-v0.2 §5.8 (§5.7.10). */
  readout_lines(): string[] {
    return readout_lines(this.rig, this.scene_.camera.frame_mm, this.delta);
  }
}

function load_notices(res: { clampedD: boolean; clampedR: boolean }): string[] {
  const out: string[] = [];
  if (res.clampedR) out.push(NOTICE_R_CLAMPED);
  if (res.clampedD) out.push(NOTICE_D_CLAMPED);
  return out;
}

const same3 = (p: readonly number[], q: readonly number[]): boolean => p[0] === q[0] && p[1] === q[1] && p[2] === q[2];

const f2 = (x: number): string => {
  const t = x.toFixed(2);
  return t === "-0.00" ? "0.00" : t;
};

/** The readout lines (spec-v0.2 §5.8): plane, `g` and `R`, `E`, `D`, pan and roll, frame size, picture delta. */
export function readout_lines(rig: RigState, frame_mm: readonly number[], delta: number | null): string[] {
  const r = readouts(rig, frame_mm);
  const [w, h] = frameMetres(rig, frame_mm);
  return [
    `投影平面：${r.equation}`,
    `板子離場景 g = ${f2(r.g)} m · 觀看距離 R = ${f2(r.R)} m`,
    `眼睛 E（唯讀）= (${r.E.map(f2).join(", ")})`,
    `眼睛到板子 D = ${f2(r.D)} m`,
    `平移 (a, b) = (${f2(r.a)}, ${f2(r.b)}) m · 滾轉 ${f2(r.roll_deg)}°`,
    `畫框 ${f2(w)} × ${f2(h)} m`,
    `這次拖動右窗畫面變動：${deltaText(delta)}`,
  ];
}

/** The current plane's equation (the field's text while it is not focused). */
export function equation_text(rig: RigState): string {
  return equation(rig);
}

/** The pivot of an object: the centre of its stage-A bounding box. */
export function object_centres(objects: readonly { id: string; bbox: readonly (readonly number[])[] }[]): Map<string, Vec3> {
  return new Map(objects.map((o) => [o.id, bboxCentre(o.bbox)]));
}

// ------------------------------------------------------------------------------------------------ left-pane handles

/** The ring grab (§5.7.8 item 1) for ring point `X` with the observer's right / up axes. */
export function ring_grab(X: readonly number[], P: readonly number[], r_c: Vec3, u_c: Vec3): RingGrab {
  return { w: [X[0]! - P[0]!, X[1]! - P[1]!, X[2]! - P[2]!], r_c, u_c };
}

/** A ring drag in the observer pane from the pointer-down state. */
export function ring_drag(rig0: RigState, grab: RingGrab, dx: number, dy: number, snap: boolean): RigState {
  return orbitRing(rig0, dx, dy, grab, snap);
}

/** An arrow drag in the observer pane from the pointer-down state with the screen vector `v`. */
export function arrow_drag(rig0: RigState, v: Vec2, dx: number, dy: number, snap: boolean): RigState {
  return arrowDrag(rig0, v, dx, dy, snap);
}
