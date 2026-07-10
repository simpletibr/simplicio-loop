import json

from simplicio import bench, mapper, pipeline
from simplicio import precedent as precedent_module
from simplicio import prompt as prompt_module
from simplicio.pipeline_fixers import FixerResult
from simplicio.precedent import build_precedent_block


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_mapper_consumes_project_map_and_precedent_index(tmp_path):
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("from service import run\n\nrun()\n", encoding="utf-8")
    write_json(
        tmp_path / ".simplicio" / "project-map.json",
        {
            "schema": "simplicio.project-map/v1",
            "generated_at": "2026-05-27T00:00:00Z",
            "files": [
                {
                    "path": "src/app.py",
                    "language": "python",
                    "importance": 0.91,
                    "roles": ["entrypoint"],
                    "imports": ["service"],
                    "exports": ["run"],
                },
                {
                    "path": "tests/test_app.py",
                    "language": "python",
                    "importance": 0.72,
                    "roles": ["test"],
                },
            ],
            "entry_points": ["src/app.py"],
            "test_files": ["tests/test_app.py"],
            "architecture": {"signals": ["cli", "service-layer"]},
            "modules": [{"name": "src", "files": ["src/app.py"]}],
            "recent_changes": [{"path": "src/app.py", "status": "modified"}],
        },
    )
    write_json(
        tmp_path / ".simplicio" / "precedent-index.json",
        {
            "schema": "simplicio.precedent-index/v1",
            "items": [
                {
                    "path": "tests/test_app.py",
                    "line": 7,
                    "change_type": "test",
                    "summary": "Existing service-layer test",
                    "tags": ["service", "entrypoint"],
                    "snippet": "def test_run():\n    assert run() == 0",
                }
            ],
        },
    )

    block = prompt_module._mapper(str(tmp_path), "src/app.py", goal="update service test")

    assert "project-map.json" in block
    assert "src/app.py" in block
    assert "tests/test_app.py" in block
    assert "service-layer" in block
    assert "Existing service-layer test" in block


def test_precedent_index_ranks_candidates_without_embedding(tmp_path):
    write_json(
        tmp_path / ".simplicio" / "precedent-index.json",
        {
            "items": [
                {
                    "path": "src/ui/Login.tsx",
                    "line": 12,
                    "change_type": "feature",
                    "summary": "Login guard checks permission before render",
                    "tags": ["react", "login", "permission"],
                    "snippet": "return can('login') && <Login />",
                },
                {
                    "path": "src/payments.ts",
                    "line": 3,
                    "summary": "Payment helper",
                    "tags": ["billing"],
                    "snippet": "export const pay = () => null",
                },
            ]
        },
    )

    block = build_precedent_block(str(tmp_path), "react", "fix login permission", k=1)

    assert "src/ui/Login.tsx:12" in block
    assert "Payment helper" not in block


