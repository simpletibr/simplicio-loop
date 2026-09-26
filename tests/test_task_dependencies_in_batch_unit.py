"""A dependency on a task in the SAME dispatch batch is satisfied by the
batch's serial order, not by a result marker that cannot exist yet."""
import pytest

from simplicio_loop.runner import _assert_task_dependencies_ready

TASKS = [
    {"identity": {"system": "cadastro-1"}},
    {"identity": {"system": "cadastro-2"}, "dependencies": {"state": "declared", "items": ["Depends on: task 1"]}},
]


def test_dependency_inside_the_batch_is_not_required_to_be_completed(tmp_path):
    _assert_task_dependencies_ready(tmp_path, TASKS, 2, "run-x", in_batch={1, 2})


def test_dependency_outside_the_batch_must_be_completed(tmp_path):
    with pytest.raises(RuntimeError, match="task 2 requires task 1"):
        _assert_task_dependencies_ready(tmp_path, TASKS, 2, "run-x", in_batch={2})
