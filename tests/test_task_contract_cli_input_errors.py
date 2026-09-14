"""`simplicio-loop task preview|validate` must fail closed on unusable input.

Both commands load a *compiled* contract, but neither guards the load. Passing a
markdown source (the natural mistake) or a missing path crashed with a raw
traceback and `json.decoder.JSONDecodeError`, which is not a usable
fail-closed contract for a public CLI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = [sys.executable, "-m", "simplicio_loop.cli"]

SAMPLE = """Sistema: Simplicio
Funcionalidade: TASK-CHECKERS-001 — criação
Tipo: criação

COMO jogador
QUERO um jogo de dama em site/checkers.html
PARA jogar uma partida.

1. Critérios de Aceite

Cenário 1: criação funcional
  Dado um diretório vazio
  Quando a tarefa de criação for aplicada
  Então o tabuleiro é visível [AC01]

2. Regras de Negócio

RN01 – O jogo deve impedir movimentos inválidos.
"""


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        CLI + list(args), cwd=REPO, capture_output=True, text=True, timeout=180
    )


def _write(tmp_path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_task_preview_fails_closed_when_the_contract_is_not_json(tmp_path) -> None:
    source = _write(tmp_path, "tasks.md", SAMPLE)

    result = _run("task", "preview", source)

    assert result.returncode == 2, result
    assert "Traceback" not in result.stderr
    combined = result.stdout + result.stderr
    assert "JSON" in combined


def test_task_validate_fails_closed_when_the_contract_is_not_json(tmp_path) -> None:
    source = _write(tmp_path, "tasks.md", SAMPLE)

    result = _run("task", "validate", source)

    assert result.returncode == 2, result
    assert "Traceback" not in result.stderr
    combined = result.stdout + result.stderr
    assert "JSON" in combined


def test_task_preview_fails_closed_when_the_contract_is_missing(tmp_path) -> None:
    missing = str(tmp_path / "absent.json")

    result = _run("task", "preview", missing)

    assert result.returncode == 2, result
    assert "Traceback" not in result.stderr


def test_task_validate_fails_closed_when_the_contract_is_missing(tmp_path) -> None:
    missing = str(tmp_path / "absent.json")

    result = _run("task", "validate", missing)

    assert result.returncode == 2, result
    assert "Traceback" not in result.stderr


def test_task_preview_and_validate_still_accept_a_compiled_contract(tmp_path) -> None:
    source = _write(tmp_path, "tasks.md", SAMPLE)
    compiled = str(tmp_path / "contract.json")
    compiled_process = _run("task", "compile", "--input", source, "--out", compiled)
    assert compiled_process.returncode == 0, compiled_process
    assert json.loads(open(compiled, encoding="utf-8").read())["schema"].endswith(
        "/v1.collection"
    )

    preview = _run("task", "preview", compiled)
    assert preview.returncode == 0, preview
    assert "[task 1]" in preview.stdout

    validate = _run("task", "validate", compiled)
    assert validate.returncode in {0, 2}, validate
    assert json.loads(validate.stdout)["ok"] in {True, False}
