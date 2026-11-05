#!/usr/bin/env python3
"""Build the Hanabishi Miki drawing-reference model and write it for castplane (dev tool).

    python3 tools/make_miki_model.py                       # build -> validate -> write examples/miki.json,
                                                           #   examples/meshes/miki.{obj,mtl,glb}
    python3 tools/make_miki_model.py --check               # + castplane validate / render (warnings must be
                                                           #   []) + statistics table vs the budget
    python3 tools/make_miki_model.py --preview DIR         # + shaded contact sheets and head close-ups
    python3 tools/make_miki_model.py --lines DIR [--lines-views front head_side ...] [--no-hidden]
                                             [--lines-layers objects]
                                                           # + castplane line renders and their contact sheet
    python3 tools/make_miki_model.py --only hair headband --preview DIR [--context]
                                                           # quick iteration on some regions (writes no model
                                                           #   files unless --out-dir is given; --context draws
                                                           #   the other regions as grey mannequin parts)

The generator lives in ``tools/miki_model/`` (Miki's data and part builders) on top of the shared toolkit
``tools/charmodel/`` (mesh builders, assembly, writers, previews and this command line, ``charmodel.cli``;
geometry numpy-only, previews use Pillow and cairosvg).  The output is deterministic: running the tool twice
gives byte-identical files.  Exit status: 0 on success, 1 when the model is invalid, over budget or the
castplane check reports warnings, 2 on a usage error.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from charmodel import cli  # noqa: E402
from charmodel.cli import castplane_check  # noqa: E402,F401
from miki_model import assemble as asm  # noqa: E402
from miki_model import export, preview  # noqa: E402
from miki_model.rig import Rig  # noqa: E402

#: The Miki package as the shared command line sees it (``charmodel.cli.Tool``).
TOOL = cli.Tool(name="miki", title="Hanabishi Miki", rig=Rig, assemble=asm, export=export, preview=preview, repo=REPO,
                description=__doc__.split("\n\n")[0])


def main(argv=None) -> int:
    return cli.main(TOOL, argv)


if __name__ == "__main__":
    sys.exit(main())
