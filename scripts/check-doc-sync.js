#!/usr/bin/env node
/* eslint-disable no-console */
/**
 * check-doc-sync.js — issue #163 (eliminate manual doc mirroring, part 1).
 *
 * AGENTS.md is the canonical source of the agent-instructions content this
 * repo ships for every AI coding tool. `CLAUDE.md`'s own header note says
 * Claude Code needs a *regular file*, not a symlink
 * ("O Claude Code lê arquivo regular, não símbolo") -- so `ln -sf AGENTS.md
 * CLAUDE.md` is not a safe option here (it was tried informally and
 * explicitly documented as unsafe before this script existed). Instead,
 * `CLAUDE.md` is treated as a **generated file**: fixed preamble +
 * AGENTS.md's content verbatim, same pattern already used by
 * `scripts/generate-ecosystem-doc.py` (issue #156) and
 * `scripts/regen_contract_fixtures.py` (issue #157).
 *
 * `.github/copilot-instructions.md` used to be a third hand-copied mirror
 * of the same content (Stack/Comandos/Workflow loop/DoD/Proibido sections
 * duplicated almost verbatim). It is now a short stub that points at
 * AGENTS.md for that shared content and keeps only genuinely
 * Copilot-specific material (Agent Mode custom-agent list, `.github/copilot/
 * agents/` mirror note). This script checks the stub stays short and keeps
 * its required pointer to AGENTS.md, instead of silently regrowing back into
 * a full hand-copy.
 *
 * Usage:
 *   node scripts/check-doc-sync.js check    # CI gate, exit 1 if stale
 *   node scripts/check-doc-sync.js sync     # regenerate CLAUDE.md
 */

"use strict";

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const AGENTS_PATH = path.join(ROOT, "AGENTS.md");
const CLAUDE_PATH = path.join(ROOT, "CLAUDE.md");
const COPILOT_PATH = path.join(ROOT, ".github", "copilot-instructions.md");

// The only hand-maintained part of CLAUDE.md going forward: this preamble
// plus a "---" separator, followed by AGENTS.md's content verbatim.
const CLAUDE_PREAMBLE = `# CLAUDE.md

> Este arquivo espelha [AGENTS.md](./AGENTS.md) e é **gerado**, não editado
> a mão -- veja \`scripts/check-doc-sync.js\` (issue #163). Edite
> \`AGENTS.md\`, depois rode \`node scripts/check-doc-sync.js sync\`. Não é
> um symlink: o próprio Claude Code lê arquivo regular, não símbolo, nesta
> configuração.
>
> Canonical pattern spec: [YOOL_TUPLE_HAMT.md](YOOL_TUPLE_HAMT.md)
>
> Receipt schema reference: [YOOL_TUPLE_HAMT.md §1.8.4](YOOL_TUPLE_HAMT.md#184-receipt-schema-reference)

---

`;

// Structural checks for the copilot-instructions.md stub -- loose on purpose
// (it is allowed genuinely Copilot-specific prose), strict on the two things
// that matter: it must not silently regrow into a full duplicate of
// AGENTS.md's shared sections, and it must keep pointing readers at AGENTS.md.
const COPILOT_MAX_LINES = 140;
const COPILOT_REQUIRED_SNIPPETS = ["AGENTS.md"];

function buildExpectedClaudeMd() {
  const agents = fs.readFileSync(AGENTS_PATH, "utf8");
  return CLAUDE_PREAMBLE + agents;
}

function checkClaudeSync() {
  const expected = buildExpectedClaudeMd();
  if (!fs.existsSync(CLAUDE_PATH)) {
    return { ok: false, reason: "CLAUDE.md is missing." };
  }
  const actual = fs.readFileSync(CLAUDE_PATH, "utf8");
  if (actual !== expected) {
    return {
      ok: false,
      reason:
        "CLAUDE.md does not match AGENTS.md (preamble + verbatim body). " +
        "Run `node scripts/check-doc-sync.js sync` and commit the result.",
    };
  }
  return { ok: true };
}

function checkCopilotStub() {
  if (!fs.existsSync(COPILOT_PATH)) {
    return { ok: false, reason: ".github/copilot-instructions.md is missing." };
  }
  const text = fs.readFileSync(COPILOT_PATH, "utf8");
  const lineCount = text.split("\n").length;
  const problems = [];
  if (lineCount > COPILOT_MAX_LINES) {
    problems.push(
      `.github/copilot-instructions.md has ${lineCount} lines (limit ${COPILOT_MAX_LINES}) -- ` +
        "it looks like it grew back into a hand-copy of AGENTS.md's shared sections " +
        "(Stack/Comandos/Workflow loop/DoD/Proibido) instead of pointing at them. " +
        "Keep only genuinely Copilot-specific content (Agent Mode / .github/copilot/agents/) " +
        "and link to AGENTS.md for the rest (issue #163).",
    );
  }
  const lowerText = text.toLowerCase();
  for (const snippet of COPILOT_REQUIRED_SNIPPETS) {
    if (!lowerText.includes(snippet.toLowerCase())) {
      problems.push(`.github/copilot-instructions.md no longer mentions "${snippet}".`);
    }
  }
  if (problems.length > 0) {
    return { ok: false, reason: problems.join("\n") };
  }
  return { ok: true };
}

function runCheck() {
  const claude = checkClaudeSync();
  const copilot = checkCopilotStub();
  const failures = [claude, copilot].filter((r) => !r.ok);
  if (failures.length === 0) {
    console.log("[ok] CLAUDE.md is in sync with AGENTS.md; copilot-instructions.md stays a short stub.");
    return 0;
  }
  console.error("[err] doc-sync check failed:");
  for (const failure of failures) {
    console.error(`  - ${failure.reason}`);
  }
  return 1;
}

function runSync() {
  fs.writeFileSync(CLAUDE_PATH, buildExpectedClaudeMd());
  console.log("[ok] regenerated CLAUDE.md from AGENTS.md.");
  return 0;
}

function main() {
  const mode = process.argv[2] || "check";
  if (mode === "check") {
    return runCheck();
  }
  if (mode === "sync") {
    return runSync();
  }
  console.error(`usage: node ${path.basename(__filename)} check|sync`);
  return 2;
}

process.exitCode = main();
