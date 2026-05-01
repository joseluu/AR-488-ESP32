This plan focuses on building a **Dual-Core "Gateway"** firmware. It treats the GPIB bus as a protected resource, allowing you to run a high-performance JSON/MCP interface today while leaving a "slot" open for a Legacy Prologix-style task later.

### `Implementation\\\_Plan.md`

# Project: Modern AI-GPIB Gateway (ESP32 to Tektronix 784)

## Overview

A streamlined ESP32 firmware designed for AI-driven laboratory automation. It utilizes a non-blocking WebSocket/JSON interface for modern agents (via MCP) and provides a thread-safe path for legacy IEEE-488.2 compatibility.

Hardware is the Heltec ESP32 Wifi Kit V1 with OLED

## Phase 1: The Hardware Abstraction Layer (HAL)

**Goal:** Create a thread-safe C++ Class using direct register access.

### 1.1 `GpibBus` Class Definition

- **Encapsulation:** Protect GPIB pins using a FreeRTOS Mutex (`SemaphoreHandle\\\_t`).

- **Register Mapping:** Define macros for GPIO Port A/B writes for the 8-bit data bus.

- **Handshake Logic:** Implement `write\\\_byte` and `read\\\_byte` using the 3-wire handshake (DAV, NRFD, NDAC).

### 1.2 Validation (Test 1)

- **Flash firmware.**

- **Detect GPIB connection and indicate detection on the OLED**

- **Test:** send `\\\*IDN?` query to the Tek 784.

- **Success Criteria:** The scope returns `"TEKTRONIX,784..."` without timing out.

- Display return value on the OLED

## Phase 2: The Modern Communication Core

**Goal:** Establish a JSON-over-WebSocket transport on Core 0.

implementation note: use the file network\_creds.h to connect to local Wifi AP

### 2.1 Async WebSocket Server

- Use `ESPAsyncWebServer` to handle incoming JSON frames.

- **Protocol:**

- JSON


`\\\{`

- `  "request\\\_id": "123",`

- ` "action": "query",`

- `  "command": "CH1:SCALE?"`

- `\\\}`

```
  
\#\#\# 2.2 Command Dispatcher  
  
- Parse JSON using \`ArduinoJson\`.  
  
- Acquire the \`GpibBus\` mutex.  
  
- Execute the command on the bus and capture the response.  
  
- Return a JSON response frame.  
  
\#\#\# 2.3 Validation (Test 2)  
  
- \*\*Flash firmware.\*\*  
  
- \*\*Report IP address on OLED\*\*  
  
- \*\*Test:\*\*  Make a Python script to send a WebSocket JSON request for the scope's horizontal scale.  
  
- \*\*Do some communication traces on the OLED\*\*  
  
- \*\*Success Criteria:\*\* Valid JSON received containing the numeric scale value.  
  
  
\#\# Phase 3: High-Bandwidth Data Handling  
  
\*\*Goal:\*\* Efficiently handle large waveform captures (CURVe? data).  
  
\#\#\# 3.1 Binary Pass-through  
  
- Detect when a command expects a large binary payload (e.g., \`CURV?\`).  
  
- Implement a "Raw Mode" where the HAL streams bytes directly from the bus to the WebSocket buffer to avoid memory fragmentation on the ESP32.  
  
\#\#\# 3.2 Validation (Test 3)  
  
- \*\*Test:\*\* Request a 5,000-point waveform capture.  
  
- \*\*Success Criteria:\*\* Data is received in under 500ms and matches the visual representation on the scope.  
  
  
\#\# Phase 4: MCP Integration (Local Machine)  
  
\*\*Goal:\*\* Bridge the AI to the ESP32.  
  
\#\#\# 4.1 Python MCP Server  
  
- Implement an MCP server using the Python SDK.  
  
- Define Tools: \`get\\\_waveform\`, \`set\\\_vertical\\\_scale\`, \`auto\\\_setup\`.  
  
- The server maintains a persistent WebSocket connection to the ESP32.  
  
\#\#\# 4.2 Validation (Test 4)  
  
- \*\*Test:\*\* Prompt the AI: \*"Analyze the signal on Channel 1 and tell me if the rise time is within TTL specs."\*  
  
- \*\*Success Criteria:\*\* AI triggers the tools, receives the data, and provides a correct engineering analysis.  
  
  
\#\# Phase 5: Legacy Compatibility Layer (Future Slot)  
  
\*\*Goal:\*\* Open a Telnet port for legacy software.  
  
\#\#\# 5.1 The "Prologix" Task  
  
- Initialize a second listening port (Telnet 1234).  
  
- Create a "Legacy Parser" that translates \`++addr\` and \`++read\` into \`GpibBus\` class calls.  
  
- \*\*Constraint:\*\* Ensure this task requests the same \`GpibBus\` mutex used by the WebSocket task.  
  
  
\#\# Development Milestones & Checklist  
  
- \\\[ \\\] \*\*Milestone 1:\*\* Basic register-based handshake working (verified by Logic Analyzer or Scope ID).  
  
- \\\[ \\\] \*\*Milestone 2:\*\* Mutex-protected bus access (prevents crashes during simultaneous requests).  
  
- \\\[ \\\] \*\*Milestone 3:\*\* WebSocket server reliably delivering SCPI responses.  
  
- \\\[ \\\] \*\*Milestone 4:\*\* MCP Server operational and "Tools" recognized by the AI Agent.  
  
  
\#\#\# Key Technical Notes for the Agent  
  
  
- \*\*Timeouts:\*\* Implement a hard 2-second watchdog on the \`NDAC\` line to prevent the ESP32 from hanging if the scope is disconnected.  
  
- \*\*Core Affinity:\*\* Force the WiFi/WebSocket task to \`Core 0\` and the GPIB HAL to \`Core 1\` for maximum timing stability.
```

