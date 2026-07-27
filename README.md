# CacheSim — 对象级缓存模拟框架

对象级缓存（Content Cache）模拟器，通过回放请求 trace 来模拟多种缓存驱逐策略，并以此框架为基础实验新算法。

## 项目结构

```
cachesim/
├── cache_sim/                   # 主包
│   ├── __init__.py              # 版本信息
│   ├── __main__.py              # 入口: python -m cache_sim
│   ├── core/                    # 核心抽象
│   │   ├── models.py            # ContentCache 缓存模型、SimulationResult 结果模型
│   │   └── policy.py            # EvictionPolicy 驱逐策略抽象基类、AccessContext
│   ├── algorithms/              # 驱逐算法实现
│   │   ├── registry.py          # 算法注册机制 (@register / get_algorithm)
│   │   ├── lru.py               # LRU (Least Recently Used)
│   │   ├── lfu.py               # LFU (Least Frequently Used)
│   │   ├── fifo.py              # FIFO (First In First Out)
│   │   ├── random_evict.py      # Random 随机驱逐
│   │   ├── randomized_marking.py # Randomized Marking (Fiat et al.)
│   │   ├── belady.py            # Belady 最优离线算法
│   │   └── bit_model_online.py  # Learning-Augmented Bit-Model Caching (论文实现)
│   ├── engine/                  # 模拟引擎
│   │   ├── simulator.py         # ContentSimulator、BitModelOnlineSimulator、竞争比计算
│   │   └── experiment.py        # ExperimentRunner 批量实验编排
│   ├── traceparser/             # Trace 解析与生成
│   │   ├── reader.py            # ContentTraceReader 流式读取器 + 完整性检查
│   │   ├── loader.py            # 数据集定位与注册
│   │   ├── tracegenerator.py    # SyntheticGenerator 合成 trace 生成器
│   │   └── basic_trace.py       # basic_trace.cc 的 Python 复现 (Pareto/Bounded-Pareto)
│   ├── config/                  # 实验配置
│   │   ├── schema.py            # 配置数据类 (AlgorithmConfig, DatasetConfig, ExperimentConfig)
│   │   └── loader.py            # JSON/YAML 配置加载器
│   ├── metrics/                 # 报告生成
│   │   └── report.py            # JSON/CSV 输出 + 控制台摘要
│   └── cli/                     # 命令行入口
│       └── main.py              # argparse CLI (模拟 / gen-trace / check-trace)
├── traces/                      # Trace 数据文件目录
├── 项目设计.md                   # 项目设计文档
└── README.md
```

## 快速开始

### 环境要求

- Python 3.10+


### 基本用法

#### 查看已注册的算法

```bash
python -m cache_sim --list-algorithms
```

输出: `lru`, `lfu`, `fifo`, `random`, `randomized_marking`, `belady`, `bit_model_online`

#### 单次模拟

```bash
# 使用文件 trace 运行 LRU 算法
python -m cache_sim --algorithm lru --dataset traces/twitter29_test10.csv --capacity 10000

# 使用合成数据集
python -m cache_sim --algorithm lru --dataset synthetic --capacity 5000 \
    --num-pages 200 --length 5000 --seed 42

# 计算竞争比 (与 Belady 最优对比)
python -m cache_sim --algorithm lru --dataset traces/twitter29_test10.csv \
    --capacity 10000 --competitive

# 输出到 JSON 文件
python -m cache_sim --algorithm lru --dataset traces/twitter29_test10.csv \
    --capacity 10000 --output results/lru_result.json
```

#### 生成 Trace

```bash
# 生成 basic_trace (Pareto 流行度 + Bounded-Pareto 对象大小)
python -m cache_sim gen-trace --num-objects 1000 --popular-requests 10000 --pareto-shape 1.8 --min-size 1 --max-size 10000 -o traces/my_trace.tr --seed 42
```

#### Trace 完整性检查

```bash
python -m cache_sim check-trace traces/twitter29_test10.csv
```

### 批量实验

创建配置文件 `experiment.json`:

```json
{
  "algorithms": [
    {"name": "lru"},
    {"name": "fifo"},
    {"name": "lfu"}
  ],
  "datasets": [
    {
      "name": "twitter29_test10",
      "source": "traces/twitter29_test10.csv",
      "cost_model": "bit"
    }
  ],
  "cache_sizes": [5000, 10000, 50000],
  "repeats": 3,
  "output_dir": "results",
  "output_prefix": "experiment",
  "competitive": true
}
```

