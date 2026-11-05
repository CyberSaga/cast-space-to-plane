/**
 * The observer pane of M9 (contract §5.6.3–§5.6.5): a second {@link Stage3D} on its own canvas showing the scene
 * (`scene3d.ts`, the same builder as the drawing pane), plus the board group built from the pure arrays of
 * `observer.ts` (eye, board patch, frame with the drawing on it, frustum, principal point, D and g lines, pivot,
 * vertex rays) and HTML labels. D83: the vertex rays and the object rings live in a second group, so the 「板子」
 * checkbox can hide the board group and its labels while they stay. The pane is incremental ({@link ObserverFrame}):
 * pooled line objects, each part redrawn only when its inputs changed, the drawing kept in canvas mm under one
 * matrix. Its camera is an ordinary `THREE.PerspectiveCamera` (40° vertical field of view) set
 * from {@link observer_basis}; left drag orbits it, the wheel and a two-finger pinch zoom it. Nothing here changes the
 * drawing camera, the document or the SVG (read-only, §5.6.0).
 */

import * as THREE from "three";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import { LineSegments2 } from "three/addons/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/addons/lines/LineSegmentsGeometry.js";

import type { Scene, StageA, Vec2, Vec3 } from "castplane";

import {
  CLICK_PX, OBSERVER_FAR_M, OBSERVER_FOV_DEG, OBSERVER_NEAR_M, board_labels, first_inside, frustum, initial_view, layout_labels,
  observer_accepts_pointer, observer_basis, orbit_view, pinch_view, zoom_view,
} from "./observer.js";
import type {
  Board, BoardLabel, FillStyle, HandleHit, Handles, LineStyle, ObjectRingSet, ObserverView, VertexRays,
} from "./observer.js";
import type { ArtBuffers } from "./art_buffers.js";
import { OBJECT_ID_KEY, RECEIVER_ID_KEY, object_id_of } from "./helpers3d.js";
import { build_scene3d } from "./scene3d.js";
import { Stage3D } from "./stage.js";

/** Opacity of the receiver plates in the observer pane (see {@link ObserverPane.set_scene}). */
const RECEIVER_OPACITY = 0.5;

/**
 * M10 handle input of the observer pane (§5.7.9): on pointer-down the pane asks {@link hit} first (arrow tip > ring);
 * a hit starts a handle drag (`begin`, `move` with the **total** displacement from pointer-down, `end`; `cancel` when
 * a second finger turns it into an observer pinch), anything else is an observer gesture. A pointer-up within
 * {@link CLICK_PX} of its pointer-down on blank space is a click (`click`, the object pivot pick); the observer view is
 * then restored to its pointer-down state.
 */
export interface HandleInput {
  hit(p: Vec2, touch: boolean): HandleHit;
  begin(hit: NonNullable<HandleHit>, p: Vec2): void;
  move(dx: number, dy: number, alt: boolean): void;
  end(): void;
  cancel(): void;
  click(p: Vec2): void;
}

interface LineSpec {
  color: number;
  width: number;
  dash?: [number, number];
  opacity?: number;
  order: number;
}

/** Colours follow the drawing pane's SVG styles (§2.10) for the drawing and the demo's light palette for the rest. */
const ART_LINES: Record<LineStyle, LineSpec> = {
  horizon: { color: 0x999999, width: 1.2, order: 4 },
  objects: { color: 0x111111, width: 1.6, order: 4 },
  objects_back: { color: 0x111111, width: 1, dash: [0.06, 0.04], order: 4 },
  hidden: { color: 0x777777, width: 1, dash: [0.03, 0.03], order: 4 },
  terminator: { color: 0x333355, width: 1.1, order: 4 },
  cast_shadow: { color: 0x000000, width: 1.2, order: 4 },
  ray_LP: { color: 0xdd3333, width: 1, order: 4 },
  ray_FQ: { color: 0x3366cc, width: 1, order: 4 },
  ray_PQ: { color: 0x33aa33, width: 1, order: 4 },
};
const ART_FILLS: Record<FillStyle, { color: number; opacity: number }> = {
  form_shadow: { color: 0x333355, opacity: 0.18 },
  cast_shadow: { color: 0x000000, opacity: 0.3 },
};
const HELPER_LINES = {
  patch: { color: 0x2563d9, width: 1, opacity: 0.6, order: 1 },
  frame: { color: 0x2563d9, width: 2.6, order: 5 },
  frustum: { color: 0x8d8b83, width: 1, order: 6 },
  frustum_far: { color: 0x8d8b83, width: 1, dash: [0.04, 0.1], order: 6 },
  d_line: { color: 0x47463f, width: 1.2, dash: [0.12, 0.08], order: 6 },
  g_line: { color: 0xa233c4, width: 1.3, dash: [0.1, 0.12], order: 6 },
  sight: { color: 0x8d8b83, width: 1, opacity: 0.75, order: 6 },
  light: { color: 0xd9a000, width: 1.5, dash: [0.1, 0.06], order: 6 },
  shadow_sight: { color: 0x282c46, width: 1, dash: [0.04, 0.06], opacity: 0.55, order: 6 },
  ring: { color: 0xe8730c, width: 2.4, dash: [0.09, 0.06], order: 7 },
  ring_active: { color: 0xe8730c, width: 4, dash: [0.09, 0.06], order: 7 },
  arrow: { color: 0x1d4ed8, width: 3, order: 7 },
  arrow_active: { color: 0x1d4ed8, width: 5, order: 7 },
  // M11 object rings (§5.8.4): x red, y green, z blue
  object_ring_0: { color: 0xd93025, width: 2.4, order: 8 },
  object_ring_1: { color: 0x1e9e48, width: 2.4, order: 8 },
  object_ring_2: { color: 0x1f5fd6, width: 2.4, order: 8 },
  object_ring_0_active: { color: 0xd93025, width: 4.5, order: 8 },
  object_ring_1_active: { color: 0x1e9e48, width: 4.5, order: 8 },
  object_ring_2_active: { color: 0x1f5fd6, width: 4.5, order: 8 },
} satisfies Record<string, LineSpec>;

