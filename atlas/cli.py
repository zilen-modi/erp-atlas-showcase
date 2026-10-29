"""`atlas` command line."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from atlas import config as cfgmod
from atlas import query, sync
from atlas.drift.diff import Hunk, to_markdown
from atlas.memory import facts
from atlas.store.db import Store

app = typer.Typer(no_args_is_help=True, help="ERP Atlas: legacy Pick ERP intelligence")
fact_app = typer.Typer(no_args_is_help=True, help="Learned facts: propose, review, accept, retire")
live_app = typer.Typer(no_args_is_help=True, help="Read-only live TEST access via the python layer")
app.add_typer(fact_app, name="fact")
user_app = typer.Typer(no_args_is_help=True, help="Atlas accounts: add people, reset passwords")
app.add_typer(live_app, name="live")
app.add_typer(user_app, name="user")


def _ctx() -> tuple[cfgmod.Config, Store]:
    cfg = cfgmod.load()
    return cfg, Store(cfg.store)


def _out(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------- sync/status

@app.command()
def status() -> None:
    """Sources, SHAs, last sync, counts, stale facts."""
    _cfg, st = _ctx()
    _out(query.status(st))


@app.command("sync")
def sync_cmd(
    full: bool = typer.Option(False, help="Re-scan every file instead of the git diff"),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="Index the mirror as-is, no git fetch"),
    worktree: Path | None = typer.Option(None, help="Also index a local erp checkout (uncommitted edits)"),
    live: bool = typer.Option(False, help="Also refresh a budget of programs from live TEST"),
    budget: int | None = typer.Option(None, help="Live programs per run (default from policy)"),
) -> None:
    """Bring the index up to date with erp (and optionally live TEST)."""
    cfg, st = _ctx()
    sync.sync_git(st, cfg, fetch=not no_fetch, full=full, log=typer.echo)
    if worktree:
        sync.sync_worktree(st, cfg, worktree.resolve(), log=typer.echo)
    if live:
        sync.sync_live(st, cfg, budget, log=typer.echo)


@app.command()
def ingest(slice_name: str = typer.Argument("transfer"),
           refresh: bool = typer.Option(False, help="Re-fetch live even if cached")) -> None:
    """Fetch a slice's programs from live TEST and compute drift for each."""
    cfg, st = _ctx()
    if st.get_state("git:erp") is None:
        sync.sync_git(st, cfg, log=typer.echo)
    sl = cfg.slices[slice_name]
    progs = sync.slice_programs(st, sl.seeds, sl.menus, sl.expand_calls)
    typer.echo(f"slice {slice_name}: {len(progs)} programs")
    sync.fetch_live_programs(st, cfg, progs, refresh=refresh, log=typer.echo)
    for p in progs:
        sync.compute_drift(st, cfg, p)
    rows = st.db.execute("SELECT program, class, COUNT(*) n FROM drift GROUP BY program, class").fetchall()
    per: dict[str, dict[str, int]] = {}
    for r in rows:
        if r["program"] in progs:
            per.setdefault(r["program"], {})[r["class"]] = r["n"]
    for p in progs:
        d = per.get(p)
        real = {k: v for k, v in (d or {}).items() if k in ("logic", "git-only", "live-only")}
        typer.echo(f"  {p:32} {'identical' if not d else (real or 'cosmetic only')}")


# ---------------------------------------------------------------- queries

@app.command()
def program(name: str, provenance: str = typer.Option("git")) -> None:
    """Overview: signature, calls, files, I/O, menus, callers, drift, facts."""
    _cfg, st = _ctx()
    _out(query.program_overview(st, name, provenance))


@app.command()
def callers(name: str) -> None:
    """Who CALLs / RUNs / CHAINs to this program, and which menus launch it."""
    _cfg, st = _ctx()
    _out(query.callers(st, name))


@app.command("who-writes")
def who_writes(pick_file: str, attr: int) -> None:
    """Programs that assign FILE<attr> (e.g. TRANSFER 10)."""
    _cfg, st = _ctx()
    _out(query.attr_sites(st, pick_file, attr, "write"))


@app.command("who-reads")
def who_reads(pick_file: str, attr: int) -> None:
    """Programs that read FILE<attr>."""
    _cfg, st = _ctx()
    _out(query.attr_sites(st, pick_file, attr, "read"))


@app.command()
def menu(code: str) -> None:
    """A MENU-ITEMS code: EXEC, usage, and its program."""
    _cfg, st = _ctx()
    _out(query.menu(st, code))


@app.command()
def lines(name: str, start: int, end: int, provenance: str = typer.Option("git")) -> None:
    """Print source lines (git | live | worktree)."""
    _cfg, st = _ctx()
    r = query.read_lines(st, name, start, end, provenance)
    typer.echo("\n".join(r.get("lines", [r.get("error", "")])))


@app.command()
def grep(text: str, provenance: str = typer.Option("git"), limit: int = 50) -> None:
    """Substring search over indexed BP source."""
    _cfg, st = _ctx()
    _out(query.search_code(st, text, provenance, limit))


