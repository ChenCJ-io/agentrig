import { useLocation } from "react-router";

import { PlaceholderPage } from "~/pages/placeholder-page";
import { V1ConsolePage } from "~/pages/v1/v1-console-page";

// AgentRig 只保留评测模块；其余路径走占位页
export function WorkspaceRouter() {
  const location = useLocation();
  const pathname = location.pathname;

  if (pathname.startsWith("/evaluation")) return <V1ConsolePage pathname={pathname} />;
  return <PlaceholderPage pathname={pathname} />;
}
