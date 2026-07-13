#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "simplicio.issue-acceptance-audit/v1"
STATUS_DONE = "DONE"
STATUS_PARTIAL = "PARTIAL"
STATUS_UNVERIFIED = "UNVERIFIED"


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _read_text(relpath: str) -> str:
    return (ROOT / relpath).read_text(encoding="utf-8")


def _find_line(relpath: str, needle: str) -> int | None:
    try:
        text = _read_text(relpath)
    except FileNotFoundError:
        return None
    for index, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return index
    return None


def _receipt(relpath: str, needle: str, *, note: str = "") -> dict[str, Any] | None:
    line = _find_line(relpath, needle)
    if line is None:
        return None
    payload = {
        "type": "file_line",
        "path": relpath,
        "line": line,
        "match": needle,
    }
    if note:
        payload["note"] = note
    return payload


def _evaluate_patterns(
    patterns: list[dict[str, str]],
    *,
    status_if_all_found: str,
    status_if_some_found: str,
    status_if_none_found: str,
) -> tuple[str, list[dict[str, Any]]]:
    receipts = []
    found = 0
    for pattern in patterns:
        hit = _receipt(pattern["path"], pattern["match"], note=pattern.get("note", ""))
        if hit is not None:
            found += 1
            receipts.append(hit)
    if found == len(patterns) and patterns:
        return status_if_all_found, receipts
    if found > 0:
        return status_if_some_found, receipts
    return status_if_none_found, receipts


def _rollup(statuses: list[str]) -> str:
    if statuses and all(status == STATUS_DONE for status in statuses):
        return STATUS_DONE
    if statuses and all(status == STATUS_UNVERIFIED for status in statuses):
        return STATUS_UNVERIFIED
    return STATUS_PARTIAL


def _criterion(
    *,
    issue: int,
    criterion_id: str,
    text: str,
    commands: list[str],
    patterns: list[dict[str, str]] | None = None,
    status_if_all_found: str = STATUS_DONE,
    status_if_some_found: str = STATUS_PARTIAL,
    status_if_none_found: str = STATUS_UNVERIFIED,
    boundary: str = "",
) -> dict[str, Any]:
    patterns = patterns or []
    status, receipts = _evaluate_patterns(
        patterns,
        status_if_all_found=status_if_all_found,
        status_if_some_found=status_if_some_found,
        status_if_none_found=status_if_none_found,
    )
    payload = {
        "issue": issue,
        "criterion_id": criterion_id,
        "text": text,
        "status": status,
        "commands": commands,
        "receipts": receipts,
    }
    if boundary:
        payload["boundary"] = boundary
    return payload


