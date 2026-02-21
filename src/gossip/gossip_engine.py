"""Gossip message store: deduplication, forwarding decisions, IHAVE/IWANT support."""

from __future__ import annotations

import time
from dataclasses import dataclass

from gossip.protocol import Message


@dataclass
class StoredMessage:
    """A GOSSIP message plus the local time it was first received."""

    message: Message
    received_at: float


class GossipEngine:
    """Tracks seen message IDs and stores full GOSSIP messages for retrieval."""

    def __init__(self) -> None:
        self.message_store: dict[str, StoredMessage] = {}

    def has_seen(self, msg_id: str) -> bool:
        """Return True if this msg_id has already been stored."""
        return msg_id in self.message_store

    def store(self, message: Message) -> bool:
        """Store message; returns False if already seen, True if newly stored."""
        if message.msg_id in self.message_store:
            return False
        self.message_store[message.msg_id] = StoredMessage(
            message=message,
            received_at=time.time(),
        )
        return True

    def get_message(self, msg_id: str) -> Message | None:
        """Return the stored Message for msg_id, or None if not found."""
        entry = self.message_store.get(msg_id)
        return entry.message if entry else None

    def get_recent_ids(self, max_count: int) -> list[str]:
        """Return up to max_count msg_ids ordered most-recent first (by received_at)."""
        sorted_items = sorted(
            self.message_store.items(),
            key=lambda kv: kv[1].received_at,
            reverse=True,
        )
        return [msg_id for msg_id, _ in sorted_items[:max_count]]

    def get_missing_ids(self, ids: list[str]) -> list[str]:
        """Return IDs from the given list that are not in the local store."""
        return [msg_id for msg_id in ids if msg_id not in self.message_store]
