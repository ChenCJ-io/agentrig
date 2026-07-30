import { Bell, ChevronDown, CircleHelp, LogOut, X } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router";

import { getShellContext, isNavigationActive } from "./navigation";

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const pathname = location.pathname;
  const context = useMemo(() => getShellContext(pathname), [pathname]);
  const ContextIcon = context.icon;
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [shellNotice, setShellNotice] = useState<string | null>(null);

  function showHelpStatus() {
    setUserMenuOpen(false);
    setShellNotice("帮助与反馈通道尚未接入；当前未提交任何反馈。");
  }

  function handleLogout() {
    const hadLocalToken = Boolean(window.localStorage.getItem("auth_token"));
    if (hadLocalToken) {
      window.localStorage.removeItem("auth_token");
    }
    setUserMenuOpen(false);
    setShellNotice(
      hadLocalToken
        ? "本地访问令牌已清除。"
        : "当前没有本地访问令牌。",
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="topbar__brand" to="/evaluation/overview" aria-label="AgentRig 评测控制台">
          <span className="topbar__brand-mark" aria-hidden="true">A</span>
          <span>AgentRig</span>
        </Link>
        <div className="topbar__context">
          <div className="topbar__title-group">
            <span className={`topbar__context-icon topbar__context-icon--${context.area}`} aria-hidden="true">
              <ContextIcon size={15} />
            </span>
            <span className="topbar__copy">
              <strong>{context.title}</strong>
              <small>{context.subtitle}</small>
            </span>
          </div>
          <div className="topbar__utilities">
            <div className="runtime-state" title="当前控制台">
              <span>V1 控制台</span>
              <i aria-hidden="true" />
              <strong>local</strong>
            </div>
            <span className="topbar__divider" aria-hidden="true" />
            <div className="notification-menu">
              <button
                className="icon-button"
                type="button"
                aria-label="通知"
                title="通知"
                aria-expanded={notificationOpen}
                aria-controls="shell-notification-panel"
                onClick={() => {
                  setNotificationOpen((open) => !open);
                  setUserMenuOpen(false);
                }}
              >
                <Bell size={15} />
              </button>
              {notificationOpen ? (
                <section id="shell-notification-panel" className="notification-menu__popover" role="dialog" aria-labelledby="shell-notification-title">
                  <header>
                    <strong id="shell-notification-title">通知</strong>
                    <button type="button" onClick={() => setNotificationOpen(false)} aria-label="关闭通知" title="关闭通知">
                      <X size={13} />
                    </button>
                  </header>
                  <p>通知服务尚未接入，当前没有可读取的通知数据。</p>
                </section>
              ) : null}
            </div>
            <div className="user-menu">
              <button
                className="user-menu__trigger"
                type="button"
                aria-label="用户菜单"
                aria-expanded={userMenuOpen}
                aria-haspopup="menu"
                onClick={() => {
                  setUserMenuOpen((open) => !open);
                  setNotificationOpen(false);
                }}
              >
                <span className="user-menu__avatar">A</span>
                <span>AgentRig</span>
                <ChevronDown size={13} />
              </button>
              {userMenuOpen ? (
                <div className="user-menu__popover" role="menu">
                  <button role="menuitem" type="button" onClick={showHelpStatus}>
                    <CircleHelp size={14} /> 帮助与反馈
                  </button>
                  <button role="menuitem" type="button" onClick={handleLogout}>
                    <LogOut size={14} /> 清除本地令牌
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </header>

      {shellNotice ? (
        <div className="shell-action-feedback" role="status" aria-live="polite">
          <span>{shellNotice}</span>
          <button type="button" onClick={() => setShellNotice(null)} aria-label="关闭状态提示" title="关闭状态提示">
            <X size={13} />
          </button>
        </div>
      ) : null}

      <div className="app-shell__body">
        <aside className="sidebar">
          <div className="sidebar__top">
            <div className="sidebar__scope">
              <span>{context.eyebrow}</span>
              <small>{context.code}</small>
            </div>
            <nav className="sidebar__navigation" aria-label="主导航">
              {context.groups.map((group, groupIndex) => (
                <div className="sidebar__group" key={group.label ?? groupIndex}>
                  {group.label ? <p>{group.label}</p> : null}
                  <div className="sidebar__links">
                    {group.items.map((item, itemIndex) => {
                      const active = isNavigationActive(item, pathname);
                      const ItemIcon = item.icon;
                      return (
                        <Link className={`sidebar-link ${active ? "is-active" : ""}`} to={item.path} key={item.path}>
                          <span className="sidebar-link__rail" aria-hidden="true" />
                          {group.label ? <em>{String(itemIndex + 1).padStart(2, "0")}</em> : <ItemIcon size={16} />}
                          <span>{item.label}</span>
                        </Link>
                      );
                    })}
                  </div>
                </div>
              ))}
            </nav>
          </div>

          <div className="sidebar__footer">
            <Link className="sidebar__utility-link" to="/evaluation/overview">
              <ContextIcon size={15} />
              <span>返回评测总览</span>
            </Link>
          </div>
        </aside>
        <main className="app-canvas" id="main-content">
          {children}
        </main>
      </div>
    </div>
  );
}
