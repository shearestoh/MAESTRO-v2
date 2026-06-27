"""
Pydantic data models — single source of truth for all data shapes.

Phase 2 additions: FigureModel, TableModel, SectionModel on DocumentModel.
Phase 3 additions: ResultEntry generalised for domain-agnostic campaigns.
  - condition_label / condition_value replace power_W as primary keys
  - power_W kept for backward compatibility with existing sessions
  - best_objective added alongside best_energy
  - SessionModel.active_condition_key tracks which condition dimension
    is being varied in the current campaign
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Document structure (MinerU-enriched) ─────────────────────────────────────

class FigureModel(BaseModel):
    """An extracted figure from a paper."""
    figure_id:  str
    page_idx:   int = 0
    caption:    str = ""
    path:       str = ""
    section:    str = ""
    served_url: str = ""


class TableModel(BaseModel):
    """An extracted table from a paper."""
    table_id:  str
    page_idx:  int = 0
    caption:   str = ""
    html:      str = ""
    section:   str = ""


class SectionModel(BaseModel):
    """A structured section from a paper (MinerU heading hierarchy)."""
    heading:    str
    level:      int = 2
    content:    str = ""
    figure_ids: List[str] = Field(default_factory=list)
    table_ids:  List[str] = Field(default_factory=list)


class DocumentModel(BaseModel):
    """A PDF paper that has been uploaded and parsed."""
    document_id:  str
    filename:     str
    title:        Optional[str] = None
    raw_text:     str = ""
    pages:        List[str] = Field(default_factory=list)
    uploaded_at:  Optional[str] = None
    summary:      Optional[str] = None
    sections:     List[SectionModel]  = Field(default_factory=list)
    figures:      List[FigureModel]   = Field(default_factory=list)
    tables:       List[TableModel]    = Field(default_factory=list)
    mineru_used:  bool = False


# ── Agent internals ───────────────────────────────────────────────────────────

class AgentStateModel(BaseModel):
    messages:              List[dict]  = Field(default_factory=list)
    results_store:         List[dict]  = Field(default_factory=list)
    last_llm_message:      Optional[dict] = None
    last_tool_result:      Optional[Any]  = None
    last_active_node:      Optional[str]  = None
    last_tools_used:       List[str]  = Field(default_factory=list)
    awaiting_confirmation: bool = False
    pending_tool_calls:    List[dict] = Field(default_factory=list)


# ── Equipment ─────────────────────────────────────────────────────────────────

class EquipmentStatusModel(BaseModel):
    """Which lab equipment is currently active — drives digital twin."""
    llm:       bool = False
    optimiser: bool = False
    sampler:   bool = False
    tester:    bool = False
    memory:    bool = False
    knowledge: bool = False
    reporting: bool = False


# ── Results ───────────────────────────────────────────────────────────────────

class ResultEntry(BaseModel):
    """
    One result entry per operating condition value.

    Phase 3: generalised to support any domain.

    condition_label: human-readable condition name
                     e.g. "power_W", "temperature_C", "ph"
    condition_value: the fixed value for this run
                     e.g. 150.0, 300.0, 7.0

    power_W is kept for backward compatibility — it mirrors
    condition_value when condition_label == "power_W".

    best_objective is the general field; best_energy mirrors it
    for backward compatibility.
    """
    # ── General condition fields (Phase 3) ────────────────────────────────────
    condition_label: str   = "power_W"   # which condition dimension
    condition_value: float = 0.0         # the fixed value for this run

    # ── Backward-compatible field ─────────────────────────────────────────────
    power_W: float = 0.0                 # mirrors condition_value

    # ── BO results ────────────────────────────────────────────────────────────
    X:  List[List[float]] = Field(default_factory=list)  # parameter vectors
    y:  List[float]       = Field(default_factory=list)  # objective values

    # ── Best observed ─────────────────────────────────────────────────────────
    best_params:     Dict[str, float] = Field(default_factory=dict)
    best_objective:  Optional[float]  = None   # general field (Phase 3)
    best_energy:     Optional[float]  = None   # backward compat alias

    # ── Legacy per-param best fields (battery-specific, kept for compat) ──────
    best_am:         Optional[float]  = None
    best_por:        Optional[float]  = None

    # ── Diagnostics ───────────────────────────────────────────────────────────
    failed_samples:     int = 0
    attempts:           int = 0
    termination_reason: Optional[str] = None

    # ── Param names used in this run (for display) ────────────────────────────
    param_names: List[str] = Field(default_factory=list)

    def sync_compat_fields(self) -> "ResultEntry":
        """
        Keep backward-compatible fields in sync with general fields.
        Call after updating condition_value or best_objective.
        """
        # power_W mirrors condition_value
        self.power_W = self.condition_value

        # best_energy mirrors best_objective
        if self.best_objective is not None:
            self.best_energy = self.best_objective
        elif self.best_energy is not None:
            self.best_objective = self.best_energy

        # best_am / best_por: mirror from best_params if available
        if "active_material" in self.best_params:
            self.best_am = self.best_params["active_material"]
        if "porosity" in self.best_params:
            self.best_por = self.best_params["porosity"]

        return self


def make_result_entry(
    condition_label: str,
    condition_value: float,
) -> dict:
    """
    Factory: create a new result entry dict for the results_store.

    Using a plain dict (not ResultEntry instance) to match the existing
    results_store pattern — avoids breaking the many places that do
    r["X"], r["y"], r["best_energy"] etc.
    """
    return {
        # General fields (Phase 3)
        "condition_label": condition_label,
        "condition_value": condition_value,
        "param_names":     [],

        # Backward compat
        "power_W":         condition_value,

        # BO results
        "X":               [],
        "y":               [],

        # Best observed
        "best_params":     {},
        "best_objective":  None,
        "best_energy":     None,   # backward compat

        # Legacy battery-specific best fields
        "best_am":         None,
        "best_por":        None,

        # Diagnostics
        "failed_samples":     0,
        "attempts":           0,
        "termination_reason": None,
    }


# ── Campaign ──────────────────────────────────────────────────────────────────

class CampaignSpec(BaseModel):
    campaign_id:          str
    title:                str
    source_document_id:   str
    target_case_study:    str
    objective_metric:     str
    parameter_space:      List[dict] = Field(default_factory=list)
    operating_conditions: List[dict] = Field(default_factory=list)
    desired_outputs:      List[str]  = Field(default_factory=list)
    assumptions:          List[str]  = Field(default_factory=list)
    provenance:           Dict[str, Any] = Field(default_factory=dict)
    capability_match:     Dict[str, Any] = Field(default_factory=dict)
    status:               str = "draft"


class CaseStudyExtraction(BaseModel):
    document_id:       str
    case_name:         str
    campaign:          CampaignSpec
    evidence_snippets: List[str] = Field(default_factory=list)


# ── Events ────────────────────────────────────────────────────────────────────

class ExecutionEvent(BaseModel):
    """
    A single live event emitted during workflow execution.
    Pushed to the frontend via WebSocket.
    """
    event_type: str
    message:    str
    equipment:  Optional[str] = None
    category:   str = "execution"
    payload:    Dict[str, Any] = Field(default_factory=dict)


# ── Artifacts ─────────────────────────────────────────────────────────────────

class ArtifactModel(BaseModel):
    name: str
    kind: str
    path: str


# ── Session ───────────────────────────────────────────────────────────────────

class SessionModel(BaseModel):
    """Complete state of one user session."""
    session_id:    str
    agent_state:   AgentStateModel

    # Virtual lab clock
    virtual_clock_minutes: int = 0
    virtual_day_index:     int = 1

    # Task tracking
    outstanding_tasks: List[dict] = Field(default_factory=list)

    # Outputs
    show_plotter_image: Optional[str] = None
    artifacts:          List[ArtifactModel] = Field(default_factory=list)

    # Document / campaign
    active_document_id: Optional[str] = None
    extracted_campaign: Optional[CampaignSpec] = None

    # Phase 3: which condition dimension is active in current campaign
    # e.g. "power_W", "temperature_C", "ph"
    # Derived from extracted_campaign.operating_conditions[0].name
    active_condition_key: str = "power_W"

    # UI state
    equipment_status: EquipmentStatusModel = Field(
        default_factory=EquipmentStatusModel
    )
    current_activity: Optional[str] = None
    activity_log:     List[str] = Field(default_factory=list)
    current_mission:  Optional[str] = None

    # Background job
    background_job_active:      bool = False
    background_job_label:       Optional[str] = None
    background_job_error:       Optional[str] = None
    background_job_plan:        List[dict] = Field(default_factory=list)
    background_job_index:       int = 0
    background_job_status:      str = "idle"
    background_job_id:          Optional[str] = None

    # Live event queue (drained by WebSocket endpoint)
    live_event_queue: List[ExecutionEvent] = Field(default_factory=list)

    # Phase 2C: resource schedule log for Gantt display
    resource_log: List[dict] = Field(default_factory=list)


# ── API request/response shapes ───────────────────────────────────────────────

class CreateSessionResponse(BaseModel):
    session_id: str

class UserMessageRequest(BaseModel):
    session_id: str
    text:       str

class ConfirmRequest(BaseModel):
    session_id: str
    proceed:    bool

class NextDayRequest(BaseModel):
    session_id: str

class ResetRequest(BaseModel):
    session_id: str

class StateResponse(BaseModel):
    session_id: str
    state:      Dict[str, Any]