import {
  Bot,
  Database,
  FileSearch,
  Gauge,
  ListChecks,
  MessagesSquare,
  Settings2,
  Waypoints,
  TestTube2,
  type LucideIcon,
} from "lucide-react";

export interface NavigationItem {
  label: string;
  path: string;
  icon: LucideIcon;
  match?: string;
}

export interface NavigationGroup {
  label?: string;
  items: NavigationItem[];
}

export interface ShellContext {
  area: "agentrig";
  eyebrow: string;
  code: string;
  title: string;
  subtitle: string;
  icon: LucideIcon;
  groups: NavigationGroup[];
}

const evaluationItems: NavigationItem[] = [
  { label: "智能评测助手", path: "/assistant", icon: MessagesSquare },
  { label: "评测总览", path: "/evaluation/overview", icon: Gauge },
  { label: "运行记录", path: "/evaluation/batches", icon: ListChecks },
  { label: "测试用例", path: "/evaluation/test-cases", icon: TestTube2 },
  { label: "用例审核", path: "/evaluation/cases/review", icon: FileSearch, match: "/evaluation/cases" },
  { label: "Targets", path: "/evaluation/targets", icon: Waypoints },
  { label: "Profiles", path: "/evaluation/profiles", icon: Settings2 },
  { label: "Samples", path: "/evaluation/samples", icon: Database },
];

const titleMap: Array<[RegExp, Pick<ShellContext, "title" | "subtitle" | "icon">]> = [
  [/^\/assistant/, { title: "智能评测助手", subtitle: "AgentTeams · V2", icon: MessagesSquare }],
  [/^\/evaluation\/batches\/[^/]+$/, { title: "Run Detail", subtitle: "CaseRun · evidence", icon: ListChecks }],
  [/^\/evaluation\/targets/, { title: "Targets", subtitle: "Driver · versions", icon: Waypoints }],
  [/^\/evaluation\/profiles/, { title: "Execution Profiles", subtitle: "Providers · evaluation", icon: Settings2 }],
  [/^\/evaluation\/samples/, { title: "Samples", subtitle: "Tool results · review", icon: Database }],
  [/^\/evaluation\/test-cases/, { title: "Test Cases", subtitle: "Evaluation · authored cases", icon: TestTube2 }],
  [/^\/evaluation\/cases/, { title: "Case Workspace", subtitle: "Evaluation · trace evidence", icon: TestTube2 }],
  [/^\/evaluation/, { title: "Evaluation", subtitle: "AgentRig · V1", icon: Gauge }],
];

function pageContext(pathname: string) {
  return titleMap.find(([matcher]) => matcher.test(pathname))?.[1] ?? {
    title: "AgentRig",
    subtitle: "MCP 原生 agent 测试台",
    icon: Bot,
  };
}

export function getShellContext(pathname: string): ShellContext {
  const page = pageContext(pathname);
  return {
    ...page,
    area: "agentrig",
    eyebrow: "AGENTRIG",
    code: "EVALUATION / CONTROL",
    groups: [{ items: evaluationItems }],
  };
}

export function isNavigationActive(item: NavigationItem, pathname: string) {
  if (item.match) return pathname.startsWith(item.match);
  return pathname === item.path || pathname.startsWith(`${item.path}/`);
}
