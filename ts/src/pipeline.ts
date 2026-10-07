/**
 * Three-stage pipeline (port of `castplane/pipeline.py`; spec §3; contract §3, §5.4.7).
 *
 * - Stage A `shadow_geometry(scene)`: camera independent; never reads `scene.camera`.
 * - Stage B `project_scene(scene, A, camera?)`: camera matrices and every projected point / clipped segment /
 *   polygon in homogeneous 2-D form, `L'`, `F'`, the 2-D construction rays and the self-check. Scalar semantics of
 *   every record (contract §5.4.4 (6)); never mutates `A`.
 * - Stage C `compose(scene, B)`: the spec §6.2 document (division by `x̃3` last). Camera-free lists are shared by
 *   reference with `A`; a document is read-only data.
 * - `render(scene, camera?)` runs all three and writes the SVG.
 */

import {
  camera_matrix, clip_polygon_near, clip_polygon_rect_h, clip_segment_near, clip_segment_rect_h, divide, horizon as camera_horizon,
  nu, project,
} from "./camera.js";
import type { CameraBlock, CameraRecord, Horizon } from "./camera.js";
import { ellipse_arc_params, ellipse_params, sample_arc, sample_count } from "./conics.js";
import { clip_segments_uv, coincidence_check, covering_segments, extended_segments, self_check, special_point_image } from "./construction.js";
import type { SpecialPointImage } from "./construction.js";
import { stage_a_object, stage_b_objects } from "./curved.js";
import type { ArcRecord, CurvedData, CurvedStageB, LoopEntry, ShadowRecord } from "./curved.js";
import type { GeometryDocument } from "./document.js";
import { SceneError, make_warning, merge_warnings } from "./errors.js";
import type { Warning } from "./errors.js";
import { TOL_DIR, row_max_abs, scene_scale, tolerance } from "./homogeneous.js";
import { face_lit_flags, light_vector, lit_value, silhouette_loops } from "./light.js";
import { NotManifoldError } from "./mesh.js";
import type { Mesh } from "./mesh.js";
import { canonical } from "./output/geometry_json.js";
import { write_svg } from "./output/svg.js";
import { build_object, point_inside_solid } from "./primitives.js";
import type { EdgeTemplate, ObjectRecord } from "./primitives.js";
import { validate_camera } from "./scene.js";
import type { Light, Receiver, Scene } from "./scene.js";
import { clip_mesh_to_plane, foot, mat4_vec, shadow_loop, shadow_matrix, shadow_w } from "./shadow.js";
import type { Origin, Source, VertexTag } from "./shadow.js";
import { degrees } from "./transform.js";
import type { Mat4, Vec2, Vec3, Vec4 } from "./types.js";

// ---------------------------------------------------------------------------
// records
// ---------------------------------------------------------------------------

export interface LightRecord {
  id: string;
  type: string;
  L: Vec4;
  M: Mat4;
  F: Vec4;
  F_defined: boolean;
  pi_L: number;
  active: boolean;
  tol_w: number;
  tol_lit: number;
  warnings: Warning[];
}

export interface ObjectLightData {
  lit: boolean[];
  parallel: boolean[];
  light_inside: boolean;
  edge_silhouette: boolean[];
  silhouette_vertices: number[];
  loops: number[][];
  /** Vertex index lists of the unlit faces (form shadow, §6.1 "陰"). */
  form_idx: number[][];
  /** The same faces as point-name lists (shared with every document). */
  form_faces: string[][];
}

export interface StageAObject extends ObjectRecord {
  lights: Map<string, ObjectLightData>;
  ground_mesh?: [Mesh, Origin[]] | null;
  curved?: Map<string, CurvedData>;
}

export interface StageA {
  objects: StageAObject[];
  vertices: Vec3[];
  bbox: [Vec3, Vec3];
  scene_scale: number;
  tol: number;
  receiver: { id: string; pi: Vec4 };
  lights: LightRecord[];
  shadows: StageAShadow[];
  warnings: Warning[];
}

/** A stage-A shadow record with its camera-free point lists (contract §5.4.7: shared by reference with stage B). */
export type StageAShadow = ShadowRecord & { S_lists: Vec3[]; Q_lists: Vec3[]; G_lists: Vec3[] };

export interface PolyStageB {
  id: string;
  type: string;
  analytic: false;
  point_names: string[];
  world: Vec3[];
  world_lists: Vec3[];
  image_h: Vec3[];
  depth: number[];
  behind: boolean[];
  edges: [number, number][];
  edge_templates: EdgeTemplate[];
  back: boolean[];
  silhouette: boolean[];
  segments_h: ([Vec3, Vec3] | null)[];
  segment_keep: boolean[];
  form_faces: string[][];
  form_polygons: Vec2[][];
}

export interface LightStageB {
  id: string;
  type: string;
  active: boolean;
  L: Vec4;
  F: Vec4;
  F_defined: boolean;
  light_point: SpecialPointImage;
  shadow_vp: SpecialPointImage;
  L_depth: number | null;
  F_depth: number | null;
}

export interface RaySegment {
  kind: string;
  point: string;
  points: [Vec2, Vec2];
}

export interface Check {
  point: string;
  max_error_mm: number;
}

