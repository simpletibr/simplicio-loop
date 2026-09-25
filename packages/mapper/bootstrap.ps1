<#
.SYNOPSIS
  LLM Project Mapper installer/upgrader (Windows native / PowerShell 5.1+ / pwsh 7+).

.DESCRIPTION
  Mirror of bootstrap.sh:
    1. Auto-detects PRODUCT_NAME (cwd basename), STACK (Node, .NET, Python,
       Go, Rust, Flutter, PHP/Laravel, Ruby, Elixir, Kotlin/Java).
       Auto-detects PROJECT_MODE from workspace signals at cwd:
         - monorepo signal (pnpm-workspace.yaml, lerna.json, nx.json,
           turbo.json, rush.json, package.json with "workspaces", or >=2 of
           apps/ packages/ services/ subfolders with manifests) -> "monorepo"
         - otherwise -> "root" (single project at cwd)
       INIT.md infers team/domain/vision/personas from the codebase (no human
       prompts).
    2. Asks only TWO questions:
        - Append recommended ignore entries to .gitignore? (y/N)
        - Which CLI/LLM should run INIT.md?
    3. Substitutes <PRODUCT_NAME>/<STACK> ONLY inside
       starter-managed paths (.specs/, .agents/, .skills/, .claude/,
       .codex/, .github/copilot*, .github/workflows/{ci,dod}.yml,
       plus root AGENTS.md/CLAUDE.md/INIT.md/README*.md ONLY if those
       files actually contain a placeholder).
    4. NEVER overwrites pre-existing user files (.razor, .cs, .ts, .py,
       package.json, README.md, AGENTS.md, CLAUDE.md, INIT.md, .gitignore).
       Existing instruction files are flagged in .starter-meta.json so
       INIT.md can read them and improve in place (essence preserved).
    5. Hands off to the chosen CLI/LLM to execute INIT.md.

.EXAMPLE
  PS> .\bootstrap.ps1
  PS> .\bootstrap.ps1 -NonInteractive -Cli claude -AppendGitignore yes
  PS> .\bootstrap.ps1 -NonInteractive -Cli codex -AppendGitignore yes -McpEdge
