import mimetypes
import struct
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.core.database import get_session
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
    UPLOADABLE_ASSET_KINDS,
)
from packages.core.schemas import (
    AssetCreate,
    AssetRead,
    GenerationTaskCreate,
    GenerationTaskRead,
    ImageGenerationTaskCreate,
    PlanShotsRequest,
    PipelineRunRead,
    PipelineRunRequest,
    PromptOptimizeRead,
    PromptOptimizeRequest,
    RenderJobCreate,
    RenderJobRead,
    ShotRead,
    TimelineCreate,
    TimelineRead,
)
from packages.core.settings import settings
from packages.integrations.seedance import build_seedance_request, is_seedance_configured
from packages.integrations.seedream import build_seedream_request, is_seedream_configured
from packages.media.ffmpeg import build_ffmpeg_plan
from packages.media.storage import upload_file
from packages.timeline.planner import build_seedance_shots, build_timeline_segments, infer_timeline_duration
from packages.timeline.prompt_optimizer import optimize_project_prompt
from apps.worker.app.celery_app import (
    poll_seedance_generation_task,
    run_render_job,
    submit_seedance_generation_task,
    submit_seedream_image_task,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["pipeline"])
NAMED_UPLOAD_FIELDS: tuple[tuple[str, AssetKind], ...] = (
    ("reference_image", AssetKind.reference_image),
    ("reference_video", AssetKind.reference_video),
    ("audio", AssetKind.audio),
    ("subtitle", AssetKind.subtitle),
)


def get_project_or_404(project_id: uuid.UUID, session: Session) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def get_project_shot_or_404(project_id: uuid.UUID, shot_id: uuid.UUID, session: Session) -> Shot:
    shot = session.get(Shot, shot_id)
    if shot is None or shot.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shot not found")
    return shot


def build_upload_object_key(project_id: uuid.UUID, asset_kind: AssetKind, asset_id: uuid.UUID, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return f"uploads/{project_id}/{asset_kind.value}/{asset_id}{suffix}"


def detect_upload_dimensions(file_bytes: bytes, asset_kind: AssetKind) -> tuple[int | None, int | None]:
    if asset_kind not in {AssetKind.reference_image, AssetKind.generated_image}:
        return None, None
    if file_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(file_bytes) >= 24:
        return struct.unpack(">II", file_bytes[16:24])
    if file_bytes.startswith((b"GIF87a", b"GIF89a")) and len(file_bytes) >= 10:
        return struct.unpack("<HH", file_bytes[6:10])
    return None, None


def resolve_uploaded_file(
    *,
    file: UploadFile | None,
    kind: AssetKind | None,
    reference_image: UploadFile | None,
    reference_video: UploadFile | None,
    audio: UploadFile | None,
    subtitle: UploadFile | None,
) -> tuple[AssetKind, UploadFile]:
    uploads: list[tuple[AssetKind, UploadFile]] = []
    named_uploads = {
        "reference_image": reference_image,
        "reference_video": reference_video,
        "audio": audio,
        "subtitle": subtitle,
    }
    for field_name, asset_kind in NAMED_UPLOAD_FIELDS:
        upload = named_uploads[field_name]
        if upload is not None:
            uploads.append((asset_kind, upload))

    if file is not None or kind is not None:
        if file is None or kind is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Both file and kind are required when using the generic upload fields",
            )
        uploads.append((kind, file))

    if not uploads:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide exactly one uploaded file using file+kind or one named asset field",
        )
    if len(uploads) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide exactly one uploaded file per request",
        )

    asset_kind, upload = uploads[0]
    if asset_kind not in UPLOADABLE_ASSET_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upload is only supported for: {', '.join(sorted(item.value for item in UPLOADABLE_ASSET_KINDS))}",
        )
    return asset_kind, upload


def list_project_shots(session: Session, project_id: uuid.UUID) -> list[Shot]:
    return list(
        session.scalars(select(Shot).where(Shot.project_id == project_id).order_by(Shot.order_index.asc())).all()
    )


def list_project_generation_tasks(
    session: Session,
    project_id: uuid.UUID,
    provider: str | None = None,
) -> list[GenerationTask]:
    statement = select(GenerationTask).where(GenerationTask.project_id == project_id)
    if provider is not None:
        statement = statement.where(GenerationTask.provider == provider)
    statement = statement.order_by(GenerationTask.created_at.desc())
    return list(session.scalars(statement).all())


