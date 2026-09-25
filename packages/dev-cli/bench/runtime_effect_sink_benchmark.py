"""Microbenchmark for EffectTransaction mapping + verified receipt persistence."""

from __future__ import annotations

import json
import logging
import statistics
import sys
import tempfile
import time
from pathlib import Path

from simplicio.plan_compiler import EffectPlan, PlanNode
from simplicio.plan_compiler.canonical_hash import canonical_hash
from simplicio.plan_compiler.effect_sink import EffectDispatchContext
from simplicio.plan_compiler.runtime_effect_sink import RECEIPT_SCHEMA, TRANSACTION_SCHEMA, RuntimeEffectSink


class LoopbackTransport:
    name = "http-json"

    def capabilities(self):
        return {
            "runtime_version": "1.0",
            "effect_transaction_schemas": [TRANSACTION_SCHEMA],
            "transports": [self.name],
        }

    def submit(self, transaction):
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "state": "completed",
            "idempotency_key": transaction["idempotency_key"],
            "effect_digest": transaction["effect_digest"],
            "effect_id": transaction["causal"]["effect_id"],
            "plan_node_id": transaction["causal"]["plan_node_id"],
            "causal": transaction["causal"],
            "acceptance_criteria_refs": transaction["acceptance_criteria_refs"],
            "gate_decision": "allow",
            "base_hash": transaction["base_hash"],
            "source_hash": transaction["source_hash"],
            "validation": {"state": "passed"},
        }
        receipt["receipt_digest"] = canonical_hash(receipt)
        return receipt

    def query(self, key):
        raise AssertionError("benchmark uses unique transactions")


def main(iterations: int = 500) -> dict[str, float | int]:
    logging.disable(logging.CRITICAL)
    samples = []
    with tempfile.TemporaryDirectory() as directory:
        sink = RuntimeEffectSink(LoopbackTransport(), root=Path(directory))
        node = PlanNode("node", "edit.apply", write_set=["src/a.py"], acceptance_criteria_refs=["AC1"])
        for index in range(iterations):
            effect = EffectPlan(f"effect-{index}", "node", "write", "runtime", "ignored")
            context = EffectDispatchContext("plan", "goal", node, [], turn_id=str(index))
            started = time.perf_counter_ns()
            sink.submit(effect, context)
            samples.append((time.perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(samples)
    result = {
        "iterations": iterations,
        "median_ms": round(statistics.median(samples), 4),
        "p95_ms": round(ordered[int(iterations * 0.95) - 1], 4),
        "throughput_per_s": round(iterations / (sum(samples) / 1000), 2),
    }
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    main()
