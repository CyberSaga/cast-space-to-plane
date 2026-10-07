"""Ray-casting comparison of the cast shadows (spec §7.3; contract §4, M3 gate).

For every seeded random scene the §6.2 shadow loops of the geometry document are
rasterised on a ground grid (world coordinates of the named points, direction entries
of unbounded outlines truncated at a large distance, **nonzero** rule across all loops
of one object, union across objects) and compared with the independent ray-casting
reference :func:`tests.reference.raycast.shadow_mask`: the IoU must be ≥ 0.99.

The union IoU is the spec gate, but it cannot see a missing or displaced shadow of a
*small* object among large ones (deleting a whole box from a ten-object scene costs
< 1 % of the union), so every object is additionally compared **on its own**: its loops
against the ray cast of a scene holding only that object, on a window and grid chosen
for that object, with the same ≥ 0.99 bound.

Grid: the window covers the objects, their analytic ground shadows and every finite
drawn shadow point, grown by a margin (capped around the objects for unbounded
shadows).  The resolution is chosen from a coarse pass so that the discretisation
error of a point-sampled region -- the expected relative area error
``sqrt(N_boundary) · h² / A`` with ``N_boundary ≈ P / h`` boundary cells for a shadow of
area ``A`` and perimeter ``P`` on cells of size ``h`` -- is below 0.5 %.

Curved objects (cylinder / sphere / cone, M2) take part when ``INCLUDE_CURVED`` is
true; the polyhedral families always run.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import castplane
from castplane.scene import load_scene
from tests.reference import random_scenes, raster, raycast

#: Curved primitives in the compared scenes (their shadows are the M2 conic outlines).
INCLUDE_CURVED = True

IOU_MIN = 0.99
#: Target discretisation error (relative area error estimate of the point sampling).
DISCRETISATION_TARGET = 0.005
N_COARSE = 256
N_MIN, N_MAX = 256, 1024
#: Safety factor on the resolution derived from the coarse pass (its boundary count is approximate).
RESOLUTION_SAFETY = 1.25
#: Direction entries of unbounded outlines are truncated at this multiple of the window extent.
FAR_FACTOR = 1e6
#: Window cap around the objects for scenes with far / unbounded shadows (metres).
WINDOW_CAP = 8.0

POLYHEDRAL = ("box", "prism")
CURVED = ("cylinder", "sphere", "cone")


# --------------------------------------------------------------------------- loops -> ground polygons
loop_entries_to_ground = raster.loop_entries_to_ground
doc_ground_loops = raster.doc_ground_loops


def stage_a_ground_loops(A: dict, centre, far: float) -> list:
    """The homogeneous ground polygons of stage A (``loops[k]["vertices"]``, ``w = 0`` rows are
    direction vertices) as ground polygons; the camera-free counterpart of :func:`doc_ground_loops`."""
    loops = []
    for rec in A["shadows"]:
        for loop in rec["loops"]:
            V = np.asarray(loop["vertices"], dtype=np.float64).reshape(-1, 4)
            if V.shape[0] < 3:
                continue
            out = []
            for v in V:
                if v[3] == 0.0:
                    n = float(np.hypot(v[0], v[1]))
                    out.append([centre[0] + far * v[0] / n, centre[1] + far * v[1] / n])
                else:
                    out.append([v[0] / v[3], v[1] / v[3]])
            loops.append(np.asarray(out))
    return loops


def finite_shadow_xy(doc: dict) -> np.ndarray:
    """Ground coordinates of every finite point named in a shadow loop."""
    pts = [doc["points"][e]["world"][:2] for sh in doc["shadows"] for loop in sh["loops"]
           for e in loop if isinstance(e, str)]
    return np.asarray(pts, dtype=np.float64).reshape(-1, 2)


def has_direction_entries(doc: dict) -> bool:
    return any(not isinstance(e, str) for sh in doc["shadows"] for loop in sh["loops"] for e in loop)


# --------------------------------------------------------------------------- window and resolution
def comparison_window(scene: dict, doc: dict):
    """``(lo, hi, centre, far)`` of the ground window (see module docstring)."""
    light = scene["lights"][0]
    lo, hi = random_scenes.shadow_window(scene, light, finite_shadow_xy(doc), margin=1.0)
    obj = np.vstack([random_scenes.world_extreme_points(o) for o in scene["objects"]])[:, :2]
    lo = np.maximum(lo, obj.min(axis=0) - WINDOW_CAP)
    hi = np.minimum(hi, obj.max(axis=0) + WINDOW_CAP)
    centre = 0.5 * (lo + hi)
    far = FAR_FACTOR * max(1.0, float(np.max(hi - lo)))
    return lo, hi, centre, far


def boundary_cells(mask: np.ndarray) -> int:
    """Number of cells whose 4-neighbourhood is not uniform (the boundary band of the mask)."""
    b = np.zeros(mask.shape, dtype=bool)
    b[:, 1:] |= mask[:, 1:] != mask[:, :-1]
    b[:, :-1] |= mask[:, 1:] != mask[:, :-1]
    b[1:, :] |= mask[1:, :] != mask[:-1, :]
    b[:-1, :] |= mask[1:, :] != mask[:-1, :]
    return int(np.count_nonzero(b))


def discretisation_error(mask: np.ndarray, h: float) -> float:
    """``sqrt(N_boundary) · h² / A``: expected relative error of the point-sampled area."""
    area = float(np.count_nonzero(mask)) * h * h
    if area == 0.0:
        return 0.0
    return math.sqrt(boundary_cells(mask)) * h * h / area


def choose_resolution(loops, lo, hi) -> tuple[int, float]:
    """Grid size per axis so that the discretisation error estimate is below the target
    (from a coarse pass); returns ``(n, coarse_error)``."""
    xs, ys = random_scenes.grid(lo, hi, N_COARSE)
    h0 = float(max(xs[1] - xs[0], ys[1] - ys[0]))
    mask = raster.rasterize_polygons(loops, xs, ys)
    err0 = discretisation_error(mask, h0)
    if err0 == 0.0:
        return N_MIN, 0.0
    area = float(np.count_nonzero(mask)) * h0 * h0
    perimeter = boundary_cells(mask) * h0
    # sqrt(P / h) · h² / A ≤ target  <=>  h ≤ (target · A / sqrt(P))^(2/3)
    h = (DISCRETISATION_TARGET * area / math.sqrt(perimeter)) ** (2.0 / 3.0)
    n = int(math.ceil(RESOLUTION_SAFETY * float(np.max(hi - lo)) / h)) + 1
    return max(N_MIN, min(N_MAX, n)), err0


def restrict(scene: dict, doc: dict, objects) -> tuple[dict, dict]:
    """Shallow copies of ``scene`` / ``doc`` holding only the given object ids (their shadows)."""
    sub_scene = dict(scene, objects=[o for o in scene["objects"] if o["id"] in objects])
    sub_doc = dict(doc, shadows=[sh for sh in doc["shadows"] if sh["object"] in objects])
    return sub_scene, sub_doc


def compare(scene: dict, doc: dict, loops=None, objects=None) -> dict:
    """IoU of the drawn loops against the ray caster; returns the measurements.  With
    ``objects`` (a set of ids) only those objects take part: their loops, their ray casts and
    a window / grid of their own."""
    if objects is not None:
        scene, doc = restrict(scene, doc, objects)
    lo, hi, centre, far = comparison_window(scene, doc)
    if loops is None:
        loops = doc_ground_loops(doc, centre, far)
    n, err0 = choose_resolution(loops, lo, hi)
    xs, ys = random_scenes.grid(lo, hi, n)
    h = float(max(xs[1] - xs[0], ys[1] - ys[0]))
    got = raster.rasterize_polygons(loops, xs, ys)
    ref = raycast.shadow_mask(scene, scene["lights"][0], xs, ys)
    return {
        "iou": raster.iou(got, ref),
        "n": n,
        "error": discretisation_error(got, h),
        "coarse_error": err0,
        "got": got,
        "ref": ref,
        "loops": loops,
        "window": (lo, hi, centre, far),
    }


def assert_iou(out: dict, scene: dict, what: str) -> None:
    assert out["iou"] >= IOU_MIN, (
        f"{what}: IoU {out['iou']:.4f} < {IOU_MIN} on a {out['n']}x{out['n']} grid "
        f"(discretisation error {out['error']:.4%}, light {scene['lights'][0]['type']})")
    assert out["error"] <= DISCRETISATION_TARGET or out["n"] == N_MAX, (what, out["error"])


def render_and_compare(scene: dict, per_object: bool = True) -> dict:
    """Render, compare the union of all shadows (the §7.3 gate) and, with ``per_object``,
    every object on its own (see the module docstring); returns the union measurements
    with the per-object IoUs under ``"per_object"``."""
    validated = load_scene(scene)
    doc = castplane.render(validated)["geometry"]
    out = compare(scene, doc)
    out["doc"] = doc
    assert_iou(out, scene, "union of all objects")
    out["per_object"] = {}
    if per_object and len(scene["objects"]) > 1:
        for o in scene["objects"]:
            single = compare(scene, doc, objects={o["id"]})
            assert_iou(single, scene, f"object {o['id']} ({o['type']}) alone")
            out["per_object"][o["id"]] = single["iou"]
    return out


# --------------------------------------------------------------------------- scene families
def polyhedral(seed):
    return random_scenes.make_polyhedral_scene(seed)


def concavity_u(seed):
    return random_scenes.make_concavity_scene(seed)


def concavity_u_directional(seed):
    return random_scenes.make_concavity_scene(seed, point_light=False)


def concavity_star(seed):
    return random_scenes.make_concave_star_scene(seed, n_extra=1 + seed % 3)


def concavity_star_unbounded(seed):
    return random_scenes.make_concave_star_scene(seed, n_extra=1, light_above=False)


def unbounded_polyhedral(seed):
    return random_scenes.make_unbounded_scene(seed, kinds=POLYHEDRAL)


def light_behind_camera_polyhedral(seed):
    return random_scenes.make_light_behind_camera_scene(seed, kinds=POLYHEDRAL)


def near_camera_polyhedral(seed):
    return random_scenes.make_near_camera_scene(seed, kinds=POLYHEDRAL)


def light_parallel_to_picture_plane_polyhedral(seed):
    return random_scenes.make_light_parallel_to_picture_plane_scene(seed, exact=seed % 2 == 1, kinds=POLYHEDRAL)


def mixed(seed):
    return random_scenes.make_scene(seed)


def curved_only(seed):
    return random_scenes.make_scene(seed, kinds=CURVED)


def unbounded_mixed(seed):
    return random_scenes.make_unbounded_scene(seed)


def cases(builder, seeds, curved: bool = False):
    marks = [pytest.mark.skipif(not INCLUDE_CURVED, reason="curved shadows need M2")] if curved else []
    return [pytest.param(builder, seed, id=f"{builder.__name__}-{seed}", marks=marks) for seed in seeds]


POLYHEDRAL_CASES = (
    cases(polyhedral, range(30))
    + cases(concavity_u, range(4))
    + cases(concavity_u_directional, range(2))
    + cases(concavity_star, range(4))
    + cases(concavity_star_unbounded, range(3))
    + cases(unbounded_polyhedral, range(6))
    + cases(light_behind_camera_polyhedral, range(2))
    + cases(near_camera_polyhedral, range(2))
    + cases(light_parallel_to_picture_plane_polyhedral, range(4))
)
CURVED_CASES = (
    cases(mixed, range(20), curved=True)
    + cases(curved_only, range(6), curved=True)
    + cases(unbounded_mixed, range(4), curved=True)
)


# --------------------------------------------------------------------------- tests
@pytest.mark.parametrize("builder, seed", POLYHEDRAL_CASES + CURVED_CASES)
def test_shadow_loops_match_raycast_reference(builder, seed):
    """Spec §7.3: IoU of the §6.2 loops against the ray caster ≥ 0.99."""
    scene = builder(seed)
    out = render_and_compare(scene)
    assert out["ref"].any(), "the reference mask is empty: the scene casts no shadow on the window"


@pytest.mark.parametrize("builder, seed", cases(unbounded_polyhedral, range(6)) + cases(concavity_star_unbounded, range(3)))
def test_unbounded_scenes_report_the_warning_and_direction_entries(builder, seed):
    """Spec §5.7 row 4: a point light lower than a silhouette vertex gives an unbounded outline with
    direction entries, flagged ``unbounded`` and ``VERTEX_NOT_BELOW_LIGHT``."""
    scene = builder(seed)
    doc = castplane.render(load_scene(scene))["geometry"]
    codes = {w["code"] for w in doc["warnings"]}
    light = scene["lights"][0]["position"]
    tops = [random_scenes.highest_z(o) for o in scene["objects"]]
    assert max(tops) > light[2]
    assert "VERTEX_NOT_BELOW_LIGHT" in codes
    unbounded = [s for s in doc["shadows"] if s["unbounded"]]
    assert unbounded
    for s in unbounded:
        assert any(isinstance(e, dict) and "direction" in e for loop in s["loops"] for e in loop)
    assert has_direction_entries(doc)


@pytest.mark.parametrize("builder, seed", cases(concavity_u, range(4)) + cases(concavity_star, range(4)))
def test_light_foot_lies_inside_the_concavity(builder, seed):
    """The dedicated §7.3 case: the foot of the point light is outside the concave prism but
    inside its convex hull, and the prism's shadow still matches the reference."""
    scene = builder(seed)
    prism = scene["objects"][0]
    light = scene["lights"][0]
    foot = np.array([[light["position"][0], light["position"][1], 0.0]])
    down = {"type": "directional", "direction": [0.0, 0.0, 1.0]}
    assert not raycast.occluded({"objects": [prism]}, down, foot)[0]
    R, pos = raycast.object_frame(prism)
    local = (foot[0] - pos) @ R
    hull = random_scenes.convex_hull(prism["polygon"])
    assert raycast.point_in_polygon(np.array([local[0]]), np.array([local[1]]), hull)[0]
    out = render_and_compare(scene)
    prism_loops = [s for s in out["doc"]["shadows"] if s["object"] == prism["id"]]
    assert prism_loops and prism_loops[0]["loops"]


