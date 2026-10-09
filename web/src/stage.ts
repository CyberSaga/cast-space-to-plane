/**
 * One three.js view (contract §5.4.10): a WebGL renderer on a given `<canvas>`, its `THREE.Scene` holding the
 * scene group built by `scene3d.ts`, and a camera driven only by castplane camera blocks (`threeCamera.ts`).
 * The class holds no module state, so a second independent view (the M9 observer pane) is another instance on
 * another canvas. `letterbox` sizes a view's box to the `canvas_mm` aspect inside its viewport.
 */

import * as THREE from "three";

import { apply_camera_block } from "./threeCamera.js";
import type { CameraBlockLike } from "./types.js";
import { dispose_scene3d } from "./scene3d.js";

export class Stage3D {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene3: THREE.Scene;
  readonly camera3: THREE.PerspectiveCamera;
  private group3: THREE.Group | null = null;

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
    this.renderer.shadowMap.enabled = false; // normative (§5.4.0): shadows come only from the ported core
    this.renderer.setPixelRatio(window.devicePixelRatio || 1);
    this.scene3 = new THREE.Scene();
    this.scene3.background = new THREE.Color(0xffffff);
    this.camera3 = new THREE.PerspectiveCamera();
  }

  /** The current scene group (`null` before the first scene). */
  get group(): THREE.Group | null {
    return this.group3;
  }

  /** Remove and dispose the current scene group, then add the one `make` builds. */
  replace_group(make: () => THREE.Group): void {
    if (this.group3 !== null) {
      this.scene3.remove(this.group3);
      dispose_scene3d(this.group3);
    }
    this.group3 = make();
    this.scene3.add(this.group3);
  }

  /** The drawing-buffer size in CSS pixels (the canvas's CSS box is left to the stylesheet). */
  set_size(w: number, h: number): void {
    this.renderer.setSize(w, h, false);
  }

  /** Draw the scene through a castplane camera block. */
  render(block: CameraBlockLike, canvas_mm: readonly number[], scene_scale: number): void {
    apply_camera_block(this.camera3, block, canvas_mm, scene_scale);
    this.renderer.render(this.scene3, this.camera3);
  }

  /** Draw the scene through any three.js camera (the M9 observer camera, §5.6.4; not a castplane camera). */
  render_with(camera: THREE.Camera): void {
    this.renderer.render(this.scene3, camera);
  }
}

/** Size `box` to the largest `aspect` rectangle inside `viewport` (8 px margin each side); returns `[w, h]` px. */
export function letterbox(viewport: HTMLElement, box: HTMLElement, aspect: number): [number, number] {
  const W = viewport.clientWidth - 16, H = viewport.clientHeight - 16;
  let w = W, h = W / aspect;
  if (h > H) {
    h = H;
    w = H * aspect;
  }
  w = Math.max(1, Math.floor(w));
  h = Math.max(1, Math.floor(w / aspect));
  box.style.width = `${w}px`;
  box.style.height = `${h}px`;
  return [w, h];
}
