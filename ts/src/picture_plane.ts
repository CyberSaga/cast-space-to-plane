/**
 * The `picture_plane` camera form (M10; port of `castplane/picture_plane.py`; spec-v0.2 §4.1, §4.3; contract §5.7).
 *
 * A camera block may give `position` (the eye `E`) plus `picture_plane = {normal, offset, up?}` instead of a `target`
 * or `yaw_deg` / `pitch_deg`. The plane is `n·X + offset = 0`; validation (`scene.validate_picture_plane`) keeps it as
 * given. `resolve_picture_plane` normalises it exactly once (`n̂ = n/|n|`, `off̂ = offset/|n|`, `|n|` summed left to
 * right) and resolves it, before stage B, into an ordinary `target`-form block:
 *
 *     s = n̂·E + off̂,   D = |s|,   f = −sign(s) n̂,   Q = E − s n̂,   target = E + f
 *
 * The camera's forward row is `f` itself (bit for bit), so the default up of `camera_matrix` (world z, or +y when
 * `|f × z| ≤ 1e-9`) is decided on `f`; `roll_deg` is the signed angle from that default up to the given `up` (exactly 0
 * without `up`). The form never emits `CAMERA_LOOKING_ALONG_UP`. Every scalar expression is written left to right as
 * in the Python reference.
 */

import { default_basis } from "./camera.js";
import type { CameraBlock, CameraRecord } from "./camera.js";
import { py_fixed } from "./pyfloat.js";
import { degrees } from "./transform.js";
import type { Vec2, Vec3 } from "./types.js";

/** `||n_i| − 1| < AXIS_TOL` marks a unit normal parallel to coordinate axis `i` (spec-v0.2 §4.3). */
export const AXIS_TOL = 1e-9;
/** `|n_i| < DROP_TOL` is not printed; the first printed coefficient is made positive. */
export const DROP_TOL = 5e-4;

/** `info` of `resolve_picture_plane`: the plane with its normal pointing from the eye to the plane. */
export interface PicturePlaneInfo {
  normal: Vec3;
  offset: number;
  distance: number;
  foot: Vec3;
}

/** The `camera.picture_plane` block of the geometry document (spec-v0.2 §4.1, appendix A.3; contract §5.7.4). */
export interface PicturePlaneRecord {
  normal: Vec3;
  offset: number;
  up: Vec3;
  distance: number;
  foot: Vec3;
  frame_m: Vec2;
  equation: string;
}

/**
 * `[target_cam, roll_deg, info]` of a validated `picture_plane` camera (spec-v0.2 §4.1). `target_cam` is a validated
 * `target`-form block (`position`, `target = E + f`, `roll_deg` and the lens keys); `info = {normal: f, offset: −f·Q,
 * distance: D, foot: Q}`. `f` is also the camera's forward row (`camera_matrix` uses `info.normal`).
 */
export function resolve_picture_plane(cam: CameraBlock): [CameraBlock, number, PicturePlaneInfo] {
  const pp = cam.picture_plane;
  if (pp === undefined) throw new TypeError("resolve_picture_plane: not a picture_plane camera block");
  const n0 = pp.normal;
  const nn = Math.sqrt(n0[0] * n0[0] + n0[1] * n0[1] + n0[2] * n0[2]); // the single normalisation of the plane
  const n: Vec3 = [n0[0] / nn, n0[1] / nn, n0[2] / nn];
  const off = pp.offset / nn;
  const E: Vec3 = [cam.position[0], cam.position[1], cam.position[2]];
  const s = n[0] * E[0] + n[1] * E[1] + n[2] * E[2] + off;
  const D = Math.abs(s);
  let f: Vec3, offset: number;
  if (s > 0.0) {
    f = [-n[0] + 0.0, -n[1] + 0.0, -n[2] + 0.0];
    offset = -off + 0.0;
  } else {
    f = [n[0] + 0.0, n[1] + 0.0, n[2] + 0.0];
    offset = off + 0.0;
  }
  const Q: Vec3 = [E[0] - s * n[0] + 0.0, E[1] - s * n[1] + 0.0, E[2] - s * n[2] + 0.0];
  const target: Vec3 = [E[0] + f[0], E[1] + f[1], E[2] + f[2]];
  const tcam: CameraBlock = {
    position: E, target, roll_deg: 0.0, focal_length_mm: cam.focal_length_mm, frame_mm: cam.frame_mm,
  };
  if (cam.shift_mm !== undefined) tcam.shift_mm = cam.shift_mm;
  if (cam.near_m !== undefined) tcam.near_m = cam.near_m;
  let roll = 0.0;
  if (pp.up !== undefined) {
    const up = pp.up;
    const [right0, up0] = default_basis(f);
    const sin_r = -(up[0] * right0[0] + up[1] * right0[1] + up[2] * right0[2]);
    const cos_r = up[0] * up0[0] + up[1] * up0[1] + up[2] * up0[2];
    roll = degrees(Math.atan2(sin_r, cos_r)) + 0.0;
    tcam.roll_deg = roll;
  }
  return [tcam, roll, { normal: f, offset, distance: D, foot: Q }];
}

