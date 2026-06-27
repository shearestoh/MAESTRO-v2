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

export interface ResultEntry {
  // ── Phase 3: general condition fields ──────────────────────────────────────
  condition_label: string;    // e.g. "power_W", "temperature_C", "ph"
  condition_value: number;    // the fixed value for this run

  // ── Backward compat ────────────────────────────────────────────────────────
  power_W: number;            // mirrors condition_value

  // ── BO results ─────────────────────────────────────────────────────────────
  X:  [number, number][];
  y:  number[];

  // ── Best observed ──────────────────────────────────────────────────────────
  best_params:    Record<string, number>;  // general: {param_name: value}
  best_objective: number | null;           // general field
  best_energy:    number | null;           // backward compat alias

  // ── Legacy battery-specific best fields ────────────────────────────────────
  best_am:  number | null;
  best_por: number | null;

  // ── Diagnostics ────────────────────────────────────────────────────────────
  failed_samples:     number;
  attempts:           number;
  termination_reason: string | null;

  // ── Param names used in this run ───────────────────────────────────────────
  param_names: string[];
}

export interface OutstandingTask {
  kind:              string;
  condition_label:   string;
  condition_value:   number;
  remaining_n_calls: number;
  free_params:       Array<{name: string; min: number; max: number; unit: string}>;
  // backward compat
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
  // Phase 3
  active_condition_key:       string;
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

// ── Tool Registry ─────────────────────────────────────────────────────────────

export interface VirtualTool {
  tool_id:       string;
  name:          string;
  kind:          string;
  description:   string;
  parameters:    ToolParameter[];
  outputs:       ToolOutput[];
  failure_modes: ToolFailureMode[];
  time_cost_min: number;
  enabled:       boolean;
}

export interface ToolParameter {
  name:        string;
  type:        string;
  min?:        number;
  max?:        number;
  unit:        string;
  description: string;
  required:    boolean;
}

export interface ToolOutput {
  name:        string;
  type:        string;
  unit:        string;
  description: string;
}

export interface ToolFailureMode {
  name:        string;
  description: string;
  probability: number;
}