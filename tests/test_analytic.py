"""Hand-computed cases of spec §7.2 through the full pipeline (contract §4): the box ``h/(h−1)`` case,
sun elevation shadow lengths, the camera cases and the roll test vector of contract §2.2.
The sphere bullet (§7.2 third item) belongs to the curved-primitive track."""

from __future__ import annotations

import math

import numpy as np
import pytest

import castplane
from castplane.scene import load_scene


def scene_with(objects, light, camera, canvas=(360, 240), frame=(36, 24)):
    return load_scene({
        "version": "0.1",
        "objects": objects,
        "lights": [light],
        "receivers": [{"id": "ground", "type": "plane", "normal": [0, 0, 1], "offset": 0.0}],
        "camera": dict({"roll_deg": 0, "focal_length_mm": 35, "frame_mm": list(frame), "near_m": 0.05}, **camera),
        "output": {"canvas_mm": list(canvas)},
    })


FAR_CAMERA = {"position": [4.0, -8.0, 5.0], "target": [0.0, 0.0, 0.5]}


# --------------------------------------------------------------------------- §7.2 bullet 1
@pytest.mark.parametrize("h", [2.0, 3.0, 5.0, 1.5])
def test_unit_box_point_light_overhead_scales_base_by_h_over_h_minus_1(h):
    box = {"id": "cube", "type": "box", "size": [1.0, 1.0, 1.0]}
    doc = castplane.render(scene_with([box], {"id": "lamp", "type": "point", "position": [0.0, 0.0, h]},
                                      FAR_CAMERA))["geometry"]
    assert doc["warnings"] == []
    k = h / (h - 1.0)
    base = {"v0": (-0.5, -0.5), "v1": (0.5, -0.5), "v2": (0.5, 0.5), "v3": (-0.5, 0.5)}
    sh = [s for s in doc["shadows"] if s["object"] == "cube"][0]
    assert not sh["unbounded"] and len(sh["outline"]) == 4
    # silhouette = top face edges (the light is above the box, the sides are unlit): shadows of v4..v7
    for top, bottom in (("v4", "v0"), ("v5", "v1"), ("v6", "v2"), ("v7", "v3")):
        S = doc["points"][f"cube.{top}.shadow.lamp"]["world"]
        np.testing.assert_allclose(S, [k * base[bottom][0], k * base[bottom][1], 0.0], atol=1e-9)
    assert set(sh["outline"]) == {f"cube.v{i}.shadow.lamp" for i in (4, 5, 6, 7)}
    # outline area = k^2
    P = np.array([doc["points"][n]["world"][:2] for n in sh["outline"]])
    area = 0.5 * float(np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1]))
    assert area == pytest.approx(k * k, rel=1e-9)
    assert max(c["max_error_mm"] for c in doc["construction"]["checks"]) <= 1e-6


# --------------------------------------------------------------------------- §7.2 bullet 2
@pytest.mark.parametrize("elev_deg, factor", [(45.0, 1.0), (30.0, math.sqrt(3.0)), (60.0, 1.0 / math.sqrt(3.0))])
def test_sun_elevation_shadow_length(elev_deg, factor):
    height = 2.0
    post = {"id": "post", "type": "box", "size": [0.2, 0.2, height]}
    e, a = math.radians(elev_deg), math.radians(30.0)   # azimuth 30 deg: no face is parallel to the sun
    sun = {"id": "sun", "type": "directional",
           "direction": [math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)]}
    doc = castplane.render(scene_with([post], sun, FAR_CAMERA))["geometry"]
    assert doc["warnings"] == []
    # the shadow of a top vertex (x, y, height) is (x, y) - height / tan(e) * (cos a, sin a): its length
    # measured from the foot is height * factor (spec §7.2 bullet 2)
    # the +x, +y and top faces are lit: the silhouette top vertices are v4, v5, v7 (v6 is the lit corner)
    assert "post.v6.shadow.sun" not in doc["points"]
    for top, bottom in (("v4", "v0"), ("v5", "v1"), ("v7", "v3")):
        S = doc["points"][f"post.{top}.shadow.sun"]["world"]
        P = doc["points"][f"post.{top}"]["world"]
        Q = doc["points"][f"post.{bottom}"]["world"]
        np.testing.assert_allclose(S, [P[0] - height * factor * math.cos(a), P[1] - height * factor * math.sin(a),
                                       0.0], atol=1e-9)
        assert math.hypot(S[0] - Q[0], S[1] - Q[1]) == pytest.approx(height * factor, rel=1e-9)
    # F is at infinity in the direction of the sun's ground projection
    assert doc["points"]["F.sun"]["at_infinity"] is True
    np.testing.assert_allclose(np.array(doc["points"]["F.sun"]["direction"]) / math.cos(e),
                               [math.cos(a), math.sin(a), 0.0], atol=1e-12)
    assert max(c["max_error_mm"] for c in doc["construction"]["checks"]) <= 1e-6