def test_precedent_block_renders_native_precedent_search_candidates(tmp_path, monkeypatch):
    """End-to-end proof that rank_precedents()'s native-first branch
    (simplicio/mapper.py) slots into build_precedent_block()'s existing
    rendering unmodified: a translated simplicio.precedent-search/v1
    candidate (no path/line/summary of its own) still produces a legible
    [PRECEDENT] block via the same code that renders precedent-index.json
    items."""

    class _Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "schema": "simplicio.precedent-search/v1",
                "status": "ok",
                "candidates": [
                    {
                        "precedent_id": "p42",
                        "score": 0.77,
                        "reuse_level": "high",
                        "suggested_next_action": "reuse the login guard from a prior run",
                    }
                ],
            }
        )

    monkeypatch.setattr(mapper.shutil, "which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(mapper.subprocess, "run", lambda cmd, **kwargs: _Completed())

    block = build_precedent_block(str(tmp_path), "react", "fix login permission", k=1)

    assert "[PRECEDENT]" in block
    assert "precedent:p42" in block
    assert "reuse the login guard from a prior run" in block


def test_precedent_unknown_stack_falls_back_without_keyerror(tmp_path):
    # Asserts the STRUCTURAL invariant (marker + the stack name surfaced in the fallback
    # message), not literal prose wording — the exact wording of this fallback sentence is
    # an intentional optimization target of the #90 autoresearch run (bench/precedent_
    # autoresearch_mutate.py), so pinning its exact text here would make the gate reject
    # every legitimate wording improvement by construction.
    stack = "Python + FastAPI"
    block = build_precedent_block(
        str(tmp_path),
        stack,
        "Add a FastAPI route",
        k=1,
    )

    assert "[PRECEDENT]" in block
    assert repr(stack) in block


def test_precedent_alias_stack_scanner_handles_project_stack_labels(tmp_path):
    target = tmp_path / "src" / "app" / "app.routes.ts"
    target.parent.mkdir(parents=True)
    target.write_text("export const routes = [{ canActivate: [authGuard] }];\n", encoding="utf-8")

    candidates = precedent_module.grep_candidates(str(tmp_path), "node-ts-angular")

    assert len(candidates) == 1
    assert candidates[0]["line"] == 1


def test_index_repo_skips_heavy_embedding_by_default(tmp_path, monkeypatch):
    target = tmp_path / "src" / "app" / "app.routes.ts"
    target.parent.mkdir(parents=True)
    target.write_text("export const routes = [{ canActivate: [authGuard] }];\n", encoding="utf-8")

    monkeypatch.delenv("SIMPLICIO_ENABLE_EMBED_INDEX", raising=False)
    monkeypatch.setattr(
        precedent_module,
        "_embedder",
        lambda: (_ for _ in ()).throw(AssertionError("embedder should not load")),
    )

    _, candidates = precedent_module.index_repo(str(tmp_path), "node-ts-angular", verbose=False)

    assert len(candidates) == 1


def test_prompt_adds_model_adaptation_and_decomposition(tmp_path, monkeypatch):
    target = tmp_path / "src" / "feature.py"
    target.parent.mkdir(parents=True)
    target.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setenv("SIMPLICIO_MODEL", "tiny-local")
    monkeypatch.setattr(prompt_module, "build_precedent_block", lambda *a, **k: "[PRECEDENT]\nnone")
    monkeypatch.setattr(prompt_module, "build_skill_block", lambda *a, **k: "")

    rendered = prompt_module.build_prompt(
        str(tmp_path),
        "python",
        "Update mapper, add tests, and document the contract",
        "src/feature.py",
        "- tests pass",
        "- no new deps",
    )

    assert "[MODEL ADAPTATION]" in rendered
    assert "extra scaffolding" in rendered
    assert "[TASK DECOMPOSITION]" in rendered
    assert "1. Update mapper" in rendered


def test_retry_classification_and_pre_apply_validation():
    bad_output = "Here is a patch with no diff"
    assert pipeline.validate_generated_output(bad_output).ok is False
    assert pipeline.classify_failure("SyntaxError: invalid syntax").kind == "syntax"

    feedback = pipeline.build_retry_feedback(
        attempt=2,
        validation=pipeline.validate_generated_output(bad_output),
        test_log="AssertionError: expected 1 got 2",
    )

    assert "pre-apply validation failed" in feedback
    assert "assertion" in feedback
    assert "attempt 2" in feedback


def test_apply_and_test_applies_unified_diff_before_running_test(tmp_path, monkeypatch):
    target = tmp_path / "GOAL_RESULT.md"
    target.write_text("# Result\n", encoding="utf-8")
    output = "\n".join(
        [
            "```diff",
            "diff --git a/GOAL_RESULT.md b/GOAL_RESULT.md",
            "--- a/GOAL_RESULT.md",
            "+++ b/GOAL_RESULT.md",
            "@@ -1 +1,3 @@",
            " # Result",
            "+",
            "+Simplicio Sprint CLI E2E - terminal",
            "```",
            "",
            "TEST: grep marker",
        ]
    )
    monkeypatch.setenv(
        "SIMPLICIO_TEST_CMD",
        'grep -q "Simplicio Sprint CLI E2E - terminal" GOAL_RESULT.md',
    )

    ok, log = pipeline._apply_and_test(output, str(tmp_path))

    assert ok, log
    assert "Simplicio Sprint CLI E2E - terminal" in target.read_text(encoding="utf-8")
    assert (tmp_path / ".simplicio" / "last_patch.diff").exists()


def test_apply_and_test_fails_closed_without_real_test_command(tmp_path, monkeypatch):
    target = tmp_path / "app.py"
    target.write_text("old\n", encoding="utf-8")
    monkeypatch.delenv("SIMPLICIO_TEST_CMD", raising=False)
    output = "\n".join(
        [
            "diff --git a/app.py b/app.py",
            "--- a/app.py",
            "+++ b/app.py",
            "@@ -1 +1 @@",
            "-old",
            "+new",
            "TEST: pytest -q",
        ]
    )

    ok, log = pipeline._apply_and_test(output, str(tmp_path))

    assert ok is False
    assert "verification command missing" in log
    assert target.read_text(encoding="utf-8") == "old\n"


def test_run_task_rejects_missing_test_command_before_application(tmp_path, monkeypatch):
    target = tmp_path / "app.py"
    target.write_text("old\n", encoding="utf-8")
    monkeypatch.delenv("SIMPLICIO_TEST_CMD", raising=False)
    monkeypatch.setattr(pipeline, "MAX_ATTEMPTS", 1)
    generated = []
    output = "\n".join(
        [
            "diff --git a/app.py b/app.py",
            "--- a/app.py",
            "+++ b/app.py",
            "@@ -1 +1 @@",
            "-old",
            "+new",
            "TEST: pytest -q",
        ]
    )
    monkeypatch.setattr(
        pipeline,
        "generate",
        lambda *a, **k: generated.append(True) or output,
    )

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "change app",
        "app.py",
        "- behavior proven",
        "- keep compatibility",
        quiet=True,
    )

    assert result["applied"] is False
    assert generated == [True]
    assert target.read_text(encoding="utf-8") == "old\n"
    assert "verification command missing" in result["warnings"][0]


