from __future__ import annotations


def _style_phrase(style: str) -> str:
    return {
        "documentary": "真实、自然、有现场感",
        "cinematic": "有电影镜头感、光影层次和情绪推进",
        "commercial": "高级、利落、适合商业传播",
        "editorial": "精致、有杂志大片感和视觉留白",
    }.get(style, style or "统一")


def _platform_phrase(platform: str) -> str:
    return {
        "douyin": "竖屏短视频节奏",
        "bilibili": "更完整的内容表达节奏",
        "wechat_channels": "轻快直接的视频号表达节奏",
        "internal": "内部演示和方案展示节奏",
        "shorts": "短视频节奏",
    }.get(platform, platform or "短视频节奏")


def _duration_beats(target_duration: int) -> list[str]:
    if target_duration <= 3:
        return [
            "开场用一个最抓人的核心画面迅速点题。",
            "中段立刻展示主题主体或关键卖点。",
            "结尾用一句简洁的收束或行动号召结束。",
        ]
    if target_duration <= 5:
        return [
            "开场先建立主题氛围或品牌记忆点。",
            "第二拍展示主体细节、动作或核心信息。",
            "第三拍补充人物反应、环境变化或情绪推进。",
            "结尾用明确收束和 CTA 留下记忆点。",
        ]
    if target_duration <= 9:
        return [
            "开场先用一个高识别度画面吸引注意力。",
            "第二段交代主体、产品或场景关系。",
            "第三段强调关键细节、动作或使用瞬间。",
            "第四段让情绪或氛围自然推进。",
            "结尾用品牌、口号或行动号召完成收束。",
        ]
    return [
        "开场用氛围镜头快速建立主题与场景。",
        "第二段引出主体或核心内容，让观众立刻理解视频要讲什么。",
        "第三段补充关键细节、人物动作或产品卖点。",
        "第四段强化节奏变化和情绪推进，让内容更完整。",
        "第五段进入结果展示、对比或价值呈现。",
        "结尾用清晰的品牌记忆、字幕承接或 CTA 做收束。",
    ]


def generate_project_script_draft(
    *,
    title: str,
    topic: str,
    target_duration: int,
    style: str = "documentary",
    platform: str = "shorts",
    language: str = "zh",
) -> tuple[str, list[str]]:
    beats = _duration_beats(target_duration)
    style_phrase = _style_phrase(style)
    platform_phrase = _platform_phrase(platform)

    if language == "en":
        english_beats = [
            "Open with the most eye-catching visual to establish the idea immediately.",
            "Then show the core subject, product, or scene relationship clearly.",
            "Add one or two meaningful details that reinforce the main point.",
            "Close with a clear takeaway, brand cue, or call to action.",
        ]
        script_text = (
            f"Title: {title}. Topic: {topic}. This {target_duration}-second video should follow a {platform_phrase} and keep a "
            f"{style_phrase} tone. {' '.join(english_beats[: max(3, min(5, len(beats)))])}"
        )
        return script_text, english_beats[: len(beats)]

    script_text = (
        f"这是一条围绕《{title}》展开的 {target_duration} 秒视频，主题是：{topic}。"
        f"整体表达采用{platform_phrase}，画面气质保持{style_phrase}。"
        f"{' '.join(beats)}"
    )
    return script_text, beats
