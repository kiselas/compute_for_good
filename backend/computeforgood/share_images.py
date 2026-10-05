"""Bounded PNG rendering from public outcome text, never from uploaded images."""
from functools import lru_cache
import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
from threading import BoundedSemaphore
from fastapi import HTTPException
from PIL import Image, ImageDraw, ImageFont


@lru_cache(maxsize=12)
def font(size):
    for path in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "C:/Windows/Fonts/msyh.ttc",
                 "C:/Windows/Fonts/msjh.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"):
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size)
    raise RuntimeError("Card rendering requires the bundled Unicode font")


def lines(draw, text, size, width, max_lines):
    text = " ".join(str(text).split())[:500]
    result, current = [], ""
    for character in text:
        if current and draw.textlength(current + character, font=font(size)) > width:
            result.append(current.rstrip())
            current = character.lstrip()
        else:
            current += character
    if current:
        result.append(current)
    if len(result) > max_lines:
        result = result[:max_lines]
        while draw.textlength(result[-1] + "…", font=font(size)) > width:
            result[-1] = result[-1][:-1]
        result[-1] += "…"
    return result


def _render(value, copy, shape, lang):
    width, height = (1200, 630) if shape == "wide" else (1080, 1350)
    portrait = shape == "portrait"
    im = Image.new("RGB", (width, height), "#f2f8f4")
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((32, 32, width - 32, height - 32), radius=26, fill="#ffffff", outline="#d4e7dc", width=2)
    d.rounded_rectangle((60, 60, 120, 120), radius=14, fill="#13734f")
    d.text((73, 65), "+", font=font(40), fill="#ffffff")
    d.text((138, 65), "ComputeForGood", font=font(34), fill="#122e25")
    y = 150
    headline = copy["demo"] if value["is_demo"] else copy["accepted"]
    for line in lines(d, headline, 38, width - 120, 2):
        d.text((60, y), line, font=font(38), fill="#13734f")
        y += 55
    y += 10
    for line in lines(d, value["title"], 42, width - 120, 3 if not portrait else 5):
        d.text((60, y), line, font=font(42), fill="#122e25")
        y += 60
    y = max(y + 20, 415 if not portrait else 680)
    identity = "@" + value["username"] + "  /  " + value["project"]["name"]
    for line in lines(d, identity, 26, width - 120, 2):
        d.text((60, y), line, font=font(26), fill="#425c50")
        y += 40
    if portrait:
        d.text((60, y + 30), copy["review"], font=font(24), fill="#425c50")
        names = ", ".join("@" + n for n in value["reviewers"]) or "—"
        for line in lines(d, names, 24, width - 120, 3):
            y += 38
            d.text((60, y + 40), line, font=font(24), fill="#122e25")
    d.line((60, height - 130, width - 60, height - 130), fill="#d4e7dc", width=2)
    d.text((60, height - 110), value["recorded_at"].date().isoformat() + " UTC  ·  " + value["head_sha"][:12], font=font(22), fill="#425c50")
    d.text((60, height - 76), "compute-for-good.tech", font=font(22), fill="#13734f")
    result = BytesIO()
    im.save(result, format="PNG", compress_level=3)
    return result.getvalue()


_render_slots = BoundedSemaphore(2)


@lru_cache(maxsize=32)
def _cached_card(serialized, copy_items, shape, lang):
    value = json.loads(serialized)
    value["recorded_at"] = datetime.fromisoformat(value["recorded_at"])
    return _render(value, dict(copy_items), shape, lang)


def render_card(value, copy, shape, lang):
    # Database visibility is checked before using this bounded content cache.
    if not _render_slots.acquire(blocking=False):
        raise HTTPException(503, "Card renderer busy; retry shortly", headers={"Retry-After": "2", "Cache-Control": "no-store"})
    try:
        return _cached_card(json.dumps(value, default=str, sort_keys=True), tuple(sorted(copy.items())), shape, lang)
    finally:
        _render_slots.release()
