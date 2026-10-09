"""Test that _sigterm_as_exit restores the previous SIGTERM handler (#1574)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper import canonical_builder
from simplicio_mapper.mapper.canonical_builder import (
    _sigterm_as_exit,
)


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout


def _repo(path: Path, files: int = 2) -> None:
    path.mkdir(parents=True)
    _git(["init", "-q", "--initial-branch", "main"], path)
    _git(["config", "user.email", "t@example.com"], path)
    _git(["config", "user.name", "T"], path)
    for index in range(files):
        (path / f"mod{index}.py").write_text(f"def f{index}():\n    return {index}\n", encoding="utf-8")
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", "init"], path)


class SigtermHandlerRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.repo = base / "repo"
        _repo(self.repo)
        self.cache = base / "cache"

    def test_sigterm_handler_restored_after_successful_build(self) -> None:
        """The previous SIGTERM handler is restored after a successful context manager exit."""
        import threading
        
        # Can only test on main thread
        if threading.current_thread() is not threading.main_thread():
            self.skipTest("SIGTERM handler test requires main thread")
        
        sigterm = getattr(signal, "SIGTERM", None)
        if sigterm is None:
            self.skipTest("SIGTERM not available")
        
        # Get the initial handler
        initial_handler = signal.getsignal(sigterm)
        
        # Use the context manager
        with _sigterm_as_exit():
            pass
        
        # Verify the handler is restored
        restored_handler = signal.getsignal(sigterm)
        assert restored_handler is initial_handler, "Handler should be restored after context exit"

    def test_sigterm_handler_restored_after_exception(self) -> None:
        """The previous SIGTERM handler is restored even when the context raises an exception."""
        import threading
        
        # Can only test on main thread
        if threading.current_thread() is not threading.main_thread():
            self.skipTest("SIGTERM handler test requires main thread")
        
        sigterm = getattr(signal, "SIGTERM", None)
        if sigterm is None:
            self.skipTest("SIGTERM not available")
        
        # Get the initial handler
        initial_handler = signal.getsignal(sigterm)
        
        # Use the context manager and raise an exception inside it
        try:
            with _sigterm_as_exit():
                raise RuntimeError("Test exception")
        except RuntimeError:
            pass
        
        # Verify the handler is restored even after exception
        restored_handler = signal.getsignal(sigterm)
        assert restored_handler is initial_handler, "Handler should be restored even after exception"

    def test_sigterm_handler_untouched_when_custom_handler_already_present(self) -> None:
        """When a custom SIGTERM handler is already installed, it should be left untouched."""
        import threading
        
        # Can only test on main thread
        if threading.current_thread() is not threading.main_thread():
            self.skipTest("SIGTERM handler test requires main thread")
        
        sigterm = getattr(signal, "SIGTERM", None)
        if sigterm is None:
            self.skipTest("SIGTERM not available")
        
        # Install a custom handler
        def custom_handler(signum, frame):
            pass
        
        signal.signal(sigterm, custom_handler)
        custom_handler_ref = signal.getsignal(sigterm)
        
        try:
            # Use the context manager
            with _sigterm_as_exit():
                # The handler should still be the custom one inside
                assert signal.getsignal(sigterm) is custom_handler_ref
                pass
            
            # Verify it's unchanged after
            assert signal.getsignal(sigterm) is custom_handler_ref
        finally:
            # Restore default
            signal.signal(sigterm, signal.SIG_DFL)
