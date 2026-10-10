/**
 * Selection, hit testing and the key helpers of M11 (spec-v0.3 §3, §6, §7; contract §5.8.2, §5.8.10, §5.8.11; D81,
 * D86) — pure, DOM-free and unit-tested (`web/test/selection.test.ts`).
 *
 * Contents: the selection state and its transitions (a press selects at once and keeps the previous selection to
 * restore on a cancel; add, delete, load and the object history entries move it as §5.8.2 says); the pointer ray of
 * the observer pane (`observer_ray`); exact ray–object hit tests for every object type (`box`, `cylinder`, `sphere`,
 * `cone`, `prism` — concave prisms included, no convexity is assumed — and the inline `mesh` on its stage-A
 * triangles), the nearest hit winning (`nearest_hit`); the observer pane's hit priority tip > ring > the selected
 * object's vertical handle > object > blank (`hit_order`, `press_target`); the click / drag classifier with the 5 px
 * dead zone measured as the maximum excursion and the two-finger rule (`PressTracker`); and the keyboard helpers
 * `is_typing_target`, `shortcut_action` and `escape_action`.
 *
 * The drawing (right) pane takes no input (D79): nothing here is for it. Hit tests use the observer camera's ray only.
 */

import { build_object, transform_frame } from "castplane";
import type { CameraRecord, GeometryDocument, SceneObject, Vec2, Vec3 } from "castplane";

import {
  CLICK_PX, HIT_PX_MOUSE, HIT_PX_TOUCH, OBSERVER_NEAR_M, hit_handles, observer_basis, observer_project_with, sample_arc,
  sample_ellipse,
} from "./observer.js";
import type { HandleHit, Handles, ObserverView } from "./observer.js";
import { focal_px } from "./scene_edit.js";
import type { CameraFrame, Ray } from "./scene_edit.js";

export { CLICK_PX, HIT_PX_MOUSE, HIT_PX_TOUCH };

// ------------------------------------------------------------------------------------------------ vector helpers

const add = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! + q[0]!, p[1]! + q[1]!, p[2]! + q[2]!];
const sub = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! - q[0]!, p[1]! - q[1]!, p[2]! - q[2]!];
const mul = (p: readonly number[], s: number): Vec3 => [p[0]! * s, p[1]! * s, p[2]! * s];
const dot = (p: readonly number[], q: readonly number[]): number => p[0]! * q[0]! + p[1]! * q[1]! + p[2]! * q[2]!;
const len = (p: readonly number[]): number => Math.sqrt(dot(p, p));
const unit = (p: readonly number[]): Vec3 => { const l = len(p); return [p[0]! / l, p[1]! / l, p[2]! / l]; };

// ------------------------------------------------------------------------------------------------ selection state (§5.8.2)

/**
 * The selection (web state, never in the scene JSON or a history entry): at most one object id, and while a press on
 * an object is pending, the selection of before the press (restored on a cancel).
 */
export interface SelectionState {
  selected: string | null;
  /** Set by {@link press_select} until the press ends ({@link end_press}) or is cancelled ({@link cancel_press}). */
  pending: { prev: string | null } | null;
}

export function empty_selection(): SelectionState {
  return { selected: null, pending: null };
}

/** A press on an object selects it at once; the previous selection is kept to restore on a cancel. */
export function press_select(s: SelectionState, id: string): SelectionState {
  return { selected: id, pending: { prev: s.pending !== null ? s.pending.prev : s.selected } };
}

/** A cancelled press (second finger before 5 px, `pointercancel`, a load, entering 預覽): the old selection returns. */
export function cancel_press(s: SelectionState): SelectionState {
  return s.pending === null ? s : { selected: s.pending.prev, pending: null };
}

/** The press ended (a click or a drag): the selection stays. */
export function end_press(s: SelectionState): SelectionState {
  return { selected: s.selected, pending: null };
}

/** A blank click in the observer pane, Esc in the edit view, a delete or a load: nothing selected. */
export function clear_selection(_s?: SelectionState): SelectionState {
  return { selected: null, pending: null };
}

