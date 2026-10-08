'''Idle CPU measurement of the Simplicio Live server (#1400).'''
from __future__ import annotations

import secrets
import shutil
import tempfile
import unittest
from pathlib import Path

from simplicio_loop.dashboard import bench, server


class IdleCpuTest(unittest.TestCase):
    def test_idle_cpu_reports_sample_and_percent(self) -> None:
        root = Path(tempfile.mkdtemp(prefix='simplicio-live-idle-'))
        self.addCleanup(shutil.rmtree, root, True)
        token = secrets.token_urlsafe(8)
        run_ids = bench.build_fixture(root, 2, 5)
        handle = server.start(root, port=0, token=token)
        self.addCleanup(handle.stop)
        result = bench.idle_cpu(handle.port, run_ids[0], token, seconds=1.0)
        self.assertEqual(result['sample_s'], 1.0)
        if bench.proc_stats() is None:
            self.assertEqual(result['status'], 'UNVERIFIED')
        else:
            self.assertEqual(result['status'], 'MEASURED')
            self.assertGreaterEqual(result['cpu_percent'], 0.0)
            self.assertLess(result['cpu_percent'], 50.0)

    def test_summary_includes_idle_cpu(self) -> None:
        result = bench.run_bench(2, 5, idle_seconds=0.5)
        self.assertIn('idle_cpu', result)
        self.assertIn('idle_cpu', bench.summary_line(result))


if __name__ == '__main__':
    unittest.main()
