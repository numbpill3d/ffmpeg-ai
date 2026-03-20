"""Free TTS via edge-tts (Microsoft Edge, no API key)."""
import asyncio
from pathlib import Path
import edge_tts

# Good voices for Shorts — clear, energetic
VOICES = {
    "en-male": "en-US-GuyNeural",
    "en-female": "en-US-JennyNeural",
    "en-news": "en-US-AriaNeural",
}
DEFAULT_VOICE = VOICES["en-female"]


async def synthesize(text: str, output_path: Path, voice: str = DEFAULT_VOICE, rate: str = "+10%") -> Path:
    """Convert text to speech and save as MP3."""
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(output_path))
    return output_path


async def synthesize_segments(
    segments: list[dict],
    out_dir: Path,
    voice: str = DEFAULT_VOICE,
) -> list[Path]:
    """Synthesize each script segment to its own audio file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = [
        synthesize(seg["text"], out_dir / f"seg_{i:03d}.mp3", voice=voice)
        for i, seg in enumerate(segments)
    ]
    return await asyncio.gather(*tasks)
