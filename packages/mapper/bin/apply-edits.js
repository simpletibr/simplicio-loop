#!/usr/bin/env node
'use strict';

/*
 * Deterministic JSON-driven file edit executor.
 *
 * Motivation: mechanical edits (rename a key, bump a version, insert a block)
 * do not need an LLM. Describe the operations in JSON once and apply them with
 * zero token cost, in milliseconds, deterministically and reversibly.
 *
 * The recommended hybrid flow: an LLM decides WHAT to do once and emits this
 * JSON; this executor applies it for free as many times as needed.
 *
 * Usage:
 *   node bin/apply-edits.js <edits.json> [--root <dir>] [--dry-run] [--json]
 *
 * Edit file shape:
 *   {
 *     "version": 1,
 *     "edits": [
 *       { "file": "a.ts", "op": "replace", "find": "x", "replace": "y", "count": 1 },
 *       { "file": "a.ts", "op": "regex_replace", "pattern": "v\\d+", "replacement": "v2", "flags": "g" },
 *       { "file": "new.txt", "op": "create", "content": "hi\n", "overwrite": false },
 *       { "file": "a.md", "op": "append", "content": "\nfoot\n" },
 *       { "file": "a.md", "op": "prepend", "content": "head\n" },
 *       { "file": "a.md", "op": "insert_after", "anchor": "## S", "content": "line\n" },
 *       { "file": "a.md", "op": "insert_before", "anchor": "## E", "content": "line\n" },
 *       { "file": "old.txt", "op": "delete_file" }
 *     ]
 *   }
 *
 * Transactional: every operation is validated against the current file
 * contents before anything is written. If any operation is invalid, nothing
 * is written and the process exits non-zero.
 */

const fs = require('node:fs');
const path = require('node:path');

const SUPPORTED_OPS = new Set([
  'replace',
  'regex_replace',
  'create',
  'append',
  'prepend',
  'insert_after',
  'insert_before',
  'delete_file',
]);

class EditError extends Error {}

/**
 * Resolve a user-supplied relative path against root and refuse to escape it.
 */
function resolveSafe(root, rel, index) {
  if (typeof rel !== 'string' || rel.length === 0) {
    throw new EditError(`edit[${index}]: "file" must be a non-empty string`);
  }
  if (path.isAbsolute(rel)) {
    throw new EditError(`edit[${index}]: "file" must be relative, got "${rel}"`);
  }
  const full = path.resolve(root, rel);
  const rootResolved = path.resolve(root);
  const prefix = rootResolved.endsWith(path.sep) ? rootResolved : rootResolved + path.sep;
  if (full !== rootResolved && !full.startsWith(prefix)) {
    throw new EditError(`edit[${index}]: "file" escapes root: "${rel}"`);
  }
  return full;
}

function readIfExists(full) {
  try {
    return fs.readFileSync(full, 'utf8');
  } catch (err) {
    if (err.code === 'ENOENT') return null;
    throw err;
  }
}

function requireString(edit, field, index) {
  if (typeof edit[field] !== 'string') {
    throw new EditError(`edit[${index}] (${edit.op}): "${field}" must be a string`);
  }
  return edit[field];
}

/**
 * Read a single edit and compute its plan from disk.
 * Returns { full, action, before, after } where action is write|delete|noop.
 */
function planEdit(root, edit, index) {
  const full = resolveSafe(root, edit && edit.file, index);
  const current = readIfExists(full);
  return computePlan(edit, index, full, current);
}

/**
 * Pure planner: given an edit, its target path and the CURRENT content
 * (string, or null if the file does not exist), compute the next content.
 * No disk access — used for both fresh reads and in-batch chaining.
 */
