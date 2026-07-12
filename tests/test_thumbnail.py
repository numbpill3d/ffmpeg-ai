from ffmpeg_ai.video.thumbnail import _wrap_title


def test_wrap_title_preserves_repeated_words_in_final_line() -> None:
    wrapped = _wrap_title("ECHO ECHO SIGNAL ECHO SIGNAL", max_chars=10)

    assert wrapped.splitlines() == [
        "ECHO ECHO",
        "SIGNAL",
        "ECHO SIGNAL",
    ]
