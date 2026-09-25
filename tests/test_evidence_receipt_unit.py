import json
import os
import subprocess
import sys
from types import SimpleNamespace

import simplicio_loop.evidence as evidence_mod
from simplicio_loop.evidence import execute_receipt_checks, redact_sensitive_text

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = [sys.executable, "-m", "simplicio_loop.cli"]
WATCHER = os.path.join(REPO, "scripts", "watcher_verify.py")
EVIDENCE = os.path.join(REPO, "scripts", "evidence_receipt.py")

TASK = """Sistema: PLANES
Funcionalidade: Tela de Modelagem — Ordenação de linhas
Tipo: Evolução

COMO analista do ONS,
QUERO organizar as linhas
PARA melhorar a análise

1. Critérios de Aceite

Cenário 1: Estrutural aparece primeiro
  Dado que existe uma linha estrutural
  Quando a tela for exibida
  Então a linha estrutural aparece primeiro [RN01]

2. Regras de Negócio

RN01 – Estrutural sempre primeiro.
"""


def _run(cmd, cwd, env=None):
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=30,
                          stdin=subprocess.DEVNULL, env=full_env)


def test_evidence_receipt_built_from_run_and_watcher_reads_it(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    src = repo / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    task = tmp_path / "task.md"
    task.write_text(TASK, encoding="utf-8")
    operator_bin = tmp_path / "bin"
    operator_bin.mkdir()
    mapper_script = operator_bin / "simplicio-mapper.py"
    mapper_script.write_text(
        """#!/usr/bin/env python3
import json
import sys

if len(sys.argv) > 1 and sys.argv[1] == "inspect":
    print(json.dumps({
        "status": {"artifacts_present": True, "fresh": True},
        "evidence": {"artifacts": {"snapshot": {"exists": True}}},
    }))
elif len(sys.argv) > 1 and sys.argv[1] == "handoff":
    print(json.dumps({
        "context_pack": {
            "pack_hash": "test-evidence-receipt",
            "files": [{"path": "src/app.py"}],
        }
    }))
else:
    print("{}")
""",
        encoding="utf-8",
    )
    if os.name == "nt":
        mapper = operator_bin / "simplicio-mapper.cmd"
        mapper.write_text(
            f'@echo off\n"{sys.executable}" "{mapper_script}" %*\n',
            encoding="utf-8",
        )
    else:
        mapper = operator_bin / "simplicio-mapper"
        mapper_script.replace(mapper)
        mapper.chmod(0o755)
    fake_operator = json.dumps({
        "execution_state": "dry_run",
        "returncode": 0,
        "stdout": {"kind": "operator-proposal", "ok": True},
        "stderr": "",
        "argv": ["simplicio-dev-cli", "task", "demo"]
    })
    fake_mapper_preflight = json.dumps({
        "version_stdout": "simplicio-mapper 0.26.0",
        "help_stdout": " scan inspect handoff ask sync drift ",
        "version_returncode": 0,
        "help_returncode": 0,
    })
    fake_devcli_preflight = json.dumps({
        "version_stdout": "simplicio-dev-cli 0.18.0",
        "help_stdout": " edit --plan --apply --dry-run --json ",
        "version_returncode": 0,
        "help_returncode": 0,
    })
    started = _run(CLI + ["run", "--repo", str(repo), "--task", str(task),
                          "--delivery", "verified", "--max-iterations", "9",
                          "--quality-provider", "simplicio_loop_quality"], REPO,
                   env={
                       "SIMPLICIO_LOOP_FAKE_OPERATOR_JSON": fake_operator,
                       "SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON": fake_mapper_preflight,
                       "SIMPLICIO_LOOP_FAKE_DEVCLI_PREFLIGHT_JSON": fake_devcli_preflight,
                       # Do not inherit a host-installed operator: this test proves the
                       # explicit dry-run boundary and must remain PARTIAL everywhere.
                       "PATH": str(operator_bin) + os.pathsep + os.defpath,
                       # Mandatory mutation-authority is a separate, later gate (host-supplied
                       # plan.json) than the dry-run proposal this test exercises -- opt out
                       # of it here the same way other fixtures in this suite do.
                       "SIMPLICIO_REQUIRE_MUTATION_AUTHORITY": "0",
                   })
    assert started.returncode == 22, started.stdout + started.stderr
    payload = json.loads(started.stdout)
    assert payload["outcome"]["outcome"] == "PARTIAL"
    run_dir = payload["run_dir"]
    evidence_path = os.path.join(run_dir, "evidence-receipt.json")
    assert os.path.exists(evidence_path)
    receipt = json.loads(open(evidence_path, encoding="utf-8").read())
    assert receipt["schema"] == "simplicio.evidence-receipt/v1"
    assert receipt["status"] == "UNVERIFIED"
    assert receipt["summary"]["criteria_total"] == 1
    assert receipt["summary"]["scenario_total"] == 1
    assert receipt["summary"]["rule_total"] == 1
    assert receipt["run"]["task_contract_hash"]
    assert receipt["criteria"][0]["id"] == "AC1"
    assert receipt["operator"]["coverage_ok"] is True

    loop_dir = repo / ".simplicio/orchestrator" / "loop"
    loop_dir.mkdir(parents=True, exist_ok=True)
    challenge = loop_dir / "watcher_challenge.json"
    challenge.write_text(json.dumps({"challenge": "abc", "goal_fp": "", "written_at": "2026-07-10T00:00:00Z"}),
                         encoding="utf-8")
    (loop_dir / "anchor.json").write_text(json.dumps({"criteria": [{"id": "AC1", "status": "done"}]}),
                                          encoding="utf-8")
    r = _run(
        [sys.executable, WATCHER, "verify"],
        str(repo),
        env={"SIMPLICIO_RUN_DIR": run_dir, "SIMPLICIO_LOOP_REPO": str(repo)},
    )
    assert r.returncode == 0
    state = json.loads((loop_dir / "watcher_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "UNVERIFIED"
    assert state["match"] is False
    assert state["criteria_results"][0]["id"] == "AC1"
    assert state["criteria_results"][0]["match"] is False


def test_evidence_receipt_flags_uncovered_manual_diff(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init"], str(repo))
    _run(["git", "config", "user.email", "test@example.com"], str(repo))
    _run(["git", "config", "user.name", "Test User"], str(repo))
    (repo / "src").mkdir()
    tracked = repo / "src" / "app.py"
    tracked.write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    _run(["git", "add", "."], str(repo))
    _run(["git", "commit", "-m", "init"], str(repo))

    run_dir = repo / ".simplicio/orchestrator" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(json.dumps({
        "schema": "simplicio.run-manifest/v1",
        "run_id": "r1",
        "delivery_target": "verified"
    }), encoding="utf-8")
    (run_dir / "task-contract.json").write_text(json.dumps({
        "schema": "simplicio.task-contract-collection/v1",
        "collection_hash": "abc",
        "tasks": [{"scenarios": [{"id": "S1", "title": "scenario", "rule_refs": ["RN01"]}], "rules": [{"id": "RN01"}]}]
    }), encoding="utf-8")
    (run_dir / "mapper-context.json").write_text(json.dumps({"handoff": {"stdout": {"context_pack": {"files": []}}}}), encoding="utf-8")
    (run_dir / "plan.json").write_text(json.dumps({}), encoding="utf-8")
    (run_dir / "operator-receipt.json").write_text(json.dumps({
        "schema": "simplicio.operator-receipt/v0",
        "mode": "execute",
        "execution_state": "applied",
        "target": "src/app.py",
        "changed_paths": ["src/app.py"],
    }), encoding="utf-8")

    extra = repo / "manual_extra.txt"
    extra.write_text("manual mutation\n", encoding="utf-8")
    monkeypatch.setattr(evidence_mod, "_changed_paths", lambda root: ["manual_extra.txt"])
    receipt = evidence_mod.build_evidence_receipt(str(run_dir))
    assert receipt["operator"]["coverage_ok"] is False
    assert "manual_extra.txt" in receipt["operator"]["uncovered_paths"]


def test_watcher_rejects_uncovered_manual_diff_from_evidence(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    loop_dir = repo / ".simplicio/orchestrator" / "loop"
    loop_dir.mkdir(parents=True, exist_ok=True)
    run_dir = repo / ".simplicio/orchestrator" / "runs" / "demo"
    run_dir.mkdir(parents=True)
    (loop_dir / "watcher_challenge.json").write_text(json.dumps({
        "challenge": "abc", "goal_fp": "", "written_at": "2026-07-10T00:00:00Z"
    }), encoding="utf-8")
    (loop_dir / "anchor.json").write_text(json.dumps({"criteria": [{"id": "AC1", "status": "done"}]}),
                                          encoding="utf-8")
    (run_dir / "evidence-receipt.json").write_text(json.dumps({
        "schema": "simplicio.evidence-receipt/v1",
        "run_id": "demo",
        "status": "VERIFIED",
        "run": {"task_contract_hash": "hash1", "plan_hash": "hash2", "commit_sha": "", "diff_hash": ""},
        "operator": {"coverage_ok": False, "uncovered_paths": ["README.manual.md"]},
        "criteria": [{"id": "AC1", "verification_state": "verified", "proof_refs": ["proof-1"]}],
        "summary": {"criteria_total": 1, "criteria_verified": 1, "scenario_total": 1,
                    "scenario_verified": 1, "rule_total": 0, "rule_verified": 0},
        "checks": [],
    }), encoding="utf-8")
    r = _run(
        [sys.executable, WATCHER, "verify"],
        str(repo),
        env={"SIMPLICIO_RUN_DIR": str(run_dir), "SIMPLICIO_LOOP_REPO": str(repo)},
    )
    assert r.returncode == 0
    state = json.loads((loop_dir / "watcher_state.json").read_text(encoding="utf-8"))
    assert state["match"] is False
    assert "uncovered diff outside operator receipt" in state["reported"]


def test_watcher_rejects_verified_ac_without_proof_reference(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    loop_dir = repo / ".simplicio/orchestrator" / "loop"
    loop_dir.mkdir(parents=True)
    run_dir = repo / ".simplicio/orchestrator" / "runs" / "demo"
    run_dir.mkdir(parents=True)
    (loop_dir / "watcher_challenge.json").write_text(json.dumps({
        "challenge": "proof-required", "goal_fp": "", "written_at": "2026-07-10T00:00:00Z"
    }), encoding="utf-8")
    (loop_dir / "anchor.json").write_text(json.dumps({
        "criteria": [{"id": "AC1", "status": "done"}]
    }), encoding="utf-8")
    (run_dir / "evidence-receipt.json").write_text(json.dumps({
        "schema": "simplicio.evidence-receipt/v1", "run_id": "demo", "status": "VERIFIED",
        "run": {"task_contract_hash": "hash1", "plan_hash": "hash2", "commit_sha": "", "diff_hash": ""},
        "criteria": [{"id": "AC1", "verification_state": "verified"}],
        "summary": {"criteria_total": 1, "criteria_verified": 1, "scenario_total": 1,
                    "scenario_verified": 1, "rule_total": 0, "rule_verified": 0}, "checks": [],
    }), encoding="utf-8")
    r = _run(
        [sys.executable, WATCHER, "verify"],
        str(repo),
        env={"SIMPLICIO_RUN_DIR": str(run_dir), "SIMPLICIO_LOOP_REPO": str(repo)},
    )
    assert r.returncode == 0
    state = json.loads((loop_dir / "watcher_state.json").read_text(encoding="utf-8"))
    assert state["match"] is False
    assert state["criteria_results"][0]["match"] is False


def test_evidence_receipt_cli_selftest():
    r = _run([sys.executable, EVIDENCE, "selftest"], REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS evidence-receipt" in r.stdout


def test_execute_receipt_checks_redacts_secret_output_and_allows_safe_argv():
    def fake_run(argv, shell, cwd, capture_output, text, timeout):
        assert shell is False
        assert argv[:2] == ["python", "-c"]
        return SimpleNamespace(returncode=0, stdout="token=ghp_abcdefghijklmnopqrstuvwxyz1234567890\n", stderr="")

    original_run = evidence_mod.subprocess.run
    evidence_mod.subprocess.run = fake_run
    try:
        result = execute_receipt_checks({
            "checks": [{
                "id": "safe",
                "argv": ["python", "-c", "print('token=ghp_abcdefghijklmnopqrstuvwxyz1234567890')"],
                "expected_exit_code": 0,
            }]
        })
    finally:
        evidence_mod.subprocess.run = original_run
    assert result["all_passed"] is True
    item = result["results"][0]
    assert item["status"] == "MEASURED"
    assert item["policy"] == "allowed"
    assert "ghp_" not in item["stdout"]
    assert "[REDACTED_SECRET]" in item["stdout"]


def test_execute_receipt_checks_blocks_unsafe_shell_syntax():
    result = execute_receipt_checks({
        "checks": [{
            "id": "unsafe",
            "command": "python -c \"print(1)\" && whoami",
            "expected_exit_code": 0,
        }]
    })
    assert result["all_passed"] is False
    item = result["results"][0]
    assert item["status"] == "UNVERIFIED"
    assert item["policy"] == "blocked"
    assert "unsafe shell syntax" in item["reason"]


def test_redact_sensitive_text_rewrites_generic_secret_assignments():
    redacted = redact_sensitive_text('api_key="supersecretvalue123" password=abcdef123456')
    assert "supersecretvalue123" not in redacted
    assert "abcdef123456" not in redacted
    assert "[REDACTED" in redacted


def test_watcher_without_anchor_or_criteria_never_returns_ready(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    loop_dir = repo / ".simplicio/orchestrator" / "loop"
    loop_dir.mkdir(parents=True, exist_ok=True)
    (loop_dir / "watcher_challenge.json").write_text(json.dumps({
        "challenge": "abc", "goal_fp": "", "written_at": "2026-07-10T00:00:00Z"
    }), encoding="utf-8")
    r = _run([sys.executable, WATCHER, "verify"], str(repo), env={"SIMPLICIO_LOOP_REPO": str(repo)})
    assert r.returncode == 0
    state = json.loads((loop_dir / "watcher_state.json").read_text(encoding="utf-8"))
    assert state["match"] is False
    assert state["status"] == "UNVERIFIED"
    assert "anchor missing" in state["reported"]


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_evidence_receipt")
