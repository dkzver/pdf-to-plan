"""PDF -> схема планировки: классификация, извлечение стен, склейка, узлы.

Два пути:
  vector  — тянем операторы рисования из PDF (PyMuPDF), стены = толстые линии
            и залитые прямоугольники; двойные тонкие линии склеиваем в стену.
  raster  — рендер 300 dpi, порог, контуры, minAreaRect для залитых стен,
            пара тонких линий для двойных.

Выход: plan.json (стены осевыми линиями + толщина) и overlay.svg для проверки.
Единицы — пункты PDF (1 pt = 1/72"), масштаб в метры задаётся отдельно.
"""
from __future__ import annotations

import base64
import json
import math
import os
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
import pymupdf as fitz

# --- геометрия ---------------------------------------------------------------

@dataclass
class Wall:
    a: tuple[float, float]
    b: tuple[float, float]
    thickness: float
    confidence: float = 0.8
    source: str = "vector"

    @property
    def length(self) -> float:
        return math.dist(self.a, self.b)

    @property
    def angle(self) -> float:
        ang = math.degrees(math.atan2(self.b[1] - self.a[1], self.b[0] - self.a[0]))
        return ang % 180.0


def _norm(w: Wall) -> Wall:
    """Стабильное направление: слева-направо, иначе сверху-вниз."""
    (x1, y1), (x2, y2) = w.a, w.b
    if (x1, y1) > (x2, y2):
        return Wall((x2, y2), (x1, y1), w.thickness, w.confidence, w.source)
    return w


def _axis(angle_deg: float) -> tuple[float, float]:
    r = math.radians(angle_deg)
    return math.cos(r), math.sin(r)


def _offset(w: Wall) -> float:
    ux, uy = _axis(w.angle)
    nx, ny = -uy, ux
    return w.a[0] * nx + w.a[1] * ny


def merge_collinear(walls: list[Wall], angle_tol: float = 2.5,
                    offset_tol: float = 3.5, gap_tol: float = 14.0) -> list[Wall]:
    """Склеивает отрезки одной прямой с разрывами (стыки, проёмы)."""
    bins: dict[int, list[Wall]] = {}
    for w in walls:
        bins.setdefault(round(w.angle / angle_tol), []).append(w)

    out: list[Wall] = []
    for group in bins.values():
        group.sort(key=_offset)
        clusters: list[list[Wall]] = []
        for w in group:
            if clusters and abs(_offset(w) - _offset(clusters[-1][-1])) <= offset_tol:
                clusters[-1].append(w)
            else:
                clusters.append([w])

        for cluster in clusters:
            ux, uy = _axis(sum(w.angle for w in cluster) / len(cluster) / 1.0)
            off = sum(_offset(w) for w in cluster) / len(cluster)
            nx, ny = -uy, ux
            spans = []
            for w in cluster:
                t1 = w.a[0] * ux + w.a[1] * uy
                t2 = w.b[0] * ux + w.b[1] * uy
                spans.append((min(t1, t2), max(t1, t2), w.thickness))
            spans.sort()
            cur_s, cur_e, th = spans[0]
            for s, e, t in spans[1:]:
                if s - cur_e <= gap_tol:
                    cur_e = max(cur_e, e)
                    th = max(th, t)
                else:
                    out.append(_make(cur_s, cur_e, off, th, ux, uy, cluster))
                    cur_s, cur_e, th = s, e, t
            out.append(_make(cur_s, cur_e, off, th, ux, uy, cluster))
    return [w for w in out if w.length >= 20]


def _make(s, e, off, th, ux, uy, cluster) -> Wall:
    nx, ny = -uy, ux
    a = (ux * s + nx * off, uy * s + ny * off)
    b = (ux * e + nx * off, uy * e + ny * off)
    conf = sum(w.confidence for w in cluster) / len(cluster)
    return Wall(a, b, th, conf, cluster[0].source)


def snap_nodes(walls: list[Wall], tol: float = 6.0) -> list[Wall]:
    """Сводит близкие концы в общий узел и выпрямляет почти ортогональные стены."""
    pts: list[tuple[float, float]] = []
    for w in walls:
        pts.extend([w.a, w.b])

    clusters: list[list[tuple[float, float]]] = []
    for p in pts:
        for c in clusters:
            cx = sum(q[0] for q in c) / len(c)
            cy = sum(q[1] for q in c) / len(c)
            if math.dist(p, (cx, cy)) <= tol:
                c.append(p)
                break
        else:
            clusters.append([p])

    def snap(p):
        for c in clusters:
            cx = sum(q[0] for q in c) / len(c)
            cy = sum(q[1] for q in c) / len(c)
            if math.dist(p, (cx, cy)) <= tol:
                return (round(cx, 2), round(cy, 2))
        return p

    out = []
    for w in walls:
        a, b = snap(w.a), snap(w.b)
        ang = Wall(a, b, w.thickness, w.confidence, w.source).angle
        if min(abs(ang - 0), abs(ang - 90), abs(ang - 180)) <= 2.0:
            if abs(ang - 90) >= 2.0:
                b = (b[0], a[1])
            else:
                b = (a[0], b[1])
        out.append(Wall(a, b, w.thickness, w.confidence, w.source))
    return out


