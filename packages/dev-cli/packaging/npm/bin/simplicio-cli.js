#!/usr/bin/env node
'use strict';

const { ensureAndRun } = require('../lib/python-shim');

ensureAndRun({
  packageName: 'simplicio-cli',
  version: '0.7.1',
  entrypoint: 'simplicio-cli',
  args: process.argv.slice(2),
});
