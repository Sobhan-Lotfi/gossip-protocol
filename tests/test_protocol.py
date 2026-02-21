"""Tests for message serialization round-trips and error handling."""

import json

import pytest

from gossip.protocol import Message, make_message, parse_addr


def _make_test_message(msg_type: str, payload: dict, ttl: int = 1) -> Message:
    return make_message(
        msg_type=msg_type,
        sender_id="test-sender-id",
        sender_addr="127.0.0.1:9000",
        payload=payload,
        msg_id="test-msg-id-0001",
        ttl=ttl,
    )


def _roundtrip(msg: Message) -> Message | None:
    return Message.from_bytes(msg.to_bytes())


# ── Round-trip tests ──────────────────────────────────────────────────────────

def test_hello_roundtrip():
    msg = _make_test_message("HELLO", {"capabilities": ["udp", "json"]})
    result = _roundtrip(msg)
    assert result is not None
    assert result.msg_type == "HELLO"
    assert result.msg_id == msg.msg_id
    assert result.sender_id == msg.sender_id
    assert result.payload["capabilities"] == ["udp", "json"]


def test_get_peers_roundtrip():
    msg = _make_test_message("GET_PEERS", {"max_peers": 20})
    result = _roundtrip(msg)
    assert result is not None
    assert result.msg_type == "GET_PEERS"
    assert result.payload["max_peers"] == 20


def test_peers_list_roundtrip():
    peers = [{"node_id": "abc", "addr": "127.0.0.1:9001"}]
    msg = _make_test_message("PEERS_LIST", {"peers": peers})
    result = _roundtrip(msg)
    assert result is not None
    assert result.msg_type == "PEERS_LIST"
    assert result.payload["peers"] == peers


def test_gossip_roundtrip():
    payload = {
        "topic": "chat",
        "data": "Hello network!",
        "origin_id": "origin-node-id",
        "origin_timestamp_ms": 1730000000000,
    }
    msg = _make_test_message("GOSSIP", payload, ttl=8)
    result = _roundtrip(msg)
    assert result is not None
    assert result.msg_type == "GOSSIP"
    assert result.ttl == 8
    assert result.payload["data"] == "Hello network!"


def test_ping_roundtrip():
    msg = _make_test_message("PING", {"ping_id": "some-uuid", "seq": 17})
    result = _roundtrip(msg)
    assert result is not None
    assert result.msg_type == "PING"
    assert result.payload["seq"] == 17


def test_pong_roundtrip():
    msg = _make_test_message("PONG", {"ping_id": "some-uuid", "seq": 17})
    result = _roundtrip(msg)
    assert result is not None
    assert result.msg_type == "PONG"
    assert result.payload["ping_id"] == "some-uuid"


def test_ihave_roundtrip():
    ids = ["id-1", "id-2", "id-3"]
    msg = _make_test_message("IHAVE", {"ids": ids})
    result = _roundtrip(msg)
    assert result is not None
    assert result.msg_type == "IHAVE"
    assert result.payload["ids"] == ids


def test_iwant_roundtrip():
    msg = _make_test_message("IWANT", {"ids": ["id-2"]})
    result = _roundtrip(msg)
    assert result is not None
    assert result.msg_type == "IWANT"
    assert result.payload["ids"] == ["id-2"]


def test_trigger_roundtrip():
    msg = _make_test_message("TRIGGER", {"data": "EXPERIMENT_PAYLOAD_42"})
    result = _roundtrip(msg)
    assert result is not None
    assert result.msg_type == "TRIGGER"
    assert result.payload["data"] == "EXPERIMENT_PAYLOAD_42"


# ── Error handling ────────────────────────────────────────────────────────────

def test_invalid_json_returns_none():
    result = Message.from_bytes(b"not valid json{{")
    assert result is None


def test_empty_bytes_returns_none():
    result = Message.from_bytes(b"")
    assert result is None


def test_missing_fields_returns_none():
    incomplete = json.dumps({"version": 1, "msg_type": "PING"}).encode()
    result = Message.from_bytes(incomplete)
    assert result is None


def test_unknown_msg_type_returns_none():
    obj = {
        "version": 1,
        "msg_id": "x",
        "msg_type": "UNKNOWN_TYPE",
        "sender_id": "s",
        "sender_addr": "127.0.0.1:9000",
        "timestamp_ms": 1000,
        "ttl": 1,
        "payload": {},
    }
    result = Message.from_bytes(json.dumps(obj).encode())
    assert result is None


def test_non_object_json_returns_none():
    result = Message.from_bytes(b"[1, 2, 3]")
    assert result is None


# ── parse_addr ────────────────────────────────────────────────────────────────

def test_parse_addr_basic():
    host, port = parse_addr("127.0.0.1:8000")
    assert host == "127.0.0.1"
    assert port == 8000


def test_parse_addr_high_port():
    host, port = parse_addr("192.168.1.100:65535")
    assert host == "192.168.1.100"
    assert port == 65535
