'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const { autoMapProject } = require('../../bin/auto-map');

const CLI = path.resolve(__dirname, '..', '..', 'bin', 'cli.js');
const NODE = process.execPath;

function mkTmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'mapper-artifacts-'));
}

function rmTmp(dir) {
  fs.rmSync(dir, { recursive: true, force: true });
}

function writeFile(dir, rel, content) {
  const file = path.join(dir, rel);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, content);
}

function readJson(dir, rel) {
  return JSON.parse(fs.readFileSync(path.join(dir, rel), 'utf8'));
}

test('autoMapProject emits rich project-map and precedent-index artifacts', () => {
  const dir = mkTmp();
  try {
    writeFile(dir, 'package.json', JSON.stringify({
      name: 'artifact-host',
      scripts: { test: 'node --test', lint: 'node scripts/lint.js' },
      dependencies: { express: '^4.0.0' },
    }));
    writeFile(dir, 'src/server.js', "const express = require('express');\nfunction startServer() {}\nmodule.exports = { startServer };\n");
    writeFile(dir, 'src/services/user.service.js', "function listUsers() { return []; }\nmodule.exports = { listUsers };\n");
    writeFile(dir, 'tests/server.test.js', "const { test } = require('node:test');\ntest('starts server', () => {});\n");
    writeFile(dir, '.starter-meta.json', JSON.stringify({
      product_name: 'Artifact Host',
      stack: 'node-express',
      project_mode: 'root',
    }));

    autoMapProject({
      cwd: dir,
      meta: { product_name: 'Artifact Host', stack: 'node-express', project_mode: 'root' },
      log: () => {},
    });

    const projectMap = readJson(dir, '.simplicio/project-map.json');
    const precedentIndex = readJson(dir, '.simplicio/precedent-index.json');
    const architectureInventory = readJson(dir, '.simplicio/architecture-inventory.json');
    const symbolIndex = readJson(dir, '.simplicio/symbol-index.json');
    const callGraph = readJson(dir, '.simplicio/call-graph.json');

    assert.equal(projectMap.schema, 'simplicio.project-map/v1');
    assert.equal(projectMap.product.name, 'Artifact Host');
    assert.ok(projectMap.files.some((file) => file.path === 'src/server.js' && file.language === 'javascript'));
    assert.ok(projectMap.entry_points.includes('src/server.js'));
    assert.ok(projectMap.test_files.includes('tests/server.test.js'));
    assert.ok(projectMap.architecture.signals.includes('express'));
    assert.ok(projectMap.entities.some((entity) => entity.name === 'server'));
    assert.equal(precedentIndex.schema, 'simplicio.precedent-index/v1');
    assert.ok(precedentIndex.items.some((item) => item.path === 'tests/server.test.js' && item.change_type === 'test'));
    assert.equal(architectureInventory.schema, 'simplicio.architecture-inventory/v1');
    assert.equal(symbolIndex.schema, 'simplicio.symbol-index/v1');
    assert.equal(callGraph.schema, 'simplicio.call-graph/v1');
    assert.ok(architectureInventory.layers.some((layer) => layer.name === 'service'));
    assert.ok(symbolIndex.symbols.some((symbol) => symbol.name === 'listUsers'));
  } finally {
    rmTmp(dir);
  }
});

test('map command updates artifacts and records incremental changed files', () => {
  const dir = mkTmp();
  try {
    writeFile(dir, 'package.json', JSON.stringify({ name: 'incremental-host', scripts: { test: 'node --test' } }));
    writeFile(dir, 'src/index.js', 'export function run() { return 1; }\n');

    let res = spawnSync(NODE, [CLI, 'map', '--root', dir, '--stack', 'node', '--product-name', 'Incremental Host'], {
      encoding: 'utf8',
      timeout: 15000,
    });
    assert.equal(res.status, 0, res.stderr);
    assert.match(res.stdout, /project-map\.json/);

    writeFile(dir, 'src/index.js', 'export function run() { return 2; }\n');
    res = spawnSync(NODE, [CLI, 'map', '--root', dir, '--stack', 'node', '--product-name', 'Incremental Host', '--incremental'], {
      encoding: 'utf8',
      timeout: 15000,
    });
    assert.equal(res.status, 0, res.stderr);

    const projectMap = readJson(dir, '.simplicio/project-map.json');
    assert.equal(projectMap.update_mode, 'incremental');
    assert.ok(projectMap.changed_files.includes('src/index.js'));
  } finally {
    rmTmp(dir);
  }
});

test('map command marks untracked files inside new directories', () => {
  const dir = mkTmp();
  try {
    spawnSync('git', ['init'], { cwd: dir, encoding: 'utf8', timeout: 15000 });
    writeFile(dir, 'package.json', JSON.stringify({ name: 'untracked-host' }));
    writeFile(dir, 'src/new/index.js', 'export function run() { return 1; }\n');

    const res = spawnSync(NODE, [CLI, 'map', '--root', dir, '--stack', 'node', '--product-name', 'Untracked Host', '--incremental'], {
      encoding: 'utf8',
      timeout: 15000,
    });
    assert.equal(res.status, 0, res.stderr);

    const projectMap = readJson(dir, '.simplicio/project-map.json');
    const entry = projectMap.files.find((file) => file.path === 'src/new/index.js');
    assert.equal(entry.git_status, '??');
    assert.ok(projectMap.changed_files.includes('src/new/index.js'));
    assert.deepEqual(
      projectMap.recent_changes.find((item) => item.path === 'src/new/index.js'),
      { path: 'src/new/index.js', status: '??' },
    );
  } finally {
    rmTmp(dir);
  }
});

test('starter metadata includes the simplicio integration contract pointer', () => {
  const dir = mkTmp();
  try {
    writeFile(dir, 'package.json', JSON.stringify({ name: 'meta-host' }));
    const res = spawnSync(NODE, [CLI, '--yes', '--cli', 'skip', '--append-gitignore', 'no', '--no-update-check'], {
      cwd: dir,
      encoding: 'utf8',
      timeout: 20000,
    });
    assert.equal(res.status, 0, res.stderr);
    const meta = readJson(dir, '.starter-meta.json');
    assert.equal(meta.simplicio.project_map, '.simplicio/project-map.json');
    assert.equal(meta.simplicio.precedent_index, '.simplicio/precedent-index.json');
    assert.equal(meta.simplicio.architecture_inventory, '.simplicio/architecture-inventory.json');
    assert.equal(meta.simplicio.symbol_index, '.simplicio/symbol-index.json');
    assert.equal(meta.simplicio.call_graph, '.simplicio/call-graph.json');
    assert.equal(meta.simplicio.architecture_docs, '.simplicio/docs/');
    assert.equal(meta.simplicio.integration_contract, 'SIMPLICIO_INTEGRATION.md');
    assert.equal(meta.simplicio.docs_command, 'simplicio-mapper docs .');
  } finally {
    rmTmp(dir);
  }
});
