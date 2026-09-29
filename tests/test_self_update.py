from simplicio_loop import self_update as su


def test_parse_and_compare():
    assert su.parse_version("v3.43.17") == (3, 43, 17)
    assert su.parse_version("simplicio-loop v3.44.0") == (3, 44, 0)
    assert su.parse_version("3.43.17") > su.parse_version("3.43.9")


def test_check_only_reports_without_installing(capsys):
    calls = []
    rc = su.run_update(check=True, installed="3.43.16", fetch=lambda: "v3.43.17",
                       runner=lambda cmd: calls.append(cmd) or 0, editable=False)
    assert rc == 0 and calls == []
    assert "3.43.16 -> 3.43.17" in capsys.readouterr().out


def test_up_to_date_is_noop(capsys):
    calls = []
    rc = su.run_update(installed="3.43.17", fetch=lambda: "v3.43.17",
                       runner=lambda cmd: calls.append(cmd) or 0, editable=False, legacy=[])
    assert rc == 0 and calls == []
    assert "up to date" in capsys.readouterr().out


def test_update_installs_tag_then_refreshes_global():
    calls = []
    rc = su.run_update(installed="3.43.16", fetch=lambda: "v3.43.17",
                       runner=lambda cmd: calls.append(cmd) or 0, editable=False)
    assert rc == 0 and len(calls) == 2
    assert "git+https://github.com/simpletibr/simplicio-loop@v3.43.17" in calls[0][-1]
    assert calls[1][-3:] == ["simplicio_loop.cli", "install", "--global"] or "--global" in calls[1]


def test_editable_checkout_refuses(capsys):
    calls = []
    rc = su.run_update(installed="3.43.16", fetch=lambda: "v3.43.17",
                       runner=lambda cmd: calls.append(cmd) or 0, editable=True)
    assert rc == 2 and calls == []
    assert "git pull" in capsys.readouterr().out


def test_fetch_failure_fails_closed(capsys):
    def boom():
        raise OSError("offline")
    rc = su.run_update(installed="3.43.16", fetch=boom, runner=lambda c: 0, editable=False)
    assert rc == 1


def test_update_retires_legacy_standalone_distributions_before_installing():
    # simplicio-cli / simplicio-mapper wrote the same paths the single wheel now owns;
    # uninstalling them AFTER the install would delete the new files.
    calls = []
    rc = su.run_update(installed="3.43.16", fetch=lambda: "v3.44.0",
                       runner=lambda cmd: calls.append(cmd) or 0, editable=False,
                       legacy=["simplicio-cli", "simplicio-mapper"])
    assert rc == 0 and len(calls) == 3
    assert calls[0][3:] == ["uninstall", "-y", "simplicio-cli", "simplicio-mapper"]
    assert "install" in calls[1] and "--upgrade" in calls[1]


def test_legacy_uninstall_failure_stops_before_install():
    calls = []
    rc = su.run_update(installed="3.43.16", fetch=lambda: "v3.44.0",
                       runner=lambda cmd: calls.append(cmd) or 1, editable=False,
                       legacy=["simplicio-cli"])
    assert rc == 1 and len(calls) == 1


def test_up_to_date_with_legacy_distributions_repairs_them(capsys):
    calls = []
    rc = su.run_update(installed="3.44.1", fetch=lambda: "v3.44.1",
                       runner=lambda cmd: calls.append(cmd) or 0, editable=False,
                       legacy=["simplicio-cli", "simplicio-mapper"])
    assert rc == 0 and len(calls) == 2
    assert calls[0][3:] == ["uninstall", "-y", "simplicio-cli", "simplicio-mapper"]
    assert "--force-reinstall" in calls[1] and "--no-deps" in calls[1]
    assert calls[1][-1].endswith("@v3.44.1")
