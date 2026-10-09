/**
 * The page's view toggles — pure, DOM-free and unit-tested (`web/test/plane.test.ts`): the six layer checkboxes
 * (with "作圖線" mirroring `construction`), "Hidden lines" and "3D view". They are page-level UI state: they start at
 * {@link initial_toggles} when the page opens and keep whatever the user sets across scene and example loads; a loaded
 * scene's `output.layers` and `output.hidden_lines` do not drive them (`main.ts` sets the checkboxes once, from
 * {@link initial_toggles}, and never in its scene load). "Download SVG" writes the checked layers; "Download JSON" and
 * "Download scene" follow the "Hidden lines" checkbox. The page also opens in the edit view: "預覽" released, the
 * observer pane shown (D80), whatever an earlier visit chose.
 */

/** The layer that starts unchecked (and its "作圖線" mirror). */
export const LAYERS_OFF_AT_START: readonly string[] = ["construction"];

/** The toggle state of the page. */
export interface Toggles {
  /** The checked layer ids. */
  layers: Set<string>;
  /** "Hidden lines" (`compose`'s `hidden_lines`; the "Hidden style" select is enabled iff it is checked). */
  hidden_lines: boolean;
  /** "3D view": with it off the three.js canvas is hidden and not rendered. */
  view3d: boolean;
  /** "預覽" (D80): pressed hides the observer pane and the drawing pane takes the full width. */
  preview: boolean;
}

/** The toggles at page start: every layer but `construction` checked, hidden lines on, the 3D view off, not previewing
 * (the observer pane shown). */
export function initial_toggles(layer_ids: readonly string[]): Toggles {
  return { layers: new Set(layer_ids.filter((id) => !LAYERS_OFF_AT_START.includes(id))), hidden_lines: true, view3d: false, preview: false };
}
