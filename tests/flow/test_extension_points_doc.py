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


def test_every_row_has_a_valid_state_and_evidence():
    for number, name, state in _doc_rows():
        assert state in STATES, f"point {number} {name}: invalid state {state!r}"
    text = DOC.read_text(encoding="utf-8")
    for number, name, _ in _doc_rows():
        row = next(line for line in text.splitlines() if line.startswith(f"| {number} | `{name}` |"))
        evidence = row.split("|")[4].strip()
        assert evidence, f"point {number} {name}: empty evidence cell"
