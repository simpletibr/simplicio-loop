'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');

const {
  extractHeadingLevels,
  editDistance,
  computeDivergence,
} = require('../../scripts/check-readme-sync.js');

test('extractHeadingLevels reads heading depth, ignoring code fences', () => {
  const text = [
    '# Title',
    '',
    '## Section A',
    '',
    '```bash',
    '# this is a bash comment, not a heading',
    '### also not a heading',
    '```',
    '',
    '### Subsection',
    '',
    '## Section B',
  ].join('\n');
  assert.deepEqual(extractHeadingLevels(text), [1, 2, 3, 2]);
});

test('editDistance is 0 for identical sequences', () => {
  assert.equal(editDistance([1, 2, 2, 3], [1, 2, 2, 3]), 0);
});

test('editDistance counts a missing heading as 1', () => {
  assert.equal(editDistance([1, 2, 2, 3], [1, 2, 3]), 1);
});

test('computeDivergence is 0 for structurally parallel translations (different text, same skeleton)', () => {
  const en = '# Title\n\n## Quick Start\n\n### Sub one\n\n## Install matrix\n';
  const pt = '# Título\n\n## Começo rápido\n\n### Sub um\n\n## Matriz de instalação\n';
  const divergence = computeDivergence(en, pt);
  assert.equal(divergence.distance, 0);
  assert.equal(divergence.enCount, divergence.ptCount);
});

test('computeDivergence catches an intentionally-desynced mirror (issue #163 AC)', () => {
  const en = [
    '# Title',
    '',
    '## Quick Start',
    '',
    '## Install matrix',
    '',
    '### Details',
  ].join('\n');
  // pt-BR mirror "forgot" to add the equivalent of "## Install matrix" and
  // "### Details" -- a real-world desync scenario (a section added to one
  // language's README without its counterpart in the other).
  const ptDesynced = ['# Título', '', '## Começo rápido'].join('\n');

  const divergence = computeDivergence(en, ptDesynced);
  assert.ok(
    divergence.distance > 0,
    'expected a nonzero structural divergence when a whole section is missing from one mirror',
  );

  // And the properly-synced version (same skeleton, translated text) must
  // report back down to 0 -- proving the check reacts to structure, not
  // language content.
  const ptSynced = [
    '# Título',
    '',
    '## Começo rápido',
    '',
    '## Matriz de instalação',
    '',
    '### Detalhes',
  ].join('\n');
  const noDivergence = computeDivergence(en, ptSynced);
  assert.equal(noDivergence.distance, 0);
});
