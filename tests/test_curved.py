"""Closed-form and cross-check tests for castplane.curved (spec §5.6, §7.2 bullet 3,
§7.3; contract §2.6, §2.7, §2.10, §4 pillar/lamp case, M2 acceptance)."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from castplane.conics import (circle_embedding, circle_matrix, circle_point, classify, conic_entry,
                              conic_point, ellipse_params, functional_coeffs, sub_arcs_where_nonnegative,
                              transform_conic)
from castplane.curved import (ASYMPTOTE_REFINE, camera_outline, canonical_light, construction_points,
                              loop_pieces_4d, shadow_outline, shadow_polygon_h, silhouette, terminator)
from castplane.light import light_vector, lit
from castplane.primitives import build_object
from castplane.shadow import shadow_matrix, shadow_w

GROUND = np.array([0.0, 0.0, 1.0, 0.0])
TOL = 1e-9
#: "identity-like" 3x4 projection that drops z: H = DROP_Z @ M @ E is the ground conic map
DROP_Z = np.array([[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 0, 1.0]])


# --------------------------------------------------------------------------- helpers
def obj(kind, position=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0), oid="o", **params):
    d = {"id": oid, "type": kind, "transform": {"position": list(position), "rotation_deg": list(rotation)}}
    d.update(params)
    return build_object(d)


def point_light(x, y, z):
    return light_vector({"type": "point", "position": [x, y, z]})


def directional(phi_deg, az_deg):
    phi, az = math.radians(phi_deg), math.radians(az_deg)
    d = [math.cos(phi) * math.cos(az), math.cos(phi) * math.sin(az), math.sin(phi)]
    return light_vector({"type": "directional", "direction": d})


def signed_area(xy):
    P = np.asarray(xy, dtype=np.float64)
    x, y = P[:, 0], P[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def truncate(vertices4, far=1e4):
    """Replace direction vertices by finite points at distance ``far`` (ground x, y)."""
    out = []
    for v in vertices4:
        if v[3] == 0.0:
            out.append(v[:2] / np.linalg.norm(v[:2]) * far)
        else:
            out.append(v[:2] / v[3])
    return np.array(out)


def point_in_polygon(poly, p):
    wn = 0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        left = (x1 - x0) * (p[1] - y0) - (p[0] - x0) * (y1 - y0)
        if y0 <= p[1] < y1 and left > 0:
            wn += 1
        elif y1 <= p[1] < y0 and left < 0:
            wn -= 1
    return wn != 0


def ground_conic(piece):
    """Ground conic of a ``conic_arc`` piece with the z-dropping P (contract §2.6 H = P M E)."""
    arc = piece["conic_arc"]
    H = DROP_Z @ arc["T"] @ arc["E"]
    return transform_conic(circle_matrix(arc["rho"]), H)


def loop_points(sil, n=12):
    """World points sampled along the silhouette loop (segments: endpoints; arcs: n samples)."""
    pts = []
    for piece in loop_pieces_4d(sil):
        if "segment" in piece:
            pts.extend([piece["segment"][0][:3], piece["segment"][1][:3]])
        else:
            arc = piece["arc"]
            th = np.linspace(arc["theta0"], arc["theta1"], n)
            pts.extend(conic_point(arc["E"], th, arc["rho"])[:, :3])
    return np.array(pts)


def to_jsonable(x):
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, dict):
        return {k: to_jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [to_jsonable(v) for v in x]
    return x


def assert_same_structure(a, b, rel=1e-9, abs_=1e-9, path="root"):
    """Recursive equality of nested dict / list / array / scalar results, floats compared
    with a tolerance (spec §7.1 row 5: 1e-9)."""
    if isinstance(a, dict):
        assert isinstance(b, dict) and set(a) == set(b), path
        for k in a:
            assert_same_structure(a[k], b[k], rel, abs_, f"{path}.{k}")
    elif isinstance(a, (list, tuple, np.ndarray)):
        a_arr, b_arr = np.asarray(a, dtype=object), np.asarray(b, dtype=object)
        assert a_arr.shape == b_arr.shape, path
        for i, (x, y) in enumerate(zip(a_arr.ravel(), b_arr.ravel())):
            assert_same_structure(x, y, rel, abs_, f"{path}[{i}]")
    elif isinstance(a, (float, np.floating)) and not isinstance(a, bool):
        assert isinstance(b, (float, np.floating)), path
        assert a == pytest.approx(b, rel=rel, abs=abs_), path
    else:
        assert a == b, path


# --------------------------------------------------------------------------- §7.2 sphere, directional light
@pytest.mark.parametrize("phi_deg", [20.0, 35.0, 45.0, 60.0, 80.0])
@pytest.mark.parametrize("az_deg", [0.0, 123.0, 260.0])
def test_sphere_directional_shadow_closed_form(phi_deg, az_deg):
    """Spec §7.2 bullet 3: sphere centre (0, 0, r), sun at elevation phi -> shadow ellipse
    with semi-minor r, semi-major r / sin(phi), centre at r / tan(phi) opposite the light."""
    r = 0.7
    o = obj("sphere", radius=r)
    assert np.allclose(o["analytic"]["centre"], [0, 0, r])
    L = directional(phi_deg, az_deg)
    M = shadow_matrix(GROUND, L)
    out = shadow_outline(o["analytic"], L, M, GROUND, TOL, TOL)
    assert not out["unbounded"] and not out["empty"] and out["warnings"] == []
    assert len(out["pieces"]) == 1 and "conic_arc" in out["pieces"][0]
    piece = out["pieces"][0]
    assert abs(piece["conic_arc"]["theta1"] - piece["conic_arc"]["theta0"]) == pytest.approx(2 * math.pi)
    Cg = ground_conic(piece)
    assert classify(Cg) == "ellipse"
    centre, (major, minor), rot = ellipse_params(Cg)
    phi, az = math.radians(phi_deg), math.radians(az_deg)
    assert minor == pytest.approx(r, abs=1e-9)
    assert major == pytest.approx(r / math.sin(phi), abs=1e-9)
    expected_centre = -(r / math.tan(phi)) * np.array([math.cos(az), math.sin(az)])
    assert np.allclose(centre, expected_centre, atol=1e-9)
    if abs(major - minor) > 1e-6:
        assert math.cos(rot - az) ** 2 == pytest.approx(1.0, abs=1e-9)
    # the §3.1 conics entry built the documented way agrees
    entry = conic_entry(piece["conic_arc"]["circle"], DROP_Z @ M @ piece["conic_arc"]["E"], None, "shadow")
    assert entry["kind"] == "ellipse" and not entry["sampled"] and entry["arc"] is None
    assert np.allclose(np.array(entry["conic"]), Cg / Cg.ravel()[np.argmax(np.abs(Cg))])
    # the sampled polygon lies on the conic and is CCW
    poly = shadow_polygon_h(out)
    V = poly["vertices"]
    assert not poly["unbounded"] and len(V) == 64
    xy = V[:, :2] / V[:, 3:4]
    for p in xy:
        x = np.array([p[0], p[1], 1.0])
        assert abs(x @ Cg @ x) < 1e-9 * np.abs(Cg).max() * (x @ x)
    assert signed_area(xy) > 0
    assert signed_area(xy) == pytest.approx(math.pi * major * minor, rel=2e-3)


# --------------------------------------------------------------------------- point-light sphere
@pytest.mark.parametrize("c,r,l", [((0.0, 0.0, 1.0), 1.0, (3.0, 1.0, 4.0)), ((2.0, -1.0, 0.5), 0.5, (-2.0, 2.0, 2.5)),
                                   ((0.0, 0.0, 0.8), 0.8, (0.0, 0.0, 5.0))])
def test_sphere_point_light_silhouette_is_tangent_and_shadow_conic_passes_through_sil_points(c, r, l):
    c = np.array(c)
    o = obj("sphere", position=(c[0], c[1], c[2] - r), radius=r)
    L = point_light(*l)
    sil = silhouette(o["analytic"], L, TOL)
    circ = sil["circle"]
    v = np.array(l) - c
    assert np.allclose(circ["centre"], c + (r * r / (v @ v)) * v)
    assert circ["radius"] == pytest.approx(r * math.sqrt(1 - r * r / (v @ v)))
    assert np.allclose(circ["normal"], v / np.linalg.norm(v))
    # frame of contract §2.6: e1 = normalize(n x z) (fallback n x x), e2 = n x e1
    n = circ["normal"]
    e1 = np.cross(n, [0, 0, 1.0])
    e1 = np.cross(n, [1.0, 0, 0]) if np.linalg.norm(e1) <= 1e-9 else e1
    e1 = e1 / np.linalg.norm(e1)
    assert np.allclose(circ["e1"], e1) and np.allclose(circ["e2"], np.cross(n, e1))
    # tangency: every silhouette point p satisfies (p - c) . (l - p) = 0 and |p - c| = r
    for th in np.linspace(0, 2 * math.pi, 17):
        p = circle_point(circ, th)[:3]
        assert abs((p - c) @ (np.array(l) - p)) < 1e-9
        assert np.linalg.norm(p - c) == pytest.approx(r)
    # the ground shadow conic passes through the shadows of the four sil points
    M = shadow_matrix(GROUND, L)
    out = shadow_outline(o["analytic"], L, M, GROUND, TOL, TOL)
    assert not out["unbounded"]
    Cg = ground_conic(out["pieces"][0])
    pts = construction_points(o["analytic"], L, TOL, obj_id="s")
    assert list(pts) == ["s.c", "s.sil.0", "s.sil.1", "s.sil.2", "s.sil.3"]
    assert np.allclose(pts["s.c"], [c[0], c[1], c[2], 1.0])
    for k in range(4):
        S = M @ pts[f"s.sil.{k}"]
        x = np.array([S[0] / S[3], S[1] / S[3], 1.0])
        assert abs(x @ Cg @ x) < 1e-9 * np.abs(Cg).max() * (x @ x)
    # the centre's shadow is NOT the ellipse centre in general (contract §2.7), but it is inside
    S = M @ pts["s.c"]
    x = np.array([S[0] / S[3], S[1] / S[3], 1.0])
    centre, _, _ = ellipse_params(Cg)
    inside = np.array([centre[0], centre[1], 1.0])
    assert np.sign(x @ Cg @ x) == np.sign(inside @ Cg @ inside)
    # the terminator is the same circle, as an image-side drawable
    term = terminator(o["analytic"], L, TOL)
    assert len(term) == 1 and term[0]["circle_arc"]["full"]
    assert np.allclose(term[0]["circle_arc"]["circle"]["centre"], circ["centre"])


# --------------------------------------------------------------------------- §4 pillar under the lamp
def pillar():
    return obj("cylinder", position=(-1.5, 6.0, 0.0), radius=0.3, height=2.4, oid="pillar")


def test_pillar_tangent_generators_match_contract_section_4():
    """Contract §4: pillar base (-1.5, 6, 0), r = 0.3, h = 2.4 under the lamp (0, 3, 3.5):
    theta_l = -63.43 deg, generator angles -148.30 deg and 21.43 deg."""
    o = pillar()
    L = point_light(0.0, 3.0, 3.5)
    sil = silhouette(o["analytic"], L, TOL)
    assert sil["kind"] == "cylinder"
    assert math.degrees(sil["theta_l"]) == pytest.approx(-63.43, abs=0.01)
    angles = sorted(math.degrees(g["theta"]) for g in sil["generators"])
    assert angles[0] == pytest.approx(-148.30, abs=0.01)
    assert angles[1] == pytest.approx(21.43, abs=0.01)
    assert sil["cap_lit"] == {"base": False, "top": True}
    assert sil["lit_interval"] == pytest.approx([sil["theta_l"] - sil["alpha"], sil["theta_l"] + sil["alpha"]])
    # the generators are tangent: u_theta . (l - p) = 0 along the whole generator
    l = L[:3]
    for g in sil["generators"]:
        u = np.array([math.cos(g["theta"]), math.sin(g["theta"]), 0.0])
        for t in np.linspace(0, 1, 5):
            p = (1 - t) * g["base"] + t * g["top"]
            assert abs(u @ (l - p)) < 1e-9
        assert np.allclose(g["base"][:2], [-1.5, 6.0] + 0.3 * u[:2]) and g["base"][2] == pytest.approx(0.0)
        assert g["top"][2] == pytest.approx(2.4)
    # the lit interval agrees with the lateral lit test at sample angles
    for th in np.linspace(-math.pi, math.pi, 73):
        u = np.array([math.cos(th), math.sin(th), 0.0])
        p = o["analytic"]["base"] + 0.3 * u + 1.1 * o["analytic"]["axis"]
        inside = (th - sil["theta_l"] + math.pi) % (2 * math.pi) - math.pi
        if abs(abs(inside) - sil["alpha"]) > 1e-6:
            assert lit(u, p, L, TOL) == (abs(inside) < sil["alpha"])
    # loop = base arc (lit interval, CCW) + generator up + top arc (complement, CCW) + generator down
    kinds = [list(p)[0] for p in sil["loop"]]
    assert kinds == ["arc", "segment", "arc", "segment"]
    base_arc, top_arc = sil["loop"][0]["arc"], sil["loop"][2]["arc"]
    assert base_arc["which"] == "base" and top_arc["which"] == "top"
    assert base_arc["theta1"] > base_arc["theta0"] and top_arc["theta1"] > top_arc["theta0"]
    assert (base_arc["theta1"] - base_arc["theta0"]) + (top_arc["theta1"] - top_arc["theta0"]) == pytest.approx(2 * math.pi)
    names = list(construction_points(o["analytic"], L, TOL, obj_id="pillar"))
    assert names == ["pillar.g0.base", "pillar.g0.top", "pillar.g1.base", "pillar.g1.top"]
    # the shadow outline is bounded, CCW, its base arc is its own shadow and the conic
    # entries are healthy ellipses
    M = shadow_matrix(GROUND, L)
    out = shadow_outline(o["analytic"], L, M, GROUND, TOL, TOL)
    assert not out["unbounded"] and out["warnings"] == []
    kinds = [list(p)[0] for p in out["pieces"]]
    assert kinds == ["conic_arc", "segment", "conic_arc", "segment"]
    for piece in out["pieces"]:
        if "conic_arc" in piece:
            a = piece["conic_arc"]
            entry = conic_entry(a["circle"], DROP_Z @ a["T"] @ a["E"], (a["theta0"], a["theta1"]), "shadow")
            assert entry["kind"] == "ellipse" and not entry["sampled"]
            assert entry["arc"]["theta1"] > entry["arc"]["theta0"]
    poly = shadow_polygon_h(out)
    V = poly["vertices"]
    assert np.all(V[:, 3] > 0)
    xy = V[:, :2] / V[:, 3:4]
    assert signed_area(xy) > 0
    # generator base points are their own shadows
    S0 = M @ np.append(sil["generators"][0]["base"], 1.0)
    assert np.allclose(S0[:3] / S0[3], sil["generators"][0]["base"])


def test_pillar_camera_outline_generators_are_tangent_from_the_camera():
    o = pillar()
    C = np.array([0.0, 0.0, 1.5])
    co = camera_outline(o["analytic"], C, TOL)
    assert not co["camera_inside"]
    gens = co["generators"]
    assert len(gens) == 2
    for g in gens:
        u = np.array([math.cos(g["theta"]), math.sin(g["theta"]), 0.0])
        for t in (0.0, 0.5, 1.0):
            p = (1 - t) * g["base"] + t * g["top"]
            assert abs(u @ (C - p)) < 1e-9
    # camera below the top (z = 1.5 < 2.4): top cap not visible, base cap not visible either
    sil = co["silhouette"]
    assert sil["cap_lit"] == {"base": False, "top": False}
    arcs = co["cap_arcs"]
    assert len(arcs) == 4
    th0, th1 = gens[0]["theta"], gens[1]["theta"]
    for which in ("base", "top"):
        mine = [a for a in arcs if a["which"] == which]
        front = [a for a in mine if not a["back"]]
        back = [a for a in mine if a["back"]]
        assert len(front) == 1 and len(back) == 1
        assert front[0]["theta0"] == pytest.approx(th0) and front[0]["theta1"] == pytest.approx(th1)
        assert back[0]["theta0"] == pytest.approx(th1) and back[0]["theta1"] == pytest.approx(th0 + 2 * math.pi)
        # the front arc faces the camera: its midpoint's lateral normal sees the camera
        mid = 0.5 * (th0 + th1)
        u = np.array([math.cos(mid), math.sin(mid), 0.0])
        assert lit(u, mine[0]["circle"]["centre"] + 0.3 * u, np.append(C, 1.0), TOL)
    # camera above the top: the top circle is wholly front, the far base arc is back
    co2 = camera_outline(o["analytic"], [0.0, 0.0, 5.0], TOL)
    assert co2["silhouette"]["cap_lit"] == {"base": False, "top": True}
    assert all(not a["back"] for a in co2["cap_arcs"] if a["which"] == "top")
    assert [a["back"] for a in co2["cap_arcs"] if a["which"] == "base"] == [False, True]


# --------------------------------------------------------------------------- cone
@pytest.mark.parametrize("seed", range(6))
def test_cone_lit_is_constant_along_generators_and_matches_sign_formula(seed):
    rng = np.random.default_rng(seed)
    r, h = float(rng.uniform(0.2, 1.0)), float(rng.uniform(0.3, 2.0))
    rot = tuple(float(v) for v in rng.uniform(-40, 40, size=3))
    o = obj("cone", position=(0.0, 0.0, 0.5), rotation=rot, radius=r, height=h)
    an = o["analytic"]
    b, a, e1, e2 = an["base"], an["axis"], an["e1"], an["e2"]
    apex = b + h * a
    if seed % 2:
        L = point_light(*rng.uniform(-3, 3, size=2), float(rng.uniform(0.5, 4.0)))
    else:
        L = directional(float(rng.uniform(15, 80)), float(rng.uniform(0, 360)))
    sil = silhouette(an, L, TOL)
    l, w = L[:3], L[3]
    q = l - w * apex
    qa = float(q @ a)
    q_perp = q - qa * a
    for th in rng.uniform(-math.pi, math.pi, 40):
        u = math.cos(th) * e1 + math.sin(th) * e2
        n_th = h * u + r * a                       # contract §2.6 lateral normal (unnormalised)
        n_th = n_th / np.linalg.norm(n_th)
        formula = h * float(q_perp @ u) + r * qa  # contract §2.6 sign formula
        values = [n_th @ (l - w * ((1 - t) * (b + r * u) + t * apex)) for t in (0.0, 0.3, 0.7, 0.999)]
        assert max(values) - min(values) < 1e-9 * max(1.0, abs(values[0]))   # constant along the generator
        assert np.sign(values[0]) == np.sign(formula)
        # and matches the lit interval
        if sil["lit_interval"] == "all":
            assert formula > 0
        elif sil["lit_interval"] is None:
            assert formula <= 0
        else:
            inside = (th - sil["theta_l"] + math.pi) % (2 * math.pi) - math.pi
            if abs(abs(inside) - sil["alpha"]) > 1e-6:
                assert (formula > 0) == (abs(inside) < sil["alpha"])
    if sil["generators"]:
        # tangent-from-the-apex condition of §5.6: the generator base points are the
        # tangent points from l_a = v - (h / (q.a)) q (central projection of L through the apex
        # onto the base plane) when q.a != 0
        if abs(qa) > 1e-6:
            l_a = apex - (h / qa) * q
            assert abs((l_a - b) @ a) < 1e-9
            for g in sil["generators"]:
                p = g["base"]
                assert abs((p - b) @ (l_a - p)) < 1e-9
                assert np.allclose(g["top"], apex)
        names = list(construction_points(an, L, TOL, obj_id="k"))
        assert names == ["k.g0.base", "k.g1.base", "k.apex"]
        kinds = [list(p)[0] for p in sil["loop"]]
        assert kinds == ["arc", "segment", "segment"]
        assert np.allclose(sil["loop"][1]["segment"]["to"], apex) and np.allclose(sil["loop"][2]["segment"]["from"], apex)


# --------------------------------------------------------------------------- guards
def test_all_lit_all_unlit_and_on_axis_guards():
    # cone with the light on the axis above the apex: |q_perp| <= tol -> all lit iff r (q.a) > tol
    cone = obj("cone", radius=0.5, height=1.0)["analytic"]
    sil = silhouette(cone, point_light(0.0, 0.0, 3.0), TOL)
    assert sil["lit_interval"] == "all" and sil["generators"] == []
    assert len(sil["loop"]) == 1 and sil["loop"][0]["arc"]["which"] == "base"
    assert sil["loop"][0]["arc"]["theta1"] > sil["loop"][0]["arc"]["theta0"]    # CCW: light on the +a side
    assert construction_points(cone, point_light(0.0, 0.0, 3.0), TOL) == {}
    # directional light straight down the axis: all lit too
    assert silhouette(cone, directional(90.0, 0.0), TOL)["lit_interval"] == "all"
    # light far on the base side (below the base plane): lateral all unlit, base lit -> CW full base circle
    tilted = obj("cone", position=(0.0, 0.0, 3.0), rotation=(180.0, 0.0, 0.0), radius=0.5, height=1.0)["analytic"]
    assert np.allclose(tilted["axis"], [0, 0, -1])
    sil = silhouette(tilted, point_light(0.0, 0.0, 10.0), TOL)
    assert sil["lit_interval"] is None and sil["cap_lit"]["base"] is True
    assert len(sil["loop"]) == 1 and sil["loop"][0]["arc"]["theta1"] < sil["loop"][0]["arc"]["theta0"]
    # cone lit from the side with the light above the base plane but below the apex: partial
    sil = silhouette(cone, point_light(3.0, 0.0, 0.5), TOL)
    assert isinstance(sil["lit_interval"], list) and 0 < sil["alpha"] < math.pi
    # cylinder, directional light along the axis: d <= tol -> lateral unlit, top lit -> full top circle
    cyl = obj("cylinder", radius=0.3, height=1.0)["analytic"]
    sil = silhouette(cyl, directional(90.0, 0.0), TOL)
    assert sil["lit_interval"] is None and sil["generators"] == []
    assert len(sil["loop"]) == 1 and sil["loop"][0]["arc"]["which"] == "top"
    assert sil["warnings"] == []
    # point light exactly on the axis above: same
    sil = silhouette(cyl, point_light(0.0, 0.0, 4.0), TOL)
    assert sil["lit_interval"] is None and sil["cap_lit"] == {"base": False, "top": True}
    out = shadow_outline(cyl, point_light(0.0, 0.0, 4.0), shadow_matrix(GROUND, point_light(0, 0, 4.0)), GROUND, TOL, TOL)
    Cg = ground_conic(out["pieces"][0])
    centre, (major, minor), _ = ellipse_params(Cg)
    assert np.allclose(centre, 0) and major == pytest.approx(0.3 * 4.0 / 3.0) and minor == pytest.approx(major)
    # point light inside the cylinder (d <= r, caps unlit): LIGHT_INSIDE_OBJECT, no loop
    sil = silhouette(cyl, point_light(0.0, 0.1, 0.5), TOL)
    assert sil["light_inside"] and [w["code"] for w in sil["warnings"]] == ["LIGHT_INSIDE_OBJECT"]
    assert sil["loop"] == []
    # cylinder with the point light within the band d <= r + tol but outside -> cap circle only
    sil = silhouette(cyl, point_light(0.3 + 1e-12, 0.0, 2.0), TOL)
    assert sil["lit_interval"] is None and sil["generators"] == [] and len(sil["loop"]) == 1


def test_light_inside_sphere_yields_warning_and_no_shadow():
    sph = obj("sphere", radius=1.0)["analytic"]
    L = point_light(0.2, 0.1, 1.0)
    sil = silhouette(sph, L, TOL)
    assert sil["light_inside"] and sil["loop"] == [] and sil["circle"] is None
    assert [w["code"] for w in sil["warnings"]] == ["LIGHT_INSIDE_OBJECT"]
    assert "sphere" in sil["warnings"][0]["message"]
    out = shadow_outline(sph, L, shadow_matrix(GROUND, L), GROUND, TOL, TOL)
    assert out["empty"] and out["pieces"] == [] and [w["code"] for w in out["warnings"]] == ["LIGHT_INSIDE_OBJECT"]
    assert shadow_polygon_h(out)["vertices"].shape == (0, 4)
    assert construction_points(sph, L, TOL) == {}
    assert terminator(sph, L, TOL) == []
    # on the surface counts as inside (band), just outside does not
    assert silhouette(sph, point_light(1.0, 0.0, 1.0), TOL)["light_inside"]
    assert not silhouette(sph, point_light(1.0 + 1e-6, 0.0, 1.0), TOL)["light_inside"]
    # the camera inside the object is a flag only: no light warning leaks through (§2.9 has
    # no code for a camera inside an object)
    for an, C in ((sph, [0.0, 0.0, 1.0]),
                  (obj("cylinder", radius=0.5, height=1.0)["analytic"], [0.1, 0.0, 0.5]),
                  (obj("cone", radius=0.5, height=1.0)["analytic"], [0.0, 0.0, 0.2])):
        cam_out = camera_outline(an, C, TOL)
        assert cam_out["camera_inside"]
        assert cam_out["silhouette"]["warnings"] == []
        assert cam_out["generators"] == []
    assert camera_outline(sph, [0.0, 0.0, 5.0], TOL)["silhouette"]["warnings"] == []


def test_light_inside_message_names_the_primitive_kind():
    """The default ``LIGHT_INSIDE_OBJECT`` text of ``errors.WARNING_CODES`` names the sphere;
    cylinders and cones pass their own kind (contract §2.9 message field)."""
    cyl = obj("cylinder", radius=0.5, height=1.0)["analytic"]
    cone = obj("cone", radius=0.5, height=1.0)["analytic"]
    for an, L in ((cyl, point_light(0.4999, 0.0, 0.5)), (cone, point_light(0.0, 0.0, 0.2))):
        sil = silhouette(an, L, TOL)
        assert sil["light_inside"] and [w["code"] for w in sil["warnings"]] == ["LIGHT_INSIDE_OBJECT"]
        msg = sil["warnings"][0]["message"]
        assert an["kind"] in msg and "sphere" not in msg
        assert sil["warnings"][0]["ids"] == []
        out = shadow_outline(an, L, shadow_matrix(GROUND, L), GROUND, TOL, TOL)
        assert out["empty"] and out["warnings"][0]["message"] == msg


def test_cone_on_axis_guard_is_a_plain_length_comparison():
    """Contract §2.6 on-axis case ``|q_perp| <= tol``: all generators lit iff ``q . a > tol``.
    The predicate must not be scaled by the radius (a length^2 quantity against a length
    tolerance): a thin cone lit from just above its apex is wholly (grazingly) lit."""
    thin = obj("cone", radius=1e-3, height=1.0)["analytic"]
    # q . a = 1e-7 > tol, while r * (q . a) = 1e-10 <= tol would wrongly say "none"
    sil = silhouette(thin, point_light(0.0, 0.0, 1.0 + 1e-7), TOL)
    assert sil["lit_interval"] == "all" and sil["generators"] == []
    # from just below the apex (q . a < -tol) nothing is lit; the base is lit -> full CW base circle
    sil = silhouette(thin, point_light(0.0, 0.0, 1.0 - 1e-7), TOL)
    assert sil["lit_interval"] is None
    # directional light straight down the axis (dimensionless q . a = 1 > tol_dir): all lit
    assert silhouette(thin, directional(90.0, 0.0), TOL)["lit_interval"] == "all"
    # exactly at the apex height on the axis: the band counts as the degenerate side
    sil = silhouette(thin, point_light(0.0, 0.0, 1.0), TOL)
    assert sil["lit_interval"] is None and sil["light_inside"]


# --------------------------------------------------------------------------- spec §7.1 row 5: homogeneous scale invariance
def _scaled_cases():
    objects = [
        obj("sphere", position=(0.3, -0.2, 0.1), radius=0.6)["analytic"],
        obj("cylinder", position=(0.5, 1.0, 0.0), rotation=(20.0, -10.0, 35.0), radius=0.4, height=1.5)["analytic"],
        obj("cone", position=(-0.5, 0.5, 0.0), rotation=(-15.0, 25.0, 60.0), radius=0.4, height=1.5)["analytic"],
    ]
    lights = [point_light(3.0, 1.0, 2.5), point_light(-1.0, 2.0, 1.2), directional(35.0, 110.0), directional(70.0, 300.0)]
    return [(an, L) for an in objects for L in lights]


@pytest.mark.parametrize("case", range(12))
@pytest.mark.parametrize("s", [0.5, 2.0, 1e3, 1e-3])
def test_silhouette_and_shadow_are_invariant_under_positive_homogeneous_scaling(case, s):
    """Spec §7.1 row 5 / contract §2.1: ``silhouette`` (hence terminator, construction points,
    shadow outline and camera outline) must not change when ``L`` is multiplied by a positive
    scalar; the point-light predicates ``|l - c| - r``, ``|q_perp| - r`` and ``q . a`` are
    evaluated on the canonical representative ``L / w``."""
    an, L = _scaled_cases()[case]
    Ls = s * L
    assert np.allclose(canonical_light(Ls), canonical_light(L))
    sil, sil_s = silhouette(an, L, TOL), silhouette(an, Ls, TOL)
    assert_same_structure(sil, sil_s)
    assert sil["warnings"] == sil_s["warnings"] == []
    assert_same_structure(terminator(an, L, TOL), terminator(an, Ls, TOL))
    assert_same_structure(construction_points(an, L, TOL, "o"), construction_points(an, Ls, TOL, "o"))
    # the shadow outline with M built from the scaled L: the same dehomogenised polygon
    M, Ms = shadow_matrix(GROUND, L), shadow_matrix(GROUND, Ls)
    out, out_s = shadow_outline(an, L, M, GROUND, TOL, TOL), shadow_outline(an, Ls, Ms, GROUND, TOL, TOL)
    assert out["unbounded"] == out_s["unbounded"] and out["empty"] == out_s["empty"]
    assert [w["code"] for w in out["warnings"]] == [w["code"] for w in out_s["warnings"]]
    assert [list(p)[0] for p in out["pieces"]] == [list(p)[0] for p in out_s["pieces"]]
    V, Vs = shadow_polygon_h(out)["vertices"], shadow_polygon_h(out_s)["vertices"]
    assert V.shape == Vs.shape
    for v, vs in zip(V, Vs):
        if v[3] == 0.0:
            assert vs[3] == 0.0 and np.allclose(v[:3], vs[:3], atol=1e-9)
        else:
            assert vs[3] != 0.0 and np.allclose(v[:3] / v[3], vs[:3] / vs[3], rtol=1e-9, atol=1e-9)
    # the shadow conic matrices agree up to scale
    for p, ps in zip(out["pieces"], out_s["pieces"]):
        if "conic_arc" in p:
            Cg, Cgs = ground_conic(p), ground_conic(ps)
            assert np.allclose(Cg / np.abs(Cg).max(), Cgs / np.abs(Cgs).max(), atol=1e-9)
            assert p["conic_arc"]["theta0"] == pytest.approx(ps["conic_arc"]["theta0"])
            assert p["conic_arc"]["theta1"] == pytest.approx(ps["conic_arc"]["theta1"])


def test_scaled_light_inside_object_and_negative_w_are_canonicalised():
    sph = obj("sphere", radius=1.0)["analytic"]
    cyl = obj("cylinder", radius=0.5, height=1.0)["analytic"]
    L_in = point_light(0.2, 0.1, 1.0)
    for s in (0.5, 2.0, 1e3):
        assert silhouette(sph, s * L_in, TOL)["light_inside"]
        assert silhouette(cyl, s * point_light(0.1, 0.0, 0.5), TOL)["light_inside"]
        assert not silhouette(sph, s * point_light(1.0 + 1e-6, 0.0, 1.0), TOL)["light_inside"]
    # a negative w is the same projective point: canonicalised to (l, 1)
    L = point_light(3.0, 1.0, 2.5)
    assert np.allclose(canonical_light(-2.0 * L), L)
    assert_same_structure(silhouette(cyl, -2.0 * L, TOL), silhouette(cyl, L, TOL))
    # directions are made unit length; the zero vector is left alone
    assert np.allclose(canonical_light([0.0, 0.0, 5.0, 0.0]), [0.0, 0.0, 1.0, 0.0])
    assert np.allclose(canonical_light([0.0, 0.0, 0.0, 0.0]), 0.0)
    assert silhouette(sph, [0.0, 0.0, 0.0, 0.0], TOL)["loop"] == []


def test_sphere_frame_fallback_when_normal_is_vertical():
    sph = obj("sphere", radius=1.0)["analytic"]
    sil = silhouette(sph, directional(90.0, 0.0), TOL)      # n = z: fallback e1 = n x x
    circ = sil["circle"]
    assert np.allclose(circ["normal"], [0, 0, 1])
    assert np.allclose(circ["e1"], [0, 1, 0]) and np.allclose(circ["e2"], [-1, 0, 0])
    assert circ["radius"] == pytest.approx(1.0) and np.allclose(circ["centre"], [0, 0, 1])


# --------------------------------------------------------------------------- unbounded curved shadow
def test_unbounded_sphere_shadow_has_direction_vertices_and_contains_far_points():
    """Contract review example: sphere c = (2, 5, 1), r = 1 whose top (z = 2) is above the
    point light (-1, 5, 1.5)."""
    sph = obj("sphere", position=(2.0, 5.0, 0.0), radius=1.0)["analytic"]
    L = point_light(-1.0, 5.0, 1.5)
    M = shadow_matrix(GROUND, L)
    out = shadow_outline(sph, L, M, GROUND, TOL, TOL)
    assert out["unbounded"]
    assert [w["code"] for w in out["warnings"]] == ["VERTEX_NOT_BELOW_LIGHT"]
    kinds = [list(p)[0] for p in out["pieces"]]
    assert kinds == ["conic_arc", "direction", "direction"]
    arc = out["pieces"][0]["conic_arc"]
    # the kept arc has w_S >= tol everywhere and the dropped part has w_S <= tol
    for th in np.linspace(arc["theta0"], arc["theta1"], 200):
        X = conic_point(arc["E"], th, arc["rho"])
        assert shadow_w(GROUND, L, X) >= TOL * (1 - 1e-6)
    lo, hi = sorted((arc["theta0"], arc["theta1"]))
    for th in np.linspace(hi, lo + 2 * math.pi, 50)[1:-1]:
        X = conic_point(arc["E"], th, arc["rho"])
        assert shadow_w(GROUND, L, X) <= TOL
    # the ground conic is a hyperbola (the circle crosses the light's height plane)
    assert classify(ground_conic(out["pieces"][0])) == "hyperbola"
    d_out = [p for p in out["pieces"] if "direction" in p and p["role"] == "out"][0]["direction"]
    d_in = [p for p in out["pieces"] if "direction" in p and p["role"] == "in"][0]["direction"]
    for D in (d_out, d_in):
        assert D[3] == 0.0 and np.linalg.norm(D[:3]) == pytest.approx(1.0) and D[0] > 0.9   # away from the light (+x)
    assert d_out[1] < 0 < d_in[1]            # CCW sweep from out to in covers the +x wedge
    poly = shadow_polygon_h(out)
    V = poly["vertices"]
    assert poly["unbounded"] and np.all(np.isfinite(V))
    assert sum(1 for v in V if v[3] == 0.0) == 2       # a 33 deg sweep needs no intermediate vertex
    assert all(v[3] > 0 or v[3] == 0.0 for v in V)
    assert [s[2] for s in poly["sources"] if s[0] == "dir"] == ["out", "in"]
    trunc = truncate(V, 1e4)
    assert signed_area(trunc) > 0
    # far ground points in the shadow direction are inside the truncated polygon
    for far in (50.0, 500.0, 5000.0):
        assert point_in_polygon(trunc, (2.0 + far, 5.0))
        assert point_in_polygon(trunc, (2.0 + far, 5.0 + 0.2 * far))
        assert not point_in_polygon(trunc, (2.0 - far, 5.0))          # towards the light
        assert not point_in_polygon(trunc, (2.0, 5.0 + far))
    # near the sphere: the ground point under the sphere centre is in shadow, a point behind the light not
    assert point_in_polygon(trunc, (2.0, 5.0))
    assert not point_in_polygon(trunc, (-1.5, 5.0))
    # the direction vertices are the limits of the shadow rays of the arc endpoints
    for th, D in ((arc["theta1"], d_out), (arc["theta0"], d_in)):
        X = conic_point(arc["E"], th, arc["rho"])
        S = M @ X
        assert np.allclose(S[:3] / np.linalg.norm(S[:3]), D[:3], atol=1e-6)


def test_unbounded_cylinder_shadow_generators_crossing_the_light_height():
    """A cylinder taller than a nearby point light: both generators cross w_S = 0, the top arc
    is wholly dropped and the direction vertices follow the §2.5 rule."""
    cyl = obj("cylinder", position=(2.0, 0.0, 0.0), radius=0.4, height=3.0)["analytic"]
    L = point_light(0.0, 0.0, 1.5)
    M = shadow_matrix(GROUND, L)
    out = shadow_outline(cyl, L, M, GROUND, TOL, TOL)
    assert out["unbounded"]
    kinds = [list(p)[0] for p in out["pieces"]]
    assert kinds == ["conic_arc", "segment", "direction", "direction", "segment"]
    sil = out["silhouette"]
    g1 = sil["generators"][1]
    S_a = M @ np.append(g1["base"], 1.0)
    S_b = M @ np.append(g1["top"], 1.0)
    w_a, w_b = S_a[3], S_b[3]
    assert w_a > 0 > w_b
    t = w_a / (w_a - w_b)
    D = (1 - t) * S_a + t * S_b
    D = D[:3] / np.linalg.norm(D[:3])
    d_out = out["pieces"][2]["direction"]
    assert out["pieces"][2]["role"] == "out" and np.allclose(d_out[:3], D, atol=1e-6)
    poly = shadow_polygon_h(out)
    V = poly["vertices"]
    assert np.all(np.isfinite(V)) and poly["unbounded"]
    trunc = truncate(V, 1e4)
    assert signed_area(trunc) > 0
    for far in (20.0, 2000.0):
        assert point_in_polygon(trunc, (2.0 + far, 0.0))
        assert not point_in_polygon(trunc, (-far, 0.0))
    # the segment pieces never contain a vertex with w <= tol
    for p in out["pieces"]:
        if "segment" in p:
            assert all(s[3] > TOL for s in p["segment"])


def test_ground_clip_of_a_half_buried_sphere_and_a_tilted_base_circle():
    # sphere centred on the ground: the lower half is below the receiver
    sph = obj("sphere", position=(0.0, 0.0, -1.0), radius=1.0)["analytic"]
    L = point_light(3.0, 0.0, 4.0)
    M = shadow_matrix(GROUND, L)
    out = shadow_outline(sph, L, M, GROUND, TOL, TOL)
    assert out["below_ground"] and [w["code"] for w in out["warnings"]] == ["OBJECT_BELOW_RECEIVER"]
    kinds = [list(p)[0] for p in out["pieces"]]
    # the kept arc, then the ground chain (contract §2.3 cut face): a polyline of ground segments
    # along the lit half of the ground cross-section circle (radius 1 about the origin)
    assert kinds[0] == "conic_arc" and set(kinds[1:]) == {"segment"} and len(kinds) > 10
    ground = [p["segment"] for p in out["pieces"][1:]]
    assert all(p["which"] == "ground" for p in out["pieces"][1:])
    for A, B in ground:
        for S in (A, B):
            assert abs(S[2] / S[3]) < 1e-8          # the chain lies on the ground
    interior = [B for A, B in ground[:-1]]
    for S in interior:
        p = S[:3] / S[3]
        assert math.hypot(p[0], p[1]) == pytest.approx(1.0, abs=1e-9)   # on the cross-section circle
        assert lit(p, p, L, TOL)                                        # on the lit side of the sphere
    assert 20 <= len(interior) <= 30            # the lit arc p.l > r^2 spans 141 deg: 25 of 64 samples
    # consecutive chain segments share their end points (a connected polyline)
    for (_a, b), (c, _d) in zip(ground[:-1], ground[1:]):
        assert np.allclose(b, c)
    poly = shadow_polygon_h(out)
    V = poly["vertices"]
    assert np.all(V[:, 3] > 0) and signed_area(V[:, :2] / V[:, 3:4]) > 0
    # the lit half disc (towards the light, +x) is inside the shadow, the far half is not inside it
    # on its own merits: the chain bulges towards the light beyond the straight chord
    xy = V[:, :2] / V[:, 3:4]
    assert point_in_polygon(xy, (0.9, 0.0)) and point_in_polygon(xy, (0.5, 0.5))
    assert not point_in_polygon(xy, (1.05, 0.0))
    # a cylinder whose tilted base circle dips below the ground
    cyl = obj("cylinder", position=(0.0, 0.0, 0.1), rotation=(30.0, 0.0, 0.0), radius=0.5, height=1.0)["analytic"]
    out = shadow_outline(cyl, L, M, GROUND, TOL, TOL)
    assert out["below_ground"]
    ground = [p for p in out["pieces"] if "segment" in p and p["which"] == "ground"]
    assert len(ground) > 1
    a, b = cyl["axis"], cyl["base"]
    for p in ground:
        for S in p["segment"]:
            X = S[:3] / S[3]
            assert abs(X[2]) < 1e-8
            d = X - b
            s = float(d @ a)
            assert -1e-9 <= s <= 1.0 + 1e-9                                 # between the two caps
            assert np.linalg.norm(d - s * a) == pytest.approx(0.5, abs=1e-9)  # on the lateral surface
    poly = shadow_polygon_h(out)
    V = poly["vertices"]
    assert np.all(np.isfinite(V)) and np.all(V[:, 3] > 0)
    assert signed_area(V[:, :2] / V[:, 3:4]) > 0


def test_ground_chain_of_a_lit_cap_is_the_straight_cap_chord():
    """A cylinder standing on its (lit) top: the base cap faces up and dips below the ground on one
    side; the removed part of the loop is a cap arc and the boundary of the cut face there is the
    cap's own ground chord, so the chain is a single straight segment with both ends on the cap."""
    # axis tilted 10 deg from straight down: the base cap (z = 0.04 at its centre) dips below the ground
    # on the side where the lateral surface is unlit; the top cap is wholly buried, so both generators
    # also cross the ground and that second gap gets a lateral chain
    cyl = obj("cylinder", position=(0.0, 0.0, 0.04), rotation=(170.0, 0.0, 0.0), radius=0.5, height=1.0)["analytic"]
    L = point_light(0.0, 0.0, 6.0)
    M = shadow_matrix(GROUND, L)
    sil = silhouette(cyl, L, TOL)
    assert sil["cap_lit"]["base"] and not sil["cap_lit"]["top"]
    out = shadow_outline(cyl, L, M, GROUND, TOL, TOL)
    assert out["below_ground"]
    ground = [p for p in out["pieces"] if "segment" in p and p["which"] == "ground"]
    a, b = cyl["axis"], cyl["base"]

    def on_base_circle(S):
        X = S[:3] / S[3]
        return abs(float((X - b) @ a)) < 1e-9 and abs(np.linalg.norm(X - b) - 0.5) < 1e-9

    chords = [p for p in ground if all(on_base_circle(S) for S in p["segment"])]
    assert len(chords) == 1                                       # the lit cap's chord, straight
    A, B = chords[0]["segment"]
    assert abs(A[2] / A[3]) < 1e-8 and abs(B[2] / B[3]) < 1e-8 and np.linalg.norm(A[:3] / A[3] - B[:3] / B[3]) > 0.3
    lateral = [p for p in ground if p is not chords[0]]
    assert len(lateral) > 5
    for p in lateral:
        for S in p["segment"]:
            X = S[:3] / S[3]
            s = float((X - b) @ a)
            assert -1e-9 <= s <= 1.0 + 1e-9 and abs(np.linalg.norm(X - b - s * a) - 0.5) < 1e-9


