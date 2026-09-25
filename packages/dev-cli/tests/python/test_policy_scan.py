from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.policy_scan import load_policy, main, render, scan


def _write_policy(root: Path, *, exceptions: str = "") -> Path:
    policy = root / "policy" / "no-internal-json.toml"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(
        f'schema = "simplicio.no-internal-json/v1"\nversion = 1\nscanner_version = "0.1.0"\n{exceptions}',
        encoding="utf-8",
    )
    return policy


def _exception(
    path: str,
    *,
    category: str = "external-adapter",
    review_date: str = "2026-07-23",
    removal_date: str = "2099-01-01",
) -> str:
    return (
        "\n[[exceptions]]\n"
        f'path = "{path}"\n'
        f'category = "{category}"\n'
        'owner = "quality"\n'
        'external_dependency = "explicit boundary"\n'
        'justification = "bounded test exception"\n'
        f'review_date = "{review_date}"\n'
        f'removal_date = "{removal_date}"\n'
    )


def _parse_hbp_fields(receipt: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in receipt.splitlines() if "=" in line)


def _hbp_digest(fields: dict[str, str]) -> str:
    ordered = (
        fields["seq"],
        fields["prev_hash"],
        fields["topic"],
        fields["payload"],
        fields["provenance"],
    )
    encoded = b"".join(len(value.encode()).to_bytes(8, "little") + value.encode() for value in ordered)
    return hashlib.sha256(encoded + (0).to_bytes(8, "little")).hexdigest()


def test_strict_scan_fails_for_unclassified_serializer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _write_policy(tmp_path)
    (tmp_path / "state.py").write_text("import json\nvalue = json.loads(raw)\n", encoding="utf-8")
    monkeypatch.setenv("SIMPLICIO_POLICY_SCAN_DATE", "2026-07-23")

    assert main(["--repo", str(tmp_path), "--policy", str(policy), "--mode", "strict"]) == 1


def test_exception_is_exact_and_does_not_authorize_sibling(tmp_path: Path) -> None:
    policy_path = _write_policy(tmp_path, exceptions=_exception("adapter.py"))
    (tmp_path / "adapter.py").write_text("import json\n", encoding="utf-8")
    (tmp_path / "domain.py").write_text("import json\n", encoding="utf-8")
    policy = load_policy(policy_path, "2026-07-23")

    findings = scan(tmp_path, policy)

    assert any(item[0] == "adapter.py" and item[4] == "external-adapter" for item in findings)
    assert any(item[0] == "domain.py" and item[4] == "unclassified" for item in findings)


@pytest.mark.parametrize(
    ("exceptions", "message"),
    [
        (_exception("*.py"), "not exact"),
        (_exception("../escape.py"), "not exact"),
        (_exception("folder\\\\adapter.py"), "not exact"),
        (_exception("adapter.py", category="anything"), "unsupported exception category"),
        (
            _exception("adapter.py", review_date="2026-01-01", removal_date="2026-07-22"),
            "expired exception",
        ),
        (_exception("adapter.py", removal_date="2026-02-30"), "invalid exception dates"),
    ],
)
def test_policy_rejects_broad_or_unaccountable_exceptions(
    tmp_path: Path, exceptions: str, message: str
) -> None:
    policy = _write_policy(tmp_path, exceptions=exceptions)

    with pytest.raises(ValueError, match=message):
        load_policy(policy, "2026-07-23")


