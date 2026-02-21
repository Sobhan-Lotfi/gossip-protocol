"""Message dataclasses, serialization, deserialization, and validation."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

VALID_MSG_TYPES = frozenset(
    {
        "HELLO",
        "GET_PEERS",
        "PEERS_LIST",
        "GOSSIP",
        "PING",
        "PONG",
        "IHAVE",
        "IWANT",
        "TRIGGER",
    }
)

REQUIRED_FIELDS = frozenset(
    {"version", "msg_id", "msg_type", "sender_id", "sender_addr", "timestamp_ms", "ttl", "payload"}
)


def parse_addr(addr: str) -> tuple[str, int]:
    """Parse 'ip:port' string into (ip, port) tuple."""
    host, _, port_str = addr.rpartition(":")
    return host, int(port_str)


@dataclass
class Message:
    """Envelope for every UDP datagram in the gossip network."""

    version: int
    msg_id: str
    msg_type: str
    sender_id: str
    sender_addr: str
    timestamp_ms: int
    ttl: int
    payload: dict[str, Any]

    def to_bytes(self) -> bytes:
        """Serialize message to UTF-8 encoded JSON bytes."""
        return json.dumps(asdict(self), separators=(",", ":")).encode("utf-8")

    @staticmethod
    def from_bytes(data: bytes) -> "Message | None":
        """Deserialize bytes to Message; returns None on any parse or validation error."""
        try:
            obj = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Failed to parse message: %s", exc)
            return None

        if not isinstance(obj, dict):
            logger.warning("Message is not a JSON object")
            return None

        missing = REQUIRED_FIELDS - obj.keys()
        if missing:
            logger.warning("Message missing fields: %s", missing)
            return None

        if obj["msg_type"] not in VALID_MSG_TYPES:
            logger.warning("Unknown msg_type: %s", obj["msg_type"])
            return None

        return Message(
            version=obj["version"],
            msg_id=obj["msg_id"],
            msg_type=obj["msg_type"],
            sender_id=obj["sender_id"],
            sender_addr=obj["sender_addr"],
            timestamp_ms=obj["timestamp_ms"],
            ttl=obj["ttl"],
            payload=obj["payload"],
        )


def make_message(
    msg_type: str,
    sender_id: str,
    sender_addr: str,
    payload: dict[str, Any],
    msg_id: str,
    ttl: int = 0,
) -> Message:
    """Construct a Message with current timestamp."""
    return Message(
        version=1,
        msg_id=msg_id,
        msg_type=msg_type,
        sender_id=sender_id,
        sender_addr=sender_addr,
        timestamp_ms=int(time.time() * 1000),
        ttl=ttl,
        payload=payload,
    )
