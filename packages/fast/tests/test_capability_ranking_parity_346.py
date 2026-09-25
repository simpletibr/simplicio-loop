import hashlib
import json
from pathlib import Path

from simplicio_fast.capability_ranking import CapabilityCandidate, rank_capabilities


FIXTURE = Path(__file__).parents[1] / "fixtures" / "delivery" / "v1" / "issue346-capability-ranking-parity.json"


def _digest(value: dict[str, object]) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_python_filtering_and_ranking_match_shared_golden_vectors() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["schema"] == "simplicio.fast.capability-ranking-parity/v1"
    for case in fixture["cases"]:
        request = case.get("request", {})
        result = rank_capabilities(
            [CapabilityCandidate(**candidate) for candidate in case["candidates"]],
            case["required"],
            max_results=request.get("max_results", 32),
            required_scope=request.get("required_scope"),
            required_trust=request.get("required_trust"),
            max_freshness_seconds=request.get("max_freshness_seconds"),
        )
        assert _digest(result) == case["expected_sha256"], case["name"]
