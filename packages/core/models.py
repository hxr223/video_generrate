import enum
from datetime import datetime
from typing import Any
import uuid

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.core.database import Base


class ProjectStatus(str, enum.Enum):
    draft = "draft"
    planning = "planning"
    generating = "generating"
    assembling = "assembling"
    rendering = "rendering"
    completed = "completed"
    failed = "failed"


class ShotStatus(str, enum.Enum):
    planned = "planned"
    queued = "queued"
    generating = "generating"
    ready = "ready"
    failed = "failed"


class AssetKind(str, enum.Enum):
    seedance_video = "seedance_video"
    generated_image = "generated_image"
    reference_image = "reference_image"
    reference_video = "reference_video"
    audio = "audio"
    subtitle = "subtitle"
    export = "export"


UPLOADABLE_ASSET_KINDS: tuple[AssetKind, ...] = (
    AssetKind.reference_image,
    AssetKind.reference_video,
    AssetKind.audio,
    AssetKind.subtitle,
)


SHOT_BINDABLE_ASSET_KINDS: tuple[AssetKind, ...] = UPLOADABLE_ASSET_KINDS


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str] = mapped_column(Text)
    target_duration: Mapped[int] = mapped_column(Integer)
    target_ratio: Mapped[str] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(32), default="en")
    style: Mapped[str] = mapped_column(String(80), default="documentary")
    platform: Mapped[str] = mapped_column(String(80), default="shorts")
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"),
        default=ProjectStatus.draft,
    )
    owner_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    final_video_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtitle_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    script_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    optimized_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_optimization_notes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    shots: Mapped[list["Shot"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    assets: Mapped[list["Asset"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    generation_tasks: Mapped[list["GenerationTask"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    timelines: Mapped[list["Timeline"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    render_jobs: Mapped[list["RenderJob"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Shot(Base):
    __tablename__ = "shots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    order_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    status: Mapped[ShotStatus] = mapped_column(Enum(ShotStatus, name="shot_status"), default=ShotStatus.planned)
    camera: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    project: Mapped[Project] = relationship(back_populates="shots")
    assets: Mapped[list["Asset"]] = relationship(back_populates="shot")
    generation_tasks: Mapped[list["GenerationTask"]] = relationship(
        back_populates="shot",
        cascade="all, delete-orphan",
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    shot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    kind: Mapped[AssetKind] = mapped_column(Enum(AssetKind, name="asset_kind"))
    label: Mapped[str] = mapped_column(String(200))
    uri: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="assets")
    shot: Mapped[Shot | None] = relationship(back_populates="assets")


class GenerationTask(Base):
    __tablename__ = "generation_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    shot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(80), default="volcengine_seedance")
    model: Mapped[str] = mapped_column(String(160))
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, name="job_status"), default=JobStatus.queued)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    provider_task_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    result_asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    project: Mapped[Project] = relationship(back_populates="generation_tasks")
    shot: Mapped[Shot | None] = relationship(back_populates="generation_tasks")


class Timeline(Base):
    __tablename__ = "timelines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    audio_tracks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    subtitle_tracks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="timelines")
    render_jobs: Mapped[list["RenderJob"]] = relationship(back_populates="timeline")


class RenderJob(Base):
    __tablename__ = "render_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    timeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("timelines.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, name="render_job_status"), default=JobStatus.queued)
    profile: Mapped[str] = mapped_column(String(80), default="social_1080p")
    output_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    ffmpeg_plan: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    project: Mapped[Project] = relationship(back_populates="render_jobs")
    timeline: Mapped[Timeline] = relationship(back_populates="render_jobs")
