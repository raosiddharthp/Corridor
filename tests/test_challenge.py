import pytest

from pipeline.challenge import ChallengeLimitError, MemoryChallengeStore

AUD = "corridor-payment-processor"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _store(**kwargs):
    clock = Clock()
    return MemoryChallengeStore(clock=clock, **kwargs), clock


def test_issued_challenge_is_accepted_once():
    store, _ = _store()
    c = store.issue(AUD)
    assert store.consume(AUD, c.nonce)
    assert not store.consume(AUD, c.nonce)


def test_unknown_nonce_is_rejected():
    store, _ = _store()
    assert not store.consume(AUD, "never-issued")


def test_wrong_audience_is_rejected_and_burns_the_nonce():
    store, _ = _store()
    c = store.issue(AUD)
    assert not store.consume("someone-else", c.nonce)
    assert not store.consume(AUD, c.nonce)


def test_expired_challenge_is_rejected():
    store, clock = _store(ttl=60)
    c = store.issue(AUD)
    clock.now += 60
    assert not store.consume(AUD, c.nonce)


def test_challenge_is_valid_just_before_expiry():
    store, clock = _store(ttl=60)
    c = store.issue(AUD)
    clock.now += 59.9
    assert store.consume(AUD, c.nonce)


def test_nonces_are_unique():
    store, _ = _store()
    assert len({store.issue(AUD).nonce for _ in range(50)}) == 50


def test_limit_is_enforced_and_expired_entries_are_purged():
    store, clock = _store(ttl=60, max_outstanding=2)
    store.issue(AUD)
    store.issue(AUD)
    with pytest.raises(ChallengeLimitError):
        store.issue(AUD)
    clock.now += 61
    store.issue(AUD)
