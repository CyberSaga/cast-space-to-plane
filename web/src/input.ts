/**
 * File-drop input (contract §5.4.10). The M7 pointer and wheel handler of the drawing pane is superseded in M10 by the
 * right pane's plane-mode gestures (`plane.ts` `RightPaneGesture`, wired in `main.ts`; contract §5.7.9).
 */

/** Page-wide drag and drop of a file: `highlight` gets class `dragover` while a drag is over the page; the first
 * dropped file goes to `on_file`. */
export function attach_file_drop(highlight: HTMLElement, on_file: (file: File) => void): void {
  window.addEventListener("dragover", (ev) => {
    ev.preventDefault();
    highlight.classList.add("dragover");
  });
  window.addEventListener("dragleave", (ev) => {
    if (ev.relatedTarget === null) highlight.classList.remove("dragover");
  });
  window.addEventListener("drop", (ev) => {
    ev.preventDefault();
    highlight.classList.remove("dragover");
    const f = ev.dataTransfer?.files?.[0];
    if (f !== undefined) on_file(f);
  });
}
