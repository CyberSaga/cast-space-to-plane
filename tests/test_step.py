"""STEP import (contract §5.5; spec §9 row "STEP", §10 M8).  Part 21 parser, units, topology walk,
recognisers, importer API.  Fixtures: ``tests/fixtures/step/`` (written by
``tools/make_step_fixtures.py`` with OCP; committed)."""

from __future__ import annotations

import copy
import json
import math
import pathlib
import random
import re
import time

import numpy as np
import pytest

import castplane
from castplane import cli
from castplane import io as cpio
from castplane.errors import SceneError
from castplane.io import part21
from castplane.io import step as S
from castplane.io.part21 import Part21SyntaxError, parse, tokenize
from castplane.io.step import (DEFAULT_SCENE_TEMPLATE, STEP_WARNING_CODES, StepError, euler_zyx_deg,
                               expand_step_object, import_step, make_step_warning, recognise_solid, to_metres)
from castplane.output.geometry_json import dumps as geometry_dumps
from castplane.transform import euler_zyx_matrix
from tests.test_conformance import CASES, EXPECTED, compare_documents, recorded_numpy_version

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "step"


def p21(data: str, header: str = "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));") -> str:
    """A complete Part 21 text around a DATA section body."""
    return f"ISO-10303-21;\nHEADER;\n{header}\nENDSEC;\nDATA;\n{data}\nENDSEC;\nEND-ISO-10303-21;\n"


# --------------------------------------------------------------------------- Part 21 (§5.5.2)
def test_part21_public_surface():
    assert part21.__all__ == ["Part21SyntaxError", "tokenize", "parse"]
    assert issubclass(Part21SyntaxError, ValueError)


def test_tokenize_kinds_and_skip():
    toks = tokenize("#12 = FOO('a''b', .T., -0., 3, $, *, (1.E-07)) /* c */ ;")
    assert toks == [("ref", "#12"), ("punct", "="), ("name", "FOO"), ("punct", "("), ("str", "'a''b'"),
                    ("punct", ","), ("enum", ".T."), ("punct", ","), ("real", "-0."), ("punct", ","),
                    ("real", "3"), ("punct", ","), ("punct", "$"), ("punct", ","), ("punct", "*"),
                    ("punct", ","), ("punct", "("), ("real", "1.E-07"), ("punct", ")"), ("punct", ")"),
                    ("punct", ";")]
    assert tokenize("ISO-10303-21; END-ISO-10303-21;")[0] == ("name", "ISO-10303-21")
    assert tokenize("END-ISO-10303-21;")[0] == ("name", "END-ISO-10303-21")


def test_parse_values_round_trip():
    doc = parse(p21("#1 = FOO('it''s',$,*,LENGTH_MEASURE(1.E-07),-0.,.MILLI.,(#2,(3,4.5)),'\\X2\\00E9\\X0\\');\n"
                    "#2 = BAR();"))
    name, args = doc["entities"]["#1"]
    assert name == "FOO"
    assert args[0] == "it's"
    assert args[1] is None and args[2] is None
    assert args[3] == ("LENGTH_MEASURE", 1e-07)
    assert args[4] == 0.0 and math.copysign(1.0, args[4]) == -1.0
    assert args[5] == ".MILLI."
    assert args[6] == ["#2", [3, 4.5]] and isinstance(args[6][1][0], int) and isinstance(args[6][1][1], float)
    assert args[7] == "\\X2\\00E9\\X0\\"
    assert doc["entities"]["#2"] == ("BAR", [])
    assert doc["header"] == {"FILE_SCHEMA": [["AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }"]]}


def test_parse_complex_entity_and_multiline_records():
    text = p21("#114 = ( LENGTH_UNIT() NAMED_UNIT(*)\n   SI_UNIT(.MILLI.,\n .METRE.) );\n"
               "#7 = PRODUCT('a',\n  'b','',(#8));")
    ents = parse(text)["entities"]
    assert ents["#114"] == ("COMPLEX", [("LENGTH_UNIT", []), ("NAMED_UNIT", [None]),
                                        ("SI_UNIT", [".MILLI.", ".METRE."])])
    assert ents["#7"] == ("PRODUCT", ["a", "b", "", ["#8"]])


def test_parse_comments_skipped_but_kept_inside_strings():
    ents = parse(p21("/* lead */ #1 = /* mid */ FOO('/* not a comment */', 2) /* tail */;"))["entities"]
    assert ents["#1"] == ("FOO", ["/* not a comment */", 2])


def test_parse_multiple_data_sections_concatenated():
    text = ("ISO-10303-21;HEADER;ENDSEC;DATA;#1=A();ENDSEC;DATA;#2=B(1);ENDSEC;END-ISO-10303-21;")
    assert parse(text)["entities"] == {"#1": ("A", []), "#2": ("B", [1])}


@pytest.mark.parametrize("text, needle", [
    (p21("#1 = A();\n#1 = B();"), "duplicate instance #1"),
    (p21("#1 = !USER_ENTITY(1);"), "unexpected character '!'"),
    (p21("#1 = A('abc);"), "unterminated string"),
    (p21("#1 = A(\"0FF\");"), "unexpected character"),
    (p21("#1 = A(1 2);"), "expected ',' or ')'"),
    ("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n#1 = A(1,", "unexpected end of input"),
])
def test_parse_syntax_errors_name_an_offset(text, needle):
    with pytest.raises(Part21SyntaxError) as exc:
        parse(text)
    assert needle in str(exc.value)
    assert "at offset" in str(exc.value)
    assert 0 <= exc.value.offset <= len(text)


def test_truncated_file_names_the_end_offset():
    text = p21("#1 = A();")[:-30]
    with pytest.raises(Part21SyntaxError) as exc:
        parse(text)
    assert exc.value.offset == len(text)


def test_parse_cylinder_fixture_counts():
    doc = parse((FIX / "cylinder.step").read_text(encoding="utf-8", errors="replace"))
    assert len(doc["entities"]) == 118
    assert doc["entities"]["#15"] == ("MANIFOLD_SOLID_BREP", ["", "#16"])
    assert doc["header"]["FILE_SCHEMA"] == [["AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }"]]


# =========================================================================== STEP semantics (§5.5.3–§5.5.6)

FIXTURES = ("cylinder", "cylinder_down", "cylinder_tilted", "sphere", "cone", "box", "frustum", "two_solids")
PILLAR = {"id": "pillar", "type": "cylinder", "radius": 0.3, "height": 2.4,
          "transform": {"position": [-1.5, 6.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]}}
SPHERE = {"type": "sphere", "radius": 0.5, "transform": {"position": [1.0, 2.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]}}
CONE = {"type": "cone", "radius": 0.4, "height": 1.2,
        "transform": {"position": [-2.0, 5.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]}}


def fixture_text(name: str) -> str:
    return (FIX / f"{name}.step").read_text(encoding="utf-8")


