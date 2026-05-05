"""Tests for tektool/flash.py against a mock transport.

Captures every memory_read / memory_write call so we can assert that
the byte sequences match the upstream flash.c (Intel command codes
0x90, 0xFF, 0x40, 0xD0, 0x20, 0xA7, 0x30 etc.) and the address
masking (flash_command -> base & ~0x1ffff).
"""

from __future__ import annotations

import struct
from collections import deque

import pytest

from host_software.tektool import flash as flashmod
from host_software.tektool.flash import (
    FAMILIES, VEN_DEV_28F016SA, VEN_DEV_28F010_AMD, VEN_DEV_28F008SA,
    FlashError,
)


class MockTransport:
    """Records every memory_read/memory_write and returns canned replies."""

    def __init__(self):
        self.events: list[tuple[str, int, bytes | int]] = []
        self.read_replies: deque[bytes] = deque()

    def queue_read(self, body: bytes) -> None:
        self.read_replies.append(body)

    async def memory_read(self, addr: int, length: int, *, timeout_ms=None) -> bytes:
        self.events.append(("read", addr, length))
        if not self.read_replies:
            return bytes(length)            # default: zero-filled
        return self.read_replies.popleft()

    async def memory_write(self, addr: int, data: bytes, *, timeout_ms=None) -> None:
        self.events.append(("write", addr, bytes(data)))

    # The flash module uses asyncio.sleep + logger; nothing else to mock.


# ---------------------------------------------------------------------------
# Helpers.

def _writes(events):
    return [(addr, data) for kind, addr, data in events if kind == "write"]


def _reads(events):
    return [(addr, length) for kind, addr, length in events if kind == "read"]


# ---------------------------------------------------------------------------
# flash_command address masking + replicated cmd byte.

@pytest.mark.asyncio
async def test_flash_command_masks_to_128k_block():
    t = MockTransport()
    await flashmod.flash_command(t, 0x1012345, 0x90)
    # base & ~0x1FFFF -> 0x1000000
    assert _writes(t.events) == [(0x1000000, b"\x90\x90\x90\x90")]


@pytest.mark.asyncio
async def test_flash_command_8bit_masks_to_64k_block():
    t = MockTransport()
    await flashmod.flash_command_8bit(t, 0x1012345, 0x20)
    # base & ~0xFFFF -> 0x1010000
    assert _writes(t.events) == [(0x1010000, b"\x20\x20\x20\x20")]


# ---------------------------------------------------------------------------
# flash_identify — happy path for 28F016SA.

@pytest.mark.asyncio
async def test_flash_identify_28F016SA():
    t = MockTransport()
    # The C source's flash_identify does:
    #     Ven_Dev_ID = ((Device_ID >> 8) & 0xFF) | (Vendor_ID & 0xFF00)
    # where Vendor_ID/Device_ID are LE-decoded uint32_ts. For 28F016SA
    # the upstream comments give Vendor_ID=0x89008900, Device_ID=0xa066a066,
    # which produces Ven_Dev_ID = 0xA0 | 0x8900 = 0x89A0.
    t.queue_read(struct.pack("<I", 0x89008900))   # vendor
    t.queue_read(struct.pack("<I", 0xA066A066))   # device

    ven_dev = await flashmod.flash_identify(t, 0x1000000)
    assert ven_dev == VEN_DEV_28F016SA

    writes = _writes(t.events)
    # First: 0x90 (read ID), at base. Last two: 0xFF resets.
    assert writes[0] == (0x1000000, b"\x90\x90\x90\x90")
    assert writes[-2:] == [
        (0x1000000, b"\xFF\xFF\xFF\xFF"),
        (0x1000000, b"\xFF\xFF\xFF\xFF"),
    ]
    # Reads at base and base+4.
    reads = _reads(t.events)
    assert reads[:2] == [(0x1000000, 4), (0x1000004, 4)]


@pytest.mark.asyncio
async def test_flash_identify_unknown_chip_raises():
    t = MockTransport()
    t.queue_read(struct.pack("<I", 0x00120012))  # unknown vendor
    t.queue_read(struct.pack("<I", 0x00340034))
    with pytest.raises(FlashError):
        await flashmod.flash_identify(t, 0x1000000)


@pytest.mark.asyncio
async def test_flash_identify_bad_base_raises():
    t = MockTransport()
    with pytest.raises(FlashError):
        await flashmod.flash_identify(t, 0x2000000)


# ---------------------------------------------------------------------------
# flash_program — chip-specific dispatch.

@pytest.mark.asyncio
async def test_flash_program_28F016SA_first_addr():
    t = MockTransport()
    await flashmod.flash_program(
        t, 0x1000000, 0xCAFEBABE, FAMILIES[VEN_DEV_28F016SA],
    )
    writes = _writes(t.events)
    # At base==0x1000000 the chip-specific path issues 0x40 first.
    assert writes[0] == (0x1000000, b"\x40\x40\x40\x40")
    # Then writes the {0x40404040, data} pair at base-4.
    addr, data = writes[1]
    assert addr == 0x1000000 - 0x4
    assert data == struct.pack("<II", 0x40404040, 0xCAFEBABE)


@pytest.mark.asyncio
async def test_flash_program_28F016SA_subsequent_addr():
    t = MockTransport()
    await flashmod.flash_program(
        t, 0x1000004, 0x12345678, FAMILIES[VEN_DEV_28F016SA],
    )
    writes = _writes(t.events)
    # No 0x40 prefix; just one write at base-4.
    assert len(writes) == 1
    addr, data = writes[0]
    assert addr == 0x1000004 - 0x4
    assert data == struct.pack("<II", 0x40404040, 0x12345678)


# ---------------------------------------------------------------------------
# flash_erase variants — confirm the command-byte sequence matches flash.c.

@pytest.mark.asyncio
async def test_erase_28F016SA_command_sequence():
    t = MockTransport()
    # SR poll uses mask (0x0080 << 16) | 0x0080 = 0x00800080. Queue an
    # SR read that satisfies it on the first poll so the function
    # completes its happy path.
    t.queue_read(struct.pack(">I", 0x00800080))
    await flashmod.flash_erase_28F016SA(t, 0x1000000)
    writes = _writes(t.events)
    cmd_bytes = [w[1][0] for w in writes if w[0] == 0x1000000]
    # 0xA7 (erase setup), 0xD0 (confirm), then 0xFF (reset) at the end.
    assert cmd_bytes[0] == 0xA7
    assert cmd_bytes[1] == 0xD0
    assert cmd_bytes[-1] == 0xFF


@pytest.mark.asyncio
async def test_erase_28F016SA_polls_until_done():
    t = MockTransport()
    # Inject a SR read that satisfies the mask 0x0080 on the first poll.
    sr_match = struct.pack(">I", 0x00800080)
    t.queue_read(sr_match)
    await flashmod.flash_erase_28F016SA(t, 0x1000000)
    # After success, the finally: clause issues 0xFF reset.
    last = _writes(t.events)[-1]
    assert last == (0x1000000, b"\xFF\xFF\xFF\xFF")


@pytest.mark.asyncio
async def test_flash_program_unsupported_family_raises():
    t = MockTransport()
    bogus = type(FAMILIES[VEN_DEV_28F016SA])(
        name="BOGUS", ven_dev_id=0xDEAD, size=0, devices_stacked=0,
    )
    with pytest.raises(FlashError):
        await flashmod.flash_program(t, 0x1000000, 0, bogus)