def get_latest_timeline_for_project(session: Session, project_id: uuid.UUID) -> Timeline | None:
    return session.scalar(
        select(Timeline).where(Timeline.project_id == project_id).order_by(Timeline.version.desc()).limit(1)
    )


def get_latest_render_job_for_project(session: Session, project_id: uuid.UUID) -> RenderJob | None:
    return session.scalar(
        select(RenderJob).where(RenderJob.project_id == project_id).order_by(RenderJob.created_at.desc()).limit(1)
    )


def ensure_all_shots_ready(shots: list[Shot]) -> None:
    missing = [shot.title for shot in shots if not shot.result_asset_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Shots are still missing assets: {', '.join(missing)}",
        )


def plan_project_shots(project: Project, shot_count: int, replace_existing: bool, session: Session) -> list[Shot]:
    if replace_existing:
        existing = session.scalars(select(Shot).where(Shot.project_id == project.id)).all()
        for shot in existing:
            session.delete(shot)
        session.flush()

    planned_shots = [
        Shot(project_id=project.id, status=ShotStatus.planned, **shot_payload)
        for shot_payload in build_seedance_shots(project, shot_count)
    ]
    session.add_all(planned_shots)
    project.status = ProjectStatus.planning
    session.commit()

    for shot in planned_shots:
        session.refresh(shot)
    return planned_shots


def create_provider_generation_tasks(
    project: Project,
    shots: list[Shot],
    *,
    provider: str,
    model: str,
    attach_generated_images_to_shots: bool,
    session: Session,
) -> list[GenerationTask]:
    existing_tasks = list_project_generation_tasks(session, project.id, provider=provider)
    blocked_shot_ids = {
        task.shot_id
        for task in existing_tasks
        if task.shot_id is not None and task.status in {JobStatus.queued, JobStatus.running, JobStatus.succeeded}
    }

    tasks: list[GenerationTask] = []
    for shot in shots:
        if shot.id in blocked_shot_ids:
            continue
        shot.status = ShotStatus.queued
        if provider == "volcengine_seedream":
            request_payload = {
                **build_seedream_request(project, shot, model=model),
                "attach_to_shot": attach_generated_images_to_shots,
            }
            if not is_seedream_configured():
                request_payload["configuration_warning"] = "SEEDREAM_API_KEY is empty; image task is queued locally only."
        else:
            request_payload = build_seedance_request(project, shot, model=model)
            if not is_seedance_configured():
                request_payload["configuration_warning"] = "ARK_API_KEY is empty; task is queued locally only."
        tasks.append(
            GenerationTask(
                project_id=project.id,
                shot_id=shot.id,
                provider=provider,
                model=model,
                status=JobStatus.queued,
                request_payload=request_payload,
            )
        )

    if tasks:
        session.add_all(tasks)
        project.status = ProjectStatus.generating
        session.commit()
        for task in tasks:
            session.refresh(task)
    return tasks


def submit_generation_tasks(tasks: list[GenerationTask]) -> int:
    submitted = 0
    for task in tasks:
        if task.status != JobStatus.queued:
            continue
        if task.provider == "volcengine_seedream":
            if is_seedream_configured():
                submit_seedream_image_task.delay(str(task.id))
                submitted += 1
        else:
            if is_seedance_configured():
                submit_seedance_generation_task.delay(str(task.id))
                submitted += 1
    return submitted


def timeline_matches_shots(timeline: Timeline | None, shots: list[Shot]) -> bool:
    if timeline is None:
        return False
    expected = build_timeline_segments(shots)
    current = timeline.segments
    if len(expected) != len(current):
        return False
    for expected_segment, current_segment in zip(expected, current, strict=False):
        if expected_segment.get("shot_id") != current_segment.get("shot_id"):
            return False
        if expected_segment.get("asset_id") != current_segment.get("asset_id"):
            return False
        if expected_segment.get("duration") != current_segment.get("duration"):
            return False
    return True


def create_project_timeline(project: Project, shots: list[Shot], payload: TimelineCreate, session: Session) -> Timeline:
    segments = payload.segments if payload.segments is not None else build_timeline_segments(shots)
    next_version = int(
        session.scalar(select(func.coalesce(func.max(Timeline.version), 0)).where(Timeline.project_id == project.id))
        or 0
    ) + 1
    timeline = Timeline(
        project_id=project.id,
        version=next_version,
        duration_seconds=infer_timeline_duration(segments),
        segments=segments,
        audio_tracks=payload.audio_tracks,
        subtitle_tracks=payload.subtitle_tracks,
    )
    session.add(timeline)
    project.status = ProjectStatus.assembling
    session.commit()
    session.refresh(timeline)
    return timeline


