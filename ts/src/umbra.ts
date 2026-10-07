/**
 * Umbra (本影) computation: one nonzero scanline kernel (port of `castplane/umbra.py`; contract §5.3.4, §5.3.7; M6,
 * M7 phase 2 §5.4.14).
 *
 * The umbra of a receiver is the intersection of the *drawn* cast-shadow regions of the lights active on it. It is a
 * pure function of `shadows[].polygons`, `umbra[].lights` and `canvas_mm` (canvas mm, exactly the numbers written in
 * the document), so the port recomputes it from the JSON alone (`umbra_from_document`).
 *
 * One kernel, `scan_pieces`, does all the work: a slab decomposition with one nonzero winding counter per group. It is
 * used per record (`record_pieces`: one group, the record's loops) and once per receiver (`umbra_pieces`: one group
 * per active light, the record pieces as input). Every piece is a convex counter-clockwise trapezoid or triangle
 * (`v` up) with an area above `tol_area`; the pieces of one scan have pairwise disjoint interiors.
 *
 * Literal readings shared with the reference (§5.3 implementation notes, M6 step 2): `tol_area = 1e-9 * (D * D)`;
 * "consecutive edges" are edges whose indices **in the input polygon** differ by 1 modulo `n_i`, decided before the
 * horizontal edges are discarded; the line ids of `record_pieces` and the `base_{k,r}` of `umbra_pieces` count every
 * input polygon's `n_i` edges (also of polygons with fewer than three vertices); equal `(line_left, line_right)` keys
 * inside one slab are paired in order (the `m`-th of slab `s + 1` extends the merged piece of the `m`-th of slab `s`).
 * The reference's chunking of the slab loop and of the crossing pairs is a memory device that never changes the
 * output (`tests/test_umbra.py::test_chunk_sizes_are_invisible_in_the_output`): the port processes every slab in one
 * sweep. Every predicate is `>` / `<=` against the tolerances or an exact comparison of snapped values, every order
 * a `(value, index)` order, every emitted float goes through `+ 0`.
 */

/** A `[u, v]` canvas-mm point. */
export type UV = [number, number];
/** The `(line_left, line_right)` line ids of a piece. */
export type Sides = [number, number];

/** `[tol_mm, tol_area]` of contract §5.3.4: `D = 1.5 · max(canvas_w, canvas_h)` (the extent of the extended rectangle
 * of §2.2), `tol_mm = 1e-9 · D`, `tol_area = 1e-9 · (D · D)`. */
export function tolerances(canvas_mm: readonly number[]): [number, number] {
  const w = Number(canvas_mm[0]), h = Number(canvas_mm[1]);
  const D = 1.5 * (h > w ? h : w);
  return [1e-9 * D, 1e-9 * (D * D)];
}

// ---------------------------------------------------------------------------
// small helpers
// ---------------------------------------------------------------------------

/** numpy's float order for sorting: NaN last, `-0 == 0`. */
function cmp_float(a: number, b: number): number {
  if (a < b) return -1;
  if (a > b) return 1;
  const na = a !== a, nb = b !== b;
  if (na !== nb) return na ? 1 : -1;
  return 0;
}

/** `np.sort` of a float list (ascending, NaN last). */
function sorted_floats(values: readonly number[]): number[] {
  return [...values].sort(cmp_float);
}

/** `np.minimum` / `np.maximum` on two floats (the first operand on ties, NaN propagating). */
function npmin(a: number, b: number): number {
  return a <= b || a !== a ? a : b;
}

function npmax(a: number, b: number): number {
  return a >= b || a !== a ? a : b;
}

/** Kept values of the greedy merge of the ascending list `values`: the first value is kept, each following value is
 * kept iff it exceeds the last kept value by more than `tol` (the reference's vectorised form is result-identical). */
function greedy_merge(values: readonly number[], tol: number): number[] {
  const out: number[] = [];
  if (values.length === 0) return out;
  let last = values[0] as number;
  out.push(last);
  for (let t = 1; t < values.length; t++) {
    const x = values[t] as number;
    if (x - last > tol) {
      out.push(x);
      last = x;
    }
  }
  return out;
}

