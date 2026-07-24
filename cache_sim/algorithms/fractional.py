"""Fractional Caching 驱逐策略（在线 primal-dual 框架）。

论文《Randomized Competitive Algorithms for Generalized Caching》第 3 节
"Computing a Competitive Fractional Solution" 的核心算法：分数算法。

维护分数变量 x(p) ∈ [0,1]：0 表示页面在缓存中，1 表示被完全驱逐。每次缺失时执行
primal-dual 更新——增大共享对偶变量 y(t,S) 直到分数意义上腾出足够空间（满足当前
knapsack-cover 约束），各候选 x(p) 同步按指数函数增长：

    x(p) = (1/k) · exp( (D_p − c_p) / c_p )

其中：
  - D_p 为页面 p 自上次被请求以来累计的对偶贡献 Σ ŵ_p^S · y(t,S)（跨多次缺失累加，
    重新被请求时归零）；
  - c_p 为获取成本；
  - k 为缓存容量（以候选总大小近似）；
  - ŵ_p^S = min{W(S) − k, w_p} 为截断权重，W(S) − k 即需腾出的空间（excess）。

算法要点（对应论文 Fractional Caching Algorithm）：
  - 新请求页面：x ← 0（仅在此后可被增大）。
  - 活动集 S 取“极小集” = {p | x(p) < 1/γ}（论文第 3 节 γ-精化：舍入仅需保证该集合
    的 knapsack-cover 约束被满足，无需满足所有约束）。x ≥ 1/γ 的页面已“离开 S”，其对偶
    冻结、x 不再增长（对应舍入中 y_p = min{γ·x_p, 1} = 1，已被视作完全驱逐）。
  - γ 由模型决定：Bit 模型 γ=3、General 模型 γ=U+3（U=⌊log₂k⌋）、Fault 模型 γ=15。
    各舍入算法（bit/fault/general rounding）在调用前将对应 γ 注入 self.gamma。
  - x(p)=0 的页面在对偶约束变紧（D_p = c_p）时跳变到 1/k（类 Randomized Marking）。
  - 1/k ≤ x(p) < 1 的页面按上述指数函数连续增长（上限 1，保证可腾出足够空间）。
  - 所有活动页面共享同一个对偶 y(t,S)：y 增大 dy 时，每个页面 D_p 同步增加 ŵ_p · dy。

离散实现说明：论文以连续形式给出算法并指出“可容易地离散实现”。由于 x(p) 是 D_p 的
确定性函数，而 D_p = D_p⁰ + ŵ_p · y（D_p⁰ 为本次缺失前的累计值），释放空间 freed(y)
关于共享对偶 y 单调不减。故对 y 在 [0, y_hi] 上二分求最小的 y* 使 freed(y*) ≥ needed，
再一次性提交各页面 D_p ← D_p⁰ + ŵ_p · y* 并重算 x。每次缺失仅更新一次（以 ctx.time 去重）。

- 作为独立算法时，驱逐 x 最大的项。
- 作为舍入算法（bit/fault/general rounding）的基础时，暴露 x 变量供其计算 y = min{γ·x, 1}。
"""

import math
from typing import Dict, List

from cache_sim.core.policy import EvictionPolicy
from cache_sim.algorithms.registry import register


