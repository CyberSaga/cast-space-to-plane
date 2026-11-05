"""The Reiya drawing-reference model (``tools/make_reiya_model.py``, ``tools/reiya_model/`` on ``tools/charmodel/``).

The generator is a dev tool outside the package; these tests import it from ``tools/`` and pin what the
shipped files promise: the generator reproduces ``examples/reiya.json`` and ``examples/meshes/reiya.{obj,mtl,glb}``
byte for byte; every object is a closed, consistently oriented manifold that castplane takes without mesh
preprocessing warnings; stage A and the scene camera render have ``warnings == []`` with the default layers; the
polygon / triangle budget and the 64 feature silhouette vertices per object hold; ``display_color`` is the colour
of the object's dominant material and the core ignores it; and the GLB and OBJ import with ``castplane import``.
Reiya's own promises: the rig is at the design sheet's scale and the model is scaled by ``rig.figure_scale`` to her
stated height (1.52 m barefoot, the user's figure), so the soles stay on ``z = 0``, the skin head's top is the final
skull top in her loafers, and the scene camera is the sheet camera scaled by the same factor.  Object lists come
from ``reiya_model.assemble`` (no hard-coded counts).  The model is built once per module.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import pathlib
import re
import sys

import numpy as np
import pytest

import castplane
from castplane import pipeline
from castplane.cli import EXIT_OK, main
from castplane.meshprep import MESH_MAX_RAYS
from castplane.output.geometry_json import dumps

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from charmodel import meshkit as mk  # noqa: E402
from reiya_model import assemble as asm  # noqa: E402
from reiya_model import export  # noqa: E402
from reiya_model.rig import Rig  # noqa: E402

SCENE = ROOT / "examples" / "reiya.json"
MESHES = ROOT / "examples" / "meshes"
COLOUR = re.compile(r"#[0-9a-f]{6}")
#: Tolerance of the height checks: 0.1 mm.
HEIGHT_TOL = 1e-4
#: Two faces on one edge are folded back onto each other when their normals are this far apart (opposite within 2°).
FOLD_BACK_DEG = 178.0


@pytest.fixture(scope="module")
def model():
    """The model built from the default rig (strict: invalid parts raise)."""
    return asm.assemble(Rig())


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads(SCENE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def scene(raw) -> dict:
    return castplane.load_scene(copy.deepcopy(raw))


@pytest.fixture(scope="module")
def stage_a(scene) -> dict:
    return pipeline.shadow_geometry(scene)


@pytest.fixture(scope="module")
def rendered(scene) -> dict:
    return castplane.render(scene)


def _without_display_color(raw: dict) -> dict:
    plain = copy.deepcopy(raw)
    for o in plain["objects"]:
        o.pop("display_color", None)
    return plain


def _polygon_area(points: np.ndarray) -> float:
    """Area of a planar-ish polygon ``(n, 3)`` by Newell's vector sum."""
    n = np.cross(points, np.roll(points, -1, axis=0)).sum(axis=0)
    return 0.5 * float(np.sqrt(n @ n))


# ---------------------------------------------------------------------------- (a) reproducible files

def test_build_reproduces_the_scene_json_byte_for_byte(model):
    assert model.ok
    assert export.scene_text(model).encode("utf-8") == SCENE.read_bytes()


def test_build_reproduces_the_obj_mtl_and_glb_byte_for_byte(model):
    assert export.obj_text(model, "reiya.mtl").encode("utf-8") == (MESHES / "reiya.obj").read_bytes()
    assert export.mtl_text(model).encode("utf-8") == (MESHES / "reiya.mtl").read_bytes()
    assert export.glb_bytes(model) == (MESHES / "reiya.glb").read_bytes()


def test_scene_objects_are_the_generator_objects_in_order(raw, model):
    assert [o["id"] for o in raw["objects"]] == list(asm.OBJECT_IDS) == list(model.meshes)
    assert all(o["type"] == "mesh" and set(o["data"]) == {"vertices", "faces", "smooth_groups"} for o in raw["objects"])


# ---------------------------------------------------------------------------- (b) closed manifolds, no warnings