def render_job_matches(render_job: RenderJob | None, timeline: Timeline, profile: str) -> bool:
    if render_job is None:
        return False
    return render_job.timeline_id == timeline.id and render_job.profile == profile


def summarize_generation_task_counts(tasks: list[GenerationTask]) -> dict[str, int]:
    counts = {"queued": 0, "running": 0, "succeeded": 0, "failed": 0}
    for task in tasks:
        counts[task.status.value] = counts.get(task.status.value, 0) + 1
    return counts


def uses_legacy_stage_mode(payload: PipelineRunRequest) -> bool:
    return any(
        stage is not None
        for stage in (
            payload.optimize,
            payload.plan,
            payload.image,
            payload.video,
            payload.timeline,
            payload.render,
            payload.run_render,
        )
    )


@router.post("/prompt/optimize", response_model=PromptOptimizeRead)
def optimize_prompt(
    project_id: uuid.UUID,
    payload: PromptOptimizeRequest,
    session: Session = Depends(get_session),
) -> PromptOptimizeRead:
    project = get_project_or_404(project_id, session)
    optimized_prompt, notes = optimize_project_prompt(
        project,
        creative_direction=payload.creative_direction,
        preserve_script=payload.preserve_script,
    )
    project.optimized_prompt = optimized_prompt
    project.prompt_optimization_notes = notes
    session.commit()

    return PromptOptimizeRead(
        project_id=project.id,
        optimized_prompt=optimized_prompt,
        prompt_optimization_notes=notes,
    )


@router.post("/shots/plan", response_model=list[ShotRead], status_code=status.HTTP_201_CREATED)
def plan_shots(
    project_id: uuid.UUID,
    payload: PlanShotsRequest,
    session: Session = Depends(get_session),
) -> list[Shot]:
    project = get_project_or_404(project_id, session)
    return plan_project_shots(project, payload.shot_count, payload.replace_existing, session)


@router.get("/shots", response_model=list[ShotRead])
def list_shots(project_id: uuid.UUID, session: Session = Depends(get_session)) -> list[Shot]:
    get_project_or_404(project_id, session)
    return list_project_shots(session, project_id)


@router.post("/assets", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
def create_asset(
    project_id: uuid.UUID,
    payload: AssetCreate,
    session: Session = Depends(get_session),
) -> Asset:
    get_project_or_404(project_id, session)
    if payload.shot_id is not None:
        get_project_shot_or_404(project_id, payload.shot_id, session)
    asset = Asset(project_id=project_id, **payload.model_dump())
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.post("/assets/upload", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    project_id: uuid.UUID,
    file: UploadFile | None = File(default=None),
    kind: AssetKind | None = Form(default=None),
    label: str | None = Form(default=None),
    shot_id: uuid.UUID | None = Form(default=None),
    attach_to_shot: bool = Form(default=False),
    reference_image: UploadFile | None = File(default=None),
    reference_video: UploadFile | None = File(default=None),
    audio: UploadFile | None = File(default=None),
    subtitle: UploadFile | None = File(default=None),
    session: Session = Depends(get_session),
) -> Asset:
    get_project_or_404(project_id, session)
    resolved_kind, upload = resolve_uploaded_file(
        file=file,
        kind=kind,
        reference_image=reference_image,
        reference_video=reference_video,
        audio=audio,
        subtitle=subtitle,
    )

    shot: Shot | None = None
    if shot_id is not None:
        shot = get_project_shot_or_404(project_id, shot_id, session)

    if attach_to_shot and shot is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shot_id is required when attach_to_shot is true")
    if attach_to_shot and resolved_kind not in {AssetKind.reference_image, AssetKind.reference_video}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only reference_image and reference_video can be attached to a shot",
        )

    if not upload.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file must include a filename")

    contents = await upload.read()
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    suffix = Path(upload.filename).suffix.lower()
    temp_dir = Path(settings.local_render_dir) / "uploads" / str(project_id)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    asset_id = uuid.uuid4()
    object_key = build_upload_object_key(project_id, resolved_kind, asset_id, upload.filename)
    content_type = upload.content_type or mimetypes.guess_type(upload.filename)[0] or "application/octet-stream"
    width, height = detect_upload_dimensions(contents, resolved_kind)

    try:
        with tempfile.NamedTemporaryFile(dir=temp_dir, suffix=suffix, delete=False) as temp_file:
            temp_file.write(contents)
            temp_path = Path(temp_file.name)
        asset_uri = upload_file(temp_path, object_key, content_type=content_type)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    asset = Asset(
        id=asset_id,
        project_id=project_id,
        shot_id=shot.id if shot is not None else None,
        kind=resolved_kind,
        label=label or Path(upload.filename).stem or upload.filename,
        uri=asset_uri,
        duration_seconds=None,
        width=width,
        height=height,
        metadata_json={
            "source_filename": upload.filename,
            "content_type": content_type,
            "file_size_bytes": len(contents),
            "object_key": object_key,
            "uploaded_via": "api",
        },
    )
    session.add(asset)
    if attach_to_shot and shot is not None:
        shot.result_asset_id = asset.id
        shot.status = ShotStatus.ready

    session.commit()
    session.refresh(asset)
    return asset


