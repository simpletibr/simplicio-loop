"""The gh and uv releases that `setup` may install: tag and SHA256 of each archive, from `setup_pins.json` (#1657).

`build` is the maintainer's step (`scripts/update_release_pins.py`): it reads the latest official releases and keeps an
archive's digest only when the release's own checksums file publishes the same one. Nothing else writes the pins.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import prereqs, release_fetch

SCHEMA = "simplicio-loop/setup-pins/v1"
PINS_PATH = Path(__file__).with_name("setup_pins.json")
REPOS = {"gh": "cli/cli", "uv": "astral-sh/uv"}


class PinError(Exception):
    """The releases cannot be pinned: a checksum disagrees with its archive, or a latest release has no usable tag."""


def load(path: Path = PINS_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build(get: Callable[[str], bytes]) -> dict[str, Any]:
    """The pins of the latest gh and uv releases for the six platforms of `prereqs`."""
    doc: dict[str, Any] = {"schema": SCHEMA}
    for tool, repo in REPOS.items():
        try:
            answer = json.loads(get(f"https://api.github.com/repos/{repo}/releases/latest"))
        except ValueError:
            raise PinError(f"the latest {tool} release answer is not JSON") from None
        tag = answer.get("tag_name") if isinstance(answer, dict) else None
        if not isinstance(tag, str) or not prereqs._TAG.fullmatch(tag):
            raise PinError(f"the latest {tool} release has no usable tag")
        assets = {}
        for system, arch in prereqs._UV_TRIPLE:
            archive, sums_url, archive_url, _ = prereqs._release_files(tool, tag, system, arch)
            digest = hashlib.sha256(get(archive_url)).hexdigest()
            published = release_fetch.parse_checksums(get(sums_url).decode("utf-8", "replace")).get(archive)
            if published != digest:
                raise PinError(f"SHA256 of {archive} does not match the checksum its release publishes")
            assets[f"{system}-{arch}"] = {"archive": archive, "sha256": digest}
        doc[tool] = {"tag": tag, "assets": assets}
    return doc
