import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "task_contract.py")
CLI = [sys.executable, "-m", "simplicio_loop.cli"]

SAMPLE = """Sistema: PLANES
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

3. Requisitos Não Funcionais

Nenhum requisito não-funcional identificado na entrada — validar com o time.
"""


def _run(cmd, cwd):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=30,
                          stdin=subprocess.DEVNULL)


def test_script_compile_validate_preview_roundtrip(tmp_path):
    task = tmp_path / "task.md"
    out = tmp_path / "contract.json"
    task.write_text(SAMPLE, encoding="utf-8")
    c = _run([sys.executable, SCRIPT, "compile", "--input", str(task), "--out", str(out)], REPO)
    assert c.returncode == 0, c.stdout + c.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["task_count"] == 1
    v = _run([sys.executable, SCRIPT, "validate", str(out)], REPO)
    assert v.returncode == 0, v.stdout + v.stderr
    p = _run([sys.executable, SCRIPT, "preview", str(out)], REPO)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "scenarios: 1" in p.stdout


def test_package_cli_exposes_task_subcommand(tmp_path):
    task = tmp_path / "task.md"
    out = tmp_path / "contract.json"
    task.write_text(SAMPLE, encoding="utf-8")
    r = _run(CLI + ["task", "compile", "--input", str(task), "--out", str(out)], REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["tasks"][0]["identity"]["system"] == "PLANES"
    assert payload["tasks"][0]["questions"]


def test_package_cli_plan_writes_default_contract_and_preview(tmp_path):
    task = tmp_path / "task.md"
    task.write_text(SAMPLE, encoding="utf-8")
    out = tmp_path / ".simplicio-loop/orchestrator" / "task-contract.json"
    r = _run(CLI + ["plan", "--task", str(task), "--out", str(out)], REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.exists()
    assert "scenarios: 1" in r.stdout


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_task_contract_cli")
