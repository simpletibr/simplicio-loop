"""bench/swebench runner (#1819): arms, env config, --dry-run, raw JSON in the bench/llm_ab schema.

No model, no network, no docker: the agent and the evaluator are injected fakes. The live adapters
(OpenCode, swebench evaluator) are exercised only through their pure helpers. The committed manifest is a
TEMPLATE, so every plan here is built from a SYNTHETIC verified manifest generated in tmp_path.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SWE = REPO / "bench" / "swebench"
sys.path.insert(0, str(SWE))
sys.path.insert(0, str(REPO / "bench" / "llm_ab"))

import swe_common as common
import swe_manifest as sm
import swe_runner as rn

SECRET = "sk-or-TOPSECRET-do-not-print"
PRICES = {
    "m/one": {"model": "m/one", "fetched_at": "2000-01-01T00:00:00+00:00", "available": True, "prompt": 1e-06,
              "completion": 2e-06, "input_cache_read": None, "input_cache_write": None, "internal_reasoning": None},
    "m/two": {"model": "m/two", "fetched_at": "2000-01-01T00:00:00+00:00", "available": True, "prompt": 3e-06,
              "completion": 6e-06, "input_cache_read": None, "input_cache_write": None, "internal_reasoning": None},
}
DATASET = {"name": "toy/dataset", "split": "test", "revision": "a" * 40}


def _manifest(n=30):
    """A SYNTHETIC VERIFIED-shaped manifest: invented IDs o__r-1..o__r-n, digested like a real one.

    Built directly (not by sm.build_manifest) so small n can exercise plan and execute logic; the CLI
    still demands n >= 30 and the tests that need that refusal truncate a 30-task manifest.
    """
    rows = [{"instance_id": f"o__r-{i}", "repo": "o/r", "base_commit": "c" * 40} for i in range(1, n + 1)]
    return {"schema": sm.SCHEMA, "status": sm.STATUS_VERIFIED, "dataset": dict(DATASET),
            "selection": {"algorithm": sm.ALGORITHM, "rule": sm.RULE, "seed": "toy", "n": n, "pool_size": n + 10,
                          "pool_sha256": hashlib.sha256(b"synthetic pool").hexdigest(), "allocation": {"o/r": n}},
            "instances": rows,
            "manifest_id": sm.compute_manifest_id(DATASET, [r["instance_id"] for r in rows])}


def _write_manifest(tmp_path, n=30):
    """n < 30 truncates a valid 30-task manifest and re-digests it, so only the runner's own n-check can refuse it."""
    man = _manifest(30)
    if n < 30:
        man["instances"] = man["instances"][:n]
        man["manifest_id"] = sm.compute_manifest_id(man["dataset"], [r["instance_id"] for r in man["instances"]])
    p = tmp_path / "manifest.json"
    p.write_text(sm.dumps(man), encoding="utf-8")
    return p


def _env(tmp_path, models="m/one,m/two", manifest=None):
    keys = tmp_path / "keys.env"
    keys.write_text(f"OR_KEY_NORMAL={SECRET}\nOR_KEY_SIMPLICIO={SECRET}2\n", encoding="utf-8")
    man = manifest or _manifest(30)
    inst = tmp_path / "instances.json"
    inst.write_text(json.dumps([{"instance_id": r["instance_id"], "repo": r["repo"],
                                 "base_commit": r["base_commit"], "problem_statement": "p"}
                                for r in man["instances"]]), encoding="utf-8")
    opencode = tmp_path / "opencode"
    opencode.write_text("#!/bin/sh\n", encoding="utf-8")
    opencode.chmod(0o755)
    return {"SIMPLICIO_SWEBENCH_MODELS": models, "SIMPLICIO_BENCH_KEYS": str(keys),
            "SIMPLICIO_BENCH_OPENCODE_BIN": str(opencode), "SIMPLICIO_SWEBENCH_INSTANCES": str(inst)}


PROBES_OK = {"which": lambda name: f"/usr/bin/{name}", "has_module": lambda name: True}


