/** Tests of the core worker's scheduling client (`web/src/core_client.ts`): one render in flight, the latest params
 * win, stale generations dropped, the two phases applied in order, `settle` ignoring the in-flight reply, and
 * `publish_pose` deduplicated by value — all with a fake `post`. */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { Transform } from "castplane";

import { CoreClient, same_entries } from "../src/core_client.js";
import type { FromWorker, PoseEntries, RenderMessage, RenderParams, RenderedReply, RequestInfo, ToWorker } from "../src/core_client.js";

const T = (x: number, rz = 0): Transform => ({ position: [x, 0, 0], rotation_deg: [0, 0, rz] });

interface Rig {
  client: CoreClient;
  sent: ToWorker[];
  applied: { reply: RenderedReply; info: RequestInfo }[];
  errors: string[];
  arts: number[];
  downloads: string[];
  params: RenderParams;
}

function rig(): Rig {
  const sent: ToWorker[] = [], applied: Rig["applied"] = [], errors: string[] = [], arts: number[] = [], downloads: string[] = [];
  const params: RenderParams = { block: { focal: 50 }, hidden: true, umbra: true, layers: null, quick_layers: ["objects"], img_threshold: 250_000,
    hidden_style: "dashed", two_phase: false, art_layers: ["objects"], dragging: true, img: false, transforms: null };
  const r: Rig = { sent, applied, errors, arts, downloads, params, client: null as unknown as CoreClient };
  r.client = new CoreClient((m) => sent.push(structuredClone(m)), {
    rendered: (reply, info) => applied.push({ reply, info }),
    error: (m) => errors.push(m.message),
    art: (m) => arts.push(m.req),
    downloaded: (m) => downloads.push(m.text),
  }, () => ({ ...r.params }));
  return r;
}

const renders = (r: Rig): RenderMessage[] => r.sent.filter((m): m is RenderMessage => m.type === "render");

function reply(m: RenderMessage, phase: "quick" | "final" = "final", gen = m.gen): FromWorker {
  return { type: "rendered", req: m.req, gen, phase, svg: `<svg>${m.req}${phase}</svg>`, img: false,
    rec: {} as RenderedReply["rec"], art: { lines: [], fills: [] }, ray_points: { P: [], light_P: [], light_S: [] }, warnings: [],
    summary: { points: 0, edges: 0, rays: 0, umbra_pieces: null, hidden_lines: false, hidden_edge_runs: 0, receivers: [], constructions: [] },
    core_ms: 1, stage_a_ms: null, stage_a_ran: false };
}

test("core client: one render in flight; a request meanwhile marks it dirty, the next carries the latest params", () => {
  const r = rig();
  r.client.load({ objects: [] }, [["a", T(0)]]);
  r.client.request();
  assert.equal(renders(r).length, 1);
  assert.ok(r.client.in_flight);
  r.params.block = { focal: 60 };
  r.client.request();
  r.params.block = { focal: 70 };
  r.client.request();
  assert.equal(renders(r).length, 1, "nothing more while one is in flight");
  assert.ok(r.client.dirty);
  r.client.on_message(reply(renders(r)[0]!));
  assert.equal(r.applied.length, 1);
  assert.equal(renders(r).length, 2, "the wanted render goes out at the reply");
  assert.deepEqual(renders(r)[1]!.block, { focal: 70 }, "with the latest params");
  assert.ok(r.client.in_flight && !r.client.dirty);
  r.client.on_message(reply(renders(r)[1]!));
  assert.equal(r.applied.length, 2);
  assert.ok(!r.client.in_flight);
  assert.equal(renders(r).length, 2, "nothing wanted: nothing posted");
  assert.ok(renders(r)[1]!.req > renders(r)[0]!.req, "increasing req");
});

test("core client: a reply of a stale gen is dropped (and the wanted render follows)", () => {
  const r = rig();
  r.client.load({}, [["a", T(0)]]);
  r.client.request();
  const m0 = renders(r)[0]!;
  const g = r.client.publish_pose([["a", T(1)]]);
  assert.equal(g, m0.gen + 1);
  r.client.request();
  r.client.on_message(reply(m0));
  assert.equal(r.applied.length, 0, "the old gen's reply is not applied");
  const m1 = renders(r)[1]!;
  assert.equal(m1.gen, g);
  r.client.on_message(reply(m1));
  assert.equal(r.applied.length, 1);
  assert.equal(r.applied[0]!.info.gen, g);
  // a stale reply of the worker clears the flight too
  r.client.request();
  r.client.request();
  r.client.on_message({ type: "stale", req: renders(r)[2]!.req });
  assert.equal(renders(r).length, 4, "the wanted render follows a stale reply");
  // a reply carrying an old gen for the current request (cannot happen with an in-order worker) is dropped too
  r.client.on_message(reply(renders(r)[3]!, "final", g - 1));
  assert.equal(r.applied.length, 1);
  assert.ok(!r.client.in_flight);
});

