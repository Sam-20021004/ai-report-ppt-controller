import type { WorkflowStep } from "../store/types";

export function WorkflowTimeline({ steps }: { steps: WorkflowStep[] }) {
  return (
    <div className="timeline">
      {steps.map((step) => (
        <article className="step-row" key={step.index}>
          <div className="step-no">{step.index}</div>
          <strong>{step.step_name}</strong>
          <span>{step.agent}</span>
          <span>{step.output_summary || step.error || "等待中"}</span>
          <span className={`badge ${step.status}`}>{step.status}</span>
        </article>
      ))}
    </div>
  );
}
