# AR-488-ESP32 — hardware notes for firmware developers

This document targets a developer (human or AI) porting AR-488 firmware
from another hardware platform to this board. It covers the pieces that
aren't obvious from a stock AR-488 port and that have already cost
debugging time on this design. Chip pinouts, KiCad metadata, and high
level design rationale live in `docs/TECHNICAL_INFORMATIONS.md` — read
that first if you need the chip-level reference.

## At a glance

- **MCU:** Heltec WiFi Kit 32 (ESP32). Two physical revisions exist on
  this board:
  - **V1** — ESP32-D0WDQ6, 26 MHz crystal. PIO env: `heltec_wifi_kit_32`.
  - **V2** — ESP32-PICO-D4, 40 MHz crystal. PIO env:
    `heltec_wifi_kit_32_v2`.
  Both are pin-compatible. Selecting the wrong env produces garbled
  serial because of the wrong crystal divisor.
- **GPIB transceivers:** SN75160B (data, SOIC-20W) + SN75161B (control,
  DIP-20). Both 5 V parts. Direct 3.3 V drive from ESP32 — no level
  shifters. Inputs are TTL (V_IH ~1.5 V), outputs swing 0–5 V on the MCU
  side; the ESP32's input clamp diodes tolerate this in practice but a
  series resistor (~330 Ω) is the safe-by-design fix and is on the
  hardware to-do list.
- **GPIO expander:** MCP23017 at I²C 0x20 (A0=A1=A2=GND, ~RESET tied to
  3.3 V). Powered at 3.3 V to match ESP32 logic levels on SDA/SCL.
- **OLED:** SSD1306 128×64 on internal I²C (GPIO4=SDA, GPIO15=SCL,
  GPIO16=RST). Separate from the GPIB I²C bus. Free for firmware to use
  as a status display.
- **Power:** USB Vbus (5 V) **or** barrel jack 7–12 V → AO4407A reverse
  polarity P-FET → AMS1117-5.0 LDO → 5 V rail. ESP32 module's onboard
  AMS1117-3.3 generates 3.3 V.

## GPIB signal → pin map

This is the canonical mapping. Use it verbatim; deviating breaks the PCB.

### Direct ESP32 GPIOs (data + handshake + EOI + TE_DATA + I²C)

| GPIB signal | ESP32 GPIO | Notes |
|-------------|-----------:|-------|
| DIO1        | 13         |       |
| DIO2        | 12         | **Strapping pin — must be LOW at boot.** |
| DIO3        | 14         |       |
| DIO4        | 27         |       |
| DIO5        | 26         |       |
| DIO6        | 25         | Heltec onboard LED is also wired here. |
| DIO7        | 33         |       |
| DIO8        | 32         |       |
| DAV         | 5          | Strapping pin (must be HIGH at boot — not a problem in practice, see below). |
| NRFD        | 18         |       |
| NDAC        | 23         |       |
| EOI         | 19         |       |
| TE_DATA     | 17         | SN75160B Talk Enable. |
| I²C SDA     | 21         | To MCP23017 + external pull-up. |
| I²C SCL     | 22         | To MCP23017 + external pull-up. |

### MCP23017 GPIOA (slow management path)

| GPIB / control signal | MCP bit (port A) | Drives                    |
|-----------------------|-----------------:|---------------------------|
| ATN                   | 0                | SN75161B ATN terminal pin |
| IFC                   | 1                | SN75161B IFC terminal pin |
| SRQ                   | 2                | SN75161B SRQ terminal pin |
| REN                   | 3                | SN75161B REN terminal pin |
| TE_CTRL               | 4                | SN75161B Talk Enable      |
| DC                    | 5                | SN75161B Direction Control |

GPIOB is unused on the board. The test firmware sets it as outputs
forced LOW; do the same to avoid floating CMOS inputs and the
shoot-through current that comes with them.

## Boot-strap caveats — read before writing `setup()`

The ESP32 samples several GPIOs at the rising edge of EN. If the GPIB
bus or the SN7516x outputs back-drive these pins to the wrong level the
chip won't boot.

