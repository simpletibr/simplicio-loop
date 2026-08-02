from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from simplicio import codex_wrapper


def _runtime_fixture(path: Path, *, receipt: bool, exit_code: int = 0) -> Path:
    result = {
        "schema": "simplicio.io/v1",
        "status": "passed",
    }
    if receipt:
        result["receipt_id"] = "subprocess-fixture-receipt"
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        f"result = {result!r}\n"
        "result['argv'] = sys.argv[1:]\n"
        "result['policy'] = os.environ.get('SIMPLICIO_CODEX_POLICY_JSON')\n"
        "result['codex_argv'] = os.environ.get('SIMPLICIO_CODEX_ARGV_JSON')\n"
        "result['route'] = os.environ.get('SIMPLICIO_CODEX_ROUTE')\n"
        "result['hook_guard'] = os.environ.get('SIMPLICIO_HOOK_GUARD')\n"
        "print(json.dumps(result, sort_keys=True))\n"
        f"raise SystemExit({exit_code})\n",
        encoding="utf-8",
        newline="\n",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _environment(runtime: Path) -> dict[str, str]:
    repository = str(Path(__file__).resolve().parents[2])
    existing = os.environ.get("PYTHONPATH")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (repository, existing)))
    environment["SIMPLICIO_RUNTIME_COMMAND"] = str(runtime)
    environment["SIMPLICIO_SKIP_AUTO_INIT"] = "1"
    environment.pop("SIMPLICIO_HOOK_GUARD", None)
    return environment


def _run_hook(tmp_path: Path, runtime: Path, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "simplicio.codex_hooks",
        "--route",
        "runtime",
        "--marker",
        codex_wrapper.HOOK_MARKER,
    ]
    process = subprocess.Popen(
        command,
        cwd=tmp_path,
        env=_environment(runtime),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = process.communicate(json.dumps(payload))
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def test_installed_wrapper_and_hook_route_subprocess_preserves_policy(tmp_path):
    codex_home = tmp_path / "codex"
    wrapper_path = tmp_path / "bin" / "codex"
    report = codex_wrapper.install_codex_integration(codex_home, wrapper_path=wrapper_path)
    runtime = _runtime_fixture(tmp_path / "runtime-receipt.py", receipt=True)

    installed_hooks = json.loads(report.hooks_path.read_text(encoding="utf-8"))
    commands = [
        hook["command"] for entry in installed_hooks["hooks"]["UserPromptSubmit"] for hook in entry["hooks"]
    ]
    assert any(codex_wrapper.HOOK_MARKER in command for command in commands)

    prompt = "fix settings.json"
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": prompt,
        "cwd": str(tmp_path),
        "codex_argv": ["exec", prompt],
        "sandbox_mode": "workspace-write",
        "approval_policy": "on-request",
        "permission_mode": "acceptEdits",
    }
    hook_result = _run_hook(tmp_path, runtime, payload)

    assert hook_result.returncode == 0
    response = json.loads(hook_result.stdout)
    assert response["decision"] == "block"
    receipt = json.loads(response["hookSpecificOutput"]["additionalContext"])
    assert receipt["status"] == "passed"
    assert receipt["argv"] == ["run", prompt, "--repo", str(tmp_path), "--evidence", "--json"]
    assert json.loads(receipt["policy"]) == {
        "approval_policy": "on-request",
        "bypass_requested": False,
        "permission_mode": "acceptEdits",
        "sandbox_mode": "workspace-write",
    }
    assert json.loads(receipt["codex_argv"]) == [
        "exec",
        prompt,
        "--sandbox",
        "workspace-write",
        "--ask-for-approval",
        "on-request",
        "--permission-mode",
        "acceptEdits",
    ]
    assert receipt["route"] == "runtime"
    assert receipt["hook_guard"] == "1"

    wrapper_result = subprocess.run(
        [
            sys.executable,
            str(wrapper_path),
            "exec",
            "--sandbox",
            "workspace-write",
            "--ask-for-approval",
            "on-request",
            prompt,
        ],
        cwd=tmp_path,
        env={**_environment(runtime), "SIMPLICIO_CODEX_ROUTE": "runtime"},
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )
    assert wrapper_result.returncode == 0


def test_subprocess_hook_blocks_runtime_output_without_receipt(tmp_path):
    runtime = _runtime_fixture(tmp_path / "runtime-no-receipt.py", receipt=False)
    result = _run_hook(
        tmp_path,
        runtime,
        {"hook_event_name": "UserPromptSubmit", "prompt": "fix app.py"},
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    assert response["decision"] == "block"
    assert "valid evidence receipt" in response["reason"]


def test_subprocess_hook_blocks_nonzero_runtime(tmp_path):
    runtime = _runtime_fixture(tmp_path / "runtime-failure.py", receipt=True, exit_code=3)
    result = _run_hook(
        tmp_path,
        runtime,
        {"hook_event_name": "UserPromptSubmit", "prompt": "fix app.py"},
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    assert response["decision"] == "block"
    assert "Runtime rejected the task" in response["reason"]


def test_codex_cli_install_and_uninstall_are_reversible(tmp_path, capsys):
    codex_home = tmp_path / "codex"
    wrapper_path = tmp_path / "bin" / "codex"

    assert (
        codex_wrapper.main(
            [
                "--install-codex",
                str(codex_home),
                "--wrapper-path",
                str(wrapper_path),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert Path(report["wrapper"]) == wrapper_path.resolve()
    assert Path(report["hooks"]) == (codex_home / "hooks.json").resolve()
    assert wrapper_path.is_file()

    assert (
        codex_wrapper.main(
            [
                "--uninstall-codex",
                str(codex_home),
                "--wrapper-path",
                str(wrapper_path),
            ]
        )
        == 0
    )
    assert not wrapper_path.exists()


def test_codex_cli_run_forwards_remainder(monkeypatch):
    observed = {}

    def fake_run(argv):
        observed["argv"] = argv
        return 0

    monkeypatch.setattr(codex_wrapper, "run_wrapped", fake_run)
    assert codex_wrapper.main(["--run", "--", "exec", "what is Python?"]) == 0
    assert observed["argv"] == ["exec", "what is Python?"]
