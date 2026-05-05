"""Direct port of unified_tektool's flash.c + 28F0x0_flash.c.

Function names, control flow and Intel/AMD flash command codes mirror
the C source so anyone cross-referencing the two sees the equivalence.
The only behavioural change is structural error reporting via Python
exceptions (FlashError) instead of -1 return codes + goto out.

Entry points:
  flash_identify(t, base) -> int (Ven_Dev_ID, 16-bit)
  flash_program(t, base, data_u32, family)
  flash_erase(t, base, family)
  zero_fill(t, base, family)
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time
from dataclasses import dataclass

from .transport import TektoolError, TektoolSession

log = logging.getLogger("tektool.flash")


# ---------------------------------------------------------------------------
# Flash chip identifiers (Ven_Dev_ID, 16-bit, matching flash.c).

VEN_DEV_28F010_AMD   = 0x01A7
VEN_DEV_28F020_AMD   = 0x012A
VEN_DEV_28F010_INTEL = 0x89B4
VEN_DEV_28F020_INTEL = 0x89BD
VEN_DEV_28F016SA     = 0x89A0
VEN_DEV_28F008SA     = 0x89A2
VEN_DEV_28F160S5     = 0xB0D0


_28F010_size = 0x20000   # 128 KiB per device, three devices stacked = 0x60000
_28F020_size = 0x40000   # 256 KiB per device, three devices stacked = 0xC0000


# Flash command codes used by the scope's service-mode firmware.
CMD_READ_ID    = 0x90
CMD_RESET      = 0xFF
CMD_PROGRAM    = 0x40
CMD_ERASE_SETUP_28F008SA = 0x20    # block-erase, also confirm
CMD_ERASE_SETUP_28F160S5 = 0x30
CMD_ERASE_SETUP_28F016SA = 0xA7
CMD_ERASE_CONFIRM        = 0xD0
CMD_READ_SR              = 0x70


@dataclass
class FlashFamily:
    name: str
    ven_dev_id: int
    size: int                # total bytes per device
    devices_stacked: int     # 3 for 28F010/28F020 stacks, 1 for the others


FAMILIES: dict[int, FlashFamily] = {
    VEN_DEV_28F010_AMD:   FlashFamily("AMD 28F010",    VEN_DEV_28F010_AMD,   _28F010_size, 3),
    VEN_DEV_28F010_INTEL: FlashFamily("Intel 28F010",  VEN_DEV_28F010_INTEL, _28F010_size, 3),
    VEN_DEV_28F020_AMD:   FlashFamily("AMD 28F020",    VEN_DEV_28F020_AMD,   _28F020_size, 3),
    VEN_DEV_28F020_INTEL: FlashFamily("Intel 28F020",  VEN_DEV_28F020_INTEL, _28F020_size, 3),
    # On TDS5xx/7xx these SA chips are stacked to fill a 4 MB region:
    # 28F008SA (1 MB) × 4, 28F016SA (2 MB) × 2, 28F160S5 (2 MB) × 2.
    VEN_DEV_28F016SA:     FlashFamily("Intel 28F016SA", VEN_DEV_28F016SA,    0x200000,    2),
    VEN_DEV_28F008SA:     FlashFamily("Intel 28F008SA", VEN_DEV_28F008SA,    0x100000,    4),
    VEN_DEV_28F160S5:     FlashFamily("Intel 28F160S5", VEN_DEV_28F160S5,    0x200000,    2),
}


class FlashError(TektoolError):
    """Raised on flash-level protocol/abort failures."""


def _be32_to_cpu(b: bytes) -> int:
    return struct.unpack(">I", b)[0]


# ---------------------------------------------------------------------------
# Helpers: flash_command, flash_command_8bit.
#
# flash_command:        write cmd*0x01010101 to (base & ~0x1ffff)
# flash_command_8bit:   write cmd*0x01010101 to (base & ~0xffff) — used only
#                       on 28F008SA which is byte-organised.

async def flash_command(t: TektoolSession, base: int, cmd: int) -> None:
    aligned = base & ~0x1FFFF
    buf = bytes([cmd, cmd, cmd, cmd])
    await t.memory_write(aligned, buf)


async def flash_command_8bit(t: TektoolSession, base: int, cmd: int) -> None:
    aligned = base & ~0xFFFF
    buf = bytes([cmd, cmd, cmd, cmd])
    await t.memory_write(aligned, buf)


# ---------------------------------------------------------------------------
# Identify.

async def flash_identify(t: TektoolSession, base: int) -> int:
    """Read vendor/device ID. Returns Ven_Dev_ID (16-bit). Raises FlashError
    if the chip is unknown or `base` isn't 0x1000000."""
    if (base & 0xF000000) != 0x1000000:
        raise FlashError(f"identify: bad base {base:#x} (only 0x1000000 supported)")

    await flash_command(t, base, CMD_READ_ID)

    # Read 4 bytes at base for the vendor ID dword, then 4 bytes at base+4
    # for the device ID dword. C source treats each as little-endian dword
    # in memory; we pull as raw bytes and interpret the high byte of the
    # vendor and the high byte of the device per the C bit-shuffle:
    #     Ven_Dev_ID = ((Device_ID >> 8) & 0xFF) | (Vendor_ID & 0xFF00)
    # where Vendor_ID/Device_ID are uint32_t little-endian dwords.
    try:
        v_buf = await t.memory_read(base,     4)
        await asyncio.sleep(10e-6)             # mirror C usleep(10)
        d_buf = await t.memory_read(base + 4, 4)
    finally:
        # The 0x90 (Read ID) latch must ALWAYS be cleared with 0xFF
        # before we leave this function, even if the reads above failed.
        # Otherwise the chip stays in ID mode and subsequent memory_read
        # of actual data returns vendor/device bytes forever.
        # Mirror upstream flash.c: CMD_RESET, CMD_RESET.
        try:
            await flash_command(t, base, CMD_RESET)
            await flash_command(t, base, CMD_RESET)
        except TektoolError:
            log.warning("flash_identify: CMD_RESET failed during cleanup — "
                        "chip may still be in Read-ID mode")

    vendor_id = struct.unpack("<I", v_buf)[0]
    device_id = struct.unpack("<I", d_buf)[0]
    ven_dev_id = ((device_id >> 8) & 0xFF) | (vendor_id & 0xFF00)

    log.info("flash_identify: vendor=%#010x device=%#010x -> ven_dev=%#06x",
             vendor_id, device_id, ven_dev_id)

    if ven_dev_id not in FAMILIES:
        raise FlashError(
            f"identify: unknown chip ven_dev={ven_dev_id:#06x} "
            f"(vendor={vendor_id:#010x} device={device_id:#010x})"
        )
    return ven_dev_id


