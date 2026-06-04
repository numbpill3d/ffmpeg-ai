"""Designed thumbnail generator for YouTube Shorts and landscape videos."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

# Font search order — condensed bold gives the most impact per pixel
_BOLD_FONTS = [
    "/usr/share/fonts/TTF/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]


def _font(size: int):
    from PIL import ImageFont
    for path in _BOLD_FONTS:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _fit_crop(img, w: int, h: int):
    """Resize + center-crop to exact (w, h)."""
    from PIL import Image as _Image
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    new_w, new_h = int(iw * scale), int(ih * scale)
    img = img.resize((new_w, new_h), _Image.LANCZOS)
    x, y = (new_w - w) // 2, (new_h - h) // 2
    return img.crop((x, y, x + w, y + h))


def _gradient_overlay(width: int, height: int, top_alpha: int, bottom_alpha: int):
    """Build an RGBA black gradient — dark at top and bottom, transparent in centre."""
    from PIL import Image
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = overlay.load()
    mid = height // 2
    for y in range(height):
        if y < mid:
            a = int(top_alpha * (1 - y / mid))
        else:
            a = int(bottom_alpha * ((y - mid) / max(mid, 1)))
        for x in range(width):
            pixels[x, y] = (0, 0, 0, a)
    return overlay


def _wrap_title(title: str, max_chars: int) -> str:
    """Wrap title to max_chars per line, at most 3 lines, preserving words."""
    words = title.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        test = " ".join(current + [word])
        if len(test) > max_chars and current:
            lines.append(" ".join(current))
            current = [word]
            if len(lines) == 2:
                current.extend(words[words.index(word) + 1:])
                break
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines[:3])


def _draw_text_shadowed(
    draw,
    text: str,
    font,
    x: int,
    y: int,
    fill: tuple = (255, 255, 255),
    shadow: tuple = (0, 0, 0),
    shadow_offset: int = 4,
    align: str = "center",
) -> None:
    for dx, dy in [(shadow_offset, shadow_offset), (-1, shadow_offset), (shadow_offset, -1)]:
        draw.multiline_text(
            (x + dx, y + dy), text, font=font, fill=shadow, align=align, anchor="ma",
        )
    draw.multiline_text((x, y), text, font=font, fill=fill, align=align, anchor="ma")


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return r, g, b


def make_thumbnail(
    source_image: Path,
    title: str,
    output_path: Path,
    mode: str = "shorts",
    brand_name: str = "",
    accent_color: str = "#00d4ff",
) -> Path:
    """Generate a YouTube-ready thumbnail from a source image.

    Applies contrast boost, gradient overlay, bold title text with drop shadow,
    an accent bar, and optional channel branding.

    mode: "shorts" → 1080×1920  |  "landscape" → 1280×720
    """
    from PIL import Image, ImageDraw, ImageEnhance

    if mode == "landscape":
        width, height = 1280, 720
        title_y_pct    = 0.30
        title_max_chars = 22
        title_font_sz  = 80
        brand_font_sz  = 36
        accent_bar_h   = 8
        accent_bar_y   = int(height * 0.08)
        top_dark       = 200
        bot_dark       = 140
    else:                           # shorts / 9:16
        width, height = 1080, 1920
        title_y_pct    = 0.22
        title_max_chars = 18
        title_font_sz  = 96
        brand_font_sz  = 42
        accent_bar_h   = 10
        accent_bar_y   = int(height * 0.06)
        top_dark       = 210
        bot_dark       = 160

    img = Image.open(source_image).convert("RGB")
    img = _fit_crop(img, width, height)

    # Boost contrast and saturation — makes it pop on the shelf
    img = ImageEnhance.Contrast(img).enhance(1.25)
    img = ImageEnhance.Color(img).enhance(1.35)

    # Dark gradient overlay
    overlay = _gradient_overlay(width, height, top_dark, bot_dark)
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)

    # Accent bar (horizontal stripe below top dark zone)
    accent_rgb = _hex_to_rgb(accent_color)
    draw.rectangle(
        [(0, accent_bar_y), (width, accent_bar_y + accent_bar_h)],
        fill=accent_rgb,
    )

    # Title text
    title_font  = _font(title_font_sz)
    wrapped     = _wrap_title(title.upper(), title_max_chars)
    title_y     = int(height * title_y_pct)
    _draw_text_shadowed(
        draw, wrapped, title_font,
        x=width // 2, y=title_y,
        fill=(255, 255, 255),
        shadow=(0, 0, 0),
        shadow_offset=5,
    )

    # Channel branding at bottom
    if brand_name:
        brand_font = _font(brand_font_sz)
        brand_y = height - int(height * 0.06)
        # Accent dot before name
        dot_r = brand_font_sz // 4
        dot_x = width // 2 - 120
        dot_y = brand_y - dot_r
        draw.ellipse(
            [(dot_x, dot_y), (dot_x + dot_r * 2, dot_y + dot_r * 2)],
            fill=accent_rgb,
        )
        draw.text(
            (dot_x + dot_r * 2 + 12, brand_y),
            brand_name,
            font=brand_font,
            fill=(200, 200, 200),
            anchor="lm",
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(str(output_path), "JPEG", quality=93, optimize=True)
    return output_path


def make_thumbnail_from_job(
    job_dir: Path,
    title: str,
    output_path: Path,
    mode: str = "shorts",
    brand_name: str = "",
    accent_color: str = "#00d4ff",
) -> Optional[Path]:
    """Try to build a designed thumbnail from the job image cache.

    Falls back gracefully to None if no images are cached yet.
    """
    # Prefer frame_000 (hook image) — usually the most visually striking
    for candidate in ["frame_000.jpg", "frame_001.jpg", "frame_002.jpg"]:
        img_path = job_dir / "images" / candidate
        if img_path.exists():
            return make_thumbnail(
                img_path, title, output_path,
                mode=mode, brand_name=brand_name, accent_color=accent_color,
            )
    return None
