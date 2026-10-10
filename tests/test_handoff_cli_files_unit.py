"""`simplicio-loop handoff write|read`: where the file goes, who can read it, what it holds (#1608, part B)."""
from __future__ import annotations

import io
import json
import os
import stat
from pathlib import Path

import pytest

from simplicio_loop import cli_impl

FIXTURES = Path(__file__).resolve().parent.parent / "contracts" / "agent-handoff" / "v1" / "fixtures"
KEY = "sk-" + "A1b2C3d4" * 4
POSIX = pytest.mark.skipif(os.name != "posix", reason="file modes and symlinks are checked on POSIX")


def doc(**changes):
    d = json.loads((FIXTURES / "valid-measured.json").read_text(encoding="utf-8"))
    d.update(changes)
    return d


def run(capsys, *argv, stdin=None, monkeypatch=None):
    if stdin is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    code = cli_impl.main(["handoff", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def write(capsys, monkeypatch, repo, d):
    return run(capsys, "write", "--repo", str(repo), stdin=json.dumps(d), monkeypatch=monkeypatch)


def target(repo, run_id="run-20261009T161000Z", n=2):
    return repo / ".simplicio-loop" / "orchestrator" / "handoff" / run_id / ("%d.json" % n)


def reason(err):
    return json.loads(err)["reason_code"]


# --- write ---------------------------------------------------------------------------------------------------------------

def test_write_puts_the_document_where_the_contract_says(tmp_path, capsys, monkeypatch):
    code, out, err = write(capsys, monkeypatch, tmp_path, doc())
    assert code == 0 and err == ""
    path = target(tmp_path)
    assert json.loads(path.read_text(encoding="utf-8")) == doc()
    result = json.loads(out)
    assert result["path"] == ".simplicio-loop/orchestrator/handoff/run-20261009T161000Z/2.json"
    assert result["continuation"] == 2 and result["redacted"] == []


def test_write_reads_the_document_from_a_file_too(tmp_path, capsys):
    src = tmp_path / "in.json"
    src.write_text(json.dumps(doc()), encoding="utf-8")
    code, _, _ = run(capsys, "write", "--repo", str(tmp_path), "--file", str(src))
    assert code == 0 and target(tmp_path).is_file()


def test_write_never_touches_dot_simplicio(tmp_path, capsys, monkeypatch):
    write(capsys, monkeypatch, tmp_path, doc())
    assert sorted(p.name for p in tmp_path.iterdir()) == [".simplicio-loop"]
    assert not (tmp_path / ".simplicio").exists()


@POSIX
def test_write_makes_a_private_file_and_private_directories(tmp_path, capsys, monkeypatch):
    write(capsys, monkeypatch, tmp_path, doc())
    path = target(tmp_path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    for directory in (path.parent, path.parent.parent, path.parent.parent.parent, tmp_path / ".simplicio-loop"):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700, directory


@POSIX
def test_write_keeps_a_private_mode_whatever_the_umask(tmp_path, capsys, monkeypatch):
    old = os.umask(0)
    try:
        write(capsys, monkeypatch, tmp_path, doc())
    finally:
        os.umask(old)
    assert stat.S_IMODE(target(tmp_path).stat().st_mode) == 0o600
    for directory in (target(tmp_path).parent, tmp_path / ".simplicio-loop", tmp_path / ".simplicio-loop" / "orchestrator"):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700, directory


@POSIX
def test_write_tightens_an_existing_open_run_directory(tmp_path, capsys, monkeypatch):
    run_dir = target(tmp_path).parent
    run_dir.mkdir(parents=True, mode=0o755)
    run_dir.chmod(0o755)
    write(capsys, monkeypatch, tmp_path, doc())
    assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700


def test_write_redacts_the_free_text_before_it_touches_the_disk(tmp_path, capsys, monkeypatch):
    d = doc(objective="deploy with %s now" % KEY, next_steps=["ok", "mail bob@example.com"])
    code, out, _ = write(capsys, monkeypatch, tmp_path, d)
    assert code == 0
    raw = target(tmp_path).read_text(encoding="utf-8")
    assert KEY not in raw and "bob@example.com" not in raw
    assert json.loads(out)["redacted"] == ["/objective", "/next_steps/1"]
    assert KEY not in out


def test_write_stores_a_valid_handoff_after_redaction(tmp_path, capsys, monkeypatch):
    from simplicio_loop.agent_handoff import validate_handoff
    write(capsys, monkeypatch, tmp_path, doc(objective="use %s" % KEY))
    validate_handoff(json.loads(target(tmp_path).read_text(encoding="utf-8")))


def test_a_failure_message_never_echoes_a_secret(tmp_path, capsys, monkeypatch):
    d = doc(objective="use %s" % KEY)
    d["surprise"] = "extra field"
    code, out, err = write(capsys, monkeypatch, tmp_path, d)
    assert code == 2 and KEY not in err and KEY not in out


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d.update(schema="simplicio.agent-handoff/v2"), "handoff_schema_invalid"),
    (lambda d: d.update(surprise=1), "handoff_schema_invalid"),
    (lambda d: d["done"]["files"][0].update(path="../escape.py"), "handoff_path_invalid"),
    (lambda d: d["done"]["files"][0].update(path=".simplicio/x.py"), "handoff_path_invalid"),
    (lambda d: d["tokens"].update(prompt_tokens=1), "handoff_tokens_inconsistent"),
    (lambda d: d.update(run_id="../../etc"), "handoff_schema_invalid"),
    (lambda d: d.update(next_steps=["word " * 180] * 50), "handoff_too_large"),
])
def test_an_invalid_document_is_refused_and_nothing_is_written(tmp_path, capsys, monkeypatch, mutate, code):
    d = doc()
    mutate(d)
    got, out, err = write(capsys, monkeypatch, tmp_path, d)
    assert got == 2 and out == "" and reason(err) == code
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("text", ["", "not json", "[1, 2]", "null", '{"a": '])
def test_input_that_is_not_a_json_object_is_refused(tmp_path, capsys, monkeypatch, text):
    code, out, err = run(capsys, "write", "--repo", str(tmp_path), stdin=text, monkeypatch=monkeypatch)
    assert code == 2 and reason(err) in ("handoff_input_invalid", "handoff_schema_invalid")
    assert list(tmp_path.iterdir()) == []


