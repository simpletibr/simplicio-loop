#!/usr/bin/env python3
"""Smoke test of the standalone binary OUTSIDE the source tree (issue #1576).

The binary is copied alone into an empty temp directory and run with a scrubbed environment: no
PYTHONPATH, a short PATH, a temp HOME. The checks are the product requirement: version, help,
``doctor stack``, ``preflight``, the two-command hot path (``turbo``: the bundled mapper surveys,
the bundled dev-cli applies), ``install``, and the data of the three packages.

Give ``--reference-bin DIR`` (the ``bin`` directory of a venv with the wheel installed) to run the
same commands from the wheel and compare the results. Give ``--wheel FILE`` to check that every
non-Python file of the wheel, and every module, is inside the binary.

    python3 scripts/smoke_binary.py dist/binary/simplicio-loop-v3.48.1-linux-x86_64 \\
        --wheel dist/simplicio_loop-3.48.1-py3-none-any.whl --reference-bin /tmp/slb/bin
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_binary import parse_asset_name  # noqa: E402

PACKAGES = ("simplicio_loop", "simplicio_mapper", "simplicio")
PLAN = {"operations": [{"path": "app.py", "find": '"hello "', "replace": '"hi "'}]}
# Runs inside the binary through `simplicio-loop -c`. argv[1] is a JSON file that lists what to find.
INSIDE_CHECK = (
    "import importlib.util, json, os, sys; spec = json.load(open(sys.argv[1])); base = sys._MEIPASS; "
    "missing_files = [p for p in spec['files'] if not os.path.exists(os.path.join(base, p))]; "
    "missing_modules = [m for m in spec['modules'] if importlib.util.find_spec(m) is None]; "
    "print(json.dumps({'files': len(spec['files']), 'modules': len(spec['modules']), "
    "'missing_files': missing_files, 'missing_modules': missing_modules, "
    "'operator': __import__('shutil').which('simplicio-mapper')}))"
)


def scrubbed_env(home: Path, system: Optional[str] = None) -> dict[str, str]:
    """An environment with no PYTHONPATH, a short PATH and a temp HOME."""
    if (system or os.name) == "nt":
        root = os.environ.get("SystemRoot", r"C:\Windows")
        return {"PATH": rf"{root}\System32;{root}", "SystemRoot": root, "USERPROFILE": str(home),
                "HOME": str(home), "TEMP": str(home / "tmp"), "TMP": str(home / "tmp")}
    return {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home / "tmp"), "LANG": "C.UTF-8"}


def expected_from_wheel(wheel: Path) -> dict[str, list[str]]:
    """List what the binary must hold: data files (and the .py files under _bundle) and modules."""
    files, modules = [], []
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    for name in sorted(names):
        parts = name.split("/")
        if parts[0] not in PACKAGES or name.endswith("/") or "__pycache__" in parts:
            continue
        # A .py file is a module only when every directory above it is a package.
        is_module = name.endswith(".py") and all("/".join(parts[:i]) + "/__init__.py" in names for i in range(1, len(parts)))
        if is_module:
            modules.append(name[:-3].replace("/", ".").removesuffix(".__init__"))
        else:
            files.append(name)
    return {"files": files, "modules": modules}


def normalize_doctor(report: dict[str, Any]) -> dict[str, Any]:
    """Keep what must be equal between the binary and the wheel; drop paths and hashes."""
    components = sorted((item["name"], item.get("version"), item.get("available")) for item in report["components"])
    return {"status": report.get("status"), "components": components, "routes": report.get("routes")}


def tree_digest(root: Path, skip: Sequence[str] = ()) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file() and path.name not in skip
    }


def measure_startup(command: Sequence[str], env: dict[str, str], runs: int = 10) -> dict[str, float]:
    """Wall time of ``runs`` starts (first = cold) and the largest peak RSS. POSIX only."""
    import resource  # noqa: F401  (POSIX; the import fails on Windows, which is reported by the caller)
    walls, peaks = [], []
    for _ in range(runs):
        started = time.perf_counter()
        pid = os.fork()
        if pid == 0:
            devnull = os.open(os.devnull, os.O_RDWR)
            for fd in (0, 1, 2):
                os.dup2(devnull, fd)
            try:
                os.execve(command[0], list(command), env)
            finally:
                os._exit(127)
        _, _, usage = os.wait4(pid, 0)
        walls.append(time.perf_counter() - started)
        peaks.append(usage.ru_maxrss / 1024)
    return {"runs": runs, "first_s": round(walls[0], 3), "warm_median_s": round(statistics.median(walls[1:]), 3),
            "min_s": round(min(walls), 3), "peak_rss_mib": round(max(peaks), 1)}


class Smoke:
    def __init__(self, binary: Path, work: Path, reference_bin: Optional[Path], wheel: Optional[Path],
                 expected_version: Optional[str]) -> None:
        self.work, self.wheel, self.reference_bin = work, wheel, reference_bin
        self.home = work / "home"
        (self.home / "tmp").mkdir(parents=True)
        self.env = scrubbed_env(self.home)
        bin_dir = work / "bin"
        bin_dir.mkdir()
        self.long_name = bin_dir / binary.name
        shutil.copy2(binary, self.long_name)  # ONLY the executable
        self.exe = bin_dir / "simplicio-loop"
        parsed = parse_asset_name(binary.name)
        self.expected = expected_version or (parsed[0] if parsed else None)
        self.results: list[dict[str, Any]] = []

    def run(self, command: Sequence[str], *, cwd: Optional[Path] = None, stdin: Optional[str] = None,
            env: Optional[dict[str, str]] = None, timeout: int = 600) -> subprocess.CompletedProcess:
        return subprocess.run(list(command), cwd=cwd or self.work, env=env or self.env, input=stdin,
                              capture_output=True, text=True, timeout=timeout,
                              stdin=None if stdin is not None else subprocess.DEVNULL)

    def reference(self, *args: str, cwd: Optional[Path] = None, stdin: Optional[str] = None) -> subprocess.CompletedProcess:
        env = dict(self.env, PATH=os.pathsep.join([str(self.reference_bin), self.env["PATH"]]))
        return self.run([str(self.reference_bin / "simplicio-loop"), *args], cwd=cwd, stdin=stdin, env=env)

    def check(self, name: str, function: Callable[[], str]) -> None:
        started = time.perf_counter()
        try:
            detail, ok = function(), True
        except AssertionError as error:
            detail, ok = f"{error}", False
        except (OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
            detail, ok = f"{type(error).__name__}: {error}", False
        self.results.append({"check": name, "ok": ok, "detail": detail[:600], "seconds": round(time.perf_counter() - started, 2)})

    # --- checks -----------------------------------------------------------------------------
    def version(self) -> str:
        done = self.run([str(self.long_name), "--version"])  # under the long release name
        os.replace(self.long_name, self.exe)
        assert done.returncode == 0, f"exit {done.returncode}: {done.stderr[-300:]}"
        assert self.expected and done.stdout.strip() == f"simplicio-loop {self.expected}", done.stdout
        return done.stdout.strip()

    def help(self) -> str:
        done = self.run([str(self.exe), "--help"])
        assert done.returncode == 0 and "usage: simplicio-loop" in done.stdout, done.stderr[-300:]
        return f"{len(done.stdout.splitlines())} lines"

    def doctor(self) -> str:
        done = self.run([str(self.exe), "doctor", "stack", "--json"])
        report = json.loads(done.stdout)
        assert report["status"] == "READY", done.stdout[:400]
        assert all(item["available"] for item in report["components"]), done.stdout[:400]
        names = sorted(item["name"] for item in report["components"])
        if self.reference_bin:
            reference = json.loads(self.reference("doctor", "stack", "--json").stdout)
            assert normalize_doctor(report) == normalize_doctor(reference), "differs from the wheel install"
        return f"READY {names}"

    def preflight(self) -> str:
        repo = self.work / "empty"
        repo.mkdir()
        done = self.run([str(self.exe), "preflight", "--strict", "--json"], cwd=repo)
        report = json.loads(done.stdout)
        assert done.returncode == 0 and report["all_present"] is True, done.stdout[:400]
        return "operators: " + ", ".join(f"{op['name']} {op['version']}" for op in report["operators"])

    def _tiny_repo(self, name: str) -> Path:
        repo = self.work / name
        repo.mkdir()
        (repo / "app.py").write_text('def greet(name):\n    return "hello " + name\n')
        (repo / "test_app.py").write_text('from app import greet\n\ndef test_greet():\n    assert greet("x") == "hello x"\n')
        for args in (("init", "-q"), ("add", "."), ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")):
            self.run(["git", *args], cwd=repo)
        return repo

    def _hot_path(self, repo: Path, run_program: Callable[..., subprocess.CompletedProcess]) -> dict[str, Any]:
        orient = json.loads(run_program("turbo", "--repo", ".", "--task", "change greeting from hello to hi in app.py", cwd=repo).stdout)
        assert orient["status"] == "needs_plan" and "app.py" in orient["files"], str(orient)[:300]
        applied = json.loads(run_program("turbo", "--repo", ".", "--apply", "-", "--run-id", orient["run_id"], cwd=repo,
                                         stdin=json.dumps(PLAN)).stdout)
        return {"orient": orient["status"], "apply": applied["status"], "applied": applied["applied"],
                "failed": applied["failed"], "content": (repo / "app.py").read_text()}

    def hot_path(self) -> str:
        repo = self._tiny_repo("repo-binary")
        result = self._hot_path(repo, lambda *a, cwd, stdin=None: self.run([str(self.exe), *a], cwd=cwd, stdin=stdin))
        assert result["apply"] == "ok" and result["applied"] == ["app.py"] and 'return "hi " + name' in result["content"], str(result)
        if self.reference_bin:
            expected = self._hot_path(self._tiny_repo("repo-wheel"),
                                      lambda *a, cwd, stdin=None: self.reference(*a, cwd=cwd, stdin=stdin))
            assert result == expected, f"binary {result} != wheel {expected}"
        return f"orient {result['orient']}, apply {result['apply']}, applied {result['applied']}"

    def install(self) -> str:
        target = self.work / "proj-binary"
        target.mkdir()
        help_text = self.run([str(self.exe), "install", "--help"]).stdout
        if "--check" in help_text:
            checked = self.run([str(self.exe), "install", "--check", "--target", str(target)])
            assert checked.returncode == 0, checked.stdout[-300:] + checked.stderr[-300:]
        else:
            checked = self.run([str(self.exe), "install", "--target", str(target), "--dry-run"])
            assert checked.returncode == 0 and not any(target.iterdir()), "dry run wrote files"
        done = self.run([str(self.exe), "install", "--target", str(target)])
        assert done.returncode == 0, done.stdout[-300:] + done.stderr[-300:]
        files = tree_digest(target, skip=("install-ownership.json",))
        assert any(name.endswith("SKILL.md") for name in files), "no skill was installed"
        mode = "--check" if "--check" in help_text else "--dry-run (no --check flag yet)"
        if self.reference_bin:
            other = self.work / "proj-wheel"
            other.mkdir()
            self.reference("install", "--target", str(other))
            assert files == tree_digest(other, skip=("install-ownership.json",)), "installed files differ from the wheel install"
        return f"{len(files)} files installed; dry run used {mode}"

    def data(self) -> str:
        assert self.wheel, "skipped: pass --wheel to compare against the wheel"
        expected = expected_from_wheel(self.wheel)
        spec = self.work / "expected.json"
        spec.write_text(json.dumps(expected))
        done = self.run([str(self.exe), "-c", INSIDE_CHECK, str(spec)])
        assert done.returncode == 0, done.stderr[-400:]
        report = json.loads(done.stdout)
        assert not report["missing_files"] and not report["missing_modules"], (
            f"missing files {report['missing_files'][:5]}, modules {report['missing_modules'][:5]}")
        assert any(name.startswith("simplicio_loop/dashboard/static/") for name in expected["files"]), "the wheel has no dashboard static files"
        assert report["operator"] and Path(report["operator"]).is_relative_to(self.home), report["operator"]
        return f"{report['files']} data files and {report['modules']} modules found; simplicio-mapper -> {report['operator']}"

    def operators(self) -> str:
        names = {"simplicio-mapper": "simplicio-mapper", "simplicio-dev-cli": "simplicio-cli"}
        out = []
        for command in names:
            done = self.run([str(self.exe), "-c", f"import shutil, subprocess, sys; sys.exit(subprocess.call([shutil.which('{command}'), '--version']))"])
            assert done.returncode == 0 and done.stdout.strip(), f"{command}: exit {done.returncode} {done.stderr[-200:]}"
            out.append(f"{command}: {done.stdout.strip().splitlines()[0]}")
        return "; ".join(out)

    def run_all(self) -> list[dict[str, Any]]:
        self.check("version", self.version)
        for name, function in (("help", self.help), ("doctor stack", self.doctor), ("preflight", self.preflight),
                               ("operators by name", self.operators), ("hot path (turbo orient + apply)", self.hot_path),
                               ("install", self.install), ("bundled data and modules", self.data)):
            self.check(name, function)
        return self.results


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="smoke_binary", description=__doc__.split("\n\n")[0])
    parser.add_argument("binary", type=Path)
    parser.add_argument("--wheel", type=Path, help="wheel to compare the bundled files and modules with")
    parser.add_argument("--reference-bin", type=Path, help="bin directory of a venv with the wheel installed")
    parser.add_argument("--expected-version", help="default: the version in the file name")
    parser.add_argument("--timing", type=int, default=0, metavar="N", help="also measure N starts of --version")
    parser.add_argument("--workdir", type=Path, help="parent directory for the temp dir (default: the system temp)")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)
    work = Path(tempfile.mkdtemp(prefix="slsmoke-", dir=args.workdir))
    try:
        smoke = Smoke(args.binary.resolve(), work, args.reference_bin, args.wheel, args.expected_version)
        results = smoke.run_all()
        report: dict[str, Any] = {"binary": str(args.binary), "bytes": args.binary.stat().st_size, "checks": results,
                                  "ok": all(item["ok"] for item in results)}
        if args.timing:
            report["binary_startup"] = measure_startup([str(smoke.exe), "--version"], smoke.env, args.timing)
            if args.reference_bin:
                reference = str(args.reference_bin / "simplicio-loop")
                report["wheel_startup"] = measure_startup([reference, "--version"], dict(smoke.env, PATH=str(args.reference_bin) + ":/usr/bin:/bin"), args.timing)
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
