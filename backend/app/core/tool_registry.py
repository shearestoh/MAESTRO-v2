"""
Domain-agnostic tool registry.

This is the single source of truth for what the virtual lab can do.
Tools are registered here — either at startup (built-in virtual tools)
or dynamically via the API (user-defined tools).

The LLM system prompt is generated FROM this registry.
The feasibility checker queries this registry.
The digital twin reads this registry.
The Lab Builder writes to this registry.

A 'tool' in this context is any callable capability:
  - A virtual instrument (SamplerAgent, TesterAgent)
  - A computational method (BayesianOptimiser, GridSearch)
  - A data operation (DatabaseQuery, Plotter)
  - Future: a real instrument driver
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Tool parameter / output schemas ──────────────────────────────────────────

class ToolParameter(BaseModel):
    """One controllable input parameter of a tool."""
    name:        str
    type:        str = "continuous"   # continuous | discrete | categorical
    min:         Optional[float] = None
    max:         Optional[float] = None
    unit:        str = ""
    description: str = ""
    required:    bool = True


class ToolOutput(BaseModel):
    """One measurable output of a tool."""
    name:        str
    type:        str = "scalar"       # scalar | vector | image | text
    unit:        str = ""
    description: str = ""


class ToolFailureMode(BaseModel):
    """A known failure mode of a tool."""
    name:        str
    description: str
    probability: float = 0.0          # baseline probability


class VirtualTool(BaseModel):
    """
    A registered virtual tool in the lab.

    This is intentionally domain-agnostic — it describes WHAT the tool
    can do, not HOW it does it internally.
    """
    tool_id:      str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:         str
    kind:         str                 # instrument | optimiser | analyser | data | custom
    description:  str
    parameters:   List[ToolParameter]  = Field(default_factory=list)
    outputs:      List[ToolOutput]     = Field(default_factory=list)
    failure_modes:List[ToolFailureMode]= Field(default_factory=list)
    time_cost_min:float = 0.0          # virtual minutes per call
    enabled:      bool  = True
    metadata:     Dict[str, Any] = Field(default_factory=dict)


# ── Registry ──────────────────────────────────────────────────────────────────

class ToolRegistry:
    """
    In-memory registry of all virtual tools available in this session.

    Designed to be:
    - Queried by the LLM to understand lab capabilities
    - Written to by the Lab Builder UI
    - Read by the feasibility checker
    - Read by the digital twin for node rendering
    """

    def __init__(self):
        self._tools: Dict[str, VirtualTool] = {}

    def register(self, tool: VirtualTool) -> VirtualTool:
        self._tools[tool.tool_id] = tool
        return tool

    def get(self, tool_id: str) -> Optional[VirtualTool]:
        return self._tools.get(tool_id)

    def get_by_name(self, name: str) -> Optional[VirtualTool]:
        return next((t for t in self._tools.values() if t.name == name), None)

    def list_all(self) -> List[VirtualTool]:
        return [t for t in self._tools.values() if t.enabled]

    def remove(self, tool_id: str) -> bool:
        if tool_id in self._tools:
            del self._tools[tool_id]
            return True
        return False

    def update(self, tool_id: str, updates: Dict[str, Any]) -> Optional[VirtualTool]:
        if tool_id not in self._tools:
            return None
        tool_data = self._tools[tool_id].model_dump()
        tool_data.update(updates)
        self._tools[tool_id] = VirtualTool(**tool_data)
        return self._tools[tool_id]

    def all_controllable_parameters(self) -> List[str]:
        """All parameter names across all tools — for feasibility checking."""
        params = set()
        for tool in self.list_all():
            for p in tool.parameters:
                params.add(p.name)
        return sorted(params)

    def all_measurable_outputs(self) -> List[str]:
        """All output names across all tools — for feasibility checking."""
        outputs = set()
        for tool in self.list_all():
            for o in tool.outputs:
                outputs.add(o.name)
        return sorted(outputs)

    def check_feasibility(self, required_params: List[str], required_outputs: List[str]) -> dict:
        """
        Check if the current tool set can execute an experiment
        requiring the given parameters and outputs.
        Domain-agnostic — works for any scientific domain.
        """
        controllable = set(self.all_controllable_parameters())
        measurable   = set(self.all_measurable_outputs())

        missing_params  = [p for p in required_params  if p not in controllable]
        missing_outputs = [o for o in required_outputs if o not in measurable]

        return {
            "feasible":         len(missing_params) == 0 and len(missing_outputs) == 0,
            "missing_params":   missing_params,
            "missing_outputs":  missing_outputs,
            "available_params": sorted(controllable),
            "available_outputs":sorted(measurable),
        }

    def to_llm_context(self) -> str:
        """
        Render the registry as a structured string for injection
        into the LLM system prompt. Domain-agnostic.
        """
        if not self._tools:
            return "No tools registered."

        lines = ["Available virtual lab tools:\n"]
        for tool in self.list_all():
            lines.append(f"### {tool.name} ({tool.kind})")
            lines.append(f"  {tool.description}")
            if tool.parameters:
                lines.append("  Controllable parameters:")
                for p in tool.parameters:
                    rng = f" [{p.min}–{p.max} {p.unit}]" if p.min is not None else ""
                    lines.append(f"    - {p.name}{rng}: {p.description}")
            if tool.outputs:
                lines.append("  Measurable outputs:")
                for o in tool.outputs:
                    lines.append(f"    - {o.name} ({o.unit}): {o.description}")
            if tool.failure_modes:
                lines.append("  Known failure modes:")
                for f in tool.failure_modes:
                    lines.append(f"    - {f.name} (p={f.probability:.0%}): {f.description}")
            if tool.time_cost_min > 0:
                lines.append(f"  Time cost: {tool.time_cost_min} virtual minutes per call")
            lines.append("")

        return "\n".join(lines)


# ── Global registry instance ──────────────────────────────────────────────────
# One registry per process. Sessions share it (tools are lab-level, not session-level).
# In a multi-user deployment this would be per-lab, stored in a database.

TOOL_REGISTRY = ToolRegistry()


# ── Built-in virtual tools ────────────────────────────────────────────────────
# These are the default tools for the battery virtual lab.
# They can be removed or supplemented via the Lab Builder.

def register_default_tools():
    """
    Register the built-in virtual tools.
    Called once at startup from main.py.

    These are expressed as domain-agnostic tool specs —
    the LLM reads these descriptions and infers what experiments
    are possible, without any hardcoded domain knowledge in the prompts.
    """
    TOOL_REGISTRY.register(VirtualTool(
        name="SamplerAgent",
        kind="instrument",
        description=(
            "Prepares physical samples by controlling material composition parameters. "
            "Sample preparation may fail at extreme parameter values."
        ),
        parameters=[
            ToolParameter(
                name="active_material",
                type="continuous",
                min=88.0, max=98.0,
                unit="wt%",
                description="Weight fraction of active electrode material",
            ),
            ToolParameter(
                name="porosity",
                type="continuous",
                min=20.0, max=60.0,
                unit="%",
                description="Electrode porosity — affects ion transport",
            ),
        ],
        outputs=[],  # Sampler produces a physical sample, not a measurement
        failure_modes=[
            ToolFailureMode(
                name="electrode_defect",
                description="Sample preparation fails — electrode is unusable. "
                            "Probability increases at high active_material + low porosity.",
                probability=0.06,
            ),
        ],
        time_cost_min=2.0,
    ))

    TOOL_REGISTRY.register(VirtualTool(
        name="TesterAgent",
        kind="instrument",
        description=(
            "Electrochemical discharge tester. Measures specific energy of a prepared "
            "electrode sample under a specified discharge power condition. "
            "Uses a validated surrogate model of a potentiostat."
        ),
        parameters=[
            ToolParameter(
                name="power_W",
                type="continuous",
                min=50.0, max=250.0,
                unit="W",
                description="Discharge power applied during electrochemical test",
            ),
        ],
        outputs=[
            ToolOutput(
                name="specific_energy",
                type="scalar",
                unit="Wh/kg",
                description="Gravimetric specific energy of the electrode",
            ),
        ],
        failure_modes=[
            ToolFailureMode(
                name="measurement_noise",
                description="Gaussian noise added to measurement (σ=0.5 Wh/kg)",
                probability=1.0,
            ),
        ],
        time_cost_min=5.0,
    ))

    TOOL_REGISTRY.register(VirtualTool(
        name="BayesianOptimiser",
        kind="optimiser",
        description=(
            "Gaussian Process Bayesian optimisation with Expected Improvement acquisition. "
            "Suggests the next experiment candidate given previous observations. "
            "Balances exploration and exploitation."
        ),
        parameters=[
            ToolParameter(
                name="n_calls",
                type="discrete",
                min=1, max=100,
                unit="",
                description="Number of optimisation evaluations to run",
            ),
            ToolParameter(
                name="n_initial_points",
                type="discrete",
                min=1, max=20,
                unit="",
                description="Number of random initial points before GP fitting",
            ),
        ],
        outputs=[
            ToolOutput(
                name="next_candidate",
                type="vector",
                unit="",
                description="Suggested parameter values for next experiment",
            ),
            ToolOutput(
                name="best_observed",
                type="scalar",
                unit="",
                description="Best objective value observed so far",
            ),
        ],
        failure_modes=[],
        time_cost_min=0.0,  # Computational — no virtual time cost
    ))

    TOOL_REGISTRY.register(VirtualTool(
        name="ExperimentDatabase",
        kind="data",
        description=(
            "Persistent SQLite store for all experimental results. "
            "Supports read-only SQL SELECT queries for analysis."
        ),
        parameters=[],
        outputs=[
            ToolOutput(
                name="query_result",
                type="vector",
                unit="",
                description="Rows matching the SQL query",
            ),
        ],
        failure_modes=[],
        time_cost_min=0.0,
    ))

    TOOL_REGISTRY.register(VirtualTool(
        name="Plotter",
        kind="analyser",
        description=(
            "Generates multi-panel matplotlib figures summarising optimisation results. "
            "Produces scatter plots per condition and an optimal parameter path plot."
        ),
        parameters=[],
        outputs=[
            ToolOutput(
                name="figure",
                type="image",
                unit="",
                description="PNG summary figure",
            ),
        ],
        failure_modes=[],
        time_cost_min=0.0,
    ))