def test_write_never_overwrites_an_existing_handoff(tmp_path, capsys, monkeypatch):
    write(capsys, monkeypatch, tmp_path, doc())
    before = target(tmp_path).read_bytes()
    code, _, err = write(capsys, monkeypatch, tmp_path, doc(objective="another objective"))
    assert code == 2 and reason(err) == "handoff_exists"
    assert target(tmp_path).read_bytes() == before


def test_write_leaves_no_temporary_file_behind(tmp_path, capsys, monkeypatch):
    write(capsys, monkeypatch, tmp_path, doc())
    write(capsys, monkeypatch, tmp_path, doc())  # the second one fails
    assert [p.name for p in target(tmp_path).parent.iterdir()] == ["2.json"]


def test_a_missing_repo_directory_is_refused(tmp_path, capsys, monkeypatch):
    code, _, err = write(capsys, monkeypatch, tmp_path / "nope", doc())
    assert code == 2 and reason(err) == "handoff_input_invalid"
    assert not (tmp_path / "nope").exists()


@POSIX
@pytest.mark.parametrize("depth", [".simplicio-loop", "orchestrator", "handoff", "run"])
def test_a_symlink_in_the_directory_chain_is_refused(tmp_path, capsys, monkeypatch, depth):
    outside = tmp_path / "outside"
    outside.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    chain = [".simplicio-loop", "orchestrator", "handoff", "run-20261009T161000Z"]
    here = repo
    for name in chain:
        key = "run" if name.startswith("run-") else name
        if key == depth:
            here.joinpath(name).symlink_to(outside, target_is_directory=True)
            break
        here.joinpath(name).mkdir(mode=0o700)
        here = here / name
    code, out, err = write(capsys, monkeypatch, repo, doc())
    assert code == 2 and reason(err) == "handoff_symlink" and out == ""
    assert list(outside.rglob("*")) == []


@POSIX
def test_a_symlink_in_place_of_the_file_is_refused(tmp_path, capsys, monkeypatch):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    path = target(tmp_path)
    path.parent.mkdir(parents=True, mode=0o700)
    path.symlink_to(victim)
    code, _, err = write(capsys, monkeypatch, tmp_path, doc())
    assert code == 2 and reason(err) in ("handoff_exists", "handoff_symlink")
    assert victim.read_text(encoding="utf-8") == "keep"


# --- read ----------------------------------------------------------------------------------------------------------------

def read(capsys, repo, *extra):
    code, out, err = run(capsys, "read", "--repo", str(repo), "--run", "run-20261009T161000Z", *extra)
    return code, (json.loads(out) if out else None), err


def test_read_returns_what_write_stored(tmp_path, capsys, monkeypatch):
    write(capsys, monkeypatch, tmp_path, doc())
    code, got, _ = read(capsys, tmp_path, "--n", "2")
    assert code == 0 and got == doc()


