"""Live data sourcing for tasks outside the vetted registry (spec 03 §1.1, priority 2 and 3).

Intake: Nemotron Ultra drafts a task card from the request, then this module searches the Hugging Face Hub
(keyword search) and Tavily (web search limited to huggingface.co), reads each candidate's license tag and
columns through the dataset viewer API, and asks Nemotron Ultra which candidates fit and how their labels map
onto the task's labels. The user approves one in the chat, or picks synthetic data (the default when nothing
usable is found).

Build: the card's `data_source` is loaded again by the Data agent. The license is re-checked, rows are read
from the viewer API (sampled across the split, so label-sorted files still cover every label), and labels the
dataset lacks are filled with synthetic examples. Synthetic rows always carry `synthetic: True`.

Settings and URLs: the `sourcing` section of config/datasets.yaml.
"""
from __future__ import annotations

import datetime as dt
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import httpx

from backend import config
from backend.schemas import Label, TaskCard, Thresholds

MAIN_ROLE = "main_chat_planner_teacher_baseline"
Emit = Callable[..., None]
TEXT_NAMES = ("text", "sentence", "content", "message", "body", "review", "comment", "query", "utterance",
              "question", "description", "title", "tweet", "email", "document", "input", "prompt", "sms")
LABEL_NAMES = ("label", "labels", "category", "class", "intent", "sentiment", "target", "topic", "emotion",
               "type", "tag", "is_spam", "toxic", "y")
HF_ID = re.compile(r"huggingface\.co/datasets/([\w.-]+/[\w.-]+)")
DATASET_ID = re.compile(r"[A-Za-z0-9][\w-]*(\.[\w-]+)*/[A-Za-z0-9][\w-]*(\.[\w-]+)*")


class SourcingError(RuntimeError):
    pass


def cfg() -> dict:
    return config.sourcing()


def _headers() -> dict:
    tok = config.env("HF_TOKEN")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _get(url: str, params: dict | None = None, timeout: float = 20) -> Any:
    r = httpx.get(url, params=params, headers=_headers(), timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    return r.json()


def chat_json(llm, prompt: str, *, purpose: str, max_tokens: int, response_format: dict, temperature: float = 0.0,
              agent: str = "Data"):
    """One JSON call, retried once uncached and a little warmer: Nemotron Ultra occasionally fills the whole
    budget with whitespace under a JSON schema, and that reply would otherwise be served from the cache forever."""
    for attempt in range(2):
        res = llm.chat(MAIN_ROLE, [{"role": "user", "content": prompt}], agent=agent, purpose=purpose,
                       max_tokens=max_tokens, temperature=temperature if attempt == 0 else max(temperature, 0.4),
                       thinking=False, response_format=response_format, use_cache=attempt == 0)
        try:
            return res.json()
        except ValueError:
            if attempt:
                raise


# ---- licenses -------------------------------------------------------------------------------
def license_of(info: dict) -> str:
    """License from a Hub dataset record: the card's `license` field, else the `license:` tag."""
    lic = (info.get("cardData") or {}).get("license")
    if isinstance(lic, list):
        lic = lic[0] if lic else None
    if not lic:
        lic = next((t.split(":", 1)[1] for t in info.get("tags", []) if t.startswith("license:")), None)
    return str(lic or "unknown").lower()


def license_ok(lic: str) -> bool:
    return lic.lower() in cfg()["license_allowlist"]


def hub_info(dataset_id: str) -> dict:
    return _get(f"{cfg()['hf_api']}/{dataset_id}")


# ---- task draft -----------------------------------------------------------------------------
DRAFT_SCHEMA = {
    "type": "json_schema", "json_schema": {"name": "task_draft", "strict": True, "schema": {
        "type": "object", "additionalProperties": False,
        "required": ["feasible", "why_not", "reframed_from", "task_name", "description", "output_type", "labels",
                     "positive_label", "search_queries", "web_query", "input_hint", "preference_question"],
        "properties": {
            "feasible": {"type": "boolean"},
            "why_not": {"type": "string"},
            "reframed_from": {"type": "string"},
            "task_name": {"type": "string"},
            "description": {"type": "string"},
            "output_type": {"type": "string", "enum": ["binary", "multiclass"]},
            "labels": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["name", "definition"],
                "properties": {"name": {"type": "string"}, "definition": {"type": "string"}}}},
            "positive_label": {"type": "string"},
            "search_queries": {"type": "array", "items": {"type": "string"}},
            "web_query": {"type": "string"},
            "input_hint": {"type": "string"},
            "preference_question": {"type": "string"},
        }}}}


INSIST = ("\nThe user explicitly asked for a model, so feasible must be true: frame the request as the closest "
          "classification of one text into fixed labels (for a recommender: classify one item as recommend / skip "
          "for this user).")


