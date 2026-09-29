"""Hermetic timeout and reason-code contracts for scripts/check.py."""
from __future__ import annotations

import os
import errno
import importlib.util
import inspect
import _socket
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import pytest

from scripts import check
from scripts import check_runtime


def test_pytest_reason_markers_are_counted_by_explicit_category() -> None:
    output = "\n".join([
        "SKIPPED [3] tests/conftest.py: CAPABILITY_UNAVAILABLE[af_unix_eperm]: denied",
        "SKIPPED [1] tests/x.py: EXTERNAL_INTEGRATION_UNAVAILABLE[installed_e2e]: absent",
        "SKIPPED [8] tests/y.py: ordinary platform-specific skip",
        "EXTERNAL_INTEGRATION_EXCLUDED[core_marker_selection]=4",
    ])

    assert check.classify_pytest_reasons(output) == {
        "capability_unavailable": {"af_unix_eperm": 3},
        "external_integration": {"installed_e2e": 1, "core_marker_selection": 4},
    }


def test_reason_aggregation_keeps_regressions_separate_from_environment() -> None:
    results = {
        "audit": check.GateResult(False, "claims_audit_failed"),
        "tests": check.GateResult(
            True,
            reasons={
                "capability_unavailable": {"af_unix_eperm": 2},
                "external_integration": {"installed_e2e": 1},
            },
        ),
    }

    assert check.aggregate_reason_groups(results) == {
        "regression": {"claims_audit_failed": 1},
        "capability_unavailable": {"af_unix_eperm": 2},
        "external_integration": {"installed_e2e": 1},
    }


def test_reason_aggregation_classifies_containment_unavailable_as_capability() -> None:
    results = {
        "core_tests": check.GateResult(False, "core_tests_containment_unavailable"),
    }

    assert check.aggregate_reason_groups(results) == {
        "regression": {},
        "capability_unavailable": {"core_tests_containment_unavailable": 1},
        "external_integration": {},
    }


def test_pytest_exit_five_is_a_failed_no_tests_result() -> None:
    result = check._gate_result("core_tests", check.CommandResult(returncode=5))

    assert result.ok is False
    assert result.reason_code == "pytest_no_tests_collected"


def test_passed_count_uses_the_final_pytest_summary_line() -> None:
    assert check._passed_test_count("test output: 99 passed\n3544 passed, 42 skipped in 1.0s\n") == 3544
    assert check._passed_test_count("user output: 99 passed\n42 skipped in 1.0s\n") == 0
    assert check._deselected_test_count("1 passed, 14 deselected in 1.0s\n") == 14
    assert check._deselected_test_count("1 passed in 1.0s\n") == 0


def test_default_and_core_pytest_selectors_exclude_the_marked_external_lane() -> None:
    core = check._pytest_args(["tests/test_example.py"], only_core=True)
    full = check._pytest_args(["tests/test_example.py"], only_core=False)

    expression_index = core.index("not external_integration and not satellite")
    assert core[expression_index - 1:expression_index + 1] == [
        "-m", "not external_integration and not satellite",
    ]
    full_expression_index = full.index("not external_integration")
    assert full[full_expression_index - 1:full_expression_index + 1] == [
        "-m", "not external_integration",
    ]


def test_pytest_file_shards_preserve_order_and_bound_targets() -> None:
    files = ["C:/repo/tests/test_%03d.py" % index for index in range(65)]
    shards = check._test_file_shards(files, shard_size=32)
    assert [len(shard) for shard in shards] == [32, 32, 1]
    assert [item for shard in shards for item in shard] == files


def test_pytest_probe_reports_containment_failure_separately(monkeypatch) -> None:
    unavailable = check.CommandResult(
        126, reason=check.CommandReason.CONTAINMENT_UNAVAILABLE,
    )
    monkeypatch.setattr(check, "_run_bounded", lambda *args, **kwargs: unavailable)

    assert check._have_pytest() == "containment_unavailable"


def test_satellite_test_stems_match_the_current_inventory() -> None:
    assert check.SATELLITE_TEST_STEMS == {
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
    }


def test_external_collect_count_parses_pytest_collection_summary() -> None:
    assert check._external_test_count("12/2400 tests collected (2388 deselected)\n") == 12
    assert check._external_test_count("no usable summary\n") is None


def test_unknown_check_flag_is_rejected_fail_closed() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check.py", "--not-a-real-gate-flag"],
        cwd=check.REPO,
        capture_output=True, stdin=subprocess.DEVNULL,
        text=True,
    )
    assert result.returncode == 2
    assert "unknown flag" in result.stderr


