#!/usr/bin/env python3
"""Offline, bounded local verifier; GitHub Actions is not evidence."""
import os
import sys
import glob
import shutil
import time

try:
    from .check_runtime import (
        CommandResult as CommandResult,
        CommandReason,
        GateResult,
        PHASE_TIMEOUT_SECONDS,
        aggregate_reason_groups as aggregate_reason_groups,
        classify_pytest_reasons,
        gate_result as _gate_result,
        print_reason_summary,
        pytest_collected_count as _external_test_count,
        pytest_summary_count,
        run_bounded as _runtime_run_bounded,
    )
except ImportError:  # direct `python scripts/check.py` execution
    from check_runtime import (
        CommandResult as CommandResult,
        CommandReason,
        GateResult,
        PHASE_TIMEOUT_SECONDS,
        aggregate_reason_groups as aggregate_reason_groups,
        classify_pytest_reasons,
        gate_result as _gate_result,
        print_reason_summary,
        pytest_collected_count as _external_test_count,
        pytest_summary_count,
        run_bounded as _runtime_run_bounded,
    )

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SYSTEM_TEST_NESTED_GUARD = "SIMPLICIO_SYSTEM_TEST_NESTED"
# The phase limits remain the primary containment boundary.  The aggregate
# deadline must exceed the core-test allowance so audit/parity work does not
# consume part of the suite's legitimate runtime on a cold machine.
CORE_GATE_TIMEOUT_SECONDS = 900.0
TEST_FILE_SHARD_SIZE = 8
_core_deadline = None


def _run_bounded(*args, **kwargs):
    """Apply one absolute deadline to the mandatory core gate."""
    if _core_deadline is not None:
        env = dict(kwargs.get("env") or os.environ)
        env["SIMPLICIO_CORE_NO_NETWORK"] = "1"
        kwargs["env"] = env
        remaining = _core_deadline - time.monotonic()
        if remaining <= 0:
            phase = kwargs.get("phase", "phase")
            return CommandResult(124, timed_out=True, stderr="core gate deadline exhausted: %s" % phase)
        configured = kwargs.get("timeout_seconds")
        phase_timeout = PHASE_TIMEOUT_SECONDS[kwargs.get("phase")]
        requested = phase_timeout if configured is None else configured
        kwargs["timeout_seconds"] = min(remaining, requested)
    return _runtime_run_bounded(*args, **kwargs)


def _pytest_command():
    """Use the pytest executable selected by the active environment.

    ``uv run pytest`` may intentionally expose a standalone pytest executable
    while ``uv run python -m pytest`` uses a project interpreter without the
    pytest module installed.  The local gate must follow the former so its
    result matches the documented source-checkout command.
    """
    executable = shutil.which("pytest")
    return [executable] if executable else [sys.executable, "-m", "pytest"]

# #118 — opt-in satellite files excluded from the mandatory core; see the scripts inventory.
SATELLITE_TEST_STEMS = frozenset([
    "test_agentsview_adapter_integration",
    "test_autoresearch_system",
    "test_az_boards_adapter_integration",
    "test_dashboard_hook_integration",
    "test_e2e_demo_audit_system",
    "test_fan_out_flow_system",
    "test_fan_out_scheduler_integration",
    "test_fan_out_unit",
    "test_learn_pipeline_removed_regression",
    "test_independent_watcher_integration",
    "test_repo_conventions_architecture_unit",
    "test_schema_verify_integration",
    "test_schema_verify_unit",
    "test_check_e2e_demo_contract_system",
])

def _hr(title):
    print("\n=== %s ===" % title, flush=True)


def run_audit():
    _hr("claims-audit")
    path = os.path.join(HERE, "claims_audit.py")
    if not os.path.isfile(path):
        print("scripts/claims_audit.py not found")
        return GateResult(False, "claims_audit_missing")
    argv = [sys.executable, path]
    if _core_deadline is not None:
        argv.append("--core")
    command = _run_bounded(argv, phase="claims_audit", capture_output=True)
    if command.stdout:
        print(command.stdout, end="" if command.stdout.endswith("\n") else "\n")
    if command.stderr:
        print(command.stderr, end="" if command.stderr.endswith("\n") else "\n", file=sys.stderr)
    return _gate_result("claims_audit", command)


