#!/usr/bin/env python3
"""Draws the fictional discharge medication list of the family-timeline demo (episode_hip_fracture.json, update u08):
- discharge_medication_list.jpg: as a phone photo (paper slightly turned, on a table, uneven light), the demo photo;
- discharge_medication_list_scan.png: the same paper, flat and straight, to tell a reading error caused by the photo
  from one caused by the model.
TEXT is exactly what is printed on it, line by line: the recorded reading of the demo and the expected reading for
scripts/try_photo_read.py. Fictional; not a real prescription. Needs Pillow (installed with streamlit):
  python make_sample_photos.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
TEXT = [
    "DISCHARGE MEDICATIONS",
    "Patient: Elena Novak (fictional)   Ward 5B   24/10/2026",
    "Paracetamol 1 g four times a day as needed for pain.",
    "Enoxaparin 40 mg injection once a day for 28 days (to prevent blood clots).",
    "Lansoprazole 15 mg once a day.",
    "Continue: Amlodipine 5 mg once a day.",
    "STOP taking Ibuprofen.",
    "FICTIONAL DEMO DOCUMENT - NOT A REAL PRESCRIPTION",
]
FONTS = Path("/usr/share/fonts/truetype/dejavu")


def font(name: str, size: int):
    try:
        return ImageFont.truetype(str(FONTS / name), size)
    except OSError:
        return ImageFont.load_default(size)


def paper() -> Image.Image:
    w, h = 1460, 860
    img = Image.new("RGB", (w, h), (250, 249, 244))
    d = ImageDraw.Draw(img)
    d.text((70, 60), TEXT[0], font=font("DejaVuSans-Bold.ttf", 46), fill=(25, 25, 30))
    d.text((70, 130), TEXT[1], font=font("DejaVuSans.ttf", 28), fill=(70, 70, 75))
    d.line((70, 185, w - 70, 185), fill=(120, 120, 125), width=3)
    y = 225
    for line in TEXT[2:7]:
        bold = line.startswith(("STOP", "Continue"))
        d.text((70, y), line, font=font("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", 31), fill=(20, 20, 25))
        y += 82
    d.line((70, y + 10, w - 70, y + 10), fill=(160, 160, 165), width=2)
    d.text((70, y + 40), TEXT[7], font=font("DejaVuSans-Bold.ttf", 26), fill=(150, 40, 40))
    return img


def phone_photo(sheet: Image.Image) -> Image.Image:
    bg = Image.new("RGB", (1840, 1240), (118, 96, 74))   # a wooden table
    d = ImageDraw.Draw(bg)
    for x in range(0, 1840, 37):
        d.line((x, 0, x + 120, 1240), fill=(110 + x % 17, 89 + x % 11, 68), width=2)
    shadow = Image.new("RGBA", sheet.size, (0, 0, 0, 110)).rotate(3.2, expand=True, fillcolor=(0, 0, 0, 0))
    turned = sheet.convert("RGBA").rotate(3.2, expand=True, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))
    bg.paste(shadow.filter(ImageFilter.GaussianBlur(12)), (200, 190), shadow)
    bg.paste(turned, (170, 160), turned)
    light = Image.linear_gradient("L").rotate(35, expand=False).resize(bg.size)   # brighter at one corner
    return Image.composite(bg, Image.eval(bg, lambda v: int(v * 0.82)), light).filter(ImageFilter.GaussianBlur(0.6))


if __name__ == "__main__":
    sheet = paper()
    sheet.save(HERE / "discharge_medication_list_scan.png", optimize=True)
    phone_photo(sheet).save(HERE / "discharge_medication_list.jpg", quality=82, optimize=True)
    print("\n".join(TEXT))
