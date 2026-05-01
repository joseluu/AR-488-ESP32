## Design workflow with claude _ circuitsynth and kicad

The schematic is written in Python using [circuit-synth](https://github.com/circuit-synth/circuit-synth), which generates KiCad 9/10 project files. The PCB layout is done in KiCad, assisted by AI through the IPC API.

```mermaid
flowchart TD
    A["circuit-synth/main.py\nPython circuit description"] --> B["circuit-synth\nGenerates .kicad_sch, .kicad_pro, netlist"]
    B --> C["KiCad schematic editor\nReview, ERC"]
    C --> D["KiCad PCB editor\nImport netlist, place components manually"]
    D --> E["FreeRouting\nAutoroute bulk signals"]
    E --> F["AI via IPC API (MCP server)\nRefine routing, ground plane, DRC review"]
    F --> G["Final review + Gerbers\nManufacturing files"]
```

### Generating the schematic

```bash
export KICAD_SYMBOL_DIR="C:/Program Files/KiCad/9.0/share/kicad/symbols;$(pwd)/libs"
export PYTHONIOENCODING=utf-8
uv run python circuit-synth/main.py
```

The generated KiCad project is in `AR488_ESP32/`.

## Development environment setup

### Prerequisites

- **OS:** Windows 11 under **Git Bash** (Unix shell syntax throughout)
- **Python:** 3.12 via [uv](https://github.com/astral-sh/uv)
- **KiCad:** 9.0 (or 10.0 — the IPC API is the same)
- **FreeRouting:** installed as KiCad plugin or [standalone](https://github.com/freerouting/freerouting)

### Installing circuit-synth

circuit-synth is included as a **git submodule** pointing to `joseluu/circuit-synth` on the `fix/windows-utf8-file-write` branch. This branch contains fixes for Windows UTF-8 encoding issues (emoji in logs, missing `encoding="utf-8"` on `write_text()` calls) that are not yet merged upstream.

```bash
# Clone with submodule
git clone --recurse-submodules <this-repo-url>
cd AR-488-ESP32

# Or if already cloned without submodules
git submodule update --init

# Create the virtual environment and install circuit-synth in editable mode
uv sync
```

The `pyproject.toml` references circuit-synth as a local editable dependency:

```toml
[tool.uv.sources]
circuit-synth = { path = "circuit-synth", editable = true }
```

If the upstream UTF-8 fixes are eventually merged into `circuit-synth/circuit-synth`, you can switch the submodule to track the official repo instead.

### Custom KiCad libraries

The `libs/` directory contains project-specific symbols and footprints:

- `AR488_custom.kicad_sym` — SN75161BN (not in KiCad standard library), AO4407A P-FET
- `AR488_custom.pretty/Centronics_24_GPIB.kicad_mod` — Centronics 24-pin plug (2x12, 2.159mm pitch, 4.45mm row spacing, top-bottom pin numbering)
- `AR488_custom.pretty/Heltec_WiFi_Kit_32_V2.kicad_mod` — ESP32 module header (2x18, 22.86mm row spacing)

These are referenced via `KICAD_SYMBOL_DIR` at generation time (see above).

## AI-assisted PCB routing (Option C)

The PCB layout is refined using Claude via KiCad's IPC API and the Model Context Protocol (MCP).

### Setting up the MCP server

1. **Enable IPC API in KiCad:** Preferences > Plugins > Enable IPC API Server

2. **Install the MCP server** — we use [mixelpixx/KiCAD-MCP-Server](https://github.com/mixelpixx/KiCAD-MCP-Server) (Node.js + Python):

   ```bash
   # Clone next to this project
   cd ..
   git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git
   cd KiCAD-MCP-Server

   # Install Node.js dependencies and build (requires Node.js 18+)
   npm install          # also runs tsc via postinstall

   # Install Python dependencies into KiCad's bundled Python (NOT system Python)
   # KiCad 9 ships its own Python 3.11 — the MCP server must use it because
   # pcbnew.pyd is compiled for that specific interpreter.
   "/c/Program Files/KiCad/9.0/bin/python.exe" -m pip install -r requirements.txt
   ```

3. **Install the IPC backend** (optional but recommended for real-time UI sync):

   ```bash
   # Install kicad-python (provides kipy — Protocol Buffers + NNG transport)
   "/c/Program Files/KiCad/9.0/bin/python.exe" -m pip install kicad-python
   ```

   The MCP server auto-detects the backend at startup:
   - **IPC backend** (`kipy` installed + KiCad running with IPC enabled): real-time UI sync, read operations work live. Write operations (routing) currently fall back to SWIG.
   - **SWIG backend** (fallback): reads/writes `.kicad_pcb` directly. Requires File > Revert in KiCad to see changes.

   SWIG is deprecated in KiCad 9 and will be removed in KiCad 10. The IPC write path is under active development.

4. **Configure Claude Code** — create a `.mcp.json` file in the **AR-488-ESP32 project directory** (already checked into the repo):

   ```json
   {
     "mcpServers": {
       "kicad": {
         "command": "<full-path-to-node>",
         "args": ["<path-to>/KiCAD-MCP-Server/dist/index.js"],
         "env": {
           "KICAD_PROJECT_DIR": "<path-to>/AR-488-ESP32/AR488_ESP32",
           "KICAD_PYTHON": "C:/Program Files/KiCad/9.0/bin/python.exe"
         }
       }
     }
   }
   ```

   Key points:
   - Use the **full path to node** (nvm-managed node isn't on PATH for spawned processes)
   - `KICAD_PYTHON` tells the server to use KiCad's bundled Python (required for pcbnew access)
   - Claude Code detects `.mcp.json` automatically when launched from the project directory

5. **Workflow:**
   - Open the PCB in KiCad's PCB editor
   - Enable IPC API: Preferences > Plugins > Enable IPC API Server
   - Place components manually (connector at board edge, decoupling caps near their ICs)
   - Manually route critical traces (power rails, high-speed signals)
   - Run FreeRouting to autoroute remaining signals (install via Plugin and Content Manager)
   - Use Claude via MCP to review DRC, optimize trace widths, add ground plane, adjust silkscreen
   - After SWIG writes: File > Revert to see changes in KiCad

### Current limitations

- The IPC API only supports the **PCB editor** (pcbnew). There is no schematic API yet — that's why we generate `.kicad_sch` files directly with circuit-synth.
- The mixelpixx MCP server uses IPC for read operations but falls back to SWIG for writes (routing, component placement). After SWIG writes, you must File > Revert in KiCad.
- Headless mode (kicad-cli as IPC server) is planned but not yet implemented.
- SWIG is deprecated in KiCad 9 and will be removed in KiCad 10 — plan to migrate to full IPC.
- Alternative: [Finerestaurant/kicad-mcp-python](https://github.com/Finerestaurant/kicad-mcp-python) is IPC-only (no SWIG) but still v0.1.
