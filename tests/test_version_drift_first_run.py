"""Issue #1812, observation 1: a running simplicio-loop older than its checkout is reported.

`preflight` and `doctor` compare the running version with the source checkout's version and
its latest `v*` tag. When the running version is older, they print one line with both versions
and the exact fix command. A current install prints nothing extra.
"""
from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from simplicio_loop import cli_impl, doctor_overview, version_drift


def _checkout(root: Path, *, version: str, tag: str | None) -> Path:
    """A real git checkout of simplicio-loop: pyproject name/version plus an optional tag."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "simplicio-loop"\nversion = "%s"\n' % version, encoding="utf-8")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin"}
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True, env=env)
    if tag:
        subprocess.run(["git", "tag", tag], cwd=root, check=True, env=env)
    return root


def test_installed_older_than_checkout_gives_one_line_with_both_versions_and_fix(tmp_path):
    checkout = _checkout(tmp_path / "simplicio-loop", version="3.50.0", tag="v3.50.0")

    report = version_drift.check("3.49.0", environ={"SIMPLICIO_LOOP_SOURCE": str(checkout)})

    assert report is not None and report["behind"] is True
    line = version_drift.format_line(report)
    assert line is not None
    assert "\n" not in line
    assert "3.49.0" in line and "3.50.0" in line
    assert "pip install --upgrade" in line
    assert shlex.quote(str(checkout)) in line or str(checkout) in line


def test_latest_tag_newer_than_checkout_version_counts_as_drift(tmp_path):
    checkout = _checkout(tmp_path / "simplicio-loop", version="3.50.0", tag="v3.51.0")

    report = version_drift.check("3.50.0", environ={"SIMPLICIO_LOOP_SOURCE": str(checkout)})

    assert report is not None and report["behind"] is True
    assert report["tag"] == "v3.51.0"
    assert "3.51.0" in version_drift.format_line(report)


def test_current_install_prints_nothing(tmp_path):
    checkout = _checkout(tmp_path / "simplicio-loop", version="3.50.0", tag="v3.50.0")

    report = version_drift.check("3.50.0", environ={"SIMPLICIO_LOOP_SOURCE": str(checkout)})

    assert report is not None and report["behind"] is False
    assert version_drift.format_line(report) is None


def test_no_simplicio_loop_checkout_means_no_comparison(tmp_path, monkeypatch):
    other = tmp_path / "some-project"
    other.mkdir()
    (other / "pyproject.toml").write_text('[project]\nname = "other"\nversion = "1.0.0"\n', encoding="utf-8")
    monkeypatch.setattr(version_drift, "_installed_source_dir", lambda: None)

    assert version_drift.check("3.49.0", repo=str(other), environ={}) is None


def test_preflight_prints_the_drift_line_for_a_stale_install(tmp_path, monkeypatch, capsys):
    checkout = _checkout(tmp_path / "simplicio-loop", version="3.50.0", tag="v3.50.0")
    monkeypatch.setenv("SIMPLICIO_LOOP_SOURCE", str(checkout))
    monkeypatch.setattr(version_drift, "running_version", lambda: "3.49.0")

    cli_impl.preflight(str(tmp_path), False)
    out = capsys.readouterr().out

    drift = [line for line in out.splitlines() if line.startswith("version drift:")]
    assert len(drift) == 1
    assert "3.49.0" in drift[0] and "3.50.0" in drift[0] and "pip install --upgrade" in drift[0]


def test_preflight_json_carries_the_version_report_only_when_a_checkout_is_known(tmp_path, monkeypatch, capsys):
    checkout = _checkout(tmp_path / "simplicio-loop", version="3.50.0", tag="v3.50.0")
    monkeypatch.setenv("SIMPLICIO_LOOP_SOURCE", str(checkout))
    monkeypatch.setattr(version_drift, "running_version", lambda: "3.49.0")

    cli_impl.preflight(str(tmp_path), True)
    payload = json.loads(capsys.readouterr().out)

    assert payload["version_drift"]["behind"] is True
    assert payload["version_drift"]["installed"] == "3.49.0"
    assert payload["version_drift"]["source"] == "3.50.0"


def test_doctor_distribution_row_warns_when_the_install_is_older(tmp_path):
    # The checkout is passed through `environ`, the mapping doctor reads. The host's own environment, its
    # installed metadata (direct_url.json, or a stray simplicio_loop.egg-info on sys.path) never decides it.
    checkout = _checkout(tmp_path / "simplicio-loop", version="3.50.0", tag="v3.50.0")

    result = doctor_overview.collect(
        installed="3.49.0", kind="pip", only="distribution", repo=str(tmp_path),
        environ={"SIMPLICIO_LOOP_SOURCE": str(checkout)}, state_dir=tmp_path / "state")

    row = result["checks"][0]
    assert row["name"] == "distribution"
    assert row["status"] == "warn"
    assert "3.49.0" in row["summary"] and "3.50.0" in row["summary"]
    assert "pip install --upgrade" in row["fix"]


def test_drift_check_is_silent_without_any_source(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_LOOP_SOURCE", raising=False)
    monkeypatch.setattr(version_drift, "_installed_source_dir", lambda: None)
    assert version_drift.check("3.49.0", repo=str(tmp_path), environ={}) is None


def test_the_opt_out_turns_the_comparison_off_even_with_a_checkout(tmp_path):
    checkout = _checkout(tmp_path / "simplicio-loop", version="3.50.0", tag="v3.50.0")
    assert version_drift.check("3.49.0", environ={"SIMPLICIO_LOOP_SOURCE": "off"}) is None
    assert version_drift.check("3.49.0", environ={"SIMPLICIO_LOOP_SOURCE": str(checkout)}) is not None


def test_the_latest_tag_is_read_from_packed_refs_and_loose_refs(tmp_path):
    checkout = _checkout(tmp_path / "simplicio-loop", version="3.50.0", tag="v3.50.0")
    git_dir = checkout / ".git"
    (git_dir / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        "1111111111111111111111111111111111111111 refs/tags/v3.9.0\n"
        "2222222222222222222222222222222222222222 refs/tags/v3.52.1\n"
        "3333333333333333333333333333333333333333 refs/tags/release-x\n",
        encoding="utf-8")
    (git_dir / "refs" / "tags" / "v3.53.0").write_text("4444444444444444444444444444444444444444\n", encoding="utf-8")
    assert version_drift.latest_tag(checkout) == "v3.53.0"