def test_loop_wholly_below_the_ground_gives_the_lit_footprint():
    """A sphere buried past its centre under a steep directional light: the silhouette great circle
    is entirely below the receiver, the cap above it is wholly lit and its shadow is the footprint
    disc (contract §2.3 cut face).  A low point light sees part of that cap: its silhouette circle
    crosses the ground and the ordinary arc + chain outline results."""
    sph = obj("sphere", position=(0.0, 0.0, -1.3), radius=0.8)["analytic"]      # centre z = -0.5, top z = 0.3
    L = directional(70.0, 20.0)
    M = shadow_matrix(GROUND, L)
    out = shadow_outline(sph, L, M, GROUND, TOL, TOL)
    assert out["below_ground"] and not out["empty"] and not out["unbounded"]
    assert all("segment" in p and p["which"] == "ground" for p in out["pieces"])
    rs = math.sqrt(0.8 ** 2 - 0.5 ** 2)
    for p in out["pieces"]:
        for S in p["segment"]:
            X = S[:3] / S[3]
            assert abs(X[2]) < 1e-9 and math.hypot(X[0], X[1]) == pytest.approx(rs, abs=1e-9)
    V = shadow_polygon_h(out)["vertices"]
    assert len(V) == 64 and signed_area(V[:, :2] / V[:, 3:4]) == pytest.approx(math.pi * rs * rs, rel=0.01)
    L2 = point_light(5.0, 0.0, 0.1)
    out2 = shadow_outline(sph, L2, shadow_matrix(GROUND, L2), GROUND, TOL, TOL)
    kinds = [list(p)[0] for p in out2["pieces"]]
    assert out2["below_ground"] and out2["unbounded"]            # the light is below the top of the sphere
    assert kinds.count("conic_arc") >= 1 and kinds.count("segment") > 1
    V2 = shadow_polygon_h(out2)["vertices"]
    assert np.all(np.isfinite(V2)) and signed_area(truncate(V2, 1e4)) > 0


