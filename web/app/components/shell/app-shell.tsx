import { Bell, ChevronDown, CircleHelp, KeyRound, LogOut, X } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation } from "react-router";

import {
  authRequiredEvent,
  clearAuthToken,
  hasStoredAuthToken,
  storeAuthToken,
} from "~/api/client";

import { getShellContext, isNavigationActive } from "./navigation";

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const pathname = location.pathname;
  const context = useMemo(() => getShellContext(pathname), [pathname]);
  const ContextIcon = context.icon;
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [shellNotice, setShellNotice] = useState<string | null>(null);
  const [authDialogOpen, setAuthDialogOpen] = useState(false);
  const [accessToken, setAccessToken] = useState("");
  const [hasLocalToken, setHasLocalToken] = useState(false);

  useEffect(() => {
    setHasLocalToken(hasStoredAuthToken());
    const requireAuth = () => {
      setAccessToken("");
      setAuthDialogOpen(true);
    };
    window.addEventListener(authRequiredEvent, requireAuth);
    return () => window.removeEventListener(authRequiredEvent, requireAuth);
  }, []);

  function showHelpStatus() {
    setUserMenuOpen(false);
    setShellNotice("帮助与反馈通道尚未接入；当前未提交任何反馈。");
  }

  function handleLogout() {
    const hadLocalToken = hasStoredAuthToken();
    if (hadLocalToken) {
      clearAuthToken();
    }
    setUserMenuOpen(false);
    setHasLocalToken(false);
    if (hadLocalToken) {
      window.location.reload();
      return;
    }
    setShellNotice("当前没有本地访问令牌。");
  }

  function openAuthDialog() {
    setUserMenuOpen(false);
    setNotificationOpen(false);
    setAccessToken("");
    setAuthDialogOpen(true);
  }

  function saveAccessToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = accessToken.trim();
    if (!token) return;
    storeAuthToken(token);
    setHasLocalToken(true);
    setAuthDialogOpen(false);
    window.location.reload();
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
              <span>{pathname.startsWith("/assistant") ? "V2 协作模式" : "V1 控制台"}</span>
              <i aria-hidden="true" />
              <strong>{pathname.startsWith("/assistant") ? "AgentTeams" : "local"}</strong>
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
                  <button role="menuitem" type="button" onClick={openAuthDialog}>
                    <KeyRound size={14} />
                    {hasLocalToken ? "更新访问令牌" : "设置访问令牌"}
                  </button>
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

      {authDialogOpen ? (
        <div className="auth-dialog-backdrop" role="presentation">
          <section
            aria-labelledby="auth-dialog-title"
            aria-modal="true"
            className="auth-dialog"
            role="dialog"
          >
            <header>
              <div>
                <span>ACCESS CONTROL</span>
                <strong id="auth-dialog-title">设置访问令牌</strong>
              </div>
              <button
                aria-label="关闭访问令牌对话框"
                onClick={() => setAuthDialogOpen(false)}
                title="关闭"
                type="button"
              >
                <X size={15} />
              </button>
            </header>
            <form onSubmit={saveAccessToken}>
              <p>
                当前 AgentRig 服务要求 Bearer Token。令牌仅保存在这个浏览器的本地存储中，
                后续 API 请求会自动携带。
              </p>
              <label htmlFor="agentrig-access-token">访问令牌</label>
              <input
                autoComplete="off"
                autoFocus
                id="agentrig-access-token"
                onChange={(event) => setAccessToken(event.target.value)}
                placeholder={hasLocalToken ? "输入新的令牌" : "输入服务访问令牌"}
                type="password"
                value={accessToken}
              />
              <footer>
                <button
                  className="button button--quiet"
                  onClick={() => setAuthDialogOpen(false)}
                  type="button"
                >
                  取消
                </button>
                <button
                  className="button button--primary"
                  disabled={!accessToken.trim()}
                  type="submit"
                >
                  保存并重新加载
                </button>
              </footer>
            </form>
          </section>
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
