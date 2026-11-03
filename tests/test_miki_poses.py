"""The Miki model's posed checks (``tools/miki_model/poses.py``, ``checks.py --poses``; milestone 2, "tested clearance").

Three layers:

* the pose maths against the real web code: ``tests/fixtures/miki_poses.json`` holds every object's final transform
  after each pose, written from the built web modules by ``tools/miki_model/pose_fixtures.mjs`` (``links.ts``
  ``resolve_links`` / ``subtree``, ``object_rotate.ts`` ``rotate_unit`` about ``world_centre(T, joint)``); the Python
  rigid map of every object agrees with it on three points (joint, joint + e_x, joint + e_z) within 1e-9 m, for every
  pose and angle, including the two-step pose; the motions go the way the table says (a sign test on centroids);
* the posed evaluation on synthetic parts: a join whose parts separate FAILs ("no longer meet"), a pair disjoint at
  rest that a pose makes cross FAILs under the generic rule, and the face masks come from the rest pose;
* the posed run on Miki (built once per module): the rest report is unchanged by ``--poses``, the pose requirements
  carry their table level (advisory, ``arms-inward`` required since profile v5) and are INDETERMINATE "not tested"
  without it, and the first failing angle of every cross pair is pinned.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import math
import pathlib
import sys
import time

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from miki_model import acceptance as ac  # noqa: E402
from miki_model import assemble as asm  # noqa: E402
from miki_model import checks  # noqa: E402
from miki_model import meshkit as mk  # noqa: E402
from miki_model import poses  # noqa: E402
from miki_model.rig import Rig  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "miki_poses.json"
#: The parity tolerance against the web code (m): the pose maths mirrors the TypeScript expression by expression, so
#: only libm's last-ulp differences (cos / sin / atan2 / hypot) remain.
PARITY_TOL = 1e-9


@pytest.fixture(scope="module")
def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def links():
    return asm.part_links(Rig())


# -- the pose maths against the web code ------------------------------------------------------------------------

def test_fixture_lists_the_python_poses(fixture, links):
    """pose_fixtures.mjs repeats the table: the same poses, angles, steps and subtrees, and the scene's links."""
    assert set(fixture["poses"]) == set(poses.POSES)
    for name, spec in poses.POSES.items():
        assert set(fixture["poses"][name]) == {poses.angle_key(a) for a in spec.sweeps}, name
        for a in spec.sweeps:
            case = fixture["poses"][name][poses.angle_key(a)]
            steps = [(s["object"], s["axis"], float(s["degrees"])) for s in case["steps"]]
            assert steps == list(poses.pose_steps(spec, a)), (name, a)
            for s in case["steps"]:
                assert s["moved"] == poses.subtree(s["object"]), (name, a, s["object"])
    for oid, (parent, joint) in links.items():
        assert fixture["parents"][oid] == parent and fixture["joints"][oid] == list(joint), oid


def _points(R, p, X):
    return np.stack([R[i][0] * X[:, 0] + R[i][1] * X[:, 1] + R[i][2] * X[:, 2] + p[i] for i in range(3)], axis=1)


def _parity(fixture, links):
    out = {}
    for name, spec in poses.POSES.items():
        worst = 0.0
        for a in spec.sweeps:
            case = fixture["poses"][name][poses.angle_key(a)]
            pivots = []
            T = poses.pose_transforms(Rig(), poses.pose_steps(spec, a), links, pivots=pivots)
            for s, c in zip(case["steps"], pivots):
                worst = max(worst, float(np.max(np.abs(np.asarray(c) - s["pivot"]))))
            for oid, o in case["objects"].items():
                j = np.asarray(links[oid][1], dtype=np.float64)
                X = np.stack([j, j + (1.0, 0.0, 0.0), j + (0.0, 0.0, 1.0)])
                got = poses.apply_transform(T[oid], X)
                want = _points(o["matrix"], o["position"], X)
                worst = max(worst, float(np.max(np.abs(got - want))))
        out[name] = worst
    return out


