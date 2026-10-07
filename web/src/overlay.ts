/**
 * The SVG overlay (contract §5.4.10): an `<svg>` laid exactly over the WebGL canvas, filled with the core
 * writer's text. At rest (and for small SVGs) the writer's inner markup is the overlay's DOM; during a drag of a
 * large scene the writer's unchanged SVG text may be shown through `<img src="blob:…">` instead (§5.4.11).
 */

import { LAYER_IDS } from "castplane";

/** SVG length (characters) above which a drag frame uses the `<img>` mode (recorded in `web/README.md`). */
export const IMG_MODE_THRESHOLD = 250_000;

export const LAYERS = LAYER_IDS;

export type OverlayMode = "dom" | "img";

/** The pieces of the writer's text: the root element's `viewBox` and the markup between `<svg …>` and `</svg>`. */
export function split_svg(text: string): { viewBox: string | null; inner: string } {
  const start = text.indexOf("<svg");
  const open_end = start < 0 ? -1 : text.indexOf(">", start);
  const close = text.lastIndexOf("</svg>");
  if (start < 0 || open_end < 0 || close < open_end) throw new Error("set_svg: not an SVG document");
  const m = /viewBox="([^"]*)"/.exec(text.slice(start, open_end));
  return { viewBox: m ? m[1]! : null, inner: text.slice(open_end + 1, close) };
}

export class Overlay {
  readonly svg: SVGSVGElement;
  readonly img: HTMLImageElement;
  mode: OverlayMode = "dom";
  private url: string | null = null;

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

  /** The DOM mode: replace the overlay's children with the writer's inner markup (the header is not inserted twice). */
  set_svg(text: string): void {
    const { viewBox, inner } = split_svg(text);
    if (viewBox !== null && this.svg.getAttribute("viewBox") !== viewBox) this.svg.setAttribute("viewBox", viewBox);
    this.svg.innerHTML = inner;
    this.revoke();
    this.img.hidden = true;
    this.svg.style.display = "";
    this.mode = "dom";
  }

  /** The `<img>` mode: the writer's unchanged text as an image (the previous blob URL is revoked). */
  set_img(text: string): void {
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