def _have_pytest():
    command = _run_bounded(
        _pytest_command() + ["--version"],
        phase="pytest_probe",
        capture_output=True,
    )
    if command.timed_out:
        return None
    if command.reason == CommandReason.CONTAINMENT_UNAVAILABLE:
        return "containment_unavailable"
    return command.returncode == 0


def _core_test_files(tests_dir):
    return sorted(
        tf for tf in glob.glob(os.path.join(tests_dir, "test_*.py"))
        if os.path.splitext(os.path.basename(tf))[0] not in SATELLITE_TEST_STEMS)


def _test_file_shards(test_files, shard_size=TEST_FILE_SHARD_SIZE):
    """Split pytest file targets so Windows never receives a command-line-sized test list."""
    if shard_size <= 0:
        raise ValueError("shard_size must be positive")
    files = list(test_files)
    return [files[start:start + shard_size] for start in range(0, len(files), shard_size)]


def _merge_pytest_reasons(target, source):
    for category, codes in source.items():
        bucket = target.setdefault(category, {})
        for code, count in codes.items():
            bucket[code] = bucket.get(code, 0) + count


def _pytest_args(test_files, only_core=False):
    args = _pytest_command() + ["-q", "-ra"]
    # Installed/live lanes are explicit and never local-gate proof.
    marker_expression = "not external_integration"
    if only_core:
        marker_expression += " and not satellite"
    args.extend(["-m", marker_expression])
    return args + list(test_files)


def _collect_marker_exclusions(test_files, env, marker_expression, unparseable_reason):
    """Collect one marker expression and return its exact selected-node count."""
    command = _run_bounded(
        _pytest_command() + ["-q", "--collect-only", "-m",
         marker_expression] + list(test_files),
        phase="pytest_collect",
        env=env,
        capture_output=True,
    )
    output = command.stdout + "\n" + command.stderr
    if command.returncode == 5 and "no tests collected" in output.lower():
        return 0, "", output
    result = _gate_result("pytest_collect", command)
    if not result.ok:
        return None, result.reason_code, output
    count = _external_test_count(output)
    if count is None:
        return None, unparseable_reason, output
    return count, "", output


def _external_exclusion_reason(count):
    return "EXTERNAL_INTEGRATION_EXCLUDED[marker_selection]=%d" % count


def _passed_test_count(output):
    return pytest_summary_count(output, "passed")


def _deselected_test_count(output):
    return pytest_summary_count(output, "deselected")