interface DotSpec {
  color: number;
  size: number;
  shape: "circle" | "diamond";
}
const DOTS = {
  E: { color: 0x111111, size: 15, shape: "circle" },
  Q: { color: 0x47463f, size: 6, shape: "circle" },
  pivot: { color: 0xa233c4, size: 16, shape: "diamond" },
  crossing: { color: 0x23231f, size: 6, shape: "circle" },
  shadow: { color: 0xd9a000, size: 6, shape: "circle" },
  shadow_crossing: { color: 0xd9a000, size: 7, shape: "circle" },
  tip: { color: 0x1d4ed8, size: 15, shape: "circle" },
} satisfies Record<string, DotSpec>;

function dot_texture(shape: "circle" | "diamond"): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d")!;
  g.beginPath();
  if (shape === "circle") g.arc(32, 32, 28, 0, Math.PI * 2);
  else {
    g.moveTo(32, 4);
    g.lineTo(60, 32);
    g.lineTo(32, 60);
    g.lineTo(4, 32);
    g.closePath();
  }
  g.fillStyle = "#fff";
  g.fill();
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** The two dashed art styles: their dash lengths are metres, their line distances canvas mm (`dashScale`). */
const DASHED_ART: readonly LineStyle[] = ["objects_back", "hidden"];
/** The triangles of a quad in {@link Board.corners} order (the patch and the frame back). */
const SQUARE_TRIS: number[] = THREE.ShapeUtils.triangulateShape(
  ([[-1, -1], [1, -1], [1, 1], [-1, 1]] as const).map(([a, b]) => new THREE.Vector2(a, b)), []).flat();

/** Writes segments (6 floats each, `x0 y0 z0 x1 y1 z1`) into the start of a pooled buffer. */
type SegmentWriter = (a: Float32Array) => void;

const pairs_writer = (pairs: readonly (readonly [Vec3, Vec3])[]): SegmentWriter => (a) => {
  let j = 0;
  for (const [p, q] of pairs) {
    a[j] = p[0]; a[j + 1] = p[1]; a[j + 2] = p[2]; a[j + 3] = q[0]; a[j + 4] = q[1]; a[j + 5] = q[2];
    j += 6;
  }
};

/** The closed polyline through `pts` (segment `i` joins point `i` and point `i + 1 mod n`). */
const loop_writer = (pts: readonly Vec3[]): SegmentWriter => (a) => {
  const n = pts.length;
  for (let i = 0, j = 0; i < n; i++, j += 6) {
    const p = pts[i]!, q = pts[(i + 1) % n]!;
    a[j] = p[0]; a[j + 1] = p[1]; a[j + 2] = p[2]; a[j + 3] = q[0]; a[j + 4] = q[1]; a[j + 5] = q[2];
  }
};

/** Canvas-mm segments (4 floats each, `u0 v0 u1 v1`) on the plane `z = 0`. */
const uv_writer = (uv: Float32Array): SegmentWriter => (a) => {
  for (let i = 0, j = 0; i + 3 < uv.length; i += 4, j += 6) {
    a[j] = uv[i]!; a[j + 1] = uv[i + 1]!; a[j + 2] = 0; a[j + 3] = uv[i + 2]!; a[j + 4] = uv[i + 3]!; a[j + 5] = 0;
  }
};

