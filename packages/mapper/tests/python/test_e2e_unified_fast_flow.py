"""End-to-end integration test verifying that all simplicio-fast capabilities
operate natively inside simplicio-mapper without requiring an external simplicio-fast installation.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

from simplicio_mapper.changeset import validate_changeset
from simplicio_mapper.processor import plan, understand
from simplicio_mapper.store.fast_link import mapper_fast_status
from simplicio_mapper.store.snapshot import Snapshot, is_snapshot_valid


def test_unified_fast_lifecycle_in_mapper(tmp_path: Path) -> None:
    repo = tmp_path / "sample_repo"
    repo.mkdir()

    # Create sample codebase
    src = repo / "src"
    src.mkdir()
    auth_file = src / "auth.py"
    auth_content = (
        "def authenticate_user(username: str, token: str) -> bool:\n"
        "    if not username or not token:\n"
        "        return False\n"
        "    return token.startswith('secret_')\n"
    )
    auth_file.write_text(auth_content, encoding="utf-8")
    auth_sha = hashlib.sha256(auth_content.encode("utf-8")).hexdigest()

    tests_dir = repo / "tests"
    tests_dir.mkdir()
    test_auth = tests_dir / "test_auth.py"
    test_auth.write_text(
        "from src.auth import authenticate_user\n\n"
        "def test_auth():\n"
        "    assert authenticate_user('admin', 'secret_123') is True\n",
        encoding="utf-8"
    )

    pyproject = repo / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'sample-repo'\nversion = '0.1.0'\n", encoding="utf-8")

    # Step 1: Run simplicio-mapper index via CLI
    cmd = [sys.executable, "-m", "simplicio_mapper.cli", "index", str(repo), "--json"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert proc.returncode == 0

    simplicio_dir = repo / ".simplicio-loop"
    assert (simplicio_dir / "project-map.json").is_file()
    assert (simplicio_dir / "symbol-index.json").is_file()

    # Verify SFAST binary snapshot was produced directly by index
    sfast_path = simplicio_dir / "project.sfast"
    assert sfast_path.is_file(), f"Binary snapshot {sfast_path} must exist"
    assert is_snapshot_valid(sfast_path) is True

    # Step 2: Query the SFAST snapshot directly via mmap
    with Snapshot(sfast_path) as snap:
        symbols = snap.search("authenticate_user")
        assert len(symbols) > 0
        assert symbols[0].name == "authenticate_user"

    # Step 3: Test understand() natively in mapper
    und = understand("authenticate user with token", root=repo)
    assert und.schema == "simplicio.fast.understanding/v2"
    assert any("auth.py" in str(f) for f in und.files)
    assert any(span.source_sha256 == auth_sha for span in und.context)

    # Step 4: Test plan() emitting PlanDAG natively in mapper
    plandag = plan("authenticate user with token", root=repo)
    assert plandag["schema"] == "simplicio.fast.plandag/v2"
    node_kinds = [n["id"] for n in plandag["nodes"]]
    assert node_kinds == ["orient", "modify", "validate", "refresh"]

    # Verify context handles and validation gates
    orient_node = next(n for n in plandag["nodes"] if n["id"] == "orient")
    assert "context_handles" in orient_node["inputs"]
    assert any(h["source_sha256"] == auth_sha for h in orient_node["inputs"]["context_handles"])

    validate_node = next(n for n in plandag["nodes"] if n["id"] == "validate")
    assert any("unittest" in c or "pytest" in c for cmd in validate_node["inputs"]["commands"] for c in cmd)

    # Step 5: Test changeset validation natively in mapper
    valid_changeset = {
        "schema": "simplicio.fast.changeset/v2",
        "changes": [
            {
                "path": "src/auth.py",
                "expected_sha256": auth_sha,
                "replacements": [
                    {
                        "start_line": 3,
                        "end_line": 3,
                        "content": "    if not username or not token or len(token) < 8:\n"
                    }
                ]
            }
        ]
    }
    validation_receipt = validate_changeset(valid_changeset, root=repo)
    assert validation_receipt["status"] == "valid"
    assert len(validation_receipt["files"]) == 1

    # Stale hash rejection test: modifying auth.py causes stale source hash error
    auth_file.write_text(auth_content + "\n# Modified\n", encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="stale source hash"):
        validate_changeset(valid_changeset, root=repo)

    # Step 6: Verify mapper_fast_status reports ready/integrated without external fast
    status = mapper_fast_status(repo=repo)
    assert status["status"] in {"integrated", "tools_ready", "ready"}
    assert status["mapper"]["binary"] is not None
