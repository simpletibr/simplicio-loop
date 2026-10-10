'''Measured cache counters of the execution report (#1608). The caller passes the cache reads and cache writes it measured
for a task, next to the new input count they belong to. Without a measurement the field stays None, never 0, and the
cache counts never enter the total of input plus output.
'''
import pytest

from simplicio_loop import execution_report as er


def test_record_task_stores_the_measured_cache_counters(tmp_path):
    report = er.new_report(tmp_path)
    er.record_task(report, task_id="T1", title="t", tokens_in=1000, tokens_out=200, cache_read=40000, cache_write=30000)
    tok = report["tasks"][0]["tokens"]
    assert tok["tokens_cached"] == 40000
    assert tok["tokens_cache_write"] == 30000
    assert tok["tokens_in"] == 1000 and tok["tokens_out"] == 200
    assert tok["tokens_total"] == 1200


def test_cache_counters_stay_none_when_the_caller_did_not_measure_them(tmp_path):
    report = er.new_report(tmp_path)
    er.record_task(report, task_id="T1", title="t", tokens_in=1000, tokens_out=200)
    tok = report["tasks"][0]["tokens"]
    assert tok["tokens_cached"] is None and tok["tokens_cache_write"] is None


@pytest.mark.parametrize("kwargs", [{"cache_read": 5}, {"cache_write": 5}])
def test_cache_counters_need_the_new_input_count_they_belong_to(tmp_path, kwargs):
    with pytest.raises(ValueError):
        er.record_task(er.new_report(tmp_path), task_id="T1", title="t", **kwargs)


@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_cache_counters_must_be_non_negative_integers(tmp_path, value):
    with pytest.raises(ValueError):
        er.record_task(er.new_report(tmp_path), task_id="T1", title="t", tokens_in=1, cache_read=value)
    with pytest.raises(ValueError):
        er.record_task(er.new_report(tmp_path), task_id="T1", title="t", tokens_in=1, cache_write=value)


def test_consolidate_sums_only_the_cache_counters_that_were_measured(tmp_path):
    report = er.new_report(tmp_path)
    er.record_task(report, task_id="T1", title="a", tokens_in=10, cache_read=100, cache_write=5)
    er.record_task(report, task_id="T2", title="b", tokens_in=20, cache_read=200, cache_write=7)
    er.record_task(report, task_id="T3", title="c")
    summary = er.consolidate(report)
    assert summary["tokens_cached_sum"] == 300
    assert summary["tokens_cache_write_sum"] == 12


def test_consolidate_has_no_cache_sum_when_nothing_was_measured(tmp_path):
    report = er.new_report(tmp_path)
    er.record_task(report, task_id="T1", title="a", tokens_in=10)
    summary = er.consolidate(report)
    assert summary["tokens_cached_sum"] is None and summary["tokens_cache_write_sum"] is None


def test_record_task_cli_takes_the_cache_counters(tmp_path):
    argv = ["record-task", "--repo", str(tmp_path), "--task-id", "T1", "--title", "t", "--tokens-in", "10",
            "--cache-read", "40", "--cache-write", "3"]
    assert er.main(argv) == 0
    tok = er.load_latest(tmp_path)["tasks"][0]["tokens"]
    assert tok["tokens_cached"] == 40 and tok["tokens_cache_write"] == 3
