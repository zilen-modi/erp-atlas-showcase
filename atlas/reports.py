"""PDF reports of any Atlas page.

The web UI renders every page in a print layout when the URL carries ?print=1
(no navigation or buttons, accordions open, a report header). Headless Chrome
loads that URL, waits for the page's data to arrive, and prints it to PDF with
page numbers. Each PDF is kept in .data/reports so its link can be shared.
"""

from __future__ import annotations

import html
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from atlas.config import ROOT
from atlas.store.db import Store, now

SESSION_COOKIE = "atlas_session"     # auth.COOKIE: the headless browser signs in with it
REPORT_DIR = Path(os.environ.get("ATLAS_REPORTS", ROOT / ".data" / "reports"))
WEB_URL = os.environ.get("ATLAS_WEB_URL", "http://localhost:3217").rstrip("/")

Result = dict[str, Any]


class ReportError(ValueError):
    pass


def _page_url(page: str) -> str:
    """Only paths of this Atlas are rendered: never an arbitrary URL."""
    parts = urlsplit(page)
    if parts.scheme or parts.netloc or not parts.path.startswith("/") or parts.path.startswith("/api/"):
        raise ReportError("export a page of Atlas, e.g. /program/LG.XFER.MAINT")
    query = "&".join(q for q in parts.query.split("&") if q and not q.startswith("print="))
    return f"{WEB_URL}{parts.path}?{query + '&' if query else ''}print=1"


def _footer(title: str, sha: str, env: str) -> str:
    t = html.escape(title[:90])
    return (
        '<div style="font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; font-size: 7.5px; '
        'color: #6b7280; width: 100%; padding: 0 14mm; display: flex; justify-content: space-between;">'
        f'<span>ERP Atlas · {t}</span>'
        f'<span>git main {html.escape(sha or "—")} · {html.escape(env)} · generated <span class="date"></span></span>'
        '<span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>'
    )


def render_pdf(page: str, title: str, sha: str, env: str, out: Path, timeout_s: float = 90,
               session: str | None = None) -> int:
    """Print one Atlas page to `out`, signed in as whoever asked (`session` is their sign-in token).
    Returns the page count."""
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import sync_playwright

    url = _page_url(page)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except PWError:
            browser = p.chromium.launch()         # Playwright's own Chromium, if installed
        try:
            ctx = browser.new_context(viewport={"width": 1240, "height": 1754}, color_scheme="light")
            if session:
                ctx.add_cookies([{"name": SESSION_COOKIE, "value": session, "url": WEB_URL}])
            pg = ctx.new_page()
            pg.goto(url, wait_until="networkidle", timeout=timeout_s * 1000)
            if urlsplit(pg.url).path == "/login":
                raise ReportError("Couldn't export: the page asked for sign-in. Sign in again and retry")
            # pages that load data client-side flag themselves busy until it arrives
            pg.wait_for_function("() => !document.querySelector('[data-report-busy]')", timeout=timeout_s * 1000)
            pg.wait_for_load_state("networkidle")
            pg.emulate_media(media="print")
            # scale 0.8: the page lays out ~880px wide, close to the desktop layout, and still fits A4
            pdf = pg.pdf(format="A4", print_background=True, prefer_css_page_size=False, scale=0.8,
                         margin={"top": "14mm", "bottom": "16mm", "left": "12mm", "right": "12mm"},
                         display_header_footer=True, header_template="<span></span>",
                         footer_template=_footer(title, sha, env))
        finally:
            browser.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pdf)
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


def create(store: Store, page: str, title: str, sha: str, env: str, user_id: str | None = None,
           session: str | None = None) -> Result:
    title = re.sub(r"\s+", " ", title).strip() or page
    rid = uuid.uuid4().hex[:10]
    out = REPORT_DIR / f"{rid}.pdf"
    pages = render_pdf(page, title, sha, env, out, session=session)
    store.db.execute("INSERT INTO report (id, title, page, file, bytes, pages, git_sha, environment, created_at, "
                     "user_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (rid, title, page, out.name, out.stat().st_size, pages, sha, env, now(), user_id))
    store.commit()
    return get(store, rid)


def get(store: Store, rid: str) -> Result:
    r = store.db.execute("SELECT * FROM report WHERE id=?", (rid,)).fetchone()
    if r is None:
        raise ReportError(f"no report {rid}")
    return {**dict(r), "filename": filename(r["title"])}


def path_of(store: Store, rid: str) -> Path:
    return REPORT_DIR / get(store, rid)["file"]


def filename(title: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")[:70] or "report"
    return f"ERP-Atlas-{slug}.pdf"


def list_all(store: Store, limit: int = 200, user_id: str | None = None) -> list[Result]:
    """Your PDFs (and those from before sign-in). Anyone signed in can open one from its link."""
    mine = " WHERE user_id = ? OR user_id IS NULL" if user_id else ""
    rows = store.db.execute(f"SELECT * FROM report{mine} ORDER BY created_at DESC LIMIT ?",
                            (*([user_id] if user_id else []), limit))
    return [{**dict(r), "filename": filename(r["title"])} for r in rows]


def delete(store: Store, rid: str) -> None:
    p = path_of(store, rid)
    store.db.execute("DELETE FROM report WHERE id=?", (rid,))
    store.commit()
    p.unlink(missing_ok=True)