export interface ShadowStageB {
  light: string;
  receiver: string;
  object: string;
  keep: boolean[];
  shadow_names: string[];
  foot_names: string[];
  S_world: Vec3[];
  S_h: Vec3[];
  S_behind: boolean[];
  Q_world: Vec3[];
  Q_h: Vec3[];
  Q_behind: boolean[];
  ground_names: string[];
  G_world: Vec3[];
  G_h: Vec3[];
  G_behind: boolean[];
  S_lists: Vec3[];
  Q_lists: Vec3[];
  G_lists: Vec3[];
  loops: LoopEntry[][];
  polygons: Vec2[][];
  unbounded: boolean;
  rays: [string, string][];
  segments: RaySegment[];
  checks: Check[];
}

export interface ConstructionStageB {
  light_point: Vec2 | null;
  light_point_at_infinity: Vec2 | null;
  shadow_vp: Vec2 | null;
  shadow_vp_at_infinity: Vec2 | null;
  rays: [string, string][];
  checks: Check[];
  segments: RaySegment[];
}

export interface StageB {
  camera: CameraRecord;
  scene_scale: number;
  tol: number;
  objects: (PolyStageB | CurvedStageB)[];
  lights: LightStageB[];
  horizon: Horizon;
  shadows: ShadowStageB[];
  construction: ConstructionStageB | null;
  warnings: Warning[];
  A: StageA;
}

// ---------------------------------------------------------------------------
// stage A
// ---------------------------------------------------------------------------

function dot4(a: readonly number[], b: readonly number[]): number {
  return (a[0] as number) * (b[0] as number) + (a[1] as number) * (b[1] as number)
    + (a[2] as number) * (b[2] as number) + (a[3] as number) * (b[3] as number);
}

function h4(v: readonly number[]): Vec4 {
  return [v[0] as number, v[1] as number, v[2] as number, 1.0];
}

function receiver_plane(receiver: Receiver): Vec4 {
  const n = receiver.normal;
  return [n[0], n[1], n[2], receiver.offset];
}

function light_record(light: Light, pi: Vec4, tol: number): LightRecord {
  const L = light_vector(light);
  const pi_L = dot4(pi, L);
  const warnings: Warning[] = [];
  let active = true;
  let tol_w: number;
  if (light.type === "point") {
    tol_w = tol;
    if (pi_L <= tol) {
      warnings.push(make_warning("LIGHT_BELOW_RECEIVER", [light.id]));
      active = false;
    }
  } else {
    tol_w = TOL_DIR;
    if (Math.abs(pi_L) <= TOL_DIR) {
      warnings.push(make_warning("DIRECTIONAL_HORIZONTAL", [light.id]));
      active = false;
    } else if (pi_L < -TOL_DIR) {
      warnings.push(make_warning("LIGHT_BELOW_RECEIVER", [light.id]));
      active = false;
    }
  }
  const F = foot(pi, L);
  const F_defined = light.type === "point" || row_max_abs(F) > TOL_DIR;
  return { id: light.id, type: light.type, L, M: shadow_matrix(pi, L), F, F_defined, pi_L, active, tol_w, tol_lit: tol_w, warnings };
}

function object_light_data(obj: StageAObject, lt: LightRecord): [ObjectLightData, Warning[]] {
  const mesh = obj.mesh;
  let { lit, parallel } = face_lit_flags(mesh, lt.L, lt.tol_lit);
  const warnings: Warning[] = [];
  const inside = lt.type === "point" && point_inside_solid(obj, lt.L, lt.tol_lit);
  if (inside) {
    lit = lit.map(() => false);
    parallel = parallel.map(() => false);
    warnings.push(make_warning("LIGHT_INSIDE_OBJECT", [obj.id], `point light is inside the ${obj.type}; no shadow`));
  }
  if (parallel.some((p) => p)) warnings.push(make_warning("FACE_PARALLEL_TO_LIGHT", [obj.id]));
  const edge_sil = mesh.edge_faces.map(([f0, f1]) => lit[f0] !== lit[f1]);
  const sil_set = new Set<number>();
  mesh.edges.forEach(([i, j], e) => {
    if (edge_sil[e]) {
      sil_set.add(i);
      sil_set.add(j);
    }
  });
  const unlit: number[] = [];
  lit.forEach((l, k) => {
    if (!l) unlit.push(k);
  });
  return [{
    lit,
    parallel,
    light_inside: inside,
    edge_silhouette: edge_sil,
    silhouette_vertices: [...sil_set].sort((a, b) => a - b),
    loops: silhouette_loops(mesh, lit),
    form_idx: unlit.map((k) => mesh.faces[k] as number[]),
    form_faces: unlit.map((k) => obj.face_point_names[k] as string[]),
  }, warnings];
}

function is_tag(s: Source): s is Exclude<Source, VertexTag> {
  return s.kind !== "vertex";
}