def test_python38_collects_pep585_annotation_test_modules() -> None:
    python38 = shutil.which("python3.8")
    if python38 is None:
        pytest.skip("CAPABILITY_UNAVAILABLE[python38_runtime]: Python 3.8 is not installed")
    probe = subprocess.run(
        [python38, "-c", "import pytest"],
        cwd=check.REPO,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if probe.returncode != 0:
        pytest.skip(
            "CAPABILITY_UNAVAILABLE[python38_pytest]: Python 3.8 cannot import pytest: "
            + (probe.stderr or probe.stdout).strip()
        )
    result = subprocess.run(
        [
            python38, "-m", "pytest", "--collect-only", "-q",
            "tests/test_completion_oracle_matrix_unit.py",
            "tests/test_map_service_git_mapper_system.py",
            "tests/test_merge_queue_live_probe_integration.py",
        ],
        cwd=check.REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_runtime_environment_is_sanitized_and_uses_only_checkout_pythonpath() -> None:
    from scripts.check_runtime import _repo_env, REPO

    clean = _repo_env({
        "PYTHONPATH": "/untrusted", "PYTEST_ADDOPTS": "-p evil",
        "PYTEST_PLUGINS": "evil", "HTTP_PROXY": "http://proxy",
        "GITHUB_TOKEN": "secret", "SAFE": "yes",
        "SIMPLICIO_CORE_NO_NETWORK": "1",
        "SIMPLICIO_SYSTEM_TEST_NESTED": "1",
    })
    # The checkout comes first; the only other entries are the bound operator
    # packages (#1290). A caller-supplied PYTHONPATH never survives.
    entries = clean["PYTHONPATH"].split(os.pathsep)
    assert entries[0] == REPO
    assert "/untrusted" not in entries
    for extra in entries[1:]:
        assert os.path.isdir(os.path.join(extra, "simplicio_mapper")), extra
    assert clean["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert clean["SIMPLICIO_CORE_NO_NETWORK"] == "1"
    assert clean["SIMPLICIO_SYSTEM_TEST_NESTED"] == "1"
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "HTTP_PROXY", "GITHUB_TOKEN", "SAFE"):
        assert name not in clean


def test_bounded_run_uses_a_removed_per_run_home() -> None:
    result = check._run_bounded(
        [sys.executable, "-c", (
            "import os; print(os.environ['HOME']); "
            "print(os.environ['USERPROFILE']); "
            "print(os.environ.get('AWS_SECRET_ACCESS_KEY', 'absent'))"
        )],
        phase="stdlib_test", capture_output=True,
        env={"PATH": os.environ.get("PATH", ""), "AWS_SECRET_ACCESS_KEY": "secret"},
    )
    home, userprofile, secret = result.stdout.splitlines()
    assert result.returncode == 0
    assert home == userprofile
    assert not os.path.exists(home)
    assert secret == "absent"


@pytest.mark.skipif(os.name == "nt", reason="CAPABILITY_UNAVAILABLE[af_unix_eperm]: POSIX socket contract")
@pytest.mark.skipif(sys.platform != "linux", reason="Linux network containment contract")
def test_core_network_hook_blocks_inet_but_not_unix(monkeypatch, tmp_path) -> None:
    spec = importlib.util.spec_from_file_location(
        "check_gate_conftest", str(check.REPO + "/tests/conftest.py")
    )
    gate_conftest = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(gate_conftest)

    original_socket_class = socket.socket
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_sendto = socket.socket.sendto
    original_sendmsg = getattr(socket.socket, "sendmsg", None)
    original_create = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo
    original_gethostbyname = socket.gethostbyname
    original_gethostbyname_ex = socket.gethostbyname_ex
    original_gethostbyaddr = socket.gethostbyaddr
    original_getnameinfo = socket.getnameinfo
    original_socket_type = socket.SocketType
    original_raw_socket = _socket.socket
    original_raw_socket_type = _socket.SocketType
    original_raw_getaddrinfo = _socket.getaddrinfo
    original_raw_gethostbyname = _socket.gethostbyname
    original_raw_gethostbyname_ex = _socket.gethostbyname_ex
    original_raw_gethostbyaddr = _socket.gethostbyaddr
    original_raw_getnameinfo = _socket.getnameinfo
    original_popen = subprocess.Popen
    original_popen_signature = inspect.signature(original_popen)
    original_popen_init_signature = inspect.signature(original_popen.__init__)
    original_system = os.system
    original_os_popen = os.popen
    original_os_launchers = {
        name: getattr(os, name)
        for name in (
            "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp",
            "execlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
            "posix_spawn", "posix_spawnp",
        )
        if hasattr(os, name)
    }
    monkeypatch.setenv("SIMPLICIO_CORE_NO_NETWORK", "1")
    gate_conftest.pytest_configure(None)
    try:
        assert isinstance(subprocess.Popen, type)
        assert inspect.signature(subprocess.Popen) == original_popen_signature
        assert inspect.signature(subprocess.Popen.__init__) == original_popen_init_signature
        assert socket.socket is original_socket_class
        assert socket.SocketType is original_socket_type
        assert _socket.socket is original_raw_socket
        assert _socket.SocketType is original_raw_socket_type
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            assert client.connect_ex(("127.0.0.1", port)) == 0
        accepted, _ = listener.accept()
        accepted.close()
        with socket.create_connection(("localhost", port)) as client:
            pass
        accepted, _ = listener.accept()
        accepted.close()
        listener.close()
        with __import__("pytest").raises(OSError) as raised:
            socket.create_connection(("198.51.100.7", 9))
        assert raised.value.errno == errno.ENETUNREACH
        with __import__("pytest").raises(OSError) as raised:
            socket.getaddrinfo("example.invalid", 443)
        assert raised.value.errno == errno.ENETUNREACH
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            with __import__("pytest").raises(OSError) as raised:
                client.sendto(b"blocked", ("198.51.100.7", 9))
            assert raised.value.errno == errno.ENETUNREACH
        with __import__("pytest").raises(OSError) as raised:
            socket.gethostbyname("example.invalid")
        assert raised.value.errno == errno.ENETUNREACH
        for resolver, arguments in (
            (_socket.gethostbyname, ("example.invalid",)),
            (_socket.gethostbyname_ex, ("example.invalid",)),
            (_socket.gethostbyaddr, ("198.51.100.7",)),
            (_socket.getnameinfo, (("198.51.100.7", 443), 0)),
        ):
            with pytest.raises(OSError) as raised:
                resolver(*arguments)
            assert raised.value.errno == errno.ENETUNREACH
        assert isinstance(socket.socket(), socket.SocketType)
        raw_client = _socket.SocketType(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(OSError) as raised:
                raw_client.connect(("198.51.100.7", 9))
            assert raised.value.errno == errno.ENETUNREACH
        finally:
            raw_client.close()

        # Bytes, positional Popen options, a replaced child environment, and
        # shell command text must not provide an interpreter escape route.
        guarded_env = dict(os.environ)
        with pytest.raises(OSError) as raised:
            subprocess.Popen(
                [b"ignored", b"-S", b"-c", b"pass"], -1,
                os.fsencode(sys.executable), None, None, None, None, True,
                False, os.fsencode(tmp_path), guarded_env,
            )
        assert raised.value.errno == errno.EPERM
        duplicate_env_args = (
            [sys.executable, "-c", "raise AssertionError('must not launch')"],
            -1, None, None, None, None, None, True, False, None, guarded_env,
        )
        with pytest.raises(TypeError) as native_error:
            original_popen(*duplicate_env_args, env=guarded_env)
        with pytest.raises(TypeError) as guarded_error:
            subprocess.Popen(
                *duplicate_env_args, env=guarded_env,
            )
        assert str(guarded_error.value) == str(native_error.value)
        without_guard = dict(os.environ)
        without_guard.pop("SIMPLICIO_CORE_NO_NETWORK", None)
        child = subprocess.run(
            [sys.executable, "-c", "import errno,socket; "
             "\ntry:\n socket.create_connection(('198.51.100.7',9))\n"
             "except OSError as exc:\n assert exc.errno == errno.ENETUNREACH; print('blocked')\n"
             "else:\n raise AssertionError('network was not blocked')"],
            env=without_guard, capture_output=True, text=True,
        )
        assert child.returncode == 0, child.stderr
        assert child.stdout.strip() == "blocked"
        with pytest.raises(OSError) as raised:
            subprocess.Popen("true; %s -S -c pass" % sys.executable, shell=True)
        assert raised.value.errno == errno.EPERM
        with pytest.raises(OSError) as raised:
            subprocess.Popen(
                "true", -1, None, None, None, None, None, True, True,
            )
        assert raised.value.errno == errno.EPERM
        for name in ("posix_spawn", "posix_spawnp"):
            launcher = getattr(os, name, None)
            if launcher is not None:
                with pytest.raises(OSError) as raised:
                    launcher(sys.executable, [sys.executable, "-S", "-c", "pass"], guarded_env)
                assert raised.value.errno == errno.EPERM
        if hasattr(socket, "AF_UNIX"):
            try:
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            except PermissionError:
                # The sandbox can deny AF_UNIX itself; the hook did not turn
                # that into its ENETUNREACH network policy.
                pass
            else:
                with client:
                    with __import__("pytest").raises(FileNotFoundError):
                        client.connect(str(tmp_path / "no-server.sock"))
    finally:
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex
        socket.socket.sendto = original_sendto
        if original_sendmsg is not None:
            socket.socket.sendmsg = original_sendmsg
        socket.create_connection = original_create
        socket.getaddrinfo = original_getaddrinfo
        socket.gethostbyname = original_gethostbyname
        socket.gethostbyname_ex = original_gethostbyname_ex
        socket.gethostbyaddr = original_gethostbyaddr
        socket.getnameinfo = original_getnameinfo
        socket.SocketType = original_socket_type
        _socket.socket = original_raw_socket
        _socket.SocketType = original_raw_socket_type
        _socket.getaddrinfo = original_raw_getaddrinfo
        _socket.gethostbyname = original_raw_gethostbyname
        _socket.gethostbyname_ex = original_raw_gethostbyname_ex
        _socket.gethostbyaddr = original_raw_gethostbyaddr
        _socket.getnameinfo = original_raw_getnameinfo
        subprocess.Popen = original_popen
        os.system = original_system
        os.popen = original_os_popen
        for name, launcher in original_os_launchers.items():
            setattr(os, name, launcher)


def _assert_pid_gone(pid: int) -> None:
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if check_runtime._pid_is_running(pid) is False:
            return
        time.sleep(0.02)
    raise AssertionError("timed-out process %d was not reaped" % pid)


def test_bounded_phase_reports_timeout_and_reaps_process_group(tmp_path) -> None:
    leader_pid = tmp_path / "leader.pid"
    child_pid = tmp_path / "child.pid"
    grandchild = (
        "import os,pathlib,sys,time; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    )
    leader = (
        "import os,pathlib,subprocess,sys,time; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
        "subprocess.Popen([sys.executable, '-c', sys.argv[3], sys.argv[2]]); "
        "time.sleep(30)"
    )
    result = check._run_bounded(
        [sys.executable, "-c", leader, str(leader_pid), str(child_pid), grandchild],
        phase="stdlib_test",
        capture_output=True,
        timeout_seconds=0.3,
    )

    assert result.timed_out is True
    assert leader_pid.exists()
    assert child_pid.exists()
    _assert_pid_gone(int(leader_pid.read_text()))
    _assert_pid_gone(int(child_pid.read_text()))


def test_timeout_kills_group_after_leader_exits_but_child_keeps_pipes_open(tmp_path) -> None:
    child_pid = tmp_path / "child-after-leader.pid"
    child = (
        "import os,pathlib,sys,time; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    )
    leader = (
        "import subprocess,sys; "
        "subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[1]])"
    )
    started = time.monotonic()
    result = check._run_bounded(
        [sys.executable, "-c", leader, str(child_pid), child],
        phase="stdlib_test",
        capture_output=True,
        timeout_seconds=0.3,
    )

    assert result.timed_out is True
    assert time.monotonic() - started < 2.0
    assert child_pid.exists()
    _assert_pid_gone(int(child_pid.read_text()))


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process-tree containment contract")
def test_timeout_kills_observed_descendant_that_escapes_process_group(tmp_path) -> None:
    child_pid = tmp_path / "escaped-child.pid"
    child = (
        "import os,pathlib,sys,time; os.setsid(); "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    )
    leader = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[1]]); time.sleep(.15)"
    )
    started = time.monotonic()
    result = check._run_bounded(
        [sys.executable, "-c", leader, str(child_pid), child], phase="stdlib_test",
        capture_output=True, timeout_seconds=.3,
    )
    assert result.timed_out is True
    assert time.monotonic() - started < 2.0
    _assert_pid_gone(int(child_pid.read_text()))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux subreaper contract")
def test_immediate_double_fork_setsid_is_adopted_and_reaped(tmp_path) -> None:
    """An orphan must be caught even when its original leader exits at once."""
    child_pid = tmp_path / "double-fork.pid"
    grandchild = (
        "import os,pathlib,sys,time; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    )
    leader = """import os, subprocess, sys
pid = os.fork()
if pid:
    os._exit(0)
os.setsid()
subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[1]],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
import pathlib, time
while not pathlib.Path(sys.argv[1]).exists():
    time.sleep(.005)
devnull = os.open(os.devnull, os.O_WRONLY)
os.dup2(devnull, 1)
os.dup2(devnull, 2)
os._exit(0)
"""
    result = check._run_bounded(
        [sys.executable, "-c", leader, str(child_pid), grandchild],
        phase="stdlib_test", capture_output=True, timeout_seconds=0.5,
    )
    assert result.reason is check_runtime.CommandReason.DESCENDANT_LEAK
    assert result.timed_out is False
    assert child_pid.exists()
    pid = int(child_pid.read_text())
    deadline = time.monotonic() + 3.0
    while os.path.exists("/proc/%d" % pid) and time.monotonic() < deadline:
        stat_path = "/proc/%d/stat" % pid
        try:
            with open(stat_path) as handle:
                assert handle.read().rsplit(") ", 1)[1].split()[0] != "Z"
        except FileNotFoundError:
            break
        time.sleep(0.02)
    assert not os.path.exists("/proc/%d" % pid), "adopted descendant was not reaped"


def test_bounded_capture_keeps_tail_pytest_summary_after_large_prefix() -> None:
    payload = (
        "import sys; sys.stdout.write('x' * %d); "
        "sys.stdout.write('\\n1 passed\\n'); "
        "sys.stdout.write('3544 passed, 42 skipped in 1.0s\\n')"
    ) % (2 * 1024 * 1024)
    result = check._run_bounded(
        [sys.executable, "-c", payload], phase="stdlib_test",
        capture_output=True, timeout_seconds=5,
    )
    assert result.returncode == 0
    assert "OUTPUT_TRUNCATED[stdout total_bytes=" in result.stdout
    assert len(result.stdout.encode("utf-8")) <= check_runtime.MAX_CAPTURE_BYTES
    assert check._passed_test_count(result.stdout) == 3544


def test_bounded_capture_invalid_utf8_keeps_marker_within_public_byte_limit() -> None:
    capture = check_runtime._CaptureBuffer()
    capture.add(b"\xff" * check_runtime.MAX_CAPTURE_BYTES)

    rendered = capture.render("stdout")

    assert "OUTPUT_TRUNCATED[stdout total_bytes=" in rendered
    assert len(rendered.encode("utf-8")) <= check_runtime.MAX_CAPTURE_BYTES


def test_windows_thread_capture_does_not_register_pipes_with_selector(monkeypatch) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "print('portable-capture')"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
    )
    from tests._os_proxy import os_with_name

    monkeypatch.setattr(check_runtime, "os", os_with_name(check_runtime.os, "nt"))
    monkeypatch.setattr(
        check_runtime.selectors, "DefaultSelector",
        lambda: (_ for _ in ()).throw(AssertionError("Windows pipe selector used")),
    )
    stdout, stderr, timed_out, leaked = check_runtime._bounded_capture(
        proc, 2.0, set(), discover=False,
    )
    assert stdout.strip() == "portable-capture"
    assert stderr == ""
    assert timed_out is False
    assert leaked is False


def test_windows_thread_capture_timeout_is_bounded_when_taskkill_fails(monkeypatch) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
    )

    class FailedTaskkill:
        returncode = 1

    from tests._os_proxy import os_with_name

    monkeypatch.setattr(check_runtime, "os", os_with_name(check_runtime.os, "nt"))
    monkeypatch.setattr(check_runtime.subprocess, "run", lambda *_args, **_kwargs: FailedTaskkill())
    started = time.monotonic()
    _stdout, _stderr, timed_out, leaked = check_runtime._bounded_capture(
        proc, 0.1, set(), discover=False,
    )
    assert time.monotonic() - started < 2.0
    assert timed_out is True
    assert leaked is False
    assert proc.poll() is not None


def test_thread_capture_poll_error_still_cleans_spawned_process(monkeypatch) -> None:
    cleanup_calls = []

    class BrokenPollProcess:
        stdout = tempfile.TemporaryFile()
        stderr = tempfile.TemporaryFile()

        @staticmethod
        def poll():
            raise OSError("poll unavailable")

    proc = BrokenPollProcess()

    def terminate(observed, descendants=None, *, baseline=None, discover=False):
        cleanup_calls.append((observed, set(descendants or ()), set(baseline or ()), discover))
        return True

    monkeypatch.setattr(check_runtime, "_terminate_and_reap", terminate)
    with pytest.raises(OSError, match="poll unavailable"):
        check_runtime._bounded_capture_threads(
            proc, 1.0, {70001}, discover=False,
        )
    assert cleanup_calls == [(proc, set(), {70001}, False)]
    assert proc.stdout.closed is True
    assert proc.stderr.closed is True


def test_thread_capture_reader_error_still_cleans_and_closes(monkeypatch) -> None:
    cleanup_calls = []

    class WaitingProcess:
        stdout = tempfile.TemporaryFile()
        stderr = tempfile.TemporaryFile()

        @staticmethod
        def poll():
            return None

    proc = WaitingProcess()
    monkeypatch.setattr(
        check_runtime.os, "read",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("read unavailable")),
    )
    monkeypatch.setattr(
        check_runtime, "_terminate_and_reap",
        lambda observed, descendants=None, *, baseline=None, discover=False:
        cleanup_calls.append((observed, set(descendants or ()), set(baseline or ()), discover))
        or True,
    )
    with pytest.raises(OSError, match="read unavailable"):
        check_runtime._bounded_capture_threads(proc, 1.0, {70002}, discover=False)
    assert cleanup_calls == [(proc, set(), {70002}, False)]
    assert proc.stdout.closed is True
    assert proc.stderr.closed is True


