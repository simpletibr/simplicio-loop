import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.check_json_boundaries import check, load_policy, main

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 optional backport
    import tomli as tomllib  # type: ignore[no-redef]


@pytest.fixture
def policy_root(tmp_path: Path) -> Path:
    source = Path(__file__).parents[2]
    (tmp_path / "config").mkdir()
    (tmp_path / ".simplicio-loop").mkdir()
    (tmp_path / "config" / "json-boundaries.toml").write_text(
        (source / "config" / "json-boundaries.toml").read_text(), encoding="utf-8"
    )
    return tmp_path


def test_checked_in_state_is_inventory_classified():
    assert check(Path(__file__).parents[2]) == []


def test_checked_in_registry_carries_only_permanent_classifications():
    registry_path = Path(__file__).parents[2] / "config" / "json-boundaries.toml"
    registry = tomllib.loads(registry_path.read_text(encoding="utf-8"))
    permanent = {"path", "category", "owner", "reason"}
    offending = {
        entry["path"]: sorted(set(entry) - permanent)
        for entry in registry.get("exceptions", [])
        if set(entry) - permanent
    }
    assert offending == {}


def test_unclassified_internal_state_is_blocked(policy_root: Path):
    (policy_root / ".simplicio-loop" / "new-state.json").write_text("{}", encoding="utf-8")
    assert "UNCLASSIFIED .simplicio-loop/new-state.json" in check(policy_root)
    assert main(["--root", str(policy_root), "--strict"]) == 1


def test_disposable_runtime_probe_outputs_are_not_checked_in_state(policy_root: Path):
    for relative in (
        ".simplicio-loop/issue-422-runtime/run/effect-plan.json",
        ".simplicio-loop/update/first-party-adapters.json",
    ):
        path = policy_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    assert check(policy_root) == []


def test_dynamic_run_and_observability_folders_are_classified(policy_root: Path):
    for relative in (
        ".simplicio-loop/orchestrator/runs/run-20261019-7f3a/state.json",
        ".simplicio-loop/orchestrator/runs/run-20261019-7f3a/events.jsonl",
        ".simplicio-loop/orchestrator/runs/run-20261019-7f3a/receipts/build-apply.json",
        ".simplicio-loop/loop-runs/run-42/state.json",
        ".simplicio-loop/observability/dev-cli/events.jsonl",
        ".simplicio-loop/events.jsonl",
    ):
        path = policy_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    assert check(policy_root) == []


def test_directory_classification_does_not_cover_siblings_or_prefixes(policy_root: Path):
    for relative in (
        ".simplicio-loop/orchestrator/runs.json",
        ".simplicio-loop/orchestrator/runs-archive/state.json",
        ".simplicio-loop/events.json",
    ):
        path = policy_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    assert sorted(check(policy_root)) == [
        "UNCLASSIFIED .simplicio-loop/events.json",
        "UNCLASSIFIED .simplicio-loop/orchestrator/runs-archive/state.json",
        "UNCLASSIFIED .simplicio-loop/orchestrator/runs.json",
    ]


