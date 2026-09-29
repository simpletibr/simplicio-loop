"""Queue lease primitives shared by the Mapper-backed local task queue.

Task, lease and fencing state is owned by MapperStore (see
:mod:`simplicio_loop.mapper_remote_queue`); this module only holds the value types callers
exchange with it. There is no fail-open path: an unavailable store raises
:class:`QueueUnavailable` and callers must hand off rather than mutate a task.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


class QueueConflict(RuntimeError):
    """The caller lost a lease or presented an old fencing token."""


class QueueUnavailable(RuntimeError):
    """The queue could not be reached; mutation must pause and hand off."""


@dataclass(frozen=True)
class Lease:
    task_id: str
    agent_id: str
    lease_id: str
    fencing_token: int | str
    expires_at: float
    idempotency_key: str
    identity: Optional[Dict[str, Any]] = None
    capabilities: tuple[str, ...] = ()
    cancelled: bool = False
    # MapperStore operations use an opaque attempt id in addition to the
    # queue lease id.
    attempt_id: str = ""
