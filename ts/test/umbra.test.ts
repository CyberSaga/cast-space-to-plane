/**
 * The umbra scanline kernel of contract §5.3.4 through the port (the port of `tests/test_umbra.py`): the
 * `record_pieces` table of §5.3.10, the intersection scan, determinism, the geometric properties of the pieces, the
 * acceptance pieces from the hand drawables, and `umbra_from_document` reproducing every expected `umbra[]` of the
 * conformance set bit for bit.
 */

import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import { test } from "node:test";

import { record_pieces, scan_pieces, tolerances, umbra_from_document, umbra_pieces } from "../src/umbra.js";
import type { UV } from "../src/umbra.js";

import { read_json, repo_path } from "./helpers.js";

const CANVAS = [360.0, 240.0];
const [TOL_MM, TOL_AREA] = tolerances(CANVAS);

type P = readonly (readonly number[])[];

function area(piece: P): number {
  let s = 0.0;
  const n = piece.length;
  for (let k = 0; k < n; k++) {
    const a = piece[k] as readonly number[], b = piece[(k + 1) % n] as readonly number[];
    s += (a[0] as number) * (b[1] as number) - (b[0] as number) * (a[1] as number);
  }
  return 0.5 * s;
}

const total = (pieces: readonly P[]): number => pieces.reduce((acc, p) => acc + area(p), 0.0);
const approx = (a: number, b: number, tol: number, what = ""): void => assert.ok(Math.abs(a - b) <= tol, `${what} ${a} vs ${b}`);

function assert_convex_ccw(piece: P): void {
  assert.ok(piece.length === 3 || piece.length === 4, JSON.stringify(piece));
  assert.ok(area(piece) > TOL_AREA);
  const n = piece.length;
  const scale = Math.max(1.0, ...piece.flatMap((p) => p.map((x) => Math.abs(x))));
  for (let k = 0; k < n; k++) {
    const a = piece[k] as readonly number[], b = piece[(k + 1) % n] as readonly number[], c = piece[(k + 2) % n] as readonly number[];
    const cross = ((b[0] as number) - (a[0] as number)) * ((c[1] as number) - (b[1] as number))
      - ((b[1] as number) - (a[1] as number)) * ((c[0] as number) - (b[0] as number));
    assert.ok(cross >= -1e-12 * scale * scale, `${JSON.stringify(piece)} ${k} ${cross}`);
  }
}

function assert_canonical_start(piece: P): void {
  const vmin = Math.min(...piece.map((p) => p[1] as number));
  let cand = piece.map((_p, k) => k).filter((k) => ((piece[k] as readonly number[])[1] as number) <= vmin + TOL_MM);
  const umin = Math.min(...cand.map((k) => (piece[k] as readonly number[])[0] as number));
  cand = cand.filter((k) => ((piece[k] as readonly number[])[0] as number) <= umin + TOL_MM);
  assert.equal(cand[0], 0, JSON.stringify(piece));
}

/** Winding number of a point about a closed polygon (crossing count, as `tests/test_umbra.py::winding`). */
function winding(x: number, y: number, poly: P): number {
  let w = 0;
  const n = poly.length;
  for (let k = 0; k < n; k++) {
    const p = poly[k] as readonly number[], q = poly[(k + 1) % n] as readonly number[];
    const p0 = p[0] as number, p1 = p[1] as number, q0 = q[0] as number, q1 = q[1] as number;
    const side = (q0 - p0) * (y - p1) - (x - p0) * (q1 - p1);
    if (p1 <= y && q1 > y && side > 0) w += 1;
    if (p1 > y && q1 <= y && side < 0) w -= 1;
  }
  return w;
}

function grid(u0: number, u1: number, v0: number, v1: number, nu: number, nv: number): [UV[], number] {
  const pts: UV[] = [];
  for (let j = 0; j < nv; j++) for (let i = 0; i < nu; i++) pts.push([u0 + (i + 0.5) * (u1 - u0) / nu, v0 + (j + 0.5) * (v1 - v0) / nv]);
  return [pts, (u1 - u0) * (v1 - v0) / (nu * nv)];
}

