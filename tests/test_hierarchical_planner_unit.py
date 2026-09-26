import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import hierarchical_planner as planner  # noqa: E402


def _write_goal(root, goal):
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "scratchpad.md"), "w", encoding="utf-8") as f:
        f.write("---\niteration: 1\nmax_iterations: 5\n---\n%s\n" % goal)
    return loop


def test_planner_biases_bug_work_to_debug_and_escalates_after_repeated_stalls(tmp_path):
    root = str(tmp_path)
    loop = _write_goal(root, "Fix the failing bug in the loop gate")
    origin = planner.REPO
    try:
        planner._set_repo(root)
        planner.cmd_plan()
        with open(os.path.join(loop, "phase.json"), encoding="utf-8") as f:
            phase = json.load(f)
        assert phase["phase"] == "debug"

        with open(os.path.join(loop, "journal.jsonl"), "w", encoding="utf-8") as f:
            for i in range(1, 4):
                f.write(json.dumps({
                    "iteration": i,
                    "action": "retry flaky test",
                    "gate": "fail",
                    "fingerprint": "same-fp",
                }) + "\n")

        planner.cmd_plan()
        with open(os.path.join(loop, "phase.json"), encoding="utf-8") as f:
            phase = json.load(f)
        assert phase["phase"] == "explore"

        with open(os.path.join(loop, "journal.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "iteration": 4,
                "action": "retry flaky test",
                "gate": "fail",
                "fingerprint": "same-fp",
            }) + "\n")

        planner.cmd_plan()
        with open(os.path.join(loop, "phase.json"), encoding="utf-8") as f:
            phase = json.load(f)
        assert phase["phase"] == "escalate"
        assert phase["execution_state"] == "stalled"
    finally:
        planner._set_repo(origin)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_hierarchical_planner")