@pytest.mark.skipif(os.name == "nt", reason="POSIX selector capture contract")
def test_capture_setup_failure_terminates_spawned_process(monkeypatch) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
    )

    class BrokenSelector:
        @staticmethod
        def register(*_args, **_kwargs):
            raise OSError("selector registration failed")

        @staticmethod
        def get_map():
            return {}

        @staticmethod
        def close():
            return None

    monkeypatch.setattr(check_runtime.selectors, "DefaultSelector", BrokenSelector)
    with pytest.raises(OSError, match="selector registration failed"):
        check_runtime._bounded_capture(proc, 2.0, set(), discover=False)
    assert proc.poll() is not None


@pytest.mark.parametrize("threaded", [False, True])
def test_capture_buffer_init_failure_cleans_child_and_pipes(monkeypatch, threaded) -> None:
    if os.name == "nt" and not threaded:
        pytest.skip("CAPABILITY_UNAVAILABLE[posix_selector]: Windows uses thread capture")
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
        start_new_session=True,
    )
    stdout, stderr = proc.stdout, proc.stderr
    cleanup_calls = []
    real_terminate = check_runtime._terminate_and_reap

    def terminate(observed, descendants=None, *, baseline=None, discover=False):
        cleanup_calls.append(observed)
        return real_terminate(observed, descendants, baseline=baseline, discover=False)

    monkeypatch.setattr(check_runtime, "_terminate_and_reap", terminate)
    monkeypatch.setattr(
        check_runtime, "_CaptureBuffer",
        lambda: (_ for _ in ()).throw(OSError("buffer init failed")),
    )
    capture = check_runtime._bounded_capture_threads if threaded else check_runtime._bounded_capture
    with pytest.raises(OSError, match="buffer init failed"):
        capture(proc, 1.0, set(), discover=False)
    assert cleanup_calls == [proc]
    assert proc.poll() is not None
    assert stdout.closed is True
    assert stderr.closed is True