def test_direction_vertices_sit_at_the_exact_w_zero_crossing():
    """Contract §2.5: the direction vertex is the ``w_S = 0`` point of the piece (``t* = w_a /
    (w_a - w_b)`` on a segment, the closed-form zero crossing on an arc), not the ``w_S = tol``
    point where the kept part ends."""
    # arc: sphere whose top is above the light (see test_unbounded_sphere_shadow_...)
    sph = obj("sphere", position=(2.0, 5.0, 0.0), radius=1.0)["analytic"]
    L = point_light(-1.0, 5.0, 1.5)
    M = shadow_matrix(GROUND, L)
    big = 1e-3                                                   # a coarse tolerance makes the drift visible
    out = shadow_outline(sph, L, M, GROUND, big, big)
    arc = out["pieces"][0]["conic_arc"]
    A, B, C = functional_coeffs(M[3], arc["E"], arc["rho"])
    zeros = sub_arcs_where_nonnegative(A, B, C, 0.0, 2 * math.pi, 0.0)
    assert len(zeros) == 1
    z0, z1 = zeros[0]
    lo, hi = sorted((arc["theta0"], arc["theta1"]))
    assert z0 < lo and hi < z1                                    # the kept part ends at w_S = tol, inside
    d_out = [p for p in out["pieces"] if "direction" in p and p["role"] == "out"][0]["direction"]
    d_in = [p for p in out["pieces"] if "direction" in p and p["role"] == "in"][0]["direction"]
    for th, D in ((z1, d_out), (z0, d_in)):
        S = M @ conic_point(arc["E"], th, arc["rho"])
        assert abs(S[3]) < 1e-12
        assert np.allclose(S[:3] / np.linalg.norm(S[:3]), D[:3], atol=1e-12)
    # segment: cylinder generators crossing the light height
    cyl = obj("cylinder", position=(2.0, 0.0, 0.0), radius=0.4, height=3.0)["analytic"]
    L = point_light(0.0, 0.0, 1.5)
    M = shadow_matrix(GROUND, L)
    out = shadow_outline(cyl, L, M, GROUND, big, big)
    g1 = out["silhouette"]["generators"][1]
    S_a, S_b = M @ np.append(g1["base"], 1.0), M @ np.append(g1["top"], 1.0)
    t = S_a[3] / (S_a[3] - S_b[3])
    D = (1 - t) * S_a + t * S_b
    d_out = [p for p in out["pieces"] if "direction" in p and p["role"] == "out"][0]["direction"]
    assert np.allclose(d_out[:3], D[:3] / np.linalg.norm(D[:3]), atol=1e-12)


