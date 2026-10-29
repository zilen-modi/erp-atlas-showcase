from atlas.drift.diff import compare, summarize

GIT = [
    "      A = 1",
    "      *",
    "      IF XF<3> = 142 THEN ;* ANTF",
    "      B = 2 ;* old note",
    "      IF NEW.SW AND XF<10> < DATE() THEN",
    "         MSG = 'Date Required Cannot be in the Past.'",
    "      END",
    "      C = 3",
]
LIVE = [
    "      A  = 1",
    "1671: *",
    "      IF XF<1> = 142 THEN ;* ANTF",
    "      B = 2 ;* new note",
    "      C = 3",
    "REMOVE.BOM.LINE:",
    "      DEL XF<27,1>",
    "      RETURN",
]


def classes(h):
    return [x.cls for x in h]


def test_classification():
    h = compare(GIT, LIVE)
    s = summarize(h)
    assert s == {"whitespace": 1, "label": 1, "comment": 1, "logic": 1, "git-only": 1, "live-only": 1}
    logic = next(x for x in h if x.cls == "logic")
    assert logic.git_lines == ["      IF XF<3> = 142 THEN ;* ANTF"]      # not swallowed by cosmetics
    assert next(x for x in h if x.cls == "git-only").git_start == 5       # the past-date guard
    assert next(x for x in h if x.cls == "live-only").live_lines == ["      DEL XF<27,1>", "      RETURN"]
    label = next(x for x in h if x.cls == "label")
    assert label.live_lines == ["1671: *", "REMOVE.BOM.LINE:"] and label.labels == ["1671", "REMOVE.BOM.LINE"]


def test_cosmetic_only():
    assert classes(compare(["      A = 1"], ["      A  =  1"])) == ["whitespace"]
    assert classes(compare(["      *"], ["1671: *"])) == ["label"]
    assert classes(compare(["      X = 1 ;* a"], ["      X = 1 ;* b"])) == ["comment"]
    assert classes(compare(["      * one"], ["      * two"])) == ["comment"]


def test_label_escalates_only_when_dangling():
    # live has label 1671 and branches to it; git dropped both -> cosmetic here
    assert classes(compare(["      X = 1"], ["1671: X = 1"], set(), {"1671"})) == ["label"]
    # git dropped the label but git still branches to it -> would not compile
    assert classes(compare(["      X = 1"], ["1671: X = 1"], {"1671"}, {"1671"})) == ["logic"]
    assert classes(compare(["      *"], ["1671: *"], {"1671"}, set())) == ["logic"]


def test_same_label_respaced_is_whitespace_even_if_targeted():
    assert classes(compare(["GUI.DECODE.EVENT: *"], ["GUI.DECODE.EVENT:*"], {"GUI.DECODE.EVENT"})) == \
        ["whitespace"]


def test_identical():
    assert compare(GIT, GIT) == []
