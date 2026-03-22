## 1.0 general design
Using kicad, design a circuit similar to the https://oshpark.com/profiles/artag ar488promicro
A sibling work is in https://github.com/artgodwin/AR488-32u4-PCB, these 2 examples should be use only to have a layout example as all the details are wrong.
The main idea is to have the PCB parallel to the back of the plug. Keep the 2 holes spaced 46.3 mm on each side of the length of the connector. The PCB length in the direction of the connector is 11cm maximum with the connector at the center. The PCB width can extend 1.5cm from the connector center on the side of pins 1 to 12, the PCB width can extend 4.5 cm on the side of pins 13-24.

### 1.0.1 Architecture decisions

**Target instrument:** Tektronix TDS784A (fast GPIB instrument, 200-500 KB/s).

**GPIO hybrid architecture:** The Heltec WiFi Kit 32 V2 has only 16 bidirectional GPIOs available (OLED uses GPIO4/15/16). GPIB needs 18+ signals. Solution: use an MCP23017 I2C GPIO expander (SOIC-28) for slow management signals, keeping data and handshake lines on direct GPIOs for zero-latency data transfer.

**Signal split:**
- **Direct ESP32 GPIOs (fast path):** DIO1-DIO8 (8 data), DAV, NRFD, NDAC (3 handshake), EOI (1 end-of-message), TE_data (1 SN75160B talk enable), I2C SDA/SCL (2) = 15 GPIOs
- **MCP23017 (slow path, accessed only on mode changes):** ATN, IFC, SRQ, REN, TE_ctrl (SN75161B talk enable), DC (SN75161B direction control) = 6 signals

**TE lines:** Separate — TE_data on direct GPIO for SN75160B, TE_ctrl on MCP23017 for SN75161B.

**Level shifting:** Direct 3.3V to 5V TTL connection (no level shifters). ESP32 3.3V outputs exceed SN7516x D-side TTL HIGH threshold (~1.5V).

**GPIO assignments:**

| Signal | ESP32 GPIO | Destination |
|--------|-----------|-------------|
| DIO1 | GPIO13 | SN75160B D1 (pin 19) |
| DIO2 | GPIO12 | SN75160B D2 (pin 18) |
| DIO3 | GPIO14 | SN75160B D3 (pin 17) |
| DIO4 | GPIO27 | SN75160B D4 (pin 16) |
| DIO5 | GPIO26 | SN75160B D5 (pin 15) |
| DIO6 | GPIO25 | SN75160B D6 (pin 14) |
| DIO7 | GPIO33 | SN75160B D7 (pin 13) |
| DIO8 | GPIO32 | SN75160B D8 (pin 12) |
| TE_data | GPIO17 | SN75160B TE (pin 1) |
| DAV | GPIO5 | SN75161B DAV term (pin 15) |
| NRFD | GPIO18 | SN75161B NRFD term (pin 16) |
| NDAC | GPIO23 | SN75161B NDAC term (pin 17) |
| EOI | GPIO19 | SN75161B EOI term (pin 14) |
| I2C SDA | GPIO21 | MCP23017 SDA |
| I2C SCL | GPIO22 | MCP23017 SCL |

| Signal | MCP23017 Pin | Destination |
|--------|-------------|-------------|
| ATN | GPA0 | SN75161B ATN term (pin 13) |
| IFC | GPA1 | SN75161B IFC term (pin 18) |
| SRQ | GPA2 | SN75161B SRQ term (pin 12) |
| REN | GPA3 | SN75161B REN term (pin 19) |
| TE_ctrl | GPA4 | SN75161B TE (pin 1) |
| DC | GPA5 | SN75161B DC (pin 11) |

### 1.1 specific component footprints
#### 1.1.1 Centronics 24 pin plug
The centronics 24 plug is a solder type with 2 raws of 12 pins, each pin is 1.45 mm in diameter, this leads to a pcb hole diameter of 1.5mm, the spacing between each of the 12 pins in a row is 2.159mm center to center, the spacing center to center between the 2 rows is 4.45mm.
#### 1.1.2 Microprocessor module
The microprocessor module is an ESP32 Wifi Kit 32 V2 from Heltec, based on ESP32 with built-in OLED display. The mechanical interface is 2 rows of 18 pin headers spaced 22.86mm, 2.54mm pitch. The module has a 5V pin (from USB) on the right header, position 2.
#### 1.1.3 interface ICs
Due to voltage requirements of the bus, there need to be
- SN75160B — Data Bus (8 lines)
This IC is available in smd, reference SN75160BDWR (SOIC-20W)
KiCad symbol: `Interface:SN75160BDW`
Handling DIO1–DIO8 Bidirectional. ~PE pin tied to VCC (3-state mode).

Direction pin (TE) selects talk/listen mode.
- SN75161B — Control Bus
This IC is only available in DIP20 reference SN75161BN
KiCad symbol: custom (not in standard library)
Handling the management lines:

  - ATN
  - DAV
  - NRFD
  - NDAC
  - IFC
  - SRQ
  - REN
  - EOI

Direction controlled by TE (handshake lines) and DC (management lines).

#### 1.1.4 I2C GPIO expander
MCP23017 in SOIC-28 package. KiCad symbol: `Interface_Expansion:MCP23017_SO`.
I2C address 0x20 (A0=A1=A2=GND). RESET pin tied to VCC via 10kΩ pullup.
Handles slow management signals (ATN, IFC, SRQ, REN, TE_ctrl, DC) — accessed only during bus mode changes, not during data transfer.

#### 1.1.5 Power supply
5V power is either supplied to the microprocessor module through USB, or through a 5.5mm barrel jack (7-12V DC input).

**Reverse polarity protection:** AO4407A P-channel MOSFET (SOIC-8). Source to jack V+, drain to LDO input, gate to GND via 100kΩ resistor. Near-zero voltage drop (~2.4mV at 200mA) vs ~300mV for a Schottky diode.

**Voltage regulation:** AMS1117-5.0 LDO in SOT-223 package. Input capacitor: 10µF ceramic 0805. Output capacitor: 10µF ceramic 0603.

**Decoupling capacitors:**
- SN75160B: 100nF 0603 + 22µF 0603
- SN75161B: 100nF 0603 + 22µF 0603
- MCP23017: 100nF 0603
