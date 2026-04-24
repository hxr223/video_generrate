from __future__ import annotations

from typing import Any

from packages.core.models import Project, Shot
from packages.core.settings import settings


def build_seedance_request(project: Project, shot: Shot, model: str | None = None) -> dict[str, Any]:
    return {
        "provider": "volcengine_seedance",
        "base_url": settings.ark_base_url,
        "model": model or settings.seedance_model,
        "prompt": shot.prompt,
        "duration": shot.duration_seconds,
        "ratio": project.target_ratio,
        "language": project.language,
        "metadata": {
            "project_id": str(project.id),
            "shot_id": str(shot.id),
            "shot_title": shot.title,
        },
    }


def is_seedance_configured() -> bool:
    return bool(settings.ark_api_key)
