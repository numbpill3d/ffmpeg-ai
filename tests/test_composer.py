from pathlib import Path

from ffmpeg_ai.video import composer


def test_concat_plain_escapes_apostrophes_in_manifest(tmp_path, monkeypatch) -> None:
    first = tmp_path / "speaker's clip.mp4"
    second = tmp_path / "closing.mp4"
    first.touch()
    second.touch()
    captured: dict[str, str] = {}

    def capture_manifest(cmd: list[str], label: str) -> None:
        manifest = Path(cmd[cmd.index("-i") + 1])
        captured["contents"] = manifest.read_text()

    monkeypatch.setattr(composer, "_run", capture_manifest)

    composer.concat_plain([first, second], tmp_path / "output.mp4")

    assert "speaker'\\''s clip.mp4" in captured["contents"]
    assert captured["contents"].endswith(f"file '{second.resolve()}'\n")
