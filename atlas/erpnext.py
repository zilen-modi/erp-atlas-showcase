"""ERP Next: the BASIC the new system calls, and the old code it still depends on.

The ERP Next API calls subroutines kept in the ERP repo under src/next (api-helpers, utilities). Many reuse
business logic from the old programs (LG.GETCOST, LG.QTY.CALC...). Following their CALLs shows which old programs
the new system still needs: those can't be retired until the logic is rebuilt on the new side.

Dependencies are followed a few hops through CALL / EXECUTE / CHAIN / ENTER, skipping GUI and record-lock
plumbing (IOREADU, ATGUI*...), which every program uses and says nothing about business logic.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from atlas import query
from atlas.parse.program import is_gui_callee
from atlas.store.db import Store
from atlas.sync import FOLDER_LABEL

Result = dict[str, Any]
NEXT_DIRS = ("src/next/api-helpers", "src/next/utilities")
DEPTH = 3
CALLS = ("CALL", "EXECUTE", "CHAIN", "ENTER")
WRITES = {"WRITE", "WRITEU", "WRITEV", "WRITEVU", "MATWRITE", "MATWRITEU", "DELETE"}


def _helpers(store: Store) -> dict[str, str]:
    """name -> folder label, for every program kept under src/next."""
    out = {}
    for r in store.db.execute("SELECT name, path FROM source_file WHERE provenance='git' AND kind='BP' "
                              "AND path LIKE 'src/next/%'"):
        out[r["name"].upper()] = next((FOLDER_LABEL[d] for d in NEXT_DIRS if r["path"].startswith(d + "/")), "ERP Next")
    return out


def overview(store: Store) -> Result:
    helpers = _helpers(store)
    names = list(helpers)
    known = {r["name"]: r for r in store.db.execute(
        "SELECT name, kind, params, line_count FROM program WHERE provenance='git'")}
    summaries = {r["program"]: {"title": r["title"], "stale": r["source_hash"] != r["hash"]} for r in store.db.execute(
        "SELECT s.program, s.title, s.source_hash, p.hash FROM summary s JOIN program p ON p.provenance='git' "
        "AND p.name=s.program WHERE s.kind='program'")}
    edges: dict[str, set[str]] = defaultdict(set)
    for r in store.db.execute(f"SELECT program, target FROM call_edge WHERE provenance='git' AND kind IN "
                              f"({','.join('?' * len(CALLS))})", CALLS):
        if not is_gui_callee(r["target"]):
            edges[r["program"]].add(r["target"])

    # walk out from each helper: which old programs does it reach, and how far down
    needed: dict[str, Result] = {}
    for h in names:
        frontier, seen = {h}, {h}
        for depth in range(1, DEPTH + 1):
            nxt = set()
            for p in frontier:
                for t in edges.get(p, ()):
                    if t in seen or t in helpers:
                        continue
                    seen.add(t)
                    nxt.add(t)
                    d = needed.setdefault(t, {"program": t, "depth": depth, "via": set(), "indexed": t in known})
                    d["depth"] = min(d["depth"], depth)
                    d["via"].add(h)
            frontier = nxt
    usage = query.usage_map(store)
    drifted = {r["program"] for r in store.db.execute(
        "SELECT DISTINCT program FROM drift WHERE class IN ('logic','git-only','live-only')")}
    deps = sorted(({**d, "via": sorted(d["via"]), "lines": known[d["program"]]["line_count"] if d["indexed"] else None,
                    "launches": usage.get(d["program"]), "summary": summaries.get(d["program"]),
                    "test_differs": d["program"] in drifted} for d in needed.values()),
                  key=lambda d: (d["depth"], -len(d["via"]), -(d["launches"] or 0), d["program"]))

    # the Pick files the helpers read and write themselves
    files: dict[str, Result] = {}
    io = store.db.execute(f"SELECT program, op, pick_file FROM io_op WHERE provenance='git' AND pick_file IS NOT "
                          f"NULL AND program IN ({','.join('?' * len(names))})", names) if names else []
    for r in io:
        f = files.setdefault(r["pick_file"], {"file": r["pick_file"], "reads": set(), "writes": set()})
        (f["writes"] if r["op"] in WRITES else f["reads"]).add(r["program"])
    by_helper_files: dict[str, set[str]] = defaultdict(set)
    for f in files.values():
        for p in f["reads"] | f["writes"]:
            by_helper_files[p].add(f["file"])

    rows = []
    for h in sorted(names):
        k = known.get(h)
        rows.append({"program": h, "folder": helpers[h], "kind": k["kind"] if k else None,
                     "lines": k["line_count"] if k else None, "summary": summaries.get(h),
                     "calls": sorted(t for t in edges.get(h, ()) if t not in helpers),
                     "uses_helpers": sorted(t for t in edges.get(h, ()) if t in helpers),
                     "files": sorted(by_helper_files.get(h, ()))})
    return {
        "helpers": rows,
        "depends_on": deps,
        "files": sorted(({"file": f["file"], "reads": sorted(f["reads"]), "writes": sorted(f["writes"])}
                         for f in files.values()), key=lambda f: (-len(f["writes"]), f["file"])),
        "totals": {"helpers": len(names), "old_programs": len(deps),
                   "direct": sum(1 for d in deps if d["depth"] == 1), "files": len(files),
                   "summarised": sum(1 for h in names if h in summaries)},
        "depth": DEPTH,
    }
