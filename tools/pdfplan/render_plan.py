"""Чистая схема по разобранному плану: стены с обводкой, перегородки, проёмы, площади.

Рисуется поверх белого листа, без подложки PDF: несущие стены — тёмная заливка и
толстая обводка, перегородки — светлая заливка и тонкая обводка, двери — дуга и
полотно, окна — три линии в проёме, комнаты — площадь в м².
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PX_PER_PT = 3.0
INK = (28, 27, 28)
WALL_LOAD = (196, 202, 210)
WALL_PART = (232, 229, 226)
BG = (255, 255, 255)
ROOM_TEXT = (90, 88, 90)


def _font(size_pt: float) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    px = max(9, int(size_pt * PX_PER_PT * 0.55))
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _rect(draw, a, b, t, fill, outline, ow):
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(dx, dy) or 1
    nx, ny = -dy / ln * t / 2, dx / ln * t / 2
    pts = [(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny),
           (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)]
    draw.polygon(pts, fill=fill, outline=outline, width=ow)


def _door(draw, a, b, t, side=1):
    ln = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
    ux, uy = (b[0] - a[0]) / ln, (b[1] - a[1]) / ln
    nx, ny = -uy * side, ux * side
    r = ln
    pts = []
    for i in range(25):
        th = math.radians(90 * i / 24)
        px = a[0] + (ux * math.cos(th) + nx * math.sin(th)) * r
        py = a[1] + (uy * math.cos(th) + ny * math.sin(th)) * r
        pts.append((px, py))
    draw.line(pts, fill=INK, width=max(1, int(PX_PER_PT * 0.9)))
    draw.line([a, pts[-1]], fill=INK, width=max(1, int(PX_PER_PT * 0.9)))


def _window(draw, a, b, t):
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(dx, dy) or 1
    nx, ny = -dy / ln, dx / ln
    for off in (-t / 3, 0, t / 3):
        draw.line([(a[0] + nx * off, a[1] + ny * off), (b[0] + nx * off, b[1] + ny * off)],
                  fill=INK, width=max(1, int(PX_PER_PT * 0.7)))


def main() -> int:
    base = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/pdfplan/out/projectfortest")
    plan = json.loads((base / "plan.json").read_text(encoding="utf-8"))
    rooms_path = base / "rooms.json"
    rooms = json.loads(rooms_path.read_text(encoding="utf-8")).get("rooms", []) if rooms_path.exists() else []

    W = int(plan["page_size"]["width"] * PX_PER_PT)
    H = int(plan["page_size"]["height"] * PX_PER_PT)
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)

    walls = plan["walls"]
    thickness = sorted(w["thickness"] for w in walls)
    median = thickness[len(thickness) // 2] if thickness else 8
    load_threshold = median * 1.12

    def px(p):
        return (p[0] * PX_PER_PT, p[1] * PX_PER_PT)

    # стены
    for w in walls:
        a, b = px(w["a"]), px(w["b"])
        t = w["thickness"] * PX_PER_PT
        load = w["thickness"] >= load_threshold
        _rect(dr, a, b, t, WALL_LOAD if load else WALL_PART, INK,
              3 if load else 2)

    # проёмы: белая подчистка + символ
    for o in plan.get("openings", []):
        a, b = px(o["a"]), px(o["b"])
        t = o.get("width", 8) * PX_PER_PT
        _rect(dr, a, b, t, BG, BG, 1)
        kind = o.get("kind")
        if kind == "door":
            _door(dr, a, b, t)
        else:
            _window(dr, a, b, t)

    # комнаты
    f_area = _font(11)
    for r in rooms:
        cx, cy = px(r["center_pt"])
        text = f"{r['area_m2']:.1f} м²"
        box = dr.textbbox((0, 0), text, font=f_area)
        dr.rectangle([cx - 26, cy - 12, cx + 26, cy + 12], fill=(255, 255, 255, 230))
        dr.text((cx - (box[2] - box[0]) / 2, cy - (box[3] - box[1]) / 2 - 2),
                text, font=f_area, fill=ROOM_TEXT)

    # заголовок и легенда
    f_title = _font(14)
    f_leg = _font(9)
    name = plan.get("source_name") or Path(plan.get("file", "")).name
    dr.text((24, 20), f"Схема: {name}", font=f_title, fill=INK)
    dr.text((24, 52), "несущие стены — тёмные, перегородки — светлые, "
                      "дверь — дуга, окно — три линии", font=f_leg, fill=ROOM_TEXT)

    lx, ly = W - 320, H - 120
    dr.rectangle([lx - 12, ly - 12, W - 16, H - 16], fill=BG, outline=(200, 197, 199), width=2)
    _rect(dr, (lx, ly + 8), (lx + 60, ly + 8), 12, WALL_LOAD, INK, 3)
    dr.text((lx + 72, ly - 2), "несущая стена", font=f_leg, fill=INK)
    _rect(dr, (lx, ly + 34), (lx + 60, ly + 34), 7, WALL_PART, INK, 2)
    dr.text((lx + 72, ly + 26), "перегородка", font=f_leg, fill=INK)
    dr.line([(lx, ly + 62), (lx + 40, ly + 62)], fill=INK, width=2)
    dr.line([(lx + 40, ly + 62), (lx + 40, ly + 96)], fill=INK, width=2)
    dr.text((lx + 72, ly + 52), "дверь", font=f_leg, fill=INK)
    for off in (-4, 0, 4):
        dr.line([(lx, ly + 82 + off), (lx + 60, ly + 82 + off)], fill=INK, width=2)
    dr.text((lx + 72, ly + 76), "окно", font=f_leg, fill=INK)

    out = base / "scheme.png"
    img.save(out)
    print(f"scheme: {out} ({W}x{H})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