# ---------------------------------------------------------------------------
# Status-register polling.

async def flash_wait_sr_write(
    t: TektoolSession, base: int, mask: int, result: int, tries: int,
) -> None:
    """Spin until (sr & mask) == result, up to `tries` polls. Raises on timeout.

    Currently unused by the C upstream's "faster algorithm" path
    (commented out), kept here for symmetry with flash.c."""
    _mask = (mask << 16) | mask
    _result = (result << 16) | result
    while tries > 0:
        buf = await t.memory_read(base, 4)
        if (_be32_to_cpu(buf) & _mask) == _result:
            return
        tries -= 1
    raise FlashError(f"flash_wait_sr_write timeout @ {base:#x} mask={mask:#x}")


async def flash_wait_sr_erase(
    t: TektoolSession, base: int, mask: int, result: int, tries: int,
) -> None:
    """Erase status poll. usleep(200ms) between polls; logs SR + elapsed."""
    _mask = (mask << 16) | mask
    _result = (result << 16) | result
    start = time.monotonic()
    while tries > 0:
        buf = await t.memory_read(base, 4)
        sr = _be32_to_cpu(buf)
        log.info("SR: %#010x %4ds", sr, int(time.monotonic() - start))
        if (sr & _mask) == _result:
            log.info("erasing successful")
            return
        await asyncio.sleep(0.2)
        tries -= 1
    raise FlashError(f"flash_wait_sr_erase timeout @ {base:#x} mask={mask:#x}")


