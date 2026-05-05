#include "GpibBus.h"

#include <Wire.h>
#include <string.h>

// --------------------------------------------------------------------------
// Pinout — must match firmware/HARDWARE.md.

static constexpr uint8_t I2C_SDA_PIN   = 21;
static constexpr uint8_t I2C_SCL_PIN   = 22;
static constexpr uint8_t MCP23017_ADDR = 0x20;

static constexpr uint8_t MCP_IODIRA = 0x00;
static constexpr uint8_t MCP_IODIRB = 0x01;
static constexpr uint8_t MCP_OLATA  = 0x14;
static constexpr uint8_t MCP_OLATB  = 0x15;

static constexpr uint8_t MCP_BIT_ATN     = 0;
static constexpr uint8_t MCP_BIT_IFC     = 1;
static constexpr uint8_t MCP_BIT_SRQ     = 2;
static constexpr uint8_t MCP_BIT_REN     = 3;
static constexpr uint8_t MCP_BIT_TE_CTRL = 4;
static constexpr uint8_t MCP_BIT_DC      = 5;

// 8-bit GPIB data bus, indexed by DIO1..DIO8.
static constexpr uint8_t kDioPin[8] = {
    13, 12, 14, 27, 26, 25, 33, 32
};

static constexpr uint8_t GPIO_DAV     = 5;
static constexpr uint8_t GPIO_NRFD    = 18;
static constexpr uint8_t GPIO_NDAC    = 23;
static constexpr uint8_t GPIO_EOI     = 19;
static constexpr uint8_t GPIO_TE_DATA = 17;

// --------------------------------------------------------------------------
// MCP23017 helpers.

bool GpibBus::mcpWrite(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(MCP23017_ADDR);
    Wire.write(reg);
    Wire.write(value);
    return Wire.endTransmission() == 0;
}

bool GpibBus::mcpSetOlatA(uint8_t v) {
    mcpOlatA_ = v;
    return mcpWrite(MCP_OLATA, v);
}

bool GpibBus::mcpSetBitA(uint8_t bit, bool high) {
    uint8_t v = mcpOlatA_;
    if (high) v |= (1u << bit);
    else      v &= ~(1u << bit);
    return mcpSetOlatA(v);
}

// --------------------------------------------------------------------------
// Data bus.

void GpibBus::setDataDir(bool output) {
    for (uint8_t i = 0; i < 8; ++i) {
        if (output) {
            pinMode(kDioPin[i], OUTPUT);
            digitalWrite(kDioPin[i], HIGH);     // released
        } else {
            pinMode(kDioPin[i], INPUT);
        }
    }
}

void GpibBus::writeData(uint8_t b) {
    // Bus is negative-true; transceiver is non-inverting -> invert in SW.
    uint8_t inv = ~b;
    for (uint8_t i = 0; i < 8; ++i) {
        digitalWrite(kDioPin[i], (inv >> i) & 0x01 ? HIGH : LOW);
    }
}

uint8_t GpibBus::readData() {
    uint8_t v = 0;
    for (uint8_t i = 0; i < 8; ++i) {
        if (digitalRead(kDioPin[i])) v |= (1u << i);
    }
    return ~v;
}

// --------------------------------------------------------------------------
// Direction control.

void GpibBus::setTalker() {
    if (talker_) return;

    // Drive handshake outputs to released BEFORE flipping TE_CTRL, so we
    // don't briefly assert DAV/EOI on the bus when SN75161B switches.
    digitalWrite(GPIO_DAV, HIGH);
    digitalWrite(GPIO_EOI, HIGH);
    pinMode(GPIO_DAV, OUTPUT);
    pinMode(GPIO_EOI, OUTPUT);
    pinMode(GPIO_NRFD, INPUT);
    pinMode(GPIO_NDAC, INPUT);

    digitalWrite(GPIO_TE_DATA, HIGH);           // SN75160B Talk (DIO out)
    setDataDir(true);

    mcpSetBitA(MCP_BIT_TE_CTRL, true);          // SN75161B handshake Talk
    delayMicroseconds(2);
    talker_ = true;
}

void GpibBus::setListener() {
    if (!talker_) return;

    // Pre-load the handshake outputs we'll be driving as listener.
    digitalWrite(GPIO_NRFD, LOW);               // not ready
    digitalWrite(GPIO_NDAC, LOW);               // not accepted
    pinMode(GPIO_NRFD, OUTPUT);
    pinMode(GPIO_NDAC, OUTPUT);
    pinMode(GPIO_DAV, INPUT);
    pinMode(GPIO_EOI, INPUT);

    digitalWrite(GPIO_TE_DATA, LOW);            // SN75160B Listen (DIO in)
    setDataDir(false);

    mcpSetBitA(MCP_BIT_TE_CTRL, false);         // SN75161B handshake Listen
    delayMicroseconds(2);
    talker_ = false;
}

