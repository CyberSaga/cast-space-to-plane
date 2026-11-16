/**
 * The SVG overlay (contract §5.4.10): an `<svg>` laid exactly over the WebGL canvas, filled with the core
 * writer's text. At rest (and for small SVGs) the writer's inner markup is the overlay's DOM; during a drag of a
 * large scene the writer's unchanged SVG text may be shown through `<img src="blob:…">` instead (§5.4.11).
 */

import { LAYER_IDS } from "castplane";

import { FILL_BUDGET, FILL_THRESHOLD, TEXT_WEIGHT, more_elements_than, plan_fill, split_svg } from "./overlay_split.js";
import type { FillStep } from "./overlay_split.js";

/** SVG length (characters) above which a drag frame uses the `<img>` mode (recorded in `web/README.md`). */
export const IMG_MODE_THRESHOLD = 250_000;

export const LAYERS = LAYER_IDS;

export type OverlayMode = "dom" | "img";

export { FILL_BUDGET, FILL_THRESHOLD, TEXT_WEIGHT, more_elements_than, plan_fill, split_svg };

export class Overlay {
  readonly svg: SVGSVGElement;
  readonly img: HTMLImageElement;
  mode: OverlayMode = "dom";
  private url: string | null = null;
  /** D92: called whenever the overlay starts showing a picture (a DOM document's first insertion, an `<img>` source). */
  onshow: (() => void) | null = null;
  /** D89, D91: the DOM document being inserted: its markup and `viewBox`, its frames (`plan_fill`; null until planned),
   * the next frame to insert and the animation-frame request. */
  private rest: { inner: string; viewBox: string | null; frames: FillStep[][] | null; next: number; raf: number } | null = null;

  constructor(parent: HTMLElement) {
    this.svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    this.svg.setAttribute("class", "overlay");
    this.svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    this.svg.setAttribute("aria-label", "castplane SVG overlay");
    this.img = document.createElement("img");
    this.img.className = "overlay";
    this.img.alt = "";
    this.img.hidden = true;
    parent.append(this.svg, this.img);
  }

  /** Whether frames of the last DOM document are still to be inserted (D89, D91). */
  get filling(): boolean {
    return this.rest !== null;
  }

  /** Insert the rest of the document now (D89, D91): the overlay's DOM is then the whole document. */
  flush(): void {
    const r = this.rest;
    if (r === null) return;
    this.drop_rest();
    if (r.frames === null || r.next === 0) this.show_dom(r.inner, r.viewBox);
    else for (let i = r.next; i < r.frames.length; i++) this.insert(r.frames[i]!);
  }

  private drop_rest(): void {
    if (this.rest === null) return;
    cancelAnimationFrame(this.rest.raf);
    this.rest = null;
  }

  /** Apply one frame's steps (`plan_fill`): each appends its markup to the element its path reaches. */
  private insert(frame: readonly FillStep[]): void {
    for (const st of frame) {
      let el: Element = this.svg;
      for (const i of st.path) el = el.children[i]!;
      el.insertAdjacentHTML("beforeend", st.html);
    }
  }

  /** Replace the overlay's children with `html` and show the DOM overlay (the `<img>` hidden, its URL revoked). */
  private show_dom(html: string, viewBox: string | null): void {
    if (viewBox !== null && this.svg.getAttribute("viewBox") !== viewBox) this.svg.setAttribute("viewBox", viewBox);
    this.svg.innerHTML = html;
    this.revoke();
    this.img.hidden = true;
    this.svg.style.display = "";
    this.onshow?.();
  }

  /** One animation frame of a document inserted over several (D91): first its plan, then one frame of steps each. */
  private fill_step(): void {
    const r = this.rest;
    if (r === null) return;
    if (r.frames === null) {
      const frames = plan_fill(r.inner);
      if (frames === null) {
        this.rest = null;
        this.show_dom(r.inner, r.viewBox); // not the writer's markup after all: inserted whole
        return;
      }
      r.frames = frames;
    } else {
      const frame = r.frames[r.next]!;
      if (r.next === 0) {
        this.show_dom(frame[0]!.html, r.viewBox); // the plan's first step is the <svg>'s new content
        this.insert(frame.slice(1));
      } else this.insert(frame);
      r.next += 1;
      if (r.next >= r.frames.length) {
        this.rest = null;
        return;
      }
    }
    r.raf = requestAnimationFrame(() => this.fill_step());
  }

  /**
   * The DOM mode: replace the overlay's children with the writer's inner markup (the header is not inserted twice).
   * D91 (generalising D89): a document of more than `FILL_THRESHOLD` elements (`more_elements_than`) is inserted over
   * several animation frames, starting in the frame after the next one (the first rendering after this call belongs to
   * the caller's task): one frame computes its plan (`plan_fill`), each later one inserts elements costing about
   * `FILL_BUDGET` (a `<text>` counts `TEXT_WEIGHT`) in document order; the previous picture stays until the first of
   * them. The same markup, the same final DOM; `flush()` completes it at once. A lighter document is inserted whole,
   * now. Returns whether the document is still to be completed.
   */
  set_svg(text: string): boolean {
    const { viewBox, inner } = split_svg(text);
    this.drop_rest();
    this.mode = "dom";
    if (!more_elements_than(inner, FILL_THRESHOLD)) {
      this.show_dom(inner, viewBox);
      return false;
    }
    const r = { inner, viewBox, frames: null, next: 0, raf: 0 };
    this.rest = r;
    r.raf = requestAnimationFrame(() => {
      if (this.rest === r) r.raf = requestAnimationFrame(() => this.fill_step());
    });
    return true;
  }

  /** The `<img>` mode: the writer's unchanged text as an image (the previous blob URL is revoked). */
  set_img(text: string): void {
    this.drop_rest();
    const url = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }));
    this.img.src = url;
    this.revoke();
    this.url = url;
    this.img.hidden = false;
    this.svg.style.display = "none";
    this.mode = "img";
    this.onshow?.();
  }

  /** Layer visibility of the DOM mode: classes `hide-<layer>` on the overlay. */
  set_hidden_layers(checked: ReadonlySet<string>): void {
    for (const id of LAYERS) this.svg.classList.toggle(`hide-${id}`, !checked.has(id));
  }

  clear(): void {
    this.drop_rest();
    this.svg.innerHTML = "";
    this.revoke();
    this.img.removeAttribute("src");
    this.img.hidden = true;
  }

  private revoke(): void {
    if (this.url !== null) {
      URL.revokeObjectURL(this.url);
      this.url = null;
    }
  }
}