@app.command()
def drift(name: str,
          refresh: bool = typer.Option(False, help="Re-fetch the live copy first"),
          all_classes: bool = typer.Option(False, "--all", help="Show cosmetic hunks too"),
          as_json: bool = typer.Option(False, "--json")) -> None:
    """Git vs live TEST differences for one program, classified and blamed."""
    cfg, st = _ctx()
    if refresh or st.source("live", "BP", name.upper()) is None:
        sync.fetch_live_programs(st, cfg, [name], refresh=refresh, log=typer.echo)
    res = sync.compute_drift(st, cfg, name)
    if res is None:
        typer.echo(f"{name}: need both a git and a live copy")
        raise typer.Exit(1)
    if as_json:
        _out(query.drift(st, name, None if all_classes else {"logic", "git-only", "live-only"}))
        return
    hunks: list[Hunk] = res["hunks"]  # type: ignore[assignment]
    show = {"whitespace", "comment", "label", "logic", "git-only", "live-only"} if all_classes else None
    typer.echo(f"git {str(res['git_sha'])[:9]} vs live TEST fetched {res['live_fetched_at']}")
    c = res.get("closest")
    if c:
        match = "matches exactly" if c["real_hunks"] == 0 else f"is closest to ({c['real_hunks']} real hunks off)"
        typer.echo(f"live TEST {match} git `{c['sha'][:9]}` {c['date']} {c['author']}: {c['summary']}"
                   f" -- {c['behind']} commit(s) behind main for this file")
    typer.echo("")
    typer.echo(to_markdown(name.upper(), hunks, res["commits"], show))  # type: ignore[arg-type]


# ---------------------------------------------------------------- live

@live_app.command("get")
def live_get(table: str, record_id: str, refresh: bool = typer.Option(False),
             head: int = typer.Option(0, help="Print the first N lines")) -> None:
    """Read one record from live TEST (read-only, cached)."""
    cfg, _st = _ctx()
    rec = sync.live_client(cfg).read_record(table, record_id, refresh=refresh)
    typer.echo(f"{table} {record_id}: {len(rec.lines)} lines hash={rec.hash[:12]} "
               f"fetched_at={rec.fetched_at}{' (cache)' if rec.from_cache else ''}")
    for i, ln in enumerate(rec.lines[:head], 1):
        typer.echo(f"{i}: {ln}")


# ---------------------------------------------------------------- facts

def _parse_cite(s: str) -> facts.Cite:
    """git:LG.XFER.MAINT:2036 | live:PROG:12 | doc:path/to/file.md | parity:run-id"""
    parts = s.split(":")
    if len(parts) >= 3 and parts[0] in facts.CODE_SOURCES:
        return facts.Cite(parts[0], parts[1], int(parts[2]))
    if len(parts) >= 2:
        return facts.Cite(parts[0], ":".join(parts[1:]))
    raise typer.BadParameter(f"bad cite {s!r}")


@fact_app.command("propose")
def fact_propose(text: str,
                 cite: list[str] = typer.Option(..., help="git:PROG:LINE | live:PROG:LINE | doc:PATH | parity:RUN"),
                 kind: str = typer.Option("rule"), scope: str = typer.Option(""),
                 rationale: str = typer.Option(""), by: str = typer.Option(..., help="your name"),
                 supersedes: str | None = typer.Option(None)) -> None:
    _cfg, st = _ctx()
    fid = facts.propose(st, text, kind, [_parse_cite(c) for c in cite], by, rationale, scope, supersedes)
    typer.echo(f"{fid} proposed (unconfirmed until a reviewer runs: atlas fact accept {fid} --by <name>)")


@fact_app.command("accept")
def fact_accept(fid: str, by: str = typer.Option(..., help="reviewer's name")) -> None:
    _cfg, st = _ctx()
    facts.accept(st, fid, by)
    typer.echo(f"{fid} accepted by {by}")


@fact_app.command("retire")
def fact_retire(fid: str, by: str = typer.Option(...), reason: str = typer.Option(...)) -> None:
    _cfg, st = _ctx()
    facts.retire(st, fid, by, reason)
    typer.echo(f"{fid} retired")


@fact_app.command("recite")
def fact_recite(fid: str, by: str = typer.Option(...)) -> None:
    """Re-pin a stale fact to the current line text and send it back to review."""
    _cfg, st = _ctx()
    facts.recite(st, fid, by)
    typer.echo(f"{fid} re-cited; status=proposed")


@fact_app.command("show")
def fact_show(fid: str) -> None:
    _cfg, st = _ctx()
    _out(facts.get(st, fid))


@fact_app.command("list")
def fact_list(q: str = typer.Argument(""), status: str | None = typer.Option(None),
              scope: str | None = typer.Option(None)) -> None:
    _cfg, st = _ctx()
    for f in facts.search(st, q, status, scope, limit=200):
        typer.echo(f"{f['id']} [{f['status']}] {f['scope'] or ''} {f['text']}")


