/**
 * The cuts of the SVG writer's text for the overlay (contract §5.4.10, D89, D91) — pure, DOM-free and unit-tested
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

/** D91 (D89's `LABEL_CHUNK` for every layer; recorded in `web/README.md`): the element count up to which a document
 * is inserted whole (every bundled example holds fewer than 500 elements). */
export const FILL_THRESHOLD = 1000;
/** D91: the cost of the elements one animation frame inserts, an element counting 1 and a `<text>` {@link TEXT_WEIGHT}. */
export const FILL_BUDGET = 1000;
/** D91: the cost of a `<text>` element against any other (its glyph layout; measured on the Miki scene, D91). */
export const TEXT_WEIGHT = 2.5;

/** Whether `inner` holds more than `n` start tags (a quick count that stops at `n + 1`; `plan_fill` validates). */
export function more_elements_than(inner: string, n: number): boolean {
  let k = 0;
  for (let i = inner.indexOf("<"); i >= 0; i = inner.indexOf("<", i + 1)) if (inner.charCodeAt(i + 1) !== 47 && ++k > n) return true;
  return false;
}

/**
 * One insertion of a fill plan: `html` goes at the end of the element reached from the overlay `<svg>` by `path`
 * (indices into `children`, one per level; `[]` is the `<svg>` itself). The plan's first step is the `<svg>`'s new
 * content (`innerHTML`), every later one an `insertAdjacentHTML("beforeend", …)`.
 */
export interface FillStep {
  path: number[];
  html: string;
}

/** The writer's markup as flat arrays over its elements in document order (ordinal `e`): the element's span
 * `start[e]`–`end[e]`, the end of its start tag `open_end[e]`, the start of its end tag `close[e]` (`open_end` for a
 * self-closed element) and `next[e]`, the ordinal after its subtree (so it holds `next[e] − e` elements; its children
 * are `e + 1`, `next[e + 1]`, … below `next[e]`); `cost[e]` is the cost of the elements before `e` (so the subtree
 * of `e` costs `cost[next[e]] − cost[e]`). */
interface Tree {
  start: number[];
  open_end: number[];
  close: number[];
  end: number[];
  next: number[];
  cost: number[];
}

/** Whether the code unit starts a tag name (an ASCII letter). */
const letter = (c: number): boolean => (c >= 65 && c <= 90) || (c >= 97 && c <= 122);
/** Whether the code unit ends a tag name (whitespace, `/` or `>`). */
const name_end = (c: number): boolean => c === 32 || c === 10 || c === 9 || c === 13 || c === 47 || c === 62;

/** The element arrays of `inner`, or null for markup the writer does not produce (comments, processing instructions,
 * a stray `<` or `>`, unbalanced or mismatched tags). A plain scan: the writer escapes `<` and `>` in text and
 * attribute values (`ts/src/output/svg.ts::escape`, `attr`). */
function parse(inner: string, text_weight: number): Tree | null {
  const t: Tree = { start: [], open_end: [], close: [], end: [], next: [], cost: [0] };
  let total = 0;
  const open: number[] = []; // ordinals of the elements whose end tag is still to come
  let pos = 0;
  for (;;) {
    const lt = inner.indexOf("<", pos);
    const gt = inner.indexOf(">", pos);
    if (lt < 0) {
      if (gt >= 0 || open.length !== 0) return null;
      break;
    }
    if (gt < lt) return null; // a stray ">" in text, or a "<" never closed
    if (inner.lastIndexOf("<", gt) !== lt) return null; // a "<" inside a tag
    const closing = inner.charCodeAt(lt + 1) === 47;
    const n0 = closing ? lt + 2 : lt + 1;
    if (!letter(inner.charCodeAt(n0))) return null; // a comment, a processing instruction, "< "
    let n1 = n0 + 1;
    while (n1 < gt && !name_end(inner.charCodeAt(n1))) n1++;
    const self = inner.charCodeAt(gt - 1) === 47 && gt - 1 >= n1;
    const end = gt + 1;
    if (closing) {
      const e = open.pop();
      if (e === undefined || self || n1 !== gt) return null;
      const o0 = t.start[e]! + 1, len = n1 - n0; // the start tag's name must be the same
      if (!name_end(inner.charCodeAt(o0 + len))) return null;
      for (let j = 0; j < len; j++) if (inner.charCodeAt(o0 + j) !== inner.charCodeAt(n0 + j)) return null;
      t.close[e] = lt;
      t.end[e] = end;
      t.next[e] = t.start.length;
    } else {
      const e = t.start.length;
      t.start.push(lt);
      t.open_end.push(end);
      t.close.push(end);
      t.end.push(end);
      t.next.push(e + 1);
      total += n1 - n0 === 4 && inner.startsWith("text", n0) ? text_weight : 1;
      t.cost.push(total);
      if (!self) open.push(e);
    }
    pos = end;
  }
  return t;
}