# ---------------------------------------------------------------------------
# Programming — variants 28F008SA / 28F016SA / 28F160S5.
#
# All three use the "faster algorithm": one memory_write places
# {0x40404040, data} at base-4 (so the program-confirm byte ends up at
# `base` and the data follows). At the very first call (base==0x1000000)
# we additionally issue a flash_command(base, 0x40) since base-4 maps
# outside the chip's CE.

async def _faster_program(
    t: TektoolSession, base: int, data_u32: int, *, first_addr: int = 0x1000000,
) -> None:
    if base == first_addr:
        await flash_command(t, base, CMD_PROGRAM)
    payload = struct.pack("<II", 0x40404040, data_u32)
    await t.memory_write(base - 0x4, payload)


async def flash_program_28F008SA(t: TektoolSession, base: int, data_u32: int) -> None:
    await _faster_program(t, base, data_u32)


async def flash_program_28F016SA(t: TektoolSession, base: int, data_u32: int) -> None:
    await _faster_program(t, base, data_u32)


async def flash_program_28F160S5(t: TektoolSession, base: int, data_u32: int) -> None:
    await _faster_program(t, base, data_u32)


async def flash_program_28F0x0(
    t: TektoolSession, base: int, data_u32: int, flash_size: int,
) -> None:
    """28F010/020 stacked-three program. Reset previous device's CE before
    crossing into the next when `base` matches a stack boundary."""
    if base == 0x1000000:
        await flash_command(t, base, CMD_PROGRAM)
        await t.memory_write(base, struct.pack("<I", data_u32))
    elif base == (0x1000000 + flash_size):
        await flash_command(t, base - flash_size, CMD_RESET)
        await flash_command(t, base, CMD_PROGRAM)
        await t.memory_write(base, struct.pack("<I", data_u32))
    elif base == (0x1000000 + flash_size * 2):
        await flash_command(t, base - flash_size, CMD_RESET)
        await flash_command(t, base, CMD_PROGRAM)
        await t.memory_write(base, struct.pack("<I", data_u32))
    else:
        payload = struct.pack("<II", 0x40404040, data_u32)
        await t.memory_write(base - 0x4, payload)


async def flash_program(
    t: TektoolSession, base: int, data_u32: int, family: FlashFamily,
) -> None:
    """Dispatch one 4-byte program write to the chip-specific variant."""
    if (base & 0xF000000) != 0x1000000:
        raise FlashError(f"program: bad base {base:#x}")
    fid = family.ven_dev_id
    if fid == VEN_DEV_28F016SA:
        await flash_program_28F016SA(t, base, data_u32)
    elif fid == VEN_DEV_28F008SA:
        await flash_program_28F008SA(t, base, data_u32)
    elif fid == VEN_DEV_28F160S5:
        await flash_program_28F160S5(t, base, data_u32)
    elif fid in (VEN_DEV_28F010_AMD, VEN_DEV_28F010_INTEL):
        await flash_program_28F0x0(t, base, data_u32, _28F010_size)
    elif fid in (VEN_DEV_28F020_AMD, VEN_DEV_28F020_INTEL):
        await flash_program_28F0x0(t, base, data_u32, _28F020_size)
    else:
        raise FlashError(f"program: unsupported family {family.name}")


# ---------------------------------------------------------------------------
# Erase — variants.

async def flash_erase_28F160S5(t: TektoolSession, base: int) -> None:
    try:
        await flash_command(t, base, CMD_ERASE_SETUP_28F160S5)
        await asyncio.sleep(10e-6)
        await flash_command(t, base, CMD_ERASE_CONFIRM)
        await asyncio.sleep(10e-6)
        await flash_wait_sr_erase(t, base, 0x0080, 0x0080, 1000)
    finally:
        await flash_command(t, base, CMD_RESET)


async def flash_erase_28F016SA(t: TektoolSession, base: int) -> None:
    try:
        await flash_command(t, base, CMD_ERASE_SETUP_28F016SA)
        await asyncio.sleep(10e-6)
        await flash_command(t, base, CMD_ERASE_CONFIRM)
        await asyncio.sleep(10e-6)
        await flash_wait_sr_erase(t, base, 0x0080, 0x0080, 1000)
    finally:
        await flash_command(t, base, CMD_RESET)


