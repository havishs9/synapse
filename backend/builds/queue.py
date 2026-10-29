"""Build queue on the Postgres `builds` table (docs/TEAM_PLAN.md §2.3).

queued -> running (claimed by a dispatcher with FOR UPDATE SKIP LOCKED, under the concurrency caps) ->
done | failed | cancelled. Workers heartbeat while they run and write their events to build_events; a build
whose heartbeat goes stale is marked failed. Cancel is a flag the worker reads with its heartbeat.
"""
from __future__ import annotations

import json

from fastapi import HTTPException

from backend import config
from backend.storage import db as pg

COLUMNS = ("run_id, user_id::text as user_id, kind, task_id, task_name, status, stage, round, n_rounds, "
           "spend_usd::float8 as spend_usd, budget_usd::float8 as budget_usd, message, specialist_id, version, "
           "deployed, cancel_requested, attempts, worker_id, "
           "extract(epoch from created_at)::float8 as created_at, extract(epoch from updated_at)::float8 as updated_at, "
           "extract(epoch from started_at)::float8 as started_at, extract(epoch from finished_at)::float8 as finished_at, "
           "extract(epoch from heartbeat_at)::float8 as heartbeat_at")
CONTRACT = ("run_id", "task_id", "task_name", "status", "stage", "round", "n_rounds", "spend_usd", "budget_usd",
            "created_at", "updated_at", "message", "specialist_id", "version", "deployed", "kind")
STARTUP_GRACE_S = 30 * 60     # a worker installing dependencies sends no heartbeat yet (pre-built image: step 4)
HEARTBEAT_STALE_S = 3 * 60
_LOCK_KEY = 7351_2026         # pg advisory lock serializing claims across dispatchers


def _int(name: str, default: int) -> int:
    return int(config.env(name, str(default)))


def view(row: dict) -> dict:
    """The builds-list contract shape (TEAM_PLAN §1)."""
    return {k: row.get(k) for k in CONTRACT}


def get(run_id: str) -> dict | None:
    with pg.conn() as c:
        return c.execute(f"select {COLUMNS} from builds where run_id = %s", (run_id,)).fetchone()


def task_card(run_id: str) -> tuple[dict, dict]:
    with pg.conn() as c:
        r = c.execute("select task_card, options from builds where run_id = %s", (run_id,)).fetchone()
    if not r:
        raise KeyError(run_id)
    return r["task_card"], r["options"]


def list_for(user_id: str | None) -> list[dict]:
    """Builds of `user_id` plus builds with no owner (started without sign-in)."""
    with pg.conn() as c:
        rows = c.execute(f"select {COLUMNS} from builds where user_id is null or user_id = %s "
                         "order by created_at desc limit 200", (user_id,)).fetchall()
    return [view(r) for r in rows]


def enqueue(run_id: str, card: dict, options: dict, user_id: str | None, budget_usd: float) -> dict:
    """Add a build to the queue, enforcing the per-user daily build cap (MAX_BUILDS_PER_USER_PER_DAY)."""
    cap = _int("MAX_BUILDS_PER_USER_PER_DAY", 3)
    with pg.conn() as c:
        # Callers without sign-in share one allowance (user_id null), so an open deployment stays capped.
        mine = c.execute("""select count(*) filter (where kind = 'build' and status <> 'cancelled') as n,
                                   coalesce(sum(spend_usd), 0)::float8 as spend
                            from builds where user_id is not distinct from %s
                              and created_at > now() - interval '24 hours'""", (user_id,)).fetchone()
        if mine["n"] >= cap:
            raise HTTPException(429, f"{'You have' if user_id else 'Visitors without sign-in have'} started "
                                     f"{mine['n']} builds in the last 24 hours (limit {cap}). Try again tomorrow.")
        allday = c.execute("select coalesce(sum(spend_usd), 0)::float8 as s from builds "
                           "where created_at > now() - interval '24 hours'").fetchone()["s"]
        total = c.execute("select coalesce(sum(spend_usd), 0)::float8 as s from builds").fetchone()["s"]
        for spent, limit, what in (
                (mine["spend"], float(config.env("USER_DAILY_BUILD_BUDGET_USD", "2.5")), "your daily build budget"),
                (allday, float(config.env("GLOBAL_DAILY_BUILD_BUDGET_USD", "5")), "today's build budget for all users"),
                (total, float(config.env("TOKEN_FACTORY_TOTAL_BUDGET_USD", "17")), "the demo's total build budget")):
            if spent >= limit:
                raise HTTPException(429, f"Builds are paused: {what} (${limit:.2f}) is used up. "
                                         "Recorded demo runs still work.")
        c.execute("""insert into builds (run_id, user_id, kind, task_id, task_name, task_card, options, status,
                                         budget_usd, message)
                     values (%s, %s, %s, %s, %s, %s, %s, 'queued', %s, 'Waiting for a free worker')""",
                  (run_id, user_id, options.get("kind", "build"), card["task_id"], card["task_name"],
                   json.dumps(card), json.dumps(options), budget_usd))
    return view(get(run_id))


