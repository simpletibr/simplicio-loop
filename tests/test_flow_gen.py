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
