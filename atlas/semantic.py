"""Search by meaning: "where is freight calculated" finds the program even when nothing in it says freight.

What is searched is what Atlas has written down in words: program and section summaries, and facts. Each is
turned into a vector by a small embedding model that runs on this machine (no code or text leaves it); a query
is turned into a vector the same way and compared with all of them. Vectors are kept in SQLite with the hash of
the text they came from, so only new or changed text is re-embedded.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import threading
from collections.abc import Callable
from typing import Any

from atlas.config import ROOT
from atlas.store.db import Store

# numpy's type stubs need Python 3.12 syntax and mypy checks against 3.11, so load it untyped
np: Any = importlib.import_module("numpy")

Result = dict[str, Any]
MODEL = "BAAI/bge-small-en-v1.5"
CACHE = ROOT / ".data" / "models"
MIN_SCORE = 0.6                # below this a match is noise for this model (bge-small scores bunch up)

_lock = threading.Lock()
_model: Any = None
_matrix: tuple[tuple[int, int], list[tuple[str, str]], Any] | None = None   # (signature, keys, vectors)


def _embedder() -> Any:
    """The embedding model, loaded once (downloaded into .data/models the first time)."""
    global _model
    with _lock:
        if _model is None:
            fastembed = importlib.import_module("fastembed")      # untyped, like numpy above
            _model = fastembed.TextEmbedding(MODEL, cache_dir=str(CACHE))
        return _model


def available() -> bool:
    """Has the model been fetched? Searching never triggers the download; building the index does."""
    return CACHE.exists() and any(CACHE.rglob("*.onnx"))


def _h(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def documents(store: Store) -> dict[tuple[str, str], str]:
    """Everything searchable, as {(kind, key): text}."""
    docs: dict[tuple[str, str], str] = {}
    for r in store.db.execute("SELECT * FROM summary"):
        terms = ", ".join(json.loads(r["terms"]))
        if r["kind"] == "program":
            docs[("program", r["program"])] = f"{r['program']}: {r['title']}. {r['summary']} Terms: {terms}"
        else:
            key = f"{r['program']}:{r['start_line']}-{r['end_line']}"
            docs[("section", key)] = f"{r['program']} lines {r['start_line']}-{r['end_line']}: {r['title']}. " \
                                     f"{r['summary']} Terms: {terms}"
    for r in store.db.execute("SELECT id, text, scope FROM fact WHERE status != 'retired'"):
        docs[("fact", r["id"])] = f"{r['text']} ({r['scope'] or ''})"
    return docs


def index(store: Store, log: Callable[[str], None] | None = None) -> Result:
    """Embed new and changed text, drop vectors for text that's gone."""
    say = log or (lambda _m: None)
    docs = documents(store)
    have = {(r["kind"], r["key"]): r["text_hash"] for r in store.db.execute(
        "SELECT kind, key, text_hash FROM embedding WHERE model=?", (MODEL,))}
    todo = [(k, t) for k, t in docs.items() if have.get(k) != _h(t)]
    gone = [k for k in have if k not in docs]
    for k in gone:
        store.db.execute("DELETE FROM embedding WHERE kind=? AND key=?", k)
    if todo:
        say(f"Updating the meaning index: {len(todo)} new or changed" + ("" if available() else
            " (fetching the search model the first time, about 70 MB)"))
        model = _embedder()
        for i in range(0, len(todo), 128):
            chunk = todo[i:i + 128]
            vecs = list(model.passage_embed([t for _, t in chunk]))
            for (k, t), v in zip(chunk, vecs, strict=True):
                store.db.execute("INSERT OR REPLACE INTO embedding VALUES (?,?,?,?,?)",
                                 (k[0], k[1], _h(t), MODEL, np.asarray(v, dtype=np.float32).tobytes()))
            store.commit()
    store.commit()
    n = store.db.execute("SELECT COUNT(*) n FROM embedding WHERE model=?", (MODEL,)).fetchone()["n"]
    say(f"Meaning index: {n} entries ({len(todo)} updated, {len(gone)} removed)")
    return {"entries": n, "updated": len(todo), "removed": len(gone)}


def _vectors(store: Store) -> tuple[list[tuple[str, str]], Any]:
    """All vectors as one normalised matrix, reloaded only when the table changes."""
    global _matrix
    sig = tuple(store.db.execute("SELECT COUNT(*), COALESCE(MAX(rowid),0) FROM embedding WHERE model=?",
                                 (MODEL,)).fetchone())
    if _matrix is None or _matrix[0] != sig:
        rows = store.db.execute("SELECT kind, key, vec FROM embedding WHERE model=?", (MODEL,)).fetchall()
        keys = [(r["kind"], r["key"]) for r in rows]
        m = np.vstack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows]) if rows else np.zeros((0, 384))
        m = m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
        _matrix = ((int(sig[0]), int(sig[1])), keys, m)
    return _matrix[1], _matrix[2]


def search(store: Store, q: str, limit: int = 10, kinds: tuple[str, ...] = ("program", "section", "fact")) -> Result:
    """The closest summaries and facts to a description, best first, with what they say and where to look."""
    q = q.strip()
    if not q:
        return {"query": q, "ready": True, "results": []}
    if not available() or not store.db.execute("SELECT 1 FROM embedding LIMIT 1").fetchone():
        return {"query": q, "ready": False, "results": [],
                "note": "The meaning index is empty: an admin writes summaries on the Admin page first."}
    keys, m = _vectors(store)
    qv = np.asarray(next(iter(_embedder().query_embed([q]))), dtype=np.float32)
    scores = m @ (qv / max(float(np.linalg.norm(qv)), 1e-9))
    out: list[Result] = []
    seen: set[str] = set()
    for i in np.argsort(-scores):
        if float(scores[i]) < MIN_SCORE or len(out) >= limit:
            break
        kind, key = keys[i]
        if kind not in kinds:
            continue
        r = _describe(store, kind, key)
        if r is None:
            continue
        # one program shouldn't fill the list: keep its best hit (whole program or a section)
        prog = r.get("program") or key
        if kind != "fact" and prog in seen:
            continue
        seen.add(prog)
        out.append({**r, "score": round(float(scores[i]), 3)})
    return {"query": q, "ready": True, "results": out}


def _describe(store: Store, kind: str, key: str) -> Result | None:
    if kind == "fact":
        f = store.db.execute("SELECT id, text, status FROM fact WHERE id=?", (key,)).fetchone()
        return {"kind": "fact", "id": f["id"], "text": f["text"], "status": f["status"]} if f else None
    if kind == "program":
        prog, start = key, 0
    else:
        prog, rng = key.rsplit(":", 1)
        start = int(rng.split("-")[0])
    s = store.db.execute("SELECT s.*, p.hash cur FROM summary s LEFT JOIN program p ON p.provenance='git' "
                         "AND p.name=s.program WHERE s.kind=? AND s.program=? AND s.start_line=?",
                         (kind, prog, start)).fetchone()
    if s is None:
        return None
    return {"kind": kind, "program": prog, "start": s["start_line"] or None, "end": s["end_line"] or None,
            "title": s["title"], "summary": s["summary"], "highlights": json.loads(s["highlights"])[:3],
            "stale": s["cur"] is not None and s["cur"] != s["source_hash"]}
