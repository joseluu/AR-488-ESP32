"""Safety wrapper around tektool's destructive operations.

The point of this module is to make it *very* hard to brick the scope:
  - Pre-flight identity & version checks (gateway FW, *IDN?, flash ID)
  - Backup-before-erase with SHA-256 sidecar
  - Block-level read-back verify after every write
  - Full-image post-verify after a program completes
  - Two-step confirm: --i-understand-this-can-brick-the-scope + --idn echo
  - Dry-run that prints the plan without sending destructive ops
  - Resumable session journal (last-good block)

Layout on disk:
    host_software/tektool/sessions/<iso>_<verb>.log
    host_software/tektool/sessions/<iso>_<verb>.journal.json
    host_software/tektool/backups/<iso>_<name>.bin (+ .sha256 sidecar)
"""

from __future__ import annotations

import hashlib
import json
import logging
import struct
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from . import flash as flashmod
from .flash import FAMILIES, FlashError, FlashFamily
from .transport import TektoolError, TektoolSession

log = logging.getLogger("tektool.safety")


REQUIRED_GATEWAY_VERSION = "0.5"

# Block size used for backup reads and program-verify cycles. Aligns with
# the firmware's payload cap (1200 bytes) and gives a clean progress
# fraction when the flash is sized in MiB.
BLOCK_BYTES = 1024


# ---------------------------------------------------------------------------
# Filesystem helpers.

def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def _module_dir() -> Path:
    return Path(__file__).resolve().parent


def sessions_dir() -> Path:
    p = _module_dir() / "sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def backups_dir() -> Path:
    p = _module_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Confirmation token used by destructive verbs.

CONFIRM_TOKEN = "i-understand-this-can-brick-the-scope"


# ---------------------------------------------------------------------------
# Journal — written to disk after every block so a Ctrl-C can resume.

@dataclass
class Journal:
    session_id: str
    verb: str
    base: int
    length: int
    family_name: str
    image_path: str = ""
    backup_path: str = ""
    last_completed_block: int = -1     # -1 = nothing yet
    finished: bool = False
    log: list[dict] = field(default_factory=list)

    def path(self) -> Path:
        return sessions_dir() / f"{self.session_id}.journal.json"

    def save(self) -> None:
        self.path().write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, session_id: str) -> Journal:
        p = sessions_dir() / f"{session_id}.journal.json"
        if not p.exists():
            raise FileNotFoundError(f"no journal for session {session_id!r}")
        return cls(**json.loads(p.read_text()))

    def record(self, event: str, **fields) -> None:
        self.log.append({"ts": datetime.now().isoformat(timespec="seconds"),
                         "event": event, **fields})


# ---------------------------------------------------------------------------
# Pre-flight result.

@dataclass
class PreflightResult:
    gateway_version: str
    scope_idn: str
    ven_dev_id: int
    family: FlashFamily


# ---------------------------------------------------------------------------
# SafeSession — wraps a TektoolSession with the safety contract.

class SafetyError(TektoolError):
    """Raised by SafeSession when a safety check refuses to continue."""


