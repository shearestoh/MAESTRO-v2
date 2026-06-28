"""
Domain-agnostic instrument registry — single source of truth for
lab capabilities.

Phase 3: renamed from 'tool registry' to 'instrument registry'
to clarify the distinction between:
  - Instruments (physical/virtual lab equipment registered here)
  - Agent actions (LLM-callable functions in llm.py)

Backward compat: TOOL_REGISTRY alias kept so existing imports
don't break during transition.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Instrument component schemas ──────────────────────────────────────────────

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
    """
    A virtual lab instrument or computational service.

    Domain-agnostic: no hardcoded parameter names.
    The LLM reads descriptions to understand capabilities.

    kind values:
      instrument   — physical lab equipment (sampler, tester, reactor)
      optimiser    — computational optimisation engine
      analyser     — data analysis / reporting tool
      data         — data store / database
      custom       — user-defined
    """
    tool_id:       str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:          str
    kind:          str
    description:   str
    parameters:    List[InstrumentParameter]   = Field(default_factory=list)
    outputs:       List[InstrumentOutput]      = Field(default_factory=list)
    failure_modes: List[InstrumentFailureMode] = Field(default_factory=list)
    time_cost_min: float = 0.0
    enabled:       bool  = True
    metadata:      Dict[str, Any] = Field(default_factory=dict)

    # Backward compat aliases
    @property
    def instrument_id(self) -> str:
        return self.tool_id


# Backward compat alias
VirtualTool = VirtualInstrument


# ── Registry ──────────────────────────────────────────────────────────────────

class InstrumentRegistry:
    """
    In-memory registry of all virtual instruments.

    Previously called ToolRegistry — renamed for clarity.
    TOOL_REGISTRY alias maintained for backward compatibility.
    """

    def __init__(self):
        self._instruments: Dict[str, VirtualInstrument] = {}

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def register(self, instrument: VirtualInstrument) -> VirtualInstrument:
        self._instruments[instrument.tool_id] = instrument
        return instrument

    def get(self, tool_id: str) -> Optional[VirtualInstrument]:
        return self._instruments.get(tool_id)

    def get_by_name(self, name: str) -> Optional[VirtualInstrument]:
        return next(
            (t for t in self._instruments.values() if t.name == name),
            None,
        )

    def list_all(self) -> List[VirtualInstrument]:
        return [t for t in self._instruments.values() if t.enabled]

    def remove(self, tool_id: str) -> bool:
        if tool_id in self._instruments:
            del self._instruments[tool_id]
            return True
        return False

    def update(
        self, tool_id: str, updates: Dict[str, Any]
    ) -> Optional[VirtualInstrument]:
        if tool_id not in self._instruments:
            return None
        data = self._instruments[tool_id].model_dump()
        data.update(updates)
        self._instruments[tool_id] = VirtualInstrument(**data)
        return self._instruments[tool_id]

    # ── Queries ───────────────────────────────────────────────────────────────

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

    def get_instruments_by_kind(self, kind: str) -> List[VirtualInstrument]:
        """Return all enabled instruments of a given kind."""
        return [t for t in self.list_all() if t.kind == kind]

    def get_sample_preparers(self) -> List[VirtualInstrument]:
        """Return instruments that can prepare samples (have parameters, no outputs)."""
        return [
            t for t in self.list_all()
            if t.kind == "instrument" and t.parameters and not t.outputs
        ]

    def get_sample_testers(self) -> List[VirtualInstrument]:
        """Return instruments that can test samples (have outputs)."""
        return [
            t for t in self.list_all()
            if t.kind == "instrument" and t.outputs
        ]

    def check_feasibility(
        self,
        required_params:  List[str],
        required_outputs: List[str],
    ) -> dict:
        controllable = set(self.all_controllable_parameters())
        measurable   = set(self.all_measurable_outputs())

        missing_params  = [p for p in required_params  if p not in controllable]
        missing_outputs = [o for o in required_outputs if o not in measurable]

        return {
            "feasible":          len(missing_params) == 0 and len(missing_outputs) == 0,
            "missing_params":    missing_params,
            "missing_outputs":   missing_outputs,
            "available_params":  sorted(controllable),
            "available_outputs": sorted(measurable),
        }

    def to_llm_context(self) -> str:
        """
        Render registry as structured text for LLM system prompt.
        Called on every LLM invocation.
        """
        instruments = self.list_all()
        if not instruments:
            return "No instruments registered in the virtual lab."

        lines = ["Available virtual lab instruments:\n"]
        for t in instruments:
            lines.append(f"### {t.name} ({t.kind})")
            lines.append(f"  {t.description}")
            if t.parameters:
                lines.append("  Controllable parameters:")
                for p in t.parameters:
                    rng = (
                        f" [{p.min}–{p.max} {p.unit}]"
                        if p.min is not None else ""
                    )
                    lines.append(f"    - {p.name}{rng}: {p.description}")
            if t.outputs:
                lines.append("  Measurable outputs:")
                for o in t.outputs:
                    lines.append(f"    - {o.name} ({o.unit}): {o.description}")
            if t.failure_modes:
                lines.append("  Known failure modes:")
                for fm in t.failure_modes:
                    lines.append(
                        f"    - {fm.name} (p≈{fm.probability:.0%}): {fm.description}"
                    )
            if t.time_cost_min > 0:
                lines.append(
                    f"  Time cost: {t.time_cost_min} virtual minutes per call"
                )
            lines.append("")
        return "\n".join(lines)

    def to_dict_list(self) -> List[dict]:
        return [t.model_dump() for t in self.list_all()]


# ── Singleton ─────────────────────────────────────────────────────────────────

INSTRUMENT_REGISTRY = InstrumentRegistry()

# Backward compat alias — existing imports of TOOL_REGISTRY still work
TOOL_REGISTRY = INSTRUMENT_REGISTRY


# ── Default instruments ───────────────────────────────────────────────────────

def register_default_tools() -> None:
    """
    Register the built-in virtual instruments for the battery SDL demo.
    Called once at startup from main.py.

    These are expressed as domain-agnostic specs — the LLM reads the
    descriptions and infers what experiments are possible.
    """
    INSTRUMENT_REGISTRY.register(VirtualInstrument(
        name="SamplerAgent",
        kind="instrument",
        description=(
            "Prepares physical samples by controlling material composition. "
            "Sample preparation may fail at extreme parameter values. "
            "Returns a prepared sample that can be stored and tested later."
        ),
        parameters=[
            InstrumentParameter(
                name="active_material",
                type="continuous",
                min=88.0, max=98.0,
                unit="wt%",
                description="Weight fraction of active electrode material",
            ),
            InstrumentParameter(
                name="porosity",
                type="continuous",
                min=20.0, max=60.0,
                unit="%",
                description="Electrode porosity — affects ion transport",
            ),
        ],
        outputs=[],
        failure_modes=[
            InstrumentFailureMode(
                name="electrode_defect",
                description=(
                    "Sample preparation fails — electrode is unusable. "
                    "Probability increases at high active_material + low porosity."
                ),
                probability=0.06,
            ),
        ],
        time_cost_min=2.0,
    ))

    INSTRUMENT_REGISTRY.register(VirtualInstrument(
        name="TesterAgent",
        kind="instrument",
        description=(
            "Electrochemical discharge tester (virtual potentiostat). "
            "Measures specific energy of a prepared electrode sample "
            "under a specified discharge power condition. "
            "Can test any prepared sample — accepts a sample_id or "
            "direct parameter values."
        ),
        parameters=[
            InstrumentParameter(
                name="power_W",
                type="continuous",
                min=50.0, max=250.0,
                unit="W",
                description="Discharge power applied during electrochemical test",
            ),
        ],
        outputs=[
            InstrumentOutput(
                name="specific_energy",
                type="scalar",
                unit="Wh/kg",
                description="Gravimetric specific energy of the electrode",
            ),
        ],
        failure_modes=[
            InstrumentFailureMode(
                name="measurement_noise",
                description="Gaussian noise σ=0.5 Wh/kg added to measurement",
                probability=1.0,
            ),
        ],
        time_cost_min=5.0,
    ))

    INSTRUMENT_REGISTRY.register(VirtualInstrument(
        name="BayesianOptimiser",
        kind="optimiser",
        description=(
            "Gaussian Process Bayesian optimisation with Expected Improvement "
            "acquisition. Suggests the next experiment candidate given previous "
            "observations. Balances exploration and exploitation automatically."
        ),
        parameters=[
            InstrumentParameter(
                name="n_calls",
                type="discrete",
                min=1, max=100,
                unit="",
                description="Number of optimisation evaluations to run",
            ),
            InstrumentParameter(
                name="n_initial_points",
                type="discrete",
                min=1, max=20,
                unit="",
                description="Random initial points before GP fitting",
            ),
        ],
        outputs=[
            InstrumentOutput(
                name="next_candidate",
                type="vector",
                unit="",
                description="Suggested parameter values for next experiment",
            ),
            InstrumentOutput(
                name="best_observed",
                type="scalar",
                unit="",
                description="Best objective value observed so far",
            ),
        ],
        failure_modes=[],
        time_cost_min=0.0,
    ))

    INSTRUMENT_REGISTRY.register(VirtualInstrument(
        name="ExperimentDatabase",
        kind="data",
        description=(
            "Persistent SQLite store for all experimental results. "
            "Supports read-only SQL SELECT queries for analysis and reporting."
        ),
        parameters=[],
        outputs=[
            InstrumentOutput(
                name="query_result",
                type="vector",
                unit="",
                description="Rows matching the SQL query",
            ),
        ],
        failure_modes=[],
        time_cost_min=0.0,
    ))

    INSTRUMENT_REGISTRY.register(VirtualInstrument(
        name="Plotter",
        kind="analyser",
        description=(
            "Generates multi-panel matplotlib figures summarising optimisation "
            "results. Produces scatter plots per operating condition and an "
            "optimal parameter path plot."
        ),
        parameters=[],
        outputs=[
            InstrumentOutput(
                name="figure",
                type="image",
                unit="",
                description="PNG summary figure",
            ),
        ],
        failure_modes=[],
        time_cost_min=0.0,
    ))