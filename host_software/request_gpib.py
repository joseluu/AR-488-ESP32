#!/usr/bin/env python3
"""Send GPIB SCPI commands to a Tek scope via the AR-488-ESP32 gateway.

The ESP32 hosts a JSON-over-WebSocket bridge at ws://<host>/ws. This
script handles the protocol so an operator (or AI agent) can issue
SCPI commands and capture waveforms directly from the shell.

Invocation
----------
    send_gpib.py <ip> <scpi-command>           # auto: query if '?' else write
    send_gpib.py <ip> --binary "<scpi>"        # force binary response
    send_gpib.py <ip> --waveform [options]     # capture waveform(s)
    send_gpib.py <ip> --hardcopy [options]     # capture screen (PCXCOLOR -> PNG default)
    send_gpib.py <ip> --default-addr N         # persist gateway default addr
    send_gpib.py --help                         # full per-flag help

Output files
------------
Named  <ISO_8601>_<name>[_<chN>].<ext>  where:
  ISO_8601 = YYYY-MM-DDTHH-MM-SS taken at capture start (Windows-safe)
  name     = --name (default 'waveform')
  ext      = controlled by --out: 'csv', 'bin', or 'csv,bin'
  Default for --waveform is csv; other commands write nothing unless
  --out bin is given.

CSV layout
----------
    meta_key, meta_value, sample, raw_chN..., time_s, voltage_v_chN...
- Cols 1-2 hold scope state: date, hour, *IDN?, horizontal/trigger
  setup, then per-channel scale/offset/coupling/etc. Failed queries
  are silently dropped from this block.
- 'sample' is the 1-based scope record index.
- time_s/voltage_v_* are present only when WFMPRE? succeeds.

Windowed / large captures
-------------------------
TDS784A supports up to 500 000 points per record (option 1M). Use
--start-index/--end-index (1-based inclusive) to crop in the
instrument via DATA:START / DATA:STOP - only the requested range
crosses the GPIB bus. Windows larger than --chunk-bytes (default
32 KiB) are still split per-CURVE? to keep each Python bytes object
small; the gateway itself streams unbounded binary payloads.

Examples
--------
    send_gpib.py 192.168.1.42 "*IDN?"
    send_gpib.py 192.168.1.42 "CH2:SCALE 500E-3"             # 500 mV/div
    send_gpib.py 192.168.1.42 "HORIZONTAL:MAIN:SCALE?"

    # Default 5 K-pt capture from CH1 -> <stamp>_waveform.csv
    send_gpib.py 192.168.1.42 --waveform

    # Two channels, both CSV and per-channel .bin
    send_gpib.py 192.168.1.42 --waveform --source CH1,CH2 --out csv,bin

    # Full 500 K-pt record at 16-bit, custom name
    send_gpib.py 192.168.1.42 --waveform --points 500000 --width 2 --name run42

    # Sub-window 100k..105k from a 500 K record (5 K samples on the wire)
    send_gpib.py 192.168.1.42 --waveform --points 500000 \\
                 --start-index 100000 --end-index 105000

    # Screen hardcopy: PCXCOLOR fetched, converted to PNG -> <stamp>_screen.png
    send_gpib.py 192.168.1.42 --hardcopy

    # Hardcopy as native TIFF (no conversion), custom name
    send_gpib.py 192.168.1.42 --hardcopy --hardcopy-format TIFF --name run42

    # Different scope GPIB address
    send_gpib.py 192.168.1.42 --addr 5 "*IDN?"
"""
import argparse
import asyncio
import csv
import json
import re
import struct
import sys
import time
from datetime import datetime

import websockets

# MCP-LIBRARY: imported by mcp_server. Do not change name or pattern.
_FLOAT_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


# MCP-LIBRARY: imported by mcp_server. Do not change signature.
def iso_stamp(dt: datetime) -> str:
    """Sortable ISO 8601 stamp safe for Windows filenames (':' replaced by '-')."""
    return dt.strftime("%Y-%m-%dT%H-%M-%S")


def parse_formats(s: str):
    return {f.strip().lower() for f in s.split(",") if f.strip()}


