"""Seeded random scene generator producing valid spec §4 scene dicts (spec §7.3, §7.4, §8; contract §4).

Scenes contain 1–10 primitives of all five types (prisms with concave simple polygons),
random rotations (objects are lifted so that nothing is below the ground), one random
point or directional light above the ground and a random camera looking at the scene.
Shares no code with ``castplane``; the only geometry re-implemented here is the Z-Y-X
placement of :mod:`tests.reference.raycast` (used to lift tilted objects).

Besides :func:`make_scene` (the general §7.3 distribution) this module builds the
dedicated families the verification harness needs:

* :func:`make_concavity_scene` / :func:`make_concave_star_scene` -- a concave prism with
  the light foot inside the concavity;
* :func:`make_unbounded_scene` -- a point light lower than some object tops
  (spec §5.7 row 4: unbounded shadows);
* :func:`make_light_behind_camera_scene` -- the light behind the camera (§5.7 row 1);
* :func:`make_light_parallel_to_picture_plane_scene` -- a directional light (nearly)
  parallel to the picture plane (§5.7 row 2);
* :func:`make_near_camera_scene` -- the camera close to an object (near clipping,
  §5.7 row 5);
* :func:`make_benchmark_scene` -- the §8 benchmark scene (100 primitives, ≈10k edges).

The RNG draw order of :func:`random_object`, :func:`random_light` and
:func:`random_camera` is frozen: other test modules rely on the scenes a given seed
produces.
"""

from __future__ import annotations

import math

import numpy as np

from tests.reference.raycast import rotation_matrix

TYPES = ("box", "cylinder", "sphere", "cone", "prism")
LAYERS = ["horizon", "objects", "form_shadow", "cast_shadow", "construction", "labels"]
FRAME_MM = [36.0, 24.0]
CANVAS_MM = [360.0, 240.0]
#: Positive margin (m) by which every object is lifted above the ground: rounding the lift to
#: 6 decimals alone may leave a tilted object ~5e-7 m below the receiver.
LIFT_MARGIN = 1e-6


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


def regular_polygon(n: int, radius: float, phase: float = 0.0) -> list[list[float]]:
    """Counter-clockwise regular ``n``-gon of circumradius ``radius``."""
    return [[round(radius * math.cos(phase + 2.0 * math.pi * k / n), 6),
             round(radius * math.sin(phase + 2.0 * math.pi * k / n), 6)] for k in range(n)]


def convex_hull(points) -> np.ndarray:
    """Counter-clockwise convex hull (Andrew's monotone chain) of 2-D points."""
    pts = sorted({(float(x), float(y)) for x, y in np.asarray(points, dtype=np.float64).reshape(-1, 2)})

    def half(seq):
        out = []
        for q in seq:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (q[1] - out[-2][1])
                                     - (out[-1][1] - out[-2][1]) * (q[0] - out[-2][0])) <= 0:
                out.pop()
            out.append(q)
        return out

    lower, upper = half(pts), half(pts[::-1])
    return np.asarray(lower[:-1] + upper[:-1], dtype=np.float64)


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


def lowest_z(obj: dict) -> float:
    """Exact lowest world ``z`` of the primitive (analytic rims for the curved types: the lowest
    point of a circle of radius ``r`` with unit normal ``a`` is ``c_z - r sqrt(1 - a_z^2)``)."""
    kind = obj["type"]
    R = rotation_matrix(obj["transform"]["rotation_deg"])
    pos = np.asarray(obj["transform"]["position"], dtype=np.float64)
    if kind in ("box", "prism"):
        return float(np.min(world_extreme_points(obj)[:, 2]))
    a = R @ np.array([0.0, 0.0, 1.0])
    r = float(obj["radius"])
    drop = r * math.sqrt(max(0.0, 1.0 - a[2] * a[2]))
    if kind == "sphere":
        return float(pos[2] + r * a[2] - r)
    base = float(pos[2]) - drop
    top = pos + float(obj["height"]) * a
    if kind == "cylinder":
        return min(base, float(top[2]) - drop)
    if kind == "cone":
        return min(base, float(top[2]))
    raise ValueError(kind)


