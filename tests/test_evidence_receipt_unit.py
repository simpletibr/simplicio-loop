import json
import os
import subprocess
import sys
from pathlib import Path
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
    # Two-phase flow: `prepare` arms the run (no mutation attempted yet), the
    # host then writes the edit-plan (a host-authored, already-frozen plan --
    # `schema` set skips the dev-cli compile subprocess entirely, matching
    # what a host that already has a compiled plan would hand the loop), and
    # `wave` dispatches it. The single-shot deprecated `run --task` command
    # now redirects straight into this same arm+wave path (see
    # `_redirect_run_to_wave` in cli_impl.py), so exercising `prepare` + `wave`
    # directly is the current, non-deprecated shape of what this test proves:
    # the evidence receipt is built from the run, and the watcher reads it.
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
    common_env = {
        "SIMPLICIO_LOOP_FAKE_OPERATOR_JSON": fake_operator,
        "SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON": fake_mapper_preflight,
        "SIMPLICIO_LOOP_FAKE_DEVCLI_PREFLIGHT_JSON": fake_devcli_preflight,
        # Do not inherit a host-installed operator: this test proves the
        # explicit dry-run/no-mutation boundary and must remain UNVERIFIED
        # everywhere.
        "PATH": str(operator_bin) + os.pathsep + os.defpath,
        # Mandatory mutation-authority is a separate, later gate (host-supplied
        # plan.json) than the dry-run proposal this test exercises -- opt out
        # of it here the same way other fixtures in this suite do.
        "SIMPLICIO_REQUIRE_MUTATION_AUTHORITY": "0",
    }

    # Phase 1: arm the run. No mutation is attempted at prepare time -- the
    # dry-run operator preflight above only proves dev-cli accepts a plan.
    prepared = _run(CLI + ["prepare", "--task", str(task), "--repo", str(repo),
                           "--delivery", "verified", "--max-iterations", "9"],
                     REPO, env=common_env)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    prepared_payload = json.loads(prepared.stdout)
    assert prepared_payload["status"] == "prepared", prepared_payload
    run_id = prepared_payload["run_id"]
    run_dir = prepared_payload["run_dir"]

    # Phase 2: the host writes the edit plan. A plan that already carries
    # `schema` is a frozen/compiled plan (see `_compile_minimal_host_plan`)
    # and is applied as-is -- no dev-cli compile subprocess needed, so this
    # stays hermetic under the restricted PATH above.
    edit_plan = {
        "schema": "simplicio.dev-cli.edit-plan/v1",
        "operations": [{"path": "src/app.py", "op": "noop"}],
    }
    (Path(run_dir) / "edit-plan-1.json").write_text(json.dumps(edit_plan), encoding="utf-8")

    # Phase 3: dispatch the wave. `SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON`
    # substitutes the real dev-cli `--apply` subprocess the same way
    # `SIMPLICIO_LOOP_FAKE_OPERATOR_JSON` substituted its dry-run preflight
    # above -- no file is actually mutated, so the run stays UNVERIFIED.
    fake_operator_exec = json.dumps({
        "returncode": 0,
        "stdout": {"kind": "operator-apply", "ok": True},
        "stderr": "",
        "write_files": {},
    })
    wave_env = dict(common_env)
    wave_env["SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON"] = fake_operator_exec
    started = _run(CLI + ["wave", run_id, "--repo", str(repo)], REPO, env=wave_env)
    assert started.returncode in (0, 2), started.stdout + started.stderr
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

    loop_dir = repo / ".simplicio-loop/orchestrator" / "loop"
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

    run_dir = repo / ".simplicio-loop/orchestrator" / "runs" / "r1"
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
    loop_dir = repo / ".simplicio-loop/orchestrator" / "loop"
    loop_dir.mkdir(parents=True, exist_ok=True)
    run_dir = repo / ".simplicio-loop/orchestrator" / "runs" / "demo"
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
    loop_dir = repo / ".simplicio-loop/orchestrator" / "loop"
    loop_dir.mkdir(parents=True)
    run_dir = repo / ".simplicio-loop/orchestrator" / "runs" / "demo"
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
    loop_dir = repo / ".simplicio-loop/orchestrator" / "loop"
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


def _git_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=tmp_path, check=True,
    )
    return tmp_path


def test_changed_paths_ignores_coverage_tool_byproducts(tmp_path):
    """BUG 2 regression (multiprocess/verify chain): the diff-coverage check
    (`_operator_diff_coverage`) uses this SAME ``_changed_paths`` to find
    what changed since the operator ran. A task's own Coverage verifier lane
    rewrites `.coverage` at the repo root as a byproduct of running -- not
    an operator receipt is ever expected to list it -- so it must not count,
    the same way __pycache__/.pyc already do not.
    """
    repo = _git_repo(tmp_path)
    before = evidence_mod._changed_paths(repo)
    (repo / ".coverage").write_bytes(b"coverage-data")
    (repo / ".coverage.host.123.abc").write_bytes(b"parallel-mode-data")
    (repo / "htmlcov").mkdir()
    (repo / "htmlcov" / "index.html").write_text("<html></html>", encoding="utf-8")
    assert evidence_mod._changed_paths(repo) == before


def test_changed_paths_still_detects_a_real_new_file_alongside_coverage_byproducts(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / ".coverage").write_bytes(b"coverage-data")
    (repo / "new_source.py").write_text("y = 2\n", encoding="utf-8")
    assert "new_source.py" in evidence_mod._changed_paths(repo)
    assert ".coverage" not in evidence_mod._changed_paths(repo)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_evidence_receipt")


def test_git_meta_diff_hash_ignores_verifier_byproducts(tmp_path):
    """The evidence receipt is sealed before the quality lanes run and the
    watcher re-hashes after them; bytecode, pytest/mypy/ruff caches and
    coverage data those lanes write must not change the run-diff fingerprint,
    or every `wave` blocks with "run diff differs from watcher worktree"."""
    run = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (tmp_path / "app.py").write_text("x = 1\n")
    run("add", "-A")
    run("commit", "-qm", "init")
    (tmp_path / "app.py").write_text("x = 2\n")
    (tmp_path / "new.py").write_text("y = 1\n")
    before = evidence_mod._git_meta(tmp_path)["diff_hash"]

    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "app.cpython-311.pyc").write_bytes(b"\0bytecode")
    (tmp_path / "pkg" / "__pycache__").mkdir(parents=True)
    (tmp_path / "pkg" / "__pycache__" / "m.pyc").write_bytes(b"\0")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "README.md").write_text("cache\n")
    (tmp_path / ".coverage").write_bytes(b"sqlite")
    (tmp_path / ".coverage.host.1.abc").write_bytes(b"sqlite")
    (tmp_path / "htmlcov").mkdir()
    (tmp_path / "htmlcov" / "index.html").write_text("<html/>")

    assert evidence_mod._git_meta(tmp_path)["diff_hash"] == before
    (tmp_path / "new.py").write_text("y = 2\n")
    assert evidence_mod._git_meta(tmp_path)["diff_hash"] != before
