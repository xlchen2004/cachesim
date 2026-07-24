"""FIFO（First In First Out）驱逐策略。

基于插入顺序，驱逐最先加入缓存的项。命中不更新插入顺序。对象级缓存。
"""

from cache_sim.core.policy import EvictionPolicy
from cache_sim.algorithms.registry import register


@register("fifo")
class FIFO(EvictionPolicy):
    """先进先出：驱逐插入时间最小的项。"""

    def __init__(self):
        super().__init__("FIFO")
        self._insert_time = {}  # key -> 接纳时的逻辑时间

    def on_hit(self, key, ctx):
        pass  # FIFO 命中不更新插入顺序

    def on_admit(self, key, ctx):
        self._insert_time[key] = ctx.time

    def on_evict(self, key):
        self._insert_time.pop(key, None)

    def select_victim(self, candidates, ctx):
        return min(candidates, key=lambda k: self._insert_time.get(k, 0))

    def reset(self):
        self._insert_time.clear()
