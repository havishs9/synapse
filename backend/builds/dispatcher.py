"""Dispatcher loop (runs inside the API server when the database is configured).

Every POLL_S it marks builds with a stale heartbeat as failed, then claims queued builds while the caps allow
(backend/builds/queue.py) and launches one worker per build:
  TRAINING_BACKEND=local  a thread in this process (the laptop, or the endpoint for small demos)
  TRAINING_BACKEND=jobs   one Nebius AI Job per build (`nebius ai job create`), see deploy/jobs/worker_bootstrap.sh
Jobs are checked every JOB_POLL_S: a job that ended while its build still shows running marks the build failed,
and a cancel requested before the worker started cancels the job. Worker spend is capped by
WORKER_TOTAL_BUDGET_USD (hours on AI Jobs x the worker preset's hourly rate from config/pricing.yaml).
"""
from __future__ import annotations

import json
import shlex
import subprocess
import threading
import time
import uuid
from pathlib import Path

from backend import config
from backend.builds import queue

POLL_S = 3.0
JOB_POLL_S = 30.0
ROOT = config.ROOT
# Settings a worker job needs; secrets come from this server's environment and are passed as job env vars.
JOB_ENV = ["NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_PROJECT_ID", "HF_TOKEN", "TAVILY_API_KEY", "API_KEY_PEPPER",
           "SUPABASE_URL", "SUPABASE_DB_URL", "OBJECT_STORAGE_ENDPOINT", "OBJECT_STORAGE_REGION", "OBJECT_STORAGE_BUCKET",
           "OBJECT_STORAGE_ACCESS_KEY", "OBJECT_STORAGE_SECRET_KEY", "CREDIT_BUDGET_USD", "MAX_REPAIR_ROUNDS",
           "DEMO_MONTHLY_VOLUME", "SANDBOX_BASE_URL"]

_thread: threading.Thread | None = None
_stop = threading.Event()


def backend() -> str:
    return config.training_backend()


def enabled() -> bool:
    from backend.storage import db
    return db.enabled() and config.env("DISPATCHER", "on") != "off" and config.app_mode() != "replay"


# ---- Nebius AI Jobs -------------------------------------------------------------------------
def _nebius() -> list[str]:
    cli = config.env("NEBIUS_CLI") or str(Path.home() / ".nebius" / "bin" / "nebius")
    profile = config.env("NEBIUS_CLI_PROFILE")
    return [cli] + (["--profile", profile] if profile else [])


def worker_spec() -> dict:
    """Platform, preset, disk and hourly rate of a worker job (config/pricing.yaml `ai_jobs`)."""
    p = config.pricing()
    jobs, cpu = p["ai_jobs"], p["serverless_cpu"]
    preset = cpu["presets"][jobs["preset"]]
    hourly = preset["vcpus"] * cpu["vcpu_hour"] + preset["ram_gib"] * cpu["ram_gib_hour"] + \
        jobs["disk_gib"] * cpu["network_ssd_gib_month"] / cpu["hours_per_month"]
    return {"platform": jobs.get("platform", cpu["platform"]), "preset": jobs["preset"], "disk_gib": jobs["disk_gib"],
            "timeout": jobs["timeout"], "hourly_usd": hourly}


def worker_spend_usd() -> float:
    return queue.worker_hours("job:") * worker_spec()["hourly_usd"]


def job_command(run_id: str) -> list[str]:
    spec = worker_spec()
    env = {k: config.env(k) for k in JOB_ENV if config.env(k)}
    env.update(SYNAPSE_RUN_ID=run_id, TRAINING_BACKEND="local", REGISTRY_BACKEND="postgres", APP_MODE="live",
               SYNAPSE_REPO_TARBALL=config.env("SYNAPSE_REPO_TARBALL",
                                               "https://github.com/havishs9/synapse/archive/refs/heads/main.tar.gz"))
    cmd = _nebius() + [
        "ai", "job", "create", "--name", f"synapse-build-{run_id[-40:]}".lower(),
        "--image", config.env("WORKER_IMAGE", "python:3.12-slim"),
        "--inject-file", f"{ROOT / 'deploy' / 'jobs' / 'worker_bootstrap.sh'}:/worker_bootstrap.sh",
        "--container-command", "bash /worker_bootstrap.sh",
        "--platform", spec["platform"], "--preset", spec["preset"], "--disk-size", f"{spec['disk_gib']}Gi",
        "--timeout", spec["timeout"], "--restart-policy", "never", "--async", "--format", "json"]
    if config.env("NEBIUS_PROJECT_ID", "").startswith("project-"):
        cmd += ["--parent-id", config.env("NEBIUS_PROJECT_ID")]
    image, registry_host = cmd[cmd.index("--image") + 1], (config.env("NEBIUS_REGISTRY") or "").split("/")[0]
    if registry_host and image.startswith(registry_host) and config.env("NEBIUS_REGISTRY_TOKEN"):
        cmd += ["--registry-username", "iam", "--registry-password", config.env("NEBIUS_REGISTRY_TOKEN")]
    for k, v in env.items():
        cmd += ["--env", f"{k}={v}"]
    return cmd


