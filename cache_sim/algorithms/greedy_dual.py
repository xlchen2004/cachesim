"""Greedy-Dual 驱逐策略（Cao-Irani）。

广义缓存 baseline，k+1 竞争比，面向对象级缓存（变长对象）。
通过 H 值（优先级）与 age 机制实现：驱逐 H 值最小的项，
并将剩余项的 H 值减去被驱逐项的最小 H 值。支持任意 size 和 cost。

算法流程：
  - 项接纳时：H = cost（获取成本）。
  - 命中时：不更新 H（标准 GD 版本）。
  - 驱逐时：选 H 最小的项驱逐，剩余候选 H 减去该项 H（age 机制）。
"""

from cache_sim.core.policy import EvictionPolicy
from cache_sim.algorithms.registry import register


@register("greedy_dual")
class GreedyDual(EvictionPolicy):
    """Greedy-Dual（Cao-Irani），k+1 竞争比。"""

    def __init__(self):
        super().__init__("GreedyDual")
        self._h = {}  # key -> H 值（优先级）

    def on_hit(self, key, ctx):
        pass  # 标准 GD 命中不更新 H

    def on_admit(self, key, ctx):
        self._h[key] = ctx.cost

    def on_evict(self, key):
        self._h.pop(key, None)

    def select_victim(self, candidates, ctx):
        cand_set = set(candidates)
        victim = min(candidates, key=lambda k: self._h.get(k, 0.0))
        min_h = self._h.get(victim, 0.0)
        # age 机制：剩余候选的 H 减去被驱逐项的最小 H
        if min_h > 0:
            for k, h in list(self._h.items()):
                if k != victim and k in cand_set:
                    self._h[k] = h - min_h
        return victim

    def reset(self):
        self._h.clear()
