#!/usr/bin/env python3
"""GPIB stability stress tests for AR-488-ESP32 + Tektronix TDS784A.

Implements the four phases from Data_Stress_tests.md:
  1. *IDN? heartbeat (200x)
  2. CURVE? bulk read (20x, 15000-pt record, RIBINARY width 1)
  3. MESSAGE:SHOW bulk write (50x, 1024-char alphanumeric payloads)
  4. HARDCOPY screen capture (BMP, validated by 'BM' signature)

Uses request_gpib as a library (one_shot, parse_ieee_block, iso_stamp).

Usage:
    cd host_software
    uv run python data_stress_tests.py <ip> [--addr N] [--quiet]
"""
import argparse
import asyncio
import random
import string
import struct
import sys
import time
from datetime import datetime

import websockets

import request_gpib as rg


TIMEOUT_MS = 5000  # per spec section 1
EXPECTED_IDN_PREFIX = "TEKTRONIX,TDS 784A"


# Suppress per-call request/response prints from request_gpib in --quiet mode.
class _SinkStdout:
    def write(self, _):
        pass

    def flush(self):
        pass


_real_stdout = sys.stdout


def _quiet(on: bool):
    sys.stdout = _SinkStdout() if on else _real_stdout


def now_iso():
    return rg.iso_stamp(datetime.now())


async def _safe_one_shot(ws, action, command, addr, timeout):
    """one_shot wrapper that converts low-level errors into (None, str)."""
    try:
        return await rg.one_shot(ws, action, command, addr, timeout), None
    except (asyncio.TimeoutError, TimeoutError) as e:
        return None, f"timeout: {e}"
    except websockets.exceptions.ConnectionClosed as e:
        return None, f"connection closed: {e}"
    except OSError as e:
        return None, f"os error: {type(e).__name__}: {e}"


async def phase1_heartbeat(ws, addr, n_iter=200, quiet=True):
    print(f"\n=== Phase 1: heartbeat (*IDN? x {n_iter}) ===")
    fails = []
    t0 = time.perf_counter()
    _quiet(quiet)
    try:
        for i in range(1, n_iter + 1):
            res, err = await _safe_one_shot(ws, "query", "*IDN?", addr, TIMEOUT_MS)
            if err:
                fails.append((i, err))
                continue
            meta, _ = res
            if not meta.get("ok"):
                fails.append((i, f"gateway error: {meta.get('error')!r}"))
                continue
            data = (meta.get("data") or "").strip()
            if not data.startswith(EXPECTED_IDN_PREFIX):
                fails.append((i, f"unexpected response: {data[:80]!r}"))
    finally:
        _quiet(False)
    dt = time.perf_counter() - t0
    n_pass = n_iter - len(fails)
    print(f"Phase 1: {n_pass}/{n_iter} OK in {dt:.1f}s ({n_iter/dt:.1f} req/s)")
    for i, msg in fails[:10]:
        print(f"  FAIL iter {i}: {msg}")
    if len(fails) > 10:
        print(f"  ... and {len(fails) - 10} more failures")
    return len(fails) == 0


