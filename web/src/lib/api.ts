import type { Overview, RunResult, TestCase, ToolSample } from "./types";

const BASE = "/api";

async function asjson<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as T;
}

export async function getOverview(): Promise<Overview> {
  return asjson<Overview>(await fetch(`${BASE}/overview`));
}

export async function getCases(): Promise<TestCase[]> {
  return asjson<TestCase[]>(await fetch(`${BASE}/cases`));
}

export async function getCase(id: string): Promise<TestCase> {
  return asjson<TestCase>(await fetch(`${BASE}/cases/${encodeURIComponent(id)}`));
}

export async function upsertCase(c: TestCase): Promise<TestCase> {
  return asjson<TestCase>(
    await fetch(`${BASE}/cases/${encodeURIComponent(c.id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(c),
    }),
  );
}

export async function runCase(id: string): Promise<RunResult> {
  return asjson<RunResult>(
    await fetch(`${BASE}/cases/${encodeURIComponent(id)}/run`, { method: "POST" }),
  );
}

export async function getToolSamples(tool?: string): Promise<ToolSample[]> {
  const q = tool ? `?tool_name=${encodeURIComponent(tool)}` : "";
  return asjson<ToolSample[]>(await fetch(`${BASE}/tool-samples${q}`));
}