def draft_task(text: str, samples: list[str], llm, insist: bool = False) -> dict:
    """Nemotron Ultra turns a request into a text-classification task draft plus search queries. `insist` re-drafts
    a request it called infeasible, framed as the closest classification."""
    prompt = (
        "You are the intake step of Synapse, which builds small, cheap specialist models for repetitive "
        "text-classification tasks (one short text in, one label out). The user wrote:\n"
        f'"""{text[:2000]}"""\n'
        + ("Sample inputs they pasted:\n" + "\n".join(f"- {s[:200]}" for s in samples[:10]) + "\n" if samples else "")
        + "\nDraft the task. If the request is already a classification of a text input into a fixed set of "
        "labels, draft it and set reframed_from=\"\". Most other requests can be framed as classifying one text: "
        "recommendation, filtering or \"based on my taste\" requests classify one item (e.g. a title with its synopsis "
        "and genres) as recommend / skip, or into the user's preference categories; use the user's stated tastes in "
        "the label definitions. Then in reframed_from say in one plain sentence what a small classifier can't do "
        "directly and how this task helps instead (e.g. for 'recommend movies for my tastes': 'A small specialist "
        "can't rank a whole catalogue, but it can read a movie's description and say whether it fits your tastes'). "
        "Never set feasible=false for lack of data, a catalog or labels: Synapse searches for a dataset and generates "
        "synthetic data when none fits. Set feasible=false (and say why in why_not) only if no text classification "
        "can serve the request (e.g. generating long free text or images, 'what's the weather'). task_name: 2 to 4 words in Title Case ending in a role noun "
        "(e.g. 'Spam Detector', 'Review Sentiment Classifier'). description: one sentence. labels: 2 to 20 short "
        "snake_case names with a one-sentence definition each; for a yes/no task use output_type=binary with "
        "exactly 2 labels and set positive_label to the one to detect (else positive_label=\"\"). "
        "search_queries: 3 to 5 short keyword queries (1 to 3 words) that would appear in the NAME of a matching "
        "labeled dataset on the Hugging Face Hub (e.g. 'sms spam', 'sentiment', 'toxic comments'); include one query that is just the domain (e.g. 'anime', 'myanimelist'), since catalogs with genre or rating columns can be mapped onto the labels. web_query: one "
        "web search query for a labeled dataset for this task. input_hint: what one input looks like, a few words. "
        "preference_question: when the labels depend on this user's personal taste or rules (e.g. a recommender), one "
        "friendly question asking what they like and dislike, with an example answer; else \"\"."
        + (INSIST if insist else ""))
    d = chat_json(llm, prompt, purpose="intake_task_draft" + ("_insist" if insist else ""), max_tokens=1200,
                  response_format=DRAFT_SCHEMA)
    labels, seen = [], set()
    for lab in d.get("labels") or []:
        name = re.sub(r"[^a-z0-9_]+", "_", str(lab.get("name", "")).strip().lower()).strip("_")[:40]
        if name and name not in seen:
            seen.add(name)
            labels.append({"name": name, "definition": str(lab.get("definition", ""))[:300]})
    d["labels"] = labels[:20]
    pos = re.sub(r"[^a-z0-9_]+", "_", str(d.get("positive_label") or "").lower()).strip("_")
    if d.get("output_type") == "binary":
        if len(labels) != 2:
            d["output_type"] = "multiclass"
        d["positive_label"] = pos if pos in seen else (labels[0]["name"] if labels else "")
    if len(labels) < 2:
        d["feasible"] = False
        d["why_not"] = d.get("why_not") or "A classifier needs at least two labels."
    d["search_queries"] = [q.strip()[:60] for q in d.get("search_queries") or [] if q.strip()][:5]
    return d


def card_from_draft(d: dict, samples: list[str]) -> TaskCard:
    """The custom task's default card (the user's answers and data choice edit it, like a demo task's)."""
    binary = d["output_type"] == "binary"
    slug = re.sub(r"[^a-z0-9]+", "_", d["task_name"].lower()).strip("_")[:40] or "custom"
    return TaskCard(
        task_id=f"custom_{slug}", task_name=d["task_name"][:60], description=d["description"][:500],
        input_type="text", output_type="binary" if binary else "multiclass",
        labels=[Label(**lab) for lab in d["labels"]], positive_definition=d.get("positive_label") if binary else None,
        error_preference="balanced", optimization_metric="pr_auc" if binary else "macro_f1",
        thresholds=Thresholds(primary_min=0.80 if binary else 0.70), needs_reason=False,
        monthly_volume=config.demo_monthly_volume(), latency_budget_ms=50, deployment="cloud_ok",
        build_budget_usd=config.credit_budget_usd(), build_budget_minutes=30, sample_inputs=samples[:20])


# ---- search ---------------------------------------------------------------------------------
_tavily_lock = threading.Lock()
_tavily_day: dict[str, int] = {}


def _tavily_allowed() -> bool:
    """Daily cap on Tavily searches for everyone (TAVILY_DAILY_SEARCH_LIMIT, docs/TEAM_PLAN.md §6)."""
    today = dt.date.today().isoformat()
    with _tavily_lock:
        n = _tavily_day.get(today, 0)
        if n >= int(config.env("TAVILY_DAILY_SEARCH_LIMIT", "100")):
            return False
        _tavily_day.clear()
        _tavily_day[today] = n + 1
        return True


def search_hub(queries: list[str]) -> list[dict]:
    """Hub keyword search (it matches dataset names), most downloaded first."""
    out: dict[str, dict] = {}
    for q in queries:
        try:
            for d in _get(cfg()["hf_api"], {"search": q, "sort": "downloads", "limit": cfg()["hf_results_per_query"],
                                            "full": "true"}):
                out.setdefault(d["id"], {**d, "found_by": f"Hugging Face search \"{q}\""})
        except httpx.HTTPError:
            continue
    return list(out.values())


def search_web(query: str) -> list[str]:
    """Tavily web search limited to huggingface.co; returns dataset ids found in the result URLs."""
    key = config.env("TAVILY_API_KEY")
    if not key or not query or not _tavily_allowed():
        return []
    try:
        from tavily import TavilyClient
        res = TavilyClient(api_key=key).search(query, include_domains=cfg()["tavily_domains"], max_results=8)
    except Exception:
        return []
    ids = []
    for r in res.get("results", []):
        m = HF_ID.search(r.get("url", ""))
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def _is_text_classification(d: dict) -> bool:
    tags = d.get("tags", [])
    if any(t.startswith("modality:") for t in tags) and "modality:text" not in tags:
        return False
    return not any(t.startswith("task_categories:") for t in tags) or any(
        t in tags for t in ("task_categories:text-classification", "task_categories:token-classification",
                            "task_categories:zero-shot-classification", "task_categories:sentence-similarity"))


