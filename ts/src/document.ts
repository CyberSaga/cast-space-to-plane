/**
 * The spec §6.2 geometry document — the final shape of contract §5.0.3 (§3.1 as amended by M4–M6; contract
 * §5.4.14, phase 2). A single-light scene with the unbounded ground, no `mesh` object and hidden lines off produces
 * the v1 document plus the switch-off values of the M4 keys (`hidden_lines: false`, one `receivers` entry,
 * `construction.per_receiver: {}`, empty `runs` / `hidden_polylines` / `polygon_edges`, every `visibility`
 * `"visible"`). Keys marked "(N ≥ 2)" exist iff the scene has at least two lights; keys marked "(mesh)" exist only on
 * `edges[]` entries of `mesh` objects.
 */

import type { Warning } from "./errors.js";
import type { Vec2, Vec3 } from "./types.js";

export type Segment2 = [Vec2, Vec2];

export type Visibility = "visible" | "hidden" | "partial";

export interface FinitePoint {
  world: Vec3;
  image: Vec2 | null;
  depth: number;
}

export interface DirectionPoint {
  direction: Vec3;
  at_infinity: true;
  image: Vec2 | null;
}

export type PointRecord = FinitePoint | DirectionPoint;

/** One run of a straight drawable (§5.1.7): image fraction `s`, 4-D parameter `t`, length `mm` from its start. */
export interface StraightRun {
  s: Vec2;
  t: Vec2;
  mm: Vec2;
  visible: boolean;
}

/** One run of a conic drawable (§5.1.7): `interval` indexes `visible` (an integer, `INT_KEYS`). */
export interface ConicRun {
  interval: number;
  theta: Vec2;
  mm: Vec2;
  visible: boolean;
}

/** The run record of a drawn shadow-polygon edge (`shadows[].polygon_edges`). */
export interface RunRecord {
  visibility: Visibility;
  runs: StraightRun[];
}

export interface EdgeEntry {
  object: string;
  from: string;
  to: string;
  /** OR over lights. */
  silhouette: boolean;
  back: boolean;
  visibility: Visibility;
  runs: StraightRun[];
  segment: Segment2 | null;
  /** (N ≥ 2): light ids in scene order. */
  silhouette_lights?: string[];
  /** (mesh) */
  smooth?: boolean;
  /** (mesh) */
  camera_silhouette?: boolean;
}

export interface ArcDrawable {
  start: Vec2;
  end: Vec2;
  rx: number;
  ry: number;
  rotation_deg: number;
  large_arc: number;
  sweep: number;
  theta: Vec2;
}

export interface EllipseDrawable {
  centre: Vec2;
  rx: number;
  ry: number;
  rotation_deg: number;
}

export interface ConicDocEntry {
  conic: number[][];
  kind: string;
  arc: { theta0: number; theta1: number } | null;
  circle: { centre: Vec3; e1: Vec3; e2: Vec3; radius: number };
  map: string;
  sampled: boolean;
  which: string;
  visible: Vec2[];
  polylines: Vec2[][];
  arcs: ArcDrawable[];
  ellipses: EllipseDrawable[];
  visibility: Visibility;
  runs: ConicRun[];
  hidden_polylines: Vec2[][];
  /** `outlines[]` only. */
  back?: boolean;
}

export type OutlineEntry = string | { direction: Vec3 };

export interface ShadowEntry {
  light: string;
  receiver: string;
  /** The caster: an object id or (a plate caster) a receiver id. */
  object: string;
  outline: OutlineEntry[];
  loops: OutlineEntry[][];
  conics: ConicDocEntry[];
  unbounded: boolean;
  polygons: Vec2[][];
  /** Parallel to `polygons` when hidden lines are on, `[]` when off. */
  polygon_edges: RunRecord[][];
}

export interface TerminatorSegmentEntry {
  segment: [string, string];
  polylines: Segment2[];
  visibility: Visibility;
  runs: StraightRun[];
}

export interface FormShadowEntry {
  object: string;
  faces: string[][];
  polygons: Vec2[][];
  terminator: (ConicDocEntry | TerminatorSegmentEntry)[];
  /** (N ≥ 2): one entry per (light, object), light-major. */
  light?: string;
}

export interface FormShadowCoreEntry {
  object: string;
  faces: string[][];
  polygons: Vec2[][];
}

export interface GeneratorEntry {
  from: string;
  to: string;
  back: boolean;
  segment: Segment2 | null;
  visibility: Visibility;
  runs: StraightRun[];
}

export interface OutlineObjectEntry {
  object: string;
  generators: GeneratorEntry[];
  conics: ConicDocEntry[];
}

export interface RaySegmentEntry {
  kind: string;
  point: string;
  points: Segment2;
}

/** The per-receiver part of a construction block (`per_receiver[<r>]`, r ≠ receivers[0]). */
export interface ReceiverConstructionBlock {
  shadow_vp: Vec2 | null;
  shadow_vp_at_infinity: Vec2 | null;
  rays: [string, string][];
  checks: { point: string; max_error_mm: number }[];
  segments: RaySegmentEntry[];
}

export interface ConstructionBlock {
  light_point: Vec2 | null;
  light_point_at_infinity: Vec2 | null;
  shadow_vp: Vec2 | null;
  shadow_vp_at_infinity: Vec2 | null;
  rays: [string, string][];
  checks: { point: string; max_error_mm: number }[];
  segments: RaySegmentEntry[];
  per_receiver: Record<string, ReceiverConstructionBlock>;
}

export interface HorizonBlock {
  v_mm: number | null;
  line: Vec3;
  segment: Segment2 | null;
  vanishing_points: { x: Vec2 | null; y: Vec2 | null; z: Vec2 | null };
}

export interface ReceiverEntry {
  id: string;
  plane: [number, number, number, number];
  bounds: Vec3[] | null;
  lit: Record<string, boolean>;
  casts: Record<string, boolean>;
}

export interface UmbraEntry {
  receiver: string;
  /** Active light ids, scene order. */
  lights: string[];
  /** `null` only when `project_scene(..., umbra = false)` was used. */
  polygons: Vec2[][][] | null;
}

export interface GeometryDocument {
  /** The effective switch (scene value or render override). */
  hidden_lines: boolean;
  canvas_mm: Vec2;
  camera: { P: number[][]; C: Vec3; horizon_line: Vec3; principal_point: Vec2 };
  /** Scene order; `receivers[0]` is the default receiver. */
  receivers: ReceiverEntry[];
  points: Record<string, PointRecord>;
  edges: EdgeEntry[];
  /** Order: receiver (scene) → light (scene) → caster (objects in scene order, then the other bounded receivers). */
  shadows: ShadowEntry[];
  form_shadow: FormShadowEntry[];
  /** (N ≥ 2) */
  form_shadow_core?: FormShadowCoreEntry[];
  outlines: OutlineObjectEntry[];
  construction: ConstructionBlock;
  /** (N ≥ 2): `construction === constructions[lights[0].id]`. */
  constructions?: Record<string, ConstructionBlock>;
  /** (N ≥ 2) */
  umbra?: UmbraEntry[];
  /** The ground's line at infinity (eye level), always. */
  horizon: HorizonBlock;
  warnings: Warning[];
}
