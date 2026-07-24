"""Randomized Marking 驱逐策略（Fiat et al.）。

经典 paging 的随机化标记算法，2H_k 竞争比。对象级缓存。

算法流程：
  - 每个缓存项维护标记状态（marked/unmarked）。
  - 命中或接纳时标记该项。
  - 需要驱逐时：若所有候选都已标记，清除全部标记（开始新阶段），
    再从（未标记的）候选中随机选一个驱逐。
"""

import random

from cache_sim.core.policy import EvictionPolicy
from cache_sim.algorithms.registry import register


@register("randomized_marking")
class RandomizedMarking(EvictionPolicy):
    """随机化标记算法（Fiat et al.，2H_k 竞争比）。"""

    def __init__(self, seed=None):
        super().__init__("RandomizedMarking")
        self._seed = seed
        self._rng = random.Random(seed)
        self._marked = {}  # key -> bool

    def on_hit(self, key, ctx):
        self._marked[key] = True

    def on_admit(self, key, ctx):
        # 新加入的页面标记（属于当前阶段）
        self._marked[key] = True

    def on_evict(self, key):
        self._marked.pop(key, None)

    def select_victim(self, candidates, ctx):
        # 若所有候选都已标记，清除全部标记开始新阶段
        if candidates and all(self._marked.get(k, False) for k in candidates):
            for k in candidates:
                self._marked[k] = False
        unmarked = [k for k in candidates if not self._marked.get(k, False)]
        if unmarked:
            return self._rng.choice(unmarked)
        # 兜底（理论上不会到达）
        return self._rng.choice(candidates)

    def reset(self):
        self._marked.clear()
        self._rng = random.Random(self._seed)
