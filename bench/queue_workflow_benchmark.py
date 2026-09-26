"""Read-only environment identity for the queue benchmark preparation."""
import importlib.metadata
import json
import os
from pathlib import Path
import hashlib
import simplicio_loop
import argparse
import datetime
import subprocess
import time

TASKS = [
    ("GH-101", "github", "create", "Create slugify(text) in src/slug.py; lowercase, trim and join whitespace with hyphens."),
    ("GH-102", "github", "edit", "Fix total(values) in src/total.py to return the sum, including negative values and the empty list."),
    ("GH-103", "github", "search", "Find the timeout setting in config/settings.json and write its JSON pointer and value to answers/timeout.json."),
    ("GH-104", "github", "tests", "Add tests/test_total.py covering empty input, negative numbers and three positive numbers."),
    ("JIRA-201", "jira", "create", "Create unique(values) in src/unique.py preserving first occurrence order."),
    ("JIRA-202", "jira", "edit", "Fix clamp(value, low, high) in src/clamp.py to preserve values inside the interval."),
    ("JIRA-203", "jira", "docs", "Document the configured timeout value and its unit in docs/configuration.md."),
    ("ADO-301", "azuredevops", "search", "Find all deprecated=true entries in data/endpoints.json and write their sorted names to answers/deprecated.json."),
    ("ADO-302", "azuredevops", "create", "Create median(values) in src/median.py supporting odd and even nonempty lists."),
    ("ADO-303", "azuredevops", "edit", "Fix parse_bool(text) in src/boolean.py to accept true/false case-insensitively and reject other values."),
]

def prepare(include_requirements=False):
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = root / ".simplicio-loop/benchmark" / ("queue-3.43.10-" + stamp)
    fixture = out / "fixture"
    fixture.mkdir(parents=True)
    files = {
        ".gitignore": ".simplicio-loop/\n__pycache__/\n",
        "src/total.py": "def total(values):\n    return len(values)\n",
        "src/clamp.py": "def clamp(value, low, high):\n    return low\n",
        "src/boolean.py": "def parse_bool(text):\n    return bool(text)\n",
        "config/settings.json": '{"network":{"timeout_seconds":30}}\n',
        "data/endpoints.json": '[{"name":"legacy","deprecated":true},{"name":"current","deprecated":false},{"name":"v0","deprecated":true}]\n',
    }
    for name, body in files.items():
        path = fixture / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    if include_requirements:
        requirements = fixture / "requirements"
        requirements.mkdir()
        for task_id, source, kind, goal in TASKS:
            dependency = "Dependency: GH-102 must pass before GH-104.\n" if task_id == "GH-104" else ""
            (requirements / (task_id + ".md")).write_text(
                f"# {task_id}\n\nSource simulation: {source}. Work kind: {kind}.\n\n{goal}\n\n{dependency}"
                "This is an input specification, not evidence of implementation or test success.\n")
    rows = []
    def command(argv, phase, cwd=fixture):
        start = time.perf_counter_ns()
        try:
            result = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=90)
            code, stdout, stderr = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            code, stdout, stderr = None, "", "timeout; no retry"
        row = dict(argv=argv, phase=phase, exit_code=code,
                   wall_ns=time.perf_counter_ns()-start)
        index = len(rows)
        (out / f"command-{index}.stdout.txt").write_text(stdout)
        (out / f"command-{index}.stderr.txt").write_text(stderr)
        rows.append(row)
        (out / "commands.json").write_text(json.dumps(rows, indent=2))
        print(phase, code, round(row["wall_ns"]/1e6, 2), "ms", flush=True)
        return code
    for argv in (["git", "init", "-q"], ["git", "add", "."],
                 ["git", "-c", "user.name=Benchmark", "-c", "user.email=benchmark@localhost", "commit", "-qm", "fixture"]):
        if command(argv, "fixture") != 0:
            return 2
    sources = {name: [] for name in ("github", "jira", "azuredevops")}
    for task_id, source, kind, goal in TASKS:
        item = dict(id=task_id, source=source, kind=kind, goal=goal, simulated_source=True)
        sources[source].append(item)
        task = out / f"{task_id}.md"
        task.write_text(f"System: QueueBenchmark\nFeature: {task_id} {goal}\nType: Change\n\nAS A maintainer\nI WANT {goal}\nSO THAT the fixture meets its documented behavior\n\n1. Acceptance Criteria\n\nScenario 1: {goal}\n  Given the isolated fixture\n  When the task is delivered\n  Then its independent verifier passes [RN01]\n\n2. Business Rules\n\nRN01 - Modify only the named fixture paths.\n")
        command(["simplicio-loop", "plan", "--task", str(task), "--out", str(out / f"{task_id}.contract.json")], "plan:"+task_id)
    (out / "simulated-sources.json").write_text(json.dumps(sources, indent=2))
    command(["simplicio-mapper", "scan", str(fixture), "--sync", "--json"], "central_mapper")
    command(["simplicio-mapper", "inspect", str(fixture), "--json"], "central_inspect")
    (out / "status.json").write_text(json.dumps({
        "status": "PREPARATION_ONLY", "task_count": 10, "implemented_tasks": 0,
        "openrouter_key_present": bool(os.environ.get("OPENROUTER_API_KEY")),
        "model_calls": 0, "winner": None,
        "remaining": ["independent verifiers", "live provider runner", "serial/wave/Fast trials", "CPU/RAM sampler", "provider usage receipts"],
    }, indent=2))
    print("artifact:", out, flush=True)
    return 0 if all(row["exit_code"] == 0 for row in rows) else 2

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="create isolated simulated queues and measure central preparation")
    parser.add_argument("--include-requirements", action="store_true", help="freeze input specifications in the initial seed before central mapping")
    args = parser.parse_args()
    if args.prepare:
        raise SystemExit(prepare(args.include_requirements))
    package = Path(simplicio_loop.__file__).resolve().parent
    identity = {
        "loop_version": importlib.metadata.version("simplicio-loop"),
        "package": str(package),
        "prism_sha256": hashlib.sha256((package / "prism_scheduler.py").read_bytes()).hexdigest(),
        "openrouter_key_present": bool(os.environ.get("OPENROUTER_API_KEY")),
    }
    for field, value in identity.items():
        print(f"{field}: {value}")
