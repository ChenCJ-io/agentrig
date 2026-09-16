export interface RuntimeData {
  targetId: string;
  runId: string;
  cellId: string;
  sessionId?: string;
}

export interface ApprovedRoute {
  key: string;
  path: (data: RuntimeData) => string;
  group: "targets" | "evaluation" | "assistant" | "assets";
  dataRequirement?: "target" | "plan" | "run" | "cell" | "case";
  p0: boolean;
}

const target = (data: RuntimeData) =>
  `/targets/${encodeURIComponent(data.targetId)}`;

export const approvedRoutes: ApprovedRoute[] = [
  { key: "target-overview", path: (data) => `${target(data)}/overview`, group: "targets", dataRequirement: "target", p0: true },
  { key: "run-list", path: (data) => `${target(data)}/evaluation/runs`, group: "evaluation", dataRequirement: "target", p0: true },
  { key: "run-create-review", path: (data) => `${target(data)}/evaluation/runs/new/review`, group: "evaluation", dataRequirement: "plan", p0: true },
  { key: "run-detail", path: (data) => `${target(data)}/evaluation/runs/${encodeURIComponent(data.runId)}`, group: "evaluation", dataRequirement: "run", p0: true },
  { key: "run-report", path: (data) => `${target(data)}/evaluation/runs/${encodeURIComponent(data.runId)}/report`, group: "evaluation", dataRequirement: "run", p0: true },
  { key: "cell-detail", path: (data) => `${target(data)}/evaluation/runs/${encodeURIComponent(data.runId)}/cells/${encodeURIComponent(data.cellId)}`, group: "evaluation", dataRequirement: "cell", p0: true },
  { key: "assistant-empty", path: (data) => `${target(data)}/assistant`, group: "assistant", dataRequirement: "target", p0: true },
  { key: "assistant-plan", path: (data) => `${target(data)}/assistant${data.sessionId ? `?session=${encodeURIComponent(data.sessionId)}` : ""}`, group: "assistant", dataRequirement: "plan", p0: true },
  { key: "test-cases", path: (data) => `${target(data)}/evaluation/test-cases`, group: "assets", dataRequirement: "case", p0: false },
  { key: "tool-results", path: (data) => `${target(data)}/assets/tool-results`, group: "assets", p0: false },
];