void GpibBus::assertATN()    { mcpSetBitA(MCP_BIT_ATN,  false); }
void GpibBus::releaseATN()   { mcpSetBitA(MCP_BIT_ATN,  true);  }
void GpibBus::assertIFC()    { mcpSetBitA(MCP_BIT_IFC,  false); }
void GpibBus::releaseIFC()   { mcpSetBitA(MCP_BIT_IFC,  true);  }
void GpibBus::assertREN()    { mcpSetBitA(MCP_BIT_REN,  false); }
void GpibBus::releaseREN()   { mcpSetBitA(MCP_BIT_REN,  true);  }

// --------------------------------------------------------------------------
// Initialisation.

bool GpibBus::begin() {
    // Boot-strap safety: GPIO12 (DIO2) must be LOW. Done first so the
    // SN75160B can't back-drive it before we get TE_DATA defined.
    pinMode(12, OUTPUT);
    digitalWrite(12, LOW);

    pinMode(GPIO_TE_DATA, OUTPUT);
    digitalWrite(GPIO_TE_DATA, HIGH);           // SN75160B Talk

    // Default release state for the direct handshake outputs.
    pinMode(GPIO_DAV, OUTPUT);  digitalWrite(GPIO_DAV, HIGH);
    pinMode(GPIO_EOI, OUTPUT);  digitalWrite(GPIO_EOI, HIGH);
    pinMode(GPIO_NRFD, INPUT);
    pinMode(GPIO_NDAC, INPUT);
    setDataDir(true);                           // DIO outputs, released (HIGH)
    talker_ = true;

    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    Wire.setClock(400000);

    // GPIOA = outputs (used). GPIOB = outputs forced LOW (unused on board).
    bool ok = mcpWrite(MCP_OLATB, 0x00)
           && mcpWrite(MCP_IODIRB, 0x00)
           && mcpWrite(MCP_IODIRA, 0x00);
    if (!ok) return false;

    // ATN/IFC/SRQ/REN released (=HIGH=1), TE_CTRL=H (Talk), DC=L (controller).
    // bits 0..4 = 1, bit 5 = 0  ->  0x1F.
    if (!mcpSetOlatA(0x1F)) return false;

    mtx_ = xSemaphoreCreateMutex();
    return mtx_ != nullptr;
}

bool GpibBus::lock(uint32_t timeoutMs) {
    if (!mtx_) return false;
    return xSemaphoreTake(mtx_, pdMS_TO_TICKS(timeoutMs)) == pdTRUE;
}

void GpibBus::unlock() {
    if (mtx_) xSemaphoreGive(mtx_);
}

bool GpibBus::controllerInit() {
    if (!lock()) return false;
    setTalker();
    releaseATN();
    assertIFC();
    delay(1);                                    // IFC must be >100us; 1ms is generous
    releaseIFC();
    assertREN();
    delay(1);
    unlock();
    return true;
}

// --------------------------------------------------------------------------
// Byte-level handshake.

bool GpibBus::writeByte(uint8_t b, bool eoi, uint32_t timeoutMs) {
    // wait NRFD released (HIGH = all listeners ready)
    uint32_t t0 = millis();
    while (digitalRead(GPIO_NRFD) == LOW) {
        if (millis() - t0 > timeoutMs) return false;
    }

    writeData(b);
    if (eoi) digitalWrite(GPIO_EOI, LOW);        // assert EOI
    delayMicroseconds(2);                        // T1 settle

    digitalWrite(GPIO_DAV, LOW);                 // assert DAV (data valid)

    // wait NDAC released (HIGH = all listeners accepted)
    t0 = millis();
    while (digitalRead(GPIO_NDAC) == LOW) {
        if (millis() - t0 > timeoutMs) {
            digitalWrite(GPIO_DAV, HIGH);
            if (eoi) digitalWrite(GPIO_EOI, HIGH);
            writeData(0xFF);                     // release DIO
            return false;
        }
    }

    digitalWrite(GPIO_DAV, HIGH);                // release DAV
    if (eoi) digitalWrite(GPIO_EOI, HIGH);
    writeData(0xFF);                             // release DIO between bytes
    return true;
}

