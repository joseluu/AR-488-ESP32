"""Async WebSocket transport to the AR-488-ESP32 gateway for tektool.

Wraps the new firmware actions:
  - write_bytes  : send raw bytes (with EOI on last byte)
  - query_bytes  : write_bytes + binary read (atomic on the bus mutex)
  - device_clear : addressed SDC

A single asyncio.Lock serialises every memory_read/memory_write so that
concurrent callers can't interleave half-packets — the scope's binary
protocol has no framing recovery.

Logger:    logging.getLogger("tektool.transport") — DEBUG dumps every
           outbound packet (cmd/addr/len/csum) and inbound length.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any

import websockets

from . import protocol

log = logging.getLogger("tektool.transport")


class TektoolError(RuntimeError):
    """Raised on any gateway / GPIB / scope-level transport failure."""


class TektoolSession:
    """One persistent WebSocket connection plus a serialising lock.

    Lifecycle:
        s = TektoolSession("192.168.1.42")
        await s.open()
        ver = await s.gateway_version()
        idn = await s.scope_idn()
        body = await s.memory_read(0x1000000, 0x10)
        await s.memory_write(0x1000000, b"\\x90\\x90\\x90\\x90")
        await s.close()
    """

    def __init__(
        self,
        host: str,
        addr: int = 29,
        default_timeout_ms: int = 10_000,
        path: str = "/ws",
    ):
        self.host = host
        self.addr = addr
        self.default_timeout_ms = default_timeout_ms
        self._uri = f"ws://{host}{path}"
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle.

    async def open(self) -> None:
        if self._ws is not None:
            return
        log.info("connecting to %s", self._uri)
        # ping_interval=None disables client-initiated pings. The gateway
        # is single-threaded and will sometimes block its WS task for a
        # few seconds while servicing a long GPIB transaction (e.g. a
        # 1024-byte memory_read). The default 20 s ping_timeout would
        # then drop the connection mid-backup. We rely on application
        # request/response traffic to detect a dead link.
        self._ws = await websockets.connect(
            self._uri, max_size=None, ping_interval=None,
        )
        # Settle the bus into a known state for the service-mode session.
        # IFC first to recover from any hung talker left over from a
        # previous failed transaction, then SDC to clear the scope.
        try:
            await self.interface_clear()
        except TektoolError as exc:
            log.warning("interface_clear at session open failed: %s", exc)
        await self.device_clear()

    async def close(self) -> None:
        if self._ws is not None:
            ws, self._ws = self._ws, None
            try:
                await ws.close()
            except Exception:  # pragma: no cover - best-effort
                pass

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    # ------------------------------------------------------------------
    # Low-level request/response.

    def _make_request(
        self,
        action: str,
        command: str = "",
        timeout_ms: int | None = None,
        payload: bytes | None = None,
        addr: int | None = None,
        expect_bytes: int | None = None,
    ) -> dict[str, Any]:
        rid = f"tt-{int(time.time() * 1000)}"
        req: dict[str, Any] = {
            "request_id": rid,
            "action": action,
            "command": command,
            "addr": addr if addr is not None else self.addr,
            "timeout_ms": timeout_ms if timeout_ms is not None else self.default_timeout_ms,
        }
        if payload is not None:
            req["payload_b64"] = base64.b64encode(payload).decode("ascii")
        if expect_bytes is not None:
            req["expect_bytes"] = int(expect_bytes)
        return req

    async def _send_and_recv(
        self,
        req: dict[str, Any],
        timeout_ms: int,
    ) -> tuple[dict[str, Any], bytes | None]:
        """Issue one request. Returns (final-meta, body-bytes-or-None)."""
        if self._ws is None:
            raise TektoolError("session not open — call open() first")

        log.debug(
            "-> action=%s addr=%s timeout_ms=%s payload_len=%s",
            req["action"], req.get("addr"), req["timeout_ms"],
            len(base64.b64decode(req["payload_b64"])) if "payload_b64" in req else 0,
        )
        await self._ws.send(json.dumps(req))

        # First reply is always JSON.
        text = await asyncio.wait_for(
            self._ws.recv(), timeout=timeout_ms / 1000 + 3,
        )
        meta = json.loads(text)
        log.debug("<- %s", meta)

        if meta.get("stream") == "begin":
            chunks: list[bytes] = []
            per_frame_to = max(timeout_ms / 1000 + 30, 60)
            while True:
                frame = await asyncio.wait_for(self._ws.recv(), timeout=per_frame_to)
                if isinstance(frame, (bytes, bytearray)):
                    chunks.append(bytes(frame))
                else:
                    end = json.loads(frame)
                    log.debug("<- end %s", end)
                    body = b"".join(chunks) if end.get("ok") else None
                    return end, body
        return meta, None

    async def _request_locked(
        self,
        action: str,
        *,
        command: str = "",
        timeout_ms: int | None = None,
        payload: bytes | None = None,
        addr: int | None = None,
        expect_bytes: int | None = None,
    ) -> tuple[dict[str, Any], bytes | None]:
        async with self._lock:
            tm = timeout_ms if timeout_ms is not None else self.default_timeout_ms
            req = self._make_request(
                action, command=command, timeout_ms=tm,
                payload=payload, addr=addr, expect_bytes=expect_bytes,
            )
            return await self._send_and_recv(req, tm)

    # ------------------------------------------------------------------
    # Gateway / scope state queries (re-used by safety pre-flight).

    async def gateway_version(self) -> str:
        meta, _ = await self._request_locked("version", addr=0)
        if not meta.get("ok"):
            raise TektoolError(f"version query failed: {meta.get('error')}")
        return str(meta.get("version", ""))

    async def scope_query(self, command: str, timeout_ms: int | None = None) -> str:
        """Issue a normal SCPI text query — used for `*IDN?` pre-flight only."""
        meta, _ = await self._request_locked(
            "query", command=command, timeout_ms=timeout_ms,
        )
        if not meta.get("ok"):
            raise TektoolError(f"query {command!r} failed: {meta.get('error')}")
        return str(meta.get("data", ""))

    async def device_clear(self, timeout_ms: int | None = None) -> None:
        meta, _ = await self._request_locked("device_clear", timeout_ms=timeout_ms)
        if not meta.get("ok"):
            raise TektoolError(f"device_clear failed: {meta.get('error')}")

    async def interface_clear(self, timeout_ms: int | None = None) -> None:
        """Pulse IFC and reassert REN. Recovers a hung GPIB bus."""
        meta, _ = await self._request_locked(
            "interface_clear", addr=0, timeout_ms=timeout_ms,
        )
        if not meta.get("ok"):
            raise TektoolError(f"interface_clear failed: {meta.get('error')}")

    # ------------------------------------------------------------------
    # Tektool memory primitives.

    async def memory_read(
        self,
        addr: int,
        length: int,
        *,
        timeout_ms: int | None = None,
    ) -> bytes:
        """Read `length` bytes from scope memory at `addr`.

        Wire transaction:
          host -> scope :  m-packet (cmd_hdr + addr + len)
          scope -> host :  '+' '=' csum len_be16 body[len]   (one GPIB msg)
          host -> scope :  '+'   (final ack)
        """
        if length <= 0:
            raise ValueError("length must be positive")
        pkt = protocol.pack_memory_read(addr, length)
        log.debug("memory_read addr=%#x len=%d csum=%#x", addr, length, pkt[1])
        # Reply is '+' (1) + cmd_hdr (4) + body (length) bytes, no EOI.
        meta, raw = await self._request_locked(
            "query_bytes", payload=pkt, timeout_ms=timeout_ms,
            expect_bytes=5 + length,
        )
        if not meta.get("ok") or raw is None:
            raise TektoolError(
                f"memory_read addr={addr:#x} len={length}: {meta.get('error')}"
            )
        try:
            body = protocol.parse_read_response(raw, length)
        except ValueError as exc:
            raise TektoolError(f"memory_read addr={addr:#x}: {exc}") from None
        await self._send_ack()
        return body

    async def memory_write(
        self,
        addr: int,
        data: bytes,
        *,
        timeout_ms: int | None = None,
    ) -> None:
        """Write `data` to scope memory at `addr`.

        Wire transaction:
          host -> scope :  M-packet (cmd_hdr + addr + len + data)
          scope -> host :  '+' '=' csum len_be16   (5 bytes, EOI on last)
          host -> scope :  '+'   (final ack)
        """
        if not data:
            raise ValueError("data must be non-empty")
        pkt = protocol.pack_memory_write(addr, data)
        log.debug(
            "memory_write addr=%#x len=%d csum=%#x", addr, len(data), pkt[1],
        )
        # Reply is '+' (1) + cmd_hdr (4) = 5 bytes, no body, no EOI.
        meta, raw = await self._request_locked(
            "query_bytes", payload=pkt, timeout_ms=timeout_ms,
            expect_bytes=5,
        )
        if not meta.get("ok") or raw is None:
            raise TektoolError(
                f"memory_write addr={addr:#x} len={len(data)}: {meta.get('error')}"
            )
        try:
            protocol.parse_write_response(raw)
        except ValueError as exc:
            raise TektoolError(f"memory_write addr={addr:#x}: {exc}") from None
        await self._send_ack()

    async def _send_ack(self) -> None:
        """Single-byte '+' write, no reply expected. Final ack of a transaction."""
        meta, _ = await self._request_locked(
            "write_bytes", payload=protocol.pack_ack(),
        )
        if not meta.get("ok"):
            # Best-effort: the data we wanted is already in hand. Surface
            # in the journal so the operator notices, but don't raise.
            log.warning("ack write_bytes failed: %s", meta.get("error"))