def _issue_199() -> dict[str, Any]:
    criteria = [
        _criterion(
            issue=199,
            criterion_id="199-AC01",
            text="Versioned retrieval index is created during scan/index and reused by later task-aware queries.",
            commands=[
                "python -m unittest tests/python/test_retrieval_index.py",
                "python -m unittest tests/python/test_task_aware_handoff.py",
            ],
            patterns=[
                {"path": "simplicio_mapper/cli/_index_engine.py", "match": "build_retrieval_index("},
                {"path": "simplicio_mapper/cli/_index_engine.py", "match": "write_retrieval_index("},
                {"path": "simplicio_mapper/cli/_status_engine.py", "match": "load_retrieval_index("},
            ],
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC02",
            text="Warm task-aware query avoids reopening every source file body; local tests prove bounded read behavior.",
            commands=["python -m unittest tests/python/test_retrieval_index.py"],
            patterns=[
                {
                    "path": "tests/python/test_retrieval_index.py",
                    "match": "def test_index_carries_symbol_and_path_terms_without_reading_files",
                },
                {"path": "simplicio_mapper/retrieval_index.py", "match": "not LLM-based, and recency never creates"},
            ],
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC03",
            text="Incremental updates invalidate changed chunks/edges only and preserve stable ids for unchanged content.",
            commands=["python -m unittest tests/python/test_retrieval_index.py"],
            patterns=[
                {
                    "path": "tests/python/test_retrieval_index.py",
                    "match": "def test_incremental_update_reuses_unchanged_document_and_chunk_ids",
                },
                {"path": "simplicio_mapper/retrieval_index.py", "match": "def update_retrieval_index("},
            ],
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC04",
            text="Ranking uses deterministic IDF/BM25-style scoring, not raw set overlap alone.",
            commands=["python -m unittest tests/python/test_retrieval_index.py"],
            patterns=[
                {"path": "simplicio_mapper/retrieval_index.py", "match": "deterministic BM25"},
                {
                    "path": "tests/python/test_retrieval_index.py",
                    "match": "def test_exact_symbol_query_ranks_specific_file_over_generic_docs",
                },
            ],
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC05",
            text="Exact target, symbol, path and AC/RN identifiers receive explicit weighting and reason codes.",
            commands=["python -m unittest tests/python/test_retrieval_index.py"],
            patterns=[
                {"path": "tests/python/test_retrieval_index.py", "match": "def test_explicit_target_and_symbol_weighting"},
                {"path": "tests/python/test_retrieval_index.py", "match": 'self.assertIn("rn01"'},
                {"path": "tests/python/test_retrieval_index.py", "match": 'self.assertIn("reason_codes", row)'},
            ],
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC06",
            text="Recency cannot select a file with zero task relevance.",
            commands=["python -m unittest tests/python/test_retrieval_index.py"],
            patterns=[
                {"path": "tests/python/test_retrieval_index.py", "match": "def test_recency_never_creates_relevance"},
            ],
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC07",
            text="Generated/vendor/archive/large generic files are penalized or excluded unless explicitly targeted.",
            commands=["python -m unittest tests/python/test_retrieval_index.py"],
            patterns=[
                {"path": "tests/python/test_retrieval_index.py", "match": "def test_generated_file_penalized"},
                {"path": "simplicio_mapper/retrieval_index.py", "match": "generated_or_vendor_penalty"},
            ],
            status_if_all_found=STATUS_PARTIAL,
            status_if_some_found=STATUS_PARTIAL,
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC08",
            text="Returned candidates expose explainable score components rather than a single opaque score.",
            commands=["python -m unittest tests/python/test_retrieval_index.py"],
            patterns=[
                {"path": "tests/python/test_retrieval_index.py", "match": "def test_explainable_score_components"},
                {"path": "simplicio_mapper/retrieval_index.py", "match": '"score_components"'},
            ],
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC09",
            text="Context packs contain exact source spans plus hashes and line anchors.",
            commands=["python -m unittest tests/python/test_retrieval_index.py"],
            patterns=[
                {"path": "tests/python/test_retrieval_index.py", "match": "def test_span_expands_symbol_range_with_stable_handle"},
                {"path": "simplicio_mapper/retrieval_index.py", "match": '"range_hash"'},
            ],
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC10",
            text="Omitted content has stable expansion handles and can be retrieved without rerunning whole-repo mapping.",
            commands=["python -m unittest tests/python/test_retrieval_index.py"],
            patterns=[
                {"path": "tests/python/test_retrieval_index.py", "match": "def test_expand_handle_round_trip_reads_omitted_content"},
                {"path": "simplicio_mapper/retrieval_index.py", "match": "def resolve_expand_handle("},
            ],
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC11",
            text="`--token-budget` constrains serialized output within the documented tolerance.",
            commands=["python -m unittest tests/python/test_task_aware_handoff.py"],
            patterns=[
                {"path": "simplicio_mapper/cli/_shared.py", "match": "--token-budget <n>"},
                {"path": "tests/python/test_task_aware_handoff.py", "match": "def test_engine_accepts_token_budget_and_limit_and_reports_budget_fit"},
                {"path": "tests/python/test_task_aware_handoff.py", "match": "tokens_estimation_method"},
            ],
            status_if_all_found=STATUS_PARTIAL,
            status_if_some_found=STATUS_PARTIAL,
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC12",
            text="Required context that cannot fit returns broader-context reasons instead of silent truncation.",
            commands=["python -m unittest tests/python/test_retrieval_index.py tests/python/test_task_aware_handoff.py"],
            patterns=[
                {"path": "tests/python/test_retrieval_index.py", "match": "def test_required_span_overflow_requests_broader_context"},
                {"path": "tests/python/test_task_aware_handoff.py", "match": "def test_declared_serialized_output_budget_sets_broader_context"},
            ],
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC13",
            text="Sufficiency uses multi-dimensional fidelity coverage; high generic lexical overlap alone cannot pass.",
            commands=["python -m unittest tests/python/test_retrieval_index.py"],
            patterns=[
                {"path": "tests/python/test_retrieval_index.py", "match": "def test_high_generic_overlap_alone_cannot_pass"},
                {"path": "simplicio_mapper/retrieval_index.py", "match": "Multi-dimensional fidelity coverage"},
            ],
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC14",
            text="Negative/no-match corpus abstains instead of returning arbitrary top-k files.",
            commands=["python -m unittest tests/python/test_retrieval_index.py tests/python/test_task_aware_handoff.py"],
            patterns=[
                {"path": "tests/python/test_retrieval_index.py", "match": "def test_selector_abstains_on_no_vocabulary"},
                {"path": "tests/python/test_task_aware_handoff.py", "match": "def test_engine_abstains_when_repo_has_no_task_vocabulary"},
            ],
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC15",
            text="Polyglot and cross-layer tasks include necessary diversity without exceeding budget.",
            commands=["python scripts/evaluation_scorecard.py --json"],
            patterns=[
                {"path": "tests/fixtures/evaluation_corpus/manifest.json", "match": '"id": "frontend-ordering-en"'},
                {"path": "tests/fixtures/evaluation_corpus/manifest.json", "match": '"id": "planes-ordering-ptbr"'},
            ],
            status_if_all_found=STATUS_UNVERIFIED,
            status_if_some_found=STATUS_UNVERIFIED,
            boundary="The local corpus proves labeled retrieval behavior, but this repo-local audit does not prove the broader polyglot/cross-layer budget claim across Runtime, Dev CLI, or Loop consumers.",
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC16",
            text="Repeated identical query/tree produces byte-stable ordering, pack hash and serialized output.",
            commands=[
                "python -m unittest tests/python/test_behavioral_scorecard.py",
                "python scripts/evaluation_scorecard.py --json",
            ],
            patterns=[
                {"path": "tests/python/test_behavioral_scorecard.py", "match": "def test_real_cli_scorecard_is_deterministic_and_measured"},
                {"path": "tests/python/test_retrieval_index.py", "match": "def test_identical_inputs_produce_stable_ordering"},
            ],
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC17",
            text="Runtime-scale committed fixture meets the stated warm p95 target or the documented >=10x fallback.",
            commands=["python scripts/evaluation_scorecard.py --json"],
            patterns=[
                {"path": "scripts/evaluation_scorecard.py", "match": "mean_latency_ms"},
            ],
            status_if_all_found=STATUS_UNVERIFIED,
            status_if_some_found=STATUS_UNVERIFIED,
            boundary="Reference-CI p95 proof is outside this repo-local audit and still depends on runtime-scale fixtures plus external CI/runtime conditions.",
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC18",
            text="Precision@k and AC/source recall are measured against a committed labeled corpus with explicit thresholds.",
            commands=[
                "python scripts/evaluation_scorecard.py --json",
                "python -m unittest tests/python/test_evaluation_benchmark.py",
            ],
            patterns=[
                {"path": "scripts/evaluation_scorecard.py", "match": "precision_at_k"},
                {"path": "scripts/evaluation_scorecard.py", "match": "required_span_recall"},
                {"path": "tests/python/test_evaluation_benchmark.py", "match": 'self.assertEqual(payload["measurements"]["sufficiency"], 1.0)'},
            ],
            status_if_all_found=STATUS_PARTIAL,
            status_if_some_found=STATUS_PARTIAL,
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC19",
            text="The 2026-07-11 token-economy query no longer passes by selecting only generic docs/main chunks.",
            commands=["python scripts/evaluation_scorecard.py --json"],
            patterns=[
                {"path": "tests/fixtures/evaluation_corpus/manifest.json", "match": "token-economy"},
            ],
            status_if_all_found=STATUS_UNVERIFIED,
            status_if_some_found=STATUS_UNVERIFIED,
            boundary="The exact historical token-economy replay is not committed as a local fixture in this repo, so the original cross-repo query remains unverified here.",
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC20",
            text="Dev CLI and Loop consume the installed package in integration tests, not an in-tree mock.",
            commands=["python scripts/dogfood.py --help"],
            patterns=[
                {"path": "scripts/dogfood.py", "match": "Cross-repo (dev-cli/loop) legs are intentionally left"},
                {"path": "scripts/ecosystem-consumers.json", "match": '"name": "simplicio-dev-cli"'},
                {"path": "scripts/ecosystem-consumers.json", "match": '"name": "simplicio-loop"'},
            ],
            status_if_all_found=STATUS_UNVERIFIED,
            status_if_some_found=STATUS_UNVERIFIED,
            boundary="Installed-package integration for simplicio-dev-cli and simplicio-loop is explicitly cross-repo and remains outside this mapper-only audit.",
        ),
        _criterion(
            issue=199,
            criterion_id="199-AC21",
            text="No new dependency was added without explicit approval.",
            commands=["python -m build --wheel --sdist"],
            patterns=[
                {"path": "pyproject.toml", "match": 'dependencies = ['},
            ],
            status_if_all_found=STATUS_UNVERIFIED,
            status_if_some_found=STATUS_UNVERIFIED,
            boundary="A repo-local snapshot can show the current dependency set, but it cannot prove the historical approval path for additions without external issue/PR review context.",
        ),
    ]
    return {
        "issue": 199,
        "title": "[P0][Retrieval] Replace full-file task ranking with indexed, token-budgeted context selection",
        "status": _rollup([criterion["status"] for criterion in criteria]),
        "criteria": criteria,
        "residual_boundaries": [
            "simplicio-runtime: runtime-scale latency targets and native consumer reality are outside this mapper-only audit.",
            "simplicio-dev-cli: installed-package integration remains cross-repo.",
            "simplicio-loop: installed-package integration remains cross-repo.",
        ],
    }


