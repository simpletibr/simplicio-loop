#!/usr/bin/env node
/**
 * LLM Project Mapper - CLI scaffolder.
 *
 * Run inside any project to install the starter pack:
 *   npx @wesleysimplicio/llm-project-mapper
 *
 * Behavior (mirror of bootstrap.sh / bootstrap.ps1):
 *   1. Auto-detects PRODUCT_NAME and STACK (Node/.NET/Python/Go/Rust/Flutter/PHP/...).
 *      Auto-detects PROJECT_MODE from workspace signals at cwd:
 *        - monorepo signal (pnpm-workspace.yaml, lerna.json, nx.json,
 *          turbo.json, rush.json, package.json with "workspaces", or >=2
 *          apps/ packages/ services/ subfolders with manifests) -> "monorepo"
 *        - otherwise -> "root" (single project at cwd)
 *      INIT.md infers team/domain/personas/vision from the codebase (no human
 *      prompts).
 *   2. Asks only TWO questions:
 *        - Append recommended ignore entries to .gitignore? (y/N)
 *        - Which CLI/LLM should run INIT.md?
 *   3. Immediately runs an automatic local mapping pass that fills the
 *      starter-managed docs from the detected project structure.
 *   4. Substitutes <PRODUCT_NAME>/<STACK> ONLY inside starter-managed paths
 *      AND only when the file actually contains a placeholder (protects user
 *      .razor/.cs/.ts/.py/package.json).
 *   5. NEVER overwrites pre-existing user files. Existing instruction
 *      files (AGENTS.md/CLAUDE.md/INIT.md/copilot-instructions.md) are
 *      preserved AND flagged in .starter-meta.json so INIT.md can read
 *      them and improve in place (essence preserved).
 *   6. .gitignore: never overwritten. Appended on opt-in, created if missing.
 *   7. Optionally hands off to the chosen CLI to further refine INIT.md.
 *
 * Pure Node.js. No bash dependency. Works on macOS, Linux, and Windows.
 */

'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const https = require('node:https');
const { spawn, spawnSync } = require('node:child_process');
const { autoMapProject } = require('./auto-map');

const PACKAGE_ROOT = path.resolve(__dirname, '..');
const CWD = process.cwd();
const PKG = require(path.join(PACKAGE_ROOT, 'package.json'));

// Candidate Python 3 executable names to probe for the `map`/`update` shim
// (issue #158, ADR-005). `python3` first everywhere except Windows, where a
// bare `python` more commonly resolves to Python 3 (`python3` is often
// absent there even when Python 3 is installed).
const PYTHON_SHIM_CANDIDATES = process.platform === 'win32'
  ? ['python', 'python3']
  : ['python3', 'python'];

/**
 * Probe PATH for a Python 3 interpreter that can `import simplicio_mapper`.
 * Returns the executable name/path to use, or `null` when neither Python
 * nor an importable `simplicio_mapper` package is available -- callers
 * must fall back to the Node reimplementation in that case, never fail.
 */
function detectPythonShim() {
  for (const candidate of PYTHON_SHIM_CANDIDATES) {
    let probe;
    try {
      probe = spawnSync(candidate, ['-c', 'import simplicio_mapper'], { stdio: 'ignore' });
    } catch {
      continue;
    }
    if (!probe.error && probe.status === 0) {
      return candidate;
    }
  }
  return null;
}

const TEMPLATE_PATHS = [
  'AGENTS.md',
  'CLAUDE.md',
  'INIT.md',
  '_BOOTSTRAP.md',
  'YOOL_TUPLE_HAMT.md',
  'README.md',
  'README.pt-BR.md',
  'INSTALL.md',
  '.agents',
  '.claude',
  '.codex',
  '.github',
  '.skills',
  '.specs',
  'docs',
  'scripts',
  'bootstrap.sh',
  'bootstrap.ps1',
  'playwright.config.ts',
  'tests',
];

const PROTECTED_INSTRUCTION_FILES = [
  'AGENTS.md',
  'CLAUDE.md',
  'INIT.md',
  '.github/copilot-instructions.md',
];

const COLLISION_PRONE_TEMPLATE_FILES = [
  'README.md',
  'README.pt-BR.md',
  'INSTALL.md',
];

const STARTER_DIRS = ['.specs', '.agents', '.skills', '.claude', '.codex'];
const STARTER_GITHUB_PATTERNS = [
  '.github/copilot-instructions.md',
  '.github/copilot',
  '.github/PULL_REQUEST_TEMPLATE.md',
  '.github/ISSUE_TEMPLATE',
  '.github/workflows/ci.yml',
  '.github/workflows/dod.yml',
];
const STARTER_ROOT_FILES = [
  'AGENTS.md', 'CLAUDE.md', 'INIT.md', '_BOOTSTRAP.md',
  'README.md', 'README.pt-BR.md',
  'playwright.config.ts',
];

const TEXT_EXTS = new Set(['.md', '.json', '.toml', '.yml', '.yaml', '.ts']);

const WALK_SKIP_DIRS = new Set([
  'node_modules', '.git', 'dist', 'build', 'out',
  '.next', '.nuxt', 'coverage', 'playwright-report', 'test-results',
]);

const GITIGNORE_MARKER = '# === LLM Project Mapper (auto-managed)';
const GITIGNORE_END_MARKER = '# === End LLM Project Mapper (auto-managed) ===';

const RECOMMENDED_IGNORES = `# === LLM Project Mapper (auto-managed) — do not remove this header ===
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
# === End LLM Project Mapper (auto-managed) ===
`;

const GITATTRIBUTES_CONTENT = `# Cross-platform line endings.
* text=auto eol=lf

# Shell scripts MUST be LF.
*.sh        text eol=lf
*.bash      text eol=lf

# Windows scripts MUST be CRLF.
*.ps1       text eol=crlf
*.psm1      text eol=crlf
*.psd1      text eol=crlf
*.bat       text eol=crlf
*.cmd       text eol=crlf

# Common config / source.
*.md        text
*.json      text
*.jsonc     text
*.yml       text
*.yaml      text
*.toml      text
*.xml       text
*.html      text
*.css       text
*.scss      text
*.js        text
*.jsx       text
*.ts        text
*.tsx       text
*.mjs       text
*.cjs       text
*.py        text
*.cs        text
*.csproj    text
*.sln       text eol=crlf
*.go        text
*.rs        text
*.java      text
*.kt        text
*.kts       text
*.gradle    text

# Binaries: never normalize.
*.png       binary
*.jpg       binary
*.jpeg      binary
*.gif       binary
*.ico       binary
*.pdf       binary
*.zip       binary
*.gz        binary
*.tar       binary
*.7z        binary
*.exe       binary
*.dll       binary
*.so        binary
*.dylib     binary
*.woff      binary
*.woff2     binary
*.ttf       binary
*.eot       binary
*.mp3       binary
*.mp4       binary
*.mov       binary

# Lockfiles: text but no noisy diff.
package-lock.json    text -diff
pnpm-lock.yaml       text -diff
yarn.lock            text -diff
poetry.lock          text -diff
Cargo.lock           text -diff
`;