@pytest.mark.parametrize("builder, seed", cases(polyhedral, [0, 1, 2, 3, 4]) + cases(unbounded_polyhedral, [0, 2]))
def test_doc_loops_agree_with_stage_a_polygons(builder, seed):
    """The truncated §6.2 loops and stage A's homogeneous ground polygons describe the same region
    (sanity check of this harness's own loop reconstruction, incl. direction vertices)."""
    scene = builder(seed)
    validated = load_scene(scene)
    A = castplane.shadow_geometry(validated)
    doc = castplane.compose(validated, castplane.project_scene(validated, A))
    lo, hi, centre, far = comparison_window(scene, doc)
    xs, ys = random_scenes.grid(lo, hi, 400)
    a = raster.rasterize_polygons(doc_ground_loops(doc, centre, far), xs, ys)
    b = raster.rasterize_polygons(stage_a_ground_loops(A, centre, far), xs, ys)
    assert raster.iou(a, b) >= 0.999


#: ``(builder, seed, object id)`` whose shadow can be deleted from the document without the union
#: IoU dropping below 0.99 (it is small, or mostly covered by other shadows).
BLIND_SPOTS = [
    pytest.param(polyhedral, 5, "obj1", id="polyhedral-5-obj1"),
    pytest.param(polyhedral, 26, "obj7", id="polyhedral-26-obj7"),
    pytest.param(mixed, 10, "obj3", id="mixed-10-obj3",
                 marks=[pytest.mark.skipif(not INCLUDE_CURVED, reason="curved shadows need M2")]),
    pytest.param(mixed, 17, "obj2", id="mixed-17-obj2",
                 marks=[pytest.mark.skipif(not INCLUDE_CURVED, reason="curved shadows need M2")]),
]


