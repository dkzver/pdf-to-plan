"""Чистая схема из слоя стен PDF: заливки, обводки, дуги дверей, линии окон.

Берём только слои «стены»/«перегородки» и перерисовываем их на белом листе:
заливки стен — светло-серые с чёрной обводкой, проёмы — белые, тонкие линии
(створки, дуги, окна) — чёрные. Никаких размерных цепочек, мебели и таблиц.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline as P  # noqa: E402

PX = 3.0
INK = (28, 27, 28)
WALL = (150, 156, 164)
BG = (255, 255, 255)
WIN = (188, 214, 236)
LEAF = (222, 219, 215)
MUTED = (95, 92, 94)


def _kind(drs, o) -> str:
    """Дверь — если в проёме есть дуга, окно — если 2+ тонкие линии, иначе по ширине."""
    a, b = o["a"], o["b"]
    x0, x1 = min(a[0], b[0]) - 2, max(a[0], b[0]) + 2
    y0, y1 = min(a[1], b[1]) - 2, max(a[1], b[1]) + 2
    lines = curves = 0
    for d in drs:
        for it in d.get("items", []):
            if it[0] == "c":
                xs = [p.x for p in it[1:5]]
                ys = [p.y for p in it[1:5]]
                if not (max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1):
                    curves += 1
            elif it[0] == "l":
                if all(x0 <= p.x <= x1 and y0 <= p.y <= y1 for p in (it[1], it[2])):
                    lines += 1
    if curves:
        return "door"
    if lines >= 2:
        return "window"
    return "window" if math.dist(a, b) > 60 else "door"


def _rect_white(dr, a, b, t, fill=None, outline=None, width=0):
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(dx, dy) or 1
    nx, ny = -dy / ln * t / 2, dx / ln * t / 2
    dr.polygon([(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny),
                (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)],
               fill=fill, outline=outline, width=width)


def _opening(dr, a, b, t, kind):
    """Проём целиком непрозрачный: окно — голубой блок, дверь — плотное полотно."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(dx, dy) or 1
    ux, uy = dx / ln, dy / ln
    px, py = -uy, ux

    _rect_white(dr, a, b, 3, fill=BG, outline=BG)

    if kind == "window":
        if ln / PX > 150:
            return  # длинный разрыв — это не окно, оставляем проём открытым
        _rect_white(dr, a, b, t, fill=WIN, outline=INK, width=2)
        for off in (-t / 5, t / 5):
            dr.line([(a[0] + px * off, a[1] + py * off),
                     (b[0] + px * off, b[1] + py * off)], fill=INK, width=1)
    else:
        width = max(4.0, t * 0.5)
        leaf_len = min(ln, 90 * PX)
        leaf = [(a[0] + px * width / 2, a[1] + py * width / 2),
                (a[0] + px * width / 2 + ux * leaf_len, a[1] + py * width / 2 + uy * leaf_len),
                (a[0] + ux * leaf_len - px * width / 2, a[1] + uy * leaf_len - py * width / 2),
                (a[0] - px * width / 2, a[1] - py * width / 2)]
        dr.polygon(leaf, fill=LEAF, outline=INK, width=2)



def _font(size: float):
    px = max(9, int(size * PX * 0.55))
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _pts(d: dict) -> list[tuple[float, float]]:
    out = []
    for it in d.get("items", []):
        k = it[0]
        if k == "l":
            out += [(it[1].x, it[1].y), (it[2].x, it[2].y)]
        elif k == "re":
            r = it[1]
            out += [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
        elif k == "qu":
            q = it[1]
            out += [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)]
        elif k == "c":
            p = [it[1], it[2], it[3], it[4]]
            for i in range(16):
                t = i / 15
                mt = 1 - t
                x = (mt ** 3 * p[0].x + 3 * mt ** 2 * t * p[1].x +
                     3 * mt * t ** 2 * p[2].x + t ** 3 * p[3].x)
                y = (mt ** 3 * p[0].y + 3 * mt ** 2 * t * p[1].y +
                     3 * mt * t ** 2 * p[2].y + t ** 3 * p[3].y)
                out.append((x, y))
    return out


