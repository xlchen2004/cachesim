"""LRU（Least Recently Used）驱逐策略。

基于访问时间戳，驱逐最近最少访问的项。对象级缓存。
"""

from cache_sim.core.policy import EvictionPolicy
from cache_sim.algorithms.registry import register


@register("lru")
class LRU(EvictionPolicy):
    """最近最少使用：驱逐 last_access 时间最小的项。"""

    def __init__(self):
        super().__init__("LRU")
        self._last_access = {}  # key -> 最后访问逻辑时间

    def on_hit(self, key, ctx):
        self._last_access[key] = ctx.time

    def on_admit(self, key, ctx):
        self._last_access[key] = ctx.time

    def on_evict(self, key):
        self._last_access.pop(key, None)

    def select_victim(self, candidates, ctx):
        return min(candidates, key=lambda k: self._last_access.get(k, 0))

    def reset(self):
        self._last_access.clear()
