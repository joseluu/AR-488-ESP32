#pragma once

// Single source of truth for the firmware version.
// Bump on every shipped change. Surfaced on:
//   - OLED title bar (main.cpp)
//   - Serial banner at boot (main.cpp)
//   - WebSocket "version" action (GpibWorker)
#define AR488_FW_VERSION "0.5.3"
