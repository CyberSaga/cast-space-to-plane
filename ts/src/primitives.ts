/**
 * Object records: mesh in world coordinates + analytic parameters (port of `castplane/primitives.py`; spec §4, §5.6;
 * contract §2.4).
 *
 * `build_object(obj)` turns one validated `objects[i]` entry into a record with the world mesh, the point names,
 * the analytic parameters of curved primitives, the bounding box, the frame, the face tables (`face_first`,
 * `face_point_names`; the padded numpy tables are not ported, §5.4.2), the camera / light free §3.1 edge templates and
 * the vertices as canonical lists (`world_lists`, shared by reference with every document).
 */

import type { Warning } from "./errors.js";
import { box_mesh, cone_mesh, cylinder_mesh, mesh_bbox, prism_mesh, sphere_mesh, transform_mesh } from "./mesh.js";
import type { Mesh } from "./mesh.js";
import { SMOOTH_ANGLE_DEFAULT, WELD_TOLERANCE_DEFAULT, point_inside_mesh, preprocess_mesh } from "./meshprep.js";
import type { MeshInput, Triangle } from "./meshprep.js";
import type { SceneObject } from "./scene.js";
import { transform_frame } from "./transform.js";
import type { Mat3, Vec3 } from "./types.js";

export const CURVED_TYPES = ["cylinder", "sphere", "cone"] as const;

export interface Analytic {
  kind: string;
  base: Vec3;
  axis: Vec3;
  e1: Vec3;
  e2: Vec3;
  radius: number;
  height: number | null;
  centre: Vec3;
}

export interface EdgeTemplate {
  object: string;
  from: string;
  to: string;
  silhouette: boolean;
  back: boolean;
  visibility: string;
  segment: null;
  /** M5 (contract §5.2.4): mesh objects only, the camera-free `edge_smooth` flag of the edge. */
  smooth?: boolean;
}

export interface ObjectRecord {
  id: string;
  type: string;
  mesh: Mesh;
  point_names: string[];
  analytic: Analytic | null;
  bbox: [Vec3, Vec3];
  frame: [Mat3, Vec3];
  shape: SceneObject;
  face_first: number[];
  face_point_names: string[][];
  world_lists: Vec3[];
  edge_templates: EdgeTemplate[];
  /** M5 (contract §5.2.3 step 8): the per-face fallback of §5.2.5 is used (non-manifold mesh); false for primitives. */
  fallback: boolean;
  /** The `MESH_*` warnings of the preprocessing (merged into the stage-A warnings); `[]` for primitives. */
  prep_warnings: Warning[];
  /** Mesh objects only: the fan triangles of the kept (oriented) faces on the welded vertices (the original surface). */
  triangles?: Triangle[];
  /** Mesh objects only: the smoothing group of every final face. */
  smooth_groups?: number[];
  /** Mesh objects only: the §5.2.3 length scale `scale_A` (the fallback's area test, the M5 note "Fallback area test"). */
  mesh_scale_A?: number;
  [key: string]: unknown;
}

/** The preprocessed local mesh of a validated `mesh` object (contract §5.2.3): `{mesh, triangles, fallback,
 * smooth_groups, warnings, scale_A}` of `meshprep.preprocess_mesh` (`scale` applied, `transform` not). */
export interface PreparedMesh {
  mesh: Mesh;
  triangles: Triangle[];
  fallback: boolean;
  smooth_groups: number[];
  warnings: Warning[];
  scale_A: number;
}

export function prepared_mesh(obj: SceneObject): PreparedMesh {
  const [mesh, triangles, fallback, smooth_groups, warnings, scale_A] = preprocess_mesh(obj.data as MeshInput, obj.scale ?? 1.0,
    obj.weld_tolerance ?? WELD_TOLERANCE_DEFAULT, obj.smooth_angle_deg ?? SMOOTH_ANGLE_DEFAULT, obj.id, true);
  return { mesh, triangles, fallback, smooth_groups, warnings, scale_A };
}

/** Mesh of a validated object in its local frame (contract §2.1). */
export function local_mesh(obj: SceneObject): Mesh {
  switch (obj.type) {
    case "box":
      return box_mesh(obj.size as Vec3);
    case "prism":
      return prism_mesh(obj.polygon as [number, number][], obj.height as number);
    case "cylinder":
      return cylinder_mesh(obj.radius as number, obj.height as number);
    case "cone":
      return cone_mesh(obj.radius as number, obj.height as number);
    case "sphere":
      return sphere_mesh(obj.radius as number);
    case "mesh":
      return prepared_mesh(obj).mesh;
    default:
      throw new Error(`unknown object type '${obj.type}'`);
  }
}

/** `{kind, base, axis, e1, e2, radius, height, centre}` in world coordinates for curved types (contract §2.4). */
export function analytic_record(obj: SceneObject, R: Mat3, position: readonly number[]): Analytic | null {
  const typ = obj.type;
  if (!(CURVED_TYPES as readonly string[]).includes(typ)) return null;
  const base: Vec3 = [position[0] as number, position[1] as number, position[2] as number];
  const e1: Vec3 = [R[0][0], R[1][0], R[2][0]];
  const e2: Vec3 = [R[0][1], R[1][1], R[2][1]];
  const axis: Vec3 = [R[0][2], R[1][2], R[2][2]];
  const radius = obj.radius as number;
  let height: number | null;
  let centre: Vec3;
  if (typ === "sphere") {
    height = null;
    centre = [base[0] + radius * axis[0], base[1] + radius * axis[1], base[2] + radius * axis[2]];
  } else {
    height = obj.height as number;
    const h2 = 0.5 * height;
    centre = [base[0] + h2 * axis[0], base[1] + h2 * axis[1], base[2] + h2 * axis[2]];
  }
  return { kind: typ, base, axis, e1, e2, radius, height, centre };
}