def parse_channels(s: str):
    return [c.strip().upper() for c in s.split(",") if c.strip()]


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="send_gpib.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("host", help="AR-488-ESP32 IP or hostname (shown on the OLED)")
    p.add_argument("command", nargs="?", help="SCPI command (omit when using --waveform or --hardcopy)")
    p.add_argument("--addr", type=int, default=1, help="GPIB primary address (default 1)")
    p.add_argument("--timeout", type=int, default=2000, help="GPIB timeout in ms")
    p.add_argument("--binary", action="store_true",
                   help="Force binary_query action (response returned as raw bytes)")
    p.add_argument("--waveform", action="store_true",
                   help="Capture a waveform: configures DATA:* and runs CURVE? per channel")
    p.add_argument("--hardcopy", action="store_true",
                   help="Capture the scope screen as an image (default TIFF). "
                        "Saved to <stamp>_<name>.<ext>.")
    p.add_argument("--hardcopy-format", default="PCXCOLOR",
                   choices=("TIFF", "BMP", "BMPCOLOR", "PCX", "PCXCOLOR", "RLE"),
                   help="HARDCOPY:FORMAT value (default PCXCOLOR; PCX/PCXCOLOR are "
                        "auto-converted to PNG on disk)")
    p.add_argument("--hardcopy-layout", default="PORTRAIT",
                   choices=("PORTRAIT", "LANDSCAPE"),
                   help="HARDCOPY:LAYOUT value (default PORTRAIT)")
    p.add_argument("--hardcopy-palette", default="COLOR",
                   choices=("COLOR", "MONOCHROME", "INKSAVER", "HARDCOPY"),
                   help="HARDCOPY:PALETTE value (default COLOR)")
    p.add_argument("--points", type=int, default=5000,
                   help="Default end-index when --end-index is not given (default 5000). "
                        "Set to the scope's full record length (up to 500000) to grab everything.")
    p.add_argument("--start-index", type=int, default=None,
                   help="First record sample to transfer, 1-based (default 1). Maps to DATA:START.")
    p.add_argument("--end-index", type=int, default=None,
                   help="Last record sample to transfer, 1-based inclusive "
                        "(default --points). Maps to DATA:STOP.")
    p.add_argument("--chunk-bytes", type=int, default=32768,
                   help="Max bytes per CURVE? response; larger windows are split into "
                        "chunks transparently (default 32768).")
    p.add_argument("--source", default="CH1",
                   help="Source channel(s), comma-separated (default CH1, e.g. CH1,CH2)")
    p.add_argument("--width", type=int, default=1, choices=(1, 2),
                   help="Bytes per sample, 1 or 2 (default 1)")
    p.add_argument("--name", default=None,
                   help="Stem for output files (default 'waveform' for --waveform, "
                        "'screen' for --hardcopy, 'capture' otherwise)")
    p.add_argument("--out", default="",
                   help="Output formats, comma-separated: csv, bin. "
                        "Default for --waveform is 'csv'; for other commands no file is written.")
    p.add_argument("--default-addr", type=int, default=None,
                   help="Set the gateway's persisted default GPIB address (1..30) and exit.")
    args = p.parse_args(argv)
    n_modes = sum(bool(x) for x in (args.waveform, args.hardcopy, args.default_addr is not None))
    if n_modes > 1:
        p.error("--waveform, --hardcopy, --default-addr are mutually exclusive")
    if (not args.waveform and not args.hardcopy and args.default_addr is None
            and not args.command):
        p.error("a SCPI command, --waveform, --hardcopy, or --default-addr is required")
    if args.default_addr is not None and not (1 <= args.default_addr <= 30):
        p.error("--default-addr must be in 1..30")
    args.formats = parse_formats(args.out)
    args.channels = parse_channels(args.source)
    if args.waveform and not args.formats:
        args.formats = {"csv"}
    bad = args.formats - {"csv", "bin"}
    if bad:
        p.error(f"unknown --out format(s): {sorted(bad)} (allowed: csv, bin)")
    if args.name is None:
        args.name = "screen" if args.hardcopy else ("waveform" if args.waveform else "capture")
    return args


# MCP-LIBRARY: imported by mcp_server. Do not change signature.
def make_request(rid, action, command, addr, timeout):
    return {
        "request_id": rid,
        "action": action,
        "command": command,
        "addr": addr,
        "timeout_ms": timeout,
    }


