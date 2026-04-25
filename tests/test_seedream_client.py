from packages.integrations.seedream import extract_error_message, extract_image_urls


def test_extract_seedream_image_url_shapes() -> None:
    assert extract_image_urls({"data": {"images": [{"url": "https://example.com/a.png"}]}}) == [
        "https://example.com/a.png"
    ]
    assert extract_image_urls({"data": {"image_urls": ["https://example.com/b.png"]}}) == [
        "https://example.com/b.png"
    ]
    assert extract_image_urls({"image_url": "https://example.com/c.png"}) == ["https://example.com/c.png"]


def test_extract_seedream_error_message() -> None:
    assert extract_error_message({"error": {"message": "bad prompt"}}) == "bad prompt"
