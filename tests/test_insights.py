from atlas import insights
from atlas.parse.program import parse_program
from atlas.store.db import Store

LINES = ["      SUBROUTINE W4DEMO(A)", "      CALL *OPEN.FILE('TRANSFER',XFFILE)",
         "      READ XF FROM XFFILE, K ELSE XF = ''", "      XF<88> = 1", "      WRITE XF ON XFFILE, K"]


def store():
    st = Store(":memory:")
    h = st.put_source("git", "BP", "W4DEMO", "src/BP/W4DEMO", "\n".join(LINES))
    st.put_program("git", parse_program("W4DEMO", LINES), h)
    st.db.execute("INSERT INTO menu VALUES ('M1','RUN BP W4DEMO','W4DEMO',500,'2026-04-09')")
    st.commit()
    return st


def test_track_and_rank():
    st = store()
    for _ in range(3):
        insights.track(st, "program", "w4demo")
    insights.track(st, "field", "TRANSFER<88>")
    insights.track(st, "nonsense", "x")                       # unknown kinds are ignored
    top = insights.most_looked_up(st)
    assert [(t["kind"], t["key"], t["count"]) for t in top] == [("program", "W4DEMO", 3), ("field", "TRANSFER<88>", 1)]
    assert top[1]["href"] == "/field/TRANSFER/88"


def test_ideas_skip_what_was_already_asked():
    st = store()
    titles = [i["title"] for i in insights.ideas(st)]
    assert "What is TRANSFER<88>?" in titles                  # written, not named in DICT
    assert any("M1" in t for t in titles)
    st.db.execute("INSERT INTO answer VALUES ('a1','u','What is TRANSFER<88>?','x','[]','[]','{}','m','v','t')")
    st.commit()
    assert "What is TRANSFER<88>?" not in [i["title"] for i in insights.ideas(st)]
