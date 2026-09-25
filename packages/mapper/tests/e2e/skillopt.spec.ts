import { spawnSync, SpawnSyncReturns } from 'node:child_process';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { expect, test, type TestInfo } from '@playwright/test';

const CLI = path.resolve(__dirname, '..', '..', 'bin', 'cli.js');
const NODE = process.execPath;

function mkTmp(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'lpm-skillopt-e2e-'));
}

function rmTmp(dir: string): void {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch {
    // ignore
  }
}

function writeFile(dir: string, rel: string, content: string): void {
  const full = path.join(dir, rel);
  fs.mkdirSync(path.dirname(full), { recursive: true });
  fs.writeFileSync(full, content);
}

function runCli(args: string[], cwd: string): SpawnSyncReturns<string> {
  return spawnSync(NODE, [CLI, ...args], { cwd, encoding: 'utf8', timeout: 30_000 });
}

async function attachEvidence(testInfo: TestInfo, res: SpawnSyncReturns<string>, files: Record<string, string>) {
  await testInfo.attach('stdout.txt', { body: res.stdout ?? '', contentType: 'text/plain' });
  await testInfo.attach('stderr.txt', { body: res.stderr ?? '', contentType: 'text/plain' });
  for (const [name, file] of Object.entries(files)) {
    if (fs.existsSync(file)) {
      await testInfo.attach(name, { path: file, contentType: 'text/plain' });
    }
  }
}

const WEAK_SKILL = `---
name: demo
description: weak demo skill
---

# Skill: demo

1. Make the change.
2. Open the PR.
`;

const SUITE = {
  skill: 'SKILL.md',
  rounds: 10,
  budget: 2,
  tasks: [
    { id: 't1', split: 'train', requires: ['run lint before commit', 'run unit tests before commit'], forbids: ['skip tests'] },
    { id: 't2', split: 'train', requires: ['run unit tests before commit'], forbids: ['force push to main'] },
    { id: 'h1', split: 'holdout', requires: ['run lint before commit', 'run unit tests before commit'], forbids: ['skip tests', 'force push to main'] },
  ],
};

test('skillopt CLI optimizes a weak skill to a passing held-out gate', async ({}, testInfo) => {
  const dir = mkTmp();
  try {
    writeFile(dir, 'SKILL.md', WEAK_SKILL);
    writeFile(dir, 'suite.json', JSON.stringify(SUITE, null, 2));

    const res = runCli(['skillopt', '--suite', 'suite.json', '--out', 'best_skill.md', '--report', 'report.json'], dir);

    const bestPath = path.join(dir, 'best_skill.md');
    const reportPath = path.join(dir, 'report.json');
    await attachEvidence(testInfo, res, { 'best_skill.md': bestPath, 'report.json': reportPath });

    expect(res.status, res.stderr).toBe(0);
    expect(fs.existsSync(bestPath)).toBe(true);

    const best = fs.readFileSync(bestPath, 'utf8');
    expect(best).toContain('run lint before commit');
    expect(best).toContain('run unit tests before commit');
    expect(best).not.toContain('force push to main');

    const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
    expect(report.exitSignal).toBe(true);
    expect(report.scores.best.gate).toBeGreaterThan(report.scores.initial.gate);
    expect(report.scores.best.gatePassRate).toBe(1);
    expect(report.scores.usedHoldout).toBe(true);
  } finally {
    rmTmp(dir);
  }
});
