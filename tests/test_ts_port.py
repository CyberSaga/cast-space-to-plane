"""Python-side checks of the files shared with the TypeScript port (contract §5.4.13, §5.4.5, §5.4.8).

They run in the Python job without node.  The checks that read ``ts/`` are skipped while the port is
absent (M7 phase 1 adds ``ts/`` on its own branch); the others guard the shared contract files now:

* ``tests/conformance/rules.json`` equals the comparator constants of ``tests/test_conformance.py``
  (incl. ``drawable_containers``) -- the TypeScript runner reads the file, the Python runner its
  constants, so the two can never drift apart;
* every integer-valued leaf of every expected file sits under a key of ``rules.json["int_keys"]``
  (the writer's ``INT_KEYS``: JavaScript has one number type, so the port writes an integer only
  under these keys), and with ``ts/`` present ``INT_KEYS`` of ``ts/src/output/geometry_json.ts``
  equals that list;
* with ``ts/`` present: ``ts/package.json`` version == ``castplane.__version__`` ==
  ``ts/src/index.ts``'s ``__version__``, and no file under ``ts/src/`` touches node-only APIs.

The ``benchmarks/scenes/benchmark_100.json`` lock rule lives in ``tests/test_bench.py``.

When ``node`` is on the PATH the TypeScript runner is exercised from here as well (rebuilt first when the
workspace's ``typescript`` is installed, ``npm ci``): the port's ``node:test`` suite, the conformance runner of
§5.4.8 included, must pass; the port's SVG of every example must equal the Python writer's text and its JSON
document must pass the comparator; the benchmark's ``--json`` record carries the ``bench.py`` field names.
Without node (or without a built port) those tests are skipped; the ``ts`` CI job runs the suite anyway.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest

import castplane
from tests import test_conformance as tc

ROOT = pathlib.Path(__file__).resolve().parents[1]
TS = ROOT / "ts"
EXPECTED = ROOT / "tests" / "conformance" / "expected"
RULES = json.loads((ROOT / "tests" / "conformance" / "rules.json").read_text(encoding="utf-8"))

needs_ts = pytest.mark.skipif(not (TS / "package.json").exists(),
                              reason="ts/ is absent (the TypeScript port is added by M7 phase 1)")

#: Substrings that must not occur under ts/src (contract §5.4.1 / §5.4.13: the core is browser- and node-neutral).
NODE_ONLY = ("node:", "process.", "Buffer", "require(", "import.meta")


def _int_leaves(obj, key=None, out=None):
    """``(enclosing key, value)`` of every integer leaf (booleans excluded) of a JSON document."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            _int_leaves(v, k, out)
    elif isinstance(obj, list):
        for v in obj:
            _int_leaves(v, key, out)
    elif isinstance(obj, int) and not isinstance(obj, bool):
        out.append((key, obj))
    return out


def ts_int_keys(text: str) -> list[str]:
    """The string items of the ``INT_KEYS`` literal of ``ts/src/output/geometry_json.ts``."""
    m = re.search(r"\bINT_KEYS\b[^=\n]*=\s*(?:new\s+Set(?:<[^>]*>)?\(\s*)?\[([^\]]*)\]", text)
    assert m, "no INT_KEYS literal in ts/src/output/geometry_json.ts"
    return re.findall(r"""["']([^"']+)["']""", m.group(1))


# ---------------------------------------------------------------------------
# shared files that exist now
# ---------------------------------------------------------------------------

def test_rules_json_equals_the_python_comparator_constants():
    assert RULES["image_tol_mm"] == tc.IMAGE_TOL_MM and RULES["rel_tol"] == tc.REL_TOL
    assert RULES["max_reported"] == tc.MAX_REPORTED
    assert sorted(RULES["mm_keys"]) == sorted(tc._MM_KEYS)
    assert tuple(RULES["drawable_containers"]) == tc._DRAWABLE_CONTAINERS
    assert sorted(RULES["arc_non_mm"]) == sorted(tc._ARC_NON_MM)
    assert tuple(tuple(p) for p in RULES["mm_key_paths"]) == tc._MM_KEY_PATHS
    assert tuple(RULES["int_keys"]) == tc._INT_KEYS
    assert RULES == tc.RULES


def test_integer_leaves_of_the_expected_files_sit_under_int_keys():
    """Contract §5.4.5 [decision]: a Python ``int`` under any key outside ``INT_KEYS`` is a contract
    violation, because the port writes every other number as a float."""
    int_keys = set(RULES["int_keys"])
    seen = {k: 0 for k in int_keys}
    files = sorted(EXPECTED.glob("*.json"))
    assert files
    for path in files:
        for key, _ in _int_leaves(json.loads(path.read_text(encoding="utf-8"))):
            assert key in int_keys, f"{path.name}: integer leaf under {key!r} (not in rules.json int_keys)"
            seen[key] += 1
    assert all(seen.values()), seen        # every listed key really occurs as an integer


def test_ts_int_keys_regex():
    assert ts_int_keys('export const INT_KEYS: ReadonlySet<string> = new Set(["large_arc", "sweep"]);') == \
        ["large_arc", "sweep"]
    assert ts_int_keys("export const INT_KEYS = ['large_arc', 'sweep', 'interval'] as const;") == \
        ["large_arc", "sweep", "interval"]


# ---------------------------------------------------------------------------
# checks of ts/ (skipped while the port is absent)
# ---------------------------------------------------------------------------

@needs_ts
def test_ts_versions_equal_the_python_version():
    pkg = json.loads((TS / "package.json").read_text(encoding="utf-8"))
    assert pkg["version"] == castplane.__version__
    index = (TS / "src" / "index.ts").read_text(encoding="utf-8")
    m = re.search(r"""\b__version__\b[^=\n]*=\s*["']([^"']+)["']""", index)
    assert m and m.group(1) == castplane.__version__


@needs_ts
def test_ts_int_keys_equal_rules_json():
    text = (TS / "src" / "output" / "geometry_json.ts").read_text(encoding="utf-8")
    assert sorted(ts_int_keys(text)) == sorted(RULES["int_keys"])


@needs_ts
def test_ts_core_is_node_neutral():
    offenders = []
    for path in sorted((TS / "src").rglob("*.ts")):
        text = path.read_text(encoding="utf-8")
        offenders += [f"{path.relative_to(ROOT)}: {s}" for s in NODE_ONLY if s in text]
    assert offenders == []


