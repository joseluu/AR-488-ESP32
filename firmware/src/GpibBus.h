// AR-488-ESP32 GPIB bus HAL
//
// Direct-GPIO data + handshake (DIO1..8, DAV, NRFD, NDAC, EOI, TE_DATA).
// MCP23017-mediated management (ATN, IFC, SRQ, REN, TE_CTRL, DC).
//
// Polarity reminder: SN7516x are non-inverting; the GPIB bus is
// negative-true. So at MCU level, 1 = bus released, 0 = bus asserted.
// Data bytes are inverted between MCU pins and bus DIO.

#pragma once

#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

class GpibBus {
public:
    static constexpr uint8_t CTRL_ADDR = 0;     // controller GPIB primary address

    // 488.1 command bytes
    static constexpr uint8_t CMD_UNL = 0x3F;
    static constexpr uint8_t CMD_UNT = 0x5F;
    static inline uint8_t LAD(uint8_t a) { return 0x20 | (a & 0x1F); }
    static inline uint8_t TAD(uint8_t a) { return 0x40 | (a & 0x1F); }

    bool begin();
    bool controllerInit();                              // IFC pulse + assert REN
    bool detectDevice(uint8_t addr, uint32_t timeoutMs = 100);

    // High-level helpers (acquire mutex internally).
    bool send(uint8_t addr, const char* cmd);
    int  receive(uint8_t addr, char* buf, size_t maxLen, uint32_t timeoutMs = 2000);
    int  query(uint8_t addr, const char* cmd, char* buf, size_t maxLen, uint32_t timeoutMs = 2000);

    // Raw / binary path — stops only on EOI or buffer-full. Used for
    // CURVE? and other definite-length-block payloads where LF is a
    // legitimate data byte.
    int  receiveRaw(uint8_t addr, uint8_t* buf, size_t maxLen, uint32_t timeoutMs = 2000);
    int  queryRaw(uint8_t addr, const char* cmd, uint8_t* buf, size_t maxLen, uint32_t timeoutMs = 2000);

    // Mutex (public so callers can group multiple ops in one critical section).
    bool lock(uint32_t timeoutMs = 2000);
    void unlock();

private:
    SemaphoreHandle_t mtx_ = nullptr;
    bool talker_ = true;
    uint8_t mcpOlatA_ = 0;

    bool mcpWrite(uint8_t reg, uint8_t value);
    bool mcpSetOlatA(uint8_t v);
    bool mcpSetBitA(uint8_t bit, bool high);

    void writeData(uint8_t b);
    uint8_t readData();
    void setDataDir(bool output);

    void setTalker();
    void setListener();
    void assertATN();
    void releaseATN();
    void assertIFC();
    void releaseIFC();
    void assertREN();
    void releaseREN();

    bool writeByte(uint8_t b, bool eoi, uint32_t timeoutMs);
    bool readByte(uint8_t& b, bool& eoi, uint32_t timeoutMs);
    bool sendCommand(uint8_t cmd, uint32_t timeoutMs = 500);

    bool addressTalk(uint8_t talker, uint8_t listener);
    bool sendData(const char* data, size_t len);
};
