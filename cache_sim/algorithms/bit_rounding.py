"""Bit Model Rounding 驱逐策略。

论文《Randomized Competitive Algorithms for Generalized Caching》的舍入算法之一，
用于 Bit Model（cost = size）。将分数算法的输出 x 舍入为整数缓存状态，
达到 O(log k) 竞争比。面向对象级缓存。

核心思路：
  - 内部维护 FractionalCaching 获取分数变量 x。
  - 计算 y_p = min{γ·x_p, 1}（γ=3）。
  - 按 ⌊log₂ size⌋ 将页面划分到 size class。
  - y=1 的页面优先驱逐（按 size 降序），否则按 (size_class 降序, y 降序) 驱逐。
"""

import math
from typing import Dict

from cache_sim.core.policy import EvictionPolicy
from cache_sim.algorithms.fractional import FractionalCaching
from cache_sim.algorithms.registry import register


@register("bit_rounding")
class BitModelRounding(EvictionPolicy):
    """Bit Model 舍入算法（γ=3，O(log k) 竞争比）。"""

    def __init__(self, gamma: float = 3.0, seed=None):
        super().__init__("BitModelRounding")
        self.gamma = gamma
        self._fractional = FractionalCaching(gamma=gamma)
        self._size: Dict = {}

    def on_hit(self, key, ctx):
        self._fractional.on_hit(key, ctx)
        self._size[key] = ctx.size

    def on_admit(self, key, ctx):
        self._fractional.on_admit(key, ctx)
        self._size[key] = ctx.size

    def on_evict(self, key):
        self._fractional.on_evict(key)
        self._size.pop(key, None)

    def _size_class(self, size: float) -> int:
        if size <= 0:
            return 0
        return int(math.floor(math.log2(size)))

    def _y(self, key) -> float:
        return min(self.gamma * self._fractional.x_vars.get(key, 0.0), 1.0)

    def select_victim(self, candidates, ctx):
        # 先刷新 x（primal-dual 更新，每次缺失只更新一次）
        self._fractional.update_x(candidates, ctx)
        # y=1 的页面优先驱逐，按 size 降序
        y_one = [k for k in candidates if self._y(k) >= 1.0]
        if y_one:
            return max(y_one, key=lambda k: self._size.get(k, 1.0))
        # 否则按 (size_class 降序, y 降序)
        return max(candidates, key=lambda k: (
            self._size_class(self._size.get(k, 1.0)), self._y(k)))

    def reset(self):
        self._fractional.reset()
        self._size.clear()
