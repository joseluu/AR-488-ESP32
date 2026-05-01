#include "GpibWorker.h"

#include <ArduinoJson.h>
#include <ESPAsyncWebServer.h>
#include <string.h>

#include "Display.h"
#include "GpibBus.h"

static constexpr int QUEUE_DEPTH = 8;
static constexpr int TASK_STACK  = 8192;
static constexpr int TASK_PRIO   = 5;
static constexpr int TASK_CORE   = 1;

bool GpibWorker::begin(GpibBus* bus, AsyncWebSocket* ws, Display* display, uint8_t scopeAddr) {
    bus_       = bus;
    ws_        = ws;
    display_   = display;
    scopeAddr_ = scopeAddr;

    queue_ = xQueueCreate(QUEUE_DEPTH, sizeof(GpibRequest));
    if (!queue_) return false;

    BaseType_t ok = xTaskCreatePinnedToCore(
        taskTrampoline, "gpib_worker", TASK_STACK, this, TASK_PRIO, nullptr, TASK_CORE);
    return ok == pdPASS;
}

bool GpibWorker::submit(const GpibRequest& req, TickType_t wait) {
    if (!queue_) return false;
    return xQueueSend(queue_, &req, wait) == pdPASS;
}

void GpibWorker::taskTrampoline(void* arg) {
    static_cast<GpibWorker*>(arg)->run();
}

void GpibWorker::run() {
    GpibRequest req;
    for (;;) {
        if (xQueueReceive(queue_, &req, portMAX_DELAY) == pdPASS) {
            handle(req);
        }
    }
}

static void sendResponse(AsyncWebSocket* ws, uint32_t clientId, const JsonDocument& doc) {
    String out;
    serializeJson(doc, out);
    if (ws) ws->text(clientId, out);
}

// Cap on a single binary capture. 64 KiB covers a 50000-point CURVE? at
// 1 byte/sample or a 32000-point capture at 2 bytes/sample with header.
static constexpr size_t MAX_BIN_BYTES = 65536;

void GpibWorker::handle(const GpibRequest& req) {
    JsonDocument resp;
    resp["request_id"] = req.request_id;

    uint8_t addr = req.addr ? req.addr : scopeAddr_;

    bool isQuery   = (strcmp(req.action, "query") == 0);
    bool isWrite   = (strcmp(req.action, "write") == 0) || (strcmp(req.action, "send") == 0);
    bool isRead    = (strcmp(req.action, "read")  == 0);
    bool isBinary  = (strcmp(req.action, "binary_query") == 0)
                  || (strcmp(req.action, "binary_read")  == 0);

    if (!isQuery && !isWrite && !isRead && !isBinary) {
        resp["ok"] = false;
        resp["error"] = "unknown action";
        sendResponse(ws_, req.client_id, resp);
        if (display_) display_->log("ERR action %.10s", req.action);
        return;
    }

    uint32_t timeout = req.timeout_ms ? req.timeout_ms : 2000;

    if (isBinary) {
        // Heap-allocate the binary buffer so we don't blow the worker stack
        // and so the memory is freed promptly after the WS send.
        uint8_t* buf = (uint8_t*)malloc(MAX_BIN_BYTES);
        if (!buf) {
            resp["ok"] = false;
            resp["error"] = "oom";
            sendResponse(ws_, req.client_id, resp);
            if (display_) display_->log("ERR oom bin");
            return;
        }
        int n;
        if (strcmp(req.action, "binary_read") == 0) {
            n = bus_->receiveRaw(addr, buf, MAX_BIN_BYTES, timeout);
        } else {
            n = bus_->queryRaw(addr, req.command, buf, MAX_BIN_BYTES, timeout);
        }
        bool ok = (n > 0);

        resp["ok"] = ok;
        resp["binary"] = true;
        resp["length"] = ok ? n : 0;
        if (!ok) resp["error"] = "gpib timeout";
        sendResponse(ws_, req.client_id, resp);

        if (ok && ws_) {
            // AsyncWebSocket::binary copies the payload; we can free
            // immediately afterwards.
            ws_->binary(req.client_id, buf, (size_t)n);
        }
        free(buf);

        if (display_) display_->log("%s bin %d", ok ? "OK" : "ER", n);
        return;
    }

    char buf[512];
    bool ok = false;
    int  n  = 0;

    if (isQuery) {
        n = bus_->query(addr, req.command, buf, sizeof(buf), timeout);
        ok = (n > 0);
    } else if (isWrite) {
        ok = bus_->send(addr, req.command);
    } else { // isRead
        n = bus_->receive(addr, buf, sizeof(buf), timeout);
        ok = (n > 0);
    }

    resp["ok"] = ok;
    if (ok && (isQuery || isRead)) {
        // strip trailing CR/LF
        while (n > 0 && (buf[n - 1] == '\n' || buf[n - 1] == '\r')) buf[--n] = 0;
        resp["data"] = buf;
    } else if (!ok) {
        resp["error"] = "gpib timeout";
    }
    sendResponse(ws_, req.client_id, resp);

    if (display_) {
        char preview[18];
        strncpy(preview, req.command, sizeof(preview) - 1);
        preview[sizeof(preview) - 1] = 0;
        for (char* p = preview; *p; ++p) if (*p == '\n' || *p == '\r') { *p = 0; break; }
        display_->log("%s %s", ok ? "OK" : "ER", preview);
    }
}