/** `np.searchsorted(a, x, side="left")`: the first index `k` with `a[k] >= x` (`a` ascending). */
function search_left(a: readonly number[], x: number): number {
  let lo = 0, hi = a.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((a[mid] as number) < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** `np.searchsorted(a, x, side="right")`: the first index `k` with `a[k] > x` (`a` ascending). */
function search_right(a: readonly number[], x: number): number {
  let lo = 0, hi = a.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((a[mid] as number) <= x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** `x(y) = u0 + (y − v0)·((u1 − u0)/(v1 − v0))` with the exact-endpoint rule `x(v0) = u0`, `x(v1) = u1` (contract
 * §5.3.4 step 4; the `v1` test wins, as the reference's second `np.where`). */
function x_at(u0: number, v0: number, u1: number, v1: number, y: number): number {
  if (y === v1) return u1;
  if (y === v0) return u0;
  return u0 + (y - v0) * ((u1 - u0) / (v1 - v0));
}

// ---------------------------------------------------------------------------
// the kernel
// ---------------------------------------------------------------------------

/** The flat input of the kernel: the concatenated vertices of the polygons with at least three vertices, their sizes,
 * groups and the concatenated line ids (`_flatten` of the reference). */
interface Flat {
  U: number[];
  V: number[];
  sizes: number[];
  groups: number[];
  line: number[];
}

/** The edge table of steps 1–2 (input order, horizontal edges discarded). */
interface EdgeTable {
  u0: number[];
  v0: number[];
  u1: number[];
  v1: number[];
  dir: number[];
  group: number[];
  line: number[];
  poly: number[];
  local: number[];
  size: number[];
}

/** A scan result: per piece its `nv` (3 or 4) vertices from the canonical start on, and its sides. */
interface ScanOut {
  pieces: UV[][];
  sides: Sides[];
}

const EMPTY_SCAN = (): ScanOut => ({ pieces: [], sides: [] });

function flatten(polygons: readonly (readonly (readonly number[])[])[], groups: readonly number[],
  lines: readonly (readonly number[])[]): Flat | null {
  const out: Flat = { U: [], V: [], sizes: [], groups: [], line: [] };
  polygons.forEach((poly, i) => {
    if (poly.length < 3) return;
    for (const p of poly) {
      out.U.push(Number(p[0]));
      out.V.push(Number(p[1]));
    }
    out.sizes.push(poly.length);
    out.groups.push(Math.trunc(Number(groups[i])));
    for (const l of lines[i] as readonly number[]) out.line.push(Math.trunc(Number(l)));
  });
  return out.sizes.length > 0 ? out : null;
}

/** Steps 1–2: vertex events (the greedy merge of the sorted `v` values), snapping (every `v` replaced by the kept value
 * it merged into) and the edge table. */
function edge_table(F: Flat, tol_mm: number): [number[], EdgeTable | null] {
  const kept = greedy_merge(sorted_floats(F.V), tol_mm);
  const snapped = F.V.map((v) => kept[search_right(kept, v) - 1] as number);
  const T: EdgeTable = { u0: [], v0: [], u1: [], v1: [], dir: [], group: [], line: [], poly: [], local: [], size: [] };
  let first = 0;
  F.sizes.forEach((n, p) => {
    for (let k = 0; k < n; k++) {
      const a = first + k, b = first + ((k + 1) % n);
      const v0 = snapped[a] as number, v1 = snapped[b] as number;
      if (v0 === v1) continue;
      T.u0.push(F.U[a] as number);
      T.v0.push(v0);
      T.u1.push(F.U[b] as number);
      T.v1.push(v1);
      T.dir.push(v1 > v0 ? 1 : -1);
      T.group.push(F.groups[p] as number);
      T.line.push(F.line[a] as number);
      T.poly.push(p);
      T.local.push(k);
      T.size.push(n);
    }
    first += n;
  });
  return [kept, T.u0.length > 0 ? T : null];
}

/** Step 3: the merged crossing events (crossings within `tol_mm` of a vertex event dropped). Candidate pairs overlap
 * in `v` and in `u` (closed comparisons); consecutive edges of one input polygon are excluded; `(i, j)` in the formula
 * is `(min, max)` of the two table indices (the events are sorted, so the visiting order is immaterial). */
function crossing_events(T: EdgeTable, kept: readonly number[], tol_mm: number): number[] {
  const { u0, v0, u1, v1 } = T;
  const E = u0.length;
  const vmin = new Array<number>(E), vmax = new Array<number>(E), umin = new Array<number>(E), umax = new Array<number>(E);
  for (let e = 0; e < E; e++) {
    vmin[e] = npmin(v0[e] as number, v1[e] as number);
    vmax[e] = npmax(v0[e] as number, v1[e] as number);
    umin[e] = npmin(u0[e] as number, u1[e] as number);
    umax[e] = npmax(u0[e] as number, u1[e] as number);
  }
  const order = Array.from({ length: E }, (_x, e) => e).sort((a, b) => cmp_float(vmin[a] as number, vmin[b] as number) || a - b);
  const vmin_s = order.map((e) => vmin[e] as number);
  const found: number[] = [];
  for (let p = 0; p < E; p++) {
    const ep = order[p] as number;
    const hi = search_right(vmin_s, vmax[ep] as number);
    for (let q = p + 1; q < hi; q++) {
      const eq = order[q] as number;
      const i = ep < eq ? ep : eq, j = ep < eq ? eq : ep;
      if (!((umin[i] as number) <= (umax[j] as number) && (umin[j] as number) <= (umax[i] as number))) continue;
      if (T.poly[i] === T.poly[j]) {
        const n = T.size[i] as number;
        const dl = ((((T.local[j] as number) - (T.local[i] as number)) % n) + n) % n;
        if (dl === 1 || dl === n - 1) continue;
      }
      const ru = (u1[i] as number) - (u0[i] as number), rv = (v1[i] as number) - (v0[i] as number);
      const su = (u1[j] as number) - (u0[j] as number), sv = (v1[j] as number) - (v0[j] as number);
      const den = ru * sv - rv * su;
      if (den === 0.0) continue; // a NaN `den` stays (`den != 0.0` is true) and fails the range test below
      const qu = (u0[j] as number) - (u0[i] as number), qv = (v0[j] as number) - (v0[i] as number);
      const t = (qu * sv - qv * su) / den;
      const s = (qu * rv - qv * ru) / den;
      if (t >= 0.0 && t <= 1.0 && s >= 0.0 && s <= 1.0) {
        found.push((v0[i] as number) + t * ((v1[i] as number) - (v0[i] as number)));
      }
    }
  }
  const far: number[] = [];
  for (const vx of found) {
    const k = search_left(kept, vx);
    let near = false;
    if (k > 0) near = Math.abs(vx - (kept[k - 1] as number)) <= tol_mm;
    if (k < kept.length) near = near || Math.abs((kept[k] as number) - vx) <= tol_mm;
    if (!near) far.push(vx);
  }
  return greedy_merge(sorted_floats(far), tol_mm);
}

/** The raw pieces of steps 4–5 in (slab, k0) order. */
interface Raw {
  slab: number[];
  el: number[];
  er: number[];
  lo_a: number[];
  hi_a: number[];
  lo_b: number[];
  hi_b: number[];
}

/** Steps 4–5: per slab the active edges ordered by `(x(y_m), edge index)`, the inside intervals (every group's winding
 * number nonzero), the maximal runs of inside intervals bounded by their outer edges, clamped per end; a raw piece is
 * dropped iff both ends are at most `tol_mm` wide. */
function raw_pieces(T: EdgeTable, ev: readonly number[], n_groups: number, tol_mm: number): Raw | null {
  const { u0, v0, u1, v1 } = T;
  const E = u0.length;
  const n_slabs = ev.length - 1;
  const s_lo = new Array<number>(E), s_hi = new Array<number>(E);
  for (let e = 0; e < E; e++) {
    s_lo[e] = search_left(ev, npmin(v0[e] as number, v1[e] as number));
    s_hi[e] = search_left(ev, npmax(v0[e] as number, v1[e] as number));
  }
  // edges by their first slab (the sweep's insertion order is immaterial: each slab sorts its active edges)
  const starting: number[][] = Array.from({ length: n_slabs + 1 }, () => []);
  for (let e = 0; e < E; e++) if ((s_lo[e] as number) < (s_hi[e] as number)) (starting[s_lo[e] as number] as number[]).push(e);
  const out: Raw = { slab: [], el: [], er: [], lo_a: [], hi_a: [], lo_b: [], hi_b: [] };
  let active: number[] = [];
  const w = new Array<number>(Math.max(n_groups, 0)).fill(0);
  for (let s = 0; s < n_slabs; s++) {
    active = active.filter((e) => (s_hi[e] as number) > s);
    for (const e of starting[s] as number[]) active.push(e);
    if (active.length < 2) continue;
    const y = ((ev[s] as number) + (ev[s + 1] as number)) / 2.0;
    const ee: number[] = [], xm: number[] = [];
    for (const e of active) {
      if (((v0[e] as number) - y) * ((v1[e] as number) - y) < 0.0) {
        ee.push(e);
        xm.push(x_at(u0[e] as number, v0[e] as number, u1[e] as number, v1[e] as number, y));
      }
    }
    const m = ee.length;
    if (m < 2) continue;
    const ord = Array.from({ length: m }, (_x, k) => k)
      .sort((a, b) => cmp_float(xm[a] as number, xm[b] as number) || (ee[a] as number) - (ee[b] as number));
    const es = ord.map((k) => ee[k] as number);
    w.fill(0);
    const ins = new Array<boolean>(m).fill(false);
    for (let k = 0; k < m; k++) {
      const e = es[k] as number;
      const g = T.group[e] as number;
      if (g >= 0 && g < n_groups) w[g] = (w[g] as number) + (T.dir[e] as number);
      let inside = true;
      for (let grp = 0; grp < n_groups; grp++) if (w[grp] === 0) inside = false;
      ins[k] = inside && k < m - 1;
    }
    const a = ev[s] as number, b = ev[s + 1] as number;
    for (let k = 0; k < m; k++) {
      if (!ins[k] || (k > 0 && ins[k - 1])) continue;
      let k1 = k;
      while (k1 + 1 < m && ins[k1 + 1]) k1++;
      const el = es[k] as number, er = es[k1 + 1] as number;
      const xla = x_at(u0[el] as number, v0[el] as number, u1[el] as number, v1[el] as number, a);
      const xra = x_at(u0[er] as number, v0[er] as number, u1[er] as number, v1[er] as number, a);
      const xlb = x_at(u0[el] as number, v0[el] as number, u1[el] as number, v1[el] as number, b);
      const xrb = x_at(u0[er] as number, v0[er] as number, u1[er] as number, v1[er] as number, b);
      const lo_a = npmin(xla, xra), hi_a = npmax(xla, xra);
      const lo_b = npmin(xlb, xrb), hi_b = npmax(xlb, xrb);
      if (hi_a - lo_a <= tol_mm && hi_b - lo_b <= tol_mm) continue;
      out.slab.push(s);
      out.el.push(el);
      out.er.push(er);
      out.lo_a.push(lo_a);
      out.hi_a.push(hi_a);
      out.lo_b.push(lo_b);
      out.hi_b.push(hi_b);
    }
  }
  return out.slab.length > 0 ? out : null;
}

/** Step 6: a raw piece of slab `s + 1` whose ordered key `(line left, line right)` equals that of a raw piece of slab
 * `s` extends that piece's merged piece; equal keys inside one slab are paired in order (rank). Returns, per merged
 * piece (ordered by its first raw piece), the indices of its first and last raw piece. */
function merge_runs(raw: Raw, line: readonly number[]): [number[], number[]] {
  const n = raw.slab.length;
  const rank_of = new Map<string, number>();
  const index_of = new Map<string, number>();
  const pred = new Array<number>(n);
  for (let k = 0; k < n; k++) {
    const ll = line[raw.el[k] as number] as number, lr = line[raw.er[k] as number] as number;
    const s = raw.slab[k] as number;
    const base = `${s},${ll},${lr}`;
    const r = rank_of.get(base) ?? 0;
    rank_of.set(base, r + 1);
    index_of.set(`${base},${r}`, k);
    const p = s > 0 ? index_of.get(`${s - 1},${ll},${lr},${r}`) : undefined;
    pred[k] = p === undefined ? k : p;
  }
  const root = new Array<number>(n);
  for (let k = 0; k < n; k++) root[k] = pred[k] === k ? k : (root[pred[k] as number] as number);
  const last = new Array<number>(n).fill(-1);
  for (let k = 0; k < n; k++) {
    const r = root[k] as number;
    if (k > (last[r] as number)) last[r] = k;
  }
  const roots: number[] = [], lasts: number[] = [];
  for (let k = 0; k < n; k++) {
    if (root[k] === k) {
      roots.push(k);
      lasts.push(last[k] as number);
    }
  }
  return [roots, lasts];
}

/** The kernel on the flat form: steps 1–7. */
function scan_flat(F: Flat, n_groups: number, tol_mm: number, tol_area: number): ScanOut {
  const [kept, T] = edge_table(F, tol_mm);
  if (T === null) return EMPTY_SCAN();
  const cross = crossing_events(T, kept, tol_mm);
  const ev = cross.length > 0 ? sorted_floats([...kept, ...cross]) : kept;
  if (ev.length < 2) return EMPTY_SCAN();
  const raw = raw_pieces(T, ev, n_groups, tol_mm);
  if (raw === null) return EMPTY_SCAN();
  const [roots, lasts] = merge_runs(raw, T.line);
  const out = EMPTY_SCAN();
  roots.forEach((r, q) => {
    const l = lasts[q] as number;
    // step 7: (x_lo, a), (x_hi, a) iff wide, (x_hi', b), (x_lo', b) iff wide
    const a = ev[raw.slab[r] as number] as number;
    const b = ev[(raw.slab[l] as number) + 1] as number;
    const U = [raw.lo_a[r] as number, raw.hi_a[r] as number, raw.hi_b[l] as number, raw.lo_b[l] as number];
    const V = [a, a, b, b];
    const has = [true, (U[1] as number) - (U[0] as number) > tol_mm, true, (U[2] as number) - (U[3] as number) > tol_mm];
    const nv = has.filter((h) => h).length;
    // shoelace over the emitted vertices: an omitted slot repeats the previous vertex (exact zero term)
    const Uf = [...U], Vf = [...V];
    if (!has[1]) {
      Uf[1] = U[0] as number;
      Vf[1] = V[0] as number;
    }
    if (!has[3]) {
      Uf[3] = U[2] as number;
      Vf[3] = V[2] as number;
    }
    let area = 0.0 * (Uf[0] as number);
    for (let k = 0; k < 4; k++) {
      const k1 = (k + 1) % 4;
      area = area + ((Uf[k] as number) * (Vf[k1] as number) - (Uf[k1] as number) * (Vf[k] as number));
    }
    area = 0.5 * area;
    if (!(nv >= 3 && area > tol_area)) return;
    // canonical start: v <= v_min + tol, then the smallest u (ties within tol: lowest index)
    let vm = Infinity;
    for (let k = 0; k < 4; k++) if (has[k]) vm = npmin_reduce(vm, V[k] as number);
    const cand = has.map((h, k) => h && (V[k] as number) <= vm + tol_mm);
    let um = Infinity;
    for (let k = 0; k < 4; k++) if (cand[k]) um = npmin_reduce(um, U[k] as number);
    for (let k = 0; k < 4; k++) cand[k] = (cand[k] as boolean) && (U[k] as number) <= um + tol_mm;
    let start_slot = cand.indexOf(true);
    if (start_slot < 0) start_slot = 0; // np.argmax of an all-false row (NaN input only); slot 0 is always emitted
    // rotation by index arithmetic: the emitted slots in slot order, read from the start slot's rank
    const emitted: number[] = [];
    for (let k = 0; k < 4; k++) if (has[k]) emitted.push(k);
    const r0 = emitted.indexOf(start_slot);
    const piece: UV[] = [];
    for (let j = 0; j < nv; j++) {
      const slot = emitted[(r0 + j) % nv] as number;
      piece.push([(U[slot] as number) + 0, (V[slot] as number) + 0]);
    }
    out.pieces.push(piece);
    out.sides.push([T.line[raw.el[r] as number] as number, T.line[raw.er[r] as number] as number]);
  });
  return out;
}

/** `np.min` reduction step (NaN propagating). */
function npmin_reduce(acc: number, x: number): number {
  if (acc !== acc || x !== x) return NaN;
  return x < acc ? x : acc;
}

/**
 * Nonzero scanline decomposition with one winding counter per group (contract §5.3.4). `polygons[i]` is a list of
 * `[u, v]` vertices, `groups[i]` its group (`0 .. n_groups − 1`), `lines[i]` the line ids of its edges (edge `e` runs
 * from vertex `e` to vertex `(e + 1) mod n_i`); polygons with fewer than three vertices are ignored. An interval of a
 * slab is inside iff every group's winding number is nonzero. Returns `[pieces, sides]`: convex CCW pieces (`v` up) of
 * 3 or 4 vertices with an area above `tol_area`, rotated to the canonical start, and their `(line_left, line_right)`.
 */
export function scan_pieces(polygons: readonly (readonly (readonly number[])[])[], groups: readonly number[],
  lines: readonly (readonly number[])[], n_groups: number, tol_mm: number, tol_area: number): [UV[][], Sides[]] {
  const F = flatten(polygons, groups, lines);
  if (F === null) return [[], []];
  const out = scan_flat(F, Math.trunc(n_groups), tol_mm, tol_area);
  return [out.pieces, out.sides];
}

/** `record_pieces` plus the record's edge count (every loop's `n_i`, also of loops with fewer than three vertices). */
function record_scan(polygons: readonly (readonly (readonly number[])[])[], tol_mm: number, tol_area: number): [ScanOut, number] {
  const lines: number[][] = [];
  let offset = 0;
  for (const poly of polygons) {
    lines.push(Array.from({ length: poly.length }, (_x, k) => offset + k));
    offset += poly.length;
  }
  const F = flatten(polygons, polygons.map(() => 0), lines);
  if (F === null) return [EMPTY_SCAN(), offset];
  return [scan_flat(F, 1, tol_mm, tol_area), offset];
}

/** `scan_pieces` of one record's loops (`shadows[].polygons`) with a single group and line ids = the running edge index
 * over the record's loops (contract §5.3.4): the nonzero decomposition of the record's drawn region. */
export function record_pieces(polygons: readonly (readonly (readonly number[])[])[], tol_mm: number, tol_area: number): [UV[][], Sides[]] {
  const [out] = record_scan(polygons, tol_mm, tol_area);
  return [out.pieces, out.sides];
}

/**
 * The umbra pieces of one receiver (contract §5.3.4): `per_light[k]` is the list of the records' drawables
 * (`shadows[].polygons`, one list of polygons per record, `shadows[]` order) of the `k`-th active light (scene order).
 * With fewer than two active lights the result is `[]`. Each record is decomposed by `record_pieces`; all record pieces
 * enter one intersection scan with one group per light and line ids `base_{k,r} + side` (an upward piece edge carries
 * the piece's right line, a downward one its left line, a horizontal one `−1`). Returns canonical `[u, v]` lists.
 */
export function umbra_pieces(per_light: readonly (readonly (readonly (readonly (readonly number[])[])[])[])[],
  canvas_mm: readonly number[]): UV[][] {
  if (per_light.length < 2) return [];
  const [tol_mm, tol_area] = tolerances(canvas_mm);
  const F: Flat = { U: [], V: [], sizes: [], groups: [], line: [] };
  let base = 0;
  per_light.forEach((records, k) => {
    for (const rec of records) {
      const [out, n_edges] = record_scan(rec, tol_mm, tol_area);
      out.pieces.forEach((piece, p) => {
        const nv = piece.length;
        const sides = out.sides[p] as Sides;
        for (let j = 0; j < nv; j++) {
          const v = (piece[j] as UV)[1], vn = (piece[(j + 1) % nv] as UV)[1];
          F.U.push((piece[j] as UV)[0]);
          F.V.push(v);
          F.line.push(vn > v ? base + sides[1] : vn < v ? base + sides[0] : -1);
        }
        F.sizes.push(nv);
        F.groups.push(k);
      });
      base += n_edges;
    }
  });
  if (F.sizes.length === 0) return [];
  return scan_flat(F, per_light.length, tol_mm, tol_area).pieces;
}

/** The subset of a geometry document `umbra_from_document` reads. */
export interface UmbraDocument {
  canvas_mm: readonly number[];
  shadows: readonly { receiver: string; light: string; polygons: readonly (readonly (readonly number[])[])[] }[];
  umbra?: readonly { receiver: string; lights: readonly string[]; polygons?: unknown }[];
}

/** Recompute every `umbra[]` entry of a multi-light document from `shadows[]`, `umbra[].lights` and `canvas_mm`
 * (contract §5.3.5 (c), §5.3.9); `[]` for a document without the key. The polygons are always computed (also for an
 * entry written with `umbra = false`); for a computed document the result equals `doc.umbra` bit for bit. */
export function umbra_from_document(doc: UmbraDocument): { receiver: string; lights: string[]; polygons: UV[][] }[] {
  if (doc.umbra === undefined) return [];
  return doc.umbra.map((entry) => {
    const rid = entry.receiver;
    const per_light = entry.lights.map((lid) => doc.shadows.filter((sh) => sh.receiver === rid && sh.light === lid).map((sh) => sh.polygons));
    return { receiver: rid, lights: [...entry.lights], polygons: umbra_pieces(per_light, doc.canvas_mm) };
  });
}
