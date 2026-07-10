from __future__ import annotations

import uuid
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


def append_assistant_message(messages: list, content: str, tool_calls: list | None = None) -> dict:
    entry: dict = {"role": "assistant", "content": content or ""}
    if tool_calls:
        entry["tool_calls"] = tool_calls
    messages.append(entry)
    return entry


def append_tool_response(messages: list, tool_call_id: str, name: str, content: str) -> bool:
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            ids = {tc.get("id") for tc in msg["tool_calls"]}
            if tool_call_id in ids:
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call_id,
                    "name":         name,
                    "content":      content,
                })
                return True
        if msg.get("role") == "tool":
            continue
    return False


def get_unanswered_tool_calls(messages: list) -> list[dict]:
    responded: set[str] = {
        msg["tool_call_id"]
        for msg in messages
        if msg.get("role") == "tool" and msg.get("tool_call_id")
    }
    unanswered = []
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls", []):
                if tc.get("id") and tc["id"] not in responded:
                    unanswered.append(tc)
    return unanswered


# ── Document structure ────────────────────────────────────────────────────────

class FigureModel(BaseModel):
    figure_id:  str
    page_idx:   int = 0
    caption:    str = ""
    path:       str = ""
    section:    str = ""
    served_url: str = ""


class TableModel(BaseModel):
    table_id: str
    page_idx: int = 0
    caption:  str = ""
    html:     str = ""
    section:  str = ""


class SectionModel(BaseModel):
    heading:    str
    level:      int = 2
    content:    str = ""
    figure_ids: List[str] = Field(default_factory=list)
    table_ids:  List[str] = Field(default_factory=list)


class DocumentModel(BaseModel):
    document_id: str
    filename:    str
    title:       Optional[str] = None
    raw_text:    str = ""
    pages:       List[str] = Field(default_factory=list)
    uploaded_at: Optional[str] = None
    summary:     Optional[str] = None
    sections:    List[SectionModel] = Field(default_factory=list)
    figures:     List[FigureModel]  = Field(default_factory=list)
    tables:      List[TableModel]   = Field(default_factory=list)
    authors:     List[str]          = Field(default_factory=list)
    year:        Optional[int]      = None
    doi:         Optional[str]      = None
    journal:     Optional[str]      = None


# ── Document Library ──────────────────────────────────────────────────────────

DocumentType = Literal["paper", "manual"]


class DocumentLibraryEntry(BaseModel):
    document_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename:    str
    title:       Optional[str] = None
    summary:     Optional[str] = None
    uploaded_at: str = ""
    file_path:   str = ""
    doc_type:    DocumentType = "paper"


# ── Optimisation Library ──────────────────────────────────────────────────────

class OptimisationLibraryEntry(BaseModel):
    lib_id:       str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:         str
    description:  str
    capabilities: List[str] = Field(default_factory=list)
    install_cmd:  str = ""
    docs_url:     str = ""
    enabled:      bool = True
    is_default:   bool = False


# ── Resource Inventory ────────────────────────────────────────────────────────

class ResourceConsumptionRule(BaseModel):
    instrument_name: str
    amount_per_use:  float
    description:     str = ""


class LabResource(BaseModel):
    resource_id:       str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:              str
    unit:              str
    current_stock:     float = 0.0
    min_stock:         float = 0.0
    description:       str = ""
    consumption_rules: List[ResourceConsumptionRule] = Field(default_factory=list)


# ── Protocols ─────────────────────────────────────────────────────────────────

class ProtocolEntry(BaseModel):
    protocol_id:       str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:              str
    description:       str = ""
    created_at:        str = ""
    optimiser_used:    str = ""
    results_summary:   str = ""
    user_instructions: List[str] = Field(default_factory=list)
    notes:             str = ""
    workflow_plan:     Optional[Dict[str, Any]] = None


# ── Lab Settings ──────────────────────────────────────────────────────────────

class LabSettings(BaseModel):
    lab_name:                str = "My Lab"
    lab_description:         str = ""
    system_prompt_extension: str = ""
    document_library:        List[DocumentLibraryEntry]     = Field(default_factory=list)
    optimisation_library:    List[OptimisationLibraryEntry] = Field(default_factory=list)
    resource_inventory:      List[LabResource]              = Field(default_factory=list)
    protocols:               List[ProtocolEntry]            = Field(default_factory=list)


# ── Optimiser Config ──────────────────────────────────────────────────────────

class OptimiserConfig(BaseModel):
    name:             str = "gp_bo"
    n_calls:          int = 20
    n_initial_points: int = 6


# ── Projected Schedule ────────────────────────────────────────────────────────

class ProjectedScheduleEntry(BaseModel):
    instrument_id:   str
    instrument_name: str = ""
    start_time:      str = ""
    end_time:        str = ""
    step_id:         str
    label:           str
    is_projected:    bool = True


# ── Sample Registry ───────────────────────────────────────────────────────────

class SampleResult(BaseModel):
    result_id:  str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    tested_by:  str
    conditions: Dict[str, float]
    outputs:    Dict[str, float]
    tested_at:  str
    notes:      str = ""