/**
 * D91 (generalising D89's labels): the writer's inner markup cut for a DOM insertion over several animation frames.
 * Returns the frames in order, each a list of {@link FillStep}s whose elements cost together at most about `n` (an
 * element 1, a `<text>` `text_weight`), or null when the whole markup costs at most `n` (or is not the writer's: then
 * it is inserted whole). The cut walks the element tree in document order: an element that fits the frame goes in
 * whole; one that does not fit goes into the next frame whole when it costs at most `n`, else (a large group) its
 * start and end tags go in empty and its children follow, cut the same way. Every piece of a parent's content starts with the text before its first element
 * and ends directly after an element's end tag (its last piece takes the parent's trailing text), so no two text
 * nodes become adjacent, and the steps applied in order build exactly the DOM of one `innerHTML = inner`: the same
 * elements, in the same order, with the same text nodes. Layers come in document order, so the geometry layers enter
 * before the `labels` layer.
 */
export function plan_fill(inner: string, n: number = FILL_BUDGET, text_weight: number = TEXT_WEIGHT): FillStep[][] | null {
  const t = parse(inner, text_weight);
  if (t === null || t.cost[t.start.length]! <= n) return null;
  const { start, open_end, close, end, next, cost } = t;
  const frames: FillStep[][] = [[]];
  let used = 0;
  const add = (path: number[], html: string, cost: number): void => {
    const f = frames[frames.length - 1]!;
    const last = f[f.length - 1];
    if (last !== undefined && last.path.length === path.length && last.path.every((v, i) => v === path[i])) last.html += html;
    else if (html !== "") f.push({ path, html });
    used += cost;
  };
  /** The children `first`, `next[first]`, … below `stop` of the element at `path` whose content spans `from`–`to`.
   * `run`–`run_end` is markup not yet added (whole children with the text before each), `run_cost` its cost. */
  const walk = (first: number, stop: number, from: number, to: number, path: number[]): void => {
    let run = from, run_end = from, run_cost = 0, i = 0;
    for (let c = first; c < stop; c = next[c]!, i++) {
      const k = cost[next[c]!]! - cost[c]!;
      if (used + run_cost + k <= n) {
        run_cost += k;
        run_end = end[c]!;
        continue;
      }
      add(path, inner.slice(run, run_end), run_cost);
      run = run_end;
      run_cost = 0;
      if (k <= n) {
        if (used > 0) {
          frames.push([]);
          used = 0;
        }
        run_cost = k;
        run_end = end[c]!;
      } else {
        // a large group: its tags now, empty, and its children cut the same way
        add(path, inner.slice(run, open_end[c]) + inner.slice(close[c]!, end[c]), 1);
        walk(c + 1, next[c]!, open_end[c]!, close[c]!, [...path, i]);
        run = run_end = end[c]!;
      }
    }
    add(path, inner.slice(run, to), run_cost);
  };
  walk(0, start.length, 0, inner.length, []);
  if (frames[frames.length - 1]!.length === 0) frames.pop();
  return frames.length < 2 ? null : frames;
}
