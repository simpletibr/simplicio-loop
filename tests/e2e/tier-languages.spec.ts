/*
 * End-to-end coverage of Tier 1/2 language support (Dart, SQL, C/C++, Swift,
 * Objective-C, Vue, Svelte, Scala).
 *
 * Playwright is used here as a test harness (parallelism, reporter, evidence
 * attach), not for browser navigation. The test spawns
 * `python -m simplicio_mapper.cli index` against a fresh multi-language temp
 * project and asserts the on-disk project-map (language detection) plus the
 * symbol-index (per-language symbol extraction). stdout and the parsed
 * artifacts are attached as evidence to satisfy the DoD gate.
 */

import { spawnSync, SpawnSyncReturns } from 'node:child_process';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { expect, test, type TestInfo } from '@playwright/test';

const ROOT = path.resolve(__dirname, '..', '..');
const PYTHON = process.env.PYTHON ?? 'python3';

const FILES: Record<string, string> = {
  'package.json': '{"name":"polyglot-host"}',
  'lib/main.dart': "import 'package:flutter/material.dart';\nclass MyApp {}\nenum Color { red, green }\nvoid main() {}\n",
  'db/schema.sql': 'CREATE TABLE users (id int);\nCREATE OR REPLACE VIEW active_users AS SELECT 1;\n',
  'src/main.c': '#include <stdio.h>\nstruct Point { int x; };\nint add(int a, int b) {\n  return a + b;\n}\n',
  'src/app.cpp': '#include "app.h"\nclass Engine {\npublic:\n  void run() { start(); }\n};\n',
  'ios/App.swift': 'import Foundation\nclass ViewController {}\nstruct Model {}\nfunc greet() {}\n',
  'ios/Legacy.m': '#import <UIKit/UIKit.h>\n@interface Foo\n@end\n@implementation Foo\n- (void)doThing {}\n@end\n',
  'ui/Button.vue': "<script>\nimport x from './x';\nexport function handleClick() {}\n</script>\n",
  'ui/Card.svelte': "<script>\nimport y from './y';\nfunction render() {}\n</script>\n",
  'be/Service.scala': 'import scala.collection.mutable\nobject Main\nclass Repo\ndef compute() = 1\n',
};

function mkTmp(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'lpm-lang-e2e-'));
}

function rmTmp(dir: string): void {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch {
    /* ignore */
  }
}

function scaffold(dir: string): void {
  for (const [rel, content] of Object.entries(FILES)) {
    const full = path.join(dir, rel);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, content);
  }
}

function runIndex(appDir: string): SpawnSyncReturns<string> {
  return spawnSync(PYTHON, ['-m', 'simplicio_mapper.cli', 'index', appDir, '--json'], {
    cwd: ROOT,
    encoding: 'utf8',
    timeout: 30_000,
    env: { ...process.env, PYTHONPATH: ROOT },
  });
}

async function attach(testInfo: TestInfo, res: SpawnSyncReturns<string>, dir: string): Promise<void> {
  await testInfo.attach('index-stdout.json', { body: res.stdout ?? '', contentType: 'application/json' });
  await testInfo.attach('index-stderr.txt', { body: res.stderr ?? '', contentType: 'text/plain' });
  const pm = path.join(dir, '.simplicio', 'project-map.json');
  if (fs.existsSync(pm)) await testInfo.attach('project-map.json', { path: pm, contentType: 'application/json' });
  const si = path.join(dir, '.simplicio', 'symbol-index.json');
  if (fs.existsSync(si)) await testInfo.attach('symbol-index.json', { path: si, contentType: 'application/json' });
}

test.describe('Tier 1/2 language support', () => {
  test('detects new languages and extracts their symbols', async ({}, testInfo) => {
    const dir = mkTmp();
    try {
      scaffold(dir);
      const res = runIndex(dir);
      await attach(testInfo, res, dir);
      expect(res.status, res.stderr).toBe(0);

      const pm = JSON.parse(fs.readFileSync(path.join(dir, '.simplicio', 'project-map.json'), 'utf8'));
      const langs: Record<string, string> = Object.fromEntries(pm.files.map((f: { path: string; language: string }) => [f.path, f.language]));
      expect(langs['lib/main.dart']).toBe('dart');
      expect(langs['db/schema.sql']).toBe('sql');
      expect(langs['src/main.c']).toBe('c');
      expect(langs['src/app.cpp']).toBe('cpp');
      expect(langs['ios/App.swift']).toBe('swift');
      expect(langs['ios/Legacy.m']).toBe('objectivec');
      expect(langs['ui/Button.vue']).toBe('vue');
      expect(langs['ui/Card.svelte']).toBe('svelte');
      expect(langs['be/Service.scala']).toBe('scala');

      const si = JSON.parse(fs.readFileSync(path.join(dir, '.simplicio', 'symbol-index.json'), 'utf8'));
      const byFile: Record<string, Set<string>> = {};
      for (const s of si.symbols) {
        (byFile[s.defined_in] ??= new Set()).add(`${s.kind}:${s.name}`);
      }
      expect(byFile['lib/main.dart']).toContain('class:MyApp');
      expect(byFile['db/schema.sql']).toContain('table:users');
      expect(byFile['src/main.c']).toContain('struct:Point');
      expect(byFile['src/app.cpp']).toContain('class:Engine');
      expect(byFile['ios/App.swift']).toContain('class:ViewController');
      expect(byFile['be/Service.scala']).toContain('class:Repo');
    } finally {
      rmTmp(dir);
    }
  });
});