def _issue_208() -> dict[str, Any]:
    criteria = [
        _criterion(
            issue=208,
            criterion_id="208-AC01",
            text="ContextSnapshot/ContextGraph v1 has schema, fixtures, canonical hash and compatibility tests.",
            commands=["python -m unittest tests/python/test_context_snapshot.py"],
            patterns=[
                {"path": "contracts/context-snapshot/v1/README.md", "match": "# ContextSnapshot / ContextGraph contract"},
                {"path": "tests/python/test_context_snapshot.py", "match": "def test_snapshot_id_is_content_addressed_and_deterministic"},
                {"path": "tests/python/test_context_snapshot.py", "match": "def test_fixtures_validate_against_shipped_schema"},
            ],
        ),
        _criterion(
            issue=208,
            criterion_id="208-AC02",
            text="Wheel and sdist include schemas; a clean install can validate them.",
            commands=["python -m unittest tests/python/test_cli_packaging.py tests/python/test_context_snapshot.py"],
            patterns=[
                {"path": "pyproject.toml", "match": '[tool.hatch.build.targets.wheel.force-include]'},
                {"path": "tests/python/test_cli_packaging.py", "match": "def test_built_wheel_and_sdist_include_contracts_tree"},
                {"path": "tests/python/test_context_snapshot.py", "match": "def test_from_package_resolves_shipped_schema"},
            ],
        ),
        _criterion(
            issue=208,
            criterion_id="208-AC03",
            text="Node contains no second implementation of snapshot semantics without equivalence proof.",
            commands=["node packaging/npm/bin/simplicio-mapper.js --help"],
            patterns=[
                {"path": "packaging/npm/bin/simplicio-mapper.js", "match": "require('../lib/python-shim')"},
                {"path": "packaging/npm/lib/python-shim.js", "match": "pip', 'install', '--upgrade', `${packageName}==${version}`"},
            ],
        ),
        _criterion(
            issue=208,
            criterion_id="208-AC04",
            text="Local updates recalculate only the causal cone, with rename/delete/config-change coverage and counters.",
            commands=["python -m unittest tests/python/test_context_dag.py tests/python/test_incremental.py"],
            patterns=[
                {"path": "tests/python/test_context_dag.py", "match": "def test_local_change_invalidates_only_dependent_cone"},
                {"path": "tests/python/test_context_dag.py", "match": "def test_rename_detected_via_matching_content_hash"},
                {"path": "tests/python/test_context_dag.py", "match": "def test_build_config_change_forces_full_invalidation"},
            ],
        ),
        _criterion(
            issue=208,
            criterion_id="208-AC05",
            text="Corrupted cache produces a safe rebuild rather than silently stale context.",
            commands=["python -m unittest tests/python/test_context_dag.py"],
            patterns=[
                {"path": "simplicio_mapper/context_dag.py", "match": 'REASON_CACHE_CORRUPTED = "cache-corrupted"'},
                {"path": "tests/python/test_context_dag.py", "match": "def test_run_after_corrupted_cache_falls_back_to_full_rebuild"},
            ],
        ),
        _criterion(
            issue=208,
            criterion_id="208-AC06",
            text="Every summary/drilldown remains reversible and the fidelity gate can abstain when context is insufficient.",
            commands=[
                "python -m unittest tests/python/test_context_snapshot.py",
                "python -m unittest tests/python/test_orient.py",
            ],
            patterns=[
                {"path": "tests/python/test_context_snapshot.py", "match": 'self.assertTrue(d["drilldown"]["reversible"])'},
                {"path": "tests/python/test_context_snapshot.py", "match": "def test_omissions_flagged_when_artifacts_missing"},
                {"path": "tests/python/test_orient.py", "match": "def test_unmatched_task_abstains_with_explicit_gap"},
            ],
            status_if_all_found=STATUS_PARTIAL,
            status_if_some_found=STATUS_PARTIAL,
        ),
        _criterion(
            issue=208,
            criterion_id="208-AC07",
            text="Published report includes precision@k, required-span recall, sufficiency accuracy, task success, tokens, bytes and latency.",
            commands=["python scripts/evaluation_scorecard.py --json"],
            patterns=[
                {"path": "scripts/evaluation_scorecard.py", "match": '"precision_at_k"'},
                {"path": "scripts/evaluation_scorecard.py", "match": '"required_span_recall"'},
                {"path": "scripts/evaluation_scorecard.py", "match": '"mean_latency_ms"'},
            ],
        ),
        _criterion(
            issue=208,
            criterion_id="208-AC08",
            text="H1 and H2 are accepted or refuted with baseline-backed data rather than asserted.",
            commands=["python scripts/evaluation_scorecard.py --json"],
            patterns=[
                {"path": "scripts/evaluation_scorecard.py", "match": '"task_success"'},
            ],
            status_if_all_found=STATUS_UNVERIFIED,
            status_if_some_found=STATUS_UNVERIFIED,
            boundary="The repo contains local metrics, but not a committed verdict that formally accepts or refutes both issue hypotheses across the intended corpus and hardware baseline.",
        ),
        _criterion(
            issue=208,
            criterion_id="208-AC09",
            text="E2E integration preserves revision and snapshot_id through the Runtime-shaped EvidenceCertificate boundary.",
            commands=["python -m unittest tests/python/test_evidence_certificate_integration.py"],
            patterns=[
                {"path": "tests/python/test_evidence_certificate_integration.py", "match": 'self.assertEqual(certificate["observed_context"]["revision"], snapshot["revision"])'},
                {"path": "tests/python/test_evidence_certificate_integration.py", "match": 'self.assertEqual(certificate["observed_context"]["snapshot_id"], snapshot["snapshot_id"])'},
                {"path": "tests/python/test_evidence_certificate_integration.py", "match": '"status": "UNVERIFIED"'},
            ],
            status_if_all_found=STATUS_PARTIAL,
            status_if_some_found=STATUS_PARTIAL,
            boundary="The mapper preserves revision/snapshot_id into the Runtime-shaped certificate, but real simplicio-runtime execution is explicitly left UNVERIFIED in this repo-local test.",
        ),
    ]
    return {
        "issue": 208,
        "title": "[P0][Information Theory] ContextGraph multi-escala, incremental e com fidelity gate",
        "status": _rollup([criterion["status"] for criterion in criteria]),
        "criteria": criteria,
        "residual_boundaries": [
            "simplicio-runtime: the final runtime execution leg is intentionally UNVERIFIED in the mapper-owned certificate test.",
            "simplicio-dev-cli: downstream consumer behavior is cross-repo.",
            "simplicio-loop: downstream consumer behavior is cross-repo.",
        ],
    }


