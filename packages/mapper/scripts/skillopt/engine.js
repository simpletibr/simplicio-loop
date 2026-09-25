'use strict';

/*
 * SkillOpt engine — Microsoft Research "Executive Strategy for Self-Evolving
 * Agent Skills" (https://microsoft.github.io/SkillOpt/), realized as a
 * dependency-free, deterministic optimizer over natural-language skill docs.
 *
 * The frozen target model is never modified. The skill document is the only
 * trainable artifact. Each round runs the four SkillOpt stages:
 *
 *   1. Rollout — score the current skill on the train split.
 *   2. Reflect — turn failure/success batches into candidate edits.
 *   3. Edit    — apply up to `budget` ops (the "textual learning rate"),
 *                skipping any op already in the rejected-edit buffer.
 *   4. Gate    — keep the candidate only if it improves the held-out split;
 *                otherwise its edits are buffered as negative feedback.
 *
 * Rollout scoring is pluggable. The default scorer is deterministic: a task
 * passes when the skill contains every `requires` directive and none of the
 * `forbids` directives. Real LLM adapters can replace `opts.scorer` without
 * touching the loop.
 */

const EPS = 1e-9;

function normalize(text) {
  return String(text).toLowerCase().replace(/\s+/g, ' ').trim();
}

function toLines(skill) {
  if (Array.isArray(skill)) return skill.slice();
  return String(skill).split('\n');
}

function skillText(lines) {
  return toLines(lines).join('\n');
}

function containsDirective(lines, directive) {
  const haystack = normalize(skillText(lines));
  const needle = normalize(directive);
  return needle.length > 0 && haystack.includes(needle);
}

/**
 * Default deterministic rollout scorer for a single task.
 * @returns {{score:number, pass:boolean, missing:string[], offending:string[]}}
 */
function scoreTask(lines, task) {
  const requires = Array.isArray(task.requires) ? task.requires : [];
  const forbids = Array.isArray(task.forbids) ? task.forbids : [];
  const missing = requires.filter((d) => !containsDirective(lines, d));
  const offending = forbids.filter((d) => containsDirective(lines, d));
  const total = requires.length + forbids.length;
  const satisfied = (requires.length - missing.length) + (forbids.length - offending.length);
  const score = total === 0 ? 1 : satisfied / total;
  return { score, pass: score >= 1 - EPS, missing, offending };
}

function evaluateSplit(lines, tasks, scorer) {
  const score = scorer || scoreTask;
  if (!tasks.length) {
    return { meanScore: 1, passRate: 1, results: [] };
  }
  const results = tasks.map((task) => ({ task, ...score(lines, task) }));
  const meanScore = results.reduce((sum, r) => sum + r.score, 0) / results.length;
  const passRate = results.filter((r) => r.pass).length / results.length;
  return { meanScore, passRate, results };
}

function editSignature(edit) {
  if (edit.op === 'replace') return `replace:${normalize(edit.from)}=>${normalize(edit.to)}`;
  return `${edit.op}:${normalize(edit.directive)}`;
}

/**
 * Reflect stage: derive candidate edits from a rollout batch.
 * Adds missing required directives, deletes present forbidden directives.
 * Candidates are ranked by frequency (desc) then text (asc) for determinism.
 * @returns {Array<{op:string, directive:string, signature:string, reason:string, weight:number}>}
 */
function reflect(lines, rolloutResults) {
  const addCounts = new Map();
  const delCounts = new Map();
  for (const r of rolloutResults) {
    if (r.pass) continue;
    for (const d of r.missing) addCounts.set(d, (addCounts.get(d) || 0) + 1);
    for (const d of r.offending) delCounts.set(d, (delCounts.get(d) || 0) + 1);
  }
  const candidates = [];
  for (const [directive, weight] of addCounts) {
    candidates.push({ op: 'add', directive, weight, reason: 'missing required directive' });
  }
  for (const [directive, weight] of delCounts) {
    candidates.push({ op: 'delete', directive, weight, reason: 'forbidden directive present' });
  }
  candidates.sort((a, b) => {
    if (b.weight !== a.weight) return b.weight - a.weight;
    if (a.op !== b.op) return a.op < b.op ? -1 : 1;
    return normalize(a.directive) < normalize(b.directive) ? -1 : 1;
  });
  for (const c of candidates) c.signature = editSignature(c);
  return candidates;
}

const MANAGED_HEADER = '## SkillOpt Directives';

