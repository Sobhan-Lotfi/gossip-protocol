"""Configuration dataclass for a gossip node."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """All runtime parameters for a gossip node."""

    port: int
    bootstrap: str | None
    fanout: int
    ttl: int
    peer_limit: int
    ping_interval: float
    peer_timeout: float
    seed: int
    mode: str
    pull_interval: float
    max_ihave_ids: int
    pow_k: int
    log_dir: str
