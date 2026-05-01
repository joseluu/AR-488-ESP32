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

    // GPIB messages need a terminator. Append \n if caller didn't.
    size_t cl = strlen(req.command);
    if (cl > 0 && cl + 1 < sizeof(req.command) &&
        req.command[cl - 1] != '\n' && req.command[cl - 1] != '\r') {
        req.command[cl] = '\n';
        req.command[cl + 1] = 0;
    }

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