@router.get("/assets", response_model=list[AssetRead])
def list_assets(project_id: uuid.UUID, session: Session = Depends(get_session)) -> list[Asset]:
    get_project_or_404(project_id, session)
    statement = select(Asset).where(Asset.project_id == project_id).order_by(Asset.created_at.desc())
    return list(session.scalars(statement).all())


@router.post("/generation-tasks", response_model=list[GenerationTaskRead], status_code=status.HTTP_201_CREATED)
def create_generation_tasks(
    project_id: uuid.UUID,
    payload: GenerationTaskCreate,
    session: Session = Depends(get_session),
) -> list[GenerationTask]:
    project = get_project_or_404(project_id, session)
    model = payload.model or settings.seedance_model

    if payload.shot_id:
        shots = [session.get(Shot, payload.shot_id)]
        if shots[0] is None or shots[0].project_id != project.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shot not found")
    else:
        shots = list_project_shots(session, project.id)

    if not shots:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plan shots before creating Seedance tasks")

    tasks = create_provider_generation_tasks(
        project,
        [shot for shot in shots if shot is not None],
        provider="volcengine_seedance",
        model=model,
        attach_generated_images_to_shots=True,
        session=session,
    )
    if is_seedance_configured():
        submit_generation_tasks(tasks)
    return tasks


@router.post("/image-generation-tasks", response_model=list[GenerationTaskRead], status_code=status.HTTP_201_CREATED)
def create_image_generation_tasks(
    project_id: uuid.UUID,
    payload: ImageGenerationTaskCreate,
    session: Session = Depends(get_session),
) -> list[GenerationTask]:
    project = get_project_or_404(project_id, session)
    model = payload.model or settings.seedream_model

    if payload.shot_id:
        shots = [session.get(Shot, payload.shot_id)]
        if shots[0] is None or shots[0].project_id != project.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shot not found")
    else:
        shots = list_project_shots(session, project.id)

    if not shots:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plan shots before creating image tasks")

    tasks = create_provider_generation_tasks(
        project,
        [shot for shot in shots if shot is not None],
        provider="volcengine_seedream",
        model=model,
        attach_generated_images_to_shots=payload.attach_to_shots,
        session=session,
    )
    if is_seedream_configured():
        submit_generation_tasks(tasks)
    return tasks


@router.get("/generation-tasks", response_model=list[GenerationTaskRead])
def list_generation_tasks(project_id: uuid.UUID, session: Session = Depends(get_session)) -> list[GenerationTask]:
    get_project_or_404(project_id, session)
    return list_project_generation_tasks(session, project_id)


@router.post("/generation-tasks/{task_id}/submit", response_model=GenerationTaskRead)
def submit_generation_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> GenerationTask:
    get_project_or_404(project_id, session)
    generation_task = session.get(GenerationTask, task_id)
    if generation_task is None or generation_task.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation task not found")
    if generation_task.provider == "volcengine_seedream":
        submit_seedream_image_task.delay(str(generation_task.id))
    else:
        submit_seedance_generation_task.delay(str(generation_task.id))
    return generation_task


