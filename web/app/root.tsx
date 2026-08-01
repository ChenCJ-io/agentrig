import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import {
  isRouteErrorResponse,
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
} from "react-router";

import "./styles/tokens.css";
import "./styles/global.css";
import "./styles/components.css";

export const meta = () => [
  { title: "AgentRig" },
  {
    name: "description",
    content: "MCP-native regression testing for AI agents",
  },
];

export const links = () => [
  { rel: "preconnect", href: "https://fonts.googleapis.com" },
  { rel: "preconnect", href: "https://fonts.gstatic.com", crossOrigin: "anonymous" },
  {
    rel: "stylesheet",
    href: "https://fonts.googleapis.com/css2?family=Funnel+Sans:wght@300..800&family=Geist:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap",
  },
];

export function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="theme-color" content="#f1f3f2" />
        <Meta />
        <Links />
      </head>
      <body>
        {children}
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

export default function App() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            staleTime: 30_000,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <Outlet />
    </QueryClientProvider>
  );
}

export function ErrorBoundary({ error }: { error: unknown }) {
  let title = "页面暂时不可用";
  let detail = "发生了未预期的错误，请刷新后重试。";

  if (isRouteErrorResponse(error)) {
    title = error.status === 404 ? "页面不存在" : `${error.status} ${error.statusText}`;
    detail = error.status === 404 ? "当前地址没有对应的工作区。" : detail;
  } else if (error instanceof Error) {
    detail = error.message;
  }

  return (
    <main className="fatal-state">
      <span className="fatal-mark" aria-hidden="true">A</span>
      <p className="eyebrow">AGENTRIG / ERROR</p>
      <h1>{title}</h1>
      <p>{detail}</p>
      <a className="button button--primary" href="/evaluation/overview">
        返回评测总览
      </a>
    </main>
  );
}