bool GpibBus::readByte(uint8_t& b, bool& eoi, uint32_t timeoutMs) {
    // ready to receive
    digitalWrite(GPIO_NRFD, HIGH);

    // wait DAV asserted
    uint32_t t0 = millis();
    while (digitalRead(GPIO_DAV) == HIGH) {
        if (millis() - t0 > timeoutMs) {
            digitalWrite(GPIO_NRFD, LOW);
            return false;
        }
    }

    digitalWrite(GPIO_NRFD, LOW);                // not ready for next byte

    b = readData();
    eoi = (digitalRead(GPIO_EOI) == LOW);

    digitalWrite(GPIO_NDAC, HIGH);               // accepted

    // wait DAV released
    t0 = millis();
    while (digitalRead(GPIO_DAV) == LOW) {
        if (millis() - t0 > timeoutMs) {
            digitalWrite(GPIO_NDAC, LOW);
            return false;
        }
    }

    digitalWrite(GPIO_NDAC, LOW);                // back to not-accepted for next
    return true;
}

bool GpibBus::sendCommand(uint8_t cmd, uint32_t timeoutMs) {
    return writeByte(cmd, /*eoi=*/false, timeoutMs);
}

// --------------------------------------------------------------------------
// Addressing helpers.

bool GpibBus::addressTalk(uint8_t talker, uint8_t listener) {
    setTalker();
    assertATN();
    if (!sendCommand(CMD_UNL))           return false;
    if (!sendCommand(CMD_UNT))           return false;
    if (!sendCommand(LAD(listener)))     return false;
    if (!sendCommand(TAD(talker)))       return false;
    releaseATN();
    return true;
}

bool GpibBus::sendData(const char* data, size_t len) {
    for (size_t i = 0; i < len; ++i) {
        bool eoi = (i == len - 1);
        if (!writeByte((uint8_t)data[i], eoi, 2000)) return false;
    }
    return true;
}

bool GpibBus::sendBytes(const uint8_t* data, size_t len, uint32_t timeoutMs) {
    for (size_t i = 0; i < len; ++i) {
        bool eoi = (i == len - 1);
        if (!writeByte(data[i], eoi, timeoutMs)) return false;
    }
    return true;
}

// --------------------------------------------------------------------------
// High-level helpers.

bool GpibBus::detectDevice(uint8_t addr, uint32_t timeoutMs) {
    if (!lock()) return false;
    bool present = false;

    setTalker();
    assertATN();
    bool ok = sendCommand(CMD_UNL)
           && sendCommand(LAD(addr));
    if (ok) {
        // After addressing, an actual listener will assert NDAC LOW.
        // Without a device on the bus, NDAC floats HIGH (bus pull-ups).
        uint32_t t0 = millis();
        while (millis() - t0 < timeoutMs) {
            if (digitalRead(GPIO_NDAC) == LOW) { present = true; break; }
            delay(1);
        }
        sendCommand(CMD_UNL);
    }
    releaseATN();

    unlock();
    return present;
}

bool GpibBus::send(uint8_t addr, const char* cmd) {
    if (!lock()) return false;
    bool ok = addressTalk(/*talker=*/CTRL_ADDR, /*listener=*/addr)
           && sendData(cmd, strlen(cmd));
    unlock();
    return ok;
}

int GpibBus::receive(uint8_t addr, char* buf, size_t maxLen, uint32_t timeoutMs) {
    static constexpr const char kTruncSuffix[] = "...truncated";
    static constexpr size_t kSuffixLen = sizeof(kTruncSuffix) - 1;  // 13

    if (maxLen <= kSuffixLen + 1) return -1;
    if (!lock()) return -1;

    const size_t dataMax = maxLen - kSuffixLen;

    int n = -1;
    if (!addressTalk(/*talker=*/addr, /*listener=*/CTRL_ADDR)) {
        unlock();
        return -1;
    }
    setListener();

    size_t i = 0;
    bool terminated = false;
    while (i + 1 < dataMax) {
        uint8_t b;
        bool eoi;
        if (!readByte(b, eoi, timeoutMs)) break;
        buf[i++] = (char)b;
        // EOI is the only safe end-of-message marker — \n may appear
        // mid-response on the TDS784A (SET? embeds line separators).
        if (eoi) { terminated = true; break; }
    }

    if (!terminated && i >= dataMax - 1) {
        memcpy(buf + i, kTruncSuffix, kSuffixLen + 1);
        i += kSuffixLen;
    }

    buf[i] = 0;
    n = (int)i;

    setTalker();
    unlock();
    return n;
}