@pytest.mark.skipif(os.name == "nt", reason="POSIX selector capture contract")
def test_selector_init_failure_cleans_child_and_pipes(monkeypatch) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
    )
    stdout, stderr = proc.stdout, proc.stderr
    cleanup_calls = []
    real_terminate = check_runtime._terminate_and_reap

    def terminate(observed, descendants=None, *, baseline=None, discover=False):
        cleanup_calls.append(observed)
        return real_terminate(observed, descendants, baseline=baseline, discover=False)

    monkeypatch.setattr(check_runtime, "_terminate_and_reap", terminate)
    monkeypatch.setattr(
        check_runtime.selectors, "DefaultSelector",
        lambda: (_ for _ in ()).throw(OSError("selector init failed")),
    )
    with pytest.raises(OSError, match="selector init failed"):
        check_runtime._bounded_capture(proc, 1.0, set(), discover=False)
    assert cleanup_calls == [proc]
    assert proc.poll() is not None
    assert stdout.closed is True
    assert stderr.closed is True


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cleanup contract")
def test_refresh_keeps_partial_leader_and_safe_adopted_descendants(monkeypatch) -> None:
    partial_pid = 93001
    adopted_pid = 93002
    baseline_pid = 93003
    signaled = []

    class FinishedProcess:
        pid = 93004

        @staticmethod
        def poll():
            return 0

        @staticmethod
        def wait(timeout=None):
            return 0

        @staticmethod
        def kill():
            return None

        @staticmethod
        def terminate():
            return None

    proc = FinishedProcess()

    def scan(pid):
        if pid == proc.pid:
            return check_runtime._DescendantDiscoveryError(
                {partial_pid}, "test_partial",
            )
        return {baseline_pid, adopted_pid}

    monkeypatch.setattr(check_runtime, "_posix_descendants", scan)
    monkeypatch.setattr(check_runtime.os, "kill", lambda pid, sig: signaled.append((pid, sig)))
    monkeypatch.setattr(check_runtime.os, "killpg", lambda *_args: None)
    monkeypatch.setattr(
        check_runtime, "_reap_adopted",
        lambda descendants, *, exclude: set(),
    )
    available = check_runtime._terminate_and_reap(
        proc, set(), baseline={baseline_pid}, discover=True,
    )
    assert available is False
    killed_pids = {pid for pid, _sig in signaled}
    assert partial_pid in killed_pids
    assert adopted_pid in killed_pids
    assert baseline_pid not in killed_pids


