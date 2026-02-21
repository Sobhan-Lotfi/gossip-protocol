"""Structured JSON-lines logger for gossip nodes."""

from __future__ import annotations

import json
import os
import time
from typing import Any

# Event type constants
NODE_START = "NODE_START"
NODE_STOP = "NODE_STOP"
PEER_ADD = "PEER_ADD"
PEER_REMOVE = "PEER_REMOVE"
GOSSIP_ORIGIN = "GOSSIP_ORIGIN"
GOSSIP_RECV = "GOSSIP_RECV"
GOSSIP_DUP = "GOSSIP_DUP"
GOSSIP_FORWARD = "GOSSIP_FORWARD"
GOSSIP_TTL_EXPIRED = "GOSSIP_TTL_EXPIRED"
MSG_SENT = "MSG_SENT"
MSG_RECV = "MSG_RECV"
PING_SENT = "PING_SENT"
PONG_RECV = "PONG_RECV"
PING_TIMEOUT = "PING_TIMEOUT"
POW_COMPUTED = "POW_COMPUTED"
IHAVE_SENT = "IHAVE_SENT"
IWANT_RECV = "IWANT_RECV"
TOPOLOGY_DUMP = "TOPOLOGY_DUMP"


class StructuredLogger:
    """Writes structured JSON-line events to a per-node log file."""

    def __init__(self, node_id: str, port: int, log_dir: str) -> None:
        self._node_id = node_id
        self._port = port
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"node_{port}.jsonl")
        self._file = open(log_path, "a", buffering=1)  # line-buffered

    def log(self, event: str, **kwargs: Any) -> None:
        """Write one JSON line with ts, node_id, port, event, plus any extra fields."""
        record: dict[str, Any] = {
            "ts": time.time(),
            "node_id": self._node_id,
            "port": self._port,
            "event": event,
        }
        record.update(kwargs)
        self._file.write(json.dumps(record) + "\n")

    def close(self) -> None:
        """Flush and close the log file."""
        self._file.flush()
        self._file.close()
