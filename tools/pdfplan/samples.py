"""Пять тестовых планировок: разные формы, комнаты, проёмы и размерные цепочки.

Чертежи рисуются в масштабе 1:50 (17.639 мм на пункт), поэтому размерные числа
на листе совпадают с реальной геометрией и калибровка масштаба проверяется на них.
"""
from __future__ import annotations

import math
from pathlib import Path

import pymupdf as fitz

OUT = Path(__file__).resolve().parent / "samples"
MM_PER_PT = 17.639
A3 = (842, 595)


def mm(pt: float) -> int:
    return int(round(pt * MM_PER_PT))


def wall(page, x1, y1, x2, y2, t=8, fill=(0.31, 0.31, 0.31)):
    if abs(y1 - y2) < 1e-6:
        r = fitz.Rect(min(x1, x2), y1 - t / 2, max(x1, x2), y1 + t / 2)
    else:
        r = fitz.Rect(x1 - t / 2, min(y1, y2), x1 + t / 2, max(y1, y2))
    page.draw_rect(r, color=None, fill=fill)


def opening(page, kind, x, y, angle, w, t=8):
    half = w / 2
    if kind == "door":
        page.draw_rect(fitz.Rect(x - t / 2, y - half, x + t / 2, y + half), color=None, fill=(1, 1, 1))
        r, k = w * 0.9, 0.5523 * w * 0.9
        s = page.new_shape()
        s.draw_bezier((x, y - r), (x + k, y - r), (x + r, y - k), (x + r, y))
        s.finish(color=(0, 0, 0), width=0.7, closePath=False)
        s.commit()
    else:
        box = fitz.Rect(x - half, y - t / 2, x + half, y + t / 2) if angle == 0 else \
              fitz.Rect(x - t / 2, y - half, x + t / 2, y + half)
        page.draw_rect(box, color=None, fill=(1, 1, 1))
        for d in (-2.5, 0, 2.5):
            if angle == 0:
                page.draw_line((x - half, y + d), (x + half, y + d), color=(0, 0, 0), width=0.6)
            else:
                page.draw_line((x + d, y - half), (x + d, y + half), color=(0, 0, 0), width=0.6)


def dims(page, xs, y, labels=None):
    """Горизонтальная размерная цепочка с числами в мм."""
    for a, b in zip(xs, xs[1:]):
        page.draw_line((a, y), (b, y), color=(0, 0, 0), width=0.4)
        for x in (a, b):
            page.draw_line((x, y - 3), (x, y + 3), color=(0, 0, 0), width=0.4)
        value = labels.pop(0) if labels else mm(b - a)
        page.insert_text(((a + b) / 2 - 14, y - 4), f"{value // 1000} {value % 1000:03d}",
                         fontsize=6.5, fontname="tiro")


def vdims(page, ys, x):
    for a, b in zip(ys, ys[1:]):
        page.draw_line((x, a), (x, b), color=(0, 0, 0), width=0.4)
        for y in (a, b):
            page.draw_line((x - 3, y), (x + 3, y), color=(0, 0, 0), width=0.4)
        page.insert_text((x - 26, (a + b) / 2), f"{mm(b - a) // 1000} {mm(b - a) % 1000:03d}",
                         fontsize=6.5, fontname="tiro", rotate=90)


def label(page, x, y, name, area):
    page.insert_text((x - 24, y), name, fontsize=8, fontname="tiro")
    page.insert_text((x - 14, y + 11), f"{area:.2f} m2", fontsize=7, fontname="tiro")


def frame(page, title):
    page.draw_rect(fitz.Rect(20, 20, A3[0] - 20, A3[1] - 20), color=(0.6, 0.6, 0.6), width=0.8)
    page.insert_text((40, 40), title, fontsize=11, fontname="tiro")
    page.insert_text((700, 570), "M 1:50", fontsize=9, fontname="tiro")


def area_m2(w_pt: float, h_pt: float) -> float:
    return w_pt * h_pt * (MM_PER_PT / 1000) ** 2


def studio() -> fitz.Document:
    doc = fitz.open(); page = doc.new_page(width=A3[0], height=A3[1])
    frame(page, "Студия 28 м²")
    x0, y0, x1, y1, t = 120, 140, 560, 440, 8
    wall(page, x0, y0, x1, y0, t); wall(page, x0, y1, x1, y1, t)
    wall(page, x0, y0, x0, y1, t); wall(page, x1, y0, x1, y1, t)
    wall(page, 380, y0, 380, 300, t)          # санузел
    wall(page, 380, 300, x1, 300, t)
    opening(page, "door", 380, 360, 90, 55)
    opening(page, "door", 300, y1, 0, 60)      # вход
    opening(page, "window", 200, y0, 0, 90)
    opening(page, "window", x1, 380, 90, 80)
    label(page, 240, 270, "Комната", area_m2(260, 300))
    label(page, 470, 370, "Санузел", area_m2(180, 140))
    dims(page, [x0, 380, x1], 118)
    vdims(page, [y0, y1], 96)
    doc.save(OUT / "01-studio.pdf"); return doc


