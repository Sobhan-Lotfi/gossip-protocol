# Gossip Protocol — Implementation Specification

## Overview

A fully functional gossip-based P2P network simulator. A single `node` program acts as one peer in the network. Multiple instances run on localhost (different ports) to form a network that discovers peers and spreads information using gossip.

**Language:** Python 3.10+ with asyncio
**Transport:** UDP with JSON messages
**No external gossip libraries.** Only stdlib + matplotlib + networkx.

---

## Repository Structure

```
gossip-protocol/
├── README.md
├── pyproject.toml              # project metadata, dependencies: matplotlib, networkx
├── src/
│   └── gossip/
│       ├── __init__.py
│       ├── node.py             # CLI entry point (argparse + main async loop)
│       ├── protocol.py         # Message dataclasses, serialize/deserialize, validation
│       ├── peer_manager.py     # Peer list, PING/PONG cycle, eviction policy
│       ├── gossip_engine.py    # Seen set, message store, forwarding, IHAVE/IWANT
│       ├── pow.py              # Proof of Work compute + verify
│       ├── transport.py        # AsyncIO UDP transport layer (send/receive)
│       ├── config.py           # Config dataclass from CLI args
│       └── logger.py           # Structured JSON-lines logger
├── scripts/
│   ├── simulate.py             # Launch N nodes, inject gossip, collect logs
│   ├── analyze.py              # Parse logs → metrics → plots
│   └── topology.py             # Build + visualize network graph from peer lists
├── tests/
│   ├── test_protocol.py        # Message serialization round-trips
│   ├── test_pow.py             # PoW compute + verify
│   └── test_gossip_engine.py   # Seen set dedup, forwarding logic
├── logs/                       # Runtime logs (gitignored)
├── results/                    # Generated plots (gitignored)
└── docs/
    └── design.md               # Protocol design document
```

---

## Config (src/gossip/config.py)

A frozen dataclass holding all parameters:

```python
@dataclass(frozen=True)
class Config:
    port: int
    bootstrap: str | None        # "ip:port" or None if this IS the seed node
    fanout: int                  # peers to forward gossip to (default 3)
    ttl: int                     # max hops (default 8)
    peer_limit: int              # max peer list size (default 20)
    ping_interval: float         # seconds between PING rounds (default 2.0)
    peer_timeout: float          # seconds before peer is suspect (default 6.0)
    seed: int                    # RNG seed for reproducibility (default 42)
    mode: str                    # "push" or "hybrid" (default "push")
    pull_interval: float         # seconds between IHAVE rounds (default 2.0)
    max_ihave_ids: int           # max msg_ids per IHAVE (default 32)
    pow_k: int                   # PoW difficulty, 0 = disabled (default 0)
    log_dir: str                 # directory for log files (default "logs")
```

CLI usage:
```
python -m gossip.node --port 8000 --bootstrap 127.0.0.1:9000 \
    --fanout 3 --ttl 8 --peer-limit 20 \
    --ping-interval 2 --peer-timeout 6 \
    --seed 42 --mode push --pow-k 0
```

If `--bootstrap` is omitted or equals own address, the node acts as the seed/bootstrap node.

---

## Protocol Messages (src/gossip/protocol.py)

Every UDP datagram is a JSON object with this envelope:

```python
@dataclass
class Message:
    version: int           # always 1
    msg_id: str            # UUID for this message instance
    msg_type: str          # HELLO | GET_PEERS | PEERS_LIST | GOSSIP | PING | PONG | IHAVE | IWANT
    sender_id: str         # node UUID of sender
    sender_addr: str       # "ip:port" of sender
    timestamp_ms: int      # unix epoch milliseconds
    ttl: int               # decremented on forward
    payload: dict          # type-specific data
```

### Message Types and Payloads

**HELLO** — join request
```json
{"capabilities": ["udp", "json"], "pow": {"hash_alg": "sha256", "difficulty_k": 4, "nonce": 9138472, "digest_hex": "0000ab12..."}}
```
`pow` field present only when pow_k > 0.

**GET_PEERS** — request peer list
```json
{"max_peers": 20}
```

**PEERS_LIST** — response with known peers
```json
{"peers": [{"node_id": "...", "addr": "127.0.0.1:8001"}, ...]}
```

**GOSSIP** — information to spread
```json
{"topic": "chat", "data": "Hello network!", "origin_id": "node-uuid", "origin_timestamp_ms": 1730000000000}
```

**PING**
```json
{"ping_id": "uuid", "seq": 17}
```

**PONG**
```json
{"ping_id": "uuid", "seq": 17}
```

**IHAVE** (hybrid mode only)
```json
{"ids": ["msg-id-1", "msg-id-2", ...]}
```

