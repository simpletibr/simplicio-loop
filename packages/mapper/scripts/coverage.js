#!/usr/bin/env node
'use strict';

// Runs the Node.js built-in test runner with V8 coverage and converts the
// "all files" summary row into coverage/coverage-summary.json (Istanbul
// json-summary shape) so the DoD gate can read total.lines.pct.
//
// Parses the textual coverage table instead of the lcov reporter so it works
// across the Node 20 and 22 CI matrix (the lcov reporter is not available on
// every supported version). Dependency-free.

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const COVERAGE_DIR = path.resolve(process.cwd(), 'coverage');
const SUMMARY_PATH = path.join(COVERAGE_DIR, 'coverage-summary.json');

function unitTestFiles(dir) {
  const files = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...unitTestFiles(full));
    else if (entry.isFile() && entry.name.endsWith('.test.js')) files.push(full);
  }
  return files.sort();
}

fs.mkdirSync(COVERAGE_DIR, { recursive: true });

const result = spawnSync(
  process.execPath,
  // The committed evaluation corpus contains TypeScript fixtures that are
  // inputs to the mapper, not Node tests for this package. Restricting this
  // coverage command to the maintained unit suite keeps the gate portable
  // across Node 20 and newer runtimes while the fixture harness remains
  // covered by the Python compatibility tests.
  ['--test', '--experimental-test-coverage', ...unitTestFiles(path.resolve(process.cwd(), 'tests/unit'))],
  { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 },
);

if (result.error) {
  console.error(`coverage run failed to start: ${result.error.message}`);
  process.exit(1);
}

const stdout = result.stdout || '';
const stderr = result.stderr || '';
process.stdout.write(stdout);
if (stderr) process.stderr.write(stderr);

// Matches the summary row, tolerating the "# " (tap) or "ℹ " (spec) prefix:
//   all files | 91.32 | 69.97 | 88.39 |
const match = stdout.match(/all files\s*\|\s*([0-9.]+)\s*\|\s*([0-9.]+)\s*\|\s*([0-9.]+)/);

if (!match) {
  if (result.status !== 0) process.exit(result.status);
  console.error('::error::could not parse coverage summary row from test output');
  process.exit(1);
}

const linesPct = Number(match[1]);
const branchesPct = Number(match[2]);
const functionsPct = Number(match[3]);
const metric = (pct) => ({ total: 0, covered: 0, skipped: 0, pct });

const summary = {
  total: {
    lines: metric(linesPct),
    statements: metric(linesPct),
    functions: metric(functionsPct),
    branches: metric(branchesPct),
  },
};

fs.writeFileSync(SUMMARY_PATH, JSON.stringify(summary, null, 2) + '\n');
console.log(`coverage summary written to ${path.relative(process.cwd(), SUMMARY_PATH)} `
  + `(lines ${linesPct}%, functions ${functionsPct}%, branches ${branchesPct}%)`);

process.exit(result.status === null ? 1 : result.status);
