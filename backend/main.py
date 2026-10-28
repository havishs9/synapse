"""FastAPI app: main chat, intake, builds, SSE progress, specialist panel, compare, API keys, improve.

The shared specialist server's public routes are mounted here too, as the documented fallback when the
Nebius Serverless endpoint isn't configured (SPECIALIST_ENDPOINT_URL empty).
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import threading
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend import config
from backend.demo_tasks import DEMO_TASKS
from backend.llm_client import LLMClient
from backend.orchestrator import Options, Orchestrator
from backend.schemas import TaskCard
from backend.sealed import is_sealed_path
from backend.serving import server as spec_server
from backend.serving.predictor import InputError
from backend.versions import registry

app = FastAPI(title="Synapse")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
app.include_router(spec_server.router)          # fallback serving: /health, /v1/specialists/...
_builds: dict[str, Orchestrator] = {}
_chat_llm = LLMClient(budget_usd=float("inf"))

SYSTEM = ("You are the main assistant in Synapse, an app that builds small, cheap specialist models for repetitive "
          "classification tasks and measures them honestly against you (NVIDIA Nemotron). Answer normally. If the user "
          "describes a repetitive task they want automated, say you can build a specialist and that you'll ask a few "
          "questions first. Be concise.")


# ---- app info ----------------------------------------------------------------------
@app.get("/api/app")
def app_info():
    return {"mode": config.app_mode(), "main_model": config.models()["main_chat_planner_teacher_baseline"]["display_name"],
            "demo_tasks": {k: f().task_name for k, f in DEMO_TASKS.items()},
            "specialist_endpoint": config.env("SPECIALIST_ENDPOINT_URL") or None,
            "replay_runs": recorded_runs()}


@app.get("/api/demo_tasks/{task_id}")
def demo_task(task_id: str):
    if task_id not in DEMO_TASKS:
        raise HTTPException(404, "Unknown demo task.")
    return DEMO_TASKS[task_id]().model_dump()


# ---- main chat ---------------------------------------------------------------------
class ChatIn(BaseModel):
    messages: list[dict]


@app.post("/api/chat")
async def chat(body: ChatIn):
    msgs = [{"role": "system", "content": SYSTEM}] + [m for m in body.messages if m.get("role") in ("user", "assistant")][-20:]
    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def worker():
        try:
            for chunk in _chat_llm.chat_stream("main_chat_planner_teacher_baseline", msgs):
                loop.call_soon_threadsafe(q.put_nowait, chunk)
        except Exception as exc:
            loop.call_soon_threadsafe(q.put_nowait, {"error": f"The main model didn't respond ({type(exc).__name__}). Try again."})
        loop.call_soon_threadsafe(q.put_nowait, None)

    threading.Thread(target=worker, daemon=True).start()

    async def gen():
        while (item := await q.get()) is not None:
            yield {"data": json.dumps(item)}
    return EventSourceResponse(gen())


# ---- builds and runs -----------------------------------------------------------------
class BuildIn(BaseModel):
    task_card: dict | None = None
    task_id: str | None = None
    profile: str = "full"          # "phase1" runs the hardcoded single-round pipeline


def recorded_runs() -> dict[str, str]:
    """Recorded demo runs per task (used by replay mode)."""
    out = {}
    for p in sorted(config.runs_dir().glob("*/run_state.json")):
        try:
            s = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        if s.get("status") == "done" and s.get("kind", "build") == "build" and (p.parent / "replay.ok").exists():
            out[s["task_id"]] = p.parent.name
    return out


@app.post("/api/builds")
def start_build(body: BuildIn):
    if body.task_card:
        card = TaskCard.model_validate(body.task_card)
    elif body.task_id in DEMO_TASKS:
        card = DEMO_TASKS[body.task_id]()
    else:
        raise HTTPException(400, "Send a task_card or a known task_id.")
    if config.app_mode() == "replay":
        run = recorded_runs().get(card.task_id)
        if not run:
            raise HTTPException(404, f"Replay mode: no recorded run for {card.task_id}.")
        return {"run_id": run, "replay": True}
    from backend.orchestrator import PHASE1
    orch = Orchestrator(card, options=PHASE1 if body.profile == "phase1" else Options())
    _builds[orch.run_id] = orch
    threading.Thread(target=orch.run, daemon=True).start()
    return {"run_id": orch.run_id, "replay": False}


def run_dir(run_id: str) -> Path:
    d = (config.runs_dir() / run_id).resolve()
    if d.parent != config.runs_dir() or not d.is_dir():
        raise HTTPException(404, "No such run.")
    return d


@app.get("/api/runs")
def runs():
    return registry.list_runs()


@app.get("/api/runs/{run_id}/state")
def run_state(run_id: str):
    p = run_dir(run_id) / "run_state.json"
    return json.loads(p.read_text()) if p.exists() else {"stage": "starting"}


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, replay: bool = False, speed: float = 1.0):
    """SSE: live runs stream as events are written; replay plays recorded events with their original timing."""
    d = run_dir(run_id)
    path = d / "events.jsonl"

    async def live():
        pos, idle = 0, 0
        while True:
            chunk = ""
            if path.exists():
                with path.open() as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                for line in chunk.splitlines():
                    if line.strip():
                        yield {"data": line}
                        if json.loads(line).get("kind") == "done":
                            return
            idle = 0 if chunk else idle + 1
            if idle > 3600 * 4:   # 1 hour without new events
                return
            await asyncio.sleep(0.25)

    async def play():
        events = [json.loads(l) for l in path.open() if l.strip()]
        prev = events[0]["ts"] if events else 0
        for e in events:
            await asyncio.sleep(min(max(e["ts"] - prev, 0) / max(speed, 0.01), 2.0))
            prev = e["ts"]
            yield {"data": json.dumps({**e, "replay": True})}

    return EventSourceResponse(play() if replay else live())


@app.get("/api/runs/{run_id}/files/{name:path}")
def run_file(run_id: str, name: str):
    d = run_dir(run_id)
    p = (d / name).resolve()
    if d not in p.parents or is_sealed_path(p) or not p.is_file():
        raise HTTPException(404, "File not available.")
    if p.suffix not in (".json", ".jsonl", ".md", ".log"):
        raise HTTPException(404, "Only JSON, Markdown and log files can be viewed.")
    if p.name in ("train.jsonl", "val.jsonl", "holdback.jsonl"):
        lines = p.read_text().splitlines()[:50]
        return PlainTextResponse("\n".join(lines) + f"\n... (first 50 of {sum(1 for _ in p.open())} rows)")
    return PlainTextResponse(p.read_text())


@app.get("/api/runs/{run_id}/report")
def report(run_id: str, fmt: str = "json"):
    d = run_dir(run_id)
    p = d / ("report_card.md" if fmt == "md" else "report_card.json")
    if not p.exists():
        raise HTTPException(404, "Report card not ready yet.")
    return FileResponse(p, filename=f"{run_id}-report.{'md' if fmt == 'md' else 'json'}")


# ---- specialists ----------------------------------------------------------------------
def _spec(sid: str):
    if not registry.path(sid).exists():
        raise HTTPException(404, f"No specialist '{sid}'.")
    return registry.load(sid)


def _version_view(v, rec) -> dict:
    meta = registry.bundle_meta(v.specialist_id, rec.version)
    rd = config.runs_dir() / rec.run_id
    rc = json.loads((rd / "report_card.json").read_text()) if (rd / "report_card.json").exists() else None
    return {**rec.model_dump(), "bundle": meta, "report": rc}


@app.get("/api/specialists")
def specialists():
    out = []
    for v in registry.list_specialists():
        live = registry.live(v)
        out.append({"specialist_id": v.specialist_id, "display_name": v.display_name, "color": v.color,
                    "monogram": v.monogram, "task_id": v.task_id, "live_version": live.version if live else None,
                    "versions": len(v.versions)})
    return out


@app.get("/api/specialists/{sid}")
def specialist(sid: str):
    v = _spec(sid)
    live = registry.live(v)
    return {"specialist_id": sid, "display_name": v.display_name, "color": v.color, "monogram": v.monogram,
            "task_id": v.task_id, "api_route": v.api_route,
            "api_base": config.env("SPECIALIST_ENDPOINT_URL") or None,
            "has_key": any(k.revoked is None for k in v.api_keys),
            "keys": [{"key_id": k.key_id, "created": k.created, "revoked": k.revoked} for k in v.api_keys],
            "live": _version_view(v, live) if live else None,
            "versions": [_version_view(v, r) for r in sorted(v.versions, key=lambda r: -r.version)]}


class PredictIn(BaseModel):
    input: str
    version: int | None = None


def _local_predict(sid: str, texts: list[str], version: int | None = None) -> dict:
    v = _spec(sid)
    ver = version or (registry.live(v).version if registry.live(v) else None)
    if ver is None:
        raise HTTPException(503, "This specialist has no live version yet.")
    t0 = time.perf_counter()
    try:
        preds = spec_server.predictor(sid, ver).predict(texts)
    except InputError as exc:
        raise HTTPException(422, str(exc))
    return {"version": ver, "predictions": preds, "wall_ms": (time.perf_counter() - t0) * 1000}


@app.post("/api/specialists/{sid}/predict")
def panel_predict(sid: str, body: PredictIn):
    out = _local_predict(sid, [body.input], body.version)
    return {"version": out["version"], **out["predictions"][0], "wall_ms": out["wall_ms"]}


@app.post("/api/specialists/{sid}/predict_batch")
async def panel_batch(sid: str, file: UploadFile = File(...)):
    raw = (await file.read()).decode("utf-8", errors="replace")
    v = _spec(sid)
    meta = registry.bundle_meta(sid, registry.live(v).version)
    if meta["input_type"] == "log_window":
        texts = [json.loads(l)["text"] for l in raw.splitlines() if l.strip()] if file.filename.endswith(".jsonl") \
            else [w for w in raw.split("\n\n") if w.strip()]
    else:
        rows = list(csv.reader(io.StringIO(raw)))
        if rows and len(rows[0]) > 1:
            header = [h.lower() for h in rows[0]]
            col = next((i for i, h in enumerate(header) if h in ("description", "text", "award_description", "input")), 0)
            texts = [r[col] for r in rows[1:] if len(r) > col and r[col].strip()]
        else:
            texts = [r[0] for r in rows if r and r[0].strip()]
    if not texts:
        raise HTTPException(422, "No records found. Upload a CSV with one record per row (a 'description' column), "
                                 "or blank-line-separated log windows.")
    if len(texts) > 5000:
        raise HTTPException(422, f"{len(texts)} records; the batch limit is 5,000.")
    out = _local_predict(sid, texts)
    return {"version": out["version"], "rows": [{"input": t, **p} for t, p in zip(texts, out["predictions"])],
            "wall_ms": out["wall_ms"]}


@app.post("/api/specialists/{sid}/keys")
def regenerate_key(sid: str):
    """Revokes existing keys and returns a new plain key once. Only its hash is stored."""
    v = _spec(sid)
    key = registry.create_key(v)
    _reload_remote(sid)
    return {"api_key": key, "note": "Copy it now; it won't be shown again."}


def _reload_remote(sid: str):
    url, token = config.env("SPECIALIST_ENDPOINT_URL"), config.env("SPECIALIST_ADMIN_TOKEN")
    if url and token:
        try:
            from backend.serving.sync import push_specialist
            push_specialist(sid)
        except Exception:
            pass


@app.post("/api/specialists/{sid}/rollback")
def rollback(sid: str):
    v = _spec(sid)
    try:
        target = registry.rollback(v)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    _reload_remote(sid)
    return {"live_version": target.version}


# ---- static frontend ------------------------------------------------------------------
_dist = config.ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "v1/", "admin/")):
            raise HTTPException(404)
        f = _dist / path
        return FileResponse(f if path and f.is_file() else _dist / "index.html")