async def phase2_bulk_read(ws, addr, n_iter=20, record_length=15000, quiet=True):
    print(f"\n=== Phase 2: bulk read (CURVE? x {n_iter}, {record_length} pts) ===")
    setup = [
        "HEADER OFF",  # so CURVE? returns "#5...." instead of ":CURVE #5...."
        f"HORIZONTAL:RECORDLENGTH {record_length}",
        "DATA:SOURCE CH1",
        "DATA:ENCDG RIBINARY",
        "DATA:WIDTH 1",
        "DATA:START 1",
        f"DATA:STOP {record_length}",
    ]
    _quiet(quiet)
    try:
        for cmd in setup:
            res, err = await _safe_one_shot(ws, "write", cmd, addr, TIMEOUT_MS)
            if err or not res[0].get("ok"):
                _quiet(False)
                print(f"  setup FAIL: {cmd} -> {err or res[0].get('error')!r}")
                return False

        fails = []
        sizes = []
        durations = []
        t0 = time.perf_counter()
        for i in range(1, n_iter + 1):
            ti = time.perf_counter()
            res, err = await _safe_one_shot(
                ws, "binary_query", "CURVE?", addr, max(TIMEOUT_MS, 8000)
            )
            durations.append((time.perf_counter() - ti) * 1000.0)
            if err:
                fails.append((i, err))
                continue
            meta, payload = res
            if not meta.get("ok") or payload is None:
                fails.append((i, f"gateway error: {meta.get('error')!r}"))
                continue
            # Locate the IEEE 488.2 definite-length block: #<n><nnn...><body>.
            # Tolerate a leading SCPI header (":CURVE ") if HEADER ON slipped through.
            hash_pos = payload.find(b"#")
            if hash_pos < 0:
                fails.append((i, f"no '#' in response (first 32 bytes={payload[:32]!r})"))
                continue
            try:
                n = int(payload[hash_pos + 1:hash_pos + 2])
                declared_len = int(payload[hash_pos + 2:hash_pos + 2 + n])
            except ValueError:
                fails.append((i, f"unparseable header {payload[hash_pos:hash_pos + 8]!r}"))
                continue
            body_len = len(payload) - (hash_pos + 2 + n)
            # Tek may append a trailing terminator (LF) after the body; tolerate it.
            if body_len < declared_len:
                fails.append((i, f"short body: header says {declared_len}, got {body_len}"))
                continue
            if body_len > declared_len + 2:
                fails.append((i, f"extra trailing bytes: body {body_len} vs header {declared_len}"))
                continue
            if declared_len != record_length:
                fails.append((i, f"length != record_length: {declared_len} vs {record_length}"))
                continue
            sizes.append(declared_len)
        dt = time.perf_counter() - t0
    finally:
        _quiet(False)

    n_pass = n_iter - len(fails)
    print(f"Phase 2: {n_pass}/{n_iter} OK in {dt:.1f}s")
    if sizes:
        print(f"  payload bytes per iter: min={min(sizes)} max={max(sizes)}")
    if durations:
        print(f"  per-CURVE? wall time: "
              f"min={min(durations):.0f} median={sorted(durations)[len(durations)//2]:.0f} "
              f"max={max(durations):.0f} ms")
    for i, msg in fails[:10]:
        print(f"  FAIL iter {i}: {msg}")
    return len(fails) == 0


async def phase3_bulk_write(ws, addr, n_iter=50, payload_len=1024, quiet=True):
    print(f"\n=== Phase 3: bulk write (MESSAGE:SHOW x {n_iter}, {payload_len} chars) ===")
    rng = random.Random(0xA488)
    alphabet = string.ascii_letters + string.digits
    fails = []
    _quiet(quiet)
    t0 = time.perf_counter()
    try:
        for i in range(1, n_iter + 1):
            s = "".join(rng.choices(alphabet, k=payload_len))
            cmd_show = f'MESSAGE:SHOW "{s}"'
            res, err = await _safe_one_shot(ws, "write", cmd_show, addr, TIMEOUT_MS)
            if err:
                fails.append((i, f"SHOW {err}"))
                continue
            meta, _ = res
            if not meta.get("ok"):
                fails.append((i, f"SHOW error: {meta.get('error')!r}"))
                continue
            res, err = await _safe_one_shot(
                ws, "write", "MESSAGE:STATE ON", addr, TIMEOUT_MS
            )
            if err:
                fails.append((i, f"STATE ON {err}"))
                continue
            meta, _ = res
            if not meta.get("ok"):
                fails.append((i, f"STATE ON error: {meta.get('error')!r}"))
        # Tidy up: clear the displayed message at the end.
        await _safe_one_shot(ws, "write", "MESSAGE:STATE OFF", addr, TIMEOUT_MS)
    finally:
        _quiet(False)
    dt = time.perf_counter() - t0
    n_pass = n_iter - len(fails)
    print(f"Phase 3: {n_pass}/{n_iter} OK in {dt:.1f}s")
    for i, msg in fails[:10]:
        print(f"  FAIL iter {i}: {msg}")
    return len(fails) == 0