def _pick_columns(features: dict, rows: list[dict]) -> tuple[str | None, str | None, list[str] | None]:
    """Text column, label column, and the label names when the label is a ClassLabel (ints in the rows)."""
    features = {k: f for k, f in features.items() if isinstance(f, dict)}    # lists are Sequence columns: skip
    strings = [k for k, f in features.items() if f.get("_type") == "Value" and f.get("dtype") in ("string", "large_string")]
    label_col, names = None, None
    classlabels = [k for k, f in features.items() if f.get("_type") == "ClassLabel"]
    if classlabels:
        label_col = next((k for k in classlabels if k.lower() in LABEL_NAMES), classlabels[0])
        names = [str(n) for n in features[label_col]["names"]]
    else:
        for k, f in features.items():
            if k.lower() in LABEL_NAMES and f.get("_type") == "Value":
                vals = {str(r.get(k)) for r in rows if r.get(k) is not None}
                if 2 <= len(vals) <= 50:
                    label_col = k
                    break
    texts = [k for k in strings if k != label_col]
    if not texts:
        return None, label_col, names
    named = [k for k in texts if k.lower() in TEXT_NAMES]
    avg = lambda k: sum(len(str(r.get(k) or "")) for r in rows) / max(len(rows), 1)
    text_col = named[0] if named else max(texts, key=avg)
    return text_col, label_col, names


def inspect(d: dict) -> dict:
    """Read a candidate's license, columns and first rows through the dataset viewer API. A candidate the
    viewer describes in an unexpected shape is reported as unusable instead of failing the whole search."""
    try:
        return _inspect(d)
    except Exception as exc:
        return {"id": f"hf:{d['id']}", "kind": "hf", "name": d["id"], "url": f"{cfg()['hf_dataset_page']}/{d['id']}",
                "license": license_of(d), "license_ok": False, "usable": False,
                "reason": f"couldn't read its columns ({type(exc).__name__})"}


def _inspect(d: dict) -> dict:
    did = d["id"]
    lic = license_of(d)
    out = {"id": f"hf:{did}", "kind": "hf", "name": did, "url": f"{cfg()['hf_dataset_page']}/{did}",
           "license": lic, "license_ok": license_ok(lic), "found_by": d.get("found_by", ""),
           "downloads": d.get("downloads")}
    if not out["license_ok"]:
        return {**out, "usable": False, "reason": f"license \"{lic}\" isn't on the allowlist"}
    ds = cfg()["datasets_server"]
    try:
        info = _get(f"{ds}/info", {"dataset": did})["dataset_info"]
    except (httpx.HTTPError, KeyError):
        return {**out, "usable": False, "reason": "the dataset viewer can't read it"}
    conf = "default" if "default" in info else next(iter(info), None)
    if not conf:
        return {**out, "usable": False, "reason": "no configurations"}
    ci = info[conf]
    splits = {k: v.get("num_examples", 0) for k, v in (ci.get("splits") or {}).items()}
    order = [s for s in ("train", "validation", "test") if s in splits] + [s for s in splits if s not in ("train", "validation", "test")]
    if not order:
        return {**out, "usable": False, "reason": "no splits"}
    try:
        first = _get(f"{ds}/first-rows", {"dataset": did, "config": conf, "split": order[0]})
        rows = [r["row"] for r in first.get("rows", [])]
    except httpx.HTTPError:
        return {**out, "usable": False, "reason": "couldn't read sample rows"}
    text_col, label_col, names = _pick_columns(ci.get("features") or {}, rows)
    if not text_col or not label_col:
        return {**out, "usable": False, "reason": "no text column with a label column next to it"}
    to_label = (lambda v: names[v] if names and isinstance(v, int) and 0 <= v < len(names) else str(v))
    source_labels = names or sorted({to_label(r.get(label_col)) for r in rows if r.get(label_col) is not None})
    return {**out, "usable": True, "config": conf, "splits": order, "rows": sum(splits.values()),
            "text_column": text_col, "label_column": label_col, "label_names": names,
            "source_labels": source_labels[:200],
            "samples": [{"text": str(r.get(text_col) or "")[:300], "label": to_label(r.get(label_col))}
                        for r in rows if r.get(text_col)][:40],
            "description": (d.get("description") or (d.get("cardData") or {}).get("pretty_name") or "")[:400]}


CHOOSE_SCHEMA = {
    "type": "json_schema", "json_schema": {"name": "dataset_choice", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["picks"],
        "properties": {"picks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["index", "fit", "why", "label_map"],
            "properties": {
                "index": {"type": "integer"},
                "fit": {"type": "number"},
                "why": {"type": "string"},
                "label_map": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["source", "target"],
                    "properties": {"source": {"type": "string"}, "target": {"type": "string"}}}},
            }}}}}}}


