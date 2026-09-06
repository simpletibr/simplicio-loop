"""Tests for `simplicio-cli versions` and its wiring into `doctor` (issue #232).

Covers: the JSON/human dual output of `commands/versions.py`, the CLI
dispatch (`simplicio.cli main(["versions", ...])`), the `doctor --json`
`mapper_versions` section, and the "must not interrupt an active task"
requirement — verified by actually running `pipeline.run_task` concurrently
with a `versions --json` query and asserting neither interferes with the
other.
"""

from __future__ import annotations

import io
import json
import threading
import time
from contextlib import redirect_stdout

from simplicio import pipeline
from simplicio.commands import versions as versions_cmd


def test_versions_report_shape(monkeypatch, tmp_path_factory):
    # root=None auto-detects this repo checkout, exercising the actual
    # pyproject.toml/uv.lock/git state, same as `test_component_manifest.py`.
    # Pin latest_known so the shape test is offline-stable.
    monkeypatch.setattr(versions_cmd, "_latest_mapper_version", lambda *, refresh=False: ("0.26.28", None))
    payload = versions_cmd.versions_report(None)
    assert payload["schema"] == "simplicio.dev-cli.versions/v1"
    mapper = payload["mapper"]
    assert mapper["installed"]
    assert mapper["declared_range"] == ">=0.26.28,<0.27"
    assert mapper["required"] == ">=0.26.28,<0.27"
    assert mapper["latest_known"] == "0.26.28"
    assert mapper["unavailable_reason"] is None
    assert payload["drift"]["kind"] in {None, "stale_vs_tested", "out_of_range", "not_installed"}
    assert payload["own_manifest"]["name"] == "simplicio-cli"


def test_versions_report_latest_null_when_registry_unreachable(monkeypatch):
    monkeypatch.setattr(
        versions_cmd, "_latest_mapper_version", lambda *, refresh=False: (None, "registry_unreachable")
    )
    payload = versions_cmd.versions_report(None)
    assert payload["mapper"]["latest_known"] is None
    assert payload["mapper"]["unavailable_reason"] == "registry_unreachable"


def test_versions_command_json_output(capsys, monkeypatch):
    import argparse

    monkeypatch.setattr(versions_cmd, "_latest_mapper_version", lambda *, refresh=False: ("0.26.28", None))
    ns = argparse.Namespace(root=".", json=True, refresh=False)
    rc = versions_cmd.run(ns)
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["schema"] == "simplicio.dev-cli.versions/v1"
    assert payload["mapper"]["required"] == ">=0.26.28,<0.27"
    assert payload["mapper"]["tested_against"] == "0.26.28"
    assert payload["mapper"]["latest_known"] == "0.26.28"


def test_versions_command_human_output(capsys, monkeypatch):
    import argparse

    monkeypatch.setattr(versions_cmd, "_latest_mapper_version", lambda *, refresh=False: ("0.26.28", None))
    ns = argparse.Namespace(root=".", json=False, refresh=False)
    rc = versions_cmd.run(ns)
    assert rc == 0
    out = capsys.readouterr().out
    assert "simplicio-py versions" in out
    assert "own component manifest" in out
    assert "0.26.28" in out


def test_release_train_mapper_stub_matches_declared_floor():
    """config/release-train-mapper.json must stay aligned with pyproject + lock."""
    from pathlib import Path

    import tomllib

    root = Path(__file__).resolve().parents[2]
    stub = json.loads((root / "config" / "release-train-mapper.json").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]
    mapper_req = next(d for d in deps if d.startswith("simplicio-mapper"))
    assert stub["schema"] == "simplicio.release-train/v1"
    assert stub["dependency"]["declared_range"] in mapper_req
    assert stub["dependency"]["tested_against"] == "0.26.28"
    version, reason = __import__(
        "simplicio.component_manifest", fromlist=["tested_dependency_version"]
    ).tested_dependency_version("simplicio-mapper", root)
    assert version == stub["dependency"]["tested_against"]
    assert reason == "locked_in_uv.lock"


