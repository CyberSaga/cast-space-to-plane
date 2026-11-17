/**
 * The few numbers of a geometry document that the page shows without the document itself (web UI, not core): the
 * status line's counts and the `doc_summary` hook. Pure and DOM-free, so the core worker (`core_worker.ts`) computes
 * them next to the document and sends only this summary to the main thread (unit-tested in
 * `web/test/doc_summary.test.ts`).
 */

import type { GeometryDocument } from "castplane";

/** What `ui.ts::status_text` and the `doc_summary` hook read of a document. */
export interface DocSummary {
  /** `Object.keys(doc.points).length`. */
  points: number;
  /** `doc.edges.length`. */
  edges: number;
  /** {@link ray_count}. */
  rays: number;
  /** {@link umbra_count}, or null when the document has no `umbra` key (the status line then omits the count). */
  umbra_pieces: number | null;
  hidden_lines: boolean;
  /** The hidden runs of every edge. */
  hidden_edge_runs: number;
  /** The receivers' ids in document order. */
  receivers: string[];
  /** The light ids of `constructions` (N ≥ 2 lights), else `[]`. */
  constructions: string[];
}

/** Construction rays of every light (`constructions` with N ≥ 2 lights, else `construction`). */
export function ray_count(doc: GeometryDocument): number {
  const blocks = doc.constructions !== undefined ? Object.values(doc.constructions) : [doc.construction];
  return blocks.reduce((n, b) => n + b.rays.length, 0);
}

/** Umbra pieces of the frame (`null` polygons — a drag frame, `umbra = false` — count as none). */
export function umbra_count(doc: GeometryDocument): number {
  return (doc.umbra ?? []).reduce((n, u) => n + (u.polygons?.length ?? 0), 0);
}

/** The summary of `doc` (only read). */
export function doc_summary_of(doc: GeometryDocument): DocSummary {
  return {
    points: Object.keys(doc.points).length,
    edges: doc.edges.length,
    rays: ray_count(doc),
    umbra_pieces: doc.umbra !== undefined ? umbra_count(doc) : null,
    hidden_lines: doc.hidden_lines,
    hidden_edge_runs: doc.edges.reduce((n, e) => n + e.runs.filter((r) => !r.visible).length, 0),
    receivers: doc.receivers.map((r) => r.id),
    constructions: doc.constructions === undefined ? [] : Object.keys(doc.constructions),
  };
}