const CLI_OPTS = [
  { key: 'claude',   label: 'Claude Code',                                                       cmd: 'claude' },
  { key: 'codex',    label: 'Codex CLI',                                                         cmd: 'codex' },
  { key: 'copilot',  label: 'GitHub Copilot CLI (chat — no agent loop)',                         cmd: 'gh' },
  { key: 'cursor',   label: 'Cursor Agent (cursor-agent)',                                       cmd: 'cursor-agent' },
  { key: 'deepseek', label: 'Deepseek (via aider --model deepseek/deepseek-coder)',              cmd: 'aider' },
  { key: 'kimi',     label: 'Kimi K2.6 (via aider --model openrouter/moonshotai/kimi-k2)',       cmd: 'aider' },
  { key: 'minimax',  label: 'MiniMax M2.7 (via aider --model openrouter/minimax/minimax-text-01)', cmd: 'aider' },
  { key: 'glm',      label: 'GLM 5.1 (via aider --model openrouter/z-ai/glm-4.5)',               cmd: 'aider' },
  { key: 'simplicio-agent', label: 'Simplicio Agent (canonical consumer of the mapper)',        cmd: 'simplicio-agent' },
  { key: 'hermes',   label: 'Hermes Agent (Nous Research) — deprecated alias of Simplicio Agent', cmd: 'hermes' },
  { key: 'openclaw', label: 'OpenClaw',                                                          cmd: 'openclaw' },
  { key: 'aider',    label: 'Aider (pick model interactively)',                                  cmd: 'aider' },
  { key: 'other',    label: 'Other / manual (copy prompt to clipboard)',                         cmd: '' },
  { key: 'skip',     label: 'Skip — I will run INIT.md later',                                   cmd: '' },
];

const INIT_PROMPT = 'Read INIT.md and execute it. Do NOT modify any user source files (.razor, .cs, .ts, .py, .go, .rs, package.json, etc). Only write inside .specs/, .agents/, .skills/, .claude/, .codex/, .github/copilot*, .github/workflows/dod.yml plus root AGENTS.md/CLAUDE.md/INIT.md/README*.md. If AGENTS.md/CLAUDE.md/copilot-instructions.md already existed before bootstrap (see .starter-meta.json), READ them and IMPROVE in place — preserve their essence. DO NOT ask the human about team, domain, vision, personas, or product purpose: infer ALL of them by reading the codebase (README, package.json/angular.json/*.csproj/pyproject.toml/etc, entry points, routes, tests, env.example). Default persona is "developer"; additional personas must be derived from code (auth roles, route guards, UI flows, customer-facing copy). Honor workspace mode: if .starter-meta.json.project_mode == "monorepo", iterate over .starter-meta.json.projects[] and produce per-project .specs/. Use parallel multi-agents.';

const PRESETS = {
  nextjs:  { label: 'Next.js 14 + React 18 + TypeScript', baseUrl: 'http://localhost:3000' },
  dotnet:  { label: '.NET 8 (ASP.NET Core)', baseUrl: 'http://localhost:5000' },
  fastapi: { label: 'Python 3.11 + FastAPI + Uvicorn', baseUrl: 'http://localhost:8000' },
  go:      { label: 'Go 1.22 + net/http', baseUrl: 'http://localhost:8080' },
  rails:   { label: 'Ruby on Rails 7', baseUrl: 'http://localhost:3000' },
  flutter: { label: 'Flutter 3 + Dart', baseUrl: 'http://localhost:8080' },
};

const argv = process.argv.slice(2);

if (argv[0] === 'build-hamt-catalog') {
  const wrapper = path.join(__dirname, 'build-hamt-catalog');
  const child = spawnSync(process.execPath, [wrapper, ...argv.slice(1)], {
    cwd: process.cwd(),
    stdio: 'inherit',
  });
  if (child.error) {
    console.error(`Failed to run build-hamt-catalog: ${child.error.message}`);
    process.exit(1);
  }
  process.exit(child.status ?? 1);
}

if (argv[0] === 'skillopt') {
  const wrapper = path.join(__dirname, 'skillopt.js');
  const child = spawnSync(process.execPath, [wrapper, ...argv.slice(1)], {
    cwd: process.cwd(),
    stdio: 'inherit',
  });
  if (child.error) {
    console.error(`Failed to run skillopt: ${child.error.message}`);
    process.exit(1);
  }
  process.exit(child.status ?? 1);
}

if (argv[0] === 'map' || argv[0] === 'update') {
  // Issue #158 (ADR-005, .specs/architecture/ADR-005-node-thin-shim.md):
  // `map`/`update` prefer shimming straight through to the canonical Python
  // CLI (`python3 -m simplicio_mapper.cli`) when a Python 3 + an importable
  // `simplicio_mapper` are both present on PATH -- argv passes through
  // unchanged since the two CLIs already accept the identical
  // --root/--stack/--product-name/--out/--incremental/--watch/--silent flag
  // set for these two subcommands. `map.js`/`mapper-artifacts.js` (the Node
  // reimplementation of the mapper) is kept only as the fallback for hosts
  // without Python -- this is a transitional state, not the long-term shape;
  // see the ADR for what is/isn't shimmed yet and why. Set
  // `SIMPLICIO_MAPPER_NO_SHIM=1` to force the Node path (debugging/tests).
  if (!process.env.SIMPLICIO_MAPPER_NO_SHIM) {
    const pythonBin = detectPythonShim();
    if (pythonBin) {
      const child = spawnSync(pythonBin, ['-m', 'simplicio_mapper.cli', ...argv], {
        cwd: process.cwd(),
        stdio: 'inherit',
      });
      if (!child.error) {
        process.exit(child.status ?? 1);
      }
      // Unexpected spawn error (not "Python missing" -- that already
      // returned null from detectPythonShim above) -- fall through to the
      // Node reimplementation rather than fail the whole command.
    }
  }
  const wrapper = path.join(__dirname, 'map.js');
  const child = spawnSync(process.execPath, [wrapper, ...argv], {
    cwd: process.cwd(),
    stdio: 'inherit',
  });
  if (child.error) {
    console.error(`Failed to run mapper update: ${child.error.message}`);
    process.exit(1);
  }
  process.exit(child.status ?? 1);
}

