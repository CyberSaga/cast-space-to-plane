/**
 * §6.1 layered SVG writer (port of `castplane/output/svg.py`; contract §2.10, §5.4.6): the same text as the Python
 * writer for the same document.
 *
 * Image coordinates `(u, v)` are canvas mm with the origin at the frame centre, `u` right, `v` up; the SVG mapping is
 * `x = u + W/2`, `y = H/2 − v`, `viewBox="0 0 W H"`. The six `<g>` layers are emitted in the fixed order of §2.10;
 * an empty layer is still written as an empty group. Numbers are formatted by `fmt` (= Python `_f`).
 */

import type { GeometryDocument } from "../document.js";
import { cmp_code_points } from "../pyfloat.js";

/** Layer ids in drawing order, bottom to top (contract §2.10). */
export const LAYER_ORDER = ["horizon", "objects", "form_shadow", "cast_shadow", "construction", "labels"] as const;

export const STYLE: Readonly<Record<string, string>> = Object.freeze({
  horizon: 'stroke="#999" stroke-width="0.15" fill="none"',
  horizon_point: 'r="0.6" fill="#999" stroke="none"',
  horizon_text: 'font-size="2.5" fill="#999" font-family="sans-serif" stroke="none"',
  objects: 'stroke="#111" stroke-width="0.3" fill="none" stroke-linecap="round"',
  objects_back: 'stroke="#111" stroke-width="0.2" stroke-dasharray="1.2 0.8" fill="none" stroke-linecap="round"',
  form_shadow: 'fill="#335" fill-opacity="0.18" stroke="none"',
  terminator: 'fill="none" stroke="#335" stroke-width="0.2"',
  cast_shadow: 'fill="#000" fill-opacity="0.3" stroke="#000" stroke-width="0.25" fill-rule="nonzero"',
  cast_shadow_conics: 'fill="none"',
  construction: 'stroke-width="0.15" fill="none"',
  ray_LP: 'stroke="#d33"',
  ray_FQ: 'stroke="#36c"',
  ray_PQ: 'stroke="#3a3"',
  labels: 'font-size="2.2" fill="#444" font-family="sans-serif" stroke="none"',
});

/** Stripped fraction digits of `k / 10000` (`""`, `".0001"`, …, `".9999"`): the table of the fast path of `fmt`. */
const FRAC: readonly string[] = (() => {
  const out = [""];
  for (let k = 1; k < 10000; k++) out.push(("." + String(k).padStart(4, "0")).replace(/0+$/, ""));
  return out;
})();
/** `|x·1e4|` below which, away from a rounding half-way by this margin, `round(x·1e4)` is the exact 4-decimal value. */
const FMT_INT_MAX = 2147483648;
const FMT_HALF_MARGIN = 1e-6;

/**
 * Python `_f`: four decimals (round half to even on the exact binary value, like `"%.4f"`), trailing zeros and a
 * trailing `.` stripped, `-0` -> `0` (contract §5.4.6). Exact ties (`x·32` odd) are rounded with integer arithmetic.
 * The table-driven fast path (contract §5.4.11 D17-b) is the Python `_fmt_bytes` rule: `n = round(x·1e4)` is the
 * correctly rounded value whenever the computed product is farther than `FMT_HALF_MARGIN` from a half-way point (its
 * error is below `2^31·2^-53 ≈ 2.4e-7`); `ts/test/svg.test.ts` proves the identity with the exact reference on 10^5
 * values incl. every tie class.
 */
export function fmt(value: number): string {
  const x = value + 0;
  const y = x * 1e4;
  if (y < FMT_INT_MAX && y > -FMT_INT_MAX) {
    const r = Math.round(y);
    const d = y - r;
    if (d < 0.5 - FMT_HALF_MARGIN && d > -(0.5 - FMT_HALF_MARGIN)) {
      if (r === 0) return "0";
      const a = r < 0 ? -r : r;
      const ip = Math.floor(a / 10000);
      return (r < 0 ? "-" : "") + String(ip) + (FRAC[a - ip * 10000] as string);
    }
  }
  return fmt_exact(x);
}

