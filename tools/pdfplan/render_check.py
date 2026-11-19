"""Наложение результата на страницу: стены, проёмы, найденные комнаты."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> int:
    base = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/pdfplan/out/projectfortest")
    plan = json.loads((base / "plan.json").read_text(encoding="utf-8"))
    rooms_path = base / "rooms.json"
    rooms = json.loads(rooms_path.read_text(encoding="utf-8")) if rooms_path.exists() else {"rooms": []}

    img = Image.open(base / "page.png").convert("RGBA")
    sx = img.width / plan["page_size"]["width"]
    sy = img.height / plan["page_size"]["height"]
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(ov)

    for w in plan["walls"]:
        a = (w["a"][0] * sx, w["a"][1] * sy)
        b = (w["b"][0] * sx, w["b"][1] * sy)
        dr.line([a, b], fill=(43, 102, 179, 120), width=max(2, int(w["thickness"] * sx)))
        dr.line([a, b], fill=(179, 38, 30, 230), width=2)
    for o in plan.get("openings", []):
        a = (o["a"][0] * sx, o["a"][1] * sy)
        b = (o["b"][0] * sx, o["b"][1] * sy)
        dr.line([a, b], fill=(31, 122, 77, 255), width=3)
    for r in rooms.get("rooms", []):
        x, y = r["center_pt"]
        p = (x * sx, y * sy)
        dr.ellipse([p[0] - 9, p[1] - 9, p[0] + 9, p[1] + 9], fill=(138, 90, 0, 255))
        dr.text((p[0] + 12, p[1] - 6), f"{r['area_m2']} m2", fill=(90, 60, 0, 255))

    out = base / "check.png"
    Image.alpha_composite(img, ov).convert("RGB").save(out)
    print(f"walls {len(plan['walls'])}, openings {len(plan.get('openings', []))}, "
          f"rooms {len(rooms.get('rooms', []))} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
