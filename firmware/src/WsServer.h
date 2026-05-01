// WebSocket gateway. Lives on Core 0 (the AsyncTCP task is created
// pinned to Core 0 by the AsyncTCP library). Parses incoming JSON
// frames, validates them, and pushes a GpibRequest onto the worker
// queue. Sending responses is the worker's job.

#pragma once

#include <ESPAsyncWebServer.h>

class GpibWorker;

class WsServer {
public:
    bool begin(GpibWorker* worker, uint16_t port = 80);
    AsyncWebSocket* ws() { return &ws_; }
    size_t clientCount() { return ws_.count(); }

private:
    AsyncWebServer    server_{80};
    AsyncWebSocket    ws_{"/ws"};
    GpibWorker*       worker_ = nullptr;

    void onEvent_(AsyncWebSocket* server, AsyncWebSocketClient* client,
                  AwsEventType type, void* arg, uint8_t* data, size_t len);
    void handleMessage_(AsyncWebSocketClient* client, const uint8_t* data, size_t len);
};