/**
 * The `camera.picture_plane` block of the geometry document: `{normal, offset, up, distance, foot, frame_m, equation}`;
 * `up` is the camera's final up row `R[1]`, `frame_m = [frame_w·D/focal, frame_h·D/focal]` (metres on the plane).
 */
export function picture_plane_document(info: PicturePlaneInfo, rec: Pick<CameraRecord, "frame_mm" | "R">,
  focal_length_mm: number): PicturePlaneRecord {
  const D = info.distance;
  const focal = focal_length_mm;
  const frame = rec.frame_mm;
  const up = rec.R[1];
  return {
    normal: [...info.normal] as Vec3,
    offset: info.offset,
    up: [up[0] + 0.0, up[1] + 0.0, up[2] + 0.0],
    distance: D,
    foot: [...info.foot] as Vec3,
    frame_m: [frame[0] * D / focal + 0.0, frame[1] * D / focal + 0.0],
    equation: plane_equation(info.normal, info.offset),
  };
}

/** `x` with `decimals` decimals (Python's exact round-half-even of the binary value); a result that reads as negative
 * zero (`-0.00`) loses its sign (Python `picture_plane._fixed`). */
export function fixed(x: number, decimals: number): string {
  let t = py_fixed(x, decimals);
  if (t[0] === "-" && /^[-0.]*$/.test(t)) t = t.slice(1);
  return t;
}

const AXES = "xyz";

/**
 * Human-readable equation of the plane `normal·X + offset = 0` (spec-v0.2 §4.3; contract §5.7.5). The normal is
 * normalised first (`n̂ = n/|n|`, constant `c = −offset/|n|`). A normal with `||n̂_i| − 1| < 1e-9` is axis `i`:
 * `"y = 2.00"` (the positive axis, value `sign(n̂_i)·c`, two decimals). Otherwise coefficients with `|n̂_i| < 5e-4` are
 * dropped, the first printed one is made positive and the rest printed with three decimals:
 * `"0.707x - 0.707y = 1.200"`.
 */
export function plane_equation(normal: readonly number[], offset: number): string {
  const n0 = normal as readonly [number, number, number];
  const nn = Math.sqrt(n0[0] * n0[0] + n0[1] * n0[1] + n0[2] * n0[2]);
  let n: Vec3 = [n0[0] / nn, n0[1] / nn, n0[2] / nn];
  let c = -offset / nn;
  for (let i = 0; i < 3; i++) {
    if (Math.abs(Math.abs(n[i] as number) - 1.0) < AXIS_TOL) {
      const sg = (n[i] as number) > 0.0 ? 1.0 : -1.0;
      return `${AXES[i]} = ${fixed(sg * c, 2)}`;
    }
  }
  const first = n.findIndex((v) => Math.abs(v) >= DROP_TOL);
  if (first >= 0 && (n[first] as number) < 0.0) {
    n = [-n[0], -n[1], -n[2]];
    c = -c;
  }
  let out = "";
  for (let i = 0; i < 3; i++) {
    const v = n[i] as number;
    if (Math.abs(v) < DROP_TOL) continue;
    const term = `${py_fixed(Math.abs(v), 3)}${AXES[i]}`;
    if (!out) out = (v < 0.0 ? "-" : "") + term;
    else out += (v < 0.0 ? " - " : " + ") + term;
  }
  return `${out} = ${fixed(c, 3)}`;
}

/**
 * Canvas point(s) `(u, v)` (mm) -> world point(s) on the picture plane at distance `D` (spec-v0.2 §4.3):
 * `X = E + D·((a·r' + b·u') + f)` with `a = (u − u0)/(focal·s)`, `b = (v − v0)/(focal·s)`, `r'`, `u'`, `f` the rows of
 * `rec.R`, `focal·s = rec.K[0][0]`, `E = rec.C`. One `[u, v]` gives one point, a list of them a list.
 */
export function unproject_to_plane(rec: Pick<CameraRecord, "K" | "R" | "C" | "u0" | "v0">, uv: readonly number[], D: number): Vec3;
export function unproject_to_plane(rec: Pick<CameraRecord, "K" | "R" | "C" | "u0" | "v0">, uv: readonly (readonly number[])[], D: number): Vec3[];
export function unproject_to_plane(rec: Pick<CameraRecord, "K" | "R" | "C" | "u0" | "v0">,
  uv: readonly number[] | readonly (readonly number[])[], D: number): Vec3 | Vec3[] {
  if (typeof uv[0] !== "number") return (uv as readonly (readonly number[])[]).map((p) => unproject_to_plane(rec, p, D));
  const p = uv as readonly number[];
  const fs = rec.K[0][0];
  const [r, u, f] = rec.R;
  const C = rec.C;
  const a = ((p[0] as number) - rec.u0) / fs;
  const b = ((p[1] as number) - rec.v0) / fs;
  return [
    C[0] + D * (a * r[0] + b * u[0] + f[0]),
    C[1] + D * (a * r[1] + b * u[1] + f[1]),
    C[2] + D * (a * r[2] + b * u[2] + f[2]),
  ];
}
