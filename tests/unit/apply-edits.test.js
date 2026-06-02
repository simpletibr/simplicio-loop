'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { applyEdits, EditError } = require('../../bin/apply-edits');

function mkTmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'lpm-apply-edits-'));
}

function rmTmp(dir) {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch {
    // ignore
  }
}

function write(root, rel, content) {
  const full = path.join(root, rel);
  fs.mkdirSync(path.dirname(full), { recursive: true });
  fs.writeFileSync(full, content);
}

function read(root, rel) {
  return fs.readFileSync(path.join(root, rel), 'utf8');
}

test('replace: replaces first occurrence by default count', () => {
  const root = mkTmp();
  try {
    write(root, 'a.txt', 'foo foo foo');
    const report = applyEdits(
      { version: 1, edits: [{ file: 'a.txt', op: 'replace', find: 'foo', replace: 'bar', count: 1 }] },
      { root }
    );
    assert.equal(read(root, 'a.txt'), 'bar foo foo');
    assert.equal(report.changed, 1);
  } finally {
    rmTmp(root);
  }
});

test('replace: count "all" replaces every occurrence', () => {
  const root = mkTmp();
  try {
    write(root, 'a.txt', 'foo foo foo');
    applyEdits(
      { edits: [{ file: 'a.txt', op: 'replace', find: 'foo', replace: 'bar', count: 'all' }] },
      { root }
    );
    assert.equal(read(root, 'a.txt'), 'bar bar bar');
  } finally {
    rmTmp(root);
  }
});

test('replace: missing find string aborts transactionally', () => {
  const root = mkTmp();
  try {
    write(root, 'a.txt', 'hello');
    write(root, 'b.txt', 'world');
    assert.throws(
      () =>
        applyEdits(
          {
            edits: [
              { file: 'a.txt', op: 'replace', find: 'hello', replace: 'hi' },
              { file: 'b.txt', op: 'replace', find: 'NOPE', replace: 'x' },
            ],
          },
          { root }
        ),
      EditError
    );
    // Nothing written because phase-1 validation failed.
    assert.equal(read(root, 'a.txt'), 'hello');
    assert.equal(read(root, 'b.txt'), 'world');
  } finally {
    rmTmp(root);
  }
});

test('regex_replace: applies pattern with flags', () => {
  const root = mkTmp();
  try {
    write(root, 'v.ts', 'const V = "1.2.3";');
    applyEdits(
      {
        edits: [
          { file: 'v.ts', op: 'regex_replace', pattern: '\\d+\\.\\d+\\.\\d+', replacement: '2.0.0' },
        ],
      },
      { root }
    );
    assert.equal(read(root, 'v.ts'), 'const V = "2.0.0";');
  } finally {
    rmTmp(root);
  }
});

test('regex_replace: non-matching pattern throws', () => {
  const root = mkTmp();
  try {
    write(root, 'v.ts', 'no digits here');
    assert.throws(
      () => applyEdits({ edits: [{ file: 'v.ts', op: 'regex_replace', pattern: '\\d+', replacement: 'x' }] }, { root }),
      EditError
    );
  } finally {
    rmTmp(root);
  }
});

test('create: makes a new file and nested dirs', () => {
  const root = mkTmp();
  try {
    applyEdits({ edits: [{ file: 'gen/notice.txt', op: 'create', content: 'hi\n' }] }, { root });
    assert.equal(read(root, 'gen/notice.txt'), 'hi\n');
  } finally {
    rmTmp(root);
  }
});

test('create: refuses to overwrite without flag, allows with flag', () => {
  const root = mkTmp();
  try {
    write(root, 'x.txt', 'old');
    assert.throws(
      () => applyEdits({ edits: [{ file: 'x.txt', op: 'create', content: 'new' }] }, { root }),
      EditError
    );
    applyEdits({ edits: [{ file: 'x.txt', op: 'create', content: 'new', overwrite: true }] }, { root });
    assert.equal(read(root, 'x.txt'), 'new');
  } finally {
    rmTmp(root);
  }
});

