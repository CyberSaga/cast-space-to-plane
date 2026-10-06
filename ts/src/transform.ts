/**
 * Object transforms: Euler Z-Y-X rotation and translation (port of `castplane/transform.py`; spec §4; contract §2.1).
 *
 * `rotation_deg = [rx, ry, rz]` gives `R = Rz(rz) · Ry(ry) · Rx(rx)` applied to local coordinates,
 * `world = R · local + position`.
 */

import type { Mat3, Vec3 } from "./types.js";

/** `math.radians` (CPython multiplies by the double `pi / 180`). */
export function radians(deg: number): number {
  return deg * (Math.PI / 180);
}

/** `math.degrees` (CPython multiplies by the double `180 / pi`). */
export function degrees(rad: number): number {
  return rad * (180 / Math.PI);
}

/** 3×3 product with every entry a left-to-right 3-term sum in `k` order (contract §5.4.4 (2)). */
export function matmul3(A: readonly (readonly number[])[], B: readonly (readonly number[])[]): Mat3 {
  const out = [[0, 0, 0], [0, 0, 0], [0, 0, 0]] as Mat3;
  for (let i = 0; i < 3; i++) {
    const a = A[i] as readonly number[];
    for (let j = 0; j < 3; j++) {
      out[i][j] = (a[0] as number) * ((B[0] as readonly number[])[j] as number)
        + (a[1] as number) * ((B[1] as readonly number[])[j] as number)
        + (a[2] as number) * ((B[2] as readonly number[])[j] as number);
    }
  }
  return out;
}

/** Right-handed rotation about +X by `deg` degrees. */
export function rotation_x(deg: number): Mat3 {
  const c = Math.cos(radians(deg)), s = Math.sin(radians(deg));
  return [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]];
}

/** Right-handed rotation about +Y by `deg` degrees. */
export function rotation_y(deg: number): Mat3 {
  const c = Math.cos(radians(deg)), s = Math.sin(radians(deg));
  return [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]];
}

/** Right-handed rotation about +Z by `deg` degrees. */
export function rotation_z(deg: number): Mat3 {
  const c = Math.cos(radians(deg)), s = Math.sin(radians(deg));
  return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]];
}

/** `R = Rz(rz) · Ry(ry) · Rx(rx)` for `rotation_deg = [rx, ry, rz]`. */
export function euler_zyx_matrix(rotation_deg: readonly number[]): Mat3 {
  const rx = rotation_deg[0] as number, ry = rotation_deg[1] as number, rz = rotation_deg[2] as number;
  return matmul3(matmul3(rotation_z(rz), rotation_y(ry)), rotation_x(rx));
}

export interface TransformLike {
  position?: readonly number[];
  rotation_deg?: readonly number[];
}

/** `[R, position]` of a validated transform. */
export function transform_frame(transform: TransformLike | null | undefined): [Mat3, Vec3] {
  const t = transform ?? {};
  const R = euler_zyx_matrix(t.rotation_deg ?? [0.0, 0.0, 0.0]);
  const p = t.position ?? [0.0, 0.0, 0.0];
  return [R, [p[0] as number, p[1] as number, p[2] as number]];
}

/** `R · v` (row dot products in `k` order). */
export function rotate(R: Mat3, v: readonly number[]): Vec3 {
  const x = v[0] as number, y = v[1] as number, z = v[2] as number;
  return [
    R[0][0] * x + R[0][1] * y + R[0][2] * z,
    R[1][0] * x + R[1][1] * y + R[1][2] * z,
    R[2][0] * x + R[2][1] * y + R[2][2] * z,
  ];
}

/** `R · v + position`. */
export function rigid(R: Mat3, position: readonly number[], v: readonly number[]): Vec3 {
  const r = rotate(R, v);
  return [r[0] + (position[0] as number), r[1] + (position[1] as number), r[2] + (position[2] as number)];
}

/** `world = R · local + position` for a list of local points. */
export function apply_transform(points: readonly (readonly number[])[], transform: TransformLike | null | undefined): Vec3[] {
  const [R, position] = transform_frame(transform);
  return points.map((p) => rigid(R, position, p));
}

/** `R · v` for a list of local directions / normals (no translation). */
export function apply_rotation(vectors: readonly (readonly number[])[], transform: TransformLike | null | undefined): Vec3[] {
  const [R] = transform_frame(transform);
  return vectors.map((v) => rotate(R, v));
}
