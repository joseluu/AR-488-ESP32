# MCP Tools for TDS784A Measurements — Revised Proposal

This document specifies the MCP server that lets an AI drive a Tektronix
TDS784A through the AR-488-ESP32 GPIB gateway. It supersedes
`MCP_Tools_for_TDS784_measurements.md`.

## Goals

1. Let the AI characterize a circuit (single measurements, swept measurements,
   waveform capture, screenshots) without forcing it to write SCPI.
2. Let the AI save a setup before experimenting and restore it on demand —
   "try-this-and-revert" workflows.
3. Make incoherent multi-channel reads impossible (atomic single-shot capture).
4. Surface scope errors after every write — no silent failures.
5. Stay close to the metal where it matters: an `raw_scpi` escape hatch and
   a clear path to add Phase 2 features (FFT/MATH, REFs, persistence, advanced
   triggers) without redesign.

## Architecture

```
  Claude  <-stdio->  MCP server (Python, FastMCP)
                          |
                          | reuses request_gpib.py as a library
                          v
                     WebSocket to ws://<host>/ws
                          |
                          v
                     AR-488-ESP32 gateway
                          |
                          v
                     GPIB bus -> TDS784A
```

- One persistent WebSocket connection for the server lifetime, with a
  single `asyncio.Lock` around send/recv. No reconnect logic — if the WS
  drops the user restarts the MCP server.
- Connection params come from env vars: `AR488_HOST` (required), `AR488_ADDR`
  (default 1), `AR488_TIMEOUT_MS` (default 2000).
- No caching. `*IDN?` and `SET?` are queried each time they're asked for.
- All I/O primitives (`one_shot`, `parse_ieee_block`, `parse_wfmpre`,
  `query_value`, `_setup_channel`, `_set_window`, `capture_channel`,
  `pcx_bytes_to_png`, …) are imported from `request_gpib.py`. Each consumed
  symbol is annotated in `request_gpib.py` with a comment warning that
  signature changes will break the MCP server. The CLI surface of
  `request_gpib.py` is free to evolve; the library surface is not.
- Hardcopy returns an inline MCP `image` content block (PNG) so Claude can
  *see* the screen, plus the bytes themselves for file persistence.

## Cross-cutting policies

### Error draining
After every command that changes scope state, the server queries `*ESR?` and
`ALLEv?` and surfaces any non-zero result as a structured error in the tool
response (alongside the success payload, not as an exception, so the AI can
read both). A read-only query never drains errors implicitly — there's a
dedicated `get_errors` tool.

### Units
Returned values are always SI (volts, seconds, hertz, ohms). Raw ADC codes
aren't exposed in v1 — `raw_scpi("CURVE?", binary=True)` is the escape hatch
if ever needed.

### Atomic multi-channel capture
`get_waveform(channels=[…])` performs one single-sequence acquisition and
reads all requested channels from that record. CH1 and CH2 are guaranteed to
share the same trigger event.

### Destructive-action guard
Two tools are gated behind an explicit `confirm=True` argument:
- `factory_reset` (FACtory) — wipes all NVRAM setups; the user wants to
  exercise this manually before trusting it.
- `set_setup_state` (sending an arbitrary SET? string back) — does **not**
  require a prior `factory_reset`; the AI may trust a previously captured
  state.

`*RST` is not exposed as a separate tool — `set_setup_state` covers
"restore a known good", and `factory_reset` covers "panic button".

### Statistics — two flavors, both exposed
The TDS784A firmware has **no** measurement-statistics SCPI group (no
running mean/min/max/stddev across acquisitions). Two compatible alternatives
are offered, and the AI is told what each one really computes:

- **Acquisition-level statistics** (`measure_with_acq_stats`): set the scope
  to `ACQUIRE:MODE AVERAGE` (or `ENVELOPE`) with N acquisitions, then take
  one measurement of the resulting smoothed/enveloped waveform. Fast, only
  one MEASUREMENT? at the end. Appropriate for *steady* signals where you
  want noise-free amplitude/timing readings. Cannot give you stddev — only
  the central tendency (AVERAGE) or the worst-case excursion (ENVELOPE).
- **Polled per-acquisition statistics** (`measure_with_polled_stats`): leave
  the scope in SAMPLE mode and poll `MEASUREMENT:IMMED:VALUE?` over N
  separate triggers. Aggregate mean/min/max/stddev/p5/p95 client-side.
  Slower (N round-trips), but answers questions about *jitter*, *drift*,
  and *distribution* that AVERAGE/ENVELOPE cannot.

Documenting this difference is part of the tool description so the AI picks
the right one.

---

# Phase 1 — v1 tool surface

~18 tools across 7 groups. Anything more obscure goes through `raw_scpi`.

## 1. Connection & status

### `verify_instrument_identity`
- SCPI: `*IDN?`
- Returns: `{vendor, model, serial, firmware}`.

