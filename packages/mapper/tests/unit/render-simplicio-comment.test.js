'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const {
  MARKER,
  renderComment,
} = require('../../scripts/render-simplicio-comment.js');

test('renderComment includes the idempotency marker', () => {
  const body = renderComment(null, null);
  assert.ok(body.startsWith(MARKER));
});

test('renderComment lists affected flows and regenerated docs', () => {
  const sync = {
    affected_flows: ['cli.map', 'cli.index'],
    regenerated_docs: ['.simplicio/docs/flows.md'],
    needs_review: [{ doc: 'docs/architecture-map.md', reason: 'references mapper.py' }],
  };
  const body = renderComment(sync, null);
  assert.match(body, /cli\.map/);
  assert.match(body, /cli\.index/);
  assert.match(body, /flows\.md/);
  assert.match(body, /architecture-map\.md/);
  assert.match(body, /references mapper\.py/);
});

test('renderComment reports drift pass/fail status', () => {
  const passingDrift = { score: { pass: true, drift_findings: 0, threshold: 10 }, findings: [] };
  const failingDrift = {
    score: { pass: false, drift_findings: 12, threshold: 10 },
    findings: [{ check: 'placeholder' }, { check: 'placeholder' }, { check: 'orphan-spec' }],
  };
  assert.match(renderComment(null, passingDrift), /PASS/);
  const failingBody = renderComment(null, failingDrift);
  assert.match(failingBody, /WARN/);
  assert.match(failingBody, /`placeholder`: 2/);
  assert.match(failingBody, /`orphan-spec`: 1/);
});

test('renderComment degrades gracefully when payloads are missing', () => {
  const body = renderComment(null, null);
  assert.match(body, /did not produce a payload/);
});

test('renderComment truncates extremely large bodies', () => {
  const sync = {
    affected_flows: Array.from({ length: 5000 }, (_, i) => `flow.${i}`),
    regenerated_docs: [],
    needs_review: [],
  };
  const body = renderComment(sync, null);
  assert.ok(body.length <= 60200);
  assert.match(body, /truncated/);
});

test('renderComment reports no-op diffs explicitly', () => {
  const sync = { affected_flows: [], regenerated_docs: [], needs_review: [] };
  const body = renderComment(sync, null);
  assert.match(body, /Nenhum fluxo conhecido foi afetado/);
  assert.match(body, /nenhum doc gerado precisou de atualização/);
});