# MCP-LIBRARY: imported by mcp_server. Do not change signature.
def parse_ieee_block(buf: bytes) -> bytes:
    """Strip the IEEE 488.2 definite-length block header `#<n><nnn...>`."""
    if not buf or buf[0:1] != b"#":
        return buf
    n = int(buf[1:2])
    length = int(buf[2:2 + n])
    return buf[2 + n:2 + n + length]


# MCP-LIBRARY: imported by mcp_server. Do not change signature or return shape.
async def one_shot(ws, action, command, addr, timeout):
    """Send one request, return (meta, payload).

    Binary actions stream: a 'stream:begin' JSON, N binary frames, then
    a 'stream:end' JSON with total length. We accumulate frames until
    the end JSON arrives. The returned `meta` is the end JSON (so
    callers see ok/error/length); `payload` is the joined bytes."""
    rid = str(int(time.time() * 1000))
    req = make_request(rid, action, command, addr, timeout)
    print(f"-> {req}")
    await ws.send(json.dumps(req))

    # First reply is always JSON.
    text = await asyncio.wait_for(ws.recv(), timeout=timeout / 1000 + 3)
    print(f"<- {text}")
    meta = json.loads(text)

    if meta.get("stream") == "begin":
        chunks = []
        # Per-frame timeout: long enough for the scope's first-byte
        # latency (e.g. HARDCOPY rendering) and slow GPIB transfers.
        per_frame_to = max(timeout / 1000 + 30, 60)
        while True:
            frame = await asyncio.wait_for(ws.recv(), timeout=per_frame_to)
            if isinstance(frame, (bytes, bytearray)):
                chunks.append(bytes(frame))
            else:
                end = json.loads(frame)
                print(f"<- {end}")
                payload = b"".join(chunks)
                expected = end.get("length")
                if end.get("ok") and expected is not None and expected != len(payload):
                    print(f"warning: stream length mismatch "
                          f"(got {len(payload)}, expected {expected})")
                print(f"<- (binary {len(payload)} bytes total in "
                      f"{len(chunks)} frame(s))")
                return end, (payload if end.get("ok") else None)
    elif meta.get("binary"):
        # Legacy single-frame binary fallback (older firmware).
        payload = await asyncio.wait_for(ws.recv(), timeout=timeout / 1000 + 3)
        print(f"<- (binary {len(payload)} bytes)")
        return meta, payload
    return meta, None


# MCP-LIBRARY: imported by mcp_server. Do not change signature.
def decode_samples(body: bytes, width: int):
    """Decode a CURVE? payload (header already stripped) to signed ints."""
    n = len(body) // width
    if width == 1:
        return list(struct.unpack(f">{n}b", body[: n * width]))
    return list(struct.unpack(f">{n}h", body[: n * width]))


# MCP-LIBRARY: imported by mcp_server. Do not change signature.
def parse_wfmpre(data: str) -> dict:
    """Parse a TDS784A WFMPRE? response into a dict of leaf -> value-string.

    Response shape (semicolon-separated, compound SCPI headers):
      :WFMPRE:BYT_NR 1;BIT_NR 8;...;XINCR 20.00E-6;XZERO 15.51E-6;
      PT_OFF 1250;...;YMULT 8.000E-3;YOFF -55.00E+0;YZERO 0.0E+0
    """
    result = {}
    for part in data.split(";"):
        part = part.strip()
        if not part:
            continue
        if part.startswith(":"):
            part = part[1:]
        if " " not in part:
            continue
        header, value = part.split(" ", 1)
        leaf = header.split(":")[-1]
        result[leaf] = value.strip()
    return result


# MCP-LIBRARY: imported by mcp_server. Do not change signature.
async def query_preamble(ws, addr, timeout):
    """Fetch the full waveform preamble in one shot and parse the scaling
    factors. Returns a float dict or None on failure (prints why)."""
    meta, _ = await one_shot(ws, "query", "WFMPRE?", addr, timeout)
    if not meta.get("ok"):
        print(f"  preamble: gateway error: {meta.get('error')!r}")
        return None
    fields = parse_wfmpre(meta.get("data", ""))

    needed = ("YMULT", "YOFF", "YZERO", "XINCR", "XZERO", "PT_OFF")
    pre = {}
    for k in needed:
        if k not in fields:
            print(f"  preamble: missing {k}; got keys: {list(fields)}")
            return None
        m = _FLOAT_RE.search(fields[k])
        if not m:
            print(f"  preamble {k}: no numeric value in {fields[k]!r}")
            return None
        pre[k] = float(m.group())
    return pre


