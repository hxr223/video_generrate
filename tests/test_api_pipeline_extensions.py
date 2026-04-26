from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

from apps.api.app.main import app
from packages.core.database import get_session
from packages.core.models import GenerationTask, JobStatus, Project, RenderJob, Shot, ShotStatus, Timeline


class FakeSession:
    def __init__(self, *, project: Project, shot: Shot | None = None, task: GenerationTask | None = None, timeline: Timeline | None = None) -> None:
        self.project = project
        self.shot = shot
        self.task = task
        self.timeline = timeline
        self.assets: list[Any] = []
        self.render_jobs: list[Any] = []

    def scalars(self, statement: Any):
        entity = statement.column_descriptions[0]["entity"]
        if entity.__name__ == "Shot":
            values = [self.shot] if self.shot is not None else []
        elif entity.__name__ == "GenerationTask":
            values = [self.task] if self.task is not None else []
        elif entity.__name__ == "Timeline":
            values = [self.timeline] if self.timeline is not None else []
        elif entity.__name__ == "RenderJob":
            values = self.render_jobs
        else:
            values = []

        class _Result:
            def __init__(self, result_values: list[Any]) -> None:
                self.result_values = result_values

            def all(self) -> list[Any]:
                return list(self.result_values)

        return _Result(values)

    def scalar(self, statement: Any) -> Any:
        entity = statement.column_descriptions[0]["entity"]
        if entity.__name__ == "Timeline":
            return self.timeline
        if entity.__name__ == "RenderJob":
            return self.render_jobs[-1] if self.render_jobs else None
        return None

    def get(self, model: type[Any], entity_id: uuid.UUID) -> Any:
        candidates = [self.project, self.shot, self.task, self.timeline, *self.render_jobs]
        for candidate in candidates:
            if candidate is not None and isinstance(candidate, model) and candidate.id == entity_id:
                return candidate
        return None

    def add(self, entity: Any) -> None:
        if entity.__class__.__name__ == "Asset":
            if getattr(entity, "id", None) is None:
                entity.id = uuid.uuid4()
            if getattr(entity, "created_at", None) is None:
                entity.created_at = datetime.now(timezone.utc)
            self.assets.append(entity)
        if entity.__class__.__name__ == "RenderJob":
            if getattr(entity, "id", None) is None:
                entity.id = uuid.uuid4()
            if getattr(entity, "created_at", None) is None:
                entity.created_at = datetime.now(timezone.utc)
            if getattr(entity, "updated_at", None) is None:
                entity.updated_at = datetime.now(timezone.utc)
            self.render_jobs.append(entity)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def refresh(self, entity: Any) -> None:
        return None


def make_project() -> Project:
    project = Project(
        id=uuid.uuid4(),
        title="Test Project",
        topic="Topic",
        target_duration=9,
        target_ratio="9:16",
        language="zh",
        style="commercial",
        platform="douyin",
    )
    project.created_at = datetime.now(timezone.utc)
    project.updated_at = datetime.now(timezone.utc)
    return project


def make_png() -> bytes:
    image = Image.new("RGB", (64, 48), color="#008f7a")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def override_session(fake_session: FakeSession) -> TestClient:
    app.dependency_overrides[get_session] = lambda: fake_session
    return TestClient(app)


def teardown_overrides() -> None:
    app.dependency_overrides.clear()


def test_get_public_settings_exposes_runtime_flags() -> None:
    client = TestClient(app)

    response = client.get("/settings/public")

    assert response.status_code == 200
    payload = response.json()
    assert payload["allowed_project_durations"] == [3, 5, 9, 15]
    assert "social_1080p" in payload["render_profiles"]
    assert "seedance" in payload["models"]


def test_upload_asset_creates_reference_image_and_binds_to_shot(monkeypatch) -> None:
    project = make_project()
    shot = Shot(
        id=uuid.uuid4(),
        project_id=project.id,
        order_index=0,
        title="Shot 1",
        prompt="Prompt",
        duration_seconds=3,
        status=ShotStatus.planned,
    )
    shot.created_at = datetime.now(timezone.utc)
    shot.updated_at = datetime.now(timezone.utc)
    fake_session = FakeSession(project=project, shot=shot)
    client = override_session(fake_session)
    monkeypatch.setattr("apps.api.app.routers.pipeline.upload_file", lambda *args, **kwargs: "minio://video-platform/uploads/test.png")

    response = client.post(
        f"/projects/{project.id}/assets/upload",
        data={
            "kind": "reference_image",
            "label": "Door Poster",
            "shot_id": str(shot.id),
            "attach_to_shot": "true",
        },
        files={"file": ("poster.png", make_png(), "image/png")},
    )
    teardown_overrides()

    assert response.status_code == 201
    payload = response.json()
    assert payload["kind"] == "reference_image"
    assert payload["width"] == 64
    assert payload["height"] == 48
    assert payload["shot_id"] == str(shot.id)
    assert shot.status == ShotStatus.ready
    assert shot.result_asset_id is not None
    assert fake_session.assets[0].uri.startswith("minio://")


