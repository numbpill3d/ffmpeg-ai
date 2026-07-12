from ffmpeg_ai import pipeline


def test_adapt_script_normalizes_string_hook_cta_and_missing_prompts() -> None:
    script = {
        "hook": "Abyss alert",
        "segments": [
            {"text": "Segment one", "visual_prompts": []},
            {"text": "Segment two"},
        ],
        "cta": "Follow for more",
    }

    adapted = pipeline._adapt_script(script, topic="deep sea")

    assert adapted["hook"] == {"text": "Abyss alert", "visual_prompts": ["deep sea"]}
    assert adapted["cta"] == {"text": "Follow for more", "visual_prompts": ["deep sea"]}
    assert adapted["segments"][0]["visual_prompts"] == ["deep sea"]
    assert adapted["segments"][1]["visual_prompts"] == ["deep sea"]


def test_adapt_script_preserves_string_visual_prompt_as_singleton_list() -> None:
    script = {
        "hook": {"text": "Abyss alert", "visual_prompts": "glowing trench"},
        "segments": [],
        "cta": {"text": "Follow for more", "visual_prompts": "follow button"},
    }

    adapted = pipeline._adapt_script(script, topic="deep sea")

    assert adapted["hook"]["visual_prompts"] == ["glowing trench"]
    assert adapted["cta"]["visual_prompts"] == ["follow button"]


def test_expand_timeline_for_pacing_splits_long_landscape_visuals() -> None:
    prompts, mapping = pipeline._expand_timeline_for_pacing(
        prompts=["slide-a", "slide-b"],
        part_mapping=[(30.0, 1), (4.0, 1)],
        max_clip_duration=6.0,
    )

    assert prompts == ["slide-a"] * 5 + ["slide-b"]
    assert mapping == [(30.0, 5), (4.0, 1)]


def test_expand_timeline_for_pacing_preserves_prompt_cycle_order() -> None:
    prompts, mapping = pipeline._expand_timeline_for_pacing(
        prompts=["wide", "detail"],
        part_mapping=[(13.0, 2)],
        max_clip_duration=5.0,
    )

    assert prompts == ["wide", "detail", "wide"]
    assert mapping == [(13.0, 3)]


def test_plan_clip_durations_accounts_for_storyboard_without_transition_overlap() -> None:
    plan = pipeline._plan_render(
        images=[object(), object(), object()],
        part_mapping=[(18.0, 3)],
        total_dur=18.0,
        max_duration=600,
        render_mode="storyboard",
    )

    assert plan.transition_duration == 0
    assert plan.clip_durations == [6.0, 6.0, 6.0]
    assert plan.clip_count == 3


def test_plan_clip_durations_adds_overlap_only_for_kenburns() -> None:
    plan = pipeline._plan_render(
        images=[object(), object()],
        part_mapping=[(12.0, 2)],
        total_dur=12.0,
        max_duration=600,
        render_mode="kenburns",
    )

    assert plan.transition_duration == 0.4
    assert plan.clip_durations == [6.2, 6.2]


def test_render_mode_defaults_to_landscape_storyboard() -> None:
    assert pipeline._default_render_mode("landscape") == "storyboard"
    assert pipeline._default_render_mode("shorts") == "kenburns"
