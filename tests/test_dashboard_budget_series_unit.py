"""Tests for token_series and by_source in usage (issue #1404, task E1)."""
import pytest
from simplicio_loop.dashboard.budget import token_series, usage, SCHEMA


class TestTokenSeries:
    """token_series(events) returns accumulated token counts, max 60 points."""

    def test_empty_events(self):
        """Empty events list returns empty series."""
        result = token_series([])
        assert result == []

    def test_single_event(self):
        """Single token_usage event returns one point."""
        events = [
            {'schema': SCHEMA, 'kind': 'token_usage', 'ts': '2025-01-01T00:00:00Z',
             'payload': {'input_tokens': 10, 'output_tokens': 20}}
        ]
        result = token_series(events)
        assert len(result) == 1
        assert result[0] == {'ts': '2025-01-01T00:00:00Z', 'tokens': 30}

    def test_accumulated_tokens(self):
        """Multiple events accumulate correctly."""
        events = [
            {'schema': SCHEMA, 'kind': 'token_usage', 'ts': '2025-01-01T00:00:00Z',
             'payload': {'input_tokens': 10, 'output_tokens': 20}},
            {'schema': SCHEMA, 'kind': 'token_usage', 'ts': '2025-01-01T00:01:00Z',
             'payload': {'input_tokens': 5, 'output_tokens': 15}},
            {'schema': SCHEMA, 'kind': 'token_usage', 'ts': '2025-01-01T00:02:00Z',
             'payload': {'input_tokens': 20, 'output_tokens': 10}}
        ]
        result = token_series(events)
        assert len(result) == 3
        assert result[0]['tokens'] == 30
        assert result[1]['tokens'] == 50
        assert result[2]['tokens'] == 80

    def test_ts_none_when_absent(self):
        """Event without 'ts' field produces ts=None in series point."""
        events = [
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 10, 'output_tokens': 20}}
        ]
        result = token_series(events)
        assert len(result) == 1
        assert result[0]['ts'] is None
        assert result[0]['tokens'] == 30

    def test_last_point_matches_usage_total(self):
        """Last point always equals usage(events)['tokens']."""
        events = [
            {'schema': SCHEMA, 'kind': 'token_usage', 'ts': '2025-01-01T00:00:00Z',
             'payload': {'input_tokens': 100, 'output_tokens': 200}},
            {'schema': SCHEMA, 'kind': 'token_usage', 'ts': '2025-01-01T00:01:00Z',
             'payload': {'input_tokens': 50, 'output_tokens': 75}}
        ]
        result = token_series(events)
        total = usage(events)['tokens']
        assert result[-1]['tokens'] == total
        assert result[-1]['tokens'] == 425

    def test_more_than_60_events_capped(self):
        """More than 60 events are subsampled to exactly 60 points."""
        events = []
        for i in range(100):
            events.append({
                'schema': SCHEMA, 'kind': 'token_usage',
                'ts': f'2025-01-01T00:{i//60:02d}:{i%60:02d}Z',
                'payload': {'input_tokens': 10, 'output_tokens': 10}
            })
        result = token_series(events)
        assert len(result) == 60
        # First and last should be present
        assert result[0]['tokens'] == 20  # first event
        assert result[-1]['tokens'] == 2000  # last == all 100 * 20

    def test_exactly_60_events(self):
        """Exactly 60 events returns all 60 points."""
        events = []
        for i in range(60):
            events.append({
                'schema': SCHEMA, 'kind': 'token_usage',
                'ts': f'2025-01-01T00:00:{i:02d}Z',
                'payload': {'input_tokens': 5, 'output_tokens': 5}
            })
        result = token_series(events)
        assert len(result) == 60
        assert result[-1]['tokens'] == 600

    def test_exactly_61_events(self):
        """Exactly 61 events are subsampled to 60 points."""
        events = []
        for i in range(61):
            events.append({
                'schema': SCHEMA, 'kind': 'token_usage',
                'ts': f'2025-01-01T00:00:{i:02d}Z',
                'payload': {'input_tokens': 1, 'output_tokens': 1}
            })
        result = token_series(events)
        assert len(result) == 60
        assert result[0]['tokens'] > 0  # First point should have positive tokens
        assert result[-1]['tokens'] == 122  # 61 * 2

    def test_non_monotonic_check_avoided(self):
        """Accumulated tokens never decrease."""
        events = []
        for i in range(100):
            events.append({
                'schema': SCHEMA, 'kind': 'token_usage',
                'payload': {'input_tokens': 1, 'output_tokens': 1}
            })
        result = token_series(events)
        for i in range(1, len(result)):
            assert result[i]['tokens'] >= result[i-1]['tokens']

    def test_countless_event_ignored(self):
        """Events without input/output tokens are ignored."""
        events = [
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 10, 'output_tokens': 20}},
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {}},  # No tokens
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 30, 'output_tokens': 40}}
        ]
        result = token_series(events)
        assert len(result) == 2
        assert result[0]['tokens'] == 30
        assert result[1]['tokens'] == 100

    def test_wrong_schema_ignored(self):
        """Events with different schema are ignored."""
        events = [
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 10, 'output_tokens': 20}},
            {'schema': 'other.schema/v1', 'kind': 'token_usage',
             'payload': {'input_tokens': 5, 'output_tokens': 5}},
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 30, 'output_tokens': 40}}
        ]
        result = token_series(events)
        assert len(result) == 2
        assert result[0]['tokens'] == 30
        assert result[1]['tokens'] == 100

    def test_wrong_kind_ignored(self):
        """Events with kind != 'token_usage' are ignored."""
        events = [
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 10, 'output_tokens': 20}},
            {'schema': SCHEMA, 'kind': 'cost_sample',
             'payload': {'usd': 1.0}},
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 30, 'output_tokens': 40}}
        ]
        result = token_series(events)
        assert len(result) == 2
        assert result[0]['tokens'] == 30
        assert result[1]['tokens'] == 100


