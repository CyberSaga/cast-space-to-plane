import { strict as assert } from "node:assert";
import { test } from "node:test";

import { LABEL_CHUNK, split_labels, split_svg } from "../src/overlay_split.js";

const texts = (n: number, from = 0): string => Array.from({ length: n }, (_, i) => `<text x="${i}" y="1">v${from + i}</text>`).join("\n");
const doc = (labels: string): string =>
  `\n<g id="objects" stroke="#000">\n<path d="M0 0L1 1"/>\n</g>\n<g id="labels" font-size="2.5">\n${labels}\n</g>\n<g id="construction">\n<text x="0" y="0">VP</text>\n</g>\n`;
/** The markup the DOM holds after `first` and every chunk were inserted. */
const joined = (p: { first: string; chunks: string[] }): string => {
  const a = p.first.indexOf('<g id="labels"'), a1 = p.first.indexOf(">", a) + 1;
  return p.first.slice(0, a1) + p.chunks.join("") + p.first.slice(a1);
};
const count = (s: string): number => s.split("</text>").length - 1;

test("split_labels (D89): the chunks joined inside the empty labels group are the writer's markup again", () => {
  for (const [n, size] of [[7, 3], [6, 3], [4, 3], [2500, 1000], [LABEL_CHUNK + 1, LABEL_CHUNK]] as [number, number][]) {
    const inner = doc(texts(n));
    const p = split_labels(inner, size);
    assert.ok(p !== null, `${n} / ${size}`);
    assert.equal(joined(p), inner);
    assert.equal(p.chunks.length, Math.ceil(n / size));
    assert.equal(count(p.first), 1); // the construction layer's text stays; the labels group is empty
    p.chunks.forEach((c, i) => {
      assert.equal(count(c), i < p.chunks.length - 1 ? size : n - size * i);
      if (i < p.chunks.length - 1) assert.ok(c.endsWith("</text>")); // a chunk ends at an element's end
    });
  }
});

test("split_labels (D89): few labels, no labels group, an empty or self-closed group and a nested group are inserted whole", () => {
  assert.equal(split_labels(doc(texts(3)), 3), null);
  assert.equal(split_labels(doc(texts(LABEL_CHUNK))), null);
  assert.equal(split_labels(doc("")), null);
  assert.equal(split_labels('<g id="objects"><text x="0" y="0">a</text><text x="0" y="0">b</text></g>', 1), null);
  assert.equal(split_labels(`<g id="labels"/><g id="construction">${texts(5)}</g>`, 2), null);
  assert.equal(split_labels(`<g id="labels"><g>${texts(5)}</g></g>`, 2), null);
});

test("split_svg: the viewBox and the markup between the root tags", () => {
  assert.deepEqual(split_svg('<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 3">\n<g id="labels"></g>\n</svg>\n'),
    { viewBox: "0 0 4 3", inner: '\n<g id="labels"></g>\n' });
  assert.throws(() => split_svg("<p>no</p>"));
});
