/**
 * The SVG overlay (contract §5.4.10): an `<svg>` laid exactly over the WebGL canvas, filled with the core
 * writer's text. At rest (and for small SVGs) the writer's inner markup is the overlay's DOM; during a drag of a
 * large scene the writer's unchanged SVG text may be shown through `<img src="blob:…">` instead (§5.4.11).
 */

import { LAYER_IDS } from "castplane";

import { LABEL_CHUNK, split_labels, split_svg } from "./overlay_split.js";

/** SVG length (characters) above which a drag frame uses the `<img>` mode (recorded in `web/README.md`). */
export const IMG_MODE_THRESHOLD = 250_000;

export const LAYERS = LAYER_IDS;

export type OverlayMode = "dom" | "img";

export { LABEL_CHUNK, split_labels, split_svg };

export class Overlay {
  readonly svg: SVGSVGElement;
  readonly img: HTMLImageElement;
  mode: OverlayMode = "dom";
  private url: string | null = null;
  /** D89: the label chunks not yet inserted, their group and the animation-frame request. */
  private rest: { group: Element; chunks: string[]; next: number; raf: number } | null = null;

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

  /** Whether label chunks of the last DOM document are still to be inserted (D89). */
  get filling(): boolean {
    return this.rest !== null;
  }

  /** Insert the remaining label chunks now (D89): the overlay's DOM is then the whole document. */
  flush(): void {
    const r = this.rest;
    if (r === null) return;
    this.drop_rest();
    r.group.insertAdjacentHTML("beforeend", r.chunks.slice(r.next).join(""));
  }

  private drop_rest(): void {
    if (this.rest === null) return;
    cancelAnimationFrame(this.rest.raf);
    this.rest = null;
  }

  private fill_step(): void {
    const r = this.rest;
    if (r === null) return;
    r.group.insertAdjacentHTML("beforeend", r.chunks[r.next]!);
    r.next += 1;
    if (r.next >= r.chunks.length) this.rest = null;
    else r.raf = requestAnimationFrame(() => this.fill_step());
  }

  /**
   * The DOM mode: replace the overlay's children with the writer's inner markup (the header is not inserted twice).
   * D89: a `labels` layer of more than `LABEL_CHUNK` `<text>` elements is inserted `LABEL_CHUNK` per animation frame
   * (the same markup, the same final DOM; `flush()` completes it at once). Returns whether chunks are left to insert.
   */
  set_svg(text: string): boolean {
    const { viewBox, inner } = split_svg(text);
    if (viewBox !== null && this.svg.getAttribute("viewBox") !== viewBox) this.svg.setAttribute("viewBox", viewBox);
    this.drop_rest();
    const parts = split_labels(inner);
    const group = parts === null ? null : ((this.svg.innerHTML = parts.first), this.svg.querySelector(":scope > #labels"));
    if (parts === null || group === null) this.svg.innerHTML = inner;
    else {
      this.rest = { group, chunks: parts.chunks, next: 0, raf: 0 };
      this.rest.raf = requestAnimationFrame(() => this.fill_step());
    }
    this.revoke();
    this.img.hidden = true;
    this.svg.style.display = "";
    this.mode = "dom";
    return this.rest !== null;
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
