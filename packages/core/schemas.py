from datetime import datetime
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.core.models import (
    AssetKind,
    JobStatus,
    ProjectStatus,
    SHOT_BINDABLE_ASSET_KINDS,
    ShotStatus,
    UPLOADABLE_ASSET_KINDS,
)

ALLOWED_PROJECT_DURATIONS = {3, 5, 9, 15}


class ProjectFields(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1)
    target_duration: int
    target_ratio: str = Field(default="9:16", max_length=16)
    language: str = Field(default="en", max_length=32)
    style: str = Field(default="documentary", max_length=80)
    platform: str = Field(default="shorts", max_length=80)
    script_text: str | None = None


class ProjectBase(ProjectFields):

    @field_validator("target_duration")
    @classmethod
    def validate_target_duration(cls, value: int) -> int:
        if value not in ALLOWED_PROJECT_DURATIONS:
            raise ValueError("target_duration must be one of 3, 5, 9, or 15 seconds")
        return value


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    topic: str | None = Field(default=None, min_length=1)
    target_duration: int | None = None
    target_ratio: str | None = Field(default=None, max_length=16)
    language: str | None = Field(default=None, max_length=32)
    style: str | None = Field(default=None, max_length=80)
    platform: str | None = Field(default=None, max_length=80)
    status: ProjectStatus | None = None
    script_text: str | None = None
    optimized_prompt: str | None = None
    prompt_optimization_notes: list[str] | None = None

    @field_validator("target_duration")
    @classmethod
    def validate_target_duration(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value not in ALLOWED_PROJECT_DURATIONS:
            raise ValueError("target_duration must be one of 3, 5, 9, or 15 seconds")
        return value


class ProjectRead(ProjectFields):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: ProjectStatus
    owner_id: str | None = None
    final_video_url: str | None = None
    cover_url: str | None = None
    subtitle_url: str | None = None
    optimized_prompt: str | None = None
    prompt_optimization_notes: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_validator("prompt_optimization_notes", mode="before")
    @classmethod
    def coerce_prompt_optimization_notes(cls, value: list[str] | None) -> list[str]:
        return value or []


class ProjectScriptDraftRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1)
    target_duration: int
    target_ratio: str = Field(default="9:16", max_length=16)
    language: str = Field(default="zh", max_length=32)
    style: str = Field(default="documentary", max_length=80)
    platform: str = Field(default="shorts", max_length=80)

    @field_validator("target_duration")
    @classmethod
    def validate_target_duration(cls, value: int) -> int:
        if value not in ALLOWED_PROJECT_DURATIONS:
            raise ValueError("target_duration must be one of 3, 5, 9, or 15 seconds")
        return value


class ProjectScriptDraftRead(BaseModel):
    script_text: str
    beats: list[str] = Field(default_factory=list)


class PromptOptimizeRequest(BaseModel):
    creative_direction: str | None = Field(default=None, max_length=500)
    preserve_script: bool = True


class PromptOptimizeRead(BaseModel):
    project_id: uuid.UUID
    optimized_prompt: str
    prompt_optimization_notes: list[str]


