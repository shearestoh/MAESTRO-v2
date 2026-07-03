"""
Instrument adapters for MAESTRO.

Each adapter implements the interface between MAESTRO's execution engine
and a specific instrument — virtual, simulated, or real hardware.

Adapter pattern:
  - Virtual/simulated instruments: implement measurement/control logic here
  - Real hardware instruments: call the instrument's SDK/API here

The adapter module path is stored in VirtualInstrument.adapter and
loaded dynamically by the execution engine.
"""