"""Contract / user-doc wording checked against the code (final review, group 'misc'): the camera-free
conic fields of §5.0.3 / §5.4.7, the reserved-id messages of §5.0.1, the per-receiver outline group ids
of §5.0.6 / §5.1.8 / README / USAGE and the scene count of the M4 depth-buffer note."""

from __future__ import annotations

import copy
import json
import pathlib
import re

import pytest

import castplane
from castplane.scene import SceneError

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _arch() -> str:
    return (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")


def _between(text: str, start: str, stop: str) -> str:
    i = text.index(start)
    return text[i:text.index(stop, i)]


def _conic_fields(paragraph: str) -> set:
    found = re.findall(r"conics\[\]\.\{([^}]*)\}", paragraph)
    assert found, paragraph[:200]
    return {f.strip() for group in found for f in group.split(",")}


def camera_free_conic_fields() -> list:
    """The ``conics[]`` fields that §5.0.3 and §5.4.7 list as camera-free."""
    text = _arch()
    p503 = _between(text, "**Camera-free parts**", "Camera-dependent:")
    p547 = _between(text, "**Camera-free parts of a document [decision, exact list]**", "camera-dependent).")
    return [_conic_fields(p503), _conic_fields(p547)]


def _other_camera(scene):
    cam = dict(scene["camera"])
    for k in ("yaw_deg", "pitch_deg"):
        cam.pop(k, None)
    cam.update(position=[-7.0, -5.0, 6.0], target=[0.0, 2.0, 0.0], roll_deg=7.0)
    return cam


@pytest.mark.parametrize("example", ["curved_demo.json", "two_lights.json"])
def test_camera_free_conic_fields_are_camera_free(example):
    """determinism-perf#1: every ``conics[]`` field §5.0.3 / §5.4.7 call camera-free is byte-identical for two
    cameras (the image conic ``conic`` / ``kind`` is not: ``H = P·M·E``, §2.6)."""
    scene = castplane.load_scene(str(ROOT / "examples" / example))
    d1 = castplane.render(scene)["geometry"]
    d2 = castplane.render(scene, camera=_other_camera(scene))["geometry"]
    assert [len(s["conics"]) for s in d1["shadows"]] == [len(s["conics"]) for s in d2["shadows"]]
    assert "POINT_BEHIND_CAMERA" not in {w["code"] for w in d1["warnings"] + d2["warnings"]}
    entries = [(c1, c2) for s1, s2 in zip(d1["shadows"], d2["shadows"]) for c1, c2 in zip(s1["conics"], s2["conics"])]
    assert entries, "the example must have conic shadows"
    for fields in camera_free_conic_fields():
        for c1, c2 in entries:
            for f in sorted(fields):
                assert json.dumps(c1.get(f), sort_keys=True) == json.dumps(c2.get(f), sort_keys=True), f


def test_reserved_id_messages_match_section_5_0_1():
    """docs-contract#6: the §5.0.1 reserved-id row names both messages the loader emits."""
    row = next(ln for ln in _arch().splitlines() if ln.startswith("| `objects[i].id` / `receivers[i].id` / `lights[i].id`"))
    base = json.loads((ROOT / "examples" / "basic.json").read_text(encoding="utf-8"))
    cases = []
    s = copy.deepcopy(base)
    s["lights"].append(dict(s["lights"][0], id="umbra"))
    cases.append((s, "lights[1].id"))
    s = copy.deepcopy(base)
    s["lights"].append(dict(s["lights"][0], id="other"))
    s["objects"][0]["id"] = "core"
    cases.append((s, "objects[0].id"))
    s = copy.deepcopy(base)
    s["objects"][0]["id"] = "hidden"
    cases.append((s, "objects[0].id"))
    for scene, field in cases:
        with pytest.raises(SceneError) as info:
            castplane.load_scene(scene)
        assert info.value.field == field
        message = str(info.value)[len(field) + 2:]
        assert f'`"{message}"`' in row, (message, row)


def test_per_receiver_outline_group_ids_are_documented():
    """docs-contract#5: on a receiver other than ``receivers[0]`` the outline / conics groups are
    ``cast_shadow.<light>.<object>.<r>.outline`` / ``.conics``; the writer does that and the user docs and the
    contract body say so."""
    from castplane.output.svg import write_svg
    scene = castplane.load_scene(str(ROOT / "examples" / "wall_and_ground.json"))
    doc = castplane.render(scene, hidden_lines=True)["geometry"]
    ids = re.findall(r'<g id="(cast_shadow\.[^"]*\.outline)"', write_svg(doc))
    first = doc["receivers"][0]["id"]
    expected = sorted({f"cast_shadow.{sh['light']}.{sh['object']}"
                       f"{'' if sh['receiver'] == first else '.' + sh['receiver']}.outline" for sh in doc["shadows"]})
    assert sorted(ids) == expected and any(i.count(".") == 4 for i in ids)
    pattern = "cast_shadow.<light>.<object>.<r>.outline"
    arch = _arch()
    assert pattern in _between(arch, "#### 5.0.6", "#### 5.0.7")
    assert pattern in _between(arch, "#### 5.1.8", "#### 5.1.9")
    for doc_path in (ROOT / "README.md", ROOT / "docs" / "USAGE.md"):
        assert pattern in doc_path.read_text(encoding="utf-8"), doc_path


def test_depth_buffer_note_counts_the_scenes():
    """m4-hidden#2: the M4 note on the depth-buffer guard counts every scene of ``ZBUFFER_SCENES``."""
    from tests.test_hidden import ZBUFFER_SCENES
    m = re.search(r"over the (\d+) depth-buffer scenes of `tests/test_hidden.py`", _arch())
    assert m and int(m.group(1)) == len(ZBUFFER_SCENES)


def _degenerate_camera(scene):
    """A camera inside the construction (near plane through the drum / pillar): drops or near-cuts conics."""
    cam = dict(scene["camera"])
    for k in ("yaw_deg", "pitch_deg"):
        cam.pop(k, None)
    cam.update(position=[0.0, 3.0, 0.4], target=[3.0, 3.0, 0.4], roll_deg=3.0)
    return cam


@pytest.mark.parametrize("example", ["curved_demo.json", "basic.json"])
def test_camera_free_conic_fields_need_an_object_in_front_of_the_near_plane(example):
    """Final review, second pass: §2.6 near-clips ``arc`` and stage B drops an arc wholly behind the near plane,
    so the ``conics[]`` entry list and ``arc`` change with the camera exactly for the objects that warn
    ``POINT_BEHIND_CAMERA``; §5.0.3 / §5.4.7 restrict the camera-free claim to the other objects."""
    scene = castplane.load_scene(str(ROOT / "examples" / example))
    d1 = castplane.render(scene)["geometry"]
    d2 = castplane.render(scene, camera=_degenerate_camera(scene))["geometry"]
    behind = {i for w in d1["warnings"] + d2["warnings"] if w["code"] == "POINT_BEHIND_CAMERA" for i in w["ids"]}
    fields = set.union(*camera_free_conic_fields())
    changed = set()
    for s1, s2 in zip(d1["shadows"], d2["shadows"]):
        assert (s1["object"], s1["light"], s1["receiver"]) == (s2["object"], s2["light"], s2["receiver"])
        same = len(s1["conics"]) == len(s2["conics"]) and all(
            json.dumps(c1.get(f), sort_keys=True) == json.dumps(c2.get(f), sort_keys=True)
            for c1, c2 in zip(s1["conics"], s2["conics"]) for f in fields)
        if not same:
            changed.add(s1["object"])
    assert changed, "the degenerate camera must change some conic entry list"
    assert changed <= behind, (changed, behind)
    text = _arch()
    for paragraph in (_between(text, "**Camera-free parts**", "Camera-dependent:"),
                      _between(text, "**Camera-free parts of a document [decision, exact list]**", "camera-dependent).")):
        assert "POINT_BEHIND_CAMERA" in paragraph and "entry list" in paragraph