def _argv(tmp_path, *extra, manifest_n=30, budget="5"):
    return ["--manifest", str(_write_manifest(tmp_path, manifest_n)), "--out", str(tmp_path / "results"),
            "--budget-usd", budget, *extra]


# --- plan ----------------------------------------------------------------------------------------------------

def test_plan_is_instances_x_models_x_arms_in_a_stable_instance_major_order():
    man = _manifest(3)
    plan = rn.build_plan(man, ["m/one", "m/two"], ["normal", "simplicio"])
    assert len(plan) == 3 * 2 * 2
    assert plan == rn.build_plan(man, ["m/one", "m/two"], ["normal", "simplicio"])
    assert [(j["instance"]["instance_id"], j["model"], j["arm"]) for j in plan[:4]] == [
        ("o__r-1", "m/one", "normal"), ("o__r-1", "m/one", "simplicio"),
        ("o__r-1", "m/two", "normal"), ("o__r-1", "m/two", "simplicio")]
    assert len({j["run_key"] for j in plan}) == len(plan)


def test_limit_keeps_whole_instances_so_arms_stay_paired():
    plan = rn.build_plan(_manifest(4), ["m/one", "m/two"], ["normal", "simplicio"], limit=2)
    assert {j["instance"]["instance_id"] for j in plan} == {"o__r-1", "o__r-2"} and len(plan) == 8


def test_arms_are_the_llm_ab_loop_off_and_loop_on_arms():
    assert rn.ARMS == ("normal", "simplicio")
    assert rn.arm_prompt_prefix("normal") == ""
    assert rn.arm_prompt_prefix("simplicio") == "/simplicio-loop "
    assert "OFF" in common.ARM_LABELS["normal"] and "ON" in common.ARM_LABELS["simplicio"]


def test_models_come_from_the_env_variable_and_are_validated():
    assert rn.parse_models("a/x, b/y ,a/x") == ["a/x", "b/y", "a/x"]
    assert rn.parse_models("") == []
    assert rn.validate_models(["a/x", "b/y"]) == []
    assert any("duplicate" in p for p in rn.validate_models(["a/x", "a/x"]))
    assert any("malformed" in p for p in rn.validate_models(["a/x", "bad model!"]))
    assert any("at least 2" in p for p in rn.validate_models(["a/x"]))


# --- --dry-run and config refusals ---------------------------------------------------------------------------

def test_dry_run_validates_prints_the_plan_and_writes_nothing(tmp_path, capsys):
    env = _env(tmp_path)
    argv = _argv(tmp_path, "--dry-run", "--limit", "2")
    before = sorted(p.name for p in tmp_path.iterdir())
    rc = rn.main(argv, env=env, probes=PROBES_OK)
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY RUN" in out and "8 runs" in out and "writes nothing" in out
    assert not (tmp_path / "results").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert SECRET not in out


def test_dry_run_never_creates_the_default_results_directory(tmp_path):
    default = SWE / "results"
    existed = default.exists()
    rn.main(["--dry-run", "--budget-usd", "1"], env={}, probes=PROBES_OK)  # invalid config: still writes nothing
    assert default.exists() == existed


def test_committed_template_manifest_is_refused_with_a_blocked_message(tmp_path, capsys):
    argv = ["--out", str(tmp_path / "results"), "--budget-usd", "50", "--dry-run"]
    assert rn.main(argv, env=_env(tmp_path), probes=PROBES_OK) == 2
    err = capsys.readouterr().err
    assert "TEMPLATE" in err and "BLOCKED" in err and "swe_manifest.py build" in err
    assert not (tmp_path / "results").exists()


def test_dry_run_needs_at_least_two_models(tmp_path, capsys):
    rc = rn.main(_argv(tmp_path, "--dry-run"), env=_env(tmp_path, models="m/one"), probes=PROBES_OK)
    assert rc == 2
    assert "at least 2" in capsys.readouterr().err