function poly_loop_entries(sources: readonly Source[], V: readonly Vec4[], loop_vertex_ids: readonly number[], origins: readonly Origin[] | null,
  oid: string, lid: string, ground: Map<string, [string, Vec3]>): LoopEntry[] {
  const entries: LoopEntry[] = [];
  const ground_name = (key: string, xyz: Vec3): string => {
    let g = ground.get(key);
    if (g === undefined) {
      g = [`${oid}.s${ground.size}.${lid}`, xyz];
      ground.set(key, g);
    }
    return g[0];
  };
  sources.forEach((src, row) => {
    const X = V[row] as Vec4;
    if (is_tag(src)) {
      if (src.kind === "ground") {
        entries.push(ground_name(`clip:${ground.size}`, [X[0] / X[3], X[1] / X[3], X[2] / X[3]]));
      } else {
        entries.push({ direction: [X[0] + 0, X[1] + 0, X[2] + 0] });
      }
    } else {
      const vid = loop_vertex_ids[src.index] as number;
      const origin = origins === null ? vid : (origins[vid] as Origin);
      if (typeof origin === "object") {
        entries.push(ground_name(`v:${vid}`, [X[0] / X[3], X[1] / X[3], X[2] / X[3]]));
      } else {
        entries.push(`${oid}.v${origin}.shadow.${lid}`);
      }
    }
  });
  return entries;
}

function poly_shadow_record(obj: StageAObject, ol: ObjectLightData, lt: LightRecord, pi: Vec4, tol: number,
  receiver_id: string): [ShadowRecord, Warning[]] {
  const mesh = obj.mesh;
  const oid = obj.id, lid = lt.id;
  const V4 = mesh.vertices.map(h4);
  let loop_mesh: Mesh, origins: Origin[] | null, sil_loops: number[][], sil: number[];
  if (obj.ground_mesh === null || obj.ground_mesh === undefined) {
    loop_mesh = mesh;
    origins = null;
    sil_loops = ol.loops;
    sil = ol.silhouette_vertices;
  } else {
    [loop_mesh, origins] = obj.ground_mesh;
    const lit_c = face_lit_flags(loop_mesh, lt.L, lt.tol_lit).lit;
    sil_loops = silhouette_loops(loop_mesh, lit_c);
    const set = new Set<number>();
    loop_mesh.edges.forEach(([i, j], e) => {
      const [f0, f1] = loop_mesh.edge_faces[e] as [number, number];
      if (lit_c[f0] !== lit_c[f1]) {
        for (const v of [i, j]) {
          const o = (origins as Origin[])[v] as Origin;
          if (typeof o === "number") set.add(o);
        }
      }
    });
    sil = [...set].sort((a, b) => a - b);
  }
  const P4 = sil.map((k) => V4[k] as Vec4);
  const w_S = P4.map((P) => shadow_w(pi, lt.L, P));
  const finite = w_S.map((w) => w > lt.tol_w);
  const keep = P4.map((P, i) => (finite[i] as boolean) && dot4(P, pi) >= -tol);
  const warnings: Warning[] = [];
  if (sil.length > 0 && !finite.every((f) => f)) warnings.push(make_warning("VERTEX_NOT_BELOW_LIGHT", [oid]));
  const S_world = P4.map((P, i): Vec3 => {
    if (!keep[i]) return [0.0, 0.0, 0.0];
    const S = mat4_vec(lt.M, P);
    const w = w_S[i] as number;
    return [S[0] / w, S[1] / w, S[2] / w];
  });
  const Q_world = P4.map((P): Vec3 => {
    const Q = foot(pi, P);
    return [Q[0] / Q[3], Q[1] / Q[3], Q[2] / Q[3]];
  });
  const V4c = loop_mesh.vertices.map(h4);
  const loops: ShadowRecord["loops"] = [];
  const ground = new Map<string, [string, Vec3]>();
  let unbounded = false;
  for (const loop of sil_loops) {
    const sh = shadow_loop(loop.map((v) => V4c[v] as Vec4), lt.M, pi, lt.tol_w, tol);
    const entries = poly_loop_entries(sh.sources, sh.vertices, loop, origins, oid, lid, ground);
    unbounded = unbounded || sh.unbounded;
    loops.push({ vertices: sh.vertices, sources: sh.sources, entries, unbounded: sh.unbounded });
  }
  return [{
    light: lid,
    receiver: receiver_id,
    object: oid,
    keep,
    P_world: sil.map((k) => [...(mesh.vertices[k] as Vec3)] as Vec3),
    S_world,
    Q_world,
    w_S,
    shadow_names: sil.map((k) => `${oid}.v${k}.shadow.${lid}`),
    foot_names: sil.map((k) => `${oid}.v${k}.foot`),
    vertex_names: sil.map((k) => obj.point_names[k] as string),
    ground_points: [...ground.values()],
    loops,
    unbounded,
  }, warnings];
}

function empty_shadow(lid: string, receiver_id: string, oid: string): ShadowRecord {
  return {
    light: lid, receiver: receiver_id, object: oid, keep: [], P_world: [], S_world: [], Q_world: [], w_S: [],
    shadow_names: [], foot_names: [], vertex_names: [], ground_points: [], loops: [], unbounded: false,
  };
}

function canonical3(v: readonly number[]): Vec3 {
  return [(v[0] as number) + 0, (v[1] as number) + 0, (v[2] as number) + 0];
}

