"""Peer list management, PING/PONG tracking, and eviction policy."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field


@dataclass
class PeerInfo:
    """State for a single known peer."""

    node_id: str
    addr: str
    last_seen: float
    missed_pings: int = 0


class PeerManager:
    """Manages the local peer list with eviction and failure detection."""

    def __init__(self, peer_limit: int, rng: random.Random) -> None:
        self._peer_limit = peer_limit
        self._rng = rng
        self.peers: dict[str, PeerInfo] = {}

    def add_peer(self, node_id: str, addr: str) -> bool:
        """Add or refresh a peer.

        Returns False only if we're at the limit AND eviction is needed but not performed.
        Evicts the oldest peer if at limit when adding a new one.
        """
        if node_id in self.peers:
            self.peers[node_id].addr = addr
            self.peers[node_id].last_seen = time.time()
            return True

        if len(self.peers) >= self._peer_limit:
            # Evict the peer with the oldest last_seen
            oldest_id = min(self.peers, key=lambda k: self.peers[k].last_seen)
            del self.peers[oldest_id]

        self.peers[node_id] = PeerInfo(
            node_id=node_id,
            addr=addr,
            last_seen=time.time(),
        )
        return True

    def remove_peer(self, node_id: str) -> None:
        """Remove a peer by node_id."""
        self.peers.pop(node_id, None)

    def get_random_peers(self, n: int, exclude: set[str]) -> list[PeerInfo]:
        """Return up to n random peers, excluding the given node_ids."""
        candidates = [p for nid, p in self.peers.items() if nid not in exclude]
        k = min(n, len(candidates))
        return self._rng.sample(candidates, k) if k > 0 else []

    def mark_seen(self, node_id: str) -> None:
        """Update last_seen timestamp for a peer."""
        if node_id in self.peers:
            self.peers[node_id].last_seen = time.time()
            self.peers[node_id].missed_pings = 0

    def mark_ping_failed(self, node_id: str) -> None:
        """Increment missed_pings for a peer."""
        if node_id in self.peers:
            self.peers[node_id].missed_pings += 1

    def evict_dead_peers(self) -> list[str]:
        """Remove and return node_ids of peers with missed_pings >= 3."""
        dead = [nid for nid, p in self.peers.items() if p.missed_pings >= 3]
        for nid in dead:
            del self.peers[nid]
        return dead

    def get_all_peers(self) -> list[PeerInfo]:
        """Return a list of all known PeerInfo objects."""
        return list(self.peers.values())
