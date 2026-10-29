"""AccuTerm W4 GUI templates (src/TEMPLATES): one project per file, forms and controls.

Lines are @VM-delimited (raw FD or the UTF-8 of U+F8FD; the text arrives latin-1 decoded):
  TEMPLATE | <OLE date> | <project> | BP<SM><program>...     header
  2 | PROJECT*FORM*CONTROL | <parent> | <type> | left | top | width | height | flags
  4 |  | <prop#> |  |  | <value> [| <value>...]            property of the control above
Positions are in character cells, relative to the parent (frame, tab) or the form.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

# latin-1 renderings of the marks: raw bytes and the UTF-8 of the Private Use Area code points
_VM = ("\xef\xa3\xbd", "\xfd")
_SM = ("\xef\xa3\xbc", "\xfc")
_TM = ("\xef\xa3\xbb", "\xfb")

KIND = {
    1: "app", 5: "form", 6: "form", 7: "form", 15: "label", 16: "text", 17: "textarea", 18: "button",
    19: "radio", 20: "checkbox", 21: "list", 22: "list", 23: "combo", 24: "dropdown", 25: "picture",
    26: "frame", 27: "grid", 28: "grid", 29: "text", 30: "tabs", 31: "tab", 32: "progress", 34: "list",
    35: "timer", 76: "menu",
}
CONTAINERS = {"frame", "tabs", "tab"}
# property numbers that matter for drawing (from the templates themselves)
P_VALUE, P_TITLE, P_ITEMS, P_COLS, P_HEADS, P_WIDTHS, P_TIP, P_BACK = 0, 22, 26, 27, 32, 37, 64, 14


def _text(s: str) -> str:
    """latin-1 decoded UTF-8 -> real text (captions are usually plain ASCII)."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def _split(line: str, marks: tuple[str, ...]) -> list[str]:
    for m in marks[1:]:
        line = line.replace(m, marks[0])
    return line.split(marks[0])


def _num(s: str) -> float:
    try:
        return float(s)
    except ValueError:
        return 0.0


def ole_date(serial: str) -> str | None:
    try:
        return (datetime(1899, 12, 30) + timedelta(days=float(serial))).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OverflowError):
        return None


@dataclass
class Control:
    id: str                      # PROJECT*FORM*CONTROL
    name: str                    # CONTROL (or FORM for a form)
    form: str
    parent: str                  # control name of the container, "" for the form itself
    type: int
    kind: str
    left: float
    top: float
    width: float
    height: float
    flags: int
    props: dict[int, list[list[str]]] = field(default_factory=dict)   # prop -> values -> subvalues

    def prop(self, n: int) -> str:
        v = self.props.get(n)
        return _text(v[0][0]) if v and v[0] else ""

    def values(self, n: int) -> list[str]:
        return [_text(x[0]) for x in self.props.get(n, [])]

    def items(self) -> list[dict[str, str]]:
        """Combo/list/radio items: 'CODE<SM>Label' or just 'Label'. Popup menus are
        'ID<SM>level<SM>Caption<SM>icon...'."""
        out = []
        for v in self.props.get(P_ITEMS, []):
            if not any(v):
                continue
            if self.kind == "menu":
                code, label = v[0], (v[2] if len(v) > 2 and v[2] else v[0])
            else:
                code, label = (v[0], v[1]) if len(v) > 1 and v[1] else (v[0], v[0])
            out.append({"value": _text(code), "label": _text(label)})
        return out


@dataclass
class Template:
    project: str
    program: str
    saved_at: str | None
    controls: list[Control]

    def forms(self) -> list[Control]:
        return [c for c in self.controls if c.kind == "form"]


def parse_template(text: str, name: str = "") -> Template:
    lines = text.splitlines()
    project, program, saved = name, "", None
    controls: list[Control] = []
    cur: Control | None = None
    for raw in lines:
        f = _split(raw, _VM)
        if not f or not f[0]:
            continue
        if f[0] == "TEMPLATE" and len(f) > 2:
            saved = ole_date(f[1])
            project = f[2] or project
            if len(f) > 3:
                sub = _split(f[3], _SM)
                program = sub[1] if len(sub) > 1 else ""
            continue
        if f[0] == "2" and len(f) >= 9:
            parts = f[1].split("*")
            t = int(_num(f[3]))
            kind = KIND.get(t, f"type{t}")
            form = parts[1] if len(parts) > 1 else ""
            cname = parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 else parts[0])
            cur = Control(f[1], cname, form, f[2], t, kind, _num(f[4]), _num(f[5]), _num(f[6]), _num(f[7]),
                          int(_num(f[8])))
            controls.append(cur)
            continue
        if f[0] == "4" and cur is not None and len(f) >= 6:
            try:
                n = int(f[2])
            except ValueError:
                continue
            cur.props[n] = [_split(v, _SM) for v in f[5:]]
    return Template(project, program or project, saved, controls)


def form_tree(t: Template, form: str) -> dict[str, Any] | None:
    """One form as nested JSON for drawing: containers hold their children."""
    fc = next((c for c in t.controls if c.kind == "form" and c.form == form), None)
    if fc is None:
        return None
    members = [c for c in t.controls if c.form == form and c.kind != "form"]
    kids: dict[str, list[Control]] = {}
    for c in members:
        kids.setdefault(c.parent, []).append(c)

    def node(c: Control) -> dict[str, Any]:
        d: dict[str, Any] = {"name": c.name, "kind": c.kind, "type": c.type, "left": c.left, "top": c.top,
                             "width": c.width, "height": c.height}
        cap = c.prop(P_VALUE) if c.kind == "label" else ""
        if c.kind in ("checkbox", "button"):
            cap = c.prop(P_TITLE) or c.prop(P_VALUE)
        title = c.prop(P_TITLE)
        if cap:
            d["caption"] = cap
        if title:
            d["title"] = title
        if c.kind in ("combo", "dropdown", "list", "radio", "menu"):
            d["items"] = c.items()[:60]
        if c.kind == "grid":
            d["columns"] = [{"heading": h, "width": _num(w) if w else 8.0}
                            for h, w in zip(c.values(P_HEADS), c.values(P_WIDTHS) + [""] * 99, strict=False)]
        tip = c.values(P_TIP)
        if tip and c.kind != "grid" and tip[0]:
            d["tip"] = tip[0]
        if c.kind in CONTAINERS:
            d["children"] = [node(k) for k in kids.get(c.name, [])]
        return d

    return {"name": form, "title": fc.prop(P_TITLE), "width": fc.width, "height": fc.height,
            "controls": [node(c) for c in kids.get("", [])]}
