/**
 * D92: the drawing pane's loading indicator — whether it is on (pure, DOM-free; `web/test/loading.test.ts`). `main.ts`
 * toggles the class `active` of `#pane-loading` (in `#viewport`, outside the stage: never part of the overlay `<svg>`
 * or of an export) and `aria-busy` on `#viewport`; the CSS shows it only after {@link LOADING_DELAY_MS}, so a scene
 * whose first picture arrives within a few frames (every bundled example) never shows it.
 *
 * - `load`: a scene was loaded (its validation passed): on until its first picture.
 * - `picture`: the overlay shows a picture (a DOM document's first insertion, or an `<img>` source; `Overlay.onshow`).
 *   With the core worker a load clears the overlay and drops pending pictures, so this is the new scene's; on the
 *   synchronous path the next animation frame renders the new scene (the indicator shows only when that frame lasts
 *   longer than the delay).
 * - `error`: the error panel shows a message (a render that failed, the worker gone, a load that failed: the previous
 *   scene stays, with its picture).
 */

/** The delay before the indicator becomes visible (ms; `web/src/style.css` `#pane-loading.active`). */
export const LOADING_DELAY_MS = 150;

/** The indicator's text, in the language of the drawing pane's other controls (預覽). */
export const LOADING_TEXT = "載入中…";

export type LoadingEvent = "load" | "picture" | "error";

/** Whether the indicator is on after `ev` (whatever it was before: a newer load restarts it). */
export function loading_after(ev: LoadingEvent): boolean {
  return ev === "load";
}
