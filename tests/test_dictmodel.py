from atlas import dictmodel
from atlas.store.db import Store

ROWS = [("@ID", "D", 0, "", "SERIAL-LOG", "S"), ("VEND/CUST", "A", 1, "", "", "M"), ("PRODUCT", "A", 2, "", "", "M"),
        ("DOC#", "A", 3, "", "", "M"), ("WRITER", "A", 4, "", "", "M"), ("DOC.TYPE", "A", 5, "", "", "M"),
        ("WHSE", "A", 6, "", "", "M"), ("DATE", "A", 7, "D2/", "TRANS DATE", "M"), ("TERMINAL", "A", 8, "", "WHO", "M"),
        ("TIME", "A", 9, "MTHS", "", "M"), ("GROUP", "S", 2, "", "", "M")]


def store():
    st = Store(":memory:")
    st.db.executemany("INSERT INTO dict_attr (pick_file, name, type, attr, conv, heading, depth) VALUES "
                      "('SERIAL-LOG',?,?,?,?,?,?)", ROWS)
    st.commit()
    return st


def test_export_matches_the_agreed_format():
    doc = dictmodel.export(store(), "serial-log")
    assert doc["table_name"] == "SERIAL-LOG"
    got = [(f["pos"], f["uv"], f["model"], f["sm"], f["format"]) for f in doc["fields"]]
    assert got == [(0, "@ID", "serialLogId", "S", "string"), (1, "VEND/CUST", "vendorCustomerId", "M", "string"),
                   (2, "PRODUCT", "productId", "M", "string"), (3, "DOC#", "documentNumber", "M", "string"),
                   (4, "WRITER", "writerId", "M", "string"), (5, "DOC.TYPE", "documentType", "M", "string"),
                   (6, "WHSE", "warehouse", "M", "string"), (7, "DATE", "transactionDate", "M", "date"),
                   (8, "TERMINAL", "terminal", "M", "string"), (9, "TIME", "time", "M", "time")]


def test_user_edits_win_and_reset():
    st = store()
    dictmodel.save(st, "SERIAL-LOG", {"description": "Serial number transaction log",
                                      "fields": [{"pos": 8, "model": "terminalId", "format": "string"}]})
    d = dictmodel.get(st, "SERIAL-LOG")
    assert d["description"] == "Serial number transaction log"
    f8 = next(f for f in d["fields"] if f["pos"] == 8)
    assert (f8["model"], f8["source"]) == ("terminalId", "user")
    assert dictmodel.reset(st, "SERIAL-LOG")["fields"][8]["model"] == "terminal"


def test_formats():
    assert [dictmodel.format_of(c) for c in ("D2/", "MTHS", "MD2", "MR0", "")] == \
        ["date", "time", "decimal", "number", "string"]