def claim(worker_kind: str, run_id_like: str = "%") -> dict | None:
    """Claim the oldest queued build that fits under the caps: MAX_CONCURRENT_BUILDS overall (Token Factory's
    rate limit is shared) and MAX_CONCURRENT_BUILDS_PER_USER. Returns the claimed row or None."""
    total, per_user = _int("MAX_CONCURRENT_BUILDS", 2), _int("MAX_CONCURRENT_BUILDS_PER_USER", 1)
    with pg.conn() as c:
        c.execute("select pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
        running = c.execute("select count(*) as n from builds where status = 'running'").fetchone()["n"]
        if running >= total:
            return None
        row = c.execute("""
            select run_id from builds b
            where status = 'queued' and run_id like %s
              and (b.user_id is null or (select count(*) from builds r where r.status = 'running'
                                         and r.user_id = b.user_id) < %s)
            order by created_at for update skip locked limit 1""", (run_id_like, per_user)).fetchone()
        if not row:
            return None
        c.execute("""update builds set status = 'running', started_at = now(), heartbeat_at = now(),
                     attempts = attempts + 1, worker_id = %s, message = 'Starting a worker', updated_at = now()
                     where run_id = %s""", (worker_kind, row["run_id"]))
    return get(row["run_id"])


def set_worker(run_id: str, worker_id: str) -> None:
    with pg.conn() as c:
        c.execute("update builds set worker_id = %s, updated_at = now() where run_id = %s", (worker_id, run_id))


def heartbeat(run_id: str, **fields) -> bool:
    """Record progress (stage, round, n_rounds, spend_usd, message); returns True if a cancel was requested."""
    allowed = {k: v for k, v in fields.items() if k in ("stage", "round", "n_rounds", "spend_usd", "message")}
    sets = "".join(f", {k} = %({k})s" for k in allowed)
    with pg.conn() as c:
        r = c.execute(f"update builds set heartbeat_at = now(), updated_at = now(){sets} "
                      "where run_id = %(run_id)s and status = 'running' returning cancel_requested",
                      {**allowed, "run_id": run_id}).fetchone()
    return bool(r and r["cancel_requested"])


def finish(run_id: str, status: str, message: str = "", **fields) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("specialist_id", "version", "deployed", "spend_usd", "stage")}
    sets = "".join(f", {k} = coalesce(%({k})s, {k})" for k in allowed)
    with pg.conn() as c:
        c.execute(f"update builds set status = %(status)s, message = %(message)s, finished_at = now(), "
                  f"updated_at = now(){sets} where run_id = %(run_id)s and status in ('queued', 'running')",
                  {**allowed, "status": status, "message": message, "run_id": run_id})


def request_cancel(run_id: str) -> dict:
    """Queued: cancelled at once. Running: the worker stops after its current round or stage."""
    with pg.conn() as c:
        c.execute("""update builds set status = 'cancelled', message = 'Cancelled before it started',
                     finished_at = now(), updated_at = now() where run_id = %s and status = 'queued'""", (run_id,))
        c.execute("""update builds set cancel_requested = true, message = 'Cancelling after the current step',
                     updated_at = now() where run_id = %s and status = 'running'""", (run_id,))
    return view(get(run_id))


def retry(run_id: str, new_run_id: str) -> dict:
    """Queue a fresh build with the same task card and options as a failed or cancelled one."""
    with pg.conn() as c:
        old = c.execute("select user_id::text as user_id, status, task_card, options, budget_usd::float8 as b "
                        "from builds where run_id = %s", (run_id,)).fetchone()
    if not old or old["task_card"] is None:
        raise HTTPException(404, "No such build.")
    if old["status"] not in ("failed", "cancelled"):
        raise HTTPException(409, f"Only failed or cancelled builds can be retried (this one is {old['status']}).")
    return enqueue(new_run_id, old["task_card"], {**old["options"], "retry_of": run_id}, old["user_id"],
                   old["b"] or config.credit_budget_usd())


def reap_stale() -> list[str]:
    """Mark running builds whose worker stopped sending heartbeats as failed."""
    with pg.conn() as c:
        rows = c.execute("""
            update builds set status = 'failed', finished_at = now(), updated_at = now(),
              message = 'The build worker stopped responding (no heartbeat).'
            where status = 'running' and (
              (stage is null and heartbeat_at < now() - make_interval(secs => %s)) or
              (stage is not null and heartbeat_at < now() - make_interval(secs => %s)))
            returning run_id""", (STARTUP_GRACE_S, HEARTBEAT_STALE_S)).fetchall()
    return [r["run_id"] for r in rows]


def running(worker_prefix: str = "") -> list[dict]:
    with pg.conn() as c:
        return c.execute(f"select {COLUMNS} from builds where status = 'running' and worker_id like %s",
                         (worker_prefix + "%",)).fetchall()


def worker_hours(worker_prefix: str = "job:") -> float:
    """Wall-clock hours of all builds that ran on AI Jobs (for WORKER_TOTAL_BUDGET_USD)."""
    with pg.conn() as c:
        r = c.execute("""select coalesce(sum(extract(epoch from coalesce(finished_at, now()) - started_at)), 0)::float8
                         as s from builds where worker_id like %s and started_at is not null""",
                      (worker_prefix + "%",)).fetchone()
    return r["s"] / 3600


# ---- events ---------------------------------------------------------------------------
def append_events(run_id: str, events: list[tuple[int, str]]) -> None:
    if not events:
        return
    with pg.conn() as c:
        with c.cursor() as cur:
            cur.executemany("insert into build_events (run_id, seq, event) values (%s, %s, %s) "
                            "on conflict (run_id, seq) do nothing", [(run_id, s, e) for s, e in events])


def events_after(run_id: str, after: int, limit: int = 500) -> list[tuple[int, dict]]:
    with pg.conn() as c:
        rows = c.execute("select seq, event from build_events where run_id = %s and seq > %s order by seq limit %s",
                         (run_id, after, limit)).fetchall()
    return [(r["seq"], r["event"]) for r in rows]

