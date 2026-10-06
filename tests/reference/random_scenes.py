"""Seeded random scene generator producing valid spec §4 scene dicts (spec §7.3, contract §4).

Scenes contain 1–10 primitives of all five types (prisms with concave simple polygons),
random rotations (objects are lifted so that nothing is below the ground), one random
point or directional light above the ground and a random camera looking at the scene.
Shares no code with ``castplane``; the only geometry re-implemented here is the Z-Y-X
placement of :mod:`tests.reference.raycast` (used to lift tilted objects).
"""

from __future__ import annotations

import math

import numpy as np

from tests.reference.raycast import rotation_matrix

TYPES = ("box", "cylinder", "sphere", "cone", "prism")
LAYERS = ["horizon", "objects", "form_shadow", "cast_shadow", "construction", "labels"]
FRAME_MM = [36.0, 24.0]
CANVAS_MM = [360.0, 240.0]


# --------------------------------------------------------------------------- geometry helpers
def star_polygon(rng: np.random.Generator, n: int, r_min: float, r_max: float,
                 concave: bool) -> list[list[float]]:
    """Counter-clockwise star-shaped (hence simple) polygon with ``n`` vertices; with
    ``concave`` the radii alternate so that the polygon has reflex vertices."""
    gaps = rng.uniform(0.4, 1.0, size=n)
    angles = np.cumsum(gaps)
    angles = angles / angles[-1] * 2.0 * math.pi
    angles = angles - angles[0] + rng.uniform(0.0, 2.0 * math.pi)
    if concave:
        radii = np.where(np.arange(n) % 2 == 0, r_max, r_min)
        radii = radii * rng.uniform(0.9, 1.1, size=n)
    else:
        radii = rng.uniform(0.8 * r_max, r_max, size=n)
    pts = [[float(r * math.cos(a)), float(r * math.sin(a))] for r, a in zip(radii, angles)]
    if polygon_area(pts) < 0:
        pts.reverse()
    return [[round(x, 6), round(y, 6)] for x, y in pts]


