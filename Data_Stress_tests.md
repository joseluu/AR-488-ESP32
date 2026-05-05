# Test Specification: GPIB Stability Verification for Tektronix TDS784A

**Target Device:** Tektronix TDS784A (Firmware v4.1e)

**Interface:** AR-488 ESP32

**Objective:** Validate error-free bidirectional bulk data transfer to ensure the interface is safe for firmware flashing.


## 1. Environment Setup

- **Timeout:** Set a global GPIB timeout of 5000ms.

- **Termination:** Commands should end with `\\n`. GPIB EOI must be enabled.

## 2. Phase 1: Latency and Response Stability (The "Heartbeat")

- **Action:** Send `\*IDN?` in a loop 200 times.

- **Pass Criteria:**

  - 100% success rate (no timeouts).

  - Response must consistently start with `TEKTRONIX,TDS 784A...`.

- **Failure:** Any "Query Unterminated" or empty response indicates a handshake timing issue.

## 3. Phase 2: Bulk Read Stress Test (Curve Extraction)

- **Setup:** Set scope to CH1, Record Length to 15,000 points.

- **Action:**

  1. Send `DATA:SOURCE CH1; ENCDG RIBINARY; WIDTH 1;` (Sets up raw binary transfer).

  2. Send `CURVE?` and capture the resulting block.

  3. Loop this 20 times.

- **Pass Criteria:**

  1. Each `CURVE?` response should contain the standard Tek binary header (e.g., `\#515000...`).

  2. Total bytes received must exactly match the header's length field.

  3. No partial packets or checksum errors.

## 4. Phase 3: Bulk Write Stress Test (The "Flash Simulator")

- **Action:**

  1. Define a string of 1,024 random alphanumeric characters.

  2. Send `MESSAGE:SHOW "\<string\>"` to the scope.

  3. Immediately send `MESSAGE:STATE ON`.

  4. Repeat this 50 times, varying the string each time.

- **Pass Criteria:**

  1. The scope's display should update without hanging.

  2. The script must not encounter a "Serial Buffer Overflow" on the ESP32.

- **Validation:** If the script can push 1k chunks repeatedly without the AR-488 crashing, it can likely handle the firmware page-write cycle.

## 5. Phase 4: Screen Capture (Large Payload)

- **Setup:** Set Hardcopy format to `BMP` via scope menu.

- **Action:**

  1. Send `HARDCOPY START`.

  2. Read the raw stream until EOI is detected.

  3. Save the stream as a `.bmp` file.

- **Pass Criteria:**

  1. The resulting file must be a valid, viewable Windows Bitmap.

  2. No "shearing" or corruption in the image (indicates dropped bytes in the middle of a transfer).


## Technical Notes for the Python Agent:

- **Buffer Size:** Use a reading buffer of at least 10,240 bytes to handle the `CURVE?` data.

- **Error Handling:** Catch `SerialException` or `TimeoutError` and log the exact loop iteration where the failure occurred.


### A Final Tip on the "Write" Path

When your agent writes the script, have it pay special attention to the **GPIB EOI (End or Identify)** signal. During a firmware flash, the scope relies on EOI to know a data block is finished. If the AR-488 or the Python script doesn't handle EOI correctly, the scope may sit indefinitely waiting for more data, which is the most common cause of a failed flash.

