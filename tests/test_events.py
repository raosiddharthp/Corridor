import json

import pytest

import pipeline.events as ev


def _log(**kwargs):
    return ev.MemoryEventLog(**kwargs)


def test_sequence_numbers_start_at_one_and_increase():
    log = _log()
    first = log.append("r1", "run.started")
    second = log.append("r1", "run.completed")
    assert (first.seq, second.seq) == (1, 2)


def test_read_after_returns_only_later_events():
    log = _log()
    for kind in ("run.started", "negotiation.offer", "run.completed"):
        log.append("r1", kind)
    assert [e.seq for e in log.read("r1", after=1)] == [2, 3]


def test_unknown_kind_is_rejected():
    with pytest.raises(ev.EventLogError):
        _log().append("r1", "made.up")


@pytest.mark.parametrize("bad", ["", "../x", "a" * 65])
def test_invalid_run_ids_are_rejected(bad):
    with pytest.raises(ev.EventLogError):
        _log().append(bad, "run.started")


def test_secrets_are_redacted_by_key_name():
    data = {"checkout_jwt": "a.b.c", "note": "hi", "nested": {"api_key": "k"}}
    event = _log().append("r1", "negotiation.offer", data)
    assert event.data["checkout_jwt"] == ev.REDACTED
    assert event.data["nested"]["api_key"] == ev.REDACTED
    assert event.data["note"] == "hi"


def test_long_text_is_truncated():
    event = _log().append("r1", "run.started", {"text": "x" * 5000})
    assert len(event.data["text"]) == ev.MAX_STR


def test_non_json_values_are_rejected():
    with pytest.raises(ev.EventLogError):
        _log().append("r1", "run.started", {"obj": object()})


def test_deeply_nested_data_is_rejected():
    data = {}
    for _ in range(6):
        data = {"a": data}
    with pytest.raises(ev.EventLogError):
        _log().append("r1", "run.started", data)


def test_a_run_cannot_grow_without_limit():
    log = _log(max_events_per_run=2)
    log.append("r1", "run.started")
    log.append("r1", "run.completed")
    with pytest.raises(ev.EventLogError):
        log.append("r1", "run.failed")


def test_the_oldest_run_is_evicted():
    log = _log(max_runs=2)
    for run in ("r1", "r2", "r3"):
        log.append(run, "run.started")
    assert log.read("r1") == []
    assert len(log.read("r3")) == 1


def test_events_are_json_serialisable():
    event = _log().append("r1", "tier.decision", {"tier": "tier1", "drift_bps": 0})
    assert json.loads(json.dumps(ev.to_dict(event)))["kind"] == "tier.decision"


def test_control_characters_are_stripped_from_text():
    event = _log().append("r1", "run.started", {"t": "a\x00b\u200bc"})
    assert event.data["t"] == "abc"


def test_reading_an_unknown_run_gives_nothing():
    assert _log().read("nope") == []


def test_the_clock_is_injectable():
    assert _log(clock=lambda: 42.0).append("r1", "run.started").ts == 42.0


def test_non_finite_numbers_are_rejected():
    with pytest.raises(ev.EventLogError):
        _log().append("r1", "run.started", {"x": float("nan")})
