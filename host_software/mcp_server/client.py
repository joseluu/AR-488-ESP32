"""Persistent WebSocket wrapper around the AR-488-ESP32 gateway.

One connection for the lifetime of the MCP server. A single asyncio.Lock
serializes send/recv since Claude can fire concurrent tool calls.
Transparently reconnects if the WS drops (e.g. the ESP32 reboots after
a firmware flash) — one retry per request.

Connection params come from environment:
  AR488_HOST       (required)  IP/hostname of the ESP32
  AR488_ADDR       (default 1) GPIB primary address of the scope
  AR488_TIMEOUT_MS (default 2000)
"""
import asyncio
import builtins
import os
import sys

import websockets
from websockets.exceptions import ConnectionClosed

import request_gpib  # noqa: E402  (sys.path patched in package __init__)
from request_gpib import one_shot  # noqa: F401  (re-exported for tests)


# request_gpib uses bare print() to log every frame on stdout, which would
# corrupt the MCP JSON-RPC stream. Redirect its prints to stderr.
def _stderr_print(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    return builtins.print(*args, **kwargs)


request_gpib.print = _stderr_print


class GpibClient:
    def __init__(self):
        host = os.environ.get("AR488_HOST")
        if not host:
            raise RuntimeError(
                "AR488_HOST environment variable is required "
                "(IP or hostname of the AR-488-ESP32 gateway)"
            )
        self.host = host
        self.addr = int(os.environ.get("AR488_ADDR", "1"))
        self.timeout_ms = int(os.environ.get("AR488_TIMEOUT_MS", "2000"))
        self._ws = None
        self._lock = asyncio.Lock()

    def _ws_alive(self):
        if self._ws is None:
            return False
        # websockets exposes .state (newer) or .closed (older).
        state = getattr(self._ws, "state", None)
        if state is not None:
            from websockets.protocol import State
            return state == State.OPEN
        return not getattr(self._ws, "closed", True)

    async def _connect(self):
        if self._ws_alive():
            return
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        uri = f"ws://{self.host}/ws"
        self._ws = await websockets.connect(uri, max_size=None)

    async def request(self, action, command, timeout_ms=None):
        """Issue one request, return (meta, payload) from one_shot.

        action ∈ {"query", "write", "binary_query", "binary_read"}.
        """
        if action not in ("query", "write", "binary_query", "binary_read", "version"):
            raise ValueError(f"unknown action: {action!r}")
        timeout = timeout_ms if timeout_ms is not None else self.timeout_ms
        async with self._lock:
            for attempt in (0, 1):
                await self._connect()
                try:
                    return await one_shot(self._ws, action, command, self.addr, timeout)
                except (ConnectionClosed, OSError):
                    self._ws = None
                    if attempt == 1:
                        raise

    @property
    def ws(self):
        """Raw WebSocket — for the few helpers that take ws directly
        (collect_metadata, capture_channel). Only safe to call while
        holding self._lock; use `with_ws()` instead."""
        return self._ws

    async def with_ws(self, fn, *args, **kwargs):
        """Run `fn(ws, *args, **kwargs)` while holding the connection lock."""
        async with self._lock:
            for attempt in (0, 1):
                await self._connect()
                try:
                    return await fn(self._ws, *args, **kwargs)
                except (ConnectionClosed, OSError):
                    self._ws = None
                    if attempt == 1:
                        raise

    async def close(self):
        if self._ws is not None:
            ws, self._ws = self._ws, None
            await ws.close()
