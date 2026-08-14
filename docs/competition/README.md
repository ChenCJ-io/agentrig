# AgentRig GOAI 2026 参赛交付中心

> 赛道：Agent Infra 新智基座
>
> 材料快照：2026-08-14（Asia/Shanghai）
>
> 公开主场景：EditFlow / Agno / DeepSeek
> 扩展验证：lassist 与 AgentScope/AgentTeams 能力台账

本版主叙事不是“让几个 Agent 对话”，而是开发者如何把一次真实 Prompt 修改治理成可复用证据：

```text
Codex + 项目 Skill + AgentRig MCP
  → Case Governance → Before → Prompt Diff → Candidate
  → Real MCP Evidence → Human-approved Sample → Replay
  → Run / Cell / Attempt / Timeline / Decision

普通用户 + AgentRig Web Assistant
  → Natural Language Plan → Confirm → Submit → Same Evidence Model
```

Codex 与 Web Assistant 不要求输出同一方案。AgentRig 提供的是统一的评测资产、工具副作用边界、人工
确认和证据合同，而不是统一不同模型的思考过程。

## 当前硬证据

- Before：同一冻结 Case 5 次为 2 Pass / 3 Behavior Fail；
- Candidate headline：同 Manifest 5/5；Prompt SHA 已变化；
- Candidate matrix：6 Cells / 30 Attempts，30/30；
- Real MCP Capture：1 次；Sample-only Replay：5/5、5 Sample hit、Run 内 real_tool Attempt=0；
- Web Assistant：Plan → confirm → submit → Run，3/3；
- EditFlow：34 non-live tests；Web：typecheck、真实后端 E2E、Axe 0 serious/critical。

详细机器事实见 `editflow-recording-evidence.json`（正式录制）与《EditFlow彩排证据与正式录制台账.md》
（仓库内位于本目录，提交包内位于 `03-运行证据/`）；彩排事实保留在 `editflow-rehearsal-evidence.json`。

## 交付物索引

| 文件 | 用途 |
|---|---|
| [01 作品简介](./01-作品简介.md) | 报名系统 500 字以内正文 |
| [02 Agent Identity](./02-Agent-Identity-清单.md) | 可选 Manager/Curator/Judge 边界 |
| [03 16 页 PPT 讲稿](./03-初赛方案PPT-讲稿.md) | 完整陈述与删减基线 |
| [04 Demo 演示脚本](./04-Demo演示脚本.md) | Codex 主流程与 Web 辅助流程 |
| [05 FAQ](./05-评审映射与答辩FAQ.md) | 真实性、AgentScope、Mock、差异规划答辩 |
| [06 检查清单](./06-提交与开源检查清单.md) | 录制、开源、媒体和提交门禁 |
| [07 真实证据报告](./07-真实运行证据报告.md) | EditFlow 正式录制权威证据 |
| [08 Skill 清单](./08-Skill-清单.md) | AgentRig 11 个 Skill 合同 |
| [09 提交表单](./09-初赛提交表单.md) | 可复制字段与待人工项 |
| [10 视频分镜与旁白](./10-Demo视频分镜与旁白.md) | 7:20 正式录制母版与 4 分钟减法 |
| [11 V2.3 台账](./11-V2.3优化成果与验收台账.md) | 平台完整能力与 Pending 边界 |
| [12 lassist 附录](./12-lassist真实闭环验收.md) | 生产形态兼容证据，非公开主视频 |
| [13 Codex + Skill + MCP](./13-Codex-Skill-MCP真实评测.md) | 开发者入口的真实工作流 |
| [14 音视频规范](./14-音视频与录制质量规范.md) | 稳定画面与自然声音标准 |
| `AgentRig-GOAI-2026-初赛方案.pptx/.pdf` | 16 页 Review 版方案 |
| `dist/competition/media/AgentRig-GOAI-2026-Demo.*` | 9:03 正式录制合成版 MP4/SRT/JSON（画面与 ID 来自干净录制库，旁白为合成音） |

内部工作文档（仅在仓库内维护，不进入提交包的 `01-报名材料/`）：

- [15 Demo 方案](./15-Codex主导脱敏Demo演示方案-待拍板.md)——已拍板架构与剩余动作；
- [16 正式录制剧本](./16-EditFlow-Codex-AgentRig正式录制剧本-待Review.md)——完整逐秒剧本、预案和 ledger；
- [17 证据台账](./17-EditFlow彩排证据与正式录制台账.md)——彩排 ID 与正式 ID 分离，随包发布于 `03-运行证据/`。

## 平台优势

1. 保留真实模型、协议、Session、工具选择，控制昂贵副作用；
2. Prompt SHA、Capability Snapshot、Canonical Manifest 保证身份可比；
3. Cell 与独立 Attempt 暴露模型方差，不用单次成功掩盖回归；
4. Rule/Judge 与生命周期解耦，`completed` 不等于 `pass`；
5. Real Tool 证据可治理成 Sample，并保留人工审核；
6. Codex、Web、CLI/CI 共用事实内核，但允许各自合理规划；
7. Driver/Provider/Evaluator/Gate 可替换，适配不同框架和风险；
8. EditFlow 可公开复现，lassist 证明可接入真实复杂 Agent。

## 可重复构建

```bash
uv run --with python-pptx python scripts/build_competition_deck.py
node web/scripts/render-competition-deck.mjs
uv run --with imageio-ffmpeg --with edge-tts python scripts/build_competition_video.py --engine macos
uv build
uv run python scripts/build_competition_submission.py
```

正式录制证据、正式截图与合成版视频均已生成；在干净 commit 上重建后 builder 自动输出 FINAL/CLEAN 包。
团队字段、仓库公开与平台限制核对由参赛人完成。凭据、Cookie、本地数据库、私有图片和模型请求头不进入
交付物。
