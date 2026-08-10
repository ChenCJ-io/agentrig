#!/usr/bin/env python3
"""Build the GOAI competition demo video from verified UI captures and deck pages.

The build is deterministic apart from the macOS ``say`` voice synthesis. It creates a
6:55 H.264/AAC MP4 with burned Chinese subtitles plus a standalone SRT file.
"""

from __future__ import annotations

import argparse
import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
COMPETITION_DIR = ROOT / "docs" / "competition"
CAPTURE_DIR = COMPETITION_DIR / "assets" / "video"
DECK_PDF = COMPETITION_DIR / "AgentRig-GOAI-2026-初赛方案.pdf"
DEFAULT_OUTPUT = (
    ROOT / "dist" / "competition" / "GOAI-2026-AgentRig-初赛材料" / "AgentRig-GOAI-2026-Demo.mp4"
)


@dataclass(frozen=True)
class Scene:
    duration: int
    image: str
    narration: str


SCENES = (
    Scene(
        18,
        "slide-01.png",
        "Agent 不缺一次成功的 Demo，缺的是每次升级后都能回答：哪里变了，为什么通过，"
        "证据是什么。AgentRig 将一次性演示变成可持续回归的评测基础设施。",
    ),
    Scene(
        30,
        "slide-04.png",
        "这条真实路径中，AgentTeams Manager 负责理解目标和编排计划，Simulation Curator "
        "负责生成受控工具结果，Evidence Judge 负责依据冻结证据独立裁决。被测的 lassist "
        "是评测对象，不计入三个协作 Agent。",
    ),
    Scene(
        40,
        "04-approval-boundary.png",
        "用户只描述评测目标。Manager 查询已批准用例、Target 和 Profile，生成可预览计划。"
        "范围、数量、结果提供链和评判器都在提交前显式展示。确认必须绑定同会话的真实用户"
        "事件和同一 plan revision；没有确认，就没有 Run。",
    ),
    Scene(
        37,
        "03-agentteams-evidence.png",
        "Curator 和 Judge 是两个独立 Worker。AgentRig 保存 Matrix 的请求与响应事件 ID、"
        "输入输出 hash、结果引用和终态。这证明任务确实经过 AgentTeams 定向投递和 Worker "
        "回写，不是进程内的伪造捷径。",
    ),
    Scene(
        45,
        "05-success-evidence.png",
        "进入 Run 详情，可以看到完整事实链。用户要求背景增强，lassist 真实产生 "
        "apply image prompt 工具调用。这里展示的不是离线伪造日志，而是同一个 CaseRun 中的"
        "用户消息、驱动请求、工具调用和事件编号。",
    ),
    Scene(
        30,
        "06-success-overview.png",
        "Curator 只读取冻结的工具上下文，看不到 rubric。它返回的候选还要通过 JSON Schema "
        "和状态验证，才能作为受控 ToolResult 回注给被测 Agent。所有步骤都写入只追加的 "
        "RunEvent。",
    ),
    Scene(
        42,
        "05-success-evidence.png",
        "执行结束后，确定性 Rule 三项全部通过；Evidence Judge 又独立对三个语义标准判定 "
        "pass，并引用本次 Run 的真实 event ID。两份 Evaluation 相互独立，Judge 不能覆盖 "
        "Rule，也不能发明不存在的证据。",
    ),
    Scene(
        30,
        "07-policy-failure.png",
        "评测平台不应只演示绿灯。接下来切换到二次确认策略场景。这个用例要求图片编辑前先"
        "向用户明确确认；我们会故意保留一次产品策略回归，让失败路径同样可以被复现和审计。",
    ),
    Scene(
        50,
        "08-failure-evidence.png",
        "旧版 lassist 没有请求二次确认，就直接调用了编辑工具。即使 Curator 成功返回工具"
        "结果，Rule 的 tool not called 仍然失败，Judge 也引用同一工具事件判定 fail。Run 的"
        "执行状态是 completed，但评测结论是未通过；工具成功，不等于策略正确。",
    ),
    Scene(
        33,
        "slide-09.png",
        "故障也不会被抹掉。首次负向运行触发有界超时后，系统保留已有 RunEvent、Rule 失败和"
        "Curator 回执，不伪造尚未发生的 Judge 结论。修正配置后新建 Run，旧 Attempt 依然可"
        "审计，幂等恢复不会覆盖历史。",
    ),
    Scene(
        33,
        "slide-14.png",
        "AgentRig 共提供十一个可复用 Skill：六个 Manager Skill、两个 Worker Skill 和三个 "
        "Core Skill。每个核心 Skill 都声明输入输出、调用条件、依赖工具、失败处理、安全边界"
        "和版本回滚。三个角色使用物理隔离的 MCP 工具集，Prompt 不是权限边界。",
    ),
    Scene(
        27,
        "slide-12.png",
        "AgentTeams 负责谁与谁协作，AgentRig 负责什么是已经发生的事实。我们不替 Agent 做"
        "决定，而是让每个决定都经过分工、验证并留下证据，最终成为企业 Agent 的持续回归、"
        "发布门禁和审计基础设施。",
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


def render_deck_pages(work_dir: Path) -> None:
    if not DECK_PDF.exists():
        raise FileNotFoundError(f"Missing deck PDF: {DECK_PDF}")
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("pdftoppm is required to render the deck pages")
    run([pdftoppm, "-png", "-r", "144", str(DECK_PDF), str(work_dir / "slide")])


def source_image(scene: Scene, work_dir: Path) -> Path:
    if scene.image.startswith("slide-"):
        path = work_dir / scene.image
    else:
        path = CAPTURE_DIR / scene.image
    if not path.exists():
        raise FileNotFoundError(f"Missing scene image: {path}")
    return path


def synthesize_narration(scene: Scene, output: Path, voice: str, initial_rate: int) -> float:
    say = shutil.which("say")
    if not say:
        raise RuntimeError("macOS say is required to build the narration")

    rate = initial_rate
    for _ in range(3):
        run([say, "-v", voice, "-r", str(rate), "-o", str(output), scene.narration])
        duration = ffmpeg_duration(imageio_ffmpeg.get_ffmpeg_exe(), output)
        available = scene.duration - 1.0
        if duration <= available:
            return duration
        rate = math.ceil(rate * duration / available * 1.03)
    raise RuntimeError(
        f"Narration for {scene.image} is {duration:.2f}s, longer than {available:.2f}s"
    )


def build_scene(ffmpeg: str, scene: Scene, image: Path, audio: Path, output: Path) -> None:
    frames = scene.duration * 24
    video_filter = (
        "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x101216,"
        f"zoompan=z='min(zoom+0.00008,1.035)':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080:fps=24,"
        "format=yuv420p[v];"
        f"[1:a]adelay=600|600,apad,atrim=0:{scene.duration},"
        "loudnorm=I=-16:TP=-1.5:LRA=11[a]"
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
            "24",
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
            str(scene.duration),
            "-r",
            "24",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


def srt_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def subtitle_text(narration: str) -> str:
    replacements = {
        "plan revision": "EvaluationPlan revision",
        "Matrix 的请求与响应事件 ID": "Matrix request/response event ID",
        "apply image prompt": "apply_image_prompt",
        "只追加的 RunEvent": " append-only RunEvent",
        "确定性 Rule 三项全部通过": "Rule 3/3 全部通过",
        "真实 event ID": " Evidence refs（真实 event ID）",
        "tool not called": "tool_not_called",
        "Run 的执行状态是 completed，但评测结论是未通过": "completed ≠ pass",
        "幂等恢复": "idempotency 恢复",
    }
    text = narration
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def split_caption(text: str, max_chars: int = 25) -> list[str]:
    protected_terms = (
        "Matrix request/response event ID",
        "EvaluationPlan revision",
        "apply_image_prompt",
        "append-only RunEvent",
        "Rule 3/3",
        "Evidence refs",
        "completed ≠ pass",
    )
    placeholders = {f"§{index}§": term for index, term in enumerate(protected_terms)}
    for placeholder, term in placeholders.items():
        text = text.replace(term, placeholder)
    clauses = [
        item.strip() for item in re.findall(r"[^。！？；]+[。！？；]?", text) if item.strip()
    ]
    cues: list[str] = []
    for clause in clauses:
        remainder = clause
        while len(remainder) > max_chars:
            breakpoints = [remainder.rfind(mark, 0, max_chars + 1) for mark in "，：、 "]
            best = max(breakpoints)
            cut = best + 1 if best >= max_chars // 2 else max_chars
            cues.append(remainder[:cut].strip())
            remainder = remainder[cut:].strip()
        if remainder:
            cues.append(remainder)
    return [_restore_placeholders(cue, placeholders) for cue in cues]


def _restore_placeholders(text: str, placeholders: dict[str, str]) -> str:
    for placeholder, term in placeholders.items():
        text = text.replace(placeholder, term)
    return text


def build_srt(narration_durations: list[float], output: Path) -> None:
    lines: list[str] = []
    scene_start = 0.0
    cue_number = 1
    for scene, narration_duration in zip(SCENES, narration_durations, strict=True):
        cues = split_caption(subtitle_text(scene.narration))
        weights = [max(1, len(re.sub(r"\s+", "", cue))) for cue in cues]
        total_weight = sum(weights)
        cursor = scene_start + 0.6
        for cue, weight in zip(cues, weights, strict=True):
            cue_duration = narration_duration * weight / total_weight
            end = min(scene_start + scene.duration - 0.3, cursor + cue_duration)
            lines.extend(
                [
                    str(cue_number),
                    f"{srt_timestamp(cursor)} --> {srt_timestamp(end)}",
                    cue,
                    "",
                ]
            )
            cursor = end
            cue_number += 1
        scene_start += scene.duration
    output.write_text("\n".join(lines), encoding="utf-8")


def concat_scenes(ffmpeg: str, scene_files: list[Path], work_dir: Path, output: Path) -> None:
    concat_file = work_dir / "concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{path.as_posix()}'" for path in scene_files) + "\n",
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
            str(concat_file),
            "-c",
            "copy",
            str(output),
        ]
    )