const opts = {
  yes: false,
  force: false,
  dryRun: false,
  mcpEdge: false,
  silent: false,
  skipMeta: false,
  update: false,
  cli: '',
  appendGitignore: '',
  preset: '',
  noUpdateCheck: false,
  telemetry: '',
};

for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  switch (a) {
    case '-y':
    case '--yes':              opts.yes = true; break;
    case '-f':
    case '--force':            opts.force = true; break;
    case '--dry-run':          opts.dryRun = true; break;
    case '--mcp-edge':         opts.mcpEdge = true; break;
    case '--update':           opts.update = true; break;
    case '--silent':           opts.silent = true; break;
    case '--skip-meta':        opts.skipMeta = true; break;
    case '--cli':              opts.cli = argv[++i]; break;
    case '--append-gitignore': opts.appendGitignore = argv[++i]; break;
    case '--preset':           opts.preset = argv[++i]; break;
    case '--no-update-check':  opts.noUpdateCheck = true; break;
    case '--telemetry':        opts.telemetry = argv[++i]; break;
    case '-v':
    case '--version':
      console.log(PKG.version);
      process.exit(0);
    case '-h':
    case '--help':
      printHelp();
      process.exit(0);
    default:
      console.error(`Unknown flag: ${a}`);
      console.error('Run with --help for usage.');
      process.exit(2);
  }
}

if (opts.preset === 'list') {
  console.log('Available presets:');
  for (const [key, def] of Object.entries(PRESETS)) {
    console.log(`  ${key.padEnd(10)} ${def.label}`);
  }
  process.exit(0);
}

if (opts.preset && !PRESETS[opts.preset]) {
  console.error(`Unknown preset: ${opts.preset}`);
  console.error(`Available: ${Object.keys(PRESETS).join(', ')} (or "list").`);
  process.exit(2);
}

if (opts.update) {
  opts.yes = true;
  opts.force = true;
  opts.appendGitignore = opts.appendGitignore || 'no';
  opts.cli = opts.cli || 'skip';
}

function printHelp() {
  console.log(`llm-project-mapper v${PKG.version}

Scaffold the LLM Project Mapper pack into the current directory.
An automatic local mapping pass starts immediately after the files are applied.

USAGE
  npx @wesleysimplicio/llm-project-mapper [options]
  npx @wesleysimplicio/llm-project-mapper map [--root <dir>] [--incremental] [--watch]
  npx @wesleysimplicio/llm-project-mapper update [--root <dir>] [--watch]
  npx @wesleysimplicio/llm-project-mapper build-hamt-catalog [project-root] [--source <AGENTS.md>] [--output <.catalog/agents.json>]
  npx @wesleysimplicio/llm-project-mapper skillopt --suite <suite.json> [--skill <SKILL.md>] [--out best_skill.md]

OPTIONS
  -y, --yes                   Non-interactive (defaults: no gitignore append, skip CLI handoff)
  -f, --force                 Overwrite starter template files (NEVER touches user
                              instruction files: AGENTS.md, CLAUDE.md, INIT.md,
                              .github/copilot-instructions.md, .gitignore)
  --update                    Safe update mode: --yes --force --append-gitignore no --cli skip
  --dry-run                   Print actions without writing files
  --mcp-edge                  Create mcp/server.ts and mcp/server.py edge adapters
  --skip-meta                 Do not write .starter-meta.json
  --cli <key>                 Pick CLI for INIT.md handoff (claude|codex|copilot|cursor|
                              deepseek|kimi|minimax|glm|simplicio-agent|hermes|openclaw|aider|other|skip)
                              Note: 'hermes' is a deprecated alias of 'simplicio-agent'.
  --append-gitignore <yes|no> Append recommended ignores to .gitignore (or create it)
  --preset <name>             Stack hint recorded in .starter-meta.json for INIT.md to use
                              (nextjs|dotnet|fastapi|go|rails|flutter). Use "--preset list"
                              to see available presets.
  --no-update-check           Disable the npm-registry semver check on startup
                              (also honored via env LLM_PROJECT_MAPPER_NO_UPDATE_CHECK=1)
  --telemetry <on|off>        Opt in/out of anonymous install telemetry.
                              Default is OFF. Also honored via env
                              LLM_PROJECT_MAPPER_TELEMETRY=on|off. See
                              docs/PRIVACY.md for what gets sent.
  --silent                    Minimal output
  -v, --version               Print version
  -h, --help                  Show this help

EXAMPLES
  npx @wesleysimplicio/llm-project-mapper
  npx @wesleysimplicio/llm-project-mapper --yes
  npx @wesleysimplicio/llm-project-mapper --yes --cli claude --append-gitignore yes
  npx @wesleysimplicio/llm-project-mapper --yes --preset nextjs
  npx @wesleysimplicio/llm-project-mapper --preset list
  npx @wesleysimplicio/llm-project-mapper@latest --update
  npx @wesleysimplicio/llm-project-mapper map --incremental
  npx @wesleysimplicio/llm-project-mapper build-hamt-catalog
  npx @wesleysimplicio/llm-project-mapper skillopt --suite skillopt.suite.json

DOCS
  https://github.com/wesleysimplicio/llm-project-mapper
`);
}

const log = (...a) => { if (!opts.silent) console.log(...a); };
const err = (...a) => console.error(...a);

function maybeNotifyUpdate() {
  if (opts.noUpdateCheck) return;
  if (process.env.LLM_PROJECT_MAPPER_NO_UPDATE_CHECK === '1') return;
  if (process.env.CI) return;
  const cacheDir = path.join(os.homedir(), '.config', 'llm-project-mapper');
  const cacheFile = path.join(cacheDir, 'update-check.json');
  const TTL_MS = 24 * 60 * 60 * 1000;
  let cached = null;
  try {
    cached = JSON.parse(fs.readFileSync(cacheFile, 'utf8'));
  } catch { /* no cache */ }
  if (cached && Date.now() - cached.checkedAt < TTL_MS) {
    if (cached.latest && cached.latest !== PKG.version) {
      err(`\n  Update available ${PKG.version} → ${cached.latest}`);
      err('  Run: npx @wesleysimplicio/llm-project-mapper@latest --update\n');
    }
    return;
  }
  https.get(
    'https://registry.npmjs.org/@wesleysimplicio/llm-project-mapper/latest',
    { headers: { Accept: 'application/json' }, timeout: 1500 },
    (res) => {
      let body = '';
      res.on('data', (c) => { body += c; });
      res.on('end', () => {
        try {
          const latest = JSON.parse(body).version;
          fs.mkdirSync(cacheDir, { recursive: true });
          fs.writeFileSync(cacheFile, JSON.stringify({ latest, checkedAt: Date.now() }) + '\n');
        } catch { /* ignore */ }
      });
    },
  ).on('error', () => { /* offline or registry unreachable — silent */ })
   .on('timeout', function onTimeout() { this.destroy(); });
}

