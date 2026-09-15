#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { writeMappingArtifacts } = require('./mapper-artifacts');

// NOTE (issues #144, #148, #149): the Python CLI (`simplicio_mapper/cli.py`)
// supports `--for-llm toon` on `index`/`inspect`/`handoff`/`ask`, backed by
// `simplicio_mapper/toon.py` (a TOON — Token-Oriented Object Notation —
// encoder/decoder, https://github.com/toon-format/toon; spec + conformance
// corpus: ../TOON-CONTRACT.md, ../fixtures/toon-golden/). This Node mirror
// has no `index`/`inspect`/`handoff`/`ask`/`--json` command surface to hook
// a `--for-llm` flag into yet (it only writes artifacts, it does not print
// JSON payloads), so a Node port of `encode_toon`/`decode_toon` is
// explicitly re-scoped out of #148/#149 rather than attempted here — Node
// parity remains pending. When it lands, it must pass
// `fixtures/toon-golden/` (see `tests/unit/toon-contract.test.js`, which
// currently reports a labeled skip for exactly this reason) and be wired
// through a Node counterpart of `scripts/toon_contract_runner.py`.

function readJsonSafe(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return {};
  }
}

function printHelp() {
  console.log(`llm-project-mapper map

Generate or update machine-readable mapper artifacts.

USAGE
  llm-project-mapper map [--root <dir>] [--incremental] [--watch]
  llm-project-mapper update [--root <dir>] [--watch]

OPTIONS
  --root <dir>          Project root to map. Defaults to cwd.
  --stack <name>        Stack hint when .starter-meta.json is absent.
  --product-name <name> Product name hint when .starter-meta.json is absent.
  --out <dir>           Artifact directory. Defaults to .simplicio.
  --incremental         Record changed files and update existing artifacts.
  --watch               Re-run mapping when local files change.
  --silent              Minimal output.
  -h, --help            Show this help
`);
}

function parseArgs(argv) {
  const opts = {
    root: process.cwd(),
    out: '.simplicio',
    stack: '',
    productName: '',
    incremental: false,
    watch: false,
    silent: false,
  };
  const command = argv[0] === 'update' ? 'update' : 'map';
  if (command === 'update') opts.incremental = true;
  for (let i = 1; i < argv.length; i++) {
    const arg = argv[i];
    switch (arg) {
      case '--root': opts.root = argv[++i]; break;
      case '--out': opts.out = argv[++i]; break;
      case '--stack': opts.stack = argv[++i]; break;
      case '--product-name': opts.productName = argv[++i]; break;
      case '--incremental': opts.incremental = true; break;
      case '--sync': opts.sync = true; break;
      case '--watch': opts.watch = true; break;
      case '--silent': opts.silent = true; break;
      case '-h':
      case '--help':
        printHelp();
        process.exit(0);
        break;
      default:
        console.error(`Unknown map option: ${arg}`);
        console.error('Run `llm-project-mapper map --help` for usage.');
        process.exit(2);
    }
  }
  return opts;
}

function runOnce(opts) {
  const root = path.resolve(opts.root);
  const metaPath = path.join(root, '.starter-meta.json');
  const meta = {
    ...readJsonSafe(metaPath),
  };
  if (opts.stack) meta.stack = opts.stack;
  if (opts.productName) meta.product_name = opts.productName;
  const log = opts.silent ? () => {} : (line) => console.log(line);
  return writeMappingArtifacts({
    cwd: root,
    meta,
    incremental: opts.incremental,
    outputDir: opts.out,
    log,
  });
}

function runMapCli(argv = process.argv.slice(2)) {
  const opts = parseArgs(argv);
  runOnce(opts);
  if (!opts.watch) return 0;

  const root = path.resolve(opts.root);
  console.log(`watching ${root} for mapper updates...`);
  let timer = null;
  fs.watch(root, { recursive: true }, (_event, filename) => {
    if (!filename) return;
    const rel = String(filename).split(path.sep).join('/');
    if (rel.startsWith('.git/') || rel.startsWith('.simplicio/') || rel.includes('/node_modules/')) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      try {
        runOnce({ ...opts, incremental: true });
      } catch (error) {
        console.error(`map update failed: ${error && error.message ? error.message : error}`);
      }
    }, 250);
  });
  return 0;
}

if (require.main === module) {
  try {
    runMapCli();
  } catch (error) {
    console.error(error && error.stack ? error.stack : error);
    process.exit(1);
  }
}

module.exports = {
  parseArgs,
  runMapCli,
};
