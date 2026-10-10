/**
 * The object library of M11 (spec-v0.3 §2, §5.1; contract §5.8.7; D84) — pure, DOM-free data and unit-tested
 * (`web/test/library.test.ts`).
 *
 * `PRESETS` is a data table: adding a preset is adding a row. A tile builds `{id, type, <params>, transform:
 * {position: [x, y, 0.0], rotation_deg: [0.0, 0.0, 0.0]}}` ({@link make_object}); the id comes from
 * `scene_edit.next_id(prefix, …)` and the position from `scene_edit.place_object`. The prism polygons are stored as
 * the contract's 1e-4 literals (counter-clockwise, centroid at the origin, the triangle's apex on `+x`), never
 * computed with `cos` / `sin` at run time.
 *
 * Thumbnails: one inline SVG string per preset, `viewBox="0 0 64 64"`, a line drawing in `currentColor` (fill
 * `currentColor` at `fill-opacity` 0.12) with no hard-coded colour and no script, so it follows the light and dark
 * themes. All eight use one convention, the cabinet oblique projection: `x` to the right, `z` up, and the receding
 * axis `y` drawn 30° up-right at half length; circles become ellipses. They are computed once at module load from
 * the preset's parameters (deterministic strings).
 */

import type { SceneObject, Vec2, Vec3 } from "castplane";

// ------------------------------------------------------------------------------------------------ constants (§5.8.15)

/** Sidebar width (px), the narrow breakpoint (viewport px, `<`) and the narrow width (CSS). */
export const LIB_W_PX = 232;
export const LIB_NARROW_PX = 880;
export const LIB_NARROW_W_CSS = "min(80%, 280px)";
/** Thumbnail size (px) and the longest tile name (characters). */
export const THUMB_PX = 64;
export const TILE_NAME_MAX = 6;

// ------------------------------------------------------------------------------------------------ preset table (§5.8.7)

export type PresetType = "box" | "cylinder" | "sphere" | "cone" | "prism";

export interface PresetParams {
  size?: Vec3;
  radius?: number;
  height?: number;
  polygon?: Vec2[];
}

export interface Preset {
  /** The tile name (display name of the objects it makes; never written to the scene JSON). */
  name: string;
  type: PresetType;
  params: Readonly<PresetParams>;
  /** The id prefix of `next_id` (one of the five fixed words). */
  prefix: PresetType;
  /** Inline SVG markup (`viewBox="0 0 64 64"`, `currentColor`). */
  thumbnail: string;
}

/** 三角柱: side 1.0 (1e-4 literals), centroid `(0, 0)`, apex on `+x`, counter-clockwise. */
export const TRIANGLE: readonly Vec2[] = [[0.5774, 0.0], [-0.2887, 0.5], [-0.2887, -0.5]];
/** 六角柱: circumradius 0.4, first vertex on `+x`, counter-clockwise. */
export const HEXAGON: readonly Vec2[] = [[0.4, 0.0], [0.2, 0.3464], [-0.2, 0.3464], [-0.4, 0.0], [-0.2, -0.3464], [0.2, -0.3464]];

type Row = Omit<Preset, "thumbnail">;

const ROWS: readonly Row[] = [
  { name: "方塊", type: "box", params: { size: [1.0, 1.0, 1.0] }, prefix: "box" },
  { name: "木箱", type: "box", params: { size: [1.2, 0.9, 0.7] }, prefix: "box" },
  { name: "高柱", type: "box", params: { size: [0.6, 0.6, 1.8] }, prefix: "box" },
  { name: "圓柱", type: "cylinder", params: { radius: 0.3, height: 1.2 }, prefix: "cylinder" },
  { name: "球", type: "sphere", params: { radius: 0.5 }, prefix: "sphere" },
  { name: "圓錐", type: "cone", params: { radius: 0.4, height: 1.0 }, prefix: "cone" },
  { name: "三角柱", type: "prism", params: { polygon: TRIANGLE.map((p) => [p[0], p[1]] as Vec2), height: 1.0 }, prefix: "prism" },
  { name: "六角柱", type: "prism", params: { polygon: HEXAGON.map((p) => [p[0], p[1]] as Vec2), height: 1.0 }, prefix: "prism" },
];

/**
 * A new scene object from a preset (§5.8.7): `{id, type, <params>, transform: {position, rotation_deg: [0, 0, 0]}}`,
 * keys in that order, the params deep-copied (the record shares nothing with the table).
 */
export function make_object(preset: Pick<Preset, "type" | "params">, id: string, position: readonly number[]): SceneObject {
  const p = preset.params;
  const obj: SceneObject = { id, type: preset.type } as SceneObject;
  if (p.size !== undefined) obj.size = [p.size[0], p.size[1], p.size[2]];
  if (p.radius !== undefined) obj.radius = p.radius;
  if (p.polygon !== undefined) obj.polygon = p.polygon.map((q) => [q[0], q[1]] as Vec2);
  if (p.height !== undefined) obj.height = p.height;
  obj.transform = { position: [position[0]!, position[1]!, position[2] ?? 0.0], rotation_deg: [0.0, 0.0, 0.0] };
  return obj;
}

