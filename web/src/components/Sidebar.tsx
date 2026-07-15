import { NavLink } from "react-router-dom";
import { useI18n } from "../i18n";
import {
  ChevronDown,
  Code,
  Flow,
  Gear,
  Globe,
  Grid,
  List,
  Play,
  Wrench,
} from "./icons";

const items = [
  { to: "/", key: "nav.overview", Icon: Grid, end: true },
  { to: "/cases", key: "nav.cases", Icon: List, end: false },
  { to: "/runs", key: "nav.runs", Icon: Play, end: false },
  { to: "/traces", key: "nav.traces", Icon: Flow, end: false },
  { to: "/tools", key: "nav.tools", Icon: Wrench, end: false },
  { to: "/prompts", key: "nav.prompts", Icon: Code, end: false },
  { to: "/settings", key: "nav.settings", Icon: Gear, end: false },
];

export default function Sidebar() {
  const { t, toggle, lang } = useI18n();
  return (
    <aside className="w-56 bg-sidebar text-white flex flex-col shrink-0 h-full">
      {/* 品牌 */}
      <div className="px-4 pt-5 pb-4">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-accent flex items-center justify-center font-bold text-white">
            A
          </div>
          <div>
            <p className="font-semibold leading-tight">AgentRig</p>
            <p className="text-[10px] text-white/50 leading-tight">{t("brand.tagline")}</p>
          </div>
        </div>
      </div>

      {/* 项目选择器 */}
      <div className="px-3">
        <button className="w-full flex items-center justify-between px-2.5 h-8 rounded-lg bg-sidebar-hover hover:bg-sidebar-active text-xs">
          <span className="flex items-center gap-2">
            <span className="w-4 h-4 rounded bg-accent/80" />
            agentrig-core
          </span>
          <ChevronDown width={14} height={14} className="text-white/50" />
        </button>
      </div>

      {/* 导航 */}
      <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
        {items.map(({ to, key, Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex items-center gap-2.5 px-2.5 h-8 rounded-lg text-[13px] transition-colors ${
                isActive
                  ? "bg-sidebar-active text-white"
                  : "text-white/70 hover:bg-sidebar-hover hover:text-white"
              }`
            }
          >
            <Icon width={16} height={16} />
            {t(key)}
          </NavLink>
        ))}
      </nav>

      {/* 底部：状态 + 语言切换 */}
      <div className="px-3 py-3 border-t border-white/10 space-y-2">
        <button
          onClick={toggle}
          className="w-full flex items-center justify-between px-2.5 h-7 rounded-lg text-[11px] text-white/70 hover:bg-sidebar-hover"
        >
          <span className="flex items-center gap-1.5">
            <Globe width={14} height={14} />
            {lang === "zh" ? "中文" : "English"}
          </span>
          <span className="text-white/50">{t("lang.toggle")}</span>
        </button>
        <div className="flex items-center justify-between px-2.5 text-[11px] text-white/50">
          <span className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-accent" />
            {t("status.mcp")}
          </span>
        </div>
        <p className="px-2.5 text-[10px] text-white/40">{t("status.local")}</p>
      </div>
    </aside>
  );
}
