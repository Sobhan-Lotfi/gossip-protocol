"""CLI entry point: parses args, runs the async gossip node event loop."""

from __future__ import annotations

import argparse
import asyncio
import random
import signal
import sys
import time
import uuid

from gossip.config import Config
from gossip.gossip_engine import GossipEngine
from gossip.logger import (
    GOSSIP_DUP,
    GOSSIP_FORWARD,
    GOSSIP_ORIGIN,
    GOSSIP_RECV,
    GOSSIP_TTL_EXPIRED,
    IHAVE_SENT,
    IWANT_RECV,
    MSG_RECV,
    MSG_SENT,
    NODE_START,
    NODE_STOP,
    PEER_ADD,
    PEER_REMOVE,
    PING_SENT,
    PING_TIMEOUT,
    PONG_RECV,
    POW_COMPUTED,
    TOPOLOGY_DUMP,
    StructuredLogger,
)
from gossip.peer_manager import PeerManager
from gossip.pow import compute_pow, verify_pow
from gossip.protocol import Message, make_message, parse_addr
from gossip.transport import UDPTransport


class Node:
    """A single gossip network peer."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._rng = random.Random(config.seed + config.port)
        self._node_id = str(uuid.UUID(bytes=self._rng.randbytes(16)))
        self._addr = f"127.0.0.1:{config.port}"
        self._transport = UDPTransport()
        self._peer_manager = PeerManager(config.peer_limit, self._rng)
        self._gossip_engine = GossipEngine()
        self._logger = StructuredLogger(self._node_id, config.port, config.log_dir)
        self._pow_nonce: int | None = None
        self._pow_digest: str | None = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None

    def _new_msg_id(self) -> str:
        """Generate a UUID using the seeded RNG."""
        return str(uuid.UUID(bytes=self._rng.randbytes(16)))

    def _send(self, message: Message, addr: tuple[str, int]) -> None:
        """Serialize and send a message, logging MSG_SENT."""
        data = message.to_bytes()
        self._transport.send(data, addr)
        self._logger.log(MSG_SENT, msg_type=message.msg_type, to_addr=f"{addr[0]}:{addr[1]}")

    def _build_message(self, msg_type: str, payload: dict, ttl: int = 0) -> Message:
        """Create a Message with this node as sender."""
        return make_message(
            msg_type=msg_type,
            sender_id=self._node_id,
            sender_addr=self._addr,
            payload=payload,
            msg_id=self._new_msg_id(),
            ttl=ttl,
        )

    def _make_pow_payload(self) -> dict:
        """Build the PoW dict for HELLO payloads, if PoW is enabled."""
        if self._config.pow_k > 0 and self._pow_nonce is not None:
            return {
                "hash_alg": "sha256",
                "difficulty_k": self._config.pow_k,
                "nonce": self._pow_nonce,
                "digest_hex": self._pow_digest,
            }
        return {}

    def _on_message(self, data: bytes, addr: tuple[str, int]) -> None:
        """Callback for every incoming UDP datagram."""
        msg = Message.from_bytes(data)
        if msg is None:
            return

        self._logger.log(MSG_RECV, msg_type=msg.msg_type, from_addr=f"{addr[0]}:{addr[1]}")

        handler = {
            "HELLO": self._handle_hello,
            "GET_PEERS": self._handle_get_peers,
            "PEERS_LIST": self._handle_peers_list,
            "GOSSIP": self._handle_gossip,
            "PING": self._handle_ping,
            "PONG": self._handle_pong,
            "IHAVE": self._handle_ihave,
            "IWANT": self._handle_iwant,
            "TRIGGER": self._handle_trigger,
        }.get(msg.msg_type)

        if handler:
            handler(msg, addr)

    def _handle_hello(self, msg: Message, addr: tuple[str, int]) -> None:
        """Handle HELLO: optionally verify PoW, add peer, send PEERS_LIST back."""
        if self._config.pow_k > 0:
            pow_info = msg.payload.get("pow", {})
            if not pow_info:
                return
            valid = verify_pow(
                msg.sender_id,
                pow_info.get("nonce", -1),
                pow_info.get("digest_hex", ""),
                self._config.pow_k,
            )
            if not valid:
                return

        added = self._peer_manager.add_peer(msg.sender_id, msg.sender_addr)
        if added:
            self._logger.log(PEER_ADD, node_id=msg.sender_id, addr=msg.sender_addr)

        peers_payload = {
            "peers": [
                {"node_id": p.node_id, "addr": p.addr}
                for p in self._peer_manager.get_all_peers()
                if p.node_id != msg.sender_id
            ]
        }
        reply = self._build_message("PEERS_LIST", peers_payload)
        self._send(reply, addr)

    def _handle_get_peers(self, msg: Message, addr: tuple[str, int]) -> None:
        """Handle GET_PEERS: reply with our current peer list."""
        peers_payload = {
            "peers": [
                {"node_id": p.node_id, "addr": p.addr}
                for p in self._peer_manager.get_all_peers()
            ]
        }
        reply = self._build_message("PEERS_LIST", peers_payload)
        self._send(reply, addr)

    def _handle_peers_list(self, msg: Message, addr: tuple[str, int]) -> None:
        """Handle PEERS_LIST: add discovered peers."""
        for peer_entry in msg.payload.get("peers", []):
            nid = peer_entry.get("node_id")
            peer_addr = peer_entry.get("addr")
            if nid and peer_addr and nid != self._node_id:
                added = self._peer_manager.add_peer(nid, peer_addr)
                if added:
                    self._logger.log(PEER_ADD, node_id=nid, addr=peer_addr)

    def _handle_gossip(self, msg: Message, addr: tuple[str, int]) -> None:
        """Handle GOSSIP: deduplicate, store, and forward."""
        if not self._gossip_engine.store(msg):
            self._logger.log(GOSSIP_DUP, msg_id=msg.msg_id, from_id=msg.sender_id)
            return

        self._logger.log(GOSSIP_RECV, msg_id=msg.msg_id, from_id=msg.sender_id)

        new_ttl = msg.ttl - 1
        if new_ttl <= 0:
            self._logger.log(GOSSIP_TTL_EXPIRED, msg_id=msg.msg_id)
            return

        exclude = {msg.sender_id, msg.payload.get("origin_id", "")}
        targets = self._peer_manager.get_random_peers(self._config.fanout, exclude)

        forwarded = Message(
            version=msg.version,
            msg_id=msg.msg_id,
            msg_type="GOSSIP",
            sender_id=self._node_id,
            sender_addr=self._addr,
            timestamp_ms=msg.timestamp_ms,
            ttl=new_ttl,
            payload=msg.payload,
        )

        for peer in targets:
            self._send(forwarded, parse_addr(peer.addr))
            self._logger.log(GOSSIP_FORWARD, msg_id=msg.msg_id, to_id=peer.node_id)

    def _handle_ping(self, msg: Message, addr: tuple[str, int]) -> None:
        """Handle PING: reply with PONG and update sender last_seen."""
        self._peer_manager.mark_seen(msg.sender_id)
        pong = self._build_message(
            "PONG",
            {"ping_id": msg.payload.get("ping_id"), "seq": msg.payload.get("seq")},
        )
        self._send(pong, addr)

    def _handle_pong(self, msg: Message, addr: tuple[str, int]) -> None:
        """Handle PONG: update sender last_seen and reset missed_pings."""
        self._peer_manager.mark_seen(msg.sender_id)
        self._logger.log(PONG_RECV, from_id=msg.sender_id)

    def _handle_ihave(self, msg: Message, addr: tuple[str, int]) -> None:
        """Handle IHAVE: reply with IWANT for any IDs we are missing."""
        ids = msg.payload.get("ids", [])
        missing = self._gossip_engine.get_missing_ids(ids)
        if missing:
            iwant = self._build_message("IWANT", {"ids": missing})
            self._send(iwant, addr)

    def _handle_iwant(self, msg: Message, addr: tuple[str, int]) -> None:
        """Handle IWANT: send back the full GOSSIP message for each requested id."""
        ids = msg.payload.get("ids", [])
        self._logger.log(IWANT_RECV, from_id=msg.sender_id, count=len(ids))
        for msg_id in ids:
            stored = self._gossip_engine.get_message(msg_id)
            if stored:
                self._send(stored, addr)

    def _handle_trigger(self, msg: Message, addr: tuple[str, int]) -> None:
        """Handle TRIGGER: create and disseminate a new GOSSIP message."""
        data = msg.payload.get("data", "")
        self._originate_gossip(data)

    def _originate_gossip(self, data: str) -> None:
        """Create a new GOSSIP message from this node and forward it."""
        msg_id = self._new_msg_id()
        payload = {
            "topic": "chat",
            "data": data,
            "origin_id": self._node_id,
            "origin_timestamp_ms": int(time.time() * 1000),
        }
        gossip = Message(
            version=1,
            msg_id=msg_id,
            msg_type="GOSSIP",
            sender_id=self._node_id,
            sender_addr=self._addr,
            timestamp_ms=int(time.time() * 1000),
            ttl=self._config.ttl,
            payload=payload,
        )
        self._gossip_engine.store(gossip)
        self._logger.log(GOSSIP_ORIGIN, msg_id=msg_id, data=data)

        targets = self._peer_manager.get_random_peers(self._config.fanout, {self._node_id})
        for peer in targets:
            self._send(gossip, parse_addr(peer.addr))
            self._logger.log(GOSSIP_FORWARD, msg_id=msg_id, to_id=peer.node_id)

    async def _ping_loop(self) -> None:
        """Periodically ping all known peers and evict unresponsive ones."""
        while self._running:
            await asyncio.sleep(self._config.ping_interval)
            now = time.time()
            for peer in self._peer_manager.get_all_peers():
                ping = self._build_message(
                    "PING",
                    {"ping_id": self._new_msg_id(), "seq": 0},
                )
                self._send(ping, parse_addr(peer.addr))
                self._logger.log(PING_SENT, to_id=peer.node_id)

                if now - peer.last_seen > self._config.peer_timeout:
                    self._peer_manager.mark_ping_failed(peer.node_id)
                    self._logger.log(
                        PING_TIMEOUT,
                        node_id=peer.node_id,
                        missed_count=peer.missed_pings,
                    )

            dead = self._peer_manager.evict_dead_peers()
            for nid in dead:
                self._logger.log(PEER_REMOVE, node_id=nid, reason="missed_pings")

    async def _pull_loop(self) -> None:
        """Periodically broadcast IHAVE to random peers (hybrid mode only)."""
        while self._running:
            await asyncio.sleep(self._config.pull_interval)
            recent_ids = self._gossip_engine.get_recent_ids(self._config.max_ihave_ids)
            if not recent_ids:
                continue
            targets = self._peer_manager.get_random_peers(self._config.fanout, set())
            for peer in targets:
                ihave = self._build_message("IHAVE", {"ids": recent_ids})
                self._send(ihave, parse_addr(peer.addr))
                self._logger.log(IHAVE_SENT, to_id=peer.node_id, count=len(recent_ids))

    async def _stdin_reader(self) -> None:
        """Read lines from stdin and originate a GOSSIP message for each."""
        if not sys.stdin.isatty():
            return
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        try:
            await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        except Exception:
            # stdin unavailable (non-interactive or sandbox environment)
            return
        while self._running:
            try:
                line = await reader.readline()
                if not line:
                    break
                text = line.decode("utf-8").rstrip("\n")
                if text:
                    self._originate_gossip(text)
            except Exception:
                break

    def _dump_topology(self) -> None:
        """Log a TOPOLOGY_DUMP event with the current peer list."""
        peer_ids = [p.node_id for p in self._peer_manager.get_all_peers()]
        self._logger.log(TOPOLOGY_DUMP, peers=peer_ids)

    def _shutdown(self) -> None:
        """Signal graceful shutdown by setting the stop event."""
        if self._stop_event and not self._stop_event.is_set():
            self._stop_event.set()

    async def _bootstrap(self) -> None:
        """Connect to the bootstrap node and discover peers."""
        if not self._config.bootstrap:
            return
        bootstrap_addr = parse_addr(self._config.bootstrap)
        bootstrap_str = self._config.bootstrap

        # Don't bootstrap to ourselves
        own_port = self._config.port
        if bootstrap_addr[1] == own_port and bootstrap_addr[0] in ("127.0.0.1", "0.0.0.0", "localhost"):
            return

        pow_payload = self._make_pow_payload()
        hello = self._build_message(
            "HELLO",
            {"capabilities": ["udp", "json"], "pow": pow_payload} if pow_payload else {"capabilities": ["udp", "json"]},
        )
        self._send(hello, bootstrap_addr)

        get_peers = self._build_message("GET_PEERS", {"max_peers": self._config.peer_limit})
        self._send(get_peers, bootstrap_addr)

        # Wait briefly for PEERS_LIST
        await asyncio.sleep(2.0)

        # Say HELLO to newly discovered peers
        for peer in self._peer_manager.get_all_peers():
            if peer.addr != bootstrap_str:
                hello2 = self._build_message(
                    "HELLO",
                    {"capabilities": ["udp", "json"], "pow": pow_payload} if pow_payload else {"capabilities": ["udp", "json"]},
                )
                self._send(hello2, parse_addr(peer.addr))

    async def run(self) -> None:
        """Main async entry point: start transport, bootstrap, then run all loops."""
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        self._running = True

        if self._config.pow_k > 0:
            t0 = time.time()
            self._pow_nonce, self._pow_digest = compute_pow(self._node_id, self._config.pow_k)
            elapsed = time.time() - t0
            self._logger.log(
                POW_COMPUTED,
                difficulty=self._config.pow_k,
                nonce=self._pow_nonce,
                time_seconds=elapsed,
            )

        await self._transport.start("0.0.0.0", self._config.port, self._on_message)

        self._logger.log(NODE_START, config={
            "port": self._config.port,
            "fanout": self._config.fanout,
            "ttl": self._config.ttl,
            "mode": self._config.mode,
            "pow_k": self._config.pow_k,
        })

        # Register signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            self._loop.add_signal_handler(sig, self._shutdown)

        await self._bootstrap()

        tasks = [
            asyncio.create_task(self._ping_loop()),
        ]
        if self._config.mode == "hybrid":
            tasks.append(asyncio.create_task(self._pull_loop()))
        tasks.append(asyncio.create_task(self._stdin_reader()))

        # Wait for stop signal
        await self._stop_event.wait()
        self._running = False

        # Cancel background tasks
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        # Cleanup
        self._dump_topology()
        self._logger.log(NODE_STOP)
        self._transport.close()
        self._logger.close()


def _parse_args() -> Config:
    """Parse CLI arguments and return a Config."""
    parser = argparse.ArgumentParser(description="Gossip protocol node")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--bootstrap", type=str, default=None)
    parser.add_argument("--fanout", type=int, default=3)
    parser.add_argument("--ttl", type=int, default=8)
    parser.add_argument("--peer-limit", type=int, default=20)
    parser.add_argument("--ping-interval", type=float, default=2.0)
    parser.add_argument("--peer-timeout", type=float, default=6.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--mode", type=str, default="push", choices=["push", "hybrid"])
    parser.add_argument("--pull-interval", type=float, default=2.0)
    parser.add_argument("--max-ihave-ids", type=int, default=32)
    parser.add_argument("--pow-k", type=int, default=0)
    parser.add_argument("--log-dir", type=str, default="logs")

    args = parser.parse_args()
    return Config(
        port=args.port,
        bootstrap=args.bootstrap,
        fanout=args.fanout,
        ttl=args.ttl,
        peer_limit=args.peer_limit,
        ping_interval=args.ping_interval,
        peer_timeout=args.peer_timeout,
        seed=args.seed,
        mode=args.mode,
        pull_interval=args.pull_interval,
        max_ihave_ids=args.max_ihave_ids,
        pow_k=args.pow_k,
        log_dir=args.log_dir,
    )


def main() -> None:
    """Entry point for python -m gossip.node."""
    config = _parse_args()
    node = Node(config)
    asyncio.run(node.run())


if __name__ == "__main__":
    main()
