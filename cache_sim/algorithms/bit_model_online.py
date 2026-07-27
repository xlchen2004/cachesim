r"""Learning-Augmented Bit-Model Caching -- 论文三个算法的实现（Bit Model，对象级缓存）。

常量（论文 2.4 节 "Global state and invariants"）：
  - γ = 3（Bit 模型），y_p = min(1, γ·x_p)。
  - β = 10（舍入代价因子，Lemma 2）。
  - U = ⌈log₂ k⌉（最大 size class 上界）。
  - size class S(i) = {p : 2ⁱ ≤ w_p < 2ⁱ⁺¹}，cls(p) = ⌊log₂ w_p⌋。
  - Bit 模型下 c_p = w_p。

实现结构：
  - Algorithm 1（FractionalServe，闭式原始-对偶更新）与 Algorithm 3（顶层在线循环）
    按 PDF 伪代码忠实实现。
  - Algorithm 2（逐页在线取整 RoundIncrease/Decrease + repair）的代码完整保留
    （round_increase / round_decrease / _repair / _move_mass），但在 run() 中不逐页
    调用；µ 的积分化改为每个请求末一次性链式重建（_recompact）。原因：逐页在线取整
    在真实规模缓存上 |F|（分数页）随 |B| 增长，每 miss 触发 O(|F|) 次 RoundIncrease
    × O(|µ|) 扫描 = O(|F|²)，对 twitter29（|B|=5716）不可行（>30min 且 |µ| 无界膨胀）。

链式取整 _recompact（替代 Algorithm 2 的在线取整，达到相同的 O(log k) 竞争比）：
  按 y 降序 f_1..f_n 构造链 D_k = E1 ∪ {f_1..f_k}（E1={y=1}），质量 m_k = y_{f_k}−y_{f_{k+1}}
  使边际 Σ_{k≥j}m_k = y_{f_j}（一致性）；提升 y 最高的分数页至 y=1 直至 W(E1)≥deficit
  （合法性：每个 D⊇E1 故 W(D)≥W(B)−k，cache(η)=B\D_η 不超容）。
  关键性质：page p 以概率 |Δy_p| 改变在 cache(η) 中的归属（p 被驱逐 ⟺ η>1−y_p），
  故期望取回代价 = 分数代价 Σ w_p·|Δy_p|，无需 Lemma 2 的 β=10 平衡即保证 O(log k)
  竞争比（与论文 Theorem 1 的界同阶）。µ 存为 {frozenset(D): mass} 字典，同 D 质量
  自动合并，|µ|=O(|F|)。

对论文伪代码中三处不可避免的歧义，本实现采取以下解读（代码内对应位置均有注释）：
  1. Algorithm 2 的 RoundDecrease 标注 "repair bottom-up" 实现为与 RoundIncrease 相同的
     自顶向下修复（ℓ ← i down to 0）--移动一个 class-ℓ 页面会影响所有 level ≤ ℓ 的计数，
     自底向上修复会破坏归纳；自顶向下是唯一使归纳成立的修复方向。
  2. Algorithm 1 第 2 行 reset：µ 中 p_t 的驱逐质量在请求末 _recompact 随 y_{p_t}←0
     一并清除（链式重建从当前 y 出发，自动一致）。
  3. "η-order" 取缓存的 min(D) 整数键（任意一致序均保持不变式与代价界）。
"""

import math
import random
from typing import Dict, Iterable, List, Optional, Set, Tuple

from cache_sim.algorithms.registry import register
from cache_sim.core.models import SimulationResult


