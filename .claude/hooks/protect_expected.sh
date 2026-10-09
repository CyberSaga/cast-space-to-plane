#!/usr/bin/env bash
# PreToolUse guard: conformance expected files are written only by tools/regen_conformance.py
# (tests/conformance/README.md rule 2). Denies Edit / Write / NotebookEdit on them.
f=$(jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
case "$f" in
  *tests/conformance/expected/*)
    jq -n --arg f "$f" '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny",
      permissionDecisionReason: ("Hand edit of " + $f + " blocked: expected files are generated only by `python3 tools/regen_conformance.py --case NAME --reason \"...\"` (tests/conformance/README.md rule 2).")}}'
    ;;
esac
exit 0
