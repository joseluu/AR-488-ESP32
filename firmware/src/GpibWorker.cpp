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

static constexpr const char* PREFS_NS  = "ar488";
static constexpr const char* PREFS_KEY = "scope_addr";

uint8_t GpibWorker::loadPersistedAddr(uint8_t fallback) {
    Preferences p;
    if (!p.begin(PREFS_NS, /*readOnly=*/true)) return fallback;
    uint8_t v = p.getUChar(PREFS_KEY, fallback);
    p.end();
    return (v >= 1 && v <= 30) ? v : fallback;
}

void GpibWorker::setDefaultAddr(uint8_t addr) {
    if (addr < 1 || addr > 30) return;
    scopeAddr_ = addr;                                   // visible to other core (volatile)
    if (prefs_.begin(PREFS_NS, /*readOnly=*/false)) {
        prefs_.putUChar(PREFS_KEY, addr);
        prefs_.end();
    }
}

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

// Streaming chunk size for binary payloads. Each filled chunk is sent
// as one WebSocket binary frame; total payload is unbounded by RAM.
static constexpr size_t BIN_CHUNK_BYTES = 8192;

struct BinStreamCtx {
    AsyncWebSocket* ws;
    uint32_t        clientId;
};

// Wait for the WS client's send queue to drain, then push one chunk.
// Returning false aborts the GPIB read.
static bool binStreamCb(void* ctx, const uint8_t* data, size_t len, bool /*isLast*/) {
    BinStreamCtx* sc = static_cast<BinStreamCtx*>(ctx);
    if (!sc || !sc->ws) return false;

    // Backpressure: poll canSend() with a 5 s ceiling so a stalled
    // client can't pin us forever.
    uint32_t t0 = millis();
    AsyncWebSocketClient* c = sc->ws->client(sc->clientId);
    while (c && !c->canSend()) {
        if (millis() - t0 > 5000) return false;
        vTaskDelay(pdMS_TO_TICKS(2));
        c = sc->ws->client(sc->clientId);
    }
    if (!c) return false;

    sc->ws->binary(sc->clientId, data, len);
    return true;
}

void GpibWorker::handle(const GpibRequest& req) {
    JsonDocument resp;
    resp["request_id"] = req.request_id;

    // Control actions (no GPIB bus access).
    if (strcmp(req.action, "set_default_addr") == 0) {
        if (req.addr < 1 || req.addr > 30) {
            resp["ok"] = false;
            resp["error"] = "addr out of range (1..30)";
        } else {
            setDefaultAddr(req.addr);
            resp["ok"] = true;
            resp["addr"] = req.addr;
        }
        sendResponse(ws_, req.client_id, resp);
        if (display_) display_->log("Addr <- %u", (unsigned)req.addr);
        return;
    }
    if (strcmp(req.action, "get_default_addr") == 0) {
        resp["ok"] = true;
        resp["addr"] = (uint8_t)scopeAddr_;
        sendResponse(ws_, req.client_id, resp);
        return;
    }

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
        // Stream the GPIB payload in BIN_CHUNK_BYTES chunks: a "begin"
        // JSON envelope, N binary WS frames, then an "end" JSON with
        // total length (or error). This lets us pass screen bitmaps or
        // 500 K-point CURVE? captures without holding the whole thing
        // in RAM.
        uint8_t* chunk = (uint8_t*)malloc(BIN_CHUNK_BYTES);
        if (!chunk) {
            resp["ok"] = false;
            resp["error"] = "oom";
            sendResponse(ws_, req.client_id, resp);
            if (display_) display_->log("ERR oom bin");
            return;
        }

        // Open envelope.
        {
            JsonDocument open;
            open["request_id"] = req.request_id;
            open["ok"] = true;
            open["binary"] = true;
            open["stream"] = "begin";
            sendResponse(ws_, req.client_id, open);
        }

        BinStreamCtx sc{ ws_, req.client_id };
        int total;
        if (strcmp(req.action, "binary_read") == 0) {
            total = bus_->receiveRawStream(addr, chunk, BIN_CHUNK_BYTES,
                                           binStreamCb, &sc, timeout);
        } else {
            total = bus_->queryRawStream(addr, req.command, chunk, BIN_CHUNK_BYTES,
                                         binStreamCb, &sc, timeout);
        }
        free(chunk);

        // Close envelope.
        JsonDocument close_;
        close_["request_id"] = req.request_id;
        close_["binary"] = true;
        close_["stream"] = "end";
        if (total > 0) {
            close_["ok"] = true;
            close_["length"] = total;
        } else {
            close_["ok"] = false;
            close_["error"] = "gpib timeout";
            close_["length"] = 0;
        }
        sendResponse(ws_, req.client_id, close_);

        if (display_) display_->log("%s bin %d", total > 0 ? "OK" : "ER", total);
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
