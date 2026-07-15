// 前端数据类型（对齐后端 models.py + run_single_case 返回）
export type JudgeMode = "rule" | "ai" | "off";
export type LastResult = "passed" | "failed" | "review" | "draft";

export interface Expectation {
  kind: "expected_tools" | "text_contains" | "tool_call_order" | "not_called" | string;
  tools?: string[];
  needle?: string;
  [k: string]: unknown;
}

export interface TestCase {
  id: string;
  name: string;
  user_message: string;
  expected_tools: string[];
  expectations: Expectation[];
  mock: Record<string, unknown>;
  tags: string[];
  rubric?: string | null;
  judge_mode: JudgeMode;
  // 前端展示用的派生字段（后端 list 可附带；缺失则前端推断）
  last_result?: LastResult;
  updated_ago?: string;
}

export interface RunResult {
  case_id: string;
  passed: boolean;
  reasons: string[];
  judge_mode: JudgeMode;
  assistant_text: string;
  tool_calls: string[];
  tool_results_count: number;
  missing_expected_tools: string[];
  error: string | null;
  transport: "real" | "echo";
}

export interface RunSummary {
  id: string;
  commit: string;
  scope: string;
  passed: number;
  failed: number;
  total: number;
  duration: string;
  when: string;
}

export interface ToolSample {
  tool_name: string;
  arguments: Record<string, unknown>;
  source: string;
  is_error: boolean;
  result: unknown;
}

export interface Overview {
  total_cases: number;
  pass_rate: number;
  median_run: string;
  changed_tools: number;
  passed: number;
  failed: number;
  skipped: number;
  coverage_done: number;
  coverage_total: number;
  recent_runs: RunSummary[];
  suite_growth: { name: string; delta: number; when: string }[];
}
