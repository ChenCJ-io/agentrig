import {
  Activity,
  BarChart3,
  Bot,
  Boxes,
  ClipboardCheck,
  FileSearch,
  Gauge,
  History,
  LayoutGrid,
  ListChecks,
  MessageSquare,
  MessagesSquare,
  Settings2,
  ShieldCheck,
  TestTube2,
  UsersRound,
  Waypoints,
  type LucideIcon,
} from "lucide-react";

export interface NavigationItem {
  label: string;
  path: string;
  icon: LucideIcon;
  match?: string | RegExp;
}

export interface NavigationGroup {
  label?: string;
  items: NavigationItem[];
}

export interface ShellContext {
  area: "platform" | "target";
  eyebrow: string;
  code: string;
  title: string;
  subtitle: string;
  icon: LucideIcon;
  groups: NavigationGroup[];
  targetId?: string;
}

function targetPath(targetId: string, suffix: string) {
  return `/targets/${encodeURIComponent(targetId)}${suffix}`;
}

function targetFromPath(pathname: string) {
  const match = pathname.match(/^\/targets\/([^/]+)(?:\/|$)/);
  return match ? decodeURIComponent(match[1]!) : null;
}

function targetGroups(pathname: string, targetId: string): NavigationGroup[] {
  const primary: NavigationItem[] = [
    { label: "工作区", path: targetPath(targetId, "/overview"), icon: Gauge, match: /^\/targets\/[^/]+\/(?:overview|conversation|assistant)/ },
    { label: "评测", path: targetPath(targetId, "/evaluation/runs"), icon: ListChecks, match: /^\/targets\/[^/]+\/evaluation/ },
    { label: "资产", path: targetPath(targetId, "/assets"), icon: Boxes, match: /^\/targets\/[^/]+\/assets/ },
    { label: "观测", path: targetPath(targetId, "/observability"), icon: Activity, match: /^\/targets\/[^/]+\/observability/ },
  ];
  let section: NavigationGroup;
  if (pathname.includes("/evaluation/")) {
    section = {
      label: "EVALUATION INDEX",
      items: [
        { label: "运行记录", path: targetPath(targetId, "/evaluation/runs"), icon: ListChecks },
        { label: "测试用例", path: targetPath(targetId, "/evaluation/test-cases"), icon: TestTube2 },
        { label: "用例审核", path: targetPath(targetId, "/evaluation/case-review"), icon: FileSearch },
        { label: "版本对比", path: targetPath(targetId, "/evaluation/comparisons"), icon: History },
        { label: "评测报告", path: targetPath(targetId, "/evaluation/reports"), icon: ClipboardCheck },
      ],
    };
  } else if (pathname.includes("/assets")) {
    section = {
      label: "ASSET INDEX",
      items: [
        { label: "资产总览", path: targetPath(targetId, "/assets"), icon: Boxes },
        { label: "工具结果资产", path: targetPath(targetId, "/assets/tool-results"), icon: FileSearch },
        { label: "Execution Profiles", path: targetPath(targetId, "/assets/profiles"), icon: Settings2 },
      ],
    };
  } else if (pathname.includes("/observability")) {
    section = {
      label: "OBSERVABILITY INDEX",
      items: [
        { label: "观测总览", path: targetPath(targetId, "/observability"), icon: Activity },
        { label: "指标目录", path: targetPath(targetId, "/observability/metrics"), icon: BarChart3 },
        { label: "问题中心", path: targetPath(targetId, "/observability/problems"), icon: FileSearch },
        { label: "数据导出", path: targetPath(targetId, "/observability/export"), icon: ClipboardCheck },
      ],
    };
  } else {
    section = {
      label: "WORKSPACE INDEX",
      items: [
        { label: "评测总览", path: targetPath(targetId, "/overview"), icon: Gauge },
        { label: "对话验证", path: targetPath(targetId, "/conversation"), icon: MessageSquare },
        { label: "智能评测助手", path: targetPath(targetId, "/assistant"), icon: MessagesSquare },
      ],
    };
  }
  return [{ items: primary }, section];
}

function pageTitle(pathname: string) {
  const pages: Array<[RegExp, string, string, LucideIcon]> = [
    [/\/conversation$/, "对话验证", "Target · direct session", MessageSquare],
    [/\/assistant$/, "智能评测助手", "AgentTeams · managed evaluation", MessagesSquare],
    [/\/overview$/, "评测总览", "Quality · operations", Gauge],
    [/\/evaluation\/runs\/[^/]+$/, "Run Evidence", "CaseRun · auditable trace", ListChecks],
    [/\/evaluation\/runs$/, "运行记录", "Runs · CaseRuns", ListChecks],
    [/\/evaluation\/test-cases/, "测试用例", "Cases · turns · rubric", TestTube2],
    [/\/evaluation\/case-review$/, "用例审核", "Human review · immutable", FileSearch],
    [/\/evaluation\/comparisons$/, "版本对比", "Baseline · candidate", History],
    [/\/evaluation\/reports$/, "评测报告", "Frozen · shareable", ClipboardCheck],
    [/\/assets\/tool-results$/, "工具结果资产", "Samples · provider chain", FileSearch],
    [/\/assets\/profiles$/, "Execution Profiles", "Mode · providers · evaluator", Settings2],
    [/\/assets$/, "资产总览", "Coverage · governance", Boxes],
    [/\/observability\/metrics$/, "指标目录", "Formula · source · dimensions", BarChart3],
    [/\/observability\/problems$/, "问题中心", "Evidence · recurring failures", FileSearch],
    [/\/observability\/export$/, "数据导出", "Scoped · redacted", ClipboardCheck],
    [/\/observability$/, "观测总览", "Quality · reliability", Activity],
  ];
  return pages.find(([matcher]) => matcher.test(pathname))?.slice(1) as [string, string, LucideIcon] | undefined;
}

export function getShellContext(pathname: string): ShellContext {
  const targetId = targetFromPath(pathname);
  if (targetId) {
    const [title, subtitle, icon] = pageTitle(pathname) ?? ["Target Workspace", "Evaluation control plane", Bot];
    return {
      area: "target",
      eyebrow: "TARGET WORKSPACE",
      code: "EVALUATION / CONTROL",
      title,
      subtitle,
      icon,
      groups: targetGroups(pathname, targetId),
      targetId,
    };
  }
  const title = pathname.startsWith("/evaluator-teams")
    ? ["Evaluator Teams", "AgentTeams · identities", UsersRound] as const
    : pathname.startsWith("/audit")
      ? ["审计日志", "Actors · resources · outcomes", ShieldCheck] as const
      : pathname.startsWith("/settings")
        ? ["系统设置", "Runtime · access · models", Settings2] as const
        : ["被测 Agent", "Target directory · control plane", LayoutGrid] as const;
  return {
    area: "platform",
    eyebrow: "AGENTRIG PLATFORM",
    code: "CONTROL / DIRECTORY",
    title: title[0],
    subtitle: title[1],
    icon: title[2],
    groups: [{
      items: [
        { label: "被测 Agent", path: "/targets", icon: Waypoints },
        { label: "Evaluator Teams", path: "/evaluator-teams", icon: UsersRound },
        { label: "审计日志", path: "/audit", icon: ShieldCheck },
        { label: "系统设置", path: "/settings", icon: Settings2 },
      ],
    }],
  };
}

export function isNavigationActive(item: NavigationItem, pathname: string) {
  if (item.match instanceof RegExp) return item.match.test(pathname);
  if (item.match) return pathname.startsWith(item.match);
  return pathname === item.path || pathname.startsWith(`${item.path}/`);
}
