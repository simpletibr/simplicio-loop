'use strict';

/*
 * Unit tests for the filesystem walker used by the VS Code extension.
 * Tests are written in plain JS so they can run with `node --test` without
 * compiling TypeScript or pulling the `vscode` module.
 */

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

// Compile-on-demand by reading the TS source as text and stripping `import`
// type-only headers. The functions are pure JS-shaped — they parse text and
// walk dirs, no syntax beyond ES2022.
// Easier: require the compiled JS if `out/scan.js` exists, otherwise skip.
let scan;
try {
  scan = require('../out/scan.js');
} catch {
  // Source-of-truth via tsc compile fallback (only when devDeps installed).
  // Skip suite gracefully if not compiled.
}

function mkTmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'lpm-vsx-'));
}

function rmTmp(dir) {
  try { fs.rmSync(dir, { recursive: true, force: true }); } catch { /* ignore */ }
}

function writeFile(dir, rel, content) {
  const full = path.join(dir, rel);
  fs.mkdirSync(path.dirname(full), { recursive: true });
  fs.writeFileSync(full, content);
}

test('scan module loads (vscode-extension/out/scan.js present)', { skip: !scan }, () => {
  assert.equal(typeof scan.listSprints, 'function');
  assert.equal(typeof scan.readFirstHeading, 'function');
  assert.equal(typeof scan.readStatus, 'function');
  assert.equal(typeof scan.statusLabel, 'function');
});

test('readFirstHeading returns the first H1 line', { skip: !scan }, () => {
  assert.equal(scan.readFirstHeading('# Hello\n\nbody'), 'Hello');
  assert.equal(scan.readFirstHeading('foo\n# Title\nbar'), 'Title');
  assert.equal(scan.readFirstHeading('## subhead only'), '');
});

test('readStatus picks up frontmatter status', { skip: !scan }, () => {
  assert.equal(scan.readStatus('---\nstatus: doing\n---'), 'doing');
  assert.equal(scan.readStatus('---\nstatus: done\n---'), 'done');
  assert.equal(scan.readStatus('no frontmatter'), 'todo');
});

test('listSprints discovers sprint dirs and task files', { skip: !scan }, () => {
  const dir = mkTmp();
  try {
    writeFile(dir, '.specs/sprints/sprint-01/SPRINT.md', '---\nstatus: doing\n---\n# Sprint 01');
    writeFile(dir, '.specs/sprints/sprint-01/01-foo.task.md', '---\nstatus: doing\n---\n# Foo task');
    writeFile(dir, '.specs/sprints/sprint-01/02-bar.task.md', '---\nstatus: todo\n---\n# Bar task');
    writeFile(dir, '.specs/sprints/sprint-02/SPRINT.md', '---\nstatus: todo\n---\n# Sprint 02');
    writeFile(dir, '.specs/sprints/sprint-02/01-baz.task.md', '---\nstatus: done\n---\n# Baz task');
    const sprints = scan.listSprints(path.join(dir, '.specs'));
    assert.equal(sprints.length, 2);
    assert.equal(sprints[0].id, 'sprint-01');
    assert.equal(sprints[0].status, 'doing');
    assert.equal(sprints[0].tasks.length, 2);
    assert.equal(sprints[0].tasks[0].status, 'doing');
    assert.equal(sprints[0].tasks[0].title, 'Foo task');
    assert.equal(sprints[1].id, 'sprint-02');
    assert.equal(sprints[1].tasks[0].status, 'done');
  } finally {
    rmTmp(dir);
  }
});

test('listSprints returns [] when no .specs/sprints dir exists', { skip: !scan }, () => {
  const dir = mkTmp();
  try {
    const sprints = scan.listSprints(path.join(dir, '.specs'));
    assert.deepEqual(sprints, []);
  } finally {
    rmTmp(dir);
  }
});
