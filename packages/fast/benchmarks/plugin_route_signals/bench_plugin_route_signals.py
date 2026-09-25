"""Cold/warm/batch PluginRouteSignals benchmark. No LLM, no mutation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from simplicio_fast.plugin_route_signals import PluginRouteRequest, measure_route_signals


def sample(iterations: int = 100, batch_size: int = 32) -> dict:
    request = PluginRouteRequest(
        generation="g1",
        source_hashes={"src/app.py": "a" * 64},
        targets=["src/app.py"],
        graph={
            "nodes": ["src/app.py", "src/cli.py"],
            "edges": [{"from": "src/cli.py", "to": "src/app.py"}],
        },
        packet_metadata={"encoded_bytes": 1694},
        cache_state={"hits": 3, "misses": 1},
    )
    return measure_route_signals(request, iterations=iterations, batch_size=batch_size)


if __name__ == "__main__":
    print(json.dumps(sample(), sort_keys=True, separators=(",", ":")))
