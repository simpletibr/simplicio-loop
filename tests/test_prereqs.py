"""prereqs (#1588): what is checked, and that nothing is installed except in the safe ways."""
from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import time
import tomllib
import zipfile
from pathlib import Path

import pytest

from simplicio_loop import prereqs

REPO = Path(__file__).resolve().parents[1]
PY = "/fake/python3.12"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX sh scripts and modes")


class World:
    """Fake `which` and `run`: tools maps a program name to its version text; every command run is recorded."""

    def __init__(self, **tools):
        self.tools = {"python3": "Python 3.12.1", "git": "git version 2.43.0", "gh": "gh version 2.60.0 (2024-11-01)",
                      "bwrap": "bubblewrap 0.8.0", "uv": "uv 0.5.1", "apt-get": "x", "sudo": ""}
        self.tools.update({k.replace("_", "-"): v for k, v in tools.items()})
        self.tools = {k: v for k, v in self.tools.items() if v is not None}
        self.calls, self.exit = [], {}

    def which(self, name):
        return f"/fake/bin/{name}" if name in self.tools else None

    def run(self, argv, timeout):
        argv = list(argv)
        self.calls.append(argv)
        name = os.path.basename(argv[0])
        key = " ".join(argv)
        if key in self.exit:
            return self.exit[key]
        if argv[0] == PY:
            return (0, "Python 3.12.1") if argv[1] == "--version" else (0, "pip 24.0 from /x/pip (python 3.12)")
        if name == "uv" and argv[1:3] == ["python", "find"]:
            return (1, "")
        return (0, self.tools.get(name, "")) if name in self.tools else (None, "")

    def ran(self, *prefix):
        return [call for call in self.calls if call[: len(prefix)] == list(prefix)]


def check(world, **kw):
    kw.setdefault("platform", "linux")
    kw.setdefault("interpreter", PY)
    return {c.name: c for c in prereqs.check_all({"PATH": ""}, which=world.which, run=world.run, **kw)}


@pytest.fixture(autouse=True)
def not_root(monkeypatch):
    monkeypatch.setattr(prereqs, "_is_root", lambda: False)


# --- check_all ------------------------------------------------------------------------------------------------------


def test_the_minimum_python_is_the_one_in_pyproject():
    declared = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["requires-python"]
    assert declared == f">={prereqs.MIN_PYTHON[0]}.{prereqs.MIN_PYTHON[1]}"


def test_everything_present_is_ok_with_versions_and_paths():
    checks = check(World())
    assert [c.name for c in checks.values()] == ["python", "pip", "venv", "git", "gh", "bwrap", "uv"]
    assert all(c.status == "ok" and c.fix == "" for c in checks.values())
    assert (checks["python"].path, checks["python"].version) == (PY, "3.12.1")
    assert (checks["git"].version, checks["gh"].version, checks["bwrap"].version, checks["pip"].version) == (
        "2.43.0", "2.60.0", "0.8.0", "24.0")
    assert checks["gh"].path == "/fake/bin/gh" and checks["uv"].required is False


def test_bwrap_is_a_linux_check_and_node_is_asked_only_for_hosts_that_need_it():
    assert "bwrap" not in check(World(), platform="darwin") and "node" not in check(World())
    ok = check(World(node="v20.11.0"), node_for=["gemini"])["node"]
    assert (ok.status, ok.version, ok.required) == ("ok", "20.11.0", True)
    old = check(World(node="v16.20.2"), node_for=["gemini"])["node"]
    assert old.status == "outdated" and old.minimum == "18" and "gemini" in old.fix
    gone = check(World(node=None), node_for=["gemini", "amp"])["node"]
    assert gone.status == "missing" and "gemini, amp" in gone.fix


def test_python_missing_or_too_old_names_the_uv_fix_and_makes_uv_required():
    world = World(python3="Python 3.9.2")
    python = check(world, interpreter=None)
    assert (python["python"].status, python["python"].version, python["python"].auto) == ("outdated", "3.9.2", "user")
    assert python["python"].fix == "uv python install 3.11" and python["uv"].required is True
    assert check(World(python3=None), interpreter=None)["python"].status == "missing"
    assert check(World(python3=None, python="Python 3.11.4"), interpreter=None)["python"].path == "/fake/bin/python"