@pytest.mark.parametrize("builder, seed, victim", BLIND_SPOTS)
def test_per_object_gate_catches_a_missing_shadow_the_union_gate_misses(builder, seed, victim):
    """The union IoU survives the deletion of one object's whole shadow (which is why the union
    alone is not enough), while the per-object comparison of that object fails outright."""
    scene = builder(seed)
    doc = castplane.render(load_scene(scene))["geometry"]
    assert any(sh["object"] == victim and sh["loops"] for sh in doc["shadows"])
    pruned = dict(doc, shadows=[sh for sh in doc["shadows"] if sh["object"] != victim])
    union = compare(scene, pruned)
    assert union["iou"] >= IOU_MIN, union["iou"]          # the spec gate is blind to the deletion
    single = compare(scene, pruned, objects={victim})
    assert single["ref"].any() and single["iou"] == 0.0   # the per-object gate is not


def test_restrict_keeps_only_the_named_objects():
    scene = polyhedral(1)
    doc = castplane.render(load_scene(scene))["geometry"]
    oid = scene["objects"][0]["id"]
    sub_scene, sub_doc = restrict(scene, doc, {oid})
    assert [o["id"] for o in sub_scene["objects"]] == [oid]
    assert {sh["object"] for sh in sub_doc["shadows"]} == {oid}
    assert sub_doc["points"] is doc["points"] and sub_scene["lights"] == scene["lights"]