int GpibBus::receiveRaw(uint8_t addr, uint8_t* buf, size_t maxLen, uint32_t timeoutMs) {
    if (maxLen == 0) return -1;
    if (!lock()) return -1;

    if (!addressTalk(/*talker=*/addr, /*listener=*/CTRL_ADDR)) {
        unlock();
        return -1;
    }
    setListener();

    size_t i = 0;
    while (i < maxLen) {
        uint8_t b;
        bool eoi;
        if (!readByte(b, eoi, timeoutMs)) break;
        buf[i++] = b;
        if (eoi) break;
    }

    setTalker();
    unlock();
    return (int)i;
}

int GpibBus::queryRaw(uint8_t addr, const char* cmd, uint8_t* buf, size_t maxLen, uint32_t timeoutMs) {
    if (maxLen == 0) return -1;
    if (!lock()) return -1;

    if (!addressTalk(/*talker=*/CTRL_ADDR, /*listener=*/addr) ||
        !sendData(cmd, strlen(cmd))) {
        unlock();
        return -1;
    }

    // Scope needs time to process the SCPI command and transition from
    // listener → talker before we reverse-address the bus.
    delay(2);

    if (!addressTalk(/*talker=*/addr, /*listener=*/CTRL_ADDR)) {
        unlock();
        return -1;
    }
    setListener();

    size_t i = 0;
    while (i < maxLen) {
        uint8_t b;
        bool eoi;
        if (!readByte(b, eoi, timeoutMs)) break;
        buf[i++] = b;
        if (eoi) break;
    }

    setTalker();
    unlock();
    return (int)i;
}

int GpibBus::receiveRawStream(uint8_t addr, uint8_t* chunkBuf, size_t chunkSize,
                              ChunkCb cb, void* ctx, uint32_t timeoutMs) {
    if (chunkSize == 0 || !chunkBuf || !cb) return -1;
    if (!lock()) return -1;

    if (!addressTalk(/*talker=*/addr, /*listener=*/CTRL_ADDR)) {
        unlock();
        return -1;
    }
    setListener();

    size_t total = 0;
    size_t fill  = 0;
    bool   ok    = true;
    bool   done  = false;
    while (!done) {
        uint8_t b;
        bool eoi;
        if (!readByte(b, eoi, timeoutMs)) { ok = false; break; }
        chunkBuf[fill++] = b;
        total++;
        if (eoi) done = true;
        if (fill == chunkSize || done) {
            if (!cb(ctx, chunkBuf, fill, done)) { ok = false; break; }
            fill = 0;
        }
    }

    setTalker();
    unlock();
    return ok ? (int)total : -1;
}

int GpibBus::queryRawStream(uint8_t addr, const char* cmd,
                            uint8_t* chunkBuf, size_t chunkSize,
                            ChunkCb cb, void* ctx, uint32_t timeoutMs) {
    if (chunkSize == 0 || !chunkBuf || !cb) return -1;
    if (!lock()) return -1;

    if (!addressTalk(/*talker=*/CTRL_ADDR, /*listener=*/addr) ||
        !sendData(cmd, strlen(cmd))) {
        unlock();
        return -1;
    }

    // Scope needs time to process the SCPI command and transition from
    // listener → talker before we reverse-address the bus.
    delay(2);

    if (!addressTalk(/*talker=*/addr, /*listener=*/CTRL_ADDR)) {
        unlock();
        return -1;
    }
    setListener();

    size_t total = 0;
    size_t fill  = 0;
    bool   ok    = true;
    bool   done  = false;
    while (!done) {
        uint8_t b;
        bool eoi;
        if (!readByte(b, eoi, timeoutMs)) { ok = false; break; }
        chunkBuf[fill++] = b;
        total++;
        if (eoi) done = true;
        if (fill == chunkSize || done) {
            if (!cb(ctx, chunkBuf, fill, done)) { ok = false; break; }
            fill = 0;
        }
    }

    setTalker();
    unlock();
    return ok ? (int)total : -1;
}

