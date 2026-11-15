/**
 * The cuts of the SVG writer's text for the overlay (contract §5.4.10, D89) — pure, DOM-free and unit-tested
 * (`web/test/overlay.test.ts`); `overlay.ts` inserts the pieces.
 */

/** The pieces of the writer's text: the root element's `viewBox` and the markup between `<svg …>` and `</svg>`. */
export function split_svg(text: string): { viewBox: string | null; inner: string } {
  const start = text.indexOf("<svg");
  const open_end = start < 0 ? -1 : text.indexOf(">", start);
  const close = text.lastIndexOf("</svg>");
  if (start < 0 || open_end < 0 || close < open_end) throw new Error("set_svg: not an SVG document");
  const m = /viewBox="([^"]*)"/.exec(text.slice(start, open_end));
  return { viewBox: m ? m[1]! : null, inner: text.slice(open_end + 1, close) };
}

/** `<text>` elements of the `labels` layer inserted per animation frame (D89; recorded in `web/README.md`). */
export const LABEL_CHUNK = 1000;

/**
 * D89: the writer's inner markup cut for a DOM insertion over several frames. `first` is the markup with an empty
 * `labels` group, `chunks` the group's content in order, each ending after its `n`-th `</text>` (the last takes the
 * rest), so `first` with the chunks joined inside the group is `inner` again. Null when the group is absent, holds at
 * most `n` `<text>` elements, or contains a nested group (then the markup is inserted whole).
 */
export function split_labels(inner: string, n: number = LABEL_CHUNK): { first: string; chunks: string[] } | null {
  const a = inner.indexOf('<g id="labels"');
  if (a < 0) return null;
  const a1 = inner.indexOf(">", a) + 1;
  const b = inner.indexOf("</g>", a1);
  if (a1 <= 0 || b < 0 || inner[a1 - 2] === "/") return null;
  const body = inner.slice(a1, b);
  if (body.includes("<g")) return null;
  const chunks: string[] = [];
  let pos = 0;
  while (pos < body.length) {
    let end = pos;
    for (let i = 0; i < n; i++) {
      const e = body.indexOf("</text>", end);
      if (e < 0) { end = body.length; break; }
      end = e + 7;
    }
    if (body.indexOf("</text>", end) < 0) end = body.length;
    chunks.push(body.slice(pos, end));
    pos = end;
  }
  if (chunks.length < 2) return null;
  return { first: inner.slice(0, a1) + inner.slice(b), chunks };
}
