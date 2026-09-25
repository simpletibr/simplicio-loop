import json
from pathlib import Path

from benchmarks.bench_task_recall_240 import CORPUS, _consume_selected


def test_issue_240_task_corpus_is_versioned_and_explicit_about_external_gates() -> None:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    assert corpus["schema"] == "simplicio.fast.delivery-task-corpus/v1"
    assert corpus["scope"] == "frozen-source-task-fixture"
    assert len(corpus["tasks"]) == 4
    assert all(Path(item["expected_files"][0]).is_absolute() is False for item in corpus["tasks"])
    assert all(item["text"] and item["expected_files"] for item in corpus["tasks"])


def test_issue_240_bounded_downstream_consumer_rejects_escape_and_records_success(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "target.py").write_text("value = 1\n", encoding="utf-8")
    task = {"expected_files": ["src/target.py"]}
    success = _consume_selected(tmp_path, task, ["src/target.py"])
    assert success == {
        "success": True,
        "selected_count": 1,
        "read_bytes": len((source / "target.py").read_bytes()),
        "failures": [],
    }
    escape = _consume_selected(tmp_path, task, ["../outside.py"])
    assert escape["success"] is False
    assert "path_outside_root:../outside.py" in escape["failures"]
    assert "missing_expected:src/target.py" in escape["failures"]
