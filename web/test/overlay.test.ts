import { strict as assert } from "node:assert";
import { test } from "node:test";

import { FILL_BUDGET, FILL_THRESHOLD, TEXT_WEIGHT, more_elements_than, plan_fill, split_svg } from "../src/overlay_split.js";
import type { FillStep } from "../src/overlay_split.js";

const texts = (n: number, from = 0): string => Array.from({ length: n }, (_, i) => `<text x="${i}" y="1">v${from + i}</text>`).join("\n");
const lines = (n: number): string => Array.from({ length: n }, (_, i) => `<line x1="${i}" y1="0" x2="1" y2="1"/>`).join("\n");
const g = (id: string, body: string, attrs = ""): string => (body === "" ? `<g id="${id}"${attrs}/>` : `<g id="${id}"${attrs}>\n${body}\n</g>`);
/** A document shaped like the writer's: top-level layer groups, nested sub-groups, self-closed empty groups. */
const doc = (labels: string, objects = `<path d="M0 0L1 1"/>`): string =>
  `\n${g("horizon", `<line x1="0" y1="1" x2="2" y2="1"/>\n<text x="0" y="0">h</text>`)}\n${g("objects", objects, ' stroke="#000"')}\n` +
  `${g("labels", labels, ' font-size="2.5"')}\n${g("construction", '<text x="0" y="0">VP</text>')}\n`;

/** The end of the start tag and the start of the end tag of the element reached by `path` in `markup` (a DOM-free model
 * of `children[i]` chains; `[]` is the whole markup). */
function locate(markup: string, path: number[]): { open_end: number; close: number } {
  let lo = 0, hi = markup.length;
  for (const idx of path) {
    const re = /<(\/?)[A-Za-z][^<>]*?(\/?)>/g;
    re.lastIndex = lo;
    let depth = 0, k = -1, found: { open_end: number; close: number } | null = null, open_end = 0;
    for (let m = re.exec(markup); m !== null && m.index < hi; m = re.exec(markup)) {
      if (m[1] === "/") {
        depth -= 1;
        if (depth === 0 && k === idx) { found = { open_end, close: m.index }; break; }
      } else {
        if (depth === 0) k += 1;
        if (m[2] === "/") {
          if (depth === 0 && k === idx) throw new Error("path reaches a self-closed element");
        } else {
          if (depth === 0 && k === idx) open_end = m.index + m[0].length;
          depth += 1;
        }
      }
    }
    if (found === null) throw new Error(`no element at ${path}`);
    lo = found.open_end;
    hi = found.close;
  }
  return { open_end: lo, close: hi };
}

/** Apply a plan as `Overlay` does (the first step replaces the content, every later one appends to its element),
 * checking that each appended piece follows an element's end or its parent's start tag (no adjacent text nodes). */
function apply(frames: FillStep[][]): string {
  let s = "";
  frames.flat().forEach((st, i) => {
    if (i === 0) {
      assert.deepEqual(st.path, []);
      s = st.html;
      return;
    }
    const at = locate(s, st.path).close;
    assert.equal(s[at - 1], ">", `step ${i} at ${st.path} follows a text node`);
    s = s.slice(0, at) + st.html + s.slice(at);
  });
  return s;
}
const count = (s: string): number => (s.match(/<[A-Za-z]/g) ?? []).length;

test("plan_fill (D91): the steps applied in order are the writer's markup again; frames hold about n elements", () => {
  const cases: [string, number][] = [
    [doc(texts(7)), 3], [doc(texts(6)), 3], [doc(texts(2500)), 1000], [doc(texts(FILL_BUDGET + 1)), FILL_BUDGET],
    [doc(texts(40), lines(30)), 8],
    [doc(texts(5), `${g("objects.hidden", `${g("objects.hidden.a", "")}\n${g("objects.hidden.b", lines(12))}`)}\n${g("objects.visible", lines(9))}`), 4],
    [doc(texts(5), `${g("deep", g("deeper", g("deepest", lines(20))))}`), 6],
  ];
  for (const [inner, n] of cases) {
    const p = plan_fill(inner, n, 1);
    assert.ok(p !== null, `${count(inner)} / ${n}`);
    assert.equal(apply(p), inner);
    assert.ok(p.length >= 2);
    for (const f of p) assert.ok(count(f.map((s) => s.html).join("")) <= n + 3, `a frame of ${count(f.map((s) => s.html).join(""))} > ${n}`);
  }
});

