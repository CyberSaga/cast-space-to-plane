"""Conformance set (spec §7.5; contract §4): every ``tests/conformance/cases/*.json`` scene rendered
through ``castplane.render`` must reproduce ``tests/conformance/expected/*.json``.

Comparison rules (the contract for the TypeScript port, see ``tests/conformance/README.md``):

* every ``image`` coordinate -- the ``points[].image`` entries and all drawables in canvas mm
  (``edges[].segment``, ``shadows[].polygons``, ``form_shadow[].polygons``, ``outlines[].generators[].segment``,
  the ``polylines`` / ``arcs`` / ``ellipses`` of conic entries, ``construction.segments[].points``,
  ``light_point`` / ``shadow_vp``, ``horizon.v_mm`` / ``segment`` / ``vanishing_points``,
  ``camera.principal_point``, ``canvas_mm`` and the self-check ``max_error_mm``) within
  :data:`IMAGE_TOL_MM` = 1e-6 mm (absolute);
* every other number (world coordinates, depths, directions, conic matrices, camera matrix, angles)
  within :data:`REL_TOL` = 1e-9 relative, with an absolute floor of 1e-9
  (``|a - b| <= 1e-9 * max(1, |a|, |b|)``);
* every non-number (strings, booleans, nulls, list lengths, dict keys) exactly;
* ``warnings``: the SET of codes must be equal (spec §7.5) and so must the set of ``(code, ids)``
  pairs (contract §2.9 fixes the ids); messages are not compared.

Integers and floats are both numbers (a port may write ``1`` for ``1.0``); booleans are not.

The comparator constants are shared with the TypeScript runner through ``tests/conformance/rules.json``
(contract §5.4.8, set v3): this module keeps its own constants and asserts that they equal the file,
and it reads the per-case ``case_overrides`` from the file (an absolute tolerance for the numbers below
the named path prefixes of one case only; non-numbers, key sets and warnings are never relaxed).

M4 (contract §5.0.8, §5.1.11): ``rules.json["runs_rule"]`` applies to every number inside a ``runs`` list
entry (edges, generators, terminator segments, conic entries, ``polygon_edges``): ``mm`` within 0.05 mm
absolute, ``s`` / ``t`` / ``theta`` within 1e-3 absolute, ``visible`` / ``interval`` exact (the run count is
a list length, exact anyway); it overrides ``arc_non_mm`` for ``theta`` inside runs.  ``hidden_polylines``
is an mm key, ``construction.per_receiver.*.segments.*.points`` an mm path and ``interval`` an int key.
"""

from __future__ import annotations

import json
import math
import pathlib
import re

import numpy
import pytest

import castplane
from castplane.output.geometry_json import dumps
from castplane.scene import LIGHT_TYPES, OBJECT_TYPES, load_scene

CONFORMANCE = pathlib.Path(__file__).resolve().parent / "conformance"
CASES = CONFORMANCE / "cases"
EXPECTED = CONFORMANCE / "expected"

IMAGE_TOL_MM = 1e-6
REL_TOL = 1e-9
MAX_REPORTED = 25

#: Keys below which every number is an image coordinate / length in canvas mm.
_MM_KEYS = frozenset({"image", "segment", "polygons", "polylines", "hidden_polylines", "light_point", "shadow_vp", "v_mm",
                      "vanishing_points", "principal_point", "canvas_mm", "max_error_mm"})
#: Inside ``arcs`` / ``ellipses`` entries these keys are angles / flags, not mm.
_ARC_NON_MM = frozenset({"rotation_deg", "theta", "large_arc", "sweep"})
#: Containers whose entries are drawables in canvas mm (except the :data:`_ARC_NON_MM` keys).
_DRAWABLE_CONTAINERS = ("arcs", "ellipses")
#: Path prefixes below which every number is in canvas mm (``*`` matches any one list index or key).
_MM_KEY_PATHS = (("construction", "segments", "*", "points"),
                 ("construction", "per_receiver", "*", "segments", "*", "points"),
                 # M6 (contract §5.3.5, §5.0.8): one construction block per light in multi-light documents
                 ("constructions", "*", "segments", "*", "points"),
                 ("constructions", "*", "per_receiver", "*", "segments", "*", "points"))
#: The only keys whose numbers the writer emits as integers (``INT_KEYS`` of contract §5.4.5).
_INT_KEYS = ("large_arc", "sweep", "interval")
#: The comparator constants shared with the TypeScript runner (contract §5.4.8, §5.0.8).
RULES_FILE = CONFORMANCE / "rules.json"
RULES = json.loads(RULES_FILE.read_text(encoding="utf-8"))
#: M4 (contract §5.0.8): the tolerances inside ``runs`` entries, read from ``rules.json``.
_RUNS_RULE = RULES["runs_rule"]
#: Spec §5.7 rows 1-6 must each be represented by at least one case (contract §4).
_DEGENERATE_ROW_CODES = ("LIGHT_BEHIND_CAMERA", "LIGHT_POINT_AT_INFINITY", "DIRECTIONAL_HORIZONTAL",
                         "VERTEX_NOT_BELOW_LIGHT", "POINT_BEHIND_CAMERA", "FACE_PARALLEL_TO_LIGHT")


def case_names() -> list[str]:
    return sorted(p.stem for p in CASES.glob("*.json"))


def path_has_prefix(path: tuple, pattern) -> bool:
    """True when ``pattern`` (``*`` = any one list index or key) matches the first ``len(pattern)``
    entries of ``path`` (the ``mm_key_paths`` and ``case_overrides`` rule of ``rules.json``)."""
    if len(path) < len(pattern):
        return False
    return all(p == "*" or p == k for p, k in zip(pattern, path))


def is_image_path(path: tuple) -> bool:
    """True when the number at ``path`` is an image coordinate / mm length (see the module docstring)."""
    in_drawable = False
    for key in path:
        if key in _MM_KEYS:
            return True
        if key in _DRAWABLE_CONTAINERS:
            in_drawable = True
        elif in_drawable and key in _ARC_NON_MM:
            return False
    if in_drawable:
        return True
    return any(path_has_prefix(path, pattern) for pattern in _MM_KEY_PATHS)


def case_overrides(case_name) -> list:
    """The ``case_overrides`` entries of ``rules.json`` for ``case_name`` as ``(paths, abs_tol)`` pairs
    (empty for ``None`` and for every case without an entry)."""
    if case_name is None:
        return []
    return [(tuple(tuple(p) for p in entry["paths"]), float(entry["abs_tol"]))
            for entry in RULES["case_overrides"].get(case_name, [])]


