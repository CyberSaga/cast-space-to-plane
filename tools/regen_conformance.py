#!/usr/bin/env python3
"""Regenerate the expected outputs of the conformance set (spec §7.5; contract §4).

    python3 tools/regen_conformance.py --reason "why the expected files change" [--case NAME ...]

Every ``tests/conformance/cases/<name>.json`` scene is rendered with
``castplane.render`` and its §6.2 geometry document is written to
``tests/conformance/expected/<name>.json`` with ``castplane.output.geometry_json.dumps``
(the deterministic serialisation of contract §3.1, trailing newline).  With ``--case``
only the named cases are regenerated; a case name without an input file is an error.

``--reason`` is mandatory: the set is versioned (spec §7.5 "測試集版本化，變更需記錄原因"),
so every regeneration appends a dated entry -- the new version number, the list of
regenerated cases and the reason -- to ``tests/conformance/CHANGELOG.md``.  Cases whose
expected file did not change are listed as unchanged in that entry.  ``--dry-run`` renders
and reports which expected files would change without writing anything.

``--rules-only`` records a comparator amendment instead (contract §5.4.8, §5.0.8): a change of
``tests/conformance/rules.json`` -- the comparator constants shared by the Python and the
TypeScript runner -- is a change of the conformance contract, so it gets its own ``## v<N>``
entry ("comparator amendment, no expected file changed") with the rules diff against the rules
recorded by the previous ``--rules-only`` entry and the new rules in full; nothing is rendered
and ``expected/`` is not touched.  It cannot be combined with ``--case``; with ``--dry-run`` it
prints the diff and writes nothing.  ``tests/test_conformance.py`` checks that the rules recorded
by the last such entry equal ``rules.json``, so the comparator cannot change silently.

Exit status: 0 on success; 2 for a command-line usage error (argparse: missing or empty
``--reason``, unknown option, ``--rules-only`` with ``--case``); 1 for an unknown ``--case`` name
or a rendering error, and for ``--rules-only`` when ``rules.json`` is missing, is not a JSON
object or is unchanged since the rules recorded in the changelog.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import platform
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy  # noqa: E402

import castplane  # noqa: E402
from castplane.output.geometry_json import dumps  # noqa: E402

CONFORMANCE = ROOT / "tests" / "conformance"
CASES = CONFORMANCE / "cases"
EXPECTED = CONFORMANCE / "expected"
CHANGELOG = CONFORMANCE / "CHANGELOG.md"
RULES_FILE = CONFORMANCE / "rules.json"

_VERSION_RE = re.compile(r"^## v(\d+) ", re.MULTILINE)
_RULES_RECORD_RE = re.compile(r"^- rules \(tests/conformance/rules\.json at v(\d+)\):\n\n```json\n(.*?)\n```$",
                              re.MULTILINE | re.DOTALL)


def case_names() -> list[str]:
    """Sorted stems of every ``cases/*.json`` file."""
    return sorted(p.stem for p in CASES.glob("*.json"))


def render_case(name: str) -> str:
    """The expected text (geometry JSON + newline) of one case."""
    scene = castplane.load_scene(CASES / f"{name}.json")
    return dumps(castplane.render(scene)["geometry"]) + "\n"


def next_version(text: str) -> int:
    """``1 + max`` of the ``## v<N>`` headings already in the changelog (``1`` when there is none)."""
    versions = [int(m.group(1)) for m in _VERSION_RE.finditer(text)]
    return max(versions, default=0) + 1


def changelog_entry(version: int, date: str, reason: str, changed: list[str], unchanged: list[str],
                    all_cases: bool) -> str:
    lines = [f"## v{version} — {date}", "", f"- reason: {reason}",
             f"- build: Python {platform.python_version()}, numpy {numpy.__version__}"]
    scope = "all cases" if all_cases else "selected cases"
    lines.append(f"- regenerated ({scope}, {len(changed)} changed): " + (", ".join(changed) if changed else "none"))
    if unchanged:
        lines.append(f"- unchanged: {', '.join(unchanged)}")
    return "\n".join(lines) + "\n\n"


def recorded_rules(text: str):
    """``(version, rules)`` of the last rules snapshot in the changelog text, ``(None, None)`` when no
    ``--rules-only`` entry exists yet."""
    found = list(_RULES_RECORD_RE.finditer(text))
    if not found:
        return None, None
    m = found[-1]
    return int(m.group(1)), json.loads(m.group(2))


def _rules_text(rules) -> str:
    return json.dumps(rules, sort_keys=True, ensure_ascii=False)


def rules_diff(old, new, prefix: str = "") -> list[str]:
    """Human-readable differences between two rules objects: keys added / removed / changed, recursing
    into objects; for two lists the added and removed items are listed."""
    out = []
    for key in sorted(set(old) | set(new)):
        path = f"{prefix}{key}"
        if key not in old:
            out.append(f"added `{path}`: `{_rules_text(new[key])}`")
        elif key not in new:
            out.append(f"removed `{path}` (was `{_rules_text(old[key])}`)")
        elif old[key] == new[key] and type(old[key]) is type(new[key]):
            continue
        elif isinstance(old[key], dict) and isinstance(new[key], dict):
            out.extend(rules_diff(old[key], new[key], prefix=f"{path}."))
        elif isinstance(old[key], list) and isinstance(new[key], list):
            olds, news = [_rules_text(v) for v in old[key]], [_rules_text(v) for v in new[key]]
            added = [v for v in news if v not in olds]
            removed = [v for v in olds if v not in news]
            if added or removed:
                parts = ([f"+ `{v}`" for v in added] + [f"- `{v}`" for v in removed])
                out.append(f"changed `{path}`: " + ", ".join(parts))
            else:
                out.append(f"changed `{path}`: reordered `{_rules_text(old[key])}` -> `{_rules_text(new[key])}`")
        else:
            out.append(f"changed `{path}`: `{_rules_text(old[key])}` -> `{_rules_text(new[key])}`")
    return out


def rules_entry(version: int, date: str, reason: str, diff: list[str], base_version, rules, n_cases: int) -> str:
    """The changelog entry of a comparator amendment (``--rules-only``, contract §5.4.8)."""
    base = (f"against the rules recorded in v{base_version}" if base_version is not None
            else "rules.json created")
    lines = [f"## v{version} — {date}", "", f"- reason: {reason}",
             "- comparator amendment, no expected file changed",
             f"- expected files: unchanged ({n_cases} cases; rendered by the build of the last entry with a build line)",
             f"- rules diff ({base}):"]
    lines += [f"  - {d}" for d in diff]
    lines += [f"- rules (tests/conformance/rules.json at v{version}):", "", "```json", _rules_text(rules), "```"]
    return "\n".join(lines) + "\n\n"


def _read_changelog() -> str:
    existing = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else ""
    if not existing.strip():
        existing = "# Conformance set changelog\n\nOne entry per regeneration (newest last); see README.md.\n\n"
    return existing


def rules_only(reason: str, dry_run: bool) -> int:
    """``--rules-only``: version a change of ``rules.json`` without rendering or touching ``expected/``."""
    try:
        rules = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: cannot read {RULES_FILE}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(rules, dict):
        print(f"error: {RULES_FILE} must hold a JSON object", file=sys.stderr)
        return 1
    existing = _read_changelog()
    base_version, base = recorded_rules(existing)
    diff = rules_diff(base if base is not None else {}, rules)
    if not diff:
        print(f"error: {RULES_FILE.name} is unchanged since the rules recorded in v{base_version}; nothing to record",
              file=sys.stderr)
        return 1
    version = next_version(existing)
    if dry_run:
        print(f"would record v{version}: comparator amendment ({len(diff)} rules change(s)), no expected file changed")
        for d in diff:
            print(f"  {d}")
        return 0
    entry = rules_entry(version, _dt.date.today().isoformat(), reason, diff, base_version, rules, len(case_names()))
    CHANGELOG.write_text(existing.rstrip("\n") + "\n\n" + entry, encoding="utf-8")
    print(f"recorded: comparator amendment ({len(diff)} rules change(s)), no expected file changed")
    print(f"CHANGELOG.md: appended v{version}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate tests/conformance/expected/*.json (spec §7.5).")
    parser.add_argument("--reason", required=True, help="why the expected files change (recorded in CHANGELOG.md)")
    parser.add_argument("--case", action="append", default=None, metavar="NAME",
                        help="regenerate only this case (repeatable); default: all cases")
    parser.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    parser.add_argument("--rules-only", action="store_true",
                        help="record a change of tests/conformance/rules.json (comparator amendment): no rendering, "
                             "no expected file touched, a new version entry with the rules diff")
    args = parser.parse_args(argv)
    reason = args.reason.strip()
    if not reason:
        parser.error("--reason must not be empty")
    if args.rules_only:
        if args.case:
            parser.error("--rules-only cannot be combined with --case")
        return rules_only(reason, args.dry_run)
    available = case_names()
    if not available:
        print(f"error: no case files in {CASES}", file=sys.stderr)
        return 1
    if args.case:
        missing = [c for c in args.case if c not in available]
        if missing:
            print(f"error: unknown case(s): {', '.join(missing)}; available: {', '.join(available)}", file=sys.stderr)
            return 1
        selected = [c for c in available if c in set(args.case)]
    else:
        selected = available
    EXPECTED.mkdir(parents=True, exist_ok=True)
    changed, unchanged = [], []
    for name in selected:
        try:
            text = render_case(name)
        except Exception as exc:  # noqa: BLE001 - report the case, then stop
            print(f"error: case {name!r} failed to render: {exc}", file=sys.stderr)
            return 1
        path = EXPECTED / f"{name}.json"
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old == text:
            unchanged.append(name)
            continue
        changed.append(name)
        if not args.dry_run:
            path.write_text(text, encoding="utf-8")
    verb = "would change" if args.dry_run else "regenerated"
    print(f"{verb}: {len(changed)} of {len(selected)} case(s)" + (f" ({', '.join(changed)})" if changed else ""))
    if args.dry_run:
        return 0
    existing = _read_changelog()
    version = next_version(existing)
    entry = changelog_entry(version, _dt.date.today().isoformat(), reason, changed, unchanged,
                            all_cases=selected == available)
    CHANGELOG.write_text(existing.rstrip("\n") + "\n\n" + entry, encoding="utf-8")
    print(f"CHANGELOG.md: appended v{version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
