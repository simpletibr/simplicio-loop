from src.scheduling.dispatch_policy import rank_dispatch_jobs


def test_rank_dispatch_jobs_prefers_risk_then_service_class():
    jobs = [
        {"id": "b", "outage_risk": "high", "service_class": "residential", "queued_at": "2026-01-02T10:00:00Z"},
        {"id": "a", "outage_risk": "critical", "service_class": "industrial", "queued_at": "2026-01-02T11:00:00Z"},
    ]
    assert [job["id"] for job in rank_dispatch_jobs(jobs)] == ["a", "b"]
