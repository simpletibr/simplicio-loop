from simplicio_fast.generation_store import GenerationError, GenerationStore


def test_twenty_overlays_isolated_and_deterministic(tmp_path):
    s = GenerationStore(tmp_path)
    g = s.create("r", "c", "cfg", "parser", {"x": b"base"})
    for i in range(20):
        s.pin(g.id, i, f"f{i}")
        s.write(g.id, f"s{i}", f"f{i}", "x", str(i).encode())
    assert [s.read(g.id, f"s{i}", f"f{i}", "x") for i in range(20)] == [
        str(i).encode() for i in range(20)
    ]


def test_tombstone_and_base():
    s = GenerationStore(".")
    g = s.create("r", "c", "x", "p", {"x": b"x"})
    s.pin(g.id, 1, "f")
    s.tombstone(g.id, "a", "f", "x")
    assert s.read(g.id, "a", "f", "x") is None and s.read(g.id, "b", "f", "x") == b"x"


def test_gc_protects_pin():
    s = GenerationStore(".")
    g = s.create("r", "c", "x", "p", {})
    s.pin(g.id, 1, "f")
    assert g.id not in s.gc()


def test_stale_fence_rejected():
    s = GenerationStore(".")
    g = s.create("r", "c", "x", "p", {})
    s.pin(g.id, 1, "f")
    try:
        s.pin(g.id, 1, "old")
        assert False
    except GenerationError as e:
        assert e.reason_code == "fence_stale"
