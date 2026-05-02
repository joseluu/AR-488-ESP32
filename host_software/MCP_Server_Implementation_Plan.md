# MCP Server Implementation Plan — TDS784A

Companion to `MCP_Tools_for_TDS784A_measurements_revised.md`. The proposal
defines *what*; this file defines *how*.

## File layout

```
host_software/
├── request_gpib.py              ← existing CLI; library symbols annotated
├── mcp_server/
│   ├── __init__.py
│   ├── __main__.py              ← `python -m mcp_server` entry
│   ├── server.py                ← FastMCP app, tools, scope ops, error drain
│   └── client.py                ← persistent WS wrapper
├── pyproject.toml               ← add `mcp[cli]`; keep `pillow`, `websockets`
├── ../.claude/skills/scope.md   ← /scope skill
└── ../.mcp.json                 ← add `tek-tds784a` server entry
```

Two new modules, not five. `errors.py` and `scope.py` collapse into
`server.py` — the helpers are short and only the server uses them.

## Order of work

### 1. Annotate `request_gpib.py` for reuse
Add a `# MCP-LIBRARY:` comment to each symbol the MCP imports. No code
edits. The CLI surface (`parse_args`, `run_*`, `main`) is free to evolve;
the annotated functions are not.

Symbols to annotate: `iso_stamp`, `parse_ieee_block`, `parse_wfmpre`,
`_FLOAT_RE`, `one_shot`, `query_value`, `query_preamble`, `decode_samples`,
`_setup_channel`, `_set_window`, `capture_channel`, `collect_metadata`,
`pcx_bytes_to_png`, `_HARDCOPY_*`, `make_request`, `_GLOBAL_META_QUERIES`,
`_PER_CHANNEL_META_QUERIES`.

### 2. `mcp_server/client.py` — connection wrapper
- One persistent `websockets.connect`, lifetime = MCP server lifetime.
- One `asyncio.Lock` around send/recv (Claude can issue concurrent calls).
- `request(action, command, expect_binary)` reusing `make_request` and
  `one_shot` from `request_gpib.py`.
- Env: `AR488_HOST`, `AR488_ADDR`, `AR488_TIMEOUT_MS`.
- No reconnect logic, no caching. If the WS dies, restart the server.

### 3. `mcp_server/server.py` — tools + helpers
Includes a small `drain_errors(client)` (runs `*ESR?` and `ALLEv?`) and
the composite ops (`arm_single_and_wait`, `atomic_capture`, `polled_stats`,
`acq_stats`). Tools register in this order so each layer is testable
before the next is built on top:

1. **Plumbing**: `raw_scpi`, `verify_instrument_identity`, `get_errors`,
   `wait_operation_complete`.
2. **Setup state**: `get_setup_state`, `set_setup_state(confirm)`,
   `save_internal`, `recall_internal`, `factory_reset(confirm)`.
3. **Acquisition**: `autoset`, `set_acquisition_mode`, `set_average_count`,
   `set_acquisition_state`, `arm_single_and_wait`.
4. **Vertical / horizontal / trigger**: `set_vertical`, `set_horizontal`,
   `set_trigger_edge`, `get_acquisition_setup`.
5. **Measurements**: `measure`, `measure_snapshot`,
   `set_measurement_ref_levels`, `measure_with_acq_stats`,
   `measure_with_polled_stats`.
6. **Waveform**: `get_waveform` (atomic multi-channel).
7. **Screen**: `get_screen` returns
   `ImageContent(type="image", data=b64, mimeType="image/png")` plus
   metadata.

### 4. Hardware-in-the-loop smoke test
Walk through each tool once against the live scope. No mocks, no automated
test harness — single user, single instrument.

### 5. Skill `~/.claude/skills/scope.md`
Short frontmatter triggers on "TDS784" / "oscilloscope". Body lists the
v1 tools, the AVERAGE-vs-polled stats trade-off, the confirm-required
tools, and points at `raw_scpi` for anything missing.

### 6. `.mcp.json` entry
Add `tek-tds784a` invoked as `uv run python -m mcp_server` with
`AR488_HOST` from env. KiCad entry untouched.

## Open items (resolve while implementing)

- **SET? size and timing** on this firmware — set the per-call timeout.
- **`MEASUREMENT:TYPE` enum values** — query the scope; the manual lists
  25 but exact mnemonics matter for the schema.
- **Trigger holdoff range** — verify on the live unit.

## Time estimate

~2 days: half a day for steps 1–2, one day for step 3, half a day for
4–6. Gated on live-scope access.
