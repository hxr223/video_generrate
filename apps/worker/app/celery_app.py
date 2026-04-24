import uuid
from pathlib import Path

from celery import Celery
from sqlalchemy import select

from packages.core.database import SessionLocal
from packages.core.models import Asset, AssetKind, GenerationTask, JobStatus, ProjectStatus, RenderJob, ShotStatus, Timeline
from packages.core.settings import settings
from packages.integrations.seedance import (
    SeedanceClient,
    SeedanceClientError,
    extract_error_message,
    extract_provider_status,
    extract_provider_task_id,
    extract_video_url,
    is_provider_terminal_failure,
    is_provider_terminal_success,
)
from packages.media.ffmpeg import render_timeline
from packages.media.storage import upload_file


celery_app = Celery(
    "video_platform",
    broker=settings.redis_url,
    backend=settings.redis_url,
)


@celery_app.task(name="video_platform.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="video_platform.submit_seedance_generation_task")
def submit_seedance_generation_task(task_id: str) -> dict[str, str]:
    task_uuid = uuid.UUID(task_id)
    with SessionLocal() as session:
        generation_task = session.get(GenerationTask, task_uuid)
        if generation_task is None:
            return {"status": "missing", "task_id": task_id}
        if not settings.ark_api_key:
            generation_task.status = JobStatus.failed
            generation_task.error_message = "ARK_API_KEY is required to submit Seedance tasks."
            session.commit()
            return {"status": "failed", "task_id": task_id}

        generation_task.status = JobStatus.running
        session.commit()

        try:
            response_payload = SeedanceClient().submit_generation(generation_task.request_payload)
            provider_task_id = extract_provider_task_id(response_payload)
            if provider_task_id is None:
                raise SeedanceClientError("Seedance response did not include a task id.")
            generation_task.provider_task_id = provider_task_id
            generation_task.request_payload = {
                **generation_task.request_payload,
                "provider_submit_response": response_payload,
            }
            session.commit()
        except Exception as exc:
            generation_task.status = JobStatus.failed
            generation_task.error_message = str(exc)
            session.commit()
            return {"status": "failed", "task_id": task_id}

    poll_seedance_generation_task.apply_async(args=[task_id], countdown=settings.seedance_poll_interval_seconds)
    return {"status": "submitted", "task_id": task_id}


@celery_app.task(name="video_platform.poll_seedance_generation_task")
def poll_seedance_generation_task(task_id: str, attempt: int = 1) -> dict[str, str]:
    task_uuid = uuid.UUID(task_id)
    with SessionLocal() as session:
        generation_task = session.get(GenerationTask, task_uuid)
        if generation_task is None:
            return {"status": "missing", "task_id": task_id}
        if generation_task.provider_task_id is None:
            generation_task.status = JobStatus.failed
            generation_task.error_message = "Seedance provider task id is missing."
            session.commit()
            return {"status": "failed", "task_id": task_id}

        try:
            response_payload = SeedanceClient().query_generation(generation_task.provider_task_id)
            provider_status = extract_provider_status(response_payload)
            video_url = extract_video_url(response_payload)
            generation_task.request_payload = {
                **generation_task.request_payload,
                "provider_latest_response": response_payload,
            }

            if is_provider_terminal_failure(provider_status):
                generation_task.status = JobStatus.failed
                generation_task.error_message = extract_error_message(response_payload) or "Seedance generation failed."
                session.commit()
                return {"status": "failed", "task_id": task_id}

            if is_provider_terminal_success(provider_status, response_payload) and video_url:
                temp_path = Path(settings.local_render_dir) / "seedance" / f"{generation_task.id}.mp4"
                SeedanceClient().download_video(video_url, temp_path)
                object_key = f"seedance/{generation_task.project_id}/{generation_task.id}.mp4"
                asset_uri = upload_file(temp_path, object_key, content_type="video/mp4")
                asset = Asset(
                    project_id=generation_task.project_id,
                    kind=AssetKind.seedance_video,
                    label=f"Seedance {generation_task.id}",
                    uri=asset_uri,
                    duration_seconds=None,
                    metadata_json={
                        "provider_task_id": generation_task.provider_task_id,
                        "source_url": video_url,
                    },
                )
                session.add(asset)
                session.flush()

                generation_task.status = JobStatus.succeeded
                generation_task.result_asset_id = asset.id
                if generation_task.shot:
                    generation_task.shot.status = ShotStatus.ready
                    generation_task.shot.result_asset_id = asset.id
                session.commit()
                return {"status": "succeeded", "task_id": task_id}

            generation_task.status = JobStatus.running
            session.commit()
        except Exception as exc:
            generation_task.status = JobStatus.failed
            generation_task.error_message = str(exc)
            session.commit()
            return {"status": "failed", "task_id": task_id}

    if attempt >= settings.seedance_max_poll_attempts:
        with SessionLocal() as session:
            generation_task = session.get(GenerationTask, task_uuid)
            if generation_task:
                generation_task.status = JobStatus.failed
                generation_task.error_message = "Seedance polling exceeded max attempts."
                session.commit()
        return {"status": "timeout", "task_id": task_id}

    poll_seedance_generation_task.apply_async(
        args=[task_id, attempt + 1],
        countdown=settings.seedance_poll_interval_seconds,
    )
    return {"status": "running", "task_id": task_id}


@celery_app.task(name="video_platform.run_render_job")
def run_render_job(render_job_id: str) -> dict[str, str]:
    render_uuid = uuid.UUID(render_job_id)
    with SessionLocal() as session:
        render_job = session.get(RenderJob, render_uuid)
        if render_job is None:
            return {"status": "missing", "render_job_id": render_job_id}

        render_job.status = JobStatus.running
        session.commit()

        try:
            timeline = session.get(Timeline, render_job.timeline_id)
            if timeline is None:
                raise RuntimeError("Timeline not found for render job.")
            assets = {
                str(asset.id): asset
                for asset in session.scalars(select(Asset).where(Asset.project_id == render_job.project_id)).all()
            }
            output_path, probe = render_timeline(
                timeline=timeline,
                assets_by_id=assets,
                profile_name=render_job.profile,
                output_dir=Path(settings.local_render_dir) / "exports" / str(render_job.id),
            )
            object_key = f"exports/{render_job.project_id}/{render_job.id}.mp4"
            output_uri = upload_file(output_path, object_key, content_type="video/mp4")
            asset = Asset(
                project_id=render_job.project_id,
                kind=AssetKind.export,
                label=f"Export {render_job.profile}",
                uri=output_uri,
                metadata_json={"render_job_id": str(render_job.id), "ffprobe": probe},
            )
            session.add(asset)
            render_job.status = JobStatus.succeeded
            render_job.output_uri = output_uri
            project = render_job.project
            project.final_video_url = output_uri
            project.status = ProjectStatus.completed
            session.commit()
            return {"status": "succeeded", "render_job_id": render_job_id}
        except Exception as exc:
            render_job.status = JobStatus.failed
            render_job.error_message = str(exc)
            if render_job.project:
                render_job.project.status = ProjectStatus.failed
            session.commit()
            return {"status": "failed", "render_job_id": render_job_id}