def highest_z(obj: dict) -> float:
    """Exact highest world ``z`` of the primitive (mirror of :func:`lowest_z`)."""
    kind = obj["type"]
    if kind in ("box", "prism"):
        return float(np.max(world_extreme_points(obj)[:, 2]))
    R = rotation_matrix(obj["transform"]["rotation_deg"])
    pos = np.asarray(obj["transform"]["position"], dtype=np.float64)
    a = R @ np.array([0.0, 0.0, 1.0])
    r = float(obj["radius"])
    rise = r * math.sqrt(max(0.0, 1.0 - a[2] * a[2]))
    if kind == "sphere":
        return float(pos[2] + r * a[2] + r)
    base = float(pos[2]) + rise
    top = pos + float(obj["height"]) * a
    if kind == "cylinder":
        return max(base, float(top[2]) + rise)
    return max(base, float(top[2]))


def bounding_sphere(obj: dict) -> tuple[np.ndarray, float]:
    """``(centre, radius)`` of a sphere containing the object (from its extreme points)."""
    pts = world_extreme_points(obj)
    c = 0.5 * (pts.min(axis=0) + pts.max(axis=0))
    r = float(np.max(np.linalg.norm(pts - c, axis=1)))
    if obj["type"] in ("cylinder", "cone", "sphere"):
        r += 0.02 * float(obj["radius"])   # sampled rims underestimate the true rim slightly
    return c, r


def clear_of_objects(p, objects: list[dict], margin: float) -> bool:
    """True when ``p`` is farther than ``margin`` from every object's bounding sphere."""
    p = np.asarray(p, dtype=np.float64)
    for o in objects:
        c, r = bounding_sphere(o)
        if float(np.linalg.norm(p - c)) <= r + margin:
            return False
    return True


def push_clear(p, objects: list[dict], margin: float, max_rounds: int = 50) -> np.ndarray:
    """Deterministically move ``p`` horizontally (``z`` kept) until it is farther than ``margin``
    from every object's bounding sphere: in each round, every violated sphere pushes the
    point radially away from its centre (in XY) to the required horizontal distance.  If the
    spheres still overlap after ``max_rounds`` the point is placed on the ray from the scene
    centre through ``p`` beyond every sphere (always clear).  Used by the hypothesis
    strategies instead of ``assume(clear_of_objects(...))``."""
    p = np.array(p, dtype=np.float64).reshape(3)
    spheres = [bounding_sphere(o) for o in objects]
    for _round in range(max_rounds):
        moved = False
        for c, r in spheres:
            need = r + margin
            if float(np.linalg.norm(p - c)) > need:
                continue
            dz = p[2] - c[2]
            horiz = math.sqrt(max(need * need - dz * dz, 0.0)) + 1e-3
            u = p[:2] - c[:2]
            n = float(np.linalg.norm(u))
            u = u / n if n > 1e-12 else np.array([1.0, 0.0])
            p[:2] = c[:2] + horiz * u
            moved = True
        if not moved:
            return p
    centre = np.mean([c for c, _r in spheres], axis=0)
    reach = max(float(np.linalg.norm(c - centre)) + r for c, r in spheres) + margin + 1e-3
    u = p[:2] - centre[:2]
    n = float(np.linalg.norm(u))
    u = u / n if n > 1e-12 else np.array([1.0, 0.0])
    p[:2] = centre[:2] + reach * u
    return p


def lift_to_ground(obj: dict, lift: float = 0.0) -> None:
    """Set ``position[2]`` so that the exact lowest point sits ``lift + LIFT_MARGIN`` above the
    ground (rounded *up* to 6 decimals: never below)."""
    obj["transform"]["position"][2] = 0.0
    z = -lowest_z(obj) + lift + LIFT_MARGIN
    obj["transform"]["position"][2] = math.ceil(z * 1e6) / 1e6


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
    # lift so that the lowest point is on the ground (or slightly above it), never below it
    lift = 0.0 if rng.uniform() < 0.7 else float(rng.uniform(0.0, 0.3))
    lift_to_ground(obj, lift)
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
    return {"id": "light", "type": "directional", "direction": unit_direction(az, el)}


def unit_direction(azimuth: float, elevation: float) -> list[float]:
    """Unit vector of the given azimuth / elevation (radians), normalised to 1e-9."""
    d = np.array([math.cos(elevation) * math.cos(azimuth), math.cos(elevation) * math.sin(azimuth),
                  math.sin(elevation)])
    d = d / np.linalg.norm(d)
    return [float(v) for v in d]


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


