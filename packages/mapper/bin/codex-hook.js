#!/usr/bin/env node
'use strict';

// Codex sends one JSON hook envelope on stdin.  Keep the bridge portable and
// fail-open: PostToolUse and UserPromptSubmit must not block the host agent.
const { spawnSync } = require('node:child_process');
const path = require('node:path');

let payload = {};
try {
  const raw = require('node:fs').readFileSync(0, 'utf8');
  if (raw.trim()) payload = JSON.parse(raw);
} catch {
  payload = {};
}

const event = String(payload.hook_event_name || payload.event || payload.type || '').toLowerCase();
const toolInput = payload.tool_input && typeof payload.tool_input === 'object' ? payload.tool_input : {};
const command = typeof toolInput.command === 'string' ? toolInput.command : '';

if (event === 'sessionstart' || event === 'session_start') {
  const result = spawnSync(process.execPath, [
    path.join(__dirname, 'hook-runner.js'), 'codex', 'session-start',
  ], { stdio: 'inherit', env: process.env });
  process.exit(result.error ? 0 : (result.status ?? 0));
}

if (event === 'pretooluse' || event === 'pre_tool_use') {
  if (!command.includes('git commit')) process.exit(0);
  const env = { ...process.env, CLAUDE_BASH_COMMAND: command };
  const result = spawnSync(process.execPath, [
    path.join(__dirname, 'hook-runner.js'), 'codex', 'pre-commit-if-needed',
  ], { stdio: 'inherit', env });
  process.exit(result.error ? 0 : (result.status ?? 0));
}

// PostToolUse and UserPromptSubmit are intentionally observational here.
// Dev CLI owns the prompt detector; Mapper has no repository mutation hook.
process.exit(0);
