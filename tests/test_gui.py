from ffmpeg_ai.gui import JobSpec, build_command


def test_generate_command_includes_gui_selections() -> None:
    cmd = build_command(JobSpec(
        kind="generate",
        topic="deep sea signals",
        output_path="/tmp/out.mp4",
        mode="landscape",
        duration=120,
        model="openai/gpt-oss-120b:free",
        voice="en-documentary",
        style="documentary",
        caption_style="plain",
        brand_name="Node 07",
        accent_color="#00d4ff",
        images_dir="/tmp/images",
        music_path="/tmp/music.mp3",
        script_path="/tmp/script.json",
        dry_run=True,
        edit_script=True,
        fresh=True,
        no_thumbnail=True,
        no_ambience=True,
        no_captions=True,
        no_ai_images=True,
    ))

    assert cmd[:4] == [cmd[0], "-m", "ffmpeg_ai", "generate"]
    assert "deep sea signals" in cmd
    assert "--quiet" in cmd
    assert "--no-ai-images" in cmd
    assert "--edit-script" in cmd
    assert "--output" in cmd
    assert "--mode" in cmd


def test_channel_command_uses_selected_controls() -> None:
    cmd = build_command(JobSpec(
        kind="channel",
        channel_name="history",
        count=2,
        model="test-model",
        upload="on",
        shorts=True,
        landscape=False,
        dry_run=True,
    ))

    assert cmd[:5] == [cmd[0], "-m", "ffmpeg_ai", "channel", "run"]
    assert "history" in cmd
    assert "--no-landscape" in cmd
    assert "--upload" in cmd
    assert "--quiet" in cmd
