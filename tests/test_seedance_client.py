from packages.integrations.seedance import (
    build_seedance_request,
    extract_error_message,
    extract_provider_status,
    extract_provider_task_id,
    extract_video_url,
    is_provider_terminal_failure,
    is_provider_terminal_success,
)
from packages.core.models import Project, Shot


def test_extract_seedance_submit_task_id_shapes() -> None:
    assert extract_provider_task_id({"id": "task-1"}) == "task-1"
    assert extract_provider_task_id({"data": {"task_id": "task-2"}}) == "task-2"


def test_extract_seedance_query_result_shapes() -> None:
    payload = {
        "data": {
            "status": "succeeded",
            "content": {"video_url": "https://example.com/result.mp4"},
        }
    }

    status = extract_provider_status(payload)

    assert status == "succeeded"
    assert extract_video_url(payload) == "https://example.com/result.mp4"
    assert is_provider_terminal_success(status, payload)
    assert not is_provider_terminal_failure(status)


def test_extract_seedance_error_message() -> None:
    payload = {"error": {"message": "quota exceeded"}}

    assert extract_error_message(payload) == "quota exceeded"
    assert is_provider_terminal_failure("failed")


def test_build_seedance_request_matches_ark_content_generation_shape() -> None:
    project = Project(
        title="测试",
        topic="咖啡店开业",
        target_duration=4,
        target_ratio="9:16",
        language="zh",
        style="commercial",
        platform="douyin",
    )
    shot = Shot(
        order_index=0,
        title="开场",
        prompt="一杯咖啡放在木桌上，阳光洒进窗户",
        duration_seconds=4,
    )

    payload = build_seedance_request(project, shot, model="doubao-seedance-2-0-260128")

    assert payload == {
        "model": "doubao-seedance-2-0-260128",
        "content": [{"type": "text", "text": "一杯咖啡放在木桌上，阳光洒进窗户"}],
        "resolution": "720p",
        "ratio": "9:16",
        "duration": 4,
        "generate_audio": True,
        "watermark": False,
    }
