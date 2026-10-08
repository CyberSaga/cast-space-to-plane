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
import type { ArcRecord, CurvedStageB, CurvedStore, LoopEntry, ReceiverRecordLike, ShadowRecord } from "./curved.js";
import type { GeometryDocument } from "./document.js";
import { SceneError, make_warning, merge_warnings } from "./errors.js";
import type { Warning } from "./errors.js";
import { TOL_DIR, row_max_abs, scene_scale, tolerance } from "./homogeneous.js";
import { face_lit_flags, light_vector, lit_value, silhouette_loops } from "./light.js";
import { classify_document } from "./hidden.js";
import { NotManifoldError } from "./mesh.js";
import { MESH_MAX_RAYS, inherit_edge_smooth } from "./meshprep.js";
import type { Mesh } from "./mesh.js";
import {
  assemble_form_shadow, construction_block, construction_blocks, construction_doc, form_table, is_multi, plate_form_lights,
  plate_silhouette_lights, silhouette_lights, split_form, umbra_entries,
} from "./multilight.js";
import type { FormItem, UmbraStageEntry } from "./multilight.js";
import { canonical } from "./output/geometry_json.js";
import { write_svg } from "./output/svg.js";
import { build_object, point_inside_solid } from "./primitives.js";
import type { EdgeTemplate, ObjectRecord } from "./primitives.js";
import { validate_camera } from "./scene.js";
import type { Light, Receiver, Scene } from "./scene.js";
import {
  arc_level, bounds_functionals, clip_mesh_to_plane, clip_polygon_bounds, foot, light_plane_level, mat4_vec, plate_loop, receiver_frame,
  shadow_loop, shadow_matrix, shadow_w,
} from "./shadow.js";
import type { Origin, ShadowLoop, Source, VertexTag } from "./shadow.js";
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
  /** M5 (contract §5.2.4): the two faces of the edge differ in `lit(n_f, p, (C, 1))` (mesh edges only use it). */
  camera_silhouette: boolean[];
  silhouette: boolean[];
  segments_h: ([Vec3, Vec3] | null)[];
  segment_keep: boolean[];
  form_faces: string[][];
  form_polygons: Vec2[][];
  /** M6 (contract §5.3.3, `N >= 2` only): per edge the lights for which it is a silhouette edge (scene order). */
  silhouette_lights?: string[][];
  /** M6 (`N >= 2` only): per light `[faces, polygons]` of its unlit faces, sharing the drawables of `form_polygons`. */
  form_by_light?: Map<string, [string[][], Vec2[][]]>;
  /** M6 (`N >= 2` only): `[faces, polygons]` of the faces unlit by every light. */
  form_core?: [string[][], Vec2[][]];
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
  /** M6 (contract §5.3.3, `N >= 2` only): the lights for which the plate casts. */
  silhouette_lights?: string[];
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
  /** M6 (contract §5.1.8, §5.3.3, `N >= 2` only): per light its single-light form-shadow entry of the plate. */
  form_by_light?: Map<string, { faces: string[][]; polygons: Vec2[][]; terminator: never[] }>;
  /** M6 (`N >= 2` only): the plate as a core face (camera side decided, no light on it), else `null`. */
  form_core?: { faces: string[][]; polygons: Vec2[][] } | null;
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
  /** M6 (contract §5.3.3, §5.3.4; `N >= 2` only): the light ids (scene order), one construction block per light
   * (`construction` is the first light's, the same object) and the umbra entries (`polygons` `null` when
   * `project_scene(..., umbra = false)`). */
  light_ids?: string[];
  constructions?: Map<string, ConstructionStageB>;
  umbra?: UmbraStageEntry[];
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
    // M5 §5.2.5: a fallback (non-manifold) mesh has no silhouette loops (its edge_faces are only [f_min, f_max]); its
    // shadow is the per-face union of fallback_shadow_record
    loops: obj.fallback ? [] : silhouette_loops(mesh, lit),
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
  const tol_c = contact_tol(obj, tol);
  const mesh = obj.mesh;
  const oid = obj.id, lid = lt.id;
  const V4 = mesh.vertices.map(h4);
  let loop_mesh: Mesh, origins: Origin[] | null, sil_loops: number[][], sil: number[], edge_sil: boolean[], lit_c: boolean[];
  if (obj.ground_mesh === null || obj.ground_mesh === undefined) {
    loop_mesh = mesh;
    origins = null;
    sil_loops = ol.loops;
    lit_c = ol.lit;
    sil = ol.silhouette_vertices;
    edge_sil = ol.edge_silhouette;
  } else {
    [loop_mesh, origins] = obj.ground_mesh;
    lit_c = face_lit_flags(loop_mesh, lt.L, lt.tol_lit).lit;
    sil_loops = silhouette_loops(loop_mesh, lit_c);
    edge_sil = loop_mesh.edge_faces.map(([f0, f1]) => lit_c[f0] !== lit_c[f1]);
    sil = clipped_silhouette_vertices(loop_mesh, origins, lit_c);
  }
  const P4 = sil.map((k) => V4[k] as Vec4);
  const w_S = P4.map((P) => shadow_w(pi, lt.L, P));
  const finite = w_S.map((w) => w > lt.tol_w);
  const keep = P4.map((P, i) => (finite[i] as boolean) && dot4(P, pi) >= -tol_c);
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
  const loop_shs = sil_loops.map((loop) => shadow_loop(loop.map((v) => V4c[v] as Vec4), lt.M, pi, lt.tol_w, tol_c));
  const fix = base_turns(loop_mesh, lit_c, lt, pi, null, loop_shs);
  if (fix !== null) { // §5.1 implementation note "Base level of the arcs at infinity"
    const [i, turns] = fix;
    loop_shs[i] = shadow_loop((sil_loops[i] as number[]).map((v) => V4c[v] as Vec4), lt.M, pi, lt.tol_w, tol_c, null, null, turns);
  }
  sil_loops.forEach((loop, li) => {
    // every component of the loop's shadow (several when the loop crosses the light plane 4+ times)
    for (const sh of (loop_shs[li] as ShadowLoop).loops) {
      const entries = poly_loop_entries(sh.sources, sh.vertices, loop, origins, oid, lid, ground);
      unbounded = unbounded || sh.unbounded;
      loops.push({ vertices: sh.vertices, sources: sh.sources, entries, unbounded: sh.unbounded });
    }
  });
  // M5 §5.2.4: rays / checks only for the first MESH_MAX_RAYS feature silhouette vertices of a mesh (silhouette-loop
  // order); every other record draws the rays of all its silhouette vertices
  let ray_vertices: boolean[] | undefined;
  if (obj.type === "mesh") {
    let capped: boolean;
    [ray_vertices, capped] = mesh_ray_vertices(obj, sil, sil_loops, loop_mesh, origins, edge_sil);
    if (capped) warnings.push(make_warning("MESH_RAYS_CAPPED", [oid]));
  }
  return [{
    light: lid,
    receiver: receiver_id,
    object: oid,
    keep,
    ...(ray_vertices === undefined ? {} : { ray_vertices }),
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

/** Receiver-contact tolerance of an object (port of `pipeline._contact_tol`; review fix m5-mesh#0, §5.2 implementation
 * notes): `max(tol, weld_tolerance)` for a `mesh` object, `tol` for every other object. Used only by the receiver-plane
 * predicates: the vertex "below" / "above" tests and the plane clips. */
function contact_tol(obj: StageAObject, tol: number): number {
  if (obj.type === "mesh") return Math.max(tol, Number((obj.shape as { weld_tolerance?: number }).weld_tolerance ?? 0.0));
  return tol;
}

/** Base-level correction of one record (port of `pipeline._base_turns`; §5.1 implementation note "Base level of the arcs
 * at infinity"): `null` when no loop result is unbounded or the drawn winding number at infinity already equals the
 * number of lit faces of `loop_mesh` crossed by the light-plane ray of `light_plane_level`; otherwise `[i, turns]`:
 * re-run `shadow_loop` of loop `i` (the first unbounded one) with `turns`. */
function base_turns(loop_mesh: Mesh, lit: readonly boolean[], lt: LightRecord, pi: Vec4, frame: readonly [Vec3, Vec3] | null,
  loop_shs: readonly ShadowLoop[]): [number, number] | null {
  const first = loop_shs.findIndex((r) => r.unbounded);
  if (first < 0) return null;
  const ref = light_plane_level(loop_mesh, lit, lt.L, pi, lt.tol_w, frame);
  if (ref === null) return null;
  const [theta, count] = ref;
  let drawn = 0;
  for (const r of loop_shs) for (const c of r.loops) drawn += arc_level(c.arcs, theta);
  if (count === drawn) return null;
  return [first, count - drawn];
}

/**
 * `[ray_vertices, capped]` of a mesh shadow record (contract §5.2.4 [decision]). Candidates are the original silhouette
 * vertices that are endpoints of at least one **feature** silhouette edge of the loop mesh actually used (the object's
 * mesh, or the receiver-clipped mesh whose edges inherit `edge_smooth` through `meshprep.inherit_edge_smooth`; cut-face
 * edges are feature; crossing vertices are never candidates). The first `MESH_MAX_RAYS` in silhouette-loop order (loops
 * in order, vertices in loop order, first occurrence) are selected; the mask is aligned with the record's rows
 * (ascending original index), so the emission order is unchanged. `edge_sil` is the light-silhouette mask of the edges
 * of `loop_mesh` that the shadow record already computed.
 */
function mesh_ray_vertices(obj: StageAObject, sil: readonly number[], sil_loops: readonly (readonly number[])[], loop_mesh: Mesh,
  origins: readonly Origin[] | null, edge_sil: readonly boolean[]): [boolean[], boolean] {
  const mesh = obj.mesh;
  const smooth = origins === null ? (mesh.edge_smooth ?? mesh.edges.map(() => false))
    : inherit_edge_smooth(loop_mesh, origins, mesh, mesh.edge_smooth ?? mesh.edges.map(() => false));
  const candidates = new Set<number>();
  loop_mesh.edges.forEach(([i, j], e) => {
    if (edge_sil[e] && !smooth[e]) {
      candidates.add(i);
      candidates.add(j);
    }
  });
  const order: number[] = [];
  const seen = new Set<number>();
  for (const loop of sil_loops) {
    for (const v of loop) {
      if (!candidates.has(v)) continue;
      const o = origins === null ? v : (origins[v] as Origin);
      if (typeof o === "object" || seen.has(o)) continue;
      seen.add(o);
      order.push(o);
    }
  }
  const selected = new Set(order.slice(0, MESH_MAX_RAYS));
  return [sil.map((k) => selected.has(k)), order.length > MESH_MAX_RAYS];
}

/**
 * Per-face shadow record of a non-manifold mesh (contract §5.2.5), replacing `poly_shadow_record`: the rows are every
 * vertex used by a kept face (ascending), each with its `.shadow` and `.foot` point when finite and above the receiver;
 * `ray_vertices` all false (no rays, checks or segments). Every face that is not parallel to the light (lit or not; an
 * unlit face reversed with `[f0] + f[1:][::-1]` so that the lit side is on the left) goes through `shadow_loop`; a loop
 * with fewer than 3 vertices, or a bounded loop whose receiver-plane area is `<= tol·scale_A`, is dropped. Crossings are
 * named `<obj>.s<k>.<light>` in order of first appearance keyed by the undirected original edge (one point per crossed
 * edge). `rcv` (the M4 / M5 merge note): a bounded receiver; each face loop is shadowed with the receiver frame and cut
 * by `clip_polygon_bounds`, names carry the receiver suffix, every bounds-clip row is a crossing of its own,
 * `VERTEX_NOT_BELOW_LIGHT` is not emitted and `ray_keep` marks the shadow points inside the bounds. `null` = the
 * unbounded ground.
 */
function fallback_shadow_record(obj: StageAObject, ol: ObjectLightData, lt: LightRecord, pi: Vec4, tol: number, receiver_id: string,
  rcv: ReceiverRecord | null = null): [ShadowRecord, Warning[]] {
  const mesh = obj.mesh;
  const oid = obj.id, lid = lt.id;
  const bounded = rcv !== null && rcv.bounded;
  const sfx = rcv !== null ? rcv.suffix : "";
  const V4 = mesh.vertices.map(h4);
  const id_set = new Set<number>();
  for (const f of mesh.faces) for (const v of f) id_set.add(v);
  const ids = [...id_set].sort((a, b) => a - b);
  const P4 = ids.map((k) => V4[k] as Vec4);
  const tol_c = contact_tol(obj, tol);
  const w_S = P4.map((P) => shadow_w(pi, lt.L, P));
  const finite = w_S.map((w) => w > lt.tol_w);
  const keep = P4.map((P, i) => (finite[i] as boolean) && dot4(P, pi) >= -tol_c);
  const warnings: Warning[] = [];
  // the fallback analogue of "some silhouette vertex": a vertex of a face that is not parallel to the light, i.e. one
  // that can reach a shadow loop (light-parallel faces are skipped below; the M5 note "Fallback VERTEX_NOT_BELOW_LIGHT")
  const in_loop_faces = new Set<number>();
  mesh.faces.forEach((f, fi) => {
    if (!ol.parallel[fi]) for (const v of f) in_loop_faces.add(v);
  });
  if (!bounded && ids.some((k, i) => in_loop_faces.has(k) && !finite[i])) warnings.push(make_warning("VERTEX_NOT_BELOW_LIGHT", [oid]));
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
  const nn = Math.sqrt(pi[0] * pi[0] + pi[1] * pi[1] + pi[2] * pi[2]);
  const n: Vec3 = [pi[0] / nn, pi[1] / nn, pi[2] / nn];
  const area_tol = tol * (obj.mesh_scale_A ?? 1.0);
  const loops: ShadowRecord["loops"] = [];
  const ground = new Map<string, [string, Vec3]>();
  let unbounded = false;
  mesh.faces.forEach((face, fi) => {
    if (ol.parallel[fi]) return;
    const cyc = ol.lit[fi] ? [...face] : [face[0] as number, ...face.slice(1).reverse()];
    const pts = cyc.map((v) => V4[v] as Vec4);
    const face_sh = rcv === null ? shadow_loop(pts, lt.M, pi, lt.tol_w, tol_c)
      : shadow_loop(pts, lt.M, pi, lt.tol_w, tol_c, rcv.frame, lt.F);
    // every component of the face's shadow (several when a concave face crosses the light plane 4+ times)
    for (const comp of face_sh.loops) {
      let sh: { vertices: Vec4[]; sources: Source[]; unbounded: boolean } = comp;
      if (bounded) {
        const [V, src] = clip_polygon_bounds(sh.vertices, sh.sources, (rcv as ReceiverRecord).psi as Vec4[], (rcv as ReceiverRecord).bounds as Vec3[], tol);
        sh = { vertices: V, sources: src, unbounded: false };
      }
      const verts = sh.vertices;
      if (verts.length < 3) continue;
      if (!sh.unbounded) {
        // ½·n̂·Σ X_i × X_{i+1} (np.sum over axis 0: a sequential sum per component; the M5 note "Fallback area test")
        const X = verts.map((v): Vec3 => [v[0] / v[3], v[1] / v[3], v[2] / v[3]]);
        let s0 = 0, s1 = 0, s2 = 0;
        X.forEach((a, k) => {
          const b = X[(k + 1) % X.length] as Vec3;
          s0 += a[1] * b[2] - a[2] * b[1];
          s1 += a[2] * b[0] - a[0] * b[2];
          s2 += a[0] * b[1] - a[1] * b[0];
        });
        const area = 0.5 * (n[0] * s0 + n[1] * s1 + n[2] * s2);
        if (Math.abs(area) <= area_tol) continue;
      }
      const entries: LoopEntry[] = [];
      sh.sources.forEach((src, row) => {
        if (is_tag(src)) {
          if (src.kind === "ground" || src.kind === "bounds") {
            let key: string;
            if (src.kind === "ground") {
              const i = cyc[(src.i as VertexTag).index] as number, j = cyc[(src.j as VertexTag).index] as number;
              key = `e:${Math.min(i, j)},${Math.max(i, j)}`;
            } else { // a bounds-clip crossing or anchor (M4 §5.1.3.3): a point of its own
              key = `clip:${ground.size}`;
            }
            let g = ground.get(key);
            if (g === undefined) {
              const X = verts[row] as Vec4;
              g = [`${oid}.s${ground.size}.${lid}${sfx}`, [X[0] / X[3], X[1] / X[3], X[2] / X[3]]];
              ground.set(key, g);
            }
            entries.push(g[0]);
          } else { // a direction vertex (w = 0)
            const d = verts[row] as Vec4;
            entries.push({ direction: [d[0] + 0, d[1] + 0, d[2] + 0] });
          }
        } else {
          entries.push(`${oid}.v${cyc[src.index] as number}.shadow.${lid}${sfx}`);
        }
      });
      unbounded = unbounded || sh.unbounded;
      loops.push({ vertices: verts, sources: sh.sources, entries, unbounded: sh.unbounded });
    }
  });
  const rec: ShadowRecord = {
    light: lid,
    receiver: receiver_id,
    object: oid,
    keep,
    ray_vertices: ids.map(() => false),
    P_world: ids.map((k) => [...(mesh.vertices[k] as Vec3)] as Vec3),
    S_world,
    Q_world,
    w_S,
    shadow_names: ids.map((k) => `${oid}.v${k}.shadow.${lid}${sfx}`),
    foot_names: ids.map((k) => `${oid}.v${k}.foot${sfx}`),
    vertex_names: ids.map((k) => obj.point_names[k] as string),
    ground_points: [...ground.values()],
    loops,
    unbounded,
  };
  if (bounded) {
    const psi = (rcv as ReceiverRecord).psi as Vec4[];
    rec.ray_keep = S4.map((S, i) => (keep[i] as boolean) && psi.every((row) => dot4(S, row) >= -tol * Math.abs(S[3])));
  }
  return [rec, warnings];
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
    warnings.push(...obj.prep_warnings); // M5: MESH_* warnings of the preprocessing
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
    const tol_c = contact_tol(obj, tol);
    if (obj.mesh.vertices.some((v) => dot4(h4(v), pi) < -tol_c)) {
      warnings.push(make_warning("OBJECT_BELOW_RECEIVER", [obj.id]));
      try {
        // M5 §5.2.5: a fallback mesh is never cut (the cut would close its open rim into caps)
        obj.ground_mesh = obj.fallback ? null : clip_mesh_to_plane(obj.mesh, pi, tol_c);
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
      const [rec, w2] = obj.fallback ? fallback_shadow_record(obj, ol, lt, pi, tol, receiver.id)
        : poly_shadow_record(obj, ol, lt, pi, tol, receiver.id);
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
  if (obj.fallback) return null; // M5 §5.2.5 [decision, synthesis]: clip_mesh_to_plane is never called on a fallback mesh
  const tol_c = contact_tol(obj, tol);
  if (!obj.mesh.vertices.some((v) => dot4(h4(v), rcv.pi) < -tol_c)) return null;
  try {
    return clip_mesh_to_plane(obj.mesh, rcv.pi, tol_c);
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
  vertex_prefix: string, tol_contact: number | null = null, level_mesh: [Mesh, readonly boolean[]] | null = null): [ShadowRecord, Warning[]] {
  const lid = lt.id, rid = rcv.id, sfx = rcv.suffix;
  const pi = rcv.pi;
  const tol_c = tol_contact === null ? tol : tol_contact;
  const w_S = P4.map((P) => shadow_w(pi, lt.L, P));
  const finite = w_S.map((w) => w > lt.tol_w);
  const keep = P4.map((P, i) => (finite[i] as boolean) && dot4(P, pi) >= -tol_c);
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
  const loop_shs = loops.map(([loop4]) => shadow_loop(loop4, lt.M, pi, lt.tol_w, tol_c, rcv.frame, lt.F));
  const fix = level_mesh === null ? null : base_turns(level_mesh[0], level_mesh[1], lt, pi, rcv.frame, loop_shs);
  if (fix !== null) { // §5.1 implementation note "Base level of the arcs at infinity"
    const [i, turns] = fix;
    loop_shs[i] = shadow_loop((loops[i] as [Vec4[], readonly number[]])[0], lt.M, pi, lt.tol_w, tol_c, rcv.frame, lt.F, turns);
  }
  loops.forEach(([, loop_ids], li) => {
    // every component of the loop's shadow (several when the loop crosses the light plane 4+ times)
    for (const comp of (loop_shs[li] as ShadowLoop).loops) {
      let sh: { vertices: Vec4[]; sources: Source[]; unbounded: boolean } = comp;
      if (rcv.bounded) {
        const [V, src] = clip_polygon_bounds(sh.vertices, sh.sources, rcv.psi as Vec4[], rcv.bounds as Vec3[], tol);
        if (V.length === 0) continue;
        sh = { vertices: V, sources: src, unbounded: false };
      }
      const entries = poly_loop_entries(sh.sources, sh.vertices, loop_ids, origins, oid, lid, ground, sfx, vertex_prefix);
      unbounded = unbounded || sh.unbounded;
      out_loops.push({ vertices: sh.vertices, sources: sh.sources, entries, unbounded: sh.unbounded });
    }
  });
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
  // M5 §5.2.5 / §5.2.7: per-face shadow_loop + bounds clip on this receiver
  if (obj.fallback) return fallback_shadow_record(obj, ol, lt, rcv.pi, tol, rid, rcv);
  const mesh = obj.mesh;
  const V4 = mesh.vertices.map(h4);
  const clipped = obj.clipped.get(rid) ?? null;
  let loop_mesh: Mesh, origins: Origin[] | null, sil_loops: number[][], sil: number[], edge_sil: boolean[], lit_c: boolean[];
  if (clipped === null) {
    loop_mesh = mesh;
    origins = null;
    sil_loops = ol.loops;
    lit_c = ol.lit;
    sil = ol.silhouette_vertices;
    edge_sil = ol.edge_silhouette;
  } else {
    [loop_mesh, origins] = clipped;
    if (loop_mesh.faces.length === 0) return [empty_shadow(lid, rid, oid), []]; // the whole solid is behind the plane
    lit_c = face_lit_flags(loop_mesh, lt.L, lt.tol_lit).lit;
    sil_loops = silhouette_loops(loop_mesh, lit_c);
    edge_sil = loop_mesh.edge_faces.map(([f0, f1]) => lit_c[f0] !== lit_c[f1]);
    sil = clipped_silhouette_vertices(loop_mesh, origins, lit_c);
  }
  const V4c = loop_mesh.vertices.map(h4);
  const loops = sil_loops.map((loop) => [loop.map((v) => V4c[v] as Vec4), loop] as [Vec4[], number[]]);
  const [rec, warnings] = caster_record(oid, lt, rcv, tol, sil, sil.map((k) => V4[k] as Vec4), sil.map((k) => obj.point_names[k] as string),
    loops, origins, "v", contact_tol(obj, tol), [loop_mesh, lit_c]);
  if (obj.type === "mesh") {
    // M5 §5.2.4: the feature-vertex ray selection on the loop mesh actually used (per object, light, receiver)
    let capped: boolean;
    [rec.ray_vertices, capped] = mesh_ray_vertices(obj, sil, sil_loops, loop_mesh, origins, edge_sil);
    if (capped) warnings.push(make_warning("MESH_RAYS_CAPPED", [oid]));
  }
  return [rec, warnings];
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

/** Stage B of one polyhedral object (the per-object form of the reference's batched `_project_polyhedra`). M6
 * (contract §5.3.3): with `N >= 2` lights `silhouette` is the OR over the lights and `silhouette_lights` lists, per
 * edge, the lights for which it is a silhouette edge; the faces unlit by at least one light are projected once and
 * split into `form_by_light` / `form_core` referencing the same drawables. With one light everything is the v1
 * computation. */
function project_polyhedron(o: StageAObject, cam: CameraRecord, tol: number, light_ids: readonly string[]): PolyStageB {
  const multi = is_multi(light_ids);
  const light_id = light_ids.length > 0 ? (light_ids[0] as string) : null;
  const m = o.mesh;
  const V4 = m.vertices.map(h4);
  const x_h = V4.map((v) => project(cam, v));
  const behind = V4.map((v) => nu(cam, v) < 0.0);
  const C4: Vec4 = [cam.C[0], cam.C[1], cam.C[2], 1.0];
  const face_lit = m.faces.map((_f, k) => lit_value(m.face_normals[k] as Vec3, m.vertices[o.face_first[k] as number] as Vec3, C4) > tol);
  const back = m.edge_faces.map(([f0, f1]) => !face_lit[f0] && !face_lit[f1]);
  const camera_silhouette = m.edge_faces.map(([f0, f1]) => face_lit[f0] !== face_lit[f1]); // M5 §5.2.4 (mesh edges only use it)
  const ol = light_id === null ? undefined : o.lights.get(light_id);
  let silhouette = ol !== undefined ? ol.edge_silhouette : m.edges.map(() => false);
  let sil_lists: string[][] | null = null;
  let table: ReturnType<typeof form_table> | null = null;
  if (multi) { // M6: OR over the lights, and the per-edge light lists (contract §5.3.3)
    [silhouette, sil_lists] = silhouette_lights(light_ids.map((lid) => o.lights.get(lid)?.edge_silhouette ?? null), light_ids, m.edges.length);
    // the faces unlit by at least one light replace the per-light lists
    table = form_table(o, light_ids);
  }
  const segments_h: ([Vec3, Vec3] | null)[] = [];
  const keep: boolean[] = [];
  for (const [i, j] of m.edges) {
    const near = clip_segment_near(cam, V4[i] as Vec4, V4[j] as Vec4);
    const r = near === null ? null : clip_segment_rect_h(project(cam, near[0]), project(cam, near[1]), cam.rect);
    segments_h.push(r);
    keep.push(r !== null);
  }
  const form_idx = table !== null ? table.form_idx : ol !== undefined ? ol.form_idx : [];
  const form_faces = table !== null ? table.form_faces : ol !== undefined ? ol.form_faces : [];
  const form_polygons = form_idx.map((face) => project_polygon(cam, face.map((v) => V4[v] as Vec4)));
  const rec: PolyStageB = {
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
    camera_silhouette,
    silhouette,
    segments_h,
    segment_keep: keep,
    form_faces,
    form_polygons,
  };
  if (table !== null) {
    rec.silhouette_lights = sil_lists as string[][];
    [rec.form_by_light, rec.form_core] = split_form(form_faces, form_polygons, table.masks, table.core, light_ids);
  }
  return rec;
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

/** One light's construction block (contract §2.7, §5.1.5, §5.4.14 (c)): `multilight.construction_block`, re-exported
 * here (phase 1 defined it in this module). */
export { construction_block };

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
  const cam_dict = resolve_camera(scene, camera);
  const cam = camera_matrix(cam_dict, scene.output.canvas_mm);
  const scale = scene_scale(A.vertices, cam.C);
  const tol = tolerance(scale);
  const warnings: Warning[] = [...cam.warnings, ...A.warnings];
  const light_ids = A.lights.map((lt) => lt.id);
  const multi = is_multi(light_ids);
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
      const rec = project_polyhedron(obj, cam, tol, light_ids);
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
    if (multi) plate_multi(prec, rcv, cam, tol, light_ids);
    plates.push(prec);
  }
  let construction: ConstructionStageB | null = null;
  let constructions: Map<string, ConstructionStageB> | null = null;
  if (multi) { // M6 (contract §5.3.3): one M4 construction block per light; construction is the alias
    constructions = construction_blocks(lights, receiver_lights, shadows, default_id);
    construction = constructions.get(light_ids[0] as string) as ConstructionStageB;
  } else if (lights.length > 0) {
    construction = construction_block(lights[0] as LightStageB, shadows, receiver_lights, default_id);
  }
  const out: StageB = {
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
  if (multi) { // M6 (contract §5.3.4): the umbra of every receiver from the stage-B drawables (canonical floats, as
    // the reference's stage-B polygons)
    const drawn = shadows.map((s) => ({
      receiver: s.receiver, light: s.light, polygons: s.polygons.map((poly) => poly.map((p) => [p[0] + 0, p[1] + 0])),
    }));
    out.light_ids = light_ids;
    out.constructions = constructions as Map<string, ConstructionStageB>;
    out.umbra = umbra_entries(out.receivers, drawn, light_ids, scene.output.canvas_mm, Boolean(umbra));
  }
  return out;
}

/** M6 (contract §5.1.8, §5.3.3): a bounded receiver as a one-face polyhedron under `N >= 2` lights — `silhouette_lights`
 * of its bounds edges (the lights for which it casts), its per-light form-shadow entries (`form_by_light`, the
 * single-light rule of each light) and its `form_core` (the camera side decided and no light on it). The face is
 * projected once. */
function plate_multi(prec: PlateStageB, rcv: ReceiverRecord, cam: CameraRecord, tol: number, light_ids: readonly string[]): void {
  const sl = plate_silhouette_lights(rcv.casts, light_ids);
  for (const e of prec.edges) e.silhouette_lights = [...sl];
  const by_id = new Map(rcv.lights.map((lt) => [lt.id, lt] as const));
  const lts = light_ids.filter((lid) => by_id.has(lid)).map((lid) => by_id.get(lid) as LightRecord);
  const b0 = (rcv.bounds as Vec3[])[0] as Vec3;
  const n = rcv.pi;
  const cam_side = n[0] * (cam.C[0] - b0[0]) + n[1] * (cam.C[1] - b0[1]) + n[2] * (cam.C[2] - b0[2]);
  const [flags, core] = plate_form_lights(lts.map((lt) => lt.pi_L), lts.map((lt) => lt.tol_w), cam_side, tol);
  prec.form_by_light = new Map();
  prec.form_core = null;
  if (!(flags.some((f) => f) || core)) return;
  const names = [...prec.point_names];
  const poly = project_polygon(cam, rcv.bounds4 as Vec4[]);
  const polygons: Vec2[][] = poly.length >= 3 ? [poly.map((p) => [p[0] + 0, p[1] + 0] as Vec2)] : [];
  lts.forEach((lt, k) => {
    if (flags[k]) prec.form_by_light?.set(lt.id, { faces: [names], polygons, terminator: [] });
  });
  if (core) prec.form_core = { faces: [names], polygons };
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
  const light_ids = B.constructions !== undefined ? (B.light_ids ?? []) : null; // M6: a multi-light document
  const multi_items = new Map<number, FormItem>(); // M6: object index -> assemble_form_shadow item
  const uv0 = (polys: readonly Vec2[][]): Vec2[][] => polys.map((poly) => poly.map((p) => [p[0] + 0, p[1] + 0] as Vec2));
  // curved objects first (their points), then the polyhedral ones, as in the Python compose
  B.objects.forEach((rec, k) => {
    if (!rec.analytic) return;
    finite_points(points, rec.point_names, rec.world, rec.image_h, rec.behind);
    const generators = rec.gen_edges.map((e) => ({
      from: e.from, to: e.to, back: false, segment: segment_uv(e.segment_h, e.keep), visibility: "visible", runs: [],
    }));
    outlines.push({ object: rec.id, generators, conics: rec.outline_arcs.map((a) => conic_doc_entry(a, true)) });
    const term: Record<string, unknown>[] = [];
    // M6 (contract §5.3.3): in a multi-light document each light's terminator entries form that light's entry
    const term_by_light = light_ids === null ? null : new Map<string, Record<string, unknown>[]>();
    for (const [lid, items] of rec.terminator) {
      const start = term.length;
      for (const it of items) {
        if ("segment" in it) {
          const seg = segment_uv(it.segment_h, it.keep);
          term.push({ segment: [...it.segment], polylines: seg !== null ? [seg] : [], visibility: "visible", runs: [] });
        } else {
          term.push(conic_doc_entry(it));
        }
      }
      if (term_by_light !== null) term_by_light.set(lid, term.slice(start));
    }
    if (term.length > 0 && term_by_light === null) form_entries.push([k, { object: rec.id, faces: [], terminator: term, polygons: [] }]);
    if (term_by_light !== null) {
      multi_items.set(k, {
        object: rec.id, core: null,
        by_light: new Map([...term_by_light].map(([lid, t]) => [lid, { faces: [], polygons: [], terminator: t }] as const)),
      });
    }
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
      const entry: Record<string, unknown> = {
        ...t, silhouette: rec.silhouette[e], back: rec.back[e],
        segment: segment_uv(rec.segments_h[e] ?? null, rec.segment_keep[e] as boolean), runs: [],
      };
      if (rec.type === "mesh") {
        // the two mesh-only edge keys (contract §5.2.4): `smooth` (from the stage-A template) and `camera_silhouette`
        // (stage B); a smooth edge that is not a camera silhouette edge is not a drawable (`segment: null`;
        // `visibility` keeps the template's "visible")
        const cs = rec.camera_silhouette[e] as boolean;
        entry["camera_silhouette"] = cs;
        if (t.smooth === true && !cs) entry["segment"] = null;
      }
      if (light_ids !== null) entry["silhouette_lights"] = [...((rec.silhouette_lights as string[][])[e] as string[])];
      edges.push(entry);
    });
    if (light_ids !== null) { // M6 (contract §5.3.3): the per-light lists and the core of the projected union
      const [fc_faces, fc_polys] = rec.form_core as [string[][], Vec2[][]];
      multi_items.set(k, {
        object: rec.id,
        core: { faces: fc_faces, polygons: uv0(fc_polys) },
        by_light: new Map([...(rec.form_by_light as Map<string, [string[][], Vec2[][]]>)].map(([lid, [f, p]]) =>
          [lid, { faces: f, polygons: uv0(p), terminator: [] }] as const)),
      });
    }
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
    if (light_ids !== null) {
      multi_items.set(n_obj + j, { object: prec.id, core: prec.form_core ?? null, by_light: prec.form_by_light ?? new Map() });
    }
  });
  form_entries.sort((a, b) => a[0] - b[0]);
  let form_shadow: unknown[] = form_entries.map(([, e]) => e);
  let form_core: unknown[] | null = null;
  if (light_ids !== null) { // M6 (contract §5.3.5): light-major per-light entries and the core
    const items = [...multi_items.keys()].sort((a, b) => a - b).map((k) => multi_items.get(k) as FormItem);
    [form_shadow, form_core] = assemble_form_shadow(items, light_ids);
  }
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
  if (light_ids !== null) { // M6 (contract §5.3.5): the keys of multi-light documents only
    const d = doc as unknown as Record<string, unknown>;
    d["form_shadow_core"] = form_core;
    const constructions: Record<string, unknown> = {};
    for (const [lid, blk] of B.constructions as Map<string, ConstructionStageB>) constructions[lid] = construction_doc(blk);
    d["constructions"] = constructions;
    d["umbra"] = (B.umbra ?? []).map((e) => ({ receiver: e.receiver, lights: [...e.lights], polygons: e.polygons }));
  }
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
