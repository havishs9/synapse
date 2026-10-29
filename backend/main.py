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
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend import config
from backend.auth import User, current_user, require_edit, require_view, uid
from backend.builds import api as builds_api
from backend.builds import dispatcher, queue as build_queue
from backend.demo_tasks import DEMO_TASKS
from backend.llm_client import LLMClient
from backend.orchestrator import Options, Orchestrator
from backend.schemas import TaskCard
from backend.sealed import is_sealed_path
from backend.serving import server as spec_server
from backend.serving.predictor import InputError
from backend.storage import objects
from backend.storage.objects import StorageError
from backend.versions import registry

@asynccontextmanager
async def _lifespan(_app):
    dispatcher.start()      # only with a database (build queue) and outside replay mode
    yield
    dispatcher.stop()


app = FastAPI(title="Synapse", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins(), allow_methods=["*"], allow_headers=["*"])
app.include_router(spec_server.router)          # fallback serving: /health, /v1/specialists/...
app.include_router(builds_api.router)           # GET /api/builds, cancel, retry (TEAM_PLAN §1)
_builds: dict[str, Orchestrator] = {}
_chat_llm = LLMClient(budget_usd=float("inf"))

SYSTEM = ("You are the main assistant in Synapse, an app that builds small, cheap specialist models for repetitive "
          "classification tasks and measures them honestly against you (NVIDIA Nemotron). Answer normally. If the user "
          "describes a repetitive task they want automated, say you can build a specialist and that you'll ask a few "
          "questions first. Be concise.")


# ---- public demo spend guard -----------------------------------------------------------
_guard = {"day": "", "spend": 0.0}


def demo_guard(extra_usd: float = 0.0) -> None:
    """Cap cloud LLM spend from interactive use (chat, compare, explanations) per day on a public deployment."""
    day = time.strftime("%Y-%m-%d")
    if _guard["day"] != day:
        _guard.update(day=day, spend=0.0)
    _guard["spend"] += extra_usd
    cap = float(config.env("DEMO_DAILY_BUDGET_USD", "3"))
    used = _chat_llm.spend.spent_usd + spec_server._get_llm().spend.spent_usd
    if used >= cap:
        raise HTTPException(429, f"The demo's daily LLM budget (${cap:.2f}) is used up. Specialist predictions "
                                 "still work; chat, compare and explanations resume tomorrow.")


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
    demo_guard()
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
def start_build(body: BuildIn, user: User | None = Depends(current_user)):
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
    if dispatcher.enabled():      # queued: a dispatcher starts it when a worker slot is free
        from backend.orchestrator import new_run_id
        budget = min(config.credit_budget_usd(), card.build_budget_usd or float("inf"))
        b = build_queue.enqueue(new_run_id(card.task_id), card.model_dump(mode="json"), {"profile": body.profile},
                                uid(user), budget)
        return {"run_id": b["run_id"], "status": b["status"], "replay": False}
    from backend.orchestrator import PHASE1
    orch = Orchestrator(card, options=PHASE1 if body.profile == "phase1" else Options(), user_id=uid(user))
    _builds[orch.run_id] = orch
    threading.Thread(target=orch.run, daemon=True).start()
    return {"run_id": orch.run_id, "status": "running", "replay": False}


def run_dir(run_id: str, user: User | None = None) -> Path:
    """A run folder the caller may read: their own builds, and runs with no owner (recorded demo runs)."""
    d = (config.runs_dir() / run_id).resolve()
    if d.parent != config.runs_dir():
        raise HTTPException(404, "No such run.")
    known, owner = registry.run_owner(run_id)
    if known and owner is not None and owner != uid(user):
        raise HTTPException(404, "No such run.")
    if not d.is_dir():
        _fetch_run(run_id, owner, d)
    return d


_run_fetch_lock = threading.Lock()


def _fetch_run(run_id: str, owner: str | None, d: Path) -> None:
    """A run this server didn't execute (another server or a build worker): fetch its folder from Object Storage."""
    if not objects.enabled():
        raise HTTPException(404, "No such run.")
    with _run_fetch_lock:
        if d.is_dir():
            return
        try:
            objects.download_dir(objects.run_prefix(owner, run_id), d)
        except StorageError:
            raise HTTPException(404, "No such run.")


