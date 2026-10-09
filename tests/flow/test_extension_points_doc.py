"""docs/EXTENSION_POINTS_SERVICE.md lists exactly the 50 points of simplicio-loop.project.json, in order."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "EXTENSION_POINTS_SERVICE.md"
PROJECT = ROOT / "simplicio-loop.project.json"
STATES = {"ligado", "parcial", "ausente"}
ROW = re.compile(r"^\| (\d+) \| `([^`]+)` \| (\w+) \| (.+) \|$")


def _json_names() -> list[str]:
    points = json.loads(PROJECT.read_text(encoding="utf-8"))["extension_points_50"]["points"]
    return [point["name"] for point in points]


def _doc_rows() -> list[tuple[int, str, str]]:
    rows = []
    for line in DOC.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match:
            rows.append((int(match.group(1)), match.group(2), match.group(3)))
    return rows


def test_json_declares_fifty_points():
    assert len(_json_names()) == 50


def test_doc_lists_exactly_the_fifty_json_names_in_order():
    rows = _doc_rows()
    assert [number for number, _, _ in rows] == list(range(1, 51))
    assert [name for _, name, _ in rows] == _json_names()


def test_summary_counts_match_the_rows():
    counted = {state: sum(1 for _, _, s in _doc_rows() if s == state) for state in STATES}
    text = DOC.read_text(encoding="utf-8")
    summary = {m.group(1): int(m.group(2)) for m in re.finditer(r"^\| (ligado|parcial|ausente) \| (\d+) \|$", text, re.M)}
    assert summary == counted
    assert sum(counted.values()) == 50


def test_every_row_has_a_valid_state_and_evidence():
    for number, name, state in _doc_rows():
        assert state in STATES, f"point {number} {name}: invalid state {state!r}"
    text = DOC.read_text(encoding="utf-8")
    for number, name, _ in _doc_rows():
        row = next(line for line in text.splitlines() if line.startswith(f"| {number} | `{name}` |"))
        evidence = row.split("|")[4].strip()
        assert evidence, f"point {number} {name}: empty evidence cell"


def _rows_by_name() -> dict[str, str]:
    return {name: state for _, name, state in _doc_rows()}


def _registered_names() -> list[str]:
    from simplicio_loop.watcher247 import points

    return [info.name for info in points.registered() if not info.name.startswith("import_failed:")]


def test_every_registered_point_is_a_point_of_the_list_and_never_ausente():
    states = _rows_by_name()
    registered = _registered_names()
    assert registered, "the registry is empty"
    for name in registered:
        assert name in states, f"registered point {name!r} is not one of the 50"
        assert states[name] != "ausente", f"{name} is registered and runs in the tick, so it is not ausente"


def test_a_blocking_registered_point_is_ligado():
    from simplicio_loop.watcher247 import points

    states = _rows_by_name()
    for info in points.registered():
        if info.blocking and not info.name.startswith("import_failed:"):
            assert states[info.name] == "ligado", f"{info.name} blocks the stage, so it acts on the run"


PIE_VALUES = re.compile(r'^\s+"[^"]*(?:Wired|ligado)[^"]*" : (\d+)\n\s+"[^"]*(?:Partial|parcial)[^"]*" : (\d+)\n'
                        r'\s+"[^"]*(?:Absent|ausente)[^"]*" : (\d+)$', re.M)


def _summary() -> tuple[int, int, int]:
    counted = [sum(1 for _, _, s in _doc_rows() if s == state) for state in ("ligado", "parcial", "ausente")]
    return counted[0], counted[1], counted[2]


def test_every_readme_pie_quotes_the_summary():
    readmes = [ROOT / "README.md", *sorted((ROOT / "READMEs").glob("README.*.md"))]
    assert len(readmes) == 15
    for path in readmes:
        found = PIE_VALUES.findall(path.read_text(encoding="utf-8"))
        assert found == [tuple(str(n) for n in _summary())], f"{path.name}: pie {found} != {_summary()}"


def test_the_guide_quotes_the_summary_and_lists_the_points_by_state():
    text = (ROOT / "docs" / "GUIDE.md").read_text(encoding="utf-8")
    assert PIE_VALUES.findall(text) == [tuple(str(n) for n in _summary())]
    rows = _rows_by_name()
    for state in ("ligado", "parcial", "ausente"):
        cell = re.search(rf"^\| \*\*{state}\*\* \((\d+)\) \| (.+) \|$", text, re.M)
        assert cell, f"GUIDE.md has no {state} row"
        listed = re.findall(r"`([^`]+)`", cell.group(2))
        assert int(cell.group(1)) == len(listed)
        expected = [name.split(" / ")[0] for name in rows if rows[name] == state]  # the guide uses the short name
        assert sorted(listed) == sorted(expected), f"GUIDE.md {state}: {sorted(set(listed) ^ set(expected))}"
    assert f"**Only {_summary()[0]} are on.**" in text
