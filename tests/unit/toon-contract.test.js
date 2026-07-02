'use strict';

/*
 * TOON-CONTRACT conformance runner for the Node side of this repo
 * (issue #149 — "Runner Python+Node").
 *
 * Honesty note: this repo has no Node TOON codec yet. `bin/map.js` carries
 * an explicit parity-pending NOTE (see that file) — the Node CLI mirror
 * does not implement `encode_toon`/`decode_toon`, only the Python side
 * does (`simplicio_mapper/toon.py`). Faking a "pass" here by not testing
 * anything, or by silently importing the Python codec through a subprocess
 * and calling that a "Node runner", would misrepresent Node-side coverage.
 *
 * So: every fixtures/toon-golden/ case is walked and explicitly SKIPPED
 * with a reason, so the gap is visible in `node --test` output (t.skip),
 * not hidden. Once a Node TOON codec module exists in this repo, replace
 * the `t.skip(...)` call below with real `encode`/`decode` calls against
 * it — same contract as tests/python/test_toon_contract.py.
 */

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..', '..');
const CORPUS = path.join(ROOT, 'fixtures', 'toon-golden');
const NODE_TOON_CODEC_PATH = path.join(ROOT, 'bin', 'toon.js');

function loadManifest() {
  return JSON.parse(fs.readFileSync(path.join(CORPUS, 'manifest.json'), 'utf8'));
}

function hasNodeCodec() {
  return fs.existsSync(NODE_TOON_CODEC_PATH);
}

test('TOON-CONTRACT golden corpus is present and well-formed', () => {
  const manifest = loadManifest();
  assert.ok(Array.isArray(manifest.valid) && manifest.valid.length > 0, 'manifest.valid must be non-empty');
  assert.ok(Array.isArray(manifest.invalid) && manifest.invalid.length > 0, 'manifest.invalid must be non-empty');
  for (const entry of manifest.valid) {
    const dir = path.join(CORPUS, 'valid', entry.id);
    assert.ok(fs.existsSync(path.join(dir, 'input.json')), `${entry.id}: missing input.json`);
    assert.ok(fs.existsSync(path.join(dir, 'expected.toon')), `${entry.id}: missing expected.toon`);
    // input.json must at least be valid JSON.
    JSON.parse(fs.readFileSync(path.join(dir, 'input.json'), 'utf8'));
  }
  for (const entry of manifest.invalid) {
    const dir = path.join(CORPUS, 'invalid', entry.id);
    assert.ok(fs.existsSync(path.join(dir, 'input.toon')), `${entry.id}: missing input.toon`);
    assert.ok(fs.existsSync(path.join(dir, 'meta.json')), `${entry.id}: missing meta.json`);
  }
});

test('TOON-CONTRACT conformance against this repo\'s Node codec', async (t) => {
  const manifest = loadManifest();
  if (!hasNodeCodec()) {
    t.skip(
      'no Node TOON codec in this repo yet (bin/map.js parity-pending NOTE); ' +
        'Python side is covered by tests/python/test_toon_contract.py — ' +
        `${manifest.valid.length + manifest.invalid.length} case(s) pending Node coverage`
    );
    return;
  }
  // eslint-disable-next-line global-require -- conditional on the codec existing
  const { encodeToon, decodeToon } = require(NODE_TOON_CODEC_PATH);
  for (const entry of manifest.valid) {
    await t.test(`valid/${entry.id}`, () => {
      const dir = path.join(CORPUS, 'valid', entry.id);
      const value = JSON.parse(fs.readFileSync(path.join(dir, 'input.json'), 'utf8'));
      const expectedToon = fs.readFileSync(path.join(dir, 'expected.toon'), 'utf8').replace(/\n$/, '');
      assert.deepEqual(decodeToon(encodeToon(value)), value, 'round-trip');
      assert.deepEqual(decodeToon(expectedToon), value, 'decode(expected.toon)');
    });
  }
  for (const entry of manifest.invalid) {
    await t.test(`invalid/${entry.id}`, () => {
      const dir = path.join(CORPUS, 'invalid', entry.id);
      const text = fs.readFileSync(path.join(dir, 'input.toon'), 'utf8');
      assert.throws(() => decodeToon(text));
    });
  }
});