/** An add selects the new object (§5.8.2). */
export function select_added(id: string): SelectionState {
  return { selected: id, pending: null };
}

/**
 * After an undo or redo (§5.8.2): an object entry selects the object it acted on (`selected` from
 * `scene_edit.apply_entry`: the inserted or moved object, `null` after a removal); a board or reset entry
 * (`entry_selected === undefined`) keeps the selection; either way a selected id that no longer exists is cleared.
 */
export function after_history(s: SelectionState, entry_selected: string | null | undefined,
  objects: readonly { id: string }[]): SelectionState {
  const sel = entry_selected === undefined ? s.selected : entry_selected;
  return { selected: sel !== null && objects.some((o) => o.id === sel) ? sel : null, pending: null };
}

/** The selection with a missing id cleared. */
export function prune_selection(s: SelectionState, objects: readonly { id: string }[]): SelectionState {
  return s.selected !== null && !objects.some((o) => o.id === s.selected) ? { selected: null, pending: s.pending } : s;
}

/** The focus object of the vertex rays (§5.8.6): the selection if it exists, else `objects[0]` (null when empty). */
export function focus_object_id(selected: string | null, objects: readonly { id: string }[]): string | null {
  if (selected !== null && objects.some((o) => o.id === selected)) return selected;
  return objects[0]?.id ?? null;
}

// ------------------------------------------------------------------------------------------------ observer ray

/** The observer camera as a {@link CameraFrame} for a pane `H_px` high. */
export function observer_frame(view: ObserverView, H_px: number): CameraFrame {
  const b = observer_basis(view);
  return { pos: b.pos, r: b.r, u: b.u, f: b.f, f_px: focal_px(H_px) };
}

/** The ray from the camera through the pane point `p` (CSS px, y down) of a `W × H` pane. */
export function frame_ray(cam: CameraFrame, W: number, H: number, p: Vec2): Ray {
  const x = (p[0] - W / 2) / cam.f_px, y = (H / 2 - p[1]) / cam.f_px;
  return { e: [cam.pos[0], cam.pos[1], cam.pos[2]], d: unit(add(add(cam.f, mul(cam.r, x)), mul(cam.u, y))) };
}

/** The observer ray (§5.8.2): from the observer camera through the pointer (vertical field of view 40°). */
export function observer_ray(view: ObserverView, W: number, H: number, p: Vec2): Ray {
  return frame_ray(observer_frame(view, H), W, H, p);
}

// ------------------------------------------------------------------------------------------------ ray–object hits

/** A hit: the ray parameter `t` (metres along the unit ray), the world point and the object. */
export interface ObjectHit {
  id: string;
  index: number;
  t: number;
  point: Vec3;
}

/** A surface crossing in local coordinates: `t` and whether the ray enters the solid there (front face). */
interface Crossing {
  t: number;
  enter: boolean;
}

/** Intervals of `t` with `A·t² + B·t + C ≤ 0` (`A` near zero is the linear case). */
function quad_le0(A: number, B: number, C: number, scale: number): [number, number][] {
  if (Math.abs(A) <= 1e-14 * scale) {
    if (B === 0) return C <= 0 ? [[-Infinity, Infinity]] : [];
    const r = -C / B;
    return B > 0 ? [[-Infinity, r]] : [[r, Infinity]];
  }
  const disc = B * B - 4 * A * C;
  if (disc < 0) return A > 0 ? [] : [[-Infinity, Infinity]];
  const sq = Math.sqrt(disc);
  // the numerically stable pair of roots
  const q = -0.5 * (B + (B >= 0 ? sq : -sq));
  let r1 = q / A, r2 = q !== 0 ? C / q : r1;
  if (r1 > r2) [r1, r2] = [r2, r1];
  return A > 0 ? [[r1, r2]] : [[-Infinity, r1], [r2, Infinity]];
}