# MCP-LIBRARY: imported by mcp_server. Do not change signature.
async def query_value(ws, addr, timeout, command):
    """Run a query and return the trimmed value string, or None on failure.

    Tek replies in either "VALUE" or ":HEADER:NAME VALUE" form; we keep
    everything after the last space and strip a trailing ';'."""
    meta, _ = await one_shot(ws, "query", command, addr, timeout)
    if not meta.get("ok"):
        return None
    data = meta.get("data", "")
    text = data.rsplit(" ", 1)[-1].rstrip(";").strip()
    return text or None


# Setup queries that don't depend on the channel.
# Note: TDS784A has no SAMPLERATE? command — sample rate is derived
# client-side from record_length / (10 * horizontal_scale_s).
# Holdoff is HOLDOFF:TIME (per SET? on TDS784A v4.1e), not :VALUE.
# MCP-LIBRARY: imported by mcp_server. Do not change tuple shape.
_GLOBAL_META_QUERIES = (
    ("horizontal_scale_s",   "HORIZONTAL:MAIN:SCALE?"),
    ("record_length",        "HORIZONTAL:RECORDLENGTH?"),
    ("trigger_position_pct", "HORIZONTAL:TRIGGER:POSITION?"),
    ("acquire_mode",         "ACQUIRE:MODE?"),
    ("acquire_count",        "ACQUIRE:NUMACQ?"),
    ("acquire_state",        "ACQUIRE:STATE?"),
    ("trigger_type",         "TRIGGER:MAIN:TYPE?"),
    ("trigger_source",       "TRIGGER:MAIN:EDGE:SOURCE?"),
    ("trigger_level_v",      "TRIGGER:MAIN:LEVEL?"),
    ("trigger_slope",        "TRIGGER:MAIN:EDGE:SLOPE?"),
    ("trigger_coupling",     "TRIGGER:MAIN:EDGE:COUPLING?"),
    ("trigger_holdoff_s",    "TRIGGER:MAIN:HOLDOFF:TIME?"),
)

# MCP-LIBRARY: imported by mcp_server. Do not change tuple shape.
_PER_CHANNEL_META_QUERIES = (
    ("scale_v",       "{ch}:SCALE?"),
    ("position_div",  "{ch}:POSITION?"),
    ("offset_v",      "{ch}:OFFSET?"),
    ("coupling",      "{ch}:COUPLING?"),
    ("bandwidth",     "{ch}:BANDWIDTH?"),
    ("impedance_ohm", "{ch}:IMPEDANCE?"),
    ("probe_atten",   "{ch}:PROBE?"),
)


# MCP-LIBRARY: imported by mcp_server. Do not change signature; mcp_server
# passes a SimpleNamespace with .addr and .timeout to mimic the CLI args.
async def collect_metadata(ws, args, channels, capture_time):
    """Query the scope for setup state. Failures on individual queries are
    silent (the key is just not added). Returns an ordered dict."""
    meta = {}
    meta["date"] = capture_time.strftime("%Y-%m-%d")
    meta["hour"] = capture_time.strftime("%H:%M:%S")

    idn = await query_value(ws, args.addr, args.timeout, "*IDN?")
    if idn is not None:
        meta["instrument"] = idn

    for key, cmd in _GLOBAL_META_QUERIES:
        v = await query_value(ws, args.addr, args.timeout, cmd)
        if v is not None:
            meta[key] = v

    for ch in channels:
        ch_low = ch.lower()
        for key, cmd_tmpl in _PER_CHANNEL_META_QUERIES:
            v = await query_value(ws, args.addr, args.timeout, cmd_tmpl.format(ch=ch))
            if v is not None:
                meta[f"{ch_low}_{key}"] = v
    return meta


# MCP-LIBRARY: imported by mcp_server. args needs .addr, .timeout, .width.
async def _setup_channel(ws, channel, args):
    """One-time per-channel DATA:* setup (source / encoding / width)."""
    for cmd in (f"DATA:SOURCE {channel}",
                "DATA:ENCDG RIBINARY",
                f"DATA:WIDTH {args.width}"):
        meta, _ = await one_shot(ws, "write", cmd, args.addr, args.timeout)
        if not meta.get("ok"):
            print(f"setup FAIL on {channel}: {cmd} -> {meta.get('error')}")
            return False
    return True


