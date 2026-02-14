"""
VERIFUSE V2 — Engine 4: Text Obfuscator (Anti-Scraper Defense)

Renders sensitive text (owner name, mailing address) as a Base64 PNG
with random noise pixels to defeat OCR scraping.
"""

from __future__ import annotations

import base64
import io
import random

from PIL import Image, ImageDraw, ImageFont


# Attempt to load a monospace font; fall back to default bitmap font
def _get_font(size: int = 18) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def text_to_image(
    text: str,
    font_size: int = 18,
    noise_density: float = 0.02,
    padding: int = 12,
) -> str:
    """Render *text* onto a transparent PNG and return a Base64 data string.

    Parameters
    ----------
    text : str
        The sensitive text to render (e.g. owner name).
    font_size : int
        Font size in pixels.
    noise_density : float
        Fraction of pixels to randomise (0.0–0.10 recommended).
    padding : int
        Pixel padding around the text.

    Returns
    -------
    str
        ``data:image/png;base64,<payload>`` suitable for ``<img src=...>``.
    """
    font = _get_font(font_size)

    # Measure text bounding box
    dummy = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    img_w = text_w + padding * 2
    img_h = text_h + padding * 2
    img = Image.new("RGBA", (img_w, img_h), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # Draw the text in dark grey
    draw.text((padding, padding), text, fill=(40, 40, 40, 255), font=font)

    # Sprinkle noise pixels to defeat OCR
    total_pixels = img_w * img_h
    noise_count = int(total_pixels * noise_density)
    for _ in range(noise_count):
        x = random.randint(0, img_w - 1)
        y = random.randint(0, img_h - 1)
        grey = random.randint(100, 200)
        alpha = random.randint(60, 160)
        img.putpixel((x, y), (grey, grey, grey, alpha))

    # Encode to Base64 PNG
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"
