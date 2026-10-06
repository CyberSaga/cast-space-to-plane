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
"""

from __future__ import annotations

import json
import math
import pathlib

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
#: Spec §5.7 rows 1-6 must each be represented by at least one case (contract §4).
_DEGENERATE_ROW_CODES = ("LIGHT_BEHIND_CAMERA", "LIGHT_POINT_AT_INFINITY", "DIRECTIONAL_HORIZONTAL",
                         "VERTEX_NOT_BELOW_LIGHT", "POINT_BEHIND_CAMERA", "FACE_PARALLEL_TO_LIGHT")


def case_names() -> list[str]:
    return sorted(p.stem for p in CASES.glob("*.json"))


def is_image_path(path: tuple) -> bool:
    """True when the number at ``path`` is an image coordinate / mm length (see the module docstring)."""
    in_drawable = False
    for key in path:
        if key in _MM_KEYS:
            return True
        if key in ("arcs", "ellipses"):
            in_drawable = True
        elif in_drawable and key in _ARC_NON_MM:
            return False
    if in_drawable:
        return True
    if len(path) >= 4 and path[0] == "construction" and path[1] == "segments" and path[3] == "points":
        return True
    return False


def _fmt(path: tuple) -> str:
    out = ""
    for key in path:
        out += f"[{key}]" if isinstance(key, int) else (f".{key}" if out else str(key))
    return out or "<root>"


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _numbers_match(a, b, image: bool) -> bool:
    if not (math.isfinite(a) and math.isfinite(b)):
        return a == b
    if image:
        return abs(a - b) <= IMAGE_TOL_MM
    return abs(a - b) <= REL_TOL * max(1.0, abs(a), abs(b))


def _walk(exp, act, path: tuple, out: list) -> None:
    if len(out) > MAX_REPORTED:
        return
    if _is_number(exp) and _is_number(act):
        image = is_image_path(path)
        if not _numbers_match(float(exp), float(act), image):
            tol = f"{IMAGE_TOL_MM:g} mm" if image else f"{REL_TOL:g} relative"
            out.append(f"{_fmt(path)}: expected {exp!r}, got {act!r} (tolerance {tol})")
        return
    if isinstance(exp, dict) and isinstance(act, dict):
        if set(exp) != set(act):
            missing, extra = sorted(set(exp) - set(act)), sorted(set(act) - set(exp))
            out.append(f"{_fmt(path)}: key mismatch (missing {missing}, unexpected {extra})")
            return
        for key in sorted(exp):
            _walk(exp[key], act[key], path + (key,), out)
        return
    if isinstance(exp, list) and isinstance(act, list):
        if len(exp) != len(act):
            out.append(f"{_fmt(path)}: expected a list of {len(exp)} entries, got {len(act)}")
            return
        for i, (e, a) in enumerate(zip(exp, act)):
            _walk(e, a, path + (i,), out)
        return
    if type(exp) is not type(act) or exp != act:
        out.append(f"{_fmt(path)}: expected {exp!r}, got {act!r} (exact)")


def compare_documents(expected: dict, actual: dict) -> list[str]:
    """List of human-readable mismatches between two JSON-native §6.2 documents (empty = conformant)."""
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
    _walk(exp_rest, act_rest, (), out)
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
    mismatches = compare_documents(load_expected(name), render_case(name))
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


def test_regen_tool_exit_codes_match_its_docstring(tmp_path):
    """The documented contract: 2 for a usage error (argparse), 1 for an unknown case or a render
    failure, 0 on success; ``--dry-run`` writes nothing and reports no drift for the committed set."""
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
    assert r.stdout.startswith("would change: 0 of"), r.stdout
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
        for lid, cd in obj["curved"].items():
            if cd["polygon"] is None:
                continue
            verts = cd["polygon"]["vertices"]
            assert len(verts) >= 8, (obj["id"], lid, len(verts))
    doc = castplane.render(scene)["geometry"]
    curved_ids = {o["id"] for o in curved}
    for sh in doc["shadows"]:
        if sh["object"] in curved_ids and sh["polygons"]:
            assert len(sh["polygons"][0]) >= 8 and any(c["map"] == "shadow" for c in sh["conics"])