function telemetryEnabled() {
  // Resolution order (last wins): config file < env var < CLI flag.
  let enabled = false;
  const configPath = path.join(os.homedir(), '.config', 'llm-project-mapper', 'telemetry.json');
  try {
    const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    if (cfg && typeof cfg.enabled === 'boolean') enabled = cfg.enabled;
  } catch { /* no config yet */ }
  const envVal = (process.env.LLM_PROJECT_MAPPER_TELEMETRY || '').toLowerCase();
  if (envVal === 'on'  || envVal === '1' || envVal === 'true')  enabled = true;
  if (envVal === 'off' || envVal === '0' || envVal === 'false') enabled = false;
  if (opts.telemetry === 'on')  enabled = true;
  if (opts.telemetry === 'off') enabled = false;
  return enabled;
}

function persistTelemetryChoice(enabled) {
  try {
    const dir = path.join(os.homedir(), '.config', 'llm-project-mapper');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      path.join(dir, 'telemetry.json'),
      JSON.stringify({ enabled, choiceAt: new Date().toISOString() }, null, 2) + '\n',
    );
  } catch { /* best-effort */ }
}

function maybeSendTelemetry(productName, stack, projectMode) {
  // Hard gates first — never send under any of these conditions.
  if (opts.dryRun) return;
  if (process.env.CI) return;
  if (process.env.LLM_PROJECT_MAPPER_TELEMETRY === '0' || process.env.LLM_PROJECT_MAPPER_TELEMETRY === 'off') return;
  if (opts.telemetry === 'off') return;

  if (!telemetryEnabled()) return;

  // Endpoint must be explicitly configured (no default beacon URL — opt-in even after opt-in).
  const endpoint = process.env.LLM_PROJECT_MAPPER_TELEMETRY_URL;
  if (!endpoint) return;

  let url;
  try {
    url = new URL(endpoint);
  } catch { return; }
  if (url.protocol !== 'https:') return; // require TLS

  const payload = {
    starter_version: PKG.version,
    stack: stack || 'unknown',
    project_mode: projectMode || 'root',
    preset: opts.preset || null,
    node_version: process.versions.node,
    os: process.platform,
    arch: process.arch,
    cli_runtime: '@wesleysimplicio/llm-project-mapper',
    timestamp: new Date().toISOString(),
  };
  // Intentionally never include: product_name, cwd, hostname, username, env, paths, git remote.

  const body = JSON.stringify(payload);
  const req = https.request(
    {
      method: 'POST',
      hostname: url.hostname,
      port: url.port || 443,
      path: url.pathname + url.search,
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
        'User-Agent': `llm-project-mapper/${PKG.version}`,
      },
      timeout: 1500,
    },
    (res) => { res.resume(); /* drain and discard */ },
  );
  req.on('error', () => { /* offline / endpoint down — silent */ });
  req.on('timeout', () => req.destroy());
  req.write(body);
  req.end();
}

function readSafe(p) { try { return fs.readFileSync(p, 'utf8'); } catch { return ''; } }
function existsHere(rel) { return fs.existsSync(path.join(CWD, rel)); }
function listCwd() { try { return fs.readdirSync(CWD); } catch { return []; } }
function commandExists(cmd) {
  if (!cmd) return false;
  const which = process.platform === 'win32' ? 'where' : 'which';
  const r = spawnSync(which, [cmd], { stdio: 'ignore' });
  return r.status === 0;
}

function detectStack() {
  if (existsHere('package.json')) {
    const pj = readSafe(path.join(CWD, 'package.json'));
    if (/"next"\s*:/.test(pj))                    return 'next-ts';
    if (/"react"\s*:/.test(pj))                   return 'react-ts';
    if (/"vue"\s*:/.test(pj))                     return 'vue-ts';
    if (/"@nestjs\/core"|"nestjs"\s*:/.test(pj))  return 'nestjs';
    if (/"express"\s*:/.test(pj))                 return 'node-express';
    return 'node-ts';
  }
  const files = listCwd();
  if (files.some(f => f.endsWith('.csproj') || f.endsWith('.sln'))) return 'dotnet';
  if (existsHere('pyproject.toml') || existsHere('requirements.txt')) {
    const py = readSafe(path.join(CWD, 'pyproject.toml')) + readSafe(path.join(CWD, 'requirements.txt'));
    if (/django/i.test(py))   return 'python-django';
    if (/fastapi/i.test(py))  return 'python-fastapi';
    if (/flask/i.test(py))    return 'python-flask';
    return 'python';
  }
  if (existsHere('go.mod'))         return 'go';
  if (existsHere('Cargo.toml'))     return 'rust';
  if (existsHere('pubspec.yaml'))   return 'flutter';
  if (existsHere('composer.json')) {
    return /laravel\/framework/.test(readSafe(path.join(CWD, 'composer.json'))) ? 'laravel' : 'php';
  }
  if (existsHere('Gemfile'))           return 'ruby';
  if (existsHere('mix.exs'))           return 'elixir';
  if (existsHere('build.gradle.kts'))  return 'kotlin-gradle';
  if (existsHere('build.gradle'))      return 'java-gradle';
  if (existsHere('pom.xml'))           return 'java-maven';
  return 'unknown';
}

const MONOREPO_PARENTS = ['apps', 'packages', 'services', 'projects'];
const SUBPROJECT_MANIFESTS = [
  'package.json', 'pyproject.toml', 'go.mod', 'Cargo.toml', 'pubspec.yaml',
  'composer.json', 'Gemfile', 'pom.xml', 'build.gradle', 'build.gradle.kts',
];

function hasWorkspaceSignal() {
  if (existsHere('pnpm-workspace.yaml')) return true;
  if (existsHere('lerna.json'))          return true;
  if (existsHere('nx.json'))             return true;
  if (existsHere('turbo.json'))          return true;
  if (existsHere('rush.json'))           return true;
  if (existsHere('package.json')) {
    if (/"workspaces"\s*:/.test(readSafe(path.join(CWD, 'package.json')))) return true;
  }
  return false;
}

