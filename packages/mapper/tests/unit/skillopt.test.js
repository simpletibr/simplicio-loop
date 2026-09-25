'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const engine = require('../../scripts/skillopt/engine.js');

const NODE = process.execPath;
const BIN = path.resolve(__dirname, '..', '..', 'bin', 'skillopt.js');
const CLI = path.resolve(__dirname, '..', '..', 'bin', 'cli.js');

function mkTmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'lpm-skillopt-'));
}

function rmTmp(dir) {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch {
    // ignore
  }
}

const WEAK_SKILL = `---
name: demo
description: demo skill
---

# Skill: demo

Some intro line.
`;

const SUITE = {
  rounds: 10,
  budget: 2,
  tasks: [
    { id: 't1', split: 'train', requires: ['run lint before commit', 'write a failing test first'], forbids: ['skip tests'] },
    { id: 't2', split: 'train', requires: ['run lint before commit'], forbids: ['force push to main'] },
    { id: 'h1', split: 'holdout', requires: ['run lint before commit', 'write a failing test first'], forbids: ['skip tests'] },
  ],
};

test('scoreTask: full pass when all requires present and no forbids', () => {
  const lines = ['- run lint before commit', '- write a failing test first'];
  const res = engine.scoreTask(lines, { requires: ['run lint before commit', 'write a failing test first'], forbids: ['skip tests'] });
  assert.equal(res.pass, true);
  assert.equal(res.score, 1);
  assert.deepEqual(res.missing, []);
});

test('scoreTask: partial score with missing directive and offending forbid', () => {
  const lines = ['- run lint before commit', '- skip tests when in a hurry'];
  const res = engine.scoreTask(lines, {
    requires: ['run lint before commit', 'write a failing test first'],
    forbids: ['skip tests'],
  });
  assert.equal(res.pass, false);
  // 1 of 2 requires present, 0 of 1 forbids avoided -> 1/3
  assert.ok(Math.abs(res.score - 1 / 3) < 1e-9);
  assert.deepEqual(res.missing, ['write a failing test first']);
  assert.deepEqual(res.offending, ['skip tests']);
});

test('containsDirective is case- and whitespace-insensitive', () => {
  const lines = ['- Run   Lint  Before Commit'];
  assert.equal(engine.containsDirective(lines, 'run lint before commit'), true);
  assert.equal(engine.containsDirective(lines, 'missing thing'), false);
});

test('reflect ranks missing directives by failure frequency', () => {
  const results = [
    { pass: false, missing: ['run lint before commit', 'write a failing test first'], offending: [] },
    { pass: false, missing: ['run lint before commit'], offending: ['skip tests'] },
    { pass: true, missing: [], offending: [] },
  ];
  const candidates = engine.reflect([], results);
  assert.equal(candidates[0].op, 'add');
  assert.equal(candidates[0].directive, 'run lint before commit'); // weight 2, ranked first
  assert.ok(candidates.some((c) => c.op === 'delete' && c.directive === 'skip tests'));
});

test('applyEdit add appends under managed header and is idempotent', () => {
  let lines = ['# Title', ''];
  lines = engine.applyEdit(lines, { op: 'add', directive: 'run lint before commit' });
  assert.ok(lines.includes(engine.MANAGED_HEADER));
  assert.ok(lines.some((l) => l === '- run lint before commit'));
  const before = lines.length;
  lines = engine.applyEdit(lines, { op: 'add', directive: 'run lint before commit' });
  assert.equal(lines.length, before, 'adding an existing directive is a no-op');
});

test('applyEdit delete removes matching lines; replace rewrites in place', () => {
  const deleted = engine.applyEdit(['- skip tests now', '- keep me'], { op: 'delete', directive: 'skip tests' });
  assert.deepEqual(deleted, ['- keep me']);
  const replaced = engine.applyEdit(['- always Skip Tests'], { op: 'replace', from: 'skip tests', to: 'run tests' });
  assert.deepEqual(replaced, ['- always run tests']);
});

test('optimize improves a weak skill and raises EXIT_SIGNAL on convergence', () => {
  const report = engine.optimize(WEAK_SKILL, SUITE);
  assert.ok(report.scores.best.gate > report.scores.initial.gate, 'gate score should improve');
  assert.equal(report.scores.best.gatePassRate, 1);
  assert.equal(report.exitSignal, true);
  assert.ok(report.bestSkill.includes('run lint before commit'));
  assert.ok(report.bestSkill.includes('write a failing test first'));
});

test('optimize gates on held-out split and reports usedHoldout', () => {
  const report = engine.optimize(WEAK_SKILL, SUITE);
  assert.equal(report.scores.usedHoldout, true);
});

test('optimize rejects regressions into the rejected-edit buffer', () => {
  // A skill already perfect on the gate split; any edit that adds a forbidden
  // directive must be rejected, never accepted as best.
  const suite = {
    rounds: 5,
    budget: 1,
    tasks: [
      { id: 'g1', split: 'holdout', requires: ['good directive'], forbids: ['bad directive'] },
      // train task that "wants" the bad directive added, which would regress holdout
      { id: 'tr', split: 'train', requires: ['bad directive'], forbids: [] },
    ],
  };
  const start = '# s\n\n- good directive\n';
  const report = engine.optimize(start, suite);
  // best skill must never contain the forbidden directive
  assert.equal(engine.containsDirective(report.bestSkillLines, 'bad directive'), false);
  assert.ok(report.rejectedEdits.length >= 1, 'the regressing edit should be buffered');
});