#>
[CmdletBinding()]
param(
  [switch]$NonInteractive,
  [string]$Cli              = "",
  [ValidateSet("yes","no","")]
  [string]$AppendGitignore  = "",
  [switch]$McpEdge
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# auto-detect stack
# ---------------------------------------------------------------------------
function Detect-Stack {
  if (Test-Path "package.json") {
    $pkg = Get-Content "package.json" -Raw
    if     ($pkg -match '"next"')                      { return "next-ts" }
    elseif ($pkg -match '"react"')                     { return "react-ts" }
    elseif ($pkg -match '"vue"')                       { return "vue-ts" }
    elseif ($pkg -match '"@nestjs/core"|"nestjs"')     { return "nestjs" }
    elseif ($pkg -match '"express"')                   { return "node-express" }
    else                                               { return "node-ts" }
  }
  if (Get-ChildItem -Filter "*.csproj" -File -ErrorAction SilentlyContinue) { return "dotnet" }
  if (Get-ChildItem -Filter "*.sln"    -File -ErrorAction SilentlyContinue) { return "dotnet" }
  if ((Test-Path "pyproject.toml") -or (Test-Path "requirements.txt")) {
    $py = ""
    if (Test-Path "pyproject.toml")    { $py += (Get-Content "pyproject.toml" -Raw) }
    if (Test-Path "requirements.txt")  { $py += (Get-Content "requirements.txt" -Raw) }
    if     ($py -match '(?i)django')  { return "python-django" }
    elseif ($py -match '(?i)fastapi') { return "python-fastapi" }
    elseif ($py -match '(?i)flask')   { return "python-flask" }
    else                              { return "python" }
  }
  if (Test-Path "go.mod")           { return "go" }
  if (Test-Path "Cargo.toml")       { return "rust" }
  if (Test-Path "pubspec.yaml")     { return "flutter" }
  if (Test-Path "composer.json") {
    if ((Get-Content "composer.json" -Raw) -match "laravel/framework") { return "laravel" }
    return "php"
  }
  if (Test-Path "Gemfile")          { return "ruby" }
  if (Test-Path "mix.exs")          { return "elixir" }
  if (Test-Path "build.gradle.kts") { return "kotlin-gradle" }
  if (Test-Path "build.gradle")     { return "java-gradle" }
  if (Test-Path "pom.xml")          { return "java-maven" }
  return "unknown"
}

# ---------------------------------------------------------------------------
# project mode (workspace signal detection — no projects/ folder needed)
# ---------------------------------------------------------------------------
function Has-WorkspaceSignal {
  if (Test-Path "pnpm-workspace.yaml") { return $true }
  if (Test-Path "lerna.json")          { return $true }
  if (Test-Path "nx.json")             { return $true }
  if (Test-Path "turbo.json")          { return $true }
  if (Test-Path "rush.json")           { return $true }
  if (Test-Path "package.json") {
    if ((Get-Content "package.json" -Raw) -match '"workspaces"') { return $true }
  }
  return $false
}

function List-MonorepoDirs {
  $dirs = @()
  foreach ($parent in @("apps","packages","services","projects")) {
    if (-not (Test-Path $parent -PathType Container)) { continue }
    Get-ChildItem -Path $parent -Directory -ErrorAction SilentlyContinue | Where-Object { -not $_.Name.StartsWith(".") } | Sort-Object Name | ForEach-Object {
      $d = $_.FullName
      $manifests = @("package.json","pyproject.toml","go.mod","Cargo.toml","pubspec.yaml","composer.json","Gemfile","pom.xml","build.gradle","build.gradle.kts")
      $hasManifest = $false
      foreach ($m in $manifests) {
        if (Test-Path (Join-Path $d $m)) { $hasManifest = $true; break }
      }
      if (-not $hasManifest) {
        if (Get-ChildItem -Path $d -Filter "*.csproj" -File -ErrorAction SilentlyContinue) { $hasManifest = $true }
      }
      if ($hasManifest) { $dirs += (Resolve-Path -Relative $d) }
    }
  }
  return $dirs
}

function Detect-ProjectMode {
  if (Has-WorkspaceSignal) { return "monorepo" }
  # Fallback: require >=2 sibling subfolders with manifests to avoid
  # false-positives where a single vendored library lives under apps/.
  $dirs = List-MonorepoDirs
  if ($dirs.Count -ge 2)   { return "monorepo" }
  return "root"
}

function Detect-ProductNameIn($path) {
  if (Test-Path (Join-Path $path "package.json")) {
    $content = Get-Content (Join-Path $path "package.json") -Raw
    if ($content -match '"name"\s*:\s*"([^"]+)"') { return $Matches[1] }
  }
  if (Get-ChildItem -Path $path -Filter "*.csproj" -File -ErrorAction SilentlyContinue | Select-Object -First 1) {
    return (Get-ChildItem -Path $path -Filter "*.csproj" -File | Select-Object -First 1).BaseName
  }
  if (Test-Path (Join-Path $path "pyproject.toml")) {
    $content = Get-Content (Join-Path $path "pyproject.toml") -Raw
    if ($content -match 'name\s*=\s*"([^"]+)"') { return $Matches[1] }
  }
  return (Get-Item $path).Name
}

function Detect-StackIn($path) {
  Push-Location $path
  try { return Detect-Stack } finally { Pop-Location }
}

$ProjectMode = Detect-ProjectMode
$ProjectsList = @()
if ($ProjectMode -eq "monorepo") {
  foreach ($d in (List-MonorepoDirs)) {
    $ProjectsList += [ordered]@{
      name  = Detect-ProductNameIn $d
      path  = $d
      stack = Detect-StackIn $d
    }
  }
  $ProductName = (Get-Item -Path ".").Name
  $Stack       = "monorepo"
} else {
  $ProductName = Detect-ProductNameIn "."
  $Stack       = Detect-Stack
}

Write-Host "=========================================="
Write-Host "  LLM Project Mapper - Bootstrap (PowerShell)"
Write-Host "=========================================="
Write-Host ""
Write-Host "Auto-detected (agent will infer team/domain/personas/vision from code):"
Write-Host "  PROJECT_MODE: $ProjectMode"
Write-Host "  PRODUCT_NAME: $ProductName"
Write-Host "  STACK:        $Stack"
if ($ProjectMode -eq "monorepo" -and $ProjectsList.Count -gt 0) {
  Write-Host "  PROJECTS:     $($ProjectsList.Count) subproject(s) detected"
}
Write-Host ""

# ---------------------------------------------------------------------------
# detect existing instruction files (DO NOT overwrite — flag for INIT.md)
# ---------------------------------------------------------------------------
$ExistingInstructionFiles = @()
$candidates = @("AGENTS.md","CLAUDE.md","INIT.md",".github/copilot-instructions.md")
foreach ($f in $candidates) {
  if (Test-Path $f) {
    $content = Get-Content $f -Raw -ErrorAction SilentlyContinue
    if ($content -and $content -notmatch 'LLM Project Mapper|<PRODUCT_NAME>|<STACK>') {
      $ExistingInstructionFiles += $f
    }
  }
}

if ($ExistingInstructionFiles.Count -gt 0) {
  Write-Host "Detected pre-existing instruction files (will be preserved):"
  foreach ($f in $ExistingInstructionFiles) { Write-Host "  - $f" }
  Write-Host "  -> INIT.md will READ them and IMPROVE in place (essence preserved)."
  Write-Host ""
}

# ---------------------------------------------------------------------------
# substitute placeholders ONLY in starter-managed paths
# ---------------------------------------------------------------------------
$StarterDirs = @(".specs",".agents",".skills",".claude",".codex")
$StarterGithubPatterns = @(
  ".github/copilot-instructions.md",
  ".github/copilot",
  ".github/PULL_REQUEST_TEMPLATE.md",
  ".github/ISSUE_TEMPLATE",
  ".github/workflows/ci.yml",
  ".github/workflows/dod.yml"
)
$StarterRootFiles = @(
  "AGENTS.md","CLAUDE.md","INIT.md","_BOOTSTRAP.md",
  "README.md","README.pt-BR.md",
  "playwright.config.ts"
)

$Touched = 0

function Substitute-InFile($path) {
  if (-not (Test-Path $path -PathType Leaf)) { return }
  try {
    $bytes = [System.IO.File]::ReadAllBytes($path)
    if ($bytes.Length -eq 0) { return }
    $head = if ($bytes.Length -gt 8192) { $bytes[0..8191] } else { $bytes }
    if ($head -contains 0) { return }
    $content = [System.IO.Text.Encoding]::UTF8.GetString($bytes)
    if ($content -notmatch '<PRODUCT_NAME>|<STACK>') { return }
    $orig = $content
    $content = $content.Replace("<PRODUCT_NAME>", $script:ProductName)
    $content = $content.Replace("<STACK>",        $script:Stack)
    if ($content -ne $orig) {
      [System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))
      $script:Touched++
    }
  } catch {
  }
}

