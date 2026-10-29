"""Business domains for every program, from the menu numbering (M1xxx order entry, M4xxx purchasing ...).

A program a menu runs belongs to that menu's domain. Every other program belongs to the domain whose menu
programs reach it through CALL/EXECUTE/CHAIN/ENTER (a few hops; nearer and busier entries count more).
Programs reached about evenly from three or more domains are the shared library.

No menu reaches most programs (batch jobs, phantoms, utilities, dead code). One that calls into a domain's
code is placed in that domain; one that touches no domain at all is "off the menus".
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from atlas.parse.program import is_gui_callee
from atlas.store.db import Store

# What each menu range is, judged by the programs its busiest menus run.
DOMAINS: dict[str, str] = {
    "1": "Order entry & invoicing",
    "2": "Pricing",
    "3": "Receivables",
    "4": "Purchasing & receiving",
    "5": "Inventory & products",
    "6": "Sales analysis",
    "7": "Customers",
    "8": "Tools & reports",
    "9": "System & admin",
}
SHARED, OFF = "shared", "off"
NAMES = {**DOMAINS, SHARED: "Shared library", OFF: "Off the menus"}
EDGE_KINDS = ("CALL", "EXECUTE", "CHAIN", "ENTER")
HOPS = 3            # how far an entry's reach counts
DECAY = 0.45        # each hop away counts this much less
SHARE = 0.15        # a domain with at least this share of a program's reach "uses" it
UTILITY = 60        # a routine with more callers than this is a utility: calling it places nobody
BELONG = 0.3        # a program no menu reaches joins a domain only on at least this much evidence

_CACHE: dict[str, Any] = {"key": None, "map": None}


def _domain_of(code: str) -> str | None:
    return code[1] if len(code) > 1 and code[0] == "M" and code[1] in DOMAINS else None


def build(store: Store) -> dict[str, str]:
    db = store.db
    names = [r["name"] for r in db.execute("SELECT name FROM program WHERE provenance='git' ORDER BY name")]
    known = set(names)

    # entries: each menu program, in the domain of its busiest menu
    entry: dict[str, tuple[str, int]] = {}
    for r in db.execute("SELECT code, program, used FROM menu WHERE program IS NOT NULL AND program <> ''"):
        d, p = _domain_of(r["code"]), r["program"].upper()
        if d is not None and p in known and (p not in entry or (r["used"] or 0) > entry[p][1]):
            entry[p] = (d, r["used"] or 0)

    # the call graph between indexed programs (GUI and I/O plumbing left out: everything calls those)
    out: dict[str, set[str]] = defaultdict(set)
    for r in db.execute(f"SELECT DISTINCT program, target FROM call_edge WHERE provenance='git' "
                        f"AND kind IN ({','.join('?' * len(EDGE_KINDS))})", EDGE_KINDS):
        a, b = r["program"], r["target"]
        if a != b and a in known and b in known and not is_gui_callee(b):
            out[a].add(b)

    # how hard each domain reaches every program
    score: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for p, (d, used) in entry.items():
        w = 1 + math.log1p(used)
        frontier, seen = [p], {p}
        for hop in range(1, HOPS + 1):
            nxt = []
            for q in frontier:
                for t in out.get(q, ()):
                    if t in seen or t in entry:
                        continue
                    seen.add(t)
                    nxt.append(t)
                    score[t][d] += w * DECAY ** (hop - 1)
            frontier = nxt

    dom: dict[str, str] = {p: d for p, (d, _) in entry.items()}
    for n, s in score.items():
        total = sum(s.values())
        dom[n] = SHARED if len([v for v in s.values() if v / total >= SHARE]) >= 3 else max(s, key=lambda k: s[k])

    # programs no menu reaches, placed by whose code they call (two hops). A routine everybody calls
    # (a product-description lookup, say) says little about where its caller belongs, so a callee's vote
    # shrinks with its number of callers, and the most-called don't vote at all.
    callers: dict[str, int] = defaultdict(int)
    for ts in out.values():
        for t in ts:
            callers[t] += 1

    def say(t: str) -> float:
        k = callers[t]
        return 0.0 if k > UTILITY else 1 / (1 + math.log1p(k))

    for n in names:
        if n in dom:
            continue
        votes: dict[str, float] = defaultdict(float)
        for t in out.get(n, ()):
            if dom.get(t) in DOMAINS:
                votes[dom[t]] += say(t)
            for t2 in out.get(t, ()):
                if dom.get(t2) in DOMAINS:
                    votes[dom[t2]] += 0.4 * say(t2)
        votes = {k: v for k, v in votes.items() if v >= BELONG}
        dom[n] = max(votes, key=lambda k: votes[k]) if votes else OFF
    return dom


def domain_map(store: Store) -> dict[str, str]:
    """Each program's domain: a menu range id, "shared" or "off". Changes only when the git index does."""
    key = (store.db.execute("SELECT last_sha FROM index_state WHERE source='git:erp'").fetchone() or [None])[0]
    if _CACHE["key"] != key or _CACHE["map"] is None:
        _CACHE.update(key=key, map=build(store))
    return _CACHE["map"]