运行:

```bash
python -m cache_sim --config experiment.json
```

输出文件:
- `results/experiment.json` — 完整结果 (含配置、extra 字段)
- `results/experiment.csv` — 表格数据 (便于导入 Excel/Pandas)

## ALL Usage


### 1. 模拟模式

```bash
python -m cache_sim [options]            # 单次模拟
```

| 参数 | 短选项 | 类型 | 取值 / 范围 | 默认值 | 说明 |
|------|--------|------|-------------|--------|------|
| `--config` | `-c` | str | 文件路径（YAML/JSON） | 无 | 批量实验配置文件路径，指定后按配置运行 |
| `--algorithm` | `-a` | str | `lru` / `lfu` / `fifo` / `random` / `randomized_marking` / `belady` / `bit_model_online` | 无（必填） | 驱逐算法注册名（见 [算法说明](#算法说明)） |
| `--dataset` | `-d` | str | 文件路径 / 数据集名（`twitter29` / `twitter45`）/ `synthetic` | 无（必填） | 数据集来源；`synthetic` 表示使用合成生成器 |
| `--capacity` | — | int | 正整数（字节） | 无（必填） | 对象级缓存总容量；≤0 会抛 `ValueError` |
| `--cost-model` | — | str | `bit` / `fault` / `general` | `bit` | 成本模型：`bit`=按字节（cost=size）、`fault`=每次未命中代价为 1、`general`=预留（cost=size） |
| `--output` | `-o` | str | 文件路径（`.json` 或 `.csv`） | 无 | 报告输出路径，按后缀决定输出格式 |
| `--seed` | — | int | 任意整数 | 无 | 随机种子，用于复现（合成 trace 与随机算法） |
| `--competitive` | — | flag | — | **开启** | 运行 Belady 基线并计算竞争比；用 --no-competitive 关闭 |
| `--no-integrity-check` | — | flag | — | 关闭 | 跳过启动时对文件 trace 的完整性检查 |
| `--num-pages` | — | int | 正整数 | 100 | 合成数据集对象数（仅 `--dataset synthetic` 生效）；≤0 会抛 `ValueError` |
| `--length` | — | int | 非负整数 | 1000 | 合成数据集请求序列长度；<0 会抛 `ValueError`，0 返回空 trace |
| `--size-range` | — | int×2 | `[min, max]`，min ≤ max | `[1, 1000]` | 合成对象大小范围（字节），用于 `randint` 采样 |
| `--list-algorithms` | — | flag | — | 关闭 | 列出所有已注册算法并退出 |

> 单次模拟模式必须同时给出 `--algorithm` 与 `--dataset`，并需指定 `--capacity`（对象级缓存必填）。
> `--config` 与 `--algorithm` 互斥：给定 `--config` 走批量实验，给定 `--algorithm` 走单次模拟，两者均无则打印帮助。
> 内置数据集名映射：`twitter29` → `traces/twitter29_test10.csv`、`twitter45` → `traces/twitter45_test.csv`（均优先使用切分出的小样本，而非 GB 级原始文件 `twitter29_all.csv` / `twitter45.csv`）。

### 2. 生成trace

```bash
python -m cache_sim gen-trace [options] -o <output>
```

生成 basic_trace（Pareto 流行度 + Bounded-Pareto 对象大小）。

| 参数 | 短选项 | 类型 | 取值 / 范围 | 默认值 | 说明 |
|------|--------|------|-------------|--------|------|
| `--num-objects` | — | int | 正整数 | 1000 | 不同对象数量 `no_objs` |
| `--popular-requests` | — | int | 正整数 | 10000 | 重复计数 / 时间上界 `reps`；最热门对象（i=0，速率 1）约产生此次数请求，总请求数为其 H_{no_objs,0.9} 倍 |
| `--pareto-shape` | — | float | > 0 | 1.8 | Bounded-Pareto 大小形状参数 α（越大对象越偏小） |
| `--min-size` | — | int | ≥ 1 | 1 | 对象大小下界  |
| `--max-size` | — | int | ≥ min-size | 10000 | 对象大小上界  |
| `--output` | `-o` | str | 文件路径 | —（必填） | 输出 trace 文件路径 |
| `--seed` | — | int | 任意整数 | 无 | 随机种子 |

### 3. 检查trace

```bash
python -m cache_sim check-trace <path> [--max-lines N]
```

对 trace 做完整性检查并打印统计（请求数、唯一对象数、总字节、大小范围、extra 列数）。

| 参数 | 类型 | 取值 / 范围 | 默认值 | 说明 |
|------|------|-------------|--------|------|
| `path`（位置参数） | str | 文件路径 | —（必填） | 待检查的 trace 文件路径 |
| `--max-lines` | int | 非负整数 | 0 | 最多检查的行数；`0` 表示全量检查 |

## Trace 数据格式

 trace 数据集需组织为空格分隔的格式，每行一条请求格式如下:

```
time id size [extra...]
```

| 列 | 类型 | 说明 |
|----|------|------|
| time | long long int | 逻辑时间戳（当前未使用，留待 TTL） |
| id | long long int | 对象唯一标识 |
| size | uint32 | 对象大小（字节） |
| extra | uint16 (可选) | 分类特征，可多列，预留 |

示例:
```
0 1 45
0 2 510
0 3 35
1 2 510
1 4 233
```

## 算法说明

| 算法 | 类型 | 注册名 | 说明 |
|------|------|--------|------|
| LRU | 在线 | `lru` | 驱逐最近最少访问的项 |
| LFU | 在线 | `lfu` | 驱逐访问频次最低的项（平局按 LRU） |
| FIFO | 在线 | `fifo` | 驱逐最先加入的项 |
| Random | 在线 | `random` | 随机驱逐 |
| Randomized Marking | 在线 | `randomized_marking` | 随机化标记算法（2Hₖ 竞争比） |
| Belady | 离线 | `belady` | 驱逐下次使用最远的项（最优离线基准） |
| Bit-Model Online | 在线 | `bit_model_online` | Learning-Augmented 论文算法（维护缓存状态分布 µ） |

### 模型

- `bit` (默认): cost = size（按字节计代价）
- `fault`: cost = 1（每次未命中代价相同）
- `general`: cost = size（预留扩展）

## 输出指标

| 指标 | 说明 |
|------|------|
| total_requests | 请求总数 |
| hits / misses | 命中 / 未命中次数 |
| OHR (hit_rate) | 对象命中率 = hits / total_requests |
| byte_total / byte_hit | 字节总流量 / 命中字节数 |
| BHR | 字节命中率 = byte_hit / byte_total |
| evictions | 驱逐次数 |
| competitive_ratio | 竞争比 = online_misses / belady_misses |
| fetch_cost | Bit-Model 取回代价（仅 bit_model_online） |

## 运行验证结果

以下是在 `traces/twitter29_test10.csv` (9566 条请求, 5716 个对象, 总字节 5,067,120) 上的测试结果:

| algorithm | k | OHR | BHR | CR |
|-----------|------|------|------|------|
| Belady | 10000 | 0.2793 | 0.1823 | 1.000 |
| LFU | 10000 | 0.1304 | 0.0832 | 1.207 |
| LRU | 10000 | 0.1166 | 0.0898 | 1.226 |
| FIFO | 10000 | 0.1111 | 0.0865 | 1.233 |
| RandomizedMarking | 10000 | 0.1092 | 0.0877 | — |
| Random | 10000 | 0.1055 | 0.0823 | — |
| LRU | 5000 | 0.0771 | 0.0573 | 1.161 |
| FIFO | 5000 | 0.0751 | 0.0561 | 1.164 |


## 扩展新算法

实现 `EvictionPolicy` 子类并用 `@register("name")` 注册:

```python
from cache_sim.core.policy import EvictionPolicy
from cache_sim.algorithms.registry import register

@register("my_algo")
class MyAlgorithm(EvictionPolicy):
    def __init__(self):
        super().__init__("MyAlgo")
        self._data = {}

    def on_hit(self, key, ctx):
        self._data[key] = ctx.time

    def on_admit(self, key, ctx):
        self._data[key] = ctx.time

    def on_evict(self, key):
        self._data.pop(key, None)

    def select_victim(self, candidates, ctx):
        return min(candidates, key=lambda k: self._data.get(k, 0))

    def reset(self):
        self._data.clear()
```

然后在 `cache_sim/algorithms/__init__.py` 中添加导入:

```python
import cache_sim.algorithms.my_algo  # noqa: F401
```

## License

本项目仅供研究与学习使用。