def launch_job(run_id: str) -> str:
    out = subprocess.run(job_command(run_id), capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        # The CLI echoes the request on some errors; never log it (it contains the env values).
        raise RuntimeError(f"nebius ai job create failed (exit {out.returncode}): "  # last line only
                           f"{(out.stderr or out.stdout).strip().splitlines()[-1][:300] if (out.stderr or out.stdout) else ''}")
    d = json.loads(out.stdout)
    job_id = d.get("resource_id") or (d.get("metadata") or {}).get("id") or d.get("id")
    if not job_id:
        raise RuntimeError("nebius ai job create returned no job id")
    return job_id


def job_state(job_id: str) -> str | None:
    out = subprocess.run(_nebius() + ["ai", "job", "get", job_id, "--format", "json"], capture_output=True,
                         text=True, timeout=60)
    if out.returncode != 0:
        return None
    return (json.loads(out.stdout).get("status") or {}).get("state")


def cancel_job(job_id: str) -> None:
    subprocess.run(_nebius() + ["ai", "job", "cancel", job_id], capture_output=True, text=True, timeout=60)


# ---- loop -----------------------------------------------------------------------------------
def _launch(row: dict) -> None:
    run_id = row["run_id"]
    if backend() == "jobs":
        if worker_spend_usd() >= float(config.env("WORKER_TOTAL_BUDGET_USD", "6")):
            queue.finish(run_id, "failed", "The build-worker budget (WORKER_TOTAL_BUDGET_USD) is used up.")
            return
        try:
            job_id = launch_job(run_id)
        except Exception as exc:
            queue.finish(run_id, "failed", f"Couldn't start a build worker: {exc}")
            return
        queue.set_worker(run_id, f"job:{job_id}")
        print(f"[dispatcher] {run_id}: started AI Job {job_id}", flush=True)
        return
    from backend.builds.worker import run_build
    threading.Thread(target=run_build, args=(run_id,), daemon=True, name=f"build-{run_id}").start()


_JOB_DONE = {"SUCCEEDED", "FAILED", "CANCELLED", "COMPLETED", "ERROR", "DELETED", "STOPPED"}


def _check_jobs() -> None:
    for row in queue.running("job:"):
        job_id = row["worker_id"][len("job:"):]
        state = (job_state(job_id) or "").upper()
        if row["cancel_requested"] and row["stage"] is None and state not in _JOB_DONE:
            cancel_job(job_id)
            queue.finish(row["run_id"], "cancelled", "Cancelled before the worker started")
        elif state in _JOB_DONE:
            queue.finish(row["run_id"], "failed", f"The build worker ended ({state.lower()}) before reporting a result.")


def tick() -> None:
    for run_id in queue.reap_stale():
        print(f"[dispatcher] {run_id}: no heartbeat, marked failed", flush=True)
    while (row := queue.claim(f"{backend()}:{uuid.uuid4().hex[:6]}")) is not None:
        _launch(row)


def _loop() -> None:
    last_jobs = 0.0
    while not _stop.wait(POLL_S):
        try:
            tick()
            if backend() == "jobs" and time.time() - last_jobs > JOB_POLL_S:
                last_jobs = time.time()
                _check_jobs()
        except Exception as exc:
            print(f"[dispatcher] {type(exc).__name__}: {exc}", flush=True)


def start() -> bool:
    global _thread
    if not enabled() or (_thread and _thread.is_alive()):
        return False
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="dispatcher")
    _thread.start()
    print(f"[dispatcher] started ({backend()} workers)", flush=True)
    return True


def stop() -> None:
    _stop.set()


def describe_job_command(run_id: str) -> str:
    """The job command with every env value masked (for logs and docs)."""
    cmd = job_command(run_id)
    def mask(i: int, a: str) -> str:
        if i and cmd[i - 1] == "--env":
            return a.split("=", 1)[0] + "=***"
        return "***" if i and cmd[i - 1] == "--registry-password" else a
    return " ".join(shlex.quote(mask(i, a)) for i, a in enumerate(cmd))
