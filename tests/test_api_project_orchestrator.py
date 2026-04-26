from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.routers import pipeline as pipeline_router
from packages.core.database import get_session
from packages.core.models import Asset, GenerationTask, JobStatus, Project, ProjectStatus, RenderJob, Shot, ShotStatus, Timeline


class FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class FakeSession:
    def __init__(
        self,
        *,
        projects: list[Project] | None = None,
        shots: list[Shot] | None = None,
        timelines: list[Timeline] | None = None,
        render_jobs: list[RenderJob] | None = None,
        assets: list[Asset] | None = None,
        generation_tasks: list[GenerationTask] | None = None,
    ) -> None:
        self.projects = {project.id: project for project in projects or []}
        self.shots = {shot.id: shot for shot in shots or []}
        self.timelines = {timeline.id: timeline for timeline in timelines or []}
        self.render_jobs = {render_job.id: render_job for render_job in render_jobs or []}
        self.assets = {asset.id: asset for asset in assets or []}
        self.generation_tasks = {task.id: task for task in generation_tasks or []}

    def get(self, model: type[Any], entity_id: uuid.UUID) -> Any:
        mapping = {
            Project: self.projects,
            Shot: self.shots,
            Timeline: self.timelines,
            RenderJob: self.render_jobs,
            Asset: self.assets,
            GenerationTask: self.generation_tasks,
        }.get(model)
        if mapping is None:
            return None
        return mapping.get(entity_id)

    def scalars(self, statement: Any) -> FakeScalarResult:
        entity = None
        if getattr(statement, "column_descriptions", None):
            entity = statement.column_descriptions[0].get("entity")
        items = {
            Project: list(self.projects.values()),
            Shot: list(self.shots.values()),
            Timeline: list(self.timelines.values()),
            RenderJob: list(self.render_jobs.values()),
            Asset: list(self.assets.values()),
            GenerationTask: list(self.generation_tasks.values()),
        }.get(entity, [])
        return FakeScalarResult(items)

    def scalar(self, statement: Any) -> Any:
        items = self.scalars(statement).all()
        return items[0] if items else None

    def add(self, entity: Any) -> None:
        if isinstance(entity, Project):
            self.projects[entity.id] = entity
        if isinstance(entity, Shot):
            if entity.id is None:
                entity.id = uuid.uuid4()
            if entity.created_at is None:
                entity.created_at = datetime.now(timezone.utc)
            if entity.updated_at is None:
                entity.updated_at = datetime.now(timezone.utc)
            self.shots[entity.id] = entity
        if isinstance(entity, Timeline):
            if entity.id is None:
                entity.id = uuid.uuid4()
            if entity.created_at is None:
                entity.created_at = datetime.now(timezone.utc)
            self.timelines[entity.id] = entity
        if isinstance(entity, RenderJob):
            if entity.id is None:
                entity.id = uuid.uuid4()
            if entity.created_at is None:
                entity.created_at = datetime.now(timezone.utc)
            if entity.updated_at is None:
                entity.updated_at = datetime.now(timezone.utc)
            self.render_jobs[entity.id] = entity
        if isinstance(entity, GenerationTask):
            if entity.id is None:
                entity.id = uuid.uuid4()
            if entity.created_at is None:
                entity.created_at = datetime.now(timezone.utc)
            if entity.updated_at is None:
                entity.updated_at = datetime.now(timezone.utc)
            self.generation_tasks[entity.id] = entity
        if isinstance(entity, Asset):
            self.assets[entity.id] = entity

    def add_all(self, entities: list[Any]) -> None:
        for entity in entities:
            self.add(entity)

    def delete(self, entity: Any) -> None:
        return None

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def refresh(self, entity: Any) -> None:
        return None


