"""Regression tests for the bounded async inventory worker queue."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simplicio_mapper.mapper.async_pipeline import build_file_inventory_async


class BoundedWorkerQueueTest(unittest.TestCase):
    def test_fixed_workers_and_bounded_batches_preserve_sorted_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("z.py", "a.py", "m.py", "b.py", "y.py"):
                (root / name).write_text(f"VALUE = {len(name)}\n", encoding="utf-8")
            degraded: dict = {}
            with mock.patch.dict(
                os.environ,
                {
                    "SIMPLICIO_MAPPER_ASYNC_BATCH_SIZE": "2",
                    "SIMPLICIO_MAPPER_ASYNC_BATCH_FACTOR": "2",
                },
            ):
                files = asyncio.run(
                    build_file_inventory_async(
                        str(root), {}, {}, max_concurrent=2, degraded=degraded
                    )
                )

        self.assertEqual([entry.path for entry in files], sorted(entry.path for entry in files))
        self.assertEqual(
            {
                "workers": 2,
                "batch_size": 2,
                "queue_capacity": 4,
                "tasks_created": 2,
                "batches_submitted": 3,
            },
            degraded["async_pipeline"],
        )


if __name__ == "__main__":
    unittest.main()
