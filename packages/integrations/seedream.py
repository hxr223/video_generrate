from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from packages.core.models import Project, Shot
from packages.core.settings import settings


class SeedreamClientError(RuntimeError):
    pass


def build_seedream_request(project: Project, shot: Shot, model: str | None = None) -> dict[str, Any]:
    return {
        "model": model or settings.seedream_model,
        "prompt": shot.prompt,
        "size": settings.seedream_size,
        "n": 1,
        "response_format": "url",
        "metadata": {
            "project_id": str(project.id),
            "shot_id": str(shot.id),
            "shot_title": shot.title,
            "target_ratio": project.target_ratio,
        },
    }


def is_seedream_configured() -> bool:
    return bool(settings.seedream_api_key)


def get_seedream_base_url() -> str:
    return (settings.seedream_api_base_url or settings.ark_base_url).rstrip("/")


def build_submit_url() -> str:
    return urljoin(f"{get_seedream_base_url()}/", settings.seedream_submit_path.lstrip("/"))


def _auth_headers() -> dict[str, str]:
    if not settings.seedream_api_key:
        raise SeedreamClientError("SEEDREAM_API_KEY is required to call the image generation provider")
    return {
        "authorization": f"Bearer {settings.seedream_api_key}",
        "content-type": "application/json",
    }


def _deep_get(payload: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> Any:
    for path in paths:
        current: Any = payload
        for key in path:
            if not isinstance(current, dict) or key not in current:
                break
            current = current[key]
        else:
            return current
    return None


def extract_image_urls(payload: dict[str, Any]) -> list[str]:
    candidates = (
        _deep_get(payload, (("data",),)),
        _deep_get(payload, (("data", "images"),)),
        _deep_get(payload, (("data", "image_urls"),)),
        _deep_get(payload, (("images",),)),
        _deep_get(payload, (("output", "images"),)),
        _deep_get(payload, (("result", "images"),)),
    )
    urls: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, list):
            for item in candidate:
                if isinstance(item, str):
                    urls.append(item)
                elif isinstance(item, dict):
                    value = item.get("url") or item.get("image_url")
                    if not value and item.get("b64_json"):
                        value = f"data:image/png;base64,{item['b64_json']}"
                    if value:
                        urls.append(str(value))
        elif isinstance(candidate, str):
            urls.append(candidate)

    single = _deep_get(
        payload,
        (
            ("data", "url"),
            ("data", "image_url"),
            ("url",),
            ("image_url",),
            ("result", "url"),
            ("result", "image_url"),
        ),
    )
    if single:
        urls.append(str(single))

    return list(dict.fromkeys(urls))


def extract_error_message(payload: dict[str, Any]) -> str | None:
    value = _deep_get(
        payload,
        (
            ("error", "message"),
            ("data", "error", "message"),
            ("message",),
            ("error_message",),
        ),
    )
    return str(value) if value else None


class SeedreamClient:
    def __init__(self, timeout_seconds: float = 120.0) -> None:
        self.timeout_seconds = timeout_seconds

    def generate_image(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            build_submit_url(),
            headers=_auth_headers(),
            json=request_payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise SeedreamClientError("Seedream response was not a JSON object")
        return payload

    def download_image(self, image_url: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if image_url.startswith("data:image/"):
            _, encoded = image_url.split(",", 1)
            destination.write_bytes(base64.b64decode(encoded))
            return destination
        with httpx.stream("GET", image_url, timeout=self.timeout_seconds) as response:
            response.raise_for_status()
            with destination.open("wb") as output:
                for chunk in response.iter_bytes():
                    output.write(chunk)
        return destination