def test_pose_transforms_match_the_web_fixture(fixture, links):
    """Every object of every pose (the two-step bow + head turn included): the rigid map agrees with the web's on
    the joint, joint + e_x and joint + e_z, and every step's pivot is the web's world_centre(T, joint)."""
    dev = _parity(fixture, links)
    assert all(v <= PARITY_TOL for v in dev.values()), dev


def test_two_step_pose_turns_about_the_carried_joint(fixture, links):
    """bow-head-turn: the head turns about its joint as carried by the bow (not about the rest joint)."""
    steps = poses.pose_steps(poses.POSES["bow-head-turn"], 20.0)
    pivots = []
    T = poses.pose_transforms(Rig(), steps, links, pivots=pivots)
    j_head = np.asarray(links["head"][1])
    carried = poses.apply_transform(poses.pose_transforms(Rig(), steps[:1], links)["head"], j_head[None])[0]
    assert np.allclose(pivots[1], carried, atol=1e-12, rtol=0)
    assert np.linalg.norm(carried - j_head) > 0.05                     # the bow moved the neck joint
    head_after = poses.apply_transform(T["head"], j_head[None])[0]
    assert np.allclose(head_after, carried, atol=1e-12, rtol=0)        # the turn keeps its own pivot fixed
    case = fixture["poses"]["bow-head-turn"]["+20"]
    assert np.allclose(case["steps"][1]["pivot"], carried, atol=PARITY_TOL, rtol=0)


@pytest.fixture(scope="module")
def miki():
    return asm.assemble(Rig())


def _centroid(parts, name, posed=None):
    if posed is not None and name in posed:
        return posed[name].vertices.mean(axis=0)
    return next(p for p in parts if p.name == name).mesh.vertices.mean(axis=0)


#: The direction each pose moves a marker part (axis, sign): the motion the table names, independent of the sign
#: convention (the figure faces -Y, her left is +X).
DIRECTIONS = (
    ("head-turn", 10.0, "head.nose_mark", 0, +1),       # the face turns toward her left (+X)
    ("head-nod", 15.0, "head.mouth", 2, -1),             # down
    ("head-nod", -10.0, "head.mouth", 2, +1),            # up
    ("arms-raised", 30.0, "limbs.hand_l", 0, +1),        # sideways: her left hand out to +X ...
    ("arms-raised", 30.0, "limbs.hand_r", 0, -1),        # ... her right hand out to -X
    ("arms-raised", 30.0, "limbs.hand_l", 2, +1),        # and up
    ("arms-inward", 10.0, "limbs.sleeve_l", 0, -1),      # inward: her left sleeve toward the body (-X) ...
    ("arms-inward", 10.0, "limbs.sleeve_r", 0, +1),      # ... her right sleeve toward the body (+X)
    ("arms-forward", -30.0, "limbs.hand_l", 1, -1),      # forward (-Y)
    ("arms-forward", -30.0, "limbs.hand_r", 1, -1),
    ("step", -15.0, "limbs.shoe_l", 1, -1),              # the legs swing forward
    ("step", 15.0, "limbs.shoe_l", 1, +1),               # back
    ("bow", 10.0, "hair.dome", 1, -1),                   # the bow leans forward ...
    ("bow", 10.0, "hair.dome", 2, -1),                   # ... and down
)


@pytest.mark.parametrize("name, angle, part, axis, sign", DIRECTIONS)
def test_poses_move_the_way_the_table_says(miki, name, angle, part, axis, sign):
    posed = poses.posed_parts(miki.parts, Rig(), poses.pose_steps(poses.POSES[name], angle))
    d = _centroid(miki.parts, part, posed)[axis] - _centroid(miki.parts, part)[axis]
    assert sign * d > 0.005, (name, angle, part, d)


