#!/usr/bin/env node
/* eslint-disable no-console */
/**
 * check-version-sync.js — legacy Node twin of scripts/check-version-sync.py.
 *
 * Prefer the Python checker (wired in .github/workflows/version-sync.yml).
 * Same contract: package.json, pyproject.toml, and
 * simplicio_mapper/__init__.py must share one SemVer string (issue #102).
 *
 * Exits 0 when all three match, 1 otherwise.
 */
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");

function readPackageVersion() {
  const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
  return pkg.version;
}

function readPyprojectVersion() {
  const text = fs.readFileSync(path.join(ROOT, "pyproject.toml"), "utf8");
  const match = text.match(/^version\s*=\s*"([^"]+)"/m);
  if (!match) {
    throw new Error("could not find `version = \"...\"` in pyproject.toml");
  }
  return match[1];
}

function readInitVersion() {
  const text = fs.readFileSync(path.join(ROOT, "simplicio_mapper", "__init__.py"), "utf8");
  const match = text.match(/^__version__\s*=\s*"([^"]+)"/m);
  if (!match) {
    throw new Error("could not find `__version__ = \"...\"` in simplicio_mapper/__init__.py");
  }
  return match[1];
}

function main() {
  const sources = {
    "package.json": readPackageVersion(),
    "pyproject.toml": readPyprojectVersion(),
    "simplicio_mapper/__init__.py": readInitVersion(),
  };
  const unique = new Set(Object.values(sources));
  if (unique.size === 1) {
    const [version] = unique;
    console.log(`[ok] version ${version} aligned across ${Object.keys(sources).length} sources`);
    return 0;
  }
  console.error("[err] version mismatch across release sources:");
  for (const [file, value] of Object.entries(sources)) {
    console.error(`  ${file.padEnd(36)} ${value}`);
  }
  console.error("\nRelease bumps must update all three files in the same commit.");
  console.error("See .specs/workflow/CONTRIBUTING.md / .specs/workflow/RELEASE.md for the bump checklist.");
  return 1;
}

process.exitCode = main();
