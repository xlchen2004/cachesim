"""``basic_trace`` 合成 trace 生成器——``basic_trace.cc`` 的忠实 Python 复现。

本模块是 ``cache_sim/traceparser/basic_trace.cc`` 的逐行 Python 移植，完整保留原 C++
实现的全部细节：Bounded-Pareto 对象大小（逆变换法）、基于指数到达间隔的非齐次
泊松过程请求序列（每对象速率 ``1/(i+1)^0.9``）、按时间排序、输出 ``1000*time id size``。

算法概要（对应原 C++ ``main``）
--------------------------------
1. 参数：``no_objs``（对象数）、``reps``（重复计数 / 时间上界）、``shape``
   （Bounded-Pareto 大小形状 α）、``lowerb``/``higherb``（大小上下界）、``outputname``。
2. 对象大小：对每个对象抽 ``us ~ Uniform(0,1)``（拒绝 0/1，且第一次抽取被丢弃以匹配
   原 C++ 的冗余抽取），``size = int(rbpareto(us, shape, lowerb, higherb))``（截断为整数，
   与 C++ ``long`` 赋值一致）。原 C++ 的内层 ``do-while`` 越界拒绝在数学上永不触发
   （``rbpareto`` 必落在 ``[l, h]``），此处原样保留。
3. 请求序列：对每个对象 ``i``，到达速率 ``rateH = 1/(i+1)^0.9``（指数 0.9 在原 C++ 中
   硬编码，与 ``shape`` 无关），``globalTime`` 从首个指数间隔开始累加，只要
   ``globalTime < reps`` 就产生一条请求 ``(globalTime, i)``。
4. 全部请求按 ``(globalTime, i)`` 字典序排序（等价于 C++ ``list.sort()``）。
5. 输出：每行 ``round(1000*globalTime) id size``（C++ ``fixed<<setprecision(0)`` 即四舍五入到整数）。

随机数
------
原 C++ 用 ``std::random_device`` 播种 ``std::mt19937``（非确定性，跨运行不可复现），
并通过 ``std::uniform_real_distribution`` / ``std::exponential_distribution`` 生成分布。
本实现用 Python 的 ``random.Random``（同为 MT19937 家族）作等价 RNG：

* 因原 C++ 用 ``random_device`` 播种，**两个版本跨运行都不产生相同输出**；
  本实现额外提供 ``seed`` 参数（默认 ``None``，等价于 ``random_device`` 的非确定性；
  传入整数则可复现，这是原 C++ 没有的便利）。
* 由于 C++ 标准库与 CPython 将 MT 输出适配为 ``double``/``long double`` 的算法不同，
  即使给定相同种子也无法做到逐比特一致；本实现忠实复现的是**算法、公式、控制流与输出格式**。
"""

import sys
from typing import List, Optional, Sequence, Tuple

__all__ = ["rbpareto", "generate_basic_trace", "main"]


def rbpareto(us: float, a: float, l: float, h: float) -> float:
    """逆变换法采样 Bounded-Pareto（与原 C++ ``rbpareto`` 完全一致）。

    Args:
        us: Uniform(0,1) 样本（须在 (0,1) 内）。
        a: 形状参数 α（>0）。
        l: 下界。
        h: 上界。

    Returns:
        落在 ``[l, h]`` 内的 Bounded-Pareto 样本。
    """
    #  return(pow((pow(l, a) / (us*pow((l/h), a) - us + 1)), (1.0/a)));
    return l / pow(1 + us * (pow(l / h, a) - 1), 1.0 / a)


