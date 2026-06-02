const { test } = require('node:test');
const assert = require('node:assert/strict');
const { startServer } = require('../src/index');

test('starts the server', () => {
  const app = startServer();
  assert.ok(app);
});