def test_external_test_command_satisfies_generated_test_contract(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")

    result = pipeline.validate_generated_output(
        "\n".join(
            [
                "diff --git a/app.py b/app.py",
                "--- a/app.py",
                "+++ b/app.py",
                "@@ -1 +1 @@",
                "-old",
                "+new",
                "",
            ]
        )
    )

    assert result.ok is True


def test_apply_and_test_recovers_bad_hunk_counts_with_recount(tmp_path, monkeypatch):
    target = tmp_path / "docs" / "result.md"
    target.parent.mkdir()
    output = "\n".join(
        [
            "```diff",
            "diff --git a/docs/result.md b/docs/result.md",
            "new file mode 100644",
            "--- /dev/null",
            "+++ b/docs/result.md",
            "@@ -0,0 +1,99 @@",
            "+Simplicio Sprint CLI E2E - terminal",
            "```",
        ]
    )
    monkeypatch.setenv(
        "SIMPLICIO_TEST_CMD",
        'grep -q "Simplicio Sprint CLI E2E - terminal" docs/result.md',
    )

    ok, log = pipeline._apply_and_test(output, str(tmp_path))

    assert ok, log
    assert "Simplicio Sprint CLI E2E - terminal" in target.read_text(encoding="utf-8")


def test_apply_and_test_keeps_worktree_byte_for_byte_when_verification_fails(tmp_path, monkeypatch):
    target = tmp_path / "app.py"
    untouched = tmp_path / "README.md"
    target.write_text("old\n", encoding="utf-8")
    untouched.write_text("keep me\n", encoding="utf-8")
    output = "\n".join(
        [
            "diff --git a/app.py b/app.py",
            "--- a/app.py",
            "+++ b/app.py",
            "@@ -1 +1 @@",
            "-old",
            "+new",
            "",
            "TEST: pytest -q",
        ]
    )
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "python -c \"import sys; sys.exit(1)\"")

    ok, log = pipeline._apply_and_test(output, str(tmp_path))

    assert ok is False
    assert target.read_text(encoding="utf-8") == "old\n"
    assert untouched.read_text(encoding="utf-8") == "keep me\n"
    assert ".simplicio" not in log


def test_external_test_command_allows_textual_placeholder_mentions(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "grep -q marker docs/result.md")

    result = pipeline.validate_generated_output(
        "\n".join(
            [
                "diff --git a/docs/result.md b/docs/result.md",
                "--- /dev/null",
                "+++ b/docs/result.md",
                "@@ -0,0 +1,2 @@",
                "+marker",
                "+placeholder text mentioned in documentation",
                "",
            ]
        )
    )

    assert result.ok is True


def _valid_pipeline_diff():
    return "\n".join(
        [
            "diff --git a/src/app.py b/src/app.py",
            "--- a/src/app.py",
            "+++ b/src/app.py",
            "@@ -0,0 +1 @@",
            "+print('ok')",
            "",
            "TEST: pytest -q",
        ]
    )


def test_pipeline_static_fixer_skips_llm_retry_when_verify_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DISABLE_RUN_LOG", "1")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    generate_calls = []
    apply_calls = {"count": 0}

    def fake_generate(prompt, feedback=None):
        generate_calls.append(feedback)
        return _valid_pipeline_diff()

    def fake_apply_and_test(output, root, bound_paths=None):
        apply_calls["count"] += 1
        if apply_calls["count"] == 1:
            return False, "ModuleNotFoundError: No module named 'fastapi'"
        return True, "1 passed"

    monkeypatch.setattr(pipeline, "generate", fake_generate)
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(pipeline, "_apply_and_test", fake_apply_and_test)
    monkeypatch.setattr(
        pipeline,
        "_run_impact_tests",
        lambda *a, **k: {
            "status": "no_callers_found",
            "callers": [],
            "tests_run": [],
            "result": pipeline.IMPACT_RESULT_NOT_NEEDED,
        },
    )
    monkeypatch.setattr(
        pipeline,
        "try_static_fixers",
        lambda log, root: FixerResult("missing-pip-package", True, "installed fastapi"),
    )

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "add api",
        "src/app.py",
        "- passes",
        "- small",
        quiet=True,
    )

    assert result["applied"] is True
    assert len(generate_calls) == 1
    assert apply_calls["count"] == 2