def polygon_area(pts) -> float:
    P = np.asarray(pts, dtype=np.float64)
    x, y = P[:, 0], P[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def local_extreme_points(obj: dict, n_circle: int = 64) -> np.ndarray:
    """Points of the primitive (local frame) whose transform bounds the object: corners,
    sampled rim circles, apex, or (for a sphere) the centre with the radius handled by
    the caller."""
    kind = obj["type"]
    if kind == "box":
        sx, sy, sz = obj["size"]
        xs = [-sx / 2, sx / 2]
        ys = [-sy / 2, sy / 2]
        return np.array([[x, y, z] for x in xs for y in ys for z in (0.0, sz)])
    if kind == "prism":
        poly = np.asarray(obj["polygon"], dtype=np.float64)
        h = obj["height"]
        return np.vstack([np.c_[poly, np.zeros(len(poly))], np.c_[poly, np.full(len(poly), h)]])
    th = np.linspace(0.0, 2.0 * math.pi, n_circle, endpoint=False)
    r = obj["radius"]
    rim = np.c_[r * np.cos(th), r * np.sin(th), np.zeros(n_circle)]
    if kind == "cylinder":
        top = rim + np.array([0.0, 0.0, obj["height"]])
        return np.vstack([rim, top])
    if kind == "cone":
        return np.vstack([rim, [[0.0, 0.0, obj["height"]]]])
    if kind == "sphere":
        return np.array([[0.0, 0.0, r]])
    raise ValueError(kind)


def world_extreme_points(obj: dict) -> np.ndarray:
    """World-space extreme points (a sphere contributes its centre +- radius along z/x/y)."""
    R = rotation_matrix(obj["transform"]["rotation_deg"])
    pos = np.asarray(obj["transform"]["position"], dtype=np.float64)
    pts = local_extreme_points(obj) @ R.T + pos
    if obj["type"] == "sphere":
        r = obj["radius"]
        c = pts[0]
        pts = np.array([c + np.array(v) * r for v in
                        [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]])
    return pts


def random_object(rng: np.random.Generator, idx: int, kind: str | None = None,
                  allow_tilt: bool = True) -> dict:
    """One random primitive resting on (or slightly above) the ground."""
    kind = kind or TYPES[int(rng.integers(len(TYPES)))]
    obj: dict = {"id": "obj%d" % idx, "type": kind}
    if kind == "box":
        obj["size"] = [round(float(v), 4) for v in rng.uniform(0.3, 1.6, size=3)]
    elif kind == "cylinder" or kind == "cone":
        obj["radius"] = round(float(rng.uniform(0.2, 0.8)), 4)
        obj["height"] = round(float(rng.uniform(0.3, 2.0)), 4)
    elif kind == "sphere":
        obj["radius"] = round(float(rng.uniform(0.2, 0.9)), 4)
    elif kind == "prism":
        n = int(rng.integers(3, 9))
        concave = n >= 5 and rng.uniform() < 0.7
        obj["polygon"] = star_polygon(rng, n, 0.35, 1.0, concave)
        obj["height"] = round(float(rng.uniform(0.3, 2.0)), 4)
    rz = float(rng.uniform(0.0, 360.0))
    if allow_tilt and rng.uniform() < 0.5 and kind != "sphere":
        rx, ry = (float(v) for v in rng.uniform(-35.0, 35.0, size=2))
    else:
        rx, ry = 0.0, 0.0
    xy = rng.uniform(-4.0, 4.0, size=2)
    obj["transform"] = {"position": [round(float(xy[0]), 4), round(float(xy[1]), 4), 0.0],
                        "rotation_deg": [round(rx, 4), round(ry, 4), round(rz, 4)]}
    # lift so that the lowest point is on the ground (or slightly above it)
    min_z = float(np.min(world_extreme_points(obj)[:, 2]))
    lift = 0.0 if rng.uniform() < 0.7 else float(rng.uniform(0.0, 0.3))
    obj["transform"]["position"][2] = round(-min_z + lift, 6)
    return obj


def random_light(rng: np.random.Generator, objects: list[dict], light_type: str | None = None,
                 light_above_objects: bool = True) -> dict:
    """A random point light (above every object by default) or directional light above the
    horizon (elevation 15–80 degrees)."""
    light_type = light_type or ("point" if rng.uniform() < 0.6 else "directional")
    if light_type == "point":
        top = max(float(np.max(world_extreme_points(o)[:, 2])) for o in objects)
        z_lo = top + 0.5 if light_above_objects else 0.8
        pos = [round(float(rng.uniform(-7.0, 7.0)), 4), round(float(rng.uniform(-7.0, 7.0)), 4),
               round(float(rng.uniform(z_lo, z_lo + 6.0)), 4)]
        return {"id": "light", "type": "point", "position": pos}
    az = float(rng.uniform(0.0, 2.0 * math.pi))
    el = math.radians(float(rng.uniform(15.0, 80.0)))
    d = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
    d = d / np.linalg.norm(d)
    return {"id": "light", "type": "directional", "direction": [float(v) for v in d]}


def random_camera(rng: np.random.Generator, objects: list[dict]) -> dict:
    """Camera at distance 6–14 from the scene centre, elevation 5–45 degrees, looking at
    the (jittered) centre; focal length 24–70 mm on a 36x24 frame."""
    pts = np.vstack([world_extreme_points(o) for o in objects])
    centre = 0.5 * (pts.min(axis=0) + pts.max(axis=0))
    az = float(rng.uniform(0.0, 2.0 * math.pi))
    el = math.radians(float(rng.uniform(5.0, 45.0)))
    dist = float(rng.uniform(6.0, 14.0))
    pos = centre + dist * np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
    pos[2] = max(pos[2], 0.3)
    target = centre + rng.uniform(-0.5, 0.5, size=3)
    return {
        "position": [round(float(v), 4) for v in pos],
        "target": [round(float(v), 4) for v in target],
        "roll_deg": 0.0,
        "focal_length_mm": round(float(rng.uniform(24.0, 70.0)), 2),
        "frame_mm": list(FRAME_MM),
        "shift_mm": [0.0, 0.0],
        "near_m": 0.05,
    }


def assemble_scene(objects: list[dict], light: dict, camera: dict) -> dict:
    return {
        "version": "0.1",
        "units": "m",
        "up": "z",
        "objects": objects,
        "lights": [light],
        "receivers": [{"id": "ground", "type": "plane", "normal": [0, 0, 1], "offset": 0.0}],
        "camera": camera,
        "output": {"canvas_mm": list(CANVAS_MM), "layers": list(LAYERS), "png_dpi": 300},
    }


# --------------------------------------------------------------------------- public
def make_scene(seed: int, n_objects: int | None = None, light_type: str | None = None,
               light_above_objects: bool = True, allow_tilt: bool = True) -> dict:
    """Valid spec §4 scene with ``n_objects`` (1–10, random when None) primitives, one
    random light and a random camera; deterministic for a given ``seed``."""
    rng = np.random.default_rng(seed)
    if n_objects is None:
        n_objects = int(rng.integers(1, 11))
    n_objects = max(1, min(10, int(n_objects)))
    kinds = list(TYPES)
    objects = []
    for i in range(n_objects):
        kind = kinds[i] if i < len(kinds) and n_objects >= len(kinds) else None
        objects.append(random_object(rng, i, kind, allow_tilt))
    light = random_light(rng, objects, light_type, light_above_objects)
    camera = random_camera(rng, objects)
    return assemble_scene(objects, light, camera)


def u_polygon(outer: float = 4.0, notch_width: float = 1.0, notch_depth: float = 3.0) -> list[list[float]]:
    """Counter-clockwise U-shaped polygon: ``outer x outer`` square centred at the origin
    with a notch of width ``notch_width`` open to ``+y`` reaching down to
    ``y = outer/2 - notch_depth``."""
    o = outer / 2.0
    w = notch_width / 2.0
    yb = o - notch_depth
    return [[-o, -o], [o, -o], [o, o], [w, o], [w, yb], [-w, yb], [-w, o], [-o, o]]


def make_concavity_scene(seed: int = 0, point_light: bool = True) -> dict:
    """Scene whose point light foot lies inside the concavity (the notch) of a U-shaped
    prism, with the light above the prism so that the shadow stays bounded; a second
    small box sits elsewhere.  The spec §7.3 "light foot inside a concavity" case."""
    rng = np.random.default_rng(seed)
    height = 1.0
    prism = {"id": "u", "type": "prism", "polygon": u_polygon(), "height": height,
             "transform": {"position": [0.0, 0.0, 0.0],
                           "rotation_deg": [0.0, 0.0, round(float(rng.uniform(-20.0, 20.0)), 4)]}}
    box = random_object(rng, 1, "box", allow_tilt=False)
    box["transform"]["position"][0] = 4.5
    box["transform"]["position"][1] = round(float(rng.uniform(-3.0, 3.0)), 4)
    objects = [prism, box]
    if point_light:
        # foot (fx, fy) inside the notch of the *unrotated* prism, then rotate with it
        rz = math.radians(prism["transform"]["rotation_deg"][2])
        fx, fy = float(rng.uniform(-0.3, 0.3)), float(rng.uniform(-0.5, 1.5))
        wx = math.cos(rz) * fx - math.sin(rz) * fy
        wy = math.sin(rz) * fx + math.cos(rz) * fy
        light = {"id": "light", "type": "point",
                 "position": [round(wx, 4), round(wy, 4), round(float(rng.uniform(2.5, 5.0)), 4)]}
    else:
        light = random_light(rng, objects, "directional")
    camera = random_camera(rng, objects)
    return assemble_scene(objects, light, camera)


def sample_grid(scene: dict, light: dict, n: int = 256, margin: float = 1.0):
    """``(xs, ys)`` covering the objects and their ground shadows (bounding box of the
    extreme points and of their analytic ground projections, grown by ``margin``), for
    the raycast/raster comparison.  Points not below a point light are ignored."""
    pts = np.vstack([world_extreme_points(o) for o in scene["objects"]])
    ground = [pts[:, :2]]
    if light["type"] == "point":
        l = np.asarray(light["position"], dtype=np.float64)
        below = pts[:, 2] < l[2] - 1e-6
        p = pts[below]
        s = (l[2] * p[:, :2] - p[:, 2:3] * l[None, :2]) / (l[2] - p[:, 2:3])
        ground.append(s)
    else:
        l = np.asarray(light["direction"], dtype=np.float64)
        if l[2] > 1e-6:
            s = pts[:, :2] - pts[:, 2:3] * l[None, :2] / l[2]
            ground.append(s)
    g = np.vstack(ground)
    lo = g.min(axis=0) - margin
    hi = g.max(axis=0) + margin
    xs = np.linspace(lo[0], hi[0], n)
    ys = np.linspace(lo[1], hi[1], n)
    return xs, ys
