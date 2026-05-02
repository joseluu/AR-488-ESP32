# Technical Information — AR-488-ESP32 GPIB Interface

## Heltec WiFi Kit 32 (ESP32) — Complete Pinout

Board orientation: USB connector at bottom, OLED at top. 2x18 pin headers, 22.86mm row spacing.

### Left Row (top to bottom)

| Pos | Label | GPIO | Notes |
|-----|-------|------|-------|
| 1 | GND | -- | Power |
| 2 | 5V | -- | **5V output from USB** |
| 3 | 3V3 | -- | 3.3V output |
| 4 | RST | -- | Reset |
| 5 | 13 | GPIO13 | ADC2_4, Touch4 |
| 6 | 12 | GPIO12 | ADC2_5, Touch5 — strapping pin (LOW at boot) |
| 7 | 14 | GPIO14 | ADC2_6, Touch6 |
| 8 | 27 | GPIO27 | ADC2_7, Touch7 |
| 9 | 26 | GPIO26 | DAC2, ADC2_9 |
| 10 | 25 | GPIO25 | DAC1, ADC2_8 — on-board LED |
| 11 | 33 | GPIO33 | ADC1_5, Touch8 |
| 12 | 32 | GPIO32 | ADC1_4, Touch9 |
| 13 | 35 | GPIO35 | ADC1_7 — **input only** |
| 14 | 34 | GPIO34 | ADC1_6 — **input only** |
| 15 | 39 | GPIO39 | ADC1_3 — **input only** |
| 16 | 38 | GPIO38 | ADC1_2 — **input only** |
| 17 | 37 | GPIO37 | ADC1_1 — **input only** |
| 18 | 36 | GPIO36 | ADC1_0 — **input only** |

### Right Row (top to bottom)

| Pos | Label | GPIO | Notes |
|-----|-------|------|-------|
| 1 | GND | -- | Power |
| 2 | 5V | -- | **5V output from USB** |
| 3 | 3V3 | -- | 3.3V output |
| 4 | GND | -- | Power |
| 5 | TX | GPIO1 | U0_TXD — serial programming |
| 6 | RX | GPIO3 | U0_RXD — serial programming |
| 7 | 15 | GPIO15 | **OLED_SCL (reserved)** |
| 8 | 2 | GPIO2 | Strapping pin |
| 9 | 0 | GPIO0 | **PROG button**, strapping |
| 10 | 4 | GPIO4 | **OLED_SDA (reserved)** |
| 11 | 16 | GPIO16 | **OLED_RST (reserved)** |
| 12 | 17 | GPIO17 | U2_TXD |
| 13 | 5 | GPIO5 | V_SPI_CS0 — strapping pin |
| 14 | 18 | GPIO18 | V_SPI_CLK |
| 15 | 23 | GPIO23 | V_SPI_MOSI |
| 16 | 19 | GPIO19 | V_SPI_MISO |
| 17 | 22 | GPIO22 | I2C SCL |
| 18 | 21 | GPIO21 | I2C SDA, V_SPI_HD |

### GPIO Classification

**OLED reserved (3):** GPIO4 (SDA), GPIO15 (SCL), GPIO16 (RST)

**Input-only (6):** GPIO34, GPIO35, GPIO36, GPIO37, GPIO38, GPIO39

**Bidirectional, free for use (16):**
GPIO2, GPIO5, GPIO12, GPIO13, GPIO14, GPIO17, GPIO18, GPIO19, GPIO21, GPIO22, GPIO23, GPIO25, GPIO26, GPIO27, GPIO32, GPIO33

**Avoid:** GPIO0 (boot button), GPIO1 (TX), GPIO3 (RX), GPIO6-11 (internal flash)

### Sources
- Official pinout diagram: https://resource.heltec.cn/download/WiFi_Kit_32/WIFI%20Kit%2032_pinoutDiagram_V1.pdf
- Heltec documentation: https://docs.heltec.org/en/node/esp32/wifi_kit_32/index.html
- ESP32 GPIO reference: https://randomnerdtutorials.com/esp32-pinout-reference-gpios/

---

## Heltec WiFi Kit 32 V2 (ESP32) — Complete Pinout

Same ESP32-D0WDQ6 chip and 2x18 header layout as V1, but the V2 adds a **Vext** switchable 3.3V rail (controlled by GPIO21) and a battery voltage divider tied to GPIO13 (Power Detection). USB connector is still Micro-USB.

