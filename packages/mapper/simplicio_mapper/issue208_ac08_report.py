from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "simplicio.issue208-ac08-report/v1"
REPORT_VERSION = 1

HYPOTHESES = {
    "H1": {
        "statement": (
            "Adaptive context packs reduce serialized tokens by at least 30% versus the "
            "full snapshot while keeping task pass rate within 2 percentage points of baseline."
        ),
        "required_metrics": [
            "baseline_full_snapshot_tokens",
            "candidate_adaptive_context_tokens",
            "baseline_task_pass_rate",
            "candidate_task_pass_rate",
        ],
    },
    "H2": {
        "statement": (
            "For local changes, incremental work grows with the affected causal cone rather than "
            "repository size, and cuts p95 by at least 3x on the frozen corpus."
        ),
        "required_metrics": [
            "baseline_full_scan_p95_ms",
            "candidate_incremental_p95_ms",
            "affected_causal_cone_size",
            "repository_size",
            "bytes_read",
            "files_parsed",
            "nodes_recomputed",
        ],
    },
}

SUPPORTING_ARTIFACTS = {
    "behavioral_corpus": {
        "path": "contracts/behavioral/v1/corpus.json",
        "supports": ["frozen_corpus_presence"],
        "note": "Committed frozen corpus with labeled expected targets/tests/AC ids.",
    },
    "toon_benchmark": {
        "path": "docs/toon-benchmark.md",
        "supports": ["supporting_context_only"],
        "note": (
            "Measures TOON serialization on survey artifacts, not adaptive-vs-full context packs "
            "on the issue #208 frozen corpus."
        ),
    },
    "measure_verbs_report": {
        "path": "scripts/measure_verbs_report.json",
        "supports": ["supporting_context_only"],
        "note": (
            "Measures isolated ask-verb latency on a minimal fixture, not full-vs-incremental "
            "causal-cone refresh p95 on the issue #208 corpus."
        ),
    },
}


def _repo_root(start: Path | None = None) -> Path:
    if start is None:
        start = Path(__file__).resolve()
    return start.parents[1]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _case_file_status(fixture_dir: Path, relative_paths: list[str]) -> dict[str, Any]:
    existing = []
    missing = []
    for rel in relative_paths:
        if (fixture_dir / rel).is_file():
            existing.append(rel)
        else:
            missing.append(rel)
    return {
        "declared": len(relative_paths),
        "existing": len(existing),
        "missing": missing,
    }


def build_issue208_ac08_report(root: str | Path | None = None) -> dict[str, Any]:
    repo_root = Path(root) if root is not None else _repo_root()
    repo_root = repo_root.resolve()

    corpus_path = repo_root / SUPPORTING_ARTIFACTS["behavioral_corpus"]["path"]
    corpus = _load_json(corpus_path)
    fixtures_root = corpus_path.parent / "fixtures"

    cases_summary: list[dict[str, Any]] = []
    language_set: set[str] = set()
    total_expected_targets = 0
    total_expected_tests = 0
    total_expected_ac_ids = 0
    abstention_case_count = 0

    for case in corpus.get("cases", []):
        fixture_dir = fixtures_root / case["fixture"]
        language_set.add(case.get("language", "unknown"))
        total_expected_targets += len(case.get("expected_targets", []))
        total_expected_tests += len(case.get("expected_tests", []))
        total_expected_ac_ids += len(case.get("expected_ac_ids", []))
        if not case.get("expected_targets"):
            abstention_case_count += 1

        target_status = _case_file_status(fixture_dir, list(case.get("expected_targets", [])))
        test_status = _case_file_status(fixture_dir, list(case.get("expected_tests", [])))
        task_path = fixture_dir / case.get("task", "task.md")
        cases_summary.append(
            {
                "id": case["id"],
                "fixture": case["fixture"],
                "language": case.get("language"),
                "task_file": case.get("task"),
                "task_exists": task_path.is_file(),
                "expected_targets": target_status,
                "expected_tests": test_status,
                "expected_ac_ids": list(case.get("expected_ac_ids", [])),
            }
        )

    artifact_status = []
    for name, meta in SUPPORTING_ARTIFACTS.items():
        artifact_path = repo_root / meta["path"]
        artifact_status.append(
            {
                "name": name,
                "path": meta["path"],
                "present": artifact_path.exists(),
                "supports": list(meta["supports"]),
                "note": meta["note"],
            }
        )

    measured = {
        "corpus_case_count": len(cases_summary),
        "languages": sorted(language_set),
        "abstention_case_count": abstention_case_count,
        "expected_target_labels": total_expected_targets,
        "expected_test_labels": total_expected_tests,
        "expected_ac_labels": total_expected_ac_ids,
        "fixtures_with_task_file": sum(1 for case in cases_summary if case["task_exists"]),
        "existing_expected_target_files": sum(case["expected_targets"]["existing"] for case in cases_summary),
        "existing_expected_test_files": sum(case["expected_tests"]["existing"] for case in cases_summary),
    }

    hypotheses = []
    for key, spec in HYPOTHESES.items():
        hypotheses.append(
            {
                "id": key,
                "statement": spec["statement"],
                "verdict": "UNVERIFIED",
                "baseline_status": "missing_required_baseline",
                "missing_metrics": list(spec["required_metrics"]),
                "measured_metrics": {},
                "note": (
                    "The committed corpus labels tasks, targets, tests, and AC ids, but does not "
                    "commit paired baseline/candidate metric runs for this hypothesis."
                ),
            }
        )

    return {
        "schema": REPORT_SCHEMA,
        "version": REPORT_VERSION,
        "issue": {
            "number": 208,
            "acceptance_criterion": "AC08",
            "scope": "Baseline-backed evaluation of H1/H2 using committed corpus and committed evidence only.",
        },
        "overall_verdict": "UNVERIFIED",
        "measured": measured,
        "cases": cases_summary,
        "artifact_status": artifact_status,
        "hypotheses": hypotheses,
        "negative_findings": [
            "No committed paired baseline/candidate token measurements exist for adaptive-vs-full context packs.",
            "No committed task pass-rate baseline exists for the issue #208 frozen corpus.",
            "No committed full-scan vs incremental p95 measurements exist for local-change causal-cone refresh on this corpus.",
            "No committed bytes-read/files-parsed/nodes-recomputed counters are attached to the issue #208 corpus cases.",
        ],
    }


