from __future__ import annotations

from typing import Any


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
