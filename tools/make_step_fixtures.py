#!/usr/bin/env python3
"""Write the M8 STEP fixtures under ``tests/fixtures/step/`` with OpenCascade (contract §5.5.9).

    python tools/make_step_fixtures.py                 # (re)write the whole set into tests/fixtures/step/
    python tools/make_step_fixtures.py --out DIR       # into another directory
    python tools/make_step_fixtures.py --check         # regenerate into a temporary directory, compare bytes
    python tools/make_step_fixtures.py --bench-solids 200 --bench-out /tmp/bench200.step
                                                       # the benchmark compound (benchmarks/README.md)

Needs OCP (``pip install 'castplane[step]'`` / ``pip install cadquery-ocp``).  The whole set is
always written in the table order of contract §5.5.9 within one process (the PRODUCT names carry a
per-process transfer counter), then every file is rewritten so that regeneration is
byte-reproducible for a given OCC build: the ``FILE_NAME`` time stamp, author and organisation are
fixed, and every ``PRODUCT`` name / id ``'Open CASCADE STEP translator 8.0 <counter>'`` becomes
``'castplane <fixture>'`` (root) or ``'castplane <fixture>.<k>'`` (k-th child).  Everything else is
left as OCC wrote it.  All parameters are integer millimetres.
"""

from __future__ import annotations

import argparse
import math
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "step"

#: the fixture set, in the write order of contract §5.5.9
NAMES = ("cylinder", "cylinder_down", "cylinder_tilted", "sphere", "cone", "box", "frustum", "two_solids")

TIME_STAMP = "2026-10-06T00:00:00"
AUTHOR = "castplane"
ORGANISATION = "cast-space-to-plane"