int GpibBus::query(uint8_t addr, const char* cmd, char* buf, size_t maxLen, uint32_t timeoutMs) {
    static constexpr const char kTruncSuffix[] = "...truncated";
    static constexpr size_t kSuffixLen = sizeof(kTruncSuffix) - 1;  // 13

    if (maxLen <= kSuffixLen + 1) return -1;
    if (!lock()) return -1;

    // Reserve space for truncation suffix so the caller can always detect it.
    const size_t dataMax = maxLen - kSuffixLen;

    if (!addressTalk(/*talker=*/CTRL_ADDR, /*listener=*/addr) ||
        !sendData(cmd, strlen(cmd))) {
        unlock();
        return -1;
    }

    // Scope needs time to process the SCPI command and transition from
    // listener → talker before we reverse-address the bus.
    delay(2);

    if (!addressTalk(/*talker=*/addr, /*listener=*/CTRL_ADDR)) {
        unlock();
        return -1;
    }
    setListener();

    size_t i = 0;
    bool terminated = false;
    bool last_eoi = false;
    char last_b = 0;
    while (i + 1 < dataMax) {
        uint8_t b;
        bool eoi;
        if (!readByte(b, eoi, timeoutMs)) break;
        buf[i++] = (char)b;
        last_b = (char)b;
        last_eoi = eoi;
        // TDS784A's SET? response embeds \n as a line separator inside
        // the message, only asserting EOI on the actual final byte.
        // Terminate on EOI only — \n alone may be mid-response.
        if (eoi) { terminated = true; break; }
    }

    // Buffer filled without seeing EOI or LF → response was longer than the buffer.
    if (!terminated && i >= dataMax - 1) {
        memcpy(buf + i, kTruncSuffix, kSuffixLen + 1);
        i += kSuffixLen;
    }

    buf[i] = 0;
    int n = (int)i;
    (void)last_b; (void)last_eoi;

    setTalker();
    unlock();
    return n;
}

// --------------------------------------------------------------------------
// Binary (tektool) helpers.

bool GpibBus::sendRaw(uint8_t addr, const uint8_t* data, size_t len, uint32_t timeoutMs) {
    if (!data || len == 0) return false;
    if (!lock(timeoutMs)) return false;
    bool ok = addressTalk(/*talker=*/CTRL_ADDR, /*listener=*/addr)
           && sendBytes(data, len, timeoutMs);
    unlock();
    return ok;
}

bool GpibBus::deviceClear(uint8_t addr, uint32_t timeoutMs) {
    // IEEE-488.1 SDC (Selected Device Clear) = 0x04, addressed via ATN.
    static constexpr uint8_t CMD_SDC = 0x04;
    if (!lock(timeoutMs)) return false;
    setTalker();
    assertATN();
    bool ok = sendCommand(CMD_UNL, timeoutMs)
           && sendCommand(LAD(addr), timeoutMs)
           && sendCommand(CMD_SDC, timeoutMs)
           && sendCommand(CMD_UNL, timeoutMs);
    releaseATN();
    unlock();
    return ok;
}

int GpibBus::queryBytesStream(uint8_t addr, const uint8_t* tx, size_t txLen,
                              uint8_t* chunkBuf, size_t chunkSize,
                              ChunkCb cb, void* ctx, uint32_t timeoutMs,
                              size_t expectBytes) {
    if (!tx || txLen == 0 || chunkSize == 0 || !chunkBuf || !cb) return -1;
    if (!lock(timeoutMs)) return -1;

    Serial.printf("[qbs] addr=%u txLen=%u expect=%u to=%u\n",
                  addr, (unsigned)txLen, (unsigned)expectBytes,
                  (unsigned)timeoutMs);

    if (!addressTalk(/*talker=*/CTRL_ADDR, /*listener=*/addr) ||
        !sendBytes(tx, txLen, timeoutMs)) {
        Serial.println("[qbs] write phase FAILED");
        unlock();
        return -1;
    }

    delay(2);

    if (!addressTalk(/*talker=*/addr, /*listener=*/CTRL_ADDR)) {
        Serial.println("[qbs] turn-around FAILED");
        unlock();
        return -1;
    }
    setListener();

    size_t total = 0;
    size_t fill  = 0;
    bool   ok    = true;
    bool   done  = false;
    while (!done) {
        uint8_t b;
        bool eoi;
        if (!readByte(b, eoi, timeoutMs)) {
            Serial.printf("[qbs] readByte timeout after %u bytes\n",
                          (unsigned)total);
            ok = false;
            break;
        }
        chunkBuf[fill++] = b;
        total++;
        if (eoi) done = true;
        if (expectBytes > 0 && total >= expectBytes) done = true;
        if (fill == chunkSize || done) {
            if (!cb(ctx, chunkBuf, fill, done)) { ok = false; break; }
            fill = 0;
        }
    }

    Serial.printf("[qbs] done ok=%d total=%u\n", ok ? 1 : 0, (unsigned)total);
    setTalker();
    unlock();
    return ok ? (int)total : -1;
}
