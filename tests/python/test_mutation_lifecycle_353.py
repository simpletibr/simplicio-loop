import pytest
from simplicio.mutation_worker import MutationBlocked, MutationWorker
from simplicio.mutation_lifecycle import MUTABLE_ENTRYPOINTS, recover, rollback, verify_receipt
from tests.python.mutation_353_helpers import plan

def test_verified_receipt_and_rollback_e2e(tmp_path):
    worker=MutationWorker(tmp_path)
    receipt=worker.execute(plan(),lambda _:{"status":"ok","applied":True,"before_hash":"a","after_hash":"b"})
    assert verify_receipt(receipt)
    rolled=rollback(worker,"k",lambda prior:{"status":"restored","restored_hash":prior["before_hash"]})
    assert rolled["status"]=="restored" and rolled["mutation_receipt_hash"]==receipt["receipt_hash"]

def test_crash_resume_by_independent_observation(tmp_path):
    worker=MutationWorker(tmp_path)
    with pytest.raises(RuntimeError):
        worker.execute(plan(),lambda _:(_ for _ in ()).throw(RuntimeError()))
    receipt=recover(worker,"k",lambda:{"status":"committed","plan_id":"p","before_hash":"a","after_hash":"b"})
    assert verify_receipt(receipt)

def test_inventory_covers_declared_mutable_cli_surface():
    assert {"task","run","mechanical-edit","changeset","edit","test.run",
            "cache.clear","memory.store","prototype.apply"} <= MUTABLE_ENTRYPOINTS
