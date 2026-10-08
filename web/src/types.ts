/** Shared web-side types. */

import type { Vec3 } from "castplane";

/** The camera fields `camera_matrix` reads (a validated block or the target-form block of `camera_from_orbit`). */
export interface CameraBlockLike {
  position: Vec3;
  target?: Vec3;
  yaw_deg?: number;
  pitch_deg?: number;
  roll_deg?: number;
  focal_length_mm: number;
  frame_mm: [number, number];
  shift_mm?: [number, number];
  near_m?: number;
}