| GPIO | Strapping role            | This board's signal | Required at boot |
|------|---------------------------|---------------------|------------------|
| 0    | Boot mode (HIGH = run)    | (unused — boot button) | HIGH |
| 2    | Boot mode                 | (unused)            | LOW or float |
| 5    | VSPI CS bootstrap         | DAV                 | HIGH |
| 12   | Flash voltage (LOW = 3.3 V) | **DIO2**          | **LOW (critical)** |
| 15   | Silent boot               | (OLED, internal)    | (handled by module) |

**What firmware must do at the very top of `setup()` — before anything
else, including `Serial.begin()`:**

1. `pinMode(12, OUTPUT); digitalWrite(12, LOW);` — get DIO2 off the
   strapping value path before the SN75160B has a chance to drive it.
2. Set TE_DATA (GPIO17) to a defined output. Until you do, the ESP32
   pin floats and the SN75160B's MCU-side D pins read whatever the bus
   side is doing. With TE_DATA floating-but-likely-HIGH (SN75160B Talk),
   any bus traffic ends up on the ESP32 D pins — including GPIO12.
3. Initialise I²C and write `IODIRA = 0`, then `OLATA` with TE_CTRL HIGH
   and DC LOW (controller / Talk). Until then the SN75161B's MCU-side
   pins are similarly indeterminate.

GPIO5 (DAV) being a strapping pin worked out in our favour: GPIB DAV is
unasserted = HIGH at idle, which is also the strapping requirement.
Don't drive DAV LOW before the ESP32 finishes booting.

GPIOs 6–11 are tied to internal flash and **must not** be used.
GPIOs 34–39 are input-only and unsuitable for any GPIB signal.

## Hybrid GPIO architecture — what it implies for firmware

This board is **not** a flat-GPIO design like the original AR-488 on
ATmega328P or the 32u4 fork. The 16-bit data + handshake bus is on
direct ESP32 GPIOs (per-cycle latency ~ tens of ns), but the four
management signals (ATN, IFC, SRQ, REN) and the two transceiver control
signals (TE_CTRL, DC) sit behind an I²C link to the MCP23017.

At 400 kHz I²C, one OLATA register write costs roughly **75 µs**
(start + addr + reg + data + stop). At 100 kHz it's roughly four times
that. **Do not put MCP23017 writes inside the per-byte handshake
loop** — only the direct GPIOs (DAV, NRFD, NDAC, DIO1..8, EOI) belong
there. ATN/IFC/REN flip at command boundaries, not data boundaries.

Implementation hints:

- **Cache the OLATA byte in RAM** and do a single-byte write per change
  — the test firmware shows the pattern (`g_mcpOlatA`,
  `mcpSetBitA()`).
- **Don't read-modify-write across boundaries** by doing a separate I²C
  read of GPIOA — the cached copy is authoritative because nothing else
  drives port A.
- For SRQ polling (where the board is in *device* mode and reads SRQ as
  an input), point IODIRA bit 2 to input first, read GPIOA, then put it
  back to output. Polling rate is bounded by 2× the I²C latency.

## Transceiver direction control — getting it right

The SN75161B has *two* direction inputs that decode per signal-group:

| TE  | DC  | DAV     | NRFD/NDAC | EOI     | ATN/IFC/REN | SRQ     |
|-----|-----|---------|-----------|---------|-------------|---------|
| 1   | 0   | drive→bus | bus→drive | drive→bus | drive→bus  | bus→drive |
| 0   | 0   | bus→drive | drive→bus | bus→drive | drive→bus  | bus→drive |
| 1   | 1   | drive→bus | bus→drive | drive→bus | bus→drive  | drive→bus |
| 0   | 1   | bus→drive | drive→bus | bus→drive | bus→drive  | drive→bus |

(See SN75161B datasheet table 1 for the authoritative version.)

In practical firmware terms:

- **DC = 0** — controller mode. ATN/IFC/REN are outputs, SRQ is an
  input. Use this for the AR-488 controller-in-charge role.
- **DC = 1** — device mode. ATN/IFC/REN are inputs, SRQ is an output.
  Use this whenever the board is acting as a GPIB device (e.g.
  asserting SRQ to request service).
- **TE = 1** — Talk for the handshake group: DAV is an output, NRFD
  and NDAC are inputs. EOI is also an output.
- **TE = 0** — Listen: DAV is an input, NRFD and NDAC are outputs.
  EOI is an input.

