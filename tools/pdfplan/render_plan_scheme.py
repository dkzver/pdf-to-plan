"""Схема из plan.json: каждая стена — плотный прямоугольник, проёмы — блоки.

Не зависит от того, как нарисован PDF: если стена найдена, она будет залита.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PX = 2.0
INK = (28, 27, 28)
WALL = (150, 156, 164)
BG = (255, 255, 255)
WIN = (176, 208, 234)
LEAF = (226, 222, 217)
TEXT = (70, 68, 70)


def _font(size: float):
    px = max(9, int(size * PX * 0.55))
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _bar(dr, a, b, t, fill, outline=INK, ow=3):
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(dx, dy) or 1
    nx, ny = -dy / ln * t / 2, dx / ln * t / 2
    dr.polygon([(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny),
                (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)],
               fill=fill, outline=outline, width=ow)


def _merge_for_draw(walls, gap=110.0, offset_tol=6.0, angle_tol=3.0):
    """Склеивает стены вдоль одной линии, чтобы окно было внутри стены, а не разрывом."""
    groups = {}
    for w in walls:
        ang = math.degrees(math.atan2(w["b"][1] - w["a"][1], w["b"][0] - w["a"][0])) % 180
        ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        nx, ny = -uy, ux
        off = w["a"][0] * nx + w["a"][1] * ny
        key = (round(ang / angle_tol), round(off / offset_tol))
        t1 = w["a"][0] * ux + w["a"][1] * uy
        t2 = w["b"][0] * ux + w["b"][1] * uy
        groups.setdefault(key, []).append((min(t1, t2), max(t1, t2), off, w["thickness"], ang))

    out = []
    for spans in groups.values():
        spans.sort()
        s, e, off, th, ang = spans[0]
        for s2, e2, off2, th2, ang2 in spans[1:]:
            if s2 - e <= gap:
                e = max(e, e2)
                th = max(th, th2)
            else:
                out.append((s, e, off, th, ang))
                s, e, off, th, ang = s2, e2, off2, th2, ang2
        out.append((s, e, off, th, ang))

    result = []
    for s, e, off, th, ang in out:
        ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        nx, ny = -uy, ux
        result.append({"a": [ux * s + nx * off, uy * s + ny * off],
                       "b": [ux * e + nx * off, uy * e + ny * off],
                       "thickness": th})
    return result


def _axes(plan):
    """Оси по кластерам координат стен: X — вертикальные оси 1..N, Y — горизонтальные А, Б, В…"""
    xs, ys = [], []
    for w in plan["walls"]:
        if abs(w["a"][0] - w["b"][0]) < 3:
            xs.append(w["a"][0])
        if abs(w["a"][1] - w["b"][1]) < 3:
            ys.append(w["a"][1])
    def cluster(vals, tol=12):
        vals = sorted(vals); out = []
        for v in vals:
            if out and v - out[-1][-1] <= tol: out[-1].append(v)
            else: out.append([v])
        return [sum(g)/len(g) for g in out]
    return cluster(xs), cluster(ys)


def _draw_axes(dr, plan, s, W, H):
    """Неизменяемые оси и размерные цепочки между ними (мм)."""
    mm_per_pt = (plan.get("scale") or {}).get("mm_per_pt")
    xs, ys = _axes(plan)
    if not xs and not ys:
        return
    f = _font(9)
    xs_px = [s((x, 0))[0] for x in xs]
    ys_px = [s((0, y))[1] for y in ys]
    top = min(ys_px) - 46 if ys_px else 40
    left = min(xs_px) - 46 if xs_px else 40

    dash = (120, 120, 120)
    for i, x in enumerate(xs_px):
        dr.line([(x, top), (x, max(ys_px) + 20 if ys_px else H - 40)], fill=dash, width=1)
        dr.ellipse([x - 11, top - 24, x + 11, top - 2], outline=INK, width=1, fill=BG)
        dr.text((x - 3, top - 19), str(i + 1), font=f, fill=INK)
    letters = "АБВГДЕЖЗИКЛМНОПРСТУФ"
    for j, y in enumerate(ys_px):
        dr.line([(left - 34, y), (max(xs_px) + 20 if xs_px else W - 40, y)], fill=dash, width=1)
        dr.ellipse([left - 58, y - 11, left - 36, y + 11], outline=INK, width=1, fill=BG)
        dr.text((left - 53, y - 6), letters[j % len(letters)], font=f, fill=INK)

    if not mm_per_pt:
        return
    # размерные цепочки между соседними осями
    for i in range(len(xs_px) - 1):
        a, b = xs_px[i], xs_px[i + 1]
        val = round((xs[i + 1] - xs[i]) * mm_per_pt)
        y = top - 34
        dr.line([(a, y), (b, y)], fill=INK, width=1)
        dr.line([(a, y - 4), (a, y + 4)], fill=INK, width=1)
        dr.line([(b, y - 4), (b, y + 4)], fill=INK, width=1)
        text = str(val)
        w = dr.textlength(text, font=f)
        dr.rectangle([(a + b) / 2 - w / 2 - 2, y - 12, (a + b) / 2 + w / 2 + 2, y - 1], fill=BG)
        dr.text(((a + b) / 2 - w / 2, y - 12), text, font=f, fill=INK)

    # общий габарит по X — второй ярус ниже
    if len(xs_px) >= 2:
        y = top - 58
        a, b = xs_px[0], xs_px[-1]
        val = round((xs[-1] - xs[0]) * mm_per_pt)
        dr.line([(a, y), (b, y)], fill=INK, width=1)
        dr.line([(a, y - 4), (a, y + 4)], fill=INK, width=1)
        dr.line([(b, y - 4), (b, y + 4)], fill=INK, width=1)
        text = str(val)
        w = dr.textlength(text, font=f)
        dr.rectangle([(a + b) / 2 - w / 2 - 2, y - 12, (a + b) / 2 + w / 2 + 2, y - 1], fill=BG)
        dr.text(((a + b) / 2 - w / 2, y - 12), text, font=f, fill=INK)

    # вертикальная цепочка — снаружи, левее кружков
    for j in range(len(ys_px) - 1):
        a, b = ys_px[j], ys_px[j + 1]
        val = round((ys[j + 1] - ys[j]) * mm_per_pt)
        x = left - 76
        dr.line([(x, a), (x, b)], fill=INK, width=1)
        dr.line([(x - 4, a), (x + 4, a)], fill=INK, width=1)
        dr.line([(x - 4, b), (x + 4, b)], fill=INK, width=1)
        text = str(val)
        w = dr.textlength(text, font=f)
        dr.rectangle([x - w - 6, (a + b) / 2 - 7, x - 2, (a + b) / 2 + 7], fill=BG)
        dr.text((x - w - 5, (a + b) / 2 - 6), text, font=f, fill=INK)


def render(plan_path: Path, out: Path, title: str | None = None) -> Path:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    W = int(plan["page_size"]["width"] * PX)
    H = int(plan["page_size"]["height"] * PX)
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)

    def s(p):
        return (p[0] * PX, p[1] * PX)

    # 0. балконы: контур и подпись
    for b in plan.get("balconies", []):
        pts = [s(p) for p in b["points"]]
        if len(pts) >= 3:
            dr.polygon(pts, fill=(232, 238, 245))
            dr.line(pts + [pts[0]], fill=(110, 118, 128), width=3)
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            dr.text((cx - 46, cy - 8), f"Балкон {b.get('area_m2', 0):.1f} м²",
                    font=_font(12), fill=(60, 78, 100))

    # 1. стены: все плотные, склеенные вдоль линии (окно остаётся внутри стены)
    for w in _merge_for_draw(plan["walls"]):
        _bar(dr, s(w["a"]), s(w["b"]), max(3.0, w["thickness"] * PX), WALL)

    # 2. проёмы: вырезаем и рисуем блок
    for o in plan.get("openings", []):
        a, b = s(o["a"]), s(o["b"])
        t = max(6.0, o.get("width", 8) * PX)
        _bar(dr, a, b, t + 4, BG, outline=BG, ow=0)

        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy) or 1
        ux, uy = dx / ln, dy / ln
        px, py = -uy, ux
        kind = o.get("kind")
        span = ln / PX
        if span > 150:
            kind = None  # слишком широкий разрыв — не проём
        elif 50 <= span <= 140:
            kind = kind or "window"
        else:
            kind = "door"

        if kind == "window" and ln / PX <= 150:
            _bar(dr, a, b, t, WIN)
            for off in (-t / 5, t / 5):
                dr.line([(a[0] + px * off, a[1] + py * off),
                         (b[0] + px * off, b[1] + py * off)], fill=INK, width=2)
        elif kind == "door":
            leaf_len = min(ln, 90 * PX)
            width = max(10.0, t * 0.5)
            # полотно идёт перпендикулярно стене, от петли в точке a
            leaf = [(a[0], a[1]),
                    (a[0] + px * leaf_len, a[1] + py * leaf_len),
                    (a[0] + px * (leaf_len + width), a[1] + py * (leaf_len + width)),
                    (a[0] + px * width, a[1] + py * width)]
            dr.polygon(leaf, fill=LEAF, outline=INK, width=2)

    _draw_axes(dr, plan, s, W, H)

    # 3. заголовок и легенда
    f_t, f_l = _font(13), _font(9)
    dr.text((26, 22), f"Схема: {title or plan_path.parent.name}", font=f_t, fill=INK)
    lx, ly = W - 300, H - 96
    dr.rectangle([lx - 14, ly - 14, W - 18, H - 18], fill=BG, outline=(206, 203, 205), width=2)
    _bar(dr, (lx, ly + 6), (lx + 54, ly + 6), 10, WALL, ow=2)
    dr.text((lx + 66, ly - 4), "стена", font=f_l, fill=INK)
    _bar(dr, (lx, ly + 30), (lx + 54, ly + 30), 10, WIN, ow=2)
    dr.text((lx + 66, ly + 20), "окно", font=f_l, fill=INK)
    dr.polygon([(lx, ly + 56), (lx + 54, ly + 56), (lx + 54, ly + 64), (lx, ly + 64)],
               fill=LEAF, outline=INK, width=2)
    dr.text((lx + 66, ly + 44), "дверь", font=f_l, fill=INK)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)

    bbox = img.convert("L").point(lambda v: 255 if v < 250 else 0).getbbox()
    if bbox:
        pad = 60
        img.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                  min(W, bbox[2] + pad), min(H, bbox[3] + pad))).save(
            out.with_name(out.stem + "_crop.png"))
    print(f"plan scheme: {out}")
    return out


if __name__ == "__main__":
    base = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/pdfplan/out/projectfortest")
    render(base / "plan.json", base / "scheme.png",
           title=json.loads((base / "plan.json").read_text(encoding="utf-8")).get("source_name"))