/** `{face_first, face_point_names}` of a mesh (contract §5.4.2: the padded numpy tables are not ported). */
export function face_tables(mesh: Mesh, names: readonly string[]): { face_first: number[]; face_point_names: string[][] } {
  return {
    face_first: mesh.faces.map((f) => f[0] as number),
    face_point_names: mesh.faces.map((f) => f.map((v) => names[v] as string)),
  };
}

/** The object record of a validated `objects[i]` entry with the world transform applied. M5 (contract §5.2.3 step 8):
 * every record carries `fallback` / `prep_warnings` and `mesh.edge_smooth` (all false for the primitives); mesh records
 * also `triangles`, `smooth_groups` and `mesh_scale_A`, and their edge templates the camera-free `smooth` key. */
export function build_object(obj: SceneObject): ObjectRecord {
  const [R, position] = transform_frame(obj.transform);
  const prep = obj.type === "mesh" ? prepared_mesh(obj) : null;
  const mesh = transform_mesh(prep === null ? local_mesh(obj) : prep.mesh, R, position);
  const names = mesh.vertex_names.map((n) => `${obj.id}.${n}`);
  const tables = face_tables(mesh, names);
  const rec: ObjectRecord = {
    id: obj.id,
    type: obj.type,
    mesh,
    point_names: names,
    analytic: analytic_record(obj, R, position),
    bbox: mesh_bbox(mesh),
    frame: [R, position],
    shape: obj,
    face_first: tables.face_first,
    face_point_names: tables.face_point_names,
    world_lists: mesh.vertices.map((v) => [v[0] + 0, v[1] + 0, v[2] + 0] as Vec3),
    edge_templates: mesh.edges.map(([i, j]) => ({
      object: obj.id, from: names[i] as string, to: names[j] as string, silhouette: false, back: false,
      visibility: "visible", segment: null,
    })),
    fallback: false,
    prep_warnings: [],
  };
  if (prep === null) {
    mesh.edge_smooth = mesh.edges.map(() => false);
  } else {
    if (mesh.faces.length === 0) throw new Error("a validated mesh object keeps at least one face (usable-face guard)");
    rec.triangles = prep.triangles;
    rec.fallback = prep.fallback;
    rec.smooth_groups = [...prep.smooth_groups];
    rec.prep_warnings = [...prep.warnings];
    rec.mesh_scale_A = prep.scale_A;
    const smooth = mesh.edge_smooth as boolean[];
    rec.edge_templates.forEach((t, e) => {
      t.smooth = smooth[e] as boolean;
    });
  }
  return rec;
}

function point_in_polygon_margin(x: number, y: number, poly: readonly (readonly number[])[], margin: number): boolean {
  let inside = false;
  const n = poly.length;
  for (let i = 0; i < n; i++) {
    const p0 = poly[i] as readonly number[], p1 = poly[(i + 1) % n] as readonly number[];
    const x0 = p0[0] as number, y0 = p0[1] as number, x1 = p1[0] as number, y1 = p1[1] as number;
    const dx = x1 - x0, dy = y1 - y0;
    let t = ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy);
    t = t < 0.0 ? 0.0 : t > 1.0 ? 1.0 : t;
    if (Math.hypot(x - (x0 + t * dx), y - (y0 + t * dy)) <= margin) return false;
    if ((y0 > y) !== (y1 > y) && x < x0 + (y - y0) * dx / dy) inside = !inside;
  }
  return inside;
}

/** True when the world point `x` lies strictly inside a polyhedral object (box or prism) by more than `tol`
 * (contract §2.5 / §2.9 `LIGHT_INSIDE_OBJECT`); always false for curved objects. */
export function point_inside_solid(rec: ObjectRecord, x: readonly number[], tol = 0.0): boolean {
  if (rec.analytic !== null) return false;
  if (rec.type === "mesh") {
    // contract §5.2.3 step 8: generalised winding number of the original surface; a fallback mesh has no inside
    if (rec.fallback) return false;
    return point_inside_mesh(rec.mesh.vertices, rec.triangles ?? [], x, tol);
  }
  const [R, position] = rec.frame;
  const d0 = (x[0] as number) - position[0], d1 = (x[1] as number) - position[1], d2 = (x[2] as number) - position[2];
  // R^T · d
  const local: Vec3 = [
    R[0][0] * d0 + R[1][0] * d1 + R[2][0] * d2,
    R[0][1] * d0 + R[1][1] * d1 + R[2][1] * d2,
    R[0][2] * d0 + R[1][2] * d1 + R[2][2] * d2,
  ];
  const shape = rec.shape;
  if (rec.type === "box") {
    const [sx, sy, sz] = shape.size as Vec3;
    return Math.abs(local[0]) < sx / 2 - tol && Math.abs(local[1]) < sy / 2 - tol && tol < local[2] && local[2] < sz - tol;
  }
  if (rec.type === "prism") {
    if (!(tol < local[2] && local[2] < (shape.height as number) - tol)) return false;
    return point_in_polygon_margin(local[0], local[1], shape.polygon as [number, number][], tol);
  }
  return false;
}
