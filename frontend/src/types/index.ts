// ── Equipment & Session ───────────────────────────────────────────────────────

export interface EquipmentStatus {
  llm:           boolean;
  optimiser:     boolean;
  synthesiser:   boolean;
  characteriser: boolean;
  memory:        boolean;
  knowledge:     boolean;
  reporting:     boolean;
}

export interface TimelineItem {
  label:  string;
  status: "done" | "active" | "pending";
}

export interface Artifact {
  name: string;
  kind: string;
  path: string;
}

export interface ParameterSpec {
  name:            string;
  original_name?:  string;
  min:             number;
  max:             number;
  unit:            string;
  mapped_to_tool?: string;
}

export interface OperatingCondition {
  name:         string;
  values:       number[];
  unit:         string;
  description?: string;
}

export interface CampaignSpec {
  campaign_id:          string;
  title:                string;
  source_document_id:   string;
  target_case_study:    string;
  objective_metric:     string;
  parameter_space:      ParameterSpec[];
  operating_conditions: OperatingCondition[];
  desired_outputs:      string[];
  assumptions:          string[];
  provenance:           Record<string, unknown>;
  capability_match:     Record<string, unknown>;
  status:               string;
}

// ── Sample Registry ───────────────────────────────────────────────────────────

export interface SampleResult {
  result_id:  string;
  tested_by:  string;
  conditions: Record<string, number>;
  outputs:    Record<string, number>;
  tested_at:  string;
  notes:      string;
}

export interface Sample {
  sample_id:      string;
  params:         Record<string, number>;
  prepared_by:    string;
  status:         "prepared" | "tested" | "failed" | "stored";
  prepared_at:    string;
  failure_reason: string | null;
  notes:          string;
  results:        SampleResult[];
  tags:           string[];
}

// ── Workflow Plan ─────────────────────────────────────────────────────────────

export type StepStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export interface WorkflowStep {
  step_id:               string;
  kind:                  string;
  label:                 string;
  instrument?:           string;
  instrument_id?:        string;
  dependencies:          string[];
  status:                StepStatus;
  start_time?:           string;
  end_time?:             string;
  projected_start_time?: string;
  projected_end_time?:   string;
  params?:               Record<string, number>;
  produces?:             string;
  sample_ref?:           string;
  conditions?:           Record<string, number>;
  measures?:             string;
  condition_label?:      string;
  condition_value?:      number;
  condition_unit?:       string;
  free_params?:          Array<{ name: string; min: number; max: number; unit: string }>;
  objective_metric?:     string;
  optimiser_name?:       string;
  n_calls?:              number;
  n_initial_points?:     number;
  plot_code?:            string;
  analysis_code?:        string;
  sql?:                  string;
  description?:          string;
  editable_fields?:      string[];
}

export interface WorkflowPlan {
  plan_id:    string;
  summary:    string;
  steps:      WorkflowStep[];
  source:     "agent" | "paper" | "user";
  created_at: string;
}

// ── Projected Schedule ────────────────────────────────────────────────────────

export interface ProjectedScheduleEntry {
  instrument_id:   string;
  instrument_name: string;
  start_time:      string;
  end_time:        string;
  step_id:         string;
  label:           string;
  is_projected:    boolean;
}

// ── Results ───────────────────────────────────────────────────────────────────

export interface ResultEntry {
  condition_label:    string;
  condition_value:    number;
  optimiser_name:     string;
  X:                  number[][];
  y:                  number[];
  best_params:        Record<string, number>;
  best_objective:     number | null;
  failed_samples:     number;
  attempts:           number;
  termination_reason: string | null;
  param_names:        string[];
}

export interface OutstandingTask {
  kind:              string;
  condition_label:   string;
  condition_value:   number;
  remaining_n_calls: number;
  completed_calls?:  number;
  free_params:       Array<{ name: string; min: number; max: number; unit: string }>;
}

export interface ToolCall {
  id:       string;
  type:     string;
  function: { name: string; arguments: string };
}

export interface Message {
  role:        "user" | "assistant" | "system" | "tool";
  content:     string;
  tool_calls?: ToolCall[];
}

export interface MetricLabels {
  experiments: string;
  best_result: string;
  conditions:  string;
  failures:    string;
}

export interface OptimiserConfig {
  name:             string;
  n_calls:          number;
  n_initial_points: number;
}