function detectStackIn(absDir) {
  const exists = (rel) => fs.existsSync(path.join(absDir, rel));
  const read = (rel) => readSafe(path.join(absDir, rel));
  if (exists('package.json')) {
    const pj = read('package.json');
    if (/"next"\s*:/.test(pj))                    return 'next-ts';
    if (/"@angular\/core"\s*:/.test(pj))          return 'angular';
    if (/"react"\s*:/.test(pj))                   return 'react-ts';
    if (/"vue"\s*:/.test(pj))                     return 'vue-ts';
    if (/"@nestjs\/core"|"nestjs"\s*:/.test(pj))  return 'nestjs';
    if (/"express"\s*:/.test(pj))                 return 'node-express';
    return 'node-ts';
  }
  let entries = [];
  try { entries = fs.readdirSync(absDir); } catch { /* ignore */ }
  if (entries.some(f => f.endsWith('.csproj') || f.endsWith('.sln'))) return 'dotnet';
  if (exists('pyproject.toml'))    return 'python';
  if (exists('go.mod'))            return 'go';
  if (exists('Cargo.toml'))        return 'rust';
  if (exists('pubspec.yaml'))      return 'flutter';
  if (exists('composer.json'))     return 'php';
  if (exists('Gemfile'))           return 'ruby';
  if (exists('mix.exs'))           return 'elixir';
  if (exists('build.gradle.kts'))  return 'kotlin-gradle';
  if (exists('build.gradle'))      return 'java-gradle';
  if (exists('pom.xml'))           return 'java-maven';
  return 'unknown';
}

function detectProductNameIn(absDir, fallback) {
  const exists = (rel) => fs.existsSync(path.join(absDir, rel));
  const read = (rel) => readSafe(path.join(absDir, rel));
  if (exists('package.json')) {
    const m = read('package.json').match(/"name"\s*:\s*"([^"]+)"/);
    if (m) return m[1];
  }
  let entries = [];
  try { entries = fs.readdirSync(absDir); } catch { /* ignore */ }
  const csproj = entries.find(f => f.endsWith('.csproj'));
  if (csproj) return csproj.replace(/\.csproj$/, '');
  if (exists('pyproject.toml')) {
    const m = read('pyproject.toml').match(/name\s*=\s*"([^"]+)"/);
    if (m) return m[1];
  }
  if (exists('Cargo.toml')) {
    const m = read('Cargo.toml').match(/name\s*=\s*"([^"]+)"/);
    if (m) return m[1];
  }
  return fallback;
}

function listMonorepoDirs() {
  const dirs = [];
  for (const parent of MONOREPO_PARENTS) {
    const absParent = path.join(CWD, parent);
    if (!fs.existsSync(absParent)) continue;
    let subs = [];
    try { subs = fs.readdirSync(absParent, { withFileTypes: true }); } catch { continue; }
    for (const sub of subs) {
      if (!sub.isDirectory() || sub.name.startsWith('.')) continue;
      const absSub = path.join(absParent, sub.name);
      let hasManifest = SUBPROJECT_MANIFESTS.some(m => fs.existsSync(path.join(absSub, m)));
      if (!hasManifest) {
        let inner = [];
        try { inner = fs.readdirSync(absSub); } catch { /* ignore */ }
        hasManifest = inner.some(f => f.endsWith('.csproj'));
      }
      if (hasManifest) dirs.push(path.join(parent, sub.name).replace(/\\/g, '/'));
    }
  }
  return dirs.sort();
}

function detectProjectMode() {
  if (hasWorkspaceSignal()) return 'monorepo';
  if (listMonorepoDirs().length >= 2) return 'monorepo';
  return 'root';
}

function buildProjectsList() {
  return listMonorepoDirs().map(rel => {
    const abs = path.join(CWD, rel);
    return {
      name: detectProductNameIn(abs, path.basename(rel)),
      path: rel,
      stack: detectStackIn(abs),
    };
  });
}

function detectExistingInstructionFiles() {
  const found = [];
  for (const rel of PROTECTED_INSTRUCTION_FILES) {
    const abs = path.join(CWD, rel);
    if (!fs.existsSync(abs)) continue;
    const content = readSafe(abs);
    if (/LLM Project Mapper|<PRODUCT_NAME>|<STACK>/.test(content)) continue;
    found.push(rel);
  }
  return found;
}

function looksStarterManagedContent(content) {
  return /LLM Project Mapper|@wesleysimplicio\/llm-project-mapper|<PRODUCT_NAME>|<STACK>/.test(content);
}

function readExistingMeta() {
  try {
    return JSON.parse(readSafe(path.join(CWD, '.starter-meta.json')) || '{}');
  } catch {
    return {};
  }
}

function detectPreservedUserFiles() {
  const metaPath = path.join(CWD, '.starter-meta.json');
  const hasMeta = fs.existsSync(metaPath);
  const meta = readExistingMeta();
  if (Array.isArray(meta.preserved_user_files)) {
    return Array.from(new Set(meta.preserved_user_files)).sort();
  }

  const preserved = new Set();
  const heuristicFiles = hasMeta ? ['README.md'] : COLLISION_PRONE_TEMPLATE_FILES;

  for (const rel of heuristicFiles) {
    const abs = path.join(CWD, rel);
    if (!fs.existsSync(abs)) continue;

    const content = readSafe(abs);
    if (!looksStarterManagedContent(content)) {
      preserved.add(rel);
    }
  }

  return Array.from(preserved).sort();
}

// Some paths under TEMPLATE_PATHS directories (.specs/, docs/) carry this
// product's OWN filled-in content (real simplicio-mapper docs, not generic
// starter placeholders) — see template-manifest.json and
// .specs/architecture/ADR-004-template-vs-product-content-manifest.md.
// Those must never be copied verbatim into a host project; autoMapProject's
// dynamic renderers (bin/auto-map.js) fill them in fresh for the host instead.
function loadProductPaths() {
  try {
    const manifest = JSON.parse(fs.readFileSync(path.join(PACKAGE_ROOT, 'template-manifest.json'), 'utf8'));
    return new Set(manifest.product_paths || []);
  } catch (e) {
    return new Set();
  }
}