def test_every_object_is_a_closed_consistently_oriented_manifold(raw):
    for o in raw["objects"]:
        d = o["data"]
        n_v = len(d["vertices"])
        directed = [(f[i], f[(i + 1) % len(f)]) for f in d["faces"] for i in range(len(f))]
        assert all(0 <= a < n_v for a, _ in directed), o["id"]
        assert len(set(directed)) == len(directed), f"{o['id']}: a directed edge is used twice (bad orientation)"
        assert all((b, a) in set(directed) for a, b in directed), f"{o['id']}: an edge has no opposite (open)"
        used = {a for a, _ in directed}
        assert used == set(range(n_v)), f"{o['id']}: unreferenced vertices"
        rep = mk.validate(mk.Mesh(d["vertices"], d["faces"], d["smooth_groups"]), o["id"])
        assert rep.ok, rep.summary()


def test_no_face_pair_of_the_bob_folds_back_onto_itself(raw):
    """V4 pass (2026-11-01): no two triangles of a bob object that share an edge lie back to back.  Before it, flipped
    sliver triangles lay folded 180 degrees onto their neighbours at the front slit's V top (three edges per side: the
    lock zone's top row ran back on itself, a spur on the outline) and at the back slit's top (two per side: the
    joining strip's zip), ten edges in all; the V now closes on one vertex and the strip zips by the shorter diagonal.
    The triangles are castplane's (a fan from each face's first vertex); a pair counts as folded when its normals are
    opposite within 2 degrees: the bob's sharpest designed crease is 172.2 degrees, the slivers were 180.0."""
    limit = float(np.cos(np.radians(FOLD_BACK_DEG)))
    bobs = [o for o in raw["objects"] if o["id"] in ("bob_l", "bob", "bob_r")]
    assert bobs
    for o in bobs:
        v = np.asarray(o["data"]["vertices"], dtype=np.float64)
        tris = np.array([(f[0], f[i], f[i + 1]) for f in o["data"]["faces"] for i in range(1, len(f) - 1)])
        n = np.cross(v[tris[:, 1]] - v[tris[:, 0]], v[tris[:, 2]] - v[tris[:, 0]])
        n /= np.linalg.norm(n, axis=1)[:, None]
        owners: dict = {}
        for k, (a, b, c) in enumerate(tris.tolist()):
            for edge in ((a, b), (b, c), (c, a)):
                owners.setdefault(frozenset(edge), []).append(k)
        assert all(len(ks) == 2 for ks in owners.values()), o["id"]
        folded = sorted(sorted(e) for e, (k, m) in owners.items() if float(n[k] @ n[m]) < limit)
        assert folded == [], f"{o['id']}: face pairs folded back onto each other at the edges {folded}"


def test_castplane_takes_every_object_without_mesh_preprocessing(stage_a):
    assert [o["id"] for o in stage_a["objects"]] == list(asm.OBJECT_IDS)
    for o in stage_a["objects"]:
        assert o["type"] == "mesh"
        assert o["fallback"] is False, o["id"]
        assert o["prep_warnings"] == [], (o["id"], o["prep_warnings"])


def test_stage_a_has_no_warnings(stage_a):
    assert stage_a["warnings"] == []


# ---------------------------------------------------------------------------- (c) scene camera render

def test_scene_camera_render_has_no_warnings(rendered):
    assert rendered["geometry"]["warnings"] == []


def test_default_layers_are_objects_and_cast_shadow(raw, scene, rendered):
    assert raw["output"]["layers"] == ["objects", "cast_shadow"]
    assert scene["output"]["layers"] == ["objects", "cast_shadow"]
    assert re.findall(r'<g id="([a-z_]+)"', rendered["svg"]) == ["objects", "cast_shadow"]


# ---------------------------------------------------------------------------- (d) budget and rays

def test_polygon_and_triangle_budget(raw, model):
    polygons = sum(len(o["data"]["faces"]) for o in raw["objects"])
    triangles = sum(len(f) - 2 for o in raw["objects"] for f in o["data"]["faces"])
    assert (polygons, triangles) == (model.stats["total"]["polygons"], model.stats["total"]["triangles"])
    assert polygons <= asm.BUDGET["polygons"]
    assert triangles <= asm.BUDGET["triangles"]
    assert model.stats["within_budget"]


def test_at_most_64_feature_silhouette_vertices_per_object(model, stage_a):
    # the generator's count (feature silhouette vertices towards the sun) and castplane's ray selection
    assert model.stats["rays_ok"] and model.stats["rays_over"] == []
    assert all(o["ray_vertices"] <= MESH_MAX_RAYS for o in model.stats["objects"])
    rays = {rec["object"]: int(np.count_nonzero(rec["ray_vertices"])) for rec in stage_a["shadows"]}
    assert set(rays) == set(asm.OBJECT_IDS)
    assert max(rays.values()) <= MESH_MAX_RAYS


