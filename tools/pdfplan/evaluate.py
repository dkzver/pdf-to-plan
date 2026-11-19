"""Сравнение найденных стен с эталоном фикстуры: precision, recall, ошибка осевой."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def load(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return [(tuple(w["a"]), tuple(w["b"]), w["thickness"]) for w in data["walls"]]


def angle(a, b) -> float:
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0


def match(truth, det, angle_tol=5.0, dist_tol=6.0, overlap=0.5):
    """Для каждой эталонной стены ищет ближайшую найденную; возвращает пары и метрики."""
    pairs = []
    used = set()
    for t in truth:
        ta, tb, tt = t
        ang = angle(ta, tb)
        ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        nx, ny = -uy, ux
        best, best_d = None, 1e9
        for i, d in enumerate(det):
            if i in used:
                continue
            da, db, dt = d
            if abs(angle(da, db) - ang) > angle_tol and abs(abs(angle(da, db) - ang) - 180) > angle_tol:
                continue
            dist = abs((da[0] - ta[0]) * nx + (da[1] - ta[1]) * ny)
            if dist > dist_tol:
                continue
            ts = sorted([ta[0] * ux + ta[1] * uy, tb[0] * ux + tb[1] * uy])
            ds = sorted([da[0] * ux + da[1] * uy, db[0] * ux + db[1] * uy])
            inter = min(ts[1], ds[1]) - max(ts[0], ds[0])
            ratio = inter / max(1e-6, min(ts[1] - ts[0], ds[1] - ds[0]))
            if ratio < overlap:
                continue
            if dist < best_d:
                best, best_d = i, dist
        if best is not None:
            used.add(best)
            pairs.append((t, det[best], best_d))
    return pairs, used


def main() -> int:
    truth_path = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/pdfplan/fixtures/truth.json")
    det_path = Path(sys.argv[2] if len(sys.argv) > 2 else "tools/pdfplan/fixtures/plan_vector_plan/plan.json")
    truth = load(truth_path)
    det = load(det_path)
    pairs, used = match(truth, det)

    tp = len(pairs)
    fp = len(det) - tp
    fn = len(truth) - tp
    prec = tp / len(det) if det else 0
    rec = tp / len(truth) if truth else 0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
    th_err = [abs(p[1][2] - p[0][2]) for p in pairs]
    dist_err = [p[2] for p in pairs]

    print(f"эталон: {len(truth)} стен, найдено: {len(det)}")
    print(f"precision {prec:.2f}  recall {rec:.2f}  f1 {f1:.2f}")
    if pairs:
        print(f"толщина: средняя ошибка {sum(th_err)/len(th_err):.1f} pt, "
              f"осевая: {sum(dist_err)/len(dist_err):.1f} pt")
    if fn:
        print("не найдены:")
        matched_ids = {id(p[0]) for p in pairs}
        for t in truth:
            if id(t) not in matched_ids:
                print(f"  {t[0]} -> {t[1]}  t={t[2]}")
    if fp:
        print("лишние:")
        for i, d in enumerate(det):
            if i not in used:
                print(f"  {d[0]} -> {d[1]}  t={d[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
