"""Check an answer's citations against the code, with no model involved.

Every `PROGRAM:line` (or `PROGRAM:start-end`) an answer cites must name an indexed program and lines it has.
Where the answer quotes code in a fenced block and cites it right after, the quoted lines must be found in or
near the cited lines (whitespace and case ignored). A citation that fails is reported, so a made-up line
number or a misquoted line is visible on the answer instead of trusted.
"""

from __future__ import annotations

import re
from typing import Any

from atlas.store.db import Store

Result = dict[str, Any]
_CITE = re.compile(r"\b(live:)?([A-Z][A-Z0-9._$%]*[A-Z0-9])[:](\d+)(?:\s*[-–]\s*(\d+))?\b")
_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
SLACK = 3          # a quote may sit this many lines outside the cited range (comments, wrapped statements)
NOT_PROGRAMS = {"HTTP", "HTTPS", "TEST", "NOTE", "UTC"}


_PREFIX = re.compile(r"^\s*(?:[A-Z][A-Z0-9._$%]*:)?\d+[:.]?\s+")     # "4947: " or "W4X:296 " before a quoted line
_TOKEN = re.compile(r'"[^"]*"|\'[^\']*\'|[A-Z0-9_.$%]+(?:<[^>]*>)?')
QUOTE_MATCH = 0.75     # share of a quoted line's tokens that must appear in the cited lines


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().upper()


def _tokens(line: str) -> list[str]:
    """The words, strings and FIELD<n> references of a quoted line, without a line-number prefix or the
    trailing comment the answer may have added."""
    # a note the answer added after the code: spaces, maybe ";" or "*", then lower-case words (code is upper case)
    line = re.split(r"\s{2,}(?:;\*?|\*|//|#|-)?\s*(?=[a-z])|\s;\s+(?=[a-z])|\s{2,};\s", line, maxsplit=1)[0]
    line = _PREFIX.sub("", _norm(line))
    line = re.split(r"\s;?\*\s", line, maxsplit=1)[0]             # " ;* note" / " * note" added after code
    return [t for t in _TOKEN.findall(line) if t not in ("...", "..")]


_LABEL = re.compile(r"^\s*(?:([A-Z][A-Z0-9._$%]*[A-Z0-9]):)?(\d+)[:.]?\s+")
_DIAGRAM = re.compile(r"[└├│─→]|->|=>")


def _prose(line: str) -> bool:
    """A description, not code: this ERP's BASIC is upper case, so mostly lower-case words are the answer's."""
    bare = re.sub(r'"[^"]*"|\'[^\']*\'', "", _LABEL.sub("", line))
    return sum(c.islower() for c in bare) > sum(c.isupper() for c in bare)


def _window(src: list[str], start: int, end: int) -> set[str]:
    """The tokens of the cited lines, give or take SLACK."""
    have: set[str] = set()
    for x in src[max(0, start - 1 - SLACK):end + SLACK]:
        have.update(_TOKEN.findall(_norm(x)))
    return have


def _found(tokens: list[str], have: set[str]) -> bool:
    """Most of the line's tokens are at the cited lines (answers trim quotes with "...")."""
    return sum(t in have for t in tokens) / len(tokens) >= QUOTE_MATCH


def cites(answer: str) -> list[Result]:
    out, seen = [], set()
    for m in _CITE.finditer(answer):
        prov = "live" if m.group(1) else "git"
        name, start = m.group(2), int(m.group(3))
        end = int(m.group(4)) if m.group(4) else start
        if name in NOT_PROGRAMS or (prov, name, start, end) in seen:
            continue
        seen.add((prov, name, start, end))
        out.append({"provenance": prov, "program": name, "start": start, "end": max(start, end),
                    "text": m.group(0), "pos": m.start()})
    return out


def check(store: Store, answer: str) -> Result:
    """{"cites": n, "ok": n, "problems": [{cite, why}]} for one answer."""
    found = cites(answer)
    sources: dict[tuple[str, str], list[str] | None] = {}

    def lines_of(prov: str, name: str) -> list[str] | None:
        if (prov, name) not in sources:
            sources[(prov, name)] = store.source_lines(prov, name)
        return sources[(prov, name)]

    problems: list[Result] = []
    for c in found:
        src = lines_of(c["provenance"], c["program"])
        if src is None:
            # not a program Atlas knows: a file or DICT name that looked like a cite (FILE:1) is not an error
            if store.db.execute("SELECT 1 FROM program WHERE name=?", (c["program"],)).fetchone() is None:
                c["skip"] = True
                continue
            problems.append({"cite": c["text"], "why": f"{c['program']} isn't in the {c['provenance']} index"})
        elif c["end"] > len(src):
            problems.append({"cite": c["text"], "why": f"{c['program']} has only {len(src)} lines"})
    # quoted code: a fenced block followed closely by a citation must match those lines
    for m in _FENCE.finditer(answer):
        after = [c for c in found if not c.get("skip") and 0 <= c["pos"] - m.end() <= 160]
        if not after:
            continue
        if _DIAGRAM.search(m.group(1)):
            continue                            # a flow drawn as text, not quoted code
        quoted = [(x.strip(), _tokens(x)) for x in m.group(1).splitlines()]
        quoted = [(x, t) for x, t in quoted if len(t) >= 2 and not x.startswith("...") and not _prose(x)]
        if not quoted:
            continue
        have: set[str] = set()
        for c in after:
            have |= _window(lines_of(c["provenance"], c["program"]) or [], c["start"], c["end"])
        # a line counts as found when most of its tokens are there (answers trim and annotate quotes); a line
        # labelled with its own place ("4947:" or "W4X:296") is checked there; the block fails only when most
        # of its lines aren't found
        missing = []
        for x, t in quoted:
            lab = _LABEL.match(x)
            if lab:
                prog, at = lab.group(1) or after[0]["program"], int(lab.group(2))
                if not _found(t, _window(lines_of(after[0]["provenance"], prog) or [], at, at)):
                    missing.append(x)
            elif not _found(t, have):
                missing.append(x)
        if len(missing) > len(quoted) / 2:
            problems.append({"cite": ", ".join(c["text"] for c in after),
                             "why": f"quoted code doesn't match those lines: {missing[0][:80]}"})
    checked = [c for c in found if not c.get("skip")]
    return {"cites": len(checked), "ok": len(checked) - sum(1 for p in problems if not p["why"].startswith("quoted")),
            "problems": problems}
