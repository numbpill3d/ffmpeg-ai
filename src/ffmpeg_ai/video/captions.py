"""Generate ASS/SRT captions from audio using faster-whisper."""
from pathlib import Path

_STYLE_CONFIGS = {
    "karaoke": {
        "size": 75, "margin_v": 140, "words_per_line": 4, "karaoke": True,
        "primary": "&H00FFFFFF", "secondary": "&H0000FFFF",
    },
    "plain": {
        "size": 60, "margin_v": 100, "words_per_line": 5, "karaoke": False,
        "primary": "&H00FFFFFF", "secondary": "&H00FFFFFF",
    },
    "bold-center": {
        "size": 90, "margin_v": 240, "words_per_line": 4, "karaoke": False,
        "primary": "&H00FFFFFF", "secondary": "&H00FFFFFF",
    },
}


def audio_to_ass(
    audio_path: Path,
    output_path: Path,
    model_size: str = "base",
    style: str = "karaoke",
) -> Path:
    """Transcribe audio and write an ASS file with configurable caption style.

    Styles:
      karaoke    — TikTok-style word-level highlight fill (default)
      plain      — clean white subtitles, no karaoke timing
      bold-center — large bold centered text, no karaoke timing
    """
    from faster_whisper import WhisperModel

    cfg = _STYLE_CONFIGS.get(style, _STYLE_CONFIGS["karaoke"])

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        str(audio_path), beam_size=5, word_timestamps=True, language="en"
    )

    words: list[tuple[float, float, str]] = []
    for seg in segments:
        if seg.words:
            for w in seg.words:
                text = w.word.strip()
                if text:
                    words.append((w.start, w.end, text))

    if not words:
        srt_path = output_path.with_suffix(".srt")
        audio_to_srt(audio_path, srt_path, model_size)
        return srt_path

    wpl = cfg["words_per_line"]
    chunks: list[list[tuple[float, float, str]]] = []
    for i in range(0, len(words), wpl):
        chunk = words[i : i + wpl]
        if chunk:
            chunks.append(chunk)

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "WrapStyle: 0\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Arial,{cfg['size']},"
        f"{cfg['primary']},{cfg['secondary']},&H00000000,&HA0000000,"
        f"1,0,0,0,100,100,2,0,1,4,2,2,30,30,{cfg['margin_v']},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    event_lines: list[str] = []
    for chunk in chunks:
        start = chunk[0][0]
        end   = chunk[-1][1]
        if cfg["karaoke"]:
            parts = []
            for w_start, w_end, word in chunk:
                cs = max(1, int((w_end - w_start) * 100))
                parts.append(f"{{\\kf{cs}}}{word}")
            text = " ".join(parts)
        else:
            text = " ".join(word for _, _, word in chunk)
        event_lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}"
        )

    output_path.write_text(header + "\n".join(event_lines) + "\n", encoding="utf-8")
    return output_path


def audio_to_srt(audio_path: Path, output_path: Path, model_size: str = "base") -> Path:
    """Transcribe audio and write an SRT file (segment-level)."""
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(audio_path), beam_size=5, language="en")

    srt_lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        start = _fmt_time(seg.start)
        end   = _fmt_time(seg.end)
        srt_lines += [str(i), f"{start} --> {end}", seg.text.strip(), ""]

    output_path.write_text("\n".join(srt_lines), encoding="utf-8")
    return output_path


def _ass_time(seconds: float) -> str:
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _fmt_time(seconds: float) -> str:
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