def _issue_213() -> dict[str, Any]:
    criteria = [
        _criterion(
            issue=213,
            criterion_id="213-AC01",
            text="Local code now wires the cache/native-first path into live query verbs rather than leaving it isolated in cache internals.",
            commands=["python -m unittest tests/python/test_query.py"],
            patterns=[
                {"path": "simplicio_mapper/query.py", "match": 'elif verb == "impact":'},
                {"path": "simplicio_mapper/query.py", "match": 'elif verb == "tests-for":'},
                {"path": "simplicio_mapper/query.py", "match": 'elif verb == "precedent":'},
                {"path": "simplicio_mapper/query.py", "match": "ContextCache("},
            ],
        ),
        _criterion(
            issue=213,
            criterion_id="213-AC02",
            text="Dedicated cache tests cover corruption quarantine, concurrency safety and truthful bypass receipts.",
            commands=["python -m unittest tests/python/test_context_cache_query.py"],
            patterns=[
                {"path": "tests/python/test_context_cache_query.py", "match": "def test_corrupt_entry_is_quarantined_on_reload"},
                {"path": "tests/python/test_context_cache_query.py", "match": "def test_concurrent_writers_merge_without_losing_entries"},
                {"path": "tests/python/test_context_cache_query.py", "match": "def test_bypass_receipt_keeps_baseline_and_method"},
            ],
        ),
        _criterion(
            issue=213,
            criterion_id="213-AC03",
            text="A replayable local benchmark artifact exists for the query/caching path.",
            commands=[
                "python scripts/measure_verbs.py --out scripts/measure_verbs_report.json",
                "python -m unittest tests/python/test_context_cache_benchmark.py",
            ],
            patterns=[
                {"path": "scripts/measure_verbs.py", "match": "DEFAULT_OUT = os.path.join(HERE, \"measure_verbs_report.json\")"},
                {"path": "scripts/measure_verbs_report.json", "match": '"schema": "simplicio.measure-verbs-report/v1"'},
            ],
        ),
        _criterion(
            issue=213,
            criterion_id="213-AC04",
            text="Distribution parity evidence exists for wheel/sdist packaging of the contracts surface.",
            commands=["python -m unittest tests/python/test_cli_packaging.py"],
            patterns=[
                {"path": "tests/python/test_cli_packaging.py", "match": "def test_built_wheel_and_sdist_include_contracts_tree"},
            ],
        ),
        _criterion(
            issue=213,
            criterion_id="213-AC05",
            text="Original GitHub closure evidence for issue #200 remains auditable rather than faked from local files alone.",
            commands=["gh issue view 200 --repo wesleysimplicio/simplicio-mapper --json number,state,body"],
            patterns=[
                {"path": "tests/python/test_evidence_certificate_integration.py", "match": '"status": "UNVERIFIED"'},
            ],
            status_if_all_found=STATUS_UNVERIFIED,
            status_if_some_found=STATUS_UNVERIFIED,
            boundary="Whether the historical closure of #200 was justified is a GitHub/PR-state question; this local repo can show current code and tests, but it cannot rewrite or prove the original remote review evidence trail.",
        ),
    ]
    return {
        "issue": 213,
        "title": "[Loop Audit] Issue #200 closed without verified evidence",
        "status": _rollup([criterion["status"] for criterion in criteria]),
        "criteria": criteria,
        "residual_boundaries": [
            "GitHub closure history for #200 is remote state, not a local-file fact.",
            "simplicio-runtime: native precedent/impact/tests-for behavior still crosses into another repo/runtime.",
            "simplicio-dev-cli and simplicio-loop: downstream consumer reality is still cross-repo.",
        ],
    }