Board orientation: USB connector at bottom, OLED at top. 2x18 pin headers, 22.86mm row spacing.

### Left Row (top to bottom)

| Pos | Label | GPIO | Notes |
|-----|-------|------|-------|
| 1 | GND | -- | Power |
| 2 | 3V3 | -- | 3.3V output |
| 3 | Vext | -- | Switchable 3.3V (controlled by GPIO21) |
| 4 | RST | -- | Reset |
| 5 | 13 | GPIO13 | ADC2_4, Touch4 — **also tied to battery voltage divider (Power Detection)** |
| 6 | 12 | GPIO12 | ADC2_5, Touch5 — strapping pin (LOW at boot) |
| 7 | 14 | GPIO14 | ADC2_6, Touch6 |
| 8 | 27 | GPIO27 | ADC2_7, Touch7 |
| 9 | 26 | GPIO26 | DAC2, ADC2_9 |
| 10 | 25 | GPIO25 | DAC1, ADC2_8 — on-board LED |
| 11 | 33 | GPIO33 | ADC1_5, Touch8 |
| 12 | 32 | GPIO32 | ADC1_4, Touch9 |
| 13 | 35 | GPIO35 | ADC1_7 — **input only** |
| 14 | 34 | GPIO34 | ADC1_6 — **input only** |
| 15 | 39 | GPIO39 | ADC1_3 — **input only** |
| 16 | 38 | GPIO38 | ADC1_2 — **input only** |
| 17 | 37 | GPIO37 | ADC1_1 — **input only** |
| 18 | 36 | GPIO36 | ADC1_0 — **input only** |

### Right Row (top to bottom)

| Pos | Label | GPIO | Notes |
|-----|-------|------|-------|
| 1 | GND | -- | Power |
| 2 | 5V | -- | **5V output from USB** |
| 3 | 3V3 | -- | 3.3V output |
| 4 | Vext | -- | Switchable 3.3V |
| 5 | TX | GPIO1 | U0_TXD — serial programming |
| 6 | RX | GPIO3 | U0_RXD — serial programming |
| 7 | 15 | GPIO15 | **OLED_SCL (reserved)** |
| 8 | 2 | GPIO2 | Strapping pin |
| 9 | 0 | GPIO0 | **PRG button**, strapping |
| 10 | 4 | GPIO4 | **OLED_SDA (reserved)** |
| 11 | 16 | GPIO16 | **OLED_RST (reserved)** |
| 12 | 17 | GPIO17 | U2_TXD |
| 13 | 5 | GPIO5 | V_SPI_CS0 — strapping pin |
| 14 | 18 | GPIO18 | V_SPI_CLK |
| 15 | 23 | GPIO23 | V_SPI_MOSI |
| 16 | 19 | GPIO19 | V_SPI_MISO |
| 17 | 22 | GPIO22 | I2C SCL |
| 18 | 21 | GPIO21 | I2C SDA — **also Vext control** (drive HIGH to enable Vext rail) |

### Differences vs V1

- Vext switchable 3.3V rail added — left pos 3 and right pos 4 (V1 had `3V3` and `GND` there)
- GPIO21 doubles as Vext enable (drive HIGH to power Vext) — careful when using as I2C SDA
- GPIO13 has a battery voltage divider on it (Power Detection) — usable as GPIO but reads ~½·VBAT when battery is connected
- USB chip changed from CP2102 to CP2104 in some revs (still Micro-USB)

### GPIO Classification (same as V1)

**OLED reserved (3):** GPIO4 (SDA), GPIO15 (SCL), GPIO16 (RST)
**Input-only (6):** GPIO34, GPIO35, GPIO36, GPIO37, GPIO38, GPIO39
**Bidirectional, free for use (16):** GPIO2, GPIO5, GPIO12, GPIO13, GPIO14, GPIO17, GPIO18, GPIO19, GPIO21, GPIO22, GPIO23, GPIO25, GPIO26, GPIO27, GPIO32, GPIO33
**Avoid:** GPIO0 (boot button), GPIO1 (TX), GPIO3 (RX), GPIO6-11 (internal flash)

### Sources
- Official pinout diagram: https://resource.heltec.cn/download/WiFi_Kit_32/WIFI_Kit_32_pinoutDiagram_V2.pdf
- Heltec hardware update log: https://wiki.heltec.org/docs/devices/open-source-hardware/esp32-series/lora-32/wifi-kit-32/hardware_update_log

