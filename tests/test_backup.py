from atlas import backup
from atlas.store.db import Store


def test_backups_copy_the_store_and_keep_only_the_newest(tmp_path, monkeypatch):
    db = tmp_path / "atlas.db"
    st = Store(db)
    st.db.execute("INSERT INTO app_user VALUES ('u1','a@b','A','admin','x',1,0,'t',NULL)")
    st.commit()
    key = tmp_path / "secret.key"
    key.write_text("k")
    monkeypatch.setattr(backup, "EXTRAS", (key,))
    stamps = iter(f"2026010{i}-000000" for i in range(1, 6))

    class FakeNow:
        @staticmethod
        def now(tz=None):
            from datetime import datetime
            return datetime.strptime(next(stamps), "%Y%m%d-%H%M%S")
    monkeypatch.setattr(backup, "datetime", type("D", (), {"now": FakeNow.now, "strptime": staticmethod(
        __import__("datetime").datetime.strptime)}))
    for _ in range(4):
        r = backup.backup(db, tmp_path / "b", keep=3)
    kept = sorted(p.name for p in (tmp_path / "b").iterdir())
    assert kept == ["20260102-000000", "20260103-000000", "20260104-000000"]
    import gzip
    restored = tmp_path / "restored.db"
    restored.write_bytes(gzip.decompress((tmp_path / "b" / "20260104-000000" / "atlas.db.gz").read_bytes()))
    copy = Store(restored)
    assert copy.db.execute("SELECT email FROM app_user").fetchone()[0] == "a@b"
    assert (tmp_path / "b" / "20260104-000000" / "secret.key").stat().st_mode & 0o777 == 0o600
    assert r["removed"] == 1
