#!/usr/bin/env node
'use strict';

/**
 * Renders the PR comment body for the simplicio-mapper docs-sync GitHub
 * Action (F8, .specs/product/flow-documentation-spec.md).
 *
 * Usage: node render-simplicio-comment.js <sync.json> <drift.json>
 * Prints the rendered Markdown to stdout.
 */

const fs = require('node:fs');

const MARKER = '<!-- simplicio-mapper-docs-sync -->';
const MAX_COMMENT_CHARS = 60000; // stays under GitHub's ~65k comment limit

function readJsonSafe(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (e) {
    return null;
  }
}

function renderSyncSection(sync) {
  if (!sync) {
    return ['### Docs sync', '', '_`sync` did not produce a payload (see workflow logs)._', ''].join('\n');
  }
  const lines = ['### Docs sync', ''];
  const flows = sync.affected_flows || [];
  if (flows.length) {
    lines.push(`**Fluxos afetados (${flows.length})**`, '');
    lines.push('| Fluxo |', '| --- |');
    for (const flow of flows) lines.push(`| \`${flow}\` |`);
    lines.push('');
  } else {
    lines.push('Nenhum fluxo conhecido foi afetado por este diff.', '');
  }

  const regenerated = sync.regenerated_docs || [];
  const needsReview = sync.needs_review || [];
  lines.push('**Docs**', '');
  if (regenerated.length) {
    lines.push(`- ✅ regenerados: ${regenerated.map((d) => `\`${d}\``).join(', ')}`);
  }
  if (needsReview.length) {
    lines.push(`- ⚠️ precisam de revisão humana: ${needsReview.map((d) => `\`${d.doc}\` (${d.reason})`).join(', ')}`);
  }
  if (!regenerated.length && !needsReview.length) {
    lines.push('- nenhum doc gerado precisou de atualização.');
  }
  lines.push('');
  return lines.join('\n');
}

function renderDriftSection(drift) {
  if (!drift) {
    return ['### Spec-drift', '', '_`drift` did not produce a payload (see workflow logs)._', ''].join('\n');
  }
  const score = drift.score || {};
  const findings = drift.findings || [];
  const status = score.pass ? '✅ PASS' : '⚠️ WARN';
  const lines = [
    '### Spec-drift',
    '',
    `${status} — ${score.drift_findings} finding(s) (threshold: ${score.threshold})`,
    '',
  ];
  if (findings.length) {
    const byCheck = {};
    for (const finding of findings) {
      byCheck[finding.check] = (byCheck[finding.check] || 0) + 1;
    }
    for (const check of Object.keys(byCheck).sort()) {
      lines.push(`- \`${check}\`: ${byCheck[check]}`);
    }
    lines.push('', '_Full detail in the workflow artifact._');
  } else {
    lines.push('No drift findings.');
  }
  lines.push('');
  return lines.join('\n');
}

function renderComment(sync, drift) {
  const parts = [
    '## simplicio-mapper — impacto do PR na documentação',
    '',
    renderSyncSection(sync),
    renderDriftSection(drift),
  ];
  let body = parts.join('\n').trimEnd() + '\n';
  if (body.length > MAX_COMMENT_CHARS) {
    body = body.slice(0, MAX_COMMENT_CHARS) + '\n\n_...truncated, see the workflow artifact for the full payload._\n';
  }
  return `${MARKER}\n${body}`;
}

function main(argv) {
  const [syncPath, driftPath] = argv;
  const sync = syncPath ? readJsonSafe(syncPath) : null;
  const drift = driftPath ? readJsonSafe(driftPath) : null;
  process.stdout.write(renderComment(sync, drift));
}

if (require.main === module) {
  main(process.argv.slice(2));
}

module.exports = { MARKER, renderComment, renderSyncSection, renderDriftSection };