def test_polygon_refines_the_arc_towards_its_direction_vertices():
    """The samples next to a direction vertex approach the ``w_S = 0`` crossing geometrically
    (``w`` halves from one to the next) and their ground directions converge to the direction vertex."""
    sph = obj("sphere", position=(2.0, 5.0, 0.0), radius=1.0)["analytic"]
    L = point_light(-1.0, 5.0, 1.5)
    M = shadow_matrix(GROUND, L)
    out = shadow_outline(sph, L, M, GROUND, TOL, TOL)
    poly = shadow_polygon_h(out)
    V, src = poly["vertices"], poly["sources"]
    i_out = [k for k, s in enumerate(src) if s[0] == "dir" and s[2] == "out"][0]
    i_in = [k for k, s in enumerate(src) if s[0] == "dir" and s[2] == "in"][0]
    before = [k for k in range(i_out - ASYMPTOTE_REFINE, i_out)]
    after = [(i_in + 1 + j) % len(V) for j in range(ASYMPTOTE_REFINE)]
    assert all(isinstance(src[k][2], float) and src[k][2] != int(src[k][2]) for k in before + after)
    w_before = [V[k, 3] for k in before]
    assert all(0.4 < b / a < 0.6 for a, b in zip(w_before[:-1], w_before[1:]))
    w_after = [V[k, 3] for k in after]
    assert all(0.4 < a / b < 0.6 for a, b in zip(w_after[:-1], w_after[1:]))   # w doubles away from the crossing
    D_out, D_in = V[i_out, :2], V[i_in, :2]
    dev_out = [np.linalg.norm(V[k, :2] / np.linalg.norm(V[k, :2]) - D_out) for k in before]
    dev_in = [np.linalg.norm(V[k, :2] / np.linalg.norm(V[k, :2]) - D_in) for k in after]
    assert dev_out == sorted(dev_out, reverse=True) and dev_out[-1] < 0.01   # O(step / 2**K) away
    assert dev_in == sorted(dev_in) and dev_in[0] < 0.01
    assert signed_area(truncate(V, 1e6)) > 0


