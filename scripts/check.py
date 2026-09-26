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


def run_contract_headers():
    _hr("contract-headers (immutable header + What the model sees, #1342)")
    path = os.path.join(HERE, "contract_headers.py")
    return _gate_result(
        "contract_headers",
        _run_bounded([sys.executable, path], phase="contract_headers"),
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


PACKAGE_ROOTS = {
    "mapper": os.path.join(REPO, "packages", "mapper"),
    "dev-cli": os.path.join(REPO, "packages", "dev-cli"),
    "loop": REPO,
}
PACKAGE_NAMES = ("mapper", "dev-cli", "loop")
PACKAGE_PREFIXES = {
    "packages/mapper/": "mapper",
    "packages/dev-cli/": "dev-cli",
}


def _tool_argv(tool):
    """Prefer a real PATH executable; fall back to `python -m <tool>`."""
    found = shutil.which(tool)
    return [found] if found else [sys.executable, "-m", tool]


def _tool_available(argv_head, *, cwd):
    """Cheap `--version` preflight, decoupled from the real step's output --
    grepping a test run's own captured stdout/stderr for "No module named"
    risks a false positive from a test's OWN assertion text. Returns True,
    False, or None (inconclusive: timeout/containment -- caller must not
    treat that as a silent skip)."""
    probe = _run_bounded(
        list(argv_head) + ["--version"], phase="package_gate_lint", cwd=cwd, capture_output=True,
    )
    if probe.timed_out or probe.reason == CommandReason.CONTAINMENT_UNAVAILABLE:
        return None
    return probe.returncode == 0


def _run_step(tool_argv, task_args, *, phase, cwd, missing_reason, fail_reason, env=None):
    """Run one package-gate step, after a dedicated tool-availability
    preflight. ``tool_argv`` is the tool invocation prefix (e.g. ["ruff"] or
    [python, "-m", "ruff"]); ``task_args`` are the subcommand's own args.
    Return None on success, a GateResult on failure -- a missing tool gets
    its own typed reason, never a silent skip."""
    argv = list(tool_argv) + list(task_args)
    available = _tool_available(tool_argv, cwd=cwd)
    if available is None:
        return GateResult(False, fail_reason + "_tool_probe_inconclusive")
    if available is False:
        return GateResult(False, missing_reason)
    command = _run_bounded(argv, phase=phase, cwd=cwd, capture_output=True, env=env)
    if command.stdout:
        print(command.stdout, end="" if command.stdout.endswith("\n") else "\n")
    if command.stderr:
        print(command.stderr, end="" if command.stderr.endswith("\n") else "\n", file=sys.stderr)
    if command.timed_out:
        return GateResult(False, fail_reason + "_timeout")
    if command.reason == CommandReason.CONTAINMENT_UNAVAILABLE:
        return GateResult(False, fail_reason + "_containment_unavailable")
    if command.reason == CommandReason.DESCENDANT_LEAK:
        return GateResult(False, fail_reason + "_descendant_leak")
    if command.returncode != 0:
        return GateResult(False, fail_reason)
    return None


def run_package_gate(pkg):
    """Run one package's own fast local gate from its in-repo location.

    ``loop`` (the root package) is a no-op alias here: its gate is already
    every other function in this file, run unconditionally by the default
    (no ``--package``) invocation -- ``--package loop``/``--package all``
    only needs a uniform, addressable name for it, never a second full run.
    """
    _hr("package-gate: %s" % pkg)
    root = PACKAGE_ROOTS.get(pkg)
    if root is None:
        return GateResult(False, "package_unknown")
    if not os.path.isdir(root):
        return GateResult(False, "package_%s_root_missing" % pkg.replace("-", "_"))

    if pkg == "loop":
        print("(the root package's gate is the rest of this script's default run)")
        return GateResult(True, "delegated_to_default_gate")

    if pkg == "mapper":
        fail = _run_step(
            _tool_argv("ruff"), ["check", "."], phase="package_gate_lint", cwd=root,
            missing_reason="package_mapper_ruff_missing", fail_reason="package_mapper_ruff_failed",
        )
        if fail:
            return fail
        fail = _run_step(
            _pytest_command(), ["tests/python", "-q"], phase="package_gate_tests", cwd=root,
            missing_reason="package_mapper_pytest_missing", fail_reason="package_mapper_pytest_failed",
        )
        if fail:
            return fail
        node = shutil.which("node")
        if node is None:
            print("node not found on PATH -- mapper's node unit tests skipped "
                  "(typed reason: package_mapper_node_unavailable, not a hard fail)")
            return GateResult(True, "package_mapper_node_unavailable")
        node_tests = sorted(glob.glob(os.path.join(root, "tests", "unit", "*.test.js")))
        if not node_tests:
            return GateResult(True, "package_mapper_no_node_tests")
        rel_tests = [os.path.relpath(p, root) for p in node_tests]
        fail = _run_step(
            [node], ["--test"] + rel_tests, phase="package_gate_tests", cwd=root,
            missing_reason="package_mapper_node_missing", fail_reason="package_mapper_node_tests_failed",
        )
        if fail:
            return fail
        return GateResult(True, "ok")

    if pkg == "dev-cli":
        fail = _run_step(
            _tool_argv("ruff"), ["check", "."], phase="package_gate_lint", cwd=root,
            missing_reason="package_devcli_ruff_missing", fail_reason="package_devcli_ruff_check_failed",
        )
        if fail:
            return fail
        fail = _run_step(
            _tool_argv("ruff"), ["format", "--check", "."], phase="package_gate_lint", cwd=root,
            missing_reason="package_devcli_ruff_missing", fail_reason="package_devcli_ruff_format_failed",
        )
        if fail:
            return fail
        fail = _run_step(
            _tool_argv("mypy"), ["simplicio"], phase="package_gate_typecheck", cwd=root,
            missing_reason="package_devcli_mypy_missing", fail_reason="package_devcli_mypy_failed",
        )
        if fail:
            return fail
        fail = _run_step(
            _pytest_command(), ["tests/python", "tests/contracts", "-q"], phase="package_gate_tests", cwd=root,
            missing_reason="package_devcli_pytest_missing", fail_reason="package_devcli_pytest_failed",
        )
        if fail:
            return fail
        return GateResult(True, "ok")

    return GateResult(False, "package_unknown")


def _changed_packages():
    """Packages touched vs origin/main (``git diff --name-only``), for
    ``--changed``. Falls back to "all" (never silently narrows) when the
    merge-base/diff cannot be determined -- e.g. shallow clone, no
    origin/main, or detached history."""
    command = _run_bounded(
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        phase="package_gate_lint", cwd=REPO, capture_output=True,
    )
    if command.returncode != 0 or command.timed_out:
        command = _run_bounded(
            ["git", "diff", "--name-only", "HEAD"],
            phase="package_gate_lint", cwd=REPO, capture_output=True,
        )
    if command.returncode != 0 or command.timed_out:
        return set(PACKAGE_NAMES)
    touched = set()
    root_touched = False
    for line in (command.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        matched = False
        for prefix, name in PACKAGE_PREFIXES.items():
            if line.startswith(prefix):
                touched.add(name)
                matched = True
                break
        if not matched:
            root_touched = True
    if root_touched:
        touched.add("loop")
    return touched or set(PACKAGE_NAMES)


def main():
    global _core_deadline
    args = sys.argv[1:]

    package_arg = None
    if "--package" in args:
        idx = args.index("--package")
        if idx + 1 >= len(args):
            print("check: FAIL (--package requires a value: mapper|dev-cli|loop|all)",
                  file=sys.stderr)
            sys.exit(2)
        package_arg = args[idx + 1]
        if package_arg not in PACKAGE_NAMES and package_arg != "all":
            print("check: FAIL (--package must be one of mapper|dev-cli|loop|all, got %r)"
                  % package_arg, file=sys.stderr)
            sys.exit(2)
        args = args[:idx] + args[idx + 2:]
    changed_mode = "--changed" in args
    args = [a for a in args if a != "--changed"]
    package_mode = package_arg is not None or changed_mode

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
    any_only = any(a in args for a in only_flags) or core_gate or package_mode
    results = {name: GateResult(True, "not_run") for name in (
        "audit", "mirror_parity", "tests", "loop_contract", "clean_env",
        "token_budget", "repo_budget", "conformance", "package_content", "contract_headers",
    )}
    if not any_only or "--audit-only" in args or core_gate:
        results["audit"] = run_audit()
        results["contract_headers"] = run_contract_headers()
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

    if package_mode:
        if changed_mode:
            selected = _changed_packages()
            if package_arg is not None and package_arg != "all":
                selected &= {package_arg}
        elif package_arg == "all":
            selected = set(PACKAGE_NAMES)
        else:
            selected = {package_arg}
        for name in PACKAGE_NAMES:
            if name in selected:
                results["package_%s" % name.replace("-", "_")] = run_package_gate(name)
            else:
                results["package_%s" % name.replace("-", "_")] = GateResult(True, "not_run")

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
    if package_mode:
        print("package-gate: %s" % " · ".join(
            "%s=%s" % (name, status["package_%s" % name.replace("-", "_")])
            for name in PACKAGE_NAMES
        ))
    print_reason_summary(results)
    _core_deadline = None
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
