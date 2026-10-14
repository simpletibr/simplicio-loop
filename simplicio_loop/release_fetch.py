"""Install one binary from a GitHub release archive, only after its SHA256 matched the release checksums (#1588).

Rules, in the order they run:

* an existing destination (file or symlink) is never touched, and nothing is downloaded for it;
* every URL is https on api.github.com or one of the exact hosts of `setup_hardening.ALLOWED_DOWNLOAD_HOSTS`, also after
  each redirect; a 3xx without `Location` is refused with `unsafe_url`;
* the checksums file of the same release must name the archive, and the SHA256 must match BEFORE the archive is opened;
* exactly one member is read, by its exact name (a regular file, size capped); nothing is extracted to a path;
* the file is written next to its destination with mode 755 and linked in with `os.link`, which fails if the name exists,
  so a file that appears meanwhile is not overwritten.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import io
import os
import re
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import httpx

from . import setup_hardening

MAX_BYTES = 200 * 1024 * 1024
MAX_REDIRECTS = 5
TIMEOUT_S = 60.0
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
_ZIP_SYMLINK = 0o120000
_transport: httpx.BaseTransport | None = None  # tests put an httpx.MockTransport here


class FetchError(Exception):
    """A download or install was refused. `reason_code` is stable; the message holds no secret."""

    def __init__(self, reason_code: str, message: str = "") -> None:
        super().__init__(message or reason_code)
        self.reason_code = reason_code


def allowed_url(url: str) -> bool:
    """https, no user info, default port, and api.github.com or an exact release-asset host."""
    try:
        parts = urlsplit(url)
        host, port = parts.hostname or "", parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username or parts.password or port not in (None, 443):
        return False
    return host == "api.github.com" or setup_hardening.is_allowed_download(url)


def parse_checksums(text: str) -> dict[str, str]:
    """`<64 hex>  name` or `<64 hex> *name` lines to {name: lowercase hex}; other lines are ignored."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        digest, _, name = line.strip().partition(" ")
        name = name.lstrip(" *")
        if name and _SHA256.fullmatch(digest):
            found[name] = digest.lower()
    return found


def default_get(url: str) -> bytes:
    """GET with no credentials; redirects are followed by hand and each hop must pass `allowed_url`."""
    try:
        with httpx.Client(transport=_transport, follow_redirects=False, timeout=TIMEOUT_S) as client:
            for _ in range(MAX_REDIRECTS + 1):
                if not allowed_url(url):
                    raise FetchError("unsafe_url", f"refused URL {url}")
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        try:
                            url = setup_hardening.redirect_target(url, response.status_code, response.headers)
                        except setup_hardening.RedirectError as exc:
                            raise FetchError("unsafe_url", str(exc)) from None
                        continue
                    if response.status_code != 200:
                        raise FetchError("download_failed", f"HTTP {response.status_code} for {url}")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            raise FetchError("too_large", f"{url} is larger than {MAX_BYTES} bytes")
                    return bytes(body)
    except httpx.HTTPError as exc:
        raise FetchError("download_failed", f"{type(exc).__name__} for {url}") from None
    raise FetchError("unsafe_url", f"too many redirects for {url}")


def _read_member(blob: bytes, archive_name: str, member: str) -> bytes:
    """The bytes of one regular file of the archive, found by its exact name."""
    try:
        if archive_name.endswith(".tar.gz"):
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
                info = tar.getmember(member)
                handle = tar.extractfile(info) if info.isreg() and info.size <= MAX_BYTES else None
                if handle is None:
                    raise FetchError("bad_archive", f"{member} is not a regular file of the allowed size")
                return handle.read()
        if archive_name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                info = archive.getinfo(member)
                if info.is_dir() or info.file_size > MAX_BYTES or (info.external_attr >> 16) & 0o170000 == _ZIP_SYMLINK:
                    raise FetchError("bad_archive", f"{member} is not a regular file of the allowed size")
                return archive.read(info)
    except KeyError:
        raise FetchError("member_missing", f"{member} is not in {archive_name}") from None
    except (tarfile.TarError, zipfile.BadZipFile, EOFError, OSError):
        raise FetchError("bad_archive", f"{archive_name} cannot be read") from None
    raise FetchError("bad_archive", f"{archive_name} is neither .tar.gz nor .zip")


def _link_in(dest: Path, data: bytes) -> str:
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp")
    except OSError as exc:
        raise FetchError("write_failed", f"cannot write in {dest.parent}: {exc.strerror}") from None
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o755)
        os.link(tmp, dest)  # fails when the name exists: nothing is overwritten
        return "installed"
    except FileExistsError:
        return "unchanged"
    except OSError as exc:
        raise FetchError("write_failed", f"cannot write {dest}: {exc.strerror}") from None
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)


def install_binary(*, archive_url: str, archive_name: str, checksums_url: str, member: str, dest: Path,
                   get: Callable[[str], bytes] = default_get, on_installed: Optional[Callable[[str], None]] = None,
                   expected_sha256: Optional[str] = None) -> str:
    """"installed" or "unchanged" (the destination already exists). Raises FetchError and writes nothing otherwise.

    `expected_sha256` is the pinned SHA256 of the archive: it must match too, so a release replaced as a whole is refused.
    `on_installed` gets the SHA256 of the bytes written, the moment they are in place (before anything else can run)."""
    if os.path.lexists(dest):
        return "unchanged"
    for url in (archive_url, checksums_url):
        if not allowed_url(url):
            raise FetchError("unsafe_url", f"refused URL {url}")
    expected = parse_checksums(get(checksums_url).decode("utf-8", "replace")).get(archive_name)
    if expected is None:
        raise FetchError("checksum_missing", f"the checksums file has no entry for {archive_name}")
    blob = get(archive_url)
    digest = hashlib.sha256(blob).hexdigest()
    if not hmac.compare_digest(digest, expected):
        raise FetchError("checksum_mismatch", f"SHA256 of {archive_name} does not match the release checksums")
    if expected_sha256 is not None and not hmac.compare_digest(digest, expected_sha256):
        raise FetchError("pin_mismatch", f"SHA256 of {archive_name} does not match the pinned SHA256 of this version")
    data = _read_member(blob, archive_name, member)
    result = _link_in(dest, data)
    if result == "installed" and on_installed is not None:
        on_installed(hashlib.sha256(data).hexdigest())
    return result