# --------------------------------------------------------------------------- raycast cross-check (§7.3)
def _curved_scene(seed, kind, light_type):
    from tests.reference import random_scenes
    rng = np.random.default_rng(seed)
    o = random_scenes.random_object(rng, 0, kind, allow_tilt=True)
    light = random_scenes.random_light(rng, [o], light_type)
    return random_scenes.assemble_scene([o], light, random_scenes.random_camera(rng, [o]))


@pytest.mark.parametrize("kind", ["sphere", "cylinder", "cone"])
@pytest.mark.parametrize("light_type", ["point", "directional"])
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_curved_shadow_matches_raycast_reference(kind, light_type, seed):
    from tests.reference import random_scenes
    from tests.reference.raster import iou, rasterize_polygons
    from tests.reference.raycast import shadow_mask

    scene = _curved_scene(seed, kind, light_type)
    light = scene["lights"][0]
    L = light_vector(light)
    M = shadow_matrix(GROUND, L)
    an = build_object(scene["objects"][0])["analytic"]
    out = shadow_outline(an, L, M, GROUND, TOL, TOL)
    assert not out["unbounded"] and not out["empty"]
    poly = shadow_polygon_h(out)
    V = poly["vertices"]
    assert np.all(np.isfinite(V)) and np.all(V[:, 3] > 0)
    xy = V[:, :2] / V[:, 3:4]
    assert signed_area(xy) > 0
    xs, ys = random_scenes.sample_grid(scene, light, n=400)
    assert iou(rasterize_polygons([xy], xs, ys), shadow_mask(scene, light, xs, ys)) >= 0.99


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_unbounded_curved_shadows_match_raycast_on_a_window(seed):
    """Low point light beside tall curved objects: the truncated polygon (direction vertices
    pushed far away) must still agree with the ray caster on a window around the object."""
    from tests.reference.raster import iou, rasterize_polygons
    from tests.reference.raycast import shadow_mask

    rng = np.random.default_rng(seed)
    kind = ["sphere", "cylinder", "cone"][seed % 3]
    params = {"radius": 0.8} if kind == "sphere" else {"radius": 0.5, "height": 2.5}
    o = {"id": "tall", "type": kind, "transform": {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]}}
    o.update(params)
    light = {"id": "light", "type": "point",
             "position": [float(rng.uniform(2.5, 4.0)), float(rng.uniform(-1.0, 1.0)), float(rng.uniform(0.6, 1.2))]}
    scene = {"objects": [o], "lights": [light]}
    L = light_vector(light)
    M = shadow_matrix(GROUND, L)
    an = build_object(o)["analytic"]
    out = shadow_outline(an, L, M, GROUND, TOL, TOL)
    assert out["unbounded"]
    poly = shadow_polygon_h(out)
    V = poly["vertices"]
    assert np.all(np.isfinite(V))
    trunc = truncate(V, 1e6)
    assert signed_area(trunc) > 0
    xs = np.linspace(-6, 3, 500)
    ys = np.linspace(-5, 5, 500)
    assert iou(rasterize_polygons([trunc], xs, ys), shadow_mask(scene, light, xs, ys)) >= 0.99


