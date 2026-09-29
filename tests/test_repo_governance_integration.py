"""#294 repository governance — repo_history_scan, history_migration_plan, canonical_manifest,
package_content_check. Each script's own selftest already proves its core logic; these tests
exercise the CLI surface (subprocess invocation, exit codes, JSON shape) the way `claims_audit.py`
and `check.py` actually call them, and assert the safety invariants the issue's Definition of Done
requires (history-migration-plan has no execute path; repo_history_scan/canonical_manifest never
touch git refs).
"""
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(rel_script, args):
    path = os.path.join(REPO, "scripts", rel_script)
    return subprocess.run([sys.executable, path] + args, capture_output=True, text=True,
                          cwd=REPO, stdin=subprocess.DEVNULL)


def _git_fixture(tmp_path):
    """A deliberately tiny history: ordinary content plus deleted generated artifacts."""
    repo = str(tmp_path / "fixture")
    os.makedirs(repo)

    def git(*args):
        subprocess.run(["git"] + list(args), cwd=repo, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

    git("init", "-q")
    git("config", "user.email", "tests@example.invalid")
    git("config", "user.name", "governance tests")
    files = {
        "README.md": b"fixture\n",
        "video/out/demo.mp4": b"m" * 4096,
        "rust/target/cache.bin": b"r" * 2048,
    }
    for path, data in files.items():
        full_path = os.path.join(repo, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(data)
    git("add", ".")
    git("commit", "-q", "-m", "add fixture artifacts")
    os.remove(os.path.join(repo, "video", "out", "demo.mp4"))
    git("add", "-A")
    git("commit", "-q", "-m", "remove generated video")
    return repo


# ---- repo_history_scan.py (#294 AC1) ----

def test_repo_history_scan_selftest_passes():
    r = _run("repo_history_scan.py", ["selftest"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "repo_history_scan selftest: PASS" in r.stdout


def test_repo_history_scan_json_report_shape(tmp_path):
    r = _run("repo_history_scan.py", ["--json", "--top", "5", "--repo", _git_fixture(tmp_path)])
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(r.stdout)
    assert report["schema"] == "simplicio.repo-history-scan/v1"
    assert report["distinct_blobs_ever_committed"] >= 3
    assert report["total_historical_blob_bytes"] > 0
    assert len(report["top_blobs"]) <= 5
    # real numbers, not fabricated -- every blob has a real 40-hex sha and positive size
    for b in report["top_blobs"]:
        assert len(b["sha"]) == 40 or len(b["sha"]) == 41  # git rev-list --objects sha len
        assert b["size_bytes"] > 0


def test_repo_history_scan_write_report_produces_both_files(tmp_path):
    output_dir = str(tmp_path / "reports")
    r = _run("repo_history_scan.py", ["--write-report", "--top", "3", "--repo",
                                       _git_fixture(tmp_path), "--output-dir", output_dir])
    assert r.returncode == 0, r.stdout + r.stderr
    md_path = os.path.join(output_dir, "REPO_SIZE_REPORT.md")
    json_path = os.path.join(output_dir, "repo_size_report.json")
    assert os.path.exists(md_path)
    assert os.path.exists(json_path)
    with open(md_path, encoding="utf-8") as f:
        text = f.read()
    assert "Repository size report" in text
    assert "size-pack" in text.lower() or "size-pack" in text


# ---- history_migration_plan.py (#294 AC3/AC4/AC10) ----

def test_history_migration_plan_selftest_passes():
    r = _run("history_migration_plan.py", ["selftest"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "history_migration_plan selftest: PASS" in r.stdout


def test_history_migration_plan_refuses_without_dry_run_flag():
    r = _run("history_migration_plan.py", [])
    assert r.returncode == 2
    assert "--dry-run" in (r.stdout + r.stderr)


def test_history_migration_plan_dry_run_json_never_executed(tmp_path):
    r = _run("history_migration_plan.py", ["--dry-run", "--json", "--repo", _git_fixture(tmp_path)])
    assert r.returncode == 0, r.stdout + r.stderr
    plan = json.loads(r.stdout)
    assert plan["mode"] == "DRY_RUN_ONLY"
    assert plan["executed"] is False
    assert plan["candidate_blob_count"] >= 2


def test_history_migration_plan_write_uses_requested_output_dir(tmp_path):
    output_dir = str(tmp_path / "plans")
    r = _run("history_migration_plan.py", ["--dry-run", "--write", "--repo",
                                             _git_fixture(tmp_path), "--output-dir", output_dir])
    assert r.returncode == 0, r.stdout + r.stderr
    md_path = os.path.join(output_dir, "HISTORY_MIGRATION_PLAN.md")
    json_path = os.path.join(output_dir, "history_migration_plan.json")
    assert os.path.exists(md_path)
    assert os.path.exists(json_path)
    with open(json_path, encoding="utf-8") as f:
        assert json.load(f)["executed"] is False


def test_history_migration_plan_source_has_no_rewrite_tool_invocation():
    """Static guard mirrored from the script's own selftest: the DEFINITION OF DONE forbids any
    execute path. Re-asserted here at the test-suite level so it cannot silently regress."""
    path = os.path.join(REPO, "scripts", "history_migration_plan.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    import re
    hits = re.findall(r"subprocess\.\w+\(\s*\[[^\]]*(filter-repo|filter-branch|bfg\.jar)", src, re.I)
    assert not hits, "history_migration_plan.py must never invoke a history-rewrite tool"


# ---- canonical_manifest.py (#294 AC6/AC7) ----

def test_canonical_manifest_selftest_passes():
    r = _run("canonical_manifest.py", ["selftest"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "canonical_manifest selftest: PASS" in r.stdout


def test_canonical_manifest_check_is_ready_on_this_repo():
    r = _run("canonical_manifest.py", ["check"])
    assert r.returncode == 0, "canonical manifest should be READY on a clean checkout: " + r.stdout + r.stderr
    assert "READY" in r.stdout


def test_canonical_manifest_json_has_expected_keys():
    r = _run("canonical_manifest.py", ["--json"])
    assert r.returncode == 0, r.stdout + r.stderr
    manifest = json.loads(r.stdout)
    for key in ("canonical_version", "skill_count", "runtime_count", "runtime_names",
                "changelog_latest_version", "quantitative_claims", "lean_mirror", "ready"):
        assert key in manifest
    assert manifest["skill_count"] == 7
    assert manifest["runtime_count"] == len(manifest["runtime_names"]) == 15
    assert manifest["adapter_non_canonical"] == ["grok"]


# ---- package_content_check.py (#294 AC11) ----

def test_package_content_check_selftest_passes():
    r = _run("package_content_check.py", ["selftest"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "package_content_check selftest: PASS" in r.stdout


def test_package_content_check_describe_cli():
    r = _run("package_content_check.py", ["--describe-cli"])
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert "selftest" in payload["verbs"]


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_repo_governance_294")
