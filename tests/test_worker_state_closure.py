from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from apps.worker.app import celery_app as worker_router
from packages.core.models import (
    Asset,
    AssetKind,
    GenerationTask,
    JobStatus,
    Project,
    ProjectStatus,
    RenderJob,
    Shot,
    ShotStatus,
    Timeline,
)


class FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class FakeWorkerSession:
    def __init__(
        self,
        *,
        projects: list[Project] | None = None,
        shots: list[Shot] | None = None,
        generation_tasks: list[GenerationTask] | None = None,
        timelines: list[Timeline] | None = None,
        render_jobs: list[RenderJob] | None = None,
        assets: list[Asset] | None = None,
    ) -> None:
        self.projects = {project.id: project for project in projects or []}
        self.shots = {shot.id: shot for shot in shots or []}
        self.generation_tasks = {task.id: task for task in generation_tasks or []}
        self.timelines = {timeline.id: timeline for timeline in timelines or []}
        self.render_jobs = {render_job.id: render_job for render_job in render_jobs or []}
        self.assets = {asset.id: asset for asset in assets or []}

    def __enter__(self) -> FakeWorkerSession:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def get(self, model: type[Any], entity_id: uuid.UUID) -> Any:
        mapping = {
            Project: self.projects,
            Shot: self.shots,
            GenerationTask: self.generation_tasks,
            Timeline: self.timelines,
            RenderJob: self.render_jobs,
            Asset: self.assets,
        }.get(model)
        if mapping is None:
            return None
        return mapping.get(entity_id)

    def add(self, entity: Any) -> None:
        if isinstance(entity, Asset):
            if entity.id is None:
                entity.id = uuid.uuid4()
            if entity.created_at is None:
                entity.created_at = datetime.now(timezone.utc)
            self.assets[entity.id] = entity

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def scalars(self, statement: Any) -> FakeScalarResult:
        entity = None
        if getattr(statement, "column_descriptions", None):
            entity = statement.column_descriptions[0].get("entity")
        items = {
            Asset: list(self.assets.values()),
            Shot: list(self.shots.values()),
            GenerationTask: list(self.generation_tasks.values()),
            Timeline: list(self.timelines.values()),
            RenderJob: list(self.render_jobs.values()),
            Project: list(self.projects.values()),
        }.get(entity, [])
        return FakeScalarResult(items)


def make_project(*, status: ProjectStatus) -> Project:
    project = Project(
        id=uuid.uuid4(),
        title="状态闭环测试",
        topic="验证 worker 状态推进",
        target_duration=9,
        target_ratio="9:16",
        language="zh",
        style="commercial",
        platform="douyin",
        status=status,
    )
    project.created_at = datetime.now(timezone.utc)
    project.updated_at = datetime.now(timezone.utc)
    return project


def make_shot(project: Project, *, status: ShotStatus) -> Shot:
    shot = Shot(
        id=uuid.uuid4(),
        project_id=project.id,
        order_index=0,
        title="镜头一",
        prompt="产品特写",
        duration_seconds=3,
        status=status,
    )
    shot.project = project
    shot.created_at = datetime.now(timezone.utc)
    shot.updated_at = datetime.now(timezone.utc)
    return shot


def make_generation_task(project: Project, shot: Shot, *, provider: str, request_payload: dict[str, Any] | None = None) -> GenerationTask:
    task = GenerationTask(
        id=uuid.uuid4(),
        project_id=project.id,
        shot_id=shot.id,
        provider=provider,
        model="test-model",
        status=JobStatus.running,
        request_payload=request_payload or {},
        provider_task_id="provider-task-1",
    )
    task.project = project
    task.shot = shot
    task.created_at = datetime.now(timezone.utc)
    task.updated_at = datetime.now(timezone.utc)
    return task


def make_timeline(project: Project, asset_id: uuid.UUID) -> Timeline:
    timeline = Timeline(
        id=uuid.uuid4(),
        project_id=project.id,
        version=1,
        duration_seconds=3,
        segments=[{"asset_id": str(asset_id), "duration": 3, "label": "镜头一"}],
        audio_tracks=[],
        subtitle_tracks=[],
    )
    timeline.project = project
    timeline.created_at = datetime.now(timezone.utc)
    return timeline


