"""Синтетические чертежи для проверки конвейера: векторный PDF и его растровая версия.

Фикстура повторяет типичный экспорт из CAD:
- несущие и внутренние стены — залитые прямоугольники;
- дверные проёмы с дугой открывания;
- окна — три тонкие линии в проёме;
- размерные линии с числами и подписи комнат;
- рамка листа и штамп — как шум.

Правда (ground truth) пишется в fixtures/truth.json: стены заданы осевыми
линиями и толщиной в пунктах PDF (1 pt = 1/72 дюйма).
"""
from __future__ import annotations

import json
from pathlib import Path

import pymupdf as fitz

OUT = Path(__file__).resolve().parent / "fixtures"

# (x1, y1, x2, y2, толщина) в пунктах, лист A4 landscape 842x595
WALLS = [
    (100, 100, 700, 100, 12),   # север
    (100, 480, 700, 480, 12),   # юг
    (100, 100, 100, 480, 12),   # запад
    (700, 100, 700, 480, 12),   # восток
    (380, 100, 380, 300, 8),    # внутренняя вертикаль
    (380, 300, 700, 300, 8),    # внутренняя горизонталь
    (560, 300, 560, 480, 8),    # короткая перегородка
]

# проёмы: (тип, x, y, угол_градусы, ширина)
OPENINGS = [
    ("door", 380, 430, 90, 70),
    ("window", 240, 100, 0, 90),
    ("window", 700, 200, 90, 80),
]


def _wall_rect(x1, y1, x2, y2, t):
    """Прямоугольник заливки вокруг осевой линии."""
    half = t / 2
    if abs(y1 - y2) < 1e-6:  # горизонтальная
        return fitz.Rect(min(x1, x2), y1 - half, max(x1, x2), y1 + half)
    return fitz.Rect(x1 - half, min(y1, y2), x1 + half, max(y1, y2))


def build_vector_pdf(path: Path, walls=WALLS, openings=OPENINGS) -> None:
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)

    shape = page.new_shape()
    # рамка листа и штамп — шум, который детектор должен игнорировать
    shape.draw_rect(fitz.Rect(20, 20, 822, 575))
    shape.finish(color=(0.6, 0.6, 0.6), width=0.8)
    shape.commit()

    # стены: заливка чёрным, без обводки
    for x1, y1, x2, y2, t in walls:
        page.draw_rect(_wall_rect(x1, y1, x2, y2, t), color=None, fill=(0, 0, 0))

    # проёмы: белая заливка поверх стены + тонкие линии
    for kind, x, y, angle, w in openings:
        half = w / 2
        if kind == "door":
            gap = fitz.Rect(x - 2, y - half, x + 14, y + half)
            page.draw_rect(gap, color=None, fill=(1, 1, 1))
            # четверть окружности радиусом w: дуга открывания двери
            r, k = w, 0.5523 * w
            shape = page.new_shape()
            shape.draw_bezier((x, y - r), (x + k, y - r), (x + r, y - k), (x + r, y))
            shape.finish(color=(0, 0, 0), width=0.8, closePath=False)
            shape.commit()
            page.draw_line((x, y - half), (x, y + half), color=(0, 0, 0), width=0.8)
        else:
            # проём окна: белая заливка поверх стены, затем тонкие линии
            if angle == 0:
                page.draw_rect(fitz.Rect(x - half, y - 8, x + half, y + 8),
                               color=None, fill=(1, 1, 1))
                for dy in (-4, 0, 4):
                    page.draw_line((x - half, y + dy), (x + half, y + dy),
                                   color=(0, 0, 0), width=0.8)
            else:
                page.draw_rect(fitz.Rect(x - 8, y - half, x + 8, y + half),
                               color=None, fill=(1, 1, 1))
                for dx in (-4, 0, 4):
                    page.draw_line((x + dx, y - half), (x + dx, y + half),
                                   color=(0, 0, 0), width=0.8)

    # размерные линии и числа
    for x1, x2, y, label in ((100, 380, 78, "2800"), (380, 700, 78, "3200")):
        page.draw_line((x1, y), (x2, y), color=(0, 0, 0), width=0.5)
        page.draw_line((x1, y - 4), (x1, y + 4), color=(0, 0, 0), width=0.5)
        page.draw_line((x2, y - 4), (x2, y + 4), color=(0, 0, 0), width=0.5)
        page.insert_text((x1 + (x2 - x1) / 2 - 10, y - 4), label,
                         fontsize=7, fontname="tiro")

    for x, y, label in ((240, 200, "Кухня"), (540, 200, "Комната"),
                        (470, 400, "Спальня"), (850 - 90, 60, "План 1 этажа  М 1:100")):
        page.insert_text((x, y), label, fontsize=10, fontname="tiro")

    doc.save(path)
    doc.close()


def build_raster_pdf(src: Path, dst: Path, dpi: int = 200) -> None:
    """Рендер векторного листа в картинку и вставка её в новый PDF."""
    src_doc = fitz.open(src)
    pix = src_doc[0].get_pixmap(dpi=dpi)
    img = OUT / "page_raster.png"
    pix.save(img)
    src_doc.close()

    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_image(fitz.Rect(0, 0, 842, 595), filename=str(img))
    doc.save(dst)
    doc.close()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    vector = OUT / "plan_vector.pdf"
    raster = OUT / "plan_raster.pdf"
    build_vector_pdf(vector)
    build_raster_pdf(vector, raster)
    truth = {
        "page": 842,
        "units": "pt",
        "walls": [{"a": [x1, y1], "b": [x2, y2], "thickness": t} for x1, y1, x2, y2, t in WALLS],
        "openings": [{"type": k, "x": x, "y": y, "angle": a, "width": w}
                     for k, x, y, a, w in OPENINGS],
    }
    (OUT / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    print("fixtures:", vector.name, raster.name)


if __name__ == "__main__":
    main()