class ShotCreate(BaseModel):
    order_index: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1)
    duration_seconds: int = Field(ge=1, le=60)
    camera: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class ShotRead(ShotCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    status: ShotStatus
    result_asset_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class PlanShotsRequest(BaseModel):
    shot_count: int = Field(default=4, ge=1, le=12)
    replace_existing: bool = True


class AssetCreate(BaseModel):
    shot_id: uuid.UUID | None = None
    kind: AssetKind
    label: str = Field(min_length=1, max_length=200)
    uri: str = Field(min_length=1)
    duration_seconds: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class AssetRead(AssetCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    created_at: datetime


class PublicSettingsServicesRead(BaseModel):
    api_base_url: str
    ark_base_url: str
    seedance_base_url: str
    seedream_base_url: str
    minio_endpoint: str
    object_storage_public_base_url: str | None = None
    minio_bucket: str


class PublicSettingsProvidersRead(BaseModel):
    seedance_configured: bool
    seedream_configured: bool


class PublicSettingsModelsRead(BaseModel):
    seedance: str
    seedream: str
    seedream_size: str


class PublicSettingsCapabilitiesRead(BaseModel):
    upload_asset_kinds: list[str] = Field(default_factory=lambda: [kind.value for kind in UPLOADABLE_ASSET_KINDS])
    shot_bindable_asset_kinds: list[str] = Field(
        default_factory=lambda: [kind.value for kind in SHOT_BINDABLE_ASSET_KINDS]
    )


class PublicSettingsRead(BaseModel):
    app_name: str
    app_env: str
    allowed_project_durations: list[int]
    render_profiles: list[str]
    providers: PublicSettingsProvidersRead
    models: PublicSettingsModelsRead
    services: PublicSettingsServicesRead
    capabilities: PublicSettingsCapabilitiesRead


class GenerationTaskCreate(BaseModel):
    shot_id: uuid.UUID | None = None
    model: str | None = Field(default=None, max_length=160)


class ImageGenerationTaskCreate(BaseModel):
    shot_id: uuid.UUID | None = None
    model: str | None = Field(default=None, max_length=160)
    attach_to_shots: bool = True


class GenerationTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    shot_id: uuid.UUID | None = None
    provider: str
    model: str
    status: JobStatus
    request_payload: dict[str, Any]
    provider_task_id: str | None = None
    result_asset_id: uuid.UUID | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class TimelineCreate(BaseModel):
    segments: list[dict[str, Any]] | None = None
    audio_tracks: list[dict[str, Any]] = Field(default_factory=list)
    subtitle_tracks: list[dict[str, Any]] = Field(default_factory=list)


class TimelineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    version: int
    duration_seconds: int
    segments: list[dict[str, Any]]
    audio_tracks: list[dict[str, Any]]
    subtitle_tracks: list[dict[str, Any]]
    created_at: datetime


class RenderJobCreate(BaseModel):
    timeline_id: uuid.UUID | None = None
    profile: str = Field(default="social_1080p", max_length=80)


class RenderJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    timeline_id: uuid.UUID
    status: JobStatus
    profile: str
    output_uri: str | None = None
    ffmpeg_plan: dict[str, Any]
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class PipelineRunRequest(BaseModel):
    optimize: bool | None = None
    plan: bool | None = None
    image: bool | None = None
    video: bool | None = None
    timeline: bool | None = None
    render: bool | None = None
    run_render: bool | None = None
    creative_direction: str | None = Field(default=None, max_length=500)
    preserve_script: bool = True
    replace_existing: bool = True
    image_model: str | None = Field(default=None, max_length=160)
    video_model: str | None = Field(default=None, max_length=160)
    attach_images_to_shots: bool = True
    render_profile: str | None = Field(default=None, max_length=80)
    shot_count: int = Field(default=4, ge=1, le=12)
    replace_existing_shots: bool = False
    optimize_prompt: bool = True
    create_image_tasks: bool = False
    create_video_tasks: bool = True
    attach_generated_images_to_shots: bool = True
    build_timeline_when_ready: bool = True
    create_render_job_when_ready: bool = True
    run_render_when_ready: bool = True
    profile: str | None = Field(default=None, max_length=80)


class PipelineRunRead(BaseModel):
    project_id: uuid.UUID
    project_status: ProjectStatus
    triggered_steps: list[str] = Field(default_factory=list)
    skipped_steps: list[str] = Field(default_factory=list)
    waiting_on: list[str] = Field(default_factory=list)
    shot_count: int = 0
    ready_shot_count: int = 0
    generation_task_counts: dict[str, int] = Field(default_factory=dict)
    latest_timeline_id: uuid.UUID | None = None
    latest_render_job_id: uuid.UUID | None = None
