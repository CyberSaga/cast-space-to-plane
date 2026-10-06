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
_MM_KEYS = frozenset({"image", "segment", "polygons", "polylines", "light_point", "shadow_vp", "v_mm",
                      "vanishing_points", "principal_point", "canvas_mm", "max_error_mm"})
#: Inside ``arcs`` / ``ellipses`` entries these keys are angles / flags, not mm.
_ARC_NON_MM = frozenset({"rotation_deg", "theta", "large_arc", "sweep"})
#: Containers whose entries are drawables in canvas mm (except the :data:`_ARC_NON_MM` keys).
_DRAWABLE_CONTAINERS = ("arcs", "ellipses")
#: Path prefixes below which every number is in canvas mm (``*`` matches any one list index or key).
_MM_KEY_PATHS = (("construction", "segments", "*", "points"),)
#: The only keys whose numbers the writer emits as integers (``INT_KEYS`` of contract §5.4.5).
_INT_KEYS = ("large_arc", "sweep")
#: The comparator constants shared with the TypeScript runner (contract §5.4.8, §5.0.8).
RULES_FILE = CONFORMANCE / "rules.json"
RULES = json.loads(RULES_FILE.read_text(encoding="utf-8"))
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
        if not _numbers_match(float(exp), float(act), image, abs_tol):
            if abs_tol is not None:
                tol = f"{abs_tol:g} absolute, case override"
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
    for name in case_names():
        scene = load_scene(CASES / f"{name}.json")
        kinds.update(o["type"] for o in scene["objects"])
        lights.update(lt["type"] for lt in scene["lights"])
        forms.add("target" if "target" in scene["camera"] else "yaw_pitch")
        codes.update(w["code"] for w in load_expected(name)["warnings"])
    assert set(_DEGENERATE_ROW_CODES) <= codes, sorted(set(_DEGENERATE_ROW_CODES) - codes)
    assert kinds == set(OBJECT_TYPES) and lights == set(LIGHT_TYPES) and forms == {"target", "yaw_pitch"}


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
                          "int_keys", "max_reported", "case_overrides"}
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
