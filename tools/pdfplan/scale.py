"""Калибровка масштаба по размерным числам чертежа.

Идея: число над размерной линией — реальная длина в мм. Делим его на длину
линии в пунктах PDF, получаем мм/пт. Медиана по совпавшим парам устойчива к
мусору: подписи мебели, высоты потолков, случайные числа.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter

import pymupdf as fitz

NUM_RE = re.compile(r"^(\d{1,2})\s(\d{3})$")


def _h_lines(page: fitz.Page, max_width: float = 0.8,
             min_len: float = 30.0) -> list[tuple[float, float, float, float]]:
    out = []
    for dr in page.get_drawings():
        w = float(dr.get("width") or 0)
        if w > max_width:
            continue
        for it in dr.get("items", []):
            if it[0] != "l":
                continue
            x1, y1, x2, y2 = it[1].x, it[1].y, it[2].x, it[2].y
            if abs(y1 - y2) < 0.6 and abs(x2 - x1) >= min_len:
                out.append((min(x1, x2), max(x1, x2), (y1 + y2) / 2, abs(x2 - x1)))
    return out


def calibrate(page: fitz.Page) -> dict:
    """Возвращает {'mm_per_pt', 'samples', 'support', 'sheet_scale'}."""
    lines = _h_lines(page)
    samples: list[tuple[float, float]] = []  # (мм/пт, длина линии)

    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            txt = "".join(s["text"] for s in line["spans"]).strip().replace("\xa0", " ")
            m = NUM_RE.match(txt)
            if not m:
                continue
            value_mm = int(m.group(1)) * 1000 + int(m.group(2))
            x0, y0, x1, y1 = line["bbox"]
            cx = (x0 + x1) / 2
            best = None
            for h in lines:
                dy = h[2] - y1
                if not (-2 <= dy <= 26):
                    continue
                if not (h[0] - 2 <= cx <= h[1] + 2):
                    continue
                mid = (h[0] + h[1]) / 2
                if abs(cx - mid) > 0.25 * (h[1] - h[0]) + 12:
                    continue  # число должно стоять над своей линией, а не над соседней
                key = (dy, -h[3])
                if best is None or key < best[0]:
                    best = (key, h)
            if best:
                samples.append((value_mm / best[1][3], best[1][3]))

    if not samples:
        return {"mm_per_pt": None, "support": 0, "sheet_scale": None}

    # округляем до 0.05 и берём самую частую группу
    buckets = Counter(round(s[0] * 20) / 20 for s in samples if s[0] > 1)
    best, support = buckets.most_common(1)[0]
    close = [s[0] for s in samples if abs(s[0] - best) <= 0.35]
    mm_per_pt = statistics.median(close)

    # 1 пт = 25.4/72 мм на бумаге; масштаб листа = реальный/бумажный
    paper = 25.4 / 72
    sheet = mm_per_pt / paper
    return {
        "mm_per_pt": round(mm_per_pt, 3),
        "support": len(close),
        "samples": len(samples),
        "sheet_scale": round(sheet),
        "approx": f"1:{round(sheet)}",
    }


def main() -> int:
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else None
    if not p:
        print("usage: python scale.py file.pdf")
        return 2
    doc = fitz.open(p)
    for i, page in enumerate(doc):
        print(i, calibrate(page))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