@register("fractional")
class FractionalCaching(EvictionPolicy):
    """分数缓存（在线 primal-dual 框架，论文第 3 节）。"""

    def __init__(self, gamma: float = 3.0):
        super().__init__("Fractional")
        self.gamma = gamma
        self._x: Dict = {}        # key -> 分数 x ∈ [0,1]
        self._dual: Dict = {}     # key -> 累计对偶贡献 D_p
        self._size: Dict = {}     # key -> size
        self._cost: Dict = {}     # key -> cost
        self._plan: List = []     # 当前 miss 的驱逐计划（按 x 降序）
        self._plan_time = -1      # 当前计划对应的请求序号
        # 求解共享对偶 y* 的二分迭代次数与容差（freed 关于 y 单调，二分可靠收敛）
        self._bisect_iters = 50
        self._eps = 1e-9

    @property
    def x_vars(self) -> Dict:
        """暴露分数变量供舍入算法使用。"""
        return self._x

    def _k(self, candidates) -> float:
        """近似缓存容量：候选总大小（驱逐发生时缓存近似满）。

        论文中 k 为缓存容量（可视为容量与最小页面大小之比）；此处无显式容量入参，
        以候选总大小近似，与各舍入算法的 k 估计保持一致。
        """
        return max(1.0, sum(self._size.get(k, 1.0) for k in candidates))

    def on_hit(self, key, ctx):
        # 重新请求对应新变量：重置 x 与累计对偶 D_p 为 0
        self._x[key] = 0.0
        self._dual[key] = 0.0
        self._size[key] = ctx.size
        self._cost[key] = ctx.cost

    def on_admit(self, key, ctx):
        self._x[key] = 0.0
        self._dual[key] = 0.0
        self._size[key] = ctx.size
        self._cost[key] = ctx.cost

    def on_evict(self, key):
        self._x.pop(key, None)
        self._dual.pop(key, None)
        self._size.pop(key, None)
        self._cost.pop(key, None)

    @staticmethod
    def _x_of(d_p: float, cp: float, k: float) -> float:
        """由累计对偶 D_p 计算分数 x（论文 Step 3、4）。

        D_p < c_p 时 x = 0（尚未被任何对偶“激活”）；D_p = c_p 时跳变到 1/k；
        此后 x = (1/k)·exp((D_p − c_p)/c_p)，上限 1。c_p ≤ 0 视为可零成本驱逐，直接取 1。
        """
        if cp <= 0:
            return 1.0
        if d_p < cp:
            return 0.0
        # x 达 1 当 D_p ≥ c_p·(1 + ln k)
        return min(1.0, (1.0 / k) * math.exp((d_p - cp) / cp))

    def update_x(self, candidates, ctx) -> None:
        """执行 primal-dual 更新（论文第 3 节 Fractional Caching Algorithm）。

        每次缺失只更新一次（以 ctx.time 去重）：增大共享对偶 y(t,S) 直到分数意义上
        腾出 needed 空间；各活动候选 x(p) = (1/k)·exp((D_p−c_p)/c_p) 同步增长。

        极小集 S = {p | x(p) < 1/γ}（论文第 3 节 γ-精化）。x ≥ 1/γ 的页面已离开 S，
        对偶冻结、x 不再增长，但仍计入分数释放空间。γ 由模型决定（Bit=3 / General=U+3 /
        Fault=15），由各舍入算法注入 self.gamma。
        """
        if ctx.time == self._plan_time:
            return
        self._plan_time = ctx.time

        needed = max(0.0, ctx.needed)
        k = self._k(candidates)
        threshold = 1.0 / self.gamma  # 1/γ：极小集 S = {x < 1/γ}

        # 无需腾出空间：仅按当前 x 给出驱逐顺序
        if needed <= 0.0:
            self._plan = sorted(candidates, key=lambda c: self._x.get(c, 0.0), reverse=True)
            return

        # 活动集 S：x < 1/γ 的候选；x ≥ 1/γ 的页面已离开 S（对偶冻结，x 不再增长）
        active = [c for c in candidates if self._x.get(c, 0.0) < threshold]
        frozen = [c for c in candidates if self._x.get(c, 0.0) >= threshold]
        # 冻结页面释放的分数空间（常量，不随本次对偶 y 变化）
        frozen_freed = sum(self._size.get(c, 1.0) * self._x.get(c, 0.0) for c in frozen)

        if not active:
            # 无可增大的活动页面：依赖冻结页面的分数质量，按当前 x 给出驱逐顺序
            self._plan = sorted(candidates, key=lambda c: self._x.get(c, 0.0), reverse=True)
            return

        # 截断权重 ŵ_p = min{W(S) − k, w_p}；excess = needed（接纳新页需腾出的空间，
        # 对应 W(S) − k：加入新页后 {候选}∪{新页} 超出容量 k 的部分）。
        w = {c: self._size.get(c, 1.0) for c in active}
        cp = {c: self._cost.get(c, 1.0) for c in active}
        w_tilde = {c: min(needed, w[c]) for c in active}
        d0 = {c: self._dual.get(c, 0.0) for c in active}  # 本次缺失前的累计对偶 D_p⁰

        def freed_at(y: float) -> float:
            """共享对偶增至 y 时释放的分数空间：冻结页面 + 活动页面 Σ w_p · x_p。

            x 达 1 后该页贡献封顶为 w_p；因 w_p ≥ ŵ_p，Σ w_p·x_p ≥ Σ ŵ_p·x_p，
            故 freed ≥ needed 即保证实际可腾出 needed 空间。
            """
            total = frozen_freed
            for c in active:
                total += w[c] * self._x_of(d0[c] + w_tilde[c] * y, cp[c], k)
            return total

        # y 的上界：使每个活动页 x 达 1 的最大 y（x=1 当 D_p ≥ c_p·(1 + ln k)）。
        # 在 y_hi 处所有活动页均被完全驱逐，freed = frozen_freed + Σ_active w_p。
        y_hi = 0.0
        for c in active:
            if cp[c] <= 0:
                continue
            target = cp[c] * (1.0 + math.log(k))  # x 达 1 的 D_p 阈值
            gap = target - d0[c]
            if gap > 0.0 and w_tilde[c] > 0.0:
                y_hi = max(y_hi, gap / w_tilde[c])

        if freed_at(0.0) >= needed - self._eps or y_hi <= 0.0:
            # 当前分数解已含足够可驱逐质量，或无可增大空间：无需增大对偶
            y_star = 0.0
        else:
            # 二分求最小 y* 使 freed(y*) ≥ needed（freed 关于 y 单调不减，含跳变点）；
            # 若 freed(y_hi) 仍 < needed（冻结页面 x 偏低），二分收敛到 y_hi（活动页全驱逐），
            # 剩余空间由 select_victim 的整数驱逐补足。
            lo, hi = 0.0, y_hi
            for _ in range(self._bisect_iters):
                mid = 0.5 * (lo + hi)
                if freed_at(mid) >= needed:
                    hi = mid
                else:
                    lo = mid
            y_star = hi

        # 提交对偶增量并依指数函数重算 x（D_p ← D_p⁰ + ŵ_p · y*）
        for c in active:
            self._dual[c] = d0[c] + w_tilde[c] * y_star
            self._x[c] = self._x_of(self._dual[c], cp[c], k)

        # 驱逐计划：按 x 降序（x 越大越先被完全驱逐）
        self._plan = sorted(candidates, key=lambda c: self._x.get(c, 0.0), reverse=True)

    def select_victim(self, candidates, ctx):
        self.update_x(candidates, ctx)
        cand_set = set(candidates)
        for k in self._plan:
            if k in cand_set:
                return k
        # 兜底：取 x 最大者
        return max(candidates, key=lambda k: self._x.get(k, 0.0))

    def get_y(self, key) -> float:
        """y = min{gamma * x, 1}，供舍入算法使用。"""
        return min(self.gamma * self._x.get(key, 0.0), 1.0)

    def reset(self):
        self._x.clear()
        self._dual.clear()
        self._size.clear()
        self._cost.clear()
        self._plan = []
        self._plan_time = -1