@app.get("/api/runs")
def runs(user: User | None = Depends(current_user)):
    return registry.list_runs(uid(user))


@app.get("/api/runs/{run_id}/state")
def run_state(run_id: str, user: User | None = Depends(current_user)):
    qb = _queued_build(run_id, user)
    local = config.runs_dir() / run_id / "run_state.json"
    if qb and qb["status"] in ("queued", "running") and not local.exists():
        return {**build_queue.view(qb), "started": qb["started_at"], "updated": qb["updated_at"]}   # on a worker
    p = run_dir(run_id, user) / "run_state.json"
    return json.loads(p.read_text()) if p.exists() else {"stage": "starting"}


def _queued_build(run_id: str, user: User | None) -> dict | None:
    """The builds row of a queued/worker build the caller may see (None without a database or row)."""
    if not dispatcher.enabled():
        return None
    row = build_queue.get(run_id)
    if row and row["user_id"] not in (None, uid(user)):
        raise HTTPException(404, "No such run.")
    return row


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, replay: bool = False, speed: float = 1.0, after: int = 0,
                     user: User | None = Depends(current_user)):
    """SSE: live runs stream as events are written; replay plays recorded events with their original timing.
    Every connection starts from the first event; `after=n` skips the first n (reconnects).
    Builds from the queue stream from build_events (the worker may run on another machine)."""
    qb = None if replay else _queued_build(run_id, user)
    if qb is not None:
        return EventSourceResponse(_db_events(run_id, after))
    d = run_dir(run_id, user)
    path = d / "events.jsonl"

    async def live():
        pos, idle, seen = 0, 0, 0
        while True:
            chunk = ""
            if path.exists():
                with path.open("rb") as f:
                    f.seek(pos)
                    raw = f.read()
                raw = raw[:raw.rfind(b"\n") + 1]          # a line still being written is read next time
                pos += len(raw)
                chunk = raw.decode()
                for line in chunk.splitlines():
                    if line.strip():
                        seen += 1
                        if seen > after:
                            yield {"data": line}
                        if json.loads(line).get("kind") == "done":
                            return
            idle = 0 if chunk else idle + 1
            if idle > 3600 * 4:   # 1 hour without new events
                return
            await asyncio.sleep(0.25)

    async def play():
        events = [json.loads(l) for l in path.open() if l.strip()][max(after, 0):]
        prev = events[0]["ts"] if events else 0
        for e in events:
            await asyncio.sleep(min(max(e["ts"] - prev, 0) / max(speed, 0.01), 2.0))
            prev = e["ts"]
            yield {"data": json.dumps({**e, "replay": True})}

    return EventSourceResponse(play() if replay else live())


async def _db_events(run_id: str, after: int):
    seen, idle = max(after, 0), 0
    while True:
        rows = await asyncio.to_thread(build_queue.events_after, run_id, seen)
        for seq, e in rows:
            seen = seq
            yield {"data": json.dumps(e)}
            if e.get("kind") == "done":
                return
        if not rows:
            idle += 1
            if idle % 20 == 0:      # every ~20 s: stop if the build ended without a done event
                b = await asyncio.to_thread(build_queue.get, run_id)
                if b and b["status"] in ("failed", "cancelled") and not build_queue.events_after(run_id, seen):
                    yield {"data": json.dumps({"ts": time.time(), "agent": "Orchestrator", "stage": "end",
                                               "message": b["message"], "data_ref": None,
                                               "spend_usd": b["spend_usd"], "kind": "done",
                                               "data": {"status": b["status"]}})}
                    return
            if idle > 4 * 3600:
                return
        else:
            idle = 0
        await asyncio.sleep(1.0)


@app.get("/api/runs/{run_id}/files/{name:path}")
def run_file(run_id: str, name: str, user: User | None = Depends(current_user)):
    d = run_dir(run_id, user)
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
def report(run_id: str, fmt: str = "json", user: User | None = Depends(current_user)):
    d = run_dir(run_id, user)
    p = d / ("report_card.md" if fmt == "md" else "report_card.json")
    if not p.exists():
        raise HTTPException(404, "Report card not ready yet.")
    return FileResponse(p, filename=f"{run_id}-report.{'md' if fmt == 'md' else 'json'}")


