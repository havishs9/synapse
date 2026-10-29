"""Postgres (Supabase) connection pool. Used when SUPABASE_DB_URL is set; otherwise the app keeps its local files.

REGISTRY_BACKEND=files forces the local files even with a database configured (tests, offline replay).
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

from backend import config

_pool = None
_lock = threading.Lock()


def enabled() -> bool:
    return bool(config.env("SUPABASE_DB_URL")) and config.env("REGISTRY_BACKEND", "postgres") != "files"


def pool():
    global _pool
    with _lock:
        if _pool is None:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
            _pool = ConnectionPool(config.env("SUPABASE_DB_URL"), min_size=1, max_size=4, open=True, timeout=30,
                                   kwargs={"row_factory": dict_row, "connect_timeout": 15},
                                   check=ConnectionPool.check_connection, name="synapse")
        return _pool


@contextmanager
def conn():
    """A pooled connection; the block runs in one transaction (committed on success, rolled back on error)."""
    with pool().connection() as c:
        yield c


def close() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None