function applyEdit(lines, edit) {
  let out = toLines(lines);
  if (edit.op === 'delete') {
    const needle = normalize(edit.directive);
    out = out.filter((line) => !(needle && normalize(line).includes(needle)));
    return out;
  }
  if (edit.op === 'replace') {
    const from = normalize(edit.from);
    return out.map((line) => (from && normalize(line).includes(from)
      ? line.replace(new RegExp(escapeRegExp(edit.from), 'gi'), edit.to)
      : line));
  }
  if (edit.op === 'add') {
    if (containsDirective(out, edit.directive)) return out;
    if (!out.includes(MANAGED_HEADER)) {
      if (out.length && out[out.length - 1].trim() !== '') out.push('');
      out.push(MANAGED_HEADER, '');
    }
    out.push(`- ${edit.directive}`);
    return out;
  }
  throw new Error(`unknown edit op: ${edit.op}`);
}

function escapeRegExp(text) {
  return String(text).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function applyEdits(lines, edits) {
  return edits.reduce((acc, edit) => applyEdit(acc, edit), toLines(lines));
}

function splitTasks(tasks) {
  const train = [];
  const holdout = [];
  for (const task of tasks) {
    if (task.split === 'holdout' || task.split === 'test' || task.split === 'val') holdout.push(task);
    else train.push(task);
  }
  return { train, holdout };
}

/**
 * Run the full SkillOpt loop.
 * @param {string|string[]} skill initial skill document
 * @param {{tasks:object[], rounds?:number, budget?:number}} suite
 * @param {{scorer?:Function}} [opts]
 */
function optimize(skill, suite, opts = {}) {
  const scorer = opts.scorer || scoreTask;
  suite = suite && typeof suite === 'object' ? suite : {};
  const tasks = (Array.isArray(suite.tasks) ? suite.tasks : [])
    .filter((t) => t && typeof t === 'object');
  const rounds = Number.isInteger(suite.rounds) ? suite.rounds : 8;
  const budget = Number.isInteger(suite.budget) && suite.budget > 0 ? suite.budget : 2;
  const { train, holdout } = splitTasks(tasks);
  const gateTasks = holdout.length ? holdout : train;

  let best = toLines(skill);
  let current = best;
  let bestGate = evaluateSplit(best, gateTasks, scorer).meanScore;
  const initialGate = bestGate;
  const initialTrain = evaluateSplit(best, train, scorer).meanScore;

  const rejected = new Set();
  const history = [];
  let exitSignal = false;
  let converged = false;

  for (let round = 1; round <= rounds; round += 1) {
    const trainEval = evaluateSplit(current, train, scorer);
    const gateEval = evaluateSplit(current, gateTasks, scorer);
    if (trainEval.passRate >= 1 - EPS && gateEval.passRate >= 1 - EPS) {
      exitSignal = true;
      break;
    }

    const candidates = reflect(current, trainEval.results)
      .filter((c) => !rejected.has(c.signature));
    if (!candidates.length) {
      converged = true;
      break;
    }

    const selected = candidates.slice(0, budget);
    const candidate = applyEdits(current, selected);
    const candidateGate = evaluateSplit(candidate, gateTasks, scorer).meanScore;

    const accepted = candidateGate > bestGate + EPS;
    if (accepted) {
      best = candidate;
      current = candidate;
      bestGate = candidateGate;
    } else {
      for (const edit of selected) rejected.add(edit.signature);
      current = best;
    }

    history.push({
      round,
      edits: selected.map((e) => ({ op: e.op, directive: e.directive, reason: e.reason })),
      accepted,
      gateScore: Number(candidateGate.toFixed(6)),
      bestGateScore: Number(bestGate.toFixed(6)),
    });
  }

  const finalTrain = evaluateSplit(best, train, scorer);
  const finalGate = evaluateSplit(best, gateTasks, scorer);
  if (finalTrain.passRate >= 1 - EPS && finalGate.passRate >= 1 - EPS) exitSignal = true;

  return {
    bestSkill: skillText(best),
    bestSkillLines: best,
    rounds: history.length,
    converged,
    exitSignal,
    rejectedEdits: [...rejected],
    history,
    scores: {
      initial: { gate: round6(initialGate), train: round6(initialTrain) },
      best: {
        gate: round6(finalGate.meanScore),
        train: round6(finalTrain.meanScore),
        gatePassRate: round6(finalGate.passRate),
        trainPassRate: round6(finalTrain.passRate),
      },
      improvement: round6(finalGate.meanScore - initialGate),
      usedHoldout: holdout.length > 0,
    },
  };
}

function round6(n) {
  return Number(Number(n).toFixed(6));
}

module.exports = {
  normalize,
  containsDirective,
  scoreTask,
  evaluateSplit,
  reflect,
  editSignature,
  applyEdit,
  applyEdits,
  splitTasks,
  optimize,
  MANAGED_HEADER,
};
