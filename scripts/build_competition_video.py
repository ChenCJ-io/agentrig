#!/usr/bin/env python3
"""Build the long-form AgentRig GOAI review cut with fixed 1080p frames.

The video deliberately uses no zoom, pan, cursor replay, or simulated typing. Every
product frame is either a page from the submitted deck or a real capture backed by the
formal recording database (browser screenshots and the Codex terminal session).
Narration is synthesized locally.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import edge_tts
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
COMPETITION_DIR = ROOT / "docs" / "competition"
LIVE_DIR = COMPETITION_DIR / "assets" / "live"
DECK_PDF = COMPETITION_DIR / "AgentRig-GOAI-2026-初赛方案.pdf"
MEDIA_DIR = ROOT / "dist" / "competition" / "media"
DEFAULT_OUTPUT = MEDIA_DIR / "AgentRig-GOAI-2026-Demo.mp4"


@dataclass(frozen=True)
class Scene:
    source: str
    title: str
    narration: str


SCENES = (
    Scene(
        "slide:1",
        "一次 Prompt 修改，怎样获得发布证据",
        "一个 Agent 的 Prompt 只改一行，也可能同时改变工具选择、参数传播、调用顺序、结果引用和最终回答。"
        "一次演示成功，不能证明回归稳定。AgentRig 要做的，是让每次变化都留下可重复、可比较、可归因的发布证据。"
        "本片使用公开的 EditFlow 修图 Agent，展示一条已经正式录制通过、可从干净状态完整复现的闭环。",
    ),
    Scene(
        "slide:3",
        "Agent 回归的真实难题",
        "Agent 的风险不只在最终文字。它可能选错工具、遗漏前置检查、编造素材标识、丢失人物保护约束，"
        "或者把旧图片引用传给下一步。真实工具回归又可能生成图片、发信、支付或写入生产，重复执行昂贵且有风险；"
        "纯 Mock 则绕过模型推理、协议和工具选择。我们需要同时保留决策真实性，并控制执行副作用。",
    ),
    Scene(
        "slide:4",
        "AgentRig 不替 Agent 回答",
        "被测 Agent 仍然使用自己的模型，真实完成 HTTP 或 SSE 会话、上下文维护、工具选择和参数生成。"
        "AgentRig 只在工具边界提供 Fixture、经审核的 Sample、Simulator 或 Real Tool，并独立记录 Manifest、"
        "Cell、Attempt 和事件。事实与 Rule、Judge、人工审核的裁决分离，因此一次失败可以被解释，而不是被一张总分遮住。",
    ),
    Scene(
        "slide:5",
        "从身份到发布门禁",
        "AgentRig 先冻结 Target、模型可见 Prompt、工具能力和版本身份；Case、Profile 与 Sample 定义风险和成本边界；"
        "Preview 生成 Canonical Manifest，Run 再展开 Cell 和独立 Attempt。每次工具调用、结果来源与裁决都进入 Timeline，"
        "最终 Report 和 Release Gate 引用同一条证据链。修复会创建新的 Run，绝不覆盖原始失败。",
    ),
    Scene(
        "slide:6",
        "Codex 主入口与 Web 辅助入口",
        "开发者在 EditFlow 项目中启动 Codex。Codex 能读取代码和 Prompt Diff，执行项目 Skill，并通过 AgentRig MCP"
        "查询、创建和运行评测资产。普通用户则可以在 AgentRig Web 助手中用自然语言生成自己的计划。"
        "两种模型上下文不同，给出不同方案完全允许；统一的是 Target、Case、Profile、人工确认和证据合同，"
        "而不是强迫它们得到同一份计划。",
    ),
    Scene(
        "slide:8",
        "三职能 Agent 与真实协同",
        "多 Agent 协同以 AgentTeams 为设计基点：Evaluation Manager 负责目标理解与计划，"
        "Simulation Curator 生成受控模拟结果，Evidence Judge 做独立语义裁决。"
        "三角色的完整协同闭环已在 AgentTeams 早期版本中真实运行；Manager 常驻规划，"
        "Curator 和 Judge 按场景条件触发，确定性规则与固定结果是低成本快速路径。"
        "每个结论都进入同一条证据合同。",
    ),
    Scene(
        "slide:9",
        "公开可复现的真实被测 Agent",
        "EditFlow 基于 Agno 和 DeepSeek，使用 PostgreSQL 保存 Session，通过 HTTP 和 SSE 暴露 Target，"
        "并把五个修图工具交给 external execution。模型推理、协议、会话和工具决策都是真实的；"
        "公开本地 MCP 返回确定性图片引用，不上传任何图片，也不调用第三方图片接口。"
        "这样既保留真实决策难度，又能让评委在本地复现。",
    ),
    Scene(
        "slide:10",
        "Before 暴露模型方差",
        "headline Case 要求一步完成调亮、雪山背景、四比五裁剪，并保持人物。Broad Prompt 允许自由修图工具"
        "吞并组合编辑。对同一个冻结 Case 和 Manifest 连续执行五个独立 Attempt，只有两次通过，"
        "三次因为 inspect image 落在 retouch 之后而行为失败。父 Run 虽然 completed，业务验收仍是 fail。"
        "这说明跑一次成功远远不够。",
    ),
    Scene(
        "slide:11",
        "Skill 把 Prompt Diff 变成风险资产",
        "Codex 先读取 prompt regression governance Skill，冻结 Git、Before Prompt SHA 和行为不变量，"
        "再通过 MCP 查询已有 Case。已有覆盖被标记为 Reuse，需要增强断言的标记为 Change，"
        "变更新增风险才创建 New，与本次修改无关的明确 Exclude。所有 Case 和 Sample 先是 Draft，"
        "创建者不能批准自己的资产。每次迭代最终沉淀为 PI 存档：变更前后 Prompt、身份、用例、Run 与指标，"
        "连同人话报告一起进入仓库，供审阅与追溯。",
    ),
    Scene(
        "slide:12",
        "最小 Prompt 修复与身份变化",
        "Codex 只修改模型可见边界：retouch photo 只负责亮度和对比度；背景素材必须搜索后应用；比例必须裁剪；"
        "每一步继续消费最新的 output image reference，人物保护传播到相关工具。HTTP 适配层没有增加关键词路由，"
        "也没有为录制写死答案。重启后 Prompt SHA 从四三一五七开头变为七一一艾迪比开头；SHA 不变，Candidate 就没有验收资格。",
    ),
    Scene(
        "live:editflow-02-candidate-run.png",
        "Candidate 与完整回归矩阵",
        "Candidate 先对相同 headline Case 再跑五次，从二比三变成五比零。随后执行六个相关 Case、"
        "每个五次，共三十个独立 Attempt，三十次全部通过。简单调亮没有过度路由，素材搜索为空时没有编造 asset ID，"
        "人物保护和图片引用按契约传播。这里展示的是 Run、Cell 和 Attempt 的真实矩阵，而不是手工拼接的绿色数字。",
    ),
    Scene(
        "live:editflow-03-timeline.png",
        "下钻到内部行为",
        "AgentRig 不只判断最终文字。完整 Timeline 记录 inspect image、search assets、retouch photo、apply asset"
        "和 crop photo 的顺序，保留每个参数、Provider 来源和工具结果。素材 ID 可以追溯到搜索返回，"
        "preserve subject 在相关工具中保持为真，image reference 每一步都来自前一步输出。"
        "评委可以直接看到 Agent 做了什么，以及为什么通过。",
    ),
    Scene(
        "slide:15",
        "一次真实采集，五次零真实调用重放",
        "对于必须观察真实结果的工具，AgentRig 先通过本地 MCP 执行一次 inspect image，并把 source 等于 real tool"
        "的事件持久化。Codex 只能从这条事件创建 Sample 草稿；人类确认来源和适用边界后批准。"
        "Sample-only Profile 随后回放五次，五次全部命中 Sample，而这个 Replay Run 中 real tool Provider Attempt 为零。"
        "真实来源、人工责任和回归成本因此同时可审计。",
    ),
    Scene(
        "live:editflow-05-assistant.png",
        "普通用户自然语言发起",
        "不使用 Codex 的产品或测试人员，也可以在 Web 助手中描述评测目标。模型生成一个 Case、三次 Attempt 的可编辑计划。"
        "因为重复执行会消耗资源，Core 触发人工确认；确认只解除门禁，仍不创建 Run，另一次提交才真正执行。"
        "最终三个 Attempt 全部通过。不同入口共享的是可治理资产和证据结构，不是同一种语言模型能力。",
    ),
    Scene(
        "slide:17",
        "为什么这是平台，不是 Demo 脚本",
        "AgentRig 用 Driver 接入 HTTP SSE、OpenAI compatible、AgentScope 和 AG UI；用 Provider Chain 在 Fixture、"
        "审核 Sample、Simulator 与 Real Tool 之间切换；用 Canonical Manifest、Cell、Attempt、Event 和 Timeline"
        "形成事实内核；再由 Rule、Judge、人工审核、报告和 Release Gate 消费证据。"
        "项目隔离、耐久任务、审计日志、生产 Trace 回灌和失败模式让闭环可以进入团队工程。",
    ),
    Scene(
        "slide:18",
        "从 AgentScope 实践到开源合同",
        "AgentRig 与 AgentScope 来自同一类真实评测实践：真实生产 Agent 工程中沉淀了十余个评测与治理 Skill，覆盖用例构建、回归执行、会话挖掘与样本采集。不同之处是，AgentRig 把内部依赖"
        "抽成协议无关、可本地部署、可独立组合的开源合同。公开 EditFlow 证明流程可以复现；真实 lassist 兼容验收作为附录，"
        "证明平台并不只适配一个专门为比赛构建的 Demo Agent。AgentTeams 多角色只在动态策展或语义裁决真正需要时启用。",
    ),
    Scene(
        "slide:19",
        "真实生产项目中的常态使用",
        "这套 Skill 治理不是为比赛准备的演示：在真实生产 Agent 工程中，同一个提示词回归治理 Skill "
        "驱动完成了 Router 上线捆绑的四表面描述瘦身——五十五个 Cell 的正式矩阵、两千零六十四项单测基线、"
        "四轮实证输入修正与 before 归因闭环，最终以硬性规则二十比二十、带披露的 ACCEPT 报告归档。",
    ),
    Scene(
        "slide:22",
        "证据化结论与诚实边界",
        "本次正式录制得到 Before 二比三、Candidate headline 五比零、最终矩阵三十比零、Sample replay 五比零、"
        "Web 助手三比零，EditFlow 三十四项非 Live 测试通过，真实浏览器可访问性没有严重或致命问题。"
        "全部 Run ID 来自干净录制库并记录在台账中，Sample 只声明覆盖 inspect image，动态引用等值以 Timeline 为准。"
        "Codex 负责思考和改变软件，AgentRig 负责让每次改变可复用、可执行、可追溯。",
    ),
)


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def ffmpeg_duration(ffmpeg: str, media: Path) -> float:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(media)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", result.stdout)
    if not match:
        raise RuntimeError(f"Could not read duration from {media}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def render_deck_pages(work_dir: Path) -> dict[int, Path]:
    if not DECK_PDF.is_file():
        raise FileNotFoundError(f"Missing deck PDF: {DECK_PDF}")
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("pdftoppm is required to render the deck pages")
    run([pdftoppm, "-png", "-r", "144", str(DECK_PDF), str(work_dir / "deck")])
    pages: dict[int, Path] = {}
    for path in work_dir.glob("deck-*.png"):
        match = re.search(r"-(\d+)\.png$", path.name)
        if match:
            pages[int(match.group(1))] = path
    if len(pages) != 22:
        raise RuntimeError(f"Expected 22 rendered deck pages, got {len(pages)}")
    return pages


def source_image(scene: Scene, pages: dict[int, Path]) -> Path:
    if scene.source.startswith("slide:"):
        path = pages[int(scene.source.removeprefix("slide:"))]
    elif scene.source.startswith("live:"):
        path = LIVE_DIR / scene.source.removeprefix("live:")
    else:
        raise ValueError(f"Unsupported scene source: {scene.source}")
    if not path.is_file():
        raise FileNotFoundError(f"Missing scene image: {path}")
    return path


async def synthesize_narration(
    text: str,
    output: Path,
    *,
    voice: str,
    rate: str,
    pitch: str,
    attempts: int = 4,
) -> None:
    # The Edge speech endpoint intermittently drops streams mid-session;
    # retry with backoff before giving up on the whole build.
    for attempt in range(1, attempts + 1):
        try:
            communicator = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
            await communicator.save(str(output))
            if output.is_file() and output.stat().st_size > 0:
                return
            raise RuntimeError("edge-tts produced an empty audio file")
        except Exception:
            if attempt == attempts:
                raise
            await asyncio.sleep(2 * attempt)



# Applied to narration audio only; subtitles keep the on-screen terminology.
# Ordered: longer phrases first. Chinese entries fix polyphones via homophones;
# English entries map jargon to natural spoken Chinese (product names stay).
SPEECH_LEXICON = (
    # polyphone fixes
    ("一行", "一航"),
    ("调亮", "条亮"),
    # multi-word phrases
    ("prompt regression governance Skill", "提示词回归治理技能"),
    ("Canonical Manifest", "规范执行清单"),
    ("Sample-only Profile", "仅样本执行配置"),
    ("real tool Provider Attempt", "真实工具尝试"),
    ("Provider Chain", "结果提供链"),
    ("Release Gate", "发布门禁"),
    ("Broad Prompt", "宽泛提示词"),
    ("headline Case", "主线用例"),
    ("output image reference", "输出图片引用"),
    ("preserve subject", "人物保护约束"),
    ("inspect image", "图片检查"),
    ("search assets", "素材搜索"),
    ("retouch photo", "修图工具"),
    ("apply asset", "素材应用"),
    ("crop photo", "裁剪工具"),
    ("asset ID", "素材编号"),
    ("OpenAI compatible", "OpenAI 兼容"),
    ("external execution", "外部执行"),
    ("PostgreSQL", "数据库"),
    ("Web 助手", "网页助手"),
    # verdict / lifecycle words
    ("completed", "已完成"),
    ("ACCEPT", "验收通过"),
    ("Candidate", "改后版本"),
    ("Before", "改前版本"),
    # single terms
    ("Prompt Diff", "提示词差异"),
    ("Real Tool", "真实工具"),
    ("real tool", "真实工具"),
    ("Prompt", "提示词"),
    ("Fixture", "固定结果"),
    ("Simulator", "模拟器"),
    ("Sample", "样本"),
    ("Manifest", "执行清单"),
    ("Timeline", "时间线"),
    ("Attempt", "尝试"),
    ("Profile", "执行配置"),
    ("Preview", "预览"),
    ("Provider", "结果来源"),
    ("headline", "主线"),
    ("Driver", "驱动层"),
    ("Event", "事件"),
    ("Trace", "轨迹"),
    ("Draft", "草稿"),
    ("Judge", "裁判"),
    ("Rule", "规则"),
    ("Skill", "技能"),
    ("Case", "用例"),
    ("Cell", "单元"),
    ("retouch", "修图"),
    ("before", "改前"),
    ("source", "来源"),
    ("fail", "失败"),
    ("Run", "运行"),
    ("Gate", "门禁"),
    # acronyms: force letter-by-letter reading
    ("HTTP", "H T T P"),
    ("SSE", "S S E"),
    ("AG UI", "A G U I"),
    ("SHA", "S H A"),
)


def speech_text(value: str) -> str:
    for term, spoken in SPEECH_LEXICON:
        if term.isascii():
            value = re.sub(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", spoken, value)
        else:
            value = value.replace(term, spoken)
    return value


_KOKORO_PIPELINE = None


def synthesize_kokoro_narration(value: str, output: Path, *, voice: str, speed: float = 0.82) -> None:
    """Local neural TTS (Kokoro-82M-v1.1-zh) with English terms via misaki G2P."""
    global _KOKORO_PIPELINE
    import numpy as np
    import soundfile as sf

    if _KOKORO_PIPELINE is None:
        from kokoro import KModel, KPipeline
        from misaki import en

        repo = "hexgrad/Kokoro-82M-v1.1-zh"
        english = en.G2P(trf=False, british=False, fallback=None)

        def en_callable(text: str) -> str:
            result = english(text)
            return result[0] if isinstance(result, tuple) else str(result)

        model = KModel(repo_id=repo).to("cpu").eval()
        _KOKORO_PIPELINE = KPipeline(
            lang_code="z", repo_id=repo, model=model, en_callable=en_callable
        )
    value = speech_text(value)
    chunks = [result.audio.numpy() for result in _KOKORO_PIPELINE(value, voice=voice, speed=speed)]
    if not chunks:
        raise RuntimeError("kokoro produced no audio")
    sf.write(str(output), np.concatenate(chunks), 24000)


def synthesize_macos_narration(
    value: str,
    output: Path,
    *,
    voice: str,
    rate: int,
) -> None:
    binary = shutil.which("say")
    if not binary:
        raise RuntimeError("macOS say is required for --engine macos")
    run([binary, "-v", voice, "-r", str(rate), "-o", str(output), value])


def srt_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def split_caption(value: str, max_chars: int = 23) -> list[str]:
    clauses = [
        part.strip() for part in re.findall(r"[^。！？；]+[。！？；]?", value) if part.strip()
    ]
    cues: list[str] = []
    for clause in clauses:
        remainder = clause
        while len(remainder) > max_chars:
            positions = [remainder.rfind(mark, 0, max_chars + 1) for mark in "，：、 "]
            best = max(positions)
            cut = best + 1 if best >= max_chars // 2 else max_chars
            cues.append(remainder[:cut].strip())
            remainder = remainder[cut:].strip()
        if remainder:
            cues.append(remainder)
    return cues


def scene_cues(
    scene: Scene, narration_duration: float, offset: float = 0.0
) -> list[tuple[float, float, str]]:
    values = split_caption(scene.narration)
    weights = [max(1, len(re.sub(r"\s+", "", value))) for value in values]
    total = sum(weights)
    cursor = offset + 0.5
    result: list[tuple[float, float, str]] = []
    for value, weight in zip(values, weights, strict=True):
        duration = narration_duration * weight / total
        result.append((cursor, cursor + duration, value))
        cursor += duration
    return result


def write_srt(cues: list[tuple[float, float, str]], output: Path) -> None:
    lines: list[str] = []
    for index, (start, end, value) in enumerate(cues, start=1):
        lines.extend([str(index), f"{srt_timestamp(start)} --> {srt_timestamp(end)}", value, ""])
    output.write_text("\n".join(lines), encoding="utf-8")


def escape_filter_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def drawtext_filters(cues: list[tuple[float, float, str]], work_dir: Path, index: int) -> str:
    font = Path("/System/Library/Fonts/STHeiti Medium.ttc")
    if not font.is_file():
        raise FileNotFoundError(f"Required Chinese subtitle font is unavailable: {font}")
    filters: list[str] = []
    for cue_index, (start, end, value) in enumerate(cues, start=1):
        text_file = work_dir / f"subtitle-{index:02d}-{cue_index:02d}.txt"
        text_file.write_text(value, encoding="utf-8")
        filters.append(
            "drawtext="
            f"fontfile='{escape_filter_path(font)}':"
            f"textfile='{escape_filter_path(text_file)}':"
            "fontcolor=white:fontsize=42:"
            "box=1:boxcolor=black@0.64:boxborderw=16:"
            "x=(w-text_w)/2:y=h-104:"
            f"enable='between(t,{start:.3f},{end:.3f})'"
        )
    return ",".join(filters)


def build_scene(
    ffmpeg: str,
    *,
    image: Path,
    audio: Path,
    cues: list[tuple[float, float, str]],
    work_dir: Path,
    index: int,
    duration: float,
    output: Path,
) -> None:
    subtitle_filter = drawtext_filters(cues, work_dir, index)
    # A looped still image is intentional: no zoompan, no cursor tweening and no
    # stabilization guesswork. The upper product frame therefore remains pixel-stable.
    video_filter = (
        "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0xF4F5F3,"
        f"fps=30,format=yuv420p,{subtitle_filter}[v];"
        f"[1:a]adelay=500|500,apad,atrim=0:{duration:.3f},"
        "afade=t=in:st=0:d=0.08,afade=t=out:st="
        f"{max(0.1, duration - 0.18):.3f}:d=0.12,"
        "loudnorm=I=-16:TP=-1.5:LRA=9[a]"
    )
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(image),
            "-i",
            str(audio),
            "-filter_complex",
            video_filter,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            f"{duration:.3f}",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-level",
            "4.1",
            "-preset",
            "slow",
            "-crf",
            "17",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


def concat_scenes(ffmpeg: str, scenes: list[Path], work_dir: Path, output: Path) -> None:
    manifest = work_dir / "concat.txt"
    manifest.write_text(
        "\n".join(f"file '{path.as_posix()}'" for path in scenes) + "\n",
        encoding="utf-8",
    )
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--engine", choices=("edge", "macos", "kokoro"), default="edge")
    parser.add_argument("--kokoro-voice", default="zm_010")
    parser.add_argument("--kokoro-speed", type=float, default=0.82)
    parser.add_argument("--voice", default="zh-CN-YunxiNeural")
    parser.add_argument("--rate", default="-4%")
    parser.add_argument("--pitch", default="-2Hz")
    parser.add_argument("--macos-voice", default="Eddy (中文（中国大陆）)")
    parser.add_argument("--macos-rate", type=int, default=165)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    srt_output = output.with_suffix(".srt")
    metadata_output = output.with_suffix(".json")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    scene_metadata: list[dict[str, object]] = []
    global_cues: list[tuple[float, float, str]] = []
    timeline = 0.0
    with tempfile.TemporaryDirectory(prefix="agentrig-video-") as temp:
        work_dir = Path(temp)
        pages = render_deck_pages(work_dir)
        scene_files: list[Path] = []
        for index, scene in enumerate(SCENES, start=1):
            print(f"Synthesizing scene {index:02d}/{len(SCENES)}: {scene.title}", flush=True)
            if args.engine == "edge":
                audio = work_dir / f"narration-{index:02d}.mp3"
                asyncio.run(
                    synthesize_narration(
                        scene.narration,
                        audio,
                        voice=args.voice,
                        rate=args.rate,
                        pitch=args.pitch,
                    )
                )
            elif args.engine == "kokoro":
                audio = work_dir / f"narration-{index:02d}.wav"
                synthesize_kokoro_narration(
                    scene.narration, audio, voice=args.kokoro_voice, speed=args.kokoro_speed
                )
            else:
                audio = work_dir / f"narration-{index:02d}.aiff"
                synthesize_macos_narration(
                    scene.narration,
                    audio,
                    voice=args.macos_voice,
                    rate=args.macos_rate,
                )
            narration_duration = ffmpeg_duration(ffmpeg, audio)
            duration = math.ceil((narration_duration + 1.7) * 2) / 2
            local_srt = work_dir / f"scene-{index:02d}.srt"
            local_cues = scene_cues(scene, narration_duration)
            write_srt(local_cues, local_srt)
            global_cues.extend(
                (start + timeline, end + timeline, value) for start, end, value in local_cues
            )

            scene_output = work_dir / f"scene-{index:02d}.mp4"
            build_scene(
                ffmpeg,
                image=source_image(scene, pages),
                audio=audio,
                cues=local_cues,
                work_dir=work_dir,
                index=index,
                duration=duration,
                output=scene_output,
            )
            scene_files.append(scene_output)
            scene_metadata.append(
                {
                    "index": index,
                    "title": scene.title,
                    "source": scene.source,
                    "start_seconds": round(timeline, 3),
                    "duration_seconds": duration,
                    "narration_seconds": round(narration_duration, 3),
                }
            )
            timeline += duration

        write_srt(global_cues, srt_output)
        concat_scenes(ffmpeg, scene_files, work_dir, output)

    actual_duration = ffmpeg_duration(ffmpeg, output)
    metadata = {
        "schema_version": "agentrig.competition-video.v3",
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "output": output.name,
        "sha256": sha256(output),
        "duration_seconds": round(actual_duration, 3),
        "resolution": "1920x1080",
        "fps": 30,
        "video": "H.264 High / CRF 17 / yuv420p",
        "audio": "AAC 192 kbps / 48 kHz / stereo / -16 LUFS target",
        "narration": (
            {
                "engine": "edge-tts",
                "voice": args.voice,
                "rate": args.rate,
                "pitch": args.pitch,
            }
            if args.engine == "edge"
            else {
                "engine": "kokoro-local",
                "voice": args.kokoro_voice,
                "speed": args.kokoro_speed,
                "model": "hexgrad/Kokoro-82M-v1.1-zh",
                "purpose": "local neural narration; fully offline and reproducible",
                "speech_lexicon": "polyphone fixes + spoken-Chinese jargon mapping (audio only)",
            }
            if args.engine == "kokoro"
            else {
                "engine": "macos-say",
                "voice": args.macos_voice,
                "rate_words_per_minute": args.macos_rate,
                "purpose": "local review fallback; formal cut prefers human narration",
            }
        ),
        "camera_motion": "none; fixed source frame per scene",
        "cut_purpose": (
            "formal agent-led recording; stills and IDs come from the clean 2026-08-14 "
            "recording database, narration is synthesized"
        ),
        "subtitles": srt_output.name,
        "scenes": scene_metadata,
    }
    metadata_output.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Built {output}")
    print(f"Subtitles {srt_output}")
    print(f"Metadata {metadata_output}")
    print(f"Duration {actual_duration:.2f}s ({actual_duration / 60:.2f} minutes)")


if __name__ == "__main__":
    main()