test("core client: quick then final applied in order; the flight ends at quick; a newer render supersedes the final", () => {
  const r = rig();
  r.client.load({}, [["a", T(0)]]);
  r.params.two_phase = true;
  r.params.dragging = false;
  r.client.request();
  const m0 = renders(r)[0]!;
  assert.equal(m0.two_phase, true);
  r.client.on_message(reply(m0, "quick"));
  assert.ok(!r.client.in_flight, "the quick reply ends the flight");
  assert.ok(r.client.final_pending);
  r.client.on_message(reply(m0, "final"));
  assert.ok(!r.client.final_pending);
  assert.deepEqual(r.applied.map((a) => a.reply.phase), ["quick", "final"]);
  assert.equal(r.applied[1]!.info.two_phase, true);
  // a camera change after the quick reply: the next render goes out at once, the old final is not applied
  r.client.request();
  const m1 = renders(r)[1]!;
  r.client.on_message(reply(m1, "quick"));
  r.params.block = { focal: 99 };
  r.client.request();
  const m2 = renders(r)[2]!;
  assert.deepEqual(m2.block, { focal: 99 });
  assert.ok(!r.client.final_pending, "a newer render: no final pending");
  r.client.on_message(reply(m1, "final"));
  assert.deepEqual(r.applied.map((a) => `${a.reply.req}${a.reply.phase}`), [`${m0.req}quick`, `${m0.req}final`, `${m1.req}quick`]);
  r.client.on_message(reply(m2, "quick"));
  r.client.on_message(reply(m2, "final"));
  assert.equal(r.applied.length, 5);
});

test("core client: settle ignores the in-flight reply and every pending one", () => {
  const r = rig();
  r.client.load({}, [["a", T(0)]]);
  r.client.request();
  r.client.request();
  const m0 = renders(r)[0]!;
  r.client.settle();
  assert.ok(!r.client.in_flight && !r.client.dirty);
  r.client.on_message(reply(m0));
  assert.equal(r.applied.length, 0, "the settled request's reply is ignored");
  assert.equal(renders(r).length, 1, "and the dirty flag went with the settle");
  r.client.request_art(["objects"]);
  const art_req = r.client.last_req;
  r.client.settle();
  r.client.on_message({ type: "art", req: art_req, gen: r.client.gen, art: { lines: [], fills: [] }, ray_points: { P: [], light_P: [], light_S: [] } });
  assert.equal(r.arts.length, 0, "an art reply of a settled request is ignored");
  // a request after the settle is applied as usual
  r.client.request();
  r.client.on_message(reply(renders(r)[1]!));
  assert.equal(r.applied.length, 1);
  // a two-phase render settled between its phases: the final is ignored
  r.params.two_phase = true;
  r.client.request();
  const m2 = renders(r)[2]!;
  r.client.on_message(reply(m2, "quick"));
  r.client.settle();
  assert.ok(!r.client.final_pending);
  r.client.on_message(reply(m2, "final"));
  assert.equal(r.applied.length, 2);
});

test("core client: publish_pose posts only changed transforms; equal ones adopt the gen; a render publishes its pose first", () => {
  const r = rig();
  const g0 = r.client.load({}, [["a", T(0)], ["b", T(5)]]);
  assert.equal(r.client.publish_pose([["a", T(0)], ["b", T(5)]]), g0, "equal to the loaded pose: no message");
  assert.equal(r.sent.length, 1);
  const g1 = r.client.publish_pose([["a", T(0, 10)], ["b", T(5)]]);
  assert.equal(g1, g0 + 1);
  assert.equal(r.sent.at(-1)!.type, "pose");
  assert.equal(r.client.publish_pose([["a", T(0, 10)], ["b", T(5)]]), g1, "the same candidate twice: one message");
  assert.equal(r.sent.length, 2);
  // −0 vs 0 is a different value (posted; never a wrong picture)
  r.client.publish_pose([["a", { position: [-0, 0, 0], rotation_deg: [0, 0, 10] }], ["b", T(5)]]);
  assert.equal(r.sent.length, 3);
  // a render with transforms: pose first, then the render with the new gen
  r.params.transforms = [["a", T(1)], ["b", T(5)]];
  r.client.request();
  assert.deepEqual(r.sent.slice(-2).map((m) => m.type), ["pose", "render"]);
  assert.equal((r.sent.at(-1) as RenderMessage).gen, r.client.gen);
  // the same transforms again: only the render
  r.client.on_message(reply(renders(r)[0]!));
  r.client.request();
  assert.deepEqual(r.sent.slice(-2).map((m) => m.type), ["render", "render"]);
  // the posted copy is not aliased: mutating the caller's array changes nothing
  const mine: PoseEntries = [["a", T(7)], ["b", T(5)]];
  r.client.publish_pose(mine);
  const n = r.sent.length;
  mine[0]![1].position[0] = 8;
  assert.notEqual(r.client.publish_pose([["a", T(7)], ["b", T(5)]]), undefined);
  assert.equal(r.sent.length, n, "still equal to what was posted");
  assert.ok(same_entries([["a", T(1)]], [["a", T(1)]]) && !same_entries([["a", T(1)]], [["b", T(1)]]));
});

test("core client: errors clear the flight; downloads of an old gen are dropped", () => {
  const r = rig();
  r.client.load({}, [["a", T(0)]]);
  r.client.request();
  r.client.request();
  r.client.on_message({ type: "error", req: renders(r)[0]!.req, message: "boom" });
  assert.deepEqual(r.errors, ["boom"]);
  assert.equal(renders(r).length, 2, "the wanted render follows");
  r.client.on_message(reply(renders(r)[1]!));
  const d = r.client.download({ kind: "svg", layers: [], hidden_style: "dashed", hidden: true, umbra: true, block: {}, scene_name: "s" });
  r.client.on_message({ type: "downloaded", req: d, gen: r.client.gen, kind: "svg", filename: "s.svg", mime: "image/svg+xml", text: "ok" });
  const d2 = r.client.download({ kind: "json", layers: [], hidden_style: "dashed", hidden: true, umbra: true, block: {}, scene_name: "s" });
  const g = r.client.gen;
  r.client.publish_pose([["a", T(3)]]);
  r.client.on_message({ type: "downloaded", req: d2, gen: g, kind: "json", filename: "s.json", mime: "application/json", text: "old" });
  assert.deepEqual(r.downloads, ["ok"]);
});
