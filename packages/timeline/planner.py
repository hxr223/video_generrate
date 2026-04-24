from __future__ import annotations

import math
from typing import Any

from packages.core.models import Project, Shot


def build_seedance_shots(project: Project, shot_count: int) -> list[dict[str, Any]]:
    duration = max(3, math.ceil(project.target_duration / shot_count))
    script = (project.optimized_prompt or project.script_text or project.topic).strip()
    style_label = {
        "documentary": "纪实自然",
        "cinematic": "电影感",
        "commercial": "商业广告",
        "editorial": "杂志编辑",
    }.get(project.style, project.style)

    beats = [
        ("开场钩子", "用一个强视觉开场建立主题和氛围"),
        ("核心展示", "展示主体、场景或产品的关键细节"),
        ("情绪推进", "补充人物动作、环境变化和节奏层次"),
        ("收束转化", "用清晰结尾承接字幕或行动号召"),
    ]

    shots: list[dict[str, Any]] = []
    for index in range(shot_count):
        title, beat = beats[index] if index < len(beats) else (f"镜头 {index + 1}", "延展主题并保持视觉连续性")
        shots.append(
            {
                "order_index": index,
                "title": title,
                "prompt": (
                    f"{project.topic}。{beat}。画幅 {project.target_ratio}，"
                    f"{style_label}风格，适合{project.platform}平台。脚本参考：{script}"
                ),
                "duration_seconds": duration,
                "camera": "平滑推拉 / 稳定运镜",
                "notes": "由项目 brief 自动生成，后续可手动微调。",
            }
        )

    return shots


def build_timeline_segments(shots: list[Shot]) -> list[dict[str, Any]]:
    cursor = 0.0
    segments: list[dict[str, Any]] = []

    for shot in sorted(shots, key=lambda item: item.order_index):
        duration = float(shot.duration_seconds)
        segments.append(
            {
                "type": "video",
                "shot_id": str(shot.id),
                "asset_id": str(shot.result_asset_id) if shot.result_asset_id else None,
                "label": shot.title,
                "prompt": shot.prompt,
                "start": round(cursor, 3),
                "duration": duration,
                "transition_out": "fade" if shot.order_index > 0 else "cut",
            }
        )
        cursor += duration

    return segments


def infer_timeline_duration(segments: list[dict[str, Any]]) -> int:
    if not segments:
        return 0

    end_time = max(float(segment.get("start", 0)) + float(segment.get("duration", 0)) for segment in segments)
    return max(1, math.ceil(end_time))