/** The slab `lo ≤ e + t·d ≤ hi` along one axis as an interval of `t` (`null`: empty). */
function slab(e: number, d: number, lo: number, hi: number): [number, number] | null {
  if (d === 0) return e >= lo && e <= hi ? [-Infinity, Infinity] : null;
  const a = (lo - e) / d, b = (hi - e) / d;
  return a <= b ? [a, b] : [b, a];
}

function intersect(a: [number, number], b: [number, number]): [number, number] | null {
  const lo = Math.max(a[0], b[0]), hi = Math.min(a[1], b[1]);
  return lo <= hi ? [lo, hi] : null;
}

/** The entries of a convex solid given as interval pieces (a finite lower end is an entering crossing). */
function entries(pieces: readonly ([number, number] | null)[]): Crossing[] {
  const out: Crossing[] = [];
  for (const p of pieces) if (p !== null && Number.isFinite(p[0])) out.push({ t: p[0], enter: true });
  return out;
}

/** Crossing-number point-in-polygon (any simple polygon, concave included). */
function in_polygon(poly: readonly (readonly number[])[], x: number, y: number): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i]![0]!, yi = poly[i]![1]!, xj = poly[j]![0]!, yj = poly[j]![1]!;
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function signed_area(poly: readonly (readonly number[])[]): number {
  let a = 0;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) a += poly[j]![0]! * poly[i]![1]! - poly[i]![0]! * poly[j]![1]!;
  return a / 2;
}

/** Crossings of the local ray with a primitive (anchor conventions of §5.8.1: every solid rests on `z = 0`). */
function primitive_crossings(obj: SceneObject, e: Vec3, d: Vec3): Crossing[] {
  switch (obj.type) {
    case "box": {
      const s = obj.size as Vec3;
      const x = slab(e[0], d[0], -s[0] / 2, s[0] / 2), y = slab(e[1], d[1], -s[1] / 2, s[1] / 2), z = slab(e[2], d[2], 0, s[2]);
      if (x === null || y === null || z === null) return [];
      const xy = intersect(x, y);
      return entries([xy === null ? null : intersect(xy, z)]);
    }
    case "cylinder": {
      const r = obj.radius as number, h = obj.height as number;
      const z = slab(e[2], d[2], 0, h);
      if (z === null) return [];
      const A = d[0] * d[0] + d[1] * d[1], B = 2 * (e[0] * d[0] + e[1] * d[1]), C = e[0] * e[0] + e[1] * e[1] - r * r;
      return entries(quad_le0(A, B, C, 1).map((p) => intersect(p, z)));
    }
    case "cone": {
      const r = obj.radius as number, h = obj.height as number, k2 = (r / h) ** 2;
      const z = slab(e[2], d[2], 0, h);
      if (z === null) return [];
      const hz = h - e[2];
      const A = d[0] * d[0] + d[1] * d[1] - k2 * d[2] * d[2];
      const B = 2 * (e[0] * d[0] + e[1] * d[1] + k2 * hz * d[2]);
      const C = e[0] * e[0] + e[1] * e[1] - k2 * hz * hz;
      return entries(quad_le0(A, B, C, 1 + k2).map((p) => intersect(p, z)));
    }
    case "sphere": {
      const r = obj.radius as number;
      const o: Vec3 = [e[0], e[1], e[2] - r];
      return entries(quad_le0(dot(d, d), 2 * dot(o, d), dot(o, o) - r * r, 1));
    }
    case "prism": {
      const poly = obj.polygon as Vec2[], h = obj.height as number;
      const ccw = signed_area(poly) > 0;
      const out: Crossing[] = [];
      if (d[2] !== 0) {
        for (const [zc, enter] of [[0, d[2] > 0], [h, d[2] < 0]] as const) {
          const t = (zc - e[2]) / d[2];
          if (in_polygon(poly, e[0] + t * d[0], e[1] + t * d[1])) out.push({ t, enter });
        }
      }
      for (let i = 0; i < poly.length; i++) {
        const a = poly[i]!, b = poly[(i + 1) % poly.length]!;
        const ex = b[0] - a[0], ey = b[1] - a[1];
        // e + t·d = a + v·(b − a) in x, y
        const den = d[0] * -ey - d[1] * -ex;
        if (den === 0) continue;
        const ax = a[0] - e[0], ay = a[1] - e[1];
        const t = (ax * -ey - ay * -ex) / den;
        const v = (d[0] * ay - d[1] * ax) / den;
        if (v < 0 || v > 1) continue;
        const zt = e[2] + t * d[2];
        if (zt < 0 || zt > h) continue;
        const nx = ccw ? ey : -ey, ny = ccw ? -ex : ex; // outward normal
        out.push({ t, enter: nx * d[0] + ny * d[1] < 0 });
      }
      return out;
    }
    default:
      return [];
  }
}