def test_dry_run_rejects_duplicate_and_malformed_models(tmp_path, capsys):
    assert rn.main(_argv(tmp_path, "--dry-run"), env=_env(tmp_path, models="m/one,m/one"), probes=PROBES_OK) == 2
    assert "duplicate" in capsys.readouterr().err
    assert rn.main(_argv(tmp_path, "--dry-run"), env=_env(tmp_path, models="m/one,bad model!"),
                   probes=PROBES_OK) == 2
    assert "malformed" in capsys.readouterr().err


def test_dry_run_rejects_an_unknown_arm(tmp_path, capsys):
    assert rn.main(_argv(tmp_path, "--dry-run", "--arms", "normal,turbo"), env=_env(tmp_path),
                   probes=PROBES_OK) == 2
    assert "unknown arm" in capsys.readouterr().err


def test_dry_run_flags_missing_keys_without_printing_secrets(tmp_path, capsys):
    env = _env(tmp_path)
    Path(env["SIMPLICIO_BENCH_KEYS"]).write_text("OR_KEY_NORMAL=" + SECRET + "\n", encoding="utf-8")
    assert rn.main(_argv(tmp_path, "--dry-run"), env=env, probes=PROBES_OK) == 2
    cap = capsys.readouterr()
    assert "OR_KEY_SIMPLICIO" in cap.err and SECRET not in cap.out + cap.err
    env.pop("SIMPLICIO_BENCH_KEYS")
    assert rn.main(_argv(tmp_path, "--dry-run"), env=env, probes=PROBES_OK) == 2
    assert "SIMPLICIO_BENCH_KEYS" in capsys.readouterr().err


def test_dry_run_flags_a_missing_instances_cache(tmp_path, capsys):
    env = _env(tmp_path)
    Path(env["SIMPLICIO_SWEBENCH_INSTANCES"]).unlink()
    assert rn.main(_argv(tmp_path, "--dry-run"), env=env, probes=PROBES_OK) == 2
    assert "SIMPLICIO_SWEBENCH_INSTANCES" in capsys.readouterr().err


def test_dry_run_reports_every_missing_toolchain_piece(tmp_path, capsys):
    probes = {"which": lambda name: None, "has_module": lambda name: False}
    assert rn.main(_argv(tmp_path, "--dry-run"), env=_env(tmp_path), probes=probes) == 2
    err = capsys.readouterr().err
    for needle in ("docker", "swebench", "git"):
        assert needle in err


def test_a_budget_is_required_and_must_be_positive(tmp_path, capsys):
    argv = ["--manifest", str(_write_manifest(tmp_path)), "--out", str(tmp_path / "results"), "--dry-run"]
    assert rn.main(argv, env=_env(tmp_path), probes=PROBES_OK) == 2
    assert "--budget-usd" in capsys.readouterr().err
    assert rn.main(argv + ["--budget-usd", "0"], env=_env(tmp_path), probes=PROBES_OK) == 2


def test_a_manifest_under_30_tasks_is_rejected(tmp_path, capsys):
    assert rn.main(_argv(tmp_path, "--dry-run", manifest_n=29), env=_env(tmp_path), probes=PROBES_OK) == 2
    assert "30" in capsys.readouterr().err


def test_a_tampered_manifest_id_is_rejected(tmp_path, capsys):
    man = _manifest(30)
    man["manifest_id"] = "0" * 64
    p = tmp_path / "manifest.json"
    p.write_text(sm.dumps(man), encoding="utf-8")
    argv = ["--manifest", str(p), "--out", str(tmp_path / "results"), "--budget-usd", "1", "--dry-run"]
    assert rn.main(argv, env=_env(tmp_path), probes=PROBES_OK) == 2
    assert "manifest_id" in capsys.readouterr().err


def test_dry_run_on_a_verified_manifest_plans_the_full_matrix(tmp_path, capsys):
    assert rn.main(_argv(tmp_path, "--dry-run"), env=_env(tmp_path), probes=PROBES_OK) == 0
    assert "120 runs" in capsys.readouterr().out  # 30 instances x 2 models x 2 arms


# --- executing a plan (fakes) ----------------------------------------------------------------------------------

