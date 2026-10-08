/**
 * The three.js camera driven by a castplane camera block (contract §5.4.10): the core's `camera_matrix` is the
 * single source of the camera, so the WebGL view and the SVG overlay are two renderings of one castplane camera.
 * `lookAt`, `updateProjectionMatrix`, `fov`, `aspect` and `filmOffset` are never used.
 */

import * as THREE from "three";

import { camera_matrix } from "castplane";
import type { CameraBlockLike } from "./types.js";

/** Set `cam3`'s world matrix and projection from a castplane camera block. */
export function apply_camera_block(cam3: THREE.PerspectiveCamera, block: CameraBlockLike, canvas_mm: readonly number[], scene_scale: number): void {
  const rec = camera_matrix(block, canvas_mm);
  const r = rec.R[0], u = rec.R[1], f = rec.forward, C = rec.C;
  // columns right', up', −forward (three cameras look down local −Z; det = +1) and translation C
  cam3.matrixAutoUpdate = false;
  cam3.matrix.set(
    r[0], u[0], -f[0], C[0],
    r[1], u[1], -f[1], C[1],
    r[2], u[2], -f[2], C[2],
    0, 0, 0, 1,
  );
  cam3.matrixWorld.copy(cam3.matrix);
  cam3.matrixWorldInverse.copy(cam3.matrixWorld).invert();
  cam3.matrixWorldNeedsUpdate = true;
  // the frustum of the frame (frame mm, shift in frame mm), built directly
  const [W, H] = block.frame_mm;
  const fl = block.focal_length_mm;
  const [u0, v0] = block.shift_mm ?? [0, 0];
  const near = block.near_m ?? 0.05;
  const left = (near * (-W / 2 - u0)) / fl;
  const right = (near * (W / 2 - u0)) / fl;
  const top = (near * (H / 2 - v0)) / fl;
  const bottom = (near * (-H / 2 - v0)) / fl;
  const far = Math.max(100, 20 * scene_scale);
  cam3.near = near;
  cam3.far = far;
  cam3.projectionMatrix.makePerspective(left, right, top, bottom, near, far);
  cam3.projectionMatrixInverse.copy(cam3.projectionMatrix).invert();
}
