/**
 * The engine of the core worker of the web UI (contract §5.4.11: "running B + C + SVG in a Web Worker: acceptable (pure
 * functions, no shared state)"). It holds the loaded scene and its stage A, re-runs stage A when the main thread posts
 * new object transforms (`pose`), and answers `render`, `art` and `download` requests with the same pure functions the
 * main thread would run (`project_scene`, `compose`, `write_svg`, `download.ts`), on an equal scene, so every document,
 * SVG and download is byte-identical to the synchronous path. The message shapes and the scheduling rules are in
 * `core_client.ts`.
 *
 * Two phases: a resting render (`two_phase`, hidden lines or umbra on) is answered first with the `quick` document
 * (hidden lines and umbra off: the §5.4.11 drag document) and then, from a later task, with the `final` one. A `render`,
 * `pose` or `scene` message that arrives before the final phase has started drops it (the main thread has moved on);
 * an `art` or `download` message runs it first (both read the final document).
 *
 * No DOM, no three.js: only `castplane` and the pure web modules. The transport and the deferral of the final phase are
 * injected, so the engine is unit-tested in Node (`web/test/core_engine.test.ts`); `core_worker.ts` wires it to the
 * worker's global scope.
 */

import { LAYER_IDS, SceneError, compose, project_scene, shadow_geometry, write_svg } from "castplane";
import type { CameraRecord, GeometryDocument, Scene, StageA } from "castplane";

import { art_transferables, pack_art } from "./art_buffers.js";
import type {
  ArtMessage, DownloadMessage, FromWorker, PoseMessage, RenderMessage, RenderedReply, SceneMessage, ToWorker,
} from "./core_client.js";
import { doc_summary_of } from "./doc_summary.js";
import { json_blob, svg_blob } from "./download.js";
import { line_art, vertex_ray_points } from "./observer.js";
import { clone_transform } from "./object_rotate.js";

/** The scene of the current gen. */
interface Held {
  gen: number;
  /** The loaded scene (the `scene` message); `scene` is it with the latest posted transforms. */
  scene0: Scene;
  scene: Scene;
  A: StageA | null;
  /** The stage-A error of the latest `scene` / `pose` (renders of this gen answer it as an error). */
  failed: string | null;
  stage_a_ms: number;
  /** A stage A ran (a `pose`) and no reply has reported it yet. */
  unreported: boolean;
}

/** The last rendered document of the current gen (any phase), with what it was rendered with. */
interface Last {
  gen: number;
  doc: GeometryDocument;
  rec: CameraRecord;
  block_key: string;
  hidden: boolean;
  umbra: boolean;
}

/** `ui.ts::describe_error` (the worker does not import `ui.ts`). */
export function describe(e: unknown): string {
  if (e instanceof SceneError) return `SceneError\nfield: ${e.field === "" ? "(document)" : e.field}\n${e.detail}`;
  return e instanceof Error ? `${e.name}: ${e.message}` : String(e);
}

/** Run `fn` from a later task; returns its cancel function. */
export type Defer = (fn: () => void) => () => void;

export class CoreEngine {
  private held: Held | null = null;
  private last: Last | null = null;
  /** The layers of the drawing on the observer's frame (the latest `render` / `art` message's). */
  private art_layers: string[] = [...LAYER_IDS];
  private pending_final: { msg: RenderMessage; cancel: () => void } | null = null;

  constructor(private readonly send: (m: FromWorker, transfer?: ArrayBuffer[]) => void, private readonly defer: Defer) {}

  /** Whether a final phase is waiting for its task. */
  get final_waiting(): boolean {
    return this.pending_final !== null;
  }

  /** One message from the main thread. */
  handle(m: ToWorker): void {
    try {
      switch (m.type) {
        case "scene": return this.on_scene(m);
        case "pose": return this.on_pose(m);
        case "render": return this.on_render(m);
        case "art": return this.on_art(m);
        case "download": return this.on_download(m);
      }
    } catch (e) {
      this.send({ type: "error", req: "req" in m ? m.req : null, message: describe(e) });
    }
  }

  private drop_final(): void {
    if (this.pending_final === null) return;
    this.pending_final.cancel();
    this.pending_final = null;
  }

  /** Run a pending final phase now (an `art` / `download` request reads the final document). */
  private flush_final(): void {
    const p = this.pending_final;
    if (p === null) return;
    this.drop_final();
    this.render_phase(p.msg, "final");
  }

  private on_scene(m: SceneMessage): void {
    this.drop_final();
    this.last = null;
    const scene = m.scene as Scene;
    const h: Held = { gen: m.gen, scene0: scene, scene, A: null, failed: null, stage_a_ms: 0, unreported: false };
    this.held = h;
    const t0 = performance.now();
    try {
      h.A = shadow_geometry(scene);
    } catch (e) {
      h.failed = describe(e);
    }
    // the main thread ran (and counted) the load's own stage A: this run is not reported as a new one
    h.stage_a_ms = performance.now() - t0;
  }

