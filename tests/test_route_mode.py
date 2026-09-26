from __future__ import annotations
import json,os,subprocess,sys,time
from pathlib import Path
from scripts import route_mode
REPO=Path(__file__).parents[1]
def write_survey(root,files,symbols=(),edges=()):
    d=root/".simplicio-loop"; d.mkdir(exist_ok=True)
    (d/"project-map.json").write_text(json.dumps({"files":[{"path":p} for p in files]}),encoding="utf-8")
    (d/"symbol-index.json").write_text(json.dumps({"symbols":list(symbols)}),encoding="utf-8")
    (d/"call-graph.json").write_text(json.dumps({"edges":list(edges)}),encoding="utf-8")
def reference(root):
    write_survey(root,["src/service.py","src/caller.py","frontend/app.ts"],[{"name":"GetRestEletrica","qualified_name":"src/service.py::GetRestEletrica","defined_in":"src/service.py"}],[{"source_file":"src/caller.py","target_file":"src/service.py"}])
def cli(root,*args):
    return subprocess.run([sys.executable,"scripts/route_mode.py","--root",str(root),*args],cwd=REPO,text=True,capture_output=True)
def test_reference_fast_path_and_anchor(tmp_path):
    reference(tmp_path); anchor=tmp_path/"anchor.json"; anchor.write_text(json.dumps({"criteria":[]}),encoding="utf-8"); goal="Fix GetRestEletrica in src/service.py"
    result=route_mode.decide(tmp_path,goal,map_dir=tmp_path/".simplicio-loop")
    assert result["mode"]=="fast-path" and result["measurements"]["goal_files"]==1 and result["measurements"]["fan_in"]==1
    out=cli(tmp_path,"--goal",goal,"--map-dir",str(tmp_path/".simplicio-loop"),"--anchor",str(anchor)); assert out.returncode==0
    assert json.loads(anchor.read_text())["route_mode"]["mode"]=="fast-path"
def test_vague_multi_unavailable_and_sensitive_are_converge(tmp_path):
    reference(tmp_path)
    assert route_mode.decide(tmp_path,"Improve performance",map_dir=tmp_path/".simplicio-loop")["mode"]=="converge"
    assert route_mode.decide(tmp_path,"Update src/service.py and frontend/app.ts",map_dir=tmp_path/".simplicio-loop")["mode"]=="converge"
    assert route_mode.decide(tmp_path,"Fix x",map_dir=tmp_path/".missing")["measurements"]["survey_available"] is False
    write_survey(tmp_path,["contracts/api.py"],[{"name":"Api","defined_in":"contracts/api.py"}])
    assert route_mode.decide(tmp_path,"Change Api in contracts/api.py",map_dir=tmp_path/".simplicio-loop")["mode"]=="converge"
def test_hub_force_and_only_converge_override(tmp_path):
    write_survey(tmp_path,["src/hub.py"],edges=[{"source_file":"a.py","target_file":"src/hub.py"},{"source_file":"b.py","target_file":"src/hub.py"}])
    result=route_mode.decide(tmp_path,"Change src/hub.py",map_dir=tmp_path/".simplicio-loop")
    assert result["measurements"]["fan_in"]==2 and result["mode"]=="converge"
    reference(tmp_path); forced=route_mode.decide(tmp_path,"Fix GetRestEletrica in src/service.py",map_dir=tmp_path/".simplicio-loop",force_converge=True)
    assert forced["mode"]=="converge" and forced["force_converge"]; assert cli(tmp_path,"--goal","x","--force-fast-path").returncode!=0
def test_cli_json_and_benchmark(tmp_path):
    reference(tmp_path); out=cli(tmp_path,"--goal","Fix GetRestEletrica in src/service.py","--map-dir",str(tmp_path/".simplicio-loop"))
    assert out.returncode==0 and json.loads(out.stdout)["schema"]==route_mode.SCHEMA
    start=time.perf_counter()
    for _ in range(20): assert route_mode.decide(tmp_path,"Fix GetRestEletrica in src/service.py",map_dir=tmp_path/".simplicio-loop")["mode"]=="fast-path"
    assert (time.perf_counter()-start)/20<.1

def test_turn_header_includes_measured_route(tmp_path):
    anchor = tmp_path / "anchor.json"
    anchor.write_text(json.dumps({"item": 526, "criteria": [{"status": "pending"}],
                                  "route_mode": {"mode": "fast-path", "justification": "goal->1 file, fan-in 1, no sensitive surface"}}))
    progress = tmp_path / "progress"
    progress.mkdir()
    env = os.environ.copy()
    env.update({"SIMPLICIO_ANCHOR_FILE": str(anchor), "SIMPLICIO_PROGRESS_DIR": str(progress)})
    result = subprocess.run([sys.executable, "scripts/loop_progress.py", "render", "--turn-header"],
                            cwd=REPO, text=True, capture_output=True, env=env)
    assert result.returncode == 0
    assert "mode=fast-path: goal->1 file" in result.stdout

def test_evidence_fallback_and_invalid_anchor_are_safe(tmp_path):
    write_survey(tmp_path, ["src/service.py"], symbols=[{"name": "Service", "evidence": {"file": "src/service.py"}}])
    assert route_mode.decide(tmp_path, "Fix Service", map_dir=tmp_path / ".simplicio-loop")["mode"] == "fast-path"
    assert route_mode.record_anchor(tmp_path / "missing.json", {}) is False
    broken = tmp_path / "broken.json"
    broken.write_text("[]", encoding="utf-8")
    assert route_mode.record_anchor(broken, {}) is False
