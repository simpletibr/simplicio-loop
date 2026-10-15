"""bench/swebench aggregate (#1819): the published table is recomputed ONLY from raw run files.

All data here is SYNTHETIC: tests/fixtures/bench_swebench/SYNTHETIC_run (hand-checkable numbers)
or runs generated in tmp_path. Nothing is read from bench/swebench/results/.
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bench" / "swebench"))
sys.path.insert(0, str(REPO / "bench" / "llm_ab"))

import swe_aggregate as ag

FIXTURE = REPO / "tests" / "fixtures" / "bench_swebench" / "SYNTHETIC_run"
HARNESS = "simplicio-swebench-harness/1"
PRICE = {"model": "synthetic/m", "fetched_at": "2000-01-01T00:00:00+00:00", "available": True,
         "prompt": 1e-06, "completion": 2e-06, "input_cache_read": None, "input_cache_write": None,
         "internal_reasoning": None}


def _raw(model, arm, i, success, wall, *, p=1000, k=0, c=100, status="ok", price=PRICE, harness=HARNESS,
         revision="0" * 40, manifest_id="synthetic00000000", synthetic=True, cost_usd=0.0):
    iid = f"SYNTHETIC__demo-{i:03d}"
    return {
        "schema": "simplicio-swebench-raw/1",
        "meta": {"synthetic": synthetic, "harness_version": harness, "run_id": "SYNTHETIC", "date": "2000-01-01",
                 "main_commit": "0000000", "model": "openrouter/" + model, "pricing": dict(price, model=model),
                 "task_set": "swebench-verified", "agent": "opencode",
                 "dataset": {"name": "SYNTHETIC/not-a-dataset", "revision": revision},
                 "manifest_id": manifest_id, "instance_id": iid, "arm": arm,
                 "loop": "on" if arm == "simplicio" else "off"},
        "arms": {arm: {"arm": arm, "model": model, "total_wall_s": float(wall), "tasks": [{
            "index": 1, "kind": "swebench-verified", "instance_id": iid, "repo": "SYNTHETIC/demo", "status": status,
            "success": bool(success), "turns": 2, "wall_s": float(wall),
            "totals": {"prompt_tokens": p, "completion_tokens": c, "reasoning_tokens": 0, "cached_tokens": k,
                       "cost_usd": cost_usd, "cost_source": "computed-from-tokens"}}]}},
    }


def _write(run_dir: Path, docs) -> Path:
    raw = run_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for d in docs:
        m, t = d["meta"], next(iter(d["arms"].values()))["tasks"][0]
        name = f"{t['instance_id']}@{m['arm']}@{m['model'].replace('/', '_')}.json"
        (raw / name).write_text(json.dumps(d), encoding="utf-8")
    return run_dir


def _grid(n=30, models=("synthetic/m1", "synthetic/m2"), **kw):
    docs = []
    for m in models:
        for arm in ("normal", "simplicio"):
            for i in range(1, n + 1):
                solved = (i % 3 != 0) if arm == "simplicio" else (i % 2 == 0)
                wall = 100 + 7 * i + (13 if arm == "simplicio" else 0)
                docs.append(_raw(m, arm, i, solved, wall, p=1000 + 10 * i, **kw))
    return docs


def _row(table, model, arm):
    return next(r for r in table["rows"] if r["model"] == model and r["arm"] == arm)


# --- point estimates (hand-computed from the fixture) ----------------------------------------------

def test_point_estimates_are_recomputed_from_raw_files():
    runs = ag.load_runs(FIXTURE)
    t = ag.build_table(runs, seed=1819, resamples=300, allow_small=True)
    a_off = _row(t, "synthetic/model-a", "normal")
    assert (a_off["n"], a_off["solved"], a_off["excluded"]) == (6, 3, 1)
    assert a_off["pass_rate"]["est"] == pytest.approx(0.5)
    assert a_off["cost_per_solved"]["est"] == pytest.approx(0.072 / 3)      # 6 x $0.012 over 3 solved
    assert a_off["wall_s"]["est"] == pytest.approx(350.0)
    a_on = _row(t, "synthetic/model-a", "simplicio")
    assert (a_on["n"], a_on["solved"], a_on["excluded"]) == (6, 4, 0)
    assert a_on["pass_rate"]["est"] == pytest.approx(4 / 6)
    assert a_on["cost_per_solved"]["est"] == pytest.approx(6 * 0.0052 / 4)  # cached tokens at the cache price
    assert a_on["wall_s"]["est"] == pytest.approx(75.0)
    b_off = _row(t, "synthetic/model-b", "normal")
    assert b_off["pass_rate"]["est"] == pytest.approx(1 / 6)
    assert b_off["cost_per_solved"]["est"] == pytest.approx(0.12)
    assert b_off["wall_s"]["est"] == pytest.approx(35.0)


def test_cached_tokens_are_priced_at_the_prompt_rate_when_the_model_has_no_cache_price():
    t = ag.build_table(ag.load_runs(FIXTURE), seed=1, resamples=50, allow_small=True)
    b_on = _row(t, "synthetic/model-b", "simplicio")
    # 4000 x 2e-6 + 1000 x 2e-6 + 400 x 4e-6 = 0.0116 per task, 6 tasks, nothing solved
    assert b_on["total_cost_usd"] == pytest.approx(6 * 0.0116)


def test_zero_solved_gives_no_cost_per_solved_never_zero():
    t = ag.build_table(ag.load_runs(FIXTURE), seed=1, resamples=50, allow_small=True)
    b_on = _row(t, "synthetic/model-b", "simplicio")
    assert b_on["solved"] == 0
    assert b_on["cost_per_solved"]["est"] is None
    assert "n/a" in ag.render_markdown(t)


def test_stored_cost_fields_in_the_raw_files_are_never_trusted(tmp_path):
    run = tmp_path / "run"
    shutil.copytree(FIXTURE, run)
    for f in (run / "raw").glob("*.json"):
        d = json.loads(f.read_text())
        for arm in d["arms"].values():
            for task in arm["tasks"]:
                task["totals"]["cost_usd"] = 12345.0
        f.write_text(json.dumps(d))
    t = ag.build_table(ag.load_runs(run), seed=1819, resamples=100, allow_small=True)
    assert _row(t, "synthetic/model-a", "normal")["cost_per_solved"]["est"] == pytest.approx(0.024)


def test_infra_errors_are_excluded_but_timeouts_count_as_failures():
    t = ag.build_table(ag.load_runs(FIXTURE), seed=1, resamples=50, allow_small=True)
    off = _row(t, "synthetic/model-a", "normal")
    assert off["excluded"] == 1 and off["n"] == 6   # demo-007 hit an infra error
    on = _row(t, "synthetic/model-a", "simplicio")
    assert on["n"] == 6 and on["solved"] == 4        # demo-006 timed out and counts as a miss


def test_paired_deltas_use_only_tasks_valid_in_both_arms():
    t = ag.build_table(ag.load_runs(FIXTURE), seed=1819, resamples=300, allow_small=True)
    pa = next(p for p in t["paired"] if p["model"] == "synthetic/model-a")
    assert pa["n_pairs"] == 6 and pa["small_n"] is True
    assert pa["delta_pass_rate"]["est"] == pytest.approx(4 / 6 - 3 / 6)
    assert pa["delta_wall_s"]["est"] == pytest.approx(75.0 - 350.0)
    assert pa["delta_cost_per_solved"]["est"] == pytest.approx(0.0078 - 0.024)
    pb = next(p for p in t["paired"] if p["model"] == "synthetic/model-b")
    assert pb["delta_cost_per_solved"]["est"] is None  # loop-on solved nothing -> undefined, not 0


# --- confidence intervals ----------------------------------------------------------------------------

def test_every_metric_has_a_95_percent_ci_that_brackets_its_estimate(tmp_path):
    run = _write(tmp_path / "run", _grid())
    t = ag.build_table(ag.load_runs(run), seed=1819, resamples=1000)
    assert t["meta"]["confidence"] == 0.95 and t["meta"]["seed"] == 1819
    for row in t["rows"]:
        assert row["n"] == 30 and row["small_n"] is False
        for key in ("pass_rate", "cost_per_solved", "wall_s"):
            m = row[key]
            assert m["lo"] <= m["est"] <= m["hi"], (row["model"], row["arm"], key, m)
        assert 0.0 <= row["pass_rate"]["lo"] and row["pass_rate"]["hi"] <= 1.0


def test_table_is_reproducible_for_a_seed_and_changes_with_it(tmp_path):
    run = _write(tmp_path / "run", _grid())
    runs = ag.load_runs(run)
    a = ag.build_table(runs, seed=5, resamples=400)
    b = ag.build_table(ag.load_runs(run), seed=5, resamples=400)
    c = ag.build_table(runs, seed=6, resamples=400)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["rows"][0]["wall_s"]["est"] == c["rows"][0]["wall_s"]["est"]
    assert [r["wall_s"] for r in a["rows"]] != [r["wall_s"] for r in c["rows"]]


# --- the n < 30 refusal ---------------------------------------------------------------------------------

def test_refuses_any_row_with_fewer_than_30_tasks_by_default():
    with pytest.raises(ag.SmallSampleError) as exc:
        ag.build_table(ag.load_runs(FIXTURE), seed=1, resamples=50)
    msg = str(exc.value)
    assert "30" in msg and "--allow-small" in msg and "synthetic/model-a" in msg


def test_boundary_29_tasks_is_refused_and_30_is_accepted(tmp_path):
    with pytest.raises(ag.SmallSampleError):
        ag.build_table(ag.load_runs(_write(tmp_path / "r29", _grid(n=29))), seed=1, resamples=50)
    ok = ag.build_table(ag.load_runs(_write(tmp_path / "r30", _grid(n=30))), seed=1, resamples=50)
    assert all(r["n"] == 30 for r in ok["rows"])


def test_infra_exclusions_cannot_hide_a_small_sample(tmp_path):
    docs = _grid(n=30)
    for d in docs:  # two infra errors in one cell leave only 28 valid tasks
        m, arm = d["meta"]["model"], d["meta"]["arm"]
        t = d["arms"][arm]["tasks"][0]
        if m.endswith("m1") and arm == "normal" and t["instance_id"][-3:] in ("001", "002"):
            t["status"] = "infra_error"
            t["success"] = False
    with pytest.raises(ag.SmallSampleError, match="synthetic/m1"):
        ag.build_table(ag.load_runs(_write(tmp_path / "run", docs)), seed=1, resamples=50)


def test_allow_small_labels_every_small_row_small_n_and_only_those(tmp_path):
    small = ag.build_table(ag.load_runs(FIXTURE), seed=1, resamples=50, allow_small=True)
    assert all(r["small_n"] for r in small["rows"])
    md = ag.render_markdown(small)
    assert md.count("SMALL-N") >= len(small["rows"])
    big = ag.build_table(ag.load_runs(_write(tmp_path / "run", _grid())), seed=1, resamples=50)
    assert "SMALL-N" not in ag.render_markdown(big)


# --- refusing to mix runs -----------------------------------------------------------------------------------

@pytest.mark.parametrize("field,doc_kw", [
    ("harness", {"harness": "simplicio-swebench-harness/2"}),
    ("revision", {"revision": "1" * 40}),
    ("manifest", {"manifest_id": "other0000000000"}),
])
def test_runs_from_different_harness_dataset_revision_or_manifest_are_not_mixed(tmp_path, field, doc_kw):
    docs = _grid(n=3, models=("synthetic/m1",))
    docs.append(_raw("synthetic/m1", "normal", 99, True, 10, **doc_kw))
    with pytest.raises(ag.RawError, match="mix"):
        ag.load_runs(_write(tmp_path / "run", docs))


def test_price_tables_must_match_per_model(tmp_path):
    docs = _grid(n=3, models=("synthetic/m1",))
    docs.append(_raw("synthetic/m1", "normal", 99, True, 10, price=dict(PRICE, prompt=9e-06)))
    with pytest.raises(ag.RawError, match="price"):
        ag.load_runs(_write(tmp_path / "run", docs))


def test_a_price_snapshot_time_difference_alone_is_not_a_mismatch(tmp_path):
    docs = _grid(n=3, models=("synthetic/m1",))
    docs.append(_raw("synthetic/m1", "normal", 99, True, 10, price=dict(PRICE, fetched_at="2001-02-03T00:00:00+00:00")))
    assert len(ag.load_runs(_write(tmp_path / "run", docs))) == 3 * 2 + 1


def test_duplicate_runs_for_one_cell_are_an_error(tmp_path):
    docs = _grid(n=3, models=("synthetic/m1",))
    dup = copy.deepcopy(docs[0])
    run = _write(tmp_path / "run", docs)
    (run / "raw" / "copy.json").write_text(json.dumps(dup))
    with pytest.raises(ag.RawError, match="duplicate"):
        ag.load_runs(run)


def test_malformed_raw_files_are_rejected_loudly(tmp_path):
    docs = _grid(n=3, models=("synthetic/m1",))
    run = _write(tmp_path / "run", docs)
    bad = copy.deepcopy(docs[0])
    del bad["arms"]["normal"]["tasks"][0]["totals"]
    bad["meta"]["instance_id"] = "SYNTHETIC__demo-500"
    (run / "raw" / "bad.json").write_text(json.dumps(bad))
    with pytest.raises(ag.RawError, match="bad.json"):
        ag.load_runs(run)
    (run / "raw" / "bad.json").write_text("{not json")
    with pytest.raises(ag.RawError, match="bad.json"):
        ag.load_runs(run)


def test_missing_raw_dir_or_empty_dir_is_an_error(tmp_path):
    with pytest.raises(ag.RawError):
        ag.load_runs(tmp_path)
    (tmp_path / "raw").mkdir()
    with pytest.raises(ag.RawError):
        ag.load_runs(tmp_path)


# --- provenance, synthetic gate, CLI ---------------------------------------------------------------------------

def test_markdown_links_the_run_directory_and_a_digest_of_the_raw_files(tmp_path):
    run = tmp_path / "run"
    shutil.copytree(FIXTURE, run)
    t1 = ag.build_table(ag.load_runs(run), seed=1, resamples=50, allow_small=True, source=str(run))
    md = ag.render_markdown(t1)
    assert str(run) in md and t1["meta"]["raw_digest"] in md and "25 raw files" in md
    victim = next((run / "raw").glob("*demo-001@normal@synthetic_model-a.json"))
    d = json.loads(victim.read_text())
    d["arms"]["normal"]["tasks"][0]["wall_s"] = 999.0
    victim.write_text(json.dumps(d))
    t2 = ag.build_table(ag.load_runs(run), seed=1, resamples=50, allow_small=True, source=str(run))
    assert t2["meta"]["raw_digest"] != t1["meta"]["raw_digest"]


def test_synthetic_data_carries_a_banner_in_the_table():
    t = ag.build_table(ag.load_runs(FIXTURE), seed=1, resamples=50, allow_small=True)
    assert t["meta"]["synthetic"] is True
    assert "SYNTHETIC" in ag.render_markdown(t)


def test_cli_refuses_small_n_by_default_and_prints_with_allow_small(capsys):
    assert ag.main([str(FIXTURE), "--allow-synthetic", "--resamples", "50"]) == 2
    err = capsys.readouterr().err
    assert "fewer than 30" in err and "--allow-small" in err
    assert ag.main([str(FIXTURE), "--allow-synthetic", "--allow-small", "--resamples", "50"]) == 0
    out = capsys.readouterr().out
    assert "SMALL-N" in out and "SYNTHETIC" in out


def test_cli_refuses_synthetic_runs_unless_told_otherwise(capsys):
    assert ag.main([str(FIXTURE), "--allow-small", "--resamples", "50"]) == 2
    assert "SYNTHETIC" in capsys.readouterr().err


def test_cli_json_output_and_out_file(tmp_path, capsys):
    out = tmp_path / "table.json"
    rc = ag.main([str(FIXTURE), "--allow-synthetic", "--allow-small", "--resamples", "50",
                  "--format", "json", "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert len(data["rows"]) == 4 and data["meta"]["resamples"] == 50
    assert capsys.readouterr().out == ""  # --out writes the file instead of printing


def test_a_real_run_directory_without_raw_files_is_an_error_not_an_empty_table(tmp_path, capsys):
    assert ag.main([str(tmp_path)]) == 1
    assert "raw" in capsys.readouterr().err


# --- schema compatibility with bench/llm_ab ----------------------------------------------------------------------

def test_raw_files_keep_the_llm_ab_arm_shape_so_its_helpers_can_read_them():
    import aggregate as llm_ab_aggregate  # bench/llm_ab/aggregate.py (not ours)
    raw = next((FIXTURE / "raw").glob("*demo-001@simplicio@synthetic_model-a.json"))
    doc = json.loads(raw.read_text())
    arm = doc["arms"]["simplicio"]
    assert llm_ab_aggregate.success_summary(arm) == (1, 1)
    assert llm_ab_aggregate.task_wall(arm) == pytest.approx(50.0)
    assert llm_ab_aggregate.token_totals(arm)["prompt_uncached"] == 4000
