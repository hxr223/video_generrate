from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from packages.core.models import Project, Shot
from packages.core.settings import settings


class SeedanceClientError(RuntimeError):
    pass


def build_seedance_request(project: Project, shot: Shot, model: str | None = None) -> dict[str, Any]:
    return {
        "model": model or settings.seedance_model,
        "content": [
            {
                "type": "text",
                "text": shot.prompt,
            }
        ],
        "resolution": "720p",
        "ratio": project.target_ratio,
        "duration": shot.duration_seconds,
        "generate_audio": True,
        "watermark": False,
    }


def is_seedance_configured() -> bool:
    return bool(settings.ark_api_key)


def get_seedance_base_url() -> str:
    return (settings.seedance_api_base_url or settings.ark_base_url).rstrip("/")


def build_submit_url() -> str:
    return urljoin(f"{get_seedance_base_url()}/", settings.seedance_submit_path.lstrip("/"))


def build_query_url(provider_task_id: str) -> str:
    path = settings.seedance_query_path_template.format(task_id=provider_task_id)
    return urljoin(f"{get_seedance_base_url()}/", path.lstrip("/"))


def _auth_headers() -> dict[str, str]:
    if not settings.ark_api_key:
        raise SeedanceClientError("ARK_API_KEY is required to call Seedance")
    return {
        "authorization": f"Bearer {settings.ark_api_key}",
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


def extract_provider_task_id(payload: dict[str, Any]) -> str | None:
    value = _deep_get(
        payload,
        (
            ("id",),
            ("task_id",),
            ("data", "id"),
            ("data", "task_id"),
            ("result", "id"),
            ("result", "task_id"),
        ),
    )
    return str(value) if value else None


def extract_provider_status(payload: dict[str, Any]) -> str | None:
    value = _deep_get(
        payload,
        (
            ("status",),
            ("data", "status"),
            ("result", "status"),
            ("task", "status"),
        ),
    )
    return str(value).lower() if value else None


def extract_video_url(payload: dict[str, Any]) -> str | None:
    value = _deep_get(
        payload,
        (
            ("content", "video_url"),
            ("data", "content", "video_url"),
            ("data", "video_url"),
            ("result", "content", "video_url"),
            ("result", "video_url"),
            ("output", "video_url"),
        ),
    )
    return str(value) if value else None


def is_provider_terminal_success(status: str | None, payload: dict[str, Any]) -> bool:
    if extract_video_url(payload):
        return True
    return status in {"succeeded", "success", "completed", "done", "finished"}


def is_provider_terminal_failure(status: str | None) -> bool:
    return status in {"failed", "fail", "error", "cancelled", "canceled"}


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


class SeedanceClient:
    def __init__(self, timeout_seconds: float = 60.0) -> None:
        self.timeout_seconds = timeout_seconds

    def submit_generation(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            build_submit_url(),
            headers=_auth_headers(),
            json=request_payload,
            timeout=self.timeout_seconds,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SeedanceClientError(_format_http_error(exc)) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise SeedanceClientError("Seedance submit response was not a JSON object")
        return payload

    def query_generation(self, provider_task_id: str) -> dict[str, Any]:
        response = httpx.get(
            build_query_url(provider_task_id),
            headers=_auth_headers(),
            timeout=self.timeout_seconds,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SeedanceClientError(_format_http_error(exc)) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise SeedanceClientError("Seedance query response was not a JSON object")
        return payload

    def download_video(self, video_url: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", video_url, timeout=self.timeout_seconds) as response:
            response.raise_for_status()
            with destination.open("wb") as output:
                for chunk in response.iter_bytes():
                    output.write(chunk)
        return destination


def _format_http_error(exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    body = response.text[:1200]
    return f"Seedance HTTP {response.status_code} for {response.url}: {body}"
