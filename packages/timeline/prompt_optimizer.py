from __future__ import annotations

from packages.core.models import Project


def optimize_project_prompt(
    project: Project,
    creative_direction: str | None = None,
    preserve_script: bool = True,
) -> tuple[str, list[str]]:
    style_label = {
        "documentary": "真实自然的纪实影像",
        "cinematic": "电影感、层次丰富、光影明确",
        "commercial": "商业广告质感、干净高级、节奏清晰",
        "editorial": "杂志编辑感、构图精致、视觉留白",
    }.get(project.style, project.style)
    platform_label = {
        "douyin": "抖音/小红书竖屏短视频",
        "bilibili": "B站内容视频",
        "wechat_channels": "视频号短视频",
        "internal": "内部预览视频",
        "shorts": "竖屏短视频",
    }.get(project.platform, project.platform)
    source_script = (project.script_text or project.topic).strip()
    direction = f"创意方向：{creative_direction.strip()}。" if creative_direction else ""
    script_instruction = "保留原脚本叙事，不新增无关角色或场景。" if preserve_script else "允许在不偏离主题的前提下增强画面表达。"

    optimized_prompt = (
        f"为{platform_label}生成一支{project.target_duration}秒、{project.target_ratio}画幅的视频。"
        f"主题：{project.topic}。{direction}"
        f"整体风格：{style_label}，画面真实可信，主体清晰，构图稳定，运动自然。"
        f"镜头语言：开场要有吸引力，中段突出关键细节和情绪推进，结尾适合承接字幕或行动号召。"
        f"视觉要求：避免杂乱背景、避免文字变形、避免低清晰度和过度夸张特效；保持统一色调、柔和光线和专业广告片质感。"
        f"叙事参考：{source_script}。{script_instruction}"
    )
    notes = [
        "补齐了平台、画幅、时长、风格和镜头语言，方便后续拆分 Seedance 分镜。",
        "加入了画面质量约束，减少文字变形、杂乱背景和低清晰度风险。",
        "保留项目主题和脚本，不调用外部模型也能稳定产出可复用提示词。",
    ]
    return optimized_prompt, notes
