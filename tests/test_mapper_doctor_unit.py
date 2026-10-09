"""`simplicio-loop doctor mapper`: flags an installed simplicio_mapper that is not the expected build."""

import json

import pytest

from simplicio_loop import mapper_doctor as md

GOOD = {
    "version": "0.26.35",
    "origin": "simplicio-loop/packages/mapper",
    "source_commit": "a" * 40,
    "state_dir": ".simplicio-loop",
    "source": "build",
}


def _identity(**overrides):
    return {**GOOD, **overrides}


def test_matching_build_is_verified_with_no_fix_command():
    row = md.evaluate(_identity(), checkout_head=None)

    assert row["status"] == "OK"
    assert row["reason_code"] == "verified"
    assert row["fix"] is None


def test_standalone_build_that_predates_the_identity_module_is_flagged_as_missing_identity():
    row = md.evaluate(None, checkout_head=None)

    assert row["status"] == "BLOCKED"
    assert row["reason_code"] == "mapper_identity_missing"
    assert "pip uninstall -y simplicio-mapper" in row["fix"]


def test_build_from_another_origin_is_flagged_even_with_the_same_version():
    row = md.evaluate(_identity(origin="/projetos/ai/simplicio-mapper"), checkout_head=None)

    assert row["reason_code"] == "origin_mismatch"
    assert row["expected"]["origin"] == "simplicio-loop/packages/mapper"
    assert row["installed"]["origin"] == "/projetos/ai/simplicio-mapper"


def test_mapper_writing_to_the_standalone_state_dir_is_flagged():
    row = md.evaluate(_identity(state_dir=".simplicio"), checkout_head=None)

    assert row["reason_code"] == "state_dir_mismatch"
    assert row["expected"]["state_dir"] == ".simplicio-loop"


def test_unstamped_build_without_commit_is_flagged():
    row = md.evaluate(_identity(origin=None, source_commit=None, source="unstamped"),
                      checkout_head=None)

    assert row["reason_code"] == "build_unstamped"


def test_commit_that_is_not_a_full_sha_counts_as_unstamped():
    row = md.evaluate(_identity(source_commit="deadbeef"), checkout_head=None)

    assert row["reason_code"] == "build_unstamped"


def test_inside_a_checkout_the_installed_commit_must_equal_the_checkout_head():
    row = md.evaluate(_identity(), checkout_head="c" * 40)

    assert row["reason_code"] == "commit_mismatch"
    assert row["expected"]["source_commit"] == "c" * 40
    assert row["fix"] == "bash scripts/dev_install.sh"


def test_reason_codes_are_a_closed_set_with_a_fix_for_every_blocker():
    cases = [
        md.evaluate(None, checkout_head=None),
        md.evaluate(_identity(origin="x"), checkout_head=None),
        md.evaluate(_identity(state_dir=".x"), checkout_head=None),
        md.evaluate(_identity(source_commit=None), checkout_head=None),
        md.evaluate(_identity(), checkout_head="d" * 40),
    ]
    for row in cases:
        assert row["reason_code"] in md.REASON_CODES
        assert row["fix"]


def test_import_failure_reports_mapper_not_importable(monkeypatch):
    monkeypatch.setattr(md, "_load_identity", lambda: (_ for _ in ()).throw(ImportError("no")))

    row = md.build_report(".")

    assert row["reason_code"] == "mapper_not_importable"
    assert row["status"] == "BLOCKED"


def test_report_gathers_the_real_identity_and_checkout_head(monkeypatch, tmp_path):
    (tmp_path / "packages" / "mapper" / "simplicio_mapper").mkdir(parents=True)
    monkeypatch.setattr(md, "_load_identity", lambda: _identity())
    monkeypatch.setattr(md, "_git_head", lambda repo: "a" * 40)

    row = md.build_report(tmp_path)

    assert row["status"] == "OK"
    assert row["checkout_head"] == "a" * 40


def test_report_skips_the_commit_check_outside_the_monorepo(monkeypatch, tmp_path):
    monkeypatch.setattr(md, "_load_identity", lambda: _identity())
    monkeypatch.setattr(md, "_git_head", lambda repo: "c" * 40)

    row = md.build_report(tmp_path)

    assert row["checkout_head"] is None
    assert row["status"] == "OK"


def test_main_prints_json_and_exits_2_on_a_blocker(monkeypatch, capsys):
    monkeypatch.setattr(md, "_load_identity", lambda: _identity(origin="/projetos/ai/x"))

    code = md.main(["--json", "--repo", "."])
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["schema"] == "simplicio.mapper-doctor/v1"
    assert payload["reason_code"] == "origin_mismatch"


def test_main_exits_0_when_the_build_is_the_expected_one(monkeypatch, capsys):
    monkeypatch.setattr(md, "_load_identity", lambda: _identity())
    monkeypatch.setattr(md, "_git_head", lambda repo: None)

    assert md.main(["--repo", "."]) == 0
    assert "verified" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["doctor", "mapper", "--json"]])
def test_cli_doctor_mapper_subcommand_is_wired(monkeypatch, argv, capsys):
    from simplicio_loop import cli_impl
    monkeypatch.setattr(md, "_load_identity", lambda: _identity())
    monkeypatch.setattr(md, "_git_head", lambda repo: None)

    assert cli_impl.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["reason_code"] == "verified"
