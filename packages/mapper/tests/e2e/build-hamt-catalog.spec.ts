import { spawnSync, SpawnSyncReturns } from 'node:child_process';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { expect, test, type TestInfo } from '@playwright/test';

const CLI = path.resolve(__dirname, '..', '..', 'bin', 'cli.js');
const NODE = process.execPath;

function mkTmp(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'lpm-hamt-e2e-'));
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
  return spawnSync(NODE, [CLI, ...args], {
    cwd,
    encoding: 'utf8',
    timeout: 30_000,
  });
}

async function attachEvidence(testInfo: TestInfo, res: SpawnSyncReturns<string>, outputPath: string) {
  await testInfo.attach('stdout.txt', { body: res.stdout ?? '', contentType: 'text/plain' });
  await testInfo.attach('stderr.txt', { body: res.stderr ?? '', contentType: 'text/plain' });
  if (fs.existsSync(outputPath)) {
    await testInfo.attach('agents.json', {
      path: outputPath,
      contentType: 'application/json',
    });
  }
}

test('npx-style CLI subcommand builds a HAMT catalog on a fixture repo', async ({}, testInfo) => {
  const dir = mkTmp();
  const agentsMd = `# Agents

### Dev Agent
- yool_id: \`agent.dev.typescript.v1\`
- authority: dev
- lane: fast
- agent_terms:
    cpu_quota_pct: 55
    disk_quota_mb: 120

### Lint Agent
- yool_id: \`agent.lint.eslint.v1\`
- authority: review
- lane: background
- agent_terms:
    cpu_quota_pct: 15
    disk_quota_mb: 30
`;
  try {
    writeFile(dir, 'AGENTS.md', agentsMd);
    const res = runCli(['build-hamt-catalog', dir], dir);
    const outputPath = path.join(dir, '.catalog', 'agents.json');
    await attachEvidence(testInfo, res, outputPath);
    expect(res.status, res.stderr).toBe(0);
    expect(fs.existsSync(outputPath)).toBe(true);
    const catalog = JSON.parse(fs.readFileSync(outputPath, 'utf8'));
    expect(catalog.schema).toBe('yool-catalog/v1');
    expect(catalog.stats.entries).toBe(2);
    expect(catalog.entries.map((entry: { yool_id: string }) => entry.yool_id)).toEqual([
      'agent.dev.typescript.v1',
      'agent.lint.eslint.v1',
    ]);
    expect(catalog.hamt.root.bitmap).toBeGreaterThan(0);
  } finally {
    rmTmp(dir);
  }
});