test('optimize converges with no edits when skill already passes', () => {
  const suite = {
    tasks: [{ id: 'a', split: 'train', requires: ['already here'], forbids: [] }],
  };
  const report = engine.optimize('- already here\n', suite);
  assert.equal(report.rounds, 0);
  assert.equal(report.exitSignal, true);
  assert.equal(report.scores.improvement, 0);
});

test('optimize tolerates malformed suite (null tasks, non-array directives)', () => {
  assert.doesNotThrow(() => engine.optimize('# s\n', null));
  assert.doesNotThrow(() => engine.optimize('# s\n', { tasks: [null, { id: 'x', split: 'train' }] }));
  const report = engine.optimize('# s\n', { tasks: [{ id: 'a', requires: 'not-an-array' }] });
  assert.equal(report.exitSignal, true); // no real checks -> trivially passes
});

test('CLI: optimizes a fixture suite, writes best_skill.md, report and receipt', () => {
  const dir = mkTmp();
  try {
    fs.writeFileSync(path.join(dir, 'SKILL.md'), WEAK_SKILL);
    fs.writeFileSync(path.join(dir, 'suite.json'), JSON.stringify({ skill: 'SKILL.md', ...SUITE }));
    const res = spawnSync(NODE, [BIN, '--suite', 'suite.json', '--out', 'best_skill.md', '--report', 'report.json'], {
      cwd: dir,
      encoding: 'utf8',
      timeout: 30000,
    });
    assert.equal(res.status, 0, res.stderr);
    const best = fs.readFileSync(path.join(dir, 'best_skill.md'), 'utf8');
    assert.ok(best.includes('run lint before commit'));
    const report = JSON.parse(fs.readFileSync(path.join(dir, 'report.json'), 'utf8'));
    assert.equal(report.exitSignal, true);
    assert.ok(report.scores.best.gate > report.scores.initial.gate);
    assert.match(res.stdout, /SkillOpt run complete/);
    // receipt written under .catalog/receipts
    const receiptsDir = path.join(dir, '.catalog', 'receipts');
    const receipts = fs.readdirSync(receiptsDir).filter((f) => f.endsWith('.json'));
    assert.equal(receipts.length, 1);
    const receipt = JSON.parse(fs.readFileSync(path.join(receiptsDir, receipts[0]), 'utf8'));
    assert.match(receipt.id, /^sha256:/);
    assert.equal(receipt.yool_id, 'agent.opt.skillopt');
  } finally {
    rmTmp(dir);
  }
});

test('CLI: --no-receipt skips receipt; --json prints report', () => {
  const dir = mkTmp();
  try {
    fs.writeFileSync(path.join(dir, 'SKILL.md'), WEAK_SKILL);
    fs.writeFileSync(path.join(dir, 'suite.json'), JSON.stringify({ skill: 'SKILL.md', ...SUITE }));
    const res = spawnSync(NODE, [BIN, '--suite', 'suite.json', '--no-receipt', '--json'], {
      cwd: dir,
      encoding: 'utf8',
      timeout: 30000,
    });
    assert.equal(res.status, 0, res.stderr);
    assert.equal(fs.existsSync(path.join(dir, '.catalog', 'receipts')), false);
    const parsed = JSON.parse(res.stdout);
    assert.equal(parsed.exitSignal, true);
  } finally {
    rmTmp(dir);
  }
});

test('CLI: --help exits 0 and missing suite exits 2', () => {
  const help = spawnSync(NODE, [BIN, '--help'], { encoding: 'utf8' });
  assert.equal(help.status, 0);
  assert.match(help.stdout, /Optimize a skill document/);

  const dir = mkTmp();
  try {
    const missing = spawnSync(NODE, [BIN, '--suite', 'nope.json'], { cwd: dir, encoding: 'utf8' });
    assert.equal(missing.status, 2);
    assert.match(missing.stderr, /not found/);
  } finally {
    rmTmp(dir);
  }
});

test('CLI: cli.js proxies the skillopt subcommand', () => {
  const dir = mkTmp();
  try {
    fs.writeFileSync(path.join(dir, 'SKILL.md'), WEAK_SKILL);
    fs.writeFileSync(path.join(dir, 'suite.json'), JSON.stringify({ skill: 'SKILL.md', ...SUITE }));
    const res = spawnSync(NODE, [CLI, 'skillopt', '--suite', 'suite.json', '--no-receipt'], {
      cwd: dir,
      encoding: 'utf8',
      timeout: 30000,
    });
    assert.equal(res.status, 0, res.stderr);
    assert.ok(fs.existsSync(path.join(dir, 'best_skill.md')));
  } finally {
    rmTmp(dir);
  }
});
