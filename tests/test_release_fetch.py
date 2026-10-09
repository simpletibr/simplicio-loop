"""release_fetch (#1588): a binary is installed only after its SHA256 matched, and never over an existing file."""
from __future__ import annotations

import hashlib
import io
import os
import stat
import tarfile
import zipfile

import httpx
import pytest

from simplicio_loop import release_fetch
from simplicio_loop.release_fetch import FetchError

BASE = "https://github.com/cli/cli/releases/download/v1.2.3/"
ARCHIVE = "gh_1.2.3_linux_amd64.tar.gz"
MEMBER = "gh_1.2.3_linux_amd64/bin/gh"
BINARY = b"#!/bin/sh\necho gh\n"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX modes and symlinks")


def tar_bytes(members=((MEMBER, BINARY),), extra=None):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for info in extra or ():
            tar.addfile(info)
    return buffer.getvalue()


def zip_bytes(name="gh.exe", data=BINARY, attr=0):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo(name)
        info.external_attr = attr
        archive.writestr(info, data)
    return buffer.getvalue()


def sums(blob, name=ARCHIVE):
    return f"{hashlib.sha256(blob).hexdigest()}  {name}\n".encode()


class Web:
    """A fake `get`: serves what it was given and records every URL asked."""

    def __init__(self, files):
        self.files, self.asked = files, []

    def __call__(self, url):
        self.asked.append(url)
        return self.files[url]


def release(blob, checksums=None, name=ARCHIVE):
    return Web({BASE + name: blob, BASE + "checksums.txt": sums(blob, name) if checksums is None else checksums})


def install(web, dest, name=ARCHIVE, member=MEMBER, **kw):
    return release_fetch.install_binary(archive_url=kw.pop("archive_url", BASE + name), archive_name=name,
                                        checksums_url=kw.pop("checksums_url", BASE + "checksums.txt"),
                                        member=member, dest=dest, get=web)


# --- checksums and urls ---------------------------------------------------------------------------------------------


def test_parse_checksums_reads_both_formats_lowercases_and_skips_junk():
    h1, h2 = "A" * 64, "b" * 64
    text = f"{h1}  a.tar.gz\n{h2} *b.zip\nnot a line\n{'c' * 32}  short.md5\n{'d' * 64}\n\n"
    assert release_fetch.parse_checksums(text) == {"a.tar.gz": "a" * 64, "b.zip": h2}


@pytest.mark.parametrize("url, ok", [
    ("https://github.com/cli/cli/releases/download/v1/x.tar.gz", True),
    ("https://api.github.com/repos/cli/cli/releases/latest", True),
    ("https://objects.githubusercontent.com/x", True),
    ("https://release-assets.githubusercontent.com/x", True),
    ("http://github.com/x", False),
    ("https://evil.example/github.com", False),
    ("https://github.com.evil.example/x", False),
    ("https://githubusercontent.com.evil.example/x", False),
    ("https://raw.githubusercontent.com/a/b/c", False),  # user-controlled content: not a release asset host (#1637)
    ("https://gist.githubusercontent.com/a/b", False),
    ("https://objects.githubusercontent.com.evil.example/x", False),
    ("https://user@github.com/x", False),
    ("https://github.com:8443/x", False),
    ("file:///etc/passwd", False),
    ("https://[::1/x", False),
])
def test_allowed_url(url, ok):
    assert release_fetch.allowed_url(url) is ok


# --- install_binary -------------------------------------------------------------------------------------------------


def test_installs_a_tar_gz_member_with_mode_755_and_leaves_no_temp_file(tmp_path):
    dest = tmp_path / "bin" / "gh"  # the folder does not exist yet
    web = release(tar_bytes())
    assert install(web, dest) == "installed"
    assert dest.read_bytes() == BINARY and stat.S_IMODE(dest.stat().st_mode) == 0o755
    assert os.listdir(dest.parent) == ["gh"]
    assert web.asked == [BASE + "checksums.txt", BASE + ARCHIVE]  # the checksums come first


def test_installs_a_zip_member(tmp_path):
    name = "gh_1.2.3_windows_amd64.zip"
    dest = tmp_path / "gh.exe"
    assert install(release(zip_bytes(), name=name), dest, name=name, member="gh.exe") == "installed"
    assert dest.read_bytes() == BINARY


