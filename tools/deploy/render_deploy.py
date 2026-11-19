"""Создание сервиса на Render через API.

Нужен ключ: dashboard.render.com → Account Settings → API Keys → Create.
Запуск:  python tools/deploy/render_deploy.py --key rnd_xxx
Или:     RENDER_API_KEY=rnd_xxx python tools/deploy/render_deploy.py

Скрипт: находит ownerId, создаёт web service (Docker, free), ждёт деплой и печатает URL.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.render.com/v1"
REPO = "https://github.com/dkzver/pdf-to-plan"
BRANCH = "main"
NAME = "pdfplan"


def call(method: str, path: str, key: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json",
                                          "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        print(f"HTTP {exc.code}: {detail}", file=sys.stderr)
        raise


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("RENDER_API_KEY"))
    ap.add_argument("--name", default=NAME)
    ap.add_argument("--plan", default="free")
    ap.add_argument("--region", default="frankfurt")
    args = ap.parse_args()
    if not args.key:
        print("Нужен ключ: --key rnd_... или RENDER_API_KEY", file=sys.stderr)
        return 2

    owners = call("GET", "/owners?limit=1", args.key)
    owner = owners[0]["owner"] if isinstance(owners, list) else owners["owner"]
    owner_id = owner["id"]
    print(f"owner: {owner.get('name') or owner_id}")

    payload = {
        "type": "web_service",
        "name": args.name,
        "ownerId": owner_id,
        "repo": REPO,
        "branch": BRANCH,
        "autoDeploy": "yes",
        "serviceDetails": {
            "env": "docker",
            "plan": args.plan,
            "region": args.region,
            "healthCheckPath": "/",
            "envSpecificDetails": {
                "dockerContext": "./tools/pdfplan",
                "dockerfilePath": "./Dockerfile",
            },
        },
    }
    try:
        service = call("POST", "/services", args.key, payload)
    except urllib.error.HTTPError:
        print("Если ошибка про репозиторий — в Render не установлен GitHub App "
              "для dkzver/pdf-to-plan. Установите доступ и повторите.", file=sys.stderr)
        return 1

    svc = service.get("service", service)
    sid = svc["id"]
    url = svc.get("serviceDetails", {}).get("url") or svc.get("url")
    print(f"service id: {sid}")
    print(f"url: {url}")

    for _ in range(40):
        deploys = call("GET", f"/services/{sid}/deploys?limit=1", args.key)
        d = (deploys[0]["deploy"] if isinstance(deploys, list) else deploys["deploy"])
        status = d.get("status")
        print(f"deploy: {status}")
        if status in ("live", "build_failed", "canceled", "deactivated"):
            if status != "live":
                print(d.get("commit", {}).get("message", ""))
                return 1
            break
        time.sleep(15)

    print(f"готово: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
