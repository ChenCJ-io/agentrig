import { lazy, Suspense } from "react";
import { useLocation } from "react-router";

import { PlaceholderPage } from "~/pages/placeholder-page";
import { uiFeatures } from "~/config/ui-features";

const GovernancePage = lazy(() => import("~/pages/governance/governance-page").then((module) => ({ default: module.GovernancePage })));
const ProductPage = lazy(() => import("~/pages/product/product-page").then((module) => ({ default: module.ProductPage })));
const V1ConsolePage = lazy(() => import("~/pages/v1/v1-console-page").then((module) => ({ default: module.V1ConsolePage })));
const AssistantPage = lazy(() => import("~/pages/v2/assistant-page").then((module) => ({ default: module.AssistantPage })));
const AssetsPage = lazy(() => import("~/pages/assets/assets-page").then((module) => ({ default: module.AssetsPage })));
const EvaluationPage = lazy(() => import("~/pages/evaluations/evaluation-page").then((module) => ({ default: module.EvaluationPage })));
const TargetOverviewPage = lazy(() => import("~/pages/targets/target-overview-page").then((module) => ({ default: module.TargetOverviewPage })));

// AgentRig 只保留评测模块；其余路径走占位页
export function WorkspaceRouter() {
  const location = useLocation();
  const pathname = location.pathname;
  const overviewMatch = pathname.match(/^\/targets\/([^/]+)\/overview$/);
  if (overviewMatch?.[1] && uiFeatures.overviewV2) {
    return renderPage(<TargetOverviewPage targetId={decodeURIComponent(overviewMatch[1])} />);
  }
  const assistantMatch = pathname.match(/^\/targets\/([^/]+)\/assistant(?:\/|$)/);
  if (assistantMatch?.[1] && uiFeatures.assistantV2) {
    return renderPage(<AssistantPage />);
  }
  const evaluationMatch = pathname.match(/^\/targets\/([^/]+)\/evaluation\/runs(?:\/|$)/);
  if (evaluationMatch?.[1] && uiFeatures.evaluationV2) {
    return renderPage(<EvaluationPage targetId={decodeURIComponent(evaluationMatch[1])} />);
  }
  const assetsMatch = pathname.match(/^\/targets\/([^/]+)\/(assets(?:\/|$)|evaluation\/(?:test-cases|case-review)$)/);
  if (assetsMatch?.[1] && uiFeatures.assetsV2) {
    return renderPage(<AssetsPage pathname={pathname} targetId={decodeURIComponent(assetsMatch[1])} />);
  }

  if (
    pathname.startsWith("/targets") ||
    pathname.startsWith("/evaluator-teams") ||
    pathname.startsWith("/audit") ||
    pathname.startsWith("/settings")
  ) return renderPage(<ProductPage pathname={pathname} />);
  if (
    pathname.startsWith("/production") ||
    pathname.startsWith("/reviews") ||
    pathname.startsWith("/failure-patterns") ||
    pathname.startsWith("/jobs")
  ) return renderPage(<GovernancePage pathname={pathname} />);
  if (pathname.startsWith("/assistant")) return renderPage(<AssistantPage />);
  if (pathname.startsWith("/evaluation")) return renderPage(<V1ConsolePage pathname={pathname} />);
  return <PlaceholderPage pathname={pathname} />;
}

function renderPage(page: React.ReactNode) {
  return <Suspense fallback={<div aria-live="polite" className="workspace-loading">正在加载工作区…</div>}>{page}</Suspense>;
}
