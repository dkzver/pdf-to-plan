"""Локальный сервис: загрузить PDF -> разобрать -> открыть просмотрщик.

Запуск:  python tools/pdfplan/server.py
Открыть: http://127.0.0.1:8765
Файлы не покидают машину: разбор идёт в этом процессе, результат — в tools/pdfplan/out/<id>/.
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path

import pymupdf as fitz
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pipeline as P  # noqa: E402
from make_viewer import build_viewer  # noqa: E402

OUT = Path(os.environ.get("PLAN_OUT", HERE / "out"))
SAMPLES = HERE / "samples"
ALLOWED = {"viewer.html", "plan.json", "page.png", "overlay.svg", "rooms.json", "check.png"}
MAX_MB = 60


def _process(data: bytes, filename: str) -> str:
    """Разбирает PDF и возвращает id задачи."""
    job = uuid.uuid4().hex[:8]
    target = OUT / job
    target.mkdir(parents=True, exist_ok=True)
    pdf_path = target / "input.pdf"
    pdf_path.write_bytes(data)

    try:
        result, walls, page = P.build(pdf_path, 0)
    except MemoryError as exc:
        raise HTTPException(413, "Не хватило памяти на разбор. Попробуйте файл меньшего размера или тариф с 2 ГБ") from exc
    except Exception as exc:  # noqa: BLE001 — показываем причину пользователю
        raise HTTPException(422, f"Не удалось разобрать: {exc}") from exc
    result["source_name"] = filename

    (target / "plan.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    P.write_svg(page, walls, target / "overlay.svg")
    page.get_pixmap(dpi=150).save(target / "page.png")
    try:
        from render_plan_scheme import render as render_scheme
        render_scheme(target / "plan.json", target / "scheme.png", title=filename)
    except Exception as exc:  # noqa: BLE001 — схема не обязательна, подложка останется
        print(f"[scheme] {type(exc).__name__}: {exc}", flush=True)
    build_viewer(target, target / "viewer.html")
    return job

app = FastAPI(title="PDF → планировка")

UPLOAD_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>PDF → планировка</title>
<style>
  :root { --accent:#2b66b3; --text:#1c1b1c; --muted:#5f5c5e; --border:#d0cdcf; --surface:#f2f0f1; }
  * { box-sizing:border-box; }
  body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         font:14px/1.5 Inter,"Segoe UI",system-ui,sans-serif; color:var(--text); background:var(--surface); }
  main { width:min(560px,92vw); background:#fff; border:1px solid var(--border); border-radius:8px;
         padding:28px 28px 24px; box-shadow:0 1px 3px rgba(28,27,28,.08); }
  h1 { margin:0 0 6px; font-size:20px; font-weight:600; }
  p.lead { margin:0 0 20px; color:var(--muted); }
  .drop { border:1.5px dashed var(--border); border-radius:8px; padding:22px; text-align:center;
          transition:border-color .15s, background .15s; }
  .drop.over { border-color:var(--accent); background:#f6f9fd; }
  .drop b { display:block; margin-bottom:6px; }
  .drop span { color:var(--muted); font-size:12px; }
  input[type=file] { display:none; }
  .btn { display:inline-block; margin-top:16px; padding:9px 18px; border-radius:5px; border:0;
         background:var(--accent); color:#fff; font:inherit; font-weight:600; cursor:pointer; }
  .btn:disabled { opacity:.55; cursor:default; }
  .pick { display:inline-block; margin-top:10px; padding:7px 14px; border:1px solid var(--border);
          border-radius:5px; cursor:pointer; background:#fff; }
  .row { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-top:18px; }
  .note { color:var(--muted); font-size:12px; margin-top:14px; }
  .name { margin-top:12px; font-size:12px; color:var(--muted); min-height:18px; }
  .steps { margin:0 0 18px; padding-left:18px; color:var(--muted); }
  .steps li { margin-bottom:4px; }
  .steps b { color:var(--text); font-weight:600; }
  .samples { margin-top:18px; padding-top:14px; border-top:1px solid var(--border);
             font-size:12px; color:var(--muted); }
  .samples a { color:var(--accent); }
  form.busy .btn { opacity:.6; pointer-events:none; }
</style></head>
<body><main>
  <h1>PDF → планировка</h1>
  <p class="lead">Три шага: загрузить чертёж, дождаться разбора, поправить стены в просмотрщике.</p>
  <ol class="steps">
    <li><b>Выберите PDF</b> или перетащите файл в рамку.</li>
    <li><b>Нажмите «Разобрать»</b> — займёт 5–10 секунд.</li>
    <li><b>Проверьте схему</b>: потяните концы стен, нажмите «Пересчитать комнаты».</li>
  </ol>
  <form class="drop" id="form" action="/parse" method="post" enctype="multipart/form-data">
    <b>Перетащите PDF сюда</b>
    <span>или выберите файл · до 60 МБ · обработка локальная</span>
    <div class="name" id="name"></div>
    <label class="pick" for="file">Выбрать PDF</label>
    <input id="file" type="file" name="file" accept="application/pdf">
    <div class="row">
      <span class="note">Если в документе несколько листов, возьмём лист с планом.</span>
      <button class="btn" id="submit" type="submit">Разобрать</button>
    </div>
  </form>
  <div class="samples">
    <b>Нет файла под рукой?</b> Откройте готовый пример:
    <a href="/demo/01-studio.pdf">студия</a>,
    <a href="/demo/02-two-rooms.pdf">2 комнаты</a>,
    <a href="/demo/03-l-shape.pdf">L-образная</a>,
    <a href="/demo/04-house-terrace.pdf">дом с террасой</a>,
    <a href="/demo/05-office.pdf">офис</a>.
  </div>
</main>
<script>
const form = document.getElementById('form');
const input = document.getElementById('file');
const name = document.getElementById('name');
input.addEventListener('change', () => { name.textContent = input.files[0] ? input.files[0].name : ''; });
form.addEventListener('dragover', e => { e.preventDefault(); form.classList.add('over'); });
form.addEventListener('dragleave', () => form.classList.remove('over'));
form.addEventListener('drop', e => {
  e.preventDefault(); form.classList.remove('over');
  if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; name.textContent = input.files[0].name; }
});
form.addEventListener('submit', e => {
  if (!input.files.length) { e.preventDefault(); name.textContent = 'Сначала выберите PDF'; return; }
  form.classList.add('busy');
  document.getElementById('submit').textContent = 'Разбираю…';
});
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return UPLOAD_HTML


@app.post("/parse")
def parse(file: UploadFile = File(...)) -> RedirectResponse:
    name = (file.filename or "").lower()
    if not name.endswith(".pdf"):
        raise HTTPException(400, "Нужен PDF")
    data = file.file.read()
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"Файл больше {MAX_MB} МБ")
    job = _process(data, file.filename or "plan.pdf")
    return RedirectResponse(url=f"/plan/{job}/viewer.html", status_code=303)


@app.get("/demo/{name}")
def demo(name: str):
    if not re.fullmatch(r"[0-9a-z\-]+\.pdf", name):
        raise HTTPException(404)
    path = SAMPLES / name
    if not path.exists():
        raise HTTPException(404)
    job = _process(path.read_bytes(), name)
    return RedirectResponse(url=f"/plan/{job}/viewer.html", status_code=303)


@app.get("/plan/{job}/{name}")
def plan_file(job: str, name: str):
    if not re.fullmatch(r"[0-9a-f]{8}", job) or name not in ALLOWED:
        raise HTTPException(404)
    path = OUT / job / name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
