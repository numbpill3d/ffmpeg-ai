from pathlib import Path
import json

import pytest

from ffmpeg_ai import pipeline


class _TrackerStub:
    def __init__(self, *args, **kwargs) -> None:
        self._live = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def start(self, *args, **kwargs) -> None:
        return None

    def complete(self, *args, **kwargs) -> None:
        return None

    def fail(self, *args, **kwargs) -> None:
        return None

    def print(self, *args, **kwargs) -> None:
        return None

    def set_image_count(self, *args, **kwargs) -> None:
        return None

    def image_done(self, *args, **kwargs) -> None:
        return None

    def update(self, *args, **kwargs) -> None:
        return None


@pytest.mark.asyncio
async def test_run_pipeline_writes_failed_report_when_script_generation_crashes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job_cache = tmp_path / "jobs"
    monkeypatch.setattr(pipeline, "_JOB_CACHE", job_cache)
    monkeypatch.setattr(pipeline, "PipelineTracker", _TrackerStub)
    monkeypatch.setattr(pipeline, "_check_ffmpeg", lambda: None)

    async def _boom(*args, **kwargs):
        raise RuntimeError("script boom")

    monkeypatch.setattr(pipeline, "generate_script", _boom)

    with pytest.raises(RuntimeError, match="script boom"):
        await pipeline.run_pipeline("Broken Topic", tmp_path / "out.mp4", quiet=True)

    report_path = job_cache / "broken-topic" / "run_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["failed_stage"] == "SCRIPT"
    assert report["error"] == "script boom"
