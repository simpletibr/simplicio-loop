#!/usr/bin/env bash
# Hook pre-commit do Claude Code.
# Roda a suite de testes em modo silencioso e BLOQUEIA o commit se vermelho.
# Mensagens em pt-BR para feedback rápido.
#
# NOTA (issue #246, 2026-07): .github/workflows/ foi removido inteiramente em
# d7ff8c9 (billing lockout + centralizacao de CI/CD em simplicio-runtime), o
# que também apagou o job "coverage" (85% global / 90% critico) que #205
# tinha acabado de ligar em CI horas antes. Ate a CI centralizada voltar, ESTE
# hook e o unico gate mecanizado que roda de verdade -- por isso o piso de
# coverage do pyproject.toml (`[tool.coverage.report].fail_under = 85`) e
# aplicado aqui via `--cov`/`--cov-fail-under`, nao mais so em CI.
set -euo pipefail

echo "[pre-commit] Rodando gates locais antes do commit..."

STAGED_PY="$(git diff --cached --name-only --diff-filter=ACMR | grep -E '\.py$' || true)"
if [[ -n "$STAGED_PY" ]]; then
  echo "[pre-commit] Arquivos Python staged detectados -> ruff check ."
  ruff check .
  if [[ "${SKIP_PRECOMMIT_TESTS:-}" != "1" ]]; then
    if python3 -c "import pytest_cov" >/dev/null 2>&1; then
      echo "[pre-commit] Arquivos Python staged detectados -> pytest -q --cov=simplicio --cov-fail-under=85 (#246)"
      pytest -q --cov=simplicio --cov-report=term-missing --cov-fail-under=85
    else
      echo "[pre-commit] pytest-cov ausente (pip install -e '.[test]') -> pulando o piso de coverage, rodando so pytest -q -x"
      pytest -q -x
    fi
  else
    echo "[pre-commit] SKIP_PRECOMMIT_TESTS=1 -> pulando pytest local."
  fi
fi

if [[ -f "package.json" ]]; then
  if grep -q '"test:cli"\s*:' package.json; then
    npm run test:cli --silent
  elif grep -q '"test"\s*:' package.json; then
    npm test --silent
  fi
fi

echo "[pre-commit] Testes verdes. Seguindo com o commit."
exit 0
