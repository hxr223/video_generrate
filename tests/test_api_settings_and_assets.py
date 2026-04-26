from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.api.app.main import app
from apps.api.app.routers import pipeline as pipeline_router
from apps.api.app.routers import settings as settings_router
from packages.core.database import get_session
from packages.core.models import Asset, Project, ProjectStatus, Shot, ShotStatus
from packages.core.schemas import ProjectCreate
from packages.core.settings import settings


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


class FakeSession:
    def __init__(self, *, projects: list[Project] | None = None, shots: list[Shot] | None = None) -> None:
        self.projects = {project.id: project for project in projects or []}
        self.shots = {shot.id: shot for shot in shots or []}
        self.assets: dict[uuid.UUID, Asset] = {}

    def get(self, model: type[object], object_id: uuid.UUID) -> object | None:
        if model is Project:
            return self.projects.get(object_id)
        if model is Shot:
            return self.shots.get(object_id)
        if model is Asset:
            return self.assets.get(object_id)
        return None

    def add(self, instance: object) -> None:
        if isinstance(instance, Asset):
            if instance.id is None:
                instance.id = uuid.uuid4()
            if instance.created_at is None:
                instance.created_at = datetime.now(timezone.utc)
            self.assets[instance.id] = instance

    def commit(self) -> None:
        return None

    def refresh(self, instance: object) -> None:
        if isinstance(instance, Asset) and instance.created_at is None:
            instance.created_at = datetime.now(timezone.utc)

    def scalars(self, _statement: object) -> object:
        class FakeScalarResult:
            def __init__(self, projects: list[Project]) -> None:
                self._projects = projects

            def all(self) -> list[Project]:
                return sorted(
                    self._projects,
                    key=lambda project: project.created_at or datetime.min.replace(tzinfo=timezone.utc),
                    reverse=True,
                )

        return FakeScalarResult(list(self.projects.values()))


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides.clear()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_public_settings_reports_public_configuration(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setattr(settings_router, "is_seedance_configured", lambda: True)
    monkeypatch.setattr(settings_router, "is_seedream_configured", lambda: False)
    monkeypatch.setattr(settings, "public_api_base_url", "https://api.example.com")
    monkeypatch.setattr(settings, "ark_base_url", "https://ark.example.com/v3")
    monkeypatch.setattr(settings, "seedance_api_base_url", "https://seedance.example.com/api")
    monkeypatch.setattr(settings, "seedream_api_base_url", "https://seedream.example.com/api")
    monkeypatch.setattr(settings, "object_storage_public_base_url", "https://cdn.example.com/assets")
    monkeypatch.setattr(settings, "minio_endpoint", "https://minio.example.com")
    monkeypatch.setattr(settings, "minio_bucket", "video-platform-public")
    monkeypatch.setattr(settings, "seedance_model", "seedance-model-test")
    monkeypatch.setattr(settings, "seedream_model", "seedream-model-test")
    monkeypatch.setattr(settings, "seedream_size", "2048x2048")

    response = client.get("/settings/public")

    assert response.status_code == 200
    payload = response.json()
    assert payload["providers"] == {
        "seedance_configured": True,
        "seedream_configured": False,
    }
    assert payload["models"] == {
        "seedance": "seedance-model-test",
        "seedream": "seedream-model-test",
        "seedream_size": "2048x2048",
    }
    assert payload["services"] == {
        "api_base_url": "https://api.example.com",
        "ark_base_url": "https://ark.example.com/v3",
        "seedance_base_url": "https://seedance.example.com/api",
        "seedream_base_url": "https://seedream.example.com/api",
        "minio_endpoint": "https://minio.example.com",
        "object_storage_public_base_url": "https://cdn.example.com/assets",
        "minio_bucket": "video-platform-public",
    }
    assert payload["capabilities"] == {
        "upload_asset_kinds": ["reference_image", "reference_video", "audio", "subtitle"],
        "shot_bindable_asset_kinds": ["reference_image", "reference_video", "audio", "subtitle"],
    }
    assert "database_url" not in payload["services"]
    assert "redis_url" not in payload["services"]


def test_generate_script_draft_returns_script_and_beats(client: TestClient) -> None:
    response = client.post(
        "/projects/script-draft",
        json={
            "title": "咖啡店开业短视频",
            "topic": "为一家现代咖啡店制作开业宣传视频",
            "target_duration": 9,
            "target_ratio": "9:16",
            "language": "zh",
            "style": "commercial",
            "platform": "douyin",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "咖啡店开业短视频" in payload["script_text"]
    assert "为一家现代咖啡店制作开业宣传视频" in payload["script_text"]
    assert len(payload["beats"]) == 5


def test_upload_asset_creates_minio_asset_and_binds_shot(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    tmp_path: Path,
) -> None:
    project_id = uuid.uuid4()
    shot_id = uuid.uuid4()
    project = Project(
        id=project_id,
        title="项目",
        topic="测试素材上传",
        target_duration=5,
        target_ratio="9:16",
        language="zh",
        style="commercial",
        platform="douyin",
        status=ProjectStatus.draft,
    )
    shot = Shot(
        id=shot_id,
        project_id=project_id,
        order_index=0,
        title="镜头一",
        prompt="测试参考图",
        duration_seconds=3,
        status=ShotStatus.planned,
    )
    session = FakeSession(projects=[project], shots=[shot])
    uploaded: dict[str, object] = {}

    def override_get_session() -> FakeSession:
        return session

    def fake_upload_file(path: Path, object_key: str, content_type: str | None = None) -> str:
        uploaded["path"] = Path(path)
        uploaded["bytes"] = Path(path).read_bytes()
        uploaded["object_key"] = object_key
        uploaded["content_type"] = content_type
        return f"minio://video-platform/{object_key}"

    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr(settings, "local_render_dir", str(tmp_path))
    monkeypatch.setattr(pipeline_router, "upload_file", fake_upload_file)

    response = client.post(
        f"/projects/{project_id}/assets/upload",
        data={
            "label": "主参考图",
            "shot_id": str(shot_id),
            "attach_to_shot": "true",
        },
        files={
            "reference_image": ("storyboard.png", PNG_1X1, "image/png"),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["kind"] == "reference_image"
    assert payload["label"] == "主参考图"
    assert payload["shot_id"] == str(shot_id)
    assert payload["width"] == 1
    assert payload["height"] == 1
    assert payload["metadata_json"]["source_filename"] == "storyboard.png"
    assert payload["metadata_json"]["file_size_bytes"] == len(PNG_1X1)
    assert payload["metadata_json"]["uploaded_via"] == "api"
    assert payload["uri"].startswith("minio://video-platform/uploads/")
    assert uploaded["bytes"] == PNG_1X1
    assert uploaded["content_type"] == "image/png"
    assert f"uploads/{project_id}/reference_image/" in str(uploaded["object_key"])
    asset = next(iter(session.assets.values()))
    assert asset.shot_id == shot_id
    assert shot.result_asset_id == asset.id
    assert shot.status == ShotStatus.ready


def test_upload_asset_rejects_unsupported_kind(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    tmp_path: Path,
) -> None:
    project_id = uuid.uuid4()
    session = FakeSession(
        projects=[
            Project(
                id=project_id,
                title="项目",
                topic="测试非法 kind",
                target_duration=5,
                target_ratio="9:16",
                language="zh",
                style="commercial",
                platform="douyin",
                status=ProjectStatus.draft,
            )
        ]
    )

    def override_get_session() -> FakeSession:
        return session

    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr(settings, "local_render_dir", str(tmp_path))

    response = client.post(
        f"/projects/{project_id}/assets/upload",
        data={"kind": "seedance_video"},
        files={"file": ("clip.mp4", b"fake-video", "video/mp4")},
    )

    assert response.status_code == 400
    assert "Upload is only supported for" in response.json()["detail"]


def test_upload_asset_rejects_shot_from_another_project(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    tmp_path: Path,
) -> None:
    project_id = uuid.uuid4()
    other_project_id = uuid.uuid4()
    foreign_shot_id = uuid.uuid4()
    session = FakeSession(
        projects=[
            Project(
                id=project_id,
                title="项目",
                topic="测试镜头归属",
                target_duration=5,
                target_ratio="9:16",
                language="zh",
                style="commercial",
                platform="douyin",
                status=ProjectStatus.draft,
            )
        ],
        shots=[
            Shot(
                id=foreign_shot_id,
                project_id=other_project_id,
                order_index=0,
                title="外部镜头",
                prompt="不属于当前项目",
                duration_seconds=3,
                status=ShotStatus.planned,
            )
        ],
    )

    def override_get_session() -> FakeSession:
        return session

    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr(settings, "local_render_dir", str(tmp_path))

    response = client.post(
        f"/projects/{project_id}/assets/upload",
        data={"shot_id": str(foreign_shot_id)},
        files={"audio": ("voice.mp3", b"fake-audio", "audio/mpeg")},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Shot not found"


def test_list_projects_allows_legacy_target_duration_values(client: TestClient) -> None:
    legacy_project = Project(
        id=uuid.uuid4(),
        title="历史项目",
        topic="兼容旧项目数据",
        target_duration=30,
        target_ratio="16:9",
        language="zh",
        style="documentary",
        platform="douyin",
        status=ProjectStatus.completed,
        created_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
    )
    session = FakeSession(projects=[legacy_project])

    def override_get_session() -> FakeSession:
        return session

    app.dependency_overrides[get_session] = override_get_session

    response = client.get("/projects")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == str(legacy_project.id)
    assert payload[0]["target_duration"] == 30


def test_project_create_still_rejects_unsupported_target_duration() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(
            title="新项目",
            topic="保持写入约束",
            target_duration=30,
            target_ratio="9:16",
            language="zh",
            style="commercial",
            platform="douyin",
        )
