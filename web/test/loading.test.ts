import { strict as assert } from "node:assert";
import { test } from "node:test";

import { LOADING_DELAY_MS, LOADING_TEXT, loading_after } from "../src/loading.js";
import type { LoadingEvent } from "../src/loading.js";

const run = (events: LoadingEvent[]): boolean => events.reduce((_, ev) => loading_after(ev), false);

test("loading (D92): on from a load until the first picture, an error or a failed load", () => {
  assert.equal(run(["load"]), true);
  assert.equal(run(["load", "picture"]), false);
  assert.equal(run(["load", "error"]), false); // a render error, the worker gone, or a load that failed
  assert.equal(run(["load", "picture", "picture"]), false); // later pictures change nothing
  assert.equal(run(["load", "load"]), true); // a newer load restarts it
  assert.equal(run(["load", "picture", "load"]), true);
  assert.equal(run(["picture"]), false);
});

test("loading (D92): appears only after a delay, with the pane's language", () => {
  assert.ok(LOADING_DELAY_MS >= 100 && LOADING_DELAY_MS <= 300);
  assert.match(LOADING_TEXT, /^[一-鿿]+…$/);
});
