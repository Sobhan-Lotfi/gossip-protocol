# Protocol Design Document

## Overview

This document describes the design of the gossip-based P2P network simulator.

## Message Flow

### Bootstrap
1. New node sends `HELLO` to seed with optional PoW proof.
2. Seed replies with `PEERS_LIST`.
3. New node sends `HELLO` to each discovered peer.

### Gossip Dissemination (Push)
1. Originating node creates a `GOSSIP` message with a fresh UUID and full TTL.
2. Sends to up to `fanout` random peers (excluding self).
3. Each receiving node checks its seen-set; if new, stores and forwards.
4. TTL is decremented on each forward hop; message is dropped at TTL=0.

### Hybrid Mode (Push + Pull)
- In addition to push, each node periodically broadcasts `IHAVE [recent_ids]`.
- Recipients reply `IWANT [missing_ids]` for any IDs they lack.
- Sender replies with the full `GOSSIP` payload for each requested ID.
- This repairs messages that were lost due to UDP drops.

## Peer Management

- Peer list is bounded by `peer_limit`.
- Eviction: when full, the peer with the oldest `last_seen` is replaced.
- Dead detection: 3 consecutive missed PINGs trigger removal.
- PING/PONG cycle runs every `ping_interval` seconds.

## Proof of Work

- SHA-256(`node_id` + str(`nonce`)) must start with `difficulty_k` hex zeros.
- PoW is attached to `HELLO` messages and verified before adding a peer.
- `pow_k=0` disables PoW entirely.

## Logging

Every event is a JSON line written to `logs/node_{port}.jsonl`. Events include:
- Node lifecycle (start/stop)
- Peer changes (add/remove)
- Gossip lifecycle (origin/recv/dup/forward/ttl_expired)
- PING/PONG cycle
- Topology dumps (on shutdown)

## Reproducibility

Using `random.Random(seed + port)` per node ensures that peer selection and UUID generation produce the same sequence across runs with the same seed, enabling reproducible experiments.