def render_layer_scheme(pdf_path: str | Path, out: Path, page_no: int = 0,
                        title: str | None = None) -> Path:
    doc = fitz.open(pdf_path)
    page = doc[page_no]
    W = int(page.rect.width * PX)
    H = int(page.rect.height * PX)
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)

    drs = page.get_drawings(extended=True)
    names = {(d.get("layer") or "") for d in drs}
    wall_names = {n for n in names if "стен" in n.lower() or "перегород" in n.lower()}
    if not wall_names:
        raise SystemExit("В PDF нет слоя стен — нужен растровый режим")

    def s(p):
        return (p[0] * PX, p[1] * PX)

    bx0 = by0 = 1e9
    bx1 = by1 = -1e9

    # подложка: все найденные стены сплошной заливкой, чтобы не было белых участков
    found_walls, openings = P.layer_walls(page)
    for w in found_walls:
        a, b = s(w.a), s(w.b)
        t = max(2.0, w.thickness * PX)
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy) or 1
        nx, ny = -dy / ln * t / 2, dx / ln * t / 2
        dr.polygon([(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny),
                    (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)], fill=WALL)

    for d in drs:
        if (d.get("layer") or "") not in wall_names:
            continue
        fill = d.get("fill")
        pts = _pts(d)
        if not pts:
            continue
        closed = d.get("closePath") or (
            len(pts) >= 4 and abs(pts[0][0] - pts[-1][0]) < 0.5 and abs(pts[0][1] - pts[-1][1]) < 0.5)
        if fill and d.get("type") in ("f", "fs"):
            pts_px = [s(p) for p in pts]
            dr.polygon(pts_px, fill=WALL)
            for x, y in pts_px:
                bx0, by0 = min(bx0, x), min(by0, y)
                bx1, by1 = max(bx1, x), max(by1, y)
        elif closed and d.get("type") == "s" and len(pts) >= 4:
            pts_px = [s(p) for p in pts]
            dr.polygon(pts_px, fill=WALL)
            for x, y in pts_px:
                bx0, by0 = min(bx0, x), min(by0, y)
                bx1, by1 = max(bx1, x), max(by1, y)

    for d in drs:
        if (d.get("layer") or "") not in wall_names:
            continue
        pts = _pts(d)
        if not pts:
            continue
        fill = d.get("fill")
        stroke = d.get("color")
        width = max(2, int(round(float(d.get("width") or 0) * PX)))
        if fill and d.get("type") in ("f", "fs"):
            dr.line([s(p) for p in pts] + [s(pts[0])], fill=INK,
                    width=max(3, int(round(PX * 0.9))))
        elif stroke and d.get("type") in ("s", "fs"):
            dr.line([s(p) for p in pts], fill=INK, width=width)

    # проёмы: плотные блоки — окна голубые, двери с непрозрачным полотном
    for o in openings:
        a, b = s(o["a"]), s(o["b"])
        t = max(6.0, o.get("width", 8) * PX)
        _opening(dr, a, b, t, _kind(drs, o))

    f_title, f_leg = _font(14), _font(9)
    doc_title = title or Path(pdf_path).name
    dr.text((24, 20), f"Схема: {doc_title}", font=f_title, fill=INK)
    dr.text((24, 52), "несущие стены и перегородки — по слою чертежа; "
                      "двери — дуги, окна — тонкие линии", font=f_leg, fill=MUTED)

    lx, ly = W - 300, H - 110
    dr.rectangle([lx - 12, ly - 12, W - 16, H - 16], fill=BG, outline=(205, 202, 204), width=2)
    dr.rectangle([lx, ly, lx + 56, ly + 12], fill=WALL, outline=INK, width=2)
    dr.text((lx + 68, ly - 3), "стена / перегородка", font=f_leg, fill=INK)
    dr.line([(lx, ly + 44), (lx + 36, ly + 44)], fill=INK, width=1)
    dr.arc([lx + 4, ly + 14, lx + 64, ly + 74], 180, 270, fill=INK, width=1)
    dr.text((lx + 68, ly + 38), "дверь", font=f_leg, fill=INK)
    for off in (-5, 0, 5):
        dr.line([(lx, ly + 66 + off), (lx + 56, ly + 66 + off)], fill=INK, width=1)
    dr.text((lx + 68, ly + 62), "окно", font=f_leg, fill=INK)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)

    # обрезанный вариант для показа: без пустых полей листа
    gray = img.convert("L")
    if bx1 > bx0 and by1 > by0:
        pad = 90
        crop = img.crop((max(0, int(bx0) - pad), max(0, int(by0) - pad),
                         min(W, int(bx1) + pad), min(H, int(by1) + pad)))
        crop.save(out.with_name(out.stem + "_crop.png"))

    print(f"scheme: {out} ({W}x{H})")
    return out


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else \
        ".zwork/attachments/7682913d-fb35-41af-a128-690be3f9dde1/projectfortest.pdf"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else \
        Path("tools/pdfplan/out/projectfortest/scheme_layer.png")
    render_layer_scheme(src, dst)