def _override_tol(path: tuple, overrides) -> float | None:
    for paths, abs_tol in overrides:
        if any(path_has_prefix(path, pattern) for pattern in paths):
            return abs_tol
    return None


def runs_tol(path: tuple) -> float | None:
    """The absolute tolerance of the number at ``path`` when it lies inside a ``runs`` list entry
    (``rules.json["runs_rule"]``, contract §5.0.8): ``mm_abs`` below ``mm``, ``param_abs`` below a
    ``param_keys`` key, ``0`` (exact) below an ``exact_keys`` key; ``None`` outside runs (default rules)."""
    for i in range(len(path) - 3, -1, -1):
        if path[i] == "runs" and isinstance(path[i + 1], int):
            key = path[i + 2]
            if key == "mm":
                return float(_RUNS_RULE["mm_abs"])
            if key in _RUNS_RULE["param_keys"]:
                return float(_RUNS_RULE["param_abs"])
            if key in _RUNS_RULE["exact_keys"]:
                return 0.0
            return None
    return None


def _fmt(path: tuple) -> str:
    out = ""
    for key in path:
        out += f"[{key}]" if isinstance(key, int) else (f".{key}" if out else str(key))
    return out or "<root>"


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _numbers_match(a, b, image: bool, abs_tol: float | None = None) -> bool:
    if not (math.isfinite(a) and math.isfinite(b)):
        return a == b
    if abs_tol is not None:
        return abs(a - b) <= abs_tol
    if image:
        return abs(a - b) <= IMAGE_TOL_MM
    return abs(a - b) <= REL_TOL * max(1.0, abs(a), abs(b))


def _walk(exp, act, path: tuple, out: list, overrides=()) -> None:
    if len(out) > MAX_REPORTED:
        return
    if _is_number(exp) and _is_number(act):
        image = is_image_path(path)
        abs_tol = _override_tol(path, overrides) if overrides else None
        source = "case override"
        if abs_tol is None:
            abs_tol, source = runs_tol(path), "runs rule"
        if not _numbers_match(float(exp), float(act), image, abs_tol):
            if abs_tol is not None:
                tol = f"{abs_tol:g} absolute, {source}"
            else:
                tol = f"{IMAGE_TOL_MM:g} mm" if image else f"{REL_TOL:g} relative"
            out.append(f"{_fmt(path)}: expected {exp!r}, got {act!r} (tolerance {tol})")
        return
    if isinstance(exp, dict) and isinstance(act, dict):
        if set(exp) != set(act):
            missing, extra = sorted(set(exp) - set(act)), sorted(set(act) - set(exp))
            out.append(f"{_fmt(path)}: key mismatch (missing {missing}, unexpected {extra})")
            return
        for key in sorted(exp):
            _walk(exp[key], act[key], path + (key,), out, overrides)
        return
    if isinstance(exp, list) and isinstance(act, list):
        if len(exp) != len(act):
            out.append(f"{_fmt(path)}: expected a list of {len(exp)} entries, got {len(act)}")
            return
        for i, (e, a) in enumerate(zip(exp, act)):
            _walk(e, a, path + (i,), out, overrides)
        return
    if type(exp) is not type(act) or exp != act:
        out.append(f"{_fmt(path)}: expected {exp!r}, got {act!r} (exact)")


def compare_documents(expected: dict, actual: dict, case_name: str | None = None) -> list[str]:
    """List of human-readable mismatches between two JSON-native §6.2 documents (empty = conformant).

    ``case_name`` selects the ``case_overrides`` of ``rules.json`` (contract §5.4.8); ``None`` applies
    the default rules only."""
    out: list[str] = []
    exp_w, act_w = expected.get("warnings", []), actual.get("warnings", [])
    exp_codes, act_codes = {w["code"] for w in exp_w}, {w["code"] for w in act_w}
    if exp_codes != act_codes:
        out.append(f"warnings: code set mismatch (missing {sorted(exp_codes - act_codes)}, "
                   f"unexpected {sorted(act_codes - exp_codes)})")
    exp_ids = {(w["code"], tuple(w["ids"])) for w in exp_w}
    act_ids = {(w["code"], tuple(w["ids"])) for w in act_w}
    if exp_ids != act_ids:
        out.append(f"warnings: (code, ids) set mismatch (missing {sorted(exp_ids - act_ids)}, "
                   f"unexpected {sorted(act_ids - exp_ids)})")
    exp_rest = {k: v for k, v in expected.items() if k != "warnings"}
    act_rest = {k: v for k, v in actual.items() if k != "warnings"}
    _walk(exp_rest, act_rest, (), out, case_overrides(case_name))
    return out


def render_case(name: str) -> dict:
    """The JSON-native document of a case, exactly as the expected file would be written."""
    scene = load_scene(CASES / f"{name}.json")
    return json.loads(dumps(castplane.render(scene)["geometry"]))