// ------------------------------------------------------------------------------------------------ thumbnails (§5.8.7)

/** Cabinet oblique: the receding axis `y` at 30° up-right, half length. */
const OBL_C = 0.5 * Math.cos(Math.PI / 6);
const OBL_S = 0.5 * Math.sin(Math.PI / 6);
/** Drawing area inside the 64 px box (px) and the largest scale (px per metre). */
const FIT_PX = 50;
const MAX_SCALE = 44;
const ARC_SAMPLES = 24;
const FILL = ' fill="currentColor" fill-opacity="0.12"';

/** Oblique image `(X, Y)` of a world point, `Y` up. */
function obl(p: readonly number[]): Vec2 {
  return [p[0]! + OBL_C * p[1]!, p[2]! + OBL_S * p[1]!];
}

/** Is a face with outward normal `n` seen (the projection direction `(−c, 1, −s)` points into the picture)? */
function visible(n: readonly number[]): boolean {
  return -OBL_C * n[0]! + n[1]! - OBL_S * n[2]! < -1e-12;
}

/** The image of the horizontal circle `centre + ρ·(cos t, sin t, 0)`. */
function circle_pt(centre: readonly number[], rho: number, t: number): Vec2 {
  return obl([centre[0]! + rho * Math.cos(t), centre[1]! + rho * Math.sin(t), centre[2]!]);
}

/** The image ellipse of a horizontal circle of radius `ρ`: semi-axes and the major axis' angle (Y up, radians). */
function circle_ellipse(rho: number): { rx: number; ry: number; theta: number } {
  // M = ρ·[[1, c], [0, s]]; M·Mᵀ = ρ²·[[1 + c², c·s], [c·s, s²]]
  const a = 1 + OBL_C * OBL_C, b = OBL_C * OBL_S, d = OBL_S * OBL_S;
  const m = (a + d) / 2, q = Math.sqrt(((a - d) / 2) ** 2 + b * b);
  return { rx: rho * Math.sqrt(m + q), ry: rho * Math.sqrt(m - q), theta: 0.5 * Math.atan2(2 * b, a - d) };
}

function arc(centre: readonly number[], rho: number, t0: number, t1: number): Vec2[] {
  const out: Vec2[] = [];
  for (let i = 0; i <= ARC_SAMPLES; i++) out.push(circle_pt(centre, rho, t0 + ((t1 - t0) * i) / ARC_SAMPLES));
  return out;
}

/** Drawing primitives in oblique coordinates (Y up), mapped to the 64 px box by {@link to_svg}. */
type Shape =
  | { kind: "path"; pts: Vec2[]; closed: boolean; fill: boolean }
  | { kind: "ellipse"; c: Vec2; rx: number; ry: number; theta: number; fill: boolean };

function shape_points(s: Shape): Vec2[] {
  if (s.kind === "path") return s.pts;
  const out: Vec2[] = [];
  const ct = Math.cos(s.theta), st = Math.sin(s.theta);
  for (let i = 0; i < 64; i++) {
    const a = (2 * Math.PI * i) / 64, x = s.rx * Math.cos(a), y = s.ry * Math.sin(a);
    out.push([s.c[0] + x * ct - y * st, s.c[1] + x * st + y * ct]);
  }
  return out;
}

function num(x: number): string {
  const t = (Math.round(x * 100) / 100 + 0).toFixed(2).replace(/\.?0+$/, "");
  return t === "-0" ? "0" : t;
}

function to_svg(shapes: readonly Shape[]): string {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const s of shapes) for (const [x, y] of shape_points(s)) {
    x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
  }
  const k = Math.min(FIT_PX / (x1 - x0), FIT_PX / (y1 - y0), MAX_SCALE);
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  const X = (x: number): number => THUMB_PX / 2 + k * (x - cx);
  const Y = (y: number): number => THUMB_PX / 2 - k * (y - cy);
  const body = shapes.map((s) => {
    const fill = s.fill ? FILL : "";
    if (s.kind === "path") {
      const d = s.pts.map((p, i) => `${i === 0 ? "M" : "L"}${num(X(p[0]))} ${num(Y(p[1]))}`).join("") + (s.closed ? "Z" : "");
      return `<path d="${d}"${fill}/>`;
    }
    const ex = num(X(s.c[0])), ey = num(Y(s.c[1]));
    return `<ellipse cx="${ex}" cy="${ey}" rx="${num(k * s.rx)}" ry="${num(k * s.ry)}" transform="rotate(${num(-s.theta * 180 / Math.PI)} ${ex} ${ey})"${fill}/>`;
  }).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${THUMB_PX} ${THUMB_PX}" width="${THUMB_PX}" height="${THUMB_PX}" ` +
    `aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round">${body}</svg>`;
}

