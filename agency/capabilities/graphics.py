from __future__ import annotations

import colorsys
import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger("agency.graphics")

FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def palette_from_brand(brand: dict) -> list[tuple[int, int, int]]:
    colors = brand.get("palette", ["#101820", "#1F6FEB", "#F2F7FA", "#FFB000"])
    return [hex_to_rgb(c) for c in colors]


def _vertical_gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    w, h = size
    base = Image.new("RGB", size)
    draw = ImageDraw.Draw(base)
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return base


def render_scene_image(
    dst: Path,
    width: int,
    height: int,
    title: str,
    subtitle: str = "",
    palette: list[tuple[int, int, int]] | None = None,
    style_seed: int = 0,
) -> Path:
    palette = palette or [(16, 24, 32), (31, 111, 235), (242, 247, 250)]
    top, accent, light = palette[0], palette[1 % len(palette)], palette[-1]
    bottom = (min(255, accent[0] + 26), min(255, accent[1] + 26), min(255, accent[2] + 26))
    img = _vertical_gradient((width, height), top, bottom)
    rng_draw = ImageDraw.Draw(img)

    seed = style_seed % 5
    cx = width * (0.22 + 0.13 * seed)
    cy = height * (0.3 + 0.08 * ((seed * 3) % 4))
    radius = min(width, height) * (0.12 + 0.03 * (seed % 3))
    halo_r = int(radius * 1.9)
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse([cx - halo_r, cy - halo_r, cx + halo_r, cy + halo_r], fill=accent + (70,))
    glow = glow.filter(ImageFilter.GaussianBlur(width // 40))
    img.paste(glow, (0, 0), glow)
    rng_draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=light)
    rng_draw.ellipse(
        [cx - radius * 0.55, cy - radius * 0.55, cx + radius * 0.55, cy + radius * 0.55],
        fill=accent,
    )

    band_h = int(height * 0.14)
    band_y = height - band_h
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([0, band_y, width, height], fill=(10, 14, 18, 200))
    title_font = find_font(int(height * 0.052))
    sub_font = find_font(int(height * 0.030))
    tw = rng_draw.textlength(title, font=title_font)
    od.text(((width - tw) / 2, band_y + band_h * 0.12), title, font=title_font, fill=(255, 255, 255, 255))
    if subtitle:
        sw = rng_draw.textlength(subtitle, font=sub_font)
        od.text(((width - sw) / 2, band_y + band_h * 0.62), subtitle, font=sub_font, fill=(210, 220, 230, 255))
    out = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst, "PNG")
    return dst


def render_title_card(dst: Path, width: int, height: int, brand_name: str, tagline: str, palette: list[tuple[int, int, int]] | None = None) -> Path:
    palette = palette or [(16, 24, 32), (31, 111, 235), (242, 247, 250)]
    bg, accent, light = palette[0], palette[1 % len(palette)], palette[-1]
    img = Image.new("RGB", (width, height), bg)
    d = ImageDraw.Draw(img)
    bar_w = int(width * 0.06)
    d.rectangle([0, 0, bar_w, height], fill=accent)
    name_font = find_font(int(height * 0.11))
    tag_font = find_font(int(height * 0.042))
    nw = d.textlength(brand_name, font=name_font)
    d.text(((width - nw) / 2 + bar_w / 2, height * 0.40), brand_name, font=name_font, fill=light)
    tw = d.textlength(tagline, font=tag_font)
    d.text(((width - tw) / 2 + bar_w / 2, height * 0.56), tagline, font=tag_font, fill=accent)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "PNG")
    return dst


def render_lower_third(
    dst: Path,
    width: int,
    height: int,
    primary_text: str,
    secondary_text: str = "",
    palette: list[tuple[int, int, int]] | None = None,
) -> Path:
    palette = palette or [(16, 24, 32), (31, 111, 235), (242, 247, 250)]
    accent = palette[1 % len(palette)]
    lw = int(width * 0.52)
    lh = int(height * 0.135)
    int(width * 0.06)
    int(height * 0.10)
    img = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    accent_bar_w = int(lw * 0.015)
    d.rectangle([0, 0, accent_bar_w, lh], fill=accent + (255,))
    d.rounded_rectangle([accent_bar_w, 0, lw, lh], radius=int(lh * 0.12), fill=(12, 16, 22, 216))
    main_font = find_font(int(lh * 0.42))
    sec_font = find_font(int(lh * 0.28))
    pad = int(lh * 0.18)
    d.text((accent_bar_w + pad, pad * 0.8), primary_text, font=main_font, fill=(255, 255, 255, 255))
    if secondary_text:
        d.text((accent_bar_w + pad, pad * 0.8 + lh * 0.45), secondary_text, font=sec_font, fill=(196, 208, 220, 255))
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "PNG")
    return dst


def render_thumbnail(dst: Path, src_frame: Path, headline: str, width: int = 1280, height: int = 720) -> Path:
    img = Image.open(src_frame).convert("RGB").resize((width, height))
    d = ImageDraw.Draw(img, "RGBA")
    strip_h = int(height * 0.30)
    d.rectangle([0, height - strip_h, width, height], fill=(10, 14, 18, 205))
    font = find_font(int(strip_h * 0.42))
    text = headline.upper()
    d.textlength(text, font=font)
    lines = wrap_text(d, text, font, int(width * 0.92))
    total_h = sum(int(strip_h * 0.5) for _ in lines)
    y = height - strip_h + (strip_h - total_h) / 2
    for line in lines:
        d.text(((width - d.textlength(line, font=font)) / 2, y), line, font=font, fill=(255, 255, 255, 255))
        y += int(strip_h * 0.5)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "PNG")
    return dst


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:2]


def dominant_colors(image_path: Path, n: int = 4) -> list[tuple[int, int, int]]:
    img = Image.open(image_path).convert("RGB").resize((64, 64))
    pixels = list(img.getdata())
    buckets: dict[tuple[int, int, int], int] = {}
    for r, g, b in pixels:
        key = (r // 32 * 32, g // 32 * 32, b // 32 * 32)
        buckets[key] = buckets.get(key, 0) + 1
    return sorted(buckets, key=buckets.get, reverse=True)[:n]


def palette_distance(a: list[tuple[int, int, int]], b: list[tuple[int, int, int]]) -> float:
    def dist(x: tuple[int, int, int], y: tuple[int, int, int]) -> float:
        return sum((p - q) ** 2 for p, q in zip(x, y, strict=False)) ** 0.5

    if not a or not b:
        return 441.67
    total = sum(min(dist(x, y) for y in b) for x in a)
    return total / len(a)


__all__ = [
    "render_scene_image",
    "render_title_card",
    "render_lower_third",
    "render_thumbnail",
    "dominant_colors",
    "palette_distance",
    "palette_from_brand",
    "find_font",
    "colorsys",
]