def test_unknown_caller_nspid_depth_never_selects_a_host_pid(monkeypatch) -> None:
    monkeypatch.setattr(check_runtime, "_nspid_values", lambda path: None)
    assert check_runtime._caller_namespace_depth() is None
    assert check_runtime._visible_namespace_pid(4321, None, None) is None


@pytest.mark.skipif(sys.platform != "linux", reason="Linux subreaper containment contract")
def test_unavailable_containment_is_a_failed_command_reason(monkeypatch) -> None:
    monkeypatch.setattr(check_runtime, "_enable_linux_subreaper", lambda: False)
    result = check_runtime.run_bounded([sys.executable, "-c", "pass"], phase="stdlib_test")
    assert result.reason is check_runtime.CommandReason.CONTAINMENT_UNAVAILABLE
    assert result.returncode == 126


@pytest.mark.skipif(sys.platform != "linux", reason="Linux descendant discovery contract")
def test_capture_containment_failure_cleans_previously_observed_descendant(monkeypatch) -> None:
    baseline_pid = 81001
    child_pid = 81002
    leader_scans = 0
    cleanup_calls = []
    real_terminate = check_runtime._terminate_and_reap

    monkeypatch.setattr(check_runtime, "_enable_linux_subreaper", lambda: True)

    def discover(pid):
        nonlocal leader_scans
        if pid == os.getpid():
            return {baseline_pid}
        leader_scans += 1
        return (
            {child_pid} if leader_scans == 1
            else check_runtime._DescendantDiscoveryError(set(), "test_unavailable")
        )

    def terminate(proc, descendants=None, *, baseline=None, discover=False):
        cleanup_calls.append((set(descendants or ()), set(baseline or ()), discover))
        return real_terminate(proc, descendants, baseline=baseline, discover=False)

    monkeypatch.setattr(check_runtime, "_posix_descendants", discover)
    monkeypatch.setattr(check_runtime, "_terminate_and_reap", terminate)

    result = check_runtime.run_bounded(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        phase="stdlib_test", capture_output=True, timeout_seconds=2,
    )

    assert result.reason is check_runtime.CommandReason.CONTAINMENT_UNAVAILABLE
    assert cleanup_calls[-1] == ({child_pid}, {baseline_pid}, False)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux descendant discovery contract")
