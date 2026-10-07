"""Regression tests of the spec §8 performance pass (benchmarks/bench.py and the batched kernels).

The benchmark itself is not part of the suite (its timings depend on the machine); these
tests pin down what the performance work must not change: the benchmark script runs and
reports its gate, the bulk number formatting of the SVG writer equals the scalar
:func:`_f` on every kind of value, the SVG writer only uses NumPy APIs that exist in the
declared ``numpy>=1.24`` floor, the byte-string element assembly equals the scalar element
writers, the compressed polygon conversion equals the scalar drawing pipeline, the
per-light ray / check lists equal the per-record ones, and the lists a document shares
with the cached stage A are canonical and never mutated by a second render.
"""

import json
import math
import pathlib
import re
import sys

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import castplane
from castplane import pipeline as P
from castplane.camera import camera_matrix
from castplane.construction import clip_segments_uv, covering_segments
from castplane.homogeneous import scene_scale, tolerance
from castplane.output import svg as svg_mod
from castplane.output.geometry_json import dumps
from castplane.output.svg import _Canvas, _chunk, _f, _fmt_bytes, _fmt_many, write_svg
from castplane.scene import load_scene
from tests.reference import random_scenes

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "benchmarks") not in sys.path:
    sys.path.insert(0, str(ROOT / "benchmarks"))
import bench  # noqa: E402  (benchmarks/bench.py)


# ---------------------------------------------------------------------------
# benchmark script
# ---------------------------------------------------------------------------

def test_bench_runs_and_reports_gate(capsys):
    status = bench.main(["--objects", "6", "-n", "1", "--json", "--gate", "none"])
    out = json.loads(capsys.readouterr().out)
    assert status == 0 and out["gate"] == "none"
    assert out["objects"] == 6 and out["mesh_edges"] > 0 and out["document_edges"] > 0
    for key in ("full_render_s", "camera_only_s", "camera_only_no_gc_s", "stage_a_s", "svg_s", "json_s"):
        assert out[key]["min"] > 0.0 and out[key]["median"] >= out[key]["min"]
    assert out["full_render_s"]["target"] == bench.TARGET_FULL_S
    assert out["camera_only_s"]["target"] == bench.TARGET_CAMERA_S
    assert set(out["pass"]) == {"full_render", "camera_only"}


def test_bench_text_output_names_the_gate(capsys):
    status = bench.main(["--objects", "4", "-n", "1", "--gate", "full"])
    text = capsys.readouterr().out
    assert "RESULT:" in text and "(gate: full)" in text
    assert "cyclic GC disabled" in text
    assert status in (0, 1)


@pytest.mark.parametrize("ok_full, ok_cam, gate, expected", [
    (True, True, "both", 0), (True, False, "both", 1), (False, True, "both", 1),
    (True, False, "full", 0), (False, True, "full", 1), (False, False, "none", 0),
])
def test_exit_status_follows_gate(ok_full, ok_cam, gate, expected):
    assert bench.exit_status(ok_full, ok_cam, gate) == expected


def test_exit_status_rejects_unknown_gate():
    with pytest.raises(ValueError):
        bench.exit_status(True, True, "camera")


# ---------------------------------------------------------------------------
# SVG number formatting (bulk == scalar) and the NumPy 1.x API floor
# ---------------------------------------------------------------------------

def _special_values():
    halves = [k / 2e4 for k in range(-25, 26)]                      # exact 4-decimal half-ways
    near = [v + d for v in halves for d in (-1e-9, 1e-9, -1e-13, 1e-13)]
    big = [1e6, -1e6, 123456.78915, 2.0 ** 31 / 1e4, 2.0 ** 31 / 1e4 + 1.0, 1e15, -1e15, 1e20]
    odd = [0.0, -0.0, 5e-5, -5e-5, 4.99995e-5, 0.00005, 0.00015, 0.99995, -0.99995, 999.99995,
           math.nan, math.inf, -math.inf, 1e-300, -1e-300]
    return halves + near + big + odd


