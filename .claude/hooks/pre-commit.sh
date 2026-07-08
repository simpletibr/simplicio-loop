#!/usr/bin/env bash
# Hook pre-commit do Claude Code.
# Roda a suite de testes em modo silencioso e BLOQUEIA o commit se vermelho.
# Mensagens em pt-BR para feedback rápido. CI roda o set completo (lint + e2e);
# aqui o foco é evitar commit obviamente quebrado.

set -euo pipefail

echo "[pre-commit] Rodando gates locais antes do commit..."

STAGED_PY="$(git diff --cached --name-only --diff-filter=ACMR | grep -E '\.py$' || true)"
if [[ -n "$STAGED_PY" ]]; then
  echo "[pre-commit] Arquivos Python staged detectados -> ruff check ."
  ruff check .
  if [[ "${SKIP_PRECOMMIT_TESTS:-}" != "1" ]]; then
    echo "[pre-commit] Arquivos Python staged detectados -> pytest -q -x"
    pytest -q -x
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