Write-Host "Substituting placeholders inside starter-managed paths..."

foreach ($dir in $StarterDirs) {
  if (Test-Path $dir -PathType Container) {
    Get-ChildItem -Path $dir -Recurse -File -Include @("*.md","*.json","*.toml","*.yml","*.yaml","*.ts") -ErrorAction SilentlyContinue |
      ForEach-Object { Substitute-InFile $_.FullName }
  }
}

foreach ($p in $StarterGithubPatterns) {
  if (Test-Path $p -PathType Container) {
    Get-ChildItem -Path $p -Recurse -File -ErrorAction SilentlyContinue |
      ForEach-Object { Substitute-InFile $_.FullName }
  } elseif (Test-Path $p -PathType Leaf) {
    Substitute-InFile $p
  }
}

foreach ($f in $StarterRootFiles) { Substitute-InFile $f }

Write-Host "-> $Touched files updated (only starter-managed paths)."
Write-Host ""

# ---------------------------------------------------------------------------
# .gitignore — NEVER overwrite. Append (or create) on opt-in only.
# ---------------------------------------------------------------------------
$RecommendedIgnores = @"
# === LLM Project Mapper (auto-managed) — do not remove this header ===
# Local agent state and ephemeral artifacts created by the starter.
.codex/local
.codex/history
.claude/sessions
.claude/cache
.claude/settings.local.json