def test_fmt_bytes_equals_scalar_f_on_special_values():
    values = _special_values()
    assert _fmt_many(values) == [_f(v) for v in values]
    assert [b.decode() for b in _fmt_bytes(values).tolist()] == [_f(v) for v in values]
    assert _fmt_many([]) == [] and _fmt_bytes([]).shape == (0,)


@settings(max_examples=200, deadline=None)
@given(st.lists(st.floats(allow_nan=True, allow_infinity=True, width=64), min_size=1, max_size=300))
def test_fmt_many_equals_scalar_f_property(values):
    assert _fmt_many(values) == [_f(v) for v in values]


def test_fmt_many_random_bulk():
    rng = np.random.default_rng(20261006)
    x = np.concatenate([rng.uniform(-500, 500, 20000), rng.uniform(-5e5, 5e5, 2000),
                        rng.normal(0, 1e-3, 2000), np.round(rng.uniform(-100, 100, 2000), 4)])
    assert _fmt_many(x) == [_f(v) for v in x.tolist()]


def test_svg_writer_uses_only_numpy_1x_string_apis():
    """pyproject declares ``numpy>=1.24``; ``numpy.strings`` exists only in NumPy >= 2.0 and
    ``np.char`` in both, so the library must not reference ``np.strings`` anywhere."""
    pattern = re.compile(r"\bnp\.strings\b|numpy\.strings\b")
    offenders = [p for p in (ROOT / "castplane").rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
    assert hasattr(np.char, "add")


# ---------------------------------------------------------------------------
# byte-string element assembly == scalar element writers
# ---------------------------------------------------------------------------

def _rng_points(rng, n):
    return rng.uniform(-300, 400, (n, 2)).tolist()


def test_lines_polygons_paths_equal_scalar_writers():
    rng = np.random.default_rng(7)
    cv = _Canvas(273.0, 182.0)
    segments = [[p, q] for p, q in zip(_rng_points(rng, 500), _rng_points(rng, 500))]
    lines = cv.lines(segments)
    assert lines.shape == (500,) and lines.dtype.kind == "S"
    assert _chunk(lines) == ["\n".join(cv.line(a, b) for a, b in segments)]
    mask = rng.uniform(size=500) < 0.3
    assert _chunk(lines[mask]) == ["\n".join(cv.line(a, b) for (a, b), m in zip(segments, mask) if m)]
    assert _chunk(lines[:0]) == [] and cv.lines([]).shape == (0,)
    polys = [_rng_points(rng, int(k)) for k in rng.integers(3, 12, 60)]
    records, offsets = cv.polygons(polys)
    assert offsets.tolist() == np.concatenate([[0], np.cumsum([len(p) for p in polys])]).tolist()
    assert _chunk(records) == ["\n".join(cv.polygon(p) for p in polys)]
    a, b = int(offsets[10]), int(offsets[25])
    assert _chunk(records[a:b]) == ["\n".join(cv.polygon(p) for p in polys[10:25])]
    entries = [[_rng_points(rng, int(k)) for k in rng.integers(3, 9, int(m))] for m in rng.integers(0, 4, 40)]
    paths = cv.paths(entries)
    assert len(paths) == len(entries)
    for entry, path in zip(entries, paths):
        if entry:
            assert path == cv.path(entry)
    assert cv.pairs(polys[0]) == [f"{_f(u + 136.5)},{_f(91.0 - v)}" for u, v in polys[0]]


def test_texts_scalar_offsets_and_attrs():
    cv = _Canvas(100.0, 80.0)
    pts = [[1.0, 2.0], [-3.5, 4.25], [10.0, -10.0]]
    labels = ["a.v0", "b<c", "d&e"]
    assert cv.texts(pts, labels, None, 0.8, -0.8) == [cv.text(p, s) for p, s in zip(pts, labels)]
    assert cv.texts(pts, labels, ['x="1"'] * 3, 1.4, 2.4) == [cv.text(p, s, 'x="1"', dx=1.4, dy=2.4)
                                                             for p, s in zip(pts, labels)]
    assert cv.texts([], [], None, 0.0, 0.0) == []


# ---------------------------------------------------------------------------
# batched stage-B kernels == scalar kernels
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def basic_cam():
    scene = load_scene(ROOT / "examples" / "basic.json")
    cam = camera_matrix(scene["camera"], scene["output"]["canvas_mm"])
    return scene, cam


def test_project_polygons_compressed_rows_equal_scalar(basic_cam):
    scene, cam = basic_cam
    rng = np.random.default_rng(3)
    polys = []
    for _ in range(300):
        n = int(rng.integers(1, 40))
        p = np.ones((n, 4))
        p[:, :3] = rng.uniform(-6, 6, (n, 3)) + np.array([0.0, 3.0, 0.5])
        if rng.uniform() < 0.3:                       # a few direction vertices (unbounded shadows)
            k = int(rng.integers(0, n))
            p[k] = [rng.normal(), rng.normal(), 0.0, 0.0]
        polys.append(p)
    pts, lens = P._pad_polygons(polys)
    batched = P._project_polygons(cam, pts, lens)
    for p, poly in zip(polys, batched):
        expected = (P._project_polygon(cam, p) + 0.0).tolist()
        assert poly == expected


def test_project_shadows_batched_equals_per_record(basic_cam):
    scene, cam = basic_cam
    A = castplane.shadow_geometry(scene)
    tol = tolerance(scene_scale(A["vertices"], cam["C"]))
    lights = [P._project_light(lt, cam, tol)[0] for lt in A["lights"]]
    by_id = {lt["id"]: lt for lt in lights}
    recs = list(A["shadows"])
    empty = dict(recs[0], object="ghost", vertex_ids=np.zeros(0, dtype=np.int64), keep=np.zeros(0, dtype=bool),
                 P_world=np.zeros((0, 3)), S_world=np.zeros((0, 3)), Q_world=np.zeros((0, 3)), w_S=np.zeros(0),
                 shadow_names=[], foot_names=[], vertex_names=[], ground_points=[], loops=[], unbounded=False,
                 S_lists=[], Q_lists=[], G_world=np.zeros((0, 3)), G_lists=[],
                 ray_vertices=np.zeros(0, dtype=bool))             # M5 §5.2.4 record key, aligned with keep
    for order in ([empty] + recs, recs + [empty], [recs[0], empty] + recs[1:]):
        out, warnings = P._project_shadows(order, cam, tol, by_id)
        assert len(out) == len(order)
        for rec, o in zip(order, out):
            single, w1 = P._project_shadow(rec, cam, tol, lights[0])
            assert o["rays"] == single["rays"]
            assert o["checks"] == single["checks"]
            assert json.dumps(o["segments"]) == json.dumps(single["segments"])
            assert [p for p in o["polygons"]] == [p for p in single["polygons"]]


def test_covering_segments_and_clip_segments_uv_reference():
    rng = np.random.default_rng(11)
    n = 400
    A = rng.uniform(-50, 50, 2)
    B = rng.uniform(-50, 50, (n, 2))
    C = rng.uniform(-50, 50, (n, 2))
    C[:5] = B[:5]                                                   # degenerate rows: B == C
    seg = covering_segments(A, B, C)
    assert seg.shape == (n, 2, 2)
    for k in range(n):
        d = C[k] - B[k] if np.max(np.abs(C[k] - B[k])) > 1e-12 * max(1.0, np.max(np.abs(B[k]))) else A - B[k]
        d = d / np.linalg.norm(d)
        t = [float((A - B[k]) @ d), 0.0, float((C[k] - B[k]) @ d)]
        lo, hi = min(t), max(t)
        assert np.allclose(seg[k, 0], B[k] + lo * d, atol=1e-9) and np.allclose(seg[k, 1], B[k] + hi * d, atol=1e-9)
        # the three points lie on the segment
        for p in (A, B[k], C[k]):
            s = float((p - seg[k, 0]) @ d)
            assert -1e-9 <= s <= hi - lo + 1e-9
    rect = (-170.0, 170.0, -115.0, 115.0)
    segs = np.concatenate([seg, np.stack([B, B], axis=1)], axis=0)  # plus zero-length segments
    out, keep = clip_segments_uv(segs, rect)
    assert out.shape == (2 * n, 2, 2) and not keep[n:].any()
    inside = (out[:n][..., 0] >= rect[0] - 1e-9) & (out[:n][..., 0] <= rect[1] + 1e-9) & \
        (out[:n][..., 1] >= rect[2] - 1e-9) & (out[:n][..., 1] <= rect[3] + 1e-9)
    assert inside[keep[:n]].all()


# ---------------------------------------------------------------------------
# documents from a cached stage A: shared camera-free lists stay canonical and unchanged
# ---------------------------------------------------------------------------

def test_cached_stage_a_documents_are_stable_and_serialisable():
    scene = load_scene(random_scenes.make_benchmark_scene(12, include_curved=True))
    A = castplane.shadow_geometry(scene)
    other = dict(scene["camera"], position=[6.0, -28.0, 12.0], target=[0.0, 0.0, 0.5], roll_deg=3.0)
    doc1 = castplane.compose(scene, castplane.project_scene(scene, A, camera=other))
    text1 = dumps(doc1)
    svg1 = write_svg(doc1, layers=scene["output"]["layers"])
    # a second camera and a second render from the same stage A leave the first document unchanged
    doc_other = castplane.compose(scene, castplane.project_scene(scene, A))
    doc2 = castplane.compose(scene, castplane.project_scene(scene, A, camera=other))
    assert dumps(doc1) == text1 == dumps(doc2)
    assert write_svg(doc1, layers=scene["output"]["layers"]) == svg1
    assert dumps(doc_other) != text1
    # every shared list is a plain, canonical list of Python floats (no numpy, no -0.0)
    for name, p in doc1["points"].items():
        for key in ("world", "direction"):
            if key in p:
                assert type(p[key]) is list and all(type(v) is float for v in p[key])
                assert all(not (v == 0.0 and math.copysign(1.0, v) < 0) for v in p[key])
    for e in doc1["edges"]:
        # contract §5.0.3 (M4): every edge carries runs (empty with hidden lines off)
        assert set(e) == {"object", "from", "to", "silhouette", "back", "visibility", "segment", "runs"}
    # the documents are independent of each other where the camera matters
    e1 = next(e for e in doc1["edges"] if e["segment"] is not None)
    e1["segment"][0][0] += 1.0
    assert dumps(doc2) == text1
    # and the same scene through render() equals the cached path
    assert dumps(castplane.render(scene, camera=other)["geometry"]) == text1


def test_svg_module_exports():
    assert svg_mod.LAYER_ORDER == ("horizon", "objects", "form_shadow", "cast_shadow", "construction", "labels")
    assert callable(svg_mod._fmt_many) and callable(svg_mod._fmt_bytes)


# ---------------------------------------------------------------------------
# the committed benchmark scene file (contract §5.4.9 lock rule, §5.0.9)
# ---------------------------------------------------------------------------

def _mesh_edge_signature(raw: dict) -> tuple:
    scene = load_scene(raw)
    return (len(scene["objects"]), [o["type"] for o in scene["objects"]], random_scenes.count_edges(raw))


def test_benchmark_scene_file_matches_generator():
    """``benchmarks/scenes/benchmark_100.json`` is ``make_benchmark_scene()`` written by
    ``benchmarks/export_scene.py``.  Byte equality is required only when the running NumPy version
    equals the recorded one (the ``Generator`` bit stream is not frozen across NumPy releases, NEP 19);
    otherwise the committed file and the fresh scene must both load and have the same object count,
    types and mesh edge count (the spec §8 size)."""
    import export_scene  # benchmarks/export_scene.py

    scene_file = ROOT / "benchmarks" / "scenes" / "benchmark_100.json"
    build = json.loads((ROOT / "benchmarks" / "scenes" / "benchmark_100.build.json").read_text(encoding="utf-8"))
    assert set(build) == {"python", "numpy"} and all(isinstance(v, str) and v for v in build.values())
    assert export_scene.SCENE_FILE == scene_file
    text = scene_file.read_text(encoding="utf-8")
    committed = json.loads(text)
    assert text == json.dumps(committed, sort_keys=True, indent=1) + "\n"       # the exporter's canonical form
    fresh = random_scenes.make_benchmark_scene()
    if build["numpy"] == np.__version__:
        assert text == export_scene.scene_text(fresh), "benchmark_100.json drifted from make_benchmark_scene()"
    assert _mesh_edge_signature(committed) == _mesh_edge_signature(fresh)
    n_objects, _, n_edges = _mesh_edge_signature(committed)
    assert n_objects == 100 and 10_000 <= n_edges <= 11_000


def test_bench_default_input_is_the_committed_file():
    """Under its default arguments ``bench.py`` measures the committed file (the same bytes as the
    TypeScript benchmark); the ``--objects`` / ``--no-curved`` variants are generated."""
    raw, source = bench.benchmark_input()
    assert source == "benchmarks/scenes/benchmark_100.json" and bench.SCENE_FILE.name == "benchmark_100.json"
    assert raw == json.loads(bench.SCENE_FILE.read_text(encoding="utf-8"))
    raw6, source6 = bench.benchmark_input(6)
    assert source6.startswith("make_benchmark_scene(6") and raw6 == random_scenes.make_benchmark_scene(6)
    raw_nc, _ = bench.benchmark_input(100, no_curved=True)
    assert raw_nc == random_scenes.make_benchmark_scene(100, include_curved=False)


# ---------------------------------------------------------------------------
# M4 (contract §5.1.6.6, §5.0.9): the --hidden-lines row and the before / after switch-off rows
# ---------------------------------------------------------------------------

def test_bench_hidden_lines_row(capsys):
    status = bench.main(["--objects", "4", "-n", "1", "--json", "--gate", "none", "--hidden-lines"])
    out = json.loads(capsys.readouterr().out)
    assert status == 0
    hl = out["hidden_lines_full_render_s"]
    assert hl["min"] > 0.0 and hl["median"] >= hl["min"] and hl["target"] == bench.SOFT_TARGET_HIDDEN_S == 5.0
    assert isinstance(hl["soft_pass"], bool)
    assert out["hidden_lines_json_bytes"] > out["json_bytes"] and out["hidden_lines_svg_bytes"] > 0
    assert set(out["pass"]) == {"full_render", "camera_only"}          # the row is never gated
    bench.main(["--objects", "4", "-n", "1", "--gate", "none", "--hidden-lines"])
    assert "full render, hidden lines on" in capsys.readouterr().out
    bench.main(["--objects", "4", "-n", "1", "--json", "--gate", "none"])
    assert "hidden_lines_full_render_s" not in json.loads(capsys.readouterr().out)


def test_bench_readme_records_the_m4_rows():
    text = (ROOT / "benchmarks" / "README.md").read_text(encoding="utf-8")
    section = text.split("## M4", 1)[1]
    assert "--hidden-lines" in section and "full render, hidden lines on" in section
    assert "before M4" in section and "after M4" in section and "JSON bytes" in section
    assert "--gate full" in section


# M5: the --scene mesh10k benchmark (contract §5.2.7, §5.0.9)
# ---------------------------------------------------------------------------

def test_mesh10k_scene_is_10000_unwelded_triangles_that_weld_to_a_closed_torus():
    from castplane.primitives import prepared_mesh

    raw = bench.mesh10k_scene()
    (obj,) = raw["objects"]
    assert len(obj["data"]["faces"]) == 10000 and len(obj["data"]["vertices"]) == 30000
    assert bench.mesh10k_scene() == raw                                   # deterministic
    prep = prepared_mesh(load_scene(raw)["objects"][0])
    assert prep["fallback"] is False and prep["warnings"] == []
    assert prep["mesh"]["vertices"].shape[0] == 5000                     # the weld joins the 30 000 corners


def test_bench_mesh10k_reports_the_mesh_preprocessing_row(capsys):
    status = bench.main(["--scene", "mesh10k", "-n", "1", "--json", "--gate", "none"])
    out = json.loads(capsys.readouterr().out)
    assert status == 0 and out["scene"] == "mesh10k" and out["objects"] == 1 and out["warnings"] == []
    assert out["mesh_preprocessing_s"]["min"] > 0.0 and out["stage_a_s"]["min"] > 0.0


# M6: --lights N, --no-umbra and the 2 000-edge record_pieces row (contract §5.3.9, §5.0.9)
# ---------------------------------------------------------------------------

def test_with_lights_mirrors_the_benchmark_light_about_the_scene_centre():
    raw, _source = bench.benchmark_input()
    assert bench.with_lights(raw, 1) is raw                                  # the gated input, unchanged
    two, three = bench.with_lights(raw, 2), bench.with_lights(raw, 3)
    first = raw["lights"][0]
    assert [lt["id"] for lt in three["lights"]] == [first["id"], f"{first['id']}_mx", f"{first['id']}_my"]
    assert two["lights"] == three["lights"][:2] and raw["lights"] == [first]  # raw is not mutated
    pos = [o["transform"]["position"] for o in raw["objects"]]
    cx = (min(p[0] for p in pos) + max(p[0] for p in pos)) / 2
    cy = (min(p[1] for p in pos) + max(p[1] for p in pos)) / 2
    mx, my = three["lights"][1]["position"], three["lights"][2]["position"]
    assert mx[0] == pytest.approx(2 * cx - first["position"][0]) and mx[1:] == first["position"][1:]
    assert my[1] == pytest.approx(2 * cy - first["position"][1]) and [my[0], my[2]] == [first["position"][0],
                                                                                         first["position"][2]]
    assert len(load_scene(three)["lights"]) == 3
    with pytest.raises(ValueError):
        bench.with_lights(raw, 4)


def test_bench_lights_rows_report_the_umbra_share(capsys):
    status = bench.main(["--objects", "4", "-n", "1", "--json", "--gate", "none", "--lights", "2"])
    out = json.loads(capsys.readouterr().out)
    assert status == 0 and out["lights"] == 2 and out["umbra"] is True
    assert out["umbra_s"]["min"] > 0.0 and 0.0 < out["umbra_s"]["share_of_camera_only"]
    assert sorted(out["record_pieces"]) == ["lamp", "lamp_mx"] and out["umbra_pieces"] > 0
    loop = out["record_pieces_2000_s"]
    assert loop["edges"] == 2000 and loop["pieces"] > 0 and loop["min"] > 0.0
    assert set(out["pass"]) == {"full_render", "camera_only"}                # the M6 rows are never gated
    bench.main(["--objects", "4", "-n", "1", "--gate", "none", "--lights", "3", "--no-umbra"])
    text = capsys.readouterr().out
    assert "with 3 lights" in text and "umbra alone" in text and "umbra share of camera-only" in text
    assert "WITHOUT the umbra" in text and "2000-edge loop" in text
    bench.main(["--objects", "4", "-n", "1", "--json", "--gate", "none"])
    one = json.loads(capsys.readouterr().out)
    assert one["lights"] == 1 and "umbra_s" not in one and "record_pieces_2000_s" not in one


def test_bench_readme_records_the_m6_rows():
    text = (ROOT / "benchmarks" / "README.md").read_text(encoding="utf-8")
    section = text.split("## M6", 1)[1]
    for needle in ("--lights 2", "--lights 3", "--no-umbra", "umbra alone", "record_pieces", "2000-edge",
                   "--gate full", "N = 1"):
        assert needle in section, needle
