import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "check_e2e_installed.py")
FIXTURE_MEASURED = os.path.join(
    REPO, "contracts", "e2e-demo", "v1", "fixtures", "fully-measured", "events.jsonl")
FIXTURE_SIMULATED = os.path.join(
    REPO, "contracts", "e2e-demo", "v1", "fixtures", "simulated-hop", "events.jsonl")


def _shim(path, body):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    if os.name != "nt":
        os.chmod(path, 0o755)


def _fake_bin_dir(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    ext = ".cmd" if os.name == "nt" else ""
    mapper = "@echo off\necho Usage: simplicio-mapper inspect handoff ask sync drift\n"
    devcli = "@echo off\necho Usage: simplicio-dev-cli edit --plan --apply --dry-run --json\n"
    loop = "@echo off\necho Usage: simplicio-loop install doctor dashboard\n"
    if os.name != "nt":
        mapper = "#!/bin/sh\necho 'Usage: simplicio-mapper inspect handoff ask sync drift'\n"
        devcli = "#!/bin/sh\necho 'Usage: simplicio-dev-cli edit --plan --apply --dry-run --json'\n"
        loop = "#!/bin/sh\necho 'Usage: simplicio-loop install doctor dashboard'\n"
    _shim(bindir / ("simplicio-mapper" + ext), mapper)
    _shim(bindir / ("simplicio-dev-cli" + ext), devcli)
    _shim(bindir / ("simplicio-loop" + ext), loop)
    return bindir


def test_check_e2e_installed_selftest():
    r = subprocess.run([sys.executable, SCRIPT, "selftest"], capture_output=True, text=True,
                       cwd=REPO, timeout=30, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout, r.stdout


def test_probe_passes_with_bins_and_measured_fixture(tmp_path):
    bindir = _fake_bin_dir(tmp_path)
    env = dict(os.environ)
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    r = subprocess.run([sys.executable, SCRIPT, "probe", "--events", FIXTURE_MEASURED, "--json",
                        "--isolate-path", str(bindir)],
                       capture_output=True, text=True, cwd=REPO, timeout=30,
                       stdin=subprocess.DEVNULL, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    body = json.loads(r.stdout)
    assert body["ok"] is True
    assert all(row["ok"] for row in body["bins"])


def test_probe_fails_when_any_standin_remains(tmp_path):
    bindir = _fake_bin_dir(tmp_path)
    env = dict(os.environ)
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    r = subprocess.run([sys.executable, SCRIPT, "probe", "--events", FIXTURE_SIMULATED, "--json",
                        "--isolate-path", str(bindir)],
                       capture_output=True, text=True, cwd=REPO, timeout=30,
                       stdin=subprocess.DEVNULL, env=env)
    assert r.returncode == 2, r.stdout + r.stderr
    body = json.loads(r.stdout)
    assert body["ok"] is False
    assert body["audit"]["simulated"] == ["edit"]


def test_probe_fails_when_loop_bin_missing(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    ext = ".cmd" if os.name == "nt" else ""
    if os.name == "nt":
        _shim(bindir / ("simplicio-mapper" + ext),
              "@echo off\necho Usage: simplicio-mapper inspect handoff ask sync drift\n")
        _shim(bindir / ("simplicio-dev-cli" + ext),
              "@echo off\necho Usage: simplicio-dev-cli edit --plan --apply --dry-run --json\n")
    else:
        _shim(bindir / ("simplicio-mapper" + ext),
              "#!/bin/sh\necho 'Usage: simplicio-mapper inspect handoff ask sync drift'\n")
        _shim(bindir / ("simplicio-dev-cli" + ext),
              "#!/bin/sh\necho 'Usage: simplicio-dev-cli edit --plan --apply --dry-run --json'\n")
    env = dict(os.environ)
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    r = subprocess.run([sys.executable, SCRIPT, "probe", "--events", FIXTURE_MEASURED, "--json",
                        "--isolate-path", str(bindir)],
                       capture_output=True, text=True, cwd=REPO, timeout=30,
                       stdin=subprocess.DEVNULL, env=env)
    assert r.returncode == 2, r.stdout + r.stderr
    body = json.loads(r.stdout)
    assert body["ok"] is False
    missing = [row for row in body["bins"] if row["name"] == "simplicio-loop"][0]
    assert missing["reason"] in ("missing-on-path", "resolved-outside-isolated-path")
