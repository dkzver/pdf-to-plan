"""Генератор тестового набора: разные конвенции чертежей и виды сканов.

Кейсы:
  rects           — стены залитыми прямоугольниками, без слоёв (базовый)
  double_lines    — стены двумя тонкими линиями, без заливки
  furniture       — те же стены + мебель, штриховка, размерные цепочки
  colored         — стены светло-голубой заливкой (не чёрные)
  scan_200        — базовый кейс, отрендеренный в картинку 200 dpi
  scan_rotated    — тот же скан, повёрнутый на 1.5°
  multipage       — титульный лист + план вторым листом
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pymupdf as fitz
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import OUT, OPENINGS, WALLS, _wall_rect

CASES = OUT.parent / "bench" / "cases"


def _page(doc):
    return doc.new_page(width=842, height=595)


def _plan(page, fill=(0, 0, 0), double_lines=False, furniture=False,
          hatch=False, colored=False):
    if double_lines:
        for x1, y1, x2, y2, t in WALLS:
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy) or 1
            nx, ny = -dy / length * t / 2, dx / length * t / 2
            for sx, sy in ((nx, ny), (-nx, -ny)):
                page.draw_line((x1 + sx, y1 + sy), (x2 + sx, y2 + sy), color=(0, 0, 0), width=0.7)
    else:
        for x1, y1, x2, y2, t in WALLS:
            page.draw_rect(_wall_rect(x1, y1, x2, y2, t), color=None, fill=fill)

    if hatch:
        for x1, y1, x2, y2, t in WALLS:
            r = _wall_rect(x1, y1, x2, y2, t)
            step = 3.0
            x = r.x0 - r.height
            while x < r.x1:
                page.draw_line((x, r.y0), (x + r.height, r.y1), color=(0.6, 0.6, 0.6), width=0.3)
                x += step

    if furniture:
        items = [(150, 150, 260, 200), (620, 140, 690, 200), (420, 330, 470, 390),
                 (610, 330, 690, 400), (200, 420, 260, 470)]
        for x0, y0, x1, y1 in items:
            page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=None, fill=(0.55, 0.55, 0.55))

    for kind, x, y, angle, w in OPENINGS:
        half = w / 2
        if kind == "door":
            gap = fitz.Rect(x - 2, y - half, x + 14, y + half)
            page.draw_rect(gap, color=None, fill=(1, 1, 1))
        else:
            box = fitz.Rect(x - half, y - 8, x + half, y + 8) if angle == 0 else \
                  fitz.Rect(x - 8, y - half, x + 8, y + half)
            page.draw_rect(box, color=None, fill=(1, 1, 1))


def _basic(name: str, **kw) -> Path:
    doc = fitz.open()
    page = _page(doc)
    _plan(page, **kw)
    out = CASES / name
    doc.save(out)
    doc.close()
    return out


def _rasterize(src: Path, dst: Path, dpi: int = 200, angle: float = 0.0) -> Path:
    doc = fitz.open(src)
    pix = doc[0].get_pixmap(dpi=dpi)
    tmp = CASES / f"_{dst.stem}.png"
    pix.save(tmp)
    if angle:
        Image.open(tmp).rotate(angle, expand=False, fillcolor="white").save(tmp)
    out = fitz.open()
    page = out.new_page(width=842, height=595)
    page.insert_image(page.rect, filename=str(tmp))
    out.save(dst)
    out.close()
    return dst


def main() -> None:
    CASES.mkdir(parents=True, exist_ok=True)
    base = _basic("rects.pdf")
    _basic("double_lines.pdf", double_lines=True)
    _basic("furniture.pdf", furniture=True, hatch=True)
    _basic("colored.pdf", fill=(0.72, 0.78, 0.86))
    _rasterize(base, CASES / "scan_200.pdf")
    _rasterize(base, CASES / "scan_rotated.pdf", angle=1.5)

    doc = fitz.open()
    t = doc.new_page(width=842, height=595)
    t.insert_text((60, 80), "Титульный лист", fontsize=18, fontname="tiro")
    t.insert_text((60, 120), "Проект дома. Лист 1 из 2", fontsize=11, fontname="tiro")
    p = doc.new_page(width=842, height=595)
    _plan(p)
    doc.save(CASES / "multipage.pdf")
    doc.close()

    for f in sorted(CASES.glob("*.pdf")):
        print(f.name, f.stat().st_size)


if __name__ == "__main__":
    main()