**IWANT** (hybrid mode only)
```json
{"ids": ["msg-id-2"]}
```

### Serialization

- `Message.to_bytes()` → JSON string → UTF-8 bytes
- `Message.from_bytes(data)` → parse JSON → validate required fields → return Message
- Invalid JSON or missing fields → log warning, drop silently (never crash)

---

## Transport Layer (src/gossip/transport.py)

Use `asyncio.DatagramProtocol`:

```python
class UDPTransport:
    async def start(self, host: str, port: int, on_message: Callable)
    def send(self, data: bytes, addr: tuple[str, int])
    def close()
```

- `on_message(data: bytes, addr: tuple[str, int])` is called for every incoming datagram
- `send()` is fire-and-forget (UDP)
- Bind to `("0.0.0.0", port)` so it works on localhost

---

## Peer Manager (src/gossip/peer_manager.py)

```python
@dataclass
class PeerInfo:
    node_id: str
    addr: str                  # "ip:port"
    last_seen: float           # time.time()
    missed_pings: int = 0

class PeerManager:
    peers: dict[str, PeerInfo]   # node_id → PeerInfo
    
    def add_peer(self, node_id, addr) → bool     # returns False if at limit, evicts oldest if needed
    def remove_peer(self, node_id)
    def get_random_peers(self, n, exclude) → list  # uses seeded RNG, exclude is set of node_ids
    def mark_seen(self, node_id)                    # update last_seen
    def mark_ping_failed(self, node_id)             # increment missed_pings
    def evict_dead_peers(self)                       # remove peers with missed_pings >= 3
    def get_all_peers(self) → list[PeerInfo]
```

**Eviction policy:** When peer list is full and a new peer arrives, remove the peer with the oldest `last_seen` timestamp.

**Dead peer detection:** After 3 consecutive missed PINGs (i.e., `missed_pings >= 3`), remove the peer.

---

## Gossip Engine (src/gossip/gossip_engine.py)

```python
@dataclass
class StoredMessage:
    message: Message           # full GOSSIP message
    received_at: float         # time.time() when first seen

class GossipEngine:
    message_store: dict[str, StoredMessage]   # msg_id → StoredMessage
    
    def has_seen(self, msg_id) → bool
    def store(self, message) → bool              # returns False if already seen
    def get_message(self, msg_id) → Message | None
    def get_recent_ids(self, max_count) → list[str]   # for IHAVE, most recent first
    def get_missing_ids(self, ids: list[str]) → list[str]  # for IWANT: return ids not in store
```

---

## Proof of Work (src/gossip/pow.py)

```python
def compute_pow(node_id: str, difficulty_k: int) → tuple[int, str]:
    """Find nonce where SHA256(node_id + str(nonce)) hex starts with k zeros."""
    
def verify_pow(node_id: str, nonce: int, digest_hex: str, difficulty_k: int) → bool:
    """Verify the PoW proof."""

def benchmark_pow(difficulty_k: int, trials: int = 10) → dict:
    """Return mean, std, min, max times for given difficulty."""
```

Hash input: `f"{node_id}{nonce}".encode("utf-8")` → SHA-256 → check hex digest starts with `"0" * difficulty_k`.

---

## Structured Logger (src/gossip/logger.py)

Each node writes to `{log_dir}/node_{port}.jsonl`. Every line is a JSON object:

```python
class StructuredLogger:
    def __init__(self, node_id: str, port: int, log_dir: str)
    
    def log(self, event: str, **kwargs):
        """Write one JSON line with ts, node_id, port, event, plus any kwargs."""
```

### Event Types (string constants)

```
NODE_START           — node started, log config
NODE_STOP            — node shutting down
PEER_ADD             — new peer added (node_id, addr)
PEER_REMOVE          — peer removed (node_id, reason)
GOSSIP_ORIGIN        — this node created a new gossip (msg_id, data)
GOSSIP_RECV          — received new gossip first time (msg_id, from_id)
GOSSIP_DUP           — received duplicate gossip, dropped (msg_id, from_id)
GOSSIP_FORWARD       — forwarded gossip to peer (msg_id, to_id)
GOSSIP_TTL_EXPIRED   — gossip not forwarded, TTL=0 (msg_id)
MSG_SENT             — any message sent (msg_type, to_addr)
MSG_RECV             — any message received (msg_type, from_addr)
PING_SENT            — ping sent (to_id)
PONG_RECV            — pong received (from_id)
PING_TIMEOUT         — peer missed ping (node_id, missed_count)
POW_COMPUTED         — PoW finished (difficulty, nonce, time_seconds)
IHAVE_SENT           — IHAVE sent (to_id, count)
IWANT_RECV           — IWANT received (from_id, count)
TOPOLOGY_DUMP        — peer list snapshot (peers: list of node_ids)
```