test("plan_fill (D91): geometry layers enter before the labels; a group that fits a frame is never split", () => {
  const inner = doc(texts(25), lines(25));
  const p = plan_fill(inner, 10, 1)!;
  const flat = p.flat();
  const first_label = flat.findIndex((s) => s.html.includes("<text x=\"0\" y=\"1\">"));
  const last_line = flat.map((s) => s.html.includes("<line x1")).lastIndexOf(true);
  assert.ok(first_label > last_line);
  const small = doc(texts(25), g("small", lines(9)));
  const q = plan_fill(small, 10, 1)!;
  assert.ok(q.flat().some((s) => s.html.includes(g("small", lines(9)))), "the 10-element group goes in whole");
  assert.equal(apply(q), small);
});

test("plan_fill (D91): a <text> costs TEXT_WEIGHT elements of a frame", () => {
  const inner = doc(texts(400), lines(400));
  const p = plan_fill(inner, 100, 2.5)!;
  assert.equal(apply(p), inner);
  for (const f of p) {
    const html = f.map((s) => s.html).join(""), t = html.split("</text>").length - 1;
    assert.ok(count(html) - t + 2.5 * t <= 100 + 3, `a frame costs ${count(html) - t + 2.5 * t}`);
  }
  const labels = p.filter((f) => f.some((s) => s.html.includes("v1</text>") || s.html.includes(">v200<")));
  assert.ok(labels.every((f) => (f.map((s) => s.html).join("").split("</text>").length - 1) <= 41));
  assert.ok(TEXT_WEIGHT > 1 && FILL_BUDGET >= 100);
});

test("plan_fill (D91): a light document, and markup the writer does not produce, are inserted whole", () => {
  assert.equal(plan_fill(doc(texts(3)), 20), null);
  assert.equal(plan_fill(doc(texts(Math.floor(FILL_BUDGET / TEXT_WEIGHT) - 10))), null);
  assert.equal(plan_fill(doc("")), null);
  const many = texts(30);
  assert.equal(plan_fill(`<!-- c -->${many}`, 5), null);
  assert.equal(plan_fill(`${many}<g id="a">`, 5), null);
  assert.equal(plan_fill(`${many}</g>`, 5), null);
  assert.equal(plan_fill(`${many} a > b`, 5), null);
  assert.equal(plan_fill(`<g id="a">${many}</text>`, 5), null);
});

test("more_elements_than (D91): start tags are counted, end tags are not", () => {
  const inner = doc(texts(4)); // horizon 3, objects 2, labels 5, construction 2
  assert.equal(count(inner), 12);
  assert.equal(more_elements_than(inner, 11), true);
  assert.equal(more_elements_than(inner, 12), false);
  assert.equal(more_elements_than("", 0), false);
  assert.equal(more_elements_than(doc(texts(2500)), FILL_THRESHOLD), true);
  assert.equal(more_elements_than(doc(texts(400)), FILL_THRESHOLD), false); // every bundled example holds < 500 elements
});

test("split_svg: the viewBox and the markup between the root tags", () => {
  assert.deepEqual(split_svg('<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 3">\n<g id="labels"></g>\n</svg>\n'),
    { viewBox: "0 0 4 3", inner: '\n<g id="labels"></g>\n' });
  assert.throws(() => split_svg("<p>no</p>"));
});