def load_expected(name: str) -> dict:
    return json.loads((EXPECTED / f"{name}.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- the set itself
def test_case_ids_are_unique_and_every_case_has_an_expected_file():
    names = case_names()
    assert names, "no conformance cases"
    assert len({n.lower() for n in names}) == len(names), "case ids must be unique (case-insensitively)"
    expected = sorted(p.stem for p in EXPECTED.glob("*.json"))
    assert expected == names, (f"cases without expected file: {sorted(set(names) - set(expected))}; "
                               f"expected files without case: {sorted(set(expected) - set(names))}")
    for name in names:
        data = json.loads((CASES / f"{name}.json").read_text(encoding="utf-8"))
        assert isinstance(data.get("description"), str) and data["description"].strip(), name
        load_scene(data)   # every case is a valid spec §4 scene


def test_expected_files_are_canonical_and_small():
    """The expected files are exactly ``geometry_json.dumps`` output (no hand edits) and the whole set
    stays reviewable (< 3 MB)."""
    total = 0
    for name in case_names():
        text = (EXPECTED / f"{name}.json").read_text(encoding="utf-8")
        total += len(text.encode("utf-8"))
        assert text == dumps(json.loads(text)) + "\n", f"{name}: expected file is not in canonical form"
    assert total < 3 * 1024 * 1024, total


def test_set_covers_the_required_sources():
    """Spec §7.5 sources: every §5.7 row, all five primitive types, both light types, both camera forms."""
    codes, kinds, lights, forms = set(), set(), set(), set()
    n_lights = set()   # M6 (contract §5.0.8, §5.3.10): a case with N >= 2 and one with N >= 3
    for name in case_names():
        scene = load_scene(CASES / f"{name}.json")
        n_lights.add(len(scene["lights"]))
        kinds.update(o["type"] for o in scene["objects"])
        lights.update(lt["type"] for lt in scene["lights"])
        forms.add("target" if "target" in scene["camera"] else "yaw_pitch")
        codes.update(w["code"] for w in load_expected(name)["warnings"])
    assert set(_DEGENERATE_ROW_CODES) <= codes, sorted(set(_DEGENERATE_ROW_CODES) - codes)
    # every object kind incl. ``mesh`` (the three M5 cases, contract §5.0.8, §5.2.11)
    assert kinds == set(OBJECT_TYPES) and lights == set(LIGHT_TYPES) and forms == {"target", "yaw_pitch"}
    assert max(n_lights) >= 3 and any(n >= 2 for n in n_lights - {max(n_lights)}), sorted(n_lights)


@pytest.mark.parametrize("name", case_names())
def test_render_matches_expected(name):
    expected, actual = load_expected(name), render_case(name)
    if "hidden_lines" not in expected:
        # a v2/v3 expected file inside the M4 worktree (the key-additive v4 regeneration runs once, on the
        # merged branch; contract §5.0.8 rule 2): the M4 keys must carry their switch-off values and are
        # compared after tools/regen_conformance.py's strip_new_keys
        actual, problems = _regen_module().strip_new_keys(actual)
        assert not problems, problems
    mismatches = compare_documents(expected, actual, name)
    if mismatches:
        shown = mismatches[:MAX_REPORTED]
        more = f"\n... ({len(mismatches) - MAX_REPORTED} more)" if len(mismatches) > MAX_REPORTED else ""
        pytest.fail(f"conformance case {name!r} ({len(mismatches)} mismatch(es)):\n  " + "\n  ".join(shown) + more
                    + "\n(regenerate deliberately with tools/regen_conformance.py --reason '...')")


# --------------------------------------------------------------------------- the comparator is not vacuous
def test_comparator_detects_drift_of_each_kind():
    name = "example_basic"
    doc = load_expected(name)
    assert compare_documents(doc, json.loads(json.dumps(doc))) == []
    # image coordinate beyond 1e-6 mm
    bad = json.loads(json.dumps(doc))
    bad["points"]["crate.v0"]["image"][0] += 2e-6
    assert any(m.startswith("points.crate.v0.image[0]") for m in compare_documents(doc, bad))
    # ... but within it: silent
    ok = json.loads(json.dumps(doc))
    ok["points"]["crate.v0"]["image"][0] += 5e-7
    ok["shadows"][0]["polygons"][0][0][1] -= 5e-7
    assert compare_documents(doc, ok) == []
    # world coordinate beyond 1e-9 relative
    bad = json.loads(json.dumps(doc))
    bad["points"]["crate.v0"]["world"][2] += 1e-7
    assert any(m.startswith("points.crate.v0.world[2]") for m in compare_documents(doc, bad))
    # a boolean / string / structure change
    bad = json.loads(json.dumps(doc))
    bad["edges"][0]["back"] = not bad["edges"][0]["back"]
    bad["shadows"][0]["outline"].pop()
    msgs = compare_documents(doc, bad)
    assert any(m.startswith("edges[0].back") for m in msgs) and any(m.startswith("shadows[0].outline") for m in msgs)
    # warning codes
    bad = json.loads(json.dumps(doc))
    bad["warnings"].append({"code": "CONIC_SAMPLED", "ids": ["pillar"], "message": "x"})
    assert any(m.startswith("warnings: code set") for m in compare_documents(doc, bad))
    # an integer written for an integral float is still the same number
    same = json.loads(json.dumps(doc))
    same["canvas_mm"] = [273, 182]
    assert compare_documents(doc, same) == []


def test_image_path_classification():
    assert is_image_path(("points", "a.v0", "image", 0))
    assert is_image_path(("edges", 3, "segment", 1, 0))
    assert is_image_path(("outlines", 0, "conics", 1, "arcs", 0, "start", 1))
    assert is_image_path(("outlines", 0, "conics", 1, "ellipses", 0, "rx"))
    assert not is_image_path(("outlines", 0, "conics", 1, "arcs", 0, "rotation_deg"))
    assert not is_image_path(("outlines", 0, "conics", 1, "arcs", 0, "theta", 0))
    assert not is_image_path(("outlines", 0, "conics", 1, "circle", "centre", 0))
    assert not is_image_path(("shadows", 0, "conics", 1, "conic", 0, 0))
    assert is_image_path(("construction", "segments", 4, "points", 0, 1))
    assert not is_image_path(("construction", "checks", 0, "point"))
    assert is_image_path(("construction", "checks", 0, "max_error_mm"))
    assert not is_image_path(("points", "a.v0", "world", 0)) and not is_image_path(("points", "a.v0", "depth"))
    assert not is_image_path(("camera", "P", 0, 0)) and is_image_path(("camera", "principal_point", 0))
    assert not is_image_path(("horizon", "line", 0)) and is_image_path(("horizon", "segment", 0, 0))


# --------------------------------------------------------------------------- tools/regen_conformance.py
REGEN = CONFORMANCE.parents[1] / "tools" / "regen_conformance.py"


def run_regen(*argv: str):
    import subprocess
    import sys

    return subprocess.run([sys.executable, str(REGEN), *argv], capture_output=True, text=True,
                          cwd=str(CONFORMANCE.parents[1]), check=False)


def recorded_numpy_version() -> str | None:
    """The NumPy version recorded by the last ``## v<N>`` entry of the changelog that rendered expected
    files (``None`` when absent).  A ``--rules-only`` entry (comparator amendment, contract §5.4.8)
    renders nothing and records no build, so the build of the entry before it still applies."""
    text = (CONFORMANCE / "CHANGELOG.md").read_text(encoding="utf-8")
    entries = re.split(r"^## v\d+ ", text, flags=re.MULTILINE)
    for entry in reversed(entries[1:]):
        m = re.search(r"^- build: .*numpy (\S+)", entry, flags=re.MULTILINE)
        if m:
            return m.group(1)
    return None


def test_regen_tool_exit_codes_match_its_docstring(tmp_path):
    """The documented contract: 2 for a usage error (argparse), 1 for an unknown case or a render
    failure, 0 on success; ``--dry-run`` writes nothing and reports no drift for the committed set.

    Expected files are bit-exact only for the interpreter / NumPy build recorded in the changelog
    (contract §4): on another build (a different libm rounds a few leaves by ~1e-12) the dry run
    may list drifted cases, and each of them must then still pass the §7.5 tolerances."""
    doc = REGEN.read_text(encoding="utf-8")
    assert "2 for a command-line usage error" in doc and "1 for an unknown ``--case``" in doc
    assert run_regen().returncode == 2                                   # --reason is required
    assert run_regen("--reason", "  ").returncode == 2                   # … and must not be empty
    r = run_regen("--reason", "x", "--case", "no_such_case", "--dry-run")
    assert r.returncode == 1 and "unknown case(s): no_such_case" in r.stderr
    before = {p.name: p.read_bytes() for p in EXPECTED.glob("*.json")}
    changelog = (CONFORMANCE / "CHANGELOG.md").read_bytes()
    r = run_regen("--reason", "check", "--dry-run")
    assert r.returncode == 0, r.stderr
    m = re.match(r"would change: (\d+) of (\d+) case\(s\)(?: \((.*)\))?", r.stdout.strip())
    assert m and int(m.group(2)) == len(case_names()), r.stdout
    drifted = m.group(3).split(", ") if m.group(3) else []
    assert len(drifted) == int(m.group(1))
    # inside the M4 worktree the pre-v4 expected files drift key-additively (the M4 keys are added at the
    # v4 regeneration on the merged branch, contract §5.0.8 rule 2): such drift is checked after
    # strip_new_keys, any other drift fails as before
    pre_v4 = {name for name in drifted if "hidden_lines" not in load_expected(name)}
    if recorded_numpy_version() == numpy.__version__:
        assert not set(drifted) - pre_v4, f"expected files drift on the recorded NumPy build: {r.stdout}"
    for name in drifted:
        actual = render_case(name)
        if name in pre_v4:
            actual, problems = _regen_module().strip_new_keys(actual)
            assert not problems, (name, problems)
        assert compare_documents(load_expected(name), actual, name) == [], name
    assert {p.name: p.read_bytes() for p in EXPECTED.glob("*.json")} == before
    assert (CONFORMANCE / "CHANGELOG.md").read_bytes() == changelog


def test_curved_shadow_polygon_is_sampled_in_stage_a_as_the_contract_says():
    """Contract §2.6 (b) / §3.1: the filled shadow polygon of a curved object is sampled in stage A
    (64 per full circle, minimum 8) while its exact boundary stays in ``shadows[].conics``; the
    conic drawables are sampled only in stage C.  The frozen curved example is the witness."""
    arch = (CONFORMANCE.parents[1] / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "never in stage A/B geometry" not in arch
    assert "sampled with the same rule in stage A" in arch
    scene = load_scene(str(CASES / "example_curved_demo.json"))
    stage_a = castplane.shadow_geometry(scene)
    curved = [o for o in stage_a["objects"] if o.get("curved")]
    assert curved
    for obj in curved:
        # contract §5.1.4 (M4): per-(receiver, light) records live in obj["curved"][<receiver id>][<light id>]
        for lid, cd in ((lid, cd) for per in obj["curved"].values() for lid, cd in per.items()):
            if cd["polygon"] is None:
                continue
            verts = cd["polygon"]["vertices"]
            assert len(verts) >= 8, (obj["id"], lid, len(verts))
    doc = castplane.render(scene)["geometry"]
    curved_ids = {o["id"] for o in curved}
    for sh in doc["shadows"]:
        if sh["object"] in curved_ids and sh["polygons"]:
            assert len(sh["polygons"][0]) >= 8 and any(c["map"] == "shadow" for c in sh["conics"])


# --------------------------------------------------------------------------- rules.json (contract §5.4.8, set v3)
def test_rules_json_matches_constants():
    """``tests/conformance/rules.json`` is the single source of the comparator constants shared with the
    TypeScript runner; the constants of this module must equal it (contract §5.4.8, §5.0.8)."""
    assert set(RULES) == {"image_tol_mm", "rel_tol", "mm_keys", "drawable_containers", "arc_non_mm", "mm_key_paths",
                          "runs_rule", "int_keys", "max_reported", "case_overrides"}
    assert RULES["image_tol_mm"] == IMAGE_TOL_MM and RULES["rel_tol"] == REL_TOL
    assert RULES["max_reported"] == MAX_REPORTED
    assert set(RULES["mm_keys"]) == _MM_KEYS and len(RULES["mm_keys"]) == len(_MM_KEYS)
    assert tuple(RULES["drawable_containers"]) == _DRAWABLE_CONTAINERS
    assert set(RULES["arc_non_mm"]) == _ARC_NON_MM and len(RULES["arc_non_mm"]) == len(_ARC_NON_MM)
    assert tuple(tuple(p) for p in RULES["mm_key_paths"]) == _MM_KEY_PATHS
    assert tuple(RULES["int_keys"]) == _INT_KEYS
    names = set(case_names())
    for case, entries in RULES["case_overrides"].items():
        assert case in names, f"case_overrides names an unknown case {case!r}"
        assert entries, case
        for entry in entries:
            assert set(entry) == {"paths", "abs_tol", "reason"}, (case, sorted(entry))
            assert entry["paths"] and all(isinstance(p, list) and p and all(isinstance(k, str) for k in p)
                                          for p in entry["paths"]), case
            assert isinstance(entry["abs_tol"], float) and entry["abs_tol"] > 0.0, case
            assert isinstance(entry["reason"], str) and entry["reason"].strip(), case


def test_case_override_values_are_the_v3_amendment():
    """Set v3 (contract §5.4.8): the four ``direction`` leaves of ``degenerate_cylinder_cap_at_light_height``
    are compared at 1e-6 absolute, nothing else is overridden, and the overridden leaves exist."""
    assert sorted(RULES["case_overrides"]) == ["degenerate_cylinder_cap_at_light_height"]
    (paths, abs_tol), = case_overrides("degenerate_cylinder_cap_at_light_height")
    assert abs_tol == 1e-6
    assert paths == (("shadows", "*", "loops", "*", "*", "direction"), ("shadows", "*", "outline", "*", "direction"))
    doc = load_expected("degenerate_cylinder_cap_at_light_height")
    sh = doc["shadows"][0]
    assert sh["loops"][0][30]["direction"][1] == sh["outline"][30]["direction"][1] == 0.5052007436053615
    assert sh["loops"][0][31]["direction"][1] == sh["outline"][31]["direction"][1]


def test_case_override_scope():
    """The override applies only to the named case and only below the named paths; everything else
    keeps the default rules (contract §5.4.8, §5.4.13)."""
    name = "degenerate_cylinder_cap_at_light_height"
    doc = load_expected(name)
    # 1.5e-9 absolute (the measured sensitivity) on a direction leaf: beyond 1e-9 relative for |d| ~ 0.5
    drift = json.loads(json.dumps(doc))
    drift["shadows"][0]["loops"][0][30]["direction"][1] += 1.5e-9
    drift["shadows"][0]["outline"][30]["direction"][1] += 1.5e-9
    drift["shadows"][0]["loops"][0][31]["direction"][1] -= 4e-7
    drift["shadows"][0]["outline"][31]["direction"][1] -= 4e-7
    assert compare_documents(doc, drift, name) == []
    msgs = compare_documents(doc, drift)                                  # no case name: default rules
    assert len(msgs) == 4 and all("1e-09 relative" in m for m in msgs), msgs
    assert any(m.startswith("shadows[0].loops[0][30].direction[1]") for m in msgs)
    assert any(m.startswith("shadows[0].outline[31].direction[1]") for m in msgs)
    assert len(compare_documents(doc, drift, "example_basic")) == 4      # another case: default rules
    # beyond the override tolerance: reported with the override in the message
    bad = json.loads(json.dumps(doc))
    bad["shadows"][0]["outline"][30]["direction"][0] += 2e-6
    (msg,) = compare_documents(doc, bad, name)
    assert msg.startswith("shadows[0].outline[30].direction[0]") and "case override" in msg
    # other numbers of the same case keep 1e-9 relative / 1e-6 mm
    bad = json.loads(json.dumps(doc))
    bad["shadows"][0]["polygons"][0][0][0] += 2e-6
    first = next(iter(bad["points"]))
    bad["points"][first]["world"][0] += 1e-7
    msgs = compare_documents(doc, bad, name)
    assert len(msgs) == 2 and any(m.startswith("shadows[0].polygons[0][0][0]") for m in msgs)
    assert any(m.startswith(f"points.{first}.world[0]") for m in msgs)
    # non-numbers below an overridden path are never relaxed
    bad = json.loads(json.dumps(doc))
    bad["shadows"][0]["loops"][0][30]["direction"].append(0.0)
    assert compare_documents(doc, bad, name) != []
    # the same leaf position in another case with a direction vertex uses 1e-9 relative
    for other in case_names():
        if other == name:
            continue
        odoc = load_expected(other)
        hit = next(((i, j, k) for i, sh in enumerate(odoc["shadows"]) for j, loop in enumerate(sh["loops"])
                    for k, e in enumerate(loop) if isinstance(e, dict) and "direction" in e), None)
        if hit is None:
            continue
        i, j, k = hit
        moved = json.loads(json.dumps(odoc))
        moved["shadows"][i]["loops"][j][k]["direction"][0] += 1e-7
        assert compare_documents(odoc, moved, other) != [] and compare_documents(odoc, moved, name) == []
        break
    else:  # pragma: no cover - the set has unbounded shadows (spec §5.7 rows 2 / 4)
        pytest.fail("no other case with a direction vertex")


def test_path_prefix_rule():
    assert path_has_prefix(("construction", "segments", 4, "points", 0, 1), ("construction", "segments", "*", "points"))
    assert not path_has_prefix(("construction", "segments", 4), ("construction", "segments", "*", "points"))
    assert not path_has_prefix(("construction", "checks", 0, "points"), ("construction", "segments", "*", "points"))
    assert path_has_prefix(("shadows", 2, "outline", 7, "direction", 0), ("shadows", "*", "outline", "*", "direction"))
    assert case_overrides(None) == [] and case_overrides("example_basic") == []


def _regen_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("regen_conformance_under_test", REGEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_rules_json_is_versioned_in_the_changelog():
    """Every comparator change goes through ``regen_conformance.py --rules-only`` (contract §5.4.8): the
    rules recorded by the last such changelog entry equal ``rules.json``, and v3 is that amendment."""
    regen = _regen_module()
    text = (CONFORMANCE / "CHANGELOG.md").read_text(encoding="utf-8")
    version, recorded = regen.recorded_rules(text)
    assert version is not None and version >= 3
    assert recorded == RULES, "rules.json changed without a --rules-only changelog entry"
    v3 = re.split(r"^## v\d+ ", text, flags=re.MULTILINE)[3]
    assert "comparator amendment, no expected file changed" in v3
    assert "degenerate_cylinder_cap_at_light_height" in v3 and "- build:" not in v3


def test_regen_rules_only_mode(tmp_path, monkeypatch, capsys):
    """``--rules-only`` versions a rules change without rendering or touching ``expected/``; an unchanged
    file is refused (exit 1), ``--case`` is a usage error (exit 2), ``--dry-run`` writes nothing."""
    regen = _regen_module()
    rules_file, changelog = tmp_path / "rules.json", tmp_path / "CHANGELOG.md"
    monkeypatch.setattr(regen, "RULES_FILE", rules_file)
    monkeypatch.setattr(regen, "CHANGELOG", changelog)

    def no_render(name):  # pragma: no cover - must never be called in --rules-only mode
        raise AssertionError("--rules-only rendered a case")

    monkeypatch.setattr(regen, "render_case", no_render)
    assert regen.main(["--reason", "x", "--rules-only"]) == 1                     # no rules.json
    rules_file.write_text("[1, 2]", encoding="utf-8")
    assert regen.main(["--reason", "x", "--rules-only"]) == 1                     # not an object
    changelog.write_text("# Conformance set changelog\n\n## v1 — 2026-01-01\n\n- reason: r\n"
                         "- build: Python 3.13.0, numpy 2.0.0\n\n", encoding="utf-8")
    rules_file.write_text(json.dumps({"rel_tol": 1e-9, "mm_keys": ["image"]}), encoding="utf-8")
    capsys.readouterr()
    assert regen.main(["--reason", "first", "--rules-only", "--dry-run"]) == 0
    assert "would record v2" in capsys.readouterr().out and "- rules" not in changelog.read_text(encoding="utf-8")
    assert regen.main(["--reason", "first", "--rules-only"]) == 0
    text = changelog.read_text(encoding="utf-8")
    assert "## v2 — " in text and "- rules diff (rules.json created):" in text
    assert regen.recorded_rules(text) == (2, {"rel_tol": 1e-9, "mm_keys": ["image"]})
    assert regen.main(["--reason", "again", "--rules-only"]) == 1                 # unchanged since v2
    assert changelog.read_text(encoding="utf-8") == text
    rules_file.write_text(json.dumps({"rel_tol": 1e-8, "mm_keys": ["image", "segment"], "int_keys": []}),
                          encoding="utf-8")
    assert regen.main(["--reason", "second", "--rules-only"]) == 0
    text = changelog.read_text(encoding="utf-8")
    entry = re.split(r"^## v\d+ ", text, flags=re.MULTILINE)[-1]
    assert "- rules diff (against the rules recorded in v2):" in entry
    assert "added `int_keys`" in entry and "changed `mm_keys`: + `\"segment\"`" in entry
    assert "changed `rel_tol`: `1e-09` -> `1e-08`" in entry
    assert regen.recorded_rules(text)[0] == 3
    with pytest.raises(SystemExit) as exc:
        regen.main(["--reason", "x", "--rules-only", "--case", "example_basic"])
    assert exc.value.code == 2


# --------------------------------------------------------------------------- M4 (contract §5.0.8, §5.1.11)
M4_CASES = ("wall_and_ground", "wall_and_ground_hidden", "receiver_unlit_wall", "receiver_directional_wall",
            "fold_curved_cylinder", "bounded_default_receiver", "hidden_lines_curved_unbounded",
            "hidden_lines_vp_in_canvas", "concave_prism_on_plate")


def test_runs_rule_values_and_paths():
    """``rules.json["runs_rule"]`` is the §5.0.8 literal; ``runs_tol`` finds the number's key inside a runs
    entry wherever the runs list sits (edges, generators, terminator segments, conic entries, polygon_edges)."""
    assert _RUNS_RULE == {"mm_abs": 0.05, "param_abs": 1e-3, "param_keys": ["s", "t", "theta"],
                          "exact_keys": ["visible", "interval"]}
    assert runs_tol(("edges", 12, "runs", 1, "mm", 0)) == 0.05
    assert runs_tol(("edges", 12, "runs", 1, "s", 1)) == 1e-3 == runs_tol(("edges", 0, "runs", 0, "t", 0))
    assert runs_tol(("outlines", 0, "conics", 1, "runs", 2, "theta", 0)) == 1e-3
    assert runs_tol(("form_shadow", 0, "terminator", 0, "runs", 0, "interval")) == 0.0
    assert runs_tol(("shadows", 3, "polygon_edges", 0, 2, "runs", 1, "mm", 1)) == 0.05
    assert runs_tol(("shadows", 3, "polygons", 0, 2, 1)) is None and runs_tol(("edges", 0, "segment", 0, 0)) is None
    assert is_image_path(("shadows", 0, "conics", 0, "hidden_polylines", 0, 3, 1))
    assert is_image_path(("construction", "per_receiver", "wall", "segments", 2, "points", 0, 1))
    assert not is_image_path(("construction", "per_receiver", "wall", "checks", 0, "point", 0))


def test_runs_rule_tolerances_on_the_hidden_case():
    """The comparator applies the runs rule to ``wall_and_ground_hidden``: 0.05 mm on ``mm``, 1e-3 on ``s`` /
    ``t`` / ``theta``, exact ``visible`` / ``interval`` / run count; ``hidden_polylines`` at 1e-6 mm."""
    name = "wall_and_ground_hidden"
    doc = load_expected(name)
    i = next(k for k, e in enumerate(doc["edges"]) if (e["from"], e["to"]) == ("wall.b0", "wall.b1"))
    runs = doc["edges"][i]["runs"]
    assert [r["visible"] for r in runs] == [True, False, True]
    assert abs(runs[0]["s"][1] - 23 / 60) <= 1e-3 and abs(runs[1]["s"][1] - 37 / 60) <= 1e-3
    assert abs(runs[0]["mm"][1] - 85.5415) <= 0.05 and abs(runs[1]["mm"][1] - 137.6102) <= 0.05
    ok = json.loads(json.dumps(doc))
    ok["edges"][i]["runs"][1]["mm"][0] += 0.04
    ok["edges"][i]["runs"][1]["s"][0] += 9e-4
    ok["edges"][i]["runs"][1]["t"][1] -= 9e-4
    assert compare_documents(doc, ok, name) == []
    bad = json.loads(json.dumps(doc))
    bad["edges"][i]["runs"][1]["mm"][0] += 0.06
    bad["edges"][i]["runs"][2]["s"][0] += 2e-3
    msgs = compare_documents(doc, bad, name)
    assert len(msgs) == 2 and all("runs rule" in m for m in msgs), msgs
    bad = json.loads(json.dumps(doc))
    bad["edges"][i]["runs"][1]["visible"] = True
    bad["edges"][i]["runs"].pop()
    assert len(compare_documents(doc, bad, name)) == 1          # the run count (list length) is exact
    # conic runs: theta at 1e-3 (overrides arc_non_mm), interval exact
    cdoc = load_expected("hidden_lines_curved_unbounded")
    hit = next((path, c) for path, c in _conic_entries(cdoc) if c["runs"])
    path, entry = hit
    moved = json.loads(json.dumps(cdoc))
    target = _get(moved, path)
    target["runs"][0]["theta"][1] += 5e-4
    assert compare_documents(cdoc, moved, "hidden_lines_curved_unbounded") == []
    target["runs"][0]["interval"] += 1
    assert any("runs rule" in m for m in compare_documents(cdoc, moved, "hidden_lines_curved_unbounded"))
    assert isinstance(entry["runs"][0]["interval"], int)
    hidden_poly = next((p, c) for p, c in _conic_entries(cdoc) if c["hidden_polylines"])
    moved = json.loads(json.dumps(cdoc))
    _get(moved, hidden_poly[0])["hidden_polylines"][0][0][0] += 2e-6
    (msg,) = compare_documents(cdoc, moved, "hidden_lines_curved_unbounded")
    assert "hidden_polylines" in msg and "1e-06 mm" in msg


def _conic_entries(doc):
    for i, o in enumerate(doc.get("outlines", [])):
        for j, c in enumerate(o["conics"]):
            yield ("outlines", i, "conics", j), c
    for i, s in enumerate(doc.get("shadows", [])):
        for j, c in enumerate(s["conics"]):
            yield ("shadows", i, "conics", j), c
    for i, f in enumerate(doc.get("form_shadow", [])):
        for j, c in enumerate(f["terminator"]):
            if "segment" not in c:
                yield ("form_shadow", i, "terminator", j), c


def _get(doc, path):
    for key in path:
        doc = doc[key]
    return doc


def test_m4_cases_cover_the_required_sources():
    """§5.0.8: after M4 the set holds ``RECEIVER_UNLIT``, a bounded receiver, an anchor-rule case and a ``w = 0``
    HLR endpoint case; every M4 case is present, and the hidden-line cases carry partial runs."""
    from castplane import hidden

    names = set(case_names())
    assert set(M4_CASES) <= names, sorted(set(M4_CASES) - names)
    codes = {w["code"] for n in M4_CASES for w in load_expected(n)["warnings"]}
    assert "RECEIVER_UNLIT" in codes
    assert any(r["bounds"] is not None for n in M4_CASES for r in load_expected(n)["receivers"])
    assert load_expected("bounded_default_receiver")["receivers"][0]["bounds"] is not None
    assert ("SHADOW_VP_AT_INFINITY", ("sun", "wall")) in {
        (w["code"], tuple(w["ids"])) for w in load_expected("receiver_directional_wall")["warnings"]}
    # the anchor rule fires in stage A of concave_prism_on_plate, and its polygon is the whole plate
    scene = load_scene(CASES / "concave_prism_on_plate.json")
    A = castplane.shadow_geometry(scene)
    assert any(isinstance(s, tuple) and s[-1] == "anchor"
               for rec in A["shadows"] for loop in rec["loops"] for s in loop["sources"])
    # a drawn shadow-polygon edge with a w = 0 endpoint inside the extended canvas, hidden lines on
    scene = load_scene(CASES / "hidden_lines_vp_in_canvas.json")
    assert scene["output"]["hidden_lines"] is True
    A = castplane.shadow_geometry(scene)
    B = castplane.project_scene(scene, A)
    pts, _ids = hidden.clip_polygon_4d(B["camera"], A["shadows"][0]["loops"][0]["vertices"])
    assert int(numpy.sum(pts[:, 3] == 0.0)) >= 1
    for n in ("wall_and_ground_hidden", "hidden_lines_curved_unbounded", "hidden_lines_vp_in_canvas"):
        doc = load_expected(n)
        assert doc["hidden_lines"] is True
        records = (list(doc["edges"]) + [c for _p, c in _conic_entries(doc)]
                   + [r for s in doc["shadows"] for poly in s["polygon_edges"] for r in poly])
        assert any(r["visibility"] == "partial" and r["runs"] for r in records), n
    for n in set(M4_CASES) - {"wall_and_ground_hidden", "hidden_lines_curved_unbounded", "hidden_lines_vp_in_canvas"}:
        assert load_expected(n)["hidden_lines"] is False, n


# --------------------------------------------------------------------------- M5: mesh cases (contract §5.2.9, §5.2.11)
def test_cases_are_post_expansion_scenes_with_inline_mesh_data():
    """Conformance cases are post-expansion scenes (contract §5.0.2): a ``mesh`` object carries its
    geometry inline as ``data`` and never a ``path``; loader-only types (``step``) never appear.  The
    TypeScript port reads ``cases/`` without any loader."""
    seen = 0
    for name in case_names():
        raw = json.loads((CASES / f"{name}.json").read_text(encoding="utf-8"))
        for i, o in enumerate(raw["objects"]):
            assert o.get("type") != "step", f"{name}: objects[{i}] is a loader-only step object"
            if o.get("type") == "mesh":
                seen += 1
                assert "data" in o and "path" not in o and "node" not in o, f"{name}: objects[{i}] must use inline data"
    assert seen >= 3


def test_welded_mesh_box_expected_equals_the_parametric_box_but_for_the_mesh_keys():
    """contract §5.2.12: the expected file of ``mesh_box_welded_triangulated`` equals
    ``analytic_unit_box_point_light_overhead`` exactly except for the two mesh-only keys on its 12 edges."""
    mesh = load_expected("mesh_box_welded_triangulated")
    assert len(mesh["edges"]) == 12 and all(e.pop("smooth") is False for e in mesh["edges"])
    for e in mesh["edges"]:
        e.pop("camera_silhouette")
    assert mesh == load_expected("analytic_unit_box_point_light_overhead")


# --------------------------------------------------------------------------- M6: multi-light documents
def test_comparator_on_a_multi_light_document():
    """The multi-light keys (contract §5.3.5) go through the comparator: ``umbra[].polygons`` is an mm key
    (``polygons``), ``silhouette_lights`` / ``umbra[].lights`` are compared exactly, a missing M6 key is a key
    mismatch; the ``constructions`` mm paths come from ``rules.json`` (v6)."""
    from tests.test_multilight import acceptance_scene
    doc = json.loads(dumps(castplane.render(castplane.load_scene(acceptance_scene()))["geometry"]))
    assert compare_documents(doc, json.loads(json.dumps(doc))) == []
    assert is_image_path(("umbra", 0, "polygons", 2, 1, 0))
    ok = json.loads(json.dumps(doc))
    ok["umbra"][0]["polygons"][0][1][0] += 5e-7
    assert compare_documents(doc, ok) == []
    bad = json.loads(json.dumps(doc))
    bad["umbra"][0]["polygons"][0][1][0] += 2e-6
    assert any(m.startswith("umbra[0].polygons[0][1][0]") for m in compare_documents(doc, bad))
    bad = json.loads(json.dumps(doc))
    bad["umbra"][0]["lights"].reverse()
    k = next(i for i, e in enumerate(doc["edges"]) if e["silhouette_lights"] == ["west"])
    bad["edges"][k]["silhouette_lights"] = ["east"]
    msgs = compare_documents(doc, bad)
    assert any(m.startswith("umbra[0].lights[0]") for m in msgs)
    assert any(m.startswith(f"edges[{k}].silhouette_lights[0]") for m in msgs)
    bad = json.loads(json.dumps(doc))
    del bad["form_shadow_core"]
    assert any("key mismatch" in m and "form_shadow_core" in m for m in compare_documents(doc, bad))


M6_CASES = ("multilight_two_point_symmetric_box", "multilight_point_and_directional_curved",
            "multilight_three_lights_concave_prism", "multilight_second_light_inactive")
#: v7 (final review fixes): the multi-light case added with the umbra bridging fix m6-umbra#0
V7_MULTI_LIGHT_CASES = ("multilight_mesh_fallback_shared_edges",)


def test_constructions_paths_are_image_paths():
    """contract §5.3.5 / §5.3.10: ``constructions.*.segments[].points`` and its ``per_receiver`` form are canvas mm
    (through ``rules.json``); the other numbers of a construction block keep their rules."""
    assert is_image_path(("constructions", "east", "segments", 0, "points", 0, 1))
    assert is_image_path(("constructions", "lamp", "per_receiver", "wall", "segments", 3, "points", 1, 0))
    assert is_image_path(("constructions", "east", "light_point", 0))          # an mm key already
    assert not is_image_path(("constructions", "east", "rays", 0, "P", 0))     # world coordinates stay relative
    doc = load_expected("multilight_two_point_symmetric_box")
    bad = json.loads(json.dumps(doc))
    seg = bad["constructions"]["east"]["segments"][0]["points"][0]
    seg[0] += 2e-6
    assert any(m.startswith("constructions.east.segments[0].points[0][0]") for m in compare_documents(doc, bad))
    seg[0] -= 1.5e-6
    assert compare_documents(doc, bad) == []


def test_m6_cases_are_multi_light_documents():
    """The four v6 cases (contract §5.3.10) carry the M6 keys; every single-light case carries none (§5.3.5)."""
    m6_keys = ("constructions", "umbra", "form_shadow_core")
    for name in case_names():
        doc = load_expected(name)
        lights = load_scene(CASES / f"{name}.json")["lights"]
        multi = len(lights) >= 2
        assert all((k in doc) == multi for k in m6_keys), name
        assert multi == (name in M6_CASES or name in V7_MULTI_LIGHT_CASES), name
        if multi:
            assert doc["construction"] == doc["constructions"][lights[0]["id"]], name
            assert all("light" in e for e in doc["form_shadow"]) and all("silhouette_lights" in e for e in doc["edges"])
    inactive = load_expected("multilight_second_light_inactive")
    assert {(w["code"], tuple(w["ids"])) for w in inactive["warnings"]} == {("LIGHT_BELOW_RECEIVER", ("under",))}
    assert inactive["umbra"] == [{"receiver": "ground", "lights": ["west"], "polygons": []}]
    three = load_expected("multilight_three_lights_concave_prism")
    assert three["umbra"][0]["lights"] == ["light", "light_b", "light_c"] and len(three["umbra"][0]["polygons"]) > 0
    curved = load_expected("multilight_point_and_directional_curved")
    assert "ball.sil.0.lamp" in curved["points"] and "ball.sil.0.sun.shadow.sun" in curved["points"]
    assert sorted(curved["constructions"]) == ["lamp", "sun"]


def test_acceptance_expected_file_holds_the_hand_values():
    """contract §5.3.10: the expected file of ``multilight_two_point_symmetric_box`` holds the hand-computed
    umbra pieces (index-wise within 1e-6 mm), their areas and the edge light lists."""
    doc = load_expected("multilight_two_point_symmetric_box")
    assert doc["warnings"] == [] and sorted(doc["constructions"]) == ["east", "west"]
    (entry,) = doc["umbra"]
    assert entry["receiver"] == "ground" and entry["lights"] == ["west", "east"]
    a, b = 25.753937681885635, 22.944417207498113
    hand = [[(0, -19.444444444444443), (a, -14.285714285714285), (-a, -14.285714285714285)],
            [(-a, -14.285714285714285), (a, -14.285714285714285), (b, 12.727272727272727), (-b, 12.727272727272727)],
            [(-b, 12.727272727272727), (b, 12.727272727272727), (0, 16.666666666666664)]]
    assert len(entry["polygons"]) == 3
    areas = []
    for got, want in zip(entry["polygons"], hand):
        assert len(got) == len(want)
        for p, q in zip(got, want):
            assert abs(p[0] - q[0]) <= IMAGE_TOL_MM and abs(p[1] - q[1]) <= IMAGE_TOL_MM, (got, want)
        areas.append(0.5 * sum(got[i][0] * got[(i + 1) % len(got)][1] - got[(i + 1) % len(got)][0] * got[i][1]
                               for i in range(len(got))))
    for x, y in zip(areas, (132.85761502560047, 1315.4880281807557, 90.38709809014404)):
        assert x == pytest.approx(y, rel=1e-9)
    assert sum(areas) == pytest.approx(1538.7327412965, rel=1e-6)
    lights = sorted(tuple(e["silhouette_lights"]) for e in doc["edges"])
    assert lights.count(("west", "east")) == 2 and lights.count(("west",)) == 4 and lights.count(("east",)) == 4
    assert lights.count(()) == 2 and sum(e["silhouette"] for e in doc["edges"]) == 10
    (core,) = doc["form_shadow_core"]
    assert core["object"] == "cube" and len(core["faces"]) == 3
    assert [(e["light"], len(e["faces"])) for e in doc["form_shadow"]] == [("west", 4), ("east", 4)]


def test_three_light_case_pieces_are_stable_under_rigid_motions():
    """Why ``multilight_three_lights_concave_prism`` lifts its casters (ARCHITECTURE §5.3 implementation notes):
    rigid motions of the whole scene change every input by rounding only, and the case's umbra pieces must then
    agree index-wise within the 1e-6 mm conformance tolerance (the piece count included), so that the case is
    comparable piece by piece on another build and in the TypeScript runner."""
    from tests.test_multilight import rigid
    scene = json.loads((CASES / "multilight_three_lights_concave_prism.json").read_text(encoding="utf-8"))
    scene.pop("description")
    want = load_expected("multilight_three_lights_concave_prism")["umbra"][0]["polygons"]
    for angle, shift in ((37.0, (2.5, -1.25)), (-120.0, (-4.0, 3.0)), (180.0, (0.0, 0.0)), (90.0, (1.0, 1.0))):
        got = castplane.render(load_scene(rigid(scene, angle, shift)))["geometry"]["umbra"][0]["polygons"]
        assert [len(p) for p in got] == [len(p) for p in want], (angle, shift)
        assert max(abs(x - y) for p, q in zip(got, want) for u, v in zip(p, q) for x, y in zip(u, v)) <= 1e-9