class TestUsageBySource:
    """usage(events) includes by_source key splitting 'provider' vs 'other'."""

    def test_empty_events_by_source(self):
        """Empty events: by_source is {'provider': 0, 'other': 0}."""
        result = usage([])
        assert result['by_source'] == {'provider': 0, 'other': 0}

    def test_provider_source_counted(self):
        """Events with source='provider' counted in by_source['provider']."""
        events = [
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 10, 'output_tokens': 20, 'source': 'provider'}}
        ]
        result = usage(events)
        assert result['tokens'] == 30
        assert result['by_source']['provider'] == 30
        assert result['by_source']['other'] == 0

    def test_other_source_counted(self):
        """Events with source != 'provider' counted in by_source['other']."""
        events = [
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 10, 'output_tokens': 20, 'source': 'cache'}}
        ]
        result = usage(events)
        assert result['tokens'] == 30
        assert result['by_source']['provider'] == 0
        assert result['by_source']['other'] == 30

    def test_missing_source_is_other(self):
        """Events without source field counted in by_source['other']."""
        events = [
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 10, 'output_tokens': 20}}
        ]
        result = usage(events)
        assert result['tokens'] == 30
        assert result['by_source']['provider'] == 0
        assert result['by_source']['other'] == 30

    def test_by_source_mixed(self):
        """Mixed sources: sum provider + other == tokens."""
        events = [
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 10, 'output_tokens': 20, 'source': 'provider'}},
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 5, 'output_tokens': 15, 'source': 'cache'}},
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 20, 'output_tokens': 10}}
        ]
        result = usage(events)
        assert result['tokens'] == 80
        assert result['by_source']['provider'] == 30
        assert result['by_source']['other'] == 50
        assert result['by_source']['provider'] + result['by_source']['other'] == result['tokens']

    def test_by_source_sum_always_equals_tokens(self):
        """by_source provider + other always equals tokens."""
        events = [
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 100, 'output_tokens': 50, 'source': 'provider'}},
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 25, 'output_tokens': 75}},
            {'schema': SCHEMA, 'kind': 'token_usage',
             'payload': {'input_tokens': 10, 'output_tokens': 40, 'source': 'other_source'}}
        ]
        result = usage(events)
        total = result['by_source']['provider'] + result['by_source']['other']
        assert total == result['tokens']

    def test_by_source_with_other_keys_unchanged(self):
        """by_source addition doesn't break other keys in usage."""
        events = [
            {'schema': SCHEMA, 'kind': 'token_usage', 'task_id': 'task1', 'iteration': 0,
             'payload': {'input_tokens': 10, 'output_tokens': 20, 'source': 'provider'}}
        ]
        result = usage(events)
        # Check that existing keys are still present and correct
        assert 'tokens' in result
        assert 'by_phase' in result
        assert 'by_lane' in result
        assert 'by_model' in result
        assert 'by_task' in result
        assert 'by_iteration' in result
        assert 'unattributed_tokens' in result
        assert 'samples' in result