def test_stats_table_columns_line_up_with_long_object_ids(model):
    # review r2-T8: ids such as face_marks_l are longer than 10 characters; the object column widens to the longest
    w = max(10, *(len(i) for i in asm.OBJECT_IDS))
    assert w > 10
    lines = asm.format_stats(model.stats).splitlines()
    head = lines.index(next(line for line in lines if line.startswith(" # object")))
    table = lines[head:head + len(asm.OBJECT_IDS) + 2]          # header, the object rows, TOTAL
    assert [line[3:3 + w].rstrip() for line in table] == ["object", *asm.OBJECT_IDS, "TOTAL"]
    assert all(line[3 + w] == " " for line in table)
    parts = [line for line in lines[:head] if line.strip()]
    assert all(line[31:31 + w].rstrip() in ("object", *asm.OBJECT_IDS) and line[31 + w] == " " for line in parts)


# ---------------------------------------------------------------------------- (e) display_color

def test_every_object_has_its_display_color(raw):
    assert set(asm.DISPLAY_MATERIALS) == set(asm.OBJECT_IDS)
    for o in raw["objects"]:
        colour = o["display_color"]
        assert COLOUR.fullmatch(colour), (o["id"], colour)
        assert colour == asm.display_color(o["id"]) == asm.MATERIALS[asm.DISPLAY_MATERIALS[o["id"]]]
        assert list(o) == ["id", "type", "display_color", "data"]      # deterministic key order


def test_display_material_is_the_dominant_material_by_area(model):
    for oid, mesh in model.meshes.items():
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        area = {mat: sum(_polygon_area(vertices[list(mesh.faces[k])]) for k in faces)
                for mat, faces in model.materials(oid)}
        assert max(area, key=area.get) == asm.DISPLAY_MATERIALS[oid], (oid, area)


def test_display_color_is_ignored_by_the_core(raw, scene, rendered):
    plain = castplane.load_scene(_without_display_color(raw))
    assert all("display_color" not in o for o in scene["objects"])
    out = castplane.render(plain)
    assert out["svg"] == rendered["svg"]
    assert dumps(out["geometry"]) == dumps(rendered["geometry"])


# ---------------------------------------------------------------------------- (f) OBJ / GLB import

def test_glb_imports_into_the_same_objects(tmp_path, raw):
    out = tmp_path / "reiya_glb.json"
    assert main(["import", str(MESHES / "reiya.glb"), "--inline", "-o", str(out), "--quiet"]) == EXIT_OK
    imported = json.loads(out.read_text(encoding="utf-8"))
    assert [o["id"] for o in imported["objects"]] == list(asm.OBJECT_IDS)
    scene = castplane.load_scene(imported)
    # the GLB carries no smooth groups, so castplane counts more feature vertices on 14 objects than the cap allows;
    # nothing else: no non-manifold shell, no reoriented face
    warnings = pipeline.shadow_geometry(scene)["warnings"]
    assert [w["code"] for w in warnings] == ["MESH_RAYS_CAPPED"] * 14
    assert {i for w in warnings for i in w["ids"]} <= set(asm.OBJECT_IDS) and len({w["ids"][0] for w in warnings}) == 14
    for got, want in zip(imported["objects"], raw["objects"]):
        g, w = got["data"], want["data"]
        # triangles: castplane's fan triangulation of the scene's faces; positions: the scene's (float32)
        assert len(g["faces"]) == sum(len(f) - 2 for f in w["faces"]), got["id"]
        assert {tuple(round(x, 5) + 0.0 for x in v) for v in g["vertices"]} \
            == {tuple(float(x) + 0.0 for x in v) for v in w["vertices"]}, got["id"]


