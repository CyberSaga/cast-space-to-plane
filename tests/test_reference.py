"""Self-consistency tests of the independent reference (spec §7.3, contract §1):
ray caster, rasterizer and random scene generator."""

from __future__ import annotations

import math

import numpy as np
import pytest

from tests.reference import random_scenes, raster, raycast


def grid(lo, hi, n):
    xs = np.linspace(lo[0], hi[0], n)
    ys = np.linspace(lo[1], hi[1], n)
    return xs, ys


def cell_area(xs, ys):
    return float((xs[1] - xs[0]) * (ys[1] - ys[0]))


# --------------------------------------------------------------------------- placement
def test_rotation_matrix_is_zyx_right_handed():
    R = raycast.rotation_matrix([0, 0, 90])
    assert np.allclose(R @ [1, 0, 0], [0, 1, 0])
    R = raycast.rotation_matrix([90, 0, 0])
    assert np.allclose(R @ [0, 1, 0], [0, 0, 1])
    R = raycast.rotation_matrix([0, 90, 0])
    assert np.allclose(R @ [0, 0, 1], [1, 0, 0])
    Rz, Ry, Rx = (raycast.rotation_matrix(v) for v in ([0, 0, 30], [0, 40, 0], [50, 0, 0]))
    assert np.allclose(raycast.rotation_matrix([50, 40, 30]), Rz @ Ry @ Rx)
    assert np.allclose(np.linalg.det(raycast.rotation_matrix([12, -34, 56])), 1.0)


# --------------------------------------------------------------------------- raster
def test_raster_square_has_right_area_and_nonzero_rule():
    xs, ys = grid((-2, -2), (2, 2), 401)
    square = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], dtype=float)
    mask = raster.rasterize_polygons([square], xs, ys)
    assert mask.sum() * cell_area(xs, ys) == pytest.approx(4.0, rel=0.02)
    # clockwise loop fills the same region under nonzero
    assert np.array_equal(raster.rasterize_polygons([square[::-1]], xs, ys), mask)
    # two overlapping loops of the same orientation: union (winding 2 is still nonzero)
    shifted = square + 0.5
    both = raster.rasterize_polygons([square, shifted], xs, ys)
    assert both.sum() * cell_area(xs, ys) == pytest.approx(4 + 4 - 2.25, rel=0.02)
    wn = raster.winding_numbers([square, shifted], xs, ys)
    assert wn.max() == 2 and wn.min() == 0
    # a hole with opposite orientation is subtracted
    hole = (square * 0.5)[::-1]
    with_hole = raster.rasterize_polygons([square, hole], xs, ys)
    assert with_hole.sum() * cell_area(xs, ys) == pytest.approx(3.0, rel=0.02)
    assert raster.iou(mask, mask) == 1.0
    assert raster.iou(mask, ~mask) == 0.0
    assert raster.iou(np.zeros((2, 2), bool), np.zeros((2, 2), bool)) == 1.0


# --------------------------------------------------------------------------- ray caster
def test_box_shadow_under_vertical_sun_is_base_rectangle():
    scene = {"objects": [{"id": "b", "type": "box", "size": [1.0, 0.6, 0.8],
                          "transform": {"position": [0.3, -0.2, 0.0], "rotation_deg": [0, 0, 30]}}]}
    light = {"type": "directional", "direction": [0.0, 0.0, 1.0]}
    xs, ys = grid((-2, -2), (2, 2), 401)
    mask = raycast.shadow_mask(scene, light, xs, ys)
    R = raycast.rotation_matrix([0, 0, 30])[:2, :2]
    corners = np.array([[-0.5, -0.3], [0.5, -0.3], [0.5, 0.3], [-0.5, 0.3]]) @ R.T + [0.3, -0.2]
    expected = raster.rasterize_polygons([corners], xs, ys)
    assert raster.iou(mask, expected) >= 0.99
    assert mask.sum() * cell_area(xs, ys) == pytest.approx(0.6, rel=0.02)


def test_sphere_mask_area_matches_analytic_ellipse():
    r = 0.7
    for phi_deg in (30.0, 60.0):
        phi = math.radians(phi_deg)
        scene = {"objects": [{"id": "s", "type": "sphere", "radius": r,
                              "transform": {"position": [0, 0, 0], "rotation_deg": [0, 0, 0]}}]}
        light = {"type": "directional", "direction": [math.cos(phi), 0.0, math.sin(phi)]}
        xs, ys = grid((-5, -2), (2, 2), 701)
        mask = raycast.shadow_mask(scene, light, xs, ys)
        area = mask.sum() * cell_area(xs, ys)
        assert area == pytest.approx(math.pi * r * r / math.sin(phi), rel=0.01)
        # centre offset r / tan(phi) opposite to the light (-x)
        X, Y = np.meshgrid(xs, ys)
        assert X[mask].mean() == pytest.approx(-r / math.tan(phi), abs=0.02)
        assert abs(Y[mask].mean()) < 0.02


