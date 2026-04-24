from packages.integrations.seedance import (
    extract_error_message,
    extract_provider_status,
    extract_provider_task_id,
    extract_video_url,
    is_provider_terminal_failure,
    is_provider_terminal_success,
)


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
