/**
 * The observer pane of M9 (contract §5.6.3–§5.6.5): a second {@link Stage3D} on its own canvas showing the scene
 * (`scene3d.ts`, the same builder as the drawing pane), plus the board group built from the pure arrays of
 * `observer.ts` (eye, board patch, frame with the drawing on it, frustum, principal point, D and g lines, pivot,
 * vertex rays) and HTML labels. Its camera is an ordinary `THREE.PerspectiveCamera` (40° vertical field of view) set
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
import type { Board, BoardLabel, FillStyle, HandleHit, Handles, LineArt, LineStyle, ObserverView, VertexRays } from "./observer.js";
import { OBJECT_ID_KEY, RECEIVER_ID_KEY, object_id_of } from "./helpers3d.js";
import { build_scene3d } from "./scene3d.js";
import { Stage3D } from "./stage.js";

/** Opacity of the receiver plates in the observer pane (see {@link ObserverPane.set_scene}). */
const RECEIVER_OPACITY = 0.5;

/** What one observer update draws. */
export interface ObserverGeometry {
  board: Board;
  art: LineArt;
  rays: VertexRays | null;
  /** M10 (§5.7.9): the ring and the arrow, or null (no handles). */
  handles?: Handles | null;
  /** M10: the id of a picked pivot object (its label `旋轉中心：<id>`). */
  pivot_id?: string | null;
  /** M10: the handle being dragged (drawn thicker). */
  active?: "ring" | "arrow" | null;
}

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

const flat = (pairs: readonly (readonly [Vec3, Vec3])[]): number[] => {
  const out: number[] = [];
  for (const [a, b] of pairs) out.push(a[0], a[1], a[2], b[0], b[1], b[2]);
  return out;
};

/** The observer pane: one three.js view, the board group and the labels. */
export class ObserverPane {
  readonly stage: Stage3D;
  readonly camera: THREE.PerspectiveCamera;
  view: ObserverView = initial_view();
  private readonly board = new THREE.Group();
  private readonly lineMats = new Map<string, LineMaterial>();
  private readonly dotMats = new Map<string, THREE.PointsMaterial>();
  private readonly fillMats = new Map<string, THREE.MeshBasicMaterial>();
  private readonly labelEls = new Map<string, HTMLDivElement>();
  private labels: BoardLabel[] = [];
  private boardNow: Board | null = null;
  private handlesNow: Handles | null = null;
  private W = 1;
  private H = 1;

  constructor(canvas: HTMLCanvasElement, private readonly labelBox: HTMLElement) {
    this.stage = new Stage3D(canvas);
    this.stage.scene3.background = new THREE.Color(0xf3f2ec);
    this.camera = new THREE.PerspectiveCamera(OBSERVER_FOV_DEG, 1, OBSERVER_NEAR_M, OBSERVER_FAR_M);
    this.board.name = "observer-board";
    this.stage.scene3.add(this.board);
  }

