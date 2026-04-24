from packages.core.models import Project
from packages.timeline.planner import build_seedance_shots
from packages.timeline.prompt_optimizer import optimize_project_prompt


def test_prompt_optimizer_builds_seedance_ready_prompt() -> None:
    project = Project(
        title="咖啡店开业",
        topic="为精品咖啡店制作开业短视频",
        target_duration=30,
        target_ratio="9:16",
        language="zh",
        style="commercial",
        platform="douyin",
        script_text="清晨开店，咖啡萃取，顾客取餐。",
    )

    optimized_prompt, notes = optimize_project_prompt(project)

    assert "抖音/小红书" in optimized_prompt
    assert "商业广告质感" in optimized_prompt
    assert "9:16" in optimized_prompt
    assert notes


def test_planner_uses_optimized_prompt_when_available() -> None:
    project = Project(
        title="咖啡店开业",
        topic="原始主题",
        target_duration=30,
        target_ratio="9:16",
        language="zh",
        style="commercial",
        platform="douyin",
        script_text="原始脚本",
        optimized_prompt="优化后的 Seedance 主提示词",
    )

    shots = build_seedance_shots(project, shot_count=4)

    assert len(shots) == 4
    assert "优化后的 Seedance 主提示词" in shots[0]["prompt"]
    assert shots[0]["duration_seconds"] == 8
