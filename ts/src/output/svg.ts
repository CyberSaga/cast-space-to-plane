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
  if (is_multi_light(doc)) return ml_layer_form_shadow(doc, cv, null); // M6 (contract §5.3.6): a multi-light document
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

/** `cast_shadow.<light>.<object>.<suffix>` for a record on `receivers[0]` and for every record of a v2 document (no
 * `receivers` block), `cast_shadow.<light>.<object>.<receiver>.<suffix>` for a record on any other receiver, so that
 * an object casting on several receivers keeps unique ids (M4 implementation note, §5.1). */
function shadow_subgroup_id(sh: any, first_receiver: string | null, suffix: string): string {
  const rid = sh.receiver;
  const infix = first_receiver === null || rid === undefined || rid === null || rid === first_receiver ? "" : `.${rid}`;
  return `cast_shadow.${sh.light ?? ""}.${sh.object ?? ""}${infix}.${suffix}`;
}

function layer_cast_shadow(doc: AnyDoc, cv: Canvas): string[] {
  if (is_multi_light(doc)) return ml_layer_cast_shadow(doc, cv, null); // M6 (contract §5.3.6): a multi-light document
  const per_light = new Map<string, string[]>();
  const points = (doc as any).points ?? {};
  const receivers = (doc as any).receivers;
  const first_receiver: string | null = Array.isArray(receivers) && receivers.length > 0 ? receivers[0].id : null; // null: a v2 document
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
      items.push(group(shadow_subgroup_id(sh, first_receiver, "conics"), STYLE["cast_shadow_conics"] as string, conics));
    }
    const light = sh.light ?? "";
    let list = per_light.get(light);
    if (list === undefined) per_light.set(light, (list = []));
    list.push(...items);
  }
  return [...per_light.keys()].sort(cmp_code_points).map((light) => group(`cast_shadow.${light}`, "", per_light.get(light) as string[]));
}

/** The `per_receiver` blocks of a construction block in the order of the Python dict: scene order of the receivers
 * (`doc.receivers`, the order `project_scene` inserts them), never `Object.keys` order (contract §5.4.4 (8): integer-like
 * ids would move to the front); keys not named by `doc.receivers` follow in their own order. */
function per_receiver_entries(doc: AnyDoc, con: any): [string, any][] {
  const per = (con.per_receiver ?? {}) as Record<string, any>;
  const out: [string, any][] = [];
  const seen = new Set<string>();
  const receivers = (doc as any).receivers;
  if (Array.isArray(receivers)) {
    for (const r of receivers) {
      if (typeof r?.id === "string" && Object.prototype.hasOwnProperty.call(per, r.id) && !seen.has(r.id)) {
        seen.add(r.id);
        out.push([r.id, per[r.id]]);
      }
    }
  }
  for (const rid of Object.keys(per)) if (!seen.has(rid)) out.push([rid, per[rid]]);
  return out;
}

function layer_construction(doc: AnyDoc, cv: Canvas): string[] {
  if (is_multi_light(doc)) return ml_layer_construction(doc, cv); // M6 (contract §5.3.6): a multi-light document
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
  // M4 (contract §5.0.6): every other receiver's F'_r marker (labelled F′<receiver id>) and its rays go to the same
  // three groups (no per-receiver sub-group)
  const segments: any[] = [...(con.segments ?? [])];
  for (const [rid, blk] of per_receiver_entries(doc, con)) {
    const fpr = blk.shadow_vp;
    if (fpr !== null && fpr !== undefined) {
      body.push(cv.diamond(fpr, 1.0, 'fill="none" stroke="#36c"'));
      body.push(cv.text(fpr, `F′${rid}`, 'font-size="2.5" fill="#36c" font-family="sans-serif" stroke="none"', 1.4));
    }
    segments.push(...(blk.segments ?? []));
  }
  const drawn = segments.filter((seg: any) => ["LP", "FQ", "PQ"].includes(seg.kind) && seg.points && seg.points.length === 2);
  for (const kind of ["LP", "FQ", "PQ"]) {
    const lines = drawn.filter((seg: any) => seg.kind === kind).map((seg: any) => cv.line(seg.points[0], seg.points[1]));
    if (lines.length > 0) body.push(group(`construction.${kind}`, STYLE[`ray_${kind}`] as string, lines));
  }
  return body;
}

