import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  OVERLAY_DRAG_PAUSE_MS, OVERLAY_QUICK_HOLD_MS, overlay_kind, overlay_wait,
} from "../src/overlay_policy.js";
import type { OverlayClock, OverlayKind } from "../src/overlay_policy.js";

const clock = (o: Partial<OverlayClock>): OverlayClock => ({ now: 1000, heavy: true, dragging: false, moved_at: -Infinity, arrived: 1000, ...o });
const KINDS: OverlayKind[] = ["drag", "quick", "final"];

test("overlay_kind: a drag request's reply is 'drag' whatever its phase, a resting one keeps its phase", () => {
  assert.equal(overlay_kind(true, "final"), "drag");
  assert.equal(overlay_kind(true, "quick"), "drag");
  assert.equal(overlay_kind(false, "quick"), "quick");
  assert.equal(overlay_kind(false, "final"), "final");
});

test("a light overlay shows every reply at once (drag, after a drag, quick, final)", () => {
  for (const kind of KINDS) {
    for (const dragging of [false, true]) assert.equal(overlay_wait(kind, clock({ heavy: false, dragging, moved_at: 999 })), 0);
  }
});

test("heavy, during a drag: the wait is measured from the pointer's last move, not from the reply", () => {
  // the 19-mesh scene's replies come ~130 ms apart: a reply-keyed 150 ms debounce fired while the pointer still moved
  for (const kind of KINDS) {
    assert.equal(overlay_wait(kind, clock({ dragging: true, moved_at: 990, arrived: 700 })), OVERLAY_DRAG_PAUSE_MS - 10);
    assert.equal(overlay_wait(kind, clock({ dragging: true, moved_at: 1000 })), OVERLAY_DRAG_PAUSE_MS);
    assert.equal(overlay_wait(kind, clock({ dragging: true, moved_at: 1000 - OVERLAY_DRAG_PAUSE_MS })), 0);
    assert.equal(overlay_wait(kind, clock({ dragging: true, moved_at: 100 })), 0);
  }
});

test("heavy, during a drag: no reply is shown however long the pointer keeps moving (no periodic update)", () => {
  // a pointer moving every 8 ms for 10 s, a reply every 130 ms: never shown while it moves
  for (let t = 0; t < 10_000; t += 130) {
    const moved_at = t - (t % 8);
    assert.ok(overlay_wait("drag", clock({ now: t, arrived: t, dragging: true, moved_at }))! > 0, `t=${t}`);
  }
});

test("heavy: a drag reply that arrives (or whose wait ends) after its drag ended is never shown", () => {
  assert.equal(overlay_wait("drag", clock({ dragging: false, moved_at: 990 })), null);
  assert.equal(overlay_wait("drag", clock({ dragging: false, moved_at: -Infinity })), null);
});

test("heavy, at rest: a quick reply waits for its final up to the hold, a final reply shows at once", () => {
  assert.equal(overlay_wait("quick", clock({ now: 1000, arrived: 1000 })), OVERLAY_QUICK_HOLD_MS);
  assert.equal(overlay_wait("quick", clock({ now: 1200, arrived: 1000 })), OVERLAY_QUICK_HOLD_MS - 200);
  assert.equal(overlay_wait("quick", clock({ now: 1000 + OVERLAY_QUICK_HOLD_MS, arrived: 1000 })), 0);
  assert.equal(overlay_wait("final", clock({})), 0);
});

test("heavy: a resting reply that arrives after a new drag began waits for the pointer's pause", () => {
  assert.equal(overlay_wait("final", clock({ dragging: true, moved_at: 995 })), OVERLAY_DRAG_PAUSE_MS - 5);
  assert.equal(overlay_wait("quick", clock({ dragging: true, moved_at: 995, arrived: 0 })), OVERLAY_DRAG_PAUSE_MS - 5);
});
