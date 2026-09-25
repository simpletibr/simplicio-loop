const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const SCRIPT = path.resolve(__dirname, '..', '..', 'bin', 'codex-hook.js');

test('PostToolUse bridge accepts Codex JSON and exits cleanly', () => {
  const result = spawnSync(process.execPath, [SCRIPT], {
    input: JSON.stringify({ hook_event_name: 'PostToolUse', tool_name: 'Edit' }),
    encoding: 'utf8',
  });
  assert.equal(result.status, 0);
});

test('UserPromptSubmit bridge accepts Codex JSON and exits cleanly', () => {
  const result = spawnSync(process.execPath, [SCRIPT], {
    input: JSON.stringify({ hook_event_name: 'UserPromptSubmit', prompt: 'ajuste o hook' }),
    encoding: 'utf8',
  });
  assert.equal(result.status, 0);
});