# Test artifacts (Playwright + coverage)
test-results/
playwright-report/
playwright/.cache/
coverage/
.nyc_output/

# Env vars
.env
.env.*
!.env.example

# Editor / OS
.DS_Store
Thumbs.db
*.swp
*.swo

# Build / dist (most common)
node_modules/
dist/
build/
out/
.next/
.nuxt/
.turbo/
.vercel/
*.tsbuildinfo

# Logs
*.log
npm-debug.log*
yarn-debug.log*
pnpm-debug.log*

# Tarballs
*.tgz
*.tar.gz

# Runtime receipts
.receipts/**
!.receipts/.gitkeep
"@

function Handle-Gitignore {
  $choice = $script:AppendGitignore
  if ([string]::IsNullOrEmpty($choice) -and -not $script:NonInteractive) {
    Write-Host "=========================================="
    Write-Host "  .gitignore"
    Write-Host "=========================================="
    if (Test-Path ".gitignore") {
      Write-Host "An existing .gitignore was found."
      Write-Host "I can APPEND recommended entries (your existing content is NEVER modified)."
    } else {
      Write-Host "No .gitignore found. I can CREATE one with recommended entries."
    }
    $resp = Read-Host "Proceed? [y/N]"
    if (-not $resp) { $resp = "n" }
    $first = $resp.Substring(0,1).ToLower()
    if ($first -eq "y" -or $first -eq "s") { $choice = "yes" } else { $choice = "no" }
    Write-Host ""
  }
  if (-not $choice) { $choice = "no" }

  if ($choice -ne "yes") {
    Write-Host "-> .gitignore left untouched."
    return
  }

  if (Test-Path ".gitignore") {
    $existing = Get-Content ".gitignore" -Raw -ErrorAction SilentlyContinue
    if ($existing -match "LLM Project Mapper \(auto-managed\)") {
      Write-Host "-> Recommended entries already present in .gitignore. Nothing to do."
    } else {
      Add-Content -Path ".gitignore" -Value "`n$RecommendedIgnores"
      Write-Host "-> Recommended entries APPENDED to .gitignore (original content preserved)."
    }
  } else {
    Set-Content -Path ".gitignore" -Value $RecommendedIgnores -Encoding UTF8
    Write-Host "-> .gitignore CREATED."
  }
}

Handle-Gitignore
Write-Host ""

# ---------------------------------------------------------------------------
# runtime scaffold (.catalog, .receipts, optional MCP edge starter)
# ---------------------------------------------------------------------------
function Handle-RuntimeScaffold {
  New-Item -ItemType Directory -Force -Path ".catalog" | Out-Null
  New-Item -ItemType Directory -Force -Path ".receipts" | Out-Null
  Set-Content -Path ".catalog/.gitkeep" -Value "" -Encoding UTF8
  Set-Content -Path ".receipts/.gitkeep" -Value "" -Encoding UTF8

  if (-not (Test-Path ".catalog/agents.json")) {
    @"
{
  "version": 1,
  "generated_at": null,
  "agents": [],
  "notes": [
    "Generated from AGENTS.md entries that declare yool_id, authority, lane, and agent_terms.",
    "Refresh with bin/build-hamt-catalog after the wrapper is installed."
  ]
}
"@ | Set-Content -Path ".catalog/agents.json" -Encoding UTF8
    Write-Host "-> .catalog/agents.json stub created."
  } else {
    Write-Host "-> .catalog/agents.json already exists (preserved)."
  }

  Write-Host "-> .catalog/.gitkeep and .receipts/.gitkeep ensured."
}

function Handle-McpEdgeScaffold {
  if (-not $script:McpEdge) { return }

  New-Item -ItemType Directory -Force -Path "mcp" | Out-Null

  if (-not (Test-Path "mcp/server.ts")) {
    @'
#!/usr/bin/env node
/**
 * WARNING: MCP is an edge adapter only.
 * Do not move the inner agent loop into this file.
 */
import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const catalogPath = path.resolve(process.cwd(), ".catalog", "agents.json");