def choose(card: TaskCard, cands: list[dict], llm) -> list[dict]:
    """Nemotron Ultra ranks the usable candidates and maps each one's labels onto the task's labels."""
    if not cands:
        return []
    labels = "\n".join(f"- {lab.name}: {lab.definition}" for lab in card.labels)
    blocks = []
    for i, c in enumerate(cands):
        ex = "\n".join(f"    [{s['label']}] {s['text'][:160]}" for s in c["samples"][:4])
        blocks.append(f"{i}. {c['name']} ({c['rows']:,} rows, text column \"{c['text_column']}\", label column "
                      f"\"{c['label_column']}\")\n   {c['description'][:200]}\n   source labels: "
                      f"{', '.join(c['source_labels'][:60])}\n   examples:\n{ex}")
    samples = "\n".join(f"- {s[:160]}" for s in card.sample_inputs[:8])
    prompt = (
        f"Task: {card.task_name}. {card.description}\nTask labels:\n{labels}\n"
        + (f"The user's real inputs look like:\n{samples}\n" if samples else "")
        + "\nCandidate labeled datasets:\n" + "\n\n".join(blocks)
        + "\n\nPick up to 3 datasets whose inputs and labels really fit this task (none if nothing fits; a dataset "
        "about a different domain or label meaning doesn't fit). For each pick give fit from 0 to 1, one sentence "
        "why, and label_map: one entry per source label with target = the task label it means, or \"\" to drop "
        "rows with that label. Use only the task label names listed above as targets.")
    picks = chat_json(llm, prompt, purpose="intake_dataset_choice", max_tokens=2000, response_format=CHOOSE_SCHEMA)
    task_labels = {lab.name for lab in card.labels}
    out = []
    for p in picks.get("picks", []):
        i = p.get("index")
        if not isinstance(i, int) or not 0 <= i < len(cands) or any(o["name"] == cands[i]["name"] for o in out):
            continue
        lmap = {str(m["source"]): m["target"] for m in p.get("label_map", [])
                if m.get("target") in task_labels and str(m.get("source")) in cands[i]["source_labels"]}
        if not lmap or float(p.get("fit", 0)) < cfg()["min_fit"]:
            continue
        covered = sorted(set(lmap.values()))
        out.append({**cands[i], "fit": round(min(max(float(p.get("fit", 0)), 0), 1), 2), "why": p.get("why", "")[:300],
                    "label_map": lmap, "labels": covered,
                    "gap_labels": [lab.name for lab in card.labels if lab.name not in covered]})
    return sorted(out, key=lambda o: -o["fit"])[: cfg()["max_options_shown"]]


def synthetic_option(card: TaskCard) -> dict:
    n = cfg()["synthetic_per_label"]
    return {"id": "synthetic", "kind": "synthetic", "name": "Synthetic data from Nemotron", "license": "generated",
            "license_ok": True, "usable": True, "labels": [lab.name for lab in card.labels], "gap_labels": [],
            "rows": n * len(card.labels),
            "why": f"Nemotron Ultra writes about {n} examples per label in your input format. Every score, the sealed "
                   "test included, is then measured on synthetic data, and the report says so."}


# ---- public APIs ----------------------------------------------------------------------------
# Vetted APIs with a recorded license (`sourcing.apis` in config/datasets.yaml). Their items are real inputs with
# no labels for the user's task, so the teacher labels them at build time and the report says so.
TAG = re.compile(r"<[^>]+>")


def _api_get(url: str, params: dict | None = None, timeout: float = 30, accept: str = "application/json") -> Any:
    """GET with our User-Agent (both APIs ask for one); never sends the Hugging Face token to another host."""
    for attempt in range(2):
        r = httpx.get(url, params=params, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": cfg()["user_agent"], "Accept": accept})
        if r.status_code == 429 and not attempt:          # both APIs ask clients to back off on 429
            time.sleep(min(float(r.headers.get("Retry-After") or 3), 10))
            continue
        r.raise_for_status()
        return r.json()


def _tvmaze_text(show: dict) -> str:
    summary = re.sub(r"\s+", " ", TAG.sub(" ", show.get("summary") or "")).strip()
    meta = ", ".join(x for x in (show.get("type"), show.get("language")) if x)
    genres = ", ".join(show.get("genres") or [])
    return (f"{show.get('name', '').strip()}" + (f" ({meta})" if meta else "") + (f". Genres: {genres}" if genres else "")
            + (f". {summary}" if summary else ""))[:700]


def fetch_tvmaze(spec: dict, filt: dict, n: int, max_pages: int | None = None) -> list[dict]:
    """Shows from TVmaze's /shows index (250 ids a page), filtered by genre and language, paced under its rate
    limit (at least 20 calls per 10 s per IP)."""
    genre, lang = filt.get("genre") or "", (filt.get("language") or "").lower()
    out: list[dict] = []
    for page in range(max_pages or spec["max_pages"]):
        try:
            shows = _api_get(f"{spec['url']}/shows", {"page": page})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:          # past the last page
                break
            raise
        for sh in shows:
            if genre and genre not in (sh.get("genres") or []):
                continue
            if lang and (sh.get("language") or "").lower() != lang:
                continue
            if sh.get("name") and (sh.get("summary") or sh.get("genres")):
                out.append({"id": f"tvmaze-{sh['id']}", "text": _tvmaze_text(sh), "url": sh.get("url")})
        if len(out) >= n:
            break
        time.sleep(0.5)
    return out[:n]


def _wikidata_query(qid: str, n: int, ordered: bool) -> str:
    # Most-linked items first (a popularity proxy) at build time; the preview skips the sort to stay fast.
    inner = (f"SELECT ?item ?sl WHERE {{ ?item wdt:P31 wd:{qid} ; wikibase:sitelinks ?sl . FILTER(?sl >= 3) }}"
             + (" ORDER BY DESC(?sl)" if ordered else "") + f" LIMIT {int(n)}")
    return (f"SELECT ?item ?itemLabel ?desc (GROUP_CONCAT(DISTINCT ?gl; separator=\", \") AS ?genres) WHERE {{\n"
            f"  {{ {inner} }}\n"
            "  OPTIONAL { ?item schema:description ?desc FILTER(lang(?desc) = \"en\") }\n"
            "  OPTIONAL { ?item wdt:P136 ?g . ?g rdfs:label ?gl FILTER(lang(?gl) = \"en\") }\n"
            "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\". }\n"
            "} GROUP BY ?item ?itemLabel ?desc")


def fetch_wikidata(spec: dict, filt: dict, n: int, ordered: bool = True) -> list[dict]:
    cls = spec["classes"][filt["class"]]
    res = _api_get(spec["url"], {"query": _wikidata_query(cls["qid"], n, ordered)}, timeout=70,
                   accept="application/sparql-results+json")
    out = []
    for b in res["results"]["bindings"]:
        label = b.get("itemLabel", {}).get("value", "")
        if not label or re.fullmatch(r"Q\d+", label):        # no English label
            continue
        desc, genres = b.get("desc", {}).get("value", ""), b.get("genres", {}).get("value", "")
        out.append({"id": "wd-" + b["item"]["value"].rsplit("/", 1)[-1], "url": b["item"]["value"],
                    "text": (label + (f": {desc}" if desc else "") + (f". Genres: {genres}" if genres else ""))[:700]})
    return out


def fetch_api(src: dict, n: int, preview: bool = False) -> list[dict]:
    spec = cfg()["apis"][src["source"]]
    if src["source"] == "tvmaze":
        return fetch_tvmaze(spec, src.get("filter") or {}, n, max_pages=4 if preview else None)
    if src["source"] == "wikidata":
        return fetch_wikidata(spec, src.get("filter") or {}, n, ordered=not preview)
    raise SourcingError(f"Unknown API {src['source']}.")


def _api_filter_ok(source: str, filt: dict) -> bool:
    spec = cfg()["apis"].get(source)
    if not spec or not isinstance(filt, dict):
        return False
    if source == "wikidata":
        return filt.get("class") in spec["classes"]
    return (filt.get("genre") or "") in ("", *spec["genres"]) and len(str(filt.get("language") or "")) <= 30


def _api_schema() -> dict:
    apis = cfg()["apis"]
    return {"type": "json_schema", "json_schema": {"name": "api_choice", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["picks"],
        "properties": {"picks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["source", "wikidata_class", "tvmaze_genre", "tvmaze_language", "fit", "why"],
            "properties": {
                "source": {"type": "string", "enum": list(apis)},
                "wikidata_class": {"type": "string", "enum": [*apis["wikidata"]["classes"], ""]},
                "tvmaze_genre": {"type": "string", "enum": [*apis["tvmaze"]["genres"], ""]},
                "tvmaze_language": {"type": "string"},
                "fit": {"type": "number"},
                "why": {"type": "string"},
            }}}}}}}


