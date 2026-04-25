from datetime import datetime
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field

from packages.core.models import AssetKind, JobStatus, ProjectStatus, ShotStatus


class ProjectBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1)
    target_duration: int = Field(ge=4, le=600)
    target_ratio: str = Field(default="9:16", max_length=16)
    language: str = Field(default="en", max_length=32)
    style: str = Field(default="documentary", max_length=80)
    platform: str = Field(default="shorts", max_length=80)
    script_text: str | None = None


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    topic: str | None = Field(default=None, min_length=1)
    target_duration: int | None = Field(default=None, ge=4, le=600)
    target_ratio: str | None = Field(default=None, max_length=16)
    language: str | None = Field(default=None, max_length=32)
    style: str | None = Field(default=None, max_length=80)
    platform: str | None = Field(default=None, max_length=80)
    status: ProjectStatus | None = None
    script_text: str | None = None
    optimized_prompt: str | None = None
    prompt_optimization_notes: list[str] | None = None


class ProjectRead(ProjectBase):
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
