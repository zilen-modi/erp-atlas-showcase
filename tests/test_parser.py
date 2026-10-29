from atlas.parse.program import parse_program
from atlas.parse.records import parse_dict_printout, parse_menu, pick_date

SRC = """      SUBROUTINE W4SUBDEMO(RESULT,AUTO.XF,F1,F2)
      * a comment with CALL NOTREAL(X)
      CALL *OPEN.FILE( ' TRANSFER' , XFFILE)
      CALL *OPEN.FILE("PRODUCT",PRDFILE)
      OPEN 'CONTROL' TO CTRLFILE ELSE STOP
      READ XF FROM XFFILE, XFN ELSE XF = ""
      READV FLAG FROM CTRLFILE,"ACUMATICAFLG",1 ELSE FLAG=0
      CALL IOREADU("READU", PN:"*":XF<1>, "", PRDFILE, GUIAPP, PRD, "N", "Y", L, F, "LABEL:9525")
      XF<10> = DATE() ; XF<27,V> = PN
      IF XF<3> = 142 THEN GOSUB 1000
      ON MODE GOSUB 2000, SAVE.IT
      EXECUTE "RUN BP LG.XFLOG.RPT"
      CALL LG.XMOD.UPDATE(XF, MAT DIMXF)
1000: *
      CALL IORELEASE("WRITE", XFN, "", XFFILE, GUIAPP, XF, "LABEL:1000")
      CALL IORELEASE("RELEASE", PN, "", PRDFILE, GUIAPP, PRD, "LABEL:1000")
      RETURN
2000  MATREAD DIMXF FROM XFFILE, XFN ELSE NULL
      DIMXF(12) = "Y"
      RETURN
SAVE.IT:
      WRITEV "X" ON XFFILE, XFN, 88
      DELETE XFFILE, OLDKEY
      RETURN
"""


def pf():
    return parse_program("W4SUBDEMO", SRC.splitlines())


def test_signature_and_labels():
    p = pf()
    assert p.kind == "SUBROUTINE"
    assert p.params == ["RESULT", "AUTO.XF", "F1", "F2"]
    assert p.labels == {"1000": 14, "2000": 18, "SAVE.IT": 21}
    assert [b[0] for b in p.blocks()] == ["(main)", "1000", "2000", "SAVE.IT"]


def test_edges_skip_comments_and_open_file():
    p = pf()
    calls = {e.target for e in p.edges if e.kind == "CALL"}
    assert "NOTREAL" not in calls
    assert "OPEN.FILE" not in calls
    assert {"IOREADU", "IORELEASE", "LG.XMOD.UPDATE"} <= calls
    assert ("GOSUB", "1000") in {(e.kind, e.target) for e in p.edges}
    assert {"2000", "SAVE.IT"} <= {e.target for e in p.edges if e.kind == "GOSUB"}
    assert ("EXECUTE", "LG.XFLOG.RPT") in {(e.kind, e.target) for e in p.edges}


def test_file_handles_including_legacy_spacing():
    fh = pf().file_of_handle()
    assert fh["XFFILE"] == {"TRANSFER"}
    assert fh["PRDFILE"] == {"PRODUCT"}
    assert fh["CTRLFILE"] == {"CONTROL"}


def test_io_including_w5_wrappers():
    ops = {(o.op, o.file_var, o.record_var, o.via) for o in pf().io}
    assert ("READ", "XFFILE", "XF", "") in ops
    assert ("READU", "PRDFILE", "PRD", "IOREADU") in ops
    assert ("WRITE", "XFFILE", "XF", "IORELEASE") in ops
    assert not any(o.via == "IORELEASE" and o.record_var == "PRD" for o in pf().io)  # RELEASE = unlock only
    writev = [o for o in pf().io if o.op == "WRITEV"]
    assert writev and writev[0].attr == 88
    assert any(o.op == "DELETE" and o.file_var == "XFFILE" for o in pf().io)


def test_attribute_refs_bind_to_files():
    p = pf()
    assert p.record_bindings()["XF"] == {"TRANSFER"}
    writes = {(a.var, a.attr) for a in p.attrs if a.access == "write"}
    assert ("XF", 10) in writes and ("XF", 27) in writes
    reads = {(a.var, a.attr) for a in p.attrs if a.access == "read"}
    assert ("XF", 3) in reads and ("XF", 1) in reads
    assert ("DIMXF", 12) in writes          # MATREAD array subscript


def test_menu_and_dict():
    m = parse_menu("M4401", ["RUN BP LG.XFER.MENU", "3025313", "21284", "", "N"])
    assert (m.program, m.used, m.last_used) == ("LG.XFER.MENU", 3025313, "2026-04-09")
    assert pick_date(0) == "1967-12-31"
    items = parse_dict_printout([
        "Field......... Type & Field........ Conversion.. Column......... Output Depth &",
        "Name.......... Field. Definition... Code........ Heading........ Format Assoc..",
        "TRAN.NO        A    0                            TRAN.NO         7R     M",
        "REQUIRED       A   10               D2/          REQ'D           8R     S",
        "GROUP          S    2 F;2;C*1;:(TPR                              20L    M",
        "                      ODUCT;X;19;19",
        "TIME           A    9               MTHS                         10R    M    LINES",
    ])
    assert [(i.name, i.attr) for i in items] == [("TRAN.NO", 0), ("REQUIRED", 10), ("GROUP", 2), ("TIME", 9)]
    req, grp, tm = items[1], items[2], items[3]
    assert (req.conv, req.heading, req.format, req.depth) == ("D2/", "REQ'D", "8R", "S")
    assert grp.definition == "F;2;C*1;:(TPR" and grp.conv == ""
    assert (tm.conv, tm.depth, tm.assoc) == ("MTHS", "M", "LINES")


def test_basic_outside_bp_is_indexed_as_programs():
    from atlas.sync import _kind_name
    assert _kind_name("src/GUIBP/ATGUICLEAR", {}) == ("BP", "ATGUICLEAR")
    assert _kind_name("src/next/api-helpers/LG.GETCOST.WRAP", {}) == ("BP", "LG.GETCOST.WRAP")
    assert _kind_name("src/next/utilities/NX_ENCRYPT", {}) == ("BP", "NX_ENCRYPT")
    assert _kind_name("src/next/README.md", {}) is None
    assert _kind_name("src/next/cdc/producer/app/config.py", {}) is None
    assert _kind_name("src/next/deprecated/triggers/X", {}) is None


def test_w5_wrappers_naming_the_file_outright():
    lines = ["      SUBROUTINE NX_X(GUIAPP)",
             '      CALL IOREADU("READU",KEY,"","PRODUCT",GUIAPP,PRD,1,1,LCK,FND,F1)',
             "      PRD<26> = 5",
             '      CALL IORELEASE("WRITE",KEY,"","PRODUCT",GUIAPP,PRD,F1)',
             '      CALL IORELEASE("WRITEV",KEY,26,"PRODUCT",GUIAPP,QOH,F1)',
             "      RETURN"]
    pf = parse_program("NX_X", lines)
    writes = [o for o in pf.io if o.op.startswith("WRITE")]
    assert [(o.op, o.file_name, o.attr) for o in writes] == [("WRITE", "PRODUCT", None), ("WRITEV", "PRODUCT", 26)]
    assert pf.record_bindings()["PRD"] == {"PRODUCT"}          # so PRD<26> = 5 is a write to PRODUCT<26>
