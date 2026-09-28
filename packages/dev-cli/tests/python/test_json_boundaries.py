import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.check_json_boundaries import check, load_policy, main


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


@pytest.mark.parametrize(
    "path", [".simplicio-loop/*.json", ".simplicio-loop/../state.json", "/.simplicio-loop/state.json"]
)
def test_exception_registry_rejects_non_exact_paths(policy_root: Path, path: str):
    registry = policy_root / "config" / "json-boundaries.toml"
    registry.write_text(
        "version=1\npolicy='internal-json-deny'\n"
        "[scanner]\ninternal_roots=['.simplicio-loop']\nformats=['.json']\n"
        f"[[exceptions]]\npath='{path}'\ncategory='legacy'\ntarget='hbi'\n"
        "owner='quality'\nreason='migration'\nexpires='2099-01-01'\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exact path|normalized repository-relative"):
        load_policy(policy_root)


@pytest.mark.parametrize("missing", ["owner", "reason", "expires"])
def test_exception_registry_requires_accountability(policy_root: Path, missing: str):
    fields = {"owner": "quality", "reason": "bounded legacy migration", "expires": "2099-01-01"}
    del fields[missing]
    extra = "\n".join(f"{key}='{value}'" for key, value in fields.items())
    (policy_root / "config" / "json-boundaries.toml").write_text(
        "version=1\npolicy='internal-json-deny'\n"
        "[scanner]\ninternal_roots=['.simplicio-loop']\nformats=['.json']\n"
        "[[exceptions]]\npath='.simplicio-loop/legacy.json'\ncategory='legacy'\ntarget='hbi'\n" + extra,
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=f"missing {missing}"):
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