export interface SessionState {
  session_id:                 string;
  messages:                   Message[];
  results_store:              ResultEntry[];
  awaiting_confirmation:      boolean;
  pending_tool_calls:         ToolCall[];
  last_tool_result:           unknown;
  last_tools_used:            string[];
  outstanding_tasks:          OutstandingTask[];
  show_plotter_image:         string | null;
  active_document_id:         string | null;
  extracted_campaign:         CampaignSpec | null;
  equipment_status:           EquipmentStatus;
  current_activity:           string | null;
  activity_log:               string[];
  current_mission:            string | null;
  artifacts:                  Artifact[];
  background_job_active:      boolean;
  background_job_label:       string | null;
  background_job_error:       string | null;
  background_job_status:      string;
  background_job_index:       number;
  background_job_plan_length: number;
  background_job_plan:        WorkflowStep[];
  step_statuses:              Record<string, StepStatus>;
  bo_iteration_counts:        Record<string, number>;
  timeline:                   TimelineItem[];
  metric_labels:              MetricLabels;
  resource_log:               ResourceLogEntry[];
  active_condition_key:       string;
  sample_registry:            Sample[];
  pending_plan:               WorkflowPlan | null;
  optimiser_config:           OptimiserConfig;
  projected_schedule:         ProjectedScheduleEntry[];
}

export interface ResourceLogEntry {
  instrument: string;
  start_time: string;
  end_time:   string;
}

// ── WebSocket Events ──────────────────────────────────────────────────────────

export interface WsEvent {
  event_type: string;
  message:    string;
  equipment:  string | null;
  category:   string;
  payload:    Record<string, unknown>;
}

// ── Digital Twin ──────────────────────────────────────────────────────────────

export type EquipmentType =
  | "llm" | "optimiser" | "synthesiser" | "characteriser"
  | "memory" | "knowledge" | "reporting" | "custom";

export interface EquipmentNodeData {
  label:         string;
  equipmentType: EquipmentType;
  active:        boolean;
  failProb?:     number;
  timeCostS?:    number;
  noiseSigma?:   number;
  description?:  string;
  status:        "idle" | "active" | "failed" | "maintenance";
  tool_id?:      string;
  [key: string]: unknown;
}

// ── Instrument Registry ───────────────────────────────────────────────────────

export interface VirtualInstrument {
  tool_id:       string;
  name:          string;
  kind:          string;
  category:      "physical" | "computational";
  sub_category:  string;
  description:   string;
  parameters:    InstrumentParameter[];
  outputs:       InstrumentOutput[];
  failure_modes: InstrumentFailureMode[];
  time_cost_s:   number;
  enabled:       boolean;
  is_default:    boolean;
}

export interface InstrumentParameter {
  name:        string;
  type:        string;
  min?:        number;
  max?:        number;
  unit:        string;
  description: string;
  required:    boolean;
}

export interface InstrumentOutput {
  name:        string;
  type:        string;
  unit:        string;
  description: string;
}

export interface InstrumentFailureMode {
  name:        string;
  description: string;
  probability: number;
}

export type VirtualTool = VirtualInstrument;

// ── Lab Settings ──────────────────────────────────────────────────────────────

export type DocumentType = "paper" | "manual";

export interface DocumentLibraryEntry {
  document_id: string;
  filename:    string;
  title:       string | null;
  summary:     string | null;
  uploaded_at: string;
  file_path:   string;
  doc_type:    DocumentType;
}

export interface OptimisationLibraryEntry {
  lib_id:       string;
  name:         string;
  description:  string;
  capabilities: string[];
  install_cmd:  string;
  docs_url:     string;
  enabled:      boolean;
  is_default:   boolean;
}

// ── Resource Inventory ────────────────────────────────────────────────────────

export interface ResourceConsumptionRule {
  instrument_name: string;
  amount_per_use:  number;
  description:     string;
}

export interface LabResource {
  resource_id:       string;
  name:              string;
  unit:              string;
  current_stock:     number;
  min_stock:         number;
  description:       string;
  consumption_rules: ResourceConsumptionRule[];
}

// ── Protocols ─────────────────────────────────────────────────────────────────
// Matches the backend ProtocolEntry model exactly.

export interface ProtocolEntry {
  protocol_id:       string;
  name:              string;
  description:       string;
  created_at:        string;
  optimiser_used:    string;
  results_summary:   string;
  user_instructions: string[];
  workflow_plan:     Record<string, unknown> | null;
  notes:             string;
}

// ── Lab Settings ──────────────────────────────────────────────────────────────

export interface LabSettings {
  lab_name:                string;
  lab_description:         string;
  system_prompt_extension: string;
  document_library:        DocumentLibraryEntry[];
  optimisation_library:    OptimisationLibraryEntry[];
  resource_inventory:      LabResource[];
  protocols:               ProtocolEntry[];
}