const nonzero_mask = (pts: readonly UV[], polygons: readonly P[]): boolean[] =>
  pts.map(([x, y]) => polygons.reduce((w, poly) => w + winding(x, y, poly), 0) !== 0);

function pieces_mask(pts: readonly UV[], pieces: readonly P[]): boolean[] {
  return pts.map(([x, y]) => {
    const m = pieces.reduce((acc, piece) => acc + (winding(x, y, piece) !== 0 ? 1 : 0), 0);
    assert.ok(m <= 1, "pieces overlap");
    return m === 1;
  });
}

const count = (mask: readonly boolean[]): number => mask.reduce((acc, b) => acc + (b ? 1 : 0), 0);

/** A small deterministic generator (mulberry32) for the random rows (the Python rows use numpy's PCG64). */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function random_star(r: () => number, centre: readonly number[], n: number, r0: number, r1: number): UV[] {
  const th = Array.from({ length: n }, () => r() * 2 * Math.PI).sort((a, b) => a - b);
  return th.map((t) => {
    const rad = r0 + (r1 - r0) * r();
    return [(centre[0] as number) + rad * Math.cos(t), (centre[1] as number) + rad * Math.sin(t)];
  });
}

const SQUARE: UV[] = [[0, 0], [1, 0], [1, 1], [0, 1]];

// --- tolerances ------------------------------------------------------------------

test("tolerances derive from the canvas (§5.3.4)", () => {
  const [tol_mm, tol_area] = tolerances([360, 240]);
  assert.equal(tol_mm, 1e-9 * 540.0);
  assert.equal(tol_area, 1e-9 * (540.0 * 540.0));
  assert.ok(tol_mm < 1e-6);
  assert.deepEqual(tolerances([100, 400]), [1e-9 * 600.0, 1e-9 * 360000.0]);
});

// --- record_pieces: the table of §5.3.10 -------------------------------------------

for (const [name, loop] of [["ccw", SQUARE], ["cw", [...SQUARE].reverse()]] as const) {
  test(`square: one piece, either orientation (${name})`, () => {
    const [pieces, sides] = record_pieces([loop], TOL_MM, TOL_AREA);
    assert.equal(pieces.length, 1);
    assert.equal(sides.length, 1);
    assert.equal(area(pieces[0] as P), 1.0);
    assert.deepEqual(pieces[0], [[0, 0], [1, 0], [1, 1], [0, 1]]);
  });
}

test("two overlapping squares as one record: 3 pieces, area 1.75", () => {
  const [pieces] = record_pieces([SQUARE, [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5]]], TOL_MM, TOL_AREA);
  assert.equal(pieces.length, 3);
  approx(total(pieces), 1.75, 1e-12);
});

test("a reversed inner square is a hole: 4 pieces, area 0.75", () => {
  const [pieces] = record_pieces([SQUARE, [[0.25, 0.25], [0.25, 0.75], [0.75, 0.75], [0.75, 0.25]]], TOL_MM, TOL_AREA);
  assert.equal(pieces.length, 4);
  approx(total(pieces), 0.75, 1e-12);
});

test("bow-tie: nonzero area 2.0, convex CCW pieces", () => {
  const [pieces] = record_pieces([[[0, 0], [2, 2], [2, 0], [0, 2]]], TOL_MM, TOL_AREA);
  approx(total(pieces), 2.0, 1e-12);
  for (const p of pieces) assert_convex_ccw(p);
});

const C_LOOP: UV[] = [[3, 3], [0, 3], [0, 0], [4, 0], [7, 0], [7, 1], [3, 1], [1, 1], [5, 0.96], [5, 1.96], [7, 1.96], [7, 2.96]];

