/**
 * Orbit camera state of the web UI (contract §5.4.10) — pure, DOM-free, unit-tested (`web/test/orbit.test.ts`).
 *
 * The UI never edits a castplane camera block directly: pointer events change an {@link OrbitState}, and every
 * frame builds the block with {@link camera_from_orbit}, explicitly in target form from the lens fields (never
 * `{...base, …}`: a yaw/pitch `base` would carry `yaw_deg` + `target` and `validate_camera` would reject it,
 * §5.4.3). `frame_mm` is fixed by the scene (its aspect is tied to `canvas_mm`); `shift_mm` and `near_m` are not
 * editable in M7.
 */

import { camera_forward, camera_matrix } from "castplane";
import type { Camera, Scene, Vec3 } from "castplane";

export interface OrbitState {
  target: Vec3;
  distance: number;
  yaw_deg: number;
  pitch_deg: number;
  roll_deg: number;
  focal_length_mm: number;
}

/** The lens fields a produced block copies from the scene camera. */
export type LensBase = Pick<Camera, "frame_mm" | "shift_mm" | "near_m">;

/** The explicit target-form camera block of a frame. */
export interface TargetCamera {
  position: Vec3;
  target: Vec3;
  roll_deg: number;
  focal_length_mm: number;
  frame_mm: [number, number];
  shift_mm: [number, number];
  near_m: number;
}

export const PITCH_LIMIT_DEG = 89.5;
export const DISTANCE_MIN = 0.05;
export const DISTANCE_MAX = 1e4;
export const FOCAL_MIN_MM = 8;
export const FOCAL_MAX_MM = 400;
export const ROLL_LIMIT_DEG = 180;
/** Distance used when a yaw/pitch camera's view axis never meets the ground (`forward_z ≥ −1e-9`). */
export const DEFAULT_DISTANCE = 5;
export const ZOOM_RATE = 0.001;

const DEG = 180 / Math.PI;

function clamp(x: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, x));
}

/** The §2.2 yaw/pitch forward vector: `(−sin yaw · cos pitch, cos yaw · cos pitch, sin pitch)`. */
export function forward_from_angles(yaw_deg: number, pitch_deg: number): Vec3 {
  const yaw = yaw_deg / DEG, pitch = pitch_deg / DEG;
  return [-Math.sin(yaw) * Math.cos(pitch), Math.cos(yaw) * Math.cos(pitch), Math.sin(pitch)];
}

/**
 * The orbit state of a validated camera block. Target form: `target = cam.target`, `distance = |target − position|`.
 * Yaw/pitch form: `distance = −position_z / forward_z` when `forward_z < −1e-9` (where the view axis meets the
 * ground), else {@link DEFAULT_DISTANCE}, and `target = position + distance·forward`. In both forms
 * `pitch_deg = degrees(asin(f_z))`, `yaw_deg = degrees(atan2(−f_x, f_y))` (the inverse of §2.2's formula).
 * `_scene` is accepted for the phase-2 receivers (the ground is `z = 0` in phase 1).
 */
export function orbit_from_camera(cam: Camera, _scene?: Scene): OrbitState {
  const f = camera_forward(cam);
  const p = cam.position;
  let target: Vec3, distance: number;
  if (cam.target !== undefined) {
    target = [cam.target[0], cam.target[1], cam.target[2]];
    const d: Vec3 = [target[0] - p[0], target[1] - p[1], target[2] - p[2]];
    distance = Math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
  } else {
    distance = f[2] < -1e-9 ? -p[2] / f[2] : DEFAULT_DISTANCE;
    target = [p[0] + distance * f[0], p[1] + distance * f[1], p[2] + distance * f[2]];
  }
  return {
    target,
    distance,
    yaw_deg: Math.atan2(-f[0], f[1]) * DEG,
    pitch_deg: Math.asin(clamp(f[2], -1, 1)) * DEG,
    roll_deg: cam.roll_deg ?? 0,
    focal_length_mm: cam.focal_length_mm,
  };
}

