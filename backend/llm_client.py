"""The one Token Factory client: retries, timeouts, disk cache, cost tracking and the budget guard.

Every LLM call in the project goes through `LLMClient`. Each call is logged to
`runs/<run_id>/llm_calls.jsonl` with model, tokens, latency and dollar cost.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from backend import config

RETRYABLE = (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)


class BudgetExceeded(RuntimeError):
    """Raised before a call that would run past the run's LLM budget."""


def call_cost_usd(api_id: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0) -> float:
    p = config.token_price(api_id)
    uncached = max(prompt_tokens - cached_tokens, 0)
    cached_rate = p.get("cached_input", p["input"])
    return (uncached * p["input"] + cached_tokens * cached_rate + completion_tokens * p.get("output", 0.0)) / 1e6


@dataclass
class ChatResult:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float          # what this call cost us now (0 when served from cache)
    list_cost_usd: float     # what the call costs at list price, cached or not
    latency_ms: float        # measured latency of the original call
    cached: bool
    tool_calls: list[dict] = field(default_factory=list)

    def json(self) -> Any:
        text = self.content.strip()
        if text.startswith("```"):
            text = text.strip("`").split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0]
        return json.loads(text)


class SpendTracker:
    """Thread-safe running total for one run, checked against its budget."""

    def __init__(self, budget_usd: float):
        self.budget_usd = budget_usd
        self.spent_usd = 0.0
        self._lock = threading.Lock()

    def check(self) -> None:
        if self.spent_usd >= self.budget_usd:
            raise BudgetExceeded(
                f"LLM spend ${self.spent_usd:.4f} reached the budget of ${self.budget_usd:.2f}. "
                "Raise the build budget on the task card or CREDIT_BUDGET_USD to continue.")

    def add(self, usd: float) -> None:
        with self._lock:
            self.spent_usd += usd