def choose_apis(card: TaskCard, llm) -> list[dict]:
    """Nemotron Ultra picks which vetted APIs can supply real inputs for the task, and how to filter them."""
    apis = cfg()["apis"]
    listing = "\n".join(f"- {k}: {v['name']}, {v['covers']}" for k, v in apis.items())
    classes = ", ".join(f"{k} ({v['label']})" for k, v in apis["wikidata"]["classes"].items())
    prompt = (
        f"Task: {card.task_name}. {card.description}\nLabels: {', '.join(lab.name for lab in card.labels)}\n\n"
        f"Public APIs that return real items (no labels; a teacher model labels them for the task):\n{listing}\n"
        f"Wikidata classes: {classes}.\nTVmaze genres: {', '.join(apis['tvmaze']['genres'])}.\n\n"
        "Pick the APIs (up to 2) whose items are the kind of input this task classifies, e.g. anime or TV shows for "
        "a show recommender. None if no API returns that kind of item. For wikidata set wikidata_class; for tvmaze "
        "optionally set tvmaze_genre (e.g. Anime) and tvmaze_language (e.g. Japanese, or \"\" for all); leave the "
        "other source's fields \"\". fit from 0 to 1, and one sentence why.")
    res = chat_json(llm, prompt, purpose="intake_api_choice", max_tokens=600, response_format=_api_schema())
    out, seen = [], set()
    for p in res.get("picks", []):
        src = p.get("source")
        filt = ({"class": p.get("wikidata_class")} if src == "wikidata" else
                {"genre": p.get("tvmaze_genre") or "", "language": (p.get("tvmaze_language") or "").strip()})
        key = (src, tuple(sorted(filt.items())))
        if src not in apis or key in seen or not _api_filter_ok(src, filt) or float(p.get("fit", 0)) < cfg()["min_fit"]:
            continue
        seen.add(key)
        out.append({"source": src, "filter": filt, "fit": round(min(max(float(p["fit"]), 0), 1), 2),
                    "why": str(p.get("why", ""))[:300]})
    return sorted(out, key=lambda o: -o["fit"])[:2]


def _api_name(source: str, filt: dict) -> str:
    spec = cfg()["apis"][source]
    if source == "wikidata":
        return f"{spec['name']}: {spec['classes'][filt['class']]['label']}"
    what = " ".join(x for x in (filt.get("language"), filt.get("genre")) if x)
    return f"{spec['name']}: {what + ' ' if what else ''}shows"


def teacher_name() -> str:
    return config.models()[cfg()["teacher_labeling_role"]]["display_name"]


def api_options(card: TaskCard, llm) -> tuple[list[dict], list[dict]]:
    """Data options from the vetted APIs, each with a live preview of real items. Returns (options, rejected)."""
    from backend.agents.data_agent import format_match
    try:
        picks = choose_apis(card, llm)
    except Exception:
        return [], []
    opts, rejected = [], []
    for p in picks:
        spec = cfg()["apis"][p["source"]]
        name = _api_name(p["source"], p["filter"])
        try:
            items = fetch_api(p, cfg()["api_sample_items"], preview=True)
        except Exception as exc:
            rejected.append({"name": name, "url": spec["page"], "license": spec["license"],
                             "reason": f"the API didn't answer ({type(exc).__name__})"})
            continue
        if not items:
            rejected.append({"name": name, "url": spec["page"], "license": spec["license"],
                             "reason": "no items match the filter"})
            continue
        opts.append({"id": f"api:{p['source']}:{'-'.join(v for v in p['filter'].values() if v) or 'all'}",
                     "kind": "api", "source": p["source"], "filter": p["filter"], "name": name, "url": spec["page"],
                     "license": spec["license"], "license_ok": license_ok(spec["license"]), "usable": True,
                     "fit": p["fit"], "why": p["why"], "labels": [lab.name for lab in card.labels], "gap_labels": [],
                     "rows": cfg()["api_items_fetched"], "teacher": teacher_name(), "found_by": "public API registry",
                     "samples": [{"text": it["text"][:300], "label": ""} for it in items[:3]],
                     "format_match": format_match(card.sample_inputs, [{"text": it["text"]} for it in items])})
    return [o for o in opts if o["license_ok"]], rejected


