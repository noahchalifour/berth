"""Build a numbered comparison sheet from the ten saved Higgsfield previews.

Run from the repo root: uv run python docs/branding/berth/logo-options/build_comparison.py
"""

import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).parent


def build():
    options = json.loads((ROOT / "prompts.json").read_text())
    assert len(options) == 10, "Expected ten logo directions"
    width, card_width, card_height, margin, gap = 1880, 900, 630, 28, 24
    sheet = Image.new("RGB", (width, 150 + 5 * (card_height + gap) + margin), "#EEF1F5")
    draw = ImageDraw.Draw(sheet)
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 46)
        label_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 25)
        body_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 23)
    except OSError:
        title_font = ImageFont.load_default(size=46)
        label_font = ImageFont.load_default(size=25)
        body_font = ImageFont.load_default(size=23)
    draw.text((margin, 27), "Berth / 10 logo directions", font=title_font, fill="#172636")
    draw.text((margin, 88), "Higgsfield Recraft vector concepts. Choose a number; no logo is installed yet.", font=body_font, fill="#536170")
    gallery = ["# Berth logo options", "", "Ten independent concepts generated through Higgsfield Recraft V4.1 in vector mode.", "The existing UI mark is unchanged pending selection. SVG originals and 2048px WebP previews are saved alongside this file.", "", "![All ten options](comparison.png)", ""]
    for index, option in enumerate(options):
        stem = f"{option['number']:02d}-{option['slug']}"
        metadata = json.loads((ROOT / f"{stem}.metadata.json").read_text())
        source = ROOT / f"{stem}.webp"
        assert source.is_file(), f"Missing preview: {source}"
        svg = ROOT / f"{stem}-2.svg"
        assert svg.is_file(), f"Missing vector: {svg}"
        with Image.open(source) as original:
            image = original.convert("RGB")
        difference = ImageChops.difference(image, Image.new("RGB", image.size, "white"))
        mask = difference.convert("L").point(lambda value: 255 if value > 24 else 0)
        bounds = mask.getbbox()
        assert bounds, f"Blank image: {source}"
        # Crop white outer canvas only. Preserve all generated artwork and proportions.
        image = image.crop(bounds)
        image.thumbnail((790, 490), Image.Resampling.LANCZOS)
        x = margin + (index % 2) * (card_width + gap)
        y = 150 + (index // 2) * (card_height + gap)
        draw.rounded_rectangle((x, y, x + card_width, y + card_height), radius=16, fill="white")
        draw.text((x + 26, y + 20), f"{option['number']:02d}  {option['name']}", font=label_font, fill="#172636")
        sheet.paste(image, (x + (card_width - image.width) // 2, y + 90 + (490 - image.height) // 2))
        gallery.extend([f"## {option['number']:02d}. {option['name']}", "", f"![{option['name']}]({stem}.webp)", "", f"[SVG original]({svg.name}) | [Full-size preview]({source.name}) | [Generated media]({metadata['urls'][0]})", ""])
    sheet.save(ROOT / "comparison.png")
    (ROOT / "README.md").write_text("\n".join(gallery))
    print("Built comparison.png and README.md from all ten verified previews and SVG originals.")


if __name__ == "__main__":
    build()