function fmt_exact(x: number): string {
  let s: string;
  if (!Number.isFinite(x)) return Number.isNaN(x) ? "nan" : x > 0 ? "inf" : "-inf";
  const y = x * 32;
  if (Math.abs(x) >= 1e21) {
    s = BigInt(x).toString() + ".0000";
  } else if (Number.isInteger(y) && Math.abs(y) % 2 === 1) { // pyimod-free: absolute value
    const j = BigInt(Math.abs(y));
    const n2 = j * 625n;
    const f = n2 / 2n;
    const m = f % 2n === 0n ? f : f + 1n; // pyimod-free: BigInt f >= 0
    s = (x < 0 ? "-" : "") + (m / 10000n).toString() + "." + (m % 10000n).toString().padStart(4, "0"); // pyimod-free: BigInt m >= 0
  } else {
    s = x.toFixed(4);
  }
  let end = s.length;
  while (end > 0 && s[end - 1] === "0") end--;
  if (end > 0 && s[end - 1] === ".") end--;
  s = s.slice(0, end);
  if (s === "-0" || s === "") s = "0";
  return s;
}

/** `xml.sax.saxutils.escape`: `&`, `<`, `>`. */
function escape(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/>/g, "&gt;").replace(/</g, "&lt;");
}

/** A double-quoted attribute value: `&`, `<`, `>` and `"`. */
function attr(s: string): string {
  return escape(String(s)).replace(/"/g, "&quot;");
}

function group(gid: string, attrs: string, body: readonly string[]): string {
  const sep = attrs ? " " : "";
  if (body.length === 0) return `<g id="${attr(gid)}"${sep}${attrs}/>`;
  return `<g id="${attr(gid)}"${sep}${attrs}>\n${body.join("\n")}\n</g>`;
}

type UV = readonly number[];

class Canvas {
  readonly W: number;
  readonly H: number;

  constructor(W: number, H: number) {
    this.W = W;
    this.H = H;
  }

  xy(uv: UV): [string, string] {
    return [fmt((uv[0] as number) + this.W / 2.0), fmt(this.H / 2.0 - (uv[1] as number))];
  }

  pair(uv: UV): string {
    const [x, y] = this.xy(uv);
    return `${x},${y}`;
  }

  line(a: UV, b: UV, attrs = ""): string {
    const [x1, y1] = this.xy(a);
    const [x2, y2] = this.xy(b);
    const sep = attrs ? " " : "";
    return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"${sep}${attrs}/>`;
  }

  circle(c: UV, attrs: string): string {
    const [x, y] = this.xy(c);
    return `<circle cx="${x}" cy="${y}" ${attrs}/>`;
  }

  text(p: UV, s: string, attrs = "", dx = 0.8, dy = -0.8): string {
    const [x, y] = this.xy([(p[0] as number) + dx, (p[1] as number) - dy]);
    const sep = attrs ? " " : "";
    return `<text x="${x}" y="${y}"${sep}${attrs}>${escape(s)}</text>`;
  }

  polygon(pts: readonly UV[], attrs = ""): string {
    const coords = pts.map((p) => this.pair(p)).join(" ");
    const sep = attrs ? " " : "";
    return `<polygon points="${coords}"${sep}${attrs}/>`;
  }

  /** One `<path>` whose subpaths are the closed loops. */
  path(loops: readonly (readonly UV[])[]): string {
    const parts = loops.map((pts) => "M " + pts.map((p) => this.pair(p)).join(" L ") + " Z");
    return `<path d="${parts.join(" ")}"/>`;
  }

  polyline(pts: readonly UV[], attrs = ""): string {
    const coords = pts.map((p) => this.pair(p)).join(" ");
    const sep = attrs ? " " : "";
    return `<polyline points="${coords}"${sep}${attrs}/>`;
  }

  /** `<ellipse>` of a drawable in the v-up frame: the rotation changes sign in SVG's y-down frame. */
  ellipse(e: { centre: UV; rx: number; ry: number; rotation_deg: number }, attrs = ""): string {
    const [cx, cy] = this.xy(e.centre);
    const sep = attrs ? " " : "";
    const rot = -e.rotation_deg;
    const transform = Math.abs(rot) > 1e-12 ? ` transform="rotate(${fmt(rot)} ${cx} ${cy})"` : "";
    return `<ellipse cx="${cx}" cy="${cy}" rx="${fmt(e.rx)}" ry="${fmt(e.ry)}"${transform}${sep}${attrs}/>`;
  }

  /** `<path d="M … A rx ry rot large sweep …">`; the sweep flag is flipped and the rotation negated (y-down). */
  arc(a: { start: UV; end: UV; rx: number; ry: number; rotation_deg: number; large_arc: number; sweep: number }, attrs = ""): string {
    const [x1, y1] = this.xy(a.start);
    const [x2, y2] = this.xy(a.end);
    const sweep = Math.trunc(a.sweep) ? 0 : 1;
    const d = `M ${x1} ${y1} A ${fmt(a.rx)} ${fmt(a.ry)} ${fmt(-a.rotation_deg)} ${Math.trunc(a.large_arc)} ${sweep} ${x2} ${y2}`;
    const sep = attrs ? " " : "";
    return `<path d="${d}"${sep}${attrs}/>`;
  }

  diamond(c: UV, r: number, attrs: string): string {
    const c0 = c[0] as number, c1 = c[1] as number;
    return this.polygon([[c0 + r, c1], [c0, c1 + r], [c0 - r, c1], [c0, c1 - r]], attrs);
  }
}

type AnyDoc = GeometryDocument | Record<string, any>;

// ---------------------------------------------------------------------------
// layers
// ---------------------------------------------------------------------------

function layer_horizon(doc: AnyDoc, cv: Canvas): string[] {
  const body: string[] = [];
  const hz = (doc as any).horizon ?? {};
  const seg = hz.segment;
  if (seg) body.push(cv.line(seg[0], seg[1]));
  for (const axis of ["x", "y", "z"]) {
    const vp = (hz.vanishing_points ?? {})[axis];
    if (vp !== null && vp !== undefined) {
      body.push(cv.circle(vp, STYLE["horizon_point"] as string));
      body.push(cv.text(vp, `VP${axis}`, STYLE["horizon_text"] as string));
    }
  }
  const pp = ((doc as any).camera ?? {}).principal_point;
  if (pp !== null && pp !== undefined) {
    body.push(cv.circle(pp, STYLE["horizon_point"] as string));
    body.push(cv.text(pp, "PP", STYLE["horizon_text"] as string));
  }
  return body;
}

function drawables(entry: any, cv: Canvas): string[] {
  const out: string[] = [];
  for (const pl of entry.polylines ?? []) if (pl.length >= 2) out.push(cv.polyline(pl));
  for (const a of entry.arcs ?? []) out.push(cv.arc(a));
  for (const e of entry.ellipses ?? []) out.push(cv.ellipse(e));
  return out;
}

function layer_objects(doc: AnyDoc, cv: Canvas): string[] {
  const per_object = new Map<string, [string[], string[]]>();
  const slot = (oid: string): [string[], string[]] => {
    let s = per_object.get(oid);
    if (s === undefined) per_object.set(oid, (s = [[], []]));
    return s;
  };
  for (const e of (doc as any).edges ?? []) {
    if (e.segment === null || e.segment === undefined) continue;
    const [front, back] = slot(e.object);
    (e.back ? back : front).push(cv.line(e.segment[0], e.segment[1]));
  }
  for (const entry of (doc as any).outlines ?? []) {
    const [front, back] = slot(entry.object);
    for (const g of entry.generators ?? []) {
      if (g.segment !== null && g.segment !== undefined) (g.back ? back : front).push(cv.line(g.segment[0], g.segment[1]));
    }
    for (const c of entry.conics ?? []) (c.back ? back : front).push(...drawables(c, cv));
  }
  const body: string[] = [];
  for (const oid of [...per_object.keys()].sort(cmp_code_points)) {
    const [front, back] = per_object.get(oid) as [string[], string[]];
    const sub: string[] = [];
    if (front.length > 0) sub.push(group(`objects.${oid}.front`, STYLE["objects"] as string, front));
    if (back.length > 0) sub.push(group(`objects.${oid}.back`, STYLE["objects_back"] as string, back));
    body.push(group(`objects.${oid}`, "", sub));
  }
  return body;
}

function layer_form_shadow(doc: AnyDoc, cv: Canvas): string[] {
  const body: string[] = [];
  const points = (doc as any).points ?? {};
  for (const entry of (doc as any).form_shadow ?? []) {
    let polys: UV[][];
    if (entry.polygons !== null && entry.polygons !== undefined) {
      polys = entry.polygons.filter((poly: UV[]) => poly.length >= 3);
    } else {
      polys = [];
      for (const face of entry.faces ?? []) {
        const pts = face.map((n: string) => points[n]?.image ?? null);
        if (pts.length > 0 && pts.every((p: UV | null) => p !== null)) polys.push(pts);
      }
    }
    const sub: string[] = polys.map((poly) => cv.polygon(poly));
    const term: string[] = [];
    for (const t of entry.terminator ?? []) {
      if ("segment" in t && !("polylines" in t)) {
        const [a, b] = t.segment.map((n: string) => points[n]?.image ?? null);
        if (a !== null && b !== null) term.push(cv.line(a, b));
      }
      term.push(...drawables(t, cv));
    }
    const oid = entry.object ?? "";
    if (term.length > 0) sub.push(group(`form_shadow.${oid}.terminator`, STYLE["terminator"] as string, term));
    if (sub.length > 0) body.push(group(`form_shadow.${oid}`, "", sub));
  }
  return body;
}

function layer_cast_shadow(doc: AnyDoc, cv: Canvas): string[] {
  const per_light = new Map<string, string[]>();
  const points = (doc as any).points ?? {};
  for (const sh of (doc as any).shadows ?? []) {
    let polygons = sh.polygons;
    if (polygons === null || polygons === undefined) {
      polygons = [];
      for (const loop of sh.loops ?? []) {
        const pts = loop.map((n: unknown) => (typeof n === "string" ? points[n]?.image ?? null : null));
        if (pts.length >= 3 && pts.every((p: UV | null) => p !== null)) polygons.push(pts);
      }
    }
    const loops = polygons.filter((poly: UV[]) => poly.length >= 3);
    const items: string[] = [];
    if (loops.length > 0) items.push(cv.path(loops));
    const conics: string[] = [];
    for (const entry of sh.conics ?? []) conics.push(...drawables(entry, cv));
    if (conics.length > 0) {
      items.push(group(`cast_shadow.${sh.light ?? ""}.${sh.object ?? ""}.conics`, STYLE["cast_shadow_conics"] as string, conics));
    }
    const light = sh.light ?? "";
    let list = per_light.get(light);
    if (list === undefined) per_light.set(light, (list = []));
    list.push(...items);
  }
  return [...per_light.keys()].sort(cmp_code_points).map((light) => group(`cast_shadow.${light}`, "", per_light.get(light) as string[]));
}

function layer_construction(doc: AnyDoc, cv: Canvas): string[] {
  const body: string[] = [];
  const con = (doc as any).construction ?? {};
  const lp = con.light_point;
  if (lp !== null && lp !== undefined) {
    body.push(cv.circle(lp, 'r="1" fill="none" stroke="#d33"'));
    body.push(cv.text(lp, "L′", 'font-size="2.5" fill="#d33" font-family="sans-serif" stroke="none"', 1.4));
  }
  const fp = con.shadow_vp;
  if (fp !== null && fp !== undefined) {
    body.push(cv.diamond(fp, 1.0, 'fill="none" stroke="#36c"'));
    body.push(cv.text(fp, "F′", 'font-size="2.5" fill="#36c" font-family="sans-serif" stroke="none"', 1.4));
  }
  const drawn = (con.segments ?? []).filter((seg: any) => ["LP", "FQ", "PQ"].includes(seg.kind) && seg.points && seg.points.length === 2);
  for (const kind of ["LP", "FQ", "PQ"]) {
    const lines = drawn.filter((seg: any) => seg.kind === kind).map((seg: any) => cv.line(seg.points[0], seg.points[1]));
    if (lines.length > 0) body.push(group(`construction.${kind}`, STYLE[`ray_${kind}`] as string, lines));
  }
  return body;
}

function partition(s: string, sep: string): [string, string, string] {
  const i = s.indexOf(sep);
  return i < 0 ? [s, "", ""] : [s.slice(0, i), sep, s.slice(i + sep.length)];
}

function layer_labels(doc: AnyDoc, cv: Canvas): string[] {
  const points = (doc as any).points ?? {};
  const top = new Map<string, [number, UV]>();
  const pts: [UV, string][] = [];
  const lf: [UV, string][] = [];
  const names = Object.keys(points).filter((n) => !n.includes(".shadow.") && !n.endsWith(".foot")).sort(cmp_code_points);
  for (const name of names) {
    const p = points[name];
    const img = p.image;
    if (img === null || img === undefined) continue;
    const [oid, , rest] = partition(name, ".");
    if (!rest) continue;
    if ((oid === "L" || oid === "F") && !rest.includes(".")) {
      lf.push([img, name]);
      continue;
    }
    const head = partition(rest, ".")[0];
    if (head.startsWith("og") || (head.slice(0, 1) === "s" && /^[0-9]+$/.test(head.slice(1))) || rest === "foot"
      || oid === "shadow" || rest === "shadow" || rest.endsWith(".shadow")) continue;
    pts.push([img, rest]);
    const z = (p.world ?? [0.0, 0.0, 0.0])[2] as number;
    const t = top.get(oid);
    // strictly higher by more than rounding, else the first name in code-point order keeps the anchor (as svg.py)
    if (t === undefined || z > t[0] + 1e-9 * Math.max(1.0, Math.abs(t[0]))) top.set(oid, [z, img]);
  }
  const texts = (items: [UV, string][], attrs: string, dx: number, dy: number): string[] => items.map(([p, s]) => cv.text(p, s, attrs, dx, dy));
  const body = texts(lf, "", 1.4, 2.4);
  body.push(...texts(pts, "", 0.8, -0.8));
  const ids = [...top.keys()].sort(cmp_code_points);
  body.push(...texts(ids.map((oid) => [(top.get(oid) as [number, UV])[1], oid]), 'font-weight="bold"', 0.8, -3.2));
  return body;
}

const LAYER_BUILDERS: Record<string, [(doc: AnyDoc, cv: Canvas) => string[], string]> = {
  horizon: [layer_horizon, STYLE["horizon"] as string],
  objects: [layer_objects, ""],
  form_shadow: [layer_form_shadow, STYLE["form_shadow"] as string],
  cast_shadow: [layer_cast_shadow, STYLE["cast_shadow"] as string],
  construction: [layer_construction, STYLE["construction"] as string],
  labels: [layer_labels, STYLE["labels"] as string],
};

/**
 * Write the §6.1 SVG of a geometry document; `layers` selects a subset of the six ids (an unknown id throws, the
 * Python `ValueError`). `hidden_style` is the M4 switch (phase 2, §5.4.14); it has no effect on a v1 document.
 */
export function write_svg(doc: AnyDoc, layers?: readonly string[] | null, hidden_style?: string | null): string {
  void hidden_style;
  let selected: string[];
  if (layers === undefined || layers === null) {
    selected = [...LAYER_ORDER];
  } else {
    const unknown = layers.filter((name) => !(LAYER_ORDER as readonly string[]).includes(name));
    if (unknown.length > 0) throw new Error(`unknown SVG layer(s): ${unknown.map(String).join(", ")}`);
    selected = LAYER_ORDER.filter((name) => layers.includes(name));
  }
  const canvas = (doc as any).canvas_mm as number[];
  const W = canvas[0] as number, H = canvas[1] as number;
  const cv = new Canvas(W, H);
  const parts = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    `<svg xmlns="http://www.w3.org/2000/svg" width="${fmt(W)}mm" height="${fmt(H)}mm" viewBox="0 0 ${fmt(W)} ${fmt(H)}">`,
  ];
  for (const name of selected) {
    const [builder, attrs] = LAYER_BUILDERS[name] as [(doc: AnyDoc, cv: Canvas) => string[], string];
    parts.push(group(name, attrs, builder(doc, cv)));
  }
  parts.push("</svg>");
  return parts.join("\n") + "\n";
}