def generate_basic_trace(
    no_objs: int,
    reps: int,
    shape: float,
    lowerb: float,
    higherb: float,
    output_path: Optional[str] = None,
    seed: Optional[int] = None,
    verbose: bool = True,
    popularity_exponent: float = 0.9,
) -> List[Tuple[int, int, int]]:
    """生成 ``basic_trace`` 对象级 trace（``basic_trace.cc`` 的忠实复现）。

    Args:
        no_objs: 不同对象数量（原 C++ ``no_objs``）。
        reps: 重复计数 / 时间上界（原 C++ ``reps``）；最热门对象（i=0，速率 1）
            约产生 ``reps`` 次请求，总请求数为其 ``H_{no_objs, 0.9}`` 倍。
        shape: Bounded-Pareto 大小形状参数 α（原 C++ ``shape``）。
        lowerb: 对象大小下界（原 C++ ``lowerb``）。
        higherb: 对象大小上界（原 C++ ``higherb``）。
        output_path: 输出 trace 文件路径；给定则按 ``time id size`` 每行一条写入
            （与原 C++ 一致）。原 C++ 总是写文件；此处为可选以便内存内使用。
        seed: 随机种子；``None``（默认）等价于原 C++ 的 ``random_device`` 非确定性。
        verbose: 是否向 stderr 打印原 C++ 的进度日志。
        popularity_exponent: 请求到达速率指数（原 C++ 硬编码 0.9）；仅作可调钩子保留，
            默认与原 C++ 一致。

    Returns:
        生成的请求列表 ``[(time, id, size), ...]``，按时间升序。``time`` 为
        ``round(1000*globalTime)`` 的整数。
    """
    import random

    rng = random.Random(seed)  # None -> OS 熵（等价 random_device）；MT19937 家族

    # ---- 对象大小 ----
    size: List[int] = [0] * no_objs
    mean_size = 0.0
    for i in range(no_objs):
        us = rng.random()  # 原 C++ 第一次抽取（丢弃）
        while True:
            us = rng.random()  # 抽取直到 us != 0 且 us != 1
            if us != 0.0 and us != 1.0:
                break
        # 原 C++ 内层 do-while：用同一 us 重算并检查越界（数学上永不触发，原样保留）
        while True:
            size_i = int(rbpareto(us, shape, lowerb, higherb))  # 截断为整数（C++ long 赋值）
            if not (size_i < lowerb or size_i > higherb):
                break
        size[i] = size_i
        mean_size += size_i

    if verbose:
        denom = float(no_objs) if no_objs else 1.0
        sys.stderr.write(f"finished sizes. mean_size: {mean_size / denom}\n")

    # ---- 请求序列：每对象一个指数到达间隔的非齐次泊松过程 ----
    reqseq: List[Tuple[float, int]] = []
    for i in range(no_objs):
        rateH = 1.0 / (pow(i + 1, popularity_exponent))  # 原 C++：1/(pow(i+1,0.9))
        globalTime = rng.expovariate(rateH)  # 首个到达间隔
        while globalTime < reps:
            reqseq.append((globalTime, i))
            globalTime += rng.expovariate(rateH)  # 累加下一个间隔

    if verbose:
        sys.stderr.write("finished raw req sequence.\n")

    # 按时间（再按 id）排序，等价于 C++ list<tuple> 的字典序 sort
    reqseq.sort()
    if verbose:
        sys.stderr.write("finished sorting req.\n")

    # ---- 输出 ----
    records: List[Tuple[int, int, int]] = []
    f = open(output_path, "w", encoding="utf-8") if output_path is not None else None
    try:
        for globalTime, i in reqseq:
            # 原 C++：outfile << 1000*get<0>(*rit) << " " << get<1>(*rit) << " " << size[...]
            # fixed<<setprecision(0) -> 四舍五入到整数
            t = int(round(1000.0 * globalTime))
            if f is not None:
                f.write(f"{t} {i} {size[i]}\n")
            records.append((t, i, size[i]))
    finally:
        if f is not None:
            f.close()

    if verbose:
        sys.stderr.write("finished output.\n")

    return records


def main(argv: Sequence[str]) -> int:
    """
    用法::

        python -m cache_sim.traceparser.basic_trace \\
            number_of_objects repetition_count pareto_shape \\
            lower_pareto_bound higher_pareto_bound outputname
    """
    if len(argv) != 6:
        sys.stderr.write(
            "\n number_of_objects repetition_count pareto_shape "
            "lower_pareto_bound higher_pareto_bound outputname\n")
        return 1
    no_objs = int(argv[0])   # atoi
    reps = int(argv[1])      # atoi
    shape = float(argv[2])   # atof
    lowerb = float(argv[3])  # atof
    higherb = float(argv[4])  # atof
    outputname = argv[5]
    generate_basic_trace(no_objs, reps, shape, lowerb, higherb,
                         output_path=outputname, seed=None, verbose=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