### `get_errors`
- SCPI: `*ESR?` then `ALLEv?` (drain queue)
- Returns: list of `{code, message}` plus the raw ESR byte.

### `wait_operation_complete(timeout_s=10)`
- SCPI: `*OPC?` with polling
- Returns: `{ok: bool, elapsed_s}`. Used internally by single-shot capture;
  exposed for the AI to use after `set_setup_state` or large changes.

## 2. Setup state management

### `get_setup_state()`
- SCPI: `HEADER ON; SET?`
- Returns: `{setup_string, idn, captured_at}`.

### `set_setup_state(setup_string, confirm=False)`
- Sends the string verbatim, then `*OPC?`, then drains errors.
- **Refuses unless `confirm=True`.**
- Does **not** require a prior factory reset.

### `save_internal(slot)`
- SCPI: `*SAV <1..10>`

### `recall_internal(slot)`
- SCPI: `*RCL <1..10>`. Drains errors.

### `factory_reset(confirm=False)`
- SCPI: `FACtory`
- **Refuses unless `confirm=True`.** Most disruptive tool; user will
  validate it manually before trusting it.

## 3. Acquisition control

### `autoset()`
- SCPI: `AUTOSet EXECute`, then `*OPC?`.

### `set_acquisition_mode(mode)`
- mode ∈ `{SAMPLE, PEAKDETECT, HIRES, ENVELOPE, AVERAGE}`
- SCPI: `ACQUIRE:MODE <mode>`

### `set_average_count(n)` — n ∈ {2,4,8,…,10000}
- SCPI: `ACQUIRE:NUMAVG <n>`. Envelope count via `raw_scpi` if needed.

### `set_acquisition_state(state)` — state ∈ {RUN, STOP}
- SCPI: `ACQUIRE:STATE <state>`

### `arm_single_and_wait(timeout_s=30)` — atomic
- Sequence: `ACQUIRE:STOPAFTER SEQUENCE; ACQUIRE:STATE RUN; *OPC?`
- Returns when the scope reports OPC, or errors on timeout.
- This is the building block the AI uses to guarantee fresh data.

## 4. Vertical / horizontal / trigger setup

### `set_vertical(ch, scale_v=None, position_div=None, offset_v=None, coupling=None, bandwidth=None, impedance=None, probe_atten=None, units=None, deskew_s=None, invert=None)`
- Sends only the sub-commands whose argument is provided.
- Key SCPI: `CHx:SCALE`, `CHx:POSITION`, `CHx:OFFSET`, `CHx:COUPLING`,
  `CHx:BANDWIDTH`, `CHx:IMPEDANCE`, `CHx:PROBE`, `CHx:UNITS`, `CHx:DESKEW`,
  `CHx:INVERT`.
- Position vs. offset distinction is documented in the tool description.
- Channel on/off via `raw_scpi("SELECT:CH<n> ON|OFF")` if needed.

### `set_horizontal(scale_s=None, position_pct=None, record_length=None)`
- SCPI: `HORIZONTAL:MAIN:SCALE`, `HORIZONTAL:TRIGGER:POSITION`,
  `HORIZONTAL:RECORDLENGTH`.

### `set_trigger_edge(source=None, level_v=None, slope=None, coupling=None, holdoff_s=None, mode=None)`
- mode ∈ {AUTO, NORMAL}; slope ∈ {RISE, FALL}.
- SCPI: `TRIGGER:MAIN:TYPE EDGE` then `TRIGGER:MAIN:EDGE:*` and
  `TRIGGER:MAIN:LEVEL` / `:HOLDOFF:VALUE` / `:MODE`.
- v1 only covers edge triggers. Pulse/logic/runt/glitch are Phase 2.

### `get_acquisition_setup()`
- Single tool that returns the full read-only setup snapshot used by
  `request_gpib.py`'s `collect_metadata`: horizontal, trigger, acquire,
  per-channel state. Convenient for "save my context" without a full SET?.

## 5. Measurements

### `measure(ch, kind, source2=None)`
- Uses **immediate** measurements (`MEASUREMENT:IMMED`) so the on-screen
  MEAS1..4 slots are not disturbed.
- `kind` is one of the 25 supported types: AMPL, FREQ, PERIOD, RISE, FALL,
  PK2PK, MEAN, RMS, CRMS, DUTY, … delay-type measurements take `source2`.
- SCPI: `MEASUREMENT:IMMED:TYPE <kind>; SOURCE1 CHx; SOURCE2 CHy; VALUE?; UNITS?`
- Returns: `{value, unit, kind, source, source2}`.

### `measure_snapshot(ch)`
- SCPI: `MEASUREMENT:IMMED:SOURCE1 CHx; SNAPSHOT?`
- Returns: dict of all 25 measurements with units. One round-trip.

### `set_measurement_ref_levels(method=None, high=None, mid=None, low=None, mid2=None, units=None)`
- `method` ∈ {ABSolute, PERCent}; `units` ∈ {V, %}.
- SCPI: `MEASUREMENT:REFLEVEL:METHOD`,
  `MEASUREMENT:REFLEVEL:{ABS,PERC}:{HIGH,MID,LOW,MID2}`.
