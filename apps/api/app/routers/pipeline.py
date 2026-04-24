import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.core.database import get_session
from packages.core.models import Asset, GenerationTask, JobStatus, Project, ProjectStatus, RenderJob, Shot, ShotStatus, Timeline
from packages.core.schemas import (
    AssetCreate,
    AssetRead,
    GenerationTaskCreate,
    GenerationTaskRead,
    PlanShotsRequest,
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
from packages.media.ffmpeg import build_ffmpeg_plan
from packages.timeline.planner import build_seedance_shots, build_timeline_segments, infer_timeline_duration
from packages.timeline.prompt_optimizer import optimize_project_prompt
from apps.worker.app.celery_app import (
    poll_seedance_generation_task,
    run_render_job,
    submit_seedance_generation_task,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["pipeline"])


def get_project_or_404(project_id: uuid.UUID, session: Session) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


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

    if payload.replace_existing:
        existing = session.scalars(select(Shot).where(Shot.project_id == project.id)).all()
        for shot in existing:
            session.delete(shot)
        session.flush()

    planned_shots = [
        Shot(project_id=project.id, status=ShotStatus.planned, **shot_payload)
        for shot_payload in build_seedance_shots(project, payload.shot_count)
    ]
    session.add_all(planned_shots)
    project.status = ProjectStatus.planning
    session.commit()

    for shot in planned_shots:
        session.refresh(shot)
    return planned_shots


@router.get("/shots", response_model=list[ShotRead])
def list_shots(project_id: uuid.UUID, session: Session = Depends(get_session)) -> list[Shot]:
    get_project_or_404(project_id, session)
    statement = select(Shot).where(Shot.project_id == project_id).order_by(Shot.order_index.asc())
    return list(session.scalars(statement).all())


@router.post("/assets", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
def create_asset(
    project_id: uuid.UUID,
    payload: AssetCreate,
    session: Session = Depends(get_session),
) -> Asset:
    get_project_or_404(project_id, session)
    asset = Asset(project_id=project_id, **payload.model_dump())
    session.add(asset)
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
        shots = list(
            session.scalars(
                select(Shot).where(Shot.project_id == project.id).order_by(Shot.order_index.asc())
            ).all()
        )

    if not shots:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plan shots before creating Seedance tasks")

    tasks: list[GenerationTask] = []
    for shot in shots:
        if shot is None:
            continue
        shot.status = ShotStatus.queued
        request_payload = build_seedance_request(project, shot, model=model)
        if not is_seedance_configured():
            request_payload["configuration_warning"] = "ARK_API_KEY is empty; task is queued locally only."
        tasks.append(
            GenerationTask(
                project_id=project.id,
                shot_id=shot.id,
                model=model,
                status=JobStatus.queued,
                request_payload=request_payload,
            )
        )

    session.add_all(tasks)
    project.status = ProjectStatus.generating
    session.commit()

    for task in tasks:
        session.refresh(task)
    return tasks


@router.get("/generation-tasks", response_model=list[GenerationTaskRead])
def list_generation_tasks(project_id: uuid.UUID, session: Session = Depends(get_session)) -> list[GenerationTask]:
    get_project_or_404(project_id, session)
    statement = select(GenerationTask).where(GenerationTask.project_id == project_id).order_by(GenerationTask.created_at.desc())
    return list(session.scalars(statement).all())


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
    poll_seedance_generation_task.delay(str(generation_task.id))
    return generation_task


@router.post("/timelines", response_model=TimelineRead, status_code=status.HTTP_201_CREATED)
def create_timeline(
    project_id: uuid.UUID,
    payload: TimelineCreate,
    session: Session = Depends(get_session),
) -> Timeline:
    project = get_project_or_404(project_id, session)
    segments = payload.segments
    if segments is None:
        shots = list(
            session.scalars(
                select(Shot).where(Shot.project_id == project.id).order_by(Shot.order_index.asc())
            ).all()
        )
        if not shots:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plan shots before creating a timeline")
        segments = build_timeline_segments(shots)

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


@router.get("/timelines", response_model=list[TimelineRead])
def list_timelines(project_id: uuid.UUID, session: Session = Depends(get_session)) -> list[Timeline]:
    get_project_or_404(project_id, session)
    statement = select(Timeline).where(Timeline.project_id == project_id).order_by(Timeline.version.desc())
    return list(session.scalars(statement).all())


@router.get("/timelines/latest", response_model=TimelineRead)
def get_latest_timeline(project_id: uuid.UUID, session: Session = Depends(get_session)) -> Timeline:
    get_project_or_404(project_id, session)
    timeline = session.scalar(
        select(Timeline).where(Timeline.project_id == project_id).order_by(Timeline.version.desc()).limit(1)
    )
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
        timeline = session.scalar(
            select(Timeline).where(Timeline.project_id == project.id).order_by(Timeline.version.desc()).limit(1)
        )

    if timeline is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Create a timeline before rendering")

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
