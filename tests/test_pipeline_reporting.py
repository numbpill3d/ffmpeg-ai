import asyncio
from pathlib import Path

import pytest

from ffmpeg_ai import pipeline
from ffmpeg_ai.ai import images


def test_init_run_report_records_core_request_fields(tmp_path: Path) -> None:
    report = pipeline._init_run_report(
        topic="Deep Sea Mysteries",
        output_path=tmp_path / "video.mp4",
        job_dir=tmp_path / "job",
        mode="shorts",
        duration=45,
        model="openai/gpt-oss-120b:free",
        voice="en-US-JennyNeural",
        style="dramatic",
        caption_style="karaoke",
        render_mode="storyboard",
        thumbnail=True,
        music_path=tmp_path / "music.mp3",
        images_dir=None,
        use_ai_images=True,
        image_providers=["pollinations", "huggingface"],
        fresh=True,
        dry_run=False,
        no_captions=False,
        no_ambience=True,
        brand_name="My Channel",
        accent_color="#ff00aa",
    )

    assert report["topic"] == "Deep Sea Mysteries"
    assert report["mode"] == "shorts"
    assert report["duration_target_s"] == 45
    assert report["render_mode"] == "storyboard"
    assert report["model_requested"] == "openai/gpt-oss-120b:free"
    assert report["image_strategy"] == {
        "source": "ai",
        "providers": ["pollinations", "huggingface"],
    }
    assert report["thumbnail"] == {
        "enabled": True,
        "brand_name": "My Channel",
        "accent_color": "#ff00aa",
    }
    assert report["music"] == {"enabled": True, "path": str(tmp_path / "music.mp3")}
    assert report["job_dir"] == str(tmp_path / "job")
    assert report["output_path"] == str(tmp_path / "video.mp4")


def test_finalize_run_report_writes_json_file(tmp_path: Path) -> None:
    report = {"topic": "Ocean Trenches", "status": "running"}

    path = pipeline._finalize_run_report(
        report,
        tmp_path,
        status="succeeded",
        elapsed_s=12.34,
        extra={"placeholder_count": 2, "thumbnail": {"mode": "designed"}},
    )

    assert path == tmp_path / "run_report.json"
    saved = path.read_text(encoding="utf-8")
    assert '"status": "succeeded"' in saved
    assert '"elapsed_s": 12.34' in saved
    assert '"placeholder_count": 2' in saved
    assert '"mode": "designed"' in saved


def test_check_ffmpeg_raises_when_tool_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline.shutil, "which", lambda tool: None if tool == "ffprobe" else f"/usr/bin/{tool}")

    with pytest.raises(RuntimeError, match="'ffprobe' not found in PATH"):
        pipeline._check_ffmpeg()


def test_generate_image_reports_provider_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[tuple[str, bool]] = []

    async def fail_bfl(*args, **kwargs):
        return None

    async def ok_pollinations(prompt, output_path, seed, width, height):
        output_path.write_bytes(b"fake jpg")
        return output_path

    monkeypatch.setattr(images, "_try_bfl", fail_bfl)
    monkeypatch.setattr(images, "_try_pollinations", ok_pollinations)

    path, is_placeholder = asyncio.run(images.generate_image(
        "retro terminal",
        tmp_path / "frame.jpg",
        providers=["bfl", "pollinations"],
        on_attempt=lambda provider, ok: attempts.append((provider, ok)),
    ))

    assert path == tmp_path / "frame.jpg"
    assert is_placeholder is False
    assert attempts == [("bfl", False), ("pollinations", True)]


def test_cached_placeholder_images_are_rejected(tmp_path: Path) -> None:
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    for i in range(3):
        (img_dir / f"frame_{i:03d}.jpg").write_bytes(b"fake jpg")
    (img_dir / "manifest.json").write_text(
        '{"placeholder_count": 3, "providers": ["pollinations"]}',
        encoding="utf-8",
    )

    cache_ok, cached_frames = pipeline._cached_images_are_valid(
        img_dir,
        3,
        signature="abc",
    )

    assert cache_ok is False
    assert len(cached_frames) == 3


def test_cached_real_images_are_accepted(tmp_path: Path) -> None:
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    for i in range(2):
        (img_dir / f"frame_{i:03d}.jpg").write_bytes(b"fake jpg")
    (img_dir / "manifest.json").write_text(
        '{"placeholder_count": 0, "signature": "abc", "providers": ["pollinations"]}',
        encoding="utf-8",
    )

    cache_ok, cached_frames = pipeline._cached_images_are_valid(
        img_dir,
        2,
        signature="abc",
    )

    assert cache_ok is True
    assert len(cached_frames) == 2


def test_cached_images_reject_signature_mismatch(tmp_path: Path) -> None:
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    for i in range(2):
        (img_dir / f"frame_{i:03d}.jpg").write_bytes(b"fake jpg")
    (img_dir / "manifest.json").write_text(
        '{"placeholder_count": 0, "signature": "abc", "providers": ["pollinations"]}',
        encoding="utf-8",
    )

    cache_ok, cached_frames = pipeline._cached_images_are_valid(
        img_dir,
        2,
        signature="xyz",
    )

    assert cache_ok is False
    assert len(cached_frames) == 2


def test_cached_real_images_fall_back_to_run_report(tmp_path: Path) -> None:
    job_dir = tmp_path / "job"
    img_dir = job_dir / "images"
    img_dir.mkdir(parents=True)
    for i in range(2):
        (img_dir / f"frame_{i:03d}.jpg").write_bytes(b"fake jpg")
    (job_dir / "run_report.json").write_text(
        '{"placeholder_count": 0, "status": "succeeded"}',
        encoding="utf-8",
    )

    cache_ok, cached_frames = pipeline._cached_images_are_valid(
        img_dir,
        2,
        signature="xyz",
    )

    assert cache_ok is True
    assert len(cached_frames) == 2
