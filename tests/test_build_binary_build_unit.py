"""build() of scripts/build_binary.py with a fake subprocess.run (issue #1576, review of PR #1581).

The executable must hold the wheel of THIS tree. The build proves it by construction: it exports the sources
of the tree, builds a wheel from that export, installs exactly that wheel in a new venv, and runs PyInstaller from
that venv. These tests pin the order, the inputs and the refusals. The real build is covered by
scripts/smoke_binary.py.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_binary as bb  # noqa: E402

VERSION = bb.project_version(ROOT)
ASSET = bb.binary_name(VERSION, "linux", "x86_64")
EPOCH = "1700000000"


class Pipeline:
    """A fake subprocess.run. It writes what each real command would write."""

    def __init__(self, version_output=None, fail_on=None):
        self.calls = []
        self.version_output = f"simplicio-loop {VERSION}\n" if version_output is None else version_output
        self.fail_on = fail_on

    def kind(self, command):
        text = [str(part) for part in command]
        if any(part.endswith("pyinstaller_run.py") for part in text):
            return "pyinstaller"  # first: its --exclude-module list has the word "wheel"
        if "venv" in text:
            return "venv"
        if text[3:5] == ["pip", "wheel"] or "wheel" in text[1:4]:
            return "wheel"
        if "install" in text:
            return "install"
        return "version"

    def __call__(self, command, **kwargs):
        kind = self.kind(command)
        self.calls.append((kind, [str(part) for part in command], kwargs))
        if kind == self.fail_on:
            return subprocess.CompletedProcess(command, 3, "", f"{kind} exploded")
        if kind == "wheel":
            wheel_dir = Path(command[command.index("-w") + 1])
            wheel_dir.mkdir(parents=True, exist_ok=True)
            (wheel_dir / f"simplicio_loop-{VERSION}-py3-none-any.whl").write_bytes(b"wheel")
        if kind == "pyinstaller":
            dist = Path(command[command.index("--distpath") + 1])
            if "--onedir" in command:
                (dist / "simplicio-loop" / "_internal").mkdir(parents=True)
                (dist / "simplicio-loop" / "simplicio-loop").write_bytes(b"launcher")
            else:
                dist.mkdir(parents=True, exist_ok=True)
                (dist / "simplicio-loop").write_bytes(b"fake executable")
        if kind == "version":
            return subprocess.CompletedProcess(command, 0, self.version_output, "")
        return subprocess.CompletedProcess(command, 0, "", "")

    def kinds(self):
        return [kind for kind, _, _ in self.calls]


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    monkeypatch.setattr(bb, "detect_os", lambda *a: "linux")
    monkeypatch.setattr(bb, "detect_arch", lambda *a: "x86_64")
    events = []

    def export_source(root, dest):
        events.append(("export", dest))
        dest.mkdir(parents=True)
        (dest / "pyproject.toml").write_text("[project]\n")
        return "HEAD abc123"

    monkeypatch.setattr(bb, "export_source", export_source)
    def release_source(root, dest):
        events.append(("release", dest))
        shutil.rmtree(dest, ignore_errors=True)

    monkeypatch.setattr(bb, "release_source", release_source)
    monkeypatch.setattr(bb, "check_clean_tree", lambda root, allow_dirty: events.append(("clean", allow_dirty)))
    pipeline = Pipeline()
    out, work = tmp_path / "out", tmp_path / "work"

    def run(**overrides):
        values = dict(tool="pyinstaller", mode="onefile", version=None, out=str(out), work=str(work),
                      python="/base/python", allow_dirty=False, dry_run=False)
        values.update(overrides)
        return bb.build(argparse.Namespace(**values), run=pipeline)

    return argparse.Namespace(run=run, pipeline=pipeline, out=out, work=work, events=events, tmp=tmp_path)


def test_the_build_runs_venv_wheel_install_and_pyinstaller_in_that_order(harness):
    summary = harness.run()
    assert harness.pipeline.kinds() == ["venv", "wheel", "install", "pyinstaller", "version"]
    assert summary["asset"] == ASSET and summary["source"] == "HEAD abc123"


def test_the_wheel_is_built_from_the_exported_sources_and_installed_exactly(harness):
    harness.run()
    calls = {kind: command for kind, command, _ in harness.pipeline.calls}
    export = next(dest for event, dest in harness.events if event == "export")
    venv_python = str(harness.work / "venv" / "bin" / "python")
    assert calls["venv"][:3] == ["/base/python", "-m", "venv"]
    assert calls["wheel"][0] == venv_python and calls["wheel"][-1] == str(export)  # not the working tree
    assert "--no-deps" in calls["wheel"]
    wheel = harness.work / "wheel" / f"simplicio_loop-{VERSION}-py3-none-any.whl"
    assert str(wheel) in calls["install"]  # that file, not "simplicio-loop" from an index
    assert f"pyinstaller=={bb.PYINSTALLER_VERSION}" in calls["install"]
    assert calls["pyinstaller"][0] == venv_python  # PyInstaller runs from the venv that holds the wheel
    assert not any(str(ROOT) in part for part in calls["install"])


def test_every_command_runs_in_the_work_directory_with_the_deterministic_environment(harness, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/leak")
    harness.run()
    for kind, _, kwargs in harness.pipeline.calls:
        env = kwargs["env"]
        assert env["SOURCE_DATE_EPOCH"] == EPOCH and env["PYTHONHASHSEED"] == "0" and env["TZ"] == "UTC", kind
        assert "PYTHONPATH" not in env, kind
        assert Path(kwargs["cwd"]) == harness.work, kind


def test_the_asset_is_executable_listed_in_sha256sums_and_no_partial_file_stays(harness):
    summary = harness.run()
    asset = harness.out / ASSET
    assert asset.read_bytes() == b"fake executable"
    assert stat.S_IMODE(asset.stat().st_mode) & 0o111 == 0o111  # a plain move would leave 0644
    sums = bb.parse_sha256sums((harness.out / "SHA256SUMS").read_text())
    assert sums == {ASSET: bb.sha256_file(asset)} and summary["sha256"] == sums[ASSET]
    assert sorted(item.name for item in harness.out.iterdir()) == ["SHA256SUMS", ASSET]


def test_the_sources_are_released_even_when_a_command_fails(harness):
    harness.pipeline.fail_on = "install"
    with pytest.raises(bb.BuildError):
        harness.run()
    exports_and_releases = [event for event, _ in harness.events if event in ("export", "release")]
    assert exports_and_releases[-2:] == ["export", "release"]  # the last export is always released


@pytest.mark.parametrize("failing", ["venv", "wheel", "install", "pyinstaller"])
def test_a_failing_command_stops_the_build_names_it_and_publishes_nothing(harness, failing):
    harness.pipeline.fail_on = failing
    with pytest.raises(bb.BuildError, match=f"{failing} exploded"):
        harness.run()
    assert not harness.out.exists() or list(harness.out.iterdir()) == []
    assert failing == harness.pipeline.kinds()[-1]  # nothing ran after the failure


@pytest.mark.parametrize("output", ["simplicio-loop 0.0.1\n", "", "boom"])
def test_an_executable_that_prints_another_version_is_not_published(harness, output):
    harness.pipeline.version_output = output
    with pytest.raises(bb.BuildError, match="--version"):
        harness.run()
    assert not (harness.out / ASSET).exists() and not (harness.out / "SHA256SUMS").exists()


def test_a_version_that_is_not_the_tree_version_is_refused_before_any_command(harness):
    with pytest.raises(bb.BuildError, match="9.9.9"):
        harness.run(version="9.9.9")
    assert harness.pipeline.calls == []


def test_the_matching_version_is_accepted(harness):
    assert harness.run(version=VERSION)["asset"] == ASSET


def test_the_dirty_tree_check_runs_with_the_flag(harness):
    harness.run(allow_dirty=True)
    assert ("clean", True) in harness.events


def test_a_dirty_tree_stops_the_build_before_any_command(harness, monkeypatch):
    def refuse(root, allow_dirty):
        raise bb.BuildError("the working tree is dirty")
    monkeypatch.setattr(bb, "check_clean_tree", refuse)
    with pytest.raises(bb.BuildError, match="dirty"):
        harness.run()
    assert harness.pipeline.calls == []


def test_dry_run_plans_the_commands_and_runs_none(harness):
    plan = harness.run(dry_run=True)
    assert harness.pipeline.calls == []
    assert plan["asset"] == ASSET and [c[0] for c in plan["commands"]] == [
        "/base/python", str(harness.work / "venv" / "bin" / "python"), str(harness.work / "venv" / "bin" / "python"),
        str(harness.work / "venv" / "bin" / "python")]


def test_only_the_directories_of_the_build_are_replaced_in_the_work_directory(harness):
    (harness.work / "venv" / "stale").mkdir(parents=True)
    (harness.work / bb.WORK_MARK).write_text("made by an earlier build")
    (harness.work / "wheel").mkdir()
    (harness.work / "wheel" / "old-1.0-py3-none-any.whl").write_bytes(b"old")
    (harness.work / "keep.txt").write_text("not ours")
    harness.run()
    assert (harness.work / "keep.txt").read_text() == "not ours"
    assert not (harness.work / "wheel" / "old-1.0-py3-none-any.whl").exists()  # a stale wheel cannot be installed
    assert not (harness.work / "venv" / "stale").exists()


def test_onedir_moves_the_directory_and_writes_no_checksums(harness):
    summary = harness.run(mode="onedir")
    assert (harness.out / (ASSET + ".onedir") / "_internal").is_dir()
    assert not (harness.out / "SHA256SUMS").exists() and summary["asset"].endswith(".onedir")


def test_a_pre_existing_asset_is_replaced(harness):
    harness.out.mkdir()
    (harness.out / ASSET).write_bytes(b"old")
    harness.run()
    assert (harness.out / ASSET).read_bytes() == b"fake executable"


def test_a_work_directory_with_other_content_is_refused_and_nothing_is_removed(harness):
    """`--work .` in a project must never remove the venv, src, wheel or dist directories of the project."""
    for name in ("venv", "src", "wheel", "dist"):
        (harness.work / name).mkdir(parents=True)
        (harness.work / name / "mine.txt").write_text("project file")
    with pytest.raises(bb.BuildError, match="not a build directory"):
        harness.run()
    assert harness.pipeline.calls == []
    assert sorted(item.name for item in harness.work.iterdir()) == ["dist", "src", "venv", "wheel"]
    assert (harness.work / "venv" / "mine.txt").read_text() == "project file"


def test_a_build_directory_of_an_earlier_build_is_reused(harness):
    harness.run()
    harness.pipeline.calls.clear()
    harness.run()  # the marker file says that the build made this directory
    assert harness.pipeline.kinds() == ["venv", "wheel", "install", "pyinstaller", "version"]


# --- the sources, SOURCE_DATE_EPOCH --------------------------------------------------------------

def _git_repo(path):
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": os.environ["PATH"], "HOME": str(path)}
    def git(*args):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, stdin=subprocess.DEVNULL, env=env)
    git("init", "-q")
    (path / "a.py").write_text("one")
    (path / "sub").mkdir()
    (path / "sub" / "b.py").write_text("two")
    git("add", ".")
    git("commit", "-qm", "init")
    return git


def test_export_source_of_a_git_tree_is_head_without_local_changes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_repo(repo)
    (repo / "a.py").write_text("changed, not committed")
    (repo / "new.py").write_text("untracked")
    (repo / "build").mkdir()
    (repo / "build" / "lib.py").write_text("stale build output")
    dest = tmp_path / "work" / "src"
    (tmp_path / "work").mkdir()

    origin = bb.export_source(repo, dest)

    assert origin.startswith("HEAD ")
    assert (dest / "a.py").read_text() == "one" and (dest / "sub" / "b.py").read_text() == "two"
    assert not (dest / "new.py").exists() and not (dest / "build").exists()
    assert bb._git(dest, "rev-parse", "HEAD").strip() == origin.split()[1]  # the stamp of the mapper can read it
    bb.release_source(repo, dest)
    assert not dest.exists() and "worktrees" not in bb._git(repo, "worktree", "list")


def test_export_source_of_a_tree_without_git_copies_it_without_build_output(tmp_path):
    tree = tmp_path / "tree"
    for name in ("pkg/a.py", "build/x.py", "dist/y.whl", "pkg/__pycache__/a.pyc", "pkg.egg-info/PKG-INFO"):
        (tree / name).parent.mkdir(parents=True, exist_ok=True)
        (tree / name).write_text("x")
    dest = tmp_path / "out" / "src"
    (tmp_path / "out").mkdir()

    assert bb.export_source(tree, dest) == "copy"

    assert sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()) == ["pkg/a.py"]
    bb.release_source(tree, dest)
    assert not dest.exists()


def test_source_date_epoch_from_the_environment_must_be_a_number(monkeypatch, tmp_path):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "yesterday")
    with pytest.raises(bb.BuildError, match="not a number"):
        bb.source_date_epoch(tmp_path)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000001")
    assert bb.source_date_epoch(tmp_path) == 1700000001