def run_tests(only_core=False):
    tests_dir = os.path.join(REPO, "tests")
    if not os.path.isdir(tests_dir):
        print("tests/ not found")
        return GateResult(False, "tests_missing")
    # Prevent system-check tests from recursively launching another full gate.
    env = dict(os.environ)
    env[SYSTEM_TEST_NESTED_GUARD] = "1"
    if only_core:
        test_files = _core_test_files(tests_dir)
        label = "tests/ (core-gate — satellite tests skipped)"
    else:
        test_files = sorted(glob.glob(os.path.join(tests_dir, "test_*.py")))
        label = "tests/"
    if not test_files:
        print("no selected test files")
        return GateResult(False, "core_tests_missing" if only_core else "tests_missing")
    have_pytest = _have_pytest()
    if have_pytest is None:
        return GateResult(False, "pytest_probe_timeout")
    if have_pytest == "containment_unavailable":
        return GateResult(False, "pytest_probe_containment_unavailable")
    if have_pytest:
        phase = "core_tests" if only_core else "tests"
        shards = _test_file_shards(test_files)
        merged_reasons = {}
        passed_total = 0
        excluded_total = 0
        satellite_excluded_total = 0
        for index, shard in enumerate(shards, start=1):
            shard_label = "%s shard %d/%d" % (label, index, len(shards))
            excluded, collect_error, collect_output = _collect_marker_exclusions(
                shard, env, "external_integration", "pytest_external_collect_unparseable",
            )
            if collect_error:
                if collect_output:
                    print(collect_output, end="" if collect_output.endswith("\n") else "\n")
                return GateResult(False, collect_error, merged_reasons)
            satellite_excluded = 0
            expected_deselected = excluded
            if only_core:
                satellite_excluded, collect_error, collect_output = _collect_marker_exclusions(
                    shard, env, "satellite", "pytest_satellite_collect_unparseable",
                )
                if collect_error:
                    if collect_output:
                        print(collect_output, end="" if collect_output.endswith("\n") else "\n")
                    return GateResult(False, collect_error, merged_reasons)
                expected_deselected, collect_error, collect_output = _collect_marker_exclusions(
                    shard, env, "external_integration or satellite",
                    "pytest_core_marker_collect_unparseable",
                )
                if collect_error:
                    if collect_output:
                        print(collect_output, end="" if collect_output.endswith("\n") else "\n")
                    return GateResult(False, collect_error, merged_reasons)
            _hr("pytest %s" % shard_label)
            command = _run_bounded(
                _pytest_args(shard, only_core=only_core),
                phase=phase,
                env=env,
                capture_output=True,
            )
            if command.stdout:
                print(command.stdout, end="" if command.stdout.endswith("\n") else "\n")
            if command.stderr:
                print(command.stderr, end="" if command.stderr.endswith("\n") else "\n", file=sys.stderr)
            exclusion_reason = _external_exclusion_reason(excluded)
            print(exclusion_reason)
            if only_core:
                print("SATELLITE_EXCLUDED[core_marker_selection]=%d" % satellite_excluded)
            output = command.stdout + "\n" + command.stderr
            reasons = classify_pytest_reasons(output + "\n" + exclusion_reason)
            _merge_pytest_reasons(merged_reasons, reasons)
            excluded_total += excluded
            satellite_excluded_total += satellite_excluded
            base = _gate_result(phase, command)
            # A shard containing only excluded marker tests is valid; the overall lane
            # still requires at least one executed test below.
            if base.reason_code == "pytest_no_tests_collected" and expected_deselected:
                base = GateResult(True)
            if not base.ok:
                return GateResult(False, base.reason_code, merged_reasons)
            actual_deselected = _deselected_test_count(output)
            if actual_deselected != expected_deselected:
                return GateResult(False, "pytest_marker_selection_mismatch", merged_reasons)
            passed_total += _passed_test_count(output)
        print("EXTERNAL_INTEGRATION_EXCLUDED[marker_selection]=%d" % excluded_total)
        if only_core:
            print("SATELLITE_EXCLUDED[core_marker_selection]=%d" % satellite_excluded_total)
        if passed_total == 0:
            return GateResult(False, "pytest_all_tests_skipped", merged_reasons)
        return GateResult(True, reasons=merged_reasons)
    print("pytest is unavailable or cannot import")
    return GateResult(False, "pytest_unavailable")


def run_mirror_parity():
    _hr("mirror-parity")
    path = os.path.join(HERE, "mirror_parity.py")
    if not os.path.isfile(path):
        print("scripts/mirror_parity.py not found")
        return GateResult(False, "mirror_parity_missing")
    command = _run_bounded([sys.executable, path, "check"], phase="mirror_parity",
                           capture_output=True)
    if command.stdout:
        print(command.stdout, end="" if command.stdout.endswith("\n") else "\n")
    if command.stderr:
        print(command.stderr, end="" if command.stderr.endswith("\n") else "\n", file=sys.stderr)
    return _gate_result("mirror_parity", command)


def run_loop_contract():
    _hr("loop-contract (simplicio.loop-execution/v1)")
    path = os.path.join(HERE, "check_loop_contract.py")
    if not os.path.isfile(path):
        print("scripts/check_loop_contract.py not found")
        return GateResult(False, "loop_contract_missing")
    return _gate_result(
        "loop_contract",
        _run_bounded([sys.executable, path], phase="loop_contract"),
    )


def run_clean_env_contract():
    _hr("clean-env-contract")
    path = os.path.join(HERE, "clean_env_contract.py")
    if not os.path.isfile(path):
        print("scripts/clean_env_contract.py not found")
        return GateResult(False, "clean_env_missing")
    return _gate_result(
        "clean_env",
        _run_bounded([sys.executable, path, "check"], phase="clean_env"),
    )


def run_token_budget():
    _hr("token-budget (#121)")
    path = os.path.join(HERE, "token_budget.py")
    if not os.path.isfile(path):
        print("scripts/token_budget.py not found")
        return GateResult(False, "token_budget_missing")
    return _gate_result(
        "token_budget",
        _run_bounded([sys.executable, path], phase="token_budget"),
    )


def run_repository_budget():
    _hr("repo-budget (#294)")
    path = os.path.join(HERE, "repository_budget.py")
    if not os.path.isfile(path):
        print("scripts/repository_budget.py not found")
        return GateResult(False, "repo_budget_missing")
    return _gate_result(
        "repo_budget",
        _run_bounded([sys.executable, path], phase="repo_budget"),
    )


