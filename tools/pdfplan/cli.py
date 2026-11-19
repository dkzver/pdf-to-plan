"""CLI: PDF -> plan.json + overlay.svg + page.png."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline import build, write_svg


def main() -> int:
    ap = argparse.ArgumentParser(description="Разбор PDF-чертежа в схему стен")
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, default=0, help="номер страницы с нуля")
    ap.add_argument("--force", choices=["auto", "vector", "raster"], default="auto")
    ap.add_argument("--dpi", type=int, default=300, help="dpi для растрового пути")
    ap.add_argument("--out", default=None, help="каталог результата")
    args = ap.parse_args()

    src = Path(args.pdf)
    out = Path(args.out) if args.out else src.with_name(src.stem + "_plan")
    out.mkdir(parents=True, exist_ok=True)

    result, walls, page = build(src, args.page, None if args.force == "auto" else args.force, args.dpi)
    (out / "plan.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_svg(page, walls, out / "overlay.svg")
    page.get_pixmap(dpi=150).save(out / "page.png")

    c = result["classification"]
    print(f"{src.name}: {c['used']} (drawings={c['drawings']}, images={c['images']}, "
          f"image_area={c['image_area_ratio']})")
    print(f"стен: {result['stats']['walls']}, узлов: {result['stats']['junctions']}, "
          f"толщина медиана: {result['stats']['median_thickness_pt']} pt")
    print(f"результат: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
