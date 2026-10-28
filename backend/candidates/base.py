"""Common candidate interface: fit / predict_proba / reason / save / load."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, ClassVar

import joblib
import numpy as np

from backend import config

Progress = Callable[[dict], None]


@dataclass
class Context:
    labels: list[str]
    input_type: str
    task_description: str = ""
    label_definitions: dict[str, str] = field(default_factory=dict)
    needs_reason: bool = False
    positive: str | None = None
    seed: int = 0
    llm: Any = None                      # LLMClient, only for cloud families
    log_templates: list[tuple[str, str]] | None = None


BLK = re.compile(r"blk_-?\d+")
IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
NUM = re.compile(r"\d+")


def prep_text(text: str, input_type: str) -> str:
    """Mask block IDs, IPs and numbers in log windows so models learn events, not identifiers."""
    if input_type != "log_window":
        return text
    return NUM.sub("0", IP.sub(" IP ", BLK.sub(" BLK ", text)))


class Candidate:
    family: ClassVar[str] = "?"
    rung: ClassVar[int] = 1
    uses_cloud: ClassVar[bool] = False
    bypass_cache: bool = False      # set while measuring latency/throughput so caches can't flatter them

    def __init__(self, params: dict, ctx: Context):
        self.params = dict(params)
        self.ctx = ctx
        self.labels = list(ctx.labels)

    # subclasses implement fit / predict_proba; reason is optional
    def fit(self, texts: list[str], y: list[str], progress: Progress | None = None) -> None:
        raise NotImplementedError

    def predict_proba(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError

    def reason(self, text: str, proba: np.ndarray) -> str | None:
        return None

    def usage_stats(self) -> dict | None:
        """Measured token usage for cloud families (None for CPU-only)."""
        return None

    def y_index(self, y: list[str]) -> np.ndarray:
        idx = {l: i for i, l in enumerate(self.labels)}
        return np.array([idx[v] for v in y])

    def full_proba(self, proba: np.ndarray, classes: np.ndarray) -> np.ndarray:
        """Expand a model's proba over its seen classes to all labels."""
        out = np.zeros((proba.shape[0], len(self.labels)))
        out[:, classes] = proba
        return out

    # persistence: the LLM client is never pickled; it is re-attached on load
    def __getstate__(self):
        state = self.__dict__.copy()
        state["ctx"] = Context(**{**self.ctx.__dict__, "llm": None})
        return state

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "model.joblib"
        joblib.dump(self, path, compress=3)
        return path

    @staticmethod
    def load(directory: Path, llm: Any = None) -> "Candidate":
        model = joblib.load(Path(directory) / "model.joblib")
        model.ctx.llm = llm
        model.attach(llm)
        return model

    def attach(self, llm: Any) -> None:
        """Re-attach runtime dependencies after load (overridden by cloud families)."""


def softmax(z: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    z = np.asarray(z, float) / max(temperature, 1e-6)
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


# ---- embedding cache shared by I, B, C ------------------------------------------
class EmbeddingStore:
    """Per-text float32 vector cache in SQLite, safe across worker processes."""

    _lock = threading.Lock()

    def __init__(self, name: str):
        path = config.data_dir() / "cache" / f"emb_{re.sub(r'[^A-Za-z0-9]+', '_', name)}.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._retry(lambda c: c.execute("CREATE TABLE IF NOT EXISTS emb (h TEXT PRIMARY KEY, v BLOB, tokens REAL)"))

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=60)
        c.execute("PRAGMA busy_timeout=60000")
        return c

    def _retry(self, fn):
        """Run fn(conn) in a transaction, retrying while another worker process holds the write lock."""
        for attempt in range(20):
            try:
                with self._conn() as c:
                    if attempt == 0:
                        c.execute("PRAGMA journal_mode=WAL")
                    return fn(c)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc) or attempt == 19:
                    raise
                time.sleep(0.2 * (attempt + 1))

    @staticmethod
    def key(text: str) -> str:
        return hashlib.sha1(text.encode()).hexdigest()

    def get_many(self, texts: list[str]) -> dict[str, tuple[np.ndarray, float | None]]:
        keys = list({self.key(t) for t in texts})
        out = {}

        def read(c):
            for i in range(0, len(keys), 500):
                chunk = keys[i:i + 500]
                q = f"SELECT h, v, tokens FROM emb WHERE h IN ({','.join('?' * len(chunk))})"
                for h, v, tok in c.execute(q, chunk):
                    out[h] = (np.frombuffer(v, dtype=np.float32), tok)
        self._retry(read)
        return out

    def put_many(self, items: dict[str, tuple[np.ndarray, float | None]]) -> None:
        rows = [(h, np.asarray(v, np.float32).tobytes(), tok) for h, (v, tok) in items.items()]
        with self._lock:
            self._retry(lambda c: c.executemany("INSERT OR REPLACE INTO emb VALUES (?, ?, ?)", rows))


_local_models: dict[str, Any] = {}


def local_embed(texts: list[str], model_name: str, use_cache: bool = True) -> np.ndarray:
    """Embed with a local sentence-transformers model (offline at inference)."""
    store = EmbeddingStore(model_name)
    have = store.get_many(texts) if use_cache else {}
    missing = sorted({t for t in texts if EmbeddingStore.key(t) not in have})
    if missing:
        if model_name not in _local_models:
            from sentence_transformers import SentenceTransformer
            _local_models[model_name] = SentenceTransformer(model_name, device="cpu")
        vecs = _local_models[model_name].encode(missing, batch_size=128, normalize_embeddings=True,
                                                show_progress_bar=False)
        new = {EmbeddingStore.key(t): (v, None) for t, v in zip(missing, vecs)}
        store.put_many(new)
        have.update(new)
    return np.stack([have[EmbeddingStore.key(t)][0] for t in texts])


def cloud_embed(texts: list[str], llm: Any, agent: str = "Trainer", use_cache: bool = True) -> tuple[np.ndarray, dict]:
    """Embed with Qwen3-Embedding-8B on Token Factory, cached per text.

    Returns (vectors, usage). usage["mean_tokens_per_text"] is measured: each batch's billed prompt
    tokens divided by its size, stored with every vector it produced.
    """
    api_id = config.model_id("embeddings")
    store = EmbeddingStore(api_id)
    have = store.get_many(texts) if use_cache else {}
    missing = sorted({t for t in texts if EmbeddingStore.key(t) not in have})
    usage = {"new_texts": len(missing), "tokens": 0, "cost_usd": 0.0}
    for start in range(0, len(missing), 128):
        batch = missing[start:start + 128]
        vecs, stats = llm.embed(batch, agent=agent, purpose="embeddings", batch_size=128)
        per_text = stats["new_tokens"] / len(batch)
        new = {}
        for t, v in zip(batch, vecs):
            a = np.asarray(v, np.float32)
            new[EmbeddingStore.key(t)] = (a / (np.linalg.norm(a) + 1e-9), per_text)
        store.put_many(new)
        have.update(new)
        usage["tokens"] += stats["new_tokens"]
        usage["cost_usd"] += stats["new_cost_usd"]
    toks = [have[EmbeddingStore.key(t)][1] for t in texts]
    toks = [t for t in toks if t is not None]
    usage["mean_tokens_per_text"] = float(np.mean(toks)) if toks else None
    return np.stack([have[EmbeddingStore.key(t)][0] for t in texts]), usage
