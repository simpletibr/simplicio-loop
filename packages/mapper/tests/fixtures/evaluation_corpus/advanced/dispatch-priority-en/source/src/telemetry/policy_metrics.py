def emit_dispatch_policy_metrics(job):
    return {
        "dispatch_policy": job["service_class"],
        "outage_risk": job["outage_risk"],
        "queued_at": job["queued_at"],
    }
