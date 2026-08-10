"""Build the editable GOAI 2026 AgentRig proposal deck.

The deck intentionally uses an editorial, evidence-first visual language. Main
slides make one argument at a time; dense contract details live in appendices.
"""

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
ASSETS = ROOT / "docs/competition/assets"
ASSISTANT_SCREENSHOT = ASSETS / "agentrig-assistant.png"
TEAM_SCREENSHOT = ASSETS / "video/03-agentteams-evidence.png"
SUCCESS_SCREENSHOT = ASSETS / "video/05-success-evidence.png"

SLIDE_W = 13.333
SLIDE_H = 7.5
TOTAL_SLIDES = 15

INK = "141719"
DARK = "1B1E22"
TEXT = "2D3330"
MUTED = "68716C"
FAINT = "929A95"
PAPER = "F7F6F2"
WHITE = "FFFFFF"
LINE = "D9DCD7"
COBALT = "315CF5"
COBALT_SOFT = "E9EEFF"
GREEN = "20785A"
GREEN_SOFT = "E8F3EE"
AMBER = "A86608"
AMBER_SOFT = "F7EEDC"
CORAL = "C34A3C"
CORAL_SOFT = "F8E8E5"


def rgb(value: str) -> RGBColor:
    return RGBColor.from_string(value)


def box(
    slide,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str = WHITE,
    stroke: str | None = LINE,
    radius: bool = False,
    stroke_width: float = 0.7,
):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        Inches(x),
        Inches(y),
        Inches(w),
        Inches(h),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    if stroke is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = rgb(stroke)
        shape.line.width = Pt(stroke_width)
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
    size: float = 15,
    color: str = TEXT,
    bold: bool = False,
    font: str = "PingFang SC",
    align=PP_ALIGN.LEFT,
    valign=MSO_ANCHOR.TOP,
    margin: float = 0,
    line_spacing: float = 1.08,
):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(margin)
    frame.margin_top = frame.margin_bottom = Inches(margin)
    frame.vertical_anchor = valign
    paragraph = frame.paragraphs[0]
    paragraph.alignment = align
    paragraph.space_after = Pt(0)
    paragraph.line_spacing = line_spacing
    run = paragraph.add_run()
    run.text = value
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = rgb(color)
    return shape


def paragraphs(
    slide,
    values: Iterable[str],
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    size: float = 12,
    color: str = TEXT,
    gap: float = 8,
    bullet: bool = False,
    bold: bool = False,
):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(0)
    frame.margin_top = frame.margin_bottom = Inches(0)
    for index, value in enumerate(values):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = f"•  {value}" if bullet else value
        paragraph.font.name = "PingFang SC"
        paragraph.font.size = Pt(size)
        paragraph.font.bold = bold
        paragraph.font.color.rgb = rgb(color)
        paragraph.space_after = Pt(gap)
        paragraph.line_spacing = 1.15
    return shape


def rule(slide, x: float, y: float, w: float, *, color: str = LINE, height_pt: float = 0.8):
    shape = box(slide, x, y, w, 0.01, fill=color, stroke=None)
    shape.height = Pt(height_pt)
    return shape


def v_rule(slide, x: float, y: float, h: float, *, color: str = LINE, width_pt: float = 0.8):
    shape = box(slide, x, y, 0.01, h, fill=color, stroke=None)
    shape.width = Pt(width_pt)
    return shape


def marker(slide, value: str, x: float, y: float, *, fill: str = COBALT, size: float = 0.34):
    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(size), Inches(size))
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    shape.line.fill.background()
    text(
        slide,
        value,
        x,
        y,
        size,
        size,
        size=7.5,
        color=WHITE,
        bold=True,
        font="Helvetica Neue",
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
    )


def add_picture(slide, path: Path, x: float, y: float, w: float, *, border: bool = True):
    if not path.exists():
        box(slide, x, y, w, w / 1.742, fill=WHITE, stroke=LINE)
        text(
            slide,
            f"Missing asset: {path.name}",
            x + 0.2,
            y + 0.2,
            w - 0.4,
            0.3,
            size=10,
            color=CORAL,
        )
        return None
    picture = slide.shapes.add_picture(str(path), Inches(x), Inches(y), width=Inches(w))
    if border:
        frame = box(
            slide,
            x - 0.01,
            y - 0.01,
            w + 0.02,
            picture.height / Inches(1) + 0.02,
            fill=WHITE,
            stroke=LINE,
        )
        slide.shapes._spTree.remove(frame._element)
        slide.shapes._spTree.insert(slide.shapes._spTree.index(picture._element), frame._element)
    return picture


def new_slide(prs: Presentation, index: int, section: str, title_value: str, subtitle: str = ""):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = rgb(PAPER)
    text(slide, section, 0.72, 0.36, 4.6, 0.2, size=8.5, color=COBALT, bold=True)
    text(slide, title_value, 0.72, 0.73, 11.4, 0.53, size=27, color=INK, bold=True)
    if subtitle:
        text(slide, subtitle, 0.74, 1.29, 11.5, 0.25, size=10.5, color=MUTED)
    text(
        slide,
        f"{index:02d}",
        12.05,
        0.38,
        0.55,
        0.25,
        size=9,
        color=FAINT,
        bold=True,
        font="Helvetica Neue",
        align=PP_ALIGN.RIGHT,
    )
    rule(slide, 0.72, 1.7, 11.9)
    footer(slide, index)
    return slide