def test_adopted_scan_failure_preserves_child_seen_in_same_iteration(monkeypatch) -> None:
    baseline_pid = 81501
    child_pid = 81502
    root_scans = 0
    cleanup_calls = []
    real_terminate = check_runtime._terminate_and_reap

    monkeypatch.setattr(check_runtime, "_enable_linux_subreaper", lambda: True)

    def discover(pid):
        nonlocal root_scans
        if pid != os.getpid():
            return {child_pid}
        root_scans += 1
        return (
            {baseline_pid} if root_scans == 1
            else check_runtime._DescendantDiscoveryError(set(), "test_unavailable")
        )

    def terminate(proc, descendants=None, *, baseline=None, discover=False):
        cleanup_calls.append((set(descendants or ()), set(baseline or ()), discover))
        return real_terminate(proc, descendants, baseline=baseline, discover=False)

    monkeypatch.setattr(check_runtime, "_posix_descendants", discover)
    monkeypatch.setattr(check_runtime, "_terminate_and_reap", terminate)
    result = check_runtime.run_bounded(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        phase="stdlib_test", capture_output=True, timeout_seconds=2,
    )
    assert result.reason is check_runtime.CommandReason.CONTAINMENT_UNAVAILABLE
    assert cleanup_calls[-1] == ({child_pid}, {baseline_pid}, False)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux descendant discovery contract")
