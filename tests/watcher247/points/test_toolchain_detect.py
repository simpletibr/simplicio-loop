"""toolchain_detect (intake): the example point that proves the contract. It reports the configured verify; it detects nothing."""
from simplicio_loop.watcher247 import points

TARGETED = "python3 -m pytest -q tests/x.py"


def test_registered_at_intake_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "toolchain_detect"]
    assert (info.stage, info.blocking, info.conditional) == ("intake", False, False)


def test_contract(point_contract, make_ctx):
    point_contract("toolchain_detect", make_ctx(test_command=TARGETED), expect="ok")


def test_the_configured_command_is_the_evidence(point_contract, make_ctx, tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")  # a toolchain in the clone is not looked at
    result = point_contract("toolchain_detect", make_ctx(clone=tmp_path, test_command=TARGETED), expect="ok")
    assert result.evidence == {"test_command": TARGETED}
    assert result.reason_code is None


def test_without_a_configured_command_it_is_skipped_and_guesses_nothing(point_contract, make_ctx, tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    result = point_contract("toolchain_detect", make_ctx(clone=tmp_path), expect="skipped")
    assert result.evidence == {} and result.reason_code == "verify_not_configured"
