import httpx
import pytest

from atlas.sources.live import LiveClient, NotAllowed


def client(tmp_path, handler):
    return LiveClient("http://localhost:6000/api/v1", min_interval_s=0, cache_dir=tmp_path,
                      deny_tables=["CC.HISTORY"], transport=httpx.MockTransport(handler))


def test_allowlist_blocks_everything_else(tmp_path):
    cl = client(tmp_path, lambda r: httpx.Response(200, json={}))
    for method, path in [("POST", "/routine/call"), ("POST", "/w5/readu"), ("POST", "/w5/release"),
                         ("GET", "/table/query"), ("DELETE", "/table")]:
        with pytest.raises(NotAllowed):
            cl._request(method, path)


def test_denylist(tmp_path):
    cl = client(tmp_path, lambda r: httpx.Response(200, json={"data": []}))
    with pytest.raises(NotAllowed):
        cl.read_record("CC.HISTORY", "1")
    with pytest.raises(NotAllowed):
        cl.read_record("DICT CC.HISTORY", "1")


def test_read_and_cache(tmp_path):
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, json={"success": True, "data": ["      SUBROUTINE X", "      RETURN"],
                                         "count": 2, "error": None})

    cl = client(tmp_path, handler)
    r1 = cl.read_record("BP", "X")
    assert r1.lines == ["      SUBROUTINE X", "      RETURN"] and not r1.from_cache
    assert "table_name=BP" in calls[0] and "record_id=X" in calls[0]
    r2 = cl.read_record("BP", "X")
    assert r2.from_cache and r2.hash == r1.hash and len(calls) == 1
    cl.read_record("BP", "X", refresh=True)
    assert len(calls) == 2


def test_server_error_is_retried_then_raised(tmp_path):
    n = []

    def handler(req):
        n.append(1)
        return httpx.Response(503, json={"error": "Database connection failed"})

    cl = client(tmp_path, handler)
    with pytest.raises(Exception, match="VPN"):
        cl.read_record("BP", "X", refresh=True)
    assert len(n) == 2


def test_multivalue_arrays_become_marks():
    from atlas.sources.live import to_attr
    assert to_attr(["C", "644817*9", "539328*9"]) == "C\xfd644817*9\xfd539328*9"
    assert to_attr([["a", "b"], "c"]) == "a\xfcb\xfdc"
    assert to_attr(["", "", ""]) == "\xfd\xfd" and to_attr(None) == "" and to_attr(7) == "7"


def test_parallel_reads_are_capped(tmp_path):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import httpx

    from atlas.sources.live import LiveClient
    state = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def handler(req):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return httpx.Response(200, json={"success": True, "data": ["x"], "error": None})

    cl = LiveClient("http://t/api/v1", min_interval_s=0.01, cache_dir=None,
                    transport=httpx.MockTransport(handler), parallel=3)
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda i: cl.read_record("DOC", str(i), refresh=True), range(12)))
    assert 1 < state["peak"] <= 3


def test_clients_in_different_processes_share_one_budget_for_test(tmp_path):
    """Each Ask Atlas chat has its own tools process; together they must not exceed the machine-wide limit."""
    import threading
    import time as _time

    import httpx

    from atlas.sources.live import LiveClient
    state = {"now": 0, "max": 0}
    guard = threading.Lock()

    def handler(request):
        with guard:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        _time.sleep(0.05)
        with guard:
            state["now"] -= 1
        return httpx.Response(200, json={"success": True, "data": ["x"]})
    clients = [LiveClient("http://t/api/v1", min_interval_s=0.01, transport=httpx.MockTransport(handler), parallel=4,
                          lock_dir=tmp_path / "locks", max_parallel=2) for _ in range(3)]
    threads = [threading.Thread(target=lambda c=c, i=i: [c.read_record("PRODUCT", f"{i}-{n}") for n in range(4)])
               for i, c in enumerate(clients)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state["max"] == 2          # three clients asking for up to 4 each: never more than 2 in flight