def escape_filter_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def burn_subtitles(ffmpeg: str, source: Path, srt: Path, output: Path) -> None:
    subtitle_filter = (
        f"subtitles=filename='{escape_filter_path(srt)}':"
        "force_style='FontName=PingFang SC,FontSize=18,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=2,"
        "Shadow=1,MarginV=48,Alignment=2'"
    )
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-i",
            str(source),
            "-vf",
            subtitle_filter,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--voice", default="Tingting")
    parser.add_argument("--rate", type=int, default=165)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    srt_output = output.with_suffix(".srt")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    with tempfile.TemporaryDirectory(prefix="agentrig-video-") as temp:
        work_dir = Path(temp)
        render_deck_pages(work_dir)
        scene_files: list[Path] = []
        narration_durations: list[float] = []
        for index, scene in enumerate(SCENES, start=1):
            print(f"Building scene {index:02d}/{len(SCENES)} ({scene.duration}s)", flush=True)
            audio = work_dir / f"narration-{index:02d}.aiff"
            narration_durations.append(synthesize_narration(scene, audio, args.voice, args.rate))
            scene_output = work_dir / f"scene-{index:02d}.mp4"
            build_scene(ffmpeg, scene, source_image(scene, work_dir), audio, scene_output)
            scene_files.append(scene_output)

        build_srt(narration_durations, srt_output)
        joined = work_dir / "joined.mp4"
        concat_scenes(ffmpeg, scene_files, work_dir, joined)
        burn_subtitles(ffmpeg, joined, srt_output, output)

    duration = ffmpeg_duration(ffmpeg, output)
    print(f"Built {output}")
    print(f"Subtitles {srt_output}")
    print(f"Duration {duration:.2f}s ({duration / 60:.2f} minutes)")


if __name__ == "__main__":
    main()