def test_parallel_light_family_puts_the_light_point_at_infinity():
    """The exact light-parallel-to-the-picture-plane family (odd seeds) renders with
    ``LIGHT_POINT_AT_INFINITY``; the nearly parallel one (even seeds) with a finite ``L'``."""
    for seed in (0, 1):
        scene = light_parallel_to_picture_plane_polyhedral(seed)
        doc = castplane.render(load_scene(scene))["geometry"]
        codes = {w["code"] for w in doc["warnings"]}
        assert ("LIGHT_POINT_AT_INFINITY" in codes) == (seed % 2 == 1), (seed, codes)
        assert doc["shadows"] and all(s["loops"] for s in doc["shadows"])


def test_resolution_rule_scales_with_the_shadow():
    """The chosen grid grows for thin shadows (large perimeter / area) and the error estimate
    shrinks with the cell size."""
    square = np.array([[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]])
    sliver = np.array([[-3.0, -0.05], [3.0, -0.05], [3.0, 0.05], [-3.0, 0.05]])
    lo, hi = np.array([-4.0, -4.0]), np.array([4.0, 4.0])
    n_square, e_square = choose_resolution([square], lo, hi)
    n_sliver, e_sliver = choose_resolution([sliver], lo, hi)
    assert n_sliver > n_square >= N_MIN
    assert e_sliver > e_square > 0.0
    xs, ys = random_scenes.grid(lo, hi, 800)
    h = float(xs[1] - xs[0])
    assert discretisation_error(raster.rasterize_polygons([square], xs, ys), h) < e_square
    assert discretisation_error(np.zeros((4, 4), dtype=bool), 1.0) == 0.0


