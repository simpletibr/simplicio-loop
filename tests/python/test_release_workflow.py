from __future__ import annotations

"""Structural contract for the immutable-tag PyPI publish workflow (issue #423).

These tests do not upload to PyPI and do not force historical tag publication.
They only assert the workflow file encodes the release safety contract.
"""

import re
from pathlib import Path

WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "publish-pypi.yml"


def _workflow_text() -> str:
    assert WORKFLOW.is_file(), f"missing workflow: {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


def _run_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)run: \|\s*$", line)
        if match is None:
            continue
        indent = len(match.group(1))
        block: list[str] = []
        for candidate in lines[index + 1 :]:
            if candidate.strip() and len(candidate) - len(candidate.lstrip()) <= indent:
                break
            block.append(candidate)
        blocks.append("\n".join(block))
    return blocks


def test_publish_workflow_exists_and_is_versioned_yaml() -> None:
    text = _workflow_text()
    assert text.lstrip().startswith("name:")
    assert "Publish Mapper to PyPI" in text
    # File is checked into .github/workflows — versioned with the repo.
    assert WORKFLOW.as_posix().endswith(".github/workflows/publish-pypi.yml")


def test_publish_workflow_triggers_only_on_immutable_tags_or_explicit_dispatch() -> None:
    text = _workflow_text()
    assert re.search(r"(?m)^on:\s*$", text)
    assert re.search(r"(?m)^\s+tags:\s*$", text)
    assert '"v*.*.*"' in text or "'v*.*.*'" in text
    assert "workflow_dispatch:" in text
    # Must not auto-publish from branch pushes / PRs / schedules / release events.
    assert not re.search(r"(?m)^\s+branches:\s*$", text)
    assert "pull_request:" not in text
    assert "schedule:" not in text
    assert "release:" not in text
    # No hardcoded historical tag list that would republish old releases.
    assert not re.search(r"v0\.26\.[0-9]+", text)


def test_publish_workflow_verifies_tag_shape_and_version_match() -> None:
    text = _workflow_text()
    assert r"^v[0-9]+\.[0-9]+\.[0-9]+$" in text
    assert 'version="${tag#v}"' in text
    assert 'project["project"]["version"]' in text
    assert 'os.environ["VERSION"]' in text
    # Checked-out HEAD must equal the immutable tag object.
    assert "git rev-parse HEAD" in text
    assert 'refs/tags/$tag^{commit}' in text


def test_publish_workflow_builds_sdist_wheel_and_twine_checks() -> None:
    text = _workflow_text()
    assert "python -m build" in text
    assert "--wheel" in text and "--sdist" in text
    assert "python -m twine check dist/*" in text
    # Upload must come after check: locate step order by string position.
    check_pos = text.index("python -m twine check dist/*")
    upload_pos = text.index("python -m twine upload")
    assert check_pos < upload_pos


def test_publish_workflow_uses_existing_pypi_secret_without_printing() -> None:
    text = _workflow_text()
    assert "secrets.PYPI_API_TOKEN" in text
    assert "TWINE_USERNAME: __token__" in text
    assert "TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}" in text
    # Never echo or print the secret material.
    lowered = text.lower()
    assert "echo ${{ secrets.pypi_api_token }}" not in lowered
    assert "print(os.environ" not in text
    # Token-looking literals (PyPI API tokens start with pypi-AgE...); name
    # fragments like publish-pypi are allowed.
    assert re.search(r"pypi-AgE[A-Za-z0-9_-]+", text) is None
    assert re.search(r"(?i)pypi-[a-z0-9_]{20,}", text) is None
    # Only the secret reference on the env binding line (shell may reference the
    # env var name later without re-stating the secret expression).
    password_bindings = [
        line for line in text.splitlines() if line.strip().startswith("TWINE_PASSWORD:")
    ]
    assert password_bindings
    assert all("${{ secrets.PYPI_API_TOKEN }}" in line for line in password_bindings)


def test_publish_workflow_keeps_dispatch_input_out_of_shell() -> None:
    text = _workflow_text()
    run_blocks = _run_blocks(text)

    assert run_blocks
    assert all("${{ inputs." not in block for block in run_blocks)
    assert "RELEASE_TAG: ${{ inputs.tag || github.ref_name }}" in text
    assert 'tag="$RELEASE_TAG"' in text
    assert r"^v[0-9]+\.[0-9]+\.[0-9]+$" in text


def test_publish_workflow_does_not_auto_publish_historical_tags() -> None:
    """Guardrail: this change must not itself trigger old-tag uploads."""
    text = _workflow_text()
    # Automatic path is push-of-tag only; dispatch is explicit and opt-in.
    assert re.search(r"(?ms)^on:\s*\n\s*push:\s*\n\s*tags:", text)
    assert "workflow_dispatch:" in text
    # No repository_dispatch / workflow_call fan-in that could republish bulk history.
    assert "repository_dispatch:" not in text
    assert "workflow_call:" not in text
    # No matrix over multiple tags.
    assert "strategy:" not in text
    assert "matrix:" not in text
