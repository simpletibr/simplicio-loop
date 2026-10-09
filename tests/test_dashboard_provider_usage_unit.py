'''Provider usage reaches the token_usage stream, and a reported provider cost beats the price-table estimate.

The OpenRouter worker measures input/output/cached/cache-write/reasoning tokens and the reported USD cost in its
``provider-worker-*.json`` receipt. The execution-route record is written before the call, so it stays null. These tests
pin that measured counts become ``token_usage`` events and that ``cost_estimate`` uses the reported cost when every
priced event carries one. Without a reported cost the estimate path is unchanged.
'''
import json

from simplicio_loop import dashboard_events
from simplicio_loop.dashboard import budget

PRICES = {'as_of': '2026-10-08', 'source_url': 'https://example.invalid/prices',
          'models': {'claude-sonnet-5-5': {'input_per_mtok': 2, 'output_per_mtok': 10}}}


def _receipt(tmp_path, name, **fields):
    record = {'schema': 'simplicio.provider-worker-receipt/v1', 'status': 'READY', 'provider': 'openrouter',
              'model': 'claude-sonnet-5-5', 'task_index': 1, 'attempt': 1, 'usage_status': 'measured',
              'input_tokens': 1000, 'output_tokens': 200, 'cached_tokens': None, 'cache_write_tokens': None,
              'reasoning_tokens': None, 'cost': None, 'cost_status': 'unknown'}
    record.update(fields)
    (tmp_path / name).write_text(json.dumps(record), encoding='utf-8')
    return name


def test_receipt_with_measured_counts_becomes_a_token_usage_event(tmp_path):
    name = _receipt(tmp_path, 'provider-worker-1-attempt-1.json', cached_tokens=400, reasoning_tokens=50,
                    cost=0.0042, cost_status='measured')
    specs = dashboard_events.load().token_usage_specs(tmp_path, only=name)
    assert len(specs) == 1
    payload = specs[0]['payload']
    assert payload['input_tokens'] == 1000 and payload['output_tokens'] == 200
    assert payload['model'] == 'claude-sonnet-5-5'
    assert payload['cached_tokens'] == 400 and payload['reasoning_tokens'] == 50
    assert payload['cost'] == 0.0042
    assert 'cache_write_tokens' not in payload  # absent counts are not written as null


def test_receipt_without_measured_usage_yields_nothing(tmp_path):
    name = _receipt(tmp_path, 'provider-worker-1-attempt-1.json', input_tokens=None, output_tokens=None,
                    usage_status='unknown')
    assert dashboard_events.load().token_usage_specs(tmp_path, only=name) == []


def test_reported_cost_is_used_instead_of_the_price_table():
    events = [{'schema': 'simplicio.dashboard-event/v1', 'kind': 'token_usage',
               'payload': {'input_tokens': 1000, 'output_tokens': 200, 'model': 'claude-sonnet-5-5', 'cost': 0.0042}}]
    row = budget.cost_estimate(events, PRICES)
    assert row['usd'] == 0.0042
    assert row['proof_kind'] == 'medido' and row['state'] == 'ESTIMADO' and row['reason'] is None


def test_without_reported_cost_the_estimate_path_is_unchanged():
    events = [{'schema': 'simplicio.dashboard-event/v1', 'kind': 'token_usage',
               'payload': {'input_tokens': 1000, 'output_tokens': 200, 'model': 'claude-sonnet-5-5'}}]
    row = budget.cost_estimate(events, PRICES)
    assert row['usd'] == round((1000 * 2 + 200 * 10) / 1_000_000, 6)
    assert row['proof_kind'] == 'estimado'


def test_mixed_reported_and_missing_cost_falls_back_to_the_estimate():
    events = [
        {'schema': 'simplicio.dashboard-event/v1', 'kind': 'token_usage',
         'payload': {'input_tokens': 1000, 'output_tokens': 200, 'model': 'claude-sonnet-5-5', 'cost': 0.5}},
        {'schema': 'simplicio.dashboard-event/v1', 'kind': 'token_usage',
         'payload': {'input_tokens': 1000, 'output_tokens': 200, 'model': 'claude-sonnet-5-5'}},
    ]
    row = budget.cost_estimate(events, PRICES)
    assert row['proof_kind'] == 'estimado'
    assert row['usd'] == round((2000 * 2 + 400 * 10) / 1_000_000, 6)