# ---- specialists ----------------------------------------------------------------------
def _spec(sid: str, user: User | None = None):
    if not registry.exists(sid):
        raise HTTPException(404, f"No specialist '{sid}'.")
    v = registry.load(sid)
    require_view(v, user)
    return v


def _version_view(v, rec) -> dict:
    try:
        meta = registry.bundle_meta(v.specialist_id, rec.version)
    except StorageError:
        meta = None
    rd = config.runs_dir() / rec.run_id
    rc = json.loads((rd / "report_card.json").read_text()) if (rd / "report_card.json").exists() else None
    return {**rec.model_dump(), "bundle": meta, "report": rc}


@app.get("/api/specialists")
def specialists(user: User | None = Depends(current_user)):
    out = []
    for v in registry.list_specialists(uid(user)):
        live = registry.live(v)
        out.append({"specialist_id": v.specialist_id, "display_name": v.display_name, "color": v.color,
                    "monogram": v.monogram, "task_id": v.task_id, "live_version": live.version if live else None,
                    "versions": len(v.versions)})
    return out


@app.get("/api/specialists/{sid}")
def specialist(sid: str, user: User | None = Depends(current_user)):
    v = _spec(sid, user)
    live = registry.live(v)
    mine = [k for k in v.api_keys if k.user_id == uid(user)]       # each caller sees only their own keys
    return {"specialist_id": sid, "display_name": v.display_name, "color": v.color, "monogram": v.monogram,
            "task_id": v.task_id, "api_route": v.api_route,
            "api_base": config.env("SPECIALIST_ENDPOINT_URL") or None,
            "has_key": any(k.revoked is None for k in mine), "owned": v.user_id is not None and v.user_id == uid(user),
            "keys": [{"key_id": k.key_id, "created": k.created, "revoked": k.revoked} for k in mine],
            "live": _version_view(v, live) if live else None,
            "versions": [_version_view(v, r) for r in sorted(v.versions, key=lambda r: -r.version)]}


class PredictIn(BaseModel):
    input: str
    version: int | None = None
    explain: bool = False


def _local_predict(sid: str, texts: list[str], version: int | None = None, explain: bool = False,
                   user: User | None = None) -> dict:
    v = _spec(sid, user)
    ver = version or (registry.live(v).version if registry.live(v) else None)
    if ver is None:
        raise HTTPException(503, "This specialist has no live version yet.")
    t0 = time.perf_counter()
    try:
        preds = spec_server.predictor(sid, ver).predict(texts, explain=explain)
    except InputError as exc:
        raise HTTPException(422, str(exc))
    return {"version": ver, "predictions": preds, "wall_ms": (time.perf_counter() - t0) * 1000}


@app.post("/api/specialists/{sid}/predict")
def panel_predict(sid: str, body: PredictIn, user: User | None = Depends(current_user)):
    if body.explain:
        demo_guard()
    out = _local_predict(sid, [body.input], body.version, body.explain, user)
    return {"version": out["version"], **out["predictions"][0], "wall_ms": out["wall_ms"]}


@app.post("/api/specialists/{sid}/predict_batch")
async def panel_batch(sid: str, file: UploadFile = File(...), user: User | None = Depends(current_user)):
    raw = (await file.read()).decode("utf-8", errors="replace")
    v = _spec(sid, user)
    if registry.live(v) is None:
        raise HTTPException(503, "This specialist has no live version yet.")
    try:
        meta = registry.bundle_meta(sid, registry.live(v).version)
    except StorageError as exc:
        raise HTTPException(503, f"The model can't be loaded right now ({exc}).")
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
    out = _local_predict(sid, texts, user=user)
    return {"version": out["version"], "rows": [{"input": t, **p} for t, p in zip(texts, out["predictions"])],
            "wall_ms": out["wall_ms"]}


@app.post("/api/specialists/{sid}/keys")
def regenerate_key(sid: str, user: User | None = Depends(current_user)):
    """Revokes the caller's existing keys for this specialist and returns a new plain key once. Only its hash is
    stored. On a demo specialist every user has their own key, so nobody can revoke someone else's."""
    v = _spec(sid, user)
    key = registry.create_key(v, user_id=uid(user))
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
def rollback(sid: str, user: User | None = Depends(current_user)):
    v = _spec(sid, user)
    require_edit(v, user)
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