function copyTemplate(existingProtected, preservedUserFiles) {
  const protectedSet = new Set([...existingProtected, ...preservedUserFiles]);
  const productPaths = loadProductPaths();
  const skipProductPaths = (srcPath) => {
    const rel = path.relative(PACKAGE_ROOT, srcPath).split(path.sep).join('/');
    return !productPaths.has(rel);
  };
  let copied = 0, skipped = 0, missing = 0;

  for (const rel of TEMPLATE_PATHS) {
    const src = path.join(PACKAGE_ROOT, rel);
    const dest = path.join(CWD, rel);

    if (!fs.existsSync(src)) { missing++; continue; }

    if (protectedSet.has(rel)) {
      log(`  preserve (user): ${rel}`);
      skipped++;
      continue;
    }

    if (fs.existsSync(dest) && !opts.force) {
      log(`  skip  (exists): ${rel}`);
      skipped++;
      continue;
    }
    if (opts.dryRun) {
      log(`  copy  (dry):    ${rel}`);
      copied++;
      continue;
    }
    try {
      fs.cpSync(src, dest, { recursive: true, force: true, filter: skipProductPaths });
      log(`  copy:           ${rel}`);
      copied++;
    } catch (e) {
      err(`  fail  ${rel}: ${e.message}`);
    }
  }

  log(`\n→ ${copied} copied, ${skipped} skipped${opts.force ? '' : ' (use --force to overwrite starter files)'}, ${missing} missing in package.\n`);
}

async function handleGitignore(rl) {
  let choice = opts.appendGitignore;
  if (!choice && !opts.yes) {
    log('==========================================');
    log('  .gitignore');
    log('==========================================');
    if (existsHere('.gitignore')) {
      log('An existing .gitignore was found.');
      log('I can APPEND recommended entries (your existing content is NEVER modified).');
    } else {
      log('No .gitignore found. I can CREATE one with recommended entries.');
    }
    const resp = await ask(rl, 'Proceed?', 'n');
    choice = /^[ys]/i.test(resp) ? 'yes' : 'no';
    log('');
  }
  choice = choice || 'no';

  if (choice !== 'yes') {
    log('→ .gitignore left untouched.\n');
    return;
  }

  const gi = path.join(CWD, '.gitignore');
  if (fs.existsSync(gi)) {
    const existing = readSafe(gi);
    if (opts.dryRun) {
      log('  append (dry):   .gitignore\n');
    } else {
      const next = upsertGitignore(existing);
      fs.writeFileSync(gi, next);
      if (existing.includes(GITIGNORE_MARKER) || existing.includes('# LLM Project Mapper tracked files')) {
        log('→ Recommended entries UPDATED in .gitignore.\n');
      } else {
        log('→ Recommended entries APPENDED to .gitignore (original content preserved).\n');
      }
    }
  } else if (opts.dryRun) {
    log('  create (dry):   .gitignore\n');
  } else {
    fs.writeFileSync(gi, RECOMMENDED_IGNORES);
    log('→ .gitignore CREATED.\n');
  }

  const ga = path.join(CWD, '.gitattributes');
  if (!fs.existsSync(ga)) {
    if (opts.dryRun) {
      log('  create (dry):   .gitattributes');
    } else {
      fs.writeFileSync(ga, GITATTRIBUTES_CONTENT);
      log('→ .gitattributes CREATED.');
    }
  } else {
    log('→ .gitattributes left untouched (already exists).');
  }
  log('');
}

function upsertGitignore(existing) {
  const starts = [
    existing.indexOf(GITIGNORE_MARKER),
    existing.indexOf('# LLM Project Mapper tracked files'),
    existing.indexOf('# Agentic starter tracked files'),
  ].filter(index => index >= 0);

  if (starts.length === 0) {
    return existing.replace(/\s*$/, '') + '\n\n' + RECOMMENDED_IGNORES + '\n';
  }

  const start = Math.min(...starts);
  const end = existing.indexOf(GITIGNORE_END_MARKER, start);
  const before = existing.slice(0, start).replace(/\s*$/, '');
  const after = end >= 0
    ? existing.slice(end + GITIGNORE_END_MARKER.length).replace(/^\s*/, '')
    : '';

  return before + '\n\n' + RECOMMENDED_IGNORES + (after ? '\n' + after : '\n');
}

function writeFileIfMissing(relPath, content) {
  const abs = path.join(CWD, relPath);
  if (fs.existsSync(abs)) {
    log(`  preserve (exists): ${relPath}`);
    return;
  }
  if (opts.dryRun) {
    log(`  create (dry):      ${relPath}`);
    return;
  }
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  fs.writeFileSync(abs, content);
  log(`  create:            ${relPath}`);
}

function handleRuntimeScaffold() {
  const catalogStub = `${JSON.stringify({
    version: 1,
    generated_at: null,
    agents: [],
    notes: [
      'Generated from AGENTS.md entries that declare yool_id, authority, lane, and agent_terms.',
      'Refresh with build-hamt-catalog after the wrapper is installed.',
    ],
  }, null, 2)}\n`;
  const mcpServerTs = `#!/usr/bin/env node
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
    generatedAt: new Date().toISOString(),
  };
}

export async function dispatch(tuple) {
  return {
    accepted: false,
    reason: "TODO: wire tuple dispatch to the edge transport for your host runtime.",
    tuple,
    catalogPath,
  };
}

if (process.argv[1] && import.meta.url === new URL(\`file://\${process.argv[1]}\`).href) {
  const command = process.argv[2] ?? "snapshot";
  if (command === "snapshot") {
    console.log(JSON.stringify(await snapshot(), null, 2));
  } else if (command === "dispatch") {
    const tuple = process.argv[3] ? JSON.parse(process.argv[3]) : {};
    console.log(JSON.stringify(await dispatch(tuple), null, 2));
  } else {
    console.error(\`Unknown command: \${command}\`);
    process.exit(1);
  }
}
`;
  const mcpServerPy = `#!/usr/bin/env python3
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
`;

  writeFileIfMissing(path.join('.catalog', '.gitkeep'), '');
  writeFileIfMissing(path.join('.catalog', 'agents.json'), catalogStub);
  writeFileIfMissing(path.join('.receipts', '.gitkeep'), '');
  if (opts.mcpEdge) {
    writeFileIfMissing(path.join('mcp', 'server.ts'), mcpServerTs);
    writeFileIfMissing(path.join('mcp', 'server.py'), mcpServerPy);
  }
}

function looksBinary(buf) {
  const head = buf.length > 8192 ? buf.subarray(0, 8192) : buf;
  return head.includes(0);
}

