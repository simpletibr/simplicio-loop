#!/usr/bin/env node
/* eslint-disable no-console */
/**
 * check-readme-sync.js — issue #163 (eliminate manual doc mirroring, part 2).
 *
 * README.md and README.pt-BR.md are independent translations, so their
 * heading *text* will never match byte-for-byte -- but their heading
 * *structure* (the sequence of section levels: which headings exist, in
 * what order, at what nesting depth) should stay parallel. This script
 * does NOT try to validate translation quality; it validates structure only
 * (heading level sequence), via a simple edit-distance alignment, so a
 * section added/removed/reordered in one language without its counterpart
 * in the other gets caught mechanically instead of relying on a human
 * noticing during review.
 *
 * Because a real, nonzero amount of structural drift already exists between
 * these two files (see README.pt-BR.md not yet mirroring every section --
 * a known, separately-scoped translation gap, not something this script
 * fixes), this is a *regression* gate, not a *perfection* gate: it compares
 * today's divergence count against a committed baseline
 * (`scripts/readme-sync-baseline.json`) and only fails when the divergence
 * count goes ABOVE the baseline (i.e. someone added new structural drift).
 * Shrinking the baseline (translating more sections into parallel
 * structure) is encouraged and should update the baseline file downward in
 * the same commit.
 *
 * Usage:
 *   node scripts/check-readme-sync.js check    # CI gate
 *   node scripts/check-readme-sync.js report   # print current divergence count, no gate
 *   node scripts/check-readme-sync.js baseline # rewrite the baseline to today's count
 */

"use strict";

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const EN_PATH = path.join(ROOT, "README.md");
const PT_PATH = path.join(ROOT, "README.pt-BR.md");
const BASELINE_PATH = path.join(__dirname, "readme-sync-baseline.json");

const HEADING_RE = /^(#{1,6})\s+/;

/** Extract the sequence of heading levels (1-6) from a markdown file,
 * skipping fenced code blocks so a `#` inside a bash comment/heredoc isn't
 * mistaken for a real heading. */
function extractHeadingLevels(text) {
  const levels = [];
  let inFence = false;
  for (const line of text.split("\n")) {
    if (/^```/.test(line.trim())) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const match = line.match(HEADING_RE);
    if (match) {
      levels.push(match[1].length);
    }
  }
  return levels;
}

/** Levenshtein edit distance between two sequences (arrays of comparable
 * values) -- the number of insertions/deletions/substitutions needed to
 * turn `a` into `b`. Used here on heading-level sequences as a structural
 * divergence score: 0 means the two heading skeletons line up exactly. */
function editDistance(a, b) {
  const m = a.length;
  const n = b.length;
  const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 0; i <= m; i++) dp[i][0] = i;
  for (let j = 0; j <= n; j++) dp[0][j] = j;
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (a[i - 1] === b[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1];
      } else {
        dp[i][j] = 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
      }
    }
  }
  return dp[m][n];
}

function computeDivergence(enText, ptText) {
  const enLevels = extractHeadingLevels(enText);
  const ptLevels = extractHeadingLevels(ptText);
  return {
    distance: editDistance(enLevels, ptLevels),
    enCount: enLevels.length,
    ptCount: ptLevels.length,
  };
}

function readBaseline() {
  if (!fs.existsSync(BASELINE_PATH)) {
    return { max_edit_distance: 0 };
  }
  return JSON.parse(fs.readFileSync(BASELINE_PATH, "utf8"));
}

function writeBaseline(divergence) {
  const payload = {
    schema: "simplicio.readme-sync-baseline/v1",
    max_edit_distance: divergence.distance,
    note:
      "Structural (heading-level-sequence) edit distance between README.md and " +
      "README.pt-BR.md, as of the last `node scripts/check-readme-sync.js baseline` run. " +
      "CI fails if a future PR makes this number go UP; it is fine (encouraged) for it " +
      "to go down as translations catch up structurally.",
  };
  fs.writeFileSync(BASELINE_PATH, JSON.stringify(payload, null, 2) + "\n");
}

function runReport() {
  const divergence = computeDivergence(
    fs.readFileSync(EN_PATH, "utf8"),
    fs.readFileSync(PT_PATH, "utf8"),
  );
  console.log(
    `README.md has ${divergence.enCount} headings, README.pt-BR.md has ${divergence.ptCount}; ` +
      `structural edit distance = ${divergence.distance}`,
  );
  return 0;
}

function runCheck() {
  const divergence = computeDivergence(
    fs.readFileSync(EN_PATH, "utf8"),
    fs.readFileSync(PT_PATH, "utf8"),
  );
  const baseline = readBaseline();
  console.log(
    `README.md/${path.basename(PT_PATH)} structural edit distance: ${divergence.distance} ` +
      `(baseline: ${baseline.max_edit_distance})`,
  );
  if (divergence.distance > baseline.max_edit_distance) {
    console.error(
      `[err] README.md and README.pt-BR.md heading structure diverged further ` +
        `(${divergence.distance} > baseline ${baseline.max_edit_distance}). ` +
        "Add the missing/matching section heading(s) to the other file, or if the " +
        "divergence is intentional, run `node scripts/check-readme-sync.js baseline` " +
        "and commit the updated scripts/readme-sync-baseline.json alongside an explanation.",
    );
    return 1;
  }
  console.log("[ok] README.md/README.pt-BR.md structural divergence within baseline.");
  return 0;
}

function runBaseline() {
  const divergence = computeDivergence(
    fs.readFileSync(EN_PATH, "utf8"),
    fs.readFileSync(PT_PATH, "utf8"),
  );
  writeBaseline(divergence);
  console.log(`[ok] wrote baseline max_edit_distance=${divergence.distance} to ${BASELINE_PATH}`);
  return 0;
}

function main() {
  const mode = process.argv[2] || "check";
  if (mode === "check") return runCheck();
  if (mode === "report") return runReport();
  if (mode === "baseline") return runBaseline();
  console.error(`usage: node ${path.basename(__filename)} check|report|baseline`);
  return 2;
}

if (require.main === module) {
  process.exitCode = main();
}

module.exports = { extractHeadingLevels, editDistance, computeDivergence };
