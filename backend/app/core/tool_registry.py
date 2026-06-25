"""
Domain-agnostic tool registry — single source of truth for lab capabilities.

Every tool registered here is:
- Visible to the LLM (injected into system prompt)
- Queryable by the feasibility checker
- Readable by the Lab Builder UI
- Writable via the Lab Builder UI (Phase 2A.5)

Adding a new virtual instrument here immediately makes the agent
aware of it — no code changes needed anywhere else.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Tool component schemas ────────────────────────────────────────────────────

class ToolParameter(BaseModel):
    name:        str
    type:        str = "continuous"   # continuous | discrete | categorical
    min:         Optional[float] = None
    max:         Optional[float] = None
    unit:        str = ""
    description: str = ""
    required:    bool = True


class ToolOutput(BaseModel):
    name:        str
    type:        str = "scalar"       # scalar | vector | image | text
    unit:        str = ""
    description: str = ""


class ToolFailureMode(BaseModel):
    name:        str
    description: str
    probability: float = 0.0


class VirtualTool(BaseModel):
    tool_id:       str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:          str
    kind:          str                # instrument | optimiser | analyser | data | custom
    description:   str
    parameters:    List[ToolParameter]   = Field(default_factory=list)
    outputs:       List[ToolOutput]      = Field(default_factory=list)
    failure_modes: List[ToolFailureMode] = Field(default_factory=list)
    time_cost_min: float = 0.0
    enabled:       bool  = True
    metadata:      Dict[str, Any] = Field(default_factory=dict)


# ── Registry ──────────────────────────────────────────────────────────────────

class ToolRegistry:
    """
    In-memory registry of all virtual tools.
    Thread-safe for reads; writes should be from the main thread only.
    """

    def __init__(self):
        self._tools: Dict[str, VirtualTool] = {}

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def register(self, tool: VirtualTool) -> VirtualTool:
        self._tools[tool.tool_id] = tool
        return tool

    def get(self, tool_id: str) -> Optional[VirtualTool]:
        return self._tools.get(tool_id)

    def get_by_name(self, name: str) -> Optional[VirtualTool]:
        return next(
            (t for t in self._tools.values() if t.name == name), None
        )

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
        data = self._tools[tool_id].model_dump()
        data.update(updates)
        self._tools[tool_id] = VirtualTool(**data)
        return self._tools[tool_id]

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

    def check_feasibility(
        self,
        required_params:  List[str],
        required_outputs: List[str],
    ) -> dict:
        """
        Domain-agnostic feasibility check.
        Returns a structured dict consumed by the extraction pipeline
        and displayed in the Campaign page.
        """
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
        Render registry as structured text for injection into LLM system prompt.
        Called on every LLM invocation — always reflects current registry state.
        """
        tools = self.list_all()
        if not tools:
            return "No tools registered in the virtual lab."

        lines = ["Available virtual lab tools:\n"]
        for t in tools:
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
        """Serialise all tools for the API response."""
        return [t.model_dump() for t in self.list_all()]


# ── Singleton ─────────────────────────────────────────────────────────────────

TOOL_REGISTRY = ToolRegistry()


# ── Default tools ─────────────────────────────────────────────────────────────

def register_default_tools() -> None:
    """
    Register the built-in virtual tools for the battery SDL demo.
    Called once at startup from main.py.

    These are expressed as domain-agnostic specs — the LLM reads the
    descriptions and infers what experiments are possible.
    The surrogate function is a virtual potentiostat; the tool description
    is what the agent uses for reasoning, not the implementation.
    """
    TOOL_REGISTRY.register(VirtualTool(
        name="SamplerAgent",
        kind="instrument",
        description=(
            "Prepares physical samples by controlling material composition. "
            "Sample preparation may fail at extreme parameter values, "
            "particularly at high active material content combined with low porosity."
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
        outputs=[],
        failure_modes=[
            ToolFailureMode(
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

    TOOL_REGISTRY.register(VirtualTool(
        name="TesterAgent",
        kind="instrument",
        description=(
            "Electrochemical discharge tester (virtual potentiostat). "
            "Measures specific energy of a prepared electrode sample "
            "under a specified discharge power condition. "
            "Uses a validated surrogate model."
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
                description="Gaussian noise σ=0.5 Wh/kg added to measurement",
                probability=1.0,
            ),
        ],
        time_cost_min=5.0,
    ))

    TOOL_REGISTRY.register(VirtualTool(
        name="BayesianOptimiser",
        kind="optimiser",
        description=(
            "Gaussian Process Bayesian optimisation with Expected Improvement "
            "acquisition. Suggests the next experiment candidate given previous "
            "observations. Balances exploration and exploitation automatically."
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
                description="Random initial points before GP fitting",
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
        time_cost_min=0.0,
    ))

    TOOL_REGISTRY.register(VirtualTool(
        name="ExperimentDatabase",
        kind="data",
        description=(
            "Persistent SQLite store for all experimental results. "
            "Supports read-only SQL SELECT queries for analysis and reporting."
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
            "Generates multi-panel matplotlib figures summarising optimisation "
            "results. Produces scatter plots per operating condition and an "
            "optimal parameter path plot."
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