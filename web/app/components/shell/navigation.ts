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
      label: "评测管理",
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
      label: "资产管理",
      items: [
        { label: "资产总览", path: targetPath(targetId, "/assets"), icon: Boxes },
        { label: "工具结果资产", path: targetPath(targetId, "/assets/tool-results"), icon: FileSearch },
        { label: "执行配置", path: targetPath(targetId, "/assets/profiles"), icon: Settings2 },
      ],
    };
  } else if (pathname.includes("/observability")) {
    section = {
      label: "观测与分析",
      items: [
        { label: "观测总览", path: targetPath(targetId, "/observability"), icon: Activity },
        { label: "指标目录", path: targetPath(targetId, "/observability/metrics"), icon: BarChart3 },
        { label: "问题中心", path: targetPath(targetId, "/observability/problems"), icon: FileSearch },
        { label: "数据导出", path: targetPath(targetId, "/observability/export"), icon: ClipboardCheck },
      ],
    };
  } else {
    section = {
      label: "工作区导航",
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
    [/\/conversation$/, "对话验证", "直接连接被测 Agent", MessageSquare],
    [/\/assistant$/, "智能评测助手", "AgentTeams 协作评测", MessagesSquare],
    [/\/overview$/, "评测总览", "质量与运行概况", Gauge],
    [/\/evaluation\/runs\/[^/]+$/, "运行证据", "用例运行可审计链路", ListChecks],
    [/\/evaluation\/runs$/, "运行记录", "运行与用例运行", ListChecks],
    [/\/evaluation\/test-cases/, "测试用例", "多轮脚本与评判规则", TestTube2],
    [/\/evaluation\/case-review$/, "用例审核", "人工审核与不可变资产", FileSearch],
    [/\/evaluation\/comparisons$/, "版本对比", "基线版本与候选版本", History],
    [/\/evaluation\/reports$/, "评测报告", "冻结、分享与导出", ClipboardCheck],
    [/\/assets\/tool-results$/, "工具结果资产", "结果样本与结果提供链", FileSearch],
    [/\/assets\/profiles$/, "执行配置", "工具模式、结果提供与评判器", Settings2],
    [/\/assets$/, "资产总览", "覆盖范围与治理状态", Boxes],
    [/\/observability\/metrics$/, "指标目录", "公式、来源与统计维度", BarChart3],
    [/\/observability\/problems$/, "问题中心", "证据归并与重复失败", FileSearch],
    [/\/observability\/export$/, "数据导出", "范围控制与安全脱敏", ClipboardCheck],
    [/\/observability$/, "观测总览", "质量与可靠性趋势", Activity],
  ];
  return pages.find(([matcher]) => matcher.test(pathname))?.slice(1) as [string, string, LucideIcon] | undefined;
}

export function getShellContext(pathname: string): ShellContext {
  const targetId = targetFromPath(pathname);
  if (targetId) {
    const [title, subtitle, icon] = pageTitle(pathname) ?? ["被测 Agent 工作区", "统一评测控制面", Bot];
    return {
      area: "target",
      eyebrow: "被测 Agent 工作区",
      code: "评测控制台",
      title,
      subtitle,
      icon,
      groups: targetGroups(pathname, targetId),
      targetId,
    };
  }
  const title = pathname.startsWith("/evaluator-teams")
    ? ["评测团队", "AgentTeams 身份与协作", UsersRound] as const
    : pathname.startsWith("/audit")
      ? ["审计日志", "操作者、资源与结果", ShieldCheck] as const
      : pathname.startsWith("/settings")
        ? ["系统设置", "运行时、访问控制与模型", Settings2] as const
        : ["被测 Agent", "接入目录与评测入口", LayoutGrid] as const;
  return {
    area: "platform",
    eyebrow: "AGENTRIG 评测平台",
    code: "平台控制台",
    title: title[0],
    subtitle: title[1],
    icon: title[2],
    groups: [{
      items: [
        { label: "被测 Agent", path: "/targets", icon: Waypoints },
        { label: "评测团队", path: "/evaluator-teams", icon: UsersRound },
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
