"""One test per row of spec §5.7 (contract §4): warning codes, finite output and a successful SVG."""

from __future__ import annotations

import copy
import math
import pathlib
import xml.dom.minidom

import numpy as np
import pytest

import castplane
from castplane.errors import warning_codes
from castplane.output.geometry_json import dumps
from castplane.output.svg import write_svg
from castplane.scene import load_scene
from tests.reference import random_scenes, raster, raycast

EXAMPLES = pathlib.Path(__file__).resolve().parents[1] / "examples"


def walk_numbers(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_numbers(v)
    elif isinstance(obj, float):
        yield obj


def scene_with(objects, light, camera):
    return load_scene({
        "version": "0.1",
        "objects": objects,
        "lights": [light],
        "receivers": [{"id": "ground", "type": "plane", "normal": [0, 0, 1], "offset": 0.0}],
        "camera": dict({"roll_deg": 0, "focal_length_mm": 24, "frame_mm": [36, 24], "near_m": 0.05}, **camera),
        "output": {"canvas_mm": [360, 240]},
    })


BOX = {"id": "crate", "type": "box", "size": [1.0, 1.0, 1.0], "transform": {"position": [0.0, 5.0, 0.0]}}
LEVEL_CAMERA = {"position": [0.0, 0.0, 1.5], "target": [0.0, 5.0, 1.5]}


def finite_and_drawable(doc):
    assert all(math.isfinite(x) for x in walk_numbers(doc))
    text = dumps(doc)
    assert "NaN" not in text and "Infinity" not in text
    svg = write_svg(doc)
    xml.dom.minidom.parseString(svg)
    low = svg.lower().replace("infinity", "")
    assert "nan" not in low and "inf" not in low
    return svg


def rect(doc, slack=1e-6):
    W, H = doc["canvas_mm"]
    return (-0.75 * W - slack, 0.75 * W + slack, -0.75 * H - slack, 0.75 * H + slack)


def ground_loops(doc):
    """World ``(x, y)`` polygons of every bounded §6.2 shadow loop."""
    loops = []
    for sh in doc["shadows"]:
        for loop in sh["loops"]:
            assert all(isinstance(e, str) for e in loop), "bounded loops only"
            loops.append(np.array([doc["points"][n]["world"][:2] for n in loop]))
    return loops


def ground_iou(scene, doc, n=500):
    """IoU of the §6.2 ground loops (nonzero rule) against the ray-casting reference (spec §7.3)."""
    light = scene["lights"][0]
    xs, ys = random_scenes.sample_grid(scene, light, n=n)
    ref = raycast.shadow_mask(scene, light, xs, ys)
    got = raster.rasterize_polygons(ground_loops(doc), xs, ys)
    return raster.iou(got, ref)


def image_space_reference(scene, doc, px_per_mm=2.0):
    """Rasterise the DRAWN shadow polygons on the extended canvas and compare them, pixel centre by
    pixel centre, with the ray-casting reference evaluated at the back-projection of the pixel to the
    ground plane (only pixels whose ground point lies in front of the near plane can be shadowed).

    Returns ``(iou, drawn_outside_ground_side, horizon_sign_ok)``: the IoU, the number of drawn pixels
    whose ground point is not in front of the camera, and whether every drawn polygon vertex lies on
    the ground side of the horizon line.
    """
    W, H = doc["canvas_mm"]
    u0, u1, v0, v1 = rect(doc, 0.0)
    xs = np.linspace(u0, u1, int(round(1.5 * W * px_per_mm)))
    ys = np.linspace(v0, v1, int(round(1.5 * H * px_per_mm)))
    polys = [np.array(p) for sh in doc["shadows"] for p in sh["polygons"] if len(p) >= 3]
    got = raster.rasterize_polygons(polys, xs, ys)
    P = np.array(doc["camera"]["P"])
    Hm = P[:, [0, 1, 3]]                                   # ground homography (x, y, 1) -> image
    Hinv = np.linalg.inv(Hm)
    near = scene["camera"]["near_m"]

    def back_project(uv):
        X = uv @ Hinv.T                                    # (x, y, w) up to scale
        k = X @ Hm[2]                                      # x̃3 of the re-projected point (same scale)
        w = X[:, 2]
        front = (np.abs(w) > 1e-15) & (k * w > 0)
        depth = np.where(front, k / np.where(front, w, 1.0), -1.0)
        return X, depth

    U, V = np.meshgrid(xs, ys)
    uv1 = np.stack([U.ravel(), V.ravel(), np.ones(U.size)], axis=1)
    X, depth = back_project(uv1)
    front = depth > near
    ref = np.zeros(U.size, dtype=bool)
    gp = np.stack([X[front, 0] / X[front, 2], X[front, 1] / X[front, 2], np.zeros(int(front.sum()))], axis=1)
    ref[front] = raycast.occluded(scene, scene["lights"][0], gp)
    ref = ref.reshape(U.shape)
    outside = int(np.count_nonzero(got & ~front.reshape(U.shape)))
    # horizon half-plane test on the polygon vertices: same sign as a ground pixel in front of the camera
    a, b, c = doc["horizon"]["line"]
    sample = uv1[front][0]
    s_ref = np.sign(a * sample[0] + b * sample[1] + c)
    ok = all(s_ref * (a * u + b * v + c) >= -1e-6 for poly in polys for u, v in poly)
    return raster.iou(got, ref), outside, ok


# --------------------------------------------------------------------------- row 1
def test_light_behind_viewer_gives_anti_light_point_below_horizon():
    scene = scene_with([BOX], {"id": "lamp", "type": "point", "position": [0.5, -4.0, 3.0]}, LEVEL_CAMERA)
    doc = castplane.render(scene)["geometry"]
    assert "LIGHT_BEHIND_CAMERA" in warning_codes(doc["warnings"])
    assert [w["ids"] for w in doc["warnings"] if w["code"] == "LIGHT_BEHIND_CAMERA"] == [["lamp"]]
    con = doc["construction"]
    assert con["light_point"] is not None and con["light_point"][1] < doc["horizon"]["v_mm"]
    assert doc["points"]["L.lamp"]["image"] == con["light_point"]      # never nulled
    assert doc["points"]["L.lamp"]["depth"] < 0
    # the shadow is in front of the camera and fully constructed
    sh = doc["shadows"][0]
    assert sh["outline"] and not sh["unbounded"] and len(sh["polygons"][0]) >= 3
    assert con["rays"] and con["checks"] and max(c["max_error_mm"] for c in con["checks"]) <= 1e-6
    # the 2-D ray L'P' covers L', P' and S' (contract §2.7 decision)
    for seg in con["segments"]:
        if seg["kind"] == "LP":
            a, b = (np.array(p) for p in seg["points"])
            d = b - a
            for name in (seg["point"], f"{seg['point']}.shadow.lamp"):
                q = np.array(doc["points"][name]["image"])
                t = float((q - a) @ d / (d @ d))
                assert -1e-9 <= t <= 1 + 1e-9
                np.testing.assert_allclose(a + t * d, q, atol=1e-6)
    svg = finite_and_drawable(doc)
    assert "L′" in svg


# --------------------------------------------------------------------------- row 2
def test_light_direction_parallel_to_picture_plane_gives_parallel_rays():
    light = {"id": "sun", "type": "directional", "direction": [0.6, 0.0, 0.8]}  # no y component: ⊥ forward
    scene = scene_with([BOX], light, LEVEL_CAMERA)
    doc = castplane.render(scene)["geometry"]
    assert "LIGHT_POINT_AT_INFINITY" in warning_codes(doc["warnings"])
    con = doc["construction"]
    assert con["light_point"] is None and con["light_point_at_infinity"] is not None
    assert doc["points"]["L.sun"]["image"] is None and doc["points"]["L.sun"]["at_infinity"] is True
    d_inf = np.array(con["light_point_at_infinity"])
    lp = [s for s in con["segments"] if s["kind"] == "LP"]
    assert len(lp) >= 4
    for seg in lp:  # every L'P' ray is parallel to the direction of L'
        a, b = (np.array(p) for p in seg["points"])
        d = b - a
        assert abs(d[0] * d_inf[1] - d[1] * d_inf[0]) <= 1e-9 * np.linalg.norm(d) * np.linalg.norm(d_inf)
    assert con["checks"] and max(c["max_error_mm"] for c in con["checks"]) <= 1e-6
    assert doc["shadows"][0]["outline"]
    finite_and_drawable(doc)


# --------------------------------------------------------------------------- row 3
def test_horizontal_directional_light_has_no_shadows():
    light = {"id": "sun", "type": "directional", "direction": [1.0, 0.0, 0.0]}
    scene = scene_with([BOX], light, {"position": [-3.0, -2.0, 1.5], "target": [0.0, 5.0, 1.0]})
    doc = castplane.render(scene)["geometry"]
    codes = warning_codes(doc["warnings"])
    assert "DIRECTIONAL_HORIZONTAL" in codes and "LIGHT_BELOW_RECEIVER" not in codes
    assert len(doc["shadows"]) == 1
    sh = doc["shadows"][0]
    assert sh["outline"] == [] and sh["loops"] == [] and sh["polygons"] == [] and sh["unbounded"] is False
    con = doc["construction"]
    assert con["rays"] == [] and con["segments"] == [] and con["checks"] == []
    # F at infinity is still reported: the shadow vanishing point lies on the horizon (yawed camera: finite)
    assert con["shadow_vp"] is not None
    a, b, c = doc["horizon"]["line"]
    assert abs(a * con["shadow_vp"][0] + b * con["shadow_vp"][1] + c) < 1e-6
    # the form shadow is still defined: the -x face is lit, the +x face unlit
    assert doc["form_shadow"] and any(e["silhouette"] for e in doc["edges"])
    finite_and_drawable(doc)


# --------------------------------------------------------------------------- row 4
def test_vertex_not_below_point_light_gives_unbounded_clipped_shadow():
    tall = {"id": "tower", "type": "box", "size": [1.0, 1.0, 3.0], "transform": {"position": [0.0, 5.0, 0.0]}}
    light = {"id": "lamp", "type": "point", "position": [2.5, 3.0, 2.0]}
    scene = scene_with([tall], light, {"position": [-1.0, -3.0, 3.0], "target": [0.0, 5.0, 1.0]})
    doc = castplane.render(scene)["geometry"]
    assert [w["ids"] for w in doc["warnings"] if w["code"] == "VERTEX_NOT_BELOW_LIGHT"] == [["tower"]]
    sh = doc["shadows"][0]
    assert sh["unbounded"] is True
    assert any(isinstance(e, dict) and "direction" in e for e in sh["outline"])
    for e in sh["outline"]:
        if isinstance(e, dict):
            assert abs(np.linalg.norm(e["direction"]) - 1.0) < 1e-12 and e["direction"][2] == 0.0
    # the top vertices have no shadow point; the bottom ones do
    assert "tower.v4.shadow.lamp" not in doc["points"] and "tower.v0.shadow.lamp" in doc["points"]
    # the drawn polygon is finite, clipped to the extended canvas and marked
    poly = sh["polygons"][0]
    assert len(poly) >= 3
    u0, u1, v0, v1 = rect(doc)
    for u, v in poly:
        assert u0 <= u <= u1 and v0 <= v <= v1
    svg = finite_and_drawable(doc)
    assert '<g id="cast_shadow.lamp"' in svg and "<path" in svg


# --------------------------------------------------------------------------- row 5
def test_vertex_or_shadow_behind_camera_is_clipped():
    # a box straddling the near plane, with the lamp ahead so that its shadow runs behind the (low) camera
    box = {"id": "crate", "type": "box", "size": [1.0, 1.0, 1.0], "transform": {"position": [0.0, 0.3, 0.0]}}
    light = {"id": "lamp", "type": "point", "position": [0.0, 6.0, 2.0]}
    scene = scene_with([box], light, {"position": [0.0, 0.0, 0.3], "target": [0.0, 5.0, 0.3]})
    doc = castplane.render(scene)["geometry"]
    assert [w["ids"] for w in doc["warnings"] if w["code"] == "POINT_BEHIND_CAMERA"] == [["crate"]]
    behind = [n for n, p in doc["points"].items() if p.get("image") is None and "world" in p]
    assert any(".shadow." in n for n in behind) and any(n == "crate.v0" or n == "crate.v1" for n in behind)
    # the shadow polygon is near-clipped: drawn (finite) although some of its vertices are behind
    sh = doc["shadows"][0]
    assert sh["outline"] and sh["polygons"][0]
    assert len(sh["polygons"][0]) != len(sh["outline"]) or any(doc["points"][n]["image"] is None
                                                               for n in sh["outline"])
    # object edges crossing the near plane are clipped segments; fully hidden ones dropped
    crate_edges = [e for e in doc["edges"] if e["object"] == "crate"]
    crossing = [e for e in crate_edges if e["segment"] is not None
                and (doc["points"][e["from"]]["image"] is None) != (doc["points"][e["to"]]["image"] is None)]
    assert crossing
    # rays exist only for vertices whose P, S and Q are all in front
    con = doc["construction"]
    for kind, name in con["rays"]:
        base = name[:-5] if kind == "F" else name
        for n in (base, f"{base}.shadow.lamp", f"{base}.foot"):
            assert doc["points"][n]["image"] is not None
    finite_and_drawable(doc)


# --------------------------------------------------------------------------- row 6
@pytest.mark.parametrize("light", [
    {"id": "lamp", "type": "point", "position": [0.5, 2.0, 3.0]},          # in the plane of the +x face
    {"id": "sun", "type": "directional", "direction": [0.0, 0.6, 0.8]},   # parallel to the ±x faces
])
def test_face_parallel_to_light_is_unlit(light):
    scene = scene_with([BOX], light, {"position": [3.0, -2.0, 2.0], "target": [0.0, 5.0, 0.5]})
    doc = castplane.render(scene)["geometry"]
    assert [w["ids"] for w in doc["warnings"] if w["code"] == "FACE_PARALLEL_TO_LIGHT"] == [["crate"]]
    faces = doc["form_shadow"][0]["faces"]
    # +x face (v1, v2, v6, v5) is parallel -> unlit -> in the form shadow
    assert any(set(f) == {"crate.v1", "crate.v2", "crate.v6", "crate.v5"} for f in faces)
    # the top face is lit (not in the form shadow)
    assert not any(set(f) == {"crate.v4", "crate.v5", "crate.v6", "crate.v7"} for f in faces)
    sh = doc["shadows"][0]
    assert sh["outline"] and not sh["unbounded"]
    finite_and_drawable(doc)


# --------------------------------------------------------------------------- extra: light-side rows of contract §2.3
def test_light_below_receiver_point_and_directional():
    for light in ({"id": "lamp", "type": "point", "position": [0.0, 3.0, -1.0]},
                  {"id": "sun", "type": "directional", "direction": [0.0, 0.6, -0.8]}):
        scene = scene_with([BOX], light, {"position": [3.0, -2.0, 2.0], "target": [0.0, 5.0, 0.5]})
        doc = castplane.render(scene)["geometry"]
        assert [w["ids"] for w in doc["warnings"] if w["code"] == "LIGHT_BELOW_RECEIVER"] == [[light["id"]]]
        assert doc["shadows"][0]["outline"] == [] and doc["construction"]["rays"] == []
        finite_and_drawable(doc)


def test_object_below_receiver_is_clipped_to_the_ground():
    buried = {"id": "crate", "type": "box", "size": [1.0, 1.0, 1.0], "transform": {"position": [0.0, 5.0, -0.5]}}
    light = {"id": "lamp", "type": "point", "position": [2.0, 2.0, 3.0]}
    scene = scene_with([buried], light, {"position": [3.0, -2.0, 2.0], "target": [0.0, 5.0, 0.5]})
    doc = castplane.render(scene)["geometry"]
    assert [w["ids"] for w in doc["warnings"] if w["code"] == "OBJECT_BELOW_RECEIVER"] == [["crate"]]
    sh = doc["shadows"][0]
    ground_names = [n for n in sh["outline"] if isinstance(n, str) and ".s" in n]
    assert ground_names, "ground-crossing vertices are inserted and named <obj>.s<k>.<light>"
    for n in ground_names:
        assert abs(doc["points"][n]["world"][2]) < 1e-9
    assert all(abs(doc["points"][n]["world"][2]) < 1e-9 for n in sh["outline"])
    assert "crate.v0.shadow.lamp" not in doc["points"]   # below-ground vertices get no shadow point
    finite_and_drawable(doc)


@pytest.mark.parametrize("name, obj, light", [
    ("half-buried box",
     {"id": "crate", "type": "box", "size": [1.0, 1.0, 1.0], "transform": {"position": [0.0, 5.0, -0.5]}},
     {"id": "lamp", "type": "point", "position": [-2.0, 2.0, 3.0]}),
    ("tilted buried box",
     {"id": "crate", "type": "box", "size": [1.0, 0.8, 1.2],
      "transform": {"position": [0.0, 5.0, -0.3], "rotation_deg": [25, -15, 30]}},
     {"id": "lamp", "type": "point", "position": [-2.0, 2.0, 3.0]}),
    ("tilted U prism, notch below the ground, point light",
     {"id": "u", "type": "prism", "polygon": random_scenes.u_polygon(2.0, 0.6, 1.5), "height": 1.0,
      "transform": {"position": [0.0, 5.0, -0.2], "rotation_deg": [15, 10, 20]}},
     {"id": "lamp", "type": "point", "position": [1.5, -1.0, 6.0]}),
    ("tilted U prism, notch below the ground, directional light",
     {"id": "u", "type": "prism", "polygon": random_scenes.u_polygon(2.0, 0.6, 1.5), "height": 1.0,
      "transform": {"position": [0.0, 5.0, -0.2], "rotation_deg": [15, 10, 20]}},
     {"id": "sun", "type": "directional", "direction": [0.3, -0.4, 0.8660254037844386]}),
])
def test_buried_object_shadow_is_that_of_the_part_above_the_ground(name, obj, light):
    """Contract §2.3: the drawn shadow of an object below the receiver is that of the part above the
    ground, footprint included (the cut face is part of the silhouette), checked against the ray caster."""
    scene = scene_with([obj], light, {"position": [3.0, -2.0, 2.0], "target": [0.0, 5.0, 0.5]})
    doc = castplane.render(scene)["geometry"]
    assert [w["ids"] for w in doc["warnings"] if w["code"] == "OBJECT_BELOW_RECEIVER"] == [[obj["id"]]]
    assert ground_iou(scene, doc) >= 0.99, name
    sh = doc["shadows"][0]
    ground_names = [n for n in sh["outline"] if ".s" in n]
    assert ground_names and all(abs(doc["points"][n]["world"][2]) < 1e-9 for n in ground_names)
    # every ground point directly under the object (inside its footprint) is in the drawn shadow
    light_dict = scene["lights"][0]
    xs, ys = random_scenes.sample_grid(scene, light_dict, n=300)
    X, Y = np.meshgrid(xs, ys)
    R, pos = raycast.object_frame(obj)
    loc = (np.stack([X.ravel(), Y.ravel(), np.zeros(X.size)], axis=1) - pos) @ R
    if obj["type"] == "box":
        sx, sy, sz = obj["size"]
        inside = (np.abs(loc[:, 0]) <= sx / 2) & (np.abs(loc[:, 1]) <= sy / 2) & (loc[:, 2] >= 0) & (loc[:, 2] <= sz)
    else:
        inside = ((loc[:, 2] >= 0) & (loc[:, 2] <= obj["height"])
                  & raycast.point_in_polygon(loc[:, 0], loc[:, 1], obj["polygon"]))
    drawn = raster.rasterize_polygons(ground_loops(doc), xs, ys).ravel()
    assert inside.any() and np.count_nonzero(inside & ~drawn) <= 0.002 * np.count_nonzero(inside)
    finite_and_drawable(doc)


def test_object_entirely_below_the_ground_casts_no_shadow():
    buried = {"id": "crate", "type": "box", "size": [1.0, 1.0, 1.0], "transform": {"position": [0.0, 5.0, -2.0]}}
    light = {"id": "lamp", "type": "point", "position": [2.0, 2.0, 3.0]}
    scene = scene_with([buried, BOX | {"id": "other"}], light,
                       {"position": [3.0, -2.0, 2.0], "target": [0.0, 5.0, 0.5]})
    doc = castplane.render(scene)["geometry"]
    assert [w["ids"] for w in doc["warnings"] if w["code"] == "OBJECT_BELOW_RECEIVER"] == [["crate"]]
    crate = [s for s in doc["shadows"] if s["object"] == "crate"][0]
    assert crate["outline"] == [] and crate["loops"] == [] and crate["polygons"] == [] and not crate["unbounded"]
    assert not any(".shadow." in n and n.startswith("crate.") for n in doc["points"])
    assert [s for s in doc["shadows"] if s["object"] == "other"][0]["outline"]
    assert ground_iou(scene, doc) >= 0.99
    finite_and_drawable(doc)


def test_vertical_directional_light_has_no_shadow_vanishing_point():
    """``F = foot(π, L)`` of a light along the receiver normal is the zero vector: no ``F`` point, no F rays,
    no null-direction warning; the self-check degenerates to ``S' = Q'`` and still runs."""
    light = {"id": "sun", "type": "directional", "direction": [0.0, 0.0, 1.0]}
    scene = scene_with([BOX], light, {"position": [3.0, -2.0, 2.0], "target": [0.0, 5.0, 0.5]})
    doc = castplane.render(scene)["geometry"]
    codes = warning_codes(doc["warnings"])
    assert "SHADOW_VP_AT_INFINITY" not in codes and "CONSTRUCTION_CHECK_SKIPPED" not in codes
    assert "F.sun" not in doc["points"] and doc["points"]["L.sun"]["at_infinity"] is True
    con = doc["construction"]
    assert con["shadow_vp"] is None and con["shadow_vp_at_infinity"] is None
    assert con["light_point"] is not None                      # L' = the zenith vanishing point
    np.testing.assert_allclose(con["light_point"], doc["horizon"]["vanishing_points"]["z"], atol=1e-9)
    assert con["rays"] and all(kind == "L" for kind, _ in con["rays"])
    assert {seg["kind"] for seg in con["segments"]} == {"LP", "PQ"}
    assert con["checks"] and max(c["max_error_mm"] for c in con["checks"]) <= 1e-6
    # the shadow of every vertex is its foot
    for name, p in doc["points"].items():
        if name.endswith(".shadow.sun"):
            np.testing.assert_allclose(p["world"], doc["points"][name[:-len(".shadow.sun")] + ".foot"]["world"])
    assert ground_iou(scene, doc) >= 0.99
    finite_and_drawable(doc)


def test_point_light_at_the_camera_centre_has_undefined_light_point():
    """``L' = P·L = 0`` for a light at the camera centre: no rounding-noise direction, no L rays, and the
    self-check degenerates to ``S' = P'`` (shadows hide exactly behind their objects)."""
    cam = {"position": [0.0, -5.0, 4.0], "target": [0.0, 5.0, 0.5]}
    light = {"id": "lamp", "type": "point", "position": [0.0, -5.0, 4.0]}
    scene = scene_with([BOX], light, cam)
    doc = castplane.render(scene)["geometry"]
    codes = warning_codes(doc["warnings"])
    assert "LIGHT_POINT_AT_INFINITY" not in codes and "LIGHT_BEHIND_CAMERA" not in codes
    assert "CONSTRUCTION_CHECK_SKIPPED" not in codes
    con = doc["construction"]
    assert con["light_point"] is None and con["light_point_at_infinity"] is None
    assert con["shadow_vp"] is not None
    assert con["rays"] and all(kind == "F" for kind, _ in con["rays"])
    assert {seg["kind"] for seg in con["segments"]} == {"FQ", "PQ"}
    assert con["checks"] and max(c["max_error_mm"] for c in con["checks"]) <= 1e-6
    for c in con["checks"]:
        vertex = c["point"][:-len(".shadow.lamp")]
        np.testing.assert_allclose(doc["points"][c["point"]]["image"], doc["points"][vertex]["image"], atol=1e-6)
    assert doc["points"]["L.lamp"]["image"] is None and abs(doc["points"]["L.lamp"]["depth"]) < 1e-9
    finite_and_drawable(doc)


# --------------------------------------------------------------------------- M2: curved degeneracies
def test_point_light_inside_a_sphere_only_warns():
    """Contract §2.6 / §2.9 ``LIGHT_INSIDE_OBJECT``: no shadow, no terminator and no construction points for
    that sphere; everything else (its outline, the other objects' shadows) is drawn."""
    ball = {"id": "ball", "type": "sphere", "radius": 0.8, "transform": {"position": [0.0, 5.0, 0.0]}}
    crate = {"id": "crate", "type": "box", "size": [1.0, 1.0, 1.0], "transform": {"position": [2.5, 5.0, 0.0]}}
    lamp = {"id": "lamp", "type": "point", "position": [0.2, 5.1, 0.9]}         # inside the ball
    scene = scene_with([ball, crate], lamp, {"position": [3.0, -2.0, 2.0], "target": [0.0, 5.0, 0.5]})
    doc = castplane.render(scene)["geometry"]
    inside = [w for w in doc["warnings"] if w["code"] == "LIGHT_INSIDE_OBJECT"]
    assert [w["ids"] for w in inside] == [["ball"]] and "sphere" in inside[0]["message"]
    sh = [s for s in doc["shadows"] if s["object"] == "ball"][0]
    assert sh["outline"] == [] and sh["loops"] == [] and sh["conics"] == [] and sh["polygons"] == []
    assert not sh["unbounded"]
    assert not any(n.startswith("ball.") and ".og" not in n for n in doc["points"])
    assert not any(f["object"] == "ball" for f in doc["form_shadow"])
    assert all(r[1].split(".")[0] == "crate" for r in doc["construction"]["rays"])
    assert [s for s in doc["shadows"] if s["object"] == "crate"][0]["outline"]
    assert [o["object"] for o in doc["outlines"]] == ["ball"] and doc["outlines"][0]["conics"]
    svg = finite_and_drawable(doc)
    assert '<g id="objects.ball"' in svg and '<g id="form_shadow.ball"' not in svg


@pytest.mark.parametrize("obj, light_pos", [
    ({"id": "b", "type": "box", "size": [2.0, 2.0, 2.0], "transform": {"position": [0.0, 5.0, 0.0]}},
     [0.0, 5.0, 1.0]),
    ({"id": "b", "type": "box", "size": [2.0, 1.0, 1.5],                      # rotated: the local frame matters
      "transform": {"position": [0.0, 5.0, 0.0], "rotation_deg": [0.0, 0.0, 45.0]}},
     [0.6, 5.6, 0.5]),
    ({"id": "b", "type": "prism", "height": 1.0,                              # concave U: light inside one arm
      "polygon": [[-1.5, -1], [1.5, -1], [1.5, 2], [0.5, 2], [0.5, 0], [-0.5, 0], [-0.5, 2], [-1.5, 2]],
      "transform": {"position": [0.0, 5.0, 0.0]}},
     [1.0, 6.5, 0.5]),
])
def test_point_light_inside_a_polyhedron_only_warns(obj, light_pos):
    """Contract §2.5 / §2.9 ``LIGHT_INSIDE_OBJECT`` for box / prism: a point light strictly inside the solid
    lights nothing, so the shadow record is empty, every face is in the form shadow, no construction rays
    exist for that object, and the other object is unaffected; the test is exact in the local frame (the
    concave case puts the light in one arm of a U, where some faces would otherwise count as lit)."""
    crate = {"id": "crate", "type": "box", "size": [1.0, 1.0, 0.3], "transform": {"position": [3.5, 5.0, 0.0]}}
    lamp = {"id": "lamp", "type": "point", "position": light_pos}
    scene = scene_with([obj, crate], lamp, {"position": [3.0, -3.0, 2.5], "target": [0.0, 5.0, 0.5]})
    doc = castplane.render(scene)["geometry"]
    inside = [w for w in doc["warnings"] if w["code"] == "LIGHT_INSIDE_OBJECT"]
    assert [w["ids"] for w in inside] == [["b"]] and obj["type"] in inside[0]["message"]
    assert [w["code"] for w in doc["warnings"] if "b" in w["ids"]] == ["LIGHT_INSIDE_OBJECT"]
    sh = [s for s in doc["shadows"] if s["object"] == "b"][0]
    assert sh["outline"] == [] and sh["loops"] == [] and sh["polygons"] == [] and not sh["unbounded"]
    fs = [f for f in doc["form_shadow"] if f["object"] == "b"]
    n_faces = 6 if obj["type"] == "box" else len(obj["polygon"]) + 2
    assert len(fs) == 1 and len(fs[0]["faces"]) == n_faces
    assert all(r[1].split(".")[0] == "crate" for r in doc["construction"]["rays"])
    assert not any(n.startswith("b.") and (".shadow." in n or n.endswith(".foot")) for n in doc["points"])
    assert [s for s in doc["shadows"] if s["object"] == "crate"][0]["outline"]
    assert all(e["silhouette"] is False for e in doc["edges"] if e["object"] == "b")
    finite_and_drawable(doc)
    # the same light in the notch of the U (outside the solid) or exactly on a box face is NOT inside
    for pos in ([0.0, 6.0, 0.5], [0.0, 5.0, obj["size"][2] if obj["type"] == "box" else 1.0]):
        doc2 = castplane.render(scene_with([obj, crate], dict(lamp, position=pos),
                                           {"position": [3.0, -3.0, 2.5], "target": [0.0, 5.0, 0.5]}))["geometry"]
        assert "LIGHT_INSIDE_OBJECT" not in warning_codes(doc2["warnings"])


def test_point_light_exactly_at_a_cylinder_cap_height():
    """Spec §5.7 rows 4 and 6 at once: the top cap is parallel to the light (``FACE_PARALLEL_TO_LIGHT``,
    unlit) and the top generator endpoints are at the light's height (``VERTEX_NOT_BELOW_LIGHT``): the top
    arc has no shadow, the generators end in direction vertices and the drawn region is the unbounded wedge
    checked against the ray caster in image space."""
    cyl = {"id": "drum", "type": "cylinder", "radius": 0.4, "height": 1.5, "transform": {"position": [0.0, 5.0, 0.0]}}
    lamp = {"id": "lamp", "type": "point", "position": [2.5, 4.0, 1.5]}
    scene = scene_with([cyl], lamp, {"position": [-1.0, -3.0, 3.0], "target": [0.0, 5.0, 1.0]})
    doc = castplane.render(scene)["geometry"]
    codes = warning_codes(doc["warnings"])
    assert "VERTEX_NOT_BELOW_LIGHT" in codes and "FACE_PARALLEL_TO_LIGHT" in codes
    assert all(w["ids"] == ["drum"] for w in doc["warnings"] if w["code"] in ("VERTEX_NOT_BELOW_LIGHT",
                                                                               "FACE_PARALLEL_TO_LIGHT"))
    sh = doc["shadows"][0]
    assert sh["unbounded"] and any(isinstance(e, dict) for e in sh["outline"])
    assert "drum.g0.base.shadow.lamp" in doc["points"] and "drum.g0.top.shadow.lamp" not in doc["points"]
    assert [c["which"] for c in sh["conics"]] == ["base"]             # the top arc (w_S = 0) casts nothing
    assert {r[1] for r in doc["construction"]["rays"]} <= {"drum.g0.base", "drum.g1.base", "drum.g0.base.foot",
                                                            "drum.g1.base.foot"}
    iou, outside, horizon_ok = image_space_reference(scene, doc)
    assert iou >= 0.99 and outside == 0 and horizon_ok
    finite_and_drawable(doc)


def unbounded_scenes():
    base = load_scene(EXAMPLES / "construction_demo.json")
    tower = {"id": "tower", "type": "box", "size": [1.0, 1.0, 3.0], "transform": {"position": [0.0, 5.0, 0.0]}}
    out = [("tower", scene_with([tower], {"id": "lamp", "type": "point", "position": [2.5, 3.0, 2.0]},
                                {"position": [-1.0, -3.0, 3.0], "target": [0.0, 5.0, 1.0]}))]
    s = copy.deepcopy(base)
    s["lights"][0]["position"] = [0.0, 4.0, 1.0]                        # lower than the block
    out.append(("low lamp", s))
    s = copy.deepcopy(base)
    s["lights"][0]["position"] = [0.5, -1.5, 1.4]                       # just in front of the camera, low
    out.append(("lamp near the camera", s))
    s = copy.deepcopy(base)
    s["lights"][0]["position"] = [0.0, -6.0, 1.2]                       # behind the camera, low: anti-light point
    out.append(("low lamp behind the camera", s))
    return out


@pytest.mark.parametrize("name, scene", unbounded_scenes())
def test_drawn_unbounded_shadow_polygons_match_the_raycast_reference_in_image_space(name, scene):
    """Spec §5.7 row 4 / contract §2.5: the DRAWN polygon of an unbounded shadow (direction vertices,
    arc at infinity, near clip, homogeneous rectangle clip) covers exactly the shadowed ground pixels
    of the extended canvas and never crosses the horizon."""
    doc = castplane.render(scene)["geometry"]
    assert any(sh["unbounded"] for sh in doc["shadows"]), name
    assert "VERTEX_NOT_BELOW_LIGHT" in warning_codes(doc["warnings"])
    iou, outside, horizon_ok = image_space_reference(scene, doc)
    assert iou >= 0.99, (name, iou)
    assert outside == 0, name
    assert horizon_ok, name
    finite_and_drawable(doc)


def test_image_space_reference_detects_a_clockwise_arc_at_infinity(monkeypatch):
    """The mutant that sweeps the arc at infinity clockwise must fail the image-space check."""
    import castplane.pipeline as pipeline
    from castplane import shadow as shadow_module
    real = shadow_module.shadow_loop

    def mutant(points4, M, pi, tol=0.0, tol_clip=None):
        out = real(points4, M, pi, tol, tol_clip)
        V = out["vertices"]
        src = out["sources"]
        # drop the inserted sweep vertices and reverse the remaining direction pair: the short, wrong arc
        keep = [k for k, s in enumerate(src) if not (isinstance(s, tuple) and s[0] == "arc")]
        dirs = [k for k in keep if abs(V[k, 3]) == 0.0]
        order = list(keep)
        if len(dirs) == 2:
            i, j = order.index(dirs[0]), order.index(dirs[1])
            order[i], order[j] = order[j], order[i]
        out["vertices"] = V[order]
        out["sources"] = [src[k] for k in order]
        # the pipeline draws the components (``loops``, one per cycle of the arc pairing): mutate them too
        out["loops"] = [{"vertices": out["vertices"], "sources": out["sources"], "unbounded": out["unbounded"]}]
        return out

    name, scene = unbounded_scenes()[0]
    monkeypatch.setattr(pipeline, "shadow_loop", mutant)
    doc = castplane.render(scene)["geometry"]
    iou, outside, horizon_ok = image_space_reference(scene, doc)
    assert iou < 0.99 or outside > 0 or not horizon_ok


def test_degenerate_example_renders_through_the_cli(tmp_path):
    from castplane.cli import main
    scene = copy.deepcopy(load_scene(EXAMPLES / "construction_demo.json"))
    scene["lights"][0]["position"] = [0.0, 4.0, 1.0]
    path = tmp_path / "low_lamp.json"
    import json
    path.write_text(json.dumps(scene), encoding="utf-8")
    assert main(["render", str(path), "-o", str(tmp_path)]) == 0
    assert (tmp_path / "low_lamp.svg").exists()


# --------------------------------------------------------------------------- M4: bounded receivers (contract §5.1.11)
from tests.test_receivers import wall_and_ground_scene


def _m4_variant(name):
    scene = wall_and_ground_scene()
    if name == "light behind the wall":
        scene["lights"] = [{"id": "lamp", "type": "point", "position": [0, 8, 3]}]
    elif name == "light in the wall plane":
        scene["lights"] = [{"id": "lamp", "type": "point", "position": [0, 6, 3]}]
    elif name == "sun parallel to the wall":
        scene["lights"] = [{"id": "lamp", "type": "directional", "direction": [0.6, 0.0, 0.8]}]
    elif name == "sun behind the wall":
        scene["lights"] = [{"id": "lamp", "type": "directional", "direction": [0.0, 0.6, 0.8]}]
    elif name == "light below the ground":
        scene["lights"] = [{"id": "lamp", "type": "point", "position": [0, 2, -1]}]
    elif name == "sun along the wall normal":
        scene["lights"] = [{"id": "lamp", "type": "directional", "direction": [0.0, -1.0, 0.0]}]
    elif name == "plate seen edge-on":
        scene["camera"] = {"position": [-6, 6, 1.6], "target": [0, 6, 1.0], "focal_length_mm": 35, "frame_mm": [36, 24]}
    elif name == "crate straddling the wall":
        scene["objects"][0]["transform"]["position"] = [0, 6.0, 0]
    elif name == "coplanar caster":
        scene["receivers"].append({"id": "tile", "type": "plane", "normal": [0, -1, 0], "offset": 6,
                                   "bounds": [[3, 6, 0], [5, 6, 0], [5, 6, 2.5], [3, 6, 2.5]]})
    return load_scene(scene)


M4_CASES = {
    "light behind the wall": {"RECEIVER_UNLIT"},
    "light in the wall plane": {"RECEIVER_UNLIT"},
    "sun parallel to the wall": {"RECEIVER_UNLIT"},
    "sun behind the wall": {"RECEIVER_UNLIT"},
    "light below the ground": {"RECEIVER_UNLIT", "LIGHT_BELOW_RECEIVER"},
    "sun along the wall normal": {"DIRECTIONAL_HORIZONTAL"},
    "plate seen edge-on": set(),
    "crate straddling the wall": set(),
    "coplanar caster": set(),
}


@pytest.mark.parametrize("name", sorted(M4_CASES))
def test_m4_receiver_degeneracies_warn_and_stay_finite(name):
    doc = castplane.render(_m4_variant(name))["geometry"]
    codes = warning_codes(doc["warnings"])
    assert M4_CASES[name] <= codes, (name, codes)
    assert not codes & {"OBJECT_BELOW_RECEIVER"} or name == "light below the ground", (name, codes)
    unlit = [w for w in doc["warnings"] if w["code"] == "RECEIVER_UNLIT"]
    assert all(w["ids"] == ["lamp", "wall"] for w in unlit)
    finite_and_drawable(doc)
    if name == "sun along the wall normal":
        assert "F.lamp.wall" not in doc["points"]
    if name == "light in the wall plane":
        assert {r["id"]: r["casts"]["lamp"] for r in doc["receivers"]}["wall"] is False


# --- M6: degenerate lights in a multi-light scene (contract §5.3.8, §5.3.10) ------------------
def scene_with_lights(objects, lights, camera):
    return load_scene({
        "version": "0.1",
        "objects": objects,
        "lights": lights,
        "receivers": [{"id": "ground", "type": "plane", "normal": [0, 0, 1], "offset": 0.0}],
        "camera": dict({"roll_deg": 0, "focal_length_mm": 24, "frame_mm": [36, 24], "near_m": 0.05}, **camera),
        "output": {"canvas_mm": [360, 240]},
    })


LAMP = {"id": "lamp", "type": "point", "position": [2.0, 2.0, 4.0]}


def test_m6_vertical_directional_light_as_the_second_light():
    """``F`` undefined for the second light: ``constructions[that].shadow_vp == null``, its rays have no ``F``
    entries; the first light's block is untouched (the single-light document of that light)."""
    zenith = {"id": "zenith", "type": "directional", "direction": [0.0, 0.0, 1.0]}
    r = castplane.render(scene_with_lights([BOX], [LAMP, zenith], LEVEL_CAMERA))
    doc = r["geometry"]
    finite_and_drawable(doc)
    c = doc["constructions"]["zenith"]
    assert c["shadow_vp"] is None and c["shadow_vp_at_infinity"] is None
    assert c["rays"] and all(kind == "L" for kind, _name in c["rays"])
    assert "F.zenith" not in doc["points"] and "F.lamp" in doc["points"]
    assert any(kind == "F" for kind, _name in doc["constructions"]["lamp"]["rays"])
    single = castplane.render(scene_with_lights([BOX], [LAMP], LEVEL_CAMERA))["geometry"]
    assert dumps(doc["constructions"]["lamp"]) == dumps(single["construction"])
    assert doc["umbra"][0]["lights"] == ["lamp", "zenith"]
    xml.dom.minidom.parseString(r["svg"])


def test_m6_both_lights_inactive():
    below = {"id": "below", "type": "point", "position": [0.0, 4.0, -1.0]}
    flat = {"id": "flat", "type": "directional", "direction": [1.0, 0.0, 0.0]}
    r = castplane.render(scene_with_lights([BOX], [below, flat], LEVEL_CAMERA))
    doc = r["geometry"]
    finite_and_drawable(doc)
    codes = {(w["code"], tuple(w["ids"])) for w in doc["warnings"]}
    assert ("LIGHT_BELOW_RECEIVER", ("below",)) in codes and ("DIRECTIONAL_HORIZONTAL", ("flat",)) in codes
    assert doc["umbra"] == [{"receiver": "ground", "lights": [], "polygons": []}]
    assert all(sh["polygons"] == [] for sh in doc["shadows"])
    assert '<g id="cast_shadow.umbra" fill="#000" fill-opacity="0.3" stroke="none"/>' in r["svg"]
    assert 'id="cast_shadow.below" fill-opacity="0.3"' in r["svg"]            # N_act = max(1, 0)
    xml.dom.minidom.parseString(r["svg"])