/** The camera block of a frame: target form, lens fields copied explicitly from `base`. */
export function camera_from_orbit(state: OrbitState, base: LensBase): TargetCamera {
  const f = forward_from_angles(state.yaw_deg, state.pitch_deg);
  const t = state.target, d = state.distance;
  return {
    position: [t[0] - d * f[0], t[1] - d * f[1], t[2] - d * f[2]],
    target: [t[0], t[1], t[2]],
    roll_deg: state.roll_deg,
    focal_length_mm: state.focal_length_mm,
    frame_mm: [base.frame_mm[0], base.frame_mm[1]],
    shift_mm: [base.shift_mm[0], base.shift_mm[1]],
    near_m: base.near_m,
  };
}

/**
 * Left drag: `yaw_deg −= dx·(180 / H_px)`, `pitch_deg −= dy·(180 / H_px)` clamped to ±{@link PITCH_LIMIT_DEG}
 * (`dy` is the DOM delta, positive downwards: dragging down lifts the camera like OrbitControls; the §5.4.10
 * `+=` sign is recorded as a deviation in docs/ARCHITECTURE.md §5.4).
 */
export function rotate_orbit(state: OrbitState, dx: number, dy: number, H_px: number): OrbitState {
  const k = 180 / H_px;
  return { ...state, yaw_deg: state.yaw_deg - dx * k, pitch_deg: clamp(state.pitch_deg - dy * k, -PITCH_LIMIT_DEG, PITCH_LIMIT_DEG) };
}

/**
 * Right drag or Shift + drag: `target += (−dx·k)·right' + (dy·k)·up'` with `k = distance·(frame_mm[1] / f) / H_px`
 * (metres per pixel at the target depth); `right'`, `up'` are the first two rows of the core's `camera_matrix`.
 */
export function pan_orbit(state: OrbitState, dx: number, dy: number, H_px: number, base: LensBase, canvas_mm: readonly number[]): OrbitState {
  const k = (state.distance * (base.frame_mm[1] / state.focal_length_mm)) / H_px;
  const rec = camera_matrix(camera_from_orbit(state, base), canvas_mm);
  const r = rec.R[0], u = rec.R[1], t = state.target;
  const a = -dx * k, b = dy * k;
  return { ...state, target: [t[0] + a * r[0] + b * u[0], t[1] + a * r[1] + b * u[1], t[2] + a * r[2] + b * u[2]] };
}

/** Wheel: `distance *= exp(0.001·deltaY)` clamped to `[0.05, 1e4]`. */
export function zoom_orbit(state: OrbitState, deltaY: number): OrbitState {
  return { ...state, distance: clamp(state.distance * Math.exp(ZOOM_RATE * deltaY), DISTANCE_MIN, DISTANCE_MAX) };
}

/** Roll slider `[−180, 180]`. */
export function set_roll(state: OrbitState, roll_deg: number): OrbitState {
  return { ...state, roll_deg: clamp(roll_deg, -ROLL_LIMIT_DEG, ROLL_LIMIT_DEG) };
}

/** Focal-length slider `[8, 400] mm`. */
export function set_focal(state: OrbitState, focal_length_mm: number): OrbitState {
  return { ...state, focal_length_mm: clamp(focal_length_mm, FOCAL_MIN_MM, FOCAL_MAX_MM) };
}

/** Logarithmic focal slider: position `t ∈ [0, 1]` → `8·(400/8)^t` mm. */
export function focal_from_slider(t: number): number {
  return FOCAL_MIN_MM * Math.pow(FOCAL_MAX_MM / FOCAL_MIN_MM, clamp(t, 0, 1));
}

/** Inverse of {@link focal_from_slider} (clamped to the slider range). */
export function slider_from_focal(focal_length_mm: number): number {
  return Math.log(clamp(focal_length_mm, FOCAL_MIN_MM, FOCAL_MAX_MM) / FOCAL_MIN_MM) / Math.log(FOCAL_MAX_MM / FOCAL_MIN_MM);
}
