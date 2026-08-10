# AgentRig GOAI 2026 参赛交付中心

> 赛道：Agent Infra 新智基座
>
> 规则快照：2026-08-10
>
> 项目版本：AgentRig `0.2.0a0` / AgentTeams `v1.1.2`

本目录把比赛材料与产品设计文档分开管理。内容依据
[GOAI Agent Infra 赛道要求](https://www.goaihz.com/tracks?track=infra)整理；官网或组委会
通知变化时，以最新官方口径为准。

## 交付物

| 文件 | 用途 | 状态 |
|---|---|---|
| [01-作品简介](./01-作品简介.md) | 初赛提交框的 500 字以内作品介绍 | 可提交 |
| [02-Agent-Identity-清单](./02-Agent-Identity-清单.md) | 三个 Agent 的身份、边界与协同关系 | 可提交 |
| [03-初赛方案PPT-讲稿](./03-初赛方案PPT-讲稿.md) | 方案 PPT 的逐页内容与讲解重点 | 可提交 |
| [04-Demo演示脚本](./04-Demo演示脚本.md) | 成功、失败、安全恢复三段式现场演示 | 可执行 |
| [05-评审映射与答辩FAQ](./05-评审映射与答辩FAQ.md) | 评分项证据索引和答辩口径 | 可使用 |
| [06-提交与开源检查清单](./06-提交与开源检查清单.md) | 初赛、复赛、决赛交付前检查 | 持续更新 |
| [07-真实运行证据报告](./07-真实运行证据报告.md) | 成功、失败、超时恢复和 Worker 证据 | 已实测 |
| [08-Skill 清单](./08-Skill-清单.md) | 对齐官方附录 B 的 11 个 Skill 工程合同 | 可提交 |
| [09-初赛提交表单](./09-初赛提交表单.md) | 报名系统可复制字段、文件与待确认信息 | 待真实团队信息 |
| [10-Demo 视频分镜与旁白](./10-Demo视频分镜与旁白.md) | 6:55 成片的分镜、旁白、字幕与验收口径 | 已完成 |
| [界面截图](./assets/agentrig-assistant.png) | 真实助手、计划与 Worker 证据视图 | 已生成 |
| [初赛方案 PDF](./AgentRig-GOAI-2026-初赛方案.pdf) | 15 页、16:9 的最终提交方案 | 已生成 |
| [初赛方案 PPTX](./AgentRig-GOAI-2026-初赛方案.pptx) | 可编辑的方案源文件 | 已生成 |

最终提交 ZIP、6:55 H.264/AAC 视频、SRT 字幕、工程包和校验报告生成在被 Git 忽略的
`dist/competition/GOAI-2026-AgentRig-初赛材料/`，避免把大体积交付物和本机封装目录写入源码
历史。提交包内置 `SHA256SUMS`，外层 ZIP 另附 SHA-256 文件。

PPT 可重复构建：

```bash
uv run --with python-pptx python scripts/build_competition_deck.py
```

视频可在 macOS 上用真实 UI 取证帧、方案 PDF、系统旁白和硬字幕重复构建：

```bash
uv run --with imageio-ffmpeg python scripts/build_competition_video.py
```

最新会话的脱敏机器可读证据可重复导出：

```bash
uv run python scripts/export_competition_evidence.py
```

## 一句话定位

AgentRig 是面向企业 AI Agent 的多 Agent 可审计评测基础设施：用户只需描述评测目标，
AgentTeams Manager 形成受控计划，Simulation Curator 提供隔离的工具结果，Evidence Judge
基于不可变证据裁决，AgentRig Core 保存可复现、可追溯、可回归的事实链。

## 当前可验证证据

- 一键入口：`scripts/local_demo.sh setup`；
- Demo 页面：`http://127.0.0.1:8010/assistant`；
- 三个 AgentTeams 身份、两个 Worker、三个角色隔离 MCP route；
- 成功闭环：真实 lassist、Curator、Judge、Rule 3/3 和 Matrix 双向 event ID；
- 失败闭环：二次确认安全门禁由 Rule 2/3 与 Judge 基于同一工具事件判 fail；
- 恢复证据：超时 Run 保留既有事件与 Rule，不伪造尚未发生的 Judge 结论；
- 安全边界：计划确认、角色权限、脱敏、幂等、取消、降级和不可变快照；
- 自动化：后端、静态检查、Web 构建与真实 lassist 协议测试。

## 当前质量快照

- 方案：15 页 PPTX/PDF，PDF 无加密、无 JavaScript；
- 视频：6:55、1920×1080、H.264 High、AAC-LC，76 条无重叠字幕；
- 测试：134 passed、6 skipped；Ruff、Mypy、Web typecheck/E2E/build 通过；
- 安全：Git 历史、源码包、提交目录和最终 ZIP 的 Gitleaks 扫描均为 0 命中；
- 封装：ZIP 完整性和包内 `SHA256SUMS` 校验通过。

上述数字对应 2026-08-10 的参赛封装快照；持续开发时以最新 CI 和重新生成的验证报告为准。

真实凭据、本地数据库、Matrix token 和运行 Cookie 不属于提交包。
