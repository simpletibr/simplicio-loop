#!/usr/bin/env python3
"""Verify that the distributions just uploaded to PyPI are available intact.

The publish workflow builds the artifacts locally, uploads them, and then runs
this module as a release gate.  PyPI can take a short time to expose a newly
uploaded version, so only registry-availability failures are retried.  A
digest mismatch is terminal: reporting a successful release for different
bytes would hide a broken or non-reproducible publication.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

DEFAULT_INDEX_URL = "https://pypi.org/pypi"
_ARTIFACT_SUFFIXES = (".whl", ".tar.gz")


class PyPIReleaseVerificationError(RuntimeError):
    """Raised when PyPI metadata or an artifact digest is incorrect."""


class TransientPyPIError(PyPIReleaseVerificationError):
    """Raised when PyPI has not exposed the release yet or is unavailable."""


def _normalise_name(value: str) -> str:
    return "-".join(part for part in value.replace("_", "-").replace(".", "-").split("-") if part).lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_metadata(
    package: str,
    version: str,
    *,
    index_url: str = DEFAULT_INDEX_URL,
    urlopen_fn: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Fetch one version's PyPI JSON metadata."""

    parsed_index = urlsplit(index_url)
    if parsed_index.scheme != "https" or not parsed_index.netloc:
        raise PyPIReleaseVerificationError("index-url must be an HTTPS URL")
    url = f"{index_url.rstrip('/')}/{quote(package, safe='')}/{quote(version, safe='')}/json"
    request = Request(  # noqa: S310 - URL scheme is validated above.
        url,
        headers={"Accept": "application/json", "User-Agent": "simplicio-mapper-release-gate"},
    )
    try:
        with urlopen_fn(request, timeout=20) as response:  # noqa: S310 - URL scheme is validated above.
            payload = json.load(response)
    except HTTPError as error:
        if error.code == 404 or error.code >= 500 or error.code == 429:
            raise TransientPyPIError(f"PyPI metadata is not available yet (HTTP {error.code})") from error
        raise PyPIReleaseVerificationError(f"PyPI metadata request failed (HTTP {error.code})") from error
    except (URLError, TimeoutError, OSError) as error:
        raise TransientPyPIError(f"PyPI metadata request failed: {error}") from error
    except (ValueError, TypeError) as error:
        raise TransientPyPIError(f"PyPI returned invalid JSON metadata: {error}") from error

    if not isinstance(payload, dict):
        raise TransientPyPIError("PyPI returned a non-object JSON payload")
    return payload


def verify_release(
    package: str,
    version: str,
    dist_dir: str | Path,
    *,
    index_url: str = DEFAULT_INDEX_URL,
    urlopen_fn: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Verify package metadata and every locally built distribution digest."""

    root = Path(dist_dir)
    if not root.is_dir():
        raise PyPIReleaseVerificationError(f"distribution directory does not exist: {root}")

    artifacts = sorted(
        path
        for suffix in _ARTIFACT_SUFFIXES
        for path in root.glob(f"*{suffix}")
        if path.is_file()
    )
    wheels = [path for path in artifacts if path.name.endswith(".whl")]
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        names = ", ".join(path.name for path in artifacts) or "none"
        raise PyPIReleaseVerificationError(
            "expected exactly one wheel and one source distribution in "
            f"{root}; found: {names}"
        )

    metadata = fetch_metadata(package, version, index_url=index_url, urlopen_fn=urlopen_fn)
    info = metadata.get("info")
    if not isinstance(info, dict):
        raise TransientPyPIError("PyPI metadata has no info object")
    published_name = info.get("name")
    published_version = info.get("version")
    if _normalise_name(str(published_name)) != _normalise_name(package):
        raise PyPIReleaseVerificationError(
            f"PyPI package mismatch: expected {package!r}, got {published_name!r}"
        )
    if published_version != version:
        raise PyPIReleaseVerificationError(
            f"PyPI version mismatch: expected {version!r}, got {published_version!r}"
        )

    remote_by_filename = {
        item.get("filename"): item
        for item in metadata.get("urls", [])
        if isinstance(item, dict) and isinstance(item.get("filename"), str)
    }
    verified: list[dict[str, str]] = []
    for artifact in artifacts:
        remote = remote_by_filename.get(artifact.name)
        if not isinstance(remote, dict):
            raise TransientPyPIError(f"PyPI metadata does not list {artifact.name!r} yet")
        digests = remote.get("digests")
        expected = digests.get("sha256") if isinstance(digests, dict) else None
        if not isinstance(expected, str):
            raise TransientPyPIError(f"PyPI metadata has no SHA256 digest for {artifact.name!r}")
        actual = _sha256(artifact)
        if actual != expected:
            raise PyPIReleaseVerificationError(
                f"SHA256 mismatch for {artifact.name}: local={actual} pypi={expected}"
            )
        verified.append({"filename": artifact.name, "sha256": actual})

    return {"package": package, "version": version, "artifacts": verified}


def verify_with_retries(
    package: str,
    version: str,
    dist_dir: str | Path,
    *,
    index_url: str = DEFAULT_INDEX_URL,
    attempts: int = 12,
    retry_delay: float = 10.0,
    urlopen_fn: Callable[..., Any] = urlopen,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    if retry_delay < 0:
        raise ValueError("retry-delay must not be negative")

    for attempt in range(1, attempts + 1):
        try:
            return verify_release(
                package,
                version,
                dist_dir,
                index_url=index_url,
                urlopen_fn=urlopen_fn,
            )
        except TransientPyPIError as error:
            if attempt == attempts:
                raise
            print(f"[retry {attempt}/{attempts}] {error}; waiting {retry_delay:g}s", file=sys.stderr)
            sleep_fn(retry_delay)
    raise AssertionError("unreachable")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--dist-dir", default="dist")
    parser.add_argument("--index-url", default=DEFAULT_INDEX_URL)
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--retry-delay", type=float, default=10.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = verify_with_retries(
            args.package,
            args.version,
            args.dist_dir,
            index_url=args.index_url,
            attempts=args.attempts,
            retry_delay=args.retry_delay,
        )
    except (PyPIReleaseVerificationError, ValueError) as error:
        print(f"[error] {error}", file=sys.stderr)
        return 1
    print(f"[ok] verified {result['package']}=={result['version']} on PyPI")
    for artifact in result["artifacts"]:
        print(f"[ok] {artifact['filename']} sha256={artifact['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