def dedupe(walls: list[Wall], angle_tol: float = 3.0,
           dist_tol: float = 3.5, overlap: float = 0.55) -> list[Wall]:
    """Убирает дубли: одна стена, обведённая контуром и заливкой, даёт два отрезка."""
    walls = sorted(walls, key=lambda w: (-w.thickness, -w.length))
    kept: list[Wall] = []
    for w in walls:
        dup = False
        for k in kept:
            if abs(w.angle - k.angle) > angle_tol and abs(abs(w.angle - k.angle) - 180) > angle_tol:
                continue
            ux, uy = _axis(k.angle)
            nx, ny = -uy, ux
            d = abs((w.a[0] - k.a[0]) * nx + (w.a[1] - k.a[1]) * ny)
            if d > dist_tol:
                continue
            t = sorted([w.a[0] * ux + w.a[1] * uy, w.b[0] * ux + w.b[1] * uy])
            kt = sorted([k.a[0] * ux + k.a[1] * uy, k.b[0] * ux + k.b[1] * uy])
            inter = min(t[1], kt[1]) - max(t[0], kt[0])
            if inter > 0 and inter / max(1e-6, min(t[1] - t[0], kt[1] - kt[0])) >= overlap:
                dup = True
                break
        if not dup:
            kept.append(w)
    return kept


def pair_double_lines(walls: list[Wall], dmin: float = 6.0, dmax: float = 34.0,
                      min_len: float = 40.0, overlap: float = 0.65) -> tuple[list[Wall], list[Wall]]:
    """Две параллельные тонкие линии -> одна стена по центру. Возвращает (стены, остаток).

    Длины должны быть сопоставимы: иначе длинная размерная линия склеивается
    с короткой линией окна и рождает фантомную стену.
    """
    thin = [w for w in walls if w.thickness <= 2.2 and w.length >= min_len]
    rest = [w for w in walls if w not in thin]
    used: set[int] = set()
    pairs: list[Wall] = []

    for i, w1 in enumerate(thin):
        if i in used:
            continue
        best = None
        for j in range(i + 1, len(thin)):
            if j in used:
                continue
            w2 = thin[j]
            if abs(w1.angle - w2.angle) > 3.0:
                continue
            ux, uy = _axis(w1.angle)
            nx, ny = -uy, ux
            d = abs((w2.a[0] - w1.a[0]) * nx + (w2.a[1] - w1.a[1]) * ny)
            if not (dmin <= d <= dmax):
                continue
            t1 = sorted([w1.a[0] * ux + w1.a[1] * uy, w1.b[0] * ux + w1.b[1] * uy])
            t2 = sorted([w2.a[0] * ux + w2.a[1] * uy, w2.b[0] * ux + w2.b[1] * uy])
            len1, len2 = t1[1] - t1[0], t2[1] - t2[0]
            if min(len1, len2) / max(len1, len2) < 0.55:
                continue
            inter = min(t1[1], t2[1]) - max(t1[0], t2[0])
            if inter <= 0 or inter / max(len1, len2) < overlap:
                continue
            score = inter / (1 + abs(d - 14))
            if best is None or score > best[0]:
                best = (score, j, d, t1, t2)
        if best:
            _, j, d, t1, t2 = best
            w2 = thin[j]
            used.add(j)
            used.add(i)
            ux, uy = _axis(w1.angle)
            nx, ny = -uy, ux
            off = (t1[0] + t1[1] + t2[0] + t2[1]) / 4.0
            s, e = min(t1[0], t2[0]), max(t1[1], t2[1])
            mid_off = (_offset(w1) + _offset(w2)) / 2
            p1 = (ux * s + nx * mid_off, uy * s + ny * mid_off)
            p2 = (ux * e + nx * mid_off, uy * e + ny * mid_off)
            pairs.append(Wall(p1, p2, d, 0.6, w1.source))

    leftover = [w for idx, w in enumerate(thin) if idx not in used]
    return pairs, rest + leftover


def drop_inserts(walls: list[Wall], max_thickness: float = 5.0,
                 max_len: float = 130.0) -> list[Wall]:
    """Выкидывает тонкие вставки внутри толстой стены — это окна и проёмы, не стены."""
    out = []
    for w in walls:
        if w.thickness > max_thickness or w.length > max_len:
            out.append(w)
            continue
        insert = False
        for k in walls:
            if k is w or k.thickness < w.thickness + 2:
                continue
            if abs(k.angle - w.angle) > 3 and abs(abs(k.angle - w.angle) - 180) > 3:
                continue
            ux, uy = _axis(k.angle)
            nx, ny = -uy, ux
            d = abs((w.a[0] - k.a[0]) * nx + (w.a[1] - k.a[1]) * ny)
            if d > 4:
                continue
            tw = sorted([w.a[0] * ux + w.a[1] * uy, w.b[0] * ux + w.b[1] * uy])
            tk = sorted([k.a[0] * ux + k.a[1] * uy, k.b[0] * ux + k.b[1] * uy])
            if min(tw[1], tk[1]) - max(tw[0], tk[0]) > 0:
                insert = True
                break
        if not insert:
            out.append(w)
    return out