def test_a_python_that_uv_installed_counts_even_when_it_is_not_on_path():
    world = World(python3=None)
    world.exit["/fake/bin/uv python find >=3.11"] = (0, "/home/u/.local/share/uv/python/cpython-3.12/bin/python3\n")
    world.exit["/home/u/.local/share/uv/python/cpython-3.12/bin/python3 --version"] = (0, "Python 3.12.7")
    python = check(world, interpreter=None)["python"]
    assert (python.status, python.version) == ("ok", "3.12.7") and python.path.endswith("/bin/python3")


def test_uv_is_not_asked_when_a_good_python_is_already_there():
    world = World()
    check(world)
    assert world.ran("/fake/bin/uv", "python") == []


def test_pip_and_venv_missing_give_the_package_manager_command():
    world = World()
    world.exit[f"{PY} -m pip --version"] = (1, "No module named pip")
    world.exit[f"{PY} -c import venv, ensurepip"] = (1, "")
    checks = check(world)
    assert checks["pip"].status == checks["venv"].status == "missing"
    assert checks["pip"].fix == "sudo apt-get install -y python3-pip" and checks["venv"].fix == "sudo apt-get install -y python3-venv"
    no_apt = World(**{"apt-get": None, "dnf": "x"})
    no_apt.exit.update(world.exit)
    assert check(no_apt)["venv"].fix == "install venv with your system package manager"  # Fedora ships venv with python3
    assert not {"pip", "venv"} & set(check(World(python3=None), interpreter=None))  # no python: nothing to ask


def test_missing_system_tools_name_the_exact_command_and_root_needs_no_sudo(monkeypatch):
    world = World(git=None, bwrap=None)
    checks = check(world)
    assert checks["git"].fix == "sudo apt-get install -y git" and checks["bwrap"].fix == "sudo apt-get install -y bubblewrap"
    assert checks["git"].auto == "system" and checks["git"].status == "missing" and checks["git"].path is None
    monkeypatch.setattr(prereqs, "_is_root", lambda: True)
    assert check(world)["git"].fix == "apt-get install -y git"
    nothing = World(git=None, **{"apt-get": None})
    assert check(nothing)["git"].fix == "install git with your system package manager"


def test_a_tool_whose_version_command_hangs_is_still_found():
    world = World()
    world.exit["/fake/bin/gh --version"] = (None, "")
    gh = check(world)["gh"]
    assert (gh.status, gh.version, gh.path) == ("ok", None, "/fake/bin/gh")


def test_gh_and_uv_missing_say_how_to_get_them():
    checks = check(World(gh=None, uv=None))
    assert checks["gh"].auto == "user" and "simplicio-loop setup" in checks["gh"].fix and "https://cli.github.com" in checks["gh"].fix
    assert checks["uv"].status == "missing" and checks["uv"].required is False


@pytest.mark.parametrize("platform, which, manager", [
    ("linux", {"apt-get": 1}, "apt"), ("linux", {"dnf": 1, "pacman": 1}, "dnf"), ("linux", {"pacman": 1}, "pacman"),
    ("darwin", {"brew": 1}, "brew"), ("win32", {"winget": 1}, "winget"), ("linux", {"brew": 1}, None), ("freebsd", {"pkg": 1}, None),
])
def test_package_manager(platform, which, manager):
    assert prereqs.package_manager(which=lambda name: name if name in which else None, platform=platform) == manager


@pytest.mark.parametrize("manager, packages, argv", [
    ("apt", ["git", "bwrap"], ["apt-get", "install", "-y", "git", "bubblewrap"]),
    ("dnf", ["git"], ["dnf", "install", "-y", "git"]),
    ("pacman", ["bwrap"], ["pacman", "-S", "--needed", "--noconfirm", "bubblewrap"]),
    ("brew", ["git"], ["brew", "install", "git"]),
    ("winget", ["git"], ["winget", "install", "-e", "--id", "Git.Git"]),
    ("brew", ["bwrap"], []), ("winget", ["bwrap"], []),
])
def test_system_command(manager, packages, argv):
    assert prereqs.system_command(manager, packages) == argv