function substituteInFile(file, productName, stack) {
  let content;
  try {
    const buf = fs.readFileSync(file);
    if (buf.length === 0) return false;
    if (looksBinary(buf)) return false;
    content = buf.toString('utf8');
  } catch { return false; }

  if (!/<PRODUCT_NAME>|<STACK>/.test(content)) return false;

  const next = content
    .replace(/<PRODUCT_NAME>/g, productName)
    .replace(/<STACK>/g, stack);

  if (next === content) return false;
  if (!opts.dryRun) fs.writeFileSync(file, next);
  return true;
}

function walk(dir, cb) {
  let entries;
  try { entries = fs.readdirSync(dir, { withFileTypes: true }); }
  catch { return; }
  for (const entry of entries) {
    if (WALK_SKIP_DIRS.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, cb);
    else if (entry.isFile()) cb(full);
  }
}

function substitute(productName, stack) {
  let touched = 0;
  const stamp = (file) => {
    if (substituteInFile(file, productName, stack)) touched++;
  };

  for (const dir of STARTER_DIRS) {
    const abs = path.join(CWD, dir);
    if (!fs.existsSync(abs)) continue;
    walk(abs, (file) => {
      if (TEXT_EXTS.has(path.extname(file))) stamp(file);
    });
  }

  for (const p of STARTER_GITHUB_PATTERNS) {
    const abs = path.join(CWD, p);
    if (!fs.existsSync(abs)) continue;
    const stat = fs.statSync(abs);
    if (stat.isDirectory()) walk(abs, stamp);
    else if (stat.isFile()) stamp(abs);
  }

  for (const f of STARTER_ROOT_FILES) {
    const abs = path.join(CWD, f);
    if (fs.existsSync(abs)) stamp(abs);
  }

  log(`→ ${touched} files updated (only starter-managed paths)${opts.dryRun ? ' (dry-run)' : ''}.\n`);
}

function writeMeta(productName, stack, projectMode, projectsList, existingInstructionFiles, preservedUserFiles) {
  if (opts.skipMeta) return;
  const meta = {
    product_name: productName,
    stack: stack,
    project_mode: projectMode,
    projects: projectsList,
    bootstrapped_at: new Date().toISOString(),
    starter_version: PKG.version,
    cli: '@wesleysimplicio/llm-project-mapper',
    simplicio: {
      project_map: '.simplicio/project-map.json',
      precedent_index: '.simplicio/precedent-index.json',
      architecture_inventory: '.simplicio/architecture-inventory.json',
      symbol_index: '.simplicio/symbol-index.json',
      call_graph: '.simplicio/call-graph.json',
      architecture_docs: '.simplicio/docs/',
      integration_contract: 'SIMPLICIO_INTEGRATION.md',
      update_command: 'npx @wesleysimplicio/llm-project-mapper map --incremental',
      docs_command: 'simplicio-mapper docs .',
    },
    mcp_edge_enabled: opts.mcpEdge,
    preset: opts.preset || null,
    existing_instruction_files: existingInstructionFiles,
    preserved_user_files: preservedUserFiles,
    init_must_ask: [],
    init_must_infer: ['team', 'domain', 'vision_oneliner', 'personas_beyond_dev'],
    default_persona: 'developer',
    init_must_merge: existingInstructionFiles,
    read_only_globs: [
      '**/*.razor', '**/*.cs', '**/*.csproj', '**/*.sln',
      'package.json', 'pnpm-lock.yaml', 'yarn.lock', 'package-lock.json',
      '**/*.py', '**/*.go', '**/*.rs', '**/*.java', '**/*.kt', '**/*.dart',
      '**/*.php', '**/*.rb',
    ],
  };
  const dest = path.join(CWD, '.starter-meta.json');
  if (opts.dryRun) {
    log('  write (dry):    .starter-meta.json');
    return;
  }
  fs.writeFileSync(dest, JSON.stringify(meta, null, 2) + '\n');
  log('→ .starter-meta.json saved.');
}

function ask(rl, q, def) {
  return new Promise(resolve => {
    rl.question(`${q} [${def}]: `, ans => resolve((ans || '').trim() || def));
  });
}

async function chooseCli(rl) {
  if (opts.cli) return opts.cli;
  if (opts.yes) return 'skip';

  log('==========================================');
  log('  Choose the CLI/LLM to run INIT.md');
  log('==========================================\n');
  CLI_OPTS.forEach((o, i) => {
    const mark = commandExists(o.cmd) ? '  [installed]' : '';
    log(`  [${String(i + 1).padStart(2, ' ')}] ${o.label}${mark}`);
  });
  log('');
  const resp = await ask(rl, 'Number', String(CLI_OPTS.length));
  let idx = parseInt(resp, 10);
  if (!Number.isFinite(idx) || idx < 1 || idx > CLI_OPTS.length) idx = CLI_OPTS.length;
  return CLI_OPTS[idx - 1].key;
}

function copyToClipboard(text) {
  const candidates = process.platform === 'darwin'
    ? [['pbcopy', []]]
    : process.platform === 'win32'
      ? [['clip', []]]
      : [['xclip', ['-selection', 'clipboard']], ['wl-copy', []]];
  for (const [cmd, args] of candidates) {
    try {
      const r = spawnSync(cmd, args, { input: text, stdio: ['pipe', 'ignore', 'ignore'] });
      if (r.status === 0) return true;
    } catch { /* try next */ }
  }
  return false;
}

function execHandoff(cmd, args) {
  const child = spawn(cmd, args, { stdio: 'inherit' });
  child.on('exit', (code) => process.exit(code ?? 0));
  child.on('error', (e) => {
    err(`Failed to launch ${cmd}: ${e.message}`);
    process.exit(1);
  });
}

function requireCmd(cmd, hint) {
  if (!commandExists(cmd)) {
    err(`${cmd} not installed: ${hint}`);
    process.exit(1);
  }
}

function warnDeprecatedAlias(legacy, canonical) {
  // Once-per-process stderr warning (issue #209). Never emit to stdout/JSON.
  if (global.__simplicio_deprecation_warned) return;
  global.__simplicio_deprecation_warned = true;
  err(`[deprecated] '${legacy}' is a deprecated alias of '${canonical}' (Simplicio Agent). ` +
      `Use '--cli simplicio-agent' instead. The alias is retained for compatibility and will be removed after a release window.`);
}