def test_obj_imports_and_validates(tmp_path, raw):
    out = tmp_path / "reiya_obj.json"
    assert main(["import", str(MESHES / "reiya.obj"), "--inline", "-o", str(out), "--quiet"]) == EXIT_OK
    imported = json.loads(out.read_text(encoding="utf-8"))
    assert [o["id"] for o in imported["objects"]] == ["reiya"]
    validated = castplane.load_scene(imported)
    assert len(validated["objects"]) == 1
    # the shells share no vertex (the bob's three shells stay 0.15 mm apart), so the OBJ stays a closed manifold:
    # with coinciding caps castplane reported MESH_NON_MANIFOLD here
    codes = {w["code"] for w in pipeline.shadow_geometry(validated)["warnings"]}
    assert codes == {"MESH_RAYS_CAPPED", "MESH_WINDING_FIXED"}
    data = imported["objects"][0]["data"]
    assert len(data["faces"]) == sum(len(o["data"]["faces"]) for o in raw["objects"])
    assert len(data["vertices"]) == sum(len(o["data"]["vertices"]) for o in raw["objects"])


# ---------------------------------------------------------------------------- (g) Reiya: ground, height, camera

def test_soles_stand_on_the_ground(raw):
    assert min(v[2] for o in raw["objects"] for v in o["data"]["vertices"]) == 0.0


def test_stated_height_sets_the_figure_scale(model):
    rig = Rig()
    assert rig.stated_height == 1.52                         # the user: "Her height is 152cm" (barefoot)
    assert rig.figure_scale == rig.stated_height / rig.skin_height
    assert rig.figure_scale < 1.0                            # the sheet-scale rig is scaled down
    assert asm.figure_scale(rig) == asm.CHARACTER.scale_for(rig) == rig.figure_scale
    assert model.rig.figure_scale == rig.figure_scale
    assert rig.final_skin_height == pytest.approx(rig.stated_height, abs=1e-12)
    assert rig.final_height - rig.final_heel_lift == pytest.approx(rig.stated_height, abs=1e-12)


def test_the_head_top_is_the_final_skull_top(raw):
    head = next(o for o in raw["objects"] if o["id"] == "head")
    top = max(v[2] for v in head["data"]["vertices"])
    assert abs(top - Rig().final_height) <= HEIGHT_TOL, (top, Rig().final_height)


def test_scene_camera_is_the_sheet_camera_scaled(raw):
    rig = Rig()
    f = rig.figure_scale
    assert raw["camera"] == export.scene_settings(rig)["camera"] == export.SCENE_SETTINGS["camera"]
    sheet = export.SHEET_CAMERA
    for key in ("position", "target"):
        assert raw["camera"][key] == [round(float(v) * f, export.CAMERA_DECIMALS) + 0.0 for v in sheet[key]], key
        assert raw["camera"][key] != [float(v) for v in sheet[key]], key
    assert {k: v for k, v in raw["camera"].items() if k not in ("position", "target")} \
        == {k: v for k, v in sheet.items() if k not in ("position", "target")}


def test_a_rig_override_of_the_stated_height_rescales(model):
    # the scale comes from the rig in use (``--rig '{"stated_height": ...}'``): at the sheet's own height it is 1
    rig = Rig()
    sheet_rig = rig.replace(stated_height=rig.skin_height)
    assert asm.CHARACTER.scale_for(sheet_rig) == 1.0
    camera = export.scene_settings(sheet_rig)["camera"]
    for key in ("position", "target"):
        assert camera[key] == [round(float(v), export.CAMERA_DECIMALS) + 0.0 for v in export.SHEET_CAMERA[key]]
    # the scene description quotes the heights of the assembly's rig (final review FR-1): 1.56 m barefoot (the
    # sheet's 1.555) and 1.59 m in her loafers, not the default rig's 1.52 / 1.55; the writers take it from
    # ``assembly.rig`` (the default-rig geometry stands in, only the rig is read)
    sheet_model = dataclasses.replace(model, rig=sheet_rig)
    for scene in (export.scene_dict(sheet_model), json.loads(export.scene_text(sheet_model))):
        assert scene["description"] == export.scene_description(sheet_rig) != export.DESCRIPTION
        assert scene["description"].startswith(
            "Reiya (レイヤ) as a drawing reference: an anime girl 1.56 m tall (barefoot, sole to skull top; "
            "1.59 m in her loafers, 7.4 heads to the hair crown)")
        assert scene["camera"] == camera
    assert export.scene_dict(model)["description"] == export.scene_description() == export.DESCRIPTION
    assert export.DESCRIPTION.startswith(
        "Reiya (レイヤ) as a drawing reference: an anime girl 1.52 m tall (barefoot, sole to skull top; "
        "1.55 m in her loafers, 7.4 heads to the hair crown)")


# ---------------------------------------------------------------------------- (h) the numbers the docs quote