/** The faces of a world mesh (any planar polygon; a face is hit from either side, as the observer draws meshes
 * double-sided). */
export interface WorldMesh {
  vertices: readonly (readonly number[])[];
  faces: readonly (readonly number[])[];
}

function mesh_crossings(m: WorldMesh, e: Vec3, d: Vec3): number[] {
  const out: number[] = [];
  for (const face of m.faces) {
    if (face.length < 3) continue;
    const P = face.map((i) => m.vertices[i]!);
    // Newell normal
    let n: Vec3 = [0, 0, 0];
    for (let i = 0; i < P.length; i++) {
      const a = P[i]!, b = P[(i + 1) % P.length]!;
      n = add(n, [(a[1]! - b[1]!) * (a[2]! + b[2]!), (a[2]! - b[2]!) * (a[0]! + b[0]!), (a[0]! - b[0]!) * (a[1]! + b[1]!)]);
    }
    const den = dot(n, d);
    if (den === 0) continue;
    const t = dot(n, sub(P[0]!, e)) / den;
    const X = add(e, mul(d, t));
    // drop the dominant axis and test the point in the projected polygon
    const ax = Math.abs(n[0]) >= Math.abs(n[1]) && Math.abs(n[0]) >= Math.abs(n[2]) ? 0 : Math.abs(n[1]) >= Math.abs(n[2]) ? 1 : 2;
    const i0 = ax === 0 ? 1 : 0, i1 = ax === 2 ? 1 : 2;
    if (in_polygon(P.map((q) => [q[i0]!, q[i1]!]), X[i0]!, X[i1]!)) out.push(t);
  }
  return out;
}

/** Options of the hit tests: hits whose camera depth `t·(d·f)` is `≤ near` are ignored (the observer's near plane
 * cuts that part away). Without `f` the depth is `t`. */
export interface HitOptions {
  f?: readonly number[];
  near?: number;
}

/**
 * The first visible hit of `ray` on `obj`, or `null`: a primitive is hit where the ray enters it (its front faces;
 * exact quadrics and planes, not the tessellation), a `mesh` at any face crossing of its world mesh (`mesh`, the
 * stage-A record's, else the port's `build_object(obj).mesh`). Crossings at a depth `≤ near` are skipped.
 */
export function ray_object_t(ray: Ray, obj: SceneObject, opt: HitOptions = {}, mesh?: WorldMesh | null): number | null {
  const near = opt.near ?? OBSERVER_NEAR_M;
  const df = opt.f !== undefined ? dot(ray.d, opt.f) : 1;
  const visible = (t: number): boolean => Number.isFinite(t) && t * df > near;
  let best: number | null = null;
  if (obj.type === "mesh") {
    const m = mesh ?? build_object(obj).mesh;
    for (const t of mesh_crossings(m, ray.e, ray.d)) if (visible(t) && (best === null || t < best)) best = t;
    return best;
  }
  const [R, pos] = transform_frame(obj.transform);
  // local = Rᵀ·(world − position)
  const tr = (v: readonly number[]): Vec3 => [
    R[0][0] * v[0]! + R[1][0] * v[1]! + R[2][0] * v[2]!,
    R[0][1] * v[0]! + R[1][1] * v[1]! + R[2][1] * v[2]!,
    R[0][2] * v[0]! + R[1][2] * v[1]! + R[2][2] * v[2]!,
  ];
  const e = tr(sub(ray.e, pos)), d = tr(ray.d);
  for (const c of primitive_crossings(obj, e, d)) if (c.enter && visible(c.t) && (best === null || c.t < best)) best = c.t;
  return best;
}

