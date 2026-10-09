/**
 * The data of the 3D view's receivers and light helpers (contract §5.4.10 phase 2), without three.js or the DOM so
 * the web tests can check it: a bounded receiver is drawn as a plate over its `bounds` (a triangle fan of the convex
 * polygon the core validated, world coordinates) with an outline; the unbounded ground stays the large plane with a
 * grid (`scene3d.ts`); every light gets its own helper colour, and the shading lights share one total intensity so a
 * scene with several lights is not drawn brighter. Display only: none of this is geometric output.
 */

import type { Receiver, Vec3 } from "castplane";

/** Helper colours, one per light in `scene.lights` order (cycled); the first is the single-light colour of phase 1. */
export const LIGHT_COLOURS: readonly number[] = [0xffcc33, 0x3fa7ff, 0xff6f61, 0x8e6cff, 0x2fbf71, 0xff9f1c];

/** Total intensity of the three.js shading lights (one light: phase 1's 2.2). */
export const SHADING_TOTAL = 2.2;

/** The helper colour of the light at `index` of `scene.lights`. */
export function light_colour(index: number): number {
  return LIGHT_COLOURS[index % LIGHT_COLOURS.length]!;
}

/** The shading intensity of each of `n` lights (`SHADING_TOTAL / n`). */
export function shading_intensity(n: number): number {
  return SHADING_TOTAL / Math.max(1, n);
}

/** A receiver of the 3D view: `ground` (unbounded, drawn as a large plane with a grid) or `plate` (its `bounds`). */
export interface ReceiverPlate {
  id: string;
  kind: "ground" | "plate";
  /** `plate`: 9 floats per triangle (a fan from `bounds[0]`); `ground`: empty. */
  positions: Float32Array;
  /** `plate`: the closed outline, `bounds` followed by `bounds[0]` (3 floats per point); `ground`: empty. */
  outline: Float32Array;
}

/** The fan triangles of a convex polygon (`n − 2` triangles, `bounds[0]` shared), 9 floats per triangle. */
export function plate_positions(bounds: readonly Vec3[]): Float32Array {
  const n = bounds.length;
  const out = new Float32Array(Math.max(0, n - 2) * 9);
  for (let k = 1; k + 1 < n; k++) {
    out.set(bounds[0]!, 9 * (k - 1));
    out.set(bounds[k]!, 9 * (k - 1) + 3);
    out.set(bounds[k + 1]!, 9 * (k - 1) + 6);
  }
  return out;
}

/** The closed outline of a polygon: its vertices and the first again (3 floats per point). */
export function plate_outline(bounds: readonly Vec3[]): Float32Array {
  const out = new Float32Array((bounds.length + (bounds.length > 0 ? 1 : 0)) * 3);
  bounds.forEach((p, k) => out.set(p, 3 * k));
  if (bounds.length > 0) out.set(bounds[0]!, 3 * bounds.length);
  return out;
}

/** The receivers of a scene for the 3D view, in `scene.receivers` order. */
export function receiver_plates(receivers: readonly Receiver[]): ReceiverPlate[] {
  return receivers.map((r) =>
    r.bounds === null
      ? { id: r.id, kind: "ground", positions: new Float32Array(0), outline: new Float32Array(0) }
      : { id: r.id, kind: "plate", positions: plate_positions(r.bounds), outline: plate_outline(r.bounds) },
  );
}

/** `userData` keys that tag the 3D group's children by role (`scene3d.ts`). An id may contain any character but '.',
 * so a child's `name` cannot tell an object `crate:1` from a receiver's `receiver:<id>`. */
export const OBJECT_ID_KEY = "castplane_object_id";
export const RECEIVER_ID_KEY = "castplane_receiver_id";

/** The node shape {@link object_id_of} reads (a three.js `Object3D`). */
export interface TaggedNode {
  userData: Record<string, unknown>;
  parent: TaggedNode | null;
}

/** The scene object id of `hit` or of its nearest tagged ancestor below `group` (object picking, §5.7.8 item 10);
 * null for anything else (lights, receivers, outlines, grids). */
export function object_id_of(hit: TaggedNode, group: TaggedNode): string | null {
  for (let o: TaggedNode | null = hit; o !== null && o !== group; o = o.parent) {
    const id = o.userData[OBJECT_ID_KEY];
    if (typeof id === "string") return id;
  }
  return null;
}