def write(tmp_path, text: str, name: str = "part.step") -> pathlib.Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def edit(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, old
    return text.replace(old, new)


def add_entities(text: str, extra: str) -> str:
    """Insert entity records before the end of the DATA section."""
    i = text.rindex("ENDSEC;")
    return text[:i] + extra.strip() + "\n" + text[i:]


def expand(path, **kw) -> list:
    obj = {"id": kw.pop("id", "part"), "type": "step", "path": str(path), **kw}
    objects, notes = expand_step_object(obj, "objects[0]", None)
    return objects


def strip_id(o: dict) -> dict:
    return {k: v for k, v in o.items() if k != "id"}


# --------------------------------------------------------------------------- an inline Part-21 writer
def f(x) -> str:
    return repr(float(x))


class Builder:
    """Hand-written Part 21 B-reps (the inline-string cases of contract §5.5.10)."""

    def __init__(self):
        self.lines = []

    def add(self, record: str) -> str:
        ref = f"#{len(self.lines) + 1}"
        self.lines.append(f"{ref} = {record};")
        return ref

    def point(self, p) -> str:
        return self.add(f"CARTESIAN_POINT('',({','.join(f(c) for c in p)}))")

    def direction(self, d) -> str:
        return self.add(f"DIRECTION('',({','.join(f(c) for c in d)}))")

    def axis(self, o, a=(0, 0, 1), r=(1, 0, 0)) -> str:
        return self.add(f"AXIS2_PLACEMENT_3D('',{self.point(o)},{self.direction(a)},{self.direction(r)})")

    def vertex(self, p) -> str:
        return self.add(f"VERTEX_POINT('',{self.point(p)})")

    def edge(self, v1, v2, geom) -> str:
        return self.add(f"EDGE_CURVE('',{v1},{v2},{geom},.T.)")

    def face(self, edges, surface, vertex=None) -> str:
        if vertex is not None:
            loop = self.add(f"VERTEX_LOOP('',{vertex})")
        else:
            oes = [self.add(f"ORIENTED_EDGE('',*,*,{e},.T.)") for e in edges]
            loop = self.add(f"EDGE_LOOP('',({','.join(oes)}))")
        bound = self.add(f"FACE_OUTER_BOUND('',{loop},.T.)")
        return self.add(f"ADVANCED_FACE('',({bound}),{surface},.T.)")

    def solid(self, faces) -> str:
        shell = self.add(f"CLOSED_SHELL('',({','.join(faces)}))")
        return self.add(f"MANIFOLD_SOLID_BREP('',{shell})")

    def units(self, length="mm", angle="rad") -> None:
        refs = []
        if length == "mm":
            refs.append(self.add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )"))
        elif length == "m":
            refs.append(self.add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT($,.METRE.) )"))
        elif length == "cm":
            refs.append(self.add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.CENTI.,.METRE.) )"))
        elif length == "inch":
            mm = self.add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )")
            m = self.add(f"LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(25.4),{mm})")
            dim = self.add("DIMENSIONAL_EXPONENTS(1.,0.,0.,0.,0.,0.,0.)")
            refs.append(self.add(f"( CONVERSION_BASED_UNIT('INCH',{m}) LENGTH_UNIT() NAMED_UNIT({dim}) )"))
        if angle == "rad":
            refs.append(self.add("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )"))
        elif angle == "deg":
            rad = self.add("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
            m = self.add(f"PLANE_ANGLE_MEASURE_WITH_UNIT(PLANE_ANGLE_MEASURE(0.0174532925199433),{rad})")
            dim = self.add("DIMENSIONAL_EXPONENTS(0.,0.,0.,0.,0.,0.,0.)")
            refs.append(self.add(f"( CONVERSION_BASED_UNIT('DEGREE',{m}) NAMED_UNIT({dim}) PLANE_ANGLE_UNIT() )"))
        if refs:
            self.add(f"( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNIT_ASSIGNED_CONTEXT(({','.join(refs)})) "
                     "REPRESENTATION_CONTEXT('','') )")

    def cylinder(self, r, h, o=(0.0, 0.0, 0.0), tilt=0.0, radius2=None) -> str:
        """An upright cylinder (axis +z) of radius ``r`` and height ``h`` based at ``o``; ``tilt``
        rotates the top cap plane's normal about x; ``radius2`` adds a second cylindrical face."""
        top = (o[0], o[1], o[2] + h)
        vb, vt = self.vertex((o[0] + r, o[1], o[2])), self.vertex((top[0] + r, top[1], top[2]))
        cb = self.add(f"CIRCLE('',{self.axis(o)},{f(r)})")
        ct = self.add(f"CIRCLE('',{self.axis(top)},{f(r)})")
        eb, et = self.edge(vb, vb, cb), self.edge(vt, vt, ct)
        seam = self.edge(vb, vt, self.add(f"LINE('',{self.point((o[0] + r, o[1], o[2]))},"
                                          f"{self.add(f'VECTOR({chr(39)}{chr(39)},{self.direction((0, 0, 1))},1.)')})"))
        side = self.face([eb, seam, et, seam], self.add(f"CYLINDRICAL_SURFACE('',{self.axis(o)},{f(r)})"))
        bottom = self.face([eb], self.add(f"PLANE('',{self.axis(o)})"))
        n_top = (0.0, -math.sin(tilt), math.cos(tilt))
        topf = self.face([et], self.add(f"PLANE('',{self.axis(top, n_top)})"))
        faces = [side, topf, bottom]
        if radius2 is not None:
            faces.append(self.face([], self.add(f"CYLINDRICAL_SURFACE('',{self.axis(o)},{f(radius2)})")))
        return self.solid(faces)

    def cone(self, r, h, semi, o=(0.0, 0.0, 0.0), surface_axis=(0, 0, -1)) -> str:
        apex = (o[0], o[1], o[2] + h)
        vb, va = self.vertex((o[0] + r, o[1], o[2])), self.vertex(apex)
        cb = self.add(f"CIRCLE('',{self.axis(o)},{f(r)})")
        eb = self.edge(vb, vb, cb)
        line = self.add(f"LINE('',{self.point((o[0] + r, o[1], o[2]))},"
                        f"{self.add(f'VECTOR({chr(39)}{chr(39)},{self.direction((-r, 0, h))},1.)')})")
        seam = self.edge(vb, va, line)
        # ISO 10303-42: the surface radius is radius + u·tan(semi) along the placement axis, so the
        # axis points away from the apex (as OCC writes it: axis (0, 0, -1) for an apex above the base)
        side = self.face([eb, seam], self.add(f"CONICAL_SURFACE('',{self.axis(o, surface_axis)},{f(r)},{semi!r})"))
        base = self.face([eb], self.add(f"PLANE('',{self.axis(o, (0, 0, -1))})"))
        return self.solid([side, base])

    def text(self) -> str:
        return p21("\n".join(self.lines))


def cylinder_file(tmp_path, r, h, o=(0.0, 0.0, 0.0), length="mm", angle="rad", **kw):
    b = Builder()
    b.units(length, angle)
    b.cylinder(r, h, o, **kw)
    return write(tmp_path, b.text())


# --------------------------------------------------------------------------- public surface, notes
def test_step_public_surface_and_notes():
    assert S.__all__ == ["StepError", "STEP_WARNING_CODES", "DEFAULT_SCENE_TEMPLATE", "make_step_warning",
                         "to_metres", "import_step", "expand_step_object", "recognise_solid", "euler_zyx_deg",
                         "tessellate_step", "mesh_object_from_triangles"]
    assert set(STEP_WARNING_CODES) == {"STEP_UNIT_ASSUMED_MM", "STEP_ANGLE_UNIT_ASSUMED_RAD", "STEP_SOLID_TESSELLATED"}
    assert make_step_warning("STEP_SOLID_TESSELLATED", ["#15"]) == {
        "code": "STEP_SOLID_TESSELLATED", "ids": ["#15"], "message": STEP_WARNING_CODES["STEP_SOLID_TESSELLATED"]}
    with pytest.raises(ValueError):
        make_step_warning("MESH_NON_MANIFOLD")
    assert issubclass(StepError, SceneError)
    e = StepError("objects[2].path", "#15: x", "#15")
    assert (e.field, e.message, e.entity) == ("objects[2].path", "#15: x", "#15")


def test_default_scene_template_is_the_basic_example_blocks():
    basic = json.loads((ROOT / "examples" / "basic.json").read_text(encoding="utf-8"))
    assert DEFAULT_SCENE_TEMPLATE == {k: basic[k] for k in ("version", "units", "up", "lights", "receivers",
                                                             "camera", "output")}


# --------------------------------------------------------------------------- units (§5.5.3)
def test_to_metres_is_a_division():
    assert to_metres(9, 1000.0) == 0.009 and 9 * 0.001 != 0.009
    assert to_metres(1001.0, 1000.0) == 1.001 and 1001 * 0.001 != 1.001
    assert to_metres(0.5, 1000.0) == 0.0005
    assert to_metres(-1500.0, 1000.0) == -1.5 and to_metres(2400.0, 1000.0) == 2.4
    assert to_metres([300.0, -0.0, np.float64(2.0)], 1000.0) == [0.3, 0.0, 0.002]
    assert math.copysign(1.0, to_metres(-0.0, 1000.0)) == 1.0
    assert to_metres(np.array([1.0, 2.0]), 1.0) == [1.0, 2.0]
    assert all(type(v) is float for v in to_metres(np.array([1.0, 2.0]), 1.0))


def test_unit_arithmetic_mm_file(tmp_path):
    rep = import_step(cylinder_file(tmp_path, 9.0, 1001.0, (0.5, 0.0, 0.0)))
    (obj,) = rep["objects"]
    assert rep["unit"] == "mm" and rep["unit_divisor"] == 1000.0 and rep["notes"] == []
    assert obj["radius"] == 0.009 and obj["height"] == 1.001 and obj["transform"]["position"][0] == 0.0005
    assert obj["transform"]["position"] == [0.0005, 0.0, 0.0]


def test_unit_arithmetic_metre_file_unchanged(tmp_path):
    rep = import_step(cylinder_file(tmp_path, 9.0, 1001.0, (0.5, 0.0, 0.0), length="m"))
    (obj,) = rep["objects"]
    assert rep["unit"] == "m" and rep["unit_divisor"] == 1.0
    assert obj["radius"] == 9.0 and obj["height"] == 1001.0 and obj["transform"]["position"] == [0.5, 0.0, 0.0]


def test_no_unit_context_assumes_mm_and_radians(tmp_path):
    rep = import_step(cylinder_file(tmp_path, 300.0, 2400.0, length=None, angle=None))
    assert [n["code"] for n in rep["notes"]] == ["STEP_ANGLE_UNIT_ASSUMED_RAD", "STEP_UNIT_ASSUMED_MM"]
    assert all(n["ids"] == [] for n in rep["notes"])
    assert rep["unit"] == "mm" and rep["angle_factor"] == 1.0
    assert rep["objects"][0]["radius"] == 0.3


@pytest.mark.parametrize("length", ["inch", "cm"])
def test_unsupported_length_units(tmp_path, length):
    with pytest.raises(StepError) as exc:
        import_step(cylinder_file(tmp_path, 300.0, 2400.0, length=length))
    assert exc.value.message.startswith("unsupported: length unit")
    assert exc.value.field == "step"


def test_two_length_units_with_different_scales(tmp_path):
    b = Builder()
    b.units("mm")
    b.units("m", angle=None)
    b.cylinder(1.0, 2.0)
    with pytest.raises(StepError, match="different scales"):
        import_step(write(tmp_path, b.text()))


def test_degree_angle_unit_cone_equals_radian_cone(tmp_path):
    rad, deg = Builder(), Builder()
    rad.units("mm", "rad")
    rad.cone(400.0, 1200.0, math.atan(1.0 / 3.0))
    deg.units("mm", "deg")
    deg.cone(400.0, 1200.0, 18.434948822922)
    r_rad = import_step(write(tmp_path, rad.text(), "rad.step"), obj_id="c")
    r_deg = import_step(write(tmp_path, deg.text(), "deg.step"), obj_id="c")
    assert r_deg["angle_factor"] == 0.0174532925199433
    assert r_deg["objects"] == r_rad["objects"]
    assert strip_id(r_rad["objects"][0]) == {"type": "cone", "radius": 0.4, "height": 1.2,
                                             "transform": {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]}}
    # the degree value read as radians is out of the (0, pi/2) range
    bad = Builder()
    bad.units("mm", "rad")
    bad.cone(400.0, 1200.0, 18.434948822922)
    with pytest.raises(StepError, match="semi-angle out of range"):
        import_step(write(tmp_path, bad.text(), "bad.step"))


@pytest.mark.parametrize("semi, surface_axis", [(0.5, (0, 0, -1)), (math.atan(1.0 / 3.0), (0, 0, 1))])
def test_cone_with_wrong_semi_angle_or_axis_sense_is_rejected(tmp_path, semi, surface_axis):
    """Placement in the base plane (OCC's layout): the radius test alone reduces to ``r == radius_s``,
    so a wrong semi-angle, or a surface axis pointing at the apex (radius growing towards it), is
    caught by the surface radius having to vanish at the apex vertex."""
    b = Builder()
    b.units()
    b.cone(400.0, 1200.0, semi, surface_axis=surface_axis)
    with pytest.raises(StepError, match="inconsistent cone"):
        import_step(write(tmp_path, b.text()))


# --------------------------------------------------------------------------- tolerances (§5.5.4)
def test_tolerance_is_physical_across_units(tmp_path):
    mm = import_step(cylinder_file(tmp_path, 500.0, 2000.0, length="mm"))
    m = import_step(cylinder_file(tmp_path, 0.5, 2.0, length="m"))
    assert mm["tol"] == pytest.approx(2e-3) and m["tol"] == pytest.approx(2e-6)       # 1e-6 · 2000 mm
    assert strip_id(mm["objects"][0]) == strip_id(m["objects"][0])
    small = import_step(cylinder_file(tmp_path, 0.001, 0.0005, length="m"))           # extent < 1 mm
    assert small["tol"] == pytest.approx(1e-9)


@pytest.mark.parametrize("length, scale", [("m", 1.0), ("mm", 1000.0)])
def test_metre_file_tolerance_mirrors_the_mm_file(tmp_path, length, scale):
    ok = import_step(cylinder_file(tmp_path, 0.5 * scale, 2.0 * scale, length=length, tilt=2e-9))
    assert ok["objects"][0]["type"] == "cylinder" and ok["objects"][0]["height"] == pytest.approx(2.0)
    with pytest.raises(StepError, match="unsupported solid"):
        import_step(cylinder_file(tmp_path, 0.5 * scale, 2.0 * scale, length=length, tilt=2e-6))
    # positional tolerance (tol = 2e-6 m on this 2 m part): a second cylindrical face 1e-6 m off is
    # the same cylinder, 1e-5 m off is not
    near = import_step(cylinder_file(tmp_path, 0.5 * scale, 2.0 * scale, length=length,
                                     radius2=(0.5 + 1e-6) * scale))
    assert near["objects"][0]["type"] == "cylinder" and near["objects"][0]["radius"] == 0.5
    with pytest.raises(StepError, match="different radii"):
        import_step(cylinder_file(tmp_path, 0.5 * scale, 2.0 * scale, length=length, radius2=(0.5 + 1e-5) * scale))


# --------------------------------------------------------------------------- fixtures: exact expansions
def test_fixture_set_is_small():
    total = sum((FIX / f"{n}.step").stat().st_size for n in FIXTURES)
    assert total < 100_000
    assert (FIX / "README.md").exists()


def test_cylinder_fixture_is_the_pillar():
    objects = expand_step_object({"id": "pillar", "type": "step", "path": "cylinder.step"}, "objects[1]", FIX)[0]
    assert objects == [PILLAR]
    assert all(type(v) is float for v in objects[0]["transform"]["position"] + objects[0]["transform"]["rotation_deg"])
    rep = import_step(FIX / "cylinder.step")
    assert rep["objects"][0]["id"] == "cylinder"
    assert rep["schema"] == "AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }"
    assert rep["solids"] == [{"entity": "#15", "kind": "cylinder", "faces": {"CYLINDRICAL_SURFACE": 1, "PLANE": 2},
                              "object": rep["objects"][0]}]
    assert rep["unit"] == "mm" and rep["unit_divisor"] == 1000.0 and rep["angle_factor"] == 1.0
    assert rep["tol"] == 6e-3 and rep["notes"] == []


def _basic_with(obj_id: str, replacement: dict) -> dict:
    scene = json.loads((ROOT / "examples" / "basic.json").read_text(encoding="utf-8"))
    scene["objects"] = [replacement if o["id"] == obj_id else o for o in scene["objects"]]
    return scene


def _geometry(scene) -> dict:
    return castplane.render(castplane.load_scene(scene))["geometry"]