def build_audit() -> dict[str, Any]:
    issues = [_issue_199(), _issue_208(), _issue_213()]
    criteria = [criterion for issue in issues for criterion in issue["criteria"]]
    summary = {
        "issues": len(issues),
        "criteria": len(criteria),
        "done": sum(1 for criterion in criteria if criterion["status"] == STATUS_DONE),
        "partial": sum(1 for criterion in criteria if criterion["status"] == STATUS_PARTIAL),
        "unverified": sum(1 for criterion in criteria if criterion["status"] == STATUS_UNVERIFIED),
    }
    return {
        "schema": SCHEMA,
        "repo": ROOT.name,
        "root": ROOT.as_posix(),
        "summary": summary,
        "issues": issues,
    }


def _render_text(payload: dict[str, Any]) -> str:
    lines = [
        "# Issue acceptance audit",
        "",
        f"Schema: `{payload['schema']}`",
        "",
        f"Summary: DONE={payload['summary']['done']} PARTIAL={payload['summary']['partial']} UNVERIFIED={payload['summary']['unverified']}",
    ]
    for issue in payload["issues"]:
        lines.extend(
            [
                "",
                f"## #{issue['issue']} — {issue['title']}",
                "",
                f"Overall: **{issue['status']}**",
                "",
                "Residual boundaries:",
                "",
            ]
        )
        for boundary in issue["residual_boundaries"]:
            lines.append(f"- {boundary}")
        lines.extend(["", "Criteria:", ""])
        for criterion in issue["criteria"]:
            lines.append(f"- {criterion['criterion_id']} [{criterion['status']}] {criterion['text']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic local AC audit for issues #199/#208/#213.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument("--text", action="store_true", help="Emit Markdown-like text.")
    args = parser.parse_args(argv)

    payload = build_audit()
    if args.text and not args.json:
        sys.stdout.write(_render_text(payload) + "\n")
    else:
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False, sort_keys=True)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
