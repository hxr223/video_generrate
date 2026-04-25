from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from packages.core.models import Asset, AssetKind, Timeline
from packages.media.storage import download_minio_uri


EXPORT_PROFILES: dict[str, dict[str, Any]] = {
    "social_1080p": {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "video_codec": "libx264",
        "audio_codec": "aac",
        "pixel_format": "yuv420p",
    },
    "landscape_1080p": {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "video_codec": "libx264",
        "audio_codec": "aac",
        "pixel_format": "yuv420p",
    },
    "master_prores": {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "video_codec": "prores_ks",
        "audio_codec": "aac",
        "pixel_format": "yuv422p10le",
    },
}


def build_ffmpeg_plan(timeline: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profile = EXPORT_PROFILES.get(profile_name, EXPORT_PROFILES["social_1080p"])
    segments = timeline.get("segments", [])
    inputs = [segment for segment in segments if segment.get("asset_id")]
    scale_filter = (
        f"scale={profile['width']}:{profile['height']}:force_original_aspect_ratio=increase,"
        f"crop={profile['width']}:{profile['height']},fps={profile['fps']},format={profile['pixel_format']}"
    )

    return {
        "engine": "ffmpeg",
        "profile": profile_name,
        "profile_settings": profile,
        "status": "plan_only",
        "inputs": inputs,
        "filter_strategy": {
            "normalize": scale_filter,
            "video_assembly": "trim + setpts + concat/xfade",
            "subtitles": "ass/subtitles filter with Chinese font",
            "audio": "amix + afade + loudnorm",
            "qa": "ffprobe + blackdetect + silencedetect",
        },
        "commands": [
            {
                "name": "normalize_inputs",
                "argv": [
                    "ffmpeg",
                    "-i",
                    "<input>",
                    "-vf",
                    scale_filter,
                    "-c:v",
                    profile["video_codec"],
                    "-c:a",
                    profile["audio_codec"],
                    "<normalized-output>",
                ],
            },
            {
                "name": "render_timeline",
                "argv": [
                    "ffmpeg",
                    "-filter_complex",
                    "<generated-filtergraph>",
                    "-c:v",
                    profile["video_codec"],
                    "-c:a",
                    profile["audio_codec"],
                    "<final-output>",
                ],
            },
            {
                "name": "probe_output",
                "argv": ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", "<final-output>"],
            },
        ],
    }


def _resolve_asset_uri(uri: str, work_dir: Path) -> Path | str:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return Path(parsed.path)
    if parsed.scheme == "minio":
        return download_minio_uri(uri, work_dir / "inputs" / Path(parsed.path).name)
    if parsed.scheme in {"http", "https"}:
        return uri
    return Path(uri)


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _probe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("ffprobe did not return a JSON object")
    return payload


def _is_image_asset(asset: Asset) -> bool:
    if asset.kind in {AssetKind.generated_image, AssetKind.reference_image}:
        return True
    suffix = urlparse(asset.uri).path.lower()
    return suffix.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"))


def render_timeline(
    timeline: Timeline,
    assets_by_id: dict[str, Asset],
    profile_name: str,
    output_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg and ffprobe must be available on PATH")

    profile = EXPORT_PROFILES.get(profile_name, EXPORT_PROFILES["social_1080p"])
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir = output_dir / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)

    segments = [segment for segment in timeline.segments if segment.get("asset_id")]
    if not segments:
        raise RuntimeError("Timeline has no segments with asset_id; cannot render.")

    normalized_paths: list[Path] = []
    scale_filter = (
        f"scale={profile['width']}:{profile['height']}:force_original_aspect_ratio=increase,"
        f"crop={profile['width']}:{profile['height']},fps={profile['fps']},format={profile['pixel_format']}"
    )

    for index, segment in enumerate(segments):
        asset_id = str(segment["asset_id"])
        asset = assets_by_id.get(asset_id)
        if asset is None:
            raise RuntimeError(f"Missing asset for segment: {asset_id}")
        source = _resolve_asset_uri(asset.uri, output_dir)
        normalized_path = normalized_dir / f"{index:03d}.mp4"
        duration = str(segment.get("duration", asset.duration_seconds or 9999))
        if _is_image_asset(asset):
            command = [
                ffmpeg,
                "-y",
                "-loop",
                "1",
                "-t",
                duration,
                "-i",
                str(source),
                "-vf",
                scale_filter,
                "-an",
                "-c:v",
                profile["video_codec"],
                "-preset",
                "veryfast",
                normalized_path.as_posix(),
            ]
        else:
            command = [
                ffmpeg,
                "-y",
                "-i",
                str(source),
                "-t",
                duration,
                "-vf",
                scale_filter,
                "-an",
                "-c:v",
                profile["video_codec"],
                "-preset",
                "veryfast",
                normalized_path.as_posix(),
            ]
        _run(command)
        normalized_paths.append(normalized_path)

    concat_list = output_dir / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in normalized_paths),
        encoding="utf-8",
    )
    output_path = output_dir / "final.mp4"
    _run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_list.as_posix(),
            "-c",
            "copy",
            output_path.as_posix(),
        ]
    )
    return output_path, _probe(output_path)
