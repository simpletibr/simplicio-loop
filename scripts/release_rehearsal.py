#!/usr/bin/env python3
"""End-to-end LOCAL release-pipeline rehearsal (#292 Fase 6, partial).

Scope and honest limits
------------------------
Issue #292 Fase 6 asks for the same build-once artifact set to be published, byte-identical, to
PyPI, npm, and GitHub Release, then re-verified against each registry. That requires a real
publish target and OIDC-backed CI credentials; neither exists in this environment
(`.github/workflows/` was removed in PR #311, no registry publish has ever happened from this
worktree — see docs/SUPPLY_CHAIN.md). This script does NOT publish anywhere, and does not
simulate a fake "published" result.

What it DOES do, for real: chain every locally-achievable link of the release pipeline — version
bump, build, checksum, sign (best-effort), SBOM, provenance record (best-effort sign), and
clean-room install-smoke — into ONE command against a **disposable copy** of the repository, so a
contributor can prove the whole local chain actually composes end-to-end, not just that each
script works in isolation. Nothing under the real repo checkout is mutated:

  1. `git archive HEAD` the tracked tree into a scratch directory (a real, byte-exact copy of what
     would be tagged — not a hand-picked subset).
  2. Bump the version in that scratch copy only, via `scripts.version_sync.apply_version`
     (defaults to a `+rehearsalNNNNNNNN` local-version-label build tag appended to the current
     canonical version, so it can never collide with a real release version; `--version` overrides
     it for an explicit dry-run of a real bump).
  3. Build a real wheel from the scratch copy (`python -m build --wheel --no-isolation`).
  4. Generate + verify a `SHA256SUMS.json` for the build output (`scripts.release_verify`).
  5. Attempt a detached gpg signature over the checksum manifest — blocks (does not fail the whole
     rehearsal) if no usable secret key is configured on this machine, exactly like
     `release_verify.py sign` does standalone.
  6. Generate a CycloneDX-shaped SBOM linked to the built artifact's digest
     (`scripts.sbom_generate`).
  7. Generate a locally-verifiable provenance statement linked to the same digest + the scratch
     copy's source SHA (`scripts.provenance_generate`), signed the same way as step 5.
  8. Run the clean-room install-smoke (`scripts.install_smoke.run_smoke`) against the scratch
     copy: fresh venv, `--no-deps --no-index`, `PYTHONPATH` cleared, isolation + version asserted,
     `--help` actually executed.
  9. (optional, --binary) Build the standalone executable for the current host using PyInstaller,
     verify its version output, and generate an SBOM for the binary. Runs scripts/build_binary.py
     from the scratch copy; that script builds its own wheel in a private venv and runs PyInstaller.
     Requires network; takes minutes. macOS and Windows executables must be built on those systems.

Governance gate (#294 scope item 6: "Integrar ao CI/release")
----------------------------------------------------------------
Before any of the above runs, this script also gates on — and snapshots — the repository's own
size/claims governance: `scripts/repository_budget.py --check` (the blob-budget guard) and
`scripts/claims_audit.py --only 8,13` (quantitative-claims + canonical-manifest — the "claims
parity" checks; the OTHER claims_audit checks, e.g. the e2e-installed-toolchain probe, are
deliberately excluded here because they gate on optional local toolchain state unrelated to
release governance, not on the repo's own claims/size surface). Both run against the REAL repo
checkout (not the scratch export), since `repository_budget.py` needs `git ls-files`/history that
a `git archive` export doesn't carry, and the canonical-manifest/claims data lives in the real
tree anyway. The rehearsal receipt's `governance` key snapshots the current measured repo size
(`docs/repo_size_report.json`) and history-migration candidate set
(`docs/history_migration_plan.json`) so every rehearsal run captures a size+claims snapshot, and
`docs/REPO_SIZE_REPORT.md` + `docs/HISTORY_MIGRATION_PLAN.md` are copied alongside the checksums/
SBOM/provenance in `dist/` — the "anexar relatório de tamanho e claims à release" requirement —
without this script ever running a history rewrite itself.

The rehearsal receipt records a Fase-8-shaped state machine —
`planned -> built -> checksummed -> signed|sign_blocked -> sbom -> provenance -> smoke-verified`
— and `ok` is true only if every REQUIRED link succeeded. Signing is optional/best-effort by
design (a fresh machine legitimately has no gpg key yet); it is recorded as `sign_blocked`, not
silently marked `ok`, and downstream consumers can require it via `--require-signing`.

This is a rehearsal, not a release: it never touches the real repo's version files, never creates
a git tag, and never talks to any package registry.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from install_smoke import run_smoke  # noqa: E402
from release_verify import generate_checksums, sign_manifest, verify_checksums  # noqa: E402
from sbom_generate import build_sbom  # noqa: E402
from version_sync import VersionSyncError, apply_version  # noqa: E402
from provenance_generate import build_provenance  # noqa: E402
from build_binary import BuildError, build_environment, parse_asset_name, parse_sha256sums, sha256_file  # noqa: E402

SCHEMA = "simplicio.release-rehearsal/v1"


def _load_json_text(text: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _load_json_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return _load_json_text(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def run_governance_gate(repo: Path) -> Dict[str, Any]:
    """#294 scope item 6: gate + snapshot the repo's own size/claims governance against the REAL
    checkout (repository_budget.py needs git history a `git archive` export doesn't carry).
    Returns a dict with `ok` plus the two sub-results and a size/claims snapshot for the receipt.
    """
    here = Path(__file__).resolve().parent
    budget_proc = subprocess.run(
        [sys.executable, str(here / "repository_budget.py"), "--check"],
        cwd=repo, capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    budget = {
        "ok": budget_proc.returncode == 0,
        "output": (budget_proc.stdout + budget_proc.stderr).strip(),
    }

    claims_proc = subprocess.run(
        [sys.executable, str(here / "claims_audit.py"), "--only", "8,13", "--json"],
        cwd=repo, capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    claims = _load_json_text(claims_proc.stdout) or {
        "ok": False,
        "results": [],
        "error": (claims_proc.stdout + claims_proc.stderr).strip() or "claims_audit produced no JSON",
    }
    if claims_proc.returncode != 0 and "error" not in claims:
        claims["ok"] = False

    size_snapshot = _load_json_file(repo / "docs" / "repo_size_report.json")
    migration_snapshot = _load_json_file(repo / "docs" / "history_migration_plan.json")

    return {
        "ok": budget["ok"] and bool(claims.get("ok")),
        "repository_budget": budget,
        "claims_parity": claims,
        "size_snapshot": size_snapshot,
        "history_migration_snapshot": migration_snapshot,
    }


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, timeout=30,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _export_tracked_tree(repo: Path, dest: Path) -> str:
    """Byte-exact copy of the tracked tree at HEAD via `git archive` — never the working tree,
    so uncommitted/ignored cruft in the real checkout can't leak into the rehearsal build."""
    sha = _git(repo, "rev-parse", "HEAD")
    dest.mkdir(parents=True, exist_ok=True)
    archive_path = dest.parent / f"{dest.name}.tar"
    with archive_path.open("wb") as fh:
        result = subprocess.run(
            ["git", "archive", "--format=tar", sha], cwd=repo, stdout=fh,
            stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
        )
    if result.returncode != 0:
        raise RuntimeError(f"git archive failed: {result.stderr.decode(errors='replace')}")
    with tarfile.open(archive_path) as tar:
        tar.extractall(dest)  # noqa: S202 - trusted source (our own repo's HEAD)
    archive_path.unlink(missing_ok=True)
    return sha


def run_rehearsal(
    repo: Path,
    *,
    version: Optional[str] = None,
    require_signing: bool = False,
    keep: bool = False,
    binary: bool = False,
) -> Dict[str, Any]:
    repo = repo.resolve()
    workdir = Path(tempfile.mkdtemp(prefix="simplicio-release-rehearsal-"))
    scratch = workdir / "scratch"
    receipt: Dict[str, Any] = {
        "schema": SCHEMA,
        "scope": "local-rehearsal-only (no publish target; see docs/SUPPLY_CHAIN.md)",
        "state": "planned",
        "workdir": str(workdir),
        "steps": {},
    }
    try:
        # Step: governance gate (#294) — blob budget + claims parity, gated + snapshotted against
        # the REAL repo checkout before anything else runs. Fail-closed: a release built on top
        # of an over-budget tree or a claims/canonical-manifest drift never proceeds to build.
        governance = run_governance_gate(repo)
        receipt["governance"] = governance
        receipt["steps"]["governance_gate"] = {"ok": governance["ok"]}
        if not governance["ok"]:
            receipt["ok"] = False
            receipt["reason_code"] = "governance_gate_failed"
            return receipt

        # Step: export a byte-exact scratch copy of HEAD.
        try:
            source_sha = _export_tracked_tree(repo, scratch)
        except RuntimeError as exc:
            receipt["steps"]["export"] = {"ok": False, "error": str(exc)}
            receipt["ok"] = False
            receipt["reason_code"] = "export_failed"
            return receipt
        receipt["source_sha"] = source_sha
        receipt["steps"]["export"] = {"ok": True, "source_sha": source_sha}

        # Step: bump version in the SCRATCH copy only. Default to a rehearsal-only local-version
        # label (PEP 440 `+rehearsal<epoch>` local segment) so this can never be mistaken for, or
        # collide with, a real published version.
        rehearsal_version = version or _rehearsal_version(scratch)
        try:
            apply_result = apply_version(scratch, rehearsal_version)
        except VersionSyncError as exc:
            receipt["steps"]["version_bump"] = {"ok": False, "error": str(exc)}
            receipt["ok"] = False
            receipt["reason_code"] = "version_bump_failed"
            return receipt
        receipt["rehearsal_version"] = rehearsal_version
        receipt["steps"]["version_bump"] = {
            "ok": apply_result["ok"],
            "changed_files": apply_result["changed_files"],
        }
        if not apply_result["ok"]:
            receipt["ok"] = False
            receipt["reason_code"] = "version_bump_not_ready"
            return receipt
        receipt["state"] = "built"

        # Step: build a real wheel from the scratch copy.
        dist_dir = workdir / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        build_cmd = [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(dist_dir)]
        build = subprocess.run(build_cmd, cwd=scratch, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        wheels = sorted(dist_dir.glob("*.whl"))
        receipt["steps"]["build"] = {
            "command": " ".join(build_cmd),
            "returncode": build.returncode,
            "stderr_tail": build.stderr.strip().splitlines()[-10:] if build.stderr else [],
            "wheel": str(wheels[-1]) if wheels else None,
            "ok": build.returncode == 0 and bool(wheels),
        }
        if not receipt["steps"]["build"]["ok"]:
            receipt["ok"] = False
            receipt["reason_code"] = "build_failed"
            return receipt
        wheel_path = wheels[-1]
        receipt["state"] = "checksummed"

        # Step: attach the size + history-migration governance reports to the release artifact
        # set (#294 "anexar relatório de tamanho e claims à release") — copied from the REAL
        # repo (governance gate already ran against it above), not the scratch export.
        governance_reports = []
        for report_name in ("docs/REPO_SIZE_REPORT.md", "docs/HISTORY_MIGRATION_PLAN.md"):
            src = repo / report_name
            if src.exists():
                dest = dist_dir / Path(report_name).name
                dest.write_bytes(src.read_bytes())
                governance_reports.append(str(dest))
        receipt["steps"]["governance_gate"]["attached_reports"] = governance_reports

        # Step: checksums generate + verify.
        checksums = generate_checksums(dist_dir)
        manifest_path = dist_dir / "SHA256SUMS.json"
        manifest_path.write_text(json.dumps(checksums, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        verify = verify_checksums(dist_dir, manifest_path)
        receipt["steps"]["checksums"] = {"generate": checksums, "verify": verify, "ok": checksums["ok"] and verify["ok"]}
        if not receipt["steps"]["checksums"]["ok"]:
            receipt["ok"] = False
            receipt["reason_code"] = "checksums_failed"
            return receipt

        # Step: best-effort gpg signature over the checksum manifest.
        sign_result = sign_manifest(manifest_path, key_id=None, output=None)
        signing_ok = sign_result["ok"]
        receipt["steps"]["sign"] = sign_result
        receipt["state"] = "signed" if signing_ok else "sign_blocked"
        if require_signing and not signing_ok:
            receipt["ok"] = False
            receipt["reason_code"] = "signing_required_but_blocked"
            return receipt

        # Step: SBOM linked to the built artifact digest. `scratch` is a `git archive` export with
        # no `.git` directory, so pass the source SHA explicitly rather than let `build_sbom`'s
        # own `git rev-parse` fail against a repo-less directory.
        sbom = build_sbom(scratch, artifact=wheel_path, source_sha=source_sha)
        sbom_path = dist_dir / "sbom.json"
        sbom_path.write_text(json.dumps(sbom, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        receipt["steps"]["sbom"] = {"ok": sbom["ok"], "path": str(sbom_path)}
        if not sbom["ok"]:
            receipt["ok"] = False
            receipt["reason_code"] = "sbom_failed"
            return receipt
        receipt["state"] = "sbom"

        # Step: locally-verifiable provenance statement, signed the same best-effort way.
        provenance = build_provenance(scratch, artifact=wheel_path, source_sha=source_sha)
        provenance_path = dist_dir / "provenance.json"
        provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        prov_sign = sign_manifest(provenance_path, key_id=None, output=None) if signing_ok else {
            "ok": False, "blocked": True, "reason": "checksum manifest signing already blocked (no gpg key)"
        }
        receipt["steps"]["provenance"] = {"ok": provenance["ok"], "path": str(provenance_path), "sign": prov_sign}
        if not provenance["ok"]:
            receipt["ok"] = False
            receipt["reason_code"] = "provenance_failed"
            return receipt
        receipt["state"] = "provenance"

        # Step: clean-room install-smoke against the scratch copy using the exact pre-built,
        # checksummed wheel artifact.
        smoke = run_smoke(scratch, expected_version=rehearsal_version, keep=False, wheel_path=wheel_path)
        receipt["steps"]["install_smoke"] = smoke
        if not smoke.get("ok"):
            receipt["ok"] = False
            receipt["reason_code"] = "install_smoke_failed"
            return receipt
        receipt["state"] = "smoke-verified"

        # Step: (optional) build standalone binary using PyInstaller.
        if binary:
            if not run_binary_step(repo, scratch, workdir, receipt, wheel_path, source_sha, rehearsal_version):
                receipt["ok"] = False
                receipt["reason_code"] = "binary_failed"
                return receipt
            receipt["state"] = "binary-verified"

        receipt["ok"] = True
        return receipt
    finally:
        if keep:
            receipt["kept_workdir"] = True
        else:
            shutil.rmtree(workdir, ignore_errors=True)
            receipt.pop("workdir", None)



def binary_step_commands(
    scratch: Path, out_dir: Path, work_dir: Path, version: str
) -> list[list[str]]:
    """Return one argv list: the build_binary command which builds its own wheel and private venv."""
    return [
        [sys.executable, str(scratch / "scripts" / "build_binary.py"), "--allow-dirty", "--version", version,
         "--out", str(out_dir), "--work", str(work_dir), "--python", sys.executable],
    ]


def verify_binary_assets(out_dir: Path, version: str) -> Dict[str, Any]:
    """Check that SHA256SUMS lists exactly the one executable of this version and its digest is right."""
    result: Dict[str, Any] = {"ok": False, "asset": None, "sha256": None, "reason": ""}
    sums = out_dir / "SHA256SUMS"
    if not sums.is_file():
        result["reason"] = f"SHA256SUMS not found in {out_dir}"
        return result
    try:
        digests = parse_sha256sums(sums.read_text(encoding="utf-8"))
    except BuildError as error:
        result["reason"] = str(error)
        return result
    if len(digests) != 1:
        result["reason"] = f"SHA256SUMS must list exactly one executable, it lists {len(digests)}"
        return result
    (name, listed), = digests.items()
    parsed = parse_asset_name(name)
    if parsed is None or parsed[0] != version:
        result["reason"] = f"{name} is not an executable of version {version}"
        return result
    result["asset"] = name
    if not (out_dir / name).is_file():
        result["reason"] = f"{name} is not in {out_dir}"
        return result
    result["sha256"] = sha256_file(out_dir / name)
    if result["sha256"] != listed:
        result["reason"] = f"digest of {name} is {result['sha256']}, SHA256SUMS lists {listed}"
        return result
    result["ok"] = True
    return result


def run_binary_step(
    repo: Path, scratch: Path, workdir: Path, receipt: Dict[str, Any], wheel: Path, source_sha: str, version: str
) -> bool:
    """Build the standalone executable for this host and check it. Fills steps.binary.
    
    The new build_binary.py builds its own wheel in a private venv with PyInstaller.
    This function runs the single build command with a deterministic environment,
    verifies the assets, checks the executable version, and generates an SBOM.
    """
    out_dir = workdir / "binary"
    step: Dict[str, Any] = {"ok": False, "asset": None, "sha256": None, "reason": "", "commands": [],
                            "returncodes": [], "stderr_tail": []}
    receipt["steps"]["binary"] = step
    try:  # the scratch copy has no .git, so the commit time of the real repo is the build time
        epoch = int(_git(repo, "log", "-1", "--format=%ct"))
    except (RuntimeError, ValueError) as error:
        step["reason"] = f"no SOURCE_DATE_EPOCH: {error}"
        return False
    commands = binary_step_commands(scratch, out_dir, workdir / "binary-work", version)
    step["commands"] = [" ".join(command) for command in commands]
    for index, command in enumerate(commands):
        # Run the build_binary command with the deterministic environment
        env = build_environment(os.environ, epoch)
        done = subprocess.run(command, cwd=scratch, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=3600)
        step["returncodes"].append(done.returncode)
        if done.returncode != 0:
            step["reason"] = f"command {index} exited with {done.returncode}"
            step["stderr_tail"] = done.stderr.strip().splitlines()[-10:]
            return False
    verified = verify_binary_assets(out_dir, version)
    step.update(asset=verified["asset"], sha256=verified["sha256"])
    if not verified["ok"]:
        step["reason"] = verified["reason"]
        return False
    executable = out_dir / verified["asset"]
    shown = subprocess.run([str(executable), "--version"], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=120)
    if shown.returncode != 0 or shown.stdout.strip() != f"simplicio-loop {version}":
        step["reason"] = f"--version printed {shown.stdout.strip()!r}, expected 'simplicio-loop {version}'"
        return False
    sbom = build_sbom(scratch, artifact=executable, source_sha=source_sha)
    (out_dir / "sbom-binary.json").write_text(
        json.dumps(sbom, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    step["ok"] = bool(sbom["ok"])
    step["reason"] = "" if step["ok"] else "the SBOM of the executable failed"
    return step["ok"]


def _rehearsal_version(scratch: Path) -> str:
    from release_manifest import build_manifest as _build_manifest
    canonical = _build_manifest(scratch)["canonical_version"]
    return f"{canonical}+rehearsal{int(time.time())}"


def _cmd_run(args: argparse.Namespace) -> int:
    result = run_rehearsal(
        Path(args.repo),
        version=args.version,
        require_signing=args.require_signing,
        keep=args.keep,
        binary=args.binary,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=None if args.json else 2))
    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return 0 if result.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(prog="release_rehearsal", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="chain version-bump+build+checksum+sign+sbom+provenance+smoke against a disposable scratch copy")
    p_run.add_argument("--repo", default=".")
    p_run.add_argument("--version", default=None, help="explicit version to rehearse a real bump (default: safe +rehearsal<ts> label)")
    p_run.add_argument("--require-signing", action="store_true", help="fail the rehearsal if no gpg key is available (default: sign is best-effort)")
    p_run.add_argument("--keep", action="store_true", help="keep the scratch workdir for inspection")
    p_run.add_argument("--binary", action="store_true", default=False, help="build the standalone executable too (uses scripts/build_binary.py with its own wheel and PyInstaller; requires network; takes minutes)")
    p_run.add_argument("--output", default=None, help="also write the receipt JSON to this path")
    p_run.add_argument("--json", action="store_true", help="emit compact single-line JSON")
    p_run.set_defaults(func=_cmd_run)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
