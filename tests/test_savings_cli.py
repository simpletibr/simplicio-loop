import json

from simplicio_loop.savings_cli import main


def test_savings_report_is_honest_when_provider_usage_is_unmeasured(tmp_path, capsys):
    run = tmp_path / ".simplicio-loop" / "loop-runs" / "run-1"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text("{}", encoding="utf-8")
    (run / "operator-batch.jsonl").write_text(json.dumps({
        "execution_route": {
            "token_usage": {
                "input_tokens": None,
                "output_tokens": None,
                "reason": "route_decision_precedes_provider_invocation",
            },
            "cache_hit": False,
        }
    }) + "\n", encoding="utf-8")

    assert main(["savings", "report", "--repo", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unmeasured"
    assert payload["provider_backed"] is False
    assert payload["input_tokens"] is None
    assert payload["cost"] is None
