from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from scripts.verify_pypi_release import (
    PyPIReleaseVerificationError,
    verify_release,
    verify_with_retries,
)

PACKAGE = "simplicio-mapper"
VERSION = "0.26.19"


def _write_artifacts(root: Path) -> dict[str, str]:
    files = {
        "simplicio_mapper-0.26.19-py3-none-any.whl": b"wheel-bytes",
        "simplicio_mapper-0.26.19.tar.gz": b"sdist-bytes",
    }
    digests: dict[str, str] = {}
    for name, content in files.items():
        (root / name).write_bytes(content)
        digests[name] = hashlib.sha256(content).hexdigest()
    return digests


def _response(digests: dict[str, str]) -> io.BytesIO:
    payload = {
        "info": {"name": PACKAGE, "version": VERSION},
        "urls": [
            {"filename": name, "digests": {"sha256": digest}}
            for name, digest in digests.items()
        ],
    }
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


def test_verify_release_checks_metadata_and_each_artifact_digest(tmp_path: Path) -> None:
    digests = _write_artifacts(tmp_path)

    def urlopen(request: object, timeout: int) -> io.BytesIO:
        assert timeout == 20
        return _response(digests)

    result = verify_release(PACKAGE, VERSION, tmp_path, urlopen_fn=urlopen)

    assert result["package"] == PACKAGE
    assert result["version"] == VERSION
    assert {item["filename"] for item in result["artifacts"]} == set(digests)
    assert {item["sha256"] for item in result["artifacts"]} == set(digests.values())


def test_verify_release_fails_on_digest_mismatch(tmp_path: Path) -> None:
    digests = _write_artifacts(tmp_path)
    digests[next(iter(digests))] = "0" * 64

    with pytest.raises(PyPIReleaseVerificationError, match="SHA256 mismatch"):
        verify_release(PACKAGE, VERSION, tmp_path, urlopen_fn=lambda *_args, **_kwargs: _response(digests))


def test_verify_with_retries_waits_for_eventual_pypi_visibility(tmp_path: Path) -> None:
    digests = _write_artifacts(tmp_path)
    responses = iter(
        [
            HTTPError("https://pypi.org/pypi/simplicio-mapper/0.26.19/json", 404, "missing", {}, None),
            _response(digests),
        ]
    )
    waits: list[float] = []

    def urlopen(*_args: object, **_kwargs: object) -> io.BytesIO:
        response = next(responses)
        if isinstance(response, HTTPError):
            raise response
        return response

    result = verify_with_retries(
        PACKAGE,
        VERSION,
        tmp_path,
        attempts=2,
        retry_delay=0.25,
        urlopen_fn=urlopen,
        sleep_fn=waits.append,
    )

    assert result["version"] == VERSION
    assert waits == [0.25]


def test_verify_release_requires_one_wheel_and_one_sdist(tmp_path: Path) -> None:
    (tmp_path / "simplicio_mapper-0.26.19-py3-none-any.whl").write_bytes(b"wheel")

    with pytest.raises(PyPIReleaseVerificationError, match="exactly one wheel and one source distribution"):
        verify_release(PACKAGE, VERSION, tmp_path, urlopen_fn=lambda *_args, **_kwargs: _response({}))
