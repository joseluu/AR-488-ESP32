# AR-488-ESP32

A circuit-synth project for PCB design with Python.

## 🚀 Quick Start

```bash
# Run your circuit
uv run python circuit-synth/main.py
```

This will generate KiCad project files that you can open in KiCad.

## 📁 Included Circuits (1)

This project includes the following circuit templates:

1. **Resistor Divider** (Beginner ⭐): 5V → 3.3V logic level shifter
   - File: `circuit-synth/main.py`


You can run any circuit file independently or use them as reference for your own designs.

## 🏗️ Circuit-Synth Basics

### Creating Components

```python
from circuit_synth import Component, Net, circuit

# Create a resistor
resistor = Component(
    symbol="Device:R",           # KiCad symbol
    ref="R",                     # Reference prefix
    value="10k",                 # Component value
    footprint="Resistor_SMD:R_0603_1608Metric"
)
```

### Defining Nets and Connections

```python
# Create nets (electrical connections)
vcc = Net('VCC_3V3')
gnd = Net('GND')

# Connect component pins to nets
resistor[1] += vcc   # Pin 1 to VCC
resistor[2] += gnd   # Pin 2 to GND
```

### Generating KiCad Projects

```python
@circuit(name="My_Circuit")
def my_circuit():
    # Your circuit code here
    pass

if __name__ == '__main__':
    circuit_obj = my_circuit()
    circuit_obj.generate_kicad_project(
        project_name="my_project",
        generate_pcb=True
    )
```

### Manufacturing File Generation

All circuit templates automatically generate manufacturing files:

```python
# After generate_kicad_project(), templates also generate:

# 1. BOM (Bill of Materials) - CSV format for component ordering
bom_result = circuit_obj.generate_bom(project_name="my_project")

# 2. PDF Schematic - Documentation and review
pdf_result = circuit_obj.generate_pdf_schematic(project_name="my_project")

# 3. Gerber Files - PCB manufacturing (JLCPCB, PCBWay, etc.)
gerber_result = circuit_obj.generate_gerbers(project_name="my_project")
```

**Generated files:**
- `my_project/my_project_bom.csv` - Component list with references and values
- `my_project/my_project_schematic.pdf` - Printable schematic documentation
- `my_project/gerbers/` - Complete Gerber package for PCB fabrication

## 📖 Documentation

- Circuit-Synth: https://circuit-synth.readthedocs.io
- KiCad: https://docs.kicad.org

## 🤖 AI-Powered Design with Claude Code

This project includes specialized circuit design agents in `.claude/agents/`:

- **circuit-architect**: Master circuit design coordinator
- **circuit-synth**: Circuit code generation and KiCad integration
- **simulation-expert**: SPICE simulation and validation
- **component-guru**: Component sourcing and manufacturing optimization

Use natural language to design circuits with AI assistance!

## 🚀 Next Steps

1. Open `circuit-synth/main.py` and review the base circuit
2. Run the circuit to generate KiCad files
3. Open the generated `.kicad_pro` file in KiCad
4. Modify the circuit or create your own designs

**Happy circuit designing!** 🎛️
