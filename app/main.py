from __future__ import annotations

import json
import logging
import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import STATIC_DIR, TEMPLATE_DIR, get_settings
from app.scheduler.task import WorkflowEngine
from app.storage.db import Database
from app.utils.logger import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

settings = get_settings()
db = Database()
engine = WorkflowEngine(db=db)

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@app.on_event("startup")
async def startup_event() -> None:
    logger.info("Application startup complete")
    db.log_event("info", "Application started")
    app.state.stop_event = asyncio.Event()
    app.state.poller_task = asyncio.create_task(engine.polling_loop(app.state.stop_event))


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    tasks = db.list_tasks(limit=20)
    events = db.recent_events(limit=10)
    metrics = {
        "task_count": len(db.list_tasks(limit=1000)),
        "failed_count": len([t for t in db.list_tasks(limit=1000) if t["status"] in {"failed", "analysis_done"} and not t["feishu_sent"]]),
        "notified_count": len([t for t in db.list_tasks(limit=1000) if t["feishu_sent"]]),
    }
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "settings": settings,
            "tasks": tasks,
            "events": events,
            "metrics": metrics,
        },
    )


@app.get("/tasks", response_class=HTMLResponse)
async def task_list(request: Request):
    tasks = db.list_tasks(limit=200)
    return templates.TemplateResponse(
        "tasks.html",
        {
            "request": request,
            "settings": settings,
            "tasks": tasks,
        },
    )


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: int):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    attachments = db.list_attachments(task_id)
    result = {}
    if task.get("result_json"):
        try:
            result = json.loads(task["result_json"])
        except Exception:
            result = {"raw": task["result_json"]}
    return templates.TemplateResponse(
        "task_detail.html",
        {
            "request": request,
            "settings": settings,
            "task": task,
            "attachments": attachments,
            "result": result,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": settings,
            "engineer_map": settings.engineer_map(),
        },
    )


@app.on_event("shutdown")
async def shutdown_event() -> None:
    stop_event = getattr(app.state, "stop_event", None)
    if stop_event is not None:
        stop_event.set()
    poller_task = getattr(app.state, "poller_task", None)
    if poller_task is not None:
        try:
            await poller_task
        except Exception:
            pass


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
    }


@app.get("/api/tasks")
async def api_tasks(limit: int = 100):
    return {"items": db.list_tasks(limit=limit)}


@app.get("/api/events")
async def api_events(limit: int = 100):
    return {"items": db.recent_events(limit=limit)}


@app.post("/api/run-once")
async def api_run_once():
    results = await asyncio.to_thread(engine.fetch_and_process_once)
    return {
        "count": len(results),
        "items": [r.__dict__ for r in results],
    }


@app.post("/api/test-feishu")
async def api_test_feishu(message: str = Form(...)):
    result = engine.feishu.send_text(message)
    return {
        "ok": result.ok,
        "status_code": result.status_code,
        "response_text": result.response_text,
    }


@app.get("/downloads/{path:path}")
async def download_file(path: str):
    file_path = Path(__file__).resolve().parents[1] / "downloads" / path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(file_path))


@app.post("/api/retry/{task_id}")
async def retry_task(task_id: int):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.update_task_status(task_id, "retrying", error=None)
    return {"ok": True, "task_id": task_id}


@app.get("/favicon.ico")
async def favicon():
    raise HTTPException(status_code=404)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled application error")
    return JSONResponse(status_code=500, content={"detail": str(exc)})
