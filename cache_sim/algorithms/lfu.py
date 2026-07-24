"""LFU（Least Frequently Used）驱逐策略。

基于访问计数，驱逐访问次数最少的项；计数相同时按 LRU tie-break
（最后访问时间最旧的先驱逐）。对象级缓存。
"""

from cache_sim.core.policy import EvictionPolicy
from cache_sim.algorithms.registry import register


@register("lfu")
class LFU(EvictionPolicy):
    """最不经常使用：驱逐 (频次, 最后访问时间) 最小的项。"""

    def __init__(self):
        super().__init__("LFU")
        self._freq = {}          # key -> 访问计数
        self._last_access = {}   # key -> 最后访问逻辑时间（tie-break）

    def on_hit(self, key, ctx):
        self._freq[key] = self._freq.get(key, 0) + 1
        self._last_access[key] = ctx.time

    def on_admit(self, key, ctx):
        self._freq[key] = 1
        self._last_access[key] = ctx.time

    def on_evict(self, key):
        self._freq.pop(key, None)
        self._last_access.pop(key, None)

    def select_victim(self, candidates, ctx):
        return min(candidates,
                   key=lambda k: (self._freq.get(k, 0), self._last_access.get(k, 0)))

    def reset(self):
        self._freq.clear()
        self._last_access.clear()