/**
 * The nearest hit among `objects` (§5.8.2: the nearest ray hit wins; lights, receivers and grids are not candidates),
 * or `null`. `meshes[i]` is the stage-A world mesh of `objects[i]` when it is a `mesh` (optional).
 */
export function nearest_hit(ray: Ray, objects: readonly SceneObject[], opt: HitOptions = {},
  meshes?: readonly (WorldMesh | null | undefined)[]): ObjectHit | null {
  let best: ObjectHit | null = null;
  objects.forEach((obj, index) => {
    const t = ray_object_t(ray, obj, opt, meshes?.[index] ?? null);
    if (t !== null && (best === null || t < best.t)) best = { id: obj.id, index, t, point: add(ray.e, mul(ray.d, t)) };
  });
  return best;
}

// ------------------------------------------------------------------------------------------------ hit priority (§5.8.2)

/** What a press in the observer pane grabs. */
export type PressTarget =
  | { kind: "arrow" }
  | { kind: "ring"; index: number }
  | { kind: "handle"; id: string }
  | { kind: "object"; hit: ObjectHit }
  | { kind: "blank" };

/** The hit radius (px): 14 for a mouse, 26 for touch and pen. */
export function hit_radius(pointerType: string): number {
  return pointerType === "mouse" ? HIT_PX_MOUSE : HIT_PX_TOUCH;
}

/** Whether `p` is on the selected object's vertical handle: a disc of the hit radius around its tip (the shaft is
 * not hit). */
export function hit_vertical(basis: { pos: Vec3; r: Vec3; u: Vec3; f: Vec3 }, W: number, H: number, p: Vec2, touch: boolean,
  tip: readonly number[]): boolean {
  const q = observer_project_with(basis, W, H, tip);
  return q !== null && Math.hypot(q[0] - p[0], q[1] - p[1]) <= (touch ? HIT_PX_TOUCH : HIT_PX_MOUSE);
}

/**
 * The observer pane's order (first match wins): arrow tip > ring > the selected object's vertical handle > object >
 * blank. `vertical` is the selected id when its handle's tip disc was hit, else `null`.
 */
export function hit_order(c: { handle: HandleHit; vertical: string | null; object: ObjectHit | null }): PressTarget {
  if (c.handle !== null) return c.handle.kind === "arrow" ? { kind: "arrow" } : { kind: "ring", index: c.handle.index };
  if (c.vertical !== null) return { kind: "handle", id: c.vertical };
  if (c.object !== null) return { kind: "object", hit: c.object };
  return { kind: "blank" };
}

/** Everything {@link press_target} needs. */
export interface PressInput {
  view: ObserverView;
  W: number;
  H: number;
  p: Vec2;
  touch: boolean;
  /** The board handles (null while hidden). */
  handles: Handles | null;
  selected: string | null;
  /** The selected object's handle tip (null without a selection). */
  vertical_tip: readonly number[] | null;
  objects: readonly SceneObject[];
  meshes?: readonly (WorldMesh | null | undefined)[];
}

/** The target of a press in the observer pane, by {@link hit_order}. */
export function press_target(inp: PressInput): PressTarget {
  const basis = observer_basis(inp.view);
  const handle = inp.handles === null ? null : hit_handles(basis, inp.W, inp.H, inp.p, inp.touch, inp.handles);
  if (handle !== null) return hit_order({ handle, vertical: null, object: null });
  const vertical = inp.selected !== null && inp.vertical_tip !== null && hit_vertical(basis, inp.W, inp.H, inp.p, inp.touch, inp.vertical_tip)
    ? inp.selected : null;
  if (vertical !== null) return hit_order({ handle: null, vertical, object: null });
  const ray = observer_ray(inp.view, inp.W, inp.H, inp.p);
  const object = nearest_hit(ray, inp.objects, { f: basis.f, near: OBSERVER_NEAR_M }, inp.meshes);
  return hit_order({ handle: null, vertical: null, object });
}