@router.post("/generation-tasks/{task_id}/poll", response_model=GenerationTaskRead)
def poll_generation_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> GenerationTask:
    get_project_or_404(project_id, session)
    generation_task = session.get(GenerationTask, task_id)
    if generation_task is None or generation_task.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation task not found")
    if generation_task.provider == "volcengine_seedream":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seedream image tasks complete during submit and do not support polling.",
        )
    poll_seedance_generation_task.delay(str(generation_task.id))
    return generation_task


@router.post("/pipeline/run", response_model=PipelineRunRead)
def run_project_pipeline(
    project_id: uuid.UUID,
    payload: PipelineRunRequest,
    session: Session = Depends(get_session),
) -> PipelineRunRead:
    project = get_project_or_404(project_id, session)
    triggered_steps: list[str] = []
    skipped_steps: list[str] = []
    waiting_on: list[str] = []
    explicit_fields = payload.model_fields_set

    if uses_legacy_stage_mode(payload):
        latest_timeline_id: uuid.UUID | None = None
        latest_render_job_id: uuid.UUID | None = None

        if payload.optimize:
            optimize_prompt(
                project_id,
                PromptOptimizeRequest(
                    creative_direction=payload.creative_direction,
                    preserve_script=payload.preserve_script,
                ),
                session,
            )
            triggered_steps.append("optimize_prompt")

        if payload.plan:
            plan_shots(
                project_id,
                PlanShotsRequest(
                    shot_count=payload.shot_count,
                    replace_existing=payload.replace_existing,
                ),
                session,
            )
            triggered_steps.append("plan_shots")

        shots = list_project_shots(session, project.id)
        if payload.image:
            if not shots:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plan shots before creating image tasks")
            create_image_generation_tasks(
                project_id,
                ImageGenerationTaskCreate(
                    model=payload.image_model,
                    attach_to_shots=payload.attach_images_to_shots,
                ),
                session,
            )
            triggered_steps.append("create_image_tasks")

        if payload.video:
            if not shots:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plan shots before creating video tasks")
            create_generation_tasks(
                project_id,
                GenerationTaskCreate(model=payload.video_model),
                session,
            )
            triggered_steps.append("create_video_tasks")

        if payload.timeline:
            timeline = create_timeline(project_id, TimelineCreate(), session)
            latest_timeline_id = timeline.id
            triggered_steps.append("create_timeline")

        if payload.render:
            render_job = create_render_job(
                project_id,
                RenderJobCreate(profile=payload.render_profile or "social_1080p"),
                session,
            )
            latest_render_job_id = render_job.id
            triggered_steps.append("create_render_job")

        if payload.run_render:
            render_job_id_to_run = latest_render_job_id
            if render_job_id_to_run is None:
                latest_render_job = get_latest_render_job_for_project(session, project.id)
                render_job_id_to_run = latest_render_job.id if latest_render_job else None
            if render_job_id_to_run is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Create a render job before running render")
            run_project_render_job(project_id, render_job_id_to_run, session)
            latest_render_job_id = render_job_id_to_run
            triggered_steps.append("run_render_job")

        generation_tasks = list_project_generation_tasks(session, project.id)
        latest_timeline = get_latest_timeline_for_project(session, project.id)
        latest_render_job = get_latest_render_job_for_project(session, project.id)
        session.refresh(project)

        return PipelineRunRead(
            project_id=project.id,
            project_status=project.status or ProjectStatus.draft,
            triggered_steps=triggered_steps,
            skipped_steps=skipped_steps,
            waiting_on=waiting_on,
            shot_count=len(list_project_shots(session, project.id)),
            ready_shot_count=sum(1 for shot in list_project_shots(session, project.id) if shot.result_asset_id),
            generation_task_counts=summarize_generation_task_counts(generation_tasks),
            latest_timeline_id=latest_timeline.id if latest_timeline else latest_timeline_id,
            latest_render_job_id=latest_render_job.id if latest_render_job else latest_render_job_id,
        )

    if payload.optimize_prompt:
        optimized_prompt, notes = optimize_project_prompt(project)
        if project.optimized_prompt != optimized_prompt or project.prompt_optimization_notes != notes:
            project.optimized_prompt = optimized_prompt
            project.prompt_optimization_notes = notes
            session.commit()
            triggered_steps.append("optimize_prompt")
        else:
            skipped_steps.append("optimize_prompt")

    shots = list_project_shots(session, project.id)
    if not shots and payload.create_image_tasks and "create_image_tasks" in explicit_fields and not payload.create_video_tasks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plan shots before running downstream pipeline stages")
    if payload.replace_existing_shots or not shots:
        shots = plan_project_shots(project, payload.shot_count, payload.replace_existing_shots or not shots, session)
        triggered_steps.append("plan_shots")
    else:
        skipped_steps.append("plan_shots")

    if not shots:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plan shots before running the pipeline")

    if payload.create_image_tasks:
        image_tasks = create_provider_generation_tasks(
            project,
            shots,
            provider="volcengine_seedream",
            model=settings.seedream_model,
            attach_generated_images_to_shots=payload.attach_generated_images_to_shots,
            session=session,
        )
        if image_tasks:
            triggered_steps.append("create_image_tasks")
        else:
            skipped_steps.append("create_image_tasks")
        submitted = submit_generation_tasks(list_project_generation_tasks(session, project.id, provider="volcengine_seedream"))
        if submitted:
            triggered_steps.append("submit_image_tasks")
        elif not is_seedream_configured():
            waiting_on.append("seedream_provider_configuration")
        else:
            skipped_steps.append("submit_image_tasks")

    if payload.create_video_tasks:
        video_tasks = create_provider_generation_tasks(
            project,
            shots,
            provider="volcengine_seedance",
            model=settings.seedance_model,
            attach_generated_images_to_shots=True,
            session=session,
        )
        if video_tasks:
            triggered_steps.append("create_video_tasks")
        else:
            skipped_steps.append("create_video_tasks")
        submitted = submit_generation_tasks(list_project_generation_tasks(session, project.id, provider="volcengine_seedance"))
        if submitted:
            triggered_steps.append("submit_video_tasks")
        elif not is_seedance_configured():
            waiting_on.append("seedance_provider_configuration")
        else:
            skipped_steps.append("submit_video_tasks")

    shots = list_project_shots(session, project.id)
    all_shots_ready = bool(shots) and all(shot.result_asset_id for shot in shots)
    latest_timeline = get_latest_timeline_for_project(session, project.id)
    latest_render_job = get_latest_render_job_for_project(session, project.id)
    profile = payload.profile or ("landscape_1080p" if project.target_ratio == "16:9" else "social_1080p")

    if payload.build_timeline_when_ready:
        if all_shots_ready:
            if timeline_matches_shots(latest_timeline, shots):
                skipped_steps.append("create_timeline")
            else:
                latest_timeline = create_project_timeline(project, shots, TimelineCreate(), session)
                triggered_steps.append("create_timeline")
        else:
            if "build_timeline_when_ready" in explicit_fields and not payload.create_image_tasks and not payload.create_video_tasks:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Shots must have ready assets before creating a timeline")
            waiting_on.append("shots_ready_for_timeline")

    if payload.create_render_job_when_ready:
        if latest_timeline is None:
            if "create_render_job_when_ready" in explicit_fields and not payload.build_timeline_when_ready:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Create a timeline before creating a render job")
            waiting_on.append("timeline_available_for_render")
        elif any(not segment.get("asset_id") for segment in latest_timeline.segments):
            waiting_on.append("timeline_assets_complete_for_render")
        else:
            if render_job_matches(latest_render_job, latest_timeline, profile):
                skipped_steps.append("create_render_job")
            else:
                ffmpeg_plan = build_ffmpeg_plan(
                    {
                        "id": str(latest_timeline.id),
                        "segments": latest_timeline.segments,
                        "audio_tracks": latest_timeline.audio_tracks,
                        "subtitle_tracks": latest_timeline.subtitle_tracks,
                    },
                    profile,
                )
                latest_render_job = RenderJob(
                    project_id=project.id,
                    timeline_id=latest_timeline.id,
                    profile=profile,
                    status=JobStatus.queued,
                    ffmpeg_plan=ffmpeg_plan,
                )
                session.add(latest_render_job)
                project.status = ProjectStatus.rendering
                session.commit()
                session.refresh(latest_render_job)
                triggered_steps.append("create_render_job")

    if payload.run_render_when_ready:
        if latest_render_job is None:
            if "run_render_when_ready" in explicit_fields and not payload.create_render_job_when_ready:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Create a render job before running render")
            waiting_on.append("render_job_available_for_run")
        elif latest_render_job.status == JobStatus.queued:
            run_render_job.delay(str(latest_render_job.id))
            triggered_steps.append("run_render_job")
        elif latest_render_job.status == JobStatus.running:
            waiting_on.append("render_job_running")
        else:
            skipped_steps.append("run_render_job")

    generation_tasks = list_project_generation_tasks(session, project.id)
    latest_timeline = get_latest_timeline_for_project(session, project.id)
    latest_render_job = get_latest_render_job_for_project(session, project.id)
    session.refresh(project)

    return PipelineRunRead(
        project_id=project.id,
        project_status=project.status or ProjectStatus.draft,
        triggered_steps=triggered_steps,
        skipped_steps=skipped_steps,
        waiting_on=list(dict.fromkeys(waiting_on)),
        shot_count=len(shots),
        ready_shot_count=sum(1 for shot in shots if shot.result_asset_id),
        generation_task_counts=summarize_generation_task_counts(generation_tasks),
        latest_timeline_id=latest_timeline.id if latest_timeline else None,
        latest_render_job_id=latest_render_job.id if latest_render_job else None,
    )


