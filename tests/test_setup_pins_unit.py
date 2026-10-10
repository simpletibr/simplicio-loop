"""Pinned gh and uv releases of `setup` (#1657, point 5), and the proxy and CA settings of install commands.

Fake GitHub only: no test here reaches the network. The archives are bytes that nothing opens unless a test says so.
"""
from __future__ import annotations

import hashlib
import io
import os
import tarfile

import pytest

from simplicio_loop import prereqs, release_fetch, setup_cli, setup_hardening, setup_pins
from tests.setup_wizard.fakes import Fakes

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX sh scripts and modes")

TAG = "v2.60.0"
ARCHIVE = "gh_2.60.0_linux_amd64.tar.gz"
MEMBER = "gh_2.60.0_linux_amd64/bin/gh"
BASE = f"https://github.com/cli/cli/releases/download/{TAG}/"


def tar_gz(member, data):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo(member)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class Web:
    """A fake GitHub: `files` maps each URL to its bytes; `asked` lists every URL requested, in order."""

    def __init__(self, files):
        self.files, self.asked = files, []

    def __call__(self, url):
        self.asked.append(url)
        if url not in self.files:
            raise AssertionError(f"unexpected request {url}")
        return self.files[url]


def gh_release(blob, published=None):
    """The release TAG for linux amd64. The checksums file names `published` (default: the bytes of `blob`)."""
    digest = hashlib.sha256(blob).hexdigest() if published is None else published
    return {BASE + ARCHIVE: blob, BASE + "gh_2.60.0_checksums.txt": f"{digest}  {ARCHIVE}\n".encode()}


def pins_for(sha, *, tag=TAG, archive=ARCHIVE, system="linux", arch="amd64"):
    return {"schema": setup_pins.SCHEMA, "gh": {"tag": tag, "assets": {f"{system}-{arch}": {"archive": archive, "sha256": sha}}},
            "uv": {"tag": None, "assets": {}}}


def missing_gh():
    return prereqs.Check(name="gh", status="missing", required=True, path=None, version=None, minimum=None, fix="", auto="user")


def install_gh(tmp_path, web, pins, platform="linux", machine="x86_64"):
    return prereqs.ensure([missing_gh()], get=web, bin_dir=tmp_path / "bin", platform=platform, machine=machine, pins=pins,
                          environ={"PATH": ""}, run=lambda argv, timeout: (0, ""))


def test_the_shipped_pins_file_has_gh_and_uv_slots_and_each_pinned_archive_has_its_release_name():
    doc = setup_pins.load()
    assert doc["schema"] == setup_pins.SCHEMA and set(doc) == {"schema", "gh", "uv"}
    for tool in ("gh", "uv"):
        assert set(doc[tool]) == {"tag", "assets"}
        for key, asset in doc[tool]["assets"].items():
            system, arch = key.split("-")
            assert asset["archive"] == prereqs._release_files(tool, doc[tool]["tag"], system, arch)[0]


def test_a_pinned_gh_installs_the_pinned_release_and_never_asks_github_for_the_latest_one(tmp_path):
    script = b"#!/bin/sh\necho gh\n"
    blob = tar_gz(MEMBER, script)
    web = Web(gh_release(blob))
    actions = install_gh(tmp_path, web, pins_for(hashlib.sha256(blob).hexdigest()))
    assert [(a.name, a.result) for a in actions] == [("gh", "installed")] and "SHA256 pinned" in actions[0].detail
    assert actions[0].sha256 == hashlib.sha256(script).hexdigest()
    assert all("api.github.com" not in url for url in web.asked) and web.asked[0] == BASE + "gh_2.60.0_checksums.txt"


def test_a_release_that_matches_its_own_checksums_but_not_the_pin_is_refused_before_the_archive_is_opened(tmp_path, monkeypatch):
    pinned = tar_gz(MEMBER, b"#!/bin/sh\necho good\n")
    tampered = tar_gz(MEMBER, b"#!/bin/sh\necho evil\n")
    web = Web(gh_release(tampered))  # the release's own checksums file agrees with the tampered archive

    def opened(*args):
        raise AssertionError("the archive was opened")

    monkeypatch.setattr(release_fetch, "_read_member", opened)
    actions = install_gh(tmp_path, web, pins_for(hashlib.sha256(pinned).hexdigest()))
    assert [(a.name, a.result) for a in actions] == [("gh", "failed")] and actions[0].detail.startswith("pin_mismatch")
    assert not (tmp_path / "bin").exists()


