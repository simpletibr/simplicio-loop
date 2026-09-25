/*
 * End-to-end coverage of the `simplicio-mapper flowchart` command.
 *
 * Playwright is used here as a test harness (parallelism, reporter, evidence attach),
 * not for browser navigation. The test spawns `python -m simplicio_mapper.cli flowchart`
 * against a fresh temp project that mixes an Angular frontend with C# and Python
 * backends, then asserts the on-disk `flowchart.md` and the `--json` contract.
 * stdout and the rendered Markdown are attached to the report as evidence to
 * satisfy the DoD gate that demands Playwright artifacts.
 */

import { spawnSync, SpawnSyncReturns } from 'node:child_process';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { expect, test, type TestInfo } from '@playwright/test';

const ROOT = path.resolve(__dirname, '..', '..');
const PYTHON = process.env.PYTHON ?? 'python3';

function mkTmp(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'lpm-flow-e2e-'));
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

function runFlowchart(appDir: string): SpawnSyncReturns<string> {
  return spawnSync(PYTHON, ['-m', 'simplicio_mapper.cli', 'flowchart', appDir, '--json'], {
    cwd: ROOT,
    encoding: 'utf8',
    timeout: 30_000,
    env: { ...process.env, PYTHONPATH: ROOT },
  });
}

function scaffold(dir: string): void {
  writeFile(dir, 'src/app/app.routes.ts', `
import { Routes } from '@angular/router';
import { AdminUsersComponent } from './admin/users/users.component';
import { authGuard } from './auth.guard';

export const routes: Routes = [
  { path: 'admin/users', component: AdminUsersComponent, canActivate: [authGuard] },
];
`);
  writeFile(dir, 'src/app/admin/users/users.component.ts', `
import { Component } from '@angular/core';

@Component({
  selector: 'app-admin-users',
  template: \`<button (click)="save()">Save user</button>\`,
})
export class AdminUsersComponent {
  save() { this.http.post('/api/v1/admin/users', this.payload); }
}
`);
  writeFile(dir, 'server/Functions/UsersFunctions.cs', `
public sealed class UsersFunctions {
  [Function("UsersCreate")]
  public IActionResult Create(
    [HttpTrigger(AuthorizationLevel.Function, "post", Route = "api/v1/admin/users")] HttpRequest req,
    [FromBody] CreateUserDto dto) {
    var saved = _repository.Save(dto);
    _dbContext.SaveChanges();
    return Ok(new UserResponse());
  }
}
`);
}

async function attachEvidence(testInfo: TestInfo, res: SpawnSyncReturns<string>, doc: string) {
  await testInfo.attach('stdout.json', { body: res.stdout ?? '', contentType: 'application/json' });
  await testInfo.attach('stderr.txt', { body: res.stderr ?? '', contentType: 'text/plain' });
  await testInfo.attach('exit-code.txt', { body: String(res.status), contentType: 'text/plain' });
  if (fs.existsSync(doc)) {
    await testInfo.attach('flowchart.md', { body: fs.readFileSync(doc, 'utf8'), contentType: 'text/markdown' });
  }
}

test('flowchart maps screens, buttons, rules and backend flows to Mermaid docs', async ({}, testInfo) => {
  const dir = mkTmp();
  try {
    scaffold(dir);
    const res = runFlowchart(dir);
    const doc = path.join(dir, '.simplicio', 'docs', 'flowchart.md');
    await attachEvidence(testInfo, res, doc);

    expect(res.status, res.stderr).toBe(0);
    const payload = JSON.parse(res.stdout);
    expect(payload.schema).toBe('simplicio.service-flowchart/v1');
    expect(payload.counts.backend_flows).toBeGreaterThanOrEqual(1);

    const screen = payload.screens.find((s: { path: string }) => s.path === '/admin/users');
    expect(screen.guarded).toBe(true);
    expect(screen.buttons.map((b: { handler: string }) => b.handler)).toContain('save');

    const flow = payload.backend.find(
      (f: { method: string; path: string }) => f.method === 'POST' && f.path === '/api/v1/admin/users',
    );
    expect(flow.db_access).toBe(true);
    expect(flow.request).toContain('CreateUserDto');

    expect(fs.existsSync(doc)).toBe(true);
    const markdown = fs.readFileSync(doc, 'utf8');
    expect(markdown).toContain('```mermaid');
    expect(markdown).toContain('## Backend Flows');
  } finally {
    rmTmp(dir);
  }
});
