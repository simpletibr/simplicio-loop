'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');

const ARTIFACT_SCHEMA = 'simplicio.project-map/v1';
const PRECEDENT_SCHEMA = 'simplicio.precedent-index/v1';
const ARTIFACT_VERSION = 1;

const TEXT_EXTS = new Set([
  '.md', '.txt', '.json', '.jsonc', '.yml', '.yaml', '.toml',
  '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs',
  '.py', '.go', '.rs', '.java', '.kt', '.php', '.rb', '.cs',
  '.cshtml', '.razor', '.sh', '.ps1', '.env', '',
]);

const SKIP_DIRS = new Set([
  '.git', 'node_modules', 'dist', 'build', 'out', 'coverage',
  '.next', '.nuxt', 'playwright-report', 'test-results', '.turbo',
  '.venv', 'venv', '__pycache__', '.idea', '.vscode', '.simplicio',
  '.catalog', '.receipts',
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
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full, onFile);
    } else if (entry.isFile()) {
      onFile(full);
    }
  }
}

function languageFor(file) {
  const ext = path.extname(file).toLowerCase();
  const base = path.basename(file);
  if (base === 'Dockerfile') return 'dockerfile';
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
    const language = languageFor(rel);
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
    },
  };

  const precedentIndex = {
    schema: PRECEDENT_SCHEMA,
    version: ARTIFACT_VERSION,
    generated_at: projectMap.generated_at,
    source_project_map: '.simplicio/project-map.json',
    items: buildPrecedentItems(absCwd, files),
  };

  return { projectMap, precedentIndex };
}

function writeJsonStable(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(data, null, 2) + '\n');
}

function writeMappingArtifacts({ cwd, meta = {}, incremental = false, outputDir = '.simplicio', log = () => {} }) {
  const absCwd = path.resolve(cwd || process.cwd());
  const absOut = path.resolve(absCwd, outputDir);
  const { projectMap, precedentIndex } = buildArtifacts({ cwd: absCwd, meta, incremental, outputDir });
  const projectMapPath = path.join(absOut, 'project-map.json');
  const precedentPath = path.join(absOut, 'precedent-index.json');
  writeJsonStable(projectMapPath, projectMap);
  writeJsonStable(precedentPath, precedentIndex);
  log(`→ wrote ${path.relative(absCwd, projectMapPath)} (${projectMap.files.length} files, ${projectMap.changed_files.length} changed)`);
  log(`→ wrote ${path.relative(absCwd, precedentPath)} (${precedentIndex.items.length} precedents)`);
  return { projectMapPath, precedentPath, projectMap, precedentIndex };
}

module.exports = {
  ARTIFACT_SCHEMA,
  PRECEDENT_SCHEMA,
  buildArtifacts,
  writeMappingArtifacts,
};
