'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const packageJson = require(path.resolve(__dirname, '..', '..', 'package.json'));

test('npm test scopes discovery to the unit suite', () => {
  assert.equal(packageJson.scripts.test, 'node --test tests/unit/*.test.js');
});