def test_pipeline_retries_with_llm_when_static_fixer_does_not_resolve(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DISABLE_RUN_LOG", "1")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    generate_calls = []
    apply_calls = {"count": 0}

    def fake_generate(prompt, feedback=None):
        generate_calls.append(feedback)
        return _valid_pipeline_diff()

    def fake_apply_and_test(output, root, bound_paths=None):
        apply_calls["count"] += 1
        if apply_calls["count"] == 1:
            return False, "ModuleNotFoundError: No module named 'fastapi'"
        if apply_calls["count"] == 2:
            return False, "AssertionError: still failing after fixer"
        return True, "1 passed"

    def fake_fixers(log, root):
        if "No module named" in log:
            return FixerResult("missing-pip-package", True, "installed fastapi")
        return FixerResult("none", False, "no static fixer matched")

    monkeypatch.setattr(pipeline, "generate", fake_generate)
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(pipeline, "_apply_and_test", fake_apply_and_test)
    monkeypatch.setattr(
        pipeline,
        "_run_impact_tests",
        lambda *a, **k: {
            "status": "no_callers_found",
            "callers": [],
            "tests_run": [],
            "result": pipeline.IMPACT_RESULT_NOT_NEEDED,
        },
    )
    monkeypatch.setattr(pipeline, "try_static_fixers", fake_fixers)

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "add api",
        "src/app.py",
        "- passes",
        "- small",
        quiet=True,
    )

    assert result["applied"] is True
    assert len(generate_calls) == 2
    assert generate_calls[1] is not None


def test_static_fixers_reduce_retry_calls_in_synthetic_pipeline_case(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DISABLE_RUN_LOG", "1")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")

    def run_case(root, fixer_enabled):
        generate_calls = []
        apply_calls = {"count": 0}

        def fake_generate(prompt, feedback=None):
            generate_calls.append(feedback)
            return _valid_pipeline_diff()

        def fake_apply_and_test(output, run_root, bound_paths=None):
            apply_calls["count"] += 1
            if apply_calls["count"] == 1:
                return False, "ModuleNotFoundError: No module named 'fastapi'"
            return True, "1 passed"

        def fake_fixers(log, run_root):
            if fixer_enabled:
                return FixerResult("missing-pip-package", True, "installed fastapi")
            return FixerResult("none", False, "disabled for synthetic baseline")

        monkeypatch.setattr(pipeline, "generate", fake_generate)
        monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")
        monkeypatch.setattr(pipeline, "_apply_and_test", fake_apply_and_test)
        monkeypatch.setattr(
            pipeline,
            "_run_impact_tests",
            lambda *a, **k: {
                "status": "no_callers_found",
                "callers": [],
                "tests_run": [],
                "result": pipeline.IMPACT_RESULT_NOT_NEEDED,
            },
        )
        monkeypatch.setattr(pipeline, "try_static_fixers", fake_fixers)
        pipeline.run_task(
            str(root),
            "python",
            "add api",
            "src/app.py",
            "- passes",
            "- small",
            quiet=True,
        )
        return len(generate_calls)

    baseline_calls = run_case(tmp_path / "baseline", fixer_enabled=False)
    fixer_calls = run_case(tmp_path / "fixer", fixer_enabled=True)

    assert baseline_calls == 2
    assert fixer_calls == 1
    assert (baseline_calls - fixer_calls) / baseline_calls >= 0.3


def test_benchmark_writes_observability_log(tmp_path, monkeypatch):
    cases = [
        {
            "goal": "avoid hallucinated files",
            "target": "src/app.py",
            "criteria": "- output captured",
            "constraints": "- no hallucinated paths",
            "test_cmd": "test -f .simplicio/bench_out.txt",
        }
    ]
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    monkeypatch.setattr(
        bench,
        "generate",
        lambda prompt, *args, **kwargs: "diff --git a/src/app.py b/src/app.py",
    )
    monkeypatch.setattr(bench, "build_prompt", lambda *args, **kwargs: "structured prompt")
    monkeypatch.setenv("SIMPLICIO_PROMPT_VARIANT", "mapper-v1")

    bench.run_bench(str(tmp_path), "python", str(cases_path))

    run_log = tmp_path / ".simplicio" / "runs.jsonl"
    assert run_log.exists()
    events = [json.loads(line) for line in run_log.read_text(encoding="utf-8").splitlines()]
    assert {event["mode"] for event in events} == {"baseline", "pipeline"}
    assert all(event["prompt_variant"] == "mapper-v1" for event in events)
    assert all("tokens_estimated" in event for event in events)