---

## Heltec WiFi Kit 32 V3 (ESP32-S3) — Complete Pinout

**Major architectural change:** V3 uses **ESP32-S3FN8** (Xtensa LX7 dual-core, 8 MB flash) instead of the original ESP32. USB is now **Type-C** with native USB support on the S3 (CP2102 still present for serial). Different GPIO numbering — V1/V2 firmware will NOT run unmodified.

Board orientation: USB connector at top, OLED below. 2x18 pin headers (Heltec calls them **J2** = left, **J3** = right), 2.54mm pitch.

### Left Row — Header J2 (top to bottom)

| Pos | Label | GPIO | Notes |
|-----|-------|------|-------|
| 1 | GND | -- | Power |
| 2 | 5V | -- | **5V output from USB** (max 500 mA) |
| 3 | Ve | -- | Vext switchable 3.3V (controlled by GPIO36, max 350 mA) |
| 4 | Ve | -- | Vext switchable 3.3V (second pin) |
| 5 | RX | GPIO44 | U0_RXD — connected to CP2102 TXD |
| 6 | TX | GPIO43 | U0_TXD — connected to CP2102 RXD |
| 7 | RST | -- | CHIP_PU (reset switch) |
| 8 | 0 | GPIO0 | **PRG button**, strapping |
| 9 | 21 | GPIO21 | **OLED_RST (reserved)** |
| 10 | 20 | GPIO20 | U1_CTS, ADC2_CH9, CLK_OUT1, **USB_D+** (solder R29 to connect to USB socket) |
| 11 | 19 | GPIO19 | U1_RTS, ADC2_CH8, CLK_OUT2, **USB_D−** (solder R3 to connect to USB socket) |
| 12 | 7 | GPIO7 | ADC1_CH6, Touch7 |
| 13 | 6 | GPIO6 | ADC1_CH5, Touch6 |
| 14 | 5 | GPIO5 | ADC1_CH4, Touch5 |
| 15 | 4 | GPIO4 | ADC1_CH3, Touch4 |
| 16 | 3 | GPIO3 | ADC1_CH2, Touch3 |
| 17 | 2 | GPIO2 | ADC1_CH1, Touch2 |
| 18 | 1 | GPIO1 | ADC1_CH0, Touch1 — **also tied to VBAT divider** (V_BAT = (100+390)/100 · V_ADC) |

### Right Row — Header J3 (top to bottom)

| Pos | Label | GPIO | Notes |
|-----|-------|------|-------|
| 1 | GND | -- | Power |
| 2 | 3V3 | -- | 3.3V output (max 500 mA) |
| 3 | 3V3 | -- | 3.3V output |
| 4 | 26 | GPIO26 | SPICS1 |
| 5 | 48 | GPIO48 | SPICLK_N_DIFF, SUBSPICLK_N_DIFF |
| 6 | 47 | GPIO47 | SPICLK_P_DIFF, SUBSPICLK_P_DIFF |
| 7 | 33 | GPIO33 | SPIIO4, FSPIHD, SUBSPIHD |
| 8 | 34 | GPIO34 | SPIIO5, FSPICS0, SUBSPICS0 |
| 9 | 35 | GPIO35 | SPIIO6, FSPID, SUBSPID — **on-board LED control** |
| 10 | 36 | GPIO36 | SPIIO7, FSPICLK, SUBSPICLK — **Vext enable (drive HIGH to power Vext)** |
| 11 | 37 | GPIO37 | SPIDQS, FSPIQ, SUBSPIQ — **ADC_Ctrl (battery measurement enable)** |
| 12 | 38 | GPIO38 | FSPIWP, SUBSPIWP |
| 13 | 39 | GPIO39 | MTCK (JTAG) |
| 14 | 40 | GPIO40 | MTDO (JTAG) |
| 15 | 41 | GPIO41 | MTDI (JTAG) |
| 16 | 42 | GPIO42 | MTMS (JTAG) |
| 17 | 45 | GPIO45 | strapping pin (VDD_SPI voltage select) |
| 18 | 46 | GPIO46 | strapping pin (boot mode) |

### On-Board Peripherals (NOT broken out to headers)

- **OLED I2C:** GPIO17 = OLED_SDA, GPIO18 = OLED_SCL (internal — do not reuse). OLED_RST = GPIO21 (this one IS on the header, J2 pos 9).
- **CP2102 USB-serial:** GPIO43/44 (also broken out at J2 pos 5/6).

