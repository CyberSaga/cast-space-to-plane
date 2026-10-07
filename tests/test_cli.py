"""``castplane`` CLI (contract §1): render / validate / info / stages, ``--camera``, ``--layers``,
``--formats``, ``--quiet``, the warning table and the documented exit codes."""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from castplane import cli
from castplane.cli import EXIT_INPUT, EXIT_IO, EXIT_MISSING_DEPENDENCY, EXIT_OK, main

EXAMPLES = pathlib.Path(__file__).resolve().parents[1] / "examples"
BASIC = str(EXAMPLES / "basic.json")


def write_json(path: pathlib.Path, data) -> str:
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def basic_scene() -> dict:
    return json.loads((EXAMPLES / "basic.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- render
def test_render_default_formats_are_svg_and_json(tmp_path, capsys):
    assert main(["render", BASIC, "-o", str(tmp_path)]) == EXIT_OK
    out = capsys.readouterr().out.splitlines()
    assert out == [str(tmp_path / "basic.svg"), str(tmp_path / "basic.json")]
    assert not (tmp_path / "basic.png").exists()
    doc = json.loads((tmp_path / "basic.json").read_text(encoding="utf-8"))
    assert doc["canvas_mm"] == [273.0, 182.0] and "crate.v0" in doc["points"]
    svg = (tmp_path / "basic.svg").read_text(encoding="utf-8")
    assert re.findall(r'<g id="([a-z_]+)"', svg) == list(cli.LAYER_ORDER)


def test_render_layers_subset_and_single_format(tmp_path):
    assert main(["render", BASIC, "-o", str(tmp_path), "--formats", "svg", "--layers", "labels,objects,horizon"]) == EXIT_OK
    assert (tmp_path / "basic.svg").exists() and not (tmp_path / "basic.json").exists()
    svg = (tmp_path / "basic.svg").read_text(encoding="utf-8")
    assert re.findall(r'<g id="([a-z_]+)"', svg) == ["horizon", "objects", "labels"]   # contract §2.10 order


def test_render_png_only_when_requested(tmp_path):
    pytest.importorskip("cairosvg")
    assert main(["render", BASIC, "-o", str(tmp_path), "--formats", "png", "--dpi", "30"]) == EXIT_OK
    png = tmp_path / "basic.png"
    assert png.exists() and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert not (tmp_path / "basic.svg").exists() and not (tmp_path / "basic.json").exists()


def test_render_reports_a_missing_png_backend(tmp_path, capsys, monkeypatch):
    def no_backend(svg, dpi=300):
        raise ImportError("PNG output needs cairosvg (pip install 'castplane[png]') or the resvg CLI on PATH")
    monkeypatch.setattr(cli, "write_png", no_backend)
    assert main(["render", BASIC, "-o", str(tmp_path), "--formats", "svg,png"]) == EXIT_MISSING_DEPENDENCY
    err = capsys.readouterr().err
    assert "PNG output is unavailable" in err and "castplane[png]" in err
    assert not (tmp_path / "basic.png").exists() and not (tmp_path / "basic.svg").exists()  # nothing half-written


def test_render_quiet_prints_nothing_on_success(tmp_path, capsys):
    scene = basic_scene()
    scene["lights"][0]["position"] = [0.5, -4.0, 3.0]        # behind the camera: a warning
    path = write_json(tmp_path / "behind.json", scene)
    assert main(["render", path, "-o", str(tmp_path / "out")]) == EXIT_OK
    captured = capsys.readouterr()
    assert "warning: LIGHT_BEHIND_CAMERA ['lamp']" in captured.err and captured.out
    assert main(["render", path, "-o", str(tmp_path / "out"), "--quiet"]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_render_camera_override_accepts_a_camera_only_json(tmp_path):
    cam = write_json(tmp_path / "cam.json", {"position": [0, 0, 3], "target": [0, 5, 0], "focal_length_mm": 50,
                                             "frame_mm": [36, 24]})
    assert main(["render", BASIC, "-o", str(tmp_path / "a"), "--camera", cam]) == EXIT_OK
    assert main(["render", BASIC, "-o", str(tmp_path / "b")]) == EXIT_OK
    with_cam = json.loads((tmp_path / "a" / "basic.json").read_text(encoding="utf-8"))
    plain = json.loads((tmp_path / "b" / "basic.json").read_text(encoding="utf-8"))
    assert with_cam["points"]["crate.v0"]["world"] == plain["points"]["crate.v0"]["world"]   # stage A unchanged
    assert with_cam["points"]["crate.v0"]["image"] != plain["points"]["crate.v0"]["image"]
    assert with_cam["camera"]["C"] == [0.0, 0.0, 3.0]
    # a whole scene file works as a camera source too (its camera block is used)
    scene = basic_scene()
    scene["camera"]["position"] = [0, 0, 3]
    scene["camera"]["target"] = [0, 5, 0]
    scene["camera"]["focal_length_mm"] = 50
    other = write_json(tmp_path / "other_scene.json", scene)
    assert main(["render", BASIC, "-o", str(tmp_path / "c"), "--camera", other]) == EXIT_OK
    from_scene = json.loads((tmp_path / "c" / "basic.json").read_text(encoding="utf-8"))
    assert from_scene["camera"]["P"] == with_cam["camera"]["P"]


def test_render_camera_override_aspect_mismatch_is_an_input_error(tmp_path, capsys):
    cam = write_json(tmp_path / "cam.json", {"position": [0, 0, 3], "target": [0, 5, 0], "focal_length_mm": 50,
                                             "frame_mm": [36, 36]})
    assert main(["render", BASIC, "-o", str(tmp_path), "--camera", cam]) == EXIT_INPUT
    assert "error: camera.frame_mm:" in capsys.readouterr().err


def test_unknown_format_or_layer_is_an_input_error(tmp_path, capsys):
    assert main(["render", BASIC, "-o", str(tmp_path), "--formats", "svg,pdf"]) == EXIT_INPUT
    assert "error: --formats: unknown format 'pdf'" in capsys.readouterr().err
    assert main(["render", BASIC, "-o", str(tmp_path), "--layers", "shadows"]) == EXIT_INPUT
    assert "error: --layers: unknown layer 'shadows'" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


# --------------------------------------------------------------------------- validate / exit codes
def test_validate_ok_and_scene_error_exit_code_with_field_path(tmp_path, capsys):
    assert main(["validate", BASIC]) == EXIT_OK
    assert capsys.readouterr().out.strip() == "ok: 2 object(s), 1 light(s), 1 receiver(s)"
    assert main(["validate", BASIC, "--quiet"]) == EXIT_OK
    assert capsys.readouterr().out == ""
    scene = basic_scene()
    scene["objects"][1]["radius"] = -1
    bad = write_json(tmp_path / "bad.json", scene)
    assert main(["validate", bad]) == EXIT_INPUT
    assert capsys.readouterr().err.strip() == "error: objects[1].radius: must be > 0"
    scene = basic_scene()
    scene["output"]["canvas_mm"] = [257, 182]                 # the spec §4 example's own aspect mismatch
    bad = write_json(tmp_path / "aspect.json", scene)
    assert main(["render", bad, "-o", str(tmp_path)]) == EXIT_INPUT
    assert "error: output.canvas_mm:" in capsys.readouterr().err
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert main(["validate", str(tmp_path / "broken.json")]) == EXIT_INPUT
    assert "invalid JSON" in capsys.readouterr().err


def test_missing_scene_file_is_an_io_error(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "nope.json")]) == EXIT_IO
    assert capsys.readouterr().err.startswith("error:")


def test_usage_error_exits_2():
    with pytest.raises(SystemExit) as info:
        main(["render", BASIC])          # -o is required
    assert info.value.code == 2


# --------------------------------------------------------------------------- info
def test_info_prints_horizon_vanishing_points_and_the_warning_table(tmp_path, capsys):
    assert main(["info", BASIC]) == EXIT_OK
    out = capsys.readouterr().out
    assert "objects: 2 (crate:box, pillar:cylinder)" in out
    assert "horizon v_mm:" in out and "vanishing point z: none" not in out
    # the camera looks along +Y: the x axis is parallel to the picture plane (contract §2.2 gives null)
    assert "vanishing point x: at infinity (axis parallel to the picture plane)" in out
    assert "vanishing point y: (0.0000, 26.5417)" in out and "none" not in out.split("warnings")[0]
    assert "light point L':" in out and "shadow vanishing point F':" in out
    assert "construction self-check max error:" in out
    assert out.rstrip().endswith("warnings: none")
    scene = basic_scene()
    scene["lights"][0]["position"] = [0.5, -4.0, 3.0]        # light behind the camera
    scene["objects"][0]["transform"]["position"][2] = -0.3     # crate partly buried
    path = write_json(tmp_path / "degenerate.json", scene)
    assert main(["info", path]) == EXIT_OK
    out = capsys.readouterr().out
    assert "warnings: 2" in out
    table = out[out.index("warnings: 2"):].splitlines()
    assert table[1].split() == ["code", "ids", "message"]
    rows = {line.split()[0]: line for line in table[3:]}
    assert set(rows) == {"LIGHT_BEHIND_CAMERA", "OBJECT_BELOW_RECEIVER"}
    assert "lamp" in rows["LIGHT_BEHIND_CAMERA"] and "crate" in rows["OBJECT_BELOW_RECEIVER"]
    assert "anti-light point" in rows["LIGHT_BEHIND_CAMERA"]


def test_info_reports_points_at_infinity(tmp_path, capsys):
    scene = basic_scene()
    scene["lights"] = [{"id": "sun", "type": "directional", "direction": [0.6, 0.0, 0.8]}]  # in the picture plane
    scene["camera"]["target"] = [0.0, 5.0, 1.5]
    path = write_json(tmp_path / "parallel.json", scene)
    assert main(["info", path]) == EXIT_OK
    out = capsys.readouterr().out
    assert "light point L': at infinity, direction" in out
    assert "LIGHT_POINT_AT_INFINITY" in out
    # with the pitched camera of examples/basic.json (a scene file as camera source) only F' is at infinity
    assert main(["info", path, "--camera", BASIC]) == EXIT_OK
    out = capsys.readouterr().out
    assert "light point L': (" in out and "shadow vanishing point F': at infinity, direction" in out
    assert "SHADOW_VP_AT_INFINITY" in out and "LIGHT_POINT_AT_INFINITY" not in out


# --------------------------------------------------------------------------- stages
def test_stages_to_file_and_stdout(tmp_path, capsys):
    cam = write_json(tmp_path / "cam.json", {"position": [0, 0, 3], "target": [0, 5, 0], "focal_length_mm": 50,
                                             "frame_mm": [36, 24]})
    out = tmp_path / "stages.json"
    assert main(["stages", BASIC, "--camera", cam, "-o", str(out)]) == EXIT_OK
    assert capsys.readouterr().out.strip() == str(out)
    st = json.loads(out.read_text(encoding="utf-8"))
    assert set(st) == {"A", "B"}
    assert [o["id"] for o in st["A"]["objects"]] == ["crate", "pillar"]
    assert st["B"]["camera"]["C"] == [0.0, 0.0, 3.0] and len(st["B"]["camera"]["P"]) == 3
    assert main(["stages", BASIC, "--quiet", "-o", str(out)]) == EXIT_OK
    assert capsys.readouterr().out == ""
    assert main(["stages", BASIC]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["B"]["scene_scale"] >= 1.0


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0
    assert capsys.readouterr().out.startswith("castplane ")


# --------------------------------------------------------------------------- documentation consistency
ROOT = EXAMPLES.parent
USER_DOCS = [ROOT / "README.md", ROOT / "docs" / "USAGE.md", ROOT / "examples" / "README.md",
             ROOT / "tests" / "conformance" / "README.md"]


def documented_commands() -> list:
    """Every ``castplane <subcommand> ...`` invocation quoted in the user-facing docs (inline code
    or a fenced shell block), with the ``<name>`` placeholders filled in and comments stripped."""
    found = []
    for path in USER_DOCS:
        for line in path.read_text(encoding="utf-8").splitlines():
            for m in re.finditer(r"castplane (render|validate|info|stages|import)\b[^`#|]*", line):
                cmd = m.group(0).strip().replace("<名稱>", "basic")
                if len(cmd.split()) < 3 or cmd.split()[2].isupper():   # a mention (``castplane import``) or a
                    continue                                            # synopsis row (``… render SCENE -o OUTDIR``)
                found.append((path.name, cmd))
    return found


def test_examples_readme_describes_the_directional_example_correctly():
    """examples/README.md must describe what examples/directional.json renders: the sun direction has a
    negative y component (behind the +Y-looking camera), so L' is the anti-light point BELOW the horizon
    and no LIGHT_BEHIND_CAMERA is emitted for a direction (contract §2.7 [decision])."""
    import castplane
    doc = castplane.render(castplane.load_scene(str(EXAMPLES / "directional.json")))["geometry"]
    con = doc["construction"]
    assert con["light_point"] is not None and con["light_point"][1] < doc["horizon"]["v_mm"]
    assert doc["warnings"] == []
    row = [ln for ln in (EXAMPLES / "README.md").read_text(encoding="utf-8").splitlines()
           if ln.startswith("| `directional.json`")]
    assert len(row) == 1
    assert "反光點" in row[0] and "下方" in row[0] and "上方" not in row[0]


def test_every_documented_command_parses():
    """A reader must be able to paste a documented command: it has to pass the real argument parser
    (``render`` requires ``-o/--outdir``, formats and layers must be known, …)."""
    cmds = documented_commands()
    assert len(cmds) >= 6, cmds
    parser = cli.build_parser()
    for source, cmd in cmds:
        argv = cmd.split()[1:]
        try:
            args = parser.parse_args(argv)
        except SystemExit as exc:  # argparse reports a usage error with exit code 2
            pytest.fail(f"{source}: {cmd!r} is not a valid invocation (exit {exc.code})")
        if args.command == "render":
            assert args.outdir, f"{source}: {cmd!r} lacks -o/--outdir"
            cli._split(args.formats, cli.FORMATS, "format")
        scene = ROOT / argv[1]
        assert scene.is_file(), f"{source}: {cmd!r} names a missing scene file {scene}"


def test_usage_lists_every_public_function():
    """docs/USAGE.md §2 documents the Python API: every public function of every ``castplane``
    module (its ``__all__`` or the module-level defs) must be named there."""
    import importlib
    import inspect
    import pkgutil

    import castplane

    usage = (ROOT / "docs" / "USAGE.md").read_text(encoding="utf-8")
    missing = []
    for info in pkgutil.walk_packages(castplane.__path__, "castplane."):
        mod = importlib.import_module(info.name)
        names = getattr(mod, "__all__", None) or [
            n for n, f in inspect.getmembers(mod, inspect.isfunction) if f.__module__ == info.name and not n.startswith("_")]
        for n in names:
            if not re.search(r"`(\w+\.)?%s\b" % re.escape(n), usage):
                missing.append(f"{info.name}.{n}")
    assert not missing, f"public functions missing from docs/USAGE.md: {missing}"


def test_readme_milestone_table_reflects_the_benchmark_gate():
    """Spec §10 makes the §8 performance targets part of the M3 acceptance criteria.  The M3 row may
    only say 完成 without qualification when benchmarks/README.md records both targets as met;
    otherwise it must say that the camera-only target is missed, name the D17 waiver and point to the
    measurements."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    row = next(l for l in readme.splitlines() if l.startswith("| M3 "))
    bench = (ROOT / "benchmarks" / "README.md").read_text(encoding="utf-8")
    targets_met = "FAIL" not in bench and "not met" not in bench
    if targets_met:
        assert "尚未達標" not in row and "部分完成" not in row, row
    else:
        assert "尚未達標" in row and "benchmarks/README.md" in row and "D17" in row, row


# --------------------------------------------------------------------------- M4: hidden-line flags, info receivers
def _wall_scene() -> dict:
    from tests.test_receivers import wall_and_ground_scene
    return wall_and_ground_scene()


def test_m4_render_hidden_line_flags(tmp_path):
    """``--hidden-lines`` / ``--no-hidden-lines`` / ``--hidden-style`` are passed to the renderer; the scene
    file is not rewritten (contract §5.1.6.6, §5.0.7)."""
    scene = _wall_scene()
    path = write_json(tmp_path / "wall.json", scene)
    before = (tmp_path / "wall.json").read_text(encoding="utf-8")

    def run(*flags):
        out = tmp_path / ("out" + "".join(f.strip("-").replace("-", "_") for f in flags))
        assert main(["render", path, "-o", str(out), "-q", *flags]) == EXIT_OK
        doc = json.loads((out / "wall.json").read_text(encoding="utf-8"))
        return doc, (out / "wall.svg").read_text(encoding="utf-8")

    doc, svg = run()
    assert doc["hidden_lines"] is False and 'id="objects.hidden"' not in svg
    doc, svg = run("--hidden-lines")
    assert doc["hidden_lines"] is True and 'id="objects.hidden"' in svg
    assert any(e["visibility"] == "partial" for e in doc["edges"])
    dashed_lines = svg.count("<line")
    doc_o, svg_o = run("--hidden-lines", "--hidden-style", "omit")
    assert doc_o == doc and svg_o.count("<line") < dashed_lines and 'id="objects.hidden.crate"/>' in svg_o
    assert (tmp_path / "wall.json").read_text(encoding="utf-8") == before
    # the scene's own switch, overridden from the command line
    scene["output"]["hidden_lines"] = True
    on = write_json(tmp_path / "on.json", scene)
    assert main(["render", on, "-o", str(tmp_path / "on"), "-q"]) == EXIT_OK
    assert json.loads((tmp_path / "on" / "on.json").read_text(encoding="utf-8"))["hidden_lines"] is True
    assert main(["render", on, "-o", str(tmp_path / "off"), "-q", "--no-hidden-lines"]) == EXIT_OK
    assert json.loads((tmp_path / "off" / "on.json").read_text(encoding="utf-8"))["hidden_lines"] is False


def test_m4_hidden_line_flag_usage_errors(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["render", BASIC, "-o", str(tmp_path), "--hidden-lines", "--no-hidden-lines"])
    assert exc.value.code == EXIT_INPUT
    with pytest.raises(SystemExit) as exc:
        main(["render", BASIC, "-o", str(tmp_path), "--hidden-style", "dotted"])
    assert exc.value.code == EXIT_INPUT
    capsys.readouterr()


def test_m4_info_lists_receivers(tmp_path, capsys):
    path = write_json(tmp_path / "wall.json", _wall_scene())
    assert main(["info", path]) == EXIT_OK
    out = capsys.readouterr().out
    assert "receivers: 2" in out
    assert "ground (default): unbounded, plane [0, 0, 1, 0]; lit: lamp=yes; casts: lamp=no" in out
    assert "wall: bounded, 4 vertices, plane [0, -1, 0, 6]; lit: lamp=yes; casts: lamp=yes" in out
    assert main(["info", BASIC]) == EXIT_OK
    assert "receivers: 1" in capsys.readouterr().out


def test_usage_warning_table_lists_every_warning_code():
    """docs/USAGE.md §3 is the user-facing copy of the contract §2.9 / §5.0.5 warning table: every
    code of :data:`castplane.errors.WARNING_CODES` needs its own row there."""
    from castplane.errors import WARNING_CODES

    usage = (ROOT / "docs" / "USAGE.md").read_text(encoding="utf-8")
    section = usage.split("\n## 3. ", 1)[1].split("\n## 4", 1)[0]
    rows = {m.group(1) for m in re.finditer(r"^\| `([A-Z_]+)` \|", section, re.M)}
    missing = sorted(set(WARNING_CODES) - rows)
    assert not missing, f"warning codes without a docs/USAGE.md §3 row: {missing}"


def test_documented_import_commands_run(tmp_path, monkeypatch):
    """Every documented ``castplane import`` example (M5) runs from the repository root and writes a
    scene that ``castplane validate`` accepts (outputs redirected into a temporary directory)."""
    monkeypatch.chdir(ROOT)
    cmds = [c for _, c in documented_commands() if c.split()[1] == "import"]
    assert len(cmds) >= 3, cmds
    for k, cmd in enumerate(cmds):
        argv = cmd.split()[1:]
        out = tmp_path / f"s{k}.json"
        if "-o" in argv:
            argv[argv.index("-o") + 1] = str(out)
        else:
            argv += ["-o", str(out)]
        assert main(argv + ["-q"]) == EXIT_OK, cmd
        assert main(["validate", str(out), "-q"]) == EXIT_OK, cmd    # mesh paths resolve from the output directory
