/**
 * Plane mode's session (M10; spec-v0.2 §4.2, §5; contract §5.7.7–§5.7.10) — pure, DOM-free and unit-tested
 * (`web/test/plane.test.ts`). It owns the rig of the loaded scene, the undo stack, the pivot selection, the
 * "unedited scene camera" flag and the picture-delta readout, and maps the observer pane's handle drags (ring, arrow)
 * and the controls onto the rig operations of `rig.ts` (which it never re-implements). The drawing pane is view-only:
 * no gesture there reaches the session. `main.ts` wires the DOM to it.
 */

import type { Vec2, Vec3 } from "castplane";

import {
  UndoStack, arrowDrag, bboxCentre, clone, deltaText, equation, frameMetres, fromCamera, measureRef, orbitRing,
  pictureDelta, readouts, sameState, setD, setFocal, setLockLevel, setPivot, setRoll, sixView, toCameraBlock,
} from "./rig.js";
import type { AnyCamera, PicturePlaneCamera, RigState, RingGrab, ViewName } from "./rig.js";
import { EquationError, applyEquation } from "./equation.js";

/** The pivot selection (§5.7.7): not part of an undo snapshot. */
export interface PivotSelection {
  mode: "scene" | "object";
  object_id: string | null;
}

/** Notices of the readout area (not document warnings, §5.7.10). */
export const NOTICE_R_CLAMPED = "相機與場景中心的距離超出範圍，已調整";
export const NOTICE_D_CLAMPED = "眼睛到板子的距離 D 超出滑桿範圍（0.5–12 m），已調整";
export const NOTICE_EYE_BELOW_GROUND = "眼睛在地面下方";

/** What the session needs of a loaded scene. */
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

/**
 * The plane-mode session of one loaded scene. Every rig change goes through it: handle drags in the observer pane
 * (`begin` / `drag` / `end`), the sliders, views, the equation, lock-horizontal, pivot, undo and reset. While {@link scene_block} is true
 * (since the load or a reset, until the first rig change) the core renders the scene camera itself, so the document,
 * its warnings and the downloads are the CLI's; the rig's `picture_plane` block has the same picture (§5.7.7 load rule,
 * no clamp), and every change switches to it.
 */
export class PlaneSession {
  rig: RigState;
  /** The load rule's state (reset target). */
  readonly initial: RigState;
  readonly undo = new UndoStack();
  pivot: PivotSelection = { mode: "scene", object_id: null };
  /** Whether the frame renders the scene camera as it is (unedited since the load or reset, no load clamp). */
  scene_block: boolean;
  /** The load rule's notices (clamps). */
  readonly load_notices: string[];
  private delta_: number | null = null;
  /** Whether {@link delta} must be re-measured (computed lazily: at most once per rendered frame, not per pointer event). */
  private delta_stale = false;
  private ref0: (Vec2 | null)[] | null = null;
  private gesture0: { rig: RigState; scene_block: boolean; delta: number | null } | null = null;
  private readonly clamped: boolean;

  constructor(readonly scene: SessionScene) {
    const res = fromCamera(scene.camera, scene.centre);
    this.rig = res.rig;
    this.initial = clone(res.rig);
    this.clamped = res.clampedD || res.clampedR;
    this.scene_block = !this.clamped;
    this.load_notices = [];
    if (res.clampedR) this.load_notices.push(NOTICE_R_CLAMPED);
    if (res.clampedD) this.load_notices.push(NOTICE_D_CLAMPED);
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
    return toCameraBlock(this.rig, this.scene.camera);
  }

  /** The block the core renders and the downloads write: the scene camera while {@link scene_block}, else the rig's. */
  block(): AnyCamera {
    return this.scene_block ? this.scene.camera : this.rig_block();
  }

  /** Image of every stage-A vertex in frame mm through the rig (null behind the eye). */
  measure(rig: RigState = this.rig): (Vec2 | null)[] {
    return measureRef(rig, this.scene.camera, this.scene.canvas_mm, this.scene.vertices);
  }

  /** Replace the rig; any change leaves the scene camera's block. Returns whether the state changed. */
  private assign(next: RigState): boolean {
    const changed = !sameState(this.rig, next) || !same3(this.rig.P, next.P);
    this.rig = next;
    if (changed) this.scene_block = false;
    if (changed && this.ref0 !== null) this.delta_stale = true;
    return changed;
  }

  // ---------------------------------------------------------------------------------------------- gestures

  /** Pointer-down of a handle drag (ring, arrow): opens one undo step and the delta. */
  begin(): void {
    this.undo.begin(this.rig);
    this.gesture0 = { rig: clone(this.rig), scene_block: this.scene_block, delta: this.delta };
    this.ref0 = this.measure();
    this.delta = 0;
  }

