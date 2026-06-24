"""
Pydantic data models — the single source of truth for all data shapes.

Why Pydantic?
- Automatic validation: if a field is wrong type, you get a clear error
- Serialisation: .model_dump() gives you a plain dict for JSON responses
- IDE support: full autocomplete on all fields
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Agent internals ───────────────────────────────────────────────────────────

class AgentStateModel(BaseModel):
    """Everything the LLM agent needs to maintain context."""
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
    """Which lab equipment is currently active (drives digital twin animation)."""
    llm:       bool = False
    optimiser: bool = False
    sampler:   bool = False
    tester:    bool = False
    memory:    bool = False
    knowledge: bool = False
    reporting: bool = False


# ── Campaign ──────────────────────────────────────────────────────────────────

class CampaignSpec(BaseModel):
    """A fully-specified experimental campaign extracted from a paper or designed by the agent."""
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


# ── Documents ─────────────────────────────────────────────────────────────────

class DocumentModel(BaseModel):
    """A PDF paper that has been uploaded and parsed."""
    document_id: str
    filename:    str
    title:       Optional[str] = None
    raw_text:    str = ""
    pages:       List[str] = Field(default_factory=list)
    uploaded_at: Optional[str] = None
    summary:     Optional[str] = None


class CaseStudyExtraction(BaseModel):
    document_id:      str
    case_name:        str
    campaign:         CampaignSpec
    evidence_snippets: List[str] = Field(default_factory=list)


# ── Events ────────────────────────────────────────────────────────────────────

class ExecutionEvent(BaseModel):
    """
    A single live event emitted during workflow execution.
    These are pushed to the frontend via WebSocket.
    
    equipment: which node to highlight in the digital twin
    category:  controls colour in the activity feed
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
    """
    The complete state of one user session.
    
    Everything the frontend needs is derived from this object via
    session_state_payload() in orchestrator.py.
    """
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

    # UI state
    equipment_status: EquipmentStatusModel = Field(default_factory=EquipmentStatusModel)
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