def test_compare_svg_tolerates_only_differences_at_a_rounding_boundary():
    """``tools/compare_svg.py`` (contract §5.4.6): a one-unit difference of the fourth decimal is tolerated only when
    the reference's unrounded value lies within 1e-12 mm of the half-way; a genuine 1e-4 drift is a mismatch."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("compare_svg", ROOT / "tools" / "compare_svg.py")
    cs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cs)
    py, ts = '<line x1="1.2345" y1="2"/>', '<line x1="1.2346" y1="2"/>'
    assert cs.near_boundary(1.23455) and cs.near_boundary(-7.00005) and not cs.near_boundary(1.2345)
    assert not cs.near_boundary(1.23455 + 1e-9)
    assert cs.compare("x", py, ts, '<line x1="1.23455000000000004" y1="2.00000000000000000"/>') == (
        ["x:1:\n  py: " + py + "\n  ts: " + ts], [])
    b, m = cs.compare("x", py, ts, '<line x1="1.23452000000000000" y1="2.00000000000000000"/>')
    assert b == [] and len(m) == 1                              # 3e-5 from the half-way: a drift, not rounding
    assert cs.compare("x", py, ts)[1] != []                     # without the unrounded line nothing is tolerated
    # the unrounded writer keeps the line structure of the real one
    scene = castplane.load_scene(ROOT / "examples" / "curved_demo.json")
    svg = castplane.render(scene)["svg"]
    real, exact = svg.split("\n"), cs.unrounded_svg(scene).split("\n")
    assert castplane.render(scene)["svg"] == svg                # the writer's formatters are restored
    assert len(real) == len(exact)
    assert [len(cs.split_numbers(a)[1]) for a in real] == [len(cs.split_numbers(e)[1]) for e in exact]
    assert exact != real and all(cs.split_numbers(a)[0] == cs.split_numbers(e)[0] for a, e in zip(real, exact))


# ---------------------------------------------------------------------------
# the TypeScript runner, exercised from pytest when node is present (M7 step 7)
# ---------------------------------------------------------------------------

NODE = shutil.which("node")
TSC = ROOT / "node_modules" / "typescript" / "bin" / "tsc"
BUILT = TS / "build" / "src" / "index.js"
needs_node = pytest.mark.skipif(NODE is None or not (TS / "package.json").exists(),
                                reason="node is not installed (the ts CI job runs the TypeScript suite)")


@pytest.fixture(scope="module")
def built_port():
    """``ts/build``, rebuilt from ``ts/src`` when the workspace's typescript is installed (``npm ci``), so the
    tests below never run a stale build; skipped when neither a compiler nor a build is available."""
    if TSC.is_file():
        for config in ("tsconfig.json", "tsconfig.test.json"):
            proc = subprocess.run([NODE, str(TSC), "-p", config], cwd=TS, capture_output=True, text=True, timeout=600)
            assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
    if not BUILT.is_file():
        pytest.skip("the TypeScript port is not built (npm ci && npm run -w ts build)")
    return TS / "build"


@needs_node
def test_ts_suite_passes(built_port):
    """The port's ``node:test`` suite (the §5.4.8 conformance runner on every case of the set included)."""
    tests = sorted(str(p) for p in (built_port / "test").glob("*.test.js"))
    assert any(p.endswith("conformance.test.js") for p in tests)
    proc = subprocess.run([NODE, "--test", *tests], cwd=TS, capture_output=True, text=True, timeout=900)
    tail = "\n".join(proc.stdout.splitlines()[-40:])
    assert proc.returncode == 0, tail + proc.stderr[-2000:]
    m = re.search(r"^# fail (\d+)$", proc.stdout, re.M)
    assert m and m.group(1) == "0", tail
    m = re.search(r"^# pass (\d+)$", proc.stdout, re.M)
    assert m and int(m.group(1)) >= len(tc.case_names()), tail


