import json
from pathlib import Path


MATRIX = Path(__file__).parents[1] / "fixtures" / "changeset" / "v1" / "issue241-ac-matrix.json"


def test_issue_241_matrix_is_complete_and_does_not_hide_residuals() -> None:
    payload = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert payload["schema"] == "simplicio.fast.issue241-ac-matrix/v1"
    assert payload["status"] == "partial"
    assert payload["closure_ready"] is False
    assert len(payload["rows"]) == 12
    assert {row["status"] for row in payload["rows"]} == {"measured", "partial"}
    assert any(row["residual"] for row in payload["rows"])
    assert all(row["evidence"] for row in payload["rows"])
