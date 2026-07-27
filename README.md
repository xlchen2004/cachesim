# CacheSim — 对象级缓存模拟框架

缓存模拟器，通过回放请求 trace 来模拟多种缓存驱逐策略，并以此框架为基础实验新算法。



## 快速开始

### 环境要求

- Python 3.10+


### 基本用法

#### 查看已注册的算法

```bash
python -m cache_sim --list-algorithms
```

#### 单次模拟

```bash
# 使用文件 trace 运行 LRU 算法
python -m cache_sim --algorithm lru --dataset traces/twitter29_test10.csv --capacity 10000

# 使用内置数据集名
python -m cache_sim --algorithm lru --dataset wiki2018 --capacity 10000

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

#### 合成 Trace

```bash
# 合成 basic_trace 
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
| `--dataset` | `-d` | str | 文件路径 / 数据集名（`twitter29` / `twitter45` / `wiki2018`）/ `synthetic` | 无（必填） | 数据集来源；`synthetic` 表示使用合成数据集 |
| `--capacity` | — | int | 正整数（字节） | 无（必填） | 对象级缓存总容量；≤0 会抛 `ValueError` |
| `--cost-model` | — | str | `bit` / `fault` / `general` | `bit` | 成本模型：`bit`=按字节（cost=size）、`fault`=每次未命中代价为 1、`general`=预留（cost=size） |
| `--output` | `-o` | str | 文件路径（`.json` 或 `.csv`） | 无 | 报告输出路径，按后缀决定输出格式 |
| `--seed` | — | int | 任意整数 | 无 | 随机种子，用于复现（合成 trace 与随机算法） |
| `--competitive` | — | flag | — | 开启 | 运行 Belady 基线并计算竞争比；用 --no-competitive 关闭 |
| `--no-integrity-check` | — | flag | — | 关闭 | 跳过启动时对文件 trace 的完整性检查 |
| `--num-pages` | — | int | 正整数 | 100 | 合成数据集对象数（仅 `--dataset synthetic` 生效）；≤0 会抛 `ValueError` |
| `--length` | — | int | 非负整数 | 1000 | 合成数据集请求序列长度；<0 会抛 `ValueError`，0 返回空 trace |
| `--size-range` | — | int×2 | `[min, max]`，min ≤ max | `[1, 1000]` | 合成对象大小范围（字节），用于 `randint` 采样 |
| `--list-algorithms` | — | flag | — | 关闭 | 列出所有已注册算法并退出 |



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

## 运行结果


测试配置：

| 数据集 | 请求总数 | 不同对象数 |对象大小范围 | 总字节数 | 缓存大小 |
|--------|---------|---------|--------|---------|--------|
| synthetic_test.csv | 105181 | 1000 | [1, 74] | 161753 | 500 |
| twitter29_test10.csv | 9566 | 5716 | [35, 49465] | 5067120 | 10000 |
| twitter45_test.csv | 10000 | 9320 | [1, 1014] | 500505 | 10000 |
| wiki2018_test10.csv | 10000 | 6504 | [89,12542746] | 380700557 | 15000000 |


> **竞争比口径说明**：LRU / Belady 的竞争比为**未命中次数比**（online_misses / belady_misses），`bit_model_online` 的竞争比为**字节代价比**（fetch_cost / belady 字节未命中量），两者口径不同、不可直接横向比较；Belady 为离线最优基准（竞争比恒为 1.0），且其并非 bit 模型的最优离线解，故 bit 的代价比相对真实 OPT 被低估。`fetch_cost` 仅 `bit_model_online` 输出（“-”表示不适用）。

### synthetic_test.csv（capacity=500）

| 算法 | 命中 | 未命中 | OHR | 字节命中 | BHR | 驱逐 | fetch_cost | 竞争比 |
|------|------|--------|------|---------|-----|------|-----------|--------|
| lru | 71392 | 33789 | 0.6788 | 97323 | 0.6017 | 33524 | - | 1.9864 |
| belady | 88171 | 17010 | 0.8383 | 128513 | 0.7945 | 16726 | - | 1.0000 |
| bit_model_online | 57990 | 47191 | 0.5513 | 79414 | 0.4910 | 96304 | 182878 | 5.5017 |

### twitter29_test10.csv（capacity=10000）

| 算法 | 命中 | 未命中 | OHR | 字节命中 | BHR | 驱逐 | fetch_cost | 竞争比 |
|------|------|--------|------|---------|-----|------|-----------|--------|
| lru | 1116 | 8450 | 0.1167 | 454973 | 0.0898 | 8427 | - | 1.2305 |
| belady | 2699 | 6867 | 0.2821 | 929022 | 0.1833 | 6846 | - | 1.0000 |
| bit_model_online | 673 | 8893 | 0.0704 | 381514 | 0.0753 | 8915 | 4705982 | 1.1372 |

### twitter45_test.csv（capacity=10000）

| 算法 | 命中 | 未命中 | OHR | 字节命中 | BHR | 驱逐 | fetch_cost | 竞争比 |
|------|------|--------|------|---------|-----|------|-----------|--------|
| lru | 188 | 9812 | 0.0188 | 18183 | 0.0363 | 9582 | - | 1.0469 |
| belady | 628 | 9372 | 0.0628 | 62316 | 0.1245 | 9132 | - | 1.0000 |
| bit_model_online | 164 | 9836 | 0.0164 | 16282 | 0.0325 | 9638 | 484223 | 1.1051 |

### wiki2018_test10.csv（capacity=15000000）

| 算法 | 命中 | 未命中 | OHR | 字节命中 | BHR | 驱逐 | fetch_cost | 竞争比 |
|------|------|--------|------|---------|-----|------|-----------|--------|
| lru | 1962 | 8038 | 0.1962 | 4738203 | 0.0124 | 7618 | - | 1.2120 |
| belady | 3368 | 6632 | 0.3368 | 11691491 | 0.0307 | 6317 | - | 1.0000 |
| bit_model_online | 977 | 9023 | 0.0977 | 2427325 | 0.0064 | 9363 | 416030328 | 1.1274 |

### 结果分析

- **Belady** 作为离线最优基准，在所有数据集上命中率（OHR/BHR）均最高，符合预期。
- **LRU** 作为在线基线，在真实 trace（twitter29/45、wiki）上未命中次数竞争比约为 1.05–1.23，表现稳健。
- **bit_model_online** 在三个真实 trace 上字节代价竞争比为 **1.11–1.14**，接近 Belady 基准，符合其 O(log k) 量级的理论竞争比保证。需注意该算法以**字节取回代价**为优化目标而非命中次数，且其缓存状态分布更新会引入额外取回，故各 trace 上对象命中率（OHR）普遍低于 LRU。
- 在 **synthetic_test** 上（对象大小几乎全为 1 字节、缓存小、驱逐频繁），bit_model_online 的额外取回开销被放大，fetch_cost 甚至高于 LRU 的字节未命中量，字节代价竞争比高达 5.50——该算法的优势在均匀微小对象的高频驱逐场景下无法体现。
- twitter45_test 的请求中约 93% 为唯一对象，时序局部性极弱，故各算法命中率整体偏低，属 trace 本身特性。

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
