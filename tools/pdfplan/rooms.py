"""Комнаты из схемы стен: замыкаем проёмы, строим полигоны, считаем площади.

Осевые линии стен не образуют замкнутых контуров из-за дверей и окон. Скрипт
дотягивает концы вдоль направления стены до ближайшей другой стены и только
потом режет плоскость наface-полигоны (shapely.polygonize). Площадь считается
по внутреннему контуру: полигон сжимается на полтолщины стены.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, polygonize, unary_union

GAP_TOL_PT = 105.0      # максимальный проём, который замыкаем (~1.85 м при 1:50)
ANGLE_TOL = 28.0        # замыкаем только примерно вдоль стены


def _angle(a, b) -> float:
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180


def build(plan: dict, mm_per_pt: float, gap_tol: float = GAP_TOL_PT) -> dict:
    walls = plan["walls"]
    lines = [LineString([w["a"], w["b"]]) for w in walls]
    thickness = sorted(w["thickness"] for w in walls)[len(walls) // 2]

    closers = []
    for i, w in enumerate(walls):
        for end in ("a", "b"):
            p = tuple(w[end])
            other = tuple(w["b"] if end == "a" else w["a"])
            direction = _angle(other, p)
            best = None
            for j, target in enumerate(lines):
                if i == j:
                    continue
                q = nearest_points(target, Point(p))[0]
                d = math.dist(p, (q.x, q.y))
                if d < 0.5 or d > gap_tol:
                    continue
                if abs(_angle(p, (q.x, q.y)) - direction) > ANGLE_TOL and \
                   abs(abs(_angle(p, (q.x, q.y)) - direction) - 180) > ANGLE_TOL:
                    continue
                if best is None or d < best[0]:
                    best = (d, (q.x, q.y))
            if best:
                closers.append(LineString([p, best[1]]))

    merged = unary_union(lines + closers)
    faces = [p for p in polygonize(merged) if p.area > 1000]

    m_per_pt = mm_per_pt / 1000.0
    rooms = []
    for poly in faces:
        inner = poly.buffer(-thickness / 2, join_style=2)
        area = (inner.area if inner.is_valid and not inner.is_empty else poly.area) * m_per_pt ** 2
        if area < 1.0:
            continue
        c = poly.centroid
        rooms.append({
            "area_m2": round(area, 2),
            "center_pt": [round(c.x, 1), round(c.y, 1)],
            "points": [[round(x, 1), round(y, 1)] for x, y in list(poly.exterior.coords)[:-1]],
        })
    rooms.sort(key=lambda r: -r["area_m2"])
    return {
        "mm_per_pt": mm_per_pt,
        "thickness_pt": thickness,
        "closers": len(closers),
        "rooms": rooms,
        "total_m2": round(sum(r["area_m2"] for r in rooms), 2),
    }


def build_raster(plan: dict, mm_per_pt: float, px_per_pt: float = 4.0) -> dict:
    """Комнаты заливкой: стены + закрытые проёмы, свободные области внутри контура."""
    walls = plan["walls"]
    W = int(plan["page_size"]["width"] * px_per_pt) + 2
    H = int(plan["page_size"]["height"] * px_per_pt) + 2
    img = Image.new("L", (W, H), 255)
    dr = ImageDraw.Draw(img)

    for w in walls:
        dr.line([(w["a"][0] * px_per_pt, w["a"][1] * px_per_pt),
                 (w["b"][0] * px_per_pt, w["b"][1] * px_per_pt)],
                fill=0, width=max(2, int(round(w["thickness"] * px_per_pt))))
    for o in plan.get("openings", []):
        dr.line([(o["a"][0] * px_per_pt, o["a"][1] * px_per_pt),
                 (o["b"][0] * px_per_pt, o["b"][1] * px_per_pt)], fill=0, width=2)

    # дотяжка концов до ближайшей другой стены: закрывает углы и непойманные проёмы
    lines = [LineString([w["a"], w["b"]]) for w in walls]
    for i, w in enumerate(walls):
        for end in ("a", "b"):
            p = tuple(w[end])
            best = None
            for j, target in enumerate(lines):
                if i == j:
                    continue
                q = nearest_points(target, Point(p))[0]
                d = math.dist(p, (q.x, q.y))
                if 0.5 < d <= 120 and (best is None or d < best[0]):
                    best = (d, (q.x, q.y))
            if best:
                dr.line([(p[0] * px_per_pt, p[1] * px_per_pt),
                         (best[1][0] * px_per_pt, best[1][1] * px_per_pt)], fill=0, width=2)

    free = (np.array(img) > 127).astype(np.uint8)
    n, labels, stats, cents = cv2.connectedComponentsWithStats(free, 8)

    m_per_px = (mm_per_pt / 1000.0) / px_per_pt
    rooms = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1:
            continue  # внешний фон
        m2 = area * m_per_px ** 2
        if m2 < 0.8:
            continue
        cx, cy = cents[i]
        rooms.append({
            "area_m2": round(m2, 2),
            "center_pt": [round(cx / px_per_pt, 1), round(cy / px_per_pt, 1)],
            "bbox_pt": [round(x / px_per_pt, 1), round(y / px_per_pt, 1),
                        round((x + w) / px_per_pt, 1), round((y + h) / px_per_pt, 1)],
        })
    rooms.sort(key=lambda r: -r["area_m2"])
    return {
        "mm_per_pt": mm_per_pt,
        "method": "flood-fill",
        "rooms": rooms,
        "total_m2": round(sum(r["area_m2"] for r in rooms), 2),
    }


def main() -> int:
    plan_path = Path(sys.argv[1] if len(sys.argv) > 1 else
                     "tools/pdfplan/out/projectfortest/plan.json")
    mm_per_pt = float(sys.argv[2]) if len(sys.argv) > 2 else 17.639
    expected = [float(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else []

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    result = build_raster(plan, mm_per_pt)
    out = plan_path.with_name("rooms.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"комнат: {len(result['rooms'])}, сумма {result['total_m2']} м² (заливка)")
    for r in result["rooms"]:
        print(f"  {r['area_m2']:7.2f} м²  центр {r['center_pt']}")
    if expected and result["rooms"]:
        got = [r["area_m2"] for r in result["rooms"]]
        print("сверка с экспликацией:")
        for e in sorted(expected, reverse=True):
            near = min(got, key=lambda g: abs(g - e))
            print(f"  ожидалось {e:6.2f}  ближайшее {near:6.2f}  разница {abs(near - e):5.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