def test_a_wrong_checksum_writes_nothing_and_the_archive_is_never_opened(tmp_path):
    garbage = b"this is not an archive"  # opening it would say bad_archive, not checksum_mismatch
    web = release(garbage, checksums=f"{'0' * 64}  {ARCHIVE}\n".encode())
    with pytest.raises(FetchError) as caught:
        install(web, tmp_path / "gh")
    assert caught.value.reason_code == "checksum_mismatch"
    assert os.listdir(tmp_path) == []


def test_a_changed_archive_with_the_old_checksum_is_refused(tmp_path):
    good = tar_bytes()
    web = release(tar_bytes(((MEMBER, b"#!/bin/sh\nevil\n"),)), checksums=sums(good))
    with pytest.raises(FetchError) as caught:
        install(web, tmp_path / "gh")
    assert caught.value.reason_code == "checksum_mismatch" and os.listdir(tmp_path) == []


def test_a_checksums_file_without_the_archive_is_refused_before_the_download(tmp_path):
    blob = tar_bytes()
    web = release(blob, checksums=sums(blob, "other.tar.gz"))
    with pytest.raises(FetchError) as caught:
        install(web, tmp_path / "gh")
    assert caught.value.reason_code == "checksum_missing"
    assert web.asked == [BASE + "checksums.txt"] and os.listdir(tmp_path) == []


def test_an_existing_file_or_symlink_is_never_touched_and_nothing_is_downloaded(tmp_path):
    web = release(tar_bytes())
    own = tmp_path / "gh"
    own.write_text("mine")
    assert install(web, own) == "unchanged" and own.read_text() == "mine"
    target = tmp_path / "target"
    target.write_text("theirs")
    link = tmp_path / "link"
    link.symlink_to(target)
    assert install(web, link) == "unchanged" and target.read_text() == "theirs" and link.is_symlink()
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "nowhere")
    assert install(web, dangling) == "unchanged" and not (tmp_path / "nowhere").exists()
    assert web.asked == []


def test_a_file_that_appears_during_the_download_is_not_overwritten(tmp_path):
    dest = tmp_path / "gh"
    web = release(tar_bytes())
    inner = web.__call__

    def racing(url):
        data = inner(url)
        if url.endswith(ARCHIVE):
            dest.write_text("appeared meanwhile")
        return data

    assert install(racing, dest) == "unchanged"
    assert dest.read_text() == "appeared meanwhile" and os.listdir(tmp_path) == ["gh"]


def test_a_missing_member_is_refused(tmp_path):
    with pytest.raises(FetchError) as caught:
        install(release(tar_bytes()), tmp_path / "gh", member="../evil")
    assert caught.value.reason_code == "member_missing" and os.listdir(tmp_path) == []


def test_a_symlink_or_a_directory_member_is_refused(tmp_path):
    link = tarfile.TarInfo(MEMBER)
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    folder = tarfile.TarInfo(MEMBER)
    folder.type = tarfile.DIRTYPE
    for extra in (link, folder):
        with pytest.raises(FetchError) as caught:
            install(release(tar_bytes(members=(), extra=[extra])), tmp_path / "gh")
        assert caught.value.reason_code == "bad_archive"
    name = "gh_1.2.3_macOS_arm64.zip"
    with pytest.raises(FetchError) as caught:
        install(release(zip_bytes("gh", b"/etc/passwd", attr=0o120777 << 16), name=name), tmp_path / "gh", name=name, member="gh")
    assert caught.value.reason_code == "bad_archive" and os.listdir(tmp_path) == []


def test_a_member_over_the_size_cap_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(release_fetch, "MAX_BYTES", 5)
    with pytest.raises(FetchError) as caught:
        install(release(tar_bytes()), tmp_path / "gh")
    assert caught.value.reason_code == "bad_archive" and os.listdir(tmp_path) == []


@pytest.mark.parametrize("name, blob", [(ARCHIVE, b"not gzip"), ("gh.zip", b"not zip"), ("gh.rar", b"x")])
def test_an_unreadable_or_unknown_archive_with_a_matching_checksum_is_refused(tmp_path, name, blob):
    with pytest.raises(FetchError) as caught:
        install(release(blob, name=name), tmp_path / "gh", name=name)
    assert caught.value.reason_code == "bad_archive" and os.listdir(tmp_path) == []


@pytest.mark.parametrize("archive_url, checksums_url", [
    ("http://github.com/x.tar.gz", BASE + "checksums.txt"),
    (BASE + ARCHIVE, "https://evil.example/checksums.txt"),
    ("https://evil.example/x.tar.gz", BASE + "checksums.txt"),
])
def test_urls_outside_github_https_are_refused_before_any_request(tmp_path, archive_url, checksums_url):
    web = release(tar_bytes())
    with pytest.raises(FetchError) as caught:
        install(web, tmp_path / "gh", archive_url=archive_url, checksums_url=checksums_url)
    assert caught.value.reason_code == "unsafe_url" and web.asked == []


