"""Прогон тестового набора: метрики по каждому PDF и сводка в markdown."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate as ev
import pipeline as P
import scale as sc

BENCH = Path(__file__).resolve().parent / "bench"
CASES = BENCH / "cases"
TRUTH = json.loads((Path(__file__).resolve().parent / "fixtures" / "truth.json")
                   .read_text(encoding="utf-8"))
TRUTH_WALLS = [(tuple(w["a"]), tuple(w["b"]), w["thickness"]) for w in TRUTH["walls"]]


def pick_page(doc: fitz.Document) -> int:
    best, score = 0, -1
    for i, page in enumerate(doc):
        s = len(page.get_drawings()) + 5 * len(page.get_images())
        if s > score:
            best, score = i, s
    return best


def run(path: Path, use_truth: bool = False) -> dict:
    doc = fitz.open(path)
    page_no = pick_page(doc)
    t0 = time.perf_counter()
    result, walls, page = P.build(path, page_no)
    dt = time.perf_counter() - t0

    scale_info = sc.calibrate(page)
    det = [((w.a[0], w.a[1]), (w.b[0], w.b[1]), w.thickness) for w in walls]

    row = {
        "file": path.name,
        "pages": doc.page_count,
        "page": page_no,
        "kind": result["classification"]["kind"],
        "used": result["classification"]["used"],
        "walls": len(walls),
        "openings": len(result["openings"]),
        "junctions": result["stats"]["junctions"],
        "median_t": result["stats"]["median_thickness_pt"],
        "scale": scale_info.get("approx") or "—",
        "mm_per_pt": scale_info.get("mm_per_pt"),
        "sec": round(dt, 1),
    }
    if use_truth and det:
        pairs, used = ev.match(TRUTH_WALLS, det)
        row["precision"] = round(len(pairs) / len(det), 2)
        row["recall"] = round(len(pairs) / len(TRUTH_WALLS), 2)
    else:
        row["precision"] = row["recall"] = None
    return row


def main() -> int:
    files = [p for p in sorted(CASES.glob("*.pdf"))]
    real = [Path("tools/pdfplan/out/projectfortest.pdf"),
            Path(".zwork/attachments/7682913d-fb35-41af-a128-690be3f9dde1/projectfortest.pdf"),
            Path("tools/pdfplan/out/projectfortest_scan.pdf")]
    cases = []
    for p in files:
        cases.append((p, True))
    for p in real:
        if p.exists():
            cases.append((p, False))

    rows = [run(p, truth) for p, truth in cases]

    lines = ["| файл | стр. | тип | путь | стен | проёмов | узлов | толщ. | масштаб | P | R | сек |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        lines.append("| {file} | {page}/{pages} | {kind} | {used} | {walls} | {openings} | "
                     "{junctions} | {median_t} | {scale} | {precision} | {recall} | {sec} |".format(
                         **{k: ("—" if v is None else v) for k, v in r.items()}))
    report = "\n".join(lines)
    (BENCH / "report_auto.md").write_text("# Прогон тестового набора\n\n" + report + "\n",
                                          encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