def _rz_rx(rz_deg: float, rx_deg: float):
    """``R = Rz(rz)·Rx(rx)`` as nested lists (columns are the local axes)."""
    cz, sz = math.cos(math.radians(rz_deg)), math.sin(math.radians(rz_deg))
    cx, sx = math.cos(math.radians(rx_deg)), math.sin(math.radians(rx_deg))
    Rz = [[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]]
    Rx = [[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]]
    return [[sum(Rz[i][k] * Rx[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def build_shapes():
    """``{name: TopoDS_Shape}`` of contract §5.5.9 (imports OCP lazily)."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    from OCP.TopoDS import TopoDS_Compound

    def cylinder(p, d, r, h, x=None):
        ax = gp_Ax2(gp_Pnt(*p), gp_Dir(*d)) if x is None else gp_Ax2(gp_Pnt(*p), gp_Dir(*d), gp_Dir(*x))
        return BRepPrimAPI_MakeCylinder(ax, r, h).Shape()

    R = _rz_rx(20.0, 30.0)
    col = lambda j: (R[0][j], R[1][j], R[2][j])  # noqa: E731

    shapes = {}
    shapes["cylinder"] = cylinder((-1500, 6000, 0), (0, 0, 1), 300, 2400)
    shapes["cylinder_down"] = cylinder((-1500, 6000, 2400), (0, 0, -1), 300, 2400)
    shapes["cylinder_tilted"] = cylinder((0, 5000, -400), col(2), 500, 1600, col(0))
    shapes["sphere"] = BRepPrimAPI_MakeSphere(gp_Pnt(1000, 2000, 500), 500).Shape()
    shapes["cone"] = BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(-2000, 5000, 0), gp_Dir(0, 0, 1)), 400, 0, 1200).Shape()
    box = BRepPrimAPI_MakeBox(gp_Pnt(-500, -400, 0), 1000, 800, 600).Shape()
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(2000, 4000, 0))
    r = gp_Trsf()
    r.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), math.radians(30.0))
    shapes["box"] = BRepBuilderAPI_Transform(box, t.Multiplied(r), True).Shape()
    shapes["frustum"] = BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 400, 200, 1200).Shape()
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, cylinder((-1500, 6000, 0), (0, 0, 1), 300, 2400))
    builder.Add(compound, BRepPrimAPI_MakeSphere(gp_Pnt(1000, 2000, 500), 500).Shape())
    shapes["two_solids"] = compound
    return shapes


def bench_compound(n: int, cols: int = 20):
    """The informational benchmark file of ``benchmarks/README.md`` (not a fixture, never committed):
    a compound of ``n`` cylinders (r 300 mm, h 2400 mm, axis +z) on a grid of ``cols`` columns with
    a 1000 mm pitch, in row-major order (imports OCP lazily)."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for k in range(n):
        ax = gp_Ax2(gp_Pnt(1000 * (k % cols), 1000 * (k // cols), 0), gp_Dir(0, 0, 1))
        builder.Add(compound, BRepPrimAPI_MakeCylinder(ax, 300, 2400).Shape())
    return compound


def write_step(shape, path: pathlib.Path) -> None:
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    writer = STEPControl_Writer()
    Interface_Static.SetCVal_s("write.step.schema", "AP214")
    if writer.Transfer(shape, STEPControl_AsIs) != IFSelect_RetDone:
        raise RuntimeError(f"OCC could not transfer {path.name}")
    if writer.Write(str(path)) != IFSelect_RetDone:
        raise RuntimeError(f"OCC could not write {path}")


_FILE_NAME = re.compile(r"FILE_NAME\('((?:[^']|'')*)','(?:[^']|'')*',\s*\((?:[^)]*)\),\s*\((?:[^)]*)\),", re.S)
_PRODUCT_NAME = re.compile(r"'Open CASCADE STEP translator [0-9.]+ (\d+)((?:\.\d+)?)'")


def normalise(text: str, name: str) -> str:
    """Fix the time stamp / author / organisation and rename the PRODUCT names (contract §5.5.9)."""
    text, n = _FILE_NAME.subn(lambda m: f"FILE_NAME('{m.group(1)}','{TIME_STAMP}',('{AUTHOR}'),('{ORGANISATION}'),",
                              text, count=1)
    if n != 1:
        raise RuntimeError(f"{name}: FILE_NAME header not found")

    def product(m):
        child = m.group(2)
        return f"'castplane {name}{child}'"

    return _PRODUCT_NAME.sub(product, text)


def generate(out_dir: pathlib.Path) -> list:
    """Write the whole set into ``out_dir`` (in table order, one process); returns the paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    shapes = build_shapes()
    paths = []
    for name in NAMES:
        path = out_dir / f"{name}.step"
        write_step(shapes[name], path)
        text = path.read_text(encoding="utf-8")
        path.write_bytes(normalise(text, name).encode("utf-8"))
        paths.append(path)
    return paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(FIXTURES), help="output directory (default tests/fixtures/step)")
    ap.add_argument("--check", action="store_true", help="regenerate into a temporary directory and compare bytes")
    ap.add_argument("--bench-solids", type=int, metavar="N",
                    help="instead of the fixtures, write the benchmark compound of N cylinders (20 columns) "
                         "to --bench-out")
    ap.add_argument("--bench-out", metavar="PATH", default="bench_solids.step",
                    help="output file of --bench-solids (default bench_solids.step)")
    args = ap.parse_args(argv)
    if args.bench_solids is not None:
        if args.bench_solids < 1:
            ap.error("--bench-solids needs N >= 1")
        path = pathlib.Path(args.bench_out)
        write_step(bench_compound(args.bench_solids), path)
        path.write_bytes(normalise(path.read_text(encoding="utf-8"), path.stem).encode("utf-8"))
        print(f"wrote {path}")
        return 0
    if args.check:
        target = pathlib.Path(args.out)
        with tempfile.TemporaryDirectory() as tmp:
            bad = []
            for path in generate(pathlib.Path(tmp)):
                committed = target / path.name
                if not committed.exists() or committed.read_bytes() != path.read_bytes():
                    bad.append(path.name)
        if bad:
            print("out of date: " + ", ".join(bad), file=sys.stderr)
            return 1
        print("fixtures up to date")
        return 0
    for path in generate(pathlib.Path(args.out)):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