# MCP-LIBRARY: imported by mcp_server. args needs .addr, .timeout.
async def _set_window(ws, args, start, stop):
    for cmd in (f"DATA:START {start}", f"DATA:STOP {stop}"):
        meta, _ = await one_shot(ws, "write", cmd, args.addr, args.timeout)
        if not meta.get("ok"):
            print(f"window set FAIL: {cmd} -> {meta.get('error')}")
            return False
    return True


# MCP-LIBRARY: imported by mcp_server. args needs .addr, .timeout, .width,
# .points, .start_index, .end_index, .chunk_bytes.
async def capture_channel(ws, channel, args, want_preamble):
    """Capture a (possibly windowed, possibly chunked) waveform for one channel.

    Returns a capture dict: channel, samples, body (last chunk only), preamble,
    dt_ms (sum across chunks), start_idx, end_idx. None on failure (printed)."""
    start_idx = args.start_index if args.start_index else 1
    end_idx   = args.end_index   if args.end_index   else args.points
    if start_idx < 1 or end_idx < start_idx:
        print(f"invalid window for {channel}: start={start_idx} end={end_idx}")
        return None

    if not await _setup_channel(ws, channel, args):
        return None

    # Set the user's full window first so WFMPRE?'s NR_PT/PT_OFF/XZERO
    # describe the transmitted window. This also primes DATA:* if the
    # window fits in one chunk (the loop below will overwrite for chunks).
    if not await _set_window(ws, args, start_idx, end_idx):
        return None

    preamble = None
    if want_preamble:
        preamble = await query_preamble(ws, args.addr, args.timeout)

    # Chunked CURVE?. Each chunk has its own DATA:START/DATA:STOP.
    max_samples = max(1, args.chunk_bytes // args.width)
    samples = []
    last_body = b""
    total_dt = 0.0
    pos = start_idx
    n_chunks = 0
    while pos <= end_idx:
        chunk_end = min(pos + max_samples - 1, end_idx)
        # Only re-set the window if we'll do more than one chunk.
        if pos != start_idx or chunk_end != end_idx:
            if not await _set_window(ws, args, pos, chunk_end):
                return None
        t0 = time.perf_counter()
        meta, payload = await one_shot(ws, "binary_query", "CURVE?",
                                       args.addr, max(args.timeout, 8000))
        dt = (time.perf_counter() - t0) * 1000.0
        total_dt += dt
        n_chunks += 1
        if not meta.get("ok") or payload is None:
            print(f"FAIL {channel} chunk [{pos}-{chunk_end}]: {meta.get('error')}")
            return None
        last_body = parse_ieee_block(payload)
        chunk_samples = decode_samples(last_body, args.width)
        samples.extend(chunk_samples)
        print(f"  {channel} chunk [{pos}-{chunk_end}] {len(chunk_samples)} pts "
              f"({len(last_body)} B) in {dt:.1f} ms")
        pos = chunk_end + 1

    print(f"OK  {channel}  {len(samples)} pts (record idx {start_idx}-{end_idx}) "
          f"in {n_chunks} chunk(s) / {total_dt:.1f} ms")

    return {
        "channel": channel,
        "body": last_body,
        "samples": samples,
        "preamble": preamble,
        "dt_ms": total_dt,
        "start_idx": start_idx,
        "end_idx": end_idx,
    }


def encode_samples_bytes(samples, width):
    """Pack decoded sample list back to big-endian signed bytes."""
    if width == 1:
        return struct.pack(f">{len(samples)}b", *samples)
    return struct.pack(f">{len(samples)}h", *samples)


def write_multi_csv(path, captures, metadata):
    """Combined CSV: meta key/value columns first, then sample columns.

    Columns: meta_key, meta_value, sample, raw_chN..., time_s, voltage_v_chN...
    Metadata block lives in rows where there are pairs to write; sample
    block lives in rows where there are samples. When one side runs out,
    those cells are empty so the other side keeps going.
    """
    n_samples = min(len(c["samples"]) for c in captures)
    have_preamble = all(c.get("preamble") is not None for c in captures)
    start_idx = captures[0]["start_idx"]
    meta_items = list(metadata.items())
    n_meta = len(meta_items)

    sample_cols = 1 + len(captures)                     # sample, raw_chN
    if have_preamble:
        sample_cols += 1 + len(captures)                # time_s, voltage_v_chN

    header = ["meta_key", "meta_value", "sample"]
    for c in captures:
        header.append(f"raw_{c['channel'].lower()}")
    if have_preamble:
        header.append("time_s")
        for c in captures:
            header.append(f"voltage_v_{c['channel'].lower()}")

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        if have_preamble:
            pre0 = captures[0]["preamble"]
            xincr  = pre0["XINCR"]
            xzero  = pre0["XZERO"]
            pt_off = pre0["PT_OFF"]

        for i in range(max(n_samples, n_meta)):
            row = []
            if i < n_meta:
                k, v = meta_items[i]
                row.extend([k, v])
            else:
                row.extend(["", ""])

            if i < n_samples:
                global_idx = start_idx + i
                row.append(global_idx)
                for c in captures:
                    row.append(c["samples"][i])
                if have_preamble:
                    t = (i + 1 - pt_off) * xincr + xzero
                    row.append(f"{t:.9e}")
                    for c in captures:
                        pre = c["preamble"]
                        raw = c["samples"][i]
                        v = (raw - pre["YOFF"]) * pre["YMULT"] + pre["YZERO"]
                        row.append(f"{v:.9e}")
            else:
                row.extend([""] * sample_cols)
            w.writerow(row)
    suffix = "" if have_preamble else " (raw codes only - WFMPRE? unavailable)"
    print(f"saved {n_samples} samples x {len(captures)} channel(s) "
          f"and {n_meta} metadata entries to {path}{suffix}")


async def run_set_default_addr(args):
    """Send a set_default_addr control request and exit."""
    uri = f"ws://{args.host}/ws"
    async with websockets.connect(uri) as ws:
        rid = str(int(time.time() * 1000))
        req = {
            "request_id": rid,
            "action": "set_default_addr",
            "addr": args.default_addr,
            "timeout_ms": args.timeout,
        }
        print(f"-> {req}")
        await ws.send(json.dumps(req))
        text = await asyncio.wait_for(ws.recv(), timeout=args.timeout / 1000 + 3)
        print(f"<- {text}")
        meta = json.loads(text)
        if not meta.get("ok"):
            print(f"FAIL: {meta.get('error')}")
            sys.exit(1)
        print(f"OK  default GPIB address persisted as {meta.get('addr')}")


async def run_simple(args):
    action = "binary_query" if args.binary else ("query" if "?" in args.command else "write")
    uri = f"ws://{args.host}/ws"
    capture_time = datetime.now()
    async with websockets.connect(uri) as ws:
        meta, payload = await one_shot(ws, action, args.command, args.addr, args.timeout)
        if not meta.get("ok"):
            print("FAIL:", meta.get("error"))
            sys.exit(1)
        if payload is not None and "bin" in args.formats:
            path = f"{iso_stamp(capture_time)}_{args.name}.bin"
            with open(path, "wb") as f:
                f.write(payload)
            print(f"saved {len(payload)} bytes to {path}")


# MCP-LIBRARY: imported by mcp_server. Do not change keys/values.
_HARDCOPY_EXT = {
    "TIFF": "tif",
    "BMP": "bmp", "BMPCOLOR": "bmp",
    "PCX": "pcx", "PCXCOLOR": "pcx",
    "RLE": "rle",
}

# PCX-family is decoded to PNG client-side; the rest is written as-is.
# MCP-LIBRARY: imported by mcp_server. Do not change set membership.
_HARDCOPY_PNG_FORMATS = {"PCX", "PCXCOLOR"}


# MCP-LIBRARY: imported by mcp_server. Do not change signature.
def pcx_bytes_to_png(pcx_bytes: bytes, png_path: str):
    """Decode a PCX byte stream and save as PNG. Pillow handles both
    1-bit/4-bit/8-bit and 24-bit PCX variants the TDS784A emits."""
    try:
        from PIL import Image
    except ImportError:
        print("ERROR: Pillow is required to convert PCX to PNG. "
              "Run: uv sync   (after the project pyproject.toml lists 'pillow').",
              file=sys.stderr)
        sys.exit(2)
    import io
    img = Image.open(io.BytesIO(pcx_bytes))
    img.load()
    img.save(png_path, format="PNG")


async def run_hardcopy(args):
    """HARDCOPY sequence per the TDS784 programmer manual:
       set port=GPIB, format, layout; HARDCOPY START; read binary stream
       (the scope holds NRFD until the bitmap is ready, so no BUSY? poll)."""
    capture_time = datetime.now()
    uri = f"ws://{args.host}/ws"
    fmt = args.hardcopy_format
    setup_cmds = [
        "HARDCOPY:PORT GPIB",
        f"HARDCOPY:FORMAT {fmt}",
        f"HARDCOPY:LAYOUT {args.hardcopy_layout}",
        f"HARDCOPY:PALETTE {args.hardcopy_palette}",
    ]
    # Hardcopy can take several seconds (bitmap render + GPIB transfer of
    # ~30-150 KiB). Override the per-byte timeout generously.
    read_timeout = max(args.timeout, 20000)

    async with websockets.connect(uri) as ws:
        for cmd in setup_cmds:
            meta, _ = await one_shot(ws, "write", cmd, args.addr, args.timeout)
            if not meta.get("ok"):
                print(f"setup FAIL: {cmd} -> {meta.get('error')}")
                sys.exit(1)
        # HARDCOPY START triggers the scope; it then becomes the talker.
        meta, _ = await one_shot(ws, "write", "HARDCOPY START", args.addr, args.timeout)
        if not meta.get("ok"):
            print(f"FAIL: HARDCOPY START -> {meta.get('error')}")
            sys.exit(1)

        t0 = time.perf_counter()
        meta, payload = await one_shot(ws, "binary_read", "", args.addr, read_timeout)
        dt = (time.perf_counter() - t0) * 1000.0

    if not meta.get("ok") or payload is None:
        print(f"FAIL: hardcopy read: {meta.get('error')}")
        sys.exit(1)

    if fmt in _HARDCOPY_PNG_FORMATS:
        path = f"{iso_stamp(capture_time)}_{args.name}.png"
        pcx_bytes_to_png(payload, path)
        print(f"OK  hardcopy {fmt} -> PNG  {len(payload)} bytes in {dt:.1f} ms -> {path}")
    else:
        ext = _HARDCOPY_EXT.get(fmt, fmt.lower())
        path = f"{iso_stamp(capture_time)}_{args.name}.{ext}"
        with open(path, "wb") as f:
            f.write(payload)
        print(f"OK  hardcopy {fmt}  {len(payload)} bytes in {dt:.1f} ms -> {path}")


async def run_waveform(args):
    want_preamble = "csv" in args.formats
    want_metadata = "csv" in args.formats
    uri = f"ws://{args.host}/ws"
    capture_time = datetime.now()
    captures = []
    metadata = {}
    async with websockets.connect(uri) as ws:
        if want_metadata:
            metadata = await collect_metadata(ws, args, args.channels, capture_time)
        for ch in args.channels:
            cap = await capture_channel(ws, ch, args, want_preamble)
            if cap is None:
                sys.exit(1)
            captures.append(cap)

    base = f"{iso_stamp(capture_time)}_{args.name}"

    if "bin" in args.formats:
        for cap in captures:
            path = f"{base}_{cap['channel'].lower()}.bin"
            data = encode_samples_bytes(cap["samples"], args.width)
            with open(path, "wb") as f:
                f.write(data)
            print(f"saved {len(data)} bytes ({len(cap['samples'])} samples) to {path}")

    if "csv" in args.formats:
        write_multi_csv(f"{base}.csv", captures, metadata)


def main():
    args = parse_args(sys.argv[1:])
    try:
        if args.default_addr is not None:
            asyncio.run(run_set_default_addr(args))
        elif args.waveform:
            asyncio.run(run_waveform(args))
        elif args.hardcopy:
            asyncio.run(run_hardcopy(args))
        else:
            asyncio.run(run_simple(args))
    except (TimeoutError, asyncio.TimeoutError, ConnectionError, OSError) as e:
        # ConnectionError covers refused/reset; OSError covers DNS/route failures;
        # TimeoutError covers websockets' "timed out during opening handshake".
        print(f"\nERROR: cannot reach AR-488-ESP32 at ws://{args.host}/ws",
              file=sys.stderr)
        print(f"  ({type(e).__name__}: {e})", file=sys.stderr)
        print("Check: ESP32 powered on, IP shown on its OLED matches "
              f"'{args.host}', and you're on the same network.",
              file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
