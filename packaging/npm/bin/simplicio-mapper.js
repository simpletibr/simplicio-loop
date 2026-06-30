#!/usr/bin/env node
'use strict';

const { ensureAndRun } = require('../lib/python-shim');

ensureAndRun({
  packageName: 'simplicio-mapper',
  version: '0.11.0',
  entrypoint: 'simplicio-mapper',
  args: process.argv.slice(2),
});