class _Agent:
    def __init__(self, fail_on=None, timeout_on=None):
        self.calls = []
        self.fail_on, self.timeout_on = fail_on, timeout_on

    def __call__(self, job):
        self.calls.append(job["run_key"])
        if self.timeout_on and self.timeout_on in job["run_key"]:
            raise rn.AgentTimeout("agent exceeded its time limit")
        if self.fail_on and self.fail_on in job["run_key"]:
            raise RuntimeError("HTTP 402 from provider")
        return {"patch": "diff --git a/x b/x\n", "turns": 3, "final_text": "done",
                "totals": {"prompt_tokens": 1000, "completion_tokens": 200, "reasoning_tokens": 0,
                           "cached_tokens": 0}}


def _eval(job, patch):
    ok = job["arm"] == "simplicio"
    return {"resolved": ok, "tail": "PASS" if ok else "FAIL"}


def _exec(tmp_path, plan, agent, *, budget=100.0, evaluator=_eval, man=None, prices=PRICES):
    man = man or _manifest(4)
    return rn.execute_plan(plan, out_dir=tmp_path / "res", manifest=man, run_id="RID", main_commit="abc1234",
                           pricing_by_model=prices, agent_fn=agent, eval_fn=evaluator, budget_usd=budget,
                           clock=itertools.count(0, 10).__next__, now_iso=lambda: "2030-01-01T00:00:00+00:00")


def test_execute_writes_one_valid_raw_json_per_run_in_the_llm_ab_schema(tmp_path):
    man = _manifest(2)
    plan = rn.build_plan(man, ["m/one", "m/two"], ["normal", "simplicio"])
    summary = _exec(tmp_path, plan, _Agent(), man=man)
    files = sorted((tmp_path / "res" / "raw").glob("*.json"))
    assert len(files) == len(plan) == 8 and summary["completed"] == 8 and summary["stopped"] is None
    doc = json.loads((tmp_path / "res" / "raw" / "o__r-1@simplicio@m_one.json").read_text())
    assert common.validate_raw(doc) == []
    meta, arm = doc["meta"], doc["arms"]["simplicio"]
    assert meta["model"] == "openrouter/m/one" and arm["model"] == "m/one"
    assert meta["harness_version"] == common.HARNESS_VERSION and meta["main_commit"] == "abc1234"
    assert meta["pricing"]["prompt"] == 1e-06 and meta["manifest_id"] == man["manifest_id"]
    assert meta["dataset"] == {"name": "toy/dataset", "revision": "a" * 40}
    task = arm["tasks"][0]
    assert task["success"] is True and task["status"] == "ok" and task["wall_s"] == 10 and arm["total_wall_s"] == 10
    assert task["totals"]["prompt_tokens"] == 1000 and task["totals"]["completion_tokens"] == 200
    off = json.loads((tmp_path / "res" / "raw" / "o__r-1@normal@m_one.json").read_text())
    assert off["arms"]["normal"]["tasks"][0]["success"] is False and off["meta"]["loop"] == "off"


def test_execute_output_feeds_the_aggregate_script_end_to_end(tmp_path):
    import swe_aggregate as ag
    man = _manifest(3)
    plan = rn.build_plan(man, ["m/one", "m/two"], ["normal", "simplicio"])
    _exec(tmp_path, plan, _Agent(), man=man)
    t = ag.build_table(ag.load_runs(tmp_path / "res"), seed=1, resamples=50, allow_small=True)
    assert len(t["rows"]) == 4 and all(r["n"] == 3 for r in t["rows"])
    on = next(r for r in t["rows"] if r["model"] == "m/one" and r["arm"] == "simplicio")
    assert on["pass_rate"]["est"] == 1.0 and on["cost_per_solved"]["est"] == pytest.approx(3 * 0.0014 / 3)


def test_run_json_records_the_run_without_secrets(tmp_path):
    man = _manifest(2)
    _exec(tmp_path, rn.build_plan(man, ["m/one", "m/two"], ["normal", "simplicio"]), _Agent(), man=man)
    run = json.loads((tmp_path / "res" / "run.json").read_text())
    assert run["run_id"] == "RID" and run["harness_version"] == common.HARNESS_VERSION
    assert run["manifest_id"] == man["manifest_id"] and run["planned"] == 8 and run["completed"] == 8
    assert run["models"] == ["m/one", "m/two"] and run["arms"] == ["normal", "simplicio"]
    assert run["status"] == "complete" and "OR_KEY" not in json.dumps(run)


