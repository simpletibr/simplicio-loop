"""Issue #477: default source-file size limit is 80 MB with override."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from simplicio_fast.cli import build_parser
from simplicio_fast.processor import ProjectProcessor
from simplicio_fast.snapshot import (
    DEFAULT_MAX_SOURCE_FILE_BYTES,
    SourceFileTooLarge,
    build_snapshot,
)


class SourceFileLimit477Test(unittest.TestCase):
    def test_default_max_source_file_bytes_is_80_mb(self) -> None:
        self.assertEqual(80 * 1024 * 1024, DEFAULT_MAX_SOURCE_FILE_BYTES)
        self.assertEqual(83_886_080, DEFAULT_MAX_SOURCE_FILE_BYTES)

    def test_cli_defaults_use_80_mb_for_build_understand_and_plan(self) -> None:
        parser = build_parser()
        for command in ("build", "refresh", "ingest", "understand", "plan"):
            argv = (
                [command]
                if command in {"build", "refresh", "ingest"}
                else [command, "task"]
            )
            args = parser.parse_args(argv)
            self.assertEqual(
                DEFAULT_MAX_SOURCE_FILE_BYTES,
                args.max_file_bytes,
                msg=f"{command} --max-file-bytes default",
            )

    def test_cli_max_file_bytes_override_is_parsed(self) -> None:
        parser = build_parser()
        for command, extra in (
            ("build", []),
            ("understand", ["task text"]),
            ("plan", ["task text"]),
        ):
            args = parser.parse_args(
                [command, *extra, "--max-file-bytes", "16000000"]
            )
            self.assertEqual(16_000_000, args.max_file_bytes)

    def test_build_rejects_file_above_effective_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "bundle.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            output = root / "project.sfast"
            real_stat = source.stat()
            # Resolve via os.path.realpath, not Path.resolve()/Path.stat(), so
            # this comparison never re-enters the patched Path.stat below
            # (Path.resolve() calls self.stat() internally on some Python
            # versions, which would recurse into fake_stat indefinitely).
            resolved_source = os.path.realpath(str(source))
            original_stat = Path.stat

            def fake_stat(self: Path, *args: object, **kwargs: object):
                if os.path.realpath(str(self)) == resolved_source:
                    return SimpleNamespace(
                        st_size=DEFAULT_MAX_SOURCE_FILE_BYTES + 1,
                        st_mtime_ns=real_stat.st_mtime_ns,
                        st_ctime_ns=getattr(
                            real_stat, "st_ctime_ns", real_stat.st_mtime_ns
                        ),
                        st_ino=getattr(real_stat, "st_ino", 0),
                        st_dev=getattr(real_stat, "st_dev", 0),
                        st_mode=real_stat.st_mode,
                    )
                return original_stat(self, *args, **kwargs)

            with patch.object(Path, "stat", fake_stat):
                with self.assertRaises(SourceFileTooLarge) as raised:
                    build_snapshot(root, output)
            self.assertEqual(DEFAULT_MAX_SOURCE_FILE_BYTES, raised.exception.limit)
            self.assertEqual(
                DEFAULT_MAX_SOURCE_FILE_BYTES + 1, raised.exception.size
            )
            self.assertFalse(output.exists())

    def test_build_accepts_former_8mb_bundle_size_under_80mb_default(self) -> None:
        """A ~9.85 MB source (previously rejected at 8 MiB) builds under 80 MB default."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = 9_853_285
            prefix = b'VALUE = "'
            suffix = b'"\n'
            body = b"a" * (target - len(prefix) - len(suffix))
            source = root / "vendor_bundle.py"
            source.write_bytes(prefix + body + suffix)
            self.assertEqual(target, source.stat().st_size)
            self.assertLess(source.stat().st_size, DEFAULT_MAX_SOURCE_FILE_BYTES)
            self.assertGreater(source.stat().st_size, 8 * 1024 * 1024)

            output = root / "project.sfast"
            metrics = build_snapshot(root, output)
            self.assertTrue(output.exists())
            self.assertGreaterEqual(metrics.files, 1)

    def test_understand_and_plan_honor_max_file_bytes_when_bootstrapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text(
                "def run():\n    return True\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            processor = ProjectProcessor(root, snapshot)

            with patch.object(processor, "ingest") as ingest:
                def _ingest(**kwargs):
                    self.assertEqual(4, kwargs.get("max_file_bytes"))
                    build_snapshot(root, snapshot, max_file_bytes=1024)
                    return {"schema": "mock"}

                ingest.side_effect = _ingest
                understanding = processor.understand(
                    "run", max_file_bytes=4, selection_mode="legacy-regex"
                )
                self.assertEqual(
                    "simplicio.fast.understanding/v2", understanding.schema
                )
                ingest.assert_called_once_with(max_file_bytes=4)

            snapshot.unlink(missing_ok=True)
            processor = ProjectProcessor(root, snapshot)
            with patch.object(processor, "ingest") as ingest:
                def _ingest_plan(**kwargs):
                    self.assertEqual(16_000_000, kwargs.get("max_file_bytes"))
                    build_snapshot(root, snapshot)
                    return {"schema": "mock"}

                ingest.side_effect = _ingest_plan
                plan = processor.plan(
                    "run",
                    max_file_bytes=16_000_000,
                    selection_mode="legacy-regex",
                )
                self.assertEqual("simplicio.fast.plandag/v2", plan["schema"])
                ingest.assert_called_once_with(max_file_bytes=16_000_000)


if __name__ == "__main__":
    unittest.main()