/** Stage A: camera-independent geometry (contract §3). Never touches `scene.camera`. */
export function shadow_geometry(scene: Scene): StageA {
  const objects = scene.objects.map((o) => build_object(o) as StageAObject);
  const vertices: Vec3[] = [];
  for (const o of objects) for (const v of o.mesh.vertices) vertices.push(v);
  const scale = scene_scale(vertices);
  const tol = tolerance(scale);
  const receiver = scene.receivers[0] as Receiver;
  const pi = receiver_plane(receiver);
  const lights = scene.lights.map((lt) => light_record(lt, pi, tol));
  const warnings: Warning[] = lights.flatMap((lt) => lt.warnings);
  const shadows: ShadowRecord[] = [];
  for (const obj of objects) {
    obj.lights = new Map();
    if (obj.analytic !== null) {
      shadows.push(...stage_a_object(obj, lights, pi, tol, receiver.id, warnings));
      continue;
    }
    obj.ground_mesh = null;
    if (obj.mesh.vertices.some((v) => dot4(h4(v), pi) < -tol)) {
      warnings.push(make_warning("OBJECT_BELOW_RECEIVER", [obj.id]));
      try {
        obj.ground_mesh = clip_mesh_to_plane(obj.mesh, pi, tol);
      } catch (exc) {
        // degenerate contact (Python: `except ValueError`); any other error is a bug and propagates
        if (!(exc instanceof NotManifoldError)) throw exc;
        obj.ground_mesh = null;
      }
    }
    for (const lt of lights) {
      const [ol, w] = object_light_data(obj, lt);
      warnings.push(...w);
      obj.lights.set(lt.id, ol);
      if (!lt.active || ol.light_inside) {
        shadows.push(empty_shadow(lt.id, receiver.id, obj.id));
        continue;
      }
      const [rec, w2] = poly_shadow_record(obj, ol, lt, pi, tol, receiver.id);
      warnings.push(...w2);
      shadows.push(rec);
    }
  }
  const shadows_a: StageAShadow[] = shadows.map((rec) => Object.assign(rec, {
    S_lists: rec.S_world.filter((_s, i) => rec.keep[i]).map(canonical3),
    Q_lists: rec.Q_world.filter((_s, i) => rec.keep[i]).map(canonical3),
    G_lists: rec.ground_points.map((g) => canonical3(g[1])),
  }));
  const lo: Vec3 = [Infinity, Infinity, Infinity], hi: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const v of vertices) {
    for (let k = 0; k < 3; k++) {
      lo[k] = Math.min(lo[k] as number, v[k] as number);
      hi[k] = Math.max(hi[k] as number, v[k] as number);
    }
  }
  return {
    objects,
    vertices,
    bbox: [lo, hi],
    scene_scale: scale,
    tol,
    receiver: { id: receiver.id, pi },
    lights,
    shadows: shadows_a,
    warnings: merge_warnings(warnings),
  };
}

// ---------------------------------------------------------------------------
// stage B
// ---------------------------------------------------------------------------

function resolve_camera(scene: Scene, camera: unknown): CameraBlock {
  if (camera === undefined || camera === null) return scene.camera;
  const cam = validate_camera(camera, "camera");
  const canvas = scene.output.canvas_mm, frame = cam.frame_mm;
  if (Math.abs(canvas[0] / canvas[1] - frame[0] / frame[1]) > 1e-9) {
    throw new SceneError("camera.frame_mm", "aspect ratio must equal output.canvas_mm aspect ratio");
  }
  return cam;
}

/** Drawing pipeline of contract §2.2 for one homogeneous world polygon -> canvas-mm points (may be empty). */
function project_polygon(cam: CameraRecord, V4in: readonly Vec4[]): Vec2[] {
  if (V4in.length < 3) return [];
  const V4 = clip_polygon_near(cam, V4in);
  if (V4.length < 3) return [];
  const X = clip_polygon_rect_h(V4.map((v) => project(cam, v)), cam.rect);
  if (X.length < 3) return [];
  return X.map((x) => divide(x));
}

function project_polyhedron(o: StageAObject, cam: CameraRecord, tol: number, light_id: string | null): PolyStageB {
  const m = o.mesh;
  const V4 = m.vertices.map(h4);
  const x_h = V4.map((v) => project(cam, v));
  const behind = V4.map((v) => nu(cam, v) < 0.0);
  const C4: Vec4 = [cam.C[0], cam.C[1], cam.C[2], 1.0];
  const face_lit = m.faces.map((_f, k) => lit_value(m.face_normals[k] as Vec3, m.vertices[o.face_first[k] as number] as Vec3, C4) > tol);
  const back = m.edge_faces.map(([f0, f1]) => !face_lit[f0] && !face_lit[f1]);
  const ol = light_id === null ? undefined : o.lights.get(light_id);
  const silhouette = ol !== undefined ? ol.edge_silhouette : m.edges.map(() => false);
  const segments_h: ([Vec3, Vec3] | null)[] = [];
  const keep: boolean[] = [];
  for (const [i, j] of m.edges) {
    const near = clip_segment_near(cam, V4[i] as Vec4, V4[j] as Vec4);
    const r = near === null ? null : clip_segment_rect_h(project(cam, near[0]), project(cam, near[1]), cam.rect);
    segments_h.push(r);
    keep.push(r !== null);
  }
  const form_faces = ol !== undefined ? ol.form_faces : [];
  const form_polygons = ol !== undefined ? ol.form_idx.map((face) => project_polygon(cam, face.map((v) => V4[v] as Vec4))) : [];
  return {
    id: o.id,
    type: o.type,
    analytic: false,
    point_names: o.point_names,
    world: m.vertices,
    world_lists: o.world_lists,
    image_h: x_h,
    depth: x_h.map((x) => x[2]),
    behind,
    edges: m.edges,
    edge_templates: o.edge_templates,
    back,
    silhouette,
    segments_h,
    segment_keep: keep,
    form_faces,
    form_polygons,
  };
}

