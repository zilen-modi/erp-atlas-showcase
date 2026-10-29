from atlas import screens
from atlas.parse.program import parse_program
from atlas.parse.template import form_tree, parse_template
from atlas.store.db import Store
from atlas.sync import index_template

VM, SM = "".encode().decode("latin-1"), "".encode().decode("latin-1")   # PUA marks, as git gives them


def row(*f: str) -> str:
    return VM.join(f)


TEMPLATE = "\r\n".join([
    row("TEMPLATE", "46276.5", "W4DEMO", f"BP{SM}W4DEMO{SM}0"),
    row("2", "W4DEMO*FRMMAIN", "", "6", "auto", "auto", "60", "20", "1"),
    row("4", "", "22", "", "", "Demo Entry"),
    row("2", "W4DEMO*FRMMAIN*TXTDOC", "", "16", "9", ".5", "10", "1.25", "0"),
    row("2", "W4DEMO*FRMMAIN*CMBVIA", "FRAHEAD", "23", "2", "1", "8", "1.25", "0"),
    row("4", "", "26", "", "", f"UPS{SM}UPS Ground", f"PU{SM}Pick up"),
    row("2", "W4DEMO*FRMMAIN*FRAHEAD", "", "26", "1", "3", "40", "6", "0"),
    row("2", "W4DEMO*FRMMAIN*BTNOK", "", "18", "30", "15", "8", "1.25", "0"),
    row("4", "", "22", "", "", "&Ok"),
    row("2", "W4DEMO*FRMMAIN*BTNHELP", "", "18", "40", "15", "8", "1.25", "0"),
])

PROGRAM = [
    "      SUBROUTINE W4DEMO(A)",
    "      CALL *OPEN.FILE('DOC',DOCFILE)",
    "      READ DOC FROM DOCFILE, DOCNO ELSE DOC = ''",
    "      CALL ATGUISETPROP(GUIAPP,'FRMMAIN','TXTDOC',GPVALUE,0,0,DOCNO,GUIERRORS,GUISTATE)",
    "      CALL ATGUIGETPROP(GUIAPP,'FRMMAIN','CMBVIA',GPVALUE,0,0,VIA,GUIERRORS,GUISTATE)",
    "      DOC<15> = VIA",
    "      RETURN",
    "GUI.W4DEMO.FRMMAIN.BTNOK.CLICK:",
    "      WRITE DOC ON DOCFILE, DOCNO",
    "      RETURN",
    "GUI.W4DEMO.FRMMAIN.BTNGONE.CLICK:",
    "      RETURN",
]


def test_parse_template_tree():
    t = parse_template(TEMPLATE, "W4DEMO")
    assert (t.project, t.program, t.saved_at[:10]) == ("W4DEMO", "W4DEMO", "2026-09-11")
    tree = form_tree(t, "FRMMAIN")
    assert tree["title"] == "Demo Entry"
    top = {c["name"]: c for c in tree["controls"]}
    assert set(top) == {"TXTDOC", "FRAHEAD", "BTNOK", "BTNHELP"}
    assert top["FRAHEAD"]["children"][0]["items"] == [{"value": "UPS", "label": "UPS Ground"},
                                                      {"value": "PU", "label": "Pick up"}]
    assert top["BTNOK"]["caption"] == "&Ok"


def test_form_wiring():
    st = Store(":memory:")
    text = "\n".join(PROGRAM)
    h = st.put_source("git", "BP", "W4DEMO", "src/BP/W4DEMO", text)
    st.put_program("git", parse_program("W4DEMO", PROGRAM), h)
    st.put_source("git", "TEMPLATE", "W4DEMO", "src/TEMPLATES/W4DEMO", TEMPLATE)
    index_template(st, "W4DEMO", TEMPLATE)
    st.commit()
    f = screens.form(st, "W4DEMO", "FRMMAIN")
    w = f["wiring"]
    assert w["TXTDOC"]["bindings"][0] == {"file": "DOC", "attr": 0, "how": "record key via DOCNO", "lines": [4]}
    assert w["CMBVIA"]["bindings"][0]["file"] == "DOC" and w["CMBVIA"]["bindings"][0]["attr"] == 15
    assert w["BTNOK"]["handlers"][0]["event"] == "CLICK" and "DOC" in w["BTNOK"]["handlers"][0]["writes"]
    assert [o["control"] for o in f["orphan_handlers"]] == ["BTNGONE"]
    assert f["buttons_without_handler"] == ["BTNHELP"]