# --- ensure: system packages ----------------------------------------------------------------------------------------


def ensure(world, checks=None, **kw):
    kw.setdefault("platform", "linux")
    kw.setdefault("machine", "x86_64")
    kw.setdefault("bin_dir", Path("/nonexistent/bin"))
    checks = checks if checks is not None else list(check(world).values())
    return prereqs.ensure(checks, environ={"PATH": ""}, which=world.which, run=world.run, **kw)


def test_without_yes_a_system_package_is_only_named_and_nothing_runs():
    world = World(git=None, bwrap=None)
    actions = ensure(world)
    assert [(a.name, a.result, a.detail) for a in actions] == [
        ("git", "skipped", "sudo apt-get install -y git bubblewrap"), ("bwrap", "skipped", "sudo apt-get install -y git bubblewrap")]
    assert world.ran("sudo") == [] and world.ran("apt-get") == []


def test_yes_with_a_sudo_that_needs_a_password_still_runs_nothing():
    world = World(git=None)
    world.exit["sudo -n true"] = (1, "a password is required")
    actions = ensure(world, yes=True)
    assert [(a.result, a.detail) for a in actions] == [("skipped", "sudo apt-get install -y git")]
    assert world.ran("sudo") == [["sudo", "-n", "true"]] and world.ran("apt-get") == [] and world.ran("sudo", "-n", "apt-get") == []


def test_yes_with_sudo_n_installs_with_sudo_n_after_probing_it():
    world = World(git=None)
    actions = ensure(world, yes=True)
    assert [(a.result, a.detail) for a in actions] == [("installed", "sudo apt-get install -y git")]
    assert world.ran("sudo") == [["sudo", "-n", "true"], ["sudo", "-n", "apt-get", "install", "-y", "git"]]


def test_yes_as_root_runs_the_manager_directly(monkeypatch):
    monkeypatch.setattr(prereqs, "_is_root", lambda: True)
    world = World(git=None)
    assert ensure(world, yes=True)[0].result == "installed"
    assert world.ran("sudo") == [] and world.ran("apt-get") == [["apt-get", "install", "-y", "git"]]


@pytest.mark.parametrize("manager, argv_full, argv_display", [
    ("dnf", ["sudo", "-n", "dnf", "install", "-y", "git"], "sudo dnf install -y git"),
    ("pacman", ["sudo", "-n", "pacman", "-S", "--needed", "--noconfirm", "git"], "sudo pacman -S --needed --noconfirm git"),
])
def test_yes_with_sudo_n_installs_with_sudo_n_for_dnf_and_pacman(manager, argv_full, argv_display):
    world = World(git=None, **{"apt-get": None, manager: "x"})
    actions = ensure(world, yes=True)
    assert [(a.result, a.detail) for a in actions] == [("installed", argv_display)]
    assert world.ran("sudo") == [["sudo", "-n", "true"], argv_full]


@pytest.mark.parametrize("manager, argv_direct", [
    ("dnf", ["dnf", "install", "-y", "git"]),
    ("pacman", ["pacman", "-S", "--needed", "--noconfirm", "git"]),
])
def test_yes_as_root_runs_manager_directly_for_dnf_and_pacman(monkeypatch, manager, argv_direct):
    monkeypatch.setattr(prereqs, "_is_root", lambda: True)
    world = World(git=None, **{"apt-get": None, manager: "x"})
    assert ensure(world, yes=True)[0].result == "installed"
    assert world.ran("sudo") == [] and world.ran(argv_direct[0]) == [argv_direct]


@pytest.mark.parametrize("manager, shown", [("dnf", "sudo dnf install -y git"), ("pacman", "sudo pacman -S --needed --noconfirm git")])
def test_without_yes_dnf_and_pacman_only_name_the_full_command_and_run_nothing(manager, shown):
    world = World(git=None, **{"apt-get": None, manager: "x"})
    assert [(a.result, a.detail) for a in ensure(world)] == [("skipped", shown)]
    assert world.ran("sudo") == [] and world.ran(manager) == []


