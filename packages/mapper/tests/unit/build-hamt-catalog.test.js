'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const NODE = process.execPath;
const WRAPPER = path.resolve(__dirname, '..', '..', 'bin', 'build-hamt-catalog');
const CLI = path.resolve(__dirname, '..', '..', 'bin', 'cli.js');

function mkTmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'lpm-hamt-'));
}

function rmTmp(dir) {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch {
    // ignore
  }
}

function writeFile(dir, rel, content) {
  const full = path.join(dir, rel);
  fs.mkdirSync(path.dirname(full), { recursive: true });
  fs.writeFileSync(full, content);
}

const AGENTS_FIXTURE = `# Agents

### Dev Agent
- yool_id: \`agent.dev.python.v1\`
- authority: dev
- lane: fast
- agent_terms:
    cpu_quota_pct: 60
    disk_quota_mb: 100
    timeout_s: 300

### Review Agent
- yool_id: \`agent.review.docs.v1\`
- authority: review
- lane: background
- agent_terms:
    cpu_quota_pct: 20
    disk_quota_mb: 25
`;

test('wrapper builds .catalog/agents.json from AGENTS.md', () => {
  const dir = mkTmp();
  try {
    writeFile(dir, 'AGENTS.md', AGENTS_FIXTURE);
    const res = spawnSync(NODE, [WRAPPER, dir], {
      cwd: dir,
      encoding: 'utf8',
      timeout: 30000,
    });
    assert.equal(res.status, 0, res.stderr);
    const outputPath = path.join(dir, '.catalog', 'agents.json');
    assert.equal(fs.existsSync(outputPath), true);
    const catalog = JSON.parse(fs.readFileSync(outputPath, 'utf8'));
    assert.equal(catalog.schema, 'yool-catalog/v1');
    assert.equal(catalog.stats.entries, 2);
    assert.equal(catalog.entries[0].yool_id, 'agent.dev.python.v1');
    assert.deepEqual(catalog.entries[0].hash.slots.length, 6);
    assert.match(res.stdout, /wrote/);
  } finally {
    rmTmp(dir);
  }
});

test('cli subcommand proxies to build-hamt-catalog', () => {
  const dir = mkTmp();
  try {
    writeFile(dir, 'AGENTS.md', AGENTS_FIXTURE);
    const res = spawnSync(NODE, [CLI, 'build-hamt-catalog', dir], {
      cwd: dir,
      encoding: 'utf8',
      timeout: 30000,
    });
    assert.equal(res.status, 0, res.stderr);
    const outputPath = path.join(dir, '.catalog', 'agents.json');
    assert.equal(fs.existsSync(outputPath), true);
    const catalog = JSON.parse(fs.readFileSync(outputPath, 'utf8'));
    assert.equal(catalog.stats.parsed_agents, 2);
  } finally {
    rmTmp(dir);
  }
});

test('wrapper reports actionable error when python is unavailable', () => {
  const dir = mkTmp();
  try {
    writeFile(dir, 'AGENTS.md', AGENTS_FIXTURE);
    const res = spawnSync(NODE, [WRAPPER, dir], {
      cwd: dir,
      encoding: 'utf8',
      env: { ...process.env, PATH: '' },
      timeout: 30000,
    });
    assert.equal(res.status, 2);
    assert.match(res.stderr, /Install python3, or use the Windows py launcher/i);
  } finally {
    rmTmp(dir);
  }
});
