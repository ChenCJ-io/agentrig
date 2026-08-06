"""Build the editable GOAI 2026 AgentRig proposal deck."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/competition/AgentRig-GOAI-2026-初赛方案.pptx"
SCREENSHOT = ROOT / "docs/competition/assets/agentrig-assistant.png"

INK = "151719"
GRAPHITE = "252927"
MUTED = "59615D"
FAINT = "737B77"
CANVAS = "F1F3F2"
SURFACE = "F7F8F7"
WHITE = "FFFFFF"
LINE = "D7DDD9"
COBALT = "2457F5"
COBALT_SOFT = "E9EEFF"
GREEN = "237A59"
GREEN_SOFT = "E8F5EF"
AMBER = "955900"
AMBER_SOFT = "FFF4D8"
CORAL = "B8403A"
CORAL_SOFT = "FCEBEA"


def rgb(value: str) -> RGBColor:
    return RGBColor.from_string(value)


def rect(slide, x, y, w, h, *, fill=WHITE, line=LINE, radius=False):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        Inches(x),
        Inches(y),
        Inches(w),
        Inches(h),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    shape.line.color.rgb = rgb(line)
    shape.line.width = Pt(0.7)
    if radius:
        shape.adjustments[0] = 0.08
    return shape


def text(
    slide,
    value: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    size: float = 16,
    color: str = GRAPHITE,
    bold: bool = False,
    font: str = "PingFang SC",
    align=PP_ALIGN.LEFT,
    valign=MSO_ANCHOR.TOP,
    margin: float = 0,
):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.clear()
    frame.margin_left = frame.margin_right = Inches(margin)
    frame.margin_top = frame.margin_bottom = Inches(margin)
    frame.vertical_anchor = valign
    paragraph = frame.paragraphs[0]
    paragraph.alignment = align
    paragraph.space_after = Pt(0)
    paragraph.line_spacing = 1.08
    run = paragraph.add_run()
    run.text = value
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = rgb(color)
    return box


def rich_lines(
    slide,
    values: Iterable[str],
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    size: float = 13,
    color: str = GRAPHITE,
    bullet: bool = True,
    gap: float = 7,
):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(0)
    frame.margin_top = frame.margin_bottom = Inches(0)
    for index, value in enumerate(values):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = f"•  {value}" if bullet else value
        paragraph.font.name = "PingFang SC"
        paragraph.font.size = Pt(size)
        paragraph.font.color.rgb = rgb(color)
        paragraph.space_after = Pt(gap)
        paragraph.line_spacing = 1.15
    return box


def line(slide, x1, y1, x2, y2, *, color=LINE, width=1.0):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(x1),
        Inches(y1),
        Inches(max(0.01, x2 - x1)),
        Inches(max(0.01, y2 - y1)),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(color)
    shape.line.fill.background()
    if y2 - y1 <= 0.02:
        shape.height = Pt(width)
    if x2 - x1 <= 0.02:
        shape.width = Pt(width)
    return shape


def pill(slide, value, x, y, w, *, fill=COBALT_SOFT, color=COBALT, line_color=None):
    rect(slide, x, y, w, 0.3, fill=fill, line=line_color or fill, radius=True)
    text(
        slide,
        value,
        x,
        y + 0.01,
        w,
        0.26,
        size=8,
        color=color,
        bold=True,
        font="IBM Plex Mono",
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
    )


def base_slide(prs: Presentation, index: int, kicker: str, title_value: str, subtitle: str = ""):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    background = slide.background.fill
    background.solid()
    background.fore_color.rgb = rgb(CANVAS)
    rect(slide, 0, 0, 0.12, 7.5, fill=COBALT, line=COBALT)
    text(
        slide, kicker, 0.55, 0.38, 6.4, 0.24, size=8, color=COBALT, bold=True, font="IBM Plex Mono"
    )
    text(slide, title_value, 0.55, 0.72, 11.9, 0.55, size=25, color=INK, bold=True)
    if subtitle:
        text(slide, subtitle, 0.57, 1.29, 11.8, 0.35, size=10, color=MUTED)
    line(slide, 0.55, 1.72, 12.8, 1.73)
    text(
        slide,
        f"AGENTRIG / GOAI 2026                                      {index:02d} / 12",
        0.55,
        7.18,
        12.1,
        0.18,
        size=7,
        color=FAINT,
        font="IBM Plex Mono",
    )
    return slide


def card_title(slide, number, title_value, description, x, y, w, h, *, accent=COBALT):
    rect(slide, x, y, w, h, fill=WHITE, line=LINE)
    rect(slide, x, y, 0.05, h, fill=accent, line=accent)
    text(
        slide,
        number,
        x + 0.18,
        y + 0.17,
        0.4,
        0.25,
        size=8,
        color=accent,
        bold=True,
        font="IBM Plex Mono",
    )
    text(slide, title_value, x + 0.18, y + 0.5, w - 0.35, 0.35, size=14, color=INK, bold=True)
    text(slide, description, x + 0.18, y + 0.98, w - 0.35, h - 1.1, size=9.5, color=MUTED)


def build() -> Presentation:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # 01 cover
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = rgb(INK)
    rect(slide, 0.6, 0.55, 0.54, 0.54, fill=COBALT, line=COBALT)
    text(
        slide,
        "A",
        0.6,
        0.57,
        0.54,
        0.5,
        size=19,
        color=WHITE,
        bold=True,
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
    )
    text(
        slide,
        "AGENTRIG",
        1.34,
        0.72,
        2.2,
        0.26,
        size=10,
        color=WHITE,
        bold=True,
        font="IBM Plex Mono",
    )
    pill(
        slide,
        "GOAI 2026 · AGENT INFRA",
        9.75,
        0.67,
        2.75,
        fill="252927",
        color="BFC5C1",
        line_color="343936",
    )
    text(
        slide,
        "让企业 Agent 的每次变化\n都有证据",
        0.65,
        2.02,
        8.9,
        1.55,
        size=37,
        color=WHITE,
        bold=True,
    )
    text(slide, "多 Agent 可审计评测基础设施", 0.68, 3.8, 6.4, 0.42, size=18, color="BFC5C1")
    text(
        slide,
        "AgentTeams 负责协作，AgentRig 负责事实、验证与审计。",
        0.68,
        4.45,
        7.6,
        0.32,
        size=12,
        color="8E9691",
    )
    for value, x, width in [
        ("AGENTTEAMS", 0.68, 1.42),
        ("MCP", 2.25, 0.66),
        ("EVALUATION", 3.08, 1.38),
        ("EVIDENCE", 4.63, 1.17),
        ("AUDIT", 5.97, 0.78),
    ]:
        pill(slide, value, x, 5.3, width, fill="252927", color="BFC5C1", line_color="343936")
    line(slide, 0.68, 6.72, 12.65, 6.73, color="343936")
    text(
        slide,
        "2026.08  /  v0.2.0a0",
        0.68,
        6.92,
        3.2,
        0.2,
        size=8,
        color="737A76",
        font="IBM Plex Mono",
    )

    # 02
    slide = base_slide(
        prs, 2, "PROBLEM", "传统测试方法不适配 Agent", "问题已经从“接口断言”升级为“执行治理”"
    )
    items = [
        ("01", "输出不确定", "字符串快照既脆弱，也无法解释语义是否正确。", CORAL),
        ("02", "工具有副作用", "真实工具昂贵且修改数据；纯 mock 又缺少合理性。", AMBER),
        ("03", "Judge 不可信", "可能看见预期答案、接受伪证据或脱离运行事实。", COBALT),
        ("04", "状态跨多轮", "版本、工具链、审批和恢复共同决定最终行为。", GREEN),
    ]
    for idx, (number, title_value, description, accent) in enumerate(items):
        card_title(
            slide,
            number,
            title_value,
            description,
            0.62 + idx * 3.08,
            2.05,
            2.86,
            3.75,
            accent=accent,
        )
    text(
        slide,
        "目标不是再做一个聊天评分器，而是建立企业 Agent 的持续验证基础设施。",
        0.65,
        6.13,
        11.9,
        0.42,
        size=16,
        color=INK,
        bold=True,
        align=PP_ALIGN.CENTER,
    )

    # 03
    slide = base_slide(
        prs, 3, "USER JOURNEY", "从一句目标到可审计 Run", "把平台数据模型隐藏在自然语言交互之后"
    )
    steps = [
        ("01", "描述目标", "自然语言"),
        ("02", "查询资产", "Case / Target / Profile"),
        ("03", "预览计划", "范围 / 风险 / 数量"),
        ("04", "用户确认", "绑定 event + revision"),
        ("05", "执行验证", "Rule + Judge"),
        ("06", "解释沉淀", "Evidence / Case Draft"),
    ]
    for idx, (number, label, detail) in enumerate(steps):
        x = 0.58 + idx * 2.08
        rect(slide, x, 2.55, 1.74, 1.72, fill=WHITE, line=LINE)
        text(
            slide,
            number,
            x + 0.16,
            2.72,
            0.4,
            0.2,
            size=8,
            color=COBALT,
            bold=True,
            font="IBM Plex Mono",
        )
        text(slide, label, x + 0.16, 3.12, 1.42, 0.28, size=14, color=INK, bold=True)
        text(slide, detail, x + 0.16, 3.55, 1.42, 0.42, size=8.5, color=MUTED)
        if idx < len(steps) - 1:
            text(
                slide,
                "→",
                x + 1.78,
                3.16,
                0.28,
                0.3,
                size=17,
                color=COBALT,
                bold=True,
                align=PP_ALIGN.CENTER,
            )
    pill(
        slide,
        "NO RUN BEFORE CONFIRMATION",
        4.78,
        4.75,
        3.75,
        fill=AMBER_SOFT,
        color=AMBER,
        line_color="EAD39A",
    )
    text(
        slide,
        "关键边界：计划不是提示词中的“建议”，而是可预览、可修订、可确认的领域对象。",
        1.2,
        5.55,
        10.9,
        0.52,
        size=15,
        color=GRAPHITE,
        bold=True,
        align=PP_ALIGN.CENTER,
    )

    # 04
    slide = base_slide(
        prs,
        4,
        "AGENT IDENTITY",
        "三 Agent 职责分离，不为数量而拆分",
        "不同知识、不同权限、不同可信边界",
    )
    roles = [
        (
            "01",
            "Manager",
            "目标理解 · 资产选择\n计划 · 审批 · 诊断",
            "不能直接执行原始 run_cases",
            COBALT,
        ),
        (
            "02",
            "Simulation Curator",
            "冻结上下文 · 工具候选\nSchema 合规结果",
            "看不到 rubric 与预期答案",
            GREEN,
        ),
        (
            "03",
            "Evidence Judge",
            "冻结证据 · 独立裁决\n引用真实 event ID",
            "不能改执行，也不能造证据",
            AMBER,
        ),
    ]
    for idx, (number, role, work, boundary, accent) in enumerate(roles):
        x = 0.72 + idx * 4.18
        rect(slide, x, 2.12, 3.76, 3.92, fill=WHITE, line=LINE)
        rect(slide, x, 2.12, 3.76, 0.08, fill=accent, line=accent)
        pill(
            slide,
            number,
            x + 0.22,
            2.48,
            0.54,
            fill=COBALT_SOFT if accent == COBALT else GREEN_SOFT if accent == GREEN else AMBER_SOFT,
            color=accent,
        )
        text(slide, role, x + 0.22, 2.98, 3.3, 0.36, size=18, color=INK, bold=True)
        text(slide, work, x + 0.22, 3.63, 3.3, 0.82, size=12, color=GRAPHITE, bold=True)
        line(slide, x + 0.22, 4.72, x + 3.53, 4.73)
        text(
            slide,
            "BOUNDARY",
            x + 0.22,
            4.98,
            1.2,
            0.18,
            size=7,
            color=FAINT,
            bold=True,
            font="IBM Plex Mono",
        )
        text(slide, boundary, x + 0.22, 5.28, 3.25, 0.34, size=10, color=MUTED)
    text(
        slide,
        "合并角色会产生三类风险：越权执行 / 目标泄漏 / 执行者自评",
        0.72,
        6.38,
        11.8,
        0.34,
        size=14,
        color=CORAL,
        bold=True,
        align=PP_ALIGN.CENTER,
    )

    # 05
    slide = base_slide(
        prs,
        5,
        "AGENTTEAMS",
        "AgentTeams 如何真实进入系统",
        "不是 PPT 依赖：身份、生命周期、Skill 和双向事件均可现场核验",
    )
    stack = [
        ("AgentTeams v1.1.2", "Manager / Worker 生命周期与身份", COBALT, COBALT_SOFT),
        ("Matrix", "定向唤醒 · 任务投递 · 最终回执", GREEN, GREEN_SOFT),
        ("MinIO", "角色工作区 · 版本化 Skills", AMBER, AMBER_SOFT),
        ("Higress", "三身份隔离 MCP Routes", CORAL, CORAL_SOFT),
    ]
    for idx, (name, detail, accent, soft) in enumerate(stack):
        y = 2.08 + idx * 1.03
        rect(slide, 0.72, y, 4.62, 0.78, fill=WHITE, line=LINE)
        rect(slide, 0.72, y, 0.07, 0.78, fill=accent, line=accent)
        text(slide, name, 0.98, y + 0.18, 1.75, 0.26, size=12, color=INK, bold=True)
        text(slide, detail, 2.62, y + 0.2, 2.45, 0.24, size=9, color=MUTED)
    text(slide, "→", 5.52, 3.37, 0.5, 0.5, size=27, color=COBALT, bold=True, align=PP_ALIGN.CENTER)
    rect(slide, 6.18, 2.32, 6.2, 3.45, fill=INK, line=INK)
    text(
        slide,
        "AGENTRIG ADAPTER",
        6.52,
        2.7,
        2.8,
        0.24,
        size=8,
        color="8E9691",
        bold=True,
        font="IBM Plex Mono",
    )
    text(slide, "协作事件", 6.52, 3.24, 1.6, 0.32, size=17, color=WHITE, bold=True)
    text(slide, "映射", 8.27, 3.24, 0.8, 0.32, size=12, color="8E9691", align=PP_ALIGN.CENTER)
    text(slide, "业务 Invocation", 9.22, 3.24, 2.5, 0.32, size=17, color=WHITE, bold=True)
    line(slide, 6.52, 3.8, 11.98, 3.81, color="343936")
    rich_lines(
        slide,
        ["request_event_id", "response_event_id", "input / result hash", "terminal status"],
        6.52,
        4.14,
        2.3,
        1.1,
        size=9,
        color="BFC5C1",
        gap=4,
    )
    rich_lines(
        slide,
        ["run_id / case_run_id", "role / deadline", "result_ref", "error boundary"],
        9.22,
        4.14,
        2.3,
        1.1,
        size=9,
        color="BFC5C1",
        gap=4,
    )
    text(
        slide,
        "Core 不依赖 AgentTeams 类型；协作框架可替换，业务事实合同不变。",
        6.52,
        5.25,
        5.45,
        0.28,
        size=10,
        color="8E9691",
    )

    # 06
    slide = base_slide(
        prs,
        6,
        "ARCHITECTURE",
        "协作层与事实层分离",
        "AgentTeams 管“谁协作”，AgentRig Core 管“什么是事实”",
    )
    layers = [
        ("EXPERIENCE", "Web Assistant / Plan Preview / Evidence Trail", COBALT, COBALT_SOFT),
        ("COLLABORATION", "Manager  ⇄  Matrix  ⇄  Curator / Judge", GREEN, GREEN_SOFT),
        ("CONTROL", "EvaluationPlan / Approval / Invocation / MCP Policies", AMBER, AMBER_SOFT),
        ("EXECUTION", "Drivers  →  lassist/Pixcake  →  Provider Chain", CORAL, CORAL_SOFT),
        ("FACTS", "Case / Snapshot / RunEvent / Evaluation / Hash", GRAPHITE, WHITE),
    ]
    for idx, (name, detail, accent, fill) in enumerate(layers):
        y = 2.02 + idx * 0.88
        rect(slide, 0.82, y, 11.72, 0.68, fill=fill, line=LINE if fill != WHITE else GRAPHITE)
        text(
            slide,
            name,
            1.05,
            y + 0.2,
            1.75,
            0.2,
            size=8,
            color=accent,
            bold=True,
            font="IBM Plex Mono",
        )
        text(
            slide,
            detail,
            2.88,
            y + 0.16,
            8.9,
            0.26,
            size=12,
            color=INK,
            bold=idx == 4,
            font="IBM Plex Mono" if idx == 4 else "PingFang SC",
        )
    pill(
        slide,
        "IMMUTABLE EVIDENCE BOUNDARY",
        4.74,
        6.61,
        3.82,
        fill=INK,
        color=WHITE,
        line_color=INK,
    )

    # 07
    slide = base_slide(
        prs,
        7,
        "SKILL + MCP",
        "可复用能力，不是一次性 Prompt",
        "11 个 Skill + 三套最小权限 MCP 工具集",
    )
    groups = [
        (
            "MANAGER / 6",
            [
                "adaptive-evaluation",
                "plan-evaluation",
                "execute-evaluation-plan",
                "diagnose-run",
                "build-test-case-draft",
                "configure-test-target",
            ],
            COBALT,
        ),
        ("WORKERS / 2", ["simulate-tool-result", "judge-evidence"], GREEN),
        ("CORE / 3", ["run-test-cases", "build-test-case", "harvest-tool-samples"], AMBER),
    ]
    x_positions = [0.7, 5.0, 8.62]
    widths = [3.95, 3.28, 3.98]
    for idx, (label, items, accent) in enumerate(groups):
        x, width = x_positions[idx], widths[idx]
        rect(slide, x, 2.02, width, 3.95, fill=WHITE, line=LINE)
        text(
            slide,
            label,
            x + 0.22,
            2.28,
            width - 0.44,
            0.24,
            size=9,
            color=accent,
            bold=True,
            font="IBM Plex Mono",
        )
        for item_index, item in enumerate(items):
            y = 2.82 + item_index * 0.56
            rect(slide, x + 0.2, y, width - 0.4, 0.4, fill=SURFACE, line=LINE)
            text(
                slide,
                f"{item_index + 1:02d}",
                x + 0.34,
                y + 0.12,
                0.32,
                0.15,
                size=6.5,
                color=FAINT,
                font="IBM Plex Mono",
            )
            text(
                slide,
                item,
                x + 0.72,
                y + 0.09,
                width - 1.1,
                0.2,
                size=8.5,
                color=GRAPHITE,
                bold=True,
                font="IBM Plex Mono",
            )
    text(
        slide,
        "每个核心 Skill 定义：触发条件 · 输入输出 · 工具依赖 · 失败 · 重试 · 安全边界 · 版本合同",
        0.7,
        6.31,
        11.9,
        0.4,
        size=13,
        color=INK,
        bold=True,
        align=PP_ALIGN.CENTER,
    )

    # 08
    slide = base_slide(
        prs,
        8,
        "TRUSTED EVALUATION",
        "防止“Judge 说通过就通过”",
        "确定性约束与语义判断独立保存，结论必须回到证据",
    )
    trust = [
        ("冻结输入", "Case / Target / Profile\n形成不可变快照", COBALT),
        ("隔离生成", "Curator 看不到 rubric\n只提交 Schema 候选", GREEN),
        ("确定性 Rule", "结构化断言先执行\n结果独立存档", AMBER),
        ("证据 Judge", "只能引用本次 Run\n真实 event ID", CORAL),
        ("输出校验", "Pydantic / JSON Schema\nHash / Ref validation", GRAPHITE),
    ]
    for idx, (name, detail, accent) in enumerate(trust):
        x = 0.66 + idx * 2.47
        rect(slide, x, 2.18, 2.2, 3.35, fill=WHITE, line=LINE)
        rect(slide, x, 2.18, 2.2, 0.08, fill=accent, line=accent)
        text(
            slide,
            f"0{idx + 1}",
            x + 0.18,
            2.56,
            0.4,
            0.2,
            size=8,
            color=accent,
            bold=True,
            font="IBM Plex Mono",
        )
        text(slide, name, x + 0.18, 3.02, 1.84, 0.3, size=15, color=INK, bold=True)
        text(slide, detail, x + 0.18, 3.65, 1.84, 0.72, size=10, color=MUTED)
        pill(slide, "VERIFIED", x + 0.18, 4.83, 1.08, fill=SURFACE, color=accent, line_color=LINE)
    text(
        slide,
        "Rule / Judge / External 三类 Evaluation 互不覆盖；任何未知 evidence_ref 都会被拒绝。",
        0.66,
        6.05,
        12.0,
        0.42,
        size=14,
        color=GRAPHITE,
        bold=True,
        align=PP_ALIGN.CENTER,
    )

    # 09
    slide = base_slide(
        prs,
        9,
        "SAFETY + RECOVERY",
        "审批、安全与恢复",
        "模型只能提出动作，确定性后端决定动作是否允许发生",
    )
    states = [
        ("DRAFT", COBALT_SOFT, COBALT),
        ("CONFIRMED", GREEN_SOFT, GREEN),
        ("SUBMITTED", AMBER_SOFT, AMBER),
    ]
    for idx, (state, fill, color) in enumerate(states):
        x = 0.82 + idx * 2.45
        rect(slide, x, 2.2, 1.96, 0.68, fill=fill, line=color)
        text(
            slide,
            state,
            x,
            2.39,
            1.96,
            0.22,
            size=9,
            color=color,
            bold=True,
            font="IBM Plex Mono",
            align=PP_ALIGN.CENTER,
        )
        if idx < 2:
            text(slide, "→", x + 2.0, 2.37, 0.4, 0.25, size=18, color=FAINT, align=PP_ALIGN.CENTER)
    text(
        slide,
        "确认绑定 AssistantEvent + 同一 Plan Revision",
        0.82,
        3.18,
        6.85,
        0.34,
        size=13,
        color=GRAPHITE,
        bold=True,
        align=PP_ALIGN.CENTER,
    )
    rect(slide, 8.05, 2.05, 4.42, 1.65, fill=INK, line=INK)
    text(
        slide,
        "NO CONFIRMATION",
        8.4,
        2.4,
        3.7,
        0.22,
        size=9,
        color="8E9691",
        bold=True,
        font="IBM Plex Mono",
        align=PP_ALIGN.CENTER,
    )
    text(
        slide,
        "NO RUN",
        8.4,
        2.82,
        3.7,
        0.4,
        size=25,
        color=WHITE,
        bold=True,
        font="IBM Plex Mono",
        align=PP_ALIGN.CENTER,
    )
    controls = [
        ("SECRET", "env: / Secret 引用；不进 Matrix、日志和 Skill"),
        ("REDACTION", "模型与 Worker 输入统一脱敏"),
        ("IDEMPOTENCY", "重复提交复用幂等键，不重复执行"),
        ("TERMINAL", "超时、取消、失败都是显式可审计终态"),
        ("DEGRADE", "AgentTeams 故障不破坏 Core 与既有证据"),
    ]
    for idx, (label, detail) in enumerate(controls):
        y = 4.18 + (idx // 3) * 0.93
        x = 0.82 + (idx % 3) * 4.04
        width = 3.72
        rect(slide, x, y, width, 0.7, fill=WHITE, line=LINE)
        text(
            slide,
            label,
            x + 0.14,
            y + 0.13,
            0.92,
            0.18,
            size=7,
            color=COBALT,
            bold=True,
            font="IBM Plex Mono",
        )
        text(slide, detail, x + 1.02, y + 0.11, width - 1.16, 0.36, size=8.5, color=MUTED)

    # 10
    slide = base_slide(
        prs,
        10,
        "LIVE DEMO",
        "真实 Demo：成功、失败与证据",
        "本机 lassist/Pixcake Agent · AgentTeams 三角色 · 双向 Matrix event ID",
    )
    rect(slide, 0.55, 1.98, 3.25, 4.78, fill=INK, line=INK)
    text(
        slide,
        "DEMO CONTRACT",
        0.85,
        2.3,
        2.6,
        0.2,
        size=8,
        color="8E9691",
        bold=True,
        font="IBM Plex Mono",
    )
    demo_items = [
        ("01", "成功闭环", "apply_image_prompt → Curator → Rule 3/3 → Judge pass"),
        ("02", "策略回归", "编辑前未二次确认 → Rule / Judge fail"),
        ("03", "审批边界", "未确认不提交；revision 更新使旧确认失效"),
    ]
    for idx, (number, name, detail) in enumerate(demo_items):
        y = 2.88 + idx * 1.08
        text(
            slide,
            number,
            0.85,
            y,
            0.34,
            0.18,
            size=7,
            color=COBALT,
            bold=True,
            font="IBM Plex Mono",
        )
        text(slide, name, 1.3, y - 0.02, 1.9, 0.24, size=12, color=WHITE, bold=True)
        text(slide, detail, 1.3, y + 0.33, 2.08, 0.46, size=8.5, color="BFC5C1")
    pill(
        slide,
        "REAL TARGET / NO FAKE DRIVER",
        0.85,
        6.06,
        2.55,
        fill="252927",
        color="BFC5C1",
        line_color="343936",
    )
    if SCREENSHOT.exists():
        slide.shapes.add_picture(
            str(SCREENSHOT), Inches(4.02), Inches(1.98), width=Inches(8.77), height=Inches(4.93)
        )
    else:
        rect(slide, 4.02, 1.98, 8.77, 4.93, fill=WHITE, line=LINE)
        text(
            slide,
            "运行 scripts/local_demo.sh setup 后重新生成 PPT 以嵌入界面截图",
            4.4,
            4.1,
            8.0,
            0.45,
            size=13,
            color=MUTED,
            align=PP_ALIGN.CENTER,
        )

    # 11
    slide = base_slide(
        prs,
        11,
        "ENGINEERING",
        "工程落地与开放价值",
        "Core 无模型、无 AgentTeams 仍可完成确定性回归",
    )
    stats = [
        ("3+", "Agent identities"),
        ("11", "Versioned Skills"),
        ("4", "Target Drivers"),
        ("3", "Evaluator types"),
    ]
    for idx, (value, label) in enumerate(stats):
        x = 0.7 + idx * 3.03
        rect(slide, x, 2.05, 2.72, 1.25, fill=WHITE, line=LINE)
        rect(
            slide,
            x,
            2.05,
            0.05,
            1.25,
            fill=COBALT if idx == 0 else GREEN if idx == 1 else AMBER if idx == 2 else CORAL,
            line=LINE,
        )
        text(
            slide,
            value,
            x + 0.2,
            2.28,
            0.92,
            0.45,
            size=25,
            color=INK,
            bold=True,
            font="IBM Plex Mono",
        )
        text(slide, label, x + 1.1, 2.42, 1.35, 0.25, size=9, color=MUTED)
    engineering = [
        ("STACK", "Python 3.12 · FastAPI · SQLAlchemy · React · MCP"),
        ("DRIVERS", "Pixcake HTTP-SSE · OpenAI compatible · ACP · subprocess"),
        ("STORAGE", "SQLite 本机一键体验；Repository 可切 PostgreSQL"),
        ("EXTENSION", "Driver / Provider / Evaluator / Skill / Adapter 均为契约"),
        ("DELIVERY", "一键部署 · 示例配置 · 安全文档 · 自动化测试"),
        ("LICENSE", "MIT License · 可执行代码包 · 可重复构建角色包"),
    ]
    for idx, (label, detail) in enumerate(engineering):
        x = 0.7 + (idx % 2) * 6.12
        y = 3.75 + (idx // 2) * 0.82
        rect(slide, x, y, 5.82, 0.62, fill=SURFACE, line=LINE)
        text(
            slide,
            label,
            x + 0.16,
            y + 0.19,
            1.0,
            0.17,
            size=7,
            color=COBALT,
            bold=True,
            font="IBM Plex Mono",
        )
        text(slide, detail, x + 1.12, y + 0.16, 4.5, 0.24, size=9, color=GRAPHITE)

    # 12
    slide = base_slide(
        prs,
        12,
        "ROADMAP",
        "让每个 Agent 决定都经过分工、验证并留下证据",
        "AgentRig 不替 Agent 做决定；它让决定可以持续回归、发布门禁与审计复盘",
    )
    roadmap = [
        ("INITIAL", "2026.08", "公开设计与身份清单\n真实三 Agent Demo\n成功 / 失败证据", COBALT),
        ("SEMIFINAL", "NEXT", "可执行代码包与视频\n运行报告 / Trace\n恢复与性能指标", GREEN),
        ("FINAL", "SCALE", "PostgreSQL / Kubernetes\nOTel / SLS 可观测\n版本对比与发布门禁", AMBER),
    ]
    for idx, (phase, time_value, detail, accent) in enumerate(roadmap):
        x = 0.78 + idx * 4.15
        rect(slide, x, 2.15, 3.72, 3.52, fill=WHITE, line=LINE)
        rect(slide, x, 2.15, 3.72, 0.08, fill=accent, line=accent)
        text(
            slide,
            phase,
            x + 0.24,
            2.52,
            1.6,
            0.2,
            size=8,
            color=accent,
            bold=True,
            font="IBM Plex Mono",
        )
        text(
            slide,
            time_value,
            x + 0.24,
            3.02,
            3.15,
            0.36,
            size=22,
            color=INK,
            bold=True,
            font="IBM Plex Mono",
        )
        line(slide, x + 0.24, 3.62, x + 3.47, 3.63)
        text(slide, detail, x + 0.24, 3.93, 3.12, 1.05, size=11, color=MUTED)
    text(
        slide,
        "不同企业 Agent 共用的开源质量与发布基础设施",
        0.78,
        6.14,
        12.0,
        0.44,
        size=18,
        color=INK,
        bold=True,
        align=PP_ALIGN.CENTER,
    )
    pill(
        slide,
        "AGENTRIG / EVIDENCE BEFORE CONFIDENCE",
        4.62,
        6.67,
        4.18,
        fill=INK,
        color=WHITE,
        line_color=INK,
    )
    return prs


def main() -> None:
    presentation = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