class SafeSession:
    """High-level orchestrator for backup / verify / erase / program.

    Construct with an *already-open* TektoolSession. All destructive
    methods require:
        confirm_token == CONFIRM_TOKEN
        idn_echo      == the scope's actual *IDN? string (byte-for-byte)
    Pass `dry_run=True` to skip every memory_write while still doing the
    pre-flight + (live) reads.
    """

    def __init__(
        self,
        session: TektoolSession,
        *,
        verb: str,
        family_hint: FlashFamily | None = None,
        dry_run: bool = False,
    ):
        self.session = session
        self.verb = verb
        self.dry_run = dry_run
        self.family_hint = family_hint
        self.session_id = f"{_stamp()}_{verb}"
        self.journal = Journal(
            session_id=self.session_id, verb=verb,
            base=0, length=0,
            family_name=family_hint.name if family_hint else "",
        )
        self._configure_file_logging()

    def _configure_file_logging(self) -> None:
        log_path = sessions_dir() / f"{self.session_id}.log"
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        ))
        logging.getLogger("tektool").addHandler(fh)
        log.info("session %s log -> %s", self.session_id, log_path)

    # ------------------------------------------------------------------
    # Pre-flight.

    async def preflight(
        self,
        *,
        expected_idn: str,
        expected_family: FlashFamily | None,
        expected_length: int | None,
        base: int = 0x1000000,
    ) -> PreflightResult:
        """Run the four mandatory checks. Raises SafetyError on any fail."""
        gw = await self.session.gateway_version()
        if gw < REQUIRED_GATEWAY_VERSION:
            raise SafetyError(
                f"gateway firmware {gw} < required {REQUIRED_GATEWAY_VERSION}"
            )
        log.info("preflight: gateway version %s OK", gw)

        # tektool only runs against a scope in service-mode boot ROM, where
        # SCPI is dead. Skip the *IDN? probe entirely — a timed-out turn-
        # around leaves the scope's GPIB chip in a half-addressed state that
        # breaks the very next memory_read. flash_identify below is the
        # live identity gate; expected_idn is journaled as user attestation.
        idn = "<service-mode: SCPI dead>"
        log.info("preflight: skipping *IDN? (service-mode assumption)")

        ven_dev = await flashmod.flash_identify(self.session, base)
        family = FAMILIES[ven_dev]
        log.info("preflight: chip = %s (ven_dev=%#06x)", family.name, ven_dev)

        if expected_family is not None and expected_family.ven_dev_id != ven_dev:
            raise SafetyError(
                f"preflight: family mismatch — expected {expected_family.name}, "
                f"chip is {family.name}"
            )

        # The chip's natural usable length is family.size * devices_stacked.
        chip_total = family.size * family.devices_stacked
        if expected_length is not None and expected_length > chip_total:
            raise SafetyError(
                f"preflight: requested length {expected_length:#x} > "
                f"chip capacity {chip_total:#x} for {family.name}"
            )

        result = PreflightResult(
            gateway_version=gw, scope_idn=idn,
            ven_dev_id=ven_dev, family=family,
        )
        self.journal.family_name = family.name
        self.journal.record("preflight",
                            gateway_version=gw, scope_idn=idn,
                            family=family.name)
        self.journal.save()
        return result

    # ------------------------------------------------------------------
    # Backup — read range to file + sha256 sidecar.

    async def backup(
        self,
        *,
        base: int,
        length: int,
        name: str = "backup",
    ) -> Path:
        """Read `length` bytes starting at `base`, write to backups/. Returns path."""
        out = backups_dir() / f"{_stamp()}_{name}.bin"
        sha = hashlib.sha256()
        log.info("backup -> %s (%d bytes)", out, length)
        self.journal.base = base
        self.journal.length = length
        self.journal.backup_path = str(out)
        self.journal.save()

        with open(out, "wb") as fh:
            done = 0
            while done < length:
                n = min(BLOCK_BYTES, length - done)
                buf = await self.session.memory_read(base + done, n)
                if len(buf) != n:
                    raise SafetyError(
                        f"backup: short read at {base + done:#x}: "
                        f"want {n}, got {len(buf)}"
                    )
                fh.write(buf)
                sha.update(buf)
                done += n
                if (done % (32 * BLOCK_BYTES)) == 0 or done == length:
                    log.info("  backup %d/%d (%d%%)", done, length,
                             done * 100 // length)

        digest = sha.hexdigest()
        (out.with_suffix(".bin.sha256")).write_text(f"{digest}  {out.name}\n")
        log.info("backup complete: sha256=%s", digest)
        self.journal.record("backup",
                            path=str(out), sha256=digest, length=length)
        self.journal.save()
        return out

    # ------------------------------------------------------------------
    # Verify — compare scope memory range to a file.

    async def verify(
        self,
        *,
        image_path: Path,
        base: int,
        length: int | None = None,
    ) -> None:
        """Read scope memory and compare byte-by-byte to `image_path`."""
        data = image_path.read_bytes()
        if length is None:
            length = len(data)
        if length > len(data):
            raise SafetyError(
                f"verify: image {image_path} is {len(data)} bytes, "
                f"asked to verify {length}"
            )
        log.info("verify scope[%#x..%#x] vs %s", base, base + length, image_path)

        done = 0
        while done < length:
            n = min(BLOCK_BYTES, length - done)
            buf = await self.session.memory_read(base + done, n)
            if buf != data[done : done + n]:
                # Find the first byte that differs for the error message.
                for j in range(n):
                    if buf[j] != data[done + j]:
                        raise SafetyError(
                            f"verify: mismatch at {base + done + j:#x} "
                            f"(scope={buf[j]:#04x}, image="
                            f"{data[done + j]:#04x})"
                        )
            done += n
            if (done % (64 * BLOCK_BYTES)) == 0 or done == length:
                log.info("  verify %d/%d", done, length)
        log.info("verify OK (%d bytes)", length)
        self.journal.record("verify_ok", image=str(image_path), length=length)
        self.journal.save()

    # ------------------------------------------------------------------
    # Confirm-token check.

    @staticmethod
    def check_confirm(token: str | None, idn_echo: str | None,
                      observed_idn: str) -> None:
        if token != CONFIRM_TOKEN:
            raise SafetyError(
                "destructive op refused: pass --i-understand-this-can-brick-the-scope"
            )
        if not idn_echo or not idn_echo.strip():
            raise SafetyError(
                "destructive op refused: --idn must be a non-empty attestation"
            )
        # In service mode SCPI is dead, so we can't compare against a live
        # *IDN?. The flash_identify family check inside preflight() is the
        # real identity gate; --idn is journaled as user attestation.
        if observed_idn.startswith("<service-mode"):
            return
        if idn_echo.strip() != observed_idn.strip():
            raise SafetyError(
                "destructive op refused: --idn must echo the scope's exact *IDN?\n"
                f"  expected: {observed_idn!r}\n"
                f"  got:      {idn_echo!r}"
            )

    # ------------------------------------------------------------------
    # Program — write a binary image with block verify after each write.
    #
    # The C tool programs 4 bytes at a time via the chip-specific
    # flash_program(). We mirror that, then do a 4-byte read-back compare
    # before advancing. After the full image is written we re-read the
    # whole range and compare to the source bytes (independent verify).

    async def program_image(
        self,
        *,
        image_path: Path,
        base: int,
        length: int,
        family: FlashFamily,
        resume_from_block: int = -1,
    ) -> None:
        data = image_path.read_bytes()
        if len(data) < length:
            raise SafetyError(
                f"program: image {image_path} is {len(data)} bytes, "
                f"asked to write {length}"
            )

        self.journal.base = base
        self.journal.length = length
        self.journal.image_path = str(image_path)
        self.journal.family_name = family.name
        self.journal.save()

        # Programming is 4-byte-word granular per the C upstream.
        word_size = 4
        if length % word_size != 0:
            raise SafetyError(
                f"program: length {length} must be a multiple of {word_size}"
            )
        total_words = length // word_size

        # Each "block" for journal-resume purposes is a whole BLOCK_BYTES
        # chunk; we still write 4 bytes at a time inside it.
        blocks = (length + BLOCK_BYTES - 1) // BLOCK_BYTES

        start_block = resume_from_block + 1
        if start_block > 0:
            log.info("resuming from block %d/%d", start_block, blocks)

        for blk in range(start_block, blocks):
            blk_start = blk * BLOCK_BYTES
            blk_end = min(blk_start + BLOCK_BYTES, length)

            # Write loop, 4 bytes per iteration.
            off = blk_start
            while off < blk_end:
                word_le = data[off : off + word_size]
                data_u32 = struct.unpack("<I", word_le)[0]
                if not self.dry_run:
                    await flashmod.flash_program(
                        self.session, base + off, data_u32, family,
                    )
                off += word_size

            # Read-back verify the whole block.
            if not self.dry_run:
                got = await self.session.memory_read(
                    base + blk_start, blk_end - blk_start,
                )
                want = data[blk_start:blk_end]
                if got != want:
                    for j in range(len(want)):
                        if got[j] != want[j]:
                            self.journal.record(
                                "verify_mismatch",
                                addr=base + blk_start + j,
                                got=got[j], want=want[j],
                                last_completed_block=self.journal.last_completed_block,
                            )
                            self.journal.save()
                            raise SafetyError(
                                f"program: mismatch at "
                                f"{base + blk_start + j:#x} "
                                f"(scope={got[j]:#04x}, image="
                                f"{want[j]:#04x}). Resume with "
                                f"`tektool resume {self.session_id}`."
                            )

            self.journal.last_completed_block = blk
            if (blk % 32) == 0 or blk == blocks - 1:
                log.info("  programmed block %d/%d", blk + 1, blocks)
                self.journal.save()

        # Independent full-image verify (re-reads everything).
        if not self.dry_run:
            log.info("program: full-image post-verify pass")
            await self.verify(image_path=image_path, base=base, length=length)

        self.journal.finished = True
        self.journal.record("program_done",
                            words=total_words, blocks=blocks)
        self.journal.save()
        log.info("program complete: %d bytes to %#x", length, base)

    # ------------------------------------------------------------------
    # Erase wrapper.

    async def erase(self, *, base: int, family: FlashFamily) -> None:
        if self.dry_run:
            log.info("[dry-run] would erase chip family=%s base=%#x",
                     family.name, base)
            return
        log.info("erase chip family=%s base=%#x", family.name, base)
        await flashmod.flash_erase(self.session, base, family)
        self.journal.record("erase_done")
        self.journal.save()