test("C-shaped sweep loop: 4 pieces, area 19.0, raster within 0.5 %", () => {
  const [pieces] = record_pieces([C_LOOP], TOL_MM, TOL_AREA);
  assert.equal(pieces.length, 4);
  assert.deepEqual(pieces[0], [[0, 0], [7, 0], [7, 1], [0, 1]]);
  assert.deepEqual(pieces[1], [[0, 1], [5, 1], [5, 1.96], [0, 1.96]]);
  assert.deepEqual(pieces[2], [[0, 1.96], [7, 1.96], [7, 2.96], [0, 2.96]]);
  assert.deepEqual(pieces[3], [[0, 2.96], [7, 2.96], [3, 3], [0, 3]]);
  approx(total(pieces), 19.0, 1e-12);
  const [pts, cell] = grid(0, 7, 0, 3, 350, 150);
  approx(count(nonzero_mask(pts, [C_LOOP])) * cell, 19.0, 0.005 * 19.0);
});

/** Smallest `|Δv|` from a vertex to a point of the closed loop with the same `u`. */
function boundary_v_distance(vertex: readonly number[], loop: P): number {
  const u = vertex[0] as number, v = vertex[1] as number;
  let best = Infinity;
  for (let k = 0; k < loop.length; k++) {
    const [u0, v0] = loop[k] as [number, number], [u1, v1] = loop[(k + 1) % loop.length] as [number, number];
    if (u0 === u1) {
      if (u === u0) best = Math.min(best, Math.max(0.0, Math.min(v0, v1) - v, v - Math.max(v0, v1)));
    } else if (Math.min(u0, u1) <= u && u <= Math.max(u0, u1)) {
      best = Math.min(best, Math.abs(v0 + (u - u0) * (v1 - v0) / (u1 - u0) - v));
    }
  }
  return best;
}

for (const [name, loop] of [
  ["sliver", [[-250, 0], [250, 1.5 * TOL_MM], [250, 100], [-250, 100]]],
  ["merged vertex", [[-250, 0], [0, 0], [250, 0.7 * TOL_MM], [250, 1.2 * TOL_MM], [250, 100], [-250, 100]]],
] as [string, UV[]][]) {
  test(`${name} case: area within tol_area, vertices within tol_mm of the boundary`, () => {
    const [pieces] = record_pieces([loop], TOL_MM, TOL_AREA);
    assert.ok(pieces.length > 0);
    assert.ok(Math.abs(total(pieces) - Math.abs(area(loop))) <= TOL_AREA);
    const u_lo = Math.min(...loop.map((p) => p[0])), u_hi = Math.max(...loop.map((p) => p[0]));
    for (const piece of pieces) {
      assert_convex_ccw(piece);
      assert_canonical_start(piece);
      for (const vertex of piece) {
        assert.ok(vertex[0] >= u_lo && vertex[0] <= u_hi);
        assert.ok(boundary_v_distance(vertex, loop) <= TOL_MM * (1 + 1e-9));
      }
    }
  });
}

test("bow-tie guard: the per-end clamp keeps every piece convex and CCW", () => {
  const on_flat = (v: number): UV => [50.0 + 2.5 * TOL_MM - 1e5 * (v - TOL_MM / 2), v];
  const bow: UV[] = [[0.0, -10.0], [100.0, 10.0], on_flat(5e-4), on_flat(-5e-4)];
  const square: UV[] = [[200.0, 0.0], [201.0, 0.0], [201.0, 1.0], [200.0, 1.0]];
  for (const loops of [[bow, square], [square, bow], [[...bow].reverse(), square]]) {
    const [pieces] = record_pieces(loops, TOL_MM, TOL_AREA);
    assert.ok(pieces.length > 0);
    for (const piece of pieces) {
      assert_convex_ccw(piece);
      assert_canonical_start(piece);
    }
    const clamped = pieces.filter((p) => (p[0] as UV)[1] === 0.0 && (p[0] as UV)[0] === 50.0);
    assert.equal(clamped.length, 1);
    assert.equal((clamped[0] as UV[]).length, 4);
    approx(((clamped[0] as UV[])[1] as UV)[0], on_flat(0.0)[0], 1e-12);
    const [pts, cell] = grid(-1, 201, -10, 10, 404, 200);
    assert.ok(Math.abs(count(pieces_mask(pts, pieces)) - count(nonzero_mask(pts, loops))) * cell <= 0.01 * total(pieces));
  }
  const steep: UV[] = [[0.0, -10.0], [100.0, 10.0], [-100.0, 10.0]];
  const flat: UV[] = [on_flat(-5e-4), on_flat(5e-4), [-50.0, -20.0], [200.0, 0.0]];
  for (const piece of record_pieces([steep, flat], TOL_MM, TOL_AREA)[0]) assert_convex_ccw(piece);
});

