"""Fault Model Rounding 驱逐策略。

论文《Randomized Competitive Algorithms for Generalized Caching》的舍入算法之一，
用于 Fault Model（cost = 1，任意 size）。将分数算法的输出 x 舍入为整数缓存状态，
达到 O(log k) 竞争比。面向对象级缓存。

核心思路：
  - 内部维护 FractionalCaching 获取分数变量 x。
  - 计算 y_p = min{γ·x_p, 1}（γ=15）。
  - y=1 的页面优先驱逐（按 size 降序），否则按 y 降序驱逐。

注：原仓库实现的 Good Grouping 与势函数 Φ 仅用于摊还分析，不参与驱逐决策，
本重新适配版本略去以保持简洁，驱逐启发式与原实现一致。
"""

from typing import Dict

from cache_sim.core.policy import EvictionPolicy
from cache_sim.algorithms.fractional import FractionalCaching
from cache_sim.algorithms.registry import register


@register("fault_rounding")
class FaultModelRounding(EvictionPolicy):
    """Fault Model 舍入算法（γ=15，O(log k) 竞争比）。"""

    PHI_COEFF_Y = 13
    PHI_COEFF_GROUP = 11
    GROUP_MAX_WEIGHT = 12
    GROUP_MIN_WEIGHT = 3
    GROUP_TARGET = 6

    def __init__(self, gamma: float = 15.0, seed=None):
        super().__init__("FaultModelRounding")
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

    def _y(self, key) -> float:
        return min(self.gamma * self._fractional.x_vars.get(key, 0.0), 1.0)

    def select_victim(self, candidates, ctx):
        self._fractional.update_x(candidates, ctx)
        # y=1 的页面优先驱逐，按 size 降序
        y_one = [k for k in candidates if self._y(k) >= 1.0]
        if y_one:
            return max(y_one, key=lambda k: self._size.get(k, 1.0))
        # 否则按 y 降序
        return max(candidates, key=lambda k: self._y(k))

    def reset(self):
        self._fractional.reset()
        self._size.clear()