#: Which of the numbers below each document quotes (final review FR-2: nothing else fails when a regeneration changes
#: a count, and the docs went stale twice while the model was built).  The quotes are plain (``5540``) or use a space
#: as the thousands separator (``5 540``, ``239 993``).
DOC_QUOTES = {
    "CHANGELOG.md": ("polygons", "triangles"),
    "docs/ARCHITECTURE.md": ("parts", "shells", "vertices", "polygons", "triangles", "svg_characters"),
    "docs/USAGE.md": ("parts", "shells", "vertices", "polygons", "triangles", "max_rays", "json_bytes", "obj_bytes",
                      "mtl_bytes", "glb_bytes", "json_kib"),
    "examples/README.md": ("parts", "vertices", "polygons", "triangles", "max_rays"),
    "web/README.md": ("polygons", "triangles", "svg_characters"),
    "tools/reiya_model/README.md": ("parts", "shells", "vertices", "polygons", "triangles", "triangles_left",
                                    "json_kib"),
    "tools/reiya_model/SPEC.md": ("polygons", "triangles"),
    ".claude/skills/character-model/SKILL.md": ("parts",),
}


def _forms(value) -> list:
    """The spellings of a number in the docs: plain and with a space for the thousands; a string is as is."""
    if isinstance(value, str):
        return [value]
    return sorted({str(value), f"{value:,}".replace(",", " ")})


def _quotes(text: str, value) -> bool:
    """Whether ``text`` quotes ``value`` as a whole number (not as the tail or the head of a longer one)."""
    return any(re.search(rf"(?<![\d.])(?<!\d ){re.escape(form)}(?!\d)", text) for form in _forms(value))


def test_quote_matcher_takes_whole_numbers_only():
    assert _quotes("5540 與 9816", 5540) and _quotes("**5 540** (9 816 triangles)", 9816)
    assert _quotes("`reiya.json` 239 993 B（234.4 KiB）", 239993) and _quotes("（234.4 KiB）", "234.4")
    assert not _quotes("55400 polygons", 5540) and not _quotes("15540 polygons", 5540)
    assert not _quotes("25 539 B", 5539) and not _quotes("1234.4", "234.4")


def test_docs_quote_the_counts_of_the_built_model(model, rendered):
    """FR-2: the counts, the file sizes and the SVG length that the docs quote are the built ones, so a regeneration
    that changes one fails here until the documents are updated."""
    total = model.stats["total"]
    sizes = {"json": SCENE, "obj": MESHES / "reiya.obj", "mtl": MESHES / "reiya.mtl", "glb": MESHES / "reiya.glb"}
    numbers = {
        "parts": len(model.stats["parts"]), "shells": total["shells"], "vertices": total["vertices"],
        "polygons": total["polygons"], "triangles": total["triangles"],
        "triangles_left": asm.BUDGET["triangles"] - total["triangles"],
        "max_rays": max(o["ray_vertices"] for o in model.stats["objects"]),
        "svg_characters": len(rendered["svg"]),
        "json_kib": f"{SCENE.stat().st_size / 1024:.1f}",
        **{f"{k}_bytes": p.stat().st_size for k, p in sizes.items()},
    }
    assert set().union(*DOC_QUOTES.values()) == set(numbers)
    stale = []
    for doc, names in DOC_QUOTES.items():
        text = (ROOT / doc).read_text(encoding="utf-8")
        stale += [f"{doc}: {name} = {numbers[name]}" for name in names if not _quotes(text, numbers[name])]
    assert not stale, "update the docs to the built model:\n" + "\n".join(stale)


def test_docs_quote_the_number_of_tests_of_this_file():
    """FR-2: the number of tests of this file that the docs quote (every test is a plain module-level function)."""
    n = len(re.findall(r"^def test_", pathlib.Path(__file__).read_text(encoding="utf-8"), re.M))
    english = r"`tests/test_reiya_model\.py` \((\d+) tests"
    quoted = {
        "README.md": r"`examples/reiya\.json`） \| (\d+) 個測試",
        "CHANGELOG.md": english,
        "docs/ARCHITECTURE.md": english,
        "tools/reiya_model/README.md": english,
    }
    for doc, pattern in quoted.items():
        found = re.findall(pattern, (ROOT / doc).read_text(encoding="utf-8"))
        assert found == [str(n)], (doc, found, n)
