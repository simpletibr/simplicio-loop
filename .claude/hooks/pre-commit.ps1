# Hook pre-commit do Claude Code (PowerShell sibling de pre-commit.sh).
# Roda a suite de testes em modo silencioso e BLOQUEIA o commit se vermelho.
# Mensagens em pt-BR para feedback rapido.
#
# NOTA (issue #246, 2026-07): .github/workflows/ foi removido inteiramente em
# d7ff8c9 (billing lockout + centralizacao de CI/CD em simplicio-runtime), o
# que tambem apagou o job "coverage" (85% global / 90% critico) que #205
# tinha acabado de ligar em CI horas antes. Ate a CI centralizada voltar,
# ESTE hook e o unico gate mecanizado que roda de verdade -- por isso o piso
# de coverage do pyproject.toml (`[tool.coverage.report].fail_under = 85`) e
# aplicado aqui via `--cov`/`--cov-fail-under`, nao mais so em CI.

[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'

Write-Host '[pre-commit] Rodando gates locais antes do commit...'

$stagedPy = git diff --cached --name-only --diff-filter=ACMR | Where-Object { $_ -match '\.py$' }
if ($stagedPy) {
    Write-Host '[pre-commit] Arquivos Python staged detectados -> ruff check .'
    & ruff check .
    if ($LASTEXITCODE -ne 0) { exit 1 }

    if ($env:SKIP_PRECOMMIT_TESTS -ne '1') {
        & python3 -c "import pytest_cov" *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host '[pre-commit] Arquivos Python staged detectados -> pytest -q --cov=simplicio --cov-fail-under=85 (#246)'
            & pytest -q --cov=simplicio --cov-report=term-missing --cov-fail-under=85
            if ($LASTEXITCODE -ne 0) { exit 1 }
        } else {
            Write-Host "[pre-commit] pytest-cov ausente (pip install -e '.[test]') -> pulando o piso de coverage, rodando so pytest -q -x"
            & pytest -q -x
            if ($LASTEXITCODE -ne 0) { exit 1 }
        }
    } else {
        Write-Host '[pre-commit] SKIP_PRECOMMIT_TESTS=1 -> pulando pytest local.'
    }
}

if (Test-Path -LiteralPath 'package.json' -PathType Leaf) {
    $npmCmd = if ($IsWindows) { 'npm.cmd' } else { 'npm' }
    $packageJson = Get-Content -LiteralPath 'package.json' -Raw
    if ($packageJson -match '"test:cli"\s*:') {
        & $npmCmd run test:cli --silent
        if ($LASTEXITCODE -ne 0) { exit 1 }
    } elseif ($packageJson -match '"test"\s*:') {
        & $npmCmd test --silent
        if ($LASTEXITCODE -ne 0) { exit 1 }
    }
}

Write-Host '[pre-commit] Testes verdes. Seguindo com o commit.'
exit 0