test('append and prepend', () => {
  const root = mkTmp();
  try {
    write(root, 'a.md', 'body');
    applyEdits(
      {
        edits: [
          { file: 'a.md', op: 'append', content: '\nfoot' },
          { file: 'a.md', op: 'prepend', content: 'head\n' },
        ],
      },
      { root }
    );
    assert.equal(read(root, 'a.md'), 'head\nbody\nfoot');
  } finally {
    rmTmp(root);
  }
});

test('insert_after and insert_before anchor', () => {
  const root = mkTmp();
  try {
    write(root, 'a.md', 'START\nEND');
    applyEdits(
      {
        edits: [
          { file: 'a.md', op: 'insert_after', anchor: 'START', content: '\nmid' },
          { file: 'a.md', op: 'insert_before', anchor: 'END', content: 'tail\n' },
        ],
      },
      { root }
    );
    assert.equal(read(root, 'a.md'), 'START\nmid\ntail\nEND');
  } finally {
    rmTmp(root);
  }
});

test('delete_file removes file; missing throws unless ignoreMissing', () => {
  const root = mkTmp();
  try {
    write(root, 'a.txt', 'x');
    applyEdits({ edits: [{ file: 'a.txt', op: 'delete_file' }] }, { root });
    assert.equal(fs.existsSync(path.join(root, 'a.txt')), false);
    assert.throws(() => applyEdits({ edits: [{ file: 'nope.txt', op: 'delete_file' }] }, { root }), EditError);
    const report = applyEdits(
      { edits: [{ file: 'nope.txt', op: 'delete_file', ignoreMissing: true }] },
      { root }
    );
    assert.equal(report.changed, 0);
  } finally {
    rmTmp(root);
  }
});

test('in-batch chaining: edits compose against staged state', () => {
  const root = mkTmp();
  try {
    applyEdits(
      {
        edits: [
          { file: 'a.txt', op: 'create', content: 'one' },
          { file: 'a.txt', op: 'append', content: ' two' },
          { file: 'a.txt', op: 'replace', find: 'one', replace: '1' },
        ],
      },
      { root }
    );
    assert.equal(read(root, 'a.txt'), '1 two');
  } finally {
    rmTmp(root);
  }
});

test('dry-run does not write but reports changes', () => {
  const root = mkTmp();
  try {
    write(root, 'a.txt', 'foo');
    const report = applyEdits(
      { edits: [{ file: 'a.txt', op: 'replace', find: 'foo', replace: 'bar' }] },
      { root, dryRun: true }
    );
    assert.equal(read(root, 'a.txt'), 'foo');
    assert.equal(report.dryRun, true);
    assert.equal(report.changed, 1);
  } finally {
    rmTmp(root);
  }
});

test('path traversal is rejected', () => {
  const root = mkTmp();
  try {
    assert.throws(
      () => applyEdits({ edits: [{ file: '../escape.txt', op: 'create', content: 'x' }] }, { root }),
      EditError
    );
    assert.throws(
      () => applyEdits({ edits: [{ file: '/etc/passwd', op: 'create', content: 'x' }] }, { root }),
      EditError
    );
  } finally {
    rmTmp(root);
  }
});

test('rejects unsupported op and malformed doc', () => {
  const root = mkTmp();
  try {
    assert.throws(() => applyEdits({ edits: [{ file: 'a', op: 'frobnicate' }] }, { root }), EditError);
    assert.throws(() => applyEdits({ edits: 'nope' }, { root }), EditError);
    assert.throws(() => applyEdits({ version: 2, edits: [] }, { root }), EditError);
  } finally {
    rmTmp(root);
  }
});

test('example doc parses as valid JSON', () => {
  const example = path.resolve(__dirname, '..', '..', 'docs', 'apply-edits.example.json');
  const doc = JSON.parse(fs.readFileSync(example, 'utf8'));
  assert.equal(doc.version, 1);
  assert.ok(Array.isArray(doc.edits) && doc.edits.length > 0);
});