function project_light(lt: LightRecord, cam: CameraRecord, tol: number): [LightStageB, Warning[]] {
  const finite = lt.type === "point";
  const tol_L = finite ? tol : TOL_DIR;
  const lp = special_point_image(cam, lt.L, tol_L);
  let fp = special_point_image(cam, lt.F, tol_L);
  if (!lt.F_defined) fp = { h: [0, 0, 0], point: null, at_infinity: null, behind: false, undefined: true };
  const warnings: Warning[] = [];
  if (finite && lp.behind) warnings.push(make_warning("LIGHT_BEHIND_CAMERA", [lt.id]));
  if (lp.at_infinity !== null) warnings.push(make_warning("LIGHT_POINT_AT_INFINITY", [lt.id]));
  if (fp.at_infinity !== null) warnings.push(make_warning("SHADOW_VP_AT_INFINITY", [lt.id]));
  return [{
    id: lt.id, type: lt.type, active: lt.active, L: lt.L, F: lt.F, F_defined: lt.F_defined, light_point: lp, shadow_vp: fp,
    L_depth: finite ? lp.h[2] : null, F_depth: finite ? fp.h[2] : null,
  }, warnings];
}

function ray_kinds(light: LightStageB, P_uv: Vec2[], S_uv: Vec2[], Q_uv: Vec2[]): [string, [Vec2, Vec2][]][] {
  const lp = light.light_point, fp = light.shadow_vp;
  const kinds: [string, [Vec2, Vec2][]][] = [];
  if (lp.point !== null) kinds.push(["LP", covering_segments(lp.point, P_uv, S_uv)]);
  else if (lp.at_infinity !== null) kinds.push(["LP", extended_segments(P_uv, S_uv)]);
  if (fp.point !== null) kinds.push(["FQ", covering_segments(fp.point, Q_uv, S_uv)]);
  else if (fp.at_infinity !== null) kinds.push(["FQ", extended_segments(Q_uv, S_uv)]);
  kinds.push(["PQ", P_uv.map((p, i) => [p, Q_uv[i] as Vec2] as [Vec2, Vec2])]);
  return kinds;
}

function project_shadow(rec: StageAShadow, cam: CameraRecord, tol: number, light: LightStageB): [ShadowStageB, Warning[]] {
  const warnings: Warning[] = [];
  const P4 = rec.P_world.map(h4), S4 = rec.S_world.map(h4), Q4 = rec.Q_world.map(h4);
  const xP = P4.map((x) => project(cam, x)), xS = S4.map((x) => project(cam, x)), xQ = Q4.map((x) => project(cam, x));
  const nuP = P4.map((x) => nu(cam, x)), nuS = S4.map((x) => nu(cam, x)), nuQ = Q4.map((x) => nu(cam, x));
  const S_behind = nuS.map((v) => v < 0.0), Q_behind = nuQ.map((v) => v < 0.0);
  if (rec.keep.some((k, i) => k && ((S_behind[i] as boolean) || (Q_behind[i] as boolean)))) {
    warnings.push(make_warning("POINT_BEHIND_CAMERA", [rec.object]));
  }
  const G_world = rec.ground_points.map((g) => g[1]);
  const G4 = G_world.map(h4);
  const xG = G4.map((x) => project(cam, x));
  const G_behind = G4.map((x) => nu(cam, x) < 0.0);
  const polygons = rec.loops.map((loop) => project_polygon(cam, loop.vertices));
  const rows_ok: number[] = [];
  rec.keep.forEach((k, i) => {
    if (k && (nuP[i] as number) >= 0.0 && (nuS[i] as number) >= 0.0 && (nuQ[i] as number) >= 0.0) rows_ok.push(i);
  });
  const lp_undefined = light.light_point.undefined, fp_undefined = light.shadow_vp.undefined;
  const kinds_of_rays = [...(lp_undefined ? [] : ["L"]), ...(fp_undefined ? [] : ["F"])];
  const segments: RaySegment[] = [];
  const rays: [string, string][] = [];
  if (rows_ok.length > 0) {
    const P_uv = rows_ok.map((i) => divide(xP[i] as Vec3));
    const S_uv = rows_ok.map((i) => divide(xS[i] as Vec3));
    const Q_uv = rows_ok.map((i) => divide(xQ[i] as Vec3));
    const kinds = ray_kinds(light, P_uv, S_uv, Q_uv).map(([kind, segs]) => [kind, clip_segments_uv(segs, cam.rect)] as const);
    rows_ok.forEach((i, r) => {
      const name = rec.vertex_names[i] as string;
      for (const [kind, clipped] of kinds) {
        const c = clipped[r];
        if (c !== null && c !== undefined) segments.push({ kind, point: name, points: [[c[0][0] + 0, c[0][1] + 0], [c[1][0] + 0, c[1][1] + 0]] });
      }
      for (const kind of kinds_of_rays) rays.push([kind, kind === "L" ? name : `${name}.foot`]);
    });
  }
  const pick = (xs: Vec3[]): Vec3[] => rows_ok.map((i) => xs[i] as Vec3);
  let res;
  if (lp_undefined) res = coincidence_check(pick(xS), pick(xP), tol);
  else if (fp_undefined) res = coincidence_check(pick(xS), pick(xQ), tol);
  else res = self_check(light.light_point.h, pick(xP), light.shadow_vp.h, pick(xQ), pick(xS), tol);
  const checks: Check[] = [];
  rows_ok.forEach((i, r) => {
    const nm = rec.shadow_names[i] as string;
    if (res.skipped[r]) warnings.push(make_warning("CONSTRUCTION_CHECK_SKIPPED", [nm]));
    else checks.push({ point: nm, max_error_mm: (res.err[r] as number) + 0 });
  });
  return [{
    light: rec.light,
    receiver: rec.receiver,
    object: rec.object,
    keep: rec.keep,
    shadow_names: rec.shadow_names,
    foot_names: rec.foot_names,
    S_world: rec.S_world, S_h: xS, S_behind,
    Q_world: rec.Q_world, Q_h: xQ, Q_behind,
    ground_names: rec.ground_points.map((g) => g[0]),
    G_world, G_h: xG, G_behind,
    S_lists: rec.S_lists,
    Q_lists: rec.Q_lists,
    G_lists: rec.G_lists,
    loops: rec.loops.map((loop) => loop.entries),
    polygons,
    unbounded: rec.unbounded,
    rays,
    segments,
    checks,
  }, warnings];
}