# --- классификация и извлечение ---------------------------------------------

def classify(page: fitz.Page) -> dict:
    drawings = page.get_drawings()
    images = page.get_images(full=True)
    text = page.get_text("text").strip()
    page_area = page.rect.width * page.rect.height
    img_area = 0.0
    for info in page.get_image_info():
        r = fitz.Rect(info["bbox"])
        img_area += max(0.0, r.width) * max(0.0, r.height)
    ratio = img_area / page_area if page_area else 0

    if len(drawings) >= 8 and ratio < 0.6:
        kind = "vector"
    elif images and ratio >= 0.6 and len(drawings) < 8:
        kind = "raster"
    elif len(drawings) >= 8:
        kind = "mixed"
    else:
        kind = "raster"

    return {
        "kind": kind,
        "drawings": len(drawings),
        "images": len(images),
        "image_area_ratio": round(ratio, 3),
        "text_chars": len(text),
    }


WALL_LAYER_HINTS = ("стен", "перегород", "wall")


def _polygon_points(d: dict) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for it in d.get("items", []):
        k = it[0]
        if k == "l":
            pts += [(float(it[1].x), float(it[1].y)), (float(it[2].x), float(it[2].y))]
        elif k == "re":
            r = it[1]
            pts += [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
        elif k == "qu":
            q = it[1]
            pts += [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)]
        elif k == "c":
            pts += [(float(p.x), float(p.y)) for p in it[1:5]]
    return pts


def _wall_from_polygon(pts: list[tuple[float, float]]) -> Wall | None:
    """Залитый полигон -> стена, если он вытянутый и по площади почти прямоугольник."""
    if len(pts) < 4:
        return None
    arr = np.array(pts, dtype=np.float32)
    (cx, cy), (w, h), ang = cv2.minAreaRect(arr)
    long_s, short_s = max(w, h), min(w, h)
    if short_s <= 0 or long_s < 20:
        return None
    if short_s < 2.0 or short_s > 48.0 or long_s / short_s < 3.0:
        return None
    poly_area = abs(cv2.contourArea(arr))
    if poly_area <= 0 or poly_area / (long_s * short_s) < 0.72:
        return None  # L-образный угол — не отдельная стена
    a = ang if w >= h else ang + 90.0
    ux, uy = _axis(a % 180.0)
    half = long_s / 2
    return Wall((cx - ux * half, cy - uy * half), (cx + ux * half, cy + uy * half),
                short_s, 0.95)


def vector_walls(page: fitz.Page) -> tuple[list[Wall], list[dict]]:
    """Стены из операторов рисования + белые «подчистки» как проёмы."""
    walls: list[Wall] = []
    lines: list[Wall] = []
    gaps: list[fitz.Rect] = []
    gap_pts: list[list[tuple[float, float]]] = []

    drs = page.get_drawings(extended=True)
    names = {(d.get("layer") or "") for d in drs}
    wall_names = {n for n in names if any(h in n.lower() for h in WALL_LAYER_HINTS)}
    strict = bool(wall_names)  # в CAD-экспорте слой стен есть — берём только его
    for d in drs:
        layer = d.get("layer") or ""
        if strict and layer not in wall_names:
            continue
        w = float(d.get("width") or 0.0)
        fill = d.get("fill")
        dtype = d.get("type")
        white_fill = bool(fill) and min(fill) >= 0.85

        if dtype in ("f", "fs") and fill:
            if white_fill:
                pts = _polygon_points(d)
                if pts:
                    gap_pts.append(pts)
                continue
            wall = _wall_from_polygon(_polygon_points(d))
            if wall:
                walls.append(wall)
            continue

        for item in d.get("items", []):
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            a = (float(p1.x), float(p1.y))
            b = (float(p2.x), float(p2.y))
            if math.dist(a, b) < 20:
                continue
            if w >= 2.0:
                ln = Wall(a, b, max(w, 1.0), 0.75, "vector")
                lines.append(ln)
                walls.append(ln)
            else:
                # тонкая линия: сама по себе не стена, но пара таких — стена
                ln = Wall(a, b, max(w, 0.3), 0.4, "vector")
                lines.append(ln)
                walls.append(ln)

    # проёмы: белые «подчистки» -> окно, если внутри 2+ тонких линии
    openings: list[dict] = []
    for pts in gap_pts:
        wall = _wall_from_polygon(pts)
        if wall is None:
            arr = np.array(pts, dtype=np.float32)
            (cx, cy), (w, h), ang = cv2.minAreaRect(arr)
            long_s, short_s = max(w, h), min(w, h)
            if long_s < 25 or short_s < 3 or short_s > 48:
                continue
            a = ang if w >= h else ang + 90.0
            ux, uy = _axis(a % 180.0)
            half = long_s / 2
            aw = Wall((cx - ux * half, cy - uy * half), (cx + ux * half, cy + uy * half),
                      short_s, 0.7)
        else:
            aw = wall
        box = fitz.Rect(min(aw.a[0], aw.b[0]), min(aw.a[1], aw.b[1]),
                        max(aw.a[0], aw.b[0]), max(aw.a[1], aw.b[1])) + (-1, -1, 1, 1)
        inside = [ln for ln in lines if box.contains(fitz.Point(*ln.a)) or box.contains(fitz.Point(*ln.b))]
        kind = "window" if len(inside) >= 2 else "door"
        openings.append({"kind": kind, "a": [round(aw.a[0], 1), round(aw.a[1], 1)],
                         "b": [round(aw.b[0], 1), round(aw.b[1], 1)],
                         "width": round(aw.thickness, 1)})

    pw, ph = page.rect.width, page.rect.height
    if strict:
        # полигоны стен в CAD упираются в угловой блок — дотягиваем до узла
        walls = extend_ends(walls, 0.5)
    else:
        walls = [w for w in walls if not (w.thickness <= 1.2 and _near_border(w, pw, ph))]
    return walls, openings


