"""The overlay check of a character model against its design sheet (``tools/charmodel/overlay.py``), synthetic.

The real design sheet never enters the repository, so these tests make a sheet of their own: the Reiya model's
front view rendered orthographically into the sheet's pixel grid (``render_view``), painted with the class colours on
the sheet's light grid background.  Read back (flood fill, nearest-colour classes, ink fill), it must match the
model: every silhouette offset 0, the class IoUs about 1, every landmark on the spot.  The same sheet shifted by k
pixels must report offsets of k sheet pixels, i.e. k x 0.615 mm x the figure scale on the final model, within 0.1 mm.
The smoothness metrics are checked on spheres (with a wall in front: a hidden face's dihedral and a hidden outline
must not count; a sphere cut in two with the rims 0.1 mm apart has the outline of the whole one; a needle's apex is a
fold, not a tip), the criteria evaluator on a small report (a criterion with a missing measurement is n/a, not a
pass), and the command line's refusals (a character without overlay data, an output directory inside the repository)
without building a model.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from charmodel import meshkit as mk  # noqa: E402
from charmodel import overlay as ov  # noqa: E402
from reiya_model import assemble as asm  # noqa: E402
from reiya_model import overlay as rov  # noqa: E402
from reiya_model.rig import Rig  # noqa: E402

SPEC = rov.SPEC
VIEW = SPEC.sheet.view("front")
CANVAS = (2900, 2500)          # rows, columns: holds the front view's box (1480..2400, 80..2800)
GRID = 70                      # the sheet's grid pitch (px)


@pytest.fixture(scope="module")
def rig():
    return Rig()


@pytest.fixture(scope="module")
def render(rig):
    """The default model's front view in the sheet's pixel grid."""
    return ov.render_view(asm.assemble(rig), SPEC, VIEW, rig)


def _sheet(render, dx: int = 0, dy: int = 0) -> np.ndarray:
    """A synthetic sheet: grey 249 paper with 214 grid lines, the front render painted in the class colours at its
    box, shifted by (dx, dy) pixels."""
    rgb = np.full(CANVAS + (3,), 249, dtype=np.uint8)
    rgb[::GRID, :] = 214
    rgb[:, ::GRID] = 214
    painted = ov.paint_classes(render.cls, SPEC)
    x0, y0, x1, y1 = render.box
    m = render.cls >= 0
    sub = rgb[y0 + dy:y1 + dy, x0 + dx:x1 + dx]
    sub[m] = painted[m]
    return rgb


def _mm(rig) -> float:
    return SPEC.sheet.scale * rig.figure_scale * 1000.0


def test_mapping_puts_the_soles_on_the_ground_row_and_the_origin_column(render, rig):
    rows = np.nonzero((render.cls >= 0).any(axis=1))[0]
    assert rows.max() + render.box[1] == SPEC.sheet.ground_row - 1      # the last pixel row above z = 0
    cols = np.nonzero((render.cls >= 0).any(axis=0))[0] + render.box[0] + 0.5
    assert abs(0.5 * (cols.min() + cols.max()) - VIEW.origin_px) < 2.0   # she stands at x = 0
    assert 0.60 < _mm(rig) < 0.61


def test_the_model_as_its_own_sheet_reports_no_offsets(render, rig):
    read = ov.read_sheet(_sheet(render), SPEC, VIEW)
    assert np.array_equal(read.figure, render.figure)
    rep = ov.compare_view(read, render, SPEC, rig)
    for band, s in rep["silhouette"].items():
        if s["n"]:
            assert s["max"] == 0.0, band
    assert rep["iou"]["figure"] == 1.0
    for cls in ("hair", "skin", "white", "navy", "cardigan", "shoes", "socks"):
        assert rep["iou"][cls] >= 0.98, (cls, rep["iou"][cls])
    for name, o in rep["outlines"].items():
        for side in ("left", "right"):
            if side in o and o[side]["n"]:
                assert o[side]["max"] <= _mm(rig) + 1e-9, (name, side, o[side])
    for name, lm in rep["landmarks"].items():
        assert lm["sheet"] is not None and lm["model"] is not None, name
        assert lm["d_mm"] <= _mm(rig) + 1e-9, (name, lm)


@pytest.mark.parametrize("dx, dy", [(5, 0), (0, -3)])
def test_a_shifted_sheet_reports_the_shift_in_mm(render, rig, dx, dy):
    """The sheet moved right by dx (down by dy) pixels: the model's left edge sticks out by dx pixels and its right
    edge lies dx pixels inside; every landmark is -dx (dh) / +dy (dz) pixels off, in mm on the final model."""
    rep = ov.compare_view(ov.read_sheet(_sheet(render, dx, dy), SPEC, VIEW), render, SPEC, rig)
    k = _mm(rig)
    if dx:
        for band in ("hair", "skirt", "legs"):
            s = rep["silhouette"][band]
            assert abs(s["left"]["signed_mean"] - dx * k) < 0.1, (band, s["left"])
            assert abs(s["right"]["signed_mean"] + dx * k) < 0.1, (band, s["right"])
            assert s["width"]["max"] < 0.1
        for name in ("bob_widest_l", "bob_widest_r", "hem_width_l", "hand_out_r"):
            lm = rep["landmarks"][name]
            assert abs(lm["dh_mm"] + dx * k) < 0.1, (name, lm)
    if dy:
        for name in ("crown", "bang_line", "sole", "sock_cuff_l", "tuft_tip_r"):
            lm = rep["landmarks"][name]
            assert abs(lm["dz_mm"] - dy * k) < 0.1, (name, lm)
        for name in ("bob_tips", "fringe"):
            low = rep["lower_edges"][name]
            assert abs(low["signed_mean"] - dy * k) < 0.1, (name, low)
            assert low["max"] - low["mean"] < 0.1 and low["sheet_only_cols"] == low["model_only_cols"] == 0


def _camera(az: float = 30.0, height: float = 0.3):
    a = np.radians(az)
    return {"position": [2.0 * np.sin(a), -2.0 * np.cos(a), height], "target": [0.0, 0.0, 0.0], "roll_deg": 0.0,
            "focal_length_mm": 50.0, "frame_mm": [24.0, 36.0], "shift_mm": [0.0, 0.0], "near_m": 0.05}


def test_smoothness_tells_a_fine_sphere_from_a_coarse_one():
    fine = mk.ellipsoid((0.0, 0.0, 0.0), (0.1, 0.1, 0.1), nu=36, nv=18)
    coarse = mk.ellipsoid((0.0, 0.0, 0.0), (0.1, 0.1, 0.1), nu=8, nv=6)
    df, dc = ov.dihedral_stats(fine), ov.dihedral_stats(coarse)
    assert df["max"] < 15.0 < dc["max"]
    of, oc = ov.outline_turns(fine, _camera()), ov.outline_turns(coarse, _camera())
    assert of["tips"] == 0 and of["max"] < 15.0
    assert oc["max"] > 25.0
    assert of["outline_edges"] > oc["outline_edges"]


def _cube() -> mk.Mesh:
    V = [(x, y, z) for z in (0.0, 0.1) for y in (0.0, 0.1) for x in (0.0, 0.1)]
    F = [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [2, 6, 7, 3], [0, 4, 6, 2], [1, 3, 7, 5]]
    return mk.Mesh(V, F)


def test_group_boundaries_and_folds_are_not_facets():
    """A cube: with one group per face every edge is a designed line; with one group for all, every edge is a 90 deg
    fold (over the crease angle).  Either way only the six flat fan diagonals count, at 0 deg."""
    per_face = ov.dihedral_stats(_cube().with_groups([1, 2, 3, 4, 5, 6]))
    assert (per_face["edges"], per_face["max"], per_face["creases"]) == (6, 0.0, 0)
    one = ov.dihedral_stats(_cube().with_groups(1))
    assert (one["edges"], one["max"], one["creases"]) == (6, 0.0, 12)


def test_a_hidden_face_does_not_count():
    """Smoothness counts what a viewer sees: with a wall between the camera and a coarse sphere, none of the sphere's
    dihedrals and none of its outline edges count; without the wall only the faces seen from that camera count, and
    the whole outline does."""
    sphere = mk.ellipsoid((0.0, 0.0, 0.0), (0.1, 0.1, 0.1), nu=8, nv=6)
    V = np.asarray(_cube().vertices) * [6.0, 1.0, 6.0] + [-0.3, -0.6, -0.3]
    wall = mk.Mesh(V, _cube().faces)
    cam = _camera(0.0)
    T = sphere.n_triangles
    own = np.zeros(T + wall.n_triangles, dtype=bool)
    own[:T] = True
    hidden = ov.front_view([sphere, wall], cam, 400)
    assert not hidden.visible()[:T].any()
    d = ov.dihedral_stats(sphere, tri_visible=[hidden.visible()[:T]])
    assert d["edges"] == 0 and d["max"] is None and d["hidden_edges"] > 0
    o = ov.outline_turns(sphere, cam, 400, front=hidden, own=own)
    assert o["outline_edges"] == 0 and o["hidden_edges"] > 0 and o["max"] is None
    seen = ov.front_view([sphere], cam, 400)
    vis = seen.visible()
    assert 0 < vis.sum() < T                       # the near half
    d_all, d_seen = ov.dihedral_stats(sphere), ov.dihedral_stats(sphere, tri_visible=[vis])
    assert 0 < d_seen["edges"] < d_all["edges"] and d_seen["hidden_edges"] == d_all["edges"] - d_seen["edges"]
    plain = ov.outline_turns(sphere, cam, 400)
    o2 = ov.outline_turns(sphere, cam, 400, front=seen, own=own[:T])
    assert o2["hidden_edges"] == 0 and o2["outline_edges"] == plain["outline_edges"] and o2["max"] == plain["max"]


def test_criteria_reduce_their_values():
    report = {"views": {"front": {"a": {"x": 2.0, "y": -5.0}}, "back": {"a": {"x": 4.0, "y": 1.0, "z": None}}}}
    crit = (ov.Criterion("c1", "max", ("views.*.a.x",), "<=", 3.0),
            ov.Criterion("c2", "abs", ("views.front.a.y",), "abs<=", 5.0),
            ov.Criterion("c3", "range", ("views.*.a.*",), "between", (-6.0, 4.0)),
            ov.Criterion("c4", "missing", ("views.side.a.x",), ">=", 1.0),
            ov.Criterion("c5", "one of two keys missing", ("views.front.a.x", "views.side.a.x"), "<=", 3.0),
            ov.Criterion("c6", "a landmark that is None", ("views.front.a.x", "views.back.a.z"), "<=", 3.0),
            ov.Criterion("c7", "a wildcard with no value", ("views.*.a.z", "views.*.a.x"), "<=", 4.0),
            ov.Criterion("c8", "a wildcard over fewer levels", ("views.*.a.y", "views.*.a.z"), ">=", -5.0))
    res = {c["id"]: c for c in ov.evaluate_criteria(report, crit)}
    assert (res["c1"]["value"], res["c1"]["pass"]) == (4.0, False)
    assert res["c2"]["pass"] is True
    assert res["c3"]["value"] == [-5.0, 4.0] and res["c3"]["pass"] is True
    assert res["c4"]["pass"] is None and res["c4"]["value"] is None and res["c4"]["missing"] == ["views.side.a.x"]
    # a measurement that is gone does not pass on the rest: n/a, with the missing keys recorded (and the value kept)
    assert res["c5"]["pass"] is None and res["c5"]["value"] == 2.0 and res["c5"]["missing"] == ["views.side.a.x"]
    assert res["c6"]["pass"] is None and res["c6"]["missing"] == ["views.back.a.z"]
    # a key with a `*` that matches nothing is recorded, but only a key without one makes the criterion n/a
    assert res["c7"]["pass"] is True and res["c7"]["missing"] == ["views.*.a.z"] and res["c7"]["value"] == 4.0
    assert res["c8"]["pass"] is True and res["c8"]["missing"] == ["views.*.a.z"] and res["c8"]["value"] == -5.0
    assert res["c1"]["missing"] == res["c2"]["missing"] == res["c3"]["missing"] == []


def test_the_report_counts_only_passes_and_names_the_missing_keys(tmp_path):
    crit = (ov.Criterion("c1", "ok", ("a",), ">=", 1.0), ov.Criterion("c2", "bad", ("a",), "<=", 0.5),
            ov.Criterion("c3", "gone", ("a", "b.c"), ">=", 1.0))
    res = ov.evaluate_criteria({"a": 2.0}, crit)
    assert [c["pass"] for c in res] == [True, False, None]
    assert ov.criteria_summary(res) == "1 of 3 pass; n/a: c3; failing: c2"       # what the command prints
    assert ov.criteria_summary(res[:1]) == "1 of 1 pass" and ov.criteria_summary(res[2:]) == "0 of 1 pass; n/a: c3"
    _, md = ov.write_report({"criteria": res, "views": {}}, str(tmp_path), "t")
    text = pathlib.Path(md).read_text(encoding="utf-8")
    assert "## Pass criteria: 1 of 3 pass" in text
    assert "| c1 | ok | 2.00 | >= 1.0 | PASS |" in text and "| c2 | bad | 2.00 | <= 0.5 | FAIL |" in text
    assert "| c3 | gone | 2.00 | >= 1.0 | n/a (no value at `b.c`) |" in text


def _halves(mesh, axis, gap):
    """``mesh`` cut by the plane through the origin normal to ``axis``: its faces on the positive side, and the rest
    moved ``gap`` against ``axis``: two open shells whose rims lie ``gap`` apart (the cut of a split shell)."""
    V = mesh.vertices
    ax = np.asarray(axis, dtype=np.float64) / np.linalg.norm(axis)
    up = [f for f in mesh.faces if V[f].mean(axis=0) @ ax > 0]
    lo = [f for f in mesh.faces if V[f].mean(axis=0) @ ax <= 0]

    def shell(faces, offset):
        used = sorted({i for f in faces for i in f})
        index = {i: k for k, i in enumerate(used)}
        return mk.Mesh(V[used] + offset, [[index[i] for i in f] for f in faces])

    return shell(up, 0.0), shell(lo, -gap * ax)


def test_a_sphere_cut_in_two_has_the_outline_of_the_whole_sphere():
    """The two rims of a cut (0.1 mm apart, a hundredth of a pixel) lie on the silhouette where the cut meets it.
    Left alone they are open-boundary edges of their own: the outline runs through both and kinks (25-29 deg on a
    sphere whose whole outline never turns more than 11 deg) or ends in tips.  Merged, they are one seam that is an
    outline edge only where the two sides face opposite ways, exactly as in the welded sphere."""
    sphere = mk.ellipsoid((0.0, 0.0, 0.0), (0.1, 0.1, 0.1), nu=36, nv=18)
    cam = _camera(30.0, 0.75)
    whole = ov.outline_turns(sphere, cam, 400)
    assert whole["tips"] == whole["folds"] == whole["merged_edges"] == 0 and whole["max"] < 11.0
    for axis in ((0.0, 0.0, 1.0), (1.0, 1.0, 0.0)):
        a, b = _halves(sphere, axis, 1e-4)
        both = mk.merge(a, b)
        raw = ov.outline_turns(both, cam, 400, merge_px=0.0, fold_deg=180.0)       # no merging: the old behaviour
        assert raw["max"] > 20.0 and raw["outline_edges"] > whole["outline_edges"], axis
        fixed = ov.outline_turns(both, cam, 400)
        assert fixed["merged_edges"] > 0, axis
        assert fixed["outline_edges"] == whole["outline_edges"], axis
        assert fixed["tips"] == fixed["folds"] == 0, axis
        assert fixed["max"] == pytest.approx(whole["max"], abs=0.1) and fixed["p95"] == pytest.approx(whole["p95"],
                                                                                                     abs=0.1), axis


def test_coincident_outlines_merge_only_where_they_coincide_in_space():
    """A sphere 0.5 mm inside another one has the same silhouette 0.14 px away: one outline.  A sphere twice as far
    and twice as large (the same rays: the camera's homothety) projects onto exactly the same pixels but is another
    surface on the same line of sight: not merged, so the outline keeps both."""
    outer = mk.ellipsoid((0.0, 0.0, 0.0), (0.1, 0.1, 0.1), nu=36, nv=18)
    cam = _camera(30.0, 0.3)
    one = ov.outline_turns(outer, cam, 400)
    nested = mk.merge(outer, mk.ellipsoid((0.0, 0.0, 0.0), (0.0995, 0.0995, 0.0995), nu=36, nv=18))
    two = ov.outline_turns(nested, cam, 400)
    assert two["merged_edges"] > 0 and two["outline_edges"] == one["outline_edges"]
    assert two["max"] == pytest.approx(one["max"], abs=0.1)
    eye = np.asarray(cam["position"])
    behind = mk.Mesh(eye + 2.0 * (outer.vertices - eye), outer.faces)
    both = ov.outline_turns(mk.merge(outer, behind), cam, 400)
    assert both["merged_edges"] == 0 and both["outline_edges"] == 2 * one["outline_edges"]


def test_a_chain_that_doubles_back_is_a_fold_not_a_tip():
    """A needle seen from the side: its apex turns 176 deg, the chain doubles back on itself.  Folds are artefacts of
    the projection (a thin wall edge-on, a spike under ~10 deg), counted apart: not tips, not turns."""
    def ring(z, r):
        t = np.linspace(0.0, 2.0 * np.pi, 12, endpoint=False)
        return np.stack([r * np.cos(t), r * np.sin(t), np.full(12, z)], axis=1)

    needle = mk.loft([ring(-0.1, 0.0075), ring(-0.05, 0.0055)], "flat", ("pole", (0.0, 0.0, 0.1)))
    cam = _camera(30.0, 0.3)
    as_tip = ov.outline_turns(needle, cam, 400, fold_deg=180.0)
    assert (as_tip["tips"], as_tip["folds"]) == (1, 0)
    fold = ov.outline_turns(needle, cam, 400)
    assert (fold["tips"], fold["folds"]) == (0, 1)
    assert fold["turn_vertices"] == as_tip["turn_vertices"] - 1 and fold["max"] == as_tip["max"]


def _run(script: str, *args: str):
    return subprocess.run([sys.executable, str(TOOLS / script), *args], capture_output=True, text=True, timeout=120)


def test_a_character_without_overlay_data_is_a_usage_error():
    res = _run("make_miki_model.py", "--overlay", "x", "y")
    assert res.returncode == 2
    assert "has no overlay data" in res.stderr


def test_the_overlay_never_writes_into_the_repository():
    res = _run("make_reiya_model.py", "--overlay", "sheet.png", str(ROOT / "examples" / "overlay"))
    assert res.returncode == 2
    assert "inside the repository" in res.stderr
    assert not (ROOT / "examples" / "overlay").exists()
    with pytest.raises(ValueError, match="inside the repository"):
        ov.run_overlay(None, None, SPEC, "sheet.png", str(ROOT / "examples" / "overlay"), repo=str(ROOT))