async def flash_erase_28F008SA(t: TektoolSession, base: int) -> None:
    """16 blocks of 64 KiB each, erase-confirmed individually."""
    try:
        block_count = 0
        while True:
            target = base | (block_count * 4)
            await flash_command_8bit(t, target, CMD_ERASE_SETUP_28F008SA)
            await asyncio.sleep(10e-6)
            await flash_command_8bit(t, target, CMD_ERASE_CONFIRM)
            await asyncio.sleep(10e-6)
            await flash_wait_sr_erase(t, target, 0x8080, 0x8080, 1000)
            if block_count == 0xF0000:
                break
            block_count += 0x10000
    finally:
        await flash_command(t, base, CMD_RESET)


async def flash_erase_28F0x0(
    t: TektoolSession, base: int, flash_size: int, tries: int,
) -> None:
    """28F010/28F020 bulk-erase + FF-verify, with safety re-erase passes.

    Direct port of 28F0x0_flash.c::flash_erase_28F0x0. The verify+safe-
    erase logic is delicate — DO NOT alter the byte sequences here, the
    upstream comment warns 'else flash will be unuseable/destroyed with
    overerasing'.
    """
    try_ = tries
    safe_erase = 0
    fail_addr = -1

    while True:
        # bulk erase
        buf = struct.pack("<I", 0x20202020 & safe_erase)
        await t.memory_write(base, buf)
        await asyncio.sleep(10e-6)
        # bulk erase confirm
        await t.memory_write(base, buf)
        await asyncio.sleep(10e-3)
        # erase verify command
        buf = struct.pack("<I", 0xA0A0A0A0 & safe_erase)
        await t.memory_write(base, buf)
        await asyncio.sleep(8e-6)
        # reset
        await flash_command(t, base, CMD_RESET)
        await flash_command(t, base, CMD_RESET)
        await asyncio.sleep(100e-3)

        size = base + flash_size - (fail_addr if fail_addr != -1 else base)
        addr = fail_addr if fail_addr != -1 else base
        fail_addr, safe_erase = await _flash_FF_verify_fast(
            t, addr, size, try_,
        )
        if fail_addr == -1:
            break
        log.info("            tries:%04d  addr:%08x", tries - try_, fail_addr)
        try_ -= 1
        if try_ <= 0:
            raise FlashError(f"flash_erase_28F0x0: gave up at {fail_addr:#x}")

    # Safety re-erase passes — count is (tries - try_)/4, copied from C.
    safe_erase = (tries - try_) // 4
    while safe_erase:
        buf = struct.pack("<I", 0x20202020)
        await t.memory_write(base, buf)
        await asyncio.sleep(10e-6)
        await t.memory_write(base, buf)
        await asyncio.sleep(10e-3)
        buf = struct.pack("<I", 0xA0A0A0A0)
        await t.memory_write(base, buf)
        await asyncio.sleep(8e-6)
        await flash_command(t, base, CMD_RESET)
        await flash_command(t, base, CMD_RESET)
        await asyncio.sleep(100e-3)
        log.info(" %2d", safe_erase)
        safe_erase -= 1


async def _flash_FF_verify_fast(
    t: TektoolSession, base: int, size: int, _try: int,
) -> tuple[int, int]:
    """Read base..base+size in 512-byte chunks; return (fail_addr, safe_erase).

    fail_addr == -1  =>  all bytes are 0xFF.
    safe_erase encodes which sub-byte position triggered the first miss
    (matches the C bitmask logic verbatim).
    """
    fail_addr = -1
    safe_erase = 0
    addr = base
    while base + size - addr > 0:
        n = min(512, base + size - addr)
        buf = await t.memory_read(addr, n)
        i = 0
        while i + 4 <= n:
            if buf[i] != 0xFF:
                fail_addr = addr
                safe_erase |= 0x000000FF
            if buf[i + 1] != 0xFF:
                fail_addr = addr
                safe_erase |= 0x0000FF00
            if buf[i + 2] != 0xFF:
                fail_addr = addr
                safe_erase |= 0x00FF0000
            if buf[i + 3] != 0xFF:
                fail_addr = addr
                safe_erase |= 0xFF000000
                # C uses goto out1 here — bail early on this lane.
                return fail_addr, safe_erase
            i += 4
        addr += n
    return fail_addr, safe_erase


