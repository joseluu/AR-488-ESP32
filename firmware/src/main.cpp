// AR-488-ESP32 firmware — Phase 2.
//
// Boot flow:
//   1. OLED + GpibBus HAL up (Core 1).
//   2. WiFi STA join using credentials from network_creds.h.
//   3. AsyncWebServer + AsyncWebSocket on /ws (Core 0 via AsyncTCP).
//   4. GpibWorker FreeRTOS task pinned to Core 1 services the WS queue.
//   5. GPIB probe loop: detect device at the persisted default addr,
//      retry forever, restart probe if a `set_default_addr` request
//      changes the target mid-search.
//
// JSON request:
//   { "request_id": "1", "action": "query"|"write"|"read",
//     "command": "*IDN?", "addr": 1, "timeout_ms": 2000 }
// JSON response:
//   { "request_id": "1", "ok": true, "data": "TEKTRONIX,..." }

#include <Arduino.h>
#include <WiFi.h>

#include "Display.h"
#include "GpibBus.h"
#include "GpibWorker.h"
#include "WsServer.h"

#include "../network_creds.h"                   // ssid, password

static constexpr uint8_t SCOPE_ADDR_FALLBACK = 1;       // when NVS is unset

static Display    g_display;
static GpibBus    g_gpib;
static GpibWorker g_worker;
static WsServer   g_ws;

// Re-reads g_worker.defaultAddr() each pass so a `set_default_addr`
// request that arrives mid-probe immediately retargets us.
static void waitForScope() {
    uint8_t target = g_worker.defaultAddr();
    g_display.log("Probe @addr %u", target);
    Serial.printf("[gpib] probing @addr %u\n", target);
    int attempts = 0;

    for (;;) {
        uint8_t cur = g_worker.defaultAddr();
        if (cur != target) {
            target = cur;
            attempts = 0;
            g_display.log("Probe @addr %u", target);
            Serial.printf("[gpib] retarget @addr %u\n", target);
        }
        if (g_gpib.detectDevice(target, /*timeoutMs=*/200)) break;

        ++attempts;
        if (attempts == 1) g_display.log("No device, retry 1");
        else               g_display.replaceLast("No device, retry %d", attempts);
        Serial.printf("[gpib] no device @%u, retry %d\n", target, attempts);

        // 2 s wait, polled every 100 ms so an addr change unblocks us
        // without waiting for the full retry interval.
        for (int i = 0; i < 20; ++i) {
            delay(100);
            if (g_worker.defaultAddr() != target) break;
        }
    }
    g_display.log("Device OK.");

    target = g_worker.defaultAddr();
    char reply[128];
    int n = g_gpib.query(target, "*IDN?\n", reply, sizeof(reply), 2000);
    if (n <= 0) { g_display.log("*IDN? timeout"); return; }
    while (n > 0 && (reply[n - 1] == '\n' || reply[n - 1] == '\r')) reply[--n] = 0;
    Serial.printf("[gpib] *IDN? -> '%s'\n", reply);

    char chunk[22];
    int pos = 0;
    while (pos < n && pos < 42) {
        int take = min<int>(21, n - pos);
        memcpy(chunk, &reply[pos], take);
        chunk[take] = 0;
        g_display.log("%s", chunk);
        pos += take;
    }
}

static bool connectWiFi(uint32_t timeoutMs) {
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);
    WiFi.begin(ssid, password);
    Serial.printf("[wifi] joining '%s'...\n", ssid);
    g_display.log("WiFi: %.16s", ssid);

    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - t0 > timeoutMs) return false;
        delay(200);
    }
    return true;
}

void setup() {
    Serial.begin(115200);
    delay(150);
    Serial.println();
    Serial.println("AR-488-ESP32 firmware - Phase 2");

    g_display.begin();
    g_display.title("AR-488 v0.2");
    g_display.log("Booting...");

    if (!g_gpib.begin()) {
        Serial.println("[gpib] begin failed");
        g_display.log("MCP23017 fail");
        return;
    }
    if (!g_gpib.controllerInit()) {
        Serial.println("[gpib] ctrl init failed");
        g_display.log("CtrlInit fail");
        return;
    }

    // Bring WiFi + WS up first so the gateway is reachable while we
    // probe for the GPIB device. A `set_default_addr` request that
    // arrives during the probe will retarget us promptly.
    if (!connectWiFi(20000)) {
        Serial.println("[wifi] timeout");
        g_display.log("WiFi timeout");
        return;
    }
    IPAddress ip = WiFi.localIP();
    Serial.printf("[wifi] connected: %s\n", ip.toString().c_str());
    g_display.log("IP %s", ip.toString().c_str());

    uint8_t startAddr = GpibWorker::loadPersistedAddr(SCOPE_ADDR_FALLBACK);
    Serial.printf("[gpib] default addr = %u (loaded from NVS)\n", startAddr);

    if (!g_worker.begin(&g_gpib, g_ws.ws(), &g_display, startAddr)) {
        Serial.println("[worker] start failed");
        g_display.log("Worker fail");
        return;
    }
    g_ws.begin(&g_worker);
    Serial.println("[ws] listening on ws://*/ws");
    g_display.log("WS ready :80/ws");

    waitForScope();
}

void loop() {
    static uint32_t lastClients = 0xFFFFFFFF;
    static uint32_t lastTick = 0;
    if (millis() - lastTick > 1000) {
        lastTick = millis();
        g_ws.ws()->cleanupClients();
        size_t n = g_ws.clientCount();
        if (n != lastClients) {
            lastClients = n;
            g_display.log("Clients: %u", (unsigned)n);
        }
    }
    delay(50);
}
