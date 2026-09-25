"""Benchmark the canonical-map + worktree-overlay reuse added for issue #213.

Measures wall-clock latency for resolving the effective map view:
  - a "cold" first call (nothing cached on disk yet — builds both halves);
  - a "warm" call with a fresh process-level cache (`clear_view_cache()`)
    but matching manifests already on disk — the "no redundant full remap"
    path this issue exists to add.

Uses a real throwaway git repository (the module shells out to the real
`git` binary; faking it would just re-describe the implementation).
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio import map_view  # noqa: E402

RESULTS_JSON = ROOT / "bench" / "results_map_view_bench.json"
RESULTS_MD = ROOT / "bench" / "results_map_view_bench.md"

REPEATS = 5


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, check=True)


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "bench@example.com")
    _git(repo, "config", "user.name", "Bench")
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def main() -> int:
    map_view._mapper_config_fingerprint = lambda: "bench-fingerprint"  # deterministic, no PATH dependency

    with tempfile.TemporaryDirectory() as tmp:
        repo = _make_repo(Path(tmp))

        cold_times = []
        warm_times = []
        for _ in range(REPEATS):
            map_view.clear_view_cache()
            start = time.perf_counter()
            map_view.get_effective_map_view(repo, force_remap=True)
            cold_times.append(time.perf_counter() - start)

            map_view.clear_view_cache()  # simulate a new process/retry, manifests already on disk
            start = time.perf_counter()
            map_view.get_effective_map_view(repo)
            warm_times.append(time.perf_counter() - start)

    cold_avg = sum(cold_times) / len(cold_times)
    warm_avg = sum(warm_times) / len(warm_times)
    speedup = cold_avg / warm_avg if warm_avg else float("inf")

    result = {
        "repeats": REPEATS,
        "cold_seconds_avg": round(cold_avg, 4),
        "warm_seconds_avg": round(warm_avg, 4),
        "speedup_x": round(speedup, 2),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }
    RESULTS_JSON.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    RESULTS_MD.write_text(
        "# Canonical map + worktree overlay benchmark (issue #213)\n\n"
        f"- Repeats: {REPEATS}\n"
        f"- Cold (`force_remap=True`, rebuild both halves): {result['cold_seconds_avg']}s avg\n"
        f"- Warm (matching canonical + overlay already on disk): {result['warm_seconds_avg']}s avg\n"
        f"- Speedup: {result['speedup_x']}x\n"
        f"- Platform: {result['platform']} / Python {result['python_version']}\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
