# Stage wave concurrency

`StageAgentCoordinator.run_all()` submits every dependency-ready stage in a wave at
once. The host slot grant (`host_total_slots - coordinator_slots`) is the only
concurrency limit: the coordinator does not let adapters create extra capacity. A
grant of one uses an explicit serial path. Later waves are evaluated only after the
current wave has completed, so every prerequisite receipt must already be accepted.

The append-only journal remains the recovery authority. Accepted `stage_passed`
events are replayed on restart and their stages are not submitted again. A
`wave_completed` event is emitted in sorted stage-ID order with raw queue wait,
overlap, elapsed time, throughput and slot count. Portable adapters currently do not
offer per-stage CPU/RSS counters, so both fields are `null` with an explicit
`resource_metrics_unavailable_reason` rather than a fabricated zero.

`cancel_stage()` cancels one active adapter instance. `cancel_all()` first prevents
admission of another wave, then requests cancellation of active stages in sorted
order. Receipts and dependency gates still decide the final result; cancellation can
never be converted into a pass.

Run the focused unit/integration/system regression and coverage gate with:

```bash
PYTHONPATH=. python3 -m pytest tests/test_stage_agent_coordinator.py \
  --cov=simplicio_loop.stage_agent_coordinator --cov-branch --cov-report=term-missing
```

The executable real-process capacity test is
`test_wave_capacity_bounds_real_child_processes`; the overlap test also reports raw
wave timing through `coordinator.wave_metrics`.
