import pytest

from atlas import reports


def test_only_atlas_pages_can_be_rendered():
    assert reports._page_url("/program/W4DEMO") == f"{reports.WEB_URL}/program/W4DEMO?print=1"
    assert reports._page_url("/ask?chat=abc&print=1") == f"{reports.WEB_URL}/ask?chat=abc&print=1"
    for bad in ("https://example.com/x", "//example.com/x", "/api/reports", "program"):
        with pytest.raises(reports.ReportError):
            reports._page_url(bad)


def test_filename_is_safe():
    assert reports.filename("Compare · 11095 vs 11094") == "ERP-Atlas-Compare-11095-vs-11094.pdf"