# --------------------------------------------------------------------------- §7.2 bullet 4
def vertical_edges(doc):
    for e in doc["edges"]:
        a, b = doc["points"][e["from"]]["world"], doc["points"][e["to"]]["world"]
        if abs(a[0] - b[0]) < 1e-12 and abs(a[1] - b[1]) < 1e-12:
            yield doc["points"][e["from"]]["image"], doc["points"][e["to"]]["image"]


def test_level_camera_keeps_vertical_edges_vertical():
    objects = [{"id": "a", "type": "box", "size": [1.0, 0.8, 1.2], "transform": {"position": [1.0, 5.0, 0.0],
                                                                                 "rotation_deg": [0, 0, 25]}},
               {"id": "b", "type": "prism", "polygon": [[-0.5, -0.5], [0.5, -0.5], [0.0, 0.5]], "height": 2.0,
                "transform": {"position": [-2.0, 7.0, 0.0]}}]
    lamp = {"id": "lamp", "type": "point", "position": [0.0, 3.0, 4.0]}
    for cam in ({"position": [0.0, 0.0, 1.5], "target": [2.0, 5.0, 1.5]},
                {"position": [0.0, 0.0, 1.5], "yaw_deg": -20.0, "pitch_deg": 0.0}):
        doc = castplane.render(scene_with(objects, lamp, cam))["geometry"]
        n = 0
        for a, b in vertical_edges(doc):
            assert abs(a[0] - b[0]) < 1e-9
            n += 1
        assert n == 4 + 3
        assert doc["horizon"]["vanishing_points"]["z"] is None
        # the vertical construction lines P'Q' are vertical too
        for seg in doc["construction"]["segments"]:
            if seg["kind"] == "PQ":
                assert abs(seg["points"][0][0] - seg["points"][1][0]) < 1e-9


def test_pitched_camera_converges_vertical_edges_to_the_third_vanishing_point():
    objects = [{"id": "a", "type": "box", "size": [1.0, 0.8, 1.2], "transform": {"position": [1.0, 5.0, 0.0]}},
               {"id": "b", "type": "prism", "polygon": [[-0.5, -0.5], [0.5, -0.5], [0.0, 0.5]], "height": 2.0,
                "transform": {"position": [-2.0, 7.0, 0.0]}}]
    lamp = {"id": "lamp", "type": "point", "position": [0.0, 3.0, 4.0]}
    for cam, below in (({"position": [1.0, -2.0, 4.0], "target": [0.5, 5.0, 0.5]}, True),      # looking down
                       ({"position": [0.0, 0.0, 0.3], "yaw_deg": 0.0, "pitch_deg": 25.0}, False)):  # looking up
        doc = castplane.render(scene_with(objects, lamp, cam))["geometry"]
        vpz = doc["horizon"]["vanishing_points"]["z"]
        assert vpz is not None
        assert (vpz[1] < doc["horizon"]["v_mm"]) is below
        vpz_h = np.array([vpz[0], vpz[1], 1.0])
        for a, b in vertical_edges(doc):
            line = np.cross(np.array(a + [1.0]), np.array(b + [1.0]))
            line = line / np.max(np.abs(line))
            assert abs(line @ vpz_h) < 1e-6 * max(1.0, np.max(np.abs(vpz_h)))


def test_roll_test_vector_of_contract_2_2():
    # a box corner at world (0, 5, 2.5): box of size [1, 1, 2.5] anchored at (0.5, 5.5): v4 = (0, 5, 2.5)
    box = {"id": "b", "type": "box", "size": [1.0, 1.0, 2.5], "transform": {"position": [0.5, 5.5, 0.0]}}
    lamp = {"id": "lamp", "type": "point", "position": [0.0, 3.0, 4.0]}
    cam = {"position": [0.0, 0.0, 1.5], "target": [0.0, 5.0, 1.5], "roll_deg": 10.0, "focal_length_mm": 35}
    doc = castplane.render(scene_with([box], lamp, cam, canvas=(36, 24)))["geometry"]
    p = doc["points"]["b.v4"]
    np.testing.assert_allclose(p["world"], [0.0, 5.0, 2.5], atol=1e-12)
    assert abs(p["image"][0] - 35.0 * math.sin(math.radians(10.0)) * 0.2) < 1e-9
    assert abs(p["image"][0] - 1.2155) < 1e-4 and p["image"][0] > 0
