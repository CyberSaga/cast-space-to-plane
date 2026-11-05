/**
 * The main thread's side of the core worker (`core_worker.ts`; contract §5.4.11 "running B + C + SVG in a Web Worker:
 * acceptable"): the message shapes and the pure scheduling of requests. DOM-free and worker-free: the transport is an
 * injected `post` function and the replies come in through {@link CoreClient.on_message}, so the class is unit-tested
 * with a fake worker (`web/test/core_client.test.ts`).
 *
 * Rules:
 * - **Generations.** `gen` numbers the scene the worker holds: {@link CoreClient.load} (a `scene` message) and every
 *   {@link CoreClient.publish_pose} whose transforms differ, value for value, from the last posted ones (a `pose`
 *   message) increment it; equal transforms post nothing and keep the gen. A reply whose `gen` is not the current one
 *   is dropped.
 * - **One render in flight, latest wins.** {@link CoreClient.request} posts a `render` built from the injected
 *   `params()` at once when no render is in flight, else it only marks the client dirty; when the in-flight render is
 *   answered (its only or its `quick` reply, a `stale` or an `error`) and the client is dirty, the next render is posted
 *   at once with the then-current `params()`. A render's `transforms` are published (deduplicated) right before it,
 *   so a pose is always followed by the render that needs it and never invalidates a render already in flight.
 * - **Two phases.** A `two_phase` render with hidden lines or umbra is answered twice, `quick` then `final`; the render
 *   stops being in flight at the `quick` reply (so a new camera need not wait for the hidden lines), and the `final`
 *   reply is applied only while no newer render has been posted ({@link CoreClient.final_pending}).
 * - **Settle.** {@link CoreClient.settle} (the main thread rendered synchronously instead) drops every render and art
 *   reply of a request posted before it.
 */

import type { CameraRecord, Transform, Warning } from "castplane";

import type { ArtBuffers } from "./art_buffers.js";
import type { DocSummary } from "./doc_summary.js";
import type { RayPoints } from "./observer.js";

/** Every object's transform, in the scene's object order. */
export type PoseEntries = [string, Transform][];

/** What the main thread asks of one render (read by {@link CoreClient} when it posts the request). */
export interface RenderParams {
  /** The camera block the core renders (`PlaneSession.block()`; any validated form). */
  block: unknown;
  /** `compose`'s `hidden_lines` and `project_scene`'s `umbra`. */
  hidden: boolean;
  umbra: boolean;
  /** `write_svg`'s layers: null = all six (`LAYER_IDS`, the DOM overlay), a list = the `<img>` mode's checked subset. */
  layers: string[] | null;
  /** The checked layers in §2.10 order: a `quick` reply whose all-layer SVG is longer than `IMG_MODE_THRESHOLD` is
   * written again with these and shown through the `<img>` overlay. */
  quick_layers: string[];
  hidden_style: "dashed" | "omit";
  /** Reply `quick` (hidden lines and umbra off) before `final` when `hidden || umbra`. */
  two_phase: boolean;
  /** The layers of the drawing on the observer's frame (`line_art`'s set). */
  art_layers: string[];
  /** The request's drag flag (recorded in the frame records). */
  dragging: boolean;
  /** Whether a reply to this request is shown through the `<img>` overlay (`layers !== null`). */
  img: boolean;
  /** Published with {@link CoreClient.publish_pose} right before the render (null: the pose is unchanged). */
  transforms: PoseEntries | null;
  /** Anything the caller wants back with the reply (e.g. the block's focal length for the status line). */
  meta?: unknown;
}

// ---------------------------------------------------------------------------- messages, main → worker
export interface SceneMessage { type: "scene"; gen: number; scene: unknown }
export interface PoseMessage { type: "pose"; gen: number; transforms: PoseEntries }
export interface RenderMessage {
  type: "render"; req: number; gen: number; block: unknown; hidden: boolean; umbra: boolean; layers: string[] | null;
  quick_layers: string[]; hidden_style: "dashed" | "omit"; two_phase: boolean; art_layers: string[]; dragging: boolean;
}
export interface ArtMessage { type: "art"; req: number; gen: number; art_layers: string[] }
export interface DownloadMessage {
  type: "download"; req: number; gen: number; kind: "svg" | "json"; layers: string[]; hidden_style: "dashed" | "omit";
  hidden: boolean; umbra: boolean; block: unknown; scene_name: string;
}
export type ToWorker = SceneMessage | PoseMessage | RenderMessage | ArtMessage | DownloadMessage;

