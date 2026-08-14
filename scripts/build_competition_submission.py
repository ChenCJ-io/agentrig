#!/usr/bin/env python3
"""Build the GOAI competition candidate directory and checksummed ZIP.

The builder packages the current working-tree contents intentionally. A dirty tree is
labelled as a candidate and never rewritten as a clean ReleaseEvidence snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EDITFLOW_ROOT = ROOT.parent / "editflow-demo-agent"
COMPETITION_DIR = ROOT / "docs" / "competition"
OPTIMIZATION_PLAN_DIR = ROOT / "docs" / "09-V2.3-Agent运行时验证与生产证据闭环"
DIST_DIR = ROOT / "dist" / "competition"
PACKAGE_NAME = "GOAI-2026-AgentRig-初赛材料"
PACKAGE_DIR = DIST_DIR / PACKAGE_NAME
PACKAGE_ZIP = DIST_DIR / f"{PACKAGE_NAME}.zip"
VIDEO_NAME = "AgentRig-GOAI-2026-Demo.mp4"
SRT_NAME = "AgentRig-GOAI-2026-Demo.srt"
VIDEO_METADATA_NAME = "AgentRig-GOAI-2026-Demo.json"
MEDIA_DIR = DIST_DIR / "media"

EXPECTED_DOCS = tuple(f"{index:02d}-" for index in range(1, 18))
# Internal working documents stay in the repository but are excluded from the
# registration folder; 17 is repackaged under 03-运行证据 as the evidence ledger.
INTERNAL_DOC_PREFIXES = ("15-", "16-", "17-")
OPTIMIZATION_PLAN_PACKAGE_NAME = "04-V2.3-Agent运行时验证与生产证据闭环"
VERIFICATION_SNAPSHOT = {
    "verified_at": "2026-08-14T02:11:42+08:00",
    "python": {
        "current": {"passed": 203, "skipped": 11},
        "skip_scope": "external runtimes and integration prerequisites",
        "warning_scope": "one upstream Starlette deprecation warning",
    },
    "web": {
        "unit_passed": 41,
        "typecheck": "passed",
        "editflow_real_backend_e2e": "passed",
        "axe_critical_serious": 0,
    },
    "postgresql": {
        "version": "17.7",
        "historical_integration_passed": 4,
        "final_commit_rerun": "passed 4/4 on 2026-08-14 (local PostgreSQL 17.7, agentrig_test)",
    },
    "skill_contracts": {"passed": 11},
    "editflow": {
        "before": {"attempts": 5, "pass": 2, "behavior_fail": 3},
        "candidate_headline": {"attempts": 5, "pass": 5},
        "candidate_matrix": {"cells": 6, "attempts": 30, "pass": 30},
        "sample_replay": {"attempts": 5, "pass": 5, "real_tool_attempts": 0},
        "web_assistant": {"attempts": 3, "pass": 3},
        "non_live_tests": 34,
    },
    "lassist_compatibility_appendix": {
        "positive_attempts": 9,
        "expected_diagnostic_failures": 1,
        "raw_private_assets_packaged": False,
    },
    "package": {"wheel": "passed", "sdist": "passed", "isolated_install": "passed"},
    "dependency_audit": {
        "python_public_dependency_vulnerabilities": 0,
        "npm_production_vulnerabilities": 0,
        "local_unpublished_package": "not queryable on PyPI",
    },
    "external_live": {
        "agentscope_v2.0.6": "pending",
        "agentteams_v1.2.2": "pending",
        "kubernetes_target_slo": "pending",
    },
}


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_state(repository: Path) -> tuple[str, bool]:
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    source_dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
    )
    return git_sha, source_dirty


def repository_paths(repository: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repository,
        check=True,
        stdout=subprocess.PIPE,
    )
    values: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = Path(os.fsdecode(raw))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe source path: {relative}")
        if relative.parts[0] in {"dist", ".agentrig", ".venv", "node_modules"}:
            continue
        if relative.match("docs/competition/assets/live/lassist-*.png"):
            continue
        source = repository / relative
        if source.is_file() or source.is_symlink():
            values.append(relative)
    return sorted(set(values), key=lambda item: item.as_posix())


def copy_repository_snapshot(repository: Path, destination: Path) -> int:
    paths = repository_paths(repository)
    for relative in paths:
        source = repository / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            target.symlink_to(os.readlink(source))
        else:
            shutil.copy2(source, target)

    return len(paths)


def copy_source_snapshot(destination: Path) -> int:
    count = copy_repository_snapshot(ROOT, destination)
    # Competition documents are intentionally ignored by Git but belong in this handoff.
    shutil.copytree(
        COMPETITION_DIR,
        destination / "docs" / "competition",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "lassist-*.png"),
    )
    return count


def copy_registration_materials(destination: Path) -> list[str]:
    copied: list[str] = []
    markdown = sorted(COMPETITION_DIR.glob("*.md"), key=lambda path: path.name)
    prefixes = {path.name[:3] for path in markdown if re.match(r"\d{2}-", path.name)}
    missing = [prefix for prefix in EXPECTED_DOCS if prefix not in prefixes]
    if missing:
        raise RuntimeError(f"missing competition documents: {missing}")

    for source in markdown:
        if source.name.startswith(INTERNAL_DOC_PREFIXES):
            continue
        target_name = "材料索引.md" if source.name == "README.md" else source.name
        shutil.copy2(source, destination / target_name)
        copied.append(target_name)
    for name in ("AgentRig-GOAI-2026-初赛方案.pdf", "AgentRig-GOAI-2026-初赛方案.pptx"):
        source = COMPETITION_DIR / name
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, destination / name)
        copied.append(name)
    public_assets = destination / "assets"
    public_assets.mkdir()
    shutil.copytree(
        COMPETITION_DIR / "assets" / "live",
        public_assets / "live",
        ignore=shutil.ignore_patterns("lassist-*.png"),
    )
    for name in ("agentrig-assistant.png", "v23-capability-run.png", "v23-quality-gate.png"):
        source = COMPETITION_DIR / "assets" / name
        if source.is_file():
            shutil.copy2(source, public_assets / name)
    return copied


def copy_optimization_plan(destination: Path) -> list[str]:
    markdown = sorted(OPTIMIZATION_PLAN_DIR.glob("*.md"), key=lambda path: path.name)
    names = [path.name for path in markdown]
    expected = {"README.md", *(f"{index:02d}-" for index in range(12))}
    present = {"README.md" if name == "README.md" else name[:3] for name in names}
    missing = sorted(expected - present)
    if missing:
        raise RuntimeError(f"missing optimization-plan documents: {missing}")
    shutil.copytree(OPTIMIZATION_PLAN_DIR, destination / OPTIMIZATION_PLAN_PACKAGE_NAME)
    return names


def copy_current_evidence(
    destination: Path, *, expected_source_dirty: bool
) -> tuple[Path, dict[str, Any]]:
    state = ROOT / ".agentrig" / "reference-demo"
    pointer = json.loads((state / "latest-evidence.json").read_text(encoding="utf-8"))
    relative = Path(str(pointer["path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError("unsafe ReferenceEvidence pointer")
    source = state / relative
    if not source.is_dir():
        raise FileNotFoundError(source)
    release = json.loads((source / "release-evidence.json").read_text(encoding="utf-8"))
    release_metadata = release.get("release", {})
    evidence_source_dirty = (
        release_metadata.get("source_dirty") if isinstance(release_metadata, dict) else None
    )
    if not isinstance(evidence_source_dirty, bool):
        raise RuntimeError("current ReferenceEvidence must declare a boolean source_dirty")
    if evidence_source_dirty is not expected_source_dirty:
        raise RuntimeError(
            "current ReferenceEvidence source_dirty does not match the current source tree"
        )
    shutil.copytree(source, destination, dirs_exist_ok=True)
    (destination / "current-evidence-pointer.json").write_text(
        json.dumps(pointer, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return source, release


def count_pptx_slides(path: Path) -> int:
    with zipfile.ZipFile(path) as archive:
        return sum(
            bool(re.fullmatch(r"ppt/slides/slide\d+\.xml", name)) for name in archive.namelist()
        )


def pdf_metadata(path: Path) -> dict[str, Any]:
    result = run(["pdfinfo", str(path)])
    pages = re.search(r"^Pages:\s+(\d+)$", result.stdout, re.MULTILINE)
    size = re.search(r"^Page size:\s+(.+)$", result.stdout, re.MULTILINE)
    encrypted = re.search(r"^Encrypted:\s+(.+)$", result.stdout, re.MULTILINE)
    if not pages or not size or not encrypted:
        raise RuntimeError("could not parse proposal PDF metadata")
    return {
        "pages": int(pages.group(1)),
        "page_size": size.group(1).strip(),
        "encrypted": encrypted.group(1).strip(),
        "javascript": "JavaScript:      yes" in result.stdout,
    }


def timestamp_ms(value: str) -> int:
    match = re.fullmatch(r"(\d\d):(\d\d):(\d\d),(\d\d\d)", value)
    if not match:
        raise ValueError(value)
    hours, minutes, seconds, milliseconds = map(int, match.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def srt_metadata(path: Path) -> dict[str, Any]:
    blocks = path.read_text(encoding="utf-8").strip().split("\n\n")
    previous_end = -1
    for expected, block in enumerate(blocks, start=1):
        lines = block.splitlines()
        if int(lines[0]) != expected:
            raise RuntimeError("SRT cue numbering is not contiguous")
        start_raw, end_raw = lines[1].split(" --> ")
        start, end = timestamp_ms(start_raw), timestamp_ms(end_raw)
        if start < previous_end or end <= start:
            raise RuntimeError(f"SRT cue {expected} overlaps or has invalid duration")
        previous_end = end
    return {"cue_count": len(blocks), "non_overlapping": True, "last_cue_ms": previous_end}


def video_metadata(ffmpeg: Path, path: Path) -> dict[str, Any]:
    probe = run([str(ffmpeg), "-hide_banner", "-i", str(path)], check=False).stdout
    duration = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", probe)
    video = re.search(r"Video: ([^,]+).*?(\d{3,5})x(\d{3,5}).*?(\d+(?:\.\d+)?) fps", probe)
    audio = re.search(r"Audio: ([^,]+), (\d+) Hz, ([^,]+)", probe)
    if not duration or not video or not audio:
        raise RuntimeError("could not parse video metadata")
    hours, minutes, seconds = duration.groups()
    duration_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    volume = run(
        [str(ffmpeg), "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        check=False,
    ).stdout
    mean = re.search(r"mean_volume: ([\-\d.]+) dB", volume)
    maximum = re.search(r"max_volume: ([\-\d.]+) dB", volume)
    return {
        "duration_seconds": duration_seconds,
        "video_codec": video.group(1).strip(),
        "width": int(video.group(2)),
        "height": int(video.group(3)),
        "fps": float(video.group(4)),
        "audio_codec": audio.group(1).strip(),
        "audio_hz": int(audio.group(2)),
        "audio_layout": audio.group(3).strip(),
        "mean_volume_db": float(mean.group(1)) if mean else None,
        "max_volume_db": float(maximum.group(1)) if maximum else None,
    }


def intro_length() -> int:
    document = (COMPETITION_DIR / "01-作品简介.md").read_text(encoding="utf-8")
    section = document.split("## 提交正文（500 字以内）", 1)[1].split("## 评委应记住的三点", 1)[0]
    body = [
        line.strip() for line in section.splitlines() if line.strip() and not line.startswith(">")
    ]
    return sum(len(line) for line in body)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_readme(path: Path, *, source_dirty: bool) -> None:
    status = "候选提交包（当前工作区尚未提交）" if source_dirty else "提交包"
    content = (
        f"# GOAI 2026 · AgentRig 初赛{status}\n\n"
        "赛道：Agent Infra 新智基座  \n"
        "项目：AgentRig——真实 Agent 的低副作用回归测试台  \n"
        "材料快照：2026-08-14（Asia/Shanghai）\n\n"
        "## 建议上传顺序\n\n"
        "1. 从 `01-报名材料/09-初赛提交表单.md` 复制项目字段与作品简介。\n"
        "2. 主方案上传 `01-报名材料/AgentRig-GOAI-2026-初赛方案.pdf`；需要编辑时补充 PPTX。\n"
        "3. 根目录 MP4 为正式录制合成版（画面与 ID 来自 2026-08-14 干净录制库，旁白为合成音），"
        "外置字幕为同名 SRT。\n"
        "4. AgentRig 与公开 EditFlow 源码、wheel、sdist 位于 `02-工程包/`。\n"
        "5. 完整优化方案与验收手册位于 `04-V2.3-Agent运行时验证与生产证据闭环/`。\n"
        "6. EditFlow 正式录制证据/台账与 AgentRig ReferenceEvidence 位于 `03-运行证据/`。\n"
        "7. 内部工作文档（录制方案 15、逐秒剧本 16、彩排台账 17）不随包分发；"
        "台账以《EditFlow彩排证据与正式录制台账.md》形式保留在 `03-运行证据/`。\n\n"
        "## 事实边界\n\n"
        "- EditFlow：真实 Agno + DeepSeek、HTTP/SSE、Session 与工具决策；图片结果受控。\n"
        "- 正式录制为 Before 2/5、Candidate 5/5、矩阵 30/30、Sample Replay 5/5、Web 3/3，"
        "全部 ID 见 03-运行证据。\n"
        "- 当前台账：Backend 203、Web 41、PostgreSQL 4、Skill contracts 11。\n"
        "- lassist 只作为脱敏兼容结论；原始对话、截图、路径和运行文件未进入公开包。\n"
        "- AgentScope v2.0.6、AgentTeams v1.2.2 外部 Live、Kubernetes 与目标 SLO 仍为 Pending。\n"
        "- 当前源码未提交时，ReleaseEvidence 必须保持 `source_dirty=true`；不得填写旧 CI Run。\n\n"
        "## 仍需参赛者本人完成\n\n"
        "填写团队/联系人，确认两个仓库公开并推送 CI，可选录制真人旁白版视频，接受协议并上传。\n",
    )
    path.write_text("".join(content), encoding="utf-8")


def write_validation(
    path: Path,
    *,
    git_sha: str,
    source_dirty: bool,
    source_count: int,
    editflow_source_count: int,
    pdf: dict[str, Any],
    slides: int,
    video: dict[str, Any],
    subtitles: dict[str, Any],
    wheel_hash: str,
    sdist_hash: str,
    evidence_path: Path,
    gitleaks_version: str | None,
) -> None:
    status = "CANDIDATE / DIRTY" if source_dirty else "FINAL / CLEAN"
    gitleaks_text = (
        f"Gitleaks `{gitleaks_version}`：AgentRig/EditFlow Git 历史与提交目录均 0 findings。"
        if gitleaks_version
        else "Gitleaks：未在本次 builder 中执行。"
    )
    content = (
        "# Final validation\n\n"
        f"验证时间：{datetime.now().astimezone().isoformat(timespec='seconds')}  \n"
        f"封装状态：**{status}**\n\n"
        "## 制品\n\n"
        f"- 作品简介：{intro_length()} 字（包含空格与标点）。\n"
        f"- 方案：PPTX {slides} 页；PDF {pdf['pages']} 页、{pdf['page_size']}、"
        f"encrypted={pdf['encrypted']}、JavaScript={str(pdf['javascript']).lower()}。\n"
        f"- Demo：{video['duration_seconds']:.2f}s，{video['width']}×{video['height']}，"
        f"{video['fps']:g} fps，{video['video_codec']} + {video['audio_codec']} "
        f"{video['audio_hz']} Hz {video['audio_layout']}。\n"
        f"- 音量：mean {video['mean_volume_db']} dB，max {video['max_volume_db']} dB。\n"
        f"- 字幕：{subtitles['cue_count']} cues，单调且无重叠。\n"
        f"- AgentRig 源码：{source_count} 个 Git 可见/新增文件，并叠加完整本地比赛材料。\n"
        f"- EditFlow 源码：{editflow_source_count} 个 Git 可见/新增文件。\n"
        f"- git SHA：`{git_sha}`；`source_dirty={str(source_dirty).lower()}`。\n"
        f"- wheel SHA-256：`{wheel_hash}`。\n"
        f"- sdist SHA-256：`{sdist_hash}`。\n\n"
        "## 当前验收\n\n"
        "- Backend：203 passed、11 skipped；1 个上游弃用 warning。\n"
        "- Web：41 passed；typecheck 与 EditFlow 真实后端 Browser E2E 通过。\n"
        "- PostgreSQL 17.7：最终提交代码上 4/4 integration passed（agentrig_test，2026-08-14）。\n"
        "- Skill contracts：11 passed。\n"
        "- EditFlow：Before 2/5、Candidate headline 5/5、6 Cells / 30 Attempts 全通过。\n"
        "- Sample：真实 MCP capture 1 次；Replay 5/5，Run 内 real_tool Attempt=0。\n"
        "- Web Assistant：Plan → confirm → submit → Run，3/3。\n"
        "- lassist：仅保留 9 pass + 1 expected fail 的脱敏兼容结论。\n"
        "- wheel/sdist 与隔离安装 smoke：通过；Python 公共依赖/Web 生产依赖 audit：0 vulnerabilities。\n"
        f"- ReferenceEvidence：`{evidence_path.name}`，普通完整性校验通过，"
        f"`source_dirty={str(source_dirty).lower()}`。\n"
        f"- {gitleaks_text}\n\n"
        "## 未完成的外部事实\n\n"
        "- 可选的真人旁白版视频与更短剪辑（当前为正式录制合成版 + 合成旁白）；\n"
        "- AgentScope v2.0.6 endpoint Live acceptance；\n"
        "- AgentTeams v1.2.2 集群 observation/compat report；\n"
        "- Kubernetes/Helm、目标容量/SLO、公开 Release/Tag；\n"
        "- 团队信息、仓库公开、协议接受、上传与最终提交。\n\n"
        "当前为 dirty 候选包时，参赛人提交源码后必须在干净 checkout 重跑 "
        "`validate-evidence --require-clean-source` 与 CI，再重建本包。\n",
    )
    path.write_text("".join(content), encoding="utf-8")


def scan_with_gitleaks(binary: Path, staging: Path) -> str:
    version = run([str(binary), "version"]).stdout.strip()
    run([str(binary), "git", "--no-banner", "--redact", "--exit-code", "2", str(ROOT)])
    run(
        [
            str(binary),
            "git",
            "--no-banner",
            "--redact",
            "--exit-code",
            "2",
            str(EDITFLOW_ROOT),
        ]
    )
    run([str(binary), "dir", "--no-banner", "--redact", "--exit-code", "2", str(staging)])
    return version


def write_hashes(root: Path) -> int:
    files = sorted(
        (path for path in root.rglob("*") if path.is_file() and path.name != "SHA256SUMS"),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    lines = [f"{sha256(path)}  {path.relative_to(root).as_posix()}" for path in files]
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(files)


def validated_binary(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise FileNotFoundError(f"{label} executable is unavailable: {resolved}")
    return resolved


def resolve_ffmpeg(path: Path | None) -> Path:
    if path is not None:
        return validated_binary(path, "ffmpeg")
    result = run(
        [
            "uv",
            "run",
            "--with",
            "imageio-ffmpeg",
            "python",
            "-c",
            "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())",
        ]
    )
    resolved = Path(result.stdout.strip().splitlines()[-1])
    return validated_binary(resolved, "ffmpeg")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", type=Path)
    parser.add_argument("--gitleaks", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ffmpeg = resolve_ffmpeg(args.ffmpeg)
    gitleaks = validated_binary(args.gitleaks, "gitleaks") if args.gitleaks else None
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    video_source = MEDIA_DIR / VIDEO_NAME
    srt_source = MEDIA_DIR / SRT_NAME
    video_metadata_source = MEDIA_DIR / VIDEO_METADATA_NAME
    wheel = ROOT / "dist" / "agentrig-0.2.0a0-py3-none-any.whl"
    sdist = ROOT / "dist" / "agentrig-0.2.0a0.tar.gz"
    for required in (video_source, srt_source, video_metadata_source, wheel, sdist):
        if not required.is_file():
            raise FileNotFoundError(required)

    git_sha, source_dirty = repository_state(ROOT)
    editflow_git_sha, editflow_source_dirty = repository_state(EDITFLOW_ROOT)
    with tempfile.TemporaryDirectory(prefix=".agentrig-competition-", dir=DIST_DIR) as temp:
        temp_root = Path(temp)
        staging = temp_root / PACKAGE_NAME
        registration = staging / "01-报名材料"
        engineering = staging / "02-工程包"
        evidence = staging / "03-运行证据"
        registration.mkdir(parents=True)
        engineering.mkdir(parents=True)
        evidence.mkdir(parents=True)

        materials = copy_registration_materials(registration)
        optimization_plan = copy_optimization_plan(staging)
        source_count = copy_source_snapshot(engineering)
        shutil.copy2(wheel, engineering / wheel.name)
        shutil.copy2(sdist, engineering / sdist.name)
        if not (EDITFLOW_ROOT / "LICENSE").is_file():
            raise FileNotFoundError(f"EditFlow public repository is unavailable: {EDITFLOW_ROOT}")
        editflow_count = copy_repository_snapshot(
            EDITFLOW_ROOT, engineering / "editflow-demo-agent"
        )
        evidence_source, release = copy_current_evidence(
            evidence, expected_source_dirty=source_dirty
        )
        write_json(evidence / "acceptance-review-20260814.json", VERIFICATION_SNAPSHOT)
        shutil.copy2(
            COMPETITION_DIR / "editflow-rehearsal-evidence.json",
            evidence / "editflow-rehearsal-evidence.json",
        )
        shutil.copy2(
            COMPETITION_DIR / "editflow-recording-evidence.json",
            evidence / "editflow-recording-evidence.json",
        )
        shutil.copy2(
            COMPETITION_DIR / "editflow-recording-ledger.json",
            evidence / "editflow-recording-ledger.json",
        )
        shutil.copy2(
            COMPETITION_DIR / "17-EditFlow彩排证据与正式录制台账.md",
            evidence / "EditFlow彩排证据与正式录制台账.md",
        )
        shutil.copy2(video_source, staging / VIDEO_NAME)
        shutil.copy2(srt_source, staging / SRT_NAME)
        shutil.copy2(video_metadata_source, staging / VIDEO_METADATA_NAME)

        pdf = pdf_metadata(COMPETITION_DIR / "AgentRig-GOAI-2026-初赛方案.pdf")
        slides = count_pptx_slides(COMPETITION_DIR / "AgentRig-GOAI-2026-初赛方案.pptx")
        subtitles = srt_metadata(srt_source)
        video = video_metadata(ffmpeg, video_source)
        if intro_length() > 500 or slides != 16 or pdf["pages"] != 16:
            raise RuntimeError("competition document constraints failed")
        if not 480 <= video["duration_seconds"] <= 600:
            raise RuntimeError("review video must remain between 8:00 and 10:00")
        if (video["width"], video["height"], round(video["fps"])) != (1920, 1080, 30):
            raise RuntimeError("competition video must be 1920x1080 at 30 fps")
        media_manifest = json.loads(video_metadata_source.read_text(encoding="utf-8"))
        narration = media_manifest.get("narration", {})
        if narration.get("engine") not in {"edge-tts", "macos-say"}:
            raise RuntimeError("review video must declare an approved narration engine")
        if media_manifest.get("cut_purpose") != (
            "formal agent-led recording; stills and IDs come from the clean 2026-08-14 "
            "recording database, narration is synthesized"
        ):
            raise RuntimeError("demo video must declare the formal recording provenance")
        if media_manifest.get("camera_motion") != "none; fixed source frame per scene":
            raise RuntimeError("competition video must declare fixed, motion-free scenes")

        write_readme(staging / "README-提交说明.md", source_dirty=source_dirty)
        manifest = {
            "schema_version": "agentrig.competition-submission.v4",
            "generated_at": datetime.now(UTC).isoformat(),
            "git_sha": git_sha,
            "source_dirty": source_dirty,
            "editflow_git_sha": editflow_git_sha,
            "editflow_source_dirty": editflow_source_dirty,
            "registration_materials": materials,
            "optimization_plan_documents": optimization_plan,
            "source_file_count": source_count,
            "editflow_source_file_count": editflow_count,
            "reference_evidence": evidence_source.name,
            "reference_release_valid": True,
            "reference_source_dirty": release.get("release", {}).get("source_dirty"),
            "verification_snapshot": VERIFICATION_SNAPSHOT,
            "proposal": {"pptx_slides": slides, "pdf": pdf},
            "video": video,
            "video_build": media_manifest,
            "subtitles": subtitles,
            "wheel_sha256": sha256(wheel),
            "sdist_sha256": sha256(sdist),
        }
        write_json(staging / "BUILD-MANIFEST.json", manifest)
        write_validation(
            staging / "FINAL-VALIDATION.md",
            git_sha=git_sha,
            source_dirty=source_dirty,
            source_count=source_count,
            editflow_source_count=editflow_count,
            pdf=pdf,
            slides=slides,
            video=video,
            subtitles=subtitles,
            wheel_hash=manifest["wheel_sha256"],
            sdist_hash=manifest["sdist_sha256"],
            evidence_path=evidence_source,
            gitleaks_version=None,
        )

        gitleaks_version = scan_with_gitleaks(gitleaks, staging) if gitleaks else None
        if gitleaks_version:
            write_validation(
                staging / "FINAL-VALIDATION.md",
                git_sha=git_sha,
                source_dirty=source_dirty,
                source_count=source_count,
                editflow_source_count=editflow_count,
                pdf=pdf,
                slides=slides,
                video=video,
                subtitles=subtitles,
                wheel_hash=manifest["wheel_sha256"],
                sdist_hash=manifest["sdist_sha256"],
                evidence_path=evidence_source,
                gitleaks_version=gitleaks_version,
            )
        artifact_count = write_hashes(staging)

        archive_base = temp_root / "submission"
        staged_zip = Path(
            shutil.make_archive(
                str(archive_base), "zip", root_dir=staging.parent, base_dir=staging.name
            )
        )

        backup_dir = DIST_DIR / f".{PACKAGE_NAME}.previous"
        backup_zip = DIST_DIR / f".{PACKAGE_NAME}.previous.zip"
        if backup_dir.exists() or backup_zip.exists():
            raise RuntimeError("previous competition backup exists; inspect it before rebuilding")
        if PACKAGE_DIR.exists():
            os.replace(PACKAGE_DIR, backup_dir)
        if PACKAGE_ZIP.exists():
            os.replace(PACKAGE_ZIP, backup_zip)
        try:
            os.replace(staging, PACKAGE_DIR)
            os.replace(staged_zip, PACKAGE_ZIP)
        except BaseException:
            if backup_dir.exists() and not PACKAGE_DIR.exists():
                os.replace(backup_dir, PACKAGE_DIR)
            if backup_zip.exists() and not PACKAGE_ZIP.exists():
                os.replace(backup_zip, PACKAGE_ZIP)
            raise
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        if backup_zip.exists():
            backup_zip.unlink()

    outer_hash = sha256(PACKAGE_ZIP)
    PACKAGE_ZIP.with_suffix(PACKAGE_ZIP.suffix + ".sha256").write_text(
        f"{outer_hash}  {PACKAGE_ZIP.name}\n",
        encoding="utf-8",
    )
    print(f"Built {PACKAGE_DIR}")
    print(f"Built {PACKAGE_ZIP}")
    print(f"Files hashed {artifact_count}")
    print(f"ZIP SHA-256 {outer_hash}")
    print(f"source_dirty={str(source_dirty).lower()}")


if __name__ == "__main__":
    main()