def test_point_light_sphere_shadow_scales_with_height():
    r = 0.5
    scene = {"objects": [{"id": "s", "type": "sphere", "radius": r,
                          "transform": {"position": [0, 0, 0], "rotation_deg": [0, 0, 0]}}]}
    light = {"type": "point", "position": [0.0, 0.0, 4.0]}
    xs, ys = grid((-2, -2), (2, 2), 601)
    mask = raycast.shadow_mask(scene, light, xs, ys)
    # tangent cone from the light: ground radius = h * r / sqrt(d^2 - r^2), d = h - r
    h, d = 4.0, 3.5
    rad = h * r / math.sqrt(d * d - r * r)
    assert mask.sum() * cell_area(xs, ys) == pytest.approx(math.pi * rad * rad, rel=0.01)


def test_known_lit_and_shadowed_points():
    scene = {"objects": [
        {"id": "b", "type": "box", "size": [1, 1, 1], "transform": {"position": [0, 0, 0], "rotation_deg": [0, 0, 0]}},
        {"id": "c", "type": "cylinder", "radius": 0.5, "height": 2.0,
         "transform": {"position": [3, 0, 0], "rotation_deg": [0, 0, 0]}},
        {"id": "k", "type": "cone", "radius": 0.5, "height": 1.0,
         "transform": {"position": [0, 3, 0], "rotation_deg": [0, 0, 0]}},
        {"id": "p", "type": "prism", "polygon": [[-0.5, -0.5], [0.5, -0.5], [0.0, 0.5]], "height": 1.0,
         "transform": {"position": [-3, 0, 0], "rotation_deg": [0, 0, 0]}},
        {"id": "s", "type": "sphere", "radius": 0.5, "transform": {"position": [0, -3, 0], "rotation_deg": [0, 0, 0]}},
    ]}
    light = {"type": "point", "position": [0.0, 0.0, 10.0]}
    pts = np.array([
        [0.0, 0.0, 0.0],    # under the box -> shadow
        [3.0, 0.0, 0.0],    # under the cylinder
        [0.0, 3.0, 0.0],    # under the cone
        [-3.0, 0.0, 0.0],   # inside the prism footprint
        [0.0, -3.0, 0.0],   # under the sphere
        [6.0, 6.0, 0.0],    # far away: lit
        [1.5, 1.5, 0.0],    # between objects: lit
        [3.0, 0.0 + 0.5 * 10 / 8 + 0.05, 0.0],  # just outside the cylinder top rim shadow: lit
    ])
    occ = raycast.occluded(scene, light, pts)
    assert occ.tolist() == [True, True, True, True, True, False, False, False]
    # directional light straight down: footprints only
    occ2 = raycast.occluded(scene, {"type": "directional", "direction": [0, 0, 1]}, pts)
    assert occ2.tolist() == [True, True, True, True, True, False, False, False]
    # light below the ground never shadows anything on the ground (rays go down)
    occ3 = raycast.occluded(scene, {"type": "point", "position": [0, 0, -5]}, pts[5:])
    assert not occ3.any()


def test_cylinder_mask_under_45deg_sun_has_closed_form_area():
    r, h = 0.4, 1.5
    scene = {"objects": [{"id": "c", "type": "cylinder", "radius": r, "height": h,
                          "transform": {"position": [0, 0, 0], "rotation_deg": [0, 0, 0]}}]}
    phi = math.radians(45.0)
    light = {"type": "directional", "direction": [-math.cos(phi), 0.0, math.sin(phi)]}
    xs, ys = grid((-1, -1), (3, 1), 801)
    mask = raycast.shadow_mask(scene, light, xs, ys)
    # footprint disc + swept rectangle (2 r * h / tan phi) + top disc = pi r^2 + 2 r h
    assert mask.sum() * cell_area(xs, ys) == pytest.approx(math.pi * r * r + 2 * r * h, rel=0.01)
    assert xs[np.nonzero(mask.any(axis=0))[0].max()] == pytest.approx(h + r, abs=0.01)


def test_tilted_prism_and_box_agree_for_same_shape():
    """A box and the equivalent 4-gon prism must give identical masks under any rotation."""
    tr = {"position": [0.2, -0.4, 0.6], "rotation_deg": [25, -15, 40]}
    box = {"objects": [{"id": "b", "type": "box", "size": [1.2, 0.8, 0.9], "transform": tr}]}
    prism = {"objects": [{"id": "p", "type": "prism", "height": 0.9, "transform": tr,
                          "polygon": [[-0.6, -0.4], [0.6, -0.4], [0.6, 0.4], [-0.6, 0.4]]}]}
    light = {"type": "point", "position": [2.0, 1.0, 5.0]}
    xs, ys = grid((-3, -3), (3, 3), 301)
    a = raycast.shadow_mask(box, light, xs, ys)
    b = raycast.shadow_mask(prism, light, xs, ys)
    assert raster.iou(a, b) >= 0.999
    assert a.any()