def test_agent_timeout_is_a_failed_run_and_other_errors_are_infra_errors(tmp_path):
    man = _manifest(2)
    plan = rn.build_plan(man, ["m/one", "m/two"], ["normal", "simplicio"])
    _exec(tmp_path, plan, _Agent(timeout_on="o__r-1@simplicio@m/one", fail_on="o__r-2@normal@m/two"), man=man)
    t1 = json.loads((tmp_path / "res" / "raw" / "o__r-1@simplicio@m_one.json").read_text())
    task = t1["arms"]["simplicio"]["tasks"][0]
    assert (task["status"], task["success"]) == ("agent_timeout", False)
    t2 = json.loads((tmp_path / "res" / "raw" / "o__r-2@normal@m_two.json").read_text())
    task = t2["arms"]["normal"]["tasks"][0]
    assert (task["status"], task["success"]) == ("infra_error", False) and "402" in task["error"]
    assert common.validate_raw(t1) == [] and common.validate_raw(t2) == []


def test_evaluator_crash_is_an_infra_error_not_a_silent_failure(tmp_path):
    def boom(job, patch):
        raise RuntimeError("docker daemon not running")
    man = _manifest(1)
    _exec(tmp_path, rn.build_plan(man, ["m/one", "m/two"], ["normal"]), _Agent(), evaluator=boom, man=man)
    d = json.loads((tmp_path / "res" / "raw" / "o__r-1@normal@m_one.json").read_text())
    assert d["arms"]["normal"]["tasks"][0]["status"] == "infra_error"


def test_a_rerun_resumes_and_does_not_repeat_finished_runs(tmp_path):
    man = _manifest(2)
    plan = rn.build_plan(man, ["m/one", "m/two"], ["normal", "simplicio"])
    _exec(tmp_path, plan, _Agent(), man=man)
    second = _Agent()
    summary = _exec(tmp_path, plan, second, man=man)
    assert second.calls == [] and summary["skipped"] == 8 and summary["completed"] == 8


def test_the_budget_stops_the_run_and_says_so(tmp_path):
    man = _manifest(4)
    plan = rn.build_plan(man, ["m/one", "m/two"], ["normal", "simplicio"])
    agent = _Agent()
    summary = _exec(tmp_path, plan, agent, budget=0.002, man=man)   # m/one run = 0.0014, m/two run = 0.0042
    assert summary["stopped"] == "budget" and 0 < summary["completed"] < len(plan)
    assert len(agent.calls) == summary["completed"]
    run = json.loads((tmp_path / "res" / "run.json").read_text())
    assert run["status"] == "stopped: budget" and run["spent_usd_computed"] >= 0.002


def test_a_run_without_a_price_table_does_not_start(tmp_path):
    man = _manifest(1)
    agent = _Agent()
    prices = dict(PRICES, **{"m/two": {"model": "m/two", "available": False, "error": "model_not_found"}})
    with pytest.raises(RuntimeError, match="m/two"):
        _exec(tmp_path, rn.build_plan(man, ["m/one", "m/two"], ["normal"]), agent, man=man, prices=prices)
    assert agent.calls == []


def test_run_cost_uses_the_llm_ab_cost_breakdown():
    totals = {"prompt_tokens": 1000, "cached_tokens": 200, "completion_tokens": 100}
    got = rn.run_cost(totals, dict(PRICES["m/one"], input_cache_read=1e-07))
    assert got == pytest.approx(800 * 1e-06 + 200 * 1e-07 + 100 * 2e-06)
    assert rn.run_cost(totals, {"available": False}) is None


# --- live-adapter helpers (pure parts) ---------------------------------------------------------------------------