def make_render_job(project: Project, timeline: Timeline) -> RenderJob:
    render_job = RenderJob(
        id=uuid.uuid4(),
        project_id=project.id,
        timeline_id=timeline.id,
        status=JobStatus.queued,
        profile="social_1080p",
        ffmpeg_plan={"segments": 1},
    )
    render_job.project = project
    render_job.timeline = timeline
    render_job.created_at = datetime.now(timezone.utc)
    render_job.updated_at = datetime.now(timezone.utc)
    return render_job


def install_fake_session(monkeypatch: pytest.MonkeyPatch, session: FakeWorkerSession) -> None:
    monkeypatch.setattr(worker_router, "SessionLocal", lambda: session)


def test_poll_seedance_failure_marks_shot_and_project_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    project = make_project(status=ProjectStatus.generating)
    shot = make_shot(project, status=ShotStatus.generating)
    task = make_generation_task(project, shot, provider="volcengine_seedance")
    session = FakeWorkerSession(projects=[project], shots=[shot], generation_tasks=[task])
    install_fake_session(monkeypatch, session)

    class FakeSeedanceClient:
        def query_generation(self, provider_task_id: str) -> dict[str, Any]:
            assert provider_task_id == "provider-task-1"
            return {"status": "failed", "error": {"message": "quota exceeded"}}

    monkeypatch.setattr(worker_router, "SeedanceClient", FakeSeedanceClient)

    result = worker_router.poll_seedance_generation_task(str(task.id))

    assert result == {"status": "failed", "task_id": str(task.id)}
    assert task.status == JobStatus.failed
    assert task.error_message == "quota exceeded"
    assert shot.status == ShotStatus.failed
    assert project.status == ProjectStatus.failed


def test_submit_seedream_failure_marks_shot_and_project_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    project = make_project(status=ProjectStatus.generating)
    shot = make_shot(project, status=ShotStatus.generating)
    task = make_generation_task(project, shot, provider="volcengine_seedream")
    session = FakeWorkerSession(projects=[project], shots=[shot], generation_tasks=[task])
    install_fake_session(monkeypatch, session)
    monkeypatch.setattr(worker_router.settings, "ark_api_key", "test-key")

    class FakeSeedreamClient:
        def generate_image(self, request_payload: dict[str, Any]) -> dict[str, Any]:
            raise worker_router.SeedreamClientError("bad prompt")

    monkeypatch.setattr(worker_router, "SeedreamClient", FakeSeedreamClient)

    result = worker_router.submit_seedream_image_task(str(task.id))

    assert result == {"status": "failed", "task_id": str(task.id)}
    assert task.status == JobStatus.failed
    assert task.error_message == "bad prompt"
    assert shot.status == ShotStatus.failed
    assert project.status == ProjectStatus.failed


def test_poll_seedance_success_promotes_project_to_assembling(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project = make_project(status=ProjectStatus.generating)
    shot = make_shot(project, status=ShotStatus.generating)
    task = make_generation_task(project, shot, provider="volcengine_seedance")
    session = FakeWorkerSession(projects=[project], shots=[shot], generation_tasks=[task])
    install_fake_session(monkeypatch, session)
    monkeypatch.setattr(worker_router.settings, "local_render_dir", str(tmp_path))
    monkeypatch.setattr(worker_router, "upload_file", lambda *args, **kwargs: "minio://video-platform/seedance/output.mp4")

    class FakeSeedanceClient:
        def query_generation(self, provider_task_id: str) -> dict[str, Any]:
            assert provider_task_id == "provider-task-1"
            return {
                "status": "succeeded",
                "content": {"video_url": "https://example.com/result.mp4"},
            }

        def download_video(self, video_url: str, destination: Path) -> Path:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"fake-video")
            return destination

    monkeypatch.setattr(worker_router, "SeedanceClient", FakeSeedanceClient)

    result = worker_router.poll_seedance_generation_task(str(task.id))

    assert result == {"status": "succeeded", "task_id": str(task.id)}
    assert task.status == JobStatus.succeeded
    assert task.result_asset_id is not None
    assert shot.status == ShotStatus.ready
    assert shot.result_asset_id == task.result_asset_id
    assert project.status == ProjectStatus.assembling
    stored_asset = session.assets[task.result_asset_id]
    assert stored_asset.kind == AssetKind.seedance_video
    assert stored_asset.uri == "minio://video-platform/seedance/output.mp4"


