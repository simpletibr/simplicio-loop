'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: 'inherit',
    env: {
      ...process.env,
      PIP_DISABLE_PIP_VERSION_CHECK: '1',
      PYTHONDONTWRITEBYTECODE: '1',
    },
    ...options,
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    const rendered = [command, ...args].join(' ');
    throw new Error(`command failed (${result.status}): ${rendered}`);
  }
}

function probe(command) {
  const result = spawnSync(command, ['--version'], {
    stdio: 'ignore',
    env: process.env,
  });
  return !result.error && result.status === 0;
}

function findPython() {
  const candidates = [];
  if (process.env.SIMPLICIO_PYTHON) {
    candidates.push(process.env.SIMPLICIO_PYTHON);
  }
  candidates.push('python3', 'python');
  for (const candidate of candidates) {
    if (probe(candidate)) {
      return candidate;
    }
  }
  throw new Error(
    'Python 3 was not found. Set SIMPLICIO_PYTHON or install python3 before running simplicio-mapper.'
  );
}

function sanitizePackageName(name) {
  return name.replace(/[^A-Za-z0-9._-]+/g, '-');
}

function venvRoot(packageName, version) {
  return path.join(os.homedir(), '.cache', 'simplicio-npm', sanitizePackageName(packageName), version);
}

function venvPython(dir) {
  return process.platform === 'win32'
    ? path.join(dir, 'Scripts', 'python.exe')
    : path.join(dir, 'bin', 'python');
}

function entrypointCandidates(dir, entrypoint) {
  if (process.platform === 'win32') {
    return [
      path.join(dir, 'Scripts', `${entrypoint}.exe`),
      path.join(dir, 'Scripts', `${entrypoint}.cmd`),
      path.join(dir, 'Scripts', `${entrypoint}.bat`),
    ];
  }
  return [path.join(dir, 'bin', entrypoint)];
}

function resolveEntrypoint(dir, entrypoint) {
  for (const candidate of entrypointCandidates(dir, entrypoint)) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  throw new Error(`installed entrypoint not found: ${entrypoint}`);
}

function ensureVirtualenv(dir, python) {
  if (fs.existsSync(venvPython(dir))) {
    return;
  }
  fs.mkdirSync(dir, { recursive: true });
  run(python, ['-m', 'venv', dir]);
}

function ensureInstalled(dir, packageName, version) {
  const marker = path.join(dir, '.installed-version');
  const expected = `${packageName}@${version}`;
  if (fs.existsSync(marker) && fs.readFileSync(marker, 'utf8').trim() === expected) {
    return;
  }
  const python = venvPython(dir);
  run(python, ['-m', 'pip', 'install', '--upgrade', 'pip']);
  run(python, ['-m', 'pip', 'install', '--upgrade', `${packageName}==${version}`]);
  fs.writeFileSync(marker, `${expected}\n`);
}

function ensureAndRun({ packageName, version, entrypoint, args }) {
  const python = findPython();
  const root = venvRoot(packageName, version);
  ensureVirtualenv(root, python);
  ensureInstalled(root, packageName, version);
  const command = resolveEntrypoint(root, entrypoint);
  const result = spawnSync(command, args, {
    stdio: 'inherit',
    env: process.env,
  });
  if (result.error) {
    throw result.error;
  }
  process.exit(result.status === null ? 1 : result.status);
}

module.exports = { ensureAndRun };
