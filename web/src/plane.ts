/**
 * Plane mode's session (M10; spec-v0.2 §4.2, §5; contract §5.7.7–§5.7.10) — pure, DOM-free and unit-tested
 * (`web/test/plane.test.ts`). It owns the rig of the loaded scene, the undo stack, the pivot selection, the
 * "unedited scene camera" flag and the picture-delta readout, and maps the observer pane's handle drags (ring, arrow)
 * and the controls onto the rig operations of `rig.ts` (which it never re-implements). The drawing pane is view-only:
 * no gesture there reaches the session. `main.ts` wires the DOM to it.
 */

import type { Transform, Vec2, Vec3 } from "castplane";

import {
  UndoStack, arrowDrag, bboxCentre, clone, deltaText, equation, frameMetres, fromCamera, measureRef, orbitRing,
  pictureDelta, readouts, sameState, setD, setFocal, setLockLevel, setPivot, setRoll, sixView, toCameraBlock,
} from "./rig.js";
import type { AnyCamera, GroupFramePose, ObjectPose, PicturePlaneCamera, RigState, RingGrab, UndoEntry, ViewName } from "./rig.js";
import { EquationError, applyEquation } from "./equation.js";
import { GROUP_VALUE_PREFIX } from "./groups.js";
import { clone_group_frame, clone_transform, identity3, local_bbox, world_bbox } from "./object_rotate.js";
import type { GroupFrame } from "./object_rotate.js";

/** The pivot selection (§5.7.7): not part of an undo snapshot. D84: `object_id` is an object id or a group's key
 * `group.<name>` (`groups.ts::selection_value`; object ids cannot contain `.`). */
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
  /** M11 (contract §5.8.3): each object's load-time transform and stage-A world vertices (`mesh.vertices`), from
   * which the session caches the local pivots and the load-time transforms (還原此物體). Optional: without it no object
   * can be rotated. */
  object_poses?: readonly { id: string; transform: Transform; vertices: readonly (readonly number[])[] }[];
  /** D84: the groups with at least two members (`groups.ts::group_members`), member ids in scene order. Each gets a
   * frame: `G = I` and `c` the centre of the load-time world bounding box of its members' `object_poses` vertices. */
  groups?: ReadonlyMap<string, readonly string[]>;
}

/** What changed after a session action: `framing` asks for an observer re-framing (§5.6.4: views, equation, reset,
 * undo, pivot changes). */
export interface ActionResult {
  changed: boolean;
  framing: boolean;
}

/** M11 (contract §5.8.3): an undo whose top entry is an object step reports it here without consuming it; the caller
 * recomputes stage A with `transform` and, on success, calls {@link PlaneSession.pop_object_step}. */
