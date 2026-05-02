# TODO — AR-488-ESP32 firmware / gateway issues

Issues observed during the first hardware-in-the-loop smoke test of the
`tek-tds784a` MCP server (2026-05-02). These are **not** MCP server
bugs — those are tracked separately and have been fixed in
`host_software/mcp_server/server.py`. Items below sit on the firmware
or WebSocket gateway side.

Firmware is a platformio development done in the firmware/directory

Gateway is a python program: host_software/request_gpib.py

## 1. First 2 bytes of some commands dropped

The TDS784A's error queue surfaced these stale `113,"Undefined header"`
events repeatedly, drained on otherwise-unrelated tool calls:

- `unrecognized command - RIZONTAL:MAIN:SAMPLERATE?` (sent: `HORIZONTAL:MAIN:SAMPLERATE?`)
- `unrecognized command - IGGER:MAIN:HOLDOFF:` (sent: `TRIGGER:MAIN:HOLDOFF:VALUE?`)

Both are full SCPI strings sent from the host with the leading 2 bytes
missing on arrival. Both happen to fire from `collect_metadata` (called
by `get_acquisition_setup` and `get_waveform`), which queues a sequence
of `query` commands quickly.

Hypotheses to investigate, in order of cheapness:

1. **GPIB write-after-write timing**: a previous talker isn't fully
   released before the next listener-addressed write begins, so the
   first 1–2 ATN-controlled command bytes get clipped on the bus.
2. **ESP32 UART → GPIB front-end race**: the bridge MCU doesn't drain
   its TX FIFO before asserting EOI on the previous command.
3. **WebSocket framing**: each request is its own JSON frame; if the
   firmware reads the JSON, immediately starts a GPIB transaction, but
   the `command` string is read into a buffer that's reused before the
   GPIB write completes, the second command can clobber the first
   couple of bytes.

The truncation looks deterministic on those two SCPI strings, but the
visible queries that *do* succeed (e.g. `HORIZONTAL:MAIN:SCALE?`,
`HORIZONTAL:RECORDLENGTH?`) are issued in the same loop, so the issue
isn't tied to any one string. Likely an intermittent race that's biased
toward certain timings.

**Reproduce**: call `get_acquisition_setup(["CH1","CH2"])` two or three
times back-to-back; the next `get_errors` will surface accumulated
`113` events.

## 2. `\0A` appended to HARDCOPY setup command

After a successful screen capture the error queue surfaced:

```
102,"Syntax error invalid character data - HARDCOPY:PALETTE COLOR\0A"
```

`\0A` is `\n`. Some path in the firmware appends a literal newline byte
to one of the HARDCOPY setup writes (likely `HARDCOPY:PALETTE COLOR`,
which is the last write before `HARDCOPY START`). The TDS784A's GPIB
parser flags it as invalid character data inside the argument value.

The hardcopy still produced a valid PCXCOLOR stream and a clean PNG —
so the scope is clearly not in a wedged state — but the spurious
`\0A` indicates command terminator handling is off for write commands
that end with a SCPI argument value (vs. just a header).

**Look at**: how `gpib_write()` (or equivalent) builds the byte buffer
in the firmware. Is it terminating with EOI only, or EOI + `\n`? GPIB
convention is EOI alone; some scopes will swallow a trailing `\n` but
the TDS784A treats it as part of the argument when the previous byte
was a non-whitespace character of an argument value.

## 3. `SET?` response truncated at ~100 bytes

`get_setup_state()` (which sends `HEADER ON` then `SET?`) returns a
`setup_string` cut off mid-quoted-string:

```
:ACQ:STOPA RUNST;STATE 1;MOD SAM;NUME 1;NUMAV 3;REPE 1;AUTOSA 0;:APPM:TITL "Application
```

A real `SET?` response is several KB. The cut at exactly the start of a
quoted string suggests either:

- a fixed-size response buffer in the firmware (the WebSocket data
  field caps out before the GPIB read finishes), or
- a heuristic that mistakes the opening `"` for end-of-data, or
- a JSON serialization that escapes the `"` and overflows somewhere.

**Look at**: the JSON-over-WS path on `query` action — specifically the
buffer that accumulates the GPIB read before serializing it into the
`data` field. Compare with how `--waveform` capture handles long
responses (it uses a binary-stream path that already works for hundreds
of KB). `SET?` is a long ASCII response, which is the awkward middle
case.

Workaround on the host side: use `binary_query` for `SET?`, which
should ride the streaming path that already works. The MCP server's
`get_setup_state` could be switched to `binary_query` if firmware fix
is non-trivial.

## Priority

1 (truncation of first bytes) is the most concerning — it silently
breaks any read query whose first 2 chars matter (which is almost all
of them). 3 (SET? truncation) blocks the "save setup / restore setup"
workflow that the MCP `set_setup_state` tool relies on. 2 (stray `\0A`)
is cosmetic — only shows up in the error queue.