  private on_pose(m: PoseMessage): void {
    this.drop_final();
    this.last = null;
    const h = this.held;
    if (h === null) return;
    const by_id = new Map(m.transforms);
    const s0 = h.scene0;
    // `main.ts::apply_pose`'s scene: the loaded objects with these transforms (equal values, so an equal stage A)
    const scene: Scene = { ...s0, objects: s0.objects.map((o) => ({ ...o, transform: clone_transform(by_id.get(o.id) ?? o.transform) })) };
    h.gen = m.gen;
    h.scene = scene;
    h.A = null;
    h.failed = null;
    const t0 = performance.now();
    try {
      h.A = shadow_geometry(scene);
    } catch (e) {
      h.failed = describe(e);
    }
    h.stage_a_ms = performance.now() - t0;
    h.unreported = true;
  }

  /** Render `m` as phase `phase` and post the reply; false when nothing was rendered (stale or an error). */
  private render_phase(m: RenderMessage, phase: "quick" | "final"): boolean {
    const h = this.held;
    if (h === null || h.gen !== m.gen) {
      this.send({ type: "stale", req: m.req });
      return false;
    }
    try {
      if (h.A === null) throw new Error(h.failed ?? "stage A unavailable");
      const hidden = phase === "quick" ? false : m.hidden, umbra = phase === "quick" ? false : m.umbra;
      const t0 = performance.now();
      const B = project_scene(h.scene, h.A, m.block, umbra);
      const doc = compose(h.scene, B, hidden);
      let img = m.layers !== null;
      let svg = write_svg(doc, m.layers ?? LAYER_IDS, m.hidden_style);
      // a resting quick document too long for the DOM overlay is shown through the <img> overlay (the checked layers)
      if (phase === "quick" && !img && svg.length > m.img_threshold) {
        svg = write_svg(doc, m.quick_layers, m.hidden_style);
        img = true;
      }
      const core_ms = performance.now() - t0;
      const art = pack_art(line_art(doc, B.camera, 1, new Set(this.art_layers)));
      this.last = { gen: m.gen, doc, rec: B.camera, block_key: JSON.stringify(m.block), hidden, umbra };
      const reply: RenderedReply = { type: "rendered", req: m.req, gen: m.gen, phase, svg, img, rec: B.camera, art,
        ray_points: vertex_ray_points(doc, h.scene), warnings: doc.warnings, summary: doc_summary_of(doc), core_ms,
        stage_a_ms: h.unreported ? h.stage_a_ms : null, stage_a_ran: h.unreported };
      h.unreported = false;
      this.send(reply, art_transferables(art));
      return true;
    } catch (e) {
      this.send({ type: "error", req: m.req, message: describe(e) });
      return false;
    }
  }

  private on_render(m: RenderMessage): void {
    this.drop_final();
    this.art_layers = [...m.art_layers];
    const two = m.two_phase && (m.hidden || m.umbra);
    // the final phase from a later task, so a newer request that is already queued can drop it
    if (this.render_phase(m, two ? "quick" : "final") && two) {
      const cancel = this.defer(() => {
        this.pending_final = null;
        this.render_phase(m, "final");
      });
      this.pending_final = { msg: m, cancel };
    }
  }

  private on_art(m: ArtMessage): void {
    this.flush_final();
    this.art_layers = [...m.art_layers];
    const h = this.held, l = this.last;
    if (h === null || h.gen !== m.gen || l === null || l.gen !== m.gen) {
      this.send({ type: "stale", req: m.req });
      return;
    }
    const art = pack_art(line_art(l.doc, l.rec, 1, new Set(this.art_layers)));
    this.send({ type: "art", req: m.req, gen: m.gen, art, ray_points: vertex_ray_points(l.doc, h.scene) }, art_transferables(art));
  }

  private on_download(m: DownloadMessage): void {
    this.flush_final();
    const h = this.held;
    if (h === null || h.gen !== m.gen) {
      this.send({ type: "stale", req: m.req });
      return;
    }
    try {
      if (h.A === null) throw new Error(h.failed ?? "stage A unavailable");
      const key = JSON.stringify(m.block), l = this.last;
      // the resting document of `block`: the last one when it is that (same block, hidden lines, umbra), else rendered
      const doc = l !== null && l.gen === m.gen && l.block_key === key && l.hidden === m.hidden && l.umbra === m.umbra ? l.doc
        : compose(h.scene, project_scene(h.scene, h.A, m.block, m.umbra), m.hidden);
      const file = m.kind === "svg" ? svg_blob(doc, m.layers, m.scene_name, m.hidden_style) : json_blob(doc, m.scene_name);
      this.send({ type: "downloaded", req: m.req, gen: m.gen, kind: m.kind, filename: file.filename, mime: file.type, text: file.text });
    } catch (e) {
      this.send({ type: "error", req: m.req, message: describe(e) });
    }
  }
}
