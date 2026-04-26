from fastapi import APIRouter, Request

from packages.core.schemas import (
    ALLOWED_PROJECT_DURATIONS,
    PublicSettingsCapabilitiesRead,
    PublicSettingsModelsRead,
    PublicSettingsProvidersRead,
    PublicSettingsRead,
    PublicSettingsServicesRead,
)
from packages.core.settings import settings
from packages.integrations.seedance import get_seedance_base_url, is_seedance_configured
from packages.integrations.seedream import get_seedream_base_url, is_seedream_configured
from packages.media.ffmpeg import EXPORT_PROFILES


router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/public", response_model=PublicSettingsRead)
def get_public_settings(request: Request) -> PublicSettingsRead:
    return PublicSettingsRead(
        app_name=settings.app_name,
        app_env=settings.app_env,
        allowed_project_durations=sorted(ALLOWED_PROJECT_DURATIONS),
        render_profiles=sorted(EXPORT_PROFILES.keys()),
        providers=PublicSettingsProvidersRead(
            seedance_configured=is_seedance_configured(),
            seedream_configured=is_seedream_configured(),
        ),
        models=PublicSettingsModelsRead(
            seedance=settings.seedance_model,
            seedream=settings.seedream_model,
            seedream_size=settings.seedream_size,
        ),
        services=PublicSettingsServicesRead(
            api_base_url=(settings.public_api_base_url or str(request.base_url)).rstrip("/"),
            ark_base_url=settings.ark_base_url.rstrip("/"),
            seedance_base_url=get_seedance_base_url(),
            seedream_base_url=get_seedream_base_url(),
            minio_endpoint=settings.minio_endpoint,
            object_storage_public_base_url=settings.object_storage_public_base_url,
            minio_bucket=settings.minio_bucket,
        ),
        capabilities=PublicSettingsCapabilitiesRead(),
    )
