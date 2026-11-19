"""Собирает автономный viewer.html: plan.json + картинка страницы внутрь файла."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def build_viewer(plan_dir: Path, out: Path) -> Path:
    plan_path = plan_dir / "plan.json"
    scheme_path = plan_dir / "scheme.png"
    page_path = plan_dir / "page.png"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    template = (HERE / "viewer_template.html").read_text(encoding="utf-8")
    scheme_b64 = base64.b64encode(scheme_path.read_bytes()).decode() if scheme_path.exists() else ""
    page_b64 = base64.b64encode(page_path.read_bytes()).decode() if page_path.exists() else scheme_b64
    html = template.replace("__DATA__", json.dumps(
        {"plan": plan, "page": page_b64, "scheme": scheme_b64}, ensure_ascii=False))
    out.write_text(html, encoding="utf-8")
    return out


def main() -> int:
    plan_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "fixtures" / "plan_vector_plan"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else plan_dir / "viewer.html"
    build_viewer(plan_dir, out)
    print(f"viewer: {out} ({out.stat().st_size // 1024} КБ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