/** Value keys: the change detection of {@link ObserverPane.update} (flat lists of numbers, compared value for value). */
function key_points(out: number[], pts: readonly (readonly number[])[]): void {
  out.push(pts.length);
  for (const p of pts) out.push(p[0]!, p[1]!, p[2]!);
}
function key_pairs(out: number[], pairs: readonly (readonly [Vec3, Vec3])[]): void {
  out.push(pairs.length);
  for (const [p, q] of pairs) out.push(p[0], p[1], p[2], q[0], q[1], q[2]);
}
function same_key(a: readonly number[] | null, b: readonly number[] | null): boolean {
  if (a === null || b === null) return a === b;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

/** A pooled `LineSegments2`: its instance buffers are rewritten in place; a new geometry only when it must grow. */
interface PooledLines {
  line: LineSegments2;
  cap: number;
  pos: THREE.InstancedInterleavedBuffer;
  /** The instance distances (dashed materials only, laid out as `LineSegments2.computeLineDistances` does). */
  dist: THREE.InstancedInterleavedBuffer | null;
}

function line_geometry(cap: number, dashed: boolean): { g: LineSegmentsGeometry; pos: THREE.InstancedInterleavedBuffer;
  dist: THREE.InstancedInterleavedBuffer | null } {
  const g = new LineSegmentsGeometry();
  const pos = new THREE.InstancedInterleavedBuffer(new Float32Array(6 * cap), 6, 1);
  pos.setUsage(THREE.DynamicDrawUsage);
  g.setAttribute("instanceStart", new THREE.InterleavedBufferAttribute(pos, 3, 0));
  g.setAttribute("instanceEnd", new THREE.InterleavedBufferAttribute(pos, 3, 3));
  let dist: THREE.InstancedInterleavedBuffer | null = null;
  if (dashed) {
    dist = new THREE.InstancedInterleavedBuffer(new Float32Array(2 * cap), 2, 1);
    dist.setUsage(THREE.DynamicDrawUsage);
    g.setAttribute("instanceDistanceStart", new THREE.InterleavedBufferAttribute(dist, 1, 0));
    g.setAttribute("instanceDistanceEnd", new THREE.InterleavedBufferAttribute(dist, 1, 1));
  }
  g.instanceCount = 0;
  return { g, pos, dist };
}

/** One frame of the observer pane ({@link ObserverPane.update}): every input of the board group, the extras and the
 * placement of the drawing. */
export interface ObserverFrame {
  board: Board;
  /** D83: whether the board group (with the drawing and the board's handles) and its labels are drawn. */
  board_visible: boolean;
  /** M10 (§5.7.9): the ring and the arrow; null while the board is hidden or without a rig. */
  handles: Handles | null;
  /** M10: the id of a picked pivot object (its label `旋轉中心：<id>`). */
  pivot_id: string | null;
  /** M10: the handle being dragged (drawn thicker). */
  active: "ring" | "arrow" | null;
  /** M11 (§5.8.4): the selected object's three rings, or null. */
  object_rings: ObjectRingSet | null;
  /** M11: the axis of the object ring being dragged (drawn thicker). */
  active_axis: 0 | 1 | 2 | null;
  /** The vertex rays, or null (the 視線 checkbox unchecked). */
  rays: VertexRays | null;
  /** The drawing's placement on the frame: canvas mm (`z = 0`) → world, 16 numbers column-major
   * (`art_buffers.ts::art_frame_matrix`; `THREE.Matrix4.fromArray`). */
  art_matrix: readonly number[];
}

/**
 * The observer pane: one three.js view, the board group and the labels. Incremental: each part (board, the board's
 * handles, object rings, rays) is redrawn only when its inputs changed, into pooled line / dot objects whose GPU
 * buffers are reused; the drawing on the frame is kept in canvas mm and placed with the art matrix, so a camera
 * change moves it without a rebuild ({@link set_art} replaces its content).
 */
export class ObserverPane {
  readonly stage: Stage3D;
  readonly camera: THREE.PerspectiveCamera;
  view: ObserverView = initial_view();
  /** The board group (hidden by the 「板子」 checkbox): its parts, the drawing, the board's handles. */
  private readonly board = new THREE.Group();
  private readonly boardParts = new THREE.Group();
  /** The drawing on the frame: canvas mm under the art matrix. */
  private readonly art = new THREE.Group();
  private readonly handleParts = new THREE.Group();
  /** D83: the vertex rays and the object rings (not hidden by the 「板子」 checkbox). */
  private readonly extras = new THREE.Group();
  private readonly rayParts = new THREE.Group();
  private readonly ringParts = new THREE.Group();
  private readonly lineMats = new Map<string, LineMaterial>();
  private readonly dotMats = new Map<string, THREE.PointsMaterial>();
  private readonly fillMats = new Map<string, THREE.MeshBasicMaterial>();
  /** Pooled objects by name. */
  private readonly lines = new Map<string, PooledLines>();
  private readonly dots = new Map<string, { points: THREE.Points; cap: number }>();
  private readonly quads = new Map<string, THREE.Mesh>();
  private artFills: THREE.Mesh[] = [];
  private readonly labelEls = new Map<string, HTMLDivElement>();
  private labels: BoardLabel[] = [];
  private boardNow: Board | null = null;
  private handlesNow: Handles | null = null;
  private objectRingsNow: ObjectRingSet | null = null;
  /** The value keys of the drawn parts (null: drawn from null, or nothing drawn yet for the board). */
  private boardKey: number[] | null = null;
  private boardEquation = "";
  private handlesKey: number[] | null | undefined = undefined;
  private ringsKey: number[] | null | undefined = undefined;
  private ringsId: string | null = null;
  private raysKey: number[] | null | undefined = undefined;
  private readonly raycaster = new THREE.Raycaster();
  private W = 1;
  private H = 1;

  constructor(canvas: HTMLCanvasElement, private readonly labelBox: HTMLElement) {
    this.stage = new Stage3D(canvas);
    this.stage.scene3.background = new THREE.Color(0xf3f2ec);
    this.camera = new THREE.PerspectiveCamera(OBSERVER_FOV_DEG, 1, OBSERVER_NEAR_M, OBSERVER_FAR_M);
    this.board.name = "observer-board";
    this.boardParts.name = "observer-board-parts";
    this.art.name = "observer-art";
    this.art.matrixAutoUpdate = false;
    this.handleParts.name = "observer-handles";
    this.extras.name = "observer-extras";
    this.rayParts.name = "observer-rays";
    this.ringParts.name = "observer-object-rings";
    this.board.add(this.boardParts, this.art, this.handleParts);
    this.extras.add(this.rayParts, this.ringParts);
    this.stage.scene3.add(this.board, this.extras);
    this.precompile();
  }

  /** Compile every line, dot and fill material once (one temporary object each), so that the first selection or drag
   * does not wait for a shader compile. A failure only defers the compile to the first draw. */
  private precompile(): void {
    const tmp = new THREE.Group();
    const geos: THREE.BufferGeometry[] = [];
    const specs: [string, LineSpec][] = [
      ...Object.entries(ART_LINES).map(([k, s]) => [`art:${k}`, s] as [string, LineSpec]),
      ...Object.entries(HELPER_LINES),
    ];
    for (const [key, spec] of specs) {
      const { g, pos, dist } = line_geometry(1, spec.dash !== undefined);
      (pos.array as Float32Array).set([0, 0, 0, 1, 0, 0]);
      if (dist !== null) (dist.array as Float32Array).set([0, 1]);
      g.instanceCount = 1;
      geos.push(g);
      tmp.add(new LineSegments2(g, this.line_mat(key, spec)));
    }
    for (const key of Object.keys(DOTS) as (keyof typeof DOTS)[]) {
      const g = new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0], 3));
      geos.push(g);
      tmp.add(new THREE.Points(g, this.dot_mat(key)));
    }
    const tri = (): THREE.BufferGeometry => {
      const g = new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 0, 1, 0], 3));
      geos.push(g);
      return g;
    };
    tmp.add(new THREE.Mesh(tri(), this.fill_mat("patch", 0x2563d9, 0.08)), new THREE.Mesh(tri(), this.fill_mat("frame", 0xffffff, 0.72)));
    for (const [style, spec] of Object.entries(ART_FILLS)) tmp.add(new THREE.Mesh(tri(), this.fill_mat(`art:${style}`, spec.color, spec.opacity)));
    this.stage.scene3.add(tmp);
    try {
      this.stage.renderer.compile(this.stage.scene3, this.camera);
    } catch {
      // nothing: the shaders are then compiled at their first draw
    } finally {
      this.stage.scene3.remove(tmp);
      for (const g of geos) g.dispose();
    }
  }

  /** Show `scene` (a second build of the `scene3d` group: three.js objects belong to one scene each). Its receiver
   * plates are see-through here (opacity {@link RECEIVER_OPACITY}, no depth write; this build's own materials, so the
   * drawing pane is unchanged): a board, frame or frustum below a receiver stays visible (§5.6.5). `colours`: the
   * objects' display colours, the same as the drawing pane's 3D view (`build_scene3d`). */
  set_scene(scene: Scene, A: StageA, colours?: ReadonlyMap<string, number>): void {
    this.stage.replace_group(() => {
      const group = build_scene3d(scene, A, colours);
      for (const c of group.children) {
        if (typeof c.userData[RECEIVER_ID_KEY] !== "string") continue;
        const mats = (c as THREE.Mesh).material;
        for (const m of Array.isArray(mats) ? mats : [mats]) {
          m.transparent = true;
          m.opacity = RECEIVER_OPACITY;
          m.depthWrite = false;
        }
      }
      return group;
    });
  }

  set_size(w: number, h: number): void {
    this.W = Math.max(1, w);
    this.H = Math.max(1, h);
    this.stage.set_size(this.W, this.H);
    for (const m of this.lineMats.values()) m.resolution.set(this.W, this.H);
  }

  /** The board of the last update (smoke test). */
  get last_board(): Board | null {
    return this.boardNow;
  }

  /** The pane's size in CSS px. */
  get size(): [number, number] {
    return [this.W, this.H];
  }

  /** The pane's aspect `W / H` (framing, §5.6.4). */
  get aspect(): number {
    return this.W / this.H;
  }

  /** The names of the drawn objects: the board group's while it is shown (its parts, the drawing's `art-fill:<style>` /
   * `art:<style>` of the non-empty styles, the board's handles), then the rays' and object rings' (smoke test). */
  get names(): string[] {
    const out: string[] = [];
    const walk = (g: THREE.Object3D): void => {
      for (const c of g.children) {
        if (c instanceof THREE.Group) walk(c);
        else out.push(c.name);
      }
    };
    if (this.board.visible) walk(this.board);
    walk(this.extras);
    return out;
  }

  /** D83: whether the board group is shown (the 「板子」 checkbox; smoke test). */
  get board_shown(): boolean {
    return this.board.visible;
  }

  /** The current label texts (smoke test). */
  get label_texts(): string[] {
    return this.labels.map((l) => l.text);
  }

  private line_mat(key: string, spec: LineSpec): LineMaterial {
    let m = this.lineMats.get(key);
    if (m === undefined) {
      m = new LineMaterial({
        color: spec.color, linewidth: spec.width, worldUnits: false, dashed: spec.dash !== undefined,
        dashSize: spec.dash?.[0] ?? 1, gapSize: spec.dash?.[1] ?? 0,
        transparent: spec.opacity !== undefined, opacity: spec.opacity ?? 1,
      });
      m.resolution.set(this.W, this.H);
      this.lineMats.set(key, m);
    }
    return m;
  }

  private dot_mat(key: keyof typeof DOTS): THREE.PointsMaterial {
    let m = this.dotMats.get(key);
    if (m === undefined) {
      const spec: DotSpec = DOTS[key];
      m = new THREE.PointsMaterial({ color: spec.color, size: spec.size, sizeAttenuation: false, map: dot_texture(spec.shape),
        transparent: true, alphaTest: 0.5, depthTest: false });
      this.dotMats.set(key, m);
    }
    return m;
  }

  private fill_mat(key: string, color: number, opacity: number): THREE.MeshBasicMaterial {
    let m = this.fillMats.get(key);
    if (m === undefined) {
      m = new THREE.MeshBasicMaterial({ color, opacity, transparent: true, side: THREE.DoubleSide, depthWrite: false });
      this.fillMats.set(key, m);
    }
    return m;
  }

  /**
   * The pooled line object `name` with `n` segments written by `write` (material `key` / `spec`), in `parent`; with
   * `n = 0` it is detached (not drawn, not in {@link names}). A dashed material gets the instance distances that
   * `LineSegments2.computeLineDistances` computes (cumulative, in the geometry's local units).
   */
  private set_lines(name: string, key: string, spec: LineSpec, parent: THREE.Group, n: number, write: SegmentWriter): void {
    let e = this.lines.get(name);
    if (n === 0) {
      if (e !== undefined && e.line.parent !== null) e.line.parent.remove(e.line);
      return;
    }
    const mat = this.line_mat(key, spec);
    if (e === undefined || e.cap < n) {
      const cap = Math.max(n, e === undefined ? 0 : Math.ceil(1.5 * e.cap), 8);
      const { g, pos, dist } = line_geometry(cap, spec.dash !== undefined);
      if (e === undefined) {
        const line = new LineSegments2(g, mat);
        line.name = name;
        line.frustumCulled = false; // its bounding volumes would cover the whole (partly stale) buffer
        e = { line, cap, pos, dist };
        this.lines.set(name, e);
      } else {
        e.line.geometry.dispose();
        e.line.geometry = g;
        e.cap = cap;
        e.pos = pos;
        e.dist = dist;
      }
    }
    e.line.material = mat;
    e.line.renderOrder = spec.order;
    const a = e.pos.array as Float32Array;
    write(a);
    e.pos.clearUpdateRanges();
    e.pos.addUpdateRange(0, 6 * n);
    e.pos.needsUpdate = true;
    if (e.dist !== null) {
      const d = e.dist.array as Float32Array;
      let s = 0;
      for (let i = 0, j = 0; i < n; i++, j += 6) {
        d[2 * i] = s;
        s += Math.hypot(a[j + 3]! - a[j]!, a[j + 4]! - a[j + 1]!, a[j + 5]! - a[j + 2]!);
        d[2 * i + 1] = s;
      }
      e.dist.clearUpdateRanges();
      e.dist.addUpdateRange(0, 2 * n);
      e.dist.needsUpdate = true;
    }
    e.line.geometry.instanceCount = n;
    if (e.line.parent !== parent) parent.add(e.line);
  }

  private set_pairs(name: string, key: string, spec: LineSpec, parent: THREE.Group, pairs: readonly (readonly [Vec3, Vec3])[]): void {
    this.set_lines(name, key, spec, parent, pairs.length, pairs_writer(pairs));
  }

  /** The pooled dot object `name` (material {@link DOTS}`[key]`) at `pts`, in `parent`; detached when empty. */
  private set_dots(name: string, key: keyof typeof DOTS, parent: THREE.Group, pts: readonly Vec3[]): void {
    let e = this.dots.get(name);
    const n = pts.length;
    if (n === 0) {
      if (e !== undefined && e.points.parent !== null) e.points.parent.remove(e.points);
      return;
    }
    if (e === undefined || e.cap < n) {
      const cap = Math.max(n, e === undefined ? 0 : Math.ceil(1.5 * e.cap), 4);
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(3 * cap), 3).setUsage(THREE.DynamicDrawUsage));
      if (e === undefined) {
        const points = new THREE.Points(g, this.dot_mat(key));
        points.name = name;
        points.renderOrder = 10;
        points.frustumCulled = false;
        e = { points, cap };
        this.dots.set(name, e);
      } else {
        e.points.geometry.dispose();
        e.points.geometry = g;
        e.cap = cap;
      }
    }
    const attr = e.points.geometry.getAttribute("position") as THREE.BufferAttribute;
    const a = attr.array as Float32Array;
    pts.forEach((p, i) => a.set(p, 3 * i));
    attr.clearUpdateRanges();
    attr.addUpdateRange(0, 3 * n);
    attr.needsUpdate = true;
    e.points.geometry.setDrawRange(0, n);
    if (e.points.parent !== parent) parent.add(e.points);
  }

  /** The pooled filled quad `name` over `corners` ({@link Board.corners} order), in the board parts. */
  private set_quad(name: string, mat: THREE.Material, corners: readonly Vec3[], order: number): void {
    let mesh = this.quads.get(name);
    if (mesh === undefined) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(12), 3).setUsage(THREE.DynamicDrawUsage));
      g.setIndex(SQUARE_TRIS);
      mesh = new THREE.Mesh(g, mat);
      mesh.name = name;
      mesh.renderOrder = order;
      mesh.frustumCulled = false;
      this.quads.set(name, mesh);
      this.boardParts.add(mesh);
    }
    const attr = mesh.geometry.getAttribute("position") as THREE.BufferAttribute;
    const a = attr.array as Float32Array;
    corners.slice(0, 4).forEach((p, i) => a.set(p, 3 * i));
    attr.needsUpdate = true;
  }

  /**
   * Replace the drawing on the frame (a new document's): one pooled line object per non-empty style (canvas mm,
   * `z = 0`, placed by the art matrix of {@link update}); the fills are rebuilt (triangulated in canvas mm).
   */
  set_art(art: ArtBuffers): void {
    this.apply_art(
      art.lines.map(({ style, uv }) => ({ style, n: Math.floor(uv.length / 4), write: uv_writer(uv) })),
      art.fills.map(({ style, uv }) => {
        const m = Math.floor(uv.length / 2);
        const pts: THREE.Vector2[] = [];
        const pos = new Float32Array(3 * m);
        for (let i = 0; i < m; i++) {
          pts.push(new THREE.Vector2(uv[2 * i]!, uv[2 * i + 1]!));
          pos[3 * i] = uv[2 * i]!;
          pos[3 * i + 1] = uv[2 * i + 1]!;
        }
        return { style, uv: pts, pos };
      }),
    );
  }

  private apply_art(lines: { style: LineStyle; n: number; write: SegmentWriter }[],
    fills: { style: FillStyle; uv: THREE.Vector2[]; pos: Float32Array }[]): void {
    const seen = new Set<string>();
    for (const l of lines) {
      const name = `art:${l.style}`;
      seen.add(name);
      this.set_lines(name, name, ART_LINES[l.style], this.art, l.n, l.write);
    }
    for (const [name, e] of this.lines) {
      if (name.startsWith("art:") && !seen.has(name) && e.line.parent !== null) e.line.parent.remove(e.line);
    }
    for (const m of this.artFills) {
      this.art.remove(m);
      m.geometry.dispose();
    }
    this.artFills = [];
    for (const f of fills) {
      const tris = THREE.ShapeUtils.triangulateShape(f.uv, []);
      if (tris.length === 0) continue;
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(f.pos, 3));
      g.setIndex(tris.flat());
      const spec = ART_FILLS[f.style];
      const mesh = new THREE.Mesh(g, this.fill_mat(`art:${f.style}`, spec.color, spec.opacity));
      mesh.name = `art-fill:${f.style}`;
      mesh.renderOrder = 3;
      this.art.add(mesh);
      this.artFills.push(mesh);
    }
  }

  /**
   * One frame: place the drawing (the art matrix, every call) and redraw each part whose inputs changed value for
   * value — the board (patch, frame back, frame, frustum, D and g lines, Q / pivot / E), the board's handles, the
   * object rings, the vertex rays. Cheap when nothing changed.
   */
  update(frame: ObserverFrame): void {
    const M = frame.art_matrix;
    this.art.matrix.fromArray(M as number[]);
    // the columns (s·r', s·u', f) of `art_frame_matrix` are left-handed (r' × u' = −f): with a negative determinant
    // three.js flips the winding and culls the front-sided `LineMaterial` quads. The z column is never used (the
    // drawing has z = 0), so it is negated instead.
    if (this.art.matrix.determinant() < 0) {
      const e = this.art.matrix.elements;
      e[8] = -e[8]!;
      e[9] = -e[9]!;
      e[10] = -e[10]!;
    }
    this.art.matrixWorldNeedsUpdate = true;
    // the art matrix turns canvas mm into metres (its uniform scale); the art dash lengths are metres
    const s = Math.hypot(M[0]!, M[1]!, M[2]!);
    for (const style of DASHED_ART) this.line_mat(`art:${style}`, ART_LINES[style]).dashScale = s;
    this.boardNow = frame.board;
    this.draw_rays(frame.rays);
    this.draw_object_rings(frame.object_rings, frame.active_axis);
    const shown = frame.board_visible;
    this.board.visible = shown;
    if (!shown) {
      // D83: 「板子」 unchecked: no board group, no board handles (the caller passes none), no labels; the drawn parts
      // keep their keys and are compared again when the board is shown
      this.handlesNow = null;
      this.labels = [];
      return;
    }
    const b = frame.board;
    this.draw_board(b);
    const h = frame.handles;
    this.handlesNow = h;
    this.draw_handles(h, frame.active, b);
    this.labels = board_labels(b, { pivot_id: frame.pivot_id, ...(h !== null ? { tip: h.tip } : {}) });
  }

  private draw_board(b: Board): void {
    const key = [b.D, b.g];
    key_points(key, [b.E, b.Q, b.P]);
    key_points(key, b.corners);
    key_points(key, b.patch);
    if (same_key(this.boardKey, key) && this.boardEquation === b.equation) return;
    this.boardKey = key;
    this.boardEquation = b.equation;
    const p = this.boardParts;
    this.set_quad("board:patch", this.fill_mat("patch", 0x2563d9, 0.08), b.patch, 1);
    this.set_lines("board:patch-outline", "patch", HELPER_LINES.patch, p, b.patch.length, loop_writer(b.patch));
    this.set_quad("board:frame-back", this.fill_mat("frame", 0xffffff, 0.72), b.corners, 2);
    this.set_lines("board:frame", "frame", HELPER_LINES.frame, p, b.corners.length, loop_writer(b.corners));
    const fr = frustum(b);
    this.set_pairs("frustum", "frustum", HELPER_LINES.frustum, p, fr.solid);
    this.set_pairs("frustum:far", "frustum_far", HELPER_LINES.frustum_far, p, fr.dotted);
    this.set_pairs("d-line", "d_line", HELPER_LINES.d_line, p, [[b.E, b.Q]]);
    this.set_pairs("g-line", "g_line", HELPER_LINES.g_line, p, [[b.Q, b.P]]);
    this.set_dots("dots:Q", "Q", p, [b.Q]);
    this.set_dots("dots:pivot", "pivot", p, [b.P]);
    this.set_dots("dots:E", "E", p, [b.E]);
  }

  /** M10 handles (§5.7.9): the orange dashed ring around Q and the blue arrow Q → tip (towards the eye). */
  private draw_handles(h: Handles | null, active: "ring" | "arrow" | null, b: Board): void {
    let key: number[] | null = null;
    if (h !== null) {
      key = [active === "ring" ? 1 : active === "arrow" ? 2 : 0];
      key_points(key, h.ring);
      key_points(key, [h.Q, h.tip, b.r]);
    }
    if (this.handlesKey !== undefined && same_key(this.handlesKey, key)) return;
    this.handlesKey = key;
    const p = this.handleParts;
    if (h === null) {
      this.set_lines("handle:ring", "ring", HELPER_LINES.ring, p, 0, () => {});
      this.set_lines("handle:arrow", "arrow", HELPER_LINES.arrow, p, 0, () => {});
      this.set_dots("handle:tip", "tip", p, []);
      return;
    }
    const ra = active === "ring", aa = active === "arrow";
    this.set_lines("handle:ring", ra ? "ring_active" : "ring", ra ? HELPER_LINES.ring_active : HELPER_LINES.ring, p,
      h.ring.length, loop_writer(h.ring));
    this.set_pairs("handle:arrow", aa ? "arrow_active" : "arrow", aa ? HELPER_LINES.arrow_active : HELPER_LINES.arrow, p,
      [[h.Q, h.tip], ...arrow_head(h.Q, h.tip, b.r)]);
    this.set_dots("handle:tip", "tip", p, [h.tip]);
  }

  /** M11 object rings (§5.8.4): one closed polyline per world axis around the object's pivot (D83: extras group). */
  private draw_object_rings(orings: ObjectRingSet | null, active_axis: 0 | 1 | 2 | null): void {
    this.objectRingsNow = orings;
    let key: number[] | null = null;
    if (orings !== null) {
      key = [active_axis ?? -1];
      key_points(key, [orings.centre]);
      for (const ring of orings.rings) key_points(key, ring);
    }
    const id = orings?.id ?? null;
    if (this.ringsKey !== undefined && same_key(this.ringsKey, key) && this.ringsId === id) return;
    this.ringsKey = key;
    this.ringsId = id;
    for (const axis of [0, 1, 2] as const) {
      const ring = orings?.rings[axis] ?? [];
      const k = `object_ring_${axis}${active_axis === axis ? "_active" : ""}` as keyof typeof HELPER_LINES;
      this.set_lines(`object-ring:${"xyz"[axis]}`, k, HELPER_LINES[k], this.ringParts, ring.length, loop_writer(ring));
    }
  }

  /** The vertex rays (D83: in the extras group, shown with or without the board). */
  private draw_rays(r: VertexRays | null): void {
    let key: number[] | null = null;
    if (r !== null) {
      key = [];
      key_pairs(key, r.sight);
      key_pairs(key, r.light);
      key_pairs(key, r.shadow_sight);
      key_points(key, r.crossings);
      key_points(key, r.shadows);
      key_points(key, r.shadow_crossings);
    }
    if (this.raysKey !== undefined && same_key(this.raysKey, key)) return;
    this.raysKey = key;
    const x = this.rayParts;
    this.set_pairs("rays:sight", "sight", HELPER_LINES.sight, x, r?.sight ?? []);
    this.set_pairs("rays:light", "light", HELPER_LINES.light, x, r?.light ?? []);
    this.set_pairs("rays:shadow-sight", "shadow_sight", HELPER_LINES.shadow_sight, x, r?.shadow_sight ?? []);
    this.set_dots("dots:crossing", "crossing", x, r?.crossings ?? []);
    this.set_dots("dots:shadow", "shadow", x, r?.shadows ?? []);
    this.set_dots("dots:shadow-crossing", "shadow_crossing", x, r?.shadow_crossings ?? []);
  }

  /** The handles of the last update (null without handles, D83 also while the board is hidden). */
  get last_handles(): Handles | null {
    return this.handlesNow;
  }

  /** M11: the object rings of the last update (null with no object selected). */
  get last_object_rings(): ObjectRingSet | null {
    return this.objectRingsNow;
  }

  /**
   * The object under the pane point `p` (CSS px) nearest to the observer camera, or null (§5.7.8 item 10): a ray cast
   * into this pane's scene group; only objects count (lights, receivers and grids are skipped).
   */
  pick_object(p: Vec2): string | null {
    const group = this.stage.group;
    if (group === null) return null;
    group.updateMatrixWorld(true); // a pick right after a pose change, before any draw, still sees the posed meshes
    this.render_camera();
    const ndc = new THREE.Vector2((p[0] / this.W) * 2 - 1, -(p[1] / this.H) * 2 + 1);
    const ray = this.raycaster;
    ray.setFromCamera(ndc, this.camera);
    const objects = group.children.filter((c) => typeof c.userData[OBJECT_ID_KEY] === "string");
    for (const hit of ray.intersectObjects(objects, true)) {
      const id = object_id_of(hit.object, group);
      if (id !== null) return id;
    }
    return null;
  }

  /** Draw the observer view and place the labels (a label whose anchor is behind the observer is hidden). */
  render(): void {
    const basis = this.render_camera();
    this.stage.render_with(this.camera);
    this.place_labels(basis);
  }

  /** Set the three.js observer camera from {@link view} (the same projection as `observer_project`). */
  private render_camera(): ReturnType<typeof observer_basis> {
    const basis = observer_basis(this.view);
    const { pos, r, u, f } = basis;
    const cam = this.camera;
    cam.aspect = this.W / this.H;
    cam.matrixAutoUpdate = false;
    cam.matrix.set(
      r[0], u[0], -f[0], pos[0],
      r[1], u[1], -f[1], pos[1],
      r[2], u[2], -f[2], pos[2],
      0, 0, 0, 1,
    );
    cam.matrixWorld.copy(cam.matrix);
    cam.matrixWorldInverse.copy(cam.matrixWorld).invert();
    cam.updateProjectionMatrix();
    return basis;
  }

  private place_labels(basis: ReturnType<typeof observer_basis>): void {
    const seen = new Set<string>();
    // the equation label needs ≈ 160 px to its right; the others are placed at their anchor; overlapping labels are
    // moved apart (`layout_labels`)
    const boxes = layout_labels(this.labels.map((l) => ({ id: l.id, text: l.text,
      p: first_inside(basis, this.W, this.H, [l.at, ...(l.alt ?? [])], l.alt !== undefined ? [4, 170, 4, 24] : [0, 0, 0, 0]) })));
    this.labels.forEach((l, i) => {
      seen.add(l.id);
      let el = this.labelEls.get(l.id);
      if (el === undefined) {
        el = document.createElement("div");
        el.className = `obs-label obs-label-${l.id}`;
        this.labelBox.append(el);
        this.labelEls.set(l.id, el);
      }
      const box = boxes[i]!;
      el.hidden = box === null;
      if (box !== null) {
        if (el.textContent !== l.text) el.textContent = l.text;
        el.style.transform = `translate(${box.x.toFixed(1)}px, ${box.y.toFixed(1)}px)`;
      }
    });
    for (const [id, el] of this.labelEls) if (!seen.has(id)) el.hidden = true;
  }

  /**
   * Pointer input of the pane (§5.6.4; M10 §5.7.9): one pointer drags (a handle when `handles` reports a hit, else the
   * observer orbit; a mouse's left button only), the wheel zooms, two pointers pinch (zoom from the state at the
   * pinch's start; a running handle drag is cancelled). `changed` is called after every change of {@link view}.
   */
  attach_input(el: HTMLElement, changed: () => void, handles: HandleInput | null = null): void {
    const pointers = new Map<number, [number, number]>();
    let pinch: { d0: number; view0: ObserverView } | null = null;
    /** The single-pointer gesture: a handle drag or the observer orbit (with its pointer-down view for a click). */
    let one: { kind: "handle" | "orbit"; x0: number; y0: number; moved: number; view0: ObserverView } | null = null;
    const local = (ev: PointerEvent): Vec2 => {
      const b = el.getBoundingClientRect();
      return [ev.clientX - b.left, ev.clientY - b.top];
    };
    const spread = (): number => {
      const [a, b] = [...pointers.values()];
      return a !== undefined && b !== undefined ? Math.hypot(a[0] - b[0], a[1] - b[1]) : 0;
    };
    el.addEventListener("contextmenu", (ev) => ev.preventDefault());
    el.addEventListener("pointerdown", (ev) => {
      if (pointers.size >= 2 || !observer_accepts_pointer(ev.pointerType, ev.button)) return;
      pointers.set(ev.pointerId, [ev.clientX, ev.clientY]);
      el.setPointerCapture(ev.pointerId);
      ev.preventDefault();
      if (pointers.size === 2) {
        if (one?.kind === "handle") handles?.cancel();
        one = null;
        pinch = { d0: Math.max(spread(), 1), view0: { ...this.view } };
        return;
      }
      pinch = null;
      const p = local(ev);
      const hit = handles?.hit(p, ev.pointerType === "touch") ?? null;
      one = { kind: hit !== null ? "handle" : "orbit", x0: ev.clientX, y0: ev.clientY, moved: 0, view0: { ...this.view } };
      if (hit !== null) handles!.begin(hit, p);
    });
    el.addEventListener("pointermove", (ev) => {
      const last = pointers.get(ev.pointerId);
      if (last === undefined) {
        if (handles !== null && ev.pointerType === "mouse" && pointers.size === 0) {
          // the cursor belongs to the canvas under the mouse (its own `cursor: grab` rule), hence a class on the pane
          el.classList.toggle("on-handle", handles.hit(local(ev), false) !== null);
        }
        return;
      }
      const dx = ev.clientX - last[0], dy = ev.clientY - last[1];
      pointers.set(ev.pointerId, [ev.clientX, ev.clientY]);
      if (pinch !== null) {
        this.view = pinch_view(pinch.view0, pinch.d0, spread());
        changed();
        return;
      }
      if (one === null || (dx === 0 && dy === 0)) return;
      const tx = ev.clientX - one.x0, ty = ev.clientY - one.y0;
      one.moved = Math.max(one.moved, Math.hypot(tx, ty));
      if (one.kind === "handle") {
        handles!.move(tx, ty, ev.altKey);
        return;
      }
      this.view = orbit_view(this.view, dx, dy);
      changed();
    });
    const end = (ev: PointerEvent): void => {
      if (!pointers.delete(ev.pointerId)) return;
      const g = one;
      one = null;
      if (pinch !== null) {
        pinch = null; // the remaining finger (if any) does nothing until it is lifted
        return;
      }
      if (g === null) return;
      if (g.kind === "handle") {
        handles!.end();
        return;
      }
      if (handles !== null && ev.type === "pointerup" && g.moved < CLICK_PX) {
        this.view = g.view0; // a click does not move the observer
        changed();
        handles.click(local(ev));
      }
    };
    el.addEventListener("pointerup", end);
    el.addEventListener("pointercancel", end);
    el.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      this.view = zoom_view(this.view, ev.deltaY);
      changed();
    }, { passive: false });
  }
}

/** The arrowhead at `tip` of the arrow `Q → tip`: two strokes back towards `Q`, in the plane of the arrow and `side`. */
function arrow_head(Q: Vec3, tip: Vec3, side: Vec3): [Vec3, Vec3][] {
  const d: Vec3 = [Q[0] - tip[0], Q[1] - tip[1], Q[2] - tip[2]];
  const l = Math.hypot(d[0], d[1], d[2]);
  if (!(l > 0)) return [];
  const k = Math.min(0.12, 0.3 * l) / l, w = Math.min(0.06, 0.15 * l);
  const back: Vec3 = [tip[0] + d[0] * k, tip[1] + d[1] * k, tip[2] + d[2] * k];
  return [1, -1].map((s) => [tip, [back[0] + s * w * side[0], back[1] + s * w * side[1], back[2] + s * w * side[2]]] as [Vec3, Vec3]);
}