def test_a_tool_or_platform_without_a_pin_is_skipped_and_nothing_is_downloaded(tmp_path):
    def no_network(url):
        raise AssertionError(url)

    actions = install_gh(tmp_path, no_network, pins_for("0" * 64, system="linux", arch="arm64"))
    assert [(a.name, a.result) for a in actions] == [("gh", "skipped")] and "no pinned gh release" in actions[0].detail
    actions = install_gh(tmp_path, no_network, pins_for("0" * 64), platform="darwin", machine="arm64")
    assert [(a.name, a.result) for a in actions] == [("gh", "skipped")] and "macos-arm64" in actions[0].detail
    unpinned = {"schema": setup_pins.SCHEMA, "gh": {"tag": None, "assets": {}}, "uv": {"tag": None, "assets": {}}}
    assert install_gh(tmp_path, no_network, unpinned)[0].result == "skipped"


def test_a_pin_whose_archive_name_is_not_the_one_of_its_release_is_treated_as_no_pin(tmp_path):
    def no_network(url):
        raise AssertionError(url)

    actions = install_gh(tmp_path, no_network, pins_for("0" * 64, archive="gh_2.60.0_linux_amd64.zip"))
    assert [(a.name, a.result) for a in actions] == [("gh", "skipped")] and not (tmp_path / "bin").exists()


@pytest.mark.parametrize("doc", [
    {"schema": setup_pins.SCHEMA, "gh": {"tag": TAG, "assets": {"linux-amd64": {"archive": ARCHIVE, "sha256": "not-a-digest"}}}},
    {"schema": setup_pins.SCHEMA, "gh": {"tag": "../../evil", "assets": {"linux-amd64": {"archive": ARCHIVE, "sha256": "0" * 64}}}},
    {"schema": setup_pins.SCHEMA, "gh": {"tag": TAG, "assets": {"linux-amd64": "not-an-object"}}},
    {"schema": setup_pins.SCHEMA, "gh": "not-an-object"},
])
def test_a_malformed_pin_is_treated_as_no_pin_and_nothing_is_downloaded(tmp_path, doc):
    def no_network(url):
        raise AssertionError(url)

    actions = install_gh(tmp_path, no_network, doc)
    assert [(a.name, a.result) for a in actions] == [("gh", "skipped")] and not (tmp_path / "bin").exists()


def fake_github(gh_tag="v2.61.0", uv_tag="0.6.0"):
    """Every release asset of both tools for the six platforms, each asset's bytes being its own URL.

    The checksums file of a gh release lists all its archives; a uv archive has a checksum file of its own."""
    files = {"https://api.github.com/repos/cli/cli/releases/latest": f'{{"tag_name": "{gh_tag}"}}'.encode(),
             "https://api.github.com/repos/astral-sh/uv/releases/latest": f'{{"tag_name": "{uv_tag}"}}'.encode()}
    sums: dict[str, list[str]] = {}
    for system, arch in prereqs._UV_TRIPLE:
        for tool, tag in (("gh", gh_tag), ("uv", uv_tag)):
            archive, sums_url, archive_url, _ = prereqs._release_files(tool, tag, system, arch)
            blob = archive_url.encode()
            files[archive_url] = blob
            sums.setdefault(sums_url, []).append(f"{hashlib.sha256(blob).hexdigest()}  {archive}")
    files.update({url: ("\n".join(lines) + "\n").encode() for url, lines in sums.items()})
    return files


def test_a_latest_uv_release_whose_tag_has_no_v_prefix_is_installed(tmp_path):
    archive = "uv-x86_64-unknown-linux-gnu.tar.gz"
    base = "https://github.com/astral-sh/uv/releases/download/0.6.0/"
    blob = tar_gz("uv-x86_64-unknown-linux-gnu/uv", b"#!/bin/sh\necho uv\n")
    web = Web({"https://api.github.com/repos/astral-sh/uv/releases/latest": b'{"tag_name": "0.6.0"}',
               base + archive: blob, base + archive + ".sha256": f"{hashlib.sha256(blob).hexdigest()}  {archive}\n".encode()})
    python = prereqs.Check(name="python", status="missing", required=True, path=None, version=None, minimum=None, fix="", auto="user")
    uv = prereqs.Check(name="uv", status="missing", required=False, path=None, version=None, minimum=None, fix="", auto="user")
    actions = prereqs.ensure([python, uv], get=web, bin_dir=tmp_path / "bin", platform="linux", machine="x86_64",
                             environ={"PATH": ""}, run=lambda argv, timeout: (0, ""))
    assert actions[0].name == "uv" and actions[0].result == "installed" and "0.6.0" in actions[0].detail


