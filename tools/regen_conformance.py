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

Exit status: 0 on success; 2 for a command-line usage error (argparse: missing or empty
``--reason``, unknown option); 1 for an unknown ``--case`` name or a rendering error.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import castplane  # noqa: E402
from castplane.output.geometry_json import dumps  # noqa: E402

CONFORMANCE = ROOT / "tests" / "conformance"
CASES = CONFORMANCE / "cases"
EXPECTED = CONFORMANCE / "expected"
CHANGELOG = CONFORMANCE / "CHANGELOG.md"

_VERSION_RE = re.compile(r"^## v(\d+) ", re.MULTILINE)


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
    lines = [f"## v{version} — {date}", "", f"- reason: {reason}"]
    scope = "all cases" if all_cases else "selected cases"
    lines.append(f"- regenerated ({scope}, {len(changed)} changed): " + (", ".join(changed) if changed else "none"))
    if unchanged:
        lines.append(f"- unchanged: {', '.join(unchanged)}")
    return "\n".join(lines) + "\n\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate tests/conformance/expected/*.json (spec §7.5).")
    parser.add_argument("--reason", required=True, help="why the expected files change (recorded in CHANGELOG.md)")
    parser.add_argument("--case", action="append", default=None, metavar="NAME",
                        help="regenerate only this case (repeatable); default: all cases")
    parser.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = parser.parse_args(argv)
    reason = args.reason.strip()
    if not reason:
        parser.error("--reason must not be empty")
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
    existing = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else ""
    if not existing.strip():
        existing = "# Conformance set changelog\n\nOne entry per regeneration (newest last); see README.md.\n\n"
    version = next_version(existing)
    entry = changelog_entry(version, _dt.date.today().isoformat(), reason, changed, unchanged,
                            all_cases=selected == available)
    CHANGELOG.write_text(existing.rstrip("\n") + "\n\n" + entry, encoding="utf-8")
    print(f"CHANGELOG.md: appended v{version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
