from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.client import Config

from packages.core.settings import settings


def storage_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        region_name=settings.minio_region,
        config=Config(signature_version="s3v4"),
    )


def ensure_bucket() -> None:
    client = storage_client()
    buckets = client.list_buckets().get("Buckets", [])
    if any(bucket.get("Name") == settings.minio_bucket for bucket in buckets):
        return
    client.create_bucket(Bucket=settings.minio_bucket)


def upload_file(path: Path, object_key: str, content_type: str | None = None) -> str:
    ensure_bucket()
    extra_args = {"ContentType": content_type} if content_type else None
    client = storage_client()
    if extra_args:
        client.upload_file(str(path), settings.minio_bucket, object_key, ExtraArgs=extra_args)
    else:
        client.upload_file(str(path), settings.minio_bucket, object_key)

    if settings.object_storage_public_base_url:
        return f"{settings.object_storage_public_base_url.rstrip('/')}/{object_key}"
    return f"minio://{settings.minio_bucket}/{object_key}"


def download_minio_uri(uri: str, destination: Path) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "minio":
        raise ValueError(f"Not a minio URI: {uri}")
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    destination.parent.mkdir(parents=True, exist_ok=True)
    storage_client().download_file(bucket, key, str(destination))
    return destination
