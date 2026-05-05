"""Round-trip tests for tektool/protocol.py.

Covers:
  - csum8 algebraic properties
  - pack_memory_read / pack_memory_write structural layout
  - parse_read_response / parse_write_response framing checks
  - Self-consistency: build a packet, validate csum8 across the bytes
"""

import struct

import pytest

from host_software.tektool import protocol


class TestCsum:
    def test_zero_buffer(self):
        assert protocol.csum8(b"") == 0
        assert protocol.csum8(bytes(100)) == 0

    def test_overflow_wraps(self):
        # Sum of 256 0x01 bytes = 256, & 0xFF = 0.
        assert protocol.csum8(bytes([0x01]) * 256) == 0

    def test_known_value(self):
        assert protocol.csum8(bytes([0x10, 0x20, 0x30, 0x40])) == 0xA0


class TestPackMemoryRead:
    def test_basic_layout(self):
        pkt = protocol.pack_memory_read(0x1000000, 0x100)
        assert pkt[0:1] == b"m"
        # cmd_hdr.len = 8 (just addr+len, no data)
        assert struct.unpack(">H", pkt[2:4])[0] == 8
        # addr + len fields, big-endian
        assert struct.unpack(">II", pkt[4:12]) == (0x1000000, 0x100)

    def test_csum_self_consistency(self):
        # The csum byte equals csum8 over the whole packet with that
        # field zeroed — matches build_csum() in tektool.c.
        pkt = protocol.pack_memory_read(0x12345678, 1024)
        rebuilt = bytearray(pkt)
        original_csum = rebuilt[1]
        rebuilt[1] = 0
        assert protocol.csum8(bytes(rebuilt)) == original_csum

    def test_invalid_addr_rejected(self):
        with pytest.raises(ValueError):
            protocol.pack_memory_read(0x1_00000000, 1)

    def test_zero_length_rejected(self):
        with pytest.raises(ValueError):
            protocol.pack_memory_read(0x1000000, 0)


class TestPackMemoryWrite:
    def test_basic_layout(self):
        data = bytes([0x90, 0x90, 0x90, 0x90])
        pkt = protocol.pack_memory_write(0x1000000, data)
        assert pkt[0:1] == b"M"
        # cmd_hdr.len = 8 (addr+len) + len(data)
        assert struct.unpack(">H", pkt[2:4])[0] == 8 + len(data)
        addr, length = struct.unpack(">II", pkt[4:12])
        assert addr == 0x1000000
        assert length == len(data)
        assert pkt[12:] == data

    def test_csum_consistency(self):
        data = bytes(range(64))
        pkt = protocol.pack_memory_write(0xDEAD_BEEF, data)
        rebuilt = bytearray(pkt)
        original = rebuilt[1]
        rebuilt[1] = 0
        assert protocol.csum8(bytes(rebuilt)) == original

    def test_max_payload_enforced(self):
        too_big = bytes(2000)
        with pytest.raises(ValueError):
            protocol.pack_memory_write(0x1000000, too_big)

    def test_empty_data_rejected(self):
        with pytest.raises(ValueError):
            protocol.pack_memory_write(0x1000000, b"")


class TestParseReadResponse:
    def _build(self, body: bytes) -> bytes:
        # Wire reply: '+', '=', csum, len_be16, body
        return b"+" + b"=" + b"\x00" + struct.pack(">H", len(body)) + body

    def test_round_trip(self):
        body = b"\x89\x89\x89\x89"
        out = protocol.parse_read_response(self._build(body), len(body))
        assert out == body

    def test_truncated(self):
        with pytest.raises(ValueError):
            protocol.parse_read_response(b"+=", expected_len=4)

    def test_missing_intermediate_ack(self):
        bad = b"X=" + b"\x00\x00\x04" + b"\x00\x00\x00\x00"
        with pytest.raises(ValueError):
            protocol.parse_read_response(bad, expected_len=4)

    def test_missing_header(self):
        bad = b"+!" + b"\x00\x00\x04" + b"\x00\x00\x00\x00"
        with pytest.raises(ValueError):
            protocol.parse_read_response(bad, expected_len=4)

    def test_length_mismatch(self):
        # Header says 8 bytes, requester asked for 4.
        body = bytes(8)
        wire = self._build(body)
        with pytest.raises(ValueError):
            protocol.parse_read_response(wire, expected_len=4)


class TestParseWriteResponse:
    def test_minimal_ok(self):
        wire = b"+=" + b"\x00\x00\x00"   # ack + header + len=0
        protocol.parse_write_response(wire)   # no exception

    def test_short(self):
        with pytest.raises(ValueError):
            protocol.parse_write_response(b"+=")
