import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from app.core.config import get_settings

T = TypeVar("T")


@dataclass(frozen=True)
class _Entry:
    """缓存里存的一条。frozen 是为了提醒"这东西是被共享的，别改它"。"""

    value: Any
    expires_at: float


class TTLCache:
    """一个极简的进程内缓存：按 key 存值，到点过期。

    为什么要缓存、为什么是这个形状 —— 看下面「为什么不上 Redis」那一整段。

    故意没做的三件事，每一条都有理由（不是漏了）：

    1. 不做 LRU / 容量上限。
       当前 key 只有个位数（dashboard:overview 这种），不存在"键会无限增长"
       的情景。给不存在的场景写淘汰策略，是凭空多一堆要维护的分支。
       真到了 key 会随查询参数变化的时候（比如 analytics 按日期范围成键）再说。

    2. 不做独立的过期清理线程。
       过期就是"下次读到它时发现过期了，重算" —— 惰性删除。
       key 只有个位数，攒不下垃圾，不值当为它起一个后台线程。

    3. 不做完整的 singleflight（把"同一个 key 正在被算"这件事管起来）。
       见 get_or_compute 里那段说明 —— 用"双重检查 + 信号量"做了一个
       便宜的近似，够用。
    """

    def __init__(self, ttl_seconds: float, max_concurrent_computes: int = 2) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        # 值是共享的，取出来的是同一个对象引用 —— 所以 _Entry 是 frozen 的。
        # 锁只管字典本身的读写，不管住在里面的对象
        self._entries: dict[str, _Entry] = {}
        # 同一时刻最多几个在真算。这是文档定的（"最多 2 个并发聚合任务，
        # 降低本地 MySQL I/O 争用"）。
        #
        # 它挡的是"缓存未命中时一拥而上"：缓存过期的瞬间十个请求同时进来，
        # 十个都去查库、把 MySQL 的 I/O 抢干净。有了这个闸门，最多两个在查，
        # 剩下的排队 —— 顺带也把缓存击穿的后果压住了（见 get_or_compute）。
        self._gate = threading.BoundedSemaphore(max_concurrent_computes)

    def get(self, key: str) -> Any | None:
        """取。过期了当没有，顺手把它删掉（惰性删除）。

        返回 None 表示"没有可用值"，不区分"从来没有过"和"过期了" ——
        调用方对这两种情况的处理是一样的（重算），分开没意义。
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= time.monotonic():
                # 过期了。删掉是有意义的：不清的话它会一直占着内存当垃圾，
                # 而且下次 get 还要再判一遍过期
                del self._entries[key]
                return None
            return entry.value

    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        """存。ttl_seconds 不传就用这个缓存默认的。"""
        ttl = self._ttl if ttl_seconds is None else ttl_seconds
        with self._lock:
            # 用 monotonic 不用 time.time()：墙上时钟会被 NTP 校时、被手动改，
            # 一次往回调的校时能让"已经过期"的东西又变成"还没过期"。
            # monotonic 只保证单调递增，正是过期判断需要的东西
            self._entries[key] = _Entry(
                value=value, expires_at=time.monotonic() + ttl
            )

    def get_or_compute(
        self, key: str, factory: Callable[[], T], ttl_seconds: float | None = None
    ) -> T:
        """拿到就用，拿不到就调 factory 算一个并存起来。

        factory 只会在真正需要的时候被调用（命中时不调）——
        这很重要，因为 Dashboard 那个 factory 一跑就是四五秒。

        闸门里还要再查一次缓存，这一句是关键：
        十个请求同时未命中，第一个过闸门去算，第二个也过闸门去算（并发上限是 2），
        第三个到第十个就堵在闸门外面。等前面两个算完放行时，
        它们只要在闸门里再看一眼缓存就会发现"已经有了"，直接拿 —— 不用再算。
        ⇒ 十个请求最多真算两次，不是十次。

        这是个便宜的 singleflight 近似：完整的做法要额外维护一张
        "谁正在算哪个 key"的表，每个 key 一个 Event 让后来者等。
        那种写法对"多个不同 key 并发"才划算，这儿就一两个 key，不值当。
        """
        cached = self.get(key)
        if cached is not None:
            return cached

        with self._gate:
            cached = self.get(key)
            if cached is not None:
                return cached
            value = factory()
            self.set(key, value, ttl_seconds=ttl_seconds)
            return value

    def clear(self) -> int:
        """清掉所有条目，返回清了几条。

        工单（和工时）的写操作之后要调这个 —— 数据变了，缓存里的聚合就旧了。
        当前只有一两个 key，所以整体清掉最简单；
        哪天 key 涨到几十个，再改成按前缀清。
        """
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
            return n


# 为什么不上 Redis
# ----------------------------------------------------------------------------
#
# 这一条不是我们自己想的，是架构文档 architecture.md 定的：
#
#     ### Dashboard 缓存
#     Dashboard 和 Analytics 聚合较重。当前使用：
#     - 进程内 TTL 缓存 5 分钟
#     - 最多 2 个并发聚合任务，降低本地 MySQL I/O 争用
#     - 工单写操作清除 Dashboard 缓存
#     当前没有引入 Redis。多实例部署时应替换为共享缓存。
#
# 而且同一份文档在「为什么不做更复杂的架构」那一节里，把
# 「为了展示而加入的 Redis」跟微服务 / Kafka / K8s / 分布式事务列在一起 ——
# 那是要被否掉的东西，不是要往上加的东西。
#
# 回头看这个判断站得住，因为它跟判据对得上。缓存该不该上，就两条：需要、且贵。
#
#   需要吗？需要。实测一次 overview 的聚合要 5531 ms（5 个 COUNT / SUM，
#   其中最大的 SUM(hours) + SUM(cost) 在 320 万行上要 3156 ms）。
#   5 秒的接口没人能忍，而这一页的数据又不需要秒级新鲜 ——
#   它看的是量级和趋势，5 分钟前的数字完全够用。
#
#   贵吗？算起来确实贵。但"贵"要跟"缓存本身要花多少"一起看：
#   进程内缓存就是内存里一个 dict，成本约等于零。
#   引入 Redis 要加一个组件、一套连接配置、一份部署依赖、一种新的故障模式
#   （Redis 挂了接口怎么办？）。用后者换前者，省下的 5 秒是同一份，
#   多出来的是要维护的东西。
#
# 那什么时候该换成 Redis？文档也说了：多实例部署的时候。
# 因为进程内缓存是每个进程各存一份 —— 两个实例会有"在 A 上改了数据、
# B 的缓存还是旧的"，而且 A 清缓存清不到 B。单实例跑着的时候没这个问题。
# 所以这不是"将来一定要换"，是"换了部署形态才需要换"。


# 缓存单例。为什么不用模块级直接 `CACHE = TTLCache(...)` ——
# 那样配置是"import 的时候就冻住"的，而 main.py 里专门说过不要那么干
# （换个配置就要重开进程，测试里想换更是麻烦）。所以第一次用的时候才建。
_cache_lock = threading.Lock()
_dashboard_cache: TTLCache | None = None


def get_dashboard_cache() -> TTLCache:
    """拿 Dashboard 缓存那个单例。第一次调用时才建，配置这时候才读。"""
    global _dashboard_cache
    if _dashboard_cache is None:
        with _cache_lock:
            # 双检锁。两个线程同时第一次调用时，只有一个能进来建，
            # 另一个在外面等完进来会发现已经有了 —— 于是不会建出两个缓存
            if _dashboard_cache is None:
                settings = get_settings()
                _dashboard_cache = TTLCache(
                    ttl_seconds=settings.dashboard_cache_ttl_seconds,
                    max_concurrent_computes=(
                        settings.dashboard_max_concurrent_aggregations
                    ),
                )
    return _dashboard_cache


def invalidate_dashboard_cache() -> int:
    """让 Dashboard 的缓存作废，返回清了几条。

    工单和工时的写操作之后都要调这个。为什么要写操作来清、而不是等它自然过期：
    TTL 是 5 分钟，那意味着"我建了一张单，点一下 Dashboard 看不到它"，
    最长要等 5 分钟 —— 用户会以为没保存成功。
    写操作自己知道自己改了数据，顺手清掉最直接。

    注意这是"进程内"缓存，所以多实例部署时每个实例各清各的、
    也会各自不一致 —— 那是换成共享缓存（Redis）才能解决的问题，
    文档里也是这么说的（"多实例部署时应替换为共享缓存"）。
    单实例跑着的时候它不是问题。
    """
    return get_dashboard_cache().clear()