// ---------------------------------------------------------------------------- messages, worker → main
export interface RenderedReply {
  type: "rendered"; req: number; gen: number; phase: "quick" | "final";
  /** The writer's text (all six layers, or the request's / the quick phase's subset when `img`). */
  svg: string;
  /** Whether `svg` is a layer subset for the `<img>` overlay (the request's `layers`, or a long quick SVG). */
  img: boolean;
  rec: CameraRecord;
  art: ArtBuffers;
  ray_points: RayPoints;
  warnings: Warning[];
  summary: DocSummary;
  /** B + C + SVG (+ the drawing's packing) in the worker. */
  core_ms: number;
  /** The worker's stage A of the latest `pose` not yet reported (`stage_a_ran`), else its last one. */
  stage_a_ms: number | null;
  stage_a_ran: boolean;
}
export interface StaleReply { type: "stale"; req: number }
export interface ArtReply { type: "art"; req: number; gen: number; art: ArtBuffers; ray_points: RayPoints }
export interface DownloadedReply { type: "downloaded"; req: number; gen: number; kind: "svg" | "json"; filename: string; mime: string; text: string }
export interface ErrorReply { type: "error"; req: number | null; message: string }
export type FromWorker = RenderedReply | StaleReply | ArtReply | DownloadedReply | ErrorReply;

/** The bookkeeping of one posted render. */
export interface RequestInfo {
  req: number;
  gen: number;
  dragging: boolean;
  img: boolean;
  two_phase: boolean;
  meta: unknown;
}

export interface ClientCallbacks {
  /** A render reply to apply (current gen, not superseded, not settled). */
  rendered(reply: RenderedReply, info: RequestInfo): void;
  art?(reply: ArtReply): void;
  downloaded?(reply: DownloadedReply): void;
  /** An exception in the worker (`info` is the render's when it was one, else null). */
  error?(reply: ErrorReply, info: RequestInfo | null): void;
}

/** The transport (a `Worker.postMessage`; the transfer list holds the `ArrayBuffer`s to move). */
export type Post = (message: ToWorker, transfer?: ArrayBuffer[]) => void;

/** Value equality of two pose lists (ids, order, and every number with `Object.is`). */
export function same_entries(a: PoseEntries, b: PoseEntries): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    const [ia, ta] = a[i]!, [ib, tb] = b[i]!;
    if (ia !== ib || !same3(ta.position, tb.position) || !same3(ta.rotation_deg, tb.rotation_deg)) return false;
  }
  return true;
}

const same3 = (p: readonly number[], q: readonly number[]): boolean =>
  p.length === q.length && p.every((x, i) => Object.is(x, q[i]));

const copy_entries = (t: PoseEntries): PoseEntries =>
  t.map(([id, x]) => [id, { ...x, position: [...x.position] as Transform["position"], rotation_deg: [...x.rotation_deg] as Transform["rotation_deg"] }]);

export class CoreClient {
  /** The scene generation the worker holds (after the messages posted so far). */
  gen = 0;
  private req_n = 0;
  private posted: PoseEntries | null = null;
  /** The render request in flight (posted, its first reply not yet received). */
  private flight: RequestInfo | null = null;
  /** The newest render posted (its `final` reply is still applied while it is the newest). */
  private newest: RequestInfo | null = null;
  private want = false;
  private settled_req = 0;
  private final_wait: number | null = null;

  constructor(private readonly post: Post, private readonly cb: ClientCallbacks, private readonly params: () => RenderParams | null) {}

  /** Whether a render is in flight. */
  get in_flight(): boolean {
    return this.flight !== null;
  }

  /** Whether another render is wanted after the one in flight. */
  get dirty(): boolean {
    return this.want;
  }

  /** Whether the newest render's `final` reply is still to come (its `quick` one was applied). */
  get final_pending(): boolean {
    return this.final_wait !== null;
  }

  /** The last request number used. */
  get last_req(): number {
    return this.req_n;
  }