def render_issue208_ac08_markdown(report: dict[str, Any]) -> str:
    measured = report["measured"]
    lines = [
        "# Issue #208 AC08 evaluation",
        "",
        "Overall verdict: **UNVERIFIED**",
        "",
        "This report is intentionally baseline-backed and evidence-conservative: it only uses "
        "committed corpus/evidence already present in the repository. It does **not** infer or "
        "fabricate missing baselines.",
        "",
        "## Measured corpus facts",
        "",
        f"- Cases in frozen corpus: {measured['corpus_case_count']}",
        f"- Languages covered: {', '.join(measured['languages'])}",
        f"- Abstention cases: {measured['abstention_case_count']}",
        f"- Expected target labels: {measured['expected_target_labels']}",
        f"- Expected test labels: {measured['expected_test_labels']}",
        f"- Expected AC labels: {measured['expected_ac_labels']}",
        f"- Fixtures with committed task file: {measured['fixtures_with_task_file']}",
        f"- Existing expected target files: {measured['existing_expected_target_files']}",
        f"- Existing expected test files: {measured['existing_expected_test_files']}",
        "",
        "## Supporting artifacts checked",
        "",
    ]
    for artifact in report["artifact_status"]:
        state = "present" if artifact["present"] else "missing"
        lines.append(f"- `{artifact['path']}` — {state}; {artifact['note']}")
    lines.extend(["", "## Hypothesis verdicts", ""])
    for hypothesis in report["hypotheses"]:
        lines.append(f"### {hypothesis['id']}")
        lines.append("")
        lines.append(f"- Statement: {hypothesis['statement']}")
        lines.append(f"- Verdict: **{hypothesis['verdict']}**")
        lines.append(f"- Baseline status: `{hypothesis['baseline_status']}`")
        lines.append(f"- Missing metrics: {', '.join(hypothesis['missing_metrics'])}")
        lines.append(f"- Note: {hypothesis['note']}")
        lines.append("")
    lines.extend(["## Negative findings", ""])
    for finding in report["negative_findings"]:
        lines.append(f"- {finding}")
    lines.extend(["", "## Case inventory", ""])
    for case in report["cases"]:
        lines.append(
            f"- `{case['id']}` ({case['language']}) — task_exists={str(case['task_exists']).lower()}, "
            f"targets={case['expected_targets']['existing']}/{case['expected_targets']['declared']}, "
            f"tests={case['expected_tests']['existing']}/{case['expected_tests']['declared']}, "
            f"ac_ids={', '.join(case['expected_ac_ids']) if case['expected_ac_ids'] else '(none)'}"
        )
    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            "H1 and H2 cannot be accepted or refuted from the currently committed issue #208 corpus "
            "and evidence alone. The honest state is `UNVERIFIED` until paired baseline/candidate "
            "measurements are committed.",
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "REPORT_SCHEMA",
    "REPORT_VERSION",
    "build_issue208_ac08_report",
    "render_issue208_ac08_markdown",
]