/**
 * Stage B: project stage-A geometry with the scene camera or an override (contract §3). `umbra` is the M6 switch
 * (phase 2, §5.4.14); it has no effect on a single-light scene.
 */
/**
 * The stage-B `construction` block of one light (contract §2.7, §5.4.14 (c)): `L'`, `F'` and the rays, self-checks
 * and segments of that light's shadow records, flattened in record order. Phase 1 calls it once for the single
 * light; the per-light `constructions` map of §5.3.5 (phase 2) is a loop around it.
 */
export function construction_block(light: LightStageB, shadows: readonly ShadowStageB[]): ConstructionStageB {
  return {
    light_point: light.light_point.point,
    light_point_at_infinity: light.light_point.at_infinity,
    shadow_vp: light.shadow_vp.point,
    shadow_vp_at_infinity: light.shadow_vp.at_infinity,
    rays: shadows.flatMap((s) => s.rays),
    checks: shadows.flatMap((s) => s.checks),
    segments: shadows.flatMap((s) => s.segments),
  };
}

export function project_scene(scene: Scene, A: StageA, camera?: unknown, umbra = true): StageB {
  void umbra;
  const cam_dict = resolve_camera(scene, camera);
  const cam = camera_matrix(cam_dict, scene.output.canvas_mm);
  const scale = scene_scale(A.vertices, cam.C);
  const tol = tolerance(scale);
  const warnings: Warning[] = [...cam.warnings, ...A.warnings];
  const light_id = A.lights.length > 0 ? (A.lights[0] as LightRecord).id : null;
  const objects: (PolyStageB | CurvedStageB)[] = [];
  const curved_objs: StageAObject[] = [];
  const curved_recs: Partial<CurvedStageB>[] = [];
  for (const obj of A.objects) {
    if (obj.analytic !== null) {
      const rec: Partial<CurvedStageB> = { id: obj.id, type: obj.type, analytic: true };
      curved_objs.push(obj);
      curved_recs.push(rec);
      objects.push(rec as CurvedStageB);
    } else {
      const rec = project_polyhedron(obj, cam, tol, light_id);
      if (rec.behind.some((b) => b)) warnings.push(make_warning("POINT_BEHIND_CAMERA", [obj.id]));
      objects.push(rec);
    }
  }
  stage_b_objects(curved_objs, curved_recs, cam, tol, warnings);
  const lights: LightStageB[] = [];
  for (const lt of A.lights) {
    const [lrec, w] = project_light(lt, cam, tol);
    warnings.push(...w);
    lights.push(lrec);
  }
  const by_id = new Map(lights.map((lt) => [lt.id, lt] as const));
  const shadows: ShadowStageB[] = [];
  for (const rec of A.shadows) {
    const [s, w] = project_shadow(rec, cam, tol, by_id.get(rec.light) as LightStageB);
    warnings.push(...w);
    shadows.push(s);
  }
  let construction: ConstructionStageB | null = null;
  if (lights.length > 0) {
    const lt = lights[0] as LightStageB;
    construction = construction_block(lt, shadows.filter((s) => s.light === lt.id));
  }
  return {
    camera: cam,
    scene_scale: scale,
    tol,
    objects,
    lights,
    horizon: camera_horizon(cam, TOL_DIR),
    shadows,
    construction,
    warnings: merge_warnings(warnings),
    A,
  };
}