TEACHER_SCHEMA_NAME = "teacher_labels"


def teacher_label(card: TaskCard, items: list[dict], llm, emit: Emit) -> list[dict]:
    """The teacher labels API items from the task card (spec 03 §1.2: bulk labeling with Nano, every call cached)."""
    role, size = cfg()["teacher_labeling_role"], cfg()["teacher_batch"]
    labels = [lab.name for lab in card.labels]
    defs = "\n".join(f"- {lab.name}: {lab.definition}" for lab in card.labels)
    schema = {"type": "json_schema", "json_schema": {"name": TEACHER_SCHEMA_NAME, "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["labels"],
        "properties": {"labels": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["i", "label"],
            "properties": {"i": {"type": "integer"}, "label": {"type": "string", "enum": labels}}}}}}}}
    batches = [items[i:i + size] for i in range(0, len(items), size)]

    def one(b: int) -> list[dict]:
        batch = batches[b]
        prompt = (f"Task: {card.task_name}. {card.description}\nLabels:\n{defs}\n\nLabel every item below with "
                  "exactly one label. Return JSON {\"labels\": [{\"i\": <item number>, \"label\": \"...\"}]}.\n\n"
                  + "\n".join(f"{i}. {it['text'][:500]}" for i, it in enumerate(batch)))
        try:
            res = llm.chat(role, [{"role": "user", "content": prompt}], agent="Data", purpose=f"teacher_label_{b}",
                           max_tokens=60 * len(batch) + 200, thinking=False, response_format=schema)
            got = {int(x["i"]): x["label"] for x in res.json().get("labels", []) if x.get("label") in labels}
        except Exception as exc:          # a failed batch is reported, not fatal
            emit("Data", "data", f"Teacher labeling batch {b + 1} failed: {type(exc).__name__}")
            return []
        return [{"id": it["id"], "text": it["text"], "label": got[i]} for i, it in enumerate(batch) if i in got]

    with ThreadPoolExecutor(4) as ex:
        return [r for rows in ex.map(one, range(len(batches))) for r in rows]


def find_datasets(card: TaskCard, draft: dict, llm) -> dict:
    """Search, inspect and rank datasets for a drafted task. Returns {options, rejected, searched}."""
    from backend.agents.data_agent import format_match
    hub = search_hub(draft.get("search_queries") or [card.task_name])
    web_ids = search_web(draft.get("web_query") or "")
    known = {d["id"] for d in hub}
    extra = []
    for did in web_ids:
        if did not in known:
            try:
                extra.append({**hub_info(did), "found_by": "Tavily web search"})
            except httpx.HTTPError:
                continue
    pool = [d for d in hub + extra if _is_text_classification(d)]
    pool = sorted(pool, key=lambda d: -(d.get("downloads") or 0))[: cfg()["max_candidates_inspected"]]
    def safe_inspect(d: dict) -> dict:      # one malformed dataset must not fail the whole search
        try:
            return inspect(d)
        except Exception as exc:
            return {"id": f"hf:{d.get('id')}", "kind": "hf", "name": d.get("id"), "usable": False,
                    "reason": f"couldn't read its layout ({type(exc).__name__})"}

    with ThreadPoolExecutor(6) as ex:
        inspected = list(ex.map(safe_inspect, pool))
    usable = [c for c in inspected if c.get("usable")]
    try:
        picks = choose(card, usable, llm)
    except Exception:
        picks = []
    for p in picks:
        p["format_match"] = format_match(card.sample_inputs, p["samples"])
        p["samples"] = p["samples"][:3]
    page = lambda name: f"{cfg()['hf_dataset_page']}/{name}"
    rejected = [{"name": c["name"], "url": c.get("url") or page(c["name"]), "license": c.get("license", "unknown"),
                 "reason": c["reason"]} for c in inspected if not c.get("usable")]
    rejected += [{"name": c["name"], "url": c["url"], "license": c["license"],
                  "reason": "inputs or labels don't match the task"}
                 for c in usable if c["name"] not in {p["name"] for p in picks}]
    apis, api_rejected = api_options(card, llm)
    return {"options": picks + apis + [synthetic_option(card)], "rejected": rejected + api_rejected,
            "searched": {"hub_queries": draft.get("search_queries") or [], "web_query": draft.get("web_query") if web_ids else None,
                         "candidates": len(pool), "apis": [o["name"] for o in apis]}}


