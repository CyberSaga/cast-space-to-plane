/**
 * The triangle soup of a `mesh` object for the 3D view (contract §5.4.10 phase 2), without three.js or the DOM so the
 * web tests can check it. With the object's stage-A record the core's own preprocessing is reused (its `triangles`
 * over the welded world-frame vertices); only without one is `prepared_mesh` run (local frame).
 */

import { prepared_mesh } from "castplane";
import type { ObjectRecord, SceneObject, Vec3 } from "castplane";

/** `positions`: 9 floats per triangle; `world`: true when they are world coordinates (identity object matrix). */
export interface MeshPositions {
  positions: Float32Array;
  world: boolean;
}

function soup(vertices: readonly Vec3[], triangles: readonly (readonly number[])[]): Float32Array {
  const positions = new Float32Array(triangles.length * 9);
  triangles.forEach((t, k) => {
    t.forEach((v, j) => positions.set(vertices[v] as Vec3, 9 * k + 3 * j));
  });
  return positions;
}

/** The triangles of a mesh object: from its stage-A record `rec` when given (world frame, no second preprocessing),
 * else from `prepared_mesh(obj)` (local frame, placed by `transform_frame` like every primitive). */
export function mesh_positions(obj: SceneObject, rec?: ObjectRecord): MeshPositions {
  if (rec !== undefined && rec.id === obj.id && rec.triangles !== undefined) {
    return { positions: soup(rec.mesh.vertices, rec.triangles), world: true };
  }
  const prep = prepared_mesh(obj);
  return { positions: soup(prep.mesh.vertices, prep.triangles), world: false };
}