### Differences vs V1/V2

- **MCU:** ESP32-S3 (LX7, 8 MB flash, native USB) — different SDK requirements; firmware is not binary-compatible with V1/V2.
- **USB:** Type-C (was Micro-USB).
- **Deep sleep:** <10 µA (was ~800 µA on V2).
- **No DAC** on ESP32-S3 (V1/V2 had DAC1/DAC2 on GPIO25/26).
- **No "input-only" pins** on ESP32-S3 (all broken-out GPIOs are bidirectional).
- **OLED I2C bus moved internal** — V1/V2 reserved GPIO4/GPIO15 (broken-out pins); V3 uses GPIO17/GPIO18 internally and frees the corresponding header positions for general use.
- **LED moved** from GPIO25 (V1/V2) to GPIO35 (V3).
- **Vext control moved** from GPIO21 (V2) to GPIO36 (V3); GPIO21 is now OLED_RST instead.
- **Battery sense moved** from GPIO13 (V2) to GPIO1 (V3), gated by GPIO37 (ADC_Ctrl).
- **Strapping pins:** GPIO0, GPIO45, GPIO46 (different from ESP32 strapping set).

### GPIO Classification

**OLED-reserved (internal, do not reuse):** GPIO17, GPIO18
**OLED RST (header, reserved if using on-board OLED):** GPIO21
**Programming UART (avoid for general use):** GPIO43 (TX), GPIO44 (RX)
**Boot/strapping (use with care):** GPIO0, GPIO45, GPIO46
**USB D+/D− (only connected to USB socket if R29/R3 soldered):** GPIO20, GPIO19
**On-board LED:** GPIO35
**Vext enable:** GPIO36
**ADC enable for battery sense:** GPIO37
**Battery voltage:** GPIO1 (still usable as GPIO/touch/ADC otherwise)
**Free for general use (broken out):** GPIO2, GPIO3, GPIO4, GPIO5, GPIO6, GPIO7, GPIO19, GPIO20, GPIO26, GPIO33, GPIO34, GPIO38, GPIO39, GPIO40, GPIO41, GPIO42, GPIO47, GPIO48

### Sources
- Official datasheet (HTIT-WB32_V3 Rev 1.1): https://resource.heltec.cn/download/WiFi_Kit_32_V3/HTIT-WiFi%20kit32_V3(Rev1.1).pdf
- Product page: https://heltec.org/project/wifi-kit32-v3/
- ESP32-S3 datasheet: https://www.espressif.com/sites/default/files/documentation/esp32-s3_datasheet_en.pdf

---

## SN75160BDW — GPIB Data Bus Transceiver (SOIC-20)

KiCad symbol: `Interface:SN75160BDW`
KiCad footprint: `Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm`

### Pinout

| Pin | Name | Function |
|-----|------|----------|
| 1 | TE | Talk Enable (input) — HIGH=transmit, LOW=receive |
| 2 | B1 | GPIB bus DIO1 |
| 3 | B2 | GPIB bus DIO2 |
| 4 | B3 | GPIB bus DIO3 |
| 5 | B4 | GPIB bus DIO4 |
| 6 | B5 | GPIB bus DIO5 |
| 7 | B6 | GPIB bus DIO6 |
| 8 | B7 | GPIB bus DIO7 |
| 9 | B8 | GPIB bus DIO8 |
| 10 | GND | Ground |
| 11 | ~{PE} | Pull-up Enable (input) — active LOW. Tie to VCC for 3-state mode |
| 12 | D8 | Terminal DIO8 (MCU side) |
| 13 | D7 | Terminal DIO7 |
| 14 | D6 | Terminal DIO6 |
| 15 | D5 | Terminal DIO5 |
| 16 | D4 | Terminal DIO4 |
| 17 | D3 | Terminal DIO3 |
| 18 | D2 | Terminal DIO2 |
| 19 | D1 | Terminal DIO1 |
| 20 | VCC | +5V supply (4.75-5.25V) |

**Notes:** D-side pins are in reverse order (D8=pin12, D1=pin19). B-side (bus) is B1=pin2 to B8=pin9.

### Source
- TI Datasheet: https://www.ti.com/lit/ds/symlink/sn75160b.pdf

---

## SN75161BN — GPIB Control Bus Transceiver (DIP-20)

**Not in KiCad 9.0 standard library — custom symbol required.**

