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
import { shadow_arc_key, stage_a_object, stage_b_objects } from "./curved.js";
import type { ArcRecord, CurvedStageB, CurvedStore, LoopEntry, ReceiverRecordLike, ShadowRecord } from "./curved.js";
import type { GeometryDocument } from "./document.js";
import { SceneError, make_warning, merge_warnings } from "./errors.js";
import type { Warning } from "./errors.js";
import { TOL_DIR, row_max_abs, scene_scale, tolerance } from "./homogeneous.js";
import { face_lit_flags, light_vector, lit_value, silhouette_loops } from "./light.js";
import { classify_document } from "./hidden.js";
import { NotManifoldError } from "./mesh.js";
import type { Mesh } from "./mesh.js";
import { is_multi } from "./multilight.js";
import { canonical } from "./output/geometry_json.js";
import { write_svg } from "./output/svg.js";
import { build_object, point_inside_solid } from "./primitives.js";
import type { EdgeTemplate, ObjectRecord } from "./primitives.js";
import { validate_camera } from "./scene.js";
import type { Light, Receiver, Scene } from "./scene.js";
import {
  bounds_functionals, clip_mesh_to_plane, clip_polygon_bounds, foot, mat4_vec, plate_loop, receiver_frame, shadow_loop, shadow_matrix,
  shadow_w,
} from "./shadow.js";
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
  /** The receiver this record belongs to (contract §5.1.2) and its name suffix (`""` for `receivers[0]`). */
  receiver: string;
  suffix: string;
}

/** Stage-A record of one receiver (contract §5.1.2). */
export interface ReceiverRecord extends ReceiverRecordLike {
  index: number;
  bounds4: Vec4[] | null;
  lights: LightRecord[];
  lit: Map<string, boolean>;
  casts: Map<string, boolean>;
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
  /** Per receiver id: the part of the solid in front of `π_r` (`null`: no vertex behind it, contract §5.1.2). */
  clipped: Map<string, [Mesh, Origin[]] | null>;
  curved?: CurvedStore;
}

