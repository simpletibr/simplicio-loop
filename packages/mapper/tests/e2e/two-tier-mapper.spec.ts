/*
 * End-to-end coverage of the two-tier async mapper commands (issue #120):
 * `macro`, `scan` and `status`.
 *
 * Playwright is used here as a test harness (parallelism, reporter, evidence
 * attach), not for browser navigation. Each test spawns
 * `python -m simplicio_mapper.cli <command>` against a fresh temp project and
 * asserts the `--json` contract plus the on-disk side effects. stdout and the
 * parsed envelopes are attached to the report as evidence to satisfy the DoD
 * gate that demands Playwright artifacts.
 */

import { spawnSync, SpawnSyncReturns } from 'node:child_process';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { expect, test, type TestInfo } from '@playwright/test';

const ROOT = path.resolve(__dirname, '..', '..');
const PYTHON = process.env.PYTHON ?? 'python3';

function mkTmp(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'lpm-twotier-e2e-'));
}

function rmTmp(dir: string): void {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch {
    /* ignore */
  }
}

function writeFile(dir: string, rel: string, content: string): void {
  const full = path.join(dir, rel);
  fs.mkdirSync(path.dirname(full), { recursive: true });
  fs.writeFileSync(full, content);
}

function runMapper(args: string[], cwd: string, env: NodeJS.ProcessEnv = {}): SpawnSyncReturns<string> {
  return spawnSync(PYTHON, ['-m', 'simplicio_mapper.cli', ...args], {
    cwd: ROOT,
    encoding: 'utf8',
    timeout: 30_000,
    env: { ...process.env, PYTHONPATH: ROOT, ...env },
  });
}

function scaffold(dir: string): void {
  writeFile(dir, 'package.json', JSON.stringify({ name: 'two-tier-host' }));
  writeFile(dir, 'pyproject.toml', "[project]\nname = 'two-tier-host'\n");
  writeFile(dir, 'src/app/page.tsx', 'export default function Page() { return null; }\n');
  writeFile(dir, 'src/app/users.component.ts', 'export class UsersComponent {}\n');
  writeFile(dir, 'api/Users.cs', 'public class UsersController {}\n');
  writeFile(dir, 'services/user_service.py', 'def get_user():\n    return 1\n');
  writeFile(dir, 'tests/test_user.py', 'def test_x():\n    assert True\n');
}

async function attach(testInfo: TestInfo, res: SpawnSyncReturns<string>, label: string): Promise<void> {
  await testInfo.attach(`${label}-stdout.json`, { body: res.stdout ?? '', contentType: 'application/json' });
  await testInfo.attach(`${label}-stderr.txt`, { body: res.stderr ?? '', contentType: 'text/plain' });
  await testInfo.attach(`${label}-exit-code.txt`, { body: String(res.status), contentType: 'text/plain' });
}

test.describe('two-tier async mapper', () => {
  test('macro emits the shallow skeleton schema', async ({}, testInfo) => {
    const dir = mkTmp();
    try {
      scaffold(dir);
      const res = runMapper(['macro', dir, '--json'], dir);
      await attach(testInfo, res, 'macro');
      expect(res.status, res.stderr).toBe(0);
      const payload = JSON.parse(res.stdout);
      expect(payload.schema).toBe('simplicio.macro-map/v1');
      expect(payload.confidence).toBe('shallow');
      expect(payload.counts.files).toBeGreaterThan(0);
      expect(payload.counts.tests).toBe(1);
      expect(payload.counts.screens).toBeGreaterThanOrEqual(2);
      expect(payload.counts.endpoint_files).toBeGreaterThanOrEqual(4);
    } finally {
      rmTmp(dir);
    }
  });

  test('scan --sync returns a complete map-job envelope with artifacts', async ({}, testInfo) => {
    const dir = mkTmp();
    try {
      scaffold(dir);
      const res = runMapper(['scan', dir, '--sync', '--json'], dir);
      await attach(testInfo, res, 'scan-sync');
      expect(res.status, res.stderr).toBe(0);
      const payload = JSON.parse(res.stdout);
      expect(payload.schema).toBe('simplicio.map-job/v1');
      expect(payload.phase).toBe('complete');
      expect(payload.sync).toBe(true);
      expect(payload.macro.schema).toBe('simplicio.macro-map/v1');
      expect(fs.existsSync(path.join(dir, '.simplicio', 'project-map.json'))).toBe(true);
      expect(fs.existsSync(path.join(dir, '.simplicio', 'map-job.json'))).toBe(true);
    } finally {
      rmTmp(dir);
    }
  });

  test('scan async returns macro_done before the deep pass finishes', async ({}, testInfo) => {
    const dir = mkTmp();
    try {
      scaffold(dir);
      const res = runMapper(['scan', dir, '--json'], dir);
      await attach(testInfo, res, 'scan-async');
      expect(res.status, res.stderr).toBe(0);
      const payload = JSON.parse(res.stdout);
      expect(payload.phase).toBe('macro_done');
      expect(payload.sync).toBe(false);
      expect(payload.deep.pid).toBeGreaterThan(0);

      // Poll status until the detached deep pass reports complete.
      let phase = 'unknown';
      for (let i = 0; i < 80; i += 1) {
        const st = runMapper(['status', dir, '--json'], dir);
        phase = JSON.parse(st.stdout).phase;
        if (phase === 'complete') break;
        await new Promise((r) => setTimeout(r, 100));
      }
      expect(phase).toBe('complete');
    } finally {
      rmTmp(dir);
    }
  });

  test('status reports deep_running while the lock is held', async ({}, testInfo) => {
    const dir = mkTmp();
    try {
      scaffold(dir);
      fs.mkdirSync(path.join(dir, '.simplicio'), { recursive: true });
      fs.writeFileSync(path.join(dir, '.simplicio', 'index.lock'), '123\n');
      const res = runMapper(['status', dir, '--json'], dir);
      await attach(testInfo, res, 'status-running');
      expect(res.status, res.stderr).toBe(0);
      const payload = JSON.parse(res.stdout);
      expect(payload.schema).toBe('simplicio.map-status/v1');
      expect(payload.phase).toBe('deep_running');
      expect(payload.lock).toBe(true);
    } finally {
      rmTmp(dir);
    }
  });

  test('status is unknown before any run', async ({}, testInfo) => {
    const dir = mkTmp();
    try {
      scaffold(dir);
      const res = runMapper(['status', dir, '--json'], dir);
      await attach(testInfo, res, 'status-unknown');
      expect(res.status, res.stderr).toBe(0);
      expect(JSON.parse(res.stdout).phase).toBe('unknown');
    } finally {
      rmTmp(dir);
    }
  });
});