class LLMClient:
    def __init__(self, run_dir: Path | None = None, budget_usd: float | None = None,
                 cache_dir: Path | None = None, client: OpenAI | None = None):
        self.run_dir = Path(run_dir) if run_dir else None
        self.spend = SpendTracker(budget_usd if budget_usd is not None else config.credit_budget_usd())
        self.cache_dir = cache_dir or config.data_dir() / "cache" / "llm"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = client
        self._log_lock = threading.Lock()

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(api_key=config.env("NEBIUS_API_KEY"), base_url=config.env("NEBIUS_BASE_URL"),
                                  timeout=120, max_retries=0)
        return self._client

    # ---- cache and log -------------------------------------------------
    def _key(self, payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    def _cache_get(self, key: str) -> dict | None:
        path = self.cache_dir / f"{key[:2]}/{key}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def _cache_put(self, key: str, value: dict) -> None:
        path = self.cache_dir / f"{key[:2]}/{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def _log(self, record: dict) -> None:
        if not self.run_dir:
            return
        with self._log_lock, (self.run_dir / "llm_calls.jsonl").open("a") as f:
            f.write(json.dumps(record) + "\n")

    def _with_retries(self, fn):
        delay = 1.0
        for attempt in range(5):
            try:
                return fn()
            except RETRYABLE:
                if attempt == 4:
                    raise
                time.sleep(delay)
                delay *= 2

    # ---- chat ----------------------------------------------------------
    def chat(self, role: str, messages: list[dict], *, agent: str, purpose: str, max_tokens: int = 1024,
             temperature: float = 0.0, response_format: dict | None = None, tools: list | None = None,
             tool_choice: Any = None, thinking: bool = True, use_cache: bool = True,
             model: str | None = None) -> ChatResult:
        api_id = model or config.model_id(role)
        kwargs: dict[str, Any] = {"model": api_id, "messages": messages, "max_tokens": max_tokens,
                                  "temperature": temperature}
        if response_format:
            kwargs["response_format"] = response_format
        if tools:
            kwargs["tools"] = tools
            if tool_choice:
                kwargs["tool_choice"] = tool_choice
        if not thinking:
            kwargs["extra_body"] = config.no_thinking_extra_body()
        key = self._key(kwargs)
        hit = self._cache_get(key) if use_cache else None
        if hit is None:
            self.spend.check()
            t0 = time.perf_counter()
            resp = self._with_retries(lambda: self.client.chat.completions.create(**kwargs))
            latency = (time.perf_counter() - t0) * 1000
            msg = resp.choices[0].message
            usage = resp.usage
            cached_tokens = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0
            hit = {
                "content": msg.content or "",
                "tool_calls": [{"name": c.function.name, "arguments": c.function.arguments} for c in (msg.tool_calls or [])],
                "prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens or 0,
                "cached_tokens": cached_tokens, "latency_ms": latency,
            }
            self._cache_put(key, hit)
            cached = False
        else:
            cached = True
        list_cost = call_cost_usd(api_id, hit["prompt_tokens"], hit["completion_tokens"], hit.get("cached_tokens", 0))
        cost = 0.0 if cached else list_cost
        self.spend.add(cost)
        self._log({"ts": time.time(), "agent": agent, "purpose": purpose, "model": api_id,
                   "prompt_tokens": hit["prompt_tokens"], "completion_tokens": hit["completion_tokens"],
                   "latency_ms": round(hit["latency_ms"], 1), "cost_usd": cost, "list_cost_usd": list_cost,
                   "cached": cached})
        return ChatResult(content=hit["content"], model=api_id, prompt_tokens=hit["prompt_tokens"],
                          completion_tokens=hit["completion_tokens"], cost_usd=cost, list_cost_usd=list_cost,
                          latency_ms=hit["latency_ms"], cached=cached, tool_calls=hit["tool_calls"])

    def chat_stream(self, role: str, messages: list[dict], *, agent: str = "chat", purpose: str = "main_chat",
                    max_tokens: int = 2048, temperature: float = 0.6) -> Iterator[dict]:
        """Yield {"delta": str} chunks, then one {"done": True, ...usage} record. Never cached."""
        api_id = config.model_id(role)
        self.spend.check()
        t0 = time.perf_counter()
        stream = self._with_retries(lambda: self.client.chat.completions.create(
            model=api_id, messages=messages, max_tokens=max_tokens, temperature=temperature, stream=True,
            stream_options={"include_usage": True}))
        usage = None
        for chunk in stream:
            if chunk.usage:
                usage = chunk.usage
            if chunk.choices and chunk.choices[0].delta.content:
                yield {"delta": chunk.choices[0].delta.content}
        latency = (time.perf_counter() - t0) * 1000
        pt, ct = (usage.prompt_tokens, usage.completion_tokens) if usage else (0, 0)
        cost = call_cost_usd(api_id, pt, ct)
        self.spend.add(cost)
        self._log({"ts": time.time(), "agent": agent, "purpose": purpose, "model": api_id, "prompt_tokens": pt,
                   "completion_tokens": ct, "latency_ms": round(latency, 1), "cost_usd": cost,
                   "list_cost_usd": cost, "cached": False})
        yield {"done": True, "model": api_id, "prompt_tokens": pt, "completion_tokens": ct, "cost_usd": cost,
               "latency_ms": latency}

    # ---- embeddings ----------------------------------------------------
    def embed(self, texts: list[str], *, agent: str, purpose: str, role: str = "embeddings",
              batch_size: int = 128) -> tuple[list[list[float]], dict]:
        """Embed texts (no caching here; callers cache vectors). Returns (vectors, stats)."""
        api_id = config.model_id(role)
        out: list[list[float]] = []
        tokens, latency, cost = 0, 0.0, 0.0
        for start in range(0, len(texts), batch_size):
            self.spend.check()
            batch = texts[start:start + batch_size]
            t0 = time.perf_counter()
            resp = self._with_retries(lambda: self.client.embeddings.create(model=api_id, input=batch))
            dt = (time.perf_counter() - t0) * 1000
            latency += dt
            out.extend(d.embedding for d in resp.data)
            tokens += resp.usage.prompt_tokens
            c = call_cost_usd(api_id, resp.usage.prompt_tokens, 0)
            cost += c
            self.spend.add(c)
            self._log({"ts": time.time(), "agent": agent, "purpose": purpose, "model": api_id,
                       "prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": 0, "n_inputs": len(batch),
                       "latency_ms": round(dt, 1), "cost_usd": c, "list_cost_usd": c, "cached": False})
        return out, {"new_tokens": tokens, "new_cost_usd": cost, "api_latency_ms": latency}
