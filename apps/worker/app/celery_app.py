from celery import Celery

from packages.core.settings import settings


celery_app = Celery(
    "video_platform",
    broker=settings.redis_url,
    backend=settings.redis_url,
)


@celery_app.task(name="video_platform.ping")
def ping() -> str:
    return "pong"

