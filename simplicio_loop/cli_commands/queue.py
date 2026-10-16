"""`queue`: the durable local task queue.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations



def add_queue(sub):
    p_queue = sub.add_parser("queue", help="operate the durable local task queue")
    p_queue.add_argument("--repo", default=".")
    p_queue.add_argument(
        "--route", choices=("legacy", "mapper"), default="mapper",
        help="storage route (default: mapper; use legacy only for compatibility actions)",
    )
    p_queue.add_argument("--mapper-db", default=None)
    p_queue.add_argument("--mapper-init", action="store_true")
    queue_sub = p_queue.add_subparsers(dest="queue_action", required=True)
    queue_help = {
        "status": "show queue health and pending work",
        "resume": "resume a legacy queue task",
        "doctor": "check queue storage and MapperStore readiness",
        "reclaim": "reclaim abandoned queue work",
    }
    for queue_action in ("status", "resume", "doctor", "reclaim"):
        queue_sub.add_parser(queue_action, help=queue_help[queue_action])
    queue_migrate = queue_sub.add_parser("migrate", help="migrate legacy queue state into MapperStore")
    queue_migrate.add_argument("--apply", action="store_true")
    queue_top = queue_sub.add_parser("top", help="list the highest-priority ready queue tasks")
    queue_top.add_argument("--limit", type=int, default=20)
    queue_drain = queue_sub.add_parser("drain", help="wait for active queue work to finish")
    queue_drain.add_argument("--timeout", type=float, default=0.0)
    queue_gc = queue_sub.add_parser("gc", help="garbage-collect retained queue state")
    queue_gc.add_argument("--apply", action="store_true")
    for queue_action in ("inspect", "cancel"):
        queue_help_text = {
            "inspect": "inspect one task by id",
            "cancel": "cancel one task by id",
        }
        queue_command = queue_sub.add_parser(queue_action, help=queue_help_text[queue_action])
        queue_command.add_argument("task_id")
