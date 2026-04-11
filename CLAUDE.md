# CLAUDE.md

Project-specific guidance for Claude Code when working on the AR-488-ESP32 GPIB interface.

## Project Overview

AR-488-ESP32 is a GPIB/IEEE-488 interface PCB for the Tektronix TDS784A oscilloscope. The schematic is written in Python using circuit-synth, generating KiCad 9 project files. PCB layout is done in KiCad with AI assistance via the MCP server.

## Key Files

- `circuit-synth/main.py` — Circuit description (Python, circuit-synth API)
- `AR488_ESP32/` — Generated KiCad project (.kicad_sch, .kicad_pro, .kicad_pcb)
- `AR488_ESP32/libs/` — Custom symbol and footprint libraries
- `.mcp.json` — MCP server configuration for Claude Code

## Schematic Generation

```bash
# Required env vars for custom library resolution
export KICAD_SYMBOL_DIR="C:/Program Files/KiCad/9.0/share/kicad/symbols;$(pwd)/AR488_ESP32/libs"
export PYTHONIOENCODING=utf-8
uv run python circuit-synth/main.py
```

**Known issue:** Incremental sync fails with `PowerSymbolLabel has no attribute 'uuid'`. Fix: temporarily add `force_regenerate=True` to `generate_kicad_project()`, run, then remove it. Always remove before committing.

**Post-processing:** The script patches the generated .kicad_sch with regex to set A4 paper size and title block (rev, date) — circuit-synth API doesn't expose these.

## KiCad MCP Server (PCB editor)

The MCP server (mixelpixx/KiCAD-MCP-Server) allows Claude to read and modify the PCB.

### Backend behavior

- **IPC backend** (read ops): `get_board_info`, `get_component_pads`, `get_nets_list` work in real-time via KiCad's IPC API
- **SWIG backend** (write ops): `route_pad_to_pad`, `move_component`, etc. write to the .kicad_pcb file directly. The user must **File > Revert** in KiCad to see changes.
- Check the `_backend` and `_realtime` fields in MCP responses to know which backend handled the call
- Always call `open_project` with the .kicad_pcb path before using SWIG write operations

### Useful MCP tools

| Tool | Use for |
|------|---------|
| `get_board_info` | Check connection, backend, component/track counts |
| `get_component_pads` | Get pad positions, nets, sizes for a component |
| `get_nets_list` | List all nets with net codes |
| `get_design_rules` | Check track width, clearance, via sizes |
| `route_pad_to_pad` | Route a trace between two component pads |
| `get_component_list` | List all components on the board |
| `run_drc` | Run design rule check |
| `move_component` | Move a component to new coordinates |

### Workaround for unreliable SWIG writes

If `route_pad_to_pad` reports success but the trace doesn't appear after revert, write the segment directly into the .kicad_pcb file:

```python
# Add a (segment ...) block before the last closing paren in the .kicad_pcb
# Use pad positions from get_component_pads, net code from get_nets_list
```

## Net Classes

Power nets (`/DC_7-12V`, `/LDO_IN`, `GND`, `+5V`, `+3V3`) are assigned to the **Power** net class in the .kicad_pro file: 0.6mm track width (3x default), 0.3mm clearance, 0.8mm via diameter.

## Versioning

Bump the revision in `circuit-synth/main.py` (post-processing section) at each design change. Commit at each revision. Current: v0.4.

## Custom 3D Models

VRML (.wrl) models are in `AR488_ESP32/libs/AR488_custom.3dshapes/`. Models use meters internally (VRML standard). The footprint `(model ...)` entry needs a scale factor to convert to KiCad's mm. Empirically determined scale: **~394** (not 1000 as expected — likely due to KiCad's internal VRML import scaling). Apply the same scale to all three axes.

Rotation `-90` on X axis is typically needed to align VRML Y-up with KiCad's coordinate system.

## Slash Commands

- `/find-symbol` — Search KiCad symbol libraries
- `/find-footprint` — Search KiCad footprint libraries
