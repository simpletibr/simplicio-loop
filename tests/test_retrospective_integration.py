import json

from simplicio_loop.retrospective import retrospective


def test_retrospective_deduplicates_and_writes_receipt(tmp_path):
    trajectory = tmp_path / ".simplicio-loop" / "orchestrator" / "trajectory"
    trajectory.mkdir(parents=True)
    (trajectory / "run-1.jsonl").write_text(
        json.dumps({"status": "merged", "lesson": "Use ff-only pulls."}) + "\n"
        + json.dumps({"status": "merged", "lesson": "Use ff-only pulls."}) + "\n",
        encoding="utf-8",
    )
    result = retrospective(tmp_path, "run-1")
    assert result["records_seen"] == 2
    assert result["new"] == 1
    assert result["merged"] == 1
    rows = [json.loads(line) for line in (tmp_path / ".simplicio-loop/orchestrator/lessons.jsonl").read_text().splitlines()]
    assert rows[0]["hit_count"] == 2
    receipt = json.loads((tmp_path / ".simplicio-loop/orchestrator/retrospective-receipt.json").read_text())
    assert receipt["schema"] == "simplicio.retrospective-receipt/v1"


def test_retrospective_ignores_malformed_and_unmarked_records(tmp_path):
    trajectory = tmp_path / ".simplicio-loop" / "orchestrator" / "trajectory"
    trajectory.mkdir(parents=True)
    (trajectory / "run-2.jsonl").write_text("not-json\n{}\n", encoding="utf-8")
    result = retrospective(tmp_path, "run-2")
    assert result["records_seen"] == 1
    assert result["candidates"] == 0
    assert result["new"] == 0
