"""General Model Rounding 驱逐策略。

论文《Randomized Competitive Algorithms for Generalized Caching》的舍入算法之一，
用于 General Model（任意 size 和 cost）。将分数算法的输出 x 舍入为整数缓存状态，
达到 O(log² k) 竞争比。面向对象级缓存。

核心思路：
  - 内部维护 FractionalCaching 获取分数变量 x。
  - γ = U + 3 = O(log k)，其中 U = ⌊log₂ k⌋（k 为缓存容量，以候选总大小近似）。
  - 计算 y_p = min{γ·x_p, 1}。
  - 二维分类：size class = ⌊log₂ size⌋，cost class = ⌊log₂ cost⌋。
  - y=1 的页面优先驱逐（按 size 降序），否则按 (size_class 降序, cost_class 降序, y 降序) 驱逐。
"""

import math
from typing import Dict

from cache_sim.core.policy import EvictionPolicy
from cache_sim.algorithms.fractional import FractionalCaching
from cache_sim.algorithms.registry import register


@register("general_rounding")
class GeneralModelRounding(EvictionPolicy):
    """General Model 舍入算法（γ=U+3，二维分类，O(log² k) 竞争比）。"""

    def __init__(self, seed=None):
        super().__init__("GeneralModelRounding")
        self._gamma = 3.0  # 运行时按 k 动态更新
        self._fractional = FractionalCaching(gamma=self._gamma)
        self._size: Dict = {}
        self._cost: Dict = {}

    def _update_gamma(self, candidates) -> None:
        k = max(1.0, sum(self._size.get(c, 1.0) for c in candidates))
        u = int(math.floor(math.log2(k))) if k > 0 else 0
        self._gamma = u + 3
        self._fractional.gamma = self._gamma

    def on_hit(self, key, ctx):
        self._fractional.on_hit(key, ctx)
        self._size[key] = ctx.size
        self._cost[key] = ctx.cost

    def on_admit(self, key, ctx):
        self._fractional.on_admit(key, ctx)
        self._size[key] = ctx.size
        self._cost[key] = ctx.cost

    def on_evict(self, key):
        self._fractional.on_evict(key)
        self._size.pop(key, None)
        self._cost.pop(key, None)

    @staticmethod
    def _class_of(v: float) -> int:
        if v <= 0:
            return 0
        return int(math.floor(math.log2(v)))

    def _y(self, key) -> float:
        return min(self._gamma * self._fractional.x_vars.get(key, 0.0), 1.0)

    def select_victim(self, candidates, ctx):
        self._update_gamma(candidates)
        self._fractional.update_x(candidates, ctx)
        # y=1 的页面优先驱逐，按 size 降序
        y_one = [k for k in candidates if self._y(k) >= 1.0]
        if y_one:
            return max(y_one, key=lambda k: self._size.get(k, 1.0))
        # 否则按 (size_class 降序, cost_class 降序, y 降序)
        return max(candidates, key=lambda k: (
            self._class_of(self._size.get(k, 1.0)),
            self._class_of(self._cost.get(k, 1.0)),
            self._y(k)))

    @property
    def gamma(self) -> float:
        return self._gamma

    def reset(self):
        self._gamma = 3.0
        self._fractional.gamma = self._gamma
        self._fractional.reset()
        self._size.clear()
        self._cost.clear()
