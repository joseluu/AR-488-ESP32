"""Capture COM6 serial output for AR-488-ESP32 diagnosis.

Run with `uv run --with pyserial python tools/com6_capture.py [seconds]`.
Default duration is 8 s. Output goes to stdout, line-buffered.
"""
import sys
import time

import serial

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
PORT = "COM6"
BAUD = 115200

with serial.Serial(PORT, BAUD, timeout=0.2) as ser:
    deadline = time.time() + DURATION
    while time.time() < deadline:
        line = ser.readline()
        if line:
            try:
                print(line.decode("utf-8", errors="replace").rstrip())
            except Exception:
                print(repr(line))
            sys.stdout.flush()