function computePlan(edit, index, full, current) {
  if (!edit || typeof edit !== 'object' || Array.isArray(edit)) {
    throw new EditError(`edit[${index}] must be an object`);
  }
  if (!SUPPORTED_OPS.has(edit.op)) {
    throw new EditError(
      `edit[${index}]: unsupported op "${edit.op}". Supported: ${[...SUPPORTED_OPS].join(', ')}`
    );
  }

  switch (edit.op) {
    case 'create': {
      const content = requireString(edit, 'content', index);
      const overwrite = edit.overwrite === true;
      if (current !== null && !overwrite) {
        throw new EditError(
          `edit[${index}] (create): "${edit.file}" already exists (set "overwrite": true to replace)`
        );
      }
      return { full, action: 'write', before: current, after: content };
    }

    case 'delete_file': {
      if (current === null) {
        if (edit.ignoreMissing === true) {
          return { full, action: 'noop', before: null, after: null };
        }
        throw new EditError(`edit[${index}] (delete_file): "${edit.file}" does not exist`);
      }
      return { full, action: 'delete', before: current, after: null };
    }

    case 'append':
    case 'prepend': {
      const content = requireString(edit, 'content', index);
      const base = current === null ? '' : current;
      const after = edit.op === 'append' ? base + content : content + base;
      return { full, action: 'write', before: current, after };
    }
  }

  // Remaining ops need an existing file.
  if (current === null) {
    throw new EditError(`edit[${index}] (${edit.op}): "${edit.file}" does not exist`);
  }

  switch (edit.op) {
    case 'replace': {
      const find = requireString(edit, 'find', index);
      const replace = requireString(edit, 'replace', index);
      if (find.length === 0) {
        throw new EditError(`edit[${index}] (replace): "find" must not be empty`);
      }
      const occurrences = countOccurrences(current, find);
      if (occurrences === 0) {
        throw new EditError(`edit[${index}] (replace): "find" not found in "${edit.file}"`);
      }
      // count: number of occurrences to replace; 0 or "all" means every match.
      const limit =
        edit.count === undefined || edit.count === 'all' || edit.count === 0
          ? Infinity
          : edit.count;
      if (limit !== Infinity && (!Number.isInteger(limit) || limit < 0)) {
        throw new EditError(`edit[${index}] (replace): "count" must be a non-negative integer or "all"`);
      }
      const after = replaceN(current, find, replace, limit);
      return { full, action: 'write', before: current, after };
    }

    case 'regex_replace': {
      const pattern = requireString(edit, 'pattern', index);
      const replacement = requireString(edit, 'replacement', index);
      const flags = edit.flags === undefined ? 'g' : edit.flags;
      if (typeof flags !== 'string') {
        throw new EditError(`edit[${index}] (regex_replace): "flags" must be a string`);
      }
      let re;
      try {
        re = new RegExp(pattern, flags);
      } catch (err) {
        throw new EditError(`edit[${index}] (regex_replace): invalid pattern/flags: ${err.message}`);
      }
      if (!re.test(current)) {
        throw new EditError(`edit[${index}] (regex_replace): pattern did not match in "${edit.file}"`);
      }
      re.lastIndex = 0;
      const after = current.replace(re, replacement);
      return { full, action: 'write', before: current, after };
    }

    case 'insert_after':
    case 'insert_before': {
      const anchor = requireString(edit, 'anchor', index);
      const content = requireString(edit, 'content', index);
      if (anchor.length === 0) {
        throw new EditError(`edit[${index}] (${edit.op}): "anchor" must not be empty`);
      }
      const at = current.indexOf(anchor);
      if (at === -1) {
        throw new EditError(`edit[${index}] (${edit.op}): "anchor" not found in "${edit.file}"`);
      }
      const cut = edit.op === 'insert_after' ? at + anchor.length : at;
      const after = current.slice(0, cut) + content + current.slice(cut);
      return { full, action: 'write', before: current, after };
    }

    default:
      // Unreachable: op was validated above.
      throw new EditError(`edit[${index}]: unhandled op "${edit.op}"`);
  }
}

function countOccurrences(haystack, needle) {
  let count = 0;
  let from = 0;
  for (;;) {
    const idx = haystack.indexOf(needle, from);
    if (idx === -1) break;
    count += 1;
    from = idx + needle.length;
  }
  return count;
}

function replaceN(haystack, needle, replacement, limit) {
  let result = '';
  let from = 0;
  let done = 0;
  for (;;) {
    if (done >= limit) {
      result += haystack.slice(from);
      break;
    }
    const idx = haystack.indexOf(needle, from);
    if (idx === -1) {
      result += haystack.slice(from);
      break;
    }
    result += haystack.slice(from, idx) + replacement;
    from = idx + needle.length;
    done += 1;
  }
  return result;
}

/**
 * Plan and (unless dryRun) apply a parsed edit document.
 * Returns a report object.
 */
