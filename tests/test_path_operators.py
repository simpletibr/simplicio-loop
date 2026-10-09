"""Test path_operators: detect stale operators on PATH."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from simplicio_loop import path_operators


class TestPathOperators:
    """Test path_operators.check() end-to-end."""

    def test_absent_operator_no_warning(self, tmp_path):
        """When an operator is not on PATH, status is 'absent', no warning."""
        def fake_which(name):
            return None

        findings = path_operators.check(which=fake_which)
        assert len(findings) == 2
        for finding in findings:
            assert finding["path"] is None
            assert finding["status"] == "absent"
            assert finding["reason_code"] is None
            assert finding["fix"] is None

    def test_mapper_old_standalone_identity_missing(self, tmp_path):
        """Old standalone mapper with no build_identity: stale, reason mapper_identity_missing."""
        mapper_path = tmp_path / "simplicio-mapper"
        mapper_path.write_text("#!/usr/bin/python3\nprint('mapper')\n")
        mapper_path.chmod(0o755)

        def fake_which(name):
            return str(mapper_path) if name == "simplicio-mapper" else None

        def fake_run(argv):
            # Simulate old mapper: no build_identity module
            if "-c" in argv and ("-I" in argv or argv[0].endswith("python3")):
                return (0, json.dumps({"version": "0.26.35", "error": "no_build_identity"}) + "\n")
            return (127, "")

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            },
            "dev_cli_version": "0.26.35",
        }

        findings = path_operators.check(which=fake_which, run=fake_run, bundled=bundled)
        mapper_finding = next(f for f in findings if f["name"] == "simplicio-mapper")
        assert mapper_finding["status"] == "stale"
        assert mapper_finding["reason_code"] == "mapper_identity_missing"
        assert "pip install --force-reinstall simplicio-loop" in mapper_finding["fix"]
        assert "python3" in mapper_finding["fix"]

    def test_mapper_origin_mismatch(self, tmp_path):
        """Mapper with different origin: stale, reason origin_mismatch."""
        mapper_path = tmp_path / "simplicio-mapper"
        mapper_path.write_text("#!/usr/bin/python3\nprint('mapper')\n")
        mapper_path.chmod(0o755)

        def fake_which(name):
            return str(mapper_path) if name == "simplicio-mapper" else None

        def fake_run(argv):
            return (0, json.dumps({
                "version": "0.26.35",
                "origin": "old-standalone-build",
                "source_commit": "abc123" + "0" * 34,
            }) + "\n")

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            },
            "dev_cli_version": "0.26.35",
        }

        findings = path_operators.check(which=fake_which, run=fake_run, bundled=bundled)
        mapper_finding = next(f for f in findings if f["name"] == "simplicio-mapper")
        assert mapper_finding["status"] == "stale"
        assert mapper_finding["reason_code"] == "origin_mismatch"

    def test_mapper_version_mismatch(self, tmp_path):
        """Mapper with different version: stale, reason version_mismatch."""
        mapper_path = tmp_path / "simplicio-mapper"
        mapper_path.write_text("#!/usr/bin/python3\nprint('mapper')\n")
        mapper_path.chmod(0o755)

        def fake_which(name):
            return str(mapper_path) if name == "simplicio-mapper" else None

        def fake_run(argv):
            return (0, json.dumps({
                "version": "0.26.34",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            }) + "\n")

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            },
            "dev_cli_version": "0.26.35",
        }

        findings = path_operators.check(which=fake_which, run=fake_run, bundled=bundled)
        mapper_finding = next(f for f in findings if f["name"] == "simplicio-mapper")
        assert mapper_finding["status"] == "stale"
        assert mapper_finding["reason_code"] == "version_mismatch"

    def test_mapper_commit_mismatch(self, tmp_path):
        """Mapper with different commit (both valid SHA): stale, reason commit_mismatch."""
        mapper_path = tmp_path / "simplicio-mapper"
        mapper_path.write_text("#!/usr/bin/python3\nprint('mapper')\n")
        mapper_path.chmod(0o755)

        def fake_which(name):
            return str(mapper_path) if name == "simplicio-mapper" else None

        def fake_run(argv):
            return (0, json.dumps({
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "deadbeef" + "0" * 32,
            }) + "\n")

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "deadf00d" + "0" * 32,
            },
            "dev_cli_version": "0.26.35",
        }

        findings = path_operators.check(which=fake_which, run=fake_run, bundled=bundled)
        mapper_finding = next(f for f in findings if f["name"] == "simplicio-mapper")
        assert mapper_finding["status"] == "stale"
        assert mapper_finding["reason_code"] == "commit_mismatch"

    def test_mapper_identical_identity_ok(self, tmp_path):
        """Mapper with identical identity: ok."""
        mapper_path = tmp_path / "simplicio-mapper"
        mapper_path.write_text("#!/usr/bin/python3\nprint('mapper')\n")
        mapper_path.chmod(0o755)

        def fake_which(name):
            return str(mapper_path) if name == "simplicio-mapper" else None

        def fake_run(argv):
            return (0, json.dumps({
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            }) + "\n")

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            },
            "dev_cli_version": "0.26.35",
        }

        findings = path_operators.check(which=fake_which, run=fake_run, bundled=bundled)
        mapper_finding = next(f for f in findings if f["name"] == "simplicio-mapper")
        assert mapper_finding["status"] == "ok"
        assert mapper_finding["reason_code"] is None
        assert mapper_finding["fix"] is None

    def test_mapper_probe_not_importable(self, tmp_path):
        """Mapper probe returns error not_importable: stale, reason mapper_not_importable."""
        mapper_path = tmp_path / "simplicio-mapper"
        mapper_path.write_text("#!/usr/bin/python3\nprint('mapper')\n")
        mapper_path.chmod(0o755)

        def fake_which(name):
            return str(mapper_path) if name == "simplicio-mapper" else None

        def fake_run(argv):
            return (0, json.dumps({"error": "not_importable"}) + "\n")

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            },
            "dev_cli_version": "0.26.35",
        }

        findings = path_operators.check(which=fake_which, run=fake_run, bundled=bundled)
        mapper_finding = next(f for f in findings if f["name"] == "simplicio-mapper")
        assert mapper_finding["status"] == "stale"
        assert mapper_finding["reason_code"] == "mapper_not_importable"

    def test_mapper_probe_nonzero_rc(self, tmp_path):
        """Mapper probe returns rc != 0: stale, reason mapper_not_importable."""
        mapper_path = tmp_path / "simplicio-mapper"
        mapper_path.write_text("#!/usr/bin/python3\nprint('mapper')\n")
        mapper_path.chmod(0o755)

        def fake_which(name):
            return str(mapper_path) if name == "simplicio-mapper" else None

        def fake_run(argv):
            return (1, "")

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            },
            "dev_cli_version": "0.26.35",
        }

        findings = path_operators.check(which=fake_which, run=fake_run, bundled=bundled)
        mapper_finding = next(f for f in findings if f["name"] == "simplicio-mapper")
        assert mapper_finding["status"] == "stale"
        assert mapper_finding["reason_code"] == "mapper_not_importable"

    def test_mapper_native_binary_version_match(self, tmp_path):
        """Native mapper (no shebang) with --version matching: ok."""
        mapper_path = tmp_path / "simplicio-mapper"
        # Native binary: no shebang
        mapper_path.write_bytes(b"\x7fELF" + b"native binary stub")
        mapper_path.chmod(0o755)

        def fake_which(name):
            return str(mapper_path) if name == "simplicio-mapper" else None

        def fake_run(argv):
            if argv[0] == str(mapper_path) and "--version" in argv:
                return (0, "0.26.35\n")
            return (127, "")

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            },
            "dev_cli_version": "0.26.35",
        }

        findings = path_operators.check(which=fake_which, run=fake_run, bundled=bundled)
        mapper_finding = next(f for f in findings if f["name"] == "simplicio-mapper")
        assert mapper_finding["status"] == "ok"

    def test_mapper_native_binary_version_mismatch(self, tmp_path):
        """Native mapper with different --version: stale, version_mismatch."""
        mapper_path = tmp_path / "simplicio-mapper"
        mapper_path.write_bytes(b"\x7fELF" + b"native binary stub")
        mapper_path.chmod(0o755)

        def fake_which(name):
            return str(mapper_path) if name == "simplicio-mapper" else None

        def fake_run(argv):
            if argv[0] == str(mapper_path) and "--version" in argv:
                return (0, "0.26.34\n")
            return (127, "")

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            },
            "dev_cli_version": "0.26.35",
        }

        findings = path_operators.check(which=fake_which, run=fake_run, bundled=bundled)
        mapper_finding = next(f for f in findings if f["name"] == "simplicio-mapper")
        assert mapper_finding["status"] == "stale"
        assert mapper_finding["reason_code"] == "version_mismatch"

    def test_devcli_version_match(self, tmp_path):
        """dev-cli with matching version: ok."""
        devcli_path = tmp_path / "simplicio-dev-cli"
        devcli_path.write_text("#!/usr/bin/python3\nprint('dev-cli')\n")
        devcli_path.chmod(0o755)

        def fake_which(name):
            return str(devcli_path) if name == "simplicio-dev-cli" else None

        def fake_run(argv):
            if "simplicio-dev-cli" in argv[0] and "--version" in argv:
                return (0, "simplicio-py 0.26.35\n")
            return (127, "")

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            },
            "dev_cli_version": "0.26.35",
        }

        findings = path_operators.check(which=fake_which, run=fake_run, bundled=bundled)
        devcli_finding = next(f for f in findings if f["name"] == "simplicio-dev-cli")
        assert devcli_finding["status"] == "ok"

    def test_devcli_version_older(self, tmp_path):
        """dev-cli with older version: stale, version_mismatch."""
        devcli_path = tmp_path / "simplicio-dev-cli"
        devcli_path.write_text("#!/usr/bin/python3\nprint('dev-cli')\n")
        devcli_path.chmod(0o755)

        def fake_which(name):
            return str(devcli_path) if name == "simplicio-dev-cli" else None

        def fake_run(argv):
            if "simplicio-dev-cli" in argv[0] and "--version" in argv:
                return (0, "simplicio-py 0.26.34\n")
            return (127, "")

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            },
            "dev_cli_version": "0.26.35",
        }

        findings = path_operators.check(which=fake_which, run=fake_run, bundled=bundled)
        devcli_finding = next(f for f in findings if f["name"] == "simplicio-dev-cli")
        assert devcli_finding["status"] == "stale"
        assert devcli_finding["reason_code"] == "version_mismatch"

    def test_devcli_version_unreadable(self, tmp_path):
        """dev-cli --version returns rc != 0: stale, reason dev_cli_version_unreadable."""
        devcli_path = tmp_path / "simplicio-dev-cli"
        devcli_path.write_text("#!/usr/bin/python3\nprint('dev-cli')\n")
        devcli_path.chmod(0o755)

        def fake_which(name):
            return str(devcli_path) if name == "simplicio-dev-cli" else None

        def fake_run(argv):
            if "simplicio-dev-cli" in argv[0] and "--version" in argv:
                return (1, "")
            return (127, "")

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            },
            "dev_cli_version": "0.26.35",
        }

        findings = path_operators.check(which=fake_which, run=fake_run, bundled=bundled)
        devcli_finding = next(f for f in findings if f["name"] == "simplicio-dev-cli")
        assert devcli_finding["status"] == "stale"
        assert devcli_finding["reason_code"] == "dev_cli_version_unreadable"

    def test_frozen_exe_symlink_ok(self, tmp_path):
        """frozen_exe symlinked on PATH: ok without calling run."""
        exe_path = tmp_path / "exe"
        exe_path.write_text("#!/bin/sh\necho 'frozen'")
        exe_path.chmod(0o755)

        link_dir = tmp_path / "bin"
        link_dir.mkdir()
        link_path = link_dir / "simplicio-mapper"
        link_path.symlink_to(exe_path)

        def fake_which(name):
            return str(link_path) if name == "simplicio-mapper" else None

        run_called = []

        def fake_run(argv):
            run_called.append(argv)
            return (127, "")

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            },
            "dev_cli_version": "0.26.35",
        }

        findings = path_operators.check(
            which=fake_which,
            run=fake_run,
            bundled=bundled,
            frozen_exe=str(exe_path),
        )
        mapper_finding = next(f for f in findings if f["name"] == "simplicio-mapper")
        assert mapper_finding["status"] == "ok"
        # run should not have been called for mapper since frozen_exe matched
        assert not any("simplicio-mapper" in str(a) for a in run_called)

    def test_env_python3_shebang(self, tmp_path):
        """Mapper with #!/usr/bin/env python3 shebang: uses which('python3') to find interpreter."""
        mapper_path = tmp_path / "simplicio-mapper"
        mapper_path.write_text("#!/usr/bin/env python3\nprint('mapper')\n")
        mapper_path.chmod(0o755)

        python_path = tmp_path / "python3"
        python_path.write_text("#!/bin/sh\necho 'python3 stub'")
        python_path.chmod(0o755)

        def fake_which(name):
            if name == "simplicio-mapper":
                return str(mapper_path)
            elif name == "python3":
                return str(python_path)
            return None

        def fake_run(argv):
            return (0, json.dumps({
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            }) + "\n")

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            },
            "dev_cli_version": "0.26.35",
        }

        findings = path_operators.check(which=fake_which, run=fake_run, bundled=bundled)
        mapper_finding = next(f for f in findings if f["name"] == "simplicio-mapper")
        assert mapper_finding["status"] == "ok"

    def test_no_run_when_nothing_on_path(self, tmp_path):
        """check() never calls run() when nothing is on PATH."""
        def fake_which(name):
            return None

        run_called = []

        def fake_run(argv):
            run_called.append(argv)
            return (127, "")

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            },
            "dev_cli_version": "0.26.35",
        }

        findings = path_operators.check(which=fake_which, run=fake_run, bundled=bundled)
        assert all(f["status"] == "absent" for f in findings)
        assert not run_called

    @pytest.mark.skipif(sys.platform == "win32", reason="requires Unix shell")
    def test_real_fake_script_with_default_run(self, tmp_path):
        """End-to-end: REAL fake dev-cli script in tmp_path with default run()."""
        devcli_path = tmp_path / "simplicio-dev-cli"
        devcli_path.write_text("#!/bin/sh\necho 'simplicio-py 0.26.35'\n")
        devcli_path.chmod(0o755)

        def fake_which(name):
            return str(devcli_path) if name == "simplicio-dev-cli" else None

        bundled = {
            "mapper": {
                "version": "0.26.35",
                "origin": "simplicio-loop/packages/mapper",
                "source_commit": "abc123" + "0" * 34,
            },
            "dev_cli_version": "0.26.35",
        }

        # Use the default _run function
        findings = path_operators.check(which=fake_which, bundled=bundled)
        devcli_finding = next(f for f in findings if f["name"] == "simplicio-dev-cli")
        assert devcli_finding["status"] == "ok"


class TestStale:
    """Test path_operators.stale() filter."""

    def test_stale_filters_status(self):
        """stale() returns only findings with status == 'stale'."""
        findings = [
            {"name": "op1", "status": "ok", "reason_code": None},
            {"name": "op2", "status": "stale", "reason_code": "version_mismatch"},
            {"name": "op3", "status": "absent", "reason_code": None},
            {"name": "op4", "status": "stale", "reason_code": "origin_mismatch"},
        ]
        result = path_operators.stale(findings)
        assert len(result) == 2
        assert all(f["status"] == "stale" for f in result)
        assert {f["name"] for f in result} == {"op2", "op4"}


class TestBundled:
    def test_bundled_identity_carries_origin_and_commit(self):
        """The identity the PATH copies are compared with must hold origin and commit, not only the version."""
        pytest.importorskip("simplicio_mapper.build_identity")
        from simplicio_loop import mapper_doctor

        bundled = path_operators._bundled()
        assert bundled["mapper"]["origin"] == mapper_doctor.EXPECTED_ORIGIN
        assert bundled["mapper"]["version"] and bundled["dev_cli_version"]