// ---------------------------------------------------------------------------
// stage C
// ---------------------------------------------------------------------------

type PointEntry = { world: Vec3; image: Vec2 | null; depth: number } | { direction: Vec3; at_infinity: true; image: Vec2 | null };

function finite_points(points: Record<string, PointEntry>, names: readonly string[], world: readonly Vec3[], x_h: readonly Vec3[],
  behind: readonly boolean[]): void {
  names.forEach((name, i) => {
    const x = x_h[i] as Vec3;
    let image: Vec2 | null = null;
    if (!behind[i]) {
      const uv = divide(x);
      image = [uv[0] + 0, uv[1] + 0];
    }
    points[name] = { world: world[i] as Vec3, image, depth: x[2] + 0 };
  });
}

function light_points(points: Record<string, PointEntry>, lt: LightStageB): void {
  const rows: [string, Vec4, SpecialPointImage, number | null][] = [
    ["L", lt.L, lt.light_point, lt.L_depth],
    ["F", lt.F, lt.shadow_vp, lt.F_depth],
  ];
  for (const [prefix, X, img, depth] of rows) {
    if (prefix === "F" && !lt.F_defined) continue;
    const name = `${prefix}.${lt.id}`;
    if (lt.type === "point") points[name] = { world: [X[0] + 0, X[1] + 0, X[2] + 0], image: img.point, depth: (depth as number) + 0 };
    else points[name] = { direction: [X[0] + 0, X[1] + 0, X[2] + 0], at_infinity: true, image: img.point };
  }
}

interface Drawables {
  polylines: Vec2[][];
  arcs: { start: Vec2; end: Vec2; rx: number; ry: number; rotation_deg: number; large_arc: number; sweep: number; theta: Vec2 }[];
  ellipses: { centre: Vec2; rx: number; ry: number; rotation_deg: number }[];
}

function arc_drawables(a: ArcRecord): Drawables {
  const out: Drawables = { polylines: [], arcs: [], ellipses: [] };
  const H = a.H, rho = a.rho;
  const healthy = a.kind === "ellipse" && !a.sampled;
  if (a.whole_circle && healthy && a.visible.length > 0) {
    const params = ellipse_params(a.conic);
    if (params !== null) {
      const [centre, [major, minor], rot] = params;
      out.ellipses.push({ centre: [centre[0] + 0, centre[1] + 0], rx: major + 0, ry: minor + 0, rotation_deg: degrees(rot) + 0 });
      return out;
    }
  }
  for (const [lo, hi] of a.visible) {
    if (healthy) {
      const p = ellipse_arc_params(H, rho, lo, hi);
      if (p !== null) {
        out.arcs.push({
          start: [p.start[0] + 0, p.start[1] + 0], end: [p.end[0] + 0, p.end[1] + 0], rx: p.axes[0] + 0, ry: p.axes[1] + 0,
          rotation_deg: degrees(p.rotation) + 0, large_arc: p.large_arc, sweep: p.sweep, theta: [lo + 0, hi + 0],
        });
        continue;
      }
    }
    const pts = sample_arc(H, rho, lo, hi, sample_count(lo, hi));
    out.polylines.push(pts.map((x) => {
      const uv = divide(x);
      return [uv[0] + 0, uv[1] + 0] as Vec2;
    }));
  }
  return out;
}

function conic_doc_entry(a: ArcRecord, with_back = false): Record<string, unknown> {
  const entry: Record<string, unknown> = {
    conic: a.conic, kind: a.kind, arc: a.arc, circle: a.circle, map: a.map, sampled: a.sampled, which: a.which,
    visible: a.visible.map(([lo, hi]) => [lo + 0, hi + 0]),
  };
  if (with_back) entry["back"] = a.back;
  return { ...entry, ...arc_drawables(a) };
}

function segment_uv(seg_h: readonly (readonly number[])[] | null, keep: boolean): [Vec2, Vec2] | null {
  if (!keep || seg_h === null) return null;
  const a = divide(seg_h[0] as readonly number[]), b = divide(seg_h[1] as readonly number[]);
  return [[a[0] + 0, a[1] + 0], [b[0] + 0, b[1] + 0]];
}

/**
 * Stage C: the spec §6.2 geometry document (contract §3.1). `hidden_lines` is the M4 switch (phase 2, §5.4.14); it has
 * no effect on the v1 document.
 */
