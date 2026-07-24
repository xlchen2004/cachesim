"""Learning-Augmented Bit-Model Caching -- 论文三个算法的实现。

Bit Model（cost = size = w_p）
与项目中已有的 ``fractional`` / ``bit_rounding``（启发式舍入）不同，本模块维护
论文所述的 **缓存状态分布 µ**：µ 是一组 (D, m) 对，D 为“被驱逐页面集合”，m 为概率
质量（Σ m = 1）。物理缓存为 ``B(t) \\ D_η``，其中 η 是一次性采样的均匀随机数，
D_η 是 µ 中包含 η 的那个区间对应的集合 D。驱逐通过对分布做 RoundIncrease /
RoundDecrease 完成，而非一次驱逐一个页面--因此本算法不兼容
``EvictionPolicy.select_victim`` 接口，而是自带顶层循环（Algorithm 3）。

常量（论文 2.4 节 "Global state and invariants"）：
  - γ = 3（Bit 模型），y_p = min(1, γ·x_p)。
  - β = 10（舍入代价因子，Lemma 2）。
  - U = ⌈log₂ k⌉（最大 size class 上界）。
  - size class S(i) = {p : 2ⁱ ≤ w_p < 2ⁱ⁺¹}，cls(p) = ⌊log₂ w_p⌋。
  - Bit 模型下 c_p = w_p。

代价记账（重要）：Algorithm 2 中 “pay m·w_p / m̂·w_q” 是 Lemma 2 分析所用的
**期望舍入代价**（对 η 取期望），本实现单独记入 ``rounding_cost`` 供诊断。
真正上报的 bit-model 取回代价按 Algorithm 3 第 8 行，由 cache(η) 状态差
``cache_after \\ cache_before`` 计算（对单次 η 的实现代价）。

对论文伪代码中三处不可避免的歧义，本实现采取以下解读（代码内对应位置均有注释）：
  1. Algorithm 2 的 RoundDecrease 标注 “repair bottom-up”--实现为与 RoundIncrease
     相同的自顶向下修复（ℓ ← i down to 0）。因为移动一个 class-ℓ 页面会影响所有
     level ≤ ℓ 的计数，自底向上修复会破坏归纳（修复 ℓ 时已修复的 < ℓ 层被扰动）。
     自顶向下是唯一使归纳成立的修复方向。
  2. Algorithm 1 第 2 行 “x_{p_t}←0; y_{p_t}←0 ▷ reset on hit”--当旧 y_{p_t} > 0
     时，需先调用 RoundDecrease(p_t, 旧 y_{p_t}) 将 p_t 从分布中移除，否则一致性
     不变式 Σ_{D∋p} m(D)=y_p 会被破坏（分布仍驱逐 p_t 而 y_{p_t}=0）。
  3. “η-order” / “lexicographically-first η-segments” 解读为 [0,1) 上的位置序
     （即 µ 列表序）；η 这个点仅用于选定 D_η。
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
        # µ：有序 (D, m) 段列表，按 [0,1) 位置序排列；D 为被驱逐页面集合（set），m 为质量
        self.mu: List[List] = []
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
        """Σ_{i'≥ℓ} Σ_{q∈S(i')} y_q：class ≥ ℓ 的所有页面的 y 之和。"""
        return sum(yp for p, yp in self.y.items() if self._cls(p) >= ell)

    def _count_cls_ge(self, D: Set, ell: int) -> int:
        """#{q ∈ D : cls(q) ≥ ℓ}。"""
        return sum(1 for q in D if self._cls(q) >= ell)

    def _find_D_eta(self) -> Set:
        """返回 µ 中包含 η 的那个段的 D（D_η）。按累积质量扫描。"""
        acc = 0.0
        for D, m in self.mu:
            if m <= 0:
                continue
            if acc <= self.eta < acc + m:
                return D
            acc += m
        # 兜底：浮点漂移或 η 落在末尾，取最后一个非零段
        for D, m in reversed(self.mu):
            if m > 0:
                return D
        return self.mu[0][0]

    def _merge_adjacent(self) -> None:
        """合并相邻且 D 相同的段（保持分布与所有不变式，抑制段数膨胀）。"""
        if not self.mu:
            return
        merged: List[List] = []
        for D, m in self.mu:
            if m <= self._eps:
                continue
            if merged and merged[-1][0] is D:
                merged[-1][1] += m
            elif merged and merged[-1][0] == D:
                merged[-1][1] += m
            else:
                merged.append([D, m])
        if not merged:
            merged = [[set(), 1.0]]
        self.mu = merged

    # ==================================================================
    # Algorithm 1：Fractional primal–dual update（closed-form）
    # ==================================================================
    def fractional_serve(self, p_t) -> None:
        """论文 Algorithm 1：FractionalServe(p_t)。

        重置 p_t 的分数变量并把 p_t“请回”缓存分布；随后循环增大共享对偶 ∆y，直到
        活动集 S 的 knapsack-cover 约束被满足或 S 可装入缓存。
        """
        # ---- 第 2 行：x_{p_t}←0; y_{p_t}←0 （reset on re-request） ----
        # 歧义处理 2：先把 p_t 从分布中移除以维持一致性不变式。 
        old_y = self.y.get(p_t, 0.0)
        if old_y > self._eps:
            self.round_decrease(p_t, old_y)
        self.x[p_t] = 0.0
        self.y[p_t] = 0.0

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
                # 第 18–21 行：分发 RoundIncrease / RoundDecrease
                if y_new > self.y[p] + self._eps:
                    self.round_increase(p, y_new - self.y[p])
                elif y_new < self.y[p] - self._eps:
                    self.round_decrease(p, self.y[p] - y_new)
                # 第 22 行：x_p ← x_new; y_p ← y_new
                self.x[p] = x_new
                self.y[p] = y_new

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
        i = self._cls(p)
        wp = self.w[p]
        # ---- 第 2–5 行：T ← 位置序中前 ε 质量、p∉D 的段；对每段把 p 加入 D ----
        plan: List[Tuple[int, float]] = []  # (段索引, 取走的质量)
        remaining = eps
        for j, (D, m) in enumerate(self.mu):
            if remaining <= self._eps:
                break
            if p in D:
                continue
            take = min(remaining, m)
            if take <= self._eps:
                continue
            plan.append((j, take))
            remaining -= take
        # 逆序应用以保持较前段的索引不变
        for j, take in reversed(plan):
            D, m = self.mu[j]
            if take >= m - self._eps:
                # 整段取走：D ← D ∪ {p}（原地修改，第 4 行 evictp；pay m·w_p）
                D.add(p)
                self.rounding_cost += take * float(wp)
            else:
                # 取左半 [c, c+take) 加入 p；右半 [c+take, c+m) 保持原 D
                right = set(D)           # 右半 = 原 D（不含 p）的副本
                D.add(p)                 # 左半沿用原 set，加入 p
                self.mu[j] = [D, take]
                self.mu.insert(j + 1, [right, m - take])
                self.rounding_cost += take * float(wp)  # 第 4 行：pay m·w_p

        # ---- 第 6–18 行：自顶向下修复（ℓ ← i down to 0） ----
        self._repair(i)

    def round_decrease(self, p, eps: float) -> None:
        """论文 Algorithm 2 第 20–21 行：RoundDecrease(p, ε)。

        对称：取位置序中前 ε 质量、p∈D 的段，从中移除 p；随后自顶向下修复。
        （歧义处理 1：与 RoundIncrease 相同的自顶向下修复方向。）
        """
        if eps <= self._eps:
            return
        i = self._cls(p)
        # 取位置序中前 ε 质量、p∈D 的段，移除 p
        plan: List[Tuple[int, float]] = []
        remaining = eps
        for j, (D, m) in enumerate(self.mu):
            if remaining <= self._eps:
                break
            if p not in D:
                continue
            take = min(remaining, m)
            if take <= self._eps:
                continue
            plan.append((j, take))
            remaining -= take
        for j, take in reversed(plan):
            D, m = self.mu[j]
            if take >= m - self._eps:
                D.discard(p)
            else:
                # 取左半 [c, c+take) 移除 p；右半 [c+take, c+m) 保持原 D（仍含 p）
                left = set(D)            # 左半 = 原 D 的副本
                left.discard(p)
                self.mu[j] = [left, take]
                self.mu.insert(j + 1, [D, m - take])  # 右半沿用原 set
        # RoundDecrease 的对称 “pay” 对应把 p 请回缓存（非 fetch 代价，不累加 fetch_cost）

        self._repair(i)

    def _repair(self, i: int) -> None:
        """论文 Algorithm 2 第 6–18 行的修复循环：ℓ ← i down to 0。

        对每个 level ℓ，s = ⌈Σ_{i'≥ℓ} y⌉；将 big（count=s+1）与 small（count=s−1）
        段配对，把一个 class-ℓ 页面从 big 移到 small，使两者都变为 s。
        """
        for ell in range(i, -1, -1):
            # 第 7 行：s ← ⌈Σ_{i'≥ℓ} y⌉
            s = math.ceil(self._suffix_y_sum(ell))
            # 第 10–17 行：while big 与 small 均非空
            while True:
                big = [j for j, (D, m) in enumerate(self.mu)
                       if m > self._eps and self._count_cls_ge(D, ell) == s + 1]
                small = [j for j, (D, m) in enumerate(self.mu)
                         if m > self._eps and self._count_cls_ge(D, ell) == s - 1]
                if not big or not small:
                    break
                # 第 11 行：按位置序（η-order）各取第一个
                jb = big[0]
                js = small[0]
                Db, mb = self.mu[jb]
                Ds, ms = self.mu[js]
                mhat = min(mb, ms)
                if mhat <= self._eps:
                    break
                # 第 13 行：q ← (D_b \ D_s) ∩ S(ℓ) 中最小 id 的页面（归纳保证存在）
                q = min((pg for pg in Db if pg not in Ds and self._cls(pg) == ell),
                        default=None)
                if q is None:
                    # 归纳前提不成立（理论上不应发生）--跳过避免死循环
                    break
                # 第 14–16 行：拆分并把 q 从 big 的 m̂ 部分移到 small 的 m̂ 部分
                # 保留左半 (D, m−m̂) 于原位，插入右半 (D, m̂) 于其后并修改之
                # 按索引递减顺序应用，避免插入造成索引错位
                ops = [(jb, "big"), (js, "small")]
                ops.sort(key=lambda t: -t[0])
                for idx, which in ops:
                    D, m = self.mu[idx]
                    right = set(D)            # 右半副本
                    if which == "big":
                        right.discard(q)      # 第 15 行：(D_b, m̂) ← (D_b\{q}, m̂)
                    else:
                        right.add(q)          # 第 16 行：(D_s, m̂) ← (D_s∪{q}, m̂)
                    self.mu[idx] = [D, m - mhat]
                    self.mu.insert(idx + 1, [right, mhat])
                # 第 16 行注释：pay m̂·w_q ≤ m̂·2^{ℓ+1}
                self.rounding_cost += mhat * float(self.w[q])
        # 清理零质量段并合并相邻同 D 的段
        self.mu = [[D, m] for D, m in self.mu if m > self._eps]
        self._merge_adjacent()

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
        self.mu = [[set(), 1.0]]
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
            # 新页面纳入 B(t)（B(t) = B(t-1) ∪ {p_t}）；已存在则保留其 w/x/y
            if obj_id not in self.B:
                self.B.add(obj_id)
                self.w[obj_id] = size
                self.x[obj_id] = 0.0
                self.y[obj_id] = 0.0
            self.fractional_serve(obj_id)

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
            },
        )


# 注册名（供 --list-algorithms / get_algorithm 使用）。返回算法实例；
# 真正的模拟由 engine.BitModelOnlineSimulator 调用 .run(trace, capacity) 完成。
@register("bit_model_online")
def _make_bit_model_online(gamma: float = BitModelOnline.GAMMA,
                           beta: float = BitModelOnline.BETA,
                           seed: Optional[int] = None) -> BitModelOnline:
    return BitModelOnline(gamma=gamma, beta=beta, seed=seed)