### Pinout

| Pin | Name | Function |
|-----|------|----------|
| 1 | TE | Talk Enable (input) — controls DAV, NRFD, NDAC direction |
| 2 | REN (bus) | Remote Enable — GPIB bus side |
| 3 | IFC (bus) | Interface Clear — GPIB bus side |
| 4 | NDAC (bus) | Not Data Accepted — GPIB bus side |
| 5 | NRFD (bus) | Not Ready For Data — GPIB bus side |
| 6 | DAV (bus) | Data Valid — GPIB bus side |
| 7 | EOI (bus) | End Or Identify — GPIB bus side |
| 8 | ATN (bus) | Attention — GPIB bus side |
| 9 | SRQ (bus) | Service Request — GPIB bus side |
| 10 | GND | Ground |
| 11 | DC | Direction Control (input) — controls ATN, SRQ, REN, IFC direction |
| 12 | SRQ (term) | Service Request — terminal/MCU side |
| 13 | ATN (term) | Attention — terminal side |
| 14 | EOI (term) | End Or Identify — terminal side |
| 15 | DAV (term) | Data Valid — terminal side |
| 16 | NRFD (term) | Not Ready For Data — terminal side |
| 17 | NDAC (term) | Not Data Accepted — terminal side |
| 18 | IFC (term) | Interface Clear — terminal side |
| 19 | REN (term) | Remote Enable — terminal side |
| 20 | VCC | +5V supply (4.75-5.25V) |

**Direction control:**
- TE controls direction of DAV, NRFD, NDAC
- DC controls direction of ATN, SRQ, REN, IFC
- EOI direction controlled by TE AND DC jointly

### Source
- TI Datasheet: https://www.ti.com/lit/ds/symlink/sn75161b.pdf

---

## GPIB IEEE-488 Centronics 24-Pin Connector Pinout

| Pin | Signal | Type | Pin | Signal | Type |
|-----|--------|------|-----|--------|------|
| 1 | DIO1 | Data | 13 | DIO5 | Data |
| 2 | DIO2 | Data | 14 | DIO6 | Data |
| 3 | DIO3 | Data | 15 | DIO7 | Data |
| 4 | DIO4 | Data | 16 | DIO8 | Data |
| 5 | EOI | Management | 17 | REN | Management |
| 6 | DAV | Handshake | 18 | GND (DAV ret) | Ground |
| 7 | NRFD | Handshake | 19 | GND (NRFD ret) | Ground |
| 8 | NDAC | Handshake | 20 | GND (NDAC ret) | Ground |
| 9 | IFC | Management | 21 | GND (IFC ret) | Ground |
| 10 | SRQ | Management | 22 | GND (SRQ ret) | Ground |
| 11 | ATN | Management | 23 | GND (ATN ret) | Ground |
| 12 | SHIELD | Ground | 24 | GND (Logic) | Ground |

**Ground pins:** 12, 18, 19, 20, 21, 22, 23, 24

### Source
- IEEE 488.1 standard
- NI GPIB concepts: https://www.ni.com/docs/en-US/bundle/gpib-help/page/gpib-concepts/gpib_concepts.html

---

## MCP23017 — I2C 16-bit GPIO Expander

KiCad symbol: `Interface_Expansion:MCP23017_SO` (SOIC-28)
KiCad footprint: `Package_SO:SOIC-28W_7.5x17.9mm_P1.27mm`

- **I2C speed:** up to 1.7 MHz
- **VCC range:** 1.8V–5.5V (works at 3.3V)
- **Outputs:** 25mA push-pull per pin
- **Interrupt:** per-pin configurable, active-low/high or open-drain
- **Address pins:** A0, A1, A2 — up to 8 devices on one bus (base address 0x20)
- **Latency:** ~20µs per byte at 1 MHz I2C

### Source
- Microchip datasheet: https://ww1.microchip.com/downloads/en/DeviceDoc/20001952C.pdf

---

## Tektronix TDS784A — GPIB Performance

- **GPIB standard:** IEEE-488.2, supports HS488
- **Transfer rate:** 200–500 KB/s sustained (standard mode), up to 1.2 MB/s with HS488
- **Handshake cycle:** 2–5 µs (standard), 1–2 µs (HS488)
- **Classification:** Fast GPIB instrument (NOT slow despite some claims)
- **HS488 T1:** 350 ns minimum

