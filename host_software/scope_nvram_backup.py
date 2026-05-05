#!/usr/bin/env python3
"""Calibration NVRAM (EEPROM) backup for vintage Tek TDS5xxB/6xxA/7xxA scopes.

Reads the two cal-EEPROM chips (U1052, U1055) via the AR-488-ESP32 gateway.
The scope must be in NORMAL mode — rear-panel Protect switch in the
Protected position, scope booted normally so it answers SCPI as usual on
GPIB primary address 1.

Wire flow (from fenugrec/tekfwtool/getcaldata.c):

  1. *IDN?                               sanity check
  2. PASSWORD PITBULL                    unlock low-level WORDCONSTANT cmd
  3. for f in 0..123:                    U1052 (256 B; first 8 are unmapped)
       WORDCONSTANT:ATOFFSET? 262144,f -> ASCII int -> [hi, lo] big-endian
  4. for f in 124..251:                  U1055 (256 B)
       same query, written to U1055.bin

Output:
  <out-dir>/<stamp>_U1052.bin   256 bytes  (8 zero bytes + 124 words BE)
  <out-dir>/<stamp>_U1055.bin   256 bytes  (128 words BE)
  + matching .sha256 sidecar files

Default --out-dir is ./host_software/tektool/backups so the cal dump lives
next to the firmware backup.

Usage:
  uv run python host_software/scope_nvram_backup.py --host 192.168.11.175

Important: this is NOT the service-mode binary protocol. The scope must be
running normally; tektool's flash backup must be done in the OPPOSITE state
(switch Unprotected). Don't mix the two in the same session.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import websockets


# Cal EEPROM layout (TDS784A and other listed models).
NVRAM_BASE = 262144         # 0x40000 — argument to WORDCONSTANT:ATOFFSET?
U1052_OFFSETS = range(0, 124)
U1055_OFFSETS = range(124, 252)
U1052_HEAD_PAD = 8          # first 8 bytes of U1052 are unmapped → write zeros


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


async def _request(ws, action: str, *, addr: int, command: str = "",
                   timeout_ms: int = 3000) -> dict:
    """One JSON request/response on the gateway WebSocket."""
    rid = f"nvr-{int(asyncio.get_running_loop().time() * 1e6)}"
    req = {
        "request_id": rid, "action": action,
        "addr": addr, "command": command, "timeout_ms": timeout_ms,
    }
    await ws.send(json.dumps(req))
    while True:
        frame = await asyncio.wait_for(
            ws.recv(), timeout=timeout_ms / 1000 + 3,
        )
        if isinstance(frame, (bytes, bytearray)):
            continue                                     # not for us
        msg = json.loads(frame)
        if msg.get("request_id") != rid:
            continue
        if msg.get("stream") == "begin":
            continue
        return msg


async def query(ws, addr: int, cmd: str, timeout_ms: int = 3000) -> str:
    msg = await _request(ws, "query", addr=addr, command=cmd,
                         timeout_ms=timeout_ms)
    if not msg.get("ok"):
        raise RuntimeError(f"query {cmd!r} failed: {msg.get('error')}")
    return str(msg.get("data", "")).strip()


async def write_cmd(ws, addr: int, cmd: str, timeout_ms: int = 2000) -> None:
    msg = await _request(ws, "write", addr=addr, command=cmd,
                         timeout_ms=timeout_ms)
    if not msg.get("ok"):
        raise RuntimeError(f"write {cmd!r} failed: {msg.get('error')}")


def _word_be(value: int) -> bytes:
    """Take low 16 bits of `value` and return them big-endian (hi, lo)."""
    return bytes([(value >> 8) & 0xFF, value & 0xFF])


async def dump_chip(ws, addr: int, offsets, head_pad: int) -> bytes:
    out = bytearray(b"\x00" * head_pad)
    for f in offsets:
        # Response is an ASCII integer — atoi-style. If the scope refuses
        # the command (no PASSWORD or wrong mode), the reply is empty or a
        # SCPI error string and int() throws.
        reply = await query(ws, addr, f"WORDCONSTANT:ATOFFSET? {NVRAM_BASE},{f}")
        try:
            val = int(reply.split(",")[-1].strip())
        except ValueError:
            raise RuntimeError(
                f"unparseable WORDCONSTANT reply at offset {f}: {reply!r}"
            )
        out += _word_be(val)
        if (f - offsets.start + 1) % 32 == 0 or f == offsets[-1]:
            print(f"  offset {f - offsets.start + 1}/{len(offsets)}",
                  end="\r", flush=True)
    print()
    return bytes(out)


def _write_with_sidecar(path: Path, data: bytes) -> str:
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(
        f"{digest}  {path.name}\n"
    )
    return digest


async def run(host: str, addr: int, out_dir: Path, idn_expect: str | None) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    uri = f"ws://{host}/ws"
    print(f"connecting to {uri}")
    async with websockets.connect(uri, max_size=None,
                                  ping_interval=None) as ws:
        # 1. *IDN? — sanity check that scope is in normal mode.
        idn = await query(ws, addr, "*IDN?", timeout_ms=3000)
        print(f"*IDN? -> {idn}")
        if idn_expect and idn.strip() != idn_expect.strip():
            raise RuntimeError(
                f"*IDN? mismatch.\n  expected: {idn_expect!r}\n  got:      {idn!r}"
            )

        # 2. Unlock — PASSWORD PITBULL (16 bytes, no quotes).
        await write_cmd(ws, addr, "PASSWORD PITBULL")
        print("PASSWORD PITBULL sent")
        await asyncio.sleep(0.1)

        # 3. U1052 — first 8 bytes zero-padded, then 124 WORDCONSTANT reads.
        print("dumping U1052 (124 words)...")
        u1052 = await dump_chip(ws, addr, U1052_OFFSETS, U1052_HEAD_PAD)

        # 4. U1055 — 128 WORDCONSTANT reads (no head pad).
        print("dumping U1055 (128 words)...")
        u1055 = await dump_chip(ws, addr, U1055_OFFSETS, 0)

    stamp = _stamp()
    p1052 = out_dir / f"{stamp}_U1052.bin"
    p1055 = out_dir / f"{stamp}_U1055.bin"
    h1 = _write_with_sidecar(p1052, u1052)
    h2 = _write_with_sidecar(p1055, u1055)

    print()
    print(f"U1052 -> {p1052} ({len(u1052)} B, sha256={h1})")
    print(f"U1055 -> {p1055} ({len(u1055)} B, sha256={h2})")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", required=True, help="AR-488-ESP32 IP/hostname")
    p.add_argument("--addr", type=int, default=1,
                   help="GPIB primary address of the scope (default 1, "
                        "scope's normal-mode address)")
    p.add_argument("--out-dir", type=Path,
                   default=Path("host_software/tektool/backups"),
                   help="Output directory (default: alongside flash backups)")
    p.add_argument("--idn",
                   help="Optional: expected *IDN? string for byte-for-byte "
                        "verification before unlocking")
    args = p.parse_args(argv)
    try:
        return asyncio.run(run(args.host, args.addr, args.out_dir, args.idn))
    except (RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
