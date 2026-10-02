"""Independent judge for the Prototype-First Gate (epic #568, PR #576).

`prototype_gate.py`'s state machine (`apply_decision`) has always accepted a
`decision` mapping built by `build_decision(...)`, but nothing in this repo
ever *produced* that mapping by actually adjudicating a round of candidates --
callers had to fabricate ACCEPT/REVISE/REJECT externally. This module closes
that gap: a pluggable :class:`Judge` protocol, a real deterministic default
(:class:`RuleBasedJudge`), and two wiring functions (`judge_and_decide`,
`judge_transition`) that make a round transition genuinely go through
judgment instead of a hand-written decision.

Contract shape is read from the SIBLING repo `simplicio-agent`'s
``agent/prototype_first_gate.py`` (``RoleIdentity``, ``measure_diversity()``,
``review_candidate()``, ``assert_no_self_judging()``, ``score_candidate()``/
``decide_round()``) -- this module reimplements the same PATTERN natively
against *this* repo's own schema (``plan["validators"]`` /
``candidate["validation_results"]``/``candidate["evidence_refs"]``, built by
``prototype_gate.build_plan``/``build_candidate``), per the ecosystem rule
that sibling repos share JSON-schema contracts, never import each other's
internals.

Hard invariants enforced here, not by convention:

* **Self-judging is impossible.**  If ``judge_identity`` matches the
  ``agent_id`` (creator identity) of ANY candidate in the round, the whole
  round refuses to emit a decision at all (:class:`SelfJudgingError`) -- never
  a silently biased verdict for just the affected candidate. Checked before
  any scoring happens.
* **ACCEPT requires evidence, not plausibility.**  A candidate is only
  eligible for ACCEPT when every validator the plan requires (``plan
  ["validators"]``) is covered by a ``validation_results`` entry that
  actually passed, AND the candidate carries at least one evidence ref, AND
  zero of its validators that DID run came back failed.
* **Diversity is measured, not assumed.**  Each candidate's score includes a
  real per-candidate mean pairwise Jaccard distance over structured facts
  (``strategy``/``assumptions``/``limitations``/``out_of_scope``) against the
  rest of the round -- two near-identical candidates collapse toward the same
  low score; genuinely distinct ones differentiate.
* **Bounded REVISE / stall detection is reused, not reinvented.**
  ``judge_transition`` drives the decision through the EXISTING
  ``apply_decision`` state machine (bounded ``max_revise``, blocked on
  ``revise_iterations_exceeded``) and appends to ``state["history"]`` in the
  exact shape ``stall_verdict()`` already understands -- a caller can keep
  calling ``stall_verdict(new_state)`` unchanged after a judge-driven
  transition.

How a smarter LLM-backed judge plugs in
----------------------------------------
:class:`Judge` is a ``typing.Protocol`` with one method::

    def judge(self, plan, candidates, judge_identity) -> dict: ...

returning a ``JUDGE_SCHEMA``-tagged verdict report (see
:meth:`RuleBasedJudge.judge` for the exact shape: ``verdicts`` sorted best
first, each with ``ac_coverage_ratio``/``evidence_present``/
``finding_count``/``diversity_score``/``score``/``eligible_for_accept``). An
LLM-backed judge satisfies the SAME protocol -- e.g. it might read the
candidates' ``assumptions``/``limitations`` prose with a model instead of
(or in addition to) the rule-based scoring, but it MUST still: (a) call
``assert_no_self_judging`` first (or delegate to it) and raise
:class:`SelfJudgingError` rather than degrade, (b) return the same
``JUDGE_SCHEMA`` verdict shape so ``judge_and_decide``/``judge_transition``
can consume it unchanged, and (c) never grant itself delivery/promotion
authority -- it recommends ACCEPT/REVISE/REJECT, it never ships. Swap it in
via the ``judge=`` keyword on ``judge_and_decide``/``judge_transition``; no
other code changes.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from simplicio_loop.prototype_gate import (
    DEFAULT_MAX_REVISE,
    PrototypeGateError,
    apply_decision,
    build_decision,
    validate_candidate,
    validate_plan,
)

JUDGE_SCHEMA = "simplicio.prototype-judge-verdict/v1"

#: Explainable, fixed weights -- documented here instead of buried in the math.
#: Mirrors the SHAPE of simplicio-agent's `JUDGE_WEIGHTS` (ac_coverage/evidence
#: dominate; diversity and clean-findings are smaller, tie-breaking signals),
#: reimplemented against this repo's own fields.
DEFAULT_JUDGE_WEIGHTS: Mapping[str, float] = {
    "ac_coverage": 0.55,
    "evidence": 0.20,
    "diversity": 0.10,
    "findings_clean": 0.15,
}
#: Per-finding penalty subtracted from the weighted score (mirrors JUDGE_FINDING_PENALTY).
FINDING_PENALTY = 0.10


class SelfJudgingError(PrototypeGateError):
    """Raised when a judge's identity matches a candidate creator's identity.

    Fails the WHOLE round -- never degrades into a biased decision for just
    the affected candidate, mirroring simplicio-agent's
    ``agent/prototype_first_gate.py::assert_no_self_judging``.
    """


@runtime_checkable
class Judge(Protocol):
    """Pluggable judgment contract.

    Anything satisfying this can adjudicate a round of candidates: the
    default :class:`RuleBasedJudge` below (deterministic, model-free, no
    network, no LLM), or a smarter LLM-backed judge (see the module
    docstring's "How a smarter LLM-backed judge plugs in").
    """

    def judge(
        self,
        plan: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
        judge_identity: str,
    ) -> dict[str, Any]:
        """Return a ``JUDGE_SCHEMA``-tagged verdict report -- never a bare
        decision string, so the caller can always audit WHY."""
        ...  # pragma: no cover - protocol method


def _candidate_features(candidate: Mapping[str, Any]) -> frozenset[str]:
    """Structured facts used for the diversity metric -- never free prose."""
    tags: set[str] = {"strategy:" + str(candidate.get("strategy", ""))}
    tags.update("assumption:" + str(a) for a in candidate.get("assumptions", []) or [])
    tags.update("limitation:" + str(lim) for lim in candidate.get("limitations", []) or [])
    tags.update("out_of_scope:" + str(o) for o in candidate.get("out_of_scope", []) or [])
    return frozenset(tags)


def _jaccard_distance(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return 1.0 - (len(left & right) / len(union))


def measure_diversity(candidates: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Real, measured per-candidate diversity across a round -- never assumed.

    For each candidate, the mean pairwise Jaccard distance of its structured
    facts (``strategy``/``assumptions``/``limitations``/``out_of_scope``)
    against every OTHER candidate in the round. Two candidates that only
    differ in prose but declare the same facts collapse to distance 0 for
    each other; genuinely different approaches score higher -- this is what
    lets the judge's final score differentiate a round of near-identical
    candidates from one with real variety, even when AC-coverage/evidence/
    findings tie.
    """
    ordered = list(candidates)
    if not ordered:
        return {}
    features = [_candidate_features(c) for c in ordered]
    scores: dict[str, float] = {}
    for i, candidate in enumerate(ordered):
        others = [features[j] for j in range(len(ordered)) if j != i]
        if not others:
            scores[str(candidate["candidate_id"])] = 0.0
            continue
        distances = [_jaccard_distance(features[i], other) for other in others]
        scores[str(candidate["candidate_id"])] = sum(distances) / len(distances)
    return scores


def _validation_status(candidate: Mapping[str, Any]) -> tuple[dict[str, bool], int]:
    """``validation_results`` entries are ``{"validator": str, "passed": bool}``.

    A validator that ran and FAILED is an unresolved finding; a validator the
    plan requires but that never ran at all is coverage-incomplete (handled
    separately in :func:`score_candidate`'s ``ac_coverage_ratio``) but is not
    itself counted as a "finding" here -- only a run-and-failed validator
    counts toward ``finding_count``, mirroring the sibling contract's
    distinction between an outright defect surfaced BY review versus mere
    incompleteness.
    """
    by_validator: dict[str, bool] = {}
    finding_count = 0
    for entry in candidate.get("validation_results", []) or []:
        name = str(entry.get("validator", "")).strip()
        if not name:
            continue
        passed = bool(entry.get("passed"))
        by_validator[name] = passed
        if not passed:
            finding_count += 1
    return by_validator, finding_count


def score_candidate(
    plan: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    diversity_score: float,
    weights: Mapping[str, float] = DEFAULT_JUDGE_WEIGHTS,
) -> dict[str, Any]:
    """Deterministic, explainable score: AC coverage + evidence + measured
    diversity + zero unresolved findings.

    Reimplements the SHAPE of simplicio-agent's ``score_candidate()`` /
    ``JudgeVerdict.eligible_for_accept`` natively against this repo's schema
    -- required validators come from ``plan["validators"]``; coverage and
    findings come from ``candidate["validation_results"]``; evidence comes
    from ``candidate["evidence_refs"]``.
    """
    required = set(plan.get("validators", []) or [])
    by_validator, finding_count = _validation_status(candidate)
    covered = {v for v in required if by_validator.get(v) is True}
    # Vacuously satisfied when the plan declares no validators at all --
    # mirrors this repo's own `build_ac_coverage_matrix` "no ACs to fail"
    # discipline (simplicio_loop/completion_auditor.py) rather than inventing
    # a new convention for the empty case.
    ac_coverage_ratio = (len(covered) / len(required)) if required else 1.0

    evidence_present = bool(candidate.get("evidence_refs"))

    breakdown = {
        "ac_coverage": weights["ac_coverage"] * ac_coverage_ratio,
        "evidence": weights["evidence"] * (1.0 if evidence_present else 0.0),
        "diversity": weights["diversity"] * diversity_score,
        "findings_clean": weights["findings_clean"] * (1.0 if finding_count == 0 else 0.0),
    }
    penalty = FINDING_PENALTY * finding_count
    breakdown["finding_penalty"] = -penalty
    score = sum(breakdown.values())

    return {
        "candidate_id": str(candidate["candidate_id"]),
        "candidate_hash": candidate["candidate_hash"],
        "ac_coverage_ratio": ac_coverage_ratio,
        "evidence_present": evidence_present,
        "finding_count": finding_count,
        "diversity_score": diversity_score,
        "score": score,
        "breakdown": breakdown,
        # ACCEPT-eligibility is never "looks plausible" -- full AC coverage,
        # real evidence, and zero unresolved findings, all three, always.
        "eligible_for_accept": (
            ac_coverage_ratio >= 1.0 and evidence_present and finding_count == 0
        ),
    }


def assert_no_self_judging(
    candidates: Sequence[Mapping[str, Any]], judge_identity: str
) -> None:
    """Hard-block self-judging: a candidate's own creator can never judge it.

    Raises :class:`SelfJudgingError` and refuses to emit ANY decision for the
    whole round -- not just the affected candidate -- when ``judge_identity``
    matches any candidate's ``agent_id`` (creator identity).
    """
    creator_identities = {str(candidate.get("agent_id", "")) for candidate in candidates}
    if str(judge_identity) in creator_identities:
        raise SelfJudgingError(
            "self-judging blocked: judge identity %r matches a candidate "
            "creator identity" % (str(judge_identity),)
        )


class RuleBasedJudge:
    """Deterministic default :class:`Judge` -- AC-coverage + evidence-presence
    + zero-critic-findings + measured diversity, no LLM, no network, no
    filesystem access."""

    def __init__(self, *, weights: Mapping[str, float] = DEFAULT_JUDGE_WEIGHTS) -> None:
        self._weights = dict(weights)

    def judge(
        self,
        plan: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
        judge_identity: str,
    ) -> dict[str, Any]:
        # Self-judging is checked FIRST, before any scoring happens -- a
        # SelfJudgingError here means NO decision is produced for the round.
        assert_no_self_judging(candidates, judge_identity)
        if not candidates:
            raise PrototypeGateError("judge requires at least 1 candidate")

        diversity = measure_diversity(candidates)
        verdicts = [
            score_candidate(
                plan,
                candidate,
                diversity_score=diversity[str(candidate["candidate_id"])],
                weights=self._weights,
            )
            for candidate in candidates
        ]
        verdicts.sort(key=lambda verdict: (-verdict["score"], verdict["candidate_id"]))
        return {
            "schema": JUDGE_SCHEMA,
            "judge_id": str(judge_identity),
            "plan_hash": plan.get("plan_hash"),
            "verdicts": verdicts,
        }


def judge_and_decide(
    plan: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    judge_identity: str,
    *,
    judge: Judge | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run ``judge`` (default :class:`RuleBasedJudge`) over ``candidates`` and
    return ``(decision, verdict_report)``.

    This is the mechanism that actually PRODUCES an ACCEPT/REVISE/REJECT
    decision from real judgment instead of requiring the caller to fabricate
    one externally. The winning candidate is ranked first
    (``verdict_report["verdicts"][0]``); the decision kind follows the
    verdict's own ``eligible_for_accept`` flag -- never a separate,
    out-of-band judgment:

    * ``ACCEPT`` -- the best candidate is ``eligible_for_accept``.
    * ``REJECT`` -- the best candidate has ZERO AC coverage and no evidence
      at all (nothing in the round is viable; re-running the same round would
      not help).
    * ``REVISE`` -- anything in between (partial coverage, or coverage/
      evidence present but unresolved findings remain).

    Self-judging is checked before any scoring (via ``Judge.judge`` ->
    :func:`assert_no_self_judging`) -- a :class:`SelfJudgingError` here means
    no decision is emitted for the round at all.
    """
    validate_plan(plan)
    for candidate in candidates:
        validate_candidate(candidate, plan=plan)

    active_judge = judge if judge is not None else RuleBasedJudge()
    report = active_judge.judge(plan, candidates, judge_identity)
    verdicts = report.get("verdicts") or []
    if not verdicts:
        raise PrototypeGateError("judge produced no verdicts")

    best = verdicts[0]
    ranked = verdicts
    rejected = verdicts[1:]

    if best["eligible_for_accept"]:
        kind = "ACCEPT"
        reason = "ac_coverage_and_evidence_satisfied"
    elif best["ac_coverage_ratio"] == 0.0 and not best["evidence_present"]:
        kind = "REJECT"
        reason = "no_viable_candidate_in_round"
    else:
        kind = "REVISE"
        reason = "unresolved_findings_or_incomplete_ac_coverage"

    decision = build_decision(
        plan=plan,
        candidate_hash=best["candidate_hash"],
        decision=kind,
        reason=reason,
        judge_id=str(judge_identity),
        judge_independent=True,
        ranked_candidates=ranked,
        rejected_candidates=rejected,
    )
    return decision, report


def judge_transition(
    state: Mapping[str, Any],
    plan: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    judge_identity: str,
    *,
    judge: Judge | None = None,
    current_source_sha: str | None = None,
    max_revise: int = DEFAULT_MAX_REVISE,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Drive ONE promotion-state-machine transition by genuinely calling a
    judge -- the wiring point this module adds to ``prototype_gate.py``.

    Before this, a REVISE/ACCEPT/REJECT transition required the caller to
    build the ``decision`` mapping by hand (``build_decision(..., decision=
    "ACCEPT", ...)``) with no judgment logic behind it. This function replaces
    that hand-written step: it calls :func:`judge_and_decide` to produce a
    real decision, then feeds it straight into the EXISTING
    ``prototype_gate.apply_decision`` state machine (unchanged -- bounded
    ``max_revise``, ``revise_iterations_exceeded`` blocking, plan/source drift
    handling all still apply exactly as before).

    Returns ``(new_state, decision, verdict_report)``. Stall detection is
    reused, not reinvented: ``prototype_gate.stall_verdict(new_state)`` still
    works unchanged afterwards, because ``apply_decision`` appends to
    ``state["history"]`` in the same shape regardless of who produced the
    decision.
    """
    decision, report = judge_and_decide(plan, candidates, judge_identity, judge=judge)
    new_state = apply_decision(
        state,
        plan=plan,
        decision=decision,
        candidate_hash=decision["candidate_hash"],
        current_source_sha=current_source_sha,
        max_revise=max_revise,
    )
    return new_state, decision, report


__all__ = [
    "DEFAULT_JUDGE_WEIGHTS",
    "FINDING_PENALTY",
    "JUDGE_SCHEMA",
    "Judge",
    "RuleBasedJudge",
    "SelfJudgingError",
    "assert_no_self_judging",
    "judge_and_decide",
    "judge_transition",
    "measure_diversity",
    "score_candidate",
]