def test_brew_and_winget_never_use_sudo():
    world = World(git=None, **{"apt-get": None, "brew": "x"})
    assert ensure(world, yes=True, platform="darwin")[0].result == "installed"
    assert world.ran("sudo") == [] and world.ran("brew") == [["brew", "install", "git"]]


def test_a_failed_package_install_is_reported_not_hidden():
    world = World(git=None)
    world.exit["sudo -n apt-get install -y git"] = (100, "E: lock")
    action = ensure(world, yes=True)[0]
    assert action.result == "failed" and "exit 100" in action.detail and "E: lock" not in action.detail


def test_dry_run_runs_nothing_even_with_yes():
    world = World(git=None, gh=None, python3=None)
    checks = list(check(world, interpreter=None).values())
    world.calls.clear()

    def no_network(url):
        raise AssertionError(f"dry run downloaded {url}")

    actions = {a.name: a for a in ensure(world, checks, yes=True, dry_run=True, get=no_network)}
    assert {name: a.result for name, a in actions.items()} == {"python": "would-install", "gh": "would-install", "git": "would-install"}
    assert world.calls == []
    assert {a.result for a in ensure(world, checks, dry_run=True, get=no_network) if a.name == "git"} == {"skipped"}


def test_ok_checks_and_optional_missing_tools_need_no_action():
    assert ensure(World()) == []
    assert ensure(World(uv=None)) == []


def test_pip_venv_and_node_are_never_installed_only_explained():
    world = World(node=None)
    world.exit[f"{PY} -m pip --version"] = (1, "")
    actions = ensure(world, list(check(world, node_for=["gemini"]).values()))
    assert {a.name: a.result for a in actions} == {"pip": "skipped", "node": "skipped"}
    assert world.ran("sudo") == [] and world.ran("apt-get") == []


# --- ensure: gh, uv and python from their releases ---------------------------------------------------------------------


def make_archive(name, member, data=b"#!/bin/sh\necho tool\n"):
    buffer = io.BytesIO()
    if name.endswith(".zip"):
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(member, data)
    else:
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            info = tarfile.TarInfo(member)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class Releases:
    """Fake GitHub: the latest-release answers and the archives, checksums included. `asked` lists every URL."""

    def __init__(self, repo, tag, archive, sums_name, member, *, per_asset_sums=False, corrupt=False):
        base = f"https://github.com/{repo}/releases/download/{tag}/"
        blob = make_archive(archive, member)
        digest = hashlib.sha256(b"other" if corrupt else blob).hexdigest()
        self.files = {f"https://api.github.com/repos/{repo}/releases/latest": json.dumps({"tag_name": tag}).encode(),
                      base + archive: blob, base + sums_name: f"{digest}  {archive}\n".encode()}
        self.asked = []

    def __call__(self, url):
        self.asked.append(url)
        return self.files[url]


GH_CASES = [
    ("linux", "x86_64", "gh_2.60.0_linux_amd64.tar.gz", "gh_2.60.0_linux_amd64/bin/gh"),
    ("linux", "aarch64", "gh_2.60.0_linux_arm64.tar.gz", "gh_2.60.0_linux_arm64/bin/gh"),
    ("darwin", "arm64", "gh_2.60.0_macOS_arm64.zip", "gh_2.60.0_macOS_arm64/bin/gh"),
    ("win32", "AMD64", "gh_2.60.0_windows_amd64.zip", "gh_2.60.0_windows_amd64/bin/gh.exe"),
]


@pytest.mark.parametrize("platform, machine, archive, member", GH_CASES)
def test_gh_comes_from_the_official_release_with_its_checksum(tmp_path, platform, machine, archive, member):
    web = Releases("cli/cli", "v2.60.0", archive, "gh_2.60.0_checksums.txt", member)
    world = World(gh=None)
    bin_dir = tmp_path / "home" / ".local" / "bin"
    actions = ensure(world, get=web, bin_dir=bin_dir, platform=platform, machine=machine)
    name = "gh.exe" if platform == "win32" else "gh"
    assert [(a.name, a.result) for a in actions] == [("gh", "installed")] and "SHA256 checked" in actions[0].detail
    assert os.listdir(bin_dir) == [name] and os.access(bin_dir / name, os.X_OK) or platform == "win32"
    assert web.asked[-2:] == [f"https://github.com/cli/cli/releases/download/v2.60.0/{a}" for a in
                              ("gh_2.60.0_checksums.txt", archive)]