/** A right prism over a counter-clockwise polygon: the top face (filled) and the seen side faces. */
function prism_shapes(poly: readonly Vec2[], h: number): Shape[] {
  const n = poly.length;
  const top: Vec2[] = poly.map((p) => obl([p[0], p[1], h]));
  const out: Shape[] = [{ kind: "path", pts: top, closed: true, fill: true }];
  for (let i = 0; i < n; i++) {
    const a = poly[i]!, b = poly[(i + 1) % n]!;
    const nrm: Vec3 = [b[1] - a[1], a[0] - b[0], 0]; // outward for a counter-clockwise polygon
    if (!visible(nrm)) continue;
    out.push({ kind: "path", pts: [obl([a[0], a[1], h]), obl([a[0], a[1], 0]), obl([b[0], b[1], 0]), obl([b[0], b[1], h])], closed: false, fill: false });
  }
  return out;
}

function box_shapes(size: Vec3): Shape[] {
  const hx = size[0] / 2, hy = size[1] / 2;
  return prism_shapes([[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]], size[2]);
}

/** Parameters `t` of the silhouette points of a vertical extrusion of a horizontal circle (extreme image `X`). */
function side_params(): [number, number] {
  const t = Math.atan(OBL_C); // d/dt (cos t + c·sin t) = 0
  return [t, t + Math.PI];
}

function cylinder_shapes(r: number, h: number): Shape[] {
  const e = circle_ellipse(r);
  const [ta, tb] = side_params(); // ta: right, tb: left
  const front = arc([0, 0, 0], r, tb, ta + 2 * Math.PI); // through t = 3π/2 (the −y side, nearer the viewer)
  return [
    { kind: "path", pts: [circle_pt([0, 0, h], r, tb), ...front, circle_pt([0, 0, h], r, ta)], closed: false, fill: false },
    { kind: "ellipse", c: obl([0, 0, h]), rx: e.rx, ry: e.ry, theta: e.theta, fill: true },
  ];
}

/** The outline (the oblique image of a sphere is the ellipse with shape `r²·Pm·Pmᵀ`, `Pm = [[1, c, 0], [0, s, 1]]`)
 * and the front half of the equator's ellipse, which touches the outline at the same silhouette parameters. */
function sphere_shapes(r: number): Shape[] {
  const a = 1 + OBL_C * OBL_C, b = OBL_C * OBL_S, d = OBL_S * OBL_S + 1;
  const m = (a + d) / 2, q = Math.sqrt(((a - d) / 2) ** 2 + b * b);
  const [ta, tb] = side_params();
  return [
    { kind: "ellipse", c: obl([0, 0, r]), rx: r * Math.sqrt(m + q), ry: r * Math.sqrt(m - q), theta: 0.5 * Math.atan2(2 * b, a - d), fill: true },
    { kind: "path", pts: arc([0, 0, r], r, tb, ta + 2 * Math.PI), closed: false, fill: false },
  ];
}

function cone_shapes(r: number, h: number): Shape[] {
  // tangent points from the apex image, solved in the circle's own parameter (the oblique map is affine)
  const qy = h / (r * OBL_S), qx = -OBL_C * qy; // pre-image of the apex direction in units of r
  const phi = Math.atan2(qy, qx), a = Math.acos(1 / Math.hypot(qx, qy));
  const t1 = phi + a, t2 = phi - a + 2 * Math.PI; // the base arc away from the apex
  const apex = obl([0, 0, h]);
  const rim = arc([0, 0, 0], r, t1, t2);
  return [{ kind: "path", pts: [apex, ...rim], closed: true, fill: true }];
}

function thumbnail_of(row: Row): string {
  const p = row.params;
  switch (row.type) {
    case "box":
      return to_svg(box_shapes(p.size as Vec3));
    case "cylinder":
      return to_svg(cylinder_shapes(p.radius as number, p.height as number));
    case "sphere":
      return to_svg(sphere_shapes(p.radius as number));
    case "cone":
      return to_svg(cone_shapes(p.radius as number, p.height as number));
    case "prism":
      return to_svg(prism_shapes(p.polygon as Vec2[], p.height as number));
  }
}

/** The eight presets of §5.8.7, in tile order. */
export const PRESETS: readonly Preset[] = ROWS.map((row) => ({ ...row, thumbnail: thumbnail_of(row) }));

/** The thumbnail strings, in tile order. */
export const THUMBNAILS: readonly string[] = PRESETS.map((p) => p.thumbnail);

/** The accessible label of a tile: `加入：<name>`. */
export function tile_label(preset: Pick<Preset, "name">): string {
  return `加入：${preset.name}`;
}
