import subprocess
from pathlib import Path

from atlas import sync
from atlas.config import Config, GitConfig, LiveConfig, SliceConfig
from atlas.memory import facts
from atlas.memory.facts import Cite
from atlas.store.db import Store


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def commit(repo: Path, msg: str) -> str:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def setup(tmp_path: Path):
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    write(origin, "src/BP/W4SUBA", "      SUBROUTINE W4SUBA(X)\n      CALL W4SUBB(X)\n      RETURN\n")
    write(origin, "src/BP/W4SUBB", "      SUBROUTINE W4SUBB(X)\n      X<10> = 1\n      RETURN\n")
    write(origin, "src/BP/V__F.RECONCILE", "      X = 1\n")
    write(origin, "src/MENU-ITEMS/M1", "RUN BP W4SUBA\n42\n21284\n")
    write(origin, "scripts/filename_map.json",
          '{"original":"V?\\F.RECONCILE","sanitized":"V__F.RECONCILE","reldir":""}\n')
    commit(origin, "init")
    cfg = Config(
        environment="TEST",
        live=LiveConfig("http://localhost:6000/api/v1", 5, 0, tmp_path / "cache", []),
        git=GitConfig(str(origin), origin, tmp_path / "mirror.git", "main",
                      ["src/BP", "src/MENU-ITEMS", "src/DICT"], "scripts/filename_map.json"),
        store=tmp_path / "atlas.db", live_budget=5,
        slices={"t": SliceConfig(seeds=["W4SUBA"], menus=["M1"])},
    )
    return origin, cfg


def test_incremental_sync_follows_origin(tmp_path):
    origin, cfg = setup(tmp_path)
    st = Store(cfg.store)
    r1 = sync.sync_git(st, cfg, log=lambda _m: None)
    assert r1.parsed == 4                                     # 3 BP + 1 menu; scripts/ is not indexed
    assert st.db.execute("SELECT name FROM program WHERE name LIKE 'V%'").fetchone()["name"] == "V?\\F.RECONCILE"
    assert st.db.execute("SELECT program, used FROM menu").fetchone()[:] == ("W4SUBA", 42)
    assert sync.slice_programs(st, ["W4SUBA"], ["M1"], 1) == ["W4SUBA", "W4SUBB"]

    fid = facts.propose(st, "W4SUBB sets X<10>", "rule", [Cite("git", "W4SUBB", 2)], "zilen")
    facts.accept(st, fid, "Ben")

    r2 = sync.sync_git(st, cfg, log=lambda _m: None)
    assert r2.parsed == 0                                     # nothing changed upstream

    write(origin, "src/BP/W4SUBB", "      SUBROUTINE W4SUBB(X)\n      X<11> = 1\n      RETURN\n")
    (origin / "src/BP/V__F.RECONCILE").unlink()
    head = commit(origin, "change B, drop V")
    r3 = sync.sync_git(st, cfg, log=lambda _m: None)
    assert r3.to_sha == head
    assert r3.parsed == 1 and r3.deleted == 1                 # only the changed file re-parsed
    assert r3.changed_programs == {"W4SUBB", "V?\\F.RECONCILE"}
    assert [s[0] for s in r3.staled] == [fid]
    assert facts.get(st, fid)["status"] == "stale"
    attrs = {r["attr"] for r in st.db.execute("SELECT attr FROM attr_ref WHERE program='W4SUBB'")}
    assert attrs == {11}
    assert st.get_state("git:erp")["last_sha"] == head


def test_user_checkout_untouched_and_worktree_mode(tmp_path):
    origin, cfg = setup(tmp_path)
    before = (git(origin, "rev-parse", "HEAD"), git(origin, "status", "--porcelain"))
    st = Store(cfg.store)
    sync.sync_git(st, cfg, log=lambda _m: None)
    write(origin, "src/BP/W4SUBA", "      SUBROUTINE W4SUBA(X)\n      CALL W4SUBC(X)\n      RETURN\n")
    after_edit_status = git(origin, "status", "--porcelain")
    rep = sync.sync_worktree(st, cfg, origin, log=lambda _m: None)
    assert "W4SUBA" in rep.changed_programs
    targets = {r["target"] for r in st.db.execute(
        "SELECT target FROM call_edge WHERE provenance='worktree' AND program='W4SUBA'")}
    assert targets == {"W4SUBC"}
    git_targets = {r["target"] for r in st.db.execute(
        "SELECT target FROM call_edge WHERE provenance='git' AND program='W4SUBA'")}
    assert git_targets == {"W4SUBB"}
    assert git(origin, "rev-parse", "HEAD") == before[0]
    assert git(origin, "status", "--porcelain") == after_edit_status   # Atlas changed nothing
