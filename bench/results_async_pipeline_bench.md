# Async pipeline benchmark (issue #212)

- Tasks: 8, simulated IO per task: 0.1s, concurrency: 4
- Sequential (existing `run_task` loop): 0.8023s
- Concurrent (`run_tasks_async`): 0.3614s
- Speedup: 2.22x
- Platform: Windows-11-10.0.26100-SP0 / Python 3.14.5
