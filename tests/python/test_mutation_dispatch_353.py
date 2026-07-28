import json
from pathlib import Path
import pytest
from simplicio.mutation_dispatch import guard_mutable_dispatch
from simplicio.mutation_worker import MutationBlocked
from test_mutation_worker_353 import plan

def test_every_inventory_route_fails_closed_without_stage_plan():
    from simplicio.mutation_lifecycle import MUTABLE_ENTRYPOINTS
    for route in MUTABLE_ENTRYPOINTS:
        argv=route.split(".")
        with pytest.raises(MutationBlocked,match="MECHANICAL_PLAN_REQUIRED"):
            guard_mutable_dispatch(argv,{"SIMPLICIO_STAGE_ABI":"1"})

def test_valid_stage_plan_and_read_only_compatibility(tmp_path):
    p=plan(tmp_path); path=tmp_path/"plan.json"; path.write_text(json.dumps(p))
    env={"SIMPLICIO_STAGE_ABI":"1","SIMPLICIO_MECHANICAL_PLAN":str(path),
         "SIMPLICIO_WORKSPACE":str(tmp_path),"SIMPLICIO_IDEMPOTENCY_KEY":"k"}
    guard_mutable_dispatch(["edit"],env)
    guard_mutable_dispatch(["status"],{"SIMPLICIO_STAGE_ABI":"1"})

def test_nested_mutating_routes_cannot_bypass_guard():
    for argv in (["token","context-cache","put"],["prototype","promote"],["cache","clear"]):
        with pytest.raises(MutationBlocked,match="MECHANICAL_PLAN_REQUIRED"):
            guard_mutable_dispatch(argv,{"SIMPLICIO_STAGE_ABI":"1"})

def test_cli_main_calls_guard_before_parser_dispatch():
    source=(Path(__file__).parents[2]/"simplicio/cli.py").read_text()
    guard=source.index("guard_mutable_dispatch(argv")
    parser=source.index("_build_parser()",guard)
    assert guard < parser
