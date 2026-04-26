from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.core.models import GenerationTask, JobStatus, Project, ProjectStatus, RenderJob, Shot, ShotStatus, Timeline


def sync_project_status(session: Session, project_id: uuid.UUID) -> Project | None:
    project = session.get(Project, project_id)
    if project is None:
        return None

    shots = list(session.scalars(select(Shot).where(Shot.project_id == project_id)).all())
    generation_tasks = list(session.scalars(select(GenerationTask).where(GenerationTask.project_id == project_id)).all())
    render_jobs = list(session.scalars(select(RenderJob).where(RenderJob.project_id == project_id)).all())
    timelines = list(session.scalars(select(Timeline).where(Timeline.project_id == project_id)).all())

    if any(render_job.status == JobStatus.failed for render_job in render_jobs):
        project.status = ProjectStatus.failed
    elif any(render_job.status in {JobStatus.queued, JobStatus.running} for render_job in render_jobs):
        project.status = ProjectStatus.rendering
    elif any(render_job.status == JobStatus.succeeded for render_job in render_jobs) and project.final_video_url:
        project.status = ProjectStatus.completed
    elif any(shot.status == ShotStatus.failed for shot in shots) or any(task.status == JobStatus.failed for task in generation_tasks):
        project.status = ProjectStatus.failed
    elif any(task.status in {JobStatus.queued, JobStatus.running} for task in generation_tasks):
        project.status = ProjectStatus.generating
    elif timelines or (shots and all(shot.status == ShotStatus.ready for shot in shots)):
        project.status = ProjectStatus.assembling
    elif shots:
        project.status = ProjectStatus.planning
    else:
        project.status = ProjectStatus.draft

    return project