### Source
- Tek programmer manual: https://www.tek.com/en/manual/tds784a-tds784c-tds784d-programmer-manual
- NI HS488: https://www.ni.com/docs/en-US/bundle/gpib-help/page/gpib-concepts/hs488-protocol.html

---

## Architecture Decision: Hybrid GPIO + MCP23017

### Signal Split

**Direct ESP32 GPIOs (fast path — 15 signals):**
- DIO1–DIO8 (8 data lines) — change every byte
- DAV, NRFD, NDAC (3 handshake lines) — change every byte
- EOI (1 line) — end-of-message detection
- TE_data (1 line) — SN75160B talk enable
- I2C SDA, SCL (2 lines) — for MCP23017

**MCP23017 (slow path — 5 signals, accessed only on mode changes):**
- ATN — once per command sequence
- IFC — once per session (bus reset)
- SRQ — occasional polling
- REN — once per session
- TE_ctrl (SN75161B talk enable)
- DC (SN75161B direction control)

**Total ESP32 GPIOs used: 15** (13 signals + 2 I2C). Available: 16. **1 spare.**

**Result:** Zero I2C overhead during data transfer. Full TDS784A speed preserved.

---

## Reverse Polarity Protection — P-FET (AO3401A)

Instead of a Schottky diode (~300mV drop), use a P-channel MOSFET for near-zero dropout protection.

**Selected part: AO3401A** (SOT-23)
- Vds: -30V (plenty of margin for 12V input)
- Rds(on): 60mΩ typ @ Vgs=-10V; ~75mΩ @ Vgs=-4.5V
- Vgs(th): -0.4V to -1.1V (logic-level)
- Vgs max: **±12V** — at 12V input this is right at the limit; add a Zener clamp (e.g. 10V) Gate↔Source if input may exceed 12V
- Id: -4A continuous (limited by SOT-23 package thermals)
- Voltage drop @ 200mA: **~15mV** (vs ~300mV for Schottky — still excellent)
- Package: SOT-23 (pin 1 = Gate, pin 2 = Source, pin 3 = Drain)
- KiCad symbol: **custom required** (not in KiCad 9.0 standard library — generic `Device:Q_PMOS_GSD` works as a stand-in)
- Datasheet: https://www.aosmd.com/res/datasheets/AO3401A.pdf

**Circuit:**
- Source → barrel jack V+ (7-12V)
- Drain → AMS1117-5.0 VIN
- Gate → GND via 100kΩ pull-down resistor (R_gate)

**How it works:** Normal polarity: Vgs is large negative → FET fully on, millivolt drop. Reverse polarity: Vgs ≥ 0 → FET off, body diode reverse-biased, no current flows.

### Sources
- AO3401A datasheet: https://www.aosmd.com/sites/default/files/res/datasheets/AO3401A.pdf
- Design guide: https://components101.com/articles/design-guide-pmos-mosfet-for-reverse-voltage-polarity-protection

---

## KiCad Component Summary

| Component | KiCad Symbol | KiCad Footprint | In Std Library? |
|-----------|-------------|-----------------|-----------------|
| SN75160BDW | `Interface:SN75160BDW` | `Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm` | Yes |
| SN75161BN | **Custom required** | `Package_DIP:DIP-20_W7.62mm` | No |
| AMS1117-5.0 | `Regulator_Linear:AMS1117-5.0` | `Package_TO_SOT_SMD:SOT-223-3_TabPin2` | Yes |
| MCP23017 (SOIC) | `Interface_Expansion:MCP23017_SO` | `Package_SO:SOIC-28W_7.5x17.9mm_P1.27mm` | Yes |
| Barrel Jack | `Connector:Barrel_Jack` | `Connector_BarrelJack:BarrelJack_Horizontal` | Yes |
| 2x18 pin header | `Connector_Generic:Conn_02x18_Odd_Even` | custom (22.86mm spacing) | Symbol yes |
| 2x12 connector | `Connector_Generic:Conn_02x12_Odd_Even` | custom (Centronics 24) | Symbol yes |
| AO3401A (P-FET) | **Custom required** | `Package_TO_SOT_SMD:SOT-23` | No |
| Cap 0805 | `Device:C` | `Capacitor_SMD:C_0805_2012Metric` | Yes |
| Cap 0603 | `Device:C` | `Capacitor_SMD:C_0603_1608Metric` | Yes |
| Resistor 0603 | `Device:R` | `Resistor_SMD:R_0603_1608Metric` | Yes |