test("degenerate inputs give no pieces", () => {
  assert.deepEqual(record_pieces([], TOL_MM, TOL_AREA)[0], []);
  assert.deepEqual(record_pieces([[[0, 0], [1, 1]]], TOL_MM, TOL_AREA)[0], []);
  assert.deepEqual(record_pieces([[[0, 0], [1, 0], [2, 0]]], TOL_MM, TOL_AREA)[0], []);
  assert.deepEqual(record_pieces([[[0, 0], [1, 1], [2, 2], [1, 1]]], TOL_MM, TOL_AREA)[0], []);
  assert.deepEqual(record_pieces([[[0, 0], [1, 0], [1, 1e-9]]], TOL_MM, TOL_AREA), [[], []]);
});

test("determinism: same bytes on two runs, emitted floats canonical", () => {
  const r = rng(7);
  const loops = [0, 1, 2].map(() => Array.from({ length: 12 }, () => [r() * 50, r() * 50] as UV));
  assert.equal(JSON.stringify(record_pieces(loops, TOL_MM, TOL_AREA)), JSON.stringify(record_pieces(loops, TOL_MM, TOL_AREA)));
  const per_light = [[[loops[0] as UV[]], [loops[1] as UV[]]], [[loops[2] as UV[]]]];
  assert.equal(JSON.stringify(umbra_pieces(per_light, CANVAS)), JSON.stringify(umbra_pieces(per_light, CANVAS)));
  const pieces = umbra_pieces([[[[[-1, -1], [1, -1], [1, 1], [-1, 1]]]], [[[[0, 0], [2, 0], [2, 2], [0, 2]]]]], CANVAS);
  assert.ok(pieces.length > 0);
  for (const piece of pieces) for (const [u, v] of piece) assert.ok(!Object.is(u, -0) && !Object.is(v, -0));
});

// --- the intersection scan ---------------------------------------------------------------

test("umbra_pieces: two lights on hand polygons", () => {
  const shifted: UV[] = [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5]];
  const pieces = umbra_pieces([[[SQUARE]], [[shifted]]], CANVAS);
  assert.deepEqual(pieces, [[[0.5, 0.5], [1.0, 0.5], [1.0, 1.0], [0.5, 1.0]]]);
  assert.equal(area(pieces[0] as P), 0.25);
  assert.deepEqual(umbra_pieces([[[SQUARE]], [[[[2.5, 0.5], [3.5, 0.5], [3.5, 1.5], [2.5, 1.5]]]]], CANVAS), []);
  assert.deepEqual(umbra_pieces([[[SQUARE]]], CANVAS), []);
  assert.deepEqual(umbra_pieces([], CANVAS), []);
  assert.deepEqual(umbra_pieces([[[SQUARE]], []], CANVAS), []);
});

test("a reversed loop of one record does not cancel another record", () => {
  const big: UV[] = [[0, 0], [4, 0], [4, 4], [0, 4]];
  const other: UV[] = [[1, 1], [1, 3], [3, 3], [3, 1]];
  approx(total(umbra_pieces([[[big], [other]], [[big]]], CANVAS)), 16.0, 1e-12);
  approx(total(umbra_pieces([[[[...big].reverse()]], [[other]]], CANVAS)), 4.0, 1e-12);
});