export function compose(scene: Scene, B: StageB, hidden_lines?: boolean | null): GeometryDocument {
  void scene;
  void hidden_lines;
  const cam = B.camera;
  const points: Record<string, PointEntry> = {};
  const edges: Record<string, unknown>[] = [];
  const outlines: Record<string, unknown>[] = [];
  const form_shadow: Record<string, unknown>[] = [];
  const conics_by = new Map<string, Record<string, unknown>[]>();
  const curved_recs: CurvedStageB[] = [];
  const poly_recs: PolyStageB[] = [];
  for (const rec of B.objects) {
    if (rec.analytic) curved_recs.push(rec);
    else poly_recs.push(rec);
  }
  // curved objects first (their points), then the polyhedral ones, as in the Python compose
  for (const rec of curved_recs) {
    finite_points(points, rec.point_names, rec.world, rec.image_h, rec.behind);
    for (const [lid, arcs] of rec.shadow_arcs) conics_by.set(JSON.stringify([rec.id, lid]), arcs.map((a) => conic_doc_entry(a)));
  }
  for (const rec of poly_recs) finite_points(points, rec.point_names, rec.world_lists, rec.image_h, rec.behind);
  for (const rec of B.objects) {
    if (rec.analytic) {
      const generators = rec.gen_edges.map((e) => ({ from: e.from, to: e.to, back: false, segment: segment_uv(e.segment_h, e.keep) }));
      outlines.push({ object: rec.id, generators, conics: rec.outline_arcs.map((a) => conic_doc_entry(a, true)) });
      const term: Record<string, unknown>[] = [];
      for (const items of rec.terminator.values()) {
        for (const it of items) {
          if ("segment" in it) {
            const seg = segment_uv(it.segment_h, it.keep);
            term.push({ segment: [...it.segment], polylines: seg !== null ? [seg] : [] });
          } else {
            term.push(conic_doc_entry(it));
          }
        }
      }
      if (term.length > 0) form_shadow.push({ object: rec.id, faces: [], terminator: term, polygons: [] });
    } else {
      rec.edge_templates.forEach((t, e) => {
        edges.push({ ...t, silhouette: rec.silhouette[e], back: rec.back[e], segment: segment_uv(rec.segments_h[e] ?? null, rec.segment_keep[e] as boolean) });
      });
      if (rec.form_faces.length > 0) {
        form_shadow.push({
          object: rec.id, faces: rec.form_faces, terminator: [],
          polygons: rec.form_polygons.map((poly) => poly.map((p) => [p[0] + 0, p[1] + 0])),
        });
      }
    }
  }
  for (const lt of B.lights) light_points(points, lt);
  for (const s of B.shadows) {
    finite_points(points, s.shadow_names.filter((_n, i) => s.keep[i]), s.S_lists, s.S_h.filter((_x, i) => s.keep[i]),
      s.S_behind.filter((_b, i) => s.keep[i]));
  }
  for (const s of B.shadows) {
    finite_points(points, s.foot_names.filter((_n, i) => s.keep[i]), s.Q_lists, s.Q_h.filter((_x, i) => s.keep[i]),
      s.Q_behind.filter((_b, i) => s.keep[i]));
  }
  for (const s of B.shadows) finite_points(points, s.ground_names, s.G_lists, s.G_h, s.G_behind);
  const shadows = B.shadows.map((s) => ({
    light: s.light,
    receiver: s.receiver,
    object: s.object,
    outline: s.loops.length > 0 ? s.loops[0] : [],
    loops: [...s.loops],
    conics: conics_by.get(JSON.stringify([s.object, s.light])) ?? [],
    unbounded: s.unbounded,
    polygons: s.polygons.map((poly) => poly.map((p) => [p[0] + 0, p[1] + 0])),
  }));
  const hz = B.horizon;
  const construction = B.construction ?? {
    light_point: null, light_point_at_infinity: null, shadow_vp: null, shadow_vp_at_infinity: null, rays: [], checks: [], segments: [],
  };
  const head = canonical({
    canvas_mm: [cam.canvas_mm[0], cam.canvas_mm[1]],
    camera: {
      P: cam.P.map((r) => [...r]),
      C: [...cam.C],
      horizon_line: [...hz.line],
      principal_point: [cam.u0, cam.v0],
    },
    construction: {
      light_point: construction.light_point,
      light_point_at_infinity: construction.light_point_at_infinity,
      shadow_vp: construction.shadow_vp,
      shadow_vp_at_infinity: construction.shadow_vp_at_infinity,
    },
    horizon: {
      v_mm: hz.v_mm,
      line: [...hz.line],
      segment: hz.segment,
      vanishing_points: { x: hz.vanishing_points.x, y: hz.vanishing_points.y, z: hz.vanishing_points.z },
    },
    warnings: B.warnings.map((w) => ({ code: w.code, ids: [...w.ids], message: w.message })),
  });
  return {
    ...head,
    construction: {
      ...head.construction,
      rays: [...construction.rays],
      checks: [...construction.checks],
      segments: [...construction.segments],
    },
    points,
    edges,
    shadows,
    form_shadow,
    outlines,
  } as unknown as GeometryDocument;
}

/** Run stages A, B, C and write the SVG with the scene's layer subset (contract §3). `hidden_lines`,
 * `hidden_style` and `umbra` are the phase-2 switches (§5.4.14) and have no effect on the v1 document. */
export function render(scene: Scene, camera?: unknown, hidden_lines?: boolean | null, hidden_style?: string | null,
  umbra = true): { geometry: GeometryDocument; svg: string } {
  void hidden_style;
  const A = shadow_geometry(scene);
  const B = project_scene(scene, A, camera, umbra);
  const doc = compose(scene, B, hidden_lines);
  return { geometry: doc, svg: write_svg(doc, scene.output.layers) };
}
