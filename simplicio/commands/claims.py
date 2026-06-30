"""Claims-gate discipline: 8 rules + MEASURED/CANON/UNVERIFIED tagging.

Absorbed from Asolaria's AGENT-BRIEF.md. Every claim made during
development — about performance, correctness, architecture, or
evidence — must pass the gate before it enters a report, a PR, or
a sprint summary.

Tag taxonomy
------------
MEASURED     Empirically verified. Data-backed, reproducible, with
             a specific measurement (latency, throughput, coverage).
CANON        Authoritative source-of-truth reference. The fabric
             (code, CI log, compiled binary, hardware spec) is
             authority — mirrors, transcripts, or heuristics are not.
UNVERIFIED   Unsubstantiated. No data, no authority, no channel.
             Tagged so it can never be confused with evidence.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# The 8 rules
# ---------------------------------------------------------------------------

RULES: list[dict] = [
    {
        "id": 1,
        "slug": "ground_impact_before_severity",
        "label": "ground impact before severity",
        "description": (
            "Ground every claim in actual impact before assigning a "
            "severity label. 'Critical' without a concrete downstream "
            "effect is an empty assertion."
        ),
        "check": _rule_1_ground,
    },
    {
        "id": 2,
        "slug": "no_flat_tuples",
        "label": "no flat tuples — preserve the 60D HyperBEHCS axes",
        "description": (
            "Never collapse multi-dimensional measurements into a "
            "single scalar. Each of the 60 HyperBEHCS axes must be "
            "reported independently."
        ),
        "check": _rule_2_tuples,
    },
    {
        "id": 3,
        "slug": "mirrors_not_authority",
        "label": "mirrors ≠ authority — fabric é authority",
        "description": (
            "A screenshot, a transcript, or a human recollection is "
            "a mirror, not authority. The fabric — code, CI log, "
            "compiled binary, deployed system — is the only authority."
        ),
        "check": _rule_3_mirrors,
    },
    {
        "id": 4,
        "slug": "cylinders_not_levels",
        "label": "cylinders ≠ levels — count distinct cylinders/towers",
        "description": (
            "Do not confuse layer/level abstractions with running "
            "instances. Count distinct cylinders, towers, or pods, "
            "not architectural tiers."
        ),
        "check": _rule_4_cylinders,
    },
    {
        "id": 5,
        "slug": "owning_gate_not_transcript",
        "label": "owning gate, not transcript — verify via gh/CI, not pasted log",
        "description": (
            "Never accept a pasted terminal log as proof of a gate "
            "passing. Verify through the owning gate — GitHub check "
            "run, CI pipeline status, or the actual test runner exit "
            "code replayed locally."
        ),
        "check": _rule_5_gate,
    },
    {
        "id": 6,
        "slug": "missing_not_clean_zero",
        "label": "missing ≠ clean-zero — unreadable ledger emits missing=1/ok=0",
        "description": (
            "If a ledger, log, or data source cannot be read, the "
            "status is 'missing' not 'clean-zero'. An empty result "
            "from a broken channel must not be reported as success."
        ),
        "check": _rule_6_missing,
    },
    {
        "id": 7,
        "slug": "real_lane_not_windows",
        "label": "real lane, not Windows — Linux/WSL/USB-raw first",
        "description": (
            "Production runs on Linux, containers, or bare metal. "
            "Windows timings, WSL paths, or emulated environments "
            "must be explicitly flagged as non-primary lanes."
        ),
        "check": _rule_7_lane,
    },
    {
        "id": 8,
        "slug": "source_not_live",
        "label": "source ≠ live — distinguish source/built/running/live",
        "description": (
            "A claim about source code is not a claim about the "
            "running system. Distinguish: source (uncompiled), "
            "built (artifact), running (process), live (production "
            "traffic)."
        ),
        "check": _rule_8_source,
    },
]


# ---------------------------------------------------------------------------
# Per-rule check functions
# ---------------------------------------------------------------------------

def _rule_1_ground(statement: str) -> dict:
    """Check that impact is grounded before severity is claimed."""
    issues: list[str] = []
    severity_words = {"critical", "high", "medium", "low", "blocker", "urgent"}

    found_severity = set()
    for word in severity_words:
        if re.search(rf"\b{re.escape(word)}\b", statement, re.IGNORECASE):
            found_severity.add(word)

    if found_severity:
        # Look for grounding phrases nearby (within ~60 chars of severity word)
        has_impact_ground = bool(
            re.search(
                r"(?:impact|effect|affect|causes?|results?\s+in|lead[s]?\s+to|"
                r"downtime|data\s+loss|performance\s+degrades?|user[s]?\s+affect|"
                r"block[s]?\s+deploy|fails?\s+when|reproducib)",
                statement,
                re.IGNORECASE,
            )
        )
        if not has_impact_ground:
            issues.append(
                f"severity label '{', '.join(found_severity)}' used without "
                "grounding in concrete impact"
            )

    return {
        "rule_id": 1,
        "slug": "ground_impact_before_severity",
        "pass": len(issues) == 0,
        "issues": issues,
    }


def _rule_2_tuples(statement: str) -> dict:
    """Check that dimensions are not collapsed into flat scalars."""
    issues: list[str] = []
    flat_signal_words = {
        "faster", "slower", "better", "worse", "improved",
        "degraded", "more", "less",
    }

    found_flat = set()
    for word in flat_signal_words:
        if re.search(rf"\b{re.escape(word)}\b", statement, re.I):
            found_flat.add(word)

    if found_flat:
        # Check if dimensions/axes are specified
        has_dimensions = bool(
            re.search(
                r"(?:dimension|axis|metric|p50|p95|p99|percentile|latency|"
                r"throughput|memory|cpu|i/o|concurrency|users?|requests?|"
                r"HyperBEHCS|60[ -]?[Dd]|BEHCS)",
                statement,
                re.IGNORECASE,
            )
        )
        if not has_dimensions:
            issues.append(
                f"flat comparison '{', '.join(found_flat)}' without "
                "dimensional axes — should preserve HyperBEHCS structure"
            )

    return {
        "rule_id": 2,
        "slug": "no_flat_tuples",
        "pass": len(issues) == 0,
        "issues": issues,
    }


def _rule_3_mirrors(statement: str) -> dict:
    """Check that mirrors are not conflated with authority."""
    issues: list[str] = []
    mirror_signals = {
        "screenshot", "transcript", "screen cap", "screen recording",
        "human said", "developer told", "i think", "i believe",
        "recollection", "as far as i know", "my memory",
        "somebody said", "i heard",
    }

    found_mirror = None
    for phrase in sorted(mirror_signals, key=len, reverse=True):
        if re.search(rf"\b{re.escape(phrase)}\b", statement, re.I):
            found_mirror = phrase
            break

    if found_mirror:
        has_fabric_anchor = bool(
            re.search(
                r"(?:code\s+show|ci\s+log|compile[dr]|binary|deploy|"
                r"repo|git\s+log|test\s+run|pipeline|artifact)",
                statement,
                re.IGNORECASE,
            )
        )
        if not has_fabric_anchor:
            issues.append(
                f"mirror signal '{found_mirror}' without fabric "
                "anchor — fabric é authority"
            )

    return {
        "rule_id": 3,
        "slug": "mirrors_not_authority",
        "pass": len(issues) == 0,
        "issues": issues,
    }


def _rule_4_cylinders(statement: str) -> dict:
    """Check that cylinders/towers are counted, not levels."""
    issues: list[str] = []
    level_words = {"layer", "level", "tier", "stack"}
    cylinder_words = {"cylinder", "tower", "pod", "instance", "node", "replica"}
    count_words = {"one", "two", "three", "four", "five", "single", "double",
                   "1", "2", "3", "4", "5", "n", "multiple", "several"}

    found_level = set()
    for word in level_words:
        if re.search(rf"\b{re.escape(word)}\b", statement, re.I):
            found_level.add(word)

    found_cylinder = set()
    for word in cylinder_words:
        if re.search(rf"\b{re.escape(word)}\b", statement, re.I):
            found_cylinder.add(word)

    if found_level and not found_cylinder:
        # Level abstraction used but no distinct cylinder/tower count mentioned
        has_count = False
        for word in count_words:
            if re.search(rf"\b{re.escape(word)}\b", statement, re.I):
                has_count = True
                break

        if not has_count:
            issues.append(
                f"layer/level abstraction ('{', '.join(found_level)}') used "
                "without distinct cylinder/tower count"
            )

    return {
        "rule_id": 4,
        "slug": "cylinders_not_levels",
        "pass": len(issues) == 0,
        "issues": issues,
    }


def _rule_5_gate(statement: str) -> dict:
    """Check that gate verification does not rely on pasted logs."""
    issues: list[str] = []
    paste_signals = {
        "pasted", "copy-paste", "ctrl+c", "ctrl+v", "here's the log",
        "see below", "as shown", "above log", "attached log",
        "terminal output", "i ran this", "output was",
    }

    gate_verbs = {
        "verified", "validated", "confirmed", "passed", "green",
        "ci passed", "check passed", "gate passed",
    }

    found_paste = None
    for phrase in sorted(paste_signals, key=len, reverse=True):
        if re.search(rf"\b{re.escape(phrase)}\b", statement, re.I):
            found_paste = phrase
            break

    found_gate = set()
    for word in gate_verbs:
        if re.search(rf"\b{re.escape(word)}\b", statement, re.I):
            found_gate.add(word)

    if found_gate and found_paste:
        # Gate claim backed by pasted transcript — violation
        has_gh_ci = bool(
            re.search(
                r"(?:github|gh\s+|ci\s+|pipeline|check\s+run|workflow|"
                r"actions|gitlab|jenkins|circle)",
                statement,
                re.IGNORECASE,
            )
        )
        if not has_gh_ci:
            issues.append(
                f"gate claim ('{', '.join(found_gate)}') appears to rely on "
                f"pasted transcript ('{found_paste}') instead of owning gate "
                "(gh/CI check run)"
            )

    if found_gate and not found_paste and not bool(
        re.search(r"(?:github|gh|ci|pipeline|check\s+run)", statement, re.I)
    ):
        issues.append(
            "gate claim without reference to the owning gate "
            "(gh/CI pipeline)"
        )

    return {
        "rule_id": 5,
        "slug": "owning_gate_not_transcript",
        "pass": len(issues) == 0,
        "issues": issues,
    }


def _rule_6_missing(statement: str) -> dict:
    """Check that missing/unreadable sources are not reported as clean-zero."""
    issues: list[str] = []
    missing_signals = {
        "no data", "no log", "empty log", "no output", "no result",
        "unavailable", "no access", "not found", "missing",
        "could not read", "failed to fetch", "errored",
    }

    zero_signals = {
        "zero", "0", "clean", "nothing", "none", "no errors", "no issues",
        "all good", "healthy", "ok", "clear",
    }

    found_missing = []
    for phrase in sorted(missing_signals, key=len, reverse=True):
        m = re.search(rf"\b{re.escape(phrase)}\b", statement, re.I)
        if m:
            found_missing.append((phrase, m))

    found_zero = []
    for phrase in sorted(zero_signals, key=len, reverse=True):
        m = re.search(rf"\b{re.escape(phrase)}\b", statement, re.I)
        if m:
            found_zero.append((phrase, m))

    # If source is reported as missing/unreadable AND reported OK/zero
    if found_missing and found_zero:
        # Check if there's an explicit "missing=1, ok=0" or similar
        has_explicit_missing_flag = bool(
            re.search(
                r"(?:missing[=:]\s*[1-9]|unreadable|"
                r"status[=:]\s*missing|broken\s+channel)",
                statement,
                re.IGNORECASE,
            )
        )
        if not has_explicit_missing_flag:
            issues.append(
                f"source reported as unavailable "
                f"('{found_missing[0][0]}') but presented as clean/ok "
                f"('{found_zero[0][0]}') — unreadable ledger emits "
                "missing=1/ok=0"
            )

    # If only missing signals without explicit missing=1 flag
    if found_missing and not has_explicit_missing_flag_present(statement):
        issues.append(
            "unreadable source without explicit missing=1 flag"
        )

    return {
        "rule_id": 6,
        "slug": "missing_not_clean_zero",
        "pass": len(issues) == 0,
        "issues": issues,
    }


def has_explicit_missing_flag_present(statement: str) -> bool:
    """Return True if the statement explicitly sets a missing=1 flag."""
    return bool(
        re.search(
            r"(?:missing[=:]\s*[1-9]|status[=:]\s*missing|unreadable|"
            r"broken\s+channel|no\s+data\s+available)",
            statement,
            re.IGNORECASE,
        )
    )


def _rule_7_lane(statement: str) -> dict:
    """Check that the primary lane is not a non-production environment."""
    issues: list[str] = []
    windows_signals = {
        "windows", "wsl", "cygwin", "mingw", "msys", "powershell",
    }
    non_lane_signals = {
        "emulator", "simulator", "vmware", "virtualbox", "docker desktop",
        "parallels", "qemu",
    }
    production_signals = {
        "linux", "container", "bare metal", "production", "deploy",
        "usb-raw", "raw usb",
    }

    found_windows = set()
    for word in windows_signals:
        if re.search(rf"\b{re.escape(word)}\b", statement, re.I):
            found_windows.add(word)

    found_non_lane = set()
    for word in non_lane_signals:
        if re.search(rf"\b{re.escape(word)}\b", statement, re.I):
            found_non_lane.add(word)

    found_prod = set()
    for word in production_signals:
        if re.search(rf"\b{re.escape(word)}\b", statement, re.I):
            found_prod.add(word)

    # If the claim involves a non-primary lane and no production lane
    primary_issue = found_windows or found_non_lane
    has_production_reference = bool(found_prod)

    if primary_issue and not has_production_reference:
        qualifier = ", ".join(found_windows | found_non_lane)
        issues.append(
            f"claim runs on non-primary lane ('{qualifier}') without "
            "production lane qualifier — Linux/WSL/USB-raw first"
        )

    return {
        "rule_id": 7,
        "slug": "real_lane_not_windows",
        "pass": len(issues) == 0,
        "issues": issues,
    }


def _rule_8_source(statement: str) -> dict:
    """Check that the claim distinguishes source/built/running/live."""
    lifecycle_signals = {
        "source": {"source", "code", "uncompiled", "file", "module", "class"},
        "built": {"built", "artifact", "compiled", "binary", "build", "dist", "wheel"},
        "running": {"running", "process", "started", "launched", "runtime", "daemon"},
        "live": {"live", "production", "deployed", "traffic", "prod", "staging", "canary"},
    }

    found_stages: dict[str, str] = {}  # stage -> first matching word
    for stage, words in lifecycle_signals.items():
        for word in words:
            if re.search(rf"\b{re.escape(word)}\b", statement, re.I):
                found_stages[stage] = word
                break

    # If a performance/behavior claim is made, check which lifecycle stage
    has_performance_claim = bool(
        re.search(
            r"(?:perform|speed|latenc|throughput|fast|slow|memory|cpu|"
            r"respond|load|stress|benchmark)",
            statement,
            re.IGNORECASE,
        )
    )

    issues: list[str] = []
    if has_performance_claim:
        if not found_stages:
            issues.append(
                "performance/behavior claim without lifecycle stage — "
                "distinguish source/built/running/live"
            )
        elif len(found_stages) == 1:
            # Single stage is fine, but if "source" is the only stage
            # for a perf claim, flag that source != running
            if "source" in found_stages:
                issues.append(
                    "claim about source code conflated with runtime "
                    "behavior — source ≠ live"
                )

    # Check for conflated stages
    if "source" in found_stages and "live" in found_stages:
        # Both source and live mentioned — check for conflation
        if not bool(
            re.search(
                r"(?:separat|distinct|differen|compile\s+then|build\s+then|"
                r"deploy\s+then|source\s+.*built\s+.*running)",
                statement,
                re.IGNORECASE,
            )
        ):
            issues.append(
                "source and live mentioned without clear separation — "
                "source ≠ built ≠ running ≠ live"
            )

    return {
        "rule_id": 8,
        "slug": "source_not_live",
        "pass": len(issues) == 0,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Check runner
# ---------------------------------------------------------------------------

def check_statement(statement: str) -> dict:
    """Run all 8 rules against *statement* and return a structured result.

    Example return::

        {
          "statement": "...",
          "pass": True,
          "rule_count": 8,
          "pass_count": 8,
          "fail_count": 0,
          "results": [ { "rule_id": 1, "slug": "...", "pass": True, ... }, ... ],
          "suggested_tag": "MEASURED"
        }
    """
    results = [rule["check"](statement) for rule in RULES]
    pass_count = sum(1 for r in results if r["pass"])
    suggested = suggest_tag(statement, results)
    return {
        "statement": statement,
        "pass": pass_count == len(RULES),
        "rule_count": len(RULES),
        "pass_count": pass_count,
        "fail_count": len(RULES) - pass_count,
        "results": results,
        "suggested_tag": suggested,
    }


# ---------------------------------------------------------------------------
# Tagging
# ---------------------------------------------------------------------------

TAG_MEASURED = "MEASURED"
TAG_CANON = "CANON"
TAG_UNVERIFIED = "UNVERIFIED"


def suggest_tag(statement: str, results: list[dict] | None = None) -> str:
    """Suggest a tag for *statement* based on content and rule results.

    Priority:
        1. UNVERIFIED — statement has no data, no numbers, no fabric anchor
        2. CANON     — statement cites authoritative fabric (code, CI,
                       compiled binary, deployed system)
        3. MEASURED  — statement contains empirical measurement
    """
    if results is None:
        results = [rule["check"](statement) for rule in RULES]

    # UNVERIFIED: no data, no authority, no channel
    has_data = bool(
        re.search(
            r"(?:\d+\.?\d*\s*(?:ms|s|mb|gb|kb|rps|qps|tps|%|bytes|"
            r"requests?|users?))",
            statement,
            re.IGNORECASE,
        )
    )
    has_authority = bool(
        re.search(
            r"(?:code\s+show|ci\s+log|compile[dr]|binary|deploy|"
            r"repo|git\s+log|test\s+run|pipeline|artifact|"
            r"github|gh\s+|ci\s+pass|check\s+run|workflow)",
            statement,
            re.IGNORECASE,
        )
    )

    # CANON: authoritative fabric reference
    fabric_signals = {
        "code", "binary", "deploy", "ci", "pipeline", "github",
        "artifact", "compiled", "repo", "commit", "tag", "release",
    }
    found_fabric = set()
    for word in fabric_signals:
        if re.search(rf"\b{re.escape(word)}\b", statement, re.I):
            found_fabric.add(word)

    # MEASURED: numbers with units, benchmarks, metrics
    measured_pattern = re.search(
        r"(?:\d+\.?\d*\s*(?:ms|s|mb|gb|kb|rps|qps|tps|%|bytes|"
        r"latency|throughput|p50|p95|p99|percentile|coverage|score|"
        r"benchmark))",
        statement,
        re.IGNORECASE,
    )
    has_empirical_measurement = bool(measured_pattern)

    if has_empirical_measurement and has_authority:
        return TAG_MEASURED
    if has_authority or found_fabric:
        return TAG_CANON
    if not has_data and not has_authority:
        return TAG_UNVERIFIED
    return TAG_CANON


def tag_statement(statement: str) -> dict:
    """Tag *statement* and return a structured result."""
    results = [rule["check"](statement) for rule in RULES]
    tag = suggest_tag(statement, results)
    return {
        "statement": statement,
        "tag": tag,
        "rule_count": len(RULES),
        "pass_count": sum(1 for r in results if r["pass"]),
        "fail_count": len(RULES) - sum(1 for r in results if r["pass"]),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

DEFAULT_REPORT_PATH = ".simplicio/claims_report.json"


def generate_report(claims: list[str] | None = None, *,
                    path: str | None = None) -> dict:
    """Generate a claims-gate report.

    If *claims* is None, the report is loaded from *path* (default:
    ``.simplicio/claims_report.json``). Otherwise *claims* are checked
    and the result is returned directly.
    """
    if claims is not None:
        return _run_report(claims)

    load_path = Path(path or DEFAULT_REPORT_PATH)
    if not load_path.is_file():
        return {
            "status": "no_report",
            "message": f"no claims report at {load_path}",
            "claims_checked": 0,
            "pass_count": 0,
            "fail_count": 0,
            "tag_counts": {},
            "claims": [],
        }
    return json.loads(load_path.read_text(encoding="utf-8"))


def _run_report(claims: list[str]) -> dict:
    """Run all claims through the gate and return an aggregated report."""
    claim_results = [check_statement(c) for c in claims]
    pass_count = sum(1 for cr in claim_results if cr["pass"])
    fail_count = len(claim_results) - pass_count
    tag_counts: dict[str, int] = {}
    for cr in claim_results:
        t = cr["suggested_tag"]
        tag_counts[t] = tag_counts.get(t, 0) + 1

    return {
        "status": "ok",
        "claims_checked": len(claims),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "tag_counts": tag_counts,
        "claims": [
            {
                "statement": cr["statement"],
                "pass": cr["pass"],
                "pass_count": cr["pass_count"],
                "fail_count": cr["fail_count"],
                "suggested_tag": cr["suggested_tag"],
                "results": cr["results"],
            }
            for cr in claim_results
        ],
    }


# ---------------------------------------------------------------------------
# CLI entrypoints
# ---------------------------------------------------------------------------

def cmd_check(args: list[str]) -> int:
    """simplicio-py claims check <statement>"""
    if not args:
        print("usage: simplicio-py claims check <statement>", file=sys.stderr)
        return 2
    statement = " ".join(args)
    result = check_statement(statement)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["pass"] else 1


def cmd_tag(args: list[str]) -> int:
    """simplicio-py claims tag <statement>"""
    if not args:
        print("usage: simplicio-py claims tag <statement>", file=sys.stderr)
        return 2
    statement = " ".join(args)
    result = tag_statement(statement)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_report(args: list[str]) -> int:
    """simplicio-py claims report [--path <path>] [--json <claims.json>]"""
    path = None
    json_file = None
    rest: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--path" and i + 1 < len(args):
            path = args[i + 1]
            i += 2
        elif args[i] == "--json" and i + 1 < len(args):
            json_file = args[i + 1]
            i += 2
        else:
            rest.append(args[i])
            i += 1

    if json_file:
        try:
            with open(json_file, encoding="utf-8") as f:
                claims_list = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"claims report: {exc}", file=sys.stderr)
            return 2
        if not isinstance(claims_list, list):
            print("claims report: --json must point to a JSON array of strings", file=sys.stderr)
            return 2
        report = generate_report(claims_list)
    elif rest:
        report = generate_report(rest)
    else:
        report = generate_report(path=path)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str]) -> int:
    """Dispatch ``claims`` subcommands.

    Usage::

        simplicio-py claims check <statement>
        simplicio-py claims tag <statement>
        simplicio-py claims report [--path <path>] [--json <file>]
    """
    if not argv or argv[0] not in ("check", "tag", "report"):
        print(
            "usage: simplicio-py claims check|tag|report [...]",
            file=sys.stderr,
        )
        print(
            "  claims check <statement>     — verify claim against 8 rules",
            file=sys.stderr,
        )
        print(
            "  claims tag <statement>       — suggest MEASURED|CANON|UNVERIFIED",
            file=sys.stderr,
        )
        print(
            "  claims report [--path <p>]   — generate/load claims report",
            file=sys.stderr,
        )
        return 2

    sub = argv[0]
    sub_args = argv[1:]

    if sub == "check":
        return cmd_check(sub_args)
    elif sub == "tag":
        return cmd_tag(sub_args)
    elif sub == "report":
        return cmd_report(sub_args)

    return 0
