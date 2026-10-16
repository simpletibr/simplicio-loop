"""`turbo`: the two-command task flow (Mapper survey, then dev-cli apply).

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations



def add_turbo(sub):
    p_turbo = sub.add_parser(
        "turbo",
        help="run a task in two commands: Mapper survey, you write the plan, dev-cli applies it (no key needed)",
        description=(
            "Default way to run a task, in exactly two commands; `simplicio-loop \"<task>\"` is the shortest form "
            "of the first. Host mode needs no provider and no key: the invoking model plans and "
            "simplicio-dev-cli edits. Command 1, `turbo --task T [--verify V]`: Mapper surveys the repo and "
            "the command prints a request (status needs_plan): the task, the map slice, the current text of "
            "the files it names, the plan format and the ONE next command, with a heredoc for the plan. "
            "Command 2, `turbo --apply - [--verify V] <<'PLAN'` followed by the find/replace JSON plan and "
            "`PLAN`: the plan is read from stdin (`--apply FILE` reads a file), dev-cli applies it and "
            "--verify runs the tests; status ok or failed, with dev-cli's reason and an excerpt of the file "
            "when a find did not match. Do not explore, list or read files, or run the tests yourself, "
            "between the two. `--provider openrouter` is headless automation only; agents invoking the "
            "skill must not use it: one model call per lane to OpenRouter (deepseek/deepseek-v4.1-flash, "
            "override with SIMPLICIO_TURBO_MODEL) on a pinned session with reasoning off; it needs "
            "OPENROUTER_API_KEY and stops with turbo_provider_key_missing without it. Prints one JSON "
            "document; exit 0 ok or needs_plan, 1 failed, 2 blocked."
        ),
    )
    p_turbo.add_argument("--repo", default=".", help="repository to change (default: .)")
    p_turbo.add_argument("--task", action="append", default=[],
                         help="task text; repeat for several tasks. Name the files to change in the text")
    p_turbo.add_argument("--target", help="with one --task: the file to create or change")
    p_turbo.add_argument("--context", action="append", default=[],
                         help="with one --task: another file the model must see; repeatable")
    p_turbo.add_argument("--tasks-file", help="JSON list of {text, target?, context?, depends_on?}")
    p_turbo.add_argument("--window", action="append", default=[], metavar="PATH:START-END",
                         help="request: also show these lines of a file too big to be shown whole; repeatable")
    p_turbo.add_argument("--verify", help="shell command run in the repo after the plan is applied, e.g. tests")
    p_turbo.add_argument("--apply", metavar="PLAN",
                         help="command 2: apply this JSON find/replace plan through dev-cli, then run --verify; "
                              "`-` reads the plan from stdin (a heredoc), anything else is a file")
    p_turbo.add_argument("--run-id", metavar="ID",
                         help="continue the run the request printed: its stage events and receipts join that run")
    p_turbo.add_argument("--leave-open", action="store_true",
                         help="with --apply and --run-id: an ok run stays open after verify, for the caller to close "
                              "(the 24/7 watcher writes its pr stage, then done)")
    p_turbo.add_argument("--provider", choices=["openrouter"],
                         help="headless automation only; agents invoking the skill must not use it "
                              "(asks this provider for the plan, needs OPENROUTER_API_KEY)")
