'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');

// The Node mirror is not differential-parity certified against the canonical
// Python producer.  It must not masquerade as a public v1 artifact: consumers
// may opt into these private payloads only through an explicit migration seam.
const ARTIFACT_SCHEMA = 'simplicio.mapper-native/project-map/v1';
const PRECEDENT_SCHEMA = 'simplicio.mapper-native/precedent-index/v1';
const ARCHITECTURE_INVENTORY_SCHEMA = 'simplicio.mapper-native/architecture-inventory/v1';
const SYMBOL_INDEX_SCHEMA = 'simplicio.mapper-native/symbol-index/v1';
const CALL_GRAPH_SCHEMA = 'simplicio.mapper-native/call-graph/v1';
const ARTIFACT_VERSION = 1;

// Directive contract handed to any LLM that consumes mapper artifacts. The
// mapper has already done the survey work, so a downstream model must act
// directly — never deliberate, never reach the internet, and load only the
// tools/skills the task strictly requires.
const LLM_DIRECTIVES = {
  no_thinking: true,
  no_internet: true,
  tools: 'only_necessary',
  skills: 'only_necessary',
  instruction:
    'No-thinking: act directly, do not deliberate or chain-of-think. '
    + 'No-internet: do not access the network. '
    + 'Load only strictly necessary tools. Load only strictly necessary skills.',
};

const TEXT_EXTS = new Set([
  '.md', '.txt', '.json', '.jsonc', '.yml', '.yaml', '.toml',
  '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs',
  '.py', '.go', '.rs', '.java', '.kt', '.php', '.rb', '.cs',
  '.cshtml', '.razor', '.sh', '.ps1', '.env', '',
  // Tier 1/2 language support
  '.dart', '.sql', '.c', '.h', '.cc', '.cpp', '.cxx', '.hpp', '.hh',
  '.swift', '.m', '.mm', '.vue', '.svelte', '.scala',
  // Tier 3 niche/basic language support
  '.ex', '.exs', '.erl', '.hrl', '.lua', '.r', '.jl', '.pl', '.pm',
  '.html', '.htm', '.xhtml', '.css', '.scss', '.sass', '.less',
  '.eex', '.heex', '.leex', '.erb',
]);

const SKIP_DIRS = new Set([
  '.git', 'node_modules', 'dist', 'build', 'out', 'coverage',
  '.next', '.nuxt', 'playwright-report', 'test-results', '.turbo',
  '.venv', 'venv', '__pycache__', '.idea', '.vscode', '.simplicio',
  '.catalog', '.receipts', '.docusaurus',
]);

const CONFIG_FILES = new Set([
  'package.json', 'pyproject.toml', 'requirements.txt', 'go.mod', 'Cargo.toml',
  'pom.xml', 'build.gradle', 'settings.gradle', 'tsconfig.json',
  'vite.config.ts', 'next.config.js', 'angular.json', 'Dockerfile',
]);

function normalizeRel(file) {
  return file.split(path.sep).join('/');
}

function readSafe(file) {
  try {
    return fs.readFileSync(file, 'utf8');
  } catch {
    return '';
  }
}

function exists(file) {
  return fs.existsSync(file);
}

function sha256(text) {
  return crypto.createHash('sha256').update(text).digest('hex');
}

function walk(dir, onFile) {
  let entries = [];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }

  for (const entry of entries) {
    if (SKIP_DIRS.has(entry.name)) continue;
    if (
      entry.name === '_generated'
      && ['.skills', '.agents'].includes(path.basename(dir))
    ) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full, onFile);
    } else if (entry.isFile()) {
      onFile(full);
    }
  }
}

