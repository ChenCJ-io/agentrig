import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Cable,
  CheckCircle2,
  ClipboardCopy,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";

import {
  createIngestSource,
  listProductionTraces,
  listProjects,
  type IngestSourceIssue,
} from "~/api/governance";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";

import governanceStyles from "./governance-page.module.css";
import styles from "./onboarding-page.module.css";

type Lane = "env" | "python" | "script" | "client" | "curl";
type Mode = "otlp" | "gateway";

export function OnboardingPage() {
  const projects = useQuery({ queryKey: ["governance", "projects"], queryFn: listProjects });
  const [projectId, setProjectId] = useState("default");
  const [name, setName] = useState("my-agent");
  const [serviceNames, setServiceNames] = useState("my-agent");
  const [savePreviews, setSavePreviews] = useState(true);
  const [mode, setMode] = useState<Mode>("otlp");
  const [upstreamUrl, setUpstreamUrl] = useState("https://api.deepseek.com/v1");
  const [upstreamEnv, setUpstreamEnv] = useState("UPSTREAM_API_KEY");
  const [issue, setIssue] = useState<IngestSourceIssue | null>(null);
  const [lane, setLane] = useState<Lane>("env");
  const [copied, setCopied] = useState(false);

  const create = useMutation({
    mutationFn: () =>
      createIngestSource(projectId, {
        name: name.trim() || "my-agent",
        source_type: mode === "gateway" ? "openai_gateway" : "otlp_http",
        allowed_service_names: serviceNames
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        enabled: true,
        retention_days: 30,
        redaction_policy: {
          save_input_preview: savePreviews,
          save_output_preview: savePreviews,
        },
        ...(mode === "gateway"
          ? {
              gateway: {
                upstream_base_url: upstreamUrl.trim(),
                upstream_secret_ref: `env:${upstreamEnv.trim()}`,
              },
            }
          : {}),
      }),
    onSuccess: (created) => {
      setIssue(created);
      setLane(mode === "gateway" ? "client" : "env");
    },
  });

  const firstTrace = useQuery({
    queryKey: ["onboarding", projectId, "first-trace", issue?.source.id],
    queryFn: () => listProductionTraces(projectId),
    enabled: Boolean(issue),
    refetchInterval: 3_000,
  });
  const received = Boolean(
    issue &&
      firstTrace.data?.items.some((item) => item.source_id === issue.source.id),
  );

  const origin =
    typeof window === "undefined" ? "http://127.0.0.1:8000" : window.location.origin;
  const snippet = useMemo(
    () => buildSnippet(lane, origin, projectId, issue),
    [issue, lane, origin, projectId],
  );
  const laneTabs: ReadonlyArray<readonly [Lane, string]> =
    mode === "gateway"
      ? ([
          ["client", "OpenAI 客户端"],
          ["curl", "curl 测试"],
        ] as const)
      : ([
          ["env", "OTel 环境变量"],
          ["python", "Python 代码"],
          ["script", "快速验证脚本"],
        ] as const);

  return (
    <div className={governanceStyles.workspace}>
      <header className={governanceStyles.pageHeader}>
        <div>
          <span className="eyebrow">接入向导 · 生产 Trace</span>
          <h1>把线上 LLM 调用接入 AgentRig</h1>
          <p>三步完成：创建接入源、配置上报、等待第一条 trace 点亮。</p>
        </div>
        <label className={governanceStyles.projectPicker}>
          <span>当前 Project</span>
          <select
            aria-label="当前 Project"
            onChange={(event) => setProjectId(event.target.value)}
            value={projectId}
          >
            {(projects.data?.items ?? [{ id: "default", name: "default" }]).map(
              (project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ),
            )}
          </select>
          <small>数据按 Project 隔离</small>
        </label>
      </header>

      <section className={styles.step}>
        <header>
          <span className={styles.stepIndex}>1</span>
          <div>
            <strong>创建接入源</strong>
            <p>每个应用一个接入源，独立 token，可随时停用。</p>
          </div>
        </header>
        {!issue ? (
          <div className={styles.laneTabs} role="radiogroup">
            {(
              [
                ["otlp", "OTel 上报（生产推荐）"],
                ["gateway", "网关代理（改 base_url 即接入）"],
              ] as const
            ).map(([value, label]) => (
              <button
                aria-checked={mode === value}
                key={value}
                onClick={() => setMode(value)}
                role="radio"
                type="button"
              >
                {label}
              </button>
            ))}
          </div>
        ) : null}
        {issue ? (
          <div className={styles.tokenPanel}>
            <div>
              <Badge tone="success">已创建</Badge>
              <code>{issue.source.id}</code>
            </div>
            <p className={styles.tokenWarning}>
              <ShieldCheck size={13} /> token 只显示这一次，请立即保存；丢失后需要重新创建接入源。
            </p>
            <pre className={styles.tokenValue}>
              <code>{issue.token}</code>
            </pre>
          </div>
        ) : (
          <form
            className={styles.sourceForm}
            onSubmit={(event) => {
              event.preventDefault();
              create.mutate();
            }}
          >
            <label>
              <span>接入源名称</span>
              <input
                onChange={(event) => setName(event.target.value)}
                value={name}
              />
            </label>
            <label>
              <span>允许的 service.name（逗号分隔）</span>
              <input
                onChange={(event) => setServiceNames(event.target.value)}
                value={serviceNames}
              />
            </label>
            {mode === "gateway" ? (
              <>
                <label>
                  <span>上游 base_url（OpenAI 兼容）</span>
                  <input
                    onChange={(event) => setUpstreamUrl(event.target.value)}
                    value={upstreamUrl}
                  />
                </label>
                <label>
                  <span>上游 key 的环境变量名（须在 AgentRig 服务端设置）</span>
                  <input
                    onChange={(event) => setUpstreamEnv(event.target.value)}
                    value={upstreamEnv}
                  />
                </label>
              </>
            ) : null}
            <label className={styles.toggleRow}>
              <input
                checked={savePreviews}
                onChange={(event) => setSavePreviews(event.target.checked)}
                type="checkbox"
              />
              <span>保存脱敏后的输入输出预览（开发环境建议开启）</span>
            </label>
            <Button disabled={create.isPending} icon={<Cable />} type="submit">
              创建并签发 token
            </Button>
            {create.error ? (
              <p className={styles.formError}>
                {create.error instanceof Error
                  ? create.error.message
                  : String(create.error)}
              </p>
            ) : null}
          </form>
        )}
      </section>

      <section className={styles.step}>
        <header>
          <span className={styles.stepIndex}>2</span>
          <div>
            <strong>配置上报</strong>
            <p>
              OTel 上报只需设置环境变量；网关代理只需把客户端 base_url 改到 AgentRig。
            </p>
          </div>
        </header>
        <div className={styles.laneTabs} role="tablist">
          {laneTabs.map(([value, label]) => (
            <button
              aria-selected={lane === value}
              key={value}
              onClick={() => setLane(value)}
              role="tab"
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
        <div className={styles.snippet}>
          <pre>
            <code>{snippet}</code>
          </pre>
          <Button
            disabled={!issue}
            icon={<ClipboardCopy />}
            onClick={() => {
              void navigator.clipboard.writeText(snippet);
              setCopied(true);
              setTimeout(() => setCopied(false), 1_500);
            }}
            type="button"
          >
            {copied ? "已复制" : "复制"}
          </Button>
        </div>
        {!issue ? (
          <p className={styles.snippetHint}>创建接入源后，代码片段会自动填入真实的 token 与 ID。</p>
        ) : null}
      </section>

      <section className={styles.step}>
        <header>
          <span className={styles.stepIndex}>3</span>
          <div>
            <strong>等待第一条 trace</strong>
            <p>发送任意一次请求后，这里会自动点亮。</p>
          </div>
        </header>
        <div
          className={`${styles.liveCheck} ${received ? styles.liveCheckOk : ""}`}
          role="status"
        >
          {received ? (
            <>
              <CheckCircle2 size={16} />
              <span>已收到第一条 trace，接入完成。</span>
              <Link to="/production">查看生产证据 →</Link>
            </>
          ) : issue ? (
            <>
              <LoaderCircle className={styles.spin} size={16} />
              <span>正在等待第一条 trace…（每 3 秒自动检查）</span>
            </>
          ) : (
            <span>先完成第 1 步。</span>
          )}
        </div>
      </section>
    </div>
  );
}

function buildSnippet(
  lane: Lane,
  origin: string,
  projectId: string,
  issue: IngestSourceIssue | null,
): string {
  const sourceId = issue?.source.id ?? "<source_id>";
  const token = issue?.token ?? "<ingest_token>";
  if (lane === "env") {
    return [
      `export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="${origin}/v1/traces"`,
      `export OTEL_EXPORTER_OTLP_TRACES_HEADERS="authorization=Bearer ${token},x-agentrig-project=${projectId},x-agentrig-source=${sourceId}"`,
      "",
      "# 之后正常启动你的应用即可；OpenLLMetry / OpenInference / 框架自带埋点",
      "# 都会通过标准 OTLP exporter 把 trace 发到 AgentRig。",
    ].join("\n");
  }
  if (lane === "python") {
    return [
      "from opentelemetry.sdk.resources import Resource",
      "from opentelemetry.sdk.trace import TracerProvider",
      "from opentelemetry.sdk.trace.export import BatchSpanProcessor",
      "from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter",
      "",
      'provider = TracerProvider(resource=Resource.create({"service.name": "my-agent"}))',
      "provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(",
      `    endpoint="${origin}/v1/traces",`,
      "    headers={",
      `        "Authorization": "Bearer ${token}",`,
      `        "X-AgentRig-Project": "${projectId}",`,
      `        "X-AgentRig-Source": "${sourceId}",`,
      "    },",
      ")))",
    ].join("\n");
  }
  if (lane === "client") {
    return [
      "from openai import OpenAI",
      "",
      "client = OpenAI(",
      `    base_url="${origin}/gateway/${sourceId}/v1",`,
      `    api_key="${token}",`,
      ")",
      "",
      "# 之后照常调用；请求会被转发到配置的上游，",
      "# 每次调用自动记录为一条生产 trace。",
    ].join("\n");
  }
  if (lane === "curl") {
    return [
      `curl -s ${origin}/gateway/${sourceId}/v1/chat/completions \\`,
      `  -H "Authorization: Bearer ${token}" \\`,
      '  -H "Content-Type: application/json" \\',
      `  -d '{"model": "your-model", "messages": [{"role": "user", "content": "你好"}]}'`,
    ].join("\n");
  }
  return [
    "uv run python scripts/send_demo_traces.py \\",
    `    --endpoint ${origin}/v1/traces \\`,
    `    --project ${projectId} --source ${sourceId} --token ${token}`,
  ].join("\n");
}