def _near_border(w: Wall, pw: float, ph: float, m: float = 26.0) -> bool:
    return all((p[0] < m or p[0] > pw - m or p[1] < m or p[1] > ph - m) for p in (w.a, w.b))


def _dominant_angle(bw: np.ndarray) -> float:
    """Главный наклон чертежа: медиана углов длинных отрезков, сведённая к [-45, 45)."""
    segs = cv2.HoughLinesP(bw, 1, np.pi / 360, threshold=60,
                           minLineLength=max(80, bw.shape[1] // 12), maxLineGap=4)
    if segs is None:
        return 0.0
    angles, weights = [], []
    for x1, y1, x2, y2 in np.asarray(segs).reshape(-1, 4):
        a = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0
        if a > 90:
            a -= 180
        if abs(a) <= 45:
            angles.append(a)
            weights.append(math.hypot(x2 - x1, y2 - y1))
    if not angles:
        return 0.0
    order = np.argsort(angles)
    cum = np.cumsum(np.array(weights)[order])
    idx = int(np.searchsorted(cum, cum[-1] / 2))
    return float(np.array(angles)[order][idx])


def raster_walls(page: fitz.Page, dpi: int = 300) -> list[Wall]:
    """Стены из растра: бинаризация, скелет, Hough по скелету, толщина из distance transform."""
    pix = page.get_pixmap(dpi=dpi)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if pix.n >= 3 else img[:, :, 0]
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if bw.mean() > 127:
        bw = 255 - bw
    scale = dpi / 72.0

    angle = _dominant_angle(bw)
    if 0.3 < abs(angle) < 15:
        h, w = bw.shape
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        bw = cv2.warpAffine(bw, M, (w, h), borderValue=0)
        walls = _walls_from_binary(bw, scale)
        Mi = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1.0)
        out = []
        for wall in walls:
            pts = []
            for (x, y) in (wall.a, wall.b):
                px = np.array([x * scale, y * scale, 1.0])
                q = Mi @ px
                pts.append((q[0] / scale, q[1] / scale))
            out.append(Wall(pts[0], pts[1], wall.thickness, wall.confidence, wall.source))
        return out
    return _walls_from_binary(bw, scale)


def layer_walls(page: fitz.Page, px_per_pt: float = 3.0) -> tuple[list[Wall], list[dict]]:
    """Только стены: перерисовываем полигоны слоя стен в растр и снимаем оси со скелета.

    Так обрабатываются L-образные и диагональные стены, которые не сводятся
    к одному прямоугольнику.
    """
    drs = page.get_drawings(extended=True)
    wall_names = {(d.get("layer") or "") for d in drs
                  if any(h in (d.get("layer") or "").lower() for h in WALL_LAYER_HINTS)}
    if not wall_names:
        return [], []

    W = int(page.rect.width * px_per_pt)
    H = int(page.rect.height * px_per_pt)
    img = Image.new("L", (W, H), 255)
    dr = ImageDraw.Draw(img)
    gap_polys: list[list[tuple[float, float]]] = []

    for d in drs:
        if (d.get("layer") or "") not in wall_names:
            continue
        fill = d.get("fill")
        pts = _polygon_points(d)
        if d.get("type") in ("f", "fs") and fill:
            scaled = [(x * px_per_pt, y * px_per_pt) for x, y in pts]
            if min(fill) >= 0.85:
                gap_polys.append(pts)
                dr.polygon(scaled, fill=255)
            else:
                dr.polygon(scaled, fill=0)
        elif d.get("type") in ("s", "fs"):
            wpx = max(1, int(round(float(d.get("width") or 0) * px_per_pt)))
            for it in d.get("items", []):
                if it[0] == "l":
                    dr.line([(it[1].x * px_per_pt, it[1].y * px_per_pt),
                             (it[2].x * px_per_pt, it[2].y * px_per_pt)],
                            fill=0, width=wpx)

    bw = 255 - np.array(img)
    walls = _walls_from_binary(bw, px_per_pt)
    walls = extend_ends(walls, 0.5)

    openings = []
    for pts in gap_polys:
        arr = np.array(pts, dtype=np.float32)
        (cx, cy), (w, h), ang = cv2.minAreaRect(arr)
        long_s, short_s = max(w, h), min(w, h)
        if long_s < 25 or short_s < 3 or short_s > 48:
            continue
        a = ang if w >= h else ang + 90.0
        ux, uy = _axis(a % 180.0)
        half = long_s / 2
        openings.append({"kind": "window" if short_s < 12 else "door",
                         "a": [round(cx - ux * half, 1), round(cy - uy * half, 1)],
                         "b": [round(cx + ux * half, 1), round(cy + uy * half, 1)],
                         "width": round(short_s, 1)})
    return walls, openings


def _skeleton(bw: np.ndarray) -> np.ndarray:
    """Скелет линий. ximgproc есть только в contrib-сборке OpenCV — есть запасной путь."""
    if os.environ.get("PLAN_NO_XIMGPROC") != "1" and hasattr(cv2, "ximgproc"):
        try:
            return cv2.ximgproc.thinning(bw)
        except Exception:  # noqa: BLE001 — падаем в морфологический скелет
            pass

    img = bw.copy()
    skel = np.zeros_like(img)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    for _ in range(200):
        eroded = cv2.erode(img, element)
        opened = cv2.dilate(eroded, element)
        skel = cv2.bitwise_or(skel, cv2.subtract(img, opened))
        img = eroded
        if cv2.countNonZero(img) == 0:
            break
    return skel


def _walls_from_binary(bw: np.ndarray, scale: float) -> list[Wall]:

    # мелкие компоненты — буквы, стрелки размеров, точки
    n, labels, stats, _ = cv2.connectedComponentsWithStats((bw > 0).astype(np.uint8), 8)
    clean = np.zeros_like(bw)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 220 or (w < 10 and h < 10):
            continue
        clean[labels == i] = 255

    dt = cv2.distanceTransform((clean > 0).astype(np.uint8), cv2.DIST_L2, 5)
    skel = _skeleton(clean)

    min_len = max(24, int(28 * scale / 4.17))
    segs = cv2.HoughLinesP(skel, 1, np.pi / 360, threshold=30,
                           minLineLength=min_len, maxLineGap=int(3 * scale))
    if segs is None:
        return []

    walls: list[Wall] = []
    for (x1, y1, x2, y2) in np.asarray(segs).reshape(-1, 4):
        length = math.hypot(x2 - x1, y2 - y1)
        if length < min_len:
            continue
        samples = []
        for k in range(9):
            t = 0.2 + 0.6 * k / 8
            px = int(round(x1 + (x2 - x1) * t))
            py = int(round(y1 + (y2 - y1) * t))
            if 0 <= py < dt.shape[0] and 0 <= px < dt.shape[1]:
                samples.append(dt[py, px])
        if not samples:
            continue
        thickness_px = 2 * float(np.median(samples))
        thickness = thickness_px / scale
        if thickness < 2.2:
            continue
        walls.append(Wall((x1 / scale, y1 / scale), (x2 / scale, y2 / scale),
                          thickness, 0.7, "raster"))
    return walls


def extend_ends(walls: list[Wall], factor: float = 0.5) -> list[Wall]:
    """Скелет растра не доходит до угла на полтолщины — дотягиваем концы."""
    out = []
    for w in walls:
        dx, dy = w.b[0] - w.a[0], w.b[1] - w.a[1]
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        pad = w.thickness * factor
        out.append(Wall((w.a[0] - ux * pad, w.a[1] - uy * pad),
                        (w.b[0] + ux * pad, w.b[1] + uy * pad),
                        w.thickness, w.confidence, w.source))
    return out


def orthogonalize(walls: list[Wall], tol: float = 3.0) -> list[Wall]:
    """Притягивает почти горизонтальные/вертикальные стены к точным 0/90°."""
    out = []
    for w in walls:
        ang = w.angle
        dx, dy = w.b[0] - w.a[0], w.b[1] - w.a[1]
        if min(abs(ang), abs(ang - 90), abs(ang - 180)) <= tol:
            if abs(ang - 90) <= tol:
                x = (w.a[0] + w.b[0]) / 2
                w = Wall((x, w.a[1]), (x, w.b[1]), w.thickness, w.confidence, w.source)
            else:
                y = (w.a[1] + w.b[1]) / 2
                w = Wall((w.a[0], y), (w.b[0], y), w.thickness, w.confidence, w.source)
        out.append(w)
    return out


def _cluster(values: list[float], tol: float) -> list[float]:
    vals = sorted(values)
    groups: list[list[float]] = []
    for v in vals:
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def _nearest(values: list[float], v: float) -> float:
    return min(values, key=lambda c: abs(c - v)) if values else v


def axis_snap(walls: list[Wall], tol: float = 12.0) -> list[Wall]:
    """Ставит стены на общие оси: горизонтальные — на общий Y, вертикальные — на общий X."""
    horiz = [w for w in walls if abs(w.angle) < 3 or abs(w.angle - 180) < 3]
    vert = [w for w in walls if abs(w.angle - 90) < 3]
    ys = _cluster([w.a[1] for w in horiz], tol) if horiz else []
    xs = _cluster([w.a[0] for w in vert], tol) if vert else []

    out: list[Wall] = []
    for w in walls:
        a, b = w.a, w.b
        if w in horiz and ys:
            y = _nearest(ys, a[1])
            a, b = (a[0], y), (b[0], y)
        elif w in vert and xs:
            x = _nearest(xs, a[0])
            a, b = (x, a[1]), (x, b[1])

        # концы подтягиваем к осям другого направления, чтобы углы сходились
        if xs:
            a = (_nearest(xs, a[0]), a[1]) if abs(_nearest(xs, a[0]) - a[0]) <= tol else a
            b = (_nearest(xs, b[0]), b[1]) if abs(_nearest(xs, b[0]) - b[0]) <= tol else b
        if ys:
            a = (a[0], _nearest(ys, a[1])) if abs(_nearest(ys, a[1]) - a[1]) <= tol else a
            b = (b[0], _nearest(ys, b[1])) if abs(_nearest(ys, b[1]) - b[1]) <= tol else b
        out.append(Wall(a, b, w.thickness, w.confidence, w.source))
    return out


def _on_seg(p, w, pad: float) -> bool:
    x0, x1 = min(w.a[0], w.b[0]) - pad, max(w.a[0], w.b[0]) + pad
    y0, y1 = min(w.a[1], w.b[1]) - pad, max(w.a[1], w.b[1]) + pad
    return x0 <= p[0] <= x1 and y0 <= p[1] <= y1


def close_corners(walls: list[Wall], tol: float = 18.0) -> list[Wall]:
    """Сводит концы стен в углы: тянет конец до линии перпендикулярной стены."""
    out: list[Wall] = []
    for w in walls:
        pts = [w.a, w.b]
        for idx, p in enumerate(pts):
            best = None
            for v in walls:
                if v is w:
                    continue
                if abs(v.angle - w.angle) < 5 or abs(abs(v.angle - w.angle) - 180) < 5:
                    continue  # нужна перпендикулярная
                if abs(v.angle - 90) < 3:
                    q = (v.a[0], p[1])
                elif abs(v.angle) < 3 or abs(v.angle - 180) < 3:
                    q = (p[0], v.a[1])
                else:
                    continue
                d = math.dist(p, q)
                if d <= tol and _on_seg(q, v, tol):
                    if best is None or d < best[0]:
                        best = (d, q)
            if best:
                pts[idx] = best[1]
        out.append(Wall(pts[0], pts[1], w.thickness, w.confidence, w.source))

    # после сведения — склейка совпавших по линии участков
    return merge_collinear(out, angle_tol=2.5, offset_tol=3.0, gap_tol=6.0)


def detect_windows(page: fitz.Page, walls: list[Wall]) -> list[dict]:
    """Окна по символу: 2+ тонкие параллельные линии в полосе стены."""
    drs = page.get_drawings(extended=True)
    names = {(d.get("layer") or "") for d in drs}
    wall_names = {n for n in names if any(h in n.lower() for h in WALL_LAYER_HINTS)}

    segs = []
    for d in drs:
        if wall_names and (d.get("layer") or "") not in wall_names:
            continue
        if float(d.get("width") or 0) > 1.2:
            continue
        for it in d.get("items", []):
            if it[0] != "l":
                continue
            a = (it[1].x, it[1].y)
            b = (it[2].x, it[2].y)
            ln = math.dist(a, b)
            if not (25 <= ln <= 170):
                continue
            ang = Wall(a, b, 0).angle
            if min(abs(ang), abs(ang - 90), abs(ang - 180)) > 2.5:
                continue
            segs.append((ang, a, b, ln))

    windows = []
    used = set()
    for i, (ang, a, b, ln) in enumerate(segs):
        if i in used:
            continue
        ux, uy = _axis(ang)
        nx, ny = -uy, ux
        off_i = a[0] * nx + a[1] * ny
        t1 = sorted([a[0] * ux + a[1] * uy, b[0] * ux + b[1] * uy])
        mates = []
        for j in range(i + 1, len(segs)):
            if j in used:
                continue
            ang2, a2, b2, ln2 = segs[j]
            if abs(ang2 - ang) > 2.5:
                continue
            off_j = a2[0] * nx + a2[1] * ny
            if not (1.5 <= abs(off_j - off_i) <= 9.0):
                continue
            t2 = sorted([a2[0] * ux + a2[1] * uy, b2[0] * ux + b2[1] * uy])
            inter = min(t1[1], t2[1]) - max(t1[0], t2[0])
            if inter <= 0 or inter / min(t1[1] - t1[0], t2[1] - t2[0]) < 0.6:
                continue
            mates.append((j, off_j, t2))
        if not mates:
            continue
        offs = [off_i] + [m[1] for m in mates]
        starts = [t1[0]] + [m[2][0] for m in mates]
        ends = [t1[1]] + [m[2][1] for m in mates]
        s, e = min(starts), max(ends)
        mid = sum(offs) / len(offs)
        a_pt = (ux * s + nx * mid, uy * s + ny * mid)
        b_pt = (ux * e + nx * mid, uy * e + ny * mid)

        thickness = max(offs) - min(offs) + 4.0
        for w in walls:
            if abs(w.angle - ang) < 3 and abs(_offset(w) - mid) <= max(10.0, w.thickness):
                thickness = w.thickness
                break

        windows.append({"kind": "window", "a": [round(a_pt[0], 1), round(a_pt[1], 1)],
                        "b": [round(b_pt[0], 1), round(b_pt[1], 1)],
                        "width": round(thickness, 1)})
        used.add(i)
        used.update(m[0] for m in mates)
    return windows


def detect_balcony(page: fitz.Page, walls: list[Wall], mm_per_pt: float = 17.639) -> list[dict]:
    """Балкон: замкнутый контур из тонких линий вне полосы стен."""
    from shapely.geometry import LineString, box as sbox
    from shapely.ops import polygonize, unary_union

    drs = page.get_drawings(extended=True)
    lines = []
    for d in drs:
        if float(d.get("width") or 0) > 1.6:
            continue
        for it in d.get("items", []):
            if it[0] != "l":
                continue
            a = (it[1].x, it[1].y)
            b = (it[2].x, it[2].y)
            if math.dist(a, b) >= 20:
                lines.append(LineString([a, b]))
    if not lines or not walls:
        return []

    min_area = 2.0 * (1000.0 / mm_per_pt) ** 2  # 2 м² в pt²
    xs = [p for w in walls for p in (w.a[0], w.b[0])]
    ys = [p for w in walls for p in (w.a[1], w.b[1])]
    bx0, bx1 = min(xs) + 10, max(xs) - 10
    by0, by1 = min(ys) + 10, max(ys) - 10  # только вне полосы стен: балкон снаружи
    wall_boxes = [sbox(min(w.a[0], w.b[0]) - w.thickness,
                       min(w.a[1], w.b[1]) - w.thickness,
                       max(w.a[0], w.b[0]) + w.thickness,
                       max(w.a[1], w.b[1]) + w.thickness) for w in walls]

    out = []
    for poly in polygonize(unary_union(lines)):
        if poly.area < min_area or poly.area > 60.0 * (1000.0 / mm_per_pt) ** 2:
            continue
        bxw = poly.bounds[2] - poly.bounds[0]
        bxh = poly.bounds[3] - poly.bounds[1]
        if min(bxw, bxh) < 30 or max(bxw, bxh) / max(1.0, min(bxw, bxh)) > 8:
            continue  # слишком тонкий или вытянутый — не балкон
        c = poly.centroid
        if bx0 <= c.x <= bx1 and by0 <= c.y <= by1:
            continue  # внутри квартиры — это не балкон
        if any(b.contains(c) for b in wall_boxes):
            continue
        out.append({"points": [[round(x, 1), round(y, 1)] for x, y in list(poly.exterior.coords)[:-1]],
                    "area_m2": round(poly.area * (mm_per_pt / 1000.0) ** 2, 2)})
    return out


def drop_hatch(walls: list[Wall], max_thickness: float = 2.2,
               angle_tol: float = 3.0, spacing: float = 5.0) -> list[Wall]:
    """Убирает штриховку: тонкие линии с 2+ параллельными соседями в 5 pt.

    Настоящая двойная линия стены имеет ровно одного партнёра; штриховка —
    плотное семейство, которое иначе склеивается в диагональные «стены».
    """
    thin = [w for w in walls if w.thickness <= max_thickness]
    keep = [w for w in walls if w.thickness > max_thickness]
    for i, w in enumerate(thin):
        neighbours = 0
        for j, other in enumerate(thin):
            if i == j:
                continue
            if abs(w.angle - other.angle) > angle_tol and \
               abs(abs(w.angle - other.angle) - 180) > angle_tol:
                continue
            if abs(_offset(w) - _offset(other)) <= spacing:
                neighbours += 1
                if neighbours >= 2:
                    break
        if neighbours < 2:
            keep.append(w)
    return keep


def build(pdf_path: str | Path, page_no: int = 0, force: str | None = None,
          dpi: int = 300) -> tuple[dict, list[Wall], fitz.Page]:
    doc = fitz.open(pdf_path)
    page = doc[page_no]
    info = classify(page)
    kind = force or info["kind"]

    openings: list[dict] = []
    if any(h in (d.get("layer") or "").lower() for d in page.get_drawings(extended=True)
           for h in WALL_LAYER_HINTS):
        raw, openings = layer_walls(page)
        raw = drop_hatch(raw)
        walls = merge_collinear(raw, gap_tol=10)
        walls = drop_inserts(walls)
        walls = snap_nodes(walls)
        walls = dedupe(walls)
        info["used"] = "layer"
    elif kind in ("vector", "mixed") and len(page.get_drawings()) >= 8:
        raw, openings = vector_walls(page)
        raw = drop_hatch(raw)
        pairs, rest = pair_double_lines(raw)
        walls = merge_collinear(rest + pairs)
        walls = drop_inserts(walls)
        walls = snap_nodes(walls)
        walls = dedupe(walls)
        info["used"] = "vector"
    else:
        raw = raster_walls(page, dpi=dpi)
        pairs, rest = pair_double_lines(raw)
        walls = extend_ends(rest + pairs)
        walls = merge_collinear(walls, angle_tol=4.0, gap_tol=22.0)
        walls = drop_inserts(walls)
        walls = snap_nodes(walls)
        walls = dedupe(walls, dist_tol=5.0)
        info["used"] = "raster"

    # одиночная тонкая линия без пары — размерная линия, створка двери, линия окна
    walls = [w for w in walls if w.thickness >= 2.2]

    balconies: list[dict] = []
    if walls:
        med = float(np.median([w.thickness for w in walls]))
        tol = min(12.0, max(6.0, med * 0.8))
        walls = snap_nodes(walls, tol=tol)
        walls = orthogonalize(walls)
        walls = axis_snap(walls, tol=max(8.0, med))
        walls = close_corners(walls, tol=max(12.0, med * 1.5))
        walls = dedupe(walls)
        try:
            windows = detect_windows(page, walls)
        except Exception:  # noqa: BLE001 — окна не критичны для геометрии
            windows = []
        openings = openings + windows

    try:
        balconies = detect_balcony(page, walls)
    except Exception:  # noqa: BLE001
        balconies = []
    walls = [Wall(a, b, round(t, 1), round(c, 2), s) for (a, b, t, c, s) in
             ((w.a, w.b, w.thickness, w.confidence, w.source) for w in walls)]
    result = {
        "file": str(pdf_path),
        "page": page_no,
        "page_size": {"width": round(page.rect.width, 1), "height": round(page.rect.height, 1)},
        "classification": info,
        "units": "pt",
        "walls": [asdict(w) for w in walls],
        "openings": openings,
        "balconies": balconies,
        "stats": {
            "walls": len(walls),
            "junctions": _junction_count(walls),
            "total_length_pt": round(sum(w.length for w in walls), 1),
            "median_thickness_pt": round(float(np.median([w.thickness for w in walls])) if walls else 0, 1),
        },
    }
    _attach_scale(result, page)
    return result, walls, page


def _attach_scale(result: dict, page: fitz.Page) -> None:
    """Масштаб по размерным числам; если не нашёлся — None, площади не считаем."""
    try:
        from scale import calibrate
        result["scale"] = calibrate(page)
    except Exception as exc:  # noqa: BLE001 — без масштаба геометрия остаётся рабочей
        result["scale"] = {"error": str(exc)}


def _junction_count(walls: list[Wall], tol: float = 6.0) -> int:
    pts: list[tuple[float, float]] = []
    for w in walls:
        pts += [w.a, w.b]
    clusters: list[list[tuple[float, float]]] = []
    for p in pts:
        for c in clusters:
            if math.dist(p, c[0]) <= tol:
                c.append(p)
                break
        else:
            clusters.append([p])
    return len([c for c in clusters if len(c) >= 2])


def write_svg(page: fitz.Page, walls: list[Wall], out: Path, dpi: int = 150) -> None:
    pix = page.get_pixmap(dpi=dpi)
    bg = base64.b64encode(pix.tobytes("png")).decode()
    W, H = page.rect.width, page.rect.height
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}">',
             f'<image href="data:image/png;base64,{bg}" width="{W}" height="{H}"/>',
             '<g stroke="#2b66b3" stroke-linecap="round" opacity="0.55">']
    for w in walls:
        parts.append(f'<line x1="{w.a[0]:.1f}" y1="{w.a[1]:.1f}" x2="{w.b[0]:.1f}" '
                     f'y2="{w.b[1]:.1f}" stroke-width="{w.thickness:.1f}"/>')
    parts.append('</g><g stroke="#b3261e" stroke-width="0.7" stroke-dasharray="4 3" opacity="0.9">')
    for w in walls:
        parts.append(f'<line x1="{w.a[0]:.1f}" y1="{w.a[1]:.1f}" x2="{w.b[0]:.1f}" '
                     f'y2="{w.b[1]:.1f}"/>')
    parts.append('</g></svg>')
    out.write_text("\n".join(parts), encoding="utf-8")