export interface StageA {
  objects: StageAObject[];
  vertices: Vec3[];
  bbox: [Vec3, Vec3];
  scene_scale: number;
  tol: number;
  receiver: { id: string; pi: Vec4 };
  receivers: ReceiverRecord[];
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
  /** Receivers other than `receivers[0]` (`receiver_lights`). */
  receiver?: string;
  suffix?: string;
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

export interface ReceiverConstructionStageB {
  shadow_vp: Vec2 | null;
  shadow_vp_at_infinity: Vec2 | null;
  rays: [string, string][];
  checks: Check[];
  segments: RaySegment[];
}

export interface ConstructionStageB {
  light_point: Vec2 | null;
  light_point_at_infinity: Vec2 | null;
  shadow_vp: Vec2 | null;
  shadow_vp_at_infinity: Vec2 | null;
  rays: [string, string][];
  checks: Check[];
  segments: RaySegment[];
  per_receiver: Map<string, ReceiverConstructionStageB>;
}

/** The camera-free §5.1.7 `receivers[]` entry. */
export interface ReceiverDocEntry {
  id: string;
  plane: Vec4;
  bounds: Vec3[] | null;
  lit: Record<string, boolean>;
  casts: Record<string, boolean>;
}

export interface PlateEdge {
  object: string;
  from: string;
  to: string;
  silhouette: boolean;
  back: false;
  visibility: "visible";
  runs: never[];
  segment: [Vec2, Vec2] | null;
}

/** Stage B of a bounded receiver drawn as an opaque plate (contract §5.1.7 / §5.1.8). */
export interface PlateStageB {
  id: string;
  point_names: string[];
  world: Vec3[];
  image_h: Vec3[];
  behind: boolean[];
  edges: PlateEdge[];
  form_shadow: { object: string; faces: string[][]; terminator: never[]; polygons: Vec2[][] } | null;
}

export interface StageB {
  camera: CameraRecord;
  scene_scale: number;
  tol: number;
  objects: (PolyStageB | CurvedStageB)[];
  lights: LightStageB[];
  /** Per receiver other than `receivers[0]`: the projections of its light records (`F'_r`). */
  receiver_lights: Map<string, LightStageB[]>;
  receivers: ReceiverDocEntry[];
  plates: PlateStageB[];
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
  return {
    id: light.id, type: light.type, L, M: shadow_matrix(pi, L), F, F_defined, pi_L, active, tol_w, tol_lit: tol_w, warnings,
    receiver: "", suffix: "",
  };
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

/**
 * Outline entries of one shadow loop from its `sources` (contract §3.1 naming). M4 (contract §5.1.2 / §5.1.3.3):
 * `suffix` is `".<receiver id>"` for every receiver other than `receivers[0]`; the `bounds` rows of the bounds clip
 * (crossings and anchors) are named as ground points of the receiver; `vertex_prefix` is `"b"` for a plate caster.
 */
function poly_loop_entries(sources: readonly Source[], V: readonly Vec4[], loop_vertex_ids: readonly number[], origins: readonly Origin[] | null,
  oid: string, lid: string, ground: Map<string, [string, Vec3]>, suffix = "", vertex_prefix = "v"): LoopEntry[] {
  const entries: LoopEntry[] = [];
  const ground_name = (key: string, xyz: Vec3): string => {
    let g = ground.get(key);
    if (g === undefined) {
      g = [`${oid}.s${ground.size}.${lid}${suffix}`, xyz];
      ground.set(key, g);
    }
    return g[0];
  };
  sources.forEach((src, row) => {
    const X = V[row] as Vec4;
    if (is_tag(src)) {
      if (src.kind === "ground" || src.kind === "bounds") {
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
        entries.push(`${oid}.${vertex_prefix}${origin}.shadow.${lid}${suffix}`);
      }
    }
  });
  return entries;
}

/** Silhouette vertices of a clipped mesh that are original vertices (a vertex on the plane may be a silhouette vertex
 * there without being one of the full mesh: cut-face edges are silhouette edges), ascending. */
function clipped_silhouette_vertices(loop_mesh: Mesh, origins: readonly Origin[], lit_c: readonly boolean[]): number[] {
  const set = new Set<number>();
  loop_mesh.edges.forEach(([i, j], e) => {
    const [f0, f1] = loop_mesh.edge_faces[e] as [number, number];
    if (lit_c[f0] !== lit_c[f1]) {
      for (const v of [i, j]) {
        const o = origins[v] as Origin;
        if (typeof o === "number") set.add(o);
      }
    }
  });
  return [...set].sort((a, b) => a - b);
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
    sil = clipped_silhouette_vertices(loop_mesh, origins, lit_c);
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

/** Stage A: camera-independent geometry (contract §3, §5.1.2, §5.1.3). Never touches `scene.camera`. `shadows` is
 * ordered receiver (scene order) → light (scene order) → caster (objects in scene order, then the other bounded
 * receivers), contract §5.1.3.1. */
export function shadow_geometry(scene: Scene): StageA {
  // interim guard until src/meshprep.ts lands (M7 phase 2, mesh part): a typed SceneError, never a plain Error
  scene.objects.forEach((o, i) => {
    if (o.type === "mesh") {
      throw new SceneError(`objects[${i}].type`, "mesh objects are not ported yet (M7 phase 2, mesh part of contract §5.4.14)");
    }
  });
  const objects = scene.objects.map((o) => build_object(o) as StageAObject);
  const receivers = scene.receivers.map((r, i) => receiver_record(r, i));
  // contract §5.1.2: bounds vertices are scene geometry (the ground has none: v2 scales unchanged)
  const vertices: Vec3[] = [];
  for (const o of objects) for (const v of o.mesh.vertices) vertices.push(v);
  for (const r of receivers) if (r.bounded) for (const b of r.bounds as Vec3[]) vertices.push(b);
  const scale = scene_scale(vertices);
  const tol = tolerance(scale);
  const receiver = scene.receivers[0] as Receiver;
  const dflt = receivers[0] as ReceiverRecord;
  const pi = dflt.pi;
  let lights: LightRecord[];
  let ground_unlit: Set<string>;
  if (dflt.bounded) {
    lights = receiver_light_records(dflt, scene.lights, tol, new Set());
    ground_unlit = new Set();
  } else {
    lights = scene.lights.map((lt) => light_record(lt, pi, tol));
    // contract §5.1.2: the unbounded ground is opaque to light
    ground_unlit = new Set(lights.filter((lt) => lt.warnings.some((w) => w.code === "LIGHT_BELOW_RECEIVER")).map((lt) => lt.id));
    for (const lt of lights) {
      lt.receiver = dflt.id;
      lt.suffix = "";
    }
  }
  dflt.lights = lights;
  for (const rcv of receivers.slice(1)) rcv.lights = receiver_light_records(rcv, scene.lights, tol, ground_unlit);
  receiver_lit_casts(receivers, ground_unlit);
  const warnings: Warning[] = receivers.flatMap((rcv) => rcv.lights.flatMap((lt) => lt.warnings));
  const light_index = new Map(scene.lights.map((lt, k) => [lt.id, k] as const));
  const multi = is_multi(scene.lights);
  const shadows: ShadowRecord[] = [];
  for (const obj of objects) {
    obj.lights = new Map();
    obj.clipped = new Map();
    if (dflt.bounded) {
      bounded_default_object(obj, receivers, lights, tol, warnings);
      continue;
    }
    if (obj.analytic !== null) {
      // curved primitives: silhouette / terminator / shadow conics from curved.ts (§5.6)
      shadows.push(...stage_a_object(obj, lights, dflt, tol, warnings, multi));
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
    clip_object_to_receivers(obj, receivers, tol);
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
  // (receiver index, light index) -> records in caster order (§5.1.3.1); the unbounded default receiver's records
  // above are object-major: regroup them by light
  const buckets = new Map<string, { ri: number; li: number; recs: ShadowRecord[] }>();
  const bucket = (ri: number, li: number): ShadowRecord[] => {
    const key = `${ri},${li}`;
    let b = buckets.get(key);
    if (b === undefined) {
      b = { ri, li, recs: [] };
      buckets.set(key, b);
    }
    return b.recs;
  };
  for (const rec of shadows) bucket(0, light_index.get(rec.light) as number).push(rec);
  for (const rcv of receivers) {
    for (const [li, recs] of shadow_records_for_receiver(rcv, objects, receivers, tol, warnings)) bucket(rcv.index, li).push(...recs);
  }
  const ordered = [...buckets.values()].sort((a, b) => a.ri - b.ri || a.li - b.li).flatMap((b) => b.recs);
  const shadows_a: StageAShadow[] = ordered.map((rec) => Object.assign(rec, {
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
    receivers,
    lights,
    shadows: shadows_a,
    warnings: merge_warnings(warnings),
  };
}

// ---------------------------------------------------------------------------
// stage A, M4: receivers other than the unbounded ground (contract §5.1.2, §5.1.3)
// ---------------------------------------------------------------------------

/** Stage-A record of one validated receiver (contract §5.1.2): `pi`, `bounded`, the name `suffix` (`""` for
 * `receivers[0]`, `".<id>"` otherwise), and for a bounded receiver its frame, `bounds`, `bounds4` and `psi`. */
function receiver_record(receiver: Receiver, index: number): ReceiverRecord {
  const pi = receiver_plane(receiver);
  const bounded = receiver.bounds !== null;
  const rec: ReceiverRecord = {
    id: receiver.id, index, pi, bounded, suffix: index === 0 ? "" : `.${receiver.id}`, frame: null, bounds: null, bounds4: null,
    psi: null, lights: [], lit: new Map(), casts: new Map(),
  };
  if (bounded) {
    const B = (receiver.bounds as Vec3[]).map((b) => [b[0], b[1], b[2]] as Vec3);
    const n: Vec3 = [pi[0], pi[1], pi[2]];
    rec.frame = receiver_frame(n);
    rec.bounds = B;
    rec.bounds4 = B.map(h4);
    rec.psi = bounds_functionals(B, n);
  }
  return rec;
}

/** `RECEIVER_UNLIT` messages per case (contract §5.1.2, §5.0.5). */
const UNLIT_MESSAGES: Readonly<Record<string, string>> = {
  ground: "light below the ground; the bounded receiver receives no shadow from it",
  point: "point light is behind the bounded receiver or in its plane; it receives no shadow",
  parallel: "directional light is parallel to the bounded receiver; it receives no shadow",
  behind: "directional light is behind the bounded receiver; it receives no shadow",
};

/** Per-light records of one receiver (the §2.3 formulas with `π_r`); a bounded receiver replaces the ground codes by
 * `RECEIVER_UNLIT` (ids `[light, receiver]`) in the three band cases and when the ground is unlit by that light. */
function receiver_light_records(rcv: ReceiverRecord, scene_lights: readonly Light[], tol: number, ground_unlit: ReadonlySet<string>): LightRecord[] {
  return scene_lights.map((light) => {
    const lt = light_record(light, rcv.pi, tol);
    lt.receiver = rcv.id;
    lt.suffix = rcv.suffix;
    if (rcv.bounded) {
      let kase: string | null = null;
      if (ground_unlit.has(light.id)) kase = "ground";
      else if (light.type === "point") kase = lt.pi_L <= tol ? "point" : null;
      else if (Math.abs(lt.pi_L) <= TOL_DIR) kase = "parallel";
      else if (lt.pi_L < -TOL_DIR) kase = "behind";
      lt.active = kase === null;
      lt.warnings = kase === null ? [] : [make_warning("RECEIVER_UNLIT", [light.id, rcv.id], UNLIT_MESSAGES[kase])];
    }
    return lt;
  });
}

/** `lit[<light>]` and `casts[<light>]` of every receiver (contract §5.1.2). */
function receiver_lit_casts(receivers: readonly ReceiverRecord[], ground_unlit: ReadonlySet<string>): void {
  for (const rcv of receivers) {
    for (const lt of rcv.lights) {
      rcv.lit.set(lt.id, lt.active);
      rcv.casts.set(lt.id, rcv.bounded && !ground_unlit.has(lt.id) && Math.abs(lt.pi_L) > lt.tol_w);
    }
  }
}

/** `obj.clipped[r]` (contract §5.1.2): the part of the solid in front of `π_r` as a closed mesh, `null` when no
 * vertex is behind `π_r` or the cut surface is not a closed manifold. */
function clip_object(obj: StageAObject, rcv: ReceiverRecord, tol: number): [Mesh, Origin[]] | null {
  if (!obj.mesh.vertices.some((v) => dot4(h4(v), rcv.pi) < -tol)) return null;
  try {
    return clip_mesh_to_plane(obj.mesh, rcv.pi, tol);
  } catch (exc) {
    if (!(exc instanceof NotManifoldError)) throw exc;
    return null;
  }
}

function clip_object_to_receivers(obj: StageAObject, receivers: readonly ReceiverRecord[], tol: number): void {
  obj.clipped.set((receivers[0] as ReceiverRecord).id, obj.ground_mesh ?? null);
  for (const rcv of receivers) if (rcv.bounded) obj.clipped.set(rcv.id, clip_object(obj, rcv, tol));
}

/** Stage A, bounded default receiver: clipped meshes and per-light data of a polyhedral object (its shadow records
 * come from `shadow_records_for_receiver`, like curved objects'). */
function bounded_default_object(obj: StageAObject, receivers: readonly ReceiverRecord[], lights: readonly LightRecord[], tol: number,
  warnings: Warning[]): void {
  if (obj.analytic !== null) return;
  for (const rcv of receivers) if (rcv.bounded) obj.clipped.set(rcv.id, clip_object(obj, rcv, tol));
  obj.ground_mesh = obj.clipped.get((receivers[0] as ReceiverRecord).id) ?? null;
  for (const lt of lights) {
    const [ol, w] = object_light_data(obj, lt);
    warnings.push(...w);
    obj.lights.set(lt.id, ol);
  }
}

/** Shadow record of one caster (an object part or a plate) on one receiver under one active light (contract §5.1.3);
 * on a bounded receiver every loop goes through `clip_polygon_bounds` (empty results dropped), `unbounded` is false,
 * `VERTEX_NOT_BELOW_LIGHT` is not emitted and rays / checks exist only for shadow points inside the bounds. */
function caster_record(oid: string, lt: LightRecord, rcv: ReceiverRecord, tol: number, sil: readonly number[], P4: readonly Vec4[],
  vertex_names: readonly string[], loops: readonly [Vec4[], readonly number[]][], origins: readonly Origin[] | null,
  vertex_prefix: string): [ShadowRecord, Warning[]] {
  const lid = lt.id, rid = rcv.id, sfx = rcv.suffix;
  const pi = rcv.pi;
  const w_S = P4.map((P) => shadow_w(pi, lt.L, P));
  const finite = w_S.map((w) => w > lt.tol_w);
  const keep = P4.map((P, i) => (finite[i] as boolean) && dot4(P, pi) >= -tol);
  const warnings: Warning[] = [];
  if (!rcv.bounded && sil.length > 0 && !finite.every((f) => f)) warnings.push(make_warning("VERTEX_NOT_BELOW_LIGHT", [oid]));
  const S4 = P4.map((P) => mat4_vec(lt.M, P));
  const S_world = S4.map((S, i): Vec3 => {
    if (!keep[i]) return [0.0, 0.0, 0.0];
    const w = w_S[i] as number;
    return [S[0] / w, S[1] / w, S[2] / w];
  });
  const Q_world = P4.map((P): Vec3 => {
    const Q = foot(pi, P);
    return [Q[0] / Q[3], Q[1] / Q[3], Q[2] / Q[3]];
  });
  let ray_keep = keep;
  if (rcv.bounded) {
    const psi = rcv.psi as Vec4[];
    ray_keep = S4.map((S, i) => (keep[i] as boolean) && psi.every((row) => dot4(S, row) >= -tol * Math.abs(S[3])));
  }
  const out_loops: ShadowRecord["loops"] = [];
  const ground = new Map<string, [string, Vec3]>();
  let unbounded = false;
  for (const [loop4, loop_ids] of loops) {
    let sh = shadow_loop(loop4, lt.M, pi, lt.tol_w, tol, rcv.frame, lt.F);
    if (rcv.bounded) {
      const [V, src] = clip_polygon_bounds(sh.vertices, sh.sources, rcv.psi as Vec4[], rcv.bounds as Vec3[], tol);
      if (V.length === 0) continue;
      sh = { vertices: V, sources: src, unbounded: false, below_ground: sh.below_ground };
    }
    const entries = poly_loop_entries(sh.sources, sh.vertices, loop_ids, origins, oid, lid, ground, sfx, vertex_prefix);
    unbounded = unbounded || sh.unbounded;
    out_loops.push({ vertices: sh.vertices, sources: sh.sources, entries, unbounded: sh.unbounded });
  }
  return [{
    light: lid,
    receiver: rid,
    object: oid,
    keep,
    ray_keep,
    P_world: P4.map((P) => [P[0] / P[3], P[1] / P[3], P[2] / P[3]] as Vec3),
    S_world,
    Q_world,
    w_S,
    shadow_names: sil.map((k) => `${oid}.${vertex_prefix}${k}.shadow.${lid}${sfx}`),
    foot_names: sil.map((k) => `${oid}.${vertex_prefix}${k}.foot${sfx}`),
    vertex_names: [...vertex_names],
    ground_points: [...ground.values()],
    loops: out_loops,
    unbounded,
  }, warnings];
}

/** Shadow record of a polyhedral object on a bounded receiver (contract §5.1.3.2): the solid cut to `π_rᵀX >= 0`
 * (silent; crossings `<obj>.s<k>.<light>.<r>`), the loops shadowed with `M_r` and clipped to the bounds. */
function bounded_object_record(obj: StageAObject, ol: ObjectLightData, lt: LightRecord, rcv: ReceiverRecord, tol: number): [ShadowRecord, Warning[]] {
  const oid = obj.id, lid = lt.id, rid = rcv.id;
  if (!lt.active || ol.light_inside) return [empty_shadow(lid, rid, oid), []];
  const mesh = obj.mesh;
  const V4 = mesh.vertices.map(h4);
  const clipped = obj.clipped.get(rid) ?? null;
  let loop_mesh: Mesh, origins: Origin[] | null, sil_loops: number[][], sil: number[];
  if (clipped === null) {
    loop_mesh = mesh;
    origins = null;
    sil_loops = ol.loops;
    sil = ol.silhouette_vertices;
  } else {
    [loop_mesh, origins] = clipped;
    if (loop_mesh.faces.length === 0) return [empty_shadow(lid, rid, oid), []]; // the whole solid is behind the plane
    const lit_c = face_lit_flags(loop_mesh, lt.L, lt.tol_lit).lit;
    sil_loops = silhouette_loops(loop_mesh, lit_c);
    sil = clipped_silhouette_vertices(loop_mesh, origins, lit_c);
  }
  const V4c = loop_mesh.vertices.map(h4);
  const loops = sil_loops.map((loop) => [loop.map((v) => V4c[v] as Vec4), loop] as [Vec4[], number[]]);
  return caster_record(oid, lt, rcv, tol, sil, sil.map((k) => V4[k] as Vec4), sil.map((k) => obj.point_names[k] as string), loops,
    origins, "v");
}

/** Shadow record of the bounded receiver `plate` (an opaque plate) on the receiver `rcv` (contract §5.1.3.2). */
function plate_shadow_record(plate: ReceiverRecord, lt: LightRecord, rcv: ReceiverRecord, tol: number): [ShadowRecord, Warning[]] {
  const pid = plate.id, lid = lt.id, rid = rcv.id;
  if (!lt.active || !(plate.casts.get(lid) ?? false)) return [empty_shadow(lid, rid, pid), []];
  const B4 = plate.bounds4 as Vec4[];
  if (B4.every((b) => Math.abs(dot4(b, rcv.pi)) <= tol)) return [empty_shadow(lid, rid, pid), []]; // coplanar: casts nothing
  const plate_light = plate.lights.find((p) => p.id === lid) as LightRecord;
  const loop = plate_loop(plate.bounds as Vec3[], plate.pi, lt.L, plate_light.tol_w);
  if (loop === null) return [empty_shadow(lid, rid, pid), []];
  const [loop4, ids] = loop;
  const range = B4.map((_b, j) => j);
  return caster_record(pid, lt, rcv, tol, range, B4, range.map((j) => `${pid}.b${j}`), [[loop4, ids]], null, "b");
}

/** The records of one receiver not produced by the v2 ground code (contract §5.1.3.1): on a bounded receiver every
 * object, and on every receiver the other bounded receivers as plates. Returns `light index -> records`. */
function shadow_records_for_receiver(rcv: ReceiverRecord, objects: readonly StageAObject[], receivers: readonly ReceiverRecord[], tol: number,
  warnings: Warning[]): Map<number, ShadowRecord[]> {
  const out = new Map<number, ShadowRecord[]>();
  const push = (li: number, rec: ShadowRecord): void => {
    let l = out.get(li);
    if (l === undefined) out.set(li, (l = []));
    l.push(rec);
  };
  if (rcv.bounded) {
    for (const obj of objects) {
      if (obj.analytic !== null) {
        for (const rec of stage_a_object(obj, rcv.lights, rcv, tol, warnings, is_multi(rcv.lights))) {
          push(rcv.lights.findIndex((lt) => lt.id === rec.light), rec);
        }
        continue;
      }
      rcv.lights.forEach((lt, li) => {
        const [rec, w] = bounded_object_record(obj, obj.lights.get(lt.id) as ObjectLightData, lt, rcv, tol);
        warnings.push(...w);
        push(li, rec);
      });
    }
  }
  for (const plate of receivers) {
    if (!plate.bounded || plate.id === rcv.id) continue;
    rcv.lights.forEach((lt, li) => {
      const [rec, w] = plate_shadow_record(plate, lt, rcv, tol);
      warnings.push(...w);
      push(li, rec);
    });
  }
  return out;
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
  // construction rays (contract §2.7): only rows with P, S, Q all in front; M4 (§5.1.3.3): on a bounded receiver only
  // shadow points inside the bounds (`ray_keep`); M5 (§5.2.4): `ray_vertices` when the record carries it
  const ray_keep = rec.ray_keep ?? rec.keep;
  const rows_ok: number[] = [];
  rec.keep.forEach((k, i) => {
    if (k && (nuP[i] as number) >= 0.0 && (nuS[i] as number) >= 0.0 && (nuQ[i] as number) >= 0.0 && (ray_keep[i] as boolean)
      && (rec.ray_vertices === undefined || (rec.ray_vertices[i] as boolean))) rows_ok.push(i);
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
      // the §3.1 `rays` list: the foot names are the records' `foot_names` (`<base>.foot[.<r>]`, M4 / M6)
      for (const kind of kinds_of_rays) rays.push([kind, kind === "L" ? name : (rec.foot_names[i] as string)]);
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
 * One light's construction block (contract §2.7, §5.1.5, §5.4.14 (c); port of `multilight.construction_block`):
 * `light` is the stage-B record of the default receiver, `receiver_lights.get(<r>)` the stage-B records of every other
 * receiver (one per light, scene order), `shadows` the stage-B records. The flat `rays` / `checks` / `segments`
 * concatenate that light's records on the default receiver in `shadows[]` order; `per_receiver[<r>]` those on
 * receiver `r`. For one light this is the v1 / M4 `construction` block; the per-light `constructions` map of §5.3.5
 * is a loop around it.
 */
export function construction_block(light: LightStageB, shadows: readonly ShadowStageB[],
  receiver_lights: ReadonlyMap<string, readonly LightStageB[]> = new Map(), default_id: string | null = null): ConstructionStageB {
  const lid = light.id;
  const own = shadows.filter((s) => (default_id === null || s.receiver === default_id) && s.light === lid);
  const block: ConstructionStageB = {
    light_point: light.light_point.point,
    light_point_at_infinity: light.light_point.at_infinity,
    shadow_vp: light.shadow_vp.point,
    shadow_vp_at_infinity: light.shadow_vp.at_infinity,
    rays: own.flatMap((s) => s.rays),
    checks: own.flatMap((s) => s.checks),
    segments: own.flatMap((s) => s.segments),
    per_receiver: new Map(),
  };
  for (const [rid, recs] of receiver_lights) {
    const lt_r = recs.find((r) => r.id === lid);
    if (lt_r === undefined) continue;
    const own_r = shadows.filter((s) => s.receiver === rid && s.light === lid);
    block.per_receiver.set(rid, {
      shadow_vp: lt_r.shadow_vp.point,
      shadow_vp_at_infinity: lt_r.shadow_vp.at_infinity,
      rays: own_r.flatMap((s) => s.rays),
      checks: own_r.flatMap((s) => s.checks),
      segments: own_r.flatMap((s) => s.segments),
    });
  }
  return block;
}

/** `project_light` of a light record of a receiver other than `receivers[0]` (contract §5.1.5): `F'_r = P·F_r`;
 * `SHADOW_VP_AT_INFINITY` carries the ids `[light, receiver]`. */
function project_receiver_light(lt: LightRecord, rcv: ReceiverRecord, cam: CameraRecord, tol: number): [LightStageB, Warning[]] {
  const [lrec, w0] = project_light(lt, cam, tol);
  const w = w0.filter((x) => x.code !== "SHADOW_VP_AT_INFINITY");
  if (lrec.shadow_vp.at_infinity !== null) w.push(make_warning("SHADOW_VP_AT_INFINITY", [lt.id, rcv.id]));
  lrec.receiver = rcv.id;
  lrec.suffix = rcv.suffix;
  return [lrec, w];
}

/** The camera-free §5.1.7 `receivers[]` entry `{id, plane, bounds, lit, casts}`. */
function receiver_doc_entry(rcv: ReceiverRecord): ReceiverDocEntry {
  const lit: Record<string, boolean> = {}, casts: Record<string, boolean> = {};
  for (const [lid, v] of rcv.lit) lit[lid] = v;
  for (const [lid, v] of rcv.casts) casts[lid] = v;
  return {
    id: rcv.id,
    plane: [rcv.pi[0] + 0, rcv.pi[1] + 0, rcv.pi[2] + 0, rcv.pi[3] + 0],
    bounds: rcv.bounded ? (rcv.bounds as Vec3[]).map(canonical3) : null,
    lit,
    casts,
  };
}

/** Stage B of a bounded receiver drawn as an opaque plate (contract §5.1.7 / §5.1.8): bounds points `<r>.b<k>`, bounds
 * edges through the §2.2 drawing pipeline, and its unlit camera-facing face as a `form_shadow` entry iff
 * `sign(πᵀL) != sign(n·(C − b0))` with both strictly beyond the tolerance; `POINT_BEHIND_CAMERA [<r>]`. */
function plate_record(rcv: ReceiverRecord, cam: CameraRecord, tol: number): [PlateStageB, Warning[]] {
  const rid = rcv.id;
  const B4 = rcv.bounds4 as Vec4[];
  const k = B4.length;
  const names = B4.map((_b, j) => `${rid}.b${j}`);
  const x_h = B4.map((X) => project(cam, X));
  const behind = B4.map((X) => nu(cam, X) < 0.0);
  const silhouette = [...rcv.casts.values()].some((v) => v);
  const edges: PlateEdge[] = [];
  for (let j = 0; j < k; j++) {
    const near = clip_segment_near(cam, B4[j] as Vec4, B4[(j + 1) % k] as Vec4);
    const r = near === null ? null : clip_segment_rect_h(project(cam, near[0]), project(cam, near[1]), cam.rect);
    edges.push({
      object: rid, from: names[j] as string, to: names[(j + 1) % k] as string, silhouette, back: false, visibility: "visible", runs: [],
      segment: segment_uv(r, r !== null),
    });
  }
  let form: PlateStageB["form_shadow"] = null;
  if (rcv.lights.length > 0) {
    const lt = rcv.lights[0] as LightRecord;
    const light_side = lt.pi_L;
    const b0 = (rcv.bounds as Vec3[])[0] as Vec3;
    const n = rcv.pi;
    const cam_side = n[0] * (cam.C[0] - b0[0]) + n[1] * (cam.C[1] - b0[1]) + n[2] * (cam.C[2] - b0[2]);
    if (Math.abs(light_side) > lt.tol_w && Math.abs(cam_side) > tol && (light_side > 0.0) !== (cam_side > 0.0)) {
      const poly = project_polygon(cam, B4);
      form = {
        object: rid, faces: [[...names]], terminator: [],
        polygons: poly.length >= 3 ? [poly.map((p) => [p[0] + 0, p[1] + 0] as Vec2)] : [],
      };
    }
  }
  const warnings = behind.some((b) => b) ? [make_warning("POINT_BEHIND_CAMERA", [rid])] : [];
  return [{
    id: rid, point_names: names, world: (rcv.bounds as Vec3[]).map(canonical3), image_h: x_h, behind, edges, form_shadow: form,
  }, warnings];
}

/**
 * Stage B: project stage-A geometry with the scene camera or an override (contract §3, §5.1.5). `B.A = A`;
 * `lights` are the projections for the default receiver, `receiver_lights` those of every other receiver (`F'_r`),
 * `plates` the projected bounded receivers, `construction.per_receiver[<r>]` the rays / checks / segments of the
 * records on receiver `r`. `umbra` is the M6 switch (a later part of phase 2); it has no effect on a single-light
 * scene. `A` is never mutated.
 */
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
  const receivers = A.receivers;
  const default_id = receivers.length > 0 ? (receivers[0] as ReceiverRecord).id : A.receiver.id;
  const key = (lid: string, rid: string): string => JSON.stringify([lid, rid]);
  const by_id = new Map(lights.map((lt) => [key(lt.id, default_id), lt] as const));
  const receiver_lights = new Map<string, LightStageB[]>();
  for (const rcv of receivers.slice(1)) {
    const recs: LightStageB[] = [];
    for (const lt of rcv.lights) {
      const [lrec, w] = project_receiver_light(lt, rcv, cam, tol);
      warnings.push(...w);
      recs.push(lrec);
      by_id.set(key(lt.id, rcv.id), lrec);
    }
    receiver_lights.set(rcv.id, recs);
  }
  const shadows: ShadowStageB[] = [];
  for (const rec of A.shadows) {
    const [s, w] = project_shadow(rec, cam, tol, by_id.get(key(rec.light, rec.receiver)) as LightStageB);
    warnings.push(...w);
    shadows.push(s);
  }
  const plates: PlateStageB[] = [];
  for (const rcv of receivers) {
    if (!rcv.bounded) continue;
    const [prec, w] = plate_record(rcv, cam, tol);
    warnings.push(...w);
    plates.push(prec);
  }
  let construction: ConstructionStageB | null = null;
  if (lights.length > 0) construction = construction_block(lights[0] as LightStageB, shadows, receiver_lights, default_id);
  return {
    camera: cam,
    scene_scale: scale,
    tol,
    objects,
    lights,
    receiver_lights,
    receivers: receivers.map(receiver_doc_entry),
    plates,
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
  // M4 (contract §5.1.7): hidden-line fields with their switch-off values (the hidden-line classification of stage C
  // replaces them, always with fresh lists, when hidden lines are on)
  return { ...entry, ...arc_drawables(a), visibility: "visible", runs: [], hidden_polylines: [] };
}

function segment_uv(seg_h: readonly (readonly number[])[] | null, keep: boolean): [Vec2, Vec2] | null {
  if (!keep || seg_h === null) return null;
  const a = divide(seg_h[0] as readonly number[]), b = divide(seg_h[1] as readonly number[]);
  return [[a[0] + 0, a[1] + 0], [b[0] + 0, b[1] + 0]];
}

/** `F.<light>.<r>` of a receiver other than `receivers[0]` (contract §5.0.4): the light foot on that receiver, a
 * direction point for a directional light, absent when undefined. */
function receiver_light_points(points: Record<string, PointEntry>, lt: LightStageB, rid: string): void {
  if (!lt.F_defined) return;
  const X = lt.F, img = lt.shadow_vp;
  const name = `F.${lt.id}.${rid}`;
  if (lt.type === "point") {
    points[name] = { world: [X[0] / X[3] + 0, X[1] / X[3] + 0, X[2] / X[3] + 0], image: img.point, depth: (lt.F_depth as number) + 0 };
  } else {
    points[name] = { direction: [X[0] + 0, X[1] + 0, X[2] + 0], at_infinity: true, image: img.point };
  }
}

/**
 * Stage C: the spec §6.2 geometry document (contract §3.1, full key listing §5.0.3), canonical floats.
 * `hidden_lines` (§5.1.6.5 / §5.0.7): `null` / `undefined` = `scene.output.hidden_lines`; the effective switch is the
 * document's top-level `hidden_lines`. With it off every `visibility` is `"visible"` and every `runs` /
 * `hidden_polylines` / `polygon_edges` is `[]`. When it is on, `hidden.classify_document(doc, B.A, B)` (src/hidden.ts,
 * §5.1.6.5) fills `visibility` / `runs` / `polygon_edges` / `hidden_polylines` with fresh lists.
 */
export function compose(scene: Scene, B: StageB, hidden_lines?: boolean | null): GeometryDocument {
  const cam = B.camera;
  const points: Record<string, PointEntry> = {};
  const edges: Record<string, unknown>[] = [];
  const outlines: Record<string, unknown>[] = [];
  const form_entries: [number, Record<string, unknown>][] = []; // (object index, entry): the block keeps object order
  const conics_by = new Map<string, Record<string, unknown>[]>();
  const conic_key = (oid: string, lid: string, rid: string): string => JSON.stringify([oid, lid, rid]);
  // curved objects first (their points), then the polyhedral ones, as in the Python compose
  B.objects.forEach((rec, k) => {
    if (!rec.analytic) return;
    finite_points(points, rec.point_names, rec.world, rec.image_h, rec.behind);
    const generators = rec.gen_edges.map((e) => ({
      from: e.from, to: e.to, back: false, segment: segment_uv(e.segment_h, e.keep), visibility: "visible", runs: [],
    }));
    outlines.push({ object: rec.id, generators, conics: rec.outline_arcs.map((a) => conic_doc_entry(a, true)) });
    const term: Record<string, unknown>[] = [];
    for (const items of rec.terminator.values()) {
      for (const it of items) {
        if ("segment" in it) {
          const seg = segment_uv(it.segment_h, it.keep);
          term.push({ segment: [...it.segment], polylines: seg !== null ? [seg] : [], visibility: "visible", runs: [] });
        } else {
          term.push(conic_doc_entry(it));
        }
      }
    }
    if (term.length > 0) form_entries.push([k, { object: rec.id, faces: [], terminator: term, polygons: [] }]);
    for (const [akey, arcs] of rec.shadow_arcs) {
      const [lid, rid] = JSON.parse(akey) as [string, string];
      conics_by.set(conic_key(rec.id, lid, rid), arcs.map((a) => conic_doc_entry(a)));
    }
  });
  B.objects.forEach((rec) => {
    if (!rec.analytic) finite_points(points, rec.point_names, rec.world_lists, rec.image_h, rec.behind);
  });
  B.objects.forEach((rec, k) => {
    if (rec.analytic) return;
    rec.edge_templates.forEach((t, e) => {
      edges.push({
        ...t, silhouette: rec.silhouette[e], back: rec.back[e],
        segment: segment_uv(rec.segments_h[e] ?? null, rec.segment_keep[e] as boolean), runs: [],
      });
    });
    if (rec.form_faces.length > 0) {
      form_entries.push([k, {
        object: rec.id, faces: rec.form_faces, terminator: [],
        polygons: rec.form_polygons.map((poly) => poly.map((p) => [p[0] + 0, p[1] + 0])),
      }]);
    }
  });
  // M4 (contract §5.1.7 / §5.1.8): bounded receivers as plates, after the objects (document order)
  const n_obj = B.objects.length;
  B.plates.forEach((prec, j) => {
    finite_points(points, prec.point_names, prec.world, prec.image_h, prec.behind);
    edges.push(...prec.edges.map((e) => ({ ...e })));
    if (prec.form_shadow !== null) form_entries.push([n_obj + j, prec.form_shadow as unknown as Record<string, unknown>]);
  });
  form_entries.sort((a, b) => a[0] - b[0]);
  const form_shadow = form_entries.map(([, e]) => e);
  for (const lt of B.lights) light_points(points, lt);
  for (const [rid, lts] of B.receiver_lights) for (const lt of lts) receiver_light_points(points, lt, rid);
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
    conics: conics_by.get(conic_key(s.object, s.light, s.receiver)) ?? [],
    unbounded: s.unbounded,
    polygons: s.polygons.map((poly) => poly.map((p) => [p[0] + 0, p[1] + 0])),
    polygon_edges: [],
  }));
  const hz = B.horizon;
  const construction: ConstructionStageB = B.construction ?? {
    light_point: null, light_point_at_infinity: null, shadow_vp: null, shadow_vp_at_infinity: null, rays: [], checks: [], segments: [],
    per_receiver: new Map(),
  };
  const per_head: Record<string, unknown> = {};
  for (const [rid, blk] of construction.per_receiver) {
    per_head[rid] = { shadow_vp: blk.shadow_vp, shadow_vp_at_infinity: blk.shadow_vp_at_infinity };
  }
  const effective = hidden_lines === undefined || hidden_lines === null ? scene.output.hidden_lines === true : Boolean(hidden_lines);
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
    per_receiver: per_head,
    hidden_lines: effective,
    receivers: B.receivers.map((r) => ({ ...r })),
    horizon: {
      v_mm: hz.v_mm,
      line: [...hz.line],
      segment: hz.segment,
      vanishing_points: { x: hz.vanishing_points.x, y: hz.vanishing_points.y, z: hz.vanishing_points.z },
    },
    warnings: B.warnings.map((w) => ({ code: w.code, ids: [...w.ids], message: w.message })),
  });
  const per_receiver: Record<string, unknown> = {};
  for (const [rid, blk] of construction.per_receiver) {
    per_receiver[rid] = {
      ...(head.per_receiver as Record<string, Record<string, unknown>>)[rid],
      rays: [...blk.rays],
      checks: [...blk.checks],
      segments: [...blk.segments],
    };
  }
  const { per_receiver: _per, ...rest } = head;
  const doc = {
    ...rest,
    construction: {
      ...head.construction,
      rays: [...construction.rays],
      checks: [...construction.checks],
      segments: [...construction.segments],
      per_receiver,
    },
    points,
    edges,
    shadows,
    form_shadow,
    outlines,
  } as unknown as GeometryDocument;
  // M4 (contract §5.1.6.5): the sampled hidden-line removal of stage C
  if (effective) classify_document(doc, B.A, B);
  return doc;
}

/** Run stages A, B, C and write the SVG with the scene's layer subset (contract §3, §5.0.7): `hidden_lines` /
 * `hidden_style` override `scene.output` (`null` / `undefined` = the scene's values); `umbra` (M6) is passed to
 * `project_scene`. */
export function render(scene: Scene, camera?: unknown, hidden_lines?: boolean | null, hidden_style?: string | null,
  umbra = true): { geometry: GeometryDocument; svg: string } {
  const A = shadow_geometry(scene);
  const B = project_scene(scene, A, camera, umbra);
  const doc = compose(scene, B, hidden_lines);
  const style = hidden_style ?? scene.output.hidden_style ?? "dashed";
  return { geometry: doc, svg: write_svg(doc, scene.output.layers, style) };
}
