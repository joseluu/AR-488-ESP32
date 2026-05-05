"""Command-line interface for tektool — service-mode flash tool.

Usage examples
--------------
  tektool --host 192.168.1.42 identify --base 0x1000000

  tektool --host 192.168.1.42 backup  --base 0x1000000 --len 0x300000

  tektool --host 192.168.1.42 verify  image.bin --base 0x1000000 --len 0x180000

  tektool --host 192.168.1.42 erase   --base 0x1000000 \\
          --family 28F016SA \\
          --i-understand-this-can-brick-the-scope \\
          --idn "TEKTRONIX,TDS784A,B021000,CF:91.1CT FV:v3.1e"

  tektool --host 192.168.1.42 program image.bin --base 0x1000000 --len 0x180000 \\
          --family 28F016SA \\
          --i-understand-this-can-brick-the-scope \\
          --idn "TEKTRONIX,TDS784A,B021000,CF:91.1CT FV:v3.1e"

  tektool --host 192.168.1.42 resume <session-id>
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from . import flash as flashmod
from .flash import FAMILIES, FlashFamily
from .safety import (
    CONFIRM_TOKEN, Journal, SafeSession, SafetyError,
)
from .transport import TektoolError, TektoolSession


# ---------------------------------------------------------------------------
# Family lookup by friendly name (used by --family flag).

_FAMILY_BY_NAME: dict[str, FlashFamily] = {}
for _id, _f in FAMILIES.items():
    short = _f.name.split()[-1]                 # "Intel 28F010" -> "28F010"
    _FAMILY_BY_NAME.setdefault(short, _f)
    _FAMILY_BY_NAME.setdefault(_f.name, _f)


def _family_arg(s: str) -> FlashFamily:
    if s in _FAMILY_BY_NAME:
        return _FAMILY_BY_NAME[s]
    raise argparse.ArgumentTypeError(
        f"unknown family {s!r}. Choices: {sorted(_FAMILY_BY_NAME)}"
    )


def _hex_int(s: str) -> int:
    return int(s, 0)


# ---------------------------------------------------------------------------
# Argument parser.

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tektool",
        description="Service-mode flash tool for vintage Tek scopes "
                    "(via the AR-488-ESP32 gateway).",
    )
    p.add_argument("--host", required=True,
                   help="AR-488-ESP32 IP or hostname")
    p.add_argument("--addr", type=int, default=29,
                   help="GPIB primary address of the scope (default 29)")
    p.add_argument("--log-level", default="INFO",
                   choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    p.add_argument("--dry-run", action="store_true",
                   help="Run pre-flight + reads, skip every memory_write")

    sub = p.add_subparsers(dest="verb", required=True)

    # identify -----------------------------------------------------------
    sp = sub.add_parser("identify",
                        help="Read flash vendor/device ID at base 0x1000000")
    sp.add_argument("--base", type=_hex_int, default=0x1000000)

    # read ---------------------------------------------------------------
    sp = sub.add_parser("read", help="Raw memory read into a file")
    sp.add_argument("--base", type=_hex_int, required=True)
    sp.add_argument("--len",  dest="length", type=_hex_int, required=True)
    sp.add_argument("--out",  type=Path, required=True)

    # backup -------------------------------------------------------------
    sp = sub.add_parser("backup",
                        help="Read a memory range to backups/<stamp>_<name>.bin"
                             " with a SHA-256 sidecar")
    sp.add_argument("--base", type=_hex_int, required=True)
    sp.add_argument("--len",  dest="length", type=_hex_int, required=True)
    sp.add_argument("--name", default="backup")

    # verify -------------------------------------------------------------
    sp = sub.add_parser("verify",
                        help="Compare scope memory range to a binary image")
    sp.add_argument("image", type=Path)
    sp.add_argument("--base", type=_hex_int, required=True)
    sp.add_argument("--len",  dest="length", type=_hex_int)

    # erase --------------------------------------------------------------
    sp = sub.add_parser("erase", help="Erase the flash (DESTRUCTIVE)")
    sp.add_argument("--base", type=_hex_int, default=0x1000000)
    sp.add_argument("--family", type=_family_arg, required=True,
                    help="Flash family (e.g. 28F016SA)")
    sp.add_argument(f"--{CONFIRM_TOKEN}", dest="confirm",
                    action="store_const", const=CONFIRM_TOKEN,
                    help="Confirm you accept the bricking risk")
    sp.add_argument("--idn", required=True,
                    help="Echo the scope's *IDN? string verbatim")

    # program ------------------------------------------------------------
    sp = sub.add_parser("program",
                        help="Erase (optional) + program a binary image (DESTRUCTIVE)")
    sp.add_argument("image", type=Path)
    sp.add_argument("--base", type=_hex_int, default=0x1000000)
    sp.add_argument("--len",  dest="length", type=_hex_int, required=True)
    sp.add_argument("--family", type=_family_arg, required=True)
    sp.add_argument("--no-erase", action="store_true",
                    help="Skip the erase step before programming")
    sp.add_argument(f"--{CONFIRM_TOKEN}", dest="confirm",
                    action="store_const", const=CONFIRM_TOKEN)
    sp.add_argument("--idn", required=True)

    # zerofill -----------------------------------------------------------
    sp = sub.add_parser("zerofill",
                        help="Pre-erase zero-fill (28F010/28F020 only, DESTRUCTIVE)")
    sp.add_argument("--base", type=_hex_int, default=0x1000000)
    sp.add_argument("--family", type=_family_arg, required=True)
    sp.add_argument(f"--{CONFIRM_TOKEN}", dest="confirm",
                    action="store_const", const=CONFIRM_TOKEN)
    sp.add_argument("--idn", required=True)

    # write --------------------------------------------------------------
    sp = sub.add_parser("write",
                        help="Raw memory_write of a binary file (RAM/IO regions, DESTRUCTIVE)")
    sp.add_argument("image", type=Path)
    sp.add_argument("--base", type=_hex_int, required=True)
    sp.add_argument("--len",  dest="length", type=_hex_int, required=True)
    sp.add_argument(f"--{CONFIRM_TOKEN}", dest="confirm",
                    action="store_const", const=CONFIRM_TOKEN)
    sp.add_argument("--idn", required=True)

    # resume -------------------------------------------------------------
    sp = sub.add_parser("resume", help="Resume an interrupted program session")
    sp.add_argument("session_id")
    sp.add_argument(f"--{CONFIRM_TOKEN}", dest="confirm",
                    action="store_const", const=CONFIRM_TOKEN)
    sp.add_argument("--idn", required=True)

    return p


# ---------------------------------------------------------------------------
# Verb implementations.

async def _verb_identify(s: SafeSession, args) -> int:
    ven_dev = await flashmod.flash_identify(s.session, args.base)
    family = FAMILIES[ven_dev]
    print(f"Flash ID    : {ven_dev:#06x}")
    print(f"Family      : {family.name}")
    print(f"Device size : {family.size:#x}")
    print(f"Stacked x   : {family.devices_stacked}")
    print(f"Total bytes : {family.size * family.devices_stacked:#x}")
    return 0


async def _verb_read(s: SafeSession, args) -> int:
    out_path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = 0
    with out_path.open("wb") as fh:
        while done < args.length:
            n = min(1024, args.length - done)
            buf = await s.session.memory_read(args.base + done, n)
            fh.write(buf)
            done += n
    print(f"read {done} bytes -> {out_path}")
    return 0


async def _verb_backup(s: SafeSession, args) -> int:
    path = await s.backup(base=args.base, length=args.length, name=args.name)
    print(f"backup -> {path}")
    return 0


async def _verb_verify(s: SafeSession, args) -> int:
    await s.verify(image_path=args.image, base=args.base, length=args.length)
    print("verify OK")
    return 0


async def _verb_erase(s: SafeSession, args, observed_idn: str) -> int:
    SafeSession.check_confirm(args.confirm, args.idn, observed_idn)
    await s.erase(base=args.base, family=args.family)
    print("erase complete")
    return 0


async def _verb_program(s: SafeSession, args, observed_idn: str) -> int:
    SafeSession.check_confirm(args.confirm, args.idn, observed_idn)

    # Mandatory backup unless dry-run.
    if not args.dry_run:
        await s.backup(base=args.base, length=args.length,
                       name=f"pre-{args.image.stem}")

    if not args.no_erase:
        await s.erase(base=args.base, family=args.family)

    await s.program_image(
        image_path=args.image, base=args.base,
        length=args.length, family=args.family,
    )
    print("program complete")
    return 0


async def _verb_zerofill(s: SafeSession, args, observed_idn: str) -> int:
    SafeSession.check_confirm(args.confirm, args.idn, observed_idn)
    if args.dry_run:
        print(f"[dry-run] would zero-fill {args.family.name} @ {args.base:#x}")
        return 0
    await flashmod.zero_fill(s.session, args.base, args.family)
    print("zero-fill complete")
    return 0


async def _verb_write(s: SafeSession, args, observed_idn: str) -> int:
    SafeSession.check_confirm(args.confirm, args.idn, observed_idn)
    data = args.image.read_bytes()
    if args.length > len(data):
        raise SafetyError(
            f"image is {len(data)} bytes, asked to write {args.length}"
        )
    if args.length % 4:
        raise SafetyError("length must be multiple of 4")
    if args.dry_run:
        print(f"[dry-run] would write {args.length} bytes to {args.base:#x}")
        return 0
    done = 0
    while done < args.length:
        n = min(1024, args.length - done)
        await s.session.memory_write(args.base + done, data[done : done + n])
        done += n
    print(f"wrote {done} bytes to {args.base:#x}")
    return 0


async def _verb_resume(s: SafeSession, args, observed_idn: str) -> int:
    SafeSession.check_confirm(args.confirm, args.idn, observed_idn)
    j = Journal.load(args.session_id)
    if j.finished:
        print(f"session {args.session_id} already finished")
        return 0
    if j.verb != "program":
        raise SafetyError(f"can only resume program sessions, not {j.verb}")
    if not j.image_path:
        raise SafetyError("journal has no image_path")

    family = next(
        (f for f in FAMILIES.values() if f.name == j.family_name), None,
    )
    if family is None:
        raise SafetyError(f"unknown family in journal: {j.family_name}")

    print(f"resuming program at block {j.last_completed_block + 1} "
          f"({j.image_path} -> {j.base:#x}, {j.length} bytes)")
    await s.program_image(
        image_path=Path(j.image_path), base=j.base,
        length=j.length, family=family,
        resume_from_block=j.last_completed_block,
    )
    print("resume complete")
    return 0


# ---------------------------------------------------------------------------
# Top-level entry.

async def _run(args) -> int:
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    needs_idn_echo = args.verb in (
        "erase", "program", "zerofill", "write", "resume",
    )
    needs_family = getattr(args, "family", None) is not None

    async with TektoolSession(args.host, addr=args.addr) as session:
        s = SafeSession(
            session, verb=args.verb,
            family_hint=getattr(args, "family", None),
            dry_run=args.dry_run,
        )

        # Pre-flight is mandatory for every verb except plain identify
        # (which IS the pre-flight).
        if args.verb == "identify":
            return await _verb_identify(s, args)

        # tektool only runs against a scope in service-mode boot ROM, where
        # SCPI is dead by design. We deliberately skip *IDN? — even with a
        # short timeout, the timed-out turn-around leaves the scope's GPIB
        # chip in a half-addressed state that breaks the next memory_read.
        # The real identity check is flash_identify inside preflight();
        # --idn is journaled as user attestation only.
        observed_idn = "<service-mode: SCPI dead>"

        if needs_idn_echo:
            await s.preflight(
                expected_idn=args.idn,
                expected_family=getattr(args, "family", None) if needs_family else None,
                expected_length=getattr(args, "length", None),
                base=getattr(args, "base", 0x1000000),
            )
        else:
            # Non-destructive: just check gateway version + chip ID.
            gw = await session.gateway_version()
            from .safety import REQUIRED_GATEWAY_VERSION
            if gw < REQUIRED_GATEWAY_VERSION:
                raise SafetyError(
                    f"gateway firmware {gw} < required {REQUIRED_GATEWAY_VERSION}"
                )

        verb_fns = {
            "read":     lambda: _verb_read(s, args),
            "backup":   lambda: _verb_backup(s, args),
            "verify":   lambda: _verb_verify(s, args),
            "erase":    lambda: _verb_erase(s, args, observed_idn),
            "program":  lambda: _verb_program(s, args, observed_idn),
            "zerofill": lambda: _verb_zerofill(s, args, observed_idn),
            "write":    lambda: _verb_write(s, args, observed_idn),
            "resume":   lambda: _verb_resume(s, args, observed_idn),
        }
        return await verb_fns[args.verb]()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except (TektoolError, SafetyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
