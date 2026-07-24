"""Random 驱逐策略。

随机选择缓存中的项驱逐。支持随机种子以保证可复现。对象级缓存。
"""

import random

from cache_sim.core.policy import EvictionPolicy
from cache_sim.algorithms.registry import register


@register("random")
class RandomEvict(EvictionPolicy):
    """随机驱逐：从候选中随机选一个。"""

    def __init__(self, seed=None):
        super().__init__("Random")
        self._seed = seed
        self._rng = random.Random(seed)

    def on_hit(self, key, ctx):
        pass

    def on_admit(self, key, ctx):
        pass

    def on_evict(self, key):
        pass

    def select_victim(self, candidates, ctx):
        return self._rng.choice(candidates)

    def reset(self):
        self._rng = random.Random(self._seed)