def test_partial_descendant_error_is_cleaned_by_capture_caller(monkeypatch) -> None:
    baseline_pid = 81701
    safe_child_pids = []
    cleanup_calls = []
    real_terminate = check_runtime._terminate_and_reap
    monkeypatch.setattr(check_runtime, "_enable_linux_subreaper", lambda: True)

    def discover(pid):
        if pid == os.getpid():
            return {baseline_pid}
        safe_child_pids.append(pid)
        return check_runtime._DescendantDiscoveryError(
            {pid}, "descendant_namespace_identity_unavailable",
        )

    def terminate(proc, descendants=None, *, baseline=None, discover=False):
        cleanup_calls.append((set(descendants or ()), set(baseline or ()), discover))
        return real_terminate(proc, descendants, baseline=baseline, discover=False)

    monkeypatch.setattr(check_runtime, "_posix_descendants", discover)
    monkeypatch.setattr(check_runtime, "_terminate_and_reap", terminate)
    result = check_runtime.run_bounded(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        phase="stdlib_test", capture_output=True, timeout_seconds=2,
    )
    assert result.reason is check_runtime.CommandReason.CONTAINMENT_UNAVAILABLE
    assert cleanup_calls == [({safe_child_pids[0]}, {baseline_pid}, False)]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux descendant discovery contract")