async def flash_erase_28F010(t: TektoolSession, base: int) -> None:
    """Erase a 28F010 stack of three (each _28F010_size apart)."""
    await flash_erase_28F0x0(t, base, _28F010_size, 200)
    log.info("1/3 flash successful erase")
    await flash_erase_28F0x0(t, base + _28F010_size, _28F010_size, 200)
    log.info("2/3 flash successful erase")
    await flash_erase_28F0x0(t, base + (_28F010_size * 2), _28F010_size, 200)
    log.info("3/3 flash successful erase")


async def flash_erase_28F020(t: TektoolSession, base: int) -> None:
    """Erase a 28F020 stack of three."""
    await flash_erase_28F0x0(t, base, _28F020_size, 200)
    log.info("1/3 flash successful erase")
    await flash_erase_28F0x0(t, base + _28F020_size, _28F020_size, 200)
    log.info("2/3 flash successful erase")
    await flash_erase_28F0x0(t, base + (_28F020_size * 2), _28F020_size, 200)
    log.info("3/3 flash successful erase")


async def flash_erase(
    t: TektoolSession, base: int, family: FlashFamily | None = None,
) -> None:
    """Top-level erase. If `family` is None, identify first."""
    if base != 0x1000000:
        raise FlashError(f"erase: bad base {base:#x} (only 0x1000000 supported)")
    if family is None:
        ven_dev = await flash_identify(t, base)
        family = FAMILIES[ven_dev]
        log.info("Flash erase process run on %s", family.name)

    fid = family.ven_dev_id
    if fid == VEN_DEV_28F016SA:
        await flash_erase_28F016SA(t, base)
    elif fid == VEN_DEV_28F008SA:
        await flash_erase_28F008SA(t, base)
    elif fid == VEN_DEV_28F160S5:
        await flash_erase_28F160S5(t, base)
    elif fid in (VEN_DEV_28F010_AMD, VEN_DEV_28F010_INTEL):
        await flash_erase_28F010(t, base)
    elif fid in (VEN_DEV_28F020_AMD, VEN_DEV_28F020_INTEL):
        await flash_erase_28F020(t, base)
    else:
        raise FlashError(f"erase: unsupported family {family.name}")


# ---------------------------------------------------------------------------
# Zero-fill (28F010/28F020 only, mirrors flash.c::zero_fill).

async def flash_00_program(
    t: TektoolSession, base: int, flash_size: int, tries: int,
) -> None:
    """Fill `flash_size` bytes from `base` with zero, in 4-byte writes.
    Mirrors 28F0x0_flash.c::flash_00_program."""
    addr_count = 0
    start = time.monotonic()
    while True:
        try:
            await flash_program_28F0x0(t, base + addr_count, 0x00000000, flash_size)
        except TektoolError:
            log.warning("addr: %#010x", base + addr_count)
            log.warning("tries: %04d", tries)
            tries -= 1
            if tries == 0:
                raise FlashError("flash_00_program: out of tries")
            continue

        addr_count += 4
        if (addr_count & 0xFF) == 0:
            log.info("%06x/%06x, %3d%% %4ds",
                     addr_count, flash_size,
                     (addr_count * 100) // flash_size,
                     int(time.monotonic() - start))
        if (addr_count & 0xFFFFFF) == flash_size:
            break

    await flash_command(t, base, CMD_RESET)


async def zero_fill(
    t: TektoolSession, base: int, family: FlashFamily | None = None,
) -> None:
    """Pre-erase zero-fill — only valid on 28F010/28F020 stacks."""
    if (base & 0xF000000) != 0x1000000:
        raise FlashError(f"zero_fill: bad base {base:#x}")
    if family is None:
        ven_dev = await flash_identify(t, base)
        family = FAMILIES[ven_dev]
    fid = family.ven_dev_id
    if fid in (VEN_DEV_28F010_AMD, VEN_DEV_28F010_INTEL):
        await flash_00_program(t, base, 3 * _28F010_size, 10)
    elif fid in (VEN_DEV_28F020_AMD, VEN_DEV_28F020_INTEL):
        await flash_00_program(t, base, 3 * _28F020_size, 10)
    else:
        raise FlashError(f"zero_fill: unsupported family {family.name}")
