'''Idle CPU measurement of the Simplicio Live server (#1400).'''
from __future__ import annotations

import secrets
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_idle_sample_reports_the_settle_window_it_waited_for(self) -> None:
        root = Path(tempfile.mkdtemp(prefix='simplicio-live-settle-'))
        self.addCleanup(shutil.rmtree, root, True)
        token = secrets.token_urlsafe(8)
        run_ids = bench.build_fixture(root, 1, 5)
        handle = server.start(root, port=0, token=token)
        self.addCleanup(handle.stop)
        result = bench.idle_cpu(handle.port, run_ids[0], token, seconds=1.0, settle_seconds=0.5)
        self.assertEqual(result['settle_s'], 0.5)

    def test_run_bench_settles_long_enough_for_the_replay_backlog(self) -> None:
        import inspect
        default = inspect.signature(bench.run_bench).parameters['settle_seconds'].default
        self.assertGreaterEqual(default, 2.0)

    def test_summary_includes_idle_cpu(self) -> None:
        result = bench.run_bench(2, 5, idle_seconds=0.5)
        self.assertIn('idle_cpu', result)
        self.assertIn('idle_cpu', bench.summary_line(result))


class PortableReaderTest(unittest.TestCase):
    FAKE_WIN = {'rss_kib': 4321, 'cpu_s': 1.5, 'rss_kind': 'current'}
    FAKE_MAC = {'rss_kib': 8765, 'cpu_s': 2.5, 'rss_kind': 'peak'}

    def _read(self, platform: str, **readers: object) -> tuple[object, str]:
        with mock.patch.object(sys, 'platform', platform), mock.patch.multiple(bench, **{'_read_linux': bench._read_linux, **readers}):
            return bench.read_process_stats()

    def _boom(self) -> dict:
        raise OSError('denied')

    @unittest.skipUnless(sys.platform.startswith('linux'), 'needs /proc')
    def test_linux_reads_proc_for_real(self) -> None:
        stats, source = bench.read_process_stats()
        self.assertIn('/proc', source)
        self.assertGreater(stats['rss_kib'], 1000)
        self.assertGreaterEqual(stats['cpu_s'], 0.0)
        self.assertEqual(stats['rss_kind'], 'current')
        before = stats['cpu_s']
        sum(i * i for i in range(2_000_000))
        self.assertGreater(bench.proc_stats()['cpu_s'], before)

    @unittest.skipIf(sys.platform == 'win32', 'resource is POSIX only')
    def test_posix_reader_reports_real_rusage(self) -> None:
        stats = bench._read_posix()
        self.assertGreater(stats['rss_kib'], 1000)
        self.assertGreaterEqual(stats['cpu_s'], 0.0)
        self.assertEqual(stats['rss_kind'], 'peak')

    def test_posix_reader_divides_macos_bytes_and_keeps_linux_kib(self) -> None:
        usage = mock.Mock(ru_maxrss=2048 * 1024, ru_utime=1.25, ru_stime=0.5)
        with mock.patch('resource.getrusage', return_value=usage):
            with mock.patch.object(sys, 'platform', 'darwin'):
                mac = bench._read_posix()
            with mock.patch.object(sys, 'platform', 'freebsd14'):
                other = bench._read_posix()
        self.assertEqual(mac, {'rss_kib': 2048, 'cpu_s': 1.75, 'rss_kind': 'peak'})  # bytes / 1024; utime + stime
        self.assertEqual(other['rss_kib'], 2048 * 1024)  # already KiB: not divided

    def test_windows_reader_fills_the_counters_struct_through_psapi(self) -> None:
        import ctypes
        seen: dict[str, int] = {}

        def get_info(handle: object, counters: object, size: int) -> int:
            seen['cb'] = size
            seen['handle'] = handle
            counters._obj.WorkingSetSize = 5 * 1024 * 1024  # type: ignore[attr-defined]
            return 1

        kernel32 = mock.Mock(GetCurrentProcess=mock.Mock(return_value=-1))
        psapi = mock.Mock(GetProcessMemoryInfo=get_info)
        dlls = {'kernel32': kernel32, 'psapi': psapi}
        with mock.patch.object(ctypes, 'WinDLL', lambda name, **kw: dlls[name], create=True), \
                mock.patch.object(bench.time, 'process_time', return_value=3.25):
            stats = bench._read_windows()
        self.assertEqual(stats, {'rss_kib': 5120, 'cpu_s': 3.25, 'rss_kind': 'current'})
        from ctypes import wintypes
        self.assertEqual(seen['cb'], 2 * ctypes.sizeof(wintypes.DWORD) + 8 * ctypes.sizeof(ctypes.c_size_t))  # 72 on Win64
        self.assertEqual(seen['handle'], -1)

    def test_windows_reader_raises_when_psapi_fails(self) -> None:
        import ctypes
        dlls = {'kernel32': mock.Mock(), 'psapi': mock.Mock(GetProcessMemoryInfo=lambda *a: 0)}
        with mock.patch.object(ctypes, 'WinDLL', lambda name, **kw: dlls[name], create=True), \
                mock.patch.object(ctypes, 'get_last_error', return_value=5, create=True):
            with self.assertRaisesRegex(OSError, 'GetProcessMemoryInfo failed'):
                bench._read_windows()

    def test_win32_dispatches_to_the_windows_reader(self) -> None:
        stats, source = self._read('win32', _read_windows=lambda: self.FAKE_WIN, _read_linux=self._boom,
                                   _read_posix=self._boom)
        self.assertEqual(stats, self.FAKE_WIN)
        self.assertIn('Windows', source)

    def test_darwin_dispatches_to_the_posix_reader(self) -> None:
        stats, source = self._read('darwin', _read_posix=lambda: self.FAKE_MAC, _read_linux=self._boom,
                                   _read_windows=self._boom)
        self.assertEqual(stats, self.FAKE_MAC)
        self.assertIn('macOS', source)

    def test_failing_reader_is_unverified_with_a_reason_not_a_number(self) -> None:
        stats, reason = self._read('win32', _read_windows=self._boom)
        self.assertIsNone(stats)
        self.assertIn('denied', reason)
        self.assertIn('win32', reason)

    def test_unknown_platform_has_no_reader(self) -> None:
        stats, reason = self._read('plan9')
        self.assertIsNone(stats)
        self.assertIn('plan9', reason)

    def test_run_bench_on_a_fake_platform_reports_its_source_and_numbers(self) -> None:
        with mock.patch.object(sys, 'platform', 'darwin'), mock.patch.object(bench, '_read_posix', lambda: self.FAKE_MAC):
            result = bench.run_bench(1, 3, idle_seconds=0.2, settle_seconds=0.0)
        self.assertEqual(result['process']['status'], 'MEASURED')
        self.assertEqual(result['process']['platform'], 'darwin')
        self.assertEqual(result['process']['after'], self.FAKE_MAC)
        self.assertEqual(result['idle_cpu']['status'], 'MEASURED')
        self.assertEqual(result['idle_cpu']['cpu_s'], 0.0)  # constant fake reader: no invented delta
        self.assertIn('rss_kib=8765', bench.summary_line(result))

    def test_run_bench_with_failing_reader_is_unverified_everywhere(self) -> None:
        with mock.patch.object(sys, 'platform', 'win32'), mock.patch.object(bench, '_read_windows', self._boom):
            result = bench.run_bench(1, 3, idle_seconds=0.2, settle_seconds=0.0)
        self.assertEqual(result['process']['status'], 'UNVERIFIED')
        self.assertIn('denied', result['process']['reason'])
        self.assertIsNone(result['process']['after'])
        self.assertEqual(result['idle_cpu']['status'], 'UNVERIFIED')
        self.assertIn('denied', result['idle_cpu']['reason'])
        self.assertIn('UNVERIFIED', bench.summary_line(result))


if __name__ == '__main__':
    unittest.main()
