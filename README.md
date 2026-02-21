# Gossip Protocol

A fully functional gossip-based P2P network simulator. Multiple node instances run on localhost (different ports) to form a network that discovers peers and spreads information using gossip dissemination.

---

## Architecture

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                        Bootstrap Flow                           │
  │                                                                 │
  │  Node A (seed)               Node B                Node C      │
  │     │                          │                     │         │
  │     │ <── HELLO ───────────────┤                     │         │
  │     │ ──► PEERS_LIST ──────────>                     │         │
  │     │ <── GET_PEERS ───────────┤                     │         │
  │     │ ──► PEERS_LIST ──────────>                     │         │
  │     │                          │ <── HELLO ──────────┤         │
  │     │                          │ ──► PEERS_LIST ─────>         │
  └─────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────┐
  │                         Gossip Flow (push)                      │
  │                                                                 │
  │   origin                fanout=3                               │
  │  Node A ──► GOSSIP ──► Node B ──► Node D                       │
  │             (ttl=8)    (ttl=7)    (ttl=6) ...                  │
  │                    └──► Node C                                  │
  │                    └──► Node E   (duplicates dropped)           │
  └─────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────┐
  │                 Hybrid Mode (push + pull)                       │
  │                                                                 │
  │  Every pull_interval:                                           │
  │  Node A ──► IHAVE [id1, id2] ──► Node B                        │
  │  Node A <── IWANT [id2]       <── Node B                        │
  │  Node A ──► GOSSIP(id2)       ──► Node B                        │
  └─────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Single node (seed/bootstrap)

```bash
python -m gossip.node --port 9000
```

### Join the network

```bash
python -m gossip.node --port 9001 --bootstrap 127.0.0.1:9000
python -m gossip.node --port 9002 --bootstrap 127.0.0.1:9000
```

Once running, type a message and press Enter — it propagates across the network.

### 10-node demo

```bash
# Terminal 1 (seed)
python -m gossip.node --port 9000 --fanout 3 --ttl 8 --seed 42

# Terminals 2-10
for port in $(seq 9001 9009); do
  python -m gossip.node --port $port --bootstrap 127.0.0.1:9000 --fanout 3 --ttl 8 --seed 42 &
done
```

---

## Configuration

| Parameter        | CLI flag            | Default | Description                                      |
|------------------|---------------------|---------|--------------------------------------------------|
| `port`           | `--port`            | —       | UDP port to bind (required)                      |
| `bootstrap`      | `--bootstrap`       | None    | `ip:port` of seed node; omit to be seed          |
| `fanout`         | `--fanout`          | 3       | Peers to forward each gossip message to          |
| `ttl`            | `--ttl`             | 8       | Max hop count before message is dropped          |
| `peer_limit`     | `--peer-limit`      | 20      | Maximum number of peers in the peer list         |
| `ping_interval`  | `--ping-interval`   | 2.0     | Seconds between PING rounds                      |
| `peer_timeout`   | `--peer-timeout`    | 6.0     | Seconds of silence before marking peer suspect   |
| `seed`           | `--seed`            | 42      | RNG seed for reproducible peer selection         |
| `mode`           | `--mode`            | push    | `push` or `hybrid` (push + pull via IHAVE/IWANT) |
| `pull_interval`  | `--pull-interval`   | 2.0     | Seconds between IHAVE rounds (hybrid only)       |
| `max_ihave_ids`  | `--max-ihave-ids`   | 32      | Max message IDs sent per IHAVE                   |
| `pow_k`          | `--pow-k`           | 0       | PoW difficulty (leading zero nibbles); 0=disabled|
| `log_dir`        | `--log-dir`         | logs    | Directory for `.jsonl` log files                 |

---

## Simulation

Run automated experiments across multiple seeds:

```bash
python scripts/simulate.py \
  --n 10 --fanout 3 --ttl 8 --mode push \
  --seeds 42,43,44,45,46 \
  --stabilize-time 5 --gossip-wait 10 \
  --log-dir logs --results-dir results
```

---

## Analysis

Generate plots from experiment results:

```bash
python scripts/analyze.py \
  --results-dir results/ \
  --output-dir results/plots/
```

Produces:
- `convergence_vs_n.png` — convergence time vs. number of nodes
- `overhead_vs_n.png` — message overhead vs. number of nodes
- `convergence_vs_fanout.png` — convergence time vs. fanout (N=50)
- `overhead_vs_fanout.png` — message overhead vs. fanout (N=50)
- `push_vs_hybrid.png` — grouped bar comparison

---

## Topology Visualization

```bash
python scripts/topology.py \
  --log-dir results/push_n10_f3_t8_s42/ \
  --output results/plots/topology_n10.png
```

Prints statistics (node count, edge count, diameter, clustering coefficient) and saves a spring-layout graph image.

---

## Tests

```bash
python -m pytest tests/
```

Covers: message serialization, PoW compute/verify, gossip engine deduplication.

---

## Project Structure

```
src/gossip/
  config.py         Frozen dataclass of all node parameters
  protocol.py       Message dataclass, serialize/deserialize, validation
  transport.py      AsyncIO UDP send/receive layer
  logger.py         Structured JSON-lines logger (per-node .jsonl files)
  pow.py            SHA-256 Proof of Work compute, verify, benchmark
  peer_manager.py   Peer list with eviction and dead-peer detection
  gossip_engine.py  Message store, deduplication, IHAVE/IWANT support
  node.py           CLI entry point, async main loop, message handler

scripts/
  simulate.py       Orchestrate N-node experiments, inject gossip, collect logs
  analyze.py        Parse logs, compute metrics, generate matplotlib plots
  topology.py       Build directed graph from TOPOLOGY_DUMP events, visualize

tests/
  test_protocol.py      Serialization round-trips, error handling
  test_pow.py           PoW correctness and rejection cases
  test_gossip_engine.py Deduplication, store/retrieve, IHAVE diff
```

---

## Design Decisions

- **UDP + JSON:** Simple, connectionless transport. JSON is human-readable and easy to debug. Each datagram is a complete message.
- **Seeded RNG per node:** All random choices (peer selection, UUIDs) use a single `random.Random` instance seeded by `seed + port`, ensuring reproducible simulations.
- **Push vs. Hybrid:** Push mode floods gossip eagerly (low latency, higher overhead). Hybrid mode adds a periodic IHAVE/IWANT pull cycle that repairs missed messages (better reliability at the cost of extra round-trips).
- **TTL-based forwarding:** Each hop decrements TTL; when TTL reaches 0 the message is not forwarded. This bounds message lifetime.
- **Dead peer eviction:** Three consecutive missed PINGs (tracked via `missed_pings`) removes a peer. Prevents routing messages to dead nodes.
- **Oldest-first eviction:** When the peer list is full, the peer with the oldest `last_seen` timestamp is replaced, keeping the peer list fresh.
- **No global state:** All mutable state lives inside the `Node` instance, making the code testable and free of import-time side effects.
- **Structured logging:** Every significant event is a JSON line, enabling offline analysis, metric extraction, and topology reconstruction without any special tooling.
- **PoW (optional):** SHA-256 leading-zero challenge prevents trivial Sybil attacks by making joining computationally non-free.