export type UndoResult = ActionResult & { object?: { id: string; transform: Transform };
  objects?: { transforms: Map<string, Transform>; group: GroupFramePose | null } };

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
  private scene_: SessionScene;
  /** M11 (contract §5.8.1): per object id the centre of its local bounding box `c_local` (the rotation pivot), computed
   * once at load; {@link update_scene} never changes it. */
  readonly local_centres: ReadonlyMap<string, Vec3>;
  /** M11: per object id half its local bounding-box diagonal (the ring radius, spec-v0.3 §3.2), computed at load. */
  readonly local_half_diagonals: ReadonlyMap<string, number>;
  /** M11: per object id its load-time transform (還原此物體). */
  private readonly initial_transforms: ReadonlyMap<string, Transform>;
  /** D84: per group (≥ 2 members) its member ids in scene order. */
  readonly groups: ReadonlyMap<string, readonly string[]>;
  /** D84: per group half the diagonal of its load-time world bounding box (the ring radius) and its load-time `c0`. */
  readonly group_loads: ReadonlyMap<string, { c0: Vec3; half_diagonal: number }>;
  /** D84: per group its current frame (`G` relative to the load, `c`). */
  private readonly group_frames = new Map<string, GroupFrame>();

  constructor(scene: SessionScene) {
    this.scene_ = scene;
    const centres = new Map<string, Vec3>(), diagonals = new Map<string, number>(), initial = new Map<string, Transform>();
    for (const o of scene.object_poses ?? []) {
      const b = local_bbox(o.transform, o.vertices);
      centres.set(o.id, b.centre);
      diagonals.set(o.id, b.half_diagonal);
      initial.set(o.id, clone_transform(o.transform));
    }
    this.local_centres = centres;
    this.local_half_diagonals = diagonals;
    this.initial_transforms = initial;
    const verts = new Map((scene.object_poses ?? []).map((o) => [o.id, o.vertices]));
    const groups = new Map<string, readonly string[]>(), loads = new Map<string, { c0: Vec3; half_diagonal: number }>();
    for (const [name, ids] of scene.groups ?? []) {
      const members = ids.filter((id) => initial.has(id));
      if (members.length < 2) continue;
      const b = world_bbox(members.map((id) => verts.get(id) ?? []));
      groups.set(name, members);
      loads.set(name, { c0: b.centre, half_diagonal: b.half_diagonal });
      this.group_frames.set(name, { name, G: identity3(), c: [b.centre[0], b.centre[1], b.centre[2]] });
    }
    this.groups = groups;
    this.group_loads = loads;
    const res = fromCamera(scene.camera, scene.centre);
    this.rig = res.rig;
    this.initial = clone(res.rig);
    this.clamped = res.clampedD || res.clampedR;
    this.scene_block = !this.clamped;
    this.load_notices = [];
    if (res.clampedR) this.load_notices.push(NOTICE_R_CLAMPED);
    if (res.clampedD) this.load_notices.push(NOTICE_D_CLAMPED);
  }

  /** What the session knows of the scene (replaced by {@link update_scene} after an object rotation). */
  get scene(): SessionScene {
    return this.scene_;
  }

  /**
   * M11 (contract §5.8.3): an object was rotated. From the new stage-A record only `object_centres` (`objects`' bounding
   * box centres) and `vertices` change; the rig (with `P`), `initial`, the scene centre, the camera, `scene_block`,
   * the load notices and the local pivots are kept. The picture-delta reference is cleared (it describes board drags).
   */
  update_scene(objects: readonly { id: string; bbox: readonly (readonly number[])[] }[], A: { vertices: readonly Vec3[] }): void {
    this.scene_ = { ...this.scene_, object_centres: object_centres(objects), vertices: A.vertices };
    this.ref0 = null;
    this.delta = null;
  }

  /** M11: the load-time transform of object `id` (a copy; null for an unknown id). */
  initial_transform(id: string): Transform | null {
    const t = this.initial_transforms.get(id);
    return t === undefined ? null : clone_transform(t);
  }

  /** D84: group `name`'s current frame (a copy; null for an unknown group). */
  group_frame(name: string): GroupFrame | null {
    const f = this.group_frames.get(name);
    return f === undefined ? null : clone_group_frame(f);
  }

  /** D84: group `name`'s load-time frame (`G = I`, `c = c0`; null for an unknown group). */
  initial_group_frame(name: string): GroupFrame | null {
    const l = this.group_loads.get(name);
    return l === undefined ? null : { name, G: identity3(), c: [l.c0[0], l.c0[1], l.c0[2]] };
  }

  /** D84: set group `frame.name`'s frame (a copy; ignored for an unknown group). Not an undo step by itself. */
  set_group_frame(frame: GroupFrame): void {
    if (this.group_frames.has(frame.name)) this.group_frames.set(frame.name, clone_group_frame(frame));
  }

  /** D84: one undo step for a discrete group action when a member's pose or the group frame changed. */
  record_objects(before: ReadonlyMap<string, ObjectPose>, group_before: GroupFramePose | null, after: ReadonlyMap<string, ObjectPose>,
    group_after: GroupFramePose | null): boolean {
    return this.undo.record_objects(before, group_before, after, group_after);
  }

  /** D84: pointer-down of a group drag (opens one undo step). */
  begin_objects(before: ReadonlyMap<string, ObjectPose>, group: GroupFramePose | null): void {
    this.undo.begin_objects(before, group);
  }

  /** D84: release of a group drag: one undo step when anything changed. */
  end_objects(after: ReadonlyMap<string, ObjectPose>, group: GroupFramePose | null): boolean {
    return this.undo.end_objects(after, group);
  }

  /** M11: one undo step for a discrete object action (numeric apply, 還原此物體, 落地) when the pose changed. */
  record_object(id: string, before: Transform, after: Transform): boolean {
    return this.undo.record_object(id, before, after);
  }

  /** M11: pointer-down of an object drag (opens one undo step; the board's gesture state is not touched). */
  begin_object(id: string, t0: Transform): void {
    this.undo.begin_object(id, t0);
  }

  /** M11: release of an object drag with the committed pose `t`: one undo step when it differs from the pointer-down
   * pose. */
  end_object(t: Transform): boolean {
    return this.undo.end_object(t);
  }

  /** M11: abandon an object drag (no step). */
  cancel_object(): void {
    this.undo.cancel();
  }

  /** The top undo entry without consuming it (null when empty). */
  peek_undo(): UndoEntry | null {
    return this.undo.peek();
  }

  /** M11: pop the top entry after its object step was applied successfully (no-op when the top is not an object step);
   * an open board gesture is kept. */
  pop_object_step(): void {
    const k = this.undo.peek()?.kind;
    if (k === "object" || k === "objects") this.undo.pop_top();
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

  /** D84: pick group `name` as the pivot (object mode only): its frame's `c`, as {@link pick_object} otherwise. */
  pick_group(name: string): ActionResult {
    if (this.pivot.mode !== "object" || !this.group_frames.has(name)) return { changed: false, framing: false };
    this.pivot = { mode: "object", object_id: GROUP_VALUE_PREFIX + name };
    return this.move_pivot(this.pivot_point(), true);
  }

  /** The pivot of the current selection (§5.7.7; D84 a group's key gives its frame's `c`). */
  pivot_point(): Vec3 {
    const id = this.pivot.mode === "object" ? this.pivot.object_id : null;
    const c = id === null ? undefined : id.startsWith(GROUP_VALUE_PREFIX)
      ? this.group_frames.get(id.slice(GROUP_VALUE_PREFIX.length))?.c : this.scene.object_centres.get(id);
    return c === undefined ? [...this.scene.centre] as Vec3 : [...c] as Vec3;
  }

  /** Move the pivot to `P` (pan cleared). With the same `P`, only a `recentre` (an explicit pick) clears the pan. */
  private move_pivot(P: Vec3, recentre: boolean): ActionResult {
    if (same3(P, this.rig.P) && (!recentre || (this.rig.a === 0 && this.rig.b === 0))) return { changed: false, framing: false };
    this.ref0 = null;
    const changed = this.assign(setPivot(this.rig, P));
    return { changed, framing: changed };
  }

  /** Undo (§5.7.8 item 13): restores the last board snapshot (the current pivot kept) and re-frames the observer. M11
   * (§5.8.3): an object step on top is only peeked and returned in `object`; the rig is not touched. */
  undo_step(): UndoResult {
    const top = this.undo.peek();
    if (top === null) return { changed: false, framing: false };
    if (top.kind === "object") return { changed: false, framing: false, object: { id: top.id, transform: top.before } };
    if (top.kind === "objects") {
      return { changed: false, framing: false, objects: { transforms: new Map([...top.before].map(([id, t]) => [id, clone_transform(t)])),
        group: top.group } };
    }
    const prev = this.undo.undo(this.rig);
    if (prev === null || prev.kind !== "rig") return { changed: false, framing: false };
    this.ref0 = null;
    const changed = this.assign(prev.rig);
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
