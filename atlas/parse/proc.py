"""PROC scripts in src/PROK: the TCL commands they run, the reports they print, the
programs and other procs they call, and hints of when they run.

PROC basics (Pick/UniVerse):
  PQ / PQN            header
  H<text>             append text to the command buffer ("H WITH..." continues it with a space)
  A / A"n / A1        insert user input (shown as <input>)
  P / PP / PX / PW    run the buffered command
  STON / STOFF        switch to the stacked (secondary) buffer: after a SELECT, the stacked H lines
                      are the next command, run with the select list active
  O<text> T (x,y),"t" output / screen text (used here as description)
  [PROK NAME]         call another proc; (PROK NAME) chains to it
PROC menus (e.g. *YEAREND) are records of captions / types (COM PRC PRG) / commands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_VM = ("\xef\xa3\xbd", "\xfd")
RETRIEVE = ("SORT", "LIST", "SSELECT", "SELECT", "COUNT", "SUM", "STAT", "SORT-LABEL", "LIST-LABEL", "LIST.ITEM",
            "SORT.ITEM", "QSELECT", "NSELECT")
DESTRUCTIVE = ("CLEAR-FILE", "CLEAR.FILE", "DELETE", "DELETE-FILE", "DELETE.FILE", "DELETE-LIST", "CLEARDATA")
RETRIEVE_WORDS = {"WITH", "AND", "OR", "BY", "BY-DSND", "BY-EXP", "BREAK-ON", "TOTAL", "HEADING", "FOOTING",
                  "LPTR", "ID-SUPP", "DET-SUPP", "COL-HDR-SUPP", "NI-SUPP", "HDR-SUPP", "COUNT-SUP", "ONLY",
                  "EVERY", "EACH", "WHEN", "NO", "NOT", "EQ", "NE", "GT", "GE", "LT", "LE", "LIKE", "UNLIKE",
                  "BETWEEN", "AFTER", "BEFORE", "IF", "ALL", "SAMPLE", "SAMPLED", "TO", "FROM", "USING", "DICT",
                  "BY-EXP-DSND", "AVERAGE", "PERCENT", "MAX", "MIN", "ENUM", "CALC", "GRAND-TOTAL", "SUPP",
                  "VERTICALLY", "DBL-SPC", "ROLL-ON", "BREAK-SUP", "OF", "IN", "INCLUDE"}


@dataclass
class Command:
    line: int
    text: str
    kind: str                     # run | proc | report | select | destructive | sleep | spool | tcl
    target: str = ""              # program, proc, or Pick file
    heading: str = ""
    printed: bool = False
    columns: list[str] = field(default_factory=list)
    criteria: str = ""


@dataclass
class Proc:
    name: str
    kind: str                     # proc | menu | other
    title: str
    description: str
    commands: list[Command]
    menu_items: list[dict[str, str]]
    lines: int


def _clean_output(s: str) -> str:
    s = re.sub(r'^\(\s*-?\d+\s*,\s*-?\d+\s*\)\s*,?', "", s.strip())   # T (0,6),"..."
    s = s.strip().strip(",").strip()
    if s.startswith("C,"):
        s = s[2:]
    s = s.strip().strip('"').strip("'").rstrip("+").strip()
    return re.sub(r"^[*=\- ]+|[*=\- ]+$", "", s).strip()                # ****** TITLE ******


def _classify(cmd: str, line: int) -> Command:
    t = " ".join(cmd.split())
    up = t.upper()
    words = up.split()
    first = words[0] if words else ""
    c = Command(line, t, "tcl")
    if first == "RUN" and len(words) >= 3:
        c.kind, c.target = "run", words[2]
    elif first in ("PROK", "EXEC", "DO") and len(words) >= 2:
        c.kind, c.target = "proc", words[1]
    elif first in RETRIEVE and len(words) >= 2:
        c.target = words[1] if words[1] != "DICT" or len(words) < 3 else words[2]
        m = re.search(r'HEADING\s+"([^"]*)"', t, re.I) or re.search(r"HEADING\s+'([^']*)'", t, re.I)
        c.heading = re.sub(r"\bPAGE\b.*$", "", re.sub(r"'[A-Z]*'", " ", m.group(1))).strip() if m else ""
        c.printed = " LPTR" in f" {up}" or "(P" in up
        c.kind = "report" if (c.heading or c.printed or first in ("SORT", "LIST", "COUNT", "SUM", "STAT")
                              ) and first not in ("SSELECT", "SELECT", "QSELECT", "NSELECT") else "select"
        crit = re.search(r"\b(WITH|IF)\b(.*?)(?=\b(BY|BY-DSND|BREAK-ON|TOTAL|HEADING|ID-SUPP|DET-SUPP|LPTR)\b|$)", t,
                         re.I)
        c.criteria = crit.group(0).strip() if crit else ""
        body = re.sub(r'"[^"]*"|\'[^\']*\'', " ", t.replace(c.criteria, " ") if c.criteria else t)
        for w in body.split()[2:]:
            wu = w.upper().strip("()")
            junk = "=" in wu or "<" in wu or re.fullmatch(r"[\d.>#*]+", wu)
            if wu and wu not in RETRIEVE_WORDS and not junk and wu not in c.columns:
                c.columns.append(wu)
    elif first in DESTRUCTIVE:
        c.kind, c.target = "destructive", words[1] if len(words) > 1 else ""
    elif first == "SLEEP":
        c.kind = "sleep"
    elif first in ("SP-ASSIGN", "SETPTR", "SP-EDIT", "SP-TAPEOUT"):
        c.kind = "spool"
    elif first == "PHANTOM":
        c.kind = "run"
        rest = words[1:]
        if len(rest) >= 3 and rest[0] == "RUN":
            c.target = rest[2]
        elif rest:
            c.kind, c.target = "proc", rest[0]
    elif first and re.fullmatch(r"[A-Z][A-Z0-9.\-_$]*", first) and len(words) <= 6:
        c.kind, c.target = "call", first           # a cataloged program or verb; resolved against BP later
    return c


def parse_proc(text: str, name: str) -> Proc:
    raw_lines = text.splitlines()
    lines = [ln.rstrip("\r") for ln in raw_lines]
    head = lines[0].strip().upper() if lines else ""
    if not head.startswith("PQ"):
        return _parse_menu_record(lines, name)
    cmds: list[Command] = []
    buf, start, stacked = "", 0, False
    sbuf, sstart = "", 0
    outputs: list[str] = []
    title = ""

    def flush() -> None:
        nonlocal buf, sbuf, stacked
        if buf.strip():
            cmds.append(_classify(buf, start))
        if sbuf.strip():
            cmds.append(_classify(sbuf, sstart))
        buf, sbuf, stacked = "", "", False

    for i, ln in enumerate(lines[1:], 2):
        s = ln.strip()
        s = re.sub(r"^\d+\s+", "", s)                       # PROC labels: "10 T C"
        if not s:
            continue
        up = s.upper()
        for m in re.finditer(r"[\[(]\s*PROK\s+([^\])\s]+)", s, re.I):
            cmds.append(Command(i, m.group(0).strip("[]()"), "proc", m.group(1).upper()))
        if up.startswith("STON"):
            stacked = True
            continue
        if up.startswith("STOFF"):
            stacked = False
            continue
        if up.startswith("H") and not up.startswith("HALT"):
            piece = s[1:]
            if stacked:
                if not sbuf:
                    sstart = i
                sbuf += piece if not sbuf or piece.startswith(" ") else " " + piece
            else:
                if not buf:
                    start = i
                buf += piece
            continue
        if re.fullmatch(r"A(\d*|\"\d+|\(\d+,?\d*\))?", up) or re.fullmatch(r"A\d*,\d+", up):
            if stacked:
                sbuf += "<input>"
            else:
                buf += "<input>"
            continue
        if up in ("P", "PP", "PX", "PW", "PH") or re.fullmatch(r"P[PXWH]?", up):
            flush()
            continue
        if up.startswith("T ") or up.startswith("O"):
            txt = _clean_output(s[1:] if up.startswith("O") else s[2:])
            if up.startswith("T C") and "," in s and not title:
                title = _clean_output(s.split(",", 1)[1])
            if txt and len(txt) > 2 and not re.fullmatch(r"[*=\- ]+", txt):
                outputs.append(txt)
    flush()
    desc = " ".join(o for o in outputs[:6] if not o.endswith("?") and "ENTER" not in o.upper()[:12])[:400]
    if not title:      # first output that reads like a title, not a prompt ("PASSWORD")
        title = next((o for o in outputs if len(o.split()) >= 3 and "ENTER" not in o.upper()), outputs[0] if outputs
                     else "")
    return Proc(name, "proc", title, desc, cmds, [], len(lines))


def _parse_menu_record(lines: list[str], name: str) -> Proc:
    """Old-style menu records: title line, then @VM lists of captions, types and commands."""
    def split(s: str) -> list[str]:
        for m in _VM[1:]:
            s = s.replace(m, _VM[0])
        return s.split(_VM[0])
    title = lines[0].strip() if lines else ""
    lists = [split(ln) for ln in lines]
    caps = next((row for row in lists if len(row) > 3 and sum(1 for x in row if re.search(r"[a-z]", x)) > 2), [])
    types = next((row for row in lists if len(row) > 3 and all(x in ("COM", "PRC", "PRG", "") for x in row)), [])
    cmd_rx = re.compile(r"^(RUN |PROK |[A-Z][A-Z0-9.\-_$]*( |$))")

    def commandish(row: list[str]) -> int:
        return sum(1 for x in row if x.strip() and x == x.upper() and cmd_rx.match(x))
    rest = [row for row in lists if row is not caps and row is not types and len(row) > 3]
    cmds_row = max(rest, key=commandish, default=[]) if rest else []
    if cmds_row and commandish(cmds_row) < 2:
        cmds_row = []
    items, cmds = [], []
    for i, cap in enumerate(caps):
        cmd = cmds_row[i] if i < len(cmds_row) else ""
        items.append({"caption": cap.strip(), "type": types[i] if i < len(types) else "", "command": cmd.strip()})
        if cmd.strip():
            cmds.append(_classify(cmd, 0))
    kind = "menu" if items else "other"
    return Proc(name, kind, title[:120], "", cmds, items, len(lines))


SCHEDULE_WORDS = [
    ("nightly", r"NIGHT|GOODNIGHT|SLEEP"), ("year-end", r"YEAR.?END|EOY|YE-|YREND"),
    ("month-end", r"\bEOM|MONTHLY|MONTH.?END|LAMO|CLOSE MONTH"), ("weekly", r"WEEKLY|\bWEEK\b"),
    ("daily", r"DAILY|\bDAY\b|EOD"),
]


def schedule_of(p: Proc, extra: str = "") -> str:
    """Name first (DAILY-CASH is daily even if its text mentions a night run), then SLEEP (waits for
    the night), then the title/description."""
    for text in (p.name.upper(), None, " ".join([p.title, p.description, extra]).upper()):
        if text is None:
            if any(c.kind == "sleep" for c in p.commands):
                return "nightly"
            continue
        for label, rx in SCHEDULE_WORDS:
            if re.search(rx, text):
                return label
    return "on demand"


def summary(p: Proc) -> dict[str, Any]:
    return {"name": p.name, "kind": p.kind, "title": p.title, "description": p.description, "lines": p.lines,
            "commands": [c.__dict__ for c in p.commands], "menu_items": p.menu_items}
