"""Build identity: every mapper build names its origin, state dir and source commit."""

import json
import re
from pathlib import Path

from simplicio_mapper import build_identity as bi
from simplicio_mapper import build_stamp

SHA = re.compile(r"^[0-9a-f]{40}$")


def test_contract_constants_name_this_monorepo_and_the_loop_state_dir():
    assert bi.ORIGIN == "simplicio-loop/packages/mapper"
    assert bi.STATE_DIR == ".simplicio-loop"


def test_stamped_build_reports_the_commit_and_origin_it_was_built_from(tmp_path, monkeypatch):
    stamp = tmp_path / bi.STAMP_FILENAME
    stamp.write_text(json.dumps({"origin": bi.ORIGIN, "source_commit": "a" * 40}))
    monkeypatch.setattr(bi, "_STAMP_PATH", stamp)

    identity = bi.build_identity()

    assert identity["source"] == "build"
    assert identity["origin"] == bi.ORIGIN
    assert identity["source_commit"] == "a" * 40
    assert identity["state_dir"] == ".simplicio-loop"


def test_checkout_without_stamp_falls_back_to_the_git_head_of_the_monorepo(tmp_path, monkeypatch):
    monkeypatch.setattr(bi, "_STAMP_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(bi, "_checkout_commit", lambda: "b" * 40)

    identity = bi.build_identity()

    assert identity["source"] == "checkout"
    assert identity["origin"] == bi.ORIGIN
    assert identity["source_commit"] == "b" * 40


def test_unstamped_build_without_git_reports_no_origin_and_no_commit(tmp_path, monkeypatch):
    monkeypatch.setattr(bi, "_STAMP_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(bi, "_checkout_commit", lambda: None)

    identity = bi.build_identity()

    assert identity["source"] == "unstamped"
    assert identity["origin"] is None
    assert identity["source_commit"] is None


def test_write_stamp_records_origin_and_the_real_head_commit_of_the_source_tree(tmp_path):
    repo = tmp_path / "repo"
    (repo / "packages" / "mapper").mkdir(parents=True)
    import subprocess
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    out = tmp_path / "stamp.json"

    payload = build_stamp.write_stamp(repo, out)

    assert json.loads(out.read_text()) == payload
    assert payload["origin"] == bi.ORIGIN
    assert SHA.match(payload["source_commit"])


def test_write_stamp_outside_git_records_no_commit_instead_of_inventing_one(tmp_path):
    out = tmp_path / "stamp.json"

    payload = build_stamp.write_stamp(tmp_path, out)

    assert payload["source_commit"] is None
    assert Path(out).is_file()
