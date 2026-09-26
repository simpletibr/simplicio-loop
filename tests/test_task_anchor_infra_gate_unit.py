"""Tests for the #526 Etapa 3 extension of scripts/task_anchor.py: the three-state gate
(`verified` / `waived:no-infra` / `pending`), the mandatory-reason waiver, and the "external
harness" evidence form's 3-artifact validation — plus the AC4 fixture end-to-end: a .NET repo
with no test project + a goal to fix one function reaches gate READY with unit verified via an
external harness and coverage/benchmark waived:no-infra, WITHOUT creating any file in the target
repo (only in the harness's own scratch location).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from scripts import task_anchor
from scripts import test_infra_probe

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "task_anchor.py"


def _snapshot(root: Path):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def _cli(anchor_path, *args):
    import os
    env = dict(os.environ)
    env["SIMPLICIO_ANCHOR_FILE"] = str(anchor_path)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO, text=True, capture_output=True, stdin=subprocess.DEVNULL, env=env,
    )


# ----- pure helpers -------------------------------------------------------------------------------

def test_coverage_excludes_waived_from_pending_and_from_done():
    criteria = [
        {"id": "AC1", "status": "done"},
        {"id": "AC2", "status": "waived:no-infra", "waived_reason": "no coverage tooling"},
        {"id": "AC3", "status": "pending"},
    ]
    done, total, pending = task_anchor.coverage(criteria)
    assert done == 1
    assert total == 3
    assert pending == ["AC3"]


def test_waived_accessor_returns_only_waived_criteria_with_reason():
    criteria = [
        {"id": "AC1", "status": "done"},
        {"id": "AC2", "status": "waived:no-infra", "waived_reason": "no perf harness"},
    ]
    w = task_anchor.waived(criteria)
    assert len(w) == 1
    assert w[0]["id"] == "AC2"
    assert w[0]["waived_reason"] == "no perf harness"


def test_gate_ready_once_only_waived_and_done_remain():
    criteria = [
        {"id": "AC1", "status": "done"},
        {"id": "AC2", "status": "waived:no-infra", "waived_reason": "r"},
        {"id": "AC3", "status": "waived:no-infra", "waived_reason": "r2"},
    ]
    done, total, pending = task_anchor.coverage(criteria)
    assert bool(total) and not pending  # this is exactly cmd_gate's READY predicate


def test_render_checklist_shows_waived_box_and_reason():
    criteria = [
        {"id": "AC1", "text": "Unit tests pass", "status": "done", "evidence": "e", "verify": ""},
        {"id": "AC2", "text": "Coverage >=85%", "status": "waived:no-infra",
         "waived_reason": "no coverage tooling detected", "verify": ""},
    ]
    md = task_anchor.render_checklist(criteria)
    assert "[w] **AC2**" in md
    assert "no coverage tooling detected" in md
    assert "1 waived:no-infra" in md


def test_render_checklist_waived_without_reason_shows_placeholder_never_blank():
    criteria = [{"id": "AC1", "text": "x", "status": "waived:no-infra", "verify": ""}]
    md = task_anchor.render_checklist(criteria)
    assert "(no reason recorded)" in md


# ----- external harness evidence form --------------------------------------------------------------

def test_verify_harness_content_requires_all_three_artifacts():
    good_log = "case_one PASS\n"
    good_hash = hashlib.sha256(b"snippet").hexdigest()
    assert task_anchor.verify_harness_content("", good_log, good_hash)[0] is False
    assert task_anchor.verify_harness_content("src", "", good_hash)[0] is False
    assert task_anchor.verify_harness_content("src", good_log, "")[0] is False
    assert task_anchor.verify_harness_content("src", good_log, good_hash)[0] is True


def test_verify_harness_content_hash_must_match_real_snippet():
    log = "case_one PASS\n"
    real = b"def add(a, b):\n    return a + b\n"
    correct_hash = hashlib.sha256(real).hexdigest()
    ok, reason, _ = task_anchor.verify_harness_content("src", log, correct_hash, snippet_bytes=real)
    assert ok is True
    ok2, reason2, _ = task_anchor.verify_harness_content(
        "src", log, correct_hash, snippet_bytes=b"a different function entirely")
    assert ok2 is False
    assert "does not match" in reason2


def test_verify_harness_content_any_failed_case_invalidates():
    log = "case_one PASS\ncase_two FAIL\n"
    ok, reason, _ = task_anchor.verify_harness_content(
        "src", log, hashlib.sha256(b"x").hexdigest())
    assert ok is False
    assert "case_two" in reason


def test_verify_harness_artifacts_reads_real_files(tmp_path):
    harness_dir = tmp_path / "harness"
    harness_dir.mkdir()
    (harness_dir / "harness_source.py").write_text("def add(a,b): return a+b\n", encoding="utf-8")
    (harness_dir / "run.log").write_text("case_add_pos PASS\ncase_add_neg PASS\n", encoding="utf-8")
    snippet = tmp_path / "Calc.cs"
    snippet_bytes = b"class Calc { int Add(int a, int b) => a + b; }"
    snippet.write_bytes(snippet_bytes)
    (harness_dir / "snippet.sha256").write_text(hashlib.sha256(snippet_bytes).hexdigest(),
                                                encoding="utf-8")
    ok, reason, detail = task_anchor.verify_harness_artifacts(
        str(harness_dir / "harness_source.py"), str(harness_dir / "run.log"),
        str(harness_dir / "snippet.sha256"), str(snippet))
    assert ok is True, reason
    assert detail["cases"] == 2


def test_verify_harness_artifacts_missing_file_fails_closed(tmp_path):
    ok, reason, _ = task_anchor.verify_harness_artifacts(
        str(tmp_path / "nope.py"), str(tmp_path / "nope.log"), str(tmp_path / "nope.sha256"))
    assert ok is False
    assert "missing harness artifact" in reason


def test_cli_mark_waived_without_reason_is_blocked(tmp_path):
    anchor = tmp_path / "anchor.json"
    r1 = _cli(anchor, "set", "--item", "x", "--goal", "g", "--ac", "Unit tests pass")
    assert r1.returncode == 0
    r2 = _cli(anchor, "mark", "--id", "AC1", "--status", "waived:no-infra")
    assert r2.returncode == 12
    assert "requires --reason" in (r2.stdout + r2.stderr)


def test_cli_verify_harness_ok_and_invalid(tmp_path):
    harness_dir = tmp_path / "harness"
    harness_dir.mkdir()
    (harness_dir / "harness_source.py").write_text("src", encoding="utf-8")
    (harness_dir / "run.log").write_text("case_one PASS\n", encoding="utf-8")
    (harness_dir / "snippet.sha256").write_text(hashlib.sha256(b"x").hexdigest(), encoding="utf-8")
    anchor = tmp_path / "anchor.json"
    anchor.write_text(json.dumps({"criteria": []}), encoding="utf-8")
    r = _cli(anchor, "verify_harness", "--harness-dir", str(harness_dir), "--exit-code")
    assert r.returncode == 0
    assert "harness-ok" in r.stdout

    (harness_dir / "run.log").unlink()
    r2 = _cli(anchor, "verify_harness", "--harness-dir", str(harness_dir), "--exit-code")
    assert r2.returncode == 12
    assert "harness-invalid" in r2.stdout


def test_gate_json_surfaces_waived_with_reason(tmp_path):
    anchor = tmp_path / "anchor.json"
    _cli(anchor, "set", "--item", "x", "--goal", "g", "--ac", "Unit tests pass",
        "--ac", "Coverage >=85%")
    _cli(anchor, "mark", "--id", "AC1", "--status", "done", "--evidence", "e")
    _cli(anchor, "mark", "--id", "AC2", "--status", "waived:no-infra", "--reason", "no tooling")
    r = _cli(anchor, "gate", "--json")
    payload = json.loads(r.stdout)
    assert payload["ready"] is True
    assert payload["waived"] == [{"id": "AC2", "text": "Coverage >=85%", "reason": "no tooling"}]


# ----- AC4: the real-case fixture ------------------------------------------------------------------

def test_dotnet_no_test_project_fixture_reaches_ready_via_harness_and_waivers(tmp_path):
    """Reproduces the exact AC4 scenario: a .NET repo with no test project + a goal to fix one
    function. The gate must reach READY with unit verified via an EXTERNAL harness and
    coverage/benchmark waived:no-infra — and NOT ONE new file may appear in the target repo."""
    target_repo = tmp_path / "dotnet-repo"
    target_repo.mkdir()
    calc_source = "public class Calc {\n    public int Add(int a, int b) { return a + b; }\n}\n"
    calc_path = target_repo / "Calc.cs"
    calc_path.write_text(calc_source, encoding="utf-8")
    (target_repo / "App.csproj").write_text(
        "<Project Sdk=\"Microsoft.NET.Sdk\"><PropertyGroup><TargetFramework>net8.0"
        "</TargetFramework></PropertyGroup></Project>", encoding="utf-8")

    before = _snapshot(target_repo)

    # 1) MEASURED probe of the target repo: no test project, no coverage tooling, no CI.
    probe_result = test_infra_probe.probe(target_repo)
    assert probe_result["test_infra"] == {"unit": "absent", "coverage": "absent", "ci": "absent"}

    # 2) anchor lives OUTSIDE the target repo (this loop's own .simplicio-loop/orchestrator, standing in for it
    #    here as a tmp_path anchor) — freezing the goal + the 3 DoD-shaped dimensions in play.
    anchor = tmp_path / "anchor.json"
    r = _cli(anchor, "set", "--item", "526-fixture", "--goal", "Fix Calc.Add",
            "--ac", "Unit tests pass", "--ac", "Coverage >=85%", "--ac", "Benchmark within budget")
    assert r.returncode == 0

    # 3) unit: an external harness in ITS OWN scratch dir (never inside target_repo) mirrors the
    #    real Calc.cs via a sha256-bound snippet hash, runs, and every named case passes.
    harness_scratch = tmp_path / "harness_scratch"
    harness_scratch.mkdir()
    (harness_scratch / "harness_source.py").write_text(
        "def add(a, b):\n    return a + b\n\n"
        "assert add(2, 3) == 5\n"
        "assert add(-1, 1) == 0\n", encoding="utf-8")
    (harness_scratch / "run.log").write_text(
        "case_add_positive PASS\ncase_add_zero_sum PASS\n", encoding="utf-8")
    (harness_scratch / "snippet.sha256").write_text(
        hashlib.sha256(calc_path.read_bytes()).hexdigest(), encoding="utf-8")

    hr = _cli(anchor, "verify_harness", "--harness-dir", str(harness_scratch),
             "--snippet", str(calc_path), "--exit-code")
    assert hr.returncode == 0, hr.stdout + hr.stderr
    assert "harness-ok" in hr.stdout

    mr = _cli(anchor, "mark", "--id", "AC1", "--status", "done",
             "--evidence", "external-harness %s (2 cases, all PASS)" % harness_scratch)
    assert mr.returncode == 0

    # 4) coverage/benchmark: structurally impossible per the MEASURED probe -> waived:no-infra.
    r_cov = _cli(anchor, "mark", "--id", "AC2", "--status", "waived:no-infra",
                "--reason", "no coverage tooling detected (test_infra_probe: coverage=absent)")
    assert r_cov.returncode == 0
    r_bench = _cli(anchor, "mark", "--id", "AC3", "--status", "waived:no-infra",
                  "--reason", "no benchmark/perf harness detected (test_infra_probe)")
    assert r_bench.returncode == 0

    # 5) the gate reaches READY.
    gate = _cli(anchor, "gate", "--json", "--exit-code")
    assert gate.returncode == 0, gate.stdout + gate.stderr
    payload = json.loads(gate.stdout)
    assert payload["ready"] is True
    assert payload["pending"] == []
    reasons = {w["id"]: w["reason"] for w in payload["waived"]}
    assert reasons["AC2"].startswith("no coverage tooling detected")
    assert reasons["AC3"].startswith("no benchmark/perf harness detected")

    # 6) NOT ONE file was created inside the target repo — only the harness's own scratch dir
    #    (a sibling directory, never target_repo) grew any files.
    assert _snapshot(target_repo) == before