def data_source_from(option: dict) -> dict:
    """What the task card stores about the chosen option (only what the build needs to load it again)."""
    if option.get("kind") == "synthetic":
        return {"kind": "synthetic", "name": "Synthetic data from Nemotron"}
    if option.get("kind") == "api":
        source, filt = str(option.get("source", "")), option.get("filter") or {}
        if not _api_filter_ok(source, filt):
            raise SourcingError("Unknown data option.")
        spec = cfg()["apis"][source]
        if not license_ok(spec["license"]):
            raise SourcingError(f"License \"{spec['license']}\" isn't on the allowlist.")
        return {"kind": "api", "source": source, "filter": filt, "name": _api_name(source, filt), "url": spec["page"],
                "license": spec["license"]}
    if option.get("kind") != "hf" or not DATASET_ID.fullmatch(str(option.get("name", ""))):
        raise SourcingError("Unknown data option.")
    if not license_ok(str(option.get("license", ""))):
        raise SourcingError(f"License \"{option.get('license')}\" isn't on the allowlist.")
    keys = ("name", "url", "license", "config", "splits", "text_column", "label_column", "label_names", "label_map", "rows")
    return {"kind": "hf", **{k: option.get(k) for k in keys}}


def apply_option(card: TaskCard, option: dict) -> TaskCard:
    """Put the chosen data option on the card. The task's labels stay; ones the dataset lacks get synthetic rows."""
    return card.model_copy(update={"data_source": data_source_from(option), "dataset_key": None})


