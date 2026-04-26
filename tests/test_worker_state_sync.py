from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.worker.app import celery_app as worker_module
from packages.core.models import GenerationTask, JobStatus, Project, ProjectStatus, Shot, ShotStatus


class FakeScalarResult:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def all(self) -> list[Any]:
        return list(self.values)


class FakeSession:
    def __init__(self, *, project: Project, shot: Shot, generation_task: GenerationTask) -> None:
        self.project = project
        self.shot = shot
        self.generation_task = generation_task
        self.assets: list[Any] = []

    def get(self, model: type[Any], entity_id: uuid.UUID) -> Any:
        for candidate in [self.project, self.shot, self.generation_task]:
            if isinstance(candidate, model) and candidate.id == entity_id:
                return candidate
        return None

    def scalars(self, statement: Any) -> FakeScalarResult:
        entity = statement.column_descriptions[0]["entity"]
        if entity.__name__ == "Shot":
            return FakeScalarResult([self.shot])
        if entity.__name__ == "GenerationTask":
            return FakeScalarResult([self.generation_task])
        return FakeScalarResult([])

    def add(self, entity: Any) -> None:
        self.assets.append(entity)

    def flush(self) -> None:
        if self.assets:
            latest = self.assets[-1]
            if getattr(latest, "id", None) is None:
                latest.id = uuid.uuid4()

    def commit(self) -> None:
        return None


@contextmanager
def fake_session_local(session: FakeSession):
    yield session


def make_entities() -> tuple[Project, Shot, GenerationTask]:
    project = Project(
        id=uuid.uuid4(),
        title="Worker Project",
        topic="topic",
        target_duration=9,
        target_ratio="9:16",
        language="zh",
        style="commercial",
        platform="douyin",
        status=ProjectStatus.generating,
    )
    shot = Shot(
        id=uuid.uuid4(),
        project_id=project.id,
        order_index=0,
        title="Shot 1",
        prompt="prompt",
        duration_seconds=3,
        status=ShotStatus.queued,
    )
    shot.created_at = datetime.now(timezone.utc)
    shot.updated_at = datetime.now(timezone.utc)
    task = GenerationTask(
        id=uuid.uuid4(),
        project_id=project.id,
        shot_id=shot.id,
        provider="volcengine_seedance",
        model="seedance",
        status=JobStatus.queued,
        request_payload={},
    )
    task.created_at = datetime.now(timezone.utc)
    task.updated_at = datetime.now(timezone.utc)
    task.shot = shot
    return project, shot, task


def test_submit_seedance_generation_task_marks_project_failed_without_api_key(monkeypatch) -> None:
    project, shot, task = make_entities()
    session = FakeSession(project=project, shot=shot, generation_task=task)

    monkeypatch.setattr(worker_module, "SessionLocal", lambda: fake_session_local(session))
    monkeypatch.setattr(worker_module.settings, "ark_api_key", None)

    result = worker_module.submit_seedance_generation_task(str(task.id))

    assert result["status"] == "failed"
    assert task.status == JobStatus.failed
    assert shot.status == ShotStatus.failed
    assert project.status == ProjectStatus.failed


def test_submit_seedream_image_task_promotes_project_to_assembling(monkeypatch, tmp_path: Path) -> None:
    project, shot, task = make_entities()
    task.provider = "volcengine_seedream"
    task.model = "seedream"
    task.request_payload = {"attach_to_shot": True}
    session = FakeSession(project=project, shot=shot, generation_task=task)

    class FakeSeedreamClient:
        def generate_image(self, request_payload: dict[str, Any]) -> dict[str, Any]:
            return {"data": {"images": [{"url": "https://example.com/generated.png"}]}}

        def download_image(self, image_url: str, destination: Path) -> Path:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"png")
            return destination

    monkeypatch.setattr(worker_module, "SessionLocal", lambda: fake_session_local(session))
    monkeypatch.setattr(worker_module.settings, "ark_api_key", "test-key")
    monkeypatch.setattr(worker_module.settings, "local_render_dir", str(tmp_path))
    monkeypatch.setattr(worker_module, "SeedreamClient", FakeSeedreamClient)
    monkeypatch.setattr(worker_module, "upload_file", lambda *args, **kwargs: "minio://video-platform/seedream/test.png")

    result = worker_module.submit_seedream_image_task(str(task.id))

    assert result["status"] == "succeeded"
    assert task.status == JobStatus.succeeded
    assert shot.status == ShotStatus.ready
    assert shot.result_asset_id is not None
    assert project.status == ProjectStatus.assembling
