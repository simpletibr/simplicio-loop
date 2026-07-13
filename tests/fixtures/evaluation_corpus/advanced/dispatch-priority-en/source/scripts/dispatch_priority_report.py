def render_dispatch_priority_report(rows):
    return [
        f"{row['queued_at']}::{row['outage_risk']}::{row['service_class']}"
        for row in rows
    ]