def test_read_prints_the_document_on_one_line(tmp_path, capsys, monkeypatch):
    write(capsys, monkeypatch, tmp_path, doc())
    code, out, _ = run(capsys, "read", "--repo", str(tmp_path), "--run", "run-20261009T161000Z", "--n", "2")
    assert out == json.dumps(doc(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def test_read_without_n_takes_the_highest_continuation_by_number(tmp_path, capsys, monkeypatch):
    for n in (1, 2, 10, 9):
        write(capsys, monkeypatch, tmp_path, doc(continuation=n, objective="objective %d" % n))
    assert read(capsys, tmp_path)[1]["continuation"] == 10


def test_read_ignores_files_that_are_not_handoffs(tmp_path, capsys, monkeypatch):
    write(capsys, monkeypatch, tmp_path, doc(continuation=1))
    run_dir = target(tmp_path).parent
    for name in ("7.json.bak", "notes.json", "07.json", ".8.json", "0.json", "x.tmp"):
        (run_dir / name).write_text("{}", encoding="utf-8")
    (run_dir / "99.json").mkdir()
    assert read(capsys, tmp_path)[1]["continuation"] == 1


def test_read_of_a_run_without_handoffs_fails_loud(tmp_path, capsys):
    code, got, err = read(capsys, tmp_path)
    assert code == 2 and got is None and reason(err) == "handoff_not_found"
    code, got, err = read(capsys, tmp_path, "--n", "3")
    assert code == 2 and reason(err) == "handoff_not_found"


def test_read_of_an_empty_run_directory_fails_loud(tmp_path, capsys):
    target(tmp_path).parent.mkdir(parents=True)
    assert reason(read(capsys, tmp_path)[2]) == "handoff_not_found"


@pytest.mark.parametrize("run_id", ["../x", "a/b", "", ".", ".."])
def test_read_refuses_a_run_id_that_is_a_path(tmp_path, capsys, run_id):
    code, _, err = run(capsys, "read", "--repo", str(tmp_path), "--run", run_id)
    assert code == 2 and reason(err) == "handoff_run_id_invalid"


@pytest.mark.parametrize("n", ["0", "-1"])
def test_read_refuses_a_continuation_below_one(tmp_path, capsys, n):
    code, _, err = run(capsys, "read", "--repo", str(tmp_path), "--run", "r", "--n", n)
    assert code == 2 and reason(err) == "handoff_continuation_invalid"


def test_read_refuses_a_file_that_is_not_a_valid_handoff(tmp_path, capsys):
    path = target(tmp_path)
    path.parent.mkdir(parents=True)
    bad = doc()
    bad["surprise"] = 1
    path.write_text(json.dumps(bad), encoding="utf-8")
    code, got, err = read(capsys, tmp_path, "--n", "2")
    assert code == 2 and got is None and reason(err) == "handoff_schema_invalid"
    path.write_text("not json", encoding="utf-8")
    assert reason(read(capsys, tmp_path, "--n", "2")[2]) == "handoff_input_invalid"


def test_read_refuses_a_file_that_says_it_is_another_handoff(tmp_path, capsys):
    path = target(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(doc(continuation=3)), encoding="utf-8")
    assert reason(read(capsys, tmp_path, "--n", "2")[2]) == "handoff_location_mismatch"
    path.write_text(json.dumps(doc(run_id="other-run")), encoding="utf-8")
    assert reason(read(capsys, tmp_path, "--n", "2")[2]) == "handoff_location_mismatch"


def test_read_refuses_a_file_too_large_to_be_a_handoff(tmp_path, capsys):
    path = target(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(" " * 300_000 + json.dumps(doc()), encoding="utf-8")
    assert reason(read(capsys, tmp_path, "--n", "2")[2]) == "handoff_too_large"


@POSIX
def test_read_refuses_a_symlinked_file_and_a_symlinked_directory(tmp_path, capsys):
    real = tmp_path / "real.json"
    real.write_text(json.dumps(doc()), encoding="utf-8")
    path = target(tmp_path)
    path.parent.mkdir(parents=True)
    path.symlink_to(real)
    assert reason(read(capsys, tmp_path, "--n", "2")[2]) == "handoff_symlink"
    other = tmp_path / "repo2"
    (other / ".simplicio-loop" / "orchestrator").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "run-20261009T161000Z").mkdir(parents=True)
    (elsewhere / "run-20261009T161000Z" / "2.json").write_text(json.dumps(doc()), encoding="utf-8")
    (other / ".simplicio-loop" / "orchestrator" / "handoff").symlink_to(elsewhere, target_is_directory=True)
    assert reason(read(capsys, other, "--n", "2")[2]) == "handoff_symlink"
    assert reason(read(capsys, other)[2]) == "handoff_symlink"