// the acceptance drawables of §5.3.10 (multilight_two_point_symmetric_box): `west` as written in the contract, `east`
// its mirror in u
const WEST: UV[] = [[-22.944417207498113, 12.727272727272727], [-25.753937681885635, -14.285714285714285],
  [54.86708462662592, -30.43478260869565], [164.60125387987776, -30.43478260869565], [130.54582204266168, 24.137931034482758],
  [43.51527401422056, 24.137931034482758]];
const EAST: UV[] = WEST.map(([u, v]) => [-u, v] as UV).reverse();
const EXPECTED: UV[][] = [
  [[0.0, -19.444444444444443], [25.753937681885635, -14.285714285714285], [-25.753937681885635, -14.285714285714285]],
  [[-25.753937681885635, -14.285714285714285], [25.753937681885635, -14.285714285714285], [22.944417207498113, 12.727272727272727],
    [-22.944417207498113, 12.727272727272727]],
  [[-22.944417207498113, 12.727272727272727], [22.944417207498113, 12.727272727272727], [0.0, 16.666666666666664]],
];
const EXPECTED_AREAS = [132.85761502560047, 1315.4880281807557, 90.38709809014404];

for (const order of [["west", "east"], ["east", "west"]]) {
  test(`acceptance pieces from the hand drawables (§5.3.10), lights ${order.join(", ")}`, () => {
    const drawn: Record<string, UV[][][]> = { west: [[WEST]], east: [[EAST]] };
    const pieces = umbra_pieces(order.map((k) => drawn[k] as UV[][][]), CANVAS);
    assert.equal(pieces.length, 3);
    pieces.forEach((piece, k) => {
      const expected = EXPECTED[k] as UV[];
      assert.equal(piece.length, expected.length);
      piece.forEach((p, j) => {
        approx(p[0], (expected[j] as UV)[0], 1e-6, `piece ${k} vertex ${j} u`);
        approx(p[1], (expected[j] as UV)[1], 1e-6, `piece ${k} vertex ${j} v`);
      });
      approx(area(piece), EXPECTED_AREAS[k] as number, 1e-12 * (EXPECTED_AREAS[k] as number), `area of piece ${k}`);
    });
    assert.ok(Math.abs(((pieces[2] as UV[])[2] as UV)[0]) < 1e-13);
    approx(total(pieces), 1538.7327412965, 1e-6 * 1538.7327412965, "total");
  });
}

for (let seed = 0; seed < 6; seed++) {
  test(`random umbra matches the raster AND (seed ${seed})`, () => {
    const r = rng(1000 + seed);
    const n_lights = 2 + (seed % 2);
    const per_light: UV[][][][] = [];
    for (let k = 0; k < n_lights; k++) {
      const records: UV[][][] = [];
      const n_rec = 1 + Math.floor(r() * 3);
      for (let j = 0; j < n_rec; j++) {
        const loops: UV[][] = [random_star(r, [r() * 40 - 20, r() * 40 - 20], 9, 5, 25)];
        if (r() < 0.5) loops.push(Array.from({ length: 6 }, () => [r() * 40 - 20, r() * 40 - 20] as UV));
        records.push(loops);
      }
      per_light.push(records);
    }
    const pieces = umbra_pieces(per_light, CANVAS);
    for (const piece of pieces) {
      assert_convex_ccw(piece);
      assert_canonical_start(piece);
    }
    const [pts, cell] = grid(-50, 50, -50, 50, 160, 160);
    const expect = pts.map(() => true);
    for (const records of per_light) {
      const lit = pts.map(() => false);
      for (const rec of records) nonzero_mask(pts, rec).forEach((b, i) => { if (b) lit[i] = true; });
      lit.forEach((b, i) => { if (!b) expect[i] = false; });
    }
    const got = pieces_mask(pts, pieces);
    const union = got.filter((g, i) => g || expect[i]).length;
    const inter = got.filter((g, i) => g && expect[i]).length;
    assert.ok(union === 0 || inter / union >= 0.99, `IoU ${inter / union}`);
    assert.ok(Math.abs(count(got) - count(expect)) * cell <= 0.03 * Math.max(total(pieces), 1.0));
    const permuted = umbra_pieces([...per_light].reverse(), CANVAS);
    approx(total(permuted), total(pieces), 1e-9 * Math.max(1.0, Math.abs(total(pieces))));
    assert.deepEqual(pieces_mask(pts, permuted), got);
  });
}

