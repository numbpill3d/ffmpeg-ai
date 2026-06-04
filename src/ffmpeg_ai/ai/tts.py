"""Free TTS via edge-tts (Microsoft Edge, no API key required)."""
import asyncio
from pathlib import Path

import edge_tts

# Full voice catalog — covers all channel styles and tones
VOICES: dict[str, str] = {
    # Neutral / general
    "en-female":      "en-US-JennyNeural",     # clear, warm — default
    "en-male":        "en-US-GuyNeural",        # measured, clear
    "en-news":        "en-US-AriaNeural",       # news anchor cadence
    # Documentary & long-form
    "en-documentary": "en-GB-RyanNeural",       # authoritative British male
    "en-uk-female":   "en-GB-SoniaNeural",      # British female, precise
    # Energetic / shorts-optimised
    "en-energetic":   "en-US-JasonNeural",      # younger male, punchy
    "en-storyteller": "en-US-SaraNeural",       # warm narrative female
    # Regional variety
    "en-au-female":   "en-AU-NatashaNeural",    # Australian female
    "en-au-male":     "en-AU-WilliamNeural",    # Australian male
    "en-in-female":   "en-IN-NeerjaNeural",     # Indian English female
}

DEFAULT_VOICE = VOICES["en-female"]

# Suggested voice per style preset — auto-selected when channel has no voice override
STYLE_VOICE_MAP: dict[str, str] = {
    "educational":  "en-female",
    "dramatic":     "en-male",
    "listicle":     "en-energetic",
    "documentary":  "en-documentary",
    "morris":       "en-documentary",
    "curiosity":    "en-storyteller",
    "mythology":    "en-storyteller",
    "horror":       "en-documentary",
    "finance":      "en-energetic",
}


def recommended_voice(style: str | None) -> str:
    """Return the recommended voice key for a given style preset."""
    return STYLE_VOICE_MAP.get(style or "", "en-female")


# TTS speech rate per mode — shorts are faster to hold attention
_RATE_FOR_MODE: dict[str, str] = {
    "shorts":    "+12%",
    "landscape": "+2%",
}


def rate_for_mode(mode: str) -> str:
    return _RATE_FOR_MODE.get(mode, "+0%")


async def synthesize(
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VOICE,
    rate: str = "+10%",
    retries: int = 4,
) -> Path:
    """Convert text to speech and save as MP3. Retries on transient failures."""
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            await communicate.save(str(output_path))
            return output_path
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
    raise RuntimeError(f"TTS failed after {retries} attempts: {last_err}") from last_err


async def synthesize_segments(
    segments: list[dict],
    out_dir: Path,
    voice: str = DEFAULT_VOICE,
    mode: str = "shorts",
) -> list[Path]:
    """Synthesize each script segment to its own audio file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rate = rate_for_mode(mode)
    tasks = [
        synthesize(seg["text"], out_dir / f"seg_{i:03d}.mp3", voice=voice, rate=rate)
        for i, seg in enumerate(segments)
    ]
    return list(await asyncio.gather(*tasks))
