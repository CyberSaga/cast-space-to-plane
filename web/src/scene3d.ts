/**
 * The three.js scene built from a validated castplane scene (contract §5.4.10): primitives, light helpers and
 * receivers. Display only — no three.js geometry is used for any geometric output, and no three.js light casts
 * or receives shadows (shadows come only from the ported core, §5.4.0).
 */

import * as THREE from "three";

import { transform_frame } from "castplane";
import type { Scene, SceneObject, StageA, Vec3 } from "castplane";

/** Per-object colours (cycled). */
const PALETTE = [0xc9d6e8, 0xe8d3c3, 0xd2e3c8, 0xe6d9ef, 0xf0e2b6, 0xc8e4e4, 0xebc9cf, 0xd9d9d9];
const LIGHT_COLOUR = 0xffcc33;

/** The local-frame geometry of a primitive (castplane local frames: base on `z = 0`, axis `+z`). */
export function primitive_geometry(obj: SceneObject): THREE.BufferGeometry {
  switch (obj.type) {
    case "box": {
      const [sx, sy, sz] = obj.size as Vec3;
      return new THREE.BoxGeometry(sx, sy, sz).translate(0, 0, sz / 2);
    }
    case "cylinder": {
      const r = obj.radius as number, h = obj.height as number;
      // three's cylinder axis is +Y: +π/2 about X turns it into +Z
      return new THREE.CylinderGeometry(r, r, h, 64).rotateX(Math.PI / 2).translate(0, 0, h / 2);
    }
    case "cone": {
      const r = obj.radius as number, h = obj.height as number;
      return new THREE.ConeGeometry(r, h, 64).rotateX(Math.PI / 2).translate(0, 0, h / 2);
    }
    case "sphere": {
      const r = obj.radius as number;
      return new THREE.SphereGeometry(r, 48, 24).translate(0, 0, r);
    }
    case "prism": {
      const shape = new THREE.Shape((obj.polygon ?? []).map(([x, y]) => new THREE.Vector2(x, y)));
      return new THREE.ExtrudeGeometry(shape, { depth: obj.height as number, bevelEnabled: false });
    }
    default:
      throw new Error(`build_scene3d: unsupported object type ${JSON.stringify(obj.type)}`);
  }
}

/** The object's world matrix from the core's `transform_frame` (`R`, `position`): three never interprets Euler angles. */
export function object_matrix(obj: SceneObject): THREE.Matrix4 {
  const [R, p] = transform_frame(obj.transform);
  return new THREE.Matrix4().set(
    R[0][0], R[0][1], R[0][2], p[0],
    R[1][0], R[1][1], R[1][2], p[1],
    R[2][0], R[2][1], R[2][2], p[2],
    0, 0, 0, 1,
  );
}

/** Scene centre and horizontal extent (from stage A's bounding box when given). */
function extent_of(scene: Scene, A?: StageA): { centre: Vec3; extent: number } {
  if (A !== undefined) {
    const [lo, hi] = A.bbox;
    const centre: Vec3 = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2];
    return { centre, extent: Math.max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2], A.scene_scale, 1) };
  }
  const ps = scene.objects.map((o) => o.transform.position);
  const xs = ps.map((p) => p[0]), ys = ps.map((p) => p[1]);
  const centre: Vec3 = [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2, 0];
  return { centre, extent: Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 1) };
}

/** Dispose every geometry and material under `root`. */
export function dispose_scene3d(root: THREE.Object3D): void {
  root.traverse((o) => {
    const m = o as THREE.Mesh;
    if (m.geometry !== undefined) m.geometry.dispose();
    const mat = (m as { material?: THREE.Material | THREE.Material[] }).material;
    if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
    else if (mat !== undefined) mat.dispose();
  });
}

/** The three.js group of a scene: one mesh per object, light helpers + shading lights, receivers. */
export function build_scene3d(scene: Scene, A?: StageA): THREE.Group {
  const group = new THREE.Group();
  group.name = "castplane-scene";
  const { centre, extent } = extent_of(scene, A);

  scene.objects.forEach((obj, i) => {
    const material = new THREE.MeshLambertMaterial({ color: PALETTE[i % PALETTE.length] });
    const mesh = new THREE.Mesh(primitive_geometry(obj), material);
    mesh.name = obj.id;
    mesh.matrixAutoUpdate = false;
    mesh.matrix.copy(object_matrix(obj));
    mesh.matrixWorldNeedsUpdate = true;
    mesh.castShadow = false;
    mesh.receiveShadow = false;
    group.add(mesh);
  });

  for (const light of scene.lights) {
    if (light.type === "point") {
      const p = light.position as Vec3;
      const marker = new THREE.Mesh(
        new THREE.SphereGeometry(Math.max(0.04, 0.012 * extent), 16, 8),
        new THREE.MeshBasicMaterial({ color: LIGHT_COLOUR }),
      );
      marker.name = `light:${light.id}`;
      marker.position.set(p[0], p[1], p[2]);
      group.add(marker);
      const pl = new THREE.PointLight(0xffffff, 2.2, 0, 0);
      pl.position.set(p[0], p[1], p[2]);
      pl.castShadow = false;
      group.add(pl);
    } else {
      const d = new THREE.Vector3(...(light.direction as Vec3)).normalize();
      const origin = new THREE.Vector3(centre[0], centre[1], Math.max(centre[2], 0));
      const arrow = new THREE.ArrowHelper(d, origin, 0.4 * extent, LIGHT_COLOUR);
      arrow.name = `light:${light.id}`;
      group.add(arrow);
      const dl = new THREE.DirectionalLight(0xffffff, 2.2);
      dl.position.copy(origin.clone().addScaledVector(d, extent));
      dl.target.position.copy(origin);
      dl.castShadow = false;
      group.add(dl, dl.target);
    }
  }
  group.add(new THREE.AmbientLight(0xffffff, 0.9));

  for (const rec of scene.receivers) {
    const size = 4 * extent;
    const plane = new THREE.Mesh(
      new THREE.PlaneGeometry(size, size),
      new THREE.MeshLambertMaterial({ color: 0xf4f4f0, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }),
    );
    plane.name = `receiver:${rec.id}`;
    const n = new THREE.Vector3(...rec.normal);
    plane.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
    // the receiver point nearest to the scene centre's ground point (n·X = offset)
    const c0 = new THREE.Vector3(centre[0], centre[1], 0);
    plane.position.copy(c0).addScaledVector(n, rec.offset - n.dot(c0));
    plane.receiveShadow = false;
    group.add(plane);
    const divisions = Math.min(200, Math.max(8, Math.round(size)));
    const grid = new THREE.GridHelper(size, divisions, 0xbbbbbb, 0xdddddd);
    grid.name = `grid:${rec.id}`;
    // GridHelper lies in XZ: +π/2 about X puts it in the plane's local XY, then the plane's orientation
    grid.quaternion.copy(plane.quaternion).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 2));
    grid.position.copy(plane.position);
    group.add(grid);
  }
  return group;
}