@pytest.mark.parametrize("platform, machine, archive, member", [
    ("linux", "x86_64", "uv-x86_64-unknown-linux-gnu.tar.gz", "uv-x86_64-unknown-linux-gnu/uv"),
    ("linux", "aarch64", "uv-aarch64-unknown-linux-gnu.tar.gz", "uv-aarch64-unknown-linux-gnu/uv"),
    ("darwin", "arm64", "uv-aarch64-apple-darwin.tar.gz", "uv-aarch64-apple-darwin/uv"),
    ("win32", "AMD64", "uv-x86_64-pc-windows-msvc.zip", "uv.exe"),
])
def test_python_installs_uv_first_from_its_release_then_runs_uv_python_install(tmp_path, platform, machine, archive, member):
    web = Releases("astral-sh/uv", "v0.5.1", archive, archive + ".sha256", member)
    world = World(python3=None, uv=None)
    checks = list(check(world, interpreter=None).values())
    bin_dir = tmp_path / "bin"
    uv = str(bin_dir / ("uv.exe" if platform == "win32" else "uv"))
    world.exit[f"{uv} python install 3.11"] = (0, "")
    world.exit[f"{uv} python find 3.11"] = (0, "/u/python3.11\n")
    actions = ensure(world, checks, get=web, bin_dir=bin_dir, platform=platform, machine=machine)
    assert [(a.name, a.result) for a in actions] == [("uv", "installed"), ("python", "installed")]
    assert actions[1].detail == "/u/python3.11" and world.ran(uv) == [[uv, "python", "install", "3.11"], [uv, "python", "find", "3.11"]]


def test_python_with_uv_already_there_downloads_nothing():
    world = World(python3=None)
    checks = list(check(world, interpreter=None).values())

    def no_network(url):
        raise AssertionError(url)

    actions = ensure(world, checks, get=no_network)
    assert [(a.name, a.result) for a in actions] == [("python", "installed")]
    assert world.ran("/fake/bin/uv", "python", "install") == [["/fake/bin/uv", "python", "install", "3.11"]]
    world.exit["/fake/bin/uv python install 3.11"] = (2, "boom")
    assert ensure(world, checks, get=no_network)[0].result == "failed"


def test_a_wrong_checksum_installs_nothing_and_says_so(tmp_path):
    archive = "gh_2.60.0_linux_amd64.tar.gz"
    web = Releases("cli/cli", "v2.60.0", archive, "gh_2.60.0_checksums.txt", "gh_2.60.0_linux_amd64/bin/gh", corrupt=True)
    actions = ensure(World(gh=None), get=web, bin_dir=tmp_path / "bin")
    assert (actions[0].result, actions[0].detail.split(":")[0]) == ("failed", "checksum_mismatch")
    assert not (tmp_path / "bin").exists() or os.listdir(tmp_path / "bin") == []


def test_a_failed_uv_download_stops_python_before_uv_python_install(tmp_path):
    archive = "uv-x86_64-unknown-linux-gnu.tar.gz"
    web = Releases("astral-sh/uv", "v0.5.1", archive, archive + ".sha256", "uv-x86_64-unknown-linux-gnu/uv", corrupt=True)
    world = World(python3=None, uv=None)
    actions = ensure(world, list(check(world, interpreter=None).values()), get=web, bin_dir=tmp_path / "bin")
    assert [(a.name, a.result) for a in actions] == [("uv", "failed")] and world.ran(str(tmp_path / "bin" / "uv")) == []


