"""
Pydantic data models — single source of truth for all data shapes.

Phase 2 additions: FigureModel, TableModel, SectionModel on DocumentModel.
Phase 3 additions:
  - SampleResult, Sample: domain-agnostic sample registry
  - WorkflowStep, WorkflowPlan: structured plan for human-in-the-loop
  - ResultEntry generalised for domain-agnostic campaigns
  - SessionModel gains sample_registry + pending_plan
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import uuid


# ── Document structure (MinerU-enriched) ─────────────────────────────────────

class FigureModel(BaseModel):
    figure_id:  str
    page_idx:   int = 0
    caption:    str = ""
    path:       str = ""
    section:    str = ""
    served_url: str = ""


class TableModel(BaseModel):
    table_id:  str
    page_idx:  int = 0
    caption:   str = ""
    html:      str = ""
    section:   str = ""


class SectionModel(BaseModel):
    heading:    str
    level:      int = 2
    content:    str = ""
    figure_ids: List[str] = Field(default_factory=list)
    table_ids:  List[str] = Field(default_factory=list)


class DocumentModel(BaseModel):
    document_id:  str
    filename:     str
    title:        Optional[str] = None
    raw_text:     str = ""
    pages:        List[str] = Field(default_factory=list)
    uploaded_at:  Optional[str] = None
    summary:      Optional[str] = None
    sections:     List[SectionModel] = Field(default_factory=list)
    figures:      List[FigureModel]  = Field(default_factory=list)
    tables:       List[TableModel]   = Field(default_factory=list)
    mineru_used:  bool = False


# ── Sample Registry ───────────────────────────────────────────────────────────

class SampleResult(BaseModel):
    """
    A single test result on a sample.

    Domain-agnostic: conditions and outputs are arbitrary dicts.
    Works for any instrument combination:
      - Battery: conditions={"power_W": 100}, outputs={"specific_energy": 87.3}
      - Catalysis: conditions={"temperature_C": 300}, outputs={"CO2_conversion": 0.82}
      - Drug: conditions={"ph": 7}, outputs={"dissolution_rate": 0.45}
    """
    result_id:  str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    tested_by:  str                      # instrument name e.g. "TesterAgent"
    conditions: Dict[str, float]         # fixed conditions during test
    outputs:    Dict[str, float]         # measured outputs
    tested_at:  str                      # virtual timestamp e.g. "09:14"
    tested_day: int = 1
    notes:      str = ""


class Sample(BaseModel):
    """
    A domain-agnostic physical or virtual sample.

    Not specific to batteries — could be:
    - A battery electrode  (active_material, porosity)
    - A catalyst pellet    (loading, particle_size)
    - A polymer film       (thickness, composition)
    - A drug formulation   (excipient_ratio, particle_size)
    - A solar cell layer   (thickness, dopant_pct)

    The 'params' dict holds whatever parameters were used
    to prepare it — no hardcoded field names.

    The 'prepared_by' field references the instrument by name,
    so any instrument can prepare samples in future.
    """
    sample_id:      str                       # e.g. "S-1-001"
    params:         Dict[str, float]          # preparation parameters
    prepared_by:    str                       # instrument name
    status:         str = "prepared"          # prepared | tested | failed | stored
    prepared_at:    str = ""                  # virtual timestamp
    prepared_day:   int = 1
    failure_reason: Optional[str] = None
    notes:          str = ""
    results:        List[SampleResult] = Field(default_factory=list)
    tags:           List[str] = Field(default_factory=list)

    def best_output(self, output_name: str) -> Optional[float]:
        """Return the best value of a given output across all test results."""
        values = [
            r.outputs[output_name]
            for r in self.results
            if output_name in r.outputs
        ]
        return max(values) if values else None

    def latest_result(self) -> Optional[SampleResult]:
        """Return the most recent test result."""
        return self.results[-1] if self.results else None


def generate_sample_id(session: "SessionModel") -> str:
    """
    Generate a sequential, human-readable sample ID.
    Format: S-{day}-{count:03d}
    e.g. S-1-001, S-1-002, S-2-001

    Domain-agnostic — works for any sample type.
    In future could be prefixed by instrument type:
    e.g. E-1-001 (electrode), C-1-001 (catalyst)
    """
    day   = session.virtual_day_index
    count = len(session.sample_registry) + 1
    return f"S-{day}-{count:03d}"


# ── Workflow Plan (Human-in-the-loop) ─────────────────────────────────────────

class WorkflowStep(BaseModel):
    """
    A single step in a proposed workflow plan.

    Domain-agnostic: kind determines what execute_plan_step() does.
    The frontend renders this as an editable card.

    DAG support: sample_ref allows steps to reference outputs
    of previous steps using {{variable_name}} syntax.
    e.g. step 2 can reference step 1's sample_id via "{{sample_id}}"
    """
    step_id:    str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    kind:       str                           # optimise_condition | prepare_sample | test_sample | plotter | query_database
    label:      str                           # human-readable description
    instrument: Optional[str] = None         # which instrument runs this step

    # For prepare_sample steps
    params:     Dict[str, float] = Field(default_factory=dict)
    produces:   Optional[str] = None         # variable name for output e.g. "sample_id"

    # For test_sample steps
    sample_ref: Optional[str] = None         # e.g. "{{sample_id}}" or literal "S-1-001"
    conditions: Dict[str, float] = Field(default_factory=dict)
    measures:   Optional[str] = None         # output metric name

    # For optimise_condition steps
    condition_label:  Optional[str] = None
    condition_value:  Optional[float] = None
    condition_unit:   str = ""
    free_params:      List[dict] = Field(default_factory=list)
    objective_metric: Optional[str] = None
    n_calls:          int = 20
    n_initial_points: int = 6

    # For query_database steps
    sql:         Optional[str] = None
    description: Optional[str] = None

    # Editable by user in WorkflowPlanEditor
    editable_fields: List[str] = Field(default_factory=list)


class WorkflowPlan(BaseModel):
    """
    A complete proposed workflow plan.

    Created by the LLM via plan_workflow tool call.
    Displayed in WorkflowPlanEditor for human review + modification.
    Sent to POST /execute-plan after approval.
    """
    plan_id:   str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    summary:   str                           # human-readable one-liner
    steps:     List[WorkflowStep]
    source:    str = "agent"                 # "agent" | "paper" | "user"
    created_at: str = ""


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
    llm:       bool = False
    optimiser: bool = False
    sampler:   bool = False
    tester:    bool = False
    memory:    bool = False
    knowledge: bool = False
    reporting: bool = False


# ── Results ───────────────────────────────────────────────────────────────────

class ResultEntry(BaseModel):
    condition_label: str   = "power_W"
    condition_value: float = 0.0
    power_W:         float = 0.0
    X:  List[List[float]] = Field(default_factory=list)
    y:  List[float]       = Field(default_factory=list)
    best_params:     Dict[str, float] = Field(default_factory=dict)
    best_objective:  Optional[float]  = None
    best_energy:     Optional[float]  = None
    best_am:         Optional[float]  = None
    best_por:        Optional[float]  = None
    failed_samples:     int = 0
    attempts:           int = 0
    termination_reason: Optional[str] = None
    param_names: List[str] = Field(default_factory=list)


def make_result_entry(
    condition_label: str,
    condition_value: float,
) -> dict:
    return {
        "condition_label": condition_label,
        "condition_value": condition_value,
        "param_names":     [],
        "power_W":         condition_value,
        "X":               [],
        "y":               [],
        "best_params":     {},
        "best_objective":  None,
        "best_energy":     None,
        "best_am":         None,
        "best_por":        None,
        "failed_samples":  0,
        "attempts":        0,
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

    # Phase 3: active condition key
    active_condition_key: str = ""

    # Phase 3: sample registry
    sample_registry: List[Sample] = Field(default_factory=list)

    # Phase 3: pending workflow plan (shown in WorkflowPlanEditor)
    pending_plan: Optional[WorkflowPlan] = None

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

    # Live event queue
    live_event_queue: List[ExecutionEvent] = Field(default_factory=list)

    # Phase 2C: resource schedule log
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

class ExecutePlanRequest(BaseModel):
    """
    Sent from frontend after user approves (and optionally edits)
    a WorkflowPlan in the WorkflowPlanEditor.
    """
    session_id: str
    plan:       Dict[str, Any]   # serialised WorkflowPlan