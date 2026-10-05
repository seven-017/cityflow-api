"""进程内 TTL 缓存的测试。

这块有两个容易写错的点，下面各钉了一条：
过期之后到底还读不读得到，以及未命中那一刻十个请求一起进来会不会算十遍。
"""

import threading
import time

from app.core.cache import TTLCache


def test_set_get_roundtrip():
    cache = TTLCache(ttl_seconds=60)
    cache.set("k", "v")
    assert cache.get("k") == "v"


def test_missing_key_returns_none():
    """没存过的 key 返回 None，不抛异常。"""
    assert TTLCache(ttl_seconds=60).get("nope") is None


def test_expired_entry_returns_none():
    cache = TTLCache(ttl_seconds=0.05)
    cache.set("k", "v")
    time.sleep(0.08)
    assert cache.get("k") is None


def test_expired_entry_is_actually_removed():
    """过期不只是「读不到」，还得真从字典里删掉（惰性删除）。

    判断办法是拿 clear 的返回值当探针：get 那一下顺手删了的话，
    再 clear 就已经没东西可清。

    不删的话它会一直占着内存当垃圾，而且以后每次 get 还要再判一遍过期。
    """
    cache = TTLCache(ttl_seconds=0.05)
    cache.set("k", "v")
    time.sleep(0.08)

    cache.get("k")  # 这一次 get 应该顺手把它删了
    assert cache.clear() == 0


def test_custom_ttl_overrides_default():
    """单条可以带自己的 ttl，不受缓存默认值影响。"""
    cache = TTLCache(ttl_seconds=9999)
    cache.set("k", "v", ttl_seconds=0.05)
    time.sleep(0.08)
    assert cache.get("k") is None


def test_get_or_compute_does_not_call_factory_on_hit():
    """命中时不能调 factory。

    这不是洁癖：Dashboard 那个 factory 一跑就是十几秒的聚合，
    命中还调一次的话缓存就白做了。
    """
    cache = TTLCache(ttl_seconds=60)
    calls: list[int] = []

    def factory() -> str:
        calls.append(1)
        return "computed"

    assert cache.get_or_compute("k", factory) == "computed"
    assert cache.get_or_compute("k", factory) == "computed"
    assert len(calls) == 1


def test_get_or_compute_shares_one_result_across_ten_threads():
    """十个线程同时未命中，factory 最多只该跑两次。

    闸门上限是 2，所以「同时在算」的顶多两个；后来的等在前面两个之后，
    一进闸门先查一次缓存，发现有值了就直接拿 —— 不再算一遍。

    这条测的就是闸门里那句「再查一次缓存」。少了它，十个线程会排着队
    一个一个算完，闸门只限制了「同时在算几个」，没拦住重复算。
    """
    cache = TTLCache(ttl_seconds=60, max_concurrent_computes=2)
    calls: list[int] = []
    counter_lock = threading.Lock()
    barrier = threading.Barrier(10)

    def factory() -> str:
        with counter_lock:
            calls.append(1)
        # 睡一下，让并发的窗口真的张开 —— 不然第一个可能已经算完存好了，
        # 后面九个进来直接命中，就测不出闸门有没有用了
        time.sleep(0.1)
        return "value"

    results: list[str] = []
    results_lock = threading.Lock()

    def worker() -> None:
        barrier.wait()  # 十个一起冲，制造「同一瞬间全部未命中」
        value = cache.get_or_compute("k", factory)
        with results_lock:
            results.append(value)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 10
    assert all(value == "value" for value in results)
    # 关键断言：不是 10 次。实际会是 1 或 2，取决于第一个算完之前
    # 第二个有没有挤进闸门 —— 两种情况都算对，10 就是错
    assert len(calls) <= 2


def test_clear_returns_number_of_removed_entries():
    """clear 返回清掉几条，工单写操作之后要用这个数写日志/判断。"""
    cache = TTLCache(ttl_seconds=60)
    cache.set("a", 1)
    cache.set("b", 2)

    assert cache.clear() == 2
    assert cache.get("a") is None
    assert cache.get("b") is None
