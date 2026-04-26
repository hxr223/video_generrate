import uuid

from packages.core.models import Project, Shot
from packages.integrations.seedream import build_seedream_request, extract_error_message, extract_image_urls


def test_extract_seedream_image_url_shapes() -> None:
    assert extract_image_urls({"data": [{"url": "https://example.com/openai.png"}]}) == [
        "https://example.com/openai.png"
    ]
    assert extract_image_urls({"data": {"images": [{"url": "https://example.com/a.png"}]}}) == [
        "https://example.com/a.png"
    ]
    assert extract_image_urls({"data": {"image_urls": ["https://example.com/b.png"]}}) == [
        "https://example.com/b.png"
    ]
    assert extract_image_urls({"image_url": "https://example.com/c.png"}) == ["https://example.com/c.png"]
    assert extract_image_urls({"data": [{"b64_json": "ZmFrZQ=="}]}) == ["data:image/png;base64,ZmFrZQ=="]


def test_extract_seedream_error_message() -> None:
    assert extract_error_message({"error": {"message": "bad prompt"}}) == "bad prompt"


def test_build_seedream_request_matches_openai_compatible_image_shape() -> None:
    project = Project(
        id=uuid.uuid4(),
        title="Project",
        topic="Topic",
        target_duration=4,
        target_ratio="9:16",
        language="zh",
        style="commercial",
        platform="douyin",
    )
    shot = Shot(
        id=uuid.uuid4(),
        project_id=project.id,
        order_index=0,
        title="Shot",
        prompt="生成咖啡店开业海报风格参考图",
        duration_seconds=4,
    )

    payload = build_seedream_request(project, shot, model="gpt-image-2")

    assert payload["model"] == "gpt-image-2"
    assert payload["prompt"] == shot.prompt
    assert payload["size"] == "1024x1024"
    assert payload["n"] == 1
    assert payload["response_format"] == "url"
    assert "base_url" not in payload
    assert "provider" not in payload