  /** Show `scene` (a second build of the `scene3d` group: three.js objects belong to one scene each). Its receiver
   * plates are see-through here (opacity {@link RECEIVER_OPACITY}, no depth write; this build's own materials, so the
   * drawing pane is unchanged): a board, frame or frustum below a receiver stays visible (§5.6.5). */
  set_scene(scene: Scene, A: StageA): void {
    this.stage.replace_group(() => {
      const group = build_scene3d(scene, A);
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

  /** The names of the board group's children (smoke test). */
  get names(): string[] {
    return this.board.children.map((c) => c.name);
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

  private add_lines(name: string, key: string, spec: LineSpec, pairs: readonly (readonly [Vec3, Vec3])[]): void {
    if (pairs.length === 0) return;
    const g = new LineSegmentsGeometry();
    g.setPositions(flat(pairs));
    const line = new LineSegments2(g, this.line_mat(key, spec));
    if (spec.dash !== undefined) line.computeLineDistances();
    line.name = name;
    line.renderOrder = spec.order;
    this.board.add(line);
  }

  private add_dots(name: string, spec: DotSpec, pts: readonly Vec3[]): void {
    if (pts.length === 0) return;
    let m = this.dotMats.get(name);
    if (m === undefined) {
      m = new THREE.PointsMaterial({ color: spec.color, size: spec.size, sizeAttenuation: false, map: dot_texture(spec.shape),
        transparent: true, alphaTest: 0.5, depthTest: false });
      this.dotMats.set(name, m);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts.flatMap((p) => [p[0], p[1], p[2]]), 3));
    const pointsObj = new THREE.Points(g, m);
    pointsObj.name = name;
    pointsObj.renderOrder = 10;
    this.board.add(pointsObj);
  }

  private fill_mat(key: string, color: number, opacity: number): THREE.MeshBasicMaterial {
    let m = this.fillMats.get(key);
    if (m === undefined) {
      m = new THREE.MeshBasicMaterial({ color, opacity, transparent: true, side: THREE.DoubleSide, depthWrite: false });
      this.fillMats.set(key, m);
    }
    return m;
  }

  /** A filled polygon: triangulated in its own 2D frame (`uv`, canvas mm or patch coordinates), drawn at `world`. */
  private add_fill(name: string, mat: THREE.Material, uv: readonly (readonly number[])[], world: readonly Vec3[], order: number): void {
    const tris = THREE.ShapeUtils.triangulateShape(uv.map((p) => new THREE.Vector2(p[0], p[1])), []);
    if (tris.length === 0) return;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(world.flatMap((p) => [p[0], p[1], p[2]]), 3));
    g.setIndex(tris.flat());
    const mesh = new THREE.Mesh(g, mat);
    mesh.name = name;
    mesh.renderOrder = order;
    this.board.add(mesh);
  }

  /** Rebuild the board group from one frame's geometry (the materials are kept). */
  update(geo: ObserverGeometry): void {
    for (const c of [...this.board.children]) {
      this.board.remove(c);
      (c as THREE.Mesh).geometry.dispose();
    }
    const b = geo.board;
    this.boardNow = b;
    const loop = (pts: readonly Vec3[]): [Vec3, Vec3][] => pts.map((p, i) => [p, pts[(i + 1) % pts.length]!]);
    const square: [number, number][] = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
    // board patch and frame (back-filled), then the drawing on the frame
    this.add_fill("board:patch", this.fill_mat("patch", 0x2563d9, 0.08), square, b.patch, 1);
    this.add_lines("board:patch-outline", "patch", HELPER_LINES.patch, loop(b.patch));
    this.add_fill("board:frame-back", this.fill_mat("frame", 0xffffff, 0.72), square, b.corners, 2);
    const fills = new Map<FillStyle, LineArt["fills"]>();
    for (const f of geo.art.fills) {
      const list = fills.get(f.style) ?? [];
      list.push(f);
      fills.set(f.style, list);
    }
    for (const [style, list] of fills) {
      const spec = ART_FILLS[style];
      const mat = this.fill_mat(`art:${style}`, spec.color, spec.opacity);
      for (const f of list) this.add_fill(`art-fill:${style}`, mat, f.uv, f.world, 3);
    }
    const lines = new Map<LineStyle, [Vec3, Vec3][]>();
    for (const s of geo.art.segments) {
      const list = lines.get(s.style) ?? [];
      list.push(s.world);
      lines.set(s.style, list);
    }
    for (const [style, pairs] of lines) this.add_lines(`art:${style}`, `art:${style}`, ART_LINES[style], pairs);
    this.add_lines("board:frame", "frame", HELPER_LINES.frame, loop(b.corners));
    // frustum, D line, g line
    const fr = frustum(b);
    this.add_lines("frustum", "frustum", HELPER_LINES.frustum, fr.solid);
    this.add_lines("frustum:far", "frustum_far", HELPER_LINES.frustum_far, fr.dotted);
    this.add_lines("d-line", "d_line", HELPER_LINES.d_line, [[b.E, b.Q]]);
    this.add_lines("g-line", "g_line", HELPER_LINES.g_line, [[b.Q, b.P]]);
    // vertex rays
    const r = geo.rays;
    if (r !== null) {
      this.add_lines("rays:sight", "sight", HELPER_LINES.sight, r.sight);
      this.add_lines("rays:light", "light", HELPER_LINES.light, r.light);
      this.add_lines("rays:shadow-sight", "shadow_sight", HELPER_LINES.shadow_sight, r.shadow_sight);
      this.add_dots("dots:crossing", DOTS.crossing, r.crossings);
      this.add_dots("dots:shadow", DOTS.shadow, r.shadows);
      this.add_dots("dots:shadow-crossing", DOTS.shadow_crossing, r.shadow_crossings);
    }
    this.add_dots("dots:Q", DOTS.Q, [b.Q]);
    this.add_dots("dots:pivot", DOTS.pivot, [b.P]);
    this.add_dots("dots:E", DOTS.E, [b.E]);
    // M10 handles (§5.7.9): the orange dashed ring around Q and the blue arrow Q → tip (towards the eye)
    const h = geo.handles ?? null;
    this.handlesNow = h;
    if (h !== null) {
      const ring: [Vec3, Vec3][] = h.ring.map((p, i) => [p, h.ring[(i + 1) % h.ring.length]!]);
      const ra = geo.active === "ring", aa = geo.active === "arrow";
      this.add_lines("handle:ring", ra ? "ring_active" : "ring", ra ? HELPER_LINES.ring_active : HELPER_LINES.ring, ring);
      this.add_lines("handle:arrow", aa ? "arrow_active" : "arrow", aa ? HELPER_LINES.arrow_active : HELPER_LINES.arrow,
        [[h.Q, h.tip], ...arrow_head(h.Q, h.tip, b.r)]);
      this.add_dots("handle:tip", DOTS.tip, [h.tip]);
    }
    this.labels = board_labels(b, { pivot_id: geo.pivot_id ?? null, ...(h !== null ? { tip: h.tip } : {}) });
  }

  /** The handles of the last update (null without handles). */
  get last_handles(): Handles | null {
    return this.handlesNow;
  }

  /**
   * The object under the pane point `p` (CSS px) nearest to the observer camera, or null (§5.7.8 item 10): a ray cast
   * into this pane's scene group; only objects count (lights, receivers and grids are skipped).
   */
  pick_object(p: Vec2): string | null {
    const group = this.stage.group;
    if (group === null) return null;
    this.render_camera();
    const ndc = new THREE.Vector2((p[0] / this.W) * 2 - 1, -(p[1] / this.H) * 2 + 1);
    const ray = new THREE.Raycaster();
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