def test_cli_dispatches_versions_subcommand(capsys):
    from simplicio import cli

    rc = cli.main(["versions", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["schema"] == "simplicio.dev-cli.versions/v1"


def test_doctor_json_includes_mapper_versions_section(monkeypatch, tmp_path, capsys):
    from simplicio import doctor

    rc = doctor.main(["--json", "--no-check-updates", "--root", str(tmp_path)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "mapper_versions" in payload
    assert payload["mapper_versions"]["schema"] == "simplicio.dev-cli.versions/v1"
    assert payload["mapper_versions"]["mapper"]["declared_range"] == ">=0.26.28,<0.27"
    assert payload["mapper_versions"]["mapper"]["required"] == ">=0.26.28,<0.27"


# --------------------------------------------------------------------------- #
# Issue #232 item 13: drift detection must never interrupt an active task.
# --------------------------------------------------------------------------- #


def test_versions_report_does_not_interfere_with_active_task(monkeypatch, tmp_path):
    """Start a slow `pipeline.run_task` in a background thread, then query
    `versions --json` (and the raw `detect_drift` it's built on) while that
    task is still mid-flight. Both must complete normally: the concurrent
    read never raises, never blocks waiting on anything the task holds, and
    the task itself finishes with its expected result instead of being
    cancelled/corrupted by the concurrent read."""
    monkeypatch.setattr(pipeline, "build_prompt", lambda *a, **k: "BASE PROMPT")
    monkeypatch.setattr(pipeline, "log_run", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_dry_run_preconditions", lambda *a, **k: [])

    target = tmp_path / "app.py"
    target.write_text("original content\n", encoding="utf-8")

    generate_started = threading.Event()
    release_generate = threading.Event()

    def slow_generate(prompt, feedback=None):
        generate_started.set()
        # Hold the "task in flight" window open long enough for the
        # concurrent versions_report()/detect_drift() calls below to run.
        release_generate.wait(timeout=5)
        return "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"

    monkeypatch.setattr(pipeline, "generate", slow_generate)

    task_result: dict = {}

    def run_it():
        task_result["value"] = pipeline.run_task(
            str(tmp_path),
            "python",
            "fix bug",
            "app.py",
            "",
            "",
            dry_run_task=True,
            mode="standalone",
            bound_paths=["app.py"],
            quiet=True,
        )

    task_thread = threading.Thread(target=run_it)
    task_thread.start()
    assert generate_started.wait(timeout=5), "task never reached generate()"

    # The task is now genuinely mid-flight (blocked inside generate()).
    # Concurrently query versions/drift — this must not raise, hang, or
    # touch anything the task thread is using.
    concurrent_errors: list[BaseException] = []
    concurrent_payloads: list[dict] = []

    def query_versions():
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                payload = versions_cmd.versions_report(".")
            concurrent_payloads.append(payload)
        except BaseException as exc:  # noqa: BLE001 - want to see any real failure
            concurrent_errors.append(exc)

    query_thread = threading.Thread(target=query_versions)
    start = time.monotonic()
    query_thread.start()
    query_thread.join(timeout=5)
    elapsed = time.monotonic() - start

    assert not query_thread.is_alive(), "versions_report() hung while a task was mid-flight"
    assert elapsed < 5, "versions_report() should return quickly, not wait on the running task"
    assert concurrent_errors == []
    assert concurrent_payloads and concurrent_payloads[0]["schema"] == "simplicio.dev-cli.versions/v1"

    # Let the task finish and confirm it completed normally, undisturbed by
    # the concurrent read.
    release_generate.set()
    task_thread.join(timeout=5)
    assert not task_thread.is_alive()
    assert task_result["value"]["status"] == "dry_run"
    assert task_result["value"]["task_id"] == "app.py"
