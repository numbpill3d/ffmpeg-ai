"""Generate ASS/SRT captions from audio using faster-whisper."""
from pathlib import Path


def audio_to_ass(audio_path: Path, output_path: Path, model_size: str = "base") -> Path:
    """Transcribe audio and write an ASS file with word-level karaoke timing.

    Each line shows ~4 words. As each word is spoken it fills from the
    secondary colour (yellow) to the primary colour (white), giving the
    CapCut / TikTok highlighted-word look.
    """
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(audio_path), beam_size=5, word_timestamps=True)

    words: list[tuple[float, float, str]] = []
    for seg in segments:
        if seg.words:
            for w in seg.words:
                text = w.word.strip()
                if text:
                    words.append((w.start, w.end, text))

    # Fall back to SRT if word-level data wasn't returned
    if not words:
        srt_path = output_path.with_suffix(".srt")
        audio_to_srt(audio_path, srt_path, model_size)
        # Convert the SRT path to a dummy ASS — caller will receive SRT
        return srt_path

    WORDS_PER_LINE = 4
    chunks: list[list[tuple[float, float, str]]] = []
    for i in range(0, len(words), WORDS_PER_LINE):
        chunk = words[i : i + WORDS_PER_LINE]
        if chunk:
            chunks.append(chunk)

    # ASS header — large font, centred low on screen, yellow karaoke fill
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
        # PrimaryColour=white, SecondaryColour=yellow, Outline=black, Shadow
        "Style: Default,Arial,65,"
        "&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,"
        "1,0,0,0,100,100,2,0,1,3,1,2,30,30,120,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    event_lines: list[str] = []
    for chunk in chunks:
        start = chunk[0][0]
        end = chunk[-1][1]
        parts: list[str] = []
        for w_start, w_end, word in chunk:
            cs = max(1, int((w_end - w_start) * 100))
            parts.append(f"{{\\kf{cs}}}{word}")
        text = " ".join(parts)
        event_lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}"
        )

    output_path.write_text(header + "\n".join(event_lines) + "\n", encoding="utf-8")
    return output_path


def audio_to_srt(audio_path: Path, output_path: Path, model_size: str = "base") -> Path:
    """Transcribe audio and write an SRT file (segment-level)."""
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(audio_path), beam_size=5)

    srt_lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        start = _fmt_time(seg.start)
        end = _fmt_time(seg.end)
        srt_lines += [str(i), f"{start} --> {end}", seg.text.strip(), ""]

    output_path.write_text("\n".join(srt_lines), encoding="utf-8")
    return output_path


# ── Time formatters ───────────────────────────────────────────────────────────

def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _fmt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