def test_build_pins_the_latest_releases_with_the_digests_their_checksums_publish():
    web = Web(fake_github())
    doc = setup_pins.build(web)
    assert doc["gh"]["tag"] == "v2.61.0" and doc["uv"]["tag"] == "0.6.0" and doc["schema"] == setup_pins.SCHEMA
    assert set(doc["gh"]["assets"]) == {f"{s}-{a}" for s, a in prereqs._UV_TRIPLE}
    url = "https://github.com/cli/cli/releases/download/v2.61.0/gh_2.61.0_linux_amd64.tar.gz"
    assert doc["gh"]["assets"]["linux-amd64"] == {"archive": "gh_2.61.0_linux_amd64.tar.gz",
                                                  "sha256": hashlib.sha256(url.encode()).hexdigest()}


def test_build_pins_refuses_an_archive_whose_bytes_differ_from_the_checksum_its_release_publishes():
    files = fake_github()
    sums = "https://github.com/cli/cli/releases/download/v2.61.0/gh_2.61.0_checksums.txt"
    files[sums] = f"{'0' * 64}  gh_2.61.0_linux_amd64.tar.gz\n".encode()
    with pytest.raises(setup_pins.PinError, match="does not match"):
        setup_pins.build(Web(files))


def test_setup_gives_ensure_the_pins_and_the_install_runner(monkeypatch):
    seen = []
    monkeypatch.setattr(prereqs, "install_command", lambda argv, timeout=prereqs.TIMEOUT_S: seen.append(list(argv)) or (0, "ran"))
    fakes = Fakes()
    setup_cli._prereq_step(setup_cli.Options(), {"HOME": "/h", "PATH": "/usr/bin"}, fakes.seams(), [], {})
    kwargs = next(entry[1] for entry in fakes.calls if entry[0] == "ensure")
    assert kwargs["pins"] == setup_pins.load()
    assert kwargs["run"](["tool", "x"], 5) == (0, "ran") and seen == [["tool", "x"]]


def test_ensure_runs_its_python_install_with_the_install_runner_when_no_runner_is_given(monkeypatch):
    ran = []
    monkeypatch.setattr(prereqs, "_run_install", lambda argv, timeout=prereqs.TIMEOUT_S: ran.append(list(argv)) or (0, "/u/py"))
    python = prereqs.Check(name="python", status="missing", required=True, path=None, version=None, minimum=None, fix="", auto="user")
    uv = prereqs.Check(name="uv", status="ok", required=False, path="/fake/bin/uv", version="0.6.0", minimum=None, fix="", auto="")
    actions = prereqs.ensure([python, uv], environ={"PATH": ""}, which=lambda name: None, platform="linux")
    assert [a.result for a in actions] == ["installed"] and ran[0] == ["/fake/bin/uv", "python", "install", "3.11"]


def test_the_install_environment_keeps_proxy_and_certificate_settings_and_no_credentials():
    env = setup_hardening.install_env({
        "PATH": "/usr/bin", "HOME": "/h", "HTTPS_PROXY": "http://proxy.example.invalid:3128", "SSL_CERT_FILE": "/etc/corp.pem",
        "UV_CA_CERT": "/etc/corp.pem", "GH_TOKEN": "ghp_FAKEFAKEFAKEFAKEFAKE0042", "ANTHROPIC_API_KEY": "sk-FAKE",
    })
    assert env["HTTPS_PROXY"] == "http://proxy.example.invalid:3128" and env["SSL_CERT_FILE"] == "/etc/corp.pem"
    assert env["UV_CA_CERT"] == "/etc/corp.pem" and env["PATH"] == "/usr/bin"
    assert "GH_TOKEN" not in env and "ANTHROPIC_API_KEY" not in env


def test_the_install_command_runs_with_the_proxy_and_certificates_and_never_with_a_token(tmp_path, monkeypatch):
    dump = tmp_path / "dump"
    dump.write_text("#!/bin/sh\nenv\n")
    dump.chmod(0o755)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.invalid:3128")
    monkeypatch.setenv("SSL_CERT_FILE", "/etc/corp.pem")
    monkeypatch.setenv("GH_TOKEN", "ghp_FAKEFAKEFAKEFAKEFAKE0042")
    code, text = prereqs.install_command([str(dump)], 5)
    assert code == 0 and "HTTPS_PROXY=http://proxy.example.invalid:3128" in text and "SSL_CERT_FILE=/etc/corp.pem" in text
    assert "GH_TOKEN" not in text and "ghp_FAKE" not in text