function applyEdits(doc, { root = process.cwd(), dryRun = false } = {}) {
  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) {
    throw new EditError('edit document must be a JSON object');
  }
  if (doc.version !== undefined && doc.version !== 1) {
    throw new EditError(`unsupported version ${doc.version} (expected 1)`);
  }
  if (!Array.isArray(doc.edits)) {
    throw new EditError('edit document must have an "edits" array');
  }

  // Phase 1: plan + validate everything against the evolving in-memory state
  // so that intra-batch edits to the same file compose correctly.
  const memory = new Map(); // full -> current string or null (deleted)
  const plans = [];
  for (let i = 0; i < doc.edits.length; i += 1) {
    const edit = doc.edits[i];
    const full = resolveSafe(root, edit && edit.file, i);
    // Chain against in-memory state when this file was touched earlier in the
    // batch; otherwise read from disk once and cache it.
    const current = memory.has(full) ? memory.get(full) : readIfExists(full);
    const plan = computePlan(edit, i, full, current);
    memory.set(full, plan.action === 'delete' ? null : plan.after);
    plans.push({ ...plan, op: edit.op, file: edit.file });
  }

  // Phase 2: apply (skipped on dry-run).
  const applied = [];
  for (const plan of plans) {
    const entry = {
      file: plan.file,
      op: plan.op,
      action: plan.action,
      changed: plan.action === 'delete' ? plan.before !== null : plan.before !== plan.after,
    };
    if (!dryRun) {
      if (plan.action === 'delete') {
        fs.rmSync(plan.full, { force: true });
      } else if (plan.action === 'write') {
        fs.mkdirSync(path.dirname(plan.full), { recursive: true });
        fs.writeFileSync(plan.full, plan.after);
      }
      // 'noop' writes nothing.
    }
    applied.push(entry);
  }

  return {
    ok: true,
    dryRun,
    root: path.resolve(root),
    count: applied.length,
    changed: applied.filter((e) => e.changed).length,
    edits: applied,
  };
}

function parseArgs(argv) {
  const args = { _: [], root: process.cwd(), dryRun: false, json: false };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--dry-run') args.dryRun = true;
    else if (a === '--json') args.json = true;
    else if (a === '--root') args.root = argv[++i];
    else if (a === '-h' || a === '--help') args.help = true;
    else args._.push(a);
  }
  return args;
}

const HELP = `apply-edits — deterministic JSON-driven file editor

Usage:
  node bin/apply-edits.js <edits.json> [options]

Options:
  --root <dir>   Base directory for relative paths (default: cwd)
  --dry-run      Validate and report without writing
  --json         Emit the report as JSON
  -h, --help     Show this help

Ops: replace, regex_replace, create, append, prepend,
     insert_after, insert_before, delete_file

Mechanical edits cost zero tokens and run in milliseconds. Use an LLM only to
generate this JSON once; replay it for free.`;

function main(argv) {
  const args = parseArgs(argv);
  if (args.help || args._.length === 0) {
    process.stdout.write(HELP + '\n');
    return args.help ? 0 : 1;
  }
  const editsPath = args._[0];
  let raw;
  try {
    raw = fs.readFileSync(editsPath, 'utf8');
  } catch (err) {
    process.stderr.write(`error: cannot read "${editsPath}": ${err.message}\n`);
    return 1;
  }
  let doc;
  try {
    doc = JSON.parse(raw);
  } catch (err) {
    process.stderr.write(`error: invalid JSON in "${editsPath}": ${err.message}\n`);
    return 1;
  }
  let report;
  try {
    report = applyEdits(doc, { root: args.root, dryRun: args.dryRun });
  } catch (err) {
    if (err instanceof EditError) {
      process.stderr.write(`error: ${err.message}\n`);
      return 2;
    }
    throw err;
  }
  if (args.json) {
    process.stdout.write(JSON.stringify(report, null, 2) + '\n');
  } else {
    const tag = report.dryRun ? '[dry-run] ' : '';
    for (const e of report.edits) {
      const mark = e.changed ? 'changed' : 'no-op';
      process.stdout.write(`${tag}${e.op} ${e.file} -> ${e.action} (${mark})\n`);
    }
    process.stdout.write(`${tag}${report.changed}/${report.count} edits changed files\n`);
  }
  return 0;
}

if (require.main === module) {
  process.exit(main(process.argv.slice(2)));
}

module.exports = { applyEdits, planEdit, computePlan, parseArgs, main, EditError, SUPPORTED_OPS };
