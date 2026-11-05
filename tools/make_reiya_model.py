#!/usr/bin/env python3
"""Build the Reiya drawing-reference model and write it for castplane (dev tool).

    python3 tools/make_reiya_model.py                      # build -> validate -> write examples/reiya.json,
                                                           #   examples/meshes/reiya.{obj,mtl,glb}
    python3 tools/make_reiya_model.py --check              # + castplane validate / render (warnings must be
                                                           #   []) + statistics table vs the budget
    python3 tools/make_reiya_model.py --preview DIR        # + shaded contact sheets and head close-ups
    python3 tools/make_reiya_model.py --lines DIR [--lines-views front head_side ...] [--no-hidden]
                                              [--lines-layers objects]
                                                           # + castplane line renders and their contact sheet
    python3 tools/make_reiya_model.py --only hair tufts --preview DIR [--context]
                                                           # quick iteration on some regions (writes no model
                                                           #   files unless --out-dir is given; --context draws
                                                           #   the other regions as grey mannequin parts)
    python3 tools/make_reiya_model.py --overlay SHEET.png DIR  # + the overlay check against the design sheet
                                                           #   (DIR outside the repository; report.md / .json)

The generator lives in ``tools/reiya_model/`` (Reiya's data and part builders) on top of the shared toolkit
``tools/charmodel/`` (mesh builders, assembly, writers, previews and this command line, ``charmodel.cli``;
geometry numpy-only, previews use Pillow and cairosvg).  The output is deterministic: running the tool twice
gives byte-identical files.  Exit status: 0 on success, 1 when the model is invalid, over budget, the
castplane check reports warnings or an overlay pass criterion fails, 2 on a usage error.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from charmodel import cli  # noqa: E402
from charmodel.cli import castplane_check  # noqa: E402,F401
from reiya_model import assemble as asm  # noqa: E402
from reiya_model import export, overlay, preview  # noqa: E402
from reiya_model.rig import Rig  # noqa: E402

#: The Reiya package as the shared command line sees it (``charmodel.cli.Tool``).
TOOL = cli.Tool(name="reiya", title="Reiya", rig=Rig, assemble=asm, export=export, preview=preview, repo=REPO,
                description=__doc__.split("\n\n")[0], overlay=overlay)


def main(argv=None) -> int:
    return cli.main(TOOL, argv)


if __name__ == "__main__":
    sys.exit(main())