def test_partial_leader_scan_still_combines_safe_adopted_scan(monkeypatch) -> None:
    baseline_pid = 91001
    partial_pid = 91002
    adopted_pid = 91003
    root_scans = 0
    cleanup_calls = []
    monkeypatch.setattr(check_runtime, "_enable_linux_subreaper", lambda: True)

    def discover(pid):
        nonlocal root_scans
        if pid != os.getpid():
            return check_runtime._DescendantDiscoveryError({partial_pid}, "partial")
        root_scans += 1
        return {baseline_pid} if root_scans == 1 else {baseline_pid, adopted_pid}

    def terminate(proc, descendants=None, *, baseline=None, discover=False):
        cleanup_calls.append((set(descendants or ()), set(baseline or ()), discover))
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=2)
        return True

    monkeypatch.setattr(check_runtime, "_posix_descendants", discover)
    monkeypatch.setattr(check_runtime, "_terminate_and_reap", terminate)
    result = check_runtime.run_bounded(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        phase="stdlib_test", capture_output=True, timeout_seconds=2,
    )
    assert result.reason is check_runtime.CommandReason.CONTAINMENT_UNAVAILABLE
    assert cleanup_calls == [({partial_pid, adopted_pid}, {baseline_pid}, False)]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux descendant discovery contract")
def test_finished_leader_still_runs_known_cleanup_when_final_discovery_fails(monkeypatch) -> None:
    baseline_pid = 82001
    root_scans = 0
    cleanup_calls = []

    class FinishedProcess:
        pid = 82002
        returncode = 0

        @staticmethod
        def poll():
            return 0

    proc = FinishedProcess()

    def discover(pid):
        nonlocal root_scans
        assert pid == os.getpid()
        root_scans += 1
        return (
            {baseline_pid} if root_scans == 1
            else check_runtime._DescendantDiscoveryError(set(), "test_unavailable")
        )

    def terminate(observed_proc, descendants=None, *, baseline=None, discover=False):
        cleanup_calls.append((observed_proc, set(descendants or ()), set(baseline or ()), discover))
        return True

    monkeypatch.setattr(check_runtime, "_enable_linux_subreaper", lambda: True)
    monkeypatch.setattr(check_runtime, "_posix_descendants", discover)
    monkeypatch.setattr(check_runtime.subprocess, "Popen", lambda *_args, **_kwargs: proc)
    monkeypatch.setattr(check_runtime, "_terminate_and_reap", terminate)

    result = check_runtime.run_bounded(
        [sys.executable, "-c", "pass"], phase="stdlib_test", timeout_seconds=2,
    )

    assert result.reason is check_runtime.CommandReason.CONTAINMENT_UNAVAILABLE
    assert cleanup_calls == [(proc, set(), {baseline_pid}, False)]


def test_non_linux_uses_portable_process_group_containment(monkeypatch) -> None:
    monkeypatch.setattr(check_runtime.sys, "platform", "darwin")
    result = check_runtime.run_bounded([sys.executable, "-c", "pass"], phase="stdlib_test")
    assert result.returncode == 0
    assert result.reason is check_runtime.CommandReason.OK


@pytest.mark.skipif(os.name == "nt", reason="Linux NSpid liveness contract")
def test_nspid_liveness_unavailable_is_not_treated_as_dead(monkeypatch) -> None:
    monkeypatch.setattr(check_runtime, "_pid_is_running", lambda _pid: None)
    assert check_runtime._surviving_descendants({12345}) is None
