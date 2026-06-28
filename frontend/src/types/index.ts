// ── Equipment & Session ───────────────────────────────────────────────────────

export interface EquipmentStatus {
  llm:       boolean;
  optimiser: boolean;
  sampler:   boolean;
  tester:    boolean;
  memory:    boolean;
  knowledge: boolean;
  reporting: boolean;
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
  name:           string;
  original_name?: string;
  min:            number;
  max:            number;
  unit:           string;
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
  tested_day: number;
  notes:      string;
}

export interface Sample {
  sample_id:      string;
  params:         Record<string, number>;
  prepared_by:    string;
  status:         "prepared" | "tested" | "failed" | "stored";
  prepared_at:    string;
  prepared_day:   number;
  failure_reason: string | null;
  notes:          string;
  results:        SampleResult[];
  tags:           string[];
}

// ── Workflow Plan ─────────────────────────────────────────────────────────────

export interface WorkflowStep {
  step_id:          string;
  kind:             "prepare_sample" | "test_sample" | "optimise_condition" | "list_samples" | "query_database" | "plotter" | "narration";
  label:            string;
  instrument?:      string;
  // prepare_sample
  params?:          Record<string, number>;
  produces?:        string;
  // test_sample
  sample_ref?:      string;
  conditions?:      Record<string, number>;
  measures?:        string;
  // optimise_condition
  condition_label?: string;
  condition_value?: number;
  condition_unit?:  string;
  free_params?:     Array<{name: string; min: number; max: number; unit: string}>;
  objective_metric?: string;
  n_calls?:         number;
  n_initial_points?: number;
  // query_database
  sql?:             string;
  description?:     string;
  // editable fields
  editable_fields?: string[];
}

export interface WorkflowPlan {
  plan_id:    string;
  summary:    string;
  steps:      WorkflowStep[];
  source:     "agent" | "paper" | "user";
  created_at: string;
}

// ── Results ───────────────────────────────────────────────────────────────────

export interface ResultEntry {
  condition_label: string;
  condition_value: number;
  power_W:         number;
  X:               [number, number][];
  y:               number[];
  best_params:     Record<string, number>;
  best_objective:  number | null;
  best_energy:     number | null;
  best_am:         number | null;
  best_por:        number | null;
  failed_samples:  number;
  attempts:        number;
  termination_reason: string | null;
  param_names:     string[];
}

export interface OutstandingTask {
  kind:              string;
  condition_label:   string;
  condition_value:   number;
  remaining_n_calls: number;
  completed_calls?:  number;
  free_params:       Array<{name: string; min: number; max: number; unit: string}>;
  power_W?:          number;
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

export interface ResourceLogEntry {
  tool:      string;
  day:       number;
  start_min: number;
  end_min:   number;
}

export interface MetricLabels {
  experiments: string;
  best_result: string;
  conditions:  string;
  failures:    string;
}

export interface SessionState {
  session_id:                 string;
  messages:                   Message[];
  results_store:              ResultEntry[];
  awaiting_confirmation:      boolean;
  pending_tool_calls:         ToolCall[];
  last_tool_result:           unknown;
  last_tools_used:            string[];
  virtual_clock_minutes:      number;
  virtual_day_index:          number;
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
  timeline:                   TimelineItem[];
  metric_labels:              MetricLabels;
  resource_log:               ResourceLogEntry[];
  active_condition_key:       string;
  // Phase 3
  sample_registry:            Sample[];
  pending_plan:               WorkflowPlan | null;
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
  | "llm" | "optimiser" | "sampler" | "tester"
  | "memory" | "knowledge" | "reporting" | "custom";

export interface EquipmentNodeData {
  label:         string;
  equipmentType: EquipmentType;
  active:        boolean;
  failProb?:     number;
  timeCost?:     number;
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
  description:   string;
  parameters:    InstrumentParameter[];
  outputs:       InstrumentOutput[];
  failure_modes: InstrumentFailureMode[];
  time_cost_min: number;
  enabled:       boolean;
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

// Backward compat alias
export type VirtualTool = VirtualInstrument;