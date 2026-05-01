// AR-488-ESP32 GPIB pin test firmware
//
// Pulses each GPIB *bus* signal HIGH for 1 ms, one at a time, in
// **GPIB connector pin order** (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
// 13, 14, 15, 16, 17), with the SN7516x transceivers held in Talk
// mode so each pulse propagates from the ESP32 side to the GPIB
// connector.
//
// Direction control:
//   TE_DATA = HIGH   SN75160B in Talk     (ESP32 -> bus, DIO1..8)
//   TE_CTRL = HIGH   SN75161B handshake   (ESP32 -> bus, DAV/NRFD/NDAC/EOI)
//   DC      = LOW    SN75161B controller  (ESP32 -> bus, ATN/IFC/REN)
//   DC      = HIGH   SN75161B device      (ESP32 -> bus, SRQ)
// DC is toggled on the fly so each MCP-driven signal is pulsed in the
// correct transceiver direction.
//
// Hardware: Heltec WiFi Kit 32 V2 (ESP32) on the AR-488-ESP32 board.

#include <Arduino.h>
#include <Wire.h>

static constexpr uint8_t I2C_SDA_PIN   = 21;
static constexpr uint8_t I2C_SCL_PIN   = 22;
static constexpr uint8_t MCP23017_ADDR = 0x20;

// MCP23017 registers (BANK=0, default)
static constexpr uint8_t MCP_IODIRA = 0x00;
static constexpr uint8_t MCP_IODIRB = 0x01;
static constexpr uint8_t MCP_OLATA  = 0x14;
static constexpr uint8_t MCP_OLATB  = 0x15;

// MCP23017 GPIOA bit assignments
static constexpr uint8_t MCP_BIT_ATN     = 0;
static constexpr uint8_t MCP_BIT_IFC     = 1;
static constexpr uint8_t MCP_BIT_SRQ     = 2;
static constexpr uint8_t MCP_BIT_REN     = 3;
static constexpr uint8_t MCP_BIT_TE_CTRL = 4;
static constexpr uint8_t MCP_BIT_DC      = 5;

// Direct ESP32 GPIO assignments
static constexpr uint8_t GPIO_TE_DATA = 17;

static constexpr uint32_t PULSE_MS = 1;
static constexpr uint32_t CYCLE_MS = 20;

enum SrcType : uint8_t { SRC_DIRECT, SRC_MCP };

// One entry per GPIB signal pin, ordered by GPIB connector pin number.
//   id      = ESP32 GPIO if SRC_DIRECT, MCP port-A bit if SRC_MCP
//   dcHigh  = required SN75161B DC level for this pulse (only used when SRC_MCP)
struct PinSpec {
    const char* name;
    uint8_t     gpibPin;
    SrcType     src;
    uint8_t     id;
    bool        dcHigh;
};

static const PinSpec kSequence[] = {
    {"DIO1",  1, SRC_DIRECT, 13,           false},
    {"DIO2",  2, SRC_DIRECT, 12,           false},
    {"DIO3",  3, SRC_DIRECT, 14,           false},
    {"DIO4",  4, SRC_DIRECT, 27,           false},
    {"EOI",   5, SRC_DIRECT, 19,           false},
    {"DAV",   6, SRC_DIRECT,  5,           false},
    {"NRFD",  7, SRC_DIRECT, 18,           false},
    {"NDAC",  8, SRC_DIRECT, 23,           false},
    {"IFC",   9, SRC_MCP,    MCP_BIT_IFC,  false},  // controller drives
    {"SRQ",  10, SRC_MCP,    MCP_BIT_SRQ,  true},   // device drives -> DC=HIGH
    {"ATN",  11, SRC_MCP,    MCP_BIT_ATN,  false},  // controller drives
    {"DIO5", 13, SRC_DIRECT, 26,           false},
    {"DIO6", 14, SRC_DIRECT, 25,           false},
    {"DIO7", 15, SRC_DIRECT, 33,           false},
    {"DIO8", 16, SRC_DIRECT, 32,           false},
    {"REN",  17, SRC_MCP,    MCP_BIT_REN,  false},  // controller drives
};

// Hold current OLATA contents so we never clobber sticky bits
// (TE_CTRL / DC) when pulsing other bits.
static uint8_t g_mcpOlatA = 0;

static bool mcpWrite(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(MCP23017_ADDR);
    Wire.write(reg);
    Wire.write(value);
    return Wire.endTransmission() == 0;
}

static bool mcpSetOlatA(uint8_t value) {
    g_mcpOlatA = value;
    return mcpWrite(MCP_OLATA, value);
}

static bool mcpSetBitA(uint8_t bit, bool high) {
    uint8_t v = g_mcpOlatA;
    if (high) v |= (1u << bit); else v &= ~(1u << bit);
    return mcpSetOlatA(v);
}

static void pulse(const PinSpec& s) {
    if (s.src == SRC_MCP) {
        // TEST: drive DC HIGH only during SRQ pulse, with 1 ms settle margins.
        bool flipDc = (strcmp(s.name, "SRQ") == 0);
        Serial.printf("  pin %2u  %-5s GPA%u%s\n",
                      s.gpibPin, s.name, s.id, flipDc ? " (DC=H)" : "");
        if (flipDc) { mcpSetBitA(MCP_BIT_DC, true); delay(1); }
        mcpSetBitA(s.id, true);
        delay(PULSE_MS);
        mcpSetBitA(s.id, false);
        if (flipDc) { delay(1); mcpSetBitA(MCP_BIT_DC, false); }
    } else {
        Serial.printf("  pin %2u  %-5s GPIO%-2u\n", s.gpibPin, s.name, s.id);
        digitalWrite(s.id, HIGH);
        delay(PULSE_MS);
        digitalWrite(s.id, LOW);
    }
}

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println();
    Serial.println("AR-488-ESP32 GPIB pin test (sweep in connector pin order)");

    // Drive direct bus signals LOW first (boot-strap safety for GPIO12 = DIO2).
    for (const auto& s : kSequence) {
        if (s.src == SRC_DIRECT) {
            pinMode(s.id, OUTPUT);
            digitalWrite(s.id, LOW);
        }
    }

    // TEST: hold TE_DATA HIGH (Talk mode for SN75160B).
    pinMode(GPIO_TE_DATA, OUTPUT);
    digitalWrite(GPIO_TE_DATA, HIGH);

    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    Wire.setClock(400000);

    // GPIOA = outputs (used). GPIOB = outputs forced LOW (unused on the board;
    // tied LOW rather than left as floating inputs to avoid shoot-through current
    // and supply ripple inside the chip).
    bool ok = mcpWrite(MCP_OLATB, 0x00)
           && mcpWrite(MCP_IODIRB, 0x00)
           && mcpWrite(MCP_IODIRA, 0x00);
    if (!ok) {
        Serial.println("WARNING: MCP23017 not responding at 0x20 - MCP pulses will be no-ops.");
    } else {
        Serial.println("MCP23017 initialized at 0x20 (GPIOA outputs, GPIOB tied LOW).");
    }

    // TEST: TE_CTRL = HIGH (Talk), DC = LOW. Other port-A bits start LOW.
    mcpSetOlatA((1u << MCP_BIT_TE_CTRL));
    Serial.println("TEST: TE_DATA=H, TE_CTRL=H, DC=L (transceivers in Talk, controller).");
}

void loop() {
    Serial.println("Sweep:");
    for (const auto& s : kSequence) {
        pulse(s);
    }
    delay(CYCLE_MS);
}
