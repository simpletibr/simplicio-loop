#!/usr/bin/env python3
"""Exercise the installed MapperStore boundary in a no-network wheel matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path, PurePosixPath, PureWindowsPath

PROBE = r"""
import json
import pathlib
import simplicio
from simplicio.store_adapter import MapperStoreAdapter, storage_capabilities

root = pathlib.Path.cwd() / "target"
def materialized_files():
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    )

payload = storage_capabilities(root)
result = {
    "simplicio_module": str(pathlib.Path(simplicio.__file__).resolve()),
    "mapper_ready": payload["mapper_store"]["ready"],
    "mapper_reason": payload["mapper_store"]["reason"],
    "route": payload["route"],
    "materialized_before": materialized_files()
}
if EXPECT_READY:
    import simplicio_mapper
    result["mapper_module"] = str(pathlib.Path(simplicio_mapper.__file__).resolve())
    adapter = MapperStoreAdapter(root, "matrix")
    adapter.write("round-trip", {"status": "ok"})
    result["round_trip"] = adapter.read("round-trip")
else:
    result["materialized_after"] = materialized_files()
print(json.dumps(result, sort_keys=True))
"""


def _run(argv: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(argv)}\n"
            f"stdout={result.stdout[-2000:]}\nstderr={result.stderr[-2000:]}"
        )
    return result.stdout


def _python(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _installed(
    wheel: Path, *, system_site: bool, root: Path
) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    holder = tempfile.TemporaryDirectory(prefix="simplicio-mapper-matrix-")
    venv_dir = Path(holder.name)
    venv.EnvBuilder(with_pip=True, system_site_packages=system_site, clear=True).create(venv_dir)
    python = _python(venv_dir)
    _run(
        [str(python), "-m", "pip", "install", "--no-index", "--no-deps", "--force-reinstall", str(wheel)],
        cwd=root,
    )
    return python, holder


def _probe(
    python: Path,
    *,
    root: Path,
    ready: bool,
    extra_env: dict[str, str] | None = None,
) -> dict:
    with tempfile.TemporaryDirectory(prefix="simplicio-mapper-matrix-target-") as raw_target:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("SIMPLICIO_MAPPER_VERSION", None)
        if extra_env:
            env.update(extra_env)
        source = "EXPECT_READY = " + repr(ready) + "\n" + PROBE
        output = _run([str(python), "-c", source], cwd=Path(raw_target), env=env)
        payload = json.loads(output.strip().splitlines()[-1])
        module_path = Path(payload["simplicio_module"]).resolve()
        if root in module_path.parents:
            raise RuntimeError(f"installed probe imported checkout: {module_path}")
        if ready:
            mapper_path = Path(payload["mapper_module"]).resolve()
            if root in mapper_path.parents:
                raise RuntimeError(f"installed probe imported checkout Mapper: {mapper_path}")
            if payload.get("round_trip") != {"status": "ok"}:
                raise RuntimeError(f"installed round-trip failed: {payload}")
        elif payload.get("materialized_after") != payload.get("materialized_before"):
            raise RuntimeError(f"blocked lane materialized state: {payload}")
        return payload


def _partial_shim(root: Path) -> Path:
    shim = root / ".matrix-partial-shim"
    (shim / "simplicio_mapper" / "mapper").mkdir(parents=True, exist_ok=True)
    (shim / "simplicio_mapper" / "__init__.py").write_text("\n", encoding="utf-8")
    (shim / "simplicio_mapper" / "mapper" / "__init__.py").write_text("\n", encoding="utf-8")
    (shim / "simplicio_mapper" / "mapper" / "file_lock.py").write_text(
        "def acquire_lock_at(*args, **kwargs):\n    return None\n", encoding="utf-8"
    )
    return shim


def _path_portability() -> dict[str, object]:
    expected = (".simplicio", "mapper-store", "route.json")
    values = {}
    for name, path in {
        "linux": PurePosixPath("/tmp/project"),
        "macos": PurePosixPath("/private/tmp/project"),
        "windows": PureWindowsPath(r"C:\Temp\project"),
    }.items():
        route = path.joinpath(*expected)
        values[name] = route.parts[-3:] == expected
    return {"status": "PASS" if all(values.values()) else "FAIL", "values": values}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    dist = root / "dist"
    wheels = sorted(dist.glob("*.whl"))
    if not wheels:
        _run([sys.executable, "-m", "build", "--wheel", "--outdir", str(dist)], cwd=root)
        wheels = sorted(dist.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one wheel, found {len(wheels)}")
    wheel = wheels[0]
    lanes: dict[str, dict] = {}
    holders = []
    try:
        python, holder = _installed(wheel, system_site=False, root=root)
        holders.append(holder)
        lanes["mapper-absent"] = _probe(python, root=root, ready=False)

        python, holder = _installed(wheel, system_site=True, root=root)
        holders.append(holder)
        lanes["mapper-incompatible"] = _probe(
            python, root=root, ready=False, extra_env={"SIMPLICIO_MAPPER_VERSION": "0.0.0"}
        )
        shim = _partial_shim(root)
        lanes["mapper-capability-partial"] = _probe(
            python, root=root, ready=False, extra_env={"PYTHONPATH": str(shim)}
        )
        lanes["mapper-installed"] = _probe(python, root=root, ready=True)
    finally:
        for holder in holders:
            holder.cleanup()
    expected_reasons = {
        "mapper-absent": "mapper-package-not-installed",
        "mapper-incompatible": "mapper-version-incompatible",
        "mapper-capability-partial": "mapper-api-unavailable",
    }
    for name, reason in expected_reasons.items():
        if lanes[name]["mapper_ready"] or lanes[name]["mapper_reason"] != reason:
            raise RuntimeError(f"unexpected {name} lane: {lanes[name]}")
    paths = _path_portability()
    if paths["status"] != "PASS":
        raise RuntimeError(f"path portability failed: {paths}")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    print(
        json.dumps(
            {
                "schema": "simplicio-dev-cli.mapper-store-installed-matrix/v1",
                "wheel": str(wheel),
                "wheel_sha256": digest,
                "network": "disabled",
                "lanes": lanes,
                "platform_paths": paths,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
