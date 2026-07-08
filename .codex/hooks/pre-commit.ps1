# Hook pre-commit do Claude Code (PowerShell sibling de pre-commit.sh).
# Roda a suite de testes em modo silencioso e BLOQUEIA o commit se vermelho.
# Mensagens em pt-BR para feedback rapido. CI roda o set completo (lint + e2e);
# aqui o foco e evitar commit obviamente quebrado.

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
        Write-Host '[pre-commit] Arquivos Python staged detectados -> pytest -q -x'
        & pytest -q -x
        if ($LASTEXITCODE -ne 0) { exit 1 }
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
