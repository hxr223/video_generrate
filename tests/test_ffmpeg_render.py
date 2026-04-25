import shutil
import subprocess
from pathlib import Path

import pytest

from packages.core.models import Asset, AssetKind, Timeline
from packages.media.ffmpeg import render_timeline


pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def _make_color_clip(path: Path, color: str) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x240:d=1:r=30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _make_color_image(path: Path, color: str) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x240",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_render_timeline_outputs_mp4(tmp_path: Path) -> None:
    first_clip = tmp_path / "first.mp4"
    second_clip = tmp_path / "second.mp4"
    _make_color_clip(first_clip, "red")
    _make_color_clip(second_clip, "blue")

    first_asset = Asset(kind=AssetKind.seedance_video, label="first", uri=str(first_clip))
    first_asset.id = "00000000-0000-0000-0000-000000000001"
    second_asset = Asset(kind=AssetKind.seedance_video, label="second", uri=str(second_clip))
    second_asset.id = "00000000-0000-0000-0000-000000000002"
    timeline = Timeline(
        version=1,
        duration_seconds=2,
        segments=[
            {"asset_id": str(first_asset.id), "start": 0, "duration": 1},
            {"asset_id": str(second_asset.id), "start": 1, "duration": 1},
        ],
        audio_tracks=[],
        subtitle_tracks=[],
    )

    output_path, probe = render_timeline(
        timeline=timeline,
        assets_by_id={str(first_asset.id): first_asset, str(second_asset.id): second_asset},
        profile_name="landscape_1080p",
        output_dir=tmp_path / "render",
    )

    assert output_path.exists()
    assert output_path.suffix == ".mp4"
    assert probe["format"]["duration"]


def test_render_timeline_accepts_generated_image_asset(tmp_path: Path) -> None:
    image = tmp_path / "storyboard.png"
    _make_color_image(image, "green")

    asset = Asset(kind=AssetKind.generated_image, label="storyboard", uri=str(image), duration_seconds=2)
    asset.id = "00000000-0000-0000-0000-000000000003"
    timeline = Timeline(
        version=1,
        duration_seconds=2,
        segments=[{"asset_id": str(asset.id), "start": 0, "duration": 2}],
        audio_tracks=[],
        subtitle_tracks=[],
    )

    output_path, probe = render_timeline(
        timeline=timeline,
        assets_by_id={str(asset.id): asset},
        profile_name="landscape_1080p",
        output_dir=tmp_path / "image-render",
    )

    assert output_path.exists()
    assert float(probe["format"]["duration"]) >= 1.9