// ------------------------------------------------------------------------------------------------ click vs drag (§5.8.2)

export type PressKind = "object" | "arrow" | "ring" | "handle" | "blank";

/** What a second pointer does to an open press: `cancel` it (no history entry; the observer pinch takes over),
 * `ignore` the second pointer, or hand over to the M10 observer `pinch` (a blank press is an orbit). */
export type SecondPointer = "cancel" | "ignore" | "pinch";

/**
 * One press: `moved` is the **largest** distance from the pointer-down point reached so far (not the net distance);
 * the press becomes a drag once `moved ≥ CLICK_PX` and stays one; a release with `moved < CLICK_PX` is a click. An
 * object does not move before the threshold, and from then on its position comes from the total displacement.
 */
export class PressTracker {
  moved = 0;
  dx = 0;
  dy = 0;

  constructor(readonly kind: PressKind, readonly x0: number, readonly y0: number) {}

  /** A pointer move: updates the total displacement and the maximum excursion. */
  move(x: number, y: number): { dx: number; dy: number; dragging: boolean } {
    this.dx = x - this.x0;
    this.dy = y - this.y0;
    this.moved = Math.max(this.moved, Math.hypot(this.dx, this.dy));
    return { dx: this.dx, dy: this.dy, dragging: this.dragging };
  }

  get dragging(): boolean {
    return this.moved >= CLICK_PX;
  }

  /** Release: a click or a drag. */
  release(): "click" | "drag" {
    return this.dragging ? "drag" : "click";
  }

  /**
   * A second pointer (or `pointercancel`, which cancels like a second finger) during this press (§5.8.2, Q18): an
   * object press that has moved `< CLICK_PX` is cancelled, one that has moved `≥ CLICK_PX` ignores it; a handle drag
   * (arrow, ring, vertical handle) is cancelled as in M10; a blank press (orbit) becomes the observer pinch.
   */
  second_pointer(): SecondPointer {
    switch (this.kind) {
      case "object":
        return this.dragging ? "ignore" : "cancel";
      case "blank":
        return "pinch";
      default:
        return "cancel";
    }
  }
}

// ------------------------------------------------------------------------------------------------ keys (§5.8.10, §5.8.11)

/** The focused element as plain data: tag name, `type` attribute (inputs) and whether it is `contenteditable`. */
export interface TargetLike {
  tag: string;
  type?: string | null;
  editable?: boolean;
}

/** Input types that are not text-like (they take the shortcuts); every other type, missing or unknown, is. */
export const NON_TEXT_INPUT_TYPES: readonly string[] = ["range", "checkbox", "radio", "button", "submit", "reset", "file", "image", "color", "hidden"];

/** Whether focus is in a text-like target: `<textarea>`, a `contenteditable` element or a text-like `<input>`. */
export function is_typing_target(t: TargetLike | null | undefined): boolean {
  if (t === null || t === undefined) return false;
  if (t.editable === true) return true;
  const tag = t.tag.toLowerCase();
  if (tag === "textarea") return true;
  if (tag !== "input") return false;
  const type = (t.type ?? "").toLowerCase();
  return !NON_TEXT_INPUT_TYPES.includes(type);
}

/** The keyboard event as plain data. */
export interface KeyLike {
  key: string;
  code?: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
  isComposing?: boolean;
}

/** Where focus is: the equation field (its own Esc), another text-like target, or anything else. */
export type FocusKind = "equation" | "text" | "other";

export function focus_kind(t: TargetLike | null | undefined, is_equation: boolean): FocusKind {
  return is_equation ? "equation" : is_typing_target(t) ? "text" : "other";
}

export interface ShortcutContext {
  has_selection: boolean;
  previewing: boolean;
  /** Default `"other"`. */
  focus?: FocusKind;
  /** A ring, arrow, handle, vertical or object drag is open (default false). */
  gesture_open?: boolean;
  /** An object press that has not yet become a drag (before `CLICK_PX` of travel) is held (default false); Esc treats
   * it as an open gesture. */
  press_pending?: boolean;
}

