"""SQLite access: connection, blob storage, and replacing a program's facts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from atlas.parse.program import ProgramFacts

SCHEMA = Path(__file__).with_name("schema.sql")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def line_hash(line: str) -> str:
    return hashlib.sha256(line.rstrip().encode("utf-8", "surrogatepass")).hexdigest()[:16]


class Store:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: a streamed response may resume on another worker thread;
        # each Store is still used by one request at a time.
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA.read_text())
        self._migrate()

    def _migrate(self) -> None:
        """Columns added after a table first shipped (CREATE IF NOT EXISTS won't add them)."""
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(dict_attr)")}
        for col in ("definition", "format", "depth", "assoc"):
            if col not in have:
                self.db.execute(f"ALTER TABLE dict_attr ADD COLUMN {col} TEXT")
        # since sign-in: whose a saved search is (and whether the team sees it), and who looked something up
        for table, col, decl in (("finder_scenario", "user_id", "TEXT"),
                                 ("finder_scenario", "shared", "INTEGER NOT NULL DEFAULT 0"),
                                 ("activity", "user_id", "TEXT"), ("report", "user_id", "TEXT")):
            if col not in {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # -- index state -------------------------------------------------------

    def get_state(self, source: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self.db.execute(
            "SELECT * FROM index_state WHERE source=?", (source,)).fetchone()
        return row

    def set_state(self, source: str, ref: str, sha: str | None, note: str = "") -> None:
        self.db.execute("INSERT OR REPLACE INTO index_state VALUES (?,?,?,?,?)",
                        (source, ref, sha, now(), note))

    # -- source ------------------------------------------------------------

    def put_source(self, provenance: str, kind: str, name: str, path: str, text: str,
                   sha: str | None = None, fetched_at: str | None = None) -> str:
        h = text_hash(text)
        self.db.execute("INSERT OR IGNORE INTO blob VALUES (?,?)", (h, text))
        self.db.execute(
            "INSERT OR REPLACE INTO source_file VALUES (?,?,?,?,?,?,?,?)",
            (provenance, kind, name, path, h, len(text.splitlines()), sha, fetched_at or now()))
        return h

    def source(self, provenance: str, kind: str, name: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self.db.execute(
            "SELECT s.*, b.text FROM source_file s JOIN blob b ON b.hash=s.hash "
            "WHERE provenance=? AND kind=? AND name=?", (provenance, kind, name)).fetchone()
        return row

    def source_lines(self, provenance: str, name: str, kind: str = "BP") -> list[str] | None:
        row = self.source(provenance, kind, name)
        return None if row is None else str(row["text"]).splitlines()

    def delete_source(self, provenance: str, kind: str, name: str) -> None:
        self.db.execute("DELETE FROM source_file WHERE provenance=? AND kind=? AND name=?",
                        (provenance, kind, name))
        if kind == "BP":
            self.delete_program(provenance, name)

    # -- program facts -----------------------------------------------------

    def delete_program(self, provenance: str, name: str) -> None:
        for t in ("program", "label", "call_edge", "file_handle", "io_op", "attr_ref"):
            col = "name" if t == "program" else "program"
            self.db.execute(f"DELETE FROM {t} WHERE provenance=? AND {col}=?", (provenance, name))

    def put_program(self, provenance: str, pf: ProgramFacts, h: str) -> None:
        self.delete_program(provenance, pf.name)
        db, p, n = self.db, provenance, pf.name
        db.execute("INSERT INTO program VALUES (?,?,?,?,?,?)",
                   (p, n, pf.kind, json.dumps(pf.params), pf.line_count, h))
        db.executemany("INSERT INTO label VALUES (?,?,?,?)",
                       [(p, n, k, v) for k, v in pf.labels.items()])
        db.executemany("INSERT INTO call_edge VALUES (?,?,?,?,?,?)",
                       [(p, n, e.kind, e.target, e.line, e.nargs) for e in pf.edges])
        db.executemany("INSERT INTO file_handle VALUES (?,?,?,?,?,?)",
                       [(p, n, v, f, ln, via) for v, f, ln, via in pf.handles])
        fh = pf.file_of_handle()
        rows = []
        for op in pf.io:
            files: list[str | None] = [*sorted(op.files(fh))] or [None]
            for f in files:
                rows.append((p, n, op.line, op.op, op.file_var, f, op.record_var, op.key, op.attr, op.via))
        db.executemany("INSERT INTO io_op VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        rb = pf.record_bindings()
        arows = []
        for a in pf.attrs:
            bound: list[str | None] = [*sorted(rb.get(a.var, set()))] or [None]
            for f in bound:
                arows.append((p, n, a.line, a.var, f, a.attr, a.value, a.access))
        db.executemany("INSERT INTO attr_ref VALUES (?,?,?,?,?,?,?,?)", arows)

    def commit(self) -> None:
        self.db.commit()
