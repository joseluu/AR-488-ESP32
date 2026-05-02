"""MCP server for Tektronix TDS784A via AR-488-ESP32 GPIB gateway.

See ../MCP_Tools_for_TDS784A_measurements_revised.md for the tool surface
and ../MCP_Server_Implementation_Plan.md for the implementation map.
"""
import os
import sys

# Make the sibling `request_gpib` module importable regardless of cwd.
_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)