def test_v6_changelog_entry_records_both_runners_green():
    """Acceptance of M7 phase 2 (contract §5.4.0 (iii), §5.0.8 row "v6 M7 phase 2"): the v6 entry of the conformance
    changelog records "both runners green on v6" with the TypeScript runner's result (phase 2 changes no expected
    file and no rule, so it adds no version of its own)."""
    text = (ROOT / "tests" / "conformance" / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = [int(v) for v in re.findall(r"^## v(\d+) ", text, re.M)]
    assert 6 in versions
    v6 = re.split(r"^## v\d+ ", text, flags=re.M)[versions.index(6) + 1]
    line = next((ln for ln in v6.splitlines() if ln.startswith("- both runners green on v6")), None)
    assert line is not None, "the v6 entry lacks the 'both runners green on v6' line"
    assert "50 of 50 cases" in line
    assert "ts/test/conformance.test.ts" in line and "# todo 0" in line and "# fail 0" in line


@needs_node
def test_ts_conformance_runner_is_green_on_the_whole_set(built_port):
    """The final TypeScript conformance runner (contract §5.4.8, §5.4.0 phase 2: "both runners green on v6"): run
    alone, it reports one passing test per case of the set (``conformance: <name>``), nothing failed, skipped or
    ``todo``; and its source carries no todo list any more (the phase-2 parts shrank it, part 5 removed it)."""
    source = (TS / "test" / "conformance.test.ts").read_text(encoding="utf-8")
    determinism = (TS / "test" / "determinism.test.ts").read_text(encoding="utf-8")
    for text in (source, determinism):
        assert not re.search(r"\btodo\s*:", text) and "TODO_CASES" not in text and "TODO_EXAMPLES" not in text
    proc = subprocess.run([NODE, "--test", "--test-reporter=tap", str(built_port / "test" / "conformance.test.js")],
                          cwd=TS, capture_output=True, text=True, timeout=900)
    tail = "\n".join(proc.stdout.splitlines()[-30:])
    assert proc.returncode == 0, tail + proc.stderr[-2000:]
    passed = set(re.findall(r"^ok \d+ - conformance: (\S+)$", proc.stdout, re.M))
    failed = re.findall(r"^not ok \d+ - (.*)$", proc.stdout, re.M)
    assert failed == [], failed
    assert passed == set(tc.case_names()), sorted(set(tc.case_names()) ^ passed)
    assert len(passed) >= 50
    for key in ("fail", "skipped", "todo", "cancelled"):
        m = re.search(rf"^# {key} (\d+)$", proc.stdout, re.M)
        assert m and m.group(1) == "0", (key, tail)


@needs_node
def test_ts_and_web_sources_have_no_unused_locals(built_port):
    """No dead imports or locals in the port, its tests or the web UI: ``tsc --noEmit --noUnusedLocals`` on the
    normative configs (the flag is passed here because the §5.4.1 ``ts/tsconfig.json`` block is literal)."""
    if not TSC.is_file():
        pytest.skip("typescript is not installed (npm ci)")
    for cwd, config in ((TS, "tsconfig.test.json"), (ROOT / "web", "tsconfig.json"), (ROOT / "web", "tsconfig.test.json")):
        proc = subprocess.run([NODE, str(TSC), "--noEmit", "--noUnusedLocals", "-p", config], cwd=cwd,
                              capture_output=True, text=True, timeout=600)
        assert proc.returncode == 0, (cwd.name, config, proc.stdout[-4000:] + proc.stderr[-2000:])


@needs_node
def test_ts_render_equals_the_reference_on_the_examples(built_port, tmp_path):
    """``node ts/scripts/render.mjs``: the port's SVG of every example is the Python writer's text byte for byte
    (§5.4.6) and its JSON document passes the conformance comparator against the Python document (§5.4.8).  An
    example that references a mesh file is rendered by the port from its Python expansion
    (``ts/test/fixtures/<stem>.expanded.json``, :func:`test_expanded_example_fixtures_are_current`): the core has no
    loader (§5.4.0, §5.2.9)."""
    from castplane.io import load_expanded_scene
    from castplane.output import geometry_json

    examples = sorted((ROOT / "examples").glob("*.json"))
    # every example, the M4-M6 ones included (M7 phase 2 complete, contract §5.4.0 / §5.4.14): hidden lines on a
    # bounded wall, a mesh (from its expansion), two lights with the umbra
    assert {"wall_and_ground.json", "mesh_demo.json", "two_lights.json"} <= {p.name for p in examples}
    assert len(examples) == 8
    inputs = [EXPANDED.get(p.name, p) for p in examples]
    proc = subprocess.run([NODE, str(TS / "scripts" / "render.mjs"), *map(str, inputs), str(tmp_path)],
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    for path, src in zip(examples, inputs):
        stem = src.name[:-len(".json")]
        ref = castplane.render(load_expanded_scene(path)[0])
        assert (tmp_path / f"{stem}.svg").read_text(encoding="utf-8") == ref["svg"], path.name
        port_doc = json.loads((tmp_path / f"{stem}.json").read_text(encoding="utf-8"))
        assert tc.compare_documents(json.loads(geometry_json.dumps(ref["geometry"])), port_doc) == [], path.name


#: Examples that reference a mesh file, and the Python expansion the port's tests read instead (§5.4.0: no loader in
#: the core; ``ts/test/helpers.ts::read_example``).
EXPANDED = {"mesh_demo.json": TS / "test" / "fixtures" / "mesh_demo.expanded.json"}


@needs_ts
def test_expanded_example_fixtures_are_current():
    """Every example with a loader-level object (a mesh ``path``) has its committed expansion, equal to
    ``castplane.io.expand_scene`` of the example now (regenerate with ``json.dumps(scene, indent=1,
    sort_keys=True, ensure_ascii=False)`` and a newline), and nothing else has one."""
    from castplane.io import expand_scene
    from castplane.scene import read_json

    with_paths = {p.name for p in (ROOT / "examples").glob("*.json")
                  if any(isinstance(o, dict) and "path" in o for o in read_json(p).get("objects", []))}
    assert with_paths == set(EXPANDED)
    assert {p.name for p in (TS / "test" / "fixtures").glob("*.expanded.json")} == {p.name for p in EXPANDED.values()}
    for name, fixture in EXPANDED.items():
        example = ROOT / "examples" / name
        expanded, notes = expand_scene(read_json(example), str(example.parent))
        assert notes == []
        assert fixture.read_text(encoding="utf-8") == json.dumps(expanded, indent=1, sort_keys=True,
                                                                 ensure_ascii=False) + "\n", name


def _mesh_scenes() -> dict:
    """Mesh scenes for the cross-implementation check of the port's mesh part (contract §5.2.9, §5.4.14): the
    acceptance boxes, the fallback and buried variants, smooth prisms (the ray cap included), a smooth UV sphere, a
    hollow box with the light in its cavity, a light inside the box, Moebius / Klein connectivity, meshes on bounded
    receivers, the §7.1 invariant scenes and seeded ``make_mesh_scene`` scenes; several with hidden lines on."""
    import copy

    from castplane.mesh import sphere_mesh
    from tests import test_mesh_pipeline as mp
    from tests import test_meshprep as tm
    from tests.reference.random_scenes import make_mesh_scene

    def box(V, F, **kw):
        return mp.mesh_box_scene(V, F, **kw)

    scenes = {f"rand{s}": make_mesh_scene(s) for s in range(12)}
    scenes.update({f"inv{k}": copy.deepcopy(dict(sc)) for k, sc in enumerate(mp.mesh_invariant_scenes())})
    scenes["split"] = box(mp.SPLIT_V, mp.SPLIT_F)
    scenes["open_bottom"] = box(mp.CUBE_V, mp.OPEN_BOTTOM_F)
    scenes["open_bottom_buried"] = box(mp.CUBE_V, mp.OPEN_BOTTOM_F, transform={"position": [0, 0, -0.5]})
    scenes["split_buried"] = box(mp.SPLIT_V, mp.SPLIT_F, transform={"position": [0, 0, -0.5]})
    scenes["prism16"] = box(*mp.prism_data(16))
    scenes["prism100_capped"] = box(*mp.prism_data(100), smooth_angle_deg=0.0)
    sm = sphere_mesh(0.5)
    scenes["sphere"] = box(sm["vertices"].tolist(), sm["faces"])
    scenes["fan_prism"] = box(*tm.fan_prism(r=0.5, h=1.0))
    hv, hf = tm.hollow_box()
    scenes["hollow_cavity_light"] = box(hv, hf)
    scenes["hollow_cavity_light"]["lights"][0]["position"] = [0, 0, 1.0]
    scenes["light_inside"] = box(mp.SPLIT_V, mp.SPLIT_F)
    scenes["light_inside"]["lights"][0]["position"] = [0, 0, 0.5]
    mv, mf = tm.mobius()
    scenes["mobius"] = box([[0.4 * x, 0.4 * y, 0.4 * z + 0.6] for x, y, z in mv], mf)
    kv, kf = tm.klein()
    scenes["klein"] = box([[0.2 * x, 0.2 * y, 0.2 * z + 0.5] for x, y, z in kv], kf)
    for floor in (False, True):
        scenes[f"wall_fallback{int(floor)}"] = mp.wall_mesh_scene(mp.OPEN_BOTTOM_F, floor=floor)
        scenes[f"wall_split{int(floor)}"] = mp.wall_mesh_scene(mp.SPLIT_F, mp.SPLIT_V, floor=floor)
    for name in ("split", "open_bottom", "prism16", "sphere", "wall_fallback1", "wall_split1", "inv0", "rand1", "rand5"):
        sc = copy.deepcopy(scenes[name])
        sc.setdefault("output", {})["hidden_lines"] = True
        scenes[f"{name}_hidden"] = sc
    return scenes


@needs_node
def test_ts_mesh_scenes_equal_the_reference(built_port, tmp_path):
    """The port's mesh part against the Python reference beyond the three conformance cases: every scene of
    :func:`_mesh_scenes` gives the same SVG text byte for byte and a JSON document that passes the comparator."""
    from castplane.output import geometry_json

    scenes = _mesh_scenes()
    (tmp_path / "in").mkdir()
    paths = []
    for name, sc in scenes.items():
        path = tmp_path / "in" / f"{name}.json"
        path.write_text(json.dumps(sc), encoding="utf-8")
        paths.append(path)
    proc = subprocess.run([NODE, str(TS / "scripts" / "render.mjs"), *map(str, paths), str(tmp_path / "out")],
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    for name, sc in scenes.items():
        ref = castplane.render(castplane.load_scene(sc))
        assert (tmp_path / "out" / f"{name}.svg").read_text(encoding="utf-8") == ref["svg"], name
        port_doc = json.loads((tmp_path / "out" / f"{name}.json").read_text(encoding="utf-8"))
        assert tc.compare_documents(json.loads(geometry_json.dumps(ref["geometry"])), port_doc) == [], name


def _multilight_scenes() -> dict:
    """Multi-light scenes for the cross-implementation check of the port's multi-light part (contract §5.3,
    §5.4.14): the scenes of ``tests/test_multilight.py`` (acceptance box, curved two-light scene, the three-light
    concave scene on the ground in two light orders, inactive / identical / inside lights, cameras on and below the
    ground, a directional light along the normal as the second light, the two-light ``wall_and_ground`` with hidden
    lines, plates with per-light entries and core, mesh cases with a second light), hidden lines on (dashed and
    ``omit``) for several of them, and seeded ``make_scene(seed, n_lights=2 | 3)`` scenes."""
    import copy

    from tests import test_multilight as tm
    from tests.reference.random_scenes import make_scene

    box = [{"id": "cube", "type": "box", "size": [1, 1, 1]}]
    scenes = {"acceptance": tm.acceptance_scene(), "curved": tm.curved_scene(), "three": tm.three_light_scene(),
              "three_permuted": tm.three_light_scene((2, 0, 1)), "wall2": tm.wall_two_lights(),
              "plate_lamp2_behind": tm.plate_two_lights([1.0, 9.0, 3.0]),
              "plate_core": tm.plate_two_lights([-1.5, 2.5, 3.0])}
    scenes["inactive"] = tm.scene_of(box, [tm.WEST, {"id": "under", "type": "point", "position": [1.0, 0.5, -2.0]}],
                                     tm.ACCEPTANCE_CAMERA)
    scenes["twins"] = tm.scene_of(box, [tm.WEST, dict(tm.WEST, id="twin")], tm.ACCEPTANCE_CAMERA)
    scenes["inside"] = tm.scene_of(box + [{"id": "low", "type": "box", "size": [0.6, 0.6, 0.3],
                                           "transform": {"position": [2.0, 0.0, 0.0]}}],
                                   [tm.WEST, {"id": "bulb", "type": "point", "position": [0.0, 0.0, 0.5]}],
                                   dict(tm.ACCEPTANCE_CAMERA, position=[1.0, -7.0, 4.0], target=[1.5, 0.0, 0.0]))
    scenes["camera_on_ground"] = tm.scene_of(box, [tm.WEST, tm.EAST], dict(tm.ACCEPTANCE_CAMERA, position=[0.0, -6.0, 0.0],
                                                                          target=[0.0, 0.0, 0.5]))
    scenes["camera_below"] = tm.scene_of(box, [tm.WEST, tm.EAST], dict(tm.ACCEPTANCE_CAMERA, position=[0.3, -6.0, -2.0],
                                                                      target=[0.0, 0.0, 0.0]))
    scenes["vertical_sun"] = tm.scene_of(box, [tm.WEST, {"id": "sun", "type": "directional", "direction": [0, 0, 1]}],
                                         tm.ACCEPTANCE_CAMERA)
    for case in ("mesh_smooth_prism16", "mesh_open_bottom_box_fallback"):
        raw = json.loads((ROOT / "tests" / "conformance" / "cases" / f"{case}.json").read_text(encoding="utf-8"))
        x, y, z = raw["lights"][0]["position"]
        raw["lights"].append(dict(raw["lights"][0], id="second", position=[x + 1.0, y - 0.5, z]))
        scenes[f"{case}_two_lights"] = raw
    # seed 3 is left out: its ray of `obj3.g1.base.light2` (a generator foot 1e-6 m above the ground, |S' - Q'| /
    # |F' - Q'| ~ 1.7e-7) is the deferred ill-conditioned `covering_segments` case of the part-3 notes, not a
    # multi-light defect (the port's segment differs by 1.05e-6 mm)
    for seed in (0, 1, 2, 4, 5, 6, 7, 8):
        scenes[f"rand{seed}"] = make_scene(seed, n_lights=2 + seed % 2)
    for name in ("acceptance", "curved", "three", "inside", "rand1", "rand2"):
        for style in ("dashed", "omit"):
            sc = copy.deepcopy(scenes[name])
            sc.setdefault("output", {}).update({"hidden_lines": True, "hidden_style": style})
            scenes[f"{name}_hidden_{style}"] = sc
    # two bounded receivers in non-code-point scene order (the `per_receiver` marker order of the SVG, the part-1
    # note) and integer-like light ids (`multi_light_ids` sorting, §5.4.4 (8)); a crate and a ball standing on the
    # ground, so its umbra partition is build dependent (the review fixes of part 4)
    scenes["int_ids_two_walls"] = {
        "version": "0.1", "units": "m", "up": "z",
        "objects": [{"id": "crate", "type": "box", "size": [1, 1, 1], "transform": {"position": [0, 4.5, 0]}},
                    {"id": "ball", "type": "sphere", "radius": 0.4, "transform": {"position": [1.5, 3.5, 0.4]}}],
        "lights": [{"id": "9", "type": "point", "position": [0.5, 2, 3]},
                   {"id": "10", "type": "point", "position": [-1.5, 1.5, 2.6]}],
        "receivers": [{"id": "ground", "type": "plane", "normal": [0, 0, 1], "offset": 0},
                      {"id": "wall_b", "type": "plane", "normal": [0, -1, 0], "offset": 6,
                       "bounds": [[-3, 6, 0], [3, 6, 0], [3, 6, 2.5], [-3, 6, 2.5]]},
                      {"id": "wall_a", "type": "plane", "normal": [-1, 0, 0], "offset": 3.5,
                       "bounds": [[3.5, 1, 0], [3.5, 6, 0], [3.5, 6, 2.5], [3.5, 1, 2.5]]}],
        "camera": {"position": [-4, -6, 4], "target": [0.5, 4, 0.8], "focal_length_mm": 35, "frame_mm": [36, 24]},
        "output": {"canvas_mm": [360, 240]}}
    return scenes




def _piece_area(p) -> float:
    return 0.5 * sum(p[k][0] * p[(k + 1) % len(p)][1] - p[(k + 1) % len(p)][0] * p[k][1] for k in range(len(p)))


def _assert_same_umbra_region(ref_doc: dict, port_doc: dict, name: str) -> None:
    """The umbra of two implementations as a region (contract §5.3.4 "as a set"): per receiver the same lights, the
    union areas within 1e-9 (relative), and for up to 40 pieces the corner set of the union within the §4 (i) scaled
    1e-6 mm (``tests/test_multilight.py::assert_same_corners`` with the turning-angle threshold of the M6 notes)."""
    from tests import test_multilight as tm

    assert [e["lights"] for e in ref_doc["umbra"]] == [e["lights"] for e in port_doc["umbra"]], name
    for er, ep in zip(ref_doc["umbra"], port_doc["umbra"]):
        a, b = er["polygons"], ep["polygons"]
        ta, tb = sum(map(_piece_area, a)), sum(map(_piece_area, b))
        assert abs(ta - tb) <= 1e-9 * max(abs(ta), 1.0), (name, er["receiver"], ta, tb)
        if 0 < len(a) <= 40:
            scale = max(1.0, max(abs(float(x)) for piece in a for v in piece for x in v))
            ca, cb = tm.union_corners(a, angle_tol=1e-3), tm.union_corners(b, angle_tol=1e-3)
            assert len(ca) == len(cb), (name, er["receiver"])
            for c in ca:
                assert min(max(abs(c[0] - d[0]), abs(c[1] - d[1])) for d in cb) <= 1e-6 * scale, (name, c)


def _without_umbra_paths(svg: str) -> list:
    """The lines of an SVG text without the body of the ``cast_shadow.umbra`` group (its ``<path>`` elements; the
    group's own opening and closing lines are kept)."""
    out, inside = [], False
    for line in svg.split("\n"):
        if line.startswith('<g id="cast_shadow.umbra"'):
            inside = not line.endswith("/>")
            out.append(line)
            continue
        if inside and line != "</g>":
            continue
        inside = False if line == "</g>" else inside
        out.append(line)
    return out


@needs_node
def test_ts_multilight_scenes_equal_the_reference(built_port, tmp_path):
    """The port's multi-light part (M7 phase 2 part 4) against the Python reference beyond the four conformance
    cases: every scene of :func:`_multilight_scenes` gives the same SVG text byte for byte, a JSON document that
    passes the comparator, and an ``umbra[]`` that the reference kernel reproduces bit for bit from the port's own
    ``shadows[].polygons`` (contract §5.3.5 (c)). Where casters stand on the receiver the umbra *partition* is build
    dependent (cross-light vertex pairs within rounding of each other and collinear ground-contact edges of different
    lights, the §5.3 implementation notes "(M6 step 8)" and "(M6 review fixes)", the §5.4 part-4 note): the port's
    drawables differ from the reference's by ulps, so the pieces may differ while the region does not, and which
    scenes do depends on the numpy / BLAS build. So a scene that is not byte-identical falls back to the region rule:
    the SVG differs at most in the ``cast_shadow.umbra`` paths, the document only under ``umbra``, and the umbra is
    the same region (strict byte identity stays with the four conformance cases of ``conformance.test.ts``)."""
    from castplane.output import geometry_json
    from castplane.umbra import umbra_from_document

    scenes = _multilight_scenes()
    (tmp_path / "in").mkdir()
    paths = []
    for name, sc in scenes.items():
        path = tmp_path / "in" / f"{name}.json"
        path.write_text(json.dumps(sc), encoding="utf-8")
        paths.append(path)
    proc = subprocess.run([NODE, str(TS / "scripts" / "render.mjs"), *map(str, paths), str(tmp_path / "out")],
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    for name, sc in scenes.items():
        ref = castplane.render(castplane.load_scene(sc))
        ref_doc = json.loads(geometry_json.dumps(ref["geometry"]))
        assert "constructions" in ref_doc, name
        svg = (tmp_path / "out" / f"{name}.svg").read_text(encoding="utf-8")
        port_doc = json.loads((tmp_path / "out" / f"{name}.json").read_text(encoding="utf-8"))
        # §5.3.5 (c) across implementations: the reference kernel on the port's own drawables gives the port's umbra
        # bit for bit (the drawables of the two implementations may differ by ulps, the comparator covers that)
        assert umbra_from_document(port_doc) == port_doc["umbra"], name
        mismatches = tc.compare_documents(ref_doc, port_doc)
        if svg == ref["svg"] and mismatches == []:
            continue
        assert [m for m in mismatches if not m.startswith("umbra[")] == [], name
        _assert_same_umbra_region(ref_doc, port_doc, name)
        assert _without_umbra_paths(svg) == _without_umbra_paths(ref["svg"]), name


@needs_node
def test_ts_mesh_seed60_is_the_deferred_covering_segments_case(built_port, tmp_path):
    """``make_mesh_scene(60)`` (outside the seeds 0–11 of :func:`_mesh_scenes`) is the one mesh scene of seeds 0–99
    where the JSON comparator fails: the M7-review note "[implementation, deferred] ``covering_segments`` is
    ill-conditioned when ``S' ≈ Q'``". Pins that the difference is exactly that case — SVG byte-identical, every
    difference a ``construction.segments[].points`` entry of a ray whose vertex sits within 1e-5 m above the receiver —
    so the seed range of the mesh differential is not widened past it unknowingly."""
    from castplane.output import geometry_json
    from tests.reference.random_scenes import make_mesh_scene

    sc = make_mesh_scene(60)
    path = tmp_path / "seed60.json"
    path.write_text(json.dumps(sc), encoding="utf-8")
    proc = subprocess.run([NODE, str(TS / "scripts" / "render.mjs"), str(path), str(tmp_path / "out")],
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    scene = castplane.load_scene(sc)
    ref = castplane.render(scene)
    assert (tmp_path / "out" / "seed60.svg").read_text(encoding="utf-8") == ref["svg"]
    ref_doc = json.loads(geometry_json.dumps(ref["geometry"]))
    diffs = tc.compare_documents(ref_doc, json.loads((tmp_path / "out" / "seed60.json").read_text(encoding="utf-8")))
    assert diffs, "seed 60 now agrees: the deferred covering_segments amendment may have landed; update the note"
    world_z = {}
    for rec in castplane.shadow_geometry(scene)["objects"]:
        for name, v in zip(rec["point_names"], rec["mesh"]["vertices"]):
            world_z[name] = float(v[2])
    for d in diffs:
        m = re.match(r"construction\.segments\[(\d+)\]\.points\[", d)
        assert m, d
        seg = ref_doc["construction"]["segments"][int(m.group(1))]
        assert 0.0 <= world_z[seg["point"]] <= 1e-5, (d, seg["point"], world_z[seg["point"]])


@needs_node
def test_ts_weld_map_equals_the_reference_loop(built_port, tmp_path):
    """``meshprep.weld_map`` of the port (the reference loop of contract §5.2.3 step 2 on compressed number keys;
    the string-key fallback needs ~1e5 distinct cells on one axis, out of reach here and of validated meshes, and is
    forced by ``ts/test/meshprep.test.ts``) against Python's reference loop: clustered near-duplicates straddling cell borders,
    exact copies, points exactly on cell borders and at distance exactly ``τ``, for six tolerances incl. 0."""
    import numpy as np

    from castplane.meshprep import weld_map

    cases = []
    for seed in range(12):
        rng = np.random.default_rng(seed)
        tau = [1e-6, 1e-3, 0.05, 0.0, 0.3, 1e-6][seed % 6] * (1.0 if seed < 6 else 7.3)
        centres = rng.uniform(-2, 2, size=(60, 3))
        pts = [centres[int(rng.integers(60))] + rng.uniform(-1.2, 1.2, size=3) * tau for _ in range(600)]
        pts += list(centres) + [np.array([0.5, 0.5, 0.5]) * tau, np.array([1.5, 0.5, 0.5]) * tau,
                                np.array([-0.5, 0.5, 0.5]) * tau]
        pts += [pts[int(rng.integers(len(pts)))] for _ in range(100)]
        V = np.array(pts)[rng.permutation(len(pts))]
        cases.append({"V": V.tolist(), "tau": tau, "rep": weld_map(V, tau, fast=False).tolist()})
    cases.append({"V": [[1.0, 0, 0], [1.0, 0, 0], [2.0, 0, 0], [1.0, 1e-300, 0]], "tau": 1e-300,
                  "rep": weld_map([[1.0, 0, 0], [1.0, 0, 0], [2.0, 0, 0], [1.0, 1e-300, 0]], 1e-300, fast=False).tolist()})
    (tmp_path / "weld.json").write_text(json.dumps(cases), encoding="utf-8")
    script = ("import { readFileSync } from 'node:fs';"
              f"const {{ weld_map }} = await import({json.dumps((built_port / 'src' / 'meshprep.js').as_uri())});"
              "const cases = JSON.parse(readFileSync(process.argv[1], 'utf-8'));"
              "console.log(JSON.stringify(cases.map((c) => JSON.stringify(weld_map(c.V, c.tau)) === JSON.stringify(c.rep))));")
    proc = subprocess.run([NODE, "--input-type=module", "-e", script, str(tmp_path / "weld.json")],
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert json.loads(proc.stdout) == [True] * len(cases)


@needs_node
def test_ts_umbra_pieces_equal_the_reference(built_port, tmp_path):
    """``umbra.record_pieces`` / ``umbra.umbra_pieces`` of the port (contract §5.3.4, M7 phase 2 part 4) against the
    reference kernel, bit for bit (pieces and sides): 40 random two- to four-light inputs with star loops,
    self-intersecting loops and loops on a coarse lattice (coincident vertices and collinear edges across lights)."""
    import numpy as np

    from castplane.umbra import record_pieces, tolerances, umbra_pieces

    canvas = [360.0, 240.0]
    tol_mm, tol_area = tolerances(canvas)
    cases = []
    for seed in range(40):
        rng = np.random.default_rng(seed)
        per_light = []
        for _ in range(2 + seed % 3):
            records = []
            for _ in range(1 + int(rng.integers(3))):
                n = int(rng.integers(3, 15))
                th = np.sort(rng.random(n)) * 2 * np.pi
                r = 5 + 20 * rng.random(n)
                c = rng.random(2) * 40 - 20
                loops = [np.stack([c[0] + r * np.cos(th), c[1] + r * np.sin(th)], axis=1)]
                if rng.random() < 0.5:
                    loops.append(rng.random((int(rng.integers(3, 9)), 2)) * 40 - 20)
                if rng.random() < 0.4:
                    loops.append(np.round(rng.random((5, 2)) * 8) * 5 - 20)
                records.append([lp.tolist() for lp in loops])
            per_light.append(records)
        recs = [rec for records in per_light for rec in records]
        cases.append({"per_light": per_light, "umbra": umbra_pieces(per_light, canvas),
                      "records": [[[p.tolist() for p in pieces], sides.tolist()]
                                  for pieces, sides in (record_pieces(rec, tol_mm, tol_area) for rec in recs)]})
    (tmp_path / "umbra.json").write_text(json.dumps(cases), encoding="utf-8")
    script = ("import { readFileSync } from 'node:fs';"
              f"const U = await import({json.dumps((built_port / 'src' / 'umbra.js').as_uri())});"
              "const cases = JSON.parse(readFileSync(process.argv[1], 'utf-8'));"
              "const [tm, ta] = U.tolerances([360, 240]);"
              "console.log(JSON.stringify(cases.map((c) => JSON.stringify(U.umbra_pieces(c.per_light, [360, 240])) === "
              "JSON.stringify(c.umbra) && JSON.stringify(c.per_light.flat().map((r) => U.record_pieces(r, tm, ta))) === "
              "JSON.stringify(c.records))));")
    proc = subprocess.run([NODE, "--input-type=module", "-e", script, str(tmp_path / "umbra.json")],
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert json.loads(proc.stdout) == [True] * len(cases)
    assert sum(len(c["umbra"]) for c in cases) > 100


@needs_node
def test_ts_bench_reports_the_bench_py_record(built_port):
    """``ts/bench/camera_only.ts --json`` (§5.4.9): the field names of ``bench.py --json`` plus ``engine``, the
    document size of the committed benchmark scene, and ``--gate none`` exits 0."""
    proc = subprocess.run([NODE, str(built_port / "bench" / "camera_only.js"), "--json", "--reps", "1", "--gate", "none"],
                          cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    rec = json.loads(proc.stdout)
    assert set(rec) == {"objects", "mesh_edges", "document_edges", "points", "svg_bytes", "json_bytes", "warnings",
                        "reps", "full_render_s", "camera_only_s", "stage_a_s", "svg_s", "json_s", "pass", "gate",
                        "engine"}
    assert rec["objects"] == 100 and rec["mesh_edges"] == 10726 and rec["reps"] == 1 and rec["gate"] == "none"
    assert rec["full_render_s"]["target"] == 1.0 and rec["camera_only_s"]["target"] == 0.1
    assert set(rec["pass"]) == {"full_render", "camera_only"} and set(rec["engine"]) == {"node", "v8"}
    bad = subprocess.run([NODE, str(built_port / "bench" / "camera_only.js"), "--gate", "sometimes"],
                         cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert bad.returncode == 2 and "unknown gate" in bad.stderr


@needs_node
def test_ts_bench_writes_the_svg_of_the_bench_py_protocol(built_port, tmp_path):
    """§5.4.9: the TS protocol mirrors ``benchmarks/bench.py``, whose ``write_svg(doc, layers=…)`` passes no
    ``hidden_style``. A ``--scene`` with ``hidden_style: "omit"`` must therefore time the document of the
    default (dashed) style, the one the Python ``--hidden-lines`` row times (review fix, M7 phase 2 part 5)."""
    from castplane.output.svg import write_svg
    scene = json.loads((ROOT / "examples" / "wall_and_ground.json").read_text(encoding="utf-8"))
    scene["output"].update({"hidden_lines": True, "hidden_style": "omit"})
    path = tmp_path / "omit.json"
    path.write_text(json.dumps(scene), encoding="utf-8")
    proc = subprocess.run([NODE, str(built_port / "bench" / "camera_only.js"), "--json", "--reps", "1", "--gate", "none",
                           "--scene", str(path)], cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    doc = castplane.compose(scene, castplane.project_scene(scene, castplane.shadow_geometry(scene)))
    dashed = write_svg(doc, layers=scene["output"]["layers"])
    assert len(dashed) != len(write_svg(doc, layers=scene["output"]["layers"], hidden_style="omit"))
    assert json.loads(proc.stdout)["svg_bytes"] == len(dashed)


# ---------------------------------------------------------------------------
# the npm workspace and the web UI (M7 step 8)
# ---------------------------------------------------------------------------

WEB = ROOT / "web"
#: Exact pins of contract §5.4.1 [decision] (no ``^`` anywhere).
WEB_PINS = {"three": "0.186.1", "castplane": "0.1.0", "vite": "8.3.3", "typescript": "6.0.2", "@types/three": "0.186.0"}


def _pins(pkg: dict) -> dict:
    return {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}


@needs_ts
def test_npm_workspace_and_exact_pins():
    root = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert root["private"] is True and root["workspaces"] == ["ts", "web"]
    ts_pkg = json.loads((TS / "package.json").read_text(encoding="utf-8"))
    web_pkg = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    assert web_pkg["name"] == "castplane-web" and web_pkg["private"] is True and web_pkg["type"] == "module"
    for name, pkg in (("ts", ts_pkg), ("web", web_pkg)):
        for dep, version in _pins(pkg).items():
            assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"{name}/package.json: {dep} {version!r} is not an exact pin"
    pins = _pins(web_pkg)
    assert {k: pins[k] for k in WEB_PINS} == WEB_PINS
    assert pins["@types/node"] == _pins(ts_pkg)["@types/node"] and _pins(ts_pkg)["typescript"] == "6.0.2"
    assert web_pkg["dependencies"] == {"three": "0.186.1", "castplane": castplane.__version__}


@needs_ts
def test_web_tsconfig_is_the_normative_block():
    """``web/tsconfig.json`` (contract §5.4.1): strict, module ESNext, moduleResolution bundler, lib exactly
    ``["ES2022", "DOM"]``, noEmit.  The only additions are the ``ts/tsconfig.json`` strictness flags, ``target``,
    ``types: ["vite/client"]`` (for ``import.meta.glob``) and ``vite.config.ts`` in ``include`` (step-8 note)."""
    config = json.loads((WEB / "tsconfig.json").read_text(encoding="utf-8"))
    opts = config["compilerOptions"]
    assert opts["strict"] is True and opts["noEmit"] is True
    assert opts["module"] == "ESNext" and opts["moduleResolution"] == "bundler"
    assert opts["lib"] == ["ES2022", "DOM"]
    extra = set(opts) - {"strict", "module", "moduleResolution", "lib", "noEmit"}
    assert extra <= {"target", "isolatedModules", "verbatimModuleSyntax", "noImplicitOverride",
                     "noFallthroughCasesInSwitch", "types"}, sorted(extra)
    assert opts.get("types") == ["vite/client"] and opts.get("target") == "ES2022"
    assert config["include"] == ["src", "vite.config.ts"]
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    for dep, version in WEB_PINS.items():
        if dep != "castplane":
            assert lock["packages"][f"node_modules/{dep}"]["version"] == version, dep
    assert lock["packages"]["node_modules/castplane"].get("link") is True
    assert "shadowMap.enabled = false" in (WEB / "src" / "main.ts").read_text(encoding="utf-8")


@needs_node
def test_web_unit_tests_pass(built_port):
    """``npm run -w web test``: the orbit / download tests of §5.4.13 (needs the workspace's typescript)."""
    if not TSC.is_file():
        pytest.skip("typescript is not installed (npm ci)")
    proc = subprocess.run([NODE, str(TSC), "-p", "tsconfig.test.json"], cwd=WEB, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
    tests = sorted(str(p) for p in (WEB / "build" / "test").glob("*.test.js"))
    assert tests
    proc = subprocess.run([NODE, "--test", *tests], cwd=WEB, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, "\n".join(proc.stdout.splitlines()[-40:]) + proc.stderr[-2000:]
    assert re.search(r"^# fail 0$", proc.stdout, re.M)


def _ci_jobs(text: str) -> dict[str, dict]:
    """The jobs of ``ci.yml`` read as text (no YAML parser: PyYAML is not a dev dependency, and an
    ``importorskip`` would silently skip this guard in the Python CI job).  The workflow's layout is fixed:
    jobs at 2 spaces under ``jobs:``, steps as ``      - `` items, step keys at 8 spaces; a ``run: |`` block's
    lines are joined with newlines and a trailing ``# comment`` of a one-line ``run:`` is dropped.  Returns
    ``{job: {"matrix_node": str | None, "steps": [{"if": str, "run": str}, ...]}}``."""
    lines = text.splitlines()
    start = lines.index("jobs:") + 1
    jobs: dict[str, dict] = {}
    job = step = None
    block = None  # the step dict whose ``run: |`` block is being read
    for line in lines[start:]:
        if block is not None:
            if line.startswith("          ") or not line.strip():
                block["run"] += line.strip() + "\n"
                continue
            block["run"] = block["run"].strip()
            block = None
        if re.fullmatch(r"\S.*", line):
            break  # a top-level key after ``jobs:``
        m = re.fullmatch(r"  ([A-Za-z_][\w-]*):\s*", line)
        if m:
            job = jobs.setdefault(m.group(1), {"matrix_node": None, "steps": []})
            step = None
            continue
        if job is None:
            continue
        m = re.fullmatch(r"\s+node: (\[.*\])\s*", line)
        if m and step is None:
            job["matrix_node"] = m.group(1)
            continue
        m = re.fullmatch(r"      - (.*)", line)
        if m:
            step = {"if": "", "run": ""}
            job["steps"].append(step)
            line = "        " + m.group(1)
        if step is None:
            continue
        m = re.fullmatch(r"        (if|run): (.*)", line)
        if m:
            value = m.group(2)
            if m.group(1) == "run" and value.strip() == "|":
                block = step
                continue
            if m.group(1) == "run":
                value = re.sub(r"\s+#.*$", "", value)
            step[m.group(1)] = value.strip()
    if block is not None:
        block["run"] = block["run"].strip()
    return jobs


def test_ci_text_parser_reads_the_layout_of_the_workflow():
    """The text reader of ``ci.yml`` on a hand-written workflow of the same layout."""
    text = (
        "name: CI\n"
        "jobs:\n"
        "  a:\n"
        "    strategy:\n"
        "      matrix:\n"
        '        node: ["20", "22"]\n'
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - run: npm ci\n"
        "      - run: npm run -w ts test    # comment\n"
        "      - name: bench\n"
        "        if: matrix.node == '22'\n"
        "        run: node x.js --gate full --reps 20\n"
        "  b:\n"
        "    steps:\n"
        "      - name: install\n"
        "        run: |\n"
        "          pip install a\n"
        "          pip install b\n"
        "      - run: done\n"
    )
    jobs = _ci_jobs(text)
    assert set(jobs) == {"a", "b"}
    assert jobs["a"]["matrix_node"] == '["20", "22"]'
    assert [s["run"] for s in jobs["a"]["steps"]] == ["", "npm ci", "npm run -w ts test", "node x.js --gate full --reps 20"]
    assert jobs["a"]["steps"][3]["if"] == "matrix.node == '22'"
    assert jobs["b"]["matrix_node"] is None
    assert [s["run"] for s in jobs["b"]["steps"]] == ["pip install a\npip install b", "done"]


def test_ci_runs_the_port_and_the_web_ui_with_the_recorded_gate():
    """``.github/workflows/ci.yml`` (contract §5.4.12): jobs ``ts`` (node 20 / 22) and ``web``; the benchmark gate
    literal is the one recorded in ``benchmarks/README.md`` at M7 step 7 (§5.4.9 margin rule).  Read as text, so
    the check runs in the Python CI job (no PyYAML there)."""
    jobs = _ci_jobs((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    assert {"test", "ts", "web"} <= set(jobs)
    assert jobs["ts"]["matrix_node"] == '["20", "22"]'
    ts_runs = [s["run"] for s in jobs["ts"]["steps"]]
    web_runs = [s["run"] for s in jobs["web"]["steps"]]
    assert "npm ci" in ts_runs and "npm ci" in web_runs
    assert any(r.startswith("npm run -w ts test") for r in ts_runs)
    # the final runner (M7 phase 2): the conformance runner alone, failing on a failed, skipped or todo case
    runner = [r for r in ts_runs if "conformance.test.js" in r]
    assert len(runner) == 1 and "--test-reporter=tap" in runner[0]
    assert all(f"grep -qx '# {key} 0'" in runner[0] for key in ("fail", "skipped", "todo"))
    bench = [s for s in jobs["ts"]["steps"] if "camera_only.js" in s["run"]]
    assert len(bench) == 1 and bench[0]["if"] == "matrix.node == '22'"
    gate = re.search(r"--gate (\w+)", bench[0]["run"]).group(1)
    assert "--reps 20" in bench[0]["run"]
    readme = (ROOT / "benchmarks" / "README.md").read_text(encoding="utf-8")
    assert f"node ts/build/bench/camera_only.js --gate {gate} --reps 20" in readme
    assert any("npm run -w web test" in r and "npm run -w web build" in r for r in web_runs)
    assert any("tests/test_ts_port.py" in s["run"] for s in jobs["test"]["steps"])
