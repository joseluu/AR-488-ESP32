# MCP Server Implementation Plan — TDS784A

Companion document to
`MCP_Tools_for_TDS784A_measurements_revised.md`. The revised proposal
defines the tool surface and policies; this file specifies how the code is
organized, the order of work, and the open items to resolve during
implementation.

## File layout

```
host_software/
├── request_gpib.py              ← existing CLI; library symbols annotated
├── mcp_server/
│   ├── __init__.py
│   ├── __main__.py              ← `python -m mcp_server` entry point
│   ├── server.py                ← FastMCP app + tool registrations
│   ├── client.py                ← persistent WS connection + asyncio lock
│   ├── scope.py                 ← high-level ops (atomic capture, stats)
│   ├── errors.py                ← *ESR/ALLEv drain + error classes
│   └── README.md
├── pyproject.toml               ← add `mcp[cli]`, keep `pillow`, `websockets`
└── ../.claude/skills/scope.md   ← /scope skill
└── ../.mcp.json                 ← add `tek-tds784a` server entry
```

## Order of work

### 1. Refactor `request_gpib.py` for reuse (no behavior change)
Annotate every symbol the MCP imports with a comment like
`# MCP-LIBRARY: signature changes break mcp_server/...`. Affected symbols
to mark:

- `iso_stamp`
- `parse_ieee_block`
- `parse_wfmpre`
- `_FLOAT_RE`
- `one_shot`
- `query_value`
- `query_preamble`
- `decode_samples`
- `encode_samples_bytes`
- `_setup_channel`
- `_set_window`
- `capture_channel`
- `collect_metadata`
- `pcx_bytes_to_png`
- `_HARDCOPY_*` constants
- `make_request`
- `_GLOBAL_META_QUERIES`
- `_PER_CHANNEL_META_QUERIES`

No code edits — just headers/comments. The CLI surface
(`parse_args`, `run_*`, `main`) is free to evolve.

### 2. `mcp_server/client.py` — persistent connection
Wraps `websockets.connect` with:
- Auto-reconnect on disconnect.
- `asyncio.Lock` around send/recv so only one SCPI exchange is in flight.
- `request(action, command, expect_binary)` returning `(meta, payload)`,
  reusing `make_request` and `one_shot` from `request_gpib.py`.
- Reads env vars `AR488_HOST`, `AR488_ADDR`, `AR488_TIMEOUT_MS`.
- Single global instance for the MCP server lifetime.

### 3. `mcp_server/errors.py` — error drain
- `async def drain_errors(client) -> list[ScopeError]` that runs `*ESR?`
  then `ALLEv?`, parses the queue, returns structured records.
- Helper `await_with_drain(coro)` that calls drain after a write.
- `ScopeError` dataclass: `{code, message, raw}`.

### 4. `mcp_server/scope.py` — composite ops
Higher-level operations that combine primitives:
- `arm_single_and_wait(timeout_s)`
- `atomic_capture(channels, start, end, width)` — single-sequence + per-channel
  CURVE? from the same record.
- `polled_stats(ch, kind, n)` — N independent triggers, aggregate client-side.
- `acq_stats(ch, kind, mode, count)` — AVERAGE/ENVELOPE acquisition then
  one measurement.

These reuse `_setup_channel`, `_set_window`, `capture_channel`,
`collect_metadata` from `request_gpib.py`.

### 5. `mcp_server/server.py` — register tools
Sub-steps in implementation order so each layer can be smoke-tested before
building on it:

1. **Plumbing smoke test**: `raw_scpi`, `verify_instrument_identity`,
   `get_errors`, `wait_operation_complete`, `get_busy`.
2. **Setup state management**: `get_setup_state`, `set_setup_state(confirm)`,
   `save_internal`, `recall_internal`, `factory_reset(confirm)`,
   `system_reset(confirm)`.
3. **Acquisition control**: `autoset`, `set_acquisition_mode`,
   `set_average_count`, `set_envelope_count`, `set_acquisition_state`,
   `set_stop_after`, `arm_single_and_wait`.
4. **Vertical / horizontal / trigger**: `set_vertical`, `set_channel_display`,
   `set_horizontal`, `set_trigger_edge`, `get_acquisition_setup`.
5. **Measurements**: `measure`, `measure_snapshot`,
   `set_measurement_ref_levels`, `set_measurement_gating`,
   `measure_with_acq_stats`, `measure_with_polled_stats`.
6. **Waveforms**: `get_waveform`, `get_waveform_raw`.
7. **Screen capture**: `get_screen` returns
   `ImageContent(type="image", data=b64, mimeType="image/png")` plus metadata.

### 6. Hardware-in-the-loop smoke test
A short manual checklist in `mcp_server/README.md` that walks through each
tool once against the live scope. No automated tests in v1 — the
gateway/ESP32/scope chain isn't worth mocking at this scale.

### 7. Skill file `~/.claude/skills/scope.md`
Frontmatter triggers on "TDS784", "oscilloscope", "scope measurement",
etc. Body documents:
- The Phase 1 surface.
- AVERAGE-vs-polled stats trade-off (when to use which).
- The confirm-required tools (factory_reset, system_reset, set_setup_state).
- The Phase 2 backlog so the AI doesn't ask for tools that don't exist.
- Common workflows: autoset+characterize, before/after with
  `get_setup_state`, atomic multi-channel capture.

### 8. `.mcp.json` entry
Add a `tek-tds784a` server invoked as `uv run python -m mcp_server` with
`AR488_HOST` set to the gateway IP. The existing KiCad MCP entry stays
untouched.

### 9. Phase 2 backlog stub
`mcp_server/PHASE2.md` with the table from the revised proposal so future
work picks up cleanly without re-deriving the design.

## Open items to resolve during implementation

- **SET? size and timing** on this firmware — set the per-call timeout
  accordingly.
- **Available `MEASUREMENT:TYPE` enum values** — confirmed by querying the
  scope (`MEASUREMENT:IMMED:TYPE?` with some probing). The manual lists 25
  but the exact mnemonics matter for the tool's enum schema.
- **Trigger holdoff range** — different on B-series firmware; verify on
  the live unit.

## Time estimate

| Steps | Effort |
|---|---|
| 1–4 (refactor + plumbing + scope ops) | ½ day |
| 5 (tool registrations) | 1 day |
| 6–8 (smoke test, skill, .mcp.json) | ½ day |
| **Total** | **~2 days** of focused work, gated on live-scope access |