@router.post("/timelines", response_model=TimelineRead, status_code=status.HTTP_201_CREATED)
def create_timeline(
    project_id: uuid.UUID,
    payload: TimelineCreate,
    session: Session = Depends(get_session),
) -> Timeline:
    project = get_project_or_404(project_id, session)
    segments = payload.segments
    if segments is None:
        shots = list_project_shots(session, project.id)
        if not shots:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plan shots before creating a timeline")
        ensure_all_shots_ready(shots)
    return create_project_timeline(project, list_project_shots(session, project.id), payload, session)


@router.get("/timelines", response_model=list[TimelineRead])
def list_timelines(project_id: uuid.UUID, session: Session = Depends(get_session)) -> list[Timeline]:
    get_project_or_404(project_id, session)
    statement = select(Timeline).where(Timeline.project_id == project_id).order_by(Timeline.version.desc())
    return list(session.scalars(statement).all())


@router.get("/timelines/latest", response_model=TimelineRead)
def get_latest_timeline(project_id: uuid.UUID, session: Session = Depends(get_session)) -> Timeline:
    get_project_or_404(project_id, session)
    timeline = get_latest_timeline_for_project(session, project_id)
    if timeline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timeline not found")
    return timeline


@router.post("/render-jobs", response_model=RenderJobRead, status_code=status.HTTP_201_CREATED)
def create_render_job(
    project_id: uuid.UUID,
    payload: RenderJobCreate,
    session: Session = Depends(get_session),
) -> RenderJob:
    project = get_project_or_404(project_id, session)
    if payload.timeline_id:
        timeline = session.get(Timeline, payload.timeline_id)
        if timeline is None or timeline.project_id != project.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timeline not found")
    else:
        timeline = get_latest_timeline_for_project(session, project.id)

    if timeline is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Create a timeline before rendering")

    incomplete_segments = [segment.get("label") or f"segment-{index + 1}" for index, segment in enumerate(timeline.segments) if not segment.get("asset_id")]
    if incomplete_segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Timeline is missing assets for: {', '.join(str(item) for item in incomplete_segments)}",
        )

    ffmpeg_plan = build_ffmpeg_plan(
        {
            "id": str(timeline.id),
            "segments": timeline.segments,
            "audio_tracks": timeline.audio_tracks,
            "subtitle_tracks": timeline.subtitle_tracks,
        },
        payload.profile,
    )
    render_job = RenderJob(
        project_id=project.id,
        timeline_id=timeline.id,
        profile=payload.profile,
        status=JobStatus.queued,
        ffmpeg_plan=ffmpeg_plan,
    )
    session.add(render_job)
    project.status = ProjectStatus.rendering
    session.commit()
    session.refresh(render_job)
    return render_job


@router.get("/render-jobs", response_model=list[RenderJobRead])
def list_render_jobs(project_id: uuid.UUID, session: Session = Depends(get_session)) -> list[RenderJob]:
    get_project_or_404(project_id, session)
    statement = select(RenderJob).where(RenderJob.project_id == project_id).order_by(RenderJob.created_at.desc())
    return list(session.scalars(statement).all())


@router.post("/render-jobs/{render_job_id}/run", response_model=RenderJobRead)
def run_project_render_job(
    project_id: uuid.UUID,
    render_job_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> RenderJob:
    get_project_or_404(project_id, session)
    render_job = session.get(RenderJob, render_job_id)
    if render_job is None or render_job.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Render job not found")
    run_render_job.delay(str(render_job.id))
    return render_job
