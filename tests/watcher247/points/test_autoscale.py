"""Tests for autoscale extension point (intake stage).

Evidence only: the recommendation is recorded and never wired to config.concurrency.
"""
from simplicio_loop import economy_profile


class TestAutoscale:
    def test_records_the_recommendation(self, point_contract, make_ctx, tmp_path, monkeypatch):
        monkeypatch.setattr(economy_profile, "recommend_operator_workers", lambda cpu=None: 4)
        result = point_contract("autoscale", make_ctx(state_dir=tmp_path), expect="ok")
        assert result.reason_code is None
        assert result.evidence == {"recommended_operator_workers": 4}

    def test_a_failing_recommendation_is_an_error_not_an_ok(self, point_contract, make_ctx, tmp_path, monkeypatch):
        def boom(cpu=None):
            raise OSError("no cpu info")
        monkeypatch.setattr(economy_profile, "recommend_operator_workers", boom)
        result = point_contract("autoscale", make_ctx(state_dir=tmp_path), expect="error")
        assert result.reason_code == "point_exception"