def two_rooms() -> fitz.Document:
    doc = fitz.open(); page = doc.new_page(width=A3[0], height=A3[1])
    frame(page, "2-комнатная квартира 54 м²")
    x0, y0, x1, y1 = 110, 150, 700, 470
    t = 8
    wall(page, x0, y0, x1, y0, t); wall(page, x0, y1, x1, y1, t)
    wall(page, x0, y0, x0, y1, t); wall(page, x1, y0, x1, y1, t)
    wall(page, 400, y0, 400, 330, t); wall(page, 400, 330, x1, 330, t)
    wall(page, 250, 330, 400, 330, t); wall(page, 250, 330, 250, y1, t)
    opening(page, "door", 400, 400, 90, 60)
    opening(page, "door", 250, 420, 90, 55)
    opening(page, "door", 480, y1, 0, 65)
    opening(page, "window", 180, y0, 0, 100)
    opening(page, "window", 560, y0, 0, 110)
    opening(page, "window", x1, 400, 90, 90)
    opening(page, "window", x0, 380, 90, 80)
    label(page, 250, 250, "Гостиная", area_m2(280, 320))
    label(page, 540, 240, "Спальня", area_m2(300, 170))
    label(page, 320, 400, "Кухня", area_m2(140, 140))
    label(page, 160, 400, "Прихожая", area_m2(130, 140))
    dims(page, [x0, 400, x1], 128)
    vdims(page, [y0, y1], 86)
    doc.save(OUT / "02-two-rooms.pdf"); return doc


def l_shaped() -> fitz.Document:
    doc = fitz.open(); page = doc.new_page(width=A3[0], height=A3[1])
    frame(page, "L-образная квартира")
    t = 8
    # внешний L: 520x300 с вырезом 200x120
    pts = [(120, 140), (640, 140), (640, 320), (440, 320), (440, 440), (120, 440)]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        wall(page, a[0], a[1], b[0], b[1], t)
    wall(page, 320, 140, 320, 300, t)
    wall(page, 320, 300, 440, 300, t)
    opening(page, "door", 320, 360, 90, 55)
    opening(page, "window", 200, 440, 0, 90)
    opening(page, "window", 560, 140, 0, 100)
    label(page, 220, 250, "Кухня-гостиная", area_m2(190, 160))
    label(page, 380, 230, "Спальня", area_m2(120, 160))
    label(page, 180, 390, "Холл", area_m2(190, 110))
    dims(page, [120, 320, 640], 118)
    vdims(page, [140, 320, 440], 96)
    doc.save(OUT / "03-l-shape.pdf"); return doc


def house_terrace() -> fitz.Document:
    doc = fitz.open(); page = doc.new_page(width=A3[0], height=A3[1])
    frame(page, "Дом с террасой")
    t = 8
    x0, y0, x1, y1 = 130, 180, 600, 470
    wall(page, x0, y0, x1, y0, t); wall(page, x0, y1, x1, y1, t)
    wall(page, x0, y0, x0, y1, t); wall(page, x1, y0, x1, y1, t)
    wall(page, 380, y0, 380, 340, t); wall(page, 380, 340, x1, 340, t)
    # терраса — тонкие линии
    for a, b in zip([(600, 180), (720, 180), (720, 380), (600, 380)],
                    [(720, 180), (720, 380), (600, 380), (600, 180)]):
        page.draw_line(a, b, color=(0.35, 0.35, 0.35), width=1.2)
    opening(page, "door", 380, 410, 90, 65)
    opening(page, "door", x0, 380, 90, 60)
    opening(page, "window", 240, y0, 0, 100)
    opening(page, "window", 500, y0, 0, 90)
    opening(page, "window", x1, 250, 90, 80)
    label(page, 250, 280, "Гостиная", area_m2(230, 280))
    label(page, 490, 260, "Спальня", area_m2(200, 150))
    label(page, 660, 290, "Терраса", area_m2(120, 200))
    dims(page, [x0, 380, x1], 158)
    vdims(page, [y0, y1], 108)
    doc.save(OUT / "04-house-terrace.pdf"); return doc


def office() -> fitz.Document:
    doc = fitz.open(); page = doc.new_page(width=A3[0], height=A3[1])
    frame(page, "Офис: коридор и три кабинета")
    t = 8
    x0, y0, x1, y1 = 110, 160, 720, 460
    wall(page, x0, y0, x1, y0, t); wall(page, x0, y1, x1, y1, t)
    wall(page, x0, y0, x0, y1, t); wall(page, x1, y0, x1, y1, t)
    # коридор по центру
    wall(page, 200, 260, 640, 260, t); wall(page, 200, 360, 640, 360, t)
    wall(page, 200, 260, 200, 360, t); wall(page, 640, 260, 640, 360, t)
    for x in (330, 470):
        wall(page, x, y0, x, 260, t); wall(page, x, 360, x, y1, t)
    for x in (330, 470, 600):
        opening(page, "door", x, 310, 90, 55)
    opening(page, "door", 200, 310, 90, 60)
    opening(page, "window", 260, y0, 0, 90)
    opening(page, "window", 540, y1, 0, 100)
    label(page, 230, 210, "Кабинет 1", area_m2(120, 100))
    label(page, 400, 210, "Кабинет 2", area_m2(140, 100))
    label(page, 540, 210, "Кабинет 3", area_m2(170, 100))
    label(page, 390, 320, "Коридор", area_m2(440, 100))
    label(page, 260, 420, "Зал", area_m2(300, 100))
    label(page, 560, 420, "Архив", area_m2(180, 100))
    dims(page, [x0, 330, 470, x1], 138)
    vdims(page, [y0, 260, 360, y1], 88)
    doc.save(OUT / "05-office.pdf"); return doc


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for build in (studio, two_rooms, l_shaped, house_terrace, office):
        doc = build()
        doc.close()
    for f in sorted(OUT.glob("*.pdf")):
        print(f.name, f.stat().st_size)


if __name__ == "__main__":
    main()
