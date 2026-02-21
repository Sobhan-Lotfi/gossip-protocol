"""AsyncIO UDP transport layer (send/receive)."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

logger = logging.getLogger(__name__)

MAX_DATAGRAM_SIZE = 65507  # maximum UDP payload size


class _GossipProtocol(asyncio.DatagramProtocol):
    """Internal asyncio DatagramProtocol that delegates to UDPTransport."""

    def __init__(self, on_message: Callable[[bytes, tuple[str, int]], None]) -> None:
        self._on_message = on_message
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore[override]
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._on_message(data, addr)

    def error_received(self, exc: Exception) -> None:
        logger.warning("UDP error received: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        if exc:
            logger.warning("UDP connection lost: %s", exc)


class UDPTransport:
    """Async UDP transport that binds a port and dispatches incoming datagrams."""

    def __init__(self) -> None:
        self._protocol: _GossipProtocol | None = None

    async def start(self, host: str, port: int, on_message: Callable[[bytes, tuple[str, int]], None]) -> None:
        """Bind to (host, port) and begin receiving datagrams, calling on_message for each."""
        loop = asyncio.get_running_loop()
        self._protocol = _GossipProtocol(on_message)
        await loop.create_datagram_endpoint(
            lambda: self._protocol,  # type: ignore[return-value]
            local_addr=("0.0.0.0", port),
        )
        logger.info("UDP transport listening on %s:%d", host, port)

    def send(self, data: bytes, addr: tuple[str, int]) -> None:
        """Fire-and-forget UDP send."""
        if self._protocol is None or self._protocol.transport is None:
            logger.warning("Transport not started; dropping send to %s", addr)
            return
        if len(data) > MAX_DATAGRAM_SIZE:
            logger.error("Datagram too large (%d bytes); skipping send to %s", len(data), addr)
            return
        self._protocol.transport.sendto(data, addr)

    def close(self) -> None:
        """Close the underlying UDP socket."""
        if self._protocol and self._protocol.transport:
            self._protocol.transport.close()