def test_cylinder_fixture_renders_the_basic_example_byte_equal():
    (pillar,) = expand_step_object({"id": "pillar", "type": "step", "path": "cylinder.step"}, "objects[1]", FIX)[0]
    inline = json.loads((ROOT / "examples" / "basic.json").read_text(encoding="utf-8"))
    doc = _geometry(_basic_with("pillar", pillar))
    assert geometry_dumps(doc) == geometry_dumps(_geometry(inline))
    expected = json.loads((EXPECTED / "example_basic.json").read_text(encoding="utf-8"))
    assert compare_documents(expected, json.loads(geometry_dumps(doc)), "example_basic") == []
    # the hand numbers of contract §5.5.10 (closed form, no castplane code)
    pts = doc["points"]
    hand = {"pillar.g0.base": (-1.7552526894158411, 5.8423736552920795, 0.0),
            "pillar.g1.base": (-1.220747310584159, 6.10962634470792, 0.0),
            "pillar.g0.top.shadow.lamp": (-5.584894920868585, 12.043916175929343, 0.0),
            "pillar.g1.top.shadow.lamp": (-3.884195988222324, 12.894265642252474, 0.0)}
    for name, world in hand.items():
        assert np.allclose(pts[name]["world"], world, rtol=0, atol=1e-9), name
    b, lamp, r = np.array([-1.5, 6.0, 0.0]), np.array([0.0, 3.0, 3.5]), 0.3
    q = (b - lamp)[:2]
    d = math.hypot(*q)
    assert d == pytest.approx(3.3541019662496847, abs=1e-15)
    theta, alpha = math.atan2(-3.0, 1.5), math.acos(r / d)
    for k, t in enumerate((theta - alpha, theta + alpha)):
        g = b + r * np.array([math.cos(t), math.sin(t), 0.0])
        assert np.allclose(pts[f"pillar.g{k}.base"]["world"], g, atol=1e-12)
        top = g + np.array([0.0, 0.0, 2.4])
        shadow = lamp + (top - lamp) * 35.0 / 11.0
        assert np.allclose(pts[f"pillar.g{k}.top.shadow.lamp"]["world"], shadow, atol=1e-9)


def test_sphere_and_cone_fixtures_exact_and_render_byte_equal():
    for name, want in (("sphere", SPHERE), ("cone", CONE)):
        (obj,) = expand(FIX / f"{name}.step", id=name)
        assert strip_id(obj) == want and obj["id"] == name
        tmpl = copy.deepcopy(DEFAULT_SCENE_TEMPLATE)
        inline = dict(tmpl, objects=[{"id": name, **want}])
        imported = dict(tmpl, objects=[obj])
        assert geometry_dumps(_geometry(imported)) == geometry_dumps(_geometry(inline))


def test_sphere_axis_down_is_the_same_sphere(tmp_path):
    text = edit(fixture_text("sphere"), "#25 = DIRECTION('',(0.,0.,1.));", "#25 = DIRECTION('',(0.,0.,-1.));")
    assert strip_id(expand(write(tmp_path, text))[0]) == SPHERE


def test_box_fixture_within_1e9_and_conformance():
    (crate,) = expand(FIX / "box.step", id="crate")
    assert crate["type"] == "box"
    assert np.allclose(crate["size"], [1.0, 0.8, 0.6], rtol=0, atol=1e-9)
    assert np.allclose(crate["transform"]["position"], [2.0, 4.0, 0.0], rtol=0, atol=1e-9)
    assert np.allclose(crate["transform"]["rotation_deg"], [0.0, 0.0, 30.0], rtol=0, atol=1e-9)
    # the OCC 8.0 numbers recorded in contract §5.5.5
    assert crate["size"] == [1.00000000000002, 0.8000000000003888, 0.6]
    assert crate["transform"]["position"] == [2.0000000000000004, 4.0, 0.0]
    if recorded_numpy_version() == np.__version__:      # atan2's last bit is per build (§5.5.5)
        assert crate["transform"]["rotation_deg"] == [0.0, 0.0, 30.000000000012566]
    doc = json.loads(geometry_dumps(_geometry(_basic_with("crate", crate))))
    expected = json.loads((EXPECTED / "example_basic.json").read_text(encoding="utf-8"))
    assert compare_documents(expected, doc, "example_basic") == []


def test_box_with_opposite_axis_signs_is_the_same_box(tmp_path):
    text = fixture_text("box")
    assert "#35 = DIRECTION('',(0.866025403784,0.5,0.));" in text
    edited = edit(text, "#155 = DIRECTION('',(0.866025403784,0.5,0.));",
                  "#155 = DIRECTION('',(-0.866025403784,-0.5,-0.));")
    assert expand(write(tmp_path, edited), id="crate") == expand(FIX / "box.step", id="crate")


def test_cylinder_down_fixture_turns_the_frame():
    (obj,) = expand(FIX / "cylinder_down.step", id="pillar")
    assert obj == dict(PILLAR, transform={"position": [-1.5, 6.0, 0.0], "rotation_deg": [0.0, 0.0, 180.0]})


_CONIC_FRAME_LEAVES = re.compile(r"\.(circle\.e1\[\d\]|circle\.e2\[\d\]|arc\.theta[01]|arcs\[\d+\]\.theta\[\d\]"
                                 r"|visible\[\d+\]\[\d\])$")


def _leaf_differences(a, b, path=""):
    """``(path, a, b)`` of every leaf differing by more than 1e-9 (structure must agree)."""
    if isinstance(a, dict):
        assert set(a) == set(b), path
        return [d for k in a for d in _leaf_differences(a[k], b[k], f"{path}.{k}")]
    if isinstance(a, list):
        assert len(a) == len(b), path
        return [d for i, (u, v) in enumerate(zip(a, b)) for d in _leaf_differences(u, v, f"{path}[{i}]")]
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return [] if abs(a - b) <= 1e-9 else [(path, a, b)]
    return [] if a == b else [(path, a, b)]


def test_cylinder_down_render_differs_only_in_the_conic_frame():
    """§5.5.10: the frame turned by 180° flips ``e1`` / ``e2`` and shifts every conic parameter by π;
    everything else (points, polygons, segments) agrees within 1e-9.  The flipped parameters also
    appear in ``visible`` intervals and in ``form_shadow[].terminator[]`` conics (implementation note)."""
    (down,) = expand(FIX / "cylinder_down.step", id="pillar")
    inline = json.loads(geometry_dumps(_geometry(json.loads((ROOT / "examples" / "basic.json")
                                                            .read_text(encoding="utf-8")))))
    doc = json.loads(geometry_dumps(_geometry(_basic_with("pillar", down))))
    diffs = _leaf_differences(inline, doc)
    assert diffs and all(_CONIC_FRAME_LEAVES.search(p) for p, _, _ in diffs), diffs
    assert len(diffs) == 64
    assert {p.split(".")[1].split("[")[0] for p, _, _ in diffs} == {"outlines", "shadows", "form_shadow"}
    for p, x, y in diffs:
        if ".circle." in p:
            assert x == -y, (p, x, y)
        else:                                           # a conic parameter: shifted by π (mod 2π)
            assert abs((x - y) % (2 * math.pi) - math.pi) < 1e-9, (p, x, y)


def test_cylinder_axis_edit_canonicalises_bit_equal(tmp_path):
    text = edit(fixture_text("cylinder"), "#34 = DIRECTION('',(0.,0.,1.));", "#34 = DIRECTION('',(0.,0.,-1.));")
    assert expand(write(tmp_path, text), id="pillar") == [PILLAR]


def test_cylinder_tilted_fixture():
    (drum,) = expand(FIX / "cylinder_tilted.step", id="drum")
    assert drum["radius"] == 0.5
    assert drum["transform"]["position"] == [0.0, 5.0, -0.4]
    assert drum["height"] == pytest.approx(1.6, abs=1e-9)
    assert np.allclose(drum["transform"]["rotation_deg"], [30.0, 0.0, 20.0], rtol=0, atol=1e-9)
    scene = json.loads((CASES / "buried_cylinder_tilted.json").read_text(encoding="utf-8"))
    scene["objects"] = [drum if o["id"] == "drum" else o for o in scene["objects"]]
    doc = json.loads(geometry_dumps(_geometry(scene)))
    expected = json.loads((EXPECTED / "buried_cylinder_tilted.json").read_text(encoding="utf-8"))
    assert compare_documents(expected, doc, "buried_cylinder_tilted") == []


def test_frustum_fixture_is_unsupported():
    with pytest.raises(StepError) as exc:
        import_step(FIX / "frustum.step", field="objects[2].path")
    e = exc.value
    assert e.entity == "#15" and e.field == "objects[2].path"
    assert e.message.startswith("#15: unsupported solid: faces {CONICAL_SURFACE: 1, PLANE: 2} "
                                "(supported: cylinder, sphere, cone, box)")


def test_two_solids_ids_and_selection():
    objs = expand(FIX / "two_solids.step", id="part")
    assert [o["id"] for o in objs] == ["part_0", "part_1"]
    assert [o["type"] for o in objs] == ["cylinder", "sphere"]
    assert strip_id(objs[0]) == strip_id(PILLAR) and strip_id(objs[1]) == SPHERE
    rep = import_step(FIX / "two_solids.step", obj_id="part")
    assert [s["entity"] for s in rep["solids"]] == ["#37", "#154"]
    assert [s["kind"] for s in rep["solids"]] == ["cylinder", "sphere"]
    (one,) = expand(FIX / "two_solids.step", id="part", solid=1)
    assert one["id"] == "part" and strip_id(one) == SPHERE
    with pytest.raises(SceneError) as exc:
        expand(FIX / "two_solids.step", solid=2)
    assert exc.value.field == "objects[0].solid" and exc.value.message == "file has 2 solid(s)"
    for bad in (True, 1.0, -1, "1"):
        with pytest.raises(SceneError) as exc:
            expand(FIX / "two_solids.step", solid=bad)
        assert exc.value.field == "objects[0].solid"


def test_default_id_is_the_sanitised_file_stem(tmp_path):
    path = write(tmp_path, fixture_text("cylinder"), "my pillar.v2.step")
    assert import_step(path)["objects"][0]["id"] == "my_pillar_v2"


# --------------------------------------------------------------------------- assemblies, errors
def test_non_identity_assembly_transformation_is_rejected(tmp_path):
    b = Builder()
    b.units()
    b.cylinder(300.0, 2400.0)
    p1, p2 = b.axis((0, 0, 0)), b.axis((1, 0, 0))
    ref = b.add(f"ITEM_DEFINED_TRANSFORMATION('','',{p1},{p2})")
    with pytest.raises(StepError) as exc:
        import_step(write(tmp_path, b.text()))
    assert exc.value.message == f"unsupported: assembly transformation {ref} is not the identity (single placement only)"
    assert exc.value.entity == ref
    ok = Builder()
    ok.units()
    ok.cylinder(300.0, 2400.0)
    ok.add(f"ITEM_DEFINED_TRANSFORMATION('','',{ok.axis((0, 0, 0))},{ok.axis((0, 0, 1e-4))})")
    assert import_step(write(tmp_path, ok.text(), "ok.step"))["objects"][0]["type"] == "cylinder"


def test_mapped_item_is_rejected(tmp_path):
    b = Builder()
    b.units()
    b.cylinder(300.0, 2400.0)
    b.add("MAPPED_ITEM('',#1,#2)")
    with pytest.raises(StepError, match="unsupported: MAPPED_ITEM"):
        import_step(write(tmp_path, b.text()))