function languageFor(file, text = '') {
  const ext = path.extname(file).toLowerCase();
  const base = path.basename(file);
  if (base === 'Dockerfile') return 'dockerfile';
  if (ext === '.m') {
    if (text === '') return 'objectivec';
    return /^\s*(#\s*import|@interface|@implementation|@import\b)/m.test(text) ? 'objectivec' : 'matlab';
  }
  return {
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.mjs': 'javascript',
    '.cjs': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'typescript',
    '.py': 'python',
    '.go': 'go',
    '.rs': 'rust',
    '.java': 'java',
    '.kt': 'kotlin',
    '.php': 'php',
    '.rb': 'ruby',
    '.cs': 'csharp',
    '.cshtml': 'razor',
    '.razor': 'razor',
    '.md': 'markdown',
    '.json': 'json',
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.toml': 'toml',
    '.sh': 'shell',
    '.ps1': 'powershell',
    '.dart': 'dart',
    '.sql': 'sql',
    '.c': 'c',
    '.h': 'c',
    '.cc': 'cpp',
    '.cpp': 'cpp',
    '.cxx': 'cpp',
    '.hpp': 'cpp',
    '.hh': 'cpp',
    '.swift': 'swift',
    '.mm': 'objectivec',
    '.vue': 'vue',
    '.svelte': 'svelte',
    '.scala': 'scala',
    '.ex': 'elixir',
    '.exs': 'elixir',
    '.erl': 'erlang',
    '.hrl': 'erlang',
    '.lua': 'lua',
    '.r': 'r',
    '.jl': 'julia',
    '.pl': 'perl',
    '.pm': 'perl',
    '.html': 'html',
    '.htm': 'html',
    '.xhtml': 'xhtml',
    '.css': 'css',
    '.scss': 'scss',
    '.sass': 'sass',
    '.less': 'less',
    '.eex': 'html-template',
    '.heex': 'html-template',
    '.leex': 'html-template',
    '.erb': 'html-template',
  }[ext] || (ext ? ext.slice(1) : 'text');
}

function parseJsonSafe(file) {
  try {
    return JSON.parse(readSafe(file) || '{}');
  } catch {
    return {};
  }
}

function gitStatusMap(cwd) {
  const result = spawnSync('git', ['status', '--porcelain', '--untracked-files=all'], {
    cwd,
    encoding: 'utf8',
    timeout: 3000,
  });
  const out = new Map();
  if (result.status !== 0) return out;
  for (const line of String(result.stdout || '').split('\n')) {
    if (!line.trim()) continue;
    const status = line.slice(0, 2).trim() || 'modified';
    const raw = line.slice(3).trim();
    const file = raw.includes(' -> ') ? raw.split(' -> ').pop() : raw;
    out.set(normalizeRel(file), status);
  }
  return out;
}

function collectTextFiles(cwd) {
  const files = [];
  walk(cwd, (file) => {
    const ext = path.extname(file).toLowerCase();
    if (!TEXT_EXTS.has(ext)) return;
    try {
      if (fs.statSync(file).size > 250_000) return;
    } catch {
      return;
    }
    files.push(file);
  });
  return files.sort();
}

function parseImports(text, language) {
  const imports = new Set();
  const patterns = [];
  if (language === 'javascript' || language === 'typescript') {
    patterns.push(/import\s+[^'"]*['"]([^'"]+)['"]/g, /require\(['"]([^'"]+)['"]\)/g);
  } else if (language === 'python') {
    patterns.push(/^\s*from\s+([A-Za-z0-9_.]+)\s+import\s+/gm, /^\s*import\s+([A-Za-z0-9_.]+)/gm);
  } else if (language === 'csharp' || language === 'razor') {
    patterns.push(/^\s*using\s+([A-Za-z0-9_.]+)\s*;/gm);
  } else if (language === 'go') {
    patterns.push(/^\s*import\s+"([^"]+)"/gm);
  } else if (language === 'vue' || language === 'svelte') {
    patterns.push(/import\s+[^'"]*['"]([^'"]+)['"]/g, /require\(['"]([^'"]+)['"]\)/g);
  } else if (language === 'dart') {
    patterns.push(/^\s*import\s+['"]([^'"]+)['"]/gm);
  } else if (language === 'swift' || language === 'scala') {
    patterns.push(/^\s*import\s+([A-Za-z_][\w.]*)/gm);
  } else if (language === 'c' || language === 'cpp') {
    patterns.push(/^\s*#\s*include\s+[<"]([^>"]+)[>"]/gm);
  } else if (language === 'objectivec') {
    patterns.push(/^\s*#\s*import\s+[<"]([^>"]+)[>"]/gm, /^\s*@import\s+([A-Za-z_][\w.]*)/gm);
  } else if (language === 'elixir') {
    patterns.push(/^\s*(?:alias|import|require|use)\s+([A-Z][A-Za-z0-9_.]*)/gm);
  } else if (language === 'erlang') {
    patterns.push(/^\s*-\s*include(?:_lib)?\("([^"]+)"\)/gm, /^\s*-\s*import\(([a-zA-Z0-9_@]+)\s*,/gm);
  } else if (language === 'lua') {
    patterns.push(/require\s*\(?\s*['"]([^'"]+)['"]\s*\)?/g);
  } else if (language === 'r') {
    patterns.push(/^\s*(?:library|require)\(\s*([A-Za-z][A-Za-z0-9._]*)\s*\)/gm, /^\s*source\(\s*['"]([^'"]+)['"]\s*\)/gm);
  } else if (language === 'julia') {
    patterns.push(/^\s*(?:using|import)\s+([A-Za-z_][\w.]*)/gm, /^\s*include\(\s*['"]([^'"]+)['"]\s*\)/gm);
  } else if (language === 'perl') {
    patterns.push(/^\s*(?:use|require)\s+([A-Za-z_][A-Za-z0-9_:]*)/gm);
  } else if (language === 'matlab') {
    patterns.push(/^\s*import\s+([A-Za-z_][\w.]*)/gm);
  } else if (['css', 'scss', 'sass', 'less'].includes(language)) {
    patterns.push(/@import\s+['"]([^'"]+)['"]/g);
  }
  for (const pattern of patterns) {
    for (const match of text.matchAll(pattern)) imports.add(match[1]);
  }
  return [...imports].slice(0, 20).sort();
}

function parseSymbols(text) {
  const symbols = new Set();
  const patterns = [
    /\bclass\s+([A-Z][A-Za-z0-9_]*)/g,
    /\bfunction\s+([A-Za-z0-9_]+)/g,
    /\bexport\s+(?:async\s+)?function\s+([A-Za-z0-9_]+)/g,
    /\bexport\s+const\s+([A-Za-z0-9_]+)/g,
    /\bdef\s+([A-Za-z0-9_]+)/g,
    /\bfunc\s+([A-Za-z0-9_]+)/g,
  ];
  for (const pattern of patterns) {
    for (const match of text.matchAll(pattern)) symbols.add(match[1]);
  }
  return [...symbols].slice(0, 30).sort();
}

function rolesFor(rel, pkg) {
  const roles = new Set();
  const base = path.basename(rel);
  const noExt = base.replace(/\.[^.]+$/, '').toLowerCase();
  if (/(\b|\/)(__tests__|tests?|specs?)(\/|\b)/i.test(rel) || /\.(test|spec)\.[^.]+$/i.test(base)) {
    roles.add('test');
  }
  if (CONFIG_FILES.has(base) || /config|rc$|\.config\./i.test(base)) roles.add('config');
  const mainValue = typeof pkg.main === 'string' ? normalizeRel(pkg.main) : '';
  const binValues = typeof pkg.bin === 'string'
    ? [normalizeRel(pkg.bin)]
    : Object.values(pkg.bin || {}).filter((v) => typeof v === 'string').map(normalizeRel);
  if (mainValue === rel || binValues.includes(rel) || ['index', 'main', 'server', 'app', 'program', 'cli'].includes(noExt)) {
    roles.add('entrypoint');
  }
  if (/routes?|controllers?|pages?|app\//i.test(rel)) roles.add('route');
  if (/components?|views?/i.test(rel)) roles.add('ui');
  if (/services?|repositories?|models?|entities?/i.test(rel)) roles.add('domain');
  return [...roles].sort();
}

function importanceFor(meta) {
  let score = 0.12;
  if (meta.roles.includes('entrypoint')) score += 0.45;
  if (meta.roles.includes('test')) score += 0.25;
  if (meta.roles.includes('config')) score += 0.2;
  if (meta.roles.includes('domain')) score += 0.2;
  if (meta.imports.length) score += 0.08;
  if (meta.exports.length) score += 0.08;
  if (meta.git_status && meta.git_status !== 'clean') score += 0.2;
  return Math.min(1, Number(score.toFixed(2)));
}

function tokenWords(value) {
  return String(value || '')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .split(/[^A-Za-z0-9]+/)
    .map((v) => v.toLowerCase())
    .filter((v) => v.length > 2 && !['src', 'lib', 'test', 'tests', 'index', 'main'].includes(v));
}

function collectEntities(files) {
  const scores = new Map();
  for (const file of files) {
    for (const token of tokenWords(path.basename(file.path, path.extname(file.path)))) {
      scores.set(token, (scores.get(token) || 0) + 1);
    }
    for (const symbol of file.exports || []) {
      for (const token of tokenWords(symbol)) scores.set(token, (scores.get(token) || 0) + 2);
    }
  }
  return [...scores.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 30)
    .map(([name, score]) => ({ name, score }));
}

function collectArchitectureSignals(pkg, corpus, stack) {
  const text = `${stack}\n${JSON.stringify(pkg)}\n${corpus}`.toLowerCase();
  const checks = [
    ['nextjs', /next/],
    ['react', /react/],
    ['vue', /vue/],
    ['angular', /angular|@angular/],
    ['express', /express/],
    ['nestjs', /nestjs|@nestjs/],
    ['fastapi', /fastapi/],
    ['django', /django/],
    ['dotnet', /aspnetcore|\.csproj|dotnet/],
    ['go', /\bgo\.mod\b|\bgin\b|\bfiber\b/],
    ['rust', /cargo\.toml|actix|axum/],
    ['playwright', /playwright/],
    ['stripe', /stripe/],
    ['prisma', /prisma/],
  ];
  return checks.filter(([, rx]) => rx.test(text)).map(([name]) => name).sort();
}

function groupModules(files) {
  const groups = new Map();
  for (const file of files) {
    const first = file.path.includes('/') ? file.path.split('/')[0] : '.';
    const group = groups.get(first) || { name: first, files: [], roles: new Set() };
    group.files.push(file.path);
    for (const role of file.roles) group.roles.add(role);
    groups.set(first, group);
  }
  return [...groups.values()]
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((group) => ({
      name: group.name,
      files: group.files.slice(0, 20),
      roles: [...group.roles].sort(),
      file_count: group.files.length,
    }));
}

function detectChangedFiles(files, previousMap, statusMap, incremental) {
  const previous = new Map((previousMap.files || []).map((file) => [file.path, file]));
  const changed = new Set([...statusMap.entries()].filter(([, status]) => status !== 'clean').map(([file]) => file));
  if (incremental) {
    for (const file of files) {
      const before = previous.get(file.path);
      if (!before || before.file_hash !== file.file_hash || before.size_bytes !== file.size_bytes) {
        changed.add(file.path);
      }
    }
  }
  return [...changed].filter((file) => files.some((entry) => entry.path === file)).sort();
}

function loadPreviousMap(outputDir) {
  const target = path.join(outputDir, 'project-map.json');
  try {
    return JSON.parse(fs.readFileSync(target, 'utf8'));
  } catch {
    return {};
  }
}

function buildFileInventory(cwd, pkg, statusMap) {
  return collectTextFiles(cwd).map((abs) => {
    const rel = normalizeRel(path.relative(cwd, abs));
    const text = readSafe(abs);
    const stat = fs.statSync(abs);
    const language = languageFor(rel, text);
    const roles = rolesFor(rel, pkg);
    const imports = parseImports(text, language);
    const exports = parseSymbols(text);
    const entry = {
      path: rel,
      language,
      size_bytes: stat.size,
      last_modified: new Date(stat.mtimeMs).toISOString(),
      file_hash: sha256(text),
      git_status: statusMap.get(rel) || 'clean',
      roles,
      imports,
      exports,
    };
    entry.importance = importanceFor(entry);
    return entry;
  }).sort((a, b) => a.path.localeCompare(b.path));
}

function extractSnippet(text, lineIndex, radius = 2) {
  const lines = text.split(/\r?\n/);
  const start = Math.max(0, lineIndex - radius);
  const end = Math.min(lines.length, lineIndex + radius + 1);
  return lines.slice(start, end).join('\n').slice(0, 1200);
}

function buildPrecedentItems(cwd, files) {
  const items = [];
  for (const file of files) {
    const abs = path.join(cwd, file.path);
    const lines = readSafe(abs).split(/\r?\n/);
    const isTest = file.roles.includes('test');
    const patterns = [
      { rx: /\btest\s*\(|\bit\s*\(|\bdescribe\s*\(|\bdef\s+test_/i, type: 'test' },
      { rx: /\bclass\s+[A-Z]|\bfunction\s+\w+|\bdef\s+\w+|\bfunc\s+\w+/i, type: isTest ? 'test' : 'feature' },
      { rx: /\btry\b|\bcatch\b|\bexcept\b|\bthrow\b/i, type: 'error-handling' },
      { rx: /\brouter\.|\bapp\.get\b|\bapp\.post\b|@app\./i, type: 'route' },
    ];
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const match = patterns.find((pattern) => pattern.rx.test(line));
      if (!match) continue;
      const snippet = extractSnippet(lines.join('\n'), i);
      if (/<[A-Z][A-Z0-9_]+>/.test(snippet)) continue;
      items.push({
        id: sha256(`${file.path}:${i + 1}:${line}`).slice(0, 16),
        path: file.path,
        line: i + 1,
        language: file.language,
        change_type: match.type,
        tags: [...new Set([...file.roles, file.language, ...tokenWords(file.path)].filter(Boolean))].slice(0, 10),
        summary: `${match.type} precedent in ${file.path}`,
        snippet,
      });
      break;
    }
  }
  return items.sort((a, b) => a.path.localeCompare(b.path) || a.line - b.line).slice(0, 250);
}

function lineNumber(text, index) {
  return text.slice(0, index).split(/\r?\n/).length;
}

function symbolDefinitionsForFile(file, text) {
  const patterns = [];
  if (file.language === 'python') {
    patterns.push([/^\s*class\s+([A-Za-z_]\w*)/gm, 'class']);
    patterns.push([/^\s*def\s+([A-Za-z_]\w*)/gm, 'function']);
  } else if (['javascript', 'typescript', 'vue', 'svelte'].includes(file.language)) {
    patterns.push([/^\s*(?:export\s+)?class\s+([A-Za-z_]\w*)/gm, 'class']);
    patterns.push([/^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)/gm, 'function']);
    patterns.push([
      /^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_]\w*)\s*=>/gm,
      'function',
    ]);
  } else if (file.language === 'dart') {
    patterns.push([/^\s*(?:abstract\s+)?class\s+([A-Za-z_]\w*)/gm, 'class']);
    patterns.push([/^\s*enum\s+([A-Za-z_]\w*)/gm, 'enum']);
    patterns.push([/^\s*mixin\s+([A-Za-z_]\w*)/gm, 'mixin']);
    patterns.push([/^[ \t]*(?:[A-Za-z_][\w<>,? \t]*?[ \t]+)?(?!(?:if|for|while|switch|else|catch|finally|return|new|await|yield)\b)([a-z_]\w*)\s*\([^)]*\)\s*(?:async\s*)?\{/gm, 'function']);
  } else if (file.language === 'swift') {
    patterns.push([/^\s*(?:public\s+|private\s+|internal\s+|open\s+|final\s+)*(?:class|struct|enum|protocol|extension|actor)\s+([A-Za-z_]\w*)/gm, 'class']);
    patterns.push([/^\s*(?:public\s+|private\s+|internal\s+|static\s+|override\s+)*func\s+([A-Za-z_]\w*)/gm, 'function']);
  } else if (file.language === 'objectivec') {
    patterns.push([/^\s*@interface\s+([A-Za-z_]\w*)/gm, 'class']);
    patterns.push([/^\s*@implementation\s+([A-Za-z_]\w*)/gm, 'class']);
    patterns.push([/^\s*[-+]\s*\([^)]*\)\s*([A-Za-z_]\w*)/gm, 'method']);
  } else if (file.language === 'cpp') {
    patterns.push([/^\s*(?:class|struct)\s+([A-Za-z_]\w*)/gm, 'class']);
    patterns.push([/^[ \t]*(?:[A-Za-z_][\w:<>, \t*&]*?[ \t]+)([A-Za-z_]\w*)\s*\([^;{]*\)\s*(?:const\s*)?\{/gm, 'function']);
  } else if (file.language === 'c') {
    patterns.push([/^\s*struct\s+([A-Za-z_]\w*)/gm, 'struct']);
    patterns.push([/^[ \t]*(?:[A-Za-z_][\w \t*]*?[ \t]+)\**([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{/gm, 'function']);
  } else if (file.language === 'scala') {
    patterns.push([/^\s*(?:case\s+)?(?:class|object|trait)\s+([A-Za-z_]\w*)/gm, 'class']);
    patterns.push([/^\s*def\s+([A-Za-z_]\w*)/gm, 'function']);
  } else if (file.language === 'sql') {
    patterns.push([/\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:["`]?[A-Za-z_]\w*["`]?\.)?["`]?([A-Za-z_]\w*)["`]?/gi, 'table']);
    patterns.push([/\bCREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:["`]?[A-Za-z_]\w*["`]?\.)?["`]?([A-Za-z_]\w*)["`]?/gi, 'view']);
    patterns.push([/\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE)\s+(?:["`]?[A-Za-z_]\w*["`]?\.)?["`]?([A-Za-z_]\w*)["`]?/gi, 'function']);
  } else if (file.language === 'elixir') {
    patterns.push([/^\s*defmodule\s+([A-Z][A-Za-z0-9_.]*)/gm, 'module']);
    patterns.push([/^\s*defp?\s+([a-z_]\w*[!?]?)/gm, 'function']);
    patterns.push([/^\s*defmacro(?:p)?\s+([a-z_]\w*[!?]?)/gm, 'macro']);
  } else if (file.language === 'erlang') {
    patterns.push([/^\s*-\s*module\(([a-zA-Z0-9_@]+)\)\./gm, 'module']);
    patterns.push([/^\s*([a-z][A-Za-z0-9_]*)\s*\([^)]*\)\s*->/gm, 'function']);
  } else if (file.language === 'lua') {
    patterns.push([/^\s*(?:local\s+)?function\s+([A-Za-z_]\w*(?:[:.][A-Za-z_]\w*)?)/gm, 'function']);
  } else if (file.language === 'r') {
    patterns.push([/^\s*([A-Za-z.][A-Za-z0-9._]*)\s*(?:<-|=)\s*function\s*\(/gm, 'function']);
  } else if (file.language === 'julia') {
    patterns.push([/^\s*module\s+([A-Z][A-Za-z0-9_]*)/gm, 'module']);
    patterns.push([/^\s*(?:mutable\s+)?struct\s+([A-Z][A-Za-z0-9_]*)/gm, 'class']);
    patterns.push([/^\s*function\s+([A-Za-z_]\w*[!?]?)/gm, 'function']);
    patterns.push([/^\s*([A-Za-z_]\w*[!?]?)\s*\([^)]*\)\s*=/gm, 'function']);
  } else if (file.language === 'perl') {
    patterns.push([/^\s*package\s+([A-Za-z_][A-Za-z0-9_:]*)\s*;/gm, 'module']);
    patterns.push([/^\s*sub\s+([A-Za-z_]\w*)/gm, 'function']);
  } else if (file.language === 'matlab') {
    patterns.push([/^\s*classdef\s+([A-Z][A-Za-z0-9_]*)/gm, 'class']);
    patterns.push([/^\s*function\s+(?:\[[^\]]+\]\s*=|[A-Za-z_]\w*\s*=)?\s*([A-Za-z_]\w*)\s*\(/gm, 'function']);
  } else if (['css', 'scss', 'sass', 'less'].includes(file.language)) {
    patterns.push([/^\s*\.([A-Za-z_][\w-]*)\b/gm, 'class']);
    patterns.push([/^\s*#([A-Za-z_][\w-]*)\b/gm, 'id']);
  } else if (['html', 'xhtml', 'html-template'].includes(file.language)) {
    patterns.push([/\bid\s*=\s*['"]([A-Za-z_][\w:-]*)['"]/gi, 'id']);
    patterns.push([/<([A-Z][A-Za-z0-9:_-]*)\b/g, 'component']);
  } else if (file.language === 'csharp' || file.language === 'razor') {
    patterns.push([/^\s*(?:public\s+|private\s+|protected\s+|internal\s+)?(?:sealed\s+|static\s+|partial\s+)?class\s+([A-Za-z_]\w*)/gm, 'class']);
    patterns.push([
      /^\s*(?:public|private|protected|internal)\s+(?:static\s+)?(?:async\s+)?[A-Za-z0-9_<>,[\]\s?.]+\s+([A-Za-z_]\w*)\s*\(/gm,
      'method',
    ]);
  } else if (['go', 'rust', 'java', 'kotlin', 'php', 'ruby'].includes(file.language)) {
    patterns.push([/\bclass\s+([A-Za-z_]\w*)/g, 'class']);
    patterns.push([/\bfunction\s+([A-Za-z_]\w*)/g, 'function']);
    patterns.push([/\bdef\s+([A-Za-z_]\w*)/g, 'function']);
  } else {
    return [];
  }

  const symbols = [];
  const seen = new Set();
  for (const [pattern, kind] of patterns) {
    for (const match of text.matchAll(pattern)) {
      const name = match[1];
      const line = lineNumber(text, match.index || 0);
      const key = `${name}:${line}:${kind}`;
      if (seen.has(key)) continue;
      seen.add(key);
      symbols.push({
        name,
        qualified_name: `${file.path}::${name}`,
        kind,
        language: file.language,
        defined_in: file.path,
        line,
        evidence: { file: file.path, line },
      });
    }
  }
  return symbols.sort((a, b) => a.defined_in.localeCompare(b.defined_in) || a.line - b.line || a.name.localeCompare(b.name));
}

function layersForFile(file) {
  const rel = file.path.toLowerCase();
  const base = path.basename(rel);
  const layers = new Set(file.roles || []);
  if (rel.includes('controller')) layers.add('controller');
  if (rel.includes('service')) layers.add('service');
  if (rel.includes('repository') || rel.includes('repositories') || base.includes('repo')) layers.add('repository');
  if (rel.includes('model') || rel.includes('entity') || rel.includes('schema')) layers.add('model');
  if (rel.includes('route') || rel.includes('router')) layers.add('route');
  if (rel.startsWith('scripts/')) layers.add('script');
  if (rel.startsWith('docs/') || file.language === 'markdown') layers.add('documentation');
  if (!layers.size) {
    layers.add(['python', 'javascript', 'typescript', 'csharp', 'go', 'rust', 'dart', 'swift', 'objectivec', 'c', 'cpp', 'scala', 'vue', 'svelte', 'elixir', 'erlang', 'lua', 'r', 'julia', 'perl', 'matlab'].includes(file.language) ? 'code' : 'asset');
  }
  return [...layers].sort();
}

function responsibilityForFile(file, layers) {
  if (layers.includes('controller') || layers.includes('route')) return 'Defines inbound request or routing behavior.';
  if (layers.includes('service')) return 'Holds application/service orchestration logic.';
  if (layers.includes('repository')) return 'Encapsulates persistence or data access behavior.';
  if (layers.includes('model')) return 'Defines domain, data or schema structures.';
  if (layers.includes('test')) return 'Verifies project behavior through automated tests.';
  if (layers.includes('entrypoint')) return 'Starts a CLI, runtime or package entrypoint.';
  if (layers.includes('config')) return 'Configures tooling, build, runtime or packaging behavior.';
  if (layers.includes('documentation')) return 'Documents product, architecture, operation or contributor workflow.';
  if (file.exports && file.exports.length) return `Defines exported symbols: ${file.exports.slice(0, 5).join(', ')}.`;
  return 'Participates in the project implementation; inspect imports and symbols for exact usage.';
}

function moduleNameForPath(rel) {
  return rel.includes('/') ? rel.split('/')[0] : '.';
}

function buildSymbolIndex(cwd, files, generatedAt) {
  const symbols = [];
  for (const file of files) {
    symbols.push(...symbolDefinitionsForFile(file, readSafe(path.join(cwd, file.path))));
  }
  return {
    schema: SYMBOL_INDEX_SCHEMA,
    version: ARTIFACT_VERSION,
    generated_at: generatedAt,
    root: cwd.split(path.sep).join('/'),
    symbols,
    counts: {
      symbols: symbols.length,
      files: new Set(symbols.map((item) => item.defined_in)).size,
    },
  };
}

function stripKnownExt(rel) {
  const ext = path.posix.extname(rel);
  return ext ? rel.slice(0, -ext.length) : rel;
}

function candidateImportTargets(importName, sourceFile, knownPaths) {
  if (!importName || importName.startsWith('@')) return [];
  let base = importName;
  if (importName.startsWith('.')) {
    base = path.posix.normalize(path.posix.join(path.posix.dirname(sourceFile), importName));
  } else if (importName.includes('.')) {
    base = importName.replace(/\./g, '/');
  }
  base = base.replace(/^\/+/, '');
  const candidates = [base];
  for (const ext of ['.py', '.js', '.jsx', '.ts', '.tsx', '.cs', '.go', '.rs']) candidates.push(`${base}${ext}`);
  for (const ext of ['.py', '.js', '.ts', '.tsx']) candidates.push(`${base}/index${ext}`);
  candidates.push(`${base}/__init__.py`);
  const direct = candidates.filter((candidate) => knownPaths.has(candidate));
  if (direct.length) return direct;
  const normalized = stripKnownExt(base);
  return [...knownPaths].filter((known) => {
    const knownBase = stripKnownExt(known);
    return knownBase === normalized || knownBase.endsWith(`/${normalized}`);
  }).sort();
}

const CALL_SKIP_NAMES = new Set([
  'if', 'for', 'while', 'switch', 'catch', 'return', 'function', 'class', 'def',
  'print', 'len', 'str', 'int', 'float', 'bool', 'list', 'dict', 'set', 'tuple',
]);
const CALL_GRAPH_LANGUAGES = new Set([
  'python', 'javascript', 'typescript', 'csharp', 'razor', 'go', 'rust', 'java', 'kotlin', 'php', 'ruby',
  'dart', 'swift', 'objectivec', 'c', 'cpp', 'scala', 'vue', 'svelte',
  'elixir', 'erlang', 'lua', 'r', 'julia', 'perl', 'matlab',
]);

function callExpressions(text) {
  const calls = [];
  for (const match of text.matchAll(/\b([A-Za-z_]\w*)\s*\(/g)) {
    if (CALL_SKIP_NAMES.has(match[1])) continue;
    calls.push({ name: match[1], line: lineNumber(text, match.index || 0) });
  }
  return calls;
}

function nearestSymbol(symbols, file, line) {
  return symbols
    .filter((item) => item.defined_in === file && item.line <= line)
    .sort((a, b) => a.line - b.line)
    .pop() || null;
}

function buildCallGraph(cwd, files, symbolIndex, generatedAt) {
  const knownPaths = new Set(files.map((file) => file.path));
  const symbols = symbolIndex.symbols || [];
  const symbolsByName = new Map();
  for (const symbol of symbols) {
    if (!symbolsByName.has(symbol.name)) symbolsByName.set(symbol.name, []);
    symbolsByName.get(symbol.name).push(symbol);
  }
  const edges = [];
  const seen = new Set();
  const addEdge = (edge) => {
    const key = `${edge.type}:${edge.source_file}:${edge.target_file}:${edge.target_symbol || edge.import || ''}`;
    if (seen.has(key)) return;
    seen.add(key);
    edges.push(edge);
  };

  for (const file of files) {
    for (const imported of file.imports || []) {
      for (const target of candidateImportTargets(imported, file.path, knownPaths).slice(0, 3)) {
        if (target === file.path) continue;
        addEdge({
          type: 'imports',
          source_file: file.path,
          target_file: target,
          import: imported,
          confidence: imported.startsWith('.') ? 0.82 : 0.65,
        });
      }
    }
    if (CALL_GRAPH_LANGUAGES.has(file.language)) {
      const text = readSafe(path.join(cwd, file.path));
      for (const call of callExpressions(text)) {
        for (const target of (symbolsByName.get(call.name) || []).slice(0, 3)) {
          if (target.defined_in === file.path && target.line === call.line) continue;
          const caller = nearestSymbol(symbols, file.path, call.line);
          addEdge({
            type: 'calls',
            source_file: file.path,
            source_symbol: caller ? caller.qualified_name : null,
            target_file: target.defined_in,
            target_symbol: target.qualified_name,
            line: call.line,
            confidence: caller ? 0.58 : 0.48,
          });
        }
      }
    }
  }

  const sortedEdges = edges.sort((a, b) => (
    (a.source_file || '').localeCompare(b.source_file || '')
    || (a.target_file || '').localeCompare(b.target_file || '')
    || (a.type || '').localeCompare(b.type || '')
    || (a.target_symbol || a.import || '').localeCompare(b.target_symbol || b.import || '')
  ));
  return {
    schema: CALL_GRAPH_SCHEMA,
    version: ARTIFACT_VERSION,
    generated_at: generatedAt,
    source_symbol_index: '.simplicio/symbol-index.json',
    edges: sortedEdges.slice(0, 1000),
    counts: {
      edges: edges.length,
      imports: edges.filter((item) => item.type === 'imports').length,
      calls: edges.filter((item) => item.type === 'calls').length,
    },
  };
}

function buildArchitectureInventory(cwd, projectMap, files, symbolIndex, callGraph, generatedAt) {
  const symbolsByFile = new Map();
  for (const symbol of symbolIndex.symbols || []) {
    if (!symbolsByFile.has(symbol.defined_in)) symbolsByFile.set(symbol.defined_in, []);
    symbolsByFile.get(symbol.defined_in).push(symbol);
  }
  const modules = new Map();
  const layers = new Map();
  const inventoryFiles = [];

  for (const file of files) {
    const fileLayers = layersForFile(file);
    const fileSymbols = symbolsByFile.get(file.path) || [];
    const moduleName = moduleNameForPath(file.path);
    inventoryFiles.push({
      path: file.path,
      language: file.language,
      module: moduleName,
      layers: fileLayers,
      roles: file.roles,
      imports: file.imports,
      symbols: fileSymbols.map((item) => item.name),
      summary: responsibilityForFile(file, fileLayers),
      evidence: [{ file: file.path }],
    });
    if (!modules.has(moduleName)) {
      modules.set(moduleName, { name: moduleName, files: [], layers: new Set(), entryPoints: [], tests: [], publicSymbols: [] });
    }
    const module = modules.get(moduleName);
    module.files.push(file.path);
    fileLayers.forEach((layer) => module.layers.add(layer));
    if (fileLayers.includes('entrypoint')) module.entryPoints.push(file.path);
    if (fileLayers.includes('test')) module.tests.push(file.path);
    module.publicSymbols.push(...fileSymbols.map((item) => item.name));
    for (const layerName of fileLayers) {
      if (!layers.has(layerName)) layers.set(layerName, { name: layerName, files: [], modules: new Set() });
      layers.get(layerName).files.push(file.path);
      layers.get(layerName).modules.add(moduleName);
    }
  }

  const moduleEntries = [...modules.values()].sort((a, b) => a.name.localeCompare(b.name)).map((module) => ({
    name: module.name,
    summary: `Groups ${module.files.length} files across ${module.layers.size} detected layers.`,
    file_count: module.files.length,
    files: module.files.slice(0, 80),
    layers: [...module.layers].sort(),
    entry_points: module.entryPoints.sort(),
    tests: module.tests.sort(),
    public_symbols: [...new Set(module.publicSymbols)].sort().slice(0, 40),
    evidence: module.files.slice(0, 10).map((file) => ({ file })),
  }));
  const layerEntries = [...layers.values()].sort((a, b) => a.name.localeCompare(b.name)).map((layer) => ({
    name: layer.name,
    file_count: layer.files.length,
    files: layer.files.sort().slice(0, 100),
    modules: [...layer.modules].sort(),
    evidence: layer.files.sort().slice(0, 10).map((file) => ({ file })),
  }));
  return {
    schema: ARCHITECTURE_INVENTORY_SCHEMA,
    version: ARTIFACT_VERSION,
    generated_at: generatedAt,
    root: cwd.split(path.sep).join('/'),
    source_project_map: '.simplicio/project-map.json',
    source_symbol_index: '.simplicio/symbol-index.json',
    source_call_graph: '.simplicio/call-graph.json',
    product: projectMap.product,
    architecture: projectMap.architecture,
    modules: moduleEntries,
    layers: layerEntries,
    files: inventoryFiles.sort((a, b) => a.path.localeCompare(b.path)),
    relationships: (callGraph.edges || []).slice(0, 250),
    coverage: {
      files: files.length,
      modules: moduleEntries.length,
      layers: layerEntries.length,
      symbols: (symbolIndex.symbols || []).length,
      relationships: (callGraph.edges || []).length,
      tests: (projectMap.test_files || []).length,
    },
    notes: [
      'Generated from deterministic repository inspection.',
      'Relationship confidence below 1.0 means the edge is heuristic and should be reviewed before making broad claims.',
    ],
  };
}

function buildArtifacts({ cwd, meta = {}, incremental = false, outputDir = '.simplicio' }) {
  const absCwd = path.resolve(cwd || process.cwd());
  const absOut = path.resolve(absCwd, outputDir);
  const pkg = parseJsonSafe(path.join(absCwd, 'package.json'));
  const statusMap = gitStatusMap(absCwd);
  const previousMap = loadPreviousMap(absOut);
  const files = buildFileInventory(absCwd, pkg, statusMap);
  const corpus = files.slice(0, 80).map((file) => readSafe(path.join(absCwd, file.path)).slice(0, 3000)).join('\n');
  const changedFiles = detectChangedFiles(files, previousMap, statusMap, incremental);
  const stack = meta.stack || pkg.type || 'unknown';
  const productName = meta.product_name || pkg.name || path.basename(absCwd);
  const architectureSignals = collectArchitectureSignals(pkg, corpus, stack);

  const projectMap = {
    schema: ARTIFACT_SCHEMA,
    version: ARTIFACT_VERSION,
    generated_at: new Date().toISOString(),
    update_mode: incremental ? 'incremental' : 'full',
    product: {
      name: productName,
      stack,
      project_mode: meta.project_mode || 'root',
    },
    files,
    entry_points: files.filter((file) => file.roles.includes('entrypoint')).map((file) => file.path),
    test_files: files.filter((file) => file.roles.includes('test')).map((file) => file.path),
    config_files: files.filter((file) => file.roles.includes('config')).map((file) => file.path),
    modules: groupModules(files),
    entities: collectEntities(files),
    architecture: {
      signals: architectureSignals,
      system_type: meta.project_mode === 'monorepo' ? 'monorepo' : (architectureSignals.includes('react') || architectureSignals.includes('nextjs') ? 'web' : 'library-or-service'),
    },
    dependencies: {
      package_manager: exists(path.join(absCwd, 'pnpm-lock.yaml')) ? 'pnpm' : exists(path.join(absCwd, 'yarn.lock')) ? 'yarn' : 'npm',
      manifest: pkg.name ? 'package.json' : null,
      runtime: Object.keys(pkg.dependencies || {}).sort(),
      dev: Object.keys(pkg.devDependencies || {}).sort(),
    },
    recent_changes: changedFiles.map((file) => ({ path: file, status: statusMap.get(file) || 'modified' })),
    changed_files: changedFiles,
    integration: {
      dev_cli_mapper: 'read .simplicio/project-map.json, then use .simplicio/precedent-index.json for task-specific examples',
      contract: 'SIMPLICIO_INTEGRATION.md',
      llm_directives: LLM_DIRECTIVES,
    },
  };

  const precedentIndex = {
    schema: PRECEDENT_SCHEMA,
    version: ARTIFACT_VERSION,
    generated_at: projectMap.generated_at,
    source_project_map: '.simplicio/project-map.json',
    items: buildPrecedentItems(absCwd, files),
  };

  const symbolIndex = buildSymbolIndex(absCwd, files, projectMap.generated_at);
  const callGraph = buildCallGraph(absCwd, files, symbolIndex, projectMap.generated_at);
  const architectureInventory = buildArchitectureInventory(
    absCwd,
    projectMap,
    files,
    symbolIndex,
    callGraph,
    projectMap.generated_at,
  );

  return { projectMap, precedentIndex, architectureInventory, symbolIndex, callGraph };
}

function writeJsonStable(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2) + '\n');
  fs.renameSync(tmp, file);
}

function writeMappingArtifacts({ cwd, meta = {}, incremental = false, outputDir = '.simplicio', log = () => {} }) {
  const absCwd = path.resolve(cwd || process.cwd());
  const absOut = path.resolve(absCwd, outputDir);
  const {
    projectMap,
    precedentIndex,
    architectureInventory,
    symbolIndex,
    callGraph,
  } = buildArtifacts({ cwd: absCwd, meta, incremental, outputDir });
  const projectMapPath = path.join(absOut, 'project-map.json');
  const precedentPath = path.join(absOut, 'precedent-index.json');
  const architectureInventoryPath = path.join(absOut, 'architecture-inventory.json');
  const symbolIndexPath = path.join(absOut, 'symbol-index.json');
  const callGraphPath = path.join(absOut, 'call-graph.json');
  writeJsonStable(projectMapPath, projectMap);
  writeJsonStable(precedentPath, precedentIndex);
  writeJsonStable(architectureInventoryPath, architectureInventory);
  writeJsonStable(symbolIndexPath, symbolIndex);
  writeJsonStable(callGraphPath, callGraph);
  log(`→ wrote ${path.relative(absCwd, projectMapPath)} (${projectMap.files.length} files, ${projectMap.changed_files.length} changed)`);
  log(`→ wrote ${path.relative(absCwd, precedentPath)} (${precedentIndex.items.length} precedents)`);
  log(`→ wrote ${path.relative(absCwd, architectureInventoryPath)} (${architectureInventory.coverage.modules} modules, ${architectureInventory.coverage.layers} layers)`);
  log(`→ wrote ${path.relative(absCwd, symbolIndexPath)} (${symbolIndex.counts.symbols} symbols)`);
  log(`→ wrote ${path.relative(absCwd, callGraphPath)} (${callGraph.counts.edges} relationships)`);
  return {
    projectMapPath,
    precedentPath,
    architectureInventoryPath,
    symbolIndexPath,
    callGraphPath,
    projectMap,
    precedentIndex,
    architectureInventory,
    symbolIndex,
    callGraph,
  };
}

module.exports = {
  ARTIFACT_SCHEMA,
  PRECEDENT_SCHEMA,
  ARCHITECTURE_INVENTORY_SCHEMA,
  SYMBOL_INDEX_SCHEMA,
  CALL_GRAPH_SCHEMA,
  buildArtifacts,
  writeMappingArtifacts,
};