def test_prompt_carries_the_issue_text_and_the_loop_prefix_only_for_loop_on():
    inst = {"instance_id": "o__r-1", "repo": "o/r", "problem_statement": "Fix the frobnicator."}
    off, on = rn.build_prompt("normal", inst), rn.build_prompt("simplicio", inst)
    assert off == "Fix the frobnicator." and on == "/simplicio-loop Fix the frobnicator."


def test_patch_extraction_ignores_agent_and_loop_scaffolding(tmp_path):
    def git(*a):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=tmp_path, check=True,
                       capture_output=True)
    git("init", "-q")
    (tmp_path / "mod.py").write_text("a = 1\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    (tmp_path / "mod.py").write_text("a = 2\n")
    (tmp_path / "new.py").write_text("b = 1\n")
    (tmp_path / ".claude" / "skills" / "simplicio-loop").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "simplicio-loop" / "SKILL.md").write_text("skill\n")
    (tmp_path / ".simplicio-loop").mkdir()
    (tmp_path / ".simplicio-loop" / "state.json").write_text("{}\n")
    patch = rn.extract_patch(str(tmp_path))
    assert "mod.py" in patch and "new.py" in patch and "+a = 2" in patch
    assert ".claude" not in patch and ".simplicio-loop" not in patch


def test_eval_summary_parsing_follows_the_swebench_report_keys(tmp_path):
    rep = tmp_path / "openrouter__m__one.RID.json"
    rep.write_text(json.dumps({"resolved_ids": ["o__r-1"], "unresolved_ids": ["o__r-2"], "error_ids": ["o__r-3"]}))
    assert rn.parse_eval_report(rep, "o__r-1") is True
    assert rn.parse_eval_report(rep, "o__r-2") is False
    with pytest.raises(RuntimeError, match="error_ids"):
        rn.parse_eval_report(rep, "o__r-3")
    with pytest.raises(RuntimeError, match="no verdict"):
        rn.parse_eval_report(rep, "o__r-9")
    with pytest.raises(RuntimeError):
        rn.parse_eval_report(tmp_path / "missing.json", "o__r-1")


def test_prediction_line_is_the_swebench_predictions_format():
    line = json.loads(rn.prediction_line("o__r-1", "openrouter/m/one", "diff"))
    assert line == {"instance_id": "o__r-1", "model_name_or_path": "openrouter/m/one", "model_patch": "diff"}


def test_fetch_instances_checks_ids_and_base_commits_against_the_pinned_manifest(tmp_path):
    man = _manifest(2)
    rows = [{"instance_id": r["instance_id"], "repo": r["repo"], "base_commit": r["base_commit"],
             "problem_statement": "p", "patch": "x", "test_patch": "y", "FAIL_TO_PASS": "[]", "PASS_TO_PASS": "[]",
             "version": "1", "environment_setup_commit": "e", "created_at": "t", "hints_text": ""}
            for r in man["instances"]] + [{"instance_id": "extra__x-1", "base_commit": "z"}]
    seen = {}

    def loader(name, revision):
        seen.update(name=name, revision=revision)
        return rows

    out = tmp_path / "instances.json"
    n = rn.fetch_instances(man, out, loader=loader)
    assert n == 2 and seen == {"name": "toy/dataset", "revision": "a" * 40}
    assert [r["instance_id"] for r in json.loads(out.read_text())] == ["o__r-1", "o__r-2"]
    bad = [dict(r, base_commit="f" * 40) if r["instance_id"] == "o__r-2" else r for r in rows]
    with pytest.raises(RuntimeError, match="base_commit"):
        rn.fetch_instances(man, tmp_path / "x.json", loader=lambda name, revision: bad)
    with pytest.raises(RuntimeError, match="missing"):
        rn.fetch_instances(man, tmp_path / "y.json", loader=lambda name, revision: rows[:1])
    assert not (tmp_path / "x.json").exists() and not (tmp_path / "y.json").exists()


def test_cache_directory_with_dataset_content_is_git_ignored():
    ignored = subprocess.run(["git", "check-ignore", "-q", "bench/swebench/.cache/instances.json"], cwd=REPO,
                             check=False)
    assert ignored.returncode == 0
