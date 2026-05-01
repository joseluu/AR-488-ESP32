# GPIB pin test firmware

Boot-then-loop sketch that pulses every GPIB connector pin HIGH for 1 ms in
connector pin-number order, with the SN75160B / SN75161B transceivers held
in the correct direction so each pulse propagates to the bus side.

Used to verify the AR-488-ESP32 board on a scope: probe any GPIB pin and you
should see a 1 ms pulse roughly 50× per second.

## Layout

- `platformio.ini` — two PIO envs:
  - `heltec_wifi_kit_32` (V1, 26 MHz xtal — current physical board)
  - `heltec_wifi_kit_32_v2` (V2, 40 MHz xtal)
- `src/main.cpp` — single-file Arduino sketch.
- `docs/a_faire.md` — original spec.

## Build & flash

```bash
~/.platformio/penv/Scripts/pio.exe run \
  -d firmware/test -e heltec_wifi_kit_32 \
  -t upload --upload-port COM6
```

Serial monitor: 115200 baud.

## Pin sweep

Each loop iteration pulses these signals in this order, then idles for
`CYCLE_MS = 20 ms`:

| GPIB pin | Signal | Source       |
|---------:|--------|--------------|
| 1        | DIO1   | ESP32 GPIO13 |
| 2        | DIO2   | ESP32 GPIO12 |
| 3        | DIO3   | ESP32 GPIO14 |
| 4        | DIO4   | ESP32 GPIO27 |
| 5        | EOI    | ESP32 GPIO19 |
| 6        | DAV    | ESP32 GPIO5  |
| 7        | NRFD   | ESP32 GPIO18 |
| 8        | NDAC   | ESP32 GPIO23 |
| 9        | IFC    | MCP23017 GPA1 |
| 10       | SRQ    | MCP23017 GPA2 |
| 11       | ATN    | MCP23017 GPA0 |
| 13       | DIO5   | ESP32 GPIO26 |
| 14       | DIO6   | ESP32 GPIO25 |
| 15       | DIO7   | ESP32 GPIO33 |
| 16       | DIO8   | ESP32 GPIO32 |
| 17       | REN    | MCP23017 GPA3 |

The 12 direct-GPIO signals (data + handshake + EOI) toggle in zero time;
the 4 MCP23017 signals (management) go through an I2C write at 400 kHz.

## Transceiver direction control

The part that took the most iteration to get clean pulses on the bus side:

- `TE_DATA = HIGH` (GPIO17) — SN75160B in Talk for DIO1..8. Held the entire run.
- `TE_CTRL = HIGH` (MCP GPA4) — SN75161B handshake in Talk. Set once at
  startup, **never flipped** during the sweep.
- `DC = LOW` (MCP GPA5) — SN75161B management in **controller** direction
  (drives ATN/IFC/REN out, listens for SRQ).
- `DC` is pulsed HIGH **only** around the SRQ pulse, with 1 ms settle
  margins on each side, so SRQ is driven outward as a "device". DC returns
  to LOW for the rest of the sweep.

### Why DC flips and TE_CTRL doesn't

We tried dropping TE_CTRL on individual pulses (e.g. during NDAC / NRFD,
during SRQ). It produced coupling artefacts on neighbouring lines: the
SN75161B's internal direction logic decodes per signal-group, so changing
TE_CTRL re-routes multiple pins at once and ghost edges show up
elsewhere. Keeping TE_CTRL fixed and only toggling DC around SRQ matches
what real GPIB device-mode traffic looks like and produced clean per-pin
pulses on the bus side.

## Other notable bits

- `setup()` drives every direct GPIO LOW before enabling outputs, so
  GPIO12 (= DIO2, an ESP32 boot-strap pin that must be LOW at reset for
  3.3 V flash) is safe at power-up.
- MCP23017 GPIOB is set to outputs and forced LOW (not floating inputs)
  to avoid shoot-through inside the chip.
- I2C is 400 kHz on SDA = GPIO21 / SCL = GPIO22. External pull-ups on the
  board are required — the ESP32 internal pulls (~45 kΩ) are too weak for
  reliable 400 kHz operation.
- If the MCP23017 doesn't ACK at 0x20, the firmware prints a warning and
  silently no-ops the MCP writes (direct-GPIO pulses still work).
