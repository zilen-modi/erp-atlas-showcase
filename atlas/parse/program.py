"""Extract structural facts from one Pick BASIC program.

Flow-insensitive and one hop deep, like lintbasic: every fact is a (line,
statement) observation with no attempt to decide which path reaches it.  What
it extracts:

  * signature        SUBROUTINE / FUNCTION / PROGRAM header and parameters
  * labels           `NAME:` and numeric `100` / `100:` statement labels
  * edges            CALL, GOSUB, GOTO/GO, ON..GOSUB/GOTO, EXECUTE/PERFORM "RUN BP x", CHAIN, ENTER
  * file handles     CALL *OPEN.FILE('X',FV) (legacy `( ' X' , FV)` spacing too), OPEN 'X' TO FV
  * io ops           READ*/MATREAD*/WRITE*/MATWRITE*/DELETE*, plus the W5 wrappers
                     IOREADU(opt,key,field,FV,app,DATA,..) and IORELEASE(opt,key,field,FV,app,DATA,..)
  * attribute refs   REC<n[,m]> reads and writes, REC(n) for MAT-read arrays

Attribute refs are resolved to Pick files afterwards: a record variable is
bound to every file it is READ from or WRITten to in the same program.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from atlas.parse._lintbasic import (
    _inside_parens,
    _is_op,
    _is_word,
    _label_key,
    _lhs_assign,
    _split_commas,
    tokenize_marked,
)

Tok = tuple[str, str, int]

READ_OPS = frozenset("READ READU READL READV READVU READVL MATREAD MATREADU MATREADL".split())
WRITE_OPS = frozenset("WRITE WRITEU WRITEV WRITEVU MATWRITE MATWRITEU".split())
DELETE_OPS = frozenset("DELETE DELETEU".split())
IO_STOP = frozenset("ELSE THEN LOCKED ON SETTING".split())   # `ON ERROR` ends the operand list too
GUI_PREFIX = ("ATGUI", "W4GUI", "W5GUI")

_RUN_RE = re.compile(r"^\s*RUN\s+(\S+)\s+(\S+)", re.IGNORECASE)


@dataclass
class Edge:
    kind: str        # CALL GOSUB GOTO EXECUTE CHAIN ENTER
    target: str
    line: int
    nargs: int | None = None


@dataclass
class IoOp:
    line: int
    op: str          # READ READU READV MATREAD WRITE WRITEV DELETE ... (W5 wrappers normalised)
    file_var: str | None
    record_var: str | None
    key: str
    attr: int | None = None      # READV/WRITEV field number when literal
    via: str = ""                # "" or IOREADU / IORELEASE
    file_name: str | None = None  # the Pick file named outright (W5 wrappers take "PRODUCT" as well as a handle)

    def files(self, handles: dict[str, set[str]]) -> set[str]:
        """The Pick file(s) this operation touches."""
        return {self.file_name} if self.file_name else handles.get(self.file_var or "", set())


@dataclass
class AttrRef:
    line: int
    var: str
    attr: int
    value: str | None
    access: str      # read | write


@dataclass
class ProgramFacts:
    name: str
    kind: str = "NONE"                    # SUBROUTINE FUNCTION PROGRAM NONE
    params: list[str] = field(default_factory=list)
    line_count: int = 0
    labels: dict[str, int] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    handles: list[tuple[str, str, int, str]] = field(default_factory=list)   # var, file, line, via
    io: list[IoOp] = field(default_factory=list)
    attrs: list[AttrRef] = field(default_factory=list)
    mat_vars: set[str] = field(default_factory=set)
    executes: list[tuple[int, str]] = field(default_factory=list)          # raw EXECUTE text

    # -- derived ---------------------------------------------------------

    def file_of_handle(self) -> dict[str, set[str]]:
        m: dict[str, set[str]] = defaultdict(set)
        for var, f, _line, _via in self.handles:
            m[var].add(f)
        return m

    def record_bindings(self) -> dict[str, set[str]]:
        """record variable -> Pick files it is read from / written to."""
        fh = self.file_of_handle()
        out: dict[str, set[str]] = defaultdict(set)
        for op in self.io:
            if op.record_var:
                out[op.record_var] |= op.files(fh)
        return out

    def blocks(self) -> list[tuple[str, int, int]]:
        """(label, start, end) spans; the code before the first label is MAIN."""
        starts = sorted((ln, name) for name, ln in self.labels.items())
        spans: list[tuple[str, int, int]] = []
        prev_name, prev_ln = "(main)", 1
        for ln, name in starts:
            if ln > prev_ln:
                spans.append((prev_name, prev_ln, ln - 1))
            prev_name, prev_ln = name, ln
        spans.append((prev_name, prev_ln, max(self.line_count, prev_ln)))
        return spans


def _unquote(tok: Tok) -> str:
    t = tok[1]
    if t and t[0] in "\"'\\":
        t = t[1:-1] if len(t) >= 2 and t[-1] == t[0] else t[1:]
    return t.strip()


def _text(toks: list[Tok]) -> str:
    return " ".join(t[1] for t in toks)


def _first_var(toks: list[Tok]) -> str | None:
    toks = [t for t in toks if not _is_word(t, "MAT")]
    if toks and toks[0][0] == "ID":
        return toks[0][1]
    return None


def _upto(toks: list[Tok], words: frozenset[str]) -> list[Tok]:
    depth = 0
    for i, t in enumerate(toks):
        if t[0] == "OP" and t[1] in "([<":
            depth += 1
        elif t[0] == "OP" and t[1] in ")]>":
            depth -= 1
        elif depth <= 0 and t[0] == "ID" and t[1] in words:
            return toks[:i]
    return toks


def _int(tok: Tok | None) -> int | None:
    if tok and tok[0] == "NUM" and tok[1].isdigit():
        return int(tok[1])
    return None


def _angle_refs(toks: list[Tok], line: int, skip_until: int = 0) -> list[AttrRef]:
    """Every VAR<n[,m]> read in a token run.  `>=` (glued by the lexer) also closes."""
    refs: list[AttrRef] = []
    i = skip_until
    n = len(toks)
    while i < n - 2:
        t = toks[i]
        if t[0] == "ID" and _is_op(toks[i + 1], "<"):
            attr = _int(toks[i + 2])
            if attr is not None and i + 3 < n:
                nxt = toks[i + 3]
                value = None
                if _is_op(nxt, ",") and i + 4 < n:
                    value = toks[i + 4][1]
                    close_at = i + 5
                else:
                    close_at = i + 3
                if close_at < n and toks[close_at][0] == "OP" and toks[close_at][1] in (">", ">="):
                    refs.append(AttrRef(line, t[1], attr, value, "read"))
                    i = close_at + 1
                    continue
        i += 1
    return refs


def parse_program(name: str, lines: list[str]) -> ProgramFacts:
    pf = ProgramFacts(name=name, line_count=len(lines))
    header_seen = False
    for lineno, raw in enumerate(lines, 1):
        try:
            marked = tokenize_marked(raw)
        except Exception:
            continue
        for idx, (_opener, toks) in enumerate(marked):
            if not toks:
                continue
            # -- statement labels ------------------------------------------
            if idx == 0:
                if len(toks) >= 2 and toks[0][0] in ("ID", "NUM") and _is_op(toks[1], ":"):
                    pf.labels.setdefault(_label_key(toks[0]), lineno)
                    toks = toks[2:]
                elif toks[0][0] == "NUM":
                    pf.labels.setdefault(_label_key(toks[0]), lineno)
                    toks = toks[1:]
            if not toks:
                continue
            _statement(pf, toks, lineno, header_seen)
            header_seen = True
    _resolve_mat_refs(pf, lines)
    return pf


def _statement(pf: ProgramFacts, toks: list[Tok], ln: int, header_seen: bool) -> None:
    head = toks[0]
    if head[0] != "ID":
        return
    w = head[1]
    rest = toks[1:]

    if w in ("SUBROUTINE", "FUNCTION", "PROGRAM") and not header_seen:
        pf.kind = w
        pf.params = [p[-1][1] for p in _split_commas(_inside_parens(rest)) if p]
        return
    if w == "CALL":
        _call(pf, rest, ln)
        return
    if w in ("GOSUB", "GOTO", "GO"):
        _branches(pf, "GOSUB" if w == "GOSUB" else "GOTO", rest, ln)
        return
    if w == "ON":
        for i, t in enumerate(rest):
            if t[0] == "ID" and t[1] in ("GOSUB", "GOTO", "GO"):
                _branches(pf, "GOSUB" if t[1] == "GOSUB" else "GOTO", rest[i + 1:], ln)
                break
        return
    if w in ("EXECUTE", "PERFORM", "CHAIN", "ENTER"):
        _execute(pf, w, rest, ln)
        return
    if w == "OPEN":
        _open(pf, rest, ln)
        return
    if w in ("DIM", "DIMENSION"):
        for part in _split_commas(rest):
            if part and part[0][0] == "ID":
                pf.mat_vars.add(part[0][1])
        return
    if w in READ_OPS or w in WRITE_OPS or w in DELETE_OPS:
        _io(pf, w, rest, ln)
        pf.attrs.extend(_angle_refs(toks, ln, 1))
        return

    # -- assignment: REC<n[,m]> = ...  -------------------------------------
    la = _lhs_assign(toks)
    if la is not None:
        idx, _op, partial = la
        if partial and len(toks) > 2 and _is_op(toks[1], "<"):
            attr = _int(toks[2])
            if attr is not None:
                value = toks[4][1] if len(toks) > 4 and _is_op(toks[3], ",") else None
                pf.attrs.append(AttrRef(ln, w, attr, value, "write"))
        pf.attrs.extend(_angle_refs(toks, ln, idx + 1))
        return
    pf.attrs.extend(_angle_refs(toks, ln))


def _call(pf: ProgramFacts, rest: list[Tok], ln: int) -> None:
    i = 0
    if rest and _is_op(rest[0], "*"):
        i = 1
    if i >= len(rest) or rest[i][0] != "ID":
        return
    target = rest[i][1]
    parts = _split_commas(_inside_parens(rest[i + 1:]))
    if target == "OPEN.FILE":
        if len(parts) >= 2 and parts[0] and parts[0][0][0] == "STR":
            fname = _unquote(parts[0][0])
            var = _first_var(parts[1])
            if fname and var:
                pf.handles.append((var, fname.upper(), ln, "OPEN.FILE"))
        return
    pf.edges.append(Edge("CALL", target, ln, len(parts)))
    if target in ("IOREADU", "IORELEASE") and len(parts) >= 6:
        mode = _unquote(parts[0][0]) if parts[0] and parts[0][0][0] == "STR" else ""
        mode = mode.upper()
        if target == "IORELEASE" and mode in ("RELEASE", ""):
            return
        op = {"READU": "READU", "READVU": "READVU", "WRITE": "WRITE", "WRITEU": "WRITEU",
              "WRITEV": "WRITEV", "WRITEVU": "WRITEVU", "WRITEUV": "WRITEVU",
              "DELETE": "DELETE"}.get(mode, mode or target)
        attr = _int(parts[2][0]) if parts[2] else None
        # the file is a handle (PRDFILE) or, in newer code, its name ("PRODUCT")
        named = _unquote(parts[3][0]).upper() if parts[3] and parts[3][0][0] == "STR" else None
        pf.io.append(IoOp(ln, op, _first_var(parts[3]), _first_var(parts[5]),
                          _text(parts[1]), attr, target, named or None))
    for part in parts:
        pf.attrs.extend(_angle_refs(part, ln))


def _branches(pf: ProgramFacts, kind: str, toks: list[Tok], ln: int) -> None:
    if toks and _is_word(toks[0], "TO"):
        toks = toks[1:]
    for part in _split_commas(toks):
        if part and part[0][0] in ("ID", "NUM"):
            pf.edges.append(Edge(kind, _label_key(part[0]), ln))


def _execute(pf: ProgramFacts, w: str, rest: list[Tok], ln: int) -> None:
    if not rest:
        return
    kind = "CHAIN" if w == "CHAIN" else ("ENTER" if w == "ENTER" else "EXECUTE")
    if w == "ENTER" and rest[0][0] == "ID":
        pf.edges.append(Edge(kind, rest[0][1], ln))
        return
    if rest[0][0] == "STR":
        cmd = _unquote(rest[0])
        pf.executes.append((ln, cmd))
        m = _RUN_RE.match(cmd)
        if m:
            pf.edges.append(Edge(kind, m.group(2).upper(), ln))
    else:
        pf.executes.append((ln, _text(rest)))


def _open(pf: ProgramFacts, rest: list[Tok], ln: int) -> None:
    to = next((i for i, t in enumerate(rest) if _is_word(t, "TO")), None)
    if to is None or to + 1 >= len(rest):
        return
    strs = [t for t in rest[:to] if t[0] == "STR"]
    var = rest[to + 1][1] if rest[to + 1][0] == "ID" else None
    if strs and var:
        names = [_unquote(s) for s in strs]
        fname = names[-1]
        if len(names) >= 2 and names[0].upper() == "DICT":
            fname = "DICT " + fname
        if fname:
            pf.handles.append((var, fname.upper(), ln, "OPEN"))


def _io(pf: ProgramFacts, w: str, rest: list[Tok], ln: int) -> None:
    if w in DELETE_OPS:
        parts = _split_commas(_upto(rest, IO_STOP))
        if parts:
            pf.io.append(IoOp(ln, w, _first_var(parts[0]), None,
                              _text(parts[1]) if len(parts) > 1 else ""))
        return
    sep = "FROM" if w in READ_OPS else None
    idx = None
    for i, t in enumerate(rest):
        if t[0] == "ID" and (t[1] == sep or (sep is None and t[1] in ("ON", "TO"))):
            idx = i
            break
    if idx is None:
        return
    record = _first_var(rest[:idx])
    if w.startswith("MAT") and record:
        pf.mat_vars.add(record)
    operands = _split_commas(_upto(rest[idx + 1:], IO_STOP))
    if not operands:
        return
    fv = _first_var(operands[0])
    key = _text(operands[1]) if len(operands) > 1 else ""
    attr = _int(operands[2][0]) if len(operands) > 2 and operands[2] else None
    pf.io.append(IoOp(ln, w, fv, record, key, attr))


_MAT_REF = re.compile(r"\b([A-Z][A-Z0-9._$%]*)\((\d+)\)")


def _resolve_mat_refs(pf: ProgramFacts, lines: list[str]) -> None:
    """REC(n) is attribute n only when REC is a MATREAD/MATWRITE target or DIMmed."""
    mat_io = {op.record_var for op in pf.io if op.op.startswith("MAT") and op.record_var}
    if not mat_io:
        return
    for lineno, raw in enumerate(lines, 1):
        s = raw.lstrip()
        if not s or s[0] in "*!":
            continue
        code = s.split(";*", 1)[0].upper()
        for m in _MAT_REF.finditer(code):
            var = m.group(1)
            if var in mat_io:
                after = code[m.end():].lstrip()
                access = "write" if after.startswith("=") and not after.startswith("==") else "read"
                pf.attrs.append(AttrRef(lineno, var, int(m.group(2)), None, access))


# Plumbing every program calls; following them one hop drags in the whole tree.
INFRA = frozenset("IOREADU IORELEASE IO.CLEAN.LOCKS IO.EMPTY.KEY OPEN.FILE".split())


def is_gui_callee(name: str) -> bool:
    """GUI library or I/O plumbing: real edges, but never worth expanding a slice through."""
    return name.startswith(GUI_PREFIX) or name in INFRA
