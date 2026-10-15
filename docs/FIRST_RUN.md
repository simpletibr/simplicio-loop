# First run: from an empty repo to a merged change

This page takes you from an empty git repository to one merged change, with the exact
sequence `orient` → `prepare` → `wave` → `verify`. The model writes one plan between
`prepare` and `wave`. Every other step is deterministic.

A system test (`tests/test_first_run_system.py`) runs the commands of the block marked
`first-run` below in a throwaway repository. The model step needs a model, so the test
stops at the last deterministic step. It checks the `next:` line that `wave` prints.

## 1. Check the install

You need `simplicio-loop`, `simplicio-mapper` and `simplicio-dev-cli` on your PATH.

```sh
simplicio-loop preflight --repo .
```

It must print `all_present: true`. If it prints a `version drift:` line, the installed
`simplicio-loop` is older than the source checkout it was installed from. Run the fix
command on that line before you go on.

## 2. Make the repository

```sh
mkdir calc && cd calc
git init -q
mkdir tests
printf 'def add(a, b):\n    return a + b\n' > calc/ops.py
printf '' > calc/__init__.py
printf 'def test_add():\n    from calc.ops import add\n    assert add(1, 2) == 3\n' > tests/test_ops.py
git add -A && git commit -qm "initial calc"
```

## 3. Run the sequence

The block below is the one the system test runs. It starts from the repository root,
so `--repo .` is that root.

```bash first-run
simplicio-loop preflight --repo .
simplicio-loop orient --brief --repo . --task "add mul(a, b) to calc/ops.py" --target calc/ops.py
simplicio-loop prepare --example > task.md
simplicio-loop prepare --repo . --task task.md
simplicio-loop wave <run_id> --repo .
```

What each step does:

1. `preflight` checks the bound operators and the version.
2. `orient --brief` runs the Mapper survey over the repository and prints the route,
   the files and the apply command. It writes nothing into your sources.
3. `prepare --example` prints a valid task file. Edit it for your change: keep the shape,
   replace the text. The shape is the one `prepare` reads, with a `1. Acceptance Criteria`
   line (no `#`), a `Scenario N:` with `Given`, `When` and `Then`, a `2. Business Rules`
   section for every `[RNnn]` you reference, and an `8. Additional Information` section
   with the verifier lines.
4. `prepare --task task.md` arms a run and prints its `run_id` and `run_dir`. Nothing is
   edited yet. If it is blocked, the `next:` line on stderr names the exact element to fix,
   with its line number.
5. `wave <run_id>` applies the plan of the run and runs the verifiers.

## 4. The model step (between prepare and wave)

Before `wave`, the model writes the plan into the run directory that `prepare` printed:

```
<run_dir>/edit-plan-1.json
```

The minimal form is a list of exact find-and-replace operations on files the task may touch:

```json
{"operations": [{"path": "calc/ops.py", "find": "def add(a, b):\n    return a + b\n", "replace": "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"}]}
```

The schema of the full form is `simplicio.dev-cli.edit-plan/v1`
(`packages/dev-cli/contracts/dev-cli-edit/edit-plan.schema.json` in the simplicio-loop checkout).

If `wave` runs before the plan is in place, the run is blocked at `plan_required`. A blocked
run takes no plan later. The output then carries a top-level `plan_required` block with the
schema, the steps and the apply command, and one `next:` line. Start again with a new
`prepare`, write the plan into the new run directory, and run `wave` with the new `run_id`.

## 5. Verify and merge

When `wave` prints `"status": "VERIFIED"`, check the run again and then merge:

```sh
simplicio-loop verify <run_id> --repo .
git add -A && git commit -m "add mul(a, b)"
```

Open the pull request from the branch in the usual way. The watcher never merges by itself.

If you prefer one command for the plan and the apply, `simplicio-loop turbo` does both in a
single call. See `docs/CLI_COMMANDS.md`, the `turbo` row.

## When something is BLOCKED

Every BLOCKED result prints one `next:` line on stderr, and stdout stays one JSON document:

| `next:` names | What to do |
|---|---|
| `orient --brief` | the Mapper survey is missing; run the command it names, then `prepare` again |
| a task file `line N` | the task shape is off at that line; fix it as the line says, or copy `prepare --example` |
| `status --run-id` | the run is blocked for the reason shown; read it there, then prepare a new run |
| `plan_required` | write the plan into a new run (section 4) |
| a `version drift` line | the installed `simplicio-loop` is older than its checkout; run the fix command |
