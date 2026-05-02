// AR-488-ESP32 GPIB pin test firmware
//
// Pulses each GPIB *bus* signal HIGH for 1 ms, one at a time, with the
// SN7516x transceivers held in Talk mode so each pulse propagates from
// the ESP32 side to the GPIB connector.
//
// Direction control (held throughout the test, NOT pulsed):
//   TE_DATA = HIGH   SN75160B in Talk     (ESP32 -> bus, DIO1..8)
//   TE_CTRL = HIGH   SN75161B handshake   (ESP32 -> bus, DAV/NRFD/NDAC/EOI)
//   DC      = LOW    SN75161B controller  (ESP32 -> bus, ATN/IFC/REN; SRQ in)
//   DC      = HIGH   SN75161B device      (ESP32 -> bus, SRQ; ATN/IFC/REN in)
//
// Hardware: Heltec WiFi Kit 32 V2 (ESP32) on the AR-488-ESP32 board.

#include <Arduino.h>
#include <Wire.h>

static constexpr uint8_t I2C_SDA_PIN   = 21;
static constexpr uint8_t I2C_SCL_PIN   = 22;
static constexpr uint8_t MCP23017_ADDR = 0x20;

// MCP23017 registers (BANK=0, default)
static constexpr uint8_t MCP_IODIRA = 0x00;
static constexpr uint8_t MCP_OLATA  = 0x14;

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

struct DirectPin {
    const char* name;
    uint8_t     gpio;
};

struct McpPin {
    const char* name;
    uint8_t     bit;
};

// GPIB bus signals on direct GPIOs (data + handshake + EOI)
static const DirectPin kBusDirect[] = {
    {"DIO1", 13},
    {"DIO2", 12},
    {"DIO3", 14},
    {"DIO4", 27},
    {"DIO5", 26},
    {"DIO6", 25},
    {"DIO7", 33},
    {"DIO8", 32},
    {"DAV",   5},
    {"NRFD", 18},
    {"NDAC", 23},
    {"EOI",  19},
};

// GPIB bus signals on MCP23017 that the controller drives outward when DC=LOW
static const McpPin kBusMcpController[] = {
    {"ATN", MCP_BIT_ATN},
    {"IFC", MCP_BIT_IFC},
    {"REN", MCP_BIT_REN},
};

// GPIB bus signals on MCP23017 that the device drives outward when DC=HIGH
static const McpPin kBusMcpDevice[] = {
    {"SRQ", MCP_BIT_SRQ},
};

// Holds current OLATA contents so we never clobber TE_CTRL / DC when
// pulsing other bits.
static uint8_t g_mcpOlat = 0;

static bool mcpWrite(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(MCP23017_ADDR);
    Wire.write(reg);
    Wire.write(value);
    return Wire.endTransmission() == 0;
}

static bool mcpSetOlat(uint8_t value) {
    g_mcpOlat = value;
    return mcpWrite(MCP_OLATA, value);
}

static bool mcpSetBit(uint8_t bit, bool high) {
    uint8_t v = g_mcpOlat;
    if (high) {
        v |= (1u << bit);
    } else {
        v &= ~(1u << bit);
    }
    return mcpSetOlat(v);
}

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println();
    Serial.println("AR-488-ESP32 GPIB pin test");

    // Drive direct bus signals LOW first (boot-strap safety for GPIO12 = DIO2).
    for (const auto& p : kBusDirect) {
        pinMode(p.gpio, OUTPUT);
        digitalWrite(p.gpio, LOW);
    }

    // SN75160B: hold TE_DATA HIGH for the entire test (Talk mode).
    pinMode(GPIO_TE_DATA, OUTPUT);
    digitalWrite(GPIO_TE_DATA, HIGH);

    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    Wire.setClock(100000);

    Serial.println("I2C scan 0x03..0x77:");
    uint8_t found = 0;
    for (uint8_t addr = 0x03; addr <= 0x77; ++addr) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            Serial.printf("  ACK at 0x%02X\n", addr);
            ++found;
        }
    }
    Serial.printf("I2C scan done, %u device(s) found.\n", found);

    // GPIOA: all outputs.
    if (!mcpWrite(MCP_IODIRA, 0x00)) {
        Serial.println("WARNING: MCP23017 not responding at 0x20 - MCP pulses will be no-ops.");
    } else {
        Serial.println("MCP23017 initialized at 0x20.");
    }

    // SN75161B: TE_CTRL = HIGH (Talk for handshake), DC = LOW (controller).
    // All bus bits start LOW.
    mcpSetOlat((1u << MCP_BIT_TE_CTRL));
    Serial.println("Transceivers in Talk mode: TE_DATA=H, TE_CTRL=H, DC=L (controller).");
}

static void pulseDirect(const DirectPin& p) {
    Serial.printf("  %-5s GPIO%-2u\n", p.name, p.gpio);
    digitalWrite(p.gpio, HIGH);
    delay(PULSE_MS);
    digitalWrite(p.gpio, LOW);
}

static void pulseMcp(const McpPin& p) {
    Serial.printf("  %-5s GPA%u\n", p.name, p.bit);
    mcpSetBit(p.bit, true);
    delay(PULSE_MS);
    mcpSetBit(p.bit, false);
}

void loop() {
    // Phase 1: controller mode (DC = LOW).
    Serial.println("Sweep: data + handshake + controller-driven management");
    mcpSetBit(MCP_BIT_DC, false);
    for (const auto& p : kBusDirect) {
        pulseDirect(p);
    }
    for (const auto& p : kBusMcpController) {
        pulseMcp(p);
    }

    // Phase 2: device mode (DC = HIGH) so SRQ is driven outward.
    Serial.println("Sweep: device-driven management (SRQ)");
    mcpSetBit(MCP_BIT_DC, true);
    for (const auto& p : kBusMcpDevice) {
        pulseMcp(p);
    }

    // Restore controller mode for the next iteration.
    mcpSetBit(MCP_BIT_DC, false);

    delay(CYCLE_MS);
}