@pytest.mark.parametrize("mutate", [
    lambda t: t[: len(t) // 2],                                                          # truncated
    lambda t: edit(t, "#118 = PRODUCT_RELATED", "#118 = !USER_ENTITY(1);\n#119 = PRODUCT_RELATED"),
    lambda t: edit(t, "#118 = PRODUCT_RELATED", "#5 = A();\n#119 = PRODUCT_RELATED"),     # duplicate #5
    lambda t: edit(t, "'distance_accuracy_value'", "'distance_accuracy_value"),          # unterminated string
])
def test_syntax_errors_are_step_errors_with_an_offset(tmp_path, mutate):
    with pytest.raises(StepError) as exc:
        import_step(write(tmp_path, mutate(fixture_text("cylinder"))), field="objects[0].path")
    assert exc.value.message.startswith("syntax:")
    assert re.search(r"at offset \d+$", exc.value.message)
    assert exc.value.field == "objects[0].path" and exc.value.entity is None


def test_comment_and_string_handling_through_the_importer(tmp_path):
    text = fixture_text("cylinder").replace("#16 = CLOSED_SHELL", "/* a comment */ #16 = CLOSED_SHELL")
    text = text.replace("#7 = PRODUCT('castplane cylinder'", "#7 = PRODUCT('castplane /* cylinder */'")
    assert expand(write(tmp_path, text), id="pillar") == [PILLAR]
    doc = parse(text)
    assert doc["entities"]["#7"][1][0] == "castplane /* cylinder */"


def test_unreadable_path_is_an_oserror(tmp_path):
    with pytest.raises(OSError) as exc:
        expand(tmp_path / "missing.step")
    assert "objects[0].path" in str(exc.value)


# --------------------------------------------------------------------------- recogniser negatives
def _unsupported(tmp_path, text, *needles):
    with pytest.raises(StepError) as exc:
        import_step(write(tmp_path, text))
    assert "unsupported" in exc.value.message
    for needle in needles:
        assert needle in exc.value.message
    return exc.value


def test_keyway_third_plane_is_unsupported(tmp_path):
    text = edit(fixture_text("cylinder"), "#16 = CLOSED_SHELL('',(#17,#105,#109));",
                "#16 = CLOSED_SHELL('',(#17,#105,#109,#200));")
    text = add_entities(text, """
#200 = ADVANCED_FACE('',(),#201,.T.);
#201 = PLANE('',#202);
#202 = AXIS2_PLACEMENT_3D('',#203,#204,#205);
#203 = CARTESIAN_POINT('',(-1.25E+03,6.E+03,0.));
#204 = DIRECTION('',(1.,0.,0.));
#205 = DIRECTION('',(0.,0.,1.));""")
    e = _unsupported(tmp_path, text, "#15: unsupported solid: faces {CYLINDRICAL_SURFACE: 1, PLANE: 3}")
    assert e.entity == "#15"


def test_tilted_cap_plane_is_unsupported(tmp_path):
    text = edit(fixture_text("cylinder"), "#46 = DIRECTION('',(0.,0.,1.));", "#46 = DIRECTION('',(0.001,0.,1.));")
    _unsupported(tmp_path, text, "faces {CYLINDRICAL_SURFACE: 1, PLANE: 2}", "perpendicular")


def test_two_cylindrical_faces_with_different_radii_are_unsupported(tmp_path):
    text = edit(fixture_text("cylinder"), "#16 = CLOSED_SHELL('',(#17,#105,#109));",
                "#16 = CLOSED_SHELL('',(#17,#105,#109,#200));")
    text = add_entities(text, "#200 = ADVANCED_FACE('',(),#201,.T.);\n#201 = CYLINDRICAL_SURFACE('',#32,301.);")
    _unsupported(tmp_path, text, "CYLINDRICAL_SURFACE: 2", "different radii")
    same = edit(text, "#201 = CYLINDRICAL_SURFACE('',#32,301.);", "#201 = CYLINDRICAL_SURFACE('',#32,300.);")
    assert expand(write(tmp_path, same, "same.step"), id="pillar") == [PILLAR]


def test_sphere_split_into_two_faces_is_a_sphere(tmp_path):
    text = edit(fixture_text("sphere"), "#16 = CLOSED_SHELL('',(#17));", "#16 = CLOSED_SHELL('',(#17,#40));")
    text = add_entities(text, """
#40 = ADVANCED_FACE('',(#41),#44,.T.);
#41 = FACE_BOUND('',#42,.T.);
#42 = VERTEX_LOOP('',#43);
#43 = VERTEX_POINT('',#21);
#44 = SPHERICAL_SURFACE('',#45,500.);
#45 = AXIS2_PLACEMENT_3D('',#24,#46,$);
#46 = DIRECTION('',(1.,0.,0.));""")
    assert strip_id(expand(write(tmp_path, text))[0]) == SPHERE
    other = edit(text, "#44 = SPHERICAL_SURFACE('',#45,500.);", "#44 = SPHERICAL_SURFACE('',#45,400.);")
    _unsupported(tmp_path, other, "SPHERICAL_SURFACE: 2")


def test_toroidal_surface_is_named(tmp_path):
    text = edit(fixture_text("cylinder"), "#31 = CYLINDRICAL_SURFACE('',#32,300.);",
                "#31 = TOROIDAL_SURFACE('',#32,300.,50.);")
    _unsupported(tmp_path, text, "TOROIDAL_SURFACE: 1", "PLANE: 2")


def test_no_manifold_solid_brep(tmp_path):
    text = edit(fixture_text("cylinder"), "#15 = MANIFOLD_SOLID_BREP('',#16);", "#15 = FACETED_BREP('',#16);")
    with pytest.raises(StepError) as exc:
        import_step(write(tmp_path, text))
    assert exc.value.message == "unsupported: no MANIFOLD_SOLID_BREP solid (found: FACETED_BREP ×1)"


def test_box_with_a_cylindrical_face_is_unsupported(tmp_path):
    text = edit(fixture_text("box"), "#152 = PLANE('',#153);", "#152 = CYLINDRICAL_SURFACE('',#153,100.);")
    _unsupported(tmp_path, text, "faces {CYLINDRICAL_SURFACE: 1, PLANE: 5}")


def test_recognise_solid_returns_none_for_unsupported():
    ents = parse(fixture_text("frustum"))["entities"]
    assert recognise_solid(ents, "#15", 1000.0, 1.0, 1.2e-3) is None
    ents = parse(fixture_text("cone"))["entities"]
    assert recognise_solid(ents, "#15", 1000.0, 1.0, 5e-3) == CONE


def test_degenerate_placement(tmp_path):
    text = edit(fixture_text("cylinder"), "#35 = DIRECTION('',(1.,0.,-0.));", "#35 = DIRECTION('',(0.,0.,2.));")
    with pytest.raises(StepError) as exc:
        import_step(write(tmp_path, text))
    assert "degenerate placement #32" in exc.value.message and exc.value.entity == "#32"


# --------------------------------------------------------------------------- euler_zyx_deg (§5.5.5)
def test_euler_round_trips():
    rng = random.Random(20261006)
    for _ in range(200):
        a = [rng.uniform(-180, 180), rng.uniform(-89, 89), rng.uniform(-180, 180)]
        R = euler_zyx_matrix(a)
        e = euler_zyx_deg(R)
        assert all(-180.0 < v <= 180.0 for v in e)
        assert np.allclose(euler_zyx_matrix(e), R, rtol=0, atol=1e-12)
        assert all(type(v) is float for v in e)


@pytest.mark.parametrize("ry", [90.0, -90.0])
@pytest.mark.parametrize("rx, rz", [(0.0, 0.0), (30.0, 0.0), (0.0, 40.0), (25.0, -70.0), (170.0, 100.0)])
def test_euler_gimbal_lock(rx, ry, rz):
    R = euler_zyx_matrix([rx, ry, rz])
    e = euler_zyx_deg(R)
    assert e[2] == 0.0
    assert np.allclose(euler_zyx_matrix(e), R, rtol=0, atol=1e-12)
    assert all(-180.0 < v <= 180.0 for v in e)


def test_euler_exact_180_with_signed_zeros():
    for z in (-0.0, 0.0):
        R = [[-1.0, z, 0.0], [z, -1.0, 0.0], [0.0, 0.0, 1.0]]
        e = euler_zyx_deg(R)
        assert e == [0.0, 0.0, 180.0] and all(math.copysign(1.0, v) == 1.0 for v in e)
    assert euler_zyx_deg(np.eye(3)) == [0.0, 0.0, 0.0]
    e = euler_zyx_deg(euler_zyx_matrix([0, 0, 30]))
    assert e[0] == e[1] == 0.0 and abs(e[2] - 30.0) < 1e-12
    if recorded_numpy_version() == np.__version__:      # atan2's last bit is per build (§5.5.5)
        assert e == [0.0, 0.0, 29.999999999999996]


@pytest.mark.parametrize("sy", [1.0, -1.0])
@pytest.mark.parametrize("r01", [0.0, -0.0])
def test_euler_gimbal_lock_signed_zero_is_180_not_minus_180(sy, r01):
    # R = Rz(0)·Ry(sy·90)·Rx(180): R01 = sy·sin(180°)·… is a zero of either sign; sy·R01 must not be -0.0
    R = [[0.0, r01, -sy], [0.0, -1.0, 0.0], [-sy, 0.0, 0.0]]
    e = euler_zyx_deg(R)
    assert e == [180.0, 90.0 * sy, 0.0] and all(-180.0 < v <= 180.0 for v in e)
    assert np.allclose(euler_zyx_matrix(e), R, rtol=0, atol=1e-12)
    assert euler_zyx_deg([[0, 0, 1], [0, -1, 0], [1, 0, 0]]) == [180.0, -90.0, 0.0]
    assert euler_zyx_deg([[0, 0, -1], [0, 1, 0], [1, 0, 0]]) == [0.0, -90.0, 0.0]


def test_cylinder_along_x_with_ref_z_is_180_not_minus_180(tmp_path):
    """A horizontal pipe: axis world +x, ref_direction +z -> frame [[0,0,1],[0,-1,0],[1,0,0]] (gimbal lock)."""
    b = Builder()
    b.units()
    a, ref, r, h = (1, 0, 0), (0, 0, 1), 300.0, 2400.0
    o, top = (0.0, 0.0, 0.0), (h, 0.0, 0.0)
    vb, vt = b.vertex((0.0, 0.0, r)), b.vertex((h, 0.0, r))
    eb = b.edge(vb, vb, b.add(f"CIRCLE('',{b.axis(o, a, ref)},{f(r)})"))
    et = b.edge(vt, vt, b.add(f"CIRCLE('',{b.axis(top, a, ref)},{f(r)})"))
    seam = b.edge(vb, vt, b.add(f"LINE('',{b.point((0.0, 0.0, r))},"
                                f"{b.add(f'VECTOR({chr(39)}{chr(39)},{b.direction(a)},1.)')})"))
    side = b.face([eb, seam, et, seam], b.add(f"CYLINDRICAL_SURFACE('',{b.axis(o, a, ref)},{f(r)})"))
    bottom = b.face([eb], b.add(f"PLANE('',{b.axis(o, (-1, 0, 0), ref)})"))
    topf = b.face([et], b.add(f"PLANE('',{b.axis(top, a, ref)})"))
    b.solid([side, topf, bottom])
    (obj,) = import_step(write(tmp_path, b.text()), obj_id="pipe")["objects"]
    assert obj == {"id": "pipe", "type": "cylinder", "radius": 0.3, "height": 2.4,
                   "transform": {"position": [0.0, 0.0, 0.0], "rotation_deg": [180.0, -90.0, 0.0]}}


# --------------------------------------------------------------------------- expansion object (§5.5.1)
def test_expand_step_object_validation_rows():
    def err(obj):
        with pytest.raises(SceneError) as exc:
            expand_step_object(dict({"id": "p", "type": "step", "path": "cylinder.step"}, **obj), "objects[0]", FIX)
        return exc.value.field

    assert err({"fallback": "x"}) == "objects[0].fallback"
    assert err({"transform": {"scale": 2}}) == "objects[0].transform.scale"
    assert err({"transform": {"position": [0, 0]}}) == "objects[0].transform.position"
    assert err({"path": ""}) == "objects[0].path"
    assert err({"path": 3}) == "objects[0].path"
    assert err({"id": "a.b"}) == "objects[0].id"
    assert err({"id": ""}) == "objects[0].id"
    with pytest.raises(SceneError) as exc:
        expand_step_object({"id": "p", "type": "step"}, "objects[0]", FIX)
    assert exc.value.field == "objects[0].path"


def test_expand_step_object_relative_to_base_dir_and_cwd(monkeypatch):
    obj = {"id": "pillar", "type": "step", "path": "cylinder.step", "unknown": 1}
    assert expand_step_object(obj, "objects[0]", FIX) == ([PILLAR], [])
    monkeypatch.chdir(FIX)
    assert expand_step_object(obj, "objects[0]", None) == ([PILLAR], [])
    with pytest.raises(StepError) as exc:
        expand_step_object(dict(obj, path="frustum.step"), "objects[3]", None)
    assert exc.value.field == "objects[3].path" and exc.value.entity == "#15"


def test_user_transform_composes():
    (obj,) = expand(FIX / "cylinder.step", id="pillar", transform={"rotation_deg": [0, 0, 90], "position": [1, 0, 0]})
    assert obj["transform"]["position"] == pytest.approx([-5.0, -1.5, 0.0], abs=1e-12)
    assert obj["transform"]["rotation_deg"] == pytest.approx([0.0, 0.0, 90.0], abs=1e-12)
    inline = {"id": "pillar", "type": "cylinder", "radius": 0.3, "height": 2.4,
              "transform": {"position": [-5.0, -1.5, 0.0], "rotation_deg": [0.0, 0.0, 90.0]}}
    tmpl = copy.deepcopy(DEFAULT_SCENE_TEMPLATE)
    tmpl["camera"] = {"position": [0.0, -12.0, 2.0], "target": [-5.0, -1.5, 1.0], "focal_length_mm": 35,
                      "frame_mm": [36, 24]}
    a = _geometry(dict(tmpl, objects=[obj]))["points"]
    b = _geometry(dict(tmpl, objects=[inline]))["points"]
    assert set(a) == set(b)
    for name in a:
        assert np.allclose(a[name]["world"], b[name]["world"], rtol=0, atol=1e-9), name


def test_expansion_is_deterministic():
    obj = {"id": "part", "type": "step", "path": "two_solids.step"}
    one = json.dumps(expand_step_object(obj, "objects[0]", FIX), sort_keys=True)
    two = json.dumps(expand_step_object(obj, "objects[0]", FIX), sort_keys=True)
    assert one == two


# --------------------------------------------------------------------------- tessellation fallback (§5.5.7)
def test_mesh_fallback_without_ocp_is_an_import_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_ocp(name, *args, **kwargs):
        if name == "OCP" or name.startswith("OCP."):
            raise ImportError("No module named 'OCP'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_ocp)
    with pytest.raises(ImportError, match=r"castplane\[step\]"):
        expand(FIX / "frustum.step", fallback="mesh")
    # recognised solids never need OCP
    assert expand(FIX / "cylinder.step", id="pillar", fallback="mesh") == [PILLAR]


def test_mesh_object_from_triangles_shape():
    tri = {"vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
           "faces": [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], "cascade_unit": "MM"}
    obj = S.mesh_object_from_triangles("t", tri, None)
    assert obj == {"id": "t", "type": "mesh", "data": {"vertices": tri["vertices"], "faces": tri["faces"],
                                                         "smooth_groups": [0, 0, 0, 0]}}
    assert S.mesh_object_from_triangles("t", tri, {"position": [1.0, 0.0, 0.0]})["transform"] == {"position": [1.0, 0.0, 0.0]}
    castplane.validate_scene(dict(copy.deepcopy(DEFAULT_SCENE_TEMPLATE), objects=[obj]))


def test_mesh_fallback_with_ocp():
    pytest.importorskip("OCP")
    rep = import_step(FIX / "frustum.step", fallback="mesh", obj_id="f")
    (obj,) = rep["objects"]
    assert obj["type"] == "mesh" and rep["solids"][0]["kind"] == "mesh"
    assert rep["notes"] == [make_step_warning("STEP_SOLID_TESSELLATED", ["#15"])]
    assert "transform" not in obj
    scene = castplane.validate_scene(dict(copy.deepcopy(DEFAULT_SCENE_TEMPLATE), objects=[obj]))
    castplane.render(scene)
    raw = {"position": [1, 0, 0]}
    moved = import_step(FIX / "frustum.step", fallback="mesh", obj_id="f", transform=raw)["objects"][0]
    assert moved["transform"] == {"position": [1, 0, 0]} and type(moved["transform"]["position"][0]) is int
    assert moved["data"] == obj["data"]
    (via_expand,), _ = expand_step_object({"id": "f", "type": "step", "path": "frustum.step", "fallback": "mesh",
                                           "transform": raw}, "objects[0]", FIX)
    assert via_expand == moved and raw == {"position": [1, 0, 0]}
    tri = S.tessellate_step(FIX / "frustum.step")
    n = len(tri["vertices"])
    assert tri["cascade_unit"] == "MM" and len(tri["faces"]) >= 100
    assert all(0 <= i < n for face in tri["faces"] for i in face)
    assert len(S.tessellate_step(FIX / "cylinder.step")["vertices"]) >= 100


# --------------------------------------------------------------------------- performance (spec §8)
def test_step_import_is_not_slow():
    for name in FIXTURES:
        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            try:
                import_step(FIX / f"{name}.step")
            except StepError:
                pass
            times.append(time.perf_counter() - t0)
        assert min(times) < 0.5, name


def test_fixture_generator_is_in_sync():
    """``tools/make_step_fixtures.py --check`` regenerates the set byte-identically (needs OCP; the
    committed bytes are those of cadquery-ocp 8.0.1.1.0, so another OCC build may legitimately differ)."""
    pytest.importorskip("OCP")
    import importlib.metadata
    import subprocess
    import sys

    try:
        version = importlib.metadata.version("cadquery-ocp")
    except importlib.metadata.PackageNotFoundError:
        version = None
    if version != "8.0.1.1.0":
        pytest.skip(f"fixtures were written by cadquery-ocp 8.0.1.1.0, found {version}")

    proc = subprocess.run([sys.executable, str(ROOT / "tools" / "make_step_fixtures.py"), "--check"],
                          cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]


def test_axis_aligned_occ_box_is_exact(tmp_path):
    """Contract §5.5.5: an axis-aligned OCC box expands to ``rotation_deg [0, 0, 0]`` and the exact size."""
    pytest.importorskip("OCP")
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_step_fixtures", ROOT / "tools" / "make_step_fixtures.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    gen.write_step(BRepPrimAPI_MakeBox(gp_Pnt(-500, -400, 0), 1000, 800, 600).Shape(), tmp_path / "b.step")
    (obj,) = import_step(tmp_path / "b.step")["objects"]
    assert obj == {"id": "b", "type": "box", "size": [1.0, 0.8, 0.6],
                   "transform": {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]}}


def test_benchmark_compound_option_of_the_generator(tmp_path):
    """Review fix: the informational 200-solid row of benchmarks/README.md is reproducible with
    ``tools/make_step_fixtures.py --bench-solids N --bench-out PATH`` (here N = 3)."""
    pytest.importorskip("OCP")
    import subprocess
    import sys

    out = tmp_path / "bench3.step"
    proc = subprocess.run([sys.executable, str(ROOT / "tools" / "make_step_fixtures.py"), "--bench-solids", "3",
                           "--bench-out", str(out)], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    objects = import_step(out)["objects"]
    assert [o["id"] for o in objects] == ["bench3_0", "bench3_1", "bench3_2"]
    assert [o["type"] for o in objects] == ["cylinder"] * 3
    assert [o["transform"]["position"] for o in objects] == [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]
    assert "Open CASCADE STEP translator" not in out.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- registry, expansion (§5.0.2, §5.5.1)
BASIC = ROOT / "examples" / "basic.json"
STEP_PILLAR = {"id": "pillar", "type": "step", "path": "cylinder.step"}


def _basic() -> dict:
    return json.loads(BASIC.read_text(encoding="utf-8"))


def test_io_registry_entries():
    assert cpio.EXPANDERS["step"] is S.expand_step_object
    assert cpio.EXPANDERS["mesh"] is cpio.expand_mesh_object
    assert cpio.EXTENSION_LOADERS == {".step": S.tessellate_step, ".stp": S.tessellate_step}
    for code, message in STEP_WARNING_CODES.items():
        assert cpio.IMPORT_NOTE_CODES[code] == message
    assert set(cpio.IMPORT_NOTE_CODES) == {"IMPORT_SPOT_AS_POINT", "IMPORT_CAMERA_DROPPED", "IMPORT_NO_CAMERA_DEFAULT",
                                           "IMPORT_NO_LIGHT_DEFAULT", *STEP_WARNING_CODES}
    assert {"EXPANDERS", "EXTENSION_LOADERS", "IMPORT_NOTE_CODES", "expand_scene", "load_expanded_scene",
            "load_mesh_file", "SUPPORTED_EXTENSIONS"} <= set(cpio.__all__)
    from castplane.io import cli as io_cli

    assert io_cli.__all__ == ["add_import_parser", "cmd_import"]
    assert castplane.scene.LOADER_TYPES == ("step",)


def test_validate_scene_rejects_an_unexpanded_step_object():
    scene = dict(copy.deepcopy(DEFAULT_SCENE_TEMPLATE), objects=[STEP_PILLAR])
    with pytest.raises(SceneError) as exc:
        castplane.validate_scene(scene)
    assert exc.value.field == "objects[0].type"
    assert exc.value.message == ("loader object type 'step' must be expanded first "
                                 "(castplane.io.expand_scene or 'castplane import')")
    with pytest.raises(SceneError) as exc:                  # unknown types keep the generic message
        castplane.validate_scene(dict(scene, objects=[{"id": "p", "type": "torus"}]))
    assert exc.value.field == "objects[0].type" and exc.value.message.startswith("must be one of ")


def test_load_expanded_scene_acceptance_cylinder_is_the_basic_example():
    """Spec §10 M8 acceptance through the loader layer: ``examples/basic.json`` with its pillar as a
    ``step`` object renders byte-equal to the inline example and passes the conformance comparison."""
    raw = _basic_with("pillar", STEP_PILLAR)
    scene, notes = cpio.load_expanded_scene(raw, base_dir=FIX)
    assert notes == []
    assert scene == castplane.load_scene(str(BASIC))
    doc = castplane.render(scene)["geometry"]
    assert geometry_dumps(doc) == geometry_dumps(_geometry(_basic()))
    expected = json.loads((EXPECTED / "example_basic.json").read_text(encoding="utf-8"))
    assert compare_documents(expected, json.loads(geometry_dumps(doc)), "example_basic") == []
    hand = {"pillar.g0.base": (-1.7552526894158411, 5.8423736552920795, 0.0),
            "pillar.g1.base": (-1.220747310584159, 6.10962634470792, 0.0),
            "pillar.g0.top.shadow.lamp": (-5.584894920868585, 12.043916175929343, 0.0),
            "pillar.g1.top.shadow.lamp": (-3.884195988222324, 12.894265642252474, 0.0)}
    for name, world in hand.items():
        assert np.allclose(doc["points"][name]["world"], world, rtol=0, atol=1e-9), name
    assert raw["objects"][1] == STEP_PILLAR                 # the input is not modified


def test_load_expanded_scene_from_a_file_resolves_relative_paths(tmp_path, monkeypatch):
    (tmp_path / "parts").mkdir()
    (tmp_path / "parts" / "pillar.step").write_bytes((FIX / "cylinder.step").read_bytes())
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(json.dumps(_basic_with("pillar", {"id": "pillar", "type": "step",
                                                            "path": "parts/pillar.step"})), encoding="utf-8")
    monkeypatch.chdir(ROOT)                                 # base_dir is the scene's directory, not the cwd
    scene, notes = cpio.load_expanded_scene(str(scene_path))
    assert notes == [] and scene == castplane.load_scene(str(BASIC))
    scene2, _ = cpio.load_expanded_scene(scene_path)        # a PathLike works too
    assert scene2 == scene
    with pytest.raises(OSError, match=r"objects\[1\]\.path"):  # a dict resolves against the cwd
        cpio.load_expanded_scene(json.loads(scene_path.read_text(encoding="utf-8")))
    monkeypatch.chdir(tmp_path)
    assert cpio.load_expanded_scene(json.loads(scene_path.read_text(encoding="utf-8")))[0] == scene


def test_expand_scene_keeps_list_positions_and_passes_other_entries_through():
    crate = {"id": "crate", "type": "box", "size": [1, 0.8, 0.6], "transform": {"position": [2, 4, 0]}}
    scene = {"objects": [crate, {"id": "part", "type": "step", "path": "two_solids.step"}, 5,
                         {"id": "ball", "type": "sphere", "radius": 0.2}], "extra": {"k": [1]}}
    before = copy.deepcopy(scene)
    out, notes = cpio.expand_scene(scene, FIX)
    assert scene == before and notes == []
    assert [o["id"] if isinstance(o, dict) else o for o in out["objects"]] == ["crate", "part_0", "part_1", 5, "ball"]
    assert out["objects"][0] == crate and out["objects"][0] is not crate
    assert out["extra"] == {"k": [1]} and out["extra"] is not scene["extra"]
    assert strip_id(out["objects"][1]) == strip_id(PILLAR) and strip_id(out["objects"][2]) == SPHERE
    again, again_notes = cpio.expand_scene(out, FIX)        # idempotent on an expanded scene
    assert again == out and again_notes == []
    assert json.dumps(cpio.expand_scene(scene, FIX), sort_keys=True) == json.dumps(cpio.expand_scene(scene, FIX),
                                                                                   sort_keys=True)


def test_expand_scene_passes_non_list_objects_through_to_validation():
    scene = dict(copy.deepcopy(DEFAULT_SCENE_TEMPLATE), objects={"id": "pillar", "type": "step"})
    out, notes = cpio.expand_scene(scene, FIX)
    assert out == scene and notes == []
    with pytest.raises(SceneError) as exc:
        cpio.load_expanded_scene(scene, base_dir=FIX)
    assert exc.value.field == "objects"
    assert cpio.expand_scene([1, 2], FIX) == ([1, 2], [])
    with pytest.raises(SceneError):
        cpio.load_expanded_scene([1, 2])


def test_expanded_id_clash_is_reported_at_the_later_object():
    scene = dict(copy.deepcopy(DEFAULT_SCENE_TEMPLATE),
                 objects=[{"id": "part", "type": "step", "path": "two_solids.step"},
                          {"id": "part_1", "type": "sphere", "radius": 0.2}])
    with pytest.raises(SceneError) as exc:
        cpio.load_expanded_scene(scene, base_dir=FIX)
    assert exc.value.field == "objects[2].id"


def test_expand_scene_error_field_paths(tmp_path):
    def scene(step_obj):
        return dict(copy.deepcopy(DEFAULT_SCENE_TEMPLATE),
                    objects=[{"id": "a", "type": "sphere", "radius": 0.1}, {"id": "b", "type": "sphere", "radius": 0.1},
                             dict({"id": "s", "type": "step"}, **step_obj)])

    with pytest.raises(StepError) as exc:
        cpio.expand_scene(scene({"path": "frustum.step"}), FIX)
    assert exc.value.field == "objects[2].path" and exc.value.entity == "#15"
    assert "unsupported solid" in exc.value.message
    for obj, field in (({"path": "two_solids.step", "solid": 2}, "objects[2].solid"),
                       ({"path": "two_solids.step", "solid": True}, "objects[2].solid"),
                       ({"path": "cylinder.step", "fallback": "x"}, "objects[2].fallback"),
                       ({"path": "cylinder.step", "transform": {"scale": 2}}, "objects[2].transform.scale"),
                       ({}, "objects[2].path")):
        with pytest.raises(SceneError) as exc:
            cpio.expand_scene(scene(obj), FIX)
        assert exc.value.field == field, obj
    with pytest.raises(OSError, match=r"objects\[2\]\.path"):
        cpio.expand_scene(scene({"path": "missing.step"}), tmp_path)
    with pytest.raises(StepError) as exc:                   # a syntax error names the field and the offset
        (tmp_path / "bad.step").write_text("ISO-10303-21;\nHEADER;", encoding="utf-8")
        cpio.expand_scene(scene({"path": "bad.step"}), tmp_path)
    assert exc.value.field == "objects[2].path" and exc.value.message.startswith("syntax:")


def test_expand_scene_merges_notes_and_keeps_them_out_of_the_document(tmp_path):
    b = Builder()
    b.cylinder(300.0, 2400.0, (-1500.0, 6000.0, 0.0))
    write(tmp_path, b.text(), "nounits.step")
    scene = _basic_with("pillar", {"id": "pillar", "type": "step", "path": "nounits.step"})
    scene["objects"].append({"id": "post", "type": "step", "path": "nounits.step",
                             "transform": {"position": [3, 0, 0]}})
    expanded, notes = cpio.load_expanded_scene(scene, base_dir=tmp_path)
    assert [n["code"] for n in notes] == ["STEP_ANGLE_UNIT_ASSUMED_RAD", "STEP_UNIT_ASSUMED_MM"]
    assert all(n["ids"] == [] for n in notes)
    assert expanded["objects"][1] == castplane.load_scene(str(BASIC))["objects"][1]
    doc = castplane.render(expanded)["geometry"]
    assert not any(w["code"].startswith(("STEP_", "IMPORT_")) for w in doc["warnings"])


def _components(faces) -> int:
    """Number of connected components of a triangle list (triangles sharing a vertex index)."""
    parent = {}

    def find(i):
        while parent.setdefault(i, i) != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b, c in faces:
        for u in (b, c):
            ra, ru = find(a), find(u)
            if ra != ru:
                parent[ru] = ra
    return len({find(i) for f in faces for i in f})


def test_tessellation_every_face_contributes_triangles():
    """§5.5.10: every B-rep face of the frustum contributes ≥ 1 triangle.  The node blocks are not
    welded, so each face's triangulation is its own connected component: 3 components = 3 faces."""
    pytest.importorskip("OCP")
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer

    reader = STEPControl_Reader()
    reader.ReadFile(str(FIX / "frustum.step"))
    reader.TransferRoots()
    explorer, n_faces = TopExp_Explorer(reader.OneShape(), TopAbs_FACE), 0
    while explorer.More():
        n_faces, _ = n_faces + 1, explorer.Next()
    tri = S.tessellate_step(FIX / "frustum.step")
    assert n_faces == 3 and _components(tri["faces"]) == n_faces
    assert all(len(set(f)) == 3 for f in tri["faces"])


def test_mesh_object_with_a_step_path_is_tessellated_directly(tmp_path):
    pytest.importorskip("OCP")
    scene = dict(copy.deepcopy(DEFAULT_SCENE_TEMPLATE), objects=[{"id": "f", "type": "mesh", "path": "frustum.step"}])
    out, notes = cpio.expand_scene(scene, FIX)
    (obj,) = out["objects"]
    tri = S.tessellate_step(FIX / "frustum.step")
    assert notes == [] and obj["path"] == "frustum.step"
    assert obj["data"] == S.mesh_object_from_triangles("f", tri, None)["data"]
    assert cpio.load_mesh_file(FIX / "frustum.step") == obj["data"]
    castplane.render(castplane.validate_scene(out))
    # case-insensitive extension, and no analytic recognition: a cylinder stays a mesh
    (tmp_path / "C.STP").write_bytes((FIX / "cylinder.step").read_bytes())
    out, _ = cpio.expand_scene(dict(scene, objects=[{"id": "c", "type": "mesh", "path": "C.STP"}]), tmp_path)
    assert out["objects"][0]["type"] == "mesh" and len(out["objects"][0]["data"]["faces"]) >= 100
    with pytest.raises(SceneError) as exc:
        cpio.expand_scene(dict(scene, objects=[{"id": "f", "type": "mesh", "path": "frustum.step", "node": 0}]), FIX)
    assert exc.value.field == "objects[0].node"


def test_a_step_file_occ_cannot_transfer_is_a_scene_error(tmp_path, capsys):
    """Review fix: OCC's ReadFile returns RetDone for a file it cannot transfer; that is a StepError /
    SceneError at objects[i].path (exit 2), never OCP's Standard_ConstructionError (traceback, exit 1)."""
    pytest.importorskip("OCP")
    empty = tmp_path / "empty.step"
    empty.write_text("ISO-10303-21;\nHEADER;ENDSEC;DATA;ENDSEC;END-ISO-10303-21;\n", encoding="utf-8")
    with pytest.raises(StepError) as err:
        S.tessellate_step(empty)
    assert err.value.field == "step" and err.value.entity is None
    assert re.fullmatch(r"unsupported: OCP cannot read .*\(no transferable shape\)", err.value.message)
    scene = dict(copy.deepcopy(DEFAULT_SCENE_TEMPLATE), objects=[{"id": "m", "type": "mesh", "path": "empty.step"}])
    with pytest.raises(SceneError) as exc:
        cpio.expand_scene(scene, tmp_path)
    assert type(exc.value) is SceneError and exc.value.field == "objects[0].path"
    assert exc.value.message.startswith("unsupported: OCP cannot read ")       # the bare loader message (§5.0.2)
    path = tmp_path / "m.json"
    path.write_text(json.dumps(scene), encoding="utf-8")
    code, _, stderr = run(capsys, "validate", path)
    assert code == 2 and stderr.startswith("error: objects[0].path: unsupported: OCP cannot read ")


def _without_ocp(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_ocp(name, *args, **kwargs):
        if name == "OCP" or name.startswith("OCP."):
            raise ImportError("No module named 'OCP'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_ocp)


def test_mesh_object_with_a_step_path_without_ocp_is_an_import_error(monkeypatch):
    _without_ocp(monkeypatch)
    scene = dict(copy.deepcopy(DEFAULT_SCENE_TEMPLATE), objects=[{"id": "f", "type": "mesh", "path": "frustum.step"}])
    with pytest.raises(ImportError, match=r"castplane\[step\]"):
        cpio.expand_scene(scene, FIX)
    with pytest.raises(ImportError, match=r"castplane\[step\]"):
        cpio.expand_scene(dict(scene, objects=[{"id": "f", "type": "step", "path": "frustum.step",
                                                "fallback": "mesh"}]), FIX)
    # the analytic path never imports OCP
    assert cpio.load_expanded_scene(_basic_with("pillar", STEP_PILLAR), base_dir=FIX)[0] == \
        castplane.load_scene(str(BASIC))


# --------------------------------------------------------------------------- CLI (§5.5.8, §5.0.2)
def run(capsys, *argv) -> tuple:
    """``castplane <argv>`` in-process -> ``(exit code, stdout, stderr)``."""
    code = cli.main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def _step_scene_file(tmp_path, name="basic.json", pillar_path="parts/pillar.step") -> pathlib.Path:
    """``examples/basic.json`` with its pillar as a ``step`` object referencing a copy of the fixture."""
    (tmp_path / "parts").mkdir(exist_ok=True)
    (tmp_path / "parts" / "pillar.step").write_bytes((FIX / "cylinder.step").read_bytes())
    path = tmp_path / name
    path.write_text(json.dumps(_basic_with("pillar", {"id": "pillar", "type": "step", "path": pillar_path}),
                               indent=1), encoding="utf-8")
    return path


def test_cli_import_writes_a_valid_scene(tmp_path, capsys):
    out = tmp_path / "s.json"
    code, stdout, stderr = run(capsys, "import", FIX / "cylinder.step", "-o", out)
    assert code == 0 and stdout == f"{out}\n"
    assert "note: IMPORT_NO_CAMERA_DEFAULT []: " in stderr and "note: IMPORT_NO_LIGHT_DEFAULT []: " in stderr
    text = out.read_text(encoding="utf-8")
    scene = json.loads(text)
    assert text == json.dumps(scene, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    assert scene["objects"] == [dict(PILLAR, id="cylinder")]
    assert [n["code"] for n in scene["meta"]["import_notes"]] == ["IMPORT_NO_CAMERA_DEFAULT", "IMPORT_NO_LIGHT_DEFAULT"]
    assert scene["receivers"] == [{"id": "ground", "type": "plane", "normal": [0.0, 0.0, 1.0], "offset": 0.0}]
    code, stdout, _ = run(capsys, "validate", out)
    assert code == 0 and stdout.startswith("ok: 1 object(s), 1 light(s), 1 receiver(s)")
    # determinism: a second run writes identical bytes; stdout mode writes the same text
    out2 = tmp_path / "s2.json"
    assert run(capsys, "import", FIX / "cylinder.step", "-o", out2, "-q") == (0, "", "")
    assert out2.read_bytes() == out.read_bytes()
    code, stdout, _ = run(capsys, "import", FIX / "cylinder.step")
    assert code == 0 and stdout == text
    # the default id is the sanitised file stem
    odd = tmp_path / "my pillar.v2.step"
    odd.write_bytes((FIX / "cylinder.step").read_bytes())
    code, stdout, _ = run(capsys, "import", odd, "-q")
    assert code == 0 and [o["id"] for o in json.loads(stdout)["objects"]] == ["my_pillar_v2"]


def test_cli_import_into_basic_appends_and_keeps_the_raw_blocks(tmp_path, capsys):
    out = tmp_path / "s.json"
    code, stdout, _ = run(capsys, "import", FIX / "cylinder.step", "--into", BASIC, "--id", "post", "-o", out)
    assert code == 0 and stdout == f"{out}\n"
    basic, scene = _basic(), json.loads(out.read_text(encoding="utf-8"))
    for key in ("version", "units", "up", "lights", "receivers", "camera", "output"):
        assert json.dumps(scene[key], sort_keys=True) == json.dumps(basic[key], sort_keys=True), key
    assert scene["objects"] == basic["objects"] + [dict(PILLAR, id="post")]
    crate = next(o for o in scene["objects"] if o["id"] == "crate")
    assert crate == next(o for o in basic["objects"] if o["id"] == "crate")
    assert all(type(v) is int for v in crate["transform"]["rotation_deg"])     # the raw [0, 0, 30]
    assert scene["meta"] == {"import_notes": []}
    assert run(capsys, "validate", out)[0] == 0
    # unknown keys of SCENE are copied verbatim
    into = tmp_path / "with_description.json"
    into.write_text(json.dumps(dict(basic, description="a hand-made scene", extra={"k": [1, 2]})), encoding="utf-8")
    code, stdout, _ = run(capsys, "import", FIX / "sphere.step", "--into", into, "-q")
    got = json.loads(stdout)
    assert code == 0 and got["description"] == "a hand-made scene" and got["extra"] == {"k": [1, 2]}
    assert got["objects"][-1] == dict(SPHERE, id="sphere")
    # an --id already used by SCENE is an error
    code, _, stderr = run(capsys, "import", FIX / "cylinder.step", "--into", BASIC, "--id", "pillar")
    assert code == 2 and stderr.startswith("error: --id: ")


def test_cli_import_into_a_scene_holding_a_step_object(tmp_path, capsys):
    into = _step_scene_file(tmp_path)
    (tmp_path / "out").mkdir()
    out = tmp_path / "out" / "s.json"
    code, _, _ = run(capsys, "import", FIX / "sphere.step", "--into", into, "-o", out, "-q")
    assert code == 0
    scene = json.loads(out.read_text(encoding="utf-8"))
    # SCENE's own step object stays raw, its relative path rewritten for the output's directory
    assert scene["objects"][1] == {"id": "pillar", "type": "step", "path": "../parts/pillar.step"}
    assert scene["objects"][-1] == dict(SPHERE, id="sphere")
    expanded, _ = cpio.load_expanded_scene(str(out))
    assert [o["type"] for o in expanded["objects"]] == ["box", "cylinder", "sphere"]
    # the ids a step object of SCENE expands to are taken: a file stem part_0 is de-duplicated
    two = tmp_path / "two.json"
    (tmp_path / "parts" / "two_solids.step").write_bytes((FIX / "two_solids.step").read_bytes())
    two.write_text(json.dumps(dict(copy.deepcopy(DEFAULT_SCENE_TEMPLATE),
                                   objects=[{"id": "part", "type": "step", "path": "parts/two_solids.step"}])),
                   encoding="utf-8")
    stem = tmp_path / "part_0.step"
    stem.write_bytes((FIX / "cone.step").read_bytes())
    code, stdout, _ = run(capsys, "import", stem, "--into", two, "-q")
    assert code == 0 and [o["id"] for o in json.loads(stdout)["objects"]] == ["part", "part_0_2"]
    code, _, stderr = run(capsys, "import", stem, "--into", two, "--id", "part_1")
    assert code == 2 and stderr.startswith("error: --id: ")
    # review fix: the <id>_<k> ids derived from an explicit --id are never renamed (§5.2.8 (4))
    has = tmp_path / "has_part_0.json"
    has.write_text(json.dumps(dict(copy.deepcopy(DEFAULT_SCENE_TEMPLATE), objects=[dict(SPHERE, id="part_0")])),
                   encoding="utf-8")
    code, stdout, stderr = run(capsys, "import", FIX / "two_solids.step", "--id", "part", "--into", has)
    assert code == 2 and stdout == "" and stderr.startswith("error: --id: 'part_0' (derived from --id 'part') ")
    code, stdout, _ = run(capsys, "import", FIX / "two_solids.step", "--into", has, "-q")    # a default id is renamed
    assert code == 0 and [o["id"] for o in json.loads(stdout)["objects"]] == ["part_0", "two_solids_0",
                                                                               "two_solids_1"]
    # review fix: a non-list objects of SCENE is reported at objects, not objects[0]
    bad = tmp_path / "bad_objects.json"
    bad.write_text(json.dumps(dict(copy.deepcopy(DEFAULT_SCENE_TEMPLATE), objects={"a": 1})), encoding="utf-8")
    code, _, stderr = run(capsys, "import", FIX / "cylinder.step", "--into", bad)
    assert code == 2 and stderr == "error: objects: must be a non-empty list\n"


def test_cli_import_solid_selection_and_quiet(capsys):
    code, stdout, stderr = run(capsys, "import", FIX / "two_solids.step", "--solid", "1", "-q")
    assert code == 0 and stderr == ""
    assert json.loads(stdout)["objects"] == [dict(SPHERE, id="two_solids")]
    code, stdout, _ = run(capsys, "import", FIX / "two_solids.step", "--id", "part", "-q")
    assert [o["id"] for o in json.loads(stdout)["objects"]] == ["part_0", "part_1"]
    code, _, stderr = run(capsys, "import", FIX / "two_solids.step", "--solid", "2")
    assert code == 2 and stderr == "error: step.solid: file has 2 solid(s)\n"
    code, _, stderr = run(capsys, "import", FIX / "two_solids.step", "--solid", "-1")
    assert code == 2 and stderr.startswith("error: step.solid: ")
    with pytest.raises(SystemExit) as exc:                  # not an integer: an argparse usage error
        cli.main(["import", str(FIX / "two_solids.step"), "--solid", "1.0"])
    assert exc.value.code == 2


def test_cli_import_errors_and_exit_codes(tmp_path, capsys):
    code, stdout, stderr = run(capsys, "import", FIX / "frustum.step")
    assert code == 2 and stdout == ""
    assert stderr.startswith("error: step: #15: unsupported solid: faces {CONICAL_SURFACE: 1, PLANE: 2}")
    assert run(capsys, "import", tmp_path / "missing.step")[0] == 1
    (tmp_path / "bad.step").write_text("ISO-10303-21;\nHEADER;\n", encoding="utf-8")
    code, _, stderr = run(capsys, "import", tmp_path / "bad.step")
    assert code == 2 and stderr.startswith("error: step: syntax: ")
    # an option of the other family is a usage error (exit 2)
    for argv in ((FIX / "cylinder.step", "--weld", "1e-6"), (FIX / "cylinder.step", "--inline"),
                 (FIX / "cylinder.step", "--up", "y"), (FIX / "cylinder.step", "--node", "0")):
        code, _, stderr = run(capsys, "import", *argv)
        assert code == 2 and "is a mesh option" in stderr, argv
    obj_file = ROOT / "tests" / "fixtures" / "meshes" / "box_split.obj"
    for argv in ((obj_file, "--solid", "0"), (obj_file, "--fallback", "mesh"), (obj_file, "--fallback", "error")):
        code, _, stderr = run(capsys, "import", *argv)
        assert code == 2 and "is a STEP option" in stderr, argv
    with pytest.raises(SystemExit) as exc:
        cli.main(["import", str(FIX / "frustum.step"), "--fallback", "tessellate"])
    assert exc.value.code == 2


def test_cli_import_fallback_mesh_with_ocp(tmp_path, capsys):
    pytest.importorskip("OCP")
    out = tmp_path / "f.json"
    code, _, stderr = run(capsys, "import", FIX / "frustum.step", "--fallback", "mesh", "-o", out)
    assert code == 0 and "note: STEP_SOLID_TESSELLATED ['#15']: " in stderr
    scene = json.loads(out.read_text(encoding="utf-8"))
    (obj,) = scene["objects"]
    assert obj["id"] == "frustum" and obj["type"] == "mesh" and "path" not in obj
    assert obj["data"] == S.mesh_object_from_triangles("frustum", S.tessellate_step(FIX / "frustum.step"), None)["data"]
    assert "STEP_SOLID_TESSELLATED" in [n["code"] for n in scene["meta"]["import_notes"]]
    assert run(capsys, "validate", out)[0] == 0


def test_cli_import_fallback_mesh_without_ocp_exits_3(capsys, monkeypatch):
    _without_ocp(monkeypatch)
    code, stdout, stderr = run(capsys, "import", FIX / "frustum.step", "--fallback", "mesh")
    assert code == 3 and stdout == "" and "castplane[step]" in stderr
    assert run(capsys, "import", FIX / "cylinder.step", "--fallback", "mesh", "-q")[0] == 0


def test_cli_render_validate_info_stages_expand_step_objects(tmp_path, capsys, monkeypatch):
    scene = _step_scene_file(tmp_path)
    monkeypatch.chdir(ROOT / "docs")                        # paths resolve against the scene file, not the cwd
    assert run(capsys, "render", scene, "-o", tmp_path / "out", "-q") == (0, "", "")
    assert run(capsys, "render", BASIC, "-o", tmp_path / "ref", "-q") == (0, "", "")
    for name in ("basic.json", "basic.svg"):
        assert (tmp_path / "out" / name).read_bytes() == (tmp_path / "ref" / name).read_bytes(), name
    code, stdout, _ = run(capsys, "validate", scene)
    assert code == 0 and stdout.startswith("ok: 2 object(s), 1 light(s), 1 receiver(s)")
    code, stdout, _ = run(capsys, "info", scene)
    assert code == 0 and "objects: 2 (crate:box, pillar:cylinder)" in stdout and "step" not in stdout.split("\n")[1]
    assert run(capsys, "stages", scene, "-o", tmp_path / "stages.json", "-q") == (0, "", "")
    assert run(capsys, "stages", BASIC, "-o", tmp_path / "stages_ref.json", "-q") == (0, "", "")
    assert (tmp_path / "stages.json").read_bytes() == (tmp_path / "stages_ref.json").read_bytes()
    # validate counts the objects after expansion, and prints the importer notes
    two = tmp_path / "two.json"
    two.write_text(json.dumps(dict(copy.deepcopy(DEFAULT_SCENE_TEMPLATE),
                                   objects=[{"id": "part", "type": "step", "path": str(FIX / "two_solids.step")}])),
                   encoding="utf-8")
    code, stdout, _ = run(capsys, "validate", two)
    assert code == 0 and stdout.startswith("ok: 2 object(s)")
    b = Builder()
    b.cylinder(300.0, 2400.0, (-1500.0, 6000.0, 0.0))
    write(tmp_path / "parts", b.text(), "pillar.step")       # the same pillar without a unit context
    code, _, stderr = run(capsys, "render", scene, "-o", tmp_path / "out2")
    assert code == 0 and "note: STEP_UNIT_ASSUMED_MM []: " in stderr
    assert "note: STEP_ANGLE_UNIT_ASSUMED_RAD []: " in stderr
    assert "STEP_" not in (tmp_path / "out2" / "basic.json").read_text(encoding="utf-8")
    assert run(capsys, "validate", scene, "-q") == (0, "", "")
    # a step error inside a scene names the object's path field
    bad = tmp_path / "bad.json"
    frustum = {"id": "pillar", "type": "step", "path": str(FIX / "frustum.step")}
    bad.write_text(json.dumps(_basic_with("pillar", frustum)), encoding="utf-8")
    code, _, stderr = run(capsys, "validate", bad)
    assert code == 2 and stderr.startswith("error: objects[1].path: #15: unsupported solid")
    bad.write_text(json.dumps(_basic_with("pillar", {"id": "pillar", "type": "step", "path": "missing.step"})),
                   encoding="utf-8")
    assert run(capsys, "render", bad, "-o", tmp_path / "out3")[0] == 1


# --------------------------------------------------------------------------- documents (§5.5.12, §5.5 intro)
def test_step_report_has_the_required_structure():
    text = (ROOT / "docs" / "STEP.md").read_text(encoding="utf-8")
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert [h.split()[1] for h in headings] == [f"{k}." for k in range(1, 10)], headings
    for needle in ("路線 (a)", "路線 (b)", "建議", "範圍外", "M5", "驗收", "風險", "same_sense", "170", "598",
                   "−1.7552526894158411", "−5.584894920868585"):
        assert needle in text, needle
    row = next(line for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
               if line.startswith("| M8 "))
    assert "原型完成（Part-21 解析器、四種基元、`castplane import`）；網格退路經 M5 內嵌網格型別" in row


# =========================================================================== final review fixes (group "step")
def _swap_refs(text: str, a: str, b: str) -> str:
    """A consistent renumbering: entity ids ``a`` and ``b`` exchanged everywhere."""
    return re.sub(r"#\d+\b", lambda m: {a: b, b: a}.get(m.group(), m.group()), text)


def _bbox_min(obj: dict) -> list:
    return np.asarray(obj["data"]["vertices"]).min(axis=0).round(6).tolist()


def test_mesh_fallback_tessellates_the_solid_of_its_entity_not_the_assembly_position(tmp_path, monkeypatch):
    """m8-step#0: OCC orders the solids of a compound by the assembly structure, not by entity id;
    the fallback must mesh the unrecognised solid itself whatever the numbering."""
    pytest.importorskip("OCP")

    def no_sphere(faces, ud, tol):
        raise S._Reject("forced")

    monkeypatch.setattr(S, "_recognise_sphere", no_sphere)       # the sphere becomes "unrecognised"
    sphere_min, cylinder = [0.5, 1.5, 0.0], {k: v for k, v in PILLAR.items() if k != "id"}
    plain = import_step(FIX / "two_solids.step", fallback="mesh", obj_id="part")
    assert [(s["entity"], s["kind"]) for s in plain["solids"]] == [("#37", "cylinder"), ("#154", "mesh")]
    assert _bbox_min(plain["objects"][1]) == pytest.approx(sphere_min, abs=1e-3)
    swapped = write(tmp_path, _swap_refs(fixture_text("two_solids"), "#37", "#154"), "swapped.step")
    rep = import_step(swapped, fallback="mesh", obj_id="part")
    assert [(s["entity"], s["kind"]) for s in rep["solids"]] == [("#37", "mesh"), ("#154", "cylinder")]
    assert _bbox_min(rep["objects"][0]) == pytest.approx(sphere_min, abs=1e-3)     # the sphere, not the cylinder
    assert rep["objects"][0]["data"] == plain["objects"][1]["data"]
    assert strip_id(rep["objects"][1]) == cylinder
    assert rep["notes"][-1] == make_step_warning("STEP_SOLID_TESSELLATED", ["#37"])
    # solid selection goes through the same entity -> OCC solid mapping
    (one,) = import_step(swapped, fallback="mesh", solid=0, obj_id="s")["objects"]
    assert one["data"] == plain["objects"][1]["data"]


def test_mesh_fallback_solid_guard_rejects_a_mismatching_ocp_solid():
    """The entity -> OCC solid mapping is checked against the file's vertex points."""
    pytest.importorskip("OCP")
    ocp_file = S._OcpFile(str(FIX / "two_solids.step"))
    entities = parse(fixture_text("two_solids"))["entities"]
    record = list(entities).index("#154") + 1
    good = S._solid_vertices(entities, "#154")
    assert ocp_file.solid("#154", record, len(entities), good, 1.0, 1e-3) is not None
    with pytest.raises(StepError, match=r"#37: .*does not match"):
        ocp_file.solid("#37", record, len(entities), S._solid_vertices(entities, "#37"), 1.0, 1e-3)
    with pytest.raises(StepError, match="numbers the records"):
        ocp_file.solid("#154", record, len(entities) + 1, good, 1.0, 1e-3)


def test_mesh_fallback_reads_the_file_once(monkeypatch):
    """m8-step#3: one OCP read per import, however many solids are tessellated (was one per solid)."""
    pytest.importorskip("OCP")
    reads = []
    real_init = S._OcpFile.__init__

    def counting_init(self, path):
        reads.append(path)
        real_init(self, path)

    def reject(faces, ud, tol):
        raise S._Reject("forced")

    monkeypatch.setattr(S._OcpFile, "__init__", counting_init)
    monkeypatch.setattr(S, "_recognise_sphere", reject)
    monkeypatch.setattr(S, "_recognise_cylinder", reject)
    rep = import_step(FIX / "two_solids.step", fallback="mesh", obj_id="part")
    assert [s["kind"] for s in rep["solids"]] == ["mesh", "mesh"] and len(reads) == 1
    # the per-solid meshes are those of the single-solid fixtures (same deflection rule per solid)
    assert rep["objects"][0]["data"]["faces"] == S.tessellate_step(FIX / "cylinder.step")["faces"]
    assert [len(o["data"]["faces"]) for o in rep["objects"]] == [164, 2836]


def _deep_file(depth: int, typed: bool = False) -> str:
    inner = "LENGTH_MEASURE(" * depth + "1." + ")" * depth if typed else "(" * depth + "1" + ")" * depth
    return p21(f"#1 = FOO({inner});")


def test_part21_nesting_is_capped_with_a_syntax_error():
    """m8-step#1: a hostile nesting depth is a Part21SyntaxError, not a RecursionError."""
    assert parse(_deep_file(64))["entities"]["#1"][0] == "FOO"
    assert parse(_deep_file(64, typed=True))["entities"]["#1"][0] == "FOO"
    for text in (_deep_file(65), _deep_file(2000), _deep_file(2000, typed=True)):
        with pytest.raises(Part21SyntaxError, match="nesting too deep"):
            parse(text)


def test_deeply_nested_step_file_is_a_step_error_exit_2(tmp_path, capsys):
    path = write(tmp_path, _deep_file(2000), "deep.step")
    with pytest.raises(StepError, match=r"^step: syntax: nesting too deep .* at offset \d+$"):
        import_step(path)
    assert cli.main(["import", str(path), "-o", str(tmp_path / "o.json")]) == 2
    assert "error: step: syntax: nesting too deep" in capsys.readouterr().err


def test_part21_numbers_beyond_int_and_float_limits():
    """m8-step#2: integers are ``int`` only while exactly representable as doubles; beyond, the
    correctly rounded ``float`` (``inf`` past 1e308), never ``int()``'s 4300-digit ValueError."""
    def value(tok):
        return parse(p21(f"#1 = FOO({tok});"))["entities"]["#1"][1][0]

    assert value(str(2 ** 53 - 1)) == 2 ** 53 - 1 and type(value(str(2 ** 53 - 1))) is int
    assert value("-7") == -7 and type(value("-7")) is int
    assert value(str(2 ** 53)) == float(2 ** 53) and type(value(str(2 ** 53))) is float
    assert value("1" + "0" * 400) == math.inf and value("-" + "9" * 5000) == -math.inf
    assert value("1E999") == math.inf
    with pytest.raises(Part21SyntaxError, match="entity id too long"):
        parse(p21("#1 = FOO(#" + "9" * 19 + ");"))
    with pytest.raises(Part21SyntaxError, match="entity id too long"):
        parse(p21("#" + "1" * 5000 + " = FOO(1);"))
    assert "#" + "9" * 18 in parse(p21("#" + "9" * 18 + " = FOO(1);"))["entities"]


def test_huge_integer_in_an_unrelated_record_is_harmless(tmp_path):
    text = add_entities(fixture_text("cylinder"), "#1000000 = FOO(" + "9" * 5000 + ");")
    assert strip_id(import_step(write(tmp_path, text))["objects"][0]) == strip_id(PILLAR)


@pytest.mark.parametrize("old, new, match", [
    ("#15 = MANIFOLD_SOLID_BREP('',#16);", "#15 = MANIFOLD_SOLID_BREP('',#16);\n#2 = FOO(#" + "9" * 5000 + ");",
     r"^step: syntax: entity id too long"),
    ("#66 = CARTESIAN_POINT('',(6.28318530718,-0.));", "#66 = CARTESIAN_POINT('',(1" + "0" * 400 + ",-0.));",
     r"^step: #66: non-finite coordinate"),
], ids=["5000-digit-entity-id", "401-digit-integer-coordinate"])
def test_huge_numbers_in_a_step_file_are_step_errors(tmp_path, old, new, match):
    """m8-step#2: ValueError / OverflowError tracebacks (exit 1) became StepErrors (exit 2)."""
    path = write(tmp_path, edit(fixture_text("cylinder"), old, new))
    with pytest.raises(StepError, match=match):
        import_step(path)
    assert cli.main(["import", str(path), "-q", "-o", str(tmp_path / "o.json")]) == 2


def test_non_finite_coordinate_anywhere_is_named(tmp_path):
    """m8-step#5: a 1E999 pcurve point made tol = inf and the cylinder was blamed ('zero height')."""
    text = edit(fixture_text("cylinder"), "#66 = CARTESIAN_POINT('',(6.28318530718,-0.));",
                "#66 = CARTESIAN_POINT('',(1E999,-0.));")
    with pytest.raises(StepError, match=r"^step: #66: non-finite coordinate inf$") as exc:
        import_step(write(tmp_path, text))
    assert exc.value.entity == "#66"


@pytest.mark.parametrize("fixture, old, new, entity", [
    ("cylinder", "#31 = CYLINDRICAL_SURFACE('',#32,300.);", "#31 = CYLINDRICAL_SURFACE('',#32,-300.);", "#31"),
    ("cylinder", "#31 = CYLINDRICAL_SURFACE('',#32,300.);", "#31 = CYLINDRICAL_SURFACE('',#32,0.);", "#31"),
    ("sphere", "#22 = SPHERICAL_SURFACE('',#23,500.);", "#22 = SPHERICAL_SURFACE('',#23,-500.);", "#22"),
    ("cylinder", "#80 = CIRCLE('',#81,300.);", "#80 = CIRCLE('',#81,-300.);", "#80"),
], ids=["cylinder-negative", "cylinder-zero", "sphere-negative", "circle-negative"])
def test_non_positive_radius_is_a_step_error_at_the_entity(tmp_path, fixture, old, new, entity):
    """m8-step#4: a radius <= 0 was emitted into the scene and rejected later at a field the user's
    ``step`` object does not have (``objects[i].radius``)."""
    path = write(tmp_path, edit(fixture_text(fixture), old, new))
    with pytest.raises(StepError, match=rf"^objects\[0\]\.path: {entity}: \w+ radius must be > 0") as exc:
        expand(path)
    assert exc.value.entity == entity and exc.value.field == "objects[0].path"


def test_conical_surface_radius_may_be_zero_but_not_negative(tmp_path):
    """ISO 10303-42 allows ``radius = 0`` for a conical surface placed at its apex."""
    b = Builder()
    b.units()
    r, h, semi = 400.0, 1200.0, math.atan(1.0 / 3.0)
    vb, va = b.vertex((r, 0.0, 0.0)), b.vertex((0.0, 0.0, h))
    eb = b.edge(vb, vb, b.add(f"CIRCLE('',{b.axis((0.0, 0.0, 0.0))},{f(r)})"))
    line = b.add(f"LINE('',{b.point((r, 0.0, 0.0))},"
                 f"{b.add(f'VECTOR({chr(39)}{chr(39)},{b.direction((-r, 0, h))},1.)')})")
    seam = b.edge(vb, va, line)
    side = b.face([eb, seam], b.add(f"CONICAL_SURFACE('',{b.axis((0.0, 0.0, h), (0, 0, -1))},0.,{semi!r})"))
    base = b.face([eb], b.add(f"PLANE('',{b.axis((0.0, 0.0, 0.0), (0, 0, -1))})"))
    b.solid([side, base])
    (obj,) = import_step(write(tmp_path, b.text()), obj_id="c")["objects"]
    assert strip_id(obj) == CONE | {"transform": {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]}}
    negative = b.text().replace(",0.,", ",-1.,")
    with pytest.raises(StepError, match=r"CONICAL_SURFACE radius must be ≥ 0"):
        import_step(write(tmp_path, negative, "neg.step"))
