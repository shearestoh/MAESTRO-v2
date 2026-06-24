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
  name: string;
  min:  number;
  max:  number;
  unit: string;
}

export interface OperatingCondition {
  name:   string;
  values: number[];
  unit:   string;
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
  power_W:            number;
  X:                  [number, number][];
  y:                  number[];
  best_am:            number | null;
  best_por:           number | null;
  best_energy:        number | null;
  failed_samples:     number;
  attempts:           number;
  termination_reason: string | null;
}

export interface OutstandingTask {
  kind:              string;
  power_W:           number;
  remaining_n_calls: number;
  params:            Record<string, number>;
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
  [key: string]: unknown;
}