- Affects how rise/fall/duty are computed.
- Measurement gating (rare) is left to `raw_scpi`.

### `measure_with_acq_stats(ch, kind, mode='AVERAGE', count=64, source2=None)`
- Acquisition-level stats. Sets `ACQUIRE:MODE <mode>`, `NUMAVG/NUMENV count`,
  arms single-sequence, waits for OPC, takes one immediate measurement.
- Returns: `{value, unit, mode, count}`. With `mode=ENVELOPE` runs twice
  (one min, one max) — documented.

### `measure_with_polled_stats(ch, kind, n=32, source2=None, max_wall_s=30)`
- Polled per-acquisition stats. Loops `arm_single_and_wait` then
  `MEASUREMENT:IMMED:VALUE?` n times.
- Returns: `{n, mean, std, min, max, p5, p95, samples?}`.
- Slow; bounded by `max_wall_s`.

## 6. Waveform retrieval

### `get_waveform(channels, start_idx=None, end_idx=None, width=2)`
- Atomic multi-channel single-shot. Sequence:
  1. `ACQUIRE:STOPAFTER SEQUENCE; ACQUIRE:STATE RUN; *OPC?`
  2. For each channel: `DATA:SOURCE CHx`, `WFMPRE?`, `CURVE?`
  3. Convert raw codes → volts using preamble.
- Default `width=2` for full 16-bit fidelity (current CLI default is 1).
- Returns:
  ```
  {
    metadata: { … same shape as collect_metadata … },
    channels: {
      "CH1": { time_s: [...], voltage_v: [...], preamble: {…} },
      ...
    },
    start_idx, end_idx, samples_per_channel
  }
  ```
- Windowing via `start_idx`/`end_idx` (1-based inclusive), maps to
  DATA:START / DATA:STOP. Auto-chunking handled internally if window > 32 KiB.

## 7. Screen capture

### `get_screen(layout='PORTRAIT', palette='COLOR')`
- HARDCOPY sequence (PCXCOLOR → PNG client-side).
- Returns:
  - MCP `image` content block (PNG bytes inline) so the AI can see the
    screen visually.
  - Plus `{format: 'PNG', bytes_len, source_format: 'PCXCOLOR'}` metadata.
- Caller may choose to save the bytes; the MCP does not write a file by
  default.

## 8. Escape hatch (the safety valve for everything trimmed)

### `raw_scpi(command, expect_reply=None, binary=False, timeout_ms=None)`
- `expect_reply=None` autodetects from `?` in command (mirrors current CLI).
- `expect_reply=True` issues a `query` (or `binary_query` if `binary`).
- `expect_reply=False` issues a write.
- All traffic is logged. Drains errors after writes.
- Documented as the "anything I forgot" hatch.

---

# Phase 2 — deferred

Add when v1 is stable. Each is roughly one tool group.

| Group | Tools | Notes |
|---|---|---|
| Math waveforms | `define_math(slot, expr)`, `get_math_waveform(slot, …)` | Slot ∈ MATH1..3. Expr supports `CH1+CH2`, `CH1-CH2`, `FFT(CH1)`, etc. FFT requires the optional Advanced DSP firmware (verify on this unit). |
| Reference waveforms | `save_to_ref(slot, source)`, `recall_ref(slot)`, `get_ref_waveform(slot)` | REF1..4 in NVRAM. |
| Display persistence | `set_persistence(mode, time_s=None)` | INFINITE / VARIABLE / OFF. Killer feature for glitch hunting. |
| Advanced triggers | `set_trigger_pulse(...)`, `set_trigger_glitch(...)`, `set_trigger_runt(...)`, `set_trigger_logic(...)`, `set_trigger_video(...)` | One tool per trigger type to keep schemas tight. |
| Cursor measurements | Likely **skipped** in favor of client-side compute against captured waveforms. Re-evaluate. |
| Limit testing | `set_limit_test(template_ref, vert_tol_div, horiz_tol_div)`, `get_limit_status()` | Template-based pass/fail. |
| Higher-level intent tools | `characterize_channel(ch)`, `compare_to_reference(ch, ref)`, `sweep_and_measure(...)`, `find_anomaly(ch, duration_s)` | Compose Phase 1 primitives. |
| Calibration status | `get_calibration_status()` | `CAL?`, `CAL:TEMP?`. |

---

# Skill: `/scope`

A short Claude Code skill (`~/.claude/skills/scope.md`) that triggers on
"TDS784", "oscilloscope", etc. Documents the v1 tool surface, the
AVERAGE-vs-polled stats trade-off, the confirm-required tools, and points
at `raw_scpi` for anything not exposed.

---

# Tool count

**Phase 1**: ~18 tools. **Phase 2**: deferred backlog above (~15 more).