def test_poll_rejects_seedream_tasks() -> None:
    project = make_project()
    task = GenerationTask(
        id=uuid.uuid4(),
        project_id=project.id,
        provider="volcengine_seedream",
        model="seedream",
        status=JobStatus.queued,
        request_payload={},
    )
    task.created_at = datetime.now(timezone.utc)
    task.updated_at = datetime.now(timezone.utc)
    fake_session = FakeSession(project=project, task=task)
    client = override_session(fake_session)

    response = client.post(f"/projects/{project.id}/generation-tasks/{task.id}/poll")
    teardown_overrides()

    assert response.status_code == 400
    assert "do not support polling" in response.json()["detail"]


def test_render_job_requires_complete_timeline() -> None:
    project = make_project()
    timeline = Timeline(
        id=uuid.uuid4(),
        project_id=project.id,
        version=1,
        duration_seconds=9,
        segments=[{"label": "Shot 1", "asset_id": None, "duration": 3}],
        audio_tracks=[],
        subtitle_tracks=[],
    )
    timeline.created_at = datetime.now(timezone.utc)
    fake_session = FakeSession(project=project, timeline=timeline)
    client = override_session(fake_session)

    response = client.post(
        f"/projects/{project.id}/render-jobs",
        json={"timeline_id": str(timeline.id), "profile": "social_1080p"},
    )
    teardown_overrides()

    assert response.status_code == 400
    assert "Timeline is missing assets" in response.json()["detail"]


def test_run_project_pipeline_advances_when_assets_are_ready(monkeypatch) -> None:
    from apps.api.app.routers import pipeline as pipeline_router

    project = make_project()
    shot = Shot(
        id=uuid.uuid4(),
        project_id=project.id,
        order_index=0,
        title="Shot 1",
        prompt="Prompt",
        duration_seconds=3,
        status=ShotStatus.ready,
        result_asset_id=uuid.uuid4(),
    )
    shot.created_at = datetime.now(timezone.utc)
    shot.updated_at = datetime.now(timezone.utc)
    fake_session = FakeSession(project=project, shot=shot)
    client = override_session(fake_session)
    timeline_holder: dict[str, Timeline | None] = {"timeline": None}
    delayed_render_ids: list[str] = []

    monkeypatch.setattr(pipeline_router, "optimize_project_prompt", lambda project: ("optimized", ["note"]))
    monkeypatch.setattr(pipeline_router, "list_project_shots", lambda session, project_id: [shot])
    monkeypatch.setattr(pipeline_router, "plan_project_shots", lambda *args, **kwargs: [shot])
    monkeypatch.setattr(pipeline_router, "create_provider_generation_tasks", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline_router, "list_project_generation_tasks", lambda *args, **kwargs: [])

    def fake_get_latest_timeline(session, project_id):
        return timeline_holder["timeline"]

    def fake_create_timeline(project, shots, payload, session):
        timeline = Timeline(
            id=uuid.uuid4(),
            project_id=project.id,
            version=1,
            duration_seconds=3,
            segments=[{"shot_id": str(shot.id), "asset_id": str(shot.result_asset_id), "duration": 3}],
            audio_tracks=[],
            subtitle_tracks=[],
        )
        timeline.created_at = datetime.now(timezone.utc)
        timeline_holder["timeline"] = timeline
        return timeline

    monkeypatch.setattr(pipeline_router, "get_latest_timeline_for_project", fake_get_latest_timeline)
    monkeypatch.setattr(pipeline_router, "create_project_timeline", fake_create_timeline)
    monkeypatch.setattr(pipeline_router, "get_latest_render_job_for_project", lambda session, project_id: fake_session.render_jobs[-1] if fake_session.render_jobs else None)
    monkeypatch.setattr(pipeline_router.run_render_job, "delay", lambda render_job_id: delayed_render_ids.append(render_job_id))

    response = client.post(
        f"/projects/{project.id}/pipeline/run",
        json={"create_video_tasks": False, "run_render_when_ready": True},
    )
    teardown_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert "optimize_prompt" in payload["triggered_steps"]
    assert "create_timeline" in payload["triggered_steps"]
    assert "create_render_job" in payload["triggered_steps"]
    assert "run_render_job" in payload["triggered_steps"]
    assert payload["ready_shot_count"] == 1
    assert payload["latest_timeline_id"] is not None
    assert payload["latest_render_job_id"] is not None
    assert delayed_render_ids


def test_run_project_pipeline_waits_for_shots_before_timeline() -> None:
    project = make_project()
    shot = Shot(
        id=uuid.uuid4(),
        project_id=project.id,
        order_index=0,
        title="Shot 1",
        prompt="Prompt",
        duration_seconds=3,
        status=ShotStatus.planned,
    )
    shot.created_at = datetime.now(timezone.utc)
    shot.updated_at = datetime.now(timezone.utc)
    fake_session = FakeSession(project=project, shot=shot)
    client = override_session(fake_session)

    response = client.post(
        f"/projects/{project.id}/pipeline/run",
        json={
            "optimize_prompt": False,
            "create_video_tasks": False,
            "create_image_tasks": False,
            "run_render_when_ready": False,
        },
    )
    teardown_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert "shots_ready_for_timeline" in payload["waiting_on"]
    assert payload["latest_timeline_id"] is None