export type ShortcutAction = "delete" | "undo" | "redo" | "toggle_library" | "leave_preview" | "clear_selection";

export type EscapeAction = "field" | "leave_preview" | "clear_selection";

/**
 * Esc (§5.8.11), one thing per press: focus in the equation field → `field` (its own Esc, no further effect); during
 * a drag, or while an object press is held that has not yet become one (`press_pending`: it may still become a drag of
 * the object it selected) → nothing; previewing → `leave_preview`; in the edit view with a selection →
 * `clear_selection`; else nothing. Esc never opens or closes the library.
 */
export function escape_action(st: { focus?: FocusKind; previewing: boolean; has_selection: boolean; gesture_open?: boolean;
  press_pending?: boolean }): EscapeAction | null {
  if (st.focus === "equation") return "field";
  if (st.gesture_open === true || st.press_pending === true) return null;
  if (st.previewing) return "leave_preview";
  return st.has_selection ? "clear_selection" : null;
}

/**
 * Whether `ev` is the letter `letter` (lower case): by `ev.key` when it is a single ASCII letter (the layout's own
 * letter, so QWERTZ's Ctrl+Y — `key` "y" on `code` "KeyZ" — is not Ctrl+Z), and by the physical `ev.code` only when
 * `ev.key` is not an ASCII letter (a non-Latin layout such as Cyrillic, or an unidentified key).
 */
export function is_key(ev: KeyLike, letter: string): boolean {
  if (/^[A-Za-z]$/.test(ev.key)) return ev.key.toLowerCase() === letter;
  return ev.code === `Key${letter.toUpperCase()}`;
}

/**
 * The shortcut a `keydown` at `window` triggers (§5.8.10, §5.8.11), or `null`; the caller calls `preventDefault`
 * exactly when the result is not `null` (a delete refused by the keep-one rule still counts as acting).
 * - IME composition: nothing.
 * - Esc: {@link escape_action} (`field` is the field's own business: `null` here).
 * - Previewing: nothing else acts and nothing is intercepted.
 * - Focus in a text-like target (the equation field included): nothing is intercepted.
 * - Delete / Backspace without Ctrl, Meta or Alt, with a selection: `delete` (not while a gesture is open).
 * - Ctrl+Z / ⌘Z: `undo`; Ctrl+Shift+Z / ⌘⇧Z: `redo` (not while a gesture is open; Alt excluded; Ctrl+Y is not bound).
 * - Ctrl+Shift+L / ⌘⇧L: `toggle_library`.
 * Z and L are matched by {@link is_key} (the layout's letter first, the physical key only for a non-Latin `key`).
 * Exactly one of Ctrl and ⌘ must be held: Ctrl+⌘+Z or Ctrl+⌘+Shift+L is not a shortcut.
 */
export function shortcut_action(ev: KeyLike, ctx: ShortcutContext): ShortcutAction | null {
  if (ev.isComposing === true) return null;
  const focus = ctx.focus ?? "other";
  if (ev.key === "Escape") {
    const a = escape_action({ focus, previewing: ctx.previewing, has_selection: ctx.has_selection, gesture_open: ctx.gesture_open ?? false,
      press_pending: ctx.press_pending ?? false });
    return a === "field" ? null : a;
  }
  if (ctx.previewing || focus !== "other") return null;
  const ctrl = ev.ctrlKey === true, meta = ev.metaKey === true, alt = ev.altKey === true, shift = ev.shiftKey === true;
  const gesture = ctx.gesture_open === true;
  if (ev.key === "Delete" || ev.key === "Backspace") {
    if (ctrl || meta || alt || !ctx.has_selection || gesture) return null;
    return "delete";
  }
  if (ctrl === meta || alt) return null; // exactly one of Ctrl and ⌘ (Ctrl+⌘ held together is not a shortcut)
  if (is_key(ev, "z")) return gesture ? null : shift ? "redo" : "undo";
  if (is_key(ev, "l") && shift) return "toggle_library";
  return null;
}

