/**
 * The three.js scene built from a validated castplane scene (contract §5.4.10): primitives, light helpers and
 * receivers. Display only — no three.js geometry is used for any geometric output, and no three.js light casts
 * or receives shadows (shadows come only from the ported core, §5.4.0).
 */

import * as THREE from "three";

import { transform_frame } from "castplane";
import type { ObjectRecord, Scene, SceneObject, StageA, Vec3 } from "castplane";

import { OBJECT_ID_KEY, RECEIVER_ID_KEY, light_colour, receiver_plates, shading_intensity } from "./helpers3d.js";
import { mesh_positions } from "./mesh3d.js";

/** Per-object colours (cycled). */
const PALETTE = [0xc9d6e8, 0xe8d3c3, 0xd2e3c8, 0xe6d9ef, 0xf0e2b6, 0xc8e4e4, 0xebc9cf, 0xd9d9d9];

/** The geometry of a primitive in its local frame (castplane local frames: base on `z = 0`, axis `+z`); a mesh object
 * with its stage-A record `rec` is the exception: world coordinates (`mesh_positions(...).world`, identity matrix). */
export function primitive_geometry(obj: SceneObject, rec?: ObjectRecord): THREE.BufferGeometry {
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
    case "mesh": {
      // contract §5.4.10 (phase 2): a BufferGeometry from the core's triangles (scale applied, welded, the original
      // surface's fans) — stage A's record when given (no second preprocessing), else `prepared_mesh`; flat normals
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(mesh_positions(obj, rec).positions, 3));
      geometry.computeVertexNormals();
      return geometry;
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

/**
 * Move the node of object `id` in a group built by {@link build_scene3d} (§5.8.12: an object drag updates the node
 * transform, no rebuild): `matrix` is `object_matrix(obj)` for a primitive, or, for a `mesh` object (whose geometry is
 * in world coordinates), the translation by the drag's displacement. Returns whether the node was found.
 */
export function set_object_node(group: THREE.Group | null, id: string, matrix: THREE.Matrix4): boolean {
  const node = group?.children.find((c) => c.userData[OBJECT_ID_KEY] === id);
  if (node === undefined) return false;
  node.matrix.copy(matrix);
  node.matrixWorldNeedsUpdate = true;
  return true;
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

/** The three.js group of a scene: one mesh per object, light helpers + shading lights per light, receivers (the
 * unbounded ground as a large plane with a grid, each bounded receiver as a plate over its `bounds`). */
export function build_scene3d(scene: Scene, A?: StageA): THREE.Group {
  const group = new THREE.Group();
  group.name = "castplane-scene";
  const { centre, extent } = extent_of(scene, A);

  scene.objects.forEach((obj, i) => {
    // a mesh object may be open (the per-face fallback of §5.2.5): draw both sides of its triangles
    const material = new THREE.MeshLambertMaterial({ color: PALETTE[i % PALETTE.length],
      side: obj.type === "mesh" ? THREE.DoubleSide : THREE.FrontSide });
    // stage A's record of a mesh object carries its triangles over world-frame vertices: drawn with the identity
    const rec = obj.type === "mesh" ? A?.objects.find((o) => o.id === obj.id) : undefined;
    const world = rec !== undefined && rec.triangles !== undefined;
    const mesh = new THREE.Mesh(primitive_geometry(obj, rec), material);
    mesh.name = obj.id;
    mesh.userData[OBJECT_ID_KEY] = obj.id;
    mesh.matrixAutoUpdate = false;
    mesh.matrix.copy(world ? new THREE.Matrix4() : object_matrix(obj));
    mesh.matrixWorldNeedsUpdate = true;
    mesh.castShadow = false;
    mesh.receiveShadow = false;
    group.add(mesh);
  });

  // lights as helpers only (§5.4.10), one colour per light (phase 2: several lights); the shading lights share
  // one total intensity so a scene with several lights is not drawn brighter
  const intensity = shading_intensity(scene.lights.length);
  scene.lights.forEach((light, i) => {
    const colour = light_colour(i);
    if (light.type === "point") {
      const p = light.position as Vec3;
      const marker = new THREE.Mesh(
        new THREE.SphereGeometry(Math.max(0.04, 0.012 * extent), 16, 8),
        new THREE.MeshBasicMaterial({ color: colour }),
      );
      marker.name = `light:${light.id}`;
      marker.position.set(p[0], p[1], p[2]);
      group.add(marker);
      const pl = new THREE.PointLight(0xffffff, intensity, 0, 0);
      pl.position.set(p[0], p[1], p[2]);
      pl.castShadow = false;
      group.add(pl);
    } else {
      const d = new THREE.Vector3(...(light.direction as Vec3)).normalize();
      const origin = new THREE.Vector3(centre[0], centre[1], Math.max(centre[2], 0));
      const arrow = new THREE.ArrowHelper(d, origin, 0.4 * extent, colour);
      arrow.name = `light:${light.id}`;
      group.add(arrow);
      const dl = new THREE.DirectionalLight(0xffffff, intensity);
      dl.position.copy(origin.clone().addScaledVector(d, extent));
      dl.target.position.copy(origin);
      dl.castShadow = false;
      group.add(dl, dl.target);
    }
  });
  group.add(new THREE.AmbientLight(0xffffff, 0.9));

  const receiver_material = (colour: number) => new THREE.MeshLambertMaterial({ color: colour, side: THREE.DoubleSide,
    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
  const plates = receiver_plates(scene.receivers);
  scene.receivers.forEach((rec, i) => {
    const plate = plates[i]!;
    if (plate.kind === "plate") {
      // a bounded receiver (phase 2): a plate over its convex `bounds` (world coordinates) and its outline
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(plate.positions, 3));
      geometry.computeVertexNormals();
      const mesh = new THREE.Mesh(geometry, receiver_material(i === 0 ? 0xf4f4f0 : 0xeceae2));
      mesh.name = `receiver:${rec.id}`;
      mesh.userData[RECEIVER_ID_KEY] = rec.id;
      mesh.receiveShadow = false;
      group.add(mesh);
      const edge = new THREE.Line(
        new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(plate.outline, 3)),
        new THREE.LineBasicMaterial({ color: 0x9a9a90 }),
      );
      edge.name = `outline:${rec.id}`;
      group.add(edge);
      return;
    }
    // the unbounded ground: a plane of 4x the scene extent with a grid
    const size = 4 * extent;
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(size, size), receiver_material(0xf4f4f0));
    ground.name = `receiver:${rec.id}`;
    ground.userData[RECEIVER_ID_KEY] = rec.id;
    const n = new THREE.Vector3(...rec.normal);
    ground.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
    // the receiver point nearest to the scene centre's ground point (the plane n·X + offset = 0)
    const c0 = new THREE.Vector3(centre[0], centre[1], 0);
    ground.position.copy(c0).addScaledVector(n, -(n.dot(c0) + rec.offset));
    ground.receiveShadow = false;
    group.add(ground);
    const divisions = Math.min(200, Math.max(8, Math.round(size)));
    const grid = new THREE.GridHelper(size, divisions, 0xbbbbbb, 0xdddddd);
    grid.name = `grid:${rec.id}`;
    // GridHelper lies in XZ: +π/2 about X puts it in the plane's local XY, then the plane's orientation
    grid.quaternion.copy(ground.quaternion).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 2));
    grid.position.copy(ground.position);
    group.add(grid);
  });
  return group;
}
