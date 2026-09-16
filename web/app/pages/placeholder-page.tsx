import { Construction, MoveRight } from "lucide-react";
import { Link } from "react-router";

import { PageHeader } from "~/components/ui/page-header";
import { Panel } from "~/components/ui/panel";

export function PlaceholderPage({ pathname: _pathname }: { pathname: string }) {
  return (
    <div className="workspace workspace--centered">
      <PageHeader eyebrow="AGENTRIG / V1" title="AgentRig 工作区" description="该模块尚未接入。" />
      <Panel className="placeholder-panel">
        <Construction size={22} aria-hidden="true" />
        <div>
          <h2>当前路径不属于 V1 控制台</h2>
          <p>请从评测总览进入用例、运行、Target、Profile 或 Sample 页面。</p>
        </div>
        <Link className="text-link" to="/evaluation/overview">
          返回评测总览 <MoveRight size={14} />
        </Link>
      </Panel>
    </div>
  );
}
