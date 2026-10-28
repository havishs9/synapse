"""Launch candidate jobs in parallel and stream their JSON-line stdout.

LocalLauncher runs each job as a subprocess on this machine (TRAINING_BACKEND=local).
SandboxLauncher would run them in Token Factory Sandboxes; our account has no spawn permission
(docs/VERIFICATION.md), so it checks first and the orchestrator falls back to local.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from backend import config

OnEvent = Callable[[dict], None]


class SandboxUnavailable(RuntimeError):
    pass


class LocalLauncher:
    name = "local"

    def __init__(self, max_parallel: int | None = None, timeout_s: int = 1800):
        self.max_parallel = max_parallel or max(2, (os.cpu_count() or 4) - 2)
        self.timeout_s = timeout_s

    def _run_one(self, job: dict, on_event: OnEvent) -> dict:
        out_dir = Path(job["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        job_path = out_dir / "job.json"
        job_path.write_text(json.dumps(job, indent=2))
        env = {**os.environ, "OMP_NUM_THREADS": "1", "TOKENIZERS_PARALLELISM": "false", "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen([sys.executable, "-m", "backend.sandbox.worker", str(job_path)],
                                cwd=config.ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        timer = threading.Timer(self.timeout_s, proc.kill)
        timer.start()
        result = {"cand": job["cand"], "status": "failed", "error": None}
        lines = []
        try:
            for line in proc.stdout:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                lines.append(ev)
                ev.setdefault("cand", job["cand"])
                on_event(ev)
                if ev.get("event") == "done":
                    result.update(status="done", **{k: ev[k] for k in ("primary", "metrics_path", "cost_per_1m_usd",
                                                                    "ms_per_item")})
                elif ev.get("event") == "error":
                    result["error"] = ev["error"]
                    result["traceback"] = ev.get("traceback")
            proc.wait()
        finally:
            timer.cancel()
        stderr = proc.stderr.read()
        (out_dir / "stderr.log").write_text(stderr[-20000:])
        if proc.returncode not in (0, None) and result["status"] != "done":
            if proc.returncode == -9:
                result.update(status="timeout", error=f"timed out after {self.timeout_s}s")
            result["error"] = result["error"] or stderr[-2000:]
            result["error_log"] = str(out_dir / "stderr.log")
        return result

    def run(self, jobs: list[dict], on_event: OnEvent) -> list[dict]:
        with ThreadPoolExecutor(max_workers=self.max_parallel) as ex:
            return list(ex.map(lambda j: self._run_one(j, on_event), jobs))


class SandboxLauncher(LocalLauncher):
    name = "sandbox"

    def __init__(self, **kw):
        super().__init__(**kw)
        try:
            from contree_sdk import ContreeSync
            info = ContreeSync().get_token_info()
        except Exception as exc:  # network or auth failure
            raise SandboxUnavailable(f"Sandboxes unreachable: {exc}") from exc
        if not (info.permissions.get("spawn") and info.permissions.get("import")):
            raise SandboxUnavailable("Sandboxes account lacks import/spawn permission (see docs/VERIFICATION.md)")
        raise SandboxUnavailable("Sandbox execution path is not implemented; permissions only became available "
                                 "after Phase 0. Use TRAINING_BACKEND=local.")


def get_launcher(emit_note: Callable[[str], None] | None = None) -> LocalLauncher:
    if config.training_backend() == "sandbox":
        try:
            return SandboxLauncher()
        except SandboxUnavailable as exc:
            if emit_note:
                emit_note(f"Sandboxes unavailable ({exc}); training locally instead")
    return LocalLauncher()