@pytest.mark.parametrize("path", [".simplicio-loop/", "elsewhere/"])
def test_directory_exception_must_lie_inside_an_internal_root(policy_root: Path, path: str):
    (policy_root / "config" / "json-boundaries.toml").write_text(
        "version=1\npolicy='internal-json-deny'\n"
        "[scanner]\ninternal_roots=['.simplicio-loop']\nformats=['.json']\n"
        f"[[exceptions]]\npath='{path}'\ncategory='runtime-ledger'\nowner='loop'\nreason='runtime output'\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="inside an internal root"):
        load_policy(policy_root)


@pytest.mark.parametrize(
    "path",
    [
        ".simplicio-loop/*.json",
        ".simplicio-loop/*/",
        ".simplicio-loop/../state.json",
        "/.simplicio-loop/state.json",
    ],
)
def test_exception_registry_rejects_non_exact_paths(policy_root: Path, path: str):
    registry = policy_root / "config" / "json-boundaries.toml"
    registry.write_text(
        "version=1\npolicy='internal-json-deny'\n"
        "[scanner]\ninternal_roots=['.simplicio-loop']\nformats=['.json']\n"
        f"[[exceptions]]\npath='{path}'\ncategory='runtime-state'\n"
        "owner='quality'\nreason='runtime output'\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exact path|normalized repository-relative"):
        load_policy(policy_root)


@pytest.mark.parametrize("missing", ["category", "owner", "reason"])
def test_exception_registry_requires_accountability(policy_root: Path, missing: str):
    fields = {"category": "runtime-state", "owner": "quality", "reason": "runtime output"}
    del fields[missing]
    extra = "\n".join(f"{key}='{value}'" for key, value in fields.items())
    (policy_root / "config" / "json-boundaries.toml").write_text(
        "version=1\npolicy='internal-json-deny'\n"
        "[scanner]\ninternal_roots=['.simplicio-loop']\nformats=['.json']\n"
        "[[exceptions]]\npath='.simplicio-loop/legacy.json'\n" + extra,
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=f"missing {missing}"):
        load_policy(policy_root)


@pytest.mark.parametrize("dated_key", ["expires='2099-01-01'", "target='hbi'"])
def test_exception_registry_rejects_dated_waivers_and_migration_targets(policy_root: Path, dated_key: str):
    (policy_root / "config" / "json-boundaries.toml").write_text(
        "version=1\npolicy='internal-json-deny'\n"
        "[scanner]\ninternal_roots=['.simplicio-loop']\nformats=['.json']\n"
        "[[exceptions]]\npath='.simplicio-loop/legacy.json'\ncategory='runtime-state'\n"
        f"owner='quality'\nreason='runtime output'\n{dated_key}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported keys"):
        load_policy(policy_root)


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_release_archive_cannot_recreate_internal_json(policy_root: Path, kind: str):
    payload_name = "release-root/.simplicio-loop/generated.json"
    if kind == "wheel":
        artifact = policy_root / "package.whl"
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.writestr(payload_name, "{}")
    else:
        artifact = policy_root / "package.tar.gz"
        content = b"{}"
        with tarfile.open(artifact, "w:gz") as archive:
            info = tarfile.TarInfo(payload_name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    assert check(policy_root, [artifact]) == [f"PACKAGED_INTERNAL_JSON {artifact.name}!{payload_name}"]


def test_external_json_in_release_archive_remains_allowed(policy_root: Path):
    artifact = policy_root / "package.whl"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("package/schema.json", "{}")
    assert check(policy_root, [artifact]) == []


def test_invalid_archive_fails_closed(policy_root: Path, capsys):
    artifact = policy_root / "broken.whl"
    artifact.write_bytes(b"not an archive")
    assert main(["--root", str(policy_root), "--artifact", str(artifact), "--strict"]) == 2
    assert "unsupported artifact archive" in capsys.readouterr().err


def test_artifact_directory_scans_every_release_archive(policy_root: Path, capsys):
    dist = policy_root / "dist"
    dist.mkdir()
    with zipfile.ZipFile(dist / "package.whl", "w") as archive:
        archive.writestr("package/schema.json", "{}")
    with tarfile.open(dist / "package.tar.gz", "w:gz") as archive:
        content = b"{}"
        info = tarfile.TarInfo("release/.simplicio-loop/state.json")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))

    assert main(["--root", str(policy_root), "--artifact-dir", str(dist), "--strict"]) == 1
    output = capsys.readouterr().out
    assert "PACKAGED_INTERNAL_JSON package.tar.gz!release/.simplicio-loop/state.json" in output


@pytest.mark.parametrize("directory", ["missing", "empty"])
def test_artifact_directory_fails_closed_without_release_archives(policy_root: Path, capsys, directory: str):
    artifact_dir = policy_root / directory
    if directory == "empty":
        artifact_dir.mkdir()

    assert main(["--root", str(policy_root), "--artifact-dir", str(artifact_dir), "--strict"]) == 2
    assert "json-boundaries: configuration error" in capsys.readouterr().err
