def rank_dispatch_jobs(jobs):
    risk_order = {"critical": 0, "high": 1, "normal": 2}
    class_order = {"restoration": 0, "industrial": 1, "residential": 2}
    return sorted(
        jobs,
        key=lambda job: (
            risk_order[job["outage_risk"]],
            class_order[job["service_class"]],
            job["queued_at"],
        ),
    )