**Lesson learned from bring-up (don't re-derive it):**

While bringing the board up we tried flipping TE_CTRL on a per-pulse
basis to get a particular signal driven outward. Doing so produces
**coupling artefacts on neighbouring lines** — ghost edges on signals
that share the direction-decode group inside the SN75161B. The robust
pattern is:

1. Choose the bus role for the operation (controller or device).
2. Choose the direction (Talk or Listen).
3. Set TE_CTRL and DC accordingly **once** at the boundary, settle (a
   few µs is enough; the test firmware uses 1 ms as a generous margin).
4. Run the whole transaction with TE_CTRL fixed.

DC may legitimately need to flip mid-sequence (e.g. asserting SRQ as a
device while the rest of the board is in controller mode). That's fine
— it's the per-pulse TE flips that misbehave.

TE_DATA on the SN75160B is independent and only affects DIO1..8. Flip
it freely with the bus direction; there's no internal coupling between
DIO bits.

## Logic polarity (easy to get wrong)

The SN7516x parts are **non-inverting** between MCU and bus. The GPIB
bus itself is **negative-true** (a signal is *asserted* when the bus
line is LOW, due to its open-collector / wired-or nature).

Combined: writing **0** to a Talk-direction MCU pin asserts the
corresponding GPIB signal; writing **1** unasserts it. Same on the
input side — reading **0** from a Listen-direction MCU pin means the
bus signal is asserted.

The pin-test firmware (`firmware/test/`) pulses signals **HIGH** for
visibility on a scope; that's the *unasserted* level on the bus. Real
firmware should treat HIGH as the idle / negated state and assert by
driving LOW.

## I²C bus details

- **Pins:** SDA = GPIO21, SCL = GPIO22.
- **External pull-ups required.** ESP32 internal pulls (~45 kΩ) are
  too weak for reliable 400 kHz operation across PCB traces. Without
  proper pull-ups the new ESP-IDF i2c_master_ng driver returns
  `ESP_ERR_INVALID_STATE` on writes (it presents as "MCP not
  responding").
- **Speed:** 400 kHz works; 1 MHz is in the MCP23017's spec but
  hasn't been tested on this board.
- **Address:** MCP23017 at 0x20. Nothing else on this bus by default.

The internal SSD1306 OLED on the ESP32 module sits on a *different*
I²C bus (GPIO4/GPIO15) and does not interfere.

## Power notes

- USB Vbus and the barrel jack are diode-OR'd at the 5 V rail (P-FET
  reverse-polarity protection on the jack side). It's safe to have
  both connected; whichever is higher wins.
- The 3.3 V rail is generated by the Heltec module's own LDO from the
  5 V rail. Current budget for 3.3 V peripherals is small — don't add
  loads of more than ~100 mA on 3.3 V without checking.
- Decoupling: 100 nF + 22 µF on each transceiver, 100 nF on the
  MCP23017. Already on the PCB; mentioned for context if you're
  measuring noise.

## Reference firmware

The likely starting point for adaptation is the upstream AR-488:

- **Original (ATmega328P / Arduino Uno R3):**
  https://github.com/Twilight-Logic/AR488
- **32u4 fork:**
  https://github.com/artgodwin/AR488-32u4-PCB

Things in those codebases that **will not survive the port** unchanged:

- Direct port-register writes (`PORTB`, `PORTD`, `PINx`) — replace
  with `digitalWrite()` / `digitalRead()` or with ESP32's
  `GPIO.out_w1ts` / `out_w1tc` registers if you need the speed.
- Timing assumed at 16 MHz — recalibrate for 240 MHz ESP32.
- Single-port assumption (all GPIB signals on one MCU port) — not
  true here; the management signals are behind I²C.
- Pin-change interrupts — ESP32 supports them per-GPIO, not
  per-port.
- AVR sleep modes — different on ESP32; usually irrelevant for an
  always-on bus interface anyway.

A clean structural split for the port is to keep AR-488's command
parser and SCPI logic intact and replace only the bus-driver layer
with one that knows about the direct/MCP split.

## Per-pin verification

`firmware/test/` contains a stand-alone sketch that pulses every GPIB
signal in connector pin-number order. Use it to confirm the wiring
end-to-end (GPIO → transceiver → connector pin) before bringing up the
real firmware. See `firmware/test/README.md` for what it does and the
direction-control choices it embeds.
