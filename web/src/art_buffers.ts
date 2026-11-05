/**
 * The drawing on the observer's frame as typed arrays (web UI, not core; contract §5.6.5 "drawing on the frame").
 * `line_art` (observer.ts) gives the drawables of a document clipped to the canvas, both in canvas mm (`uv`) and on
 * the frame (`world`). The frame mapping `unproject_to_plane(rec, uv, depth)` is affine in `(u, v)`, so the observer
 * pane keeps the drawing in canvas mm and places it with one 4×4 matrix per frame ({@link art_frame_matrix}): the
 * drawing rides on the board at once when the camera moves, and its content is replaced only when a new document
 * arrives. The packed form is transferable (a Web Worker can build it, §5.4.11), DOM-free and unit-tested
 * (`web/test/art_buffers.test.ts`).
 */

import type { CameraRecord } from "castplane";

import type { FillStyle, LineArt, LineStyle } from "./observer.js";

/** The drawing in canvas mm: one buffer per non-empty line style (4 floats per segment: `u0 v0 u1 v1`) and one per
 * filled polygon (2 floats per vertex, ≥ 3 vertices, clipped to the canvas). Styles keep `line_art`'s order of first
 * appearance; segments keep their order. */
export interface ArtBuffers {
  lines: { style: LineStyle; uv: Float32Array }[];
  fills: { style: FillStyle; uv: Float32Array }[];
}

/** Pack `art` (its `uv` only: the frame placement is {@link art_frame_matrix}'s job). */
export function pack_art(art: LineArt): ArtBuffers {
  const by_style = new Map<LineStyle, number[]>();
  for (const s of art.segments) {
    let list = by_style.get(s.style);
    if (list === undefined) {
      list = [];
      by_style.set(s.style, list);
    }
    list.push(s.uv[0][0], s.uv[0][1], s.uv[1][0], s.uv[1][1]);
  }
  const lines = [...by_style].map(([style, list]) => ({ style, uv: Float32Array.from(list) }));
  const fills = art.fills.map((f) => ({ style: f.style, uv: Float32Array.from(f.uv.flatMap((p) => [p[0], p[1]])) }));
  return { lines, fills };
}

/** The `ArrayBuffer`s of `art` (for `postMessage`'s transfer list). */
export function art_transferables(art: ArtBuffers): ArrayBuffer[] {
  return [...art.lines.map((l) => l.uv.buffer as ArrayBuffer), ...art.fills.map((f) => f.uv.buffer as ArrayBuffer)];
}

/**
 * The column-major 4×4 matrix `M` with `M · (u, v, 0, 1) = unproject_to_plane(rec, [u, v], depth)` for every canvas
 * point `(u, v)` (§5.6.1: `X = C + depth · [((u − u0) / k) · r' + ((v − v0) / k) · u' + f]`, `k = K[0][0]`, `r'`, `u'`,
 * `f` the rows of `R`). Its z column is `f` (never used: the drawing has `z = 0`), so the matrix is invertible.
 */
export function art_frame_matrix(rec: Pick<CameraRecord, "K" | "R" | "C" | "u0" | "v0">, depth: number): number[] {
  const k = rec.K[0][0];
  const [r, u, f] = rec.R;
  const C = rec.C;
  const su = depth / k, sv = depth / k;
  const ou = -rec.u0 * su, ov = -rec.v0 * sv;
  const origin = [
    C[0] + depth * f[0] + ou * r[0] + ov * u[0],
    C[1] + depth * f[1] + ou * r[1] + ov * u[1],
    C[2] + depth * f[2] + ou * r[2] + ov * u[2],
  ];
  // column-major (three.js `Matrix4.fromArray`): columns e_u, e_v, e_z, origin
  return [
    su * r[0], su * r[1], su * r[2], 0,
    sv * u[0], sv * u[1], sv * u[2], 0,
    f[0], f[1], f[2], 0,
    origin[0], origin[1], origin[2], 1,
  ];
}
