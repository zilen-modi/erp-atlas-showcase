from atlas import suggest
from atlas.parse.program import parse_program
from atlas.store.db import Store

MAIN = [
    "      SUBROUTINE W4SUBDOCMAINT(A)",
    "      CALL *OPEN.FILE('DOC',DOCFILE)",
    "      CALL *OPEN.FILE('&COMO&',COMO)",
    "GUI.W4SUBDOCMAINT.FRMDOC.BTNOK.CLICK: *",
    "      WRITE REC ON DOCFILE, K",
    "      WRITE X ON COMO, K",
    "      GOSUB SAVE.LOG",
    "      CALL W4SUBSERIAL(K)",
    "      RETURN",
    "GUI.W4SUBDOCMAINT.FRMDOC.BTNPRINT.CLICK: *",
    "      RETURN",
    "SAVE.LOG: *",
    "      CALL *OPEN.FILE('DOC-LOG',LOGFILE)",
    "      WRITE L ON LOGFILE, K",
    "      RETURN",
]
SERIAL = ["      SUBROUTINE W4SUBSERIAL(K)", "      CALL *OPEN.FILE('SERIAL-LOG',SL)",
          "      WRITE S ON SL, K", "      RETURN"]


def store():
    st = Store(":memory:")
    for name, lines in (("W4SUBDOCMAINT", MAIN), ("W4SUBSERIAL", SERIAL)):
        h = st.put_source("git", "BP", name, f"src/BP/{name}", "\n".join(lines))
        st.put_program("git", parse_program(name, lines), h)
    st.db.execute("INSERT INTO menu VALUES ('M9','RUN BP W4SUBDOCMAINT','W4SUBDOCMAINT',50,'2026-04-09')")
    st.commit()
    return st


def test_action_map_follows_gosub_and_calls_and_drops_noise():
    am = suggest.action_map(store(), "W4SUBDOCMAINT")
    assert [a["control"] for a in am["actions"]] == ["BTNOK"]          # BTNPRINT writes nothing
    ok = am["actions"][0]
    assert set(ok["writes"]) == {"DOC", "DOC-LOG", "SERIAL-LOG"}      # &COMO& is plumbing
    assert ok["writes"]["DOC"] == "W4SUBDOCMAINT:5"
    assert ok["writes"]["SERIAL-LOG"] == "via W4SUBSERIAL"


def test_topic_finds_program_and_quick_flow():
    st = store()
    assert suggest.programs_for(st, "doc") == ["W4SUBDOCMAINT"]
    q = suggest.quick(st, "doc")
    assert {f["pick_file"] for f in q["flows"][0]["files"]} == {"DOC", "DOC-LOG", "SERIAL-LOG"}
    assert suggest.cached(st, "doc") is None


def test_key_patterns_become_capturable():
    got = suggest.sanitize_files([
        {"pick_file": "transfer-hist", "key_template": "{key}-1 (ship), {key}-2 (receive)", "why": "passes"},
        {"pick_file": "PRODUCT", "key_template": "{part}*{branch}", "why": "stock"},
        {"pick_file": "WORKFLOW", "key_template": "T{key}", "why": "work"},
    ])
    assert [(g["pick_file"], g["key_template"]) for g in got] == [
        ("TRANSFER-HIST", "{key}-1"), ("TRANSFER-HIST", "{key}-2"), ("PRODUCT", "{key}"), ("WORKFLOW", "T{key}")]
    assert "Set this record's key under Keys" in got[2]["why"]