@fact_app.command("check-stale")
def fact_check_stale() -> None:
    """Re-verify every live fact against the current index."""
    _cfg, st = _ctx()
    staled = facts.check_stale(st)
    for fid, why in staled:
        typer.echo(f"{fid} STALE: {'; '.join(why)}")
    typer.echo(f"{len(staled)} fact(s) newly stale")


# ---------------------------------------------------------------- people

@user_app.command("add")
def user_add(email: str, name: str = typer.Option(..., help="Their full name, shown on facts and answers"),
             admin: bool = typer.Option(False, help="Make them an admin")) -> None:
    """Add an account. Prints a one-time password; they choose their own at first sign-in."""
    from atlas import auth
    _, st = _ctx()
    try:
        user, temp = auth.create_user(st, email, name, "admin" if admin else "member", by="cli")
    except auth.AuthError as e:
        raise typer.BadParameter(str(e)) from e
    typer.echo(f"Added {user['name']} <{user['email']}> as {user['role']}.")
    typer.echo(f"One-time password: {temp}   (shown once; they change it at first sign-in)")


@user_app.command("list")
def user_list() -> None:
    from atlas import auth
    _, st = _ctx()
    for u in auth.list_users(st):
        claude = u["claude"]["kind"] if u["claude"] else "-"
        typer.echo(f"{u['email']:32} {u['name']:24} {u['role']:7} {'active' if u['active'] else 'off':7} "
                   f"claude:{claude}")


@user_app.command("passwd")
def user_passwd(email: str) -> None:
    """A new one-time password for someone who is locked out (an admin can also do this on the Admin page)."""
    from atlas import auth
    _, st = _ctx()
    row = st.db.execute("SELECT id FROM app_user WHERE email=?", (email.strip().lower(),)).fetchone()
    if not row:
        raise typer.BadParameter(f"No account for {email}")
    typer.echo(f"One-time password: {auth.reset_password(st, row['id'], 'cli')}")


# ---------------------------------------------------------------- summaries and search by meaning

@app.command()
def summarize(limit: int = typer.Option(25, help="How many programs (most-used first)"),
              program: list[str] = typer.Option([], "--program", help="Just these programs (repeatable)"),
              model: str = typer.Option("claude-sonnet-5-5", help="Claude model to write with")) -> None:
    """Write plain-English summaries with Claude (your Claude Code login), then update the meaning index."""
    from atlas import chat, knowledge
    cfg, st = _ctx()
    r = knowledge.summarize(st, cfg, limit, chat.Person(model=model), typer.echo, only=program or None)
    _out(r)


@app.command("backup")
def backup_cmd() -> None:
    """Back up the store (accounts, facts, summaries, scenarios, chats), the token key and settings, now."""
    from atlas import backup
    cfg = cfgmod.load()
    _out(backup.backup(cfg.store))


@app.command("ask-eval")
def ask_eval_cmd(case: list[str] = typer.Option([], "--case", help="Only these case ids (repeatable)"),
                 model: str = typer.Option("", help="Claude model (default: the configured one)")) -> None:
    """How good Ask Atlas's answers are: ask the golden set and score them (one Ask Atlas answer per case)."""
    from atlas import ask_eval, chat
    cfg, st = _ctx()
    r = ask_eval.run(st, cfg, chat.Person(model=model), case or None, typer.echo)
    for x in r["results"]:
        typer.echo(f"{x['id']:6} {x['status']:8} {x['score']:.2f}  {x['q'][:70]}")
    typer.echo(f"verified: {r['verified']}  draft: {r['draft']}  cost: ${r['cost_usd']}")


@app.command()
def meaning(description: str, limit: int = 10) -> None:
    """Search summaries and facts by meaning."""
    from atlas import semantic
    _, st = _ctx()
    for r in semantic.search(st, description, limit)["results"]:
        where = f"{r['program']}:{r['start']}" if r.get("start") else r.get("program") or r.get("id")
        typer.echo(f"{r['score']:.2f}  {where:28} {r.get('title') or r.get('text')}")


# ---------------------------------------------------------------- serve / mcp

@app.command("finder-eval")
def finder_eval_cmd(case: list[str] = typer.Option([], "--case", help="Only these case ids (repeatable)"),
                    offline: bool = typer.Option(False, help="Score the criteria only, without TEST")) -> None:
    """How accurate Test data's 'Describe the record you need' is (one Claude call per case)."""
    from atlas import finder_eval
    cfg, st = _ctx()
    client = None if offline else sync.live_client(cfg, parallel=True)
    r = finder_eval.run(st, cfg, client, case or None, typer.echo)
    for x in r["results"]:
        typer.echo(f"{x['id']:6} {x['status']:8} {x['score']:.2f}  {x['query'] or '(no selection)'}")
    typer.echo(f"verified: {r['verified']}  draft: {r['draft']}  cost: ${r['cost_usd']}")


@app.command()
def serve(port: int = typer.Option(8765, help="API port (binds 127.0.0.1 only)")) -> None:
    """Run the HTTP API used by the web UI."""
    from atlas.api import serve as run
    run(port)


@app.command()
def mcp() -> None:
    """Run the MCP server on stdio."""
    from atlas.mcp.server import main
    main()


if __name__ == "__main__":
    app()