def test_a_folder_that_cannot_be_written_is_a_fetch_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(FetchError) as caught:
        install(release(tar_bytes()), blocker / "gh")
    assert caught.value.reason_code == "write_failed"


# --- default_get ----------------------------------------------------------------------------------------------------


def serve(monkeypatch, handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(release_fetch, "_transport", httpx.MockTransport(wrapped))
    return seen


def test_get_returns_the_body_and_sends_no_credentials(monkeypatch):
    seen = serve(monkeypatch, lambda request: httpx.Response(200, content=b"body"))
    assert release_fetch.default_get(BASE + "x") == b"body"
    assert "authorization" not in seen[0].headers


def test_get_follows_a_redirect_inside_github_only(monkeypatch):
    def handler(request):
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"location": "https://objects.githubusercontent.com/blob"})
        return httpx.Response(200, content=b"blob")

    seen = serve(monkeypatch, handler)
    assert release_fetch.default_get(BASE + "x") == b"blob"
    assert [r.url.host for r in seen] == ["github.com", "objects.githubusercontent.com"]


@pytest.mark.parametrize("target", ["https://evil.example/blob", "http://objects.githubusercontent.com/blob",
                                    "https://user@github.com/blob", "https://raw.githubusercontent.com/blob",
                                    "https://gist.githubusercontent.com/blob"])
def test_get_refuses_a_redirect_to_another_host_or_to_http_without_asking_it(monkeypatch, target):
    seen = serve(monkeypatch, lambda request: httpx.Response(302, headers={"location": target}))
    with pytest.raises(FetchError) as caught:
        release_fetch.default_get(BASE + "x")
    assert caught.value.reason_code == "unsafe_url" and len(seen) == 1


@pytest.mark.parametrize("host", ["objects.githubusercontent.com", "release-assets.githubusercontent.com"])
def test_get_follows_a_redirect_to_each_release_asset_host_and_a_relative_one(monkeypatch, host):
    def handler(request):
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"location": f"https://{host}/blob"})
        if request.url.path == "/blob":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, content=b"final")

    seen = serve(monkeypatch, handler)
    assert release_fetch.default_get(BASE + "x") == b"final"  # BASE is on github.com; the asset host answers the relative hop
    assert [r.url.host for r in seen] == ["github.com", host, host]


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("headers", [{}, {"location": ""}])
def test_get_refuses_a_3xx_without_location_as_a_fetch_error_not_a_key_error(monkeypatch, status, headers):
    seen = serve(monkeypatch, lambda request: httpx.Response(status, headers=headers))
    with pytest.raises(FetchError) as caught:
        release_fetch.default_get(BASE + "x")
    assert caught.value.reason_code == "unsafe_url" and "Location" in str(caught.value) and len(seen) == 1


def test_get_refuses_a_first_url_outside_github_and_a_redirect_loop(monkeypatch):
    seen = serve(monkeypatch, lambda request: httpx.Response(302, headers={"location": str(request.url)}))
    with pytest.raises(FetchError) as caught:
        release_fetch.default_get("https://evil.example/x")
    assert caught.value.reason_code == "unsafe_url" and seen == []
    with pytest.raises(FetchError) as caught:
        release_fetch.default_get(BASE + "x")
    assert caught.value.reason_code == "unsafe_url" and len(seen) == release_fetch.MAX_REDIRECTS + 1


def test_get_maps_http_errors_transport_errors_and_size(monkeypatch):
    serve(monkeypatch, lambda request: httpx.Response(404))
    with pytest.raises(FetchError) as caught:
        release_fetch.default_get(BASE + "x")
    assert caught.value.reason_code == "download_failed"

    def boom(request):
        raise httpx.ConnectError("refused")

    serve(monkeypatch, boom)
    with pytest.raises(FetchError) as caught:
        release_fetch.default_get(BASE + "x")
    assert caught.value.reason_code == "download_failed"
    monkeypatch.setattr(release_fetch, "MAX_BYTES", 3)
    serve(monkeypatch, lambda request: httpx.Response(200, content=b"four"))
    with pytest.raises(FetchError) as caught:
        release_fetch.default_get(BASE + "x")
    assert caught.value.reason_code == "too_large"
