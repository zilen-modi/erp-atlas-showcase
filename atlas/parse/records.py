"""Decoders for MENU-ITEMS records and DICT printouts, plus delimiter-mark handling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

PICK_EPOCH = date(1967, 12, 31)

# MultiValue marks: raw native byte (as latin-1 char) and the UTF-8 PUA form
# decoded as latin-1 (three chars).  U+FFFD means the mark was destroyed.
MARKS = {
    "IM": ("\xff", "\xef\xa3\xbf"),
    "AM": ("\xfe", "\xef\xa3\xbe"),
    "VM": ("\xfd", "\xef\xa3\xbd"),
    "SM": ("\xfc", "\xef\xa3\xbc"),
    "TM": ("\xfb", "\xef\xa3\xbb"),
}
DESTROYED = "\xef\xbf\xbd"


def normalise_marks(text: str) -> str:
    """Rewrite PUA-encoded marks to their raw byte so two copies compare equally."""
    for raw, pua in MARKS.values():
        text = text.replace(pua, raw)
    return text


def mark_census(text: str) -> dict[str, int]:
    out = {f"{k}_raw": text.count(raw) for k, (raw, _p) in MARKS.items()}
    out.update({f"{k}_pua": text.count(pua) for k, (_r, pua) in MARKS.items()})
    out["destroyed"] = text.count(DESTROYED)
    return {k: v for k, v in out.items() if v}


def pick_date(n: str | int | None) -> str | None:
    try:
        return (PICK_EPOCH + timedelta(days=int(str(n).strip()))).isoformat()
    except (TypeError, ValueError):
        return None


@dataclass
class Menu:
    code: str
    exec: str
    program: str | None
    used: int | None
    last_used: str | None


_RUN = re.compile(r"^\s*RUN\s+\S+\s+(\S+)", re.IGNORECASE)


def parse_menu(code: str, lines: list[str]) -> Menu:
    """attr 1 EXEC, attr 2 #USED, attr 3 DT (Pick date) -- per src/DICT/MENU-ITEMS."""
    ex = lines[0].strip() if lines else ""
    m = _RUN.match(ex)
    used = lines[1].strip() if len(lines) > 1 else ""
    return Menu(code, ex, m.group(1).upper() if m else None,
                int(used) if used.isdigit() else None,
                pick_date(lines[2]) if len(lines) > 2 else None)


@dataclass
class DictItem:
    name: str
    type: str
    attr: int
    conv: str
    heading: str
    definition: str = ""
    format: str = ""
    depth: str = ""          # S single-valued | M multivalued
    assoc: str = ""


_DICT_ROW = re.compile(r"^(\S+)\s+([ADSIV])\s+(\d+)\b")
# UniVerse LIST DICT printout columns when no header line is found
_DICT_COLS = {"definition": 22, "conv": 36, "heading": 49, "format": 65, "depth": 72}


def _dict_columns(lines: list[str]) -> dict[str, int]:
    """Column starts from the printout's own header, e.g.
    'Field......... Type & Field........ Conversion.. Column......... Output Depth &'."""
    for raw in lines:
        if raw.startswith("Field") and "Conversion" in raw:
            toks = {m.group(0).rstrip("."): m.start() for m in re.finditer(r"\S+", raw)}
            f2 = [m.start() for m in re.finditer(r"Field\.+", raw)]
            if len(f2) >= 2 and all(k in toks for k in ("Conversion", "Column", "Output", "Depth")):
                return {"definition": f2[1], "conv": toks["Conversion"], "heading": toks["Column"],
                        "format": toks["Output"], "depth": toks["Depth"]}
    return dict(_DICT_COLS)


def parse_dict_printout(lines: list[str]) -> list[DictItem]:
    """A `LIST DICT` printout as committed under src/DICT.  Continuation lines of
    long definitions/conversions start with spaces and are skipped."""
    c = _dict_columns(lines)
    items: list[DictItem] = []
    for raw in lines:
        m = _DICT_ROW.match(raw)
        if not m:
            continue

        def col(a: str, b: str | None, line: str = raw) -> str:
            return line[c[a]:c[b] if b else None].strip() if len(line) > c[a] else ""

        rest = col("depth", None).split()
        items.append(DictItem(m.group(1), m.group(2), int(m.group(3)), col("conv", "heading"),
                              col("heading", "format"), col("definition", "conv"), col("format", "depth"),
                              rest[0] if rest and rest[0] in ("S", "M") else "",
                              rest[1] if len(rest) > 1 else ""))
    return items
