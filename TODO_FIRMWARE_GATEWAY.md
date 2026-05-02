# AR-488-ESP32 firmware / gateway — issue log

Original report (2026-05-02) flagged three "firmware/gateway problems"
seen during the first hardware-in-the-loop smoke test of the
`tek-tds784a` MCP server. Investigation on 2026-05-03 with serial trace
points (Version v0.4-trace) showed only **one** of the three was an
actual firmware bug — the other two were misdiagnosed.

## 1. ~~First 2 bytes of some commands dropped~~ — NOT A FIRMWARE BUG

**Original symptom:** Errors like `unrecognized command - RIZONTAL:MAIN:SAMPLERATE?` (looks like "HO" was lost).

**Real cause:** The scope's error message buffer is showing the *parse-failure context*, not the bytes received. Trace confirmed the gateway sends the full command:

```
[trace ws] action=query len_after=27 cmd='HORIZONTAL:MAIN:SAMPLERATE?'
[trace sendData] len=27: 'HORIZONTAL:MAIN:SAMPLERATE?'
```

The TDS784A v4.1e simply **doesn't have** a `HORIZONTAL:MAIN:SAMPLERATE?` command. It also uses `HOLDOFF:TIME` not `HOLDOFF:VALUE`. Both are commands from newer Tek scope models.

**Fix:** in `host_software/request_gpib.py`:
- removed `("sample_rate_hz", "HORIZONTAL:MAIN:SAMPLERATE?")` from `_GLOBAL_META_QUERIES` — derive from `record_length / (10 * horizontal_scale_s)` if needed
- replaced `TRIGGER:MAIN:HOLDOFF:VALUE?` with `TRIGGER:MAIN:HOLDOFF:TIME?`

---

## 2. ~~`\0A` appended to HARDCOPY setup command~~ — NOT A FIRMWARE BUG

**Original symptom:** `Syntax error; invalid character data - HARDCOPY:PALETTE COLOR`.

**Real cause:** The TDS784A v4.1e's `HARDCOPY:PALETTE` only accepts `HARDCOPY` as a value on this firmware. `COLOR`, `MONOCHROME`, `INKSAVER`, `NORMAL` all return error 102 (probed). The image still rendered correctly because the scope kept its prior PALETTE setting after the rejected SET, but the error queue was being polluted.

**Fix:** in `host_software/mcp_server/server.py` `get_screen` — default palette to `HARDCOPY`, reject any other input with a helpful error.

---

## 3. `SET?` response truncated — REAL FIRMWARE BUG, FIXED IN v0.4

**Original symptom:** `setup_string` cut off at ~89 bytes mid-quoted-string (`...:APPM:TITL "Application`).

**Real cause:** The TDS784A's `SET?` response embeds `\n` as an internal line separator (e.g. inside `"Application\nMenu"`), with EOI asserted **only on the actual final byte**. The firmware's `query()` was breaking on `\n` OR EOI, so it terminated at the first internal newline:

```
[trace query recv] n=88, terminated=1, last_b=0x0A, last_eoi=0
```

`last_eoi=0` confirms the scope did NOT mean to terminate.

**Fix (`firmware/src/GpibBus.cpp`):** `query()` and `receive()` now break on EOI only — `\n` is just a data byte. Same logic applies to `receiveRaw`/`queryRaw` paths but those already only stop on EOI. Verified on v0.4 — `get_setup_state` now returns thousands of bytes including the multi-line `"Application\nMenu"` block, channel settings, trigger setup, math definitions, cursors. Hits the 4 KB buffer's `...truncated` suffix because the full SET? is even longer; for the complete dump, use the `binary_query` action which streams.

---

## Notes for future smoke tests

- Always query `gateway_firmware_version` first — confirms the running firmware matches what we think we built.
- TDS784A error messages truncate to a parse-context window. They show *where the parser stopped*, not what was received over the wire. Don't infer transmission corruption from them — use serial trace points on the gateway side instead.
- TDS784A SCPI uses the GPIB EOI line as the only reliable end-of-message marker. `\n` may appear mid-response.
