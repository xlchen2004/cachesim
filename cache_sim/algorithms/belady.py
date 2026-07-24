"""Belady 最优驱逐策略（离线）。

驱逐下一次被请求时间最远（或不再请求）的项，是离线最优算法，
作为在线算法竞争比的基准。对象级缓存。

需要预知未来：调用方（模拟器）需为每次访问预计算该 key 的 next_use
并通过 ``ctx.next_use`` 传入。
"""

from cache_sim.core.policy import INF, EvictionPolicy
from cache_sim.algorithms.registry import register


@register("belady")
class Belady(EvictionPolicy):
    """Belady 最优：驱逐 next_use 最大的项。"""

    offline = True

    def __init__(self):
        super().__init__("Belady")
        self._next_use = {}  # key -> 下一次被请求的时间

    def on_hit(self, key, ctx):
        self._next_use[key] = ctx.next_use

    def on_admit(self, key, ctx):
        self._next_use[key] = ctx.next_use

    def on_evict(self, key):
        self._next_use.pop(key, None)

    def select_victim(self, candidates, ctx):
        # 选 next_use 最大（最远 / 不再请求=INF）的项
        return max(candidates, key=lambda k: self._next_use.get(k, INF))

    def reset(self):
        self._next_use.clear()