def test_direction_truncation_reproduces_a_half_plane():
    """A loop ``A -> D_out -> (arc) -> D_in -> B`` with ``D`` directions truncated far away covers the
    half-plane region bounded by the two rays, like the homogeneous polygon does."""
    doc = {"points": {"a": {"world": [1.0, 0.0, 0.0]}, "b": {"world": [-1.0, 0.0, 0.0]}}, "shadows": []}
    loop = ["a", {"direction": [0.0, 1.0, 0.0]}, {"direction": [0.0, 1.0, 0.0]}, "b"]
    poly = loop_entries_to_ground(doc, loop, np.array([0.0, 0.0]), 1e6)
    xs, ys = random_scenes.grid([-3.0, -3.0], [3.0, 3.0], 301)
    mask = raster.rasterize_polygons([poly], xs, ys)
    X, Y = np.meshgrid(xs, ys)
    expected = (np.abs(X) < 1.0) & (Y > 0.0)
    assert raster.iou(mask, expected) >= 0.99


# --------------------------------------------------------------------------- M6: several lights (contract §5.3.10)
#: (seed, n_lights) of the multi-light comparison: ``make_scene(seed, n_objects, n_lights=…)``.
MULTI_LIGHT_CASES = [(seed, n) for n in (2, 3) for seed in range(8)]


def multi_light_scene(seed: int, n_lights: int) -> dict:
    return random_scenes.make_scene(seed, 2 + seed % 3, light_type="point" if seed % 2 == 0 else None,
                                    n_lights=n_lights)


def test_make_scene_single_light_is_unchanged_by_the_n_lights_argument():
    for seed in range(5):
        assert random_scenes.make_scene(seed) == random_scenes.make_scene(seed, n_lights=1)
    scene = random_scenes.make_scene(3, n_lights=3)
    assert [lt["id"] for lt in scene["lights"]] == ["light", "light1", "light2"]
    assert scene["lights"][0] == random_scenes.make_scene(3)["lights"][0]
    assert scene["camera"] == random_scenes.make_scene(3)["camera"]


@pytest.mark.parametrize("seed, n_lights", MULTI_LIGHT_CASES)
def test_multi_light_umbra_matches_the_raycast_and(seed, n_lights):
    """The reference "occluded from every light" (``raycast.occluded`` ANDed over the active lights) against
    the umbra pieces mapped back to the ground by ``H⁻¹``, IoU ≥ 0.99; each light's own drawables against
    its own ray cast as in v1 (union of the objects)."""
    from tests.test_multilight import umbra_raycast_iou
    scene = multi_light_scene(seed, n_lights)
    validated = load_scene(scene)
    doc = castplane.render(validated)["geometry"]
    assert len(doc["umbra"]) == 1 and len(doc["umbra"][0]["lights"]) >= 2
    assert umbra_raycast_iou(validated, doc) >= IOU_MIN
    for light in scene["lights"]:
        sub_scene = dict(scene, lights=[light])
        sub_doc = dict(doc, shadows=[sh for sh in doc["shadows"] if sh["light"] == light["id"]])
        out = compare(sub_scene, sub_doc)
        assert_iou(out, sub_scene, f"light {light['id']}")


def test_multi_light_cases_have_umbra():
    """The comparison above is not vacuous: most of its scenes have a non-empty umbra."""
    with_umbra = 0
    for seed, n_lights in MULTI_LIGHT_CASES:
        doc = castplane.render(load_scene(multi_light_scene(seed, n_lights)))["geometry"]
        with_umbra += bool(doc["umbra"][0]["polygons"])
    assert with_umbra >= len(MULTI_LIGHT_CASES) // 2