def test_concave_prism_cap_point_in_polygon():
    poly = random_scenes.u_polygon()
    scene = {"objects": [{"id": "u", "type": "prism", "polygon": poly, "height": 1.0,
                          "transform": {"position": [0, 0, 0], "rotation_deg": [0, 0, 0]}}]}
    light = {"type": "directional", "direction": [0, 0, 1]}
    pts = np.array([[0.0, 0.0, 0.0], [0.0, 1.5, 0.0], [1.5, 0.0, 0.0], [-1.5, -1.5, 0.0], [0.0, -1.5, 0.0]])
    occ = raycast.occluded(scene, light, pts)
    assert occ.tolist() == [False, False, True, True, True]


# --------------------------------------------------------------------------- random scenes
REQUIRED_TOP = {"version", "units", "up", "objects", "lights", "receivers", "camera", "output"}


def check_scene_valid(scene):
    assert REQUIRED_TOP <= set(scene)
    assert scene["version"] == "0.1" and scene["units"] == "m" and scene["up"] == "z"
    assert 1 <= len(scene["objects"]) <= 10
    ids = [o["id"] for o in scene["objects"]]
    assert len(set(ids)) == len(ids) and all(i and "." not in i for i in ids)
    for o in scene["objects"]:
        assert o["type"] in random_scenes.TYPES
        if o["type"] == "box":
            assert len(o["size"]) == 3 and all(v > 0 for v in o["size"])
        if o["type"] in ("cylinder", "cone"):
            assert o["radius"] > 0 and o["height"] > 0
        if o["type"] == "sphere":
            assert o["radius"] > 0
        if o["type"] == "prism":
            assert len(o["polygon"]) >= 3 and o["height"] > 0
            assert random_scenes.polygon_area(o["polygon"]) > 0
        assert len(o["transform"]["position"]) == 3 and len(o["transform"]["rotation_deg"]) == 3
        assert np.min(random_scenes.world_extreme_points(o)[:, 2]) >= -1e-6
    assert len(scene["lights"]) == 1
    light = scene["lights"][0]
    if light["type"] == "point":
        assert light["position"][2] > 0
    else:
        d = np.asarray(light["direction"])
        assert abs(np.linalg.norm(d) - 1) <= 1e-9 and d[2] > 0
    rec = scene["receivers"][0]
    assert rec["type"] == "plane" and rec["normal"] == [0, 0, 1] and rec["offset"] == 0.0
    cam = scene["camera"]
    assert "target" in cam and "yaw_deg" not in cam
    assert cam["focal_length_mm"] > 0 and cam["near_m"] > 0
    cw, ch = scene["output"]["canvas_mm"]
    fw, fh = cam["frame_mm"]
    assert abs(cw / ch - fw / fh) <= 1e-9
    assert scene["output"]["layers"] == random_scenes.LAYERS


@pytest.mark.parametrize("seed", range(12))
def test_make_scene_is_valid_and_deterministic(seed):
    scene = random_scenes.make_scene(seed)
    check_scene_valid(scene)
    assert random_scenes.make_scene(seed) == scene
    if len(scene["objects"]) >= 5:
        assert {o["type"] for o in scene["objects"]} == set(random_scenes.TYPES)


def test_make_scene_options():
    s = random_scenes.make_scene(3, n_objects=10, light_type="directional")
    check_scene_valid(s)
    assert len(s["objects"]) == 10 and s["lights"][0]["type"] == "directional"
    s = random_scenes.make_scene(4, n_objects=1, light_type="point", allow_tilt=False)
    assert len(s["objects"]) == 1 and s["objects"][0]["transform"]["rotation_deg"][:2] == [0.0, 0.0]
    concave = [o for seed in range(30) for o in random_scenes.make_scene(seed)["objects"]
               if o["type"] == "prism" and len(o["polygon"]) >= 5]
    assert concave, "expected some concave prisms"


def test_concavity_scene_light_foot_inside_notch():
    scene = random_scenes.make_concavity_scene(0)
    check_scene_valid(scene)
    light = scene["lights"][0]
    prism = scene["objects"][0]
    foot = np.array([light["position"][0], light["position"][1], 0.0])
    occ = raycast.occluded({"objects": [prism]}, {"type": "directional", "direction": [0, 0, 1]}, foot[None, :])
    assert not occ[0]  # the foot is in the notch, not on the prism
    # but the foot is surrounded by the prism on three sides
    R = raycast.rotation_matrix(prism["transform"]["rotation_deg"])
    for local in ([1.0, 0.0, 0.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]):
        probe = foot + R @ np.array(local) * 1.0
        probe[2] = 0.0
        assert raycast.occluded({"objects": [prism]}, {"type": "directional", "direction": [0, 0, 1]},
                                probe[None, :])[0]


def test_sample_grid_covers_shadows():
    scene = random_scenes.make_scene(7, n_objects=4, light_type="point")
    light = scene["lights"][0]
    xs, ys = random_scenes.sample_grid(scene, light, n=128)
    mask = raycast.shadow_mask(scene, light, xs, ys)
    assert mask.any()
    assert not mask[0].any() and not mask[-1].any() and not mask[:, 0].any() and not mask[:, -1].any()
