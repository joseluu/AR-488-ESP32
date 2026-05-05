// GPIB worker — owns the GpibBus on Core 1.
//
// The AsyncTCP task (Core 0) parses incoming WebSocket frames and
// enqueues a GpibRequest. This worker, pinned to Core 1, dequeues
// each request, acquires the GpibBus mutex, runs the operation,
// then sends a JSON response back through the WebSocket.

#pragma once

#include <Arduino.h>
#include <Preferences.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

class GpibBus;
class Display;
class AsyncWebSocket;

struct GpibRequest {
    uint32_t client_id;
    uint8_t  addr;
    char     request_id[32];
    char     action[16];                        // "query" | "write" | "read" | "write_bytes" | "query_bytes" | "device_clear" | "interface_clear"
    char     command[256];
    uint32_t timeout_ms;
    // Binary payload for write_bytes / query_bytes (base64-encoded in JSON).
    // Decoded raw bytes live in payload[0..payload_len). Empty for the
    // ASCII actions above.
    uint8_t  payload[1200];
    uint16_t payload_len;
    // For query_bytes only: number of bytes the host expects in the reply.
    // 0 = read until EOI (legacy behaviour). >0 = stop after that many bytes.
    // tektool's binary protocol never asserts EOI, so the host must pass the
    // exact reply length here.
    uint16_t expect_bytes;
};

class GpibWorker {
public:
    bool begin(GpibBus* bus, AsyncWebSocket* ws, Display* display, uint8_t scopeAddr);
    bool submit(const GpibRequest& req, TickType_t wait = 0);

    uint8_t defaultAddr() const { return scopeAddr_; }
    void    setDefaultAddr(uint8_t addr);                // updates RAM + NVS

    // Read the persisted default address (or `fallback` if unset/invalid).
    static uint8_t loadPersistedAddr(uint8_t fallback);

private:
    static void taskTrampoline(void* arg);
    void run();
    void handle(const GpibRequest& req);

    GpibBus*         bus_       = nullptr;
    AsyncWebSocket*  ws_        = nullptr;
    Display*         display_   = nullptr;
    volatile uint8_t scopeAddr_ = 1;                     // read across cores
    QueueHandle_t    queue_     = nullptr;
    Preferences      prefs_;
};