def test_submit_seedream_success_promotes_project_to_assembling(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project = make_project(status=ProjectStatus.generating)
    shot = make_shot(project, status=ShotStatus.generating)
    task = make_generation_task(
        project,
        shot,
        provider="volcengine_seedream",
        request_payload={"attach_to_shot": True},
    )
    session = FakeWorkerSession(projects=[project], shots=[shot], generation_tasks=[task])
    install_fake_session(monkeypatch, session)
    monkeypatch.setattr(worker_router.settings, "ark_api_key", "test-key")
    monkeypatch.setattr(worker_router.settings, "local_render_dir", str(tmp_path))
    monkeypatch.setattr(worker_router, "upload_file", lambda *args, **kwargs: "minio://video-platform/seedream/output.png")

    class FakeSeedreamClient:
        def generate_image(self, request_payload: dict[str, Any]) -> dict[str, Any]:
            return {"data": {"images": [{"url": "https://example.com/result.png"}]}}

        def download_image(self, image_url: str, destination: Path) -> Path:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"fake-image")
            return destination

    monkeypatch.setattr(worker_router, "SeedreamClient", FakeSeedreamClient)

    result = worker_router.submit_seedream_image_task(str(task.id))

    assert result == {"status": "succeeded", "task_id": str(task.id)}
    assert task.status == JobStatus.succeeded
    assert task.result_asset_id is not None
    assert shot.status == ShotStatus.ready
    assert shot.result_asset_id == task.result_asset_id
    assert project.status == ProjectStatus.assembling
    stored_asset = session.assets[task.result_asset_id]
    assert stored_asset.kind == AssetKind.generated_image
    assert stored_asset.uri == "minio://video-platform/seedream/output.png"


def test_run_render_job_success_promotes_project_to_completed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project = make_project(status=ProjectStatus.rendering)
    source_asset = Asset(
        id=uuid.uuid4(),
        project_id=project.id,
        kind=AssetKind.seedance_video,
        label="Source",
        uri="minio://video-platform/source.mp4",
        metadata_json={},
    )
    source_asset.created_at = datetime.now(timezone.utc)
    timeline = make_timeline(project, source_asset.id)
    render_job = make_render_job(project, timeline)
    session = FakeWorkerSession(
        projects=[project],
        timelines=[timeline],
        render_jobs=[render_job],
        assets=[source_asset],
    )
    install_fake_session(monkeypatch, session)
    monkeypatch.setattr(worker_router.settings, "local_render_dir", str(tmp_path))

    def fake_render_timeline(*, timeline: Timeline, assets_by_id: dict[str, Asset], profile_name: str, output_dir: Path) -> tuple[Path, dict[str, Any]]:
        assert str(source_asset.id) in assets_by_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "result.mp4"
        output_path.write_bytes(b"rendered-video")
        return output_path, {"duration": 3.0}

    monkeypatch.setattr(worker_router, "render_timeline", fake_render_timeline)
    monkeypatch.setattr(worker_router, "upload_file", lambda *args, **kwargs: "minio://video-platform/exports/final.mp4")

    result = worker_router.run_render_job(str(render_job.id))

    assert result == {"status": "succeeded", "render_job_id": str(render_job.id)}
    assert render_job.status == JobStatus.succeeded
    assert render_job.output_uri == "minio://video-platform/exports/final.mp4"
    assert project.final_video_url == "minio://video-platform/exports/final.mp4"
    assert project.status == ProjectStatus.completed
    export_assets = [asset for asset in session.assets.values() if asset.kind == AssetKind.export]
    assert len(export_assets) == 1
