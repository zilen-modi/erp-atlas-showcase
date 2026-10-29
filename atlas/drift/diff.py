"""Git vs live source comparison, classified so real logic drift stands out.

Classes, from least to most important:
  whitespace  only spacing differs
  comment     only comment text / comment-only lines differ
  label       only a statement label differs (e.g. live `1671:` that git removed)
              -- escalated to `logic` when an active GOTO/GOSUB targets that label
  logic       same place, different code
  git-only    code present in git, absent live   (not deployed yet, or reverted live)
  live-only   code present live, absent in git   (edited on the server, never committed)
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from atlas.parse.records import normalise_marks

_LEAD_LABEL = re.compile(r"^\s*(\d+|[A-Z][A-Z0-9._$%]*)\s*:(?!=)\s*", re.IGNORECASE)
_LEAD_NUM = re.compile(r"^\s*\d+\s+")
_CODE_COMMENT = re.compile(r";\s*\*.*$")


@dataclass
class Hunk:
    index: int
    cls: str
    git_start: int      # 1-based, inclusive; 0 when the hunk has no git lines
    git_end: int
    live_start: int
    live_end: int
    git_lines: list[str] = field(default_factory=list)
    live_lines: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)


def _is_comment(line: str) -> bool:
    s = _LEAD_LABEL.sub("", line.strip(), count=1).strip()
    return s == "" or s.startswith(("*", "!")) or s.upper().startswith("REM ")


def _code(line: str) -> str:
    """Line reduced to its code: no label, no trailing `;*` comment, single spaces."""
    s = _LEAD_LABEL.sub("", line.strip(), count=1)
    s = _CODE_COMMENT.sub("", s)
    return " ".join(s.split()).upper()


def _label_of(line: str) -> str | None:
    m = _LEAD_LABEL.match(line)
    if m:
        return m.group(1).upper().lstrip("0") or "0"
    return None


def _pair_class(g: str, v: str) -> str:
    """Two lines whose code already matches: what kind of cosmetic difference?"""
    if " ".join(g.split()) == " ".join(v.split()):
        return "whitespace"
    if _label_of(g) != _label_of(v):
        return "label"
    return "comment"


_RANK = {"whitespace": 0, "comment": 1, "label": 2, "logic": 3, "git-only": 3, "live-only": 3}


def _is_code(line: str) -> bool:
    return not _is_comment(line) and _code(line) != ""


def compare(git: list[str], live: list[str],
            branch_targets_git: set[str] | None = None,
            branch_targets_live: set[str] | None = None) -> list[Hunk]:
    """Align the two copies on their CODE (label, trailing comment and spacing
    stripped) so a renumbered label or an edited comment cannot swallow a real
    change into one coarse hunk; then classify the cosmetic differences inside
    aligned pairs, and diff the comment/label-only lines separately."""
    g = [normalise_marks(x.rstrip("\r")) for x in git]
    v = [normalise_marks(x.rstrip("\r")) for x in live]
    tg, tl = branch_targets_git or set(), branch_targets_live or set()

    def dangling(only_git: set[str], only_live: set[str]) -> bool:
        """A label one side lacks but that same side still branches to -- it cannot compile.
        (A label that disappears together with its GOTO is just cosmetic here; the GOTO
        change shows up as its own hunk.)"""
        return bool((only_git & tl) or (only_live & tg))
    raw: list[tuple[str, list[int], list[int]]] = []    # cls, git line idxs, live line idxs (0-based)

    gi = [i for i, x in enumerate(g) if _is_code(x)]
    vi = [i for i, x in enumerate(v) if _is_code(x)]
    sm = difflib.SequenceMatcher(a=[_code(g[i]) for i in gi], b=[_code(v[i]) for i in vi], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                a, b = gi[i1 + k], vi[j1 + k]
                if g[a] != v[b]:
                    cls = _pair_class(g[a], v[b])
                    la, lb = _label_of(g[a]), _label_of(v[b])
                    if cls == "label" and dangling({la} - {lb, None}, {lb} - {la, None}):  # type: ignore[arg-type]
                        cls = "logic"
                    raw.append((cls, [a], [b]))
            continue
        cls = {"replace": "logic", "delete": "git-only", "insert": "live-only"}[tag]
        # a code hunk shows its whole span, comments inside included, for context
        gs = list(range(gi[i1], gi[i2 - 1] + 1)) if i2 > i1 else []
        vs = list(range(vi[j1], vi[j2 - 1] + 1)) if j2 > j1 else []
        raw.append((cls, gs, vs))

    # comment- and label-only lines (blank lines ignored)
    gc = [i for i, x in enumerate(g) if not _is_code(x) and x.strip()]
    vc = [i for i, x in enumerate(v) if not _is_code(x) and x.strip()]
    sm2 = difflib.SequenceMatcher(a=[" ".join(g[i].split()) for i in gc],
                                  b=[" ".join(v[i].split()) for i in vc], autojunk=False)
    for tag, i1, i2, j1, j2 in sm2.get_opcodes():
        if tag == "equal":
            continue
        gside, vside = [g[i] for i in gc[i1:i2]], [v[j] for j in vc[j1:j2]]
        lg = {lb for lb in (_label_of(x) for x in gside) if lb}
        lv = {lb for lb in (_label_of(x) for x in vside) if lb}
        if lg ^ lv:                           # labels present on only one side
            cls = "logic" if dangling(lg - lv, lv - lg) else "label"
        elif ["".join(x.split()) for x in gside] == ["".join(x.split()) for x in vside]:
            cls = "whitespace"
        else:
            cls = "comment"
        raw.append((cls, gc[i1:i2], vc[j1:j2]))

    def pos(r: tuple[str, list[int], list[int]]) -> tuple[int, int]:
        return (r[1][0] if r[1] else 10**9, r[2][0] if r[2] else 10**9)

    hunks: list[Hunk] = []
    for cls, gs, vs in sorted(raw, key=pos):
        gl, vl = [g[i] for i in gs], [v[j] for j in vs]
        labels = sorted({lb for lb in (_label_of(x) for x in gl + vl) if lb})
        hunks.append(Hunk(len(hunks) + 1, cls, gs[0] + 1 if gs else 0, gs[-1] + 1 if gs else 0,
                          vs[0] + 1 if vs else 0, vs[-1] + 1 if vs else 0, gl, vl, labels))
    return hunks


def summarize(hunks: list[Hunk]) -> dict[str, int]:
    out: dict[str, int] = {}
    for h in hunks:
        out[h.cls] = out.get(h.cls, 0) + 1
    return out


def to_markdown(program: str, hunks: list[Hunk], commits: dict[int, list[dict[str, str]]] | None = None,
                show: set[str] | None = None) -> str:
    show = show or {"logic", "git-only", "live-only"}
    s = summarize(hunks)
    out = [f"## Drift: {program}", "", "| class | hunks |", "|---|---|"]
    out += [f"| {k} | {s[k]} |" for k in sorted(s, key=lambda k: -_RANK[k])]
    for h in hunks:
        if h.cls not in show:
            continue
        loc = f"git {h.git_start}-{h.git_end}" if h.git_start else "git —"
        loc += f" · live {h.live_start}-{h.live_end}" if h.live_start else " · live —"
        out += ["", f"### #{h.index} {h.cls} ({loc})"]
        for c in (commits or {}).get(h.index, []):
            what = "removed from git in" if c.get("role") == "removed-in-git" else "git line from"
            out.append(f"- {what} `{c['sha'][:9]}` {c.get('date', '')} "
                       f"{c.get('author', '')}: {c.get('summary', '')}")
        out.append("```diff")
        out += [f"-{x}" for x in h.git_lines] + [f"+{x}" for x in h.live_lines]
        out.append("```")
    return "\n".join(out)