def camera_frame(camera: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(forward, right, up)`` of a target-form camera with zero roll (spec §5.4 conventions:
    ``right = forward x z``, ``up = right x forward``); the fallback up is ``+y`` when the camera
    looks along ``z``."""
    pos = np.asarray(camera["position"], dtype=np.float64)
    fwd = np.asarray(camera["target"], dtype=np.float64) - pos
    fwd = fwd / np.linalg.norm(fwd)
    up_world = np.array([0.0, 0.0, 1.0])
    if np.linalg.norm(np.cross(fwd, up_world)) <= 1e-9:
        up_world = np.array([0.0, 1.0, 0.0])
    right = np.cross(fwd, up_world)
    right = right / np.linalg.norm(right)
    up = np.cross(right, fwd)
    return fwd, right, up


def assemble_scene(objects: list[dict], lights, camera: dict) -> dict:
    """The spec §4 scene dict; ``lights`` is one light dict or (M6, contract §5.3.9) a list of them."""
    return {
        "version": "0.1",
        "units": "m",
        "up": "z",
        "objects": objects,
        "lights": [lights] if isinstance(lights, dict) else list(lights),
        "receivers": [{"id": "ground", "type": "plane", "normal": [0, 0, 1], "offset": 0.0}],
        "camera": camera,
        "output": {"canvas_mm": list(CANVAS_MM), "layers": list(LAYERS), "png_dpi": 300},
    }


# --------------------------------------------------------------------------- public
def make_scene(seed: int, n_objects: int | None = None, light_type: str | None = None,
               light_above_objects: bool = True, allow_tilt: bool = True,
               kinds: tuple[str, ...] | None = None, n_lights: int = 1) -> dict:
    """Valid spec §4 scene with ``n_objects`` (1–10, random when None) primitives, one
    random light and a random camera; deterministic for a given ``seed``.

    ``kinds`` restricts the primitive types (e.g. ``("box", "prism")`` for polyhedral
    scenes); by default all five types appear once in scenes of 5+ objects.

    M6 (contract §5.3.9): ``n_lights >= 2`` appends ``n_lights - 1`` further random lights
    (ids ``light1``, ``light2`` …, same ``light_type`` rule) drawn from the generator **after**
    the camera, so that ``n_lights = 1`` is byte-identical to the frozen single-light scenes.
    """
    rng = np.random.default_rng(seed)
    if n_objects is None:
        n_objects = int(rng.integers(1, 11))
    n_objects = max(1, min(10, int(n_objects)))
    pool = list(TYPES if kinds is None else kinds)
    objects = []
    for i in range(n_objects):
        if kinds is None:
            kind = pool[i] if i < len(pool) and n_objects >= len(pool) else None
        else:
            kind = pool[i % len(pool)]
        objects.append(random_object(rng, i, kind, allow_tilt))
    light = random_light(rng, objects, light_type, light_above_objects)
    camera = random_camera(rng, objects)
    lights = [light]
    for k in range(1, max(1, int(n_lights))):
        lights.append(dict(random_light(rng, objects, light_type, light_above_objects), id=f"light{k}"))
    return assemble_scene(objects, light if len(lights) == 1 else lights, camera)


def make_polyhedral_scene(seed: int, n_objects: int | None = None, light_type: str | None = None,
                          allow_tilt: bool = True) -> dict:
    """:func:`make_scene` restricted to boxes and prisms (alternating)."""
    return make_scene(seed, n_objects, light_type, True, allow_tilt, kinds=("prism", "box"))


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


def make_concave_star_scene(seed: int = 0, n_extra: int = 1, light_above: bool = True) -> dict:
    """Concave star-shaped prism (5–8 vertices, alternating radii) whose point light foot sits
    in one of its notches (outside the polygon, inside its convex hull), plus ``n_extra``
    random polyhedra.  With ``light_above`` the light is above every object (bounded
    shadows); otherwise it sits between the prism's top and twice its height (the
    notch walls then cast an unbounded shadow)."""
    rng = np.random.default_rng(seed)
    n = int(rng.integers(5, 9)) // 2 * 2    # even: radii alternate cleanly
    r_min, r_max = 0.6, 1.6
    poly = star_polygon(rng, n, r_min, r_max, concave=True)
    height = round(float(rng.uniform(0.6, 1.8)), 4)
    rz = round(float(rng.uniform(0.0, 360.0)), 4)
    prism = {"id": "star", "type": "prism", "polygon": poly, "height": height,
             "transform": {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, rz]}}
    objects = [prism]
    for i in range(n_extra):
        o = random_object(rng, i + 1, "box" if i % 2 else "prism", allow_tilt=False)
        o["transform"]["position"][0] = round(float(rng.uniform(3.5, 5.0)) * (1 if i % 2 else -1), 4)
        objects.append(o)
    # the inner vertices of the star are the odd ones: the notch is the sector around such a vertex
    # between radius r_min and the convex hull
    P = np.asarray(poly, dtype=np.float64)
    radii = np.linalg.norm(P, axis=1)
    inner = [k for k in range(n) if radii[k] < 0.5 * (r_min + r_max)]
    k = inner[int(rng.integers(len(inner)))]
    # the notch is the triangle (P_{k-1}, P_k, P_{k+1}) minus the polygon: place the foot on the
    # ray from the origin through the reflex vertex P_k, between P_k and the chord P_{k-1} P_{k+1}
    u = P[k] / radii[k]
    A, B = P[(k - 1) % n], P[(k + 1) % n]
    e = B - A
    t_chord = (A[0] * e[1] - A[1] * e[0]) / (u[0] * e[1] - u[1] * e[0])
    rho = radii[k] + float(rng.uniform(0.35, 0.6)) * (t_chord - radii[k])
    local = rho * u
    R = rotation_matrix([0.0, 0.0, rz])[:2, :2]
    foot = R @ local
    top = max(highest_z(o) for o in objects)
    if light_above:
        z = round(float(rng.uniform(top + 0.5, top + 4.0)), 4)
    else:
        z = round(float(rng.uniform(height * 0.5, height * 0.9)), 4)
    light = {"id": "light", "type": "point", "position": [round(float(foot[0]), 4), round(float(foot[1]), 4), z]}
    camera = random_camera(rng, objects)
    return assemble_scene(objects, light, camera)


def make_unbounded_scene(seed: int, n_objects: int | None = None, kinds: tuple[str, ...] | None = None) -> dict:
    """Point light lower than some object tops (but outside every object and above the
    ground): spec §5.7 row 4, the shadow outline of the taller objects is unbounded."""
    rng = np.random.default_rng(seed)
    if n_objects is None:
        n_objects = int(rng.integers(1, 6))
    pool = list(TYPES if kinds is None else kinds)
    objects = [random_object(rng, i, pool[i % len(pool)] if kinds is not None else None) for i in range(n_objects)]
    tops = sorted(highest_z(o) for o in objects)
    z_hi = tops[-1]
    z_lo = 0.25 * z_hi
    for _attempt in range(200):
        pos = np.array([float(rng.uniform(-6.0, 6.0)), float(rng.uniform(-6.0, 6.0)),
                        float(rng.uniform(z_lo, 0.85 * z_hi))])
        if clear_of_objects(pos, objects, 0.3):
            break
    else:  # pragma: no cover - 200 draws on a 12x12 field always find a free spot
        raise RuntimeError("could not place the light outside every object")
    light = {"id": "light", "type": "point", "position": [round(float(v), 4) for v in pos]}
    camera = random_camera(rng, objects)
    return assemble_scene(objects, light, camera)


def make_light_behind_camera_scene(seed: int, kinds: tuple[str, ...] | None = None) -> dict:
    """Point light behind the camera (negative camera depth): spec §5.7 row 1, ``L'`` is the
    anti-light point below the horizon.  The light stays above every object."""
    rng = np.random.default_rng(seed)
    n_objects = int(rng.integers(1, 5))
    pool = list(TYPES if kinds is None else kinds)
    objects = [random_object(rng, i, pool[i % len(pool)] if kinds is not None else None) for i in range(n_objects)]
    camera = random_camera(rng, objects)
    fwd, right, up = camera_frame(camera)
    pos = np.asarray(camera["position"], dtype=np.float64)
    top = max(highest_z(o) for o in objects)
    back = float(rng.uniform(0.5, 4.0))
    side = float(rng.uniform(-3.0, 3.0))
    lpos = pos - back * fwd + side * right
    lpos[2] = max(float(lpos[2]) + float(rng.uniform(0.5, 3.0)), top + 0.5)
    light = {"id": "light", "type": "point", "position": [round(float(v), 4) for v in lpos]}
    return assemble_scene(objects, light, camera)


#: Lower bound of the elevation (``d_z``) of the light of :func:`make_light_parallel_to_picture_plane_scene`.
PARALLEL_LIGHT_MIN_Z = 0.23


def make_light_parallel_to_picture_plane_scene(seed: int, exact: bool = False,
                                                kinds: tuple[str, ...] | None = None) -> dict:
    """Directional light whose direction is (nearly) parallel to the picture plane, i.e.
    perpendicular to the camera forward vector: spec §5.7 row 2, ``L'`` at infinity and
    parallel construction rays.  With ``exact`` the dot product is zero up to rounding;
    otherwise it is within ±0.5 degrees of zero.  The light is above the horizon: with the
    camera elevation of :func:`random_camera` (5–45 degrees, ``up_z >= 0.7``) and
    ``phi in [20, 160]`` degrees the elevation of ``d`` is at least
    ``sin(20°) · 0.7 − sin(0.5°) > 0.23`` (:data:`PARALLEL_LIGHT_MIN_Z`), so no fallback is needed."""
    rng = np.random.default_rng(seed)
    n_objects = int(rng.integers(1, 5))
    pool = list(TYPES if kinds is None else kinds)
    objects = [random_object(rng, i, pool[i % len(pool)] if kinds is not None else None) for i in range(n_objects)]
    camera = random_camera(rng, objects)
    fwd, right, up = camera_frame(camera)
    # d = cos(phi) right + sin(phi) up lies in the picture plane; up_z > 0 so sin(phi) > 0 keeps d above
    # the horizon (right is horizontal for a camera with zero roll)
    phi = math.radians(float(rng.uniform(20.0, 160.0)))
    psi = 0.0 if exact else math.radians(float(rng.uniform(-0.5, 0.5)))
    d = math.cos(psi) * (math.cos(phi) * right + math.sin(phi) * up) + math.sin(psi) * fwd
    d = d / np.linalg.norm(d)
    assert d[2] > PARALLEL_LIGHT_MIN_Z, d
    light = {"id": "light", "type": "directional", "direction": [float(v) for v in d]}
    return assemble_scene(objects, light, camera)


def make_near_camera_scene(seed: int, kinds: tuple[str, ...] | None = None) -> dict:
    """Camera close to (or inside) an object with a short near plane: spec §5.7 row 5,
    object / shadow points behind the camera are near-clipped.  The light is above the
    objects so that only the camera is degenerate."""
    rng = np.random.default_rng(seed)
    n_objects = int(rng.integers(1, 5))
    pool = list(TYPES if kinds is None else kinds)
    objects = [random_object(rng, i, pool[i % len(pool)] if kinds is not None else None) for i in range(n_objects)]
    light = random_light(rng, objects, "point")
    target_obj = objects[int(rng.integers(n_objects))]
    c, r = bounding_sphere(target_obj)
    az = float(rng.uniform(0.0, 2.0 * math.pi))
    el = math.radians(float(rng.uniform(0.0, 40.0)))
    dist = float(rng.uniform(0.2, 1.0)) * max(r, 0.3)
    pos = c + dist * np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
    pos[2] = max(float(pos[2]), 0.15)
    target = c + rng.uniform(-0.3, 0.3, size=3)
    if np.linalg.norm(target - pos) < 1e-3:
        target = target + np.array([0.0, 0.5, 0.0])
    camera = {
        "position": [round(float(v), 4) for v in pos],
        "target": [round(float(v), 4) for v in target],
        "roll_deg": 0.0,
        "focal_length_mm": round(float(rng.uniform(14.0, 35.0)), 2),
        "frame_mm": list(FRAME_MM),
        "shift_mm": [0.0, 0.0],
        "near_m": round(float(rng.uniform(0.02, 0.5)), 4),
    }
    return assemble_scene(objects, light, camera)


#: Number of base vertices of the benchmark prisms: a prism on an ``n``-gon has ``3 n`` edges,
#: so 100 prisms on 33-gons carry 9 900 edges (spec §8: 100 primitives, 10k edges).
BENCHMARK_GON = 33


def make_benchmark_scene(n_objects: int = 100, include_curved: bool = True, seed: int = 20261006) -> dict:
    """Deterministic spec §8 benchmark scene: ``n_objects`` primitives on a 10 x 10 grid, mostly
    prisms on 33-gon bases (99 edges each) so that the scene carries ≈10k edges; with
    ``include_curved`` every tenth object is a cylinder / cone / sphere (their approximate meshes
    have 96 / 64 / 992 edges; ≈10.7k edges in total).  One point light above the scene, one
    receiver, a camera that sees the whole field."""
    rng = np.random.default_rng(seed)
    side = int(math.ceil(math.sqrt(n_objects)))
    pitch = 2.6
    objects = []
    # every tenth object is curved: cylinders (96 mesh edges) and cones (64) alternate, one sphere (992)
    curved_cycle = ("cylinder", "cone", "cylinder", "cone", "sphere", "cone", "cylinder", "cone", "cylinder", "cone")
    for i in range(n_objects):
        gx, gy = i % side, i // side
        x = (gx - (side - 1) / 2.0) * pitch + float(rng.uniform(-0.3, 0.3))
        y = (gy - (side - 1) / 2.0) * pitch + float(rng.uniform(-0.3, 0.3))
        rz = round(float(rng.uniform(0.0, 360.0)), 4)
        if include_curved and i % 10 == 5:
            kind = curved_cycle[(i // 10) % len(curved_cycle)]
            obj = {"id": "p%03d" % i, "type": kind, "radius": round(float(rng.uniform(0.3, 0.8)), 4)}
            if kind != "sphere":
                obj["height"] = round(float(rng.uniform(0.5, 2.0)), 4)
        else:
            concave = i % 2 == 1
            if concave:
                poly = star_polygon(rng, BENCHMARK_GON + 1, 0.5, 1.0, True)   # 34-gon: 102 edges
            else:
                poly = regular_polygon(BENCHMARK_GON, round(float(rng.uniform(0.5, 1.0)), 4))
            obj = {"id": "p%03d" % i, "type": "prism", "polygon": poly,
                   "height": round(float(rng.uniform(0.5, 2.2)), 4)}
        tilt = i % 4 == 3 and obj["type"] != "sphere"
        rx, ry = (round(float(v), 4) for v in (rng.uniform(-20.0, 20.0, size=2) if tilt else (0.0, 0.0)))
        obj["transform"] = {"position": [round(x, 4), round(y, 4), 0.0], "rotation_deg": [rx, ry, rz]}
        lift_to_ground(obj)
        objects.append(obj)
    top = max(highest_z(o) for o in objects)
    light = {"id": "lamp", "type": "point", "position": [3.0, -4.0, round(top + 6.0, 4)]}
    extent = side * pitch
    camera = {
        "position": [0.0, -1.2 * extent, 0.55 * extent],
        "target": [0.0, 0.0, 0.5],
        "roll_deg": 0.0,
        "focal_length_mm": 28.0,
        "frame_mm": list(FRAME_MM),
        "shift_mm": [0.0, 0.0],
        "near_m": 0.05,
    }
    return assemble_scene(objects, light, camera)


def count_edges(scene: dict) -> int:
    """Edge count of the scene's primitives as castplane meshes them (contract §2.4: box 12, prism
    ``3n``, cylinder ``3·32``, cone ``2·32``, UV sphere with 32 segments and 16 rings)."""
    total = 0
    for o in scene["objects"]:
        kind = o["type"]
        if kind == "box":
            total += 12
        elif kind == "prism":
            total += 3 * len(o["polygon"])
        elif kind == "cylinder":
            total += 3 * 32
        elif kind == "cone":
            total += 2 * 32
        elif kind == "sphere":
            total += 32 * 31     # UV sphere (16 rings): 15·32 ring edges + 14·32 band + 2·32 fan edges
    return total


# --------------------------------------------------------------------------- sampling windows
def shadow_window(scene: dict, light: dict, extra_xy=None, margin: float = 1.0):
    """``(lo, hi)`` ground ``(x, y)`` bounds covering the objects, their analytic ground
    shadows (extreme points not below a point light) and ``extra_xy`` points, grown by
    ``margin``."""
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
    if extra_xy is not None:
        extra = np.asarray(extra_xy, dtype=np.float64).reshape(-1, 2)
        if extra.shape[0]:
            ground.append(extra)
    g = np.vstack(ground)
    return g.min(axis=0) - margin, g.max(axis=0) + margin


def grid(lo, hi, n: int):
    """``(xs, ys)`` with ``n`` samples per axis over the window ``[lo, hi]``."""
    lo = np.asarray(lo, dtype=np.float64)
    hi = np.asarray(hi, dtype=np.float64)
    return np.linspace(lo[0], hi[0], n), np.linspace(lo[1], hi[1], n)


def sample_grid(scene: dict, light: dict, n: int = 256, margin: float = 1.0):
    """``(xs, ys)`` covering the objects and their ground shadows (bounding box of the
    extreme points and of their analytic ground projections, grown by ``margin``), for
    the raycast/raster comparison.  Points not below a point light are ignored."""
    lo, hi = shadow_window(scene, light, None, margin)
    return grid(lo, hi, n)