  /** Abandon the current gesture (a second finger on a handle drag): the pointer-down state comes back, no step. */
  cancel(): void {
    const g = this.gesture0;
    this.undo.cancel();
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

  /** Release: one undo step when the board changed (§5.7.8 item 13). */
  end(): boolean {
    this.gesture0 = null;
    return this.undo.end(this.rig);
  }

  // ---------------------------------------------------------------------------------------------- discrete actions

  private discrete(next: RigState, framing: boolean): ActionResult {
    const before = this.rig;
    this.undo.record(before, next);
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
    return { changed: this.assign(next), framing: false };
  }

  /** Focal length slider (mm): not an undo step. */
  set_focal(focal: number): boolean {
    return this.assign(setFocal(this.rig, focal));
  }

  /** `D` slider (m): clamped so that `R ∈ [0.8, 40]`; not an undo step. */
  set_D(D: number): boolean {
    return this.assign(setD(this.rig, D));
  }

  /** Roll slider (degrees about the line of sight; the eye does not move): not an undo step. */
  set_roll(roll_deg: number): boolean {
    return this.assign(setRoll(this.rig, roll_deg));
  }

  /** Pivot mode (§5.7.8 item 10): "scene" moves the pivot to the scene centre; "object" keeps the current pivot until
   * an object is picked (the scene centre until then). Not an undo step; only a pivot that actually moves clears the
   * pan and re-frames the observer (switching the mode alone, with the same pivot point, changes nothing). */
  set_pivot_mode(mode: PivotSelection["mode"]): ActionResult {
    this.pivot = { mode, object_id: mode === "scene" ? null : this.pivot.object_id };
    return this.move_pivot(this.pivot_point(), false);
  }

  /** Pick an object as the pivot (object mode only): the eye moves onto its axis (pan cleared), also when the object
   * was already the pivot (an explicit pick re-centres it, spec-v0.2 §7.1). */
  pick_object(id: string): ActionResult {
    if (this.pivot.mode !== "object" || !this.scene.object_centres.has(id)) return { changed: false, framing: false };
    this.pivot = { mode: "object", object_id: id };
    return this.move_pivot(this.pivot_point(), true);
  }

  /** The pivot of the current selection (§5.7.7). */
  pivot_point(): Vec3 {
    const id = this.pivot.mode === "object" ? this.pivot.object_id : null;
    const c = id === null ? undefined : this.scene.object_centres.get(id);
    return c === undefined ? [...this.scene.centre] as Vec3 : [...c] as Vec3;
  }

  /** Move the pivot to `P` (pan cleared). With the same `P`, only a `recentre` (an explicit pick) clears the pan. */
  private move_pivot(P: Vec3, recentre: boolean): ActionResult {
    if (same3(P, this.rig.P) && (!recentre || (this.rig.a === 0 && this.rig.b === 0))) return { changed: false, framing: false };
    this.ref0 = null;
    const changed = this.assign(setPivot(this.rig, P));
    return { changed, framing: changed };
  }

  /** Undo (§5.7.8 item 13): restores the last snapshot (the current pivot kept); re-frames the observer. */
  undo_step(): ActionResult {
    const prev = this.undo.undo(this.rig);
    if (prev === null) return { changed: false, framing: false };
    this.ref0 = null;
    const changed = this.assign(prev);
    return { changed, framing: true };
  }

  /** Reset (§5.7.8 item 13): the load rule's state, the scene-centre pivot, the scene camera's block again (when the
   * load clamped nothing). One undo step; the caller also resets the observer's direction and frames it. */
  reset(): ActionResult {
    const next = clone(this.initial);
    this.undo.record(this.rig, next);
    this.pivot = { mode: "scene", object_id: null };
    this.ref0 = null;
    this.delta = null;
    const changed = !sameState(this.rig, next) || !same3(this.rig.P, next.P);
    this.rig = next;
    this.scene_block = !this.clamped;
    return { changed, framing: true };
  }

  // ---------------------------------------------------------------------------------------------- readouts

  /** The notices shown under the panes: the load clamps and "眼睛在地面下方" (§5.7.10). */
  notices(): string[] {
    const out = [...this.load_notices];
    if (readouts(this.rig, this.scene.camera.frame_mm).eye_below_ground) out.push(NOTICE_EYE_BELOW_GROUND);
    return out;
  }

  /** The readout lines of spec-v0.2 §5.8 (§5.7.10). */
  readout_lines(): string[] {
    return readout_lines(this.rig, this.scene.camera.frame_mm, this.delta);
  }
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