def test_cache_and_reasoning_tokens_are_reported_as_unpriced():
    events = [{'schema': 'simplicio.dashboard-event/v1', 'kind': 'token_usage',
               'payload': {'input_tokens': 1000, 'output_tokens': 200, 'model': 'claude-sonnet-5-5',
                           'cached_tokens': 400, 'cache_write_tokens': 100, 'reasoning_tokens': 50}}]
    row = budget.cost_estimate(events, PRICES)
    assert row['unpriced_tokens'] == {'cached_tokens': 400, 'cache_write_tokens': 100, 'reasoning_tokens': 50}
    assert row['usd'] == round((1000 * 2 + 200 * 10) / 1_000_000, 6)


def test_provider_call_writes_a_token_usage_event_for_the_run(monkeypatch, tmp_path):
    '''The real runner path: a measured provider result becomes a token_usage event from its receipt, not from the route.'''
    from simplicio_loop import provider_worker, runner

    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-only-key')
    result = {'schema': 'simplicio.openrouter-worker/v1', 'status': 'succeeded', 'provider': 'openrouter',
              'upstream_provider': 'anthropic', 'model': 'claude-sonnet-5-5', 'run_id': 'run-1', 'task_index': 1,
              'prompt_sha256': 'p' * 64, 'response_sha256': 'r' * 64, 'allowed_paths': ['site/checkers.html'],
              'proposal': {'files': {'site/checkers.html': '<html></html>'}}, 'provider_call_count': 1,
              'usage': {'prompt_tokens': 1000, 'completion_tokens': 200}, 'usage_status': 'measured',
              'input_tokens': 1000, 'output_tokens': 200, 'cached_tokens': 400, 'cache_write_tokens': None,
              'reasoning_tokens': None, 'cost': 0.0042, 'cost_status': 'measured'}
    monkeypatch.setattr(provider_worker.OpenRouterWorker, 'dispatch', lambda self, **kwargs: result)
    run_dir = tmp_path / 'run'
    run_dir.mkdir()

    runner._provider_worker_plan(task={'id': 'TASK-1', 'goal': 'create'}, context={}, run_id='run-1', task_index=1,
                                 attempt=1, root=tmp_path, allowed_paths=('site/checkers.html',), run_dir=run_dir,
                                 provider_worker='openrouter')

    specs = dashboard_events.load().token_usage_specs(run_dir)
    assert len(specs) == 1
    assert specs[0]['payload']['input_tokens'] == 1000 and specs[0]['payload']['cost'] == 0.0042
    assert specs[0]['payload']['cached_tokens'] == 400
    assert specs[0]['payload']['model'] == provider_worker.OPENROUTER_MODEL  # the receipt names the model it called


def test_runner_emits_the_receipt_it_just_wrote_and_only_that_one(monkeypatch, tmp_path):
    '''Wiring contract: the runner emits token_usage for the receipt of this attempt, once, and for nothing else.'''
    from simplicio_loop import provider_worker, runner
    from simplicio_loop import dashboard_events as wrapper

    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-only-key')
    calls = []
    monkeypatch.setattr(wrapper, 'emit_token_usage', lambda run_dir, only=None: calls.append((str(run_dir), only)) or [])
    result = {'schema': 'simplicio.openrouter-worker/v1', 'status': 'succeeded', 'provider': 'openrouter',
              'upstream_provider': 'anthropic', 'model': 'claude-sonnet-5-5', 'run_id': 'run-1', 'task_index': 1,
              'prompt_sha256': 'p' * 64, 'response_sha256': 'r' * 64, 'allowed_paths': ['site/checkers.html'],
              'proposal': {'files': {'site/checkers.html': '<html></html>'}}, 'provider_call_count': 1,
              'usage': {}, 'usage_status': 'measured', 'input_tokens': 1000, 'output_tokens': 200,
              'cached_tokens': None, 'cache_write_tokens': None, 'reasoning_tokens': None,
              'cost': None, 'cost_status': 'unknown'}
    monkeypatch.setattr(provider_worker.OpenRouterWorker, 'dispatch', lambda self, **kwargs: result)
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    runner._provider_worker_plan(task={'id': 'TASK-1', 'goal': 'create'}, context={}, run_id='run-1', task_index=1,
                                 attempt=1, root=tmp_path, allowed_paths=('site/checkers.html',), run_dir=run_dir,
                                 provider_worker='openrouter')

    assert calls == [(str(run_dir), 'provider-worker-1-attempt-1.json')]
