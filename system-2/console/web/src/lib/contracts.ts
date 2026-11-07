// A hand-written mirror of system-2/contracts (models.py and events.py). Only the fields the Console reads.
// When the server lands, generate these from `uv run python -m rav_contracts.export_schema` instead.

export type Status = "passed" | "failed" | "intermittent" | "observed" | "skipped" | "inconclusive";
export type ControlKind = "button" | "slider" | "dial" | "toggle" | "door" | "knob" | "display" | "well" | "object" | "other";

export interface Control {
  id: string;
  kind: ControlKind;
  pos_mm: [number, number, number];
  normal: [number, number, number];
  conf: number;
  source: string;
  position?: number | null;
  travel_mm?: number | null;
  turn_range_deg?: [number, number] | null;
  on?: boolean | null;
  latched?: boolean | null;
}

export interface SceneInventory {
  frame: string;
  controls: Control[];
  unmatched_manual_controls: string[];
  notes: string[];
}

export interface Step {
  id: string;
  skill: string;
  target: string;
  params: Record<string, unknown>;
  quote: string | null;
  expected: string | null;
  why: string | null;
}

export interface Plan {
  plan_id: string;
  steps: Step[];
  source: "rules" | "model" | "cached" | "mock";
}

export interface StepTrace {
  step: string;
  attempt: number;
  stop_reason: string | null;
  duration_s: number | null;
  peak_force_n: number | null;
  travel_mm: number | null;
  force_trace: [number, number][];
  readout_change: Record<string, unknown[]>;
  frames: string[]; // evidence_get refs
  measures?: Record<string, unknown>;
  checks?: CheckResult[];
}

export interface CheckResult {
  metric: string;
  op: string;
  value: unknown;
  actual: unknown;
  passed: boolean | null;
}

export interface StepVerdict {
  step: string;
  target: string;
  attempt: number;
  status: Status;
  label: string | null;
  reason: string;
  channel: string | null;
  decided_by: "rule" | "cobweb" | "model" | "safety";
  evidence: string[];
}

export interface Finding {
  id: string;
  severity: "high" | "medium" | "low";
  target: string;
  label: string;
  what_happened: string;
  manual_says: string | null;
  user_impact: string | null;
  step_ids: string[];
  event_seqs: number[];
  evidence: string[];
  confirmed: boolean;
}

export interface Hypothesis {
  cause: string;
  p: number;
  check: string | null;
  ruled_out: string | null;
}

export interface RootCause {
  finding: string;
  evidence: string[];
  hypotheses: Hypothesis[];
  root_cause: string;
  confidence: number;
}

export interface ParamChange {
  param: string;
  from_value: unknown;
  to_value: unknown;
  unit: string | null;
  predicted: string | null;
}

export interface CadSource {
  document_id: string;
  workspace_id: string;
  microversion_id: string;
  base_version_id: string;
  element_id?: string | null;
  url?: string | null;
}

export interface CadEdit {
  op: "variable" | "update_feature" | "add_feature" | "delete_feature";
  target: string;
  summary: string;
}

export interface CADPatch {
  file: string;
  revision_from: string;
  revision_to: string;
  changes: ParamChange[];
  constraints_checked: string[];
  approved_by: string | null;
  verify_with: string[];
  backend: string;
  source?: CadSource | null;
  edits?: CadEdit[];
}

export interface Coverage {
  detected: number;
  passed: string[];
  failed: string[];
  observed: string[];
  inconclusive: string[];
  skipped: Record<string, string>;
  intermittent?: string[]; // failed, then passed on a retest
}

export interface Reward {
  value: number;
  control_coverage: number;
  pass_rate: number;
  formula: string;
}

export interface Report {
  run_id: string;
  product: string;
  revision: string;
  summary: string;
  findings: Finding[];
  coverage: Coverage;
  reward: Reward;
}

export type EventType =
  | "run_started" | "scene_ready" | "plan_ready" | "approval_needed" | "approved" | "step_started"
  | "step_finished" | "finding" | "root_cause" | "patch_proposed" | "patch_applied" | "steer_applied"
  | "message" | "report_ready" | "run_finished" | "model_turn" | "tool_call" | "crossing" | "plan_amended" | "agent_state" | "check_judged";

export interface RunEvent {
  seq: number;
  t: number;
  run_id: string;
  type: EventType;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload: any;
}

export type SteerKind = "pause" | "resume" | "stop" | "prioritize" | "skip" | "add_step" | "message";

export interface SteerCommand {
  kind: SteerKind;
  target?: string;
  step?: Partial<Step>;
  text?: string;
  by: string;
}