Every event includes: `{"ts": <float epoch>, "node_id": "<uuid>", "port": <int>, "event": "<EVENT_TYPE>", ...}`

---

## Node Main Loop (src/gossip/node.py)

The main entry point. Parses CLI args into Config, then runs the async event loop.

### Startup Sequence

1. Generate `node_id` (UUID4, seeded from `config.seed + config.port` for reproducibility)
2. If `pow_k > 0`: compute PoW (log time taken)
3. Start UDP transport on `config.port`
4. Start structured logger
5. If bootstrap address is set and differs from self:
   a. Send HELLO to bootstrap (include PoW if enabled)
   b. Send GET_PEERS to bootstrap
   c. Wait up to 2 seconds for PEERS_LIST response
   d. Add received peers to peer list
   e. Send HELLO to each discovered peer (with PoW if enabled)
6. Start background tasks:
   a. `ping_loop()` — every `ping_interval` seconds
   b. `pull_loop()` — every `pull_interval` seconds (hybrid mode only)
   c. `stdin_reader()` — read user input, create GOSSIP messages
   d. `peer_cleanup_loop()` — every `ping_interval` seconds, evict dead peers

### Message Handler (on_message callback)

```
Parse message from bytes (drop if invalid)
Log MSG_RECV

Switch on msg_type:

HELLO:
    If pow_k > 0: verify PoW, reject if invalid
    Add sender to peer list
    Reply with PEERS_LIST containing our known peers

GET_PEERS:
    Reply with PEERS_LIST

PEERS_LIST:
    Add each peer to our peer list (up to peer_limit)

GOSSIP:
    If msg_id in seen set → log GOSSIP_DUP, return
    Store in message store, log GOSSIP_RECV
    Decrement TTL
    If TTL > 0:
        Select min(fanout, available) random peers, excluding sender_id and origin_id
        Forward to each, log GOSSIP_FORWARD for each
    Else:
        Log GOSSIP_TTL_EXPIRED

PING:
    Reply with PONG (same ping_id, seq)
    Update sender last_seen

PONG:
    Update sender last_seen, reset missed_pings

IHAVE:
    Compute missing = ids not in our seen set
    If missing: reply with IWANT containing missing ids

IWANT:
    For each requested id: look up in message store, send full GOSSIP message
```

### User Input (stdin_reader)

Read lines from stdin. Each line becomes a new GOSSIP message:
- Generate new msg_id (UUID)
- Set origin_id = self node_id, origin_timestamp_ms = now
- Set TTL = config.ttl
- topic = "chat", data = the user's input line
- Store in own message store + seen set
- Log GOSSIP_ORIGIN
- Forward to `fanout` random peers

### Periodic Tasks

**ping_loop:** Every `ping_interval` seconds:
- For each peer: send PING
- For each peer where `time.time() - last_seen > peer_timeout`: increment missed_pings, log PING_TIMEOUT
- Evict peers with missed_pings >= 3

**pull_loop (hybrid only):** Every `pull_interval` seconds:
- Get up to `max_ihave_ids` recent message IDs from gossip engine
- Select up to `fanout` random peers
- Send IHAVE to each

---

## Simulation Script (scripts/simulate.py)

Orchestrates full experiments. CLI:

```
python scripts/simulate.py --n 10 --fanout 3 --ttl 8 --mode push \
    --seeds 42,43,44,45,46 --peer-limit 20 --ping-interval 2 --peer-timeout 6 \
    --pow-k 0 --stabilize-time 5 --gossip-wait 10 --log-dir logs
```

### Behavior

1. Create `log_dir` (clear if exists)
2. For each seed in seeds:
   a. Launch node 0 (port 9000) as bootstrap: `python -m gossip.node --port 9000 --fanout {fanout} --ttl {ttl} --seed {seed} --mode {mode} --pow-k {pow_k} --log-dir {log_dir}/{seed}/`
   b. Launch nodes 1..N-1 (ports 9001..9000+N-1) with `--bootstrap 127.0.0.1:9000`
   c. Wait `stabilize_time` seconds for peer discovery
   d. Send a trigger gossip via UDP to node 0: a special JSON message that node 0 treats as user input (inject a GOSSIP message with data="EXPERIMENT_PAYLOAD_{seed}")
   e. Wait `gossip_wait` seconds for propagation
   f. Send SIGTERM to all nodes (they should handle it gracefully and dump topology)
   g. Move logs to `results/{mode}_n{n}_f{fanout}_t{ttl}_s{seed}/`