def run_conformance():
    # Portable schema/receipt proof only; installed runtimes are external.
    _hr("portable stage-contract validation (#432)")
    path = os.path.join(HERE, "conformance_suite.py")
    if not os.path.isfile(path):
        print("scripts/conformance_suite.py not found")
        return GateResult(False, "conformance_missing")
    return _gate_result(
        "conformance",
        _run_bounded([sys.executable, path], phase="conformance"),
    )


def run_package_content():
    # Explicit release lane; it builds real package artifacts.
    _hr("package-content (#294 AC11)")
    path = os.path.join(HERE, "package_content_check.py")
    if not os.path.isfile(path):
        print("scripts/package_content_check.py not found")
        return GateResult(False, "package_content_missing")
    return _gate_result(
        "package_content",
        _run_bounded([sys.executable, path], phase="package_content"),
    )


def main():
    global _core_deadline
    args = sys.argv[1:]
    supported_flags = {
        "--core-gate", "--audit-only", "--tests-only", "--mirror-parity-only",
        "--loop-contract-only", "--clean-env-only", "--token-budget", "--repo-budget",
        "--conformance", "--package-content",
    }
    unknown_flags = sorted(set(args) - supported_flags)
    if unknown_flags:
        print("check: FAIL (unknown flag(s): %s)" % ", ".join(unknown_flags), file=sys.stderr)
        sys.exit(2)
    core_gate = "--core-gate" in args
    _core_deadline = time.monotonic() + CORE_GATE_TIMEOUT_SECONDS if core_gate else None
    only_flags = {"--audit-only", "--tests-only", "--mirror-parity-only", "--loop-contract-only",
                  "--clean-env-only", "--token-budget", "--repo-budget", "--conformance",
                  "--package-content"}
    any_only = any(a in args for a in only_flags) or core_gate
    results = {name: GateResult(True, "not_run") for name in (
        "audit", "mirror_parity", "tests", "loop_contract", "clean_env",
        "token_budget", "repo_budget", "conformance", "package_content",
    )}
    if not any_only or "--audit-only" in args or core_gate:
        results["audit"] = run_audit()
    if not any_only or "--mirror-parity-only" in args or core_gate:
        results["mirror_parity"] = run_mirror_parity()
    if not any_only or "--tests-only" in args or core_gate:
        results["tests"] = run_tests(only_core=core_gate)
    if not any_only or "--loop-contract-only" in args or core_gate:
        results["loop_contract"] = run_loop_contract()
    if not any_only or "--clean-env-only" in args or core_gate:
        results["clean_env"] = run_clean_env_contract()
    if not any_only or "--token-budget" in args or core_gate:
        results["token_budget"] = run_token_budget()
    if not any_only or "--repo-budget" in args or core_gate:
        results["repo_budget"] = run_repository_budget()
    if not any_only or "--conformance" in args or core_gate:
        results["conformance"] = run_conformance()
    if "--package-content" in args:
        # Deliberately NOT included in "not any_only" (the default full run) or core_gate — see
        # run_package_content()'s docstring: opt-in only, ~20-30s, a release-time check.
        results["package_content"] = run_package_content()
    ok = all(result.ok for result in results.values())
    status = {
        name: ("not_run" if result.reason_code == "not_run" else ("ok" if result.ok else "FAIL"))
        for name, result in results.items()
    }
    if core_gate:
        print("\ncore-gate: %s  (audit=%s · mirror-parity=%s · core-tests=%s · loop-contract=%s · clean-env=%s · token-budget=%s · repo-budget=%s · conformance=%s)" % (
            "PASS" if ok else "FAIL", status["audit"], status["mirror_parity"],
            status["tests"], status["loop_contract"], status["clean_env"],
            status["token_budget"], status["repo_budget"], status["conformance"]))
    print("\ncheck: %s  (audit=%s · mirror-parity=%s · tests=%s · loop-contract=%s · clean-env=%s · token-budget=%s · repo-budget=%s · conformance=%s · package-content=%s)" % (
        "PASS" if ok else "FAIL", status["audit"], status["mirror_parity"], status["tests"],
        status["loop_contract"], status["clean_env"], status["token_budget"],
        status["repo_budget"], status["conformance"], status["package_content"]))
    print_reason_summary(results)
    _core_deadline = None
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
