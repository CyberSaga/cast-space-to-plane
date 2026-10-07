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


@needs_node
def test_ts_render_equals_the_reference_on_the_examples(built_port, tmp_path):
    """``node ts/scripts/render.mjs``: the port's SVG of every example is the Python writer's text byte for byte
    (§5.4.6) and its JSON document passes the conformance comparator against the Python document (§5.4.8)."""
    from castplane.output import geometry_json

    examples = sorted((ROOT / "examples").glob("*.json"))
    # M7 phase 2 (contract §5.4.0): the examples whose geometry belongs to a phase-2 part that has not landed yet
    # (hidden lines, meshes, N >= 2); each part shrinks this list, the final part leaves it empty
    todo = {"mesh_demo.json", "two_lights.json", "wall_and_ground.json"}
    assert todo <= {p.name for p in examples}
    examples = [p for p in examples if p.name not in todo]
    assert len(examples) == 5
    proc = subprocess.run([NODE, str(TS / "scripts" / "render.mjs"), *map(str, examples), str(tmp_path)],
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    for path in examples:
        ref = castplane.render(castplane.load_scene(path))
        assert (tmp_path / f"{path.stem}.svg").read_text(encoding="utf-8") == ref["svg"], path.name
        port_doc = json.loads((tmp_path / f"{path.stem}.json").read_text(encoding="utf-8"))
        assert tc.compare_documents(json.loads(geometry_json.dumps(ref["geometry"])), port_doc) == [], path.name


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
    bench = [s for s in jobs["ts"]["steps"] if "camera_only.js" in s["run"]]
    assert len(bench) == 1 and bench[0]["if"] == "matrix.node == '22'"
    gate = re.search(r"--gate (\w+)", bench[0]["run"]).group(1)
    assert "--reps 20" in bench[0]["run"]
    readme = (ROOT / "benchmarks" / "README.md").read_text(encoding="utf-8")
    assert f"node ts/build/bench/camera_only.js --gate {gate} --reps 20" in readme
    assert any("npm run -w web test" in r and "npm run -w web build" in r for r in web_runs)
    assert any("tests/test_ts_port.py" in s["run"] for s in jobs["test"]["steps"])