function handoff(cliChoice) {
  log('');
  log('==========================================');
  log(`  Handing off to: ${cliChoice}`);
  log('==========================================\n');

  switch (cliChoice) {
    case 'claude':
      requireCmd('claude', 'https://docs.claude.com/claude-code');
      return execHandoff('claude', [INIT_PROMPT]);
    case 'codex':
      requireCmd('codex', 'https://github.com/openai/codex');
      return execHandoff('codex', ['exec', INIT_PROMPT]);
    case 'copilot':
      requireCmd('gh', 'https://cli.github.com');
      if (copyToClipboard(INIT_PROMPT)) log('Prompt copied to clipboard.');
      else log('(clipboard unavailable - copy manually below)');
      log('');
      log('GitHub Copilot CLI does not run an autonomous agent loop.');
      log('Open Copilot Chat (VS Code / IDE) and paste the prompt:\n');
      log(`  ${INIT_PROMPT}\n`);
      return;
    case 'cursor':
      requireCmd('cursor-agent', 'Cursor 3.0+ required');
      return execHandoff('cursor-agent', [INIT_PROMPT]);
    case 'deepseek':
      requireCmd('aider', 'pipx install aider-chat');
      return execHandoff('aider', ['--model', 'deepseek/deepseek-coder', '--message', INIT_PROMPT]);
    case 'kimi':
      requireCmd('aider', 'pipx install aider-chat');
      return execHandoff('aider', ['--model', 'openrouter/moonshotai/kimi-k2', '--message', INIT_PROMPT]);
    case 'minimax':
      requireCmd('aider', 'pipx install aider-chat');
      return execHandoff('aider', ['--model', 'openrouter/minimax/minimax-text-01', '--message', INIT_PROMPT]);
    case 'glm':
      requireCmd('aider', 'pipx install aider-chat');
      return execHandoff('aider', ['--model', 'openrouter/z-ai/glm-4.5', '--message', INIT_PROMPT]);
    case 'hermes':
      warnDeprecatedAlias('hermes', 'simplicio-agent');
      requireCmd('hermes', 'https://github.com/NousResearch/hermes-agent');
      copyToClipboard(INIT_PROMPT);
      log('(prompt copied to clipboard as fallback)');
      return execHandoff('hermes', [INIT_PROMPT]);
    case 'simplicio-agent':
      requireCmd('simplicio-agent', 'https://github.com/wesleysimplicio/simplicio-agent');
      copyToClipboard(INIT_PROMPT);
      log('(prompt copied to clipboard as fallback)');
      return execHandoff('simplicio-agent', [INIT_PROMPT]);
    case 'openclaw':
      requireCmd('openclaw', 'npm install -g openclaw@latest');
      copyToClipboard(INIT_PROMPT);
      log('(prompt copied to clipboard as fallback)');
      return execHandoff('openclaw', [INIT_PROMPT]);
    case 'aider':
      requireCmd('aider', 'pipx install aider-chat');
      return execHandoff('aider', ['--message', INIT_PROMPT]);
    case 'other':
      if (copyToClipboard(INIT_PROMPT)) {
        log('Prompt copied to clipboard. Paste it into your CLI/agent of choice.');
      } else {
        log('(clipboard unavailable - copy the prompt below manually)');
      }
      log('\nPrompt:');
      log(`  ${INIT_PROMPT}\n`);
      return;
    case 'skip':
    default:
      log(`Skipped CLI handoff. To run INIT.md later, open your agent and paste:\n\n  ${INIT_PROMPT}\n`);
      log('Recommended next steps:');
      log('  1) Open an agent in this folder.');
      log('  2) Paste the prompt above.');
      log('  3) Review .specs/product/VISION.md, DOMAIN.md, architecture/DESIGN.md.');
      log('  4) git add -A && git commit -m "chore: bootstrap llm project mapper"\n');
      log('Docs: https://github.com/wesleysimplicio/llm-project-mapper');
      return;
  }
}

async function main() {
  maybeNotifyUpdate();
  if (path.resolve(CWD) === path.resolve(PACKAGE_ROOT)) {
    err('Refusing to scaffold into the package source directory.');
    err('Run this command from inside the project where you want the starter.');
    process.exit(2);
  }

  const projectMode  = detectProjectMode();
  const projectsList = projectMode === 'monorepo' ? buildProjectsList() : [];
  const productName  = projectMode === 'monorepo'
    ? path.basename(CWD)
    : detectProductNameIn(CWD, path.basename(CWD));
  const stack        = projectMode === 'monorepo' ? 'monorepo' : detectStack();

  log('==========================================');
  log('  LLM Project Mapper - Bootstrap (npx)');
  log(`  v${PKG.version}`);
  log('==========================================\n');
  log('Auto-detected (bootstrap will map the project immediately after copy):');
  log(`  PROJECT_MODE: ${projectMode}`);
  log(`  PRODUCT_NAME: ${productName}`);
  log(`  STACK:        ${stack}`);
  if (projectMode === 'monorepo' && projectsList.length > 0) {
    log(`  PROJECTS:     ${projectsList.length} subproject(s) detected`);
  }
  log(`  MODE:         ${opts.dryRun ? 'dry-run' : 'write'}${opts.force ? ' (force)' : ''}\n`);

  const existingInstructionFiles = detectExistingInstructionFiles();
  const preservedUserFiles = detectPreservedUserFiles();
  if (existingInstructionFiles.length > 0) {
    log('Detected pre-existing instruction files (will be preserved):');
    for (const f of existingInstructionFiles) log(`  - ${f}`);
    log('  -> INIT.md will READ them and IMPROVE in place (essence preserved).\n');
  }
  if (preservedUserFiles.length > 0) {
    log('Detected pre-existing user-owned template collisions (will be preserved):');
    for (const f of preservedUserFiles) log(`  - ${f}`);
    log('');
  }

  copyTemplate(existingInstructionFiles, preservedUserFiles);

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    await handleGitignore(rl);
    handleRuntimeScaffold();
    substitute(productName, stack);
    writeMeta(productName, stack, projectMode, projectsList, existingInstructionFiles, preservedUserFiles);
    if (!opts.dryRun) {
      autoMapProject({
        cwd: CWD,
        meta: readExistingMeta(),
        log,
      });
    }
    if (opts.telemetry === 'on' || opts.telemetry === 'off') {
      persistTelemetryChoice(opts.telemetry === 'on');
    }
    maybeSendTelemetry(productName, stack, projectMode);
    log('');

    const cliChoice = await chooseCli(rl);
    rl.close();
    handoff(cliChoice);
  } finally {
    try { rl.close(); } catch { /* already closed */ }
  }
}

main().catch(e => {
  err('Error:', e && e.stack || e);
  process.exit(1);
});