// ------------------------------------------------------------------------------------------------ overlays (§5.8.2, §5.8.12)

type ConicEntry = { polylines?: readonly (readonly (readonly number[])[])[]; arcs?: readonly Parameters<typeof sample_arc>[0][];
  ellipses?: readonly Parameters<typeof sample_ellipse>[0][] };

const v2 = (p: readonly number[]): Vec2 => [p[0]!, p[1]!];

/**
 * The selection outline of the drawing pane (§5.8.2): the document drawables of object `id` — its edges, its outline
 * generators and conics — as polylines in canvas mm (the document's `(u, v)`; the page maps them to the SVG's user
 * units `x = u + W/2`, `y = H/2 − v`). Interface only: it is drawn in `#sel-overlay`, never in an output (§5.8.13).
 */
export function outline_polylines(doc: Pick<GeometryDocument, "edges" | "outlines">, id: string): Vec2[][] {
  const out: Vec2[][] = [];
  for (const e of doc.edges) if (e.object === id && e.segment !== null) out.push(e.segment.map(v2));
  for (const o of doc.outlines) {
    if (o.object !== id) continue;
    for (const g of o.generators) if (g.segment !== null) out.push(g.segment.map(v2));
    for (const c of o.conics as readonly ConicEntry[]) {
      for (const pl of c.polylines ?? []) if (pl.length >= 2) out.push(pl.map(v2));
      for (const a of c.arcs ?? []) out.push(sample_arc(a));
      for (const e of c.ellipses ?? []) {
        const pts = sample_ellipse(e);
        out.push([...pts, pts[0]!]);
      }
    }
  }
  return out;
}

/** A world mesh's straight edges (stage A's record mesh): vertices, edges and the smooth flags (smooth edges of an
 * imported mesh are not drawn). */
export interface WireMesh {
  vertices: readonly (readonly number[])[];
  edges: readonly (readonly [number, number])[];
  edge_smooth?: readonly boolean[];
}

/**
 * The preview wireframe of an object drag (§5.8.12): every edge of `meshes` (the stage-A meshes of the pressed frame,
 * mesh `k` translated by `shifts[k]` when given — the dragged object's world displacement), projected through the
 * camera record `rec` to canvas mm; an edge with an end at a depth `< rec.near` is left out. No shadow, no
 * construction line; interface only (`#sel-overlay`), never an output.
 */
export function wire_segments(meshes: readonly WireMesh[], shifts: readonly (readonly number[] | null)[],
  rec: Pick<CameraRecord, "P" | "Rt" | "near">): [Vec2, Vec2][] {
  const out: [Vec2, Vec2][] = [];
  const P = rec.P, Z = rec.Rt[2];
  const proj = (X: readonly number[], d: readonly number[] | null): Vec2 | null => {
    const x = X[0]! + (d?.[0] ?? 0), y = X[1]! + (d?.[1] ?? 0), z = X[2]! + (d?.[2] ?? 0);
    if (Z[0] * x + Z[1] * y + Z[2] * z + Z[3] < rec.near) return null;
    const w = P[2][0] * x + P[2][1] * y + P[2][2] * z + P[2][3];
    return [(P[0][0] * x + P[0][1] * y + P[0][2] * z + P[0][3]) / w, (P[1][0] * x + P[1][1] * y + P[1][2] * z + P[1][3]) / w];
  };
  meshes.forEach((m, k) => {
    const d = shifts[k] ?? null;
    const img = m.vertices.map((X) => proj(X, d));
    m.edges.forEach(([i, j], e) => {
      if (m.edge_smooth?.[e] === true) return;
      const a = img[i], b = img[j];
      if (a != null && b != null) out.push([a, b]);
    });
  });
  return out;
}

/** Canvas mm `(u, v)` to the SVG writer's user units (`x = u + W/2`, `y = H/2 − v`, `viewBox="0 0 W H"`). */
export function svg_point(p: readonly number[], canvas_mm: readonly number[]): Vec2 {
  return [p[0]! + canvas_mm[0]! / 2, canvas_mm[1]! / 2 - p[1]!];
}
