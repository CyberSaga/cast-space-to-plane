/**
 * File-drop input (contract §5.4.10), page-wide. The drawing pane itself takes no pointer or wheel input: it is
 * view-only, and the board is moved only in the observer pane (`observer3d.ts` handles) and with the controls.
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