class Sample(BaseModel):
    sample_id:      str
    params:         Dict[str, float]
    prepared_by:    str
    status:         str = "prepared"
    prepared_at:    str = ""
    failure_reason: Optional[str] = None
    notes:          str = ""
    results:        List[SampleResult] = Field(default_factory=list)
    tags:           List[str] = Field(default_factory=list)


def generate_sample_id(session: "SessionModel") -> str:
    return f"S-{len(session.sample_registry) + 1:03d}"


# ── Workflow Plan ─────────────────────────────────────────────────────────────

WorkflowSource = Literal["agent", "paper", "user"]


class WorkflowStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    step_id:              str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    kind:                 str
    label:                str
    instrument:           Optional[str] = None
    instrument_id:        Optional[str] = None
    dependencies:         List[str] = Field(default_factory=list)
    status:               str = "pending"
    start_time:           Optional[str] = None
    end_time:             Optional[str] = None
    projected_start_time: Optional[str] = None
    projected_end_time:   Optional[str] = None
    params:               Dict[str, float] = Field(default_factory=dict)
    produces:             Optional[str] = None
    sample_ref:           Optional[str] = None
    conditions:           Dict[str, float] = Field(default_factory=dict)
    measures:             Optional[str] = None
    condition_label:      Optional[str] = None
    condition_value:      Optional[float] = None
    condition_unit:       str = ""
    free_params:          List[dict] = Field(default_factory=list)
    objective_metric:     Optional[str] = None
    optimiser_name:       Optional[str] = None
    n_calls:              int = 20
    n_initial_points:     int = 6
    plot_code:            Optional[str] = None
    analysis_code:        Optional[str] = None
    sql:                  Optional[str] = None
    description:          Optional[str] = None
    editable_fields:      List[str] = Field(default_factory=list)


class WorkflowPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    plan_id:    str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    summary:    str
    steps:      List[WorkflowStep]
    source:     WorkflowSource = "agent"
    created_at: str = ""


# ── Agent internals ───────────────────────────────────────────────────────────

class AgentStateModel(BaseModel):
    messages:              List[dict] = Field(default_factory=list)
    results_store:         List[dict] = Field(default_factory=list)
    last_llm_message:      Optional[dict] = None
    last_tool_result:      Optional[Any] = None
    last_tools_used:       List[str] = Field(default_factory=list)
    awaiting_confirmation: bool = False
    pending_tool_calls:    List[dict] = Field(default_factory=list)


# ── Equipment ─────────────────────────────────────────────────────────────────

class EquipmentStatusModel(BaseModel):
    llm:           bool = False
    optimiser:     bool = False
    synthesiser:   bool = False
    characteriser: bool = False
    memory:        bool = False
    knowledge:     bool = False
    reporting:     bool = False


# ── Results ───────────────────────────────────────────────────────────────────

def make_result_entry(
    condition_label: str,
    condition_value: float,
    optimiser_name:  str = "",
) -> dict:
    return {
        "condition_label":    condition_label,
        "condition_value":    condition_value,
        "optimiser_name":     optimiser_name,
        "param_names":        [],
        "X":                  [],
        "y":                  [],
        "best_params":        {},
        "best_objective":     None,
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
    session_id:             str
    agent_state:            AgentStateModel
    outstanding_tasks:      List[dict] = Field(default_factory=list)
    show_plotter_image:     Optional[str] = None
    artifacts:              List[ArtifactModel] = Field(default_factory=list)
    active_document_id:     Optional[str] = None
    extracted_campaign:     Optional[CampaignSpec] = None
    active_condition_key:   str = ""
    sample_registry:        List[Sample] = Field(default_factory=list)
    pending_plan:           Optional[WorkflowPlan] = None
    optimiser_config:       OptimiserConfig = Field(default_factory=OptimiserConfig)
    equipment_status:       EquipmentStatusModel = Field(default_factory=EquipmentStatusModel)
    current_activity:       Optional[str] = None
    activity_log:           List[str] = Field(default_factory=list)
    current_mission:        Optional[str] = None
    background_job_active:  bool = False
    background_job_label:   Optional[str] = None
    background_job_error:   Optional[str] = None
    background_job_plan:    List[dict] = Field(default_factory=list)
    background_job_index:   int = 0
    background_job_status:  str = "idle"
    step_statuses:          Dict[str, str] = Field(default_factory=dict)
    bo_iteration_counts:    Dict[str, int] = Field(default_factory=dict)
    projected_schedule:     List[ProjectedScheduleEntry] = Field(default_factory=list)
    live_event_queue:       List[ExecutionEvent] = Field(default_factory=list)
    resource_log:           List[dict] = Field(default_factory=list)


# ── API shapes ────────────────────────────────────────────────────────────────

class CreateSessionResponse(BaseModel):
    session_id: str


class UserMessageRequest(BaseModel):
    session_id: str
    text:       str


class ConfirmRequest(BaseModel):
    session_id: str
    proceed:    bool


class ResetRequest(BaseModel):
    session_id: str


class StateResponse(BaseModel):
    session_id: str
    state:      Dict[str, Any]


class ExecutePlanRequest(BaseModel):
    session_id: str
    plan:       Dict[str, Any]


class UpdateOptimiserRequest(BaseModel):
    session_id:       str
    name:             str
    n_calls:          int = 20
    n_initial_points: int = 6