# --------------------------------------------------------------------------- determinism
def test_outline_is_deterministic_bytes():
    o = obj("cone", position=(1.0, 2.0, 0.0), rotation=(10.0, -5.0, 33.0), radius=0.4, height=1.3)["analytic"]
    L = point_light(-1.0, 0.5, 2.0)
    M = shadow_matrix(GROUND, L)

    def run():
        out = shadow_outline(o, L, M, GROUND, TOL, TOL)
        pieces = [{k: to_jsonable(v) for k, v in p.items()} for p in out["pieces"]]
        poly = shadow_polygon_h(out)
        return json.dumps({"pieces": pieces, "poly": poly["vertices"].tolist(), "src": [list(s) for s in poly["sources"]],
                           "sil": to_jsonable({k: v for k, v in silhouette(o, L, TOL).items()}),
                           "pts": to_jsonable(construction_points(o, L, TOL, "c"))}, sort_keys=True)

    assert run() == run()


def test_same_routine_serves_light_and_camera():
    """Contract §2.6: the camera outline is the silhouette with L = (C, 1)."""
    an = obj("cylinder", position=(1.0, 3.0, 0.0), rotation=(0, 0, 40.0), radius=0.3, height=1.2)["analytic"]
    C = np.array([-2.0, 0.0, 1.0])
    a = silhouette(an, np.append(C, 1.0), TOL)
    b = camera_outline(an, C, TOL)["silhouette"]
    assert a["theta_l"] == b["theta_l"] and a["alpha"] == b["alpha"]
    assert np.allclose([g["theta"] for g in a["generators"]], [g["theta"] for g in b["generators"]])


