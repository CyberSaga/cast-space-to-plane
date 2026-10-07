"""STEP import (contract §5.5; spec §9 row "STEP", §10 M8).  Part 21 parser, units, topology walk,
recognisers, importer API.  Fixtures: ``tests/fixtures/step/`` (written by
``tools/make_step_fixtures.py`` with OCP; committed)."""

from __future__ import annotations

import math
import pathlib

import pytest

from castplane.io import part21
from castplane.io.part21 import Part21SyntaxError, parse, tokenize

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
