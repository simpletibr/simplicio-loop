from __future__ import annotations

import re
from pathlib import Path


WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "publish-pypi.yml"


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


def test_publish_workflow_keeps_dispatch_input_out_of_shell() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    run_blocks = _run_blocks(text)

    assert run_blocks
    assert all("${{ inputs." not in block for block in run_blocks)
    assert "RELEASE_TAG: ${{ inputs.tag || github.ref_name }}" in text
    assert 'tag="$RELEASE_TAG"' in text
    assert "^v[0-9]+\\.[0-9]+\\.[0-9]+$" in text