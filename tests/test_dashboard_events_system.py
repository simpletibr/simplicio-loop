"""System tests: the dashboard-event/v1 CLI, drift gate and overhead budget as shipped (#1398)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "dashboard_events.py"
GATE = REPO / "scripts" / "check_dashboard_event_contract.py"
FIXTURES = REPO / "contracts" / "dashboard-event" / "v1" / "fixtures"


def _run(*args, env=None, timeout=120):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True,
                          cwd=str(REPO), timeout=timeout, stdin=subprocess.DEVNULL, env=env)


def test_cli_emit_then_read_round_trips_a_valid_event(tmp_path):
    run_dir = tmp_path / "run-cli"
    run_dir.mkdir()
    emitted = _run(SCRIPT, "emit", run_dir, "--kind", "worker_claimed", "--source", "worker",
                   "--phase", "executing", "--task-id", "T1", "--lane", "lane-a",
                   "--iteration", "2", "--payload", '{"step": "claim"}', "--ref", "receipts/a.json")
    assert emitted.returncode == 0, emitted.stderr
    event = json.loads(emitted.stdout)
    assert event["seq"] == 1 and event["scope"] == "task" and event["refs"] == ["receipts/a.json"]

    read = _run(SCRIPT, "read", run_dir)
    assert read.returncode == 0, read.stderr
    lines = [json.loads(line) for line in read.stdout.splitlines() if line.strip()]
    assert lines == [event]
    assert _run(SCRIPT, "read", run_dir, "--since", "1").stdout.strip() == ""

    assert _run(SCRIPT, "validate", run_dir / "events.jsonl").returncode == 0


def test_cli_validate_rejects_every_negative_fixture():
    result = _run(SCRIPT, "validate", FIXTURES / "invalid.jsonl")
    assert result.returncode == 1
    negatives = [line for line in (FIXTURES / "invalid.jsonl").read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    assert "validate: %d error(s)" % len(negatives) in result.stdout + result.stderr


def test_cli_validate_accepts_every_positive_fixture():
    files = sorted(p for p in FIXTURES.glob("*.jsonl") if p.name != "invalid.jsonl")
    assert len(files) >= 3
    result = _run(SCRIPT, "validate", *files)
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_selftest_passes():
    result = _run(SCRIPT, "selftest")
    assert result.returncode == 0, result.stdout + result.stderr


def test_drift_gate_passes_on_the_committed_fixtures():
    result = _run(GATE)
    assert result.returncode == 0, result.stdout + result.stderr


def test_drift_gate_fails_when_a_fixture_drifts_from_the_producers(tmp_path):
    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    path = copy / "runner-lifecycle.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["severity"] = "error" if first["severity"] != "error" else "info"
    lines[0] = json.dumps(first)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = _run(GATE, "--fixtures", copy)
    assert result.returncode == 1, result.stdout + result.stderr


def test_drift_gate_fails_when_a_negative_fixture_becomes_valid(tmp_path):
    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    valid = (FIXTURES / "runner-lifecycle.jsonl").read_text(encoding="utf-8").splitlines()[0]
    with (copy / "invalid.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(valid + "\n")
    result = _run(GATE, "--fixtures", copy)
    assert result.returncode == 1, result.stdout + result.stderr


def test_emit_overhead_p95_stays_under_one_millisecond():
    best = None
    for _ in range(3):
        result = _run(SCRIPT, "bench", "--events", "500", "--json")
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["written"] == 500
        best = report["p95_ms"] if best is None else min(best, report["p95_ms"])
        if best < 1.0:
            break
    assert best < 1.0, "p95 %.3f ms" % best


def test_check_py_runs_the_dashboard_events_phase():
    source = (REPO / "scripts" / "check.py").read_text(encoding="utf-8")
    assert "def run_dashboard_events_contract" in source
    assert "check_dashboard_event_contract.py" in source
    assert "dashboard-events=" in source


def test_drift_gate_write_regenerates_fixtures_that_then_pass(tmp_path):
    out = tmp_path / "regenerated"
    written = _run(GATE, "--write", "--fixtures", out)
    assert written.returncode == 0, written.stdout + written.stderr
    shutil.copy(FIXTURES / "invalid.jsonl", out / "invalid.jsonl")
    for name in ("runner-lifecycle.jsonl", "hook-events.jsonl", "derived-legacy-run.jsonl"):
        assert len((out / name).read_text(encoding="utf-8").splitlines()) == \
            len((FIXTURES / name).read_text(encoding="utf-8").splitlines())
    result = _run(GATE, "--fixtures", out)
    assert result.returncode == 0, result.stdout + result.stderr
