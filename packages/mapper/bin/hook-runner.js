#!/usr/bin/env node
'use strict';

const { spawnSync } = require('node:child_process');
const path = require('node:path');

const [, , tool, hookName, ...hookArgs] = process.argv;

if (!tool || !hookName) {
  console.error('Usage: node bin/hook-runner.js <codex|claude> <hook-name> [...args]');
  process.exit(2);
}

const repoRoot = path.resolve(__dirname, '..');
const isWindows = process.platform === 'win32';

function runHook(scriptBaseName, args = []) {
  const hooksDir = path.join(repoRoot, `.${tool}`, 'hooks');
  const ext = isWindows ? '.ps1' : '.sh';
  const scriptPath = path.join(hooksDir, `${scriptBaseName}${ext}`);

  const command = isWindows ? 'powershell.exe' : 'bash';
  const commandArgs = isWindows
    ? ['-ExecutionPolicy', 'Bypass', '-File', scriptPath, ...args]
    : [scriptPath, ...args];

  const result = spawnSync(command, commandArgs, {
    cwd: repoRoot,
    stdio: 'inherit',
    env: process.env,
  });

  if (result.error) {
    console.error(`[hook-runner] Failed to run ${scriptBaseName}: ${result.error.message}`);
    process.exit(1);
  }

  process.exit(result.status ?? 0);
}

switch (hookName) {
  case 'session-start':
    runHook('session-start-skills');
    break;
  case 'post-edit':
    runHook('post-edit', hookArgs);
    break;
  case 'pre-commit-if-needed': {
    const bashCommand = process.env.CLAUDE_BASH_COMMAND || '';
    if (!bashCommand.includes('git commit')) {
      process.exit(0);
    }
    runHook('pre-commit');
    break;
  }
  default:
    console.error(`[hook-runner] Unknown hook: ${hookName}`);
    process.exit(2);
}
