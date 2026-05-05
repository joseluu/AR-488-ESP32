"""Binary packet codec for unified_tektool's GPIB service-mode protocol.

Wire format (all multi-byte fields big-endian) is taken from
matt1187/unified_tektool sourcefile/tektool.c:

    struct cmd_hdr  { uint8_t cmd; uint8_t csum; uint16_t len; };
    memory_read_cmd  = cmd_hdr + uint32_t addr + uint32_t length
    memory_write_cmd = cmd_hdr + uint32_t addr + uint32_t length + data[length]

The `cmd` byte is 'm' (0x6D) for read, 'M' (0x4D) for write.
The `len` field counts the *payload* bytes after the 4-byte header.
The `csum` is an 8-bit sum across the whole packet, computed with the
csum field set to 0.
"""

from __future__ import annotations

import struct

CMD_MEMORY_READ = ord("m")   # 0x6D
CMD_MEMORY_WRITE = ord("M")  # 0x4D

# Size cap matching the firmware's GpibRequest.payload buffer (1200).
# unified_tektool's largest M-packet is 12 hdr + 1024 data = 1036.
MAX_RAW_PAYLOAD = 1200


def csum8(data: bytes) -> int:
    """8-bit additive checksum across the buffer."""
    return sum(data) & 0xFF


def _pack_with_csum(cmd: int, payload: bytes) -> bytes:
    """Build cmd_hdr + payload, fill the csum field. `len` = len(payload)."""
    if len(payload) > 0xFFFF:
        raise ValueError(f"payload too large: {len(payload)} bytes")
    # csum=0 placeholder, then patch.
    pkt = bytearray(struct.pack(">BBH", cmd, 0, len(payload)))
    pkt += payload
    pkt[1] = csum8(pkt)
    if len(pkt) > MAX_RAW_PAYLOAD:
        raise ValueError(
            f"packet {len(pkt)} bytes exceeds firmware cap {MAX_RAW_PAYLOAD}"
        )
    return bytes(pkt)


def pack_memory_read(addr: int, length: int) -> bytes:
    """Build an 'm' (memory read) request packet."""
    if not 0 <= addr <= 0xFFFFFFFF:
        raise ValueError(f"addr out of u32 range: {addr:#x}")
    if not 0 < length <= 0xFFFFFFFF:
        raise ValueError(f"length out of range: {length}")
    payload = struct.pack(">II", addr, length)
    return _pack_with_csum(CMD_MEMORY_READ, payload)


def pack_memory_write(addr: int, data: bytes) -> bytes:
    """Build an 'M' (memory write) request packet for `data` at `addr`."""
    if not 0 <= addr <= 0xFFFFFFFF:
        raise ValueError(f"addr out of u32 range: {addr:#x}")
    if not data:
        raise ValueError("data must be non-empty")
    payload = struct.pack(">II", addr, len(data)) + bytes(data)
    return _pack_with_csum(CMD_MEMORY_WRITE, payload)


ACK_OK = b"+"


def pack_ack() -> bytes:
    """Single-byte '+' ack, sent by the host after each memory transaction."""
    return ACK_OK


def parse_read_response(buf: bytes, expected_len: int) -> bytes:
    """Parse a scope memory_read reply.

    The wire format (one EOI-terminated GPIB message) is:
        '+'        intermediate ack from scope
        '='        response cmd_hdr.cmd
        csum:u8    cmd_hdr.csum  (not verified — upstream C tool also skips it)
        len:u16-be cmd_hdr.len   (number of body bytes that follow)
        body[len]

    Returns the body bytes. Raises ValueError on any framing error.
    """
    if len(buf) < 5:
        raise ValueError(f"truncated read response: {len(buf)} bytes")
    if buf[0:1] != b"+":
        raise ValueError(f"expected '+' intermediate ack, got {buf[0:1]!r}")
    if buf[1:2] != b"=":
        raise ValueError(f"expected '=' header byte, got {buf[1:2]!r}")
    rlen = struct.unpack(">H", buf[3:5])[0]
    if rlen != expected_len:
        raise ValueError(
            f"length mismatch: requested {expected_len}, scope reported {rlen}"
        )
    body = buf[5 : 5 + rlen]
    if len(body) != rlen:
        raise ValueError(
            f"short body: header says {rlen} bytes, only got {len(body)}"
        )
    return body


def parse_write_response(buf: bytes) -> None:
    """Parse a scope memory_write reply.

    Format mirrors parse_read_response but with no body (cmd_hdr.len is
    typically 0). Raises ValueError on framing error; returns None on
    success.
    """
    if len(buf) < 5:
        raise ValueError(f"truncated write response: {len(buf)} bytes")
    if buf[0:1] != b"+":
        raise ValueError(f"expected '+' intermediate ack, got {buf[0:1]!r}")
    if buf[1:2] != b"=":
        raise ValueError(f"expected '=' header byte, got {buf[1:2]!r}")