async def phase4_screen_capture(ws, addr, quiet=True):
    print(f"\n=== Phase 4: screen capture (HARDCOPY BMP) ===")
    setup = [
        "HARDCOPY:PORT GPIB",
        "HARDCOPY:FORMAT BMPCOLOR",
        "HARDCOPY:LAYOUT PORTRAIT",
        "HARDCOPY:PALETTE COLOR",
    ]
    _quiet(quiet)
    try:
        for cmd in setup:
            res, err = await _safe_one_shot(ws, "write", cmd, addr, TIMEOUT_MS)
            if err or not res[0].get("ok"):
                _quiet(False)
                print(f"  setup FAIL: {cmd} -> {err or res[0].get('error')!r}")
                return False
        res, err = await _safe_one_shot(ws, "write", "HARDCOPY START", addr, TIMEOUT_MS)
        if err or not res[0].get("ok"):
            _quiet(False)
            print(f"  HARDCOPY START FAIL: {err or res[0].get('error')!r}")
            return False
        t0 = time.perf_counter()
        # BMP renders + transfers in a few seconds; allow 30s.
        res, err = await _safe_one_shot(ws, "binary_read", "", addr, 30000)
        dt = (time.perf_counter() - t0) * 1000.0
    finally:
        _quiet(False)

    if err:
        print(f"  read FAIL: {err}")
        return False
    meta, payload = res
    if not meta.get("ok") or payload is None:
        print(f"  read FAIL: {meta.get('error')!r}")
        return False

    valid_sig = payload[:2] == b"BM"
    bf_size = struct.unpack("<I", payload[2:6])[0] if len(payload) >= 6 else 0
    path = f"{now_iso()}_stress_screen.bmp"
    with open(path, "wb") as f:
        f.write(payload)
    print(f"  read {len(payload)} bytes in {dt:.0f} ms -> {path}")
    print(f"  BMP 'BM' magic present: {valid_sig}")
    if bf_size and bf_size != len(payload):
        # TDS784A BMPCOLOR firmware writes a bfSize that doesn't equal the
        # actual file size; the file is still a valid bitmap. Note and proceed.
        print(f"  note: BMP bfSize header={bf_size} != file size {len(payload)} "
              f"(known TDS784A quirk)")
    # Verify the BMP actually decodes (catches mid-stream corruption / shearing).
    decoded = False
    decode_err = None
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(payload))
        img.load()
        print(f"  PIL decode OK: mode={img.mode} size={img.size}")
        decoded = True
    except Exception as e:
        decode_err = f"{type(e).__name__}: {e}"
        print(f"  PIL decode FAIL: {decode_err}")
    return valid_sig and decoded


async def run_all(host, addr, quiet):
    uri = f"ws://{host}/ws"
    print(f"Connecting to {uri} (GPIB addr={addr}, timeout={TIMEOUT_MS} ms)...")
    results = {}
    async with websockets.connect(uri, max_size=None) as ws:
        results["phase1"] = await phase1_heartbeat(ws, addr, quiet=quiet)
        results["phase2"] = await phase2_bulk_read(ws, addr, quiet=quiet)
        results["phase3"] = await phase3_bulk_write(ws, addr, quiet=quiet)
        results["phase4"] = await phase4_screen_capture(ws, addr, quiet=quiet)

    print("\n=== Summary ===")
    for k, v in results.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    return all(results.values())


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("host", help="AR-488-ESP32 IP (e.g. 192.168.11.175)")
    p.add_argument("--addr", type=int, default=1, help="GPIB primary address (default 1)")
    p.add_argument("--verbose", action="store_true",
                   help="Show every -> request / <- response from request_gpib")
    args = p.parse_args()
    quiet = not args.verbose
    try:
        ok = asyncio.run(run_all(args.host, args.addr, quiet))
    except (TimeoutError, asyncio.TimeoutError, ConnectionError, OSError) as e:
        print(f"\nERROR: cannot reach AR-488-ESP32 at ws://{args.host}/ws "
              f"({type(e).__name__}: {e})", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
