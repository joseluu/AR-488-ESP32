# CLAUDE.md

Project-specific guidance for Claude Code when working with this circuit-synth project.

## 🚀 Project Overview

This is a **circuit-synth project** for PCB design with Python code.

## 📝 Included Circuits (1)

This project includes the following circuit templates:

1. **Resistor Divider** (Beginner ⭐)
   - 5V → 3.3V logic level shifter
   - File: `circuit-synth/main.py`

You can modify these circuits or use them as reference for creating new designs.

## ⚡ Available Tools & Commands

### Slash Commands
- `/find-symbol` - Search KiCad symbol libraries
- `/find-footprint` - Search KiCad footprint libraries
- `/find_stm32` - STM32-specific component search

### Specialized Agents
- **circuit-architect** - Master coordinator for complex projects
- **circuit-synth** - Circuit code generation and KiCad integration
- **simulation-expert** - SPICE simulation and validation
- **component-guru** - Component sourcing and manufacturing

## 🔧 Development Workflow

1. **Component Selection**: Use `/find-symbol` and `/find-footprint` to find KiCad components
2. **Circuit Design**: Write Python code using circuit-synth
3. **Generate KiCad**: Run the Python file to create KiCad project
4. **Manufacturing Files**: Templates automatically generate BOM, PDF, and Gerbers
5. **Validate**: Open in KiCad and verify the design

## 📚 Quick Reference

### Component Creation
```python
component = Component(
    symbol="Device:R",
    ref="R",
    value="10k",
    footprint="Resistor_SMD:R_0603_1608Metric"
)
```

### Net Connections
```python
vcc = Net("VCC_3V3")
component[1] += vcc
```

### Manufacturing Exports
```python
# All templates automatically generate manufacturing files:
circuit_obj.generate_bom(project_name="my_project")          # BOM CSV
circuit_obj.generate_pdf_schematic(project_name="my_project")  # PDF schematic
circuit_obj.generate_gerbers(project_name="my_project")      # Gerber files
```

**Output:**
- BOM: `my_project/my_project_bom.csv`
- PDF: `my_project/my_project_schematic.pdf`
- Gerbers: `my_project/gerbers/` (ready for JLCPCB, PCBWay, etc.)

---

**This project is optimized for AI-powered circuit design with Claude Code!** 🎛️
