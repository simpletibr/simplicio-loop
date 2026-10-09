"""endpoint_compare (verify): route drift of the clone through scripts/flow_audit.py, on a real tmp git repo."""
import subprocess
from pathlib import Path

import pytest

from simplicio_loop.watcher247 import proc, sandbox
from simplicio_loop.watcher247.points import endpoint_compare

OLD_ROUTES = '@app.get("/api/users")\ndef users():\n    return []\n'
NEW_ROUTE = '\n@app.get("/api/new")\ndef new():\n    return []\n'


@pytest.fixture(autouse=True)
def unsandboxed(monkeypatch):
    monkeypatch.setenv(sandbox.OPT_OUT, "1")  # the sandbox has its own tests; a host without bwrap still runs this


def git(clone: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=clone, check=True, capture_output=True)


@pytest.fixture
def clone(tmp_path):
    root = tmp_path / "repo"
    (root / "backend").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "backend" / "routes.py").write_text(OLD_ROUTES, encoding="utf-8")
    (root / "src" / "utils.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "base")
    return root


def test_skipped_when_no_route_or_handler_changed(point_contract, make_ctx, clone):
    (clone / "src" / "utils.py").write_text("def helper(x):\n    return x\n", encoding="utf-8")
    result = point_contract("endpoint_compare", make_ctx(clone=clone), expect="skipped")
    assert result.reason_code == "not_applicable"


def test_skipped_when_nothing_changed(point_contract, make_ctx, clone):
    point_contract("endpoint_compare", make_ctx(clone=clone), expect="skipped")


def test_applies_on_a_changed_tracked_route_and_records_the_added_endpoint(point_contract, make_ctx, clone):
    (clone / "backend" / "routes.py").write_text(OLD_ROUTES + NEW_ROUTE, encoding="utf-8")
    result = point_contract("endpoint_compare", make_ctx(clone=clone), expect="ok")
    assert result.evidence["added"] == ["GET /api/new"]
    assert result.evidence["removed"] == []
    assert (result.evidence["endpoints_base"], result.evidence["endpoints_head"]) == (1, 2)


def test_a_removed_route_is_recorded(point_contract, make_ctx, clone):
    (clone / "backend" / "routes.py").write_text("# gone\n", encoding="utf-8")
    result = point_contract("endpoint_compare", make_ctx(clone=clone), expect="ok")
    assert result.evidence["removed"] == ["GET /api/users"]


def test_an_untracked_new_route_file_is_seen(point_contract, make_ctx, clone):
    (clone / "backend" / "orders.py").write_text('@app.get("/api/orders")\ndef orders():\n    return []\n',
                                                 encoding="utf-8")
    git_status = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=clone, capture_output=True, text=True)
    assert git_status.stdout == ""  # git diff HEAD alone cannot see it
    result = point_contract("endpoint_compare", make_ctx(clone=clone), expect="ok")
    assert result.evidence["added"] == ["GET /api/orders"]


def test_a_route_outside_a_route_path_applies_by_content(point_contract, make_ctx, clone):
    (clone / "app.py").write_text('@app.get("/api/health")\ndef health():\n    return {}\n', encoding="utf-8")
    result = point_contract("endpoint_compare", make_ctx(clone=clone), expect="ok")
    assert result.evidence["added"] == ["GET /api/health"]


def test_new_gaps_of_the_audit_are_evidence(point_contract, make_ctx, clone):
    (clone / "backend" / "routes.py").write_text(
        OLD_ROUTES + '\n@app.get("/api/todo")\ndef todo():\n    raise NotImplementedError()\n', encoding="utf-8")
    result = point_contract("endpoint_compare", make_ctx(clone=clone), expect="ok")
    assert result.evidence["new_high_gaps"] >= 1
    assert any("backend_endpoint_stub" in gap for gap in result.evidence["new_gaps"])


def test_flow_audit_is_reused_not_reimplemented(point_contract, make_ctx, clone, monkeypatch):
    calls = []
    real = proc.run

    async def spy(argv, **kwargs):
        calls.append(list(argv))
        return await real(argv, **kwargs)

    monkeypatch.setattr(proc, "run", spy)
    (clone / "backend" / "routes.py").write_text(OLD_ROUTES + NEW_ROUTE, encoding="utf-8")
    point_contract("endpoint_compare", make_ctx(clone=clone), expect="ok")
    script = endpoint_compare._script()
    assert script is not None and script.name == "flow_audit.py"
    audits = [argv for argv in calls if str(script) in argv]
    assert len(audits) == 2 and all(argv[argv.index(str(script)) + 1] == "audit" for argv in audits)  # base + working tree
    assert audits[1][audits[1].index(str(script)) + 2] == str(clone)
    assert not hasattr(endpoint_compare, "ROUTE_PATTERNS")  # no route regexes of its own


@pytest.mark.parametrize("body, code", [
    ("import sys\nsys.exit(2)\n", "flow_audit_failed"),
    ("print('not json')\n", "flow_audit_failed"),
    ("import sys\nprint('{\"schema\": \"simplicio.flow-audit/v1\"}')\nsys.exit(3)\n", "flow_audit_failed"),
])
def test_an_audit_that_fails_is_an_error_never_ok(point_contract, make_ctx, clone, monkeypatch, tmp_path, body, code):
    broken = tmp_path / "broken_audit.py"
    broken.write_text(body, encoding="utf-8")
    monkeypatch.setattr(endpoint_compare, "_script", lambda: broken)
    (clone / "backend" / "routes.py").write_text(OLD_ROUTES + NEW_ROUTE, encoding="utf-8")
    result = point_contract("endpoint_compare", make_ctx(clone=clone), expect="error")
    assert result.reason_code == code


def test_a_missing_audit_script_is_an_error(point_contract, make_ctx, clone, monkeypatch):
    monkeypatch.setattr(endpoint_compare, "_script", lambda: None)
    monkeypatch.setattr(endpoint_compare, "_module", [])
    (clone / "backend" / "routes.py").write_text(OLD_ROUTES + NEW_ROUTE, encoding="utf-8")
    result = point_contract("endpoint_compare", make_ctx(clone=clone), expect="error")
    assert result.reason_code == "flow_audit_missing"


def test_a_clone_that_is_not_a_git_repo_is_an_error(point_contract, make_ctx, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    result = point_contract("endpoint_compare", make_ctx(clone=plain), expect="error")
    assert result.reason_code == "git_archive_failed"


def test_without_a_sandbox_the_point_errors(point_contract, make_ctx, clone, monkeypatch):
    monkeypatch.delenv(sandbox.OPT_OUT)
    monkeypatch.setattr(sandbox.shutil, "which", lambda binary: None)
    (clone / "backend" / "routes.py").write_text(OLD_ROUTES + NEW_ROUTE, encoding="utf-8")
    result = point_contract("endpoint_compare", make_ctx(clone=clone), expect="error")
    assert result.reason_code == "sandbox_unavailable"


def test_no_clone_does_not_apply(point_contract, make_ctx):
    result = point_contract("endpoint_compare", make_ctx(), expect="skipped")
    assert result.reason_code == "not_applicable"
