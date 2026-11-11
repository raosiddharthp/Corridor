from pipeline.approvals import MemoryApprovalStore


def _add(store, run_id="r1"):
    return store.add(run_id, "FP-88214", "a.b.c", 35_200_000, "txn", ["drift"])


def test_take_returns_what_was_added():
    store = MemoryApprovalStore()
    _add(store)
    pending = store.take("r1")
    assert pending.total_minor == 35_200_000
    assert pending.reasons == ("drift",)


def test_an_approval_can_be_taken_only_once():
    store = MemoryApprovalStore()
    _add(store)
    store.take("r1")
    assert store.take("r1") is None


def test_an_expired_approval_cannot_be_taken():
    now = [1000.0]
    store = MemoryApprovalStore(ttl=10, clock=lambda: now[0])
    _add(store)
    now[0] += 11
    assert store.take("r1") is None


def test_peek_does_not_consume():
    store = MemoryApprovalStore()
    _add(store)
    assert store.peek("r1") is not None
    assert store.take("r1") is not None


def test_the_oldest_pending_approval_is_evicted():
    store = MemoryApprovalStore(max_pending=2)
    for run in ("r1", "r2", "r3"):
        _add(store, run)
    assert store.peek("r1") is None
    assert store.peek("r3") is not None


def test_the_public_view_omits_the_signed_checkout():
    public = _add(MemoryApprovalStore()).public()
    assert "checkout_jwt" not in public
    assert "a.b.c" not in public.values()
