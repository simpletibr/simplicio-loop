import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import flow_gen  # noqa: E402


def test_flow_sources_exist():
    flow = flow_gen.load()
    missing = [n["source"] for n in flow["nodes"] if not (ROOT / n["source"]).exists()]
    assert missing == []


def test_edges_reference_known_nodes_and_cover_all_nodes():
    flow = flow_gen.load()
    ids = {n["id"] for n in flow["nodes"]}
    used = set()
    for e in flow["edges"]:
        assert e[0] in ids and e[1] in ids
        used.update(e[:2])
    assert used == ids


def test_generation_is_deterministic_and_committed_artifacts_fresh():
    flow = flow_gen.load()
    assert flow_gen.to_mermaid(flow) == flow_gen.to_mermaid(flow_gen.load())
    assert flow_gen.to_langflow(flow) == flow_gen.to_langflow(flow_gen.load())
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "flow_gen.py"), "check"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout
    assert json.loads(out.stdout)["status"] == "fresh"


def test_run_diagram_marks_done_running_pending_from_real_progress_state():
    snap = {"step": "operate", "step_index": 5, "steps_total": 9, "run_state": "running"}
    mmd = flow_gen.to_run_mermaid(flow_gen.load(), snap)
    assert "class preflight,survey,backlog,anchor,turbo done" in mmd
    assert "class apply,strict,human running" in mmd
    assert "class claim,journal,pr,merge,promise,stop pending" in mmd
    assert flow_gen.to_run_mermaid(flow_gen.load(), snap) == mmd


def test_run_diagram_without_progress_state_is_all_unknown_not_invented():
    mmd = flow_gen.to_run_mermaid(flow_gen.load(), {})
    assert "done" not in mmd.split("classDef")[0] and "class " not in mmd.replace("classDef", "")


def test_run_cli_writes_diagram_next_to_report(tmp_path):
    snap = tmp_path / "progress.json"
    snap.write_text(json.dumps({"step": "survey", "step_index": 2, "steps_total": 9}))
    out = tmp_path / "run.mmd"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "flow_gen.py"), "run",
                        "--progress", str(snap), "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "class survey running" in out.read_text()
    missing = subprocess.run([sys.executable, str(ROOT / "scripts" / "flow_gen.py"), "run",
                              "--progress", str(tmp_path / "nope.json"), "--out", str(out)],
                             capture_output=True, text=True)
    assert missing.returncode == 4 and json.loads(missing.stdout)["status"] == "blocked"