def make_project(*, status: ProjectStatus = ProjectStatus.draft) -> Project:
    project = Project(
        id=uuid.uuid4(),
        title="项目编排测试",
        topic="验证 pipeline run 编排",
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


def make_shot(project_id: uuid.UUID, *, status: ShotStatus = ShotStatus.planned) -> Shot:
    shot = Shot(
        id=uuid.uuid4(),
        project_id=project_id,
        order_index=0,
        title="镜头一",
        prompt="开场镜头",
        duration_seconds=3,
        status=status,
    )
    shot.created_at = datetime.now(timezone.utc)
    shot.updated_at = datetime.now(timezone.utc)
    return shot


def override_session(fake_session: FakeSession) -> TestClient:
    app.dependency_overrides[get_session] = lambda: fake_session
    return TestClient(app)


def teardown_overrides() -> None:
    app.dependency_overrides.clear()


def test_pipeline_run_orchestrates_requested_steps_in_order(monkeypatch) -> None:
    project = make_project()
    fake_session = FakeSession(projects=[project])
    client = override_session(fake_session)
    call_log: list[tuple[str, dict[str, Any]]] = []
    state: dict[str, Any] = {
        "shots": [],
        "tasks": [],
        "timeline": None,
        "render_job_id": None,
        "run_render_job_id": None,
    }

    def fake_optimize(project: Project, creative_direction: str | None = None, preserve_script: bool = True) -> tuple[str, list[str]]:
        call_log.append(
            (
                "optimize",
                {
                    "creative_direction": creative_direction,
                    "preserve_script": preserve_script,
                },
            )
        )
        return "优化后的提示词", ["kept script"]

    def fake_plan(project: Project, shot_count: int, replace_existing: bool, session: FakeSession) -> list[Shot]:
        shots = [make_shot(project.id, status=ShotStatus.planned) for _ in range(shot_count)]
        state["shots"] = shots
        call_log.append(
            (
                "plan",
                {
                    "shot_count": shot_count,
                    "replace_existing": replace_existing,
                },
            )
        )
        return shots

    def fake_list_project_shots(session: FakeSession, project_id: uuid.UUID) -> list[Shot]:
        return list(state["shots"])

    def fake_create_provider_generation_tasks(
        project: Project,
        shots: list[Shot],
        *,
        provider: str,
        model: str,
        attach_generated_images_to_shots: bool,
        session: FakeSession,
    ) -> list[GenerationTask]:
        task = GenerationTask(
            id=uuid.uuid4(),
            project_id=project.id,
            shot_id=shots[0].id if shots else None,
            provider=provider,
            model=model,
            status=JobStatus.queued,
            request_payload={"attach_to_shot": attach_generated_images_to_shots},
        )
        task.created_at = datetime.now(timezone.utc)
        task.updated_at = datetime.now(timezone.utc)
        state["tasks"].append(task)
        if provider == "volcengine_seedream":
            call_log.append(
                (
                    "image",
                    {
                        "model": model,
                        "attach_to_shots": attach_generated_images_to_shots,
                    },
                )
            )
        else:
            call_log.append(
                (
                    "video",
                    {
                        "model": model,
                    },
                )
            )
        for shot in shots:
            shot.result_asset_id = uuid.uuid4()
            shot.status = ShotStatus.ready
        return [task]

    def fake_submit_generation_tasks(tasks: list[GenerationTask]) -> int:
        if not tasks:
            return 0
        task = tasks[0]
        step_name = "submit_image" if task.provider == "volcengine_seedream" else "submit_video"
        call_log.append((step_name, {"task_count": len(tasks)}))
        return len(tasks)

    def fake_list_project_generation_tasks(session: FakeSession, project_id: uuid.UUID, provider: str | None = None) -> list[GenerationTask]:
        tasks = list(state["tasks"])
        if provider is not None:
            tasks = [task for task in tasks if task.provider == provider]
        return tasks

    def fake_get_latest_timeline(session: FakeSession, project_id: uuid.UUID) -> Timeline | None:
        return state["timeline"]

    def fake_timeline_matches(timeline: Timeline | None, shots: list[Shot]) -> bool:
        return False

    def fake_create_timeline(project: Project, shots: list[Shot], payload: Any, session: FakeSession) -> Timeline:
        timeline = Timeline(
            id=uuid.uuid4(),
            project_id=project.id,
            version=1,
            duration_seconds=6,
            segments=[
                {
                    "shot_id": str(shot.id),
                    "asset_id": str(shot.result_asset_id),
                    "duration": shot.duration_seconds,
                    "label": shot.title,
                }
                for shot in shots
            ],
            audio_tracks=[],
            subtitle_tracks=[],
        )
        timeline.created_at = datetime.now(timezone.utc)
        state["timeline"] = timeline
        call_log.append(("timeline", {"shot_count": len(shots)}))
        return timeline

    def fake_get_latest_render_job(session: FakeSession, project_id: uuid.UUID) -> RenderJob | None:
        render_jobs = list(fake_session.render_jobs.values())
        return render_jobs[-1] if render_jobs else None

    monkeypatch.setattr(pipeline_router, "optimize_project_prompt", fake_optimize)
    monkeypatch.setattr(pipeline_router, "plan_project_shots", fake_plan)
    monkeypatch.setattr(pipeline_router, "list_project_shots", fake_list_project_shots)
    monkeypatch.setattr(pipeline_router, "create_provider_generation_tasks", fake_create_provider_generation_tasks)
    monkeypatch.setattr(pipeline_router, "submit_generation_tasks", fake_submit_generation_tasks)
    monkeypatch.setattr(pipeline_router, "list_project_generation_tasks", fake_list_project_generation_tasks)
    monkeypatch.setattr(pipeline_router, "get_latest_timeline_for_project", fake_get_latest_timeline)
    monkeypatch.setattr(pipeline_router, "timeline_matches_shots", fake_timeline_matches)
    monkeypatch.setattr(pipeline_router, "create_project_timeline", fake_create_timeline)
    monkeypatch.setattr(pipeline_router, "get_latest_render_job_for_project", fake_get_latest_render_job)
    monkeypatch.setattr(pipeline_router, "build_ffmpeg_plan", lambda *args, **kwargs: {"steps": ["assemble"]})
    monkeypatch.setattr(
        pipeline_router,
        "run_render_job",
        type(
            "RunRenderTask",
            (),
            {
                "delay": staticmethod(
                    lambda render_job_id: call_log.append(("run_render", {"render_job_id": render_job_id}))
                )
            },
        )(),
    )

    response = client.post(
        f"/projects/{project.id}/pipeline/run",
        json={
            "optimize_prompt": True,
            "shot_count": 3,
            "replace_existing_shots": True,
            "create_image_tasks": True,
            "create_video_tasks": True,
            "attach_generated_images_to_shots": True,
            "build_timeline_when_ready": True,
            "create_render_job_when_ready": True,
            "run_render_when_ready": True,
            "profile": "social_1080p",
        },
    )
    teardown_overrides()

    assert response.status_code < 300
    payload = response.json()
    assert [item[0] for item in call_log] == [
        "optimize",
        "plan",
        "image",
        "submit_image",
        "video",
        "submit_video",
        "timeline",
        "run_render",
    ]
    assert call_log[0][1]["creative_direction"] is None
    assert call_log[0][1]["preserve_script"] is True
    assert call_log[1][1]["shot_count"] == 3
    assert call_log[1][1]["replace_existing"] is True
    assert call_log[2][1]["model"] == pipeline_router.settings.seedream_model
    assert call_log[2][1]["attach_to_shots"] is True
    assert call_log[4][1]["model"] == pipeline_router.settings.seedance_model
    assert payload["triggered_steps"] == [
        "optimize_prompt",
        "plan_shots",
        "create_image_tasks",
        "submit_image_tasks",
        "create_video_tasks",
        "submit_video_tasks",
        "create_timeline",
        "create_render_job",
        "run_render_job",
    ]
    assert payload["waiting_on"] == []
    assert payload["shot_count"] == 3
    assert payload["ready_shot_count"] == 3
    assert payload["latest_timeline_id"] is not None
    assert payload["latest_render_job_id"] is not None
    assert call_log[-1][1]["render_job_id"] == payload["latest_render_job_id"]


def test_pipeline_run_rejects_image_stage_without_planned_shots() -> None:
    project = make_project()
    fake_session = FakeSession(projects=[project])
    client = override_session(fake_session)

    response = client.post(
        f"/projects/{project.id}/pipeline/run",
        json={
            "optimize_prompt": False,
            "replace_existing_shots": False,
            "create_image_tasks": True,
            "create_video_tasks": False,
            "build_timeline_when_ready": False,
            "create_render_job_when_ready": False,
            "run_render_when_ready": False,
            "attach_generated_images_to_shots": True,
        },
    )
    teardown_overrides()

    assert response.status_code == 400
    assert "shot" in response.json()["detail"].lower()


def test_pipeline_run_rejects_timeline_stage_without_ready_assets() -> None:
    project = make_project(status=ProjectStatus.generating)
    shot = make_shot(project.id, status=ShotStatus.planned)
    fake_session = FakeSession(projects=[project], shots=[shot])
    client = override_session(fake_session)

    response = client.post(
        f"/projects/{project.id}/pipeline/run",
        json={
            "optimize_prompt": False,
            "replace_existing_shots": False,
            "create_image_tasks": False,
            "create_video_tasks": False,
            "build_timeline_when_ready": True,
            "create_render_job_when_ready": False,
            "run_render_when_ready": False,
        },
    )
    teardown_overrides()

    assert response.status_code == 400
    assert "asset" in response.json()["detail"].lower()


def test_pipeline_run_rejects_render_stage_without_timeline() -> None:
    project = make_project(status=ProjectStatus.assembling)
    fake_session = FakeSession(projects=[project])
    client = override_session(fake_session)

    response = client.post(
        f"/projects/{project.id}/pipeline/run",
        json={
            "optimize_prompt": False,
            "replace_existing_shots": False,
            "create_image_tasks": False,
            "create_video_tasks": False,
            "build_timeline_when_ready": False,
            "create_render_job_when_ready": True,
            "run_render_when_ready": False,
            "profile": "social_1080p",
        },
    )
    teardown_overrides()

    assert response.status_code == 400
    assert "timeline" in response.json()["detail"].lower()


def test_pipeline_run_rejects_run_render_without_render_job() -> None:
    project = make_project(status=ProjectStatus.rendering)
    fake_session = FakeSession(projects=[project])
    client = override_session(fake_session)

    response = client.post(
        f"/projects/{project.id}/pipeline/run",
        json={
            "optimize_prompt": False,
            "replace_existing_shots": False,
            "create_image_tasks": False,
            "create_video_tasks": False,
            "build_timeline_when_ready": False,
            "create_render_job_when_ready": False,
            "run_render_when_ready": True,
        },
    )
    teardown_overrides()

    assert response.status_code == 400
    assert "render" in response.json()["detail"].lower()