# --------------------------------------------------------------------------- robustness sweep (spec §7.1 "no NaN / no Inf")
@pytest.mark.parametrize("seed", range(4))
def test_random_placements_and_lights_never_produce_nan_and_stay_ccw(seed):
    """Tilted / partly buried objects, lights inside objects, low lights (unbounded
    shadows) and directional lights near the horizon: outputs are finite, direction
    vertices alternate out/in and the (truncated) polygon is counter-clockwise."""
    rng = np.random.default_rng(seed)
    for i in range(150):
        kind = ["sphere", "cylinder", "cone"][i % 3]
        d = {"id": "o", "type": kind, "radius": float(rng.uniform(0.1, 1.5)),
             "transform": {"position": [*rng.uniform(-3, 3, 2), float(rng.uniform(-0.5, 1.0))],
                           "rotation_deg": list(rng.uniform(-90, 90, 3))}}
        if kind != "sphere":
            d["height"] = float(rng.uniform(0.1, 3.0))
        an = build_object(d)["analytic"]
        if rng.uniform() < 0.6:
            L = point_light(*rng.uniform(-4, 4, 2), float(rng.uniform(0.05, 5.0)))
        else:
            L = directional(float(rng.uniform(0.5, 89.5)), float(rng.uniform(0, 360)))
        M = shadow_matrix(GROUND, L)
        out = shadow_outline(an, L, M, GROUND, TOL, TOL)
        poly = shadow_polygon_h(out)
        V = poly["vertices"]
        assert np.all(np.isfinite(V))
        assert np.all((V[:, 3] > 0.5 * TOL) | (V[:, 3] == 0.0))
        roles = [p["role"] for p in out["pieces"] if "direction" in p]
        assert roles == ["out", "in"] * (len(roles) // 2)
        assert out["unbounded"] == poly["unbounded"] == (len(roles) > 0)
        if len(V) >= 3:
            assert signed_area(truncate(V, 1e5)) > 0
        for v in construction_points(an, L, TOL, "o").values():
            assert np.all(np.isfinite(v))
        co = camera_outline(an, rng.uniform(-4, 4, 3), TOL)
        assert all(np.all(np.isfinite(g["base"])) and np.all(np.isfinite(g["top"])) for g in co["generators"])
        for entry in terminator(an, L, TOL):
            if "segment" in entry:
                assert np.all(np.isfinite(entry["segment"]))


# ---------------------------------------------------------------------------
# M7 precondition (contract §5.4.4 (6)): the batched stage B of curved objects == the per-object loop
# ---------------------------------------------------------------------------

def _conformance_case_names():
    import pathlib

    cases = pathlib.Path(__file__).resolve().parent / "conformance" / "cases"
    return sorted(p.stem for p in cases.glob("*.json"))


@pytest.mark.parametrize("name", _conformance_case_names())
def test_stage_b_objects_equals_per_object_loop(name, monkeypatch):
    """``curved.stage_b_objects`` (all curved objects of a scene with the point and segment projections
    batched) is a performance device: its result must equal :func:`curved.stage_b_object` called per
    curved object **byte for byte** (``dumps(compose(scene, B))``), because the TypeScript port implements
    the scalar semantics (contract §5.4.4 (6), a precondition of M7).  Checked on every conformance case
    with the scene camera and one override camera."""
    import pathlib
    import types

    import castplane
    from castplane import curved as curved_mod
    from castplane import pipeline
    from castplane.output.geometry_json import dumps
    from castplane.output.svg import write_svg
    from castplane.scene import load_scene

    path = pathlib.Path(__file__).resolve().parent / "conformance" / "cases" / f"{name}.json"
    scene = load_scene(path)
    A = castplane.shadow_geometry(scene)
    cam = scene["camera"]
    lens = {k: cam[k] for k in ("focal_length_mm", "frame_mm", "shift_mm", "near_m")}
    other = dict(lens, position=[6.0, -28.0, 12.0], target=[0.0, 0.0, 0.5], roll_deg=3.0)
    calls = []

    def looped(objs, recs, cam_, tol, warnings):
        assert len(objs) == len(recs)
        calls.append(len(objs))
        for obj, rec in zip(objs, recs):
            curved_mod.stage_b_object(obj, rec, cam_, tol, warnings)

    looped_module = types.SimpleNamespace(**{k: getattr(curved_mod, k) for k in dir(curved_mod)
                                             if not k.startswith("__")})
    looped_module.stage_b_objects = looped
    for camera in (None, other):
        batched = castplane.compose(scene, castplane.project_scene(scene, A, camera=camera))
        with monkeypatch.context() as m:
            m.setattr(pipeline, "_curved", looped_module)
            per_object = castplane.compose(scene, castplane.project_scene(scene, A, camera=camera))
        assert dumps(per_object) == dumps(batched)
        assert write_svg(per_object) == write_svg(batched)
    from castplane.primitives import CURVED_TYPES

    n_curved = sum(1 for o in scene["objects"] if o["type"] in CURVED_TYPES)
    assert calls == [n_curved, n_curved]      # the loop really replaced the batch, once per camera
