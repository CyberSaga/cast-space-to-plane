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
"""

from __future__ import annotations

import json
import pathlib
import re

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