For injecting the gossip programmatically (since we can't type into stdin of a subprocess easily), add a special mechanism: node accepts a `TRIGGER` message type via UDP that creates a gossip as if the user typed it. This keeps the simulation fully automated.

Add to protocol.py:
```json
{"msg_type": "TRIGGER", "payload": {"data": "EXPERIMENT_PAYLOAD_42"}}
```

When node receives TRIGGER: create and disseminate a GOSSIP message with that data. TRIGGER is only used by the simulation script.

### Topology Dump

On graceful shutdown (SIGTERM handler), each node logs a TOPOLOGY_DUMP event containing its current peer list. This is used by topology.py.

---

## Analysis Script (scripts/analyze.py)

CLI:
```
python scripts/analyze.py --results-dir results/ --output-dir results/plots/
```

### Parsing

Read all `.jsonl` files in each experiment directory. Build a timeline of events.

### Metrics

**Convergence Time:** For each GOSSIP message (identified by msg_id):
- t0 = the GOSSIP_ORIGIN timestamp
- For each node, find GOSSIP_RECV timestamp for that msg_id
- Sort receive times, find when ceil(0.95 * N) nodes have received it
- Convergence time = that timestamp - t0

**Message Overhead:** Count all MSG_SENT events from t0 until the 95% convergence time.

### Plots (matplotlib)

1. **Convergence Time vs N** — one line per mode (push vs hybrid), error bars (mean ± std across seeds)
2. **Message Overhead vs N** — same format
3. **Convergence Time vs Fanout** — fix N=50, vary fanout
4. **Message Overhead vs Fanout** — same
5. **Push vs Hybrid comparison** — grouped bar chart for each N

All plots saved as PNG to `output_dir`.

---

## Topology Script (scripts/topology.py)

CLI:
```
python scripts/topology.py --log-dir results/push_n50_f3_t8_s42/ --output results/plots/topology_n50.png
```

### Behavior

1. Read TOPOLOGY_DUMP events from all node logs
2. Build a directed graph with networkx (edge from A→B means A has B in its peer list)
3. Compute and print: number of nodes, number of edges, average in-degree, average out-degree, diameter (of undirected version), clustering coefficient
4. Save a visualization (spring layout) as PNG

---

## Tests (tests/)

Use plain `assert` statements (no pytest dependency needed, but pytest-compatible).

**test_protocol.py:**
- Round-trip serialize/deserialize for each message type
- Invalid JSON handling (should return None, not crash)
- Missing fields handling

**test_pow.py:**
- compute_pow returns valid nonce for k=1,2,3
- verify_pow accepts valid proof
- verify_pow rejects tampered nonce, wrong digest, insufficient zeros

**test_gossip_engine.py:**
- store() returns True first time, False on duplicate
- has_seen() works correctly
- get_missing_ids() returns correct diff

Run with: `python -m pytest tests/`

---

## README.md

Write a clean README with:
- Project title and one-line description
- Architecture diagram (ASCII art showing nodes, bootstrap flow, gossip flow)
- Quick start: how to run a single node, how to run the 10-node demo
- Configuration: table of all CLI parameters with defaults and descriptions
- Simulation: how to run experiments
- Analysis: how to generate plots
- Project structure: brief description of each file
- Design decisions: bullet points of key choices and rationale

---

## Important Implementation Notes

1. **Seeded RNG:** Create `random.Random(seed)` instance per node. Use ONLY this instance for all random choices (peer selection, UUID generation). Never use `random.random()` module-level functions. For UUID generation, use the seeded RNG to generate bytes: `uuid.UUID(bytes=rng.randbytes(16))`.

2. **Graceful shutdown:** Handle SIGTERM and SIGINT. On shutdown: log TOPOLOGY_DUMP, close UDP socket, flush logs.

3. **No global state.** Each node's state is encapsulated in a `Node` class instance. This makes the code testable and clean.

4. **Time source:** Use `time.time()` everywhere for timestamps. For `timestamp_ms` in messages, use `int(time.time() * 1000)`.

5. **Address format:** Always store addresses as strings `"ip:port"`. Parse with a helper: `parse_addr("127.0.0.1:8000") → ("127.0.0.1", 8000)`.

6. **Max UDP datagram size:** JSON messages should comfortably fit in a single UDP datagram. Set a reasonable max (65507 bytes, the UDP max). If a message exceeds this (shouldn't happen), log error and skip.

7. **Don't over-engineer.** Keep it simple. No dependency injection frameworks, no abstract base classes, no metaclasses. Just clean Python with type hints and dataclasses.

8. **Code style:** Use type hints everywhere. Docstrings on every public class and method (short, one-line). No comments that just restate the code. Variable names should be descriptive.
