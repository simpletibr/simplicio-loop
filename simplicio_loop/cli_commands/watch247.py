"""`watch247`: the 24/7 watcher for the repos of SIMPLICIO_247_OWNERS.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations

_WATCH247_QUIET = ("The GitHub token is never an argument: pipe it to --github-token-stdin (with --email), "
                   "or run `watch247 setup` in a terminal for a hidden prompt. See --help.")


def add_watch247(sub):
    p_watch247 = sub.add_parser(
        "watch247", help="run the 24/7 watcher for SIMPLICIO_247_OWNERS repos", allow_abbrev=False,
        quiet=_WATCH247_QUIET)
    p_watch247.add_argument("action", nargs="?", choices=["login-check", "setup"],
                            help="login-check: exec CLI logins (#1467); setup: first-run credentials")
    p_watch247.add_argument("--email", help="setup: the Simplicio account e-mail")
    p_watch247.add_argument("--github-token-stdin", action="store_true",
                            help="setup: read the GitHub token from stdin (never an argument: argv shows in ps)")
    p_watch247.add_argument("--check", action="store_true",
                            help="setup: only check the Simplicio account step (after the login); no token is asked")
    p_watch247.add_argument("--once", action="store_true", help="run one tick and exit")
    p_watch247.add_argument("--dry-run", action="store_true", help="simulate without mutations")
    p_watch247.add_argument("--state-dir", help="override state directory")
    p_watch247.add_argument(
        "--mode", choices=("batch", "lockfree"), default=None,
        help="merge train mode (default: batch, or SIMPLICIO_247_MERGE_MODE when set). batch: one cumulative test per batch of up to 4 approved PRs, bisect on red, "
             "serial merge. lockfree (opt-in, #1820): merge each approved PR whose targeted tests are green, run the impacted "
             "tests on main after it, and open a revert PR on red (never force-push, never merge a revert). The approval gate "
             "applies to both modes; a merge still needs SIMPLICIO_247_AUTO_MERGE=1. See docs/MERGE_LOCKFREE.md.")
