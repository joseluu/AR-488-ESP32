#include "WsServer.h"

#include <ArduinoJson.h>
#include <string.h>

#include "GpibWorker.h"

bool WsServer::begin(GpibWorker* worker, uint16_t /*port*/) {
    worker_ = worker;

    ws_.onEvent([this](AsyncWebSocket* s, AsyncWebSocketClient* c, AwsEventType t,
                       void* arg, uint8_t* data, size_t len) {
        onEvent_(s, c, t, arg, data, len);
    });

    server_.addHandler(&ws_);

    server_.on("/", HTTP_GET, [](AsyncWebServerRequest* req) {
        req->send(200, "text/plain",
                  "AR-488-ESP32 GPIB gateway.\n"
                  "WebSocket: ws://<host>/ws\n"
                  "Send JSON: {\"request_id\":\"1\",\"action\":\"query\",\"command\":\"*IDN?\"}\n");
    });

    server_.begin();
    return true;
}

void WsServer::onEvent_(AsyncWebSocket* /*server*/, AsyncWebSocketClient* client,
                       AwsEventType type, void* arg, uint8_t* data, size_t len) {
    switch (type) {
        case WS_EVT_CONNECT:
            Serial.printf("[ws] client %u connected from %s\n",
                          client->id(), client->remoteIP().toString().c_str());
            break;
        case WS_EVT_DISCONNECT:
            Serial.printf("[ws] client %u disconnected\n", client->id());
            break;
        case WS_EVT_DATA: {
            AwsFrameInfo* info = (AwsFrameInfo*)arg;
            // Only handle single-frame text messages that fit in one packet.
            if (info->final && info->index == 0 && info->len == len &&
                info->opcode == WS_TEXT) {
                handleMessage_(client, data, len);
            }
            break;
        }
        default:
            break;
    }
}

static void copyTrimmed(char* dst, size_t cap, const char* src) {
    if (!src) { dst[0] = 0; return; }
    strncpy(dst, src, cap - 1);
    dst[cap - 1] = 0;
}

// Decode base64 from `src` into `dst` (capacity `dstCap` bytes). Returns
// the decoded length on success, or -1 if the payload is malformed or
// would overflow. Accepts standard alphabet (A-Z a-z 0-9 + /), with
// optional '=' padding. Whitespace and '\0' terminate the input.
static int b64Decode(const char* src, uint8_t* dst, size_t dstCap) {
    if (!src) return 0;
    static int8_t tbl[256];
    static bool   tblReady = false;
    if (!tblReady) {
        for (int i = 0; i < 256; ++i) tbl[i] = -1;
        const char* a = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        for (int i = 0; i < 64; ++i) tbl[(uint8_t)a[i]] = (int8_t)i;
        tblReady = true;
    }

    size_t out = 0;
    uint32_t acc = 0;
    int bits = 0;
    for (const char* p = src; *p; ++p) {
        uint8_t c = (uint8_t)*p;
        if (c == '=') break;
        if (c == '\r' || c == '\n' || c == ' ' || c == '\t') continue;
        int8_t v = tbl[c];
        if (v < 0) return -1;
        acc = (acc << 6) | (uint32_t)v;
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            if (out >= dstCap) return -1;
            dst[out++] = (uint8_t)((acc >> bits) & 0xFFu);
        }
    }
    return (int)out;
}

void WsServer::handleMessage_(AsyncWebSocketClient* client, const uint8_t* data, size_t len) {
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, data, len);
    if (err) {
        JsonDocument resp;
        resp["ok"] = false;
        resp["error"] = "json parse error";
        String out;
        serializeJson(resp, out);
        client->text(out);
        return;
    }

    GpibRequest req = {};
    req.client_id = client->id();
    copyTrimmed(req.request_id, sizeof(req.request_id), doc["request_id"] | "");
    copyTrimmed(req.action,     sizeof(req.action),     doc["action"]     | "query");
    copyTrimmed(req.command,    sizeof(req.command),    doc["command"]    | "");
    req.addr       = doc["addr"]       | 0;
    req.timeout_ms = doc["timeout_ms"] | 0;
    req.payload_len = 0;

    // GPIB uses EOI as the message terminator — no \n needed.
    // If the caller already included \n/\r, strip it so EOI lands on
    // the last real character (the TDS784A treats a trailing \n as
    // literal data when it follows an argument value).
    size_t cl = strlen(req.command);
    while (cl > 0 && (req.command[cl - 1] == '\n' || req.command[cl - 1] == '\r'))
        req.command[--cl] = 0;

    // Optional binary payload for write_bytes / query_bytes.
    const char* b64 = doc["payload_b64"] | (const char*)nullptr;
    if (b64) {
        int n = b64Decode(b64, req.payload, sizeof(req.payload));
        if (n < 0) {
            JsonDocument resp;
            resp["request_id"] = req.request_id;
            resp["ok"] = false;
            resp["error"] = "payload_b64 invalid or too large";
            String out;
            serializeJson(resp, out);
            client->text(out);
            return;
        }
        req.payload_len = (uint16_t)n;
    }

    // tektool's binary protocol does not assert EOI; the host tells us
    // exactly how many bytes to read in the reply.
    req.expect_bytes = (uint16_t)(doc["expect_bytes"] | 0);

    if (!worker_ || !worker_->submit(req)) {
        JsonDocument resp;
        resp["request_id"] = req.request_id;
        resp["ok"] = false;
        resp["error"] = "queue full";
        String out;
        serializeJson(resp, out);
        client->text(out);
    }
}
