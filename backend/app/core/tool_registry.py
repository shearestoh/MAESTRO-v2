"""
Instrument registry for MAESTRO.

Instruments are defined and managed here. They persist to SQLite.

Categories:
  physical      — lab hardware (synthesis, characterisation)
  computational — algorithms and data tools (data, simulation, modelling)

To add a new instrument:
  1. Via UI: Lab Setup → Instruments → Add Instrument (recommended)
  2. Via code: call TOOL_REGISTRY.register(VirtualInstrument(...)) at startup

For physical instruments connected to real hardware, implement an adapter
in backend/app/adapters/ and reference it in the instrument's metadata.
For virtual/simulated instruments, implement the simulation logic in
backend/app/adapters/ and call it from the execution engine (tools.py).
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class InstrumentParameter(BaseModel):
    name:        str
    type:        str = "continuous"
    min:         Optional[float] = None
    max:         Optional[float] = None
    unit:        str = ""
    description: str = ""
    required:    bool = True


class InstrumentOutput(BaseModel):
    name:        str
    type:        str = "scalar"
    unit:        str = ""
    description: str = ""


class InstrumentFailureMode(BaseModel):
    name:        str
    description: str
    probability: float = 0.0


class VirtualInstrument(BaseModel):
    tool_id:       str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:          str
    kind:          str
    category:      str = "physical"
    sub_category:  str = ""
    description:   str
    parameters:    List[InstrumentParameter]   = Field(default_factory=list)
    outputs:       List[InstrumentOutput]      = Field(default_factory=list)
    failure_modes: List[InstrumentFailureMode] = Field(default_factory=list)
    time_cost_min: float = 0.0
    enabled:       bool  = True
    is_default:    bool  = False
    adapter:       str   = ""
    metadata:      Dict[str, Any] = Field(default_factory=dict)


VirtualTool = VirtualInstrument


class InstrumentRegistry:
    def __init__(self):
        self._instruments: Dict[str, VirtualInstrument] = {}

    def register(self, instrument: VirtualInstrument) -> VirtualInstrument:
        self._instruments[instrument.tool_id] = instrument
        self._persist_one(instrument)
        return instrument

    def get(self, tool_id: str) -> Optional[VirtualInstrument]:
        return self._instruments.get(tool_id)

    def get_by_name(self, name: str) -> Optional[VirtualInstrument]:
        return next(
            (t for t in self._instruments.values() if t.name == name), None
        )

    def list_all(self) -> List[VirtualInstrument]:
        return [t for t in self._instruments.values() if t.enabled]

    def list_by_category(self, category: str) -> List[VirtualInstrument]:
        return [t for t in self.list_all() if t.category == category]

    def list_physical(self) -> List[VirtualInstrument]:
        return self.list_by_category("physical")

    def list_computational(self) -> List[VirtualInstrument]:
        return [
            t for t in self.list_by_category("computational")
            if t.sub_category != "optimiser"
        ]

    def remove(self, tool_id: str) -> bool:
        if tool_id in self._instruments:
            del self._instruments[tool_id]
            self._delete_persisted(tool_id)
            return True
        return False

    def update(self, tool_id: str, updates: Dict[str, Any]) -> Optional[VirtualInstrument]:
        if tool_id not in self._instruments:
            return None
        data = self._instruments[tool_id].model_dump()
        data.update(updates)
        self._instruments[tool_id] = VirtualInstrument(**data)
        self._persist_one(self._instruments[tool_id])
        return self._instruments[tool_id]

    def all_controllable_parameters(self) -> List[str]:
        params: set = set()
        for t in self.list_all():
            for p in t.parameters:
                params.add(p.name)
        return sorted(params)

    def all_measurable_outputs(self) -> List[str]:
        outputs: set = set()
        for t in self.list_all():
            for o in t.outputs:
                outputs.add(o.name)
        return sorted(outputs)

    def get_time_cost(self, instrument_name: str, default: float = 0.0) -> float:
        inst = self.get_by_name(instrument_name)
        if inst and inst.time_cost_min > 0:
            return inst.time_cost_min
        return default

    def check_feasibility(
        self,
        required_params:  List[str],
        required_outputs: List[str],
    ) -> dict:
        controllable    = set(self.all_controllable_parameters())
        measurable      = set(self.all_measurable_outputs())
        missing_params  = [p for p in required_params  if p not in controllable]
        missing_outputs = [o for o in required_outputs if o not in measurable]
        return {
            "feasible":          not missing_params and not missing_outputs,
            "missing_params":    missing_params,
            "missing_outputs":   missing_outputs,
            "available_params":  sorted(controllable),
            "available_outputs": sorted(measurable),
        }

    def to_llm_context(self) -> str:
        instruments = self.list_all()
        if not instruments:
            return "No instruments registered."
        lines = ["Registered lab instruments:\n"]
        for t in instruments:
            lines.append(f"### {t.name} ({t.category} / {t.sub_category or t.kind})")
            lines.append(f"  {t.description}")
            if t.parameters:
                lines.append("  Controllable parameters:")
                for p in t.parameters:
                    rng = f" [{p.min}–{p.max} {p.unit}]" if p.min is not None else ""
                    lines.append(f"    - {p.name}{rng}: {p.description}")
            if t.outputs:
                lines.append("  Measurable outputs:")
                for o in t.outputs:
                    lines.append(f"    - {o.name} ({o.unit}): {o.description}")
            if t.failure_modes:
                lines.append("  Failure modes:")
                for fm in t.failure_modes:
                    if fm.probability > 0:
                        lines.append(
                            f"    - {fm.name} (p≈{fm.probability:.0%}): {fm.description}"
                        )
            if t.time_cost_min > 0:
                lines.append(f"  Time cost: {t.time_cost_min} min per call")
            lines.append("")
        return "\n".join(lines)

    def to_dict_list(self) -> List[dict]:
        return [t.model_dump() for t in self.list_all()]

    def load_from_db(self) -> None:
        try:
            import sqlite3
            from app.core.config import DB_PATH
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS instruments (
                    tool_id    TEXT PRIMARY KEY,
                    definition TEXT NOT NULL,
                    is_default INTEGER DEFAULT 0
                )
            """)
            con.commit()
            rows = cur.execute("SELECT definition FROM instruments").fetchall()
            con.close()
            for (defn,) in rows:
                try:
                    data = json.loads(defn)
                    inst = VirtualInstrument(**data)
                    self._instruments[inst.tool_id] = inst
                except Exception as e:
                    print(f"[WARN] Could not load instrument: {e}")
        except Exception as e:
            print(f"[WARN] Could not load instruments from DB: {e}")

    def _persist_one(self, instrument: VirtualInstrument) -> None:
        try:
            import sqlite3
            from app.core.config import DB_PATH
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS instruments (
                    tool_id    TEXT PRIMARY KEY,
                    definition TEXT NOT NULL,
                    is_default INTEGER DEFAULT 0
                )
            """)
            cur.execute(
                "INSERT OR REPLACE INTO instruments (tool_id, definition, is_default) "
                "VALUES (?, ?, ?)",
                (instrument.tool_id, instrument.model_dump_json(),
                 1 if instrument.is_default else 0),
            )
            con.commit()
            con.close()
        except Exception as e:
            print(f"[WARN] Could not persist instrument {instrument.name}: {e}")

    def _delete_persisted(self, tool_id: str) -> None:
        try:
            import sqlite3
            from app.core.config import DB_PATH
            con = sqlite3.connect(DB_PATH)
            con.execute("DELETE FROM instruments WHERE tool_id = ?", (tool_id,))
            con.commit()
            con.close()
        except Exception as e:
            print(f"[WARN] Could not delete instrument {tool_id}: {e}")


INSTRUMENT_REGISTRY = InstrumentRegistry()
TOOL_REGISTRY       = INSTRUMENT_REGISTRY


def register_default_instruments() -> None:
    """
    Register demo instruments for the battery electrode optimisation example.
    Only runs if no instruments exist in the database.

    Time cost values are in seconds for virtual instruments.
    Real instruments should set time_cost_min=0 (no artificial delay).
    """
    INSTRUMENT_REGISTRY.load_from_db()

    if INSTRUMENT_REGISTRY.list_all():
        print(f"[INFO] Loaded {len(INSTRUMENT_REGISTRY.list_all())} instrument(s) from database")
        return

    print("[INFO] No instruments found — registering demo instruments")

    INSTRUMENT_REGISTRY.register(VirtualInstrument(
        name="Electrode Coater",
        kind="instrument",
        category="physical",
        sub_category="synthesis",
        description=(
            "Prepares battery electrode samples by controlling active material "
            "composition and electrode porosity. Simulates slurry coating and "
            "calendering. Backed by a simulation adapter."
        ),
        parameters=[
            InstrumentParameter(
                name="active_material", type="continuous",
                min=88.0, max=98.0, unit="wt%",
                description="Weight fraction of active electrode material",
            ),
            InstrumentParameter(
                name="porosity", type="continuous",
                min=20.0, max=60.0, unit="%",
                description="Electrode porosity — affects ion transport",
            ),
        ],
        outputs=[],
        failure_modes=[
            InstrumentFailureMode(
                name="electrode_defect",
                description="Sample preparation fails. Probability increases at high active_material + low porosity.",
                probability=0.06,
            ),
        ],
        time_cost_min=5.0,  # seconds of simulated operation time
        adapter="app.adapters.electrode_coater",
        is_default=True,
    ))

    INSTRUMENT_REGISTRY.register(VirtualInstrument(
        name="Potentiostat",
        kind="instrument",
        category="physical",
        sub_category="characterisation",
        description=(
            "Electrochemical discharge tester. Measures specific energy of a "
            "prepared electrode sample under a specified constant power discharge. "
            "Backed by a validated surrogate model. Measurement includes "
            "Gaussian noise (σ=0.5 Wh/kg) to simulate real instrument variability."
        ),
        parameters=[
            InstrumentParameter(
                name="power_W", type="continuous",
                min=50.0, max=250.0, unit="W",
                description="Constant discharge power applied during test",
            ),
        ],
        outputs=[
            InstrumentOutput(
                name="specific_energy", type="scalar",
                unit="Wh/kg",
                description="Gravimetric specific energy of the electrode",
            ),
        ],
        failure_modes=[
            InstrumentFailureMode(
                name="connection_failure",
                description="Instrument connection lost or sample contact failure.",
                probability=0.02,
            ),
        ],
        time_cost_min=8.0,  # seconds of simulated operation time
        adapter="app.adapters.potentiostat",
        is_default=True,
    ))

    INSTRUMENT_REGISTRY.register(VirtualInstrument(
        name="SQLite Database",
        kind="data",
        category="computational",
        sub_category="data",
        description=(
            "Persistent SQLite store for all experimental results. "
            "Supports read-only SQL SELECT queries for analysis and reporting."
        ),
        parameters=[],
        outputs=[
            InstrumentOutput(
                name="query_result", type="vector",
                unit="", description="Rows matching the SQL query",
            ),
        ],
        failure_modes=[],
        time_cost_min=0.0,
        is_default=True,
    ))