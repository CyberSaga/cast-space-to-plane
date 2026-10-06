/**
 * The spec §6.2 geometry document (contract §3.1) — phase 1: the literal transcription of the v1 shape
 * (contract §5.4.14; phase 2 extends it to the §5.0.3 listing).
 */

import type { Warning } from "./errors.js";
import type { Vec2, Vec3 } from "./types.js";

export type Segment2 = [Vec2, Vec2];

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

export interface EdgeEntry {
  object: string;
  from: string;
  to: string;
  silhouette: boolean;
  back: boolean;
  visibility: string;
  segment: Segment2 | null;
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
  back?: boolean;
}

export type OutlineEntry = string | { direction: Vec3 };

export interface ShadowEntry {
  light: string;
  receiver: string;
  object: string;
  outline: OutlineEntry[];
  loops: OutlineEntry[][];
  conics: ConicDocEntry[];
  unbounded: boolean;
  polygons: Vec2[][];
}

export interface TerminatorSegmentEntry {
  segment: [string, string];
  polylines: Segment2[];
}

export interface FormShadowEntry {
  object: string;
  faces: string[][];
  polygons: Vec2[][];
  terminator: (ConicDocEntry | TerminatorSegmentEntry)[];
}

export interface GeneratorEntry {
  from: string;
  to: string;
  back: boolean;
  segment: Segment2 | null;
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

export interface ConstructionBlock {
  light_point: Vec2 | null;
  light_point_at_infinity: Vec2 | null;
  shadow_vp: Vec2 | null;
  shadow_vp_at_infinity: Vec2 | null;
  rays: [string, string][];
  checks: { point: string; max_error_mm: number }[];
  segments: RaySegmentEntry[];
}

export interface HorizonBlock {
  v_mm: number | null;
  line: Vec3;
  segment: Segment2 | null;
  vanishing_points: { x: Vec2 | null; y: Vec2 | null; z: Vec2 | null };
}

export interface GeometryDocument {
  canvas_mm: Vec2;
  camera: { P: number[][]; C: Vec3; horizon_line: Vec3; principal_point: Vec2 };
  points: Record<string, PointRecord>;
  edges: EdgeEntry[];
  shadows: ShadowEntry[];
  form_shadow: FormShadowEntry[];
  outlines: OutlineObjectEntry[];
  construction: ConstructionBlock;
  horizon: HorizonBlock;
  warnings: Warning[];
}
