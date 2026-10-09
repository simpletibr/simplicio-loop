"""toolchain_detect (intake): the example point that proves the contract, wrapping verify.detect_test_command."""
from simplicio_loop.watcher247 import points, verify


def test_registered_at_intake_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "toolchain_detect"]
    assert (info.stage, info.blocking, info.conditional) == ("intake", False, False)


def test_contract(point_contract, make_ctx, tmp_path):
    point_contract("toolchain_detect", make_ctx(clone=tmp_path), expect="ok")


def test_detected_command_is_the_evidence(point_contract, make_ctx, tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    result = point_contract("toolchain_detect", make_ctx(clone=tmp_path), expect="ok")
    assert result.evidence == {"test_command": verify.PYTEST}
    assert result.reason_code is None


def test_no_toolchain_is_ok_and_names_unverified(point_contract, make_ctx, tmp_path):
    result = point_contract("toolchain_detect", make_ctx(clone=tmp_path), expect="ok")
    assert result.evidence == {"test_command": None, "label": verify.UNVERIFIED}


def test_without_a_clone_it_is_skipped(point_contract, make_ctx):
    result = point_contract("toolchain_detect", make_ctx(), expect="skipped")
    assert result.reason_code == "no_clone"