def test_an_existing_tool_in_the_user_bin_is_never_replaced_and_costs_no_download(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text("mine")

    def no_network(url):
        raise AssertionError(url)

    actions = ensure(World(gh=None), get=no_network, bin_dir=bin_dir)
    assert [(a.name, a.result) for a in actions] == [("gh", "unchanged")] and (bin_dir / "gh").read_text() == "mine"


@pytest.mark.parametrize("answer", [b"not json", b"[]", json.dumps({"tag_name": "../../evil"}).encode(), json.dumps({}).encode()])
def test_a_release_answer_without_a_usable_tag_is_refused(tmp_path, answer):
    actions = ensure(World(gh=None), get=lambda url: answer, bin_dir=tmp_path / "bin")
    assert actions[0].result == "failed" and actions[0].detail.startswith("bad_response")


def test_an_unknown_platform_gets_no_download():
    actions = ensure(World(gh=None), platform="freebsd14", machine="x86_64", get=lambda url: 1 / 0)
    assert actions[0].result == "skipped" and "freebsd14" in actions[0].detail
    assert ensure(World(gh=None), machine="riscv64", get=lambda url: 1 / 0)[0].result == "skipped"


# --- the real runner ------------------------------------------------------------------------------------------------


def script(tmp_path, name, body):
    path = tmp_path / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return str(path)


def test_the_real_runner_merges_output_cuts_it_and_reports_none_for_a_missing_program(tmp_path):
    both = script(tmp_path, "both", "echo out; echo err >&2; exit 3")
    assert prereqs._run([both], 5) == (3, "out\nerr\n")
    big = script(tmp_path, "big", "yes x | head -c 20000")
    assert len(prereqs._run([big], 5)[1]) == 4096
    assert prereqs._run([str(tmp_path / "nope")], 5) == (None, "")


def test_the_real_runner_stops_a_hung_command(tmp_path):
    hung = script(tmp_path, "hung", "exec sleep 30")
    started = time.monotonic()
    assert prereqs._run([hung], 0.3) == (None, "")
    assert time.monotonic() - started < 5


def test_the_real_runner_never_uses_a_shell(tmp_path):
    marker = tmp_path / "marker"
    assert prereqs._run(["printf", "%s", f"a b; touch {marker} $HOME"], 5) == (0, f"a b; touch {marker} $HOME")  # one literal argument
    assert not marker.exists()


def test_the_real_runner_gives_the_probe_a_minimal_environment_without_tokens(tmp_path, monkeypatch):
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY", "SIMPLICIO_TOKEN"):
        monkeypatch.setenv(name, "ghp_FAKEFAKEFAKEFAKEFAKE0042")
    dump = script(tmp_path, "dump", "env")
    code, text = prereqs._run([dump], 5)
    names = {line.split("=", 1)[0] for line in text.splitlines()}
    assert code == 0 and {"PATH", "HOME"} <= names
    assert not names & {"GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY", "SIMPLICIO_TOKEN"}
    assert "ghp_FAKE" not in text


def test_check_all_probes_a_tool_found_on_path_without_the_token_in_its_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_FAKEFAKEFAKEFAKEFAKE0042")
    seen = tmp_path / "probe-env.txt"
    (tmp_path / "bin").mkdir()
    script(tmp_path / "bin", "gh", f"env > {seen}\necho 'gh version 2.60.0 (2024-11-01)'")
    checks = {c.name: c for c in prereqs.check_all({"PATH": str(tmp_path / "bin")}, platform="linux")}
    assert checks["gh"].status == "ok" and checks["gh"].version == "2.60.0"
    assert seen.exists() and "GH_TOKEN" not in seen.read_text()


def test_a_release_download_that_answers_3xx_without_location_is_a_failed_action_not_an_exception(tmp_path, monkeypatch):
    import httpx

    from simplicio_loop import release_fetch

    def answer(request):
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={"tag_name": "v2.60.0"})
        return httpx.Response(302)  # no Location

    monkeypatch.setattr(release_fetch, "_transport", httpx.MockTransport(answer))
    gh = prereqs.Check(name="gh", status="missing", required=True, path=None, version=None, minimum=None, fix="", auto="user")
    actions = prereqs.ensure([gh], environ={"HOME": str(tmp_path)}, bin_dir=tmp_path / "bin", platform="linux", machine="x86_64")
    assert [(a.name, a.result) for a in actions] == [("gh", "failed")]
    assert actions[0].detail.startswith("unsafe_url:") and not (tmp_path / "bin").exists()
