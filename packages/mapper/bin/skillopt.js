#!/usr/bin/env node
'use strict';

/*
 * skillopt — optimize a natural-language skill document with the SkillOpt loop
 * (Rollout -> Reflect -> Edit -> Gate). See scripts/skillopt/engine.js and
 * https://microsoft.github.io/SkillOpt/.
 *
 * The skill document is the only trainable artifact; the target model stays
 * frozen. The optimizer accepts only edits that improve a held-out split.
 */

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const engine = require('../scripts/skillopt/engine.js');

const argv = process.argv.slice(2);

function printHelp() {
  console.log(`skillopt

Optimize a skill document with the SkillOpt loop (Rollout -> Reflect -> Edit -> Gate).
The skill markdown is the only trainable artifact; the target model stays frozen.

USAGE
  skillopt --suite <suite.json> [options]

OPTIONS
  --suite <file>     Task suite JSON: { skill?, rounds?, budget?, tasks: [...] } (required)
  --skill <file>     Initial skill document (overrides suite.skill)
  --out <file>       Where to write the optimized skill (default: best_skill.md)
  --report <file>    Write the run report as JSON
  --rounds <n>       Max optimization rounds (overrides suite.rounds)
  --budget <n>       Edit budget per round / textual learning rate (overrides suite.budget)
  --no-receipt       Do not write a .catalog/receipts/<sha>.json execution receipt
  --json             Print the full run report as JSON to stdout
  -h, --help         Show this help

SUITE TASK SHAPE
  { "id": "t1", "split": "train"|"holdout",
    "requires": ["directive that must appear"],
    "forbids":  ["directive that must not appear"] }

EXAMPLES
  skillopt --suite skillopt.suite.json
  skillopt --suite suite.json --skill .skills/foo/SKILL.md --out best_skill.md --report report.json
`);
}

function parseArgs(args) {
  const opts = { receipt: true, json: false };
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    switch (arg) {
      case '-h':
      case '--help': opts.help = true; break;
      case '--suite': opts.suite = args[++i]; break;
      case '--skill': opts.skill = args[++i]; break;
      case '--out': opts.out = args[++i]; break;
      case '--report': opts.report = args[++i]; break;
      case '--rounds': opts.rounds = Number.parseInt(args[++i], 10); break;
      case '--budget': opts.budget = Number.parseInt(args[++i], 10); break;
      case '--no-receipt': opts.receipt = false; break;
      case '--json': opts.json = true; break;
      default:
        if (arg.startsWith('-')) {
          console.error(`Unknown option: ${arg}`);
          process.exit(2);
        }
        if (!opts.suite) opts.suite = arg;
    }
  }
  return opts;
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function countAcceptedEdits(report) {
  return report.history
    .filter((h) => h.accepted)
    .reduce((sum, h) => sum + h.edits.length, 0);
}

function writeReceipt(report, opts) {
  const receiptsDir = path.join(process.cwd(), '.catalog', 'receipts');
  const body = {
    yool_id: 'agent.opt.skillopt',
    status: report.exitSignal ? 'ok' : 'partial',
    created_at: new Date().toISOString(),
    skill_out: opts.out,
    scores: report.scores,
    rounds: report.rounds,
    accepted_edits: countAcceptedEdits(report),
    rejected_edits: report.rejectedEdits.length,
    cost: { tokens: 0, usd: 0 },
  };
  const hash = crypto.createHash('sha256').update(JSON.stringify(body)).digest('hex');
  const receipt = { id: `sha256:${hash}`, tuple_id: `sha256:${hash}`, ...body, artifacts: [] };
  fs.mkdirSync(receiptsDir, { recursive: true });
  const file = path.join(receiptsDir, `${hash}.json`);
  fs.writeFileSync(file, `${JSON.stringify(receipt, null, 2)}\n`);
  return file;
}

function main() {
  const opts = parseArgs(argv);
  if (opts.help || argv.length === 0) {
    printHelp();
    process.exit(opts.help ? 0 : 2);
  }
  if (!opts.suite) {
    console.error('Missing required --suite <file>. See --help.');
    process.exit(2);
  }
  if (!fs.existsSync(opts.suite)) {
    console.error(`Suite file not found: ${opts.suite}`);
    process.exit(2);
  }

  let suite;
  try {
    suite = readJson(opts.suite);
  } catch (err) {
    console.error(`Invalid suite JSON ${opts.suite}: ${err.message}`);
    process.exit(2);
  }

  const skillPath = opts.skill || suite.skill;
  if (!skillPath) {
    console.error('No skill document given. Set --skill or "skill" in the suite.');
    process.exit(2);
  }
  const resolvedSkill = path.isAbsolute(skillPath)
    ? skillPath
    : path.resolve(path.dirname(path.resolve(opts.suite)), skillPath);
  const skillFile = fs.existsSync(resolvedSkill) ? resolvedSkill : path.resolve(skillPath);
  if (!fs.existsSync(skillFile)) {
    console.error(`Skill document not found: ${skillPath}`);
    process.exit(2);
  }
  const skill = fs.readFileSync(skillFile, 'utf8');

  if (suite && typeof suite === 'object') {
    if (Number.isInteger(opts.rounds)) suite.rounds = opts.rounds;
    if (Number.isInteger(opts.budget)) suite.budget = opts.budget;
  }

  let report;
  try {
    report = engine.optimize(skill, suite);
  } catch (err) {
    console.error(`SkillOpt run failed: ${err.message}`);
    process.exit(2);
  }

  const outPath = opts.out || 'best_skill.md';
  opts.out = outPath;
  fs.mkdirSync(path.dirname(path.resolve(outPath)), { recursive: true });
  fs.writeFileSync(outPath, report.bestSkill.endsWith('\n') ? report.bestSkill : `${report.bestSkill}\n`);

  if (opts.report) {
    fs.mkdirSync(path.dirname(path.resolve(opts.report)), { recursive: true });
    fs.writeFileSync(opts.report, `${JSON.stringify(report, null, 2)}\n`);
  }

  let receiptFile;
  if (opts.receipt) {
    try {
      receiptFile = writeReceipt(report, opts);
    } catch (err) {
      console.error(`Could not write receipt: ${err.message}`);
    }
  }

  if (opts.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    const s = report.scores;
    console.log('SkillOpt run complete');
    console.log(`  skill in    : ${path.relative(process.cwd(), skillFile)}`);
    console.log(`  skill out   : ${outPath}`);
    console.log(`  rounds      : ${report.rounds}`);
    console.log(`  gate score  : ${s.initial.gate} -> ${s.best.gate} (Δ ${s.improvement >= 0 ? '+' : ''}${s.improvement})`);
    console.log(`  train score : ${s.initial.train} -> ${s.best.train}`);
    console.log(`  pass rate   : train ${s.best.trainPassRate}, gate ${s.best.gatePassRate}`);
    console.log(`  edits       : ${countAcceptedEdits(report)} accepted, ${report.rejectedEdits.length} rejected`);
    console.log(`  held-out    : ${s.usedHoldout ? 'yes' : 'no (gated on train)'}`);
    if (receiptFile) console.log(`  receipt     : ${path.relative(process.cwd(), receiptFile)}`);
    console.log(`  EXIT_SIGNAL : ${report.exitSignal}`);
  }

  process.exit(0);
}

main();
