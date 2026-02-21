"""Tests for GossipEngine: deduplication, storage, IHAVE/IWANT diff logic."""

import time

import pytest

from gossip.gossip_engine import GossipEngine
from gossip.protocol import Message


def _make_gossip(msg_id: str, data: str = "hello") -> Message:
    return Message(
        version=1,
        msg_id=msg_id,
        msg_type="GOSSIP",
        sender_id="origin-node",
        sender_addr="127.0.0.1:9000",
        timestamp_ms=int(time.time() * 1000),
        ttl=8,
        payload={
            "topic": "chat",
            "data": data,
            "origin_id": "origin-node",
            "origin_timestamp_ms": int(time.time() * 1000),
        },
    )


# ── store() ───────────────────────────────────────────────────────────────────

def test_store_returns_true_first_time():
    engine = GossipEngine()
    msg = _make_gossip("msg-001")
    assert engine.store(msg) is True


def test_store_returns_false_on_duplicate():
    engine = GossipEngine()
    msg = _make_gossip("msg-001")
    engine.store(msg)
    assert engine.store(msg) is False


def test_store_different_ids_both_true():
    engine = GossipEngine()
    assert engine.store(_make_gossip("msg-001")) is True
    assert engine.store(_make_gossip("msg-002")) is True


# ── has_seen() ────────────────────────────────────────────────────────────────

def test_has_seen_false_before_store():
    engine = GossipEngine()
    assert engine.has_seen("msg-001") is False


def test_has_seen_true_after_store():
    engine = GossipEngine()
    msg = _make_gossip("msg-001")
    engine.store(msg)
    assert engine.has_seen("msg-001") is True


def test_has_seen_does_not_affect_other_ids():
    engine = GossipEngine()
    engine.store(_make_gossip("msg-001"))
    assert engine.has_seen("msg-002") is False


# ── get_message() ─────────────────────────────────────────────────────────────

def test_get_message_returns_stored_message():
    engine = GossipEngine()
    msg = _make_gossip("msg-001", data="test data")
    engine.store(msg)
    retrieved = engine.get_message("msg-001")
    assert retrieved is not None
    assert retrieved.msg_id == "msg-001"
    assert retrieved.payload["data"] == "test data"


def test_get_message_returns_none_for_unknown():
    engine = GossipEngine()
    assert engine.get_message("nonexistent") is None


# ── get_missing_ids() ─────────────────────────────────────────────────────────

def test_get_missing_ids_returns_correct_diff():
    engine = GossipEngine()
    engine.store(_make_gossip("msg-001"))
    engine.store(_make_gossip("msg-002"))

    ids = ["msg-001", "msg-002", "msg-003", "msg-004"]
    missing = engine.get_missing_ids(ids)
    assert set(missing) == {"msg-003", "msg-004"}


def test_get_missing_ids_empty_when_all_known():
    engine = GossipEngine()
    engine.store(_make_gossip("msg-001"))
    engine.store(_make_gossip("msg-002"))
    assert engine.get_missing_ids(["msg-001", "msg-002"]) == []


def test_get_missing_ids_all_when_none_known():
    engine = GossipEngine()
    ids = ["msg-001", "msg-002"]
    missing = engine.get_missing_ids(ids)
    assert set(missing) == {"msg-001", "msg-002"}


def test_get_missing_ids_empty_input():
    engine = GossipEngine()
    assert engine.get_missing_ids([]) == []


# ── get_recent_ids() ──────────────────────────────────────────────────────────

def test_get_recent_ids_most_recent_first():
    engine = GossipEngine()
    for i in range(5):
        engine.store(_make_gossip(f"msg-{i:03d}"))
        time.sleep(0.001)  # ensure distinct timestamps
    ids = engine.get_recent_ids(10)
    # Should be ordered by received_at descending
    assert len(ids) == 5
    # The last stored should be first
    assert ids[0] == "msg-004"


def test_get_recent_ids_respects_max_count():
    engine = GossipEngine()
    for i in range(10):
        engine.store(_make_gossip(f"msg-{i:03d}"))
    ids = engine.get_recent_ids(3)
    assert len(ids) == 3


def test_get_recent_ids_empty_engine():
    engine = GossipEngine()
    assert engine.get_recent_ids(10) == []