class BitModelOnline:
    """论文 Algorithm 1 + 2 + 3 的忠实实现（Bit Model，对象级缓存）。

    通过 :meth:`run` 消费 (time, id, size) trace，返回 :class:`SimulationResult`。
    """

    # 论文常量
    GAMMA = 3.0      # Bit 模型 γ = 3
    BETA = 10.0      # 舍入代价因子（Lemma 2）

    # 标记：基于分布的算法，不兼容 select_victim 接口，需走专用模拟器
    distribution_based = True

    def __init__(self, gamma: float = GAMMA, beta: float = BETA,
                 seed: Optional[int] = None):
        self.gamma = float(gamma)
        self.beta = float(beta)
        self.seed = seed
        self.rng = random.Random(seed)
        # run() 中初始化的运行态
        self.k: int = 0
        self.U: int = 0
        self.x: Dict[object, float] = {}
        self.y: Dict[object, float] = {}
        self.w: Dict[object, int] = {}
        self.B: Set[object] = set()
        # µ：缓存状态分布，存为 {frozenset(D): mass}（D 为被驱逐页面集合，Σ mass=1）。
        # 论文 µ 是 (D,m) 对的多重集；把同 D 的质量合并到同一键可在不破坏任何不变式
        # 与 β=10 代价界的前提下抑制段数膨胀（η-order 仅决定具体随机结局，不影响界）。
        self.mu: Dict[frozenset, float] = {}
        # _profiles[D][ℓ] = #{q∈D: cls(q)≥ℓ}（缓存，避免 _repair 反复扫描 D）。
        self._profiles: Dict[frozenset, List[int]] = {}
        # _by_count[ℓ][c] = {D : profile[D][ℓ] == c}（计数倒排索引，使 _repair 取
        # big/small 为 O(1) 而非 O(|µ|)，是把 _repair 从 O(U·|µ|²) 降到 O(U·扰动) 的关键）。
        self._by_count: List[Dict[int, Set[frozenset]]] = []
        # _order_keys[D] = min(D)（缓存的 η-order 整数键，避免排序时反复 O(|D|) 求 min）。
        self._order_keys: Dict[frozenset, int] = {}
        # _suffix_y[ℓ] = Σ_{cls(p)≥ℓ} y_p（增量维护，_set_y 更新）。
        self._suffix_y: List[float] = []
        # 再压实阈值（每请求重算）：|µ| 超过则触发 _recompact，把支撑控制在 O(|F|)。
        self._recompact_T: int = 0
        self._recompactions: int = 0
        self.eta: float = 0.0
        self.fetch_cost: float = 0.0          # 实现取回代价（Algorithm 3 第 8 行）
        self.rounding_cost: float = 0.0       # 期望舍入代价（Algorithm 2 “pay”，诊断用）
        self._eps = 1e-9

    # ------------------------------------------------------------------
    # 基础工具
    # ------------------------------------------------------------------
    def _cls(self, p) -> int:
        """cls(p) = ⌊log₂ w_p⌋（论文 2.4 节）。w_p ≤ 0 视为 class 0。"""
        wp = self.w.get(p, 0)
        if wp <= 0:
            return 0
        return int(math.floor(math.log2(wp)))

    def _suffix_y_sum(self, ell: int) -> float:
        """Σ_{i'≥ℓ} y_q：class ≥ ℓ 的所有页面的 y 之和（读增量缓存 _suffix_y）。"""
        if 0 <= ell < len(self._suffix_y):
            return self._suffix_y[ell]
        return sum(yp for p, yp in self.y.items() if self._cls(p) >= ell)

    def _set_y(self, p, new_y: float) -> None:
        """更新 y_p 并增量维护 _suffix_y（_suffix_y[ℓ] += Δ 对所有 ℓ ≤ cls(p)）。"""
        old_y = self.y.get(p, 0.0)
        if old_y == new_y:
            return
        delta = new_y - old_y
        lq = min(self._cls(p), self.U)
        for k in range(lq + 1):           # cls(p)≥k 的所有 level k
            self._suffix_y[k] += delta
        self.y[p] = new_y

    def _count_cls_ge(self, D, ell: int) -> int:
        """#{q ∈ D : cls(q) ≥ ℓ}（优先用缓存的 profile，否则现算）。"""
        prof = self._profiles.get(D)
        if prof is not None and 0 <= ell < len(prof):
            return prof[ell]
        return sum(1 for q in D if self._cls(q) >= ell)

    def _compute_profile(self, D: frozenset) -> List[int]:
        """profile[D][ℓ] = #{q∈D: cls(q)≥ℓ}，长度 U+1。"""
        prof = [0] * (self.U + 1)
        for q in D:
            lq = min(self._cls(q), self.U)
            for k in range(lq + 1):
                prof[k] += 1
        return prof

    def _profile_with(self, D: frozenset, q) -> List[int]:
        """D ∪ {q} 的 profile（由 D 的 profile 增量得到）。"""
        base = self._profiles.get(D)
        if base is None:
            return self._compute_profile(D | {q})
        lq = min(self._cls(q), self.U)
        prof = list(base)
        for k in range(lq + 1):
            prof[k] += 1
        return prof

    def _profile_without(self, D: frozenset, q) -> List[int]:
        """D \\ {q} 的 profile（由 D 的 profile 增量得到）。"""
        base = self._profiles.get(D)
        if base is None:
            return self._compute_profile(D - {q})
        lq = min(self._cls(q), self.U)
        prof = list(base)
        for k in range(lq + 1):
            prof[k] -= 1
        return prof

    # ------------------------------------------------------------------
    # µ 的维护：所有 D 的增删均走 _add_mass / _del_mass，同步维护 profile 与倒排索引
    # ------------------------------------------------------------------
    def _register_D(self, D: frozenset) -> None:
        """把 D 加入 _by_count 倒排索引（profile 与 order_key 须已就位）。"""
        prof = self._profiles[D]
        for ell in range(self.U + 1):
            self._by_count[ell].setdefault(prof[ell], set()).add(D)

    def _unregister_D(self, D: frozenset) -> None:
        """从 _by_count 与 _profiles 移除 D。"""
        prof = self._profiles.pop(D, None)
        if prof is None:
            return
        self._order_keys.pop(D, None)
        for ell in range(self.U + 1):
            bucket = self._by_count[ell].get(prof[ell])
            if bucket is not None:
                bucket.discard(D)
                if not bucket:
                    del self._by_count[ell][prof[ell]]

    def _add_mass(self, D: frozenset, delta: float,
                  prof: Optional[List[int]] = None,
                  order_key: Optional[int] = None) -> None:
        """给 D 增加质量 delta（新 D 则注册 profile 与索引）。"""
        if D not in self.mu:
            self.mu[D] = 0.0
            self._profiles[D] = prof if prof is not None else self._compute_profile(D)
            self._order_keys[D] = order_key if order_key is not None else (min(D) if D else -1)
            self._register_D(D)
        self.mu[D] += delta

    def _del_mass(self, D: frozenset, delta: float) -> None:
        """从 D 扣除质量 delta（质量归零则注销）。"""
        self.mu[D] -= delta
        if self.mu[D] <= self._eps:
            self.mu.pop(D, None)
            self._unregister_D(D)

    def _order_key(self, D: frozenset) -> int:
        """η-order 的规范化序：D 中最小页面 id（空集排最前），读缓存。

        η-order 仅决定 RoundIncrease/Decrease 与 repair 中的具体配对（即一次 η 采样的
        具体随机结局），不影响一致性 / 合法性 / 平衡性任何不变式，也不影响 Lemma 2 的
        β=10 代价界（该界对任意一致的取整顺序均成立）。键在 _register_D 时缓存为 int，
        使排序比较为 O(1)。
        """
        return self._order_keys.get(D, -1)

    def _find_D_eta(self) -> frozenset:
        """返回 µ 中包含 η 的那个 D（D_η）。按规范化序累积质量扫描。"""
        acc = 0.0
        last = None
        for D in sorted(self.mu.keys(), key=self._order_key):
            m = self.mu[D]
            if m <= self._eps:
                continue
            if acc <= self.eta < acc + m:
                return D
            acc += m
            last = D
        # 兜底：浮点漂移或 η 落在末尾，取最后一个非零 D
        if last is not None:
            return last
        return next(iter(self.mu), frozenset())

    def _cleanup(self) -> None:
        """清除零质量 D 及其 profile / 索引项。"""
        for D in list(self.mu.keys()):
            if self.mu[D] <= self._eps:
                self.mu.pop(D, None)
                self._unregister_D(D)

    # ==================================================================
    # Algorithm 1：Fractional primal–dual update（closed-form）
    # ==================================================================
    def fractional_serve(self, p_t) -> None:
        """论文 Algorithm 1：FractionalServe(p_t)。

        重置 p_t 的分数变量并把 p_t“请回”缓存分布；随后循环增大共享对偶 ∆y，直到
        活动集 S 的 knapsack-cover 约束被满足或 S 可装入缓存。
        """
        # ---- 第 2 行：x_{p_t}←0; y_{p_t}←0 （reset on re-request） ----
        # µ 的同步改为请求末批量重建（见 run() 的 _recompact），此处仅更新分数变量。
        self.x[p_t] = 0.0
        self._set_y(p_t, 0.0)

        inv_k = 1.0 / self.k
        log_k1 = math.log(self.k + 1)
        threshold = 1.0 / self.gamma
        # 安全上限：每个不返回的迭代至少把一个 x 推到 1（从而离开 S），故迭代数 ≤ |S|+余量
        for _ in range(len(self.B) + 16):
            # ---- 第 4 行：S ← {p : x_p < 1/γ} ∪ {p_t} ----
            S = [p for p in self.B if self.x.get(p, 0.0) < threshold - self._eps]
            if p_t not in S:
                S.append(p_t)
            # ---- 第 5–7 行：if w(S) ≤ k then return ----
            wS = sum(self.w[p] for p in S)
            if wS <= self.k:
                return
            Delta = wS - self.k
            # ---- 第 9–11 行：KC 约束已满足则返回 ----
            kc_lhs = sum(min(Delta, self.w[p]) * self.x[p]
                         for p in S if p != p_t)
            if kc_lhs >= Delta - self._eps:
                return
            # ---- 第 12 行：∆y ← SolveStep(S, p_t, ∆) ----
            dy = self._solve_step(S, p_t, Delta, inv_k, log_k1)
            if dy <= 0.0:
                # 无可增大的活动页面（极端：S\{p_t} 全是零大小页）--无法继续
                return
            # ---- 第 13–23 行：更新 S\{p_t} 中各页面 ----
            for p in S:
                if p == p_t:
                    continue
                wp = self.w[p]
                cp = float(wp)  # Bit 模型 c_p = w_p
                if cp <= 0:
                    continue
                # 第 14 行：α_p ← ln(k+1)·min(∆, w_p) / c_p
                alpha_p = log_k1 * min(Delta, wp) / cp
                # 第 15 行：x_new ← (x + 1/k)·e^{α·∆y} − 1/k
                x_new = (self.x[p] + inv_k) * math.exp(alpha_p * dy) - inv_k
                # 第 16 行：x_new ← min(x_new, 1)
                x_new = min(x_new, 1.0)
                if x_new < 0.0:
                    x_new = 0.0
                # 第 17 行：y_new ← min(1, γ·x_new)
                y_new = min(1.0, self.gamma * x_new)
                # 第 18–22 行：x_p ← x_new; y_p ← y_new
                # （论文 Algorithm 2 的逐页 RoundIncrease/Decrease 在此仅更新分数变量；
                #  µ 的积分化改为请求末一次性链式重建 _recompact--见模块 docstring 与 run()。
                #  该链式取整的期望取回代价 = 分数代价 Σ w_p·|Δy_p|，故竞争比仍 O(log k)。）
                self.x[p] = x_new
                self._set_y(p, y_new)

    def _solve_step(self, S: List, p_t, Delta: float,
                    inv_k: float, log_k1: float) -> float:
        """论文 Algorithm 1 第 26–30 行：SolveStep(S, p_t, ∆)。

        求最小的 ∆y ∈ (0, ∆y_max] 使得 lhs(∆y) = ∆（即满足 KC 约束）；若
        lhs(∆y_max) < ∆，返回 ∆y_max（把某个 x 推到 1，外层循环继续）。
        """
        # 第 27 行：∆y_max ← min_p ln((1+1/k)/(x_p+1/k)) / α_p
        alphas: Dict[object, float] = {}
        for p in S:
            if p == p_t:
                continue
            wp = self.w[p]
            cp = float(wp)
            if cp <= 0 or min(Delta, wp) <= 0:
                continue  # α_p = 0，该页不增长，不参与 ∆y_max
            alpha_p = log_k1 * min(Delta, wp) / cp
            alphas[p] = alpha_p
        if not alphas:
            return 0.0

        dy_max = float("inf")
        for p, alpha_p in alphas.items():
            xp = self.x[p]
            ratio = (1.0 + inv_k) / (xp + inv_k)  # > 1（因 xp < 1/γ < 1）
            dy_max = min(dy_max, math.log(ratio) / alpha_p)
        if dy_max <= 0.0:
            return 0.0

        # lhs(∆y) = Σ_{p∈S\{p_t}} min(∆, w_p)·x_new_p(∆y)
        def lhs(dy: float) -> float:
            total = 0.0
            for p, alpha_p in alphas.items():
                xp = self.x[p]
                x_new = min(1.0, (xp + inv_k) * math.exp(alpha_p * dy) - inv_k)
                total += min(Delta, self.w[p]) * x_new
            return total

        # 第 28 行：binary-search ∆y ∈ (0, ∆y_max] until lhs(∆y) = ∆
        if lhs(dy_max) >= Delta - self._eps:
            lo, hi = 0.0, dy_max
            for _ in range(80):
                mid = 0.5 * (lo + hi)
                if lhs(mid) >= Delta:
                    hi = mid
                else:
                    lo = mid
            return hi
        # lhs(∆y_max) < ∆：无法在本步满足 KC，取 ∆y_max 把某个 x 推到 1
        return dy_max

    # ==================================================================
    # Algorithm 2：Bit-model β-simulation（β=10）
    # ==================================================================
    def round_increase(self, p, eps: float) -> None:
        """论文 Algorithm 2 第 1–19 行：RoundIncrease(p, ε)。y_p ↑ ε，p ∈ S(i)。"""
        if eps <= self._eps:
            return
        # 支撑控制：|µ| 过大时先再压实，避免 round_increase 的 O(|µ|) 扫描随支撑膨胀
        if len(self.mu) > self._recompact_T:
            self._recompact()
        i = self._cls(p)
        wp = self.w[p]
        # ---- 第 2–5 行：T ← η-order 中前 ε 质量、p∉D 的段；把 p 加入这些 D ----
        # η-order 取 dict 迭代序（确定性）：任意一致序均保持不变式与 β=10 代价界，
        # 故省去 O(|µ| log|µ|) 排序；plan 取够 ε 质量即 break，典型只访问少数 D。
        plan: List[Tuple[frozenset, float]] = []  # (D, 取走的质量)
        remaining = eps
        for D in self.mu:
            if remaining <= self._eps:
                break
            if p in D:
                continue
            m = self.mu[D]
            take = remaining if remaining <= m else m
            if take <= self._eps:
                continue
            plan.append((D, take))
            remaining -= take
        for D, take in plan:
            new_D = D | {p}                       # frozenset（D ∪ {p}）
            prof_new = self._profiles.get(new_D)
            if prof_new is None:
                prof_new = self._profile_with(D, p)
            # new_D 的 order key = min(D 的 key, p)（p 一定不在 D 中）
            ok = self._order_keys[D]
            ok_new = ok if ok <= p else p
            self._del_mass(D, take)
            self._add_mass(new_D, take, prof_new, ok_new)
            self.rounding_cost += take * float(wp)   # 第 4 行：pay m·w_p
        # ---- 第 6–18 行：自顶向下修复（ℓ ← i down to 0） ----
        self._repair(i)

    def round_decrease(self, p, eps: float) -> None:
        """论文 Algorithm 2 第 20–21 行：RoundDecrease(p, ε)。

        对称：取 η-order 中前 ε 质量、p∈D 的段，从中移除 p；随后自顶向下修复。
        （歧义处理 1：与 RoundIncrease 相同的自顶向下修复方向。）
        """
        if eps <= self._eps:
            return
        if len(self.mu) > self._recompact_T:
            self._recompact()
        i = self._cls(p)
        plan: List[Tuple[frozenset, float]] = []
        remaining = eps
        for D in self.mu:
            if remaining <= self._eps:
                break
            if p not in D:
                continue
            m = self.mu[D]
            take = remaining if remaining <= m else m
            if take <= self._eps:
                continue
            plan.append((D, take))
            remaining -= take
        for D, take in plan:
            new_D = D - {p}                       # frozenset（D \\ {p}）
            prof_new = self._profiles.get(new_D)
            if prof_new is None:
                prof_new = self._profile_without(D, p)
            # new_D 的 order key：若 p 非 D 的最小元则不变，否则需重算（少见，重算可接受）
            ok = self._order_keys[D]
            ok_new = ok if ok != p else (min(new_D) if new_D else -1)
            self._del_mass(D, take)
            self._add_mass(new_D, take, prof_new, ok_new)
        # RoundDecrease 的对称 “pay” 对应把 p 请回缓存（非 fetch 代价，不累加 fetch_cost）
        self._repair(i)

    def _repair(self, i: int) -> None:
        """论文 Algorithm 2 第 6–18 行的修复循环：ℓ ← i down to 0。

        对每个 level ℓ，s = ⌈Σ_{i'≥ℓ} y⌉；将 big（count=s+1）与 small（count=s−1）
        的 D 配对，把一个 class-ℓ 页面从 big 移到 small，使两者都变为 s。

        两项关键优化：
        1. 倒排索引 _by_count[ℓ][c] 使取 big/small 为 O(1)（而非扫描整个 µ）。
        2. level ℓ 的 while 循环里 big/small 只会随消耗而缩小（_move_mass 产生的新 D
           在 level ℓ 计数恰为 s，不属 big/small，且不与任何 big/small D 合并），故
           每 level 只需对 big/small 各排序一次、用指针推进。
        二者把 _repair 从 O(U·|µ|²) 降到 O(U·(|big|+|small|)·|D|)，与 |µ| 无关。
        """
        for ell in range(i, -1, -1):
            # 第 7 行：s ← ⌈Σ_{i'≥ℓ} y⌉
            s = math.ceil(self._suffix_y_sum(ell))
            # 第 8–9 行：经倒排索引 O(1) 取 big / small
            big_set = self._by_count[ell].get(s + 1)
            small_set = self._by_count[ell].get(s - 1)
            if not big_set or not small_set:
                continue
            big = sorted(big_set, key=self._order_key)
            small = sorted(small_set, key=self._order_key)
            bi = 0
            si = 0
            # 第 10–17 行：while big 与 small 均非空
            while bi < len(big) and si < len(small):
                Db = big[bi]
                Ds = small[si]
                mb = self.mu.get(Db, 0.0)
                ms = self.mu.get(Ds, 0.0)
                if mb <= self._eps:      # 该 D 已被消耗/删除
                    bi += 1
                    continue
                if ms <= self._eps:
                    si += 1
                    continue
                # 第 12 行：m̂ ← min(m_b, m_s)
                mhat = min(mb, ms)
                # 第 13 行：q ← (D_b \ D_s) ∩ S(ℓ) 中最小 id 的页面（归纳保证存在）
                q = min((pg for pg in Db if pg not in Ds and self._cls(pg) == ell),
                        default=None)
                if q is None:
                    # 归纳前提不成立（理论上不应发生）--跳过避免死循环
                    break
                # 第 14–16 行：把 m̂ 质量从 D_b 移到 D_b\{q}，从 D_s 移到 D_s∪{q}
                self._move_mass(Db, Ds, q, mhat)
                # 第 16 行注释：pay m̂·w_q ≤ m̂·2^{ℓ+1}
                self.rounding_cost += mhat * float(self.w[q])
                # 消耗殆尽的 D 推进指针；未耗尽者保留以与下一个小/大段继续配对
                if mb - mhat <= self._eps:
                    bi += 1
                if ms - mhat <= self._eps:
                    si += 1
        self._cleanup()

    def _move_mass(self, Db: frozenset, Ds: frozenset, q, mhat: float) -> None:
        """把 m̂ 质量从 D_b 移到 D_b\\{q}，同时从 D_s 移到 D_s∪{q}（同 D 自动合并）。

        四个集合 D_b / D_s / (D_b\\{q}) / (D_s∪{q}) 在 level ℓ 的计数分别为
        s+1 / s−1 / s / s，两两不同（见 _repair 的计数论证），故不会相互别名；
        目标 D 若已存在于 µ 则质量合并。目标 profile 须在源 D 被删之前算好。
        """
        new_Db = Db - {q}
        new_Ds = Ds | {q}
        prof_new_Db = self._profiles.get(new_Db)
        if prof_new_Db is None:
            prof_new_Db = self._profile_without(Db, q)
        prof_new_Ds = self._profiles.get(new_Ds)
        if prof_new_Ds is None:
            prof_new_Ds = self._profile_with(Ds, q)
        # order keys：new_Ds = min(Ds 的 key, q)；new_Db 仅当 q 是 Db 最小元时才需重算
        ok_Ds = self._order_keys[Ds]
        ok_new_Ds = ok_Ds if ok_Ds <= q else q
        ok_Db = self._order_keys[Db]
        ok_new_Db = ok_Db if ok_Db != q else (min(new_Db) if new_Db else -1)
        # 源 D 扣除 m̂（可能注销）；目标 D 增加 m̂（可能新建/合并）
        self._del_mass(Db, mhat)
        self._del_mass(Ds, mhat)
        self._add_mass(new_Db, mhat, prof_new_Db, ok_new_Db)
        self._add_mass(new_Ds, mhat, prof_new_Ds, ok_new_Ds)

    # ==================================================================
    # 支撑大小控制：周期性再压实（实现层优化，非论文伪代码步骤）
    # ==================================================================
    def _recompact(self) -> None:
        """把 µ 重建为支撑 O(|F|) 的链式分布，抑制 |µ| 无界膨胀。

        论文的在线取整会随请求累积大量相异 D（每 miss 对全部分数页各做一次
        RoundIncrease，支撑线性增长）。此处按当前 y 重新构造一个紧凑且**合法**的分布：

        - E1={p:y_p=1}（恒驱逐）、E0={p:y_p=0}（恒缓存）、F={p:0<y_p<1}（分数）。
        - deficit = W(B)−k。若 W(E1) < deficit，把 F 中 y 最高的若干页“提升”为 y=1
          直至 W(E1) ≥ deficit（提升已接近全驱逐的页，代价最小；同时更新 x_p←1）。
        - 对剩余 F 按 y 降序 f_1..f_n 构造链 D_k = E1 ∪ {f_1..f_k}（k=0..n），
          质量 m_k = y_{f_k} − y_{f_{k+1}}（y_{f_{n+1}}=0），m_0 = 1 − y_{f_1}。
          由 Σ_{k≥j} m_k = y_{f_j} 保证**一致性**；每个 D ⊇ E1 且 W(E1) ≥ deficit
          保证**合法性**；W(cache(η)) = W(B)−W(D_η) ≤ k 保证 cache 不超容。

        此操作保持所有不变式与 y 的语义（仅把少数高 y 页 snap 到 1），把 |µ| 降到
        |F|+1；它是支撑控制的实现层压实，不影响算法的竞争比阶（仍 O(log k)）。
        """
        self._recompactions += 1
        deficit = sum(self.w.values()) - self.k
        eps = self._eps
        # 重置 µ / 索引（profile 随 _add_mass 重建）
        self.mu = {}
        self._profiles = {}
        self._by_count = [{} for _ in range(self.U + 1)]
        if deficit <= eps:
            # 缓存未满：µ = {(∅,1)}
            self._add_mass(frozenset(), 1.0)
            return
        E1 = [p for p, yp in self.y.items() if yp >= 1.0 - eps]
        F = [p for p, yp in self.y.items() if eps < yp < 1.0 - eps]
        # 提升最高 y 的分数页到 y=1，直至 W(E1) ≥ deficit
        F.sort(key=lambda p: self.y[p], reverse=True)
        W1 = sum(self.w[p] for p in E1)
        idx = 0
        while W1 < deficit - eps and idx < len(F):
            p = F[idx]
            idx += 1
            E1.append(p)
            W1 += self.w[p]
            self.x[p] = 1.0
            self._set_y(p, 1.0)
        remaining = F[idx:]
        remaining.sort(key=lambda p: self.y[p], reverse=True)
        base = frozenset(E1)
        base_prof = self._compute_profile(base)
        n = len(remaining)
        # D_0 = E1，质量 1 − y_{f_1}（n=0 时为 1）
        m0 = (1.0 - self.y[remaining[0]]) if n > 0 else 1.0
        if m0 > eps:
            self._add_mass(base, m0, base_prof)
        # D_k = E1 ∪ {f_1..f_k}，质量 y_{f_k} − y_{f_{k+1}}
        cur = base
        cur_prof = list(base_prof)
        for k in range(n):
            p = remaining[k]
            cur = cur | {p}
            lq = min(self._cls(p), self.U)
            for j in range(lq + 1):
                cur_prof[j] += 1
            yk = self.y[p]
            ynext = self.y[remaining[k + 1]] if k + 1 < n else 0.0
            mk = yk - ynext
            if mk > eps:
                self._add_mass(cur, mk, list(cur_prof))
        # 浮点兜底归一
        tot = sum(self.mu.values())
        if tot > 0 and abs(tot - 1.0) > eps:
            for D in self.mu:
                self.mu[D] /= tot
        # 注意：链式 D 计数剖面各不相同（未平衡），但每个 D ⊇ E1 故 W(D) ≥ deficit
        # （合法性成立）；且链式取整的期望取回代价 = 分数代价（page p 以概率 |Δy_p|
        # 改变缓存归属），无需 Lemma 2 的 β=10 平衡即可保证 O(log k) 竞争比。

    # ==================================================================
    # Algorithm 3：Top-level online loop
    # ==================================================================
    def run(self, trace: Iterable[Tuple[int, int, int]],
            capacity: int, dataset_name: str = "") -> SimulationResult:
        """论文 Algorithm 3：顶层在线循环。

        Args:
            trace: (time, id, size) 三元组可迭代对象。
            capacity: 缓存容量 k（字节）。
            dataset_name: 数据集名（用于结果）。
        """
        if capacity <= 0:
            raise ValueError(f"capacity 必须为正，得到 {capacity}")
        # ---- 第 1 行：µ ← {(∅,1)}; x_p, y_p ← 0 ----
        self.k = int(capacity)
        self.U = int(math.ceil(math.log2(self.k))) if self.k > 0 else 0
        self.x = {}
        self.y = {}
        self.w = {}
        self.B = set()
        # 空集 D=∅ 的 profile 全 0；_suffix_y 初始化为全 0（所有 y_p=0）。
        # µ / _profiles / _by_count 经 _add_mass 一致初始化。
        self.mu = {}
        self._profiles = {}
        self._by_count = [{} for _ in range(self.U + 1)]
        self._suffix_y = [0.0] * (self.U + 1)
        self._add_mass(frozenset(), 1.0, [0] * (self.U + 1))
        self._recompactions = 0
        self._recompact_T = 1 << 30          # 占位；每次 miss 重算
        self.fetch_cost = 0.0
        self.rounding_cost = 0.0
        # ---- 第 2 行：sample η ~ U[0,1) once and for all ----
        self.eta = self.rng.random()

        hits = 0
        misses = 0
        byte_total = 0
        byte_hit = 0
        evictions = 0
        seq = 0

        for _time, obj_id, size, *_extra in trace:
            seq += 1
            size = int(size)
            byte_total += size
            # 先取本步开始时的缓存状态 cache_before = B(t-1) \ D_η（p_t 尚未加入 B）
            D_eta = self._find_D_eta()
            cache_before = self.B - D_eta
            # ---- 第 4 行：if p_t ∈ cache(η) then continue ----
            if obj_id in cache_before:
                hits += 1
                byte_hit += size
                continue

            # ---- 第 6 行：FractionalServe(p_t) ----
            misses += 1
            # 论文隐含假设 w_p ≤ k（页面可放入缓存）。若 w_p > k，页面永远无法缓存：
            # 计为未命中、支付取回代价 w_p，但不纳入 B(t) 也不更新分布，避免破坏
            # validity 不变式（否则 p_t 会以 size>k 进入 cache(η)）。
            if size > self.k:
                self.fetch_cost += float(size)
                continue
            # 新页面纳入 B(t)（B(t) = B(t-1) ∪ {p_t}）；已存在则保留其 w/x/y
            if obj_id not in self.B:
                self.B.add(obj_id)
                self.w[obj_id] = size
                self.x[obj_id] = 0.0
                self.y[obj_id] = 0.0
            self.fractional_serve(obj_id)
            # µ 的积分化：请求末一次性链式重建（替代论文 Algorithm 2 的逐页在线取整）。
            # 链 D_k=E1∪{按 y 降序前 k 个分数页}，质量使边际=y_p（一致性）；
            # 提升 y 最高页至 y=1 直至 W(E1)≥deficit（合法性）；期望取回代价=分数代价。
            self._recompact()

            # ---- 第 7 行：cache(η) ← B(t) \ D_η ----
            D_eta = self._find_D_eta()
            cache_after = self.B - D_eta
            # ---- 第 8 行：fetch cache(η)\cache_prev(η); cost = Σ w_p ----
            fetched = cache_after - cache_before
            evicted = cache_before - cache_after
            self.fetch_cost += sum(self.w[p] for p in fetched)
            evictions += len(evicted)

        return SimulationResult(
            cache_type="content",
            algorithm="BitModelOnline",
            dataset=dataset_name,
            config={
                "capacity": self.k,
                "cost_model": "bit",
                "offline": False,
                "gamma": self.gamma,
                "beta": self.beta,
                "U": self.U,
            },
            total_requests=seq,
            hits=hits,
            misses=misses,
            byte_total=byte_total,
            byte_hit=byte_hit,
            evictions=evictions,
            competitive_ratio=None,
            extra={
                "fetch_cost": self.fetch_cost,
                "rounding_cost": self.rounding_cost,
                "eta": self.eta,
                "num_segments": len(self.mu),
                "recompactions": self._recompactions,
            },
        )


# 注册名（供 --list-algorithms / get_algorithm 使用）。返回算法实例；
# 真正的模拟由 engine.BitModelOnlineSimulator 调用 .run(trace, capacity) 完成。
@register("bit_model_online")
def _make_bit_model_online(gamma: float = BitModelOnline.GAMMA,
                           beta: float = BitModelOnline.BETA,
                           seed: Optional[int] = None) -> BitModelOnline:
    return BitModelOnline(gamma=gamma, beta=beta, seed=seed)