# ---- build time -----------------------------------------------------------------------------
def fetch_rows(src: dict, max_rows: int) -> list[dict]:
    """Read up to max_rows rows of the chosen dataset, in pages spread evenly across each split."""
    ds, page = cfg()["datasets_server"], cfg()["rows_page_size"]
    info = _get(f"{ds}/info", {"dataset": src["name"]})["dataset_info"][src["config"]]
    sizes = {k: v.get("num_examples", 0) for k, v in (info.get("splits") or {}).items()}
    names = src.get("label_names")
    jobs = []
    left = max_rows
    for split in src["splits"]:
        n = sizes.get(split, 0)
        if not n or left <= 0:
            continue
        take = min(n, left)
        pages = -(-take // page)
        jobs += [(split, int(i * n / pages) if n > take else i * page) for i in range(pages)]
        left -= take

    def one(job):
        split, offset = job
        res = _get(f"{ds}/rows", {"dataset": src["name"], "config": src["config"], "split": split,
                                  "offset": offset, "length": page}, timeout=60)
        return split, [(r["row_idx"], r["row"]) for r in res.get("rows", [])]

    rows, seen = [], set()
    with ThreadPoolExecutor(8) as ex:
        for split, batch in ex.map(one, jobs):
            for idx, r in batch:
                if (split, idx) in seen:
                    continue
                seen.add((split, idx))
                v = r.get(src["label_column"])
                label = names[v] if names and isinstance(v, int) and 0 <= v < len(names) else str(v)
                rows.append({"id": f"{split}-{idx}", "text": str(r.get(src["text_column"]) or ""), "source_label": label})
    return rows


def generate_synthetic(card: TaskCard, labels: list[str], per_label: int, llm, emit: Emit) -> list[dict]:
    """Nemotron Ultra writes examples per label in the user's format (spec 03 §1.1 priority 3)."""
    batch = cfg()["synthetic_batch"]
    defs = {lab.name: lab.definition for lab in card.labels}
    samples = card.sample_inputs[:5]
    angles = ["typical, everyday cases", "harder, borderline cases that are easy to confuse with another label",
              "short and informal cases", "long and detailed cases"]
    jobs = [(lab, b) for lab in labels for b in range(-(-per_label // batch))]

    def one(job):
        lab, b = job
        prompt = (
            f"Write {batch} new, realistic, varied inputs for this task: {card.description}\n"
            f"Every input must belong to the label \"{lab}\" ({defs.get(lab, '')}). "
            f"Other labels: {', '.join(n for n in defs if n != lab)}.\nFocus on {angles[b % len(angles)]}.\n"
            + ("Match the style, casing and length of these real inputs:\n" + "\n".join(f"- {s}" for s in samples) + "\n"
               if samples else "")
            + 'Write only the inputs, never the label. Return JSON: {"examples": ["...", ...]}')
        try:
            res = llm.chat(MAIN_ROLE, [{"role": "user", "content": prompt}], agent="Data",
                           purpose=f"synthetic_{lab[:20]}_{b}", max_tokens=3000, temperature=0.9, thinking=False,
                           response_format={"type": "json_object"})
            ex = [e.strip() for e in res.json().get("examples", []) if isinstance(e, str) and e.strip()]
        except Exception as exc:          # a failed batch is reported, not fatal
            emit("Data", "data", f"Couldn't generate synthetic examples for {lab}: {type(exc).__name__}")
            return []
        return [{"id": f"syn-{lab[:16]}-{b}-{i}", "text": t, "label": lab, "synthetic": True} for i, t in enumerate(ex)]

    with ThreadPoolExecutor(4) as ex:
        return [r for rows in ex.map(one, jobs) for r in rows]


def load_rows(card: TaskCard, llm, emit: Emit) -> tuple[list[dict], list[dict], dict, list[dict]]:
    """Rows for a card with `data_source`: (real or all-synthetic rows, train-only synthetic gap rows,
    load info, manifest sources)."""
    src = card.data_source or {}
    c = cfg()
    labels = [lab.name for lab in card.labels]
    if src.get("kind") == "synthetic":
        if llm is None:
            raise SourcingError("Synthetic data needs the LLM client.")
        emit("Data", "data", f"No labeled dataset was chosen: Nemotron Ultra is writing about {c['synthetic_per_label']} "
             f"synthetic examples for each of the {len(labels)} labels")
        rows = generate_synthetic(card, labels, c["synthetic_per_label"], llm, emit)
        if not rows:
            raise SourcingError("Synthetic data generation returned no examples.")
        src_info = {"name": "synthetic (Nemotron Ultra)", "url": "generated", "license": "generated by Nemotron Ultra",
                    "license_ok": True, "rows_used": len(rows), "is_synthetic": True, "citation": []}
        return rows, [], {"raw_rows": len(rows), "synthetic_only": True}, [src_info]

    if src.get("kind") == "api":
        return _load_api_rows(card, src, llm, emit)
    if src.get("kind") != "hf" or not DATASET_ID.fullmatch(str(src.get("name", ""))):
        raise SourcingError("Unknown data source on the task card.")
    lic = license_of(hub_info(src["name"]))
    if not license_ok(lic):
        raise PermissionError(f"{src['name']}: license \"{lic}\" isn't on the allowlist")
    emit("Data", "data", f"Reading {src['name']} from Hugging Face (license {lic}, checked again now)")
    raw = fetch_rows(src, c["max_rows_fetched"])
    lmap = src.get("label_map") or {}
    rows = [{"id": r["id"], "text": r["text"], "label": lmap[r["source_label"]]}
            for r in raw if r["text"].strip() and lmap.get(r["source_label"]) in labels]
    emit("Data", "data", f"Kept {len(rows):,} of {len(raw):,} rows after mapping the dataset's labels onto the task's")
    rows, gap_rows, gaps = _fill_gaps(card, rows, llm, emit)
    sources = [{"name": src["name"], "url": src.get("url") or f"{c['hf_dataset_page']}/{src['name']}", "license": lic,
                "license_ok": True, "rows_used": len(rows), "is_synthetic": False,
                "citation": [f"{src['name']}, Hugging Face Hub, {src.get('url', '')}"]}]
    info = {"raw_rows": len(raw), "kept_after_label_map": len(rows), "label_map": lmap, "gap_labels": gaps,
            "config": src.get("config"), "splits_read": src.get("splits"),
            "processing": [f"read from the Hugging Face dataset viewer, sampled across {', '.join(src.get('splits') or [])}",
                           "mapped the dataset's labels onto the task's labels; unmapped labels dropped"]}
    return rows, gap_rows, info, sources + _gap_source(gap_rows)


def _fill_gaps(card: TaskCard, rows: list[dict], llm, emit: Emit) -> tuple[list[dict], list[dict], list[str]]:
    """Labels with too few real rows get synthetic examples in the training set only; their few real rows are
    dropped so a label isn't half real, half synthetic. Returns (real rows, gap rows, gap labels)."""
    c = cfg()
    counts = {lab.name: sum(r["label"] == lab.name for r in rows) for lab in card.labels}
    gaps = [lab for lab, n in counts.items() if n < c["min_rows_per_label"]]
    gap_rows: list[dict] = []
    if gaps and llm is not None:
        emit("Data", "data", f"{len(gaps)} label(s) have under {c['min_rows_per_label']} real rows ({', '.join(gaps)}); "
             "filling them with synthetic examples in the training set only")
        gap_rows = generate_synthetic(card, gaps, c["synthetic_per_label"], llm, emit)
        rows = [r for r in rows if r["label"] not in gaps]
    return rows, gap_rows, gaps


def _gap_source(gap_rows: list[dict]) -> list[dict]:
    return [{"name": "synthetic gap fill (Nemotron Ultra)", "url": "generated", "license": "generated by Nemotron Ultra",
             "license_ok": True, "rows_used": len(gap_rows), "is_synthetic": True, "citation": []}] if gap_rows else []


def _load_api_rows(card: TaskCard, src: dict, llm, emit: Emit):
    """Real items from a vetted API, labeled by the teacher (scores then measure agreement with the teacher)."""
    c = cfg()
    if not _api_filter_ok(src.get("source", ""), src.get("filter") or {}):
        raise SourcingError("Unknown API source on the task card.")
    spec = c["apis"][src["source"]]
    if not license_ok(spec["license"]):
        raise PermissionError(f"{spec['name']}: license \"{spec['license']}\" isn't on the allowlist")
    if llm is None:
        raise SourcingError("Teacher labeling needs the LLM client.")
    emit("Data", "data", f"Reading up to {c['api_items_fetched']} items from {src['name']} (license {spec['license']})")
    items = fetch_api(src, c["api_items_fetched"])
    if not items:
        raise SourcingError(f"{src['name']} returned no items.")
    teacher = teacher_name()
    emit("Data", "data", f"{teacher} is labeling {len(items):,} real items from the task card; scores then measure "
         "agreement with this teacher, and the report says so")
    rows = teacher_label(card, items, llm, emit)
    counts = {lab.name: sum(r["label"] == lab.name for r in rows) for lab in card.labels}
    emit("Data", "data", f"Teacher labels: " + ", ".join(f"{k} {v:,}" for k, v in counts.items()))
    rows, gap_rows, gaps = _fill_gaps(card, rows, llm, emit)
    sources = [{"name": src["name"], "url": spec["page"], "license": spec["license"], "license_ok": True,
                "rows_used": len(rows), "is_synthetic": False, "labeled_by": f"teacher ({teacher})",
                "citation": [spec["citation"]]}]
    info = {"raw_rows": len(items), "teacher_labeled": len(rows), "teacher": teacher, "gap_labels": gaps,
            "api": src["source"], "filter": src.get("filter"),
            "processing": [f"read {len(items):,} items from {spec['name']} ({spec['url']})",
                           f"labeled by the teacher ({teacher}) from the task card; scores measure agreement with it"]}
    return rows, gap_rows, info, sources + _gap_source(gap_rows)


def shuffle_split_synthetic(rows: list[dict], held_out_per_label: int, seed: int) -> tuple[list[dict], list[dict]]:
    """Gap-fill rows: most go to training, a few per label are kept aside to score on synthetic data."""
    rng = random.Random(seed)
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["label"], []).append(r)
    train, held = [], []
    for lab_rows in by.values():
        rng.shuffle(lab_rows)
        held += lab_rows[:held_out_per_label]
        train += lab_rows[held_out_per_label:]
    return train, held