  /** A new scene (a load): `scene` message, a new gen; the scene's transforms become the posted pose. Every pending
   * request is forgotten (its replies carry an old gen). */
  load(scene: unknown, transforms: PoseEntries): number {
    this.gen += 1;
    this.posted = copy_entries(transforms);
    this.flight = null;
    this.newest = null;
    this.want = false;
    this.final_wait = null;
    this.post({ type: "scene", gen: this.gen, scene });
    return this.gen;
  }

  /** Post the transforms when they differ from the last posted ones (a new gen); equal ones post nothing and keep the
   * gen. Returns the current gen. */
  publish_pose(transforms: PoseEntries): number {
    if (this.posted !== null && same_entries(this.posted, transforms)) return this.gen;
    this.gen += 1;
    this.posted = copy_entries(transforms);
    this.final_wait = null;
    this.post({ type: "pose", gen: this.gen, transforms: copy_entries(transforms) });
    return this.gen;
  }

  /** A render is wanted: posted now when none is in flight, else after the in-flight one is answered. */
  request(): void {
    if (this.flight !== null) {
      this.want = true;
      return;
    }
    this.send();
  }

  /** The main thread rendered synchronously: every render / art reply of a request posted so far is ignored, and
   * nothing is in flight or wanted any more. */
  settle(): void {
    this.settled_req = this.req_n;
    this.flight = null;
    this.newest = null;
    this.want = false;
    this.final_wait = null;
  }

  /** Re-pack the drawing of the worker's last document with other layers (a layer checkbox in the DOM mode). */
  request_art(art_layers: string[]): number {
    this.req_n += 1;
    this.post({ type: "art", req: this.req_n, gen: this.gen, art_layers: [...art_layers] });
    return this.req_n;
  }

  /** The download texts of the resting document of `block` (the worker renders it when needed). */
  download(d: Omit<DownloadMessage, "type" | "req" | "gen">): number {
    this.req_n += 1;
    this.post({ type: "download", req: this.req_n, gen: this.gen, ...d });
    return this.req_n;
  }

  /** A message from the worker. */
  on_message(m: FromWorker): void {
    switch (m.type) {
      case "rendered": return this.on_rendered(m);
      case "stale": return this.on_answered(m.req);
      case "art":
        if (m.gen === this.gen && m.req > this.settled_req) this.cb.art?.(m);
        return;
      case "downloaded":
        if (m.gen === this.gen) this.cb.downloaded?.(m);
        return;
      case "error": {
        const info = m.req !== null && this.flight?.req === m.req ? this.flight : m.req !== null && this.newest?.req === m.req ? this.newest : null;
        if (info !== null && this.final_wait === info.req) this.final_wait = null;
        if (m.req !== null) this.on_answered(m.req);
        this.cb.error?.(m, info);
        return;
      }
    }
  }

  private on_rendered(m: RenderedReply): void {
    const info = this.flight?.req === m.req ? this.flight : this.newest?.req === m.req ? this.newest : null;
    const first = this.flight?.req === m.req;
    const two = info !== null && info.two_phase && m.phase === "quick";
    if (m.phase === "final" && this.final_wait === m.req) this.final_wait = null;
    if (first && two) this.final_wait = m.req;
    if (info !== null && m.req > this.settled_req && m.gen === this.gen && info.gen === this.gen && this.newest?.req === m.req) {
      this.cb.rendered(m, info);
    } else if (two && this.final_wait === m.req) this.final_wait = null;
    if (first) this.on_answered(m.req);
  }

  /** The in-flight render `req` was answered: the next one goes out now when wanted. */
  private on_answered(req: number): void {
    if (this.flight?.req !== req) return;
    this.flight = null;
    if (this.want) {
      this.want = false;
      this.send();
    }
  }

  private send(): void {
    const p = this.params();
    if (p === null) return;
    if (p.transforms !== null) this.publish_pose(p.transforms);
    this.req_n += 1;
    const info: RequestInfo = { req: this.req_n, gen: this.gen, dragging: p.dragging, img: p.img, two_phase: p.two_phase, meta: p.meta };
    this.flight = info;
    this.newest = info;
    this.final_wait = null;
    this.post({ type: "render", req: info.req, gen: info.gen, block: p.block, hidden: p.hidden, umbra: p.umbra, layers: p.layers,
      quick_layers: p.quick_layers, hidden_style: p.hidden_style, two_phase: p.two_phase, art_layers: [...p.art_layers],
      dragging: p.dragging });
  }
}
