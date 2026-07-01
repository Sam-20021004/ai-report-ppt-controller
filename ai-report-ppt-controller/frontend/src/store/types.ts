export type StepStatus =
  | "waiting"
  | "running"
  | "success"
  | "failed"
  | "needs_review"
  | "paused"
  | "cancelled"
  | "done"
  | "skipped";

export interface WorkflowStep {
  index: number;
  step_name: string;
  agent: string;
  status: StepStatus;
  output_summary: string;
  error: string;
}

export interface TaskRecord {
  task_id: string;
  status: StepStatus;
  request: Record<string, unknown>;
  steps: WorkflowStep[];
  workspace_dir: string;
  review_round: number;
  generated_files: Record<string, unknown>[];
  final_quality_check: Record<string, unknown>;
}