test("scan_pieces directly: groups and sides", () => {
  const a: UV[] = SQUARE.map(([u, v]) => [u, v]);
  const b: UV[] = SQUARE.map(([u, v]) => [u + 0.5, v + 0.5]);
  const lines = [[0, 1, 2, 3], [4, 5, 6, 7]];
  let [pieces] = scan_pieces([a, b], [0, 0], lines, 1, TOL_MM, TOL_AREA);
  approx(total(pieces), 1.75, 1e-12);
  let sides;
  [pieces, sides] = scan_pieces([a, b], [0, 1], lines, 2, TOL_MM, TOL_AREA);
  assert.deepEqual(pieces, [[[0.5, 0.5], [1.0, 0.5], [1.0, 1.0], [0.5, 1.0]]]);
  assert.deepEqual(sides, [[7, 1]]);
});

test("umbra_from_document on a hand document", () => {
  const doc = {
    canvas_mm: CANVAS,
    shadows: [
      { light: "west", receiver: "ground", object: "cube", polygons: [WEST] },
      { light: "east", receiver: "ground", object: "cube", polygons: [EAST] },
      { light: "east", receiver: "wall", object: "cube", polygons: [] },
    ],
    umbra: [{ receiver: "ground", lights: ["west", "east"], polygons: null }, { receiver: "wall", lights: ["east"], polygons: [] }],
  };
  const out = umbra_from_document(JSON.parse(JSON.stringify(doc)));
  assert.deepEqual(out.map((e) => e.receiver), ["ground", "wall"]);
  assert.deepEqual(out[0]?.lights, ["west", "east"]);
  assert.deepEqual(out[1]?.polygons, []);
  assert.deepEqual(out[0]?.polygons, umbra_pieces([[[WEST]], [[EAST]]], CANVAS));
  assert.equal(out[0]?.polygons.length, 3);
  assert.deepEqual(umbra_from_document({ canvas_mm: CANVAS, shadows: [] }), []);
});

test("umbra_from_document reproduces every expected umbra[] of the conformance set bit for bit (§5.3.5 (c))", () => {
  const dir = repo_path("tests", "conformance", "expected");
  const files = readdirSync(dir).filter((f) => f.endsWith(".json"));
  let multi = 0;
  for (const f of files) {
    const doc = read_json(`${dir}/${f}`);
    if (doc.umbra === undefined) continue;
    multi++;
    const got = umbra_from_document(doc);
    assert.equal(got.length, doc.umbra.length, f);
    got.forEach((e, k) => {
      assert.deepEqual(e.lights, doc.umbra[k].lights, f);
      assert.equal(JSON.stringify(e.polygons), JSON.stringify(doc.umbra[k].polygons), f);
    });
  }
  assert.ok(multi >= 4, `${multi} multi-light expected documents`);
});

test("record_pieces on a 2 000-edge loop (the M5 mesh case of §5.3.9)", () => {
  const loop = random_star(rng(3), [0.0, 0.0], 2000, 50.0, 70.0);
  const [pieces, sides] = record_pieces([loop], TOL_MM, TOL_AREA);
  assert.equal(sides.length, pieces.length);
  assert.ok(Math.abs(total(pieces) - Math.abs(area(loop))) <= 10 * TOL_AREA);
  for (let k = 0; k < pieces.length; k += 97) assert_convex_ccw(pieces[k] as P);
});