@pytest.mark.parametrize(
    ("policy_text", "today", "message"),
    [
        ('schema = "wrong"\nversion = 1\nscanner_version = "0.1.0"\n', "2026-07-23", "schema"),
        ('schema = "simplicio.no-internal-json/v1"\nversion = 1\n', "2026-07-23", "scanner_version"),
        (
            'schema = "simplicio.no-internal-json/v1"\nversion = 1\nscanner_version = "0.1.0"\n'
            + _exception("adapter.py").replace('owner = "quality"\n', ""),
            "2026-07-23",
            "missing required field",
        ),
        (
            'schema = "simplicio.no-internal-json/v1"\nversion = 1\nscanner_version = "0.1.0"\n'
            + _exception("adapter.py")
            + _exception("adapter.py"),
            "2026-07-23",
            "not exact",
        ),
        (
            'schema = "simplicio.no-internal-json/v1"\nversion = 1\nscanner_version = "0.1.0"\n',
            "2026-02-30",
            "invalid scan date",
        ),
    ],
)
def test_policy_corruption_fails_closed(tmp_path: Path, policy_text: str, today: str, message: str) -> None:
    policy = tmp_path / "policy.toml"
    policy.write_text(policy_text, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_policy(policy, today)


def test_renamed_array_and_oversized_text_fail_closed(tmp_path: Path) -> None:
    policy_path = _write_policy(tmp_path)
    (tmp_path / "state.data").write_text("[1, 2, 3]\n", encoding="utf-8")
    (tmp_path / "large.py").write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    policy = load_policy(policy_path, "2026-07-23")

    findings = scan(tmp_path, policy)

    assert ("state.data", 1, "renamed-json-artifact", "array-document", "unclassified") in findings
    assert ("large.py", 1, "oversized-text", "4194305-bytes", "unclassified") in findings


def test_unused_exception_fails_closed(tmp_path: Path) -> None:
    policy_path = _write_policy(tmp_path, exceptions=_exception("future-adapter.py"))
    policy = load_policy(policy_path, "2026-07-23")

    assert (
        "future-adapter.py",
        1,
        "unused-exception",
        "no-matching-finding",
        "unclassified",
    ) in scan(tmp_path, policy)


def test_binary_and_non_utf8_files_are_bounded_without_crashing(tmp_path: Path) -> None:
    policy_path = _write_policy(tmp_path)
    (tmp_path / "binary.bin").write_bytes(b"\0json.loads")
    (tmp_path / "invalid.txt").write_bytes(b"\xff\xfejson.loads")
    (tmp_path / "state.json").write_text("{}", encoding="utf-8")
    policy = load_policy(policy_path, "2026-07-23")

    findings = scan(tmp_path, policy)

    assert [item for item in findings if item[0] == "binary.bin"] == []
    assert [item for item in findings if item[0] == "invalid.txt"] == []
    assert ("state.json", 1, "artifact-extension", "json", "unclassified") in findings


def test_symlink_is_reported_without_following_external_content(tmp_path: Path) -> None:
    policy_path = _write_policy(tmp_path)
    external = tmp_path.parent / "external.py"
    external.write_text("json.loads(secret)\n", encoding="utf-8")
    link = tmp_path / "linked.py"
    try:
        link.symlink_to(external)
    except OSError:
        pytest.skip("symlinks are unavailable")
    policy = load_policy(policy_path, "2026-07-23")

    findings = scan(tmp_path, policy)

    assert ("linked.py", 1, "symlink", "not-followed", "unclassified") in findings
    assert not any(item[0] == "linked.py" and item[2] == "serialization-call" for item in findings)


def test_hbp_receipt_hash_covers_scan_outcome() -> None:
    findings = [("domain.py", 7, "serialization-call", "json.loads", "unclassified")]
    policy = {"version": 1, "scanner_version": "0.1.0"}

    _, receipt, code = render(findings, policy, "strict")
    fields = _parse_hbp_fields(receipt)

    assert code == 1
    assert fields["schema"] == "simplicio.hbp/v1"
    assert fields["hash"] == _hbp_digest(fields)
    tampered = dict(fields, payload=fields["payload"].replace("status=FAIL", "status=PASS"))
    assert tampered["hash"] != _hbp_digest(tampered)


def test_main_writes_markdown_and_hbp_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = _write_policy(tmp_path)
    markdown = tmp_path.parent / "report.md"
    hbp = tmp_path.parent / "receipt.hbp"
    monkeypatch.setenv("SIMPLICIO_POLICY_SCAN_DATE", "2026-07-23")

    assert (
        main(
            [
                "--repo",
                str(tmp_path),
                "--policy",
                str(policy),
                "--mode",
                "strict",
                "--markdown",
                str(markdown),
                "--hbp",
                str(hbp),
            ]
        )
        == 0
    )
    assert "- status: `PASS`" in markdown.read_text(encoding="utf-8")
    assert _parse_hbp_fields(hbp.read_text(encoding="utf-8"))["hash"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is unavailable")
def test_python_and_node_scanners_emit_identical_evidence(tmp_path: Path) -> None:
    scan_root = tmp_path / "repository"
    scan_root.mkdir()
    policy_path = _write_policy(scan_root, exceptions=_exception("adapter.py"))
    (scan_root / "adapter.py").write_text("import json\nvalue = json.loads(raw)\n", encoding="utf-8")
    (scan_root / "domain.py").write_text("JSON.parse(raw)\n", encoding="utf-8")
    python_markdown = tmp_path / "python.md"
    python_hbp = tmp_path / "python.hbp"
    node_markdown = tmp_path / "node.md"
    node_hbp = tmp_path / "node.hbp"
    env = dict(os.environ, SIMPLICIO_POLICY_SCAN_DATE="2026-07-23")
    repository = Path(__file__).parents[2]
    python = shutil.which("python3")
    node = shutil.which("node")
    assert python is not None
    assert node is not None

    python_process = subprocess.run(
        [
            python,
            str(repository / "tools" / "policy_scan.py"),
            "--repo",
            str(scan_root),
            "--policy",
            str(policy_path),
            "--mode",
            "baseline",
            "--markdown",
            str(python_markdown),
            "--hbp",
            str(python_hbp),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    node_process = subprocess.run(
        [
            node,
            str(repository / "tools" / "policy_scan.mjs"),
            "--repo",
            str(scan_root),
            "--policy",
            str(policy_path),
            "--mode",
            "baseline",
            "--markdown",
            str(node_markdown),
            "--hbp",
            str(node_hbp),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert python_process.returncode == node_process.returncode == 0
    assert python_markdown.read_bytes() == node_markdown.read_bytes()
    assert python_hbp.read_bytes() == node_hbp.read_bytes()