def footer(slide, index: int, *, dark: bool = False):
    color = "727A76" if dark else FAINT
    text(slide, "AgentRig  ·  GOAI 2026", 0.72, 7.16, 3.2, 0.16, size=7.2, color=color)
    text(
        slide,
        f"{index:02d} / {TOTAL_SLIDES:02d}",
        11.76,
        7.16,
        0.86,
        0.16,
        size=7.2,
        color=color,
        font="Helvetica Neue",
        align=PP_ALIGN.RIGHT,
    )


def build() -> Presentation:
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)

    # 01 — Cover
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = rgb(DARK)
    box(slide, 0.72, 0.55, 0.42, 0.42, fill=COBALT, stroke=None)
    text(
        slide,
        "A",
        0.72,
        0.54,
        0.42,
        0.42,
        size=15,
        color=WHITE,
        bold=True,
        font="Helvetica Neue",
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
    )
    text(slide, "AgentRig", 1.32, 0.66, 2.0, 0.24, size=10, color=WHITE, bold=True)
    text(
        slide,
        "GOAI 2026  ·  Agent Infra",
        9.55,
        0.66,
        3.05,
        0.2,
        size=8.5,
        color="A9B0AC",
        align=PP_ALIGN.RIGHT,
    )
    text(
        slide,
        "让企业 Agent 的\n每次变化都有证据",
        0.72,
        1.48,
        6.2,
        1.6,
        size=35,
        color=WHITE,
        bold=True,
        line_spacing=1.03,
    )
    text(slide, "多 Agent 可审计评测基础设施", 0.75, 3.42, 5.7, 0.36, size=17, color="C8CDCA")
    rule(slide, 0.75, 4.1, 5.65, color="373C39")
    text(
        slide,
        "AgentTeams 负责协作。\nAgentRig 负责事实、验证与审计。",
        0.75,
        4.38,
        5.8,
        0.83,
        size=13,
        color="9FA7A2",
        line_spacing=1.2,
    )
    text(
        slide,
        "EVIDENCE BEFORE CONFIDENCE",
        0.75,
        5.73,
        4.5,
        0.22,
        size=8.5,
        color=COBALT,
        bold=True,
        font="Helvetica Neue",
    )
    add_picture(slide, SUCCESS_SCREENSHOT, 7.1, 1.34, 5.55, border=True)
    text(
        slide,
        "真实 lassist/Pixcake Agent  ·  三角色协作  ·  成功与策略回归证据",
        7.1,
        4.66,
        5.55,
        0.38,
        size=8.5,
        color="A9B0AC",
    )
    rule(slide, 7.1, 5.25, 5.55, color="373C39")
    text(slide, "2026.08  /  v0.2.0a0", 7.1, 5.53, 2.7, 0.2, size=8, color="777F7A")
    footer(slide, 1, dark=True)

    # 02 — Problem
    slide = new_slide(
        prs,
        2,
        "问题定义",
        "Agent 的风险，不止是回答错一次",
        "真正困难的是：事后能否复原它为什么这样做。",
    )
    text(
        slide,
        "输出可以看见，\n过程往往不可见。",
        0.78,
        2.14,
        5.7,
        1.2,
        size=28,
        color=INK,
        bold=True,
    )
    text(
        slide,
        "没有冻结上下文、执行事件和独立裁决，\n一次“通过”既无法解释，也无法复现。",
        0.8,
        3.66,
        5.6,
        0.8,
        size=14,
        color=MUTED,
        line_spacing=1.2,
    )
    box(slide, 0.78, 5.2, 5.62, 0.94, fill=COBALT, stroke=None)
    text(
        slide,
        "目标：把聊天质量问题，变成可持续验证的工程问题。",
        1.05,
        5.45,
        5.08,
        0.42,
        size=13,
        color=WHITE,
        bold=True,
        valign=MSO_ANCHOR.MIDDLE,
    )
    issues = [
        ("输出", "随机结果让字符串快照失去解释力"),
        ("工具", "真实调用有成本和副作用；纯 mock 又不可信"),
        ("裁决", "Judge 可能看见答案、接受伪证据或自说自话"),
        ("状态", "版本、审批、多轮上下文与恢复共同决定行为"),
    ]
    for idx, (label, detail) in enumerate(issues):
        y = 2.04 + idx * 1.02
        text(slide, f"0{idx + 1}", 7.05, y + 0.04, 0.42, 0.2, size=8, color=COBALT, bold=True)
        text(slide, label, 7.58, y, 0.92, 0.3, size=14, color=INK, bold=True)
        text(slide, detail, 8.62, y + 0.01, 3.75, 0.42, size=11, color=MUTED)
        rule(slide, 7.05, y + 0.73, 5.4)

    # 03 — Journey
    slide = new_slide(
        prs,
        3,
        "用户路径",
        "从一句目标，到一条可审计 Run",
        "把平台对象藏在自然语言之后，把关键边界留给用户确认。",
    )
    xs = [2.05, 6.65, 11.15]
    phases = [
        ("01", "计划", "描述目标 → 查询资产\n生成可预览、可修订的计划"),
        ("02", "确认", "绑定真实 user event\n与同一 plan revision"),
        ("03", "证明", "执行 → Rule / Judge\n保存证据并解释结果"),
    ]
    rule(slide, 1.04, 2.56, 11.15, color="BFC7C2", height_pt=1.2)
    for idx, (number, label, detail) in enumerate(phases):
        marker(slide, number, xs[idx] - 0.23, 2.34, fill=COBALT, size=0.46)
        text(
            slide,
            label,
            xs[idx] - 1.55,
            3.15,
            3.1,
            0.4,
            size=21,
            color=INK,
            bold=True,
            align=PP_ALIGN.CENTER,
        )
        text(
            slide,
            detail,
            xs[idx] - 1.62,
            3.75,
            3.24,
            0.72,
            size=11.5,
            color=MUTED,
            align=PP_ALIGN.CENTER,
            line_spacing=1.18,
        )
    box(slide, 4.33, 5.38, 4.68, 0.78, fill=DARK, stroke=None)
    text(
        slide,
        "没有确认，不产生 Run",
        4.33,
        5.39,
        4.68,
        0.76,
        size=17,
        color=WHITE,
        bold=True,
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
    )
    text(
        slide,
        "计划是领域对象，不是提示词里的建议。",
        4.3,
        6.42,
        4.75,
        0.24,
        size=10.5,
        color=MUTED,
        align=PP_ALIGN.CENTER,
    )

    # 04 — Roles
    slide = new_slide(
        prs,
        4,
        "角色设计",
        "三种职责，三条不可越过的边界",
        "分工不是为了凑 Agent 数量，而是隔离知识、权限和裁决。",
    )
    box(slide, 0.72, 2.02, 4.35, 4.46, fill=DARK, stroke=None)
    text(slide, "01  /  Manager", 1.03, 2.35, 3.7, 0.24, size=9, color="9EA6A1", bold=True)
    text(slide, "把目标变成\n可确认的计划", 1.03, 2.9, 3.45, 0.92, size=24, color=WHITE, bold=True)
    text(slide, "目标理解 · 资产选择 · 计划 · 诊断", 1.03, 4.25, 3.54, 0.3, size=12, color="C8CDCA")
    rule(slide, 1.03, 4.86, 3.7, color="3A3F3C")
    text(slide, "边界", 1.03, 5.16, 0.62, 0.2, size=8.5, color=COBALT, bold=True)
    text(
        slide, "不能直接调用原始 run_cases", 1.03, 5.55, 3.5, 0.32, size=12, color=WHITE, bold=True
    )
    workers = [
        (
            2.02,
            "02  /  Simulation Curator",
            "生成合理、Schema 合法的工具结果",
            "看不到 rubric 与预期答案",
            GREEN,
        ),
        (4.32, "03  /  Evidence Judge", "基于冻结证据独立裁决", "不能改执行，也不能造证据", AMBER),
    ]
    for y, role, work, boundary, accent in workers:
        box(slide, 5.68, y, 6.92, 2.0, fill=WHITE, stroke=LINE)
        box(slide, 5.68, y, 0.08, 2.0, fill=accent, stroke=None)
        text(slide, role, 6.02, y + 0.25, 3.5, 0.22, size=9, color=accent, bold=True)
        text(slide, work, 6.02, y + 0.68, 5.95, 0.34, size=18, color=INK, bold=True)
        text(slide, f"边界  ·  {boundary}", 6.02, y + 1.35, 5.9, 0.27, size=10.5, color=MUTED)
    text(
        slide,
        "隔离的结果：不越权、不泄漏目标、不让执行者自评。",
        5.72,
        6.61,
        6.85,
        0.24,
        size=11,
        color=CORAL,
        bold=True,
        align=PP_ALIGN.RIGHT,
    )

    # 05 — AgentTeams integration
    slide = new_slide(
        prs,
        5,
        "协作接入",
        "AgentTeams 不是 PPT 依赖，而是运行时事实",
        "身份、生命周期、工作区、MCP 路由与双向事件都可以现场核验。",
    )
    text(
        slide,
        "协作框架拥有协作；\nAgentRig 只接收可审计事件。",
        0.76,
        2.12,
        4.0,
        0.95,
        size=21,
        color=INK,
        bold=True,
    )
    integration = [
        ("身份与生命周期", "AgentTeams v1.1.2"),
        ("任务与回执", "Matrix request / response event ID"),
        ("角色工作区", "MinIO versioned roles + Skills"),
        ("最小权限工具", "Higress isolated MCP routes"),
    ]
    for idx, (name, detail) in enumerate(integration):
        y = 3.42 + idx * 0.58
        text(slide, name, 0.78, y, 1.55, 0.22, size=10.5, color=TEXT, bold=True)
        text(slide, detail, 2.42, y, 2.22, 0.25, size=8.7, color=MUTED)
        rule(slide, 0.78, y + 0.39, 3.87)
    box(slide, 0.78, 5.98, 3.86, 0.6, fill=DARK, stroke=None)
    text(
        slide,
        "Core 不依赖 AgentTeams 类型",
        0.78,
        5.99,
        3.86,
        0.58,
        size=11,
        color=WHITE,
        bold=True,
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
    )
    picture = add_picture(slide, TEAM_SCREENSHOT, 5.05, 2.0, 7.55, border=True)
    if picture:
        marker(slide, "1", 8.88, 2.46, fill=COBALT)
        marker(slide, "2", 11.78, 4.78, fill=COBALT)
    text(
        slide,
        "1  三个真实角色    2  Worker 调用、输入/结果 hash 与事件回执",
        5.05,
        6.47,
        7.55,
        0.24,
        size=8.7,
        color=MUTED,
    )

    # 06 — Architecture
    slide = new_slide(
        prs,
        6,
        "系统架构",
        "两条责任链，一份权威事实",
        "AgentTeams 管“谁在协作”；AgentRig Core 管“究竟发生了什么”。",
    )
    text(slide, "协作层", 0.76, 2.04, 0.9, 0.24, size=9, color=GREEN, bold=True)
    box(slide, 0.72, 2.38, 11.9, 1.2, fill=GREEN_SOFT, stroke=None)
    collab = [
        (1.05, "Web Assistant"),
        (3.72, "Manager"),
        (6.34, "Matrix"),
        (9.0, "Curator / Judge"),
    ]
    for idx, (x, label) in enumerate(collab):
        text(slide, label, x, 2.8, 2.12, 0.3, size=14, color=INK, bold=True, align=PP_ALIGN.CENTER)
        if idx < len(collab) - 1:
            text(
                slide,
                "→",
                x + 2.2,
                2.79,
                0.38,
                0.3,
                size=17,
                color=GREEN,
                bold=True,
                align=PP_ALIGN.CENTER,
            )
    rule(slide, 0.72, 3.82, 11.9, color=COBALT, height_pt=1.8)
    box(slide, 5.02, 3.66, 3.28, 0.35, fill=PAPER, stroke=None)
    text(
        slide,
        "Adapter boundary  ·  event / hash / status",
        5.02,
        3.72,
        3.28,
        0.17,
        size=7.8,
        color=COBALT,
        bold=True,
        align=PP_ALIGN.CENTER,
    )
    text(slide, "事实层", 0.76, 4.16, 0.9, 0.24, size=9, color=COBALT, bold=True)
    box(slide, 0.72, 4.48, 11.9, 1.78, fill=COBALT_SOFT, stroke=None)
    fact_nodes = [
        (1.05, "EvaluationPlan", "确认与 revision"),
        (4.25, "AgentRig Core", "运行状态机"),
        (7.45, "Target / Driver", "真实被测对象"),
        (10.15, "Evidence Store", "Event / Eval / Hash"),
    ]
    for idx, (x, label, detail) in enumerate(fact_nodes):
        text(
            slide,
            label,
            x,
            4.91,
            2.02,
            0.28,
            size=13.5,
            color=INK,
            bold=True,
            align=PP_ALIGN.CENTER,
        )
        text(slide, detail, x, 5.38, 2.02, 0.23, size=9, color=MUTED, align=PP_ALIGN.CENTER)
        if idx < len(fact_nodes) - 1:
            text(
                slide,
                "→",
                x + 2.28,
                5.02,
                0.5,
                0.3,
                size=16,
                color=COBALT,
                bold=True,
                align=PP_ALIGN.CENTER,
            )
    text(
        slide,
        "任何 Agent 都不能用聊天文本改写 RunEvent。",
        0.76,
        6.57,
        11.82,
        0.28,
        size=12,
        color=INK,
        bold=True,
        align=PP_ALIGN.CENTER,
    )

    # 07 — Skills
    slide = new_slide(
        prs,
        7,
        "Skill 与 MCP",
        "可复用能力，不是一次性 Prompt",
        "11 个版本化 Skill；三套最小权限 MCP 工具集。",
    )
    text(
        slide, "11", 0.76, 2.02, 1.55, 0.78, size=51, color=COBALT, bold=True, font="Helvetica Neue"
    )
    text(
        slide,
        "versioned\nskills",
        0.8,
        2.92,
        1.4,
        0.52,
        size=11,
        color=MUTED,
        bold=True,
        font="Helvetica Neue",
    )
    v_rule(slide, 2.24, 2.02, 3.3, color=LINE)
    groups = [
        (
            2.62,
            4.15,
            "Manager",
            "6",
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
        (7.05, 2.18, "Workers", "2", ["simulate-tool-result", "judge-evidence"], GREEN),
        (
            9.55,
            2.82,
            "Core",
            "3",
            ["run-test-cases", "build-test-case", "harvest-tool-samples"],
            AMBER,
        ),
    ]
    for x, width, name, count, items, accent in groups:
        text(slide, name, x, 2.08, width - 0.6, 0.28, size=15, color=INK, bold=True)
        text(
            slide,
            count,
            x + width - 0.52,
            2.08,
            0.45,
            0.28,
            size=14,
            color=accent,
            bold=True,
            font="Helvetica Neue",
            align=PP_ALIGN.RIGHT,
        )
        rule(slide, x, 2.54, width, color=accent, height_pt=1.4)
        for idx, item in enumerate(items):
            y = 2.82 + idx * 0.43
            text(
                slide,
                f"{idx + 1:02d}",
                x,
                y + 0.01,
                0.34,
                0.19,
                size=7,
                color=FAINT,
                font="Helvetica Neue",
            )
            text(
                slide,
                item,
                x + 0.43,
                y,
                width - 0.44,
                0.22,
                size=9.1,
                color=TEXT,
                bold=True,
                font="Menlo",
            )
            rule(slide, x, y + 0.31, width)
    box(slide, 0.76, 5.86, 11.82, 0.82, fill=DARK, stroke=None)
    text(
        slide,
        "每个核心 Skill 都有工程合同",
        1.02,
        6.06,
        2.45,
        0.25,
        size=11,
        color=WHITE,
        bold=True,
    )
    text(
        slide,
        "输入输出  ·  调用条件  ·  依赖  ·  失败  ·  安全  ·  验证复用  ·  版本回滚",
        3.55,
        6.06,
        8.68,
        0.25,
        size=10,
        color="C8CDCA",
    )

    # 08 — Trusted evaluation
    slide = new_slide(
        prs,
        8,
        "可信评测",
        "结论必须回到证据，而不是相信 Judge",
        "确定性约束与语义判断独立保存，任何未知 evidence_ref 都会被拒绝。",
    )
    phase_x = [0.78, 4.18, 8.02]
    phase_w = [2.68, 3.06, 4.52]
    titles = [("01", "冻结事实"), ("02", "独立评测"), ("03", "证据报告")]
    for idx, (number, label) in enumerate(titles):
        text(slide, number, phase_x[idx], 2.06, 0.38, 0.2, size=8, color=COBALT, bold=True)
        text(
            slide,
            label,
            phase_x[idx] + 0.46,
            2.02,
            phase_w[idx] - 0.46,
            0.3,
            size=16,
            color=INK,
            bold=True,
        )
        rule(
            slide,
            phase_x[idx],
            2.52,
            phase_w[idx],
            color=COBALT if idx == 0 else LINE,
            height_pt=1.2,
        )
    paragraphs(
        slide,
        ["Case / Target / Profile 快照", "RunEvent / tool call / result", "Curator 看不到 rubric"],
        0.78,
        2.9,
        2.74,
        2.1,
        size=11,
        color=TEXT,
        gap=12,
        bullet=True,
    )
    box(slide, 4.18, 2.88, 3.06, 0.92, fill=AMBER_SOFT, stroke=None)
    text(slide, "Rule Evaluator", 4.42, 3.08, 2.6, 0.23, size=13, color=INK, bold=True)
    text(slide, "结构化断言 · 结果独立存档", 4.42, 3.41, 2.6, 0.19, size=8.5, color=MUTED)
    box(slide, 4.18, 4.05, 3.06, 0.92, fill=GREEN_SOFT, stroke=None)
    text(slide, "Evidence Judge", 4.42, 4.25, 2.6, 0.23, size=13, color=INK, bold=True)
    text(slide, "仅引用本次 Run 的 event ID", 4.42, 4.58, 2.6, 0.19, size=8.5, color=MUTED)
    text(slide, "→", 7.42, 3.67, 0.36, 0.3, size=20, color=COBALT, bold=True, align=PP_ALIGN.CENTER)
    box(slide, 8.02, 2.88, 4.52, 2.1, fill=DARK, stroke=None)
    text(
        slide,
        "PASS  3 / 3",
        8.35,
        3.18,
        3.84,
        0.38,
        size=23,
        color=WHITE,
        bold=True,
        font="Helvetica Neue",
    )
    text(slide, "Rule 与 Judge 的结果互不覆盖", 8.35, 3.83, 3.8, 0.26, size=11, color="C8CDCA")
    text(
        slide,
        "每个 verdict 都能追到 event / hash / evaluator",
        8.35,
        4.31,
        3.84,
        0.3,
        size=9.5,
        color="9FA7A2",
    )
    rule(slide, 0.78, 5.51, 11.76)
    text(
        slide,
        "输出进入事实库之前：Pydantic / JSON Schema / hash / evidence reference 全部校验。",
        0.78,
        5.86,
        11.74,
        0.34,
        size=12.5,
        color=INK,
        bold=True,
        align=PP_ALIGN.CENTER,
    )

    # 09 — Safety and recovery
    slide = new_slide(
        prs,
        9,
        "安全与恢复",
        "模型可以提议，只有确定性后端可以放行",
        "审批、密钥、重试与失败终态都在 Prompt 之外执行。",
    )
    text(slide, "计划状态机", 0.78, 2.08, 1.7, 0.24, size=9, color=COBALT, bold=True)
    states = [
        (0.78, "DRAFT", "生成 / 修订"),
        (3.55, "CONFIRMED", "user event + revision"),
        (6.8, "SUBMITTED", "幂等提交"),
    ]
    for idx, (x, state, detail) in enumerate(states):
        marker(slide, str(idx + 1), x, 2.72, fill=COBALT if idx < 2 else GREEN, size=0.42)
        text(
            slide,
            state,
            x + 0.62,
            2.72,
            1.85,
            0.24,
            size=12.5,
            color=INK,
            bold=True,
            font="Helvetica Neue",
        )
        text(slide, detail, x + 0.62, 3.08, 2.2, 0.21, size=8.8, color=MUTED)
        if idx < 2:
            rule(slide, x + 2.35, 2.92, 0.75, color=COBALT, height_pt=1.2)
    box(slide, 9.72, 2.36, 2.84, 1.24, fill=DARK, stroke=None)
    text(
        slide,
        "NO CONFIRMATION",
        9.72,
        2.62,
        2.84,
        0.2,
        size=8.5,
        color="9FA7A2",
        bold=True,
        font="Helvetica Neue",
        align=PP_ALIGN.CENTER,
    )
    text(
        slide,
        "NO RUN",
        9.72,
        2.96,
        2.84,
        0.34,
        size=22,
        color=WHITE,
        bold=True,
        font="Helvetica Neue",
        align=PP_ALIGN.CENTER,
    )
    rule(slide, 0.78, 4.1, 11.78)
    controls = [
        ("Secret", "只存 env:/Secret 引用；不进 Matrix、日志和 Skill"),
        ("Redaction", "模型与 Worker 输入统一脱敏"),
        ("Idempotency", "重复提交复用幂等键，不重复执行"),
        ("Terminal state", "超时、取消、失败均为显式可审计终态"),
    ]
    for idx, (name, detail) in enumerate(controls):
        x = 0.78 + idx * 3.0
        text(slide, f"0{idx + 1}", x, 4.56, 0.34, 0.2, size=7.5, color=COBALT, bold=True)
        text(
            slide, name, x, 4.9, 2.72, 0.26, size=13.5, color=INK, bold=True, font="Helvetica Neue"
        )
        text(slide, detail, x, 5.39, 2.66, 0.72, size=9.6, color=MUTED)
    text(
        slide,
        "AgentTeams 故障不会破坏 Core 与既有证据。",
        0.78,
        6.44,
        11.75,
        0.26,
        size=11.5,
        color=CORAL,
        bold=True,
        align=PP_ALIGN.CENTER,
    )

    # 10 — Product demo
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = rgb(PAPER)
    text(slide, "真实 Demo", 0.72, 0.42, 2.2, 0.2, size=8.5, color=COBALT, bold=True)
    text(slide, "真实产品，\n不是概念图", 0.72, 1.03, 2.32, 0.95, size=25, color=INK, bold=True)
    text(slide, "本机 lassist/Pixcake Agent", 0.74, 2.25, 2.24, 0.25, size=9.5, color=MUTED)
    demo_points = [
        ("1", "三角色状态与当前计划"),
        ("2", "成功 / 失败诊断"),
        ("3", "Run 与 Matrix 双向 event ID"),
    ]
    for idx, (number, detail) in enumerate(demo_points):
        y = 3.0 + idx * 0.78
        marker(slide, number, 0.74, y, fill=COBALT)
        text(slide, detail, 1.23, y + 0.04, 1.83, 0.44, size=10.5, color=TEXT, bold=True)
    text(
        slide,
        "成功闭环 + 策略回归\n均保留可引用证据",
        0.74,
        5.72,
        2.2,
        0.58,
        size=11.5,
        color=INK,
        bold=True,
    )
    picture = add_picture(slide, ASSISTANT_SCREENSHOT, 3.25, 1.15, 9.45, border=True)
    if picture:
        marker(slide, "1", 11.5, 3.18, fill=COBALT)
        marker(slide, "2", 7.74, 3.6, fill=COBALT)
        marker(slide, "3", 9.05, 1.54, fill=COBALT)
    footer(slide, 10)

    # 11 — Engineering
    slide = new_slide(
        prs,
        11,
        "工程可信度",
        "可运行、可替换、可复核",
        "Core 在无模型、无 AgentTeams 时仍能完成确定性回归。",
    )
    text(
        slide, "134", 0.76, 2.04, 3.0, 0.88, size=55, color=COBALT, bold=True, font="Helvetica Neue"
    )
    text(
        slide,
        "backend tests passed",
        0.8,
        3.06,
        3.2,
        0.26,
        size=12,
        color=INK,
        bold=True,
        font="Helvetica Neue",
    )
    text(
        slide,
        "30 unit  ·  2 E2E  ·  0 secret hits",
        0.8,
        3.58,
        3.35,
        0.28,
        size=10.5,
        color=MUTED,
        font="Helvetica Neue",
    )
    rule(slide, 0.8, 4.15, 3.55)
    text(
        slide,
        "Python 3.12  ·  FastAPI  ·  SQLAlchemy\nReact  ·  MCP  ·  MIT",
        0.8,
        4.48,
        3.55,
        0.62,
        size=11,
        color=TEXT,
        line_spacing=1.22,
    )
    box(slide, 0.8, 5.62, 3.58, 0.65, fill=DARK, stroke=None)
    text(
        slide,
        "本机一键运行与确定性验证",
        0.8,
        5.63,
        3.58,
        0.63,
        size=11,
        color=WHITE,
        bold=True,
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
    )
    ledger = [
        ("Core", "没有模型与 AgentTeams 也能执行回归"),
        ("Drivers", "Pixcake / OpenAI-compatible / ACP / subprocess"),
        ("Storage", "SQLite 本机体验；Repository 契约可接 PostgreSQL"),
        ("Extension", "Driver / Provider / Evaluator / Skill / Adapter"),
        ("Delivery", "MIT · 部署文档 · Skills · 安全文档 · 自动测试"),
    ]
    for idx, (name, detail) in enumerate(ledger):
        y = 2.03 + idx * 0.84
        text(
            slide, name, 5.02, y, 1.2, 0.24, size=10, color=COBALT, bold=True, font="Helvetica Neue"
        )
        text(slide, detail, 6.35, y - 0.01, 5.98, 0.38, size=11.2, color=TEXT, bold=idx == 0)
        rule(slide, 5.02, y + 0.56, 7.43)

    # 12 — Close and roadmap
    slide = new_slide(
        prs,
        12,
        "价值与路线",
        "从“看起来能跑”，到“证据足够发布”",
        "AgentRig 不替 Agent 做决定；它让每个决定都能回归、门禁与审计。",
    )
    text(
        slide,
        "Evidence before confidence.",
        0.78,
        2.12,
        11.76,
        0.58,
        size=30,
        color=INK,
        bold=True,
        font="Helvetica Neue",
        align=PP_ALIGN.CENTER,
    )
    text(
        slide,
        "不同企业 Agent 共用的开源质量与发布基础设施",
        0.78,
        2.98,
        11.76,
        0.34,
        size=14,
        color=MUTED,
        align=PP_ALIGN.CENTER,
    )
    rule(slide, 1.05, 4.0, 11.15, color="BFC7C2", height_pt=1.2)
    roadmap = [
        (1.1, "现在", "三 Agent 协作\n成功 / 回归证据\n开源工程包", COBALT),
        (5.0, "下一阶段", "可执行 Trace 报告\n恢复 / 性能指标\n版本对比", GREEN),
        (8.95, "规模化", "PostgreSQL / K8s\nOTel / SLS\n发布门禁", AMBER),
    ]
    for x, phase, detail, accent in roadmap:
        marker(slide, "", x, 3.78, fill=accent, size=0.43)
        text(slide, phase, x - 0.05, 4.48, 2.7, 0.28, size=14.5, color=INK, bold=True)
        text(slide, detail, x - 0.05, 4.95, 2.7, 0.78, size=10.5, color=MUTED, line_spacing=1.22)
    box(slide, 3.78, 6.13, 5.78, 0.62, fill=COBALT, stroke=None)
    text(
        slide,
        "让每次变化，都留下可核验的证据",
        3.78,
        6.14,
        5.78,
        0.6,
        size=14,
        color=WHITE,
        bold=True,
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
    )

    # 13 — Appendix: identities
    slide = new_slide(
        prs,
        13,
        "评审附录 A",
        "三个 Agent 的身份合同",
        "输入、输出、依赖、边界与追踪字段可与代码、MCP 路由和运行轨迹交叉核验。",
    )
    columns = [0.58, 1.83, 5.48, 9.13, 12.75]
    headers = ["字段", "Evaluation Manager", "Simulation Curator", "Evidence Judge"]
    box(slide, 0.58, 1.94, 12.17, 0.58, fill=DARK, stroke=None)
    for idx, header in enumerate(headers):
        text(
            slide,
            header,
            columns[idx] + 0.12,
            2.13,
            columns[idx + 1] - columns[idx] - 0.24,
            0.2,
            size=8.5 if idx else 8,
            color=WHITE if idx else "A9B0AC",
            bold=True,
        )
    identity_rows = [
        ("角色", "面向用户的评测编排", "受控工具结果生成", "基于证据的独立裁决"),
        (
            "能力",
            "资产选择 / 计划 / 审批 / 诊断",
            "最小合理且 Schema 合法的候选",
            "pass / fail / inconclusive + 引用",
        ),
        (
            "输入",
            "会话 / 目标 / 权威资产事实",
            "tool / args / schema / 脱敏历史",
            "冻结 rubric / Rule / 脱敏证据",
        ),
        (
            "输出",
            "Plan / Decision / Run 引用",
            "CuratorGeneration / 结构化失败",
            "JudgeOutput / criteria / refs",
        ),
        (
            "依赖",
            "6 Manager Skills / MCP / Core",
            "simulate-tool-result / Worker MCP",
            "judge-evidence / Worker MCP",
        ),
        (
            "决策边界",
            "不能原始 run_cases；提交绑定 event + revision",
            "看不到 rubric；不调真实工具",
            "不造证据；不足必须 inconclusive",
        ),
        (
            "审计追踪",
            "AssistantEvent / Plan / Run / Matrix IDs",
            "invocation / hash / event IDs",
            "evaluation / hash / evidence refs",
        ),
    ]
    row_y = 2.52
    row_h = 0.59
    for row_idx, row in enumerate(identity_rows):
        if row_idx % 2 == 0:
            box(slide, 0.58, row_y, 12.17, row_h, fill=WHITE, stroke=None)
        for col_idx, value in enumerate(row):
            text(
                slide,
                value,
                columns[col_idx] + 0.12,
                row_y + 0.13,
                columns[col_idx + 1] - columns[col_idx] - 0.24,
                row_h - 0.2,
                size=7.3 if col_idx else 8,
                color=TEXT if col_idx else COBALT,
                bold=col_idx == 0,
                line_spacing=1.08,
            )
        rule(slide, 0.58, row_y + row_h, 12.17)
        row_y += row_h
    for x in columns[1:-1]:
        v_rule(slide, x, 1.94, row_y - 1.94, color=LINE)
    text(
        slide,
        "完整身份清单：docs/competition/02-Agent-Identity-清单.md",
        0.58,
        6.78,
        12.17,
        0.18,
        size=7.5,
        color=MUTED,
    )

    # 14 — Appendix: skill contracts
    slide = new_slide(
        prs,
        14,
        "评审附录 B",
        "11 个 Skill 如何被工程化",
        "不是名称清单：每个核心 Skill 都定义调用、失败、安全、验证与版本边界。",
    )
    text(
        slide,
        "Skill inventory",
        0.68,
        2.0,
        4.5,
        0.3,
        size=16,
        color=INK,
        bold=True,
        font="Helvetica Neue",
    )
    skill_groups = [
        (
            "Manager / 6",
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
        ("Workers / 2", ["simulate-tool-result", "judge-evidence"], GREEN),
        ("Core / 3", ["run-test-cases", "build-test-case", "harvest-tool-samples"], AMBER),
    ]
    y = 2.55
    for label, values, accent in skill_groups:
        text(
            slide,
            label,
            0.68,
            y,
            1.28,
            0.2,
            size=8.5,
            color=accent,
            bold=True,
            font="Helvetica Neue",
        )
        for idx, value in enumerate(values):
            text(
                slide,
                value,
                2.05,
                y + idx * 0.34,
                3.12,
                0.19,
                size=7.7,
                color=TEXT,
                bold=True,
                font="Menlo",
            )
        y += max(0.82, len(values) * 0.34 + 0.28)
    v_rule(slide, 5.45, 1.98, 4.8, color=LINE)
    text(
        slide,
        "Official contract fields",
        5.82,
        2.0,
        5.9,
        0.3,
        size=16,
        color=INK,
        bold=True,
        font="Helvetica Neue",
    )
    fields = [
        "名称 / 类型",
        "使用场景",
        "输入参数",
        "输出结果",
        "调用条件",
        "依赖工具",
        "失败处理",
        "安全边界",
        "验证 / 复用",
        "版本 / 回滚",
    ]
    for idx, value in enumerate(fields):
        col = idx % 2
        row = idx // 2
        x = 5.82 + col * 3.25
        yy = 2.58 + row * 0.51
        text(
            slide,
            f"{idx + 1:02d}",
            x,
            yy + 0.02,
            0.34,
            0.18,
            size=7,
            color=FAINT,
            font="Helvetica Neue",
        )
        text(slide, value, x + 0.44, yy, 2.55, 0.22, size=9.5, color=TEXT, bold=True)
        rule(slide, x, yy + 0.33, 2.92)
    box(slide, 5.82, 5.52, 6.57, 0.98, fill=COBALT_SOFT, stroke=None)
    text(slide, "版本与回滚", 6.07, 5.76, 1.28, 0.22, size=9.5, color=COBALT, bold=True)
    text(
        slide,
        "随 AgentRig 0.2.0a0 进入 Git；锁定 AgentTeams v1.1.2；回滚完整 Release + 角色包，不热替换临场 Prompt。",
        7.42,
        5.71,
        4.68,
        0.48,
        size=8.6,
        color=TEXT,
        bold=True,
    )
    text(
        slide,
        "完整逐 Skill 字段表：docs/competition/08-Skill-清单.md",
        5.82,
        6.71,
        6.5,
        0.18,
        size=7.5,
        color=MUTED,
    )

    # 15 — Appendix: verification
    slide = new_slide(
        prs,
        15,
        "评审附录 C",
        "上下文能力与当前验证台账",
        "赛题要求四选二；AgentRig 已实现记忆、共享状态和轨迹可观测三项。",
    )
    text(
        slide,
        "Context capabilities",
        0.7,
        2.0,
        4.8,
        0.3,
        size=16,
        color=INK,
        bold=True,
        font="Helvetica Neue",
    )
    context_rows = [
        ("Agent 记忆", "已实现", "Session / Turn / Event"),
        ("知识库 RAG", "未采用", "当前评测场景不需要"),
        ("共享状态", "已实现", "Plan / Invocation / Run"),
        ("轨迹可观测", "已实现", "RunEvent / Eval / Matrix IDs / hash"),
    ]
    for idx, (name, state, detail) in enumerate(context_rows):
        y = 2.56 + idx * 0.78
        text(slide, name, 0.7, y, 1.5, 0.23, size=10.5, color=TEXT, bold=True)
        text(
            slide,
            state,
            2.35,
            y,
            0.7,
            0.23,
            size=8.5,
            color=GREEN if state == "已实现" else FAINT,
            bold=True,
        )
        text(slide, detail, 3.18, y, 2.2, 0.36, size=8.8, color=MUTED)
        rule(slide, 0.7, y + 0.49, 4.68)
    v_rule(slide, 5.7, 1.98, 4.54, color=LINE)
    text(
        slide,
        "Verification ledger",
        6.06,
        2.0,
        6.24,
        0.3,
        size=16,
        color=INK,
        bold=True,
        font="Helvetica Neue",
    )
    evidence_rows = [
        ("Backend", "134 passed", "6 skipped / 1 deprecation warning"),
        ("Web", "30 unit + 2 E2E", "typecheck / coverage / build passed"),
        ("Reference demo", "3 scenarios", "success / policy regression / recovery"),
        ("Secret scan", "0 findings", "Gitleaks 8.29.1 + fixture sanity"),
        ("Worker receipts", "2 directions", "Curator + Judge / Matrix event IDs"),
    ]
    for idx, (name, value, detail) in enumerate(evidence_rows):
        y = 2.56 + idx * 0.68
        text(
            slide, name, 6.06, y, 1.42, 0.22, size=9.5, color=TEXT, bold=True, font="Helvetica Neue"
        )
        text(
            slide,
            value,
            7.62,
            y,
            1.62,
            0.22,
            size=9.2,
            color=COBALT if idx < 3 else GREEN,
            bold=True,
            font="Helvetica Neue",
        )
        text(slide, detail, 9.38, y, 2.93, 0.33, size=8.1, color=MUTED)
        rule(slide, 6.06, y + 0.42, 6.24)
    box(slide, 0.7, 6.3, 11.6, 0.48, fill=CORAL_SOFT, stroke=None)
    text(
        slide,
        "边界：未把云端 OTel/SLS、Kubernetes 与公开 Release/Tag 伪装为已完成。",
        0.92,
        6.43,
        11.15,
        0.2,
        size=9,
        color=CORAL,
        bold=True,
        align=PP_ALIGN.CENTER,
    )

    return prs


def main() -> None:
    presentation = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