def test_posed_parts_are_rigid_images(miki):
    """posed_parts moves exactly the parts of the moved objects, rigidly (distances kept), the step's joint fixed."""
    steps = poses.pose_steps(poses.POSES["bow"], 20.0)
    posed = poses.posed_parts(miki.parts, Rig(), steps)
    moved = set(poses.moved_objects(steps))
    assert set(posed) == {p.name for p in miki.parts if p.obj in moved}
    rest = {p.name: p.mesh for p in miki.parts}
    for name, m in posed.items():
        V0, V1 = rest[name].vertices, m.vertices
        k = np.arange(0, len(V0), max(1, len(V0) // 16))
        d0 = np.linalg.norm(V0[k][:, None] - V0[k][None], axis=2)
        d1 = np.linalg.norm(V1[k][:, None] - V1[k][None], axis=2)
        assert np.max(np.abs(d0 - d1)) < 1e-12, name
        assert m.faces == rest[name].faces and m.groups == rest[name].groups
    T = poses.pose_transforms(Rig(), steps)
    j = np.asarray(asm.part_links(Rig())["blouse"][1])
    assert np.allclose(poses.apply_transform(T["blouse"], j[None])[0], j, atol=1e-12, rtol=0)


# -- the posed evaluation on synthetic parts ----------------------------------------------------------------------

def _box(lo, hi) -> mk.Mesh:
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    ring = lambda z: np.array([[x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z]])  # noqa: E731
    return mk.loft([ring(z0), ring(z1)], "flat", "flat")


def _rod(x, y, z0, z1, r=0.005, n=12) -> mk.Mesh:
    return mk.loft([mk.ellipse_ring(r, r, n, (x, y, z)) for z in (z0, z1)], "flat", "flat")


TOP = 0.05


def _swing_fixture():
    """A rod (object ``arm_l``) sunk into a box (``blouse``) through its top, hinged at its own top end; a wall
    (``skirt``) beside it, disjoint at rest.  Swinging the rod 90 deg about y lifts it out of the box and through the
    wall."""
    parts = [mk.Part("box", "skin", _box((-0.05, -0.05, 0.0), (0.05, 0.05, TOP)), obj="blouse"),
             mk.Part("rod", "skin", _rod(0.0, 0.0, 0.03, 0.1), obj="arm_l"),
             mk.Part("wall", "skin", _box((0.06, -0.05, 0.08), (0.09, 0.05, 0.12)), obj="skirt")]
    join = ac.Join("join:rod~box", "rod", "box", ac.Zone(z=(TOP, TOP)), None, 0.0, "fixture", "a rod in a box")
    pose = ac.Pose("pose:swing", "swing", "fixture", "posed clearance", steps=(("arm_l", "y", "-"),),
                   sweeps=(5.0, 90.0))
    links = dict(asm.part_links(Rig()))
    links["arm_l"] = ("blouse", (0.0, 0.0, 0.1))
    return parts, [join, pose], links


def test_posed_join_that_separates_and_a_new_crossing_fail():
    parts, profile, links = _swing_fixture()
    rest = checks.run(parts, profile=profile)
    names = {e["name"]: e for e in rest["requirements"]}
    assert names["join:rod~box"]["verdict"] == checks.PASS
    assert "generic:rod|wall" not in names                              # disjoint boxes at rest
    assert names["pose:swing"]["verdict"] == checks.INDETERMINATE
    rep = checks.add_poses(copy.deepcopy(rest), parts, profile=profile, links=links)
    small, big = rep["poses"]["swing"]["+5"], rep["poses"]["swing"]["+90"]
    assert small["failing"] == [] and small["changed"] == []
    assert big["failing"] == ["generic:rod|wall", "join:rod~box"]
    by = {e["name"]: e for e in big["changed"]}
    j = by["join:rod~box"]
    assert j["zone"] == "not tested in poses" and j["measured"]["parts_meet"] is False
    assert any(f["what"].startswith("the parts no longer meet") for f in j["findings"])
    g = by["generic:rod|wall"]
    assert g["rest_verdict"] == checks.PASS and "disjoint" in g["rest_note"] and g["measured"]["crossings"] > 0
    assert rep["pose_tables"]["swing"]["first_failing"] == {"box|rod": ["+90"], "rod|wall": ["+90"]}
    p = next(e for e in rep["requirements"] if e["name"] == "pose:swing")
    assert p["verdict"] == checks.FAIL and p["level"] == "advisory"
    assert rep["summary"]["required_pass"] is True                       # advisory: never gates


def test_required_pose_gates_the_posed_run():
    """Profile v5: a required pose not tested (no --poses) leaves the rest gate green; tested, a failing angle
    fails it, and a clean sweep passes it."""
    parts, profile, links = _swing_fixture()
    required = [profile[0], dataclasses.replace(profile[1], level="required")]
    rest = checks.run(parts, profile=required)
    p = next(e for e in rest["requirements"] if e["name"] == "pose:swing")
    assert p["verdict"] == checks.INDETERMINATE and p["level"] == "required"
    assert rest["summary"]["required_pass"] is True
    rep = checks.add_poses(copy.deepcopy(rest), parts, profile=required, links=links)
    assert next(e for e in rep["requirements"] if e["name"] == "pose:swing")["verdict"] == checks.FAIL
    assert rep["summary"]["required_pass"] is False                      # +90 crosses the wall
    clean = [profile[0], dataclasses.replace(profile[1], level="required", sweeps=(5.0,))]
    rest = checks.run(parts, profile=clean)
    rep = checks.add_poses(copy.deepcopy(rest), parts, profile=clean, links=links)
    assert next(e for e in rep["requirements"] if e["name"] == "pose:swing")["verdict"] == checks.PASS
    assert rep["summary"]["required_pass"] is True


def test_posed_masks_come_from_the_rest_pose():
    """A selector written in the rest frame (z range) keeps its rest faces on the posed part; the posed part itself
    refuses to select."""
    parts, _profile, links = _swing_fixture()
    geo = {p.name: checks.PartGeom(p.name, p.obj, p.mesh) for p in parts}
    rest = checks.Checker(geo)
    steps = (("arm_l", "y", -90.0),)
    T = poses.pose_transforms(Rig(), steps, links)
    posed = dict(geo, rod=checks.PosedPartGeom(geo["rod"], T["arm_l"]))
    chk = checks.PosedChecker(posed, rest, {})
    low = ac.Select(z=(0.0, 0.04), note="the buried end")
    m = chk.sel("rod", low, chk.eps)
    assert m.any() and np.array_equal(m, geo["rod"].select(low, chk.eps))
    with pytest.raises(RuntimeError):
        posed["rod"].select(low, chk.eps)
    assert np.allclose(np.linalg.norm(posed["rod"].normal, axis=1), 1.0)


# -- the posed run on Miki ----------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def miki_runs(miki):
    rest = checks.run(miki.parts, reports=miki.reports)
    t = time.perf_counter()
    posed = checks.add_poses(copy.deepcopy(rest), miki.parts, rig=miki.rig, reports=miki.reports)
    return rest, posed, time.perf_counter() - t


def _strip(report):
    r = copy.deepcopy(report)
    r["requirements"] = [e for e in r["requirements"] if e["kind"] != "pose"]
    r["summary"]["counts"].pop("pose", None)
    r.pop("poses", None)
    r.pop("pose_tables", None)
    return checks.dumps(r)


def test_default_run_does_not_test_poses(miki_runs):
    rest, _posed, _t = miki_runs
    assert "poses" not in rest and "pose_tables" not in rest
    pose = [e for e in rest["requirements"] if e["kind"] == "pose"]
    assert [e["name"] for e in pose] == sorted(f"pose:{n}" for n in poses.POSES)
    for e in pose:
        level = poses.POSES[e["name"].split(":", 1)[1]].level
        assert e["level"] == level and e["verdict"] == checks.INDETERMINATE and "not tested" in e["verdict_reason"]
    assert [e["name"] for e in pose if e["level"] == "required"] == ["pose:arms-inward"]
    assert rest["summary"]["required_pass"] is True                       # a required pose not tested does not gate
    assert rest["summary"]["counts"]["pose"] == {"PASS": 0, "FAIL": 0, "INDETERMINATE": len(poses.POSES),
                                                 "NOT_EXERCISED": 0}


def test_poses_leave_the_rest_report_unchanged(miki_runs):
    """--poses adds report["poses"] / ["pose_tables"] and the pose verdicts; every other byte is the default run's."""
    rest, posed, _t = miki_runs
    assert _strip(posed) == _strip(rest)
    assert set(posed) - set(rest) == {"poses", "pose_tables"}
    assert posed["summary"]["required_pass"] == rest["summary"]["required_pass"]


def test_posed_report_shape(miki_runs):
    _rest, posed, _t = miki_runs
    assert set(posed["poses"]) == set(poses.POSES)
    for name, spec in poses.POSES.items():
        per = posed["poses"][name]
        assert set(per) == {poses.angle_key(a) for a in spec.sweeps}
        for a in spec.sweeps:
            e = per[poses.angle_key(a)]
            assert [tuple(s) for s in e["steps"]] == list(poses.pose_steps(spec, a))
            assert e["evaluated"] > 0
            for c in e["changed"]:
                assert c["verdict"] != c["rest_verdict"]
                if c["kind"] == "join":
                    assert c["zone"] == "not tested in poses"
    json.loads(checks.dumps(posed))                                       # finite, serialisable


#: The first tested angle at which each cross pair of Miki FAILs (profile v6, poses.POSES), per pose and per sweep
#: direction ("+" first).  Information about the drawing reference's range, not a model defect: the pose
#: requirements are advisory until the user sets which poses must stay clean.  ``arms-inward`` is required (v5; v6:
#: at 5 / 10 / 11): it must stay empty.  ``arms-inward-far`` starts past the tested-clean range (v6: clean through
#: +13, the sleeve 2.8 mm off the blouse below the shoulder join there; at +15 it sinks into the blouse waist,
#: clear:limbs.sleeve_*^body.blouse/waist; from +20 the sleeves and cuffs meet the A-line skirt, from +25 the hands,
#: the under-skirt and the thighs).  v6: ``step`` keeps the legs in the bloomers block through +-15 (was -15 out),
#: ``knee-bend`` is clean (the split over-knee sock), and the back sheet no longer meets the narrower skirt in
#: ``head-turn``.  A change is deliberate: update this with the reason in the commit message.
MIKI_FIRST_FAILING = {
    "arms-forward": {},
    "arms-inward": {},
    "arms-inward-far": {
        "body.blouse|limbs.sleeve_l": ("+15",),
        "body.blouse|limbs.sleeve_r": ("+15",),
        "body.skirt|limbs.cuff_stripe_l0": ("+20",),
        "body.skirt|limbs.cuff_stripe_l1": ("+20",),
        "body.skirt|limbs.cuff_stripe_r0": ("+20",),
        "body.skirt|limbs.cuff_stripe_r1": ("+20",),
        "body.skirt|limbs.hand_l": ("+25",),
        "body.skirt|limbs.hand_r": ("+25",),
        "body.skirt|limbs.sleeve_l": ("+20",),
        "body.skirt|limbs.sleeve_r": ("+20",),
        "body.underskirt|limbs.cuff_stripe_l0": ("+25",),
        "body.underskirt|limbs.cuff_stripe_l1": ("+25",),
        "body.underskirt|limbs.cuff_stripe_r0": ("+25",),
        "body.underskirt|limbs.cuff_stripe_r1": ("+25",),
        "body.underskirt|limbs.sleeve_l": ("+25",),
        "body.underskirt|limbs.sleeve_r": ("+25",),
        "limbs.cuff_stripe_l1|limbs.leg_l": ("+25",),
        "limbs.cuff_stripe_r1|limbs.leg_r": ("+25",),
        "limbs.leg_l|limbs.sleeve_l": ("+25",),
        "limbs.leg_r|limbs.sleeve_r": ("+25",),
    },
    "arms-raised": {
        "body.collar|limbs.sleeve_l": ("+90",),
        "body.collar|limbs.sleeve_r": ("+90",),
    },
    "bow": {},
    "bow-head-turn": {
        "body.blouse|hair.back": ("+20",),
        "body.blouse|hair.sidelock_l": ("+20",),
        "body.collar_stripe|hair.back": ("+20",),
        "body.collar_stripe|hair.sidelock_l": ("+20",),
        "body.collar|hair.back": ("+20",),
        "body.collar|hair.sidelock_l": ("+20",),
        "body.scarf_ribbon_l|hair.sidelock_l": ("+20",),
        "hair.back|limbs.sleeve_r": ("+20",),
    },
    "head-nod": {
        "body.blouse|hair.back": ("-10",),
        "body.blouse|hair.sidelock_l": ("+15",),
        "body.blouse|hair.sidelock_r": ("+15",),
        "body.collar_stripe|hair.back": ("-10",),
        "body.collar|hair.back": ("-10",),
        "body.collar|hair.sidelock_l": ("+15",),
        "body.collar|hair.sidelock_r": ("+15",),
        "body.skirt|hair.back": ("-10",),
        "body.underskirt|hair.back": ("-10",),
        "hair.back|limbs.sleeve_l": ("-10",),
        "hair.back|limbs.sleeve_r": ("-10",),
    },
    "head-turn": {
        "body.blouse|hair.back": ("+10", "-10"),
        "body.blouse|hair.sidelock_l": ("+20",),
        "body.blouse|hair.sidelock_r": ("-20",),
        "body.collar_stripe|hair.back": ("+10", "-10"),
        "body.collar_stripe|hair.sidelock_l": ("+10",),
        "body.collar_stripe|hair.sidelock_r": ("-10",),
        "body.collar|hair.back": ("+10", "-10"),
        "body.collar|hair.sidelock_l": ("+10",),
        "body.collar|hair.sidelock_r": ("-10",),
        "body.scarf_ribbon_l|hair.sidelock_l": ("+10",),
        "body.scarf_ribbon_r|hair.sidelock_r": ("-10",),
        "hair.back|limbs.sleeve_l": ("-20",),
        "hair.back|limbs.sleeve_r": ("+20",),
        "hair.sidelock_l|limbs.sleeve_l": ("+30",),
        "hair.sidelock_r|limbs.sleeve_r": ("-30",),
    },
    "knee-bend": {},
    "step": {
        "body.underskirt|limbs.leg_l": ("+25", "-25"),
        "body.underskirt|limbs.leg_r": ("+25", "-25"),
    },
}


def test_miki_first_failing_angles_are_pinned(miki_runs):
    _rest, posed, _t = miki_runs
    got = {name: {pair: tuple(v) for pair, v in t["first_failing"].items()}
           for name, t in posed["pose_tables"].items()}
    assert got == MIKI_FIRST_FAILING
    assert all(not t["indeterminate"] for t in posed["pose_tables"].values())
    for e in posed["requirements"]:
        if e["kind"] == "pose":
            name = e["name"].split(":", 1)[1]
            want = checks.FAIL if MIKI_FIRST_FAILING[name] else checks.PASS
            assert e["verdict"] == want and e["level"] == poses.POSES[name].level, e["name"]
    req = next(e for e in posed["requirements"] if e["name"] == "pose:arms-inward")
    assert req["level"] == "required" and req["verdict"] == checks.PASS
    assert all(posed["poses"]["arms-inward"][a]["failing"] == [] for a in ("+5", "+10", "+11"))
    assert posed["summary"]["required_pass"] is True


def test_posed_run_time(miki_runs):
    """The posed checks (every pose, every angle) stay well inside a minute (milestone 2 note: > 60 s is reported,
    not hidden behind a slow mark)."""
    _rest, _posed, t = miki_runs
    assert t < 60.0, t
    assert math.isfinite(t)
