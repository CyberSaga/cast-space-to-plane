/**
 * Pointer, wheel and file-drop input (contract §5.4.10). The handlers only report gestures to callbacks; the
 * callbacks mutate state and request a frame ("latest camera wins"). No camera math here.
 */

/** Callbacks of `attach_drag_input`. */
export interface DragHandlers {
  /** Whether a gesture may start or continue (a scene is loaded). */
  ready(): boolean;
  /** A drag began (after pointer capture). */
  start(): void;
  /** A pointer moved by `(dx, dy)` CSS px during a drag; `pan` = right button or Shift at pointer-down; `H_px` = the
   * element's height (≥ 1). Not called for a zero move. */
  drag(dx: number, dy: number, pan: boolean, H_px: number): void;
  /** The drag ended (pointer-up or cancel of the dragging pointer). */
  end(): void;
  /** A wheel event (default prevented). */
  wheel(deltaY: number): void;
}

/** One pointer drag at a time on `el` (left: orbit, right or Shift: pan), plus the wheel; the context menu is
 * suppressed so a right drag can pan. */
export function attach_drag_input(el: HTMLElement, h: DragHandlers): void {
  let pointer: { id: number; x: number; y: number; pan: boolean } | null = null;

  el.addEventListener("contextmenu", (ev) => ev.preventDefault());
  el.addEventListener("pointerdown", (ev) => {
    if (!h.ready() || pointer !== null) return;
    pointer = { id: ev.pointerId, x: ev.clientX, y: ev.clientY, pan: ev.button === 2 || ev.shiftKey };
    el.setPointerCapture(ev.pointerId);
    h.start();
    ev.preventDefault();
  });
  el.addEventListener("pointermove", (ev) => {
    if (pointer === null || ev.pointerId !== pointer.id || !h.ready()) return;
    const dx = ev.clientX - pointer.x, dy = ev.clientY - pointer.y;
    pointer.x = ev.clientX;
    pointer.y = ev.clientY;
    if (dx === 0 && dy === 0) return;
    h.drag(dx, dy, pointer.pan, el.clientHeight || 1);
  });
  const end_drag = (ev: PointerEvent): void => {
    if (pointer === null || ev.pointerId !== pointer.id) return;
    pointer = null;
    h.end();
  };
  el.addEventListener("pointerup", end_drag);
  el.addEventListener("pointercancel", end_drag);
  el.addEventListener("wheel", (ev) => {
    if (!h.ready()) return;
    ev.preventDefault();
    h.wheel(ev.deltaY);
  }, { passive: false });
}

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