/** Some part after the first of the dotted name is `shadow` or `foot` (contract §5.0.4). */
function has_shadow_or_foot_part(name: string): boolean {
  const parts = name.split(".").slice(1);
  return parts.includes("shadow") || parts.includes("foot");
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
  // contract §5.0.4: a name is unlabelled iff a part after the first is "shadow" or "foot" (the receiver suffix may
  // follow "foot")
  const names = Object.keys(points).filter((n) => !((n.includes(".shadow") || n.includes(".foot")) && has_shadow_or_foot_part(n)))
    .sort(cmp_code_points);
  for (const name of names) {
    const p = points[name];
    const img = p.image;
    if (img === null || img === undefined) continue;
    const [oid, , rest] = partition(name, ".");
    if (!rest) continue;
    if (oid === "L" || oid === "F") {
      // L.<light> and F.<light>[.<r>] go through the L/F branch and never set an object's top label
      lf.push([img, name]);
      continue;
    }
    // ground points s<k> and camera outline points og<k> are unlabelled
    const head = partition(rest, ".")[0];
    if (head.startsWith("og") || (head.slice(0, 1) === "s" && /^[0-9]+$/.test(head.slice(1)))) continue;
    pts.push([img, rest]);
    const z = (p.world ?? [0.0, 0.0, 0.0])[2] as number;
    const t = top.get(oid);
    if (t === undefined || z > t[0]) top.set(oid, [z, img]);
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

/** `hidden_style` values of `write_svg` (contract §5.1.8). */
export const HIDDEN_STYLES = ["dashed", "omit"] as const;

/**
 * Write the §6.1 SVG of a geometry document; `layers` selects a subset of the six ids (an unknown id throws, the
 * Python `ValueError`). `hidden_style` (contract §5.1.8 / §5.0.6): an unknown value throws; `"dashed"` draws the hidden
 * runs of a document with `hidden_lines == true` dashed in the `*.hidden` sub-groups, `"omit"` writes those groups
 * empty. A document with `hidden_lines` false (or absent) is written exactly as by the v2 writer.
 */
export function write_svg(doc: AnyDoc, layers?: readonly string[] | null, hidden_style: string | null = "dashed"): string {
  const style = hidden_style ?? "dashed";
  if (!(HIDDEN_STYLES as readonly string[]).includes(style)) {
    throw new Error(`unknown hidden_style '${style}'; expected one of ${HIDDEN_STYLES.join(", ")}`);
  }
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
  const hidden = Boolean((doc as any).hidden_lines);
  for (const name of selected) {
    const [builder, attrs] = LAYER_BUILDERS[name] as [(doc: AnyDoc, cv: Canvas) => string[], string];
    const hidden_builder = HIDDEN_LAYER_BUILDERS[name];
    if (hidden && hidden_builder !== undefined) { // M4 (contract §5.1.8): hidden-run sub-groups
      parts.push(group(name, attrs, hidden_builder(doc, cv, style)));
      continue;
    }
    parts.push(group(name, attrs, builder(doc, cv)));
  }
  parts.push("</svg>");
  return parts.join("\n") + "\n";
}

// ---------------------------------------------------------------------------
// M4: hidden-line runs (contract §5.1.8, §5.0.6)
// ---------------------------------------------------------------------------

/** Stroke colour of each layer's `*.hidden` group (the layer's own stroke colour, contract §5.1.8). */
export const HIDDEN_STROKE: Readonly<Record<string, string>> = Object.freeze({ objects: "#111", form_shadow: "#335", cast_shadow: "#000" });

function hidden_group_style(layer: string): string {
  return `stroke="${HIDDEN_STROKE[layer] as string}" stroke-width="0.15" stroke-dasharray="0.5 0.5" fill="none"`;
}

/** Stroke of the cast-shadow outline runs (the fill paths are then written `stroke="none"`). */
export const OUTLINE_STYLE = 'stroke="#000" stroke-width="0.25"';

type Seg = [UV, UV];

/** Visible and hidden pieces of a drawn straight segment by its `visibility` / `runs` (`segment[0] + s (segment[1] −
 * segment[0])` at the run boundaries, contract §5.1.8). */
function split_runs(seg: readonly UV[], item: any): [Seg[], Seg[]] {
  const vis = item.visibility ?? "visible";
  const s0 = seg[0] as UV, s1 = seg[1] as UV;
  if (vis === "visible") return [[[s0, s1]], []];
  if (vis === "hidden") return [[], [[s0, s1]]];
  const ua = s0[0] as number, va = s0[1] as number, ub = s1[0] as number, vb = s1[1] as number;
  const du = ub - ua, dv = vb - va;
  const shown: Seg[] = [], hidden: Seg[] = [];
  for (const r of item.runs ?? []) {
    const [r0, r1] = r.s as [number, number];
    const a: UV = [r0 === 0.0 ? ua : ua + r0 * du, r0 === 0.0 ? va : va + r0 * dv];
    const b: UV = [r1 === 1.0 ? ub : ua + r1 * du, r1 === 1.0 ? vb : va + r1 * dv];
    (r.visible ? shown : hidden).push([a, b]);
  }
  return [shown, hidden];
}

/** `<layer>.hidden` with one sub-group per `[id, segments, polylines]` (empty under `"omit"`). */
function hidden_group(layer: string, groups: readonly [string, Seg[], UV[][]][], hidden_style: string, cv: Canvas): string {
  const sub = groups.map(([gid, segs, plines]) => {
    const body: string[] = [];
    if (hidden_style !== "omit") {
      for (const [a, b] of segs) body.push(cv.line(a, b));
      for (const pl of plines) if (pl.length >= 2) body.push(cv.polyline(pl));
    }
    return group(`${layer}.hidden.${gid}`, "", body);
  });
  return group(`${layer}.hidden`, hidden_group_style(layer), sub);
}

function conic_hidden(entry: any): UV[][] {
  return ((entry.hidden_polylines ?? []) as UV[][]).filter((pl) => pl.length >= 2);
}

interface ObjectSlot { front: Seg[]; back: Seg[]; extra_front: string[]; extra_back: string[]; hidden: Seg[]; hidden_pl: UV[][] }

/** The objects layer of a document with hidden lines on: `objects.hidden` (sub-groups per object, sorted like the
 * object groups) first, then the v2 object groups with the visible runs only. */
function layer_objects_hidden(doc: AnyDoc, cv: Canvas, hidden_style: string): string[] {
  const per_object = new Map<string, ObjectSlot>();
  const slot = (oid: string): ObjectSlot => {
    let s = per_object.get(oid);
    if (s === undefined) per_object.set(oid, (s = { front: [], back: [], extra_front: [], extra_back: [], hidden: [], hidden_pl: [] }));
    return s;
  };
  for (const e of (doc as any).edges ?? []) {
    if (e.segment === null || e.segment === undefined) continue;
    const s = slot(e.object);
    const [shown, hid] = split_runs(e.segment, e);
    (e.back ? s.back : s.front).push(...shown);
    s.hidden.push(...hid);
  }
  for (const entry of (doc as any).outlines ?? []) {
    const s = slot(entry.object);
    for (const g of entry.generators ?? []) {
      if (g.segment === null || g.segment === undefined) continue;
      const [shown, hid] = split_runs(g.segment, g);
      (g.back ? s.back : s.front).push(...shown);
      s.hidden.push(...hid);
    }
    for (const c of entry.conics ?? []) {
      (c.back ? s.extra_back : s.extra_front).push(...drawables(c, cv));
      s.hidden_pl.push(...conic_hidden(c));
    }
  }
  const ids = [...per_object.keys()].sort(cmp_code_points);
  const groups: [string, Seg[], UV[][]][] = [];
  for (const oid of ids) {
    const s = per_object.get(oid) as ObjectSlot;
    if (s.hidden.length > 0 || s.hidden_pl.length > 0) groups.push([oid, s.hidden, s.hidden_pl]);
  }
  const body = [hidden_group("objects", groups, hidden_style, cv)];
  for (const oid of ids) {
    const s = per_object.get(oid) as ObjectSlot;
    const front = [...s.front.map(([a, b]) => cv.line(a, b)), ...s.extra_front];
    const back = [...s.back.map(([a, b]) => cv.line(a, b)), ...s.extra_back];
    const sub: string[] = [];
    if (front.length > 0) sub.push(group(`objects.${oid}.front`, STYLE["objects"] as string, front));
    if (back.length > 0) sub.push(group(`objects.${oid}.back`, STYLE["objects_back"] as string, back));
    if (sub.length > 0 || s.hidden.length > 0 || s.hidden_pl.length > 0) body.push(group(`objects.${oid}`, "", sub));
  }
  return body;
}

/** The form-shadow layer with hidden lines on: `form_shadow.hidden` first (sub-groups in document order), then the v2
 * entries whose terminator keeps the visible runs only (fills unchanged). */
function layer_form_shadow_hidden(doc: AnyDoc, cv: Canvas, hidden_style: string): string[] {
  if (is_multi_light(doc)) return ml_layer_form_shadow(doc, cv, hidden_style); // M6 (contract §5.3.6, §5.0.6)
  const hidden_groups: [string, Seg[], UV[][]][] = [];
  const body: string[] = [];
  for (const entry of (doc as any).form_shadow ?? []) {
    const oid = entry.object ?? "";
    const polys = ((entry.polygons ?? []) as UV[][]).filter((poly) => poly.length >= 3);
    const sub: string[] = polys.map((poly) => cv.polygon(poly));
    const term: string[] = [], hid: Seg[] = [], hid_pl: UV[][] = [];
    for (const t of entry.terminator ?? []) {
      if ("segment" in t) {
        for (const seg of t.polylines ?? []) {
          if (seg.length !== 2) continue;
          const [shown, h] = split_runs(seg, t);
          term.push(...shown.map((p) => cv.polyline(p)));
          hid.push(...h);
        }
        continue;
      }
      term.push(...drawables(t, cv));
      hid_pl.push(...conic_hidden(t));
    }
    if (term.length > 0) sub.push(group(`form_shadow.${oid}.terminator`, STYLE["terminator"] as string, term));
    if (hid.length > 0 || hid_pl.length > 0) hidden_groups.push([oid, hid, hid_pl]);
    if (sub.length > 0) body.push(group(`form_shadow.${oid}`, "", sub));
  }
  return [hidden_group("form_shadow", hidden_groups, hidden_style, cv), ...body];
}

/** The cast-shadow layer with hidden lines on: `cast_shadow.hidden` (sub-groups per light) first; per record the fill
 * path with `stroke="none"`, the visible conic drawables in `.conics` and the visible outline runs of the drawn polygon
 * edges in `cast_shadow.<light>.<object>[.<r>].outline`. */
function layer_cast_shadow_hidden(doc: AnyDoc, cv: Canvas, hidden_style: string): string[] {
  if (is_multi_light(doc)) return ml_layer_cast_shadow(doc, cv, hidden_style); // M6 (contract §5.3.6, §5.0.6)
  const receivers = (doc as any).receivers;
  const first_receiver: string | null = Array.isArray(receivers) && receivers.length > 0 ? receivers[0].id : null;
  const per_light = new Map<string, string[]>();
  const hidden_by_light = new Map<string, [Seg[], UV[][]]>();
  for (const sh of (doc as any).shadows ?? []) {
    const lid = sh.light ?? "";
    const items: string[] = [];
    const loops = ((sh.polygons ?? []) as UV[][]).filter((poly) => poly.length >= 3);
    if (loops.length > 0) {
      const path = cv.path(loops);
      items.push(path.slice(0, -2) + ' stroke="none"/>');
    }
    const conics: string[] = [], hid_pl: UV[][] = [];
    for (const entry of sh.conics ?? []) {
      conics.push(...drawables(entry, cv));
      hid_pl.push(...conic_hidden(entry));
    }
    if (conics.length > 0) {
      items.push(group(shadow_subgroup_id(sh, first_receiver, "conics"), STYLE["cast_shadow_conics"] as string, conics));
    }
    const shown: Seg[] = [], hid: Seg[] = [];
    const records = (sh.polygon_edges ?? []) as any[][];
    ((sh.polygons ?? []) as UV[][]).forEach((poly, j) => {
      if (poly.length < 3) return;
      const recs = j < records.length ? (records[j] as any[]) : [];
      const n = poly.length;
      for (let e = 0; e < n; e++) {
        const seg = [poly[e] as UV, poly[(e + 1) % n] as UV];
        const rec = e < recs.length ? recs[e] : { visibility: "visible", runs: [] };
        const [a, b] = split_runs(seg, rec);
        shown.push(...a);
        hid.push(...b);
      }
    });
    if (shown.length > 0) {
      items.push(group(shadow_subgroup_id(sh, first_receiver, "outline"), OUTLINE_STYLE, shown.map(([a, b]) => cv.line(a, b))));
    }
    if (hid.length > 0 || hid_pl.length > 0) {
      let h = hidden_by_light.get(lid);
      if (h === undefined) hidden_by_light.set(lid, (h = [[], []]));
      h[0].push(...hid);
      h[1].push(...hid_pl);
    }
    let list = per_light.get(lid);
    if (list === undefined) per_light.set(lid, (list = []));
    list.push(...items);
  }
  const lids = [...hidden_by_light.keys()].sort(cmp_code_points);
  const body = [hidden_group("cast_shadow", lids.map((lid) => [lid, ...(hidden_by_light.get(lid) as [Seg[], UV[][]])]), hidden_style, cv)];
  for (const light of [...per_light.keys()].sort(cmp_code_points)) body.push(group(`cast_shadow.${light}`, "", per_light.get(light) as string[]));
  return body;
}

const HIDDEN_LAYER_BUILDERS: Record<string, (doc: AnyDoc, cv: Canvas, hidden_style: string) => string[]> = {
  objects: layer_objects_hidden,
  form_shadow: layer_form_shadow_hidden,
  cast_shadow: layer_cast_shadow_hidden,
};

// ---------------------------------------------------------------------------
// M6: multi-light layers (contract §5.3.6, §5.0.6; port of `castplane/output/svg_multilight.py`)
// ---------------------------------------------------------------------------
//
// A geometry document is multi-light iff it carries the `constructions` key (`N >= 2` lights, contract §5.3.5); its
// `form_shadow`, `cast_shadow` and `construction` layers (and the two hidden-line builders of the first two) are then
// written by the builders below. `N_act = max(1, number of distinct ids in the union of all umbra[].lights)` is the
// opacity divisor; light sub-groups are ordered by light id in code-point order, object sub-groups keep document order.

/** Style of the `cast_shadow.umbra` sub-group (contract §5.3.6). */
export const UMBRA_STYLE = 'fill="#000" fill-opacity="0.3" stroke="none"';

/** The writer's test for a multi-light document: the `constructions` key (contract §5.3.6). */
export function is_multi_light(doc: AnyDoc): boolean {
  return doc !== null && typeof doc === "object" && Object.prototype.hasOwnProperty.call(doc, "constructions");
}

/** `N_act = max(1, number of distinct ids in the union of all umbra[].lights)` (contract §5.3.6). */
export function n_active(doc: AnyDoc): number {
  const ids = new Set<string>();
  for (const e of ((doc as any).umbra ?? []) as any[]) for (const lid of (e?.lights ?? []) as string[]) ids.add(lid);
  return Math.max(1, ids.size);
}

/** The document's light ids in code-point order (the keys of `constructions`). */
export function multi_light_ids(doc: AnyDoc): string[] {
  return Object.keys((doc as any).constructions ?? {}).sort(cmp_code_points);
}

function ml_opacity(base: number, doc: AnyDoc): string {
  return `fill-opacity="${fmt(base / n_active(doc))}"`;
}

/** `{object: set of face keys}` of `form_shadow_core` (a face key is its name list as JSON, the reference's tuple). */
function ml_core_faces(doc: AnyDoc): Map<string, Set<string>> {
  const out = new Map<string, Set<string>>();
  for (const c of ((doc as any).form_shadow_core ?? []) as any[]) {
    const oid = c.object ?? "";
    let set = out.get(oid);
    if (set === undefined) out.set(oid, (set = new Set()));
    for (const f of (c.faces ?? []) as string[][]) set.add(JSON.stringify(f));
  }
  return out;
}

/** The drawable polygons of a per-light entry except the core faces (writer rule, contract §5.3.6; the document keeps
 * them in the entry). `polygons` is parallel to `faces` for polyhedral objects; when it is not (a plate whose face is
 * clipped away), the entry is drawn whole unless every face is a core face. */
function ml_light_polygons(entry: any, core: ReadonlySet<string>): UV[][] {
  const faces = (entry.faces ?? []) as string[][];
  const polygons = (entry.polygons ?? []) as UV[][];
  let polys: UV[][];
  if (polygons.length === faces.length) polys = polygons.filter((_p, k) => !core.has(JSON.stringify(faces[k])));
  else if (faces.length > 0 && faces.every((f) => core.has(JSON.stringify(f)))) polys = [];
  else polys = [...polygons];
  return polys.filter((p) => p.length >= 3);
}

/** Terminator drawables of one entry: `[elements, hidden segments, hidden polylines]` exactly as the single-light
 * writer draws them (hidden runs split off when hidden lines are on). */
function ml_terminator(entry: any, cv: Canvas, hidden: boolean, points: Record<string, any>): [string[], Seg[], UV[][]] {
  const term: string[] = [], hid: Seg[] = [], hid_pl: UV[][] = [];
  for (const t of entry.terminator ?? []) {
    if (hidden) {
      if ("segment" in t) {
        for (const seg of t.polylines ?? []) {
          if (seg.length !== 2) continue;
          const [shown, h] = split_runs(seg, t);
          term.push(...shown.map((p) => cv.polyline(p)));
          hid.push(...h);
        }
        continue;
      }
      term.push(...drawables(t, cv));
      hid_pl.push(...conic_hidden(t));
      continue;
    }
    if ("segment" in t && !("polylines" in t)) { // no drawable: fall back to the named points' images
      const [a, b] = t.segment.map((n: string) => points[n]?.image ?? null);
      if (a !== null && b !== null) term.push(cv.line(a, b));
    }
    term.push(...drawables(t, cv));
  }
  return [term, hid, hid_pl];
}

/** The `form_shadow` layer body of a multi-light document (contract §5.3.6, §5.0.6): (`form_shadow.hidden` iff hidden
 * lines are on) then per light `form_shadow.<light>` (that light's unlit faces minus the core faces, and its
 * terminator), then `form_shadow.core`. `hidden_style` is `null` when the document's hidden lines are off. */
function ml_layer_form_shadow(doc: AnyDoc, cv: Canvas, hidden_style: string | null): string[] {
  const hidden = hidden_style !== null;
  const points = (doc as any).points ?? {};
  const entries = ((doc as any).form_shadow ?? []) as any[];
  const core = ml_core_faces(doc);
  const lids = multi_light_ids(doc);
  const attrs = ml_opacity(0.18, doc);
  const by_light = new Map<string, string[]>(lids.map((lid) => [lid, []] as [string, string[]]));
  const hidden_groups = new Map<string, [Seg[], UV[][]]>(); // object -> (segments, polylines), first-appearance order
  for (const entry of entries) {
    const lid = entry.light ?? "", oid = entry.object ?? "";
    const sub = ml_light_polygons(entry, core.get(oid) ?? new Set()).map((poly) => cv.polygon(poly));
    const [term, hid, hid_pl] = ml_terminator(entry, cv, hidden, points);
    if (term.length > 0) sub.push(group(`form_shadow.${lid}.${oid}.terminator`, STYLE["terminator"] as string, term));
    if (hid.length > 0 || hid_pl.length > 0) {
      let h = hidden_groups.get(oid);
      if (h === undefined) hidden_groups.set(oid, (h = [[], []]));
      h[0].push(...hid);
      h[1].push(...hid_pl);
    }
    if (sub.length > 0) {
      let list = by_light.get(lid);
      if (list === undefined) by_light.set(lid, (list = []));
      list.push(group(`form_shadow.${lid}.${oid}`, "", sub));
    }
  }
  const body: string[] = [];
  if (hidden) {
    body.push(hidden_group("form_shadow", [...hidden_groups].map(([oid, [h, pl]]) => [oid, h, pl] as [string, Seg[], UV[][]]),
      hidden_style as string, cv));
  }
  for (const lid of [...by_light.keys()].sort(cmp_code_points)) body.push(group(`form_shadow.${lid}`, attrs, by_light.get(lid) as string[]));
  const core_body: string[] = [];
  for (const c of ((doc as any).form_shadow_core ?? []) as any[]) {
    const sub = ((c.polygons ?? []) as UV[][]).filter((p) => p.length >= 3).map((poly) => cv.polygon(poly));
    if (sub.length > 0) core_body.push(group(`form_shadow.core.${c.object ?? ""}`, "", sub));
  }
  body.push(group("form_shadow.core", "", core_body));
  return body;
}

/** `cast_shadow.umbra`: one `<path>` per `umbra[]` entry whose `polygons` is a non-empty list (one `M … Z` subpath per
 * piece); entries with `[]` or `null` produce nothing (the group is still written). */
function ml_umbra_group(doc: AnyDoc, cv: Canvas): string {
  const entries = (((doc as any).umbra ?? []) as any[]).filter((e) => Array.isArray(e.polygons) && e.polygons.length > 0);
  return group("cast_shadow.umbra", UMBRA_STYLE, entries.map((e) => cv.path(e.polygons as UV[][])));
}

/** The `cast_shadow` layer body of a multi-light document (contract §5.3.6, §5.0.6): the single-light content with
 * `fill-opacity="<0.3/N_act>"` on every `cast_shadow.<light>` group, then `cast_shadow.umbra` on top. */
function ml_layer_cast_shadow(doc: AnyDoc, cv: Canvas, hidden_style: string | null): string[] {
  const plain: Record<string, any> = { ...(doc as any) };
  delete plain["constructions"];
  const body = hidden_style === null ? layer_cast_shadow(plain, cv) : layer_cast_shadow_hidden(plain, cv, hidden_style);
  const attrs = ml_opacity(0.3, doc);
  const heads = new Set(multi_light_ids(doc).map((lid) => `<g id="${attr(`cast_shadow.${lid}`)}"`));
  const out = body.map((item) => {
    let head = item.split(">", 1)[0] as string;
    if (head.endsWith("/")) head = head.slice(0, -1);
    return heads.has(head) ? `${head} ${attrs}${item.slice(head.length)}` : item;
  });
  out.push(ml_umbra_group(doc, cv));
  return out;
}

/** The `construction` layer body of a multi-light document (contract §5.3.6): one `construction.<light>` group per
 * light (code-point order) holding the single-light markers of that light's construction block (every receiver's
 * `F′_r` included, `per_receiver` in receiver scene order) and its `construction.<light>.LP` / `.FQ` / `.PQ` groups. */
function ml_layer_construction(doc: AnyDoc, cv: Canvas): string[] {
  const body: string[] = [];
  for (const lid of multi_light_ids(doc)) {
    const inner = layer_construction({ construction: (doc as any).constructions[lid], receivers: (doc as any).receivers }, cv);
    const renamed = inner.map((item) => {
      for (const kind of ["LP", "FQ", "PQ"]) {
        const head = `<g id="construction.${kind}"`;
        if (item.startsWith(head)) return `<g id="${attr(`construction.${lid}.${kind}`)}"` + item.slice(head.length);
      }
      return item;
    });
    body.push(group(`construction.${lid}`, "", renamed));
  }
  return body;
}