async function readCatalog() {
  const raw = await readFile(catalogPath, "utf8");
  return JSON.parse(raw);
}

export async function snapshot() {
  return {
    catalogPath,
    catalog: await readCatalog(),
    generatedAt: new Date().toISOString()
  };
}

export async function dispatch(tuple) {
  return {
    accepted: false,
    reason: "TODO: wire tuple dispatch to the edge transport for your host runtime.",
    tuple,
    catalogPath
  };
}

if (process.argv[1] && import.meta.url === new URL(`file://${process.argv[1]}`).href) {
  const command = process.argv[2] ?? "snapshot";
  if (command === "snapshot") {
    console.log(JSON.stringify(await snapshot(), null, 2));
  } else if (command === "dispatch") {
    const tuple = process.argv[3] ? JSON.parse(process.argv[3]) : {};
    console.log(JSON.stringify(await dispatch(tuple), null, 2));
  } else {
    console.error(`Unknown command: ${command}`);
    process.exit(1);
  }
}
'@ | Set-Content -Path "mcp/server.ts" -Encoding UTF8
    Write-Host "-> mcp/server.ts created."
  } else {
    Write-Host "-> mcp/server.ts already exists (preserved)."
  }

  if (-not (Test-Path "mcp/server.py")) {
    @'
#!/usr/bin/env python3
"""
WARNING: MCP is an edge adapter only.
Do not move the inner agent loop into this file.
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone
from typing import Any

CATALOG_PATH = pathlib.Path.cwd() / ".catalog" / "agents.json"


def read_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def snapshot() -> dict[str, Any]:
    return {
        "catalogPath": str(CATALOG_PATH),
        "catalog": read_catalog(),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


def dispatch(tuple_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "accepted": False,
        "reason": "TODO: wire tuple dispatch to the edge transport for your host runtime.",
        "tuple": tuple_payload,
        "catalogPath": str(CATALOG_PATH),
    }


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    if command == "snapshot":
        print(json.dumps(snapshot(), indent=2))
    elif command == "dispatch":
        payload = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        print(json.dumps(dispatch(payload), indent=2))
    else:
        raise SystemExit(f"Unknown command: {command}")
'@ | Set-Content -Path "mcp/server.py" -Encoding UTF8
    Write-Host "-> mcp/server.py created."
  } else {
    Write-Host "-> mcp/server.py already exists (preserved)."
  }
}

Handle-RuntimeScaffold
Handle-McpEdgeScaffold
Write-Host ""

# ---------------------------------------------------------------------------
# .starter-meta.json (machine-readable handoff for INIT.md)
# ---------------------------------------------------------------------------
$readOnlyGlobs = @(
  "**/*.razor","**/*.cs","**/*.csproj","**/*.sln",
  "package.json","pnpm-lock.yaml","yarn.lock","package-lock.json",
  "**/*.py","**/*.go","**/*.rs","**/*.java","**/*.kt","**/*.dart","**/*.php","**/*.rb"
)

$meta = [ordered]@{
  product_name                = $ProductName
  stack                       = $Stack
  project_mode                = $ProjectMode
  projects                    = $ProjectsList
  bootstrapped_at             = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
  starter_version             = "0.4.0"
  mcp_edge_enabled            = [bool]$McpEdge
  existing_instruction_files  = $ExistingInstructionFiles
  init_must_ask               = @()
  init_must_infer             = @("team","domain","vision_oneliner","personas_beyond_dev")
  default_persona             = "developer"
  init_must_merge             = $ExistingInstructionFiles
  read_only_globs             = $readOnlyGlobs
}
$meta | ConvertTo-Json -Depth 6 | Out-File -FilePath ".starter-meta.json" -Encoding utf8
Write-Host "-> .starter-meta.json saved."
Write-Host ""

# ---------------------------------------------------------------------------
# choose CLI / LLM
# ---------------------------------------------------------------------------
$InitPrompt = 'Read INIT.md and execute it. Do NOT modify any user source files (.razor, .cs, .ts, .py, .go, .rs, package.json, etc). Only write inside .specs/, .agents/, .skills/, .claude/, .codex/, .github/copilot*, .github/workflows/dod.yml plus root AGENTS.md/CLAUDE.md/INIT.md/README*.md. If AGENTS.md/CLAUDE.md/copilot-instructions.md already existed before bootstrap (see .starter-meta.json), READ them and IMPROVE in place — preserve their essence. DO NOT ask the human about team, domain, vision, personas, or product purpose: infer ALL of them by reading the codebase (README, package.json/angular.json/*.csproj/pyproject.toml/etc, entry points, routes, tests, env.example). Default persona is "developer"; additional personas must be derived from code (auth roles, route guards, UI flows, customer-facing copy). Honor workspace mode: if .starter-meta.json.project_mode == "monorepo", iterate over .starter-meta.json.projects[] and produce per-project .specs/. Use parallel multi-agents.'

$CliOpts = @(
  @{ Key="claude";   Label="Claude Code";                                                       Cmd="claude" },
  @{ Key="codex";    Label="Codex CLI";                                                         Cmd="codex" },
  @{ Key="copilot";  Label="GitHub Copilot CLI (chat - no agent loop)";                           Cmd="gh" },
  @{ Key="cursor";   Label="Cursor Agent (cursor-agent)";                                       Cmd="cursor-agent" },
  @{ Key="deepseek"; Label="Deepseek (via aider --model deepseek/deepseek-coder)";              Cmd="aider" },
  @{ Key="kimi";     Label="Kimi K2.6 (via aider --model openrouter/moonshotai/kimi-k2)";       Cmd="aider" },
  @{ Key="minimax";  Label="MiniMax M2.7 (via aider --model openrouter/minimax/minimax-text-01)"; Cmd="aider" },
  @{ Key="glm";      Label="GLM 5.1 (via aider --model openrouter/z-ai/glm-4.5)";               Cmd="aider" },
  @{ Key="simplicio-agent"; Label="Simplicio Agent (canonical consumer of the mapper)";       Cmd="simplicio-agent" },
  @{ Key="hermes";   Label="Hermes Agent (Nous Research) - deprecated alias of Simplicio Agent"; Cmd="hermes" },
  @{ Key="openclaw"; Label="OpenClaw";                                                          Cmd="openclaw" },
  @{ Key="aider";    Label="Aider (pick model interactively)";                                  Cmd="aider" },
  @{ Key="other";    Label="Other / manual (copy prompt to clipboard)";                         Cmd="" },
  @{ Key="skip";     Label="Skip - I will run INIT.md later";                                     Cmd="" }
)

function Has-Cmd($name) {
  if ([string]::IsNullOrEmpty($name)) { return $false }
  return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Choose-Cli {
  if (-not [string]::IsNullOrEmpty($script:Cli)) { return $script:Cli }
  if ($script:NonInteractive) { return "skip" }

  Write-Host "=========================================="
  Write-Host "  Choose the CLI/LLM to run INIT.md"
  Write-Host "=========================================="
  Write-Host ""
  for ($i = 0; $i -lt $CliOpts.Count; $i++) {
    $opt = $CliOpts[$i]
    $mark = ""
    if (Has-Cmd $opt.Cmd) { $mark = "  [installed]" }
    Write-Host ("  [{0,2}] {1}{2}" -f ($i+1), $opt.Label, $mark)
  }
  Write-Host ""
  $resp = Read-Host "Number [13]"
  if ([string]::IsNullOrEmpty($resp)) { $resp = "13" }
  $idx = 0
  if (-not [int]::TryParse($resp, [ref]$idx)) { $idx = 13 }
  if ($idx -lt 1 -or $idx -gt $CliOpts.Count) { $idx = 13 }
  return $CliOpts[$idx-1].Key
}

$CliChoice = Choose-Cli

# ---------------------------------------------------------------------------
# clipboard helper
# ---------------------------------------------------------------------------
function Copy-ToClipboard($text) {
  try { Set-Clipboard -Value $text; return $true } catch { return $false }
}

# ---------------------------------------------------------------------------
# handoff
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=========================================="
Write-Host "  Handing off to: $CliChoice"
Write-Host "=========================================="
Write-Host ""

function Require-Cmd($name, $installHint) {
  if (-not (Has-Cmd $name)) {
    Write-Host "$name not installed: $installHint"
    exit 1
  }
}

switch ($CliChoice) {
  "claude" {
    Require-Cmd "claude" "https://docs.claude.com/claude-code"
    & claude $InitPrompt
    exit $LASTEXITCODE
  }
  "codex" {
    Require-Cmd "codex" "https://github.com/openai/codex"
    & codex exec $InitPrompt
    exit $LASTEXITCODE
  }
  "copilot" {
    Require-Cmd "gh" "https://cli.github.com"
    if (Copy-ToClipboard $InitPrompt) { Write-Host "Prompt copied to clipboard." } else { Write-Host "(clipboard unavailable - copy manually below)" }
    Write-Host ""
    Write-Host "GitHub Copilot CLI does not run an autonomous agent loop."
    Write-Host "Open Copilot Chat (VS Code / IDE) and paste the prompt:"
    Write-Host ""
    Write-Host "  $InitPrompt"
    Write-Host ""
  }
  "cursor" {
    Require-Cmd "cursor-agent" "Cursor 3.0+ required"
    & cursor-agent $InitPrompt
    exit $LASTEXITCODE
  }
  "deepseek" {
    Require-Cmd "aider" "pipx install aider-chat"
    & aider --model deepseek/deepseek-coder --message $InitPrompt
    exit $LASTEXITCODE
  }
  "kimi" {
    Require-Cmd "aider" "pipx install aider-chat"
    & aider --model openrouter/moonshotai/kimi-k2 --message $InitPrompt
    exit $LASTEXITCODE
  }
  "minimax" {
    Require-Cmd "aider" "pipx install aider-chat"
    & aider --model openrouter/minimax/minimax-text-01 --message $InitPrompt
    exit $LASTEXITCODE
  }
  "glm" {
    Require-Cmd "aider" "pipx install aider-chat"
    & aider --model openrouter/z-ai/glm-4.5 --message $InitPrompt
    exit $LASTEXITCODE
  }
  "hermes" {
    Write-Warning "[deprecated] 'hermes' is a deprecated alias of 'simplicio-agent' (Simplicio Agent). Use 'simplicio-agent' instead. The alias is retained for compatibility and will be removed after a release window."
    Require-Cmd "hermes" "https://github.com/NousResearch/hermes-agent"
    Copy-ToClipboard $InitPrompt | Out-Null
    Write-Host "(prompt copied to clipboard as fallback)"
    & hermes $InitPrompt
    exit $LASTEXITCODE
  }
  "simplicio-agent" {
    Require-Cmd "simplicio-agent" "https://github.com/wesleysimplicio/simplicio-agent"
    Copy-ToClipboard $InitPrompt | Out-Null
    Write-Host "(prompt copied to clipboard as fallback)"
    & simplicio-agent $InitPrompt
    exit $LASTEXITCODE
  }
  "openclaw" {
    Require-Cmd "openclaw" "npm install -g openclaw@latest"
    Copy-ToClipboard $InitPrompt | Out-Null
    Write-Host "(prompt copied to clipboard as fallback)"
    & openclaw $InitPrompt
    exit $LASTEXITCODE
  }
  "aider" {
    Require-Cmd "aider" "pipx install aider-chat"
    & aider --message $InitPrompt
    exit $LASTEXITCODE
  }
  "other" {
    if (Copy-ToClipboard $InitPrompt) {
      Write-Host "Prompt copied to clipboard. Paste it into your CLI/agent of choice."
    } else {
      Write-Host "(clipboard unavailable - copy the prompt below manually)"
    }
    Write-Host ""
    Write-Host "Prompt:"
    Write-Host "  $InitPrompt"
    Write-Host ""
  }
  default {
    @"
Skipped CLI handoff. To run INIT.md later, open your agent and paste:

  $InitPrompt

Recommended next steps:
  1) Open an agent in this folder.
  2) Paste the prompt above.
  3) Review .specs/product/VISION.md, DOMAIN.md, architecture/DESIGN.md.
  4) git add -A; git commit -m "chore: bootstrap llm project mapper"

Docs: https://github.com/wesleysimplicio/llm-project-mapper
"@ | Write-Host
  }
}
