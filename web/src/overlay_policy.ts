/**
 * When the drawing pane shows a core-worker reply (contract §5.4 implementation notes, D87 and D88). Pure: the caller
 * passes the clock and the state, so the rule is unit-tested without a DOM (`web/test/overlay_policy.test.ts`).
 *
 * A new overlay costs the main thread its parse, layout and paint; an `<img>` SVG document is parsed, laid out and
 * painted on the main thread like the DOM overlay. For a large drawing that is one long task of 100–400 ms. Below
 * {@link OVERLAY_HEAVY_MS} (the smallest resting `innerHTML` time since the load; every bundled example takes 0.5–2 ms)
 * the overlay is **light** and every reply is shown at once; until that time is measured, a scene counts as heavy for a
 * drag when a reply since the load was longer than the `<img>` threshold ({@link overlay_heavy}; the caller passes
 * that flag only for a held drag or a drag reply, so a load's resting replies still replace the previous scene's
 * picture at once). A **heavy** overlay is shown only when nothing moves:
 * - **During a held drag** (any reply, also a resting one that arrives after a new drag began): when the pointer has
 *   not moved for {@link OVERLAY_DRAG_PAUSE_MS}. The pause is measured from the pointer's last move, not from the last
 *   reply: a slow scene's replies come about as far apart as the pause, so a reply-keyed wait would fire while the
 *   pointer still moves. A continuous drag shows no new overlay; the observer's drawing on the frame (GPU lines, cheap)
 *   follows every reply.
 * - **A drag reply after its drag ended** is never shown: the release always requests the resting frame
 *   (`request_after_drag`, `finish_object_drag`), which replaces it.
 * - **A resting `quick` reply** waits {@link OVERLAY_QUICK_HOLD_MS} for its `final` one (which replaces it at once), so
 *   a release or a resting edit pays one overlay update instead of two; a late `final` still lets the `quick` one
 *   show. Continuous resting input (a slider moved, a key held) counts as moving too: each newer reply replaces the
 *   waiting one and restarts its hold, and a newer render drops the pending `final`, so the pane shows the last
 *   document once the input stops.
 * - **A resting `final` reply** is shown at once.
 */

/** Smallest resting `innerHTML` time (ms) from which the overlay counts as heavy (D87). */
export const OVERLAY_HEAVY_MS = 3;
/** How long the pointer must rest during a drag before a heavy overlay is replaced (ms, D88). */
export const OVERLAY_DRAG_PAUSE_MS = 250;
/** How long a heavy resting `quick` reply waits for its `final` one (ms, D88). */
export const OVERLAY_QUICK_HOLD_MS = 500;

/** The reply's kind: a drag request's reply, or a resting request's `quick` or `final` (or single) reply. */
export type OverlayKind = "drag" | "quick" | "final";

export interface OverlayClock {
  /** The current time (ms, `performance.now()`). */
  now: number;
  /** Whether the scene's overlay is heavy (`resting_dom_ms >= OVERLAY_HEAVY_MS`). */
  heavy: boolean;
  /** Whether a drag is held now. */
  dragging: boolean;
  /** When the pointer last moved during the held drag (or the drag began). */
  moved_at: number;
  /** When the reply arrived. */
  arrived: number;
}

/** Whether the overlay is heavy: the smallest resting `innerHTML` time since the load (`Infinity` while none was
 * measured) is at least {@link OVERLAY_HEAVY_MS}; before a measurement, whether a reply since the load was longer than
 * the `<img>` threshold (`long_svg`; such a scene is far above the cost threshold, and a drag begun before its first
 * resting `final` is shown must not replace the overlay on every reply). */
export function overlay_heavy(resting_dom_ms: number, long_svg: boolean): boolean {
  return Number.isFinite(resting_dom_ms) ? resting_dom_ms >= OVERLAY_HEAVY_MS : long_svg;
}

/** The reply kind of a render reply: its request's drag flag and its phase. */
export function overlay_kind(dragging_request: boolean, phase: "quick" | "final"): OverlayKind {
  return dragging_request ? "drag" : phase;
}

/** Milliseconds to wait before the reply's overlay is shown (0: now), or null when it is never shown (a newer frame
 * replaces it). Re-evaluated when the wait is over: a pointer that moved meanwhile restarts it. */
export function overlay_wait(kind: OverlayKind, c: OverlayClock): number | null {
  if (!c.heavy) return 0;
  if (c.dragging) return Math.max(0, c.moved_at + OVERLAY_DRAG_PAUSE_MS - c.now);
  if (kind === "drag") return null;
  if (kind === "quick") return Math.max(0, c.arrived + OVERLAY_QUICK_HOLD_MS - c.now);
  return 0;
}
